# 01 live 协议体系 审计报告

## 1. 概况

本区审计 live 协议/路由/审批体系，共 8 个模块约 4941 行：`live_operations.py`（2691 行，核心业务：turn/queue/approval/compact 各操作处理器与后台运行时任务）、`live_router.py`（656 行，WebSocket JSON-RPC 路由、事件下发与 runItem 合并）、`live_client.py`（397 行，Python 客户端）、`cli_live.py`（824 行，CLI watch/format 层）、以及 `live_hub.py`、`live_approval.py`、`live_protocol.py`、`live_member.py`。整体架构成熟度高：写路径统一经 `SQLiteWriteCoordinator` 全局锁 + BEGIN IMMEDIATE 串行化，turn.start 在锁内做快照守卫 + 注册表 claim + client_message_id 去重；事件流采用持久化（全量 content）与瞬时（delta，seq=0 不落库）双通道，路由端 20ms 窗口合并 + 前端 rAF 合并 + `_coalesced_event_ids`/`seen_event_ids` 双端去重，是经过实测（56MB 线程、~2500 msg/s）的扎实方案；启动收割（`recover_stale_active_turns`）、`turn.force_reset` 逃生舱、运行时状态乐观重试等恢复路径完备。主要问题集中在：等待审批的 turn 会被误标为 completed 导致队列在未获批准时自动派发（S1）、`turn.start` 忽略 `include_snapshot:false` 使 UI 的 56MB 快照规避失效（S2）、CLI watch 同一会话只能提示一次审批（S2）。

## 2. 问题清单

- **[S1] `_ensure_turn_terminal` 将等待审批（waiting）的 turn 误写为 completed，导致队列未获批准即自动派发、双 turn 并发执行**
  - 位置：`core/src/lamtools_core/app/live_operations.py:1835-1878`（判断 1847-1856，写 terminal 1865-1866）
  - 问题：turn 因审批暂停时，kernel 以 decision="wait" 返回（`default_agent.py:613` status="ok"），快照线程状态为 "waiting"。`_ensure_turn_terminal` 的守卫只排除 `{"completed","idle"}`，`latest_active_turn_id` 视 "waiting" 为活动 turn 且等于本 turn，于是在**审批尚未发生**时写入 `status="completed"` 的终端事件；随后 `_dispatch_next_queue_item`（1881-1984）读到 completed 状态，把下一个排队项派发成新 turn。
  - 影响：① 线程在等待审批时 UI 显示 turn 已完成；② 排队项在用户批准前被自动执行，队列"无批准自放行"；③ 新旧两个 kernel 在同一线程并发执行，新 turn 的审批流程会覆盖 `pending_approval`，旧请求变为 "approval request mismatch" 无法回答；④ 用户批准旧请求时 `decision_durable` 的 `accept_run` 会因新 turn 已占 run 而抛 "approval continuation runtime claim failed"——此时决策已持久化但工具未执行，审批被消费且无法重试（default_agent 侧报 "no pending approval"）。触发条件：线程存在排队项 + turn 进入审批等待。
  - 修复建议：在写 terminal 前校验该 turn 自身已处于终端状态（如 `_turn_is_terminal(snapshot, turn_id)` 为真或检查最近的 turn 级 status 事件），并在 `effective_thread_status` 处于 "waiting" 时直接返回；`_ensure_turn_terminal` 的语义应限定为"兜底补写真正的终端状态"，绝不能把 waiting 当作完成。

- **[S2] `turn.start` 忽略 `include_snapshot:false`，每次响应都携带完整快照**
  - 位置：`core/src/lamtools_core/app/live_operations.py:686-697`（响应无条件含 `"snapshot": snapshot`）；对比 `command.execute`（131 行）、`turn.cancel`（861/909 行）均会判断该参数
  - 问题：桌面 UI 明确传 `include_snapshot: false` 以规避大线程 56MB 快照的 JSON.parse 主线程卡顿（`core/ui/src/appServer/store.ts:246-256` 注释明言 "Skip it — callers can override"），但服务端从未读取该参数，快照照发不误。
  - 影响：UI 声称规避的 ~1s 主线程 stall 实际每次 turn/start 都发生；客户端意图与服务端行为不一致，属于协议契约破损。
  - 修复建议：在 `handle_turn_start_operation` 的响应构建处按 `params.get("include_snapshot") is not False` 决定是否带 snapshot（与 command.execute 一致）；注意事件流已含 turn/accepted 等事件，快照仅用于断线补齐。

