# Writer App Server Implementation Log

更新时间：2026-06-30

维护标注（2026-06-30）：阶段 5 至阶段 8 记录的是当时“前端单 reducer”路线的实现过程。当前最新收敛结果见文末“阶段 11”：产品主线已从前端 reducer 进一步简化为后端 snapshot-only。

## 当前目标口径修正

本轮整改的目标不能由实现者自行定义，必须回指到 `docs/writer-app-server-implementation-plan.md` 的“目标来源与裁决规则”：

1. 先按 OpenAI/Codex 官方 app-server 模型判断方向是否正确。
2. 再按 Writer 设计文档里的状态、队列、审批、显示、删除旧链路规则判断实现是否完整。
3. 最后按真实浏览器端到端测试数据判断是否可交付。
4. 当前代码只能作为待验证材料，不能反过来定义正确设计。

因此，后续复核不能只说“测试通过”。必须同时说明：是否仍有旧主链路、是否仍有脏事件来源、是否仍有 live/replay 双投影、是否仍有本地伪造业务事实，以及是否满足真实浏览器验收指标。

## 阶段 0：Codex app-server 直接使用评估

### 改了什么

- 新增 `docs/writer-codex-app-server-feasibility.md`。
- 明确决策为 `decision: writer-subset`。
- 记录官方 Codex app-server 语义、本机 CLI 验证结果、当前 Writer 旧链路扫描证据。

### 删了什么

- 本阶段只做评估和文档记录，未删除产品代码。

### 还剩什么债务

- Writer 产品主链路仍依赖 `/chat` SSE、`/sessions/events`、queue REST、前端 `sseStore`、DB transcript projection、本地 UI 状态拼接。
- 还没有 Writer App Server protocol、ledger、snapshot reducer、WebSocket JSON-RPC endpoint。
- 还没有把 queue、approval、tool、artifact、status 收敛进统一事件模型。

### 哪些验收通过

- 已完成 Codex app-server 直接使用评估并记录证据。
- 已说明为什么不能直接用官方 app-server。
- 已确认后续必须进入 Writer App Server 子集路线。

### 哪些验收未通过

- Writer 前端尚未切到一个 WebSocket 主连接。
- DB event log 尚不能重建 snapshot。
- live/replay/snapshot 尚未共用同一 reducer。
- 工具、审批、queue、artifact、status 尚未统一进 app-server event model。
- 旧 SSE、DB polling、本地 pending、本地 queue、多 endpoint active polling 尚未删除。

## 阶段 1：协议与 ledger

状态：已完成基础设施切入。

### 改了什么

- 新增 Writer 专属 `members/writer/backend/app/app_server/` 模块：
  - `protocol.py`：JSON-RPC request/response、initialize 参数、event envelope。
  - `ledger.py`：append-only event log，按 thread 分配单调 `seq`，支持按 `event_id` 幂等。
  - `reducer.py`：后端 snapshot reducer，处理 thread、turn、item、queue、request、artifact 基础事件。
  - `snapshot.py`：增量应用事件到 snapshot，并支持从 event log 重建 snapshot。
  - `connection.py` / `router.py`：新增 `/api/app-server` WebSocket JSON-RPC 基础端点。
- 新增 canonical 表模型：
  - `writer_app_events`
  - `writer_thread_snapshots`
  - `writer_app_requests`
  - `writer_artifacts`
- 更新 SQLite additive migration，确保现有本地 DB 可创建新表和索引。
- 更新 FastAPI app，把 Writer App Server WebSocket 路由挂到 `/api/app-server`。
- 新增阶段 1 后端测试：
  - `tests/test_writer_app_server_protocol.py`
  - `tests/test_writer_app_event_ledger.py`

### 删了什么

- 本阶段未删除旧产品主链路；按计划旧 SSE、queue REST、DB projection 会在前端单 reducer 和新 turn/queue/approval 路径可用后集中下线。

### 还剩什么债务

- 新 WebSocket 端点目前只覆盖 initialize、thread/start、thread/resume、thread/read；还未接入 turn/start、queue、approval、runtime bridge。
- `writer_app_events` 已存在，但旧 `/chat` SSE 仍是实际运行主入口。
- 前端尚未建立 app-server client/reducer/store。
- 旧 transcript、queue、SSE store 仍被产品入口 import。

### 哪些验收通过

- `py -3.14 -m pytest tests\test_writer_app_server_protocol.py tests\test_writer_app_event_ledger.py -q`：6 passed。
- `py -3.14 -c "from app.main import app; print(any(getattr(route, 'path', '') == '/api/app-server' for route in app.routes))"`：输出 `True`。
- ledger 支持 thread 内单调 `seq`。
- 重复 `event_id` 不重复写。
- gap replay 能按 `seq` 返回。
- snapshot 可由 event log 重建，并与增量 snapshot 一致。

### 哪些验收未通过

- Writer 前端尚未切到一个 WebSocket 主连接。
- live/replay/snapshot 尚未在前端共用同一 reducer。
- 工具 started/delta/completed 尚未从 runtime 事实流式进入 app-server event。
- queue、approval、artifact、status 尚未完成统一事件模型。
- 旧 SSE、DB polling、本地 pending、本地 queue、多 endpoint active polling 尚未删除。

## 阶段 2：Runtime Bridge

状态：已完成基础转换层。

### 改了什么

