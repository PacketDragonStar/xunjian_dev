"""巡检执行器 - 支持多线程并发、返回差异化报告"""
import logging
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from netmiko import ConnectHandler

from django.db import close_old_connections
from django.db.models import Q
from django.db.utils import OperationalError
from app02.models import (
    NewDevice, CheckItem, CheckSet, CheckResult,
    AnomalyRecord, XunjianRecord, XunjianTask, DeviceParseResult, InspectionGap
)
from app02.engine.pipeline import run_check_item
from app02.engine.capability import ensure_capabilities, PROBE_COMMAND
from app02.parsers import SCHEMA_VERSION
from app02.engine.reporter import (
    XunjianReport, DeviceReport, CheckItemReport,
    extract_diff_summary, render_cli_report
)

logger = logging.getLogger(__name__)


def _normalize_device_type(device_type: str) -> str:
    """兼容历史设备类型命名，转换为 netmiko 可识别值"""
    dt = (device_type or '').strip().lower()
    if not dt:
        return 'huawei'
    # H3C/comware 设备
    if 'h3c' in dt or 'comware' in dt or 'hp_comware' in dt:
        return 'hp_comware'
    # 华为
    if 'huawei' in dt:
        return 'huawei'
    # 华为 VRPv8（NE系列）
    if 'vrpv8' in dt:
        return 'huawei_vrpv8'
    # cisco（v2 不做，回退到 hp_comware）
    if 'cisco' in dt or 'ios' in dt or 'nxos' in dt:
        return 'hp_comware'
    return dt


# ═══════════════════════════════════════════════════════════
# 落库辅助（带 OperationalError 重试，避免 MySQL 连接超时导致整条设备巡检中断）
# ═══════════════════════════════════════════════════════════

def _db_create_with_retry(create_fn, max_retries=2):
    """执行 create_fn() 创建 DB 记录。

    OperationalError 时关闭旧连接并重试（最多 max_retries 次）。
    返回 True 表示创建成功，False 表示重试耗尽。
    非 OperationalError 异常向上传播。
    """
    for attempt in range(max_retries):
        try:
            create_fn()
            return True
        except OperationalError:
            if attempt < max_retries - 1:
                try:
                    close_old_connections()
                except Exception:
                    pass
    return False


def _safe_create_check_result(xunjian_time: str, device_name: str, command: str, result) -> bool:
    """写一条命令结果；遇 MySQL 连接超时会关闭旧连接重试一次。返回是否成功。"""
    result = result if isinstance(result, str) else (str(result) if result is not None else '')
    ok = _db_create_with_retry(
        lambda: CheckResult.objects.create(
            time=xunjian_time, device=device_name, command=command, result=result
        )
    )
    if not ok:
        logger.error(f'[{device_name}] CheckResult 落库失败({command})')
    return ok


def _safe_create_anomaly(xunjian_time: str, device_name: str, command: str,
                         notes: str, severity: str,
                         baseline_val: str = '', current_val: str = '') -> None:
    """写一条异常记录；遇 MySQL 连接超时重建连接重试一次。"""
    try:
        ok = _db_create_with_retry(
            lambda: AnomalyRecord.objects.create(
                time=xunjian_time, device=device_name, command=command,
                notes=(notes or '')[:190], confirm=False,
                baseline_val=(baseline_val or '')[:500],
                current_val=(current_val or '')[:500],
                severity=severity or 'P2',
            )
        )
        if not ok:
            logger.error(f'[{device_name}] AnomalyRecord 落库失败({command})')
    except Exception as e:
        logger.error(f'[{device_name}] AnomalyRecord 落库失败({command}): {e}')


