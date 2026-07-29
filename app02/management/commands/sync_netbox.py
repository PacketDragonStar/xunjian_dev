"""sync_netbox —— 巡检系统 → NetBox CMDB 同步。

用法：
  python manage.py sync_netbox --site 化龙               # 仅导文件
  python manage.py sync_netbox --site 化龙 --push         # 推送写入
  python manage.py sync_netbox --site 化龙 --push --delete  # 推送 + 执行删除
  python manage.py sync_netbox --out netbox_fixtures/     # 指定导出目录

架构（双写模式）：
  - 默认产出 netbox_fixtures/<site>/<timestamp>.json（供人工审核）
  - --push 通过 pynetbox 调 NetBox REST API 写入
  - 增量 diff：仅增/改，不静默删除
  - --delete 开关执行删除

Phase 0: seed_netbox        → 基础数据（Site/Role/Manufacturer/Platform/...）
Phase 1: sync_devices       → 设备（含 Virtual Chassis 拆堆叠）
Phase 2: sync_interfaces    → 接口 + Console Port + Power Port
Phase 3: sync_ipam          → VLAN/VLAN Group/VRF/IP/Prefix/FHRP/Service/ASN
Phase 4: sync_cables        → LLDP → Cable（两阶段：先接口后 Cable）
Phase 5: sync_extras        → Tags/CustomFields/ConfigContexts/Journal/NAT
Phase 6: diff_report        → 变更摘要 + 待删除清单
Phase 7: delete_stale       → --delete 时执行
"""
import json
import os
from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand

from app02.netbox.client import NetBoxClient
from app02.netbox.mapper import map_role, map_if_type, map_device_status
from app02.netbox.diff import DiffReport
from app02.netbox.seed import seed_netbox
from app02.netbox.sync import sync_devices, sync_interfaces, sync_ipam, sync_cables, sync_extras, delete_stale


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument('--site', help='站点名（知识城/化龙），不指定=全部')
        parser.add_argument('--out', default=None, help='fixture 导出目录')
        parser.add_argument('--push', action='store_true', help='推送写入 NetBox API')
        parser.add_argument('--delete', action='store_true', help='执行删除（默认仅报告）')

    def handle(self, **options):
        site = options.get('site') or '全部站点'
        push = options['push']
        do_delete = options['delete']
        out_dir = options.get('out') or os.path.join(
            settings.BASE_DIR if hasattr(settings, 'BASE_DIR') else '.',
            'netbox_fixtures',
        )

        self.stdout.write(f'\n{"="*60}')
        self.stdout.write(f'  NetBox 同步 — {site}')
        self.stdout.write(f'  模式：{"推送" if push else "仅导文件"}'
                          f'{" + 删除" if do_delete else ""}')
        self.stdout.write(f'{"="*60}\n')

        report = DiffReport(site=site)

        # Phase 0: seed 基础数据
        nb = NetBoxClient()
        if push:
            if nb.connect():
                self.stdout.write(self.style.SUCCESS('[Phase 0] NetBox 连接成功'))
            else:
                self.stdout.write(self.style.WARNING(
                    '[Phase 0] NetBox 不可达，检查 NETBOX_URL/NETBOX_TOKEN。改为仅导文件模式。'))
                push = False
        else:
            self.stdout.write('[Phase 0] 仅导文件模式（不加 --push）')

        if push:
            seed_netbox(nb, report)

            # Phase 1: Devices
            self.stdout.write('[Phase 1] 同步设备…')
            sync_devices(nb, site, report)

            # Phase 2: Interfaces + Ports
            self.stdout.write('[Phase 2] 同步接口…')
            sync_interfaces(nb, site, report)

            # Phase 3: IPAM
            self.stdout.write('[Phase 3] 同步 IPAM…')
            sync_ipam(nb, site, report)

            # Phase 4: Cables
            self.stdout.write('[Phase 4] 同步 Cable 连线…')
            sync_cables(nb, site, report)

            # Phase 5: Extras
            self.stdout.write('[Phase 5] 同步 Extras (Tags/CustomFields/Journal/NAT)…')
            sync_extras(nb, site, report)

            # Phase 7: Delete stale
            if do_delete:
                self.stdout.write('[Phase 7] 执行删除…')
                delete_stale(nb, site, report)

        # ── 以下各 Phase 将在后续 Ticket 中逐项实现 ──
        # Phase 5: sync_extras(nb, site, report)
        # Phase 7: if do_delete: delete_stale(nb, site, report)

        # Phase 6: 输出报告
        report.print()

        # 导出 JSON
        os.makedirs(out_dir, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        json_path = os.path.join(out_dir, f'{site}_{ts}.json')
        report.save(json_path)
        self.stdout.write(f'  变更报告已保存: {json_path}\n')
