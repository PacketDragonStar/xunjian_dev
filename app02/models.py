from django.db import models


# ══════════════════════════════════════════════════════════
# 新版巡检引擎数据模型
# ══════════════════════════════════════════════════════════

CHECK_TYPE_CHOICES = [
    ('baseline',  '基线文本对比'),
    ('threshold', '阈值判断'),
    ('count',     '关键字计数'),
    ('contains',  '包含检查'),
    ('custom',    '自定义函数'),
]

PARSER_CHOICES = [
    ('raw',      '原始文本'),
    ('regex',    '正则提取'),
    ('strip_ts', '去时间戳'),
    ('textfsm',  'TextFSM模板'),
]

EXTRACT_PARSER_CHOICES = [
    ('',        '不提取'),
    ('memory',  '内存提取'),
]

# ══════════════════════════════════════════════════════════
# 设备分类 2.0：命名规则解析出的 device_class（基础命令集真源）
# ══════════════════════════════════════════════════════════
DEVICE_CLASS_CHOICES = [
    ('ASW',  '接入交换机'),
    ('CSW',  '核心交换机'),
    ('LSW',  '轻量交换机'),
    ('OASW', '带外接入交换机'),
    ('PSW',  '汇聚交换机'),
    ('USW',  '专线交换机'),
    ('DCI',  '数据中心互联'),
    ('DSW',  'DCI交换机'),
    ('IDC',  '出口交换机'),
    ('SRP',  '业务路由器/设备'),
    ('FW',   '防火墙'),
    ('WAF',  'WEB应用防火墙'),
    ('IPS',  '入侵防御'),
    ('IDS',  '入侵检测'),
    ('OTHER','其他'),
]
DEVICE_CLASS_KEYS = {k for k, _ in DEVICE_CLASS_CHOICES}

# 巡检项能力标签：base=基础健康项（恒跑）；其余为协议特性项（需能力门控）
FEATURE_CHOICES = [
    ('base',    '基础'),
    ('ospf',    'OSPF'),
    ('bgp',     'BGP'),
    ('vrrp',    'VRRP'),
    ('irf',     'IRF'),
    ('m-lag',   'M-LAG'),
    ('rbm',     'RBM'),
    ('security','安全域/策略'),
    ('lacp',    '链路聚合'),
    ('nqa',     'NQA'),
]


def device_class_of(name: str) -> str:
    """按命名规则解析设备名前缀 → device_class（基础命令集真源）。

    取设备名首段字母前缀，查 DEVICE_CLASS_CHOICES；命中返回该类别，
    否则返回 'OTHER'（兜底组仍可跑 base）。IDC 已补映射为出口交换机。
    """
    import re as _re
    m = _re.match(r'^([A-Za-z]+)', name or '')
    if not m:
        return 'OTHER'
    pre = m.group(1).upper()
    return pre if pre in DEVICE_CLASS_KEYS else 'OTHER'


class DeviceGroup(models.Model):
    """设备分组表"""
    name        = models.CharField(verbose_name='分组名称', max_length=50, unique=True)
    description = models.CharField(verbose_name='描述', max_length=200, blank=True)
    check_items = models.ManyToManyField(
        'CheckItem',
        verbose_name='绑定巡检项',
        blank=True,
        related_name='groups'
    )

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = '设备分组'


class NewDevice(models.Model):
    """设备表"""
    name        = models.CharField(verbose_name='设备名', max_length=50, unique=True)
    ip          = models.CharField(verbose_name='IP地址', max_length=50)
    group       = models.ForeignKey(
        DeviceGroup,
        verbose_name='所属分组',
        on_delete=models.SET_NULL,
        null=True, blank=True
    )
    device_type = models.CharField(verbose_name='设备类型', max_length=50)
    username    = models.CharField(verbose_name='用户名', max_length=64)
    password    = models.CharField(verbose_name='密码', max_length=64)
    extra       = models.JSONField(
        verbose_name='扩展参数',
        default=dict,
        blank=True,
        help_text='JSON格式，如: {"ospf_nei": 9, "lldp_nei": 6, "down_ok": 2, "vrrp_master": 1}'
    )
    enabled     = models.BooleanField(verbose_name='启用', default=True)

    # —— 连接层扩展 + 角色/站点元数据 ——
    conn_type       = models.CharField(
        verbose_name='连接方式', max_length=10,
        choices=[('ssh', 'SSH'), ('telnet', 'Telnet')], default='ssh'
    )
    port            = models.IntegerField(verbose_name='端口', null=True, blank=True)
    enable_password = models.CharField(verbose_name='enable密码', max_length=128, blank=True, default='')
    ssh_key_file    = models.CharField(verbose_name='SSH密钥路径', max_length=255, blank=True, default='')
    role            = models.CharField(
        verbose_name='角色', max_length=10, blank=True,
        help_text='fw/csw/asw/lsw/srp'
    )
    site            = models.CharField(
        verbose_name='站点', max_length=20, blank=True,
        help_text='知识城/化龙'
    )
    device_class    = models.CharField(
        verbose_name='设备分类(命名规则)', max_length=20,
        choices=DEVICE_CLASS_CHOICES, default='OTHER', db_index=True,
        help_text='由命名规则解析得出，替代手写 role 作为基础命令集真源'
    )

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = '设备'


