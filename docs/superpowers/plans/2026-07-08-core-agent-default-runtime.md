# Core Agent Default Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an independently usable Core Agent runtime and let Writer reuse Core-owned event, snapshot, approval, and operation plumbing through explicit member configuration.

**Architecture:** Add a Core default agent assembly layer that owns generic agent runtime concerns. Keep Writer as a member adapter that supplies paths, storage models, prompts, tools, and Writer-only event handlers.

**Tech Stack:** Python 3.14, pytest, SQLAlchemy async, FastAPI, existing LamTools Core runtime, existing Writer app-server protocol.

## Global Constraints

- PowerShell involving Chinese must use UTF-8.
- Core must not contain Writer/Artist product names.
- New behavior must use existing Core logic where possible.
- GUI capability must have an equivalent CLI/operation entry.
- Writer default data dir remains `members/writer/data/`; explicit `LAMWRITER_DATA_DIR` wins.
- Do not revert unrelated dirty files.
- TDD is required for production changes.

---

## Files

- Create: `core/src/lamtools_core/app/event_store.py`
- Create: `core/src/lamtools_core/app/snapshot_store.py`
- Create: `core/src/lamtools_core/app/default_agent.py`
- Test: `core/tests/test_core_agent_event_store.py`
- Test: `core/tests/test_core_agent_snapshot_store.py`
- Test: `core/tests/test_core_default_agent.py`
- Modify: `core/src/lamtools_core/app/__init__.py`
- Modify: `members/writer/backend/app/app_server/ledger.py`
- Modify: `members/writer/backend/app/app_server/snapshot.py`
- Modify: `members/writer/backend/app/app_server/event_store.py`
- Modify: `members/writer/backend/app/app_server/reducer.py`
- Test: `members/writer/backend/tests/test_writer_app_event_ledger.py`
- Test: `members/writer/backend/tests/test_writer_app_server_protocol.py`

## Task 1: Core SQLAlchemy Event Store

**Files:**
- Create: `core/src/lamtools_core/app/event_store.py`
- Test: `core/tests/test_core_agent_event_store.py`

**Interfaces:**
- Produces: `AppEventInput`, `AppEventEnvelope`, `SqlAlchemyAppEventStore`, `CORE_RUN_ITEM_METHOD`.
- Consumes: SQLAlchemy async session plus event model class with Writer-compatible columns.

- [ ] **Step 1: Write failing tests**

Create `core/tests/test_core_agent_event_store.py` with tests for:

```python
async def test_app_event_store_allocates_thread_sequence(async_session): ...
async def test_app_event_store_returns_existing_event_by_id(async_session): ...
async def test_app_event_store_wraps_run_item_event(async_session): ...
```

Use a temporary SQLAlchemy model with columns matching `WriterAppEvent`.

- [ ] **Step 2: Verify RED**

Run:

```powershell
py -3.14 -m pytest core/tests/test_core_agent_event_store.py -q
```

Expected: fails because `lamtools_core.app.event_store` does not exist.

- [ ] **Step 3: Implement minimal Core event store**

Add a generic async store that:

- converts rows to `AppEventEnvelope`
- allocates `seq=max(thread_id)+1`
- retries thread sequence collisions
- returns existing rows for duplicate `event_id`
- wraps `RunItemEvent` as `method="core/runItem"`

- [ ] **Step 4: Verify GREEN**

Run:

```powershell
py -3.14 -m pytest core/tests/test_core_agent_event_store.py -q
```

Expected: pass.

## Task 2: Core Snapshot Store

**Files:**
- Create: `core/src/lamtools_core/app/snapshot_store.py`
- Test: `core/tests/test_core_agent_snapshot_store.py`

**Interfaces:**
- Consumes: `AppEventEnvelope`, `CORE_RUN_ITEM_METHOD`, `lamtools_core.snapshot.apply_run_item_event`.
- Produces: `CoreAppSnapshotProjector`, `SqlAlchemyThreadSnapshotStore`.

- [ ] **Step 1: Write failing tests**

Create tests proving:

```python
def test_projector_keeps_member_defaults_and_core_snapshot(): ...
def test_projector_applies_core_run_item_event(): ...
async def test_sqlalchemy_snapshot_store_load_apply_rebuild(async_session): ...
```

- [ ] **Step 2: Verify RED**

Run:

```powershell
py -3.14 -m pytest core/tests/test_core_agent_snapshot_store.py -q
```

Expected: fails because store/projector does not exist.

- [ ] **Step 3: Implement snapshot projector and SQLAlchemy store**

The projector must:

- return `thread_id`, `snapshot_seq`, `seen_event_ids`, `turns`, `items`, `item_order`, `requests`, `artifacts`, `status`
- include `core=empty_thread_snapshot(thread_id)`
- accept `member_defaults` such as `{"queue": []}`
- apply `core/runItem` payloads through Core snapshot reducer
- sync top-level status from `core.status`

The SQLAlchemy store must:

- load default snapshot when no row exists
- apply one event and flush
- rebuild from listed events

- [ ] **Step 4: Verify GREEN**

Run:

```powershell
py -3.14 -m pytest core/tests/test_core_agent_snapshot_store.py -q
```

Expected: pass.

## Task 3: Core Default Agent Assembly

**Files:**
- Create: `core/src/lamtools_core/app/default_agent.py`
- Modify: `core/src/lamtools_core/app/__init__.py`
- Test: `core/tests/test_core_default_agent.py`

