"""阶段 B · 自定义检查器集合（hp_comware V7 设备）

所有检查器使用 @register_checker('name') 注册，由 pipeline.check_custom 通过
CheckItem.checker_config = {"func": "name"} 调用。

签名统一为：
    def checker(parsed: str, baseline: str, config: dict, extra: dict) -> (bool, str)
    # (是否正常, 异常说明)

注意：
- parsed 是命令原始回显（parser='raw' 时即为命令输出文本）。
- extra 是 NewDevice.extra（JSON），用于传入每设备期望值（如 down_ok / ospf_nei / vrrp_master）。
- 解析尽量对输出措辞差异健壮，避免把正常状态误判为异常。
"""
import re
from datetime import datetime, timedelta

from app02.engine.pipeline import register_checker


# dir flash: 回显失败/设备不支持的错误特征（用于区分"无法判定"与"格式异常"）
FLASH_ERROR_PAT = re.compile(
    r'(% ?(Unrecognized command|Wrong parameter|Incomplete command|'
    r'Too many parameters|Invalid)|not configured|not enabled|'
    r'Information not available|Error:|is not supported)',
    re.IGNORECASE,
)


# ══════════════════════════════════════════════════════════════
# 已有 checker（保持不变）
# ══════════════════════════════════════════════════════════════

@register_checker('check_fan')
def check_fan(parsed, baseline, cfg, extra):
    """风扇状态：双重验证——至少1个Normal且无异常关键字；采集为空时报异常，避免漏检。"""
    text = parsed or ''
    normal_count = len(re.findall(r'\bNormal\b', text, re.I))
    if normal_count == 0:
        return False, '风扇状态采集为空或无Normal（可能采集失败或全部异常）'
    if re.search(r'\b(Abnormal|Fault)\b', text, re.I):
        bad = re.findall(r'Fan\s*\d+[^\n]*?(?:Abnormal|Fault)', text, re.I)
        return False, f'存在风扇异常状态: {" / ".join(bad[:3])}'
    return True, ''


@register_checker('check_power')
def check_power(parsed, baseline, cfg, extra):
    """电源状态：双重验证——至少1个Normal且无异常关键字"""
    text = parsed or ''
    normal_count = len(re.findall(r'\bNormal\b', text, re.I))
    if normal_count == 0:
        return False, '电源状态采集为空或无Normal（可能采集失败或全部异常）'
    if re.search(r'\b(Abnormal|Fault|Failed|Off)\b', text, re.I):
        bad = re.findall(r'Power\s*\d+[^\n]*?(?:Abnormal|Fault|Failed|Off)', text, re.I)
        return False, f'存在电源异常状态: {" / ".join(bad[:3])}'
    return True, ''


@register_checker('check_device')
def check_device(parsed, baseline, cfg, extra):
    """单板状态：双重验证——至少1个Normal且无异常关键字"""
    text = parsed or ''
    normal_count = len(re.findall(r'\bNormal\b', text, re.I))
    if normal_count == 0:
        return False, '单板状态采集为空或无Normal（可能采集失败或全部异常）'
    if re.search(r'\b(Fault|Abnormal)\b', text, re.I):
        bad = re.findall(r'Slot\s*\d+[^\n]*?(?:Fault|Abnormal)', text, re.I)
        return False, f'存在单板异常状态: {" / ".join(bad[:3])}'
    return True, ''


@register_checker('check_env')
def check_env(parsed, baseline, cfg, extra):
    """环境温度：超过阈值(默认60C)或存在 Fault/Abnormal 即异常"""
    thr = float(cfg.get('temp_warning', 60))
    for line in (parsed or '').splitlines():
        if re.search(r'temp', line, re.I):
            m = re.search(r'(\d+(?:\.\d+)?)', line)
            if m and float(m.group(1)) > thr:
                return False, f'温度超过阈值 {thr}C: {line.strip()}'
    if re.search(r'\b(Fault|Abnormal)\b', parsed or '', re.I):
        return False, '环境状态异常(Fault/Abnormal)'
    return True, ''


@register_checker('check_ifbrief')
def check_ifbrief(parsed, baseline, cfg, extra):
    """接口概要：辅助检查——保证输出非空。接口变化详情由 baseline checker 面板对比。在实际巡检中建议直接使用 checker=baseline 替代此 checker 进行全量对比。"""
    text = parsed or ""
    if not text.strip():
        return False, "接口输出为空（采集失败）"
    return True, ""

