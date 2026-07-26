# 阶段 B · 单引擎重建实施方案与测试用例

> **范围说明**：本方案取代《阶段B_收敛双引擎_详细实施方案.md》。
> 用户决策（已确认）：**直接用单引擎、全面拥抱新巡检系统、摒弃旧逻辑**，巡检命令以**知识城 / 化龙真实设备清单**为准；判定粒度=**采集+完整规则**；旧引擎代码与旧表**彻底删除**。

---

## 0. 背景与决策

原方案 B 是"双引擎逐步收敛"，但用户已改为"单引擎重建"——不再保留旧引擎做回退，而是以新引擎为唯一路径，并用知识城/化龙清单里的真实命令重建巡检项。这意味着：

- 旧 `xunjian.py` / `methon/test1.py` / 旧表（`device_table` 等）/ `ConfigBackup`：**整体删除**。
- 巡检命令来源：知识城 76 台 + 化龙 26 台 = **102 台 hp_comware** 设备清单（含每设备巡检命令）。
- 判定：每条命令既采集存档，又按规则自动判定异常（CPU/内存阈值、风扇/电源/接口状态、协议邻居数等）。

---

## 1. 现状盘点（基于真实代码，带定位）

### 1.1 设备与命令事实（来自 Excel）
- 文件：`C:/Users/ZSS/Desktop/化龙/化龙/化龙配置/network_inspection/知识城设备清单_带巡检命令.xlsx`、`化龙设备清单_带巡检命令.xlsx`
- 共 **102 台**，设备类型全部 `hp_comware`，连接方式全部 `ssh`，用户名 `wocloud-gdgz`。
- 连接参数特征：**端口默认 22，但化龙防火墙 `fw001...hualong.xc` 端口为 8022**；`enable密码`/`SSH密钥` 样本均为空。→ 连接层必须支持 `port`，其余可留扩展位。
- 命令按设备名前缀聚成 **5 套模板**（同一前缀命令集高度一致）：

| 模板 | 角色 | 数量(知识城/化龙) | 命令数 | 特征命令 |
|------|------|-------------------|--------|----------|
| **FW**  | 防火墙(fw*) | 12 / 8 = 20 | 15 | zone / security-policy / rbm / session table / vrrp |
| **CSW** | 核心交换(csw*) | 6 / 2 = 8 | 18 | ospf peer / bgp peer / vrrp / nqa / track |
| **ASW** | 接入交换(asw*) + idc/oas/psw/usw | 36+6+5+9+2 / 6+4+3 = 71 | 13 | stp / vlan / link-aggregation / arp conflict |
| **LSW** | 轻交换(dci/dsw) | 0+1+1 / = 2 | 11 | 同 ASW 但无 arp |
| **SRP** | 业务路由(srp*) | 0 / 1 = 1 | 11 | bgp peer / ospf peer / ip routing |

> 说明：idc/oas/psw/usw 的命令集与 ASW 完全一致，统一归入 **ASW 模板**；dci/dsw 无 arp 命令，归入 **LSW 模板**。最终**只需 5 套命令模板 + 5 个 DeviceGroup**。

### 1.2 新引擎数据模型（`app02/models.py`）
- `NewDevice`（L169）：`name / ip / group(FK DeviceGroup) / device_type / username / password / extra(JSON) / enabled`。
  - **缺口**：无 `conn_type / port / enable_password / ssh_key_file` → 化龙 8022 防火墙连不上。
- `DeviceGroup`（L151）：`name / check_items(M2M CheckItem)`。
- `CheckItem`（L197）：`name / command / parser / parser_config(JSON) / checker / checker_config(JSON) / error_note / timeout / enabled`。
  - `PARSER_CHOICES`=raw/regex/strip_ts/textfsm；`CHECK_TYPE_CHOICES`=baseline/threshold/count/contains/custom。
- `CheckSet`（L269）：M2M `groups` → DeviceGroup。
- `CheckResult`(L238) / `AnomalyRecord`(L252)：结果落库。

