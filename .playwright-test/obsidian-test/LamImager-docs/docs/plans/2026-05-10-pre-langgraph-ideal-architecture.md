# Pre-LangGraph Ideal Architecture Implementation Plan

> **For agentic workers:** Use executing-plans or subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在引入 LangGraph 之前，把 LamImager 的 agent 与 plan 执行收敛为统一的 `ExecutionPlan -> Executor -> Artifact/Event` 内核，避免把当前前后端分裂、策略分散、结果不结构化的问题直接迁移到图编排框架里。

**Architecture:** 继续保留当前 FastAPI + Vue3 + TaskManager + tool registry 的基础架构，不引入新框架。先统一四个核心对象：`ExecutionPlan`、`PlanStep`、`Artifact`、`ExecutionTrace`；再统一三个执行器入口：`single`、`parallel`、`iterative`、`radiate`；最后让 Agent 模式与工作台模式都把任务交给同一个 `PlanExecutionService` 执行。

**Tech Stack:** Python / FastAPI / SQLAlchemy async / Vue3 / SSE

---

## 一、为什么在 LangGraph 之前先做这一步

当前系统已经有较强的 agent 能力，但执行架构仍然分散：

- Agent 模式通过 `run_agent_loop()` 做工具调用与结果消费
- 工作台模式在前端 `Sessions.vue` 内自行执行 parallel / iterative
- radiate 策略在后端 `generate_service.py` 里特判执行
- 结果主要以 `image_urls` 和 message 落库，没有统一 artifact 模型
- 事件虽然已有 `TaskManager` 和 `LamEvent` 雏形，但还不是 step 级结构化执行轨迹

如果现在直接引入 LangGraph：

- 只会把当前分散的 parallel / iterative / radiate 逻辑搬进图节点
- 依然没有统一 Plan 对象
- 依然没有统一 Artifact / Trace
- Agent 与 Workbench 还是两套执行路径

因此，**LangGraph 前的理想状态**应该是：

```text
Agent 输入 / Workbench 输入
-> ExecutionPlan
-> PlanExecutionService
-> Strategy Executor
-> Tool Runtime
-> Artifact Store
-> Event Bus
```

到这一步之后，LangGraph 才是“调度器替换”，而不是“救火重构”。

---

## 二、Pre-LangGraph 理想架构

### 2.0 三层输入原则

在进入 Planner 之前，任务不应只由 `prompt` 或 `intent` 单独描述，而应明确包含三个不同语义层：

- **skill**：思考偏置、创作原则、计划总方针
- **context**：用户输入、参考图、上下文图、搜索结果、历史消息、用户偏好
- **plan**：由 planner 输出的执行结构

理想链路应为：

```text
intent + skill + context
-> planner
-> ExecutionPlan
-> PlanExecutionService
-> executor
```

这意味着：

- `skill` 不是 prompt 片段库
- `context` 不是散落在各函数里的参数包
- `plan` 不是万能语义容器，只承载执行结构

### 2.1 双入口，单执行内核

保留两种用户入口，但底层只允许有一个执行内核：

1. **Agent 模式**
   - 用户自然语言输入
   - Agent 负责理解任务，结合 `skill + context` 选择模板、补变量、形成 `ExecutionPlan`
   - 不再直接在 `handle_agent_generate()` 里散落消费 `plan/generate_image` 结果并执行业务分支

2. **Workbench 模式**
   - 用户手动构造步骤、填变量、选策略
   - 前端不再自己执行 parallel / iterative
   - 前端只负责提交 `ExecutionPlan` 到后端统一执行
   - Workbench 也应允许显式选择 `skill` 或调整 `context`，但这些仍然要在 planner 层转译成 plan

二者共享：

```text
ExecutionPlan -> PlanExecutionService -> Executor -> Tool Runtime
```

---

### 2.2 四个必须统一的对象

#### A. `ExecutionPlan`

