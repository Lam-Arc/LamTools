# Writer backend/CLI Core-first audit

日期：2026-07-10

范围：

- `members/writer/backend/app/app_server/`
- `members/writer/backend/app/services/`
- `members/writer/backend/writer_cli/`

结论：目标范围内仍有多处“通用 Agent host 基础设施”由 Writer 承担。最高价值迁移不是继续增加新层，而是把 Writer 已经复用 Core 的半下沉代码收敛为 Core 的深模块接口：事件/快照/队列/审批/运行投影/CLI watch 归 Core，Writer 只保留会话、转录、项目、附件、Git/review/checkpoint 等产品或本地持久层 adapter。

## 判定边界

本次不纳入迁移候选：

- 项目管理、项目目录选择、AGENTS.md 读写：`project_management.py`、`project_directory_picker.py`、`operations.py` 中 `project.*`。
- 转录模型本身：`transcript_service.py`、`runtime_transcript_sink.py` 的 block/call/producer 落库结构属于 Writer 展示与恢复实现，可作为 Core hook 的 adapter，不应整体下沉。
- Git/review/checkpoint/rollback/undo/agent branch：这些是 Writer coding 产品能力或工作区治理能力，不按通用 Agent 基础设施误报。
- 会话 CRUD 的 Writer 数据模型：`WriterSession` 及其项目归属、模式、工作目录字段仍属于 Writer member。

## P0：App event ledger / snapshot / reducer adapter

精确位置：

- `members/writer/backend/app/app_server/protocol.py:20-50`
- `members/writer/backend/app/app_server/ledger.py:13-18`, `members/writer/backend/app/app_server/ledger.py:21-84`
- `members/writer/backend/app/app_server/snapshot.py:14-28`, `members/writer/backend/app/app_server/snapshot.py:31-73`
- `members/writer/backend/app/app_server/event_store.py:12-45`
- `members/writer/backend/app/app_server/reducer.py:14-22`, `members/writer/backend/app/app_server/reducer.py:18-117`, `members/writer/backend/app/app_server/reducer.py:296-315`

现有职责：

- 定义 Writer app event envelope/input。
- 把 Writer SQLAlchemy app-event row 转成 Core app event，再转回 Writer envelope。
- 每次追加事件后更新 snapshot。
- 对 `turn/accepted`、`item/started`、`queue/*`、`serverRequest/resolved`、`core/runItem` 维护可恢复 thread snapshot。

为何不含 Writer 产品语义：

- 这些对象和方法名是 thread、turn、item、queue、request、artifact、runItem，都是 Agent host 通用显示/恢复语义。
- `PROTOCOL_VERSION = "writer.app_server.v1"` 是成员协议标识，不是业务语义。
- 当前 Writer reducer 已经把 `core/runItem`、queue 状态和 snapshot 主体交给 `CoreAppSnapshotProjector`，说明这不是 Writer 独有行为。

Core 现有可复用能力：

- `core/src/lamtools_core/app/event_store.py:33-57` 已有 `AppEventInput` / `AppEventEnvelope`。
- `core/src/lamtools_core/app/event_store.py:75-204` 已有 `SqlAlchemyAppEventStore`。
- `core/src/lamtools_core/app/snapshot_store.py:20-75` 已有 `CoreAppSnapshotProjector`，覆盖 turn/item/queue/core runItem。
- `core/src/lamtools_core/app/snapshot_store.py:215-257` 已有 `SqlAlchemyThreadSnapshotStore`。
- `core/src/lamtools_core/snapshot/__init__.py:19-132` 已有 canonical run-item reducer。

最小下沉接口：

- 在 Core 提供 `CoreAppPersistenceHost(event_model, snapshot_model, protocol_version, projector=None)`，统一暴露 `append_event`、`append_run_item_event`、`append_and_apply_snapshot`、`list_after`、`list_thread`、`find_client_event`、`load_snapshot`、`rebuild_snapshot`。
- Writer 只传 SQLAlchemy row model、协议版本和少量 legacy projector patch。
- Writer 的 `WriterAppEventEnvelope` 可保留为兼容 DTO，但不再承担 event-store/snapshot 编排。

迁移风险：

