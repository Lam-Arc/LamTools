# Artist 长任务编排 — 实施计划

> **For agentic workers:** Use executing-plans or subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Artist 模式支持多步骤长任务编排（自动拆分批量请求、进度追踪、暂停/恢复/取消）

**Architecture:** 在 ArtistRuntime 中新增 `plan_complex_task` 和 `delegate_to_agent` 两种 action 分支；新增 TaskOrchestrator 作为长任务调度器，复用现有 ExecutionEngine 执行单步；新增 10 种 SSE 事件和前端 LongTaskCard 组件

**Tech Stack:** Python 3.14+ / FastAPI / SQLAlchemy async / Vue3 (Composition API) / TypeScript / Pinia

**Source Design:** [docs/plans/2026-05-29-artist-long-task-orchestration.md](./2026-05-29-artist-long-task-orchestration.md)

---

## Task 1: 新增 long_task Pydantic Schema

**Files:** 新建 `backend/app/schemas/long_task.py`

**Steps:**
- [ ] Step 1: 创建文件 `backend/app/schemas/long_task.py`
- [ ] Step 2: 定义 `LongTaskStep` — 含 index, name, prompt, status, artifact_urls, artifact_type, reference_step_indices, started_at, completed_at, error, metadata
- [ ] Step 3: 定义 `LongTaskPlan` — 含 task_run_id, session_id, name, strategy, total_steps, steps: list[LongTaskStep], status, completed_steps, failed_steps, created_at, started_at, completed_at, plan_meta
- [ ] Step 4: 定义 `LongTaskRun` — 含 task_run_id, session_id, plan: LongTaskPlan, current_step_index, status, artifacts: list[dict], tokens_in, tokens_out, cost, created_at, updated_at
- [ ] Step 5: 所有 Pydantic model 使用 `model_config = ConfigDict(from_attributes=True)`
- [ ] Step 6: 使用 Python 3.14+ 语法 (`X | None` 非 `Optional[X]`)

**Verification:**
- [ ] `py -3.14 -c "from app.schemas.long_task import LongTaskStep, LongTaskPlan, LongTaskRun; print('OK')"` 无错误

**Commit:** `feat: add LongTaskStep, LongTaskPlan, LongTaskRun Pydantic schemas`

---

## Task 2: 新增 LongTaskRunModel SQLAlchemy 模型

**Files:** 新建 `backend/app/models/long_task.py`

**Steps:**
- [ ] Step 1: 创建文件 `backend/app/models/long_task.py`
- [ ] Step 2: 定义 `LongTaskRunModel(Base)` 表名 `long_task_runs`，列: id(String PK), session_id(String FK→sessions.id), name(String 200), plan_json(JSON), current_step(Integer), status(String 20), artifacts_json(JSON), tokens_in(Integer), tokens_out(Integer), cost(Numeric 10,6), created_at(DateTime), updated_at(DateTime)
- [ ] Step 3: 导入 `gen_uuid` 和 `now` 从 `app.models.base`
- [ ] Step 4: 在 `backend/app/models/__init__.py` 中导出 `LongTaskRunModel`

**Verification:**
- [ ] `py -3.14 -c "from app.models.long_task import LongTaskRunModel; print('OK')"` 无错误
- [ ] 数据库自动创建 `long_task_runs` 表（重启后端后检查）

**Commit:** `feat: add LongTaskRunModel DB model`

---

## Task 3: 扩展 ArtistAction type literal 和 ArtistSessionState

**Files:** 修改 `backend/app/core/artist/schemas.py`

**Steps:**
- [ ] Step 1: 在 `ArtistActionType` Literal 联合类型中新增 `"plan_complex_task"`, `"delegate_to_agent"` 两个值
- [ ] Step 2: 在 `IMAGE_ACTION_TYPES` 集合中新增 `"plan_complex_task"`, `"delegate_to_agent"`
- [ ] Step 3: 在 `ArtistAction` 模型中新增强字段: `plan_strategy: str = ""`, `max_steps: int = 50`, `delegate_reason: str = ""`（用于 plan_complex_task 和 delegate_to_agent 的元信息）
- [ ] Step 4: 在 `ArtistSessionState` 中新增字段: `active_long_task_id: str = ""` (当前活跃长任务 ID)

