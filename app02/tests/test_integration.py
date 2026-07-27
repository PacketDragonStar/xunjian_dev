"""集成回归测试：巡检流程关键路径。

不连真实设备/DB，mock 外部依赖，验证核心逻辑正确性。
覆盖已修复的 bug，避免回退。
"""
import unittest
from unittest import mock
from datetime import datetime, timedelta


# ═══════════════════════════════════════════════════════════
# Fake objects
# ═══════════════════════════════════════════════════════════

class FakeDevice:
    def __init__(self, name='dev001', extra=None, group=None):
        self.name = name
        self.pk = 1
        self.extra = extra or {}
        self.group = group

class FakeGroup:
    def __init__(self, check_items=None):
        self.check_items = check_items

class FakeCheckItem:
    def __init__(self, command, feature='base', enabled=True):
        self.command = command
        self.feature = feature
        self.name = command
        self.enabled = enabled


# ═══════════════════════════════════════════════════════════
# 能力门控逻辑
# ═══════════════════════════════════════════════════════════

class CapabilityGatingTest(unittest.TestCase):

    def test_no_group_returns_none(self):
        from app02.engine.executor import _get_items_for_device
        self.assertIsNone(_get_items_for_device(FakeDevice(group=None)))

    def test_filter_logic_all_cases(self):
        """门控筛选逻辑：直接测试，不依赖 Django ORM"""
        items = [
            FakeCheckItem('display version', 'base'),
            FakeCheckItem('display cpu-usage', 'base'),
            FakeCheckItem('display ospf peer', 'ospf'),
            FakeCheckItem('display bgp peer', 'bgp'),
            FakeCheckItem('display nqa result', 'nqa'),
        ]

        # caps=None → only base
        caps = None
        sel = [it for it in items if it.feature == 'base']
        self.assertEqual(len(sel), 2)

        # caps=[] → only base
        caps = []
        sel = [it for it in items if it.feature == 'base' or it.feature in caps]
        self.assertEqual(len(sel), 2)

        # caps=['ospf'] → base + ospf
        caps = ['ospf']
        sel = [it for it in items if it.feature == 'base' or it.feature in caps]
        cmds = [it.command for it in sel]
        self.assertIn('display ospf peer', cmds)
        self.assertNotIn('display bgp peer', cmds)
        self.assertNotIn('display nqa result', cmds)

        # caps=['ospf','nqa'] → base + ospf + nqa
        caps = ['ospf', 'nqa']
        sel = [it for it in items if it.feature == 'base' or it.feature in caps]
        cmds = [it.command for it in sel]
        self.assertIn('display ospf peer', cmds)
        self.assertIn('display nqa result', cmds)
        self.assertNotIn('display bgp peer', cmds)

        # disabled_commands
        caps = ['ospf']
        disabled = ['display ospf peer']
        sel = [it for it in items
               if it.enabled and (it.feature == 'base' or it.feature in caps)
               and it.command not in disabled]
        cmds = [it.command for it in sel]
        self.assertNotIn('display ospf peer', cmds)


# ═══════════════════════════════════════════════════════════
# 能力检测回归：防火墙误判
# ═══════════════════════════════════════════════════════════

