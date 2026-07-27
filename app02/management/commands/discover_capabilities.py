"""discover_capabilities —— 检测设备能力。

有两种模式：
  1. --live (默认)  连接到设备跑 PROBE_COMMAND（支持 --force 过期重探）
  2. --from-checkresult  从已采集的 CheckResult 解析（不连设备）

用法：
  python manage.py discover_capabilities --device csw001
  python manage.py discover_capabilities --site 化龙
  python manage.py discover_capabilities --site all --force
  python manage.py discover_capabilities --from-checkresult --site 知识城
  python manage.py discover_capabilities --dry-run
"""
from django.core.management.base import BaseCommand

from app02.models import NewDevice, CheckResult
from app02.engine.device_session import DeviceSession
from app02.engine.capability import detect_capabilities, ensure_capabilities


class Command(BaseCommand):
    help = '检测设备能力：--live (SSH) 或 --from-checkresult (读库)'

    def add_arguments(self, parser):
        parser.add_argument('--site', default='', help='站点过滤(知识城/化龙/all)')
        parser.add_argument('--device', default='', help='指定单台设备名')
        parser.add_argument('--dry-run', action='store_true', help='只打印将处理的设备，不写库')
        parser.add_argument('--force', action='store_true', help='忽略 expired，强制重探(--live)')
        parser.add_argument('--from-checkresult', action='store_true',
                            help='从最近采集的 CheckResult 解析（不连设备）')

    def handle(self, *args, **opts):
        site = opts.get('site') or ''
        dev_name = opts.get('device') or ''
        dry = opts.get('dry_run', False)
        force = opts.get('force', False)
        from_cr = opts.get('from_checkresult', False)

        qs = NewDevice.objects.filter(enabled=True)
        if dev_name:
            qs = qs.filter(name=dev_name)
        elif site and site != 'all':
            qs = qs.filter(site=site)

        if not qs.exists():
            self.stdout.write(self.style.WARNING('没有符合条件的设备'))
            return

        if dry:
            mode = 'CR' if from_cr else 'LIVE'
            self.stdout.write(self.style.WARNING(
                f'[dry-run] [{mode}] 将处理以下 {qs.count()} 台设备:\n  ' +
                '\n  '.join(d.name for d in qs)))
            return

        if from_cr:
            self._from_checkresult(qs)
        else:
            self._live_probe(qs, force)

    def _live_probe(self, qs, force):
        """SSH 连接设备跑探针。"""
        ok = 0
        for dev in qs:
            self.stdout.write(f'→ 探测 {dev.name} ({dev.ip}) ...')
            try:
                session = DeviceSession(dev)
                conn = session.connect()
                caps = ensure_capabilities(dev, conn, force=force)
                session.disconnect(conn)
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'  [连接失败] {dev.name}: {e}'))
                continue

            if caps is None:
                self.stdout.write(self.style.ERROR(
                    f'  [探测失败] {dev.name}: 未获得能力'))
            else:
                ok += 1
                self.stdout.write(self.style.SUCCESS(
                    f'  [能力] {dev.name}: {", ".join(caps) if caps else "(无特性，仅基础)"}'))

        self.stdout.write(self.style.SUCCESS(
            f'\nLive 探测完成：{ok}/{qs.count()} 台成功'))

    def _from_checkresult(self, qs):
        """从最近采集的 display current-configuration CheckResult 解析能力。"""
        ok = 0
        for dev in qs:
            self.stdout.write(f'→ 解析 {dev.name} ...')
            try:
                cr = CheckResult.objects.filter(
                    device=dev.name, command='display current-configuration',
                ).order_by('-time').first()
                if not cr or not cr.result:
                    self.stdout.write(self.style.WARNING(
                        f'  [跳过] {dev.name}: 无 display current-configuration 采集数据'))
                    continue
                caps = detect_capabilities(cr.result)
                extra = dict(dev.extra or {})
                extra['capabilities'] = caps
                if caps:
                    extra['capabilities_ts'] = cr.time
                else:
                    extra.pop('capabilities_ts', None)
                NewDevice.objects.filter(pk=dev.pk).update(extra=extra)
                ok += 1
                self.stdout.write(self.style.SUCCESS(
                    f'  [能力] {dev.name}: {", ".join(caps) if caps else "(无特性，仅基础)"}'))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'  [解析失败] {dev.name}: {e}'))

        self.stdout.write(self.style.SUCCESS(
            f'\nCheckResult 解析完成：{ok}/{qs.count()} 台成功'))