class CheckItem(models.Model):
    """巡检项定义表"""
    name           = models.CharField(verbose_name='巡检项名称', max_length=100)
    command        = models.CharField(verbose_name='执行命令', max_length=200)
    parser         = models.CharField(verbose_name='解析器', max_length=30, choices=PARSER_CHOICES, default='raw')
    parser_config  = models.JSONField(verbose_name='解析器配置', null=True, blank=True)
    checker        = models.CharField(verbose_name='检查器', max_length=30, choices=CHECK_TYPE_CHOICES, default='baseline')
    checker_config = models.JSONField(verbose_name='检查器配置', null=True, blank=True)
    error_note     = models.CharField(verbose_name='异常提示', max_length=200, default='请检查')
    timeout        = models.IntegerField(verbose_name='超时(秒)', default=30)
    enabled        = models.BooleanField(verbose_name='启用', default=True)
    feature        = models.CharField(
        verbose_name='能力标签', max_length=10, choices=FEATURE_CHOICES,
        default='base', db_index=True,
        help_text='base=基础健康项(恒跑)；ospf/bgp/vrrp/irf/m-lag/rbm/security/lacp=协议特性项(需能力门控)'
    )
    fix_suggestion = models.CharField(verbose_name='整改建议', max_length=500, null=True, blank=True)
    severity       = models.CharField(
        verbose_name='严重级别', max_length=10, default='P2',
        choices=[('P0', 'P0-高危'), ('P1', 'P1-中危'), ('P2', 'P2-低危')],
        help_text='该巡检项判定异常时记录的严重级别'
    )
    created_at     = models.DateTimeField(verbose_name='创建时间', auto_now_add=True)
    updated_at     = models.DateTimeField(verbose_name='更新时间', auto_now=True)

    # 对比 / 展示增强（不影响判定链路）
    compare_strip = models.JSONField(
        verbose_name='对比清洗配置', null=True, blank=True,
        help_text='对比差异前清洗文本(JSON)：{"head_lines":3,"skip_patterns":["^2026-"]}'
    )
    extract_parser = models.CharField(
        verbose_name='字段提取器', max_length=30, blank=True, default='',
        choices=EXTRACT_PARSER_CHOICES,
        help_text='对比页结构化展示该命令提取的字段（仅展示，不影响判定）'
    )

    def __str__(self):
        return f'{self.name} ({self.command})'

    class Meta:
        verbose_name = '巡检项'


class XunjianRecord(models.Model):
    """巡检总体记录"""
    time             = models.CharField(verbose_name='巡检时间', max_length=50)
    operator         = models.CharField(verbose_name='操作人', max_length=50)
    result           = models.CharField(verbose_name='巡检结果', max_length=20, default='正常')
    is_baseline      = models.BooleanField(verbose_name='是否为基线', default=False)
    device_count     = models.IntegerField(verbose_name='巡检设备数', default=0)
    check_count      = models.IntegerField(verbose_name='执行巡检项数', default=0)
    expected_count   = models.IntegerField(verbose_name='应执行项数', default=0)
    ok_devices       = models.IntegerField(verbose_name='正常台数', default=0)
    anomaly_devices  = models.IntegerField(verbose_name='异常台数', default=0)
    failed_devices   = models.IntegerField(verbose_name='失败台数', default=0)

    @property
    def missing_count(self) -> int:
        """未回显/未执行的项数（应执行 − 实际回显），>0 表示有命令未被执行或落库失败。"""
        return max(0, self.expected_count - self.check_count)

    def __str__(self):
        return f'{self.time} - {self.result}'

    class Meta:
        verbose_name = '巡检记录'
        ordering = ['-time']


