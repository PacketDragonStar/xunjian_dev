"""prune_disabled_commands —— 自适应裁剪：协议未开启/回显失败的命令后续不再巡检。

使用场景（2026-07-23）：
  新增了 display irf / display m-lag summary / display link-aggregation verbose /
  display vrrp / display security-zone / display security-policy ip rule all /
  display rbm / display zone 等命令（用于 network-seek 识别 M-LAG/堆叠/VRRP/防火墙策略）。
  但部分设备并未开启这些协议（如接入交换无 IRF/M-LAG、非防火墙无安全策略），
  首次全量采集时这些命令会回显失败/为空。本命令扫描**最近一次巡检**的结果，
  将「无结果」或「命中错误特征」的命令写入该设备 extra['disabled_commands']，
  后续巡检（executor 已过滤）即跳过它们，不再反复报错。

判定（仅在该设备最近一次巡检至少有 1 条成功结果时才裁剪，避免整台不可达被误删）：
  - 最近一次巡检中该命令无 CheckResult 行（netmiko 报错/不支持，未产生结果）→ 禁用
  - 或结果命中错误特征（% Unrecognized command / not configured / not enabled /
    Information not available / Error: 等）→ 禁用

用法：
  python manage.py prune_disabled_commands                # 默认裁剪高可用/堆叠/安全域命令集
  python manage.py prune_disabled_commands --site 化龙     # 仅某站点
  python manage.py prune_disabled_commands --dry-run      # 只报告不写库
  python manage.py prune_disabled_commands --commands display irf display m-lag summary  # 指定命令
"""
import re
from django.db.models import Max
from django.core.management.base import BaseCommand

from app02.models import NewDevice, CheckResult

# 默认裁剪范围：本次新增的高可用/堆叠/安全域命令（最容易因协议未开启而失败）
DEFAULT_PRUNABLE = [
    'display irf',
    'display m-lag summary',
    'display link-aggregation verbose',
    'display vrrp',
    'display security-zone',
    'display security-policy ip rule all',
    'display rbm',
    'display zone',
]

# 永不可裁剪的通用健康巡检项：这类命令应在所有设备上都尝试采集，
# 一旦被裁剪（写入 disabled_commands），executor 会直接跳过、不生成 CheckResult，
# 设备汇总时按"无异常"显示正常 → 形成沉默的盲区（如 dir flash:/ 存储利用率）。
# 即便用户通过 --commands 显式传入，也强制跳过。
NEVER_PRUNE = {
    'dir flash:/',
}

# 命令回显失败/协议未开启的错误特征
ERROR_PAT = re.compile(
    r'(% ?(Unrecognized command|Wrong parameter|Incomplete command|'
    r'Too many parameters|Invalid)|not configured|not enabled|'
    r'Information not available|Error:|is not supported)',
    re.IGNORECASE,
)


class Command(BaseCommand):
    help = '自适应裁剪：将首次全量采集中回显失败/协议未开启的命令从单设备后续巡检中剔除'

    def add_arguments(self, parser):
        parser.add_argument('--site', default='', help='仅处理指定站点(知识城/化龙)')
        parser.add_argument('--commands', nargs='*', default=None,
                            help='仅裁剪指定命令（默认裁剪 DEFAULT_PRUNABLE 命令集）')
        parser.add_argument('--dry-run', action='store_true',
                            help='只报告将要禁用的命令，不写库')
        parser.add_argument('--restore', action='store_true',
                            help='恢复模式：将 NEVER_PRUNE 中的通用健康项从各设备 '
                                 'disabled_commands 中移除（解救被误裁的 dir flash:/ 等）')

    def handle(self, *args, **opts):
        site = opts.get('site') or ''
        consider = opts.get('commands') or DEFAULT_PRUNABLE
        dry = opts.get('dry_run', False)
        restore = opts.get('restore', False)

        devs = NewDevice.objects.filter(enabled=True)
        if site:
            devs = devs.filter(site=site)

        # 恢复模式：把 NEVER_PRUNE 中的通用健康项从各设备 disabled_commands 移除
        if restore:
            total_restored = 0
            for dev in devs:
                extra = dev.extra or {}
                disabled = set(extra.get('disabled_commands') or [])
                removed = disabled - (disabled - NEVER_PRUNE)  # = disabled ∩ NEVER_PRUNE
                if removed:
                    disabled -= NEVER_PRUNE
                    extra['disabled_commands'] = sorted(disabled)
                    dev.extra = extra
                    if not dry:
                        dev.save(update_fields=['extra'])
                    total_restored += len(removed)
                    self.stdout.write(self.style.SUCCESS(
                        f'  [恢复] {dev.name} <- 移除禁用: {", ".join(sorted(removed))}'))
            verb = '（dry-run，未写库）' if dry else ''
            self.stdout.write(self.style.SUCCESS(
                f'\n恢复完成{verb}：共 {total_restored} 条通用健康项已从设备 disabled_commands 移除，'
                f'后续巡检将重新采集。'))
            return

        total_disabled = 0
        for dev in devs:
            # 该设备最近一次巡检时间（time 为可词典序排序的字符串）
            latest = CheckResult.objects.filter(device=dev.name).aggregate(m=Max('time'))['m']
            if not latest:
                continue
            # 整台不可达保护：最近一次巡检至少要有 1 条非空结果
            ok = CheckResult.objects.filter(
                device=dev.name, time=latest, result__isnull=False,
            ).exclude(result='').count()
            if ok == 0:
                continue

            extra = dev.extra or {}
            disabled = set(extra.get('disabled_commands') or [])
            before = len(disabled)

            for cmd in consider:
                if cmd in NEVER_PRUNE:
                    continue  # 通用健康项永不裁剪，避免沉默正常盲区
                rec = CheckResult.objects.filter(
                    device=dev.name, command=cmd, time=latest,
                ).first()
                failed = False
                if rec is None:
                    failed = True
                elif not rec.result or ERROR_PAT.search(rec.result or ''):
                    failed = True
                if failed and cmd not in disabled:
                    disabled.add(cmd)
                    self.stdout.write(self.style.WARNING(f'  [禁用] {dev.name} <- {cmd}'))

            if len(disabled) > before:
                total_disabled += (len(disabled) - before)
                extra['disabled_commands'] = sorted(disabled)
                dev.extra = extra
                if not dry:
                    dev.save(update_fields=['extra'])

        verb = '（dry-run，未写库）' if dry else ''
        self.stdout.write(self.style.SUCCESS(
            f'\n裁剪完成{verb}：共 {total_disabled} 条 (设备,命令) 被标记为禁用，'
            f'后续巡检将跳过。'))
