"""新模块单元测试：DeviceSession / ItemRunner / ResultRecorder / post_inspection。

遵循 test_capability.py 的 mock 模式：mock 外部依赖（netmiko / Django ORM），
不连真实设备或 DB。
"""
import unittest
from unittest import mock
from dataclasses import dataclass


# ── Fake 对象 ───────────────────────────────────────────────

class FakeDevice:
    def __init__(self, name='dev001', ip='10.0.0.1', device_type='hp_comware',
                 username='admin', password='pass', extra=None,
                 conn_type='ssh', port=0, enable_password='', ssh_key_file='',
                 pk=1):
        self.name = name
        self.ip = ip
        self.device_type = device_type
        self.username = username
        self.password = password
        self.extra = extra or {}
        self.conn_type = conn_type
        self.port = port
        self.enable_password = enable_password
        self.ssh_key_file = ssh_key_file
        self.pk = pk


class FakeConnection:
    def __init__(self):
        self.calls = []
        self.disconnected = False

    def send_command(self, cmd, **kw):
        self.calls.append(('send_command', cmd, kw))
        return 'fake output'

    def disconnect(self):
        self.disconnected = True


# ═══════════════════════════════════════════════════════════
# DeviceSession 测试
# ═══════════════════════════════════════════════════════════

class DeviceSessionTest(unittest.TestCase):

    def test_build_conn_kwargs_hp_comware(self):
        from app02.engine.device_session import _build_conn_kwargs
        dev = FakeDevice()
        kwargs = _build_conn_kwargs(dev)
        self.assertEqual(kwargs['device_type'], 'hp_comware')
        self.assertEqual(kwargs['ip'], '10.0.0.1')
        self.assertEqual(kwargs['username'], 'admin')

    def test_build_conn_kwargs_telnet(self):
        from app02.engine.device_session import _build_conn_kwargs
        dev = FakeDevice(conn_type='telnet')
        kwargs = _build_conn_kwargs(dev)
        self.assertEqual(kwargs['device_type'], 'hp_comware_telnet')

    def test_build_conn_kwargs_with_enable_password(self):
        from app02.engine.device_session import _build_conn_kwargs
        dev = FakeDevice(enable_password='secret')
        kwargs = _build_conn_kwargs(dev)
        self.assertEqual(kwargs['secret'], 'secret')

    def test_connect_creates_connection(self):
        from app02.engine.device_session import DeviceSession
        dev = FakeDevice()
        session = DeviceSession(dev)
        with mock.patch('app02.engine.device_session.ConnectHandler',
                        return_value=FakeConnection()):
            conn = session.connect()
        self.assertIsNotNone(conn)
        self.assertTrue(hasattr(conn, 'send_command'))

    def test_connect_sends_screen_length_disable(self):
        from app02.engine.device_session import DeviceSession
        dev = FakeDevice()
        session = DeviceSession(dev)
        fake_conn = FakeConnection()
        with mock.patch('app02.engine.device_session.ConnectHandler',
                        return_value=fake_conn):
            session.connect()
        cmd_calls = [c for c in fake_conn.calls if c[0] == 'send_command']
        self.assertTrue(
            any('screen-length' in str(c[1]) for c in cmd_calls),
            msg='screen-length disable should be sent after connect'
        )

    def test_disconnect_calls_disconnect(self):
        from app02.engine.device_session import DeviceSession
        conn = FakeConnection()
        DeviceSession.disconnect(conn)
        self.assertTrue(conn.disconnected)

    def test_disconnect_safe_on_none(self):
        from app02.engine.device_session import DeviceSession
        # Should not raise
        DeviceSession.disconnect(None)


# ═══════════════════════════════════════════════════════════
# ItemRunner 测试
# ═══════════════════════════════════════════════════════════

@dataclass
class FakeCheckItem:
    command: str = 'display version'
    name: str = '版本检查'
    parser: str = 'raw'
    parser_config: dict = None
    checker: str = 'baseline'
    checker_config: dict = None
    error_note: str = ''
    timeout: int = 30
    severity: str = 'P2'


