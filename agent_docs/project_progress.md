# Project Progress

## Goal

Deliver the Core single-UI, multi-Transport architecture: one shared
Workbench and application for desktop and mobile, with connection-specific
code isolated behind DirectTransport, RemoteTransport, the desktop Gateway,
and the opaque Relay tunnel.

## Overall Progress

**Active goal (2026-09-24): 移动端与桌面端功能对齐。** 依据
`core/docs/audits/mobile-desktop-parity-2026-09-24.md`，桌面 164 个操作中共享 UI 调用 88 个，移动端
曾有 28 个未实现，另有核心工具集、HTTP 路由与整块子系统缺口。按批次推进，每批一个版本、逐批出包：

1. ✅ 0.1.14 核心工具：`edit_file`、`search_files`、`search_content`、`web_fetch`
2. ✅ 0.1.15 HTTP 路由：`/projects/{id}/agents-md`、`/files`、`/files/content`、`/files/raw`、`/browse-directory`。桌面 56 条注册已逐条对照（parity 文档新增章节）；路由与移动端 project client 共用同一实现，`files/raw` 返回真实字节与 MIME，消息/舞台的图片视频 PDF 预览从 403 变为可用
3. ✅ 0.1.16 模式与命名：工具改名对齐桌面（`list_dir`/`read_file`/`write_file`）+ `config.loadtools.get/set` + 运行时模式白名单（广告与执行两侧都生效，拒绝语与桌面逐字一致）+ `sunday_tool_catalog`；未实现的 RPC 由静默 `{ok:false}` 改为抛错
4. ✅ 0.1.17 配置面收尾：`skill.create/delete`（用户技能落在运行时扫描的目录并挂载进每次装配）、`plugin.config.get/update`（宿主内嵌 imagegen/websearch schema，写入运行时真正读取的命名空间，密钥打码与保留）、`websearch.config.*`（JSONC 文档编辑，设置驱动 Rust 搜索内核与回退顺序）。`plugin.install/uninstall`、`plugin.widget.*` 移动端无宿主，明确报错
5. 🟡 0.1.18 artifact 存储：表/版本/回滚/store 与面板 RPC 全部对齐，`GET /projects/{id}/artifacts/{id}/file` 通（消息里的成果预览从 403 变为可用），快照 `artifacts` 由 store 填充；`write_file`/`edit_file` 观察即记录版本，未变化不产生新版本。剩 `artifact.open`（需 Android intent 桥）与 Goal 存储
6. ⏳ 会话检查点 / fork / rollback
7. ⏳ `write_checklist`、`update_checklist`、`question` 工具
8. ⏳ Office 渲染（或在移动端改写依赖 CLI 的技能）
9. ⏳ 切会话丢过程（会话状态归属分裂）

不做的：git 工具（用户决定）、workflow 工具（用户决定）、桌面宠物、CLI 本身（移动端无 CLI）。

**剩余目标（用户 2026-09-24 指定：逐项推进直到全部完成）**

- ✅ 0.1.19 4b：`artifact.open`（复用附件面板的缓存+intent 桥，Android-only）+ Goal 存储（状态机/乐观并发/校验语与桌面一致，`goal.create|get|list|update` patch 语义）
- ✅ 0.1.20 5：检查点（每回合边界记项目文件清单哈希，图/头/节点形状照桌面）+ 恢复（先记 undo 检查点，从 artifact blob 写回并记新版本，删除检查点之后新建的文件）+ fork（按回合派生分支会话）+ rollback（恢复文件并截断该回合之后的对话，无 turn 时取最新检查点）
- ✅ 0.1.21 6：`write_checklist`/`update_checklist`（桌面同款 action 集合与 schema，计划存在运行时、工具结果即计划；完成后指针自动移到下一步）+ `question`（新增 `ToolPermission::AlwaysAsk`，任何权限预设下都暂停）+ 转录里按 `plan` 部件渲染清单
- ✅ 0.1.22 7：技能清单按宿主能力说话——技能文本两平台共用不改写，无 shell 的宿主在清单后追加一行说明「涉及 `lamtools_core.cli office` 的步骤需要桌面端，本机直接产出源文件、验证与渲染在桌面完成」；技能面板的空状态提示不再让人往桌面专有目录放 SKILL.md。Office 渲染本身仍为桌面能力（Android 无 Python/Office）
- ✅ 0.1.23 8：切会话丢过程——`snapshotFor` 先问在跑的活快照（运行中的回合归它所有，与桌面「服务器持有运行中回合」同形），只把新读到的会话元数据并上去；没有在跑回合的会话仍从库读。回归测试跑的就是原故障路径：开一个不结束的回合→写入文本与工具调用→resume 后必须拿回运行中的回合、流式文本与工具步骤

**目标完成**：批次 1–8 全部落地。不做的仍是：git 工具、workflow 工具（用户决定）、桌面宠物、CLI、Office 渲染

**后续目标（2026-09-24）：真机 8 条行为缺陷。** 对齐批次交付后真机按严重度报出 8 条，全部位于**已存在代码内部**的行为层（常量、线上形状、错误/取消路径、竞态、失效注释），面核查看不到——原因与逐条证据记在 `core/docs/audits/mobile-desktop-parity-2026-09-24.md` 的「行为审计补充」章节。逐条一个版本：

- ✅ 0.1.24 第 2 条（P1）：删掉 `MAX_TOOL_ROUNDS = 8` 与 `ToolLimit`（第 9 轮不再丢弃整个 continuation），按桌面语义加两道证据闸门——纯工具轮计数（默认 8，达阈值注入桌面原文 `[TOOL_PROGRESS_REQUIRED]`，模型说话即归零）与重复结果停止（10 次/窗口 12，指纹为工具名+参数+结果的 SHA-256）；桌面在此暂停等用户，移动端改为可恢复收尾（不报错、不丢消息、原因进 `runtime_warnings`、给一次无工具收尾请求）。阈值可由 `TurnOptions` 调整
- ✅ 0.1.25 第 3+6 条（P2）：持久化历史的门槛由「最近回合是 completed」改为「写它的回合仍是本会话的 completed 回合」，并补上之后各回合的消息（取消/失败后不再整条会话退化为纯文本）；失败轮次的错误文案不再作为 assistant 消息回灌（用户仍看得到失败）
- ✅ 0.1.26 第 1 条（P1）：更新清单首次上线（清单由构建出的 APK 元数据生成、随包用同一把受限密钥上传、`verify_public.py` 四项断言），客户端所有失败自述地址；发布后用线上函数跑真实地址得 `up_to_date` / `update_available`
- ✅ 0.1.27 第 4 条（P2）：附件两条命令改 `dataBase64`（命令面上已无 `Vec<u8>`，客户端签名不变），附件正文按 id 做 32 MiB 有界缓存（历史图片不再每轮重读）
- ✅ 0.1.28 第 5/7/8 条（P3）：Workflow 入口注释改为如实描述（入口按决定继续隐藏）；空闲 `queue/create` 改为入队并立即派发、返回本方法的 `{snapshot, queue_item_id}`；`openStudySession` 按 `${kind}:${subjectId}` 在途去重
- ✅ 0.1.29 真机日志发现的第 9 条（不在用户报的 8 条内）：连接类失败重试预算不对齐——`provider.rs` 把「响应头之前」的失败夹到 2 次，桌面读同一份 `model_retry.jsonc` 却吃满 10 次。已对齐（500 行的阶段测试从「只允许两次」改为「跑满配置次数」），并留下「策略数值」这一层的检查表与「为什么上一轮没查出来」的复盘（parity 文档）

**目标完成**：8 条全部修复并逐版发布（0.1.24–0.1.28），外加真机日志暴露的 0.1.29；每条都有能对着旧实现失败的回归测试（第 8 条守卫测试除外，已注明）。仍未在真机复验：0.1.24 的长工具链（>8 轮不再丢轮）、0.1.27 的大附件上传耗时、0.1.29 的网络抖动容忍度（下一次断网时应看到约 34 秒的重试窗口而不是 6 秒）。

每项完成后立即升一个小版本、出包、发布、写 audit、提交，再进入下一项。


The shared-UI and multi-transport architecture has substantial existing
implementation, but the current Rust/mobile refactor is still incomplete.
Desktop and mobile work must be tracked against the active Rust migration
below rather than treating the overall refactor as closed. The legacy
Capacitor RemoteTransport path remains documented historical architecture.
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

- Mobile plugin tools and full audit (`mobile_plugin_tools_20260924`; 2026-09-24): mobile runs
  `study` (5 tools), `web_search` (3 ported kernels) and `generate_image` (configuration from the
  shared 设置 → 生图 panel, output landed as a session attachment). The extensions panel derives its
  tool counts from the manifests and the assembled runtimes instead of a written list, and plugin
  switches reach the runtime. `git` and `workflow` are deliberately not assembled on mobile: there is
  no `git` binary or repository, and workflow is a UI-RPC surface. Published mobile is **0.1.12 /
  versionCode 1012** at `https://47.114.43.99.nip.io/downloads/Sunday-mobile-latest.apk`; each release
  since 0.1.9 was verified by a complete public GET matching the local SHA256. The full audit
  (`core/docs/audits/full-code-audit-2026-09-24.md`) closed the previous P1 with its own fixture
  (`auto_tool_execute_count=0` for both deny and ask_user), retracted one of its own findings,
  withdrew one hardening recommendation as ineffective, and recorded three modules with no caller.
  Entries below describe earlier states: where they say ordinary skill loading or Study subagent
  tools "remain missing", both were implemented afterwards.

- Mobile/Desktop capability audit and Study assembly repair (`mobile_study_skill_assembly_20260923`): deployment closure is complete for the audit and the specified Study main-agent fixes only; it does not mean the findings are all repaired or the Rust migration is complete. The canonical finding list is [the audit report](../core/docs/mobile-desktop-code-audit-2026-09-23.md), with supporting evidence in `core/docs/audits/mobile-desktop-2026-09-23/`. HEAD remains `9cc013066f6229ce48a0cf4784cdb9e9f6503019`; the fixes and audit were not released. Published mobile remains 0.1.7 / versionCode 1007; next package is 0.1.8 / 1008. Study mode aliases, five skills/fourteen references, disabled-skill filtering, approval-resume context, prompt updates, and two color-token fixes are present in source only. Ordinary skill loading and Study subagent tools/context remain missing. Verification: mobile 175 tests, Rust runtime 130, native 18, and mobile typecheck passed (323 tests total); a local fixture also confirmed PreToolUse `deny` and `ask_user` still execute the tool. Prioritize permission enforcement, attachment bytes, Study concurrency, and backup recovery, then continue the report's ordered scope. Do not satisfy parity by hiding functionality. Full read-only handoff is in [latest session work](latest_session_work.md); preserve the broadly dirty working tree.
- Mobile sidebar and Study navigation (`mobile_sidebar_navigation_20260923`):
  the narrow viewport keeps the bottom dock available independently of the
  temporary drawer and account-panel state; wide layout restores modes,
  account, search, settings, plugins, and arrange actions. The Notes tree's
  “返回学习” navigation uses the resolved map binding before changing page.
  Dirty-draft cancellation or failed navigation preserves the draft; successful
  discard removes only the captured, unchanged draft. Main Study tests passed
  27; dock mobile tests passed 9 and UI tests 15; final UI/mobile typechecks and
  scoped diff check passed. Independent review covered success/cancel/failure.
  Code-only validation; no visual device acceptance is claimed. Signed 0.1.7 /
  versionCode 1007 is published as `https://47.114.43.99.nip.io/downloads/Sunday-mobile-0.1.7.apk`
  and at the stable link; SHA256
  `F6ECB4DD38366045B402C5513485B4F56342BFACCC67C6229AEE06B444C14386`,
  49,764,432 bytes. The prior 0.1.2 stable APK was archived on the server.
  Public versioned/latest HEAD returned 200 with matching length; homepage and
  main JS returned 200, with public JS hash matching the local website build and
  containing version 0.1.7. Server hash and cleanup checks passed. The prior
  0.1.6 work was committed as `9cc01306`; this sidebar/navigation work remains
  uncommitted pending phone feedback.
- Android provider-credential follow-through (`mobile_auth016_20260923`): phone
  0.1.5 reached the provider and received HTTP 401 `InvalidAuthorization/token`.
  The actual phone key is unavailable, so cause is unproven. Mobile config
  normalizes pasted `Authorization:` / `Bearer` prefixes on create/update and
  legacy reads, preserves bare tokens, rejects blank/masked/invalid new keys,
  and preserves stored credentials for masked updates. Focused tests passed
  9/9 and typecheck passed. Signed 0.1.6 / code 1006 is published at
  `https://47.114.43.99.nip.io/downloads/Sunday-mobile-diagnostic-0.1.6-20260923.apk`
  (49,763,916 bytes; SHA256
  `7A47E53747FB8D0BF06F8343F8E4A97EC37114894A81247022C62014191D7A39`).
  Public HEAD returned 200 with expected length; no full GET was done. The
  server key was revoked, authorized_keys is empty, stable/latest and 0.1.5
  hashes unchanged; the final temporary local key file remains. Successful
  phone authorization remains unverified; no Rust auth change was made.
- Android TLS revocation follow-through (`mobile_tls015_release_docs`): signed
  universal 0.1.5 / versionCode 1005 is built at
  `release/mobile/Sunday-mobile_0.1.5.apk` (49,764,032 bytes; SHA256
  `4683AB85217DD1FB60DDA6FB6914ADC88701BFB246B1C51E064399426B84EAD6`). It
  retains the verified signer, is non-debuggable, includes ARM64/ARMv7, passes
  16 KiB alignment, and contains the verified Sunday icon. Android 36 runtime
  verification confirms the release Network Security Config trusts the API's
  normal HTTPS chain, can download its signed CRL from `c.pki.goog`, and rejects
  a revoked certificate. The default config failed because OCSP could not reach
  its responder and cleartext HTTP CRL retrieval was blocked. The production
  Android manifest narrowly permits HTTP only for `c.pki.goog` (no subdomains);
  debug retains its previous cleartext behavior. The Rust/AAR verifier algorithm
  is unchanged; upstream maps certificate-verification errors to Revoked even
  for absent OCSP data. Contract tests passed 4/4. This validates the Android 36
  Java platform verifier configuration, not the full Rust app path or physical
  phone behavior. The user's 0.1.4 result was
  `provider TLS certificate revocation check failed before response headers`.
  Versioned APK is published at
  `https://47.114.43.99.nip.io/downloads/Sunday-mobile-diagnostic-0.1.5-20260923.apk`; public HEAD returned 200 and a complete GET matched the expected size and SHA256. Server cleanup revoked the exact temporary key, left `authorized_keys` empty, removed staging files, and confirmed Caddy and relay active. Stable/latest 0.1.2, diagnostic 0.1.4, and archived legacy 0.1.2 hashes are unchanged. On a physical phone, 0.1.5 reached the provider and returned HTTP 401 `InvalidAuthorization/token`; successful authorization remains unverified. Broader Rust refactor remains incomplete.
- Active Rust/mobile migration: Rust runtime Study, model, and Workflow runners
  remain partial; queue, human-task, and host-backed Workflow nodes are not
  ported. The mobile app has a Tauri host, Stop handling, and snapshot-based
  recovery. Phone TLS reaches the provider; acceptance remains unverified after the 0.1.5 HTTP 401, with credential normalization in 0.1.6 awaiting retest. The broader
  Rust refactor remains incomplete.
- Operational evidence (2026-09-23): the phone trace reached
  `http_request_built` at 13:43:42, then reported `provider send task failed`;
  there was no matching provider console record. Android reqwest 0.13.5 uses
  `rustls-platform-verifier` 0.7, and source inspection found its missing JNI
  and Kotlin initialization. This is a probable cause, not yet confirmed by a
  successful phone HTTPS request.