- 中高。现有 snapshot 同时存在 outer state 和 `core` state，且 `session/rollback_turn`、legacy `turn/started` 仍在 Writer reducer 内。
- 风险主要是历史事件重放和前端 snapshot 兼容，不是新 runtime 行为。

推荐优先级：P0。它是后续 queue、approval、CLI watch 下沉的基础。

## P0：Thread / turn / queue / approval live operations

精确位置：

- `members/writer/backend/app/app_server/operations.py:142-149`
- `members/writer/backend/app/app_server/operations.py:461-540`
- `members/writer/backend/app/app_server/operations.py:1612-1680`
- `members/writer/backend/app/app_server/operations.py:1683-1721`
- `members/writer/backend/app/app_server/operations.py:1724-1809`
- `members/writer/backend/app/app_server/operations.py:2084-2114`
- `members/writer/backend/app/app_server/operations.py:2163-2236`
- `members/writer/backend/app/app_server/queue.py:33-83`, `members/writer/backend/app/app_server/queue.py:86-168`, `members/writer/backend/app/app_server/queue.py:171-246`

现有职责：

- 构造 RPC outcome。
- 处理 `thread.start/read/resume`。
- 处理 `turn.start/steer/cancel` 的参数校验、事件接受、snapshot 返回和 runtime_start。
- 处理 queue create/update/delete/dispatch。
- 处理 approval respond，并给 runtime continuation。

为何不含 Writer 产品语义：

- Thread/turn/queue/approval 是任何可交互 Agent app 的通用控制面。
- Writer 特化点只在 turn 接收前后：`prepare_composer_input`、`create_user_message_turn`、attachment id、`WriterSession.work_root`。
- `queue.py:9-24` 已直接导入 Core queue/turn acceptance helpers，说明 Writer 主要在补 adapter，而不是提供业务策略。

Core 现有可复用能力：

- `core/src/lamtools_core/app/live_operations.py:32-38` 已有 `CoreLiveOperationOutcome`。
- `core/src/lamtools_core/app/live_operations.py:40-176` 已有 thread read/resume 和 turn start。
- `core/src/lamtools_core/app/live_operations.py:179-235` 已有 turn cancel。
- `core/src/lamtools_core/app/live_operations.py:238-284` 已有 queue create。
- `core/src/lamtools_core/app/turn_acceptance.py:35-90` 已有 turn acceptance plan。
- `core/src/lamtools_core/app/queue_state.py:35-84` 已有 queue payload/dispatch rules。

最小下沉接口：

- 把 Writer 的 live operations 改成 Core `LiveAgentOperations`，注入：
  - `TurnAdapter.create_user_turn(input_items) -> turn_id/user_item_id/runtime_text/visible_items/runtime_items`
  - `SessionAdapter.get_work_root(thread_id)`
  - `ApprovalAdapter.resolve(request_id, decision, guidance)`
- Core 负责 RPC response、snapshot load、notify/publish/runtime_start 形状。
- Writer 只负责把 input 持久化到自己的 transcript/session 表。

迁移风险：

- 中高。`turn.start` 当前同时创建 transcript turn 和 app-server events；需要保证幂等 client_message_id、attachment、queued dispatch 不丢。
- Approval continuation 会触发后续 runtime 调度，需保留 `was_open` 语义。

推荐优先级：P0。先迁移 read/resume/queue update/delete 低风险操作，再迁移 turn.start/approval。

## P1：Runtime lifecycle and task orchestration

精确位置：

- `members/writer/backend/app/app_server/runtime.py:40-73`
- `members/writer/backend/app/app_server/runtime.py:74-117`
- `members/writer/backend/app/app_server/runtime.py:118-141`
- `members/writer/backend/app/app_server/runtime.py:143-180`
- `members/writer/backend/app/app_server/runtime.py:198-275`
- `members/writer/backend/app/services/runtime_runner.py:88-184`
- `members/writer/backend/app/services/runtime_runner.py:292-365`
- `members/writer/backend/app/services/runtime_runner.py:400-450`

现有职责：

- 用 runtime task registry 防重复启动、注册后台任务、取消任务。
- 运行 Core kernel 并桥接 live events。
- 失败时生成 canonical error/status run item。
- 运行结束后做 finalization、terminal fallback、自动调度下一条 queue。
- approval resolve 后继续等待中的工具/引导。