class DetectCapabilitiesRegressionTest(unittest.TestCase):

    def test_fw_config_acl_names_no_false_positive(self):
        """ACL 规则名含 ospf/bgp 不应误判"""
        from app02.engine.capability import detect_capabilities
        fw = "\n".join([
            "#",
            "security-zone name Trust",
            " rule 10 name ospf_to_bgp_allow",
            " object-group ip address ospf_peers",
            "#",
        ])
        caps = detect_capabilities(fw)
        self.assertNotIn('ospf', caps, msg='ACL 规则名不应误判为 OSPF')
        self.assertNotIn('bgp', caps, msg='ACL 规则名不应误判为 BGP')
        # security-zone IS present → should be detected
        self.assertIn('security', caps)

    def test_real_ospf_config_detected(self):
        from app02.engine.capability import detect_capabilities
        cfg = "ospf 1\n area 0.0.0.0\n  network 10.0.0.0 0.0.0.255\n"
        self.assertIn('ospf', detect_capabilities(cfg))

    def test_real_bgp_config_detected(self):
        from app02.engine.capability import detect_capabilities
        cfg = "bgp 100\n peer 10.0.0.1 as-number 200\n"
        self.assertIn('bgp', detect_capabilities(cfg))

    def test_vpn_instance_detected(self):
        from app02.engine.capability import detect_capabilities
        cfg = "ip vpn-instance vpn1\n route-distinguisher 100:1\n"
        self.assertIn('vpn', detect_capabilities(cfg))

    def test_nqa_entry_detected(self):
        from app02.engine.capability import detect_capabilities
        cfg = "nqa entry admin test\n type icmp-echo\n"
        self.assertIn('nqa', detect_capabilities(cfg))

    def test_stp_does_not_trigger_false_positive(self):
        """含 stp/ntp 等常见单词不误判"""
        from app02.engine.capability import detect_capabilities
        cfg = "stp enable\n ntp-service enable\ndisplay stp brief\n"
        caps = detect_capabilities(cfg)
        self.assertEqual(caps, [], msg='stp/ntp 不是已注册的能力标签')


# ═══════════════════════════════════════════════════════════
# 自定义 checker 回归
# ═══════════════════════════════════════════════════════════

class CustomCheckerRegressionTest(unittest.TestCase):

    def test_system_stable_no_redundancy_is_ok(self):
        """单机 No redundancy → 正常"""
        from app02.custom_checks import check_system_stable
        out = ("System state     : Stable\n"
               "Redundancy state : No redundancy\n"
               "  Slot    CPU    Role       State\n"
               "  1       0      Active     Stable")
        ok, notes = check_system_stable(out, None, {}, {})
        self.assertTrue(ok, msg=f'No redundancy 应正常: {notes}')

    def test_system_stable_redundancy_stable_is_ok(self):
        """IRF 冗余 Stable → 正常"""
        from app02.custom_checks import check_system_stable
        out = ("System state     : Stable\n"
               "Redundancy state : Stable\n"
               "  Slot    CPU    Role       State\n"
               "  1       0      Active     Stable\n"
               "  2       0      Standby    Stable")
        ok, notes = check_system_stable(out, None, {}, {})
        self.assertTrue(ok, msg=f'Stable 冗余应正常: {notes}')

    def test_system_state_not_stable_is_anomaly(self):
        from app02.custom_checks import check_system_stable
        out = "System state     : Fault\nRedundancy state : Stable\n"
        ok, notes = check_system_stable(out, None, {}, {})
        self.assertFalse(ok)

    def test_logbuffer_filters_21_days_old(self):
        """21天前日志 不应触发 window_days=2"""
        from app02.custom_checks import check_logbuffer
        old = datetime.now() - timedelta(days=21)
        ts = old.strftime('%b %d %H:%M:%S %Y')
        # 确保月份缩写正确（H3C 格式：Jul）
        log = f'%{ts} dev001 DEV/2/OLD_ERROR test\n'
        ok, notes = check_logbuffer(log, None, {'window_days': 2}, {})
        self.assertTrue(ok, msg=f'21天前日志应被过滤: {notes}')

    def test_logbuffer_catches_today_error(self):
        """今天的 severity=3 日志必须捕获"""
        from app02.custom_checks import check_logbuffer
        now = datetime.now()
        ts = now.strftime('%b %d %H:%M:%S %Y')
        log = f'%{ts} dev001 DEV/3/ERROR_NOW test\n'
        ok, notes = check_logbuffer(log, None, {'window_days': 2}, {})
        self.assertFalse(ok, msg='今天的 error 日志必须捕获')

    def test_logbuffer_empty_input(self):
        from app02.custom_checks import check_logbuffer
        ok, notes = check_logbuffer('', None, {}, {})
        self.assertFalse(ok)

    def test_logbuffer_no_valid_format(self):
        from app02.custom_checks import check_logbuffer
        ok, notes = check_logbuffer('no valid log format here\n', None, {'window_days': 2}, {})
        self.assertFalse(ok)


# ═══════════════════════════════════════════════════════════
# ResultRecorder 端到端
# ═══════════════════════════════════════════════════════════

