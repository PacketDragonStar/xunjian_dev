# -*- coding: utf-8 -*-
"""
巡检文件导入脚本
将巡检 txt 文件解析后导入到数据库的 result_specific_table 和 device_table
用法: python import_xunjian.py <txt文件路径> [巡检时间]
"""
import os
import sys
import django
import re
from pathlib import Path

# ── Django 环境初始化 ──────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'xunjian_system1.settings')
django.setup()

from app02.models import result_specific_table, device_table

# ── 解析函数 ────────────────────────────────────────────────
def parse_xunjian_file(filepath):
    """
    解析格式:
    ============================================================
    命令: <command>
    ============================================================
    <result lines...>
    
    返回: list of (command, result)
    """
    sep = '=' * 60
    results = []
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()

    # 按分隔线切分块
    pattern = re.compile(
        r'={60}\s*\n命令:\s*(.+?)\s*\n={60}\s*\n(.*?)(?=\n={60}|\Z)',
        re.DOTALL
    )
    for m in pattern.finditer(content):
        cmd = m.group(1).strip()
        result = m.group(2).strip()
        results.append((cmd, result))
    return results


def get_device_name_from_filename(filename):
    """从文件名提取设备名和IP，文件名格式: DeviceName_IP.txt"""
    stem = Path(filename).stem  # 去掉 .txt
    # 最后一段是 IP，前面是设备名
    parts = stem.rsplit('_', 1)
    if len(parts) == 2:
        device_name = parts[0]
        ip = parts[1]
    else:
        device_name = stem
        ip = ''
    return device_name, ip


def main():
    if len(sys.argv) < 2:
        print('用法: python import_xunjian.py <txt文件路径> [巡检时间]')
        print('示例: python import_xunjian.py C:\\Users\\ZSS\\Desktop\\2026-03-26_07-32-56\\...\\DEVICE.txt 2026-03-26_07-32-56')
        sys.exit(1)

    filepath = sys.argv[1]
    xunjian_time = sys.argv[2] if len(sys.argv) > 2 else '2026-03-26_07-32-56'

    if not os.path.exists(filepath):
        print(f'文件不存在: {filepath}')
        sys.exit(1)

    filename = os.path.basename(filepath)
    device_name, ip = get_device_name_from_filename(filename)
    print(f'设备名: {device_name}')
    print(f'IP:     {ip}')
    print(f'时间:   {xunjian_time}')

    # 确保设备存在于 device_table
    dev_obj, created = device_table.objects.get_or_create(
        device=device_name,
        defaults={
            'ip': ip,
            'group_name': '导入',
            'user': '',
            'password': '',
            'expand': '',
            'device_type': 'H3C',
        }
    )
    if created:
        print(f'已创建新设备记录: {device_name}')
    else:
        print(f'设备已存在，跳过创建: {device_name}')

    # 解析巡检结果
    items = parse_xunjian_file(filepath)
    print(f'共解析到 {len(items)} 条命令结果')

    # 写入 result_specific_table（如已存在同设备+时间+命令则跳过）
    created_count = 0
    skip_count = 0
    for cmd, result in items:
        obj, c = result_specific_table.objects.get_or_create(
            time=xunjian_time,
            device=device_name,
            command=cmd,
            defaults={'result': result}
        )
        if c:
            created_count += 1
        else:
            skip_count += 1

    print(f'导入完成: 新增 {created_count} 条，跳过重复 {skip_count} 条')


if __name__ == '__main__':
    main()