**Verification:**
- [ ] `py -3.14 -c "from app.core.artist.schemas import ArtistAction, ArtistSessionState; a = ArtistAction(type='plan_complex_task'); print(a.type)"` → 输出 `plan_complex_task`
- [ ] `py -3.14 -c "from app.core.artist.schemas import IMAGE_ACTION_TYPES; assert 'plan_complex_task' in IMAGE_ACTION_TYPES"` 无错误

**Commit:** `feat: add plan_complex_task, delegate_to_agent to ArtistActionType`

---

## Task 4: 扩展 ArtistRuntime.handle_turn 支持 plan_complex_task 和 delegate_to_agent 分支

**Files:** 修改 `backend/app/core/artist/runtime.py`
**Files:** 修改 `backend/app/core/artist/turn_parser.py`

**Steps:**
- [ ] Step 1: 在 `infer_strategy()` 函数中新增对 `plan_complex_task` 的判断：返回 `"long_task"` 策略
- [ ] Step 2: 在 `turn_parser.py` 的 `_split_blocks` 中保留 `plan_complex_task` 和 `delegate_to_agent` 的 action，不让它们被过滤
- [ ] Step 3: 在 `handle_turn()` 的 action 分离逻辑中（`non_gen_actions` vs `gen_actions`），将 `plan_complex_task` 和 `delegate_to_agent` 归入 `gen_actions`（因为它触发实际生成操作）
- [ ] Step 4: 在 `handle_turn()` 的 `gen_actions` 处理块中，检测 `infer_strategy(gen_actions) == "long_task"`：
  - 若是 `plan_complex_task`：从 action 提取 `series_prompts` 和 `series_style_lock`，构建 `LongTaskPlan`，发射 `long_task_created` + `long_task_progress` 事件，**不在当前 turn 内执行**，而是返回 `{"deferred_long_task": true, "long_task_plan": plan}`
  - 若是 `delegate_to_agent`：发射 `artist_action_started` + `artist_thinking`，返回 `{"delegate_to_agent": true, "sub_prompt": action.prompt}`
- [ ] Step 5: 在 `handle_turn()` 返回值 dict 中增加可选字段 `"deferred_long_task": bool`、`"long_task_plan": LongTaskPlan | None`、`"delegate_to_agent": bool`

**Verification:**
- [ ] `py -3.14 -c "from app.core.artist.runtime import infer_strategy; from app.core.artist.schemas import ArtistAction; a = ArtistAction(type='plan_complex_task'); assert infer_strategy([a]) == 'long_task'"` 无错误
- [ ] 启动后端，发送含 `plan_complex_task` 的模拟请求，检查返回的 `deferred_long_task` 为 `true`

**Commit:** `feat: add plan_complex_task and delegate_to_agent branches in ArtistRuntime`

---

## Task 5: 新增 long_task SSE 事件工厂函数

**Files:** 修改 `backend/app/core/artist/events.py`

**Steps:**
- [ ] Step 1: 在 `events.py` 末尾新增 10 个事件工厂函数，每个返回 dict（与现有风格一致，无 class）：
  - `long_task_created(session_id, task_run_id, name, total_steps, strategy) -> dict`
  - `long_task_step_started(session_id, task_run_id, step_index, step_name, prompt) -> dict`
  - `long_task_step_completed(session_id, task_run_id, step_index, artifact_urls, tokens, cost) -> dict`
  - `long_task_step_failed(session_id, task_run_id, step_index, error, retry_count) -> dict`
  - `long_task_progress(session_id, task_run_id, completed, total, failed, current_step_name) -> dict`
  - `long_task_paused(session_id, task_run_id, completed, total, paused_at) -> dict`
  - `long_task_resumed(session_id, task_run_id, resumed_at) -> dict`
  - `long_task_completed(session_id, task_run_id, total_artifacts, total_tokens, total_cost) -> dict`
  - `long_task_cancelled(session_id, task_run_id, reason) -> dict`
  - `long_task_checkpoint(session_id, task_run_id, step_index, error, actions) -> dict`
- [ ] Step 2: 所有返回 dict 的 type 字段使用 `long_task_*` 前缀

**Verification:**
- [ ] `py -3.14 -c "from app.core.artist.events import long_task_created, long_task_progress; print(long_task_created('s1', 'r1', 'test', 10, 'radiate'))"` → 输出完整 dict

**Commit:** `feat: add 10 long_task SSE event factory functions`

---

## Task 6: 创建 TaskOrchestrator 核心类

