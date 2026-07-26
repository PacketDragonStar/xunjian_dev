<!-- approved -->
# 巡检系统清理 & 可运行化 · 看板

> 基于 PRD v2.1 | 生成日期：2026-07-20
> 审批状态：✅ 已批准

---

## 依赖关系图

```
Ticket 1 (models.py 清理) ──┐
                             ├──→ Ticket 5 (pipeline 死代码)
Ticket 2 (urls.py 清理) ────┤
                             ├──→ Ticket 6 (根目录脚本清理)
Ticket 3 (settings.py 修正) ─┤
                             ├──→ Ticket 7 (Cisco 模板归档)
Ticket 4 (views_01 删除) ────┘
                                  ↓
                             Ticket 8 (urls 路由统一)
                                  ↓
                             Ticket 9 (端到端验证)
                                  ↓
                             Ticket 10 (test_checker 验证)
                                  ↓
                             Ticket 11 (P0 bug 修复)
```

---

## P0（阻塞启动）

### Ticket 1：清理 models.py 中 v1 残余模型及重复定义

- [ ] **Ticket 1**：删除 `app02/models.py` 中旧模型（`Department`、`UserInfo`、`Admin`、`Item`、`MyModel`），删除重复的第二套 `DeviceGroup`/`NewDevice`/`CheckItem`/`CheckSet`/`XunjianTask`/`XunjianRecord`/`CheckResult`/`AnomalyRecord` 定义，仅保留一套与 `app02/engine/executor.py` 中 import 完全匹配的模型。

**测试用例 TC-1-1**

编号：TC-001-1
名称：验证 models.py 删除 v1 残余后 manage.py check 零错误
前置条件：Python 虚拟环境已激活，Django 已安装
步骤：
1. 备份 db.sqlite3（如有）
2. 删除 app02/migrations/ 下除 __init__.py 外的所有文件
3. 执行 `python manage.py check`
预期结果：`System check identified no issues (0 silenced).`
清理：无需清理

**测试用例 TC-1-2**

编号：TC-001-2
名称：验证 models.py 中仅存在一套 NewDevice 定义，字段与 executor.py 匹配
前置条件：Ticket 1 已完成
步骤：
1. 执行 `python -c "from app02.models import NewDevice; f = [f.name for f in NewDevice._meta.get_fields()]; print(f)"`
2. 检查输出中是否包含 `name, ip, group, device_type, username, password, extra, enabled, conn_type, port, enable_password, ssh_key_file, role, site`
预期结果：输出包含以上所有字段，且无重复字段
清理：无需清理

---

### Ticket 2：清理 urls.py 中 v1 残余路由

- [ ] **Ticket 2**：删除 `xunjian_system1/urls.py` 中所有 v1 路由相关代码：`from app02.views_01 import ...`、`/depart/`、`/admin/list/`、`/host/list/`、`/login/`（v1 版本）、`/search/`、`re_path media` 等。合并重复的 `/new/*` 路由定义。

- 依赖：Ticket 4（views_01 删除）

**测试用例 TC-2-1**

编号：TC-002-1
名称：验证 urls.py 删除 v1 路由后 manage.py check 无 URL 相关 warning
前置条件：Ticket 4 已完成
步骤：
1. 执行 `python manage.py check`
预期结果：系统检查通过，无 "WARNING: ?: (urls.W001)" 或其他 URL 配置错误
清理：无需清理

**测试用例 TC-2-2**

编号：TC-002-2
名称：验证所有新路由 URL name 可达
前置条件：Ticket 2 已完成
步骤：
1. 执行 `python manage.py shell -c "from django.urls import reverse; names=['new_index','new_devices_list','new_device_add','new_device_edit','new_checkitem_list','new_checkitem_add','test_checker','new_run_xunjian','new_xunjian_tasks','new_device_group_list','new_checkset_list','acceptance_list','new_bulk_import']; [print(n, '→', reverse(n, args=[1] if 'edit' in n or 'delete' in n or 'progress' in n or 'report' in n or 'diff' in n or 'detail' in n or 'retry' in n else [])) for n in names]"`（简化：使用 `django.urls.reverse` 验证关键路由）
预期结果：每个 name 都能成功 reverse，无 `NoReverseMatch` 异常
清理：无需清理

