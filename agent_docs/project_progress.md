# Project Progress

## Goal

Deliver the Core single-UI, multi-Transport architecture: one shared
Workbench and application for desktop and mobile, with connection-specific
code isolated behind DirectTransport, RemoteTransport, the desktop Gateway,
and the opaque Relay tunnel.

## Overall Progress

The refactor is implemented. Core UI no longer uses the former demo entry;
desktop and mobile both mount `core/ui/src/app/LamToolsApp.vue`. The Workbench
depends on `LamToolsTransport`, desktop uses DirectTransport, and mobile keeps
one stable RemoteTransport while ConnectionManager selects the secure LAN or
Relay route. Pairing, device identity, secure-storage separation, Noise
authentication, replay protection, protocol versioning, reconnect handling,
and multi-client response ownership are in place.
The latest Workflow UI closure adds multi-workflow tabs, a responsive
schema-driven node catalog, Chinese presentation labels, and semantic Lucide
icons while leaving canonical node IDs and execution contracts unchanged.
The current Workflow observability closure adds a persistent run panel, live
node/edge execution states, safe input/output/timing/retry/cache/error and
audit projections, an explicit HumanTask approval path, and usable Schema
defaults/JSON parameter editing. It also hardens public run/queue projections
against credentials, tokens, and hidden reasoning content.
The follow-up canvas-runtime closure moves that observability into a
graph-native sidecar: the default run panel is removed, graph nodes stay
opaque with restrained active-state treatment, and the dock accumulates public
delta/output/log/tool/artifact/error/approval information without turning the
canvas into a text dashboard.

## Current Position

- Shared UI/runtime: `core/ui/src/app/`, `core/ui/src/workbench/`, and
  `core/ui/src/transport/`.
- Mobile-only code is limited to pairing, native capabilities, lifecycle,
  discovery, secure storage, and connection/wire code; its APP screen mounts
  the shared `LamToolsApp`.
- The Tauri Gateway keeps Core loopback-only and bridges authenticated,
  encrypted tunnel frames; Relay forwards opaque tunnel traffic without
  parsing Core business messages.
- Context-compaction trigger behavior was corrected so precise planning is not
  skipped by a fast estimate and short no-LLM histories return `not_needed`.
- Context compaction now defaults to retaining `0` Steps: all non-prefix
  history is summarized, then the newest 20 user instructions are appended
  verbatim as a numbered recent-user section. The setting is available through
  the CLI, settings RPC, and CoreSettings UI.
- The follow-up compaction fixes preserve same-run summary visibility in memory
  while filtering durable rows, use valid high-water/compacted sequences for a
  manual zero-tail, roll prior structured recent-user sections forward, and
  keep automatic/manual overrides aligned across edge cases.
- Workflow UI is at the user-acceptance handoff: open workflow tabs, dirty
  switch protection, responsive sidebar/popover catalog search and filters,
  localized presentation copy, and semantic icon affordances are implemented;
  visual acceptance remains user-owned in Tauri. Runtime observability and
  approval UX are implemented, but the Agent adapter currently exposes only
  tool names/counts rather than per-call tool status.
- Sunday’s control-surface contrast and icon-coverage closure is complete at
  the code and runtime-readiness level. The clarified “background” is the
  backdrop workbench / background-board / sidebar area; chat main and
  composer remain separate surfaces with their own flat fills and shared
  boundary color. Visual acceptance remains user-owned in Tauri.

## Verification

- Core: `1677 passed, 2 skipped`.
- Shared UI: 67 test files / 471 tests; typecheck and build pass.
- Mobile: 9 test files / 33 tests; typecheck, build, and Capacitor sync pass.
- Desktop Rust: 49 tests, `cargo check`, and format check pass.
- Relay Rust: 10 tests and format check pass.
- Android Debug APK builds successfully from the synchronized Capacitor project.
- Docker Compose configuration validates with an example domain; the image
  build still depends on Docker Hub network access in the local environment.
- Website build passes.
- LamTools design audit: 69 files scanned, 0 deviations.
- `git diff --check` passes.
- Latest Workflow UI closure: full `npm run typecheck` passed; the five
  Workflow UI test files passed 49 tests; backend
  `core/tests/test_workflow_node_contract.py` passed 7 tests; the LamTools
  design audit covered 83 files with 0 deviations; and the independent Tester
  gave the final code review a pass. These checks do not constitute a visual
  Tauri acceptance pass.
- Latest Workflow observability closure (`workflow_observability_20260914`):
  Workflow backend coverage passed 214 tests / 1693 deselected; focused
  Workflow UI coverage passed 56 tests; UI typecheck, `npm run build:app`,
  LamTools design audit (84 files / 0 deviations), and `git diff --check`
  passed. Independent Tester review passed (backend 45 / UI 45).
- Real run evidence for workflow `工作流测试1` (`77638d5256364cc99f6887fa00e17d08`):
  revision 148 with 9 current nodes and 9 links paused at HumanTask approval,
  then completed after approval. The Agent returned 23 sources and the model
  produced 17,970 characters. This confirms a real end-to-end run, not visual
  acceptance of the Tauri surface.
- Latest graph-native Workflow runtime sidecar closure
  (`workflow_canvas_runtime_sidecar_20260914`): full UI coverage passed 83
  files / 620 tests; UI typecheck and `npm run build:app` passed (only existing
  chunk/dynamic-import warnings); LamTools design audit passed 84 files / 0
  deviations; `git diff --check` exited 0 with line-ending warnings; and the
  independent Tester passed 4 files / 45 tests plus typecheck and diff check.
- This closure did not perform Tauri visual acceptance or a real Workflow run.
  The known `工作流测试1` data is currently damaged at revision 155 with 8
  nodes and 0 links; it was deliberately neither rerun nor restored here.

## Workflow dynamic-module loading repair (2026-09-14)

- Root cause: during HMR, a stale `index.ts` module URL remained in the failed
  module cache while the deprecated `WorkflowRunPanel` export and dead
  `WorkflowView` state still referenced the old surface. This made entering
  Workflow fail before the view mounted.
- Repair: removed the deprecated component/export and the dead `WorkflowView`
  state, then fully restarted Tauri so the module graph and failed URL cache
  were rebuilt.
- Verification: all three Workflow Vite modules returned HTTP 200; backend
  Workflow V2 document reading succeeded; focused Workflow coverage passed 34
  tests; UI typecheck, `npm run build:app`, and the LamTools design audit
  passed. This is loading verification, not visual acceptance or real
  Workflow execution evidence.

## Office retest process-audit closure (2026-09-10)

- Deployment `office_retest_process_audit` is complete. The Office retest process audit is documented in `core/docs/office-skills-internal-evaluation-2026-09-10.md`.
- Verified scores: directness/planning 5.8/10, failure/problem control 6.4/10, speed/efficiency 5.5/10, instruction adherence 8.9/10; overall 6.7/10.
- Microsoft FY25 Q4 wall time was 641.384 s; customer handover was 241.735 s (baseline 140.720 s). The two retest logs retained high cache rates and were sharply smaller; no code or Skill changes were made by this closure.
- Evidence is retained under `.tmp/office-skills-evaluation/2026-09-10-retest/{02-microsoft-fy25q4,07-customer-handover}/run/`. The process audit did not run the newcomer-onboarding scenario and does not clear the finance footer/page-number visual defect.

## Card overlay close pointer guard (2026-09-11)

- Deployment `card_close_pointer_guard` is complete. The overlay dismissal fix
  adds `core/ui/src/composables/useOutsidePointerDismiss.ts` and unifies every
  existing `@click.self` / `@mousedown.self` card-overlay close point: the same
  pointer must have both `pointerdown` and `pointerup` outside the card before
  dismissal occurs.
- Nested and Teleport-rendered overlays are isolated through their overlay
  subtrees. The covered surfaces are CoreSettings, CorePluginsEditor,
  CoreProjectSettings, PluginsShell, SearchShell, CoreArrangeManager,
  ThemeEditor, MessageView, CoreProjectCreate, CoreProjectPicker, and
  FolderBrowserDialog.
- Verification completed: `npm run test:contract` — 71 files / 494 tests
  passed; `npm run typecheck` passed; `npm run build` passed; LamTools
  design-spec audit — 71 files / 0 deviations; `git diff --check` passed.
- Tauri/CUA manual observation was attempted, but after the prescribed
  retry/reset flow it was blocked by `nodeRepl.fetch request failed`; this is
  not recorded as a passing manual check.
- The working tree retains the pre-existing uncommitted user changes and the
  pointer-guard changes; no commit or cleanup was performed by this closure.

## Office GUI 财报复测（2026-09-11）

- 新增详细记录：`core/docs/office-skills-gui-retest-2026-09-11.md`。
- 本次交付链路完成，但过程评分为 5.5/10：118 步、140 个逻辑工具调用、
  8 次失败、20 分 41 秒；加权缓存命中率 98.18%，不能掩盖步骤和上下文
  规模膨胀。
- 程序化数据/结构验证通过；人工预览仍发现 p02/p03/p04/p06/p07/p09
  的可见版式冲突，因此视觉验收未通过。
- 实时刷新后端未再出现旧订阅队列阻塞证据；GUI 交互时延仍需人工记录，
  包括首条正文、重试状态和 Stop 到终态的时间。

## Auto-follow and process-card compacting (2026-09-11)

- Deployment `auto_follow_process_cards_20260911` is complete. Auto-follow now
  targets `scrollHeight - clientHeight`, clears stale programmatic intent after
  upward input, and performs frame correction only after actual content growth.
- Older history loads automatically within 160px of the top with an in-flight
  guard and height-delta viewport anchoring; the manual load control is removed.
  The thread scrollbar reaches the main chat edge with 5% resting and 12% hover
  thumb opacity.
- Each thinking/tool card defaults collapsed to a responsive three-line
  semantic-tail caption, snapshots every 2s with fade transition, and uses
  Lucide operation/state icons. Running uses shimmer plus restrained breathing;
  completed is static. Pointer leave schedules a 5s card/group collapse and
  re-entry cancels it. Adjacent reasoning and ordinary tools fold together while
  pending approvals remain exposed.
- Verification: focused 4-file coverage (104 tests), `npm run test:contract`
  (71 files / 500 tests), `npm run typecheck`, `npm run build`, Lam design audit
  (71 files / 0 deviations), and `git diff --check` all passed. No Tauri/manual
  UI run was performed per user request.
- Final UI copy/interaction correction: reasoning titles preserve the last
  semantic sentence; tool titles use action + target (`加载技能 · 技能名`, the
  filename for writes/edits, and the concrete command for commands), with
  unified indentation. Title click reveals 3 lines of card body content, body
  click a 7-line body viewport, and mouseleave collapses after 5s. The 3/7-line
  limit excludes tool outer frames and file/terminal bars; `.thread
  .reasoning-body.process-card-body--*` raises specificity so reasoning bodies
  follow the same limit.
- History pagination now hides its skeleton, prefetches at two viewports or at
  least 640px ahead, fetches 50 items per batch, and anchors to the first visible
  message DOM node. Final correction verification: focused 96/96, contract 71
  files / 502 tests, typecheck/build pass, design audit 71 files / 0 deviations,
  and `git diff --check` with only newline warnings. Tauri/manual UI remains
  unrun by request.
- The deployment has no known code blocker. Existing uncommitted user changes
  remain in the working tree; no commit or cleanup was performed.

## User-message history paging closure (2026-09-12)

- Deployment `user_message_history_paging_20260912` is complete. Root cause was
  `_character_page_snapshot` paging only `core.item_order`, then filtering
  top-level items by Core-selected IDs; persisted `userMessage` rows were
  therefore unreachable in large turns.
- The fix unifies sequence-ordered top/Core paging, includes causally preceding
  user-message anchors for selected assistant turns, and widens the frontend
  tail window when a boundary lands on an assistant.
- Real thread `4124c50498f5441d83b377dc16fa0e48` now returns an initial 200KB
  page containing its user ID, 27 latest Core items, `has_more=true`, and
  `character_count=186390`.
- Verification: `pytest tests/test_core_sync.py -q` passed 7 tests; focused UI
  coverage passed 2 files / 32 tests; full UI Vitest passed 71 files / 503
  tests; `npm run typecheck` and `npm run build` passed; `git diff --check`
  passed with LF/CRLF warnings only. No Tauri/manual UI run was performed.
- A broader pre-existing backend subset had 89 passed / 1 unrelated failure in
  `test_core_live_resume_response_exposes_page_cursor`; it expects events while
  resume defaults to including a snapshot, and is not attributed to this patch.
- No deployment-specific blocker is known. Existing uncommitted work remains;
  no commit or cleanup was performed.

## Unified message attachment deck closure (2026-09-12)

- Task ID: `artifact_deck_closure`. Deployment `core_artifact_attachment_deck`
  is complete. The shared UI now has
  `core/ui/src/components/MessageAttachmentDeck.vue` for direct, panel-free
  message-local previews: assistant output accepts only `image` and
  `file_change` artifacts and excludes `file_read`; user-upload attachments
  render below user messages.
- Output decks expand left-to-right and upload decks right-to-left. Cards stay
  compact and overlapped; hover, focus, and click expand a single preview, and
  click pinning keeps it open. `ResizeObserver` derives page size from the
  actual deck width, with left/right arrow paging. Text/code/config/document
  excerpts, image thumbnails, and typed file icons are supported.
- Motion uses GSAP Flip with restrained back easing, selected-card scale and
  z-layer elevation, sliding page changes, and a reduced-motion fallback.
