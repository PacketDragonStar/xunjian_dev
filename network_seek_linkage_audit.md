# network-seek 联动审计报告

> 审计对象：巡检系统（`xunjian_system1`）→ network-seek（`C:/Users/ZSS/Desktop/network-seek`）的拓扑联动
> 审计方法：把 network-seek 的**精确解析正则**套在库内**真实 H3C 回显**（`CheckResult`）上离线跑通，逐项验证命中情况
> 审计时间：2026-07-22

---

## 一、联动链路

```
rebuild_topology [--push]
  ├─ sync_cmdb                       # CheckResult → CmdbDevice 台账
  ├─ export_networkseek_fixtures     # 每台设备写 <device>.txt，6 段 !Command: 格式
  └─ [--push] full_reset_and_import_comware
                └─ import_comware_fixture
                      ├─ split_fixture_comware      # 按 !Command: 切段
                      └─ parse_*_comware            # 各段解析 → Neo4j 图
```

导出 6 段：`display version` / `display current-configuration` / `display interface brief` /
`display lldp neighbor-information list` / `display vlan brief` / `display ip routing-table`。

---

## 二、问题清单（按严重度）

### 🔴 P0-1　LLDP 解析器双 bug —— 拓扑互联核心错误
**文件**：`network_seek/parsers/comware.py` → `parse_lldp_comware`

1. **对端端口丢失**：真实 `display lldp neighbor-information list` 为**空格分列**
   （列：Local Interface / Chassis ID / Port ID / System Name），解析器先 `s.split('|')`，
   切不出 → 掉 `else` 分支取首尾 token → `(本地口, 对端设备, '')`，**远端端口全空**。
2. **假链路污染**：图例续行
   `# -- -- Nearest customer bridge neighbor` 与
   `Default -- -- Nearest bridge neighbor` **未被 SKIP 过滤**
   （SKIP 列表仅含 `Local Interface`/`Chassis ID`/`Port ID`/`System Name`/`Total entries`），
   每台设备被注入 2 条假链路到假设备 `#` 与 `Default`。

**实测**（化龙 oasw005 一台）：
```
当前解析 links=5 → [('#','neighbor',''), ('Default','Nearest','--'),
                    ('GE1/0/1','psw004&005...xc',''),
                    ('XGE1/0/49','asw011&012...xc',''),
                    ('XGE1/0/50','asw011&012...xc','')]
              ↑ 2 条假链路         ↑ 3 条真实链路，对端端口全空
```

**影响**：拓扑图既有悬空端口、又有假节点假边，互联关系不可信。

**修复方向**：
```python
SKIP += ('Nearest',)                      # 过滤图例续行
# 空格分列，按列映射：本地口 / 对端设备 / 对端端口
toks = s.split()
if len(toks) >= 4:
    out.append((toks[0], toks[3], toks[2]))
```

---

### 🔴 P0-2　VLAN brief 解析器命中 0 条
**文件**：`network_seek/parsers/comware.py` → `parse_vlan_brief_comware`

真实 `display vlan brief` 表头 `VLAN ID   Name   Port`，数据行形如：
```
1         VLAN 0001                        GE1/0/10  GE1/0/11  ...
```
解析器只认 `VLANs include:` 或 `^\s*(\d{1,4})\s+Enabled` 两种形态 →
**实测解析出 0 个 VLAN**。VLAN 节点只能靠 `display current-configuration` 兜底，
且**端口-VLAN 映射从 brief 彻底丢失**。

**实测**：
```
当前解析 vlan 数 = 0
修正正则 ^\s*(\d{1,4})\s+VLAN  → [1, 100, 101, 110, 116]  ✅
```

**影响**：VLAN 拓扑不全、端口归属 VLAN 关系缺失（依赖 running-config 完整度）。

---

### 🟠 P1　设备命名脆弱
**文件**：`network_seek/parsers/comware.py` → `parse_version_comware`

解析器靠 `Device name:` 取主机名，但真实 `display version` **无此行**
（实测 `Device name: present? = False`）→ 退回用**导出文件名**当设备名。
只有「巡检 `NewDevice.name` == LLDP System Name 完全同名」约定成立时才连得通。

**风险**：
- 任一设备改名 / 带域名差异 → 链路静默断裂。
- IRF 堆叠 System Name 为 `psw004&005.pri...xc` 合并名，若台账拆成两台独立设备 → dangling。