- **[S2] CLI watch 同一会话只能提示一次审批，后续审批请求被静默跳过导致会话挂起**
  - 位置：`core/src/lamtools_core/app/cli_live.py:366-382`（`approval_prompted` 置位/复位逻辑）；`is_resumed_event` 712-714（仅匹配 method=="serverRequest/resolved"）
  - 问题：`approval_prompted` 只在 `is_resumed_event` 命中时复位，而全仓库没有任何代码发出 `serverRequest/resolved` 事件（grep 确认仅 `cli_live.py` 与 `snapshot_store.py:75` 投影分支引用，无生产者）；真实的"审批已处理"信号是 kind=`approval_response` 的 run item（`event/runtime_projection.py:380-400` 生成），与检查的 method 不一致。因此在一次 watch 会话中第二次及以后的 `approval_request` 到达时 `approval_prompted` 恒为 True，被 `continue` 静默丢弃，不提示、不回复，turn 永久停在等待审批（只能等 event_timeout 或 Ctrl-C）。断线重连回放 approval_request 同样不提示（标志未复位）。
  - 影响：多步工具调用且 approval_policy=require 的真实会话中，第二个工具调用起全部静默挂起，用户无任何提示。
  - 修复建议：将复位信号改为检测 kind==`approval_response` 的 run item（或响应 approve 后显式复位），并顺带在重连回放审批请求时重置标志（可结合 respond 是否成功）。

- **[S2] 审批续跑任务异常无人观察，决策已持久化但工具未执行，turn 卡死且审批无法重试**
  - 位置：`core/src/lamtools_core/app/live_operations.py:1184-1203`（`asyncio.wait` 早退）；`decision_durable` 1120-1136
  - 问题：`asyncio.wait({decision_ready, task}, FIRST_COMPLETED)` 在 `decision_ready` 先完成时立即返回并丢弃对 `continue_approval` 任务的引用，后续该任务抛出的任何异常（典型如 `decision_durable` 中 `accept_run` 失败抛 "approval continuation runtime claim failed"、或成员侧续跑异常）都只会产生 "Task exception was never retrieved" 日志，无任何终端对账。此时 `ApprovalResolutionLifecycle.persist_decision` 已把审批状态置为 resolved/executing（`app/approval_resolution.py:65-73`），工具不会执行，用户重试会得到 "approval already resolving"/"no pending approval"。
  - 影响：审批被消费但动作未执行、turn 状态卡死（用户可见为"审批已通过但什么都没发生"）。
  - 修复建议：为 `continue_approval` 任务挂 done-callback，异常时走 `_persist_cancelled_terminal`/`_fail_runtime_start` 对账并记日志；或把 wait 改为同时等待 task 失败并在早退时保留对任务的显式持有与异常处理。

- **[S3] Python 客户端 `_seen_event_ids` 无上限增长**
  - 位置：`core/src/lamtools_core/app/live_client.py:36,293-299`
  - 问题：`put_app_server_event` 对每个含 event_id/seq 的事件都记入 `_seen_event_ids`，永不清理；同一实现的前端在 200k 处有清空兜底（`core/ui/src/appServer/store.ts:177-179`），Python 侧没有。
  - 影响：长驻连接（`core_cli watch`、长会话）内存随事件数线性增长（数千万事件可致数百 MB）。
  - 修复建议：与前端一致，超过阈值（如 20 万）时清空或改用有界结构；清空后由 thread/resume 与快照去重兜底。

