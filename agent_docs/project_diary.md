# Project Diary

This is a compact reference of stable project decisions and lessons. It does
not record session chronology, releases, commits, routine maintenance, or raw
logs.

## Decisions and Lessons

- Keep current implementation and planning centered on `core/`; treat
  `archive/members/` as historical reference rather than a development target.
- Keep runtime persistence in SQLite and user-facing configuration in the
  unified `.lam/core/config/` JSONC tree. Default seeding must be idempotent so
  upgrades cannot overwrite user edits.
- Treat Tauri as the authoritative Core UI observation surface. Its Vite
  frontend and dynamically ported local backend are separate from the legacy
  repository startup scripts; restarting the wrong process can break the
  desktop dev URL.
- The website showcase is an integration consumer of `core/ui`, not a second
  hand-built UI. Preserve its Vue singleton alias and the shared component/data
  contracts when changing either surface.
- The product UI boundary is `LamToolsApp → Workbench → LamToolsTransport`.
  Desktop and mobile must keep the same Workbench/application; platform code
  belongs in runtime/native/connection adapters.
- Remote traffic is an authenticated Noise tunnel. The desktop Gateway keeps
  Core loopback-only, and the Relay forwards opaque encrypted tunnel payloads
  without interpreting Core business messages.
- Transport reconnects replace only the physical tunnel. The shared Workbench,
  conversation projection, and composer state remain alive across LAN/Relay
  route changes.
- Mobile account, workspace, connection, and sync transitions must be fenced by
  monotonic generations; user-triggered account/workspace operations are
  serialized so stale async results cannot repopulate credentials, routes, or
  repository state after logout, replacement, resume, or unmount. Noise
  handshake waits are bounded and cancellation-safe, and non-native builds use
  memory-only credential storage unless persistence is explicitly requested.
- Mobile standalone capability is developed before any remote communication or
  protocol refactor. The first standalone scope excludes filesystem, command,
  terminal, MCP, and other host-privileged operations; existing paired
  desktop/LAN/Relay behavior remains compatible until a separately approved
  protocol deployment.
- The verified mobile foundation is local-first: the default entry is an
  independent local mode with a login-free panel; local projects and sessions
  use SQLite, with direct OpenAI-compatible and Anthropic provider access.
  Sync begins at device → project → remote control/import, browsing cache is
  independent, offline mode disables remote control, and import pagination
  must fetch the complete session history. Mobile hides session-title and
  window-switch controls; this foundation remains separate from any later
  communication/protocol refactor. Before replacing an App Server transport,
  disconnect must clear the old client's reconnect timers so it cannot close a
  newer remote-control connection. Final validation passed 16 mobile files / 77
  tests, typecheck, Capacitor sync, and Android `assembleDebug`; ADB overlay
  installation on vivo V2536A / Android 16 verified the login-free entry,
  surface-matched dynamic safe area, compact sidebar, long-press context
  menu, and import. Offline-device remote control was not claimed.
- For Android releases, treat `core/mobile/src-tauri/gen/android` as the active
  package and `core/mobile/src-tauri/icons/android` as the canonical launcher
  resources. Sync them before Tauri builds and inspect the signed APK's adaptive
  background and launcher pixels; edits to the archived Capacitor Android
  resources do not change the shipped Tauri icon.
- Keep mobile navigation controls reachable in exactly one place: the top-right
  command dock when visible, and the left sidebar footer when the host hides
  that dock. On narrow-to-wide viewport changes, restore the pinned sidebar;
  an open drawer needs its full width independently of the main surface's peek
  inset.
- A provider console with no HTTP request does not prove the Android request
  stayed inside the app. TLS certificate verification can fail before HTTP
  headers. Classify the safe cause without echoing URLs or keys, and preserve
  certificate validation while investigating Android platform-verifier faults.
- `rustls-platform-verifier` 0.7.0 maps every Android revocation-check
  `CertPathValidatorException` to `Revoked`, including a missing OCSP responder.
  That status alone is not evidence of actual revocation. Android can fall back
  to signed CRLs, whose distribution URLs may use HTTP; inspect the packaged
  network security policy before replacing the verifier or weakening validation.
  For the observed GTS chain, an exact `c.pki.goog` cleartext exception fixes the
  platform check while the default policy remains closed. Preserve the debug
  resource overlay explicitly, and validate both a valid and a revoked CRL
  fixture; neither a desktop HTTPS success nor an Android harness proves the
  complete phone application path.
- Keep credential input separate from HTTP authentication syntax: mobile may
  receive a copied `Authorization: Bearer ...` header, while Rust supplies the
  scheme itself. Normalize that wrapper on both writes and legacy reads, reject
  masked placeholders, and preserve the existing key when a masked editor value
  is submitted. A provider 401 confirms HTTP was reached but does not establish
  whether the device's unknown credential is expired, mistyped, or malformed.
- Treat Office/runtime capability discovery as reusable runtime state rather
  than letting each Agent task spend many model rounds searching program paths.
  Model latency dominates these workflows, so eliminating discovery rounds is
  more valuable than shaving milliseconds from individual tools.
- Do not pipe validation/build commands into filters unless failure status is
  preserved. A successful pipeline exit can hide a failing Python process and
  make tool-failure metrics materially undercount real process errors.
- Keep structural, textual, and visual verification claims distinct. Geometry
  and text extraction cannot prove pixel-level layout quality; footer/page-number
  collisions are a concrete case that passed structural checks but failed human
  visual review.
- Treat provider health as layered: a successful models endpoint proves only
  DNS/authentication/model discovery, not usable completion or streaming. Stop
  must cancel provider I/O before any persistence round-trip, while retaining
  the active-run claim until the cancelled terminal event is durable.
- Parse SSE `data:` fields with or without the optional separator space. Do not
  attribute a provider incident to this compatibility edge unless raw response
  evidence shows that form was actually used.
- Shared modal/backdrop dismissal must treat an outside action as a complete
  primary pointer click: the same pointer must start and end outside the card.
  This prevents dragging from card content onto the backdrop from dismissing
  overlays and keeps nested/teleported overlays isolated.
- Keep live thinking/tool cards compact by default: titles are single-line and
  icon-led; reasoning keeps a two-second semantic-tail snapshot, while tools use
  stable action-and-target labels (including the loaded skill name). Clicking a
  title reveals three lines of body content and clicking that content expands
  it to a seven-line viewport; tool chrome is never part of the line limit.
  Adjacent reasoning and ordinary tools share one fold group. Manual detail
  expansion auto-collapses five seconds after pointer leave, with re-entry
  cancelling the timer. Running state is motion-based (shimmer plus a restrained
  icon breath) and completed state is static.
- Thread auto-follow must target the browser's real maximum scroll offset
  (`scrollHeight - clientHeight`) and only perform a frame correction after
  actual content growth. Earlier history prefetches at two viewports (minimum
  640px) in 50-message batches without showing the history skeleton, and pins
  the first visible message by its DOM coordinate; no manual load button is used.
- Conversation history pages must use one seq-ordered timeline across top-level
  user items and Core runtime items. A page that starts inside an assistant turn
  must retain the causally preceding user inputs, and the UI message window must
  widen an assistant boundary to its preceding user message; otherwise large
  single-turn sessions can make a persisted user message permanently unreachable.
- Message-local files use one transparent attachment-deck interaction: generated
  `image` and `file_change` artifacts expand from the assistant side left-to-right,
  while persisted user uploads expand right-to-left below the user message. The
  deck measures its own width for compact stacked pagination, keeps only one
  hovered/focused/pinned preview expanded, and uses transform-based GSAP Flip
  motion with reduced-motion fallback. Read-only artifacts are not presented as
  turn output.
- Treat Artifact identity as one durable product fact, not a projection-only
  convenience. The current event projection can derive `artifact-{sha1}` ids for
  every tool payload while the project registry separately assigns UUID manifests;
  most file changes therefore appear in conversation history but not in the
  project Artifact panel. Any Artifact redesign must remove this dual identity
  before adding more presentation layers.
- Office GUI retest evidence confirms that a 98% weighted cache-hit rate does
  not imply an efficient run: the 2026-09-11 Microsoft task still used 118
  LLM steps, 123 usage rounds, 15.54M cumulative input tokens, and 20m41s.
  Track uncached input, wall time, steps, logical tool calls, and failure rate
  together rather than reporting cache hit rate alone.
- Structural Office validation must not be reported as visual acceptance. The
  2026-09-11 deck passed shape/text/number checks but human review still found
  visible collisions on p02, p03, p04, p06, p07, and p09. A visual-channel
  capability check is required before claiming a pixel-level review.
- Distinguish logical tool executions from runtime state events. One GUI run
  had 140 logical tool items but 644 `tool_call` event rows; counting rows as
  executions inflates process and log metrics, while ignoring them hides UI
  event pressure.
- Keep `web_search` available in the read-only `consider` tool set. The
  configured default search provider may fall back through other built-in
  providers on network or anti-bot failure, while an explicitly requested
  provider remains strict; use `ddg` as the canonical DuckDuckGo identifier
  and retain `duckduckgo` only as a compatibility alias.
- Do not treat Baidu's anonymous `/s` endpoints as a reliable product API:
  desktop HTML, mobile HTML, and `tn=json` can all be redirected to the same
  `wappass` challenge even after normal cookie warmup and direct networking.
  The supported replacement is Baidu AI Search's authenticated
  `POST /v2/ai_search/web_search`; adopting it requires an explicit API-key
  configuration decision rather than captcha workarounds.
- Keep regional search networking explicit and portable: `websearch` accepts
  an optional port-only `proxy_port` setting for DuckDuckGo and derives the
  loopback HTTP/mixed proxy URL as `http://127.0.0.1:<port>`. An empty or
  invalid port means direct access; do not hard-code a developer's local
  proxy into product code or bundled defaults.
- Process-card polish uses one 16px icon column with an 8px title gap and a
  24px expanded-content inset. Prose is capped at 72ch while code, tables, and
  tool output retain full width; numeric metadata uses tabular figures. Turn
  boundaries use 24px rhythm, same-turn handoffs stay compact, and interactive
  states use shared alpha/motion tokens with reduced-motion fallbacks.
