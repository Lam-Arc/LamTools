# Infrastructure Task 3B — turn/start timeout and late success

Release status: **NO-GO pending Tauri acceptance**. Source fixes, automated
regressions, production build, installation and final installed-backend
verification passed (`acceptance-result.txt`). No commit/tag/publication/deployment.

## Root cause and lifecycle

The current Tauri development log has one matching request, `direct-584`, for
thread `5545f1e3cc4f41fea09bac0ac675a8fb`. Its duplicate-message lookup awaited
**62.009 seconds**; metadata loading then took 27 ms and append/projection
261 ms. Core processed the request successfully in **62,763.8 ms**, and sent
its reply immediately afterward. Agent task creation took effectively 0 ms
and happened only after the acceptance transaction. This was acknowledgement
delay before Agent execution, not a model inference timeout.

The database only indexed `(thread_id, seq)`. Looking for a fresh random
`client_message_id` had to scan the thread's historical event rows. This lookup
ran inside the shared write transaction, also delaying other mutations. The
read-only query plan confirms the thread-only index. A new partial composite
index searches `(thread_id, client_message_id, seq)` directly and avoids reading
historical payloads for a missing ID. Existing current-schema databases receive
the index at startup; no user records or schema-version contract were removed.

UI flow: composer captures input and generates an idempotency key → runtime
store requests `turn/start` with `include_snapshot: false` → CoreAppServerClient
→ DirectTransport WebSocket → Core router/session actor → duplicate lookup,
active-turn check and atomic acceptance commit → acceptance events/runtime
registration → RPC reply → UI response application and composer settlement.
Agent model/tool execution continues independently after acceptance.

Previously, DirectTransport's 60-second timer deleted the local RPC waiter and
rejected the promise. It sent no cancellation to Core. Core therefore committed
success afterward; its late RPC reply was ignored, but event notifications still
updated the thread. The composer showed failure and retained its draft; pressing
Send again generated a new key and could send the same input as another turn,
queue entry or guidance. No duplicate occurred in the observed request log.

The reported approximately 0.5-second delay is consistent with this race. The
identified server request exceeded the deadline by approximately 2.8 seconds;
there is no frontend timing trace proving the exact displayed interval.

## Changes

- [Core index and startup upgrade](E:/LamTools/core/src/lamtools_core/app/core_db.py): partial composite index; idempotent creation on existing tables with startup-phase diagnostics.
- [Acceptance/Resume](E:/LamTools/core/src/lamtools_core/app/live_operations.py): a duplicate start during an active run returns its original indexed receipt. Different input still returns SESSION_BUSY. Resume optionally stores a client-message key and returns an existing receipt without starting another execution.
- [Client acknowledgement](E:/LamTools/core/ui/src/appServer/client.ts): correlated committed `turn/accepted` / `turn/started` events can settle requests before the RPC reply. The original timeout stays unchanged. A timeout triggers one separate five-second reconciliation request using the same key. Local pending state is cleaned up; Core execution is not cancelled.
- [Transport timeout type](E:/LamTools/core/ui/src/transport/types.ts): distinguish missing acknowledgement from a server refusal. Unconfirmed recovery reports an explicitly unknown acceptance outcome.
- [Composer](E:/LamTools/core/ui/src/composables/useCoreLiveComposerController.ts): retain the uncertain submission's key for retry; a late running state does not convert the retry into new guidance or queued input. Explicitly clearing the draft ends that retry identity.
- [Runtime store](E:/LamTools/core/ui/src/appServer/store.ts): retain uncertain Resume identity for explicit retry; a late acceptance retires it so a later Stop/Resume can start a fresh execution of the same logical Turn.

No retry waits for model completion. Normal Agent ownership, steering, sub-agent
status reconciliation, permissions and committed-history Resume behavior remain
intact. No timeout limit was increased.

## Verification

- Full Python: **3,019 passed, 2 skipped**, `python-full.log` / exit 0.
- Core Tasks 1/1A/7 plus indexed lookup/concurrent receipt regressions: **30 passed**, `python-regressions.log`. Same-turn stream/tool interruption, restart, preserved history, no completed-tool replay, and duplicate Resume receipt assertions passed.
- UI: **1,390 passed across 148 files**; typechecks passed. `ui-tests-final-accepted.log` and `ui-typecheck-final-accepted.log`. Includes Task 1B status/card/pane regressions and fake-clock receipt tests: success before reply, acceptance at 60.5 seconds, wrong thread/key rejection, unknown outcome, retained manual retry identity and late Resume followed by a new execution.
- Synthetic 30,000-row database: old missing-ID lookup executes over 100,000 SQLite VM instructions; indexed lookup executes fewer than 2,000. Existing records remain intact and the upgrade query plan uses the composite index.
- Private read-only snapshot benchmark: **2.526 GB**, warm old lookup **49.619 ms**, indexed lookup **0.0382 ms**, index creation **103.2 ms**. Snapshot creation warms filesystem caches; it does not reproduce the original 62-second live/cold/load conditions. The original Tauri log supplies that evidence. No cache eviction or production-database index write was performed.
- Final rebuilt installed backend: start ack **59 ms**, Resume ack **48 ms**, duplicate Resume ack **21 ms** while the mock Agent execution is independent. No duplicate model call or user turn. Installer upgrade from 0.3.18 adds the index; configuration, models/providers, projects and history survive upgrade and rollback. Workflow/plugin regressions and recording configuration also pass. Evidence: `packaged-acceptance-final.log`, exit 0.
- Actual production pipeline: `package-final.log` / exit file. Final setup installed silently in `E:\setuptest\0.3.19`; exact digest is in `installer-hash.json`.

Models are local HTTP mocks; no paid model calls. Private database copies are
under `E:\setuptest`, outside distributable artifacts. Only redacted metadata
and timings are included here.

## Acceptance and remaining risks

The user's Tauri development instance remains running and holds Sunday's
single-instance mutex. Its database reports two active snapshots. Closing it
would interrupt those runs, so permission was requested once and no closure
was assumed. Installer files and isolated production backends are verified;
main Tauri launch, real UI clicks and final user acceptance remain pending.
The required installation skill's main-app launch gate and the full installer
lifecycle launch gate must be completed once that mutex is available.

One-time index creation can take longer on cold/slow/large databases; startup
logs identify that phase. The benchmark does not establish a worst-case boot
time. Severe storage failures or unavailable transport can still leave an
explicitly unknown acceptance result. A timeout never proves cancellation.
Retries must retain their identity; an independently composed submission or an
external/older client using a new key remains a distinct user action. Existing
clients that omit a Resume key keep their previous behavior.

**Code cause fixed; 0.3.19 publication remains blocked until Tauri acceptance.**
Production installer: `E:\LamTools\core\desktop\src-tauri\target\release\bundle\inno\Sunday_0.3.19_x64-setup.exe`.
Evidence copy: `Sunday_0.3.19_x64-setup.exe` beside this report. Ignore files
labelled `before-task-3b` or `superseded` when preparing publication.
Final installer: **95,086,883 bytes**, SHA-256
`82525b74246ab1128fdef0c419057ec0e6cf3c83b193cf61a69b5be937d4a7d7`.