- **[S3] `CoreAppServerClient.close()` 不解除在途请求的 pending future**
  - 位置：`core/src/lamtools_core/app/live_client.py:273-285`（close 只 `_reader.cancel()`）；对比 `_read_loop` 自然断开路径 347-350 会为所有 pending future `set_exception`
  - 问题：主动 `close()` 时取消 reader 但不 fail `_pending` 中的 future，正在 `await request()` 的调用方将永远挂起（只能靠外部取消）；且残留条目不再回收。
  - 影响：任何"关闭期间仍有请求在飞"的调用（如竞态下的 `respond_approval`/`execute_command`）会静默挂死。
  - 修复建议：close 时遍历 `_pending`，对未完成 future `set_exception(RuntimeError("app-server connection closed"))` 后清空。

- **[S3] 重连期间实时瞬时 delta 与 resume 回放事件存在入队乱序，UI/CLI 内容短暂错乱**
  - 位置：`core/src/lamtools_core/app/live_client.py:313-329`（`_resume_thread` 回放）+ `_read_loop` 334-350；前端消费 `core/ui/src/appServer/store.ts:537-556`；CLI 消费 `cli_live.py:101-135`
  - 问题：`connect()` 中 `initialize` 先建立订阅（router 侧 `live_router.py:555-556`），随后才发 `thread/resume`。resume 请求在途期间 hub 推送的瞬时 delta（seq=0，不落库）可能先于 resume 响应中的回放事件进入 `_events` 队列；由于回放事件由 `_resume_thread` 在响应返回后才入队，而 `_read_loop` 并行消费，二者顺序无保证。前端对 content 事件是整体替换（`item.content = content`），先到的 delta 会被随后到达的旧 content 覆盖；CLI 的 `content.startswith(streamed)` 前缀去重也会因顺序反转输出截断乱码。
  - 影响：断线重连恰逢流式输出时，UI/CLI 短暂显示缺字或乱码，直到下一条完整 content 事件（约 128 字符阈值或 turn 结束）自愈。
  - 修复建议：`_resume_thread` 把回放事件放入队列时与实时事件串行化（如 resume 期间先缓存实时事件，回放入队后再放行），或按 seq 排序后入队。

- **[S3] 路由层对非 JSON/畸形帧无容错，坏帧直接杀死连接**
  - 位置：`core/src/lamtools_core/app/live_router.py:187-192`
  - 问题：`websocket.receive_json()` 对非法 JSON 抛 `json.JSONDecodeError`，`run()` 循环只捕获 `WebSocketDisconnect`；未初始化阶段坏帧还会在 `_handle_raw` 内联 await 处直接抛出终止整个连接。
  - 影响：单个畸形帧即可断连（客户端被迫走重连），与 JSON-RPC 应返回 -32600 的语义不符。
  - 修复建议：捕获 `(ValueError, json.JSONDecodeError)` 并回 `rpc_error(-32600)`；非 dict 帧同样处理。

- **[S3] `_sender` 任务异常未捕获，仅产生任务异常日志噪声**
  - 位置：`core/src/lamtools_core/app/live_router.py:223-226`
  - 问题：`send_json` 在对端断开时抛异常，`_sender` 无 try/except，异常以 "Task exception was never retrieved" 形式被丢弃（主循环随后靠 receive_json 断开才清理）。
  - 修复建议：在 `_sender` 内捕获异常并 break（或转由主循环统一清理）。

- **[S3] `_auto_title_session` 后台任务 fire-and-forget，不跟踪不取消**
  - 位置：`core/src/lamtools_core/app/live_operations.py:598-605,1552-1616`
  - 问题：`loop.create_task(_auto_title_session(...))` 创建后不持有引用、不注册、不取消；服务关停时出现 "Task was destroyed but it is pending"；同一线程连续两条首消息会生成两个并发 title 任务（虽都有 `is_default_title`/`only_if_title_default` 保护，但双次 LLM 调用浪费）。
  - 修复建议：在连接/服务器生命周期持有任务集合并于 shutdown 时统一 cancel+gather；或在任务内尽早快速失败。

