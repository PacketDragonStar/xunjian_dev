"""变更报告 + 待删除清单。

每次 sync_netbox 运行后生成 DiffReport，终端输出 + 可选 JSON 落盘。
"""

import json
from datetime import datetime
from typing import Dict, List


class DiffReport:
    """同步变更追踪器。"""

    def __init__(self, site: str = ''):
        self.site = site
        self.timestamp = datetime.now()
        # (endpoint, name) → action
        self.created: Dict[str, List[str]] = {}
        self.updated: Dict[str, List[str]] = {}
        self.skipped: Dict[str, List[str]] = {}
        self.to_delete: Dict[str, List[str]] = {}

    def record_created(self, endpoint: str, name: str):
        self.created.setdefault(endpoint, []).append(name)

    def record_updated(self, endpoint: str, name: str):
        self.updated.setdefault(endpoint, []).append(name)

    def record_skipped(self, endpoint: str, name: str, reason: str = ''):
        label = f'{name} ({reason})' if reason else name
        self.skipped.setdefault(endpoint, []).append(label)

    def add_to_delete(self, endpoint: str, name: str):
        self.to_delete.setdefault(endpoint, []).append(name)

    # ── 终端输出 ──

    def print(self):
        print(f'\n{"="*60}')
        print(f'  NetBox 同步报告 — {self.site or "全部站点"}')
        print(f'  时间：{self.timestamp.strftime("%Y-%m-%d %H:%M:%S")}')
        print(f'{"="*60}')
        self._print_section('新增', self.created)
        self._print_section('更新', self.updated)
        self._print_section('跳过', self.skipped)
        self._print_section('⚠️  待删除（需 --delete 执行）', self.to_delete)

        total = sum(len(v) for v in self.created.values()) \
                + sum(len(v) for v in self.updated.values())
        dels = sum(len(v) for v in self.to_delete.values())
        print(f'\n  总计：新增/更新 {total} 项，待删除 {dels} 项')
        if dels > 0:
            print(f'  执行删除：python manage.py sync_netbox --push --delete')
        print()

    def _print_section(self, title: str, data: Dict[str, List[str]]):
        if not data:
            return
        print(f'\n  ── {title} ──')
        for endpoint, names in sorted(data.items()):
            print(f'    [{endpoint}]')
            for n in names[:50]:  # 最多显示 50 条
                print(f'      · {n}')
            if len(names) > 50:
                print(f'      ... 共 {len(names)} 条')

    # ── JSON 导出 ──

    def to_dict(self) -> dict:
        return {
            'site': self.site,
            'timestamp': self.timestamp.isoformat(),
            'created': {k: sorted(v) for k, v in self.created.items()},
            'updated': {k: sorted(v) for k, v in self.updated.items()},
            'skipped': {k: sorted(v) for k, v in self.skipped.items()},
            'to_delete': {k: sorted(v) for k, v in self.to_delete.items()},
        }

    def save(self, path: str):
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