def _get_items_for_device(device):
    """决定该设备执行哪些巡检项（v3 opt-in 能力感知门控）。

    - protocol_inspection 关（默认）→ 仅 base 基础项（opt-in 总开关，零风险、不发探针）。
    - protocol_inspection 开 → 基础项恒跑 + feature 项按 capabilities 门控：
        · caps 为非空列表 → 仅跑 base ∪ caps 中的 feature；
        · caps 为 None（开开关但未检测）或 []（已检测确无）→ 仅 base。
    - disabled_commands 反向裁剪保留。

    模块级函数：主循环与巡检结束的缺口审计共用，保证「应执行」口径一致。
    """
    if device.group:
        qs = device.group.check_items.filter(enabled=True)
        extra = device.extra or {}
        if extra.get('protocol_inspection'):
            caps = extra.get('capabilities', None)
            if caps:  # 非空列表 → 已知能力，按能力门控（feature 命令已全局链接所有组）
                qs = qs.filter(Q(feature='base') | Q(feature__in=caps))
            else:
                # 开关开了但从未检测(None)或已检测确无特性([]) → 仅基础项
                qs = qs.filter(feature='base')
        else:
            # opt-in 总开关关 → 仅基础项。feature 命令全局链接所有组，必须此处门控，
            # 否则所有设备都会无差别跑全部协议命令（spray+prune，正是 v3 要规避的）。
            qs = qs.filter(feature='base')
        disabled = extra.get('disabled_commands') or []
        if disabled:
            qs = qs.exclude(command__in=disabled)
        return qs
    return None


def _audit_missing_checks(xunjian_time: str, devices) -> int:
    """巡检结束审计：找出「应执行但未落库」的设备-命令对，写入 InspectionGap（埋点）。

    返回缺口项数。即使巡检正常也应运行——一旦未来再出现单项异常/连接中断，
    这里会精确记录是哪些设备、哪些命令没回显，方便追责。
    """
    try:
        gaps = []
        have_cache = {}
        for device in devices:
            items = _get_items_for_device(device)
            if not items:
                continue
            if device.name not in have_cache:
                have_cache[device.name] = set(
                    CheckResult.objects.filter(time=xunjian_time, device=device.name)
                    .values_list('command', flat=True)
                )
            have = have_cache[device.name]
            for it in items:
                if it.command not in have:
                    gaps.append(InspectionGap(
                        time=xunjian_time, device=device.name,
                        command=it.command,
                        note='执行结束仍未落库（单项异常/连接中断）'
                    ))
        if gaps:
            InspectionGap.objects.bulk_create(gaps, ignore_conflicts=True)
            logger.warning(f'[audit] 巡检 {xunjian_time} 发现 {len(gaps)} 个缺口项（已写入 InspectionGap）')
        return len(gaps)
    except Exception as e:
        logger.error(f'巡检缺口审计异常: {e}')
        return 0



# ═══════════════════════════════════════════════════════════
# 基线获取
# ═══════════════════════════════════════════════════════════

def _get_baseline_record():
    """获取当前激活的基线记录"""
    return XunjianRecord.objects.filter(is_baseline=True).order_by('-time').first()


def _get_baseline_result(baseline_record, device_name: str, command: str) -> str:
    """从基线记录中获取某设备某命令的输出"""
    if not baseline_record:
        return ''
    obj = CheckResult.objects.filter(
        time=baseline_record.time,
        device=device_name,
        command=command
    ).first()
    return obj.result if obj else ''


# ═══════════════════════════════════════════════════════════
# 单台设备执行
# ═══════════════════════════════════════════════════════════

def _build_conn_kwargs(device: NewDevice) -> dict:
    """
    根据 NewDevice 连接字段构造 netmiko ConnectHandler 参数。

    支持：端口(port)、enable密码(secret)、SSH密钥(use_keys/key_file)、telnet。
    """
    _dtype = _normalize_device_type(device.device_type)
    kwargs = dict(
        device_type=('hp_comware_telnet' if device.conn_type == 'telnet' else _dtype),
        ip=device.ip,
        username=device.username,
        password=device.password,
        conn_timeout=30,
        fast_cli=False,
        global_delay_factor=2,
    )
    if device.port:
        kwargs['port'] = device.port
    if device.enable_password:
        kwargs['secret'] = device.enable_password
    if device.ssh_key_file:
        kwargs.update(use_keys=True, key_file=device.ssh_key_file)
    return kwargs


