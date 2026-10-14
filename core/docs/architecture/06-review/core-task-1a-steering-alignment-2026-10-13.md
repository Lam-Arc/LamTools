# Core Task 1A — Main/Sub-agent Steering Alignment

Task 1 fixes were retained. This is a delta review of steering delivery, not a repeat of the previous database/log investigation. Implementation and regression verification cover the Python application runtime used by desktop and remote clients. The embedded Rust/mobile capability differences are stated separately below.

## Shared execution semantics

Main and child runs execute `CoreLoopKernel`; there is no separate main/child implementation of guidance application.

| Boundary | Main and sub-agent behavior |
|---|---|
| Before sampling | Incorporate available committed guidance as user input before building the next model request. |
| During a provider call or executing tool | Queue input; do not alter the active request or interrupt the executing tool. |
| After sequential tools | Collect guidance after a tool boundary, finish ordered tool-result writeback (including skipped remaining calls), then apply and checkpoint it. |
| After parallel tools | Incorporate guidance at the next sampling boundary after the batch settles. |
| Completion verification | Keep steering open while verification may continue the run. Re-check input after verification before sealing a successful completion. |
| Would-be final response | Guidance arriving before the final boundary forces another model round in the same run. |
| Delivery acknowledgement | Checkpoint input/history IDs before acknowledging/removing the offer or emitting `runtime.guidance_received`. |

“Accepted” means successfully queued/recorded. “Acknowledged” means incorporated into checkpointed context; it does not mean the model followed the instruction or completed its task.

## Differences found and fixed

### P1: Main guidance was visible before durable acceptance

Both `turn.steer` and `queue.guide` previously added input to `RuntimeTaskRegistry` inside an awaited database transaction. The runtime could consume that input before commit. If commit retries failed, retraction could not undo context already consumed. Existing retry tests explicitly simulated that ordering.

Main acceptance now reserves a hidden offer with `ready=False`. Only after the existing event transaction commits does `_activate_stored_guidance` make it available. Rollback retracts the reservation. Queue guidance still commits its steer and queue removal together. An idempotent retry of a committed event can reactivate its original text/ID if activation did not complete; altered retry text cannot replace it.

The asynchronous finalizer waits for outstanding acceptance transactions to commit or roll back rather than sealing over an unresolved reservation. Publish, rollback/retraction, cancellation, and release signal its wait.

### P1: Main IDs/receipts were lost at consumption

Main consumption previously discarded the stored guidance ID and removed the message before its context checkpoint. Task 1's child mailbox preserved both.

The production main source now offers committed messages without deleting them, includes immutable `metadata.guidance_id`, and acknowledges through the shared kernel after checkpoint persistence. `guidance_ids` are retained in history for duplicate detection and durable receipt evidence. Anonymous registry injections receive distinct IDs. Built-in registry sources expose their acknowledger for SDK callers; the application callback also handles its mailbox/lifecycle sources.

Accepted but uncheckpointed main input can be recovered from the existing `turn/steered` events on a later turn. The helper subtracts IDs present in persisted user/system history, and recognizes only the new explicitly marked acceptance records. No table or additional state authority was introduced. Unmarked legacy events are not guessed to be pending. Restored instructions precede the current input so the newer input remains authoritative. Recovery does not itself start an automatic turn or call a model.

### P2: Main guidance sealed before completion verification

The shared kernel previously finalized main guidance before an awaited completion gate, although that gate could turn `done` back into `continue`. Main steering could therefore be rejected as closed while work continued, whereas the child mailbox remained accepting.

The kernel now makes a non-sealing guidance check before verification, then performs the final check/seal only after successful verification. Input arriving during either a passing or continuing verification is retained and applied. Regression tests cover both cases.

### P2: Built-in child-to-parent replies acknowledged at enqueue

The built-in parent guidance sink now advertises checkpoint acknowledgements. A child reply injected into a running parent remains pending in its durable mailbox until the parent's checkpoint callback acknowledges the injected guidance ID. Replies included with a fresh parent input are likewise acknowledged after its input checkpoint, rather than waiting for the whole run to return. Legacy injected sinks retain their compatibility contract.

## Intentional remaining differences

- Main `turn.steer` targets an existing run. Once its final gate is sealed, a new steer is refused; the caller must send a new turn. A named child's mailbox targets a reusable child, so input accepted after one run's final boundary can start the next child run. This is an identity/lifecycle distinction, not different treatment of guidance during an active run.
- Plain-string SDK guidance sources and legacy custom sinks do not provide the same durable acceptance/receipt guarantees as the application's ID-bearing sources. Production main and child paths use the checkpoint contract.
- Embedded mobile main steering still explicitly reports `native_turn_cannot_steer_live` and queues `steer_after_turn`; Rust children drain mailbox guidance before the next model request. The native child adapter also marks mailbox delivery during drain, rather than using the Python checkpoint acknowledgement contract. These separate native capabilities were inspected statically, not modified or verified as Python-equivalent in this task. No cross-platform parity claim is made.

## Code references

- Main stage/offer/acknowledge/finalizer: [runtime/__init__.py](../../../src/lamtools_core/runtime/__init__.py), `RuntimeTaskRegistry`.
- Shared checkpoint and verification boundary: [kernel/loop.py](../../../src/lamtools_core/kernel/loop.py), `_collect_guidance`, `_apply_guidance`, `_acknowledge_guidance`, completion decision path.
- Commit-before-activation for both public handlers: [live_operations.py](../../../src/lamtools_core/app/live_operations.py), `_activate_stored_guidance`, `handle_turn_steer_operation`, `handle_queue_guidance_operation`.
- Host acknowledgement and later-turn recovery: [default_agent.py](../../../src/lamtools_core/app/default_agent.py), `acknowledge_input`, `parent_guidance_sink`; [steering.py](../../../src/lamtools_core/app/steering.py), `pending_steering`.
- Durable child reply receipts: [sub_agent_supervisor.py](../../../src/lamtools_core/sub_agent_supervisor.py), `child_message`, `acknowledge_parent_guidance`.
- Native limitation: [StandaloneTransport.ts](../../../mobile/src/standalone/StandaloneTransport.ts), `steer_after_turn`; [Rust sub_agent.rs](../../../runtime-rs/src/sub_agent.rs), `MailboxGuidance`; [Rust lib.rs](../../../runtime-rs/src/lib.rs), late-guidance drain.

## Verification

Final selected Python regression run: **409 passed**, across 14 affected runtime/application test files. Task 1's state consistency, child lifecycle, approval, memory recovery, and ownership regressions remain passing. No assertion or failure visibility was weakened.

New/strengthened checks include paired main/child checkpoint success and failure, stable IDs, anonymous input IDs, commit/rollback versus final sealing, completion-gate steering, durable activation retry, exhausted transaction retries with no uncommitted delivery, preservation of queue entries on failed commits, recovery without duplicate receipt replay, system-origin receipts, and child-to-parent checkpoint acknowledgement.

`git diff --check` passed. Tests used scripted models and temporary databases; there were no paid model calls, original-database edits, repeated manual runs, backend restart, package builds, or GUI verification. Existing Task 1 UI fixes and unrelated working-tree changes were preserved. Backend changes take effect after the next full backend restart.
