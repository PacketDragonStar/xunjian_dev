"""capability 模块单测：覆盖 v3 核心解析与门控逻辑（吸收 v2 硬伤）。

无需真实设备/DB：ensure_capabilities 通过 monkeypatch NewDevice 避免写库。
"""
import unittest
from unittest import mock

from app02.engine import capability as cap


CSW_REAL_SAMPLE = """
#
 irf domain 10
 irf member 1 priority 32
 irf member 2 priority 30
 link-aggregation load-sharing mode destination-mac
 interface Bridge-Aggregation 1
#
"""


class FakeDev:
    def __init__(self, extra, name='dev', pk=1):
        self.name = name
        self.pk = pk
        self.extra = extra


class FakeConn:
    def __init__(self, resp='', raise_exc=None):
        self.resp = resp
        self.raise_exc = raise_exc
        self.calls = []

    def send_command(self, cmd, **kw):
        self.calls.append(cmd)
        if self.raise_exc:
            raise self.raise_exc
        return self.resp


class FakeObjects:
    def filter(self, *a, **k):
        return self

    def update(self, *a, **k):
        return 0


class FakeModel:
    objects = FakeObjects()


class DetectCapabilitiesTest(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(cap.detect_capabilities(''), [])
        self.assertEqual(cap.detect_capabilities(None), [])

    def test_csw_real_sample(self):
        # csw003&004 真实回显：含 irf + link-aggregation，无 ospf/bgp/vrrp/m-lag/rbm/security
        self.assertEqual(cap.detect_capabilities(CSW_REAL_SAMPLE), ['irf', 'lacp'])

    def test_ospf_bgp_vrrp(self):
        cfg = "ospf 1\n area 0.0.0.0\nbgp 100\n peer 1.1.1.1\nvrrp vrid 1 virtual-ip 2.2.2.2\n"
        self.assertEqual(cap.detect_capabilities(cfg), ['ospf', 'bgp', 'vrrp'])

    def test_mlag_only(self):
        cfg = "m-lag keepalive ip 10.0.0.1\n"
        self.assertEqual(cap.detect_capabilities(cfg), ['m-lag'])

    def test_security_zone(self):
        cfg = "security-zone name Trust\n zone Trust\n"
        self.assertEqual(cap.detect_capabilities(cfg), ['security'])

    def test_neighbor_does_not_trigger_mlag(self):
        # v2 硬伤回归防护：BGP/OSPF 的 neighbor 绝不能误判为 m-lag
        cfg = "bgp 100\n neighbor 1.1.1.1 remote-as 200\nospf 1\n"
        caps = cap.detect_capabilities(cfg)
        self.assertIn('bgp', caps)
        self.assertIn('ospf', caps)
        self.assertNotIn('m-lag', caps)

    def test_vrid_does_not_trigger_vrrp_alone(self):
        # vrid 不带 vrrp 关键字不应命中（vrid 已弃用）
        cfg = "vrid 5\n"
        self.assertNotIn('vrrp', cap.detect_capabilities(cfg))

    def test_include_keyword_sync(self):
        # 每个 feature 的主 token 都必须出现在 PROBE_COMMAND 中，
        # 否则探针根本采不到该关键字 → 探测恒为空（v2 漂移硬伤的回归防护）。
        primary = {
            'ospf': 'ospf', 'bgp': 'bgp', 'vrrp': 'vrrp', 'irf': 'irf',
            'm-lag': 'm-lag', 'rbm': 'remote-backup-group',
            'security': 'security-zone', 'lacp': 'link-aggregation',
        }
        for feat, token in primary.items():
            self.assertIn(token, cap.PROBE_COMMAND,
                          f'feature {feat} 的主 token "{token}" 不在 PROBE_COMMAND 中')
            self.assertIn(token, cap.INCLUDE_TOKENS)


class EnsureCapabilitiesTest(unittest.TestCase):
    def _now(self):
        import datetime
        return datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')

    def test_fresh_caps_no_probe(self):
        dev = FakeDev({'capabilities': ['irf'], 'capabilities_ts': self._now()})
        conn = FakeConn('anything')
        with mock.patch.object(cap, 'NewDevice', FakeModel):
            res = cap.ensure_capabilities(dev, conn)
        self.assertEqual(res, ['irf'])
        self.assertEqual(conn.calls, [])  # 未过期 → 不发探针

    def test_empty_list_is_fresh_not_none(self):
        # None vs [] 严格区分：[] 表示"已检测确无特性"，视为 fresh，不再探测
        dev = FakeDev({'capabilities': [], 'capabilities_ts': self._now()})
        conn = FakeConn('ospf 1')
        with mock.patch.object(cap, 'NewDevice', FakeModel):
            res = cap.ensure_capabilities(dev, conn)
        self.assertEqual(res, [])
        self.assertEqual(conn.calls, [])

    def test_none_caps_triggers_probe_and_writes(self):
        dev = FakeDev({'capabilities': None})
        conn = FakeConn(CSW_REAL_SAMPLE)
        with mock.patch.object(cap, 'NewDevice', FakeModel):
            res = cap.ensure_capabilities(dev, conn)
        self.assertEqual(res, ['irf', 'lacp'])
        self.assertIn(cap.PROBE_COMMAND, conn.calls)
        # 写回了 extra
        self.assertEqual(dev.extra['capabilities'], ['irf', 'lacp'])
        self.assertIsNotNone(dev.extra.get('capabilities_ts'))

    def test_stale_caps_reprobes(self):
        import datetime
        old = (datetime.datetime.now() - datetime.timedelta(days=30)).strftime('%Y-%m-%dT%H:%M:%S')
        dev = FakeDev({'capabilities': ['ospf'], 'capabilities_ts': old})
        conn = FakeConn('bgp 100')
        with mock.patch.object(cap, 'NewDevice', FakeModel):
            res = cap.ensure_capabilities(dev, conn)
        self.assertEqual(res, ['bgp'])  # 重探得到新结果

    def test_probe_failure_returns_old(self):
        dev = FakeDev({'capabilities': ['irf'], 'capabilities_ts': None})
        conn = FakeConn('', raise_exc=RuntimeError('unreachable'))
        with mock.patch.object(cap, 'NewDevice', FakeModel):
            res = cap.ensure_capabilities(dev, conn)
        # 探测失败 → 返回旧值（保守兜底），不写库
        self.assertEqual(res, ['irf'])
        self.assertEqual(dev.extra.get('capabilities'), ['irf'])

    def test_probe_failure_with_no_old_returns_none(self):
        dev = FakeDev({})
        conn = FakeConn('', raise_exc=RuntimeError('unreachable'))
        with mock.patch.object(cap, 'NewDevice', FakeModel):
            res = cap.ensure_capabilities(dev, conn)
        self.assertIsNone(res)

    def test_force_ignores_fresh(self):
        dev = FakeDev({'capabilities': ['irf'], 'capabilities_ts': self._now()})
        conn = FakeConn('bgp 100')
        with mock.patch.object(cap, 'NewDevice', FakeModel):
            res = cap.ensure_capabilities(dev, conn, force=True)
        self.assertEqual(res, ['bgp'])
        self.assertIn(cap.PROBE_COMMAND, conn.calls)


if __name__ == '__main__':
    unittest.main()
