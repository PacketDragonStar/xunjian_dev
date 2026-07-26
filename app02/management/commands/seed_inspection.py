"""
阶段 B · seed_inspection —— 单引擎巡检数据与设备种子命令（幂等、按站点分离部署）

功能：
  1. 以「命令」为唯一键，全局创建 CheckItem（去重，解析器/检查器规则见 COMMAND_RULES）。
  2. 按 (站点, 角色) 创建 DeviceGroup，并将该角色的命令集绑定到分组。
  3. 按站点创建 CheckSet（包含该站点全部角色分组）。
  4. 读取两个 Excel 设备清单，按设备名前缀推导 role、从文件名推导 site，
     导入 NewDevice 并设置连接参数(conn_type/port/enable_password/ssh_key_file)、
     role、site 以及每设备期望值(extra: down_ok/ospf_nei/bgp_nei/vrrp_master)。

设计要点（化龙/知识城分开部署）：
  - 通过 --site 只处理单一站点；每站点拥有独立的 Group( GRP-<站点>-<角色> )
    与 CheckSet( CS-<站点> )，数据互不干扰，可分别部署到两套环境。
  - CheckItem 全局复用（命令相同则不重复创建），仅分组/集合按站点隔离。

用法：
  python manage.py seed_inspection                 # 两个站点都建（默认）
  python manage.py seed_inspection --site 知识城    # 仅知识城
  python manage.py seed_inspection --site 化龙      # 仅化龙
  python manage.py seed_inspection --excel 路径.xlsx --site 化龙   # 指定Excel覆盖

重复执行安全：所有对象均用 get_or_create / update_or_create，不会翻倍。
"""
import os
import re
from collections import defaultdict

import openpyxl
from django.core.management.base import BaseCommand

from app02.models import (NewDevice, CheckItem, DeviceGroup, CheckSet,
                          device_class_of, DEVICE_CLASS_CHOICES)

# ═══════════════════════════════════════════════════════════
# 1. 两个站点的 Excel 路径
# ═══════════════════════════════════════════════════════════
# 路径基于项目根目录（manage.py 所在目录）计算，避免硬编码绝对路径导致找不到文件
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SITE_EXCEL = {
    '知识城': os.path.join(BASE_DIR, '知识城设备清单_已填充命令.xlsx'),
    '化龙':   os.path.join(BASE_DIR, '化龙设备清单_已填充命令_v2.xlsx'),
}

