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

## Card overlay close pointer guard handoff

- Task/deployment: `card_close_pointer_guard`; closure state: `complete`.
- Outcome: overlay card dismissal now requires the same pointer's
  `pointerdown` and `pointerup` to both occur outside the card. The shared
  implementation is `core/ui/src/composables/useOutsidePointerDismiss.ts`.
- Material changes: all existing `@click.self` / `@mousedown.self` card
  overlay close points use the pointerdown/pointerup guard. Nested and
  Teleport-rendered overlays are isolated through their overlay subtrees.
  Coverage includes CoreSettings, CorePluginsEditor, CoreProjectSettings,
  PluginsShell, SearchShell, CoreArrangeManager, ThemeEditor, MessageView,
  CoreProjectCreate, CoreProjectPicker, and FolderBrowserDialog.
- Verification: `npm run test:contract` passed with 71 files / 494 tests;
  `npm run typecheck` passed; `npm run build` passed; LamTools design-spec
  audit passed with 71 files / 0 deviations; `git diff --check` passed.
- Verification limitation/blocker: Tauri/CUA manual observation was attempted
  and the prescribed retry/reset flow was exhausted, but it was blocked by
  `nodeRepl.fetch request failed`. No manual-observation pass is claimed.
- Working-tree disposition: existing uncommitted user changes remain present;
  the closure did not commit, revert, or clean them. The pointer-guard source
  and test files are also uncommitted in the current working tree.
- Pending work: no pointer-guard deployment work remains. Real-device
  LAN/Relay pairing and reconnect validation, plus the Docker image build when
  Docker Hub access is available, remain project-level follow-up items.
- Evidence: `core/ui/src/composables/useOutsidePointerDismiss.ts`, the covered
  component sources listed above, `core/ui/tests/outside-pointer-dismiss.test.ts`,
  and the command/audit results recorded here. Exact next entry point: inspect
  the current uncommitted working tree, then continue with real-device
  LAN/Relay pairing and reconnect validation when credentials and devices are
  available.

## Office Skills GUI 财报复测（2026-09-11）

- 会话：`#4124c504`；项目：
  `.tmp/office-skills-evaluation/2026-09-11-gui-retest/02-microsoft-fy25q4`。
- 详细报告：`core/docs/office-skills-gui-retest-2026-09-11.md`。
- 事件证据：`data/core.db` 的 `core_app_events`，thread id
  `4124c50498f5441d83b377dc16fa0e48`；`turn/accepted` 到完成状态为
  1241.224 秒，1261 条事件。
- 结果：XLSX/PPTX/PDF/摘要均生成；证据 350/350 命中，工作簿重算 28
  项通过、5 项记录、0 个错误单元格，PPTX/PDF 结构和数字交叉核对通过。
- 过程评分：直接性/规划 6/10，失败控制 5/10，速度/效率 3/10，指令
  遵循 7/10，综合 5.5/10。
- 运行量：118 个 LLM 步骤、140 个逻辑工具调用、8 个工具失败、123
  个 usage 回合；输入 15,543,306、缓存 15,260,800、输出 140,028，
  加权缓存命中率 98.18%，最大单次输入 243,853/256,000 Token。
- 视觉结论：程序化报告称 0 越界/0 重叠，但人工查看预览发现 p02、p03、
  p04、p06、p07、p09 仍有标题、表格或文字区域冲突；不得把几何/文本
  校验当作视觉通过。
- GUI 刷新结论：事件在停止前按顺序落库，未重现旧订阅队列阻塞的后端证据；
  仍需以人工首条正文、重试和 Stop 响应时间记录完成 GUI 验收。
- 下一步：先修生成前的标题/表格/页脚安全区和视觉通道前置判断，再收敛
  批量生成步骤与重复状态事件；不要先扩大 Office Skill 范围。

## Auto-follow and process-card compacting handoff

- Task/deployment: `auto_follow_process_cards_20260911`; closure state:
  `complete`.
- Outcome: auto-follow uses `scrollHeight - clientHeight`, clears stale
  programmatic intent after upward input, and only frame-corrects after actual
  growth. Older history auto-loads within 160px of the top with an in-flight
  guard and height-delta viewport anchoring; the manual load control is gone.
- Material changes: the thread scrollbar reaches the main chat edge with 5%
  resting / 12% hover thumb opacity. Live thinking/tool process remains visible
  while each message-level card defaults collapsed to a responsive three-line
  semantic-tail caption. Captions snapshot every 2s with fade transition;
  operation/state uses Lucide icons; running uses shimmer plus restrained
  breathing and completed is static. Pointer leave schedules 5s card/group
  collapse and re-entry cancels it. Adjacent reasoning and ordinary tool parts
  fold into one group while pending approvals remain auto-exposed.
- Final copy/interaction correction: reasoning titles preserve the last semantic
  sentence. Tool titles use action + target: `load_skill` renders “加载技能 ·
  技能名”, writes/edits render the filename, and commands render the concrete
  command; title indentation is unified. Clicking a title reveals 3 lines of
  body content, clicking the body expands a 7-line body viewport, and mouseleave
  collapses it after 5s. The 3/7-line limit applies only to card body content,
  not tool outer frames or file/terminal bars; `.thread
  .reasoning-body.process-card-body--*` raises specificity for reasoning bodies.
- Older-history pagination hides its skeleton, prefetches at two viewports or at
  least 640px ahead, fetches 50 items per batch, and anchors correction to the
  first visible message DOM node.
- Verification: focused 4-file coverage passed 104/104 tests; final
  `npm run test:contract` passed 71 files / 500 tests; `npm run typecheck` and
  `npm run build` passed; Lam design audit passed 71 files / 0 deviations;
  `git diff --check` passed with only LF/CRLF warnings.
- Final correction verification: the focused suite passed 96/96; contract suite
  passed 71 files / 502 tests; typecheck, build, and the 71-file/0-deviation
  design audit passed; `git diff --check` reported only newline warnings.
- Limitation: no Tauri/manual UI run was performed, per the user request to
  verify code correctness only; no visual/manual pass is claimed.
- Working-tree disposition: pre-existing and concurrent uncommitted changes
  remain; this closure changed only the assigned documentation and did not
  commit, revert, or clean production/test work.
- Evidence: `docs/core-ui-streaming-perf.md`,
  `core/ui/src/composables/useCoreAutoFollowScroll.ts`,
  `core/ui/src/app/LamToolsApp.vue`, `core/ui/src/components/ChatThread.vue`,
  `core/ui/src/components/MessageView.vue`, `core/ui/src/styles/layout.css`,
  and the focused/contract test results above.
- Pending work/blockers: no deployment-specific blocker is known. Project-level
  follow-up remains the Office visual-quality work, real-device LAN/Relay
  pairing/reconnect validation, and the Docker image build when Docker Hub
  access is available. Exact next entry point: inspect the current uncommitted
  tree, then continue with those project-level milestones.

## User-message history paging handoff

- Task/deployment: `user_message_history_paging_20260912`; closure state:
  `complete`.
- Root cause: `_character_page_snapshot` paged only `core.item_order`, then
  filtered top-level items by Core-selected IDs, making persisted `userMessage`
  rows unreachable in large turns.
- Fix: unify sequence-ordered top/Core paging, include causally preceding
  user-message anchors for selected assistant turns, and widen the frontend
  tail window when a boundary lands on an assistant.
- Evidence: real thread `4124c50498f5441d83b377dc16fa0e48` now yields an initial
  200KB page containing its user ID, 27 latest Core items, `has_more=true`, and
  `character_count=186390`.
- Regression coverage: `core/tests/test_core_sync.py` and
  `core/ui/tests/core-workbench-projection-window.test.ts`.
- Verification: `pytest tests/test_core_sync.py -q` passed 7 tests; focused UI
  coverage passed 2 files / 32 tests; full UI Vitest passed 71 files / 503
  tests; `npm run typecheck` and `npm run build` passed; touched-file
  `git diff --check` passed with LF/CRLF warnings only.
- Limitation: a broader pre-existing backend subset had 89 passed / 1 unrelated
  failure in `test_core_live_resume_response_exposes_page_cursor` because it
  expects events although resume defaults to include a snapshot. This is not
  attributed to the paging patch. No Tauri/manual UI run was performed per the
  user request.
- Working-tree disposition: existing uncommitted changes remain; this closure
  changed only the assigned documentation and did not commit, revert, or clean
  production/test work. No deployment-specific blocker is known.
- Exact next entry point: inspect the current uncommitted tree, then continue
  with the existing project-level Office visual-quality, real-device LAN/Relay,
  and Docker Hub follow-up milestones.

## Unified message attachment deck handoff

- Task ID: `artifact_deck_closure`; deployment:
  `core_artifact_attachment_deck`; closure state: `complete`.
- Outcome: `core/ui/src/components/MessageAttachmentDeck.vue` is the shared,
  panel-free deck for message-local files. Assistant output is limited to
  `image` and `file_change` and omits `file_read`; uploaded attachments appear
  below user messages. Output expands left-to-right and uploads right-to-left.
- Material behavior: compact overlapping cards expand on hover, focus, or
  click; click pins one preview. Deck width is measured with `ResizeObserver`
  to derive page size, with side arrows for paging. Text/code/config/document
  excerpts, image thumbnails, typed file icons, GSAP Flip motion, restrained
  back easing, selected scale/z-layer elevation, and reduced-motion fallback
  are implemented. `MessageView.vue` owns placement and output filtering;
  shared app/workbench projection sources carry uploaded attachment data.
- Verification: focused 3 files / 16 tests passed; full
  `npm run test:contract` passed 72 files / 512 tests; `npm run typecheck` and
  `npm run build` passed; LamTools design audit passed 72 files / 0 deviations.
  `git diff --check` on tracked touched files reported only LF-to-CRLF
  warnings, with no whitespace-error text.
- Limitation: Tauri/CUA manual observation was attempted twice, including once
  after CUA reset. Desktop Vite was correctly on `127.0.0.1:5173`, but both
  attempts failed with `nodeRepl.fetch request failed`; no manual UI pass is
  claimed.
- Read-only Git handoff: deployment files are the new
  `core/ui/src/components/MessageAttachmentDeck.vue`, its
  `core/ui/src/components/MessageView.vue` integration, shared app/workbench
  projection updates, and the focused attachment-deck/artifact-panel tests.
  The working tree was already heavily dirty and remains uncommitted; this
  closure preserved unrelated/concurrent changes and performed no commit,
  revert, or cleanup.
- Pending work/blockers: no deployment-specific blocker is known. Exact next
  entry point is to inspect the current uncommitted tree, then continue the
  project-level Office visual-quality work, real-device LAN/Relay
  pairing/reconnect validation, and Docker image build when Docker Hub access
  is available.

## Web search plugin repair handoff

- Task ID/deployment: `web_search_plugin_repair_closure` /
  `web_search_plugin_repair_20260912`; closure state: `complete`.
- Outcome/root causes: bundled/current `consider` loadtools omitted
  `web_search`; real default Baidu was blocked by wappass captcha; Bing's
  parser returned no result structure; and the schema used `duckduckgo` while
  runtime accepted `ddg`.
- Material changes: bundled `consider` includes `web_search`; the search
  factory falls back across configured providers in `ddg` then `bing` order,
  keeps strict explicit-provider behavior, records attempted-provider/error
  metadata, and makes `duckduckgo` a compatibility alias with `ddg` canonical
  in schema. Local runtime configs now expose `web_search` and default to DDG.
- Verification: 99 targeted tests passed (`test_web_tools.py`,
  `test_bundled_plugins.py`, `test_config_defaults.py`, `test_default_toolbox.py`,
  `test_core_default_agent.py`); current `consider` config reports
  `web_search_visible=True`; real default search for `LamTools GitHub` returned
  `status=ok` via `ddg` with 3 results; scoped `git diff --check` passed with
  newline warnings only.
- Git disposition: read-only inspection identified tracked deployment files
  in the loadtools/default-agent/websearch-schema/default-toolbox/search-factory/
  sub-agent-runner paths and their related config, toolbox, agent, HTTP-agent,
  and web-tool tests. `core/.lam/core/config/loadtools.jsonc` and
  `data/core-agent/plugins/websearch.jsonc` are local runtime config changes
  likely ignored by Git. The tree remains heavily dirty and uncommitted; no
  commit, revert, or cleanup was performed.
- Material gaps/risks: no deployment-specific blocker is known. Provider
  availability remains network-dependent; the next entry point is to inspect
  the current uncommitted tree, then continue the project-level Office
  visual-quality, real-device LAN/Relay, and Docker Hub milestones.

## Baidu official API decision handoff

- Task ID/deployment: `baidu_search_official_api_decision` /
  `baidu_search_plugin_repair_20260912`; closure state: `paused` pending user
  choice. This is separate from the completed
  `web_search_plugin_repair_20260912` deployment.
- Outcome: no production code changed in this deployment; the main agent added
  one durable diary lesson. Direct probes of `https://www.baidu.com/s`
  (standard HTML and `tn=json`), `https://m.baidu.com/s` (`word` and `wd`),
  HTTP/HTTPS, cookie warmup, and `trust_env` true/false all returned 302
  redirects to `wappass.baidu.com/static/captcha`; no proxy environment
  variables were active.
- Official source: Baidu docs at
  `https://cloud.baidu.com/doc/qianfan-api/s/Wmbq4z7e5` specify
  `POST https://qianfan.baidubce.com/v2/ai_search/web_search`, API-key auth,
  references output, and 1,500 free monthly calls with daily allocation.
- Verification limitation: the official authenticated API was not integrated
  or exercised because the user decision and key are not yet available.
- Exact next entry point: ask whether to replace the anonymous Baidu provider
  with this official authenticated API; if approved, obtain and configure a
  key. The working tree remains heavily dirty and uncommitted; unrelated and
  concurrent changes were preserved.

## Web search proxy configuration handoff

- Task ID/deployment: `web_search_proxy_config_closure` /
  `web_search_proxy_config_20260912`; closure state: `complete`.
- Outcome: websearch schema, UI, and backend accept optional port-only
  `proxy_port`; the UI persists it through the existing websearch config RPC.
  DuckDuckGo derives `http://127.0.0.1:<port>` when configured and connects
  directly otherwise. Local runtime config is `7890`. Generic `plugin config
  get/set` already provides the matching CLI capability.
- Verification: 119 backend-related tests passed; focused UI coverage passed
  1/1; full UI coverage passed 74 files / 518 tests; UI typecheck and build
  passed; LamTools design audit passed 72 files / 0 deviations; a real DDG
  request through configured port 7890 returned `status=ok` with 3 results.
  Touched-source `git diff --check` had newline warnings only.
- Limitation: no Tauri visual/manual observation was performed, so no manual UI
  pass is claimed.
- Read-only Git handoff: touched deployment source/tests are
  `core/src/lamtools_core/plugins/bundled/websearch/config/schema.jsonc`,
  `core/src/lamtools_core/tool/search/duckduckgo.py`,
  `core/src/lamtools_core/tool/search/factory.py`,
  `core/ui/src/components/CoreWebSearchEditor.vue`,
  `core/tests/test_web_tools.py`, and
  `core/ui/tests/core-web-search-editor.test.ts`. The working tree remains
  dirty and uncommitted; unrelated and concurrent changes were preserved. Exact
  next entry point: use the existing UI or generic plugin config CLI to adjust
  `proxy_port` if the local proxy port changes.

## Artifact system redesign handoff

- Task ID/deployment: `artifact_system_redesign_closure` /
  `artifact_system_redesign_20260912`; closure state: `paused`.
- Outcome: diagnosis and a proposed redesign direction are recorded, but the
  deployment stopped before implementation because project rules require user
  consensus. No production code or tests changed. The main agent added one
  lasting diary lesson; this deployment changed only the assigned documentation
  in addition to that diary bullet.
- Verified diagnosis: the project registry uses per-artifact JSON UUID
  manifests at `.lam/artifact`; runtime projection derives `artifact-{sha1}`
  IDs for tool artifacts without IDs; only image-generation and upload paths
  register durable manifests, while ordinary `file_change` events do not.
  `data/core.db` contains 3,842 events with top-level artifacts and 3,842
  refs: 2,210 `command_output`, 1,072 `file_change`, 495 `file_read`, 47
  `web_fetch_content`, 17 `web_search_result`, and 1 `test_result`. The
  `.lam/artifact` directory contains only two manifests, both deleted
  user-upload images.
- UI evidence: `ArtifactPanel.vue` is mounted beneath runtime status in the
  292px right drawer, fetches only on mount/project change/manual refresh, and
  owns a separate preview. The uncommitted `MessageAttachmentDeck.vue` is
  message-local and filters output presentation; it does not solve durable
  artifact identity.
- Proposed direction, explicitly pending user approval: one durable Artifact
  fact model; distinct output/input/evidence roles; contextual message deck
  plus project-wide 成果库; StagePane as preview/open surface; live RPC/event
  updates; CLI parity; and migration/compatibility for existing manifests and
  events.
- Verification and limitation: Tauri dev was running on `127.0.0.1:5173`, but
  two CUA attempts, including a reset/retry, failed with
  `nodeRepl.fetch request failed`. No visual/manual pass is claimed. Only
  read-only evidence review and documentation consistency checks were done;
  no production test suite was run for this paused deployment.
- Git disposition: the working tree was already heavily dirty and remains
  uncommitted. This deployment preserved unrelated/concurrent changes and made
  no production or test-file edits.
- Blocker and exact next entry point: user approval or revision of the proposed
  direction is required. After approval, inspect the existing artifact
  schemas/RPC and event projection, define the durable contract and migration
  compatibility first, then implement live updates, CLI parity, and the
  message-deck/project-library/StagePane surfaces. Evidence references:
  `data/core.db`, `.lam/artifact`, `core/ui/src/components/ArtifactPanel.vue`,
  and `core/ui/src/components/MessageAttachmentDeck.vue`.

## Sunday branding and visual implementation handoff

- Task ID/deployment: `sunday_brand_plan_closure` /
  `sunday_ai_brand_20260912`; state: `complete`. The canonical product name
  is `Sunday`; `AI software` is only a subdued secondary label/tagline. No
  translated product name is displayed.
- Completed theme and metadata: shared `SUNDAY_DARK_THEME`/
  `SUNDAY_LIGHT_THEME` defaults plus the `sunday` preset; validated project
  `icon_key`/`color_key` metadata with backend persistence and shared picker /
  icon rendering.
- Completed owned brand assets: `core/ui/src/assets/sunday-mark.svg`,
  `sunday-app-icon.svg`, `core/ui/src/components/SundayLogo.vue`, and the
  desktop/UI/Tauri ICO assets. The app icon uses the requested gradient mark
  on a warm-white rounded-square background with a soft shadow.
- `TitleBar.vue` places the mark at the far left, then strong `Sunday` and the
  weak `AI software` label. Document, native main-window, and plugin-host
  titles are Sunday-facing. The desktop left sidebar is 232px; the mobile
  drawer keeps the separate `min(86vw, 320px)` rule.
- Project settings save name and icon/color metadata immediately on
  change/blur/enter or selection; the picker and settings use the same
  validated project-visual contract.
- Packaging uses the repository-owned Inno chain:
  `core/desktop/installer/Sunday.iss` and `build-installer.ps1`, orchestrated
  by the package script. Tauri uses `--no-bundle`; the stable upgrade/runtime
  boundary remains `lamcore.exe`, `lamcore-backend/LamCore.exe`, and
  `com.lamtools.lamcore`, with legacy installation migration retained.
- Startup first-paint bootstrap resolves the saved/system Sunday theme before
  stylesheet paint, preventing the dark-preference ~80ms light flash. Tauri
  verification covered dark preference at 80/480/740ms, explicit light with a
  dark system, and reduced-motion. The motion handoff is translucent veil →
  centered bare logo → theme background expanding from the logo center → shell
  components fading in; reduced-motion removes clip-path motion while keeping
  the accessible hand-off. Empty sessions render an animated Sunday
  logo/greeting.
- Final gates passed: UI 75 files / 540 tests, typecheck, UI build, desktop
  build, design audit 76 files / 0 deviations, and `git diff --check`.
  Final Inno package:
  `E:\LamTools\core\desktop\src-tauri\target\release\bundle\inno\Sunday_0.3.2_x64-setup.exe`
  (56,460,297 bytes; SHA-256
  `238EB54CDBD4A55C76735F767A28864F8316CA70F9248F8952B3CE87083E096A`).
  Installation to `E:\setuptest\0.3.2` verified the main process at PID
  `34412` and backend at PID `39536`, with both executable paths correct.
- Evidence: the files listed above, `core/ui/src/motion/startupSplash.ts`,
  `core/desktop/index.html`, `core/ui/tests/startup-splash.test.ts`,
  `core/ui/src/styles/variables.css`, `core/ui/tests/workspace-shell.test.ts`,
  `core/desktop/installer/Sunday.iss`, the final package, and the installed
  `E:\setuptest\0.3.2` process check.
- Pending work/blockers: no Sunday deployment blocker is known. The project
  next entry point is the existing Artifact redesign consensus, followed by
  Office visual-quality, real-device LAN/Relay pairing/reconnect, and Docker
  image validation when Docker Hub access is available.

## Modular right-sidebar closure

- Task ID/deployment: `sidebar_closure_handoff` /
  `modular_sidebar_20260913`; closure state: `complete`.
- Outcome: Core/Sunday now has a modular, pluggable right rail. A roughly
  320px single-column separator stack is hosted on one high-transparency,
  subtly blurred, theme-token-driven liquid-glass surface. The host owns
  ordering, visibility, collapse, and per-project persistence. Built-ins are
  Runtime, Resources, Web Search engine/health, RAG status/search, and
  Artifacts; Three.js/runtime visualization is deferred.
- Material backend changes: plugin widget manifests and validation, scoped
  `plugin.widget.list/get/invoke` operations, ownership/schema checks,
  dangerous-action confirmation, mutation idempotency, and CLI
  `plugin widget list/show/action` access. Web Search exposes snapshot and
  real-health operations. Relevant implementation areas are
  `core/src/lamtools_core/plugins/{models.py,registry.py,operations.py,cli.py}`,
  the bundled Web Search backend/manifest, and the app-server HTTP exposure.
- Material frontend changes: `core/ui/src/right-sidebar/types.ts`,
  `useRightSidebarLayout.ts`, the `RightSidebarHost`, module/editor/renderer,
  Runtime/Web Search/RAG components, trusted plugin loader registry and
  `PluginModeHost`, plus `LamToolsApp`/`WorkspaceShell` integration and
  Artifact embedding. Declarative widgets render bounded snapshots; trusted
  Vue components are registered in-process, and raw plugin markup is not
  evaluated. With no RAG plugin installed, the UI says unavailable and only
  attempts legacy search after a user action; no fabricated counts or event
  push are used.
