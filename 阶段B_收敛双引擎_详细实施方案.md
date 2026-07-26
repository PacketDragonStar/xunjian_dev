# 阶段 B：收敛双引擎（降技术债）详细实施方案与测试用例

> 配套文档：《中期架构改进工作清单.md》阶段 B；《阶段A_调度解耦_详细实施方案.md》（已落地）
> 适用范围：内网运行、手动触发、不做安全整改/不做告警（与阶段 A 一致的边界）
> 编写依据：基于真实源码扫描（行号见各节），非模板套用

---

## 0. 现状与边界（基于代码的事实）

### 0.1 双引擎并存现状

| 维度 | 旧引擎（待下线） | 新引擎（保留） |
|------|------------------|----------------|
| 入口视图 | `info_xunjian` (`views.py:153`)、`info_xunjiantest` (`views.py:229`) | `new_run_xunjian` (`views.py`，阶段 A 已异步化) |
| URL | `/info/xunjian/` (`urls.py:37`)、`/info/xunjiantest/` (`urls.py:38`) | `/new/xunjian/run/` (`urls.py:126`) |
| 执行逻辑 | `xunjian.xunjian_device` / `xunjian.xunjian_paramiko` (`xunjian.py:25/236`) | `engine/executor.run_xunjian` |
| 命令库 | `methon/test1.py`（1871 行 / 75KB / **80+ 厂商函数**） | `engine/pipeline.PARSERS` + `CHECKERS` 注册表 (`pipeline.py:71/206`) |
| 连接层 | `xunjian.ConnectDevice`（paramiko，`sleep+recv(999999)` 脆弱） | netmiko（`executor.py` 已用） |
| 设备模型 | `device_table` (`models.py:78`) | `NewDevice` (`models.py:169`) |
| 结果模型 | `result_specific_table` (`models.py:104`)、`result_notes_table` (`models.py:113`)、`result_overall_table` (`models.py:98`) | `CheckResult` (`models.py:238`)、`AnomalyRecord` (`models.py:252`)、`XunjianRecord` (`models.py:218`) |
| 配置备份 | `ConfigBackup` (`models.py:57`，FK→`device_table`) | 无对应新模型（见 §5.4） |
| 巡检项定义 | `function_table` / `function_group_relationship_table` (`models.py:90/94`) | `CheckItem` (`models.py:197`) |

### 0.2 关键利好（降低风险）

1. **UI 已不暴露旧引擎**：新侧边栏 `layout.html` 只链接 `/new/xunjian/`、`/new/checkitem/list/`、`/new/history/` 等，**完全没链接 `/info/xunjian/`**。旧引擎在 UI 上是"孤岛"，下线不会断现有操作路径。
2. **新结果表是旧表的超集**：
   - `result_specific_table(time,device,command,result,config_changed,notes)` ⊂ `CheckResult(time,device,command,result)`（仅 `config_changed/notes` 两个次要字段未迁，可忽略）。
   - `result_notes_table(time,device,command,notes,confirm)` ⊂ `AnomalyRecord(time,device,command,notes,confirm,baseline_val,current_val)`。
   → 历史数据可**行级直转**，无需结构改造。
3. **迁移先例已存在**：`init_new_devices.py` 已把旧 `device_table` 的 **H3C** 设备迁到 `NewDevice/DeviceGroup/CheckItem`。阶段 B2 是在此基础上**扩展**（补华为/其他厂商 + 补结果表迁移）。
4. **旧函数多数可被新引擎"零代码"覆盖**：`test1.py` 的 80+ 函数本质是 `shxxx`（跑命令→文本对比）。其中绝大多数只是"跑命令 + 与基线/关键字比较"，直接对应新引擎现成的 `check_baseline` / `check_contains` / `check_count` / `check_threshold`，**无需写新代码**，只需在 `CheckItem` 里登记命令与检查器类型。

### 0.3 爆破半径（谁还在用旧引擎/旧表）

