"""按站点统计空闲光模块（含光转电口），确认替换需求。

口径：
- 真空闲 = ADM(NO-USE) + DOWN无描述
- 光转电口（1000_BASE_T_AN_SFP 电口模块）单独列出但计入"可用替换"池
- 型号归并：Ordering Name 与 Vendor Part Number 是同一模块的两种输出
"""
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

# 型号归并：transceiver type → (显示名, 速率, 类型)
MODEL_NORM = {
    '10G_BASE_SR_SFP':      ('10G 多模 SFP (SR-MM850)', '10G', '光'),
    '10G_BASE_LR_SFP':      ('10G 单模 SFP (LR-SM1310)', '10G', '光'),
    '40G_BASE_CSR4_QSFP_PLUS': ('40G 多模 QSFP (CSR4-MM850)', '40G', '光'),
    '40G_BASE_LR4_QSFP_PLUS': ('40G 单模 QSFP (LR4-WDM1300)', '40G', '光'),
    '100G_BASE_SR4_QSFP28': ('100G 多模 QSFP28 (SR4-MM850)', '100G', '光'),
    '1000_BASE_SX_SFP':     ('1G 多模 SFP (SX-MM850)', '1G', '光'),
    '1000_BASE_T_AN_SFP':   ('1G 电口 SFP (光转电/铜缆)', '1G', '电'),
    'UNKNOWN_SFP_PLUS':     ('未知 SFP+', '?', '?'),
}

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
    print(f'=== 按站点空闲光模块统计 — 巡检: {rec.time} ({rec.device_count}台) ===\n')

    brief_map = {}
    for cr in CheckResult.objects.filter(time=rec.time, command='display interface brief'):
        if cr.result:
            brief_map[cr.device] = parse_brief(cr.result)

    # site -> model_key -> [总, ADM, DOWN无描述, DOWN有描述]
    stats = defaultdict(lambda: defaultdict(lambda: [0, 0, 0, 0]))
    dev_detail = defaultdict(lambda: defaultdict(list))

    for cr in CheckResult.objects.filter(time=rec.time, command='display transceiver interface'):
        if not cr.result:
            continue
        dev = cr.device
        site = '知识城' if 'zscidc' in dev else ('化龙' if 'hualong' in dev else '未知')
        br = brief_map.get(dev, {})
        for blk in re.split(r'(?=^\S+\s+transceiver information:)', cr.result, flags=re.M):
            m = re.match(r'^(\S+)\s+transceiver information:', blk)
            if not m:
                continue
            if 'The transceiver is absent' in blk:
                continue
            t = re.search(r'Transceiver Type\s*:\s*(\S+)', blk)
            ttype = t.group(1) if t else 'UNKNOWN'
            port = norm(m.group(1))
            if not phys(port):
                continue
            st, desc = br.get(port, ('?', ''))
            s = stats[site][ttype]
            s[0] += 1
            if st == 'ADM':
                s[1] += 1
                dev_detail[site][ttype].append(f'{dev.split(".")[0]} {port} (ADM)')
            elif st == 'DOWN':
                if desc.strip():
                    s[3] += 1
                else:
                    s[2] += 1
                    dev_detail[site][ttype].append(f'{dev.split(".")[0]} {port} (DOWN)')

    # ── 按站点输出 ──
    for site in ('化龙', '知识城', '未知'):
        if site not in stats:
            continue
        print(f'╔══ {site} ═══════════════════════════════════════════════')
        rows = []
        for ttype, s in stats[site].items():
            total, adm, dn, dd = s
            idle = adm + dn
            name, speed, kind = MODEL_NORM.get(ttype, (ttype, '?', '?'))
            rows.append((speed, kind, name, total, adm, dn, dd, idle))
        rows.sort(key=lambda r: (-int(r[0].rstrip('G').rstrip('?') or 0), r[1], r[2]))

        print(f'{"型号":35s} {"总":>5s} {"ADM":>5s} {"DOWN":>5s} {"有描述":>5s} {"真空闲":>6s} {"空闲率":>7s}')
        print('-' * 75)
        for speed, kind, name, total, adm, dn, dd, idle in rows:
            rate = idle / total * 100 if total else 0
            tag = ' [光转电]' if kind == '电' else ''
            print(f'{name:35s} {total:>5d} {adm:>5d} {dn:>5d} {dd:>5d} {idle:>6d} {rate:>6.1f}%{tag}')
        site_total = sum(r[7] for r in rows if r[1] == '光')
        site_all = sum(r[7] for r in rows)
        print(f'{"":35s} 光模块真空闲: {site_total} | 含光转电口: {site_all}')
        print()

    # ── 汇总（两站合计）──
    print('╔══ 两站合计 ═══════════════════════════════════════════════')
    merged = defaultdict(lambda: [0, 0, 0, 0])
    for site in stats:
        for ttype, s in stats[site].items():
            for i in range(4):
                merged[ttype][i] += s[i]
    rows = []
    for ttype, s in merged.items():
        total, adm, dn, dd = s
        name, speed, kind = MODEL_NORM.get(ttype, (ttype, '?', '?'))
        rows.append((speed, kind, name, total, adm, dn, dd, adm + dn))
    rows.sort(key=lambda r: (-int(r[0].rstrip('G').rstrip('?') or 0), r[1], r[2]))
    print(f'{"型号":35s} {"总":>5s} {"ADM":>5s} {"DOWN":>5s} {"有描述":>5s} {"真空闲":>6s} {"空闲率":>7s}')
    print('-' * 75)
    for speed, kind, name, total, adm, dn, dd, idle in rows:
        rate = idle / total * 100 if total else 0
        tag = ' [光转电]' if kind == '电' else ''
        print(f'{name:35s} {total:>5d} {adm:>5d} {dn:>5d} {dd:>5d} {idle:>6d} {rate:>6.1f}%{tag}')

    # ── 设备 × 型号 明细 ──
    print('\n════ 设备级空闲明细 ════')
    for site in ('化龙', '知识城'):
        print(f'\n[{site}]')
        for ttype, lst in sorted(dev_detail[site].items(), key=lambda x: -len(x[1])):
            name, speed, kind = MODEL_NORM.get(ttype, (ttype, '?', '?'))
            print(f'  {name}: {len(lst)} 个')
            # 每行设备聚合成 设备: 端口列表
            bydev = defaultdict(list)
            for item in lst:
                d, p, st = item.split(' ')
                bydev[d].append(p)
            for d in sorted(bydev.keys()):
                print(f'      {d:12s} {", ".join(bydev[d])}')


if __name__ == '__main__':
    main()