**Files:** 新建 `backend/app/services/executors/orchestrator.py`

**Steps:**
- [ ] Step 1: 创建文件 `backend/app/services/executors/orchestrator.py`
- [ ] Step 2: 定义 `OrchestratorDeps` dataclass，含:
  - `db_session_factory: Callable`（用于创建独立 DB session）
  - `execution_engine_run: Callable`（传入 ExecutionEngine 执行回调）
  - `event_publish: Callable`（SSE 事件发布回调）
  - `image_provider_id: str`
  - `default_count: int`, `default_size: str`, `negative_prompt: str`
- [ ] Step 3: 定义 `TaskOrchestrator` 类：
  - `__init__(self, deps: OrchestratorDeps)`
  - `async start(plan: LongTaskPlan, session_id, artist_turn_id) -> str`: 保存 LongTaskRun 到 DB，发射 `long_task_created`，启动 `_run` 后台协程，返回 `task_run_id`
  - `async pause(task_run_id) -> None`: 设置 `_pause_events[task_run_id]` 信号，等待当前步骤完成
  - `async resume(task_run_id) -> None`: 清除 pause 信号，发射 `long_task_resumed`
  - `async cancel(task_run_id) -> None`: 设置 cancel 信号，发射 `long_task_cancelled`
  - `async _run(task_run_id, session_id, artist_turn_id) -> None`: 内部协程 — 循环步骤，每步之间 `await asyncio.sleep(0)` + 检查暂停/取消
  - `async _execute_step(step, task_run_id, session_id, artist_turn_id) -> None`: 单步执行 → 构建 PlanStep → 构建 ExecutionPlan(single) → 调用 `execution_engine_run` → 发射事件
  - `async _handle_step_failure(step, task_run_id, session_id, artist_turn_id, error, retry_count) -> str`: 失败处理 → 重试或发射 checkpoint
- [ ] Step 4: 使用 `_pause_events: dict[str, asyncio.Event]` 和 `_cancel_events: dict[str, asyncio.Event]` 进行并发控制
- [ ] Step 5: 每 5 步自动 `_persist_run()` 持久化到 DB

**Verification:**
- [ ] 单元测试：mock `execution_engine_run`，启动 orchestrator（3 步骤），验证 `long_task_created` → `long_task_step_started`(x3) → `long_task_step_completed`(x3) → `long_task_progress`(x3) → `long_task_completed` 事件顺序
- [ ] 单元测试：启动 10 步骤，在第 5 步后调用 `pause()`，验证 `long_task_paused` 事件 + 步骤不超过 5；再调 `resume()`，验证继续执行

**Commit:** `feat: add TaskOrchestrator core class`

---

## Task 7: 扩展 artist_service.py 集成 TaskOrchestrator

**Files:** 修改 `backend/app/services/artist_service.py`

**Steps:**
- [ ] Step 1: 在 `artist_service.py` 顶部导入 `TaskOrchestrator`, `OrchestratorDeps` 和 `long_task_*` 事件工厂
- [ ] Step 2: 新增辅助函数 `_build_orchestrator_deps(db, session_id, image_provider_id, default_count, default_size, negative_prompt, task_manager) -> OrchestratorDeps` — 构建 orchestrator 依赖
- [ ] Step 3: 在 `artist_orchestrate()` 中新增 `orchestrator_deps` 参数
- [ ] Step 4: 修改 `_event_publish` 回调，新增 `long_task_created/started/completed/progress/paused/resumed/cancelled/checkpoint` 事件的转发
- [ ] Step 5: 在 `artist_orchestrate()` 的返回值处理中检测 `result.get("deferred_long_task")`：
  - 若为 true：创建 `TaskOrchestrator` → 调用 `orchestrator.start(plan, session_id, artist_turn_id)` → 立即返回（后台执行）
  - 将 `task_run_id` 存入返回结果的 `metadata`

**Verification:**
- [ ] 集成测试：发送 `plan_complex_task` action 的模拟请求 → 验证返回含 `long_task_run_id` 且任务在后台正确执行

**Commit:** `feat: integrate TaskOrchestrator into artist_service.py`

---

## Task 8: 新增 long_task API 路由

**Files:** 新建 `backend/app/routers/long_task.py`
**Files:** 修改 `backend/app/main.py`（注册路由）

