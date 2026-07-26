# 网络巡检系统 · 产品需求文档（PRD v2.1 — 清理与可运行化）

> **版本**：v2.1 — 聚焦"清理 v1 残余 + 修复致命缺陷 + 端到端可运行"
> **站点覆盖**：化龙 + 知识城
> **生成日期**：2026-07-20
> **来源**：Grill Me 全代码审查（9 个问题） + `设备巡检命令与判断清单_化龙与知识城_修正版.xlsx`

---

## 1. 项目背景与目标

### 1.1 背景

本系统是一套面向金融生产环境的网络设备巡检平台。当前已完成 Django 4.2 底层框架、新版流水线引擎（`app02/engine/`）、差异化报告引擎，并具备多厂商设备 SSH 采集能力。

经 Grill Me 全代码审查（详见 `docs/adr/adr-001-grill-review.md` 及本次补充审查），确认当前存在以下阻挡"真正运行"的问题：

- **v1 项目残余**：`models.py` 中旧模型（`Department`、`UserInfo`、`Admin` 等）、`urls.py` 中 v1 路由、`views_01/` 模块、Cisco TextFSM 模板
- **代码库污染**：根目录 14 个 `fix_*.py` 一次性修复脚本，可能被误执行产生副作用
- **pipeline 双注册表**：`CUSTOM_CHECK_REGISTRY`（死代码）与 `_CUSTOM_CHECKERS`（实际使用）并存
- **无日志配置**：当前 `settings.py` 无 `LOGGING` 配置，引擎内所有 `logging.getLogger('xunjian.*')` 日志静默丢弃
- **语言/时区配置**：`LANGUAGE_CODE='en-us'`、`TIME_ZONE='Etc/GMT-8'` 不符合国内使用

### 1.2 目标

- **清理所有 v1 残余**：旧模型、旧路由、旧视图模块、废弃 TextFSM 模板、一次性脚本
- **修复阻塞性缺陷**：补充 LOGGING 配置、修正语言/时区、删除 pipeline 死代码
- **统一 models.py**：只保留一套巡检模型定义，删除冲突的重复类
- **验证端到端可运行**：`python manage.py check && python manage.py runserver` 无报错启动

---

## 2. 核心用户故事

### US-1：开发者 · 首次启动

> 作为开发/运维人员，我需要 `git clone` 后执行 `pip install -r requirements.txt`、`python manage.py migrate`、`python manage.py runserver` 三步即可启动巡检系统，无任何 import 错误或 500 页面。

**验收标准**：
- `python manage.py check` 返回 0 errors
- `python manage.py runserver` 启动后首页可访问（非 500）
- `python manage.py test_checker --list` 可列出所有 checker

### US-2：网络运维工程师 · 日常巡检

> 作为网络运维工程师，我需要在网页上选择检查集、点击"执行巡检"，系统自动 SSH 登录设备采集命令、执行检查器、生成报告。

**验收标准**：
- 巡检执行引擎正常调用所有 custom checker（风扇/电源/温度/OSPF/BGP/RBM/MLAG 等 20+ 个）
- `logging.getLogger('xunjian.*')` 日志正常输出，可在控制台追踪巡检进度

### US-3：巡检管理员 · 配置巡检项

> 作为巡检管理员，我需要通过 Web 页面（或 CLI `test_checker` 工具）添加、编辑、测试巡检项。

**验收标准**：
- `/new/checkitem/list/` 页面正常加载
- `test_checker` CLI 工具正常工作，`_CUSTOM_CHECKERS` 注册表正确显示所有自定义 checker

---

## 3. 功能性需求（按优先级）

### P0（阻塞启动，必须完成）

| ID | 需求 | 说明 |
|----|------|------|
| F1 | 清理 `models.py` 中 v1 残余模型 | 删除 `Department`、`UserInfo`、`Admin`、`Item`、`MyModel`，以及重复定义的 `DeviceGroup`/`NewDevice`/`CheckItem` 等（保留正确的一套） |
| F2 | 清理 `urls.py` 中 v1 残余路由 | 删除 `views_01` 相关 import、`/depart/`、`/admin/list/`、`/host/list/` 等旧路由；合并两套 `/new/*` 路由 |
| F3 | 修正 `settings.py` 配置 | 添加 `LOGGING` 配置；`LANGUAGE_CODE='zh-hans'`；`TIME_ZONE='Asia/Shanghai'`；添加 `XUNJIAN_CONCURRENCY` |
| F4 | 删除 `views_01/` 残余模块 | 删除整个 `app02/views_01/` 目录 |
| F5 | 删除 `pipeline.py` 死代码 | 删除 `CUSTOM_CHECK_REGISTRY` 及其对应的 `register_checker` 函数（保留 `_CUSTOM_CHECKERS` 版本） |

