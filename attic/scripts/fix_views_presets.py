# -*- coding: utf-8 -*-
"""修复 views.py 预设：接口/路由表改 baseline，加收发光"""
with open('app02/views.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

updated = []
for line in lines:
    # 1. 接口预设: checker custom check_ifbrief → baseline
    if '"label": "【接口】接口DOWN数"' in line:
        line = line.replace('【接口】接口DOWN数', '【接口】接口状态（基线对比）')
    if '"note": "物理DOWN\u2264规划(down_ok)"' in line:
        line = line.replace('物理DOWN\u2264规划(down_ok)', 'A类基线全量对比，清晰展示UP/DOWN变化')
    if '"checker": "custom", "checker_config": _json.dumps({"func": "check_ifbrief"}, ensure_ascii=False),' in line:
        line = line.replace(
            '"checker": "custom", "checker_config": _json.dumps({"func": "check_ifbrief"}, ensure_ascii=False),',
            '"checker": "baseline", "checker_config": _json.dumps({"similarity": 1.0}, ensure_ascii=False),')

    # 2. 路由表预设: checker custom check_routing_table → baseline + all-vpn-instance
    if '"label": "【路由】路由表"' in line:
        line = line.replace('【路由】路由表', '【路由】路由表（基线对比）')
    if '"command": "display ip routing-table"' in line:
        line = line.replace('display ip routing-table', 'display ip routing-table all-vpn-instance')
    if '"note": "期望路由存在下一跳正确"' in line:
        line = line.replace('期望路由存在下一跳正确', 'A类基线全量对比含所有VPN实例，路由增删一目了然')
    if '"checker_config": _json.dumps({"func": "check_routing_table", "expected_routes": []}, ensure_ascii=False),' in line:
        line = line.replace(
            '{"func": "check_routing_table", "expected_routes": []}',
            '{"similarity": 1.0}')

    # 3. 在ARP冲突记录后插入收发光预设
    if '"note": "冲突记录清零"' in line:
        updated.append(line)
        updated.append('        },\n')
        updated.append('        {\n')
        updated.append('            "label": "【硬件】光模块收发光",\n')
        updated.append('            "command": "display transceiver diagnosis interface",\n')
        updated.append('            "parser": "raw", "parser_config": "{}",\n')
        updated.append('            "checker": "custom", "checker_config": _json.dumps({"func": "check_transceiver"}, ensure_ascii=False),\n')
        updated.append('            "note": "Temp/Voltage/Bias/RX/TX 越限即异常"\n')
        continue

    updated.append(line)

with open('app02/views.py', 'w', encoding='utf-8') as f:
    f.writelines(updated)

print('OK: views.py presets updated')
print('  接口 → baseline')
print('  路由表 → baseline + all-vpn-instance')
print('  光模块收发光 added')