- Verification: focused 3 files / 16 tests passed; `npm run test:contract`
  passed 72 files / 512 tests; `npm run typecheck` and `npm run build` passed;
  LamTools design audit passed 72 files / 0 deviations. `git diff --check`
  for tracked touched files emitted only LF-to-CRLF warnings and no
  whitespace-error text.
- Tauri/CUA observation was attempted twice, including once after a CUA reset;
  desktop Vite remained on `127.0.0.1:5173`, but both attempts failed with
  `nodeRepl.fetch request failed`. No manual UI pass is claimed.
- Read-only Git handoff: deployment evidence includes the new
  `MessageAttachmentDeck.vue`, its `MessageView.vue` integration, the shared
  app/workbench projection updates, and the focused attachment-deck and
  artifact-panel tests. The tree remains heavily dirty and uncommitted;
  unrelated and concurrent user changes were preserved, with no commit,
  revert, or cleanup performed.

## Web search plugin repair (2026-09-12)

- Deployment `web_search_plugin_repair_20260912` is complete. Root causes were
  the bundled/current `consider` loadtools omitting `web_search`, the real
  default Baidu endpoint being blocked by wappass captcha, Bing returning no
  usable result structure, and the schema naming `duckduckgo` while runtime
  accepted `ddg`.
- Fixes: bundled `consider` now includes `web_search`; the factory supports
  configured-provider fallback defaults (`ddg` then `bing`), strict explicit
  provider behavior, attempted-provider/error metadata, and a
  `duckduckgo` compatibility alias with `ddg` as canonical schema. Local
  runtime configs expose `web_search` and use DDG by default.
- Verification: 99 targeted tests passed across `test_web_tools.py`,
  `test_bundled_plugins.py`, `test_config_defaults.py`, `test_default_toolbox.py`,
  and `test_core_default_agent.py`; the current `consider` config reports
  `web_search_visible=True`; real default search for `LamTools GitHub` returned
  `status=ok` through `ddg` with 3 results. Scoped `git diff --check` passed
  with newline warnings only.
- Read-only Git handoff: tracked deployment files are
  `core/config/resources/loadtools.jsonc`, the bundled websearch schema,
  `core/src/lamtools_core/app/default_agent.py`,
  `core/src/lamtools_core/tool/default_toolbox.py`,
  `core/src/lamtools_core/tool/search/factory.py`,
  `core/src/lamtools_core/tool/sub_agent_runner.py`, and the related config,
  toolbox, agent, HTTP-agent, and web-tool tests. The ignored local runtime
  files `core/.lam/core/config/loadtools.jsonc` and
  `data/core-agent/plugins/websearch.jsonc` were updated; the heavily dirty
  uncommitted tree and unrelated/concurrent changes were preserved.

## Baidu official API decision (2026-09-12)

- Deployment `baidu_search_plugin_repair_20260912` is paused pending user
  choice; it is a follow-up to the completed web-search repair and made no
  production-code changes. The main agent recorded one durable diary lesson.
- Direct probes of `https://www.baidu.com/s` (standard HTML and `tn=json`),
  `https://m.baidu.com/s` (`word` and `wd`), HTTP/HTTPS, cookie warmup, and
  `trust_env` true/false all returned 302 redirects to
  `wappass.baidu.com/static/captcha`; no proxy environment variables were
  active.
- Official Baidu documentation at
  `https://cloud.baidu.com/doc/qianfan-api/s/Wmbq4z7e5` identifies
  `POST https://qianfan.baidubce.com/v2/ai_search/web_search`, API-key
  authentication, references output, and 1,500 free monthly calls with daily
  allocation.
- Exact next step: ask whether to replace the anonymous Baidu provider with
  the official authenticated API, then obtain and configure a key if approved.

## Web search proxy configuration (2026-09-12)

- Deployment `web_search_proxy_config_20260912` is complete. The websearch
  schema, UI, and backend now accept an optional port-only `proxy_port`; the UI
  persists it through the existing websearch config RPC. DuckDuckGo derives
  `http://127.0.0.1:<port>` when set and connects directly when omitted. The
  local runtime configuration uses port `7890`; generic `plugin config get/set`
  already provides the matching CLI capability.
- Verification: 119 backend-related tests passed; focused UI coverage passed
  1/1; full UI coverage passed 74 files / 518 tests; UI typecheck and build
  passed; LamTools design audit passed 72 files / 0 deviations; a real
  configured DDG request through port 7890 returned `status=ok` with 3 results.
  Touched-source `git diff --check` reported only newline warnings.
- No Tauri visual/manual observation was performed. Read-only Git handoff
  covers `core/src/lamtools_core/plugins/bundled/websearch/config/schema.jsonc`,
  `core/src/lamtools_core/tool/search/duckduckgo.py`,
  `core/src/lamtools_core/tool/search/factory.py`,
  `core/ui/src/components/CoreWebSearchEditor.vue`,
  `core/tests/test_web_tools.py`, and
  `core/ui/tests/core-web-search-editor.test.ts`. The working tree remains
  dirty and uncommitted; unrelated and concurrent changes were preserved.

## Artifact system redesign (2026-09-12)

- Deployment `artifact_system_redesign_20260912` is paused before
  implementation pending user consensus on the redesign direction. No
  production code or tests changed; the main agent added one diary lesson and
  this handoff documentation.
- Diagnosis: the project registry stores per-artifact JSON UUID manifests under
  `.lam/artifact`; runtime projection derives `artifact-{sha1}` IDs when tool
  artifacts have no ID. Only image-generation and upload paths register
  durable manifests, while ordinary `file_change` events do not. Local
  evidence is `data/core.db` with 3,842 events containing top-level artifacts
  and 3,842 refs: 2,210 `command_output`, 1,072 `file_change`, 495
  `file_read`, 47 `web_fetch_content`, 17 `web_search_result`, and 1
  `test_result`; `.lam/artifact` contains only two manifests, both deleted
  user-upload images.
- Current UI evidence: `ArtifactPanel.vue` sits below runtime status in the
  292px right drawer, fetches on mount/project change/manual refresh, and owns
  a separate preview. The new uncommitted `MessageAttachmentDeck.vue` is
  message-local and filters output presentation; it does not provide durable
  identity.
- Proposed direction, pending approval: one durable Artifact fact model with
  separate output/input/evidence roles; a contextual message deck plus
  project-wide 成果库; StagePane as the preview/open surface; live RPC/event
  updates; CLI parity; and migration/compatibility for existing manifests and
  events.
- Tauri dev was on port 5173, but two CUA attempts, including one after reset,
  failed with `nodeRepl.fetch request failed`; no visual pass is claimed.
- Exact next milestone: obtain user approval or revision of the proposed
  direction, then define the artifact contract and migration against existing
  manifests/events before implementing production code. The tree remains
  heavily dirty and uncommitted; unrelated work is preserved.

## Sunday branding and visual implementation (2026-09-13)

- Task ID/deployment: `sunday_brand_plan_closure` /
  `sunday_ai_brand_20260912`; state: `complete`. The canonical product name
  is `Sunday`. `AI software` is only a subdued secondary label/tagline; no
  translated product name is displayed.
- Completed Sunday theme: `SUNDAY_DARK_THEME` and `SUNDAY_LIGHT_THEME` are
  shared defaults, and the `sunday` preset is available through the shared
  theme system. Validated project visual metadata (`icon_key`/`color_key`)
  has shared picker/icon rendering and backend persistence.
- Completed visual assets: repository-owned
  `core/ui/src/assets/sunday-mark.svg` and `sunday-app-icon.svg`, reusable
  `core/ui/src/components/SundayLogo.vue`, and the desktop/UI/Tauri ICO assets
  provide the gradient mark with its warm-white rounded-square, soft-shadow
  application-icon treatment.
- The custom title bar places the Sunday mark at the far left, followed by
  strong `Sunday` and weak `AI software`. Document, native main-window, and
  desktop plugin-host titles use Sunday-facing names. The desktop left sidebar
  is 232px; the mobile drawer retains its independent `min(86vw, 320px)` rule.
- Project settings save name and visual metadata immediately on the relevant
  change/blur/enter or icon/color selection; the visual picker and settings
  share one validated metadata contract.
- Packaging uses the repository-owned Inno Setup chain:
  `core/desktop/installer/Sunday.iss` plus `build-installer.ps1`, orchestrated
  by the package script. Tauri remains `--no-bundle`; `lamcore.exe`,
  `lamcore-backend/LamCore.exe`, `com.lamtools.lamcore`, and legacy migration
  behavior remain compatibility boundaries.
- Empty sessions use an animated Sunday logo/greeting. Startup first-paint
  bootstrap now resolves the saved/system Sunday theme before stylesheet paint,
  preventing the dark-preference ~80ms light flash. Tauri verification covered
  dark preference at 80/480/740ms, explicit light with a dark system, and
  reduced-motion. The motion sequence is translucent veil → centered bare logo
  → theme background expanding from the logo center → shell components fading
  in; reduced-motion removes clip-path motion while retaining the hand-off.
- Final gates passed: UI 75 files / 540 tests, typecheck, UI build, desktop
  build, design audit 76 files / 0 deviations, and `git diff --check`.
  The final Inno package is
  `E:\LamTools\core\desktop\src-tauri\target\release\bundle\inno\Sunday_0.3.2_x64-setup.exe`
  (56,460,297 bytes; SHA-256
  `238EB54CDBD4A55C76735F767A28864F8316CA70F9248F8952B3CE87083E096A`).
  Installation to `E:\setuptest\0.3.2` started the main process as PID
  `34412` and the backend as PID `39536`; both executable paths were verified.
- Evidence: `core/ui/src/helpers/theme.ts`,
  `core/ui/src/data/theme-presets.ts`, `core/src/lamtools_core/app/project_visuals.py`,
  `core/ui/src/components/ProjectVisualPicker.vue`,
  `core/ui/src/components/ProjectVisualIcon.vue`,
  `core/ui/src/components/CoreProjectSettings.vue`,
  `core/ui/src/components/TitleBar.vue`, `core/ui/src/components/SundayLogo.vue`,
  `core/ui/src/motion/startupSplash.ts`, `core/ui/src/app/LamToolsApp.vue`,
  `core/desktop/index.html`, `core/desktop/src-tauri/tauri.conf.json`,
  `core/desktop/installer/Sunday.iss`, `core/desktop/installer/build-installer.ps1`,
  `core/desktop/PACKAGING.md`, `core/ui/tests/startup-splash.test.ts`,
  `core/ui/tests/workspace-shell.test.ts`, the final package, and the installed
  `E:\setuptest\0.3.2` process check.
- Compatibility boundary: visible UI/native/installer/asset branding changes
  do not rename stable technical identifiers (`core`, `lamtools_core`,
  `core:agent`, protocols, storage/config keys, data paths,
  `com.lamtools.lamcore`, or internal `LamCore.exe`).

## Modular right-sidebar closure (2026-09-13)

- Task ID/deployment: `sidebar_closure_handoff` /
  `modular_sidebar_20260913`; closure state: `complete`. The active goal was
  to make the Core/Sunday right rail modular and plugin-capable while
  preserving the shared UI and mobile right-rail behavior.
- Overall progress: the roughly 320px single-column separator stack now uses
  one token-driven liquid-glass host surface. `RightSidebarHost` owns
  reorder/hide/collapse state and per-project persistence; built-ins cover
  Runtime, Resources, Web Search, RAG status/search, and Artifacts. Declarative
  plugin snapshots and trusted in-process Vue contributions are supported;
  Three.js/runtime visualization remains deferred.
- Current position: backend widget manifests/validation, scoped
  `plugin.widget.list/get/invoke` operations, CLI list/show/action parity,
  Web Search snapshot/real-health operations, and safety controls are in
  place. The frontend host, editor, layout persistence, trusted loader,
  plugin-mode surface, Web Search/RAG modules, Artifact embedding, and
  `LamToolsApp`/`WorkspaceShell` integration are in place. With no RAG plugin
  installed, the UI reports unavailable and only tries legacy search after a
  user action; no fabricated counts or event-push dependency are used.
- Verification: frontend focused coverage passed 25/25; full UI coverage
  passed 77 files / 553 tests; UI typecheck and `build:app` passed (existing
  chunk/dynamic-import warnings remain). Backend plugin/lifecycle/workflow
  coverage passed 64, CLI/assembly 76, widget 7/7, Web Search 10/10, and the
  combined target passed 42 with 1 skip; HTTP exposure passed. Full pytest
  separately passed 1740 with 2 skips; two unrelated live-resume tests still
  fail alone (`expected 500, got 0`) and are not on the sidebar call path.
- Limitation and disposition: the user stopped visual/Tauri interaction, so
  no visual or manual UI pass is claimed. `git diff --check` passed; the
  working tree remains heavily dirty and uncommitted, and this closure made no
  commit, revert, cleanup, or unrelated attribution.
- Exact next entry point: inspect the current uncommitted tree, then continue
  the existing Artifact redesign consensus/contract work, Office visual
  quality, real-device LAN/Relay pairing/reconnect, and Docker Hub image
  validation milestones. No deployment-specific blocker is known.

## Next Milestone

本轮下一里程碑是用户在当前 Tauri 窗口完成 Workflow UI 的视觉验收，并按需
运行一个真实工作流。Artifact 重做共识与契约、Office 生成质量、真实设备
LAN/Relay 配对重连和 Docker Hub 镜像构建仍是并行后续事项；本轮不替代这些
工作，也不把进程/日志核验写成视觉通过。

