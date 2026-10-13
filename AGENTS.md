<!-- codex-workflow-id: viettran-edgeAI/codex_workflow -->
<!-- codex-workflow-managed-start -->
# AGENTS.md

## Design Principles

- Keep modules cohesive, interfaces explicit, coupling minimal, and behavior
  testable, replaceable, and reusable.
- Define proportionate acceptance and verification before implementation. Never
  weaken coverage, assertions, or failure visibility to save time or tokens.
- Avoid unnecessary process or safeguards; preserve unrelated user work and use
  verified facts in durable documentation.

## Working State

-`deployment state` : planning or executing a broad, possibly multi-session deployment plan.
- `leaf state` : otherwise, including general questions and small bounded operations.

## Project Documentation

Use the durable project documents under `agent_docs/`:

- `project_overview.md`: goals, architecture, workflow, and major decisions.
- `project_core_tech.md`: concise special technology or architecture notes.
- `project_structure.md`: layout, modules, components, and ownership.
- `project_progress.md`: goal, overall progress, current position, next milestone.
- `project_diary.md`: distilled decisions, discarded approaches, mistakes, and
  reusable lessons.
- `latest_session_work.md`: detailed handoff evidence and continuation point.
- Module-specific documents, when present.

In deployment state, you own `project_diary.md` and record only lasting
decisions, discarded approaches, mistakes, and reusable lessons. Archivist owns
assigned project and public documentation from verified facts, including
overview, structure, core technologies, and closing updates to progress and
latest-session documents. Assign module documents explicitly. Perform a direct
user-requested document edit yourself outside deployment.

Keep raw logs, temporary reasoning, and short-lived checkpoints out of durable
documents; give each fact one canonical home. Never delete a main project
document without warning and a second explicit confirmation.

## Route Selection

Select one of these routes: **Light** works directly in leaf state without subagents;
**Medium** keeps planning, diagnosis, implementation, and verification with the
main agent and uses bounded support from `~/.codex/codex_workflow/medium_route.md`;
**Heavy** delegates bounded production, verification, documentation,
project-context, and Internet research under `~/.codex/codex_workflow/heavy_route.md`.

Follow the user's route selection. Use Light when none is selected; do not infer
Medium or Heavy. Keep the route until the user changes it or the session ends.
Enter deployment state for Medium or Heavy only when the work is substantive.

## Rollout Efficiency

Batch independent reads, searches, metadata checks, and other known-input
operations. Keep dependencies and overlapping mutations sequential. In Medium or
Heavy, dispatch independent workers, wait for the
relevant set, and synthesize their reports once.

Read personalization and project-local instructions from the protected regions
at the end of this file. Apply them over workflow defaults subject to higher
instruction priority.

## Required Documentation Read

On the first `deployment state` entry under either route, before planning,
modifying files, or dispatching a worker, directly read the complete current
`agent_docs/` framework exactly once: overview, core technology, structure,
progress, diary, latest session work.

This is one shared session-level read across both routes; reuse it for later
deployments and route changes. Assign Companion a bounded delta or conflict
check when documentation changes or freshness matters. Missing or unreadable
required documents leave deployment entry incomplete; report the intake blocker.

## Platform Paths

Interpret `/` as a platform-neutral separator and translate paths for the
current operating system and shell.
<!-- codex-workflow-managed-end -->

<!-- codex-workflow-project-personalization-start -->
## User Preferences

- Answer only what is asked. Keep communication concise, direct, and efficient.
- For exploration tasks, use six Luna sub-agents with high or maximum reasoning
  effort. Respect platform concurrency limits by scheduling them in batches.
- Do not use Computer Use unless explicitly requested. Limit verification to
  code-based methods. Record any unperformed installer or visual acceptance
  gates as pending rather than claiming they passed.
<!-- codex-workflow-project-personalization-end -->

<!-- codex-workflow-project-local-instructions-start -->
# LamTools Project Instructions

These instructions define project behavior and override workflow defaults where
applicable. Follow higher-priority instructions and the user's explicit request.
Paths in this section are repository-relative unless stated otherwise.

## 1. Communication and Decisions

- Answer only what the user asked. Keep replies simple, direct, and efficient.
- Describe observable behavior, outcomes, and business decisions with their
  consequences. Include implementation details only when the user explicitly
  requests code inspection, review, or diagnostic detail.
- Own implementation choices and technical tradeoffs. Do not ask the user to
  choose function names, code organization, or equivalent technical details.
- Reach agreement with the user on the plan before implementation. An explicit
  request or previously approved plan supplies agreement for that scope; do not
  repeatedly ask for the same approval.
