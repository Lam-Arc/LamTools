# LamTools / Sunday full code audit — 2026-09-24

## Scope and method

**Covered:** the whole tracked tree as of `2da89ae0` — Python backend (`core/src/lamtools_core`),
Rust runtime (`core/runtime-rs`), mobile host (`core/mobile`), desktop shell
(`core/desktop`), shared UI (`core/ui`), website, repository scripts and release/config plumbing.

**Method:** automated signals first, then targeted manual review of the paths those signals
flagged, with every claim verified against code or a run rather than inferred. Automated passes:
`cargo clippy --all-targets`, `pylint --enable=E`, panic-path and `unsafe` inventories, a
key-shaped secret scan over tracked files, dangerous-call scans (`eval`/`exec`/`shell=True`/
`pickle`/`yaml.load`/`os.system`), a coverage-gap heuristic, and the previous audit's own repro
fixture.

**Not covered:** the archived member products under `archive/`; the website's copy and visuals;
runtime behaviour on a real phone (no device in this environment); load/performance testing;
dependency-vulnerability scanning (no advisory database available offline).

## Findings

### F1 · P1 (resolved, no action) · The previous audit's hook-enforcement finding no longer reproduces

The 2026-09-23 audit recorded that a `PreToolUse` hook returning `deny` or `ask_user` still let an
`AutoAllow` tool execute, and shipped a fixture
(`core/docs/audits/mobile-desktop-2026-09-23/pre-hook-repro`). Running that fixture on this tree:

```
policy=deny     status=completed         auto_tool_execute_count=0
policy=ask_user status=approval_required auto_tool_execute_count=0
```

The tool does not run on `deny`, and `ask_user` pauses the turn for approval. This matches
`runtime-rs/src/lib.rs`: the pre-tool decision is honoured at the call site
(`pre_decision.permission_decision == "deny"` → blocked tool result) and the permission-request
decision is honoured separately before execution. The fixture was committed and now builds and runs
as a permanent regression check; it needed `text: String::new()` after `ModelTurn::ToolCalls` gained
that field earlier in the day. Conclusion: fixed between the two audits — the earlier report was not
wrong, it is simply no longer current.

### F2 · P2 · The real context-compaction summarizer has no test

`context_compaction/summarizer.py` (13.9 KB) is production-reachable
(`context_compaction/controller.py:45`, `context_compaction/__init__.py:55` export
`summarize_context_messages`) and no test imports or names it.
`core/tests/test_context_compaction_budget.py` drives the controller with a **fake** summarizer, so
the budget logic is covered while the summarizer's own behaviour — prompt construction, truncation,
token accounting — is not. Context compaction directly shapes what the model sees, so a silent
regression here degrades every long conversation. Suggested: a focused test with a scripted model
asserting the summary request shape and the retained/replaced split.

### F3 · P2 · `checkpoint_v2.py` is only reachable through `core_db.py`

The 11.6 KB module is imported solely by `app/core_db.py` and named by no test. Its v2 checkpoint
tables are exercised only insofar as `core_db` tests touch them. Session/checkpoint durability is
the layer that decides whether a crash loses a conversation; an explicit test of the v2
write/read/materialise path is warranted.

### F4 · P2 · `study_exams.rs` (1777 lines) has no unit tests in `runtime-rs`

No inline `#[cfg(test)]` block and no `runtime-rs/tests/study_exams.rs`. It is covered end to end by
`core/mobile/src-tauri/src/lib.rs` (`study_rpc_round_trips_an_exam_and_its_signed_evidence`) and
mentioned in `runtime-rs/tests/study.rs`, so the happy path is verified. What is untested is the
assessment logic's edge cases: score bounds versus `max_score`, partial/uncertain states, and the
"evidence must belong to the exam" rule that the tool descriptions promise.

### F5 · P3 · Workflow script nodes inherit the full backend environment

`plugins/bundled/workflow/backend/runtime.py` builds the script subprocess environment with
`env = dict(os.environ)`. Anything exported into the backend process (proxy credentials, CI tokens,
`LAMTOOLS_*`) reaches user-authored workflow scripts. This is inside the documented trust model —
authoring a node requires `ask_user` (`workflow_add_node`/`connect`/`update`/`delete`;
`workflow_graph` is read-only `auto_allow`) and `exec`/`eval` in the expression evaluator are
annotated as trusted user-authored content — but the environment copy is broader than the feature
needs. Suggested: pass a filtered environment, as the WSL command path already does with
`forward_names`.

### F6 · P3 · `cargo clippy` cannot be used as a gate yet

