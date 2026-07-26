# -*- coding: utf-8 -*-
"""
初始化新版巡检引擎数据
将旧版 device_table 中的 H3C 设备迁移到 NewDevice/DeviceGroup/CheckItem
执行: .\venv\Scripts\python.exe init_new_devices.py
"""
import os, sys, django
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'xunjian_system1.settings')
django.setup()

from app02.models import device_table, NewDevice, DeviceGroup, CheckItem

# ══════════════════════════════════════════════════════════
# 1. 创建设备分组
# ══════════════════════════════════════════════════════════
GROUPS = [
    {'name': 'H3C-接入层',  'description': 'H3C 接入层交换机'},
    {'name': 'H3C-汇聚层',  'description': 'H3C 汇聚层交换机'},
    {'name': 'H3C-核心层',  'description': 'H3C 核心层交换机'},
]

print('=== 创建设备分组 ===')
group_map = {}
for g in GROUPS:
    obj, created = DeviceGroup.objects.get_or_create(
        name=g['name'],
        defaults={'description': g['description']}
    )
    group_map[g['name']] = obj
    print(f"  {'新建' if created else '已存在'}: {g['name']}")

# ══════════════════════════════════════════════════════════
# 2. 迁移旧版 H3C 设备到 NewDevice
# ══════════════════════════════════════════════════════════
def pick_group(device_name):
    """根据设备名自动判断分组"""
    name = device_name.upper()
    if 'HX-CS' in name or 'CORE' in name:
        return group_map['H3C-核心层']
    elif 'ZHONGJI' in name or 'AGG' in name:
        return group_map['H3C-汇聚层']
    else:
        return group_map['H3C-接入层']

print('\n=== 迁移设备到新版 NewDevice ===')
old_devices = device_table.objects.filter(device_type='H3C')
for d in old_devices:
    group = pick_group(d.device)
    obj, created = NewDevice.objects.get_or_create(
        name=d.device,
        defaults={
            'ip':          d.ip,
            'group':       group,
            'device_type': 'H3C S6520X',
            'username':    d.user if d.user else 'admin',
            'password':    d.password if d.password else '',
            'extra':       {},
            'enabled':     True,
        }
    )
    print(f"  {'新建' if created else '已存在'}: {d.device} ({d.ip}) -> {group.name}")

# ══════════════════════════════════════════════════════════
# 3. 创建标准 H3C 巡检项
# ══════════════════════════════════════════════════════════
H3C_CHECK_ITEMS = [
    {
        'name':    '版本信息',
        'command': 'display version',
        'parser':  'raw',
        'checker': 'baseline',
        'error_note': '版本信息变化，请确认是否升级',
        'timeout': 30,
    },
    {
        'name':    '系统时钟',
        'command': 'display clock',
        'parser':  'raw',
        'checker': 'contains',
        'checker_config': {'keyword': '2026'},
        'error_note': '系统时钟异常，请检查',
        'timeout': 15,
    },
    {
        'name':    'NTP同步状态',
        'command': 'display ntp-service status',
        'parser':  'raw',
        'checker': 'contains',
        'checker_config': {'keyword': 'synchronized'},
        'error_note': 'NTP未同步，请检查时钟源',
        'timeout': 15,
    },
    {
        'name':    'NTP会话',
        'command': 'display ntp-service sessions',
        'parser':  'raw',
        'checker': 'baseline',
        'error_note': 'NTP会话变化，请检查',
        'timeout': 15,
    },
    {
        'name':    'Flash目录',
        'command': 'dir',
        'parser':  'raw',
        'checker': 'baseline',
        'error_note': 'Flash文件变化，请确认',
        'timeout': 30,
    },
    {
        'name':    '设备信息',
        'command': 'display device verbose',
        'parser':  'raw',
        'checker': 'baseline',
        'error_note': '设备信息变化，请检查',
        'timeout': 30,
    },
    {
        'name':    '温度状态',
        'command': 'display environment',
        'parser':  'raw',
        'checker': 'threshold',
        'error_note': '温度异常，请检查机房环境',
        'timeout': 15,
    },
    {
        'name':    '风扇状态',
        'command': 'display fan',
        'parser':  'raw',
        'checker': 'contains',
        'checker_config': {'keyword': 'Normal'},
        'error_note': '风扇异常，请立即检查',
        'timeout': 15,
    },
    {
        'name':    '电源状态',
        'command': 'display power',
        'parser':  'raw',
        'checker': 'contains',
        'checker_config': {'keyword': 'Normal'},
        'error_note': '电源异常，请立即检查',
        'timeout': 15,
    },
    {
        'name':    'CPU使用率',
        'command': 'display cpu-usage',
        'parser':  'raw',
        'checker': 'baseline',
        'error_note': 'CPU使用率变化，请检查',
        'timeout': 15,
    },
    {
        'name':    '内存使用',
        'command': 'display memory',
        'parser':  'raw',
        'checker': 'baseline',
        'error_note': '内存使用变化，请检查',
        'timeout': 15,
    },
    {
        'name':    '链路聚合',
        'command': 'display link-agg verbose',
        'parser':  'raw',
        'checker': 'baseline',
        'error_note': '链路聚合状态变化，请检查',
        'timeout': 30,
    },
    {
        'name':    '接口状态',
        'command': 'display interface',
        'parser':  'raw',
        'checker': 'baseline',
        'error_note': '接口状态变化，请检查',
        'timeout': 60,
    },
]

print('\n=== 创建H3C标准巡检项 ===')
check_items = []
for item in H3C_CHECK_ITEMS:
    obj, created = CheckItem.objects.get_or_create(
        name=item['name'],
        command=item['command'],
        defaults={
            'parser':         item.get('parser', 'raw'),
            'parser_config':  item.get('parser_config', None),
            'checker':        item.get('checker', 'baseline'),
            'checker_config': item.get('checker_config', None),
            'error_note':     item.get('error_note', '请检查'),
            'timeout':        item.get('timeout', 30),
            'enabled':        True,
        }
    )
    check_items.append(obj)
    print(f"  {'新建' if created else '已存在'}: [{obj.command}] {obj.name}")

# ══════════════════════════════════════════════════════════
# 4. 将巡检项绑定到所有分组
# ══════════════════════════════════════════════════════════
print('\n=== 绑定巡检项到分组 ===')
for g in group_map.values():
    g.check_items.set(check_items)
    print(f"  {g.name}: 已绑定 {len(check_items)} 个巡检项")

# ══════════════════════════════════════════════════════════
# 5. 汇总
# ══════════════════════════════════════════════════════════
print('\n' + '=' * 60)
print(f'完成！')
print(f'  设备分组: {DeviceGroup.objects.count()} 个')
print(f'  新版设备: {NewDevice.objects.count()} 台')
print(f'  巡检项:   {CheckItem.objects.count()} 个')
print()
print('下一步：')
print('  1. 进入系统 http://127.0.0.1:8000/new/device/list/ 检查设备，填写 SSH 账号密码')
print('  2. 进入 http://127.0.0.1:8000/new/xunjian/ 选择设备分组执行巡检')