- `views.py`：`info_xunjian`、`info_xunjiantest`、`import_functions_from_package` (`views.py:218`)。
- `urls.py`：`info/xunjian/`、`info/xunjiantest/`（无模板引用，仅 URL 残留）。
- `import_xunjian.py`、`import_xunjian_batch.py`：将历史 txt 导入 `device_table`+`result_specific_table`+`result_overall_table`（**数据导入工具，需一并迁移或改造**）。
- `app02/methon/test1.py`：全文件 `result_notes_table.objects.create`（80+ 处），是旧引擎唯一命令库。
- `xunjian.py`：被 `views.py:9` `from app02 import xunjian` 引入，仅上述两视图使用。

> ⚠️ **唯一外部依赖**：`import_xunjian*.py` 向旧表写数据。阶段 B2 必须提供"新导入脚本"或改造它指向 `NewDevice`+`CheckResult`，否则历史导入会断。

### 0.4 风险评级

| 子阶段 | 风险 | 说明 |
|--------|------|------|
| B0 覆盖度核对 | 中 | 决定后续工作量；结论可能显示新引擎覆盖不足 |
| B1 插件化重构 | 高 | 厂商逻辑沉淀在 80+ 函数里，映射错会丢巡检能力 |
| B2 数据迁移 | 高 | 历史数据不可丢；字段类型需转换（`expand`文本→`extra`JSON） |
| B3 下线旧引擎 | 低 | UI 已不引用，但需 grep 全仓确认无遗漏引用 |

---

## 1. 总体策略与执行顺序

分 4 个子阶段，**强制顺序执行**，前一步验收通过才进下一步：

```
B0 覆盖度核对 ──▶ B1 插件化重构 test1.py ──▶ B2 数据迁移 ──▶ B3 下线旧引擎
   (产出:         (产出: 厂商插件 +       (产出: 旧表数据   (产出: 移除旧代码/
    覆盖矩阵)       CheckItem 全量登记)    转入新表)          旧表/旧URL)
```

**核心铁律：B3 下线前必须跑"影子双跑"（shadow mode）**——新旧引擎对同一批设备巡检，逐设备比对异常判定结论，差异为 0 才允许下线。这是阶段 B 唯一不可跳过的质量门。

---

## 2. B0 覆盖度核对（Coverage Matrix）

**目标**：列出旧引擎 `test1.py` 全部函数 → 厂商/命令/检查语义 → 判定新引擎是否已覆盖（对应 `CheckItem` 或已有注册检查器）。

### 2.1 提取旧函数清单
`test1.py` 函数命名规则：`sh*`=执行类、`dis*`=显示类、`h3cfw_*`=华三防火墙、`dispatch_*`=华三下发。按函数名 + 首行注释（如 `# show version 设备运行时间`）即可分类。

### 2.2 覆盖判定规则
对第 i 个旧函数，判定其属于哪一型（决定 B1 工作量）：

| 类型 | 特征 | B1 处理方式 | 是否需要写代码 |
|------|------|-------------|----------------|
| **A 基线型** | 仅"跑命令 + 与基线文本比较" | 登记 `CheckItem(parser=raw/textfsm, checker=baseline)` | 否 |
| **B 规则型** | 阈值/计数/包含判断（如 OSPF 邻居数、CRC、光功率） | 登记 `CheckItem(checker=threshold/count/contains)` | 否 |
| **C 复杂型** | 多命令联动、厂商专属解析（如 `disver_ar/fw/ce` 多平台版本、`dispatch_hw*` 下发） | 用 `@register_checker` 写自定义函数，挂在 `engine/vendor_checks/` | **是（约 10~15 个）** |

### 2.3 交付物
- `docs/coverage_matrix.csv`：列 = `旧函数名, 厂商, 命令, 语义, 类型(A/B/C), 对应CheckItem名/注册检查器名, 状态(已覆盖/待补)`
- 验收：`C 型`数量明确、每个 `C 型`已认领负责人。

