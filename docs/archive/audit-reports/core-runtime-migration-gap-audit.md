# Core Runtime Migration Gap Audit

Date: 2026-06-13

## Purpose

This document records the gaps found after moving Writer and Artist onto the shared CoreLoopKernel path. The goal is not to reintroduce the old runtimes, but to migrate the missing control, state, verification, and tool-contract behavior into the current single-track architecture cleanly.

## Ground Rules

- CoreLoopKernel remains the only loop skeleton.
- Product-specific behavior belongs in each member Kit or member service, not in core product branches.
- Fixes must be incremental and testable.
- Do not store API keys or provider credentials in this repository.
- Prefer preserving existing user-visible API and CLI behavior.
- Each repair should include targeted tests and at least one real smoke run when practical.

## P0 Shared Runtime Gaps

### 1. Runtime State Store Is Not Wired Into Kernel

Current issue:

- Writer service creates `WriterStateStore`, but `members/writer/backend/app/core/writer/core_kernel_adapter.py::run_core_kernel` creates `_InMemoryStateStore`.
- Artist service creates `ArtistStateStore`, but `members/artist/backend/app/core/artist/core_kernel_adapter.py::run_core_kernel` creates `InMemoryRuntimeStateStore`.
- Runtime state, phase, loop position, verification attempt, artifacts, memory, and cross-turn data can disappear after the run.

Expected fix:

- Allow both member `run_core_kernel` functions to accept an injected state store.
- Pass the service-level state store into CoreLoopKernel.
- Keep test-only in-memory stores available only as defaults for unit tests.

Acceptance:

- Writer and Artist service paths persist kernel state through their real state stores.
- A second turn can read state written by the first turn.
- Existing unit tests still pass; add focused tests proving injected store is used.

### 2. Cancel Is Not Wired To The Running Kernel

Current issue:

- CoreLoopKernel exposes `cancel()`.
- Writer and Artist routers call `TaskManager.cancel_task(session_id)`.
- No active kernel registry maps session_id to the running kernel, so cancel only sets an unused event.

Expected fix:

- Introduce an active-run registry per service or TaskManager integration that can call `kernel.cancel()`.
- Register the kernel before run starts and unregister it in finally.
- Preserve SSE/CLI cancel response shape.

Acceptance:

- Calling cancel during a long run stops the kernel promptly.
- Session status becomes failed/cancelled or a clear cancelled terminal state.
- No model/tool calls continue after cancel.

### 3. Step And Runtime Event Persistence Is Incomplete

Current issue:

- Writer still has `WriterStep` and `WriterRuntimeEvent` models and routers.
- Core path mostly keeps events in memory and publishes summarized SSE events.
- DB step/runtime-event views do not reflect real progress.

Expected fix:

- Bridge Core events and tool steps into Writer `WriterStep` rows and relevant runtime event rows.
- Keep event payloads summarized; do not persist full prompts or full file contents.
- For Artist, ensure equivalent persisted progress is available through existing session/message metadata or introduce a member-appropriate store.

Acceptance:

- Writer `/api/steps` and `/api/runtime-events` show meaningful records for a Core run.
- SSE and DB records agree on major lifecycle/tool/verification events.

## P0 Writer Gaps

### 4. CompletionVerifier Is Not The Main Verification Path

Current issue:

- `CompletionVerifier` still exists and has extensive tests.
- WriterKit currently performs lightweight metadata checks only.
- Real checks such as compile/import/browser/runtime/dependency validation are not run before completion.

Expected fix:

- Integrate `CompletionVerifier.verify(work_root, task=goal)` into WriterKit verification when the task produced files or the model wants to finish.
- Preserve lightweight checks as cheap pre-checks, but final completion must use the real verifier.
- Feed verifier failures back as repair prompts.

Acceptance:

- A local app with broken JS/Python/runtime dependency fails completion.
- A runnable simple app passes.
- CLI/SSE display verification results clearly.

### 5. Plan / Checklist / TDD Flow Is Not Enforced

Current issue:

- Old WriterRuntime had plan, execute, verify loop positions and TaskPlan progress.
- Current Core path injects a design-first nudge, but does not enforce a planning/checklist gate.
- `write_checklist` is declared but not executed as a real state transition.

Expected fix:

- Implement `write_checklist` execution in the Core Writer tool executor.
- Store a structured plan in RuntimeState metadata or Writer state.
- Use plan progress in verification and decision logic.
- For complex tasks, require architecture/checklist before broad writes.

Acceptance:

- Complex task starts with architecture/checklist behavior, not direct broad implementation.
- Plan progress appears in state and events.
- Verification blocks completion when planned deliverables are missing.

### 6. Writer Tool Specs And Tool Execution Are Out Of Sync

Current issue:

- Tool specs advertise `write_checklist`, `verify_design`, `load_skill`, `mcp_tool`, and others.
- The current executor only implements part of that set.
- The model can legitimately call advertised tools and receive `Unknown tool`.

Expected fix:

- Either implement advertised tools or remove them from the advertised schema until implemented.
- Prefer implementing minimal compatible handlers for core workflow tools.
- Add a test asserting advertised tool names are executable.

Acceptance:

- Every tool exposed in `LLMRequest.tools` has an executor handler.
- Unknown tool failures only occur for unadvertised tool names.

### 7. Git Context And Checkpoints Are Not Wired Into Core Runs

Current issue:

- `git_context.py` and `WriterGitManager` remain, but Core path only reads metadata hints.
- Task branch, snapshots, checkpoints, and final promotion are not part of the Core run.
- Work roots inside the LamTools monorepo can be mistaken for their parent git repo.

