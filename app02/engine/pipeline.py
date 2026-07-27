"""巡检引擎 - Pipeline 流水线核心"""
import re
import difflib
import logging
import json

from app02.parsers import parse_device_command, is_parseable

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════

def _safe_json(val, default=None):
    """安全地把 JSONField 值转为 dict（处理字符串存储的 JSON）"""
    if val is None:
        return default or {}
    if isinstance(val, dict):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            return default or {}
    return default or {}


def _safe_float(val, default=None):
    """安全转换为 float，失败返回 default"""
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s:
        return default
    try:
        return float(s)
    except (ValueError, TypeError):
        return default


# ═══════════════════════════════════════════════════════════
# 解析器注册表
# ═══════════════════════════════════════════════════════════

def parse_raw(result: str, config: dict) -> str:
    """原始文本，不做任何处理"""
    return result


def parse_regex(result: str, config: dict):
    """
    正则提取数值
    config: {"pattern": "CPU: (\\d+)%", "group": 1, "cast": "float"}
    """
    pattern = config.get('pattern', '')
    group   = config.get('group', 1)
    cast    = config.get('cast', 'str')
    match   = re.search(pattern, result)
    if not match:
        return None
    try:
        val = match.group(group)
    except (IndexError, AttributeError):
        # group 参数无效时回退到 group 0（完整匹配）
        val = match.group(0)
    # 空字符串视为无匹配
    if not val or str(val).strip() == '':
        return None
    try:
        if cast == 'float':
            return float(val)
        elif cast == 'int':
            return int(val)
        return val
    except (ValueError, TypeError):
        return None


def parse_strip_ts(result: str, config: dict) -> str:
    """
    去除时间戳后的文本
    config: {"patterns": ["\\d{4}-\\d{2}-\\d{2}.*"]}
    """
    text = result
    for pat in config.get('patterns', []):
        text = re.sub(pat, '', text)
    return text


def parse_textfsm(result: str, config: dict):
    """
    TextFSM 模板解析
    config: {"template": "cisco_nxos_show_interface.textfsm"}
    """
    import os
    from django.conf import settings
    from textfsm import TextFSM

    template_name = config.get('template', '')
    template_path = os.path.join(settings.BASE_DIR, 'app02', 'static', 'textfsm_template', template_name)
    try:
        with open(template_path, encoding='utf8') as f:
            template = TextFSM(f)
        return template.ParseTextToDicts(result)
    except Exception as e:
        logger.error(f'TextFSM解析失败: {e}')
        return []


PARSERS = {
    'raw':      parse_raw,
    'regex':    parse_regex,
    'strip_ts': parse_strip_ts,
    'textfsm':  parse_textfsm,
}


# ═══════════════════════════════════════════════════════════
# 字段提取器（用于对比页结构化展示，不影响判定）
# ═══════════════════════════════════════════════════════════

def extract_memory(text: str) -> dict:
    """
    从 `display memory` 输出提取各槽位(Slot)内存指标。
    匹配行如：
        Mem:        506408    360856    145552         0      1420    123424       30.1%
    返回 {'slot1_total_kb':..., 'slot1_free_ratio_%':30.1, 'slot2_...':...}
    """
    out = {}
    if not text:
        return out
    slot = 0
    for line in text.splitlines():
        m = re.match(
            r'\s*Mem:\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+([\d.]+)%',
            line,
        )
        if m:
            slot += 1
            p = f'slot{slot}_'
            out[p + 'total_kb']   = int(m.group(1))
            out[p + 'used_kb']    = int(m.group(2))
            out[p + 'free_kb']    = int(m.group(3))
            out[p + 'shared_kb']  = int(m.group(4))
            out[p + 'buffers_kb'] = int(m.group(5))
            out[p + 'cached_kb']  = int(m.group(6))
            out[p + 'free_ratio_%'] = float(m.group(7))
    return out


EXTRACTORS = {
    'memory': extract_memory,
}



# ═══════════════════════════════════════════════════════════
# 检查器注册表
# ═══════════════════════════════════════════════════════════

def _normalize(text) -> str:
    """标准化文本：合并空白字符"""
    return re.sub(r'\s+', ' ', str(text)).strip()


def check_baseline(parsed, baseline_parsed, config: dict, extra: dict):
    """
    基线文本对比
    config: {"similarity": 1.0}
    """
    if baseline_parsed is None:
        return False, config.get('no_baseline_note', '基线数据不存在，请先设置基线')

    similarity = config.get('similarity', 1.0)
    t1 = _normalize(parsed)
    t2 = _normalize(baseline_parsed)
    ratio = difflib.SequenceMatcher(None, t1, t2).ratio()

    if ratio >= similarity:
        return True, ''
    return False, config.get('note', '与基线不一致，请检查')