- **[S4] 线上事件流 protocol_version 字符串不一致，且客户端不校验版本**
  - 位置：`core/src/lamtools_core/app/event_store.py:77`（默认 `"core.agent.v1"`）、`live_protocol.py:9`（`"core.app_server.v1"`）、`live_operations.py:2518` 与 `default_agent.py:1782`（瞬时事件硬编码 `"core.app_server.v1"`）
  - 问题：持久化信封带 `core.agent.v1`，瞬时流式事件带 `core.app_server.v1`，同一连接内两种版本串行混发；`initialize` 响应返回 `protocolVersion` 但 Python 客户端与前端均不校验。
  - 影响：目前无实际破坏（无版本门控），但为协议演进埋雷，且字段语义无法依赖。
  - 修复建议：统一由 `PROTOCOL_VERSION` 常量注入 event store 的 protocol_version；客户端在 initialize 后校验并显式拒绝不兼容版本。

- **[S4] `_handle_core_client_response`（id+result 帧→approval.respond）与前端 `{id,method}` 服务端请求分支均为遗留死路径**
  - 位置：`core/src/lamtools_core/app/live_router.py:107-146`；前端 `core/ui/src/appServer/client.ts:133-143,118-124`
  - 问题：Python 服务端从不发送带 `id`+`method` 的服务端请求帧（grep 无产出），前端 `serverRequestIds`/`respondServerRequest` 永不触发；相应地服务端 `_handle_core_client_response` 把任意含 `id`+dict`result` 的帧当作 approval.respond——该路径在无 `host` 时以 `request_id=raw.id` 执行审批（112 行 `setdefault("request_id", ...)`），语义脆弱且无鉴权边界。
  - 影响：死代码增加维护与安全审查负担；若未来旧客户端沿用该路径，`request_id` 语义与 `approval.respond` RPC 不一致。
  - 修复建议：删除两端遗留路径，或显式声明兼容并补充测试与鉴权。

- **[S4] 队列派发后进程崩溃：排队输入永久丢失**
  - 位置：`core/src/lamtools_core/app/live_operations.py:2140-2242`（`recover_stale_active_turns`）+ `queue_state.py:244-264`（`next_dispatchable_queue_item` 只认 status=="queued"）
  - 问题：`_dispatch_next_queue_item` 的 `queue/itemDispatched` + `turn/accepted` 已落库但 `_start_runtime_task` 未及启动时进程崩溃，重启后收割器只写 cancelled 终端，queue 项状态保持 "dispatched"，永远不再派发。
  - 影响：崩溃窗口内的排队输入不会执行，且 UI 无提示（用户消息仍在时间线，但无回复）。
  - 修复建议：收割器对"dispatched 且对应 turn 无终端"的项恢复为 "queued"（幂等：若 turn 已 terminal 则维持）。

- **[S4] queue.create/steer 等操作的 client_message_id 幂等键客户端不可控，超时重试会产生重复项**
  - 位置：`core/src/lamtools_core/app/live_operations.py:1238`（queue.create 服务端生成 id）、`live_client.py:100-101,137-145`（每次调用新 uuid）
  - 问题：服务端去重（`find_client_event`）只有在客户端重试时复用同一 `client_message_id` 才生效；`create_queue_input` 客户端不传、CLI 无对应参数，超时后的重试必然新建重复 queue 项（`turn.start` 有 `--client-message-id` 可传，queue.create 没有）。
  - 修复建议：为 CLI queue 子命令暴露 client_message_id，或由客户端在构建时固定生成并透传。

- **[S4] 审批无服务端超时，pending approval 可永久等待**
  - 位置：`core/src/lamtools_core/app/default_agent.py:707-769`（claim 循环无超时）、`live_operations.py:1107-1216`
  - 问题：服务端对 pending approval 无任何超时/过期路径（客户端 event_timeout 只是断连），长时间无人应答时 runtime 状态永久 waiting，占用注册表与状态。
  - 修复建议：如产品接受超时，可在 kernel wait 或 approval_respond 处加超时并写 cancelled 终端；否则应在文档中明确为有意设计。

- **[S4] 并发 RPC 下订阅切换存在竞态**
  - 位置：`core/src/lamtools_core/app/live_router.py:196-198,421-423`（每个已初始化请求独立 task，`_subscribe` 互踩 `self.thread_id/self.subscription`）
  - 问题：单连接并发操作不同 thread（多线程工作台场景）时，后到的订阅会覆盖先前的，hub 事件可能发到与 RPC 不一致的订阅。
  - 影响：单线程 UI 实际低风险；多线程场景事件错投。
  - 修复建议：订阅切换放入连接级串行队列或仅在 `_hub_reader` 单点切换。

