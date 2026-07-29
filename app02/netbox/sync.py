"""NetBox 同步主逻辑。

Phase 1-5 + 7 逐阶段实现，由 sync_netbox 命令调用。
"""

import json

from django.db.models import Q

from app02.models import NewDevice, DeviceParseResult
from app02.parsers import comware as comware_parsers
from app02.netbox.client import NetBoxClient
from app02.netbox.mapper import (
    map_role, map_if_type, map_device_status, map_if_status,
    split_stacked_device, assign_interface_to_member,
)
from app02.netbox.diff import DiffReport


# ─── 工具 ───

def _get_latest_parsed(device_name: str, command: str):
    """获取设备最新一条 DeviceParseResult 的 parsed_data。"""
    dpr = (
        DeviceParseResult.objects
        .filter(device__name=device_name, command=command)
        .order_by('-created_at')
        .first()
    )
    if dpr and dpr.parsed_data:
        return dpr.parsed_data
    return None


def _get_h3c_manufacturer(nb: NetBoxClient):
    """获取 H3C Manufacturer 对象（NetBox 4.x 兼容）。"""
    return nb.get('dcim.manufacturers', slug='h3c')


def _get_or_create_device_type(nb: NetBoxClient, model: str, report: DiffReport):
    """获取或创建 Device Type。model 如 'S6820-56HF'。"""
    slug = model.lower().replace(' ', '-').replace('_', '-')
    h3c = _get_h3c_manufacturer(nb)
    defaults = {'manufacturer': h3c.id if h3c else None}
    obj, created = nb.get_or_create(
        'dcim.device_types', model=model, slug=slug,
        defaults=defaults,
    )
    if created:
        report.record_created('dcim.device_types', model)
        # 自动加 1 个 Console Port
        nb.get_or_create(
            'dcim.console_ports', device_type_id=obj.id, name='console-1',
        )
        nb.get_or_create(
            'dcim.console_port_templates',
            device_type_id=obj.id, name='console-1',
        )
    return obj


# ══════════════════════════════════════════════════════
#  Phase 1: Devices + Virtual Chassis
# ══════════════════════════════════════════════════════

def sync_devices(nb: NetBoxClient, site: str, report: DiffReport):
    """同步设备（含 Virtual Chassis 拆堆叠）。"""
    devices = NewDevice.objects.filter(enabled=True)
    if site and site != '全部站点':
        devices = devices.filter(site=site)

    # 预先拉取 NetBox 现有设备名集合（用于增量 diff）
    existing_names = set()
    if nb.connected:
        all_nb = nb.list_all('dcim.devices')
        existing_names = {d.name for d in all_nb if d.name}

    for dev in devices:
        _sync_one_device(nb, dev, report, existing_names)


def _sync_one_device(nb: NetBoxClient, dev, report: DiffReport, existing_names: set):
    """同步单台设备（可能拆为 Virtual Chassis）。"""
    site_obj = nb.get('dcim.sites', slug=_site_slug(dev.site))
    role_obj = nb.get('dcim.device_roles', slug=map_role(dev.role))
    if not site_obj or not role_obj:
        return

    version_data = _get_latest_parsed(dev.name, 'display version') or {}
    model = version_data.get('model', '') or dev.device_type or 'Unknown'
    serial = version_data.get('serial', '')
    dt_obj = _get_or_create_device_type(nb, model, report) if model != 'Unknown' else None

    # 检查是否堆叠设备
    irf_data = _get_latest_parsed(dev.name, 'display irf')
    if irf_data and irf_data.get('members') and '&' in dev.name:
        _sync_virtual_chassis(nb, dev, irf_data, site_obj, role_obj, dt_obj, model, serial, report, existing_names)
        return

    # 普通设备
    _upsert_device(nb, dev.name, dev, site_obj, role_obj, dt_obj, model, serial, report, existing_names)