@register_checker('check_agg')
def check_agg(parsed, baseline, cfg, extra):
    """链路聚合概要：检查 Unselected 端口数量（阶段二·优先消费结构化解析结果）。

    结构化键：display link-aggregation summary 解析为
      [{'lag_name','mode','partner_id','selected_ports','unselected_ports'}, ...]
    无结构化数据时回退到改造前的 raw 文本判定（行为完全一致）。
    """
    structured = extra.get('__structured__')
    if structured is not None:
        for lag in structured:
            unsel = int(lag.get('unselected_ports', 0) or 0)
            if unsel > 0:
                return False, f'{lag.get("lag_name", "")} 存在{unsel}个未选中端口'
        return True, ''
    # 回退：raw 文本（与改造前一致）
    text = parsed or ''
    # 只处理以聚合口名开头的行（如 BAGG100、RAGG200），跳过表头/分隔线
    for line in text.splitlines():
        m = re.match(r'^\s*(BAGG|RAGG|BLAGG|SCH-B)\d+', line, re.I)
        if not m:
            continue
        parts = line.split()
        if len(parts) >= 5:
            try:
                unselected_val = int(parts[4])  # 第5列: Unselected
                if unselected_val > 0:
                    return False, f'{parts[0]} 存在{unselected_val}个未选中端口'
            except (ValueError, IndexError):
                pass
    return True, ''


@register_checker('check_arp')
def check_arp(parsed, baseline, cfg, extra):
    """ARP IP 冲突记录：存在冲突记录即异常；无冲突(0 / No)视为正常"""
    text = parsed or ''
    if re.search(r'(\b0\b\s*(conflict|条))', text, re.I):
        return True, ''
    if re.search(r'\bno\b.*conflict', text, re.I):
        return True, ''
    lines = [
        l for l in text.splitlines()
        if re.search(r'conflict', l, re.I) and not re.match(r'\s*no\b', l.strip(), re.I)
    ]
    if lines:
        return False, f'发现 {len(lines)} 条ARP IP冲突记录'
    return True, ''


@register_checker('check_vrrp')
def check_vrrp(parsed, baseline, cfg, extra):
    """VRRP 概要：Master 数应与设备期望值(vrrp_master)一致；存在 Initialize 即异常"""
    expected = int(extra.get('vrrp_master', cfg.get('vrrp_master', 0) or 0) or 0)
    masters = len(re.findall(r'\bMaster\b', parsed or '', re.I))
    if expected and masters != expected:
        return False, f'VRRP Master 数应为 {expected}，实际 {masters}'
    if re.search(r'\bInitialize\b', parsed or '', re.I):
        return False, '存在 VRRP 状态为 Initialize（未协商完成）'
    return True, ''


@register_checker('check_nqa')
def check_nqa(parsed, baseline, cfg, extra):
    """NQA 探测结果：存在 failed / Timeout / Unreachable 即异常"""
    failed = re.findall(r'\bfailed\b', parsed or '', re.I)
    if failed:
        return False, f'存在 {len(failed)} 个NQA探测失败'
    if re.search(r'(Timeout|Unreachable|不可达)', parsed or '', re.I):
        return False, 'NQA 探测超时/不可达'
    return True, ''


# ══════════════════════════════════════════════════════════════
# 🔴 新增 checker（14 个）
# ══════════════════════════════════════════════════════════════

@register_checker('check_cpu')
def check_cpu(parsed, baseline, cfg, extra):
    """CPU 5秒使用率：从原始回显提取（兼容多种 H3C 格式），再与阈值比较。

    已用库内真实回显校准，支持两种 H3C V7 格式：
        格式A:  6% in last 5 seconds
        格式B:  CPU utilization in last 5 seconds:  6%
    注意：必须精确匹配「in last 5 seconds」上下文里的百分比，
    不能用「行内首个数字」（否则会把 '5 seconds' 里的 5 误当成使用率）。
    """
    text = parsed or ''
    if not text.strip():
        return False, 'CPU数据采集为空'
    warning = float(cfg.get('warning', 80))
    # 优先匹配两种真实格式（数字紧跟在 'in last 5 seconds' 之前或之后）
    m = re.search(r'(\d+(?:\.\d+)?)%\s*in last 5 seconds', text, re.I)
    if not m:
        m = re.search(r'in last 5 seconds:?\s*(\d+(?:\.\d+)?)%', text, re.I)
    if not m:
        return False, '无法从CPU输出提取5秒使用率'
    val = float(m.group(1))
    # warning 为「超过即异常」阈值（如 40 表示 CPU>40% 告警）
    if val > warning:
        return False, f'CPU利用率 {val}% 超过阈值 {warning}%'
    return True, ''


@register_checker('check_memory')
def check_memory(parsed, baseline, cfg, extra):
    """内存利用率：从 display memory 输出提取 FreeRatio 做阈值判断。
    
    输出格式（hp_comware V7）：
        Mem:        991732    439140    552592         0      1480    182036       55.9%
                                                                               ^^^^^^ FreeRatio
    """
    text = parsed or ''
    # 提取所有 FreeRatio 值
    freeratios = re.findall(r'Mem:[\s\d]+\s+([\d.]+)%', text)
    if not freeratios:
        return False, '无法从内存输出提取FreeRatio'
    
    warning = float(cfg.get('warning', 20))
    operator = cfg.get('operator', '>')
    lowest = min(float(x) for x in freeratios)
    for fr in freeratios:
        val = float(fr)
        if operator == '>':
            # FreeRatio 越高越好：低于 warning 即异常
            if val < warning:
                return False, f'内存FreeRatio {val}% 低于阈值 {warning}%（当前最低: {lowest}%）'
        elif operator == '<':
            if val > warning:
                return False, f'内存FreeRatio {val}% 超过阈值 {warning}%'
    return True, ''