`clippy --all-targets` exits non-zero on four `unused_io_amount` errors, all in `provider.rs` test
servers (lines 3018, 3050, 3112, 3761), plus 22 warnings. The warnings are style-level (`clamp`,
`is_multiple_of`, `div_ceil`, redundant closures) with two structural ones worth noting:
`large size difference between variants` on the turn-progress enum (`lib.rs:275`) and
`items after a test module` (`workflow_document.rs:2414`). Fixing the four test errors would let CI
adopt clippy as a lint gate.

### F7 · P3 · 67 panic-path calls in production Rust code

Non-test `unwrap`/`expect`/`panic!`/`unreachable!`/`todo!` calls, concentrated in
`workflow_document.rs` (35), then `workflow_store.rs`, `sub_agent.rs`, `study_notes.rs` and
`provider.rs` (7 each), `profiles.rs` (2), `hooks.rs`/`workflow_runner.rs` (1 each). Mobile and
desktop hosts are near-clean (2 and 13, the latter in the remote control/relay paths). Most are
plausibly invariant-backed, but a panic in a turn-handling path aborts the turn — and on mobile it
can take the app down. Worth a focused pass on `provider.rs` first, since it is on every request.

### F8 · P2 (documentation) · `agent_docs/project_progress.md` is stale enough to mislead

It states that ordinary skill loading and Study subagent tools/context "remain missing" and that the
next package is 0.1.8 with 0.1.7 published. Ordinary skill loading and Study subagent tools are
implemented, and mobile is at 0.1.12. Per `AGENTS.md` the Archivist owns these documents, so this is
recorded rather than rewritten here.

## Verified non-issues

Recorded so nobody spends time on them again.

| Item | Evidence |
| --- | --- |
| `pylint E0602` for `LoadTools` (`cli.py:4131`) and `LoopDecision` (`base_agent.py:590`, `:664`) | Annotation-only uses in modules that declare `from __future__ import annotations`; never evaluated. Not runtime `NameError`s. |
| `clippy: read_openai_stream is never used` | Test-only wrapper. Production uses `read_openai_stream_with_idle` for the OpenAI protocol (`provider.rs:522`) and `read_native_stream` for the others. |
| Diagnostics export claims redaction | Implemented: `recordNativeStage` requires an allowlisted stage and stores no `turnId`; `recordTransport` allowlists events and frame types, bounds every number, and stores a classified error kind instead of raw text. The declared contract holds. |
| Provider API keys | `mask_api_key` returns a placeholder for list RPCs; masked or empty write-backs keep the stored key at multiple call sites; no key-shaped value exists in tracked files; no `.lam/` config is tracked. |
| Version sync | Desktop: 5/5 at `0.3.7-beta.1`. Mobile: 8/8 at `0.1.12` (including `Cargo.lock` and the website default). Android versionCode follows the documented formula (1012). |
| `eval`/`exec` in the workflow backend | Two sites, both annotated as trusted user-authored workflow content, behind the `ask_user` node-authoring gate. See F5 for the environment nuance. |
| Path traversal in file tools | Guards exist and are tested on both hosts: Rust `project_tools` rejects absolute paths and `..` components; mobile attachments canonicalise and reject unsafe paths; skill references validate components and containment. Out-of-root access on desktop is a per-turn policy (`core.runtimeControls.allow_access_outside_workdir`), not an oversight. |

## Coverage summary

| Area | Tests | Notes |
| --- | --- | --- |
| Python backend | 2274 passing | 7 modules unreferenced by name; F2/F3 are the substantive two |
| `runtime-rs` | 117 inline + 54 integration | F4 is the notable gap |
| Mobile (TS) | 209 + typecheck | |
| Mobile (Rust crate) | 31 | carries the Study e2e test |
| Desktop UI | 800 | |
| Website | build only | no unit tests, by design |

## Overall assessment

No exploitable vulnerability was found in the reviewed surfaces, and the security posture is
deliberate: approval gates on anything that spends money or touches the network, a policy-gated
escape hatch for out-of-root file access, masked credentials, and a diagnostics export whose
redaction contract matches its implementation. The previous audit's P1 is closed with its own
fixture.

The real residual risk is **verification depth, not known defects**: the context summarizer and the
v2 checkpoint path — both on the critical path for long sessions — have no direct tests, and the
largest Rust module in the Study subsystem has only end-to-end coverage. Two hardening items are
cheap: filter the workflow script environment, and make `clippy` clean enough to gate.

Priority order if work continues: F2 → F3 → F4 → F6 → F5 → F7 → F8.
