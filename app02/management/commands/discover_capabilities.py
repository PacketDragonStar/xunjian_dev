"""discover_capabilities —— 检测能力（纯透明，只写 capabilities 不执行）。

与「启用协议巡检」(set_protocol_inspection) 解耦：本命令仅跑探针写 extra['capabilities']，
供界面展示识别结果，不影响任何巡检执行。可在启用开关前先跑，看清设备支持哪些协议。

用法：
  python manage.py discover_capabilities --device csw001
  python manage.py discover_capabilities --site 化龙
  python manage.py discover_capabilities --site all --force
  python manage.py discover_capabilities --dry-run
"""
from django.core.management.base import BaseCommand
from netmiko import ConnectHandler

from app02.models import NewDevice
from app02.engine.device_session import DeviceSession, _build_conn_kwargs
from app02.engine.capability import ensure_capabilities


class Command(BaseCommand):
    help = '检测能力：连接设备跑探针，写 extra[capabilities]（仅展示，不执行协议巡检）'

    def add_arguments(self, parser):
        parser.add_argument('--site', default='', help='站点过滤(知识城/化龙/all)')
        parser.add_argument('--device', default='', help='指定单台设备名')
        parser.add_argument('--dry-run', action='store_true', help='只打印将探测的设备，不连接不写库')
        parser.add_argument('--force', action='store_true', help='忽略 capabilities_ts 过期，强制重探')

    def handle(self, *args, **opts):
        site = opts.get('site') or ''
        dev_name = opts.get('device') or ''
        dry = opts.get('dry_run', False)
        force = opts.get('force', False)

        qs = NewDevice.objects.filter(enabled=True)
        if dev_name:
            qs = qs.filter(name=dev_name)
        elif site and site != 'all':
            qs = qs.filter(site=site)

        if not qs.exists():
            self.stdout.write(self.style.WARNING('没有符合条件的设备'))
            return

        if dry:
            self.stdout.write(self.style.WARNING(
                f'[dry-run] 将对以下 {qs.count()} 台设备执行探针:\n  ' +
                '\n  '.join(d.name for d in qs)))
            return

        ok = 0
        for dev in qs:
            self.stdout.write(f'→ 探测 {dev.name} ({dev.ip}) ...')
            conn = None
            try:
                conn = ConnectHandler(**_build_conn_kwargs(dev))
                try:
                    conn.send_command('screen-length disable',
                                      expect_string=r'>|\$|#|\]', read_timeout=10)
                except Exception:
                    pass
                caps = ensure_capabilities(dev, conn, force=force)
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'  [连接失败] {dev.name}: {e}'))
                continue
            finally:
                if conn is not None:
                    try:
                        conn.disconnect()
                    except Exception:
                        pass

            if caps is None:
                self.stdout.write(self.style.ERROR(
                    f'  [探测失败] {dev.name}: 未获得能力（保守按基础项巡检）'))
            else:
                ok += 1
                self.stdout.write(self.style.SUCCESS(
                    f'  [能力] {dev.name}: {", ".join(caps) if caps else "(无特性，仅基础)"}'))

        self.stdout.write(self.style.SUCCESS(
            f'\n检测完成：{ok}/{qs.count()} 台成功写入 capabilities'))
