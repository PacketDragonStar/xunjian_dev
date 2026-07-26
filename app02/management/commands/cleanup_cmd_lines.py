"""cleanup_cmd_lines —— 一次性清理旧 CheckResult 首行的命令行回声。

背景：早期采集用 strip_command=False，每条回显首行都是被执行的命令本身
（如 "display cpu-usage"）。现改为 strip_command=True 后新数据已干净，
但历史数据仍残留命令行。本命令精确剥离「首行 == 命令」的回声行，幂等可重跑。

仅当首行去除首尾空白后【等于】命令时才剥离，避免误伤正常输出。
"""
from django.core.management.base import BaseCommand

from app02.models import CheckResult


class Command(BaseCommand):
    help = '剥离旧 CheckResult 首行的命令行回声（仅首行==命令时），幂等可重跑'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='只统计将受影响行数，不实际修改')

    def handle(self, *args, **options):
        dry = options.get('dry_run', False)
        affected = 0
        for r in CheckResult.objects.exclude(result='').exclude(command=''):
            text = r.result or ''
            lines = text.split('\n')
            if not lines:
                continue
            first = lines[0].strip()
            cmd = (r.command or '').strip()
            if not cmd:
                continue
            # 精确匹配：首行即为被执行的命令（netmiko strip_command=False 遗留）
            if first == cmd:
                new_text = '\n'.join(lines[1:]).strip('\n')
                affected += 1
                if not dry:
                    r.result = new_text
                    r.save(update_fields=['result'])
        if dry:
            self.stdout.write(self.style.WARNING(
                f'[dry-run] 将清理 {affected} 条历史回显的首行命令'))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'已清理 {affected} 条历史回显的首行命令'))
