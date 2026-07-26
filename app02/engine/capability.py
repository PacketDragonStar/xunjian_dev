"""能力感知探测 —— v3 opt-in 模型的核心。

设计要点（吸收 v2 硬伤）：
- INCLUDE_TOKENS 单一真源：PROBE_COMMAND 必须由其派生，禁止手写两份
  （避免「include 8 个 token 却 keyword 列一堆死代码」的漂移）。
- 关键字→能力映射仅用「主 token」，严禁 neighbor / vrid / BAGG 这类跨协议易误判词。
- None vs [] 严格区分：None=从未检测（保守）；[]=已检测确无特性。
- capabilities_ts 过期（CAP_STALE_DAYS）自动重探。
- 探测失败不写库、返回旧值/None，由调用方保守兜底（不波及全 fleet）。
"""
import re
import datetime
import logging

from app02.models import NewDevice

logger = logging.getLogger(__name__)

# ── 探针命令：单一真源（INCLUDE_TOKENS → PROBE_COMMAND）──
INCLUDE_TOKENS = [
    'ospf', 'bgp', 'vrrp', 'irf', 'm-lag',
    'remote-backup-group', 'security-zone', 'link-aggregation', 'lacp', 'zone',
]
PROBE_COMMAND = 'display current-configuration | include ' + '|'.join(INCLUDE_TOKENS)

CAP_STALE_DAYS = 7

# 能力 → 命中关键字（仅主 token，避免跨协议误判）
#   m-lag 严禁 neighbor（BGP/OSPF 也用 neighbor）；
#   vrrp 严禁 vrid（不在 include 中）；
#   lacp 弃用 BAGG（用 link-aggregation 主 token + lacp 兜底）。
FEATURE_KEYWORDS = {
    'ospf':     [r'\bospf\b'],
    'bgp':      [r'\bbgp\b'],
    'vrrp':     [r'\bvrrp\b'],
    'irf':      [r'\birf\b', r'\bmember\b'],
    'm-lag':    [r'\bm-lag\b'],
    'rbm':      [r'remote-backup-group'],
    'security': [r'security-zone', r'\bzone\b'],
    'lacp':     [r'link-aggregation', r'\blacp\b'],
}


def _now_iso():
    return datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')


def _is_older_than(ts, days):
    if not ts:
        return True
    try:
        dt = datetime.datetime.strptime(ts, '%Y-%m-%dT%H:%M:%S')
    except Exception:
        return True
    return (datetime.datetime.now() - dt).days >= days


def detect_capabilities(raw):
    """从探针回显解析出能力清单（feature key 列表）。空回显返回 []。"""
    if not raw:
        return []
    caps = []
    for feat, pats in FEATURE_KEYWORDS.items():
        if any(re.search(p, raw, re.I) for p in pats):
            caps.append(feat)
    return caps


def _send_probe(connection):
    """在已建立的连接上发送探针，返回回显文本。"""
    try:
        connection.send_command(
            'screen-length disable',
            expect_string=r'>|\$|#|\]',
            read_timeout=10,
        )
    except Exception:
        pass
    return connection.send_command(PROBE_COMMAND, read_timeout=40)


def ensure_capabilities(device, connection, force=False):
    """确保 device 有最新的 capabilities（用于 opt-in 执行门控 / 检测能力）。

    - connection: 必须传入一个已建立的 netmiko 连接（巡检 worker 内复用；
      管理命令自行建立后传入）。本模块不负责建连，避免循环依赖。
    - 仅在 caps 为 None / 过期 / force 时重新探测并写回 extra。
    - 探测失败：返回已有 caps（None 或旧值），本次不写库，由调用方保守兜底。

    返回：能力列表（可能为空列表 []）或 None（从未检测且本次探测失败）。
    """
    extra = dict(device.extra or {})
    caps = extra.get('capabilities')          # None=从未检测；[]=已检测确无特性
    ts = extra.get('capabilities_ts')
    fresh = (caps is not None) and (not force) and (not _is_older_than(ts, CAP_STALE_DAYS))
    if fresh:
        return caps

    try:
        raw = _send_probe(connection)
        new_caps = detect_capabilities(raw)
    except Exception as e:
        logger.warning(f'[{device.name}] 能力探测失败(本次不写库): {e}')
        return extra.get('capabilities')      # None 或旧值 → 调用方保守兜底

    extra['capabilities'] = new_caps
    extra['capabilities_ts'] = _now_iso()
    device.extra = extra
    try:
        NewDevice.objects.filter(pk=device.pk).update(extra=extra)
    except Exception as e:
        logger.warning(f'[{device.name}] 能力写库失败(仍返回本次探测结果): {e}')
    return new_caps
