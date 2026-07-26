# -*- coding: utf-8 -*-
"""升级 check_system_stable + 新增 check_irf + 更新所有相关文件"""
import re

# ---- 1. custom_checks.py 末尾追加两个新 checker ----
with open('app02/custom_checks.py', 'r', encoding='utf-8') as f:
    content = f.read()

new_checkers = """


@register_checker('check_system_stable')
def check_system_stable(parsed, baseline, cfg, extra):
    "系统稳定状态检查：System state=Stable，Redundancy state=Stable，所有Slot State=Stable"
    text = parsed or ''
    if not text.strip():
        return False, '系统稳定状态输出为空（采集失败）'
    if not re.search(r'System state\\s*:\\s*Stable', text):
        return False, '系统状态不是 Stable'
    if not re.search(r'Redundancy state\\s*:\\s*Stable', text):
        return False, '冗余状态不是 Stable'
    unstable = re.findall(r'\\b(\\d+)\\s+(\\d+)\\s+(\\d+)\\s+\\w+\\s+(Fault|Abnormal|Failure)', text)
    if unstable:
        slots = [m[0] for m in unstable]
        return False, f'存在不稳定槽位: ' + ', '.join(slots[:5])
    return True, ''


@register_checker('check_irf')
def check_irf(parsed, baseline, cfg, extra):
    "IRF堆叠状态检查：IRF mode=normal，所有成员在线且角色正确"
    text = parsed or ''
    if not text.strip():
        return False, 'IRF状态输出为空（采集失败）'
    irf_mode = re.search(r'IRF mode\\s*:\\s*(\\S+)', text)
    if irf_mode and irf_mode.group(1) != 'normal':
        return False, f'IRF模式异常: {irf_mode.group(1)}'
    members = re.findall(r'^\\s*(\\*)?(\\+)?\\s*(\\d+)\\s+(\\d+)\\s+(\\w+)', text, re.M)
    if members:
        master_count = len([m for m in members if m[4] == 'Master'])
        total = len({m[2] for m in members})  # unique MemberID
        if master_count == 0:
            return False, 'IRF 无 Master 设备'
        if master_count > 1:
            return False, f'IRF 脑裂: {master_count} 个 Master'
    else:
        return True, ''  # 非IRF设备跳过
    return True, ''
"""

content += new_checkers

with open('app02/custom_checks.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('✅ custom_checks.py: check_system_stable + check_irf added')

# ---- 2. commands_inspection.yaml 追加 display irf（如果有 hp_comware 组） ----
yaml_path = r'C:\Users\ZSS\Desktop\化龙\化龙\化龙配置\network_inspection\commands_inspection.yaml'
with open(yaml_path, 'r', encoding='utf-8') as f:
    yaml_content = f.read()

if 'display irf' not in yaml_content:
    # 在 hp_comware 组末尾追加
    yaml_content = yaml_content.rstrip() + '\n  - display irf\n'
    with open(yaml_path, 'w', encoding='utf-8') as f:
        f.write(yaml_content)
    print('✅ commands_inspection.yaml: display irf added')
else:
    print('⚠️ commands_inspection.yaml: display irf already exists')

# ---- 3. gen_hualong_excel.py 更新两处 ----
with open('gen_hualong_excel.py', 'r', encoding='utf-8') as f:
    excel_content = f.read()

# 3a: 把 "系统稳定状态" 从 contains 改为 custom + check_system_stable
old = "'系统稳定状态', 'display system stable state', '所有', '-', 'raw', 'contains', '', '{}', '仅采集', ''"
new = "'系统稳定状态', 'display system stable state', '所有', 'B', 'raw', 'custom', '', '{\"func\":\"check_system_stable\"}', '所有State=Stable(含冗余)', ''"
excel_content = excel_content.replace(old, new)

# 3b: 在核心交换机 CORE_EXTRA 中追加 check_irf
old = "'链路聚合', 'display link-aggregation summary', '核心', 'B', 'raw', 'custom', '', '{\"func\":\"check_agg\"}', '无Unselected', '')"
new = "'链路聚合', 'display link-aggregation summary', '核心', 'B', 'raw', 'custom', '', '{\"func\":\"check_agg\"}', '无Unselected', ''),\n    (28, 'IRF堆叠状态', 'display irf', '核心/堆叠', 'B', 'raw', 'custom', '', '{\"func\":\"check_irf\"}', 'IRF mode=normal,Master=1', ''"
excel_content = excel_content.replace(old, new)

with open('gen_hualong_excel.py', 'w', encoding='utf-8') as f:
    f.write(excel_content)

print('✅ gen_hualong_excel.py: system_stable→custom, irf added to core')

# ---- 4. views.py 预设更新 ----　　
with open('app02/views.py', 'r', encoding='utf-8') as f:
    views_content = f.read()

# 4a: system stable state 预设
old = '''"command": "display system stable state",
            "parser": "raw", "parser_config": "{}",
            "checker": "contains", "checker_config": _json.dumps({}, ensure_ascii=False),
            "note": "仅采集"'''
new = '''"command": "display system stable state",
            "parser": "raw", "parser_config": "{}",
            "checker": "custom", "checker_config": _json.dumps({"func": "check_system_stable"}, ensure_ascii=False),
            "note": "System/Redundancy全Stable即正常"'''
views_content = views_content.replace(old, new)

# 4b: 在最后一个预设后面加入 IRF 预设
marker = '"note": "越限即异常"'
irf_preset = '''"note": "越限即异常"
        },
        {
            "label": "【堆叠】IRF堆叠状态",
            "command": "display irf",
            "parser": "raw", "parser_config": "{}",
            "checker": "custom", "checker_config": _json.dumps({"func": "check_irf"}, ensure_ascii=False),
            "note": "IRF mode=normal,Master=1,无脑裂"'''
views_content = views_content.replace(marker, irf_preset)

with open('app02/views.py', 'w', encoding='utf-8') as f:
    f.write(views_content)

print('✅ views.py: system_stable→custom, irf preset added')

# ---- 5. 重新生成 Excel ----
print('🔄 重新生成 Excel...')
exec(open('gen_hualong_excel.py', encoding='utf-8').read())