为何不含 Writer 产品语义：

- 后台任务登记、cancel event、terminal fallback、queue-after-turn dispatch 是通用 Agent runtime lifecycle。
- Writer 特化项是 `service["run_turn"]`、transcript block 查询、checkpoint/review after-turn hook。
- `runtime_runner.py:145-158` 直接调用 Core kernel；Writer 只是在 Core kernel 外层做运行生命周期编排。

Core 现有可复用能力：

- `core/src/lamtools_core/runtime/__init__.py` 提供默认 runtime task registry。
- `core/src/lamtools_core/kernel/loop.py` / `CoreLoopKernel` 是核心运行循环。
- `core/src/lamtools_core/context_compaction.py` 已提供通用 compaction。
- `core/src/lamtools_core/app/default_agent.py` 已有 Core Agent app 的运行范式，可作为 service-side host 参考。

最小下沉接口：

- Core 提供 `AgentRunLifecycle`：
  - 输入：`thread_id`、`turn_id`、`user_item_id`、runtime input、work_root、model/runtime controls。
  - 注入：`run_kernel`、`input_context_loader`、`projection_sink`、`finalization_sink`、`after_turn_hooks`、`queue_dispatcher`。
- Writer 把 checkpoint/review 作为 `after_turn_hooks`，transcript final answer 作为 `finalization_sink`。

迁移风险：

- 高。它触及 live runtime、取消、失败恢复和 queue 串行调度。
- 建议在 P0 event/operation host 稳定后做，避免同时改变事件持久化和运行生命周期。

推荐优先级：P1。

## P1：CoreEvent / RunItem projection persistence and broadcast

精确位置：

- `members/writer/backend/app/services/runtime_fact_recorder.py:52-71`
- `members/writer/backend/app/services/runtime_fact_recorder.py:93-118`
- `members/writer/backend/app/services/runtime_fact_recorder.py:152-221`
- `members/writer/backend/app/services/runtime_fact_recorder.py:235-275`
- `members/writer/backend/app/services/app_projection_sink.py:19-70`
- `members/writer/backend/app/app_server/runtime_bridge.py:12-20`
- `members/writer/backend/app/app_server/runtime_side_effects.py:15-19`
- `members/writer/backend/app/app_server/runtime_side_effects.py:37-97`

现有职责：

- 接收 CoreEvent，转为 RuntimeProjectionInput。
- 合并增长中的 `runtime.part`。
- 写 Writer transcript。
- 转换为 RunItemEvent，持久化为 app events，广播给 hub。
- 对 artifact 和 approval request 做 side effect 落库。

为何不含 Writer 产品语义：

- CoreEvent、RunItemEvent、runtime.part、runtime.done、artifact、approval_request 都是 Agent runtime 协议事实。
- Writer 特化项只有 transcript sink 和 `WriterArtifact` / `WriterAppRequest` 的具体表。

Core 现有可复用能力：

- `core/src/lamtools_core/event/runtime_projection.py:31-70` 已有 projection input/buffer。
- `core/src/lamtools_core/event/runtime_projection.py:73-119` 已有 group/summary/payload preview。
- `core/src/lamtools_core/event/runtime_projection.py:204-218` 已有 RuntimeProjectionInput -> RunItemEvent。
- `core/src/lamtools_core/event/runtime_projection.py:221-420` 已覆盖 reply/tool/approval/usage/waiting/part 等映射。
- `core/src/lamtools_core/app/snapshot_store.py:66-68` 已能把 `core/runItem` 投进 snapshot。

最小下沉接口：

- Core 提供 `RunItemProjectionSink`：
  - `record_core_event(CoreEvent)`
  - `record_projection_fact(...)`
  - `publish_run_items(events, source_event_id)`
  - 可选 hooks：`on_transcript_fact`、`on_context_compaction`、`on_artifact`、`on_request`。
- Writer 保留 transcript/artifact/request row adapter。

迁移风险：

- 中高。历史上 final text truncation 和 preview/full_text 选择出过问题，迁移必须用完整文本、terminal event、snapshot 长度做回归。

推荐优先级：P1。

## P1：Approval and waiting-request continuation

精确位置：

