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
import re

from django.core.management.base import BaseCommand
from django.db import IntegrityError
from app02.models import (
    NewDevice, CheckResult, DeviceParseResult,
    CmdbDevice, CmdbInterface, CmdbVlan, CmdbNeighborLink, CmdbIpSubnet, CmdbSyncLog,
    CmdbFan, CmdbPowerSupply, CmdbBoard, CmdbTransceiver, CmdbFlashStorage,
)
from app02.parsers.comware import (
    parse_version, parse_interface_brief, parse_lldp, parse_vlan_brief,
    parse_running_config, parse_cpu_usage, parse_memory_free, parse_manuinfo,
    parse_fan, parse_power, parse_device, parse_transceiver, parse_flash_usage,
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


def _preload_results(device_name):
    """预取一台设备的所有 CheckResult（降为 2 次 DB 查询）"""
    crs = list(CheckResult.objects.filter(device=device_name)
               .order_by('command', '-created_at'))
    seen = set()
    raw_map = {}
    for cr in crs:
        if cr.command not in seen and cr.result:
            seen.add(cr.command)
            raw_map[cr.command] = cr.result
    return raw_map


def _preload_structured(device_name):
    """预取结构化数据"""
    dprs = list(DeviceParseResult.objects.filter(device=device_name)
                .order_by('command', '-collected_at'))
    seen = set()
    struct_map = {}
    for dpr in dprs:
        if dpr.command not in seen and dpr.data is not None:
            seen.add(dpr.command)
            struct_map[dpr.command] = dpr.data
    return struct_map


def _from_cache(cmd, raw_map, struct_map, parser_fn, default=None):
    """从缓存取数据：优先结构化，回落 raw，无数据返回 default"""
    if cmd in struct_map:
        return struct_map[cmd]
    raw = raw_map.get(cmd, '')
    if raw:
        return parser_fn(raw)
    return default or []


# 接口长名 → 短名（transceiver 输出用长名，interface brief 用短名）
#   支持 3 段（HundredGigE1/0/25→HGE1/0/25）和 4 段（FortyGigE1/4/0/33→FGE1/4/0/33）板卡口
_IF_TYPE_SHORT = {
    'HundredGigE': 'HGE', 'FortyGigE': 'FGE', 'TwentyGigE': 'TGE',
    'Twenty-FiveGigE': '25GE', 'Ten-GigabitEthernet': 'XGE',
    'GigabitEthernet': 'GE', 'M-GigabitEthernet': 'MGE',
}
_IF_RE = re.compile(r'^([A-Za-z\-]+)(\d+(?:/\d+){2,4})$')

def _short_iface(name: str) -> str:
    """HundredGigE1/0/25 → HGE1/0/25；已是短名则原样返回。"""
    m = _IF_RE.match(name.strip())
    if not m:
        return name.strip()
    return _IF_TYPE_SHORT.get(m.group(1), m.group(1)) + m.group(2)


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
                # ★ 预取缓存：每台设备从 ~20 次 DB 查询降为 2 次
                raw_map = _preload_results(dev.name)
                struct_map = _preload_structured(dev.name)

                dv = _from_cache('display version', raw_map, struct_map, parse_version, {})
                cpu_v = _from_cache('display cpu-usage', raw_map, struct_map, parse_cpu_usage)
                mem_v = _from_cache('display memory', raw_map, struct_map, parse_memory_free)
                ifb_data = _from_cache('display interface brief', raw_map, struct_map, parse_interface_brief, [])
                lldp_data = _from_cache('display lldp neighbor-information list', raw_map, struct_map, parse_lldp, [])
                vlan_data = _from_cache('display vlan brief', raw_map, struct_map, parse_vlan_brief, [])
                cfg_data = _from_cache('display current-configuration', raw_map, struct_map, parse_running_config, {})
                manu_data = _from_cache('display device manuinfo', raw_map, struct_map, parse_manuinfo, '')
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

                trans_data = _from_cache('display transceiver interface', raw_map, struct_map, parse_transceiver, [])
                cmdb_dev.transceivers.all().delete()
                # 建立 接口名(短名) → 光模块 索引，供接口表关联
                #   Ten-GigabitEthernet1/0/1 → XGE1/0/1, HundredGigE1/0/25 → HGE1/0/25
                trans_by_iface = {}
                for t in trans_data:
                    long_name = t.get('iface', '')
                    short = _short_iface(long_name)
                    trans_by_iface[short] = t
                    try:
                        CmdbTransceiver.objects.create(
                            device=cmdb_dev, interface=long_name,
                            module_type=t.get('type', ''), vendor=t.get('vendor', ''),
                            serial=t.get('serial', ''), wavelength=t.get('wavelength', ''),
                            distance=t.get('distance', ''),
                        )
                    except IntegrityError:
                        continue

                # 子表按设备重建（快照）：接口带光模块信息
                cmdb_dev.interfaces.all().delete()
                for it in ifb_data:
                    t = trans_by_iface.get(it.get('name', ''), {})
                    CmdbInterface.objects.create(device=cmdb_dev, **it,
                                                 transceiver_type=t.get('type', ''),
                                                 transceiver_vendor=t.get('vendor', ''),
                                                 transceiver_serial=t.get('serial', ''),
                                                 transceiver_wavelength=t.get('wavelength', ''),
                                                 transceiver_distance=t.get('distance', ''),
                                                 transceiver_ordering=t.get('ordering_name', ''))

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

                # ── 硬件表同步 ──
                fan_data = _from_cache('display fan', raw_map, struct_map, parse_fan, [])
                cmdb_dev.fans.all().delete()
                for f in fan_data:
                    try:
                        CmdbFan.objects.create(
                            device=cmdb_dev, fan_id=f.get('fan_id', ''),
                            status=f.get('status', ''), fan_type=f.get('type', ''),
                        )
                    except IntegrityError:
                        continue

                psu_data = _from_cache('display power', raw_map, struct_map, parse_power, [])
                cmdb_dev.power_supplies.all().delete()
                for p in psu_data:
                    try:
                        CmdbPowerSupply.objects.create(
                            device=cmdb_dev, psu_id=p.get('id', ''),
                            status=p.get('status', ''), psu_type=p.get('type', ''),
                        )
                    except IntegrityError:
                        continue

                board_data = _from_cache('display device', raw_map, struct_map, parse_device, [])
                cmdb_dev.boards.all().delete()
                for b in board_data:
                    try:
                        CmdbBoard.objects.create(
                            device=cmdb_dev, slot=b.get('slot', ''),
                            board_type=b.get('type', ''), status=b.get('status', ''),
                        )
                    except IntegrityError:
                        continue

                flash_data = _from_cache('dir flash:/', raw_map, struct_map, parse_flash_usage)
                cmdb_dev.flash_storage.all().delete()
                if flash_data:
                    try:
                        CmdbFlashStorage.objects.create(
                            device=cmdb_dev,
                            total_kb=flash_data.get('total_kb'),
                            used_kb=flash_data.get('used_kb'),
                            free_kb=flash_data.get('free_kb'),
                            used_pct=flash_data.get('used_percent'),
                        )
                    except IntegrityError:
                        continue

                synced += 1
                self.stdout.write(self.style.SUCCESS(f'  [OK] {dev.name} (接口{len(ifb_data)} 链路{len(lldp_data)} VLAN{len(vlan_data)})'))
            except Exception as e:
                self.stdout.write(self.style.WARNING(f'  [FAIL] {dev.name}: {e}'))
                logger.exception(f'[sync_cmdb] {dev.name} 失败')

        CmdbSyncLog.objects.create(site=site, device_count=synced, note='sync_cmdb 全量重建')
        self.stdout.write(self.style.SUCCESS(f'\nCMDB 同步完成：{synced} 台设备（站点={site or "全部"}）'))
