# 02 Agent 生命周期 审计报告

- 审计区：02（Agent 生命周期与编排）
- 审计日期：2026-08-13
- 审计方式：只读代码走查（未运行测试、未启动服务、未修改任何代码文件）
- 相对路径均相对于仓库根 `E:\LamTools`，源码位于 `core/src/lamtools_core/`。

## 1. 概况

本区覆盖 Agent 从"接收用户输入"到"终端落盘"的完整生命周期：主循环（`kernel/loop.py` 的 `CoreLoopKernel._run`，3398 行）、策略（`kernel/policy.py`）、Kit 契约（`app/base_agent.py`）、装配层（`app/default_agent.py` 的 `create_core_agent_operations`，1990 行）、子代理（`tool/sub_agent_runner.py`、`sub_agent.py`、`sub_session.py`）、审批恢复（`app/approval_resolution.py`）、任务注册表与取消（`runtime/__init__.py` 的 `RuntimeTaskRegistry`）、以及 live 层编排（`app/live_operations.py` 的 turn.start / turn.cancel / turn.force_reset）。

总体评价：**生命周期框架整体健壮**。取消路径经过 2b34c636 事件的重构后已相当完整——`task.cancel()` 强制取消、协作式 cancel 事件、`asyncio.shield` 保护终端持久化、注册表 + 快照双重"活跃 turn"守卫、启动期 `recover_stale_active_turns` 收割机、`ApprovalResolutionLifecycle` 的 claim→durable→continue→terminal 顺序约束，都是高质量设计。审批解决路径（`approval_resolution.py`）对状态冲突做了乐观重试 + 只合并自有 metadata key，严谨。

主要问题集中在三处：**子代理并行执行的会话竞态**（S2）、**取消/异常逃逸路径不经过统一的终端收敛**（S2）、**若干性能与健壮性次要点**（流式失败整段重放、state.metadata 无界增长 + 每步深拷贝、事件实时持久化失败杀死整个 turn 等）。

## 2. 问题清单

### [S2] 1. 并行调用同名字代理时共享同一子会话，无串行化导致状态/历史竞态
- 位置：`core/src/lamtools_core/app/default_agent.py:145`（`parallel_tool_names=("sub_agent",)`）；`core/src/lamtools_core/kernel/loop.py:765-770, 771-803, 2604-2621`（`can_parallelize_named_tools` 与 `_execute_tools_parallel`）；`core/src/lamtools_core/tool/sub_agent_runner.py:231`（`"session_id": f"{self.session_prefix}:sub:{agent_name}"`）。
- 问题：主循环默认允许同一轮内多个 `sub_agent` 工具调用并行执行（`parallel_tool_names=("sub_agent",)`，且当一轮所有工具都是 sub_agent 时 `can_parallelize_named_tools=True`）。子会话 ID 仅由 `{thread}:sub:{agent_name}` 决定——模型若在同一轮发出两个同名 `agent` 的子代理调用（工具说明中"每个 name 是可复用会话"，模型完全可能对同一 name 发两个任务），两个 `CoreLoopKernel._run` 将并发读写同一个子会话：同时 `append_history`、同时 `save`。
- 影响：SQL 状态存储（`app/core_db.py:487,504`）的 revision 冲突检测会让其中一个子代理以 `RuntimeStateConflictError` 失败（被 `kernel/loop.py:1158-1164` 吞成 "Unexpected error: …" 决策 failed）；内存存储（`runtime/__init__.py` 的 `InMemoryRuntimeStateStore`）则无冲突检测，两个会话的历史行交错写入，该 name 的可复用会话历史被静默污染，后续同 name 调用会读到串台内容。表现为偶发子代理失败或子会话历史错乱。
- 修复建议：并行分支按 `agent` 名去重/串行化——同轮内同名 `agent` 的调用改为顺序执行（或排队），仅对 `agent` 名互不相同的调用并行；也可在 `KernelSubAgentRunner` 内按 session_id 加 per-session asyncio 锁。

