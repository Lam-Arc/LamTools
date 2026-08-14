# 07 runtime 编排与事件系统 审计报告

## 1. 概况

本区覆盖 runtime 编排（`core/src/lamtools_core/runtime/`：workflow.py 1712 行、arrange.py 1090 行、goal.py、plan.py、evidence.py、observer.py、audit.py、background_processes.py、workflow_watcher.py、`__init__.py`）、事件系统（`event/runtime_projection.py` 943 行、`event/run_item.py`、`event/__init__.py`）、`run_event/`（hub + 内存 store）以及 `project/workflow_store.py` 持久化。为验证并发与取消语义的实际路径，交叉核查了 `app/core_db.py` 的 `SqlAlchemyArrangeStore`（唯一持久化 ArrangeStore 实现）、`app/http_agent_app.py`、`app/durable_operations.py`、`app/workflow_operations.py` 与 `app/base_agent.py` 的消费侧。

总体判断：代码结构清晰、模型分层（数据模型 / Manager / Runner / Store 协议）一致性好，两份 ArrangeStore 实现（内存 + SQLAlchemy）语义基本对齐；revision 乐观锁 + `BEGIN IMMEDIATE` 写协调器使任务领取在数据库层是安全的。主要风险集中在三处：**arrange 租约/取消语义下任务的重复执行**、**workflow 子图 loop 迭代反馈失效**、**run_event hub 修剪后的序列号回退与重放缺口**。未发现 S1 级缺陷（无死锁、无持久化数据丢失的直接路径），但有 5 项 S2。

## 2. 问题清单

### S2（中等，5 条）

- **[S2] Arrange 任务租约过期后同一轮轮询内被重置并重新领取，导致任务重复执行**
  位置：`core/src/lamtools_core/runtime/arrange.py:314-343`（内存 store）、`core/src/lamtools_core/app/core_db.py:671-706`（SQL 实现，语义相同）
  问题：`claim_due` 先扫描 `status=="running"` 且租约已过期的任务，将其重置为 `scheduled`（`next_run_at=now`），随后立即在**同一次调用**的 due 筛选中再次领取它。`ArrangeRunner._execute`（arrange.py:1017-1021）对同步 executor 直接 `self.executor(effective_job)` 调用，不经过 `run_in_executor`——一个阻塞型 executor 会卡死整个事件循环：续租任务（`_renew`，每 lease/3≈10s 续租一次）无法运行 → 租约在 30s 后过期 → executor 返回后同一 worker 下一轮轮询立刻把同一 job 重新领取执行。多实例场景下则是 worker B 在 worker A 卡死期间抢占执行。
  影响：arranged 操作（focus/routine，多为有副作用的命令）被重复执行；首次执行的 `complete_run` 因 `_owned_running` 校验抛 "lease lost"，被 `run_due_once` 的 `gather(return_exceptions=True)` 静默吞掉（见下条），结果被丢弃但副作用已发生——at-least-once 语义且无幂等/fencing。
  修复建议：租约过期任务不立即在同一轮 poll 内重新领取，而是重置后要求下一轮（或等待 >1 个 poll 间隔）再领；将同步 executor 用 `asyncio.to_thread`/`run_in_executor` 包装，避免阻塞事件循环导致续租失效；执行前校验 occurrence 的 `started_at`/租约代次作为 fencing token。

- **[S2] `ArrangeRunner.cancel()` 只取消执行协程，不落地 job 状态，取消后任务会再次执行**
  位置：`core/src/lamtools_core/runtime/arrange.py:963-969`（cancel）、`:309-343`（claim_due 重领路径）、`:696-747`（update_status）
  问题：`cancel(job_id)` 仅 `task.cancel()`，`_execute` 的 `except asyncio.CancelledError: raise`（:1041-1042）直接上抛，不写 `fail_run`/`complete_run`，job 在 store 中保持 `running` 且租约未到期。租约到期后 `claim_due` 将其重置并重新领取 → **被取消的任务随后再次执行**。当前 `app/durable_operations.py:178-188` 的 `arrange_status` 路径会紧接着调用 `update_status(..., "cancelled")` 弥补，但二者之间存在竞态：若 update_status 的 `get`+`replace(expected_revision)` 之间被续租的 revision 自增打断（revision conflict 异常被 `_error` 吞掉），job 将一直保持 `running` 直到租约过期后重新执行；且任何不经 `update_status` 的调用方都会踩中该缺陷。
  影响：用户取消 arrange 任务后任务仍可能被再次执行（副作用重复、资源浪费）；取消结果不可靠。
  修复建议：`ArrangeRunner.cancel` 成功取消后应同步将 job 置为 `cancelled`（或提供原子 "cancel+mark" 的 store 方法）；`arrange_status` 中先标记取消再取消任务，消除竞态窗口。

