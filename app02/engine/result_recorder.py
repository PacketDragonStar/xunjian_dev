"""ResultRecorder — 巡检结果落库层。

封装三种 DB 写入操作（CheckResult / DeviceParseResult / AnomalyRecord），
统一使用 _db_create_with_retry 处理 OperationalError 重试。
"""
import logging

from django.db import close_old_connections
from django.db.utils import OperationalError

from app02.models import CheckResult, AnomalyRecord, DeviceParseResult
from app02.parsers import SCHEMA_VERSION

logger = logging.getLogger(__name__)


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


class ResultRecorder:
    """巡检结果持久化。

    Usage:
        recorder = ResultRecorder(xunjian_time, device_name)
        recorder.record_command(item.command, result_raw)
        recorder.record_anomaly(item.command, notes, severity)
        recorder.record_parse(item.command, result_raw, structured)
    """

    def __init__(self, xunjian_time: str, device_name: str):
        self._time = xunjian_time
        self._device = device_name

    def record_command(self, command: str, result_raw: str) -> bool:
        """记录一条命令的 CheckResult（始终写入）。"""
        result = result_raw if isinstance(result_raw, str) else (
            str(result_raw) if result_raw is not None else ''
        )
        ok = _db_create_with_retry(
            lambda: CheckResult.objects.create(
                time=self._time,
                device=self._device,
                command=command,
                result=result,
            )
        )
        if not ok:
            logger.error(f'[{self._device}] CheckResult 落库失败({command})')
        return ok

    def record_parse(self, command: str, result_raw: str,
                     structured: dict) -> None:
        """记录结构化解析结果（仅在 raw + structured 有效时调用）。"""
        if not result_raw or structured is None:
            return
        ok = _db_create_with_retry(
            lambda: DeviceParseResult.objects.update_or_create(
                device=self._device,
                command=command,
                collected_at=self._time,
                defaults=dict(
                    schema_version=SCHEMA_VERSION,
                    data=structured,
                ),
            )
        )
        if not ok:
            logger.warning(f'[{self._device}] 结构化结果落库失败({command})')

    def record_anomaly(self, command: str, notes: str, severity: str,
                       baseline_val: str = '', current_val: str = '') -> None:
        """记录一条异常记录（仅在异常/错误时调用）。"""
        try:
            ok = _db_create_with_retry(
                lambda: AnomalyRecord.objects.create(
                    time=self._time,
                    device=self._device,
                    command=command,
                    notes=(notes or '')[:190],
                    confirm=False,
                    baseline_val=(baseline_val or '')[:500],
                    current_val=(current_val or '')[:500],
                    severity=severity or 'P2',
                )
            )
            if not ok:
                logger.error(f'[{self._device}] AnomalyRecord 落库失败({command})')
        except Exception as e:
            logger.error(f'[{self._device}] AnomalyRecord 落库失败({command}): {e}')

    @staticmethod
    def record_connection_failure(time, device_name, error):
        """记录连接失败结果（一条 SSH连接 + 一条异常记录 P1）。"""
        CheckResult.objects.create(
            time=time, device=device_name,
            command='SSH连接', result=f'连接失败: {error}',
        )
        try:
            AnomalyRecord.objects.create(
                time=time, device=device_name,
                command='SSH连接', notes=f'连接失败: {error}'[:190],
                confirm=False, severity='P1',
            )
        except Exception:
            pass

    @staticmethod
    def record_bulk_connection_failure(time, device_name, error, items):
        """连接失败时，批量写入所有未执行巡检项的 CheckResult。"""
        try:
            CheckResult.objects.bulk_create([
                CheckResult(
                    time=time, device=device_name,
                    command=it.command,
                    result=f'未执行（连接失败）：{error}',
                )
                for it in items
            ])
        except Exception:
            pass