- Sunday is the canonical product name. `AI software` is a deliberately weak
  secondary label/tagline; no translated product name is displayed. Keep this
  naming rule consistent across the title bar, document/native
  titles, icons, and installer copy.
- Sunday branding is implemented as a shared visual system: dark/light Sunday
  themes, repository-owned SVG/ICO assets, and validated project
  `icon_key`/`color_key` metadata. The repository-owned Inno Setup chain owns
  Windows installer presentation, while `lamcore.exe`,
  `lamcore-backend/LamCore.exe`, `com.lamtools.lamcore`, protocols, storage,
  and configuration identifiers remain compatibility boundaries.
- Project visual/name edits are immediate-save interactions: commit on the
  relevant change/blur/enter or icon/color selection, while AGENTS content
  remains an explicit save. The desktop bootstrap must resolve saved/system
  theme colors before the first stylesheet paint; this prevents a dark-theme
  light flash during the first ~80ms. The Tauri startup surface uses real native
  transparency, not a theme-colored full-window veil: the main window and
  pre-shell WebView layers stay alpha-zero, while the native shadow remains
  enabled to preserve Windows rounded corners and its acceptable 1px frame.
  Only the centered Sunday mark is painted, and the normal workspace shell
  takes over once Vue is ready. The startup optical layer uses a low-alpha
  neutral tint over delayed native Acrylic, restrained 8px WebView blur,
  static localized environmental color transmission and masked irregular edge
  reflections; avoid uniform white borders, high-opacity fog, over-blur, and
  full-window looping effects. Once Vue is ready, the saved theme backdrop
  expands once from the centered Sunday mark to the farthest window corner,
  then crossfades into the staged shell entrance; this completion reveal must
  not be applied during native first paint. The window remains interactive;
  startup transparency must never imply click-through behavior, and reduced
  motion replaces the radial expansion with a direct crossfade.
- The desktop sidebar uses a compact 232px width while the mobile drawer keeps
  an independent responsive width; test these as separate layout contracts.
- Keep `WorkspaceShell` as the single source of truth for left/right sidebar
  pin state. Title-bar controls only request toggles and mirror the shell's
  emitted state, including responsive auto-unpinning; hide those title-bar
  controls at the shared `640px` narrow breakpoint while preserving device and
  native window controls.
- Text-like input boxes and textareas derive their background, border, text,
  caret, and placeholder colors from the composer area rather than the control
  area. Transparent title editors are the explicit exception and keep the text
  color of their containing area. Keep the shared text-input selector at zero
  specificity (for example through `:where(...)`) so it cannot override those
  local title rules. Selects, buttons, badges, and native non-text inputs remain
  control-area surfaces.
- `CoreSendStopButton` is the composer action-button exception to the generic
  control-button recipe: both send and stop use composer text for the outer
  surface and composer background for the paper-plane/stop glyph and trail.
- The right sidebar is one host-owned module rail: the host owns ordering,
  visibility, collapse state, and per-project persistence, while plugins only
  contribute content inside a module. Plugin content may be declarative blocks
  or a trusted in-process Vue component; it never replaces the host shell.
- Treat sidebar widget metadata as a security boundary. The manifest descriptor
  owns action titles, schemas, dangerous/mutating flags, and trusted loaders;
  snapshots may provide bounded display blocks and runtime action availability
  only. Mutating actions require an idempotency key, dangerous actions require
  confirmation, and component snapshots are fetched only through the
  `plugin.widget.*` facade.
- The right rail and shared context menus use one theme-token-driven optical
  glass primitive: a highly transparent 2% tint, restrained 8px backdrop blur,
  slight saturation/brightness/contrast response, localized inner reflection
  and color dispersion, and irregular edge highlights. Do not add a uniform
  white outline or edge-opacity fade. Mobile preserves the same substrate
  instead of inheriting the generic opaque drawer surface. Runtime
  visualization remains intentionally simple until a later visual decision;
  no Three.js dependency is justified yet.
- Liquid-glass blur belongs on a stable, untransformed outer surface; opacity
  and transform entrance motion belongs on an inner content layer. The shared
  context-menu host applies this rule once for every root menu and submenu so
  right-click callers cannot drift into separate opaque card recipes.
- Right-rail motion is state-driven and brief: 240ms enter / 180ms exit,
  capped module staggering with transform-based reorder, 200ms retained-body
  collapse, and 180ms layout-editor reveal. Motion must be interruptible,
  lifecycle-scoped, reduced-motion safe, and must not animate runtime data for
  decoration. The rail keeps rounded left corners only, square right corners,
  and an exact 2px gap from the main chat surface.
- Optional sidebar providers must expose truthful absence. In particular, Core
  ships a RAG host/search compatibility surface but no RAG provider, so it must
  show unavailable state and no invented document or chunk counts. Widget
  refresh is explicit/deterministic for now; event push is a future contract.
- ComfyUI parity for Sunday Workflow is a behavioral and contract target, not
  a code-copying target: ComfyUI's editable workflow document and executable
  prompt graph are separate representations, and Sunday must independently
  implement the equivalent compile/validate boundary without importing GPL-3.0
  code or its unrestricted custom-Python trust model.
- Workflow/Agent integration must preserve two-way usefulness without shared
  implicit runtime state. Workflow owns document storage, validation, queueing,
  execution, cache, history, cancellation, and events; Agent participates only
  through explicit invocation adapters and an execution context carrying parent
  identity, permissions, working directory, attachments, cancellation, and
  event lineage. This boundary is now implemented: Workflow can run independently,
  Agent/Model/plugin nodes enter through explicit adapters, and a Workflow exposed
  as an Agent tool inherits the complete authority/correlation envelope rather
  than reconstructing partial state.
- Treat `workflow_stack` as an authority-bearing cycle-detection contract. An
  externally supplied stack containing the current workflow must fail before any
  node executes; only runner-created child contexts may identify the current
  workflow as the already-entered stack tail. Preserve attachments, runtime
  snapshot, environment, capabilities, permissions, lineage, cancellation, and
  stack metadata across every Agent/tool boundary, with regression coverage for
  the real `KernelSubAgentRunner` path.
- Scope ordinary conversation-header layout with an explicit host marker rather
  than a shared `.thread-header` override: Workflow reuses that class, and Vue
  build output may place SFC rules before imported shared CSS. Keep the marker
  rule adjacent to the shared base rule and verify the built cascade/specificity
  whenever moving the titlebar-to-divider geometry.
- Workflow persistence has one canonical editable truth: atomic
  `workflow.json` in Sunday `lamtools.workflow` V2. Legacy `config.json`, node
  files, and Mermaid-style `map` remain compatibility/recovery artifacts only;
  when V2 exists they must never override or silently replace it. Stable
  node/port/link identities are semantic, while display names and canvas
  placement remain freely editable.
- Keep three workflow representations explicit: `WorkflowDocumentV2` for
  lossless editing, `ExecutionPromptV1` for deterministic canvas-free runtime
  input, and paged/focused `SemanticGraphV1` for compact Agent understanding.
  ComfyUI v0.4/v1 support is an import/export adapter around this boundary;
  unknown ComfyUI editor metadata belongs under `canvas.comfyui`, never in
  executable node params, and unknown executable types remain truthful
  `schema_only` nodes until an executor is installed.
- Workflow node identity is an open registry key, not a closed frontend/runtime
  enum. `workflow.object_info` is the canonical catalog and editor-schema
  source; shipped canonical nodes are Model, Agent, Command, Python, Constant,
  Input, Output, Template, Condition, Merge, Join, Wait Event, Approval, and
  Subgraph. Legacy
  AI/Script/Content and duplicate Transform/Branch aliases remain executable
  and loadable but are hidden from new-node choices. Model and Agent use
  independent invocation paths, node type is immutable after creation, and a
  plugin type must have both a trusted schema and an installed executor before
  it can run. User-visible Chinese names, descriptions, categories, and Lucide
  icons belong only to the presentation layer; canonical English `type_id`,
  schema keys, stored preferences, and execution contracts stay unchanged. Do
  not advertise Tool/MCP or HTTP nodes until Core provides a real host service
  and permission boundary for them.
- n8n is a concept/reference source only, not a code or UI dependency: its
  Sustainable Use License requires legal review before any code reuse. The
  transferable production concepts are versioned node manifests/migrations,
  item envelopes with binary references and lineage, sandboxed expressions,
  credential references, activation/triggers, and durable wait/resume/error
  execution records. Reuse Core Arrange for schedule/event activation instead
  of creating a second scheduler, and do not ship HTTP, Tool, or MCP workflow
  nodes before credential and permission boundaries exist.
- Workflow canvas interaction follows the transferable ComfyUI convention:
  middle-button drag pans, right-click opens context menus, stable port IDs own
  connections, and nodes expose inputs on the left and outputs on the right.
  Workflow mode owns the full central surface; title, controls, and the compact
  one-line composer are overlays. The composer rests as a short fully rounded
  textarea/send affordance and expands only while hovered, focused, populated,
  or running.
- Vue Flow 1.41 的无修饰框选契约是 `selectionKeyCode=true`，不是 React Flow
  风格的 `selectionOnDrag`；配合 `panOnDrag=[1]` 后，左键空白拖拽框选、中键
  平移。节点和画布元素仅在已选中时 `draggable=true`，保持“先选中、再拖动”。
- Workflow 节点的 `parent_id` 是纯画布父级元数据：V2 只存于
  `canvas.node_views[node_id].parent_id`，legacy/store/导入导出/剪贴板须无损
  往返，但执行 prompt、DAG、权限和缓存不得读取它。旧数据可用几何包含兼容，
  显式父级关系优先；不得直接映射 Vue Flow `parentNode`，避免绝对坐标被当作
  相对坐标而跳位。
