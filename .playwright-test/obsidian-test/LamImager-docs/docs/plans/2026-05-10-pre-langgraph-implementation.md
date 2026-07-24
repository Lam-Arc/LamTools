# Pre-LangGraph Architecture Implementation Plan

> **For agentic workers:** Use executing-plans or subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不引入 LangGraph 的前提下，把 LamImager 当前分散的 agent / plan / executor / result 路径收敛为统一的 `ExecutionPlan -> PlanExecutionService -> Executor -> Artifact/Event` 执行内核。

**Architecture:** 先定义统一的数据模型与服务边界，再把后端执行器完整化，最后让 Agent 模式与 Workbench 模式都提交 `ExecutionPlan` 到同一个后端执行入口。当前已有的 `run_agent_loop`、`TaskManager`、`plan_executor.py`、`generate_images_core()` 全部保留并重用，不做大框架替换。

**Tech Stack:** Python / FastAPI / SQLAlchemy async / Vue3 / SSE

---

## 设计一致性审查

本计划基于以下 3 份文档汇总而来：

- `docs/plans/2026-05-10-pre-langgraph-ideal-architecture.md`
- `docs/plans/2026-05-09-lamtools-ecosystem.md`
- `docs/plans/2026-05-09-plan-system-gaps.md`

### 已一致的部分

- 需要在 LangGraph 前先统一 Plan / Executor / Artifact / Event
- 后端已经开始收敛 `parallel` / `iterative` 到 `plan_executor.py`
- `TaskManager` + `LamEvent` 是未来 Event Bus 的基础
- `handle_agent_generate()` 是当前最需要收敛的入口

### 当前文档之间的不一致

1. `2026-05-09-plan-system-gaps.md` 重点修的是 plan 缺口，但没有把 `ExecutionPlan` / `Artifact` / `ExecutionTrace` 提升为一级任务。
2. `2026-05-09-lamtools-ecosystem.md` 的 Phase 1 更偏生态目录重组，没有把 Workbench 执行器后移到后端作为 Phase 1 强制要求。
3. `2026-05-10-pre-langgraph-ideal-architecture.md` 给出了理想模块，但没有落成可执行任务清单。
4. 当前计划还没有把 `skill / context / plan` 的语义边界正式纳入实施顺序，容易导致 skill 继续废弃、context 继续散传、plan 继续过载。

### 本文档的作用

这份计划专门补上上述空白：

- 把“理想架构”翻译成可实施任务
- 保证任务顺序与设计目标一致
- 不与 Phase 0 上线目标冲突

---

## 实施边界

本计划 **不做** 的事：

- 不引入 LangGraph
- 不做 monorepo 迁移
- 不做 LamAssistant 跨产品调用
- 不重构成桌面壳

本计划 **必须完成** 的事：

- 让 `skill / context / plan` 三层至少具备接口位与最小语义边界
- 统一 `ExecutionPlan`
- 统一后端执行器
- 统一 artifact 与 step 级 trace
- 让 Agent / Workbench 共享一个后端执行入口

---

## Task 0: 新增 PlanningContext 与 skill 接口位

**Files:**
- `backend/app/imager/planning/context.py` (new)
- `backend/app/imager/planning/models.py` (new or merged)

**Steps:**
- [ ] 新建 `PlanningContext` 数据结构，至少包含：`prompt`、`context_images`、`reference_images`、`reference_labels`、`search_context`、`intent`、`expected_count`、`user_preferences`
- [ ] 在文档和模型层明确 `skill` 将来作为 planner 输入的一部分，而不是直接进入 executor
- [ ] 为 `ExecutionPlan` 预留 `skill_constraints` 或等价字段入口位

**Verification:**
- [ ] 后续 Planner / Prompt Builder 都可以统一接收 `PlanningContext`
- [ ] skill 不会再被迫以 prompt 片段方式混入 plan

**Commit:** `feat(planning): add PlanningContext and reserve skill constraints input`

---

## Task 1: 新增核心执行模型

**Files:**
- `backend/app/imager/planning/models.py` (new)
- `backend/app/imager/runtime/models.py` (new)