- **[S2] workflow 子图 `iterate=loop` 的迭代反馈机制失效，输出不会回流为下一次输入**
  位置：`core/src/lamtools_core/runtime/workflow.py:914-936`（loop 分支）、`:948-975`（`_map_entry_inputs`）
  问题：文档（:879-881）声明 loop 模式"子工作流输出反馈到下一次迭代的输入，直到条件满足"。但实现中 `_map_entry_inputs(sub_def, {**bound_inputs, "__value__": output})` 的 `first_val`（:960-963）取的是 `bound_inputs` 中第一个非哨兵值——即**原始输入**，`__value__` 仅在子工作流恰有一个名为 `__value__` 的输入端口（或端口名恰好匹配）时才会被用到；多输入子工作流的端口名匹配（:970-971 `name.split(".")[-1]`）同样无法命中父节点端口名。结果：每一轮迭代都喂入相同输入，确定性子工作流每轮产出相同输出，退出条件永不变化，白白执行满 `max_iterations`（默认 5）次，且返回的仍是未收敛的输出。
  影响：loop 模式子图收敛逻辑整体失效：N 倍无效执行成本（LLM 调用/子进程）、结果不可靠且无任何报错。
  修复建议：非 dict 输出时应把 `output` 作为 `first_val` 回填（单输入子图），dict 输出时按子图输入端口名（`{nodeId}.{portName}` 或端口名）做映射而非按父节点端口名；补充 loop 收敛的单元测试。

- **[S2] run_event hub 修剪后序列号回退/重复，重放（replay）出现缺口**
  位置：`core/src/lamtools_core/run_event/hub.py:183-191`（`_trim_events`）、`core/src/lamtools_core/run_event/__init__.py:71-77`（`_next_sequence`）
  问题：`InMemoryRuntimeEventStore.append` 在 `sequence==0` 时分配 `len(self._events)+1`。`_trim_events` 超过 `max_events`（2000）后 `clear()` 并以**原 sequence** 重新 append 保留记录（如 1501..2000），此后新事件被分配 `len+1` ≈ 501 → **新事件序列号回退且与旧记录重复**（`list()` 按 sequence 升序排序，新事件排到最前，`records[-tail:]` 重放可能漏掉刚产生的事件）。
  影响：订阅重放/增量投影在长会话（>2000 事件）后顺序错乱、最新事件可能不出现在 replay 尾部；任何依赖 sequence 单调性的消费者（游标、去重）都会出问题。
  修复建议：用独立单调计数器（如 `itertools.count` 或持久化的 max_seq）分配 sequence；修剪后重新编号或保证 `_next_sequence` 不小于已保留的最大值。

- **[S2] `recover_running` 无属主校验，任意 worker/实例启动都会抢占其他实例正在运行的任务**
  位置：`core/src/lamtools_core/runtime/arrange.py:463-487`（内存）、`core/src/lamtools_core/app/core_db.py:934-965`（SQL）
  问题：`ArrangeRunner.start()`（arrange.py:946）无条件调用 `recover_running(now)`，将 store 中**所有** `running` job 重置为 `scheduled` 并清空 lease_owner，不区分是否是本实例领取的。单实例场景下该逻辑安全（本进程任务已被 stop 取消），但多实例共享同一 DB 时，实例 B 启动会把实例 A 正在执行（且续租正常）的任务全部重置，随后重新领取 → 双执行。
  影响：多 worker 部署时启动即触发任务重复执行；`recover_running` 应只回收租约已过期/属主已死的任务（与 claim_due 的过期判定一致）。
  修复建议：`recover_running` 仅重置 `lease_expires_at <= now` 的任务，或要求显式传入 worker 身份并由属主清理。

### S3（轻微，12 条）