def check_threshold(parsed, baseline_parsed, config: dict, extra: dict):
    """
    阈值判断
    config: {"warning": 75, "operator": "<="}
    """
    if parsed is None:
        return False, '采集异常，无法提取数值，请检查'

    value = _safe_float(parsed)
    if value is None:
        return False, f'无法转换为数值: {str(parsed)[:100]}'

    op        = config.get('operator', '<=')
    threshold = float(config.get('warning', 0))

    ops = {
        '<=': lambda a, b: a <= b,
        '<':  lambda a, b: a < b,
        '>=': lambda a, b: a >= b,
        '>':  lambda a, b: a > b,
        '==': lambda a, b: a == b,
    }
    op_func = ops.get(op, lambda a, b: a <= b)
    ok = op_func(value, threshold)
    return ok, '' if ok else config.get('note', f'当前值 {value} 超出阈值 {threshold}')


def check_count(parsed, baseline_parsed, config: dict, extra: dict):
    """
    关键字计数判断
    config: {"keyword": "FULL/", "expected": 9, "expand_field": "ospf_nei"}
    """
    keyword      = config.get('keyword', '')
    expand_field = config.get('expand_field')

    if expand_field and expand_field in extra:
        try:
            expected = int(extra[expand_field])
        except (ValueError, TypeError):
            expected = int(config.get('expected', 0))
    else:
        expected = int(config.get('expected', 0))

    actual = str(parsed).count(keyword)
    if actual == expected:
        return True, ''
    return False, config.get('note', f'"{keyword}" 出现次数应为 {expected}，实际为 {actual}，请检查')


def check_contains(parsed, baseline_parsed, config: dict, extra: dict):
    """
    包含检查：输出必须包含指定字符串
    """
    must_list = config.get('must_contain', [])
    if not must_list and config.get('keyword'):
        must_list = [config.get('keyword')]

    text = str(parsed)
    for keyword in must_list:
        if keyword not in text:
            return False, config.get('note', f'缺少关键字: "{keyword}"，请检查')
    return True, ''


# 自定义函数注册表
_CUSTOM_CHECKERS = {}


def register_checker(name: str):
    """装饰器：注册自定义检查函数"""
    def decorator(func):
        _CUSTOM_CHECKERS[name] = func
        logger.debug(f'注册自定义检查器: {name}')
        return func
    return decorator


def load_checker_overrides():
    """从 CheckerScript 表热加载用户编辑的 checker 覆盖到 _CUSTOM_CHECKERS。
    单用户工具，信任操作者（不强制沙箱）。失败时记录日志并保持文件版。
    应在 app02.custom_checks 导入之后调用（DB覆盖优先于文件版）。"""
    try:
        from app02.models import CheckerScript
    except Exception as e:
        logger.warning(f'load_checker_overrides: 无法导入模型 {e}')
        return
    try:
        from app02.engine.pipeline import register_checker as _reg
    except Exception:
        _reg = None
    try:
        rows = CheckerScript.objects.filter(enabled=True)
    except Exception as e:  # 表尚未建好等情况
        logger.warning(f'load_checker_overrides: 查询失败(忽略) {e}')
        return
    for row in rows:
        try:
            ns = {
                '__name__': f'checker_override_{row.name}',
                're': __import__('re'),
                'json': __import__('json'),
                'math': __import__('math'),
                'datetime': __import__('datetime').datetime,
                'timedelta': __import__('datetime').timedelta,
            }
            # 注入 custom_checks 的私有工具函数（DB checker 源码依赖它们）
            try:
                import app02.custom_checks as _cc
                for _name in ('_parse_log_time', '_MONTH_MAP', '_parse_optic_block',
                              'FLASH_ERROR_PAT', 'BIAS_OFF'):
                    ns[_name] = getattr(_cc, _name, None)
            except Exception:
                pass
            if _reg is not None:
                ns['register_checker'] = _reg
            compiled = compile(row.source, f'<checker:{row.name}>', 'exec')
            exec(compiled, ns)
            fn = ns.get(row.name)
            if not callable(fn):
                for v in ns.values():
                    if callable(v) and getattr(v, '__name__', '').startswith('check_'):
                        fn = v
                        break
            if callable(fn):
                _CUSTOM_CHECKERS[row.name] = fn
                logger.info(f'热加载 checker 覆盖: {row.name} (v{row.version})')
            else:
                logger.error(f'checker 覆盖 {row.name}: 源码中未找到可调用函数')
        except Exception as e:
            logger.error(f'checker 覆盖 {row.name} 加载失败: {e}')


def check_custom(parsed, baseline_parsed, config: dict, extra: dict):
    """
    调用自定义函数
    config: {"func": "my_check_func_name"}
    """
    func_name = config.get('func', '')
    if func_name not in _CUSTOM_CHECKERS:
        return False, f'自定义检查函数 "{func_name}" 未注册，请检查 custom_checks 目录'
    try:
        return _CUSTOM_CHECKERS[func_name](parsed, baseline_parsed, config, extra)
    except Exception as e:
        logger.error(f'自定义检查函数 {func_name} 执行异常: {e}')
        return False, f'检查函数执行异常: {e}'