- 新增 `members/writer/backend/app/app_server/runtime_bridge.py`。
- 增加从现有 `WriterRuntimeEvent` 到 app-server event 的规范化转换：
  - `runtime.reply_delta` -> `item/delta` (`agentMessage`)。
  - `runtime.tool.started` -> `item/started` (`dynamicToolCall`)。
  - `runtime.tool.finished` -> `item/delta` + `item/completed`。
  - `runtime.approval_request` / `runtime.waiting` -> `item/started` + `item/requestApproval`。
  - `runtime.part` -> item lifecycle 基础事件。
  - `runtime.done` / `runtime.failed` -> `turn/completed`。
- 增加 `persist_runtime_event_as_app_events(...)`，确保 runtime 事实进入 ledger 后再更新 snapshot。
- 新增 `tests/test_writer_app_runtime_bridge.py` 覆盖 reply、tool、approval 和 snapshot 更新。

### 删了什么

- 本阶段未删除旧 runtime -> transcript/SSE 同步逻辑；它仍是当前产品主链路，后续阶段迁移产品入口后下线。

### 还剩什么债务

- runtime bridge 还未接入 `writer_service.py` 的实际运行循环。
- `turn/start` 尚未通过 app-server 启动 runtime。
- 工具 stdout/stderr、artifact 细粒度映射还未完成。
- approval 只完成事件转换，尚未实现 request 幂等状态表和决策响应。

### 哪些验收通过

- `py -3.14 -m pytest tests\test_writer_app_server_protocol.py tests\test_writer_app_event_ledger.py tests\test_writer_app_runtime_bridge.py -q`：10 passed。
- 命令/工具开始事件可规范为 `item/started`，不依赖工具完成后补块。
- approval runtime fact 可规范为 `item/requestApproval`，不是 tool error。
- runtime bridge 写入 ledger 后可以更新 snapshot。

### 哪些验收未通过

- 前端还不能通过 WebSocket 看到 runtime bridge 事件。
- app-server 还没有 turn/start queue steer。
- app-server 还没有 approval/respond。
- 旧主链路仍未删除。

## 阶段 3：turn/start、queue、steer

状态：已完成后端事实入口。

### 改了什么

- 新增 `members/writer/backend/app/app_server/queue.py`。
- 新增 app-server 后端方法处理：
  - `turn/start`
  - `queue/create`
  - `turn/steer`
- `turn/start` 现在会立即写入并推送：
  - `turn/accepted`
  - userMessage `item/started`
  - userMessage `item/completed`
  - `turn/started`
- `queue/create` 只产生 `queue/itemAccepted`，不把运行中普通输入写进 transcript item。
- `turn/steer` 校验 active turn；active turn 不匹配时记录 `queue/itemUpdated` with `guidance_expired`。
- ledger 增加 `find_client_event(...)`，支持 `client_message_id` 幂等重试。
- 新增 `tests/test_writer_app_queue.py`。

### 删了什么

- 本阶段没有删除旧 queue REST；新 queue event 模型已建立，旧 REST 会在前端迁移后下线。

### 还剩什么债务

- `turn/start` 还没有真正启动 `CoreLoopKernel + WriterKit`。
- completed 后 FIFO 自动派发尚未实现。
- failed 后不自动派发尚未接入真实终态。
- 前端尚未通过 app-server client 调用这些方法。

### 哪些验收通过

- `py -3.14 -m pytest tests\test_writer_app_server_protocol.py tests\test_writer_app_event_ledger.py tests\test_writer_app_runtime_bridge.py tests\test_writer_app_queue.py -q`：14 passed。
- `turn/start` 能立即生成 accepted/user item/started 事件。
- 同一 `client_message_id` 重试复用已存在 accepted 事实，不重复创建 turn。
- `queue/create` 只进入 queue tray，不写 transcript user message。
- `turn/steer` 只允许 active turn，否则记录 guidance expired。

### 哪些验收未通过

- completed 后 500ms 内自动派发 FIFO 还未实现。
- failed 后不自动派发还未用真实 runtime 终态验证。
- 前端点击发送到 accepted/queued 可见 < 300ms 尚未实测。
- 旧 `/queued-inputs` REST 仍在产品主链路中。

## 阶段 4：审批与 waiting

状态：已完成后端 request 幂等基础。

### 改了什么

- 新增 `members/writer/backend/app/app_server/approvals.py`。
- 新增 `approval/respond` JSON-RPC 方法。
- runtime bridge 遇到 `item/requestApproval` 时同步写入 `writer_app_requests(status=open)`。
- `respond_to_approval(...)` 使用 `writer_app_requests` 作为幂等事实：
  - 第一次决策把 request 改为 `resolved`；
  - append `serverRequest/resolved`；
  - 后续重复响应返回第一次决策，不再改写 decision。
- 新增 `tests/test_writer_app_approvals.py`。

### 删了什么

- 本阶段未删除旧 approval/transcript waiting_request 逻辑；它仍被旧 SSE UI 使用。

### 还剩什么债务

- app-server approval 尚未接入真实工具执行继续/拒绝路径。
- UI 尚未通过 app-server request 卡片做决策。
- 高危命令审批 E2E 尚未接到新链路验证。
- `other_guidance` 已记录，但尚未接入 active turn guidance 消费。

### 哪些验收通过