- **[S3] workflow run 中 `_inputs_ready` 不满足时静默 `continue`，最终仍返回 `completed`**
  位置：`core/src/lamtools_core/runtime/workflow.py:552-553`、`:648-656`
  问题：节点输入缺失（如 `start_node` 续跑但 `prior_values` 未提供上游值、或被取消的上游节点未写 outputs）时，节点被永久跳过且不计数，循环结束后返回 `status="completed"`，未执行节点保持 `idle`，无任何错误提示。
  影响：图形部分执行却被报告为完成，调试/续跑场景下结果静默错误。
  修复建议：跳过未就绪节点时应记录并最终返回 `failed`（含缺失输入列表），或在返回 `completed` 前校验所有节点已终态。

- **[S3] 恢复运行（resume）时 `skipped` 状态的节点会被重新执行并重复发出事件**
  位置：`core/src/lamtools_core/runtime/workflow.py:550-551`
  问题：恢复跳过集合只含 `{"done", "cancelled"}`；`skipped` 节点重跑时由于输入仍是哨兵，会再走一次 skip 级联并再次 `_emit_state`（重复事件流），`attempts`/时间戳也被重写。
  影响：断点续跑的事件流与完整运行不一致（幂等性破坏），GUI 收到重复节点事件。
  修复建议：将 `skipped` 加入恢复跳过集合（其哨兵输出已在 `values` 中）。

- **[S3] 节点 `state.output` 使用 `or` 回退，falsy 输出被错误替换**
  位置：`core/src/lamtools_core/runtime/workflow.py:641-643`
  问题：`outputs.get(_default_output_port(node)) or (outputs[next(iter(outputs))] ...)` —— 默认端口的合法 falsy 值（`0`、`""`、`False`、`[]`、`{}`）会被回退成第一个端口的输出。
  影响：节点状态展示的输出值错误（`state.output` 用于结果汇报），对返回 0/空串的节点会显示错误数据。
  修复建议：改为 `key in outputs` 判断后用 `outputs[key]`，或 `if outputs` 结构。

- **[S3] 子图嵌套 thread_id 不在任务注册表中，协作式取消无法到达子图节点**
  位置：`core/src/lamtools_core/runtime/workflow.py:533`（`_cancel_event(thread_id)` 按当前 thread 查）、`:909-910`、`:921-922`、`:940-941`（嵌套 run 使用 `{thread_id}.map{i}` 等新 id）
  问题：`get_cancel_event` 对未注册的嵌套 thread_id 会新建一个永不被 set 的事件；子图内部节点检查的是嵌套 id 的事件。`workflow_cancel` 走 `force=True`（`task.cancel()`）时靠 `CancelledError` 传播尚能中断，但纯协作式取消（仅 set 事件）对子图内节点无效。
  影响：取消延迟到子图整体跑完；协作取消语义不完整。
  修复建议：子图 run 沿用父 thread_id 的取消事件，或在 `_cancel_event` 中做父链回退查找。

- **[S3] `ArrangeRunner.run_due_once` 等待全部已领取任务完成后才继续轮询**
  位置：`core/src/lamtools_core/runtime/arrange.py:982-992`
  问题：`await asyncio.gather(*(task for ...))` 阻塞轮询循环直到所有任务结束；期间新到期任务、observer wake 触发的新信号都无法领取，调度延迟等于最长任务的运行时长。
  影响：单 worker 下长任务（数分钟）期间所有新任务排队等待；事件触发类任务时效性受损。
  修复建议：不 gather 等待，任务完成后经 done-callback 清理 `_active_tasks`，轮询循环只负责领取与启动。

- **[S3] `_execute` 异常路径中 `fail_run` 抛出的 lease-lost 异常被静默吞掉，失败原因丢失**
  位置：`core/src/lamtools_core/runtime/arrange.py:1043-1049` + `:987-988`
  问题：`except Exception` 内调用 `store.fail_run`，若任务已被抢占/取消（job 不再 running），`_owned_running` 抛 `RuntimeError("Arrange job lease lost")`，该异常替换原始异常并被 `gather(return_exceptions=True)` 吞掉——既未记日志也未保留原错误。
  影响：排障时看不到任务失败的真实原因；job 最终状态与事实不符。
  修复建议：fail_run/complete_run 失败时用 logger 记录（含原始异常），或对 lease-lost 显式处理。

