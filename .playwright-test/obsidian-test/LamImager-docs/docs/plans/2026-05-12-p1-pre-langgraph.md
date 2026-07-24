# P1 Pre-LangGraph Implementation Plan

> **Status:** Active working draft. This document supersedes `2026-05-10-pre-langgraph-implementation.md` as the current P1施工文档. The 2026-05-10 document is retained as a predecessor/reference snapshot for rationale and task history.

> **For agentic workers:** Use executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a unified planning/execution model layer that decouples intent parsing from execution, enabling all strategies (single, parallel, iterative, radiate) to flow through a common `ExecutionPlan` → `PlanExecutionService` pipeline.

**Architecture:** Introduce `PlanningContext` as the unified input bag, `ExecutionPlan`/`PlanStep`/`Artifact`/`ExecutionTrace` as the structured intermediate representation, and `PlanExecutionService` as the single execution entry point. Skills provide planning bias / constraint inputs to Planner and Prompt Builder, but do **not** directly own execution steps. Template `apply()` outputs `ExecutionPlan`-compatible structures.

**Tech Stack:** Python 3.14+ / Pydantic v2 / SQLAlchemy 2.0 async / dataclasses

---

## Group 1: Core Models + Template Output Unification

### Task 0: PlanningContext 与 skill 接口位

**Files:**
- `backend/app/schemas/planning.py` (new)

**Steps:**
- [ ] Create `PlanningContext` Pydantic model that aggregates all inputs needed for planning:
  - `session_id: str`
  - `prompt: str`
  - `negative_prompt: str = ""`
  - `image_count: int = 1`
  - `image_size: str = "1024x1024"`
  - `reference_images: list[str] = []`
  - `reference_labels: list[dict] = []`
  - `context_messages: list[dict] = []`
  - `skill_ids: list[str] = []`
  - `optimize_directions: list[str] = []`
  - `custom_optimize_instruction: str = ""`
  - `agent_mode: bool = False`
  - `agent_tools: list[str] = []`
  - `agent_plan_strategy: str = ""`
  - `image_provider_id: str | None = None`
  - `llm_provider_id: str | None = None`
  - `search_context: str = ""`
  - `context_images: list[str] | None = None`
- [ ] Add `from_planning_context` class method to `PlanningContext` that accepts a `GenerateRequest` + resolved provider IDs and constructs the context
- [ ] Add `SkillInterface` protocol class with `name`, `description`, `prompt_template`, `parameters`, `strategy_hint` (optional), `planning_bias` (optional), `constraints` (optional) — defines the contract for skill-as-planner-input, not skill-as-plan

**Verification:**
- [ ] `py -3.14 -c "from app.schemas.planning import PlanningContext, SkillInterface; print('OK')"` from backend dir

**Commit:** `feat(p1): add PlanningContext and SkillInterface`

---

### Task 1: ExecutionPlan / PlanStep / Artifact / ExecutionTrace 模型

**Files:**
- `backend/app/schemas/execution.py` (new)

**Steps:**
- [ ] Create `Artifact` Pydantic model:
  - `type: str` (e.g. "image", "text")
  - `url: str = ""`
  - `data: str = ""` (for base64)
  - `metadata: dict = {}`
- [ ] Create `PlanStep` Pydantic model:
  - `index: int`
  - `prompt: str`
  - `negative_prompt: str = ""`
  - `description: str = ""`
  - `image_count: int = 1`
  - `image_size: str = ""`
  - `reference_step_indices: list[int] | None = None`
  - `checkpoint: dict | None = None`
  - `condition: dict | None = None`
  - `role: str = ""` (for radiate: "anchor", "expand")
  - `repeat: str = ""` (for radiate: "items")
  - `metadata: dict = {}`
- [ ] Create `StepTrace` Pydantic model:
  - `step_index: int`
  - `status: str = "pending"` (pending/running/completed/failed)
  - `artifacts: list[Artifact] = []`
  - `tokens_in: int = 0`
  - `tokens_out: int = 0`
  - `cost: float = 0.0`
  - `error: str = ""`
  - `started_at: str = ""`
  - `completed_at: str = ""`
- [ ] Create `ExecutionPlan` Pydantic model:
  - `id: str = ""` (auto UUID)
  - `strategy: str` (single/parallel/iterative/radiate)
  - `steps: list[PlanStep] = []`
  - `intent_meta: dict = {}` (carries AgentIntent info)
  - `plan_meta: dict = {}` (carries radiate items/style/theme)
  - `source: str = ""` (e.g. "agent_intent", "template", "skill")
