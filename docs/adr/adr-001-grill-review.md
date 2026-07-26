# ADR-001：Grill Me 架构审问 — 核心决策记录

- **状态**：已采纳
- **日期**：2026-07-16
- **决策者**：系统管理员 + AI 架构师（Cline）
- **关联 PRD**：`docs/PRD.md` v2.0

---

## 背景

在 2026-07-16 进行三轮 Grill Me 架构审问，对 `xunjian_system1` 进行全代码审查。目的是在进入下一轮开发前，明确技术债、架构风险、以及当前阶段的具体边界。

审问基于以下文件：
- `app02/engine/pipeline.py`、`executor.py`、`reporter.py`
- `app02/models.py`、`views.py`、`custom_checks.py`
- `xunjian_system1/settings.py`、`auth.py`
- `巡检系统技术评审报告.md`、`中期架构改进工作清单.md`
- `设备巡检命令与判断清单_化龙与知识城_修正版.xlsx`

---

## 决策 #1：执行层继续使用 threading.Thread(daemon=True)，不引入 Celery

### 决策

保持当前 `views.py:88-89` 的 `threading.Thread(target=_worker, daemon=True)` 方案，不引入 Celery + Redis 中间件。

### 后果

**正面**：
- 零额外中间件依赖，部署复杂度不变
- 满足 70+ 台设备并发巡检的性能需求（`ThreadPoolExecutor(max_workers=32)`）

**负面**：
- daemon 线程在主进程重启/worker 回收时会被强制 kill，`XunjianTask` 永久卡在 `queued` 状态（孤儿任务）
- 无超时守护：单设备 SSH 卡死会阻塞线程池槽位
- 无心跳检测机制

**缓解措施（当前阶段接受，不做）**：
- 可补救方案：进程启动时扫描 `queued/running` 超时任务自动标记 `failed`；`future.result(timeout=120)` 加超时；加 `updated_at` 字段做假死检测

### 相关讨论摘要

- 用户明确："纯内网巡检，直接用线程"
- AI 指出三个风险（孤儿任务/超时/心跳），用户判断"当前环境风险可控"
- 不纳入本期改进范围

---

## 决策 #2：设备密码不做加密，保持明文存储

### 决策

`NewDevice.password` 保持 `CharField` 明文存储，`SECRET_KEY` 和数据库密码保持 `settings.py` 硬编码。

### 后果

**正面**：
- 零改造成本，现有代码不改动

**负面**：
- 若代码仓库意外外泄（如 push 到公共 Git），所有设备 SSH 密码和数据库密码直接暴露
- 若数据库被 dump，所有设备受控
- 违反纵深防御原则

**缓解措施**：
- 若未来需要，仅需在 `NewDevice.save()` 中加 Fernet 对称加密，密钥从环境变量读取
- `SECRET_KEY` 建议至少 `.gitignore` 排除，使用 `python-decouple` 环境变量化

### 相关讨论摘要

- 用户明确："只有我单人用，没必要"
- AI 指出风险但尊重决策

---

## 决策 #3：role/site 字段改为人工指定，删除自动推导说明

### 决策

`NewDevice.role` 和 `NewDevice.site` 保留为数据库字段，删除 `help_text` 中的"由设备名前缀推导"误导信息。由运维人员在添加/编辑设备时手动指定 `fw/csw/asw/lsw/srp` 和 `知识城/化龙`。

### 后果

**正面**：
- 数据一致性由人工保证（改设备名不等于改角色）
- 不需要维护设备命名规则解析代码

**负面**：
- 增加人工录入负担（但每个设备只录入一次）
- `role` 和 `site` 可以从设备名推导的信息冗余存储

### 相关讨论摘要

- 用户明确："删掉自动推导，由人工指定"
- AI 确认两方案（A 删掉改 @property；B 保留人工填），用户选 B

---

## 决策 #4：测试覆盖率从 ~15% 提升至 ≥ 80%

### 决策

当前仅 `tests/test_custom_checks.py` 有 18 个测试（覆盖 9 个自定义 checker）。需要补齐：

| 新测试文件 | 覆盖模块 | 目标覆盖率 |
|-----------|---------|:---------:|
| `tests/test_pipeline.py` | `engine/pipeline.py` | 90% |
| `tests/test_executor.py` | `engine/executor.py` | 85% |
| `tests/test_reporter.py` | `engine/reporter.py` | 90% |
| `tests/test_views.py` | `views.py` HTTP 层 | 80% |

### 后果

**正面**：
- 重构/新增 checker 时有回归保护
- `_build_conn_kwargs` 连接参数生成得到验证（当前 0 测试，telnet 参数错误只能在生产发现）

**负面**：
- 需 mock netmiko 连接（`unittest.mock.patch`），测试代码量较大

### 相关讨论摘要

- 用户明确："测试要全覆盖"
- AI 指出 `_build_conn_kwargs`、`_normalize_device_type`、`run_xunjian` 零测试的风险
- PRD 中已纳入 F5（P0 需求）

---

## 决策 #5：设备范围限定 H3C（Comware V7）交换机+防火墙

### 决策

当前聚焦 H3C 交换机（核心/接入/汇聚/OA/存储/IDC/上行）和 H3C 防火墙。排除：
- 化龙 srp001&002（路由器）
- DCI/TAP 设备
- Cisco/NX-OS 等其他厂商

### 后果

**正面**：
- 聚焦单一厂商 Comware V7，检查器/解析器可以针对性优化
- Excel 中化龙 26 台 + 知识城 46 台 = 72 台设备，范围可控

**负面**：
- 化龙核心路由器 srp001&002 需后续单独方案（PRD F9）

### 相关讨论摘要

- 用户明确输入：`设备巡检命令与判断清单` Excel 文件中已标注设备类型
- 原则：先覆盖交换机+防火墙，再扩展到路由器

---

## 发现的关键 Bug（纳入 PRD P0 修复）

### Bug #1：`new_device_edit` 丢失新增字段

**位置**：`app02/views.py:425-449`

**现象**：编辑设备时只处理 `name/ip/group/device_type/username/password/extra`，`models.py` 新增的 `conn_type/port/enable_password/ssh_key_file/role/site` 字段全部被忽略。

**影响**：通过前端编辑设备后，这些字段的数据丢失。

**修复**：在 `new_device_edit` 中补全所有新增字段的赋值。

### Bug #2：`_normalize_device_type` Cisco 分支无效

**位置**：`app02/engine/executor.py:36-38`

**现象**：`if 'cisco' in dt or 'ios' in dt or 'nxos' in dt: return dt` 直接返回原字符串，未做任何映射转换。

**影响**：无实际影响（本期不做 Cisco），但代码歧义。

**修复**：删除或补充 Cisco 家族映射。

### Bug #3：`difflib.HtmlDiff` 大输出性能风险

**位置**：`app02/views.py:216-221`

**现象**：`context=False` 全文对比 5000+ 行输出时生成巨大 HTML table，浏览器可能卡死。

**影响**：`display security-policy ip rule all` 等全量配置命令对比时用户体验极差。

**修复**：超过 500 行自动切换 `context=True`。