- **[S3] InMemoryArrangeStore 信号去重表 `_signals` 无界增长**
  位置：`core/src/lamtools_core/runtime/arrange.py:253`、`:497-500`
  问题：`emit_signal` 以 event_id 去重，去重表只增不减（每 event_id 一条），长时间运行的内存 store 会持续膨胀。
  影响：内存泄漏（测试/单进程长跑场景）。
  修复建议：按时间/容量淘汰（如保留最近 N 条或 TTL），或改为按 job 维度去重。

- **[S3] plan 存在 blocked 步骤时，完成其他步骤会把 plan 误标为 `completed`**
  位置：`core/src/lamtools_core/runtime/plan.py:147-156`（block_step）、`:159-177`（start_next_pending_step）、`:193-205`（plan_is_completed）
  问题：`start_next_pending_step` 只查找 in_progress/pending，忽略 blocked 步骤；步骤 [A blocked, B in_progress] 完成 B 后：无 in_progress、无 pending → `current_step_id=""` 且 `plan["status"]="completed"`；而 `plan_is_completed` 优先检查 `plan.status == "completed"` 直接返回 True，尽管 A 仍 blocked。
  影响：计划完成判定与执行状态矛盾（plan 与执行偏差），阻塞步骤被静默掩盖。
  修复建议：存在非 completed/skipped 步骤时不应置 `completed`；`plan_is_completed` 先校验步骤状态再信任 status 字段。

- **[S3] observer 信号读取任务（`_read_stdout`）死亡后无重启，信号静默丢失**
  位置：`core/src/lamtools_core/runtime/observer.py:219-266`
  问题：`_read_stdout` 的异常捕获只覆盖解析类异常（`UnicodeDecodeError/JSONDecodeError/TypeError/ValueError`）；若 `emit_signal` 抛出其他异常（store 故障等），任务直接死亡，`_monitor` 仍挂起等待进程退出，此后的信号行不再处理，且状态不更新。
  影响：持久性 store 故障期间 observer 信号丢失，无告警无重试。
  修复建议：任务外层兜底 except 记录状态并继续读下一行，或任务死亡后终止进程触发 `_schedule_restart`。

- **[S3] 投影状态映射不一致：`runtime.tool.finished` 把 `skipped`/`blocked` 映射为 `failed`，而 `runtime.part` 路径映射为 `skipped`/`running`**
  位置：`core/src/lamtools_core/event/runtime_projection.py:324-332`、`:915-922`
  问题：`ToolResultStatus = Literal["ok","failed","skipped","blocked"]`（kernel/loop.py:3134 透传）。tool.finished 路径中 `skipped`/`blocked` 均落入 `else → "failed"`；而 part 路径的 `_canonical_status` 中 `skipped`→`skipped`、`blocked` 不在映射表 → 回退为 `"running"`。同一事实（一个被跳过/被拒绝的工具调用）经两条投影路径得到三种不同状态。
  影响：GUI 上工具状态展示不一致（部分路径显示失败、部分显示运行中/跳过）；增量投影与全量重放结果不一致。
  修复建议：两路径统一走 `_canonical_status`，并补齐 `blocked` 的映射（如 → `failed` 或新增 `skipped`）。

- **[S3] `RuntimeEventHub._replay_records` 在 last_event_id 找不到时返回空（静默丢失），与 `InMemoryEventLog.replay_since` 语义相反**
  位置：`core/src/lamtools_core/run_event/hub.py:166-181`（`:178` return []）、`core/src/lamtools_core/event/__init__.py:129-137`
  问题：订阅者携带的 last_event_id 因修剪或服务重启而丢失时，hub 重放返回空列表——客户端以为"没有新事件"，实际中间事件全部错过且无任何提示；而 `InMemoryEventLog.replay_since` 对未知 id 返回全量（两处语义不一致）。
  影响：断线重连后事件丢失且不可感知，投影/快照与真实事件流不一致。
  修复建议：未知 last_event_id 时返回全量（或带 gap 标记），并在 SSE 响应中暴露"是否发生过修剪"。

