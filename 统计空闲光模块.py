"""统计空闲光模块：插了光模块但端口 Link DOWN 的物理端口。

数据来源（最近一次巡检）：
- display transceiver interface   → 哪些端口插了光模块（排除 absent）
- display interface brief          → 端口 Link 状态

注意：
- transceiver 输出用长名（HundredGigE1/0/25），interface brief 用短名（HGE1/0/25）
  需要归一化后才能匹配。
- 物理端口才统计；BAGG/RAGG/Vlan/InLoop/NULL/MGE/REG0/HA 等逻辑口排除。
"""
import os
import re
import django
from collections import defaultdict

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'xunjian_system1.settings')
django.setup()

from app02.models import CheckResult, XunjianRecord

# ── 接口名归一化：长名 → 短名 ──
IF_TYPE_MAP = {
    'HundredGigE':   'HGE',
    'FortyGigE':     'FGE',
    'TwentyGigE':    'TGE',
    'Twenty-FiveGigE': '25GE',
    'TenGigE':       'XGE',
    'GigabitEthernet': 'GE',
}
_IF_RE = re.compile(r'^([A-Za-z\-]+)(\d+/[\d/]+)$')

def normalize_ifname(name: str) -> str:
    """HundredGigE1/0/25 → HGE1/0/25；已是短名则原样返回。"""
    m = _IF_RE.match(name.strip())
    if not m:
        return name.strip()
    prefix, loc = m.group(1), m.group(2)
    short = IF_TYPE_MAP.get(prefix, prefix)
    return f'{short}{loc}'

# 逻辑/虚拟接口排除
LOGICAL_PREFIXES = (
    'BAGG', 'RAGG', 'Vlan', 'InLoop', 'NULL', 'MGE', 'REG0',
    'HA', 'Loop', 'Tunnel', 'Dialer', 'Virtual', 'Eth',
)


def is_physical(name: str) -> bool:
    up = name.upper()
    return not up.startswith(LOGICAL_PREFIXES) and re.match(r'^[A-Z]+\d+/\d+/\d+$', up) is not None


def parse_transceiver(raw: str):
    """从 display transceiver interface 提取插了光模块的端口（长名）。"""
    ports = []
    for m in re.finditer(r'^(\S+)\s+transceiver information:', raw, re.M):
        name = m.group(1).strip()
        # 取该段内容
        seg_end = raw.find('\n', m.end())
        nxt = re.search(r'^(\S+)\s+transceiver information:', raw[seg_end:], re.M)
        seg = raw[seg_end:seg_end + (nxt.start() if nxt else len(raw) - seg_end)]
        if 'The transceiver is absent' not in seg:
            ports.append(name)
    return ports


def parse_interface_brief(raw: str):
    """从 display interface brief 提取 端口名 → Link 状态。"""
    status = {}
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        name, link = parts[0], parts[1]
        if not re.match(r'^[A-Za-z\-]+\d+/\d+/\d+$', name):
            continue  # 表头/说明行/逻辑口
        if link in ('UP', 'DOWN', 'ADM'):
            status[name] = link
    return status


def main():
    rec = XunjianRecord.objects.order_by('-time').first()
    print(f'=== 最近巡检: {rec.time} ({rec.device_count}台设备) ===\n')

    dev_rows = CheckResult.objects.filter(
        time=rec.time, command='display transceiver interface'
    )
    brief_map = {
        cr.device: cr.result
        for cr in CheckResult.objects.filter(time=rec.time, command='display interface brief')
        if cr.result
    }

    total_transceivers = 0
    total_idle = 0
    site_stats = defaultdict(lambda: {'has': 0, 'idle': 0})
    per_device = []

    for cr in dev_rows:
        device = cr.device
        if not cr.result:
            continue
        brief_raw = brief_map.get(device, '')
        brief_status = parse_interface_brief(brief_raw) if brief_raw else {}

        # 插了光模块的端口（长名 → 短名）
        transceivers = [normalize_ifname(p) for p in parse_transceiver(cr.result)]

        idle_ports = []
        for port in transceivers:
            if not is_physical(port):
                continue
            status = brief_status.get(port, '?')
            if status in ('DOWN', 'ADM'):
                idle_ports.append(port)

        total_transceivers += len(transceivers)
        total_idle += len(idle_ports)
        site = '知识城' if 'zscidc' in device else ('化龙' if 'hualong' in device else '未知')
        site_stats[site]['has'] += len(transceivers)
        site_stats[site]['idle'] += len(idle_ports)
        per_device.append((device, len(transceivers), idle_ports))

    print(f'{"设备":55s} {"光模块数":>8s} {"空闲数":>6s}  空闲端口')
    print('-' * 120)
    for device, n_has, idle_ports in sorted(per_device, key=lambda x: x[0]):
        if idle_ports:
            print(f'{device:55s} {n_has:>8d} {len(idle_ports):>6d}  {", ".join(idle_ports)}')
        else:
            print(f'{device:55s} {n_has:>8d} {0:>6d}')

    print('\n=== 站点汇总 ===')
    for site, s in sorted(site_stats.items()):
        print(f'{site:6s}: 光模块 {s["has"]:>4d} 个，空闲 {s["idle"]:>4d} 个 '
              f'(空闲率 {s["idle"]/s["has"]*100:.1f}%)' if s['has'] else f'{site}: 无数据')

    print(f'\n=== 总计 ===')
    print(f'已插光模块端口: {total_transceivers} 个')
    print(f'空闲光模块 (端口DOWN): {total_idle} 个')
    if total_transceivers:
        print(f'空闲率: {total_idle/total_transceivers*100:.1f}%')


if __name__ == '__main__':
    import sys
    import io
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main()
    text = buf.getvalue()

    # 终端输出（若支持 UTF-8）
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        print(text)
    except Exception:
        pass

    # 落盘（UTF-8）
    out = '空闲光模块统计_' + ('20260803' if 'rec' not in dir() else '') + '.txt'
    with open(out, 'w', encoding='utf-8') as f:
        f.write(text)
    print(f'\n报告已写入: {out}')