- Verification: frontend focused coverage passed 25/25; full UI coverage
  passed 77 files / 553 tests; UI typecheck and `build:app` passed with only
  existing chunk/dynamic-import warnings. Backend plugin/lifecycle/workflow
  coverage passed 64, CLI/assembly 76, widget 7/7, Web Search 10/10, and the
  combined target passed 42 with 1 skip; HTTP exposure passed. Full pytest
  separately passed 1740 with 2 skips. The two unrelated live-resume failures
  reproduce alone: `test_core_app_server_client_runs_live_operation_matrix_against_real_websocket_server`
  and `test_core_live_resume_response_exposes_page_cursor` (expected 500, got
  0); neither uses the sidebar call path. `git diff --check` passed.
- Limitation: the user explicitly stopped visual/Tauri interaction; no
  visual/manual UI pass is claimed. The working tree remains heavily dirty
  and uncommitted; this closure preserved unrelated/concurrent changes and
  made no commit, revert, or cleanup. Archivist changed only the assigned
  durable documentation.
- Evidence: `core/ui/src/components/RightSidebarHost.vue`,
  `RightSidebarLayoutEditor.vue`, `RightSidebarModule.vue`,
  `RightSidebarWidgetRenderer.vue`, `RightSidebarRuntimeStatus.vue`,
  `RightSidebarWebSearch.vue`, `RightSidebarRag.vue`,
  `core/ui/src/right-sidebar/types.ts`,
  `core/ui/src/composables/useRightSidebarLayout.ts`,
  `core/tests/test_plugin_widgets.py`,
  `core/ui/tests/right-sidebar.test.ts`, and the related plugin/UI tests.
- Pending work/blockers: no deployment-specific blocker is known. Exact next
  entry point: inspect the current uncommitted tree, then continue the
  existing Artifact redesign consensus/contract work, Office visual quality,
  real-device LAN/Relay pairing/reconnect, and Docker Hub image validation.

## ComfyUI 工作流与 Agent 对齐规划

- Task ID/deployment: `workflow_alignment_planning_closure` /
  `comfyui_workflow_agent_alignment_20260913`; closure state: `paused`。
  本轮是 Heavy 规划/研究部署，未修改生产代码或测试；项目规则要求在实现
  前先取得用户对完整方案的共识。
- ComfyUI 研究结论：对齐范围应覆盖能力、架构和交互范式，不是像素级视觉
  克隆。ComfyUI 前后端为 GPL-3.0，LamTools 为 MIT，因此后续依据公开规范
  独立实现并沿用 Sunday/LamTools 设计语言，不复制其代码。
- 当前 Workflow 证据：`core/src/lamtools_core/plugins/bundled/workflow/`
  已有后端 store/runtime/operations/watcher/CLI/build-tools 与 Vue Flow UI。
  现有 UI 支持五类节点、条件边、自动保存、全图/单节点/从节点运行和 Agent
  自然语言改图；但步进每次从第一个节点重新执行，运行结果/节点输出/错误/尝试
  次数未形成稳定投影，后端 `completed/failed` 与前端 `done/error` 不一致，右
  栏 Teleport 目标缺失，并缺少运行输入表单、历史、缓存、Undo/Redo、多选、
  分组、reroute、模板、导入导出及 Schema 驱动节点注册。自动保存没有 revision/
  CAS，端口重命名也不会同步修复连线。
- 建议的稳定关系：Workflow 独立拥有文档、存储、校验、队列、运行时、缓存、
  历史和事件；Agent 只经显式适配器与 `ExecutionContext` 参与——辅助编辑图、
  作为 Agent 节点执行器，或将 Workflow 作为工具调用。两者不共享隐式会话状态
  或彼此注入内部运行对象，以同时保证独立性与配合性。
- UI 方向：将工作流 UI 拆为 `model/commands/document/canvas/catalog/inspector/
  runtime/resources/services/tests`，复用 `RightSidebarHost`、`ArtifactPanel`、
  `StagePane`、共享菜单、`AutoTextarea`、`CoreConfirmDialog`；移除 `WfSelect`，
  统一 `UiSelect`。运行态、历史/缓存、撤销重做、输入和导入导出应成为一等
  工作流体验，而非 Agent 会话的附属面板。
- 待用户决策的四项边界：
  1. 采用行为/交互对齐，还是要求像素级复制；
  2. 是否保留现有 Workflow 文件格式并提供迁移；
  3. 是否允许插件注册任意节点类型；
  4. 缓存是否限制为声明的纯函数/确定性节点（建议命令、脚本、Agent 默认不缓存）。
- Verification/limitations：本轮完成代码、架构、ComfyUI 公开规范和 UI 的只读
  审计；没有生产测试、构建或 Tauri 手工验收，也没有宣称通过。工作树仍重度
  dirty 且未提交，未执行 stage、commit、revert 或 cleanup；所有既有及并发用户
  改动均保留。
- Exact next entry point：用户确认四项边界后，先定义 Workflow/Agent 适配器、
  `ExecutionContext`、节点 Schema、运行事件/缓存契约和旧格式迁移，再按后端
  核心、CLI parity、画布/目录/检查器、运行历史与 UI 收尾分阶段实现。证据入口：
  `core/src/lamtools_core/plugins/bundled/workflow/`、
  `core/tests/test_workflow_*.py`、
  `core/src/lamtools_core/plugins/bundled/workflow/ui/`，以及本次 Heavy 审计记录。

## ComfyUI 工作流与 Agent 对齐实现闭环

- Task ID/deployment: `workflow_rebuild_closure` /
  `comfyui_workflow_rebuild_20260913`; state: `complete`。本节取代上方
  `comfyui_workflow_agent_alignment_20260913` 的 paused 规划状态。
- Outcome: 独立实现已覆盖节点注册表与 Schema 节点、DAG/部分执行、持久续跑、
  声明纯节点缓存、队列/历史/取消、CLI/RPC parity、旧格式兼容，以及
  revision/CAS、并发原子锁和保存冲突处理。Workflow 通过
  `WorkflowExecutionContext` 与 Model/Agent/插件适配器协作，权限、取消和
  事件链路保持显式边界。
- Agent-tool verification: 真实
  `KernelSubAgentRunner→CoreBaseAgentKit→workflow-tool` 链路保留附件、runtime
  snapshot、环境、能力、权限、lineage 和 workflow stack；外部 stack 含当前
  workflow 时立即拒绝，内部 child context 合法。
- UI outcome: 节点目录、输入表单、运行结果、队列/历史/缓存、导入导出、模板、
  右栏、Undo/Redo、多选、分组、reroute、注释、系统剪贴板、重连、对齐/分布、
  标签页和移动端布局已实现；统一 Sunday/LamTools 设计体系，删除重复
  `WfSelect` 并使用共享 `UiSelect`。
- Verification: backend workflow subset `py -3.14 -m pytest -q tests -k workflow`
  = 74 passed / 1689 deselected；UI typecheck PASS；`npm run test:contract` =
  80 files / 573 tests PASS；`npm run build:app` PASS（仅既有
  chunk/dynamic-import warnings）；`git diff --check` PASS（仅 CRLF warnings）。
  Full backend `py -3.14 -m pytest -q tests` = 1759 passed / 2 skipped / 2 failed。
  两项失败为部署前已存在且与 Workflow 无关的 live-resume 空 events：
  `test_core_live_client_e2e::test_core_app_server_client_runs_live_operation_matrix_against_real_websocket_server`
  和 `test_core_live_router::test_core_live_resume_response_exposes_page_cursor`。
- Limitation/disposition: 用户负责视觉验收；未启动 Tauri、浏览器或人工视觉检查，
  不宣称视觉通过。工作树重度 dirty 且未提交；未 commit、cleanup、revert、stage
  或归因，并保留所有既有/并发用户改动。Archivist 本次仅更新本文件和
  `agent_docs/project_progress.md`。
- Exact next entry point: 用户先做视觉验收；发现问题时仅修复 Workflow UI；若无
  问题，另起独立范围部署处理上述无关 live-resume 失败。证据入口为
  `core/src/lamtools_core/plugins/bundled/workflow/`、
  `core/tests/test_workflow_*.py`、Workflow UI 目录及本次验证命令输出。
## Workflow 数据模型研究闭环

- Task ID/deployment: `workflow_data_model_research_closure` /
  `workflow_data_model_alignment_20260913`; state: `paused`，等待用户确认
  Sunday-native V2 或 ComfyUI JSON canonical。该部署只有规划/研究和文档交接，
  未修改生产代码或测试；前一节 `workflow_rebuild_closure` 的实现闭环保持原样。
- 研究快照（官方 ComfyUI backend `0.35.0`、frontend `1.55.7`）：持久化工作流
  是 LiteGraph editor document，而非直接执行 payload。v0.4 为数组 links；v1
  同时包含 state counters、object links、groups、reroutes、config、extra、
  subgraph definitions，以及节点 geometry/flags/mode/order/slots/properties/
  widgets_values。执行 prompt 单独以 node-id keyed objects 表示，节点含
  `class_type` 与 `inputs`，引用为上游 node/output slot pair；muted/virtual
  editor nodes 被省略。后端从输出递归校验 required inputs、types、combos 和
  cycles。
- 运行时边界为 `/prompt`、`/queue`、`/history`、`/object_info` 与 WebSocket；
  queue tuple 实际字段可能不同于 OpenAPI，集成层应做版本探测而不是硬编码。
  官方研究入口：
  `https://github.com/Comfy-Org/ComfyUI_frontend/blob/main/src/platform/workflow/validation/schemas/workflowSchema.ts`、
  `https://github.com/Comfy-Org/ComfyUI_frontend/blob/main/src/utils/executionUtil.ts`、
  `https://github.com/Comfy-Org/ComfyUI/blob/master/server.py`、
  `https://github.com/Comfy-Org/ComfyUI/blob/master/execution.py`、
  `https://github.com/Comfy-Org/ComfyUI/blob/master/openapi.yaml`。两仓库均为
  GPL-3.0-only；Sunday 只采用概念/规范行为，不复制实现。
- 本地审计确认的 Sunday 弱点：`WorkflowDef` 混合执行和画布位置；config/types
  为自由形态；edges 与派生/持久 map 的含义重复；平铺完整 JSON 不利于 Agent
  语义理解。建议 canonical 采用 Sunday-native V2，编译到独立 execution prompt，
  再生成紧凑 model semantic view，并提供 ComfyUI import/export adapters；原始
  LiteGraph JSON 不作为内部 canonical。
- Verification/limitations：只读完成官方规范、本地代码/测试目录和 Git 状态核对；
  未运行生产测试、构建、浏览器或 Tauri 手工检查，不宣称实现或视觉通过。工作树
  重度 dirty、未提交；未执行 stage、commit、revert、cleanup 或归因，保留所有
  既有及并发用户改动。Evidence: `core/src/lamtools_core/plugins/bundled/workflow/`
  及 `core/tests/test_workflow_*.py`。
- Exact next entry point：向用户确认 canonical 选择；若采纳 Sunday-native V2，
  先定义 V2 文档、执行 prompt 编译器、semantic view、ComfyUI 迁移适配器和
  compatibility tests，再进入生产实现。

## Hide project header hash handoff

- Task ID/deployment：`hide_project_hash_setting_closure` /
  `hide_project_hash_setting`；closure state：`paused`，pending user
  clarification/consensus。
- Verified request context：截图中的 `#4124c504` 是当前 session/thread ID
  的前 8 位，不是 project ID。常规标题栏路径是 `LamToolsApp` 挂载的
  `CoreSessionTitleEditor`；Workflow 同样复用该组件。
- Verified settings boundary：`CoreProjectSettings` 已收到 `project.id`，
  但没有 `activeSessionId`。因此仍有两个待选解释：（1）把当前 session ID
  移到项目设置；（2）在项目设置显示 project ID。
- Outcome/limitation：这是只读规划交接；没有修改任何 production/test 文件，
  也没有运行测试或构建。证据仅核对
  `core/ui/src/components/CoreSessionTitleEditor.vue`、
  `core/ui/src/app/LamToolsApp.vue`、
  `core/ui/src/components/CoreProjectSettings.vue`、
  `core/ui/tests/core-session-title-editor.test.ts`、
  `core/ui/tests/core-project-components.test.ts`。
- Git disposition：工作树原已重度 dirty、未提交；本部署未执行 commit、
  stage、revert 或 cleanup，既有及并发改动均保留。
- Exact next entry point：用户确认两种解释之一后，从上述组件的标识传递边界
  开始实施选定方案，更新对应测试，再运行聚焦验证；在确认前不改代码。

## Right-sidebar motion closure

- Task ID/deployment: `sidebar_motion_closure` /
  `right_sidebar_motion_20260913`; closure state: `complete`.
- Outcome: the modular right-sidebar motion pass is complete and independently
  verified; runtime visualization is unchanged. `RightSidebarHost.vue` now
  scopes lifecycle-safe GSAP editor motion and uses `TransitionGroup` for
  module enter/leave/reorder. `RightSidebarModule.vue` retains body content
  with `v-show`, animates collapse through 200ms grid/opacity, applies
  `aria-hidden`/`inert` safety, shows drag lift/drop feedback, and cleans up
  animation/listener state. `workspace-shell.css` defines 240ms enter / 180ms
  exit, an instant reduced-motion fallback, the exact 2px main gap, rounded
  left corners only, and square right corners.
- Verification: focused right-sidebar coverage passed 25/25; full UI coverage
  passed 553/553; `npm run typecheck` and `npm run build:app` passed; design
  audit passed 83 files / 0 violations; `git diff --check` passed. Earlier
  full-backend evidence remains 1740 passed / 2 skipped, with unrelated
  failures in `test_core_app_server_client_runs_live_operation_matrix_against_real_websocket_server`
  and `test_core_live_resume_response_exposes_page_cursor`.
- Limitation: no Tauri runtime interaction or visual/manual UI pass was
  performed. The working tree remains heavily dirty and uncommitted; this
  closure preserved unrelated/concurrent changes and performed no commit,
  stage, revert, cleanup, or attribution. Archivist changed only the assigned
  durable documentation.
- Evidence: `core/ui/src/components/RightSidebarHost.vue`,
  `core/ui/src/components/RightSidebarModule.vue`,
  `core/ui/src/styles/workspace-shell.css`,
  `core/ui/tests/right-sidebar.test.ts`, and the existing sidebar host/layout
  contract files.
- Pending work/blockers: no deployment-specific blocker is known. Exact next
  entry point: when available, perform Tauri visual/manual validation of
  collapse, reorder, drag feedback, geometry, and reduced-motion states;
  otherwise inspect the current uncommitted tree and continue the existing
  Artifact consensus, Office visual-quality, real-device LAN/Relay, and Docker
  image milestones.

## ComfyUI 工作流最终核验补充

- Task ID: `workflow_rebuild_closure`；这是最终核验补充，取代同日 Workflow
  数据模型研究的 paused 规划状态。用户此前记录的 UI 收尾一并完成：全幅画布、
  中键平移、右键菜单、紧凑 workflow composer、保存 icon-only、exposure 移入
  设置，以及 ComfyUI 节点稳定端口。
- Contract/UI boundary: V2 UI 使用 canonical RPC，并保留兼容回退；模型边界
  对齐 ComfyUI v1 state/object links、0.4 reroutes、max id、strict one-hop
  引用。扩展字段隔离在 `canvas.comfyui`，不进入 Sunday-native canonical
  文档。
- Final verification: UI typecheck PASS；UI contract tests 583/583 PASS；
  `build:app` PASS；design audit 83/0；Workflow focused tests 92/92。后端
  full suite 为 1777 passed / 2 skipped / 2 failed，两个失败是已知且与
  Workflow 无关的 live-resume 空 events 问题。
- Runtime handoff: Tauri 观察环境已 ready，Vite `5173`、backend `58273`。
  这不是视觉通过声明；用户负责视觉验收。本次只更新本文件与
  `agent_docs/project_progress.md`，未修改代码，未 stage/commit/cleanup/
  revert 或归因；工作树仍重度 dirty。
- Exact next entry point: 用户在 Tauri 中完成 Workflow 视觉验收；发现问题时
  仅修复 Workflow UI，并保持 canonical RPC 与兼容回退边界。

## Workflow UI 工具栏收尾

- Task ID: `workflow_rebuild_closure`。最终 UI 收尾已验证：工具栏固定画布左侧
  纵向排列，按钮为 icon-only 并带 `title`，工具栏可纵向滚动；Vue Flow
  Controls 已移除，运行控制条上移以避开紧凑 workflow composer。
- 变更文件：`WorkflowCanvas.vue`、`WorkflowControlBar.vue`、
  `workflow-canvas-parity.test.ts`。
- Verification: 定向 Vitest 18/18、UI typecheck、`npm run build:app`、设计
  审计 0 偏离、`git diff --check` 均通过；Tauri Vite `5173` 与 backend
  `58273` 均 HTTP 200。
- Limitation: 视觉验收归用户负责；本次不宣称视觉通过。未修改业务代码之外
  的内容，未覆盖或回退他人改动。

## Session ID 项目设置与标题栏收尾

- Task ID/deployment：`move_session_id_to_project_settings_closure` /
  `move_session_id_to_project_settings`；closure state：`complete`。本节明确
  supersedes the earlier paused `hide_project_hash_setting` planning note。
- Outcome：普通 `LamToolsApp` header 已移除 session ID 前 8 位；
  `CoreProjectSettings` 仅在当前活动 session 属于所选项目时显示 `#` 加前 8
  位，并支持复制完整 ID 与复制成功反馈。Workflow 和
  `CoreSessionTitleEditor` 行为保持不变。
- Desktop layout：ordinary title row uses `data-session-header`、token-derived
  75px band，以及 token-derived `-44px` inset reclaim，位于原生标题栏下沿与
  divider 之间居中；mobile 与 Workflow 不受影响。
- Evidence：`core/ui/src/app/LamToolsApp.vue`、
  `core/ui/src/components/CoreProjectSettings.vue`、
  `core/ui/src/styles/layout.css`、
  `core/ui/tests/core-project-components.test.ts`、
  `core/ui/tests/package-boundary-contract.test.ts`。
- Verification：focused 2 files / 27 tests passed；full UI contract 80 files /
  588 passed；typecheck passed；`build:app` passed with existing
  chunk/dynamic-import warnings；Lam audit 83 files / 0 violations；scoped
  `git diff --check` passed。Independent tester inspected built CSS and accepted
  after one rejected cascade defect was repaired。
- Limitation/decision：用户明确停止 Tauri automation；没有 runtime/manual visual
  pass 声明。工作树仍 heavily dirty/uncommitted；未执行 commit、stage、revert、
  cleanup 或归因，保留既有及并发改动。
- Exact next entry point：若需要视觉确认，用户在 Tauri 中检查普通标题栏与项目
  设置的间距/复制反馈；否则从上述证据文件和当前未提交树继续，不重复此前 paused
  标识符方案讨论。

## Workflow 节点目录与 Agent 边界重构

- Task ID/deployment：`workflow_node_catalog_refactor_closure` /
  `workflow_node_catalog_refactor_20260913`；state：`complete`。
- Verified outcome：右键添加器与节点目录现在从 `object_info` 动态注册并按分类、
  搜索和 schema 添加；canonical 类型为 Model、Agent、Command、Python、Constant、
  Input、Output、Template、Condition、Merge、Join、Subgraph。旧 `AI`、`Script`、
  `Content`、`Transform`、`Branch` 隐藏但仍可执行；类型 ID 开放，端口 ID 稳定且
  不可变，V2/ComfyUI 往返兼容边界保留。Tool/MCP、HTTP 节点因安全宿主边界未定
  暂缓。
- Verified architecture：Workflow 独立拥有文档、校验、队列、运行时、缓存、历史
  和事件；Agent 仅经显式 `WorkflowExecutionContext`/适配器参与。SemanticGraph
  编辑视图保留 params、position 与 link modifiers；WorkflowView 的 Agent 说明
  已明确使用语义 JSON 并优先引用稳定 port ID。
- Evidence/checks：Workflow backend `103 passed`；Agent/default-toolbox regression
  `97 passed`；UI contracts `81 files / 596 tests passed`；`npm run typecheck`、
  `npm run build:app`、Lam design audit `83 files / 0 violations` 通过；Tauri
  Vite `5173` 与 backend `58273` `/api/health` 均 HTTP 200。
- Limitation/disposition：用户负责 Tauri 视觉验收与真实工作流运行实测，本记录不
  宣称视觉通过。工作树重度 dirty、未提交；仅完成只读 Git handoff，未 stage、
  commit、revert、cleanup 或归因；未发现本部署特有 blocker。
- Exact next entry point：用户在 Tauri 中视觉检查并实际运行工作流；问题出现时从
  Workflow UI/目录继续，保持 canonical RPC 与兼容回退边界。

## n8n 工作流系统对齐研究交接（2026-09-13）

- Task ID/deployment：`n8n_workflow_alignment_research_closure` /
  `n8n_workflow_alignment_20260913`；state：`paused`。目标是把 n8n 的成熟
  工作流运行契约转化为 LamTools 自有实现；本部署停在用户共识前，未修改生产
  代码或测试。
- 研究结论：n8n workflow JSON 将版本化 node type、parameters、credential
  references、connections 和 execution settings 作为持久契约；运行时围绕
  item/binary-data、表达式和 lineage；触发器/webhook、retry/error routing、
  wait/resume、subflow、credential isolation、execution persistence、
  pin/manual data 是生产级配套能力。n8n 使用 Sustainable Use License，故
  仅作概念/行为参考，任何代码或 UI 复用须先法律审查：
  <https://docs.n8n.io/n8n-community-license/sustainable-use-license.md>。
- LamTools 现状（代码核对）：`backend/registry.py` 的 `object_info`/Schema
  registry 已可动态描述节点；`document.py` 已有 V2 文档、canvas-free
  execution prompt 编译和分页 semantic graph；`runtime.py` 有 Model/Agent
  分离、`WorkflowExecutionContext`、subgraph、queue/cache/history/snapshot/
  resume；`core/src/lamtools_core/app/cli.py` 的 Arrange 已支持 once、
  daily/monthly calendar 和 event trigger。
- Gap map：工作流尚无一等 item/binary envelope 与 lineage packet；表达式仍是
  Condition/edge 的受信作者 Python `eval`，缺统一安全表达式引擎；无 workflow
  `CredentialRef`/vault 与凭据隔离；Arrange 尚未连接 activation/webhook；缺
  node version migration chain 和明确 upgrade policy。HTTP、Tool、MCP 节点的
  credential/permission host boundary 尚未成立。现有 queue/cache/history/
  snapshots/resume 不等同于 n8n 的 per-node error outputs、wait/resume、
  pin/debug 交互契约，后者仍需补齐。
- 推荐实施顺序（待确认）：
  1. 契约基础：版本迁移、`DataPacket` legacy adapter、安全表达式、
     `CredentialRef`；
  2. 触发器：复用 Arrange，并加入受认证 webhook；
  3. 每节点 error outputs、wait/resume、pin/debug 投影；
  4. 最后再引入 HTTP/Tool/MCP 节点。
  Workflow/Agent 继续以显式 `WorkflowExecutionContext`/adapter 协作，不共享
  隐式运行状态。