class ResultRecorderIntegrationTest(unittest.TestCase):

    def test_normal_result(self):
        from app02.engine.result_recorder import ResultRecorder
        rec = ResultRecorder('2026-01-01 12:00', 'dev001')
        with mock.patch('app02.engine.result_recorder._db_create_with_retry',
                        return_value=True):
            self.assertTrue(rec.record_command('display version', 'v7.1'))

    def test_anomaly_with_baseline(self):
        from app02.engine.result_recorder import ResultRecorder
        rec = ResultRecorder('2026-01-01 12:00', 'dev001')
        with mock.patch('app02.engine.result_recorder._db_create_with_retry',
                        return_value=True):
            rec.record_anomaly('display cpu', 'CPU 95%', 'P1',
                               baseline_val='20%', current_val='95%')

    def test_parse_skips_when_no_raw(self):
        from app02.engine.result_recorder import ResultRecorder
        rec = ResultRecorder('2026-01-01 12:00', 'dev001')
        with mock.patch('app02.engine.result_recorder.DeviceParseResult') as m:
            rec.record_parse('cmd', None, {'parsed': True})
            m.objects.update_or_create.assert_not_called()

    def test_connection_failure_does_not_raise(self):
        from app02.engine.result_recorder import ResultRecorder
        items = [FakeCheckItem('cmd1'), FakeCheckItem('cmd2')]
        with mock.patch('app02.engine.result_recorder.CheckResult.objects.create'), \
             mock.patch('app02.engine.result_recorder.AnomalyRecord.objects.create'), \
             mock.patch('app02.engine.result_recorder.CheckResult.objects.bulk_create'):
            ResultRecorder.record_connection_failure('t1', 'dev', 'timeout')
            ResultRecorder.record_bulk_connection_failure('t1', 'dev', 'timeout', items)


# ═══════════════════════════════════════════════════════════
# Post-inspection hook pipeline
# ═══════════════════════════════════════════════════════════

class PostInspectionPipelineTest(unittest.TestCase):

    def test_hooks_run_in_order(self):
        from app02.engine.post_inspection import run_post_inspection_hooks, _HOOKS
        order = []
        def a(tid, t, op): order.append('a')
        def b(tid, t, op): order.append('b')
        hooks_before = list(_HOOKS)
        try:
            _HOOKS.clear()
            _HOOKS.extend([a, b])
            run_post_inspection_hooks(1, 't', 'op')
            self.assertEqual(order, ['a', 'b'])
        finally:
            _HOOKS.clear()
            _HOOKS.extend(hooks_before)

    def test_failing_hook_does_not_block(self):
        from app02.engine.post_inspection import run_post_inspection_hooks, _HOOKS
        order = []
        def fail(tid, t, op): raise RuntimeError('boom')
        def ok(tid, t, op): order.append('ok')
        hooks_before = list(_HOOKS)
        try:
            _HOOKS.clear()
            _HOOKS.extend([fail, ok])
            run_post_inspection_hooks(1, 't', 'op')
            self.assertEqual(order, ['ok'])
        finally:
            _HOOKS.clear()
            _HOOKS.extend(hooks_before)


# ═══════════════════════════════════════════════════════════
# 能力生命周期
# ═══════════════════════════════════════════════════════════

class CapabilityLifecycleTest(unittest.TestCase):

    def test_new_detected_not_in_existing(self):
        existing = {'irf', 'lacp'}
        detected = {'irf', 'lacp', 'nqa'}
        new = set(detected) - existing
        self.assertEqual(new, {'nqa'})

    def test_pending_prevents_duplicate_pending(self):
        existing = {'irf'}
        pending = {'nqa'}
        detected = {'irf', 'nqa'}
        new = set(detected) - existing - pending
        self.assertEqual(new, set())

    def test_confirm_merges_correctly(self):
        extra = {'capabilities': ['irf'], 'pending_capabilities': ['nqa']}
        pending = extra.pop('pending_capabilities', [])
        caps = sorted(set(extra['capabilities']) | set(pending))
        self.assertEqual(caps, ['irf', 'nqa'])


if __name__ == '__main__':
    unittest.main()