CHECKERS = {
    'baseline':  check_baseline,
    'threshold': check_threshold,
    'count':     check_count,
    'contains':  check_contains,
    'custom':    check_custom,
}


# ═══════════════════════════════════════════════════════════
# 流水线执行核心
# ═══════════════════════════════════════════════════════════

def run_check_item(connection, check_item, baseline_result: str, device_extra: dict,
                   xunjian_time: str, device_name: str):
    """
    执行单个巡检项的完整流水线

    流程: 执行命令 -> 解析 -> 对比 -> 返回结果

    Returns:
        (result_raw, is_ok, notes)
    """
    # 安全解析 JSON 字段
    p_conf = _safe_json(check_item.parser_config)
    c_conf = _safe_json(check_item.checker_config)

    # 解析器提前定义：任何提前 return 分支（如空输出 + custom）都可能引用 parser，
    # 必须保证在首个分支前已绑定，否则会抛 UnboundLocalError('parser')。
    parser = PARSERS.get(check_item.parser, parse_raw)

    # Step 1: 执行命令
    try:
        result_raw = connection.send_command(
            check_item.command,
            read_timeout=check_item.timeout,
            strip_command=True,
            strip_prompt=True,
        )
    except Exception as e:
        logger.error(f'[{device_name}] 执行命令 "{check_item.command}" 失败: {e}')
        # 注意：必须返回 4 个值（与正常路径一致），否则 executor 的
        # `result_raw, is_ok, notes, structured = run_check_item(...)` 会因
        # 只收到 3 个值而抛 "not enough values to unpack (expected 4, got 3)"，
        # 进而把真实的"命令执行失败"原因掩盖成"采集/落库异常"的误导信息。
        return None, False, f'命令执行失败: {e}', None

    if not result_raw or not result_raw.strip():
        # 空输出：对"自定义检查器"交给其判定（如 check_arp 语义为"无冲突记录=正常"）。
        # 内置 checker（baseline/count 等）空输出仍视为异常，保持原行为，避免误放行。
        if check_item.checker == 'custom':
            parsed = parser('', p_conf)
            if parsed is None:
                return None, False, '设备采集为空，请检查', None
            checker = CHECKERS.get(check_item.checker, check_baseline)
            extra_with_struct = dict(device_extra)
            extra_with_struct['__structured__'] = None
            try:
                is_ok, notes = checker(parsed, None, c_conf, extra_with_struct)
            except Exception as e:
                is_ok, notes = False, f'检查器执行异常: {e}'
            if is_ok:
                # 正常但无内容：返回占位文本，避免被 executor 当"采集为空"异常
                return '(无输出)', True, notes or '', None
            return None, False, notes or '设备采集为空，请检查', None
        return None, False, '设备采集为空，请检查', None

    # Step 2: 解析当前结果（pipeline 后处理层：raw/regex/strip_ts/textfsm，供 checker 判定）
    # 注：parser 已在函数开头绑定，此处直接复用。
    parsed = parser(result_raw, p_conf)

    # 解析结果为 None 说明正则未匹配，直接记为异常
    if parsed is None:
        notes = check_item.error_note or f'解析失败：命令输出与解析器配置不匹配（parser={check_item.parser}），请检查正则表达式'
        return result_raw, False, notes, None

    # Step 2.5（阶段二·采集时一次解析）：用单一真源解析器把 raw 解析为结构化结果，
    # 注入 checker 的 extra['__structured__']，供「结构化检查器」消费（无则走 raw 回退）。
    structured = parse_device_command(check_item.command, result_raw) if is_parseable(check_item.command) else None

    # Step 3: 解析基线（用相同的解析器）
    baseline_parsed = None
    if baseline_result:
        try:
            baseline_parsed = parser(baseline_result, p_conf)
        except Exception as e:
            logger.warning(f'[{device_name}] 基线解析失败: {e}')

    # Step 4: 执行检查（结构化结果随 extra 传入，不改变 raw parsed 的基线对比语义）
    checker = CHECKERS.get(check_item.checker, check_baseline)
    extra_with_struct = dict(device_extra)
    extra_with_struct['__structured__'] = structured
    try:
        is_ok, notes = checker(parsed, baseline_parsed, c_conf, extra_with_struct)
    except Exception as e:
        logger.error(f'[{device_name}] 检查器 {check_item.checker} 执行异常: {e}')
        is_ok, notes = False, f'检查器执行异常: {e}'

    # error_note 作为兜底
    if not is_ok and not notes and check_item.error_note:
        notes = check_item.error_note

    return result_raw, is_ok, notes, structured