## ComfyUI 工作流与 Agent 对齐规划（2026-09-13）

- 部署 `comfyui_workflow_agent_alignment_20260913` 处于 `paused`：本轮为
  Heavy 规划/研究，没有修改生产代码或测试；实现必须等用户对边界方案
  完成共识。现有工作树很脏且含并发/用户改动，已保留原状。
- 对齐目标应是 ComfyUI 的能力、架构和交互范式，而非复制其代码或做像素
  克隆。ComfyUI 前后端为 GPL-3.0，LamTools 为 MIT；后续应依据公开行为
  独立实现，并保留 Sunday/LamTools 视觉语言。
- 当前工作流已有 Vue Flow 画布、五类节点、条件边、自动保存，以及全图、
  单节点、从节点运行和 Agent 自然语言改图；审计发现步进不会续跑、运行
  输出/错误/尝试信息被丢弃、事件终态名称不一致、右栏挂载目标缺失，并缺少
  输入表单、历史/缓存、Undo/Redo、多选分组、reroute、模板、导入导出和
  Schema 驱动节点注册等 ComfyUI 核心体验。
- 建议边界：Workflow 独立负责文档、存储、校验、队列、运行时、缓存、历史
  与事件；Agent 通过显式适配器和 `ExecutionContext` 协作，可辅助改图、作为
  Agent 节点执行器、或把 Workflow 当工具调用，禁止共享隐式会话状态和内部
  运行对象。UI 可按 `model/commands/document/canvas/catalog/inspector/runtime/
  resources/services/tests` 分层，并复用现有右栏与共享控件。
- 待用户明确的四项边界：行为/交互对齐还是像素级复制；是否保留现有格式并
  提供迁移；是否开放插件注册任意节点类型；缓存是否仅允许声明为纯函数的
  确定性节点（建议命令、脚本、Agent 默认不缓存）。
- 下一入口：取得共识后先定义 Workflow/Agent 合同、执行上下文、事件与旧格式
  迁移，再分阶段实现 ComfyUI 能力和 UI；详细交接见
  `agent_docs/latest_session_work.md`。

## ComfyUI 工作流与 Agent 对齐实现闭环（2026-09-13）

- Task ID/deployment: `workflow_rebuild_closure` /
  `comfyui_workflow_rebuild_20260913`; state: `complete`。本节 supersede
  上述规划部署的 paused 状态。
- 已完成 ComfyUI 行为/契约对齐的独立实现：节点注册表与 Schema 节点、DAG
  与部分执行、持久续跑、声明纯节点缓存、队列/历史/取消、CLI/RPC 对等；
  同时保留旧格式兼容。
- Workflow 与 Agent 已通过显式 `WorkflowExecutionContext` 和适配器解耦：
  Model、Agent、插件节点可在权限、取消和事件链路内协作。Workflow 作为
  Agent 工具调用时会继承附件、runtime snapshot、环境、能力、权限、lineage
  与 workflow stack；外部传入包含当前 workflow 的 stack 会立即拒绝，内部
  child context 仍合法。revision/CAS、并发原子锁和保存冲突处理已覆盖。
- UI 已补齐节点目录、输入表单、运行结果、队列/历史/缓存、导入导出、模板、
  右栏、Undo/Redo、多选、分组、reroute、注释、系统剪贴板、重连、对齐/分布、
  标签页和移动端布局；Sunday/LamTools 设计体系统一并移除重复 `WfSelect`，
  使用共享 `UiSelect`。
- 验证：`py -3.14 -m pytest -q tests -k workflow` 为 74 passed / 1689
  deselected；UI `npm run typecheck`、`npm run test:contract`（80 files / 573
  tests）和 `npm run build:app` 均通过（仅既有 chunk/dynamic-import warnings）；
  `git diff --check` 通过，仅有 CRLF warnings。独立 Adapter verification
  PASS，覆盖真实 `KernelSubAgentRunner→CoreBaseAgentKit→workflow-tool` 链路。
- 全量后端为 1759 passed / 2 skipped / 2 failed。两个失败均为本次部署前已
  存在且与 Workflow 无关的 live-resume 空 events 问题：
  `test_core_live_client_e2e::test_core_app_server_client_runs_live_operation_matrix_against_real_websocket_server`
  与 `test_core_live_router::test_core_live_resume_response_exposes_page_cursor`。
- 限制与 Git 交接：用户负责视觉验收；本部署未启动 Tauri、浏览器或人工视觉
  检查，不宣称视觉通过。工作树仍重度 dirty 且未提交；未执行 commit、cleanup、
  revert、stage 或归因，既有及并发用户改动均保留。
- 下一入口：用户进行视觉验收；若发现缺陷，仅修复 Workflow UI；否则另起独立
  范围部署处理无关的 live-resume 失败。
## Workflow 数据模型与 ComfyUI 规范研究（2026-09-13）

- Task ID/deployment: `workflow_data_model_research_closure` /
  `workflow_data_model_alignment_20260913`; state: `paused`，等待用户确认
  Sunday 原生 V2 还是 ComfyUI JSON 作为 canonical。此次仅做只读研究与交接，
  未修改生产代码或测试；不取代前述已完成的 Workflow 实现闭环记录。
- 官方快照：ComfyUI backend `0.35.0`、frontend `1.55.7`。持久化工作流是
  LiteGraph 编辑器文档：v0.4 使用数组 links，v1 增加 state counters、对象
  links、groups、reroutes、config、extra、subgraph definitions，以及节点的
  几何、flags、mode、order、slots、properties、widgets_values。
- 可执行 API prompt 是另一种模型：以 node id 为键的对象，包含 `class_type`
  与 `inputs`；连线编码为上游 node/output slot 对。静音或虚拟编辑节点不进入
  prompt；后端从 outputs 递归校验 required inputs、类型、组合约束与 cycles。
  `/prompt`、`/queue`、`/history`、`/object_info` 和 WebSocket 构成运行时边界；
  实际 queue tuple 字段可能与 OpenAPI 漂移，因此适配器需要版本探测。
- 本地模型问题已确认：单一 `WorkflowDef` 混合执行与画布位置；config/types
  过于自由；edges 与派生/持久 map 的语义重复；完整平铺 JSON 不适合作为模型
  视图。这使机器校验、迁移和 Agent 理解都容易产生歧义。
- 推荐待确认方案：Sunday-native V2 canonical document + 编译后的 execution
  prompt + 面向模型的紧凑 semantic view，并提供 ComfyUI import/export adapters；
  不将原始 ComfyUI LiteGraph JSON 作为内部 canonical。依据公开行为独立实现，
  不复制 ComfyUI GPL-3.0-only 代码；保留 Sunday/LamTools 视觉语言。
- 官方证据入口：
  `https://github.com/Comfy-Org/ComfyUI_frontend/blob/main/src/platform/workflow/validation/schemas/workflowSchema.ts`、
  `https://github.com/Comfy-Org/ComfyUI_frontend/blob/main/src/utils/executionUtil.ts`、
  `https://github.com/Comfy-Org/ComfyUI/blob/master/server.py`、
  `https://github.com/Comfy-Org/ComfyUI/blob/master/execution.py`、
  `https://github.com/Comfy-Org/ComfyUI/blob/master/openapi.yaml`；本地证据为
  `core/src/lamtools_core/plugins/bundled/workflow/` 及其测试目录。
- Verification/limitations：完成官方规范与本地模型的只读核对，未运行生产测试、
  构建或 Tauri 手工验收。工作树仍重度 dirty 且未提交；本次不归因、stage、
  commit、清理或回滚任何现有/并发改动。Exact next entry point：先取得用户对
  Sunday-native V2 与 ComfyUI JSON canonical 的选择，再定义迁移兼容、编译 prompt、
  semantic view 和测试计划。

## Hide project header hash handoff（2026-09-13）

- Task ID/deployment：`hide_project_hash_setting_closure` /
  `hide_project_hash_setting`；state：`paused`，等待用户确认标识符放置方式。
- Active goal：隐去常规标题栏的 `#4124c504`，并明确项目设置中应显示会话
  标识还是项目标识。已核实该值是当前 session/thread ID 的前 8 位，不是
  project ID；常规标题栏由 `LamToolsApp` 使用的 `CoreSessionTitleEditor`
  渲染，Workflow 也复用该组件。
- Current position：`CoreProjectSettings` 已接收 `project.id`，但未接收
  `activeSessionId`。待选解释为：（1）将当前 session ID 移入项目设置；或
  （2）在项目设置中显示 project ID。此暂停部署未修改生产或测试文件。
- Verification/Git：仅完成指定证据文件的只读核对，未运行测试或构建。工作树
  原已重度 dirty、未提交；本部署未执行 commit、stage、revert 或 cleanup。
- Exact next entry point：用户确认上述解释后，按选择更新
  `CoreSessionTitleEditor`、`CoreProjectSettings` 与 `LamToolsApp` 传参，
  同步对应 UI 测试，再运行聚焦验证。证据：上述三份组件及
  `core/ui/tests/core-session-title-editor.test.ts`、
  `core/ui/tests/core-project-components.test.ts`。

## Optical liquid-glass closure (2026-09-14)

- Task ID/deployment: `optical_liquid_glass` /
  `optical_liquid_glass`; closure state: `complete`. The active goal was to
  apply advanced optical liquid glass consistently to the right sidebar and
  all shared right-click cards under a code-only verification scope.
- Overall progress/current position: `core/ui/src/styles/optical-glass.css`
  now provides token-driven clear transmission, restrained 8px blur,
  saturation 1.14, brightness 1.02, contrast 1.03, and 2% tint, with localized
  radial/linear/conic reflection, dispersion, highlight, and environment/color
  response layers. `layout.css` imports the stylesheet; `.optical-glass` is
  applied to the WorkspaceShell right drawer and ContextMenuPanel. Both use
  border 0; the old four-edge masks and per-surface filters are removed, with
  no uniform white border or edge-opacity fade.
- Verification: focused coverage passed 36/36 and independent coverage passed
  56/56; full UI coverage passed 82 files / 614 tests; UI typecheck and
  `build:app` passed; LamTools design audit passed 84 files / 0 violations;
  independent Tester review passed; scoped `git diff --check` passed.
- Limitation and disposition: no Tauri runtime or visual check was authorized
  or performed. The worktree remains heavily dirty and uncommitted; unrelated
  and concurrent changes were preserved, with no stage, commit, revert,
  cleanup, or attribution.
- Exact next entry point: if visual validation is later authorized, inspect the
  Tauri right drawer and shared context menus for background transmission,
  localized highlights, and reduced edge treatment; otherwise continue the
  existing Workflow acceptance, Artifact consensus, Office visual-quality,
  real-device LAN/Relay, and Docker image milestones. No deployment-specific
  blocker is known.

## Context-menu liquid-glass closure (2026-09-14)

- Task ID/deployment: `context_menu_liquid_glass` /
  `context_menu_liquid_glass`; closure state: `complete`. The active goal was
  to align every right-click card with the right-sidebar transparency and blur
  standard under the code-only verification scope.
- Overall progress/current position: all seven right-click caller surfaces
  route through the shared `openContextMenu`/`ContextMenuHost`; root menus and
  submenus share `ContextMenuPanel.vue`. Its stable outer surface uses
  `blur(var(--space-4)) saturate(1.08)`, a four-edge mask, and a 4% current-area
  text tint; animation is isolated to inner content so the outer compositing
  remains visually stable.
- Verification: focused context-menu coverage passed 58/58; full UI coverage
  passed 82 files / 614 tests; UI typecheck and `build:app` passed; LamTools
  design audit passed 83 files / 0 violations; independent Tester review
  passed; scoped `git diff --check` passed.
- Limitation and disposition: no Tauri runtime/visual check was performed,
  per the code-only scope. The working tree remains heavily dirty and
  uncommitted; unrelated and concurrent changes were preserved, with no
  stage, commit, revert, cleanup, or attribution.
- Exact next entry point: when visual validation is requested, inspect the
  shared Tauri context-menu host across root and submenu surfaces; otherwise
  continue the existing project-level Workflow acceptance, Artifact consensus,
  Office visual-quality, real-device LAN/Relay, and Docker image milestones.
  No deployment-specific blocker is known.

## Right-sidebar motion closure (2026-09-13)

- Task ID/deployment: `sidebar_motion_closure` /
  `right_sidebar_motion_20260913`; closure state: `complete`. The active goal
  was to finish lifecycle-safe motion and geometry behavior for the modular
  right-sidebar without changing runtime visualization.
- Overall progress/current position: `RightSidebarHost` now scopes GSAP editor
  motion and uses `TransitionGroup` for module enter/leave/reorder. Modules
  retain their body with `v-show`, collapse through 200ms grid/opacity motion,
  expose `aria-hidden`/`inert` safety, provide drag lift/drop feedback, and
  clean up listeners/animation state. Workspace shell geometry uses 240ms
  enter / 180ms exit, an instant reduced-motion fallback, an exact 2px main
  gap, rounded left corners only, and square right corners.
- Verification: focused right-sidebar coverage passed 25/25; full UI coverage
  passed 553/553; `npm run typecheck` and `npm run build:app` passed; design
  audit passed 83 files / 0 violations; `git diff --check` passed. Prior full
  backend evidence remains 1740 passed / 2 skipped with two unrelated
  live-router/e2e failures; this motion closure did not attribute them to the
  sidebar.