class CheckResult(models.Model):
    """单个巡检项的执行结果"""
    time    = models.CharField(verbose_name='巡检时间', max_length=50)
    device  = models.CharField(verbose_name='设备名', max_length=50)
    command = models.CharField(verbose_name='命令', max_length=200)
    result  = models.TextField(verbose_name='命令输出', null=True, blank=True)
    created_at = models.DateTimeField(verbose_name='入库时间', auto_now_add=True, null=True, blank=True)

    class Meta:
        verbose_name = '命令结果'
        indexes = [
            models.Index(fields=['time', 'device', 'command']),
            models.Index(fields=['device']),
            models.Index(fields=['created_at']),
        ]


class DeviceParseResult(models.Model):
    """设备解析结果（阶段二·采集时一次解析落库）。

    与 CheckResult 解耦：CheckResult.result 保留 raw 原文（重解析溯源），
    本表存「device × command 的当前态」结构化结果（app02.parsers 单一真源输出）。
    device 沿用 CheckResult.device 的 CharField 约定（不引 FK，避免采集期额外 DB 查询）。
    下游消费者（sync_cmdb / 异常检查器 / export）优先读本表，无记录时实时 parse 回退。
    """
    device         = models.CharField(verbose_name='设备名', max_length=50, db_index=True)
    command        = models.CharField(verbose_name='命令', max_length=200)
    collected_at   = models.CharField(verbose_name='采集时间', max_length=50,
                                      help_text='对齐 CheckResult.time')
    schema_version = models.CharField(verbose_name='schema版本', max_length=10, default='1')
    data           = models.JSONField(verbose_name='结构化结果', null=True, blank=True)
    created_at     = models.DateTimeField(verbose_name='入库时间', auto_now_add=True, null=True, blank=True)

    class Meta:
        verbose_name = '设备解析结果'
        indexes = [
            models.Index(fields=['device', 'command', 'collected_at']),
            models.Index(fields=['created_at']),
        ]
        unique_together = [('device', 'command', 'collected_at')]


class AnomalyRecord(models.Model):
    """异常记录"""
    time         = models.CharField(verbose_name='巡检时间', max_length=50)
    device       = models.CharField(verbose_name='设备名', max_length=50)
    command      = models.CharField(verbose_name='命令', max_length=200)
    notes        = models.CharField(verbose_name='异常说明', max_length=200, null=True, blank=True)
    confirm      = models.BooleanField(verbose_name='已确认', default=False)
    severity     = models.CharField(verbose_name='严重级别', max_length=10, default='P2',
                                     choices=[('P0', 'P0-高危'), ('P1', 'P1-中危'), ('P2', 'P2-低危')])
    baseline_val = models.TextField(verbose_name='基线值', null=True, blank=True)
    current_val  = models.TextField(verbose_name='当前值', null=True, blank=True)
    created_at   = models.DateTimeField(verbose_name='记录时间', auto_now_add=True, null=True, blank=True)

    class Meta:
        verbose_name = '异常记录'
        indexes = [
            models.Index(fields=['time', 'device']),
            models.Index(fields=['created_at']),
        ]


class InspectionGap(models.Model):
    """巡检缺口埋点：某次巡检中「应执行但未回显」的设备-命令对。

    巡检结束时由 executor._audit_missing_checks 自动写入，用于精确定位
    「哪些设备、哪些命令没巡检到」（历史上曾因单项异常中断整台设备循环，
    导致数十项凭空丢失却无任何记录）。
    """
    time    = models.CharField(verbose_name='巡检时间', max_length=50)
    device  = models.CharField(verbose_name='设备名', max_length=50)
    command = models.CharField(verbose_name='命令', max_length=200)
    note    = models.CharField(verbose_name='说明', max_length=200, blank=True)
    created_at = models.DateTimeField(verbose_name='记录时间', auto_now_add=True, null=True, blank=True)

    class Meta:
        verbose_name = '巡检缺口'
        indexes = [
            models.Index(fields=['time', 'device']),
            models.Index(fields=['created_at']),
        ]