这是整个执行内核的中心对象。建议结构：

```python
@dataclass
class ExecutionPlan:
    plan_id: str
    source: str                  # agent | workbench | template
    strategy: str                # single | parallel | iterative | radiate
    template_id: str | None
    title: str
    description: str
    steps: list[PlanStep]
    variables: dict
    review_required: bool
    metadata: dict
```

#### B. `PlanStep`

```python
@dataclass
class PlanStep:
    step_id: str
    role: str                    # draft | refine | anchor | expand | generate
    prompt: str
    negative_prompt: str
    image_count: int
    image_size: str
    reference_step_ids: list[str]
    checkpoint: dict | None
    repeat_over: str | None      # e.g. items
    metadata: dict
```

#### C. `Artifact`

```python
@dataclass
class Artifact:
    artifact_id: str
    step_id: str
    type: str                    # image | video | audio | file | text
    url: str
    mime_type: str
    status: str                  # pending | ready | failed | superseded
    metadata: dict
```

#### D. `ExecutionTrace`

```python
@dataclass
class ExecutionTrace:
    trace_id: str
    plan_id: str
    step_id: str | None
    phase: str                   # planning | review | executing | checkpoint | completed | failed
    event_type: str              # tool_call | tool_result | checkpoint_required | retry | artifact_created
    message: str
    payload: dict
    timestamp: int
```

这些对象在 LangGraph 前必须先落地，不然后面没有稳定的 graph state 输入输出模型。

---

### 2.3 统一执行器模型

#### `SingleExecutor`

- 负责单图任务
- 负责少量无依赖的单步任务
- 可直接包住现有 `generate_images_core()`

#### `ParallelExecutor`

- 后端统一执行并发，不再由前端 `Promise` 池控制
- 负责多独立 step 的 plan
- 对应当前 `app/services/plan_executor.py:14-95`

#### `IterativeExecutor`

- 后端统一处理上一步结果传给下一步
- 当前已有雏形：`app/services/plan_executor.py:98-172`
- 需要明确 `reference_step_ids` 和 step 失败恢复策略

#### `RadiateExecutor`

- 负责锚点图 -> checkpoint -> 切格 -> 逐项扩展
- 当前已有雏形：`app/services/generate_service.py:_execute_radiate`
- 需要从 `handle_agent_generate()` 中剥离为独立执行器模块

执行器的目标不是“更聪明”，而是“后端统一执行所有 strategy”。

---

### 2.4 `PlanExecutionService`

在 LangGraph 前，最值得新增的服务类就是它。

职责：

```text
validate plan
-> review plan
-> choose executor
-> execute
-> persist artifacts
-> persist trace
-> emit events
-> finalize billing
```

建议接口：

```python
class PlanExecutionService:
    async def execute_plan(
        self,
        db: AsyncSession,
        session_id: str,
        plan: ExecutionPlan,
        context: ExecutionContext,
    ) -> ExecutionResult:
        ...
```

其中 `ExecutionContext` 负责挂载：

- source_mode: agent / workbench / assistant
- llm_provider_id
- image_provider_id
- session_context
- user_preferences
- cancel_event

当前 `handle_agent_generate()` 和未来工作台执行入口都应该收敛到它。

### 2.4A Planner 与 Prompt Builder 的位置

在 Pre-LangGraph 架构里，LLM 的主要职责不应再是“最终裁决执行器”，而应集中在两层：

1. **Planner**
   - 根据 `intent + skill + context` 生成 `ExecutionPlan`
   - 决定 strategy、steps、依赖、expected outputs

2. **Prompt Builder**
   - 根据 `plan step + skill + context` 生成高质量执行 prompt
   - 当前已存在的 `_generate_iterative_steps()`、`_generate_radiate_params()`、`_generate_item_prompts()` 应逐步归拢到这两层之下

这两层位于 Executor 之前，不能继续散落在执行器内部。

---

### 2.5 Event 与 Artifact 的落地方向