- Limitation and disposition: no Tauri runtime interaction or visual/manual
  pass was performed. The working tree remains heavily dirty and uncommitted;
  unrelated and concurrent changes were preserved, with no commit, stage,
  revert, cleanup, or attribution.
- Exact next entry point: when visual validation is requested and available,
  inspect the Tauri right-sidebar collapse, reorder, drag feedback, geometry,
  and reduced-motion states; otherwise continue the existing project-level
  Artifact consensus, Office visual-quality, real-device LAN/Relay, and Docker
  image milestones. No deployment-specific blocker is known.

## ComfyUI 工作流最终核验补充（2026-09-13）

- Task ID: `workflow_rebuild_closure`；本补充记录最终已验证事实，并取代
  同日 Workflow 数据模型研究的 paused 规划状态。此前用户记录的 UI 收尾也
  计入本次完成范围：全幅画布、中键平移、右键菜单、紧凑 workflow composer、
  保存 icon-only、将 exposure 移入设置，以及 ComfyUI 节点稳定端口。
- V2 UI 以 canonical RPC 为主，保留兼容回退。数据/执行边界覆盖 ComfyUI
  v1 state 与 object links、0.4 reroutes、最大合法 id、strict one-hop
  引用；扩展字段隔离在 `canvas.comfyui`，不污染 Sunday-native canonical
  文档。
- 最终验证：UI typecheck 通过；UI 合同测试 583/583 通过；`build:app` 通过；
  design audit 为 83/0；Workflow focused tests 为 92/92。后端全量为 1777
  passed / 2 skipped / 2 failed，两个失败仍是已知且与 Workflow 无关的
  live-resume 空 events 问题。
- Tauri 环境已就绪：Vite `5173`，backend `58273`。这仅表示可供用户观察，
  本次不宣称已完成视觉验收；用户负责最终视觉验收。工作树保持重度 dirty
  且未提交，未执行代码修改、stage、commit、cleanup、revert 或归因。
- 下一入口：用户在 Tauri 中进行 Workflow 视觉验收；若发现问题，仅修复
  Workflow UI，并沿用上述 canonical RPC/兼容回退边界。

## Workflow UI 工具栏收尾（2026-09-13）

- Task ID: `workflow_rebuild_closure`。已验证工具栏固定在画布左侧纵向排列，
  按钮采用 icon-only 并提供 `title`，工具栏支持纵向滚动；移除 Vue Flow
  Controls，运行控制条上移以避开紧凑 workflow composer。
- 变更范围：`WorkflowCanvas.vue`、`WorkflowControlBar.vue`，及
  `workflow-canvas-parity.test.ts`。
- 验证：定向 Vitest 18/18、UI typecheck、`npm run build:app`、设计审计
  0 偏离、`git diff --check` 均通过；Tauri Vite `5173` 与后端 `58273`
  均返回 HTTP 200。
- 视觉验收仍由用户负责；本记录不宣称视觉通过。

## Session ID 项目设置与标题栏收尾（2026-09-13）

- Task ID/deployment：`move_session_id_to_project_settings_closure` /
  `move_session_id_to_project_settings`；state：`complete`。本节取代此前
  `hide_project_hash_setting` 的 paused 规划记录。
- Active goal/outcome：普通 `LamToolsApp` 标题栏不再显示 session ID 前 8 位；
  项目设置仅在所选项目与当前活动 session 匹配时显示 `#` 加前 8 位，并可复制
  完整 ID，复制成功后给出状态反馈。Workflow 与 `CoreSessionTitleEditor`
  的既有行为保持不变。
- Desktop geometry：普通标题行使用 `data-session-header`，以设计 token
  推导的 75px band 和 token 推导的 -44px inset reclaim，使其位于原生标题栏
  下沿与分割线之间居中；移动端与 Workflow 不受影响。
- Verification：聚焦 2 文件 / 27 tests、UI contract 80 文件 / 588 tests、
  typecheck、`build:app` 均通过；构建仅有既有 chunk/dynamic-import warnings；
  LamTools audit 为 83 文件 / 0 violations；scoped `git diff --check` 通过。
  独立 tester 检查构建 CSS 后，在修复一次被拒绝的 cascade 缺陷后接受结果。
- Limitation/Git：用户明确停止 Tauri 自动化，因此没有 runtime/manual visual
  pass 声明。工作树仍重度 dirty 且未提交；本部署保留既有及并发改动，未执行
  commit、stage、revert、cleanup 或归因。
- Next milestone：如需继续，仅在 Tauri 可用时由用户进行视觉确认；否则从当前
  未提交树继续既有项目级里程碑。

## Workflow 节点目录与 Agent 边界重构（2026-09-13）

- Task ID/deployment：`workflow_node_catalog_refactor_closure` /
  `workflow_node_catalog_refactor_20260913`；closure state：`complete`。
- Outcome：工作流节点目录与右键添加器改为 `object_info` 驱动的动态注册、分类、
  搜索和添加；canonical 节点类型为 Model、Agent、Command、Python、Constant、
  Input、Output、Template、Condition、Merge、Join、Subgraph。旧 `AI`、`Script`、
  `Content`、`Transform`、`Branch` 类型隐藏于新目录但保持可执行兼容。类型 ID
  保持开放，端口 ID 稳定且不可变；V2 与 ComfyUI 往返边界保留。Tool/MCP 与
  HTTP 节点暂缓，待安全宿主边界明确后再引入。
- Agent/Workflow 通过显式 `WorkflowExecutionContext` 与适配器协作；Workflow
  独立拥有文档、校验、队列、运行时、缓存、历史和事件，避免共享隐式运行状态。
  SemanticGraph 编辑视图保留节点参数、位置和 link modifiers。
- Verification：Workflow backend suite `103 passed`；Agent/default-toolbox
  regression `97 passed`；UI contracts `81 files / 596 tests passed`；
  `npm run typecheck`、`npm run build:app`、Lam design audit `83 files / 0
  violations` 均通过。Tauri Vite `5173` 与 backend `58273` 的 `/api/health`
  均返回 HTTP 200。
- Limitation/Git：代码和自动化核验已完成；未宣称 Tauri 视觉验收通过，视觉验收
  与真实工作流运行体验由用户负责。工作树仍重度 dirty 且未提交；本部署仅做
  只读 Git 交接，未 stage、commit、revert、cleanup 或归因。
- Exact next entry point：用户在 Tauri 中完成视觉验收并运行一个真实工作流；若
  发现问题，仅从 Workflow UI/节点目录边界继续修复，并保持 canonical RPC 与
  兼容回退契约。

## n8n 工作流系统对齐研究闭环（2026-09-13）

- Task ID/deployment：`n8n_workflow_alignment_research_closure` /
  `n8n_workflow_alignment_20260913`；closure state：`paused`。本轮是研究与规划，
  等待用户共识后才进入实现；未修改生产代码或测试。
- 已核实的 n8n 可迁移概念：工作流 JSON 以版本化 node type、parameters、
  credential references、connections 和 execution settings 描述；运行时以
  item/binary-data、表达式与 lineage 传递数据；生产执行还覆盖
  trigger/webhook、retry/error routing、wait/resume、subflow、credential
  isolation、execution persistence，以及 pin/manual data。n8n Sustainable Use
  License 只允许将其作为概念参考；任何代码或 UI 复用须先做法律审查：
  <https://docs.n8n.io/n8n-community-license/sustainable-use-license.md>。
- LamTools 已有的对应基础：`workflow/backend/registry.py` 提供动态
  `object_info`/Schema registry；`document.py` 提供 V2 文档、execution prompt
  编译和紧凑 semantic graph；`runtime.py` 已有 Model/Agent 分离的
  `WorkflowExecutionContext`、subgraph、queue/cache/history/snapshot/resume
  运行路径；Core Arrange 已支持 once、interval/calendar 和 event 触发。
- 当前差距：尚无工作流一等的 item/binary envelope 与 lineage packet；表达式仍是
  Condition/edge 的受信作者 Python `eval`，没有统一安全表达式引擎；没有
  `CredentialRef` 与 workflow 级凭据隔离；Arrange 尚未桥接 workflow activation
  或 webhook；也缺 node version migration chain 与明确 upgrade policy。HTTP、
  Tool、MCP 节点暂不具备可接受的 credential/permission host boundary。
- 建议顺序（待用户确认）：(1) 契约基础——版本迁移、`DataPacket` legacy
  adapter、安全表达式和 `CredentialRef`；(2) 触发器——复用现有 Arrange 并增加
  受认证 webhook；(3) 每节点 error outputs、wait/resume、pin/debug 投影；
  (4) 最后才引入 HTTP/Tool/MCP 节点。Workflow 与 Agent 继续通过显式
  `WorkflowExecutionContext`/adapter 协作，不共享隐式运行状态。
- 待用户明确的决定：是否接受 n8n 仅作概念参考及上述四阶段顺序；`DataPacket`
  的 item/binary/lineage 语义与旧 Workflow 格式迁移策略；表达式语法/沙箱能力
  及凭据 vault/ref 的隔离边界；Arrange + webhook 的激活、认证、幂等与重放策略；
  以及 HTTP/Tool/MCP 是否继续暂缓直到宿主权限契约落地。
- Verification/limitations：完成官方 n8n 规范与本地 workflow/Arrange/Agent
  代码的只读核对；未运行生产测试、构建、Tauri 或真实 workflow runtime 验收，
  不宣称实现或运行通过。工作树原已重度 dirty 且未提交；本部署未 stage、
  commit、revert、cleanup 或归因。证据入口：上述 backend 文件、
  `core/src/lamtools_core/app/cli.py` 的 Arrange CLI，以及 n8n license URL。
- Exact next entry point：取得用户对数据包、表达式/凭据、触发器安全和 HTTP/Tool/
  MCP 范围的确认；随后先定义契约、迁移和兼容测试，再分阶段实现。

## Workflow 画布容器交互与 parent_id 闭环（2026-09-13）

- Task ID/deployment：`workflow_canvas_parenting_closure` /
  `workflow_canvas_parenting_20260913`；closure state：`complete`。本轮完成
  Workflow 画布的容器交互收尾及父级关系数据契约，未改变 Workflow 的执行语义。
- 交互已对齐：左键无修饰拖拽用于框选（Vue Flow
  `selectionKeyCode=true`），中键平移；节点、框架、分组和其他画布元素只有先
  选中后才可拖动。框架/分组双击会选中全部内部组件；其右键菜单提供“全选”、
  “删除”和“全部删除”。“删除”只移除容器并解除子项父级关系；“全部删除”递归
  移除容器及其内容，并清除相关节点连线。全部删除先打开确认框，倒计时 3 秒后
  才启用确认删除按钮。
- 数据模型：`WorkflowNode.parent_id` 已在 legacy 输入、V2
  `canvas.node_views`、store、UI document/resources、剪贴板复制/粘贴之间端到端
  往返；旧 `parentId` 仍可读，canonical 输出使用 `parent_id`。父级关系保留在
  画布视图，不进入执行 prompt 或节点执行配置。ComfyUI 的 bounding/pos/size
  几何字段保留兼容归一化；未声明父级的旧数据继续使用几何包含回退。
- Verification：Workflow UI 定向覆盖 4 个文件 / 39 tests；UI typecheck 与
  `npm run build:app` 通过；主代理复核 Python 37 tests，执行者更广 Workflow
  覆盖 102 tests，独立 tester 覆盖 39 tests；LamTools design audit 为 83/0，
  `git diff --check` 通过。视觉验收与真实工作流运行仍由用户负责，本轮未宣称
  Tauri/CUA 实机视觉通过。
- Git/限制：工作树重度 dirty 且未提交；本轮未 stage、commit、revert、cleanup
  或归因，既有及并发用户改动均保留。Token report 受限于主线程在续接压缩上下文
  后未能在本轮首条 commentary 写入 deployment marker。
- Exact next entry point：用户在 Tauri 中完成 Workflow 视觉验收并实际运行一个
  含框架/分组、父子节点和删除操作的工作流；若发现问题，仅从 Workflow UI 与
  parent_id 兼容边界继续修复，并保持 canonical RPC/执行 prompt 隔离。

## Durable Workflow Platform deployment closure (2026-09-13)

- Task ID/deployment: `durable_workflow_platform_closure` /
  `durable_workflow_platform_20260913`; closure state: `complete`。
- Outcome: Sunday Workflow now has a local-first durable runtime. Canonical V2
  documents pin immutable revisions for each run; the engine persists
  Workflow/Version/Run/NodeRun/Attempt state, append-only JSONL events and
  projected snapshots, and resumes completed or waiting work without repeating
  recorded side effects. Queue records retain the workflow ID, revision and
  definition snapshot. Retry/backoff/timeout, cancellation, idempotency,
  cache, activation, and wait/signal are engine contracts; activations reuse
  Core Arrange.
- Contract/security boundary: DataPacket item envelopes carry JSON plus
  Attachment/Artifact references; CredentialRef resolution is attempt-local;
  secrets are excluded from metadata, event history, snapshots, logs and
  results. Capability/resource access is fail-closed. Built-in nodes preserve
  legacy raw values while trusted plugin executors use the packet boundary.
  Conditions, edge modifiers and templates use the versioned safe expression
  AST with legacy compatibility. Agent participation remains through explicit
  execution contexts/adapters rather than shared implicit state.