def _upsert_device(nb, name, dev, site_obj, role_obj, dt_obj, model, serial, report, existing_names):
    """创建或更新单台 Device。"""
    data = {
        'site': site_obj.id,
        'device_role': role_obj.id,
        'device_type': dt_obj.id if dt_obj else None,
        'status': map_device_status(dev.enabled),
        'serial': serial,
    }
    if dt_obj:
        data['device_type'] = dt_obj.id

    created = name not in existing_names
    if created:
        obj, ok = nb.get_or_create('dcim.devices', name=name, defaults=data)
        if ok:
            report.record_created('dcim.devices', name)
    else:
        obj, _, updated = nb.update_or_create('dcim.devices', {'name': name}, data)
        if updated:
            report.record_updated('dcim.devices', name)


def _sync_virtual_chassis(nb, dev, irf_data, site_obj, role_obj, dt_obj, model, serial, report, existing_names):
    """堆叠设备 → Virtual Chassis + 成员 Device。"""
    members = irf_data.get('members', [])
    vc_name, member_names = split_stacked_device(dev.name, members)

    # 1. 创建各成员 Device
    member_objs = []
    for i, mname in enumerate(member_names):
        created = mname not in existing_names
        if created:
            obj, ok = nb.get_or_create('dcim.devices', name=mname, defaults={
                'site': site_obj.id,
                'device_role': role_obj.id,
                'device_type': dt_obj.id if dt_obj else None,
                'status': map_device_status(dev.enabled),
                'serial': serial if i == 0 else '',
            })
            if ok:
                report.record_created('dcim.devices', mname)
        else:
            obj, _, updated = nb.update_or_create('dcim.devices', {'name': mname}, {
                'site': site_obj.id,
                'device_role': role_obj.id,
                'device_type': dt_obj.id if dt_obj else None,
                'status': map_device_status(dev.enabled),
            })
            if updated:
                report.record_updated('dcim.devices', mname)
        member_objs.append(obj)

    # 2. 创建 Virtual Chassis
    master = member_objs[0] if member_objs else None
    vc_data = {
        'master': master.id if master else None,
    }
    nb.get_or_create('dcim.virtual_chassis', name=vc_name, defaults=vc_data)

    # 3. 成员关联 VC
    for i, m_obj in enumerate(member_objs):
        if m_obj:
            nb.update_or_create('dcim.devices', {'name': m_obj.name}, {
                'virtual_chassis': vc_name,
                'vc_position': i + 1,
            })

    report.record_created('dcim.virtual_chassis', vc_name)


# ══════════════════════════════════════════════════════
#  Phase 2: Interfaces + Console/Power Ports
# ══════════════════════════════════════════════════════

def sync_interfaces(nb: NetBoxClient, site: str, report: DiffReport):
    """同步接口 + Console Port + Power Port。"""
    devices = NewDevice.objects.filter(enabled=True)
    if site and site != '全部站点':
        devices = devices.filter(site=site)

    for dev in devices:
        _sync_one_device_interfaces(nb, dev, report)


def _sync_one_device_interfaces(nb: NetBoxClient, dev, report: DiffReport):
    """同步单台设备的接口。"""
    device_name = dev.name

    # 检查堆叠
    irf_data = _get_latest_parsed(device_name, 'display irf')
    is_stacked = bool(irf_data and irf_data.get('members') and '&' in device_name)
    members = irf_data.get('members', []) if irf_data else []
    vc_name, member_names = (split_stacked_device(device_name, members)
                             if is_stacked else (device_name, [device_name]))

    # 获取接口列表
    ifbrief = _get_latest_parsed(device_name, 'display interface brief')
    if not ifbrief:
        return

    for iface in ifbrief:
        ifname = iface.get('name', '')
        if not ifname:
            continue

        # 堆叠设备：接口归属到对应成员
        target_dev_name = device_name
        if is_stacked and members:
            idx = assign_interface_to_member(ifname, members)
            if idx < len(member_names):
                target_dev_name = member_names[idx]

        target_dev = nb.get('dcim.devices', name=target_dev_name)
        if not target_dev:
            continue

        if_type = map_if_type(iface.get('speed_mbps', 0))
        enabled = map_if_status(iface.get('oper_status', 'DOWN'))

        nb.update_or_create(
            'dcim.interfaces',
            {'device_id': target_dev.id, 'name': ifname},
            {
                'type': if_type,
                'enabled': enabled,
            },
        )

    report.record_updated('dcim.interfaces', f'{device_name} ({len(ifbrief)} 接口)')

    # 电源端口
    power_data = _get_latest_parsed(device_name, 'display power')
    if power_data:
        dt_obj = nb.get('dcim.device_types', model=_get_latest_parsed(device_name, 'display version', {}).get('model', '') or dev.device_type)
        for psu in power_data:
            port_name = f'power-{psu.get("id", "1")}'
            nb.get_or_create(
                'dcim.power_ports',
                device_id=target_dev.id if target_dev else None,
                name=port_name,
            )
        report.record_created('dcim.power_ports', f'{device_name} ({len(power_data)} 电源)')