- `py -3.14 -m pytest tests\test_writer_app_server_protocol.py tests\test_writer_app_event_ledger.py tests\test_writer_app_runtime_bridge.py tests\test_writer_app_queue.py tests\test_writer_app_approvals.py -q`：17 passed。
- approval request 会写入 `writer_app_requests(status=open)`。
- `serverRequest/resolved` 进入 ledger/snapshot。
- 重复点击不同 decision 只保留第一次服务端 decision。
- `other_guidance` 能作为决策 payload 记录。

### 哪些验收未通过

- 审批点击到 UI 锁定 < 100ms 尚未实现。
- 审批点击到 resolved 可见 < 700ms 尚未实测。
- 删除文件命令在新 app-server UI 下触发审批尚未实测。
- 旧 waiting_request transcript 仍在产品显示链路。

## 阶段 5：前端单 reducer

状态：已完成产品主路径迁移。

### 改了什么

- 新增 `members/writer/frontend/src/appServer/`：
  - `protocol.ts`：前端 app-server event/snapshot 类型。
  - `reducer.ts`：live event / replay event / snapshot hydrate 共用 reducer。
  - `selectors.ts`：chat、queue、approval、status selector。
  - `client.ts`：WebSocket JSON-RPC client，处理 initialize、request/response、server notifications。
  - `store.ts`：Pinia store，集中持有后端事件事实和连接状态。
- 新增前端测试：
  - `tests/appServer/reducer.test.ts`
  - `tests/appServer/selectors.test.ts`
- 更新 `npm test`，把 `tests/appServer/*.test.ts` 纳入常规测试。
- `CoreWorkbenchView.vue` 初步接入 app-server store/selectors：
  - 会话切换时连接 `/api/app-server` 并 resume 当前 thread。
  - 普通发送走 `turn/start`。
  - running/waiting 普通发送走 `queue/create`。
  - queue 编辑/删除走 `queue/update` / `queue/delete`。
  - queue row 引导走 `turn/steer`，随后删除 queue item。
  - approval 点击走 `approval/respond`。
  - ChatThread 消息与 queue tray 优先由 app-server reducer state 映射。
- 后端 `turn/start` 已接到真实 Writer runtime：
  - app-server accepted 后启动 `writer_service["send_message"]`。
  - `writer_service` 的 runtime 事实双写到 `writer_app_events` 并通过 app-server hub 广播。
- 新增 app-server hub：
  - WebSocket 连接按 thread 订阅。
  - runtime bridge 写入 ledger/snapshot 后推送给订阅客户端。
- queue 方法补齐：
  - `queue/update`
  - `queue/delete`

### 删了什么

- `CoreWorkbenchView.vue` 的发送、运行中排队、队列编辑/删除/引导、审批点击已经不再调用旧 `/chat` SSE 或 `/queued-inputs` REST。
- 删除 `CoreWorkbenchView.vue` 中的旧 transcript snapshot fallback、`refreshCoreTranscript`、`refreshQueuedInputs`、`scheduleTranscriptRefresh`、旧 waiting-request REST fallback。
- 删除前端 `stores/sse.ts` 与 `composables/useSSE.ts`。
- 删除前端 `/chat`、`/queued-inputs`、`/sessions/events`、`/waiting-requests`、`/transcript` API 暴露。
- 删除前端旧 `transcriptProjectionProtocol.ts`，`runtime/transcript.ts` 缩减为类型定义，不再提供 DB transcript builder。
- 删除旧 runtime transcript/projection 测试，常规前端测试只覆盖 app-server reducer/selectors。

### 还剩什么债务

- WebSocket 重连 gap recovery 只有基础 lastSeenSeq 调用，还没有完整暂停渲染/补齐策略。
- approval 继续执行已桥接到旧 waiting_request 服务函数，但 request -> waiting block 目前通过“唯一打开 waiting_request”查找；后续应在 runtime bridge 写入稳定 block_id 映射，避免多等待请求时拒绝继续。
- artifact 索引表存在，但 runtime artifact -> `artifact/created` 的完整映射仍未补齐。
- CLI/TUI 旧 `/chat` SSE 入口已经不能使用，尚未迁移到 app-server transport。

### 哪些验收通过

- `npm test`：9 passed。
- `npm run build`：通过，保留既有 chunk-size warning。
- `py -3.14 -m pytest tests\test_writer_app_server_protocol.py tests\test_writer_app_event_ledger.py tests\test_writer_app_runtime_bridge.py tests\test_writer_app_queue.py tests\test_writer_app_approvals.py -q`：21 passed。
- live event 和 replay event 输入同一 reducer 后结果一致。
- 重复 `event_id` 不重复显示。
- `item/started` 可立即生成工具块，delta 追加到同一 item。
- queue tray 与 transcript 分离。
- queue update/delete 是 app-server event fact，不依赖旧 REST。
- `queue/itemDispatched` 会从 queue tray 移除，completed 后 dispatcher 复用 `turn/start` 事件序列自动派发 FIFO。
- failed 后 dispatcher 不派发 queue。
- approval resolved 后 selector 能显示已选择 decision。
- snapshot hydrate 复用同一 normalized state shape。
- Workbench 编译通过，发送/队列/审批调用已改为 app-server client。
- 浏览器加载 `http://127.0.0.1:6174/` 正常；手动 WebSocket smoke 连接 `ws://127.0.0.1:6173/api/app-server`，`initialize` 返回 `writer.app_server.v1`，`thread/read` 返回 snapshot。
- 旧 `/chat`、`/queued-inputs`、`/sessions/events`、`/transcript` 外部 route 已从后端 session router 删除。

