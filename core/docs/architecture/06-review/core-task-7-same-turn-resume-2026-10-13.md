# Core Task 7 — Lightweight same-turn Resume

Implemented in the Python Core runtime and shared desktop/remote UI on 2026-10-13. Existing Task 1 and 1A fixes remain in place. No production database was edited, no backend was restarted, and no paid model requests were made.

## Behavior

- An empty composer shows Resume when the latest logical turn is interrupted (`cancelled`) and the connected server advertises support. Typing a new message or adding attachments selects Send instead. A normal completed or failed turn does not offer Resume.
- Resume retains the original Turn ID and starts a fresh execution Run ID. It appends `turn/started` with `resumed=true`, rather than `turn/accepted` or a user-message item.
- The existing `turn.start` runtime executor, `CoreLoopKernel`, history loader, tool-history repair, model routing, prompt assembly, permissions, and steering boundaries are reused. The continuation instruction is a marked system-history message; it skips the user-prompt-submit hook.
- Committed assistant messages and tool results remain in model history. Partial streaming previews remain interrupted display items and are not imported into model history. Missing tool results use the existing interrupted-tool history repair; Resume does not execute a stored tool call.
- If Stop wins before the initial input reaches kernel history, the existing committed acceptance input supplies continuation context, including its attachment references, through the existing input preparation and attachment assembly paths. No extra user row is created.
- Stop still acknowledges promptly. Resume waits for existing Stop finalizers, and the main runtime retains ownership while its cancellation history is committed. Live execution ownership is checked before resumption.
- Steering remains bound to the original logical turn, while each resumed execution gets distinct response, interruption, and terminal event identities. Guidance IDs, commit-before-publication, consumption boundaries, and checkpoint acknowledgements remain unchanged.
- Restart never invokes Resume automatically. Existing startup reconciliation closes orphaned resumed executions as interrupted and preserves their logical Turn ID. Resume remains an explicit action after restart.

CLI: `py -3.14 -m lamtools_core.cli resume <thread_id> [--turn-id <turn_id>]` from `core/`, with the existing live-connection options. RPC: `turn.resume` / `turn/resume`.

## Changes and code references

| Area | Evidence |
| --- | --- |
| Resume acceptance, committed-record reconstruction, ownership checks, normal runtime dispatch | [live_operations.py](E:/LamTools/core/src/lamtools_core/app/live_operations.py:1439) |
| Early Stop convergence | [live_operations.py](E:/LamTools/core/src/lamtools_core/app/live_operations.py:2320) |
| Per-execution Stop/recovery identities | `_turn_execution_id`, `_append_interrupting_record`, `_persist_cancelled_terminal`, `_close_active_turns` in the same module |
| Logical-turn steering binding and cancellation persistence settlement | [default_agent.py](E:/LamTools/core/src/lamtools_core/app/default_agent.py:384), `kernel.await_background_persistence()` in its execution cleanup |
| System continuation and committed input identity | `_begin_run` in [kernel/loop.py](E:/LamTools/core/src/lamtools_core/kernel/loop.py:1702) |
| Explicit reopening of both snapshot projections, preserving terminal-state guards for ordinary late events | `_apply_turn_started` in [snapshot_store.py](E:/LamTools/core/src/lamtools_core/app/snapshot_store.py:189) and `applyAppEvent` in [UI store](E:/LamTools/core/ui/src/appServer/store.ts:1309) |
| Composer Resume selection, dispatch, and button label/play glyph | [createWorkbench.ts](E:/LamTools/core/ui/src/workbench/createWorkbench.ts:388), `useCoreLiveComposerController.ts`, `CoreSendStopButton.vue`, `LamToolsApp.vue` |
| Capability negotiation; unsupported runtimes keep Send | [live_router.py](E:/LamTools/core/src/lamtools_core/app/live_router.py:932), `appServer/client.ts` |
| CLI and public live client | [cli.py](E:/LamTools/core/src/lamtools_core/cli.py:1477), `app/live_client.py` |

Two integration problems required fixes: Stop before the coroutine starts previously left a turn `interrupting` without a terminal writer; fixed through the existing Stop finalizer. Reusing turn-scoped terminal event IDs across resumed attempts would deduplicate a later Stop or restart recovery; those identities now use the execution Run ID while retaining the Turn ID.

No new database table, checkpoint mechanism, recovery supervisor, replay engine, confirmation workflow, or exactly-once system was introduced. Existing application checkpoint infrastructure remains unchanged.

## Verification

All model streams and tool handlers were scripted; no external commands or paid providers were used in Resume tests.

- **10 targeted Python tests passed** in [test_same_turn_resume.py](E:/LamTools/core/tests/test_same_turn_resume.py): Stop during streaming and a tool batch; committed first-tool result retained while a second tool is interrupted; same Turn ID and one acceptance/user item; partial stream excluded; repeated Stop/Resume; early Stop before either original or resumed kernel startup; steering on a resumed execution and its durable receipt; normal completion and active execution refusal; database reopen after user Stop; repeated orphaned-attempt recovery without automatic execution; CLI routing; transaction rollback releases the claim without starting the model.
- **314 Python regression tests passed** across `test_core_live.py`, `test_steering_alignment.py`, `test_kernel.py`, `test_sub_agent_supervisor.py`, `test_core_sub_agent_runner.py`, and the then-current Resume tests.
- **85 Python checks passed** across recovery, CLI, sub-agent state consistency, and the then-current Resume tests. These suites overlap; the counts are not additive.
- **94 UI tests passed** across composer, runtime store, Send/Stop/Resume button, workbench, and Task 1 sub-agent state tests. Coverage includes explicit reopening without changing completed/partial item statuses and capability-gated Resume dispatch without `turn/start` or input.
- All three UI TypeScript checks passed. `git diff --check` passed.
- Python emitted only existing SQLite datetime-adapter deprecation warnings.

## Limitations and activation

- Interrupted tools may have uncertain external side effects. The model receives this fact and existing missing-result repair, but there is no guarantee against a model choosing to issue a similar new tool call. Committed calls are not replayed by Resume.
- Incomplete response reasoning/text fragments are display previews only; per-block history persistence was not added.
- Only the latest interrupted logical turn can resume. Resume preserves accepted model/instruction settings and uses current session permissions. It does not restore the exact in-flight provider stream or tool process.
- The embedded Rust/mobile runtime does not implement this new same-turn operation and does not advertise its capability. The shared UI keeps Resume hidden there. Mobile connected to the Python server can use the server capability.
- Visual Tauri acceptance and installer checks were not performed. No installer or release was built. Activate backend changes with a full application/backend restart; restart itself does not resume stopped execution.
