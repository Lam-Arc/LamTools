# Windows 0.3.19 release-candidate acceptance

> Historical Task 3 evidence. The production installer has since been rebuilt
> for Tasks 1B and 3B; use task-3b/REPORT.md and its installer hash for the current
> candidate. Publication remains blocked pending Tauri acceptance.

Status: **local automated acceptance passed** (`acceptance-result.txt`: passed;
`python-tests-accepted.exit.txt`: 0). **NO-GO for stable publication until
required Tauri user acceptance is confirmed.** No remaining confirmed code or
installer blocker was found within this scope.

Proposed version: **0.3.19** (Windows stable patch). No commit, tag, publication,
production deployment or public artifact replacement has occurred.

## Release blockers fixed

1. Restored legacy conversation rows could retain revision 0 after a previous
   repair marker was written. That made optimistic writes conflict indefinitely.
   Startup now probes snapshot signatures even when marked, and scans events only
   when repair is necessary. Healthy startup never reads the event log.
   [Implementation](E:/LamTools/core/src/lamtools_core/app/core_db.py:2193).
2. Model setup could return an operation error before a terminal event existed,
   leaving an accepted turn permanently running. The live host now persists a
   failed terminal and its explanation, retaining already recorded terminal
   reasons. The conversation accepts a subsequent turn.
   [Implementation](E:/LamTools/core/src/lamtools_core/app/live_operations.py:3650).
3. The externally installed optional Workflow plugin required the namespace of
   a package deliberately excluded from the installer. Its bootstrap supplies
   that namespace from the installed plugin, retaining existing handler names.
   No Workflow files/modules were added to the installer.
   [Bootstrap](E:/LamTools/core/src/lamtools_core/plugins/bundled/workflow/bootstrap.py:17).
4. Windows PowerShell 5 misdecoded lifecycle acceptance comments and failed to
   parse the script. Added UTF-8 BOM; the lock-holder helper now runs hidden.
   Windows PowerShell parser and full lifecycle verification cover this change.

Stale tests were corrected to recognize turn metadata and forensic retry
identity, actual settings/composer contracts, schema PRAGMA queries rather than
event-data scans, and the release skill's explicit plugin list. The restart
fixture now models an exited owner rather than a still-running test process.
No coverage or failure visibility was removed.

## Evidence

| Gate | Evidence / boundary |
| --- | --- |
| Python integration | `python-tests-accepted.log`: 3,017 passed, 2 skipped; full suite after final host fix |
| Vue/TypeScript | `ui-tests-final.log`: 147 files / 1,372 passed; `ui-typecheck.exit.txt`: 0 |
| Desktop Rust | `rust-tests.log`: 70 passed |
| Shared Rust runtime | `runtime-rust-tests.log`: 165 passed; verification only, no migration |
| Workflow and plugin regressions | `workflow-plugin-final.log`: 460 passed; optional bootstrap included |
| Setup failure, Resume and memory regressions | `runtime-start-failure-tests.log`: 107 passed |
| Production pipeline | `package-accepted.log`: Vite, sole PyInstaller spec, packaged REST/WS/Study smoke, Tauri release, Inno Setup |
| Required installed launch | `installed-startup-accepted.log`: isolated E:\\setuptest\\0.3.19, shell and bundled backend process paths/PIDs |
| Windows installer lifecycle | `installer-lifecycle-accepted.log`: fresh install; system close; no orphan backend; live update; payload replacement; locked-file refusal; subsequent boot; silent automatic restart; uninstall preserves markers |
| Packaged functional and upgrade | `packaged-upgrade-accepted-final.log`: actual installed sidecars, local HTTP mock, provider/model read-back, same-turn Stop/Resume, external plugin disable/enable, Workflow save/reconnect |
| Backup and configuration | `supplement-acceptance-accepted-final.log`: restored backup opens under prior stable; matching table schema; recording off; model setup failure and retry |
| Resource inventory | `artifact-inventory.json`: exact files, sizes/hashes and byte-matched skills/default resources/adapters |
| Published channel | `public-update-install.log`: existing public 0.3.18 downloads with matching size/digest, silent install and automatic healthy restart |
| Live GitHub fallback | `github-live-fallback.json`: forced unavailable local manifest falls back to actual GitHub latest 0.3.17 |