- Latest scoped verification: full `core/runtime-rs` tests passed (119 tests),
  Android `cargo check`, Gradle Kotlin compilation, and ARM64 APK build passed;
  independent source/APK review passed. Mobile passed 156/156 across 27 files,
  Vue typecheck passed, and Rust format checks passed for runtime and Android
  host. Emulator installation was blocked by `Can't find service: package`, so
  there is no device HTTPS proof.
- Python suite status: the latest full run passed 2260 tests with 2 skipped in
  347.68 seconds, after fixing a transient Windows atomic-replace issue in
  `MEMORY.md` handling.
- Latest scoped verification: full Rust tests passed (67 unit tests and all
  integration suites), `cargo check --lib` passed, and mobile passed 156/156
  with typecheck. These checks do not establish phone behavior or complete the
  Rust migration.

- Shared UI/runtime: `core/ui/src/app/`, `core/ui/src/workbench/`, and
  `core/ui/src/transport/`.
- The established mobile transport surface owns pairing, native capabilities,
  lifecycle, discovery, secure storage, and connection/wire code. The newer
  mobile Tauri host/runtime migration is tracked separately above and remains
  incomplete.
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

## Study plugin UI repair (2026-09-17)

- Task ID/deployment: `study_plugin_style_archive` /
  `study_plugin_style_20260917`; closure state: `complete`.
- Active goal/progress: Study UI styling and session continuity repairs are
  implemented. The title is teleported into `.workspace-plugin-header` and
  aligned with the standard header band; overview rows/progress use main-area
  tokens; selection-assistant readability fills use theme tokens instead of
  hardcoded dark/light colors.
- Current position: the actual VueFlow graph remains strictly driven by
  backend `net.relations`; theme-derived dot grid, relationship styles/legend,
  and node/relationship counts make the graph contract explicit. Study chat
  reuses `useCoreAutoFollowScroll`, an IntersectionObserver bottom sentinel,
  jump-to-latest, and remount reset/forced-bottom behavior.
- Verification: focused Study 7/7; related scroll/plugin 31/31; full UI 92
  files / 698 tests; backend Study 10/10; typecheck and build passed; LamTools
  audit 84 files / 0 deviations plus a manual Study token scan with no
  off-scale literals; scoped diff check passed. Build retained the existing
  `::highlight` lightningcss warning.
- Limitation and next milestone: no Computer Use or pixel-level visual
  acceptance was performed. Exact next entry point is user visual acceptance
  in the now-open Tauri Study mode, including confirming title placement,
  overview tokens, graph relationships, and sentinel return position.
- Git handoff: Study UI/test files are untracked within the broader dirty
  tree; `project_diary.md` and these two documents are modified. No stage,
  commit, revert, cleanup, or unrelated attribution was performed.

## Study graph layout closure (2026-09-18)

- Task ID/deployment: `study_obsidian_graph_archive` /
  `study_obsidian_graph_20260918`; closure state: `complete`.
- Active goal/overall progress: the Study knowledge graph now has a compact,
  Obsidian-like dot/label presentation with deterministic one-shot,
  relation-aware force layout. Label-aware spacing, saved/manual positions,
  graph navigation/inspection/pagination, theme-derived edges, and
  hover/focus/selection emphasis of direct edges are implemented.
- Current position: VueFlow viewport persistence uses the supported `@init`
  `store/setViewport` path and `moveEnd.flowTransform`; unsupported
  `v-model:viewport` was removed. Manual positions remain authoritative after
  layout, and relation edges remain the source for direct-edge emphasis.
- Verification: focused Study 7/7; full UI 92 files / 698 tests; UI typecheck,
  production build, and LamTools audit (84 files / 0 deviations) passed.
  Independent Tester returned PASS after the viewport repair. Scoped diff /
  whitespace checks passed; the existing `::highlight` build warning remains.
- Pending/next milestone: no deployment-specific blocker is known. No
  Tauri/Computer Use or pixel-level visual acceptance was performed. Exact
  next entry point is user-owned visual acceptance in Tauri Study mode,
  checking graph layout, saved viewport/positions, and direct-edge states.
- Git handoff: the shared tree remains heavily dirty with concurrent and
  untracked Study changes; this closure does not attribute them. No stage,
  commit, revert, cleanup, or `project_diary.md` edit was performed.

## Selection assistant target grounding closure (2026-09-18)

- Task ID/deployment: `selection_target_grounding_archive` /
  `selection_target_grounding_20260917`; closure state: `complete`.
- Active goal/progress: the exact selected quote is now the primary target for
  lightweight selection-assistant calls. Prefix and suffix text are used only
  for disambiguation, and every Ask follow-up re-anchors to that quote.
- Current position: the prompt version invalidates old explain/translate cache
  entries while preserving per-mark Q&A history. The local dictionary remains
  model-free.
- Verification: backend Study coverage passed 11 tests; focused frontend
  coverage passed 13 tests; the full UI contract passed 92 files / 698 tests;
  typecheck passed; and the independent Tester returned PASS with no P0, P1,
  or P2 findings.
- Limitation and next milestone: no real-model semantic exercise or Tauri
  visual exercise was run. If further acceptance is requested, start with a
  real selected-term translation/explanation in Tauri and confirm that the
  answer stays grounded in the quoted target.
- Git handoff: the shared tree remains dirty and uncommitted; unrelated and
  concurrent work was preserved. No stage, commit, revert, cleanup, or
  unrelated attribution was performed.

## Study Markdown translation and response rendering (2026-09-18)

- Task ID/deployment: `study_markdown_translation_archive` /
  `study_markdown_translation_20260917`; closure state: `complete`.
- Active goal/progress: Study SelectionAssistant now renders explain answers,
  model-translation fallbacks, and Ask-assistant replies through
  `MarkdownRenderer` with `mermaid=false`. User questions and dictionary
  entries remain plain text; card bodies use `line-height: 1.35` and tighter
  Markdown spacing.
- Current position: backend quote, prefix, and suffix are explicit sections;
  translate/explain/ask limits are 256/600/1200 characters. Prompt-version
  invalidation clears only explain/translate/dictionary caches and preserves
  thread history. The dictionary fast path remains model-free.
- Verification: `study.test.ts` 7/7; `test_study.py` 11/11; full UI 92 files /
  698 tests; typecheck and build passed. Build output contains only the
  existing `::highlight` lightningcss warning.
- Limitation and next milestone: Tauri session 13230 remains running and its
  application RPC is active, but no Computer Use or pixel-level visual
  acceptance was performed. Exact next entry point is user visual acceptance
  in the open Tauri Study mode, including Markdown response rendering and
  plain-text question/dictionary behavior.
- Git handoff: the shared tree remains dirty and uncommitted; Study files may
  remain untracked. No stage, commit, revert, cleanup, or unrelated
  attribution was performed.

## Study shared chat primitives and node sessions (2026-09-18)

- Deployment `study_shared_primitives_20260918` is complete. Study now keeps
  `study:main` as the global knowledge-graph builder and creates one isolated
  session per knowledge node; safe legacy IDs stay readable and Unicode or
  punctuation-heavy node IDs use a stable hash while retaining the original
  ID in session metadata.
- Study delegates its conversation surface to Core: message history,
  pagination, actions, the bottom sentinel, composer, upload button, pending
  attachment tray, drag/drop, paste upload, attachment-only submission, and
  historical attachment rendering all use the canonical implementation.
  Course navigation, graph layout, marks, and anchors remain Study-owned.
- Mode-session isolation restores the Agent conversation after returning from
  Workflow or Study. Clicking a node selects its session and only prefills the
  teaching prompt. The builder title is `知识图谱`; legacy default title
  `学习` migrates while user-defined titles remain unchanged.
- Verification passed: backend Study/attachment HTTP 22/22, focused Study/mode/scroll 9/9,
  attachment and composer coverage 35/35, full UI 92 files / 698 tests,
  typecheck, production build, design audit 84 files / 0 deviations, and
  `git diff --check`. The build retains the known `::highlight` minifier
  warning. Per instruction, no Computer Use validation was performed.

## Study skill-pack integration closure (2026-09-18)

- Task ID/deployment: `study_skills_integration_20260918`; closure state:
  `complete` for the requested Study integration. The four supplied skills
  (`build-map`, `teach`, `answer`, and `take-exam`) and `study-system.md` are
  installed under the bundled Study plugin and remain isolated behind the
  existing SkillRegistry/`load_skill` path for active mode `study:study`.
- The Study system prompt is automatically added by the backend, while the
  public safety, permission, tool, and verification protocols remain shared.
  Generic project/programming/business workflow prompts are excluded from the
  Study prompt path. Existing tool IDs, Agent Loop interfaces, live/queue late
  context forwarding, `study:main`/node sessions, and the existing UI/right-
  click lightweight calls are reused; no parallel UI architecture was added.
- Persistence and exam behavior now cover notes/content/metadata, shared-node
  per-course notes and evaluation state, current learning context, exam help
  records, private answer/rubric storage, batch save versus explicit submit,
  isolated generation/grading, review evidence, and idempotent score writeback.
  Answer/rubric data is not returned through ordinary public reads or grading
  output. Deferred textbook, PDF, knowledge-base, and RAG work remains out of
  scope.
- Verification evidence: focused backend Study/plugin plus the corrected
  Workflow regression passed `33 passed` (two existing datetime-adapter
  deprecation warnings); focused Study/composer UI passed `19 passed`;
  `npm run typecheck`, `npm run build`, and the full UI contract (`699
  passed`) passed. The build retains existing LightningCSS `::highlight` and
  ineffective dynamic-import warnings. The latest full Core run recorded
  `2077 passed, 9 failed, 2 skipped`; after the unrelated Workflow assertion
  correction, the eight known baseline failures were rerun directly and
  yielded `57 passed, 8 failed`.
- The eight remaining failures are outside Study: three persistence tests
  (`test_core_operation_persists_run_items_and_snapshot`,
  `test_core_operation_publishes_run_items_while_turn_is_running`,
  `test_core_approval_continuation_persists_approved_tool_and_final_snapshot`),
  three live tests (`test_live_turn_reuses_accepted_id_for_core_events_terminal_and_task_registry`,
  `test_live_turn_steer_reaches_the_next_model_call_before_a_no_tool_final`,
  `test_live_queue_guidance_reaches_the_next_model_call`), the live client E2E
  matrix, and the live resume page-cursor test. The first six fail with
  `sqlite3.OperationalError: no such table: core_projects`; the last two
  return no resume events where the tests expect them. The full Core suite was
  not rerun after the Workflow correction, so no newer aggregate is claimed.
- No Computer Use/Tauri manual or pixel-level acceptance was executed. The
  exact next entry point is user-owned Study acceptance in Tauri, followed by
  a separately scoped repair of the eight existing Core baseline failures if
  a green full suite is required. The worktree remains dirty/uncommitted;
  this closure did not stage, commit, revert, clean, or change production
  state.

## Study v2 knowledge workspace closure (2026-09-18)

- Task ID/deployment: `study_v2_closure` /
  `study_complete_v2_20260918`; closure state: **paused at a stable,
  tested boundary**. The requested Study upgrade is implemented through the
  P0–P3b boundary: scoped knowledge data, map/notes/node sessions, exams and
  evidence-backed mastery, marks/quick assist, note blocks and curation
  control records, and shared Dreaming/Memory policy seams.
- Current position: Study uses the existing Core Agent Loop, SkillRegistry,
  Tool Gateway, session/message/attachment persistence, ModelGateway entry
  points, and Arrange runtime. The bundled Study plugin maps the existing
  tool IDs `get_knowledge_net`, `build_knowledge_net`, `exam`, and `sign` to
  `study.get`, `study.build`, `study.exam`, and `study.sign`; it loads
  `build-map`, `teach`, `answer`, and `take-exam` only for `study:study`, and
  injects `prompts/study-system.md` while retaining shared safety/tool
  protocol. The UI keeps the existing shell and chat primitives, with
  Overview/Graph/Notes/Subject Tree, scoped pins/search, local graph layout,
  node-bound sessions, marks, and note management layered on them.
- Data protection/migration: the Study store is the single SQLite write
  source. It creates scoped records, revisions, idempotency receipts,
  transactional outbox, session bindings, notes/blocks, curation tasks, and
  soft-delete/restore-compatible records. Startup migration copies the
  legacy JSON entity/meta tables into the explicit local compatibility scope
  and upgrades the note-block foreign key idempotently. Before first use,
  retain a SQLite `.backup`; the audit backups are in
  `E:\LamTools\.tmp\study-v2-backup-20260918-0158` for
  `core/data/core.db` and `core/core.db`, both with `integrity_check=ok`.
  No real `study.db` existed at audit time; migration evidence is synthetic
  and test-backed, not a claim of migrating a user library.
- Verification: the recorded full Core run is `2113 passed, 2 failed,
  2 skipped`; both failures are the pre-existing
  `thread.resume` snapshot-only protocol mismatch. The shared UI run is
  92 files / 702 tests, with typecheck and production build passing. Current
  independent checks are `tests/test_study.py` 36 passed,
  `tests/test_memory_v2.py` 12 passed, and `tests/test_arrange_fencing.py`
  3 passed. Build output retains the known LightningCSS `::highlight`
  warning (and ineffective dynamic-import warnings).
- Not complete/verified: Study operation declarations still use
  `auto_allow`, so action-level Study approval/policy is not a completed
  security boundary. Exam/quick-assist isolated calls still need the shared
  Direct ModelGateway retry/cancel/usage path. The runtime SQLite is
  Python 3.50.4 / CLI 3.50.6, below the design-required 3.51.3 WAL-fix
  floor; the newer engine is not installed. No real model, Tauri/mobile
  visual, or performance-budget run was executed. P4 textbook/PDF/knowledge
  base/RAG and P5 features remain interfaces/placeholders only.
- Exact next milestone: add and verify action-level Study approval, unified
  Direct ModelGateway cancellation/retry/usage accounting, and the supported
  SQLite engine/connection policy; then run real-model, Tauri, migration-copy,
  and performance acceptance. Keep the existing UI and Core loop as the
  integration points.
- Git handoff: baseline was `56d45e4e9257ec1be9c98a948783b23ff598183d`
  on `codex/multiplatform-dev` with a pre-existing heavily dirty worktree;
  most Study source/tests/docs are untracked. Cross-cutting tracked edits
  overlap concurrent work and cannot be attributed safely. This closure
  changed only the assigned progress/latest-session documentation; no stage,
  commit, reset, checkout, clean, database deletion, push, or release was
  performed.

## Study reset and performance closure (2026-09-18)

- Task ID/deployment/state: `study_perf_reset_closure_20260918` /
  `study_perf_reset_20260918` / **complete**. Study content data was backed
  up before reset, then cleared: `E:\LamTools\.tmp\study-reset-20260918-111814`
  contains `study.db` and `core.db`. After Tauri startup, only one empty
  `study:main` shell snapshot/binding was regenerated; knowledge, notes,
  exams, marks, receipts, outbox, history, and runtime rows were zero.
- Performance fixes: removed the unsupported `study.session.binding` alias
  that caused five global retries and roughly 6.2 s worst-case backoff;
  canonical `study.session` is now used. Duplicate refresh/select work was
  removed, known bindings skip session refresh, binding and overview load in
  parallel, the sidebar avoids eager course fan-out, and graph get/layout run
  in parallel. VueFlow is split into an async `StudyGraph` chunk. Shared
  `HistoryLoadingIndicator` is reused, later switches retain the Core thread,
  mode changes preserve the connection-scoped App Server client, and command
  catalog/goal/scroll work is parallelized.
- Runtime evidence: Tauri was restarted with frontend `5173` and backend
  `59690`. Empty-DB RPC timings were 58.7 ms for `study.session` and 41.7 ms
  for `study.get`; CLI wall time was about 1 s including process/WebSocket
  startup and is not an RPC latency claim.