- 框架/分组双击与右键“全选”只选择内部内容；“删除”只移除容器并解除直接
  父级，“全部删除”移除容器、递归内容及相关连线，并使用 3 秒不可确认倒计时。
  几何识别出的嵌套容器仍须递归纳入其显式后代，避免留下孤儿节点。
- Sunday Workflow 的长期方向是本地优先的 durable workflow platform：画布只是
  WorkflowDocument 的一种编辑器，运行内核使用持久状态机、append-only event
  history 与派生 snapshot；Agent 是显式的非确定性节点/子运行时，不能取代
  orchestrator。先在现有 SQLite、Arrange、Attachment 与本地队列上定义可替换
  接口，不提前引入 PostgreSQL、Kafka/NATS、Redis、Vault 或 Temporal 依赖。
- Durable 语义必须区分 Workflow、不可变的发布 Version、Run、NodeRun 与
  Attempt；已开始的 Run 固定其版本。任意 Python/Command 和外部 HTTP 副作用不
  承诺 Temporal 式代码重放或真正 exactly-once，只通过持久完成记录、幂等键、
  去重与必要的 compensation 达到 effectively-once。第一阶段保持单一 durable
  默认模式；Fast/Express 仅在真实性能证据出现后作为显式策略加入。
- Retry、timeout、error policy、concurrency、capability/resource class、credential
  reference 与 wait/signal 属于 Engine/Node Contract，不允许各节点重复实现。
  大二进制只以 Attachment/Artifact 引用穿过 WorkflowDataPacket；统一 item envelope
  保留 json、binary refs 和 lineage。触发激活必须适配 Core Arrange，禁止另造
  scheduler；HTTP、MCP 和外部连接器继续等待凭据解析和权限宿主边界完成。
- Durable wait/human-task 第一阶段使用 `run=paused`、`node=waiting`：wait descriptor
  与固定 definition/revision 一起持久化，Signal 恢复时不轮询、不占 worker，并以
  不可预测 token、事件类型和幂等记录校验。并发去重覆盖同一进程内的多个
  `WorkflowRunner` 实例；它不代表跨进程强一致，跨进程部署前必须把 claim/lock
  下沉到事务性持久层。
- CredentialRef 只在单次 Node Attempt 的临时副本中解析；resolver 缺失或节点所需
  capability/resource 未被宿主显式授权时必须 fail closed。解析出的 secret 不得进入
  execution metadata、Event History、Snapshot、日志或结果；内置节点继续接收 legacy
  raw value，可信插件 executor 边界使用 WorkflowDataPacket，以维持旧图兼容。
- 手动 `/compact` 不得维护独立压缩策略：它只向共享
  `ContextCompactionController` 传递“跳过触发阈值”，窗口、80%/60% 预算、摘要
  输出、安全余量、重试、模型/推理配置、选段和失败语义全部与自动压缩一致。
  手动成功后只更新摘要与 `summary_seq`，不重写原始历史；失败不得覆盖现有摘要。
- 压缩尾部保留单位按模型 Step 计算：一个 `assistant` 消息及其后连续的 `tool`
  结果组成一个 Step；设置范围为 0–100，默认 0，即所有非稳定 system-prefix 历史
  都进入模型摘要。最近 20 条用户指令不再作为 raw message 尾部保留，而由程序在
  摘要末尾追加 `## Recent user messages`，以 `1.`、`2.` 顺序写入原文。该程序段
  优先于模型摘要细节；token 预算不足时静默删除最旧编号项，最新用户原文仅在其
  自身都无法装入时才导致压缩失败。再次压缩前必须剥离旧程序段，避免递归重复；
  自动压缩与手动 `/compact` 共用此策略。实际保留的最近用户列表必须随摘要写入
  结构化 metadata，再次压缩时与新用户消息按序列重叠合并后滚动到 20 条；不得从
  展示文本猜测当前列表，也不得把 request-local 内部 user 上下文当成用户指令。
  纯媒体 user 使用稳定占位，typed image/tool-result block 的 `content` 不得误作文本。
  用户原文可能包含后缀标题、编号、CRLF、尾随空白或特殊换行符；可见内容仍保持
  标准编号原文，仅在有解析歧义时追加不可见的长度 footer，以便逐字符还原和剥离。
  `retained_steps=0` 时，同一 run 的内存 history 必须保留摘要供后续 Step 使用，写入
  durable history 前再过滤摘要行；手动压缩不重写原始历史，因此须持久化已压缩行
  序号和有效高水位，不能把合法的空 retained tail 当作边界漂移后回退到完整历史。
  连续手动压缩必须合并而非覆盖已压缩行序号；任何被 exact-budget fitter 静默丢弃的
  Step 也属于已移除上下文，不得在同一 run、durable history 或下一 run 中重新出现。
- Workflow 可观测性采用“安全运行投影”而不是暴露模型内部推理：画布与运行面板可展示
  节点状态、时间、尝试、缓存、输入输出、错误、日志以及宿主实际提供的工具调用摘要，
  但必须过滤 reasoning/chain-of-thought 类字段，并在 RPC 边界移除 credential、resume
  token 等秘密。人工审批是 durable wait 的显式任务入口；完成任务必须返回续跑后的
  Run 快照，使 UI 同步剩余节点和最终输出，而不是只回“已提交”。
- 节点编辑器中的 object-info schema 是真实参数表单契约，不是展示类型名的说明卡；
  对已有完整端口不得显示无效的“按 Schema 补齐端口”，无可配置字段的节点也不得用
  `output`/`object` 等单字类型冒充配置。`any`、`object`、`array` 字段使用可编辑文本或
  JSON 输入，并在保存前保持结构化值。
- Bundled plugin 的 `index.ts` 是动态模块入口：替换组件时必须在同一次改动中删除旧导出，
  否则 Vite HMR 的短暂失败会被浏览器缓存为 rejected module，使整个插件模式显示
  `Failed to fetch dynamically imported module`；验证除 production build 外还须直接请求
  dev-server 的入口模块，并在发生失败缓存后完整重启 Tauri dev。
- Artifact 的长期事实边界是“项目级成果”，不是所有工具输出：同一项目路径保持稳定
  Artifact ID，内容变化形成 SHA-256 去重的不可变 Revision；用户输入、处理中间产物与
  可交付成果进入成果库，`command_output`、`file_read`、网页抓取和测试证据只保留为运行
  证据。软移除不删除文件或历史，单 Revision 恢复只影响该成果；Checkpoint 保存当时的
  Artifact Revision 指针，整体回退时恢复这些指针对应内容，并将检查点之后新增的成果从
  当前成果库状态移除。历史 `.lam/artifact` manifest 与 `artifact-{sha1}` 只作为兼容别名，
  不再形成第二套身份。
- 产品级思考强度统一为 `off/light/medium/high/xhigh/max` 六档，并在所有入口把 `xh`
  归一化为 `xhigh`；适配器负责把较多的产品档位折叠到供应商实际支持的较少档位，既有
  `light/high/max` 语义不得改变。DeepSeek 的固定映射为 `off=disabled`、`light=low`、
  `medium/high/xhigh=high`、`max=max`。子代理单次调用可覆盖模型与思考强度，未指定时
  继承父代理；批准后续跑必须沿用已持久化的子代理档位。`Shallow` 仅从所有可见 UI 入口
  隐藏，底层字段、存储、CLI 与旧会话解析继续保留兼容。
- 子代理生命周期由父会话级、进程持有的 SQLite supervisor 管理，`(parent_thread_id,
  name)` 是稳定身份；主 Agent 只能用严格的 `create/close` 五参数契约和严格的
  `type/name/prompt` 消息契约。`consider` 与 `execute` 使用各自工具集合，但都必须移除
  `sub_agent`/`sub_agent_message` 并只保留子代理专属 `message(message)`，从工具边界阻断
  递归委派。创建和发消息立即返回，后台子代理不得阻塞父运行；忙碌期间收到的新 prompt
  必须作为 guidance 在同一运行的下一 `step`、下一次模型采样前注入，而不是等待新的
  turn。mailbox 以调用 ID 幂等，不能按正文永久去重，否则合法的重复消息会被吞掉。
- 可变的子代理 `name/model/summary` 上下文必须在完整持久历史之后以最后一条 `user`
  message 追加，且不得写回历史；不能使用尾部 `system` message，因为 Anthropic/Gemini
  会把 system 内容提升到请求前部，破坏稳定缓存前缀。会话级历史定位保存真实
  `assistant:<turn_id>` 与 `part-<call_id>`，右栏才能从已关闭/历史子代理记录可靠定位并展开
  父消息中的对应过程块。子代理运行事件必须归属当前 `sub_agent_message` 过程块，不能泄漏成
  父主线普通消息或结束父运行；事件 item ID 必须同时包含子会话、run 与 invocation 身份，避免
  跨 run/调用冲突。审批恢复必须恢复子代理身份、专属 toolbox、request-local 尾部上下文与父级
  定位信息，不能按普通父代理续跑。
- 子代理角色分配以全局 `role_assignments` 为基线，项目规则按规范化后的
  `task_type` 同名覆盖、新任务类型追加；项目编辑器只保存项目本地规则，不回写
  全局继承项。持久化字段固定为 `task_type/type/model/reasoning_min/reasoning_max`，
  模型保存稳定 `model_id`，思考范围只使用 `off/light/medium/high/xhigh/max`。有效
  规则以稳定段紧接 Sub-agent 调用纪律进入主 Agent 系统提示词，空配置不输出该段。
- 子代理委派策略固定为 `forbidden/low/medium/high` 四档，内置默认是 `medium`；
  全局 `delegation_strategy` 是基线，项目显式值覆盖，删除项目本地键才表示恢复继承。
  策略段按 guide → strategy → role assignments 的稳定顺序进入 leading system prompt，
  并明确优先于通用委派指南与角色建议。`forbidden` 不能只靠提示词：所有主运行时
  toolbox 装配入口必须同时隐藏并禁用 `sub_agent/sub_agent_message`，直接调用与旧审批恢复
  均要 blocked；显式的用户/运维生命周期 RPC 不属于主 Agent 委派策略边界。