### 哪些验收未通过

- 刷新前后 ChatThread 业务内容一致尚未用真实长任务完整验证。
- 审批点击到 UI 锁定 < 100ms、resolved 可见 < 700ms 尚未在真实危险命令场景实测。
- completed 后 FIFO 自动派发 < 500ms 已有单元语义测试，尚未在真实前端任务中计时验证。
- 前端 network 主连接数尚未用 DevTools/CDP 完整采样；已通过源码删除和后端日志确认旧接口未被页面启动调用。
- 长上下文旧 20s-60s 吞消息场景尚未重新跑完整性能记录。
- CLI/TUI 迁移未完成。

## 阶段 6：删除旧链路

状态：产品主链路旧入口已删除，非前端 CLI/TUI 迁移未完成。

### 改了什么

- 后端 session router 删除旧实时/队列/投影 route：
  - `/api/sessions/events`
  - `/api/sessions/{session_id}/chat`
  - `/api/sessions/{session_id}/queued-inputs...`
  - `/api/sessions/{session_id}/waiting-requests/{block_id}/decision`
  - `/api/sessions/{session_id}/transcript`
- app-server queue 增加 FIFO dispatcher：
  - completed 后只在 snapshot status 为 `idle` 时派发第一条 queued item；
  - 先写 `queue/itemDispatched`，再复用 `turn/start` 事件序列；
  - failed 状态不自动派发。
- app-server approval 增加后台继续：
  - `approval/respond` 先写 `serverRequest/resolved`；
  - 首次决策才尝试继续真实等待块；
  - 重复决策只返回第一次 resolved event，不重复执行。
- WebSocket 正常断开不再作为 ASGI 异常打印。

### 删了什么

- 删除 Writer 前端 SSE store、SSE reader、旧 transcript projection builder、旧 runtime projection tests。
- 删除 Writer 后端旧 SSE/queue/transcript/chat route 块，不再保留外部兼容入口。
- 删除前端 `SSEWriterPart` / `SSEWriterReplyDelta` 类型暴露。

### 还剩什么债务

- `writer_service.py` 内部仍会生成旧 runtime event 名称，例如 `writer_part`，目前由 runtime bridge 消化；这不是外部主链路，但后续应继续收敛为纯 app-server item fact。
- `queued_input_service.py` 和旧 queue model 仍存在，供旧内部恢复/迁移代码引用；产品外部入口已删除。
- `transcript_service.py` 仍存在，供旧内部恢复/迁移代码引用；产品外部投影入口已删除。
- CLI/TUI 仍包含旧 `/chat` SSE 调用代码，当前会失败；需要后续迁移为 app-server client。

### 哪些验收通过

- 旧前端主链路扫描未命中：`useSseStore`、`readSSEStream`、`/chat`、`/queued-inputs`、`transcriptSnapshot`、`projectTranscriptSnapshot`、`applyTranscriptProjectionUpdate`。
- 后端产品 route 不再暴露旧 `/chat`、`/queued-inputs`、`/sessions/events`、`/transcript`。
- WebSocket smoke：
  - `initialize` -> `writer.app_server.v1`
  - `thread/read` -> snapshot response
- `py -3.14 -m pytest tests\test_writer_app_server_protocol.py tests\test_writer_app_event_ledger.py tests\test_writer_app_runtime_bridge.py tests\test_writer_app_queue.py tests\test_writer_app_approvals.py -q`：21 passed。
- `npm test`：9 passed。
- `npm run build`：通过，只有既有 chunk-size warning。

### 哪些验收未通过

- 真实 UI 连续发送、排队、自动派发、审批、刷新一致性的完整 E2E 尚未跑完。
- 旧 20s-60s 长上下文延迟场景尚未重新复现并记录分段延迟。
- artifact lazy read/open 尚未实现。
- schema 单源生成/校验脚本尚未实现，前后端协议类型仍是手写同步。

## 阶段 7：CLI/TUI 与旧验收资产收敛

状态：CLI/TUI 运行控制面已迁移到 app-server，旧 `/chat` SSE 测试资产已删除。

### 改了什么

- 新增 `members/writer/backend/writer_tui/backend/app_server.py`：
  - TUI 通过 `/api/app-server` WebSocket 连接；
  - 复用 app-server 事件事实并转换为 TUI reducer event；
  - 支持 `turn/start`、`turn/interrupt`、`approval/respond`。
- `ChatScreen` 改为打开页面即订阅 app-server event stream：
  - 发送消息只提交 `turn/start`；
  - 不再本地追加用户消息作为 pending；
  - 取消任务走 `turn/interrupt`；
  - 审批按钮走 `approval/respond`。
- CLI `cancel` 改为通过 app-server `turn/interrupt`，不再调用旧 HTTP cancel route。
- 前端 API 删除旧 `cancelSession` / `resumeSession` 辅助函数。
- 后端 session router 删除旧 HTTP cancel route、旧 runtime/chat 辅助函数、旧 resume 占位 route、旧 debug SSE 注入 route。
- 后端 pytest 收集仍可完成，当前可运行测试集不再依赖旧 `/chat` route。

### 删了什么