---

## 3. B1 插件化重构（test1.py → 注册表）

**目标**：把厂商领域知识从"单体 75KB 文件 + 函数名约定"改为"新引擎注册表驱动"，消除 `methon/test1.py`。

### 3.1 目录结构（新增）
```
app02/engine/
├── vendor_checks/              # 新增：厂商自定义检查器
│   ├── __init__.py             # 自动 import 本目录所有模块 → 触发 register_checker 注册
│   ├── huawei.py               # disver_ar/fw/ce/fm/ce57 等 C 型函数
│   ├── h3c.py                  # h3cfw_* / dispatch_hw* 等 C 型函数
│   └── common.py               # 跨厂商通用 C 型（如光功率解析）
└── ...（pipeline/executor/reporter 不变）
```

### 3.2 改造范式（以 C 型为例）
旧 `test1.py:disver_ar`（华三/华为 AR 版本检查）→ 新：
```python
# app02/engine/vendor_checks/huawei.py
from app02.engine.pipeline import register_checker

@register_checker('check_version_ar')
def check_version_ar(parsed, baseline_parsed, config, extra):
    """AR 设备版本检查：解析 display version，比对运行时间/版本基线"""
    # parsed: engine 已用 check_item.command 采集的原始输出
    if baseline_parsed is None:
        return False, '基线数据不存在，请先设置基线'
    # ...原 disver_ar 的解析与判定逻辑平移至此...
    return True, ''
```
> A/B 型**不写代码**，仅在 `CheckItem` 表登记（命令 + 检查器类型），由 `pipeline.run_check_item` 自动调度。

### 3.3 注册自发现
`vendor_checks/__init__.py` 用 `pkgutil` 遍历本目录 import 所有模块（与现 `import_functions_from_package` 思路一致），确保 `@register_checker` 在 Django 启动时全部注册。需在 `apps.py` 的 `ready()` 或 `engine/__init__.py` 触发一次 import。

### 3.4 CheckItem 全量登记
基于 B0 矩阵，为所有 A/B 型函数创建 `CheckItem` 行（命令、parser、checker、checker_config）。可脚本化批量插入（参考 `init_new_devices.py` 写法）。

### 3.5 验收
- `python manage.py shell` 中 `from app02.engine.pipeline import _CUSTOM_CHECKERS`，确认所有 C 型检查器已注册。
- `CheckItem` 数量 ≥ B0 矩阵中 A/B/C 总数。

---

## 4. B2 数据迁移（旧表 → 新表）

**目标**：把旧表历史数据无损迁入新表，旧表保留为只读直至 B3。

### 4.1 字段映射表（精确，源自 `models.py`）

**设备：`device_table` → `NewDevice`**
| 旧字段 | 新字段 | 转换 |
|--------|--------|------|
| `device` | `name` | 直接（注意 `NewDevice.name` 有 `unique=True`，需先查重） |
| `ip` | `ip` | 直接 |
| `group_name` | `group` | `group_name` → `DeviceGroup` 按名匹配；不存在则建 |
| `user` | `username` | 直接 |
| `password` | `password` | 直接（安全暂缓，保持明文一致） |
| `expand` (Text) | `extra` (JSON) | `json.loads(expand)`；失败则 `{}` |
| `device_type` | `device_type` | 直接 |

**结果：`result_specific_table` → `CheckResult`**
| 旧 | 新 | 转换 |
|----|----|------|
| `time` | `time` | 直接 |
| `device` | `device` | 直接 |
| `command` | `command` | 直接 |
| `result` | `result` | 直接 |
| `config_changed`/`notes` | （舍弃） | 非核心，可并入 `notes` 或丢弃 |

**异常：`result_notes_table` → `AnomalyRecord`**
| 旧 | 新 | 转换 |
|----|----|------|
| `time`/`device`/`command`/`notes`/`confirm` | 同名 | 直接 |
| — | `baseline_val`/`current_val` | 旧表无，留空 |

