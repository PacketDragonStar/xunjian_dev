"""100G 光模块分布查询"""
import os
import re
import sys
import django
from collections import defaultdict

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'xunjian_system1.settings')
django.setup()

from app02.models import CheckResult, XunjianRecord

IF_TYPE_MAP = {
    'HundredGigE': 'HGE', 'FortyGigE': 'FGE', 'TwentyGigE': 'TGE',
    'Twenty-FiveGigE': '25GE', 'Ten-GigabitEthernet': 'XGE', 'TenGigE': 'XGE',
    'GigabitEthernet': 'GE', 'M-GigabitEthernet': 'MGE',
}
_IF_RE = re.compile(r'^([A-Za-z\-]+)(\d+(?:/\d+){2,3})$')

def norm(n):
    m = _IF_RE.match(n.strip())
    if not m:
        return n.strip()
    return IF_TYPE_MAP.get(m.group(1), m.group(1)) + m.group(2)

LOGICAL = ('BAGG', 'RAGG', 'Vlan', 'InLoop', 'NULL', 'MGE', 'REG0',
           'HA', 'Loop', 'Tunnel', 'Dialer', 'Virtual', 'Eth')

def phys(n):
    up = n.upper()
    return not up.startswith(LOGICAL) and re.match(r'^[A-Z0-9\-]+(?:/\d+){2,3}$', up) is not None

def parse_brief(raw):
    out = {}
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        if not re.match(r'^[A-Za-z\-]+\d+(?:/\d+){2,3}$', parts[0]):
            continue
        if parts[1] not in ('UP', 'DOWN', 'ADM'):
            continue
        desc = ' '.join(parts[6:]) if len(parts) > 6 else ''
        out[parts[0]] = (parts[1], desc)
    return out

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    rec = XunjianRecord.objects.order_by('-time').first()

    brief_map = {}
    for cr in CheckResult.objects.filter(time=rec.time, command='display interface brief'):
        if cr.result:
            brief_map[cr.device] = parse_brief(cr.result)

    by_status = defaultdict(int)
    by_device = defaultdict(lambda: defaultdict(list))

    for cr in CheckResult.objects.filter(time=rec.time, command='display transceiver interface'):
        if not cr.result:
            continue
        dev = cr.device
        br = brief_map.get(dev, {})
        for blk in re.split(r'(?=^\S+\s+transceiver information:)', cr.result, flags=re.M):
            m = re.match(r'^(\S+)\s+transceiver information:', blk)
            if not m:
                continue
            if 'The transceiver is absent' in blk:
                continue
            t = re.search(r'Transceiver Type\s*:\s*(\S+)', blk)
            if not t or '100G' not in t.group(1):
                continue
            port = norm(m.group(1))
            if not phys(port):
                continue
            st, desc = br.get(port, ('?', ''))
            if st == 'ADM':
                key = 'ADM(空闲)'
            elif st == 'DOWN':
                key = 'DOWN(有光但未用)'
            elif st == 'UP':
                key = 'UP(在用)'
            else:
                key = '未知'
            by_status[key] += 1
            by_device[dev][key].append(f'{port}')

    print('=== 100G 光模块状态分布 ===')
    for k, v in sorted(by_status.items(), key=lambda x: -x[1]):
        print(f'{k:20s} {v}')

    print()
    print('=== 按设备明细 ===')
    for dev in sorted(by_device.keys()):
        d = by_device[dev]
        up = d.get('UP(在用)', [])
        adm = d.get('ADM(空闲)', [])
        down = d.get('DOWN(有光但未用)', [])
        parts = []
        if up:
            parts.append(f'UP在用 {len(up)}: {", ".join(up)}')
        if adm:
            parts.append(f'ADM空闲 {len(adm)}: {", ".join(adm)}')
        if down:
            parts.append(f'DOWN {len(down)}: {", ".join(down)}')
        print(f'\n{dev}')
        for p in parts:
            print(f'    {p}')

if __name__ == '__main__':
    main()