Tests use isolated data/configuration and local mocked models. No paid model
requests were made. Older failure/build logs remain as historical evidence;
use the `accepted` logs for final installer/backend acceptance.

## Upgrade and rollback

The preserved 0.3.18 installer matches the public SHA-256
`b8681e66243634654b98b70274aee3cee7e6fd69241ddf1f99219cec6334a5f7`.
Acceptance creates a real project registry and conversation messages using its
installed backend, then upgrades to 0.3.19 in an isolated directory. Settings,
provider/model files and project content are compared by digest; history and
registry are compared by API responses. Candidate execution writes new state,
then the old installer/backend reopens the same data. Backup restoration is
verified independently. These fixtures prove this upgrade/rollback path, not
every possible historical database or third-party plugin combination. Before a
real rollback, exit Sunday and retain a backup of `.lam` and project directories.
Selecting a model intentionally updates remembered scene choices; rollback
compares settings against that latest state and verifies the original user
network/keep-awake values survived, rather than treating legitimate new choices
as corruption.

## Artifacts and distribution

Production installer:
`E:\\LamTools\\core\\desktop\\src-tauri\\target\\release\\bundle\\inno\\Sunday_0.3.19_x64-setup.exe`.
Reviewable evidence copy: `Sunday_0.3.19_x64-setup.exe` beside this report.
Exact inventory is `artifact-inventory.json`. Ignore installers named
`superseded` when preparing publication.
Final installer: **95,078,359 bytes**, SHA-256
`5a000e5d5ebc71ff9057b76414a96998ceedb93e995cdd6b60794e766cb34185`.

`workflow-1.0.0-optional-rc.zip` is a separate optional source plugin candidate,
not an embedded desktop component. Its bootstrap fix requires replacing older
external Workflow source copies with this updated optional package; the Core
installer does not rewrite external plugin directories. Built-in plugins are git, imagegen, plan,
study and websearch. Workflow and emotion-ball-pet remain excluded. The Python
runtime, standard library, native extensions, frontend and all 42 skill files,
5 default resources, 3 command resources and 25 adapter files are present.
The installer contains the WebView2 bootstrapper; the test host already has
WebView2. Provisioning it on a clean/offline host remains untested.

All five desktop version sources and desktop npm/Cargo lock metadata target
0.3.19. `desktop-update.proposed.json` is private proposed metadata, not a
published manifest. The official site advertises Windows 0.3.18; GitHub fallback
advertises 0.3.17. Fallback works but is one stable release behind the official
site. Publication should synchronize the approved installer/digest, GitHub and
website desktop labels, preserving existing independent Linux/mobile metadata.
Website source labels still reflect published 0.3.18; updating public copies and
running public-site sync are deferred until publication is approved.

## Remaining acceptance limits

- Tauri launch and backend connectivity are tested by processes, HTTP and WS.
  Actual frontend IPC boot, settings navigation/dialog appearance, clicking
  Stop/Resume and plugin panels have no visual Tauri acceptance. Vue component
  tests verify draft protection; they are not user confirmation of appearance.
  Per AGENTS.md, required user Tauri confirmation remains pending.
- Authenticated remote gateway compatibility has source/Rust test evidence;
  no live production relay or remote device session was exercised or deployed.
- The candidate's public download and automatic-update path cannot be checked
  before approved publication. Current public 0.3.18 and local candidate paths
  are tested separately.
- Core local mode trusts programs on the host; unauthenticated local forwarding
  can extend that trust. Explicit LAN mode requires a bearer token; use TLS/VPN
  to avoid plaintext credential exposure. No per-user authorization was added.
- Raw forensic files contain unredacted model payloads. Recording stays disabled
  by default; intentional Stop produces an interrupted capture, not a complete
  one. Production provider behavior was not tested with paid API calls.
- Six-digit WAN pairing is deprecated/unsupported, excluded from release gates.
  Mobile and runtime migration were not changed.

## Recommendation

**GO for the local 0.3.19 candidate; NO-GO for stable publication pending required
Tauri user acceptance.** [AGENTS.md](E:/LamTools/AGENTS.md:139) states: “The user
confirms appearance in the Tauri window.” No visual acceptance was performed,
as requested. Production relay/device behavior and post-publication candidate
update/public-site checks remain unverified. There is no authorization to
publish. Release notes are in `RELEASE-NOTES.md`.