- Sunday 品牌以用户提供的两张 1254×1254 明暗参考图为像素真源，禁止再凭感觉近似重画。
  应用图标、标题栏和启动页必须保留完整银灰外框、内板、材质与抗锯齿像素；无损源 PNG
  进入产物并派生 ICO/ICNS。可动画的独立 mark 才使用实测 1024 矢量几何：眼中心约
  `(367.5,421.7)`、眨眼 `M599.8…726.3`、笑弧 `M318.1…703.4`。主题本身保持纯色，
  工作台底层 backdrop 直接使用参考图边框色，聊天区使用 main/composer；
  暗色为工作台 `#818289`、聊天区 `#1B1D22`，浅色为工作台 `#D2D8E6`、聊天区
  `#FDFBF7`。控件采用反向高对比品牌色：
  浅色控件 `#2E3138` 配 `#FBF7F0` 文字，暗色控件 `#FBF7F0` 配 `#2E3138`
  文字。旧彩色 Sunday 默认值及第一版灰色控件默认值只在完整精确匹配时迁移，任何用户
  自定义主题不得覆盖。原始参考 PNG 保持字节不变；显示与打包图标由居中 1120px 裁切
  经 LANCZOS 放大为 1254px 的 display master，有效图形覆盖约 90%，避免系统图标视觉缩小。
- Office 交付的数据真实性采用渲染前门禁：Agent 在制作任何数据承载表格或图表前先写
  canonical `office-data.json`，源文件完成后再追加稳定对象绑定；数据、标签、单位、顺序、
  派生值或结构任一不一致都必须在后端探测和输出目录创建前 hard stop，不得通过修改生成物
  反向迎合 manifest。纯装饰对象只能显式列入 `non_data_targets`，不能用作全局逃生口。
- Office 视觉验证必须经过真实布局引擎。Windows 自动后端顺序固定为 Microsoft Office COM
  优先、LibreOffice 后备；LibreOffice 命令行发现优先使用 `soffice.com`，因为 `soffice.exe`
  是 GUI launcher，可能不可靠返回版本或退出码。两者都不可用时仍可报告数据/结构结果，但
  visual 只能是 `not_run` 或 `unavailable`。重叠诊断必须给出页码、双方文本、元素 ID、bbox
  与交集；豁免仅允许精确元素对，禁止全局关闭视觉冲突检查。
- Office renderer 的所有权属于 Office Skills bundle，不属于 Core Agent 内核。它按标准
  Skill 发布结构放在 `skills/office-renderer/`：`SKILL.md`、`agents/openai.yaml` 和
  `scripts/office.py`/`scripts/lamtools_office_renderer`。其 invocation policy 为 explicit-only；
  `SkillRegistry` 必须读取该标准字段，使它可显式加载但不进入自动 Skill 提示索引。Core 只
  提供 `office check` / `office validate` / `office render` CLI 适配，并从
  `office-renderer/scripts` 延迟加载。Agent 在任意项目目录使用
  `py -3.14 -m lamtools_core.cli office ...`。源码、wheel 和 PyInstaller frozen 布局使用
  同一相对路径；打包逐文件排除 `__pycache__`、`.pyc` 和 `.pyo`。
- 本轮产出不能只依赖工具显式返回 `artifacts`：命令、Office 应用和 Skill 附属程序可能直接
  写文件。完成态顶层 Agent 消息是补充登记边界；仅解析最终回复显式列出的路径，验证为项目
  根目录内真实普通文件后才登记为 deliverable，并绑定 thread/turn/item。提示词负责要求逐项
  列出真实交付路径，后端负责存在性和目录边界校验，前端不得自行扫描磁盘。文本/代码成果默认
  使用内置纯文本预览，系统默认应用只用于非文本格式；CLI 对应能力为 `artifact preview`。
- 聊天区堆叠成果卡的展开状态只由 pointer hover 驱动；单击和键盘焦点不能锁定尺寸，双击或
  Enter/Space 只负责打开。所有从消息流打开的模态预览必须 Teleport 到 `body`，避免聊天区
  的 transform/滚动内容成为 fixed containing block；遮罩复用 CoreConfirmDialog 的中性主题配方。
- 普通 Office 生产任务直接使用 `office validate` / `office render` 的公开 CLI 和结构化报告。
  环境状态通常无需预检；需要确认时可选运行一次 `office check`，其最小 Word/Excel/
  PowerPoint 转换测试全部通过时固定返回 `Office 应用已就绪 · Test Passed 3/3`，随后进入
  正式产物流程。只有正式入口明确不可用时才使用已发布的内置脚本 fallback。程序化
  `visual=passed` 只表示自动规则通过；整体视觉通过必须逐页查看全部预览，代表页检查只能
  记录为 sampled 并列出实际页码。
- Direct WebSocket 瞬断必须保留 close `code/reason/wasClean` 供诊断，但产品 UI 对可恢复的
  transport 错误采用 2 秒宽限：窗口内重连成功即静默，持续断线才展示带关闭原因的错误；
  模型供应商和业务错误不进入该宽限。`seq=0` 的瞬时流式事件从不进入 sync journal，live
  reader 不得为每个 delta 查询 SQLite，否则突发输出会阻塞 reader、填满 256 项订阅队列并
  触发 `1013 Event stream overflow`。
- 插件模式若自行渲染聊天滚动容器，必须复用 Core 的 `useCoreAutoFollowScroll` 与底部哨兵
  契约；模式切换导致容器重新挂载时要重置跟随状态并强制落到最新位置，用户向上滚动后则
  暂停跟随并提供“回到最新消息”入口。插件标题进入宿主 `.workspace-plugin-header`，不得在
  内容流中另放一套错位标题。
- Study 知识图谱使用一次性、确定性的关系力导向布局，而不是持续物理模拟：首次布局按稳定
  ID、关系强度与名称宽度分散节点，已保存或用户拖动的位置始终优先，避免每次进入时漂移。
  节点保持轻量圆点与文字形态，悬停/聚焦只强化直接关系并压低其余连线。Vue Flow 视口必须
  通过实例的 `setViewport` 与 `moveEnd.flowTransform` 同步和持久化；当前版本不支持
  `v-model:viewport`，不得用本地 ref 冒充实际画布缩放状态。
- 全局选中文本的轻量模型调用必须把精确 `quote` 放在每次请求开头的独立主要目标区，
  `prefix/suffix` 只能作为明确标注的消歧上下文，避免长段附近文本抢占回答目标；
  translate/explain/ask 的输出预算分别为 256/600/1200 tokens。提示词契约升级只失效缓存的
  解释/翻译结果，不得清空用户的标记问答历史；本地词典翻译继续保持无模型调用。选文助手的
  模型回复统一复用 `MarkdownRenderer` 并关闭 Mermaid，用户问题与词典字段保持纯文本；
  紧凑卡片正文行高固定为 1.35。
- Office 全量预览声明必须绑定到最后一次源文件变更后的渲染批次。源文件修订并重新渲染后，
  之前看过的旧预览不能继续支撑 `scope=full`；应重新查看受影响的全部页面，或如实降级为
  sampled。Checklist 状态也不得重复提交或先于该证据完成。
- Sunday 安装包的内置插件边界固定为仅携带 `git`、`imagegen`、`websearch`；
  `emotion-ball-pet` 与 `workflow` 保留源码但不得进入 PyInstaller 后端资源、显式 hidden
  imports 或安装包，且本地打包脚本与 GitHub Release 流程必须使用同一拒绝/必需清单。
- DeepSeek 直连官方预设以官方 API 文档为准：当前模型为 `deepseek-flash` 与
  `deepseek-v4-pro`，上下文均为 1M，最大输出上限均为 393216 tokens；Flash 支持视觉，
  Pro 官方明确不支持视觉，不能仅凭产品命名把两者都标为多模态。
- 需要标准对话的插件模式通过 `PluginModeSurface.useCoreThread` 复用 Core 的
  `ChatThread`、历史分页、消息操作、附件托盘/上传/拖放/粘贴/发送和历史附件渲染；
  不再在插件内重复实现对话面。`useCoreAutoFollowScroll` 自身拥有唯一的底部
  sentinel `IntersectionObserver`，宿主和插件只提供容器与 sentinel ref。Study 使用
  `study:main` 作为全局知识图谱构建会话，每个知识节点对应独立会话；非 ASCII
  节点 ID 以稳定 SHA-256 摘要映射到会话 ID，真实 ID 始终保留在 metadata。
  插件会话常用的冒号不直接进入附件目录名，附件存储层将这类逻辑会话 ID
  稳定哈希为文件系统安全目录，数据库和运行时仍保留原会话 ID。
- Study v2 继续复用同一 Agent Loop、Core 会话/附件/流式/取消与既有工具 ID，不建立第二套
  Agent 基座。Study 数据的授权边界固定为宿主提供的 `user/environment/library` scope；本地
  单用户兼容必须显式落入 legacy/local/default scope，任何模型或业务 payload 都不能自报 scope
  或 capability。知识、考试、标记、笔记、会话绑定、幂等回执和 outbox 均按该 scope 隔离。
- Study 的会话语义固定为 `map`、`notes`、`node` 三类 binding；同 scope/类型/节点只有一个当前
  primary，替换 primary 只保留历史、不删除旧会话。节点首次创建会话只返回一次空草稿预填，
  不自动发送且不覆盖已有草稿。图谱与笔记各有管理会话，课程/分组展开不再等同于打开网图。
- Study 知识层以 SQLite 单事务写源为准，Markdown 仅作为内容/导出表示。结构和学习状态使用独立
  revision；包含与前置分别检环，关联允许环；分页游标绑定 scope、查询与结构 revision。课程移除
  采用可恢复的软分离，保留共享节点、会话、笔记与考试证据。P4 教材/PDF/RAG/向量库和 P5 远期
  功能继续只保留接口，不形成文件/数据库双主或第二个图数据库。