- 用户决定清单：确认 n8n 仅作概念参考及四阶段顺序；确认 `DataPacket` 的
  item/binary/lineage 语义与旧 Workflow 格式迁移；确定表达式语法/沙箱能力和
  credential vault/ref 隔离；确定 Arrange + webhook 的激活、认证、幂等、重放
  策略；确认 HTTP/Tool/MCP 是否继续暂停至宿主权限契约落地。
- Verification/limitations：完成官方 n8n 规范和本地 workflow/Arrange/Agent
  源码的只读核对；未运行测试、构建、Tauri 或真实 workflow runtime 验收，不
  宣称实现通过。工作树原已重度 dirty 且未提交；本部署未 stage、commit、
  revert、cleanup 或归因。Evidence：`core/src/lamtools_core/plugins/bundled/
  workflow/backend/registry.py`、`document.py`、`runtime.py`、`queue.py`、
  `cache.py`、`history.py`、`snapshots.py`、`operations.py` 及
  `core/src/lamtools_core/app/cli.py` 的 Arrange CLI。
- Exact next entry point：等待用户确认上述边界；确认后先写契约、迁移、兼容测试，
  再按四阶段推进实现。

## Workflow 画布容器交互与 parent_id 部署闭环

- Task ID/deployment：`workflow_canvas_parenting_closure` /
  `workflow_canvas_parenting_20260913`；closure state：`complete`。
- Outcome：Workflow 画布现为左键无修饰框选（Vue Flow
  `selectionKeyCode=true`）、中键平移；元素必须先选中才可拖动。框架/分组双击
  全选内部节点和画布元素。容器右键菜单包含“全选”“删除”“全部删除”：前者
  选择递归内部元素；“删除”仅删除容器并将子项解除父级；“全部删除”递归删除
  容器、后代内容及相关节点 edges，并在确认框中倒计时 3 秒后解禁确认删除键。
- Data contract：`WorkflowNode.parent_id` 从 legacy/V2 导入、store、UI
  document/resources 和 clipboard 复制/粘贴端到端保留；legacy `parentId` 作为
  读取兼容别名，canonical V2 归一为 `canvas.node_views[*].parent_id`。该字段是
  画布关系元数据，不进入执行 prompt 或 node execution config。ComfyUI
  `bounding`、`pos`、`size` 的几何字段仍可归一化，旧数据无 parent 时用几何包含
  回退。
- Evidence：Workflow UI 4 files / 39 tests；UI typecheck、`npm run build:app`、
  LamTools design audit（83 files / 0 deviations）与 `git diff --check` 通过。
  Python 验证包含主代理复核 37 tests、执行者更广 Workflow 102 tests 和独立
  tester 39 tests。视觉验收由用户负责；未宣称 Tauri/CUA 实机视觉或真实工作流
  运行已通过。
- Git handoff：工作树仍重度 dirty、未提交；未执行 stage、commit、revert、
  cleanup 或归因，既有及并发改动均保留。主线程因续接压缩上下文未在本部署首条
  commentary 写入 deployment marker，token report 需原样返回该限制。
- Pending/next entry point：用户在 Tauri 完成视觉验收，并运行含容器父子关系、
  框选/拖动、双击全选和两种删除路径的真实 Workflow；若出现缺陷，从
  `core/src/lamtools_core/plugins/bundled/workflow/ui/WorkflowCanvas.vue`、
  `WorkflowCanvasElement.vue`、`canvas.ts`、`document.ts` 与
  `resources.ts` 继续，保持 `parent_id` 只存在于画布视图且不进入执行语义。

## Durable Workflow Platform deployment closure

- Task ID/deployment：`durable_workflow_platform_closure` /
  `durable_workflow_platform_20260913`；state：`complete`。
- Outcome：Sunday Workflow 已升级为本地优先的 durable runtime。Canonical V2
  document 为每次 Run 固定不可变 revision；运行内核持久化
  Workflow/Version/Run/NodeRun/Attempt、append-only JSONL event journal 与
  派生 snapshot。Queue 记录 workflow ID、revision 和完整 definition snapshot；
  恢复会跳过已完成节点，具有副作用历史但缺 snapshot 时 fail-closed，相同终态
  run 重试不重复副作用。Retry/backoff/timeout、取消、幂等、缓存、activation、
  wait/signal 均属于 Engine contract，activation 复用 Core Arrange。
- Contract/security：WorkflowDataPacket 用 item envelope 传递 JSON 与
  Attachment/Artifact 引用；CredentialRef 只在单次 Node Attempt 临时解析，
  secret 不得进入 execution metadata、events、snapshots、日志或结果。Capability
  与 resource class 必须得到宿主显式授权，否则 fail-closed。内置节点保持 legacy
  raw-value 兼容，可信插件 executor 走 packet boundary；Condition、edge
  modifiers、Template 使用版本化安全表达式 AST 并保留 legacy 兼容。Agent 与
  Workflow 通过显式 WorkflowExecutionContext/adapter 协作，不共享隐式状态。
- Verification：`py -3.14 -m pytest -q tests -k workflow` 为 166 passed / 1691
  deselected；相邻 Agent/runner 回归主代理侧 99 passed、独立侧 117 passed，含
  4 个既有 deprecation warnings；UI typecheck passed；UI contract 为 81 files /
  607 tests passed；`npm run build:app` passed（仅既有 chunk/dynamic-import
  warnings）；workflow manifests parsed；LamTools design audit 为 Core UI
  83 files / 0 deviations（脚本不扫描 workflow plugin directory）；workflow
  plugin 手工 banned-token scan 无 findings；`git diff --check` exit 0，仅有
  line-ending warnings。
- Concurrency correction：独立验证曾发现不同 WorkflowRunner 并发 signal 会产生
  duplicate side effect；现已使用按 store path 区分的 process-level single-flight
  及有界 lock 生命周期修复，同一进程内覆盖，不能宣称跨进程一致性。
- Residual limits：无跨进程 locking；timeout settle 仍在 signal 时惰性完成；没有
  完整 HumanTask center；Fast/Express 延后；HTTP/MCP 及其他 external connectors
  等待完整 credential/permission host boundary。Effectively-once 仍要求外部
  executor 遵守 idempotency key。
- Visual/Git disposition：未启动 Tauri、浏览器或人工视觉验收，不宣称视觉通过；
  视觉验收和真实 Workflow 运行由用户负责。工作树仍 heavily dirty、uncommitted；
  未 stage、commit、revert、cleanup 或归因，既有和并发改动均保留。
- Evidence/next entry：实现证据在
  `core/src/lamtools_core/plugins/bundled/workflow/backend/{durable.py,runtime.py,queue.py,snapshots.py,data_packet.py,credentials.py,capabilities.py,expressions.py,activations.py}`
  及相邻 document/registry/adapters；UI 契约在 workflow tests。下一步由用户在
  Tauri 运行真实 Workflow，覆盖 durable wait/signal 与 Agent boundary；出现缺陷
  时从上述 backend 合同和 canonical V2/legacy 兼容边界继续。

## Manual `/compact` auto-alignment closure (2026-09-13)

- Task ID/deployment: `compact_auto_alignment_closure` /
  `compact_auto_alignment_20260913`; closure state: `complete`。
- Goal/outcome: make manual `/compact` an immediate entry to the automatic
  compaction path. It now uses the shared `ContextCompactionController`; its
  `force` flag only skips the automatic trigger threshold. It does not turn off
  thinking, change the compaction target, or use a separate request path.
  `resolve_compaction_budget`, snapshot model/reasoning/thinking settings,
  trigger/limit/safety margin, 4096 default summary output, retry count and
  retry strategy are shared. Effective history is loaded by `summary_seq` with
  the legacy summary-blob fallback. Raw history is retained and persistence of
  the summary/recovery boundary occurs only after a completed successful stream.
- Verification: backend compaction/runtime checks `317 passed`; UI command/action
  checks `22 passed`; UI typecheck and Python `compileall` passed; `git diff
  --check` passed. No real `/compact` invocation was run, so runtime behavior
  remains for the user's test.
- Runtime handoff: Tauri restart completed successfully; frontend Vite is on
  `5173`, backend on `61646`. The target session is idle with 100 history rows
  (`seq` 1..100), `summary_seq=0`, and a 6561-character existing summary.
- Git/working-tree disposition: heavily dirty and uncommitted; no stage,
  commit, revert, cleanup, or attribution was performed, and unrelated or
  concurrent user changes were preserved.
- Exact next entry point: run `/compact` in the restarted Tauri session and
  verify the manual request matches automatic compaction, including failure
  atomicity.

## Durable Workflow phase 2 closure

- Task ID/deployment: `durable_workflow_phase2_closure` /
  `durable_workflow_phase2_20260913`; state: `complete`。
- Outcome: the durable engine now uses cross-process SQLite claims with
  lease/heartbeat/fencing and protects claims against definition fingerprint
  mismatches. JSONL event appends are serialized across processes. HumanTask
  state has a durable projection, and Arrange-backed once timeouts resume without
  exposing a resume token. Runtime admission covers concurrency, rate, throttle
  and debounce; queue priority is persisted and the UI exposes a strategy panel.
- Verification: Workflow backend 195 passed; adjacent Agent/Runner 100 passed;
  claims + HumanTask focused checks 23 passed; UI typecheck passed; UI contracts
  82 files / 610 tests passed; `npm run build:app` passed; LamTools design audit
  Core UI 83/0; `git diff --check` exit 0 with line-ending warnings. Tauri Vite
  `5173`, backend `61646`, and `lamcore.exe` were alive; health returned 200.
- Limitations and Git disposition: user owns visual and real Workflow
  acceptance. The JSON queue does not itself provide a cross-process queue-item
  claim, and external side effects require executor idempotency. The worktree
  remains heavily dirty/uncommitted; no stage, commit, revert or cleanup was
  performed.
- Exact next entry point — Tauri user acceptance checklist: inspect canvas,
  strategy panel and HumanTask projection; run a normal Agent-bound Workflow;
  exercise concurrent claims, lease/heartbeat recovery and fingerprint mismatch;
  exercise concurrency/rate/throttle/debounce plus queue priority; complete a
  HumanTask via signal/approval and verify Arrange once-timeout resume; restart
  during execution and confirm the pinned revision resumes without duplicate
  external side effects. No visual or real-run pass is claimed here.

## Transparent startup window handoff

- Task/deployment: `transparent_startup_closure` /
  `transparent_startup_window_20260914`; closure state: `complete`.
- Outcome: the main Tauri window now has `transparent: true`, an alpha-zero
  background, and `shadow: false`. Pre-shell `html`/`body`/`#app` and the splash
  are transparent, and only the centered Sunday mark is painted.
- Material changes: the full-screen veil/reveal/backdrop-filter path was removed;
  the normal workspace shell takes over after Vue is ready. Click-through is not
  enabled. Normal and reduced-motion paths clear `aria-hidden` and clean their
  animation state.
- Evidence: `core/desktop/src-tauri/tauri.conf.json`,
  `core/desktop/index.html`, `core/ui/src/motion/startupSplash.ts`, and
  `core/ui/tests/startup-splash.test.ts`.
- Verification: focused startup tests passed 12/12; full UI contracts passed
  610/610; full UI typecheck and desktop Vite build passed; `npm run build:app`
  generated `lamcore.exe`; config JSON/bootstrap syntax checks passed; Lam
  design audit passed 83/0; scoped `git diff --check` passed with line-ending
  warnings only.
- Limitation: no Tauri GUI/OS visual check was run, per the code-only request;
  manual smoke remains user-owned. No deployment-specific blocker is known.
- Git handoff: the worktree remains heavily dirty and uncommitted; no stage,
  commit, revert, cleanup, or attribution was performed, and unrelated/concurrent
  changes were preserved. Exact next entry point: user performs manual Tauri
  startup smoke/visual acceptance; if it fails, inspect the four evidence files
  above and keep the transparent shell contract intact.

## Workflow UI tabs, responsive catalog, and localized affordances handoff (2026-09-14)

- Task ID/deployment: `workflow_ui_acceptance_closure_20260914`; closure state:
  `complete`.
- Implemented: Workflow View supports multiple open workflow tabs with active
  state, dirty markers, close actions, and an unsaved-switch guard. The
  schema-driven node catalog supports sidebar/popover responsive bounds,
  bounded scrolling, search across canonical and localized values, category
  filters, recent/favorite filters, keyboard activation, and mobile-sized
  controls. Chinese labels, descriptions, categories, and accessible copy are
  presentation-only; canonical English type IDs, schema keys, stored
  preferences, and execution behavior are preserved. Workflow node/catalog,
  inspector, queue, trigger, and canvas affordances use semantic Lucide icons.
- Verification: full `npm run typecheck` passed. The Workflow UI suite covered
  5 files / 49 tests passed: `workflow-canvas-parity.test.ts` (19),
  `workflow-node-contract.test.ts` (3), `workflow-policies-panel.test.ts` (2),
  `workflow-runtime-services.test.ts` (9), and `workflow-ui.test.ts` (16).
  Backend `core/tests/test_workflow_node_contract.py` passed 7 tests. LamTools
  design audit: 83 files / 0 deviations. Independent Tester final code review:
  pass. These are code/design checks only; no visual Tauri pass is claimed.
- Runtime evidence: read-only process/log-chain verification found Tauri dev
  frontend Vite on `127.0.0.1:5173` and backend on `127.0.0.1:49733`. The
  process chain is ready for user observation, but it does not verify layout or
  visual behavior.
- Git disposition: Workflow UI product changes remain uncommitted alongside
  the existing dirty tree. This closure writes only
  `agent_docs/project_progress.md` and this file; `agent_docs/project_diary.md`
  was not touched. Keep unrelated/concurrent startup and desktop changes
  un-attributed: `core/desktop/index.html`,
  `core/desktop/src-tauri/tauri.conf.json`,
  `core/ui/src/motion/startupSplash.ts`, and
  `core/ui/tests/startup-splash.test.ts`. Keep untracked temporary material
  (`artifacts/`, `core/core.db-wal`, `core/core.db-shm`) untouched. No stage,
  commit, revert, cleanup, or attribution was performed.
- Exact next entry point: user performs Tauri visual acceptance of Workflow
  tabs, catalog responsiveness, Chinese presentation, and semantic icons, then
  runs a representative Workflow. If a problem appears, continue from the
  Workflow UI source and the five test files above; preserve the canonical
  registry/RPC and presentation-only localization boundary.

## Optical liquid-glass closure

- Task ID/deployment: `optical_liquid_glass` /
  `optical_liquid_glass`; closure state: `complete`.
- Outcome: `core/ui/src/styles/optical-glass.css` centralizes the optical
  liquid-glass treatment. Its tokenized surface keeps background transmission
  clear while applying 8px blur, saturation 1.14, brightness 1.02, contrast
  1.03, and 2% tint. Localized radial, linear, and conic layers provide
  restrained reflection, dispersion, highlight, and environment/color
  response. `layout.css` imports the stylesheet, and `.optical-glass` is used
  by the WorkspaceShell right drawer and ContextMenuPanel. The outer surfaces
  have border 0; legacy four-edge masks and per-surface filters were removed,
  so there is no uniform white border or edge opacity fade.
- Evidence: `core/ui/src/styles/optical-glass.css`,
  `core/ui/src/styles/variables.css`, `core/ui/src/styles/layout.css`,
  `core/ui/src/components/WorkspaceShell.vue`,
  `core/ui/src/components/context-menu/ContextMenuPanel.vue`, and
  `core/ui/tests/context-menu.test.ts`.
- Verification: focused main coverage passed 36/36; independent coverage
  passed 56/56; full UI coverage passed 82 files / 614 tests; UI typecheck and
  `build:app` passed; LamTools design audit passed 84 files / 0 violations;
  independent Tester review passed; scoped `git diff --check` passed.
- Limitation: no Tauri runtime visual check was authorized or performed. The
  worktree remains heavily dirty and uncommitted; this closure preserved
  unrelated/concurrent changes and made no stage, commit, revert, cleanup, or
  attribution. Archivist changed only the assigned documentation.
- Pending work/blockers: no deployment-specific blocker is known. Exact next
  entry point: if visual validation is later authorized, inspect the Tauri
  right drawer and shared root/submenu context menus against the optical-glass
  contract; otherwise inspect the current uncommitted tree and continue the
  existing Workflow acceptance, Artifact consensus, Office visual-quality,
  real-device LAN/Relay, and Docker image milestones.

## Context-menu liquid-glass closure

- Task ID/deployment: `context_menu_liquid_glass` /
  `context_menu_liquid_glass`; closure state: `complete`.
- Outcome: every right-click caller now uses the shared
  `openContextMenu`/`ContextMenuHost` path, and root menus plus submenus share
  `core/ui/src/components/context-menu/ContextMenuPanel.vue`. The stable outer
  transparent blur uses `blur(var(--space-4)) saturate(1.08)`, a 4% current-area
  text tint, and a four-edge mask; animation is confined to inner content.
- Evidence: `core/ui/src/components/context-menu/ContextMenuPanel.vue`,
  `core/ui/src/components/context-menu/ContextMenuHost.vue`,
  `core/ui/src/components/context-menu/context-menu.ts`, and
  `core/ui/tests/context-menu.test.ts`. The seven caller surfaces route through
  the shared host/open function.
- Verification: focused context-menu coverage passed 58/58; full UI coverage
  passed 82 files / 614 tests; UI typecheck and `build:app` passed; LamTools
  design audit passed 83 files / 0 violations; independent Tester review
  passed; scoped `git diff --check` passed.
- Limitation: no Tauri runtime/visual check was performed, per the code-only
  scope. The working tree remains heavily dirty and uncommitted; this closure
  preserved unrelated/concurrent changes and made no stage, commit, revert,
  cleanup, or attribution. Archivist changed only the assigned documentation.
- Pending work/blockers: no deployment-specific blocker is known. Exact next
  entry point: when visual validation is requested, inspect root and submenu
  context menus in Tauri; otherwise inspect the current uncommitted tree and
  continue the existing Workflow acceptance, Artifact consensus, Office
  visual-quality, real-device LAN/Relay, and Docker image milestones.

## Workflow observability, HumanTask approval, and Schema UX closure

- Task ID/deployment: `workflow_observability_20260914`; closure state:
  `complete`.
- Outcome: Workflow runs now have a persistent, collapsible run panel with
  live node/edge state, timing, attempts, retry/cache/error information,
  safe input/output summaries, tool-audit summaries, logs, and final results.
  The canvas and run panel share the public run projection. HumanTask approval
  is an explicit, resumable action; completing approval returns the continued
  terminal run snapshot rather than only an acknowledgement. Schema UX now
  exposes usable node/default parameters and JSON/text editing instead of an
  inert one-word Schema label; existing ports are not redundantly synthesized.
- Security boundary: Queue and Run public projections redact credentials,
  tokens, resume secrets, and hidden reasoning. Durable execution storage
  retains the execution input required for recovery/audit. The Agent adapter
  currently reports tool names and aggregate counts only; it does not expose
  per-call tool status, so no finer-grained tool timeline is claimed.
- Real-run evidence: workflow `工作流测试1`, ID
  `77638d5256364cc99f6887fa00e17d08`, revision 148, had 9 current nodes and
  9 links. Run `workflow_run_4f43e4a76fe0` paused for HumanTask approval and
  completed after approval. The Agent returned 23 sources and the model output
  was 17,970 characters.
- Verification: Workflow backend coverage passed 214 tests / 1693 deselected;
  focused Workflow UI coverage passed 56 tests; UI typecheck and
  `npm run build:app` passed; LamTools design audit passed 84 files / 0
  deviations; `git diff --check` passed. Independent Tester final review
  passed (backend 45 / UI 45). These checks do not constitute visual Tauri
  acceptance.
- Runtime handoff: Tauri dev was fully restarted and is currently reported at
  frontend Vite `127.0.0.1:5173`, backend `127.0.0.1:61293`, session
  `20858`. This is a readiness/runtime state, not a visual layout claim.
- Git disposition: the repository remains heavily dirty and uncommitted. This
  closure changed only `agent_docs/project_progress.md` and
  `agent_docs/latest_session_work.md`; it did not stage, commit, revert,
  clean, or attribute unrelated/concurrent work, and did not touch
  `project_diary.md`.
- Exact next entry point: the user performs visual acceptance in the Tauri
  window: open the run panel, observe node/edge progress, expand input/output
  and audit details, approve a HumanTask, and inspect the final result. If a
  defect appears, continue from
  `core/src/lamtools_core/plugins/bundled/workflow/ui/WorkflowRunPanel.vue`,
  `SchemaNodeEditor.vue`, and the Workflow runtime projection/RPC files while
  preserving the public redaction boundary.

## Graph-native Workflow runtime sidecar closure

- Task ID/deployment: `workflow_canvas_runtime_sidecar_docs_20260914` /
  `workflow_canvas_runtime_sidecar_20260914`; closure state: `complete`.
- Outcome: the global `WorkflowRunPanel` was removed from the default/UI
  source. Workflow nodes remain opaque; running nodes use a rainbow ring and
  the active graph node is layered at z-index 34, below toolbar 35, composer
  40, and popovers 60. A translucent right-side dock now presents accumulated
  public delta, output, logs, tool summaries, image/PDF/file artifacts,
  errors, and HumanTask actions. Completed runs collapse the dock. Hidden
  reasoning is filtered defensively before presentation.
- Canvas contract: VueFlow presentation-only updates no longer emit workflow
  definition changes or autosaves; only actual coordinate changes do. This
  keeps live graph positioning independent from execution semantics and
  persistence.
- Verification: full UI coverage passed 83 files / 620 tests; UI typecheck and
  `npm run build:app` passed with only existing chunk/dynamic-import warnings;
  LamTools design audit passed 84 files / 0 deviations; `git diff --check`
  exited 0 with line-ending warnings. Independent Tester passed the focused
  4-file / 45-test surface plus typecheck and diff check.
- Limitations: no Tauri visual acceptance and no real Workflow run were
  performed. The known `工作流测试1` data is damaged at revision 155 with 8
  nodes and 0 links; it was deliberately not rerun or restored during this
  deployment. Do not treat the code checks as runtime or visual confirmation.
- Git disposition: the repository remains heavily dirty and uncommitted. This
  closure changes only `agent_docs/project_progress.md` and
  `agent_docs/latest_session_work.md`; it does not stage, commit, revert,
  clean, or attribute unrelated/user changes, and leaves `project_diary.md`
  untouched.
- Exact next entry point: the user performs Tauri visual acceptance of the
  graph-native sidecar, active-node ring/layering, dock expansion/collapse,
  artifact/error/HumanTask rendering, and live canvas interaction. A valid
  Workflow fixture must be repaired or recreated before real-run acceptance;
  do not restore the damaged fixture implicitly.