# ═══════════════════════════════════════════════════════════
# 2. 命令 -> 解析器/检查器规则（基于 hp_comware V7 真实输出）
#    仅采集类命令 checker=contains 且 checker_config={}（恒正常）。
# ═══════════════════════════════════════════════════════════
COMMAND_RULES = {
    # —— 路由/邻居（count：与每设备期望值 extra 比对，无邻居则期望为 0）——
    'display ospf peer': dict(
        name='OSPF邻居', parser='raw', parser_config=None,
        checker='count', checker_config={'keyword': 'Full', 'expand_field': 'ospf_nei',
                                         'note': 'OSPF Full 邻居数与期望不符'},
        error_note='OSPF邻居异常', timeout=30),
    'display bgp peer': dict(
        name='BGP邻居', parser='raw', parser_config=None,
        checker='count', checker_config={'keyword': 'Established', 'expand_field': 'bgp_nei',
                                         'note': 'BGP Established 邻居数与期望不符'},
        error_note='BGP邻居异常', timeout=30),

    # —— OSPF 控制面采集（拓扑/排障用，不做异常检查，scope=topology）——
    'display ospf lsdb': dict(
        name='OSPF LSDB', parser='raw', parser_config=None,
        checker='contains', checker_config={},
        error_note='OSPF LSDB采集', timeout=60),
    'display ospf routing': dict(
        name='OSPF路由表', parser='raw', parser_config=None,
        checker='contains', checker_config={},
        error_note='OSPF路由表采集', timeout=30),

    # —— 高可用 / 双机 ——
    'display remote-backup-group status': dict(
        name='RBM双机热备', parser='raw', parser_config=None,
        checker='custom', checker_config={'func': 'check_rbm'},
        error_note='RBM状态异常', timeout=30),
    'display track': dict(
        name='Track状态', parser='raw', parser_config=None,
        checker='custom', checker_config={'func': 'check_track'},
        error_note='Track状态异常', timeout=30),
    # —— 堆叠 / IRF（核心交换，提供给 network-seek 识别堆叠设备）——
    'display irf': dict(
        name='IRF堆叠', parser='raw', parser_config=None,
        checker='contains', checker_config={}, error_note='IRF堆叠采集', timeout=30),
    'display m-lag summary': dict(
        name='M-LAG概要', parser='raw', parser_config=None,
        checker='contains', checker_config={}, error_note='M-LAG采集', timeout=30),

    # —— 链路 / 接口 / VLAN / STP ——
    'display link-aggregation summary': dict(
        name='链路聚合概要', parser='raw', parser_config=None,
        checker='custom', checker_config={'func': 'check_agg'},
        error_note='链路聚合异常', timeout=30),
    'display link-aggregation verbose': dict(
        name='链路聚合详情', parser='raw', parser_config=None,
        checker='contains', checker_config={}, error_note='链路聚合详情采集', timeout=30),
    'display interface brief': dict(
        name='接口概要', parser='raw', parser_config=None,
        checker='custom', checker_config={'func': 'check_ifbrief'},
        error_note='接口输出为空', timeout=30),
    'display vlan brief': dict(
        name='VLAN清单', parser='raw', parser_config=None,
        checker='custom', checker_config={'func': 'check_vlan'},
        error_note='VLAN集合异常', timeout=30),
    'display stp brief': dict(
        name='STP状态', parser='raw', parser_config=None,
        checker='custom', checker_config={'func': 'check_stp'},
        error_note='STP状态异常', timeout=30),

    # —— 安全 ——
    'display arp user-ip-conflict record': dict(
        name='ARP冲突记录', parser='raw', parser_config=None,
        checker='custom', checker_config={'func': 'check_arp'},
        error_note='存在ARP IP冲突', timeout=30),
    'display session table ipv4': dict(
        name='会话表', parser='raw', parser_config=None,
        checker='custom', checker_config={'func': 'check_session', 'max_sessions': 500000},
        error_note='会话表异常', timeout=30),
    'display security-zone': dict(
        name='安全域', parser='raw', parser_config=None,
        checker='contains', checker_config={}, error_note='安全域采集', timeout=30),
    'display security-policy ip': dict(
        name='安全策略规则', parser='raw', parser_config=None,
        checker='contains', checker_config={}, error_note='安全策略规则采集', timeout=30),

    # —— 探测 / 时间 ——
    'display nqa result': dict(
        name='NQA探测结果', parser='raw', parser_config=None,
        checker='custom', checker_config={'func': 'check_nqa'},
        error_note='NQA探测异常', timeout=30),
    'display ntp status': dict(
        name='NTP状态', parser='raw', parser_config=None,
        checker='contains',
        checker_config={'must_contain': ['Clock status: synchronized']},
        error_note='NTP未同步', timeout=30),

    # —— 资源 / 健康 ——
    'display cpu-usage': dict(
        name='CPU使用率', parser='raw', parser_config=None,
        checker='custom', checker_config={'func': 'check_cpu', 'warning': 40},
        error_note='CPU使用率超过40%', timeout=30),
    'display memory': dict(
        name='内存空闲率', parser='raw', parser_config=None,
        checker='custom', checker_config={'func': 'check_memory', 'warning': 40},
        error_note='内存空闲率低于40%', timeout=30,
        extract_parser='memory'),
    'display environment': dict(
        name='环境温度', parser='raw', parser_config=None,
        checker='custom', checker_config={'func': 'check_env'}, error_note='环境温度异常', timeout=30),
    'display fan': dict(
        name='风扇状态', parser='raw', parser_config=None,
        checker='custom', checker_config={'func': 'check_fan'}, error_note='风扇状态异常', timeout=30),
    'display power': dict(
        name='电源状态', parser='raw', parser_config=None,
        checker='custom', checker_config={'func': 'check_power'}, error_note='电源状态异常', timeout=30),
    'display device': dict(
        name='单板状态', parser='raw', parser_config=None,
        checker='custom', checker_config={'func': 'check_device'}, error_note='单板/部件状态异常', timeout=30),
    'display transceiver diagnosis interface': dict(
        name='光模块诊断', parser='raw', parser_config=None,
        checker='custom', checker_config={'func': 'check_transceiver'},
        error_note='光模块收发异常', timeout=30),
    'display system stable state': dict(
        name='系统稳定状态', parser='raw', parser_config=None,
        checker='custom', checker_config={'func': 'check_system_stable'},
        error_note='系统稳定状态异常', timeout=30),
    'display logbuffer': dict(
        name='日志缓冲', parser='raw', parser_config=None,
        checker='custom', checker_config={'func': 'check_logbuffer'},
        error_note='日志存在严重级别', timeout=30,
        compare_strip={'head_lines': 6}),

    # —— 采集类（纯收集，不判错）——
    'display lldp neighbor-information list': dict(
        name='LLDP邻居', parser='raw', parser_config=None,
        checker='contains', checker_config={}, error_note='LLDP采集', timeout=30),
    'display ip routing-table': dict(
        name='路由表', parser='raw', parser_config=None,
        checker='custom', checker_config={'func': 'check_routing_table'}, error_note='路由表采集', timeout=30),
    'display ip routing-table all-vpn-instance': dict(
        name='路由表(全VPN)', parser='raw', parser_config=None,
        checker='contains', checker_config={}, error_note='路由表采集', timeout=30),
    'display current-configuration': dict(
        name='当前配置', parser='raw', parser_config=None,
        checker='contains', checker_config={}, error_note='配置采集', timeout=30),
    'display version': dict(
        name='版本信息', parser='raw', parser_config=None,
        checker='contains', checker_config={}, error_note='版本采集', timeout=30),
    'display device manuinfo': dict(
        name='设备序列号', parser='raw', parser_config=None,
        checker='contains', checker_config={}, error_note='序列号采集', timeout=30),
    'display vrrp verbose': dict(
        name='VRRP全量', parser='raw', parser_config=None,
        checker='contains', checker_config={}, error_note='VRRP采集', timeout=30),
    'display counters inbound interface': dict(
        name='入向计数', parser='raw', parser_config=None,
        checker='contains', checker_config={}, error_note='入向计数采集', timeout=30),
    'display counters outbound interface': dict(
        name='出向计数', parser='raw', parser_config=None,
        checker='contains', checker_config={}, error_note='出向计数采集', timeout=30),
    'dir flash:/': dict(
        name='Flash存储利用率', parser='raw', parser_config=None,
        checker='custom', checker_config={'func': 'check_flash_usage', 'warning': 75},
        error_note='Flash存储利用率超过75%', timeout=30),
}