---

### Ticket 3：修正 settings.py 配置

- [ ] **Ticket 3**：在 `xunjian_system1/settings.py` 中：
  1. 添加 `LOGGING` 配置字典（覆盖 `xunjian.*` 命名空间，`INFO` 级别输出到控制台）
  2. 修改 `LANGUAGE_CODE = 'zh-hans'`
  3. 修改 `TIME_ZONE = 'Asia/Shanghai'`
  4. 添加 `XUNJIAN_CONCURRENCY = 32`
  5. 删除 `GRAPPELLI_ADMIN_TITLE`（grappelli 未安装，无此依赖）

- 依赖：无

**测试用例 TC-3-1**

编号：TC-003-1
名称：验证 LOGGING 配置生效
前置条件：无
步骤：
1. 执行 `python manage.py shell -c "import logging; logger = logging.getLogger('xunjian.executor'); logger.info('TEST_LOGGING_OK')"`
预期结果：控制台输出类似 `2026-07-20 xx:xx:xx INFO xunjian.executor: TEST_LOGGING_OK`
清理：无需清理

**测试用例 TC-3-2**

编号：TC-003-2
名称：验证语言和时区配置
前置条件：无
步骤：
1. 执行 `python manage.py shell -c "from django.conf import settings; print(settings.LANGUAGE_CODE); print(settings.TIME_ZONE)"`
预期结果：输出 `zh-hans` 和 `Asia/Shanghai`
清理：无需清理

---

### Ticket 4：删除 views_01/ 残余模块

- [ ] **Ticket 4**：删除 `app02/views_01/` 目录及其所有内容（`__init__.py`、`account.py`、`admin.py`、`depart.py`、`host_xunjian.py`）。

- 依赖：无（仅需确保 urls.py 已不 import 此模块，或与 Ticket 2 同步进行）

**测试用例 TC-4-1**

编号：TC-004-1
名称：验证 views_01 目录已完全删除
前置条件：无
步骤：
1. 执行 `python -c "import os; print(os.path.exists('app02/views_01'))"`
预期结果：`False`
清理：无需清理

**测试用例 TC-4-2**

编号：TC-004-2
名称：验证删除后 manage.py check 无 import 错误
前置条件：Ticket 2 和 Ticket 4 均已完成
步骤：
1. 执行 `python manage.py check`
预期结果：系统检查通过，无 ImportError
清理：无需清理

---

### Ticket 5：删除 pipeline.py 死代码

- [ ] **Ticket 5**：在 `app02/engine/pipeline.py` 中删除 `CUSTOM_CHECK_REGISTRY` 字典及其对应的 `register_checker` 装饰器函数定义（保留 `_CUSTOM_CHECKERS` 和其 `register_checker`）。确认 `CUSTOM_CHECK_REGISTRY` 无任何实际引用（`search_files` 验证）。

- 依赖：无

**测试用例 TC-5-1**

编号：TC-005-1
名称：验证 pipeline.py 中无 CUSTOM_CHECK_REGISTRY 残留
前置条件：无
步骤：
1. 执行 `python -c "with open('app02/engine/pipeline.py') as f: c=f.read(); print('CUSTOM_CHECK_REGISTRY' in c)"`
预期结果：`False`
清理：无需清理

**测试用例 TC-5-2**

编号：TC-005-2
名称：验证 custom checker 注册表正常工作
前置条件：Ticket 5 已完成
步骤：
1. 执行 `python manage.py test_checker --list`
2. 检查输出中 `已注册自定义检查器` 列表
预期结果：列表包含 `check_fan, check_power, check_device, check_env, check_ifbrief, check_agg, check_arp, check_vrrp, check_nqa, check_stp, check_vlan, check_ospf_peer, check_bgp_peer, check_rbm, check_security_policy, check_session, check_mlag, check_track, check_cpu, check_memory, check_logbuffer, check_irf, check_transceiver, check_system_stable, check_zone, check_security_policy_zone, check_routing_table` 等全部 checker
清理：无需清理

