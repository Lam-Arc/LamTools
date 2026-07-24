# Agent Checkpoint State Persistence & Recovery Implementation Plan

> **For agentic workers:** Use executing-plans or subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make agent checkpoint/task state survive server restarts and user disconnects, so users can resume where they left off when they return.

**Architecture:** Three-layer persistence: (1) LangGraph `InMemorySaver` → `AsyncSqliteSaver` for graph checkpoint data (thread_id, state snapshots), (2) New `agent_checkpoints` DB table for checkpoint metadata (session_id, thread_id, step info, status), (3) Frontend localStorage for checkpoint/stream UI state. On startup and session load, backend checks for pending checkpoints and frontend restores UI from localStorage + backend API.

**Tech Stack:** langgraph-checkpoint-sqlite (AsyncSqliteSaver), SQLAlchemy async, aiosqlite, localStorage

---

## Task 1: Add `langgraph-checkpoint-sqlite` to requirements.txt

**Files:** `backend/requirements.txt`

**Steps:**
- [ ] Add `langgraph-checkpoint-sqlite>=3.1.0` line after the `langgraph` line

**Verification:**
- [ ] `py -3.14 -m pip install -r requirements.txt` succeeds
- [ ] `py -3.14 -c "from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver; print('OK')"` prints OK

**Commit:** `chore: add langgraph-checkpoint-sqlite dependency`

---

## Task 2: Replace InMemorySaver with AsyncSqliteSaver in graph.py

**Files:** `backend/app/core/agent/graph.py`

**Steps:**
- [ ] Remove `from langgraph.checkpoint.memory import InMemorySaver` import
- [ ] Remove `_memory_saver = InMemorySaver()` singleton
- [ ] Add `from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver` import
- [ ] Create a module-level `_checkpoint_db_path` derived from `settings.DATA_DIR / "langgraph_checkpoints.db"`
- [ ] Create `_memory_saver` as a lazy-initialized `AsyncSqliteSaver` via `AsyncSqliteSaver.from_conn_string(str(_checkpoint_db_path))`, stored in a module variable `_checkpoint_saver` that is initialized on first use
- [ ] Add an `init_checkpoint_saver()` async function that creates the saver and calls `await _checkpoint_saver.setup()` to initialize the DB tables
- [ ] Modify `build_agent_graph()` and `build_agent_mode_graph()` to use `_checkpoint_saver` instead of `_memory_saver`
- [ ] Call `init_checkpoint_saver()` in `main.py` lifespan before `init_db()`

**Verification:**
- [ ] Server starts without errors
- [ ] `langgraph_checkpoints.db` file created in DATA_DIR after first run
- [ ] Agent mode generation still works (sidebar assistant + agent mode)

**Commit:** `feat: replace InMemorySaver with AsyncSqliteSaver for persistent graph checkpoints`

---

## Task 3: Add `agent_checkpoints` DB model and migration

**Files:** `backend/app/models/agent_checkpoint.py`, `backend/app/models/__init__.py`, `backend/app/database.py`

**Steps:**
- [ ] Create `backend/app/models/agent_checkpoint.py` with:
  ```python
  class AgentCheckpoint(Base):
      __tablename__ = "agent_checkpoints"
      id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
      session_id: Mapped[str] = mapped_column(String(36), ForeignKey("sessions.id"), nullable=False, unique=True)
      thread_id: Mapped[str] = mapped_column(String(100), nullable=False)
      step_index: Mapped[int] = mapped_column(default=-1)
      step_description: Mapped[str] = mapped_column(Text, default="")
      checkpoint_message: Mapped[str] = mapped_column(Text, default="")
      image_urls: Mapped[str] = mapped_column(Text, default="")  # JSON array
      status: Mapped[str] = mapped_column(String(20), default="pending")  # pending/resolved/cancelled
      retry_level: Mapped[str] = mapped_column(String(20), default="approve")
      created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
      updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
  ```