**Steps:**
- [ ] 新建 `ExecutionPlan` dataclass，字段至少包含：`plan_id`、`source`、`strategy`、`template_id`、`title`、`description`、`steps`、`variables`、`review_required`、`metadata`
- [ ] 新建 `PlanStep` dataclass，字段至少包含：`step_id`、`role`、`prompt`、`negative_prompt`、`image_count`、`image_size`、`reference_step_ids`、`checkpoint`、`repeat_over`、`metadata`
- [ ] 新建 `Artifact` dataclass，字段至少包含：`artifact_id`、`step_id`、`type`、`url`、`mime_type`、`status`、`metadata`
- [ ] 新建 `ExecutionTrace` dataclass，字段至少包含：`trace_id`、`plan_id`、`step_id`、`phase`、`event_type`、`message`、`payload`、`timestamp`

**Verification:**
- [ ] `python -m py_compile backend\app\imager\planning\models.py`
- [ ] `python -m py_compile backend\app\imager\runtime\models.py`

**Commit:** `feat(plan): add ExecutionPlan PlanStep Artifact and ExecutionTrace models`

---

## Task 1A: 重定义 skill 数据模型与职责

**Files:**
- `backend/app/models/skill.py`
- `backend/app/schemas/skill.py`
- `backend/app/services/skill_engine.py`

**Steps:**
- [ ] 将 skill 从“prompt 片段库”重定义为“思考偏置 / 计划总方针 / 质量约束”载体
- [ ] 设计最小结构：`planning_bias`、`consistency_required`、`constraints`、`prompt_bias`、`search_policy`
- [ ] 明确 skill 不应直接承载具体 step 列表

**Verification:**
- [ ] skill 可以表达“品牌 logo skill”“套图 skill”“先草图再精修 skill”这类偏置
- [ ] skill 与 plan 的语义边界清晰，不再重叠

**Commit:** `refactor(skill): redefine skills as planner inputs instead of prompt snippets`

---

## Task 2: 统一模板 apply 输出为 ExecutionPlan 兼容步骤

**Files:**
- `backend/app/services/plan_template_service.py`
- `backend/app/tools/plan.py`

**Steps:**
- [ ] 在 `apply_template()` 中保留并返回完整 step 语义：`role`、`checkpoint`、`reference_step_indices`、`repeat` 等，而不是只裁剪成 prompt/description/image_count/image_size
- [ ] 为每个 step 注入稳定的 `step_id`（例如 `step-1`, `step-2`）
- [ ] `PlanTool._apply_template()` 返回的 `meta.steps` 必须已经是 ExecutionPlan-compatible step dict，而不是后续执行器再猜结构

**Verification:**
- [ ] `plan(action="apply")` 的 `meta.steps` 中包含 `step_id`
- [ ] radiate 模板的 `role=anchor/expand`、`repeat=items` 被完整保留

**Commit:** `feat(plan): return execution-plan-compatible steps from template apply`

---

## Task 3: 新增 PlanExecutionService

**Files:**
- `backend/app/imager/runtime/execution_service.py` (new)

**Steps:**
- [ ] 新建 `PlanExecutionService.execute_plan(db, session_id, plan, context)` 入口
- [ ] 在服务内实现三段式流程：`validate -> select executor -> persist result`
- [ ] 初版支持 `single` / `parallel` / `iterative` / `radiate` 四种 `strategy`

**Verification:**
- [ ] `python -m py_compile backend\app\imager\runtime\execution_service.py`
- [ ] 代码中不直接依赖前端状态

**Commit:** `feat(runtime): add PlanExecutionService entrypoint`

---

## Task 4: 把 single 执行器显式化

**Files:**
- `backend/app/imager/executors/single.py` (new)
- `backend/app/services/generate_service.py`

**Steps:**
- [ ] 把当前 `generate_images_core()` 的单步消费方式封装成 `execute_single()`
- [ ] `execute_single()` 输入为 `PlanStep`，输出为 `{artifacts, traces, tokens_in, tokens_out}` 风格的结构化结果
- [ ] `handle_generate()` 继续复用 `generate_images_core()`，但 agent/workbench 不再直接调它，而是通过 `execute_single()`

**Verification:**
- [ ] 单图计划可通过 `execute_single()` 产出结构化 artifact
- [ ] 原有普通生图路径行为不变

**Commit:** `refactor(executor): add explicit single executor around generate_images_core`

