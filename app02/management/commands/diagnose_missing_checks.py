# -*- coding: utf-8 -*-
"""巡检缺口诊断：对比某次巡检「应执行」与「实际回显」，列出未巡检到的设备-命令对。

用法：
    python manage.py diagnose_missing_checks            # 诊断最近一次巡检
    python manage.py diagnose_missing_checks --time "2026-07-24 10:11:33"
    python manage.py diagnose_missing_checks --time "2026-07-24 10:11:33" --verbose

说明：
    「应执行」按设备当前分组配置（enabled + 自适应裁剪 disabled_commands）推算，
    若巡检后改过配置，结果含少量误差，但能准确反映「哪些命令本次没有回显行」。
"""
import io
import sys

from django.core.management.base import BaseCommand
from django.db.models import Count

from app02.models import (
    CheckResult, XunjianRecord, NewDevice, InspectionGap
)


class Command(BaseCommand):
    help = '诊断某次巡检中未回显/未巡检到的设备与命令'

    def add_arguments(self, parser):
        parser.add_argument('--time', default=None, help='巡检时间(YYYY-MM-DD HH:MM:SS)，缺省取最近一次')
        parser.add_argument('--verbose', action='store_true', help='打印每条缺失命令')

    def _items_for_device(self, device):
        if not device.group:
            return []
        qs = device.group.check_items.filter(enabled=True)
        disabled = (device.extra or {}).get('disabled_commands') or []
        if disabled:
            qs = qs.exclude(command__in=disabled)
        return list(qs.values_list('command', flat=True))

    def handle(self, *args, **opts):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

        time = opts['time']
        if not time:
            rec = XunjianRecord.objects.order_by('-time').first()
            if not rec:
                self.stdout.write('无任何巡检记录。')
                return
            time = rec.time

        rec = XunjianRecord.objects.filter(time=time).first()
        if not rec:
            self.stdout.write(f'未找到该次巡检记录: {time}')
            return

        self.stdout.write('=' * 64)
        self.stdout.write(f'巡检时间 : {time}')
        self.stdout.write(f'操作人   : {rec.operator}')
        self.stdout.write(f'结果     : {rec.result}')
        self.stdout.write(f'设备数   : {rec.device_count}  (正常 {rec.ok_devices} / 异常 {rec.anomaly_devices} / 失败 {rec.failed_devices})')
        self.stdout.write(f'应执行   : {rec.expected_count}')
        self.stdout.write(f'回显条数 : {rec.check_count}  (缺 {rec.missing_count})')
        self.stdout.write('=' * 64)

        # 该次参与者（有任意回显行的设备）
        participants = list(
            CheckResult.objects.filter(time=time).values_list('device', flat=True).distinct()
        )
        # 已有埋点缺口（若本次巡检已跑过新审计逻辑）
        gap_rows = list(
            InspectionGap.objects.filter(time=time).values_list('device', 'command')
        )
        if gap_rows:
            self.stdout.write(f'\n[InspectionGap 埋点记录] 共 {len(gap_rows)} 项缺口：')
            by_dev = {}
            for dv, cmd in gap_rows:
                by_dev.setdefault(dv, []).append(cmd)
            for dv, cmds in by_dev.items():
                self.stdout.write(f'  {dv}: {len(cmds)} 项')
                if opts['verbose']:
                    for c in cmds:
                        self.stdout.write(f'      - {c}')

        # 用当前配置重新推算缺口（兼容旧巡检：彼时尚未有 InspectionGap）
        self.stdout.write('\n[按当前配置推算缺口]')
        total_cfg = total_act = 0
        any_gap = False
        for d in NewDevice.objects.filter(enabled=True).select_related('group'):
            if d.name not in participants:
                continue
            cfg = self._items_for_device(d)
            if not cfg:
                continue
            act = set(CheckResult.objects.filter(time=time, device=d.name)
                      .values_list('command', flat=True))
            missing = [c for c in cfg if c not in act]
            if missing:
                any_gap = True
                total_cfg += len(cfg)
                total_act += len(act)
                self.stdout.write(f'  {d.name}: 配置 {len(cfg)} / 回显 {len(act)} / 缺 {len(missing)}')
                if opts['verbose']:
                    for c in missing:
                        self.stdout.write(f'      - {c}')
        if not any_gap:
            self.stdout.write('  （无缺口，所有配置命令均有回显行）')
        else:
            self.stdout.write(f'\n推算缺口合计: {total_cfg - total_act} 项')
        self.stdout.write('\n提示：若巡检后改过配置，推算值含少量误差；以 InspectionGap 埋点记录为准。')
