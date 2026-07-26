# ADR-002：v1 残余清理与可运行化修复

- **状态**：已采纳
- **日期**：2026-07-20
- **决策者**：ZSS + AI 架构师（Cline）
- **关联 PRD**：`docs/PRD.md` v2.1
- **关联看板**：`BOARD.md`

---

## 背景

在 2026-07-20 进行全代码审查（Grill Me），发现 `xunjian_system1` 项目中存在大量 v1 项目残余，以及多处阻塞项目"真正运行"的致命缺陷。审查覆盖 `models.py`、`settings.py`、`urls.py`、`views.py`、`engine/`、`custom_checks.py`、`views_01/` 及根目录全部文件。

---

## 决策 1：删除 v1 残余模型，统一 models.py

### 决策

删除 `app02/models.py` 中所有 v1 项目残余（`Department`、`UserInfo`、`Admin`、`Item`、`MyModel`），以及重复定义的第二套巡检模型（`DeviceGroup`、`NewDevice`、`CheckItem` 等），仅保留与 `app02/engine/executor.py` 中 import 完全匹配的一套模型。

### 理由

1. 两套模型定义字段完全不同：`NewDevice` 第一版有 `conn_type/port/enable_password/ssh_key_file/role/site`，第二版没有
2. `executor.py` 中 `from app02.models import NewDevice, CheckItem, CheckSet, CheckResult, AnomalyRecord, XunjianRecord, XunjianTask` 依赖的是第二套
3. `Department`/`UserInfo`/`Admin` 等 v1 模型已被 `views_01` 引用，但 `views_01` 即将删除

### 后果

- ✅ Django 迁移不再产生歧义
- ❌ 现有 `db.sqlite3` 可能与新模型 schema 不兼容，需重建数据库

---

## 决策 2：删除 views_01/ 模块及 v1 路由

### 决策

删除整个 `app02/views_01/` 目录，并清理 `xunjian_system1/urls.py` 中所有引用该模块的路由（`/depart/`、`/admin/list/`、`/host/list/`、`/login/` v1 版本）。

### 理由

1. `views_01/account.py` 依赖旧模型 `Admin`、旧工具函数 `md5_encryption`、已删除的 `check_code`
2. v1 路由与 v2 路由重复定义相同 URL name，可能导致 URL 解析歧义
3. `re_path('media/(?P<path>.*)$', serve, ...)` 与 v2 的 `*static(settings.MEDIA_URL, ...)` 重复

### 后果

- ✅ URL 路由完全统一到 v2
- ❌ 登录页面需要确认 v2 中的实现（`app02/middleware/auth.py` 已提供 AuthMiddleware）

---

## 决策 3：删除 pipeline.py 中的 CUSTOM_CHECK_REGISTRY 死代码

### 决策

删除 `app02/engine/pipeline.py` 中第 22 行的 `CUSTOM_CHECK_REGISTRY` 字典及其对应的 `register_checker` 装饰器（保留 `_CUSTOM_CHECKERS` 版本）。

### 理由

1. `custom_checks.py` 使用 `from app02.engine.pipeline import register_checker`，该导入的 `register_checker` 注册到 `_CUSTOM_CHECKERS`
2. `test_checker.py` CLI 工具也 from 导入 `_CUSTOM_CHECKERS`
3. `CUSTOM_CHECK_REGISTRY` 无任何实际引用（已验证）

### 后果

- ✅ 消除双注册表的歧义
- ✅ 减少 ~10 行死代码

---

## 决策 4：添加 LOGGING 配置，修正语言/时区

### 决策

在 `settings.py` 中添加 `LOGGING` 配置字典（覆盖 `xunjian.*` 命名空间，`INFO` 级别输出到控制台），同时修正 `LANGUAGE_CODE='zh-hans'`、`TIME_ZONE='Asia/Shanghai'`。

### 理由

1. `executor.py` 中全部使用 `logging.getLogger('xunjian.*')`，无 LOGGING 配置会导致所有 INFO 日志静默丢弃
2. `LANGUAGE_CODE='en-us'` 和 `TIME_ZONE='Etc/GMT-8'` 是国内开发中不合理的配置

### 后果

- ✅ `python manage.py shell` 执行 `logging.getLogger('xunjian.executor').info('test')` 可见输出
- ✅ Django admin 和表单显示中文

---

## 决策 5：清理根目录 14 个一次性脚本

### 决策

删除 14 个 `fix_*.py` 及 `gen_*.py`、`demo_*.py` 等一次性修复/生成脚本，已完成使命的移动到 `attic/` 目录归档。

### 理由

1. 所有 `fix_*.py` 都是针对特定问题的单次修复（如 `fix_bracket.py` 修复单行语法、`fix_encoding.py` 修复编码），已完成使命
2. 任何人误执行这些脚本都可能对已修复的代码产生副作用
3. `gen_*.py` 包含从 Excel 生成巡检项的配置逻辑，可归档参考

---

## 决策 6：归档 Cisco TextFSM 模板

### 决策

将 4 个 `cisco_nxos_*.textfsm` 模板移动到 `attic/textfsm_cisco/`。

### 理由

ADR-001 已明确 v2.0 仅支持 H3C Comware V7，Cisco 模板为死文件。

---

## 相关讨论摘要

- **用户输入**："三个全修，并且这个项目是改造项目，上个项目残余的东西是不是有点多，给他把没用的都删了"
- **AI 确认**：逐一审查后识别出 v1 残余（旧模型、旧路由、旧视图模块）、一次性脚本、Cisco 模板、双注册表、配置缺陷等 9 个问题
- **最终决定**：生成 PRD v2.1 和 BOARD.md，11 个 Ticket，按 P0→P1→P2 优先级垂直切片

---

## 影响范围

| 受影响文件 | 操作 |
|-----------|------|
| `app02/models.py` | 重构：删除 v1 模型 + 删除重复定义 |
| `app02/views_01/` | 删除整个目录 |
| `xunjian_system1/urls.py` | 重构：删除 v1 路由，合并重复路由 |
| `xunjian_system1/settings.py` | 修改：+LOGGING, +XUNJIAN_CONCURRENCY, 修正 LANGUAGE_CODE/TIME_ZONE |
| `app02/engine/pipeline.py` | 修改：删除 CUSTOM_CHECK_REGISTRY 死代码 |
| `app02/cisco_nxos_*.textfsm` ×4 | 移动到 attic/ |
| 根目录 14 个脚本 | 删除/移动到 attic/ |
| `app02/engine/executor.py` | 修改：修复 _normalize_device_type Cisco 分支 |
| `app02/views.py` | 修改：修复 new_device_edit 字段丢失 + difflib 大输出保护 |