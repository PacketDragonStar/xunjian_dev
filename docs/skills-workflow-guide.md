# Matt Pocock Skills 使用指南

> 适用于 `xunjian_system1`（Django 巡检系统）的技能协作流水线。

---

## 一、技能全景图

### 1.1 需求与规划流水线（上游）

```
需求模糊 → /to-questionnaire → /to-spec → /to-tickets → /implement
                ↓ 替代入口（大规模）
              /wayfinder → /to-tickets → /implement
```

| 技能 | 输入 | 输出 | 适用时机 |
|------|------|------|----------|
| `/to-questionnaire` | 模糊需求 | 结构化问卷（交给他人填写） | 你无法独自回答某个 decision |
| `/to-spec` | 对话上下文 | GitHub Issue（PRD 规范） | 需求已讨论清楚，要固化 |
| `/to-tickets` | spec/plan | 一组 tracer-bullet tickets | spec 已就绪，要拆成可执行任务 |
| `/wayfinder` | 松散想法 | issue tracker 上的决策地图 | 任务太大，单次 session 装不下 |

### 1.2 架构与设计（中游）

```
代码现状 → /improve-codebase-architecture → /request-refactor-plan → /implement
                ↓ 依赖的基础技能
              /codebase-design（深模块词汇）
              /domain-modeling（领域模型）
              /design-an-interface（多方案对比）
```

| 技能 | 输入 | 输出 | 适用时机 |
|------|------|------|----------|
| `/improve-codebase-architecture` | 代码库（+ git history） | HTML 深化报告 | 想找架构层面的优化点 |
| `/codebase-design` | 模块代码 | 深模块词汇 + 设计原则 | 设计接口、决定 seam 位置 |
| `/domain-modeling` | 业务概念 | CONTEXT.md + ADR | 术语混乱、需要统一语言 |
| `/design-an-interface` | 模块需求 | 2+ 个接口方案对比 | API 设计、多方案选型 |
| `/request-refactor-plan` | 架构问题 | GitHub Issue（重构计划） | 已有明确重构方向 |

### 1.3 实现与交付（下游）

```
tickets → /implement（内含 /tdd + /code-review）
              ↓ 独立使用
            /tdd（测试驱动开发）
            /code-review（双轴审查）
```

| 技能 | 输入 | 输出 | 适用时机 |
|------|------|------|----------|
| `/implement` | ticket/spec | 提交到当前分支的代码 | 按 ticket 实现功能 |
| `/tdd` | 功能需求 | 先写测试 → 实现 → 重构 | 新功能或修复 bug |
| `/code-review` | fixed point（commit/branch） | Standards + Spec 双轴报告 | PR 审查、自审查 |

### 1.4 辅助与专项

| 技能 | 用途 |
|------|------|
| `/grill-me` | 持续追问式访谈，打磨计划或设计 |
| `/triage` | Issue 分类、验证、写出 agent-ready brief |
| `/teach` | 在工作区中系统教学新技能或概念 |
| `/find-skills` | 搜索和安装更多 skills |
| `/prototype` | 构建一次性原型验证设计 |
| `/research` | 对照高可信一手来源调研，保存为 Markdown |
| `/qa` | 交互式 QA，对话式提交 issue |
| `/migrate-to-shoehorn` | 把 `as` 类型断言迁移到 shoehorn |
| `/resolving-merge-conflicts` | 解决 merge/rebase 冲突 |
| `/setup-pre-commit` | 配置 Husky pre-commit hooks |

---

## 二、核心流水线详解

### 2.1 需求澄清流水线

```
/to-questionnaire  →  /to-spec  →  /to-tickets  →  /implement
```

#### 阶段 1：`/to-questionnaire` — 把不确定变成问卷

**触发条件：** 你对某个 decision 缺少关键信息，需要他人提供。

**执行过程：**
1. Agent 询问「发送给谁？」— 确定 recipient 的 role、expertise
2. Agent 询问「需要返回什么？」— 列出你无法自行决定的 facts/decisions
3. Agent 起草问卷文件 `to-questionnaire-<slug>.md`
4. 你把文件转发给 recipient 填写

**输出：** 一份 Markdown 问卷，按重要程度降序排列问题

**本项目典型场景：**
- 「OA 交换机的巡检项阈值应该设多少？」→ 发给网络管理员
- 「知识城设备的命名规范是什么？」→ 发给运维团队
- 「化龙机房的拓扑图谁维护？」→ 发给机房负责人

#### 阶段 2：`/to-spec` — 把讨论固化为规范

**触发条件：** 需求已讨论清楚，不需要额外访谈。

