# Mobile Study domain parity audit (2026-09-23)

Scope: read-only comparison of the desktop Python Study plugin and mobile native Rust Study store/adapter. The skill/prompt assembly fix is outside this audit. No Android UI automation or remote model call was used. The focused native scripted AgentRuntime test and `cargo check` were run for the prior implementation; findings below come from source paths and deterministic call schedules.

## Findings

### P1 — Concurrent text actions can overwrite a saved answer

Desktop `marks.answer` obtains a per-mark `asyncio.Lock` before reading the mark and holds it through model completion and write (`core/src/lamtools_core/plugins/bundled/study/marks.py:154-201`). Mobile `StudyStore::answer` reads the entire mark, drops the connection before awaiting the model, then writes the same entire mark after completion with no per-mark lock or revision comparison (`core/runtime-rs/src/study.rs:2373-2518`); native RPC dispatches independent `study.text` requests (`core/mobile/src-tauri/src/lib.rs:1339-1359`).

Deterministic interleaving: create mark M; start two `study.text` actions `{id:M,action:"ask",question:"A"}` and `...question:"B"}` with model responses held at a barrier. Both read the empty thread. Release A then B. A writes `[A,answerA]`; B writes its stale copy `[B,answerB]`. A returned success but its durable turn is lost. Desktop serializes these requests and keeps both turns. This applies to concurrent `explain`/`translate` on the same mark as whole-record stale writes too.

### P2 — Mobile Study search cannot find Notes or Study chats

Rust `StudyStore::search` only loops over graph nodes (`core/runtime-rs/src/study.rs:1788-1865`); native `dispatch_study` returns it unchanged (`core/mobile/src-tauri/src/lib.rs:1298-1300`). Desktop `StudyStore.search` additionally reads Note title/source/Markdown (`core/src/lamtools_core/plugins/bundled/study/store.py:806-833`), and `backend.study_search` merges matching Study session titles and message contents (`core/src/lamtools_core/plugins/bundled/study/backend.py:267-324`).

Repro: create a Note with a unique term only in `body_md`, then call `study.search` with that term; desktop returns a `note` target, mobile returns `total:0`. Likewise a term only in a Study chat message yields a desktop `session` target and zero mobile results. This is a visible feature gap even though graph-node search itself works.

### P2 — Active exam context is omitted from mobile Study chat context

Desktop `study_context` collects up to eight relevant exams with statuses `open`, `in_progress`, or `submitted`, filtered by selected node, into `latest_context.exams` (`core/src/lamtools_core/plugins/bundled/study/backend.py:365-385`). Rust `StudyStore::context` builds language, selected node, course and teaching position, then saves/returns immediately (`core/runtime-rs/src/study.rs:2526-2641`), with no exam query. Repro: create an exam for a node and call `study.context` for that node. The mobile context has no `exams` key, so the next Study request lacks the desktop's compact in-progress exam cue.

### P3 — Legacy curation task actions are absent on mobile

Python `StudyStore.notes` routes `task_*` and `curate_*` to a durable revision-checked task state machine (`core/src/lamtools_core/plugins/bundled/study/store.py:1582-1694,1994-2002`). Rust `StudyStore::notes` accepts only Raw/Resource/Note actions and returns `Unknown note action` for these task actions (`core/runtime-rs/src/study_notes.rs:347-395`). Repro: `study.notes {action:"task_create"}` works on desktop and fails on mobile. I found no direct `task_*`/`curate_*` caller in current Study UI or active skills, so this is a compatibility gap rather than a confirmed current user flow.

## Covered paths with no further confirmed discrepancy

| Area | Desktop evidence | Mobile evidence | Result |
|---|---|---|---|
| Graph layered read, build, revision, delete/restore | `store.py:365-731` | `study.rs:516-1787` | Same major operations and structure revision checks; no additional confirmed mismatch from static review. |
| Assessment sign and exam lifecycle | `store.py:1028-1289`, `exams.py:136-440` | `study_exams.rs:470-1510` | Create/save/submit/help/grade/review/reference/sign paths present; private answers and evidence checks present. |
| Raw → Resource → Note, citations, history, locks | `store.py:1696-2300`, `note_vault.py:28-160` | `study_notes.rs:27-1790` | Core actions and trusted writer split present. Rust `raw_list` syncs graph records (`study_notes.rs:355,459-480`); mobile host syncs session messages (`mobile/src-tauri/src/lib.rs:1124-1244`), matching desktop host split (`backend.py:394-464`). |
| Selection mark create/list/get/delete and answer | `marks.py:110-201` | `study.rs:2212-2518` | Same actions and bounded selection prompt; concurrency finding above. |
| Pins and session bindings | `store.py:842-937,1290-1339`, `backend.py:148-266` | `study.rs:1867-2000,2084-2210`, `StandaloneTransport.ts:295-373` | Stable id pins and binding operations present; mobile host owns session metadata. |
| Outbox and events | `store.py:1330-1338`, `backend.py:555-574` | `study.rs:2051-2082`, `mobile/src-tauri/src/lib.rs:1284-1298` | Durable outbox exists. UI event fanout belongs to transport and is outside this bounded domain review. |

Limitations: This was source parity review, not exhaustive schema fuzzing or a side-by-side database replay. The exam/sign and Note code is extensive; absence of another finding should not be read as a proof of byte-for-byte behavioral equivalence. No broad test suite was run because it would not resolve the identified gaps.