# 未知命令的兜底规则（纯采集，不判错；避免无基线时一律报错）
DEFAULT_RULE = dict(name=None, parser='raw', parser_config=None,
                    checker='contains', checker_config={}, error_note='未配置检查规则的命令（仅采集）', timeout=30)

# 检查项默认严重级别：资源/可用性/协议类异常归 P1，ARP 冲突归 P0，纯采集归 P2。
# 巡检结果将按此级别在验收报告中分级统计（P0/P1/P2）。
SEVERITY_DEFAULTS = {
    'display cpu-usage': 'P1',
    'display memory': 'P1',
    'display environment': 'P1',
    'display fan': 'P1',
    'display power': 'P1',
    'display device': 'P1',
    'display interface brief': 'P1',
    'display ospf peer': 'P1',
    'display ospf lsdb': 'P2',
    'display ospf routing': 'P2',
    'display bgp peer': 'P1',
    'display m-lag summary': 'P1',
    'display remote-backup-group status': 'P1',
    'display irf': 'P1',
    'display stp brief': 'P1',
    'display track': 'P1',
    'display ntp status': 'P1',
    'display security-zone': 'P1',
    'display security-policy ip': 'P1',
    'display vlan brief': 'P1',
    'display arp user-ip-conflict record': 'P0',
    'display transceiver diagnosis interface': 'P2',
    'display logbuffer': 'P2',
    'display session table ipv4': 'P1',
    'display link-aggregation summary': 'P1',
    'display link-aggregation verbose': 'P1',
    'display nqa result': 'P1',
    'dir flash:/': 'P1',
}