- **[S3] `RuntimeTaskRegistry` 条目泄漏 + 取消事件跨 run 误伤（workflow 路径不注册 task）**
  位置：`core/src/lamtools_core/app/workflow_operations.py:157-162`、`core/src/lamtools_core/runtime/__init__.py:260-271`（accept_run）、`:312-331`（cancel）
  问题：`workflow_run` 调用 `registry.accept_run(thread_id, run_id)` 但**丢弃返回值**，且从不 `registry.register(thread_id, task)`。后果：① 条目 `task=None` 永不触发 done 回调清理，run 结束后 `active_run_id`/`is_running` 长期报告该 run 活跃；② 同 thread 第二次运行（不同 run_id）时 `accept_run` 返回 False 被忽略，第二次运行复用**同一个取消事件**——之后用旧 run_id 调用 `cancel` 会连带取消第二次运行（`cancel` 中 run_id 过滤仅在 entry.run_id 匹配时生效，事件却是共享的）。
  影响：取消请求可能误杀同线程的后续运行；registry 状态与实际不符。
  修复建议：workflow_run 尊重 accept_run 返回值（失败即拒绝），或注册真实 task；取消事件按 run 隔离或取消时校验 run_id 后 set。

- **[S3] `WorkflowManager.update_fields` 读-改-写无版本/无锁，并发更新互相覆盖**
  位置：`core/src/lamtools_core/runtime/workflow.py:396-427`
  问题：`get` → 修改字段 → `save` 全量覆盖，期间其他请求的修改丢失（workflow def 无 revision 字段，store 层也无 CAS）。
  影响：画布/API 并发编辑工作流定义时静默丢字段（与 arrange/goal 的 revision 机制形成对照）。
  修复建议：为 WorkflowDef 增加 revision 并在 save 时校验（或 store 提供 merge 语义）。

### S4（建议，6 条）

- **[S4] `_eval_condition` 的受限 eval 沙箱可通过属性遍历逃逸**
  位置：`core/src/lamtools_core/runtime/workflow.py:1680-1695`
  问题：`eval(expr, {"__builtins__": _CONDITION_BUILTINS}, dict(bound_inputs))` 只是替换了 builtins，locals 中的运行时值（LLM/命令输出产生的 dict/str 等）仍可被 `x.__class__.__mro__...` 属性链访问，经典沙箱逃逸路径。由于条件表达式由工作流作者编写（作者本就能写任意 shell/Python 节点），实际风险低，但建议注明信任边界或用 AST 白名单校验表达式。

- **[S4] `_substitute_env_vars` 的 `$VAR` 替换存在变量名前缀碰撞**
  位置：`core/src/lamtools_core/runtime/workflow.py:1487-1491`
  问题：先替换 `${VAR}` 再替换 `$VAR`，`$INPUT_A` 会命中 `$INPUT_ABC` 的前缀（`"$INPUT_ABC".replace("$INPUT_A", v)` → `"<v>BC"`）。端口名存在前缀关系（如 `a` 与 `abc`）时命令被错误改写。
  修复建议：用正则按 `\$(?:\{VAR\}|VAR)\b` 整体匹配替换。

- **[S4] `RuntimeProjectionBuffer.merge_part_growth` 为死代码，且 `_pending_parts` 无界**
  位置：`core/src/lamtools_core/event/runtime_projection.py:51-74`
  问题：全库检索无任何调用方（仅定义+导出）；若启用，`_pending_parts` 按 part_id 只增不减。建议删除或接入实际消费方并加清理。

- **[S4] SSE 慢消费者队列满时事件被静默丢弃，无追踪**
  位置：`core/src/lamtools_core/run_event/hub.py:134-140`
  问题：`_try_put` 队列满返回 False，`publish_runtime_record` 只统计 delivered 数，丢包无日志、无补偿（重放仅依赖 store 内 2000 条）。建议丢包时记日志并提示客户端重新同步。

- **[S4] workflow_store 节点 id 经 `_safe_filename` slug 化后可能碰撞，节点文件互相覆盖**
  位置：`core/src/lamtools_core/project/workflow_store.py:339`（`_safe_filename(node.id)+".json"`）、`:379-381`
  问题：两个不同节点 id 若 slug 化结果相同（如含中文/特殊字符），后写覆盖先写，读取时同 id 节点重复解析、首个生效，静默丢节点。
  修复建议：写入时检测同名文件且 id 不同则拒绝或加后缀。