**Steps:**
- [ ] Step 1: 创建 `backend/app/routers/long_task.py`
- [ ] Step 2: 定义 5 个端点：
  - `GET /api/sessions/{session_id}/long-tasks` — 获取会话所有长任务列表
  - `GET /api/sessions/{session_id}/long-task/{task_run_id}` — 获取单个长任务状态
  - `POST /api/sessions/{session_id}/long-task/{task_run_id}/pause` — 暂停
  - `POST /api/sessions/{session_id}/long-task/{task_run_id}/resume` — 恢复
  - `POST /api/sessions/{session_id}/long-task/{task_run_id}/cancel` — 取消
  - `POST /api/sessions/{session_id}/long-task/{task_run_id}/checkpoint` — 步骤级检查点响应（body: `{"action": "skip|retry|abort"}`）
- [ ] Step 3: 每个端点通过依赖注入获取 `db: AsyncSession`，查询 `LongTaskRunModel`
- [ ] Step 4: pause/resume/cancel 端点调用 `TaskOrchestrator` 单例的对应方法
- [ ] Step 5: 在 `backend/app/main.py` 中 `app.include_router(long_task_router, prefix="/api")`

**Verification:**
- [ ] 用 `curl` 测试所有 6 个端点返回 200
- [ ] pause/resume 后 GET 状态反映正确 status

**Commit:** `feat: add long_task API routes (list/get/pause/resume/cancel/checkpoint)`

---

## Task 9: 扩展前端 types 定义

**Files:** 修改 `frontend/src/types/index.ts`

**Steps:**
- [ ] Step 1: 新增接口 `LongTaskStep`：`{ index: number; name: string; prompt: string; status: 'pending'|'running'|'completed'|'failed'|'skipped'; artifact_urls: string[]; error?: string }`
- [ ] Step 2: 新增接口 `LongTaskState`：`{ sessionId: string; taskRunId: string; name: string; totalSteps: number; completedSteps: number; failedSteps: number; status: 'running'|'paused'|'completed'|'failed'|'cancelled'; steps: LongTaskStep[]; currentStepName: string; cost: number | null; startedAt: number | null }`
- [ ] Step 3: 在 `LamEventPayload` 接口中新增可选字段：`task_run_id?: string`, `step_index?: number`, `step_name?: string`

**Verification:**
- [ ] `npx vue-tsc --noEmit` 无类型错误（在前端项目目录下执行）

**Commit:** `feat: add LongTaskStep and LongTaskState TypeScript types`

---

## Task 10: 扩展前端 sessionStore 添加 long_task handlers

**Files:** 修改 `frontend/src/stores/session.ts`

**Steps:**
- [ ] Step 1: 新增 reactive `longTaskStates: Map<string, LongTaskState>`（与 `artistStreamStates` 同级）
- [ ] Step 2: 新增 11 个 handler 函数（与 `handleArtistTurnStarted` 同级模式）：
  - `handleLongTaskCreated(sessionId, event)` — 创建 `LongTaskState`，初始化 steps 为空数组
  - `handleLongTaskStepStarted(sessionId, event)` — 更新 `currentStepName`，追加 step 到 steps 数组（status=`running`）
  - `handleLongTaskStepCompleted(sessionId, event)` — 找到对应 step 设为 `completed`，`completedSteps++`，设置 artifact_urls
  - `handleLongTaskStepFailed(sessionId, event)` — 找到对应 step 设为 `failed`，`failedSteps++`，设置 error
  - `handleLongTaskProgress(sessionId, event)` — 更新 `completedSteps`, `failedSteps`, `currentStepName`
  - `handleLongTaskPaused(sessionId, event)` — `status = 'paused'`
  - `handleLongTaskResumed(sessionId, event)` — `status = 'running'`
  - `handleLongTaskCompleted(sessionId, event)` — `status = 'completed'`，记录 cost
  - `handleLongTaskCancelled(sessionId, event)` — `status = 'cancelled'`
  - `handleLongTaskCheckpoint(sessionId, event)` — 设置 checkpoint state（复用现有 `CheckpointInfo` 模式）
- [ ] Step 3: 新增 `clearLongTaskState(sessionId)` / `getLongTaskState(sessionId)` 辅助函数
- [ ] Step 4: 在 `handleArtistFinalize` 中新增清理 `longTaskStates.delete(sessionId)`
- [ ] Step 5: 在 `handleTaskCompleted` 中新增清理 `longTaskStates.delete(sessionId)`
- [ ] Step 6: 在 `return` 导出对象中新增所有 handler 和 getter

