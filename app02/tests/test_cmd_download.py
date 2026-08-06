"""命令回显批量下载功能测试（cmd_download_*）。

覆盖：
- 页面可渲染（cmd_download_page）
- 命令列表 AJAX（cmd_download_commands）
- zip 打包：设备分文件 + !Command: 分段（cmd_download_zip）
- 站点过滤
- 缺参校验
"""
import io
import json
import unittest
import zipfile

from django.test import RequestFactory

from app02.models import CheckResult, NewDevice, XunjianRecord


def _mk_device(name, site):
    return NewDevice.objects.create(
        name=name, ip='10.0.0.1', site=site, enabled=True,
        device_type='hp_comware', username='u', password='p',
        conn_type='netmiko', role='ASW', device_class='ASW',
        extra={},
    )


def _mk_record(time):
    return XunjianRecord.objects.create(
        time=time, operator='tester', result='正常', device_count=2,
        check_count=4, expected_count=4,
    )


class CmdDownloadTest(unittest.TestCase):
    def setUp(self):
        self.rf = RequestFactory()
        self.time = '2026-01-01 10:00:00'
        _mk_record(self.time)
        d1 = _mk_device('dev001', '知识城')
        d2 = _mk_device('dev002', '化龙')
        for dev in (d1, d2):
            CheckResult.objects.create(
                time=self.time, device=dev.name,
                command='display logbuffer', result=f'log of {dev.name}')
            CheckResult.objects.create(
                time=self.time, device=dev.name,
                command='display current-configuration', result=f'cfg of {dev.name}')

    def tearDown(self):
        CheckResult.objects.all().delete()
        XunjianRecord.objects.all().delete()
        NewDevice.objects.all().delete()

    def test_page_renders(self):
        resp = self.cmd_download_page_get()
        self.assertEqual(resp.status_code, 200)

    def test_commands_ajax(self):
        req = self.rf.get('/new/cmd/download/commands/', {'time': self.time})
        from app02.views import cmd_download_commands
        resp = cmd_download_commands(req)
        data = json.loads(resp.content)
        self.assertEqual(set(data['commands']),
                         {'display logbuffer', 'display current-configuration'})

    def test_zip_packs_per_device_with_command_headers(self):
        req = self.rf.get('/new/cmd/download/zip/', {
            'time': self.time,
            'commands': ['display logbuffer', 'display current-configuration'],
        })
        from app02.views import cmd_download_zip
        resp = cmd_download_zip(req)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/zip')

        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        names = zf.namelist()
        # 2 台设备各一个文件（目录 = 时间）
        self.assertEqual(len(names), 2)
        for n in names:
            self.assertIn('dev00', n)
            content = zf.read(n).decode('utf-8')
            self.assertIn('!Command: display logbuffer', content)
            self.assertIn('!Command: display current-configuration', content)

    def test_zip_site_filter(self):
        req = self.rf.get('/new/cmd/download/zip/', {
            'time': self.time, 'site': '化龙',
            'commands': ['display logbuffer'],
        })
        from app02.views import cmd_download_zip
        resp = cmd_download_zip(req)
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        names = zf.namelist()
        self.assertEqual(len(names), 1)
        self.assertIn('dev002', names[0])

    def test_zip_missing_params(self):
        from app02.views import cmd_download_zip
        # 无命令
        req = self.rf.get('/new/cmd/download/zip/', {'time': self.time})
        self.assertEqual(cmd_download_zip(req).status_code, 400)
        # 无时间
        req = self.rf.get('/new/cmd/download/zip/', {'commands': ['display logbuffer']})
        self.assertEqual(cmd_download_zip(req).status_code, 400)

    def cmd_download_page_get(self):
        from app02.views import cmd_download_page
        req = self.rf.get('/new/cmd/download/')
        return cmd_download_page(req)