- Verification: focused UI 18/18; full UI 92 files / 706 tests; typecheck;
  `build:app`; backend 48 passed with 2 deprecation warnings; LamTools design
  audit 84 files / 0 deviations; and `git diff --check` with line-ending
  warnings only. Independent Tester passed 3 files / 17 tests.
- Limitations: no Computer Use/perceptual timing run was performed. Real
  Tauri visual/interaction timing remains user acceptance. The shared tree
  remains heavily dirty; preserve unrelated changes and do not infer this
  closure as a commit or release.

## Study graph primary-progress closure (2026-09-18)

- Task ID/deployment/state: `study_graph_primary_progress_20260918_closure` /
  `study_graph_primary_progress_20260918` / **complete**.
- The old Study overview UI/page was removed. Its sidebar location is now
  `管理你的知识`; `图谱` remains. The explicit `manage` action clears the
  selected node and restores the existing `map` primary binding/default main
  session without issuing a duplicate `study.session` request when the
  binding is cached. No backend, schema, or database changes were made.
- Top-level course nodes reuse the existing overview aggregate. They render
  exact course names as large circular spheres with an external SVG progress
  ring and readable/clamped percentages (`total <= 0` renders 0%); deeper
  nodes retain their existing rendering. Ring bounds were aligned with the
  existing 112px layout spacing.
- Verification: focused Study 15/15; full UI 92 files / 708 tests; UI
  typecheck and `build:app` passed; backend Study 38 passed with 2
  deprecation warnings; design audit 84 files / 0 deviations; independent
  Tester PASS. Build output contains only existing `::highlight`,
  dynamic-import, and chunk warnings. DOM/CSS/mock-RPC contracts were
  verified.
- Limitation/Git handoff: computer-use and live Tauri visual/perceptual
  inspection were intentionally not run; visual and interaction timing remain
  user acceptance. The worktree remains heavily dirty with unrelated and
  concurrent changes preserved; no production/test files, diary, commit,
  reset, cleanup, push, or release was performed by this closure.

## Glass material unification pause (2026-09-18)

- Task ID/deployment/state: `glass_material_unification_archive` /
  `glass_material_unification` / `paused`. The deployment stopped before
  implementation pending required user consensus on the proposed scope.
- Verified context: the supplied Liquid Glass standard requires high
  transmission, low blur, restrained localized highlights, subtle gray-green
  edge refraction, and short soft shadows; the existing shared optical-glass
  primitive is the intended starting point. The read-only inventory covers
  current glass-like surfaces and the worktree already contains unrelated and
  concurrent dirty/untracked changes.
- No production or test files changed for this deployment. No tests, build,
  Tauri visual acceptance, or Computer Use were run. `project_diary.md` was
  intentionally left unchanged.
- Exact continuation point: after the user confirms scope, unify the true
  glass-material surfaces against the supplied standard, while excluding mere
  modal dimmer backdrops and opaque panels. Preserve unrelated work and keep
  shape/layout behavior separate from the shared material primitive.

## Study skill v3 refactor closure (2026-09-18)

- Task ID/deployment/state: `study_skill_refactor_v3_20260918_docs` /
  `study_skill_refactor_v3_20260918` / **complete**. The package snapshot is
  preserved at `E:\LamTools\.tmp\study-skill-v3-snapshot-20260918-135315`.
  The exact v3 files for `build-map`, `teach`, `answer`, `take-exam`, and
  `prompts/study-system.md` were copied into the bundled Study plugin.
- `curate-notes` remains under
  `core/src/lamtools_core/plugins/bundled/study/future/curate-notes` and was
  deliberately not registered: the Agent Loop has no callable notes tool or
  capability gate for it. Added evaluation manifest tooling at
  `core/src/lamtools_core/plugins/bundled/study/eval_manifest.py` and expanded Study coverage.
- Verification: host smoke PASS for 4 active skills plus 1 future-gated skill;
  14 references; 40 evaluations with `run=0` / `NOT_RUN=40`; focused Python
  coverage 50 passed; UI 708 tests, typecheck, UI build and desktop build
  passed; package validation PASS; examples 14/14 passed under Python 3.9
  because Python 3.14 lacks sympy. The stable Core full suite result is 2116
  passed / 2 skipped / 2 failed; both failures are the unrelated existing
  `thread.resume` event-page tests.
- Limitations: `quick_validate` cannot accept the package's standard
  compatibility frontmatter. Audit gaps remain for source version/archive
  service, verified technical image generation, strict schema limitations,
  and `study.text.cancel`. These are not claimed as implemented by this
  closure. The dirty worktree remains preserved; no unrelated files, diary,
  commit, reset, cleanup, push, or release was changed by documentation.

## Glass material unification implementation closure (2026-09-18)

- Task ID/deployment/state: `glass_material_unification_impl_archive` /
  `glass_material_unification_impl` / **complete**. This user-confirmed
  implementation supersedes the earlier paused planning deployment.
- Outcome/current position: the shared `.optical-glass` primitive now owns the
  tokenized transmission, blur, saturation/brightness/contrast, fallback,
  localized highlight, gray-green refraction, inset edge, and soft-shadow
  recipe. Confirmed consumers are the WorkspaceShell right drawer, shared
  context-menu root/submenus, Study selection card, Workflow node catalog
  popover and runtime dock, jump-to-latest control, Goal area, and MobileTopBar
  button/sync/account controls. Startup `index.html` mirrors the treatment
  before Vue mounts, with native Acrylic configured in the desktop shell.
- Scope boundary: modal dimmer backdrops, ordinary opaque panels, the left
  drawer, and Workflow node cards remain outside the glass surface contract.
  The startup blue refraction and 48% inset were repaired to gray-green and
  56%; the independent Tester then returned PASS.
- Verification: shared UI coverage passed 93 files / 712 tests; focused
  glass/startup recheck passed 21 tests; UI typecheck/build, desktop Vite
  build, `cargo check`, LamTools design audit (84 files / 0 deviations), and
  scoped/full diff checks passed. No Computer Use or Tauri visual validation
  was run per user instruction.
- Read-only Git handoff: the worktree remains heavily dirty with concurrent
  and untracked changes. Archivist changed only the assigned documentation;
  no stage, commit, revert, cleanup, or unrelated attribution was performed.

## Glass specular quieting closure (2026-09-18)

- Task ID/deployment/state: `glass_specular_quieting_archive` /
  `glass_specular_quieting` / **complete**. This is a focused visual-material
  correction following the glass unification.
- Verified delta: the shared upper-left reflection was reduced from 26% to 10%
  and its footprint from 92×42 to 54×24. Startup light/dark optics and edge
  layers were reduced to 38×20 at `.06/.05` and 26×4 at `.09/.08`;
  all other material parameters remain unchanged.
- Verification: focused glass/startup coverage passed 2 files / 21 tests;
  LamTools design audit passed 84 files / 0 deviations; the relevant diff
  check passed; and the independent Tester returned PASS. No Computer Use or
  Tauri visual validation was run per user instruction.
- Git handoff: preserve the heavily dirty tree and unrelated/untracked work.
  No diary, production/test, stage, commit, revert, or cleanup operation was
  performed by this documentation closure.

## 0.3.4 repository audit, fixes, and package build (2026-09-18)

- Deployment `audit_fix_bump_20260918` completed the code audit and package
  build. Fixed `thread.resume` event loss, proxy-sensitive localhost health
  probing, mobile project visual-field persistence, and browser-global access
  during shared UI module import. Applied bounded Rust cleanup without changing
  the desktop/relay protocols.
- Version is `0.3.4` in all five sources plus npm/Cargo lockfiles. The Windows
  installer was built at
  `core/desktop/src-tauri/target/release/bundle/inno/Sunday_0.3.4_x64-setup.exe`
  (93,961,819 bytes) and installed to `E:\setuptest\0.3.4`.
- Verification passed: backend 2122 passed / 2 skipped; UI 725/725 plus
  typecheck/build; mobile 46/46 plus typecheck/build; desktop Rust 53/53 plus
  fmt/check/clippy; relay 11/11 plus fmt/clippy; dependency audits reported zero
  vulnerabilities; design audit reported 84 files / 0 deviations.
- Installed main-process smoke remains blocked by the already-running Tauri dev
  instance `target/debug/lamcore.exe` (PID 7000), which owns the global
  single-instance lock. The installed executable exited cleanly with code 0;
  project policy forbids closing the development instance. Re-run the setup
  helper after that instance is closed to obtain installed main/backend PIDs.
  No commit, tag, push, or release was performed.

## PDF ingestion correction (2026-09-18)

- Fixed remote `web_fetch` PDF responses being decoded as binary text. Remote bytes and local/uploaded PDFs now share the existing bounded `pypdf` normalizer, including untrusted-content labeling, encryption/page/text limits, and scanned-page warnings.
- Current uploaded PDFs are extracted into model text context instead of being deferred to an unsupported multimodal content block. Main-agent and sub-agent paths retain text-only attachment context and perform parsing/file I/O in a worker thread.
- Verification passed: real TI `SLVA477` fetched as 8 pages / 22,044 normalized characters with no `%PDF-` leakage; focused PDF/attachment/default/sub-agent coverage passed; full Core suite passed 2128 / 2 skipped; UI passed typecheck, 93 files / 727 tests, and build; desktop Vite build passed. Existing deprecation/CSS Highlight warnings remain non-blocking. Version remains 0.3.4.

## Study exam model-routing correction (2026-09-18)

- Task ID/deployment/state: `study_exam_model_routing_fix_docs` /
  `study_exam_model_routing_fix` / **complete**. This closure follows the
  Study exam failure where the isolated authoring call did not receive the
  active turn model and raised `model id is required when no routing setting
  is available` after unnecessary retries.
- Outcome: isolated Study exam authoring, grading, and review now inherit the
  active runtime model across approval boundaries. An explicit operation model
  remains authoritative. Arrange and Workflow queue records inherit and
  persist the runtime model, with explicit overrides taking precedence. Missing
  model, provider, or base-URL routing is deterministic configuration failure:
  it stops immediately and cannot silently fall back or consume retry budget.
- Modified/covered surfaces: Study backend/exam/marks routing, live runtime
  model stamping, Arrange persistence, Workflow operation/queue/runtime model
  resolution, and the shared retry classification; focused coverage includes
  `core/tests/test_study.py`, `core/tests/test_workflow_operations.py`,
  `core/tests/test_llm.py`, and related runtime/provider tests.
- Verification: targeted suites passed; the full Core run recorded `2142
  passed, 2 skipped, 1 unrelated localhost HTTP probe timeout`, followed by an
  isolated rerun of that probe with `1 passed`. A later focused provider/routing
  run passed `67 passed, 1 skipped`; the independent verifier returned PASS.
  This is not reported as one clean all-green full run.
- Limits and handoff: no network or UI/Tauri testing and no database migration
  were performed for this correction. Existing dirty/untracked work was
  preserved; no unrelated UI, deployment, or migration behavior is implied by
  this closure. Git state remains uncommitted and requires normal maintainer
  review before release.

## Study agent grading correction handoff (2026-09-19)

- Study exam grading now stays with the current Agent flow. The Agent creates
  the exam and, when needed after context loss, reads the persisted reference
  answer on demand before grading; grading no longer uses a separate isolated
  model call and no longer compares a choice response to the reference text as
  an exact string. The persisted reference remains a recovery aid for the
  case where intervening help or compaction has displaced the original grading
  context.
- Grading supports partial credit and step-level scores (`step_scores`) while
  retaining grading `version` and idempotent write semantics. The program
  preserves record identity, score bounds, version, and idempotency guarantees;
  the Agent supplies the semantic judgment and score.
- Verification: the focused Study grading set passed 50 tests. The recorded
  full Core run passed 2143 tests with 2 skipped and had 1 temporary
  `PermissionError`; rerunning that affected test passed. UI and desktop builds
  passed, and the independent Tester returned PASS.
- Not yet verified: no real production-model request and no Tauri/UI manual
  retest has been run. The next milestone is the user's live retest of the
  formal exam in the 极限 node, followed by recording any model or UI behavior
  observed there.

## Study note curation connection (2026-09-19)

- Root cause from the real 极限-node trace: the note tables, `study.notes` RPC,
  and Notes UI existed, but the Agent had no callable note tool and
  `curate-notes` remained future-gated. It therefore produced an unsaved draft.
- The existing store is now exposed as the Study-only `notes` Agent tool and
  `curate-notes` is registered through the existing mode-scoped SkillRegistry.
  The tool schema stays stable from the first Study request; only skill text is
  loaded on demand, preserving prompt-cache prefix stability.
- Agent-created blocks are attributed to AI and cannot use the UI-only
  `user_edit` override. Existing title-required, locked-block, and revision
  conflict behavior remains; proposed extra size/count validation was removed
  per the user's preference to avoid premature strictness.
- Focused Study/bundled-plugin verification passed 50 tests and compileall.
  The full Core run was intentionally interrupted after the design was changed
  from on-load tool exposure to a stable Study tool set; do not report it as a
  completed full-suite result. Live user acceptance remains pending.

## Chat instruction navigator design pause (2026-09-19)

- Task ID/deployment/state: `chat_turn_navigator_design_20260919_archive` /
  `chat_turn_navigator_design_20260919` / **paused** pending user consensus.
  This was a read-only design/code audit; no production or test files changed.
- Verified seams: `LamToolsApp.vue` owns the `.thread` scroll surface and
  existing `locateMessage`/history-pagination flow; `ChatThread.vue` places
  `data-message-id` on every rendered message; the initial history projection
  uses a 10-turn page; shared `.optical-glass` is available; and the narrow
  layout has a 640px breakpoint.
- Proposed direction: a ChatGPT-style, left-edge instruction navigator keyed
  only by user messages, with the selected marker longest and other markers
  progressively weaker. Hover/focus previews should use shared optical glass;
  clicks should reuse `locateMessage`, without introducing a second scroll
  observer. The attached screenshot is visual reference only.
- Pending decisions: whether markers represent all historical instructions or
  only the loaded window; whether preview cards show user text only or a paired
  response summary; and whether mobile hides the navigator or uses a compact
  overlay. No Computer Use or Tauri run was performed. Preserve the existing
  dirty/concurrent UI work. Exact next entry point is user confirmation of
  those three decisions, followed by scoped implementation and Tauri-owned
  visual acceptance.

## Chat instruction navigator implementation closure (2026-09-19)

- Task ID/deployment/state: `chat_turn_navigator_impl_archive` /
  `chat_turn_navigator_impl_20260919` / **complete**. The Core chat now has a
  left-edge user-instruction navigator backed by `thread.outline`; the backend
  includes only top-level renderable `userMessage` rows and caps prompt/response
  excerpts at 240 characters. CLI access is available through `session outline`.
- The Canvas uses evenly indexed full-history markers. The active marker follows
  the mounted user message nearest 38% of the viewport. Preview cards use the
  shared `.optical-glass` material, and click navigation reuses `locateMessage`
  plus the existing history pagination. Keyboard access, reduced-motion rules,
  DPR-aware sizing, and explicit RAF/ResizeObserver cleanup are included; the
  navigator is hidden at `<=640px` and adds no second scroll observer.
- Verification: backend focused coverage passed 50 tests; the broader executor
  set passed 181 tests. Final frontend focused coverage passed 27 tests;
  typecheck and `build:app` passed with existing warnings; the design audit
  covered 85 files with 0 deviations. The independent Tester passed after an
  earlier RAF S3 finding was fixed and the navigator follow-up (7 tests plus
  typecheck) passed.
- No Computer Use or Tauri visual validation was run by user request. The
  heavily dirty/concurrent worktree was preserved; no commit or cleanup was
  performed. Future visual acceptance should begin in Tauri at the navigator
  and narrow-layout behavior.

## Study Obsidian notes phase 1 closure (2026-09-19)