- 删除 `writer_tui/backend/sse.py`。
- 删除旧 TUI SSE parser 测试，替换为 `test_tui_app_server_events.py`。
- 删除 CLI `writer sse send` 调试命令。
- 删除一批以旧 `/api/sessions/{id}/chat` + SSE 为入口的历史手工脚本和 E2E 测试资产：
  - `bench_v2.py`、`bench_v3.py`
  - `e2e_recipe*.py`
  - `run_*.py` 旧 SSE 手工脚本
  - `send_task.py`、`smoke_test.py`
  - `test_e2e_stability.py`
  - `test_tool.py`
  - `test_tui_e2e.py`
  - `test_writer_core_http.py`
  - `test_writer_core_http_e2e.py`

### 还剩什么债务

- `writer_service.py`、`TaskManager`、`core/writer/events.py` 等内部仍存在 SSE 命名和旧 Writer event 名称；当前产品外部入口已删除，但内部命名后续应继续收敛。
- TUI 当前复用 CLI app-server client 的 legacy-shaped adapter；后续应直接消费 app-server item snapshot，而不是先转旧事件形状。
- approval request 到旧 waiting block 的稳定映射仍需补齐。
- artifact -> `artifact/created` 完整映射仍需补齐。
- 真实 UI 连续发送、排队、审批、刷新一致性和长上下文延迟仍需要完整 E2E 计时验证。

### 哪些验收通过

- 旧外部入口扫描通过：
  - 未命中 `/api/sessions/{id}/chat`
  - 未命中 `debug/sse`
  - 未命中 `/cancel`
  - 未命中 `/resume`
  - 未命中 `/sessions/events`
  - 未命中 `readSSEStream`
  - 未命中 `useSseStore`
  - 未命中 `transcriptSnapshot` / `projectTranscriptSnapshot` / `applyTranscriptProjectionUpdate`
- `py -3.14 -m pytest tests\test_tui_app_server_events.py tests\test_writer_app_server_protocol.py tests\test_writer_app_event_ledger.py tests\test_writer_app_runtime_bridge.py tests\test_writer_app_queue.py tests\test_writer_app_approvals.py -q`：28 passed。
- 加上旧 cancel route 删除验收后：29 passed。
- `py -3.14 -m pytest --collect-only -q`：945 tests collected。
- `py -3.14 -c "import writer_tui.backend.app_server; import writer_tui.screens.chat; import writer_cli.app_server_client; print('imports ok')"`：通过。
- `py -3.14 -m writer_cli --help`：通过，CLI 不再暴露 `sse` 子命令。
- `npm test`：9 passed。
- `npm run build`：通过，只有既有 Vite chunk-size warning。

### 哪些验收未通过

- TUI 未做交互式端到端按键验证；本阶段只完成导入和事件转换单测。
- 真实浏览器完整 E2E 未重新跑完：连续发送、排队自动派发、审批点击、刷新一致性仍需计时记录。
- 长上下文 20s-60s 发送延迟场景未重新实测。
- 内部 SSE 命名债务尚未完成语义重命名。

## 阶段 8：浏览器 E2E 与实时链路收口

状态：真实浏览器 app-server 主链路验收已通过，artifact lazy read/open 子集已补齐。

### 改了什么

- `members/writer/frontend/vite.config.ts` 给 `/api` 代理启用 `ws: true`，确保前端 dev server 可以代理 `/api/app-server` WebSocket。
- `members/writer/frontend/src/appServer/reducer.ts` 不再直接 `structuredClone` Pinia reactive proxy，避免 live event reducer 因 `DataCloneError` 中断。
- `members/writer/frontend/src/views/CoreWorkbenchView.vue` 调整 composer 清空时机：只有 `turn/accepted` 或 `queue/itemAccepted` 成功后才清空输入。
- `members/writer/frontend/src/appServer/client.ts` 把主动断开的 WebSocket close 归类为 `AbortError`，页面切换/重连不再误报实时失败。
- `members/writer/frontend/scripts/writer-app-server-e2e.mjs` 增加真实浏览器验收：
  - idle 发送后等待 transcript 中出现后端 accepted 用户消息；
  - running 发送后等待 queue tray 中出现后端 queue item；
  - reload 后验证 transcript 和 queue 仍可恢复；
  - 检查禁止旧实时接口；
  - 统计 `/api/app-server` WebSocket。
- E2E 网络失败过滤收窄：只忽略 reload/navigation 期间可解释的 `GET /api/core/sessions net::ERR_ABORTED`，旧实时接口和其它请求失败仍然报错。
- E2E 增加 300ms 硬门槛：accepted 或 queued 可见超过 300ms 时测试直接失败。
- 新增 `members/writer/backend/app/app_server/artifacts.py`。
- 新增 `artifact/read` / `artifact/open` JSON-RPC 方法：
  - `artifact/read` 只返回 `writer_artifacts` 索引元数据；
  - `artifact/open` 校验 artifact 属于当前 thread、路径为绝对路径且文件存在后，再交给系统打开。