- `members/writer/backend/app/app_server/approvals.py:16-61`
- `members/writer/backend/app/app_server/approvals.py:64-88`
- `members/writer/backend/app/app_server/approvals.py:91-158`
- `members/writer/backend/app/services/runtime_waiting_request.py:12-55`
- `members/writer/backend/app/services/runtime_approved_tool.py:20-130`
- `members/writer/backend/app/services/runtime_continuation_prompts.py:11-34`

现有职责：

- 存储 server-side approval request。
- 校验 approval decision。
- 追加 `approval_response` RunItemEvent 和 `serverRequest/resolved` app event。
- 将等待请求标记 completed，清理 runtime state 中 pending approval。
- 用户批准后执行等待工具，并生成继续 prompt。

为何不含 Writer 产品语义：

- approve/deny/guide、approval_response、pending approval、approved tool execution 是通用工具审批工作流。
- Writer 特化项是 waiting request 存储在 transcript block，以及 `ReadWriteToolExecutor(work_root)` 的当前实现位置。

Core 现有可复用能力：

- `core/src/lamtools_core/tool/approval_continuation.py:8-42` 已有 waiting decision normalization。
- `core/src/lamtools_core/tool/approval_continuation.py:45-75` 已有 continuation prompt。
- `core/src/lamtools_core/tool/default_toolbox.py:503-541` 已有 approval-gated tool preparation/execution。
- `core/src/lamtools_core/tool/approval.py` 已有 approval policy/gate。

最小下沉接口：

- Core 提供 `ApprovalContinuationCoordinator`：
  - `resolve_request(request_id, decision, guidance)`
  - `continue_waiting_request(thread_id, request_id)`
  - 注入 `ApprovalRequestStore`、`WaitingRequestStore`、`ToolExecutor`、`RunItemPublisher`。
- Writer 只实现 transcript-block backed `WaitingRequestStore`。

迁移风险：

- 高。错误迁移会导致用户批准后重复执行工具、无法继续、或丢失等待状态。
- 先迁移纯 decision normalization/response event 生成，再迁移 approved tool execution。

推荐优先级：P1。

## P1：CLI run-item formatting, watch loop, interactive decisions

精确位置：

- `members/writer/backend/writer_cli/app_server_client.py:8-33`
- `members/writer/backend/writer_cli/__main__.py:22-53`
- `members/writer/backend/writer_cli/__main__.py:101-266`
- `members/writer/backend/writer_cli/__main__.py:319-483`
- `members/writer/backend/writer_cli/__main__.py:497-555`
- `members/writer/backend/writer_cli/__main__.py:894-949`
- `members/writer/backend/writer_cli/__main__.py:975-995`

现有职责：

- App-server client endpoint adapter。
- 对 `core/runItem`、queue events、approval request、artifact、status/error 做 CLI 格式化。
- 判断 done/failed/waiting/resumed。
- 在 CLI watch/run 中处理 raw 输出、心跳、交互式 approval reply。

为何不含 Writer 产品语义：

- `core/runItem` 语义、watch until terminal、approval prompt 都是 Core Agent CLI 能力。
- Writer 特化只应是 endpoint path、client_info、默认 base URL、session/project 命令、少量显示标签。

Core 现有可复用能力：

- `core/src/lamtools_core/app/live_client.py:12-229` 已有 app-server websocket client。
- `core/src/lamtools_core/kernel/display.py:112-223` 已有 stateful display formatter。
- `core/src/lamtools_core/kernel/display.py:244-260` 起已有 CoreEvent -> CoreDisplayEvent 映射，但缺少 app event / RunItemEvent -> CLI line 的通用映射。
- `core/src/lamtools_core/cli.py:474-557` 已有 Core CLI parser/run summary，但不是 live app-server watch helper。

最小下沉接口：

- Core 提供：
  - `RunItemCliFormatter`：输入 app-server event dict，输出 lines/status。
  - `watch_app_server_turn(client, start_turn, options, prompt_decision)`：统一 run/watch/resume 的 raw、terminal、failed、approval loop。
  - `snapshot_chat_messages(snapshot)`：从 Core snapshot 提取 user/assistant 消息。
- Writer CLI 保留 project/session 命令和 endpoint adapter。

迁移风险：

- 中。主要风险是改变现有 CLI 输出文本，影响脚本/验收。
- 建议先保持 Writer 输出兼容，把现有 formatter 移到 Core，再由 Writer import。