- **[S4] evidence 引用可能悬空；`_python3_shim_dir` 注释与实现不符**
  位置：`core/src/lamtools_core/runtime/evidence.py:49-57`、`core/src/lamtools_core/runtime/workflow.py:1529-1533`
  问题：① `remember_evidence` 只记录 `call_id/run_id/turn_id` 引用不存内容，历史压缩/清理后引用无法解析（审计链断裂）；② 注释声称写 `.exe` wrapper，实际写的是 `python3.bat`。
  修复建议：① 记录时附带内容摘要或在清理时同步清理证据索引；② 修正注释。

## 3. 该区 Top 3 问题

1. **Arrange 任务重复执行（S2×3 同源）**：租约过期即在同一轮轮询内重领 + 同步阻塞 executor 使续租失效 + `recover_running` 无属主校验 + `ArrangeRunner.cancel` 不落地状态——四条路径都指向"同一 arranged 操作被执行多次且副作用不可撤销"。这是本区最严重的行为缺陷，建议优先处理（fencing + 异步执行 executor + cancel 落库）。
2. **Workflow 子图 loop 迭代反馈失效（S2）**：文档承诺的"输出回灌下一轮输入"从未生效，loop 模式退化为"同输入跑满 max_iterations"，浪费 N 倍执行且结果不可信。
3. **run_event 重放一致性（S2）**：`_trim_events` 后序列号回退/重复 + 未知 last_event_id 重放返回空，订阅者重连后静默丢事件，增量投影与真实事件流可能不一致。

## 4. 亮点

- **存储层一致性好**：`SqlAlchemyArrangeStore` 与 `InMemoryArrangeStore` 语义逐方法对齐（含 occurrence 转换、signal 交付、retry 次数），`BEGIN IMMEDIATE` + `SQLiteWriteCoordinator` 使 select-update 领取在数据库层串行化，跨进程双领取被 revision 条件防住。
- **revision 乐观锁贯穿 arrange/goal**：`replace(expected_revision=...)` 一致应用于两份 store，并发冲突能显式抛出而非静默覆盖。
- **workflow 运行器设计克制**：无租赁/轮询，纯拓扑序 + 值表，SKIP 哨兵级联、edge condition/transform、fallback/skip/abort 三种失败策略、`_emit_state` 异常隔离（流式事件永不中断执行）都很完整；`_resolve_output` 的终态端口判定正确。
- **观察者安全模型**：`prepare_observer` 路径约束 + `approved_sha256` 内容校验 + 指数退避重启 + 事件按 `observer_id:event_id` 绑定去重，设计严谨。
- **事件 id 派生确定性**：`_content_event_id`（sha1 摘要）与 `_tool_item_id` 均为纯函数，同一事实重放可复现相同事件 id，为投影一致性提供基础。
- **workflow_store 文件夹布局 + 惰性迁移 + 原子写**：节点文件隔离损坏、`.tmp` 原子替换、签名缓存（mtime+size）与 watcher 配合，外部编辑可自动发现。

## 5. 审计范围与方法

- **范围**：`core/src/lamtools_core/runtime/`（workflow.py、arrange.py、goal.py、plan.py、evidence.py、observer.py、audit.py、background_processes.py、workflow_watcher.py、`__init__.py`）；`core/src/lamtools_core/event/`（runtime_projection.py、run_item.py、`__init__.py`）；`core/src/lamtools_core/run_event/`（hub.py、`__init__.py`）；`core/src/lamtools_core/project/workflow_store.py`。交叉核查（仅验证语义，非审计对象）：`app/core_db.py`（SqlAlchemyArrangeStore）、`app/http_agent_app.py`、`app/durable_operations.py`、`app/workflow_operations.py`、`app/base_agent.py`、`app/snapshot_store.py`、`kernel/loop.py`（事件生产方）、`app/sqlite_write.py`。
- **方法**：逐文件通读（共约 6300 行）→ 状态机与异常路径走查（claim/complete/fail/recover/cancel、run/pause/resume/cancel、skip 级联）→ 双实现（内存/SQL）语义比对 → 消费方/生产方交叉验证（取消链路、投影 status 值域）→ 行号级复核。全程只读，未运行任何测试或服务；所有发现均可定位到具体 `file:line`。
- **统计**：S2 × 5、S3 × 12、S4 × 6，共 23 条；无 S1。
