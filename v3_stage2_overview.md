# 设备分类 2.0 · 能力感知分级巡检 — 阶段2 落地概览

> 阶段0（device_class + 重分类）✅ 阶段1（feature 字段 + seed 全局化）✅ **阶段2（opt-in 执行 + 命令 + 前端）✅** 阶段3（内网验证）待做

## 核心改动

### 1. 新增 `app02/engine/capability.py`（能力探测单一真源）
- `INCLUDE_TOKENS` 单一真源 → 派生 `PROBE_COMMAND`（杜绝 v2「include 与 keyword 漂移」硬伤）。
- `FEATURE_KEYWORDS` 仅用主 token；**严禁 neighbor / vrid / BAGG** 等跨协议易误判词。
- `detect_capabilities(raw)`：从探针回显解析能力清单。
- `ensure_capabilities(device, connection, force)`：
  - `None`（从未检测）vs `[]`（已检测确无特性）严格区分；
  - `capabilities_ts` 过期（`CAP_STALE_DAYS=7`）自动重探；
  - 探测失败**不写库**、返回旧值/`None`，由调用方保守兜底（不波及全 fleet）。

### 2. `executor.py` 能力门控（opt-in）
- `_get_items_for_device`：开关**关** → 仅 `base`；开关**开** → `base ∪ caps`（feature 命令已全局链接所有组，必须此处门控，否则全 fleet 无差别跑全部协议命令）。
- worker 连接成功后：开关开则 `ensure_capabilities` 并**重算 `actual_items`**（时序修复），`dev_report.expected` 回填；
- `report.expected_checks` 改由 worker 累加（开关开 + 探针发现新特性时，实际应执行项多于主线程初算）。

### 3. 两个管理命令
- `discover_capabilities`：连接设备跑探针 → 写 `extra['capabilities']`（**纯透明，只检测不执行**）。`--site/--device/--dry-run/--force`。
- `set_protocol_inspection`：逐设备/站点/role 开关 `protocol_inspection`。`--on/--off`。

### 4. 前端
- **设备管理页**新增「设备分类」列（device_class 中文标签）+「协议巡检」列：能力徽章 + **检测能力**按钮 + 协议开关（调新接口 `new/device/capability/`）。
- **巡检项管理页**新增「能力标签」列，新增/编辑弹窗支持 `feature` 选择。

### 5. 单测
`app02/tests/test_capability.py` **15 项全过**（csw003&004 真实回显、邻居误判防护、vrid 防护、include/keyword 同步、None/[]、过期重探、探测失败回退、force）。`manage.py check` 0 issues。

## 用户操作清单（生效与验证）
1. **重启 runserver**（开发机改代码惯例，否则跑旧代码）。
2. 内网 `python manage.py migrate`（0012/0013 本机已 apply，内网库确认）。
3. `python manage.py discover_capabilities --site all --force` → 写入各设备 capabilities。
4. 试点：`python manage.py set_protocol_inspection --device csw001 --on`。
5. 全量巡检 → 核对 `expected_count` 比改造前下降（未开开关/无特性设备不计入 feature 项），`InspectionGap` 缺口为 0 或仅真机断连。

## 回退
默认 `protocol_inspection=False` + `feature='base'` → 行为等同改造前（只跑基础项），零回归；删除三处新增即完全回退。