### [S2] 2. 取消路径（task.cancel）跳过 on_run_end / Stop hook / 终端事件，与正常路径收敛点不一致
- 位置：`core/src/lamtools_core/kernel/loop.py:288-296`（`run()` 的 CancelledError 分支）与 `1221-1236`（`_persist_external_cancellation`）；对比正常路径 `1202-1209`（on_run_end → Stop hook → terminal event → end_span）。
- 问题：外部强制取消（`RuntimeTaskRegistry.cancel(..., force=True)` → `task.cancel()`）时，`CoreLoopKernel.run` 只把 `state.status="cancelled"` 落盘并清除 pending_approval/pending_waiting_request，**不调用 `kit.on_run_end`、不触发 Stop hook（`_apply_session_stop_hook`，含 dreaming）、不发出 `runtime.cancelled` 终端事件、不关闭 tracer run_span**。正常退出路径的这三个收敛点在取消路径全部缺失。
- 影响：依赖 Stop hook 做收尾（如插件清理、会话记忆落库、观测上报）的产品逻辑在用户点击 Stop 时静默不执行；`runtime.cancelled` 事件不产生，依赖事件流的消费者（审计/前端非 live 路径）看不到取消；live 层虽由 `_persist_cancelled_terminal`（`app/live_operations.py:2048`）补写了快照侧事件，但 kernel 侧收敛仍不一致，且非 live 调用方（如 CLI 直连 kernel 的路径）完全缺失。tracer run_span 在取消时泄漏（默认 NoopTracer 无实害，但接入真实 tracer 后每次取消泄漏一个 span）。
- 修复建议：把"kit.on_run_end + Stop hook + terminal event + end_span"抽成 `_finalize_run(state, result)`，在正常路径与取消路径（shield 保护下）统一调用；tracer span 用 try/finally 保证关闭。

### [S3] 3. 主循环 try 之外的异常使 RuntimeState 卡死在 "running"，且无 kernel 侧终端事件
- 位置：`core/src/lamtools_core/kernel/loop.py:420-466`（mark running、`kit.on_run_start`、SessionStart hook、`_append_history_checkpoint`、UserPromptSubmit hook、`runtime.started` 事件发射均在 `484` 行 try 之外）与 `1180-1209`（循环后的 `_replace_history_checkpoint`、on_run_end、Stop hook、terminal event 亦无保护）；`core/src/lamtools_core/app/default_agent.py:536-591`（`kernel.run` 只包了 `finally` 关 MCP registry，无异常收敛）。
- 问题：`_run` 只在每步循环体内 catch 异常（`loop.py:1148-1164`）。状态存储写入失败（DB 锁）、`runtime.started` 实时持久化失败、hook 引擎以外任一步骤抛错，都会让异常逃出 `_run`（`run()` 的 CancelledError 分支不处理普通异常），此时 `state.status="running"` 已持久化，之后没有任何代码把该状态改为 terminal。
- 影响：运行中的 run 状态残留 "running"。live 层 `_run_core_turn`（`app/live_operations.py:1811-1832`）会补写快照侧 failed 事件，用户能看到失败，但运行时状态存储（`CoreRuntimeSession`）停留在 "running" 直到下一次 turn.start 覆盖或进程重启（`recover_stale_active_turns` 只对快照侧收割）；期间的 `turn.cancel`/状态查询会看到矛盾状态。
- 修复建议：在 `_run` 的 mark-running 之后包一层 try/finally（或扩展 `run()` 的 except），对逃逸异常统一走"状态置 failed + 尽力持久化 + 重抛"的收敛路径，与 S2 的 `_finalize_run` 合并实现。