## Workflow dynamic-module loading repair (2026-09-14)

- Root cause: HMR left a stale `index.ts` URL in the failed dynamic-module
  cache, while the deprecated `WorkflowRunPanel` export and dead
  `WorkflowView` state remained in the module graph. Entering Workflow could
  therefore fail before the view mounted.
- Repair: removed the deprecated component/export and dead view state, then
  fully restarted Tauri to rebuild the Vite module graph and clear the stale
  failure state.
- Verification: the three Workflow Vite modules each returned HTTP 200;
  backend Workflow V2 document reading succeeded; focused coverage passed 34
  tests; UI typecheck, `npm run build:app`, and the LamTools design audit
  passed. No visual Tauri acceptance or real Workflow execution is claimed.
- Exact next entry point: user opens Workflow in the restarted Tauri window,
  confirms the view loads, then performs the existing graph-native sidecar
  visual checks. Keep the damaged `工作流测试1` fixture unrepaired unless a
  separate restoration decision is made.

## Artifact V2 deployment handoff

- Task ID/deployment: `artifact_v2_closure` /
  `artifact_system_v2_20260914`; closure state: `complete`.
- Outcome: SQLite Artifact V2 is implemented and reviewed with stable
  per-project-path identity and immutable SHA-256-deduplicated revisions. It
  preserves legacy `.lam/artifact` manifests and historical projection-ID
  aliases, ingests at event boundaries, treats uploads as inputs, records
  generated and `file_change` outputs, supports soft remove/restore and
  revision preview/restore, and exposes RPC/HTTP/CLI parity. Checkpoints carry
  Revision pointers; workspace rollback restores referenced revisions and
  soft-removes artifacts created after the target checkpoint. Main review also
  hardened project-scoped mutation/read boundaries.
- UI outcome: the project 成果库 provides role/kind/status/search filtering,
  history/restore, StagePane preview, and event-driven refresh. Conversation
  preview stacking is preserved; card and preview surfaces remain opaque.
- Verification evidence: final backend-focused coverage passed 34 tests / 1
  skipped. The broader related suite before the final narrow hardening passed
  60 / 2 skipped. Focused UI coverage passed 3 files / 24 tests; full UI
  coverage passed 83 files / 624 tests; UI typecheck passed; `npm run
  build:app` passed; website build passed; Python `compileall` passed; the
  LamTools design audit passed 84 files / 0 deviations; scoped
  `git diff --check` passed with line-ending warnings only. Existing Vite
  chunk/dynamic-import warnings and aiosqlite datetime deprecation warnings
  are non-blocking.
- Limitation: no Tauri visual/runtime acceptance was run because this was a
  code-only scope. No visual pass is claimed. The repository remains heavily
  dirty and uncommitted; no stage, commit, revert, cleanup, or attribution was
  performed, and unrelated/user changes remain untouched.
- Exact next entry point: user performs Tauri acceptance of the project
  成果库, StagePane preview, conversation card opacity/stacking, event-driven
  refresh, and revision restore/rollback, then exercises the matching
  RPC/HTTP/CLI paths. If a defect appears, continue from the Artifact V2
  backend/RPC/CLI contract and project-library/StagePane UI; preserve legacy
  manifest/projection aliases and project-scoped boundaries.

## Reasoning levels, sub-agent overrides, and Shallow visibility handoff (2026-09-15)

- Task ID/deployment: `reasoning_levels_archive` /
  `reasoning_levels_xhigh_medium`; closure state: `complete`.
- Outcome: the canonical reasoning levels are now `off`, `light`, `medium`,
  `high`, `xhigh`, and `max`, with `xh` accepted as an alias for `xhigh`.
  Providers use multi-to-fewer mapping when they expose fewer native levels;
  DeepSeek is verified as `off → disabled`, `light → low`,
  `medium/high/xhigh → high`, and `max → max`. Adapter preset definitions
  cover the expanded six-level contract.
- Delegation outcome: a sub-agent call can override its model and
  `reasoning_level`; when omitted, both inherit the parent agent settings.
  Optional-argument filtering preserves compatibility with older narrow
  `sub_agent` runners. CLI `medium`/`xhigh` choices and approval-resume
  `reasoning_level` continuation are included. The Shallow control is hidden
  from user menus, but its compatibility field, CLI, and legacy-session path
  remain intact.
- Verification: independent Tester — 108 Python tests; 3 UI files / 22 tests;
  typecheck; 26 adapter preset checks; DeepSeek payload; inheritance/override;
  old-runner compatibility; Shallow hidden; and diff check all passed. Main
  agent — 185 Python tests passed with 28 warnings, 22 UI tests, typecheck,
  8 supplementary focused tests, CLI choices, and approval-resume continuation
  checks passed. No Tauri visual acceptance was run or claimed.
- Git disposition: only this handoff and the matching progress entry are
  documentation scope; the repository remains heavily dirty and uncommitted,
  with unrelated/concurrent changes preserved. No stage, commit, revert,
  cleanup, or attribution was performed. The next entry point is the focused
  reasoning/profile/sub-agent/UI test surface when extending adapters or
  delegation controls; do not infer visual Tauri acceptance from these checks.

## Startup optical-glass handoff

- Task/deployment: `startup_optical_glass_20260915`; closure state: `complete`.
- Outcome: `core/desktop/index.html` now renders the startup glass with a
  low-gray tint, 8px blur, static localized dispersion/environment-color
  penetration, and a masked edge highlight. `core/desktop/src-tauri/src/main.rs`
  lowers the native Acrylic alpha from 32 to 18.
- Material scope: the transparent first paint is preserved; no full-screen
  opaque treatment was introduced. Evidence files are
  `core/desktop/index.html`, `core/desktop/src-tauri/src/main.rs`, and the
  existing startup splash contract in `core/ui/src/motion/startupSplash.ts`.
- Verification: startup-focused tests passed 12/12; UI typecheck and desktop
  build passed; `cargo check --no-default-features` passed with only existing
  dead_code warnings; LamTools design audit passed 84 files / 0 deviations.
- Limitation: no Tauri GUI/OS visual check was run under the code-only scope;
  manual smoke remains user-owned. No deployment-specific blocker is known.
- Git handoff: worktree remains heavily dirty and uncommitted; no stage,
  commit, revert, cleanup, or attribution was performed, and unrelated/concurrent
  changes were preserved. Exact next entry point: user performs startup visual
  smoke in Tauri; if a defect appears, continue from the three evidence files
  above while preserving transparent first paint and low-cost static effects.

## Asynchronous sub-agent lifecycle and messaging handoff

- Task/deployment: `subagent_async_lifecycle_ui`; closure state: `complete`.
- Outcome: sub-agents have explicit create/close lifecycle operations and a
  stable `(parent_thread_id, name)` reuse identity. The main-agent
  `sub_agent_message(type, name, prompt)` path validates both type and name;
  the sub-agent-only `message(message)` path reports to the parent. Dispatch
  runs in the background and returns without blocking the parent. A prompt
  sent while a sub-agent is busy is queued for injection before sampling at
  the next `step`.
- Contract/UI outcome: `consider` and `execute` have isolated tool sets and
  cannot recursively delegate. Late context places the sub-agent name, model,
  and summary after history as a final user message for provider cache-prefix
  stability. The UI renders `type name · model reasoning · elapsed`; the right
  rail lists every current and historical sub-agent for the session, supports
  click-to-locate/expand, and shows model/reasoning on hover.
- Verification: backend focused tests passed 160; default-agent plus HTTP
  tests passed 61 with 1 skipped; UI tests passed 28; UI typecheck, Python
  `compileall`, LamTools design audit (84 files / 0 violations), and scoped
  `git diff --check` passed. Independent model-notes verification had already
  passed 216 related tests. The extended live-router suite has one existing
  pagination-resume failure unrelated to this deployment; it remains a
  known limitation and is not attributed here.
- No Tauri visual/runtime acceptance was run under this code-only closure.
  The repository remains heavily dirty and uncommitted; no stage, commit,
  revert, cleanup, or unrelated attribution was performed.
- Exact next entry point: preserve the stable name/type validation, provider
  tail ordering, next-step busy-message injection, and right-rail session
  projection when extending the supervisor or delegation UI; begin with the
  focused supervisor/runner/toolbox/HTTP and sub-agent UI tests.

## Asynchronous sub-agent UI motion follow-up

- Task/deployment: `subagent_async_lifecycle_ui`; closure state remains
  `complete`. This follow-up fills the interaction motion on the existing
  sub-agent lifecycle surface.
- Changed UI behavior: `CoreSubAgentPanel` animates list add/remove/reorder,
  expands rows including those without a source timeline, and keeps status
  icon/label transitions aligned. `CoreSubAgentDialog` adds status, backdrop,
  and close micro-motion. `RightSidebarHost` transitions files/modules and
  uses a GSAP mount-preserving runtime/artifacts transition so module instances
  remain mounted. `LamToolsApp` completes sub-agent location with a temporary
  source-heading highlight.
- Reduced-motion behavior disables the animations and switches scrolling to
  `auto`.
- Evidence: `core/ui/src/components/CoreSubAgentPanel.vue`,
  `CoreSubAgentDialog.vue`, `RightSidebarHost.vue`, `core/ui/src/app/LamToolsApp.vue`,
  `core/ui/tests/core-sub-agent.test.ts`, and
  `core/ui/tests/right-sidebar.test.ts`.
- Verification: the two focused Vitest files passed 33 tests; `npm run
  typecheck` passed; LamTools design audit passed 84 files / 0 deviations;
  scoped `git diff --check` passed with CRLF warnings only. No Tauri visual or
  runtime acceptance was run.
- Git disposition: the repository remains heavily dirty and uncommitted;
  existing and concurrent changes were preserved, with no stage, commit,
  revert, cleanup, or attribution. Exact next entry point: user visually
  checks the sub-agent panel/dialog and right-rail transitions in Tauri,
  including preserved runtime/artifacts instances, source-heading highlight,
  and reduced-motion scrolling.

## Startup theme reveal follow-up

- Continuation of deployment `startup_optical_glass_20260915`: the transparent
  startup glass is unchanged. When application preparation completes, the saved
  theme background performs one circular reveal from the actual Sunday mark
  center, expanding to a `farthest-corner` radius over 0.5s before the staged
  main-shell fade-in.
- Reduced motion skips the reveal and uses a direct cross-fade. The change keeps
  the static low-cost optical treatment and existing accessibility cleanup.
- Verification: startup-focused tests 12/12; UI typecheck; desktop build;
  LamTools design audit 84/0; and scoped `git diff --check` all passed. No
  Tauri visual verification was run; manual acceptance remains user-owned.
- Git disposition: existing heavily dirty, uncommitted work remains untouched;
  no stage, commit, revert, cleanup, or attribution was performed. Exact next
  entry point: user performs startup visual smoke in Tauri, checking reveal
  origin, radius timing, staged shell fade-in, and reduced-motion cross-fade.

## Sunday ivory/graphite brand closure

- Task ID: `sunday_ivory_graphite_close`; deployment:
  `sunday_ivory_graphite_20260915`; state: `complete`.
- Material changes: Sunday light and dark themes are flat ivory/graphite. Main
  and composer surfaces share the fill color and solid border. The exact old
  default theme can be migrated without replacing a user-customized theme.
  The 1024-viewBox logo geometry is shared by `SundayLogo.vue`, the startup
  inline logo, `sunday-mark.svg`, `sunday-app-icon.svg`, and light/dark SVG
  variants. ICO, ICNS, and legacy ICO copies were regenerated for the app icon
  and title-bar branding.
- Evidence: `core/ui/src/helpers/theme.ts`,
  `core/ui/src/data/theme-presets.ts`, `core/ui/src/components/SundayLogo.vue`,
  `core/desktop/index.html`, the Sunday SVG assets, desktop icon outputs,
  `core/ui/tests/sunday-brand.test.ts`,
  `core/ui/tests/theme-helpers.test.ts`, and
  `core/ui/tests/startup-splash.test.ts`.
- Verification: focused 6-file coverage passed 48 tests; UI typecheck/build,
  desktop Vite build, Tauri Rust build, LamTools audit (84 files / 0
  deviations), and targeted `git diff --check` passed. ICO copies hash-match;
  ICNS validation passed.
- Limitations: the full UI suite was 634/637; the three failing
  `MessageView`/`chat-thread-process` tests are pre-existing and outside this
  deployment. No Tauri visual/runtime check was performed, so title-bar,
  startup, and theme appearance remain user-owned acceptance items.
- Git disposition: repository remains heavily dirty and uncommitted. This
  closure changed only `agent_docs/project_progress.md` and
  `agent_docs/latest_session_work.md`; no stage, commit, revert, cleanup, or
  unrelated attribution was performed, and `project_diary.md` was untouched.
- Exact next entry point: on visual-validation request, open the Tauri app and
  inspect the Sunday mark at the title bar and startup surface, then check
  ivory/graphite main/composer contrast in both themes; preserve the migration
  guard and synchronized SVG/ICO/ICNS asset set when iterating.

## Sunday reference-image trace correction

- Task ID: `sunday_reference_icon_trace_archive`; deployment
  `sunday_reference_icon_trace_20260915`; state: `complete`.
- This correction replaces the approximate prior redraw with the two supplied
  reference images as the source of truth. The retained files are lossless
  1254×1254 RGBA PNGs:
  `core/ui/src/assets/sunday-app-icon-dark.png` has SHA-256
  `43baa9ec01d1f571852e3dc86463b27e39a077ff43c49523d6bfb27f12768291`, and
  `core/ui/src/assets/sunday-app-icon-light.png` has SHA-256
  `dba8a5508c294093fb3723bfe9417a04564bf797a2bf61121247464db0bd0087`.
- The application icon, title-bar icon, and startup splash now select the
  complete framed reference artwork using the resolved effective theme. The
  standalone Sunday mark is an independently measured tight 1024-viewBox
  vector, while the app-icon SVG wrappers preserve the full reference frame.
  The ivory/graphite theme tokens remain flat and sampled from the reference;
  no gradients are introduced. ICO, ICNS, and both legacy ICO copies were
  regenerated. Startup fallback colors now match the backdrop, and the Tauri
  dev stack was fully restarted after asset and startup changes.
- Evidence: `core/ui/src/assets/sunday-app-icon-{dark,light}.png`, the
  matching SVG wrappers and mark variants, `core/ui/src/components/SundayLogo.vue`,
  `core/ui/src/components/TitleBar.vue`, `core/desktop/index.html`, desktop
  icon outputs, theme token files, and `core/ui/tests/sunday-brand.test.ts`.
- Verification: focused Sunday coverage passed 47 tests; UI typecheck/build,
  desktop build, `cargo check`, the LamTools audit (84 files / 0 deviations),
  and native icon/hash checks passed. Full UI coverage was 637/640; the three
  failures are unrelated `chat-thread-process` label assertions. No Computer
  Use or visual GUI verification was performed, so visual acceptance remains
  a residual user-owned risk.
- Runtime handoff: Tauri dev is running in session `66861`, frontend port
  `5173`, backend port `64257`. The working tree is heavily dirty and
  uncommitted; existing, unrelated, and concurrent changes were preserved.
  No stage, commit, revert, cleanup, or broad attribution was performed by
  this closure. `project_diary.md` was left untouched per ownership.
- Exact next entry point: the user performs Tauri visual smoke in both
  effective themes, checking that startup and title-bar show the complete
  framed icon, the standalone mark matches the measured geometry, startup
  fallback matches the backdrop, and flat ivory/graphite surfaces retain
  contrast. If iteration is needed, begin with the corrected PNG/SVG asset
  set and the focused Sunday brand contract.

## Sunday workbench frame and icon coverage handoff

- Task ID/deployment: `archivist_sunday_workbench_frame_color_20260915` /
  `sunday_workbench_frame_color_20260915`; closure state: `complete`.
- The user clarified that “背景” refers to the `backdrop` workbench,
  background-board, and sidebar area. Chat main and composer are separate
  surfaces. The final flat light contract is workbench `#D2D8E6`, chat
  main/composer `#FDFBF7`, and controls `#2E3138` with `#FBF7F0` text. The
  dark contract is workbench `#818289`, chat main/composer `#1B1D22`, and
  controls `#FBF7F0` with `#2E3138` text. Gradients are excluded.
- Migration logic recognizes the older colorful, prior gray-control, and
  immediately previous inverted-control Sunday defaults, while preserving
  custom themes. The canonical implementation is in the Sunday theme token,
  migration, and workspace/layout surface styles.
- The raw 1254×1254 source PNGs remain byte-identical. Centered 1120px crops
  resized with LANCZOS produce 1254px display masters at approximately 90%
  meaningful alpha coverage; SundayLogo, startup splash, SVG icon wrappers,
  ICO, and ICNS use the normalized display masters. All three ICO copies are
  byte-identical with 16/24/32/48/64/256 sizes, and the ICNS is valid.
- Verification evidence: independent scoped checks passed 54/54 focused UI
  tests, UI typecheck, desktop Vite build, `cargo check` (four existing
  dead-code warnings), and scoped `git diff --check`. The full UI suite was
  645/648; three unrelated chat-thread-process assertions still expect
  obsolete `001 · name` labels instead of current `execute name` labels.
- Runtime handoff: fresh Tauri dev is active in exec session `28924`, frontend
  Vite `5173`, backend `63144`; backend ready in 2108 ms and desktop plugin
  host ready. No Computer Use or GUI visual check was run, so visual
  acceptance remains a residual user-owned item.
- Git disposition: the worktree remains heavily dirty and uncommitted. No
  stage, commit, revert, cleanup, or broad attribution was performed; all
  unrelated and concurrent edits were preserved. Exact next entry point: the
  user checks both effective themes in Tauri, especially the corrected
  workbench frame color, enlarged startup/title-bar icon, chat surfaces,
  controls, and boundaries. On defect, continue from the Sunday theme
  migration helpers, workspace/layout styles, and normalized display-master
  asset set.

## Compaction keep-recent-step setting pause

- Task ID/deployment: `compaction_keep_steps_settings_closure` /
  `compression_keep_steps_settings_20260915`; state: `paused`.
- User request: make the number of recent steps retained by compaction
  adjustable in settings. Read-only diagnosis found that current structural
  compaction is driven by token budgets and the planner retains complete
  semantic message groups split at user turns (plus compaction summary
  boundaries); there is no count-based retention setting.
- Semantic boundaries to preserve: `LoopPolicy.max_history_messages` trims a
  bounded number of history messages before context construction and is not
  the compaction retention policy. The Goal evaluator copies only
  `metadata.kernel_steps[-12:]` into its `recent_steps` projection and is not
  the compaction planner. `kernel_steps` also counts kernel loop iterations,
  which may differ from semantic user-turn groups.
- Blocker: implementation needs the user to define what “Step” means for this
  setting. No production files, tests, or runtime configuration were changed
  in this paused planning turn, and no tests/builds were run.
- Evidence pointers: `core/src/lamtools_core/context_compaction/planner.py`
  (semantic grouping and token-target layout),
  `core/src/lamtools_core/kernel/policy.py` and `kernel/loop.py`
  (`max_history_messages` trim), and
  `core/src/lamtools_core/runtime/goal.py` (`kernel_steps[-12:]` projection).
- Git disposition: the worktree remains heavily dirty and uncommitted;
  unrelated and concurrent changes were preserved. No stage, commit, revert,
  cleanup, or attribution was performed. `agent_docs/project_diary.md` was
  left unchanged.
- Exact next entry point: once “Step” is defined, update the corresponding
  settings/schema and compaction planner contract, add focused coverage for
  the chosen unit, and verify that message-count trimming and Goal’s fixed
  twelve-step projection remain independent.

## Compaction retained-step setting implementation

- Task ID/deployment: `compaction_step_tail_backend` /
  `compaction_step_tail_20260915`; state: `complete`.
- Outcome in the current worktree: structural compaction now reads
  `core.contextCompaction.retained_steps` (default `6`, accepted range `1–100`)
  with safe fallback. The settings UI (`CoreSettings`) and CLI
  (`context-compaction show/config --retained-steps`) expose the value.
  `CompactionPlanner` defines a model Step as one assistant response and its
  immediately following contiguous tool results; it protects the latest N
  Steps together with the latest 20 user messages. The exact token fitter can
  remove the oldest selected units when the target budget requires it while
  retaining the newest user boundary. Automatic and manual `/compact` share
  this policy, with per-call and `LoopPolicy.compact_retained_steps` overrides.
- The planner’s oversized-union path was corrected to enter compaction and
  use the exact token budget instead of returning an early no-op. The prior
  kernel compatibility failures were then repaired by the main agent.
- Verification evidence: main-agent backend expansion across context,
  step-tail, live/kernel, CLI, default-agent, and budget suites passed 341
  tests with 28 existing aiosqlite deprecation warnings; `compileall` passed.
  UI focused coverage passed 54 tests; UI typecheck and the LamTools design
  audit passed (84 files / 0 deviations); scoped `git diff --check` passed
  with LF/CRLF warnings only. `ruff` was unavailable (`No module named ruff`).
  The independent Tester’s corrected regression command passed 247 tests in
  35.85 seconds. Its audit confirmed union retention, budget reservation and
  shrinkage, atomic assistant+tool dropping, the newest-user minimum boundary,
  and shared automatic/manual behavior. The earlier nine kernel failures were
  fixed; the planner/fitter stage docstring mismatch was also corrected.
- Evidence pointers: `core/src/lamtools_core/context_compaction_budget.py`,
  `context_compaction/planner.py`, `context_compaction/controller.py`,
  `kernel/policy.py`, `kernel/loop.py`, `config/operations.py`, `cli.py`,
  `app/default_agent.py`, `app/command_execution.py`,
  `core/ui/src/components/CoreSettings.vue`, and the focused
  `core/tests/test_context_compaction_step_tail.py` contract.
- Git disposition: the worktree remains heavily dirty and uncommitted;
  unrelated and concurrent changes were preserved. No stage, commit, revert,
  cleanup, or attribution was performed. `project_diary.md` was not edited by
  this closure and remains under main-agent ownership.
- Exact next entry point: begin any follow-up with the focused compaction,
  step-tail, and kernel tests. Preserve the setting namespace, Step grouping,
  20-user union, newest-user boundary, and exact-budget behavior. This closure
  did not include Tauri visual acceptance.

## Input composer token alignment handoff (2026-09-15)

- Task ID/deployment: `input_token_alignment_archive` /
  `input_token_alignment_20260915`; state: `complete`.
- Outcome: every active Core UI text-like input box and textarea sources
  background, border, text, caret, and placeholder colors from composer tokens.
  Transparent title inputs are the explicit exception and remain area-local.
  Select, button, badge, and native non-text input surfaces remain on
  control-area tokens. The LamTools design guidance at
  `.agents/skills/lam-design-spec/SKILL.md` was synchronized.
