# Core Task 1C — Child takeover on Stop/Resume and question-answer resume

Completed in the Python Core runtime and the shared desktop/remote UI on 2026-10-14. A previous session had left the backend foundation for requirement 1 in the working tree, unreachable from any host; this session completed the wiring, fixed the two defects that blocked it, implemented requirement 2, and verified both. Tasks 1, 1A, 1B, and 7 remain intact. No paid model calls, production database edits, installer build, publication, backend restart, or GUI/visual acceptance were performed.

## Requirements

| # | Requirement | Resulting behavior |
|---|---|---|
| 1 | When the parent Agent turn is completed but children remain active, Stop/Resume must control the children without restarting the parent. | With the parent turn terminal and a member running, the composer's Stop becomes available and interrupts the members; with members interrupted it offers Resume and continues them. Neither restarts, re-cancels, or rewrites the parent turn. With a draft present the composer still sends. |
| 2 | When a child asks a question through the parent interface, answering must automatically resume that child. | The user's answer is delivered as the child's own `question` tool result, persisted in the child session's history, forwarded onto the parent timeline under the child identity, and the child continues its own run. The parent thread receives no stray tool row and no parent model call is made to deliver the answer. |

## Already implemented before this session (preserved, not rewritten)

The working tree already contained the 1C backend foundation, all of it unreachable:

- `SubAgentSupervisor.interrupt_active` / `resume_interrupted` (member-task cancellation, `member_interrupted` publication, resume scheduling from committed child history).
- `KernelSubAgentRunner.resume_interrupted` with `origin="turn_resume"` and the `_run_turn` extensions (`delegated_task`, `run_id`, `turn_id`, `origin`).
- Supporting Task 1/1A machinery: durable mailbox offers with `guidance_id` receipts, `runtime_owner` fencing, deterministic member-status event ids, `report_members_drained`.

No operation, CLI verb, or UI path reached any of it, so a running child could not be stopped or resumed by a user at all.

## Implemented changes

| Area | Change | Reference |
|---|---|---|
| Member lifecycle surface | `sub_agent.interrupt` and `sub_agent.resume` are registered on the operation catalog, session-scoped, returning the affected records plus `lifecycle_action`. They act on the members themselves and never touch the parent runtime registry. | `sub_agent_supervisor.py:1484`, `:1514` |
| Stop settlement | After cancelling member tasks, Stop waits (bounded, 3 s) for each child's runtime state to leave the live set, so the kernel's detached cancel-finalizer cannot race a Resume. Records are already interrupted either way. | `_await_children_settled` `sub_agent_supervisor.py:747` |
| Resume durability | Resume writes a `member_resumed` durable outbox fact in addition to the in-turn live publish, so the transition is visible when no parent turn holds a live sink. | `sub_agent_supervisor.py:802` |
| Ownership guard defect | A member whose recorded owner was *this* process no longer counts as "owned by another running process". Previously `resume_interrupted` skipped every member this process had released, which made Resume a silent no-op; a live token from another process is still refused. | `_owned_elsewhere` `sub_agent_supervisor.py:205` |
| Child question answer (defect) | An option click on a child's question card arrives as an approval decision (`approve_once`) — the delegated branch then executed the `question` tool on the child toolbox and returned the "auto-approved without user input" placeholder, discarding the user's answer. A question is now answered, not executed: the option text is the answer for `approve` and `guide`, and `deny` keeps the existing "declined" wording. | `default_agent.py:1134`, `:1189` |
| Child question answer (resume) | A question on a delegated child runs on the child runner: the answer is emitted to the parent timeline through the child forwarding sink, cleared from the pending approval, persisted as the child's own `question` tool history row, and the child continues with `question_answer_continuation_prompt` on its own identity, toolbox, and request-local context. The member record converges through the existing `finalize_resumed` path. | `KernelSubAgentRunner.resume_question` `tool/sub_agent_runner.py:1047`; wiring `default_agent.py:1267` |
| Thread purity | The main agent's answer keeps being written to the thread that asked; a child's answer is written only to the child session, so the parent history no longer carries a child's `question` tool result. | `default_agent.py:1168` |
| UI Stop/Resume target | `CoreSessionActivity` exposes `interruptibleSubAgentNames` (members running/pending) and `resumableSubAgentNames` (members interrupted) from the same reconciled records every status label uses. The composer derives a child stop target when the parent turn is not active and the draft is empty, and a child resume target when members are interrupted and the parent turn is not resumable. | `sessionActivity.ts:60`, `:149`; `useCoreLiveComposerController.ts:161`, `:169` |
| UI dispatch | Child-directed Stop sends `sub_agent.interrupt` (no `turn/interrupt`, no force-reset escalation, no grace timer); Resume sends `sub_agent.resume` and additionally continues interrupted members when the parent turn itself is resumable. Responses fold into the same record map the registry poll fills. | `useCoreLiveComposerController.ts:302`; `createWorkbench.ts:334`, `:339`, `:432` |
| Capability contract | The Core app server advertises `sub_agent_control` alongside `same_turn_resume`; the composer shows a child control only when the connected runtime advertises it, so the embedded mobile standalone transport (which implements neither operation) offers no dead Stop. | `live_router.py:932`; `useCoreLiveComposerController.ts:160`; `createWorkbench.ts:434` |
| CLI parity | `core subagent interrupt <thread_id>` and `core subagent resume <thread_id>` (same live-connection options as the other lifecycle verbs). | `cli.py:2124`, `:4506` |