当前系统已有：

- `TaskManager`
- `LamEvent`
- `agent_event_to_lam_event`

Pre-LangGraph 的理想状态不是推翻它们，而是：

1. 保留 `TaskManager.publish()` 和 `/api/sessions/events`
2. 把事件细化到 step 级，而不只是 task 级
3. 把结果从 `image_urls` 提升为 `Artifact`

建议事件类型：

- `plan_created`
- `plan_review_required`
- `plan_review_passed`
- `step_started`
- `step_checkpoint_required`
- `step_retrying`
- `step_completed`
- `artifact_created`
- `task_completed`
- `task_failed`
- `task_cancelled`

这样以后切到 LangGraph，只是“节点状态 -> 事件”的映射，不是重新发明协议。

---

## 三、当前代码文件 -> 理想模块映射表

### 3.1 Agent / Plan 相关现状映射

| 当前文件 | 当前职责 | 理想模块去向 | 问题 |
|---|---|---|---|
| `backend/app/services/agent_service.py` | `AGENT_SYSTEM_PROMPT`、`run_agent_loop()`、工具调度、token/tool 事件 | `core/agent_runtime/` | 过于偏“循环调度”，尚未对接统一 `ExecutionPlan` |
| `backend/app/services/generate_service.py` | `handle_generate()`、`handle_agent_generate()`、`_execute_radiate()`、图片上下文处理 | `imager/application/` + `imager/executors/` + `imager/planning/` | 混合了入口、策略分发、具体执行、消息持久化，且部分 Planner / Prompt Builder 逻辑仍散落其中 |
| `backend/app/services/plan_executor.py` | `execute_parallel()`、`execute_iterative()` | `imager/executors/` | 已经是统一执行器雏形，但还没收敛到 `ExecutionPlan` |
| `backend/app/tools/plan.py` | agent 的 plan tool：list/apply/create | `core/tools/` + `imager/planning/` | 只生成 steps/meta，未输出统一 `ExecutionPlan`，也没有显式接收 `skill/context` 约束 |
| `backend/app/services/plan_template_service.py` | 模板 CRUD、apply、内置模板 seed | `imager/planning/templates/` | 模板层独立了，但 apply 产物还是裸 dict steps |
| `backend/app/services/skill_engine.py` / `skills` 表 | 当前主要用于普通生成路径的 skill 拼接 | `imager/planning/skills/` | 语义层正确，但未真正进入 agent / planner 主链 |
| `frontend/src/views/Sessions.vue` | Agent UI + Workbench UI + 部分前端执行逻辑 | `ui/agent` + `ui/workbench` | 仍承载工作台执行器逻辑，应该只负责构造/提交 plan |
| `backend/app/services/task_manager.py` | task 状态、订阅、广播、checkpoint state | `core/events/` | 已有事件总线雏形，但还不够 step 级 |
| `backend/app/core/events.py` 或相关模块 | `LamEvent`（若已存在） | `core/events/` | 需要和 `ExecutionTrace`/step event 统一 |

### 3.2 未来建议模块目录（引入 LangGraph 前）

建议在现有仓库内先形成逻辑目录，而不必立刻拆包：

```text
backend/app/
├── core/
│   ├── agent_runtime/          # run_agent_loop, agent events, intent bridge
│   ├── tools/                  # Tool, ToolResult, registry
│   ├── events/                 # LamEvent, TaskManager, Event publishing
│   └── billing/                # calc_cost, record_billing
├── imager/
│   ├── planning/
│   │   ├── models.py           # ExecutionPlan, PlanStep, PlanReviewResult
│   │   ├── templates.py        # plan_template_service
│   │   └── review.py           # plan validation / review
│   ├── executors/
│   │   ├── single.py
│   │   ├── parallel.py
│   │   ├── iterative.py
│   │   └── radiate.py
│   ├── runtime/
│   │   ├── artifacts.py        # Artifact models / persistence
│   │   ├── traces.py           # ExecutionTrace
│   │   └── execution_service.py
│   └── entrypoints/
│       ├── agent_generate.py   # handle_agent_generate 拆分后入口
│       └── workbench_generate.py
```