- Task ID/deployment/state: `study_obsidian_phase1_archive` /
  `study_obsidian_phase1` / **complete**. Study notes now present one
  continuous Markdown document in read mode, with edit/preview switching,
  h1-h6 outline navigation, and scoped `[[wikilink]]` resolution for notes
  and knowledge nodes. Backlinks are derived within the active Study scope.
- Stable note/node IDs drive navigation; unresolved links remain visible and
  saveable. Whole-document edits use the existing `update_blocks` path as one
  atomic write while retaining block and source rows, and duplicate block IDs
  are rejected. No `.md` mirror, link table, new Agent Loop, or replacement UI
  architecture was introduced.
- Verification: focused backend coverage passed 53 tests; focused UI coverage
  passed 21 tests; final UI typecheck and build passed; the LamTools design
  audit covered 85 files with 0 deviations; and an independent Tester returned
  PASS. Full UI (739 tests) and full Core (2152 passed / 2 skipped) were run
  before the final narrow atomic-boundary fixes; focused final rechecks then
  passed. Build output retains only the existing `::highlight` and
  dynamic-import warnings.
- No Computer Use/manual Tauri acceptance, data migration or deletion,
  commit, push, or release was performed. Exact next entry point: retest the
  existing 极限 note under Study > 笔记 by editing, previewing, and saving,
  then try `[[another note]]` and `[[knowledge node|label]]`. Preserve the
  heavily dirty worktree and treat visual/perceptual behavior as user-owned
  acceptance.

## Study packaged RPC hotfix closure (2026-09-19)

- Task ID/deployment/state: `study_rpc_packaged_hotfix_archive` /
  `study_rpc_packaged_hotfix_20260919` / **complete**. The packaged-only
  failure was traced to the canonical Study backend import looking for
  `study-system.md` beside the PyInstaller module, while frozen plugin data
  lives under the bundled resource root. The fix adds the existing
  `bundled_plugins_dir()` fallback without changing the Agent Loop or Study
  RPC contract.
- Packaging smoke now performs WebSocket initialization and a real
  `study.session` call. Source focused coverage passed 55 tests; independent
  verification passed Study 44 and bundled-boundary 10; the PyInstaller
  packaged smoke passed. Installed `E:\setuptest\0.3.5` backend PID 29728 on
  port 49758 returned non-empty session ID `study:main`.
- The rebuilt installer is 93,990,114 bytes with SHA256
  `5E26B6F280DC5E8D8A4B20338569488A036E370E34695840493B592C3111BE5A`.
  The public download was replaced and the redownload hash matched. Server
  backups are
  `/var/www/lamtools/Sunday_0.3.5_x64-setup.exe.before-study-rpc-hotfix-20260919T143333Z`
  and the corresponding `Sunday-latest...` backup. The temporary SSH key and
  upload directory were removed.
- No full repository test result is claimed. No commit, tag, or push was made;
  the heavily dirty worktree and unrelated changes remain preserved. Exact
  next entry point: launch the installed 0.3.5 build and exercise Study; if a
  packaged-only regression appears, inspect the frozen resource path through
  `bundled_plugins_dir()` before changing the RPC or prompt contract.

## Study notes UX optimization closure (2026-09-20)

- Task ID/deployment/state: `study_notes_ux_20260920` /
  `study_notes_ux_20260920` / **complete**. The notes surface now enforces a
  trusted host writer boundary and AI/user ownership, broadcasts precise
  `study/changed` updates, resolves code-safe typed wikilinks and node
  backlinks, and keeps Study CLI `search`/`pin` parity. The UI preserves
  Markdown losslessly, exposes detail loading/error/retry states, refetches
  after save while rejecting stale responses, protects note-scoped draft
  navigation, reports provenance and unresolved links, derives setext/DOM
  outlines, and honors reduced motion. The `curate-notes` Skill is 3.1.0 and
  the Study system prompt now states the corresponding read-first, minimal
  increment, ownership, conflict, and receipt rules.
- Verification: the backend Study trio passed 59 tests; focused frontend
  coverage passed 31 tests; `npm run typecheck` and `npm run build` passed;
  compileall and the scoped whitespace check passed; the LamTools design audit
  scanned 85 files with 0 deviations. Build output retains the existing
  `::highlight` and ineffective dynamic-import warnings. Independent Tester
  review concluded there were no P0-P2 defects after the CommonMark indented
  code/wikilink fix.
- No auto-save or delete/restore workflow was added. No Computer Use or Tauri
  visual acceptance was run. Read-only Git inspection found the expected
  heavily dirty workspace, with Study files among concurrent and untracked
  changes; no stage, commit, reset, revert, cleanup, or release was performed.
  If visual acceptance is later requested, begin at Study > 笔记 and exercise
  read/edit/preview/save, draft navigation, typed links, backlinks, search,
  pinning, and retry states.

## Linux/macOS desktop distribution planning closure (2026-09-20)

- Task ID/deployment: `multiplatform_planning_archive` /
  `linux_macos_desktop_20260920`; state: **paused** pending user consensus.
  This was a read-only Heavy audit for adding Linux and macOS desktop
  distributions. No lasting product decision has been approved.
- Current Windows-only blockers are verified: packaged `LamCore.exe`
  discovery is embedded in the current desktop/package handoff; the supported
  package flow is PowerShell + PyInstaller + Tauri `--no-bundle` + Inno Setup;
  release/update selection only recognizes `Sunday_*_x64-setup.exe`; Linux
  secure storage currently falls back to in-memory behavior; install-adjacent
  user data is incompatible with the desired signed macOS app/AppImage
  locations; hook path fallback still assumes Windows `APPDATA`/`AppData`; and
  native Linux/macOS desktop CI is absent.
- Already-portable foundation: shared Vue `LamToolsApp`/Workbench and
  `LamToolsTransport`, the Rust/Tauri desktop shell, the Python Core backend,
  JSONC configuration and CLI boundaries. The official packaging constraint
  is that PyInstaller and Tauri artifacts must be built on native runners for
  their target operating systems; Windows cross-build output is not evidence
  of Linux/macOS packages.
- Recommended but not approved scope: Linux x64 AppImage plus `.deb`; separate
  Intel and Apple Silicon macOS DMGs; standard Linux/macOS data roots while
  preserving Windows behavior; Secret Service and Keychain-backed secrets;
  native packaged smoke checks; and platform-aware update selection plus
  website download assets.
- Mandatory user decisions before implementation: whether Apple Developer ID
  signing/notarization credentials are available and in scope, and whether
  this deployment only implements/tests or also bumps versions, tags, and
  releases. Until confirmed, do not implement, package, run CI, sign,
  notarize, release, or change Windows behavior.
- Verification/disposition: only read-only source/document/Git inspection was
  performed. No implementation, package build, CI run, signing,
  notarization, release, or Computer Use occurred. The heavily dirty and
  untracked worktree was preserved; no production/test file, `project_diary.md`,
  stage, commit, reset, revert, cleanup, push, or attribution was performed.
  Evidence: `core/desktop/PACKAGING.md`, `scripts/package.ps1`,
  `.github/workflows/release.yml`,
  `core/src/lamtools_core/update/checker.py`,
  `core/src/lamtools_core/plugins/hook_config.py`, and the shared
  `core/ui`/`core/desktop` transport and shell paths.
- Exact next milestone: obtain the two user decisions, then define the
  per-platform data/secret/package/update contracts and native-runner CI
  matrix before making production changes. Do not treat this audit as package
  or release acceptance.

## Study three-layer notes closure (2026-09-20)

- Deployment `study_notes_three_layer_20260920` is complete. Study notes now
  use three explicit layers: trusted host-captured immutable Raw from sessions,
  marks, exams, and nodes; Agent-authored, versioned Resource entries that must
  cite real Raw IDs; and user-visible Note documents whose real source is a
  scope-specific Markdown vault. SQLite stores the index, relations, source
  references, revisions/hashes, and locks rather than the Note body.
- Each Note requires at least one Resource and keeps a low-key, host-managed
  source footer. The Note workspace switches the left rail to the physical
  Markdown path tree, keeps `parent_id` as a semantic parent relation only,
  provides top return/Notes-chat controls, and places a Note-only overall
  wikilink/parent graph in the right rail. Users and the Agent can edit the
  full Markdown body; user-selected UTF-16 ranges can be locked against Agent
  edits, with `NOTE_REGION_LOCKED`, reason, and overlap returned on conflict.
- Verification: Study backend focused coverage passed 66 tests with 2 SQLite
  datetime deprecation warnings; Study frontend focused coverage passed 31;
  `npm run typecheck`, `npm run build`, Study compileall, and UTF-8
  `curate-notes` quick validation passed; the LamTools design audit covered
  85 files with 0 deviations; and the independent Tester passed. Build output
  retains only the existing `::highlight` and ineffective dynamic-import
  warnings.
- No Computer Use/Tauri visual acceptance, complete-repository run, real-model
  semantic acceptance, real-user-library migration, package, commit, or
  release was performed. The heavily dirty and untracked worktree remains
  preserved. Historical `study_note_blocks` is migration input only and is not
  the current Note contract. If visual acceptance is requested, start at
  Study > 笔记 and exercise the file tree, Note chat, right-rail graph, source
  footer, full Markdown edit/preview, CAS conflict, and user-lock conflict.

## Linux x64 desktop distribution implementation closure (2026-09-20)

- Task ID/deployment/state: `linux_desktop_closure_20260920` /
  `linux_desktop_implementation_20260920` / **complete**. The approved scope
  is Linux x64 only: native AppImage and Debian artifacts are implemented and
  verified. macOS is deferred and has no artifact or release claim.
- Runtime contract: Linux packages carry a native, extensionless PyInstaller
  `LamCore` at `lamcore-backend/LamCore`. Tauri mutable state uses
  `app_data_dir()`/XDG data paths, hooks use `XDG_CONFIG_HOME`, and credentials
  use the persistent Linux Secret Service keyring backend. Windows keeps its
  existing `LamCore.exe` and portable data behavior.
- Build/release contract: `scripts/package-linux.sh` performs the native build
  in Ubuntu 22.04 WSL2 whose filesystem is backed by `E:\WSL\Ubuntu-22.04`;
  toolchains, caches, and staging remain on the WSL ext4 filesystem and the
  script rejects `/mnt/c`. It builds the frontend, Linux sidecar, AppImage,
  and `.deb`, then performs package-content and packaged-startup checks. CI
  and release jobs invoke this script. Update selection prefers the versioned
  AppImage and falls back to the versioned `.deb`; the website exposes both
  versioned `latest/download` links.
- Final artifacts (version `0.3.5`, not published):
  `core/desktop/src-tauri/target/release/bundle/appimage/Sunday_0.3.5_amd64.AppImage`;
  186,821,112 bytes, SHA256
  `9A714A659577D6DBBC5DBF28B05ECB7FA6EDD4EABF607F6E1652E2879C47C345`.
  `core/desktop/src-tauri/target/release/bundle/deb/Sunday_0.3.5_amd64.deb`;
  120,093,070 bytes, SHA256
  `B869BF672284EA32F08FA9DAA8EB9DD8C9CFE428867F3B6E08FE63A32BB6B0C7`.
  `artifacts/linux-x64/sidecar/LamCore`; 17,551,704 bytes, SHA256
  `77545A21C1BF49674043DCC2354BD662EB5F1FF004DA76371AAB5FAC6088ED8F`.
- Verification: 15 Linux/update Python tests passed; website build passed;
  workflow YAML parsing, Bash syntax, and `git diff --check` passed; Rust
  release `cargo check` passed; packaged REST/WebSocket/Study smoke passed;
  AppImage and Debian format/content checks passed. Independent AppImage
  smoke observed bundled `LamCore` PID 3883 and exit code 124, with no
  surviving sidecar processes. A broader 55-test run was 50/55 because five
  pre-existing concurrent-network tests failed; those failures were unrelated
  to this Linux distribution delta.
- Git/release disposition: read-only inspection found the heavily dirty,
  concurrently edited worktree and preserved it. No version bump, stage,
  commit, tag, push, GitHub release, or publication occurred. The next
  milestone is an explicitly authorized versioned release; macOS requires a
  separate native/signing implementation before it can be supported.

## Mobile code review, refactor, and bug-fix closure (2026-09-20)

- Deployment `mobile_review_refactor_20260920` is complete. Mobile account
  refresh now uses single-flight coordination with logout/session-generation
  safety; account/workspace transitions are serialized and fenced on unmount.
  Connection and resume generations fence stale results, Noise handshake waits
  are bounded and cancellable, and SyncEngine close waits for started writes.
- `MemoryLocalDatabase` now restores the scoped active bucket correctly. The
  non-native credential default is memory-only; tunnel validation/cancellation
  and `chunk_final` handling are hardened. Capacitor metadata names the app
  `Sunday`. The mobile-only code remains scoped to pairing, lifecycle,
  connection/wire, native capabilities, and local cache concerns.
- Verification recorded by the independent Tester: `npm test -- --reporter=dot`
  passed 12 files / 54 tests; `npm run typecheck`, `npm run build`,
  `npm run cap:sync`, and `git diff --check -- core/mobile` passed. Capacitor
  sync produced no visible native Git diff; the build emitted only chunk and
  dynamic-import warnings.
- No real Android/iOS device, LAN, Relay, or Tauri visual runtime acceptance
  was performed; Windows CocoaPods/xcodebuild checks were skipped. Read-only
  Git handoff: implementation commit `bae53c33` precedes the documentation
  amend; only `.tmp_glass_rg.txt`, `MyProject/`, `artifacts/`, and `docs.7z`
  remain intentionally untracked. Exact next entry point is device/network
  acceptance of pairing, reconnect/resume, workspace switching, and cache
  recovery; do not infer it from the static checks above.

## DSH prompt comparison and Core prompt optimization (2026-09-20)

- Deployment `prompt_comparison_20260920` is in the prompt-optimization
  handoff. The verified comparison used DeepSeek Harness commit `ddefc45f`
  (`0.1.6-alpha.2`, 2026-09-17), its native text-turn snapshot, and the
  system-prompt assembly design. The baseline measured about 4,276 bytes for
  DSH native versus 13,117 characters / 245 lines for the LamTools prompt;
  the post-change prompt measured 11,264 characters / 194 lines, while the
  Skill index fell from 3,341 to 1,878 characters.
- The current Core delta gives every default entry point one canonical,
  one-sentence identity (`你是 Sunday Agent。`) and moves the
  high-frequency Shell, file, search, web, Skill, evidence-reuse, and progress
  rules into one shared tool protocol. MCP activation output is explicitly
  treated as untrusted external data. Study keeps its narrower protocol while
  reusing the shared safety rules.
- Seeded global `AGENTS.md` and `memory.md` templates are filtered from prompt
  context, while customized files remain eligible. The Skill prompt index now
  contains compact trigger hints (full content stays behind `load_skill`).
  Active plans and loop repair guidance are late internal `user` messages so
  the stable system prefix can be reused; internal guidance is excluded from
  recent-user selection and semantic compaction grouping.
- The comparison/optimization does not yet implement the full DSH section
  registry or snapshot/budget gate. The existing LamTools guide/strategy/role
  layers remain unchanged, as does the broader project-context model. These
  are deliberate scope limits, not evidence that those areas were audited as
  complete.
- Verification disposition: focused regression coverage was added for the
  canonical prompt, compact Skill index, template filtering, internal plan
  and repair messages, and compaction grouping. The focused suite passed 259
  tests; the entrypoint/plugin/Study suite passed 237 with 1 skip. `compileall`
  and `git diff --check` passed. The workspace remains heavily dirty and
  concurrent changes are preserved.
- Next milestone: decide whether to add a complete prompt snapshot and budget
  regression gate. No Tauri visual acceptance is relevant to this backend
  prompt change.

## Standalone mobile architecture decision handoff (2026-09-20)

- Task ID/deployment/state: `mobile_standalone_scope_archive` /
  `mobile_standalone_foundation_20260920` / **paused** pending user consensus.
  The confirmed sequence is standalone basic functions first, followed later
  by communication/protocol refactoring.