**执行过程：**
1. Agent 探索代码库现状
2. Agent 确定测试 seam（优先复用现有 seam）
3. Agent 按模板起草 spec：
   - **Problem Statement** — 用户面对的问题
   - **Solution** — 解决方案（用户视角）
   - **Seams** — 测试切入点和策略
   - **Acceptance Criteria** — 验收标准
4. 发布为 GitHub Issue，打上 `ready-for-agent` label

**本项目典型场景：**
- 「新增设备分类 3.0 规则」
- 「巡检报告增加趋势图」
- 「CMDB 同步支持华为交换机」

#### 阶段 3：`/to-tickets` — 拆成可执行任务

**触发条件：** spec 已就绪。

**执行过程：**
1. Agent 读取 spec/conversation 上下文
2. Agent 探索代码库，寻找 prefactor 机会
3. Agent 把工作拆成 **tracer-bullet tickets**：
   - 每个 ticket 是端到端的垂直切片
   - 声明 blocking edges（依赖关系）
   - 每个 ticket 独立可测试/可交付
4. 发布到 issue tracker

**输出示例结构：**
```
Ticket 1: 新增 DeviceClassRule 模型和数据迁移  [无依赖]
    ↓ blocks
Ticket 2: 设备分类引擎 v3 核心逻辑  [依赖 #1]
    ↓ blocks
Ticket 3: 设备列表页面显示新分类  [依赖 #2]
    ↓ blocks
Ticket 4: 分类结果验证和回归测试  [依赖 #2]
```

#### 阶段 4：`/implement` — 逐个实现

**执行过程：**
1. Agent 读取 ticket
2. 在预定 seam 上用 `/tdd`（测试驱动）
3. 定期运行 typechecking 和单文件测试
4. 完成后运行完整测试套件
5. 用 `/code-review` 审查
6. 提交到当前分支

---

### 2.2 架构优化流水线

```
/improve-codebase-architecture  →  /request-refactor-plan  →  /implement
        ↑                                ↑
   依赖 /codebase-design          依赖 /domain-modeling
   （深模块词汇）                 （领域术语）
```

#### 阶段 1：`/improve-codebase-architecture` — 扫描深化机会

**触发条件：** 想找出代码库中 shallow modules → deep modules 的重构机会。

**执行过程：**
1. **划定范围** — 优先关注 `git log` 中频繁变更的热点区域
2. **读领域模型** — `CONTEXT.md` + `docs/adr/`
3. **扫描** — 识别 shallow modules（interface 和 implementation 复杂度相当的模块）
4. **提出深化机会** — 给出具体的 refactor 建议
5. **生成 HTML 报告** — 可视化展示

**本项目热点区域（基于 git history）：**
- `app02/engine/` — 巡检引擎（频繁变更）
- `app02/parsers/` — 解析器（刚重构为单一真源）
- `app02/views.py` — 视图层
- `app02/models.py` — 数据模型

**输出：** 带深化建议的可视化 HTML 报告

#### 阶段 2：`/request-refactor-plan` — 用户访谈 + 细化计划

**触发条件：** 已有明确的架构问题要解决。

**执行过程：**
1. 用户描述问题和可能的解决方案
2. Agent 探索代码库，验证断言
3. Agent 提出其他方案选项
4. 围绕 implementation 详细访谈用户
5. 确定 exact scope（改什么 + 不改什么）
6. 检查 test coverage，确认测试计划
7. 拆成 **tiny commits** 的计划（"make each refactoring step as small as possible"）
8. 发布为 GitHub Issue

#### 阶段 3：`/implement` — 逐 commit 实现重构

每个 commit 保持小步、可验证、可回退。

---

### 2.3 大规模规划流水线（Wayfinder）

```
/wayfinder  →  decision tickets 逐个解决  →  /to-tickets  →  /implement
```

#### 适用条件

满足以下任一条件时用 `/wayfinder`，而不是直接 `/to-spec`：

- 工作太大，单个 agent session 无法完成
- 从出发点到目标之间的路径被 "fog" 包围
- 需要先做多个 decision，才能开始 planning
- 多人在多个 session 中协作

#### 执行过程

1. **命名 destination** — 明确目标（spec、decision、migration 等）
2. **创建 Map issue** — 在 tracker 上创建带 `wayfinder:map` label 的索引 issue
3. **逐个处理 decision tickets** — 每张 ticket 解决一个待决策问题
4. **路径清晰后 hand off** — 转给 `/to-tickets` 或直接 `/implement`

**本项目典型场景：**
- 「巡检系统 v3：支持多厂商设备 + AI 异常检测」（太大，需要先做技术选型）
- 「数据库从 SQLite 迁移到 PostgreSQL」（风险高，需要逐步决策）
- 「前后端分离重构」（涉及多个子系统）