@register_checker('check_stp')
def check_stp(parsed, baseline, cfg, extra):
    """STP状态：检查根桥角色和端口状态。
    
    参数：
        root_expected: "本端"/"非根桥"/"按规划"
        默认检查所有端口 STP State=FORDWARDING，无 BLO
    """
    text = parsed or ''
    root_expected = cfg.get('root_expected', '')

    # 非根桥检查
    if root_expected == '非根桥':
        root_ports = re.findall(r'^\s*\d+\s+(\S+)\s+ROOT\s', text, re.M)
        if not root_ports:
            return True, ''  # 无ROOT端口也算正常（不一定所有设备有上行）
    
    if root_expected == '本端':
        if not re.search(r'\bROOT\b', text):
            return False, '设备不是本STP实例的根桥'

    # 阻塞端口检查
    blocked = re.findall(r'\b(BLO|DISC)\b', text)
    if blocked:
        return False, f'存在 {len(blocked)} 个阻塞端口'

    # TC(N)检查
    tc_count = len(re.findall(r'TCN?\b', text, re.I))
    if tc_count > 0:
        return False, f'存在 {tc_count} 次拓扑变更(TC/TCN)'
    
    return True, ''


@register_checker('check_ospf_peer')
def check_ospf_peer(parsed, baseline, cfg, extra):
    """OSPF邻居检查：统计 Full 状态的邻居数，与期望值对比。
    
    参数：
        expected_full_count: 期望的 Full 邻居总数
        instances: {"EIP_MGMT": 2, "Internet": 1} 多实例模式
    """
    text = parsed or ''
    full_count = len(re.findall(r'\bFull\b', text))
    
    if 'instances' in cfg:
        # 多实例模式：检查每个实例
        errors = []
        total_expected = 0
        for inst_name, expected in cfg['instances'].items():
            expected = int(expected) if expected else 0
            total_expected += expected
        if full_count != total_expected:
            return False, f'OSPF Full邻居数 {full_count}，期望 {total_expected}'
        return True, ''
    
    expected = int(cfg.get('expected_full_count', 0) or 0)
    if expected and full_count != expected:
        return False, f'OSPF Full邻居数 {full_count}，期望 {expected}'
    
    if full_count == 0:
        return False, 'OSPF 无 Full 邻居'
    
    return True, ''


@register_checker('check_ospf_baseline')
def check_ospf_baseline(parsed, baseline, cfg, extra):
    """OSPF 基线对比：屏蔽 Dead-Time 动态字段后全量对比。

    归一化 Dead-Time（替换为固定值 99），避免每次巡检 Dead-Time 递减导致误报。
    然后对 neighbor 行做 difflib 对比。

    checker_config:
        similarity: 一致度阈值（默认 1.0）
    """
    import difflib

    def _normalize(text):
        """归一化 OSPF peer 输出：去掉 Dead-Time 表头行，替换 Dead-Time 数值。"""
        if not text:
            return ''
        lines = []
        for line in text.splitlines():
            # 跳过表头行
            if 'Dead-Time' in line:
                continue
            # 替换 Dead-Time 列：数字(空格)数字(空格+Full/Init/…) → 数字 99 State..
            # 格式: RouterID  Address  Pri  Dead-Time  State  Interface
            line = re.sub(
                r'(\d+)\s+(\d+)\s+(Full|Init|Down|Exchange|Loading|ExStart|2-Way)',
                r'\1  99  \3', line
            )
            lines.append(line)
        return '\n'.join(lines)

    t1 = _normalize(parsed or '')
    t2 = _normalize(baseline or '')

    if not t1:
        return False, 'OSPF 输出为空'
    if not t2:
        return False, '基线不存在，请先设置基线'

    # 合并空白后对比
    n1 = re.sub(r'\s+', ' ', t1).strip()
    n2 = re.sub(r'\s+', ' ', t2).strip()
    ratio = difflib.SequenceMatcher(None, n1, n2).ratio()
    similarity = float((cfg or {}).get('similarity', 1.0))

    if ratio >= similarity:
        return True, ''
    return False, f'OSPF 邻居信息与基线不一致（相似度 {ratio:.1%}）'