- Current evidence bounds the architecture: mobile `App.vue` injects only
  `RemoteTransport`/`ConnectionManager` and the local sync cache; Relay's
  README/control/main paths state that Relay stores no Core work data and only
  forwards opaque Noise frames; the shared Workbench requires
  `LamToolsTransport`/App Server semantics; and Python Core owns LLM,
  runtime, and tool execution.
- Proposed minimum scope, awaiting approval and not implemented: phone-local,
  text-only model access and local sessions while paired desktop/Relay remains
  available. File read/write, command/terminal, MCP/plugins, and host tools are
  explicitly excluded. A cloud Core Worker alternative would expand the
  security and deployment scope and is not implemented.
- Targeted stabilization commit `b2761c06` passed the prior mobile checks:
  14 files / 60 tests, typecheck, build, Capacitor sync, and Gradle
  `assembleDebug`. These results do not approve or validate the standalone
  proposal.
- Exact next decision: choose local direct provider/API-key access with
  local-only sessions, or a server-hosted Core. Read-only Git handoff found
  concurrent prompt/backend edits and the documented personal/generated paths;
  this closure made no production/test/diary changes, staging, commit, reset,
  or cleanup.

## Mobile standalone foundation current contract (2026-09-20)

- The verified mobile foundation is local-first: the default entry is an
  independent local mode with a login-free panel. Local projects and sessions
  persist in SQLite, while direct OpenAI-compatible and Anthropic provider
  access is available. The paired desktop/Relay path remains a separate
  option; communication/protocol refactoring is deferred.
- Sync enters through device → project → remote control/import. Browsing cache
  is independent, offline mode disables remote control, and import pagination
  pulls the complete session history. Mobile hides session-title and
  window-switch controls.
- Before replacing an App Server transport, disconnect now clears the old
  client's reconnect timers, preventing an old client from closing a newer
  remote-control connection. Communication protocol refactoring remains
  deferred.
- Verification: mobile coverage passed 16 files / 77 tests; shared UI coverage
  passed 96 files / 757 tests and typecheck; mobile `npm run typecheck`,
  `npm run cap:sync`, and Android `assembleDebug` passed. ADB
  overlay installation on vivo V2536A running Android 16 verified the
  login-free entry, surface-matched dynamic safe area, compact left sidebar,
  long-press context menu, and import.
- The currently offline device's remote-control path was not verified. No
  broader communication/protocol refactor is claimed; preserve all unrelated
  and concurrent worktree changes.
- This is a documentation handoff for the verified foundation only; it does
  not claim a communication/protocol refactor or cloud Core Worker. Preserve
  all unrelated and concurrent worktree changes.

## Mobile floating command dock closure (2026-09-20)

- Deployment `mobile_floating_command_dock_20260920` is complete in production
  code, with APK install confirmation pending. Mobile now exposes a draggable
  optical-glass command dock listing all app/plugin modes plus search, settings,
  and account. The left sidebar retains plugin management and its
  session/project opener; mobile hides duplicate search/settings actions and
  desktop defaults are unchanged.
- GSAP Draggable persists and clamps the dock position, separates drag from
  click, and keeps panel geometry within 12px at 280px and 390px widths.
  Reduced-motion behavior and ARIA listbox/option semantics are covered. The
  independent verifier found and the main agent fixed horizontal overflow and
  listitem semantics; the recheck passed.
- Verification: UI typecheck passed; UI coverage passed 96 files / 761 tests;
  mobile typecheck passed; mobile coverage passed 17 files / 79 tests;
  `npm run cap:sync` and Android `assembleDebug` passed.
- Wireless ADB installation on vivo reaches the OEM package-confirmation step
  but cannot complete without device confirmation, so no real-touch verification
  is claimed. Next entry point: confirm the APK on-device, then exercise dock
  drag/click, mode selection, search/settings/account, and narrow-width states.
- Read-only Git handoff — intended deployment files:
  `core/mobile/src/App.vue`,
  `core/mobile/tests/mobile-command-dock-contract.test.ts`,
  `core/ui/src/app/LamToolsApp.vue`,
  `core/ui/src/components/LeftSidebarShell.vue`,
  `core/ui/src/components/MobileTopBar.vue`,
  `core/ui/src/components/WorkspaceShell.vue`,
  `core/ui/tests/left-sidebar-shell.test.ts`,
  `core/ui/tests/mobile-top-bar.test.ts`, and
  `core/ui/tests/optical-glass-contract.test.ts`.
  Exclude unrelated dirty paths: `agent_docs/project_diary.md`, the modified
  `core/src/lamtools_core/**` prompt/compaction files, their
  `core/tests/test_context_compaction.py`,
  `test_core_default_agent.py`, `test_kernel.py`, `test_project_context.py`,
  `test_skill_runtime.py`, `test_tool_result_model_evidence.py`, and
  `.tmp_glass_rg.txt`, `MyProject/`, `artifacts/`, `docs.7z`. No commit or
  cleanup was performed.

## Mobile Tunnel protocol/transport refactor closure (2026-09-20)

- Task ID/deployment/state: `mobile_tunnel_protocol_archive_20260920` /
  `mobile_tunnel_protocol_refactor_20260920` / **complete**. The external
  Tunnel v1 wire schema is unchanged; TypeScript protocol responsibilities are
  split from transport orchestration, with one shared golden fixture consumed
  by both TypeScript and Rust.
  Limits and chunk boundaries are UTF-8 byte based, sequence values remain
  JavaScript-safe, and continuation frames must preserve the first frame's
  version/type/stream/request envelope. Unknown channels remain rejected.
- LAN, Relay, and Noise behavior remains compatible; Relay continues to carry
  opaque encrypted tunnel traffic. No P0-P2 issue was found in the reviewed
  scope.
- Verification: mobile coverage passed 17 files / 90 tests; mobile typecheck
  and build passed; Rust format and `cargo check` passed; all Rust tests passed
  59/59, including remote tunnel 8/8 and gateway 12/12; Android
  `assembleDebug` and `git diff --check` passed.
- No real-device installation or runtime test was performed in this deployment.
  Read-only Git handoff: unrelated pre-existing backend/context-compaction
  modifications and untracked `.tmp_glass_rg.txt`, `MyProject/`, `artifacts/`,
  and `docs.7z` remain untouched. Exact next entry point is real-device and
  LAN/Relay acceptance of pairing, reconnect/resume, and remote control.

## Desktop 0.3.6 / Android 0.1.2 release and website deployment (2026-09-21)

- Task ID/deployment/state: `close_release_036_website_20260921` /
  `release_036_mobile_012_website_20260921` / **complete**. Desktop `0.3.6`
  and Android `0.1.2` (`versionCode 33`) were built, released, and linked from
  the website at `https://47.114.43.99.nip.io/`.
- The website's Windows download is
  `/downloads/Sunday-latest-x64-setup.exe` (94,081,829 bytes, SHA256
  `2C0F61C0D613DC0C5313E393DE87A6202C3C7D12EC1327A83EFA1B37AE68934A`), and
  the Android download is `/downloads/Sunday-mobile-latest.apk`
  (31,701,668 bytes, SHA256
  `5E60F49BBC7280E849CAB89A0B620AA67719CB3652B63E6F420CACBA92F1A3F2`).
- GitHub Release `v0.3.6` is published at
  `https://github.com/Lam-Arc/LamTools/releases/tag/v0.3.6` with the three
  desktop assets: Windows setup 57,333,030 bytes, Linux AppImage
  186,640,888 bytes, and Linux `.deb` 120,141,358 bytes. These CI artifacts
  are from a separate build pipeline and intentionally do not share the local
  website Windows package's size or hash.
- Release CI run `35524142986` completed green. The Windows job took 10m47s
  and the Linux job 9m24s. The application update check returned
  `up_to_date`; the installed Windows package at `E:\setuptest\0.3.6` passed
  startup, health, WebSocket, Study, and websearch-snapshot checks.
- The Android release APK passed V2/signature, single-signer, version,
  non-debuggable, and non-test-only checks; the mobile release suite passed
  18 files / 97 tests. Website HTTP, content-length, and hash checks matched
  the local Windows and Android artifacts; the web service and relay were
  active.
- Known non-blocking warnings are limited to existing frontend chunk and
  dynamic-import build warnings and the expected difference between local
  website packages and GitHub CI assets. No release blocker remains. The
  untracked `.tmp_glass_rg.txt`, `MyProject/`, `artifacts/`, and `docs.7z`
  remain preserved; no cleanup was performed by this closure. Next entry
  point is ordinary development from the published `v0.3.6` baseline.

## Model catalog/provider refactor closure (2026-09-21)

- Task ID/deployment/state: `archivist_model_catalog_20260921` /
  `commandcode_provider_20260921` / **complete**. The implemented catalog
  keeps the model record ID separate from the upstream API `model_id`; the
  latter remains unchanged for requests, including provider-specific `/` and
  `:` characters. Provider connection data and model definitions remain
  separate JSONC records.
- User-defined groups are persisted in `model_groups.jsonc` with unique names,
  stable IDs, ordered many-to-many memberships, and revision checks. Existing
  models can be added to a group; deleting a group removes only relationships.
  Adding a new model from the group view requires an absolute API base URL and
  either selects a matching existing provider or creates a provider/model and
  membership atomically with rollback on failure. “未分组” is computed in the
  UI.
- Request-format resolution is model-over-provider: explicit model profile,
  provider profile, matchers, then protocol default; inline provider overrides
  are merged before model overrides. RPC/CLI surfaces cover model/provider
  CRUD, group CRUD/reorder/member replacement, and composite model creation.
- `CoreModelCatalogViewToggle` is shared by the main model picker and 设置 →
  模型与供应商. The 按组 / 按供应商 choice is persisted at
  `settings.jsonc` → `core.modelCatalog.classification`. Presets now include
  Command Code, Command Code Free, OpenCode Free, SambaNova Free, Groq Free,
  Google Gemini Free, Cloudflare Workers AI Free, and OpenRouter Free; their
  API-key/documentation links open through the external URL bridge. Free preset
  models are merged into the user `Free` group after creation.
- Verification: backend full run reported `2201 passed`; an isolated rerun of
  the environment-jitter case passed, and a subsequent independent full run
  reported `2202 passed`. Core UI reported 96 files / 773 tests passed;
  UI typecheck and the desktop build passed. These are code/build checks, not
  a claim of manual Tauri visual acceptance.
- Git handoff is read-only: the worktree remains heavily dirty with user and
  concurrent changes, including the separate `project_diary.md` update; no
  reset, cleanup, stage, commit, release, or attribution was performed. Next
  entry point is to open the Tauri Settings → 模型与供应商 page or the main
  model picker and exercise the group/provider toggle, group CRUD, and a real
  provider request with user-supplied credentials.

## Website Windows installer refresh (2026-09-22)

- Deployment `website_installer_20260922` completed without a version bump,
  commit, tag, or GitHub Release. The current dirty worktree was packaged as
  Sunday Desktop `0.3.6` through `scripts/package.ps1`.
- The package pipeline passed the desktop Vite build, PyInstaller plugin
  boundary checks, packaged REST/WebSocket/Study/websearch smoke, Tauri release
  build, and Inno Setup compilation. The resulting setup is 94,124,582 bytes
  with SHA256 `41FEDC6C7F14ED7A6B5F9420DD2CDA780CD386B499E915B85873F60091711343`.
- Local setup acceptance installed to `E:\setuptest\0.3.6`; the verified main
  and backend processes were PID 19560 and PID 10424 from that directory.
- The website download `/downloads/Sunday-latest-x64-setup.exe` was atomically
  replaced at `2026-09-22T02:30:09Z`. HTTP returned 200 and Content-Length
  94,124,582; the server hash matched the local package. The prior 94,081,829
  byte file remains at
  `/var/www/lamtools/Sunday-latest-x64-setup.exe.before-20260922T023008Z`.
- Server verification confirmed the temporary deployment key was removed and
  `lamtools-relay` remained active. The worktree and unrelated untracked files
  were preserved.

## Android bundled catalog repair and website refresh (2026-09-22)

- Android standalone mode now exposes the bundled desktop plugin/skill catalog,
  including Study and its UI mode, with persisted enable/disable state. Shared
  plugin settings recognize Study and Workflow as built in. Desktop's empty
  default hook configuration remains empty; remote mode continues to read the
  connected desktop's live hooks.
- Mobile tests, typecheck, production build, Capacitor Android sync, Gradle
  release build, APK metadata checks, and V2 signature verification passed.
  APK `release/mobile/Sunday-mobile_0.1.2.apk` is 31,709,068 bytes, SHA256
  `58E0E54BCD21602A3AD9E4DA186276701CA15929D1943C97B65568C0BE19035A`.
- Website `/downloads/Sunday-mobile-latest.apk` was atomically replaced at
  `2026-09-22T03:36:46Z`; HTTP returned 200 with matching length. Rollback is
  `/var/www/lamtools/Sunday-mobile-latest.apk.before-20260922T033646Z`.
- Cloud Assistant inspection/deployment/verification invocations:
  `t-hz06xsqi4tfah34`, `t-hz06xsqlku6ar5s`, `t-hz06xsqn3srvqps`.
  Temporary SSH authorization was removed (`KEY_COUNT=0`) and
  `lamtools-relay` remained active.

## Android Tauri 2 shared Rust release candidate (2026-09-22)

- Deployment `mobile_tauri_rust_release_20260922` reached the P1 release-candidate
  boundary. Android now uses the Tauri 2 host and routes standalone model turns
  only through the shared Rust runtime; the obsolete TypeScript provider/tool
  loop was removed and guarded by contract tests.
- Latest signed artifact:
  `release/mobile/Sunday-mobile_0.1.2.apk`, versionCode `1002`, 41,785,124 bytes,
  SHA256 `0D72E68CEB487CFB676E8B20AD46F21BBE6969F0C3669D30437355A883EF203C`.
  It has one V2 signer, certificate SHA256
  `045567d59580c97311203453e104938ad09d9f79e1e78e028f607cdbc4ecb4fb`,
  `arm64-v8a` + `armeabi-v7a`, and passed non-debuggable/non-testOnly,
  `zipalign -P 16`, and arm64 ELF `0x4000` LOAD alignment checks.
- The reported black screen was reproduced on an API 36 x86_64 emulator. Its
  cause was a CSP rejection of `WebAssembly.Module` during
  `noise-handshake`/`xsalsa20` initialization before Vue mounted. The mobile
  CSP now grants only `wasm-unsafe-eval`, the entry point renders a startup
  failure surface if module loading fails, and packaging removes stale emulator
  ABIs before producing the physical-device release.
- Verification passed: mobile 19 files / 108 tests, mobile typecheck and
  production build, `core/runtime-rs` 2 tests, Tauri host 2 tests, both Rust
  format checks, and `git diff --check`. The corrected x86_64 debug build
  launched successfully on the API 36 emulator with the Sunday onboarding
  visible and no CSP/compile/startup exception in logcat. CI includes the same
  frontend/Rust boundary checks plus a real aarch64 Tauri Android debug build.
- The currently published APK remains the earlier 31,709,068-byte Capacitor
  build. Its signer certificate exactly matches the new Tauri APK, but only a
  clean emulator launch has been accepted; in-place upgrade, legacy SQLite
  import, and secure-key continuity on the prior-install physical phone remain
  pending. The website APK was intentionally not replaced. Next milestone:
  connect that phone, perform the upgrade/migration matrix, then publish only
  if it passes.
- Scope remains P1 rather than complete Python Core replacement. Hooks, MCP,
  subagents, compaction, memory, full Study/Workflow backend behavior, and the
  complete model-level official thinking-parameter adapter still require later
  migration before feature parity can be claimed.

## Shared Rust Agent continuation: native protocols, persistence, and approvals (2026-09-22)