**总记录：`result_overall_table` → `XunjianRecord`**
| 旧 | 新 | 转换 |
|----|----|------|
| `time` | `time` | 直接 |
| `user_xnjian` | `operator` | 直接 |
| `result` | `result` | 直接 |
| （无） | `device_count` | 由 `result_specific_table.filter(time=t).count()` 推导 |
| （无） | `ok/anomaly/failed_devices` | 由 `result_notes_table` 是否含该 `time` 推导（有 notes=异常，否则正常） |
| （无） | `check_count` | 由该 `time` 的 `result_specific_table` 行数推导 |

### 4.2 迁移脚本
新增管理命令 `app02/management/commands/migrate_legacy.py`：
- 幂等：以 `time`+`device`+`command` 为键 `get_or_create`，可重复执行。
- 事务：每张表一个事务，失败回滚不影响已迁数据。
- 日志：输出每表"已迁/跳过/失败"计数。
- **不删旧表**（B3 才删）。

### 4.3 双写与回滚策略
- 迁移是**一次性可逆**操作，不是长期双写。回滚 = 提供 `migrate_legacy --reverse`（删除本次新表新增行，按迁移日志里的主键清单）。
- 旧表在 B3 前保持**只读**（应用层不再写入；`import_xunjian*.py` 在 B2 同步改造指向新表，见 §4.4）。

### 4.4 数据导入工具改造
`import_xunjian.py` / `import_xunjian_batch.py` 当前写 `device_table`+`result_specific_table`+`result_overall_table`。B2 中改为：
- 设备 → `NewDevice`（复用 `init_new_devices.py` 逻辑）；
- 命令结果 → `CheckResult`；
- 总记录 → `XunjianRecord`。
> 否则即使迁完旧数据，新的文本/Excel 导入仍会写进即将删除的旧表，造成数据分裂。

### 4.5 `ConfigBackup` 处理（需决策）
新引擎**无**配置备份模型。`ConfigBackup` (`models.py:57`) 是真实功能（配置备份+变更检测）。两种选择：
- **(a) 保留 `ConfigBackup` 模型**，仅把其 FK 从 `device_table` 改为 `NewDevice`；
- **(b) 在新引擎增加 `ConfigBackup` 模型 + 备份逻辑**（更彻底但工作量更大）。
> 建议阶段 B 采用 **(a)**，FK 改 `NewDevice` 即可，功能不动。B 阶段不做功能新增。

---

## 5. B3 下线旧引擎

**前置条件**：B0~B2 完成 **且** 影子双跑差异为 0（§6 TC-BX）。

### 5.1 删除清单
- `views.py`：删除 `info_xunjian`、`info_xunjiantest`、`import_functions_from_package`。
- `xunjian_system1/urls.py`：删除 `info/xunjian/`、`info/xunjiantest/` 两条 path（`:37/:38`）。
- `app02/xunjian.py`：整文件删除（确认无其他引用）。
- `app02/methon/test1.py` + `__pycache__`：整目录删除。
- `views.py:9` `from app02 import xunjian`：删除。

### 5.2 旧模型下线（生成迁移）
在 `models.py` 删除：`device_table`、`group_table`、`device_group_relationship_table`、`function_table`、`function_group_relationship_table`、`result_overall_table`、`result_specific_table`、`result_notes_table`、`Item`、`MyModel`（后两者疑似死代码，删除前 grep 确认）。
- 生成 `makemigrations app02`（自动产生 `DeleteModel` 操作）。
- `ConfigBackup` 按 §4.5 改为 FK→`NewDevice` 后再随版本迁移。

### 5.3 残留引用清扫
全仓 grep（模板/py/JS）：`info/xunjian`、`info_xunjiantest`、`device_table`、`result_specific_table`、`result_notes_table`、`from app02 import xunjian`、`methon`、`xunjian_device`、`xunjian_paramiko`。应为 0 命中。