### 1.3 命令挂载路径（`app02/engine/executor.py`）
- `run_xunjian`（L203）：按 `device_ids` → `checkset.groups` → 全部启用设备；`prefetch_related('group__check_items')`。
- `_get_items_for_device`（L267）：`device.group.check_items.filter(enabled=True)`。
- → **"按角色模板"天然成立**：设备归入对应角色 Group，Group 绑定该角色 CheckItem 即可。

### 1.4 检查器实现（`app02/engine/pipeline.py`）—— 测试用例基于此
- `check_threshold`（L106）：`config={warning, operator}`；`parsed` 为数值；operator 默认 `<=`。
- `check_contains`（L152）：`config={must_contain:[...]}` 或 `{keyword}`；**均缺失 → `(True,'')` 即恒正常（纯采集）**。
- `check_count`（L130）：`config={keyword, expected, expand_field}`；`expand_field` 从 `extra` 取期望值。
- `check_baseline`（L88）：`config={similarity}`；difflib 相似度比对。
- `check_custom`（L191）：`config={func}` → 调 `_CUSTOM_CHECKERS[name]`；`@register_checker(name)` 装饰器（L174）注册。
- `run_check_item`（L219）：`connection.send_command(cmd, read_timeout, expect_string=r'>|\$|#|\]')`；空输出/解析 None/命令失败均有明确返回。

### 1.5 连接层缺口（`app02/engine/executor.py` L82-93）
当前 `ConnectHandler` 仅传 `device_type/ip/username/password/conn_timeout=30/fast_cli=False/global_delay_factor=2`：
- ❌ 不支持 `port`（化龙 8022 防火墙失败）
- ❌ 不支持 `enable_password(secret)` / `ssh_key_file(use_keys)`
- ❌ 不支持 `conn_type=telnet`
- ❌ **未发送关分页预命令** → `display logbuffer` / `display interface brief` 等会触发 `--More--` 卡死或只采到首屏
- 对照可跑的 `化龙/.../inspection.py`：它连上后先发 `screen-length disable`，且按 `device_type` 选驱动、带 `port`/`secret`/`key_file`。

---

## 2. 目标与范围

**目标**：以内网 102 台 hp_comware 设备为唯一巡检对象，用新引擎重建巡检项（5 套角色模板），实现"采集+完整规则"自动判定，并彻底删除旧引擎，使系统成为单引擎。

**不做**（依用户边界）：安全加密/HTTPS（内网）、告警推送（邮件/IM）、定时调度（手动触发）、自动设备发现（名单已给定）。

---

## 3. 数据模型设计

### 3.1 `NewDevice` 扩展字段（`models.py` L169）
```python
conn_type      = models.CharField(verbose_name='连接方式', max_length=10,
                                   choices=[('ssh','SSH'),('telnet','Telnet')], default='ssh')
port           = models.IntegerField(verbose_name='端口', null=True, blank=True)
enable_password = models.CharField(verbose_name='enable密码', max_length=64, blank=True, default='')
ssh_key_file   = models.CharField(verbose_name='SSH密钥路径', max_length=255, blank=True, default='')
role           = models.CharField(verbose_name='角色', max_length=10, blank=True,
                                   help_text='fw/csw/asw/lsw/srp，由设备名前缀推导')
site           = models.CharField(verbose_name='站点', max_length=20, blank=True,
                                   help_text='知识城/化龙')
```
> 迁移：`makemigrations app02` 生成（如 `0014_newdevice_conn.py`）。`role/site` 也可存 `extra`，但独立字段便于仪表盘按站点分组统计，故显式建字段。

### 3.2 5 套角色命令模板 → `DeviceGroup` + `CheckItem`
- 建 5 个 `DeviceGroup`：`GRP-FW / GRP-CSW / GRP-ASW / GRP-LSW / GRP-SRP`。
- 每套命令建成一组 `CheckItem`（全局只建一次，设备入组即套用）。
- 建 1 个全量 `CheckSet`（绑定全部 5 个 Group）+ 可按站点拆 2 个。

### 3.3 完整规则配置（每条命令的 parser/checker）
下表为落地规格（regex 以 hp_comware V7 输出为准，实际接入后微调）：

