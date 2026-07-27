"""DeviceSession — 设备 SSH 连接生命周期管理。

纯连接层：建立连接、关分页、断开。不含业务逻辑（能力探测等）。
"""
import logging
from netmiko import ConnectHandler

from app02.models import NewDevice

logger = logging.getLogger(__name__)


def _normalize_device_type(device_type: str) -> str:
    """兼容历史设备类型命名，转换为 netmiko 可识别值。"""
    dt = (device_type or '').strip().lower()
    if not dt:
        return 'huawei'
    if 'h3c' in dt or 'comware' in dt or 'hp_comware' in dt:
        return 'hp_comware'
    if 'huawei' in dt:
        return 'huawei'
    if 'vrpv8' in dt:
        return 'huawei_vrpv8'
    if 'cisco' in dt or 'ios' in dt or 'nxos' in dt:
        return 'hp_comware'
    return dt


def _build_conn_kwargs(device: NewDevice) -> dict:
    """根据 NewDevice 连接字段构造 netmiko ConnectHandler 参数。

    支持：端口(port)、enable密码(secret)、SSH密钥(use_keys/key_file)、telnet。
    """
    _dtype = _normalize_device_type(device.device_type)
    kwargs = dict(
        device_type=('hp_comware_telnet' if device.conn_type == 'telnet' else _dtype),
        ip=device.ip,
        username=device.username,
        password=device.password,
        conn_timeout=30,
        fast_cli=False,
        global_delay_factor=2,
    )
    if device.port:
        kwargs['port'] = device.port
    if device.enable_password:
        kwargs['secret'] = device.enable_password
    if device.ssh_key_file:
        kwargs.update(use_keys=True, key_file=device.ssh_key_file)
    return kwargs


class DeviceSession:
    """封装单台设备的 SSH 连接生命周期。

    Usage:
        session = DeviceSession(device)
        connection = session.connect()
        # ... use connection ...
        session.disconnect(connection)
    """

    def __init__(self, device: NewDevice):
        self.device = device

    def connect(self):
        """建立 SSH/Telnet 连接并关分页。

        Returns:
            netmiko.ConnectHandler 连接对象

        Raises:
            Exception: 连接失败（由调用方处理）
        """
        kwargs = _build_conn_kwargs(self.device)
        connection = ConnectHandler(**kwargs)

        # IRF 设备名含 &（如 csw001&002），netmiko 的 base_prompt
        # 匹配会失败。覆盖为通配模式，信任终端提示符以 > # ] 结尾。
        if '&' in (self.device.name or ''):
            connection.base_prompt = r'[>#\]]\s*$'

        # 关分页（hp_comware V7 默认分页，失败不影响后续）
        try:
            connection.send_command(
                'screen-length disable',
                expect_string=r'>|\$|#|\]',
                read_timeout=10,
            )
        except Exception as e:
            logger.warning(f'[{self.device.name}] 关分页预命令失败(忽略): {e}')

        logger.info(f'[{self.device.name}] 连接成功')
        return connection

    @staticmethod
    def disconnect(connection):
        """安全断开连接。"""
        try:
            connection.disconnect()
        except Exception:
            pass