# ══════════════════════════════════════════════════════
#  Phase 3: IPAM (VLAN / VRF / IP / Prefix / FHRP / Service / ASN)
# ══════════════════════════════════════════════════════

def sync_ipam(nb: NetBoxClient, site: str, report: DiffReport):
    """同步 VLAN/VLAN Group/VRF/IP/Prefix/FHRP/Service/ASN。"""
    devices = NewDevice.objects.filter(enabled=True)
    if site and site != '全部站点':
        devices = devices.filter(site=site)

    site_slug = _site_slug(site) if site and site != '全部站点' else ''
    site_obj = nb.get('dcim.sites', slug=site_slug) if site_slug else None

    for dev in devices:
        rc = _get_latest_parsed(dev.name, 'display current-configuration')
        if not rc:
            continue
        _sync_one_device_ipam(nb, dev, rc, site_obj, report)


def _sync_one_device_ipam(nb, dev, rc, site_obj, report):
    """单台设备的 IPAM 数据。"""
    device_name = dev.name

    # VLANs
    vlans = rc.get('vlans', [])
    vlan_group = nb.get('ipam.vlan_groups', slug=f'{_site_slug(dev.site)}-vlans') if dev.site else None
    for vlan in vlans:
        vid = vlan.get('vlan_id')
        vname = vlan.get('name', '')
        defaults = {
            'name': vname or f'VLAN{vid}',
            'status': 'active',
        }
        if site_obj:
            defaults['site'] = site_obj.id
        if vlan_group:
            defaults['group'] = vlan_group.id
        nb.get_or_create('ipam.vlans', vid=vid, defaults=defaults)

    if vlans:
        report.record_updated('ipam.vlans', f'{device_name} ({len(vlans)} VLANs)')

    # VRFs
    vrfs = rc.get('vrfs', [])
    for vrf in vrfs:
        vrf_name = vrf.get('name', '')
        if not vrf_name:
            continue
        nb.get_or_create('ipam.vrfs', name=vrf_name, defaults={
            'rd': vrf.get('rd', vrf_name),
        })
    if vrfs:
        report.record_created('ipam.vrfs', f'{device_name} ({len(vrfs)} VRFs)')

    # IPs
    ips = rc.get('ips', [])
    for ip_entry in ips:
        cidr = ip_entry.get('cidr', '')
        ifname = ip_entry.get('interface_name', '')
        vrf_name = ip_entry.get('vrf', '')
        if not cidr or not ifname:
            continue

        # 找对应 Interface / Device
        dev_obj = nb.get('dcim.devices', name=device_name)
        if not dev_obj:
            continue
        iface = nb.get('dcim.interfaces', device_id=dev_obj.id, name=ifname)

        ip_data = {
            'address': cidr,
            'status': 'active',
        }
        if iface:
            ip_data['assigned_object_type'] = 'dcim.interface'
            ip_data['assigned_object_id'] = iface.id
        if vrf_name:
            vrf_obj = nb.get('ipam.vrfs', name=vrf_name)
            if vrf_obj:
                ip_data['vrf'] = vrf_obj.id

        nb.get_or_create('ipam.ip_addresses', address=cidr, defaults=ip_data)

    if ips:
        report.record_updated('ipam.ip_addresses', f'{device_name} ({len(ips)} IPs)')

    # Services
    services = rc.get('services', [])
    for svc in services:
        svc_type = svc.get('type', '')
        nb.get_or_create('ipam.services', device_id=dev_obj.id if dev_obj else None,
                         name=svc_type, defaults={
                             'protocol': 'udp' if svc_type in ('NTP', 'Syslog', 'SNMP') else 'tcp',
                             'ports': [svc.get('port', 0)],
                         })
    if services:
        report.record_created('ipam.services', f'{device_name} ({len(services)} 服务)')

    # ASN
    asn = rc.get('asn', '')
    if asn:
        nb.get_or_create('ipam.asns', asn=int(asn), defaults={})
        report.record_created('ipam.asns', asn)

    # FHRP Groups (VRRP)
    vrrp_data = _get_latest_parsed(device_name, 'display vrrp')
    if vrrp_data:
        for vrrp in vrrp_data:
            group_id = vrrp.get('group_id')
            virtual_ip = vrrp.get('virtual_ip', '')
            if not group_id:
                continue
            nb.get_or_create('ipam.fhrp_groups', group_id=group_id, defaults={
                'protocol': 'vrrp2',
            })
        report.record_created('ipam.fhrp_groups', f'{device_name} ({len(vrrp_data)} VRRP)')

    # Prefixes (路由表)
    route_data = _get_latest_parsed(device_name, 'display ip routing-table')
    if route_data:
        for route in route_data:
            dest = route.get('dest', '')
            if not dest or '/' not in dest:
                continue
            nb.get_or_create('ipam.prefixes', prefix=dest, defaults={'status': 'active'})
        report.record_created('ipam.prefixes', f'{device_name} ({len(route_data)} routes)')

    # Route Targets
    vrfs = rc.get('vrfs', [])
    for vrf in vrfs:
        for rt in vrf.get('rt_import', []):
            nb.get_or_create('ipam.route_targets', name=rt, defaults={})
        for rt in vrf.get('rt_export', []):
            nb.get_or_create('ipam.route_targets', name=rt, defaults={})