推荐优先级：P1。

## P2：Runtime controls and capabilities catalog

精确位置：

- `members/writer/backend/app/services/runtime_capabilities.py:11-67`
- `members/writer/backend/app/services/runtime_capabilities.py:70-145`
- `members/writer/backend/app/services/subagent_config.py:11-23`
- `members/writer/backend/app/services/subagent_config.py:26-76`

现有职责：

- 合并 shared/core/writer/legacy runtime controls。
- 输出 agents、subagents、tools、command policies。
- 管理 project subagent definitions。

为何不含 Writer 产品语义：

- agent enabled/disabled、tool enabled/disabled、command policy、subagent definition 是通用 Agent capability surface。
- Writer 特化是 `WRITER_TOOLS`、`default_agent_registry()`、settings 中的默认 work_root 和 legacy namespace。

Core 现有可复用能力：

- `core/src/lamtools_core/agent.py:18-35` 已有 Core agent spec。
- `core/src/lamtools_core/agent.py:64-99` 已有 sub-agent prompt contract。
- `core/src/lamtools_core/tool/default_toolbox.py:352-401` 已有 default tool specs / model tool list。
- `core/src/lamtools_core/tool/default_toolbox.py:436-541` 已有 CoreToolbox、tool permissions、approval gate。
- `core/src/lamtools_core/tool/sub_agent.py` 已有 project sub-agent definition parsing/writing/deleting。

最小下沉接口：

- Core 提供 `RuntimeCapabilitiesService`：
  - 输入 member agent registry、member tool specs、namespace overlay 列表、work_root。
  - 输出稳定 `agents/subagents/tools/command_policies`。
- Writer 只传自己的 registry/tool list 和 legacy namespace。

迁移风险：

- 中。设置页依赖字段名；同时存在 legacy namespace，需要兼容迁移。

推荐优先级：P2。

## P2：Model routing and runtime LLM resolution

精确位置：

- `members/writer/backend/app/services/llm_config_service.py:13-23`
- `members/writer/backend/app/services/llm_config_service.py:86-128`
- `members/writer/backend/app/services/llm_config_service.py:131-170`
- `members/writer/backend/app/services/llm_config_service.py:173-234`
- `members/writer/backend/app/services/llm_config_service.py:237-254`
- `members/writer/backend/app/services/config_read.py:17-26`
- `members/writer/backend/app/services/config_write.py:21-24`

现有职责：

- 维护 model routing setting。
- 按 task type 解析 provider/model，支持 per-request model override。
- 删除模型后修复 routing state。
- 构造运行时 LLM client。

为何不含 Writer 产品语义：

- provider/model 配置、task-type routing、per-request model switch 是通用 Agent runtime 能力。
- `writer` 是当前 member 的默认 route key；`sub_agent` 已明显是通用 Agent 子任务 key。

Core 现有可复用能力：

- `core/src/lamtools_core/config/read.py` / `write.py` 已有 provider/model CRUD。
- `core/src/lamtools_core/config/operations.py:27-218` 已有 shared config operation catalog。
- `core/src/lamtools_core/llm` 已有 request/response、adapter profile、retry、shallow thinking 等通用 LLM 能力。

最小下沉接口：

- Core 提供 `ModelRouter(namespace, default_task_type, fallback_task_type, task_groups)`：
  - `ensure_state`
  - `set_route_model`
  - `resolve(task_type, model_id=None)`
  - `repair_after_model_delete`
- Writer 配置 `default_task_type="writer"`，`agent_task_type="sub_agent"`。
- `build_llm_client` 应迁到 Core 或 LLM adapter factory，Writer 只传 resolved config。

迁移风险：

- 中。需要兼容 `lamwriter.modelRouting` 旧 namespace 和 settings import-env 行为。

推荐优先级：P2。

## P2：App-server hub and websocket authorization guard

精确位置：

- `members/writer/backend/app/app_server/hub.py:12-39`
- `members/writer/backend/app/app_server/security.py:9-37`
- `members/writer/backend/app/app_server/router.py:11-23`

现有职责：

- 按 thread_id 管理 app-server event subscribers。
- 为 browser/desktop websocket 发 capability token。
- 校验 loopback origin + token。