### 5.4 验收
- `manage.py check` 0 issues；
- 全仓旧引用 grep = 0；
- 旧表在 DB 中已 DROP（`migrate` 后）；
- 新引擎全链路（发起→进度→历史→异常确认）冒烟通过。

---

## 6. 测试用例（详细）

> 约定：测试基于 `pytest` + `pytest-django`，使用独立 test DB（内网 MySQL 的测试库或 SQLite 测试库）。每个 TC 标注 类型 / 前置 / 步骤 / 断言。

### 6.1 覆盖度核对测试

**TC-B0-01 旧函数全量提取**
- 类型：静态分析
- 步骤：扫描 `app02/methon/test1.py`，收集所有顶层 `def sh*/dis*/h3cfw_*/dispatch_*`。
- 断言：`len(函数列表) == 80+`（与实际一致）；`coverage_matrix.csv` 行数 == 函数数；无函数遗漏分类。

**TC-B0-02 覆盖判定无 C 型遗漏**
- 步骤：读取 `coverage_matrix.csv`，筛 `类型==C`。
- 断言：每个 C 型都有 `对应CheckItem名/注册检查器名` 非空；C 型总数在 10~15 区间（与 §2.2 预期一致）。

### 6.2 插件化注册测试

**TC-B1-01 自定义检查器自发现注册**
```python
def test_vendor_checkers_registered():
    from app02.engine.pipeline import _CUSTOM_CHECKERS
    expected = ['check_version_ar', 'check_optical_power', ...]  # 来自 coverage_matrix C 型
    for name in expected:
        assert name in _CUSTOM_CHECKERS, f"{name} 未注册"
```

**TC-B1-02 注册检查器签名与返回规范**
```python
def test_checker_signature_and_return():
    from app02.engine.pipeline import _CUSTOM_CHECKERS
    for name, fn in _CUSTOM_CHECKERS.items():
        ok, note = fn("fake parsed", "fake baseline", {}, {})
        assert isinstance(ok, bool)
        assert isinstance(note, str)
```

**TC-B1-03 A/B 型 CheckItem 可被引擎调度（无需自定义代码）**
```python
@pytest.mark.django_db
def test_baseline_checkitem_runs():
    ci = CheckItem.objects.create(name='cpu基线', command='show cpu',
                                  parser='raw', checker='baseline',
                                  checker_config={'similarity': 1.0})
    # 用 mock connection 返回固定输出
    ok, note = run_check_item(mock_conn, ci, baseline='expected', device_extra={}, ...)
    assert ok is True
```

### 6.3 数据迁移测试

**TC-B2-01 迁移行数一致（设备）**
```python
@pytest.mark.django_db
def test_device_migration_count():
    # 预置 device_table 100 行（fixture）
    call_command('migrate_legacy')
    assert NewDevice.objects.count() == 100
```

**TC-B2-02 字段映射正确**
```python
@pytest.mark.django_db
def test_device_field_mapping():
    dt = device_table.objects.create(device='R1', ip='10.0.0.1', group_name='核心',
                                      user='admin', password='x', expand='{"ospf_nei":9}',
                                      device_type='Huawei')
    call_command('migrate_legacy')
    nd = NewDevice.objects.get(name='R1')
    assert nd.ip == '10.0.0.1'
    assert nd.username == 'admin'
    assert nd.extra == {'ospf_nei': 9}          # 文本→JSON 转换
    assert nd.group.name == '核心'               # group_name→DeviceGroup
```

**TC-B2-03 结果表行级直转**
```python
@pytest.mark.django_db
def test_result_migration():
    result_specific_table.objects.create(time='T1', device='R1', command='show ver', result='...')
    result_notes_table.objects.create(time='T1', device='R1', command='show ver',
                                       notes='异常', confirm=False)
    call_command('migrate_legacy')
    assert CheckResult.objects.filter(time='T1', device='R1').count() == 1
    assert AnomalyRecord.objects.filter(time='T1', device='R1', confirm=False).count() == 1
```