- Contract evidence: `core/ui/tests/input-composer-tokens.test.ts` scans the
  app, components, workflow, and styles surfaces. Executor affected tests were
  60/60; focused contract coverage was 4/4; UI typecheck passed; the LamTools
  design audit covered 84 files with 0 violations; and the scoped diff check
  passed. Independent Tester PASS after scanner hardening confirmed focused
  4/4 and found no applicable residue in the static scan.
- Validation limits: the full UI suite had 651 passes and 3 unrelated failures
  in `tests/chat-thread-process.test.ts` for obsolete sub-agent labels. No
  Computer Use/Tauri visual verification was run. Existing
  `CoreGoalStrip.vue` cancel-button composer coloring is outside this scope.
- Git disposition: read-only handoff; the repository remains heavily dirty and
  uncommitted, with unrelated and concurrent edits preserved. No stage, commit,
  revert, cleanup, or attribution was performed. Exact next entry point: use
  the composer-token contract and `input-composer-tokens.test.ts` scanner when
  adding or auditing text-entry surfaces; retain the title-input exception and
  control-area mapping.

## Composer action-button color handoff (2026-09-15)

- Task ID/deployment: `composer_action_button_archive` /
  `composer_action_button_colors_20260915`; state: `complete`.
- `CoreSendStopButton` send and stop outer surfaces use
  `--theme-composer-text`; paper-plane, stop glyph, and motion trail use
  `--theme-composer-background`. GSAP runtime color resolution no longer uses
  control tokens or red, while existing motion, accessibility, and hit-area
  behavior remains unchanged. The lam-design-spec canonical guidance includes
  this explicit composer action-button exception.
- Evidence: executor focused 3 files / 8 tests, UI typecheck, LamTools design
  audit 84 files / 0 violations, and scoped diff check passed. Independent
  Tester PASS covered 3 files / 22 tests, typecheck, design audit 84/0, scoped
  diff check, and a temporary non-reduced GSAP send→stop→send runtime test
  that passed; the temporary test was removed.
- Limitation: jsdom cannot compute pseudo-element `currentColor`; source
  inheritance was verified. No Tauri or pixel visual run was performed.
- Git disposition: read-only handoff; the repository remains heavily dirty and
  uncommitted, with unrelated and concurrent edits preserved. No stage, commit,
  revert, cleanup, or attribution was performed. Exact next entry point: begin
  with `CoreSendStopButton`, the composer action-button exception, and focused
  contract coverage when extending send/stop coloring.

## Title input transparency handoff (2026-09-15)

- Task ID/deployment: `title_input_transparency_archive` /
  `title_input_transparency_20260915`; state: `complete`.
- Root cause was selector specificity from accumulated `:not(...)` clauses on
  the shared text-input recipe. Wrapping that recipe in zero-specificity
  `:where(...)` lets seven inline/pure-text title exceptions reliably set
  border 0, transparent background, and local text/caret while preserving
  composer colors, native exclusions, and the select-control recipe. Form
  values named `title` or `name` remain composer input boxes.
- Evidence: executor 5 files / 62 focused tests, UI typecheck, LamTools design
  audit 84 files / 0 violations, and scoped diff checks passed. Independent
  Tester PASS covered 8 files / 109 tests, typecheck, scoped diff check, and
  selector-specificity/source review.
- Limitation: static CSS contract only; no rendered Tauri CSSOM or visual run.
  A discarded invalid explicit Vitest-config attempt had no product impact.
- Git disposition: read-only handoff; the repository remains heavily dirty and
  uncommitted, with unrelated and concurrent edits preserved. No stage, commit,
  revert, cleanup, or attribution was performed. Exact next entry point: use
  the zero-specificity recipe and seven title exceptions when auditing title
  controls, retaining composer tokens for ordinary `title`/`name` fields.

## Context compaction full-summary and recent-user handoff (2026-09-15)

- Task ID/deployment: `compaction_full_summary_recent_users_20260915`; state:
  `complete`.
- Material behavior: `core.contextCompaction.retained_steps` defaults to `0`
  with a valid range of `0–100`. The zero setting summarizes all non-prefix
  history, then programmatically appends a generated `## Recent user messages`
  section containing the newest 20 user instructions verbatim as `1.`, `2.`,
  and subsequent numbered entries. Positive values retain recent Step units
  (assistant response plus contiguous tool results) alongside that user suffix.
- Budget and repeat rules: the exact fitter drops the oldest retained Steps,
  then the oldest numbered user entries, and preserves the newest user
  instruction unless it cannot fit by itself. Repeated compaction removes the
  previous generated section before summarizing and appending again. For
  multimodal instructions, text/content blocks remain and media-only blocks
  are omitted. Automatic and manual `/compact` use the same policy; CLI,
  settings RPC, and CoreSettings UI accept `0`.
- Exact implementation and contract files:
  `core/src/lamtools_core/app/command_execution.py`,
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
- Verification: main backend regression `348 passed`; independent Tester
  `209 passed`; CoreSettings Vitest `15 passed`; UI typecheck, `compileall`,
  LamTools design audit (84 files / 0 deviations), and scoped
  `git diff --check` passed. No Tauri visual/runtime check was run, matching
  this code-focused acceptance scope.
- Git disposition: implementation and documentation remain uncommitted in a
  heavily dirty worktree; concurrent and unrelated changes were preserved. No
  stage, commit, revert, cleanup, or attribution was performed. No blockers
  remain for this deployment. Exact next entry point: start with the focused
  compaction/step-tail tests before changing the zero default, recent-user
  suffix, newest-user minimum, or exact-budget drop ordering.

## Sub-agent lifecycle event copy and mailbox projection handoff (2026-09-15)

- Follow-up to deployment `subagent_async_lifecycle_ui`; this handoff records
  the event-copy and projection closure. `MessageView` renders five explicit
  lifecycle/mailbox states with Lucide icons: `UserRoundPlus` — `创建了
  {name} · {model} {reasoning}`; `Power` — `启用了 {name} · {model}
  {reasoning}`; `PowerOff` — `关闭了 {name}`; `Send` — `向 {name} 发送了消息`;
  and `Inbox` — `收到了 {name} 的消息`.
- Backend `sub_agent` operation results carry the transient actions
  `created`, `enabled`, `closed`, and `message_sent`. Child-to-parent guidance
  is projected as a completed `sub_agent_receive` tool row with `name`/`type`
  arguments and `message_received` metadata. Asynchronous lifecycle calls stay
  ordinary dynamic tool rows rather than `agent_summary` rows.
- The projection metadata is presentation-only: provider/model history keeps
  the original message text and does not receive lifecycle UI metadata. This
  preserves the late-context/cache-prefix contract and keeps the mailbox body
  visible without leaking event bookkeeping into prompts.
- Evidence and verification: the UI closure suite passed 116 tests, the
  backend closure suite passed 249 tests, and `npm run typecheck` passed. No
  Tauri visual/runtime check was run or claimed.
- Git disposition: only this documentation handoff is owned here. The working
  tree remains heavily dirty and uncommitted; unrelated and concurrent edits
  were preserved, with no stage, commit, revert, cleanup, or `project_diary.md`
  change. Exact next entry point: use `MessageView`,
  `event/runtime_projection.py`, `sub_agent_supervisor.py`, and the lifecycle
  tests when extending copy or mailbox behavior; retain the five mappings,
  action metadata, ordinary asynchronous tool rows, and body-only model
  history.

## Context compaction full-summary bugfix continuation (2026-09-16)

- Task ID/deployment: `compaction_full_summary_recent_users_20260915`; state:
  `complete`.
- Same-run later Steps now retain the generated summary in memory while
  filtering it from durable rows. Manual zero-tail compaction uses valid
  high-water/compacted sequence values and no longer falls back to full
  history. Repeated compaction combines the previous structured
  `recent_user_messages` section with new raw users and rolls it forward to
  the newest 20. Internal request-local user messages are excluded; typed
  media fields are excluded and media-only users receive a placeholder.
- The visible numbered original-user suffix remains unchanged. Ambiguous
  heading/number/newline, CRLF, and special `splitlines()` inputs carry an
  invisible length footer so decoding round-trips exactly. Automatic and
  manual policy overrides have matching behavior.
- Evidence: compaction planner/controller/formatter and budget contracts in
  `core/src/lamtools_core/context_compaction/` and
  `core/src/lamtools_core/context_compaction_budget.py`, with focused coverage
  in `core/tests/test_context_compaction.py` and
  `core/tests/test_context_compaction_step_tail.py`.
- Verification: main focused tests `289 passed`; independent focused tests
  `215 passed` plus the compaction trio `95 passed`; 61 targeted tests and
  20,000 randomized round-trip cases passed; `compileall` and scoped
  `git diff --check` passed. Full Core: `1965 passed, 2 skipped`, with six
  unrelated failures in tool-count, artifact-DB, and live-resume tests. No
  Tauri run was performed.
- Git disposition: only these two documentation files are owned by this
  handoff. The worktree remains heavily dirty and uncommitted; concurrent and
  unrelated changes were preserved, with no stage, commit, revert, cleanup,
  attribution, or diary edit. Exact next entry point: begin with the focused
  compaction and round-trip contracts before changing sequence handling,
  newest-20 roll-forward, exclusion rules, or invisible footer encoding.

## Sub-agent runtime integration repair closure (2026-09-16)

- Task ID/deployment: `fix_subagent_runtime_integration`; closure state:
  `complete`.
- Outcome: create/close validate the complete
  `action/type/name/model/reasoning_level` contract; `sub_agent_message`
  validates `type/name/prompt`; the child-only `message(message)` channel is
  auto-allowed. `consider` and `execute` receive isolated tool sets without
  recursive delegation. Child runs execute asynchronously and use `name` as
  the stable reuse key.
- Runtime behavior: parent/child run, Step, call, and source anchors refresh
  on lifecycle operations; persistent mailbox and live guidance deliver child
  messages at the next Step. Cross-run and cross-invocation deduplication is
  enforced, and child item IDs include sub-session, run, and invocation
  identity. Approval resume restores child identity, toolbox, and request-local
  context. Child events remain attached to the active `sub_agent_message`
  item and do not terminate or leak into the parent main line. States expose
  running, idle, paused, closed, interrupted, and error.
- Prompt/config behavior: `xh`/`XH` and `Medium` normalize through schema,
  CLI, and runtime; DeepSeek level reduction is mapped and tested. Model notes
  enter model request prompts. Name, model, and summary are appended after
  history as request-local context to preserve cache prefixes.
- UI behavior: the right rail combines live and historical sub-agents with
  click-to-locate/expand/highlight, hover model/reasoning details, status
  ordering, and reduced-motion-safe transitions. Rows show
  `类型 名 · 模型 思考强度 · 耗时`; lifecycle rows use the create/enable/close/
  send/receive copy and icons. Shallow is hidden from entry points while
  active indicators remain available.
- Verification: main-agent backend expansion `205 passed`; UI `86 files /
  665 passed`; typecheck, `build:app`, Python `compileall`, LamTools design
  audit `84 files / 0 deviations`, and scoped diff check passed. The build
  reported only existing chunk/dynamic-import warnings and diff check only
  line-ending warnings. Independent Tester: PASS with backend `152 passed`,
  UI `665 passed`, typecheck, compileall, and diff check. No Tauri visual
  acceptance was performed, matching the user-requested code-only scope.
- Git handoff: read-only; the heavily dirty worktree remains uncommitted and
  all unrelated/concurrent changes were preserved. No stage, commit, revert,
  cleanup, or attribution was performed. Exact next entry point: use the
  supervisor/runner contracts, runtime projection, and sub-agent UI tests for
  follow-up changes, retaining asynchronous mailbox delivery, approval-resume
  child identity, late-context placement, and the five lifecycle mappings.

## Context compaction final fix delta (2026-09-16)

- Task ID/deployment: `compaction_full_summary_recent_users_20260915`; state:
  `complete`.
- Consecutive manual compactions now union prior `compacted_history_seqs`
  while preserving positive retained Steps. Steps removed by the exact-budget
  fitter are marked and cannot reappear in same-run memory, durable history, or
  the next run for either manual or automatic compaction.
- Final evidence: main focused coverage `291 passed`; independent targeted
  coverage PASS. The full Core baseline remains `1965 passed, 2 skipped`, with
  six unrelated failures in tool-count, artifact-DB, and live-resume tests.
  No Tauri run was performed.
- Git handoff: only this documentation delta is owned here; the heavily dirty
  uncommitted worktree and concurrent changes remain untouched. No stage,
  commit, revert, cleanup, attribution, or diary edit was performed. Exact
  next entry point: use the focused sequence-union and fitter-removal
  contracts before changing zero-tail behavior, newest-20 suffix handling, or
  positive-Step retention.

## Sub-agent role assignments handoff (2026-09-16)

- The role-assignment model uses a global `role_assignments` baseline. Project
  assignments merge by trimmed, case-folded `task_type`: a same-name project
  assignment overrides the global assignment and a new project assignment is
  appended. The stored fields are `task_type`, `type`, `model`,
  `reasoning_min`, and `reasoning_max`; `type` is `consider` or `execute`.
  Supported reasoning is `off/light/medium/high/xhigh/max`; `xh` normalizes to
  `xhigh`, and `shallow` is not supported.
- Shared UI edits both global and project scopes and saves canonical
  `model_id`. RPC responses distinguish `local`, `effective`, and `inherited`.
  CLI commands are `subagent roles show/set/delete`. The role section in the
  system prompt is emitted immediately after the guide section.
- Verification: backend `77 passed`; frontend `37 passed`; typecheck,
  `compileall`, LamTools design audit (`84/0`), and `git diff --check` passed.
  No Tauri visual acceptance was run.
- Git handoff: this entry is documentation-only; preserve the existing dirty,
  uncommitted worktree and unrelated changes. For follow-up, begin with the
  role-assignment merge/RPC/CLI contracts and the shared UI tests, retaining
  canonical model IDs, inherited/effective state, and the no-Shallow boundary.

## Office renderer contract planning handoff (2026-09-16)

- Task ID/deployment: `office_renderer_contract_20260916`; closure state:
  `paused`.
- Scope completed: read-only inspection and planning for a unified renderer
  needed by the built-in Office Skills. Core currently has no durable Office
  renderer/service that owns rendering and layout validation.
- Proposed contract for the next implementation entry: expose one `office
  render` CLI/service; require the Agent to write a canonical, machine-readable
  data manifest first; validate each table cell and each chart
  series/category/value binding against that manifest before rendering; fail
  closed on any mismatch and return a structured error with code, page/element
  identity, expected and actual values, and source location.
- Layout QA belongs in the renderer. The planned PDF/PNG preview pass should
  detect text overlaps and return page number, element IDs, visible text,
  bounding boxes, overlap rectangle, and the conflicting element so the Agent
  can correct the source layout. Planned conversion is LibreOffice Office to
  PDF with an isolated profile and no automatic installation; packaging must
  declare PyMuPDF, python-pptx, and openpyxl.
- Verification performed: read-only document/code/Git inspection only. No
  tests, builds, Tauri/Computer Use, production or Skill edits, staging,
  commit, revert, cleanup, or attribution were performed. The worktree remains
  heavily dirty with unrelated and concurrent changes preserved.
- Blocker/decision: implementation must wait for user confirmation of the
  proposed renderer location, CLI/service boundary, manifest schema, supported
  Office formats, and LibreOffice availability behavior. Exact next entry point
  is to confirm that contract, then inspect existing Office Skill/tooling
  surfaces and add the renderer plus CLI and contract tests.

## Sub-agent delegation strategy handoff (2026-09-16)

- Task ID/deployment: `delegation_strategy_closure` /
  `subagent_delegation_strategy`; closure state: `complete`.
- Delegation strategy is `forbidden`, `low`, `medium`, or `high`, defaulting to
  `medium`. The global baseline is inherited by projects; an explicit project
  value overrides it, while `null` or `unset` deletes the local key and
  restores inheritance. RPC returns `local`, `effective`, `global`, and
  `inherited`; CLI commands are `subagent strategy show/set/unset`.
- Projects with blank `work_root` are rejected, including the unified
  guide/roles validation. The shared editor supports all four levels and a
  project “inherit global” option with independent saves. Prompt order is
  `guide → strategy (priority declaration) → roles`, and high-strategy
  responsibility copy is complete.
- `CoreBaseAgentKit` and `_build_core_runtime_toolbox` hide/disable
  `sub_agent` and `sub_agent_message` under `forbidden`. Direct calls and
  approval resumes after switching to `forbidden` are blocked; already-running
  historical agents are not closed. Explicit user/operator lifecycle RPCs do
  not belong to the main-agent strategy boundary.
- Verification: backend prompt/CLI `83 passed`; config defaults `5 passed`;
  approval-focused `2 passed` plus approval group `5 passed`; blank-root CLI
  `9 passed`; blank-root RPC `4 passed`; frontend `3 files / 40 passed`;
  typecheck, `compileall`, design audit `84/0`, and diff check passed. Tester
  verdict: ACCEPT, with no P0/P1/P2 findings. No Tauri or Computer Use run was
  performed.
- Git handoff: documentation-only scope; the shared dirty, uncommitted tree
  and unrelated changes remain untouched. Next entry point is the strategy
  merge/RPC/CLI/editor contract and forbidden-boundary approval tests.

## Title-bar sidebar toggle and narrow-screen closure (2026-09-16)

- Task ID/deployment: `titlebar_sidebar_controls_archive` /
  `titlebar_sidebar_controls_20260916`; closure state: `complete`.
- WorkspaceShell now owns left/right pin state. Both pin changes, including
  responsive auto-unpin, are emitted and synchronized into LamToolsApp; TitleBar
  only requests the toggles. At max-width 640px, only the two sidebar controls
  are hidden; device/account and native window controls remain available.
- Evidence surfaces: `core/ui/src/components/WorkspaceShell.vue`,
  `core/ui/src/app/LamToolsApp.vue`, `core/ui/src/components/TitleBar.vue`,
  and the responsive/sidebar contract tests.
- Verification: focused coverage 24/24; full UI contract 87 files / 674 tests;
  UI typecheck passed; LamTools design audit covered 84 files with 0 violations;
  affected-file `git diff --check` was clean.
- Limitation: code-only verification; no Tauri visual/runtime check was run.
- Git handoff: read-only; the heavily dirty, uncommitted tree was preserved.
  No stage, commit, revert, cleanup, or unrelated attribution was performed.
  Exact next entry point: start with the WorkspaceShell/LamToolsApp/TitleBar
  synchronization contracts and responsive sidebar-control tests when extending
  this behavior.

## Unified Office renderer implementation handoff (2026-09-16)

- Task/deployment: `office_renderer_implementation_20260916`; this deployment
  originally delivered the renderer below `_shared`. The later standard
  packaging repair in this handoff supersedes that location. The former
  `lamtools_core.office` package remains removed.
- Contract: canonical datasets are written first in a manifest. Table and
  chart targets bind to that manifest using `pptx_table`, `pptx_chart`,
  `docx_table`, `xlsx_range`, or `xlsx_chart`. Each cell, category, series,
  and value is compared before rendering. A data or structure mismatch stops
  before backend discovery and leaves no PDF/PNG/Office output.
- Rendering and diagnostics: Windows `auto` uses Microsoft Office COM first
  and LibreOffice second through `soffice.com`. Successful rendering provides
  PDF/PNG previews and text-overlap reports with page, conflicting elements,
  visible text, and geometry.
- CLI entry points are `office validate` and `office render`. Runtime location
  checks passed for source, simulated `_MEIPASS`, and wheel installation. The
  wheel contains the companion runtime and no `__pycache__`. The PyInstaller
  spec static-path check passed; a complete PyInstaller build was not run.
- Evidence: final main regression coverage passed 157 tests; independent
  acceptance passed 133 tests; a real Microsoft Office COM CLI smoke run
  passed. Deliberate mismatch and text-overlap cases retain exit codes 2 and 4
  with structured diagnostics.
- Limitations and pending work: this evidence covers structural/data gates,
  backend conversion, and programmatic overlap diagnostics; it is not a claim
  of pixel-level human visual acceptance. The repository remains a shared
  dirty tree pending the user's normal commit/review decision. This handoff
  changed only the two assigned documents; no diary, staging, commit, revert,
  cleanup, or unrelated attribution was performed. Exact next entry point is
  the companion-runtime CLI path and the unrun complete PyInstaller build.

## Office Skill standard packaging repair handoff (2026-09-16)

- Deployment `office_skill_standard_packaging_20260916`; closure state:
  `complete`.
- The GUI retest exposed a discoverability failure: from an isolated project
  directory the Agent ran `which office`, concluded the renderer was absent,
  and bypassed the required manifest gate. The stable invocation is now
  embedded directly in each relevant authoring Skill as
  `py -3.14 -m lamtools_core.cli office ...`; PATH probing is forbidden.
- Renderer ownership is now standard and self-describing at
  `core/skills/office-renderer/`, with `SKILL.md`, explicit-only
  `agents/openai.yaml`, executable `scripts/office.py`, and the implementation
  package below `scripts/lamtools_office_renderer/`. Core CLI lazy-loads this
  path and keeps the former `_shared` lookup only as a temporary compatibility
  fallback.
- The ten authoring Skills gained standard `agents/openai.yaml` metadata and
  moved to version 0.2.0 beta. Spreadsheet guidance requires recalculation to
  be saved into the exact file bound and delivered; chart guidance forbids
  truncated positive-value bar baselines.
- Runtime support now honors standard
  `policy.allow_implicit_invocation: false`: the renderer can be loaded
  explicitly but is omitted from automatic Skill indexes, with cache
  invalidation when `openai.yaml` changes.
- Evidence: all 11 Office Skills passed the Skill Creator validator; 117
  Office/Skill/runtime tests and 59 Core CLI tests passed; direct script help
  and structured JSON failure behavior passed from unrelated working
  directories; scoped diff check had no errors. Wheel build remains unexecuted
  because neither available Python environment has `hatchling`; existing
  recursive force-include/spec packaging covers the new standard tree.
- Git disposition: the repository remains heavily dirty with concurrent work.
  No staging, commit, revert, cleanup, or attribution of unrelated edits was
  performed. The next behavioral acceptance step is a fresh GUI task in a new
  project directory and confirmation that `office-data.json`, validate report,
  render report, and preview directory are all produced before delivery.

## Turn artifact discovery and presentation repair (2026-09-16)

- Completed top-level Agent answers now discover explicitly listed local file
  paths, reject missing/out-of-project paths, register the files in Artifact V2,
  and attach them to the same message item so both “本轮产出” and the project
 成果库 receive the deliverables without a UI-side filesystem scan.
- The stable system prompt now requires every newly created or updated
  deliverable path to be listed explicitly in the final answer.
- Message artifact cards use theme-aware neutral surfaces and Lucide type icons;
  the hard black card and saturated blue code tile were removed. Artifact-panel
  selection and primary actions were also neutralized, with spreadsheet,
  presentation, and code icons inferred from the filename.