**Verification:**
- [ ] `npx vue-tsc --noEmit` 无类型错误
- [ ] 在浏览器 console 手动调用 `store.handleLongTaskCreated(...)`，验证 `store.longTaskStates` 更新

**Commit:** `feat: add long_task handlers to sessionStore`

---

## Task 11: 创建 LongTaskCard 前端组件

**Files:** 新建 `frontend/src/components/session/LongTaskCard.vue`

**Steps:**
- [ ] Step 1: 创建文件 `LongTaskCard.vue`，使用 `<script setup lang="ts">`
- [ ] Step 2: Props 定义：`taskState: LongTaskState`
- [ ] Step 3: 模板结构：
  - 顶部：任务名称 + 状态标签（运行中/暂停/完成/失败/取消）
  - 进度条：`completedSteps / totalSteps` 百分比（含 failed 红色部分）
  - 步骤列表（可折叠）：每个 step 显示序号、名称、状态图标（✓/⟳/✗/—）、缩略图（artifact_urls[0]）、prompt 摘要
  - 底部操作栏：暂停/继续/取消按钮（根据 status 动态显示）
- [ ] Step 4: Emit 事件：`@pause`, `@resume`, `@cancel`
- [ ] Step 5: 状态图标使用 Lucide icons: `Check`(完成), `Loader2`(运行, 旋转), `X`(失败), `Minus`(跳过)
- [ ] Step 6: 颜色方案与项目一致（#FAFAFA bg, #000 accent, #E5E5E5 border）
- [ ] Step 7: 无 emoji，使用纯文本和 Lucide 图标

**Verification:**
- [ ] `npx vue-tsc --noEmit` 无错误
- [ ] 在 MessageList 中临时嵌入，用 mock 数据验证渲染正确

**Commit:** `feat: add LongTaskCard component with progress bar and step list`

---

## Task 12: 前端 SSE 事件路由集成

**Files:** 修改 `frontend/src/views/Sessions.vue`
**Files:** 修改 `frontend/src/components/session/MessageList.vue`

**Steps:**
- [ ] Step 1: 在 `Sessions.vue` 的 `onAgentEvent` 回调中新增 10 个 case（`long_task_*`），分发到 `store` 对应 handlers（pattern 与现有 artist 事件一致）
- [ ] Step 2: 在 `MessageList.vue` 中检测 `longTaskState` 存在且 status 不为 `completed`/`cancelled` 时，渲染 `LongTaskCard` 组件（在现有 artist 流式渲染块之前或之后）
- [ ] Step 3: 在 `MessageList.vue` 中为已保存消息（`msg.metadata.long_task_run_id` 存在）渲染已完成的长任务摘要卡片
- [ ] Step 4: 连接 LongTaskCard 的 `@pause`/`@resume`/`@cancel` 事件到对应的 API 调用（通过 `sessionApi` 新增方法或内联 fetch）

**Verification:**
- [ ] 启动后端 + 前端，触发 `plan_complex_task` action → 验证 LongTaskCard 实时渲染
- [ ] 点击暂停 → 验证步骤停在当前位置，状态变为 paused
- [ ] 点击继续 → 验证从暂停点恢复

**Commit:** `feat: integrate long_task SSE events into frontend views`

---

## Task 13: 集成测试 — Artist 长任务编排 pipeline

**Files:** 新建 `backend/tests/test_long_task_pipeline.py`

**Steps:**
- [ ] Step 1: 创建集成测试文件
- [ ] Step 2: Mock 外部 API（LLM + 生图），不 mock 内部模块
- [ ] Step 3: 测试用例 1 `test_plan_complex_task_action_creates_orchestrator`:
  - 构造含 `plan_complex_task` action 的 `ArtistTurn`
  - Mock `execution_engine_run` 返回正确的 ExecutionTrace
  - 调用 `handle_turn()` → 验证 `result["deferred_long_task"] == True`
- [ ] Step 4: 测试用例 2 `test_orchestrator_executes_all_steps`:
  - 创建 `LongTaskPlan`（5 步骤）
  - 启动 `TaskOrchestrator.start()`
  - 验证所有步骤 status 为 `completed`
  - 验证事件序列正确
- [ ] Step 5: 测试用例 3 `test_orchestrator_pause_resume`:
  - 创建 `LongTaskPlan`（10 步骤）
  - 在第 3 步后调用 `pause()`
  - 验证 steps 3-9 为 `pending`
  - 调用 `resume()`
  - 验证 steps 3-9 为 `completed`
