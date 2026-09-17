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
- Office 全量预览声明必须绑定到最后一次源文件变更后的渲染批次。源文件修订并重新渲染后，
  之前看过的旧预览不能继续支撑 `scope=full`；应重新查看受影响的全部页面，或如实降级为
  sampled。Checklist 状态也不得重复提交或先于该证据完成。
- Sunday 安装包的内置插件边界固定为仅携带 `git`、`imagegen`、`websearch`；
  `emotion-ball-pet` 与 `workflow` 保留源码但不得进入 PyInstaller 后端资源、显式 hidden
  imports 或安装包，且本地打包脚本与 GitHub Release 流程必须使用同一拒绝/必需清单。
- DeepSeek 直连官方预设以官方 API 文档为准：当前模型为 `deepseek-flash` 与
  `deepseek-v4-pro`，上下文均为 1M，最大输出上限均为 393216 tokens；Flash 支持视觉，
  Pro 官方明确不支持视觉，不能仅凭产品命名把两者都标为多模态。