- **[S4] 其他小项**
  - `CoreAppEventHub` 模块级单例（`live_hub.py:69`）：同进程多实例（测试/嵌入场景）同 thread_id 事件串扰。
  - `CliLiveFormatter._streamed_message_text`（`cli_live.py:74`）按 item_id 无界累积。
  - 前端 `receivedEventIds` 达 20 万后整体清空（`core/ui/src/appServer/store.ts:177-179`），清空后重放事件可能被重复应用（下次快照会整体替换兜底）。
  - `handle_queue_update_operation`（`live_operations.py:1289-1371`）无 client_message_id 去重，重复请求产生重复 itemUpdated 事件（投影幂等，仅日志噪音）。

## 3. 该区 Top 3 问题

1. **等待审批的 turn 被误标 completed，队列在未批准时自动派发并双 turn 并发**（S1，live_operations.py:1835-1878）——直接破坏审批语义与单 turn 状态机，是本区最严重缺陷。
2. **`turn.start` 忽略 `include_snapshot:false`**（S2，live_operations.py:686-697）——与 UI 显式优化意图相反，大线程每次 start 仍全量返回快照。
3. **CLI watch 审批提示只触发一次**（S2，cli_live.py:366-382）——多审批会话静默挂起，用户无任何反馈。

## 4. 亮点

1. 写路径设计严谨：`SQLiteWriteCoordinator` 进程级锁 + BEGIN IMMEDIATE + 退避重试，turn.start 在锁内完成"快照守卫→注册表 claim→materialize→batch 落库"，配合 `find_client_event` 幂等去重，双客户端并发 start 不会双执行（live_operations.py:478-589, sqlite_write.py:61-78）。
2. 流式性能工程成熟：瞬时 delta（seq=0）与持久化事件双通道、路由 20ms 合并窗口 + `_coalesced_event_ids` 去重、前端 rAF 合并与 `shouldHydrateSnapshot` 增量判定（store.ts:685-702），并有 56MB 线程的实测数据支撑，事件顺序在单连接内严格保持。
3. 崩溃恢复体系完整：启动收割 `recover_stale_active_turns`（含 50 事件防跑飞守卫）、`turn.force_reset` 逃生舱、`_persist_cancelled_runtime_state` 对 `RuntimeStateConflictError` 乐观重试（5 次），注释明确记录了 2b34c636 死锁教训与修复动机。
4. 审批并发防护到位：`ApprovalResolutionLifecycle` 强制 claim→durable decision→continue→durable terminal 顺序，成员侧以 status="executing" + 冲突重试防止并发批准（default_agent.py:727-768），`decision_durable` 在注册表中登记续跑任务以延续 run 生命周期。

## 5. 审计范围与方法

- 范围：`core/src/lamtools_core/app/` 下 live_operations.py、live_router.py、live_client.py、live_hub.py、live_protocol.py、live_approval.py、live_member.py、cli_live.py（合计 4941 行）；交叉核对支撑模块 event_store.py、persistence_host.py、snapshot_store.py、queue_state.py、turn_acceptance.py、sqlite_write.py、approval_resolution.py、default_agent.py、runtime/__init__.py、kernel/loop.py、event/runtime_projection.py、tool/approval_continuation.py，以及消费者 `core/ui/src/appServer/`（client.ts、store.ts、protocol.ts）与 `cli.py` 的 live 子命令。
- 方法：全程只读。逐文件精读两端（服务端路由/操作 vs 客户端解析/前端 store）的协议假设与 payload 字段；对消息形状、事件名、seq/去重键做两端对照；追踪 turn/queue/approval 的完整生命周期与异常路径；核对并发路径（注册表 claim/release、写锁、hub 订阅、asyncio 任务生命周期）；grep 验证死代码与事件生产者（如 "serverRequest/resolved"、"ping"、`{id,method}` 帧）确实不存在；每条发现均定位到 file:line 并评估用户可见影响。
