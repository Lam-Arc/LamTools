# Unified Execution Engine Implementation Plan

> **For agentic workers:** Use executing-plans skill to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace 4 separate strategy executors with a unified ExecutionEngine that uses `reference_step_indices` to declare step-to-step relationships, enabling checkpoint integration inside plan execution and consistent image passing between steps.

**Architecture:** ExecutionEngine is a step-by-step state machine. Each step's reference images and prompt context are computed by StepContextResolver based on `reference_step_indices` and completed step results. The engine handles sequential and concurrent step groups. executor_node calls engine.step() per step, with interrupt() for checkpoints — no plan decomposition.

**Tech Stack:** Python 3.14+ / Pydantic v2 / SQLAlchemy async / LangGraph StateGraph

---

## Task 1: Add StepContext model to execution.py

**Files:** `backend/app/schemas/execution.py`

**Steps:**
- [ ] Add `StepContext` class with fields: `reference_images: list[str]`, `reference_labels: list[dict]`, `prompt_suffix: str`
- [ ] Add `crop_from_anchor: bool = False` and `crop_region: dict = {}` to `PlanStep.metadata` default (document in PlanStep docstring, not as explicit field — metadata already accepts arbitrary dict)
- [ ] No changes to StepTrace, ExecutionTrace, ExecutionPlan — they remain backward-compatible

**Verification:**
- [ ] `py -3.14 -c "from app.schemas.execution import StepContext; print(StepContext())"` runs without error
- [ ] Existing `ExecutionPlan.from_steps()` still works with unchanged test data

**Commit:** `feat: add StepContext model for unified execution engine`

---

## Task 2: Create ExecutionEngine + StepContextResolver

**Files:** `backend/app/services/executors/engine.py` (NEW)

**Steps:**
- [ ] Create `StepContextResolver` class with `resolve()` async method:
  - Always include `initial_context.reference_images` as base refs
  - Convert `initial_context.context_reference_urls` via `urls_to_base64()` and append
  - If `step.reference_step_indices` is set, for each index: get `completed[idx].urls[:1]`, convert via `urls_to_base64()`, append to refs
  - If `step.metadata.get("crop_from_anchor")`: get anchor step output URL, call `_crop_single_cell()` with `crop_region` from metadata, append cropped base64 to refs. On crop failure, fallback: convert anchor URL to base64 via `urls_to_base64()` and append whole image
  - If `step.metadata.get("prompt_suffix")`: set `StepContext.prompt_suffix`
  - Return `StepContext(reference_images=refs[:4], reference_labels=labels, prompt_suffix=...)`
- [ ] Create `_crop_single_cell(anchor_url, crop_region)` async function:
  - Download anchor image (handle both HTTP URL and data URL)
  - Compute grid layout from `plan_meta.items` length via `_compute_grid_config()`
  - Crop the cell at `(row, col)` from crop_region
  - Return base64 data URL of cropped cell, or empty string on failure
  - Migrate `_compute_grid_config()` from radiate.py