Expected fix:

- Initialize git context from the service/Kit when work_root is present.
- Treat work_root as isolated only when it has its own `.git`; do not accept parent repo membership as sufficient for generated task roots.
- Record checkpoints at meaningful terminal points.

Acceptance:

- A generated task directory under `e2e/real-task-runs/...` gets isolated git management or explicitly documented no-git behavior.
- Final successful Writer runs create useful checkpoint metadata.

### 8. MEM / Session Memory Is Not Actually Used By Core Writer

Current issue:

- `MEMModule` is instantiated in service but not passed into WriterKit.
- `recall_session` mostly reads runtime metadata, not the old session memory index.

Expected fix:

- Inject a memory/session-memory adapter into WriterKit.
- Record useful tool outputs, failures, and terminal summaries.
- Make `recall_session` use the real memory source.

Acceptance:

- A later turn can recall a prior run's key files, failures, and decisions.
- Memory writeback is covered by a focused test.

## P0 Artist Gaps

### 9. Artist Persistent State Store Is Bypassed

Current issue:

- `ArtistStateStore` persists JSON state.
- Core adapter uses an in-memory RuntimeStateStore.
- Visual memory, phase, lineage hints, and cross-turn context can be lost.

Expected fix:

- Pass `ArtistStateStore` or an adapter into `artist_run_core_kernel`.
- Map Core RuntimeState metadata to existing ArtistSessionState fields cleanly.

Acceptance:

- Artist state survives between turns and process-local runs where existing state store supports it.
- Phase and visual memory updates are visible through existing state mechanisms.

### 10. Contact Sheet Review Is Not In Core Path

Current issue:

- CLI still has contact sheet logic.
- Artist Core adapter explicitly says no contact sheets.
- Multi-image review quality is weaker than the old flow.

Expected fix:

- Add contact sheet generation as a verification aid or review artifact when multiple images are produced.
- Keep it Artist-specific; do not move image layout logic into core.

Acceptance:

- Multi-image generation can produce or reference a review contact sheet.
- VLM review receives either the relevant images or contact sheet context.

### 11. Delegate Agent Is Missing From Artist Core Execution

Current issue:

- Old ArtistRuntime supported `delegate_agent`.
- Current Artist Core adapter does not support it, and current tool specs omit it.

Expected fix:

- Reintroduce `delegate_agent` as a tool when a delegate callback is configured.
- If no delegate is configured, return a clear skipped/not-configured result without crashing.

Acceptance:

- Non-image research/analysis tasks can delegate or explicitly skip delegation.
- Tool schema and executor stay aligned.

### 12. Artist Visual Tool Set Was Narrowed Too Much

Current issue:

- Current executor supports only `generate_image`, `finish`, `ask_user`, `inspect_lineage`, `set_lineage_head`.
- Older docs and helpers reference review/observe/modify/variation/local-edit flows.

Expected fix:

- Decide the supported v1 Core tool set and make specs, parser, executor, and prompt agree.
- At minimum, implement or explicitly remove `review_artifacts`, `observe_artifact`, `modify_image`, and `generate_variation` from the model-visible contract.

Acceptance:

- Advertised Artist tools are executable.
- Local edit tasks preserve target/reference semantics.

### 13. Lineage Is Only Lightweight Metadata

Current issue:

- Core adapter maintains simplified `lineage_items`.
- Existing `lineage_service` rebuilds DAG from message metadata and session metadata.
- HEAD/root/branch consistency can drift.

Expected fix:

- Define one source of truth for Artist lineage during Core runs.
- Ensure generated artifacts carry enough metadata for `lineage_service` to rebuild the correct DAG.
- Sync lineage head consistently after generation and after `set_lineage_head`.

Acceptance:

- Follow-up refine uses the expected current HEAD.
- Message metadata can rebuild parent/root/branch relationships.

## P1 Cleanup And Consistency

### 14. HookSet Documentation Is Outdated

Current issue:

- Some docs say HookSet carries member differences.
- Current code marks HookSet deprecated and moves business logic into Kit.

Expected fix:

- Update docs to the actual boundary.
- Remove stale guidance that tells future fixes to put logic in HookSet if HookSet is no longer active.

Acceptance:

- Architecture docs match code.

### 15. Real Task Regression Tests Are Missing

Expected fix:

- Add small non-network regression tests around the runtime gaps.
- Add a real-task smoke script for Writer using a local app task.
- Add an Artist smoke path that can run with mocked generation where provider access is unavailable.

Acceptance:

- Tests cover state injection, cancel wiring, advertised tool executability, and verification behavior.
- Real task smoke can be run before commits.

## Suggested Repair Order

1. Shared state-store injection for Writer and Artist.
2. Active kernel registry and cancel wiring.
3. Writer step/runtime-event persistence.
4. Writer CompletionVerifier integration.
5. Writer tool spec/executor alignment.
6. Writer plan/checklist gate.
7. Writer git context/checkpoints.
8. Writer memory injection.
9. Artist persistent state mapping.
10. Artist tool spec/executor alignment, including delegate_agent.
11. Artist contact sheet and lineage consistency.
12. Documentation and smoke tests.

## Verification Commands

Use commands from the repository root:

```powershell
.\scripts\test.ps1 all
.\writer.cmd run --work-root E:\LamTools\e2e\real-task-runs\writer-video-editor --raw --no-interactive-decisions "开发一个本地视频剪辑软件"
```

For focused backend checks, prefer member-specific pytest commands already used by the repo scripts.