这一步做完后，再引入 LangGraph，只需要把：

- `agent_runtime`
- `planning/review`
- `runtime/execution_service`

三层接到 graph 节点上。

---

## 四、对这份理想架构的审查

### 4.1 优点

1. **不脱离当前代码**
   - `plan_executor.py` 已经有 parallel / iterative 雏形
   - `run_agent_loop()` 已经稳定
   - `TaskManager` 和 `LamEvent` 已有基础
   - 这份架构不是推翻重写，而是收敛职责

2. **能解决当前最核心的分裂问题**
   - 工作台模式不再在前端执行 parallel / iterative
   - radiate 不再散落在 `handle_agent_generate()` 里特判
   - plan tool 不再只是“返回步骤”，而是真正产出 `ExecutionPlan`

3. **能平滑接 LamAssistant**
   - Assistant 不需要知道 radiate / iterative 的细节
   - 只需要提交 `ExecutionPlan` 或自然语言

4. **LangGraph 接入成本最低**
   - graph state 可以直接是 `ExecutionPlan` / `ExecutionTrace`
   - executor 直接作为 graph 节点调用

### 4.2 风险

1. **短期后端复杂度上升**
   - 现在部分执行逻辑在前端，迁回后端会增加后端职责
   - 但这是集中复杂度，不是新增复杂度

2. **工作台 UI 改造成本不小**
   - 当前 `Sessions.vue` 同时承担输入、规划、执行、展示
   - 改造成“只提交 plan”后，前端需要重新组织状态

3. **容易过度设计 `ExecutionPlan`**
   - 现在不应该一次把条件分支、子 plan、插件节点全部塞进去
   - 建议先只覆盖当前四种 strategy 的最小字段集

4. **Agent 可能继续绕过 PlanExecutionService**
   - 如果 `handle_agent_generate()` 继续自己消费 `plan/generate_image` tool 结果并直接执行业务分支，统一内核就会失效
   - 这是过渡阶段最需要警惕的风险

### 4.3 结论

这是**在不引入 LangGraph 的前提下，当前项目最值得追求的理想架构**。

它的核心价值不在于“更聪明”，而在于：

- 把当前分散在前端/后端/agent prompt/tool meta 中的执行语义收敛到 `ExecutionPlan`
- 把当前零散的结果收敛到 `Artifact`
- 把当前粗粒度的状态广播收敛到 `ExecutionTrace / step events`
- 让 LangGraph 未来只接管“编排”，而不是替你清理混乱

---

## 五、最小实现顺序（引入 LangGraph 前）

### Phase A：先统一对象

1. `ExecutionPlan`
2. `PlanStep`
3. `Artifact`
4. `ExecutionTrace`

### Phase B：再统一后端执行层

1. `PlanExecutionService`
2. `SingleExecutor`
3. `ParallelExecutor`
4. `IterativeExecutor`
5. `RadiateExecutor`

### Phase C：最后收敛入口

1. Agent 模式输出 `ExecutionPlan`
2. Workbench 模式提交 `ExecutionPlan`
3. 全部统一走 `PlanExecutionService`

到这一步，LangGraph 才值得引入。

---

## 六、与当前代码最直接对应的下一步

如果只选 3 件最值得先做的事：

1. **把 `handle_agent_generate()` 中 parallel / iterative / radiate 的策略分支抽到统一的 `PlanExecutionService`**
2. **让 Workbench 模式不再前端执行步骤，而是提交统一 plan 给后端执行**
3. **把 `image_urls` 提升为 `Artifact`，给每张图挂上 `step_id`**

这三件事做完，LangGraph 的引入就不是“救火”，而是“升级调度器”。
