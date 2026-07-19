<!-- 历史参考，不代表当前架构 -->
# Writer Task System Transformation Plan

> **For agentic workers:** Use executing-plans or subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform Writer from a prototype while-true-loop agent into a stable "task running system" with Project → Session → Step data model, structured events, git version graph, multi-provider config, and a Vue3 workbench frontend.

**Architecture:** Merge the two parallel persistence systems (WriterSession DB + WriterSessionState JSON files) into a single DB model. Add Project and Step as DB models. Collapse 30+ ad-hoc event types into 6 canonical event shapes. Git emits branch-linear timeline (not raw git text). Config supports multi-Provider/Model with per-task-type routing. Frontend rebuilds from vanilla JS to Vue3+Pinia.

**Tech Stack:** Python 3.14+ / FastAPI / SQLAlchemy async / Pydantic / SSE / Vue3 / Pinia / Vue Router

---

## Phase 1: Backend Data Model Foundation (2 days)

### Task 1.1: Add WriterProject DB Model

**Files:**
- `backend/app/models/project.py` (CREATE)
- `backend/app/models/__init__.py` (MODIFY)
- `backend/app/database.py` (VERIFY — no changes needed, auto-migrated)

**Steps:**
- [ ] Create `backend/app/models/project.py` with `WriterProject(Base)` model:
  ```python
  class WriterProject(Base):
      __tablename__ = "writer_projects"
      id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
      name: Mapped[str] = mapped_column(String(255), default="Untitled Project")
      work_root: Mapped[str] = mapped_column(String(1024), default="")
      agents_md: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
      config: Mapped[Optional[dict]] = mapped_column("config", JSON, nullable=True)
      created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
      updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
  ```
- [ ] Update `backend/app/models/__init__.py` to export `WriterProject`
- [ ] Verify: `py -3.14 -m compileall backend/app/models/project.py`

**Verification:**
- [ ] Python import succeeds: `from app.models.project import WriterProject`
- [ ] No syntax errors

**Commit:** `add: WriterProject DB model`

---

### Task 1.2: Add WriterStep DB Model

**Files:**
- `backend/app/models/step.py` (CREATE)
- `backend/app/models/__init__.py` (MODIFY)

**Steps:**
- [ ] Create `backend/app/models/step.py` with `WriterStep(Base)` model:
  ```python
  class WriterStep(Base):
      __tablename__ = "writer_steps"
      id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
      session_id: Mapped[str] = mapped_column(String(36), ForeignKey("writer_sessions.id"), nullable=False)
      step_number: Mapped[int] = mapped_column(default=0)
      step_type: Mapped[str] = mapped_column(String(50), nullable=False)
      # step_type: "plan" | "tool_call" | "tool_result" | "verification" | "decision" | "thought" | "text" | "git_op"
      status: Mapped[str] = mapped_column(String(50), default="pending")
      # status: "pending" | "running" | "completed" | "failed" | "skipped"
      parent_step_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("writer_steps.id"), nullable=True)
      retry_of: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("writer_steps.id"), nullable=True)
      content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
      tool_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
      tool_args: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
      tool_result: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
      tool_result_summary: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
      error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
      retry_count: Mapped[int] = mapped_column(default=0)
      max_retries: Mapped[int] = mapped_column(default=3)
      failure_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
      duration_ms: Mapped[Optional[int]] = mapped_column(nullable=True)
      metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSON, nullable=True)
      created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
      completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
  ```
- [ ] Update `backend/app/models/__init__.py` to export `WriterStep`
- [ ] Verify: `py -3.14 -m compileall backend/app/models/step.py`

**Verification:**
- [ ] Python import succeeds
- [ ] `parent_step_id` and `retry_of` self-referential FKs defined correctly

**Commit:** `add: WriterStep DB model`

---

### Task 1.3: Merge WriterSessionState into WriterSession

**Files:**
- `backend/app/models/session.py` (MODIFY)
- `backend/app/core/writer/state_store.py` (REWRITE)
- `backend/app/core/writer/schemas.py` (MODIFY)

**Steps:**
- [ ] Add new columns to `WriterSession` DB model in `backend/app/models/session.py`:
  - `project_id: Mapped[Optional[str]]` with FK to `writer_projects.id`
  - `loop_position: Mapped[str]` default "execute"
  - `task_complexity: Mapped[str]` default "simple"
  - `planning_depth: Mapped[Optional[str]]`
  - `turn_count: Mapped[int]` default 0
  - `error_count: Mapped[int]` default 0
  - `task_plan: Mapped[Optional[dict]]` JSON column
  - `runtime_state: Mapped[Optional[dict]]` JSON column (for git_state, locked_context, delegation_queue, session_memory, etc.)
- [ ] Rewrite `WriterSessionState` in `schemas.py` to be a Pydantic view model that converts to/from `WriterSession` DB row:
  - Add `@classmethod from_session(cls, session: WriterSession) -> WriterSessionState`
  - Add `def to_session_updates(self) -> dict` — returns only changed fields for DB update
  - The runtime still holds `WriterSessionState` in memory for fast access
  - `runtime_state` JSON blob stores rarely-queried fields (git_state, git_history, locked_context, delegation_queue, pending_decision_points, decision_history, session_memory)