### [S3] 4. turn_start 末尾 `_persist_run_items` 失败把已完成的 run 报为错误
- 位置：`core/src/lamtools_core/app/default_agent.py:599-607`（`kernel.run` 成功返回后调用 `_persist_run_items`，无 try 保护）。
- 问题：`kernel.run` 已正常完成（状态已 terminal、live 事件已逐条落库），仅最后批量持久化 run_items/快照失败（DB 锁、连接中断）时异常直接逃出 `turn_start` → `_run_core_turn` 的 `except BaseException` → `_fail_runtime_start` 写入 **failed** 终端事件。
- 影响：用户看到"本轮失败"，但模型实际已完成全部工作且事件已存在——成功结果被报为失败，且后续 `_ensure_turn_terminal` 不会再纠正为 completed。与 S2/S3 同源的"持久化失败即整体失败"策略问题，此处后果是误报。
- 修复建议：`_persist_run_items` 包 try/except，失败时降级为 `core_events_to_snapshot`（内存快照）并仍返回 status="ok"，把持久化失败记入日志/结果 metadata 而非翻转整轮结果。

### [S3] 5. 流式失败整段回退非流式重放：双倍 token 消耗 + 超长重试窗口
- 位置：`core/src/lamtools_core/kernel/loop.py:1741-1751`（`_stream_model` 的 `except Exception: return None` 与 `ModelRetryExhausted` 回退）、`524-525`（回退后 `_call_model` 全量重放）、`1812-1816`（`_next_stream_event` 120s 空闲超时）；`core/src/lamtools_core/kernel/policy.py:17,22`（`model_timeout_seconds=360`、`model_retries=100`）。
- 问题：流式调用在**任意**异常（含超时、Provider 中断）下丢弃已累积的流内容，回退到 `complete_with_retry` 整段重发，重试上限 `model_retries=100` 次、每次最长 360s。即：一次流式失败 = 已流出的 token 作废 + 最多 100×360s 的非流式重试。
- 影响：Provider 短暂故障时单步最坏可挂约 10 小时（流式侧 100 次 setup 重试后仍失败，再进非流式 100 次）；正常场景每次流中断多付一次完整响应的 token 费用。流式已输出的半截内容在 UI 上是"流式响应中断"占位，随后整段重出，体验与成本双输。
- 修复建议：回退前评估已累积内容（有实质内容且无 tool_calls 时直接用累积内容构造 response）；回退重试上限与流式侧共用且显著收敛（如 3-5 次）；流式 idle 超时后先尝试续流而非整段重放。

### [S3] 6. state.metadata 无界增长 + 每步深拷贝，长 run 呈 O(n²)
- 位置：`core/src/lamtools_core/kernel/loop.py:478`（每步 `state_before=self._copy_state(state)`）与 `2623-2632`（`_copy_state` 对 `metadata` 整体 `deepcopy`）、`1136-1138`（`persist_steps` 默认 True 时每步向 `state.metadata["kernel_steps"]` append，从不裁剪）；`core/src/lamtools_core/app/base_agent.py:798-813`（`written_files` 每次写文件 append，跨 run 累积、无上限）；`core/src/lamtools_core/kernel/policy.py:76`（`persist_steps: bool = True`）。
- 问题：`kernel_steps` 随步数线性增长且每步 `_copy_state` 深拷贝整个 metadata（含 kernel_steps、written_files、evidence 等）→ 单 run 总成本 O(n²)；`written_files` 跨 run 持久化在会话 metadata 里（每个 checkpoint 都整体写库）。
- 影响：长任务（几十~上百步、大量写文件）时每步的深拷贝与 `_save_checkpoint` 序列化开销显著放大，且最终状态体积膨胀（一个会话跑完可能携带数百条 written_files 记录进下个 run 的每次请求构建）。
- 修复建议：`_copy_state` 改为浅拷贝 metadata（step 只读引用即可，KernelStep 本身不修改旧 metadata）；`kernel_steps` 与 `written_files` 设上限（如保留最近 64 条/按 run 隔离，run 结束时折叠为摘要）。

