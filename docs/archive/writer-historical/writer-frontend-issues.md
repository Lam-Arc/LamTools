# Writer Frontend — Known Issues

> Last updated: 2026-06-29

## Current Non-Blocking Issues

### 0. Runtime Display Chain Durability

- **Severity**: P0 display/runtime contract issue
- **Observed**: In session `8b0f4b26`, the UI showed streaming progress, then suddenly displayed `已取消` and previous process information disappeared. Refresh did not rebuild the process.
- **Confirmed facts**:
  - Backend session was not actually cancelled; DB status stayed `active`.
  - Runtime state advanced and kept checklist/architecture state.
  - Renderable tables had no recoverable process: `writer_steps = 0`, `writer_runtime_events = 0`, only the user message existed.
  - Logs showed the task continued after the UI showed cancellation, including sub agent work and file writes.
- **Root cause**: Display relied too much on transient SSE memory. Runtime events were batched until the kernel run ended, so another frontend refresh could not recover in-flight process state.
- **Desired contract**: `SSE -> durable runtime event/message/step store -> frontend incremental display from persisted data`. Refresh must rebuild from the same durable source.
- **Impact**: Users cannot trust the visible process during long tasks; a normal stream interruption can look like cancellation and can hide previous work.
- **Status**: Partially fixed. Recoverable runtime events are now persisted before SSE publish; token-level reply deltas are no longer stored as runtime events. Frontend AbortError refreshes from persisted history instead of showing `已取消`. Remaining work: full frontend should consume persisted events as the primary incremental source, not just as reconnect recovery.

### 0.1 Abort Is Labeled as Cancelled Too Broadly

- **Severity**: P1 UX/state issue
- **Observed**: The UI can show `已取消` when the frontend stream is aborted, even if backend runtime continues.
- **Root cause**: Frontend mapped generic `AbortError` to `已取消`. This conflated user Stop with session switch, component reset, connection interruption, or stream replacement.
- **Desired contract**: Only explicit backend/user cancellation should show `已取消`. Passive stream aborts should show reconnecting, detached, or no status change, depending on context.
- **Status**: Fixed for the main stream. AbortError now shows connection sync wording and triggers persisted-history reload. `已取消` is reserved for backend lifecycle/session status.

### 0.2 Sub Agent Timeline Does Not Match Writer Timeline Style

- **Severity**: P1 UX/protocol issue
- **Observed**: Sub agent output in the current run is not displayed like a smaller Writer timeline. In the screenshot, the agent header is too sparse, the nested content looks disconnected from the main Writer rendering, and markdown/process blocks do not clearly reuse the normal Writer message/tool/thought styles.
- **Working name**: `sub line`, not `Agent card`.
- **Expected behavior**: When Writer calls an Agent, the UI opens one `sub line`. This sub line is the nested sub agent timeline: Writer's dispatched message is shown on the right, and the sub agent's running timeline is shown on the left. The sub line container itself may be smaller, but inside it, tool calls, thinking, markdown, file writes, diffs, and final text should reuse the same rendering rules as the main Writer timeline with smaller typography.
- **Parallel behavior**: If one Writer turn dispatches multiple Agents in parallel, the UI should open multiple sub lines at the same level, ordered by dispatch order. There should not be a separate fake `parallel` agent item; parallelism is only the fact that multiple sub lines started from the same Writer turn.
- **Likely cause direction**: Sub agent presentation still has special-case rendering instead of treating sub agent events as the same display protocol under a nested scope.
- **Status**: Partially fixed. Sub agent calls now carry stable `sub_line_id` / `agent_run_id`, frontend maps agent display to `sub_line`, and child reasoning/tool/text events are grouped under the parent sub line when possible. Needs real-task visual验收 for parallel sibling sub lines.

### 1. Writer LLM Error on Some Multi-Step Tasks

- **Severity**: Backend/runtime issue
- **Description**: 前端可以正常发送任务和接收 SSE，但 Writer runtime 在部分复杂任务里仍可能返回 `llm_error`。
- **Impact**: 前端会展示错误状态；步骤面板本身可用。

### 2. Work Root Folder Picker Is Browser-Limited

- **Severity**: UX
- **Description**: Web 端无法可靠拿到 Windows 绝对路径。桌面端通过 `window.lamwriterDesktop.selectDirectory()` 提供原生目录选择；浏览器端仍需要目录选择 API或手动输入。
- **Impact**: 浏览器模式仍受平台限制；Electron/Tauri 桌面模式已走原生选择。

### 3. Attachment Button Is UI Placeholder

- **Severity**: UX / feature gap
- **Description**: 输入栏已有附件入口，但后端消息附件协议尚未落地。
- **Impact**: 普通文本任务不受影响。

### 4. Quality Mode Selector Is Not Yet a Runtime Contract