- [ ] Rewrite `WriterStateStore` to use SQLAlchemy instead of JSON files:
  - `get(session_id)` → DB query, then `WriterSessionState.from_session(row)`
  - `save(state)` → `state.to_session_updates()`, then DB update
  - `delete(session_id)` → DB delete
  - `create(session_id, ...)` → DB insert
  - `list_sessions()` → DB query
  - Constructor takes `AsyncSession` factory instead of `data_dir`
- [ ] Add `project_id` column to `WriterSession` migration
- [ ] Verify: `py -3.14 -m compileall backend/app/models/session.py backend/app/core/writer/state_store.py backend/app/core/writer/schemas.py`

**Verification:**
- [ ] `WriterSessionState.from_session()` and `.to_session_updates()` round-trip correctly
- [ ] `WriterStateStore` reads/writes from DB, not JSON files
- [ ] Runtime's `state_store.save(state)` calls still work unchanged (API preserved)

**Commit:** `refactor: merge WriterSessionState into WriterSession DB model`

---

### Task 1.4: Add Project CRUD API Endpoints

**Files:**
- `backend/app/routers/project.py` (CREATE)
- `backend/app/main.py` (MODIFY)

**Steps:**
- [ ] Create `backend/app/routers/project.py` with endpoints:
  - `POST /api/projects` — create project (name, work_root)
  - `GET /api/projects` — list projects (paginated)
  - `GET /api/projects/{project_id}` — get project
  - `PATCH /api/projects/{project_id}` — update project (name, work_root, config)
  - `DELETE /api/projects/{project_id}` — delete project
  - `GET /api/projects/{project_id}/agents-md` — read AGENTS.md content
  - `PUT /api/projects/{project_id}/agents-md` — write/update AGENTS.md content
  - `GET /api/projects/{project_id}/sessions` — list sessions for project
- [ ] Request/response schemas:
  ```python
  class ProjectCreate(BaseModel):
      name: str = "Untitled Project"
      work_root: str = ""
  class ProjectResponse(BaseModel):
      id: str; name: str; work_root: str; agents_md: str | None; config: dict | None; created_at: datetime; updated_at: datetime
  class AgentsMdUpdate(BaseModel):
      content: str
  ```
- [ ] Register router in `main.py`: `app.include_router(project_router, prefix="/api")`
- [ ] Verify: start server, `curl http://localhost:6173/api/health` returns ok

**Verification:**
- [ ] `POST /api/projects` creates a project in DB
- [ ] `GET /api/projects` returns list
- [ ] `PUT /api/projects/{id}/agents-md` writes AGENTS.md to work_root and updates DB

**Commit:** `add: Project CRUD API endpoints`

---

### Task 1.5: Add Step API Endpoints

**Files:**
- `backend/app/routers/step.py` (CREATE)
- `backend/app/main.py` (MODIFY)

**Steps:**
- [ ] Create `backend/app/routers/step.py` with endpoints:
  - `GET /api/sessions/{session_id}/steps` — list steps (paginated, filterable by status/step_type)
  - `GET /api/sessions/{session_id}/steps/{step_id}` — get single step with full content
  - `POST /api/sessions/{session_id}/steps/{step_id}/retry` — retry a failed step
- [ ] Request/response schemas:
  ```python
  class StepResponse(BaseModel):
      id: str; session_id: str; step_number: int; step_type: str; status: str
      parent_step_id: str | None; retry_of: str | None; content: str | None
      tool_name: str | None; tool_args: dict | None; tool_result_summary: str | None
      error: str | None; retry_count: int; failure_reason: str | None; duration_ms: int | None
      created_at: datetime; completed_at: datetime | None
  class StepDetailResponse(StepResponse):
      tool_result: str | None; metadata_: dict | None
  ```
- [ ] Register router in `main.py`
- [ ] Verify: endpoints return 200 with valid data

**Verification:**
- [ ] `GET /api/sessions/{sid}/steps` returns paginated step list
- [ ] Step nesting (parent_step_id) queryable

**Commit:** `add: Step API endpoints`

---

## Phase 2: Structured Events (1 day)

### Task 2.1: Define 6 Canonical Event Types

**Files:**
- `backend/app/core/writer/events.py` (MODIFY)
- `backend/app/core/writer/schemas.py` (MODIFY)

