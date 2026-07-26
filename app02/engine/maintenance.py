"""运维维护：结果保留清理 + 卡死任务回收。

被 ``app02/apps.py`` 的 ``AppConfig.ready`` 后台线程周期调用；
也可单独用 ``python manage.py prune_results`` 手动触发清理。
"""
import logging
import time
from datetime import timedelta

logger = logging.getLogger('xunjian')

DEFAULT_RETENTION_DAYS = 90
STUCK_TIMEOUT_MINUTES = 60
MAINTENANCE_INTERVAL = 3600  # 每小时一次


def prune_old_results(retention_days: int = DEFAULT_RETENTION_DAYS) -> int:
    """清理超期的结果表（仅清理带 created_at 且超期的行，legacy 无时间行保留）。

    注意：DeviceParseResult（采集时一次解析的结构化结果）此前漏清理，
    会随每次巡检无界增长，而巡检对每个命令都会做 update_or_create，
    表越大写越慢——这正是「巡检越跑越卡」的根因之一。此处一并清理。
    """
    from django.utils import timezone
    from app02.models import (
        CheckResult, DiscoveryRecord, ComplianceResult,
        DeviceParseResult, AnomalyRecord,
    )

    cutoff = timezone.now() - timedelta(days=retention_days)
    deleted = 0
    deleted += CheckResult.objects.filter(created_at__lt=cutoff).delete()[0]
    deleted += DiscoveryRecord.objects.filter(created_at__lt=cutoff).delete()[0]
    deleted += ComplianceResult.objects.filter(created_at__lt=cutoff).delete()[0]
    deleted += DeviceParseResult.objects.filter(created_at__lt=cutoff).delete()[0]
    deleted += AnomalyRecord.objects.filter(created_at__lt=cutoff).delete()[0]
    if deleted:
        logger.info(f'[maintenance] 清理超期结果 {deleted} 行（保留窗口={retention_days}天）')
    return deleted


def recover_running_on_startup() -> int:
    """冷启动恢复：把 running 状态的任务标记为 failed（进程重启导致的中断）。"""
    from app02.models import XunjianTask

    n = XunjianTask.objects.filter(status='running').update(
        status='failed', error='进程重启，任务中断（已自动回收）'
    )
    if n:
        logger.warning(f'[maintenance] 启动回收 {n} 个卡死任务(running->failed)')
    return n


def reap_stuck_tasks(timeout_minutes: int = STUCK_TIMEOUT_MINUTES) -> int:
    """周期回收：运行超时仍 stuck 在 running 的任务。"""
    from django.utils import timezone
    from app02.models import XunjianTask

    cutoff = timezone.now() - timedelta(minutes=timeout_minutes)
    n = XunjianTask.objects.filter(status='running', created_at__lt=cutoff).update(
        status='failed', error=f'执行超时({timeout_minutes}分钟)自动回收'
    )
    if n:
        logger.warning(f'[maintenance] 超时回收 {n} 个任务')
    return n


def run_maintenance(retention_days: int = DEFAULT_RETENTION_DAYS,
                    timeout_minutes: int = STUCK_TIMEOUT_MINUTES) -> None:
    prune_old_results(retention_days)
    reap_stuck_tasks(timeout_minutes)


def maintenance_loop(retention_days: int, interval: int = MAINTENANCE_INTERVAL) -> None:
    """后台线程主循环。"""
    while True:
        time.sleep(interval)
        try:
            run_maintenance(retention_days=retention_days)
        except Exception as e:  # 守护线程永不退出
            logger.warning(f'[maintenance] 周期维护出错(忽略): {e}')