- [ ] Create `ExecutionTrace` Pydantic model:
  - `plan_id: str`
  - `strategy: str`
  - `step_traces: list[StepTrace] = []`
  - `total_tokens_in: int = 0`
  - `total_tokens_out: int = 0`
  - `total_cost: float = 0.0`
  - `status: str = "pending"` (pending/running/completed/failed)
  - `error: str = ""`
- [ ] Add `ExecutionPlan.from_steps()` factory that converts `list[dict]` (legacy format) to `ExecutionPlan`
- [ ] Add `ExecutionPlan.to_steps_dict()` method that converts back to `list[dict]` for backward compatibility

**Verification:**
- [ ] `py -3.14 -c "from app.schemas.execution import ExecutionPlan, PlanStep, Artifact, ExecutionTrace, StepTrace; p = ExecutionPlan(strategy='single', steps=[PlanStep(index=0, prompt='test')]); print(p.model_dump_json()[:80])"` from backend dir

**Commit:** `feat(p1): add ExecutionPlan/PlanStep/Artifact/ExecutionTrace models`

---

### Task 1A: 重定义 skill 数据模型

**Files:**
- `backend/app/models/skill.py` (modify)
- `backend/app/schemas/skill.py` (modify)
- `backend/app/services/skill_engine.py` (modify)

**Steps:**
- [ ] Add `strategy_hint` column to `Skill` SQLAlchemy model: `strategy_hint: Mapped[str] = mapped_column(String(20), default="")`
- [ ] Add `planning_bias` column to `Skill` SQLAlchemy model: `planning_bias: Mapped[dict] = mapped_column(JSON, default=dict)`
- [ ] Add `constraints` column to `Skill` SQLAlchemy model: `constraints: Mapped[dict] = mapped_column(JSON, default=dict)`
- [ ] Add `prompt_bias` column to `Skill` SQLAlchemy model: `prompt_bias: Mapped[dict] = mapped_column(JSON, default=dict)`
- [ ] Update `SkillCreate` schema: add `strategy_hint: str = ""`, `planning_bias: dict = {}`, `constraints: dict = {}`, `prompt_bias: dict = {}`
- [ ] Update `SkillUpdate` schema: add `strategy_hint: str | None = None`, `planning_bias: dict | None = None`, `constraints: dict | None = None`, `prompt_bias: dict | None = None`
- [ ] Update `SkillResponse` schema: add `strategy_hint: str`, `planning_bias: dict`, `constraints: dict`, `prompt_bias: dict`
- [ ] Update `skill_engine.py` `create_skill()` / `update_skill()` to persist these fields
- [ ] Update `skill_engine.py` `apply_skill()` — when a skill contains bias/constraint fields, return planner hints or a constraint object, **not** an `ExecutionPlan`
- [ ] Add `skill_to_planner_hints()` helper in `skill_engine.py` that converts a skill into planner constraints and prompt bias without embedding steps

**Verification:**
- [ ] `py -3.14 -c "from app.models.skill import Skill; s = Skill(name='test', strategy_hint='iterative', planning_bias={'consistency':'high'}, constraints={'max_steps':3}, prompt_bias={'detail_level':'rich'}); print(s.strategy_hint, s.planning_bias, s.constraints, s.prompt_bias)"` from backend dir

**Commit:** `refactor(skill): redefine skills as planner bias/constraint carriers`

---

### Task 2: 模板 apply 输出 ExecutionPlan 兼容结构

**Files:**
- `backend/app/services/plan_template_service.py` (modify)
- `backend/app/schemas/plan_template.py` (modify)

**Steps:**
- [ ] Add `PlanTemplateApplyResponse` schema in `plan_template.py` that wraps `ExecutionPlan`:
  - `template_id: str`
  - `template_name: str`
  - `plan: ExecutionPlan`
- [ ] Modify `apply_template()` in `plan_template_service.py` to return `ExecutionPlan` instead of `list[dict]`:
  - Build `PlanStep` objects from the applied step dicts
  - Set `strategy` from template
  - Set `source = "template"`
  - Set `plan_meta` with template variables
- [ ] Update the router endpoint that calls `apply_template()` to handle the new return type (backward-compatible: also expose `steps` as `list[dict]` in response)

**Verification:**
- [ ] `py -3.14 -c "from app.services.plan_template_service import apply_template; print('signature updated')"` from backend dir (import check)

**Commit:** `feat(p1): template apply returns ExecutionPlan`