- **Severity**: API contract gap
- **Description**: Workbench 已按设计稿展示 `auto/toy/low/medium/high/crazy` 质量模式，但当前 `/chat` 的 `mode` 字段仍主要对应 Writer interaction mode。
- **Impact**: UI 已保留入口；后端需要单独字段区分 Writer 质量模式、交互模式和模型思考参数。

### 5. Git Graph Depends on Session Work Root

- **Severity**: Expected behavior
- **Description**: 只有会话绑定的 `work_root` 是真实 Git 仓库时，右侧 Git 面板才展示版本图。
- **Impact**: 非 Git 目录显示 `No git graph`。

---

## Fixed Issues

### Running Task Feedback Was Too Sparse

- **Fix**: 聊天区按发送流程分层：用户消息、过程、sub line、决策、reply 各有固定落点。LLM/tool/step/progress 在 reply 前展开，reply 后折叠为“已处理 N 项过程”；sub line 显示 Writer 派发消息、子代理运行时间线和返回信息；决策卡展示原因、阻塞点、计划和选项。

### favicon 404

- **Fix**: `frontend/index.html` 改为引用已有的 `/favicon.svg`。

### Routing Rule Display Shows IDs Instead of Names

- **Fix**: Settings 页路由规则展示 provider/model 名称，不再默认展示 UUID。

### No Error Toast/Notification on API Failures

- **Fix**: Workbench 加入顶部错误提示，项目、会话、AGENTS.md、发送、取消、重试失败都会反馈。

### Chat Input Enter Key Not Always Triggering Send

- **Fix**: 输入框改为 `Enter` 发送，`Ctrl+Enter` 同样发送。

### No Loading Indicator During SSE Streaming

- **Fix**: SSE 运行中且尚未收到文本时显示 Writer typing indicator。

### SSE Cancel Did Not Abort Fetch

- **Fix**: `api.chat()` 支持 `AbortSignal`，`sseStore.stopStream()` 会中止当前 fetch/stream。

### Duplicate Assistant Draft Risk

- **Fix**: SSE 完成事件不再额外追加 assistant 消息，避免与 Workbench 的 live draft 重复。

### Step Summary Not Updating During Stream

- **Fix**: `writer_step` 事件通过 `stepStore.upsertStep()` 更新，并本地重算 summary。

### Root App Debug Navigation Leak

- **Fix**: 删除 `App.vue` 中临时 `Workbench/Settings` 导航，避免压在真实 UI 左上角。

### Accepted UX Preview Implemented in Vue

- **Fix**: Workbench 改为左侧项目抽屉、中央主线程、右侧运行抽屉和浮动输入栏；支持 `Ctrl+Tab`、`Ctrl+E`、边缘 hover、固定抽屉、进度窗口、Git 状态区和发送动画。

### Settings Product Skeleton Implemented

- **Fix**: Settings 改为中文设置中心，包含 API 管理、模型参数、Writer/Agent 模型分配、当前解析、权限与工具、Git 策略、记忆与上下文、界面与快捷键。旧路由规则不再作为用户入口。

### Provider Presets Create Matching Default Models

- **Fix**: Settings 新增 Provider 模板：OpenAI、Claude / Anthropic、DeepSeek、智谱 GLM、讯飞 Coding。新建 Provider 时可同时创建推荐模型，保存后保持刚创建的 Provider 选中。
- **Contract**: 模板只预填 provider/model 配置，不保存 API key 以外的隐式凭据；编辑已有 Provider 时不套模板，避免覆盖用户配置。

### Workbench Project List Uses Latest Activity

- **Fix**: 项目组和未归档会话组按最近项目/会话更新时间排序。新建项目后立即把新会话写入本地 session 列表，再刷新远端列表，避免创建后侧栏短暂丢失。
- **Fix**: 未归档工作区现在可以按组删除，会逐个删除该 work_root 下的会话；若当前会话被删除，会断开 app-server 并切换到剩余会话或重新加载初始数据。

### App Server Queue Actions Are Bound to Their Thread

- **Fix**: 队列托盘只展示当前 active session 对应的 app-server snapshot，避免切换会话后操作旧 thread 队列。
- **Fix**: 删除、保存、引导 queued input 前会确保 app-server 已连接到该 queued item 的 session。

### Runtime Metrics Are Displayed As Product Metrics

- **Fix**: `processMetrics` 进入共享 `ChatThread` 与 Workbench 指标条，折叠态优先展示模型调用、耗时、总 token、缓存命中率；缺少指标时回退为工具/思考/上下文/压缩/失败计数。
- **Contract**: 前端只展示后端 app-server snapshot/selectors 提供的 runtime metrics，不再本地估算模型消耗。

### /api/config/resolved 500 Error

- **Root cause**: Backend fallback ORM 对象缺少 `created_at/updated_at`，Pydantic 转换失败。
- **Fix**: 直接构造 Pydantic response 对象。

### Frontend Body Stream Already Read Error

- **Root cause**: `res.json()` 先消费错误响应 body，后续 `res.text()` 失败。
- **Fix**: 先读 `res.text()`，再尝试 `JSON.parse()`。