### P1（清理项目根目录，提高可维护性）

| ID | 需求 | 说明 |
|----|------|------|
| F6 | 删除根目录 14 个一次性脚本 | 移动到 `attic/` 或直接删除：`fix_*.py`、`_fix_line82.py`、`gen_*.py`、`demo_*.py`、`update_excel_commands.py`、`compare_sheets.py`、`generate_threshold_excel.py`、`bulk_import_checkitems.py`、`split_raw_output.py` |
| F7 | 删除 Cisco TextFSM 模板 | 移动到 `attic/textfsm_cisco/`：4 个 `cisco_nxos_*.textfsm` |
| F8 | 统一 `urls.py` 路由 | 合并重复的 `/new/*` 路由定义，确保一个 view 函数对应一个 URL name |

### P2（验证，后续迭代）

| ID | 需求 | 说明 |
|----|------|------|
| F9 | 端到端启动验证 | `python manage.py check` + `python manage.py runserver` 验证 |
| F10 | `test_checker` CLI 验证 | 确认所有 custom checker 正常注册并可通过 CLI 调用 |
| F11 | 补齐 P0 bug 修复（PRD v2.0 遗留） | `new_device_edit` 字段丢失、`_normalize_device_type` Cisco 无效分支、`difflib.HtmlDiff` 大输出保护 |

---

## 4. 非功能性需求

| 维度 | 要求 | 度量标准 |
|------|------|---------|
| **可维护性** | 项目中无不相关的残留代码 | 零 v1 残余 import、零一次性脚本 |
| **可启动性** | 三步启动 | `check` + `migrate` + `runserver` 无错误 |
| **日志规范** | 全模块统一 `logging`，无 `print()` | `LOGGING` 配置覆盖 `xunjian.*` 命名空间 |

---

## 5. 关键技术决策

| 决策 | 理由 |
|------|------|
| **保留 `_CUSTOM_CHECKERS`，删除 `CUSTOM_CHECK_REGISTRY`** | `custom_checks.py` 和 `executor.py` 都使用 `_CUSTOM_CHECKERS`，另一个是死代码 |
| **保留 `app02/middleware/auth.py`** | url 路由和 views 依赖 `AuthMiddleware` |
| **保留 `app02/engine/probe.py`** | 虽然未直接使用，但属于引擎组件，后续可能用到 |
| **保留 `app02/utils/` 目录** | `encrypt.py` 被 views_01 引用，但 views_01 即将删除；保留 utils 框架以备后用 |
| **SQLite 切换** | 当前 `settings.py` 配置了 MySQL，本地开发建议使用 SQLite（`db.sqlite3` 已在根目录），具体切换由部署时决定 |

---

## 6. 测试策略

- **冒烟测试**：`python manage.py check` 验证 Django 配置完整性
- **启动测试**：`python manage.py runserver` 验证 URL 路由无 500
- **CLI 测试**：`python manage.py test_checker --list` 验证 PARSERS/CHECKERS/_CUSTOM_CHECKERS 正常加载

---

## 7. Out of Scope（明确不做）

- ❌ 更改数据库引擎（MySQL → SQLite 或反过来）
- ❌ 新增巡检项/自定义检查器
- ❌ 前端 UI 改造
- ❌ 测试覆盖率提升（P0 bug 修复除外）
- ❌ PRD v2.0 中 F2/F3/F4/F5/F6/F7/F8 的功能需求（本次只做清理）

---

## 附：被清理文件清单

| 文件/目录 | 清理原因 |
|-----------|---------|
| `app02/views_01/` | v1 项目残余，依赖已废弃的模型和工具函数 |
| `app02/models.py` 中 `Department`/`UserInfo`/`Admin`/`Item`/`MyModel` | v1 项目旧模型 |
| `app02/models.py` 中重复的 `DeviceGroup`/`NewDevice`/`CheckItem` 等 | 两套定义冲突 |
| `app02/engine/pipeline.py` 中 `CUSTOM_CHECK_REGISTRY` | 死代码 |
| `app02/cisco_nxos_*.textfsm` ×4 | ADR 已明确不做 Cisco |
| `xunjian_system1/urls.py` v1 路由 | `/depart/`、`/admin/list/`、`/host/list/`、`/login/` 等 |
| 根目录 14 个 `fix_*.py` + `gen_*.py` + `demo_*.py` | 一次性脚本，已完成使命 |
| `auth.py`（根目录） | 不在 Django 路径中，悬空文件 |
| `gen`（根目录） | 无扩展名文件，用途不明 |
| `fix_line82`（根目录） | 无扩展名文件，一次性修复残留 |