def _xunjian_one_device(
    device: NewDevice,
    check_items,
    xunjian_time: str,
    baseline_record
) -> DeviceReport:
    """
    对单台设备执行所有巡检项，返回 DeviceReport
    """
    dev_report = DeviceReport(
        device_name=device.name,
        device_ip=device.ip,
        status='ok',
    )

    # 空巡检项：提前检查（check_items 已在主线程物化为 list）
    actual_items = list(check_items) if hasattr(check_items, '__iter__') else []
    if len(actual_items) == 0:
        logger.warning(f'[{device.name}] 所属分组无巡检项，跳过')
        dev_report.status = 'failed'
        dev_report.connect_error = '所属分组未绑定任何巡检项'
        dev_report.expected = 0
        CheckResult.objects.create(
            time=xunjian_time,
            device=device.name,
            command='巡检项',
            result='无巡检项：请在该设备所属分组中绑定巡检项',
        )
        return dev_report

    # 连接设备
    try:
        _conn_kwargs = _build_conn_kwargs(device)
        connection = ConnectHandler(**_conn_kwargs)
        # 关分页（hp_comware V7 默认分页）
        try:
            connection.send_command(
                'screen-length disable',
                expect_string=r'>|\$|#|\]',
                read_timeout=10,
            )
        except Exception as e:
            logger.warning(f'[{device.name}] 关分页预命令失败(忽略): {e}')
        logger.info(f'[{device.name}] 连接成功')

        # —— v3 opt-in 能力门控：开关开启时，确保能力已探测并按能力重算巡检项 ——
        extra = device.extra or {}
        if extra.get('protocol_inspection'):
            try:
                ensure_capabilities(device, connection)   # 探测(过期则重探) + 写回 extra
                # 探测后重算本设备应执行的巡检项（时序修复：actual_items 必须反映最新能力）
                items_qs = _get_items_for_device(device)
                if items_qs is not None:
                    actual_items = list(items_qs)
            except Exception as cap_e:
                logger.warning(f'[{device.name}] 能力门控重算失败，回退到主线程分配项: {cap_e}')
            dev_report.expected = len(actual_items)
        else:
            # 开关关：仅基础项（actual_items 已由主线程按 base 门控），无需探针
            dev_report.expected = len(actual_items)
    except Exception as e:
        logger.error(f'[{device.name}] 连接失败: {e}')
        dev_report.status = 'failed'
        dev_report.connect_error = str(e)
        # 连接失败但该设备分配到的巡检项数量仍计入「应执行项数」，避免回显条数随连接抖动而漂移
        dev_report.total = len(actual_items)
        dev_report.expected = len(actual_items)
        CheckResult.objects.create(
            time=xunjian_time,
            device=device.name,
            command='SSH连接',
            result=f'连接失败: {e}',
        )
        try:
            AnomalyRecord.objects.create(
                time=xunjian_time, device=device.name,
                command='SSH连接', notes=f'连接失败: {e}'[:190], confirm=False,
                severity='P1',
            )
        except Exception as db_e:
            logger.error(f'[{device.name}] 写入异常记录失败: {db_e}')
        # 连接失败 -> 该设备其余分配的巡检项都不会执行。逐条落 CheckResult，
        # 避免历史回显「凭空少了一堆命令」且看不出哪些没巡检到。
        for it in actual_items:
            try:
                CheckResult.objects.create(
                    time=xunjian_time,
                    device=device.name,
                    command=it.command,
                    result=f'未执行（连接失败）：{e}',
                )
            except Exception:
                pass
        return dev_report

    # 逐项执行（每个巡检项独立 try，单项异常绝不中断其余项；且保证每条命令都落一条 CheckResult）
    # 一次性取出本机基线结果，避免逐项查库（原实现每命令一次 SELECT，
    # 千级命令时产生大量 round-trip，是巡检随数据增长变慢的主因之一）。
    baseline_map = {}
    if baseline_record:
        try:
            baseline_map = {
                cr.command: cr.result
                for cr in CheckResult.objects.filter(
                    time=baseline_record.time, device=device.name
                )
            }
        except Exception:
            baseline_map = {}

    for item in actual_items:
        baseline_result = baseline_map.get(item.command, '')
        try:
            result_raw, is_ok, notes, structured = run_check_item(
                connection=connection,
                check_item=item,
                baseline_result=baseline_result,
                device_extra=device.extra or {},
                xunjian_time=xunjian_time,
                device_name=device.name
            )
            dev_report.total += 1

            # 无论成功/失败/空输出，都落一条 CheckResult：保证历史回显条数稳定，
            # 「未巡检到的项」可见、可追溯。落库失败自动重试（MySQL 连接超时）。
            _safe_create_check_result(
                xunjian_time, device.name, item.command,
                result_raw if result_raw else (notes or '采集失败（无输出）')
            )

            # 阶段二·采集时一次解析落库（仅当确有 raw 输出且解析成功）
            if result_raw and structured is not None:
                try:
                    DeviceParseResult.objects.update_or_create(
                        device=device.name,
                        command=item.command,
                        collected_at=xunjian_time,
                        defaults=dict(
                            schema_version=SCHEMA_VERSION,
                            data=structured,
                        ),
                    )
                except Exception as dpe:
                    logger.warning(f'[{device.name}] 结构化结果落库失败({item.command}): {dpe}')

            if not result_raw:
                item_report = CheckItemReport(
                    command=item.command,
                    desc=item.name,
                    status='error',
                    notes=notes or '采集为空，请检查',
                )
                dev_report.items.append(item_report)
                dev_report.anomaly_count += 1
                _safe_create_anomaly(xunjian_time, device.name, item.command,
                                     item_report.notes or '', item.severity)

            elif is_ok:
                dev_report.ok_count += 1
                dev_report.items.append(CheckItemReport(
                    command=item.command, desc=item.name, status='ok'
                ))

            else:
                current_summary, baseline_summary, diff_lines = extract_diff_summary(
                    result_raw, baseline_result
                )
                item_report = CheckItemReport(
                    command=item.command,
                    desc=item.name,
                    status='anomaly',
                    notes=notes,
                    baseline_val=baseline_summary,
                    current_val=current_summary,
                    diff_lines=diff_lines,
                )
                dev_report.items.append(item_report)
                dev_report.anomaly_count += 1

                _safe_create_anomaly(xunjian_time, device.name, item.command,
                                     notes or '', item.severity,
                                     baseline_val=baseline_summary[:500] if baseline_summary else '',
                                     current_val=current_summary[:500] if current_summary else '')
                logger.warning(f'[{device.name}] {item.command} 异常: {notes}')

        except Exception as item_e:
            # 单项执行/落库异常：兜底写一条 CheckResult（记录异常原因），保证不丢项、可追责，
            # 且不影响本设备后续命令继续巡检。
            logger.error(f'[{device.name}] 命令 {item.command} 执行异常(已兜底记录): {item_e}')
            dev_report.total += 1
            dev_report.anomaly_count += 1
            _safe_create_check_result(
                xunjian_time, device.name, item.command,
                f'采集/落库异常: {item_e}'[:190]
            )
            _safe_create_anomaly(xunjian_time, device.name, item.command,
                                 f'采集/落库异常: {item_e}'[:190], item.severity)
            dev_report.items.append(CheckItemReport(
                command=item.command, desc=item.name,
                status='error', notes=f'采集/落库异常: {item_e}'
            ))

    try:
        connection.disconnect()
    except Exception:
        pass

    if dev_report.anomaly_count > 0:
        dev_report.status = 'anomaly'

    logger.info(
        f'[{device.name}] 完成: '
        f'正常 {dev_report.ok_count}/{dev_report.total}, '
        f'异常 {dev_report.anomaly_count} 项'
    )
    return dev_report