- If requirements, intended behavior, scope, or a business decision remain
  uncertain, clarify them before implementing the affected work.

## 2. Product and Change Boundaries

LamTools is a general-purpose, all-in-one AI application. Workflows support many
AI scenarios. AI animated comics are one application scenario, not the product's
positioning.

| Area | Role | Change policy |
| --- | --- | --- |
| `core/` | Standalone agent foundation; the only active product | Default implementation scope |
| `website/` | Official website; reuses the real Core UI | Change for website work or required release synchronization |
| `archive/members/` | Archived Writer, Sage, and Imager products | Retain for historical traceability; do not maintain |

Keep product development in `core/`. Explicitly requested repository instruction
edits and required website release updates are within their respective scope.
Every GUI capability must have a corresponding CLI capability.

## 3. Verification Policy

- Define acceptance criteria before implementation and use checks appropriate to
  the change. Preserve coverage, assertions, and failure visibility.
- Default to code-level verification. Do not use computer-use tools, browsers,
  or GUI inspection unless the user explicitly requests or authorizes them.
- Tauri (`core/desktop`) is the only environment for visual UI acceptance.
  The user confirms appearance in the Tauri window. Do not replace this with
  browser previews or a dev.ps1-based observation setup.
- Required installer launch/process checks remain release acceptance gates.
  They do not authorize additional visual inspection.
- Report only completed verification as passed. Distinguish code checks from
  installer checks, public-deployment checks, and user visual confirmation.

### Required contextual guidance

- For Core UI components, CSS, tokens, or design decisions, use the project skill
  `.agents/skills/lam-design-spec`. Existing interface decisions follow that
  design language; use Impeccable for new designs as directed by the skill.
- Before work related to Core UI streaming performance, read
  `docs/core-ui-streaming-perf.md`. It is the sole authoritative record for
  investigation, implementation, and continuation across sessions.
- After every Core Windows Inno Setup build or setup version update, use
  `.agents/skills/lamtools-setup-install` as specified in Section 8.

## 4. Development Environment

Use UTF-8 whenever PowerShell reads, writes, or passes Chinese text.

| Tool | Location / requirement |
| --- | --- |
| Android SDK | `E:\Environment\AndroidSDK`; system `ANDROID_HOME` is configured |
| ADB | `E:\Environment\AndroidSDK\platform-tools\adb.exe` |
| Android Gradle JDK | JDK 21 at `C:\Users\Administrator\AppData\Roaming\.minecraft\runtime\java-runtime-delta` |

Before an Android Gradle build, set `JAVA_HOME` in the current PowerShell process
to the JDK 21 directory. Do not use the existing Java 8 or JDK 17 installations.

### Tauri lifecycle

- Tauri dev is independent of `scripts/dev.ps1` and `scripts/restart.ps1`.
  Never use those scripts to manage Tauri: terminating port 5173 kills its Vite
  server and breaks the window's loading chain.
- The desktop Vite server runs from `core/desktop`; the Tauri devUrl is fixed
  at `127.0.0.1:5173`. Before starting it, ensure that another Vite instance is
  not occupying 5173. A fallback to 5174 leaves the window loading the wrong
  server on 5173.
- Rust chooses an available backend port and launches
  `py -3.14 -m lamtools_core.cli serve --port <port>` with cwd `core/`.
  **Never add `--reload`.** On Windows, uvicorn's reloader can leave child
  processes that escape `stop_backend` and retain database locks.
- Rust supplies `__LAMTOOLS_API_BASE__` through `get_api_base`. Tauri does not
  use the dev.ps1 backend port 5172 or its proxy.
- Backend changes require a full application exit and restart with
  `npm run tauri dev` from `core/desktop`.
- UI changes use HMR: the desktop `src/main.ts` imports
  `../../ui/src/app/LamToolsApp.vue`. Packaged `tauri build` output has no HMR.

### Separate development scripts

These commands describe the separate development system. They are not Tauri
restart commands or UI acceptance tools.

```powershell
.\scripts\dev.ps1 core  # Core backend/frontend on 5172 / 5173
.\scripts\dev.ps1 all   # Same Core-only startup
.\scripts\restart.ps1  # Restart only the dev.ps1 system
```

## 5. Persistent Data and Configuration

Core conversations and runtime state use `data/core.db`. Models, providers, and
settings use JSONC files, not a configuration database.

| Configuration | Location under `.lam/core/config/` |
| --- | --- |
| Models | `models/<model_id>.jsonc` |
| Providers | `providers/<id>.jsonc` |
| Settings | `settings.jsonc` |
| Model retries | `model_retry.jsonc` |