---

## 三、本项目推荐使用顺序

基于 `xunjian_system1` 当前状态（v2 单引擎架构刚上线），推荐的技能使用顺序：

### 第 1 步：建立领域基础

```
/domain-modeling
```

- 检查 `CONTEXT.md` 是否存在且完整
- 统一术语：设备分类、巡检项、能力感知、合规检查、CMDB 同步等
- 记录已有的架构决策到 `docs/adr/`

### 第 2 步：扫描架构现状

```
/improve-codebase-architecture
```

- 重点关注 `app02/engine/`、`app02/parsers/`、`app02/views.py`
- 找 shallow modules → deep modules 的机会
- 生成报告，选 2-3 个最有价值的深化项

### 第 3 步：从需求到交付

根据需求类型选择入口：

| 需求类型 | 入口技能 |
|----------|----------|
| 新增功能（需求明确） | `/to-spec` → `/to-tickets` → `/implement` |
| 新增功能（需求模糊） | `/to-questionnaire` → `/to-spec` → `/to-tickets` → `/implement` |
| 架构重构 | `/request-refactor-plan` → `/implement` |
| 大规模改动 | `/wayfinder` → `/to-tickets` → `/implement` |
| Bug 修复 | `/tdd`（写复现测试）→ 修复 → `/code-review` |

### 第 4 步：交付质量把关

- **每个 ticket 完成后：** `/code-review`
- **合并前：** `/code-review` 从 `main...HEAD`
- **用户验收：** `/qa`（对话式提交 issue）

---

## 四、技能协作关系图

```
                    ┌──────────────────────┐
                    │  /domain-modeling     │ ← 基础设施
                    │  /codebase-design     │ ← 共享词汇
                    └────────┬─────────────┘
                             │ 被依赖
        ┌────────────────────┼────────────────────┐
        ▼                    ▼                    ▼
┌───────────────┐   ┌───────────────┐   ┌───────────────────┐
│ /to-question- │   │ /improve-     │   │ /design-an-       │
│   naire       │   │ codebase-     │   │ interface         │
│               │   │ architecture  │   │                   │
└───────┬───────┘   └───────┬───────┘   └─────────┬─────────┘
        │                   │                     │
        ▼                   ▼                     │
┌───────────────┐   ┌───────────────┐              │
│   /to-spec    │   │ /request-     │              │
│               │   │ refactor-plan │              │
└───────┬───────┘   └───────┬───────┘              │
        │                   │                     │
        └─────────┬─────────┘                     │
                  ▼                               │
        ┌───────────────────┐                     │
        │   /to-tickets     │◄────────────────────┘
        └─────────┬─────────┘
                  │
        ┌─────────┼─────────┐
        ▼         ▼         ▼
┌───────────┐ ┌───────────┐ ┌───────────┐
│  /tdd     │ │/implement │ │/code-     │
│           │ │           │ │ review    │
└───────────┘ └───────────┘ └───────────┘

   大规模入口：/wayfinder → /to-tickets → /implement
```

---

## 五、使用技巧

### 5.1 强制加载 Skill

如果 Agent 没有自动识别应该使用某个 skill，可以手动触发：

```
/skill:to-spec 把刚才讨论的内容写成规范
/skill:code-review 审查最近3个commit
/skill:improve-codebase-architecture 扫描 app02/engine/
```

### 5.2 组合使用

```
# 一条链走到底
/skill:to-spec 新增巡检报告邮件推送功能
/skill:to-tickets
/skill:implement

# 审查后再改进
/skill:implement   # 实现
/skill:code-review # 审查
/skill:grill-me    # 对审查结果追问打磨
```

### 5.3 并行子代理

以下技能内部已使用并行子代理，无需手动并行：

- `/code-review` — Standards 轴和 Spec 轴并行审查
- `/design-an-interface` — 多个接口方案并行生成
- `/research` — 多来源并行调研

---

## 六、项目配置文件

本项目已配置的 Agent 基础设施：

| 文件 | 用途 |
|------|------|
| `CLAUDE.md` | Agent 项目指令（issue tracker、triage labels、domain docs） |
| `docs/agents/issue-tracker.md` | Issue tracker（GitHub Issues）操作规范 |
| `docs/agents/triage-labels.md` | Triage labels 定义 |
| `docs/agents/domain.md` | Domain docs 布局规范 |
| `docs/skills-workflow-guide.md` | 本文档 |

> 以上配置由 `/setup-matt-pocock-skills` 生成，后续可用 `docs/agents/` 下的规范文件指导 `/triage`、`/to-spec`、`/to-tickets`、`/wayfinder` 等技能的 tracker 操作。