- Study 考试由当前 Agent 一次生成题面、每题分值、参考答案和评分点并持久化；参考答案是上下文压缩
  或长间隔后的恢复依据，不触发另一套隔离出题/判卷模型。普通 `get/list` 不返回参考答案，Agent 仅在
  需要恢复依据时显式调用 `reference`。判卷由当前 Agent 提交逐题得分、部分得分、步骤反馈和掌握建议；
  服务端不比较答案原始字符串，只校验结构、分数范围、节点/题号归属、版本和幂等。`sign` 仍只能完全
  匹配已保存的当前评分建议；受助、未覆盖、uncertain/不可读证据不得升级或判失败，同一签名重试不得
  增加 state revision 或重复 outbox。
- 全局长期学习记忆复用共享 MemoryService/Dreaming，以 scope-keyed 内部身份隔离相同公开 memory ID；
  Study 不写项目 `MEMORY.md`。显式记住、纠正、遗忘和来源抑制是权威状态，遗忘内容不得从缓存、
  派生摘要或候选重放复活；一般教学说明留在 `knowledge.teaching_hint`，不能据一次错误或标记生成
  全局能力标签。Arrange/Dreaming 的持久任务使用 checkpoint、lease fencing 与可取消恢复语义。
- Study 会话绑定只调用 operation catalog 中真实注册的 `study.session`；不得把未注册的兼容别名交给
  通用指数退避 RPC，否则永久错误会被放大为秒级首屏卡顿。已有 binding 不刷新全量会话列表，
  同一 active session 不重复 resume。模式切换保留 connection-scoped App Server 客户端并使用既有
  `switchThread`，不要为 Agent/插件切换主动断线重连。
- Study 首屏只加载会话、概览和置顶所需数据：绑定与概览并行，课程树必须点击后逐层读取，不在挂载
  时展开所有课程。Vue Flow 及图谱控件属于按需 `StudyGraph` chunk，进入聊天不得提前加载。插件导入和
  首次绑定统一复用 `HistoryLoadingIndicator`；首次 ready 后的节点会话切换保留 Core thread DOM，
  继续由宿主同一加载动画接管，避免为 loading 重挂整棵消息树。
- Study 不再提供独立“总览”页面；原入口固定为“管理你的知识”，显式清除节点选择并恢复既有 `map`
  primary binding，因此无论此前位于哪个节点会话都回到默认知识管理主会话，不能创建平行会话体系。
  顶层图谱直接复用 `study.get view=overview` 的课程聚合，每门课程以大圆球展示原始全名，并以外圈
  `passed / total` 环形进度和可访问百分比替代旧列表进度；该聚合进度与节点 mastery 保持独立，深入
  课程后的模块和知识节点仍使用紧凑节点配方。
- Study v3 教学技能沿用 bundled plugin 的 `skills` 根和 `study:study` mode gate：系统提示词只替换
  Study 业务身份，宿主继续追加公共工具协议；模型上下文的技能索引只含 name/description，正文由
  `load_skill` 按任务送入，references 再经受限 `read_file` 按需读取。build-map、teach、answer、
  take-exam 使用现有知识图、考试、文件和 Web 工具 ID，不新增同义工具或 UI。
- `curate-notes` 在 `study.notes` 已有事务存储和 UI/RPC 合同基础上，通过 Study 专属 `notes` Agent tool
  接通；为保持模型请求的工具前缀稳定，工具从首轮起可见，只有技能正文按需加载。Agent 写入被规范为
  AI 未锁定块，不能传 UI 专用的 `user_edit` 覆盖用户锁定块；笔记继续使用同一 `StudyStore`，不另建写源。
- NoteBlock 是内部修订、来源和锁定单位，不是默认阅读界面的视觉卡片。Study 笔记默认把有序块连续合成为
  一篇 Markdown 文档；只有进入编辑态才显示分块编辑器。这样保留块级并发与来源能力，同时避免把完整
  学习笔记呈现成“AI 建议”碎片列表。
- Study 技能静态宿主验证与真实教学行为评测必须分开：宿主检查可证明模式隔离、工具声明、引用和
  fixtures 可读，但不能证明输出质量。无可用生产模型/固定工具快照时，40 个场景一律保留
  `NOT_RUN`，`expected_output` 不能写入 actual output；准确、桥梁、密度、资源选择、自主性和硬失败
  只能在真实轨迹产生后评分。
- `thread.resume` 的 snapshot 与 journal delta 是互补合同：`include_snapshot=true` 不能清空
  `events`，否则会破坏断线续传、分页游标和去重连续性。localhost 生命周期探测必须显式禁用系统
  代理，避免本机后台服务被用户代理配置误路由后产生假超时。共享 UI 动画模块不得在模块顶层访问
  `window`/`matchMedia`；无浏览器环境要在调用时安全降级，确保移动端 Node 测试和 SSR 可导入。
- Setup 安装版启动验收受 Tauri 全局单实例锁约束。开发版正在运行时，新安装版会正常以退出码 0
  结束；验收脚本不得把旧进程当成新版本，也不得为此关闭其他目录或开发环境。此时安装/版本/哈希
  可独立验证，但主程序与打包后端双进程冒烟必须明确记为受阻并在开发实例关闭后重跑。
- Core 的真实玻璃材质统一复用 `.optical-glass`：右侧 rail、上下文菜单、Study 选区卡、Workflow
  catalog/runtime dock、回到最新按钮、移动顶栏和 Goal 区只能通过共享 token/伪元素配方获得透射、
  高光、边缘、折射与阴影，不再维护局部 `backdrop-filter` 配方；启动 Acrylic 在 Vue 挂载前以同参数
  手工镜像。模态 dimmer、普通不透明面板、左侧 drawer 和 Workflow node card 不是玻璃表面，不得
  为了视觉统一套用玻璃。共享配方必须同时覆盖 WebKit、无滤镜 fallback 和 reduced-motion 边界。
- 远程 PDF 与本地 PDF 必须复用 `document_normalize` 的同一条受限解析路径；`web_fetch` 不得对
  `application/pdf` 或 `%PDF-` 内容访问 `response.text`。PDF 提取和附件文件读取要移出事件循环，
  并保留文件/页数/文本预算、加密拒绝、扫描页警告和不可信内容边界。模型仅收到可提取文本；
  当前内容块合同不支持的 PDF 不得伪装为多模态附件，也不得因没有图片块而静默丢弃附件索引。
- 图片搜索不得用本地关键词交集替模型做语义裁决；准确性优先由精确查询、可用 provider 和可核验
  来源保证，结果标题、最终来源页与图片 URL 完整交给模型判断。图片分支必须尊重显式/默认 provider，
  不得静默强制切换 Bing。DuckDuckGo 是缺省搜索内核；其非公开图片 JSON 接口不可用时，先用准确
  网页结果发现来源页，再提取页面声明的 HTTPS 图片候选，百度/Bing 仅按统一 fallback 合同降级。
- 任何从主 Agent 转入隔离、排队或延期执行的模型调用，都必须在工具边界由宿主从当前 runtime
  snapshot 写入私有 `_runtime_model_id`，并在持久化前归一为明确的 `model_id`；显式授权的模型覆盖
  优先，随后才是当前回合模型和静态宿主默认。审批恢复、Arrange 与 Workflow queue 都遵循该合同，
  不能因跨 operation/plugin 边界静默切换模型。Study 出题/判卷现已回归主 Agent Loop，不适用隔离
  模型路由。未知模型、缺失路由/provider、
  非绝对 HTTP(S) provider URL 属于确定性配置错误：立即失败、不得指数重试，也不得偷偷回退到另一
  默认模型。
- Core 对话的用户指令导航以 `thread.outline` 作为轻量只读索引：仅投影完整 snapshot 中可定位的
  顶层 `userMessage`，每项保留 message/turn/seq、最多 240 字符的指令和对应回复摘要，不为 queue、
  steer 或 pending placeholder 合成不可定位锚点。前端用单个 Canvas 按全历史索引等距绘制刻度，
  当前项由已挂载用户消息靠近视口 38% 激活线的位置决定，点击继续复用既有 `locateMessage` 与历史
  分页；预览卡统一使用 `.optical-glass`，窄屏（≤640px）隐藏，且不新增滚动 Observer。
- Study 的 Obsidian 式笔记继续以 SQLite NoteBlock 为唯一写源：阅读/预览把有序块投影为连续 Markdown，
  编辑时只原位更新既有可编辑块，不合并、删除或另存 `.md` 双主。`[[target]]`/`[[target|label]]` 在
  当前 scope 内按“笔记优先、知识节点其次”动态解析，未解析链接允许保留；反向链接同样由当前 Markdown
  读时计算，首版不建立易漂移的 link 表。文档级保存通过 `study.notes update_blocks` 单事务校验现有
  revision/锁定状态并原子批写，重复 block ID 必须在写入前拒绝；客户端不得降级为逐块写入而产生半保存。
- PyInstaller 中可导入的插件 Python 模块与插件数据资源不在同一路径：Study 业务提示词必须先读源码旁
  路径，再通过 `bundled_plugins_dir()` 解析 frozen `resources/plugins/bundled/study`。打包验收不能只测
  `/api/health` 或 WebSocket initialize，必须真实调用 `study.session`，否则动态 operation 导入失败会被
  健康检查漏掉并在 UI 中表现为 `Unsupported method: study.session`。
- Study 笔记写入者身份由宿主调用边界提供，不能来自 `study.notes` payload：Agent 创建/追加只能得到
  `author=ai, locked=false`，更新也只能触及现有 AI 未锁定块；用户 RPC 保存会把被编辑块归属为用户并
  锁定。Agent tool schema 不暴露 `user_edit` 等提权字段，后续新增调用路径也必须显式选择可信 writer。
- Study 笔记阅读投影不得对 NoteBlock 内容做 `trim` 或其他 Markdown 归一化；块间只加安全段落边界，
  保留缩进代码和行尾硬换行。保存成功后以详情接口重新读取派生 links/backlinks/node labels，陈旧详情
  响应不得覆盖已提交内容；本地草稿按 note/block 保留，内部导航必须先提示且不得丢弃草稿。