Design notes that are deliberate, not oversights:

- The composer shows child Stop only when member evidence exists (a published member status or the polled registry record). With no evidence it stays `send`, exactly as before; the transcript-inferred count alone does not authorize a stop.
- Priority order is unchanged where Task 7 defined it: an active parent turn keeps `turn/interrupt`, a cancelled parent turn keeps `turn/resume` (plus a child resume when members are interrupted). Child Stop never outranks a resumable parent turn.
- Child control is session-scoped: the operations address the session's members as a set. A member interrupted in an earlier turn is likewise resumable; the action is explicit and user-initiated.

## Verification

All models are scripted, all states in-memory or temporary; zero paid provider calls, no production database edits, no backend restart.

- **Python, new `core/tests/test_sub_agent_takeover.py` — 8 passed**: child Stop with a terminal parent turn interrupts the member (child state `cancelled`, record `interrupted`, parent state and history byte-identical, `llm.parent_calls` unchanged); child Resume continues the member from committed history (`resume_prompt_seen`, member back to `idle`, parent untouched); both operations are registered and return empty items for a thread without members; an option click on a child's question resumes the child with `blue` as its own `question` tool row in the child history and nothing in the parent history; a free-text answer does the same with its text; a dismissed question resumes the child with the declined-answer wording instead of leaving it paused; the main agent's question still lands in the thread history; the CLI parser exposes both verbs.
- **Focused Python batch — 83 passed** on the final code across `test_sub_agent_takeover.py`, `test_sub_agent_supervisor.py`, `test_sub_agent_state_consistency.py`, `test_steering_alignment.py`, `test_same_turn_resume.py`, `test_member_turn_boundary.py` (135 passed earlier in the session including the child-runner and memory-resume suites).
- **Full Python suite** (`py -3.14 -m pytest tests` from `core/`, `PYTHONPATH=core/src`): **3,027 passed, 2 skipped**. One pass under the shell's inherited `http_proxy`/`https_proxy`/`all_proxy=http://127.0.0.1:7890` reported a single failure, `test_command_tools.py::test_python_http_server_lifecycle_contract_with_real_process`, which is environmental, not a 1C regression: that test's in-process `urllib` probe of `127.0.0.1` is sent to that proxy and answered `502 Bad Gateway`. It passes in this tree with those variables cleared (the run recorded above), and `test_command_tools.py` contains no sub-agent code. Existing SQLite datetime-adapter deprecation warnings remain.
- **UI, new `core/ui/tests/sub-agent-takeover.test.ts` — 7 passed**: Stop in state (b) sends only `sub_agent.interrupt`; Resume for an interrupted member sends only `sub_agent.resume`; a real draft keeps `send`; an active parent turn still sends `turn/interrupt`; a cancelled parent turn keeps `turn/resume` and also resumes interrupted members; no member evidence keeps `send`; a runtime without `sub_agent_control` keeps `send` even with an interrupted member record.
- **Full UI suite (`npm run test:contract`) — 149 files, 1,397 tests passed** (1,390 before this task).
- **UI typechecks**: all three `vue-tsc` projects passed.
- `git diff --check` passed.

## Limits and activation

- Backend changes take effect after a full backend/application restart; no restart was forced during this work.
- Resuming a member through the lifecycle operation while no live parent sink exists publishes the member's durable status but not its streamed items into the parent timeline; this is the same limitation `sub_agent.message` already has and is covered by the 10-second registry poll.
- Answering a child's question finalizes the member record without publishing an additional status event, matching the existing approval-resume path; the pane converges on the next poll or live child event.
- The sub-agent pane and card remain read-only by design; the composer Stop/Resume is the child-control surface. No per-child buttons were added.
- The embedded Rust/mobile runtime was not changed and does not advertise these operations.
- **Visual Tauri acceptance and installer acceptance were not performed.** The 0.3.19 installer predates this fix, so rebuild plus packaged Tauri acceptance remain release gates. No release version was bumped and nothing was published.
- No database or log evidence file accompanies this report: 1C is an implementation completion, and its verification is code-level only.

[SUNDAY_TASKS.md](E:/LamTools/SUNDAY_TASKS.md) records the brief status.
