# -*- coding: utf-8 -*-
"""一次性修改 custom_checks.py：双重验证 + 简化 checker + 追加 check_transceiver"""
with open('app02/custom_checks.py', 'r', encoding='utf-8') as f:
    content = f.read()

# ---- 1. check_fan: 双重验证 ----
old = "@register_checker('check_fan')\ndef check_fan(parsed, baseline, cfg, extra):\n    \"\"\"风扇状态：存在 Abnormal / Fault 即异常（Normal 视为正常）\"\"\"\n    if re.search(r'\\b(Abnormal|Fault)\\b', parsed or '', re.I):\n        return False, '存在风扇异常状态(Abnormal/Fault)'\n    return True, ''"
new = "@register_checker('check_fan')\ndef check_fan(parsed, baseline, cfg, extra):\n    \"\"\"风扇状态：双重验证——至少1个Normal且无异常关键字；采集为空时报异常，避免漏检。\"\"\"\n    text = parsed or ''\n    normal_count = len(re.findall(r'\\bNormal\\b', text, re.I))\n    if normal_count == 0:\n        return False, '风扇状态采集为空或无Normal（可能采集失败或全部异常）'\n    if re.search(r'\\b(Abnormal|Fault)\\b', text, re.I):\n        bad = re.findall(r'Fan\\s*\\d+[^\\n]*?(?:Abnormal|Fault)', text, re.I)\n        return False, f'存在风扇异常状态: {\" / \".join(bad[:3])}'\n    return True, ''"
content = content.replace(old, new)

# ---- 2. check_power: 双重验证 ----
old = "@register_checker('check_power')\ndef check_power(parsed, baseline, cfg, extra):\n    \"\"\"电源状态：Normal 正常；Abnormal/Fault/Failed/Off 异常\"\"\"\n    if re.search(r'\\b(Abnormal|Fault|Failed|Off)\\b', parsed or '', re.I):\n        return False, '存在电源异常状态(Abnormal/Fault/Failed/Off)'\n    return True, ''"
new = "@register_checker('check_power')\ndef check_power(parsed, baseline, cfg, extra):\n    \"\"\"电源状态：双重验证——至少1个Normal且无异常关键字\"\"\"\n    text = parsed or ''\n    normal_count = len(re.findall(r'\\bNormal\\b', text, re.I))\n    if normal_count == 0:\n        return False, '电源状态采集为空或无Normal（可能采集失败或全部异常）'\n    if re.search(r'\\b(Abnormal|Fault|Failed|Off)\\b', text, re.I):\n        bad = re.findall(r'Power\\s*\\d+[^\\n]*?(?:Abnormal|Fault|Failed|Off)', text, re.I)\n        return False, f'存在电源异常状态: {\" / \".join(bad[:3])}'\n    return True, ''"
content = content.replace(old, new)

# ---- 3. check_device: 双重验证 ----
old = "@register_checker('check_device')\ndef check_device(parsed, baseline, cfg, extra):\n    \"\"\"单板/部件状态：State 列 Normal 正常；Fault/Abnormal 异常\"\"\"\n    if re.search(r'\\b(Fault|Abnormal)\\b', parsed or '', re.I):\n        return False, '存在单板/部件异常状态(Fault/Abnormal)'\n    return True, ''"
new = "@register_checker('check_device')\ndef check_device(parsed, baseline, cfg, extra):\n    \"\"\"单板状态：双重验证——至少1个Normal且无异常关键字\"\"\"\n    text = parsed or ''\n    normal_count = len(re.findall(r'\\bNormal\\b', text, re.I))\n    if normal_count == 0:\n        return False, '单板状态采集为空或无Normal（可能采集失败或全部异常）'\n    if re.search(r'\\b(Fault|Abnormal)\\b', text, re.I):\n        bad = re.findall(r'Slot\\s*\\d+[^\\n]*?(?:Fault|Abnormal)', text, re.I)\n        return False, f'存在单板异常状态: {\" / \".join(bad[:3])}'\n    return True, ''"
content = content.replace(old, new)