**建议**：从 `display current-configuration` 的 `sysname` 取主机名（更可靠），并与导出文件名约定对齐。

---

### 🟡 P2　整洁性 / 根因
- **校准未同步**：巡检系统在阶段 B 已校准 LLDP（空格分列）、version 格式等，
  但**未同步到 network-seek**，两份 H3C 解析逻辑已分叉（comware.py 注释自身也写"需用真实回显校准"）。
- `splitter.py` 的 `split_fixture` 是 **NX-OS 专用**，Comware 链路实际走 `split_fixture_comware`，
  两者同处 `parsers` 包、易被误用。
- `rebuild_topology` 注释写 `bolt://localhost:7688`，默认配置却是 `7687`，文档对不上。

---

## 三、验证正常（无需改动）

| 组件 | 结果 |
|------|------|
| `split_fixture_comware` 段头映射 | ✅ 6 段全部正确 |
| `parse_interfaces_comware` | ✅ 57 个接口正确解析 |
| `parse_route_table_comware` | ✅ 13 条路由正确（目的/协议/下一跳/出接口） |
| `parse_version_comware`（型号/版本/时长） | ✅ 仅缺失主机名 |

---

## 四、结论与建议

1. **巡检侧采集无碍**——6 段命令在 `CheckResult` 中均真实存在，export 不会漏台。
2. **network-seek 侧 2 个 P0 直接导致拓扑图错误**：LLDP 链路残损+假节点、VLAN 拓扑缺失。
3. **根因是校准分叉**：建议把「巡检系统 ↔ network-seek」的 H3C 解析逻辑统一为一份，避免再分叉。
4. **下一步**：待用户确认后，直接修改 network-seek 仓库的 `comware.py`（P0-1 / P0-2），
   改动小且可用同一真实回显离线复验后再落盘。

---

## 五、修复记录（2026-07-22 已落盘 ✅）

用户确认后已直接修改 `C:/Users/ZSS/Desktop/network-seek/network_seek/parsers/comware.py`，
**用化龙真实 `CheckResult` 回显离线复验通过后落盘**（未跑 Neo4j 全链路，但解析层已实证）。

### P0-1　`parse_lldp_comware` 重写
- 去掉 `|` 竖线切分，改为**空格分列 + 列定位**：`(src_intf, dst_device, dst_intf) = (toks[0], ' '.join(toks[3:]), toks[2])`。
- SKIP 关键词新增 `'Nearest'`，过滤三行图例（`# -- -- Nearest customer bridge neighbor` / `Default -- -- Nearest bridge neighbor` / `Chassis ID : * -- -- Nearest nontpmr bridge neighbor`）。
- **复验（化龙 26 台有 LLDP 数据设备）**：
  - 新逻辑：**真实链路 522 条 / 假链路 0 / 对端端口为空 0** ✅
  - 旧逻辑：真实链路 527 条中 **假链路 50 条**（连到 `#`/`Default` 假节点），且 **527 条 `dst_intf` 全空** → CONNECTS_TO 边无法匹配对端接口。

### P0-2　`parse_vlan_brief_comware` 新增形式3
- 新增分支 `^\s*(\d{1,4})\s+VLAN\b`，命中真实 H3C 表格行 `1  VLAN 0001  GE1/0/10 ...`。
- 形式1（`VLANs include:`）/ 形式2（`^\d+ Enabled`）保留兼容其它固件。
- **复验（化龙 17 台有 vlan brief 数据设备）**：16 台正确解析出 VLAN 列表；**1 台（oasw005）仍为 0**。
- 该 0 设备经核查**非解析器 bug**：其 `display vlan brief` 回显串成了 `display current-configuration` 接口段（`interface ... port access vlan 110`），属**采集侧数据质量问题**，需返工重采该设备此命令，不在解析器修复范围。

### 遗留（未改，按原审计 P1/P2）
- **P1 设备命名脆弱**：`parse_version_comware` 仍依赖 `Device name:`（真实回显无此行），退回用导出文件名当设备名；
  跨设备 LLDP 链路能否连通，取决于"台账名 == LLDP System Name"约定。本次未动，待后续评估统一命名源。
- **P2**：巡检系统与 network-seek 的 H3C 解析逻辑仍双份维护；`rebuild_topology` 注释端口与默认配置不符。建议后续统一。
- **未跑端到端**：Neo4j 在本环境不可达，修复仅验证到"解析层产出正确元组/列表"，导入建图需在内网执行 `rebuild_topology [--push]` 复验。
