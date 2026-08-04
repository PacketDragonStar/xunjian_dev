## Agent skills

### Issue tracker

Issues 存放在 GitHub Issues（`PacketDragonStar/xunjian_dev`），使用 `gh` CLI 操作。See `docs/agents/issue-tracker.md`.

### Triage labels

五个标准 triage labels：`needs-triage`、`needs-info`、`ready-for-agent`、`ready-for-human`、`wontfix`。See `docs/agents/triage-labels.md`.

### Domain docs

Single-context 布局：根目录 `CONTEXT.md`（待创建）+ `docs/adr/`。See `docs/agents/domain.md`.

---

## 项目概要

巡检系统 v2（Django 4.2 + H3C Comware V7），单引擎架构。

### 关键模块

| 模块 | 职责 |
|------|------|
| `app02/engine/executor.py` | 巡检执行器：`_xunjian_one_device` + `run_xunjian` 主入口 |
| `app02/engine/pipeline.py` | 流水线：parser/checker 注册表 + `run_check_item` |
| `app02/engine/device_session.py` | SSH 连接生命周期（DeviceSession） |
| `app02/engine/item_runner.py` | 单条命令执行（ItemRunner → ItemResult） |
| `app02/engine/result_recorder.py` | 三种落库 + `_db_create_with_retry` |
| `app02/engine/capability.py` | 能力检测：`detect_capabilities` / `ensure_capabilities` |
| `app02/engine/post_inspection.py` | 巡检后 hook pipeline（sync_cmdb + detect_capabilities） |
| `app02/engine/reporter.py` | 报告生成（XunjianReport / render_cli_report） |
| `app02/custom_checks.py` | 自定义 checker 函数（文件版，DB 同步源） |
| `app02/parsers/` | Comware 解析器「单一真源」 |

### 能力门控流程

```
巡检前：读 device.extra.capabilities → _get_items_for_device 按 feature 门控
巡检后：post_inspection.detect_capabilities hook
       → 从 CheckResult 解析 display current-configuration
       → 发现新能力 → 写入 pending_capabilities
用户：  前端 API 确认/关闭 → capabilities 更新
下次巡检：capabilities 已更新 → 全量门控
```

### DB checker 覆盖机制

`load_checker_overrides()` 从 `CheckerScript` 表热加载用户编辑的 checker 源码。
**exec 命名空间已注入**：`re`, `json`, `math`, `datetime`(类), `timedelta`, `_parse_log_time`, `_MONTH_MAP`, `_parse_optic_block`, `FLASH_ERROR_PAT`, `BIAS_OFF`。
新增文件版 checker 依赖新的私有工具时，必须同步更新 pipeline.py 中的注入列表。

### 光模块入 CMDB（2026-08-04 已验证）

- `CmdbInterface` 带光模块字段：`transceiver_type/vendor/serial/wavelength/distance/ordering`
- 接口页筛选器：`trans=any/none/idle/inuse`（idle=有光模块且 DOWN/ADM）
- **坑①**：`parse_transceiver` 只认 `Transceiver Type`（`Type\s*:` 会误匹配 `Connector Type`→LC/MPO）
- **坑②**：接口长名→短名映射必须支持 4 段板卡口（`FortyGigE1/4/0/33`→`FGE1/4/0/33`），正则 `(?:/\d+){{2,4}}`
- **坑③**：改 parser 后旧的 `DeviceParseResult` 是脏数据，需删掉该命令的记录让 `sync_cmdb` 回退实时解析
- 统计口径：真空闲 = ADM(NO-USE) + DOWN无描述；有 `To-[对端]` 描述的 DOWN 不算空闲
- 工具脚本：`统计空闲光模块.py` / `统计光模块按型号.py` / `按站点统计光模块.py` / `查100G光模块.py`

### 已有 ADR

- `docs/adr/adr-001-grill-review.md` — Threading / 无加密 / role 人工指定 / 测试覆盖率 ≥80%
- `docs/adr/adr-002-cleanup-v1-residue.md` — v1 模型/路由/脚本全部清理

---

## 开发守则

### 修改代码后必须跑测试

```bash
python manage.py test app02.tests
```

56 个全过才算安全。当前覆盖：
- capability 检测 + 回归（防火墙误判 / 协议配置行匹配 / 关键词同步）
- custom_checks（system_stable / logbuffer / fan / power / device / env / ifbrief / agg / arp / vrrp / nqa / cpu / memory / stp / ospf_peer / bgp_peer / rbm / mlag / track / session / vlan）
- DeviceSession（连接/断开/kwargs 构建）
- ItemRunner（正常/异常/参数传递）
- ResultRecorder（落库/异常/parse/连接失败）
- PostInspection（hook 顺序/异常隔离）
- 能力门控（5 种 caps 状态 + disabled_commands）
- 能力生命周期（去重/confirm 合并）

### 修改关键逻辑后建议手动巡检一次

端到端验证 >= 单元测试，特别是改动 executor/pipeline/checker 后。

### 常见坑

- DB checker 覆盖优先级 > 文件版。如果巡检行为跟文件版不一致，先检查 `CheckerScript` 表是否有 `enabled=True` 的覆盖
- **改 `custom_checks.py` 后必须运行** `python manage.py sync_checkers` 同步 DB，否则运行时仍用旧 DB 版本
- 设备名含 `&` 是 IRF 设备（如 `csw001&002`），netmiko prompt 匹配可能不稳定
- `datetime` 在 DB checker 命名空间中是**类**不是模块，`timedelta` 也单独注入
- 改 `FEATURE_KEYWORDS` 的检测正则时，必须加 `re.MULTILINE` 否则 `^` 只匹配字符串开头
