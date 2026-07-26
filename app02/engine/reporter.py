# -*- coding: utf-8 -*-
"""报告生成器 - 包括巡检报告和验收报告"""
import re
import difflib
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from collections import defaultdict


# ═══════════════════════════════════════════════════════════
# 基础报告数据模型
# ═══════════════════════════════════════════════════════════

@dataclass
class CheckItemReport:
    """单个巡检项的报告"""
    command:      str
    desc:         str          # 巡检项名称（人可读）
    status:       str          # 'ok' / 'anomaly' / 'error' / 'no_baseline'
    notes:        str = ''
    baseline_val: str = ''     # 基线值摘要
    current_val:  str = ''     # 当前值摘要
    diff_lines:   List[str] = field(default_factory=list)  # diff 行列表
    severity:     str = 'P2'   # P0/P1/P2
    fix_suggestion: str = ''   # 整改建议


@dataclass
class DeviceReport:
    """单台设备的巡检报告"""
    device_name:   str
    device_ip:     str
    status:        str          # 'ok' / 'anomaly' / 'failed'
    total:         int = 0      # 总巡检项数
    ok_count:      int = 0
    anomaly_count: int = 0
    expected:      int = 0      # 本台设备「应执行」的巡检项数（能力门控重算后）
    items:         List[CheckItemReport] = field(default_factory=list)
    connect_error: str = ''


@dataclass
class XunjianReport:
    """完整巡检报告"""
    xunjian_time:    str
    operator:        str
    baseline_time:   str         # 对比的基线时间
    total_devices:   int = 0
    ok_devices:      int = 0
    anomaly_devices: int = 0
    failed_devices:  int = 0
    total_checks:    int = 0
    expected_checks: int = 0   # 实际应执行的巡检项数（含自适应裁剪后每台设备分配到的命令数之和）
    total_anomalies: int = 0
    devices:         List[DeviceReport] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════
# 差异提取函数
# ═══════════════════════════════════════════════════════════

def extract_diff_summary(current: str, baseline: str, max_lines: int = 5) -> tuple:
    """
    提取两段文本的差异摘要
    返回: (current_summary, baseline_summary, diff_lines)
    """
    if not baseline:
        return current[:200] if current else '', '', []

    c_lines = str(current).splitlines()
    b_lines = str(baseline).splitlines()

    diff = list(difflib.unified_diff(
        b_lines, c_lines,
        fromfile='基线', tofile='当前',
        lineterm=''
    ))

    # 提取实际变化的行（去掉 diff 头部）
    changed = [l for l in diff if l.startswith(('+', '-')) and not l.startswith(('+++', '---'))]
    added   = [l for l in changed if l.startswith('+')]
    removed = [l for l in changed if l.startswith('-')]

    current_summary  = '\n'.join(added[:max_lines])   or current[:100]
    baseline_summary = '\n'.join(removed[:max_lines]) or baseline[:100]

    return current_summary, baseline_summary, diff[:50]  # 最多50行diff


def extract_number_change(current_val, baseline_val, label: str = '') -> str:
    """数值变化描述：'75 → 82（增加7）'"""
    try:
        c = float(str(current_val))
        b = float(str(baseline_val))
        delta = c - b
        sign  = '+' if delta > 0 else ''
        return f'{b} → {c}（{sign}{delta:.1f}）'
    except (ValueError, TypeError):
        return f'{baseline_val} → {current_val}'


def extract_count_change(current_text: str, baseline_text: str, keyword: str) -> str:
    """关键字计数变化：'FULL邻居: 9 → 8（减少1）'"""
    c_count = str(current_text).count(keyword)
    b_count = str(baseline_text).count(keyword) if baseline_text else 0
    delta   = c_count - b_count
    if delta == 0:
        return f'"{keyword}" 数量: {c_count}（与基线一致）'
    sign = '+' if delta > 0 else ''
    return f'"{keyword}" 数量: {b_count} → {c_count}（{sign}{delta}）'


# ═══════════════════════════════════════════════════════════
# 报告渲染：文本格式（CLI 输出）
# ═══════════════════════════════════════════════════════════

STATUS_ICON = {
    'ok':          '[正常]',
    'anomaly':     '[异常]',
    'failed':      '[失败]',
    'error':       '[错误]',
    'no_baseline': '[无基线]',
}