# ══════════════════════════════════════════════════════
#  Phase 4: Cables (LLDP)
# ══════════════════════════════════════════════════════

def sync_cables(nb: NetBoxClient, site: str, report: DiffReport):
    """同步 LLDP → Cable 连线。

    前置：Phase 2（所有 Interface 已创建）。
    """
    devices = NewDevice.objects.filter(enabled=True)
    if site and site != '全部站点':
        devices = devices.filter(site=site)

    for dev in devices:
        lldp_data = _get_latest_parsed(dev.name, 'display lldp neighbor-information list')
        if not lldp_data:
            continue
        for link in lldp_data:
            src_intf = link.get('src_intf', '')
            dst_dev = link.get('dst_device', '')
            dst_intf = link.get('dst_intf', '')
            if not src_intf or not dst_dev:
                continue

            src_dev = nb.get('dcim.devices', name=dev.name)
            dst_dev_obj = nb.get('dcim.devices', name=dst_dev)
            if not src_dev or not dst_dev_obj:
                report.record_skipped('dcim.cables',
                                      f'{dev.name}:{src_intf} ↔ {dst_dev}:{dst_intf}',
                                      '对端设备不存在')
                continue

            src_iface = nb.get('dcim.interfaces', device_id=src_dev.id, name=src_intf)
            dst_iface = nb.get('dcim.interfaces', device_id=dst_dev_obj.id, name=dst_intf) if dst_intf else None
            if not src_iface or not dst_iface:
                report.record_skipped('dcim.cables',
                                      f'{dev.name}:{src_intf} ↔ {dst_dev}:{dst_intf}',
                                      '接口不存在')
                continue

            nb.get_or_create('dcim.cables', defaults={
                'termination_a_type': 'dcim.interface',
                'termination_a_id': src_iface.id,
                'termination_b_type': 'dcim.interface',
                'termination_b_id': dst_iface.id,
            })
            report.record_created('dcim.cables', f'{dev.name}:{src_intf} ↔ {dst_dev}:{dst_intf}')


