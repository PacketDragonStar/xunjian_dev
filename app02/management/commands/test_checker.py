# -*- coding: utf-8 -*-
"""
test_checker —— 巡检规则微调工具（CLI 版）

用法：
  # 从文件读取 raw log，指定 checker 和 config
  python manage.py test_checker --input fw001_display_fan.txt --checker custom --checker-config '{"func": "check_fan"}'

  # 直接粘贴 raw log
  python manage.py test_checker --stdin --checker threshold --checker-config '{"warning": 80, "operator": "<"}' --parser regex --parser-config '{"pattern": "([\\d\\.]+)%", "group": 1, "cast": "float"}'

  # 列出所有可用的 parser / checker
  python manage.py test_checker --list

  # 对比两份文件（基线 vs 当前）
  python manage.py test_checker --input fw001_current.txt --baseline fw001_baseline.txt --checker baseline
"""
import json
import sys
import io

from django.core.management.base import BaseCommand

from app02.engine.pipeline import (
    PARSERS, CHECKERS, _CUSTOM_CHECKERS,
    parse_raw, parse_regex, parse_strip_ts, parse_textfsm,
    check_baseline, check_threshold, check_count, check_contains, check_custom,
)

# 触发自定义检查器注册
try:
    import app02.custom_checks  # noqa
except ImportError:
    pass


def _safe_json(s: str) -> dict:
    """安全解析 JSON，失败返回空字典"""
    if not s or not s.strip():
        return {}
    try:
        return json.loads(s)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON 解析失败: {e}")


class Command(BaseCommand):
    help = '巡检规则微调工具：输入原始命令输出 + checker 配置，立即看到检查结果'

    def add_arguments(self, parser):
        parser.add_argument('--input', default=None, help='原始命令输出文件路径')
        parser.add_argument('--baseline', default=None, help='基线输出文件路径（用于 baseline checker）')
        parser.add_argument('--stdin', action='store_true', default=False,
                            help='从标准输入读取 raw log（管道输入）')
        parser.add_argument('--parser', default='raw',
                            choices=list(PARSERS.keys()),
                            help=f'解析器类型: {", ".join(PARSERS.keys())}')
        parser.add_argument('--parser-config', default='{}', help='解析器配置 JSON')
        parser.add_argument('--checker', default='baseline',
                            choices=list(CHECKERS.keys()),
                            help=f'检查器类型: {", ".join(CHECKERS.keys())}')
        parser.add_argument('--checker-config', default='{}', help='检查器配置 JSON')
        parser.add_argument('--list', action='store_true', default=False,
                            help='列出所有可用的 parser/checker/custom checker')

    def handle(self, *args, **options):
        if options['list']:
            self._list_all()
            return

        # 读取输入
        raw_text = self._read_input(options)
        if not raw_text:
            self.stderr.write(self.style.ERROR('错误: 未提供原始输出。请用 --input/--stdin 指定'))
            sys.exit(1)

        baseline_text = None
        if options['baseline']:
            with open(options['baseline'], encoding='utf-8') as f:
                baseline_text = f.read()

        # 解析配置
        parser_name = options['parser']
        checker_name = options['checker']
        try:
            p_conf = _safe_json(options['parser_config'])
            c_conf = _safe_json(options['checker_config'])
        except ValueError as e:
            self.stderr.write(self.style.ERROR(str(e)))
            sys.exit(1)

        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write(self.style.SUCCESS(f'  Checker 微调测试'))
        self.stdout.write(self.style.SUCCESS(f'  Parser : {parser_name}  config={json.dumps(p_conf, ensure_ascii=False)}'))
        self.stdout.write(self.style.SUCCESS(f'  Checker: {checker_name}  config={json.dumps(c_conf, ensure_ascii=False)}'))
        self.stdout.write(self.style.SUCCESS('=' * 60))

        # ── Step 1: 解析 ──
        parser_func = PARSERS.get(parser_name, parse_raw)
        try:
            parsed = parser_func(raw_text, p_conf)
        except Exception as e:
            self.stderr.write(self.style.ERROR(f'❌ 解析失败: {e}'))
            sys.exit(1)

        if parsed is None:
            self.stderr.write(self.style.WARNING('⚠️  解析结果为 None（正则未匹配），将记为异常'))
            self.stdout.write(f'\n  原始输出（前500字符）:\n{raw_text[:500]}')
            sys.exit(0)

        self.stdout.write(f'\n  📥 解析结果（类型: {type(parsed).__name__}）:')
        self.stdout.write(f'  {str(parsed)[:200]}{"..." if len(str(parsed)) > 200 else ""}')

        # ── Step 2: 基线解析 ──
        baseline_parsed = None
        if baseline_text:
            try:
                baseline_parsed = parser_func(baseline_text, p_conf)
                self.stdout.write(f'\n  📥 基线解析结果:')
                self.stdout.write(f'  {str(baseline_parsed)[:200]}{"..." if len(str(baseline_parsed)) > 200 else ""}')
            except Exception as e:
                self.stdout.write(self.style.WARNING(f'  ⚠️ 基线解析失败: {e}'))

        # ── Step 3: 检查 ──
        checker_func = CHECKERS.get(checker_name, check_baseline)
        try:
            is_ok, notes = checker_func(parsed, baseline_parsed, c_conf, {})
        except Exception as e:
            self.stderr.write(self.style.ERROR(f'❌ 检查器执行异常: {e}'))
            import traceback
            traceback.print_exc()
            sys.exit(1)

        # ── 输出结果 ──
        self.stdout.write(self.style.SUCCESS('\n' + '=' * 60))
        if is_ok:
            self.stdout.write(self.style.SUCCESS('  ✅ 结果: 正常'))
        else:
            self.stderr.write(self.style.ERROR(f'  ❌ 结果: 异常'))
            if notes:
                self.stderr.write(f'    说明: {notes}')
        self.stdout.write(self.style.SUCCESS('=' * 60))

        # ── 额外：输出 diff 摘要（针对 baseline checker） ──
        if checker_name == 'baseline' and baseline_text and not is_ok:
            from app02.engine.reporter import extract_diff_summary
            curr_sum, base_sum, diff_lines = extract_diff_summary(raw_text, baseline_text)
            if diff_lines:
                self.stdout.write('\n  📊 差异摘要（前20行）:')
                for line in diff_lines[:20]:
                    self.stdout.write(f'  {line}')

    def _read_input(self, options) -> str:
        if options['stdin']:
            return sys.stdin.read()
        if options['input']:
            with open(options['input'], encoding='utf-8') as f:
                return f.read()
        return ''

    def _list_all(self):
        self.stdout.write(self.style.SUCCESS('\n可用解析器 (PARSERS):'))
        for name, func in PARSERS.items():
            self.stdout.write(f'  {name:12s} -> {func.__doc__ or "(无文档)"}')

        self.stdout.write(self.style.SUCCESS('\n可用检查器 (CHECKERS):'))
        for name, func in CHECKERS.items():
            self.stdout.write(f'  {name:12s} -> {func.__doc__ or "(无文档)"}')

        self.stdout.write(self.style.SUCCESS('\n已注册自定义检查器 (CUSTOM CHECKERS):'))
        if _CUSTOM_CHECKERS:
            for name in sorted(_CUSTOM_CHECKERS.keys()):
                self.stdout.write(f'  {name}')
        else:
            self.stdout.write('  (无)')