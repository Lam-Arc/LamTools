# Core Task 1 — Sub-agent Communication & State Consistency

Inspection and fixes completed against the current E:\LamTools working tree. Existing unrelated changes were preserved. Original databases and logs were inspected read-only; no live provider calls, application restart, packaging, or GUI testing was performed.

## Evidence and observed timeline

Sources: `data/core-agent/sub_agents.sqlite3`, `data/core.db`, the final 4 MiB of `data/core-agent/backend.log`, and the approximately 884 KB development stderr log. Redacted structured evidence is in [evidence/core-task-1-2026-10-13.json](evidence/core-task-1-2026-10-13.json). It contains identifiers, timestamps, statuses, message hashes, and matching history sequence numbers, rather than conversation content or credentials.

The affected parent is `5545f1e3cc4f41fea09bac0ac675a8fb`; child is `host_lamtools_v1`, session `5545f1e3cc4f41fea09bac0ac675a8fb:sub:host_lamtools_v1`.

User-facing times below use UTC−12, matching this chat. Registry epoch timestamps were converted directly; naive SQL timestamps were interpreted using the recorded local UTC−12 environment.

| October 13, 2026 (UTC−12) | Observed fact |
|---|---|
| 01:13:08.393 | Child execution began. |
| 01:14:54.329 → 01:14:55.339 | Parent message entered the mailbox, then appeared byte-for-byte as child user-history row 21, approximately 1.01 seconds later. |
| 01:15:55.929 → 01:16:00.069 | Second message entered the mailbox, then appeared as child user-history row 30, approximately 4.14 seconds later. |
| 01:21:59.896 | Last persisted child runtime state remained `running`, revision 143. Last child history row was a tool result, sequence 83. |
| 01:22:00.155 | Last child-specific synchronization record in the inspected log portion. |
| 02:37:53.851 | Parent runtime was completed. Parent child-tool projection still contained running activity. |
| 02:38:18.773 | Lazy restart recovery marked the registry `interrupted` and wrote `member_interrupted`. Its parent-delivery field remained null. Child Core runtime remained `running`; no corresponding interruption status reached the parent projection. |

All three original parent-to-child mailbox rows had null delivery receipts even though their bodies appeared in child history. Null receipts therefore did not prove delivery failure. The evidence proves active-context insertion; it does not prove that the model understood or followed every instruction. The interruption-detection timestamp does not establish the exact time or cause of process termination.

## Actual delivery semantics

`sub_agent_message` creates a durable mailbox row, deduplicated by the sending run/call identity. An idle child starts a new turn. An already-running child receives guidance at the next safe execution boundary: before sampling, after tool execution/batch writeback, or before sealing a no-tool final response. Guidance arriving at the final boundary keeps the same kernel run going; guidance arriving after that boundary starts a following run.

It does not alter an in-flight provider request or preempt a currently executing tool. A slow provider or long tool can delay that boundary. The observed messages reached the existing child loop; they were not deferred until child completion.

Before the fix, mailbox persistence was only a record: delivery depended on volatile `_guidance`/`_pending_prompts`, no parent-to-child receipt was written, and the kernel popped guidance before checkpointing it. A closeout race could also accept a message into a task that then exited without consuming it.

Now the mailbox is the delivery source. Offers carry stable IDs; initial inputs and guidance retain those IDs in history. The kernel acknowledges after input/checkpoint persistence, and emits guidance-received events after the checkpoint. A committed history row allows replay to avoid appending the same ID twice if receipt writing fails. Unacknowledged messages survive restart or failed checkpoints; interrupted work is not automatically executed again. Explicit re-enabling and messaging can deliver remaining work.

Message acceptance exposes `message_id` and `delivery_mode` (`new_turn` or `next_boundary`). Acceptance means queued successfully; a receipt means incorporated into persisted child context, not task completion or guaranteed model compliance.

## Confirmed causes and implemented fixes

