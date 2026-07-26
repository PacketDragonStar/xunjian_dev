"""阶段 C：设备发现 + 配置合规。

完全基于「已采集的 CheckResult」做二次分析，不新增任何设备连接：
- 设备发现：解析 ``display lldp neighbor-information list``，与已知资产库(NewDevice)比对，
  标记未知邻居 / 缺失 LLDP 的设备。
- 配置合规：按 ComplianceRule 对指定命令的采集结果做 正则/包含/不应出现 判定。

LLDP 解析为启发式实现，真实回显与文档 CPU/内存一样可能需要校准（见 _parse_lldp 注释）。
"""
import logging
import re
from datetime import datetime

from app02.parsers.comware import parse_lldp as _comware_parse_lldp

logger = logging.getLogger('xunjian')

LLDP_COMMAND = 'display lldp neighbor-information list'


# ───────────────────────── 设备发现 ─────────────────────────
def _parse_lldp(raw: str):
    """解析 comware ``display lldp neighbor-information list`` 输出。

    委托 ``app02.parsers.comware.parse_lldp``（单一真源，已用真实回显校准），
    仅做 key 适配（peer_device → neighbor），保证 run_discovery 下游不动、判定不变。
    解析失败返回空列表（不抛异常）。
    """
    return [
        {'local_port': n['local_port'], 'peer_port': n['peer_port'], 'neighbor': n['peer_device']}
        for n in _comware_parse_lldp(raw)
    ]


def run_discovery(site: str = None, xunjian_time: str = None) -> dict:
    """对范围内设备做 LLDP 发现，写入 DiscoveryRecord，返回汇总。"""
    from app02.models import NewDevice, CheckResult, DiscoveryRecord

    xunjian_time = xunjian_time or datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    devs = NewDevice.objects.filter(enabled=True)
    if site:
        devs = devs.filter(site=site)

    known_names = set(NewDevice.objects.values_list('name', flat=True))
    known_ips = set(NewDevice.objects.values_list('ip', flat=True))

    summary = {'total': devs.count(), 'devices': {}, 'unknown_count': 0, 'no_lldp': []}
    DiscoveryRecord.objects.filter(time=xunjian_time).delete()  # 同批次覆盖

    for dev in devs:
        latest = (CheckResult.objects
                  .filter(device=dev.name, command=LLDP_COMMAND)
                  .order_by('-created_at', '-id').first())
        dev_info = {'neighbors': [], 'unknown': []}
        if not latest or not latest.result:
            summary['no_lldp'].append(dev.name)
            summary['devices'][dev.name] = dev_info
            continue
        for nb in _parse_lldp(latest.result):
            is_known = (nb['neighbor'] in known_names) or (nb['neighbor'] in known_ips)
            DiscoveryRecord.objects.create(
                time=xunjian_time, device=dev.name,
                neighbor=nb['neighbor'], neighbor_ip='',
                local_port=nb['local_port'], peer_port=nb['peer_port'],
                is_known=is_known, site=dev.site or '',
            )
            dev_info['neighbors'].append(nb)
            if not is_known:
                dev_info['unknown'].append(nb['neighbor'])
                summary['unknown_count'] += 1
        summary['devices'][dev.name] = dev_info

    logger.info(f'[discovery] 发现 {summary["unknown_count"]} 个未知邻居，'
                f'{len(summary["no_lldp"])} 台无 LLDP 采集')
    return summary


# ───────────────────────── 配置合规 ─────────────────────────
def _eval_rule(rule, output: str) -> (bool, str):
    """返回 (passed, detail)。"""
    if not output:
        return False, '无采集结果'
    pat = rule.pattern or ''
    if rule.rule_type == 'regex':
        ok = bool(re.search(pat, output, re.IGNORECASE))
        return ok, ('' if ok else f'未匹配正则: {pat}')
    if rule.rule_type == 'contains':
        ok = pat in output
        return ok, ('' if ok else f'未包含: {pat}')
    if rule.rule_type == 'absence':
        ok = pat not in output
        return ok, ('' if ok else f'不应出现但却存在: {pat}')
    return True, ''


def run_compliance(site: str = None, xunjian_time: str = None) -> dict:
    """对范围内设备逐策略逐规则评估，写入 ComplianceResult，返回汇总。"""
    from app02.models import NewDevice, CheckResult, CompliancePolicy, ComplianceResult

    xunjian_time = xunjian_time or datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    devs = NewDevice.objects.filter(enabled=True)
    if site:
        devs = devs.filter(site=site)

    policies = CompliancePolicy.objects.filter(enabled=True)
    summary = {'policies': {}, 'violations': 0}
    ComplianceResult.objects.filter(time=xunjian_time).delete()  # 同批次覆盖

    for policy in policies:
        rules = policy.rules.filter(enabled=True)
        policy_stat = {'rules': rules.count(), 'devices': {}, 'violations': 0}
        for dev in devs:
            dev_viol = []
            for rule in rules:
                latest = (CheckResult.objects
                          .filter(device=dev.name, command=rule.source_command)
                          .order_by('-created_at', '-id').first())
                output = latest.result if latest else ''
                passed, detail = _eval_rule(rule, output)
                ComplianceResult.objects.create(
                    time=xunjian_time, device=dev.name,
                    policy=policy.name, rule=rule.name,
                    passed=passed, detail=detail,
                    severity=rule.severity,
                )
                if not passed:
                    dev_viol.append({'rule': rule.name, 'severity': rule.severity, 'detail': detail})
                    policy_stat['violations'] += 1
                    summary['violations'] += 1
            policy_stat['devices'][dev.name] = dev_viol
        summary['policies'][policy.name] = policy_stat

    logger.info(f'[compliance] 评估 {policies.count()} 个策略，发现 {summary["violations"]} 项不合规')
    return summary