为何不含 Writer 产品语义：

- 事件 hub 和 websocket guard 是 live app-server 基础设施。
- loopback/Vite/desktop 是部署模式，不是 Writer 业务。

Core 现有可复用能力：

- `core/src/lamtools_core/app/live_hub.py:12-45` 已有等价 `CoreAppEventHub`。
- `core/src/lamtools_core/app/live_router.py:73-84` 已有 live websocket router，但没有可选 auth guard。

最小下沉接口：

- Writer 直接用 `CoreAppEventHub`。
- Core live router 增加可选 `authorize(websocket) -> bool` 或 `LiveWebSocketAuthGuard`，Writer 注入 loopback/token 策略。

迁移风险：

- 低到中。Hub 替换简单；auth guard 需确认桌面、浏览器、CLI 三种入口都能取 token 或被允许。

推荐优先级：P2。

## P3：Operation catalog binding boilerplate

精确位置：

- `members/writer/backend/app/app_server/connection.py:122-160`
- `members/writer/backend/app/app_server/connection.py:162-233`
- `members/writer/backend/app/app_server/connection.py:235-263`
- `members/writer/backend/app/app_server/connection.py:711-753`
- `members/writer/backend/app/app_server/connection.py:843-895`
- `members/writer/backend/app/app_server/operations.py:306-458`
- `members/writer/backend/app/app_server/operations.py:2239-2245`

现有职责：

- 给 CoreLiveConnection 配 Writer adapter。
- 构造 operation catalog。
- 将大量 handler 机械绑定到 `OperationCatalog`。
- 对 outcome 执行 `_send`、notify、publish、runtime_start、continuation。

为何不含 Writer 产品语义：

- 绑定方式和 outcome 处理是通用 live operation 框架问题。
- Product 语义只在具体 handler 中；catalog 注册和 `_handler` 包装不应由每个 member 重写。

Core 现有可复用能力：

- `core/src/lamtools_core/app/live_router.py:51-70` 已有 `CoreLiveConnectionAdapter`。
- `core/src/lamtools_core/app/live_router.py:153-170` 已有 `send_operation_outcome`。
- `core/src/lamtools_core/app/operation_catalog.py:35-68` 已有 catalog execute。
- `core/src/lamtools_core/app/operation_groups.py` 已有 operation grouping。

最小下沉接口：

- Core 提供 `build_live_operation_catalog(core_handlers, member_overlay_handlers)` 的 handler-to-RPC bridge。
- Core 提供 declarative registration：`{"turn.start": handler, ...}`，避免 Writer 长参数列表。
- Writer 只导出 overlay handler map。

迁移风险：

- 低。功能风险小，主要是重构噪音大；建议在 P0/P1 后顺手清理。

推荐优先级：P3。

## 推荐迁移顺序

1. P0 event/snapshot host：先把 ledger/snapshot/event_store/hub 的通用包装收进 Core，但保持 Writer DTO 和协议版本兼容。
2. P0 live operations：先替换 thread read/resume、queue update/delete，再替换 queue create/turn steer，最后替换 turn start/approval respond。
3. P1 projection sink：把 `RuntimeFactRecorder` 的 CoreEvent -> RunItem -> app event 发布链路下沉，Writer 保留 transcript/artifact/request adapters。
4. P1 runtime lifecycle：Core 接管 task registry、failure status、terminal fallback、queue-after-turn；Writer after-turn hooks 保留 checkpoint/review。
5. P1 CLI watch：先移动现有 formatter 保持输出兼容，再让 Writer CLI 使用 Core watch helper。
6. P2 capabilities/model routing/security：作为后续瘦身项推进。

## 未确定点

- `session/rollback_turn` 和 legacy `turn/started` 是否仍有真实历史事件需要重放；这决定 reducer 下沉时保留兼容分支的位置。
- 前端是否依赖 snapshot 同时存在 outer `items/turns` 与 nested `core.items/core.turns`；CLI 当前也合并两者。
- approval continuation 当前通过 transcript block 查找唯一 waiting request；Core 下沉前需要确认是否应以 app request row 作为权威等待源。
- model routing 是否继续保留 `lamwriter.modelRouting` namespace，还是迁移为 Core namespace + Writer overlay。