class ItemRunnerTest(unittest.TestCase):

    def test_run_one_returns_item_result(self):
        from app02.engine.item_runner import ItemRunner, ItemResult
        conn = FakeConnection()
        runner = ItemRunner(conn, 'dev001', {})
        item = FakeCheckItem()
        with mock.patch('app02.engine.item_runner.run_check_item',
                        return_value=('raw output', True, '', None)):
            result = runner.run_one(item, '2026-01-01 12:00:00')
        self.assertIsInstance(result, ItemResult)
        self.assertEqual(result.command, 'display version')
        self.assertTrue(result.is_ok)
        self.assertEqual(result.raw, 'raw output')

    def test_run_one_captures_exception(self):
        from app02.engine.item_runner import ItemRunner
        conn = FakeConnection()
        runner = ItemRunner(conn, 'dev001', {})
        item = FakeCheckItem()
        with mock.patch('app02.engine.item_runner.run_check_item',
                        side_effect=RuntimeError('SSH timeout')):
            result = runner.run_one(item, '2026-01-01 12:00:00')
        self.assertFalse(result.is_ok)
        self.assertIsNone(result.raw)
        self.assertIn('SSH timeout', result.notes)

    def test_run_one_passes_all_params(self):
        from app02.engine.item_runner import ItemRunner
        conn = FakeConnection()
        runner = ItemRunner(conn, 'dev001', {'site': '化龙'})
        item = FakeCheckItem(command='display memory', timeout=60)
        with mock.patch('app02.engine.item_runner.run_check_item',
                        return_value=('mem output', True, '', None)) as mock_run:
            runner.run_one(item, '2026-01-01 12:00:00', baseline_result='old')
            mock_run.assert_called_once()
            args, kwargs = mock_run.call_args
            self.assertEqual(kwargs['check_item'].command, 'display memory')
            self.assertEqual(kwargs['baseline_result'], 'old')
            self.assertEqual(kwargs['device_name'], 'dev001')
            self.assertEqual(kwargs['device_extra'], {'site': '化龙'})


# ═══════════════════════════════════════════════════════════
# ResultRecorder 测试
# ═══════════════════════════════════════════════════════════

class ResultRecorderTest(unittest.TestCase):

    def test_record_command_creates_check_result(self):
        from app02.engine.result_recorder import ResultRecorder
        recorder = ResultRecorder('2026-01-01 12:00', 'dev001')
        with mock.patch('app02.engine.result_recorder.CheckResult.objects.create',
                        return_value=True) as mock_create:
            recorder.record_command('display version', 'output')
            mock_create.assert_called_once_with(
                time='2026-01-01 12:00',
                device='dev001',
                command='display version',
                result='output',
            )

    def test_record_anomaly_with_baseline_val(self):
        from app02.engine.result_recorder import ResultRecorder
        recorder = ResultRecorder('2026-01-01 12:00', 'dev001')
        with mock.patch('app02.engine.result_recorder._db_create_with_retry',
                        return_value=True):
            recorder.record_anomaly(
                'display memory', 'memory > 90%', 'P1',
                baseline_val='80%', current_val='95%',
            )

    def test_record_parse_skips_when_no_raw(self):
        from app02.engine.result_recorder import ResultRecorder
        recorder = ResultRecorder('2026-01-01 12:00', 'dev001')
        with mock.patch('app02.engine.result_recorder.DeviceParseResult') as mock_model:
            recorder.record_parse('display version', None, {'parsed': True})
            mock_model.objects.update_or_create.assert_not_called()

    def test_connection_failure_handlers_do_not_raise(self):
        from app02.engine.result_recorder import ResultRecorder
        fake_items = [FakeCheckItem(command='cmd1'), FakeCheckItem(command='cmd2')]
        with mock.patch('app02.engine.result_recorder.CheckResult.objects.create'), \
             mock.patch('app02.engine.result_recorder.AnomalyRecord.objects.create'), \
             mock.patch('app02.engine.result_recorder.CheckResult.objects.bulk_create'):
            # Should not raise
            ResultRecorder.record_connection_failure('t1', 'dev001', 'timeout')
            ResultRecorder.record_bulk_connection_failure('t1', 'dev001', 'timeout', fake_items)


# ═══════════════════════════════════════════════════════════
# post_inspection 测试
# ═══════════════════════════════════════════════════════════

class PostInspectionTest(unittest.TestCase):

    def test_hooks_run_sequentially(self):
        from app02.engine.post_inspection import run_post_inspection_hooks
        order = []

        def hook1(tid, t, op):
            order.append('hook1')

        def hook2(tid, t, op):
            order.append('hook2')

        from app02.engine.post_inspection import _HOOKS
        hooks_before = list(_HOOKS)
        try:
            _HOOKS.clear()
            _HOOKS.extend([hook1, hook2])
            run_post_inspection_hooks(1, 't', 'op')
            self.assertEqual(order, ['hook1', 'hook2'])
        finally:
            _HOOKS.clear()
            _HOOKS.extend(hooks_before)

    def test_hook_exception_does_not_block(self):
        from app02.engine.post_inspection import run_post_inspection_hooks
        order = []

        def fail_hook(tid, t, op):
            raise RuntimeError('fail')

        def ok_hook(tid, t, op):
            order.append('ok')

        from app02.engine.post_inspection import _HOOKS
        hooks_before = list(_HOOKS)
        try:
            _HOOKS.clear()
            _HOOKS.extend([fail_hook, ok_hook])
            run_post_inspection_hooks(1, 't', 'op')
            self.assertEqual(order, ['ok'])
        finally:
            _HOOKS.clear()
            _HOOKS.extend(hooks_before)


if __name__ == '__main__':
    unittest.main()