# ═══════════════════════════════════════════════════════════
# 主执行入口
# ═══════════════════════════════════════════════════════════

def run_xunjian(
    operator:    str,
    device_ids:  list = None,
    checkset_id: int  = None,
    max_workers: int  = None,
    task_id:    int  = None,
) -> dict:
    """
    执行巡检（新版引擎）

    Args:
        operator:    操作人
        device_ids:  指定设备ID列表（None = 全部启用设备）
        checkset_id: 指定检查集ID（None = 使用设备分组绑定的巡检项）
        max_workers: 最大并发线程数

    Returns:
        {
            "time": 巡检时间,
            "report": XunjianReport 对象,
            "cli_output": CLI格式报告字符串,
            "result": 正常/异常
        }
    """
    # 导入自定义检查函数（如果存在）
    try:
        import app02.custom_checks  # noqa
    except ImportError:
        pass
    # 应用 Web 编辑的 checker 覆盖（DB 优先于文件版）
    try:
        from app02.engine.pipeline import load_checker_overrides
        load_checker_overrides()
    except Exception:
        pass

    xunjian_time    = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    baseline_record = _get_baseline_record()
    baseline_time   = baseline_record.time if baseline_record else '无基线'

    logger.info(f'巡检开始: {xunjian_time}, 操作人: {operator}, 基线: {baseline_time}')

    # 获取设备列表
    qs = NewDevice.objects.filter(enabled=True)
    if device_ids:
        qs = qs.filter(id__in=device_ids)
    elif checkset_id:
        checkset_obj = CheckSet.objects.filter(id=checkset_id, enabled=True)\
                              .prefetch_related('groups').first()
        if checkset_obj:
            group_ids = list(checkset_obj.groups.values_list('id', flat=True))
            qs = qs.filter(group__id__in=group_ids)
    devices = list(qs.select_related('group').prefetch_related('group__check_items'))

    # 初始化报告
    report = XunjianReport(
        xunjian_time=xunjian_time,
        operator=operator,
        baseline_time=baseline_time,
        total_devices=len(devices),
    )

    if not devices:
        return _build_result(xunjian_time, report, operator)

    # 动态调整并发数：不超过32，也不超过设备数+4（避免空闲线程浪费）
    if max_workers is None:
        max_workers = min(32, len(devices) + 4)

    # 并发执行
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for device in devices:
            items_qs = _get_items_for_device(device)
            if items_qs is None:
                # 设备无分组，记录为失败并计入统计
                logger.warning(f'[{device.name}] 未绑定分组，跳过')
                dev_report = DeviceReport(
                    device_name=device.name,
                    device_ip=device.ip,
                    status='failed',
                    connect_error='该设备未绑定任何分组，无巡检项可执行',
                )
                report.devices.append(dev_report)
                report.failed_devices += 1
                continue
            
            # 在主线程中预先求值为 list，避免跨线程传递 QuerySet 导致数据库连接问题
            check_items = list(items_qs)
            if not check_items:
                logger.warning(f'[{device.name}] 所属分组无巡检项（enabled=0），跳过')
                dev_report = DeviceReport(
                    device_name=device.name,
                    device_ip=device.ip,
                    status='failed',
                    connect_error='所属分组未绑定任何启用的巡检项',
                )
                report.devices.append(dev_report)
                report.failed_devices += 1
                CheckResult.objects.create(
                    time=xunjian_time,
                    device=device.name,
                    command='巡检项',
                    result=f'无巡检项：分组 {device.group.name} 无启用的巡检项',
                )
                continue
            
            logger.info(f'[{device.name}] 分配 {len(check_items)} 个巡检项')
            # 应执行项数由 worker 在「能力门控重算」后回填到 dev_report.expected，
            # 此处不再预加（开关开启且探针后发现新特性时，实际应执行项会多于主线程初算）。
            futures[executor.submit(
                _xunjian_one_device, device, check_items, xunjian_time, baseline_record
            )] = device

        done_count = 0
        failed_names = []
        for future in as_completed(futures):
            device = futures[future]
            try:
                dev_report = future.result()
                report.devices.append(dev_report)
                report.expected_checks += getattr(dev_report, 'expected', 0)
                report.total_anomalies += dev_report.anomaly_count
                if dev_report.status == 'ok':
                    report.ok_devices += 1
                elif dev_report.status == 'anomaly':
                    report.anomaly_devices += 1
                else:
                    report.failed_devices += 1
                    if dev_report.device_name:
                        failed_names.append(dev_report.device_name)
                done_count += 1
                if task_id:
                    close_old_connections()
                    XunjianTask.objects.filter(id=task_id).update(
                        status='running',
                        done=done_count,
                        ok_devices=report.ok_devices,
                        anomaly_devices=report.anomaly_devices,
                        failed_devices=report.failed_devices,
                    )
            except Exception as e:
                logger.error(f'[{device.name}] 线程异常: {e}')
                done_count += 1
                if task_id:
                    close_old_connections()
                    XunjianTask.objects.filter(id=task_id).update(
                        status='running', done=done_count,
                    )

    # 巡检结束：更新任务最终状态（供前端进度轮询/续跑使用）
    if task_id:
        close_old_connections()
        final_status = 'done' if (report.failed_devices == 0 and report.total_anomalies == 0) else 'partial'
        XunjianTask.objects.filter(id=task_id).update(
            status=final_status,
            done=report.total_devices,
            ok_devices=report.ok_devices,
            anomaly_devices=report.anomaly_devices,
            failed_devices=report.failed_devices,
            failed_device_list=','.join(failed_names),
            finished_at=datetime.datetime.now(),
            xunjian_time=xunjian_time,
        )

    # 回显条数 = 本次巡检实际写入的命令结果行数。
    # 与历史详情页严格一致（每条分配到的巡检项都落一条 CheckResult，无论成功/空/失败/连接失败），
    # 不再随「某条命令执行成功与否」漂移，也不因瞬时连接抖动而少算。
    try:
        report.total_checks = CheckResult.objects.filter(time=xunjian_time).count()
    except Exception:
        pass

    # 巡检缺口埋点：精确记录「应执行但未回显」的设备-命令对，写入 InspectionGap，
    # 便于后续在界面/命令中查看究竟是哪些没巡检到（修复前 60 项凭空丢失的根因）。
    try:
        gap_n = _audit_missing_checks(xunjian_time, devices)
        if gap_n:
            logger.warning(f'巡检 {xunjian_time} 审计发现 {gap_n} 个缺口项（详见 InspectionGap 表）')
    except Exception as e:
        logger.error(f'巡检缺口审计调用异常: {e}')

    return _build_result(xunjian_time, report, operator)


def _build_result(xunjian_time: str, report: XunjianReport, operator: str) -> dict:
    """保存总记录并返回结果字典"""
    overall = '异常' if (report.total_anomalies > 0 or report.failed_devices > 0) else '正常'

    XunjianRecord.objects.create(
        time=xunjian_time,
        operator=operator,
        result=overall,
        is_baseline=False,
        device_count=report.total_devices,
        check_count=report.total_checks,
        expected_count=report.expected_checks,
        ok_devices=report.ok_devices,
        anomaly_devices=report.anomaly_devices,
        failed_devices=report.failed_devices,
    )

    cli_output = render_cli_report(report)
    logger.info(f'巡检完成\n{cli_output}')

    return {
        'time':       xunjian_time,
        'report':     report,
        'cli_output': cli_output,
        'result':     overall,
    }