**FW 模板（15 项）**
| 命令 | parser | checker | checker_config | 说明 |
|------|--------|---------|----------------|------|
| display cpu-usage | regex `(?i)cpu usage:\s*(\d+)%` g1 float | threshold | `{warning:80, operator:'<'}` | <80% 正常 |
| display memory | regex `(?i)memory(?: usage\| using percentage):\s*(\d+)%` g1 float | threshold | `{warning:85, operator:'<'}` | |
| display environment | raw | custom | `{func:'check_env'}` | 温度阈值+无 Fault |
| display fan | raw | custom | `{func:'check_fan'}` | 全部 Normal |
| display power | raw | custom | `{func:'check_power'}` | 全部 Normal |
| display device | raw | custom | `{func:'check_device'}` | 无 Fault/Abnormal |
| display interface brief | raw | custom | `{func:'check_ifbrief', expand_field:'down_ok'}` | DOWN 口数≤预期 |
| display logbuffer | raw | contains | `{}` | 纯采集 |
| display zone | raw | contains | `{}` | 纯采集 |
| display security-policy statistics | raw | contains | `{}` | 纯采集 |
| display security-policy ip rule all | raw | contains | `{}` | 纯采集 |
| display rbm | raw | contains | `{}` | 纯采集 |
| display ip routing-table | raw | contains | `{}` | 纯采集 |
| display session table ipv4 | raw | contains | `{}` | 纯采集 |
| display vrrp brief | raw | custom | `{func:'check_vrrp', expand_field:'vrrp_master'}` | Master 数=预期 |

**CSW 模板（18 项）**：基础 7 项同 FW（cpu/mem/env/fan/power/device/ifbrief）+ `logbuffer`(采集) + `ospf peer`(count `Full`, expand `ospf_nei`) + `bgp peer`(count `Established`, expand `bgp_nei`) + `vrrp brief`(custom) + `stp brief`(采集) + `vlan brief`(采集) + `link-aggregation summary`(custom `check_agg`) + `ip routing-table`(采集) + `nqa result`(custom `check_nqa`) + `track`(采集) + `arp user-ip-conflict record`(custom `check_arp`)。

**ASW 模板（13 项）**：基础 7 项 + `logbuffer` + `stp brief` + `vlan brief` + `link-aggregation summary`(custom) + `ip routing-table` + `arp user-ip-conflict record`(custom)。

**LSW 模板（11 项）**：同 ASW 但**不含** `arp user-ip-conflict record`。

**SRP 模板（11 项）**：基础 7 项（device 用 check_device）+ `logbuffer` + `ip routing-table` + `bgp peer`(count) + `ospf peer`(count)。

> 自定义检查器统一放在 `app02/custom_checks.py`（被 `executor.py` L229 `import app02.custom_checks` 自动加载）。

---

## 4. 连接层升级（`executor._xunjian_one_device` L82-93）

改造后连接构建（对齐 `inspection.py` 健壮性）：
```python
dtype = _normalize_device_type(device.device_type)
kwargs = dict(
    device_type=('hp_comware_telnet' if device.conn_type == 'telnet' else dtype),
    ip=device.ip,
    username=device.username,
    password=device.password,
    conn_timeout=30, fast_cli=False, global_delay_factor=2,
)
if device.port:            kwargs['port'] = device.port
if device.enable_password: kwargs['secret'] = device.enable_password
if device.ssh_key_file:    kwargs.update(use_keys=True, key_file=device.ssh_key_file)
connection = ConnectHandler(**kwargs)
# 关分页（hp_comware）
connection.send_command('screen-length disable', expect_string=r'>|\$|#|\]', read_timeout=10)
```
- 超时：单命令 `read_timeout` 沿用 `CheckItem.timeout`（默认 30）。
- 异常：连接失败已写 `AnomalyRecord` 并标 `failed`（L95-106），保留。

---

## 5. seed_inspection 管理命令

