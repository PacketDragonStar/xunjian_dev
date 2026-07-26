"""set_protocol_inspection —— 启用/停用逐设备「协议巡检」开关(默认关)。

与 discover_capabilities 解耦：
- 本命令只改 extra['protocol_inspection'] 开关；
- 开了开关后，巡检才会按 capabilities 门控执行 feature 项；
- 建议先用 discover_capabilities 看清设备支持哪些协议，再开开关。

用法：
  python manage.py set_protocol_inspection --device csw001 --on
  python manage.py set_protocol_inspection --device csw001 --off
  python manage.py set_protocol_inspection --site 化龙 --role CSW --on   # 批量试点
"""
from django.core.management.base import BaseCommand

from app02.models import NewDevice


class Command(BaseCommand):
    help = '启用/停用逐设备「协议巡检」开关（默认关；开启后按 capabilities 门控执行 feature 项）'

    def add_arguments(self, parser):
        parser.add_argument('--device', default='', help='指定单台设备名')
        parser.add_argument('--site', default='', help='站点过滤(知识城/化龙/all)')
        parser.add_argument('--role', default='', help='按 device_class 过滤(如 CSW/FW/ASW)')
        g = parser.add_mutually_exclusive_group(required=True)
        g.add_argument('--on', dest='on', action='store_true', help='开启协议巡检')
        g.add_argument('--off', dest='on', action='store_false', help='关闭协议巡检')

    def handle(self, *args, **opts):
        on = opts.get('on')
        qs = NewDevice.objects.filter(enabled=True)
        if opts.get('device'):
            qs = qs.filter(name=opts['device'])
        if opts.get('site') and opts['site'] != 'all':
            qs = qs.filter(site=opts['site'])
        if opts.get('role'):
            qs = qs.filter(device_class=opts['role'].upper())

        if not qs.exists():
            self.stdout.write(self.style.WARNING('没有符合条件的设备'))
            return

        n = 0
        for dev in qs:
            extra = dict(dev.extra or {})
            extra['protocol_inspection'] = on
            dev.extra = extra
            dev.save(update_fields=['extra'])
            n += 1
            self.stdout.write(f'  {dev.name}: protocol_inspection = {on}')

        tip = '' if not on else '（建议先对该设备执行 discover_capabilities 写入 capabilities）'
        self.stdout.write(self.style.SUCCESS(
            f'\n已{"开启" if on else "关闭"} {n} 台设备的协议巡检开关{tip}'))