- Goal `01a0bad2-6dfd-79b3-b832-3403fcf1e1a1` remains **active**. The Android
  black-screen defect is fixed, but P0-P8 is not complete and the website APK
  remains the prior Capacitor build.
- `core/runtime-rs` now supports native OpenAI Responses and Gemini Generative
  Language request/response envelopes in addition to Chat Completions and
  Anthropic. It maps tools, output limits, official reasoning settings,
  reasoning text, provider-native continuation state, and the actual upstream
  model id. Bundled media/non-reasoning profile variants are embedded too.
- Rust `AgentContext` now owns Sunday identity plus global/project/memory/mode
  sections. Android loads project `AGENTS.md` and `MEMORY.md`; projectless Study
  sessions receive an isolated session workspace and explicit Study mode
  context instead of failing the project-id check.
- Native persistence now covers model/provider settings and plugin/skill
  switches, with one-time legacy localStorage import and no silent fallback.
  The UI file browser and Rust Agent tools share the same native project
  directory, with lazy import of prior SQLite-backed project files.
- Project file writes are `ask_user` operations. Rust returns a serializable
  continuation, the standalone transport persists and projects a normal Core
  approval card, and `approval/respond` resumes the same tool/model chain.
  Per-session approvals are retained in session metadata.
- Verification at this checkpoint: Rust runtime 11/11 tests, mobile Tauri host
  5/5 tests, mobile 22 files / 114 tests, mobile typecheck and production Vite
  build passed, and a real aarch64 Tauri Android debug APK build completed.
- Still pending: complete Hooks engine/config/trust execution, MCP, subagents,
  context compaction, memory/Dreaming, full Study/Workflow Rust backends,
  desktop/CLI Rust host replacement, cross-platform final regression, and the
  real-phone Capacitor-to-Tauri upgrade/data/key migration matrix.

## Shared Rust Hooks and MCP checkpoint (2026-09-22)

- Hooks are now implemented in `core/runtime-rs`: configuration parsing,
  definition hashes and per-hook trust, cumulative decisions, Prompt/HTTP/MCP/
  Command handlers, required-hook fail-closed behavior, and all seven lifecycle
  events are connected to the shared Agent loop. Mobile hook list/config/trust/
  untrust/delete RPCs persist through native SQLite instead of returning an
  empty catalog.
- Shared MCP support now covers server config, stdio JSON-RPC initialization,
  header and JSON-lines framing, tool discovery/calls, permissions, safe result
  formatting, and Hook MCP calls. Android reads global and project MCP config;
  unavailable executables surface as errors instead of fake tools.
- Verification passed: Rust runtime 18 tests, mobile Tauri host 5 tests, mobile
  22 files / 115 tests, typecheck, Vite production build, `git diff --check`,
  and a complete four-ABI Tauri Android debug APK build. No device is currently
  connected, so the latest APK has not received a new runtime launch test.

## Shared Rust Sub Agent, compaction, and Dreaming checkpoint (2026-09-22)

- Shared Rust now owns reusable non-blocking Sub Agents, strict lifecycle/tool
  contracts, independent histories, durable bidirectional mailboxes, approval
  continuation, read-only `consider` filtering, and recursive-delegation
  blocking. Android stores records/mail in SQLite, exposes list/snapshot and
  approval RPCs, and keeps one process-level hub across turns.
- Android sends the complete configured model catalog (including each
  provider credential) into the Rust boundary. Parent tools combine Project,
  MCP, and Sub Agent; child tools combine Project/MCP plus parent messaging.
  Global/project Sub Agent guide and delegation settings persist natively;
  `forbidden` removes the parent delegation tools.
- Rust context compaction and durable runtime history are connected. Context
  windows drive automatic 80%/60% thresholds, the existing retained-step
  setting is honored, recent user instructions survive, and model/fallback
  summaries are bounded. Provider-native state and tool history persist in the
  Android session database and are reused after restart.
- Rust Dreaming appends durable facts to project `MEMORY.md` without replacing
  manual content, uses the existing `core.dreaming` settings, is turn-id
  idempotent, and keeps its throttle checkpoint in SQLite. Dreaming failure is
  reported as best-effort metadata and does not fail the completed main turn.
- Verification at this checkpoint: runtime 23/23, Android host 7/7, mobile 22
  files / 117 tests, mobile typecheck, production Vite build, and an aarch64
  Tauri Android debug APK build passed. The website APK remains unchanged.
- Still pending before P0-P8 completion: full Study/Workflow Rust backends,
  desktop Python-host replacement, Rust CLI, final unified migration/rollback,
  real-phone Capacitor-to-Tauri data/key upgrade, and Windows/Linux/macOS/
  Android final regression.
- Goal remains active. Still pending: subagents, context compaction,
  memory/Dreaming, full Study/Workflow Rust services, desktop/CLI Rust host
  replacement, final cross-platform regression, and the physical-phone
  upgrade/data/key matrix. The website APK remains unchanged.

## Shared Rust Study backend checkpoint (2026-09-22)

- Goal `01a0bad2-6dfd-79b3-b832-3403fcf1e1a1` remains active. This package
  moved Study out of the bundled Python plugin for the native host: the scoped
  knowledge graph, annotations, presentation state and the Study agent tools now
  live in `core/runtime-rs/src/study.rs` and reach the UI through the mobile
  Tauri host.
- `StudyStore` implements the existing contract over SQLite: layered reads with
  revision-bound cursors and the 32 KiB cap, revision-checked incremental
  builds with receipts and outbox events, scoped search and pins, layout state,
  session bindings, marks with the prompt-version migration and anchor
  normalization, and a local-lexicon translate path that needs no model.
- `StandaloneTransport` no longer returns empty Study data: every `study.*` call
  goes to the runtime, session creation and the selected-node teaching position
  stay in the host that owns the session store, and Study failures reject with
  the structured error payload. The Study mode context now comes from the
  shared prompt and latest context rather than a hand-written string.
- Verification: runtime 23 lib + 11 Study tests, Tauri host 9 tests, mobile 23
  files / 125 tests, mobile typecheck, Vite production build, both
  `cargo fmt --check` runs, and `git diff --check`.
- Still pending for full Study parity: the Note vault/Raw/Resource graph and
  note pins, exams with evidence-checked signing, and the streaming selection
  cancel path. `study.exam`, `study.sign` and `study.notes` currently fail
  loudly on mobile instead of returning empty results.
- Remaining migration scope after Study: the Workflow backend, the desktop
  host/CLI Rust replacement, the real-device Capacitor-to-Tauri upgrade matrix,
  and the Windows/Linux/macOS/Android release gate. The website APK is
  unchanged.

## Compaction equivalence fix and Dreaming divergence finding (2026-09-22)

- Goal `01a0bad2-6dfd-79b3-b832-3403fcf1e1a1` stays **active**.
- Context compaction in `core/runtime-rs/src/compaction.rs` now matches the
  shared Python policy in `context_compaction_budget.py` and `tokens.py`:
  - The token estimator is no longer a byte-length heuristic. It categorises
    characters the same way `estimate_text_tokens` does (ASCII / 3.5,
    CJK / 1.5, emoji × 2, other / 2) and charges the documented per-message
    overhead (200 exact, 100 fast) plus 50 tokens per tool call. The previous
    `bytes / 4` estimate undercounted ASCII text by roughly 12 % and charged
    almost no per-message overhead, so the native host compacted later than the
    Python host for the same conversation.
  - The trigger decision uses `measure_for_compaction_trigger` semantics: the
    fast estimate is trusted only while `fast × 8 < trigger`, otherwise the
    exact estimator runs. This is the guard the Python comment added because
    Unicode-heavy text can be substantially undercounted.
  - An explicit `compact_trigger_tokens`/`compact_limit_tokens` of `0` is
    treated as unset and falls back to the shared 80 % / 60 % ratios, matching
    Python's `X or default`.
  - `align_tail_start` documents and enforces the retention invariant that the
    retained tail never begins on a tool result, so a request can never carry a
    tool result whose assistant tool call was summarized away. Python needs the
    same guard in its history trim (`while history[cut].role == "tool"`); in
    Rust the split is always anchored on a user message, so this is a defended
    invariant rather than a live defect.
  - Tests: `token_estimation_follows_the_shared_unicode_policy`,
    `an_explicit_zero_budget_keeps_the_shared_ratio_policy`, and
    `compaction_never_orphans_a_tool_result`. Runtime is now 26 lib tests.
- **Verified defect, not yet fixed — Dreaming is not equivalent.** Rust
  `core/runtime-rs/src/memory.rs` writes `MEMORY.md` in a different format than
  the Python implementation in `mem/memory_file.py`:
  - Python owns a structured, sectioned document: the fixed `# Memory` header,
    the five sections `Preferences` / `Facts` / `Decisions` / `Todo` /
    `Deprecated`, `- [YYYY-MM-DD] content — source: <id>` entry lines with
    human-authored entries (no `source`) preserved forever, in-place update of
    an existing `(source, section)` pair, and a 20 000-character budget that
    trims machine entries before human ones.
  - Rust appends every extracted fact under an unprefixed `## Dreaming update`
    heading with plain `- ` bullets, uses a different header line, and guards a
    262 144-character limit instead of 20 000.
  - Consequences, in order of severity: (1) `MEMORY.md` grown by the native
    host exceeds `MAX_MEMORY_MD_CHARS = 20000` and
    `ProjectContextLoader`'s per-file read cap, so memory silently stops
    reaching the system prompt while dreaming keeps appending; (2) Python never
    parses Rust's `## Dreaming update` bullets as structured entries, so they
    are carried verbatim, can never be de-duplicated or suppressed, and the
    section grows without bound; (3) Rust's `existing_memory.contains(update)`
    is a substring check rather than Python's per-`(source, section)` update.
    Python preserves unknown lines verbatim, so this is not data loss — it is a
    format split plus silent truncation of the loaded memory.
  - Required fix: port `mem/memory_file.py` (parse / render / append-new-entries
    / section-tail / budget trim / merge / suppress) into the shared runtime and
    have `dream_with_model` return structured entries that the host merges with
    those semantics. Nothing was claimed as migrated here; the file-format split
    is recorded so the next Dreaming package fixes it rather than adding another
    strategy.
- Verification after this pass: `core/runtime-rs` 26 lib tests + 11 Study
  integration tests, Tauri host 9 tests, mobile 23 files / 125 tests, mobile
  `vue-tsc` typecheck, Vite production build, `cargo fmt --check` for both
  crates, and `git diff --check` all pass. No APK was rebuilt and the website
  APK is unchanged.

## Shared Rust Study exams and assessment signing (2026-09-22)

- Goal `01a0bad2-6dfd-79b3-b832-3403fcf1e1a1` stays **active**. No version was
  published; the website APK is unchanged.
- Added `core/runtime-rs/src/study_exams.rs` (declared from `study.rs` as
  `mod exams`) porting the bundled plugin's `exams.py` and the `sign` path from
  `store.py`:
  - `study.exam` with `create` / `list` / `get` / `reference` /
    `save_answers` / `submit` / `help` and the versioned `grade` / `review`
    pair.  Public reads allowlist learner-safe fields, so the private
    answer/rubric never leaks through an ordinary exam response, and `help` is
    only projected for the requested question.
  - Validation matches the reference: question type/prompt/node ownership,
    positive bounded scores, choice options, private grading-step limits,
    per-question results covering every question exactly once, assessed and
    incorrect node ownership, and `uncertain` results carrying no evidence.
  - Scores stay authoritative: a coarse or stale `state` is normalized from the
    score instead of rejecting a semantically valid model grade, and helped
    questions are excluded from independent mastery evidence.
  - Grading versions increment only on a real change; an exact retry or a
    repeat of the last `grading_hash` returns the stored document without a new
    version, `grading_history` keeps the previous grade, and
    `request_id` receipts reject a conflicting retry.
  - Auto-derived suggestions reproduce the reference thresholds (pass at 0.6,
    `medium` at 0.8 with two or more unhelped questions, `high` only at 1.0 with
    a prior pass on a different exam) and quote the supporting question ids.
  - `study.sign` requires a graded exam, the current `grading_version` and exact
    supporting `question_ids`; it rejects caller-supplied evidence fields,
    matches the graded suggestion (including mastery and reason), refuses
    helped, uncertain or malformed question evidence, resolves merge aliases,
    writes `assessment` records with retained history, bumps the node's
    `state_revision`, emits a `study.mastery.changed` outbox event and stores a
    `study_sign_receipts` row so retries replay the original result.
- Host wiring: `sunday_study_rpc` now routes `study.exam` and `study.sign`, and
  the Study tool list exposes `sign` and `exam` from the plugin's own
  `tools.jsonc`.  `study.notes` remains the only Study operation that fails
  loudly because the Note vault is still Python-only.
- Tests: `core/runtime-rs/tests/study_exam.rs` adds 8 contract tests covering
  public/private separation, creation guards, grading guards, derived mastery
  and idempotency, state normalization with helped questions, evidence-checked
  signing, and unknown-id rejection.  The Tauri host adds an end-to-end
  create → submit → grade → sign round trip through `dispatch_study`.
- Verification: runtime 26 lib + 11 Study + 8 exam tests; Tauri host 10 tests;
  mobile 23 files / 125 tests; mobile `vue-tsc`, Vite production build, both
  `cargo fmt --check` runs and `git diff --check` all pass.
- Still Python-only and not claimed as migrated: the Study Note vault
  (`study.notes`, note pins and the Raw/Resource layers), the Workflow backend
  (20,843 Python lines across 27 modules), and the desktop host/CLI Rust
  replacement (the Python application is 102,722 lines).  Those are multi-session
  packages, not single-session ones.

## Study Note vault disabled on the mobile host via a capability declaration (2026-09-22)

- Goal `01a0bad2-6dfd-79b3-b832-3403fcf1e1a1` stays **active**. The Rust Study
  migration does not include the Note vault yet, so the mobile host previously
  offered a "笔记" entry that could only fail. That entry is now gone instead of
  being reachable-but-broken.
- The gate is a general host capability declaration rather than a mobile special
  case, because the Note vault is a host capability and not a UI preference:
  - `PluginUIEntry.capabilities?: string[]` (`core/ui/src/plugins/types.ts`)
    declares what a mode can serve. Absence means the host makes no claim and
    every surface stays available; an empty list claims the host supports none.
  - `PluginModeHost` publishes the active mode's declaration through
    `CorePluginModeContext.modeCapabilities`.
  - `StudyView` derives `notesEnabled` from it, refuses `navigate('notes')` when
    the capability is absent, and passes the flag to the sidebar host.
  - `StudySidebar` hides the 笔记 entry when the host has no vault, while 图谱,
    搜索 and 管理你的知识 stay available.
- Desktop keeps the vault: `study/plugin.json` now declares
  `"capabilities": ["notes"]`, and the Python manifest parser, model and
  `plugin.ui.list` serializer pass the declaration through. Undeclared modes
  (for example `workflow`) omit the field so the UI keeps their surfaces.
- Mobile declares `capabilities: []` for Study in
  `StandaloneExtensionsStore.plugin.ui.list`, and `study.notes` still fails
  loudly at the RPC boundary as a second line of defence.
- Tests: Python covers optional parsing, empty-versus-absent separation, invalid
  declarations being skipped at discovery, and the declaration surviving the
  `plugin.ui.list` boundary; the shared UI covers the hidden entry plus the
  guarded navigation and capability read; mobile asserts the declared empty
  capability.
- Verification: `core/ui` 96 files / 778 tests and its typecheck, `core/mobile`
  23 files / 125 tests plus typecheck and production build, Python plugin tests
  139 passed plus 16 registry tests, and the desktop frontend build all pass.
  The running Tauri dev instance stayed healthy and reloaded both sides.

## Mobile runtime acceptance on the Android emulator (2026-09-22)

