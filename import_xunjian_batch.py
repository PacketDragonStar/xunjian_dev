# -*- coding: utf-8 -*-
"""
巡检文件批量导入脚本
将指定目录下所有 GZBY*.txt 巡检文件解析后批量导入数据库
"""
import os
import sys
import re
from pathlib import Path

# ── Django 环境初始化 ──────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'xunjian_system1.settings')

import django
django.setup()

from app02.models import result_specific_table, device_table, result_overall_table

# ── 配置 ────────────────────────────────────────────────────
XUNJIAN_TIME = '2026-03-26_07-32-56'
OPERATOR     = 'admin'

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
    pattern = re.compile(
        r'={60}\s*\n命令:\s*(.+?)\s*\n={60}\s*\n(.*?)(?=\n={60}|\Z)',
        re.DOTALL
    )
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()
    results = []
    for m in pattern.finditer(content):
        cmd    = m.group(1).strip()
        result = m.group(2).strip()
        results.append((cmd, result))
    return results


def get_device_name_ip(filename):
    """从文件名提取设备名和IP，格式: DeviceName_IP.txt"""
    stem  = Path(filename).stem
    parts = stem.rsplit('_', 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return stem, ''


def import_file(filepath):
    filename    = os.path.basename(filepath)
    device_name, ip = get_device_name_ip(filename)

    # 确保设备存在于 device_table
    dev_obj, created = device_table.objects.get_or_create(
        device=device_name,
        defaults={
            'ip':          ip,
            'group_name':  '导入',
            'user':        '',
            'password':    '',
            'expand':      '',
            'device_type': 'H3C',
        }
    )
    if not created and dev_obj.ip != ip:
        # 更新IP（如有变化）
        dev_obj.ip = ip
        dev_obj.save()

    items = parse_xunjian_file(filepath)
    created_count = 0
    skip_count    = 0
    for cmd, result in items:
        _, c = result_specific_table.objects.get_or_create(
            time    = XUNJIAN_TIME,
            device  = device_name,
            command = cmd,
            defaults={'result': result}
        )
        if c:
            created_count += 1
        else:
            skip_count += 1

    status = 'new' if created else 'exist'
    print(f'  [{status}] {device_name} ({ip}) | 命令 {len(items)} 条 | 新增 {created_count} 跳过 {skip_count}')
    return len(items), created_count


def main():
    base = r'C:\Users\ZSS\Desktop\2026-03-26_07-32-56'

    # 找全量数据目录（名称含 '全量'）
    target_dir = None
    for d in os.listdir(base):
        full = os.path.join(base, d)
        if os.path.isdir(full):
            try:
                if '全量' in d:
                    target_dir = full
                    break
            except Exception:
                pass

    if not target_dir:
        # 编码问题时用字节比较
        for d in os.listdir(base):
            full = os.path.join(base, d)
            if os.path.isdir(full):
                try:
                    files = os.listdir(full)
                    if any(f.endswith('.txt') and f.startswith('GZBY') for f in files):
                        target_dir = full
                        break
                except Exception:
                    pass

    if not target_dir:
        print('未找到全量数据目录，请检查路径')
        sys.exit(1)

    print(f'数据目录: {target_dir}')
    print(f'巡检时间: {XUNJIAN_TIME}')
    print('=' * 60)

    txt_files = [
        os.path.join(target_dir, f)
        for f in os.listdir(target_dir)
        if f.endswith('.txt') and f.startswith('GZBY')
    ]
    txt_files.sort()

    if not txt_files:
        print('未找到任何 GZBY*.txt 文件')
        sys.exit(1)

    print(f'共找到 {len(txt_files)} 个设备文件')
    print()

    total_cmds    = 0
    total_created = 0
    for fp in txt_files:
        cmds, created = import_file(fp)
        total_cmds    += cmds
        total_created += created

    # 写入总体巡检记录
    result_overall_table.objects.get_or_create(
        time=XUNJIAN_TIME,
        defaults={
            'user_xnjian': OPERATOR,
            'jixian':      False,
            'result':      '正常',
        }
    )

    print()
    print('=' * 60)
    print(f'全部完成: {len(txt_files)} 台设备，共 {total_cmds} 条命令结果，新增 {total_created} 条记录')


if __name__ == '__main__':
    main()