- Text/code artifacts open in an internal plain-text preview instead of the OS
  default app. CLI parity is available through `artifact preview`.
- Follow-up interaction repair: card expansion is hover-only; click/focus no
  longer pins its size. Text preview opens on double-click (or Enter/Space) and
  is teleported to `body`, so its fixed overlay is window-relative rather than
  anchored to the transformed/scrolling chat content. The overlay now reuses
  the neutral Core confirmation backdrop recipe instead of the themed solid
  color that appeared blue.
- The “本轮产出” hover stage now expands horizontally only. Card, icon area,
  and deck height stay at 72px, so inspecting a file no longer pushes later
  chat content downward.
- Verification: Artifact V2 tests 8/8; focused UI tests 93/93; UI typecheck
  passed; design audit scanned 84 files with zero violations; scoped diff check
  passed aside from existing line-ending warnings. No Tauri visual run or commit
  was performed.

## Office Skill direct-execution prompt repair (2026-09-16)

- Task/deployment: `office_skill_runtime_directness_20260916`; state: complete.
- Root cause: the generic instruction to confirm tools and environments allowed
  ordinary Office production to drift into renderer source inspection, backend
  probing, scratch experiments, and capability re-certification. The renderer's
  automated `visual=passed` status was also being conflated with a full preview
  review, so only representative pages were viewed while an overall visual pass
  was claimed.
- Repair: `office-renderer/SKILL.md`, `office-renderer-contract.md`, and
  `tooling-contract.md` now make the public CLI/JSON report the trusted boundary
  and prescribe the single path `office-data.json -> final source -> validate ->
  render -> structured-error repair -> validate`. Ordinary tasks may not inspect
  renderer/Core CLI source, make scratch Office/negative-manifest/formula-cache
  experiments, or probe PATH/installations/private backends. A formal environment
  error stops rendering and is reported rather than reverse-engineered.
- Visual claim boundary: full visual review requires every generated page/sheet
  preview image to be viewed once; sampled review must list the viewed pages.
  Programmatic `visual=passed` remains an automated-rule result, not evidence of
  human or vision-model page review.
- Evidence: new static prompt-contract coverage plus renderer regression suites
  passed 31 tests. All 11 Office Skills passed `quick_validate.py` with UTF-8
  enabled. Scoped `git diff --check` passed with line-ending warnings only. No
  GUI or complex Office scenario rerun was performed.
- Git disposition: the shared worktree remains heavily dirty and uncommitted;
  unrelated and concurrent changes were preserved. Exact next entry point is a
  fresh GUI Office task verifying the Agent uses the direct path and performs a
  truthful full-versus-sampled preview review.

## Direct transport repair and `16-2-test` process-only review (2026-09-17)

- Root cause of the observed `direct transport disconnected` behavior was split
  between presentation and queue pressure: the client discarded WebSocket close
  diagnostics and surfaced every disconnect immediately, while the backend live
  reader performed a pointless sync-journal SQLite lookup for every transient
  `seq=0` delta. Under bursty streaming this could fill the 256-event subscriber
  queue and close with code 1013.
- Repair files: `core/ui/src/transport/{types,directTransport}.ts`,
  `core/ui/src/composables/useCoreToast.ts`, `core/ui/src/app/LamToolsApp.vue`,
  `core/ui/src/appServer/store.ts`, and `core/src/lamtools_core/app/live_router.py`,
  with focused tests in the corresponding UI/backend suites. Reconnects within
  two seconds are silent; persistent disconnects retain actionable close details.
- Verification: focused UI 42/42; full UI 683/683 across 87 files; UI typecheck
  and build passed; LamTools design audit reported 0 deviations across 84 files;
  the new backend regression passed. The wider router/hub run retained one
  unrelated failure in `test_core_live_resume_response_exposes_page_cursor`.
- Process audit evidence for session `95593909ad434e5e99aa45ca597ede80`:
  607 seconds, 48 model calls, 82 unique tool calls (80 completed, 2 failed),
  4,077,666 input tokens, 3,916,672 cached tokens, 73,654 output tokens, and a
  weighted 96.05% cache-hit rate. The Agent loaded the 0.2.1 renderer contract
  but still probed Python packages, LibreOffice paths, and matplotlib and ran a
  forbidden scratch formula-cache experiment. A later UTF-8 validation command
  failed because inline JSON reads used the Windows GBK default. After changing
  and rerendering the workbook, the Agent did not reopen the regenerated XLSX
  previews before claiming full visual review. This is a process finding only;
  no deliverable-quality judgment was made.
- Git disposition: the shared worktree remains heavily dirty. This closure did
  not stage, commit, revert, clean, or attribute unrelated changes.

## Optional Office readiness command and positive prompt (2026-09-17)

- Superseding prompt decision: Office Skills no longer enumerate renderer
  source inspection, PATH probes, scratch files, or other unwanted behaviors.
  They state the direct production path and one optional readiness command.
- `py -3.14 -m lamtools_core.cli office check` creates temporary minimal DOCX,
  XLSX, and PPTX files and performs real PDF conversions. Success prints exactly
  `Office 应用已就绪 · Test Passed 3/3`; JSON detail is written only when a
  report path is requested, while failures retain a concise status plus
  structured diagnostics.
- The companion `office-renderer/scripts/office.py check` entry point has the
  same behavior for standalone Skill packages. Both real commands passed 3/3
  locally. Focused tests passed 33/33, and all 11 Office Skills passed
  `quick_validate.py` with UTF-8 enabled.
- The shared worktree remains dirty; no staging, commit, cleanup, or unrelated
  attribution was performed.

## Model/provider and tool-mode settings entry cleanup (2026-09-17)

- Task ID/deployment: `model_provider_page_entry_refresh_archive` /
  `model_provider_page_entry_refresh_20260917`; closure state: `complete`.
- Production scope: `core/ui/src/components/CoreSettings.vue` removes the
  `.models-overview-bar` statistics and duplicate create buttons while keeping
  the page title/subtitle, provider-rail footer and provider empty-state CTA,
  and model-section header and model empty-state CTA. `CoreLoadToolsEditor.vue`
  removes `.loadtools-overview-bar` metrics and the duplicate top add action
  while keeping title/subtitle, dirty/refresh/save controls, mode-rail footer,
  and the empty-state CTA.
- Tests: `core/ui/tests/core-settings.test.ts` was updated and
  `core/ui/tests/core-loadtools-editor.test.ts` was added.
- Verification evidence: executor focused CoreSettings passed 16 tests;
  combined focused coverage passed 19 tests; typecheck, build, LamTools audit
  (84 files / 0 deviations), and scoped diff check passed. Independent Tester
  PASS included focused 19/19, full UI 88 files / 687 tests, typecheck,
  `npm run build`, and Git diff checks. Build output contained only existing
  dynamic-import warnings.
- Limitations: no Tauri/Computer Use visual validation was performed. The
  Tester observed older pre-existing dead CSS in CoreSettings unrelated to the
  removed active overview selectors; no blocker was found.
- Git handoff and exact next entry point: the shared worktree remains dirty and
  uncommitted, with unrelated files preserved. No stage, commit, revert,
  cleanup, or attribution was performed. If visual acceptance is requested,
  open the model/provider settings page and tool-mode editor in Tauri and check
  the retained local add/empty-state entry points.

## Website self-hosted distribution implementation closure (2026-09-17)

- Task ID/deployment: `website_self_hosted_distribution_closure` /
  `website_self_hosted_distribution_20260917`; implementation is complete;
  hosting/distribution follow-up is pending user confirmation.
- Completed scope: `website/` is now tracked. `website/src/App.vue` contains
  SiteNav/Hero/Showcase/Features/Download/SiteFooter. Showcase mounts the full
  real `LamToolsApp` with a typed in-memory `MockTransport`; it makes zero
  real API, XHR, or WebSocket calls. The UI provides synchronized ivory-white
  and graphite-black themes, with a very small rainbow spectrum reserved for
  fine-line emphasis. The default download is same-origin
  `/downloads/Sunday-latest-x64-setup.exe`.
- Preview containment repair: inline mounting had caused Core's
  `position:fixed`/`100vw`/`100vh`, settings cards, and composer to resolve
  against the host page. The preview now runs in a same-origin
  `preview.html` iframe with an independent viewport, still directly
  importing the complete `LamToolsApp` and `MockTransport`; the parent page
  does not load Core global CSS. Vite multi-page output now includes both
  `index.html` and `preview.html`.
- Theme synchronization is implemented with a fixed iframe URL and
  same-origin `postMessage`; the iframe remounts the real `LamToolsApp`, so
  switching themes is independent of parent-page scrolling and inline Core
  state.
- Independent Tester evidence: `npm run build` and
  `scripts/verify-preview.mjs` passed at 1440px and 390px; `pageScrollY=0`,
  no horizontal page overflow, and no console errors were reported.
- Extended verification passed at 2277x1362, 1440x1000, and 390x844, including
  shell/main/composer/settings containment, no Core overlay leakage into the
  parent page, and no API/XHR/WebSocket calls, console errors, or horizontal
  overflow.
- Final independent Tester verification passed in the production preview on
  port 5200 (`verify-preview` exit 0). Graphite and ivory both reported
  `pageScrollY=0`; settings rect `107.7/74.6/1330.3/798.5` was fully within
  the `1438x819` viewport; no API/XHR/WebSocket calls, console errors, or page
  errors occurred.
- Not yet executed: owned-server hosting, DNS configuration, update-source
  migration, and deployment. Until the user confirms the canonical HTTPS
  domain and upload/deployment method, the existing GitHub update/release
  path remains the active backend path. The installer artifact convention is
  `Sunday_<version>_x64-setup.exe`.
- Exact next entry point: after confirmation, deploy the tracked website and
  installer/manifest assets, configure DNS and same-origin update/download
  endpoints, then verify the live website and desktop update check. The local
  preview/test evidence must not be reported as live-server verification.
- Documentation/Git handoff: this correction changes only
  `agent_docs/project_progress.md` and `agent_docs/latest_session_work.md`.
  Preserve unrelated dirty/untracked files; no stage, commit, revert, cleanup,
  attribution, or `project_diary.md` edit was performed here.

## Study plugin UI repair closure (2026-09-17)

- Task ID: `study_plugin_style_archive`. Deployment ID/state:
  `study_plugin_style_20260917` / `complete`.
- Outcome/material changes: Study title now teleports into
  `.workspace-plugin-header` and follows the standard header band. Overview
  rows/progress use main-area tokens. The VueFlow graph remains backend-owned
  through `net.relations`, with theme-derived dot grid, relationship styles
  and legend, plus node/relationship counts. Study chat retains
  `useCoreAutoFollowScroll`, the IntersectionObserver bottom sentinel,
  jump-to-latest, and remount reset/forced-bottom behavior. Selection-assistant
  readability fills now use main theme tokens rather than hardcoded dark/light
  fills.
- Verification/evidence: focused Study 7/7; related scroll/plugin 31/31; full
  UI 92 files / 698 tests; backend Study 10/10; typecheck and build passed;
  LamTools audit 84 files / 0 deviations; manual Study token scan found no
  off-scale literals; scoped diff check passed. Tauri dev launched and the
  app/backend connected. Build output retained the existing `::highlight`
  lightningcss warning.
- Limitations/pending: no Computer Use or pixel visual acceptance was run.
  Exact next entry point is user visual acceptance in the now-open Tauri Study
  mode. No deployment-specific blocker is known.
- Git disposition: Study UI/test files are untracked inside the existing
  broader dirty tree; `project_diary.md` and these two documents are modified.
  No staging, commit, revert, cleanup, or unrelated attribution was performed.

## Study graph layout closure (2026-09-18)

- Task ID/deployment: `study_obsidian_graph_archive` /
  `study_obsidian_graph_20260918`; state: `complete`.
- Outcome/material changes: Study graph rendering now uses a deterministic
  one-shot relation-aware force layout with label-aware spacing. Compact
  Obsidian-like dot/label nodes, theme-derived edges, hover/focus/selection
  direct-edge emphasis, saved/manual position preservation, and existing graph
  navigation, inspection, and pagination are retained.
- Viewport contract: persistence uses supported VueFlow `@init`
  `store/setViewport` plus `moveEnd.flowTransform`; unsupported
  `v-model:viewport` was removed. The viewport repair was independently
  Tester-verified PASS.
- Verification/evidence: focused Study 7/7; full UI 92 files / 698 tests;
  UI typecheck; production build; LamTools audit 84 files / 0 deviations;
  independent Tester PASS after viewport repair; scoped diff/whitespace
  checks passed. The existing `::highlight` build warning remains.
- Limitations/pending: no Tauri/Computer Use or pixel-level visual acceptance
  was performed per project instruction. No deployment-specific blocker is
  known. Exact next entry point: user visual acceptance in Tauri Study mode
  for layout, viewport/position persistence, and direct-edge interaction.
- Git disposition: read-only handoff; the shared tree remains heavily dirty
  with concurrent and untracked Study/session/context changes. Preserve them
  without attribution. No stage, commit, revert, cleanup, or diary edit was
  performed.

## Selection assistant target grounding closure (2026-09-18)

- Task ID: `selection_target_grounding_archive`. Deployment ID/state:
  `selection_target_grounding_20260917` / `complete`.
- Outcome/material changes: the exact selected quote is the primary target for
  lightweight selection-assistant calls. Prefix and suffix text provide
  disambiguation only. Every Ask follow-up re-anchors to the selected quote,
  so a short mark such as “英语周” does not silently broaden into the whole
  surrounding passage.
- Cache/history behavior: the prompt version invalidates old explain/translate
  cache entries, while per-mark Q&A history is preserved. The local dictionary
  path remains model-free.
- Verification/evidence: backend Study coverage passed 11 tests; focused
  frontend coverage passed 13 tests; full UI contract passed 92 files / 698
  tests; typecheck passed; and the independent Tester returned PASS with no
  P0/P1/P2 findings.
- Limitations: no real-model semantic exercise or Tauri visual exercise was
  performed, so semantic answer quality and visual presentation remain for
  later acceptance.
- Git disposition and next entry point: the shared tree remains dirty and
  uncommitted; unrelated and concurrent changes were preserved. No staging,
  commit, revert, cleanup, or unrelated attribution was performed. If this
  behavior is extended or accepted manually, begin with a real Tauri selection
  of a short term, then Ask and verify the response remains quote-grounded.

## Study Markdown translation and response rendering closure (2026-09-18)

- Task ID: `study_markdown_translation_archive`. Deployment ID/state:
  `study_markdown_translation_20260917` / `complete`.
- Outcome/material changes: SelectionAssistant explain answers, model
  translation fallbacks, and Ask-assistant replies reuse `MarkdownRenderer`
  with `mermaid=false`. User questions and dictionary entries remain plain
  text. Card body line-height is `1.35`, with compressed Markdown spacing.
- Backend contract: quote, prefix, and suffix are explicit sections;
  translate/explain/ask limits are 256/600/1200. Old `prompt_version`
  invalidation clears only explain/translate/dictionary entries and preserves
  thread history. The dictionary fast path does not call the model.
- Verification/evidence: `study.test.ts` 7/7; `test_study.py` 11/11; full UI
  92 files / 698 tests; typecheck and build passed. The only build note is the
  existing `::highlight` lightningcss warning. Tauri session 13230 remains
  running and application RPC activity was confirmed.
- Limitations/pending: no Computer Use or pixel-level visual acceptance was
  performed. Exact next entry point is user visual acceptance in the open
  Tauri Study mode. No deployment-specific blocker is known.
- Git disposition: shared tree remains dirty and uncommitted; Study files may
  remain untracked. `project_diary.md` and the two assigned documents are
  modified. No stage, commit, revert, cleanup, or unrelated attribution was
  performed.

## Study shared chat primitives and node-session closure (2026-09-18)

- Deployment ID/state: `study_shared_primitives_20260918` / `complete`.
- Study no longer owns a parallel chat implementation. Its chat page uses the
  Core thread, history paging, message actions, composer, single sentinel
  observer, and complete attachment flow (picker, tray, drag/drop, paste,
  attachment-only send, and historical rendering).
- Core attachment storage now accepts plugin-owned colon session IDs and maps
  them to stable filesystem-safe directories while preserving the exact
  logical session ID in records and runtime input.
- Conversation architecture now consists of the compatible builder session
  `study:main` plus one session per knowledge node. The builder is titled
  `知识图谱`; node sessions keep teaching/exam context isolated. Unicode and
  punctuation-heavy node IDs map to stable hashed session IDs with the exact
  source ID retained in metadata.
- Agent/Workflow/Study switching no longer leaves the Workflow session visible
  in Agent. Node clicks select the corresponding node thread and prefill the
  learning prompt without sending it.
- Verification: backend Study/attachment HTTP 22/22; focused Study/mode/scroll 9/9;
  attachment/composer tests 35/35; full UI 92 files / 698 tests; typecheck,
  production build, design audit (84 files / 0 deviations), and diff check
  passed. The existing `::highlight` build warning remains. Computer Use was
  intentionally not used.
- Git disposition: the shared worktree remains dirty and uncommitted, including
  pre-existing unrelated changes and untracked Study files. Nothing was staged,
  committed, reverted, or cleaned.

## Study skill-pack integration closure (2026-09-18)

- Task ID: `study_skills_integration_20260918`. Deployment ID/state:
  `study_skills_integration_20260918` / `complete` for the requested Study
  scope.
- Source/evidence: the supplied Study pack was extracted under
  `E:\LamTools\.tmp\study-skills-integration-20260918\study-skill-pack`;
  `INTEGRATION.md`, `study-system.md`, and all four skill files were read
  before implementation. The durable Study module contract remains in
  `core/docs/study.md`.
- Outcome/material changes: the four skills are registered as bundled Study
  skills and only load through the existing SkillRegistry/`load_skill` route
  for `study:study`. The backend auto-loads `study-system.md` and retains
  shared safety, permission, tool, and verification protocols while omitting
  generic business/project workflow prompts. Existing Agent Loop, tool IDs,
  live/queue `instructions` and `request_local_late_context` forwarding,
  `study:main`/node sessions, UI components, and right-click lightweight calls
  remain the single implementation path.
- Data/contract completion: notes, learning context, help records, evaluated
  state, answer isolation, private answer/rubric storage, batch-save versus
  explicit-submit exam lifecycle, isolated generation/grading, review evidence,
  validation/signing, and idempotent score writeback are covered. Public
  reads and grading output do not expose answer/rubric content. Textbook,
  PDF, knowledge-base, and RAG integration was deliberately not implemented;
  the Study UI was not redesigned.
- Verification performed: `py -3.14 -m pytest tests/test_study.py
  tests/test_bundled_plugins.py
  tests/test_workflow_operations.py::test_workflow_disabled_at_start_can_reenable_and_restart_watcher -q`
  passed `33`; `npm run test:contract -- --run tests/study.test.ts
  tests/core-live-composer-controller.test.ts` passed `19`; prior recorded
  typecheck, build, and full UI contract passed (`699` tests). Build warnings
  are the existing LightningCSS `::highlight` and ineffective dynamic-import
  warnings. A direct rerun of the eight known non-Study failures produced
  `57 passed, 8 failed`.
- Non-Study failures and evidence: the three persistence tests
  `test_core_operation_persists_run_items_and_snapshot`,
  `test_core_operation_publishes_run_items_while_turn_is_running`, and
  `test_core_approval_continuation_persists_approved_tool_and_final_snapshot`,
  plus the three live tests
  `test_live_turn_reuses_accepted_id_for_core_events_terminal_and_task_registry`,
  `test_live_turn_steer_reaches_the_next_model_call_before_a_no_tool_final`,
  `test_live_queue_guidance_reaches_the_next_model_call` fail because
  `core_projects` is absent. The live client E2E matrix and live resume
  page-cursor test return empty resume events. The full Core suite was not
  rerun after the unrelated Workflow expectation correction, so the earlier
  `2077 passed, 9 failed, 2 skipped` aggregate remains the only full-suite
  aggregate and is not silently upgraded to a claimed `2078/8` result.
- Limitations/next entry point: no Computer Use, Tauri manual, pixel-level,
  or real-model semantic acceptance was run. If requested, begin with a
  user-owned Tauri Study pass, then handle the eight Core baseline failures in
  a separate scope. No deployment-specific Study blocker is known.
- Git disposition: Archivist changed only the assigned progress and latest
  session documentation by appending this handoff. The shared tree remains
  dirty and uncommitted; unrelated/concurrent modifications and untracked
  Study files were preserved. No stage, commit, revert, cleanup, or diary
  edit was performed.

## Study v2 knowledge workspace closure

- Task ID/deployment/state: `study_v2_closure` /
  `study_complete_v2_20260918` / **paused at a stable, tested boundary**.
  The source package was extracted to
  `E:\LamTools\.tmp\study-complete-v2-20260918\Study_v2.0`; its README and
  design/contracts/performance documents were read before the repository
  audit. The P0–P3b implementation is present; P4 textbook/PDF/knowledge
  base/RAG and P5 remain deferred interfaces.
- Implemented architecture and principal paths: the bundled plugin under
  `core/src/lamtools_core/plugins/bundled/study/` owns the scoped SQLite
  `StudyStore`, backend adapter, exam/sign/marks handlers, operation/tool
  contracts, `study-system.md`, and the four requested skills. Existing
  tool IDs remain `get_knowledge_net`, `build_knowledge_net`, `exam`, and
  `sign`; the registry exposes their mapped operations only to Study. Core
  `base_agent.py` injects the Study prompt while preserving shared safety,
  permissions, tool protocol, streaming, cancellation, and session/message
  persistence. `core/ui/src/study/` adds the v2 Overview/Graph/Notes/Subject
  Tree semantics, scoped search/pins, local graph layout, node session
  bindings, marks, selection assistant, and note manager on the existing
  Workbench/chat components. Core `mem/` and `runtime/arrange.py` provide
  scoped memory and curation/fencing seams shared with Dreaming.
- Data/migration behavior: `study.db` is created in the runtime application
  data directory. Startup creates scoped records, separate structure/state
  revisions, signed cursors, request/sign receipts, an outbox, session
  bindings, notes/blocks, curation tasks, pins, and soft-delete snapshots.
  The idempotent migration copies legacy `study_entities`/`study_meta` into
  the explicit local-compatibility scope and repairs the note-block composite
  foreign key. Backups were made with SQLite `.backup` at
  `E:\LamTools\.tmp\study-v2-backup-20260918-0158` for
  `core/data/core.db` and `core/core.db`; both reported
  `integrity_check=ok`. No real `study.db` was present during audit, so the
  migration test is synthetic and does not represent a user-library run.