`LAMTOOLS_CORE_CONFIG_ROOT` can override the configuration root. Do not
reintroduce the `llm_providers`, `llm_models`, or `app_settings` tables or the
`LAMTOOLS_LLM_CONFIG_DB` environment variable.

### Retry configuration and provider credentials

- Read attempt count, per-attempt timeout, streaming idle timeout,
  empty-response retries, `retry_delays_seconds`, and jitter from
  `model_retry.jsonc`; use built-in defaults for missing values.
- Assembly points are `default_agent.create_kernel`, `cli.py`, and
  `tool/sub_agent_runner.py`. Explicit arguments take precedence over files.
- Provider `api_key` values are plaintext in `providers/*.jsonc`. RPC list
  responses mask them as `********`. Masked or empty write-back values must
  preserve the existing key.

### Default seeding

`ensure_default_config_files` in `config/defaults.py` is idempotent and must not
overwrite existing configuration.

- Copy loadtools/access_tools/hooks/mcp/README from `core/config/resources/`.
- Generate AGENTS.md/load_context/model_retry/subagent from built-in defaults.
- Create the global memory library directory `memory/`.
- Put new resource-backed defaults in `core/config/resources/` and register
  them in the seeding list.
- **Never bundle `.lam` in installers.** Earlier NSIS overwrite behavior erased
  user configuration; that packaging behavior was removed.

## 6. Runtime Behavior Contracts

Implementation references below are relative to `core/src/lamtools_core/` for
Python modules and `core/ui/src/` for frontend modules.

### Memory library

Implementation: `mem/library.py` and `tool/memory_tools.py`.

- Project scope: `<work_root>/.lam/memory/`. Global scope:
  `.lam/core/config/memory/`.
- Directory structure is the index. Generate each scope's `INDEX.md`
  automatically and inject it into every conversation at priorities 15 and 20
  for project and global memory respectively.
- Models access memory through the built-in `memory` tool with `auto_allow`.
- Manual access is Library → Memory, with projects listed first for project
  memory. Do not restore memory sections in settings or project settings.
- `INDEX.md` is reserved: no entry point may write, rename, or delete it.
- Do not restore legacy dreaming, the `core_memories` table, or
  `memory.md` / `MEMORY.md` injection; compatibility was removed.

Access: `memory.*` RPCs and
`core memory tree/read/write/append/edit/delete/rename/mkdir`.
`memory.reveal` / `core memory reveal` opens the corresponding system folder;
`--global` selects global memory.

### Outbound network routing

Setting: `core.network` in `settings.jsonc`; implementation: `config/network.py`.
User entry: Settings → General.

- `proxy`, `no_proxy`, and `ca_cert` govern application outbound traffic:
  models including image generation, MCP, command tools, Workflow command
  nodes, hooks, observers, fetching, search engines, plugin installation, and
  update checks/downloads.
- Do not derive routing from system environment variables. Empty settings mean
  direct connections; clear inherited `*_PROXY` variables in subprocesses.
- Localhost, 127.0.0.1, ::1, and `[::1]` always connect directly.
  `no_proxy` supports `.corp.com`, `*.corp.com`, `host`, and `*`.
- A DuckDuckGo engine's explicit `proxy_port` overrides the global proxy.
- Use `ca_cert` as the httpx trust root and inject it into subprocesses through
  `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`, `CURL_CA_BUNDLE`, and
  `NODE_EXTRA_CA_CERTS`. Convert WSL paths to `/mnt/<drive>/...`.
- WebView2 follows the system proxy; it is a rendering-layer exception.
- WSL exception: unconfigured `wsl.exe` retains its inherited environment with
  `WSLENV` forwarding. Configured routing variables enter WSL through `WSLENV`.

CLI: `core network get` / `core network set --proxy/--no-proxy/--ca-cert`.

### Keep awake

Setting: `core.keepAwake`; implementation: `runtime/power.py`.
User entry: Settings → General.

- Prevent idle system sleep during long tasks when enabled.
- On Windows, call
  `SetThreadExecutionState(ES_CONTINUOUS|ES_SYSTEM_REQUIRED)` **on the event-loop
  thread**; the request is tied to that thread's lifetime.
- Apply once at backend startup and immediately after every settings write.
- On other platforms, store the preference but mark it unsupported and hide
  the switch; it has no effect.

CLI: `core keep-awake get` / `core keep-awake set on|off`.

### Automatic continuation for questions

Setting: `core.askAutoContinue`; validation: `config/automation.py`;
timer: `composables/useCoreAskAutoContinue.ts`.
User entry: Settings → General.

