"""backfill_parse_results —— 阶段二·历史数据回填。

把历史 CheckResult.raw 按「单一真源」解析为 DeviceParseResult，
使采集时一次解析落库对存量巡检结果全覆盖（设计文档阶段二/四）。

幂等：以 (device, command, collected_at) 为唯一键 update_or_create。
未配置解析器的命令、空输出、解析失败均跳过（不报错）。
"""
import logging

from django.core.management.base import BaseCommand

from app02.models import CheckResult, DeviceParseResult
from app02.parsers import (
    parse_device_command, is_parseable, SCHEMA_VERSION,
)

logger = logging.getLogger('xunjian')


class Command(BaseCommand):
    help = '将历史 CheckResult 补解析为 DeviceParseResult（阶段二·一次解析落库回填，幂等）'

    def add_arguments(self, parser):
        parser.add_argument('--device', default='', help='仅回填指定设备名')
        parser.add_argument('--command', default='', help='仅回填指定命令(如 "display version")')
        parser.add_argument('--batch', type=int, default=500, help='日志进度刷新间隔')

    def handle(self, *args, **options):
        device = options.get('device', '') or ''
        command = options.get('command', '') or ''
        batch = int(options.get('batch', 500) or 500)

        qs = CheckResult.objects.all()
        if device:
            qs = qs.filter(device=device)
        if command:
            qs = qs.filter(command=command)

        distinct = qs.values_list('device', 'command', 'time').distinct()
        total = distinct.count()
        self.stdout.write(f'待回填组合(device,command,time): {total}')

        done = skipped = 0
        for dev, cmd, t in distinct.iterator():
            if not is_parseable(cmd):
                skipped += 1
                continue
            cr = (qs.filter(device=dev, command=cmd, time=t)
                  .order_by('-created_at', '-id').first())
            if not cr or not cr.result:
                skipped += 1
                continue
            structured = parse_device_command(cmd, cr.result)
            if structured is None:
                skipped += 1
                continue
            try:
                DeviceParseResult.objects.update_or_create(
                    device=dev, command=cmd, collected_at=t,
                    defaults=dict(schema_version=SCHEMA_VERSION, data=structured),
                )
                done += 1
            except Exception as e:
                logger.warning(f'backfill 落库失败 {dev}/{cmd}/{t}: {e}')
                skipped += 1
            if done and done % batch == 0:
                self.stdout.write(f'  已回填 {done}/{total} ...')

        self.stdout.write(self.style.SUCCESS(
            f'回填完成: 成功 {done}, 跳过 {skipped} (不可解析/空/失败)'))