新建 `app02/management/commands/seed_inspection.py`，**幂等**：
1. 内置 5 套角色命令模板（命令 + parser/checker 配置，见 §3.3），用 `get_or_create` 建 `CheckItem`（以 `command` 为唯一键）。
2. `get_or_create` 建 5 个 `DeviceGroup`，`group.check_items.set([...])`（幂等）。
3. `get_or_create` 建全量 `CheckSet`（及按站点 2 个），`checkset.groups.set([...])`。
4. 读两个 Excel：按设备名前缀推导 `role`（fw→FW, csw→CSW, asw/idc/oas/psw/usw→ASW, dci/dsw→LSW, srp→SRP），`site` 取文件名，写入 `NewDevice`（`conn_type/port/enable_password/ssh_key_file` 来自清单），`group` 指向对应 Group。
5. 重复执行：设备以 `name` 唯一，`get_or_create` 不重复；命令/分组同理。
6. 打印汇总：建/更新设备数、各 Group 命令项数。

> 自定义检查器 `custom_checks.py` 与 `seed` 一起入库，命令即用。

---

## 6. 彻底删除旧引擎

**删除清单**（全仓 grep 验证引用=0）：
- 代码：`app02/xunjian.py`、`app02/methon/test1.py`（1871 行）、`app02/methon/` 目录。
- 视图：`views.py` 的 `info_xunjian` / `info_xunjiantest` / `import_functions_from_package`（及 `configBackup`/`logBackup` 相关视图）。
- URL：`urls.py` 的 `/info/xunjian/`、`/info/xunjiantest/`、`import_functions_from_package` 等旧路由。
- 模型：`device_table` / `result_specific_table` / `result_notes_table` / `result_overall_table` / `function_table` / `function_group_relationship_table` / `group_table` / `device_group_relationship_table` / `ConfigBackup`（L57-72，FK 指向旧 `device_table`）。
- 根脚本：`import_xunjian.py` / `import_xunjian_batch.py` / `init_new_devices.py`（旧导入，删除或重写为调用 seed）。
- 迁移：旧模型删除后 `makemigrations` 生成删除迁移；**检查 `0009/0010` 等旧迁移是否含 `RunPython` 引用已删模型**，有则一并清理。

> 注意：`ConfigBackup` 耦合旧 `device_table`，必须随旧引擎一并删除（其 views/templates/migrations 一并移除）。新版若需配置备份，后续单独立项，不在本阶段。

---

## 7. 实施步骤（强制顺序）

| 步骤 | 内容 | 工作量 | 依赖 |
|------|------|--------|------|
| B0 | 写 `custom_checks.py`（env/fan/power/device/ifbrief/agg/arp/vrrp/nqa 共 ~9 个检查器）+ 单元测试 TC-B3.6 | S | - |
| B1 | `NewDevice` 扩 4+2 字段 + 迁移（TC-B1） | S | - |
| B2 | 连接层升级（port/enable/key/telnet/关分页）（TC-B5） | M | B1 |
| B3 | 写 `seed_inspection` 命令（5 模板 + 102 台导入，幂等）（TC-B7） | M | B0,B1 |
| B4 | 删除旧引擎代码/模型/视图/URL/脚本 + 迁移 + grep 校验（TC-B9） | M | B3 |
| B5 | `manage.py check` + 离线模板渲染 + 在内网 `migrate` + 跑 `seed_inspection` | S | B1-B4 |
| B6 | 联调：手动触发全量巡检，核对 XunjianRecord/CheckResult/AnomalyRecord（TC-B8） | M | B5 |

**总工作量估算：约 10~14 人天**（较原"双引擎收敛"更低，因无需数据迁移与影子双跑）。

---

## 8. 测试用例（pytest，基于真实 Checker/Pipeline 编写）

> 测试文件：`app02/tests/test_engine_b.py`（或 `tests.py`）。所有网络调用用 `unittest.mock` 打桩，不连真机。

### TC-B1 模型层
```python
import pytest
from app02.models import NewDevice, CheckItem, DeviceGroup, CheckSet

def test_newdevice_conn_fields():
    d = NewDevice(name='fw001.t', ip='1.1.1.1', device_type='hp_comware',
                  username='u', password='p', conn_type='ssh', port=8022,
                  role='fw', site='化龙')
    d.save()
    assert d.port == 8022 and d.conn_type == 'ssh'

def test_checkitem_fields_and_choices():
    ci = CheckItem.objects.create(name='CPU', command='display cpu-usage',
                                  parser='regex', parser_config={'pattern': r'(\d+)%', 'group':1, 'cast':'float'},
                                  checker='threshold', checker_config={'warning':80,'operator':'<'})
    assert ci.checker == 'threshold'
```