**Steps:**
- [ ] Define 6 canonical SSE event types in `schemas.py`:
  ```python
  class WriterStepEvent(BaseModel):
      """Emitted when a step is created or its status changes."""
      event: Literal["writer_step"] = "writer_step"
      session_id: str
      step: dict  # WriterStep as dict (matches StepResponse schema)
  
  class WriterProgressEvent(BaseModel):
      """Emitted for plan progress, verification, and phase transitions."""
      event: Literal["writer_progress"] = "writer_progress"
      session_id: str
      phase: str | None = None
      loop_position: str | None = None
      mode: str | None = None
      plan_progress: dict | None = None  # {total, completed, failed, pct, current_step, next_step}
      verification: dict | None = None   # {attempt, passed, summary}
  
  class WriterResponseEvent(BaseModel):
      """Emitted for text responses (thought, reply, self-critique)."""
      event: Literal["writer_response"] = "writer_response"
      session_id: str
      text: str
      output_type: str = "text"
      output_meta: dict = {}
  
  class WriterDecisionEvent(BaseModel):
      """Emitted when Writer needs user input (waiting, decision point, plan confirmation)."""
      event: Literal["writer_decision"] = "writer_decision"
      session_id: str
      decision_type: str  # "waiting_for_user" | "decision_point" | "plan_ready"
      title: str = ""
      options: list[dict] = []
      context: dict = {}
  
  class WriterGitEvent(BaseModel):
      """Emitted for git operations (branch, checkpoint, merge, snapshot)."""
      event: Literal["writer_git"] = "writer_git"
      session_id: str
      git_type: str  # "branch" | "checkpoint" | "merge" | "snapshot" | "version_graph"
      data: dict = {}
  
  class WriterLifecycleEvent(BaseModel):
      """Emitted for session lifecycle (done, failed, error, resumed)."""
      event: Literal["writer_lifecycle"] = "writer_lifecycle"
      session_id: str
      lifecycle_type: str  # "done" | "failed" | "error" | "resumed" | "cancelled"
      reason: str = ""
      details: dict = {}
  ```
- [ ] In `events.py`, create new constructors that map old event names to canonical types:
  - `writer_response` / `writer_thought` → `WriterResponseEvent`
  - `writer_phase_changed` / `writer_progress` / `writer_verification_*` → `WriterProgressEvent`
  - `writer_action_started` / `writer_part_updated` / `writer_criteria_verified` → `WriterStepEvent`
  - `writer_waiting_for_user` / `writer_decision_required` / `writer_plan_ready` → `WriterDecisionEvent`
  - `writer_git_*` → `WriterGitEvent`
  - `writer_done` / `writer_failed` / `writer_error` → `WriterLifecycleEvent`
- [ ] Keep old event functions as thin wrappers that call new constructors (backward compat during transition)
- [ ] Verify: `py -3.14 -m compileall backend/app/core/writer/events.py`

**Verification:**
- [ ] All 6 canonical event types defined
- [ ] Old event functions still work (thin wrappers)
- [ ] New constructors produce correct canonical event format

**Commit:** `add: 6 canonical Writer event types`

---

### Task 2.2: Add emit_step() Dual-Write Helper

**Files:**
- `backend/app/core/writer/events.py` (MODIFY)
- `backend/app/core/writer/runtime.py` (MODIFY)

**Steps:**
- [ ] Create `emit_step()` function that:
  1. Creates a `WriterStep` DB row
  2. Emits `WriterStepEvent` SSE event
  3. Returns the created step
- [ ] Signature:
  ```python
  async def emit_step(
      db: AsyncSession,
      event_callback: Callable,
      session_id: str,
      step_number: int,
      step_type: str,
      parent_step_id: str | None = None,
      **kwargs,
  ) -> WriterStep:
  ```
- [ ] Integrate into runtime at key points:
  - `_execute_action()` → creates "tool_call" step (pending→running) + "tool_result" step (parent = tool_call step)
  - Phase transitions → creates "plan"/"verification"/"decision" steps
  - Text responses → creates "thought"/"text" steps
  - Git operations → creates "git_op" steps
- [ ] Each step creation: `step = await emit_step(db, event_callback, session_id, step_number, step_type, ...)`
- [ ] Verify: runtime still runs, SSE events include step data

**Verification:**
- [ ] `emit_step()` writes to DB and emits SSE in one call
- [ ] Steps appear in `GET /api/sessions/{sid}/steps`
- [ ] Runtime loop continues to work correctly

**Commit:** `add: emit_step() dual-write helper and runtime integration`

---

### Task 2.3: Add Step-Level Retry with retry_of Link

**Files:**
- `backend/app/core/writer/runtime.py` (MODIFY)
- `backend/app/routers/step.py` (MODIFY)

**Steps:**
- [ ] In `_execute_action()`, when a tool call fails:
  1. Mark current step as `failed` with `failure_reason`
  2. Increment `retry_count`
  3. If `retry_count < max_retries`, create new step with `retry_of = failed_step.id`
  4. If exhausted, keep step as `failed` (session-level repair mode kicks in)
- [ ] In `POST /api/sessions/{session_id}/steps/{step_id}/retry`:
  1. Load failed step
  2. Create new step with `retry_of = original_step.id`
  3. Inject repair prompt into runtime
  4. Resume runtime
- [ ] Verify: retry chain queryable via `retry_of` field

**Verification:**
- [ ] Failed steps show `retry_of` link to original attempt
- [ ] Retry endpoint creates new step and resumes runtime

**Commit:** `add: step-level retry with retry_of link`

---

## Phase 3: Git Version Graph (1 day)

### Task 3.1: Add Git Version Graph Data Model and API

**Files:**
- `backend/app/core/writer/git.py` (MODIFY)
- `backend/app/routers/session.py` (MODIFY)

**Steps:**
- [ ] Add to `git.py`:
  ```python
  class GitGraphNode(BaseModel):
      hash: str           # Short hash (8 chars)
      message: str        # First line only
      timestamp: datetime
      author: str
      branch: str         # Which branch this commit belongs to
      is_head: bool = False
      is_merge_point: bool = False
      parent_branch: str | None = None
  
  class GitBranchLine(BaseModel):
      branch_name: str
      commits: list[GitGraphNode]  # Newest-first, max 50
      head_hash: str
      is_active: bool = False  # Currently checked out
  
  class GitVersionGraph(BaseModel):
      branches: list[GitBranchLine]
      merge_points: list[dict]  # [{"from": branch, "to": branch, "commit": hash}]
  ```
