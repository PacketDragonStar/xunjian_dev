from django.core.management.base import BaseCommand

from app02.engine.maintenance import prune_old_results


class Command(BaseCommand):
    help = '清理超期的 CheckResult / DiscoveryRecord / ComplianceResult（默认保留 90 天）'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=90,
                            help='保留窗口（天），默认 90')

    def handle(self, *args, **options):
        n = prune_old_results(retention_days=options['days'])
        self.stdout.write(self.style.SUCCESS(
            f'已清理 {n} 行（保留窗口={options["days"]}天）'))
