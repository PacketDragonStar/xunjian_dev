"""按型号统计空闲光模块 v3（最精确版）

判定逻辑：
- ADM（管理性 shutdown，描述 NO-USE）= 真空闲 ✅
- DOWN + 无描述 = 空闲 ✅
- DOWN + 有 To-[xxx] 描述 = 有规划用途但对端未起 ❌ 不算空闲
- UP = 在用
- 电口模块（1000_BASE_T_AN_SFP）单独统计，不计入光模块
"""
import os
import re
import io
import sys
import contextlib
import django
from collections import defaultdict

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'xunjian_system1.settings')
django.setup()

from app02.models import CheckResult, XunjianRecord

IF_TYPE_MAP = {
    'HundredGigE':   'HGE',
    'FortyGigE':     'FGE',
    'TwentyGigE':    'TGE',
    'Twenty-FiveGigE': '25GE',
    'Ten-GigabitEthernet': 'XGE',
    'TenGigE':       'XGE',
    'GigabitEthernet': 'GE',
    'M-GigabitEthernet': 'MGE',
}
_IF_RE = re.compile(r'^([A-Za-z\-]+)(\d+(?:/\d+){2,3})$')

def normalize_ifname(name: str) -> str:
    m = _IF_RE.match(name.strip())
    if not m:
        return name.strip()
    return IF_TYPE_MAP.get(m.group(1), m.group(1)) + m.group(2)

LOGICAL_PREFIXES = (
    'BAGG', 'RAGG', 'Vlan', 'InLoop', 'NULL', 'MGE', 'REG0',
    'HA', 'Loop', 'Tunnel', 'Dialer', 'Virtual', 'Eth',
)

def is_physical(name: str) -> bool:
    up = name.upper()
    return (not up.startswith(LOGICAL_PREFIXES)
            and re.match(r'^[A-Z0-9\-]+(?:/\d+){2,3}$', up) is not None)

ELECTRICAL_TYPES = {'1000_BASE_T_AN_SFP'}


def parse_brief(raw: str):
    """返回 {短名: (link, desc)}"""
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
    rec = XunjianRecord.objects.order_by('-time').first()
    print(f'=== 空闲光模块统计 v3 — 巡检: {rec.time} ({rec.device_count}台) ===\n')

    # 设备 → brief 状态
    brief_map = {}
    for cr in CheckResult.objects.filter(time=rec.time, command='display interface brief'):
        if cr.result:
            brief_map[cr.device] = parse_brief(cr.result)

    # [型号] -> [总, ADM, DOWN无描述, DOWN有描述, UP]
    model_stats = defaultdict(lambda: [0, 0, 0, 0, 0])
    site_stats = defaultdict(lambda: defaultdict(lambda: [0, 0, 0, 0, 0]))
    per_device = defaultdict(list)
    electrical = [0, 0]  # [总数, 空闲]

    for cr in CheckResult.objects.filter(time=rec.time, command='display transceiver interface'):
        if not cr.result:
            continue
        dev = cr.device
        br = brief_map.get(dev, {})
        site = '知识城' if 'zscidc' in dev else ('化龙' if 'hualong' in dev else '未知')

        blocks = re.split(r'(?=^\S+\s+transceiver information:)', cr.result, flags=re.M)
        for blk in blocks:
            m = re.match(r'^(\S+)\s+transceiver information:', blk)
            if not m:
                continue
            if 'The transceiver is absent' in blk:
                continue
            t = re.search(r'Transceiver Type\s*:\s*(\S+)', blk)
            ttype = t.group(1) if t else 'UNKNOWN'

            port = normalize_ifname(m.group(1))
            if not is_physical(port):
                continue

            if ttype in ELECTRICAL_TYPES:
                electrical[0] += 1
                st, desc = br.get(port, ('?', ''))
                if st in ('DOWN', 'ADM'):
                    electrical[1] += 1
                continue

            st, desc = br.get(port, ('?', ''))
            s = model_stats[ttype]
            s[0] += 1
            site_stats[site][ttype][0] += 1
            if st == 'ADM':
                s[1] += 1
                site_stats[site][ttype][1] += 1
                per_device[dev].append(f'{port}  ADM(NO-USE)')
            elif st == 'DOWN':
                if desc.strip():
                    s[3] += 1
                    site_stats[site][ttype][3] += 1
                    per_device[dev].append(f'{port}  DOWN(有描述:{desc[:22]})')
                else:
                    s[2] += 1
                    site_stats[site][ttype][2] += 1
                    per_device[dev].append(f'{port}  DOWN(无描述)')
            # UP 不计

    # ── 型号汇总 ──
    print(f'{"型号 (Transceiver Type)":28s} {"总数":>6s} {"ADM":>6s} {"DOWN无描述":>8s} {"DOWN有描述":>8s} {"UP在用":>7s} {"真空闲":>6s} {"空闲率":>7s}')
    print('-' * 100)
    sorted_keys = sorted(model_stats.keys(), key=lambda k: -model_stats[k][0])
    for key in sorted_keys:
        s = model_stats[key]
        total, adm, dn, dd, up = s
        idle = adm + dn
        rate = idle / total * 100 if total else 0
        print(f'{key:28s} {total:>6d} {adm:>6d} {dn:>8d} {dd:>8d} {up:>7d} {idle:>6d} {rate:>6.1f}%')

    if electrical[0]:
        print(f'\n[电口模块已排除] 1000_BASE_T_AN_SFP: 总数 {electrical[0]}，空闲 {electrical[1]}')

    grand = [sum(s[i] for s in model_stats.values()) for i in range(5)]
    total, adm, dn, dd, _up = grand
    up_used = total - adm - dn - dd
    idle = adm + dn
    print(f'\n=== 汇总（仅光模块）===')
    print(f'光模块总数: {total}')
    print(f'  真空闲(ADM+DOWN无描述): {idle}  ← 统计口径')
    print(f'    ├─ ADM(NO-USE 标注): {adm}')
    print(f'    └─ DOWN 且无描述: {dn}')
    print(f'  DOWN但有用途描述(对端未起): {dd}')
    print(f'  UP在用: {up_used}')
    print(f'真空闲率: {idle/total*100:.1f}%')

    print(f'\n=== 站点 × 型号 真空闲 ===')
    for site in ('化龙', '知识城'):
        print(f'\n[{site}]')
        for ttype, s in sorted(site_stats[site].items(), key=lambda x: -(x[1][1] + x[1][2])):
            idle = s[1] + s[2]
            if idle:
                print(f'  {ttype:28s} 真空闲 {idle:>4d}（ADM {s[1]} + DOWN {s[2]}）')

    # ── 设备明细 ──
    print(f'\n=== 设备 × 型号 × 空闲端口明细 ===')
    for dev in sorted(per_device.keys()):
        if per_device[dev]:
            print(f'\n{dev}:')
            for p in per_device[dev]:
                print(f'    {p}')


if __name__ == '__main__':
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main()
    text = buf.getvalue()
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        print(text)
    except Exception:
        pass
    out = '空闲光模块统计v3_20260803.txt'
    with open(out, 'w', encoding='utf-8') as f:
        f.write(text)
    print(f'\n报告已写入: {out}')