- Study wikilink 解析继续兼容 `[[target]]`，并以 `[[note:<id>]]` / `[[node:<id>]]` 处理重名消歧；
  fenced code 和 inline code 内的字面量不形成链接。未解析链接在 UI 明确标识为不可导航，节点反链同时
  返回来源关联与正文 wikilink 关联，所有笔记变更广播 `study/changed`，纯读取不广播。

## Study 三层笔记架构（2026-09-20）

- 此决策取代本文件中早期“NoteBlock/SQLite 正文单一写源”的 Study 笔记方案。新合同固定为
  Raw → Resource → Note：Raw 是宿主从 Study 会话、标记、考试和节点生成的不可变真实快照，
  Agent 只读；Resource 是 Agent 基于真实 Raw 形成的可追溯、CAS 更新且历史版本可读的素材；
  Note 才是用户阅读和编辑的最终知识库，每篇必须引用至少一个 Resource。
- Note 的正文真源是 scope 隔离 vault 中的真实 UTF-8 `.md` 文件；SQLite 只维护索引、Resource、
  关系、锁和版本。宿主管理 frontmatter 与文末轻量来源链接/机器哨兵，API 只读写正文，不能让
  用户或 Agent 覆盖来源尾注。旧 AI block 迁移为 Resource，旧用户 block 同时保留 Raw 依据、
  Note 正文与锁区；旧块表迁移后只读，不再双写。
- Note 写入采用全文 `body_md + resource_ids + expected_revision + expected_content_hash` CAS。
  用户和 Agent 均可编辑，但用户框选锁定仅阻止 Agent；浏览器和后端统一使用 UTF-16 code-unit
  区间。Agent 与锁重叠时整次写入原子失败并返回 reason、lock id、quote 与重合范围；用户编辑后
  尽力重锚，失锚锁进入保守阻断状态。
- Note 工作区左侧固定为真实 Markdown 路径文件树，顶部提供返回/对话，主区为单文档编辑/预览、
  Markdown 原生块模板和论文式来源；Notes 对话复用既有 Study Agent 会话维护文档。总体关系图
  归属 Note 并放在右侧栏，只包含 Note 节点及 wikilink/父子边；Raw、Resource 不进入该图，也
  不另建图谱实体、独立页面或后台整理任务。
- Note 的 `path` 是左侧物理文件目录的唯一结构来源；`parent_id` 只表达语义子文档并产生右栏父子边，
  不能把父 Note 伪装成目录。所有离开或替换当前 Note 的入口（文件树、图、链接、搜索、置顶、返回、
  对话）统一通过同一脏草稿门禁；旧 NoteBlock CRUD 与前端 blocks 投影仅用于一次性迁移读取，不再是
  可调用或可回退的运行时笔记合同。

## Linux 桌面发行合同（2026-09-20）

- 当前桌面发行新增 Linux x64，交付格式固定为 AppImage 与 `.deb`；macOS 暂不提供。Linux 后端必须在
  Linux 原生 Python 上由 PyInstaller 生成无扩展名 `LamCore`，不能复用 Windows `LamCore.exe`；两个
  Linux 包都必须把完整 sidecar 放入 `lamcore-backend/LamCore`。
- Windows 继续使用应用目录旁的绿色/便携数据布局；Linux AppImage/`.deb` 的可变状态必须写入 Tauri
  `app_data_dir()` 对应的 XDG 用户数据目录，hooks 默认遵循 `XDG_CONFIG_HOME`，敏感凭据使用 Linux
  Secret Service 持久后端，不能回退为进程内存存储。
- Linux 原生打包统一由 `scripts/package-linux.sh` 驱动：工具链、缓存与 staging 必须位于 Linux 文件系统
  且拒绝 `/mnt/c`；GTK helper 固定到已修复版本，其他 helper 采用原子重试缓存，打包器重试只清理残缺
  AppDir 并保留 Cargo target 避免重复编译。验收至少覆盖后端 REST/WebSocket/Study smoke、包内 sidecar、AppImage 解包和
  Xvfb + 独立 D-Bus 启动存活。CI/release 不得绕过该脚本直接运行裸 `tauri build`。
- Linux 后端必须进入专属进程组：正常退出先向整组发送 SIGTERM、超时后 SIGKILL；桌面进程异常死亡时
  通过竞态检查后的 `PDEATHSIG=SIGKILL` 保证直接 sidecar 不残留。AppImage 冒烟必须真实捕获包内
  `LamCore` 的 PID 与 starttime，并在 launcher 超时退出后断言其消失，不能只把 timeout 124 当作成功。

## Core 提示词分层决策（2026-09-20）

- 默认身份在 CLI、HTTP、默认 Agent 与基础 Kit 间统一为 `你是 Sunday Agent。`；高频 Shell、文件、搜索、Web、
  MCP、证据复用规则集中维护，外部网页和 MCP 输出统一视为不可信数据而非指令。
- 未编辑的全局 `AGENTS.md` / `memory.md` 播种模板不进入提示词；项目 `AGENTS.md` 与既有
  sub-agent guide/strategy/roles 仍完整保留。Skill 常驻索引只携带名称和有界触发摘要，完整正文继续由
  `load_skill` 按需加载。
- 易变计划与循环修复指令使用带 `internal=true` 的尾部 user 消息，避免 Provider 把新增 system 消息提升
  后破坏稳定前缀缓存；上下文压缩不得把这类内部消息当成真实最新用户输入或新的语义分组。

## 移动端悬浮命令控件（2026-09-20）

- 移动端的模式切换、搜索、设置与账号入口统一归入可拖动的光学玻璃悬浮控件；模式必须完整列出并支持
  直接选择，不能再依赖“切换到下一个模式”的循环操作。会话/项目侧栏入口继续独立保留，插件管理仍在
  侧栏，桌面端侧栏默认行为不变。
- 悬浮位置使用 GSAP Draggable、限制在视口内并本地持久化；拖动后必须抑制同一手势产生的点击。展开
  卡片依据实际宽高夹取到 12px 视口边距内，不能只按左右二选一，否则控件位于屏幕中部或窄屏时会溢出。
  模式列表使用 `listbox` / `option` / `aria-selected`，并遵循 reduced-motion。

## 移动端 Tunnel v1 协议边界（2026-09-20）

- Tunnel v1 的外部 JSON-line 线格式保持不变；Noise XX 继续负责认证和加密，LAN/Relay 仅选择物理路径，
  Relay 不解释明文业务消息。移动端协议编解码、验证、重放保护和分片重组集中在独立协议模块，传输层只
  负责会话、多路复用和业务消息映射。
- 帧、消息、分片和标识符限制统一按 UTF-8 字节解释；分片只能落在合法 UTF-8 边界。续片除 message id、
  index、final 和递增 sequence 外，version、type、stream id、request id 必须与首片一致；sequence 的跨语言
  上限固定为 JavaScript safe integer。未知业务通道仍按既有契约拒绝，不借重构扩展协议。
- TypeScript 与 Rust 必须共同消费 `core/protocol/tunnel-v1-fixtures.json` 的 golden fixture，并分别验证精确
  编码和解码；任何后续 Tunnel v1 字段、顺序、限制或空白行语义变更都必须同步更新双端测试，避免协议漂移。

## 多平台发布与官网下载合同（2026-09-21）

- Sunday Desktop `0.3.6` 与 Android `0.1.2` 首次作为同一轮官网交付：Windows 官网入口继续使用
  `/downloads/Sunday-latest-x64-setup.exe`，Android 使用 `/downloads/Sunday-mobile-latest.apk`；官网静态站点
  按版本发布目录部署并由 `/var/www/lamtools/site` 原子切换，上一版本目录和被替换的 Windows latest 文件保留以便回滚。
- Android 正式包必须由 `scripts/package-mobile.ps1` 生成并验证 release 签名、单 signer、`Sunday` 应用标签、
  versionName/versionCode 以及非 debuggable、非 testOnly；不能把开发 APK 或仅能安装但未核验签名身份的包挂到官网。
- Tauri 的 `bundle.icon` 是 Linux `generate_context!` 的编译输入，即使仓库全局忽略 `*.png` 也必须精确放行并跟踪
  配置引用的图标。Linux 打包脚本须在 checkout 与 staging 两处按配置动态校验所有图标，避免本地有文件而 CI checkout
  缺文件的隐性发布失败。

## 模型目录与供应商配置合同（2026-09-21）

- 模型配置的内部记录 ID 与上游 API `model_id` 必须分离：安全 `id` 用于 JSONC 文件名、默认模型、UI 选择和模型组关系，
  上游 `model_id` 原样用于请求并允许 `/`、`:` 等官方字符；旧 JSONC 缺 `id` 时以安全文件 stem 兼容读取。
- 用户模型组是 `.lam/core/config/model_groups.jsonc` 中的独立全局配置，采用稳定 group id、唯一名称、有序多对多 membership
  与 revision 乐观并发控制；模型可属于多个组，“未分组”只在 UI 投影中计算。删除组只删除关系，删除模型或供应商必须清理关系。
- 连接信息继续只由可见 Provider JSONC 保存；模型不复制 `base_url/api_key/api_type`。按组新建模型必须填写 API 基础 URL，
  选择现有供应商时只能匹配其 URL，选择新供应商时组合创建 provider、model 与 membership；版本冲突或写入失败不得残留新文件。
- 请求适配优先级固定为显式 model profile > 显式 provider profile > model matcher > provider/base matcher > protocol default；
  inline override 先合并 provider 再合并 model。Command Code/OpenCode 等混合网关的 DeepSeek、Qwen、GLM 预设必须写入模型级官方适配器。
- 主界面模型菜单与“设置 → 模型与供应商”共用“按组 / 按供应商”分类偏好，持久化在 `settings.jsonc` 的
  `core.modelCatalog.classification`；免费供应商预设创建后将返回的内部模型 ID 合并到用户 `Free` 组。

## Android Tauri 2 与共享 Rust Agent 边界（2026-09-22）

