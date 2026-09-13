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