**TC-B2-04 总记录派生字段正确**
```python
@pytest.mark.django_db
def test_overall_derivation():
    result_specific_table.objects.create(time='T2', device='R1', command='c1', result='x')
    result_specific_table.objects.create(time='T2', device='R2', command='c2', result='y')
    result_notes_table.objects.create(time='T2', device='R1', command='c1', notes='异常', confirm=False)
    call_command('migrate_legacy')
    rec = XunjianRecord.objects.get(time='T2')
    assert rec.device_count == 2
    assert rec.check_count == 2
    assert rec.anomaly_devices == 1
    assert rec.result == '异常'
```

**TC-B2-05 幂等（重复执行不重复插入）**
```python
@pytest.mark.django_db
def test_migration_idempotent():
    call_command('migrate_legacy')
    n1 = NewDevice.objects.count()
    call_command('migrate_legacy')   # 第二次
    assert NewDevice.objects.count() == n1
```

**TC-B2-06 回滚可逆**
```python
@pytest.mark.django_db
def test_migration_rollback():
    call_command('migrate_legacy')
    assert NewDevice.objects.count() > 0
    call_command('migrate_legacy', '--reverse')
    assert NewDevice.objects.count() == 0   # 仅删本次迁移新增行
```

**TC-B2-07 expand 非法 JSON 不中断**
```python
@pytest.mark.django_db
def test_expand_bad_json():
    device_table.objects.create(device='Bad', ip='1.1.1.1', group_name='g',
                                 user='u', password='p', expand='not-json', device_type='X')
    call_command('migrate_legacy')   # 不应抛异常
    assert NewDevice.objects.get(name='Bad').extra == {}
```

### 6.4 影子双跑等价性测试（质量门，不可跳过）

**TC-BX-01 新旧引擎异常判定一致**
- 类型：集成（需可达设备或用录制回放）
- 前置：准备 N 台设备的"命令输出快照"（fixture 文本），旧引擎 `test1.py` 函数与新引擎 `CheckItem` 各跑一遍。
- 步骤：对每台设备、每个命令，比较旧 `result_notes_table` 是否生成 notes vs 新 `AnomalyRecord` 是否 `ok=False`。
- 断言：两者"是否异常"结论**100% 一致**；不一致项必须逐个review并归因为预期差异（如新引擎更严格），写入豁免清单。

**TC-BX-02 影子模式不污染生产数据**
```python
@pytest.mark.django_db
def test_shadow_mode_isolated():
    # 新旧同跑，断言旧表与新表写入互不干扰、可独立比对
    ...
```

### 6.5 下线后回归测试

**TC-B3-01 全仓无旧引用**
```python
def test_no_legacy_references():
    import subprocess
    out = subprocess.run(['grep','-rn',
        'device_table|result_specific_table|result_notes_table|from app02 import xunjian|methon|xunjian_device|xunjian_paramiko',
        'app02','xunjian_system1'], capture_output=True, text=True)
    assert out.stdout.strip() == '', f"仍存在旧引用:\n{out.stdout}"
```
> 注：测试代码本身不得包含上述关键字，否则误报；可用白名单排除测试文件。

**TC-B3-02 新引擎全链路冒烟**
```python
@pytest.mark.django_db
def test_new_engine_e2e(client):
    # 登录 → 发起巡检(异步) → 轮询任务 → 历史可查 → 异常可确认
    ...
    assert resp.status_code == 200
```

**TC-B3-03 旧 URL 返回 404**
```python
@pytest.mark.django_db
def test_legacy_urls_gone(client):
    assert client.get('/info/xunjian/').status_code == 404
    assert client.get('/info/xunjiantest/').status_code == 404
```