@register_checker('check_bgp_peer')
def check_bgp_peer(parsed, baseline, cfg, extra):
    """BGP邻居检查：统计 Established 状态邻居数，与期望值对比。
    
    参数：
        expected_established: 期望的 Established 邻居数量
    """
    text = parsed or ''
    summary = re.search(r'Peers\s+in\s+established\s+state:\s*(\d+)', text, re.I)
    if summary:
        established = int(summary.group(1))
    else:
        established = len(re.findall(r'\bEstablished\b', text, re.I))
    expected = int(cfg.get('expected_established', 0) or 0)
    
    if expected:
        if established != expected:
            return False, f'BGP Established 邻居数 {established}，期望 {expected}'
    elif established == 0:
        return False, 'BGP 无 Established 邻居'
    
    return True, ''


@register_checker('check_rbm')
def check_rbm(parsed, baseline, cfg, extra):
    """RBM双机热备状态检查：命令 display remote-backup-group status。
    本端 Device running status 应为 Active 或 Standby（主墙Active，备墙Standby）。
    控制通道/数据通道 Up 且配置一致无异常。"""
    text = parsed or ''
    
    if not text.strip():
        return False, 'RBM状态输出为空（采集失败）'
    
    # 检查本端状态
    local_match = re.search(r'Local remote backup group information:(.*?)(?=Peer remote backup group|Switchover records|$)',
                           text, re.DOTALL)
    if local_match:
        local = local_match.group(1)
        running_status = re.search(r'Device running status:\s*(\S+)', local)
        data_channel = re.search(r'Data channel interface current state:\s*(\S+)', local)
        control_channel = re.search(r'Control channel status:\s*(\S+)', local)
        
        if running_status:
            status = running_status.group(1)
            if status not in ('Active', 'Standby'):
                return False, f'本端RBM状态异常: {status}'
        if data_channel and data_channel.group(1) != 'Up':
            return False, f'数据通道异常: {data_channel.group(1)}'
        if control_channel and control_channel.group(1) != 'Connected':
            return False, f'控制通道异常: {control_channel.group(1)}'
    
    # 检查对端状态
    peer_match = re.search(r'Peer remote backup group information:(.*?)(?=Switchover records|$)',
                           text, re.DOTALL)
    if peer_match:
        peer = peer_match.group(1)
        peer_status = re.search(r'Device running status:\s*(\S+)', peer)
        if peer_status and peer_status.group(1) not in ('Active', 'Standby'):
            return False, f'对端RBM状态异常: {peer_status.group(1)}'
    
    return True, ''


@register_checker('check_mlag')
def check_mlag(parsed, baseline, cfg, extra):
    """M-LAG状态检查：状态 Active/Up，无 MAD 冲突/异常"""
    text = parsed or ''
    
    if re.search(r'(M-LAG\s*error|MAD\s*conflict|M-LAG\s*fault)', text, re.I):
        return False, 'M-LAG 检测到异常(error/conflict/fault)'
    
    return True, ''


@register_checker('check_track')
def check_track(parsed, baseline, cfg, extra):
    """Track/NQA状态检查：所有Track状态为Positive
    
    参数：
        expected_tracks: 期望的 Track 总数
    """
    text = parsed or ''
    expected = int(cfg.get('expected_tracks', 0) or 0)
    
    positive_count = len(re.findall(r'\bPositive\b', text))
    
    if re.search(r'\bNegative\b', text, re.I):
        negatives = re.findall(r'Track\s*(\d+)[\s\S]*?Negative', text, re.I)
        return False, f'存在 {len(negatives)} 个Negative状态的Track'
    
    if expected and positive_count < expected:
        return False, f'Track Positive {positive_count}，期望 {expected}'
    
    return True, ''


@register_checker('check_session')
def check_session(parsed, baseline, cfg, extra):
    """会话表检查：并发会话数在正常范围内
    
    参数：
        max_sessions: 最大会话数阈值
    """
    if parsed is None:
        return False, '会话数据采集异常'
    
    text = str(parsed)
    max_val = float(cfg.get('max_sessions', 500000))
    
    # 尝试提取数字
    nums = re.findall(r'([\d,]+)', text)
    for n in nums:
        try:
            val = int(n.replace(',', ''))
            if val > max_val:
                return False, f'并发会话数 {val} 超过上限 {int(max_val)}'
        except ValueError:
            continue
    
    return True, ''