- Handle only pending model question cards from the `question` tool.
- After five minutes without an answer, submit `other_guidance` using the
  existing no-answer wording: the user skipped answering, five minutes elapsed
  without a response, and no user answer was collected. Continue the turn.
  Preserve the existing product message; this English guide does not authorize
  translating application copy.
- **Never automatically handle permission approval cards.** A timeout is not
  consent; only a human may approve.
- Read the preference once when a pending question appears. Restart the timer
  if submission fails. Cancel it immediately after a manual answer.

CLI: `core ask-auto-continue get` / `core ask-auto-continue set on|off`.

### Automatic resumption after memory interruption

Setting: `core.memoryResume`; implementations: `runtime/memory_guard.py` and
`app/memory_resume_supervisor.py`. User entry: Settings → General.

- Start and stop the watchdog with the backend.
- Immediately explain a low-memory interruption and state the recovery
  threshold: Sunday will continue when available memory exceeds X GB.
- Available memory means **physical memory + page file**. On Windows use
  available commit capacity from `GlobalMemoryStatusEx`, not free physical
  memory alone. The configurable default threshold is 4 GB.
- Persist `failure_code=host_memory_exhausted` and the explanation in runtime
  state. Retain the terminal item in the live frontend status path
  (`appServer/store.ts`); do not leave an unexplained "Creating file..." state.
- After recovery, start a new turn in the **same conversation** using
  `memory_resume_continuation_prompt`, with at most three consecutive automatic
  resumptions. Cancel automatic resumption if the user sends a new message.
- Persist terminal events separately from loading the full thread snapshot.
  Snapshot failure must not roll back an already committed terminal event.
  If batch persistence fails, fall back to writing the terminal event alone.
- `reconcile_terminal_turns` runs at startup and every 15 seconds to close
  turns with recorded terminal status but a running snapshot. Use recorded
  terminal status, **never elapsed inactivity**, as the criterion. Normal
  long-running tools and dead turns can look identical externally.
- Do not show a false running state while reporting that resumption is
  available. Hide the setting on unsupported platforms (outside Windows/Linux).

CLI: `core memory-resume get` /
`core memory-resume set on|off [--threshold-gb N]`.

## 7. Website and Real-UI Preview

Stack: Vue 3.5, Vite 8, TypeScript 6, anime.js v4, and lucide-vue-next.
Website implementation rules apply when website work is in scope; they do not
authorize browser-based UI verification.

### Build and development

- Install `core/ui` dependencies first: `cd core/ui` then `npm ci`.
- From `website/`, run `npm run build`. Output is `website/dist/`.
  The script uses Vite without vue-tsc because cross-project Core UI type
  checking produces excessive noise.
- The separate website dev command is `npm run dev`, using port 5199.
  Do not interfere with ports 5172 or 5173.

### Showcase contract

The showcase mounts the actual `core/ui` `LamToolsApp`, including Workflow UI,
through `preview.html` and `src/preview-main.ts`. Read the preview implementation
before changing showcase behavior. Do not hand-build an imitation.

- Keep one persistent iframe in `Showcase.vue`; synchronize themes with
  postMessage. Changing its URL can scroll the host page.
- Reuse components and CSS from `core/ui/src`. Mock data must follow the real
  `CoreMessage/MessagePart` shape.
- Alias Vue to the website's own singleton. A second Vue instance can produce
  a blank screen.
- ChatThread `v-memo` depends on message identity. Use a new message object for
  every update (`commitMsg`); mutating parts in place does not rerender.
- Use `model_text` for answer parts and `msg.content` for final full text.
- Put DOM overrides in global styles. Scoped selectors cannot reach nodes
  rendered by WorkspaceShell; for example, `.core-preview-document .thread`
  in `preview.html` controls bottom alignment.
- Alias dependencies such as `@vue-flow/*` to `core/ui/node_modules`.

### Release references and public copies

- Keep `VITE_SUNDAY_VERSION` and `VITE_SUNDAY_MOBILE_VERSION` defaults in
  `website/src/components/Download.vue` synchronized with releases. Also update
  `.env.example` and preview versions in `src/mock/runtime.ts`.
- Do not use legacy TODO copy placeholders. Download links use the site's
  `downloads/` directory, including `Sunday-latest-x64-setup.exe` and
  versioned installers.
- Publishing `/var/www/lamtools/site` (`47.114.43.99.nip.io`) does not update
  all copies served by `ainarit.com`. Synchronize both
  `/var/www/ainarit/sunday.html` (hard-coded versions and Linux links) and
  `/var/www/ainarit-preview` (the embedded `/preview/` UI).