---

## 7. 执行顺序与依赖图

```
[1] B0 覆盖度核对 ──产物:coverage_matrix.csv──┐
                                              ▼
[2] B1 插件化重构 ◀──────────────────────────┘ (依赖 B0 矩阵)
      ├─ B1.1 建 vendor_checks/ + 写 C 型检查器
      ├─ B1.2 批量登记 A/B 型 CheckItem
      └─ B1.3 注册自发现验证
                                              ▼
[3] B2 数据迁移 ◀────────────────────────────┘ (依赖 B1：CheckItem 全量就位)
      ├─ B2.1 migrate_legacy 命令（设备+结果+总记录）
      ├─ B2.2 import_xunjian*.py 改造指向新表
      └─ B2.3 ConfigBackup FK→NewDevice
                                              ▼
[4] TC-BX 影子双跑 ── 差异=0 才放行 ──────────┘
                                              ▼
[5] B3 下线旧引擎（删代码+删旧模型迁移）
      └─ B3.4 全仓 grep 清扫 + 回归测试
```

---

## 8. 验收标准（阶段 B 出口）

1. `coverage_matrix.csv` 完整，C 型全部认领并实现。
2. 所有厂商命令在 `CheckItem`（A/B 型）或 `vendor_checks/`（C 型）中可寻址；`methon/test1.py` 删除。
3. 历史数据 100% 迁入新表（TC-B2-01~05 全绿），旧表只读直至 B3。
4. **影子双跑新旧异常判定差异 = 0**（TC-BX-01），豁免项有书面记录。
5. `manage.py check` 0 issues；全仓旧引用 grep = 0（TC-B3-01）；旧 URL 404（TC-B3-03）。
6. 新引擎全链路冒烟通过（TC-B3-02）。

---

## 9. 工作量估算（T 恤 + 人天）

| 子阶段 | 工作量 | 说明 |
|--------|--------|------|
| B0 覆盖度核对 | S（1~2 人天） | 脚本提取 + 人工分类 80 函数 |
| B1 插件化重构 | L（4~6 人天） | C 型 10~15 个检查器 + A/B 型 CheckItem 批量登记（脚本化） |
| B2 数据迁移 | M（3~4 人天） | migrate_legacy + import 改造 + ConfigBackup FK |
| B3 下线旧引擎 | S（1~2 人天） | 删代码 + 删模型迁移 + grep 清扫 |
| 测试与影子双跑 | M（3~4 人天） | 上述全部 TC |
| **合计** | **约 12~18 人天** | 其中 TC-BX 影子双跑是最关键的质量投入 |

---

## 10. 风险与回滚

| 风险 | 触发 | 缓解 |
|------|------|------|
| 新引擎覆盖不足即下线 → 丢巡检能力 | B0 结论偏差 | B3 强制依赖 TC-BX 影子双跑；差异>0 禁止下线 |
| 历史数据迁移丢失 | 字段类型错（expand→extra） | TC-B2-02/07 覆盖；迁移幂等可重跑 |
| 删旧模型后外部脚本仍写旧表 | import_xunjian*.py 未改造 | B2.4 先于 B3 完成 |
| 注册检查器未加载 → 巡检静默失效 | `vendor_checks/__init__` 未触发 | TC-B1-01 注册自发现测试拦截 |
| 回滚困难 | 直接 DROP 旧表 | B3 前旧表只读不删；删表走 Django 迁移可逆 |

---

## 11. 与阶段 A 的关系

- 阶段 A 已落地 `XunjianTask` + 异步触发 + 续跑，基于**新引擎**。本阶段 B 收敛旧引擎后，`XunjianTask` 成为唯一任务入口，旧 `result_overall_table` 的历史在 B2 并入 `XunjianRecord`，任务中心数据更完整。
- B 完成后，阶段 A 的"续跑失败设备"逻辑无需改动（它只依赖新引擎 `executor`）。
