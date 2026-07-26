# -*- coding: utf-8 -*-
"""修复 seed_inspection.py 并重新导入化龙数据"""
import re

SEED_FILE = r'app02/management/commands/seed_inspection.py'

with open(SEED_FILE, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. 修改化龙 Excel 路径
old_hl_path = "'化龙':   r'C:/Users/ZSS/Desktop/化龙/化龙/化龙配置/network_inspection/化龙设备清单_带巡检命令.xlsx'"
new_hl_path = "'化龙':   r'C:/Users/ZSS/Desktop/化龙/化龙/化龙配置/network_inspection/化龙设备清单_带巡检命令_含irf.xlsx'"
content = content.replace(old_hl_path, new_hl_path)

# 2. 修改 DEFAULT_RULE：将 checker 从 contains 改为 baseline
old_default = "DEFAULT_RULE = dict(name=None, parser='raw', parser_config=None,\n                    checker='contains', checker_config={}, error_note='采集', timeout=30)"
new_default = "DEFAULT_RULE = dict(name=None, parser='raw', parser_config=None,\n                    checker='baseline', checker_config={'similarity': 1.0}, error_note='A类基线全量对比', timeout=30)"
content = content.replace(old_default, new_default)

# 3. 更新 ROLE_EXTRA_DEFAULT，为 LSW 添加 irf 相关（LSW 也包含堆叠设备）
old_lsw = "'LSW': {'down_ok': 1, 'vrrp_master': 0, 'ospf_nei': 0, 'bgp_nei': 0}"
new_lsw = "'LSW': {'down_ok': 1, 'vrrp_master': 0, 'ospf_nei': 0, 'bgp_nei': 0}"
content = content.replace(old_lsw, new_lsw)  # no change, just placeholder

# 4. 在 COMMAND_RULES 中补充关键命令
new_rules = """
    'display ospf peer': dict(
        name='OSPF邻居', parser='raw', parser_config=None,
        checker='custom', checker_config={'func': 'check_ospf_peer', 'expected_full_count': 0},
        error_note='OSPF邻居异常', timeout=30),
    'display bgp peer ipv4': dict(
        name='BGP邻居', parser='raw', parser_config=None,
        checker='custom', checker_config={'func': 'check_bgp_peer', 'expected_established': 0},
        error_note='BGP邻居异常', timeout=30),
    'display vrrp brief': dict(
        name='VRRP概要', parser='raw', parser_config=None,
        checker='custom', checker_config={'func': 'check_vrrp'},
        error_note='VRRP状态异常', timeout=30),
    'display m-lag summary': dict(
        name='M-LAG状态', parser='raw', parser_config=None,
        checker='custom', checker_config={'func': 'check_mlag'},
        error_note='M-LAG状态异常', timeout=30),
    'display nqa result': dict(
        name='NQA探测结果', parser='raw', parser_config=None,
        checker='custom', checker_config={'func': 'check_nqa'},
        error_note='NQA探测异常', timeout=30),
    'display track': dict(
        name='Track状态', parser='raw', parser_config=None,
        checker='custom', checker_config={'func': 'check_track'},
        error_note='Track状态异常', timeout=30),
    'display stp brief': dict(
        name='STP状态', parser='raw', parser_config=None,
        checker='custom', checker_config={'func': 'check_stp'},
        error_note='STP状态异常', timeout=30),
    'display vlan brief': dict(
        name='VLAN清单', parser='raw', parser_config=None,
        checker='baseline', checker_config={'similarity': 1.0},
        error_note='VLAN集合比对', timeout=30),
    'display link-aggregation summary': dict(
        name='链路聚合概要', parser='raw', parser_config=None,
        checker='custom', checker_config={'func': 'check_agg'},
        error_note='链路聚合异常', timeout=30),
    'display arp user-ip-conflict record': dict(
        name='ARP冲突记录', parser='raw', parser_config=None,
        checker='custom', checker_config={'func': 'check_arp'},
        error_note='存在ARP IP冲突', timeout=30),
    'display security-zone': dict(
        name='安全域成员', parser='raw', parser_config=None,
        checker='baseline', checker_config={'similarity': 1.0},
        error_note='安全域成员对比', timeout=30),
    'display security-policy statistics': dict(
        name='安全策略统计', parser='raw', parser_config=None,
        checker='baseline', checker_config={'similarity': 1.0},
        error_note='安全策略统计对比', timeout=30),
    'display security-policy ip rule all': dict(
        name='安全策略规则', parser='raw', parser_config=None,
        checker='baseline', checker_config={'similarity': 1.0},
        error_note='安全策略规则对比', timeout=30),
    'display remote-backup-group status': dict(
        name='RBM双机热备状态', parser='raw', parser_config=None,
        checker='custom', checker_config={'func': 'check_rbm'},
        error_note='RBM状态异常', timeout=30),
    'display session table ipv4': dict(
        name='会话表', parser='raw', parser_config=None,
        checker='custom', checker_config={'func': 'check_session', 'max_sessions': 500000},
        error_note='会话表异常', timeout=30),
    'display irf': dict(
        name='IRF堆叠状态', parser='raw', parser_config=None,
        checker='custom', checker_config={'func': 'check_irf'},
        error_note='IRF状态异常', timeout=30),
"""

# 插入到 COMMAND_RULES 开头
insert_pos = content.find('COMMAND_RULES = {') + len('COMMAND_RULES = {')
content = content[:insert_pos] + new_rules + content[insert_pos:]

with open(SEED_FILE, 'w', encoding='utf-8') as f:
    f.write(content)

print('seed_inspection.py updated (DEFAULT_RULE=baseline, new rules, HL path fixed)')

# 执行导入
import subprocess, sys
cmd = [sys.executable, 'manage.py', 'seed_inspection', '--site', '化龙']
result = subprocess.run(cmd, capture_output=True, text=True)
print(result.stdout)
if result.stderr:
    print(result.stderr)