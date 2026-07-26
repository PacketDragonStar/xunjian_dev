# -*- coding: utf-8 -*-
"""重新初始化化龙数据：删除所有旧 CheckItem，从 Excel 重新导入并绑定分组"""
import os, sys, json
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'xunjian_system1.settings')
import django
django.setup()

import pandas as pd
from app02.models import CheckItem, DeviceGroup, NewDevice, CheckSet

EXCEL = '巡检项阈值配置表_化龙.xlsx'
ROLE_MAP = {
    '防火墙': 'GRP-化龙-FW',
    '核心交换机': 'GRP-化龙-CSW',
    '接入交换机': 'GRP-化龙-ASW',
    'OA交换机': 'GRP-化龙-ASW',
    '存储交换机': 'GRP-化龙-ASW',
    'IDC交换机': 'GRP-化龙-ASW',
    '路由器': 'GRP-化龙-SRP',
}

# 1. 删除所有旧 CheckItem 和旧分组
print('清理旧数据...')
CheckItem.objects.all().delete()
DeviceGroup.objects.filter(name__startswith='GRP-化龙-').delete()
DeviceGroup.objects.filter(name__startswith='H3C-').delete()
print('  已清除 CheckItem 和旧分组')

# 2. 创建新分组
ROLE_NAMES = {
    'SRP': '路由器', 'FW': '防火墙', 'ASW': '接入交换机', 'CSW': '核心交换机', 'LSW': '轻量交换'
}
for role, site in [('SRP','化龙'),('FW','化龙'),('ASW','化龙'),('CSW','化龙'),('LSW','化龙')]:
    DeviceGroup.objects.get_or_create(
        name=f'GRP-{site}-{role}',
        defaults={'description': f'{site} {ROLE_NAMES.get(role, role)}'}
    )

# 3. 从 Excel 读所有角色命令
xl = pd.ExcelFile(EXCEL)
group_map = {}  # 分组名 → [命令列表]

for sheet_name in xl.sheet_names:
    if sheet_name.startswith('防火墙1'):
        continue
    gname = ROLE_MAP.get(sheet_name)
    if not gname:
        continue
    if gname not in group_map:
        group_map[gname] = []
    
    df = pd.read_excel(xl, sheet_name)
    for _, row in df.iterrows():
        cmd = str(row['命令']).strip()
        if not cmd or cmd == 'nan' or cmd in group_map[gname]:
            continue
        group_map[gname].append(cmd)

# 4. 创建/更新 CheckItem
item_lookup = {}
print('创建 CheckItem 并绑定分组...')
for gname, cmds in group_map.items():
    grp = DeviceGroup.objects.get(name=gname)
    items = []
    for cmd in cmds:
        if cmd in item_lookup:
            obj = item_lookup[cmd]
        else:
            # 从 Excel 获取 parser/checker 配置
            parser, checker, p_conf, c_conf = 'raw', 'baseline', None, {'similarity': 1.0}
            for sheet_name in xl.sheet_names:
                if sheet_name.startswith('防火墙1'):
                    continue
                df = pd.read_excel(xl, sheet_name)
                for _, row in df.iterrows():
                    if str(row['命令']).strip() == cmd:
                        parser = str(row['parser']).strip()
                        checker = str(row['checker']).strip()
                        p_val = row.get('parser_config')
                        c_val = row.get('checker_config')
                        if pd.notna(p_val) and str(p_val) != 'nan' and str(p_val).strip():
                            p_conf = str(p_val).strip()
                        if pd.notna(c_val) and str(c_val) != 'nan' and str(c_val).strip():
                            c_conf = str(c_val).strip()
                        break
            
            obj, _ = CheckItem.objects.update_or_create(
                command=cmd,
                defaults={
                    'name': cmd,
                    'parser': parser,
                    'parser_config': p_conf if p_conf and p_conf != '{}' else None,
                    'checker': checker,
                    'checker_config': c_conf if c_conf and c_conf != '{}' else None,
                    'error_note': f'{cmd}检查',
                    'timeout': 30,
                    'enabled': True,
                }
            )
            item_lookup[cmd] = obj
        
        items.append(obj)
    
    grp.check_items.set(items)
    print(f'  {gname}: {len(items)} 个巡检项')

# 5. 设备绑定分组
for d in NewDevice.objects.all():
    if d.role and d.site:
        gname = f'GRP-{d.site}-{d.role}'
        grp = DeviceGroup.objects.filter(name=gname).first()
        if grp and d.group_id != grp.id:
            d.group = grp
            d.save()

# 6. 检查集绑定
cs, _ = CheckSet.objects.get_or_create(name='CS-化龙', defaults={'description': '化龙全量巡检集'})
all_groups = DeviceGroup.objects.filter(name__startswith='GRP-化龙-')
cs.groups.set(all_groups)

# 7. 验证
print('\n=== 验证报告 ===')
print(f'CheckItem 总数: {CheckItem.objects.count()}')
print(f'DeviceGroup:')
for g in DeviceGroup.objects.filter(name__startswith='GRP-化龙-').prefetch_related('check_items'):
    items = g.check_items.all()
    # 统计 checker 类型分布
    from collections import Counter
    checker_dist = Counter(c.checker for c in items)
    print(f'  {g.name}: {items.count()} 项 checker={dict(checker_dist)}')

print(f'\nCheckSet:')
for cs in CheckSet.objects.prefetch_related('groups').all():
    print(f'  {cs.name}: {cs.groups.count()} 个分组')

print('\n✅ 完成，可以执行巡检。')