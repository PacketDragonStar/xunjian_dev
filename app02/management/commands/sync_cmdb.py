"""sync_cmdb —— 把已采集的 CheckResult 解析为 CMDB 台账。

从每台设备最新的若干命令结果中提取：
  display version                → 设备型号/版本/序列号/运行时间
  display interface brief        → 接口状态/速率/双工/PVID/描述
  display lldp neighbor-information list → LLDP 邻居链路
  display vlan brief             → VLAN 列表
  display current-configuration  → 三层接口 IP（Vlan-interface + ip address）

⚠️ 解析逻辑统一来自 app02.parsers.comware（单一真源），本命令不再维护任何内联正则；
   改命令解析只改 app02/parsers/comware.py 一处即可，拓扑图(network-seek)同步受益。
每次运行按设备重建其子表（快照语义）。
"""
import logging

from django.core.management.base import BaseCommand
from django.db import IntegrityError
from app02.models import (
    NewDevice, CheckResult, DeviceParseResult,
    CmdbDevice, CmdbInterface, CmdbVlan, CmdbNeighborLink, CmdbIpSubnet, CmdbSyncLog,
)
from app02.parsers.comware import (
    parse_version, parse_interface_brief, parse_lldp, parse_vlan_brief,
    parse_running_config, parse_cpu_usage, parse_memory_free, parse_manuinfo,
)

logger = logging.getLogger('xunjian')


def _latest(device, command):
    return (CheckResult.objects
            .filter(device=device, command=command)
            .order_by('-created_at', '-id').first())


def _get_structured(device, command, parser_fn):
    """阶段二·采集时一次解析落库消费入口。

    优先读 DeviceParseResult.data（采集时已解析一次）；无记录（历史数据/未跑回填）
    则实时 parse CheckResult.raw 回退，保证阶段切换期 CMDB 输出不变。
    """
    dpr = (DeviceParseResult.objects
           .filter(device=device, command=command)
           .order_by('-collected_at', '-id').first())
    if dpr is not None and dpr.data is not None:
        return dpr.data
    cr = _latest(device, command)
    return parser_fn(cr.result if cr else '') if cr else None


# ───────────────────────── 命令主体 ─────────────────────────
class Command(BaseCommand):
    help = '将已采集的 CheckResult 解析为 CMDB 台账（设备/接口/VLAN/链路/IP）'

    def add_arguments(self, parser):
        parser.add_argument('--site', default='', help='仅同步指定站点(知识城/化龙)，默认全部')

    def handle(self, *args, **options):
        site = options.get('site', '') or ''
        devs = NewDevice.objects.filter(enabled=True)
        if site:
            devs = devs.filter(site=site)

        synced = 0
        for dev in devs:
            try:
                # 阶段二：优先消费 DeviceParseResult（采集时已解析一次），无则实时 parse 回退
                dv = _get_structured(dev.name, 'display version', parse_version) or {}
                real_name = dv.get('name', '')  # 真机回显主机名，仅作参考/日志，不作为主键
                cpu_v = _get_structured(dev.name, 'display cpu-usage', parse_cpu_usage)
                mem_v = _get_structured(dev.name, 'display memory', parse_memory_free)
                ifb_data = _get_structured(dev.name, 'display interface brief', parse_interface_brief) or []
                lldp_data = _get_structured(dev.name, 'display lldp neighbor-information list', parse_lldp) or []
                vlan_data = _get_structured(dev.name, 'display vlan brief', parse_vlan_brief) or []
                cfg_data = _get_structured(dev.name, 'display current-configuration', parse_running_config) or {}
                manu_data = _get_structured(dev.name, 'display device manuinfo', parse_manuinfo) or ''
                # 序列号：优先 display device manuinfo，缺失时回退 display version 的 SN
                serial = (manu_data or '') or dv.get('serial', '')

                # 主键固定用台账名 dev.name，与 CheckResult.device / _latest 的键三处统一，
                # 保证堆叠设备（如 asw001&002）连一台即整组归位，重跑也不会分裂或清空。
                cmdb_dev, _ = CmdbDevice.objects.update_or_create(
                    name=dev.name,
                    defaults=dict(
                        site=dev.site or '', vendor='H3C',
                        model=dv.get('model', '') or dev.device_type or '',
                        os_version=dv.get('os_version', ''), serial=serial,
                        uptime_days=dv.get('uptime_days'), mgmt_ip=dev.ip or '',
                        role=dev.role or '',
                        cpu_5s=cpu_v, mem_free_ratio=mem_v,
                    ),
                )

                # 子表按设备重建（快照）
                cmdb_dev.interfaces.all().delete()
                for it in ifb_data:
                    CmdbInterface.objects.create(device=cmdb_dev, **it)

                cmdb_dev.links.all().delete()
                for nb in lldp_data:
                    try:
                        CmdbNeighborLink.objects.create(
                            device=cmdb_dev, local_port=nb['local_port'],
                            peer_device=nb['peer_device'], peer_port=nb['peer_port'], protocol='lldp')
                    except IntegrityError:
                        continue  # 防御：单条重复不拖垮整台

                cmdb_dev.vlans.all().delete()
                for vid in vlan_data:
                    try:
                        CmdbVlan.objects.create(device=cmdb_dev, vlan_id=vid)
                    except IntegrityError:
                        continue

                cmdb_dev.ips.all().delete()
                for ip in cfg_data.get('ips', []):
                    try:
                        CmdbIpSubnet.objects.create(device=cmdb_dev, **ip)
                    except IntegrityError:
                        continue

                synced += 1
                self.stdout.write(self.style.SUCCESS(f'  [OK] {dev.name} (真实主机名={real_name or "-"} 接口{len(ifb_data)} 链路{len(lldp_data)} VLAN{len(vlan_data)})'))
            except Exception as e:
                self.stdout.write(self.style.WARNING(f'  [FAIL] {dev.name}: {e}'))
                logger.exception(f'[sync_cmdb] {dev.name} 失败')

        CmdbSyncLog.objects.create(site=site, device_count=synced, note='sync_cmdb 全量重建')
        self.stdout.write(self.style.SUCCESS(f'\nCMDB 同步完成：{synced} 台设备（站点={site or "全部"}）'))