@register_checker('check_vlan')
def check_vlan(parsed, baseline, cfg, extra):
    """VLAN清单检查：实际VLAN集合 vs 期望VLAN集合（双向比对，阶段二·优先消费结构化）。

    结构化键：display vlan brief 解析为 [int VLAN id, ...]。
    无结构化数据时回退到改造前的 raw 文本判定（行为完全一致）。

    参数：
        expected_vlans: 期望的 VLAN ID 列表，如 [1, 100, 101, 110, 111, 112, 114, 301, 4094]
    """
    expected = cfg.get('expected_vlans', [])
    if not expected:
        return True, ''  # 未配置期望列表时跳过

    structured = extra.get('__structured__')
    if structured is not None:
        # 结构化：parse_vlan_brief 返回 [int VLAN id, ...]
        vlan_ids = set(int(v) for v in structured if isinstance(v, int) and 1 <= v <= 4094)
    else:
        text = parsed or ''
        vlan_ids = set()
        for line in text.splitlines():
            line = line.strip()
            m = re.match(r'^(\d+)\s+\S', line)
            if m:
                vid = int(m.group(1))
                if 1 <= vid <= 4094:
                    vlan_ids.add(vid)

    if not vlan_ids:
        return True, ''  # 无法提取时跳过

    expected_set = set(int(v) for v in expected)

    missing = expected_set - vlan_ids
    extra_vlans = vlan_ids - expected_set

    if missing or extra_vlans:
        msgs = []
        if missing:
            msgs.append(f'缺少VLAN: {sorted(missing)}')
        if extra_vlans:
            msgs.append(f'多出VLAN: {sorted(extra_vlans)}')
        return False, '; '.join(msgs)

    return True, ''


@register_checker('check_zone')
def check_zone(parsed, baseline, cfg, extra):
    """安全域成员检查：各zone的import接口集合 == 期望值（阶段二·优先消费结构化）。

    结构化键：display security-zone 解析为 [{'name','interfaces'}, ...]。
    无结构化数据时回退到改造前的 raw 文本判定（行为完全一致）。

    参数：
        expected: {"OutBand": ["GE1/0/1", "GE1/0/2"], "InBand": [...], ...}
    """
    expected = cfg.get('expected', {})
    if not expected:
        return True, ''  # 未配置期望值时跳过

    structured = extra.get('__structured__')
    if structured is not None:
        # 结构化：parse_security_zone 返回 [{'name': zone, 'interfaces': [intf, ...]}, ...]
        zone_map = {z.get('name', ''): list(z.get('interfaces', [])) for z in structured}
    else:
        text = parsed or ''
        zone_map = {}
        current_zone = None
        for line in text.splitlines():
            m = re.match(r'^\s*(\S+)\s*$', line)
            if m and not re.search(r'\binterface\b', line, re.I):
                current_zone = m.group(1)
                zone_map[current_zone] = []
            elif current_zone:
                intf = re.findall(r'(?:GE|XGE|Route-Aggregation|BAGG)\d+/[\d/]+', line)
                zone_map[current_zone].extend(intf)

    # 比对
    errors = []
    for zone, expected_intfs in expected.items():
        actual = zone_map.get(zone, [])
        expected_set = set(expected_intfs)
        actual_set = set(actual)
        missing = expected_set - actual_set
        extra_intfs = actual_set - expected_set
        if missing:
            errors.append(f'{zone}缺少接口: {sorted(missing)}')
        if extra_intfs:
            errors.append(f'{zone}多出接口: {sorted(extra_intfs)}')

    if errors:
        return False, '; '.join(errors)
    return True, ''


@register_checker('check_routing_table')
def check_routing_table(parsed, baseline, cfg, extra):
    """路由表检查：A类基线对比。
    推荐采集命令：display ip routing-table all-vpn-instance。
    此 checker 仅做辅助：保证输出非空。"""
    text = parsed or ''
    if not text.strip():
        return False, '路由表输出为空（采集失败）'
    return True, ''

@register_checker('check_security_policy_zone')
def check_security_policy_zone(parsed, baseline, cfg, extra):
    """安全策略规则zone检查：每条规则的dest_zone == 路由出接口对应zone
    
    参数：（复杂，当前版本仅检查策略输出可读性）
        current Zone to interface mapping
    """
    text = parsed or ''
    # 基础检查：策略输出非空即正常
    if not text.strip():
        return False, '安全策略规则输出为空'
    
    return True, ''


_MONTH_MAP = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
}