- Android 本地模式的模型执行必须经 `StandaloneTransport` → Tauri command → `core/runtime-rs`；移动端
  TypeScript 不得重新引入 `fetch`/`CapacitorHttp` 的模型请求、第二套系统提示词或前端工具循环。Vue UI
  和 App Server 形状继续跨桌面/移动端共享，平台差异只留在宿主、持久化与系统能力适配层。
- 当前 Rust Core 是 P1 骨架，只覆盖 Sunday 身份、模型请求、项目文件工具、工具结果回传循环与实际模型 ID。
  Hooks、MCP、子代理、上下文压缩、记忆以及完整 Study/Workflow 后端迁移仍是后续阶段；Android 正式能力
  不得因为能生成 APK 就被描述为已经与 Python Core 完全等价。
- Android 正式包除既有签名、版本和 release flags 外，必须包含且只包含 `arm64-v8a` 与 `armeabi-v7a`，
  通过 `zipalign -P 16`，并保证 arm64 应用库所有 ELF `LOAD` 段为 `0x4000` 对齐。以上检查固化在
  `scripts/package-mobile.ps1`，不能依赖发布前人工记忆。
- 从 Capacitor APK 切换到 Tauri APK 前必须在真实设备覆盖安装，验证旧 SQLite、加密密钥与项目/会话迁移；
  同签名和更高 versionCode 只证明系统允许升级，不能替代数据迁移验证。未完成真机验收时保留官网旧包。
- Tauri Android 的 CSP 必须显式允许依赖初始化所需的 WebAssembly：当前 `noise-handshake` → `xsalsa20`
  会在 Vue 挂载前构造 `WebAssembly.Module`，因此使用窄权限 `script-src 'self' 'wasm-unsafe-eval'`；不得为此
  放开更宽泛的 `'unsafe-eval'`。移动入口必须保留独立的启动错误兜底，模块导入或挂载失败时显示诊断信息，
  不能再次留下 0×0 的空 `#app` 黑屏。
- 正式 Android 构建前必须清理生成目录中不属于发布合同的 `x86`/`x86_64` JNI 库，避免模拟器调试产物
  混入只允许 `arm64-v8a` 与 `armeabi-v7a` 的正式包。

## 共享 Rust Agent 的协议、状态与审批合同（2026-09-22）

- Rust 模型后端必须按协议生成原生请求，不能仅替换 URL：Chat Completions 使用 `messages`，OpenAI
  Responses 使用 `input`/扁平 function tools/`max_output_tokens`，Gemini 使用
  `contents`/`systemInstruction`/`generationConfig`，Anthropic 使用 content blocks。官方思考字段继续由
  model profile 优先于 provider profile 的适配规则产生。
- 供应商原生续传状态只能在相同协议且相同上游模型内回放：Responses 保留 reasoning/function-call output
  items，Gemini 保留 thought signature 与 functionCall content，Anthropic 保留 thinking/redacted-thinking blocks，
  Chat Completions 保留 reasoning message fields；切换模型不得携带这些不透明状态。
- Tauri Android 的项目、会话、模型/供应商设置、插件/技能开关均以 Rust SQLite 为持久化边界；原生读写失败
  必须向上暴露，不能静默落入 WebView localStorage/IndexedDB 或进程内存。旧 WebView 设置只允许在新库为空时
  一次性导入。
- UI 文件浏览与 Agent 项目文件工具必须指向同一个 `app_data_dir()/projects/<project-id>` 根目录；旧移动端
  SQLite 中的项目文件在首次列举/读取时迁入该目录。任何新实现不得恢复“UI 看一份、Agent 写另一份”的双存储。
- `ask_user` 工具通过可序列化 Rust continuation 暂停，审批卡和 continuation 一同进入会话快照；批准、拒绝或
  指导后从同一模型消息链继续，不能重新请求并重放审批前的模型调用。`approve_for_session` 的工具授权写回
  会话元数据，`hard_block` 永不受权限预设解除。

## 共享 Rust Hooks 与 MCP 合同（2026-09-22）

- Hook 定义、稳定哈希、逐条信任、匹配和累积语义属于共享 Rust Core；移动端只持久化配置并转发，不得再以
  `hook.list = []` 伪装功能存在。7 个生命周期事件必须在共享 Agent Loop 内触发，审批续传后不得重放
  `PreToolUse`。必需 Hook 的无效输出、失败、超时或平台不可用一律 fail closed。
- Hook command 必须以 argv 方式交给宿主 runner，模型可控占位符不得经过 shell 展开。Android 当前没有安全的
  本地命令 runner，因此 optional command Hook 记为 `skipped_unavailable`，required command Hook 阻断；Prompt、
  HTTP 和已连接 MCP Hook 可原生执行。
- MCP 的配置解析、工具命名、stdio JSON-RPC、`Content-Length`/JSON Lines framing、工具发现、权限和结果格式化
  统一进入 `core/runtime-rs`。消息体上限为 32 MiB，header 上限为 64 KiB；下划线开头的运行时参数不得发给
  MCP server。Android 从共享配置和项目 `.lamtools/mcp.json` 读取配置，进程不存在时显式报告启动失败。

## 共享 Rust 子代理、压缩与 Dreaming 合同（2026-09-22）

- 子代理生命周期、父子邮箱、独立历史、审批 continuation 和运行状态属于进程级共享 Rust `SubAgentHub`；
  Android 只负责 SQLite `SubAgentStore` 与宿主工具装配。父 Agent 可用 Project/MCP/Sub Agent 工具，子 Agent
  只继承 Project/MCP 与 parent-message 工具，`consider` 继续执行只读过滤，且禁止递归委派。所有已配置模型及
  对应 provider key 在 Tauri 调用边界一次性提供，模型级配置继续优先于供应商配置。
- Rust runtime history（含 provider state、tool call/result 与压缩摘要）是模型续传真源；共享 UI 快照继续作为
  展示真源。Android 每次成功回合把 runtime history 持久化到原生 SQLite 会话元数据，下回合只追加当前 user
  输入，不能再从 UI 文本反向重建并丢失工具/思考续传状态。
- 自动上下文压缩默认在模型 context window 的 80% 触发并压到 60%，模型总结失败时使用确定性有界摘要；
  `core.contextCompaction.retained_steps` 控制保留的完整最近步骤，缺省 0，同时最多 20 条近期用户指令以数据区
  形式保留。压缩模型调用不暴露工具，且统一关闭思考。
- Dreaming 默认关闭；启用后仅在有工具结果或压缩结果、且达到 `min_turns` 时运行。Dreaming 不得改写或删除
  用户现有 `MEMORY.md`，只追加去重后的持久事实；失败不反向把已成功主回合改成失败。节流 checkpoint 和 turn-id
  幂等状态保存在 Rust SQLite，写入后的 MEMORY 在下一回合重新加载。

## Rust 移动端取消与 Workflow 执行边界（2026-09-23）

- 移动端 Stop 的世代号必须在异步准备和初始快照写入之前登记；完成、审批续传和快照保存后的每个异步边界都要核对世代号。同一会话的快照写入按提交顺序串行化，入队时深拷贝快照，避免运行中对象的后续修改污染已持久化版本。
- Rust runtime history 属于产生它的已完成回合。持久化时记录来源 turn id；取消回合的迟到元数据写入不得成为下一回合的模型上下文。缺少可信来源或上一回合已取消时，从可见消息重建并跳过取消的 assistant 内容。
- Study 分页游标的 HMAC 是二进制字节，可能包含用于分隔载荷的 `.`；解析必须按固定签名长度定位分隔符，不能搜索最后一个同名字节。
- Workflow Rust 同步执行器目前只覆盖受限的内置数据节点：`workflow.run` 先以宿主选定的项目作用域读取 V2 文档并静态预检，再执行纯内置图；权限、恢复/部分运行、外部节点与未实现语义均在副作用前明确拒绝。队列、持久化、Human Task、激活和宿主执行器仍需独立移植，不能把这一路径称为完整 Python 契约。

## Core Shell 与会话恢复边界（2026-09-23）

- `core.commandShell` 是桌面 Python 命令工具和 Workflow 命令节点共享的 Shell 偏好；Windows 自动顺序为 WSL、Git Bash、Windows PowerShell，手动所选不可用时按同序降级。WSL 是否可用须用有界执行探测，不能只凭 `wsl.exe` 或已注册发行版判断；向 WSL 传递的命令保持单个 argv 参数，工作目录显式传给 `--cd`，工作流只通过 `WSLENV` 转发显式配置的变量。
- Windows 命令路径校验必须按所选 Shell 的引号语义生成参数，再解析路径；保留原样引号或在引号不完整时退回空白切分，会把实际越界的路径误判成工作区内路径。校验要拦截引号拼接的 `../`，同时允许合法的工作区内引号路径。
- `thread.resume` 先装入当前快照再重放旧 journal 事件。旧轮次终态只更新该轮次，不能覆盖另一正在运行轮次的全局状态；同轮次的终态补偿仍须保留。`final_response` / `has_tool_calls` 标记须穿过运行时事件投影，显式非最终模型文本留在过程区，无标记旧快照保留兼容推断。
- Composer 发送失败只走错误提示通道，不能把同一错误也发成成功色状态提示。发送/停止按钮的外层用 composer 文字色，纸飞机、停止方块及尾迹直接以 composer 背景填充；背景可能是渐变，不能作为 CSS `color` 值。

## 移动端请求前诊断与终态恢复（2026-09-23）