### TC-B2 解析器
```python
from app02.engine.pipeline import parse_regex, parse_raw, parse_strip_ts
def test_parse_regex_extract():
    assert parse_regex("CPU usage: 85%", {'pattern': r'CPU usage:\s*(\d+)%', 'group':1, 'cast':'float'}) == 85.0
def test_parse_regex_no_match():
    assert parse_regex("no data", {'pattern': r'(\d+)%', 'group':1}) is None
def test_parse_raw_passthrough():
    assert parse_raw("abc", {}) == "abc"
```

### TC-B3 检查器
```python
from app02.engine.pipeline import (check_threshold, check_contains, check_count,
                                    check_baseline, check_custom, register_checker, _CUSTOM_CHECKERS)

def test_threshold_ok_and_anomaly():
    assert check_threshold(50.0, '', {'warning':80,'operator':'<'}, {}) == (True, '')
    ok, note = check_threshold(85.0, '', {'warning':80,'operator':'<'}, {})
    assert ok is False and '80' in note

def test_contains_missing():
    ok, note = check_contains("line up", {}, {'must_contain':['Normal']}, {})
    assert ok is False
def test_contains_collect_mode_empty_config():
    # 空配置恒正常（纯采集）
    assert check_contains("anything", {}, {}, {}) == (True, '')

def test_count_with_expand_field():
    # 期望邻居数从 device.extra 取（expand_field）
    ok, _ = check_count("Full\nFull\nFull", '', {'keyword':'Full','expand_field':'ospf_nei'}, {'ospf_nei':3})
    assert ok is True
    ok2, note2 = check_count("Full\nFull", '', {'keyword':'Full','expand_field':'ospf_nei'}, {'ospf_nei':3})
    assert ok2 is False and '3' in note2

def test_baseline_match_and_diff():
    assert check_baseline("a b c", "a b c", {'similarity':1.0}, {}) == (True, '')
    ok, note = check_baseline("a b c", "x y z", {'similarity':1.0}, {})
    assert ok is False

def test_custom_register_and_missing():
    @register_checker('demo_chk')
    def demo_chk(parsed, base, cfg, extra):
        return (parsed == 'ok'), ''
    assert 'demo_chk' in _CUSTOM_CHECKERS
    assert check_custom('ok', '', {'func':'demo_chk'}, {}) == (True, '')
    ok, note = check_custom('x', '', {'func':'not_exist'}, {})
    assert ok is False and '未注册' in note
```

### TC-B3.6 自定义检查器（custom_checks.py 内）
```python
# app02/custom_checks.py 中的真实检查器示例
from app02.engine.pipeline import register_checker
import re

@register_checker('check_fan')
def check_fan(parsed, baseline, cfg, extra):
    # hp_comware: "Fan 1 State: Normal"；存在 Abnormal/Fault 即异常
    if re.search(r'(Abnormal|Fault)', parsed, re.I):
        return False, '存在风扇异常'
    return True, ''

@register_checker('check_env')
def check_env(parsed, baseline, cfg, extra):
    thr = cfg.get('temp_warning', 60)
    for m in re.finditer(r'(\d+)\s*C', parsed):
        if float(m.group(1)) > thr:
            return False, f'温度超过 {thr}C'
    if re.search(r'(Fault|Abnormal)', parsed, re.I):
        return False, '环境异常'
    return True, ''

@register_checker('check_ifbrief')
def check_ifbrief(parsed, baseline, cfg, extra):
    # 统计 Physical 口 DOWN 数，超过设备预期(down_ok)即异常
    down_ok = int(extra.get('down_ok', 0))
    down = len(re.findall(r'(?i)\bdown\b', parsed))
    if down > down_ok:
        return False, f'DOWN口 {down} 超过预期 {down_ok}'
    return True, ''
```
```python
# 测试
from app02 import custom_checks  # 触发注册
from app02.engine.pipeline import check_custom
def test_check_fan_normal_and_fault():
    assert check_custom("Fan 1 State: Normal\nFan 2 State: Normal", '', {'func':'check_fan'}, {}) == (True, '')
    ok, note = check_custom("Fan 1 State: Abnormal", '', {'func':'check_fan'}, {})
    assert ok is False
def test_check_ifbrief_down_limit():
    assert check_custom("GE1/0/1 down\nGE1/0/2 up", '', {'func':'check_ifbrief'}, {'down_ok':1}) == (True, '')
    ok, _ = check_custom("GE1/0/1 down\nGE1/0/2 down", '', {'func':'check_ifbrief'}, {'down_ok':1})
    assert ok is False
```

