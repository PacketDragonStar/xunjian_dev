import logging
import sys
import threading

from django.apps import AppConfig

logger = logging.getLogger('xunjian')

# 这些一次性管理命令不启动后台维护线程（runserver 除外，开发也要回收）
_ONESHOT_CMDS = {
    'migrate', 'makemigrations', 'seed_inspection', 'prune_results',
    'collectstatic', 'shell', 'test',
}


class App02Config(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'app02'

    def ready(self):
        argv = sys.argv
        # 跳过一次性命令（runserver 仍要启动回收线程）
        if any(c in argv for c in _ONESHOT_CMDS) and 'runserver' not in argv:
            return

        # 1) 冷启动回收：把上次进程遗留的 running 任务标记为失败
        try:
            from app02.engine.maintenance import recover_running_on_startup
            recover_running_on_startup()
        except Exception as e:  # 启动阶段异常不应阻断应用
            logger.warning(f'[maintenance] 启动回收失败(忽略): {e}')

        # 2) 启动周期维护守护线程
        try:
            from django.conf import settings
            from app02.engine.maintenance import maintenance_loop
            retention = getattr(settings, 'CHECKRESULT_RETENTION_DAYS', 90)
            t = threading.Thread(target=maintenance_loop, args=(retention,),
                                name='xunjian-maintenance', daemon=True)
            t.start()
        except Exception as e:
            logger.warning(f'[maintenance] 维护线程启动失败(忽略): {e}')

        # 3) 加载 Web 编辑的 checker 覆盖（DB 优先于文件版）
        try:
            import app02.custom_checks  # 确保文件版先注册
            from app02.engine.pipeline import load_checker_overrides
            load_checker_overrides()
        except Exception as e:
            logger.warning(f'[checker] 加载覆盖失败(忽略): {e}')