---

## P1（清理项目根目录）

### Ticket 6：清理根目录一次性脚本及废弃文件

- [ ] **Ticket 6**：删除或移动到 `attic/` 目录（归档）以下根目录文件：

  **直接删除**（已完成使命的一次性脚本）：
  - `_fix_line82.py`
  - `fix_add_acceptance_view.py`
  - `fix_and_verify.py`
  - `fix_bgp_command.py`
  - `fix_bracket.py`
  - `fix_commands_yaml.py`
  - `fix_custom_checks.py`
  - `fix_encoding.py`
  - `fix_models_for_report.py`
  - `fix_seed_and_import.py`
  - `fix_srp_commands.py`
  - `fix_stable_irf.py`
  - `fix_views_presets.py`
  - `fix_zone_rbm_in_excel.py`
  - `fix_line82`
  - `demo_raw_check.py`
  - `demo_test_checker.py`
  - `update_excel_commands.py`
  - `compare_sheets.py`
  - `split_raw_output.py`
  - `auth.py`

  **移动到 `attic/`**（包含配置信息，后续可能参考）：
  - `gen_check_logic_excel.py`
  - `gen_hualong_excel.py`
  - `gen_oa_excel.py`
  - `gen_vlan_demo.py`
  - `generate_threshold_excel.py`
  - `bulk_import_checkitems.py`
  - `gen`（无扩展名文件）

- 依赖：无

**测试用例 TC-6-1**

编号：TC-006-1
名称：验证根目录下无 fix_*.py 文件
前置条件：Ticket 6 已完成
步骤：
1. 执行 `ls fix_*.py 2>&1`（Windows: `dir fix_*.py 2>&1`）
预期结果：`File Not Found` 或 `找不到文件`
清理：无需清理

**测试用例 TC-6-2**

编号：TC-006-2
名称：验证项目启动不受删除影响
前置条件：Ticket 6 已完成
步骤：
1. 执行 `python manage.py check`
预期结果：系统检查通过
清理：无需清理

---

### Ticket 7：归档 Cisco TextFSM 模板

- [ ] **Ticket 7**：将 `app02/cisco_nxos_show_bfd_session.textfsm`、`cisco_nxos_show_interface_transceiver_details.textfsm`、`cisco_nxos_show_interface.textfsm`、`cisco_nxos_show_lldp_neighbors.textfsm` 移动到 `attic/textfsm_cisco/` 目录。

- 依赖：无

**测试用例 TC-7-1**

编号：TC-007-1
名称：验证 Cisco TextFSM 模板已从 app02 目录移除
前置条件：Ticket 7 已完成
步骤：
1. 执行 `ls app02/cisco_*.textfsm 2>&1`
预期结果：`File Not Found`
清理：无需清理

---

### Ticket 8：统一 urls.py 路由定义

- [ ] **Ticket 8**：合并 `xunjian_system1/urls.py` 中重复的 `/new/*` 路由。当前存在两套路由定义（v1 残余中的旧命名 + v2 中的新命名），统一为一个 URL 配置块，确保：
  - 同一个 view 函数只有一个 URL name
  - URL pattern 使用一致的参数风格（`<int:xxx_id>` 而非 GET 参数）
  - `/` 首页路由指向 `new_index`

- 依赖：Ticket 2

**测试用例 TC-8-1**

编号：TC-008-1
名称：验证无重复 URL name
前置条件：Ticket 8 已完成
步骤：
1. 执行 `python manage.py check`
预期结果：无 "URL namespace isn't unique" 之类 warning
清理：无需清理

**测试用例 TC-8-2**

编号：TC-008-2
名称：验证首页可访问
前置条件：Ticket 8 已完成
步骤：
1. 启动 `python manage.py runserver`
2. 浏览器或 curl 访问 `http://127.0.0.1:8000/`
预期结果：返回 200，内容为非 500 错误页面
清理：停止 runserver

---

## P2（验证）

### Ticket 9：端到端启动验证

