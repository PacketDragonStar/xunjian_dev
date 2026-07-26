# -*- coding: utf-8 -*-
"""修复 commands_inspection.yaml：路由命令改为 all-vpn-instance"""
import os

path = r'C:\Users\ZSS\Desktop\化龙\化龙\化龙配置\network_inspection\commands_inspection.yaml'

with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# 替换所有 ip routing-table → ip routing-table all-vpn-instance
content = content.replace(
    '- display ip routing-table',
    '- display ip routing-table all-vpn-instance'
)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

# 统计
count = content.count('display ip routing-table all-vpn-instance')
print(f'OK: commands_inspection.yaml updated ({count} occurrences of all-vpn-instance)')
print(f'   文件: {path}')