# 特性命令 → feature 标签（其余命令默认 base，恒跑）
COMMAND_FEATURE = {
    'display ospf peer': 'ospf',
    'display ospf lsdb': 'ospf',
    'display ospf routing': 'ospf',
    'display bgp peer': 'bgp',
    'display irf': 'irf',
    'display m-lag summary': 'm-lag',
    'display link-aggregation verbose': 'lacp',
    'display vrrp verbose': 'vrrp',
    'display remote-backup-group status': 'rbm',
    'display security-zone': 'security',
    'display security-policy ip': 'security',
}

# device_class -> 中文标签（用于 DeviceGroup 描述）
DEVICE_CLASS_LABEL = dict(DEVICE_CLASS_CHOICES)

# ═══════════════════════════════════════════════════════════
# 3. 角色推断与每角色默认值
# ═══════════════════════════════════════════════════════════
def role_of(name: str) -> str:
    s = (name or '').lower()
    if s.startswith('fw'):   return 'FW'
    if s.startswith('csw'):  return 'CSW'
    if s.startswith('srp'):  return 'SRP'
    if s.startswith(('asw', 'idc', 'oas', 'psw', 'usw')): return 'ASW'
    if s.startswith(('dci', 'dsw')): return 'LSW'
    return 'OTHER'


# 每角色每设备 extra 默认值（邻居数 / DOWN口容忍）。可在界面逐设备覆盖。
ROLE_EXTRA_DEFAULT = {
    'FW':  {'down_ok': 0, 'vrrp_master': 1, 'ospf_nei': 0, 'bgp_nei': 0},
    'CSW': {'down_ok': 0, 'vrrp_master': 1, 'ospf_nei': 2, 'bgp_nei': 1},
    'ASW': {'down_ok': 2, 'vrrp_master': 0, 'ospf_nei': 0, 'bgp_nei': 0},
    'LSW': {'down_ok': 1, 'vrrp_master': 0, 'ospf_nei': 0, 'bgp_nei': 0},
    'SRP': {'down_ok': 0, 'vrrp_master': 0, 'ospf_nei': 1, 'bgp_nei': 1},
    'OTHER': {'down_ok': 0, 'vrrp_master': 0, 'ospf_nei': 0, 'bgp_nei': 0},
}

ROLE_LABEL = {'FW': '防火墙', 'CSW': '核心交换', 'ASW': '接入交换',
              'LSW': '轻量交换', 'SRP': '业务路由', 'OTHER': '其他'}

# 高可用/堆叠/安全域 命令：按角色自动注入到采集集（无需改 Excel 即可采集）。
# 这些命令用于 network-seek 识别 M-LAG / 堆叠 / VRRP / 防火墙策略。
# 若某设备未开启该协议（回显失败/空），首次全量采集后可运行
# `prune_disabled_commands` 将其从单设备巡检中剔除（见自适应裁剪）。
ROLE_EXTRA_COMMANDS = {
    'CSW': ['display irf', 'display m-lag summary',
            'display link-aggregation verbose', 'display vrrp verbose'],
    'FW':  ['display security-zone', 'display security-policy ip',
            'display remote-backup-group status', 'display vrrp verbose'],
}


# ═══════════════════════════════════════════════════════════
# 4. Excel 读取
# ═══════════════════════════════════════════════════════════
def _find_col(hdr, *keys):
    for i, h in enumerate(hdr):
        h = str(h)
        for k in keys:
            if k in h:
                return i
    return None