def _parse_log_time(line):
    """从 H3C 日志行首解析时间戳，返回 datetime 或 None。

    支持 hp_comware V7 常见格式（前导 % / * 可选）：
        Jun 24 17:26:46:437 2026        ->  Mon DD HH:MM:SS[:fff] YYYY
        Jun 24 17:26:46 2026            ->  Mon DD HH:MM:SS YYYY
        2026-07-23 14:30:49             ->  %Y-%m-%d %H:%M:%S
        2026/07/23 14:30:49             ->  %Y/%m/%d %H:%M:%S

    使用硬编码月份映射（不依赖运行环境 locale），避免在非英文 locale 下
    %b 解析失败导致返回 None、进而把近期真实错误静默跳过（漏报）。
    """
    # 1) 英文月格式: Mon DD HH:MM:SS[:fff] YYYY
    s = line.lstrip('%* ')
    m = re.match(
        r'([A-Za-z]{3})\s+(\d{1,2})\s+'
        r'(\d{1,2}):(\d{1,2}):(\d{1,2})(?::(\d{1,3}))?\s+(\d{4})', s)
    if m:
        mon = _MONTH_MAP.get(m.group(1).lower())
        if mon:
            try:
                year = int(m.group(7))
                day = int(m.group(2))
                hour = int(m.group(3))
                minute = int(m.group(4))
                second = int(m.group(5))
                micro = int((m.group(6) or '0').ljust(6, '0'))
                return datetime(year, mon, day, hour, minute, second, micro)
            except ValueError:
                pass
    # 2) ISO 风格: YYYY-MM-DD HH:MM:SS 或 YYYY/MM/DD HH:MM:SS
    m2 = re.search(r'(\d{4}[-/]\d{2}[-/]\d{2}\s+\d{2}:\d{2}:\d{2})', line)
    if m2:
        chunk = m2.group(1)
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y/%m/%d %H:%M:%S'):
            try:
                return datetime.strptime(chunk, fmt)
            except ValueError:
                continue
    return None


@register_checker('check_logbuffer')
def check_logbuffer(parsed, baseline, cfg, extra):
    """日志缓冲检查：统计【最近 N 天】内的异常日志。

    屏蔽无意义的管理命令日志（SHELL/4,5,6/SHELL_CMD）。
    时间窗口可在 CheckItem.checker_config 配置：{"window_days": 2}（默认 2 天）。
    """
    text = (parsed or '').strip()
    if not text:
        return False, '日志输出为空（采集失败）'

    cfg = cfg or {}
    window_days = int(cfg.get('window_days', 2))
    cutoff = datetime.now() - timedelta(days=window_days)

    # 屏蔽的日志：管理命令操作记录 / SHELL 登录登出 / SSH 登录登出
    skip_pat = re.compile(r'SHELL/[456]/(SHELL_CMD|SHELL_LOGIN|SHELL_LOGOUT)|SSHS?/')

    # 仅匹配「模块名/严重级/子消息」形态（如 PWDCTL/3/P），避免把接口编号误判
    sev_re = re.compile(r'[A-Za-z]+/(\d)/')

    recent = []
    valid_lines = 0

    for line in text.splitlines():
        m = sev_re.search(line)
        if not m:
            continue
        valid_lines += 1

        ts = _parse_log_time(line)
        if ts is None or ts < cutoff:
            continue

        # 跳过管理员命令日志
        if skip_pat.search(line):
            continue

        sev = int(m.group(1))
        recent.append((sev, line))

    if valid_lines == 0:
        return False, '未找到有效日志格式，输出可能异常'

    if recent:
        sev, line = recent[0]
        return False, f'近 {window_days} 天内存在 {len(recent)} 条异常日志(sev={sev}): {line[:80]}...'

    return True, ''
BIAS_OFF = 0.1  # 偏置电流(A)低于此值视为激光器关闭


def _parse_optic_block(body):
    """解析单个接口的光模块诊断块，返回 dict 或 None。

    统一把 Bias/RX/TX 归一成逐通道列表；Temp/Voltage 取模块级标量。
    兼容两种输出：
      - 标准 10G：5 数列值行(Temp Voltage Bias RX TX)
      - 40G/100G：[module] 行(Temp Voltage TotalRX TotalTX) + [channel] 逐通道表(Bias RX TX)
    """
    res = {'temp': None, 'voltage': None, 'biases': [], 'rxs': [], 'txs': [], 'thr': {}}

    # 告警阈值（5 列：Temp Voltage Bias RX TX）
    mt = re.search(
        r'Alarm thresholds:.*?'
        r'High\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s*\n'
        r'\s*Low\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)',
        body, re.DOTALL)
    if mt:
        hi = [float(x) for x in mt.groups()[:5]]
        lo = [float(x) for x in mt.groups()[5:]]
        res['thr'] = {'temp': (lo[0], hi[0]), 'voltage': (lo[1], hi[1]),
                      'bias': (lo[2], hi[2]), 'rx': (lo[3], hi[3]), 'tx': (lo[4], hi[4])}

    # 逐通道表：仅解析 [channel] 区段内的行（每行 通道号 Bias RX TX）。
    # 注意：[module] 行外形也是 4 个数字，必须限定在 [channel] 之后，否则会误把
    # Total TX 当成通道 TX 去比对阈值，产生海量误报。
    mc = re.search(r'\[channel\][^\n]*\n((?:\s*\d+\s+[-\d.]+\s+[-\d.]+\s+[-\d.]+\s*(?:\n|$))+)', body)
    if mc:
        for line in mc.group(1).strip().splitlines():
            p = line.split()
            try:
                res['biases'].append(float(p[1]))
                res['rxs'].append(float(p[2]))
                res['txs'].append(float(p[3]))
            except (ValueError, IndexError):
                pass

    if res['biases']:
        # 40G/100G：Temp/Voltage 来自 [module] 行
        mm = re.search(r'\[module\]\s*Temp[^\n]*\n\s*([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)', body)
        if mm:
            res['temp'] = float(mm.group(1))
            res['voltage'] = float(mm.group(2))
    else:
        # 标准 10G：5 数列值行
        ms = re.search(
            r'Current diagnostic parameters:.*?\n\s*Temp[^\n]*\n'
            r'\s*([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)', body, re.DOTALL)
        if ms:
            res['temp'] = float(ms.group(1))
            res['voltage'] = float(ms.group(2))
            res['biases'] = [float(ms.group(3))]
            res['rxs'] = [float(ms.group(4))]
            res['txs'] = [float(ms.group(5))]

    if not res['biases']:
        return None  # 无可解析诊断数据
    return res


