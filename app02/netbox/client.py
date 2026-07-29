"""NetBox REST API 客户端（pynetbox 封装）。

设计：NETBOX_URL 为空时所有操作降级为 no-op，不抛异常。
"""

from django.conf import settings


class NetBoxClient:
    """NetBox API 客户端。

    用法：
        nb = NetBoxClient()
        nb.connect()
        site = nb.get_or_create('dcim.sites', name='化龙', slug='hualong')
    """

    def __init__(self):
        self.api = None
        self._connected = False

    def connect(self):
        if self._connected:
            return True
        url = getattr(settings, 'NETBOX_URL', '')
        token = getattr(settings, 'NETBOX_TOKEN', '')
        if not url or not token:
            self.api = None
            return False
        try:
            import pynetbox
            self.api = pynetbox.api(url, token=token)
            self.api.http_session.verify = False
            # smoke test
            self.api.status()
            self._connected = True
            return True
        except Exception:
            self.api = None
            return False

    @property
    def connected(self):
        return self._connected and self.api is not None

    # ── 通用 CRUD ──

    def get_or_create(self, endpoint: str, defaults=None, **lookup):
        """幂等 get_or_create。

        endpoint: 'dcim.sites' / 'dcim.devices' / 'ipam.vlans' ...
        lookup:  name='xxx' / slug='xxx'
        返回 (obj, created: bool)
        """
        if not self.connected:
            return None, False
        app, model = endpoint.split('.')
        mgr = getattr(self.api, app)
        mgr = getattr(mgr, model)
        try:
            existing = mgr.get(**lookup)
            if existing is not None:
                return existing, False
        except Exception:
            pass
        data = dict(lookup)
        if defaults:
            data.update(defaults)
        try:
            obj = mgr.create(data)
            return obj, True
        except Exception:
            return None, False

    def update_or_create(self, endpoint: str, lookup: dict, data: dict):
        """幂等 update_or_create。

        lookup 找到 → 仅更新 data 中变化的字段（分列比较）。
        lookup 找不到 → create。
        返回 (obj, created: bool, updated: bool)
        """
        if not self.connected:
            return None, False, False
        app, model = endpoint.split('.')
        mgr = getattr(self.api, app)
        mgr = getattr(mgr, model)
        try:
            existing = mgr.get(**lookup)
            if existing is not None:
                changed = False
                for k, v in data.items():
                    cur = getattr(existing, k, None)
                    if cur != v:
                        setattr(existing, k, v)
                        changed = True
                if changed:
                    existing.save()
                return existing, False, changed
        except Exception:
            pass
        create_data = dict(lookup)
        create_data.update(data)
        try:
            obj = mgr.create(create_data)
            return obj, True, False
        except Exception:
            return None, False, False

    def delete_if_exists(self, endpoint: str, **lookup):
        """查找并删除；返回是否实际删除了。"""
        if not self.connected:
            return False
        app, model = endpoint.split('.')
        mgr = getattr(self.api, app)
        mgr = getattr(mgr, model)
        try:
            obj = mgr.get(**lookup)
            if obj is not None:
                obj.delete()
                return True
        except Exception:
            pass
        return False

    def list_all(self, endpoint: str, **filters):
        """列出 endpoint 下所有对象。"""
        if not self.connected:
            return []
        app, model = endpoint.split('.')
        mgr = getattr(self.api, app)
        mgr = getattr(mgr, model)
        try:
            return list(mgr.filter(**filters))
        except Exception:
            return []

    def get(self, endpoint: str, **lookup):
        """单条查询。"""
        if not self.connected:
            return None
        app, model = endpoint.split('.')
        mgr = getattr(self.api, app)
        mgr = getattr(mgr, model)
        try:
            return mgr.get(**lookup)
        except Exception:
            return None