### [S3] 7. 事件实时持久化（live_callback）失败直接杀死整个 turn
- 位置：`core/src/lamtools_core/app/default_agent.py:1767-1826`（`_persist_core_event_live` 每次非 transient 事件一个 DB 事务，异常直接上抛）；`core/src/lamtools_core/kernel/loop.py:1158-1164`（循环内 `event_sink.emit` 异常被兜成 "Unexpected error" → 整轮 failed）。
- 问题：流式/工具执行过程中任一事件的 DB 落库失败（SQLite 锁、IO 抖动）会沿 `CollectingEventSink.emit → kernel 各 emit 点` 冒泡，最终整轮 run 被判 failed——即使模型与工具本身全部成功。
- 影响：一次瞬态 DB 故障 = 整轮用户可见失败 + 已执行工具的工作被废弃重来；且"事件持久化"是旁路职责，不应决定 agent 主流程成败。
- 修复建议：`_persist_core_event_live` 内部包 try/except（记录日志、事件不落库但继续跑），终端事件（done/failed/waiting）保留强一致路径——实时旁路失败不应中断主循环。

### [S3] 8. agent_app.run_turn（非 LLM 客户端路径）无异常处理，模型异常时 session 卡 "running"
- 位置：`core/src/lamtools_core/app/agent_app.py:95-184`（`_ensure_session` 建 session 时 status="running"，`_generate` 失败无 try/except，`session.status="completed"` 只在成功末尾执行）。
- 问题：当 `model_provider` 不是 LLM 客户端（走 `AgentApp.run_turn` 的 fallback 路径）时，`_generate` 抛异常 → `run_turn` 直接上抛，用户消息已入 store，session 状态永远停留在 "running"，无任何终端事件。
- 影响：该路径（旧式 ModelProvider 适配）下一次调用会看到僵尸 running 会话；状态机缺失完整转换。当前 live 主路径不走这里，但作为公开契约仍是缺陷。
- 修复建议：`run_turn` 用 try/finally 保证异常时写入 failed 终端事件并把 session 置为 "failed"（或与 kernel 路径一样统一收敛）。

### [S4] 9. sub_session.py 整模块死代码，且与 runner 的子会话 ID 格式不一致
- 位置：`core/src/lamtools_core/sub_session.py:29-128`（`SubSessionManager`、`SubSessionRuntimeStateStore`）与 `138-149`（`filter_sub_agent_tools`）。
- 问题：全仓库 grep 确认这三个类/函数除定义外零引用（live 路径与 `default_agent.py` 均通过 `KernelSubAgentRunner` 生成 `{prefix}:sub:{name}` 形式的会话 ID，而本模块生成 `{parent}:sub:{index:03d}:{name}`）。两套子会话 ID 生成逻辑并存且从未合流，说明该模块是遗留实现。
- 影响：维护负担 + 误导（新读者会以为子会话由 SubSessionManager 管理）；`filter_sub_agent_tools` 的语义（过滤 sub_agent 工具）与 runner 的 `_disabled_tools()` 重复。
- 修复建议：删除或明确迁移到 runner 的会话模型；若保留，统一 ID 格式并让 runner 使用它。

### [S4] 10. SubAgentEventForwardingSink._events 无界累积
- 位置：`core/src/lamtools_core/sub_agent.py:27, 33-34`。
- 问题：子代理运行期间**所有**事件（含非可见事件）无界 append 进 `_events` 列表，直到 run 结束对象被 GC。
- 影响：长子代理（大量工具往返、长流式）内存驻留全部事件对象；与父侧 `CollectingEventSink` 的双份保留叠加。
- 修复建议：只收集可见/需要的事件（复用 `_is_visible_child_event` 过滤），或设上限（如 2000 条后只留摘要）。