- [ ] Add `WriterGitManager.version_graph(cwd, max_commits=50) -> GitVersionGraph`:
  1. `git branch -a` → get branch list
  2. For each branch: `git log branch --oneline -n 50 --format="%h|%s|%ai|%an"` → build `GitBranchLine`
  3. `git merge-base --all` between branches → mark `is_merge_point` and build `merge_points`
  4. `git rev-parse --abbrev-ref HEAD` → mark `is_active`
- [ ] Add API endpoint: `GET /api/sessions/{session_id}/git-graph`
  - Calls `git_manager.version_graph(work_root)`
  - Returns `GitVersionGraph` as JSON
- [ ] Verify: endpoint returns structured graph data, not raw git text

**Verification:**
- [ ] `GET /api/sessions/{sid}/git-graph` returns `GitVersionGraph` with branches, commits, merge points
- [ ] Graph data is human-readable (commit messages, branch names, timestamps)

**Commit:** `add: Git version graph data model and API`

---

### Task 3.2: Emit Git Version Graph Events During Runtime

**Files:**
- `backend/app/core/writer/runtime.py` (MODIFY)
- `backend/app/core/writer/events.py` (MODIFY)

**Steps:**
- [ ] After each git operation (checkpoint, branch, merge), call `version_graph()` and emit as `WriterGitEvent(git_type="version_graph", data=graph.model_dump())`
- [ ] In `_initialize_git_context()` and `_refresh_git_context()`, emit version graph
- [ ] Verify: SSE stream includes `writer_git` events with `git_type="version_graph"`

**Verification:**
- [ ] Git version graph events emitted after checkpoints and branch operations
- [ ] Frontend (once built) can render from these events

**Commit:** `add: git version graph events in runtime`

---

## Phase 4: Multi-Provider Config System (1 day)

### Task 4.1: Add LLM Provider, Model, Routing Rule DB Models

**Files:**
- `backend/app/models/llm_config.py` (CREATE)
- `backend/app/models/__init__.py` (MODIFY)

**Steps:**
- [ ] Create `backend/app/models/llm_config.py`:
  ```python
  class LLMProvider(Base):
      __tablename__ = "llm_providers"
      id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
      name: Mapped[str] = mapped_column(String(100), nullable=False)
      api_type: Mapped[str] = mapped_column(String(50), default="openai")
      base_url: Mapped[str] = mapped_column(String(1024), nullable=False)
      api_key: Mapped[str] = mapped_column(String(1024), nullable=False)
      is_default: Mapped[bool] = mapped_column(default=False)
      created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
      updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
  
  class LLMModel(Base):
      __tablename__ = "llm_models"
      id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
      provider_id: Mapped[str] = mapped_column(String(36), ForeignKey("llm_providers.id"), nullable=False)
      model_id: Mapped[str] = mapped_column(String(255), nullable=False)
      display_name: Mapped[str] = mapped_column(String(255), default="")
      context_window: Mapped[int] = mapped_column(default=128000)
      max_output_tokens: Mapped[int] = mapped_column(default=16384)
      thinking_supported: Mapped[bool] = mapped_column(default=False)
      thinking_budget: Mapped[int] = mapped_column(default=10000)
      temperature: Mapped[float] = mapped_column(default=0.7)
      is_default: Mapped[bool] = mapped_column(default=False)
  
  class LLMRoutingRule(Base):
      __tablename__ = "llm_routing_rules"
      id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
      provider_id: Mapped[str] = mapped_column(String(36), ForeignKey("llm_providers.id"), nullable=False)
      model_id: Mapped[str] = mapped_column(String(36), ForeignKey("llm_models.id"), nullable=False)
      task_type: Mapped[str] = mapped_column(String(50), nullable=False)
      # task_type: "bugfix" | "feature" | "refactor" | "doc" | "test" | "prose" | "default"
      priority: Mapped[int] = mapped_column(default=0)
  ```
- [ ] Update `__init__.py` to export new models
- [ ] Verify: imports succeed

**Verification:**
- [ ] All 3 models importable
- [ ] FK relationships defined correctly (Model → Provider, RoutingRule → Model + Provider)

**Commit:** `add: LLM Provider, Model, Routing Rule DB models`

---

### Task 4.2: Add Config API Endpoints

**Files:**
- `backend/app/routers/config.py` (CREATE)
- `backend/app/main.py` (MODIFY)

**Steps:**
- [ ] Create `backend/app/routers/config.py`:
  - `GET /api/config/providers` — list providers
  - `POST /api/config/providers` — create provider
  - `PATCH /api/config/providers/{id}` — update provider
  - `DELETE /api/config/providers/{id}` — delete provider
  - `GET /api/config/models` — list models (filterable by provider)
  - `POST /api/config/models` — create model
  - `PATCH /api/config/models/{id}` — update model
  - `DELETE /api/config/models/{id}` — delete model
  - `GET /api/config/routing-rules` — list routing rules
  - `POST /api/config/routing-rules` — create routing rule
  - `DELETE /api/config/routing-rules/{id}` — delete routing rule
  - `GET /api/config/resolved?task_type=feature` — resolve which provider/model to use for a given task type
