"""NetBox 基础数据 seed。

一次性创建：Site / DeviceRole / Manufacturer / Platform / VLANGroup / CustomFields。
幂等（get_or_create），可重复运行。
"""

from .client import NetBoxClient
from .mapper import ROLE_MAP


def seed_netbox(nb: NetBoxClient, report=None):
    """在 NetBox 中创建所有基础数据（Site/Role/Manufacturer/Platform/CustomField）。

    report: 可选 DiffReport 实例，记录增/跳。
    """
    if not nb.connected:
        print('[seed_netbox] NetBox 不可达，跳过 seed')
        return

    _seed_sites(nb, report)
    _seed_manufacturer(nb, report)
    _seed_roles(nb, report)
    _seed_platform(nb, report)
    _seed_vlan_groups(nb, report)
    _seed_custom_fields(nb, report)


def _seed_sites(nb, report):
    for name, slug in [('知识城', 'zhishicheng'), ('化龙', 'hualong')]:
        obj, created = nb.get_or_create('dcim.sites', name=name, slug=slug,
                                        defaults={'status': 'active'})
        if report:
            if created:
                report.record_created('dcim.sites', name)
            else:
                report.record_skipped('dcim.sites', name, 'exists')


def _seed_manufacturer(nb, report):
    obj, created = nb.get_or_create('dcim.manufacturers', name='H3C', slug='h3c')
    if report:
        if created:
            report.record_created('dcim.manufacturers', 'H3C')
        else:
            report.record_skipped('dcim.manufacturers', 'H3C', 'exists')


def _seed_roles(nb, report):
    for xr, nr_slug in sorted(ROLE_MAP.items()):
        obj, created = nb.get_or_create(
            'dcim.device_roles', name=xr, slug=nr_slug,
        )
        if report:
            if created:
                report.record_created('dcim.device_roles', xr)
            else:
                report.record_skipped('dcim.device_roles', xr, 'exists')


def _seed_platform(nb, report):
    h3c = nb.get('dcim.manufacturers', slug='h3c')
    manufacturer_id = h3c.id if h3c else None
    obj, created = nb.get_or_create(
        'dcim.platforms', name='Comware 7', slug='comware-7',
        defaults={'manufacturer': manufacturer_id} if manufacturer_id else {},
    )
    if report:
        if created:
            report.record_created('dcim.platforms', 'Comware 7')
        else:
            report.record_skipped('dcim.platforms', 'Comware 7', 'exists')


def _seed_vlan_groups(nb, report):
    for site_name, slug in [('知识城', 'zhishicheng'), ('化龙', 'hualong')]:
        site = nb.get('dcim.sites', slug=slug)
        scope_type = 'dcim.site'
        scope_id = site.id if site else None
        obj, created = nb.get_or_create(
            'ipam.vlan_groups', name=f'{site_name}-VLANs', slug=f'{slug}-vlans',
            defaults={
                'scope_type': scope_type,
                'scope_id': scope_id,
            } if scope_id else {},
        )
        if report:
            if created:
                report.record_created('ipam.vlan_groups', site_name)
            else:
                report.record_skipped('ipam.vlan_groups', site_name, 'exists')


def _seed_custom_fields(nb, report):
    fields = [
        ('inspection_last_run',    'date',   '巡检·最近巡检日期'),
        ('inspection_status',      'text',   '巡检·最近巡检状态'),
        ('cpu_usage_5s',           'integer', '巡检·CPU 使用率(5s %)'),
        ('memory_free_pct',        'integer', '巡检·内存空闲率(%)'),
        ('uptime_days',            'integer', '巡检·运行天数'),
        ('capabilities',           'json',   '巡检·能力清单'),
    ]
    for name, cf_type, description in fields:
        obj, created = nb.get_or_create(
            'extras.custom_fields', name=name,
            defaults={
                'content_types': ['dcim.device'],
                'type': cf_type,
                'label': description,
                'description': description,
            },
        )
        if report:
            if created:
                report.record_created('extras.custom_fields', name)
            else:
                report.record_skipped('extras.custom_fields', name, 'exists')