- Verification: `py -3.14 -m pytest -q tests -k workflow` — 166 passed / 1691
  deselected; adjacent Agent/runner checks — 99 passed in the main-side run and
  117 passed in the independent run, with 4 existing deprecation warnings;
  UI typecheck passed; UI contract suite — 81 files / 607 tests passed;
  `npm run build:app` passed with existing chunk/dynamic-import warnings;
  workflow manifests parsed; LamTools design audit — Core UI 83 files / 0
  deviations (the audit does not scan the workflow plugin directory); manual
  banned-token scan of the workflow plugin found no findings; `git diff --check`
  exited 0 with line-ending warnings.
- Concurrency correction: independent verification exposed duplicate side
  effects when concurrent signals arrived through separate WorkflowRunner
  instances. The engine now uses a store-path-keyed process-level single-flight
  guard with bounded lock lifecycle; this closes the same-process case only.
- Limitations: no cross-process lock/claim guarantee; timeout completion settles
  lazily on signal; no complete HumanTask center; Fast/Express execution modes
  are deferred; HTTP/MCP and other external connectors remain deferred until a
  complete credential and permission host boundary exists. Effectively-once
  behavior still depends on external executors honoring idempotency keys.
- Visual/Git handoff: no Tauri or manual visual acceptance is claimed; the user
  owns visual验收 and real workflow execution. The working tree remains heavily
  dirty and uncommitted; no stage, commit, revert, cleanup or attribution was
  performed, and unrelated/concurrent changes were preserved.
- Exact next entry point: user runs a real Workflow in Tauri, including a
  durable wait/signal path and Agent boundary where applicable; if a defect is
  found, continue from `backend/durable.py`, `runtime.py`, `queue.py`,
  `snapshots.py`, `data_packet.py`, `credentials.py`, `capabilities.py`,
  `expressions.py`, and `activations.py`, keeping the same V2/legacy boundary.

## Manual `/compact` auto-alignment closure (2026-09-13)

- Task ID/deployment: `compact_auto_alignment_closure` /
  `compact_auto_alignment_20260913`; state: `complete`。
- Outcome: manual `/compact` now enters the shared `ContextCompactionController`
  used by automatic compaction. `force` only bypasses the automatic trigger
  threshold; it does not disable thinking or introduce a separate target.
  Manual and automatic paths share `resolve_compaction_budget`, the snapshot's
  model/reasoning/thinking settings, the 4096 default summary output, retry
  configuration, trigger/limit and safety margin, and effective-history loading
  via `summary_seq` (including the legacy summary-blob fallback). Original raw
  history is retained; summaries and recovery boundaries are persisted only
  after a successful completed stream.
- Verification: backend focused compaction/runtime coverage — 317 passed; UI
  command/action coverage — 22 passed; UI typecheck, Python `compileall`, and
  `git diff --check` passed. No real `/compact` was executed during verification;
  the user owns the final runtime test.
- Runtime handoff: Tauri was fully restarted with frontend Vite `5173` and
  backend `61646`. Target session remains idle with 100 history rows (`seq`
  1..100), `summary_seq=0`, and an existing 6561-character summary. This is a
  ready-to-test state, not a claim that manual compaction has passed in runtime.
- Git disposition: the worktree remains heavily dirty and uncommitted; this
  closure preserved unrelated/concurrent changes and performed no stage,
  commit, revert, cleanup, or attribution.
- Exact next entry point: user runs `/compact` in the restarted Tauri session
  and checks that it follows automatic-compaction behavior and leaves history
  unchanged on failure.

## Durable Workflow phase 2 closure (2026-09-14)

- Task ID/deployment: `durable_workflow_phase2_closure` /
  `durable_workflow_phase2_20260913`; closure state: `complete`。
- Outcome: durable Workflow execution now supports cross-process SQLite claims
  with lease/heartbeat/fencing and definition fingerprint mismatch protection.
  JSONL event append is serialized across processes. HumanTask state is projected
  durably, and Arrange-backed once timeouts resume without exposing a resume
  token. Runtime admission now enforces concurrency, rate, throttle and debounce
  policies; queue priority and a UI strategy panel expose the configured policy.
- Verification: Workflow backend suite — 195 passed; adjacent Agent/Runner
  coverage — 100 passed; claims + HumanTask focused coverage — 23 passed; UI
  typecheck passed; UI contracts — 82 files / 610 tests passed; `npm run
  build:app` passed; LamTools design audit — Core UI 83 files / 0 deviations;
  `git diff --check` exited 0 with line-ending warnings. Tauri frontend Vite
  `5173` and backend `61646` were alive, `lamcore.exe` was running, and health
  returned HTTP 200.
- Limitations: visual acceptance and real Workflow execution remain owned by
  the user; the JSON queue itself has no cross-process queue-item claim;
  external side effects still depend on executor idempotency. The worktree is
  heavily dirty and uncommitted; no stage, commit, revert or cleanup was done.
- Exact next entry point — user acceptance checklist in Tauri: (1) inspect the
  Workflow canvas, strategy panel and HumanTask projection visually; (2) run a
  normal Workflow through an Agent boundary; (3) exercise concurrent claims,
  lease/heartbeat recovery and revision/fingerprint mismatch; (4) exercise
  concurrency/rate/throttle/debounce and queue priority; (5) start a HumanTask,
  complete it through signal/approval, and verify Arrange once-timeout resume;
  (6) restart/reload during a run and confirm the pinned revision resumes
  without duplicate external side effects.

## Transparent startup window closure (2026-09-14)

- Deployment `transparent_startup_window_20260914` is complete. The main Tauri
  window now uses `transparent: true`, an alpha-zero background, and
  `shadow: false`; pre-shell `html`/`body`/`#app` and the splash are transparent,
  with only the centered Sunday mark painted.
- The full-screen veil/reveal/backdrop-filter path was removed. The normal
  workspace shell takes over after Vue is ready; click-through remains disabled.
  Normal and reduced-motion paths clear `aria-hidden` and clean animation state.
- Verification: focused startup tests 12/12; full UI contracts 610/610;
  full UI typecheck and desktop Vite build passed; `npm run build:app` generated
  `lamcore.exe`; config JSON/bootstrap syntax checks passed; Lam design audit
  83/0; scoped `git diff --check` passed with line-ending warnings only.
- No Tauri GUI/OS visual check was run; manual smoke remains user-owned. The
  worktree remains heavily dirty/uncommitted; no stage, commit, revert, cleanup,
  or attribution was performed, and no deployment-specific blocker is known.

## Workflow UI tabs, responsive catalog, and localized affordances closure (2026-09-14)

- Task ID/deployment: `workflow_ui_acceptance_closure_20260914`; closure state:
  `complete`.
- Outcome: Workflow View now supports multiple open workflow tabs with active,
  dirty, close, and unsaved-switch handling. The node catalog is
  `object_info`/schema-driven and responsive for sidebar and popover placement,
  with bounded scrolling, search, category filters, recent/favorite filters,
  keyboard activation, and mobile-sized controls. Chinese display names,
  descriptions, category labels, and accessible copy are presentation-only;
  canonical English type IDs, stored preferences, schema keys, and execution
  contracts remain unchanged. Node, catalog, inspector, queue, trigger, and
  canvas affordances use semantic Lucide icons instead of text glyphs.
- Evidence and verification: the Workflow UI contract surface is 5 test files
  / 49 tests passed (`workflow-canvas-parity.test.ts`,
  `workflow-node-contract.test.ts`, `workflow-policies-panel.test.ts`,
  `workflow-runtime-services.test.ts`, and `workflow-ui.test.ts`). Backend
  `core/tests/test_workflow_node_contract.py` passed 7 tests. Full
  `npm run typecheck` passed; the LamTools design audit covered 83 files with
  0 deviations; an independent Tester passed the final code review. No Tauri
  visual acceptance is claimed.
- Runtime handoff: the current Tauri development process/log chain was checked
  read-only with frontend Vite listening on `127.0.0.1:5173` and the backend on
  `127.0.0.1:49733`; this confirms readiness only, not visual behavior.
- Git handoff: Workflow UI source/test changes are the in-scope product work;
  this closure updates only `agent_docs/project_progress.md` and
  `agent_docs/latest_session_work.md` and leaves `project_diary.md` unchanged.
  Concurrent, unrelated startup/desktop changes remain un-attributed in
  `core/desktop/index.html`, `core/desktop/src-tauri/tauri.conf.json`,
  `core/ui/src/motion/startupSplash.ts`, and
  `core/ui/tests/startup-splash.test.ts`. Untracked temporary material remains
  in `artifacts/`, `core/core.db-wal`, and `core/core.db-shm`; none was touched.
  The working tree is heavily dirty and uncommitted; no stage, commit, revert,
  cleanup, or attribution was performed.
- Exact next entry point: the user opens the current Tauri Workflow surface and
  visually checks tabs, responsive catalog bounds, Chinese copy, and semantic
  icons, then runs a representative Workflow. If a defect appears, continue
  only from the Workflow UI files and their 5-file/49-test contract surface;
  do not reinterpret the process check as a visual pass.

## Artifact V2 closure (2026-09-14)

- Task ID/deployment: `artifact_v2_closure` /
  `artifact_system_v2_20260914`; closure state: `complete`.
- Outcome: SQLite Artifact V2 now provides stable per-project-path identity,
  immutable SHA-256-deduplicated revisions, legacy `.lam/artifact` manifest and
  historical projection-ID aliases, event-boundary ingestion, upload-as-input
  and generated/file-change outputs, soft remove/restore, revision
  preview/restore, and RPC/HTTP/CLI parity. Checkpoints retain Revision
  pointers; workspace rollback restores referenced revisions and soft-removes
  artifacts created after the target checkpoint. Project-scoped read/mutation
  boundaries were hardened in main review.
- UI outcome: the project 成果库 supports role/kind/status/search filters,
  history/restore, StagePane preview, and event-driven refresh. Conversation
  preview stacking remains intact; card and preview surfaces are opaque.
- Verification: backend focused final coverage passed 34 tests / 1 skipped;
  the broader related suite before the final narrow hardening passed 60 / 2
  skipped; focused UI coverage passed 3 files / 24 tests; full UI coverage
  passed 83 files / 624 tests; UI typecheck, `npm run build:app`, website
  build, and Python `compileall` passed; LamTools design audit passed 84 files
  / 0 deviations; scoped `git diff --check` passed with line-ending warnings.
  Existing Vite chunk/dynamic-import and aiosqlite datetime deprecation
  warnings are non-blocking.
- Limitation: no Tauri visual/runtime acceptance was run under the code-only
  scope; no visual pass is claimed. The repository remains heavily dirty and
  uncommitted. No stage, commit, revert, cleanup, or unrelated attribution was
  performed.
- Exact next entry point: user performs Tauri acceptance of the project 成果库,
  StagePane preview, conversation card opacity/stacking, event refresh, and
  revision restore/rollback; then exercises the matching CLI/RPC paths. If a
  defect appears, continue from the Artifact V2 backend/RPC/CLI contract and
  the project library/StagePane UI while preserving legacy aliases and
  project-scoped boundaries.

## Reasoning levels, sub-agent overrides, and Shallow visibility closure (2026-09-15)

- Deployment `reasoning_levels_xhigh_medium` is complete. Reasoning controls now
  use six canonical levels: `off`, `light`, `medium`, `high`, `xhigh`, and
  `max`; the `xh` alias normalizes to `xhigh`. Adapter profiles provide the
  complete preset surface and collapse unsupported levels to the nearest
  supported provider level. DeepSeek follows the verified mapping
  `off → disabled`, `light → low`, `medium/high/xhigh → high`, and
  `max → max`.
- Sub-agent dispatch accepts a per-call model and `reasoning_level`; omitted
  values inherit the parent agent settings. Existing narrow runner signatures
  remain compatible through optional-argument filtering. The UI no longer
  exposes the Shallow switch, while the underlying compatibility field, CLI,
  and legacy-session behavior remain available.
- Verification evidence: the independent Tester passed 108 Python tests,
  22 UI tests across 3 files, UI typecheck, 26 adapter preset checks,
  DeepSeek payload checks, inheritance/override and legacy-runner checks,
  Shallow-visibility checks, and `git diff --check`. The main agent additionally
  passed 185 Python tests (28 warnings), 22 UI tests, typecheck, 8 focused
  supplementary tests, and CLI `medium`/`xhigh` plus approval-resume
  `reasoning_level` continuation checks. No Tauri visual acceptance is claimed.
- Git handoff: the worktree remains heavily dirty and uncommitted, including
  unrelated and concurrent user changes. No stage, commit, revert, cleanup, or
  attribution was performed. Exact next entry point is to preserve the
  canonical six-level contract and provider mappings when adding adapters or
  changing delegation settings; use the focused reasoning/sub-agent/UI tests
  before broader validation.

## Startup optical-glass closure (2026-09-15)

- Deployment `startup_optical_glass_20260915` is complete. The startup layer in
  `core/desktop/index.html` now uses a low-gray tint, 8px blur, static localized
  dispersion/environment-color penetration, and a masked edge highlight.
- Native Acrylic tint in `core/desktop/src-tauri/src/main.rs` was reduced from
  alpha 32 to 18. These changes preserve the transparent first paint and avoid
  a full-screen opaque treatment.
- Verification: startup-focused tests 12/12; UI typecheck; desktop build;
  `cargo check --no-default-features` (existing dead_code warnings only); and
  LamTools design audit 84 files / 0 deviations all passed. No Tauri GUI/OS
  visual check was run; manual smoke remains user-owned.
- The worktree remains heavily dirty and uncommitted; no stage, commit, revert,
  cleanup, or attribution was performed. No deployment-specific blocker is
  known. Exact next entry point: user performs startup visual smoke in Tauri;
  if needed, inspect `index.html`, `main.rs`, and the startup splash contract.

