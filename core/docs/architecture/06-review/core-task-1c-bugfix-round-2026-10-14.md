# Core Task 1C bug-fix round (2026-10-14)

Fixes for three user-reported defects found while exercising Task 1C in the Tauri dev build. Read-only investigation preceded every fix; each fix has code-level tests and the full suites pass. No installer build, no publication, no visual acceptance claim.

## Defect 1. First open of a long session took ~61 s and then failed

**Cause.** `thread.resume`, `thread.read`, `thread.history` and `thread.outline` all called `persistence.load`, which materializes **every** item row of the thread before answering. The reported thread holds 6,030 rows / 74 MiB of item JSON (single items up to 400 KiB, mostly child-agent tool output) inside a 2.4 GiB `core.db`. On a cold cache that read took 61.4 s, just past the client's 60 s timeout, so the client reported a failed load and cleared the transcript; the retry was fast because the pages were then cached. `thread.outline` in the same window took 60.6 s.

**Fixes.**

| Area | Change |
| --- | --- |
| Store | `SqlAlchemyThreadSnapshotStore.load_page` reads the metadata row plus only the newest item rows, streamed backwards from the cursor and stopped at a byte budget (6 MiB default, 4,000-row cap). `core.item_order` keeps the full metadata order, and one index probe records whether older rows exist. |
| Page builder | The paging envelope (`total_items`, `has_more`) is computed from the metadata's item orders instead of from the loaded items, and `has_more` also honours the store's probe. The private probe key is stripped from the wire page. |
| Handlers | `thread.resume` / `thread.read` / `thread.history` use the bounded read with a read budget of three times the requested page budget. |
| Client | `requestWithTimeoutRetry` retries a transcript read once after a timeout. The desktop shell's session selection now passes `attachInBackground`, so the persisted page paints before the live attach resolves. |

**Measured on the live backend, heavy thread.** `thread.read` 0.51 s (194 of 6,074 items, `has_more` true, 2.0 MiB), `thread.resume` 0.64 s, `thread.outline` 0.47 s. Before: 61.4 s and 60.6 s. The read volume per open dropped from about 82 MiB to about 13.5 MiB, so a cold open improves proportionally and no longer grows with thread length.

**Deliberately not changed.** `thread.outline` keeps the complete read. A turn's own closing assistant message can sit 200 items deep inside a turn that ends with child output, so no bounded tail reproduces it exactly; an empty or wrong excerpt is worse than a slow outline panel. The builder does now ignore child-owned items when choosing a turn's excerpt, so a child's report can no longer appear as the turn's own summary.

## Defect 2. Stop terminated instead of pausing everything

**Cause.** `turn.cancel` only cancelled the parent turn. Children are independent by design (Task 1 / 1A), so they kept working, which read as "terminated, not paused". With the parent turn already finished, the Task 1C child Stop did pause them, which is the difference the user identified.

**Fix.** A user Stop now pauses the whole session. `_turn_cancel_finalizer` and `handle_turn_force_reset_operation` call `_interrupt_session_members`, which interrupts the session's running/pending members through the supervisor. Members waiting on an unanswered question are deliberately left alone, so a question card survives a Stop. Resume already continues both the parent turn and interrupted members.

## Defect 3. Child question cards disappeared, were replaced, or became unanswerable

Three separate causes.

1. **Identity.** A child's item ids are scoped by `(child session, child run, invocation)`, and every continuation minted a fresh invocation scope, so the answer's `runtime.tool.finished` created a second item while the original waiting card stayed `waiting` forever. The runner now records the scope it ran under in the child state (`sub_invocation_id`) and continuations reuse it, so the answer resolves the card that asked, in place.
2. **Admission.** The approval continuation claimed the **parent thread** in `RuntimeTaskRegistry`, which admits one run per thread. Answering a second child while the first child's continuation was still running therefore failed with `RuntimeError: approval continuation runtime claim failed`. Child continuations now claim their own child session; the parent thread's claim stays free for the parent turn. Inline continuations are also registered with the supervisor (`track_inline_task`) so a Stop can cancel them.
3. **Stranded claim.** A refused claim left the child's pending approval marked `executing`, after which every later click failed as "approval already resolving". A refusal now rolls the pending back to `waiting` (guarded to the exact request, and only while it still reads `executing`) so the question stays answerable.

## Verification

- New Python tests: `core/tests/test_thread_page_load.py` (4), four added cases in `core/tests/test_sub_agent_takeover.py` (question identity, per-child claim, claim rollback, Stop interrupts children). Each takeover test now runs on its own thread id, because supervisors live in a process-global map keyed by `(data_dir, thread)` and the lookup helper matches on thread id alone.
- New UI tests: `core/ui/tests/thread-open-resilience.test.ts` (2).
- Full Python suite: **3,035 passed, 2 skipped**. Full UI suite: **150 files, 1,399 passed**. All three `vue-tsc` projects pass. `git diff --check` clean.
- Live check on the restarted dev backend: capabilities `same_turn_resume` and `sub_agent_control`, bounded pages with correct envelopes on both a heavy and a light thread.

