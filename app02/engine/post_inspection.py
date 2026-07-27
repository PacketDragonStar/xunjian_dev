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