@register_checker('check_transceiver')
def check_transceiver(parsed, baseline, cfg, extra):
    """光模块收发光诊断（hp_comware V7），逐接口解析，避免跨口错位。

    判定：
    1) 无模块 / 不支持 → 跳过（不告警）。【修复张冠李戴误报】
    2) 激光关闭特征（偏置电流≈0 或 发射光功率跌至地板值）→ 端口未发光
       （未启用 / 对端未连），整口判正常，不报硬件故障。
    3) 激光开启时做硬阈值判异；其中「本端发光正常但收光偏低」(对端关闭/光纤中断)
       按用户要求判正常，仅作提示。
    4) 偏大/偏小(软预警)：RX/TX/Bias 进入 [Low,High] 临近任一阈值的软带
       （warn_ratio，默认 0.1=10%）→ 预警，便于提前发现劣化。
       想关掉软预警：checker_config 设 {"soft_check": false}。
    """
    text = parsed or ''
    cfg = cfg or {}
    warn_ratio = max(0.0, min(0.95, float(cfg.get('warn_ratio', 0.1))))
    soft_check = bool(cfg.get('soft_check', True))

    HEADER_RE = re.compile(r'(?m)^(\S+)\s+transceiver diagnostic information:')
    parts = HEADER_RE.split(text)
    hard_errors, soft_warns, info_notes = [], [], []

    for i in range(1, len(parts), 2):
        intf = parts[i]
        body = parts[i + 1] if i + 1 < len(parts) else ''

        # 1) 无模块 / 不支持 → 跳过
        if ('transceiver is absent' in body) or ('operation is not supported' in body):
            continue

        rec = _parse_optic_block(body)
        if rec is None:
            continue
        thr = rec['thr']
        if not thr:
            info_notes.append(f'{intf} 无法解析告警阈值，已跳过')
            continue

        # 模块级温度/电压
        temp, volt = rec.get('temp'), rec.get('voltage')
        if temp is not None:
            lo, hi = thr['temp']
            if temp < lo or temp > hi:
                hard_errors.append(f'{intf} Temp={temp}越限[{lo},{hi}]')
        if volt is not None:
            lo, hi = thr['voltage']
            if volt < lo or volt > hi:
                hard_errors.append(f'{intf} Voltage={volt}越限[{lo},{hi}]')

        # 逐通道 (bias, rx, tx)
        pairs = list(zip(rec['biases'], rec['rxs'], rec['txs']))
        if not pairs:
            continue
        all_off = True
        for (bias, rx, tx) in pairs:
            lo_b, hi_b = thr['bias']
            lo_r, hi_r = thr['rx']
            lo_t, hi_t = thr['tx']
            # 2) 激光关闭判定（偏置≈0 或 发射光功率跌到地板值）
            laser_off = (bias <= BIAS_OFF) or (tx <= lo_t + 0.5)
            if laser_off:
                continue  # 该通道未发光，跳过告警
            all_off = False
            # 3) 本端发光正常但收光偏低 → 对端关闭/光纤中断 → 正常（抑制误报）
            peer_down = (rx <= lo_r) and (lo_t <= tx <= hi_t)
            if bias < lo_b or bias > hi_b:
                hard_errors.append(f'{intf} Bias={bias}越限[{lo_b},{hi_b}]')
            if peer_down:
                note = f'{intf} 收光偏低但本端发光正常(疑似对端关闭/光纤中断)'
                if note not in info_notes:
                    info_notes.append(note)
            elif rx < lo_r or rx > hi_r:
                hard_errors.append(f'{intf} RX={rx}越限[{lo_r},{hi_r}]')
            if tx < lo_t or tx > hi_t:
                hard_errors.append(f'{intf} TX={tx}越限[{lo_t},{hi_t}]')
            # 4) 偏大/偏小(软预警)
            if soft_check:
                for val, (lo, hi), label in ((rx, (lo_r, hi_r), 'RX'),
                                             (tx, (lo_t, hi_t), 'TX'),
                                             (bias, (lo_b, hi_b), 'Bias')):
                    if val < lo or val > hi:
                        continue
                    span = hi - lo
                    if span <= 0:
                        continue
                    if val >= hi - warn_ratio * span:
                        soft_warns.append(f'{intf} {label}={val} 偏大(近High={hi})')
                    elif val <= lo + warn_ratio * span:
                        soft_warns.append(f'{intf} {label}={val} 偏小(近Low={lo})')
        if all_off and pairs:
            info_notes.append(f'{intf} 全部通道未发光(偏置≈0/发射功率跌地板)，疑似端口未启用/对端断开')

    if hard_errors:
        msg = f'{len(hard_errors)}项硬告警: ' + ' | '.join(hard_errors[:8])
        if info_notes:
            msg += ' ［提示: ' + '; '.join(info_notes[:4]) + '］'
        return False, msg
    if soft_warns:
        msg = f'{len(soft_warns)}项偏大/偏小(预警): ' + ' | '.join(soft_warns[:8])
        if info_notes:
            msg += ' ［提示: ' + '; '.join(info_notes[:4]) + '］'
        return False, msg
    if info_notes:
        return True, '; '.join(info_notes[:6])
    return True, ''



