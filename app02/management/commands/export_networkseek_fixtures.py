"""export_networkseek_fixtures —— 把巡检采集结果桥接为 network-seek 可摄入的 fixture。

阶段三（2026-07-23）起：默认导出**结构化 JSON**（每台设备一个 .json），
内容为该设备各命令的「规范化 dict」（取自阶段二落库的 DeviceParseResult.data，
无结构化记录时实时解析 CheckResult.raw 回退），与《解析器单一真源》设计文档 §4 契约同源。
network-seek 侧 `import_comware_structured` 直接消费该 JSON 建图，**不再对 raw 重解析**。

JSON 文件结构：
    {
      "device": "<台账名>", "site": "...", "role": "...", "mgmt_ip": "...",
      "schema_version": "1",
      "parsed": {
        "display version": {...}, "display interface brief": [...], ...
      }
    }

调试/回退：加 --raw 可同时导出旧版 .txt（raw 文本，!Command: 分段），供 network-seek
旧导入链路（import_comware_fixture）使用。

输出目录：<项目根>/cmdb_fixtures/<site>/<device>.json
之后在 network-seek 侧（结构化薄导入）：
    python scripts/reimport_comware.py --dir cmdb_fixtures/化龙 --json
"""
import os
import json

from django.core.management.base import BaseCommand
from app02.models import NewDevice, CheckResult, DeviceParseResult
from app02.parsers import parse_device_command, SCHEMA_VERSION


# 导出命令集（顺序即导出顺序；键=命令，值=旧版 .txt 段头标记）
SECTIONS = [
    ('display version', 'display version'),
    ('display current-configuration', 'display current-configuration'),
    ('display interface brief', 'display interface brief'),
    ('display lldp neighbor-information list', 'display lldp neighbor-information list'),
    ('display vlan brief', 'display vlan brief'),
    ('display ip routing-table', 'display ip routing-table'),
    # ── 高可用 / 堆叠 / 安全 ──
    ('display vrrp verbose', 'display vrrp'),
    ('display irf', 'display irf'),
    ('display m-lag summary', 'display m-lag summary'),
    ('display link-aggregation verbose', 'display link-aggregation verbose'),
    ('display security-zone', 'display security-zone'),
    ('display security-policy ip', 'display security-policy ip'),
    ('display remote-backup-group status', 'display remote-backup-group status'),
]


def _collect_parsed(device_name: str, cmd: str):
    """取某设备某命令的结构化结果。

    1) 优先 DeviceParseResult（阶段二采集时一次解析落库的最新一份）；
    2) 回退：实时解析 CheckResult.raw（切换期/历史数据尚未回填时）。
    无数据返回 None。
    """
    rec = (DeviceParseResult.objects
           .filter(device=device_name, command=cmd)
           .order_by('-collected_at', '-id').first())
    if rec is not None and rec.data:
        return rec.data
    raw = (CheckResult.objects
           .filter(device=device_name, command=cmd)
           .order_by('-created_at', '-id').first())
    if raw and raw.result and raw.result.strip():
        return parse_device_command(cmd, raw.result)
    return None


class Command(BaseCommand):
    help = '将已采集的解析结果导出为 network-seek 可摄入的结构化 JSON（默认；--raw 另产旧版 .txt）'

    def add_arguments(self, parser):
        parser.add_argument('--site', default='', help='仅导出指定站点(知识城/化龙)，默认全部')
        parser.add_argument('--out', default='cmdb_fixtures', help='输出根目录(相对项目根)')
        parser.add_argument('--raw', action='store_true',
                            help='同时导出旧版 .txt（raw 文本，!Command: 分段），供回退使用')

    def handle(self, *args, **options):
        from django.conf import settings
        site = options.get('site', '') or ''
        out_root = os.path.join(settings.BASE_DIR, options.get('out', 'cmdb_fixtures'))
        emit_raw = bool(options.get('raw'))

        devs = NewDevice.objects.filter(enabled=True)
        if site:
            devs = devs.filter(site=site)

        total = 0
        for dev in devs:
            parsed = {}
            for cmd, _ in SECTIONS:
                data = _collect_parsed(dev.name, cmd)
                if data is not None:
                    parsed[cmd] = data
            if not parsed:
                continue

            doc = {
                'device': dev.name,
                'site': dev.site or '',
                'role': dev.role or '',
                'mgmt_ip': dev.ip or '',
                'schema_version': SCHEMA_VERSION,
                'parsed': parsed,
            }
            site_dir = os.path.join(out_root, dev.site or '未知')
            os.makedirs(site_dir, exist_ok=True)

            # 结构化 JSON（默认产物）
            jpath = os.path.join(site_dir, re_sub(dev.name) + '.json')
            with open(jpath, 'w', encoding='utf-8') as f:
                json.dump(doc, f, ensure_ascii=False, indent=2)
            total += 1
            self.stdout.write(self.style.SUCCESS(f'  [OK] {dev.name} -> {dev.site}/{re_sub(dev.name)}.json'))

            # 旧版 .txt（调试/回退，可选）
            if emit_raw:
                parts = []
                for cmd, header in SECTIONS:
                    rec = (CheckResult.objects
                           .filter(device=dev.name, command=cmd)
                           .order_by('-created_at', '-id').first())
                    if rec and rec.result and rec.result.strip():
                        parts.append(f'!Command: {header}\n{rec.result.strip()}')
                if parts:
                    tpath = os.path.join(site_dir, re_sub(dev.name) + '.txt')
                    with open(tpath, 'w', encoding='utf-8') as f:
                        f.write('\n\n'.join(parts) + '\n')
                    self.stdout.write(self.style.WARNING(f'       (raw) {dev.site}/{re_sub(dev.name)}.txt'))

        self.stdout.write(self.style.SUCCESS(f'\n导出完成：{total} 台设备 -> {out_root}'))


def re_sub(name: str) -> str:
    import re
    return re.sub(r'[^\w\-.]', '_', name)