# ---- 4. check_ifbrief: 简化（接口用 baseline 对比）
old = "@register_checker('check_ifbrief')\ndef check_ifbrief(parsed, baseline, cfg, extra):"
old_end = "    return True, ''"
s1 = content.find(old)
s2 = content.find('\n@register_checker', s1 + len('@register_checker(''check_ifbrief'')'))
if s1 != -1 and s2 != -1:
    content = content[:s1] + old + '\n    """接口概要：辅助检查——保证输出非空。接口变化详情由 baseline checker 面板对比。在实际巡检中建议直接使用 checker=baseline 替代此 checker 进行全量对比。"""\n    text = parsed or ""\n    if not text.strip():\n        return False, "接口输出为空（采集失败）"\n    return True, ""\n' + content[s2:]

# ---- 5. check_routing_table: 简化（路由表用 baseline 对比） + 命令改为 all-vpn-instance
old = "@register_checker('check_routing_table')"
s1 = content.find(old)
s2 = content.find('\n@register_checker', s1 + len(old))
if s1 != -1 and s2 != -1:
    content = content[:s1] + "@register_checker('check_routing_table')\ndef check_routing_table(parsed, baseline, cfg, extra):\n    \"\"\"路由表检查：A类基线对比。\n    推荐采集命令：display ip routing-table all-vpn-instance。\n    此 checker 仅做辅助：保证输出非空。\"\"\"\n    text = parsed or ''\n    if not text.strip():\n        return False, '路由表输出为空（采集失败）'\n    return True, ''\n" + content[s2:]

# ---- 6. 追加 check_transceiver
if 'check_transceiver' not in content:
    transceiver_code = '''
@register_checker('check_transceiver')
def check_transceiver(parsed, baseline, cfg, extra):
    """光模块收发光诊断：当前值 vs 告警阈值（High/Low），越限即异常。
    
    hp_comware V7 输出格式：
        Ten-GigabitEthernet1/0/49 transceiver diagnostic information:
          Current diagnostic parameters:
            Temp.(C) Voltage(V)  Bias(mA)  RX power(dBm)  TX power(dBm)  
            29         3.31        6.84      -3.51          -2.38          
          Alarm thresholds:
            Temp.(C) Voltage(V)  Bias(mA)  RX power(dBm)  TX power(dBm)  
            High  73         3.80        16.50     1.00           1.00           
            Low   -3         2.81        1.00      -11.90         -10.30         
    """
    text = parsed or ''
    errors = []
    pattern = re.compile(
        r'(\\S+)\\s+transceiver diagnostic information:'
        r'.*?Current diagnostic parameters:\\s*\\n\\s*Temp.*?\\n\\s+([\\d\\s\\.\\-]+)'
        r'.*?Alarm thresholds:\\s*\\n\\s+Temp.*?\\n\\s+High\\s+([\\d\\s\\.\\-]+)\\n\\s+Low\\s+([\\d\\s\\.\\-]+)',
        re.DOTALL)
    for m in pattern.finditer(text):
        intf = m.group(1)
        try:
            currs = [float(v) for v in m.group(2).split()]
            highs = [float(v) for v in m.group(3).split()]
            lows = [float(v) for v in m.group(4).split()]
        except (ValueError, IndexError):
            continue
        if len(currs) < 5 or len(highs) < 5 or len(lows) < 5:
            continue
        labels = ['Temp', 'Voltage', 'Bias', 'RX(dBm)', 'TX(dBm)']
        for i, label in enumerate(labels):
            if currs[i] < lows[i]:
                errors.append(f'{intf} {label}={currs[i]} < Low={lows[i]}')
            elif currs[i] > highs[i]:
                errors.append(f'{intf} {label}={currs[i]} > High={highs[i]}')
    if errors:
        return False, f'{len(errors)}项异常: ' + '; '.join(errors[:5])
    return True, ''
'''
    content += transceiver_code

with open('app02/custom_checks.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('OK: custom_checks.py updated')
print('  check_fan/power/device: 双重验证（Normal>=1 + 无异常关键字）')
print('  check_ifbrief: 辅助 checker（建议用 baseline 替代）')
print('  check_routing_table: 辅助 checker（建议用 baseline + all-vpn-instance）')
print('  check_transceiver: 新增（光模块收发光诊断）')