## Asynchronous sub-agent lifecycle and messaging closure (2026-09-15)

- Deployment `subagent_async_lifecycle_ui` is complete. Sub-agents now use
  explicit `create`/`close` lifecycle operations and the stable `(parent,
  name)` key for reuse. `sub_agent_message(type, name, prompt)` validates the
  type and name before dispatch; each sub-agent has a dedicated `message`
  operation for sending a message to its parent. Dispatch returns immediately
  through the background supervisor, while a prompt sent to a busy sub-agent
  is injected before model sampling at the next `step`.
- Consider and execute agents have separate tool sets, neither can delegate
  another sub-agent, and both preserve the sub-agent message path. Late
  context appends the name, model, and summary after history as a final user
  message so provider requests retain a cacheable prefix. The UI displays
  `type name · model reasoning · elapsed`, keeps `consider` and `execute` as
  the only types, and the right rail lists current and historical sub-agents
  for the session with click-to-locate/expand and model/reasoning hover details.
- Verification: backend focused coverage passed 160 tests; default-agent and
  HTTP coverage passed 61 tests with 1 skip; UI coverage passed 28 tests; UI
  typecheck, Python `compileall`, LamTools design audit (84 files / 0
  violations), and scoped `git diff --check` passed. The independent model
  notes verification had already passed 216 related tests.
- The extended live-router suite retains one pre-existing pagination-resume
  failure unrelated to this deployment; it is not attributed to the
  sub-agent lifecycle changes. No Tauri visual/runtime acceptance is claimed.
- The worktree remains heavily dirty and uncommitted; no stage, commit,
  revert, cleanup, or unrelated attribution was performed. Exact next entry
  point is the focused supervisor/runner/toolbox/HTTP and sub-agent UI test
  surface when extending lifecycle, validation, or provider-tail behavior.

## Asynchronous sub-agent UI motion follow-up (2026-09-15)

- This is the motion completion follow-up for deployment
  `subagent_async_lifecycle_ui`. `CoreSubAgentPanel` now animates list add,
  remove, and reorder operations; rows without a source timeline can expand;
  remaining rows expose their expanded content; and status icons/labels stay
  synchronized with the projected state.
- `CoreSubAgentDialog` now has status, backdrop, and close micro-motion.
  `RightSidebarHost` transitions files/modules and uses a GSAP
  mount-preserving transition for runtime/artifacts, so switching those views
  does not remount their module instances. `LamToolsApp` locates a sub-agent
  run and finishes with a temporary highlight on the source heading.
- The reduced-motion path disables these animations and uses `scroll-behavior:
  auto`. Verification passed for the two focused Vitest files (33 tests),
  `npm run typecheck`, the LamTools design audit (84 files / 0 deviations),
  and scoped `git diff --check` (CRLF warnings only). No Tauri visual/runtime
  acceptance is claimed.
- The worktree remains heavily dirty and uncommitted; no stage, commit,
  revert, cleanup, or unrelated attribution was performed. Exact next entry
  point: user performs Tauri visual acceptance of sub-agent list/dialog/right-
  rail transitions, heading highlight, and reduced-motion behavior.

## Startup theme reveal follow-up (2026-09-15)

- The transparent startup glass remains unchanged. Once application preparation
  completes, the saved theme background now performs a single circular reveal:
  it expands from the actual Sunday mark center to a `farthest-corner` radius
  over 0.5s, then hands off to the staged main-shell fade-in.
- The reduced-motion path skips the reveal and uses a direct cross-fade. This
  follow-up preserves the low-cost static glass treatment and existing startup
  accessibility cleanup.
- Verification: startup-focused tests 12/12, UI typecheck, desktop build,
  LamTools design audit 84/0, and scoped `git diff --check` all passed. No
  Tauri visual verification was run; manual acceptance remains user-owned.

## Sunday ivory/graphite brand closure (2026-09-15)

- Task/deployment: `sunday_ivory_graphite_close` /
  `sunday_ivory_graphite_20260915`; closure state: `complete`.
- Outcome: Sunday’s light/dark themes now use flat ivory/graphite surfaces;
  main and composer share the same fill and solid border treatment. Exact old
  default themes migrate safely without overwriting user-customized themes.
  The logo was geometrically redrawn on a 1024 viewBox with a circular eye,
  round-cap wink, and wide smile, and synchronized across the Vue component,
  startup inline mark, source SVG assets, light/dark variants, ICO, ICNS, and
  legacy ICO copies.
- Verification: focused brand/theme/startup coverage passed 48 tests; UI
  typecheck/build, desktop Vite build, Tauri Rust build, LamTools audit
  (84 files / 0 deviations), and targeted `git diff --check` passed. ICO
  copies hash-match and the ICNS is valid.
- Limitation: the full UI suite passed 634/637; three existing
  `MessageView`/`chat-thread-process` failures are unrelated to this
  deployment. No Tauri visual validation was run under the code-only scope.
- Git handoff: the worktree remains heavily dirty and uncommitted; no stage,
  commit, revert, cleanup, or unrelated attribution was performed. Exact next
  entry point: when visual validation is requested, inspect the Sunday mark,
  title-bar placement, startup mark, and light/dark theme surfaces in Tauri;
  otherwise continue from the focused brand/theme tests and preserve the
  migration and asset-synchronization contracts.

## Sunday reference-image trace correction (2026-09-15)

- Task/deployment: `sunday_reference_icon_trace_archive` /
  `sunday_reference_icon_trace_20260915`; closure state: `complete`.
- The brand assets now follow the supplied reference artwork. The complete
  framed 1254×1254 light and dark PNGs are retained losslessly with SHA-256
  `43baa9ec01d1f571852e3dc86463b27e39a077ff43c49523d6bfb27f12768291`
  (dark) and
  `dba8a5508c294093fb3723bfe9417a04564bf797a2bf61121247464db0bd0087`
  (light). Application icon, title-bar icon, and startup surface use the
  complete framed artwork with explicit effective-theme switching; the
  standalone mark uses the measured tight 1024-viewBox vector geometry.
- The flat ivory/graphite palette is sampled into the theme tokens without
  gradients. ICO, ICNS, and legacy ICO copies were regenerated from the
  corrected application artwork. Startup fallback colors match the resolved
  backdrop, and Tauri development was fully restarted after the changes.
- Verification: focused Sunday coverage passed 47 tests; UI typecheck/build,
  desktop build, `cargo check`, LamTools design audit (84 files / 0
  deviations), and native icon/hash checks passed. The full UI suite passed
  637/640; the three failures are unrelated `chat-thread-process` label
  assertions. No Computer Use or visual GUI verification was performed.
- Runtime handoff: Tauri dev is running in session `66861`, frontend `5173`,
  backend `64257`. Visual acceptance of the startup, title-bar, and theme
  surfaces remains user-owned. The repository remains heavily dirty and
  uncommitted; unrelated and concurrent changes were preserved, with no
  stage, commit, revert, cleanup, or attribution performed.
- Exact next entry point: perform the user-owned Tauri visual smoke for both
  effective themes, checking the complete framed startup/title-bar icon,
  measured standalone mark, and flat ivory/graphite contrast; if a defect is
  found, continue from the synchronized SVG/PNG/ICO/ICNS asset set and the
  47-test brand contract.

## Sunday workbench frame and icon coverage closure (2026-09-15)

- Task ID/deployment: `archivist_sunday_workbench_frame_color_20260915` /
  `sunday_workbench_frame_color_20260915`; closure state: `complete`.
- User clarification: “背景” means the `backdrop` workbench/background-board /
  sidebar area, not the chat main surface. The final flat contract is light
  workbench `#D2D8E6`, chat main/composer `#FDFBF7`, and controls `#2E3138`
  with `#FBF7F0` text; dark workbench `#818289`, chat main/composer
  `#1B1D22`, and controls `#FBF7F0` with `#2E3138` text. No gradients are
  part of this contract.
- Exact migrations cover the older colorful, prior gray-control, and
  immediately previous inverted-control Sunday defaults. Any custom theme
  remains unchanged by migration.
- The raw 1254×1254 reference PNGs remain byte-identical. Centered 1120px
  crops resized with LANCZOS produce 1254px display masters at approximately
  90% meaningful alpha coverage; SundayLogo, startup splash, SVG icon wrappers,
  ICO, and ICNS use those normalized display masters. All three ICO copies are
  byte-identical with 16/24/32/48/64/256 sizes, and the ICNS is valid.
- Verification: independent scoped checks passed 54/54 focused UI tests, UI
  typecheck, desktop Vite build, `cargo check` (four existing dead-code
  warnings), and scoped `git diff --check`. The full UI suite was 645/648;
  three unrelated chat-thread-process assertions still expect obsolete
  `001 · name` labels instead of current `execute name` labels.
- Runtime handoff: fresh Tauri dev is active in exec session `28924`, frontend
  port `5173`, backend port `63144`; the backend became ready in 2108 ms and
  the desktop plugin host is ready. No Computer Use or GUI visual verification
  was performed, so visual acceptance remains user-owned.
- Git handoff: the repository remains heavily dirty and uncommitted. No
  stage, commit, revert, cleanup, or unrelated attribution was performed;
  concurrent and unrelated changes remain preserved. Exact next entry point:
  the user performs Tauri visual smoke in both themes, checking the corrected
  workbench frame color, complete enlarged icon in startup/title bar, chat
  surfaces, controls, and boundaries. If a defect appears, continue from the
  Sunday theme helpers, workspace styles, and normalized display-master asset
  set.

## Compaction keep-recent-step setting pause (2026-09-15)

- Task ID/deployment: `compaction_keep_steps_settings_closure` /
  `compression_keep_steps_settings_20260915`; closure state: `paused`.
- Current compaction is token-budgeted. Its structural planner retains whole
  semantic user-turn groups within the token target; no setting currently
  controls a count of retained “steps”. `LoopPolicy.max_history_messages` is
  a separate message-count safety trim, and the Goal evaluator’s
  `kernel_steps[-12:]` is only a fixed recent-step projection for evaluation.
  These three mechanisms must not be conflated.
- Implementation is paused pending the user’s definition of “Step” (for
  example, a semantic user-turn group versus a kernel loop iteration). No
  production edits or checks were performed for this request.
- Git disposition: read-only handoff; the repository remains heavily dirty
  and uncommitted. No stage, commit, revert, cleanup, or unrelated attribution
  was performed, and `project_diary.md` remains untouched.
- Exact next entry point: after the user defines “Step”, map that meaning to
  the compaction planner and settings contract, then implement and test the
  corresponding configurable retention behavior without changing the
  independent history trim or Goal projection semantics.

## Compaction retained-step setting implementation (2026-09-15)

- Task ID/deployment: `compaction_step_tail_backend` /
  `compaction_step_tail_20260915`; closure state: `complete`.
- The requested setting is implemented in the shared compaction path:
  `core.contextCompaction.retained_steps`, default `6`, validated to `1–100`.
  CoreSettings exposes the number field and save/refresh flow; the CLI provides
  `context-compaction show` and `context-compaction config --retained-steps`.
  A model Step is one `assistant` response plus its immediately following
  contiguous `tool` results. The planner initially protects the latest N Steps
  union the latest 20 user messages, then the exact token-budget fitter may
  drop the oldest protected units while preserving the newest user boundary.
  Automatic and manual `/compact` use this same policy; per-invocation and
  `LoopPolicy.compact_retained_steps` overrides remain available.
- Main-agent verification: the expanded backend set passed 341 tests with 28
  existing aiosqlite deprecation warnings; `compileall` passed. UI focused
  coverage (54), typecheck, and the LamTools design audit (84 files / 0
  deviations) passed. Scoped `git diff --check` passed with only LF/CRLF
  warnings. `ruff` was unavailable (`No module named ruff`).
- Independent Tester’s corrected regression surface passed 247 tests in
  35.85 seconds. It confirmed union retention, exact-budget shrinkage,
  assistant+tool atomic dropping, the newest-user minimum boundary, and the
  shared automatic/manual path. The earlier nine kernel compatibility failures
  were fixed and are not a remaining limitation; the planner/fitter stage
  documentation was synchronized.
- Git disposition: the repository remains heavily dirty and uncommitted;
  unrelated and concurrent changes were preserved. No stage, commit, revert,
  cleanup, or attribution was performed. `project_diary.md` was left to the
  main agent and was not edited by this closure.
- Exact next entry point: future changes should begin with the focused
  compaction/step-tail/kernel contract and preserve the setting namespace,
  Step grouping, 20-user union, newest-user boundary, and exact-budget fitter
  behavior. Visual Tauri acceptance was not part of this code-focused closure.

## Input composer token alignment closure (2026-09-15)

- Task/deployment: `input_token_alignment_archive` /
  `input_token_alignment_20260915`; closure state: `complete`.
- All active Core UI text-like input boxes and textareas now derive their
  background, border, text, caret, and placeholder colors from composer tokens.
  Transparent title inputs remain the explicit exception and stay area-local.
  Selects, buttons, badges, and native non-text inputs continue to use the
  control-area tokens. `.agents/skills/lam-design-spec/SKILL.md` is synchronized,
  and `core/ui/tests/input-composer-tokens.test.ts` scans app/components/workflow/styles.