### [S4] 11. 子代理内核不接外部取消事件：协作式 Stop 对运行中的子代理无效
- 位置：`core/src/lamtools_core/tool/sub_agent_runner.py:250-278`（`_build_kernel` 未传 `cancel_event_source`）；`core/src/lamtools_core/app/default_agent.py:146-147`（注释明确声明）。
- 问题：`KernelSubAgentRunner` 创建的子代理内核 `cancel_event_source=None`，且父内核在 `toolbox.execute` 等待子代理期间也不轮询 cancel 事件——**协作式**取消（仅 set cancel event、不 task.cancel）对运行中的子代理完全无效，要等子代理整轮跑完。
- 影响：UI 的 Stop 走 `force=True`（`app/live_operations.py:894`）因此实际可用；但任何走协作式取消的调用方（以及"子代理正卡在慢流式上"的场景）体验是 Stop 无反应。这是显式设计取舍，风险可控，但值得记录与验证。
- 修复建议：把 `cancel_event_source` 下传给子代理内核（子代理同样能在流中轮询 `_is_external_cancelled`），或在父内核等待工具期间轮询 cancel 事件并转发。

### [S4] 12. RuntimeTaskRegistry.cancel 优雅路径：立即杀后台进程并弹出入口，但任务本体继续运行
- 位置：`core/src/lamtools_core/runtime/__init__.py:312-331`。
- 问题：`cancel(force=False)` 时先 `cleanup_session`（杀掉该会话注册的后台子进程）再弹出 registry 条目，而 loop 任务本身不取消、继续跑到下一次迭代才感知 cancel 事件。被杀的进程可能正是当前正在执行的工具命令。
- 影响：协作式取消下，正在跑的命令被强杀而工具结果以异常/非零码返回，行为介于"取消"与"工具失败"之间；当前 live 层只用 force=True，实际影响有限，但该 API 语义不干净。
- 修复建议：优雅路径延迟 `cleanup_session` 到任务真正结束时（done_callback 中执行），或文档化"优雅取消会立即终止后台进程"。

### [S4] 13. 访问私有属性 `mcp_registry._tools_by_name`
- 位置：`core/src/lamtools_core/app/default_agent.py:480`（`_mcp_count = len(mcp_registry._tools_by_name) ...`）。
- 问题：仅用于日志计数却穿透私有属性；`MCPToolRegistry` 重构后此处会静默 AttributeError 使 turn_start 失败。
- 影响：日志功能耦合实现细节，脆弱。
- 修复建议：给 `MCPToolRegistry` 加公开 `tool_count` 属性，或改为 `len(registry.tool_specs())`。

### [S4] 14. verify() 中 known_call_ids 每轮全量重建，evidence 列表跨轮累积
- 位置：`core/src/lamtools_core/app/base_agent.py:566-578`。
- 问题：每次 `verify` 都对 `verification_state["evidence"]`（run 内累积）全量重建 set 再逐个判重，工具调用多的 run 呈 O(n²)；evidence 无上限。
- 影响：长 run 的性能与状态体积问题（与 #6 同类），量级较小。
- 修复建议：把 `known_call_ids` 挂在 verification_state 上增量维护；evidence 设上限。

## 3. 该区 Top 3 问题

1. **并行同名字代理会话竞态（S2，#1）**：默认 `parallel_tool_names=("sub_agent",)` + 按 name 定址的子会话 ID，模型一轮内发两个同名 `agent` 调用即并发写同一子会话——SQL 存储下必现一方 revision 冲突失败，内存存储下静默串台污染可复用子会话历史。这是本区唯一会"污染持久化数据"的问题，建议优先修复（同名串行或 per-session 锁）。
2. **取消/异常逃逸缺少统一终端收敛（S2 #2 + S3 #3）**：正常路径有 on_run_end → Stop hook → 终端事件 → end_span 的完整收敛链，但 task.cancel 路径只落盘状态，循环外异常路径则连状态都不收敛（卡 "running"）。两条路径都应汇入同一个 `_finalize_run`。
3. **失败放大链（S3 #4/#5/#7）**：三类"旁路/事后"失败——流式中断整段重放（双倍 token + 100×360s 重试窗口）、事件实时持久化失败杀死整轮、轮末 run_items 批量持久化失败把成功轮报成失败——都会把一次小故障放大为整轮失败或重大成本。应统一降级策略：旁路失败记日志、主结果不翻转。

## 4. 亮点

