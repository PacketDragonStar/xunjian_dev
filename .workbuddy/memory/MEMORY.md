# 项目长期记忆：xunjian_system1（网络巡检系统）

## 定位与架构
- Django 4.2 + netmiko/paramiko + MySQL，广期所内网网络设备巡检。单引擎唯一路径 `app02/engine/`（pipeline/executor/reporter，PARSERS/CHECKERS 注册表 + 线程池并发 + 基线 diff）。旧引擎 B4 彻底删除。
- 模型：`NewDevice(name/ip/role/site/device_type/conn_type/port/enable_password/ssh_key_file/extra JSON/enabled/group FK)`；`DeviceGroup(M2M CheckItem)`；`CheckSet(M2M DeviceGroup)`；`CheckItem(name/command/parser/checker/timeout/enabled)`；`CheckResult`/`DeviceParseResult`/`AnomalyRecord`/`InspectionGap`/`XunjianRecord`/`XunjianTask`。
- 命令挂载：executor `_get_items_for_device` 是唯一「决定每设备跑哪些项」入口；feature 命令已全局链接所有 DeviceGroup，`ROLE_EXTRA_COMMANDS` 已撤销，纯靠 capability 门控（v3 完成）。
- 入口：手动触发后台线程异步（秒回 task_id），无调度/无告警。DB 本机 127.0.0.1:3306/xunjian_system/root/7ujm^YHN。

## 用户约定（重要）
- 安全方向暂缓（内网，不处理凭证加密/HTTPS）；不做告警/推送；巡检人工每天手动触发。
- 惯例：非-trivial 功能「先出方案文档、review 后再实现」。

## 阶段进展
- 阶段 B 全部完成（代码层），待用户内网 `migrate`+`seed_inspection --site`+真机校准 regex。
- 阶段 A 落地（XunjianTask 后台线程+续跑+前端轮询），迁移已生成待内网执行。
- UI 青蓝主题 #0F6E56 已落地（layout 侧边栏+顶栏、theme.css）。

## 解析器单一真源（2026-07-23 决策）
- `app02/parsers/` 内置于 xunjian（@register_parser family=hp_comware）；采集时一次解析为结构化 JSON 落库，CMDB/network-seek 只读结构化产物，raw 仅解析一次。network-seek 为可选附加。

## network-seek 四类识别（2026-07-23）
- IRF/M-LAG/VRRP/安全域纳入常规采集（CSW: irf/m-lag/link-agg/vrrp；FW: security-zone/security-policy/rbm/vrrp）。`prune_disabled_commands` 写 `extra['disabled_commands']` 自适应裁剪。
- 校准已解除：本机 MySQL 可用，csw004/fw003 真实回显已校准，network-seek 单测 61/61。新命令待重新 seed+全量巡检入库复验。

## 设备分类 2.0（2026-07-24 v3，落地中）
- 三层：T0 `device_class`(基础真源) + T1 `base`(恒跑) + T2 `feature`(能力门控，需显式启用)。
- **opt-in 模型**：①基础恒跑；②检测能力(`discover_capabilities`/设备页按钮，写 `extra['capabilities']` 仅展示不执行)；③启用协议巡检(`protocol_inspection` 逐设备开关，默认关，粒度A逐设备)。
- **落地进度**：阶段0(device_class+reclassify+DeviceGroup键改)✅ 阶段1(CheckItem.feature+迁移+seed全局化)✅ 阶段2(capability.py+executor门控+两命令+前端)✅ 阶段3验证待做(内网 migrate+discover+试点+全量巡检)。
- 命名规则→`device_class`：解析名前缀查《命名规则.xlsx》，纠正 29 台错标（OASW/PSW/USW/DCI/DSW）。新增 `device_class` 字段（含 IDC=出口交换机补映射）；DeviceGroup 键 `(site,role)`→`(site,device_class)`；`reclassify_by_naming_rule` 命令。
- 特性命令全局化 + 纯能力门控：撤销 ROLE_EXTRA_COMMANDS，feature 命令全局链接所有组，加协议=只加一条 CheckItem。
- 吸收 v2 硬伤：探针时序重算 / INCLUDE_TOKENS 单一真源 / 弃用 neighbor / capabilities_ts 过期 / None([] vs None) 区分。
- 文档：`设备分类2.0与能力感知分级巡检_实施方案_v3.md`。落地阶段 0 重分类→1 feature+capability+全局化→2 opt-in执行+前端+命令→3 验证。用户已批准「开始做」。