- [ ] Register router in `main.py`
- [ ] Verify: full CRUD works

**Verification:**
- [ ] Provider CRUD works
- [ ] Model CRUD works with FK to Provider
- [ ] `GET /api/config/resolved?task_type=feature` returns correct provider+model based on routing rules
- [ ] Default fallback works when no routing rule matches

**Commit:** `add: Config API endpoints for providers, models, routing rules`

---

### Task 4.3: Integrate Multi-Provider Config into Runtime

**Files:**
- `backend/app/services/writer_service.py` (MODIFY)
- `backend/app/core/writer/runtime.py` (MODIFY — minor)
- `backend/app/config.py` (MODIFY — minor)

**Steps:**
- [ ] In `writer_service.py`, before creating `WriterRuntime`:
  1. Determine task type from user message (reuse `infer_writer_category` from `git.py`)
  2. Query `GET /api/config/resolved?task_type={category}` to get provider+model
  3. If found, create `LLMClient` with that provider's base_url, api_key, and model
  4. If not found, fall back to `settings.llm_*` defaults
- [ ] Add `project_id` to `ChatRequest` schema so the runtime knows which project context to load
- [ ] In `runtime.py`, add `model_id` and `provider_name` to `WriterRuntimeDeps` for tracking/logging
- [ ] In `config.py`, keep existing `settings.llm_*` as defaults but mark them as "fallback when no DB config exists"
- [ ] Verify: runtime works with both DB-configured providers and .env fallback

**Verification:**
- [ ] Creating a provider+model in DB and sending a chat message uses that provider
- [ ] Without DB config, .env settings still work
- [ ] Runtime logs which provider/model is being used

**Commit:** `add: multi-provider config integration into runtime`

---

### Task 4.4: Writer Mode vs Model Reasoning Separation

**Files:**
- `backend/app/routers/session.py` (MODIFY — add reasoning toggle)
- `backend/app/core/writer/schemas.py` (MODIFY — document separation)

**Steps:**
- [ ] Add `thinking_enabled` and `thinking_budget` to `ChatRequest`:
  ```python
  class ChatRequest(BaseModel):
      message: str
      work_root: str = ""
      mode: str = "EXECUTE"
      thinking_enabled: bool | None = None  # Override model default
      thinking_budget: int | None = None    # Override model default
  ```
- [ ] In `writer_service.py`, pass `thinking_enabled`/`thinking_budget` from ChatRequest to LLMClient creation (override model defaults when specified)
- [ ] In `schemas.py`, add docstring to `WriterInteractionMode` explaining mode ≠ reasoning:
  - Mode: prompt-level instruction (affects tool availability, response tone)
  - Reasoning: API parameter (thinking_enabled, thinking_budget) — depends on model capability
  - They are fully orthogonal; greying out thinking toggle in UI when model doesn't support it is a frontend concern
- [ ] Verify: sending `thinking_enabled=false` in ChatRequest disables thinking even if model supports it

**Verification:**
- [ ] Mode and reasoning can be set independently
- [ ] `thinking_enabled=false` in request disables thinking

**Commit:** `add: reasoning toggle to ChatRequest, document mode vs reasoning separation`

---

## Phase 5: Vue3 Frontend Workbench (5 days)

### Task 5.1: Vue3 Project Scaffolding

**Files:**
- `frontend/` (REBUILD)

**Steps:**
- [ ] Initialize Vue3 project in `frontend/`:
  - `npm create vite@latest frontend -- --template vue`
  - Add dependencies: `pinia`, `vue-router`, `@vueuse/core`
  - Configure Vite dev server proxy to `http://localhost:6173`
- [ ] Create directory structure:
  ```
  frontend/src/
  ├── App.vue
  ├── main.js
  ├── router/
  │   └── index.js          # /project/:id/session/:id, /settings
  ├── stores/
  │   ├── project.ts         # Project list, CRUD
  │   ├── session.ts         # Session list, active session, messages
  │   ├── step.ts            # Step list, step events
  │   ├── git.ts             # Git graph data
  │   ├── config.ts          # Provider/Model/Routing config
  │   └── sse.ts             # SSE connection management
  ├── views/
  │   ├── Workbench.vue      # Main 3-panel layout
  │   └── Settings.vue       # Config page
  ├── components/
  │   ├── sidebar/
  │   │   ├── ProjectList.vue
  │   │   ├── ProjectCard.vue
  │   │   ├── SessionList.vue
  │   │   └── SessionCard.vue
  │   ├── main/
  │   │   ├── MessageList.vue
  │   │   ├── UserMessage.vue
  │   │   ├── StepCard.vue
  │   │   ├── ToolSummary.vue
  │   │   ├── DecisionCard.vue
  │   │   ├── InputBar.vue
  │   │   └── ModeModelSelect.vue
  │   ├── right/
  │   │   ├── ProgressPanel.vue
  │   │   ├── GitGraph.vue
  │   │   └── RuntimeStats.vue
  │   └── settings/
  │       ├── ProviderSection.vue
  │       ├── ModelSection.vue
  │       ├── RoutingSection.vue
  │       ├── PermissionSection.vue
  │       └── UIConfigSection.vue
  ├── composables/
  │   ├── useSSE.js          # SSE subscription composable
  │   └── useApi.js           # API client composable
  └── styles/
      ├── variables.css       # Design tokens (colors, spacing, typography)
      ├── base.css            # Reset + base styles
      └── components.css      # Component-specific styles
  ```