- Verification evidence: recorded full Core result is `2113 passed, 2
  failed, 2 skipped`; the two failures are pre-existing
  `thread.resume` snapshot-only protocol mismatches. Shared UI result is 92
  files / 702 tests; typecheck and production build passed. Independent
  reruns on 2026-09-18: `tests/test_study.py` 36 passed,
  `tests/test_memory_v2.py` 12 passed, and `tests/test_arrange_fencing.py`
  3 passed. Build warnings are the existing LightningCSS `::highlight` and
  ineffective dynamic-import warnings. The P0 audit remains
  `core/docs/AUDIT_STUDY.md`; module usage is documented in
  `core/docs/study.md`.
- Material incomplete items: `operations.jsonc` still declares Study RPCs
  `auto_allow`, so action-level approval/policy is not complete. Exam and
  lightweight text calls still use the context LLM client directly and need
  the shared Direct ModelGateway retry/cancel/usage accounting. The runtime
  SQLite versions are Python 3.50.4 and CLI 3.50.6, below the design
  3.51.3 WAL-fix floor; no engine upgrade was performed. No real-model
  semantic test, Tauri/mobile visual test, or performance-budget run was
  executed. These are release/acceptance gaps, not claims of failure in the
  completed local contracts.
- Exact continuation point: implement and test the Study action-policy/
  approval boundary, route isolated exam/quick-assist model calls through the
  shared Direct ModelGateway, and establish the supported SQLite engine and
  per-connection policy. Then run the migration-copy against an approved
  user backup, real-model isolation/quality, Tauri visual, and performance
  acceptance suites. Preserve the existing Core loop/UI and the current
  backups while doing so.
- Git/read-only handoff: baseline was
  `56d45e4e9257ec1be9c98a948783b23ff598183d` on
  `codex/multiplatform-dev`; the worktree was already heavily dirty and Study
  files were mostly untracked. The Study-specific paths above and the
  cross-cutting Core/UI edits overlap concurrent user work, so attribution is
  intentionally conservative. This closure changed only
  `agent_docs/project_progress.md`, `agent_docs/latest_session_work.md`, and
  `core/docs/study.md`; no stage, commit, reset, checkout, clean, database
  deletion, push, or release was performed. Exact next entry point is the
  action-policy/Direct-Gateway/SQLite follow-up above.

## Study reset and performance closure

- Task ID/deployment/state: `study_perf_reset_closure_20260918` /
  `study_perf_reset_20260918` / **complete**. Study content was backed up
  before clearing at `E:\LamTools\.tmp\study-reset-20260918-111814`;
  the directory contains `study.db` and `core.db`. After Tauri startup,
  exactly one empty `study:main` shell snapshot/binding was regenerated, with
  zero knowledge, notes, exams, marks, receipts, outbox, history, or runtime
  rows.
- Root cause/fixes: the unsupported `study.session.binding` alias caused the
  global five-retry exponential backoff (about 6.2 s worst case). The UI now
  uses canonical `study.session`; duplicate refresh/select work was removed;
  known bindings skip session refresh; binding and overview load in parallel;
  the sidebar does not eagerly fan out every course; graph get/layout are
  parallel; and VueFlow is split into an async `StudyGraph` chunk. Initial
  Study and `PluginModeHost` reuse `HistoryLoadingIndicator`; later switches
  retain the Core thread; mode changes preserve the connection-scoped App
  Server client; command catalog/goal/scroll work is parallelized.
- Runtime evidence: Tauri restarted with frontend `5173` and backend `59690`.
  On the empty DB, backend RPC elapsed time was 58.7 ms for `study.session`
  and 41.7 ms for `study.get`. CLI wall time was about 1 s because it includes
  process and WebSocket startup.
- Verification: focused UI 18/18; full UI 92 files / 706 tests; typecheck;
  `build:app`; backend 48 passed with 2 deprecation warnings; design audit
  84 files / 0 deviations; `git diff --check` had no errors (only normal
  line-ending warnings); independent Tester passed 3 files / 17 tests.
- Limitations/next entry point: no Computer Use or perceptual timing run was
  performed. Real Tauri visual/interaction timing remains user acceptance.
  The worktree is heavily dirty and this closure made no commit, reset,
  cleanup, database deletion beyond the explicitly backed-up Study reset,
  push, or release.

## Study graph primary-progress closure

- Task ID/deployment/state: `study_graph_primary_progress_20260918_closure` /
  `study_graph_primary_progress_20260918` / **complete**.
- The old Study overview UI/page was removed. The former sidebar location is
  now `管理你的知识`; `图谱` remains. The explicit `manage` action clears
  the selected node and restores the existing `map` primary binding/default
  main session, without a duplicate `study.session` request when the binding
  is cached. No backend, schema, or database changes were made.
- Top-level course nodes reuse the existing overview aggregate and render
  exact course names as large circular spheres with an external SVG progress
  ring and readable/clamped percentages (`total <= 0` renders 0%). Deeper
  nodes are unchanged. Ring bounds were aligned with the existing 112px
  layout spacing.
- Verification: focused Study 15/15; full UI 92 files / 708 tests; UI
  typecheck and `build:app` passed; backend Study 38 passed with 2
  deprecation warnings; design audit 84 files / 0 deviations; independent
  Tester PASS. Only existing `::highlight`, dynamic-import, and chunk build
  warnings remain. DOM/CSS/mock-RPC contracts were verified.
- Limitation/Git handoff: computer-use and live Tauri visual/perceptual
  inspection were intentionally not run; visual and interaction timing remain
  user acceptance. The worktree is heavily dirty and unrelated/concurrent
  changes were preserved; no production/test files, diary, commit, reset,
  cleanup, push, or release was performed by this closure.

## Glass material unification pause (2026-09-18)

- Task ID: `glass_material_unification_archive`. Deployment
  `glass_material_unification` is `paused` before implementation because the
  proposed all-glass-like-surface scope requires user confirmation.
- Evidence retained: the supplied Liquid Glass brief defines high-transmission,
  low-blur optical glass with restrained highlights, gray-green edge refraction,
  and soft short shadows; the repository has a shared `optical-glass.css`
  primitive; the read-only inventory and dirty-tree review were completed.
- Disposition: no production or test changes, no tests/build checks, no Tauri
  visual acceptance, and no Computer Use. `project_diary.md` and unrelated
  dirty/untracked work were preserved; nothing was staged, committed, reverted,
  cleaned, or attributed to this deployment.
- Exact next entry point: once the user confirms scope, unify true glass
  material surfaces through the shared primitive. Exclude mere modal dimmer
  backdrops and opaque panels; keep shape/layout decisions separate from
  material treatment.

## Study skill v3 refactor closure

- Task ID/deployment/state: `study_skill_refactor_v3_20260918_docs` /
  `study_skill_refactor_v3_20260918` / **complete**. Snapshot evidence is at
  `E:\LamTools\.tmp\study-skill-v3-snapshot-20260918-135315`. The exact v3
  package files for `build-map`, `teach`, `answer`, `take-exam`, and
  `prompts/study-system.md` were copied into
  `core/src/lamtools_core/plugins/bundled/study/`.
- `curate-notes` was retained at
  `core/src/lamtools_core/plugins/bundled/study/future/curate-notes` and is
  deliberately not registered because the Agent Loop lacks a callable notes
  tool/capability gate. `core/src/lamtools_core/plugins/bundled/study/eval_manifest.py` and
  additional `test_study` coverage provide the evaluation surface.
- Host smoke PASS: 4 active skills plus 1 future-gated skill, 14 references,
  and 40 evaluations with `run=0` / `NOT_RUN=40`. Focused Python coverage
  passed 50 tests. UI 708 tests, typecheck, UI build, desktop build, package
  validation, and examples 14/14 passed. Examples ran under Python 3.9
  because Python 3.14 lacks sympy. The stable Core full suite result is 2116
  passed / 2 skipped / 2 failed; both failures are unrelated existing
  `thread.resume` event-page tests.
- Audit gaps: no source version/archive service, no verified technical image
  generation, strict schema limitations, and no `study.text.cancel`.
  `quick_validate` cannot accept the package's standard compatibility
  frontmatter, so that validator result is not represented as a pass.
  Preserve the dirty worktree and treat these as follow-up items; this
  documentation closure changed no production/test files or diary and made
  no commit, reset, cleanup, push, or release.

## Glass material unification implementation closure (2026-09-18)

- Task ID: `glass_material_unification_impl_archive`. Deployment
  `glass_material_unification_impl` is **complete** and supersedes the
  earlier paused planning deployment after user confirmation.
- Material implementation: `.optical-glass` in the shared UI now centralizes
  tokenized transmission/blur, saturation, brightness, contrast, fallback,
  localized reflection, gray-green refraction, inset edge treatment, and soft
  shadow. Consumers are WorkspaceShell's right drawer; shared context-menu
  root/submenus; Study SelectionAssistant; Workflow node catalog popover and
  runtime dock; LamToolsApp jump-to-latest and Goal; and MobileTopBar's
  button/sync/account controls. `core/desktop/index.html` mirrors the same
  startup optics before Vue mounts, while the native desktop shell supplies
  Acrylic.
- Boundary: modal dimmer backdrops, ordinary opaque panels, the left drawer,
  and Workflow node cards are intentionally not glass. Independent Tester
  PASS followed repair of blue startup refraction and the 48% inset to
  gray-green and 56%.
- Verification: 93 UI files / 712 tests passed; focused glass/startup
  recheck 21 tests; UI typecheck/build, desktop Vite build, `cargo check`,
  LamTools audit 84 files / 0 deviations, and scoped/full diff checks passed.
  No Computer Use or Tauri visual validation was run per user instruction.
- Git/evidence handoff: retain the heavily dirty, concurrent, untracked tree.
  Archivist changed only these two documentation files; no diary edit, stage,
  commit, revert, cleanup, or unrelated attribution occurred. If visual
  acceptance is later authorized, begin with the listed consumers and the
  startup surface in Tauri.

## Glass specular quieting closure (2026-09-18)

- Task ID: `glass_specular_quieting_archive`. Deployment
  `glass_specular_quieting` is **complete** as a focused correction after the
  glass unification.
- Material delta: shared upper-left reflection changed from 26% to 10%, with
  footprint 92×42 reduced to 54×24. Startup light/dark optics and edge layers
  now use 38×20 at `.06/.05` and 26×4 at `.09/.08`; every other material
  parameter is unchanged.
- Verification: focused 2-file / 21-test glass/startup coverage passed;
  LamTools audit 84 files / 0 deviations passed; relevant diff check passed;
  independent Tester PASS. No Computer Use or Tauri visual validation was run
  per user instruction.
- Git disposition: heavily dirty, concurrent, and untracked work remains
  preserved. This closure changed only the two assigned documents; no diary or
  production/test files were edited, and nothing was staged, committed,
  reverted, or cleaned.

## 0.3.4 audit/build handoff (2026-09-18)

- Deployment: `audit_fix_bump_20260918`. Current version: `0.3.4`. No commit,
  tag, push, release, reset, clean, or unrelated-file rollback was performed.
- Correctness fixes: `thread.resume` now returns journal deltas alongside the
  optional snapshot; local HTTP readiness probes bypass configured proxies;
  mobile cached projects preserve and validate `iconKey/colorKey`; shared GSAP
  animation modules safely import without a browser `window`.
- Final checks: Python 2122 passed / 2 skipped; UI 93 files / 725 tests;
  mobile 11 files / 46 tests; desktop Rust 53 tests; relay 11 tests; UI/mobile
  typechecks and production builds passed; Rust fmt/check/clippy passed with
  non-blocking structural warnings; npm production audits found zero
  vulnerabilities; design audit was 84 files / 0 deviations; `git diff --check`
  had no whitespace errors.
- Package output:
  `E:\LamTools\core\desktop\src-tauri\target\release\bundle\inno\Sunday_0.3.4_x64-setup.exe`
  (93,961,819 bytes). It installed successfully to `E:\setuptest\0.3.4`; both
  installed executable paths and product version 0.3.4 were verified.
- Remaining verification: the installed app could not remain running because
  the pre-existing development executable
  `E:\LamTools\core\desktop\src-tauri\target\debug\lamcore.exe` (PID 7000)
  holds the global Tauri single-instance lock. It exited cleanly with code 0,
  and the setup skill forbids stopping other-directory/dev processes. After the
  developer closes that instance, rerun
  `.\.agents\skills\lamtools-setup-install\scripts\install_setup.ps1 -Version 0.3.4 -ForceCloseExisting`
  to capture installed main/backend PIDs.

## PDF ingestion fix handoff (2026-09-18)

- Root cause: `web_fetch` passed successful `application/pdf` responses to `httpx.Response.text`, so the model received `%PDF` binary garbage. The upload path separately labeled PDFs as unparsed/deferred, and both main/sub-agent assembly could drop valid text-only attachment context.
- Implemented shared in-memory PDF normalization in `tool/document_normalize.py`; `web_fetch` detects MIME or PDF magic and parses off-loop; attachment runtime parsing reuses the same normalizer; main/sub-agent assembly now preserves index text and performs blocking parsing/file reads through `asyncio.to_thread`.
- Added coverage for PDF MIME and magic detection, invalid PDFs, uploaded PDF extraction, and text-only sub-agent attachments. The real TI URL extracted successfully. Final verification: Core 2128 passed / 2 skipped; UI 727 passed plus typecheck/build; desktop Vite build passed; scoped and full diff checks passed. No version bump, package, commit, reset, cleanup, push, or release was performed.

## Study exam model-routing correction handoff (2026-09-18)

- Task ID: `study_exam_model_routing_fix_docs`. Deployment
  `study_exam_model_routing_fix` is **complete**. The source failure was an
  isolated Study exam call without the active runtime `model_id`, producing
  `model id is required when no routing setting is available`; the generic
  retry path then retried a deterministic configuration error.
- Implemented behavior: isolated Study exam authoring, grading, and review
  carry the active runtime model through approval. Explicit operation-level
  model selection overrides inherited state. Arrange and Workflow queue
  scheduling inherit and persist the runtime model, while explicit queue/node
  overrides win. Missing model/provider/base URL now fails immediately without
  silent provider/model fallback or retry churn.
- Source/test surfaces reviewed for this handoff include the bundled Study
  backend/exam/marks paths, live runtime stamping, `runtime/arrange.py`,
  Workflow operation/queue/runtime resolution, shared LLM retry classification,
  and `core/tests/test_study.py`, `test_workflow_operations.py`,
  `test_llm.py`, plus related provider/runtime tests. The main Agent Loop and
  existing Study UI were preserved.
- Verification evidence: targeted suites passed. The full Core run was
  `2142 passed, 2 skipped, 1 unrelated localhost HTTP probe timeout`; an
  isolated rerun of the timeout case passed `1`. A later focused
  provider/routing run passed `67 passed, 1 skipped`, and an independent
  verifier returned PASS. Do not collapse these into a claim of one clean
  full-suite run.
- Not run / limitations: no network or UI/Tauri test, real-model semantic
  acceptance, or database migration was executed for this fix. No database
  schema change was made. The worktree remains heavily dirty and uncommitted;
  unrelated user/concurrent changes were preserved. Exact next entry point is
  maintainer review of the routing diff, followed by user-owned Study/Tauri
  acceptance if desired.
- Git handoff: read-only status showed the pre-existing broad dirty tree,
  including the two assigned documentation files and concurrent Core/UI,
  Study, Workflow, and configuration edits. No stage, commit, reset, checkout,
  clean, database deletion, push, or release was performed.

## Study agent grading correction handoff (2026-09-19)

- Scope: repair formal Study exam grading so the current Agent can use the
  persisted reference answer only when the active context no longer contains
  the original exam standard, then directly judge the submitted work. The
  grading path no longer invokes an isolated model and no longer requires an
  exact match between a choice response and the stored option text.
- Behavior: the Agent owns semantic grading, including correct, partial, and
  incorrect outcomes and step-level allocation. The persisted exam record
  retains reference answers and scoring guidance for recovery. Saved grading
  preserves partial credit, `step_scores`, grading `version`, and idempotent
  writes; code-level checks remain limited to persistence and consistency
  invariants rather than interpreting answer wording.
- Evidence: focused Study grading coverage passed 50 tests. The full Core run
  recorded 2143 passed / 2 skipped / 1 temporary `PermissionError`; the
  affected test passed when rerun. UI and desktop builds passed, and an
  independent Tester passed the change.
- Limitations: no real production-model grading request and no Tauri/manual
  interaction retest has been executed. The user plans to retest the formal
  exam in the 极限 lesson. If it fails, begin with the persisted exam record,
  grading event, model request/response, and idempotency receipt for that exam;
  do not infer a semantic result from static tests.
- Continuation point: wait for the user's 极限-node retest, inspect the actual
  grading trace if needed, and then update this handoff with the observed live
  result. Preserve the dirty worktree and do not claim production-model or
  Tauri acceptance before that retest.

## Study note curation connection (2026-09-19)

- Inspected the persisted 极限 turn `8dcd14790c38`. The model explicitly found
  no notes tool, searched unrelated workspace directories, and returned a
  draft saying it could not save. No note database failure occurred.
- Added Study tool ID `notes` mapped to the existing `study.notes` operation,
  registered `curate-notes` only in `study:study`, and kept the tool visible
  from the first Study request so loading the skill does not mutate the model's
  tool prefix. No second note service, database, or UI was added.
- Agent note creates are normalized to unlocked AI blocks. The Agent path strips
  `user_edit`, so a forged request cannot overwrite an existing locked user
  block. Existing revision conflict behavior is unchanged.
- Verification completed: `tests/test_study.py` plus
  `tests/test_bundled_plugins.py` passed 50 tests; Study compileall passed. A
  full Core run reached 80% before being deliberately stopped because the
  cache-stability design changed, so it is not a completed result.
- Follow-up UI correction: the real saved 极限 note contained eight coherent
  sections, but `NotesManager.vue` rendered every AI block as a separate card
  and textarea. Reading mode now joins the ordered blocks into one Markdown
  document; block editors appear only after selecting Edit. Study UI tests
  passed 17/17, typecheck passed, and the UI build passed with only the known
  `::highlight` minifier warnings. Tauri received the change through HMR.

## Chat instruction navigator design pause (2026-09-19)

- Task ID/deployment/state: `chat_turn_navigator_design_20260919_archive` /
  `chat_turn_navigator_design_20260919` / **paused** pending user consensus.
  Scope was a read-only design/code audit for an ultra-minimal navigator in the
  Core chat area. No production or test files changed; the attached screenshot
  was treated only as visual reference.
- Verified implementation seams: `.thread` in
  `core/ui/src/app/LamToolsApp.vue` is the scroll container; each `MessageView`
  rendered by `core/ui/src/components/ChatThread.vue` receives
  `data-message-id`; `LamToolsApp.vue` already exposes `locateMessage`, which
  loads older history when needed and centers/highlights the target; history
  pagination is already buffered and anchored; the initial history request
  uses `turn_limit: 10`; `.optical-glass` is the shared glass primitive; and
  the narrow layout has a `@media (max-width: 640px)` boundary.
- Proposed direction: add a ChatGPT-style left-edge instruction navigator
  whose points correspond only to user messages. The active point is longest;
  inactive points progressively weaken. Hover/focus previews should use the
  shared optical-glass card, while click navigation should call
  `locateMessage`. Avoid a second scroll observer and reuse the existing
  scroll/history machinery.
- Decisions still required before implementation: (1) all historical user
  instructions versus only the currently loaded window; (2) preview content as
  user-only text versus user text plus a paired response summary; (3) mobile
  behavior as hidden versus a compact overlay. No Computer Use or Tauri run
  was performed. Relevant UI files are already dirty/concurrently edited and
  must be preserved.
- Verification/disposition: source seams were inspected read-only; no tests,
  builds, visual acceptance, staging, commit, reset, revert, or cleanup were
  performed. Next entry point is user resolution of the three decisions,
  followed by a bounded implementation and Tauri visual acceptance; do not
  infer acceptance from the reference screenshot.

## Chat instruction navigator implementation closure (2026-09-19)

- Task ID/deployment/state: `chat_turn_navigator_impl_archive` /
  `chat_turn_navigator_impl_20260919` / **complete**. The previously paused
  design was implemented in Core chat. The server-side outline is exposed as
  `thread.outline`, with CLI parity through `session outline`. It emits only
  top-level, renderable `userMessage` rows and pairs each prompt with a
  response excerpt, capping both excerpts at 240 characters.
- UI outcome: `ChatOutlineNavigator.vue` renders evenly indexed markers over
  the full history. The active marker is chosen from the mounted user message
  nearest 38% of the viewport. The preview uses shared `.optical-glass` and
  click selection calls the existing `locateMessage`, so unloaded targets still
  use established history pagination/centering behavior.
- Interaction/performance contract: keyboard focus and activation are wired;
  reduced-motion behavior is honored; marker geometry accounts for device
  pixel ratio; RAF and `ResizeObserver` resources are explicitly cleaned up.
  The navigator is hidden at `max-width: 640px`. No second scroll observer was
  introduced; the existing chat scroll machinery remains authoritative.
- Verification evidence: backend focused tests passed 50; the broader executor
  set passed 181. Final frontend focused tests passed 27; UI typecheck passed;
  `build:app` passed with existing warnings; the LamTools design audit covered
  85 files with 0 deviations. An independent Tester passed. Its earlier RAF
  S3 finding was repaired, after which the navigator-focused 7 tests and
  typecheck passed.
- Limitations/disposition: no Computer Use or Tauri visual validation was run
  at the user's request, so visual placement and interaction timing remain
  user-owned acceptance. Read-only Git handoff shows a dirty worktree with
  concurrent/untracked changes preserved; no commit, stage, reset, revert, or
  cleanup was performed. If visual acceptance is authorized, begin with the
  navigator in Tauri, then verify the <=640px hidden state and full-history
  navigation after pagination.

## Study Obsidian notes phase 1 closure (2026-09-19)

- Task ID/deployment/state: `study_obsidian_phase1_archive` /
  `study_obsidian_phase1` / **complete**. The existing NotesManager now
  reads the ordered NoteBlocks as one Markdown document, supports edit versus
  preview, extracts h1-h6 headings for an outline, and resolves
  `[[wikilink]]` targets for notes and knowledge nodes within the active Study
  scope. Backlinks use the same scoped resolution.
- Navigation uses stable note/node IDs. Unresolved wikilinks are preserved and
  do not block saving. The existing `update_blocks` write is atomic, retains
  the block/source rows, and rejects duplicate block IDs. This phase added no
  `.md` shadow store, link table, second Agent Loop, or wholesale UI rewrite.
- Verification evidence: focused backend tests passed 53; focused UI tests
  passed 21; final UI typecheck and build passed; design audit covered 85
  files with 0 deviations; and independent Tester verification was PASS.
  Full UI 739 passed and full Core 2152 passed / 2 skipped were run before the
  final narrow atomic-boundary fixes, followed by focused final rechecks.
  Existing `::highlight` and dynamic-import build warnings remain.
- Limitations and handoff: no Computer Use/manual Tauri acceptance, data
  migration/deletion, commit, push, or release was performed. Retest at
  Study > 笔记 using the existing 极限 note: edit, preview, save, then test
  `[[another note]]` and `[[knowledge node|label]]`. This is the exact next
  entry point; preserve the heavily dirty worktree and do not infer visual
  acceptance from static checks.