---

## Task 5: 把 parallel 执行器对接 PlanExecutionService

**Files:**
- `backend/app/services/plan_executor.py`
- `backend/app/imager/runtime/execution_service.py`

**Steps:**
- [ ] 保留现有 `execute_parallel()`，但让它接收 ExecutionPlan-compatible `steps`
- [ ] 返回值从 `{images, steps, ...}` 扩展为可生成 `Artifact` 与 `ExecutionTrace` 的结构
- [ ] `PlanExecutionService` 在 `strategy=parallel` 时统一调用 `execute_parallel()`

**Verification:**
- [ ] `strategy=parallel` 的 plan 不再需要前端 Promise 池即可完成
- [ ] 每个并行 step 都有对应 step_index 或 step_id 元数据

**Commit:** `refactor(executor): route parallel plans through PlanExecutionService`

---

## Task 6: 把 iterative 执行器对接 PlanExecutionService

**Files:**
- `backend/app/services/plan_executor.py`
- `backend/app/imager/runtime/execution_service.py`

**Steps:**
- [ ] 保留现有 `execute_iterative()`，但把“上一步首图作为下一步参考图”的规则明确写入 step 结构与返回结构
- [ ] 为 iterative 结果附带 `reference_from_step_id`
- [ ] `PlanExecutionService` 在 `strategy=iterative` 时统一调用 `execute_iterative()`

**Verification:**
- [ ] iterative plan 执行后，第二步结果 metadata 能追溯它引用了哪个 step
- [ ] 不需要前端自行 fetch 上一步图片再 base64 传给后端

**Commit:** `refactor(executor): route iterative plans through PlanExecutionService`

---

## Task 7: 把 radiate 执行器从 handle_agent_generate 中剥离

**Files:**
- `backend/app/services/generate_service.py`
- `backend/app/imager/executors/radiate.py` (new)
- `backend/app/imager/runtime/execution_service.py`

**Steps:**
- [ ] 把 `_execute_radiate()` 挪到独立 `radiate.py` 模块，保留现有逻辑
- [ ] 调整入参，不再依赖 `event.meta` 和 `handle_agent_generate()` 内部临时变量，而是直接接 `ExecutionPlan` 与 `ExecutionContext`
- [ ] `PlanExecutionService` 在 `strategy=radiate` 时统一调用该执行器

**Verification:**
- [ ] `handle_agent_generate()` 内不再直接特判 `strategy == radiate` 然后执行业务逻辑
- [ ] radiate 执行器仍能完成锚点图 -> 切格 -> expand 流程

**Commit:** `refactor(executor): extract radiate executor and route via PlanExecutionService`

---

## Task 7A: 让 skill 真正进入 planner / agent 主链

**Files:**
- `backend/app/services/generate_service.py`
- `backend/app/services/skill_engine.py`
- `backend/app/imager/planning/`（未来 planner 模块）

**Steps:**
- [ ] 在 Agent 主链中，不再只在普通生成路径调用 skill
- [ ] skill 通过 `PlanningContext` 或 `skill_constraints` 影响 planner / prompt builder
- [ ] 明确 skill 的作用位置：strategy 建议、步骤生成偏置、prompt 生成偏置，而不是 executor

**Verification:**
- [ ] 移除 skill 后，planner / prompt builder 产物应有明显差异
- [ ] skill 不直接决定 executor，不继续与 plan 混层

**Commit:** `feat(agent): inject skill constraints into planning chain`

---

## Task 8: 让 Agent 模式输出 Plan 并交给统一执行入口

**Files:**
- `backend/app/services/generate_service.py`
- `backend/app/tools/plan.py`
- `backend/app/imager/runtime/execution_service.py`

**Steps:**
- [ ] 在 `handle_agent_generate()` 中保留 `run_agent_loop()`，但对 `plan` 工具结果的消费改成：构造 `ExecutionPlan` -> 调 `PlanExecutionService.execute_plan()`
- [ ] `generate_image` 仍可用于单图或少量独立图，但复杂任务一旦进入 `plan` 路径，不再在 `handle_agent_generate()` 中手动分派 parallel / iterative / radiate
- [ ] 将 `steps`、`images`、`tokens` 汇总逻辑从 `handle_agent_generate()` 下沉到 `PlanExecutionService` 结果对象