- **取消链路设计成熟**：`task.cancel()` + 协作式 cancel 事件 + `asyncio.shield(_persist_external_cancellation)`（loop.py:291-296）双保险；`_stream_model` 每事件轮询 `_is_external_cancelled`（loop.py:1559）解决"流式阻塞 Stop 无效"（2b34c636 教训落地）。
- **活跃 turn 双重守卫 + 启动收割**：快照侧 `latest_active_turn_id` 与注册表侧 `accept_run/register` 双闸（live_operations.py:506-528、1660-1667），`recover_stale_active_turns`（live_operations.py:2140）把崩溃遗留的 running turn 在重启时收割为 cancelled——"重复开始/重复结束"被系统性地防住了。
- **ApprovalResolutionLifecycle 顺序约束**（approval_resolution.py）：claim（status=executing，revision 冲突重试）→ durable decision → continue → terminal 四段式，任一阶段失败都能 `_restore_retryable_pending` 回滚为 waiting 或写 failed 终端，且冲突合并只动自有 key（`_APPROVAL_OWNED_METADATA_KEYS`），不踩并发写入者的数据。
- **状态机覆盖完整**：`RuntimeStatus` idle/running/waiting/completed/failed/cancelled 全转换路径可追踪；空回复重试（`_resolve_empty_stop`）、无进展暂停（no_progress → wait，可恢复）、审批等待（wait + pending_approval 落盘）、`_persist_external_cancellation` 清 pending——半途状态均有明确归宿。
- **子代理失败诊断**：`death_scene`（最后模型轮次回复 + 工具状态）+ `tool_call_breakdown`/`model_rounds` 通过 `failure_message()` 反馈给父代理（sub_agent_runner.py:356-392），父代理可据此决策重试而非盲目重来；`_failed_sub_agent_calls` 阻止同一 (agent, task) 无限重试。
- **资源清理到位**：MCP registry 在 turn_start/approval_respond 各分支 finally/except 双保险关闭（default_agent.py:591, 1090-1098）；后台进程注册进 `BackgroundProcessRegistry`，cancel 时按会话（含 `:sub:` 前缀子会话）整树终止；`shutdown_core_agent` 统一 `runtime_task_registry.shutdown()` 并关闭 DB。

## 5. 审计范围与方法

- 覆盖文件（全部只读走查）：
  - `core/src/lamtools_core/app/default_agent.py`（1990 行，全文）
  - `core/src/lamtools_core/app/base_agent.py`（992 行，全文）
  - `core/src/lamtools_core/app/agent_app.py`（234 行，全文）
  - `core/src/lamtools_core/agent.py`、`sub_agent.py`、`sub_session.py`（全文）
  - `core/src/lamtools_core/kernel/loop.py`（3398 行，全文）、`kernel/policy.py`、`kernel/state.py`（引用）
  - `core/src/lamtools_core/runtime/__init__.py`（RuntimeState/RuntimeTaskRegistry，全文）、`runtime/background_processes.py`
  - `core/src/lamtools_core/tool/sub_agent_runner.py`、`tool/default_toolbox.py`（sub_agent 工具段）、`tool/approval.py`、`tool/approval_continuation.py`（引用）
  - `core/src/lamtools_core/app/approval_resolution.py`、`app/live_operations.py`（turn.start/cancel/force_reset/steer/`_run_core_turn`/终端持久化段）、`app/core_session_store.py`、`app/core_db.py`（SqlAlchemyRuntimeStateStore 冲突检测段）、`app/turn_acceptance.py`、`app/http_agent_app.py`（startup/shutdown/live_context）、`app/event_store.py`（引用）
  - `core/src/lamtools_core/plugins/engine.py`（hook 异常隔离确认）
- 方法：全文通读核心文件；`grep` 交叉验证符号引用（确认死代码、cancel 路径调用方、状态写入点）；异常处理面扫描（bare except / `except Exception` 吞异常盘点）；针对状态机转换、并发写、取消传播做逐路径推演；未执行任何测试、未启动任何服务、未写入任何代码文件。
- 结论：共 14 条发现——S1: 0、S2: 2、S3: 6、S4: 6。
