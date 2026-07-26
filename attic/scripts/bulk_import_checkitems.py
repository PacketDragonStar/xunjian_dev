# -*- coding: utf-8 -*-
"""从化龙巡检项阈值配置表批量导入 CheckItem 并绑定到设备分组"""
import os, sys, json
import pandas as pd

# 临时设置 Django 环境
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'xunjian_system1.settings')
import django
django.setup()

from app02.models import CheckItem, DeviceGroup, NewDevice

EXCEL = '巡检项阈值配置表_化龙.xlsx'
ROLE_MAP = {
    '防火墙': ['GRP-化龙-FW'],
    '核心交换机': ['GRP-化龙-CSW'],
    '接入交换机': ['GRP-化龙-ASW', 'GRP-化龙-LSW'],
    'OA交换机': ['GRP-化龙-ASW'],
    '存储交换机': ['GRP-化龙-ASW'],
    'IDC交换机': ['GRP-化龙-ASW', 'GRP-化龙-LSW'],
    '路由器': ['GRP-化龙-SRP'],
}

xl = pd.ExcelFile(EXCEL)
total = 0

for sheet_name in xl.sheet_names:
    if sheet_name.startswith('防火墙1'):
        continue
    
    df = pd.read_excel(xl, sheet_name)
    groups = ROLE_MAP.get(sheet_name, [])
    if not groups:
        print(f'  ⚠️ {sheet_name}: 无对应分组，跳过')
        continue
    
    count = 0
    for _, row in df.iterrows():
        cmd = str(row['命令']).strip()
        if not cmd or cmd == 'nan':
            continue
        
        # 安全解析 JSON
        p_conf = row.get('parser_config')
        c_conf = row.get('checker_config')
        if pd.isna(p_conf) or str(p_conf) == 'nan' or not str(p_conf).strip():
            p_conf = None
        if pd.isna(c_conf) or str(c_conf) == 'nan' or not str(c_conf).strip():
            c_conf = None
        
        defaults = {
            'name': str(row['检查项']),
            'parser': str(row['parser']).strip(),
            'parser_config': p_conf,
            'checker': str(row['checker']).strip(),
            'checker_config': c_conf,
            'error_note': str(row['检查项']) + '异常',
            'timeout': 30,
            'enabled': True,
        }
        
        obj, created = CheckItem.objects.get_or_create(
            command=cmd,
            defaults=defaults
        )
        if created:
            count += 1
        
        # 绑定到分组
        for gname in groups:
            grp = DeviceGroup.objects.filter(name=gname).first()
            if grp and obj not in grp.check_items.all():
                grp.check_items.add(obj)
    
    print(f'  {sheet_name}: {df.shape[0]} 行, 新建 {count} 个, 绑定到 {groups}')
    total += count

# 更新设备所属分组
devices = NewDevice.objects.all()
for d in devices:
    if d.role and d.site:
        gname = f'GRP-{d.site}-{d.role}'
        grp = DeviceGroup.objects.filter(name=gname).first()
        if grp and d.group_id != grp.id:
            d.group = grp
            d.save()
            print(f'  设备 {d.name} → {gname}')

# 更新检查集
from app02.models import CheckSet
all_groups = DeviceGroup.objects.all()
cs, _ = CheckSet.objects.get_or_create(name='CS-化龙', defaults={'description': '化龙全量巡检集'})
cs.groups.set(all_groups)
print(f'\n ✅ 完成: 共处理 {total} 个新 CheckItem')
print(f' 检查集 CS-化龙 已绑定 {all_groups.count()} 个分组')