- 模型供应商控制台无请求记录时，不应把长时间的 `running` 归因于模型重试。独立模式在发 HTTP 前还经过扩展/密钥读取、Tauri 调用、原生项目与 Hook/MCP 装配、上下文压缩和预模型 Hook；按 turn id 记录这些阶段及真正的 HTTP 发送边界，才能定位停点。调试回显只包含固定阶段名与时间，不含密钥、提示词或请求体，也不能进入后续模型历史。
- Android WebView 重载会丢失旧 JS Promise，持久 `running` 快照不能直接恢复为仍在执行。新 Transport 应尝试按 turn id 取消遗留原生任务，并把该轮次标为取消；等待审批的 `waiting` 保持原状。后台终态保存失败仍须通知当前 UI，不能让 fire-and-forget Promise 静默拒绝。
- MCP 初始化在正式模型请求之前执行；超时必须覆盖 stdin 写入、flush 和响应读取的完整调用，不能只包住读取。默认无 MCP 时，不能把 MCP 路径当作某次故障的既定原因。
- Android edge-to-edge 下，decor view 初始返回 `top=0` 可能是临时值；Web 层继续短暂重读，原生层以稳定 status-bar inset 和系统栏高度兜底。代码/构建通过不等于真机状态栏视觉验收。
- Android 也是 Tauri 运行时，共用 TitleBar 的 `isTauri` 判断会错误挂载桌面窗口标题栏；移动宿主应显式关闭桌面 TitleBar，仅由 MobileTopBar 占据原生 inset 之后的顶栏位置。移动端诊断回显必须在模型配置读取与首次快照保存前开始；中间阶段只实时通知 UI，不排队写入快照，以免卡住终态持久化。
- Android APK 覆盖安装要求包名与签名一致。调试构建若要覆盖正式包，须用现有正式证书签名并核对证书摘要；若要覆盖旧调试包，则保留原调试证书。交付前分别核验 APK，不能仅凭相同版本号判断可覆盖。
- Windows 上原子替换 `MEMORY.md.tmp` 偶发被系统以 WinError 5/32/33 拒绝；仅对这些已知临时占用错误做短时有界重试。连续失败必须保留原文件并向上抛错，不能吞掉写入失败。
- Workflow 命令节点生成 `WSLENV` 时，显式环境变量按声明顺序在前，绑定的 `INPUT_*` 变量在后；不要通过集合消除顺序并造成测试或跨进程行为漂移。

## 移动端模型连接诊断（2026-09-23）

- `http_send_start` 在构建请求前触发，只证明代码进入 HTTP 尝试；请求显式 `.build()` 成功后才报告 `http_request_built`，失败则报告 `http_request_build_error` 并直接结束。`http_request_built` 也不能证明字节已离开设备；在 `http_headers_received` 前，供应商控制台无记录不能单独区分 DNS、连接、TLS、代理、错误目标地址与尚未出响应头。移动端 Rust `reqwest` 直接连接配置的 HTTPS 供应商地址，此路径不经过本机应用网关或固定本地端口。
- 共享后端原先默认每次请求 360 秒、最多 10 次重试，连接前卡点会表现为长时间无新阶段。连接建立限制 15 秒；等待响应头 30 秒报告固定阶段、120 秒结束该次尝试，响应头前故障最多尝试两次。已收到响应头后的响应体超时及 HTTP 5xx/429 重试仍按原策略执行。阶段事件只含固定名称，不含 URL、密钥或消息内容。
- 真机若超过连接/响应头计时仍看不到新阶段，应检查 Android 后台调度、Rust Tokio 任务进展与 Tauri 事件传递，不能继续把故障直接归因于供应商网络。
- Android 真机已观察到 `http_request_built` 后超过两分钟仍无 30 秒原生等待标记。普通异步网络等待不足以解释这一现象：同一任务若在同步回调或发送 future 的 poll 中不让出线程，任务内的 `tokio::select!` 定时分支也无法运行。发送请求因此先排入独立 Tokio 任务，再上报构建阶段；等待者的 30 秒/120 秒计时独立运行，超时或取消时中止发送任务。调试版另以 WebView 定时器报告 35 秒/125 秒等待，用于区分界面存活与原生阶段停滞。此改动提高有界性，但不能据此宣称已找出该手机的确切根因。
- `reqwest 0.13` 在 Android 上经 `rustls-platform-verifier 0.7` 使用系统证书验证；这条路径必须在首个 HTTPS 握手前由 JNI 初始化，并将对应的 Kotlin AAR 打入 APK。缺少初始化时证书验证会 panic，发送任务以 `JoinError` 失败；真机这次的 `provider send task failed` 与该机制吻合，但修复是否解决用户设备上的调用仍须真机复测。发送任务的 panic 与取消分别报告，避免再次合并为模糊错误；不能通过关闭 TLS 验证绕过此问题。
- Android 诊断 APK 应使用与现有安装包一致的签名以支持覆盖安装，上传到独立云文件名并核对完整下载 SHA-256；不要以未经真机验收的诊断构建覆盖正式 `latest`。上传授权只在传输期间存在，发布后按精确匹配撤销并清理暂存文件。

## Android 项目根目录与运行进度展示（2026-09-23）

- Tauri Android 的项目根位于 `app_data_dir()/projects/<project_id>`，属于应用私有存储；系统“文件”App 不显示可浏览的 Sunday 目录。不要把该绝对路径误说成用户可通过文件管理器访问的共享目录。共享 `ProjectFileTools::list_files` 省略路径、空路径和 `.` 都应列当前项目根，并在结果中回传规范化的相对路径和绝对 `project_root`；读写仍拒绝空路径及越界路径。若需要在系统文件管理器访问项目文件，应另做 Android SAF 导出/授权，不能靠扩大旧式存储权限解决。
- 移动端运行阶段只作为临时 UI 元数据传递；回答/错误正文保留纯结果，不能再拼接长篇执行日志，也不能把进度信息喂回模型历史。阶段数没有可校准的总量，因此进度条采用不显示百分比的动画和当前阶段文字；终态短暂显示后按到期时间隐藏，并清理取消/卸载时的监听与计时器。动效须遵循 LamTools 主题 token 和 reduced-motion 回退。

## Android 流式回复与官网包切换（2026-09-23）

- 移动端 OpenAI Chat 请求此前固定 `stream:false` 且在完整响应后才提交消息；真正的流式回复须在 Rust 按 SSE 帧重组 UTF-8、思考与按索引分片的工具调用，向 WebView 发送合并后的临时增量，最终结果仍由 `TurnResult` 覆盖。新模型轮次和重试必须重置临时内容，取消和失败必须收束已显示的思考状态。
- 流式事件只在父代理的 `runtime_model_start` 至 `runtime_model_done` 之间公开，防止压缩、Dreaming 或子代理内部模型输出混入当前聊天。固定阶段事件本身不含密钥或请求体，正式构建也要发出，否则进度条会失去原生阶段信息。其他供应商协议在对应 SSE 格式实现前不能宣称支持流式。
- 官网 Android 下载使用稳定的 `Sunday-mobile-latest.apk` 路径。切换前先把旧文件保存为可公开下载且校验哈希的独立存档，再上传新版本到暂存名并校验完整 SHA-256，最后原子替换稳定文件；公网完整下载及服务状态也须复核。代码测试和签名检查不等于真机流式或 HTTPS 验收。

## Android 模型连接复测与版本纪律（2026-09-23）

- 真机对已签名 0.1.2 包仍报告响应头前连接失败，说明 Android HTTPS 故障尚未关闭。此类错误须按 DNS、TCP、TLS 证书/握手与代理归类为固定提示；原始 `reqwest` 错误可能含完整 URL 或代理凭据，只能用于内部分类，不进入 UI/日志。源码已初始化 Android 证书验证器也不能替代真机握手证据。
- OpenAI Chat SSE 必须收到 `[DONE]` 才能把累积文本或工具调用当作完成；干净的提前 EOF 仍是截断，必须报错并在重试时清空临时输出。输出上限 `finish_reason=length` 不能静默当作完整回答，续传语义需另行处理。
- 每次交付新的 Android APK 同步递增移动端语义版本与 Tauri `versionCode`，并在签名产物里核对；诊断包先发独立版本链接，待真机验收后再切换官网稳定路径，旧版本继续保留可校验的存档。

## Sunday 预制系统提示词语言（2026-09-23）

- Sunday 自带的主 Agent、Study、子代理策略、辅助模型调用和技能索引指令统一用英文表达原有规则；用户自行编写的全局配置、项目上下文和技能内容按原文注入，不自动翻译。需要中文输出的现有约束仍由英文指令明确表达。Python 与 Rust Study 继续共用同一份系统提示词；交接导出对旧中文和新英文运行时前缀都要兼容。

## Mobile sidebar navigation ownership (2026-09-23)

- Floating-command availability is a viewport/layout decision; opening a temporary drawer or account overlay must not restore duplicate left-sidebar commands. Narrow layouts keep commands in the floating dock; wide layouts restore the full sidebar footer.
- Study's note sidebar depends on both the visible page and the active session binding. Leaving Notes must restore a learning binding, not merely change the page to chat; route the exit through the existing dirty-document navigation guard so cancelled navigation preserves the draft.
- Note navigation discards only the captured departing draft after the destination action succeeds; rejected session switches retain the note view, binding, and draft. A later concurrent edit must also survive the original navigation attempt.

## Mobile/Desktop parity audit lessons (2026-09-23)

- A catalog entry is not execution evidence: compare the visible UI action, actual transport route, assembled model tools/context, durable side effects and restart behavior. Standalone project management uses an injected project client, so missing project RPC methods alone do not prove missing UI capability; paired remote forwarding also does not prove standalone parity.
- Shared Study skills must be embedded from canonical resources, and the real UI mode key `study:study` must be normalized at both initial and approval-resume boundaries. Parent-agent skill assembly does not automatically propagate to sub-agent tools or resumed child context.
- Permission semantics must survive every runtime port. The audit's isolated fixture established that Rust PreToolUse `permissionDecision=deny/ask_user` was ignored for AutoAllow tools; matching hook event names or passing lifecycle tests is insufficient.
- Successful upload/config responses must mean the payload is durably stored and consumed by the next execution stage. Returning an attachment ID without bytes, or listing a skill without its loader, must never be counted as feature parity.
- Existing tests passing cannot establish cross-platform parity when they omit the differing behavior. The canonical audit and staged repair boundaries are recorded in `core/docs/mobile-desktop-code-audit-2026-09-23.md`; its source baseline must remain distinct from the currently released APK.
