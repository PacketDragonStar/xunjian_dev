"""ItemRunner — 单条巡检项的执行层。

封装 send_command → run_check_item 调用链，返回结构化结果。
落库和报告逻辑不在此模块内（由 ResultRecorder 和 DeviceReport 负责）。
"""
import logging
from dataclasses import dataclass
from typing import Optional

from app02.engine.pipeline import run_check_item

logger = logging.getLogger(__name__)


@dataclass
class ItemResult:
    """单条巡检项的执行结果（不含落库决策）。"""
    command: str
    raw: Optional[str]        # 命令原始输出；None = 执行失败
    is_ok: bool
    notes: str
    structured: Optional[dict]  # 结构化解析结果；None = 未解析


class ItemRunner:
    """逐项执行巡检命令。

    Usage:
        runner = ItemRunner(connection, device_name, device_extra)
        for item in check_items:
            result = runner.run_one(item, xunjian_time)
    """

    def __init__(self, connection, device_name: str, device_extra: dict):
        self._connection = connection
        self._device_name = device_name
        self._device_extra = device_extra

    def run_one(self, check_item, xunjian_time: str, baseline_result: str = '') -> ItemResult:
        """执行单个巡检项：采集 → 解析 → 检查。

        Args:
            check_item: CheckItem 实例
            xunjian_time: 巡检时间字符串
            baseline_result: 基线输出文本（空字符串 = 无基线）

        Returns:
            ItemResult（即使执行异常也返回结果，不抛异常）
        """
        try:
            result_raw, is_ok, notes, structured = run_check_item(
                connection=self._connection,
                check_item=check_item,
                baseline_result=baseline_result,
                device_extra=self._device_extra,
                xunjian_time=xunjian_time,
                device_name=self._device_name,
            )
            return ItemResult(
                command=check_item.command,
                raw=result_raw,
                is_ok=is_ok,
                notes=notes or '',
                structured=structured,
            )
        except Exception as e:
            logger.error(
                f'[{self._device_name}] 命令 {check_item.command} '
                f'执行异常(已兜底记录): {e}'
            )
            return ItemResult(
                command=check_item.command,
                raw=None,
                is_ok=False,
                notes=f'采集/落库异常: {e}',
                structured=None,
            )