def render_cli_report(report: XunjianReport) -> str:
    """渲染 CLI 格式报告（适合终端输出）"""
    lines = []
    sep   = '=' * 60

    lines.append(sep)
    lines.append(f'  巡检报告  {report.xunjian_time}')
    lines.append(f'  操作人: {report.operator}   对比基线: {report.baseline_time or "无基线"}')
    lines.append(sep)
    lines.append('')

    for dev in report.devices:
        icon = STATUS_ICON.get(dev.status, '?')
        if dev.status == 'failed':
            lines.append(f'{icon} {dev.device_name} ({dev.device_ip})')
            lines.append(f'   连接失败: {dev.connect_error}')
        else:
            ok_str = f'{dev.ok_count}/{dev.total}'
            lines.append(
                f'{icon} {dev.device_name} ({dev.device_ip})'
                f'   [{ok_str}]'
                + (f'  发现 {dev.anomaly_count} 处异常' if dev.anomaly_count else '  全部正常')
            )
            for item in dev.items:
                if item.status != 'ok':
                    item_icon = STATUS_ICON.get(item.status, '?')
                    lines.append(f'   {item_icon} [{item.desc}]  {item.command}')
                    if item.notes:
                        lines.append(f'      说明: {item.notes}')
                    if item.baseline_val and item.current_val:
                        lines.append(f'      基线: {item.baseline_val.strip()[:80]}')
                        lines.append(f'      当前: {item.current_val.strip()[:80]}')
                    lines.append('')
        lines.append('')

    lines.append(sep)
    lines.append(
        f'  汇总: 共 {report.total_devices} 台  '
        f'正常 {report.ok_devices} 台  '
        f'异常 {report.anomaly_devices} 台  '
        f'失败 {report.failed_devices} 台  '
        f'共执行 {report.total_checks} 项'
    )
    lines.append(sep)
    return '\n'.join(lines)


def render_html_report(report: XunjianReport) -> str:
    """渲染 HTML 格式报告（嵌入 Django 模板）"""
    rows = []
    for dev in report.devices:
        if dev.status == 'failed':
            badge  = '<span class="badge bg-danger">连接失败</span>'
            detail = f'<small class="text-danger">{dev.connect_error}</small>'
        elif dev.anomaly_count:
            badge      = f'<span class="badge bg-warning text-dark">异常 {dev.anomaly_count} 项</span>'
            items_html = ''
            for item in dev.items:
                if item.status != 'ok':
                    items_html += (
                        f'<div class="ms-3 text-warning">'
                        f'[异常] <b>{item.desc}</b>（{item.command}）<br>'
                        f'<small>{item.notes}</small>'
                    )
                    if item.baseline_val and item.current_val:
                        items_html += (
                            f'<br><small class="text-muted">'
                            f'基线: {item.baseline_val[:60]}  →  '
                            f'当前: {item.current_val[:60]}'
                            f'</small>'
                        )
                    items_html += '</div>'
            detail = items_html
        else:
            badge  = f'<span class="badge bg-success">正常 {dev.ok_count}/{dev.total}</span>'
            detail = ''

        rows.append(
            f'<tr>'
            f'<td>{dev.device_name}</td>'
            f'<td><code>{dev.device_ip}</code></td>'
            f'<td>{badge}</td>'
            f'<td>{detail}</td>'
            f'</tr>'
        )

    return ''.join(rows)


# ═══════════════════════════════════════════════════════════
# 验收报告生成（基于数据库记录）
# ═══════════════════════════════════════════════════════════