- [ ] **Ticket 9**：执行完整启动流程验证：
  1. `python manage.py check`
  2. `python manage.py migrate`（如使用 SQLite，确保 db.sqlite3 存在）
  3. `python manage.py runserver 0.0.0.0:8000`
  4. 访问首页确认 200

- 依赖：Ticket 1-8 全部完成

**测试用例 TC-9-1**

编号：TC-009-1
名称：端到端三步启动
前置条件：所有 P0/P1 Ticket 已完成，Python 环境就绪
步骤：
1. `python manage.py check` → 记录输出
2. `python manage.py migrate --run-syncdb` → 记录输出
3. `timeout 5 python manage.py runserver 0.0.0.0:8000` → 记录输出
预期结果：步骤1 输出 "no issues"，步骤2 无 fatal error，步骤3 输出 "Starting development server at http://0.0.0.0:8000/"
清理：无需清理

---

### Ticket 10：test_checker CLI 验证

- [ ] **Ticket 10**：执行 `python manage.py test_checker --list`，验证所有 PARSERS、CHECKERS、_CUSTOM_CHECKERS 正常注册并显示。

- 依赖：Ticket 5

**测试用例 TC-10-1**

编号：TC-010-1
名称：验证所有 checker 类型 CLI 可列出
前置条件：Ticket 5 已完成
步骤：
1. 执行 `python manage.py test_checker --list`
预期结果：输出包含 "可用解析器"、"可用检查器"、"已注册自定义检查器" 三块，自定义检查器数量 ≥ 20
清理：无需清理

---

### Ticket 11：补齐 P0 bug 修复（PRD v2.0 遗留）

- [ ] **Ticket 11**：修复 PRD v2.0 中已识别但未修复的 P0 Bug：
  1. **Bug#1 `new_device_edit`**：在 `app02/views.py` 的 `new_device_edit` 函数中补全 `conn_type/port/enable_password/ssh_key_file/role/site` 字段的赋值
  2. **Bug#2 `_normalize_device_type`**：在 `app02/engine/executor.py` 中删除无效的 Cisco `return dt` 分支
  3. **Bug#3 `difflib.HtmlDiff` 大输出保护**：在 `app02/views.py` 的 `xunjian_diff_view` 中添加行数判断，超过 500 行自动切换 `context=True`

- 依赖：Ticket 1（确保 NewDevice 模型字段正确）

**测试用例 TC-11-1**

编号：TC-011-1
名称：验证 new_device_edit 补全字段
前置条件：Ticket 1 已完成
步骤：
1. 在 Django shell 中创建一个 NewDevice 实例，设置 conn_type='ssh', port=22, role='fw', site='化龙'
2. 模拟 POST 请求到 `new_device_edit`，字段值包含 conn_type='telnet', port=23, role='csw', site='知识城'
3. 从数据库重新读取该设备
预期结果：conn_type='telnet', port=23, role='csw', site='知识城'（字段被正确更新）
清理：删除测试设备

**测试用例 TC-11-2**

编号：TC-011-2
名称：验证 _normalize_device_type Cisco 分支已删除
前置条件：Ticket 11 已完成
步骤：
1. 执行 `python -c "with open('app02/engine/executor.py') as f: c=f.read(); print('return dt' in c)"`
预期结果：`False`（`return dt` 已被替换为正确的 Cisco 映射）
清理：无需清理

---

## 完成检查清单

- [ ] `python manage.py check` → 0 issues
- [ ] `python manage.py migrate` → OK（SQLite）
- [ ] `python manage.py runserver` → Starting development server
- [ ] 首页 `http://127.0.0.1:8000/` → 200
- [ ] `python manage.py test_checker --list` → 3 类 checker 全部列齐
- [ ] 根目录 `fix_*.py` 数量 = 0
- [ ] `app02/views_01/` 不存在
- [ ] `app02/models.py` 无 `Department`、`UserInfo`、`Admin` 等旧模型
- [ ] logging 日志正常输出
- [ ] `TIME_ZONE` = `Asia/Shanghai`
</write_to_file>

<environment_details>
# Board updated.
# File: BOARD.md
# Lines: 315
# Line ending: CRLF
# 
</environment_details>