### TC-B4 pipeline.run_check_item
```python
from app02.engine.pipeline import run_check_item
from app02.models import CheckItem

class FakeConn:
    def __init__(self, out): self.out = out
    def send_command(self, cmd, **kw): return self.out

def test_run_check_item_ok():
    ci = CheckItem(command='display cpu-usage', parser='regex',
                   parser_config={'pattern':r'(\d+)%','group':1,'cast':'float'},
                   checker='threshold', checker_config={'warning':80,'operator':'<'})
    raw, ok, note = run_check_item(FakeConn("CPU usage: 50%"), ci, '', {}, 't', 'dev')
    assert raw and ok

def test_run_check_item_cmd_fail():
    class BadConn:
        def send_command(self, cmd, **kw): raise RuntimeError("timeout")
    ci = CheckItem(command='c', parser='raw', checker='contains', checker_config={})
    raw, ok, note = run_check_item(BadConn(), ci, '', {}, 't', 'dev')
    assert raw is None and ok is False and '失败' in note

def test_run_check_item_empty():
    ci = CheckItem(command='c', parser='raw', checker='contains', checker_config={})
    raw, ok, note = run_check_item(FakeConn(""), ci, '', {}, 't', 'dev')
    assert raw is None and ok is False
```

### TC-B5 连接层
```python
from unittest.mock import patch, MagicMock
import app02.engine.executor as ex

def test_build_conn_kwargs_port_and_secret():
    d = MagicMock(); d.device_type='hp_comware'; d.ip='1.1.1.1'; d.username='u'
    d.password='p'; d.conn_type='ssh'; d.port=8022; d.enable_password='en'; d.ssh_key_file=''
    with patch.object(ex, 'ConnectHandler') as CH:
        CH.return_value = MagicMock()
        # 直接调用内部连接构建（抽成 _build_conn_kwargs 函数后测）
        kwargs = ex._build_conn_kwargs(d)
        assert kwargs['port'] == 8022 and kwargs['secret'] == 'en'

def test_paging_disabled_after_connect():
    d = MagicMock(); d.device_type='hp_comware'; d.conn_type='ssh'; d.port=None
    d.enable_password=''; d.ssh_key_file=''; d.ip='1.1.1.1'; d.username='u'; d.password='p'
    with patch.object(ex, 'ConnectHandler') as CH:
        conn = MagicMock(); CH.return_value = conn
        ex._xunjian_one_device(d, [], 't', None)  # 仅验证连接+关分页被调用
        # 连接成功后应发送 screen-length disable
        sent = [c.args[0] for c in conn.send_command.call_args_list]
        assert any('screen-length disable' in (s or '') for s in sent)
```
> 实施时把连接构建抽成 `_build_conn_kwargs(device)` 纯函数，便于本测试。

### TC-B7 seed 幂等
```python
from io import StringIO
from django.core.management import call_command
from app02.models import NewDevice, CheckItem, DeviceGroup, CheckSet

def test_seed_idempotent():
    call_command('seed_inspection')
    n1 = NewDevice.objects.count()
    g1 = DeviceGroup.objects.count()
    assert n1 == 102 and g1 == 5
    # 再跑一次不应翻倍
    call_command('seed_inspection')
    assert NewDevice.objects.count() == n1 and DeviceGroup.objects.count() == g1

def test_seed_role_mapping():
    call_command('seed_inspection')
    assert NewDevice.objects.get(name__startswith='fw').group.name == 'GRP-FW'
    assert NewDevice.objects.get(name__startswith='csw').group.name == 'GRP-CSW'
```