- Goal `01a0bad2-6dfd-79b3-b832-3403fcf1e1a1` stays **active**. This pass closes
  the gap that matters most: the Rust Study migration had only ever been
  compiled and unit-tested on the host target, never built for Android and never
  run on a device.
- Android target builds: `npx tauri android build --debug --apk --target
  aarch64 --ci` and the same with `--target x86_64` both succeed. This is the
  first proof that the `rusqlite` `bundled` dependency added to
  `core/runtime-rs` cross-compiles SQLite for Android.
- Runtime evidence on the API 36 x86_64 emulator (`lamtools_api36`), fresh
  install of the x86_64 debug APK:
  - The app launches with no black screen, and logcat contains no CSP,
    `WebAssembly`, `CompileError` or JavaScript error; the first-run onboarding
    renders normally.
  - Creating a project works, and Study mode activates with its own header and
    composer placeholder.
  - The Study navigator shows 搜索 / 管理你的知识 / 图谱 and **no 笔记 entry**,
    which is the capability gate working on a real device: the desktop
    navigator still has 笔记 in the same position.
  - Selecting 图谱 renders the empty-graph state ("0 个节点 0 条关系") instead of
    an error surface, so `study.get` round-tripped through
    `StandaloneTransport` → Tauri command → `StudyStore`.
  - `state/study.db` exists next to the other native state files, and its schema
    is exactly `StudyStore::ensure_schema`: `study_records`,
    `study_scope_meta`, `study_receipts`, `study_sign_receipts`,
    `study_outbox`, `study_session_bindings`, `study_pins`,
    `study_course_removals`, with `study_scope_meta` holding
    `structure_revision` and `state_revision` under the
    `local-userlocal-environmentdefault` compatibility scope key.
- Still **not** verified, and not claimed: a real model turn (no provider
  credential on the device), graph writes from the agent, the exam and signing
  flows end to end on a device, and any physical-device (as opposed to
  emulator) upgrade or data-migration run. The desktop host received only
  startup-level verification (window, backend connection, successful RPCs on
  the Python side), not interactive feature acceptance.
- Screenshots and the pulled database are under `artifacts/mobile-acceptance/`.

## Desktop 0.3.7-beta.1 build and installer fix (2026-09-23)

- Goal `01a0bad2-6dfd-79b3-b832-3403fcf1e1a1` stays **active**. Nothing was
  published, tagged, or pushed; the website APK and GitHub Releases are
  untouched.
- Version raised to `0.3.7-beta.1` in all five locations (tauri.conf.json,
  Cargo.toml, desktop package.json, pyproject.toml, `__init__.py`). The beta
  suffix is deliberate and safe in an unusual way:
  - `scripts/bump-version.ps1` and the `release.yml` tag guard both require a
    bare `x.y.z`, so `v0.3.7-beta.1` can never be published by the release
    workflow. A beta cannot be mistaken for a release.
  - `scripts/package.ps1` and `installer/build-installer.ps1` accept the
    suffixed form, so the local installer keeps the beta identity in its
    filename and in `AppVersion`.
  - `update.check` tolerates the suffix by design (`compare_versions` only
    reads dotted numeric segments), so a beta build never fails its update
    check.
  - Known limitation, pre-existing and not introduced here: because
    `compare_versions` ignores pre-release ordering, a `0.3.7-beta.1` install
    compares as newer than a future stable `0.3.7`, so it would not be offered
    that upgrade. Betas are for local acceptance, not distribution, so this was
    left alone rather than changing release semantics.
- Fixed the installer so a beta version can actually compile: Inno Setup's
  `VersionInfoVersion` is a numeric file version and rejected `0.3.7-beta.1`
  ("Value of [Setup] section directive VersionInfoVersion is invalid"), which
  aborted the installer at the last step. `Sunday.iss` now takes a separate
  numeric `VersionInfoVersion` define, and `build-installer.ps1` derives it by
  stripping the pre-release suffix and exports it in its result object
  (`version_info`). Display version and Windows file version are therefore
  independent, and a stable build's file version is unchanged.
- Acceptance (project skill `lamtools-setup-install`, Inno
  `/VERYSILENT /NORESTART /DIR=`): installed to `E:\setuptest\0.3.7-beta.1`
  and verified `app_file_version = 0.3.7-beta.1` with the main process and the
  packaged `lamcore-backend\LamCore.exe` both running from that directory.
  Installer: `core/desktop/src-tauri/target/release/bundle/inno/Sunday_0.3.7-beta.1_x64-setup.exe`,
  93,997,103 bytes, SHA256
  `de1549a7bf5f1f625febbc24314999a04020186498755a56ef49fc0259d2bf80`.
  The first acceptance attempt failed because a running `tauri dev` instance
  held the single-instance lock and the installed app handed off and exited;
  closing the dev instance made the verification pass. This is a test-environment
  conflict, not a product defect.
- Verification boundary: `package.ps1` steps 1-3 (frontend, PyInstaller backend,
  Tauri release executable) succeeded in the run that failed at step 4, and the
  repaired step 4 then succeeded on its own against that staged payload. A
  single end-to-end `package.ps1` run of the repaired script has not been done,
  so the full chain is not yet proven in one pass. `release.yml` runs the same
  path in CI.
- Mobile artifact for the same acceptance round:
  `release/mobile/Sunday-mobile_0.1.2-debug-aarch64.apk`, 203,208,324 bytes,
  SHA256 `9c1ddd87fd324c73d0f9009eb78ae58669324fa27fc23efbc819e6131a00d643`,
  arm64-v8a only, debug-signed (installable, not publishable).

## Fixed: structuredClone rejected reactive state in the mobile stores (2026-09-23)

- Reported error: `Failed to execute 'structuredClone' on 'Window': #<Object>
  could not be cloned.` The desktop chain is not the source: `core/desktop/src`,
  `core/ui/src`, `core/desktop/node_modules/@tauri-apps` and
  `core/mobile/node_modules/@tauri-apps` contain no `structuredClone` call, so
  every call site lives in the mobile standalone stores.
- Root cause, reproduced in a test (`structuredClone` on a `reactive(...)`
  object throws): the stores let Vue reactive proxies into persisted state and
  then cloned that state on read.
  - `StandaloneConfigStore` `settings.update` shallow-merged the caller's
    object (`{ ...existing, ...value }`) and `config.subagent.settings.set`
    assigned `current[key] = value`, so a reactive value written from a settings
    panel stayed in `state` as a proxy.
  - `settings.get` additionally returned `state.settings[namespace]` **by
    reference**, so the UI could mutate stored state and a reactive copy of it
    could leak back in from the other direction.
  - The reads in `settings()`, `normalizedSubAgentSettings()` and
    `StandaloneExtensionsStore.runtimeHooks()` then called
    `structuredClone(state...)` and threw.
  - `LocalRepository` had already been hardened for exactly this shape (its
    private `clone` catches and falls back to JSON), but that hardening was
    never shared with the other two stores — the same defect was fixed in one
    place and missed in three.
- Fix: one shared `cloneState` helper (`core/mobile/src/storage/cloneState.ts`)
  that prefers `structuredClone` and falls back to a JSON round-trip, now used
  by every call site. Writes are isolated (`settings.update`,
  `config.subagent.settings.set` clone before storing), reads are guarded
  (`settings()`, `normalizedSubAgentSettings()`, `runtimeHooks()`), and
  `settings.get` returns a copy instead of its internal object.
  `LocalRepository` reuses the same helper so the fallback has one home.
- Tests: `core/mobile/tests/clone-state.test.ts` asserts that
  `structuredClone` rejects a reactive proxy while `cloneState` accepts it, and
  covers the real paths — a reactive `settings.update` value read back through
  `settings()` and `settings.get`, a reactive Sub Agent role assignment read
  back through `subAgentRuntime()`, and the hook/MCP config read. Mobile is now
  24 files / 130 tests, plus typecheck and production build.
- Not covered: the desktop packages were not rebuilt for this change, because
  the fix is mobile-only and the desktop chain never calls `structuredClone`.
  The previously delivered mobile APK predates the fix and was rebuilt.

## Mobile: model requests had no timeout, so a stalled turn never returned (2026-09-23)

- Reported symptom: in Agent mode a message produced no reply and no error, the
  turn stayed running with the elapsed time counting up, and the composer kept
  showing the stop action. A previous turn had surfaced the `structuredClone`
  error (fixed separately).
- Root cause, located at `core/runtime-rs/src/provider.rs`: the HTTP client was
  built with headers only —
  `reqwest::Client::builder().default_headers(headers).build()` — with no
  `.timeout()` and no `.connect_timeout()`. reqwest applies no request timeout by
  default, so when the target address never answers (DNS black hole, stalled TLS
  handshake, server that accepts but never responds) the `send()` future never
  resolves. The turn then holds neither a result nor an error, which is exactly
  the observed shape: UI running, elapsed time growing, no output.
- The Python host does bound this: `config/retry_store.py` defines
  `DEFAULT_MODEL_RETRY_CONFIG` with `model_timeout_seconds: 360`,
  `model_retries: 10`, `retry_delays_seconds: [1, 1, 2, 5, 5]`, `jitter: true`
  and `empty_response_retries: 3`. None of that had been ported to the Rust
  provider.
- Fix, aligned to those defaults rather than inventing a policy: added a
  `RetryPolicy` (attempts 10, timeout 360 s, delays 1/1/2/5/5 with the tail
  repeating, clock-seeded 0.5x–1.5x jitter) and `HttpModelBackend::with_retry_policy`;
  the client now sets `.timeout(policy.timeout)`, and `complete` sends through
  `send_with_retry`, which retries transport failures, timeouts, 5xx and 429
  within the attempt budget and returns a real error otherwise. A 4xx stays
  fatal because retrying cannot help it.
- Tests in `provider.rs`: the wait rhythm matches the shared baseline, jitter
  stays inside 0.5x–1.5x, and — the one that matters — a provider that accepts a
  connection and never answers now fails inside the bound instead of hanging
  (a local listener that reads the request and stays silent; the call returns an
  error in ~1 s with a 1 s timeout where it previously never returned at all).
- Not yet ported, recorded rather than implied: `empty_response_retries`
  (re-issuing after an empty completion) and the streaming idle timeout, which
  does not apply while the Rust provider sends `stream: false`.
- The refreshed ARM64 trace debug APK variants include this Rust provider fix;
  neither has yet been tested on a phone.

## Mobile layout and request-trace fixes (2026-09-23)

- The narrow sidebar fix removes the 18px peek constraint while the drawer is
  open. The Android native inset bridge supplies the status-bar top inset, and
  the app retries a temporary zero value. The shared desktop TitleBar is now
  explicitly hidden when `runtime.platform` is mobile, avoiding the fixed
  desktop titlebar overlapping Android status content.
- Verification: mobile layout contract 4/4; mobile suite 154/154; focused UI
  tests 36/36; mobile and shared UI typechecks passed. The in-chat trace begins
  before model lookup and the first message save, avoids intermediate
  persistence, and passed targeted coverage 28/28.
- ARM64 debug-signed APK:
  `core/mobile/artifacts/Sunday-mobile-trace-debug-0.1.2-20260923-debug-signed.apk`
  (216,634,556 bytes; SHA256
  `C2561DE2AF20D07B0186C14299F73ECF8DCF5F29D54A68DCF7468C282D87A41C`;
  signing certificate `a6fed859…a30c`, matching the prior debug signer).
- ARM64 release-signed APK:
  `core/mobile/artifacts/Sunday-mobile-trace-debug-0.1.2-20260923-release-signed.apk`
  (216,634,556 bytes; SHA256
  `220222D066E0F6AAF8C08BBAFB6B1D8C3C756B6829EDE4E3C4C87AB5DFEA0B1D`;
  signing certificate `045567d5…4fb`, matching the prior release signer).
  Both packages are `com.lamtools.mobile`, versionName `0.1.2`, versionCode
  `1002`, ARM64, targetSdk 36. Neither has been phone-tested or visually
  accepted.
- This earlier trace build was superseded by the network-stall follow-up below.
  The Rust refactor remains incomplete.

## Desktop command shell setting (`shell_session_fix_20260923`)

- Deployment `shell_session_fix_20260923` is complete. Desktop Python shell selection is configured by `core.commandShell`, exposed in GUI Settings and through `command-shell get/set`. Windows automatic selection is WSL → Git Bash → PowerShell; explicit unavailable choices fall back safely. Linux keeps native command behavior, and Android hides the setting.
- Agent command execution and Workflow execution share a shell resolver. WSL discovery uses a cached probe bounded to 4 seconds; command working directories use `--cd`, workflow WSL environment forwarding is explicit through `WSLENV`, and path validation respects each shell's quoting rules.
- UI corrections route duplicate error notices once, prevent replayed terminal events from an older turn closing a newer running turn, and project `final_response` / `has_tool_calls` while retaining interim text in process state. Send/stop glyphs and composer trail now share the composer background, including its gradient and theme changes.
- Verification: 5 UI test files / 75 tests passed; 4 Python suites / 111 tests passed; `npm run typecheck` passed; `git diff --check` exited 0.
- Boundary: real WSL working-directory execution remains unverified because WSL hung for over 50 seconds on this host; the bounded probe now falls back. No Tauri UI or Android device observation was performed, per code-only verification. Rust/mobile refactor files were untouched by this deployment. No commit, tag, or push was made.

## Mobile HTTP send stall follow-up (mobile_http_send_stall_20260923; 2026-09-23)

- Phone trace evidence: at 12:04:14 the turn reached `http_send_start`; by about
  12:11 it had emitted neither response headers nor an error stage. The provider
  console had no matching request. This places the stall at or before response
  headers, but does not identify whether DNS, TCP connect, TLS, routing, or
  another transport condition caused it.
- Rust provider now caps connection establishment at 15 seconds, shows a fixed
  waiting stage after 30 seconds, applies a 120-second deadline before response
  headers, and permits at most two pre-header attempts. The existing 360-second
  response-body timeout and retry behavior for 5xx responses remain. JavaScript
  trace stage labels are fixed for this path.
- Verification: `core/runtime-rs` cargo tests passed; mobile suite 154/154 and
  mobile typecheck passed. Two ARM64 APK variants were rebuilt, versionCode
  1002, versionName 0.1.2, targetSdk 36; their signing certificates match the
  corresponding previous debug/release variants. Neither new APK has been
  phone-tested.
- Debug-signed APK:
  `core/mobile/artifacts/Sunday-mobile-trace-network-0.1.2-20260923-debug-signed.apk`
  (216,802,308 bytes; SHA256
  `30501B9735ADD0C4E13FA0B3CDBBA041DC11C3E1264F2B0C5DC81DEC4F415405`).
- Release-signed APK:
  `core/mobile/artifacts/Sunday-mobile-trace-network-0.1.2-20260923-release-signed.apk`
  (216,802,308 bytes; SHA256
  `01D59CFA6A8F050693726A2A0617247013EE4219CA4BE6508D937E91B7E304FE`).
- This checkpoint is superseded by the isolated-send follow-up below. The
  12:47 trace exercised the request-build APK; the new isolated-send APK pair
  remains untested on the user's phone.

## Mobile request-build trace follow-up (mobile_http_send_stall_20260923_closure; 2026-09-23)

- The earlier 12:04 phone trace came from the older APK built at 11:24. It
  reached `http_send_start` without headers or an error by about 12:11, but it
  predates the latest request-build instrumentation and cannot verify that
  build. The screenshot's model label matches the Command Code preset; the
  actual provider configured on the phone is still unknown, so confirmation was
  requested. The phone-side network root cause remains unproven.
- Rust now builds the HTTP request before emitting the fixed
  `http_request_built` stage; build failures emit `http_request_build_error`.
  The bounded pre-header wait/retry is retained, and JavaScript maps both stages
  to fixed labels. Connection establishment is capped at 15 seconds, a fixed
  waiting stage appears after 30 seconds, the pre-header deadline is 120 seconds,
  and there are at most two pre-header attempts. The existing 360-second
  response-body timeout and 5xx retry policy remain.