- [ ] Create `ExecutionEngine` class:
  - `__init__(self, plan: ExecutionPlan, context: PlanningContext)` — store plan, context, init completed=[], current_index=0, resolver=StepContextResolver(), trace=ExecutionTrace(...)
  - `is_done` property: `current_index >= len(plan.steps)`
  - `async step(self, db, task_manager) -> StepResult`:
    1. Get `plan.steps[current_index]`
    2. Call `resolver.resolve(step, completed, context, plan.plan_meta)`
    3. Build final_prompt = step.prompt + step_ctx.prompt_suffix (if non-empty)
    4. Call `generate_images_core(db, provider_id, final_prompt, image_count, image_size, negative_prompt, reference_images=step_ctx.reference_images or None, reference_labels=step_ctx.reference_labels or None, session_id)`
    5. Create StepResult (reuse StepTrace model: step_index, status="completed", artifacts, tokens_in/out, cost)
    6. Call `record_billing()` for this step
    7. Append to completed, update trace, increment current_index
    8. Return result
  - `async run_all(self, db, task_manager) -> ExecutionTrace`:
    1. Group steps into sequential/concurrent groups via `group_steps()`
    2. For each group: if single step, call step(); if concurrent, call run_parallel_group()
    3. Return trace
  - `group_steps(self) -> list[list[int]]`:
    1. Build dependency graph from `reference_step_indices`
    2. Steps with no dependencies and same dependency set can be concurrent
    3. Return list of groups (each group is list of step indices)
  - `async run_parallel_group(self, db, task_manager, indices: list[int]) -> list[StepResult]`:
    1. For each index, compute StepContext (all share same initial_context since no cross-dependencies)
    2. Use `asyncio.gather()` with semaphore (from `max_concurrent` setting) to call generate_images_core concurrently
    3. Record billing for each
    4. Append all results to completed, update trace
    5. Return results
  - `rollback_step(self)` — pop last completed result, decrement current_index (for retry_step)

**Verification:**
- [ ] `py -3.14 -c "from app.services.executors.engine import ExecutionEngine, StepContextResolver; print('OK')"` runs without error
- [ ] Engine can be instantiated with a simple ExecutionPlan

**Commit:** `feat: create unified ExecutionEngine with StepContextResolver`

---

## Task 3: Update PlanExecutionService to use ExecutionEngine

**Files:** `backend/app/services/plan_execution_service.py`

**Steps:**
- [ ] Remove `_EXECUTORS` dict and executor class imports
- [ ] Change `execute()` method:
  ```python
  async def execute(self, db, plan, context, task_manager) -> ExecutionTrace:
      engine = ExecutionEngine(plan, context)
      return await engine.run_all(db, task_manager)
  ```
- [ ] Keep `PlanExecutionService` class name and `execute()` signature unchanged for backward compatibility

**Verification:**
- [ ] Non-agent mode `handle_generate()` still works: creates single-strategy plan, calls `PlanExecutionService().execute()`, gets `ExecutionTrace`
- [ ] `handle_execute_plan()` still works with parallel/iterative/radiate strategies

**Commit:** `refactor: PlanExecutionService delegates to ExecutionEngine`

---

## Task 4: Delete old executor files

**Files:**
- `backend/app/services/executors/single.py` (DELETE)
- `backend/app/services/executors/parallel.py` (DELETE)
- `backend/app/services/executors/iterative.py` (DELETE)
- `backend/app/services/executors/radiate.py` (DELETE)
- `backend/app/services/executors/base.py` (DELETE)

**Steps:**
- [ ] Delete all 5 files
- [ ] Update `backend/app/services/executors/__init__.py` — remove old executor imports, add `from app.services.executors.engine import ExecutionEngine, StepContextResolver`

**Verification:**
- [ ] No import errors anywhere in the codebase referencing old executors
- [ ] `py -3.14 -c "from app.services.executors import ExecutionEngine; print('OK')"` works

**Commit:** `refactor: remove old strategy executors, replaced by ExecutionEngine`

---

## Task 5: Refactor executor_node to use ExecutionEngine.step()

**Files:** `backend/app/core/agent/graph.py`

**Steps:**
- [ ] Replace entire `executor_node()` function body:
  1. Parse plan and context from state (same as current)
  2. Create `ExecutionEngine(plan, context)`
  3. Compute step groups via `engine.group_steps()`
  4. Iterate groups:
     - Single step group: call `engine.step(db, task_manager)`
     - Concurrent group: call `engine.run_parallel_group(db, task_manager, group)`
  5. After each step, check `step.checkpoint`:
     - If `checkpoint.enabled`: publish SSE checkpoint_required event, call `interrupt()`
     - On resume: if action=="replan", return status="replan_needed"; if action=="retry_step", call `engine.rollback_step()` then re-execute
  6. Collect artifacts, tokens, cost from engine.trace
  7. Return state update dict with artifacts, total_tokens_in/out, cost, status="executed"
