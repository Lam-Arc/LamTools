# Core Task 1B — Sub-agent status synchronization

Source fix and development Tauri acceptance completed on 2026-10-13. Tasks 1, 1A, and 7 remain intact. No paid model calls, production database edits, installer build, publication, or backend restart were performed.

## Confirmed cause

The reported `host_lamtools_v1` is the same child inspected in Task 1: parent `5545f1e3cc4f41fea09bac0ac675a8fb`, child `<parent>:sub:host_lamtools_v1`.

Current read-only records show:

| Source | Observed state |
| --- | --- |
| Supervisor registry, `data/core-agent/sub_agents.sqlite3` | `interrupted`; recorded elapsed 5,110,380 ms |
| Child runtime, `data/core.db` | `cancelled`, `failure_code=sub_agent_process_interrupted` |
| Parent lifecycle status item | `payload.type=subAgentStatus`; member `interrupted`, item `cancelled` |
| Historical delegation/nested activity | Still carries the earlier `running` invocation evidence |
| Parent's latest runtime turn | `completed`; a different parent turn from the child's original delegation |

The backend interruption repair from Task 1 has run: the current registry, child runtime, and parent lifecycle event agree. The remaining defect was a UI source mismatch. `RightSidebarHost` projected the historical messages directly and passed their raw `run.status` to the card. `CoreSubAgentPane` additionally consulted the registry and published member statuses, so it could correctly display Interrupted while the card displayed Running.

Two related gaps contributed: registry polling only ran while the pane was open, and the member-status selector is intentionally scoped to the current parent turn. A child delegated by an older turn can therefore be absent from the current turn's published map. The transcript-only fallback also left the session/composer background-running indicator active.

Evidence: [redacted database/status record](E:/LamTools/core/docs/architecture/06-review/evidence/core-task-1b-2026-10-13.json). The snapshot item's `seq` is its original insertion position; the newer parent status event updated that same item rather than appending another member row.

## Implemented changes

- Card, pane, timers, grouping, deletion eligibility, and background-work indicators consume the same reconciled child lifecycle evidence.
- The shared resolver compares actual child start/completion timestamps. An interruption, normal completion/idle, error, or closure beats stale Running evidence. A newer child start can legitimately become Running after an earlier interruption. Stale terminal polls cannot close that newer child, and stale Running polls cannot reopen a completed child.
- Published member records retain their lifecycle timestamps instead of being reduced only to status strings. The workbench merges them with the thread's polled registry and derives all session activity from that merged result.
- The existing ten-second registry refresh now serves the whole active session, independently of whether the pane is open. Session changes and reconnection refresh it immediately. Thread identity and request generation reject old responses. Registry state remains scoped to its thread.
- Hidden sidebar projection remains lazy. There is no model-chunk-driven RPC loop or new full-transcript scan. No backend lifecycle, ownership, steering, persistence, checkpoint, or Resume mechanism was replaced.

References:

- Shared evidence resolution and record merge: `resolveSubAgentEvidence`, `reconcileCoreSubAgentRun`, `reconcileCoreSubAgentRecords` in [subAgentProjection.ts](E:/LamTools/core/ui/src/agents/subAgentProjection.ts:666).
- Card input: [RightSidebarHost.vue](E:/LamTools/core/ui/src/components/RightSidebarHost.vue:207).
- Pane status/timing: `effectiveRun` and `elapsedLabel` in [CoreSubAgentPane.vue](E:/LamTools/core/ui/src/components/CoreSubAgentPane.vue).
- Shared activity and registry ownership: [sessionActivity.ts](E:/LamTools/core/ui/src/appServer/sessionActivity.ts:98), [createWorkbench.ts](E:/LamTools/core/ui/src/workbench/createWorkbench.ts:307).
- Host refresh and surface wiring: `refreshSubAgentRecords`, `syncSubAgentRecordsPolling`, and `effectiveSubAgentRecords` in [LamToolsApp.vue](E:/LamTools/core/ui/src/app/LamToolsApp.vue).
- Existing backend path retained: `SubAgentSupervisor._publish_member_status` → `runtime.sub_agent_status` → `runtime_projection.py` member item → snapshot/live event; startup/watchdog reconciliation remains in `app/sub_agent_recovery.py`.

## Verification

- **173 UI tests passed** across eight affected/regression suites: status consistency, pane, sub-agent projection/display, session activity, lazy sidebar, composer, runtime store, and workbench. New tests reproduce the screenshot discrepancy with mounted card and pane, then cover interruption, completion, stale polls, a newer child Resume, hydrated/reconnected transcript input, and rejection of another thread's registry. The background indicator regression confirms the session-list status also settles.
- **91 Python tests passed** across Task 1 state consistency, Task 1A steering alignment, Task 7 same-turn Resume, supervisor, and child runner tests. Models/tools are scripted. Existing SQLite datetime-adapter deprecation warnings remain.
- All three UI TypeScript checks passed. `git diff --check` passed.
- **Actual Tauri debug interface passed for the reported child.** Used the already-running `core/desktop/src-tauri/target/debug/lamcore.exe` window and its real chatt conversation. After HMR/WebView reconnect, the card lists `host_lamtools_v1` under Interrupted; the pane simultaneously shows Interrupted. Both show **85m 10s**, there is no Running group, and the stale background-running indicator is gone. Navigation only: no Stop, Resume, message, deletion, or model execution was submitted.

Tauri evidence:

- [Corrected card](E:/LamTools/core/docs/architecture/06-review/evidence/task-1b-tauri/card-interrupted.png)
- [Card and pane simultaneously Interrupted](E:/LamTools/core/docs/architecture/06-review/evidence/task-1b-tauri/pane-interrupted.png)

## Remaining limits / release status

- Where a lifecycle event is absent from a paged/current-turn snapshot, registry polling supplies the missing child status; this fallback retains the existing ten-second interval. Failed reads retain the last confirmed state until connection or polling recovers. Missing evidence is not replaced by inactivity-based guesses.
- Timestamp-less legacy records use explicit lifecycle-source precedence. They cannot provide precise historical ordering that was never recorded.
- Interruption/completion/restart/Resume transitions were verified through local regressions; the actual Tauri acceptance used the existing interrupted child and a WebView reconnect. It did not deliberately interrupt a new paid run or restart the backend.
- The existing **0.3.19 installer predates this fix**. Rebuild and packaged Tauri acceptance remain release gates. Development Tauri acceptance is not installer acceptance. No new release version or artifact was published.

[SUNDAY_TASKS.md](E:/LamTools/SUNDAY_TASKS.md) records the brief status and remaining release gate.