**Verification:**
- [ ] `handle_agent_generate()` 中不再出现 3 个以上的 `if event.name == "plan" and strategy == ...` 执行分支
- [ ] plan 路径与普通 generate_image 路径都能完成任务

**Commit:** `refactor(agent): make agent consume plan via PlanExecutionService`

---

## Task 9: 让 Workbench 模式不再自行执行步骤

**Files:**
- `frontend/src/views/Sessions.vue`
- `backend/app/routers/session.py`
- `backend/app/imager/runtime/execution_service.py`

**Steps:**
- [ ] 在后端新增一个接收 `ExecutionPlan` 的执行入口，例如 `POST /api/sessions/{id}/plans/execute`
- [ ] 前端 Workbench 模式不再执行 `parallel` / `iterative` 的 Promise / for-loop，而是把编辑好的 steps 提交到后端
- [ ] 前端仅负责 plan 编辑、plan 预览、checkpoint 展示和 SSE 订阅

**Verification:**
- [ ] `Sessions.vue` 中前端 Promise 池与 iterative 执行循环被删除或彻底降级为兼容路径
- [ ] Workbench 提交计划后，真正执行发生在后端

**Commit:** `refactor(workbench): move plan execution from frontend to backend`

---

## Task 10: 把结果从 image_urls 升级为 Artifact + step 级 trace

**Files:**
- `backend/app/imager/runtime/execution_service.py`
- `backend/app/services/session_manager.py`
- `backend/app/services/task_manager.py`

**Steps:**
- [ ] 每个 step 生成的图片都构造成 `Artifact`，至少包含 `artifact_id`、`step_id`、`type=image`、`url`
- [ ] 每个 step 的开始/结束/失败都生成 `ExecutionTrace`
- [ ] `TaskManager.publish()` 时优先广播 step 级事件，前端仍可兼容 task 级状态

**Verification:**
- [ ] 一个多步 plan 执行后，后端能明确回答“第 2 步生成了哪些图”
- [ ] SSE 中能区分 `step_started`、`artifact_created`、`step_completed`

**Commit:** `feat(runtime): add artifacts and step-level execution traces`

---

## Task 11: 增加最小回归测试与接口验证

**Files:**
- `tests/` (new or existing)

**Steps:**
- [ ] 为 `apply_template -> ExecutionPlan-compatible steps` 增加测试
- [ ] 为 `PlanExecutionService` 的四种 strategy 增加最小测试或集成测试桩
- [ ] 为 `Workbench -> 后端 execute plan` 增加至少 1 条集成路径验证

**Verification:**
- [ ] 单图、parallel、iterative、radiate 至少各有 1 个可回归验证入口

**Commit:** `test(runtime): add regression coverage for pre-langgraph execution core`

---

## 执行顺序

### 第一组：先把模型与模板输出统一
- [ ] Task 0
- [ ] Task 1
- [ ] Task 1A
- [ ] Task 2
- [ ] Task 3

### 第二组：把四个执行器统一到后端
- [ ] Task 4
- [ ] Task 5
- [ ] Task 6
- [ ] Task 7

### 第三组：收敛两个入口
- [ ] Task 7A
- [ ] Task 8
- [ ] Task 9

### 第四组：结构化结果与回归验证
- [ ] Task 10
- [ ] Task 11

---

## 与设计的一致性结论

这份实施计划与 `2026-05-10-pre-langgraph-ideal-architecture.md` **一致**，具体体现在：

1. 先统一 `ExecutionPlan / PlanStep / Artifact / ExecutionTrace`
2. 先统一后端执行器，再考虑 LangGraph
3. 让 Agent 与 Workbench 都共享一个 `PlanExecutionService`
4. 不把 LangGraph 当“救火工具”，而是未来的调度升级

这份实施计划也与 `2026-05-09-plan-system-gaps.md` **互补**：

- gaps 文档解决的是缺口与 bug
- 本文档解决的是执行内核的收敛顺序

建议执行方式：

- **先按 gaps 文档完成 P0 / 计划系统显性 bug 修复**
- **再按本文档推进 Pre-LangGraph 核心收敛**
- **最后再进入 LangGraph Phase**