- 新增 `members/writer/backend/tests/test_writer_app_artifacts.py`，覆盖读取、thread 归属校验、打开前路径校验和 opener 注入。
- 新增 `members/writer/backend/scripts/generate_app_server_schema.py`，从后端 `protocol.py` 导出 app-server JSON schema。
- 新增 `members/writer/frontend/src/appServer/protocol.schema.json`，作为当前后端协议 schema 快照。
- 新增 `members/writer/frontend/scripts/check-app-server-schema.mjs`，校验前端 `WriterAppEvent` 类型与后端 `WriterAppEventEnvelope` 字段不漂移。
- `npm test` 已接入 schema check，发现并修正 `created_at` 在前端被误标为可选的问题。
- 新增 `members/writer/frontend/scripts/writer-app-server-approval-e2e.mjs`：
  - 预置危险命令 approval request；
  - 通过 `/api/app-server` 恢复并展示审批卡；
  - 点击后 100ms 内锁定；
  - 700ms 内显示 resolved decision；
  - reload 后仍显示已选择；
  - 禁止旧实时接口。
- 新增 `members/writer/frontend/scripts/writer-app-server-long-context-e2e.mjs`：
  - 发送 13k+ 字符长上下文；
  - 记录 accepted 可见时间、首个非用户 item 事件、首个 agent delta 事件；
  - 观察窗口可用 `LONG_CONTEXT_OBSERVE_MS` 调整；
  - 结束时主动 interrupt，避免长任务悬挂。

### 删了什么

- 没有新增产品兼容旧链路。
- E2E 明确禁止以下旧接口再次出现：`/chat`、`/sessions/events`、`/queued-inputs`、`/waiting-requests`、`/transcript`、`/cancel`、`/resume`、`debug/sse`。

### 还剩什么债务

- 内部仍有旧 SSE 命名和 legacy-shaped adapter，虽然不再作为产品外部主链路。

### 哪些验收通过

- `py -3.14 -m pytest tests\test_tui_app_server_events.py tests\test_writer_app_server_protocol.py tests\test_writer_app_event_ledger.py tests\test_writer_app_runtime_bridge.py tests\test_writer_app_queue.py tests\test_writer_app_approvals.py tests\test_writer_app_artifacts.py -q`：30 passed。
- `py -3.14 -m pytest tests\test_writer_core_kernel_adapter.py::TestCommandPermissionPolicy::test_dangerous_command_requires_approval_by_default tests\test_writer_core_kernel_adapter.py::TestCommandPermissionPolicy::test_powershell_remove_item_inside_condition_requires_approval -q`：2 passed。
- `npm test`：schema check passed，10 passed。
- `npm run build`：通过，只有既有 Vite chunk-size warning。
- `WRITER_FRONTEND_URL=http://127.0.0.1:6175 npm run e2e:app-server`：通过。
  - `accepted_visible_ms`: 72
  - `queued_visible_ms`: 135
  - `queued_observed`: true
  - `forbidden_request_count`: 0
  - `app_server_socket_count`: 3，来自页面生命周期中的连接/重载；脚本限制单个生命周期只允许 app-server 主连接。
- `WRITER_FRONTEND_URL=http://127.0.0.1:6175 npm run e2e:app-server:approval`：通过。
  - `locked_visible_ms`: 41
  - `resolved_visible_ms`: 106
  - `forbidden_request_count`: 0
- `WRITER_FRONTEND_URL=http://127.0.0.1:6175 LONG_CONTEXT_OBSERVE_MS=60000 npm run e2e:app-server:long-context`：通过。
  - `prompt_chars`: 13886
  - `accepted_visible_ms`: 99
  - `first_non_user_item_event_ms`: 3783
  - `first_agent_delta_event_ms`: 15274
  - `provider_delta_observed`: true
  - `forbidden_request_count`: 0
  - 结果文件：`tmp/writer-app-server-e2e/long-context-2026-06-24T04-09-47-094Z.json`
- 残留扫描没有发现产品代码继续调用旧 Writer 实时主链路；仅剩 `thread/resume`、E2E 禁止 URL 正则和普通测试文本命中。
- completed 后 FIFO 自动派发由 `test_completed_turn_dispatches_fifo_queue_item` 覆盖，并带 `dispatch_ms < 500` 断言；failed 后不自动派发由 `test_failed_turn_does_not_dispatch_queue` 覆盖。

### 哪些验收未通过

- 无当前阻塞验收项。剩余为内部命名/legacy adapter 清理，不参与产品主实时链路。

## 阶段 9：2026-06-24 当前目标复核与脏事件源头修复

状态：当前浏览器主链路验收通过，发现并修复历史脏事件源头。

### 改了什么

- `writer_service.py` 不再把空的 `runtime.reply_delta` 总结成“整理过程说明。”。
- `runtime_bridge.py` 对没有可见内容或内容等于 `runtime.part` 的 `runtime.part` 事件不再生成可见 app-server item。
- `CoreWorkbenchView.vue` 不再把未知 app-server item 默认显示为 `sub_line`；已知工具、文件、命令、压缩、图片等类型映射到明确业务类型，未知类型显示为错误项，避免暴露内部协议名。
- `client.ts` / `connection.py` 补齐官方 app-server 风格的 server-initiated JSON-RPC request：
  - 后端遇到 `item/requestApproval` 时，以 `request_id` 作为 JSON-RPC `id` 发起 server request；
  - 前端收到带 `id` 的 `item/requestApproval` 后先把事件进入 reducer，再保存 request id；
  - 用户点击审批时优先回同一个 JSON-RPC `id` 的 response；
  - 断线、回放或旧 snapshot 场景继续保留 `approval/respond` 作为兼容入口。
- `docs/openai-codex-realtime-alignment-research.md` 和 `docs/writer-app-server-implementation-plan.md` 修正状态口径：
  - `idle` 只用于没有任何 turn 的新会话；
  - 已有 turn 的会话完成后显示 `completed`，失败后显示 `failed`；
  - 当前阶段已经进入整改实现，不再是“只调查不改代码”。