- [ ] Verify: `npm run dev` starts, blank Vue app loads

**Verification:**
- [ ] Vue3 dev server starts without errors
- [ ] Pinia and Vue Router installed and configured
- [ ] Directory structure matches above

**Commit:** `add: Vue3 project scaffolding with Pinia and Vue Router`

---

### Task 5.2: SSE → Pinia Pipeline

**Files:**
- `frontend/src/composables/useSSE.js` (CREATE)
- `frontend/src/stores/sse.ts` (CREATE)
- `frontend/src/stores/session.ts` (CREATE)
- `frontend/src/stores/step.ts` (CREATE)
- `frontend/src/stores/git.ts` (CREATE)

**Steps:**
- [ ] Create `useSSE.js` composable:
  - Connects to `GET /api/sessions/events?session_id={id}`
  - Parses SSE frames (reuses logic from current `app.js` `parseSseFrame`)
  - Dispatches to Pinia stores based on canonical event type
  - Handles reconnection, heartbeat, and abort
- [ ] Create `sse.ts` store: connection state, event log
- [ ] Create `session.ts` store:
  - State: sessions list, active session, messages
  - Actions: loadSessions, createSession, selectSession, sendMessage
  - SSE handler: `writer_lifecycle` → update session status; `writer_progress` → update phase/mode; `writer_response` → append message
- [ ] Create `step.ts` store:
  - State: steps list (keyed by session_id)
  - Actions: loadSteps
  - SSE handler: `writer_step` → upsert step, update parent nesting
- [ ] Create `git.ts` store:
  - State: version graph per session
  - Actions: loadGitGraph
  - SSE handler: `writer_git` → update graph data
- [ ] Verify: SSE events from backend update Pinia stores in real-time

**Verification:**
- [ ] SSE connection established on session select
- [ ] `writer_response` events update session.messages in Pinia
- [ ] `writer_step` events appear in step store
- [ ] Connection handles reconnection and abort

**Commit:** `add: SSE to Pinia pipeline with session, step, git stores`

---

### Task 5.3: Workbench Layout — Left Sidebar

**Files:**
- `frontend/src/views/Workbench.vue` (CREATE)
- `frontend/src/components/sidebar/ProjectList.vue` (CREATE)
- `frontend/src/components/sidebar/ProjectCard.vue` (CREATE)
- `frontend/src/components/sidebar/SessionList.vue` (CREATE)
- `frontend/src/components/sidebar/SessionCard.vue` (CREATE)

**Steps:**
- [ ] `Workbench.vue` — 3-column CSS Grid layout: `280px 1fr 300px`
- [ ] `ProjectList.vue` — lists projects from projectStore, "New Project" button
- [ ] `ProjectCard.vue` — project name, work_root path, session count, expand/collapse
- [ ] `SessionList.vue` — sessions under selected project, "New Session" button
- [ ] `SessionCard.vue` — session title, phase/mode badge, status indicator
- [ ] Slide-in animation on sidebar (CSS transition on width/opacity)
- [ ] Style: black/white/gray, Lucide SVG icons, no emoji, 6px border-radius
- [ ] Verify: project/session navigation works, sidebar slides in/out

**Verification:**
- [ ] Project list loads from API
- [ ] Clicking project expands to show sessions
- [ ] Clicking session selects it and triggers message/step load
- [ ] "New Project" and "New Session" buttons work

**Commit:** `add: Workbench layout with left sidebar project/session cards`

---

### Task 5.4: Workbench Layout — Main Area

**Files:**
- `frontend/src/components/main/MessageList.vue` (CREATE)
- `frontend/src/components/main/UserMessage.vue` (CREATE)
- `frontend/src/components/main/StepCard.vue` (CREATE)
- `frontend/src/components/main/ToolSummary.vue` (CREATE)
- `frontend/src/components/main/DecisionCard.vue` (CREATE)
- `frontend/src/components/main/InputBar.vue` (CREATE)
- `frontend/src/components/main/ModeModelSelect.vue` (CREATE)

**Steps:**
- [ ] `MessageList.vue` — scrollable message area, auto-scroll to bottom on new content
- [ ] `UserMessage.vue` — user message bubble (right-aligned, gray bg)
- [ ] `StepCard.vue` — renders WriterStep data:
  - Header: step type icon + tool name + status badge + duration
  - Body: content (collapsible), tool args (collapsible), tool result summary
  - Expand/collapse with smooth height transition
  - Nested steps (parent_step_id): indented under parent
  - Failed steps: red border, error message, retry button
  - Retry chain: show linked retries under original step
- [ ] `ToolSummary.vue` — compact inline card for tool results (file path, search hit count, command exit code)
- [ ] `DecisionCard.vue` — for `writer_decision` events: plan preview, option buttons, approval/rejection
- [ ] `InputBar.vue` — textarea + send button:
  - Ripple effect on send button click
  - Send animation (button → spinner → checkmark)
  - Ctrl+Enter to send
  - File attachment button (future: image/file uploads)
