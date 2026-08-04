"""Comware (H3C) 解析器实现 —— 单一真源（canonical parsers）。

纯 Python、无 Django / 无 network_seek 依赖。所有 Comware 语义解析只存在本文件一份，
xunjian 的 sync_cmdb 与 network-seek 的 importer 均消费本模块，避免两套正则分叉。

返回「规范化 dict」（设计文档 §4 契约），下游各自适配：
  - sync_cmdb    : dict -> CMDB 表
  - network-seek : dict -> pydantic IR -> Neo4j

正则均经真实 H3C 回显校准（csw004 / fw003 / 化龙·知识城采集，2026-07-22~23）。
"""
import ipaddress
import re
from typing import Dict, List, Optional


# ───────────────────────── 工具 ─────────────────────────
def _speed_to_mbps(raw):
    raw = (raw or '').lower()
    m = re.search(r'(\d+)\s*(g|m|k)', raw)
    if not m:
        return 0
    val, unit = int(m.group(1)), m.group(2)
    if unit == 'g':
        return val * 1000
    if unit == 'm':
        return val
    if unit == 'k':
        return max(val // 1000, 0)
    return 0


def _ip_mask_to_cidr(ip, mask):
    try:
        net = ipaddress.IPv4Network(f'{ip}/{mask}', strict=False)
        return f'{ip}/{net.prefixlen}'
    except Exception:
        return ip


# ───────────────────────── 设备/版本 ─────────────────────────
def parse_version(text):
    """display version → dict(name/model/os_version/serial/uptime_days)"""
    out = {'name': '', 'model': '', 'os_version': '', 'serial': '', 'uptime_days': None}
    if not text:
        return out
    m = re.search(r'H3C\s+(.+?)\s+uptime', text)  # 多 token 型号（防火墙 SecPath M9000-X10）
    if m:
        out['model'] = m.group(1)
    m = re.search(r'Comware Software, Version\s+([\d.]+),\s*Release\s+(\S+)', text)
    if m:
        out['os_version'] = f'Comware {m.group(1)} {m.group(2)}'
    m = re.search(r'Device name:\s*(\S+)', text, re.IGNORECASE)
    if m:
        out['name'] = m.group(1)
    m = re.search(r'SN:\s*(\S+)', text)
    if m:
        out['serial'] = m.group(1)
    weeks = days = 0
    mw = re.search(r'uptime is\s+(\d+)\s+week', text, re.IGNORECASE)
    if mw:
        weeks = int(mw.group(1))
    md = re.search(r'uptime is\s+(?:\d+\s+weeks?,\s+)?(\d+)\s+day', text, re.IGNORECASE)
    if md:
        days = int(md.group(1))
    if weeks or days:
        out['uptime_days'] = weeks * 7 + days
    return out


# ───────────────────────── 接口（display interface brief） ─────────────────────────
def parse_interface_brief(text):
    """display interface brief → list of dict(name/oper_status/admin_status/speed_mbps/duplex/vlan_id/description)

    兼容两种块（库内真实回显）：
      - route mode:  Interface Link Protocol PrimaryIP ...（三层，无 speed/duplex）
      - bridge mode: Interface Link Speed Duplex Type PVID Description（二层）
    """
    rows = []
    if not text:
        return rows
    in_route = False
    in_bridge = False
    for line in text.splitlines():
        s = line.strip()
        if not s or set(s) <= set('-|= '):
            continue
        low = s.lower()
        if 'in route mode' in low:
            in_route, in_bridge = True, False
            continue
        if 'in bridge mode' in low:
            in_route, in_bridge = False, True
            continue
        if low.startswith('interface') or ('link' in low and 'speed' in low):
            continue
        m = re.match(r'^(\S+)\s+(UP|DOWN)\s+(\S+)\s+(\S+)', s, re.IGNORECASE)
        if not m:
            continue
        ifname = m.group(1)
        link = m.group(2).upper()
        if in_route:
            proto = m.group(3).upper()
            rows.append({
                'name': ifname, 'oper_status': link, 'admin_status': proto,
                'speed_mbps': 0, 'duplex': 'auto', 'vlan_id': None, 'description': '',
            })
        else:
            speed_raw, duplex_raw = m.group(3), m.group(4)
            speed = _speed_to_mbps(speed_raw)
            duplex = 'full' if 'full' in duplex_raw.lower() else ('half' if 'half' in duplex_raw.lower() else 'auto')
            rest = s[m.end():].strip()
            pvid = None
            mvid = re.match(r'(\d+)', rest)
            if mvid:
                pvid = int(mvid.group(1))
                desc = rest[mvid.end():].strip()
            else:
                desc = rest
            rows.append({
                'name': ifname, 'oper_status': link, 'admin_status': link,
                'speed_mbps': speed, 'duplex': duplex, 'vlan_id': pvid, 'description': desc,
            })
    return rows


# ───────────────────────── 运行配置（VLAN / IP / ACL / VRF） ─────────────────────────
def parse_running_config(text):
    """display current-configuration → dict(vlans/interface_vlans/ips/acls/rules/vrfs/services/asn/nat)

    vlans:          List[dict(vlan_id, name)]
    interface_vlans:List[dict(interface, vlan_id)]
    ips:            List[dict(interface_name, cidr, vrf)]
    acls:           List[dict(name, acl_type)]
    rules:          List[dict(rule_id, acl_name, action, source_ip, dest_ip, protocol)]
    vrfs:           List[dict(name, rd, rt_import, rt_export)]
    services:       List[dict(type, address, port)]
    asn:            str (AS 号，无 BGP 则为空)
    """
    vlans: List[Dict] = []
    interface_vlans: List[Dict] = []
    ips: List[Dict] = []
    acls: List[Dict] = []
    rules: List[Dict] = []
    vrfs: List[Dict] = []
    services: List[Dict] = []
    asn = ''

    if not text:
        return dict(vlans=vlans, interface_vlans=interface_vlans, ips=ips,
                    acls=acls, rules=rules, vrfs=vrfs,
                    services=services, asn=asn)

    # VLAN 定义
    for m in re.finditer(r'^\s*vlan\s+(\d+)', text, re.MULTILINE):
        vid = int(m.group(1))
        name = ''
        seg = text[m.end():m.end() + 60]
        mn = re.search(r'description\s+(.+)', seg)
        if mn:
            name = mn.group(1).strip()
        vlans.append({'vlan_id': vid, 'name': name})

    # 接口块（修复 IP→VRF 关联）
    blocks = re.split(r'(?=^interface\s)', text, flags=re.MULTILINE)
    for blk in blocks:
        mif = re.search(r'^interface\s+(\S+)', blk, re.MULTILINE)
        if not mif:
            continue
        intf = mif.group(1)
        # 当前接口的 VRF 上下文（NetBox 联动 · 2026-07-28）
        vrf_name = ''
        mvr = re.search(r'ip binding vpn-instance\s+(\S+)', blk)
        if mvr:
            vrf_name = mvr.group(1)
        mav = re.search(r'port access vlan\s+(\d+)', blk)
        if mav:
            interface_vlans.append({'interface': intf, 'vlan_id': int(mav.group(1))})
        mtv = re.search(r'port trunk permit vlan\s+(\d+)', blk)
        if mtv:
            interface_vlans.append({'interface': intf, 'vlan_id': int(mtv.group(1))})
        for mip in re.finditer(r'ip address\s+(\d+\.\d+\.\d+\.\d+)\s+(\d+\.\d+\.\d+\.\d+)', blk):
            cidr = _ip_mask_to_cidr(mip.group(1), mip.group(2))
            ips.append({'interface_name': intf, 'cidr': cidr, 'vrf': vrf_name})
        if vrf_name:
            # VRF 去重（同 VRF 名只记一条，保留 Route Target）
            if not any(v['name'] == vrf_name for v in vrfs):
                vrfs.append({'name': vrf_name, 'rd': vrf_name, 'rt_import': [], 'rt_export': []})
            # 独立 route-target 行
            for mrt in re.finditer(r'route-target\s+(import|export)\s+(\S+)', blk):
                target_vrf = next((v for v in vrfs if v['name'] == vrf_name), None)
                if target_vrf:
                    key = 'rt_import' if mrt.group(1) == 'import' else 'rt_export'
                    if mrt.group(2) not in target_vrf[key]:
                        target_vrf[key].append(mrt.group(2))

    # ACL
    for m in re.finditer(r'^\s*acl\s+(?:advanced|basic|number)\s+(\d+)', text, re.MULTILINE):
        acls.append({'name': m.group(1), 'acl_type': 'extended'})
    for m in re.finditer(r'^\s*rule\s+(\d+)\s+(permit|deny)\s*(.*)', text, re.MULTILINE | re.IGNORECASE):
        rule_id = int(m.group(1))
        action = m.group(2).lower()
        rest = m.group(3)
        acl_name = _nearest_acl(text, m.start())
        if not acl_name:
            continue
        src = re.search(r'source\s+(\d+\.\d+\.\d+\.\d+)\s+(\d+\.\d+\.\d+\.\d+)', rest)
        dst = re.search(r'destination\s+(\d+\.\d+\.\d+\.\d+)\s+(\d+\.\d+\.\d+\.\d+)', rest)
        proto = 'ip'
        if 'tcp' in rest.lower():
            proto = 'tcp'
        elif 'udp' in rest.lower():
            proto = 'udp'
        rules.append({'rule_id': rule_id, 'acl_name': acl_name, 'action': action,
                      'source_ip': src.group(1) if src else '', 'dest_ip': dst.group(1) if dst else '',
                      'protocol': proto})

    # ASN（NetBox 联动 · 2026-07-28）
    masn = re.search(r'(?:router\s+)?bgp\s+(\d+)', text, re.I)
    if masn:
        asn = masn.group(1)

    # Services（NTP / Syslog / DNS / SNMP）（NetBox 联动 · 2026-07-28）
    for mntp in re.finditer(r'ntp-service\s+server\s+(\S+)', text, re.I):
        services.append({'type': 'NTP', 'address': mntp.group(1), 'port': 123})
    for mlog in re.finditer(r'info-center\s+loghost\s+(\S+)', text, re.I):
        services.append({'type': 'Syslog', 'address': mlog.group(1), 'port': 514})
    for mdns in re.finditer(r'dns\s+server\s+(\S+)', text, re.I):
        services.append({'type': 'DNS', 'address': mdns.group(1), 'port': 53})
    if re.search(r'snmp-agent', text, re.I):
        services.append({'type': 'SNMP', 'address': '', 'port': 161})

    return dict(vlans=vlans, interface_vlans=interface_vlans, ips=ips,
                acls=acls, rules=rules, vrfs=vrfs,
                services=services, asn=asn)


def _nearest_acl(rc: str, pos: int) -> str:
    best = None
    for m in re.finditer(r'^\s*acl\s+(?:advanced|basic|number)\s+(\d+)', rc, re.MULTILINE):
        if m.start() < pos:
            best = m.group(1)
    return best or ''


# ───────────────────────── LLDP 邻居 ─────────────────────────
def parse_lldp(text):
    """display lldp neighbor-information list → list of dict(local_port/peer_device/peer_port)

    库内真实回显为空格对齐的固定列宽表格（非 | 分隔）：
        Local Interface Chassis ID      Port ID                    System Name
        XGE1/0/1        8c2a-8e41-ee7f  8c2a-8e41-ee7f             -
        HGE1/0/25       f4e9-75bf-8400  FortyGigE1/4/0/3           csw001&002...
    兼容旧版 | 分隔格式。列：0=本地口 1=ChassisID 2=PortID 3=SystemName。
    """
    nbrs = []
    seen = set()
    if not text:
        return nbrs
    for line in text.splitlines():
        s = line.strip()
        if not s or set(s) <= set('-|= '):
            continue
        if any(k in s for k in ('Local Interface', 'Chassis ID', 'Port ID', 'System Name', 'Total entries')):
            continue
        if 'nearest' in s.lower():
            continue
        if '|' in s:
            parts = [p.strip() for p in s.split('|')]
        else:
            parts = s.split()
        if len(parts) < 4:
            continue
        key = (parts[0], parts[2], parts[3])
        if key in seen:
            continue
        seen.add(key)
        nbrs.append({'local_port': parts[0], 'peer_port': parts[2], 'peer_device': parts[3]})
    return nbrs


# ───────────────────────── VLAN（display vlan brief） ─────────────────────────
def parse_vlan_brief(text):
    """display vlan brief → list of int(vlan_id)"""
    ids = set()
    if not text:
        return []
    m = re.search(r'VLANs include:\s*(.+)', text)
    if m:
        for tok in re.split(r'[,\s]+', m.group(1)):
            # "1(default)" -> 1：先去 (default) 再剥两侧括号，避免 rstrip(')') 破坏替换
            tok = tok.strip().replace('(default)', '').strip('()')
            if tok.isdigit():
                ids.add(int(tok))
    for m in re.finditer(r'^\s*(\d{1,4})\s+Enabled', text, re.MULTILINE):
        ids.add(int(m.group(1)))
    for m in re.finditer(r'^\s*(\d{1,4})\s+VLAN\b', text, re.MULTILINE):
        ids.add(int(m.group(1)))
    return sorted(ids)


# ───────────────────────── CPU / 内存 / 序列号 ─────────────────────────
def parse_cpu_usage(text):
    """display cpu-usage → 5秒CPU使用率(%)，兼容 H3C V7 多种输出格式。"""
    if not text:
        return None
    patterns = [
        r'CPU utilization in last 5 seconds:\s*(\d+(?:\.\d+)?)%',
        r'CPU 5sec:\s*(\d+(?:\.\d+)?)%',
        r'5 seconds:\s*(\d+(?:\.\d+)?)%',
        r'in last 5 seconds:\s*(\d+(?:\.\d+)?)%',
        r'(\d+(?:\.\d+)?)%\s+in last 5 seconds',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            return float(m.group(1))
    return None


def parse_memory_free(text):
    """display memory → FreeRatio 空闲率(%)。"""
    if not text:
        return None
    m = re.search(r'Mem:.*?([\d.]+)%', text)
    return float(m.group(1)) if m else None


def parse_flash_usage(text):
    """dir flash:/ → Flash 存储利用情况。

    返回 dict: {total_kb, free_kb, used_kb, used_percent, free_percent}
    兼容 H3C V7 输出：
        3710740 KB total (3490948 KB free)
    total/free 单位需一致（KB/MB/GB/bytes 均可，单位不一致则跳过，避免误判）。
    若解析不到必要字段返回 None。
    """
    if not text:
        return None
    UNIT = r'(KB|MB|GB|bytes)?'

    def _resolve(t, f, u1, u2):
        # 两单位都存在且不一致 → 无法可靠计算利用率
        if u1 and u2 and u1.upper() != u2.upper():
            return None
        return int(t), int(f)

    # 主格式：  <total> KB total (<free> KB free[, remaining XX%])
    # 兼容防火墙 (VFAT) 头部及末尾 "remaining 65.32%" 后缀
    m = re.search(r'(\d+)\s*' + UNIT + r'\s*total\s*\(\s*(\d+)\s*' + UNIT + r'\s*free\b[^)]*\)', text, re.I)
    if m:
        res = _resolve(m.group(1), m.group(3), m.group(2), m.group(4))
    else:
        # 兜底：不限括号/顺序，分别找 total / free 附近的数字
        mt = re.search(r'(\d+)\s*' + UNIT + r'\s*total', text, re.I)
        mf = re.search(r'(\d+)\s*' + UNIT + r'\s*free', text, re.I)
        if not (mt and mf):
            return None
        res = _resolve(mt.group(1), mf.group(1), mt.group(2), mf.group(2))
    if res is None:
        return None
    total, free = res
    if total <= 0:
        return None
    used = total - free
    return {
        'total_kb': total,
        'free_kb': free,
        'used_kb': used,
        'used_percent': round(used / total * 100, 1),
        'free_percent': round(free / total * 100, 1),
    }


def parse_manuinfo(text):
    """display device manuinfo → 序列号(主槽位/机框)。

    兼容 格式A: Device Serial Number: / 格式B: DEVICE SERIAL NUMBER : / 格式C: SN:
    多槽位设备只取首个非空序列号。
    """
    if not text:
        return ''
    serials = []
    for m in re.finditer(r'Device Serial Number\s*[:：]\s*(\S+)', text, re.I):
        s = m.group(1).strip().rstrip(';')
        if s and s.upper() != 'N/A':
            serials.append(s)
    if not serials:
        m = re.search(r'DEVICE SERIAL NUMBER\s*[:：]\s*(\S+)', text, re.I)
        if m:
            serials.append(m.group(1).strip().rstrip(';'))
    if not serials:
        m = re.search(r'\bSN\s*[:：]\s*(\S+)', text, re.I)
        if m:
            serials.append(m.group(1).strip().rstrip(';'))
    seen = []
    for s in serials:
        if s not in seen:
            seen.append(s)
    return seen[0] if seen else ''


# ───────────────────────── 路由表（display ip routing-table） ─────────────────────────
def parse_route_table(text):
    """display ip routing-table → list of dict(dest_subnet/protocol/next_hop/egress_interface)"""
    out = []
    if not text:
        return out
    for line in text.splitlines():
        s = line.strip()
        m = re.match(r'^(\d+\.\d+\.\d+\.\d+/\d+)\s+(\S+)\s+\d+\s+\d+\s+(\S+)\s+(\S+)', s)
        if m:
            out.append(dict(dest_subnet=m.group(1), protocol=m.group(2),
                            next_hop=m.group(3), egress_interface=m.group(4)))
    return out


# ═════════════════════════════════════════════════════════════════════════════════
# 高可用 / 堆叠 / 安全策略（2026-07-23 用 csw004 / fw003 真实回显校准）
# 以下返回 dict（非 IR），统一交给下游（sync_cmdb / network-seek）适配。
# ═════════════════════════════════════════════════════════════════════════════════

# ───────────────────────── 堆叠 / IRF（display irf） ─────────────────────────
def parse_irf(text):
    """解析 display irf → dict(name, members)。

    返回 dict: {'name': f"{device}-IRF", 'members': [成员ID...]}；无成员返回 None。
    """
    if not text or len(text) < 10:
        return None
    members: List[str] = []
    domain = ''
    mdom = re.search(r'IRF\s+Domain\s*ID\s*:?\s*(\d+)', text, re.IGNORECASE)
    if mdom:
        domain = mdom.group(1)
    for line in text.splitlines():
        m = re.match(r'^\s*\**\s*(\d+)\s+(Master|Standby|Slave)\b', line, re.IGNORECASE)
        if m:
            members.append(m.group(1))
    if not members:
        return None
    # 注意：Stack.name 形如 "{device_name}-IRF"，依赖设备名，由下游（network-seek 适配层）
    # 在拿到 device_name 后拼接，本单一真源只回传 members 与 domain。
    return dict(members=members, domain=domain)


# ───────────────────────── M-LAG（display m-lag summary） ─────────────────────────
def parse_mlag_summary(text):
    """解析 display m-lag summary → 本端/对端机名 + 角色 + 状态 + 各 M-LAG 组健康。

    返回 dict:
      {'local', 'peer', 'role', 'state', 'keepalive',
       'groups': [{'iface','group','local_state','peer_state'}, ...]}
    既无系统信息又无组表 → 返回 None。
    """
    if not text or len(text) < 10:
        return None

    local = peer = role = state = keepalive = ''

    m_local = re.search(r'Local\s+System\s+Information\b', text, re.IGNORECASE)
    if m_local:
        blk = text[m_local.end():]
        mpeer = re.search(r'Peer\s+System\s+Information\b', blk, re.IGNORECASE)
        local_blk = blk[:mpeer.start()] if mpeer else blk
        ml = re.search(r'System\s+Name\s*:?\s*(\S+)', local_blk, re.IGNORECASE)
        if ml:
            local = ml.group(1)
        mr = re.search(r'Role\s*:?\s*(\S+)', local_blk, re.IGNORECASE)
        if mr:
            role = mr.group(1)
        ms = re.search(r'State\s*:?\s*(\S+)', local_blk, re.IGNORECASE)
        if ms:
            state = ms.group(1)
        mk = re.search(r'Keepalive\s+Status\s*:?\s*(\S+)', local_blk, re.IGNORECASE)
        if mk:
            keepalive = mk.group(1)
        if mpeer:
            peer_blk = blk[mpeer.end():]
            mp = re.search(r'System\s+Name\s*:?\s*(\S+)', peer_blk, re.IGNORECASE)
            if mp:
                peer = mp.group(1)

    groups = []
    for line in text.splitlines():
        s = line.strip()
        if 'M-LAG IF' in s or 'M-LAG group' in s:
            continue
        toks = s.split()
        if len(toks) < 5:
            continue
        if not toks[1].isdigit():
            continue
        groups.append(dict(iface=toks[0], group=int(toks[1]),
                            local_state=toks[2], peer_state=toks[3]))

    if not local and not peer and not groups:
        return None
    return dict(local=local, peer=peer, role=role, state=state,
                keepalive=keepalive, groups=groups)


# ───────────────────────── 链路聚合（display link-aggregation verbose） ─────────────────────────
def parse_link_agg_verbose(text):
    """解析 display link-aggregation verbose → 每个聚合口的成员/模式/本端-对端系统ID。

    返回 [{'lag_name','mode','local_system_id','remote_system_id','local_ports'}, ...]
    """
    out: List[Dict] = []
    if not text:
        return out
    blocks = re.split(r'(?=^\s*Aggregate\s+Interface\s*:)', text,
                      flags=re.MULTILINE | re.IGNORECASE)
    sysid_re = re.compile(r'0x[0-9a-fA-F]+,\s*[\w-]+')
    for blk in blocks:
        mif = re.search(r'Aggregate\s+Interface\s*:?\s*(\S+)', blk, re.IGNORECASE)
        if not mif:
            continue
        lag_name = mif.group(1)
        mode_m = re.search(r'Aggregation\s+Mode\s*:?\s*(\S+)', blk, re.IGNORECASE)
        mode = mode_m.group(1) if mode_m else ''
        local_sysid = ''
        mls = re.search(r'System\s+ID\s*:?\s*(' + sysid_re.pattern + r')', blk, re.IGNORECASE)
        if mls:
            local_sysid = mls.group(1)
        local_blk = remote_blk = ''
        ml = re.search(r'\bLocal\s*:', blk)
        mr = re.search(r'\bRemote\s*:', blk)
        if ml and mr:
            local_blk = blk[ml.start():mr.start()]
            remote_blk = blk[mr.start():]
        elif ml:
            local_blk = blk[ml.start():]
        elif mr:
            remote_blk = blk[mr.start():]

        def _ports(b):
            ports = []
            for ln in b.splitlines():
                s = ln.strip()
                m = re.match(r'^(\S+)\s+(S|U|I)\b', s)
                if m:
                    ports.append(m.group(1).replace('(R)', '').strip('()'))
            return ports

        local_ports = _ports(local_blk)
        remote_sysid = ''
        msr = sysid_re.search(remote_blk)
        if msr:
            remote_sysid = msr.group(0)
        out.append(dict(
            lag_name=lag_name, mode=mode,
            local_system_id=local_sysid, remote_system_id=remote_sysid,
            local_ports=local_ports,
        ))
    return out


# ───────────────────────── 链路聚合（display link-aggregation summary，表格） ─────────────────────────
def parse_link_agg_summary(text):
    """解析 display link-aggregation summary 的**表格**回显 → [LAG dict, ...]。

    返回 [{'lag_name','mode','partner_id','selected_ports','unselected_ports'}, ...]
    """
    out: List[Dict] = []
    if not text:
        return out
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith('-') or s.startswith('AGG') \
           or s.startswith('Interface') or 'Aggregation' in s \
           or 'Loadsharing' in s or 'Actor System' in s or 'BAGG --' in s:
            continue
        toks = s.split()
        if len(toks) < 4:
            continue
        if not re.match(r'^(BAGG|RAGG|BLAGG|SCH-B)\d*$', toks[0], re.IGNORECASE):
            continue
        if toks[1] not in ('D', 'S'):
            continue
        lag_name = toks[0]
        mode = 'Dynamic' if toks[1] == 'D' else 'Static'
        pparts = []
        i = 2
        while i < len(toks) and not toks[i].isdigit():
            pparts.append(toks[i])
            i += 1
        partner_id = ' '.join(pparts) if pparts and pparts != ['None'] else ''
        try:
            selected = int(toks[i])
        except (ValueError, IndexError):
            selected = 0
        try:
            unselected = int(toks[i + 1])
        except (ValueError, IndexError):
            unselected = 0
        out.append(dict(lag_name=lag_name, mode=mode, partner_id=partner_id,
                        selected_ports=selected, unselected_ports=unselected))
    return out


# ───────────────────────── VRRP（display vrrp [verbose]） ─────────────────────────
def parse_vrrp(text):
    """解析 display vrrp / display vrrp verbose → [VRRP dict, ...]（每接口每组一条）。

    返回 [{'group_id','virtual_ip','master_ip','role','priority','vlan_id'}, ...]
    FW 未配置时：'VRRP4 is not configured.' → 返回 []。
    """
    out: List[Dict] = []
    if not text:
        return out
    if 'not configured' in text.lower():
        return out

    cur_intf = ''
    gid = None
    role = 'backup'
    vip = ''
    master_ip = ''
    prio = 100
    vlan_id = None

    def _emit():
        if gid is not None and cur_intf:
            out.append(dict(group_id=gid, virtual_ip=vip, master_ip=master_ip,
                            role=role, priority=prio, vlan_id=vlan_id))

    for line in text.splitlines():
        s = line.strip()
        mif = re.search(r'Interface\s+(\S+)', s, re.IGNORECASE)
        if mif:
            _emit()
            cur_intf = mif.group(1)
            gid = None
            role = 'backup'
            vip = ''
            master_ip = ''
            prio = 100
            vlan_id = None
            mv = re.search(r'Vlan-interface\s*(\d+)', cur_intf, re.IGNORECASE)
            if mv:
                vlan_id = int(mv.group(1))
            continue
        mg = re.search(r'VRID\s*:?\s*(\d+)', s, re.IGNORECASE)
        if mg:
            gid = int(mg.group(1))
            continue
        mr = re.search(r'State\s*:?\s*(\S+)', s, re.IGNORECASE)
        if mr:
            role = 'master' if mr.group(1).lower().startswith('master') else 'backup'
            continue
        mvip = re.search(r'Virtual\s+IP\s*:?\s*(\d+\.\d+\.\d+\.\d+)', s, re.IGNORECASE)
        if mvip:
            vip = mvip.group(1)
            continue
        mmip = re.search(r'Master\s+IP\s*:?\s*(\d+\.\d+\.\d+\.\d+)', s, re.IGNORECASE)
        if mmip:
            master_ip = mmip.group(1)
            continue
        mp = re.search(r'(?:Running|Config)\s*Pri\s*:?\s*(\d+)', s, re.IGNORECASE)
        if mp:
            prio = int(mp.group(1))
            continue
    _emit()
    return out


# ───────────────────────── 安全域（display security-zone） ─────────────────────────
def parse_security_zone(text):
    """解析 display security-zone → [dict(name, interfaces), ...]。

    关键字是 **Name: <zone>**（不是 "Zone:"）；成员接口缩进列出，"None" 表示无成员。
    """
    out: List[Dict] = []
    if not text:
        return out
    cur_name = ''
    cur_ifaces: List[str] = []
    in_members = False

    def _emit():
        if cur_name:
            out.append(dict(name=cur_name, interfaces=list(cur_ifaces)))

    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        mz = re.match(r'(?:Name|Zone)\s*:\s*(\S+)', s, re.IGNORECASE)
        if mz:
            _emit()
            cur_name = mz.group(1)
            cur_ifaces = []
            in_members = False
            continue
        if s.lower().startswith('members'):
            in_members = True
            continue
        if in_members:
            if s.lower() == 'none':
                continue
            if re.match(r'^[A-Za-z][\w./-]*$', s) and ':' not in s:
                cur_ifaces.append(s)
    _emit()
    return out


# ───────────────────────── 域间安全策略（display security-policy ip） ─────────────────────────
def parse_security_policy(text):
    """解析 display security-policy ip → [dict, ...]。

    返回 [{'rule_id','name','source_zones','dest_zones','source_ips','dest_ips','service','action'}, ...]
    一条规则可含多个 source/destination zone 与多个 IP（host/subnet 均归一为 IP 列表）。
    动作归一化为 permit / deny。
    """
    out: List[Dict] = []
    if not text:
        return out
    rid = 0
    name = ''
    sz: List[str] = []
    dz: List[str] = []
    sip: List[str] = []
    dip: List[str] = []
    svc = ''
    action = 'deny'

    def _emit():
        if rid:
            out.append(dict(rule_id=rid, name=name,
                            source_zones=list(sz), dest_zones=list(dz),
                            source_ips=list(sip), dest_ips=list(dip),
                            service=svc, action=action))

    blocks = re.split(r'(?=^\s*rule\s+\d+)', text, flags=re.MULTILINE | re.IGNORECASE)
    for blk in blocks:
        mrid = re.search(r'rule\s+(\d+)', blk, re.IGNORECASE)
        if not mrid:
            continue
        _emit()
        rid = int(mrid.group(1))
        name = ''
        sz = []; dz = []; sip = []; dip = []
        svc = ''; action = 'deny'
        mname = re.search(r'rule\s+\d+\s+name\s+(\S+)', blk, re.IGNORECASE)
        if mname:
            name = mname.group(1)
        for msz in re.finditer(r'source-zone\s+(\S+)', blk, re.IGNORECASE):
            sz.append(msz.group(1))
        for mdz in re.finditer(r'destination-zone\s+(\S+)', blk, re.IGNORECASE):
            dz.append(mdz.group(1))
        for mip in re.finditer(r'source-ip-host\s+(\d+\.\d+\.\d+\.\d+)', blk, re.IGNORECASE):
            sip.append(mip.group(1))
        for mip in re.finditer(r'source-ip-subnet\s+(\d+\.\d+\.\d+\.\d+)\s+\d+\.\d+\.\d+\.\d+', blk, re.IGNORECASE):
            sip.append(mip.group(1))
        for mip in re.finditer(r'destination-ip-host\s+(\d+\.\d+\.\d+\.\d+)', blk, re.IGNORECASE):
            dip.append(mip.group(1))
        for mip in re.finditer(r'destination-ip-subnet\s+(\d+\.\d+\.\d+\.\d+)\s+\d+\.\d+\.\d+\.\d+', blk, re.IGNORECASE):
            dip.append(mip.group(1))
        msvc = re.search(r'\n\s*service\s+(\S+)', blk, re.IGNORECASE)
        if msvc:
            svc = msvc.group(1)
        mact = re.search(r'\n\s*action\s+(\S+)', blk, re.IGNORECASE)
        if mact:
            raw = mact.group(1).lower()
            action = 'permit' if raw in ('permit', 'pass', 'allow') else 'deny'
    _emit()
    return out


# ───────────────────────── RBM 双机热备（display remote-backup-group status） ─────────────────────────
def parse_rbm_status(text):
    """解析 display remote-backup-group status → 防火墙 RBM（双机热备）状态 dict。

    返回 dict: {backup_mode, mgmt_role, running_role, running_status, data_channel_if,
                data_channel_state, local_ip, remote_ip, control_channel_status, peer_device}
    未配 RBM → 返回 None。
    """
    if not text or len(text) < 10:
        return None
    if 'not configured' in text.lower():
        return None

    def _g(pat):
        m = re.search(pat, text, re.IGNORECASE)
        return m.group(1) if m else ''

    backup_mode = _g(r'Backup\s+mode\s*:?\s*(\S+)')
    mgmt_role = _g(r'Device\s+management\s+role\s*:?\s*(\S+)')
    running_role = _g(r'Device\s+running\s+management\s+role\s*:?\s*(\S+)')
    running_status = _g(r'Device\s+running\s+status\s*:?\s*(\S+)')
    data_channel_if = _g(r'Data\s+channel\s+interface\s*:?\s*(\S+)')
    data_channel_state = _g(r'Data\s+channel\s+interface\s+current\s+state\s*:?\s*(\S+)')
    local_ip = _g(r'Local\s+IP\s*:?\s*(\d+\.\d+\.\d+\.\d+)')
    remote_ip = _g(r'Remote\s+IP\s*:?\s*(\d+\.\d+\.\d+\.\d+)')
    control_channel_status = _g(r'Control\s+channel\s+status\s*:?\s*(\S+)')
    if not (backup_mode or running_status or local_ip):
        return None
    return dict(
        backup_mode=backup_mode, mgmt_role=mgmt_role, running_role=running_role,
        running_status=running_status, data_channel_if=data_channel_if,
        data_channel_state=data_channel_state, local_ip=local_ip,
        remote_ip=remote_ip, control_channel_status=control_channel_status,
        peer_device='',
    )


# ───────────────────────── OSPF 控制面（display ospf peer / lsdb / routing） ─────────────────────────

def parse_ospf_peer(text):
    """解析 display ospf peer → [{neighbor_ip, router_id, area, state, interface, cost, network_type}]

    H3C 典型输出：

    OSPF Process 1 with Router ID 10.0.0.1
     Area 0.0.0.0 interface 10.0.1.1(Vlan-interface100)
      Neighbor 10.0.0.2
        Address: 10.0.0.2
        State: Full  Mode: Nbr is Master  Priority: 1
        DR: 10.0.0.1  BDR: 10.0.0.2
        Dead timer: 34s  Retrans timer: 5s
        Interface: Vlan-interface100
        Cost: 10  Network type: broadcast

    无邻居/未配置 → 返回 [].
    """
    out = []
    if not text or 'not configured' in text.lower():
        return out

    lines = text.splitlines()
    cur_area = ''
    cur_neighbor = {}
    in_neighbor = False

    for line in lines:
        s = line.strip()
        if not s:
            continue

        # Area 行
        ma = re.search(r'Area\s+(\S+)', s, re.IGNORECASE)
        if ma and 'Neighbor' not in s:
            cur_area = ma.group(1)
            continue

        # Neighbor 行
        mn = re.search(r'Neighbor\s+(\d+\.\d+\.\d+\.\d+)', s, re.IGNORECASE)
        if mn:
            if cur_neighbor.get('neighbor_ip'):
                out.append(dict(cur_neighbor))
            cur_neighbor = {'neighbor_ip': mn.group(1), 'area': cur_area,
                            'state': '', 'interface': '', 'cost': 0, 'network_type': ''}
            in_neighbor = True
            continue

        if not in_neighbor:
            continue

        # State
        ms = re.search(r'State:\s*(\S+)', s, re.IGNORECASE)
        if ms:
            cur_neighbor['state'] = ms.group(1)
            continue

        # Interface
        mi = re.search(r'Interface:\s*(\S+)', s, re.IGNORECASE)
        if mi:
            cur_neighbor['interface'] = mi.group(1)
            continue

        # Cost
        mc = re.search(r'Cost:\s*(\d+)', s, re.IGNORECASE)
        if mc:
            cur_neighbor['cost'] = int(mc.group(1))
            continue

        # Network type
        mt = re.search(r'Network\s+type:\s*(\S+)', s, re.IGNORECASE)
        if mt:
            cur_neighbor['network_type'] = mt.group(1)
            continue

    if cur_neighbor.get('neighbor_ip'):
        out.append(dict(cur_neighbor))

    return out


def parse_ospf_lsdb(text):
    """解析 display ospf lsdb → [{lsa_type, link_state_id, adv_router, age, seq, metric, links: []}]

    H3C 典型输出：

    OSPF Process 1 with Router ID 10.0.0.1
             Link State Database

             Area: 0.0.0.0
     Type      LinkState ID    AdvRouter          Age  Len   Sequence       Metric
     Router    10.0.0.1        10.0.0.1           123  48    0x80000005     0
     Router    10.0.0.2        10.0.0.2           100  48    0x80000004     0
     Network   10.0.0.1        10.0.0.1           95   32    0x80000003     0

    另含 Router-LSA 的 Link 详情（见表后缩进段落，当前忽略），
    后续可通过 display ospf lsdb router 补充。

    无 LSDB / 未配置 → 返回 [].
    """
    out = []
    if not text or 'not configured' in text.lower():
        return out

    lines = text.splitlines()
    cur_area = ''
    header_passed = False

    for line in lines:
        s = line.strip()
        if not s:
            continue

        # Area 行
        ma = re.search(r'Area:\s*(\S+)', s, re.IGNORECASE)
        if ma:
            cur_area = ma.group(1)
            continue

        # 表头行（跳过）
        if s.startswith('Type') and 'LinkState' in s:
            header_passed = True
            continue

        # 数据行：Type + LinkStateID + AdvRouter + Age + Len + Seq + Metric
        if header_passed:
            fields = s.split()
            if len(fields) >= 6 and fields[0][0].isupper():
                try:
                    entry = dict(
                        lsa_type=fields[0],
                        link_state_id=fields[1],
                        adv_router=fields[2],
                        age=int(fields[3]),
                        seq=fields[5],
                        metric=int(fields[6]) if len(fields) > 6 else 0,
                        area=cur_area,
                    )
                    out.append(entry)
                except (ValueError, IndexError):
                    continue

    return out


def parse_ospf_routing(text):
    """解析 display ospf routing → [{dest, cost, type, nexthop, adv_router, area}]

    H3C 典型输出：

    OSPF Process 1 with Router ID 10.0.0.1
             Routing Table

     Destination        Cost  Type     NextHop         AdvRouter       Area
     10.0.1.0/24        10    Stub     10.0.0.2        10.0.0.2        0.0.0.0
     10.0.2.0/24        20    Inter    10.0.0.3        10.0.0.3        0.0.0.0

    无路由 / 未配置 → 返回 [].
    """
    out = []
    if not text or 'not configured' in text.lower():
        return out

    lines = text.splitlines()
    header_passed = False

    for line in lines:
        s = line.strip()
        if not s:
            continue

        # 表头
        if s.startswith('Destination') and 'Cost' in s:
            header_passed = True
            continue

        # 数据行
        if header_passed:
            fields = s.split()
            if len(fields) >= 5 and '/' in fields[0]:
                try:
                    entry = dict(
                        dest=fields[0],
                        cost=int(fields[1]),
                        type=fields[2],
                        nexthop=fields[3],
                        adv_router=fields[4],
                        area=fields[5] if len(fields) > 5 else '',
                    )
                    out.append(entry)
                except (ValueError, IndexError):
                    continue

    return out


# ════════════════════════════════════════════════
#  电源 / 槽位 / NAT（NetBox 联动 · 2026-07-28）
# ════════════════════════════════════════════════
# ───────────────────────── 电源（display power） ─────────────────────────
def parse_power(text):
    """display power → [{id, status, type}, ...]

    H3C 典型输出（化龙/知识城 2026-07）：
      Power 1 State: Normal / Power 2 State: Normal
    兼容 Power 1: / State: / Type: 多行模式。
    """
    if not text:
        return []
    supplies = []
    current = {}
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        m = re.match(r'Power\s*(\d+)\s*(?::\s*|State\s*:\s*(\S+))', s, re.I)
        if m:
            if current and current.get('id'):
                supplies.append(current)
            current = {'id': m.group(1)}
            if m.group(2):
                current['status'] = m.group(2)
            continue
        if current:
            mt = re.match(r'State\s*:\s*(\S+)', s, re.I)
            if mt:
                current['status'] = mt.group(1)
                continue
            mt = re.match(r'Type\s*:\s*(\S+)', s, re.I)
            if mt:
                current['type'] = mt.group(1)
                continue
    if current and current.get('id'):
        supplies.append(current)
    for sup in supplies:
        sup.setdefault('status', '')
        sup.setdefault('type', '')
    return supplies


# ───────────────────────── 设备槽位/板卡（display device） ─────────────────────────
def parse_device(text):
    """display device → [{slot, type, status}, ...]

    H3C 典型输出：Slot 1  MPU  Normal  S6820-56HF
    """
    if not text:
        return []
    boards = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        m = re.match(r'Slot\s*(\d+)\s*', s, re.I)
        if not m:
            continue
        slot = m.group(1)
        rest = s[m.end():].strip()
        toks = rest.split()
        btype = ''
        status = ''
        if len(toks) >= 1 and re.match(
            r'(Normal|Fault|Absent|Off|Illegal|Master|Standby|Slave)',
            toks[-1], re.I
        ):
            status = toks[-1]
            btype = ' '.join(toks[:-1])
        elif len(toks) >= 2 and re.match(
            r'(Normal|Fault|Absent|Off|Illegal|Master|Standby|Slave)',
            toks[-2], re.I
        ):
            status = toks[-2]
            btype = ' '.join(toks[:-2])
        else:
            btype = ' '.join(toks)
            status = 'Unknown'
        boards.append({'slot': slot, 'type': btype.strip(), 'status': status})
    return boards


# ───────────────────────── NAT（防火墙 NAT 配置） ─────────────────────────
def parse_nat(text):
    """NAT 配置 → [{type, inside_ip, outside_ip, port}, ...]

    H3C 防火墙：nat server protocol tcp global 10.1.1.1 443 inside 192.168.1.1 443
    """
    if not text:
        return []
    entries = []
    for line in text.splitlines():
        s = line.strip()
        if not s or not s.lower().startswith('nat '):
            continue
        if s.lower().startswith('nat server'):
            m = re.search(
                r'global\s+(\S+)\s*(\d+)?\s+inside\s+(\S+)\s*(\d+)?',
                s, re.I
            )
            if m:
                entries.append({
                    'type': 'server',
                    'outside_ip': m.group(1),
                    'outside_port': int(m.group(2)) if m.group(2) else None,
                    'inside_ip': m.group(3),
                    'inside_port': int(m.group(4)) if m.group(4) else None,
                })
        elif s.lower().startswith('nat static'):
            toks = s.split()
            if len(toks) >= 4:
                entries.append({
                    'type': 'static',
                    'inside_ip': toks[2],
                    'outside_ip': toks[3],
                    'outside_port': None,
                    'inside_port': None,
                })
    return entries


# ───────────────────────── 风扇（display fan） ─────────────────────────
def parse_fan(text):
    """display fan → [{fan_id, status, type}, ...]

    H3C 典型输出：
      Fan 1 State: Normal
      Fan 2 State: Normal  Type: FAN-80B-1-B
    """
    if not text:
        return []
    fans = []
    current = {}
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        m = re.match(r'Fan\s*(\d+)\s*(?::\s*|State\s*:\s*(\S+))', s, re.I)
        if m:
            if current and current.get('fan_id'):
                fans.append(current)
            current = {'fan_id': m.group(1)}
            if m.group(2):
                current['status'] = m.group(2)
            continue
        if current:
            mt = re.match(r'State\s*:\s*(\S+)', s, re.I)
            if mt:
                current['status'] = mt.group(1)
                continue
            mt = re.match(r'Type\s*:\s*(\S+)', s, re.I)
            if mt:
                current['type'] = mt.group(1)
                continue
    if current and current.get('fan_id'):
        fans.append(current)
    for f in fans:
        f.setdefault('status', '')
        f.setdefault('type', '')
    return fans


# ───────────────────────── 光模块（display transceiver interface） ─────────────────────────
def parse_transceiver(text):
    """display transceiver interface → [{iface, type, vendor, serial, wavelength, distance, ordering_name}, ...]

    提取每个接口的光模块核心信息：型号(Transceiver Type)/厂商/序列号/波长/传输距离/订货号。
    - 只认 Transceiver Type（不误吞 Connector Type）
    - absent 的端口不入库
    - Ordering Name 与 Vendor Part Number 归一为 ordering_name（同一模块两种输出）
    """
    if not text:
        return []
    modules = []
    cur = {}
    lines = text.splitlines()
    for i, line in enumerate(lines):
        s = line.strip()
        # 接口块头（含 absent 标记：整块跳过）
        mi = re.match(r'(\S+)\s+transceiver\s+information', s, re.I)
        if mi:
            if cur.get('iface'):
                modules.append(cur)
            if 'absent' in s.lower() or (i + 1 < len(lines) and 'absent' in lines[i + 1].lower()):
                cur = {}
            else:
                cur = {'iface': mi.group(1)}
            continue
        if not cur:
            continue
        # Transceiver Type（精确，避免误匹配 Connector Type）
        mt = re.search(r'Transceiver\s+Type\s*:\s*(\S.*)', s, re.I)
        if mt:
            cur['type'] = mt.group(1).strip()
            continue
        # 订货号：Ordering Name 或 Vendor Part Number（同一模块两种输出）
        mo = re.search(r'Ordering\s+Name\s*:\s*(\S.*)', s, re.I)
        if mo:
            cur['ordering_name'] = mo.group(1).strip()
            continue
        mpn = re.search(r'Vendor\s+Part\s+Number\s*:\s*(\S.*)', s, re.I)
        if mpn:
            cur.setdefault('ordering_name', mpn.group(1).strip())
            continue
        mv = re.search(r'Vendor\s*Name\s*:\s*(\S.*)', s, re.I)
        if mv:
            if 'vendor' not in cur:
                cur['vendor'] = mv.group(1).strip()
            continue
        ms = re.search(r'Serial\s*(?:No|Number)?\s*:\s*(\S+)', s, re.I)
        if ms:
            cur['serial'] = ms.group(1)
            continue
        mw = re.search(r'Wavelength\s*\(?nm\)?\s*:\s*(\d+(?:\.\d+)?)\s*(nm)?', s, re.I)
        if mw:
            cur['wavelength'] = mw.group(1)
            continue
        md = re.search(r'(?:Transfer|Transmission)\s*Distance\s*\(m\)\s*:\s*(\S.*)', s, re.I)
        if md:
            cur['distance'] = md.group(1).strip()
            continue
    if cur.get('iface'):
        modules.append(cur)
    return modules