- `docs/writer-codex-app-server-feasibility.md` 将旧链路扫描明确标为“整改前证据”，避免与当前代码状态混淆。

### 删了什么

- 删除前端产品代码和前端测试中对“整理过程说明。”的历史文本过滤常量；该问题改为后端源头不再生成。

### 当前 DB 观察

- 默认 DB 仍存在历史 `runtime.part` 事件：
  - `writer_app_events`：200 条历史 payload 命中 `runtime.part`。
  - `writer_runtime_events`：2678 条历史 runtime 记录命中 `runtime.part`。
- 这些历史记录来自整改前 session，不代表新链路继续产出。
- 2026-06-24 当前三条新 E2E session 均确认：
  - `runtime_part=0`
  - `dirty_text=0`

### 哪些验收通过

- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_app_server_protocol.py -q`：21 passed。
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_approvals.py members/writer/backend/tests/test_writer_app_artifacts.py members/writer/backend/tests/test_writer_app_event_ledger.py members/writer/backend/tests/test_writer_app_queue.py members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_tui_app_server_events.py -q`：45 passed。
- `npm test`：schema check passed，14 passed。
- `npm run test:contract` in `core/ui`：39 passed。
- `npm run build`：通过，只有既有 Vite chunk-size warning。
- 真实服务：
  - Backend `http://127.0.0.1:7000/api/health` 返回 ok。
  - Frontend `http://127.0.0.1:7001` 返回 200。
- `npm run e2e:app-server`：
  - `accepted_visible_ms`: 78
  - `queued_visible_ms`: 129
  - `queued_observed`: true
  - `forbidden_request_count`: 0
- `npm run e2e:app-server:approval`：
  - `locked_visible_ms`: 34
  - `resolved_visible_ms`: 549
  - `forbidden_request_count`: 0
- 协议改造后 `npm run e2e:app-server`：
  - `accepted_visible_ms`: 143
  - `queued_visible_ms`: 63
  - `queued_observed`: true
  - `forbidden_request_count`: 0
- `LONG_CONTEXT_OBSERVE_MS=15000 npm run e2e:app-server:long-context`：
  - `prompt_chars`: 13886
  - `accepted_visible_ms`: 105
  - `first_non_user_item_event_ms`: 4757
  - `first_agent_delta_event_ms`: null
  - `provider_delta_observed`: false
  - `forbidden_request_count`: 0
  - `failed_requests`: []
  - `console_errors`: []
- 新 E2E sessions:
  - `7f76554fe7be4e4da9dfae3234fc0c9f`
  - `449801f98bad4489ae72517529a490be`
  - `dc45a1c26ed342f38ded26d203565c81`
  - `202c838abcf340e297af67d15f8db14b`
  - `30a8dd8a3c1a41728994ac131f61ad49`
  - `7c65f7c34d4b4601a27e82fa59ea987a`
  均没有新写入 `runtime.part` 或“整理过程说明”脏 app event。
- server-initiated approval session `202c838abcf340e297af67d15f8db14b` 确认：
  - `approval=1`
  - `resolved=1`

### 哪些验收未通过

- 官方 Codex app-server 不能直接接入的本机阻塞仍存在，当前路线仍是 Writer App Server 子集实现。
- 默认 DB 中仍有整改前历史脏事件。新链路不再生成，但如果要做到“历史库也完全无脏事件”，需要单独执行归档或迁移清理策略。

## 阶段 10：默认库清理闭环与连接安全补齐

状态：已完成并通过当前验收。

### 改了什么

- 新增 `WriterAppEventArchive` 模型，把 `writer_app_events_archive` 纳入正式 metadata，不再依赖测试里手工建表。
- `init_db()` 启动路径会创建归档表，然后运行 `archive_dirty_app_display_events(...)`：
  - 先把历史 `runtime.part` 可显示事件归档到 `writer_app_events_archive`；
  - 再从 `writer_app_events` 主事实流删除；
  - 最后重建受影响 thread snapshot。
- 新增 `app_server/security.py`：
  - 后端启动进程内生成 app-server capability token；
  - `/api/app-server-token` 返回本地浏览器连接 token；
  - WebSocket 带浏览器 `Origin` 时必须是 loopback origin 且 token 正确；
  - 打包桌面允许 `file://` / `null` origin，但仍必须携带 token；
  - 无 `Origin` 的本地 CLI/TUI 客户端继续可连，避免误伤非浏览器本地入口。
- 前端 app-server store 在连接前先请求 `/api/app-server-token`，再连接 `/api/app-server?token=...`。
- runtime bridge 补齐 artifact 事实链路：
  - `runtime.tool.finished` 中的 artifacts 会写入 `writer_artifacts` 索引；
  - 同时 append `artifact/created` 到 `writer_app_events`；
  - snapshot/reducer 可恢复 artifact 索引；
  - 前端 selector 会把 artifact 按 `item_id` 挂回对应工具过程块。
- 新增 `test_writer_app_security.py`。
- `test_writer_app_cleanup.py` 改为只依赖 metadata 建表，防止归档表模型再次漏掉。
- `test_writer_app_runtime_bridge.py` 增加工具 artifact 持久化和 snapshot 回归测试。
- `selectors.test.ts` 增加 artifact 挂回工具块的回归测试。