## Study packaged RPC hotfix closure (2026-09-19)

- Task ID/deployment/state: `study_rpc_packaged_hotfix_archive` /
  `study_rpc_packaged_hotfix_20260919` / **complete**. The production-only
  failure was the canonical Study backend import resolving `study-system.md`
  beside the module, although PyInstaller places the plugin data below the
  frozen bundled resource root. `bundled_plugins_dir()` now supplies that
  fallback; Agent Loop, Study RPC IDs, and UI contracts are unchanged.
- Packaging smoke now opens the WebSocket, initializes it, and performs a real
  `study.session` request. Source-focused coverage passed 55; independent
  checks passed Study 44 and bundled-boundary 10; PyInstaller packaged smoke
  passed. Installed `E:\setuptest\0.3.5` backend PID 29728 on port 49758
  returned non-empty `session_id` `study:main`.
- Rebuilt installer: 93,990,114 bytes,
  SHA256 `5E26B6F280DC5E8D8A4B20338569488A036E370E34695840493B592C3111BE5A`.
  The public download was replaced and the redownload hash matched. Server
  backups were created at
  `/var/www/lamtools/Sunday_0.3.5_x64-setup.exe.before-study-rpc-hotfix-20260919T143333Z`
  and the corresponding `Sunday-latest...` path; the temporary SSH key and
  upload directory were removed.
- Limits/Git handoff: no full repository test result is claimed. No commit,
  tag, or push was made; the heavily dirty worktree and unrelated user and
  concurrent changes remain preserved. Exact next entry point is installed
  0.3.5 Study acceptance. If it regresses, start with the frozen resource
  resolution and `bundled_plugins_dir()` evidence rather than changing the
  Study RPC or prompt contract.

## Study notes UX optimization closure (2026-09-20)

- Task ID/deployment/state: `study_notes_ux_20260920` /
  `study_notes_ux_20260920` / **complete**. This closure hardened the full
  Study notes path: trusted host writer and Agent ownership enforcement,
  precise `study/changed` broadcasts, code-safe typed wikilinks, node
  backlinks, and Study CLI `search`/`pin` parity. NotesManager now projects
  Markdown without trimming away syntax, reports detail loading/error/retry,
  refetches after save with stale-response protection, guards note-scoped
  navigation when drafts exist, shows provenance/unresolved-link feedback,
  handles setext/DOM outlines, and honors reduced motion. `curate-notes` is
  version 3.1.0; the Study system prompt documents read-first, minimal
  incremental writes, ownership, conflict, source-honesty, and receipts.
- Verification evidence: backend Study trio 59 passed; focused frontend 31
  passed; `npm run typecheck` passed; `npm run build` passed with the existing
  lightningcss `::highlight` and ineffective dynamic-import warnings;
  compileall and scoped whitespace checks passed; the LamTools design audit
  covered 85 files with 0 deviations. Independent Tester conclusion: no P0-P2
  defects remained after the CommonMark indented-code wikilink fix.
- Scope deliberately excludes auto-save and delete/restore. No Computer Use or
  Tauri visual acceptance was run. Read-only Git handoff confirms a heavily
  dirty/untracked workspace, including Study files and concurrent edits; no
  stage, commit, reset, revert, cleanup, or release occurred. Exact next entry
  point, if visual acceptance is requested: Study > 笔记, then exercise
  read/edit/preview/save, draft navigation, typed links/backlinks, search,
  pinning, and retry/error states. Do not infer this acceptance from static
  checks.

## Linux/macOS desktop distribution planning handoff (2026-09-20)

- Task ID/deployment/state: `multiplatform_planning_archive` /
  `linux_macos_desktop_20260920` / **paused** pending user consensus. Goal:
  plan Linux and macOS desktop distributions without attributing changes to
  the already heavily dirty workspace.
- Verified blockers: the current package handoff discovers the Windows
  `LamCore.exe` sidecar; packaging is PowerShell/Inno-only; release and update
  code select only `Sunday_*_x64-setup.exe`; Linux secure storage is currently
  in-memory; install-adjacent user data does not map safely to a signed macOS
  `.app` or an AppImage; hook fallback uses Windows `APPDATA`/`AppData`; and
  there is no native Linux/macOS desktop CI. These are blockers to a reliable
  distribution, not claims that the shared application architecture is
  non-portable.
- Portable base and constraint: the shared `LamToolsApp`/Workbench and
  transport contract, Rust/Tauri shell, Python Core backend, JSONC config, and
  CLI are reusable. PyInstaller and Tauri artifacts must be built on native
  runners for each target OS; a Windows build cannot certify Linux/macOS
  artifacts.
- Recommended scope, not yet approved: Linux x64 AppImage + `.deb`; separate
  Intel and Apple Silicon DMGs; Linux/macOS standard data roots while
  preserving Windows paths; Secret Service/Keychain secret storage; native
  packaged smoke tests; and platform-aware update plus website download
  assets.
- Required decisions: confirm Apple Developer ID signing/notarization
  credentials and whether they are in scope; confirm whether this deployment
  only implements/tests or also bumps versions, tags, and publishes releases.
  No implementation should begin before those decisions.
- Work performed and limits: read-only audit only. No production or test
  files changed; no package build, CI run, signing, notarization, release, or
  Computer Use occurred. Read-only Git handoff found the existing dirty/
  untracked worktree and left it untouched; no stage, commit, reset, revert,
  cleanup, push, attribution, or `project_diary.md` edit occurred.
- Evidence: `core/desktop/PACKAGING.md`, `scripts/package.ps1`,
  `.github/workflows/release.yml`,
  `core/src/lamtools_core/update/checker.py`,
  `core/src/lamtools_core/plugins/hook_config.py`, plus the shared UI,
  transport, Tauri, and CLI paths. No test or build result is claimed for this
  planning deployment.
- Exact next entry point: after user consensus, define native-runner CI,
  platform data/secret roots, package names/assets, smoke contracts, and
  update/download selection; then implement and verify only the approved
  scope. Until then the plan remains paused.

## Study three-layer notes deployment closure (2026-09-20)

- Task ID/deployment/state: `study_notes_three_layer_20260920_archive` /
  `study_notes_three_layer_20260920` / **complete**. This closure updates the
  public Study documentation after the implementation and independent review.
- Current architecture: Raw is a trusted, immutable host snapshot of session,
  mark, exam, and node data; Resource is Agent-authored, versioned material
  with mandatory real `raw_ids`; Note is the user-visible multi-file Markdown
  vault. The `.md` body is the Note source of truth; SQLite retains index,
  relation, Resource/source links, revision/hash, and lock metadata. Historical
  NoteBlock tables are compatibility migration input only, not the runtime
  Note contract.
- Current Note UX: `path` builds the left Markdown file tree while
  `parent_id` remains a semantic parent relation. The Note page has top return
  and Notes-chat controls. Its overall relationship graph belongs to Note and
  is rendered in the right rail with Note-only wikilink and parent edges.
  Each Note references Resource and shows a low-key host-managed source footer.
- Editing contract: user and Agent edit the full Markdown document. Resource
  and Note writes use CAS; external file changes or stale revision/hash stop
  Agent overwrite. User-selected UTF-16 ranges block only Agent edits;
  `NOTE_REGION_LOCKED` returns the reason and overlap while the UI preserves
  the draft. User editing and lock management remain allowed.
- Verification evidence: Study backend trio 66 passed with 2 SQLite datetime
  deprecation warnings; Study frontend 31 passed; `npm run typecheck`,
  `npm run build`, Study compileall, and UTF-8 `curate-notes` quick validation
  passed; design audit 85 files / 0 deviations; independent Tester PASS. Build
  output has only existing `::highlight` and ineffective dynamic-import
  warnings.
- Limitations and Git handoff: no Computer Use/Tauri visual test, complete
  repository run, real-model semantic acceptance, real-user-library migration,
  package, commit, release, or data deletion was performed. Read-only Git
  inspection found the expected heavily dirty/untracked workspace; all user
  and concurrent changes remain untouched. Exact next entry point, if visual
  acceptance is requested, is Study > 笔记 with file-tree navigation, Notes
  chat, right-rail graph, source footer, full Markdown editing, CAS conflict,
  external-file handling, and user-lock overlap checks.

## Linux x64 desktop distribution implementation closure (2026-09-20)

- Task ID/deployment/state: `linux_desktop_closure_20260920` /
  `linux_desktop_implementation_20260920` / **complete**. This closes the
  approved Linux x64 implementation only. macOS is explicitly deferred; no
  macOS package, signing, notarization, or support claim was made.
- Outcome: the Linux desktop runtime selects a native extensionless `LamCore`
  sidecar and stores it in both package types as
  `lamcore-backend/LamCore`. Linux mutable state is rooted in Tauri
  `app_data_dir()`/XDG data paths, hooks honor `XDG_CONFIG_HOME`, and secure
  credentials use persistent Linux Secret Service storage. Windows retains its
  existing `.exe` sidecar and portable layout.
- Build entry point: `scripts/package-linux.sh`. It stages the repository in
  Ubuntu 22.04 WSL2 on the E-backed distro root
  `E:\WSL\Ubuntu-22.04`, keeps the Node/uv/Python/Rust toolchains, caches, and
  build staging on the Linux filesystem, and rejects `/mnt/c`. The script
  builds the Linux frontend and PyInstaller sidecar, produces AppImage and
  `.deb`, checks package contents, and runs backend plus Xvfb/isolated-D-Bus
  smoke. `.github/workflows/ci.yml` and `release.yml` call this script. The
  update checker prefers AppImage and falls back to `.deb`; the website links
  to both versioned GitHub `latest/download` assets.
- Final local artifacts for version `0.3.5` (not uploaded or published):

  - `core/desktop/src-tauri/target/release/bundle/appimage/Sunday_0.3.5_amd64.AppImage`
    — 186,821,112 bytes — SHA256
    `9A714A659577D6DBBC5DBF28B05ECB7FA6EDD4EABF607F6E1652E2879C47C345`.
  - `core/desktop/src-tauri/target/release/bundle/deb/Sunday_0.3.5_amd64.deb`
    — 120,093,070 bytes — SHA256
    `B869BF672284EA32F08FA9DAA8EB9DD8C9CFE428867F3B6E08FE63A32BB6B0C7`.
  - `artifacts/linux-x64/sidecar/LamCore` — 17,551,704 bytes — SHA256
    `77545A21C1BF49674043DCC2354BD662EB5F1FF004DA76371AAB5FAC6088ED8F`.

- Verification evidence: 15 Linux/update Python tests passed; website build,
  workflow YAML parsing, Bash syntax, `git diff --check`, and Rust release
  `cargo check` passed. REST/WebSocket/Study packaged smoke passed. The final
  AppImage and `.deb` were recognized as valid Linux packages and the `.deb`
  contained the executable sidecar. Independent AppImage smoke observed
  bundled `LamCore` PID 3883, returned expected timeout rc=124, and left no
  sidecar survivors. The broader run was 50/55; the five failures were
  pre-existing concurrent-network failures unrelated to this delta.
- Git/release handoff: read-only status showed a heavily dirty worktree with
  user and concurrent changes; it was not cleaned or attributed. No version
  bump, stage, commit, tag, push, GitHub release, or publication occurred.
  Exact next entry point is an explicitly authorized release review using the
  three hashes above. Any macOS work must begin with a separate native runner,
  data/secret-root contract, and signing/notarization decision.

## Mobile code review, refactor, and bug-fix closure (2026-09-20)

- Task ID/deployment/state: `mobile_review_refactor_closure_20260920` /
  `mobile_review_refactor_20260920` / **complete**. The mobile review fixed
  account refresh single-flight and logout/session-generation races, serialized
  account/workspace transitions, and fenced initialization after unmount.
  Connection/resume generations now reject stale results; Noise handshake
  message waits are bounded, cancellable, and cleaned up; SyncEngine close is
  fenced against started repository writes; and scoped memory-cache recovery
  restores the active bucket.
- The non-native credential default is memory-only. Tunnel cancellation and
  frame/type validation are hardened, and Capacitor identifies the app as
  `Sunday`. These changes preserve the mobile boundary around pairing,
  lifecycle, trusted devices, connection/wire, native capabilities, and local
  cache behavior.
- Independent Tester verification: `npm test -- --reporter=dot` passed 12
  files / 54 tests; `npm run typecheck`, `npm run build`, `npm run cap:sync`,
  and `git diff --check -- core/mobile` passed. Capacitor sync produced no
  visible native Git diff; build output contained only chunk/dynamic-import
  warnings.
- Limitations: no real Android/iOS device, LAN, Relay, or Tauri visual runtime
  acceptance was run; Windows CocoaPods/xcodebuild checks were skipped. Git
  handoff before this documentation amend was commit `bae53c33`; only
  `.tmp_glass_rg.txt`, `MyProject/`, `artifacts/`, and `docs.7z` remain
  intentionally untracked. Next entry point: real device/network acceptance
  of pairing, reconnect/resume, workspace switching, and cache recovery.

## DSH prompt comparison and Core prompt optimization handoff (2026-09-20)

- Task ID/deployment/state: `prompt_comparison_20260920` / **complete for the
  documented implementation scope**. This handoff records the selected prompt
  optimizations after comparing LamTools with DeepSeek Harness (DSH). DSH was
  pinned to official commit `ddefc45fbc7f8e46dd73185e68295696d1297887`
  (`0.1.6-alpha.2`, 2026-09-17), using the native text-turn expected snapshot
  and the system-prompt assembly design. Baseline evidence was about 4,276
  bytes for DSH native and 13,117 characters / 245 lines for the LamTools
  prompt. The post-change prompt measured 11,264 characters / 194 lines; the
  Skill index fell from 3,341 to 1,878 characters.
- Implemented prompt changes: `base_agent.py`, `default_agent.py`,
  `http_agent_app.py`, and `cli.py` now share the one-line identity
  `你是 Sunday Agent。`; `base_agent.py` centralizes the common
  Shell/file/search/web/Skill/evidence/progress rules; MCP server activation
  is described as on-demand and its output as untrusted external data. Study
  retains its narrower prompt while using the shared safety subset.
- Context and loading changes: `project_context.py` skips the exact seeded
  global `AGENTS.md` and `memory.md` templates but keeps customized content;
  `skills.py` emits compact trigger hints and leaves full Skill instructions to
  `load_skill`. The full project `AGENTS.md`, the guide/strategy/role layers,
  and existing plugin/MCP capability model were not removed or rewritten in
  this scope.
- Cache/compaction changes: the active plan and loop repair guidance now use
  late `user` messages tagged `metadata={"internal": true}`. This keeps the
  stable system prefix reusable while allowing the shared history to retain
  the guidance. Internal messages are excluded from recent-user selection and
  semantic compaction grouping; internal metadata is stripped before model
  dispatch. Guidance keys cover duplicate input, payload reassessment,
  no-progress recovery, tool-progress gates, failure diagnosis, and goal
  completion repair.
- Evidence references: `core/src/lamtools_core/app/base_agent.py:97`,
  `:101`, `:445`, `:479`, `:534`; `core/src/lamtools_core/app/project_context.py:119`
  and `:134`; `core/src/lamtools_core/skills.py:65` and `:97`;
  `core/src/lamtools_core/kernel/loop.py:868`, `:1024`, `:1116`, `:1144`,
  `:1158`, `:1188`, and `:1299`; and
  `core/src/lamtools_core/context_compaction/planner.py:135` and `:238`.
- Verification status: regression tests were added for the canonical identity
  and consolidated tool protocol, seeded-template filtering, compact Skill
  index/full on-demand load, late internal plan messages, internal repair
  metadata, and compaction grouping. The focused suite passed 259 tests; the
  entrypoint/plugin/Study suite passed 237 with 1 skip. `compileall` and
  `git diff --check` passed. No Tauri visual check is applicable to this
  backend prompt change.
- Git/disposition: read-only inspection found the expected heavily dirty,
  concurrently edited worktree. No stage, commit, reset, revert, cleanup,
  release, or attribution was performed; `project_diary.md` was left
  unchanged. Exact next entry point: decide whether to add a DSH-style prompt
  snapshot, duplicate/order checks, and a character/token budget gate. Keep
  the existing guide/strategy/role injection unchanged unless separately
  approved.

## Standalone mobile architecture decision handoff (2026-09-20)

- Task ID/deployment/state: `mobile_standalone_scope_archive` /
  `mobile_standalone_foundation_20260920` / **paused** pending user consensus.
  Confirmed sequencing: deliver standalone basic functions first; defer the
  communication/protocol refactor until later.
- Verified context: mobile `App.vue` currently injects only
  `RemoteTransport`/`ConnectionManager` and the local sync cache. Relay's
  README/control/main paths say Relay stores no Core work data and forwards
  opaque Noise frames. The shared Workbench requires
  `LamToolsTransport`/App Server semantics, while Python Core owns LLM,
  runtime, and tool execution.
- Proposed minimum scope, not approved or implemented: phone-local text-only
  model access and local sessions, with existing paired desktop/Relay still
  available. Exclude file read/write, command/terminal, MCP/plugins, and host
  tools. A cloud Core Worker alternative would materially expand security and
  deployment scope and is not implemented.
- Prior validation for targeted stabilization commit `b2761c06`: mobile
  14 files / 60 tests, typecheck, build, Capacitor sync, and Gradle
  `assembleDebug` passed. This is stabilization evidence only, not standalone
  architecture acceptance.
- Exact next decision: local direct provider/API-key access with local-only
  sessions versus a server-hosted Core. Read-only Git handoff: concurrent
  prompt/backend edits and the documented personal/generated paths remain
  untouched; this closure did not modify production/tests/diary or stage,
  commit, reset, or clean anything. Do not infer approval or implementation
  from the preceding checks.

## Mobile standalone foundation current contract (2026-09-20)

- The current mobile entry is local-first: it opens an independent local mode
  through a login-free panel. Local projects and sessions use SQLite, and the
  phone can connect directly to OpenAI-compatible or Anthropic providers. The
  paired desktop/Relay route remains available separately; communication and
  protocol refactoring is not part of this foundation.
- The sync path is device → project → remote control/import. Browsing cache is
  independent from sync, offline mode disables remote control, and import uses
  pagination to retrieve the complete session history. The mobile surface
  hides session-title and window-switch controls.
- Transport switching now disconnects before replacement and clears the old
  App Server client's reconnect timers, preventing that stale client from
  closing the new remote-control connection. The overall communication
  protocol refactor remains deferred.
- Verification evidence: mobile tests passed 16 files / 77 tests; the shared
  UI passed 96 files / 757 tests and typecheck; mobile `npm run typecheck`,
  `npm run cap:sync`, and Android `assembleDebug` passed. ADB
  overlay installation on vivo V2536A running Android 16 verified the
  login-free entry, surface-matched dynamic safe area, compact left sidebar,
  long-press context menu, and import.
- The current offline device's remote-control behavior was not verified. This
  handoff does not claim a broader communication/protocol refactor or any
  other remote-control device acceptance. Next entry point is to repeat the
  remote-control path only when a connected device/network is available.
- Disposition: this records verified local-foundation behavior only. It does
  not claim a cloud Core Worker, communication/protocol refactor, or physical
  device acceptance beyond the listed vivo checks. Preserve unrelated and
  concurrent worktree changes.

## Mobile floating command dock closure (2026-09-20)

- Task/deployment/state: `mobile_floating_command_dock_20260920` / **complete
  with install confirmation pending**. The mobile right-side optical-glass
  command dock directly lists all app/plugin modes and includes search,
  settings, and account. The left sidebar still owns plugin management and
  its session/project opener; mobile hides duplicate search/settings actions,
  while desktop defaults remain unchanged.
- GSAP Draggable persists and clamps position, separates drag from click, and
  keeps panel geometry within 12px at 280px and 390px widths. Reduced-motion
  and ARIA listbox/option behavior are covered. Independent review found and
  the main agent fixed horizontal overflow and listitem semantics; recheck
  passed.
- Verification: UI typecheck passed; UI coverage passed 96 files / 761 tests;
  mobile typecheck passed; mobile coverage passed 17 files / 79 tests;
  `npm run cap:sync` and Android `assembleDebug` passed.
- Wireless ADB installation on vivo reaches OEM package confirmation but
  cannot complete without confirmation on the device. No real-touch
  verification is claimed. Next entry point: confirm installation on-device,
  then test dock drag/click separation, mode selection, search/settings/account,
  and 280/390px geometry.
- Read-only Git handoff — intended files:
  `core/mobile/src/App.vue`,
  `core/mobile/tests/mobile-command-dock-contract.test.ts`,
  `core/ui/src/app/LamToolsApp.vue`,
  `core/ui/src/components/LeftSidebarShell.vue`,
  `core/ui/src/components/MobileTopBar.vue`,
  `core/ui/src/components/WorkspaceShell.vue`,
  `core/ui/tests/left-sidebar-shell.test.ts`,
  `core/ui/tests/mobile-top-bar.test.ts`, and
  `core/ui/tests/optical-glass-contract.test.ts`.
  Unrelated dirty paths to exclude are `agent_docs/project_diary.md`, the
  modified `core/src/lamtools_core/**` prompt/compaction files and their
  `core/tests/test_context_compaction.py`, `test_core_default_agent.py`,
  `test_kernel.py`, `test_project_context.py`, `test_skill_runtime.py`,
  `test_tool_result_model_evidence.py`, plus `.tmp_glass_rg.txt`, `MyProject/`,
  `artifacts/`, and `docs.7z`. No commit or cleanup was performed.

## Mobile Tunnel protocol/transport refactor closure (2026-09-20)

- Task ID/deployment/state: `mobile_tunnel_protocol_archive_20260920` /
  `mobile_tunnel_protocol_refactor_20260920` / **complete**. The external
  Tunnel v1 wire schema stayed unchanged while protocol representation and
  transport orchestration were separated. One golden fixture consumed by both
  TypeScript and Rust covers the shared frame contract; UTF-8 limits and
  boundaries are byte based, sequence values are JavaScript-safe, and
  continuation frames must match the initial
  version/type/stream/request envelope. Unknown channels are still rejected.
- LAN, Relay, and Noise compatibility was preserved, including opaque Relay
  forwarding. No P0-P2 issue was found.
- Verification recorded by the deployment: mobile 17 files / 90 tests,
  typecheck, build; Rust format, `cargo check`, and all tests 59/59 (remote
  tunnel 8/8, gateway 12/12); Android `assembleDebug`; and
  `git diff --check`. No real-device install or runtime test was run.
- Git handoff is read-only: unrelated pre-existing backend/context-compaction
  changes and untracked `.tmp_glass_rg.txt`, `MyProject/`, `artifacts/`, and
  `docs.7z` remain untouched. Next entry point: real-device and LAN/Relay
  acceptance for pairing, reconnect/resume, and remote control.
