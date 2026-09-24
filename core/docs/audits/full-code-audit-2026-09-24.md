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

### F2 · retracted · A false positive in this audit's own heuristic

An earlier draft of this document claimed `context_compaction/summarizer.py` had no test. That was
wrong, and the way it was wrong is worth recording: the coverage check looked for a module's *file
stem* in the test corpus, so it missed tests that reach the module through its package export.
`core/tests/test_context_compaction.py` imports from `lamtools_core.context_compaction` and covers
the summarizer's parser (accept/reject/round-trip), the pipeline, budget handling, prefix
preservation, recursive compaction and the stream fallback — about 25 tests. No gap.

Lesson applied to the two findings below: check symbol references, not file names.

### F3 · P2 · Three modules have no caller anywhere in the repository

A symbol-level scan of the whole repository (Python, Rust, TypeScript, scripts, manifests) found
three modules whose public API is referenced only inside its own file:

| Module | Size | What it is |
| --- | --- | --- |
| `checkpoint_v2.py` | 11.6 KB | `load_checkpoint_v2`, `migrate_legacy_checkpoints`, `legacy_watermarks`, `CheckpointMigrationReport` — none referenced in production or tests |
| `tool/spreadsheet.py` | 15 KB | `write_spreadsheet_tool` and its XLSX writer built on `openpyxl` |
| `app/http_agent_server.py` | 193 B | A Uvicorn entry point building the app at import time |

Evidence for each: the module's dotted path appears in no import statement, its public names appear
in no other file, and (for the Uvicorn shim) no `.ps1`/`.iss`/`.cmd`/`.yml`/`.toml` launches it —
the live server entry is `create_core_agent_http_app` through `cli.py serve`.

The spreadsheet module looks **superseded rather than forgotten**: `skills/office-spreadsheets`
directs the model to the office CLI and the `office-data.json` render contract, so spreadsheets now
flow through the office renderer. `openpyxl` itself is still a real dependency (the office renderer
tests use it), so only the module is orphaned. The v2 checkpoint module is the one worth a decision:
either its API was meant to be wired up and the wiring was lost in `7a354bdd`, or the v2 path was
abandoned and the module should go.

**No code was deleted.** Removing committed modules is the owner's call, especially where an
intended migration might be unlanded; this is reported instead.

### F4 · P2 · `study_exams.rs` (1777 lines) has no unit tests in `runtime-rs`

No inline `#[cfg(test)]` block and no `runtime-rs/tests/study_exams.rs`. It is covered end to end by
`core/mobile/src-tauri/src/lib.rs` (`study_rpc_round_trips_an_exam_and_its_signed_evidence`) and
mentioned in `runtime-rs/tests/study.rs`, so the happy path is verified. What is untested is the
assessment logic's edge cases: score bounds versus `max_score`, partial/uncertain states, and the
"evidence must belong to the exam" rule that the tool descriptions promise.

### F5 · P3 (recommendation withdrawn) · Workflow script nodes run with the full backend environment

`plugins/bundled/workflow/backend/runtime.py` builds the script subprocess environment with
`env = dict(os.environ)`, so anything exported into the backend process reaches user-authored
workflow scripts.

**The first draft of this audit proposed filtering that environment. That recommendation is
withdrawn**, because it would not reduce privilege: a script node runs as arbitrary Python with the
backend user's full filesystem rights, so it can read the provider records directly — and those hold
API keys in plaintext by documented design (`providers/*.jsonc`). Filtering environment variables
would break existing scripts that read them while closing nothing that matters; the keys would still
be one `open()` away.

The accurate framing is that script nodes are **designed arbitrary code execution on the user's
machine**, gated by `ask_user` on every authoring tool (`workflow_add_node`/`connect`/`update`/
`delete`; `workflow_graph` is read-only `auto_allow`). Anyone who wants a harder boundary needs one
of the real mitigations, none of which is a small change:

- move provider secrets to an OS-backed store (the desktop already uses the Linux Secret Service and
  mobile has secure storage, so this would be a consistency fix as much as a security one), or
- run script nodes in a restricted sandbox (separate user, container, or OS sandbox).

No code was changed for this finding.

### F6 · P3 · `cargo clippy` cannot be used as a gate yet

`clippy --all-targets` exits non-zero on four `unused_io_amount` errors, all in `provider.rs` test
servers (lines 3018, 3050, 3112, 3761), plus 22 warnings. The warnings are style-level (`clamp`,
`is_multiple_of`, `div_ceil`, redundant closures) with two structural ones worth noting:
`large size difference between variants` on the turn-progress enum (`lib.rs:275`) and
`items after a test module` (`workflow_document.rs:2414`). Fixing the four test errors would let CI
adopt clippy as a lint gate.

### F7 · P3 (partially fixed) · 67 panic-path calls in production Rust code

Non-test `unwrap`/`expect`/`panic!`/`unreachable!` calls were concentrated in `workflow_document.rs`
(35), then `workflow_store.rs`, `sub_agent.rs`, `study_notes.rs` and `provider.rs` (7 each),
`profiles.rs` (2), `hooks.rs`/`workflow_runner.rs` (1 each). Mobile and desktop hosts are near-clean
(2 and 13, the latter in the remote control/relay paths).

**Fixed: `provider.rs`, the path every model request takes.** Four `as_array_mut().unwrap()` calls in
the Anthropic, Responses and Gemini stream assemblers indexed arrays the assembler owns. They were
invariant-backed by construction, which is exactly why they were worth removing: a future edit to
initialization would panic mid-stream instead of failing the turn, and the surrounding code already
had the idiom for it (`return Err("out-of-order Anthropic content block".into())`). They now return
errors naming the lost array. `provider.rs` is down from 7 non-test panic paths to 3, and all three
are `unreachable!()` in exhaustive match arms whose case the preceding code already handled — the
conventional, defensible use.

**Remaining: 63 sites, mostly `workflow_document.rs` (35).** These were not touched. The Workflow
subsystem is excluded from the mobile scope and has its own integration coverage, so the case for
sweeping them is weaker than it was for the request path; a dedicated pass with the file's invariants
in mind would be the right way to do it.
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

The residual risk is **maintenance surface, not known defects**: roughly 27 KB of committed code has
no caller, the largest Rust module in the Study subsystem has only end-to-end coverage, and two
hardening items are cheap (filter the workflow script environment, make `clippy` clean enough to
gate). One earlier finding in this document was retracted after a symbol-level recheck — see F2.

Fixed in this pass: F6 (clippy now exits clean), F4 (six `study_exams` unit tests), F7 (the request path), F8
(the stale document, which also carried a corrupted byte). Open: F3 (decide the orphaned modules) and the
remaining panic paths outside `provider.rs`.