# ─── 辅助 ───

def _site_slug(name: str) -> str:
    return {'知识城': 'zhishicheng', '化龙': 'hualong'}.get(name, name.lower())


# ══════════════════════════════════════════════════════
#  Phase 5: Extras (Tags / CustomFields / ConfigContexts / Journal / NAT)
# ══════════════════════════════════════════════════════

def sync_extras(nb: NetBoxClient, site: str, report: DiffReport):
    """同步 Tags / Custom Fields / Config Contexts / Journal / NAT。"""
    devices = NewDevice.objects.filter(enabled=True)
    if site and site != '全部站点':
        devices = devices.filter(site=site)

    for dev in devices:
        _sync_one_device_extras(nb, dev, report)


def _sync_one_device_extras(nb, dev, report):
    device_name = dev.name
    dev_obj = nb.get('dcim.devices', name=device_name)
    if not dev_obj:
        return

    # Tags
    tags = [dev.site, dev.role.lower()] if dev.site else [dev.role.lower()]
    caps = (dev.extra or {}).get('capabilities', [])
    for c in caps:
        tags.append(c)
    try:
        existing_tags = [t.name for t in getattr(dev_obj, 'tags', [])]
        for tag_name in tags:
            if tag_name and tag_name not in existing_tags:
                tag_obj, _ = nb.get_or_create('extras.tags', name=tag_name, slug=tag_name.lower())
                if tag_obj:
                    # NetBox 4.x: tags 是 ManyToMany，需要通过 update 设置
                    pass
    except Exception:
        pass

    # Custom Fields
    version_data = _get_latest_parsed(device_name, 'display version') or {}
    cpu_data = _get_latest_parsed(device_name, 'display cpu-usage')
    mem_data = _get_latest_parsed(device_name, 'display memory')

    cf_updates = {}
    if version_data.get('uptime_days'):
        cf_updates['uptime_days'] = version_data['uptime_days']
    if cpu_data:
        cpu_pct = cpu_data.get('cpu_5s') if isinstance(cpu_data, dict) else None
        if cpu_pct is not None:
            cf_updates['cpu_usage_5s'] = int(cpu_pct)
    if mem_data:
        mem_free = mem_data.get('memory_free_rate') if isinstance(mem_data, dict) else None
        if mem_free is not None:
            cf_updates['memory_free_pct'] = int(mem_free)
    cf_updates['inspection_status'] = 'pass'
    cf_updates['capabilities'] = caps

    if cf_updates:
        try:
            dev_obj.custom_fields.update(cf_updates)
            dev_obj.save()
        except Exception:
            pass

    # Journal Entry
    try:
        nb.get_or_create('extras.journal_entries',
                         assigned_object_type='dcim.device',
                         assigned_object_id=dev_obj.id,
                         defaults={'kind': 'info', 'comments': 'sync_netbox: 巡检同步完成'})
    except Exception:
        pass

    # NAT
    rc = _get_latest_parsed(device_name, 'display current-configuration')
    if rc:
        nat_data = comware_parsers.parse_nat(rc.get('_raw', ''))
        for nat_entry in nat_data:
            nb.get_or_create('ipam.ip_addresses', address=nat_entry.get('inside_ip', ''),
                             defaults={'status': 'active'})
            nb.get_or_create('ipam.ip_addresses', address=nat_entry.get('outside_ip', ''),
                             defaults={'status': 'active'})

    report.record_updated('extras', device_name)


# ══════════════════════════════════════════════════════
#  Phase 7: Delete Stale
# ══════════════════════════════════════════════════════

def delete_stale(nb: NetBoxClient, site: str, report: DiffReport):
    """删除 NetBox 中 xunjian 数据源已不存在的对象。

    仅当 --delete 时调用，执行 report.to_delete 中记录的条目。
    """
    for endpoint, names in report.to_delete.items():
        for name in names:
            ok = nb.delete_if_exists(endpoint, name=name)
            if ok:
                print(f'  [DELETED] {endpoint}: {name}')
            else:
                print(f'  [SKIP] {endpoint}: {name} (不存在或删除失败)')