def render_acceptance_report(record, anomalies, check_results, devices, site_label='网络巡检'):
    """
    生成验收报告 HTML
    
    Args:
        record: XunjianRecord 对象
        anomalies: AnomalyRecord QuerySet
        check_results: CheckResult QuerySet
        devices: NewDevice QuerySet
        site_label: 站点名（知识城/化龙），用于报告标题
    
    Returns:
        HTML 字符串
    """
    # 1. 建立 设备→{命令→CheckResult} 的映射
    results_map = defaultdict(dict)  # {device_name: {command: result_text}}
    for cr in check_results:
        if cr.result and cr.result.strip():
            results_map[cr.device][cr.command] = cr.result
    
    # 2. 建立 设备→异常列表 的映射
    anomaly_map = defaultdict(list)
    for a in anomalies:
        anomaly_map[a.device].append(a)
    
    # 3. 收集所有涉及的检查项命令
    all_commands_set = set()
    for cr in check_results:
        if cr.result and cr.result.strip():
            all_commands_set.add(cr.command)
    all_commands = sorted(all_commands_set)
    
    # 4. 建立 设备×检查项 矩阵
    matrix = {}  # {device_name: {command: {'status': 'ok'/'anomaly'/'no_data', 'notes': ''}}}
    device_names = sorted(list(results_map.keys()))
    
    for dev_name in device_names:
        if dev_name not in matrix:
            matrix[dev_name] = {}
        for cmd in all_commands:
            if cmd in results_map[dev_name]:
                # 有数据
                dev_anomalies = [a for a in anomaly_map.get(dev_name, []) if a.command == cmd]
                if dev_anomalies:
                    a = dev_anomalies[0]
                    matrix[dev_name][cmd] = {
                        'status': 'anomaly',
                        'notes': a.notes or '',
                        'severity': getattr(a, 'severity', 'P2'),
                        'fix_suggestion': '',
                    }
                else:
                    matrix[dev_name][cmd] = {
                        'status': 'ok',
                        'notes': '',
                        'severity': '',
                        'fix_suggestion': '',
                    }
            else:
                matrix[dev_name][cmd] = {
                    'status': 'no_data',
                    'notes': '',
                    'severity': '',
                    'fix_suggestion': '',
                }
    
    # 5. 统计 KPI
    total_devices = len(device_names)
    ok_devices = sum(1 for d in device_names if d not in anomaly_map)
    anomaly_devices = len(anomaly_map)
    total_anomalies = len(anomalies)
    
    p0_count = len([a for a in anomalies if getattr(a, 'severity', 'P2') == 'P0'])
    p1_count = len([a for a in anomalies if getattr(a, 'severity', 'P2') == 'P1'])
    p2_count = len([a for a in anomalies if getattr(a, 'severity', 'P2') == 'P2'])
    
    # 6. 聚合同类异常（同命令+同异常说明 = 合并）
    grouped_anomalies = defaultdict(list)
    for a in anomalies:
        key = (a.command, a.notes or '')
        grouped_anomalies[key].append(a)
    
    # 7. 构建异常问题清单（聚合后的）
    issues = []
    for (cmd, notes), group in grouped_anomalies.items():
        devices_list = [a.device for a in group]
        severity = getattr(group[0], 'severity', 'P2')
        issues.append({
            'severity': severity,
            'command': cmd,
            'notes': notes,
            'device_count': len(group),
            'devices': devices_list,
            'fix_suggestion': '',
        })
    
    # 按严重级别排序
    issues.sort(key=lambda x: {'P0': 0, 'P1': 1, 'P2': 2}.get(x['severity'], 2))
    
    # 8. 生成 HTML
    return _build_acceptance_html(
        record, total_devices, ok_devices, anomaly_devices,
        total_anomalies, p0_count, p1_count, p2_count,
        matrix, all_commands, device_names, issues, site_label
    )


def _build_acceptance_html(record, total_devices, ok_devices, anomaly_devices,
                            total_anomalies, p0_count, p1_count, p2_count,
                            matrix, all_commands, device_names, issues, site_label='网络巡检'):
    """构建验收报告 HTML"""
    # 合规率
    if total_devices > 0:
        compliance_rate = round(ok_devices / total_devices * 100, 1)
    else:
        compliance_rate = 100
    
    # 简化命令名显示
    short_cmds = {cmd: cmd.replace('display ', '').replace('all-vpn-instance', 'all-vpn')[:20] for cmd in all_commands}
    
    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{site_label}网络巡检验收报告</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0;font-family:"Microsoft YaHei","PingFang SC",sans-serif}}