- After publication, run `scripts/sync-public-site.sh`, installed on the
  server under `/usr/local/bin/`. It reads the two published manifests,
  updates version labels, rebuilds `/preview/` from the published site package,
  and verifies the public site. `--check` is read-only and exits 1 on drift.
- Historical evidence:
  `core/desktop/artifacts/release-0.3.15/public-site-sync.md`. Missing this step
  previously left version 0.3.10 visible and both Linux links returning 404.

## 8. Desktop Updates and Release Acceptance

### Update behavior

Implementation: `core/src/lamtools_core/update/checker.py`.
Entry points: `update.check` RPC / `lamtools_core.cli update check` CLI.

1. Read `downloads/desktop-update.json` from the official website, falling back
   to GitHub `releases/latest`. Compare with `lamtools_core.__version__`.
2. Show a softly rounded update icon above the account in the left sidebar.
   Clicking it moves and enlarges it into a centered card showing current and
   latest versions, an optional summary, download percentage, and Cancel/Update.
3. Download with `update.download`, verifying the digest as chunks arrive.
   Support cancellation through `update.cancel`.
4. After successful verification, invoke `update.install` with `/SILENT` and
   `/AUTORESTART=1`.
5. On Windows, exit the application before launching the installer. Start it
   outside the backend job object using `JOB_OBJECT_LIMIT_BREAKAWAY_OK`.
   The installer must reopen the application after installation.
6. On Linux/macOS, open the installer folder without exiting (`quit: false`).

Do not introduce an updater plugin or signing. Follow
`core/desktop/PACKAGING.md`.

### Version synchronization

Use `scripts/bump-version.ps1` to synchronize all five desktop version sources:

- `core/desktop/src-tauri/tauri.conf.json`
- `core/desktop/src-tauri/Cargo.toml`
- `core/desktop/package.json`
- `core/pyproject.toml`
- `core/src/lamtools_core/__init__.py`

Tagging `vX.Y.Z` triggers packaging through `release.yml`. Apply the website
version synchronization in Section 7 as part of publication.

### Required acceptance gates

- After every build of `core/desktop/installer/Sunday.iss` or setup version
  update, apply `.agents/skills/lamtools-setup-install`: install the matching
  version into `E:\setuptest\<version>`, launch it, and verify the application
  and backend processes. Development-mode startup is not a substitute.
- Releases must run `scripts/verify-update-install.ps1` to verify public
  download, matching digest, silent installation, and automatic application
  restart. CI verifies the same contract with
  `scripts/verify-desktop-lifecycle.ps1`.
- Complete the public-site synchronization and checks from Section 7.

## 9. Mobile Test Releases

**0.1.x is the mobile testing channel.** After each completed mobile fix,
increment the patch version by one, build, and upload for physical-device
verification. This cadence is already authorized; do not ask again each time.

Synchronize all eight version sources:

| Source | Required value |
| --- | --- |
| `core/mobile/package.json` | Package version |
| `core/mobile/src-tauri/tauri.conf.json` | Application version |
| `core/mobile/src-tauri/Cargo.toml` | Crate version |
| `core/mobile/src-tauri/Cargo.lock` | `sunday-mobile` version |
| `core/mobile/src-tauri/gen/android/app/build.gradle.kts` | Default versionCode/versionName |
| `core/mobile/src-tauri/gen/android/app/tauri.properties` | Android version properties |
| `core/mobile/update-manifest.json` | Update version |
| `website/src/components/Download.vue` | `VITE_SUNDAY_MOBILE_VERSION` default |

Android versionCode = `major * 1000000 + minor * 1000 + patch`
(for example, 0.1.9 → 1009). `scripts/package-mobile.ps1` validates it.

Keep release audit evidence in `core/mobile/artifacts/release-0NN/` and execute:

1. Build the package.
2. Independently verify the APK.
3. Upload the APK and website.
4. Verify public availability and synchronize the public-site copies.

Redirect `package-mobile.ps1` output to a file and poll artifacts. The Gradle
daemon can keep stdout open, so piped reads may never receive EOF and appear
stuck. Use the JDK 21 environment from Section 4.

## 10. Streaming Performance Baseline

Read `docs/core-ui-streaming-perf.md` before related work in every session.
The following work is recorded as complete; consult that document for evidence
and continuation rather than treating these items as new implementation tasks:

- Delta coalescing, scroll coalescing, goal throttling, and watcher pruning.
- MessageView componentization, incremental projection updates, and incremental
  segmented Markdown rendering (2026-08-07).
- Element-level `v-for` + `v-memo` isolation in five part loops (2026-08-07).
<!-- codex-workflow-project-local-instructions-end -->