def read_site_excel(path: str, site: str):
    """返回 (devices, role_cmds)
       devices: list of dict(name, ip, device_type, username, password,
                             conn_type, port, enable_password, ssh_key_file, role)
       role_cmds: dict role -> canonical command list (mode)
    """
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    hdr = [str(c).strip() if c is not None else '' for c in rows[0]]
    name_i = _find_col(hdr, '设备名称')
    ip_i   = _find_col(hdr, 'IP')
    conn_i = _find_col(hdr, '连接方式')
    port_i = _find_col(hdr, '端口')
    user_i = _find_col(hdr, '用户名')
    pwd_i  = _find_col(hdr, '密码')
    type_i = _find_col(hdr, '设备类型')
    en_i   = _find_col(hdr, 'enable')
    key_i  = _find_col(hdr, '密钥')
    cmd_i  = _find_col(hdr, '命令')

    devices = []
    role_sigs = defaultdict(list)
    for r in rows[1:]:
        if not r[name_i]:
            continue
        name = str(r[name_i]).strip()
        cls = device_class_of(name)       # 基础分类真源（命名规则）
        role = role_of(name)              # 仅用于 extra 默认值（兼容旧行为）
        cmds = str(r[cmd_i] or '') if cmd_i is not None else ''
        cl = [p.strip() for p in re.split(r'[\n;,]+', cmds) if p and p.strip()]
        role_sigs[cls].append(' || '.join(cl))

        conn = str(r[conn_i] or 'ssh').strip().lower() if conn_i is not None else 'ssh'
        conn_type = 'telnet' if conn.startswith('telnet') else 'ssh'
        port_raw = r[port_i] if port_i is not None else None
        try:
            port = int(port_raw) if port_raw not in (None, '') else None
        except (ValueError, TypeError):
            port = None

        devices.append(dict(
            name=name,
            ip=str(r[ip_i] or '').strip(),
            device_type=str(r[type_i] or 'hp_comware').strip(),
            username=str(r[user_i] or '').strip(),
            password=str(r[pwd_i] or '').strip(),
            conn_type=conn_type,
            port=port,
            enable_password=str(r[en_i] or '').strip() if en_i is not None else '',
            ssh_key_file=str(r[key_i] or '').strip() if key_i is not None else '',
            role=role,
            device_class=cls,
            site=site,
        ))

    # 每个 device_class 取出现最多的命令签名作为 canonical 命令集
    role_cmds = {}
    for cls, sigs in role_sigs.items():
        if not sigs:
            continue
        counter = defaultdict(int)
        for s in sigs:
            counter[s] += 1
        canon = max(counter, key=counter.get)
        role_cmds[cls] = [c for c in canon.split(' || ') if c]

    return devices, role_cmds


# ═══════════════════════════════════════════════════════════
# 5. 命令执行
# ═══════════════════════════════════════════════════════════
# ═════════════════════════════════════════════════
# 阶段 C：合规策略种子（幂等，可界面增删规则）
# ═════════════════════════════════════════════════
def ensure_compliance_policies():
    from app02.models import CompliancePolicy, ComplianceRule
    policy, _ = CompliancePolicy.objects.update_or_create(
        name='基础合规基线',
        defaults=dict(description='NTP/日志/空闲超时/Telnet 等基础配置合规基线（可在界面增删规则）'))
    starter = [
        ('NTP已同步', 'display ntp status', 'regex', r'Clock status\s*:?\s*synchronized', 'P1', 'NTP 未同步'),
        ('日志主机已配置', 'display current-configuration', 'contains', 'info-center loghost', 'P1', '未配置日志主机(info-center loghost)'),
        ('VTY空闲超时', 'display current-configuration', 'contains', 'idle-timeout', 'P2', '未配置 VTY 空闲超时'),
        ('Telnet未启用', 'display current-configuration', 'absence', 'telnet server enable', 'P1', '不应启用 Telnet 服务'),
        ('SNMP已配置', 'display current-configuration', 'contains', 'snmp-agent', 'P2', '未启用 SNMP'),
    ]
    for name, cmd, rtype, pat, sev, note in starter:
        ComplianceRule.objects.update_or_create(
            policy=policy, name=name,
            defaults=dict(source_command=cmd, rule_type=rtype, pattern=pat,
                          severity=sev, note=note, enabled=True))
    return policy