- Verification: executor affected tests passed 60/60; focused contract passed
  4/4; UI typecheck passed; the LamTools design audit found 0 violations in 84
  files; and the scoped diff check passed. Independent Tester PASS followed
  scanner hardening: focused 4/4 passed and the static scan found no applicable
  residue. The full UI suite recorded 651 passes and 3 unrelated failures in
  `tests/chat-thread-process.test.ts` expecting obsolete sub-agent labels.
- No Computer Use or Tauri visual verification was run. The pre-existing
  `CoreGoalStrip.vue` cancel-button composer coloring is outside this input-box
  scope. The worktree remains heavily dirty and uncommitted; no stage, commit,
  revert, cleanup, or broad attribution was performed. Exact next entry point:
  when extending text-entry surfaces or token rules, begin with the composer
  token contract and `input-composer-tokens.test.ts` scanner, preserving the
  transparent title-input exception and control-area semantics.

## Composer action-button color closure (2026-09-15)

- Task/deployment: `composer_action_button_archive` /
  `composer_action_button_colors_20260915`; closure state: `complete`.
- `CoreSendStopButton` send and stop outer surfaces now use
  `--theme-composer-text`; the paper-plane, stop glyph, and motion trail use
  `--theme-composer-background`. Runtime GSAP color resolution no longer reads
  control tokens or red. Existing motion, accessibility, and hit-area behavior
  is preserved. The canonical lam-design-spec records this explicit composer
  action-button exception.
- Verification: executor focused coverage passed 3 files / 8 tests; UI
  typecheck, LamTools design audit (84 files / 0 violations), and scoped diff
  check passed. Independent Tester PASS covered 3 files / 22 tests, typecheck,
  design audit 84/0, scoped diff check, and a temporary non-reduced GSAP
  send-to-stop-to-send runtime test; the temporary test was removed.
- Limitation: jsdom cannot compute pseudo-element `currentColor`; source
  inheritance was verified. No Tauri or pixel visual run was performed. The
  worktree remains heavily dirty and uncommitted; no stage, commit, revert,
  cleanup, or broad attribution was performed. Exact next entry point: when
  changing send/stop visuals, start with `CoreSendStopButton`, its composer
  exception in lam-design-spec, and the focused action-button contract while
  retaining the existing motion/accessibility/hit-area behavior.

## Title input transparency closure (2026-09-15)

- Task/deployment: `title_input_transparency_archive` /
  `title_input_transparency_20260915`; closure state: `complete`.
- Root cause: the shared text-input selector accumulated specificity through
  many `:not(...)` clauses and overrode transparent inline title-editor classes.
  The global text-input recipe now sits in zero-specificity `:where(...)`,
  preserving composer colors, native exclusions, and the select-control recipe.
  Seven inline/pure-text title exceptions reliably override to border 0,
  transparent background, and local text/caret. Ordinary form values named
  `title` or `name` remain composer input boxes.
- Verification: executor coverage passed 5 files / 62 focused tests; UI
  typecheck, LamTools design audit (84 files / 0 violations), and scoped diff
  checks passed. Independent Tester PASS covered 8 files / 109 tests,
  typecheck, scoped diff check, and selector-specificity/source review.
- Limitation: this is a static CSS contract; no rendered Tauri CSSOM or visual
  run was performed. One discarded invalid explicit Vitest-config attempt had
  no product impact. The worktree remains heavily dirty and uncommitted; no
  stage, commit, revert, cleanup, or broad attribution was performed. Exact
  next entry point: when adding title-like controls, begin with the zero-
  specificity global recipe and the seven explicit title exceptions, keeping
  ordinary `title`/`name` form fields on composer tokens.

## Context compaction full-summary and recent-user retention closure (2026-09-15)

- Task ID/deployment: `compaction_full_summary_recent_users_20260915`; closure
  state: `complete`.
- Outcome: `core.contextCompaction.retained_steps` now defaults to `0` and
  accepts `0–100`. Zero summarizes all non-prefix history. Every compaction
  appends a program-owned `## Recent user messages` section containing the
  newest 20 user instructions verbatim, numbered `1.`, `2.`, and so on.
- Retention policy: positive Step settings protect recent Step units (one
  assistant response plus its contiguous tool results) together with the
  recent-user suffix. The exact-budget fitter drops the oldest retained Steps,
  then the oldest numbered user entries, while preserving the newest user
  instruction unless that instruction alone cannot fit. Repeated compaction
  strips the prior generated section before rebuilding it; text/content blocks
  from multimodal instructions are retained while media-only blocks are
  omitted.
- Surface coverage: automatic and manual `/compact` share the policy, and the
  CLI, settings RPC, and CoreSettings UI accept `0`.
- Exact files changed: `core/src/lamtools_core/app/command_execution.py`,
  `core/src/lamtools_core/app/default_agent.py`, `core/src/lamtools_core/cli.py`,
  `core/src/lamtools_core/config/operations.py`,
  `core/src/lamtools_core/context_compaction/__init__.py`,
  `core/src/lamtools_core/context_compaction/controller.py`,
  `core/src/lamtools_core/context_compaction/fitter.py`,
  `core/src/lamtools_core/context_compaction/formatting.py`,
  `core/src/lamtools_core/context_compaction/models.py`,
  `core/src/lamtools_core/context_compaction/planner.py`,
  `core/src/lamtools_core/context_compaction_budget.py`,
  `core/src/lamtools_core/kernel/loop.py`,
  `core/src/lamtools_core/kernel/policy.py`,
  `core/tests/test_context_compaction.py`,
  `core/tests/test_context_compaction_step_tail.py`, and
  `core/ui/src/components/CoreSettings.vue`.
- Verification: main backend regression passed 348 tests; the independent
  Tester passed 209 tests; CoreSettings Vitest passed 15 tests; UI typecheck,
  `compileall`, LamTools design audit (84 files / 0 deviations), and scoped
  `git diff --check` passed. No Tauri visual/runtime check was run.
- Current position and next milestone: the code and contracts are complete;
  future compaction changes should begin with the focused compaction/step-tail
  tests and preserve the zero default, 20-user suffix, newest-user boundary,
  and exact-budget ordering.

## Sub-agent lifecycle event copy and mailbox projection closure (2026-09-15)

- This is the event-surface follow-up to `subagent_async_lifecycle_ui`.
  Lifecycle and mailbox rows now use explicit Chinese copy and matching Lucide
  icons: `UserRoundPlus` for `创建了 {name} · {model} {reasoning}`, `Power`
  for `启用了 {name} · {model} {reasoning}`, `PowerOff` for `关闭了 {name}`,
  `Send` for `向 {name} 发送了消息`, and `Inbox` for `收到了 {name} 的消息`.
- Backend operation results distinguish `created`, `enabled`, `closed`, and
  `message_sent`. A child-to-parent guidance event projects as the
  `sub_agent_receive` tool with `message_received` metadata, while asynchronous
  lifecycle operations remain ordinary tool rows. UI metadata is kept out of
  the model history; the model receives only the original message body.
- Verification: the UI closure surface passed 116 tests; the backend closure
  surface passed 249 tests; and UI typecheck passed. No Tauri visual/runtime
  acceptance is claimed under the code-only scope.
- The worktree remains heavily dirty and uncommitted. Existing and concurrent
  changes were preserved; no stage, commit, revert, cleanup, attribution, or
  `project_diary.md` edit was performed. Exact next entry point: if event
  presentation changes again, begin with `MessageView`, the runtime projection,
  and lifecycle/mailbox metadata contracts while retaining the five copy/icon
  mappings and body-only model history.

## Context compaction full-summary bugfix continuation (2026-09-16)

- Task ID/deployment: `compaction_full_summary_recent_users_20260915`; closure
  state: `complete`.
- Verified fixes: same-run later Steps retain the generated summary in memory
  while durable rows filter it; manual zero-tail compaction uses valid
  high-water/compacted sequence values without falling back to full history;
  repeated compaction rolls the prior structured `recent_user_messages`
  section together with new raw users into the newest 20. Internal request-local
  users are excluded. Typed media fields are excluded while media-only users
  receive a placeholder.
- Formatting and policy: the visible numbered original-user suffix remains
  intact. Ambiguous heading/number/newline, CRLF, and special `splitlines()`
  cases carry an invisible length footer for exact round-trip reconstruction.
  Automatic/manual policy overrides remain equivalent.
- Verification: main focused coverage passed 289 tests; independent focused
  coverage passed 215 tests plus a 95-test compaction trio; 61 targeted tests
  and 20,000 randomized round-trips passed; `compileall` and scoped
  `git diff --check` passed. The full Core run passed 1,965 tests and skipped 2;
  six unrelated failures remain in tool counts, artifact DB, and live-resume
  coverage. No Tauri run was performed.
- Current position and next milestone: the compaction behavior is complete and
  ready for follow-up from the focused compaction/round-trip contracts. Preserve
  the durable-row filter, sequence high-water handling, newest-20 roll-forward,
  media/request-local exclusions, visible suffix, and invisible exact-length
  footer when extending it.

## Sub-agent runtime integration repair closure (2026-09-16)

- Deployment `fix_subagent_runtime_integration`; closure state: `complete`.
- The sub-agent contract now requires explicit `action/type/name/model/
  reasoning_level` for create/close operations and `type/name/prompt` for
  `sub_agent_message`; the dedicated child `message(message)` channel is
  auto-allowed. `consider` and `execute` retain isolated tool sets and cannot
  recursively delegate. Child runs are asynchronous, use `name` as the stable
  reuse key, and deduplicate across runs/invocations; child item IDs carry
  sub-session, run, and invocation identity.
- Child-to-parent messages use persistent mailbox and live guidance, injected
  at the next Step. Parent/child run, Step, call, and source anchors refresh on
  message and close. Approval resume restores child identity, toolbox, and
  request-local context; child events remain attached to the active
  `sub_agent_message` item. Runtime states distinguish running, idle, paused,
  closed, interrupted, and error.
- Reasoning aliases `xh`/`XH` and `Medium` normalize across schema, CLI, and
  runtime, with DeepSeek multi-level-to-fewer-level mapping covered. Model
  notes enter model request prompts. Name, model, and summary are appended
  after history as request-local context to preserve cache prefixes.
- The right rail merges current and historical sub-agents, supports click to
  locate/expand/highlight, hover model/reasoning details, status ordering, and
  reduced-motion-safe transitions. Rows use `类型 名 · 模型 思考强度 · 耗时`;
  lifecycle copy/icons cover create, enable, close, send, and receive states.
  Shallow remains hidden as a UI entry while active indicators remain valid.
- Verification: main-agent backend expansion passed 205 tests; the full UI
  suite passed 86 files / 665 tests; `npm run typecheck`, `npm run build:app`,
  Python `compileall`, the LamTools design audit (84 files / 0 deviations),
  and scoped `git diff --check` passed. Build emitted only existing
  chunk/dynamic-import warnings and diff check only line-ending warnings.
  Independent Tester verdict: PASS (backend 152 tests, UI 665 tests,
  typecheck, compileall, and diff check passed). No Tauri visual acceptance
  was run, per the code-only scope.
- The worktree remains heavily dirty and uncommitted. No stage, commit,
  revert, cleanup, or unrelated attribution was performed. Exact next entry
  point: begin with the sub-agent supervisor/runner contracts, runtime
  projection, and right-rail projection tests when extending this behavior;
  preserve asynchronous mailbox delivery, child identity on approval resume,
  late context placement, and the five lifecycle copy/icon mappings.

## Context compaction final fix delta (2026-09-16)

- Task ID/deployment: `compaction_full_summary_recent_users_20260915`; closure
  state: `complete`.
- Consecutive manual compactions now union prior `compacted_history_seqs`
  while preserving positive retained Steps. Steps removed by the exact-budget
  fitter are marked and excluded from same-run memory, durable history, and
  the next run across both manual and automatic paths.
- Final verification: main focused coverage passed 291 tests; independent
  targeted coverage passed; the previously recorded full Core result remains
  `1965 passed, 2 skipped`, with six unrelated failures in tool-count,
  artifact-DB, and live-resume tests. No Tauri run was performed.
- Next milestone: any compaction follow-up should start with the focused
  sequence-union and fitter-removal contracts and preserve the zero-tail,
  newest-20 suffix, and positive-Step retention guarantees.

## Sub-agent role assignments closure (2026-09-16)

- The role-assignment contract now has a global `role_assignments` baseline.
  Project settings merge by trimmed, case-folded `task_type`: same-name
  project entries override the global entry and new project entries append.
  Each entry carries `task_type`, `type`, `model`, `reasoning_min`, and
  `reasoning_max`; `type` is restricted to `consider` or `execute`, and
  reasoning levels are `off/light/medium/high/xhigh/max` with `xh` normalized
  to `xhigh` and no `shallow` level.
- Shared UI covers both global and project assignments and persists canonical
  `model_id` values. RPC responses expose `local`, `effective`, and
  `inherited` state. CLI parity provides `subagent roles show/set/delete`.
  The generated system-prompt role section is placed immediately after the
  guide section.
- Verification: backend 77 tests passed; frontend 37 tests passed;
  typecheck, Python `compileall`, LamTools design audit (84 files / 0
  deviations), and `git diff --check` passed. No Tauri visual acceptance was
  performed.

## Office renderer contract planning handoff (2026-09-16)

- Deployment `office_renderer_contract_20260916` is paused after a read-only
  audit and planning pass. Core currently has no durable, unified Office
  renderer implementation.
- The proposed contract is a unified `office render` CLI/service with an
  agent-authored canonical data manifest. Rendering must fail closed: validate
  every table cell and chart series/category/value binding against the manifest
  before producing Office or PDF output; a mismatch returns structured error
  details and stops rendering.