**Interfaces:**
- Produces: `CoreAgentSpec`, `CoreAgentPaths`, `CoreAgentAssembly`, `create_core_agent_operations`.
- Consumes: existing `AgentApp`, `OperationCatalog`, `ApprovalGate`, `ToolSpec`, `InMemorySessionStore`, `InMemorySnapshotStore`.

- [ ] **Step 1: Write failing tests**

Create tests proving:

```python
async def test_core_agent_runs_independent_turn_with_in_memory_store(): ...
async def test_core_agent_operations_expose_turn_start(): ...
def test_core_agent_spec_accepts_member_paths_without_product_names(): ...
```

- [ ] **Step 2: Verify RED**

Run:

```powershell
py -3.14 -m pytest core/tests/test_core_default_agent.py -q
```

Expected: fails because default agent assembly does not exist.

- [ ] **Step 3: Implement minimal assembly**

The default assembly should:

- create `AgentSpec(id="core-agent")` unless overridden
- accept `member_id`, `data_dir`, `work_root`, `prompt_fragments`, `tool_specs`
- register `turn.start` in an `OperationCatalog`
- run a single `AgentApp.run_turn`
- return snapshot/events in the operation result

- [ ] **Step 4: Verify GREEN**

Run:

```powershell
py -3.14 -m pytest core/tests/test_core_default_agent.py core/tests/test_agent_app_contract.py -q
```

Expected: pass.

## Task 4: Writer Reuses Core Event and Snapshot Stores

**Files:**
- Modify: `members/writer/backend/app/app_server/ledger.py`
- Modify: `members/writer/backend/app/app_server/snapshot.py`
- Modify: `members/writer/backend/app/app_server/event_store.py`
- Modify: `members/writer/backend/app/app_server/reducer.py`
- Test: `members/writer/backend/tests/test_writer_app_event_ledger.py`
- Test: `members/writer/backend/tests/test_writer_app_server_protocol.py`

**Interfaces:**
- Consumes: `SqlAlchemyAppEventStore`, `SqlAlchemyThreadSnapshotStore`, `CoreAppSnapshotProjector`.
- Produces: same Writer functions as today: `append_event`, `append_run_item_event`, `load_snapshot`, `apply_event_to_snapshot`, `rebuild_snapshot`.

- [ ] **Step 1: Write failing tests**

Extend Writer tests to assert:

```python
async def test_writer_ledger_uses_core_run_item_method_shape(db): ...
async def test_writer_snapshot_preserves_queue_and_core_snapshot(db): ...
async def test_writer_rebuild_snapshot_matches_incremental_snapshot(db): ...
```

- [ ] **Step 2: Verify RED**

Run:

```powershell
py -3.14 -m pytest members/writer/backend/tests/test_writer_app_event_ledger.py members/writer/backend/tests/test_writer_app_server_protocol.py -q
```

Expected: fail on new assertions or missing Core adapter calls.

- [ ] **Step 3: Replace duplicate implementation with Core adapters**

Keep Writer public functions stable, but internally:

- instantiate Core event store with `WriterAppEvent`
- instantiate Core snapshot store with `WriterThreadSnapshot`
- pass `protocol_version="writer.app_server.v1"`
- pass `member_defaults={"queue": []}`
- delegate Core run item handling to Core projector
- leave Writer queue/rollback handlers in Writer reducer for now

- [ ] **Step 4: Verify GREEN**

Run:

```powershell
py -3.14 -m pytest members/writer/backend/tests/test_writer_app_event_ledger.py members/writer/backend/tests/test_writer_app_server_protocol.py -q
```

Expected: pass.

## Task 5: End-to-End Contract Verification

**Files:**
- Modify only if tests expose gaps.

**Interfaces:**
- Consumes all tasks above.
- Produces verified Core Agent and Writer compatibility.

- [ ] **Step 1: Run Core focused tests**

```powershell
py -3.14 -m pytest core/tests/test_core_default_agent.py core/tests/test_core_agent_event_store.py core/tests/test_core_agent_snapshot_store.py core/tests/test_agent_app_contract.py core/tests/test_tool_approval.py core/tests/test_run_item_snapshot.py -q
```

Expected: pass.

- [ ] **Step 2: Run Writer focused tests**

```powershell
py -3.14 -m pytest members/writer/backend/tests/test_writer_app_event_ledger.py members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_writer_app_approvals.py members/writer/backend/tests/test_writer_app_runtime_bridge.py -q
```

Expected: pass.

- [ ] **Step 3: Run CLI smoke**

```powershell
.\lamtools.cmd members list --json
```

Expected: command succeeds and Writer remains listed.

- [ ] **Step 4: Diff audit**

```powershell
rg -n "Writer|Artist|LamWriter|LamArtist" core/src/lamtools_core
git diff --check -- core members/writer docs/superpowers
```

Expected: no product names in Core source; no whitespace errors.

## Self-Review

- Spec coverage: Core independent runtime, Writer path fields, storage parity, no duplicate Core ability, Writer compatibility all have tasks.
- Placeholder scan: no TBD/TODO placeholders.
- Type consistency: plan uses `AppEventInput`, `AppEventEnvelope`, `SqlAlchemyAppEventStore`, `CoreAppSnapshotProjector`, and `SqlAlchemyThreadSnapshotStore` consistently.