- [ ] Remove `_collect_trace()` helper (logic now in engine)
- [ ] Keep all `_after_*` edge functions unchanged
- [ ] Keep `build_agent_graph()` and `build_agent_mode_graph()` unchanged (node names and edges same)

**Verification:**
- [ ] Agent mode generation still works end-to-end
- [ ] Checkpoint interrupt/resume cycle works (approve, retry_step, replan)
- [ ] Iterative strategy passes previous step images to next step correctly

**Commit:** `refactor: executor_node uses ExecutionEngine.step() with native checkpoint`

---

## Task 6: Update planner_node for reference_step_indices auto-completion

**Files:** `backend/app/core/agent/nodes/planner_node.py`

**Steps:**
- [ ] After LLM plan parsing (around line 230-242), add post-processing:
  ```python
  # Auto-complete reference_step_indices based on strategy
  if strategy == "iterative" and len(plan_steps) > 1:
      for i, step in enumerate(plan_steps):
          if i > 0 and not step.reference_step_indices:
              step.reference_step_indices = [i - 1]

  if strategy == "radiate":
      items = plan_dict.get("plan_meta", {}).get("items", [])
      n_items = len(items) if isinstance(items, list) else 0
      cols, rows = _compute_grid_config(n_items)  # migrated from radiate.py
      style_desc = plan_dict.get("plan_meta", {}).get("style", "")
      for i, step in enumerate(plan_steps):
          if i > 0:
              if not step.reference_step_indices:
                  step.reference_step_indices = [0]
              row, col = _grid_position(i - 1, cols, rows)
              step.metadata["crop_from_anchor"] = True
              step.metadata["crop_region"] = {"row": row, "col": col}
              if style_desc:
                  step.metadata["prompt_suffix"] = f"{style_desc} style."
  ```
