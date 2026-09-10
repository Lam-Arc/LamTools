# Latest Session Work

## Goal

Finish and verify the LamTools single-UI + multi-Transport mobile refactor,
with no remaining demo/mobile business-UI entry point.

## Implemented

- Promoted `core/ui/src/app/LamToolsApp.vue` to the shared product root and
  removed `core/ui/src/demo/` and `tsconfig.demo.json`.
- Added the connection-neutral Workbench runtime and Transport contract. All
  shared UI REST/RPC access goes through the injected transport.
- Switched Tauri desktop to DirectTransport and mobile to one stable
  RemoteTransport. Mobile `App.vue` retains only pairing, native lifecycle,
  trusted-device, and connection orchestration before mounting the shared app.
- Added Noise-secured LAN/Relay tunnel handling, pairing/device identity,
  split secret storage, reconnect/route selection, sequence replay checks,
  protocol negotiation, and multi-client Core event/response routing.
- Added transport, Workbench, tunnel, pairing, gateway, and multi-client
  synchronization coverage. Corrected the context-compaction planner guard
  and no-LLM short-history behavior.
- Applied LamTools design tokens and verified the design audit is clean.

## Verification

- `cd E:\LamTools\core; py -3.14 -m pytest -q`: `1677 passed, 2 skipped`.
- `cd E:\LamTools\core\ui; npm run typecheck`: pass.
- `cd E:\LamTools\core\ui; npm run test:contract`: 67 files / 471 tests pass.
- UI build, mobile typecheck/tests/build/Capacitor sync, desktop Rust tests,
  check/format, Relay tests/format, Android Debug APK build, and website build:
  pass.
- Docker Compose static configuration passes with a supplied domain; the real
  image build is pending Docker Hub network access.
- `node .agents/skills/lam-design-spec/scripts/audit.mjs`: 69 files, 0
  deviations.
- `git diff --check`: pass (Git only reports normal LF-to-CRLF warnings).

## Working-tree Notes

The repository remains uncommitted so existing user changes are preserved.
The generated context-compaction fixture directories and `playwright-test/`
were left untouched; they are not part of the refactor implementation.

## Continuation

Use Tauri as the UI observation surface. Any future business capability should
be added once in shared UI/Workbench. Any future connection path should be
implemented behind RemoteTransport/ConnectionManager without adding a second
mobile UI.

## Provider cancellation and retry visibility

- Codex666 AI connectivity is valid at the models endpoint, but real completion
  is slow and streaming is unstable (including upstream 502 responses).
- Model retry projection now retains the error/backoff details, and all process
  rendering paths show them while retrying.
- Live Stop now cancels provider I/O before SQLite persistence and keeps the run
  claim until terminal state is durable. A real provider run measured 102 ms for
  the server-side cancel RPC and about 240 ms until the cancelled terminal event.
- Verification: 238 targeted Python tests, 78 targeted UI tests, UI typecheck,
  design-token audit, and `git diff --check` pass.
- Follow-up raw capture showed standard `data: ` framing. A minimal request
  completed in about 9 seconds on one run and 40 seconds on another; an actual
  CLI-assembled 33,147-byte/24-tool request completed in about 12.7 seconds.
  This narrows the incident to high provider latency variance and intermittent
  upstream errors rather than a stable request incompatibility. The client now
  also accepts valid `data:value` SSE framing; its focused profile suite passes
  40/40 tests.

## Office retest process-audit handoff

- Task/deployment: `office_retest_process_audit`; state: `complete`.
- Outcome: process review of the Microsoft FY25 Q4 and customer-handover retests is complete. Scores are 5.8/10 directness and planning, 6.4/10 failure/problem control, 5.5/10 speed/efficiency, 8.9/10 instruction adherence, overall 6.7/10.
- Material documentation: `core/docs/office-skills-internal-evaluation-2026-09-10.md` now records event-derived elapsed times (finance 641.384 s; handover 241.735 s, baseline 140.720 s), timing breakdowns, failure evidence, Skill-routing gaps, cache-prefix evidence, and visual limitations.
- Verification: read-only review of `summary.json` and `events-redacted.json`; event start/done timestamps confirm the recorded wall times. No implementation tests were rerun for this documentation-only closure.
- Pending work/blockers: newcomer-onboarding retest was not run; finance footer/source-note and page-number overlap remains a visual acceptance risk despite a zero-overlap geometry report; handover still lacks the `office-email` route.
- Evidence: `.tmp/office-skills-evaluation/2026-09-10-retest/02-microsoft-fy25q4/run/` and `/07-customer-handover/run/` (`summary.json`, `events-redacted.json`). Exact next entry point: resolve the finance footer reserve-area/geometry check and complete the missing Skill routes before another Office retest.