## Remaining limits

- Backend changes need a full application restart; the dev instance was restarted and verified.
- The outline panel keeps a complete read, so it can still be slow on a cold, very large thread; the transcript is unaffected and the client retries a timeout once.
- Stop now also stops background children. A user who stops only to redirect the parent must press Resume to continue them; members paused on a question are not touched.
- Two child continuations may run in parallel now; each writes only its own child session and publishes idempotent member events.
- No visual Tauri acceptance was performed for this round, and the 0.3.19 installer predates these fixes.

## Defect 4. A child's question card vanished when the main turn ended

Reported as "there is no question" while the child sat paused. The question was
in the durable snapshot and the backend had published it, so the loss was on the
client. Reproduced headlessly by replaying the session's real events: the client's
live terminal-turn rule closes every non-terminal item of the turn, and the
child's question carries the parent turn's id, so the parent's terminal event
flipped the card from `waiting` to `completed` and the pending list dropped from
one to zero. The server has skipped child-owned rows there since the 2026-10-10
rule (`snapshot/__init__.py`, `_close_turn_items` skips `_is_sub_agent_child_item`)
so a member's card outlives the parent turn; the client never mirrored that
condition, which is also the earlier "the first question disappeared" report, and
why switching sessions (a reload) brought the card back.

Fix: the client's terminal-closing loop skips child-owned items using the same
predicate the server uses (`parent_item_id` or a `sub_agent` payload block), so a
member's pending question or approval survives the parent turn's end while the
parent turn's own leftover rows are still closed. Regression test:
`core/ui/tests/child-question-survives-turn-end.test.ts` covers both directions.

UI suite after this fix: 151 files, 1,401 tests passed; typechecks clean;
`git diff --check` clean. The dev instance was restarted and the previously stuck
question remains `waiting` server-side, so it can be answered after a reload.

## Stop is a pause

Reported after the first bug-fix round: "停止依旧导致了已中断". The user then
stated the intended semantics for the feature and confirmed the full contract
before implementation:

1. A single click on the composer button pauses the running turn
   (`turn/pause`). The step's streamed thinking and output are dropped, an
   in-flight tool is recorded as interrupted, unexecuted tool calls are dropped,
   and only tool results that already succeeded stay.
2. A pause parks the whole session: every active member is parked with it, and a
   member waiting on a question keeps its card answerable (its answer queues
   until the session continues).
3. Automatic events arriving while paused (member completions, member wakes)
   queue; nothing continues the session on its own.
4. A paused turn reads 已暂停, the sidebar marks it with a pause icon, its
   duration freezes, it never expires, and it survives a backend restart.
5. With an empty composer the button continues the turn; once text is typed the
   button sends, which continues the same turn with that text as a supplementary
   input.
6. Continue re-enters the same turn from its committed history with no synthetic
   prompt and continues every parked member in the same press.
7. A member's own Continue is disabled while the session is paused; it stays
   available when the session is not paused (the Task 1C case).
8. A 0.8 s long press (progress ring, hint at the right of the button) opens an
   in-app confirm that lists what will be discarded; confirming terminates the
   turn and all its members for good.
9. A terminated turn is final: it no longer offers Continue, so the old
   cancelled-turn resume path is gone.
10. Provider and model errors still read 失败; crash leftovers read 已中断; no
    step or budget limit is introduced.
11. Host memory exhaustion parks the turn instead of failing it (one 已暂停
    state in the interface, the reason kept in the log) and the watchdog
    continues it once memory is available.
12. Queued messages are untouched by a pause; they go out after the turn ends.
13. Desktop only for now; the mobile client keeps `turn/interrupt`.

Implementation notes worth keeping:

- The kernel gained a pause signal (`pause_event_source`) beside its cancel
  signal. Both abort a streamed answer cooperatively; a pause ends the run in
  the resumable `paused` state and emits `runtime.paused` (a decision event, not
  a terminal one), while a cancel keeps converging on `cancelled`.
- `RuntimeTaskRegistry.request_pause(force=True)` also cancels the task, so a
  tool that never polls the pause event is torn down; the kernel tells that
  teardown apart from a cancel and still parks the turn.
- The application layer writes the interrupted tool results and the paused
  status item itself in a detached finalizer, and settles the runtime state, so
  a Continue issued right after the pause never reads "still settling".
- A paused turn must not be reopened by a late item: the snapshot projector only
  lets a status event or a resume take it back to `running`.
- The thread-level status follows the runtime (`sync_status_from_core` and the
  session record read `effective_thread_status`), because the session list and
  the sidebar read the flattened status.

Verification: 3,040 Python checks and 1,409 UI checks pass, UI typechecks are
clean. Verified live over the CLI against the dev backend: pause mid-stream,
paused status surviving a backend restart, continue re-running the cut step, and
terminate producing 已中断 plus a refused continue. Not verified: the in-window
long press and the confirm dialog (code review only), and no installer build,
publication, or visual acceptance was performed.