class Command(BaseCommand):
    help = '单引擎巡检数据种子：创建CheckItem/DeviceGroup/CheckSet并导入设备（按站点分离、幂等）'

    def add_arguments(self, parser):
        parser.add_argument('--site', default='all',
                            choices=['all', '知识城', '化龙'],
                            help='只处理指定站点（默认 all=两个站点都处理）')
        parser.add_argument('--excel', default=None,
                            help='指定Excel路径覆盖默认（需配合 --site 指定归属站点）')
        parser.add_argument('--force', action='store_true',
                            help='强制用模板刷新所有已存在的 CheckItem（会覆盖网页自定义配置）。'
                                 '默认不传：只新建缺失项、不覆盖已有项，保护用户在网页上的自定义。')

    def handle(self, *args, **opts):
        site_arg = opts['site']
        excel_override = opts['excel']
        force = opts.get('force', False)

        sites = ['知识城', '化龙'] if site_arg == 'all' else [site_arg]

        # 1) 全局 CheckItem（命令去重）
        item_cache = {}
        created_items = 0
        for cmd, rule in COMMAND_RULES.items():
            # 默认 get_or_create：只新建缺失项、不覆盖已存在的 CheckItem，
            # 以保护用户在网页上自定义的 checker / 阈值等配置（重跑 seed 不再破坏网页改动）。
            # 仅当显式传入 --force 时才用模板刷新所有已存在项（开发者批量推广代码模板时使用）。
            if force:
                obj, created = CheckItem.objects.update_or_create(
                    command=cmd,
                    defaults=dict(
                        name=rule['name'] or cmd,
                        parser=rule['parser'],
                        parser_config=rule['parser_config'],
                        checker=rule['checker'],
                        checker_config=rule['checker_config'],
                        error_note=rule['error_note'],
                        timeout=rule.get('timeout', 30),
                        severity=SEVERITY_DEFAULTS.get(cmd, 'P2'),
                        feature=COMMAND_FEATURE.get(cmd, 'base'),
                        extract_parser=rule.get('extract_parser', ''),
                        compare_strip=rule.get('compare_strip'),
                    ),
                )
            else:
                obj, created = CheckItem.objects.get_or_create(
                    command=cmd,
                    defaults=dict(
                        name=rule['name'] or cmd,
                        parser=rule['parser'],
                        parser_config=rule['parser_config'],
                        checker=rule['checker'],
                        checker_config=rule['checker_config'],
                        error_note=rule['error_note'],
                        timeout=rule.get('timeout', 30),
                        severity=SEVERITY_DEFAULTS.get(cmd, 'P2'),
                        feature=COMMAND_FEATURE.get(cmd, 'base'),
                        extract_parser=rule.get('extract_parser', ''),
                        compare_strip=rule.get('compare_strip'),
                    ),
                )
            if created:
                created_items += 1
            item_cache[cmd] = obj
        self.stdout.write(self.style.SUCCESS(f'CheckItem: 共 {len(item_cache)} 个，新建 {created_items} 个'))

        # 1.5) 阶段 C 合规策略（幂等）
        try:
            p = ensure_compliance_policies()
            self.stdout.write(self.style.SUCCESS(f'合规策略: {p.name} 已就绪'))
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'合规策略种子跳过: {e}'))

        total_dev = 0
        total_grp = 0
        total_set = 0

        for site in sites:
            excel_path = excel_override if (excel_override and site_arg == site) else SITE_EXCEL[site]
            try:
                devices, role_cmds = read_site_excel(excel_path, site)
            except FileNotFoundError:
                self.stdout.write(self.style.WARNING(f'[{site}] Excel 未找到，跳过: {excel_path}'))
                continue

            # 自动注入「设备序列号」采集命令到每个角色（无需改 Excel 即可采集 SN）
            # 仅当该命令已在 COMMAND_RULES 中定义才注入，保证 CheckItem 元数据正确。
            for inject in ('display device manuinfo', 'dir flash:/'):
                if inject in COMMAND_RULES:
                    for role in role_cmds:
                        if inject not in role_cmds[role]:
                            role_cmds[role].append(inject)

            # 2) 每个 (site, device_class) 建 DeviceGroup 并绑定命令
            #    - base 项：该 device_class 的 canonical 命令集（来自 Excel）
            #    - feature 项：全局所有协议特性 CheckItem（由 capability 门控决定实际跑哪些）
            #    （已撤销 ROLE_EXTRA_COMMANDS 按角色注入 —— 特性命令不再与 role 耦合）
            feature_items = [obj for obj in item_cache.values()
                             if getattr(obj, 'feature', 'base') != 'base']
            site_groups = []
            for cls, cmds in role_cmds.items():
                grp_name = f'GRP-{site}-{cls}'
                grp, _ = DeviceGroup.objects.get_or_create(name=grp_name)
                base_items = [item_cache[c] for c in cmds if c in item_cache]
                # 未知/缺失命令兜底创建（纯采集，feature=base）
                for c in cmds:
                    if c not in item_cache:
                        if force:
                            obj, _ = CheckItem.objects.update_or_create(
                                command=c, defaults=dict(
                                    name=DEFAULT_RULE['name'] or c, parser=DEFAULT_RULE['parser'],
                                    parser_config=DEFAULT_RULE['parser_config'],
                                    checker=DEFAULT_RULE['checker'],
                                    checker_config=DEFAULT_RULE['checker_config'],
                                    error_note=DEFAULT_RULE['error_note'],
                                    timeout=DEFAULT_RULE['timeout'],
                                    severity=SEVERITY_DEFAULTS.get(c, 'P2'),
                                    feature='base'))
                        else:
                            obj, _ = CheckItem.objects.get_or_create(
                                command=c, defaults=dict(
                                    name=DEFAULT_RULE['name'] or c, parser=DEFAULT_RULE['parser'],
                                    parser_config=DEFAULT_RULE['parser_config'],
                                    checker=DEFAULT_RULE['checker'],
                                    checker_config=DEFAULT_RULE['checker_config'],
                                    error_note=DEFAULT_RULE['error_note'],
                                    timeout=DEFAULT_RULE['timeout'],
                                    severity=SEVERITY_DEFAULTS.get(c, 'P2'),
                                    feature='base'))
                        item_cache[c] = obj
                        base_items.append(obj)
                # 若该 class 无 canonical 命令（如 OTHER），退化为全局 base 命令，保证仍跑基础巡检
                if not base_items:
                    base_items = [obj for obj in item_cache.values()
                                  if getattr(obj, 'feature', None) == 'base']
                # 去重保序：base 在前，feature 在后
                items = list(dict.fromkeys(base_items + feature_items))
                grp.check_items.set(items)
                cls_label = DEVICE_CLASS_LABEL.get(cls, cls)
                if grp.description != f'{site} {cls_label}':
                    grp.description = f'{site} {cls_label}'
                    grp.save(update_fields=['description'])
                site_groups.append(grp)
                total_grp += 1
                self.stdout.write(
                    f'  [{site}] {grp_name}: {len(items)} 个巡检项 '
                    f'(base {len(base_items)} + feature {len(feature_items)})')

            # 3) 每站点 CheckSet
            cs_name = f'CS-{site}'
            cs, _ = CheckSet.objects.get_or_create(name=cs_name, defaults=dict(
                description=f'{site} 全量巡检集'))
            cs.groups.set(site_groups)
            total_set += 1

            # 4) 导入设备
            for d in devices:
                extra = dict(ROLE_EXTRA_DEFAULT.get(d['role'], ROLE_EXTRA_DEFAULT['OTHER']))
                NewDevice.objects.update_or_create(
                    name=d['name'],
                    defaults=dict(
                        ip=d['ip'],
                        device_type=d['device_type'],
                        username=d['username'],
                        password=d['password'],
                        conn_type=d['conn_type'],
                        port=d['port'],
                        enable_password=d['enable_password'],
                        ssh_key_file=d['ssh_key_file'],
                        role=d['role'],
                        device_class=d['device_class'],
                        site=d['site'],
                        group=DeviceGroup.objects.filter(name=f"GRP-{d['site']}-{d['device_class']}").first(),
                        extra=extra,
                        enabled=True,
                    ),
                )
                total_dev += 1

            self.stdout.write(self.style.SUCCESS(
                f'[{site}] 设备 {len(devices)} 台, 分组 {len(site_groups)} 个, 检查集 {cs_name}'))

        self.stdout.write(self.style.SUCCESS(
            f'\n完成: CheckItem {len(item_cache)} / DeviceGroup {total_grp} / '
            f'CheckSet {total_set} / NewDevice {total_dev}'))
