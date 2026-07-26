"""rebuild_topology —— 一键刷新 CMDB 台账 + network-seek 拓扑图。

等价于依次执行：
  1. sync_cmdb                      （CheckResult → CMDB 表）
  2. export_networkseek_fixtures   （采集 → 单设备结构化 JSON fixture，阶段三默认）
  3. [可选 --push] network-seek full_reset_and_import_comware_json
                                  （结构化 JSON → Neo4j 图，调 scripts/reimport_comware.py --json）
                                  （--legacy-fixture 时退回旧版 .txt 导入）

设计要点：
  - 全程确定性正则解析，没有 AI / LLM 调用；重跑 = 重跑解析器（秒级、零费用、可重复）。
  - 图采用全量重建（clear_all 后重灌），因为图是"设备当下真实状态快照"，
    全量比增量 diff 简单且不会脏；百台规模完全够用。
  - 阶段三起，export 默认产结构化 JSON，network-seek 薄导入直接消费，不再 re-parse raw；
    两仓通过 §4 versioned JSON 契约 + 共享解析代码双重对齐（见设计文档）。
  - 新增巡检命令如需进图，只需在解析层加性挂载（见使用手册），不影响现有链路。

用法:
    python manage.py rebuild_topology                 # 刷新全部站点 CMDB + JSON fixture
    python manage.py rebuild_topology --site 知识城    # 仅某站点
    python manage.py rebuild_topology --push           # 顺带刷新 Neo4j 图（结构化 JSON，需配置 settings）
"""
import os
import sys
import subprocess

from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.management import call_command


class Command(BaseCommand):
    help = '一键刷新 CMDB 台账与拓扑图（sync_cmdb + export + 可选 push 到 Neo4j）'

    def add_arguments(self, parser):
        parser.add_argument('--site', default='all',
                            help='站点过滤：知识城 / 化龙 / all（默认 all）')
        parser.add_argument('--push', action='store_true',
                            help='同步后调用 network-seek 刷新 Neo4j 拓扑图')
        parser.add_argument('--network-seek-dir', default=None,
                            help='network-seek 项目根目录（覆盖 settings.NETWORK_SEEK_DIR）')
        parser.add_argument('--legacy-fixture', action='store_true',
                            help='push 时改用旧版 .txt fixture 导入（需先 export --raw），'
                                 '默认用结构化 JSON 薄导入（阶段三）')

    def handle(self, *args, **options):
        site = options['site']
        # sync_cmdb / export 的 --site='' 表示全部；'all' 需转换成 ''
        sub_site = '' if site in ('all', '') else site

        # 1) CMDB 台账
        self.stdout.write(self.style.WARNING('[1/2] 刷新 CMDB 台账 (sync_cmdb)...'))
        call_command('sync_cmdb', site=sub_site)

        # 2) 导出 fixture
        self.stdout.write(self.style.WARNING('[2/2] 导出 network-seek fixture...'))
        call_command('export_networkseek_fixtures', site=sub_site)

        # 3) 可选：推送到 Neo4j
        if options['push']:
            ns_dir = options['network_seek_dir'] or getattr(settings, 'NETWORK_SEEK_DIR', None)
            if not ns_dir or not os.path.isdir(ns_dir):
                self.stderr.write(self.style.ERROR(
                    '未配置 network-seek 目录，跳过 push。\n'
                    '请在 settings 设置 NETWORK_SEEK_DIR，或命令加 --network-seek-dir <路径>。'))
                return
            fixtures_root = os.path.join(settings.BASE_DIR, 'cmdb_fixtures')
            bolt = getattr(settings, 'NEO4J_BOLT_URI', 'bolt://localhost:7687')
            user = getattr(settings, 'NEO4J_USER', 'neo4j')
            pwd = getattr(settings, 'NEO4J_PASSWORD', 'networkseek2024')
            ns_python = getattr(settings, 'NETWORK_SEEK_PYTHON', sys.executable)
            script = os.path.join(ns_dir, 'scripts', 'reimport_comware.py')

            for site_name in self._site_dirs(fixtures_root, site):
                fdir = os.path.join(fixtures_root, site_name)
                if not os.path.isdir(fdir):
                    self.stderr.write(self.style.WARNING(f'[push] 跳过空目录: {site_name}'))
                    continue
                self.stdout.write(self.style.WARNING(
                    f'[push] 刷新拓扑图：{site_name} -> {bolt}'))
                env = dict(os.environ)
                env['PYTHONPATH'] = ns_dir + os.pathsep + env.get('PYTHONPATH', '')
                cmd = [ns_python, script, '--dir', fdir,
                       '--bolt', bolt, '--user', user, '--pwd', pwd]
                if not options.get('legacy_fixture'):
                    cmd.append('--json')  # 阶段三默认：结构化 JSON 薄导入
                try:
                    subprocess.run(cmd, cwd=ns_dir, env=env, check=True)
                except subprocess.CalledProcessError as e:
                    self.stderr.write(self.style.ERROR(f'[push] {site_name} 失败：{e}'))
            self.stdout.write(self.style.SUCCESS('\n拓扑图刷新完成。'))
        else:
            self.stdout.write(self.style.SUCCESS(
                '\n完成（未推送拓扑图）。如需刷新 Neo4j，请加 --push。'))

    @staticmethod
    def _site_dirs(fixtures_root, site):
        if site not in ('all', ''):
            return [site]
        if not os.path.isdir(fixtures_root):
            return []
        return [d for d in os.listdir(fixtures_root)
                if os.path.isdir(os.path.join(fixtures_root, d))]