- [ ] Update `backend/app/models/__init__.py` to import `AgentCheckpoint`
- [ ] Add migration in `database.py` `init_db()`: create table if not exists, add to `Base.metadata.create_all`

**Verification:**
- [ ] Server starts, `agent_checkpoints` table created in DB
- [ ] No migration errors in logs

**Commit:** `feat: add agent_checkpoints DB model for checkpoint state persistence`

---

## Task 4: Persist checkpoint state to DB in TaskManager

**Files:** `backend/app/services/task_manager.py`

**Steps:**
- [ ] Add `async def save_checkpoint_to_db(self, db: AsyncSession, session_id: str)` method that reads `_checkpoint_states[session_id]` and writes/updates the `AgentCheckpoint` row
- [ ] Add `async def load_checkpoint_from_db(self, db: AsyncSession, session_id: str) -> dict | None` method that reads the `AgentCheckpoint` row and reconstructs the checkpoint state dict (without `event_obj` — that must be created fresh)
- [ ] Add `async def clear_checkpoint_in_db(self, db: AsyncSession, session_id: str)` method that deletes the `AgentCheckpoint` row
- [ ] Add `async def load_all_pending_checkpoints(self, db: AsyncSession) -> list[dict]` method that returns all checkpoints with status="pending" for startup recovery
- [ ] Modify `set_checkpoint_state()` to accept optional `db` parameter and persist to DB when provided
- [ ] Modify `resolve_checkpoint()` to also update DB status when `db` is available
- [ ] Modify `clear_checkpoint_state()` to also clear DB when `db` is available
- [ ] Add `restore_checkpoint_event_obj(self, session_id: str) -> asyncio.Event` method that creates a fresh `asyncio.Event` for a loaded checkpoint state

**Verification:**
- [ ] Unit test: save → load → verify data matches
- [ ] Unit test: save → clear → load returns None

**Commit:** `feat: persist checkpoint state to database in TaskManager`

---

## Task 5: Fix retry_step/replan bug in _run_agent_mode_graph

**Files:** `backend/app/services/generate_service.py`

