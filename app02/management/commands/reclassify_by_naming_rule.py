"""
设备分类 2.0 · reclassify_by_naming_rule
─────────────────────────────────────────────
按《命名规则.xlsx》权威真源，解析设备名前缀 → device_class，
一键重算全部设备的 device_class，并输出「与旧 role 不一致」报告。

设计要点：
  - device_class 由官方命名标准驱动，替代手写 role_of() 粗映射，
    修正已发现的 29 台错标（OASW/PSW/USW 全塞 ASW、DCI/DSW 塞 LSW）。
  - IDC 已补映射为「出口交换机」（用户确认）。
  - 默认 dry-run：仅打印报告，不写库；加 --apply 才写回 device_class
    （并尽量把 group 指向 GRP-{site}-{new_class}，目标组需先经 seed 重建）。

用法：
  python manage.py reclassify_by_naming_rule                 # 全部站点 dry-run
  python manage.py reclassify_by_naming_rule --site 化龙     # 单站点
  python manage.py reclassify_by_naming_rule --apply         # 写回 device_class
"""
from django.core.management.base import BaseCommand

from app02.models import NewDevice, DeviceGroup, device_class_of


class Command(BaseCommand):
    help = '按命名规则重分类设备：解析设备名前缀→device_class，输出不一致报告（默认 dry-run）'

    def add_arguments(self, parser):
        parser.add_argument(
            '--site', default='all',
            choices=['all', '知识城', '化龙'],
            help='只处理指定站点（默认 all）')
        parser.add_argument(
            '--apply', action='store_true',
            help='写回 device_class（默认仅 dry-run 打印报告，不写库）')

    def handle(self, *args, **opts):
        site = opts['site']
        apply = opts.get('apply', False)

        qs = NewDevice.objects.all()
        if site != 'all':
            qs = qs.filter(site=site)

        mismatches = []
        updated = 0
        rebind_ok = 0
        rebind_skip = 0

        for d in qs:
            new_cls = device_class_of(d.name)
            # 与「旧 role」或「当前 device_class」任一不同，即视为不一致
            if new_cls != (d.role or '') or new_cls != (d.device_class or 'OTHER'):
                mismatches.append((d.name, d.site, d.role, d.device_class, new_cls))

            if apply:
                changed = False
                if d.device_class != new_cls:
                    d.device_class = new_cls
                    changed = True
                # 尝试把 group 指向新的 (site, device_class) 组
                grp = DeviceGroup.objects.filter(name=f'GRP-{d.site}-{new_cls}').first()
                if grp and d.group_id != grp.id:
                    d.group = grp
                    changed = True
                    rebind_ok += 1
                elif grp is None and d.group_id is not None and d.device_class != new_cls:
                    # 目标组尚未重建（需先重跑 seed_inspection），保留旧 group，但 device_class 已更新
                    rebind_skip += 1
                if changed:
                    fields = ['device_class']
                    if grp:
                        fields.append('group')
                    d.save(update_fields=fields)
                    updated += 1

        # —— 报告 ——
        self.stdout.write(self.style.SUCCESS(
            f'扫描 {qs.count()} 台，device_class 不一致 {len(mismatches)} 台'))
        for name, st, old_role, old_cls, new_cls in mismatches:
            self.stdout.write(
                f'  {name:32} [{st}] role={str(old_role):4} device_class={str(old_cls):6} -> {new_cls}')

        if apply:
            self.stdout.write(self.style.SUCCESS(
                f'已写回 {updated} 台 device_class；重绑分组 {rebind_ok} 台，'
                f'目标组缺失未重绑 {rebind_skip} 台（请先重跑 seed_inspection 重建分组）'))
        else:
            self.stdout.write(self.style.WARNING(
                '（dry-run，未写库；加 --apply 应用；目标分组需先经 seed_inspection 重建）'))