| Priority | Confirmed defect | Fix |
|---|---|---|
| P1 | Recovery changed the separate member registry without reconciling child Core runtime or parent event/snapshot state. It ran lazily and could have no bound parent event sink. | Added startup and watchdog reconciliation that terminalizes orphaned child state, closes matching child turns, and persists/publishes the existing nested member-status event independently of a turn-local sink. |
| P1 | Volatile guidance removal preceded durable context persistence; accepted messages could be stranded at drive closeout. | Durable mailbox offers, checkpoint acknowledgements, history-ID deduplication, and atomic drive ownership release before awaited closeout. |
| P1 | Generic startup stale-turn recovery could cancel a turn belonging to another live process. | Added live-owner checks to the generic reaper and member recovery, plus registry ownership at the pre-kernel launch boundary. Failed runtime reads no longer authorize reaping. |
| P2 | Every parent-to-child receipt remained null after successful consumption. | Persist receipts and backfill legacy receipts only from exact user-history matches, counting occurrences so one historical row cannot acknowledge multiple identical sends. |
| P2 | Explicit child-terminal items were not reliably recognized by UI run projection; stale nested running activity could outrank a child terminal fact. | Terminal envelopes now carry explicit sub-agent identity; projection recognizes historical terminal envelopes and prioritizes child terminal evidence. Interrupted runs acquire terminal timestamps. A newer registry interruption overrides stale running status in the pane, while an older interruption cannot override a newer invocation. |
| P2 | An interruption-only notification did not trigger automatic parent continuation and was not included in an ordinary subsequent input. | Include pending reportable lifecycle facts in the next user-driven parent input and acknowledge after its input checkpoint. Preserve the policy that interruption alone does not initiate a model call. |
| P2 | Recovery-created parent cancellation was treated as an explicit user stop, suppressing otherwise-valid member-completion delivery. | Persist cancellation origin and distinguish `unexpected_shutdown` from user cancellation. Explicit user stops still suppress automatic wakes. |
| P2 | An outbox-write failure could disappear silently, and interruption between registry/outbox writes left no parent notification. | Log publication failures and reconstruct missing terminal outbox facts from registry state using existing idempotent event keys. Duplicate reconciliation does not repeatedly wake the watchdog. |

Parent and child lifetimes remain independent: parent completion does not establish child completion, and child termination does not terminate the parent turn. Registry lifecycle, child runtime, durable events, and UI snapshots remain distinct stores; synchronization now uses idempotent reconciliation rather than assuming one transaction spans both databases.

## Code map

- Delivery, durable offers/receipts, drive closeout, owner fencing, lifecycle events: [sub_agent_supervisor.py](../../../src/lamtools_core/sub_agent_supervisor.py).
- Guidance persistence and acknowledgements: [kernel/loop.py](../../../src/lamtools_core/kernel/loop.py), [runtime input contract](../../../src/lamtools_core/runtime/__init__.py), [child runner](../../../src/lamtools_core/tool/sub_agent_runner.py).
- Startup/watchdog reconciliation: [sub_agent_recovery.py](../../../src/lamtools_core/app/sub_agent_recovery.py), [HTTP startup](../../../src/lamtools_core/app/http_agent_app.py), [supervisor](../../../src/lamtools_core/app/memory_resume_supervisor.py).
- Parent notification and cancellation provenance: [default_agent.py](../../../src/lamtools_core/app/default_agent.py), [live_operations.py](../../../src/lamtools_core/app/live_operations.py).
- Child terminal wire identity and UI selection: [runtime_projection.py](../../../src/lamtools_core/event/runtime_projection.py), [subAgentProjection.ts](../../../ui/src/agents/subAgentProjection.ts), [CoreSubAgentPane.vue](../../../ui/src/components/CoreSubAgentPane.vue).

## Verification

- Broad Python regression batch: **432 passed, 1 skipped**, across 15 selected runtime/application test files. The existing skipped HTTP Arrange test has a documented TestClient/background-worker teardown limitation; direct Arrange tests provide its separate lifecycle coverage.
- After the final outbox-notification change: **62 passed** in the affected supervisor, memory-supervisor, and new consistency test files. This subset overlaps the broad batch; counts are not additive.
- UI regression batch: **165 passed**, across 12 selected test files.
- All three configured UI typecheck projects passed. `git diff --check` passed.
- New regressions cover same-run guidance, receipt/history ordering, failed checkpoint replay, closeout arrival, startup state alignment, idempotent event publication, live-owner protection, legacy repeated-body receipts, next-input interruption delivery, and duplicate outbox notifications. Existing approval-survival, parent/child independence, and user-stop tests remain passing. Separate tests cover recovery-origin wakes and generic-reaper owner preservation.
- Fixtures use temporary databases and scripted model streams; zero paid provider calls were required.

## Limits and activation

The original process termination cause remains unproven. Original databases were not repaired in place during inspection. Reconciliation activates on the next backend start and retries on watchdog passes. No restart was forced while other application work might be active; no user visual acceptance is claimed.

This fixes the Python runtime used by desktop and remote clients plus shared UI projection. The embedded mobile Rust runtime was not changed or exercised. Legacy messages without exact matching history remain unacknowledged rather than receiving invented delivery evidence. Owner liveness continues to rely on the existing PID/host-token mechanism; process-ID reuse is not addressed here.
