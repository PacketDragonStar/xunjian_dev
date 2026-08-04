"""sync_checkers —— 将 custom_checks.py 中的 checker 函数同步到 CheckerScript 表。

用法：
    python manage.py sync_checkers              # 同步所有注册的 checker
    python manage.py sync_checkers --name=xxx   # 仅同步指定 checker
    python manage.py sync_checkers --dry-run    # 仅显示差异，不写入

注意：CheckerScript 表中 enabled=True 的记录在运行时优先于文件版。
此命令用于「改了文件版后同步到 DB」的操作。
"""
import importlib
import inspect
import ast
import textwrap

from django.core.management.base import BaseCommand
from app02.models import CheckerScript

# custom_checks.py 中通过 @register_checker 注册的函数列表
from app02.engine.pipeline import _CUSTOM_CHECKERS, register_checker


def extract_source(func):
    """提取函数的完整源码（含装饰器）。"""
    try:
        src = inspect.getsource(func)
        return textwrap.dedent(src)
    except (OSError, TypeError):
        return None


def extract_simple_source(code: str, func_name: str):
    """用 AST 从完整模块源码中提取函数定义。"""
    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == func_name:
                    # 获取函数的源码行
                    lines = code.splitlines()
                    # 包含装饰器
                    start = node.lineno - 1
                    for deco in (node.decorator_list or []):
                        if deco.lineno and deco.lineno < start + 1:
                            start = deco.lineno - 1
                    end = node.end_lineno or (node.lineno + len(node.body))
                    return '\n'.join(lines[start:end])
    except (SyntaxError, Exception):
        pass
    return None


def get_func_name_from_registry(key):
    """从 _CUSTOM_CHECKERS 注册表中获取实际函数名和源码。"""
    try:
        func = _CUSTOM_CHECKERS[key]
        return func.__name__, func
    except KeyError:
        return None, None


class Command(BaseCommand):
    help = '将 custom_checks.py 注册的 checker 同步到 CheckerScript 表'

    def add_arguments(self, parser):
        parser.add_argument('--name', default='', help='仅同步指定 checker 名称')
        parser.add_argument('--dry-run', action='store_true', help='仅显示差异，不写入')

    def handle(self, *args, **options):
        target_name = options.get('name', '').strip()
        dry_run = options.get('dry_run', False)

        updated = 0
        created = 0
        skipped = 0

        for key, func in _CUSTOM_CHECKERS.items():
            if target_name and key != target_name:
                continue

            source = extract_source(func)
            if not source:
                # 尝试从模块文件用 AST 提取
                try:
                    import app02.custom_checks as mod
                    module_source = inspect.getsource(mod)
                    source = extract_simple_source(module_source, func.__name__)
                except Exception:
                    pass

            if not source:
                self.stdout.write(self.style.WARNING(f'  [SKIP] {key}: 无法提取源码'))
                skipped += 1
                continue

            cs = CheckerScript.objects.filter(name=key).first()
            if cs:
                if cs.source.strip() == source.strip():
                    self.stdout.write(f'  [OK] {key}: 已同步 (v{cs.version})')
                    skipped += 1
                    continue

                if not dry_run:
                    cs.source = source
                    cs.note = f'从 custom_checks.py 同步'
                    cs.save()
                    self.stdout.write(self.style.SUCCESS(f'  [UPD] {key} → v{cs.version}'))
                else:
                    self.stdout.write(f'  [DRY] {key}: 有差异（文件版 vs DB v{cs.version}）')
                updated += 1
            else:
                if not dry_run:
                    CheckerScript.objects.create(
                        name=key, source=source, version=1,
                        enabled=True, note='从 custom_checks.py 同步',
                    )
                    self.stdout.write(self.style.SUCCESS(f'  [NEW] {key} → v1'))
                else:
                    self.stdout.write(f'  [DRY] {key}: 新增（DB 中不存在）')
                created += 1

        self.stdout.write(self.style.SUCCESS(
            f'\n同步完成: 新增 {created}, 更新 {updated}, 跳过 {skipped}'
            + (' (--dry-run，未写入)' if dry_run else '')
        ))