- [ ] `ModeModelSelect.vue` — dropdowns for interaction mode (EXECUTE/TEACH/etc.) and model selection, with reasoning toggle (thinking on/off)
- [ ] Verify: messages render, step cards fold/expand, input sends messages

**Verification:**
- [ ] User messages and Writer steps render in chronological order
- [ ] Step cards fold/expand with animation
- [ ] Decision cards show options and handle user selection
- [ ] Input bar sends message and starts SSE stream
- [ ] Mode and model selectors update ChatRequest params

**Commit:** `add: main area with message list, step cards, input bar`

---

### Task 5.5: Workbench Layout — Right Status Panel

**Files:**
- `frontend/src/components/right/ProgressPanel.vue` (CREATE)
- `frontend/src/components/right/GitGraph.vue` (CREATE)
- `frontend/src/components/right/RuntimeStats.vue` (CREATE)

**Steps:**
- [ ] `ProgressPanel.vue`:
  - Plan progress bar (completed/total steps, percentage)
  - Current step description
  - Phase indicator (idle → exploring → planning → executing → verifying → done)
  - Verification status (attempt number, pass/fail)
- [ ] `GitGraph.vue`:
  - Renders `GitVersionGraph` as horizontal branch lanes
  - Each lane: branch name header + commit dots (short hash + message on hover)
  - Merge points shown as vertical lines connecting branches
  - Active branch highlighted
  - Commit click → shows full message, timestamp, files changed
  - Uses CSS-only rendering (no canvas/SVG needed for ≤50 commits)
- [ ] `RuntimeStats.vue`:
  - Runtime: elapsed time (updated every second while running)
  - LLM calls: turn_count from session
  - Token usage: from latest response metadata
  - Files read/written: counters from session runtime_state
- [ ] Right panel safe area: 16px padding, panel slides in from right
- [ ] Verify: progress updates in real-time, git graph renders branch lanes

**Verification:**
- [ ] Progress bar updates on `writer_progress` events
- [ ] Git graph renders branch lanes with commits
- [ ] Runtime stats update every second while running
- [ ] Panel slides in/out smoothly

**Commit:** `add: right panel with progress, git graph, runtime stats`

---

### Task 5.6: Settings Page

**Files:**
- `frontend/src/views/Settings.vue` (CREATE)
- `frontend/src/components/settings/ProviderSection.vue` (CREATE)
- `frontend/src/components/settings/ModelSection.vue` (CREATE)
- `frontend/src/components/settings/RoutingSection.vue` (CREATE)
- `frontend/src/components/settings/PermissionSection.vue` (CREATE)
- `frontend/src/components/settings/UIConfigSection.vue` (CREATE)
- `frontend/src/stores/config.ts` (MODIFY)

**Steps:**
- [ ] `Settings.vue` — tabbed layout with sections:
  - API Providers tab
  - Models tab
  - Routing Rules tab
  - Permissions tab
  - UI Config tab
- [ ] `ProviderSection.vue`:
  - Table: name, api_type, base_url, is_default
  - Add/Edit/Delete provider forms
  - API key field (masked, show/hide toggle)
- [ ] `ModelSection.vue`:
  - Table: display_name, model_id, provider, context_window, thinking_supported, is_default
  - Add/Edit/Delete model forms
  - Provider dropdown filtered from ProviderSection
- [ ] `RoutingSection.vue`:
  - Table: task_type, provider, model, priority
  - Add/Delete routing rule
  - "Resolve" button: shows which provider/model would be used for each task type
- [ ] `PermissionSection.vue`:
  - Permission tier display (auto_allow / ask_user / hard_block)
  - Path boundary display (work_root)
  - Future: per-path permission overrides
- [ ] `UIConfigSection.vue`:
  - Default mode selection
  - Default model selection
  - Theme toggle (light only for now — black/white/gray)
  - Sidebar auto-collapse
- [ ] `config.ts` store: loadProviders, loadModels, loadRoutingRules, CRUD actions
- [ ] Verify: all CRUD operations work and persist to DB

**Verification:**
- [ ] Provider CRUD: add, edit, delete work
- [ ] Model CRUD: add, edit, delete work with provider dropdown
- [ ] Routing rules: add, delete, resolve work
- [ ] Settings persist across page refreshes

**Commit:** `add: Settings page with provider, model, routing, permission, UI config`

---

### Task 5.7: Animations and Polish

**Files:**
- `frontend/src/styles/variables.css` (MODIFY)
- `frontend/src/styles/components.css` (MODIFY)
- `frontend/src/components/main/InputBar.vue` (MODIFY)
- `frontend/src/components/sidebar/*.vue` (MODIFY)
- `frontend/src/components/right/*.vue` (MODIFY)

**Steps:**
- [ ] Left sidebar slide-in/out: `transition: width 0.3s ease, opacity 0.2s ease`
- [ ] Right panel slide-in/out: `transition: transform 0.3s ease`
- [ ] Input bar ripple effect: CSS `::after` pseudo-element with `animation: ripple 0.4s ease-out`
- [ ] Send button animation: icon morph (send → spinner → check) via CSS transition
- [ ] Step card expand/collapse: `transition: max-height 0.3s ease`
- [ ] Custom scrollbar: thin, gray, rounded corners (WebKit + Firefox)
- [ ] Right panel safe area: 16px inner padding, 8px outer margin
- [ ] Verify: all animations smooth at 60fps, no layout shift

