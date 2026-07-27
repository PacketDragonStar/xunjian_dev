"""巡检后 post-inspection hook pipeline。

巡检主流程结束后按序执行一系列 hook：sync_cmdb、detect_capabilities 等。
每个 hook 独立运行（异常不阻塞后续 hook），便于扩展。
"""
import logging

logger = logging.getLogger(__name__)

# ── Hook 注册表 ──────────────────────────────────────────────
_HOOKS = []


def register_hook(fn):
    """装饰器：注册巡检后 hook。"""
    _HOOKS.append(fn)
    return fn


def run_post_inspection_hooks(task_id, xunjian_time, operator):
    """依次执行所有已注册的巡检后 hook。

    Args:
        task_id: 巡检任务 ID（XunjianTask.id）
        xunjian_time: 巡检时间字符串
        operator: 操作人
    """
    for hook in _HOOKS:
        try:
            from django.db import close_old_connections
            close_old_connections()
            hook(task_id, xunjian_time, operator)
        except Exception as e:
            logger.warning(f'[post-inspection] hook {hook.__name__} 失败: {e}')


# ═══════════════════════════════════════════════════════════
# 内置 hooks
# ═══════════════════════════════════════════════════════════

@register_hook
def sync_cmdb(task_id, xunjian_time, operator):
    """巡检后自动同步 CMDB（设备/接口/链路/VLAN/IP/CPU/内存）。"""
    try:
        from django.core.management import call_command
        call_command('sync_cmdb')
        logger.info(f'巡检后自动同步CMDB完成(task={task_id})')
    except Exception as e:
        logger.warning(f'巡检后自动同步CMDB失败(task={task_id}): {e}')


@register_hook
def detect_capabilities(task_id, xunjian_time, operator):
    """巡检后从 CheckResult 解析能力，写入 pending_capabilities。

    只对未关闭提示（capabilities_nag_disabled != True）的设备运行。
    """
    from app02.models import NewDevice, CheckResult
    from app02.engine.capability import detect_capabilities as _detect

    try:
        # 取本次巡检采集的 display current-configuration 结果
        config_map = {
            cr.device: cr.result
            for cr in CheckResult.objects.filter(
                time=xunjian_time, command='display current-configuration',
            )
            if cr.result
        }
        if not config_map:
            logger.warning(f'[post-inspection] 未找到 display current-configuration 采集结果(task={task_id})')
            return

        # 遍历所有启用设备，跳过关闭提示的
        devices = NewDevice.objects.filter(enabled=True).only('pk', 'name', 'extra')
        updated = 0
        for device in devices:
            extra = device.extra or {}
            if extra.get('capabilities_nag_disabled'):
                continue
            raw = config_map.get(device.name)
            if not raw:
                continue
            detected = _detect(raw)
            if not detected:
                continue
            existing = set(extra.get('capabilities') or [])
            pending = set(extra.get('pending_capabilities') or [])
            new = set(detected) - existing - pending
            if new:
                extra['pending_capabilities'] = list(pending | new)
                NewDevice.objects.filter(pk=device.pk).update(extra=extra)
                updated += 1

        if updated:
            logger.info(f'[post-inspection] 发现 {updated} 台设备有新能力待确认(task={task_id})')
    except Exception as e:
        logger.warning(f'[post-inspection] detect_capabilities 失败(task={task_id}): {e}')
