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
  light flash during the first ~80ms. Tauri startup motion follows native
  translucent veil → centered bare mark → theme-centered expansion → shell
  fade-in, with a reduced-motion path that removes clip-path motion.
- The desktop sidebar uses a compact 232px width while the mobile drawer keeps
  an independent responsive width; test these as separate layout contracts.
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
- The right rail uses one theme-token-driven, high-transparency blurred
  substrate with flat modules separated by hairlines. Mobile must preserve the
  same right-rail substrate instead of inheriting the generic opaque drawer
  surface. Runtime visualization remains intentionally simple until a later
  visual decision; no Three.js dependency is justified yet.
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
  Input, Output, Template, Condition, Merge, Join, and Subgraph. Legacy
  AI/Script/Content and duplicate Transform/Branch aliases remain executable
  and loadable but are hidden from new-node choices. Model and Agent use
  independent invocation paths, node type is immutable after creation, and a
  plugin type must have both a trusted schema and an installed executor before
  it can run. Do not advertise Tool/MCP or HTTP nodes until Core provides a
  real host service and permission boundary for them.
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