- [ ] Add `_grid_position(index, cols, rows)` helper: `row = index // cols, col = index % cols`
- [ ] Import `_compute_grid_config` from `app.services.executors.engine` (or define locally since it's small)
- [ ] Remove the existing "auto-add checkpoint to iterative step 0" logic (lines 251-254) — checkpoint decision stays in planner_node but the auto-add can remain as-is, it's orthogonal to this refactor

**Verification:**
- [ ] Iterative plan from LLM always has `reference_step_indices` on steps > 0
- [ ] Radiate plan from LLM always has `reference_step_indices=[0]` and `crop_from_anchor` metadata on sub-item steps
- [ ] Single and parallel plans have no `reference_step_indices` (or None)

**Commit:** `feat: planner_node auto-completes reference_step_indices and radiate metadata`

---

## Task 7: Update capability_prompts.py for stronger reference_step_indices guidance

**Files:** `backend/app/core/agent/capability_prompts.py`

**Steps:**
- [ ] Update `PLANNER_STRATEGY_GUIDE` iterative section:
  - Change "Step N should have reference_step_indices=[N-1]" to "Step N MUST have reference_step_indices=[N-1]. This is REQUIRED, not optional."
  - Add example JSON showing reference_step_indices
- [ ] Update radiate section:
  - Add: "Each sub-item step MUST have reference_step_indices=[0] (the anchor step)."
  - Add: "Each sub-item step MUST include metadata with crop_from_anchor=true and crop_region={row: R, col: C}."
  - Add grid position explanation
- [ ] Update `STRATEGY_EXECUTION_MECHANISM` to mention reference_step_indices as the core mechanism for step-to-step image passing

**Verification:**
- [ ] Planner LLM outputs include reference_step_indices more consistently
- [ ] No syntax errors in prompt strings

**Commit:** `feat: strengthen reference_step_indices guidance in planner prompts`

---

## Task 8: Update executors/utils.py — keep tools, remove resolve_context_references

**Files:** `backend/app/services/executors/utils.py`

**Steps:**
- [ ] Remove `resolve_context_references()` function (logic moved to StepContextResolver)
- [ ] Keep `get_provider()` and `now_iso()` — still used by engine for billing
- [ ] Keep `ImageClient.urls_to_base64` reference (used by resolver)

**Verification:**
- [ ] No code references `resolve_context_references` from utils.py anymore
- [ ] Engine imports `get_provider` and `now_iso` from utils.py successfully

**Commit:** `refactor: remove resolve_context_references from utils, kept in StepContextResolver`

---

## Task 9: Verify backward compatibility — non-agent paths

**Files:** None (verification only)

**Steps:**
- [ ] Start backend: `cd backend && py -3.14 -m uvicorn app.main:app --reload`
- [ ] Test `POST /api/sessions/{id}/generate` (non-agent mode) — should work identically
- [ ] Test `POST /api/sessions/{id}/execute-plan` with strategy=parallel — should work identically
- [ ] Test `POST /api/sessions/{id}/execute-plan` with strategy=iterative — should pass previous step images to next step (this is the bug fix)
- [ ] Test `POST /api/sessions/{id}/execute-plan` with strategy=radiate — should generate anchor grid, crop, expand

**Verification:**
- [ ] All 3 non-agent generation paths produce images without errors
- [ ] Iterative strategy correctly passes images between steps (check billing records for reference_images count)
- [ ] Radiate strategy produces anchor + expanded items

**Commit:** (no commit — verification step)

---

## Task 10: Verify agent mode end-to-end

**Files:** None (verification only)

**Steps:**
- [ ] Test agent mode with single strategy prompt: "画一只猫"
- [ ] Test agent mode with iterative strategy prompt: "先画草图再精修一只猫"
- [ ] Test agent mode with radiate strategy prompt: "做一套4个表情包"
- [ ] Test checkpoint approve/reject cycle on iterative task
- [ ] Test critic + decision retry flow

**Verification:**
- [ ] Agent mode single/iterative/radiate all produce images
- [ ] Checkpoint interrupt/resume works
- [ ] Critic scoring and decision routing works
- [ ] SSE events flow correctly (task_progress, agent_token, checkpoint_required, agent_done)

**Commit:** (no commit — verification step)

---

## Task 11: Clean up — remove pyc cache files

**Files:** `backend/app/services/executors/` — .pyc files

**Steps:**
- [ ] Delete all `.pyc` files in executors directory that reference old executor names
- [ ] Run `py -3.14 -m py_compile app.services.executors.engine` to verify new module compiles

**Verification:**
- [ ] No stale .pyc files referencing deleted modules
- [ ] New engine module compiles cleanly

**Commit:** `chore: clean up executor pyc cache files`

---

## Summary of Changes

| Category | Files | Net Lines |
|----------|-------|-----------|
| New | `engine.py` | ~250 |
| Modified | `execution.py`, `plan_execution_service.py`, `graph.py`, `planner_node.py`, `capability_prompts.py`, `utils.py` | ~200 |
| Deleted | `single.py`, `parallel.py`, `iterative.py`, `radiate.py`, `base.py` | -610 |
| **Total** | | **~-160 net** |

## Key Design Decisions

1. **StepContextResolver computes per-step context** — strategy logic is expressed via `reference_step_indices` in the plan, not hardcoded in executor classes
2. **Radiate crop mapping via metadata** — `crop_from_anchor` + `crop_region` in `PlanStep.metadata` tells resolver to crop a specific cell from the anchor step's output
3. **ExecutionEngine.step() is the atomic unit** — executor_node calls step() per step, enabling natural checkpoint integration
4. **PlanExecutionService.execute() preserved** — non-agent callers don't change; internally delegates to engine.run_all()
5. **Auto-completion in planner_node** — if LLM doesn't output reference_step_indices, post-processing fills them based on strategy
6. **urls_to_base64 in resolver** — ensures all reference images are base64 format, fixing the URL/base64 inconsistency bug