class CheckSet(models.Model):
    """检查集 - 多个设备分组的组合，用于跨分组批量巡检"""
    name        = models.CharField(verbose_name='检查集名称', max_length=100, unique=True)
    description = models.TextField(verbose_name='说明', blank=True)
    groups      = models.ManyToManyField(
        DeviceGroup,
        verbose_name='包含的设备分组',
        blank=True,
        related_name='check_sets'
    )
    enabled    = models.BooleanField(verbose_name='启用', default=True)
    created_at = models.DateTimeField(verbose_name='创建时间', auto_now_add=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = '检查集'


class XunjianTask(models.Model):
    """巡检任务表（后台线程异步执行的状态/进度持久化）"""

    STATUS_CHOICES = [
        ('queued',  '排队中'),
        ('running', '执行中'),
        ('done',    '完成'),
        ('partial', '部分失败'),
        ('failed',  '失败'),
    ]

    status = models.CharField(
        verbose_name='状态', max_length=10,
        choices=STATUS_CHOICES, default='queued',
    )
    operator = models.CharField(verbose_name='操作人', max_length=50, blank=True)
    checkset = models.ForeignKey(
        'CheckSet', verbose_name='检查集', null=True, blank=True,
        on_delete=models.SET_NULL,
    )
    device_count = models.IntegerField(verbose_name='设备总数', default=0)
    done         = models.IntegerField(verbose_name='已完成数', default=0)
    ok_devices      = models.IntegerField(verbose_name='正常设备数', default=0)
    anomaly_devices = models.IntegerField(verbose_name='异常设备数', default=0)
    failed_devices  = models.IntegerField(verbose_name='失败设备数', default=0)
    failed_device_list = models.TextField(verbose_name='失败设备', blank=True, default='')
    xunjian_time = models.CharField(verbose_name='巡检时间', max_length=30, blank=True, default='')
    result = models.CharField(verbose_name='总结果', max_length=10, blank=True, default='')
    error  = models.TextField(verbose_name='错误信息', blank=True, default='')
    created_at  = models.DateTimeField(verbose_name='创建时间', auto_now_add=True)
    finished_at = models.DateTimeField(verbose_name='完成时间', null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = '巡检任务'
        verbose_name_plural = '巡检任务'

    def __str__(self):
        return f'#{self.id} {self.get_status_display()} ({self.operator})'


# ══════════════════════════════════════════════════════════
# 阶段 C：设备发现 + 配置合规
# ══════════════════════════════════════════════════════════

class DiscoveryRecord(models.Model):
    """LLDP 邻居发现记录：与已知资产库比对，标记未知/缺失"""
    time       = models.CharField(verbose_name='发现时间', max_length=50)
    device     = models.CharField(verbose_name='本端设备', max_length=50)
    neighbor   = models.CharField(verbose_name='邻居设备名', max_length=80, blank=True, default='')
    neighbor_ip = models.CharField(verbose_name='邻居管理IP', max_length=50, blank=True, default='')
    local_port = models.CharField(verbose_name='本端端口', max_length=50, blank=True, default='')
    peer_port  = models.CharField(verbose_name='对端端口', max_length=50, blank=True, default='')
    is_known   = models.BooleanField(verbose_name='是否已知资产', default=False)
    site       = models.CharField(verbose_name='站点', max_length=20, blank=True, default='')
    created_at = models.DateTimeField(verbose_name='入库时间', auto_now_add=True, null=True, blank=True)

    class Meta:
        verbose_name = '设备发现记录'
        indexes = [models.Index(fields=['time', 'device'])]


class CompliancePolicy(models.Model):
    """合规策略：一组规则的组合"""
    name        = models.CharField(verbose_name='策略名称', max_length=100, unique=True)
    description = models.TextField(verbose_name='说明', blank=True, default='')
    enabled     = models.BooleanField(verbose_name='启用', default=True)
    created_at  = models.DateTimeField(verbose_name='创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '合规策略'

    def __str__(self):
        return self.name


class ComplianceRule(models.Model):
    """单条合规规则：针对某条已采集命令的输出做匹配判定"""
    RULE_TYPE = [
        ('regex',   '正则必须匹配'),
        ('contains','必须包含'),
        ('absence', '不应出现'),
    ]
    policy         = models.ForeignKey(CompliancePolicy, verbose_name='所属策略',
                                       on_delete=models.CASCADE, related_name='rules')
    name           = models.CharField(verbose_name='规则名称', max_length=100)
    source_command = models.CharField(verbose_name='数据源命令', max_length=200,
                                      help_text='取值自哪条命令的采集结果(如 display current-configuration)')
    rule_type      = models.CharField(verbose_name='判定方式', max_length=20,
                                      choices=RULE_TYPE, default='contains')
    pattern        = models.CharField(verbose_name='匹配内容/正则', max_length=400, blank=True, default='')
    severity       = models.CharField(verbose_name='严重级别', max_length=10, default='P2',
                                      choices=[('P0', 'P0-高危'), ('P1', 'P1-中危'), ('P2', 'P2-低危')])
    note           = models.CharField(verbose_name='不合规说明', max_length=200, blank=True, default='')
    enabled        = models.BooleanField(verbose_name='启用', default=True)

    class Meta:
        verbose_name = '合规规则'

    def __str__(self):
        return f'{self.policy.name}/{self.name}'


class ComplianceResult(models.Model):
    """合规检查结果"""
    time     = models.CharField(verbose_name='检查时间', max_length=50)
    device   = models.CharField(verbose_name='设备名', max_length=50)
    policy   = models.CharField(verbose_name='策略', max_length=100)
    rule     = models.CharField(verbose_name='规则', max_length=100)
    passed   = models.BooleanField(verbose_name='是否合规', default=True)
    detail   = models.TextField(verbose_name='详情', blank=True, default='')
    severity = models.CharField(verbose_name='严重级别', max_length=10, default='P2',
                                choices=[('P0', 'P0-高危'), ('P1', 'P1-中危'), ('P2', 'P2-低危')])
    created_at = models.DateTimeField(verbose_name='入库时间', auto_now_add=True, null=True, blank=True)

    class Meta:
        verbose_name = '合规结果'
        indexes = [models.Index(fields=['time', 'device'])]


# ══════════════════════════════════════════════════════════
# CMDB：基于采集配置解析出来的资产台账（每次 sync_cmdb 重建）
# ══════════════════════════════════════════════════════════

class CmdbDevice(models.Model):
    """CMDB 设备台账（由 CheckResult 解析得到，非手工维护）"""
    name        = models.CharField(verbose_name='设备名', max_length=80, unique=True)
    site        = models.CharField(verbose_name='站点', max_length=20, blank=True, default='')
    vendor      = models.CharField(verbose_name='厂商', max_length=30, blank=True, default='H3C')
    model       = models.CharField(verbose_name='型号', max_length=60, blank=True, default='')
    os_version  = models.CharField(verbose_name='软件版本', max_length=80, blank=True, default='')
    serial      = models.CharField(verbose_name='序列号', max_length=60, blank=True, default='')
    uptime_days = models.IntegerField(verbose_name='运行天数', null=True, blank=True)
    mgmt_ip     = models.CharField(verbose_name='管理IP', max_length=40, blank=True, default='')
    role        = models.CharField(verbose_name='角色', max_length=20, blank=True, default='')
    cpu_5s      = models.FloatField(verbose_name='CPU(5s)%', null=True, blank=True)
    mem_free_ratio = models.FloatField(verbose_name='内存空闲%', null=True, blank=True)
    last_sync   = models.DateTimeField(verbose_name='最近同步', auto_now=True, null=True, blank=True)

    class Meta:
        verbose_name = 'CMDB设备'
        ordering = ['site', 'name']

    def __str__(self):
        return f'{self.name} ({self.site})'


class CmdbInterface(models.Model):
    """CMDB 接口台账"""
    device       = models.ForeignKey(CmdbDevice, verbose_name='设备', on_delete=models.CASCADE, related_name='interfaces')
    name         = models.CharField(verbose_name='接口名', max_length=40)
    admin_status = models.CharField(verbose_name='管理状态', max_length=12, blank=True, default='')
    oper_status  = models.CharField(verbose_name='操作状态', max_length=12, blank=True, default='')
    speed_mbps   = models.IntegerField(verbose_name='速率Mbps', null=True, blank=True)
    duplex       = models.CharField(verbose_name='双工', max_length=10, blank=True, default='')
    mtu          = models.IntegerField(verbose_name='MTU', null=True, blank=True)
    port_mode    = models.CharField(verbose_name='端口模式', max_length=10, blank=True, default='')
    description  = models.CharField(verbose_name='描述', max_length=120, blank=True, default='')
    mac          = models.CharField(verbose_name='MAC', max_length=20, blank=True, default='')
    vlan_id      = models.IntegerField(verbose_name='VLAN', null=True, blank=True)

    class Meta:
        verbose_name = 'CMDB接口'
        unique_together = [('device', 'name')]

    def __str__(self):
        return f'{self.device.name}/{self.name}'


class CmdbVlan(models.Model):
    """CMDB VLAN"""
    device   = models.ForeignKey(CmdbDevice, verbose_name='设备', on_delete=models.CASCADE, related_name='vlans')
    vlan_id  = models.IntegerField(verbose_name='VLAN ID')
    name     = models.CharField(verbose_name='VLAN名', max_length=40, blank=True, default='')

    class Meta:
        verbose_name = 'CMDB VLAN'
        unique_together = [('device', 'vlan_id')]

    def __str__(self):
        return f'VLAN{self.vlan_id}'


class CmdbNeighborLink(models.Model):
    """CMDB 邻居链路（LLDP/物理连接）"""
    device     = models.ForeignKey(CmdbDevice, verbose_name='本端设备', on_delete=models.CASCADE, related_name='links')
    local_port = models.CharField(verbose_name='本端端口', max_length=40, blank=True, default='')
    peer_device = models.CharField(verbose_name='对端设备', max_length=80, blank=True, default='')
    peer_port  = models.CharField(verbose_name='对端端口', max_length=40, blank=True, default='')
    protocol   = models.CharField(verbose_name='协议', max_length=10, blank=True, default='lldp')

    class Meta:
        verbose_name = 'CMDB链路'
        unique_together = [('device', 'local_port', 'peer_device', 'peer_port')]

    def __str__(self):
        return f'{self.device.name}:{self.local_port} → {self.peer_device}:{self.peer_port}'


class CmdbIpSubnet(models.Model):
    """CMDB 接口IP"""
    device         = models.ForeignKey(CmdbDevice, verbose_name='设备', on_delete=models.CASCADE, related_name='ips')
    interface_name = models.CharField(verbose_name='接口', max_length=40, blank=True, default='')
    cidr           = models.CharField(verbose_name='IP/CIDR', max_length=48, blank=True, default='')
    vrf            = models.CharField(verbose_name='VRF', max_length=30, blank=True, default='')
    gateway        = models.CharField(verbose_name='网关', max_length=40, blank=True, default='')

    class Meta:
        verbose_name = 'CMDB IP'
        unique_together = [('device', 'interface_name', 'cidr')]

    def __str__(self):
        return f'{self.interface_name}:{self.cidr}'


class CmdbSyncLog(models.Model):
    """CMDB 同步日志"""
    time          = models.DateTimeField(verbose_name='同步时间', auto_now_add=True)
    site          = models.CharField(verbose_name='站点', max_length=20, blank=True, default='')
    device_count  = models.IntegerField(verbose_name='设备数', default=0)
    note          = models.TextField(verbose_name='说明', blank=True, default='')

    class Meta:
        verbose_name = 'CMDB同步日志'
        ordering = ['-time']

    def __str__(self):
        return f'{self.time} {self.site} ({self.device_count}台)'


class CheckerScript(models.Model):
    """Web 可编辑的自定义 checker 源码覆盖（单用户工具，信任操作者）。
    保存后由 pipeline.load_checker_overrides() 热加载到 _CUSTOM_CHECKERS，
    覆盖 custom_checks.py 中同名的文件版函数。"""
    name = models.CharField(max_length=64, primary_key=True,
                            verbose_name='函数名(对应 checker_config.func)')
    source = models.TextField(verbose_name='源码(def func(parsed, baseline, config, extra): ...)')
    version = models.IntegerField(default=1, verbose_name='当前版本')
    enabled = models.BooleanField(default=True, verbose_name='启用(DB覆盖优先)')
    note = models.TextField(blank=True, verbose_name='备注')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        verbose_name = 'Checker源码'
        verbose_name_plural = 'Checker源码'

    def __str__(self):
        return f'{self.name} (v{self.version})'


class CheckerScriptVersion(models.Model):
    """Checker 源码历史版本，用于回滚。"""
    script = models.ForeignKey(CheckerScript, on_delete=models.CASCADE,
                               related_name='versions', verbose_name='源码')
    version = models.IntegerField(verbose_name='版本号')
    source = models.TextField(verbose_name='源码')
    note = models.TextField(blank=True, verbose_name='备注')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        verbose_name = 'Checker源码版本'
        verbose_name_plural = 'Checker源码版本'
        ordering = ['-version']

    def __str__(self):
        return f'{self.script_id} v{self.version}'