body{{background:#f4f6f9;color:#2c3e50;line-height:1.5}}
.wrap{{max-width:1400px;margin:0 auto;padding:24px}}
header{{background:linear-gradient(135deg,#1e3c72,#2a5298);color:#fff;padding:30px 32px;border-radius:14px;margin-bottom:22px}}
header h1{{font-size:24px;margin-bottom:6px}}
header .sub{{opacity:.85;font-size:14px}}
.kpis{{display:flex;gap:16px;flex-wrap:wrap;margin:22px 0}}
.kpi{{flex:1;min-width:180px;background:#fff;border-radius:12px;padding:18px 20px;box-shadow:0 2px 10px rgba(0,0,0,.06)}}
.kpi .n{{font-size:30px;font-weight:700}}.kpi .l{{color:#7f8c8d;font-size:13px;margin-top:4px}}
.sec{{background:#fff;border-radius:14px;padding:22px 24px;margin-bottom:22px;box-shadow:0 2px 10px rgba(0,0,0,.06)}}
.sec h2{{font-size:18px;margin-bottom:16px;padding-left:12px;border-left:4px solid #2a5298}}
.summary{{font-size:14px;color:#34495e;background:#eef6ff;border-left:4px solid #2a5298;padding:14px 18px;border-radius:8px;margin-bottom:8px}}
table{{width:100%;border-collapse:collapse;font-size:11px}}
th,td{{border:1px solid #e5e9f0;padding:5px 6px;text-align:center;vertical-align:top}}
th{{background:#f0f4fa;font-weight:600;font-size:11px}}
tr:nth-child(even) td{{background:#fafbfd}}
.sev{{color:#fff;padding:2px 9px;border-radius:10px;font-size:11px}}
.issue-box{{background:#fff8f4;border:1px solid #f5c6a5;border-radius:12px;padding:18px 22px;margin-bottom:22px}}
.cell-ok{{background:#d4edda!important;color:#155724;font-weight:600}}
.cell-fail{{background:#f8d7da!important;color:#721c24;font-weight:600}}
.cell-no-data{{background:#f8f9fa!important;color:#adb5bd}}
.cell-header{{font-size:10px;white-space:nowrap;transform:rotate(-90deg);height:100px;width:30px}}
.legend{{font-size:12px;color:#95a5a6;margin-top:6px;display:flex;gap:16px}}
.matrix-wrap{{overflow:auto;max-height:70vh}}
</style>
</head>
<body>
<div class="wrap">
<header>
    <h1>{site_label}网络巡检验收报告</h1>
    <div class="sub">巡检时间: {record.time} · 操作人: {record.operator} · 基线时间: {getattr(record, 'baseline_time', '首次巡检')}</div>
</header>

<div class="kpis">
    <div class="kpi"><div class="n">{total_devices}</div><div class="l">巡检设备总数</div></div>
    <div class="kpi"><div class="n" style="color:#27ae60">{ok_devices}</div><div class="l">正常设备数</div></div>
    <div class="kpi"><div class="n" style="color:{'#27ae60' if compliance_rate >= 90 else '#e67e22'}">{compliance_rate}%</div><div class="l">设备合规率</div></div>
    <div class="kpi"><div class="n" style="color:{'#27ae60' if anomaly_devices == 0 else '#e74c3c'}">{anomaly_devices}</div><div class="l">异常设备数</div></div>
</div>

<div class="kpis">
    <div class="kpi"><div class="n" style="color:#e74c3c">{p0_count}</div><div class="l">P0-高危</div></div>
    <div class="kpi"><div class="n" style="color:#f39c12">{p1_count}</div><div class="l">P1-中危</div></div>
    <div class="kpi"><div class="n" style="color:#95a5a6">{p2_count}</div><div class="l">P2-低危</div></div>
    <div class="kpi"><div class="n" style="color:#3498db">{total_anomalies}</div><div class="l">总异常项</div></div>
</div>

<div class="summary"><b>总体结论：</b>本次巡检覆盖 {total_devices} 台设备，执行 {len(all_commands)} 项检查。{ok_devices}/{total_devices} 台设备无明显异常。发现 P0 高危 {p0_count} 项、P1 中危 {p1_count} 项、P2 低危 {p2_count} 项，详情见下方问题清单。</div>

<div class="sec">
    <h2>一、设备 × 检查项矩阵</h2>
    <div class="matrix-wrap">
    <table>
    <tr>
        <th style="position:sticky;left:0;background:#f0f4fa;z-index:2">设备</th>
'''
    for cmd in all_commands:
        html += f'<th class="cell-header">{short_cmds.get(cmd, cmd[:15])}</th>'
    html += '</tr>\n'
    
    for dev_name in device_names:
        html += f'<tr><td style="text-align:left;position:sticky;left:0;background:#fff;font-weight:600">{dev_name[:30]}</td>'
        for cmd in all_commands:
            status = matrix[dev_name][cmd]['status']
            if status == 'ok':
                html += '<td class="cell-ok">✅</td>'
            elif status == 'anomaly':
                html += '<td class="cell-fail">❌</td>'
            else:
                html += '<td class="cell-no-data">-</td>'
        html += '</tr>\n'
    
    html += '''</table></div>
    <div class="legend"><span>✅ 正常</span> <span>❌ 异常</span> <span>- 无数据</span></div>
</div>
'''
    
    # 问题清单
    if issues:
        html += '<div class="issue-box"><h2 style="color:#c0392b;margin-bottom:12px">二、问题清单与整改建议</h2><table>'
        html += '<tr><th>等级</th><th>巡检项</th><th>异常说明</th><th>影响设备数</th><th>涉及设备</th><th>整改建议</th></tr>'
        for issue in issues:
            sev = issue['severity']
            sev_color = {'P0': '#e74c3c', 'P1': '#f39c12', 'P2': '#95a5a6'}.get(sev, '#95a5a6')
            html += f'''<tr>
                <td><span class="sev" style="background:{sev_color}">{sev}</span></td>
                <td>{issue['command']}</td>
                <td>{issue['notes']}</td>
                <td>{issue['device_count']}</td>
                <td>{", ".join(issue['devices'][:3])}{"..." if issue["device_count"] > 3 else ""}</td>
                <td>{issue["fix_suggestion"] or "请手工排查"}</td>
            </tr>'''
        html += '</table></div>'
    
    html += f'''</div></body></html>'''
    return html