**Steps:**
- [ ] In `_run_agent_mode_graph`, after `wait_checkpoint()` returns, change the logic:
  - Current: `resolved = await task_manager.wait_checkpoint(session_id)` → `if not resolved: return cancelled`
  - New: Read `retry_level` from checkpoint state. If `retry_level` is `"retry_step"` or `"replan"`, continue the loop (don't cancel). Only cancel if the checkpoint was explicitly rejected (action="cancel" or cancel_event set without retry_level)
  - The `wait_checkpoint` return value should change from `bool` to return the `retry_level` string, or we read it from the checkpoint state after wait
- [ ] Update `wait_checkpoint` to return a richer result — change return type from `bool` to `str` (returns the `retry_level`: "approve", "retry_step", "replan", or "cancelled")
- [ ] Update `_run_agent_mode_graph` to handle each retry_level:
  - "approve": continue loop (resume graph with Command(resume="approve"))
  - "retry_step": continue loop (resume graph with Command(resume="retry_step"))
  - "replan": continue loop (resume graph with Command(resume="replan"))
  - "cancelled": return cancelled result (current behavior for `not resolved`)

**Verification:**
- [ ] Agent mode with checkpoint: approve → continues correctly
- [ ] Agent mode with checkpoint: retry_step → re-executes step, not cancelled
- [ ] Agent mode with checkpoint: replan → goes back to planner, not cancelled

**Commit:** `fix: handle retry_step and replan checkpoint actions correctly instead of treating as cancellation`

---

## Task 6: Persist checkpoint state in _run_agent_mode_graph flow

**Files:** `backend/app/services/generate_service.py`

**Steps:**
- [ ] In `_run_agent_mode_graph`, after `set_checkpoint_state()`, call `task_manager.save_checkpoint_to_db(db, session_id)` to persist the checkpoint metadata (thread_id, step info, image_urls, status="pending")
- [ ] When checkpoint is resolved (after `wait_checkpoint` returns), call `task_manager.clear_checkpoint_in_db(db, session_id)` or update status to "resolved"
- [ ] On task completion/error/cancel, call `task_manager.clear_checkpoint_in_db(db, session_id)` to clean up

**Verification:**
- [ ] During checkpoint wait, `agent_checkpoints` table has a row with status="pending"
- [ ] After checkpoint resolved, row status updated or deleted
- [ ] After task completion, no stale rows remain

**Commit:** `feat: persist checkpoint metadata to DB during agent execution`

---

## Task 7: Startup recovery — restore pending checkpoints on server start

**Files:** `backend/app/main.py`, `backend/app/services/task_manager.py`

**Steps:**
- [ ] In `lifespan()` in `main.py`, after `init_db()` and `init_checkpoint_saver()`:
  - Create a DB session
  - Call `task_manager.load_all_pending_checkpoints(db)` 
  - For each pending checkpoint, create a fresh `asyncio.Event` in `_checkpoint_states`
  - Log recovered checkpoints
  - Close DB session
- [ ] This ensures that after a server restart, any session that had a pending checkpoint will have its in-memory state restored, and the `wait_checkpoint` call in `_run_agent_mode_graph` will need to be re-triggered

**Important design decision:** After server restart, the background asyncio task that was running `_run_agent_mode_graph` is gone. We cannot resume the graph execution loop automatically because:
1. The `asyncio.create_task` context is lost
2. The `db` session reference in `config` is stale
3. The graph needs to be re-invoked with `Command(resume=action)` using the persisted thread_id

So the recovery strategy is:
- On startup, load pending checkpoints from DB
- When user reconnects and calls `POST /api/sessions/{id}/agent/checkpoint` with an action, we need to **re-launch** the graph execution loop with the saved thread_id and config
- Add a new method `_resume_agent_from_checkpoint()` in `generate_service.py` that reconstructs the config from DB data and resumes the graph

**Verification:**
- [ ] Server restart with pending checkpoint → checkpoint state restored in memory
- [ ] Logs show "Recovered N pending checkpoint(s)"

**Commit:** `feat: restore pending checkpoints from DB on server startup`

---

## Task 8: Add checkpoint resume endpoint and re-launch graph on reconnect

**Files:** `backend/app/routers/session.py`, `backend/app/services/generate_service.py`, `backend/app/services/task_manager.py`

**Steps:**
- [ ] Add `GET /api/sessions/{id}/agent/checkpoint-status` endpoint that returns current checkpoint state for a session (pending/resolved/none), including step info and image_urls. This allows frontend to check on load.
- [ ] Modify `POST /api/sessions/{id}/agent/checkpoint` to handle the case where the in-memory `event_obj` doesn't exist (server was restarted):
  - If `_checkpoint_states[session_id]` has no `event_obj`, create one and set it immediately with the provided action
  - Then launch `_resume_agent_from_checkpoint()` as a background task
- [ ] Create `_resume_agent_from_checkpoint()` in `generate_service.py`:
  - Load checkpoint data from DB (thread_id, step_index, etc.)
  - Reconstruct LangGraph config with fresh db session and task_manager
  - Build the agent mode graph
  - Invoke with `Command(resume=action)` using the saved thread_id
  - Continue the execution loop same as `_run_agent_mode_graph`
- [ ] Add `resume_agent_checkpoint()` in `task_manager.py` that creates the background task context

**Verification:**
- [ ] Server restart → user opens session → checkpoint-status API returns pending checkpoint info
- [ ] User clicks approve → checkpoint resolved → graph resumes → task completes

**Commit:** `feat: add checkpoint resume endpoint and graph re-launch for server restart recovery`

---

## Task 9: Frontend — persist checkpoint/stream state to localStorage

**Files:** `frontend/src/stores/session.ts`, `frontend/src/views/Sessions.vue`

**Steps:**
- [ ] In `session.ts` store, add localStorage persistence for `checkpointStates` and `agentStreamStates`:
  - On `setCheckpoint()`, also write to `localStorage.setItem('lamimager_checkpoint_${sessionId}', JSON.stringify(info))`
  - On `clearCheckpoint()`, also `localStorage.removeItem(...)`
  - On `setAgentStream()`, also write to `localStorage.setItem('lamimager_stream_${sessionId}', JSON.stringify(state))`
  - On `clearAgentStream()`, also `localStorage.removeItem(...)`
  - Add `loadPersistedCheckpoint(sessionId)` and `loadPersistedStream(sessionId)` methods that read from localStorage
- [ ] In `Sessions.vue`, on `onMounted` and session switch:
  - Check localStorage for persisted checkpoint/stream state
  - Also call `GET /api/sessions/{id}/agent/checkpoint-status` to verify with backend
  - If backend confirms pending checkpoint, restore UI state
  - If backend says no checkpoint (e.g. task completed while user was away), clear localStorage and show normal state

**Verification:**
- [ ] Page refresh during checkpoint → checkpoint UI restored from localStorage
- [ ] Page refresh after task completed while away → localStorage cleared, normal UI shown
- [ ] Session switch → persisted state loaded correctly

**Commit:** `feat: persist checkpoint and stream state to localStorage for page refresh recovery`

---

## Task 10: Frontend — add checkpoint-status API call on session load

**Files:** `frontend/src/api/session.ts`, `frontend/src/views/Sessions.vue`

**Steps:**
- [ ] Add `checkpointStatus(id: string)` method to `sessionApi`: `api.get(`/sessions/${id}/agent/checkpoint-status`)`
- [ ] In `Sessions.vue` `selectSession()`, after loading messages:
  - Call `sessionApi.checkpointStatus(id)`
  - If response has pending checkpoint with `status: "pending"`:
    - Restore `agentCheckpointState` from API response data
    - Set `store.setCheckpoint(id, ...)` 
  - If response has no checkpoint or `status: "resolved"/"cancelled"`:
    - Clear any persisted localStorage state for this session
- [ ] In `onMounted`, after initial session selection, also check checkpoint status

**Verification:**
- [ ] Fresh page load on session with pending checkpoint → checkpoint overlay appears
- [ ] Fresh page load on session without checkpoint → normal UI

**Commit:** `feat: add checkpoint-status API and restore checkpoint UI on session load`

---

## Task 11: Clean up stale checkpoints on startup

**Files:** `backend/app/main.py`, `backend/app/services/task_manager.py`

**Steps:**
- [ ] In `lifespan()`, after loading pending checkpoints:
  - For checkpoints older than 24 hours (stale), automatically cancel them
  - Update their DB status to "cancelled"
  - Add a system message to the session about the auto-cancellation
  - Log the cleanup
- [ ] This prevents infinitely old checkpoints from accumulating

**Verification:**
- [ ] Server restart with 2-day-old checkpoint → auto-cancelled, session gets system message
- [ ] Recent checkpoint (< 24h) → preserved for recovery

**Commit:** `feat: auto-cancel stale checkpoints older than 24 hours on startup`

---

## Task 12: Update AGENTS.md with new architecture

**Files:** `AGENTS.md`

**Steps:**
- [ ] Update LangGraph Architecture section to mention `AsyncSqliteSaver` instead of `InMemorySaver`
- [ ] Add `agent_checkpoints` table to Data Models section
- [ ] Add checkpoint-status API endpoint to API Quick Reference
- [ ] Update Checkpoint Flow section to describe persistence and recovery
- [ ] Add note about localStorage persistence for frontend state

**Verification:**
- [ ] AGENTS.md accurately reflects new architecture

**Commit:** `docs: update AGENTS.md with checkpoint persistence architecture`