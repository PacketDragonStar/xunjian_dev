"""app02.parsers —— Comware (H3C) 解析器「单一真源」。

设计依据：解析器单一真源与采集时一次解析_设计文档.md（2026-07-23 用户拍板）。

核心约束：
  - 本包是**纯 Python**，不依赖 Django、不依赖 network_seek。
    因此 network-seek 可直接 import 本包（把它所在的 app02 目录加入 sys.path），
    实现「两仓共用同一份正则」，消除 sync_cmdb 与 network-seek 各自解析导致的分叉。
  - 所有解析器返回**规范化 dict**（见设计文档 §4 契约），下游自行适配：
      * sync_cmdb        : dict -> CMDB 表
      * network-seek     : dict -> pydantic IR -> Neo4j
  - 注册粒度仅按 OS 家族（hp_comware）；家族内格式变体（防火墙型号等）在解析器内部回退。

增删命令只改本文件一处即可，sync_cmdb 与 network-seek 同时受益。
"""
from app02.parsers.comware import (
    parse_version,
    parse_interface_brief,
    parse_running_config,
    parse_lldp,
    parse_vlan_brief,
    parse_route_table,
    parse_cpu_usage,
    parse_memory_free,
    parse_manuinfo,
    parse_irf,
    parse_mlag_summary,
    parse_link_agg_verbose,
    parse_link_agg_summary,
    parse_vrrp,
    parse_security_zone,
    parse_security_policy,
    parse_rbm_status,
    parse_flash_usage,
)

__all__ = [
    "parse_version",
    "parse_interface_brief",
    "parse_running_config",
    "parse_lldp",
    "parse_vlan_brief",
    "parse_route_table",
    "parse_cpu_usage",
    "parse_memory_free",
    "parse_manuinfo",
    "parse_irf",
    "parse_mlag_summary",
    "parse_link_agg_verbose",
    "parse_link_agg_summary",
    "parse_vrrp",
    "parse_security_zone",
    "parse_security_policy",
    "parse_rbm_status",
    "parse_flash_usage",
    # 调度层
    "SCHEMA_VERSION",
    "COMMAND_PARSER_MAP",
    "parse_device_command",
    "is_parseable",
]


# ═════════════════════════════════════════════════════════════════════════════════
# 调度层（阶段二·采集时一次解析）
# ═════════════════════════════════════════════════════════════════════════════════

# 结构化 schema 版本号：下游（sync_cmdb / network-seek / export）据此做兼容判断。
SCHEMA_VERSION = '1'

# 命令 → 单一真源解析函数 映射（仅按 OS 家族注册；命令字符串归一为小写匹配）。
COMMAND_PARSER_MAP = {
    'display version':                              parse_version,
    'display interface brief':                     parse_interface_brief,
    'display lldp neighbor-information list':      parse_lldp,
    'display vlan brief':                          parse_vlan_brief,
    'display current-configuration':               parse_running_config,
    'display cpu-usage':                           parse_cpu_usage,
    'display memory':                              parse_memory_free,
    'display device manuinfo':                     parse_manuinfo,
    'display ip routing-table':                    parse_route_table,
    'display irf':                                 parse_irf,
    'display m-lag summary':                       parse_mlag_summary,
    'display link-aggregation verbose':            parse_link_agg_verbose,
    'display link-aggregation summary':            parse_link_agg_summary,
    'display vrrp':                                parse_vrrp,
    'display vrrp verbose':                       parse_vrrp,
    'display security-zone':                       parse_security_zone,
    'display security-policy ip':                  parse_security_policy,
    'display remote-backup-group status':          parse_rbm_status,
    'dir flash:/':                                 parse_flash_usage,
}


def is_parseable(command: str) -> bool:
    """该命令是否有对应的结构化解析器（即是否纳入采集时一次解析）。"""
    return bool(command) and command.strip().lower() in COMMAND_PARSER_MAP


def parse_device_command(command: str, raw: str):
    """按命令分发到单一真源解析器，返回规范化结构化结果（dict / list / None）。

    - 无映射命令 → 返回 None（调用方跳过落库，下游仍可走 raw 回退）。
    - 解析异常 → 吞掉并返回 None（不拖垮巡检主流程）。
    """
    fn = COMMAND_PARSER_MAP.get((command or '').strip().lower())
    if fn is None:
        return None
    try:
        return fn(raw or '')
    except Exception as e:  # 单条解析失败不影响整台设备
        import logging
        logging.getLogger('xunjian').warning(f'parse_device_command[{command}] 失败: {e}')
        return None