- Verification: runtime Rust test groups passed 64 + 11 + 8 + 2 + 11 + 9 + 9;
  16 focused provider tests passed; mobile passed 154/154 and its typecheck
  passed. Both ARM64 APKs are version 0.1.2 / versionCode 1002 / targetSdk 36;
  the packaging script verified that their signatures match the corresponding
  previous debug and release signing identities. Neither new package has been
  tested on the user's phone.
- Release-signed APK:
  `core/mobile/artifacts/Sunday-mobile-trace-request-0.1.2-20260923-release-signed.apk`
  SHA256 `A9C8BEA0AF8095FA70B0CF4555093D7F55ECDCD59B7498F767187CCE14BF95D7`.
- Debug-signed APK:
  `core/mobile/artifacts/Sunday-mobile-trace-request-0.1.2-20260923-debug-signed.apk`
  SHA256 `E8A614FAEECAFCD12094EAF66F64DC01092DF5BEB3EB2B72C28AB9A9B70BC191`.
- This request-build checkpoint is superseded by the isolated-send follow-up
  below. The Rust refactor remains incomplete.

## Mobile HTTP stall second-trace handoff (mobile_http_send_stall_20260923_second_trace_handoff; 2026-09-23)

- New phone evidence: the request reached `http_request_built` at 12:47:08, then
  showed no native 30-second marker for more than two minutes. The phone showed
  Command Code selected. This still does not establish why the native request
  task is not progressing.
- Desktop control probe succeeded in about 25 seconds with one step and a final
  reply using `run-local --model-id deepseek/deepseek-v4.1-flash --no-thinking
  --max-tokens 128 你好` against `https://api.commandcode.ai/provider/v1`.
  This validates the desktop Python path only; it does not verify the Android
  request path or actual phone provider configuration.
- Rust now spawns the reqwest send task before publishing the built stage, with
  abort-on-drop and independent watchdogs. The JavaScript trace emits host-side
  wait markers at 35 and 125 seconds while the native invoke remains pending.
  `core/runtime-rs/Cargo.toml` enables Tokio macros as a normal dependency and
  multi-thread runtime support for dev tests. A standalone production check had
  previously failed without the macros feature; this was a feature-gating issue,
  not an Android runtime result.
- Verification: full Rust tests passed (67 unit tests and all integration
  suites); `cargo check --lib` passed; mobile passed 156/156 and typecheck passed.
- New ARM64, version 0.1.2, versionCode 1002, targetSdk 36 packages were signed
  and checked against the previous signing identities. The isolated request
  variants below have not yet been tested on the phone.
- Release-signed APK:
  `core/mobile/artifacts/Sunday-mobile-trace-isolated-0.1.2-20260923-release-signed.apk`
  SHA256 `D1FF09A435806655568D6AD043018A57448BBE71D5E6A456D8467698702A2FC6`.
- Debug-signed APK:
  `core/mobile/artifacts/Sunday-mobile-trace-isolated-0.1.2-20260923-debug-signed.apk`
  SHA256 `7E64BD32D4A3FFEA1D2E1AB914401D5258D9826012D067BFB296B315F324BB33`.
- State: paused pending a phone test of these isolated-send APKs and its new
  trace. Root cause remains unproven; broader Rust Workflow/refactor work is
  incomplete. The working tree is dirty; preserve unrelated changes. This is a
  read-only handoff with no commit or cleanup.

## Mobile project files and long-running chat progress (2026-09-23)

- `root.list_files` accepts an empty path and returns `project_root`, allowing
  project files to be browsed from the root. Android project files live under
  `app_data_dir()/projects/<project ID>`; Android's system file manager usually
  does not expose this app-private directory.
- Long-running chat execution logs now appear as an animated phase progress
  bar. The terminal progress indicator hides about 1.5 seconds after success or
  failure; answer and error bodies remain separate and do not concatenate the
  execution log.
- Verification passed: runtime Rust suite 119 tests; mobile 156 tests across 27
  files; UI 793 tests; mobile Vue typecheck; Android `cargo check`; Gradle Kotlin
  compilation; ARM64 signed APK build; design scan 87 files / 0 deviations.
  Emulator installation was blocked by `Can't find service: package`; no
  real-device HTTPS or visual acceptance is claimed.
- Published signed diagnostic APK:
  [Sunday-mobile-progress-root-0.1.2-20260923.apk](https://47.114.43.99.nip.io/downloads/Sunday-mobile-progress-root-0.1.2-20260923.apk)
  (218,855,436 bytes; SHA256
  `7A845855B1830C80D4EE3D7FB599BAEF5585B3DFD007F63ED494384B9D5942BB`).
- The full Rust migration remains incomplete.

## Mobile streaming release handoff (mobile_streaming_audit_20260923; 2026-09-23)

- Closure state: complete for the scoped Command Code/DeepSeek streaming repair
  and website APK switch. OpenAI Chat SSE now streams UTF-8 text, reasoning, and
  indexed tool calls; native and JavaScript events batch at 32 ms and 50 ms.
  Retry/reset and final-response authority, internal compaction/dreaming gates,
  fixed release stages, and frontend reasoning-terminal cleanup are covered.
  Anthropic, Responses, and Gemini remain final-only. The wider Rust refactor is
  incomplete and there is no real-phone proof.
- Verification passed: runtime 122 tests; mobile 158 tests across 27 files; UI
  793 tests across 98 files; typecheck; mobile Vite build; design scan 87 files /
  0 deviations; signed universal Android APK build for ARM64 + ARMv7 with 16 KiB
  alignment. APK version is 0.1.2 / versionCode 1002 and uses the prior
  diagnostic signing certificate.
- Website stable download now serves the 49,158,412-byte APK with SHA256
  `57958F1C739B4B2FC65556D49AD567A80A3CF21DD1C352791D31200609CFB561`; the
  versioned and stable public URLs both returned HTTP 200 and the full stable
  GET matched that hash. The older public artifact was archived. Caddy-lamtools
  and relay are active; temporary server SSH authorization was revoked.
- Read-only Git handoff: working tree remains broadly dirty with unrelated and
  ongoing Rust/mobile refactor work. Preserve it. No commit, tag, push, or
  cleanup was performed. Local temporary SSH key files remain at
  `C:\Users\ADMINI~1\AppData\Local\Temp\lamtools-mobile-stream-upload-20260923`
  after automatic exec approval rejected removal; the server no longer
  authorizes this key. No staging file remains.

## Sunday SVG system-prompt language experiment (sunday_svg_ab_closure; 2026-09-23)

- State: complete. The one-run-per-language test used Sunday `run-local` with
  `deepseek/deepseek-v4.1-flash`, thinking `max` (极高; budget 16,384),
  temperature 0.7, and the task “直接使用 SVG 画一个动态的鹈鹕骑自行车”.
  The only experimental variable was the full system-prompt language.
- Results: Chinese system prompt — 49 model steps, 52 tool calls, 13 failed
  (25.00%), 723.273 s, 4,053,398 reported tokens; English system prompt — 22
  steps, 29 calls, 3 failed (10.34%), 525.865 s, 2,136,453 reported tokens.
  The Chinese run had one empty model response without provider usage, so its
  true token total is not exact; reported totals exclude that response.
- Both SVGs parsed and showed code-driven frame differences at 0.4 s. No human
  visual evaluation was performed. One run per language, so the observed
  differences do not establish a causal language effect. No production code
  changed; stronger evidence would require repeated runs.

## Sunday code-task system-prompt language experiment (sunday_code_dev_bug_ab_20260923; 2026-09-23)

- State: complete. Four Sunday `run-local` conditions used DeepSeek V4.1 Flash,
  thinking `max` (极高; budget 16,384), temperature 0.7: development and bug
  repair, each with Chinese or equivalent English system prompts. All four
  independently passed the 8-case acceptance suite.
- In this sample, English was faster and used fewer reported tokens: development
  95.212 s / 185,853 tokens (zh) versus 78.329 s / 150,237 (en); bug repair
  74.344 s / 150,693 (zh) versus 32.675 s / 56,515 (en). Development had one
  failed tool call in each language; bug repair had none. One run per condition
  does not establish a causal language effect.
- Canonical detail and four output files are in
  `core/experiments/sunday_code_dev_bug_ab_20260923/REPORT.md` and its
  `runs/*/outputs/order_quote.py`. No production code changed; repeat both task
  pairs if a stronger causal comparison is required.

## Sunday English system-prompt rollout (sunday_system_prompts_english_20260923; 2026-09-23)

- State: complete. Sunday-owned preset prompts now have equivalent English
  text across Python main/auxiliary paths, shared Study Python/Rust,
  subagent defaults, mode/shell fragments, and the bundled skill index.
  User-authored and current global configuration remain unchanged.
- Handoff export accepts the new English metadata prefixes and legacy Chinese
  prefixes. Focused code-only verification passed: independent English prompt
  9, subagent/export 72, skill 12, config defaults plus English prompt 10,
  Study Python 48, Study Rust 11, auxiliary Python 146, and `git diff --check`.
- No broad full-suite or GUI run is claimed. Next entry point: preserve both
  metadata-prefix forms and rerun the focused checks when prompt sources change.

## Glass top-highlight removal (glass_top_highlight_20260928; 2026-09-28)

- State: complete. The shared optical-glass primitive no longer paints any
  highlight along the top of a pane: the upper-left radial specular and the
  top inset line were both removed, and the two tokens that fed them
  (`--optical-glass-reflection`, `--optical-glass-inset-top`) were retired.
  Retained: the 2px neutral grey physical edge, the left/right 1px inset
  transitions, the gray-green lower refraction, and the short two-layer shadow.
- Verification: `core/ui` contract suite passed 101 files / 828 tests. The glass
  contract test now pins the absence instead of the retired values (the
  `::before` rule carries no radial-gradient and no `inset 0 1px 0`; both
  tokens are gone from `variables.css`). A stylesheet-level before/after render
  measured the row just inside a pane's top edge dropping from 149 to 125
  luminance against a 131 interior baseline, and the upper-left wash delta from
  4.9 to 2.2.
- Spec: `lam-design-spec` now states the glass top must stay free of highlight
  and forbids re-adding it or its tokens. No app-level (Tauri) visual run was
  performed for this change.
- Git handoff: no stage, commit, revert, or cleanup; the worktree remains dirty
  with concurrent work.

## Context-menu focus indicator moved onto the row highlight (menu_focus_ring_20260928; 2026-09-28)

- State: complete. Menu rows (root items and submenu triggers) no longer paint a ring
  on top of the row highlight. The ring came from the menu item's own `:focus-visible`
  outline and showed on pointer-opened menus too, because the panel hands focus to its
  first item on open; on a glass pane it read as a selection state. Keyboard users keep
  the ordinary row highlight, which is the same recipe as hover and the menu idiom.
- Verification: `core/ui` contract suite passed 102 files / 835 tests; the context-menu
  suite gained an assertion for `outline: none` on the focused row, the retained
  `--alpha-hover` row highlight, and the absence of a 2px outline on menu items.
  Re-checked in the running Tauri dev window: no bluish pixels around the focused row,
  row highlight still rendered.
- Spec: `lam-design-spec` option-row recipe now states keyboard focus reuses the row
  highlight and must not add a focus ring.
- Git handoff: no stage, commit, revert, or cleanup.

## Mobile blocks the skills and plugin this host cannot run (mobile_skill_gate_20260928; 2026-09-28)

- State: complete. The phone no longer offers skills whose own instructions need a
  desktop host. Every embedded core skill now declares `metadata.target:
  lamtools-desktop` in its frontmatter — the eleven Office skills because their
  validation and rendering step is `py -3.14 -m lamtools_core.cli office …`,
  `create-plugin` and `plugin-manager` because their install-and-verify loop ends at
  `plugin_install`/`plugin_list`, and `observe-events` because it binds an observer to
  an event Arrange. `SkillTools` drops a desktop-targeted skill on a host without a
  shell, so the phone's catalog, the prompt and `load_skill` all agree; the loader
  refuses with the reason ("not available on this device") instead of the 0.1.22
  warning line that listed the skill anyway. The desktop keeps all fourteen: it has the
  shell, the plugin loader and the Arrange scheduler.
- Panel: the 技能 page reads the host through the new `sunday_core_skill_catalog`
  command instead of a hand-written list, which had drifted into advertising all
  fourteen skills on a device that could run none of them.
- Git plugin: removed from both the panel's plugin list and the runtime's bundled
  inventory. Android has no git executable and a project directory is not a repository,
  so the row could only ever report the tools it cannot assemble.
- Fixed in passing, same class of defect: the app-private skill directory the 新建技能
  panel writes was never mounted into a turn, so a skill the panel created could not be
  loaded by the agent. Every turn now mounts `{app_data}/skills`, which is what the
  panel's own text already promised.
- Verification: `core/runtime-rs` 163 tests and `core/mobile/src-tauri` 44 tests pass;
  mobile 48 files / 273 tests pass with `vue-tsc` clean. New tests pin the empty phone
  catalog, the refusal reason, the mounted user-skill root and the git-free inventory.
- Released as Sunday Mobile 0.1.43; record in `core/mobile/artifacts/release-1043/`.

## Plugins and skills carry one platform class (mobile_plugin_taxonomy_20260928; 2026-09-28)

- Decision (user, 2026-09-28): every plugin and skill belongs to one of three
  classes — **桌面 / 移动 / 通用** — declared by the asset itself, and each host
  offers what is universal plus what is its own. Undeclared means universal, so
  third-party and already-installed plugins keep their behaviour.
- Manifest contract: `plugin.json` gains `platforms: "desktop" | "mobile" |
  "universal"`; SKILL.md frontmatter uses the same key and the same three words
  under `metadata`. An invalid value is a manifest error, not a silent default.
  Bundled classification: imagegen / study / websearch universal; git / workflow /
  emotion-ball-pet desktop; mobile has none yet (the class exists and is tested).
  Documented in `docs/plugin-dev-guide.md` and `core/skills/README.md`.
- Desktop host (Python Core): discovery skips a plugin whose class is not this
  host's — its tools, skills, hooks, MCP, modes and widgets are not assembled and
  it is not on the plugin page; `plugin.install` refuses such a plugin with the
  declared class instead of installing something that would vanish; `plugin.list`
  carries `platforms` for the page to group by. Fixed in passing: `plugin.ui.list`
  did not carry a mode's `capabilities`, so on the desktop the Study notes
  declaration never reached the UI that reads it.
- Mobile host (Rust + TS): the plugin page is built from the embedded manifests
  (`sunday_plugin_catalog`) instead of the hand-written list that had drifted three
  times; the class filter drops git / workflow / the desktop pet by reading their
  own declarations. The skill gate now compares the declared class with the host
  rather than the "has a shell" proxy through which the 0.1.43 block was expressed.
- Plugin page (shared UI): grouped 通用 / 桌面端专用 / 移动端专用 with counts; the
  payload's `builtin` field now drives the 内置 badge and the uninstall button
  instead of a hard-coded name list. Verified in the running Tauri window (new
  header text and the 通用 group header render; the rest is pinned by tests).
- Verification: desktop 97 plugin tests + 110 adjacent suites, `core/ui` 102 files /
  837 tests, `core/runtime-rs` 164, mobile Rust 45, mobile 48 files / 274 tests.
  All four hand-written plugin lists are now one manifest + one class declaration.
- Released as Sunday Mobile 0.1.45 and published (APK + in-app update manifest + site label; public verification passed on all four assertions). 0.1.44 was built and verified but never published, so the server's previous version was 0.1.43 — the superseded build is kept in `core/mobile/artifacts/release-1044-unpublished/`, the published record in `core/mobile/artifacts/release-1045/`.
  Noted divergence, left as it is: desktop defaults websearch to disabled
  (`defaultEnabled: false`) while the phone enables it — the field is not carried
  into the mobile catalogue yet.
