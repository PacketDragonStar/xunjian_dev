# -*- coding: utf-8 -*-
"""演示：直接用 pipeline 检查 raw log，无需 Django + MySQL"""
import sys, os, json

# 设置 Django settings 模块（绕过 MySQL 连接）
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "xunjian_system1.settings")
import django
from django.conf import settings
# 切换到 SQLite 内存模式，避免 MySQL 连接问题
settings.DATABASES['default'] = {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}
django.setup()

# 导入 pipeline
from app02.engine.pipeline import parse_raw, check_custom, _CUSTOM_CHECKERS
from app02.engine.reporter import extract_diff_summary

# 触发自定义 checker 注册
import app02.custom_checks  # noqa

print("=" * 60)
print("  Checker 微调演示 — 直接跑 raw log")
print("=" * 60)

# 演示 1: check_fan（正常）
raw = open(r'media\raw\知识城\oasw001&002.a.pri.zscidc2f1.gzxc-hlw/display_fan.txt', encoding='utf8').read()
print(f"\n📥 读文件: display_fan.txt ({len(raw)} chars)")
print(f"  内容: {raw.strip()[:100]}")

parsed = parse_raw(raw, {})
is_ok, notes = check_custom(parsed, None, {"func": "check_fan"}, {})
print(f"\n  {'✅' if is_ok else '❌'} Parser=raw  Checker=check_fan")
print(f"  结果: {'正常' if is_ok else '异常'}")
if notes:
    print(f"  说明: {notes}")

# 演示 2: check_fan（异常模拟）
raw_bad = "Fan 1 State: Fault\nFan 2 State: Normal"
parsed_bad = parse_raw(raw_bad, {})
is_ok2, notes2 = check_custom(parsed_bad, None, {"func": "check_fan"}, {})
print(f"\n  {'✅' if is_ok2 else '❌'} 模拟异常输入: \"{raw_bad}\"")
print(f"  结果: {'正常' if is_ok2 else '异常'}  → {notes2}")

# 演示 3: 基线对比
print(f"\n{'='*60}")
print("  基线对比演示 (display logbuffer)")
print("=" * 60)
raw_curr = open(r'media\raw\知识城\oasw001&002.a.pri.zscidc2f1.gzxc-hlw/display_logbuffer.txt', encoding='utf8').read()
raw_base = open(r'media\raw\知识城\oasw003&004.a.pri.zscidc2f1.gzxc-hlw/display_logbuffer.txt', encoding='utf8').read()
curr_s, base_s, diff = extract_diff_summary(raw_curr[:2000], raw_base[:2000])
print(f"\n  📊 差异行 (前10行):")
for line in diff[:10]:
    print(f"    {line}")

print(f"\n{'='*60}")
print(f"  ✅ CLI 工具运行正常!")
print(f"  已注册 checker: {sorted(_CUSTOM_CHECKERS.keys())}")
print(f"  Web 版: 需要 MySQL 可用后访问 /new/tools/test_checker/")
print("=" * 60)