- The renderer should use LibreOffice Office-to-PDF conversion with an isolated
  profile and no auto-install, declare PyMuPDF/python-pptx/openpyxl packaging,
  produce PDF/PNG previews, and report text-overlap diagnostics containing
  page, element, text, bounding boxes, and the conflicting element.
- No production, Skill, test, build, Tauri, Computer Use, or Git mutations were
  performed in this paused closure. Implementation awaits user confirmation of
  the proposed contract.

## Sub-agent delegation strategy closure (2026-09-16)

- Deployment `subagent_delegation_strategy` is complete. Delegation strategy
  supports `forbidden`, `low`, `medium`, and `high`, with `medium` as the
  default. A global baseline is inherited by projects; a project can explicitly
  override it, while `null`/`unset` removes the local key and restores
  inheritance.
- RPC exposes `local`, `effective`, `global`, and `inherited` strategy state.
  CLI parity is `subagent strategy show/set/unset`. A project with blank
  `work_root` is rejected, and the same validation is applied to the unified
  guide/roles configuration. The shared editor supports all four levels and a
  project-level “inherit global” choice, with independent saves.
- Prompt ordering is `guide → strategy (priority declaration) → roles`; the
  high-strategy responsibility text is complete. In `CoreBaseAgentKit` and the
  unified `_build_core_runtime_toolbox`, `forbidden` hides/disables
  `sub_agent` and `sub_agent_message`. Direct calls and approval resumes that
  switch to `forbidden` are blocked, while already-running historical agents
  remain open. Explicit user/operator lifecycle RPCs are outside the main-agent
  strategy boundary.
- Verification: backend prompt/CLI 83 passed; config-default tests 5 passed;
  approval-focused tests 2 passed and approval group 5 passed; blank-root CLI
  9 passed and blank-root RPC 4 passed; frontend 3 files / 40 tests passed;
  typecheck, `compileall`, LamTools design audit (84 files / 0 deviations),
  and `git diff --check` passed. Tester accepted with no P0/P1/P2 findings.
  No Tauri or Computer Use validation was performed.

## Title-bar sidebar toggle and narrow-screen closure (2026-09-16)

- Task ID/deployment: `titlebar_sidebar_controls_archive` /
  `titlebar_sidebar_controls_20260916`; closure state: `complete`.
- WorkspaceShell now owns left/right pin state. Both pin changes, including
  responsive auto-unpin, are emitted and synchronized into LamToolsApp; TitleBar
  only requests the toggles. At max-width 640px, only the two sidebar controls
  are hidden; device/account and native window controls remain available.
- Verification: focused coverage 24/24; full UI contract 87 files / 674 tests;
  UI typecheck passed; LamTools design audit covered 84 files with 0 violations;
  affected-file `git diff --check` was clean.
- Limitation: code-only verification; no Tauri visual/runtime check was run.
- Git handoff: read-only; the heavily dirty, uncommitted tree was preserved.
  No stage, commit, revert, cleanup, or unrelated attribution was performed.
  Exact next entry point: use the WorkspaceShell/LamToolsApp/TitleBar pin
  synchronization contracts and responsive sidebar-control tests for follow-up.

## Unified Office renderer implementation (2026-09-16)

- Deployment `office_renderer_implementation_20260916` originally placed the
  Skill-bundle companion runtime below `_shared`; the standard packaging repair
  recorded later in this document supersedes that location. The former
  `lamtools_core.office` package remains removed.
- The runtime keeps the manifest-first canonical dataset contract. Supported
  bindings are `pptx_table`, `pptx_chart`, `docx_table`, `xlsx_range`, and
  `xlsx_chart`; every data-bearing target is checked item by item before
  rendering. Data or structure failures are fail-closed and produce no
  Office/PDF/PNG output. Windows `auto` selects Microsoft Office COM first and
  falls back to LibreOffice through `soffice.com`; successful rendering also
  provides PDF/PNG previews and structured text-overlap diagnostics.
- CLI entry points are `office validate` and `office render`. Source,
  simulated-`_MEIPASS`, and wheel-install runtime location checks passed; the
  wheel contains the companion runtime and no `__pycache__`. The PyInstaller
  spec static-path check passed, but a complete PyInstaller build was not run.
- Verification: final main regression coverage passed 157 tests and
  independent acceptance passed 133 tests. A real Microsoft Office COM CLI
  smoke run passed. Deliberate data mismatch and text overlap cases retained
  exit codes 2 and 4 with structured diagnostics.
- The implementation handoff does not claim pixel-level human visual
  acceptance. The repository remains concurrently dirty; this documentation
  update does not stage, commit, revert, clean, or attribute unrelated work.

## Office Skill standard packaging repair (2026-09-16)

- Deployment `office_skill_standard_packaging_20260916` moved the renderer from
  the nonstandard `_shared` tree into the standard explicit-only
  `core/skills/office-renderer/{SKILL.md,agents/,scripts/}` package. All ten
  authoring Skills now include `agents/openai.yaml` and report version 0.2.0 beta.
- Office authoring guidance now uses the working-directory-independent
  `py -3.14 -m lamtools_core.cli office ...` entry point and explicitly forbids
  PATH probing followed by bypass. The bundled `scripts/office.py` remains a
  standalone fallback and emits structured JSON failures.
- `SkillRegistry` now honors `policy.allow_implicit_invocation` and invalidates
  its cache when `agents/openai.yaml` changes. The renderer remains explicitly
  loadable but stays out of automatic Skill prompt indexes.
- Verification: 11/11 Skills passed `quick_validate.py`; Office/Skill/runtime
  focused tests passed 117; Core CLI tests passed 59. Scoped `git diff --check`
  passed with line-ending warnings only. Wheel build was not rerun because
  `hatchling` is unavailable in the local Python environments; static force-
  include and PyInstaller recursive Skill packaging remain in place.

## Turn artifact discovery and artifact-card redesign (2026-09-16)

- Status: complete, pending user GUI visual acceptance.
- Final Agent replies now serve as a validated fallback artifact source for
  command/Office-generated files that did not emit ToolArtifact metadata.
- “本轮产出” and the project成果库 receive the same registered files; missing,
  external, incomplete-stream, and child-agent paths are excluded.
- Artifact cards now use neutral theme surfaces and Lucide file-type icons.
  Code/text opens in internal plain text, with CLI parity via `artifact preview`.
- Follow-up GUI defects are closed: enlargement is hover-only and the code/text
  modal is body-teleported with a neutral window-relative backdrop.
- Evidence: 8 backend artifact tests, 93 focused UI tests, UI typecheck, and the
  84-file design audit all passed. No Tauri visual check or git commit was run.

## Office Skill direct execution prompt repair (2026-09-16)

- Status: complete; behavioral GUI retest remains user-owned.
- Office renderer guidance now gives one minimal final-artifact path and forbids
  source inspection, environment/backend probes, scratch Office experiments,
  and renderer re-certification during ordinary document work.
- Whole-document visual claims now require every generated page/sheet preview
  to be viewed once. Representative-page checks must be labeled sampled, and
  automated `visual=passed` is explicitly separated from full preview review.
- Verification: prompt-contract and renderer suites passed 31 tests; all 11
  Office Skills passed the Skill Creator validator under UTF-8; scoped diff
  check passed with line-ending warnings only. No GUI/Office production rerun
  was performed.

## Direct transport transient-disconnect repair and 16-2 process audit (2026-09-17)

- Direct transport close errors now retain WebSocket code, reason, and clean-close
  state. UI reporting delays only transport disconnects for two seconds and
  cancels the toast on successful reconnect; persistent disconnects remain
  visible and non-transport errors remain immediate.
- The live router skips sync-journal SQLite lookups for transient `seq=0` model
  deltas, removing a confirmed queue-pressure path to `1013 Event stream
  overflow`.
- Verification: focused UI coverage passed 42 tests; the full UI suite passed
  683 tests across 87 files; typecheck, production build, and the 84-file design
  audit passed. Focused backend coverage passed; the broader live-router/hub run
  had one pre-existing unrelated resume-page-cursor failure.
- `16-2-test` completed in about 607 seconds with 48 LLM calls, 82 unique tool
  calls, and 2 failed commands. The weighted provider cache hit rate was 96.05%.
  The new prompt contract was loaded, but the Agent still performed forbidden
  environment/install probing and a scratch formula-cache experiment. It also
  changed and rerendered the workbook after viewing its previews, then claimed a
  full review without reopening the updated pages. Product quality was not
  assessed in this audit.

## Optional Office readiness check (2026-09-17)

- The former prompt-level prohibition list was replaced with a short positive
  path. Ordinary work can start directly; when environment readiness is
  uncertain, the Agent may run `py -3.14 -m lamtools_core.cli office check`
  once and continue after `Office 应用已就绪 · Test Passed 3/3`.
- The check creates disposable minimal DOCX, XLSX, and PPTX sources and performs
  real PDF conversions through the configured Microsoft Office/LibreOffice
  backend. Temporary inputs and outputs are removed automatically.
- The same `check` command is available through the bundled Skill script. Both
  Core CLI and standalone runs passed 3/3 on the current machine. Focused
  renderer/CLI/prompt tests passed 33 tests, and all 11 Office Skills passed the
  standard Skill validator under UTF-8.

## Model/provider and tool-mode settings entry cleanup (2026-09-17)

- Task ID/deployment: `model_provider_page_entry_refresh_archive` /
  `model_provider_page_entry_refresh_20260917`; closure state: `complete`.
- Active goal and overall progress: simplify the model/provider and tool-mode
  settings surfaces by removing redundant top statistics and duplicate add
  actions while keeping clear local entry points. The implementation is
  complete in the shared Core UI.
- Current position: `CoreSettings` retains its title/subtitle, provider-rail
  footer and provider empty-state CTA, plus the model-section header and model
  empty-state CTA. `CoreLoadToolsEditor` retains title/subtitle,
  dirty/refresh/save controls, and mode-rail footer and empty-state CTA while
  removing the loadtools overview metrics and duplicate top add action.
- Verification: focused CoreSettings coverage passed 16 tests; combined focused
  coverage passed 19 tests; typecheck, build, LamTools audit (84 files / 0
  deviations), and scoped diff checks passed. Independent Tester also passed
  focused 19/19, full UI 88 files / 687 tests, typecheck, `npm run build`, and
  Git diff checks. Build output contained only existing dynamic-import warnings.
- Limitation and next milestone: no Tauri/Computer Use visual validation was
  run. The Tester noted older unrelated dead CSS in CoreSettings, with no
  blocker. Next milestone is user/Tauri visual acceptance if required.

## Website self-hosted distribution implementation handoff (2026-09-17)

- Task ID/deployment: `website_self_hosted_distribution_closure` /
  `website_self_hosted_distribution_20260917`; implementation state:
  `complete`; server-distribution follow-up remains pending user confirmation.
- Active goal/progress: the public website preview is implemented and tracked
  in `website/`. `website/src/App.vue` now contains SiteNav/Hero/Showcase/
  Features/Download/SiteFooter; the Architecture section was removed to keep
  the page focused. Showcase mounts the complete real `LamToolsApp` through a
  typed in-memory `MockTransport`, with zero real API/XHR/WebSocket calls.
- Design/result: ivory-white and graphite-black themes are synchronized, with
  only a restrained fine rainbow spectrum used for emphasis. Downloads default
  to the same-origin path `/downloads/Sunday-latest-x64-setup.exe`.
- Preview containment repair: the former inline mount let Core's
  `position:fixed`/`100vw`/`100vh`, settings cards, and composer resolve
  against the host page. It now uses a same-origin `preview.html` iframe with
  an independent viewport while still directly importing the complete
  `LamToolsApp` and `MockTransport`; the parent page no longer loads Core's
  global CSS. Vite's multi-page build emits both `index.html` and
  `preview.html`.
- Theme synchronization uses a fixed iframe URL and same-origin
  `postMessage`; the iframe remounts the real `LamToolsApp` so theme changes do
  not depend on parent-page scrolling or inline Core state.
- Verification: the independent Tester passed `npm run build` and
  `scripts/verify-preview.mjs` at 1440px and 390px. The checks reported
  `pageScrollY=0`, no horizontal page overflow, and no console errors.
- Extended containment verification also passed at 2277x1362, 1440x1000, and
  390x844, covering shell/main/composer/settings containment, no Core overlay
  leakage into the parent page, and no API/XHR/WebSocket calls, console
  errors, or horizontal overflow.
- Final independent Tester verification passed in the production preview on
  port 5200 (`verify-preview` exit 0): both graphite and ivory reported
  `pageScrollY=0`; the settings rect was
  `107.7/74.6/1330.3/798.5`, fully inside the `1438x819` viewport; and there
  were no API/XHR/WebSocket calls, console errors, or page errors.
- Distribution boundary: server hosting, DNS, update-source migration, and
  deployment have not been executed. The current GitHub-based update/release
  path remains until the user confirms the canonical HTTPS domain and the
  upload/deployment method. The installer naming remains
  `Sunday_<version>_x64-setup.exe`.
- Next milestone: after confirmation, deploy the tracked website and
  versioned installer/manifest assets to the owned server, configure DNS and
  same-origin download/update URLs, then verify the live website and desktop
  update check. Do not treat the completed local preview as evidence of live
  hosting.
- Git handoff: preserve unrelated dirty/untracked work; this documentation
  correction changes only the two assigned documents. No stage, commit,
  revert, cleanup, or `project_diary.md` edit was performed here.