### 删了什么

- 删除了 cleanup 测试中的手工 `CREATE TABLE writer_app_events_archive`，让测试覆盖真实建表路径。

### 当前 DB 观察

- 默认 DB 清理后：
  - `writer_app_events` 中 `runtime.part` 可显示脏事件：0。
  - `writer_app_events` 中“整理过程说明”：0。
  - `writer_app_events_archive` 存在。
  - `writer_app_events_archive` 中 `legacy_runtime_part_display_event`：200。

### 哪些验收通过

- 官方 app-server 审批语义已再次核对：审批是 server-initiated JSON-RPC request，客户端响应同一个 request，随后服务端发 `serverRequest/resolved` 并以 `item/completed` 结束 item。
- 旧实时主链路扫描：
  - Writer 前端/后端产品主代码只剩 OpenAI-compatible provider 的 `/chat/completions` 命中；
  - 未发现旧 `/chat`、`/queued-inputs`、`/sessions/events`、`EventSource`、`sseStore`、`pendingLocalMessages` 参与产品主链路。
- 真实 WebSocket 安全烟测：
  - 浏览器 Origin 无 token：握手被拒绝。
  - 浏览器 Origin 带 token：`initialize` 返回 `writer.app_server.v1`。
  - 桌面 `file://` origin 带 token 可连；无 token 仍被拒绝。
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_security.py members/writer/backend/tests/test_writer_app_server_protocol.py -q`：11 passed。
- `py -3.14 -m pytest members/writer/backend/tests/test_writer_app_cleanup.py members/writer/backend/tests/test_writer_app_security.py members/writer/backend/tests/test_writer_app_approvals.py members/writer/backend/tests/test_writer_app_artifacts.py members/writer/backend/tests/test_writer_app_event_ledger.py members/writer/backend/tests/test_writer_app_queue.py members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_tui_app_server_events.py -q`：49 passed。
- `npm test`：schema check passed，15 passed。
- `npm run test:contract` in `core/ui`：39 passed。
- `npm run build`：通过，只有既有 Vite chunk-size warning。
- 真实服务：
  - Backend `http://127.0.0.1:7000/api/health` 返回 ok。
  - Frontend `http://127.0.0.1:7001` 返回 200。
- token 接入后的真实浏览器 E2E：
  - `npm run e2e:app-server`
    - `accepted_visible_ms`: 148
    - `queued_visible_ms`: 172
    - `queued_observed`: true
    - `forbidden_request_count`: 0
  - `npm run e2e:app-server:approval`
    - `locked_visible_ms`: 40
    - `resolved_visible_ms`: 559
    - `forbidden_request_count`: 0
  - `LONG_CONTEXT_OBSERVE_MS=60000 npm run e2e:app-server:long-context`
    - `accepted_visible_ms`: 98
    - `first_non_user_item_event_ms`: 4206
    - `first_agent_delta_event_ms`: 18890
    - `provider_delta_observed`: true
    - `forbidden_request_count`: 0
    - `failed_requests`: []
    - `console_errors`: []
- 最新 E2E sessions:
  - `f20862b7bc91417084266155d05e4e1e`
  - `116c3c9a506f47cf9910338216551eeb`
  - `90379c8c473e49f8b20501b5c1afac46`
  均无新 `runtime.part` 或“整理过程说明”脏 app event。

### 哪些验收未通过

- 当前没有阻塞 Writer 产品主实时链路交付的验收项。
- 仍有内部命名和 legacy-shaped CLI/TUI adapter，可作为后续内部语义清理，但不再参与浏览器产品主实时链路，不构成本目标的阻塞项。

## 阶段 11：前端 snapshot-only 精简

状态：已完成并提交。

### 改了什么

- 删除 `members/writer/frontend/src/appServer/reducer.ts`，前端不再维护 app-server event reducer。
- 新增 `members/writer/frontend/src/appServer/snapshot.ts`，只负责对后端 snapshot 做默认字段补齐。
- `store.ts` 只接收后端 WebSocket/RPC 返回的 snapshot，不再从 events 推导前端状态。
- selector 测试改为使用 snapshot fixture，避免测试继续依赖前端 replay reducer。
- `docs/decomplexity-multi-angle-review-2026-06-29.md` 记录本次减法结果。

### 删了什么

- 删除 `members/writer/frontend/tests/appServer/reducer.test.ts`。
- 删除前端事件 replay 产品主线；当前前端职责收敛为连接、提交动作、hydrate snapshot、提供 selectors。

### 还剩什么债务

- 后端仍是唯一 reducer owner，后续需要继续通过 schema/contract 防止前后端协议漂移。
- transcript 与 app snapshot 的边界仍需继续审查，避免未来出现第二个 UI 可见事实源。
- CLI/TUI 中 legacy-shaped adapter 和内部旧命名仍可继续清理，但不影响浏览器主实时链路。

### 哪些验收通过

- `npm test` in `members/writer/frontend`：通过。
- `npm run build` in `members/writer/frontend`：通过。
- 当前源码确认 `members/writer/frontend/src/appServer/reducer.ts` 不存在。
- 当前源码确认 `store.ts` 只调用 `hydrateSnapshot(...)`，未命中 `applyEvent` 或 `usesAuthoritativeSnapshots`。

### 哪些验收未通过

- 本阶段没有新增阻塞项；剩余为后续协议收敛和历史命名清理。