---

### Task 3: PlanExecutionService 入口

**Files:**
- `backend/app/services/plan_execution_service.py` (new)

**Steps:**
- [ ] Create `PlanExecutionService` class with `execute()` method:
  - Signature: `async def execute(self, db: AsyncSession, plan: ExecutionPlan, context: PlanningContext, task_manager: TaskManager) -> ExecutionTrace`
  - Routes to executor based on `plan.strategy`:
    - `"single"` → `_execute_single_plan()`
    - `"parallel"` → `_execute_parallel_plan()`
    - `"iterative"` → `_execute_iterative_plan()`
    - `"radiate"` → `_execute_radiate_plan()`
  - Each executor creates `StepTrace` objects and builds `ExecutionTrace`
- [ ] Implement `_execute_single_plan()`:
  - Extract first step's prompt/params
  - Call `generate_images_core()` with context's provider
  - Build `StepTrace` with `Artifact` for each image URL
  - Record billing
- [ ] Implement `_execute_parallel_plan()`:
  - Use semaphore for concurrency
  - Call `generate_images_core()` per step
  - Build `StepTrace` per step
  - Record billing per step
- [ ] Implement `_execute_iterative_plan()`:
  - Sequential execution, pass previous step's images as reference
  - Build `StepTrace` per step
  - Record billing per step
- [ ] Implement `_execute_radiate_plan()`:
  - Stub for now — delegates to existing `_execute_radiate()` logic (will be fully migrated in Task 7)
  - Build `StepTrace` for anchor + each item
- [ ] Add `from app.services.plan_execution_service import PlanExecutionService` to verify import

**Verification:**
- [ ] `py -3.14 -c "from app.services.plan_execution_service import PlanExecutionService; print('OK')"` from backend dir

**Commit:** `feat(p1): add PlanExecutionService entry point`

---

## Group 2: Four Executors Converge to Backend (Tasks 4-7) — ✅ COMPLETED

### Scope

- `single` / `parallel` / `iterative` / `radiate` 四种策略统一收敛到后端执行器
- `generate_images_core()` 继续作为底层图像生成基础
- `radiate` 保留特殊优化，但从入口特判逻辑中剥离

### Completed tasks

- Task 4: ✅ SingleExecutor — `backend/app/services/executors/single.py`
- Task 5: ✅ ParallelExecutor — `backend/app/services/executors/parallel.py`
- Task 6: ✅ IterativeExecutor — `backend/app/services/executors/iterative.py`
- Task 7: ✅ RadiateExecutor — `backend/app/services/executors/radiate.py`
- PlanExecutionService 重构为委托模式，路由到独立执行器

## Group 3: Two Entry Points Converge (Tasks 7A-9)

### Scope

- `skill` 真正进入 planner / agent 主链
- Agent 模式不再通过散落分支手动消费 `plan` 结果
- Workbench 模式不再前端执行步骤

### Completed tasks

- Task 7A: ✅ skill 有 strategy+steps 时返回 ExecutionPlan，通过 `_execute_skill_plan` → `PlanExecutionService` 执行
- Task 8: ✅ `handle_agent_generate` 重构为 `_build_execution_plan()` → `PlanExecutionService.execute()` 统一入口
- Task 9: ✅ 新增 `POST /api/sessions/{id}/execute-plan` 端点，前端 `executePlan()` 改为单次后端调用

### Design review fixes

- ✅ `_get_provider` / `now_iso` 抽取到 `executors/utils.py`，4 个执行器共享
- ✅ `resolve_context_references()` 统一 context_reference_urls 处理，parallel/iterative 补齐
- ✅ 执行器 `generate_images_core` 改为 lazy import，打破循环依赖

## Group 4: Structured Results + Regression Tests (Tasks 10-11)

### Scope

- `image_urls` 升级为 `Artifact`
- `steps` 升级为 `ExecutionTrace`
- 增加回归验证，防止 P1 收敛后回退

### Completed tasks

- Task 10: ✅ `handle_generate` 通过 `PlanExecutionService` 执行，返回结构化 `ExecutionTrace`（含 `Artifact` + `StepTrace`）
- Task 11: ✅ 7 项回归测试全部通过 + 前端构建通过

### Bug fixes

- ✅ `apply_skill()` `{{prompt}}` 模板语法替换 bug 修复
- ✅ `generate_service.py` 清理未使用 import（`run_agent_loop`, `execute_multi_independent`, `execute_parallel`, `execute_iterative`）
