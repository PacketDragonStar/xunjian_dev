"""xunjian → NetBox 字段映射器。

所有映射函数接受 xunjian 数据，返回 NetBox API 可直接用的 dict。
纯函数，无 Django / 无网络依赖。
"""


# ─── 角色映射 ───
ROLE_MAP = {
    'FW':  'firewall',
    'CSW': 'core-switch',
    'ASW': 'access-switch',
    'LSW': 'switch',
    'SRP': 'router',
    'OASW': 'access-switch',
    'PSW': 'core-switch',
    'USW': 'switch',
    'IDC': 'switch',
}


def map_role(xunjian_role: str) -> str:
    """xunjian role → NetBox device_role slug。"""
    return ROLE_MAP.get(xunjian_role.upper(), 'switch')


# ─── 接口类型 ───
SPEED_TO_IF_TYPE = {
    10:     '10base-t',
    100:    '100base-tx',
    1000:   '1000base-t',
    10000:  '10gbase-x-sfpp',
    25000:  '25gbase-x-sfpp',
    40000:  '40gbase-x-qsfpp',
    100000: '100gbase-x-qsfp28',
}


def map_if_type(speed_mbps: int) -> str:
    """speed_mbps → NetBox interface type slug。"""
    if not speed_mbps or speed_mbps <= 0:
        return 'other'
    # 找最近的不超过 speed 的类型
    best = 'other'
    for sp, ift in sorted(SPEED_TO_IF_TYPE.items()):
        if speed_mbps >= sp:
            best = ift
    return best


# ─── 设备状态 ───
def map_device_status(enabled: bool) -> str:
    """NewDevice.enabled → NetBox device status。"""
    return 'active' if enabled else 'offline'


def map_if_status(oper_status: str) -> bool:
    """UP/DOWN → NetBox interface enabled。"""
    return oper_status.upper() == 'UP'


# ─── 堆叠设备拆分 ───
def split_stacked_device(device_name: str, irf_members: list) -> tuple:
    """从 xunjian 设备名 + IRF 成员拆出 Virtual Chassis 名和成员名列表。

    device_name: 'asw003&004.pri.2IDC4f.hualong.xc'
    irf_members: ['1', '2']
    → ('asw003&004', ['asw003', 'asw004'])
    """
    # 去域名后缀
    short = device_name.split('.')[0] if '.' in device_name else device_name
    # 如果含 & 就用作 VC 名
    if '&' in short:
        vc_name = short
        member_names = [m.strip() for m in short.split('&')]
        return vc_name, member_names
    # 不含 &：用 irf_members 的数量构造
    base = short
    vc_name = base
    member_names = [f'{base}_{i}' for i in irf_members] if irf_members else [base]
    return vc_name, member_names


def assign_interface_to_member(ifname: str, member_ids: list) -> int:
    """根据接口名判断属于哪个 IRF 成员。

    ifname: 'GE1/0/1' → member slot=1 → 返回 member_ids 中 slot 对应的成员索引 (0-based)
    默认返回 0（master）。
    """
    import re
    m = re.match(r'[A-Za-z]+(\d+)/', ifname)
    if not m:
        return 0
    slot = int(m.group(1))
    # member_ids 如 ['1', '2'] → slot 1 对应索引 0
    try:
        idx = member_ids.index(str(slot))
        return idx
    except ValueError:
        return 0
