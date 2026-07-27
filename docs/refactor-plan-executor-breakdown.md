## Problem Statement

`app02/engine/executor.py` 中的 `_xunjian_one_device` 是一个过程式单体函数（~160 行，5 层 try/except 嵌套），包含了连接管理、能力探测、逐项执行、三种落库、异常记录、报告组装等 5 种职责。当前 executor 的测试覆盖率为 **0%**，ADR-001 决策 #4 要求的 85% 覆盖率目标无法在现有结构下实现。

同时，能力探测（`ensure_capabilities`）嵌入在巡检主流程中，每台设备每次巡检都发送探针命令——实际能力不会天天变化，且探针命令与巡检命令重复采集同一份配置。

## Solution

将 `_xunjian_one_device` 拆解为三个深模块，将能力探测从主流程移除，改为巡检后从已采集的 CheckResult 异步解析。

### 模块拆分

| 新模块 | 职责 | Interface |
|--------|------|-----------|
| `DeviceSession` | SSH 连接 + 关分页 + 断开，收归 `_build_conn_kwargs` | `connect(device) → connection` / `disconnect(connection)` |
| `ItemRunner` | 逐项 send_command → run_check_item，返回结构化结果 | `run_one(item, conn, baseline, extra) → ItemResult` |
| `ResultRecorder` | 三种落库（CheckResult + AnomalyRecord + DeviceParseResult），含统一重试 | `record(ItemResult, time, device, command, severity)` |

### 能力探测新流程

```
巡检前：读 device.extra.capabilities → _get_items_for_device 门控
巡检后：从 CheckResult('display current-configuration') 解析
        → 发现新能力 → 写入 pending_capabilities
        → 前端提示用户确认 → 启用 → 下次巡检生效
        用户可关闭提示（capabilities_nag_disabled: true）
```

### 其他优化

- `_with_retry` 统一 OperationalError 重试模式（消除重复代码）
- 连接失败时 `bulk_create` 替代逐条 `create`（30 次 round-trip → 1 次）
- `_build_conn_kwargs` 收归 DeviceSession
- 巡检后回调改为 hook pipeline（`[sync_cmdb, detect_capabilities, ...]`）
- `discover_capabilities` 管理命令同步改为读 CheckResult + 复用 DeviceSession

## Commits

### Commit 1：提取 `_with_retry` 工具函数

- 在 executor.py 中提取 `_with_retry(create_fn, label)` 
- 替换 `_safe_create_check_result` 和 `_safe_create_anomaly` 的内部重试循环
- 行为不变：2 次重试 + OperationalError 时 `close_old_connections()`
- 运行现有 15 个测试确认不破坏

### Commit 2：提取 `DeviceSession`

- 新建 `app02/engine/device_session.py`
- 搬入 `_build_conn_kwargs` → `DeviceSession._build_kwargs`
- 搬入连接 + 关分页 + 断开逻辑
- `_xunjian_one_device` 中连接代码替换为 `DeviceSession` 调用
- **删除 executor 中能力探测代码**（`ensure_capabilities` 调用 + `actual_items` 重赋值块）
- `actual_items` 不再 mutate，`dev_report.expected` 只设一次
- 连接失败时改用 `bulk_create`
- 测试：`test_device_session.py`（mock `ConnectHandler`，验证 kwargs 构建、调用顺序、异常处理）

### Commit 3：提取 `ItemRunner`

- 新建 `app02/engine/item_runner.py`
- 搬入逐项执行循环（send_command → run_check_item → 组装 ItemResult）
- `ItemResult` dataclass：`(command, raw, is_ok, notes, structured)`
- `_xunjian_one_device` 中执行循环替换为 `ItemRunner.run(connection, items, baseline_map, device_extra)`
- 测试：`test_item_runner.py`（mock connection + run_check_item，验证每个 item 被正确调用）

### Commit 4：提取 `ResultRecorder`

- 新建 `app02/engine/result_recorder.py`
- 搬入三种落库逻辑（CheckResult + AnomalyRecord + DeviceParseResult）
- 使用 `_with_retry` 处理 OperationalError
- `_xunjian_one_device` 中落库代码替换为 `ResultRecorder.record(item_result, ...)`
- 测试：`test_result_recorder.py`（mock Django ORM，验证每种状态触发正确落库）

### Commit 5：巡检后 post-inspection hook pipeline

- 新建 `app02/engine/post_inspection.py`
- 定义 `POST_INSPECTION_HOOKS = [sync_cmdb, detect_capabilities]`
- 每个 hook：接收 `(task_id, xunjian_time, devices)` 签名
- `new_run_xunjian` 的 `_worker()` 回调改为调用 pipeline
- 移走硬编码的 `call_command('sync_cmdb')` 到 hook pipeline 中
- 行为不变：先 sync_cmdb，再 detect_capabilities

