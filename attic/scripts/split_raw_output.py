# -*- coding: utf-8 -*-
"""
拆分 inspection.py 的输出为 @init_checkitems Skill 需要的单命令文件格式。

输入格式（inspection.py 的输出）：
    ======
    设备巡检报告
    ...
    ======
    [命令] display cpu-usage
    [时间] 2026-07-16 18:31:13
    ------
    <命令输出>
    ======
    [命令] display fan
    ...

输出格式（Skill 需要）：
    media/raw/{站点}/{设备名}/
        display_cpu-usage.txt
        display_fan.txt
        ...

用法：
    # 拆分单个文件
    python split_raw_output.py --input inspection_output/.../fw001.....txt --site 化龙

    # 批量拆整个目录
    python split_raw_output.py --input-dir inspection_output/化龙设备清单_2026-07-16_1831/ --site 化龙

    # 指定输出根目录（默认 media/raw/）
    python split_raw_output.py --input-dir ... --site 化龙 --output-dir media/raw/
"""
import argparse
import os
import re
import sys

# 输出根目录
OUTPUT_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'media', 'raw')


def parse_report(filepath: str):
    """解析单台设备的巡检报告，返回 (设备名, {命令名: 命令输出})"""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    device_name = ''
    m = re.search(r'设备名称:\s*(.+)', content)
    if m:
        device_name = m.group(1).strip()

    # 按 [命令] 分隔
    # 格式: ======[命令] xxx[时间] xxx------(输出)======
    # 用正则拆成 (命令名, 输出)
    pattern = re.compile(
        r'={5,}\s*\n'
        r'\[命令\]\s*(.+?)\s*\n'
        r'\[时间\]\s*.+?\s*\n'
        r'-{5,}\s*\n'
        r'(.*?)'
        r'(?=\n={5,}\s*\n\[命令\]|$)',
        re.DOTALL
    )

    commands = {}
    for match in pattern.finditer(content):
        cmd_name = match.group(1).strip()
        output = match.group(2).strip()
        commands[cmd_name] = output

    return device_name, commands


def split_file(input_file: str, site: str, output_root: str = OUTPUT_ROOT):
    """拆分单个文件到 media/raw/{site}/{device}/ 目录"""
    device_name, commands = parse_report(input_file)

    if not device_name:
        print(f'[WARN] 无法解析设备名: {input_file}，使用文件名推导')
        device_name = os.path.splitext(os.path.basename(input_file))[0]

    if not commands:
        print(f'[WARN] 未找到任何命令输出: {input_file}')
        return 0

    # 创建设备目录
    device_dir = os.path.join(output_root, site, device_name)
    os.makedirs(device_dir, exist_ok=True)

    count = 0
    for cmd_name, output in commands.items():
        # 命令名中的空格替换为 _，作为文件名
        safe_name = cmd_name.replace(' ', '_').replace('/', '_')
        out_path = os.path.join(device_dir, f'{safe_name}.txt')
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(output)
        count += 1

    print(f'  ✅ {device_name}: {count} 条命令 → {device_dir}')
    return count


def split_dir(input_dir: str, site: str, output_root: str = OUTPUT_ROOT):
    """批量拆分目录下所有 .txt 文件"""
    total_files = 0
    total_cmds = 0

    for fname in os.listdir(input_dir):
        if fname.endswith('.txt') and '巡检汇总' not in fname:
            filepath = os.path.join(input_dir, fname)
            try:
                cmd_count = split_file(filepath, site, output_root)
                total_files += 1
                total_cmds += cmd_count
            except Exception as e:
                print(f'  ❌ {fname}: {e}')

    print(f'\n📊 总计: {total_files} 台设备, {total_cmds} 条命令')
    print(f'📁 输出目录: {os.path.join(output_root, site)}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='拆分 inspection.py 输出为单命令文件')
    parser.add_argument('--input', '-i', help='单个设备报告文件路径')
    parser.add_argument('--input-dir', '-d', help='批量拆分目录下的所有 .txt 文件')
    parser.add_argument('--site', '-s', required=True, help='站点名称（如 化龙/知识城）')
    parser.add_argument('--output-dir', '-o', default=OUTPUT_ROOT, help='输出根目录（默认 media/raw/）')
    args = parser.parse_args()

    if not args.input and not args.input_dir:
        parser.error('必须指定 --input 或 --input-dir')

    print(f'🔄 站点: {args.site}')

    if args.input_dir:
        split_dir(args.input_dir, args.site, args.output_dir)
    else:
        split_file(args.input, args.site, args.output_dir)