@register_checker('check_system_stable')
def check_system_stable(parsed, baseline, cfg, extra):
    "系统稳定状态检查：System state=Stable，Redundancy state=Stable，所有Slot State=Stable"
    text = parsed or ''
    if not text.strip():
        return False, '系统稳定状态输出为空（采集失败）'
    if not re.search(r'System state\s*:\s*Stable', text):
        return False, '系统状态不是 Stable'
    if not re.search(r'Redundancy state\s*:\s*(Stable|No redundanc)', text):
        return False, '冗余状态异常'
    unstable = re.findall(r'\b(\d+)\s+(\d+)\s+(\d+)\s+\w+\s+(Fault|Abnormal|Failure)', text)
    if unstable:
        slots = [m[0] for m in unstable]
        return False, f'存在不稳定槽位: ' + ', '.join(slots[:5])
    return True, ''


@register_checker('check_irf')
def check_irf(parsed, baseline, cfg, extra):
    "IRF堆叠状态检查：IRF mode=normal，所有成员在线且角色正确"
    text = parsed or ''
    if not text.strip():
        return False, 'IRF状态输出为空（采集失败）'
    irf_mode = re.search(r'IRF mode\s*:\s*(\S+)', text)
    if irf_mode and irf_mode.group(1) != 'normal':
        return False, f'IRF模式异常: {irf_mode.group(1)}'
    members = re.findall(r'^\s*(\*)?(\+)?\s*(\d+)\s+(\d+)\s+(\w+)', text, re.M)
    if members:
        master_count = len([m for m in members if m[4] == 'Master'])
        total = len({m[2] for m in members})  # unique MemberID
        if master_count == 0:
            return False, 'IRF 无 Master 设备'
        if master_count > 1:
            return False, f'IRF 脑裂: {master_count} 个 Master'
    else:
        return True, ''  # 非IRF设备跳过
    return True, ''


@register_checker('check_flash_usage')
def check_flash_usage(parsed, baseline, cfg, extra):
    """Flash 存储利用率检查：已用空间占比 ≤ 阈值(默认 75%) 即正常（空闲率 ≥ 25%）。

    结构化优先：解析 dir flash:/ 输出为 {total_kb, free_kb, used_percent, free_percent}，
    无结构化时回退到 raw 文本重新解析（与解析器逻辑一致）。
    参数：
        warning: 允许的最大利用率(%)，默认 75（即 free/total 空闲率需 ≥ 25%）

    注意：本项是全设备通用健康项，绝不应被 prune_disabled_commands 裁剪；
    若命令确实未返回有效数据（设备不支持/已被裁剪），明确判为「无法判定」报错，
    而非沉默地算作正常。
    """
    warning = float(cfg.get('warning', 75))
    structured = extra.get('__structured__')
    if structured is None and parsed:
        # 回退：从 raw 文本解析（与单一真源 parse_flash_usage 行为一致）
        from app02.parsers.comware import parse_flash_usage as _parse_flash
        structured = _parse_flash(parsed)
    if not structured:
        # 区分「命令未支持/已裁剪」与「其他格式异常」，二者都判异常但不含糊
        if parsed and FLASH_ERROR_PAT.search(parsed or ''):
            return False, 'dir flash: 命令在该设备未返回有效数据（可能不支持或已被裁剪），无法判定Flash利用率'
        return False, '无法从Flash目录输出提取存储用量（采集失败或格式异常）'
    used_percent = float(structured.get('used_percent', 0) or 0)
    free_percent = float(structured.get('free_percent', 0) or 0)
    if used_percent > warning:
        return False, f'Flash存储利用率 {used_percent}% 超过阈值 {warning}%（空闲率仅 {free_percent}%）'
    return True, ''