- [ ] Step 6: 测试用例 4 `test_orchestrator_cancel`:
  - 创建 `LongTaskPlan`（10 步骤）
  - 在第 3 步后调用 `cancel()`
  - 验证 steps 3-9 为 `skipped`
  - 验证 `long_task_cancelled` 事件
- [ ] Step 7: 测试用例 5 `test_plan_complex_task_prompt_injection`:
  - 验证 ARTIST_TURN_SYSTEM prompt 包含 `plan_complex_task` 的使用说明

**Verification:**
- [ ] `py -3.14 -m pytest backend/tests/test_long_task_pipeline.py -v` → 5/5 passed

**Commit:** `test: add long_task orchestration pipeline tests`

---

## Task 14: 前端 API client 扩展

**Files:** 修改 `frontend/src/api/session.ts`

**Steps:**
- [ ] Step 1: 新增方法：
  - `getLongTasks(sessionId: string)` → `GET /api/sessions/{sessionId}/long-tasks`
  - `getLongTask(sessionId: string, taskRunId: string)` → `GET /api/sessions/{sessionId}/long-task/{taskRunId}`
  - `pauseLongTask(sessionId: string, taskRunId: string)` → `POST /api/sessions/{sessionId}/long-task/{taskRunId}/pause`
  - `resumeLongTask(sessionId: string, taskRunId: string)` → `POST /api/sessions/{sessionId}/long-task/{taskRunId}/resume`
  - `cancelLongTask(sessionId: string, taskRunId: string)` → `POST /api/sessions/{sessionId}/long-task/{taskRunId}/cancel`
  - `checkpointLongTask(sessionId: string, taskRunId: string, action: string)` → `POST /api/sessions/{sessionId}/long-task/{taskRunId}/checkpoint`
- [ ] Step 2: 使用现有 Axios 实例 `api`，保持与现有方法一致的风格

**Verification:**
- [ ] `npx vue-tsc --noEmit` 无错误

**Commit:** `feat: add long_task API client methods`

---

## Task 15: 自审 + 收尾

**Files:** 审核所有改动

**Steps:**
- [ ] Step 1: 运行 `cd backend && py -3.14 -m pytest backend/tests/test_long_task_pipeline.py -v` → 全部通过
- [ ] Step 2: 运行 `cd frontend && npx vue-tsc --noEmit` → 无类型错误
- [ ] Step 3: 运行 `cd frontend && npm run build` → 构建成功
- [ ] Step 4: 确认现有 e2e 测试不受影响：`py -3.14 -m pytest backend/tests/test_artist_e2e.py -v -k "not skip"` → 全部通过
- [ ] Step 5: 检查 `artist_service.py` 中 `_event_publish` 新增事件不会导致旧 SSE 客户端报错
- [ ] Step 6: 检查 `LongTaskRunModel` 表 SQLite 迁移无冲突
- [ ] Step 7: 检查 `Message.metadata.long_task_run_id` 字段为可选，旧消息不受影响

**Commit:** 无单独 commit，属于 Task 1-14 完成后的验证

---

## 任务依赖图

```
Task 1 (Schema) ──┐
Task 2 (DB Model) ─┤
                   ├──→ Task 4 (Runtime) ──→ Task 7 (artist_service)
Task 3 (Action+)  ─┤                             │
                   │                             ▼
Task 5 (SSE Events)┤                       Task 8 (API Routes)
                   │                             │
Task 6 (Orchestrator)────────────────────────────┘
                                                 │
                                                 ▼
Task 9 (Types) ──→ Task 10 (Store) ──→ Task 12 (Views)
                      │                    │
Task 11 (Component)───┘                    │
                      │                    │
Task 14 (API Client)──┘                    │
                                           │
Task 13 (Tests)────────────────────────────┤
                                           │
Task 15 (Verify)───────────────────────────┘
```

**可并行执行组**:
- Group A: Task 1 + Task 2 + Task 3 + Task 5（纯数据定义，无依赖）
- Group B: Task 6 + Task 9 + Task 14（Orchestrator + 前端 types + API client）
- Group C: Task 11（LongTaskCard 组件）

**执行顺序**: A → (Task 4 → Task 7 → Task 8) 和 B → Task 10 → Task 12 → Task 13 → Task 15