**Verification:**
- [ ] Sidebar slides smoothly
- [ ] Input ripple visible
- [ ] Step cards expand/collapse smoothly
- [ ] Scrollbar styled consistently
- [ ] No layout shift during animations

**Commit:** `add: animations and visual polish`

---

## Phase 6: Integration, AGENTS.md Write-Back, and Error Recovery Polish (1 day)

### Task 6.1: AGENTS.md Write-Back Support

**Files:**
- `backend/app/core/writer/schemas.py` (MODIFY — add "write_agents_md" action type)
- `backend/app/core/writer/runtime.py` (MODIFY — add write_agents_md execution)
- `backend/app/core/writer/permission.py` (MODIFY — add "write_agents_md": "ask_user")
- `backend/app/routers/project.py` (VERIFY — PUT /agents-md already exists from Task 1.4)

**Steps:**
- [ ] Add `"write_agents_md"` to `WriterActionType` Literal in `schemas.py`
- [ ] Add `"write_agents_md": "ask_user"` to `TOOL_PERMISSIONS` in `permission.py`
- [ ] Add execution path in `runtime.py._execute_action()`:
  ```python
  elif atype == "write_agents_md":
      content = str(params.get("content", ""))
      # Write to work_root/AGENTS.md
      agents_path = Path(self.deps.work_root) / "AGENTS.md"
      agents_path.write_text(content, encoding="utf-8")
      # Also update project in DB
      output = f"AGENTS.md updated ({len(content)} chars)"
  ```
- [ ] Add `write_agents_md` tool definition in `prompt_assembler.py` tools list
- [ ] Verify: Writer can propose AGENTS.md changes, user confirms, file is written

**Verification:**
- [ ] `write_agents_md` action appears in tool definitions
- [ ] Permission tier is `ask_user`
- [ ] Execution writes to `{work_root}/AGENTS.md`
- [ ] `GET /api/projects/{id}/agents-md` returns updated content

**Commit:** `add: AGENTS.md write-back support in Writer tools`

---

### Task 6.2: State Tracking and Error Recovery for Files/Tests/Git/Memory

**Files:**
- `backend/app/core/writer/runtime.py` (MODIFY)
- `backend/app/core/writer/schemas.py` (MODIFY)

**Steps:**
- [ ] Add per-action state tracking to `WriterStep.metadata`:
  - File ops: `{"files_before": [...], "files_after": [...], "diff_hash": "..."}`
  - Test runs: `{"test_count": N, "pass_count": M, "fail_list": [...]}`
  - Git ops: `{"branch": "...", "head": "...", "commit": "..."}`
  - Memory: `{"con_entries_written": N, "recall_hit": bool}`
- [ ] Add error recovery for each domain:
  - **File ops**: On write_file failure, step records `failure_reason`. Runtime can retry with `edit_file` or `write_file` (overwrite).
  - **Test runs**: On `run_tests` failure, step records failed test names. Runtime already has completion repair mode.
  - **Git ops**: On checkpoint failure, step records git error. Runtime retries once, then continues without checkpoint (soft failure).
  - **Memory**: On MEM write-back failure, log warning and continue. Memory is best-effort.
- [ ] Verify: each failure domain has clear recovery path

**Verification:**
- [ ] Step metadata includes domain-specific tracking data
- [ ] Each failure type has documented recovery behavior
- [ ] Runtime doesn't crash on any single domain failure

**Commit:** `add: per-domain state tracking and error recovery`

---

### Task 6.3: Fix load_skill Permission Gap

**Files:**
- `backend/app/core/writer/permission.py` (MODIFY)

**Steps:**
- [ ] Add `"load_skill": "auto_allow"` to `TOOL_PERMISSIONS` dict
- [ ] Verify: `load_skill` is auto-allowed, not falling through to `hard_block` default

**Verification:**
- [ ] `TOOL_PERMISSIONS.get("load_skill")` returns `"auto_allow"`
- [ ] Runtime doesn't block load_skill actions

**Commit:** `fix: add load_skill to TOOL_PERMISSIONS as auto_allow`

---

## Execution Order Summary

| Phase | Tasks | Days | Depends On |
|-------|-------|------|------------|
| P1 | 1.1 → 1.2 → 1.3 → 1.4 → 1.5 | 2 | None |
| P2 | 2.1 → 2.2 → 2.3 | 1 | P1 |
| P3 | 3.1 → 3.2 | 1 | None (parallel with P2) |
| P4 | 4.1 → 4.2 → 4.3 → 4.4 | 1 | None (parallel with P2/P3) |
| P5 | 5.1 → 5.2 → 5.3 → 5.4 → 5.5 → 5.6 → 5.7 | 5 | P1 + P2 (P3/P4 can run in parallel) |
| P6 | 6.1 → 6.2 → 6.3 | 1 | P1 + P2 |

**Total: ~11 days**

P1 is the critical path. P2 depends on P1. P3 and P4 are independent and can run in parallel. P5 (frontend) can start after P1+P2 are done, and P3/P4 APIs are consumed as they become available.