### TC-B8 集成（mock netmiko）
```python
from unittest.mock import patch
from app02.engine.executor import run_xunjian
from app02.models import XunjianRecord, CheckResult, AnomalyRecord, CheckSet, DeviceGroup

def test_run_xunjian_writes_records():
    cs = CheckSet.objects.first()
    with patch('app02.engine.executor.ConnectHandler') as CH:
        conn = MagicMock()
        conn.send_command.return_value = "CPU usage: 50%"  # 所有命令同返回值，足够跑通
        CH.return_value = conn
        res = run_xunjian(operator='tester', checkset_id=cs.id)
    rec = XunjianRecord.objects.filter(time=res['time']).first()
    assert rec is not None
    assert CheckResult.objects.filter(time=res['time']).count() > 0

def test_run_xunjian_anomaly_to_anomalyrecord():
    cs = CheckSet.objects.first()
    with patch('app02.engine.executor.ConnectHandler') as CH:
        conn = MagicMock()
        # CPU 返回 95% → 触发阈值异常
        conn.send_command.return_value = "CPU usage: 95%"
        CH.return_value = conn
        res = run_xunjian(operator='tester', checkset_id=cs.id)
    assert AnomalyRecord.objects.filter(time=res['time']).count() > 0
```

### TC-B9 删除旧引擎后无残留
```python
import subprocess
def test_no_legacy_references():
    # 全仓 grep 旧标识应为 0（在仓库根执行）
    out = subprocess.run(['grep','-rln','device_table|xunjian.py|test1.py|info_xunjian',
                          'app02','xunjian_system1','--include=*.py'],
                         capture_output=True, text=True)
    assert out.stdout.strip() == '', f"发现旧引用: {out.stdout}"

def test_legacy_urls_gone():
    from xunjian_system1 import urls
    patterns = [str(p.pattern) for p in urls.urlpatterns]
    assert not any('info/xunjian' in p or 'info_xunjian' in p for p in patterns)
```

---

## 9. 验收标准

1. `manage.py check` 0 issues；全仓 grep 旧引擎关键词 = 0。
2. `makemigrations` + 内网 `migrate` 成功；`seed_inspection` 幂等，建 5 Group / ≥60 CheckItem / 102 设备 / 全量 CheckSet。
3. `NewDevice` 中化龙防火墙 `port=8022` 已正确写入；连接层发送 `screen-length disable`。
4. 手动触发全量巡检：102 台全部执行，CPU≥80%/内存≥85% 自动标异常；风扇/电源/接口/ARP 异常判定生效；`XunjianRecord`/`CheckResult`/`AnomalyRecord` 落库正确。
5. 旧 UI 入口（/info/xunjian/ 等）返回 404；系统仅剩新引擎路径。

## 10. 风险与回滚

- **风险1（连接兼容）**：regex 阈值基于 hp_comware V7 输出，个别型号措辞差异 → 用 1~2 台真机抽样校准 regex，再全量。
- **风险2（删除旧表破坏迁移）**：旧迁移文件若含 `RunPython` 引用已删模型会报错 → 删除前 grep 迁移目录，清理引用；必要时新建一次性清理迁移。
- **风险3（自定义检查器误判）**：`check_ifbrief` 的 `down_ok` 默认 0 可能把运维故意 shutdown 的口标异常 → 允许在 `device.extra` 配置 `down_ok`，seed 时默认按角色给宽松值（如接入交换允许 2）。
- **回滚**：本阶段不引入新中间件、不碰生产数据表结构以外的东西；若 seed 有误，`flush` 新表重跑即可；旧引擎已物理删除不可回退（符合用户"彻底单引擎"决策）。

---

*附：命令模板完整清单（52 条去重命令，5 套模板）已沉淀于 §1.1 / §3.3，可直接作为 `seed_inspection` 的内置数据。*
