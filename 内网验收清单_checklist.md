# 内网验收清单 · 四阶段（解析器单一真源 → 采集时一次解析 → 结构化导出 → 历史回填）闭环

> 用途：四阶段代码已在开发机落地并通过离线校验（`manage.py check` 0 issues / network-seek 单测 61·21 通过 / Django shell 实测 DeviceParseResult 读数正常）。本清单用于**在内网真机环境把端到端链路跑通并验证等价性**，是"改完"之后唯一未闭环的环节。
>
> 适用环境：内网 MySQL + 真实 H3C 设备（知识城 / 化龙两套，分开部署）。
> 代码基线：已包含 `app02/parsers/` 单一真源、`DeviceParseResult` 模型、阶段三 JSON 导出与 network-seek 薄导入。

---

## 0. 前置确认（开始之前）

| 项 | 检查点 | 命令 / 位置 |
|---|---|---|
| 代码版本一致 | 内网代码 = 开发机四阶段终态 | `git log` / 比对 `app02/parsers/` 是否存在（不存在说明没同步） |
| DB 连接 | 内网 `settings.py` 的 MySQL 可达 | 开发机样例：`127.0.0.1:3306 / xunjian_system / root / 7ujm^YHN`（**内网密码以你实际 settings 为准**） |
| network-seek 依赖真源 | `XUNJIAN_APP02_DIR` 指向 xunjian 根目录 | 换机器必须重设该环境变量，否则适配层 import 失败 |
| Python 环境 | 内网用你激活的 venv 跑 `manage.py` | 开发机样例：`./venv/Scripts/python.exe manage.py ...` |

---

## 1. 建表 + 回填历史（一次性）

**1.1 应用迁移，建 `DeviceParseResult` 表**
```bash
python manage.py migrate app02
```
- 预期：`0006_deviceparseresult` applied，纯新增表、零风险。
- 验收：DB 出现 `app02_deviceparseresult` 表。

**1.2 回填内网历史 CheckResult（若内网库已有旧巡检数据）**
```bash
python manage.py backfill_parse_results
```
- 预期：输出 `X 成功 / Y 跳过`。跳过的全是"映射外命令"（environment/fan/power/ospf peer/bgp peer/nqa/stp/logbuffer 等，目前无解析器）。
- ⚠️ 若内网历史是**改名前的旧采集集**，则 HA/安全新命令（m-lag / irf / security-zone / security-policy / rbm）在历史库里 **0 行**——属正常，这些靠第 3 步全量巡检入库，无需回填。
- 验收：`DeviceParseResult` 行数 = 可解析命令的历史组合数，差值应为 0（可解析命令 100% 覆盖）。

---

## 2. 更新采集集（注入新 HA/安全命令）

```bash
python manage.py seed_inspection --site 知识城
python manage.py seed_inspection --site 化龙
```
- 幂等：重复执行不重复建 CheckItem / DeviceGroup / CheckSet。
- 验收：`CheckItem` 中应有 `display m-lag summary` / `display irf` / `display link-aggregation verbose` / `display security-zone` / `display security-policy ip` / `display remote-backup-group status` 等命令；按角色模板注入（CSW/FW 有 HA 类，ASW/LSW/SRP 按 ROLE_EXTRA_COMMANDS）。
- ⚠️ 防火墙 12 台端口 8022、其余 22（已写入 NewDevice.port，连接层 `_build_conn_kwargs` 已支持）。

---

## 3. 全量巡检（自动落结构化）

- 触发方式：前端「巡检」页面手动触发全量（阶段 A 已改异步，秒回 task_id，后台线程执行）。
- 验收（巡检跑完后查 DB）：
  - `app02_checkresult` 出现新命令（`display m-lag summary` 等）的真实回显行。
  - `app02_deviceparseresult` 自动出现对应结构化行（`executor` 在 CheckResult 落库后 `update_or_create`）。
  - 重点确认：知识城 CSW×6 / 化龙 CSW×2 有 m-lag、FW 有 security-zone/security-policy/rbm；化龙 ASW×13 / CSW×2 命令数比知识城少 `display arp user-ip-conflict record`（各站点 canonical 独立，符合设计）。