### Commit 6：能力检测从 CheckResult 解析 + pending 机制

- `detect_capabilities` hook 实现：
  - 遍历每台设备，从 `CheckResult(time=xunjian_time, command='display current-configuration')` 取 raw
  - 调用 `capability.detect_capabilities(raw)` 
  - 与已有 `device.extra.capabilities` 和 `pending_capabilities` 做差集
  - 发现新能力 → 写入 `device.extra.pending_capabilities`
- 新增 `device.extra` 字段：
  - `pending_capabilities: list | null` — 待确认的能力
  - `capabilities_nag_disabled: bool` — 用户关闭了提示

### Commit 7：前端能力确认 API

- `GET /api/device/<name>/pending-capabilities/` → 返回 `{pending: ["ospf", "bgp"]}`
- `POST /api/device/<name>/capabilities/confirm/` → 启用选中能力，移入 `capabilities`，清空 `pending`
- `POST /api/device/<name>/capabilities/dismiss/` → 设置 `capabilities_nag_disabled: true`，清空 `pending`
- 设备列表页面：有 pending 的设备旁显示提示角标

### Commit 8：discover_capabilities 命令适配

- 删除 SSH 连接 + PROBE_COMMAND 逻辑
- 改为：读 `CheckResult.objects.filter(command='display current-configuration').latest()` → `detect_capabilities`
- 连接复用 `DeviceSession`（如果需要 force 重探 → 仍需连接，但不重复写连接代码）
- 支持 `--from-checkresult` 和 `--live` 两种模式

### Commit 9：集成测试 + 端到端验证

- 运行全部现有测试 → 15/15 应保持通过
- 新增 3 个测试文件的覆盖率统计
- 空巡检项设备、连接失败设备、正常设备 → 三个场景手动巡检一次

## Decision Document

- 能力探测从巡检主流程移除：不绑在 SSH 连接后，改为巡检结束后从已采集的 CheckResult 异步解析
- 新设备首次巡检：`capabilities=None` → 仅跑 `feature='base'` → 巡检后自动检测 → 提示用户启用新能力
- 用户可关闭能力提示：`device.extra.capabilities_nag_disabled = true`
- `pending_capabilities` 与 `capabilities` 严格分离：前者待确认，后者已启用
- DeviceSession scope：仅 SSH 连接/断开，不含业务逻辑
- 模块命名空间：统一 `app02/engine/` 下，保持 import 路径一致
- `_with_retry` 仅处理 OperationalError 重试，不捕获业务异常
- 巡检后 hook pipeline 按顺序执行，前一个失败不阻塞后续（保持 sync_cmdb 的容错语义）
- `discover_capabilities` 命令保留，增加 `--from-checkresult` 读库模式
- `actual_items` 只赋值一次，不再在执行中 mutate
- `dev_report.expected` 只设一次，在能力门控计算后立即确定

## Testing Decisions

### 好测试的定义
- 只测试 external behavior，不测试 implementation details
- 每个测试只验证一个行为
- 用 `unittest.mock.patch` mock 外部依赖（netmiko、Django ORM）
- 复用 `test_capability.py` 中已验证的 Fake 对象模式（FakeConn、FakeModel）

### 新增测试文件

| 文件 | 覆盖模块 | 测试数量 | Mock 策略 |
|------|---------|:------:|-----------|
| `test_device_session.py` | DeviceSession | 6-8 | mock `ConnectHandler`，验证 kwargs 构建、连接调用、异常 |
| `test_item_runner.py` | ItemRunner | 8-10 | mock `connection.send_command` + `run_check_item` |
| `test_result_recorder.py` | ResultRecorder | 5-7 | mock `CheckResult.objects.create` 等 ORM 方法 |

### Prior art
- `test_capability.py` — `FakeDev`、`FakeConn`、`FakeModel` 模式是本次测试的参考模板
- `test_custom_checks.py` — 用输入输出配对测试 checker 函数

## Out of Scope

- views.py 拆分（2393 行 → 子模块）
- pipeline.py 职责分离
- reporter.py HTML 去耦
- capability.py Django ORM 泄漏修复（本次不动 `ensure_capabilities`，仅不再从 executor 调用）
- Celery / 异步任务框架引入
- 设备密码加密
- `_audit_missing_checks` 性能优化
- 前端 UI 重设计（仅添加能力确认功能所需的最小接口）

## Further Notes

- 本次重构不改变巡检执行的并发模型（仍使用 ThreadPoolExecutor）
- executor.py 的 `run_xunjian` 函数签名不变，views 层无感知
- `ensure_capabilities` 函数保留不动，仅不再从 executor 主流程调用（discover_capabilities 命令可选使用）
- 前端能力确认 UI 的具体布局由前端开发决定，本计划只定义 API 契约