---

## 4. 自适应裁剪（跳过未开启协议）

```bash
python manage.py prune_disabled_commands
```
- 作用：把首次全量中回显失败的命令写入设备 `extra['disabled_commands']`，executor 后续过滤跳过，避免反复采无效命令。
- 验收：部分设备 `extra` 含 `disabled_commands` 列表（如未配 VRRP 的设备）。

---

## 5. 解析覆盖率自检（真机数据验证单一真源）

在 network-seek 仓库下执行（用其测试 venv）：
```bash
cd ../network-seek
.venv_test/Scripts/python.exe selftest_parsers_vs_mysql.py
```
- 作用：pymysql 直连 xunjian 库读 `app02_checkresult`，按命令映射 network-seek parser 跑全部真实行，输出**覆盖率矩阵**。
- 验收：
  - 新命令（m-lag / irf / link-aggregation verbose / security-zone / security-policy ip / remote-backup-group status）解析成功数 **> 0**（证明真机回显能被单一真源吃下）。
  - 旧改名命令（`display zone` / `display security-policy ip rule all` / `display vrrp brief` / `display rbm`）应已无错误回显行（改名正确性复验）。
  - oasw005 若为串台数据，已知忽略（非 parser bug）。

---

## 6. 导出结构化 JSON（退役 raw 重解析）

在 xunjian 项目根执行：
```bash
python manage.py export_networkseek_fixtures --site 知识城
python manage.py export_networkseek_fixtures --site 化龙
```
- 默认产出：`<device>.json`，结构 `{device, site, role, mgmt_ip, schema_version, parsed:{cmd:data}}`，数据取自 `DeviceParseResult`（latest），无则实时 parse 回退。
- `--raw` 开关另产旧版 `.txt`（仅调试回退用，正常情况下不应依赖）。
- 验收：cmdb_fixtures 目录下以 `.json` 为主，且 `parsed` 内含上述 HA/安全命令的结构化数据。

---

## 7. network-seek 导入 + 拓扑图等价复验

```bash
cd ../network-seek
python scripts/rebuild_topology.py --push        # 默认走 JSON 契约
```
- 等价性证明（按构造）：`import_comware_structured` 与旧 `import_comware_fixture` 共用 `_import_comware_core` + 同一份 `_p_X` 单一真源，故 Neo4j 节点/边数应**无损等价**。
- 验收（图 diff）：
  - M-LAG → `MLAG` 节点 + `MLAG_PEER` 边；M-LAG 标记的 BAGG → `LAG` + `MEMBER_OF_LAG`。
  - IRF → `Stack` 节点（实际环境用 M-LAG 做冗余，IRF 数据可能为空，属正常）。
  - VRRP → `VRRPGroup` + `VRRP_MASTER` 边。
  - 安全域 / 安全策略落库（`SecurityZone` / `SecurityPolicy` 模型）。
  - 节点 / 边数对比 legacy fixture 路径（`rebuild_topology.py --legacy-fixture`）应一致。
- 排错：若图缺失某类，先回第 5 步看自检矩阵对应命令解析成功数是否为 0，再顺藤摸瓜。

---

## 8. 最终验收标准（全部满足 = 四阶段闭环）

- [ ] `manage.py check` 0 issues（内网环境）
- [ ] `DeviceParseResult` 表存在且含新 HA/安全命令的结构化行
- [ ] 自检脚本新命令解析成功数 > 0，无改名前错误回显残留
- [ ] `export_networkseek_fixtures` 默认产 `.json`（非仅 `.txt`）
- [ ] `rebuild_topology --push` 拓扑图节点/边数与 legacy 路径等价
- [ ] 两仓彻底解耦：raw 不再被 sync_cmdb / network-seek 重解析（仅消费 `DeviceParseResult` 或导出 JSON）

---

## 附：可暂缓的遗留项（非验收阻塞，按需排期）

1. P1 设备命名脆弱（链路连通的命门点，建议后续加固）
2. `rebuild_topology` 按站点选 bolt 端口
3. 知识城设备实际巡检覆盖确认
4. oasw005 串台数据（已知，非 bug）
5. 3 个死检查器未删除（清理类技术债，低风险）
