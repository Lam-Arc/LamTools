# 05 kernel 核心循环 审计报告

> 审计时间：2026-08-13　审计员：ZCode（05 区）
> 范围：`core/src/lamtools_core/kernel/`（loop.py 3398 行、hooks.py、policy.py、state.py、tracing.py、kit.py、display.py、errors.py），及与 event/、plugins/、runtime/、llm/retry 的交互。

## 1. 概况

kernel 区以 `CoreLoopKernel`（loop.py）为核心，实现产品无关的主循环骨架：加载状态 → on_run_start → 循环（build_context → build_model_request → 流式/非流式模型调用 → parse → 追加 assistant 消息 → 执行工具 → verify → decide_next → writeback → 存档）→ on_run_end。Kit（RuntimeKit 协议）拥有业务逻辑，Kernel 拥有循环结构。整体设计成熟：流式与重试路径、上下文压缩与恢复边界、无进展/重复失败启发式、审批等待门、guidance 中断、取消镜像等均有细致处理。

本次审计共确认 **20** 条问题：**S2 ×2、S3 ×8、S4 ×10**。未发现 S1 级缺陷。最突出的系统性问题有二：一是 **hook 失败未隔离**（hook 引擎的 JSON 解析路径可把异常抛进主循环，杀死整个 run；Stop hook 异常直接逃出 `run()`）；二是 **循环外关键路径无异常保护**（`on_run_start`/SessionStart/UserPromptSubmit hook、循环尾部的 `on_run_end`/Stop hook/终态事件发射均不在任何 try/except 内，异常会导致 state 永久卡在 "running" 或结果丢失）。性能上 `kernel_steps` 无界增长叠加每步 `deepcopy(metadata)` 形成 O(n²) 开销，长任务明显。

## 2. 问题清单

### S2（中等）

- **[S2] Hook 失败未隔离：hook 引擎的 JSON 解析异常可杀死整个 run**
  - 位置：`core/src/lamtools_core/kernel/loop.py:2223`（PreToolUse）、`:2304`（PostToolUse/PostToolUseFailure）、`:2496`（PermissionRequest）、`:2352`（SessionStart）、`:2438`（Stop）、`:2466`（UserPromptSubmit）；根因在 `core/src/lamtools_core/plugins/engine.py:202-215`（`_decision_from_text`）。
  - 问题：`HookEngine.run` 对 command/http/mcp 钩子的执行异常均有内部兜底（返回 failed/blocked 决策），但 `_decision_from_text` 中的 `json.loads` 未捕获——当钩子进程退出码 0 却向 stdout 输出非法 JSON（或 http 2xx 返回非 JSON 体）时，抛 `JSONDecodeError` 穿透 `hook_engine.run`，进入 kernel 各 `_apply_*_hook`，主循环内被 `except Exception` 兜住后整个 run 标记为 failed（一次钩子输出问题 = 一次任务失败）；若发生在循环外（SessionStart/UserPromptSubmit/Stop），则直接逃出 `run()`。
  - 影响：违反"钩子失败不影响主流程"的隔离目标；钩子的输出格式错误即可导致任务整体失败或结果丢失。
  - 修复建议：`_decision_from_text` 用 try/except 将 JSON 解析失败转为 failed 审计 + 空决策（required 钩子再 block）；或在 kernel 侧给每个 `hook_engine.run` 调用加统一 try/except 包装（含 Stop hook 调用点）。

- **[S2] 循环前与循环尾部的关键路径无异常保护：state 卡 "running" 或结果丢失**
  - 位置：`core/src/lamtools_core/kernel/loop.py:421-466`（标记 running 存档、`kit.on_run_start`、SessionStart hook、`_append_history_checkpoint`、UserPromptSubmit hook、`_emit_state_event`）与 `:1172-1219`（`_replace_history_checkpoint`、`kit.on_run_end`、Stop hook、`_emit_terminal_event`、tracer.end_span）。
  - 问题：主循环体（484-1170）有 `except`，但上述两段均裸露。循环前任一步抛异常（如 hook 故障、store 故障）时 state 已以 `status="running"` 持久化（421 行），run() 直接抛出裸异常，无任何清理——界面将永久显示"运行中"，直至下一次 run 覆盖。循环尾部的 `_replace_history_checkpoint`/`on_run_end`/Stop hook 抛异常时，state 虽已按终态存档，但 KernelResult 无法返回给调用方（调用方收到裸异常，拿不到 decision/message）。
  - 影响：崩溃后的状态不一致（stuck running）；hook 或归档故障吞掉正常完成的结果。
  - 修复建议：把 `_run` 的"收尾段"也纳入 try/except（收尾异常降级为日志 + 仍返回 result）；循环前的 `on_run_start`/hook 调用包 try/except，异常时置 failed 并走统一收尾。

### S3（轻微）

- **[S3] `runtime.history_compacted` 事件计数错误（trimmed/remaining 均错）**
  - 位置：`core/src/lamtools_core/kernel/loop.py:504-507`。
  - 问题：`trimmed = len(history) - cut` 在 `del history[:cut]` **之前**计算。此时 `len(history)` 是删除前的总长 L，故 `trimmed` 实际等于"剩余条数"；而 `_emit_history_compacted(state, trimmed, len(history))` 传入的 `len(history)` 也是删除前的 L。事件里 trimmed=L-cut（实为剩余）、remaining=L（实为总数），两个数字全部错位。
  - 影响：上下文裁剪的监控/审计数据不可信（剩余数被当成裁剪数）。
  - 修复建议：先 `del` 再算：`trimmed = cut`、`remaining = len(history)`（删除后）。

- **[S3] 无总步数/总时长硬上限：非流式模型重试最坏 10 小时无总体截止**
  - 位置：`core/src/lamtools_core/kernel/loop.py:2078-2079`（`complete_with_retry(max_attempts=model_retries, timeout_seconds=model_timeout_seconds)`）、`core/src/lamtools_core/kernel/policy.py:17-22`（`model_retries=100`、`model_timeout_seconds=360.0`）、`:1559`（`_is_external_cancelled` 仅流式路径检查）。
  - 问题：`model_retries=100` 且每次尝试上限 360s → 单个非流式模型调用的最坏墙钟时间约 10 小时，且 `complete_with_retry` 内部（llm/retry.py `run_with_model_retry`）把超时/网络错误归类为 "retryable" 反复重试，重试 sleep 期间也不检查 kernel 的 cancel 事件——合作式取消（`cancel_event_source`）只在流式循环（1559 行）生效，非流式调用只能依赖外部 `task.cancel()`。主循环本身也无总步数/总时长上限（473-476 行注释明确"intentionally no step budget"）。
  - 影响：provider 持续 503/卡死时，一次"Stop"在非流式路径最长要等 10 小时才响应；run 的端到端时长实际无界。
  - 修复建议：在 kernel 层加总体 run 截止（如 policy 新增 `run_timeout_seconds`/`max_steps`，非 None 时在循环头与模型调用外圈 `asyncio.wait_for`）；重试循环的 sleep 间隙检查 cancel 事件。

- **[S3] `tool_progress_incomplete` 强制 `decision="continue"` 会覆盖 Kit 的终局决策，配合无步数上限形成死循环窗口**
  - 位置：`core/src/lamtools_core/kernel/loop.py:1066-1069`。
  - 问题：`if tool_progress_incomplete or (tool_progress_completed and tool_progress_structured): decision = "continue"` 无条件改写 Kit 的 `decide_next` 结果——包括 Kit 返回的 `"wait"` 甚至 `"failed"`。`tool_progress_incomplete` 仅在 `tool_progress_pending`（payload 复用时置位）且模型"有回复+有工具调用+无三标题结构"时为真，而该状态没有轮次上限（`tool_progress_blocked_rounds` 只统计另一条 `tool_progress_required` 路径）。模型持续输出文本+工具却不满足结构时，每轮追加 `[TOOL_PROGRESS_INCOMPLETE]` 系统消息并强制 continue，可无限循环，只能靠用户取消。
  - 影响：进度门反而成为无界循环入口；Kit 的失败/等待决策被吞掉。
  - 修复建议：仅当 Kit 返回 "continue"/"done" 时才强制 continue；对 `tool_progress_incomplete` 增加轮次上限（达上限转 wait）。

- **[S3] `self.kit.toolbox` 非协议成员访问，且位于异常保护之外**
  - 位置：`core/src/lamtools_core/kernel/loop.py:468-471`（日志行 `len(self.kit.toolbox.tool_specs()) if self.kit.toolbox else 0`）。
  - 问题：`RuntimeKit` 协议（`kernel/kit.py:20-96`）只声明 `name` 与方法，未声明 `toolbox`；而该访问在 `while True` 的 try 之外。当前两个 Kit 实现（`app/base_agent.py:185` 的 CoreBaseAgentKit 等）恰好有 `toolbox` 属性，但任何仅按协议实现的 Kit 会在此行抛 `AttributeError`，直接逃出 `_run`（连循环都进不去）。
  - 影响：协议与实现的隐性耦合；实现漂移时表现为无从排查的启动即崩溃。
  - 修复建议：改用 `getattr(self.kit, "toolbox", None)`，或把 `toolbox` 加入 RuntimeKit 协议。

- **[S3] `kernel_steps` 无界增长 + 每步 deepcopy(metadata)：O(n²) 时间与内存**
  - 位置：`core/src/lamtools_core/kernel/loop.py:478`（`step = KernelStep(index=index, state_before=self._copy_state(state))`）、`:2623-2632`（`_copy_state` 深拷贝整个 metadata）、`:754/911/953/1136-1138`（`kernel_steps` append，从不裁剪）、`:1141`（每步 `_save_checkpoint` 全量存档）。
  - 问题：`persist_steps=True`（默认）时 `state.metadata["kernel_steps"]` 每步追加一条摘要且跨 run 累积（从 store 加载的 state 带着历史摘要继续增长）；每步的 `_copy_state` 深拷贝包含 `kernel_steps` 的整个 metadata，且每步 `_save_checkpoint` 把含全部历史摘要的 state 完整序列化存档。三步叠加 → 单 run 内总开销 O(步数² × 摘要大小)。500 步任务的归档体量可达数十 MB。
  - 影响：长任务（无步数上限 + 该 O(n²) 开销）越跑越慢，存档越来越大。
  - 修复建议：`kernel_steps` 设上限（如保留最近 100 条）；`state_before` 改为浅拷贝或排除 `kernel_steps`；步骤摘要增量归档。

- **[S3] 工具失败指纹与成功 payload 缓存的内存/CPU 开销，`explicit_input_errors` 无界**
  - 位置：`core/src/lamtools_core/kernel/loop.py:1350-1400`（`_observe_repeated_tool_failures`）、`:659-671, 851-862`（`recent_successful_payloads`）、`:693`（`explicit_input_errors`）。
  - 问题：失败指纹 `json.dumps` 包含**完整** `result.content`/`result.error`（大工具输出可达 MB 级），窗口 12 条全量留存；`recent_successful_payloads` 同样全量保存大 payload（受窗口限制）；`explicit_input_errors` 按不同指纹累积、无上限。指纹计算每轮每工具做一次全量序列化+哈希。
  - 影响：read_file 类大输出场景下数十 MB 驻留内存；超长 run 中 `explicit_input_errors` 持续增长。
  - 修复建议：指纹只保留哈希（内容/错误先截断或直接只对 `(tool, args, status, error_type, exit_code)` 取 sha256）；`explicit_input_errors` 加容量上限。

- **[S3] 工具事件携带完整参数/结果/元数据，敏感信息进入事件流与持久化**
  - 位置：`core/src/lamtools_core/kernel/loop.py:3061`（`_emit_tool_started` 完整 `arguments`）、`:3133-3173`（`_emit_tool_finished` 完整 `content`/`error`/`metadata` + part 事件）、`:3250-3279`（`_emit_approval_request` 完整 `arguments`/`reason`/`metadata`）、`:733-738`（`pending_approval` 存档完整 `tool_call.to_dict()`）。
  - 问题：bash/exec/env 等工具的 `arguments` 可含密钥或凭据；工具结果可含文件内容；这些字段**原样**进入 `runtime.tool.*`/`runtime.part`/`runtime.approval_request` 事件并随事件持久化，且 approval 请求存档于 state.metadata。事件消费方与历史视图均可见。
  - 影响：敏感信息（密钥、文件内容）泄漏到事件存储与持久化状态；`_emit_stream_tool_call_part`（1884-1886 行）虽有 `_safe_tool_arguments` 摘要，但 started/finished/approval 事件未做同样处理，防护不一致。
  - 修复建议：对事件 payload 中的 arguments/content 复用 `_safe_tool_arguments` 式截断/摘要（display 层已有的截断不覆盖原始事件）。

- **[S3] 非 RuntimeCheckpointStore 实现时会话历史被静默丢弃**
  - 位置：`core/src/lamtools_core/kernel/loop.py:1402-1404`（`_load_history` 对非 checkpoint store 直接返回 `[]`）、`:1433-1444`（`_save_checkpoint` 只存 state，历史写入仅存在于 checkpoint store 分支）、`:1446-1478`（append/replace 对非 checkpoint store 退化为主循环外不写历史）。
  - 问题：store 只实现 `RuntimeStateStore`（get/save）时，历史永远为空——每轮对话模型只看到本轮 user 消息，跨轮会话记忆静默失效，且无任何告警。
  - 影响：实现契约的分支退化没有可见性；接入方换 store 后对话质量无征兆劣化。
  - 修复建议：启动时检测 store 能力并打 warning 日志；或在文档/协议中明确 checkpoint 能力为必需。

### S4（建议）

- **[S4] `LoopPolicy.emit_debug_events` 从未被任何代码读取（死配置）**
  - 位置：`core/src/lamtools_core/kernel/policy.py:31`。
  - 问题：全库 grep 无引用；该策略字段形同虚设，易误导配置者。
  - 修复建议：实现对应调试事件发射，或删除该字段。

- **[S4] `_emit_stream_part` 的 `raw` 参数从未使用（死参数）**
  - 位置：`core/src/lamtools_core/kernel/loop.py:1830`（`raw: Any = None`），函数体 1818-1866 无任何引用；8 处调用点都传入了 `raw=event.raw`。
  - 修复建议：删除参数或真正透传（如放入 payload.metadata）。

- **[S4] kernel 实例的共享可变状态使并发复用存在竞态；外部 cancel 事件复位耦合于 app 层**
  - 位置：`core/src/lamtools_core/kernel/loop.py:250`（`_cancel_event` 实例共享）、`:398`（`self.event_sink` 每次 run 重绑）、`:283-286`（`_is_external_cancelled` 把 registry 事件镜像进 `_cancel_event`）。
  - 问题：同一 kernel 实例上并发两次 `run()` 会互相覆盖 `self.event_sink`（事件 turn_id 串号）并共享 cancel 信号。当前调用方（`app/default_agent.py`、`tool/sub_agent_runner.py`）每个 turn 新建 kernel，竞态仅是潜在风险；另外 kernel 只清自己的 `_cancel_event`，不清 `cancel_event_source`——registry 事件靠 app 层 `accept_run` 复位，任何未走该路径的新 run 会被上一轮的 cancel 状态立即取消。
  - 修复建议：`event_sink`/`cancel` 改为 run 局部变量或加锁拒绝并发；kernel 启动时尝试复位外部 cancel 源（或文档化该耦合）。

- **[S4] `_repair_incomplete_tool_history` 静默丢弃"孤儿" tool 消息**
  - 位置：`core/src/lamtools_core/kernel/loop.py:179-187`。
  - 问题：`pending` 非空时，`call_id` 不在 pending 的 tool 消息（包括 `call_id` 为空的 tool 消息）被直接丢弃且无日志；仅当 pending 为空时才保留。跨消息批次交错时可能丢真实工具结果。
  - 影响：罕见情况下历史内容丢失（模型少看一条工具结果）。
  - 修复建议：丢弃前打 warning 日志并计入 metadata（可审计）。

- **[S4] `invalid_tool_argument_errors` 依赖 `response.tool_calls` 与 `turn.tool_calls` 按索引对齐**
  - 位置：`core/src/lamtools_core/kernel/loop.py:564-577`。
  - 问题：解析错误归因用 `call_index`（response 侧）取 `turn.tool_calls[call_index]`；若 Kit 在 `parse_model_output` 中重排/过滤工具调用，错误会归因到错误的 call。
  - 修复建议：改按 `call.id` 匹配而非索引。

- **[S4] `_backup_file_for_writer_tool` 硬编码 "write_file"/"edit_file"，违反"Kernel 不按产品分支"约定**
  - 位置：`core/src/lamtools_core/kernel/loop.py:2150-2172`。
  - 问题：kernel 层出现具体工具名分支（备份能力），与模块文档声明的职责边界不符；其他产品的写文件工具名不同时静默失效。
  - 修复建议：备份决策下沉到 Kit（或由 hook/checkpoint 层按配置驱动）。

- **[S4] `turn_count` 计数语义漂移**
  - 位置：`core/src/lamtools_core/kernel/loop.py:753`（审批等待）、`:902`（progress 门）、`:944`（no_progress 暂停）各自 +1，`:1133`（正常路径）+1，而 cancel/异常路径不加。
  - 问题：同一逻辑轮在不同出口的计数口径不一致，基于 turn_count 的统计/定价会漂移。
  - 修复建议：统一在循环出口（break 前）一次性递增，或文档化差异。

- **[S4] 空响应（无内容无工具）仅告警，重试完全交给 Kit，无 kernel 兜底**
  - 位置：`core/src/lamtools_core/kernel/loop.py:555-562`、`policy.py:28`（`empty_response_retries=3`）、`:426-431`（把预算塞进 metadata 由 Kit 消费）。
  - 问题：`empty_response_retries` 是纯约定——Kit 不实现即不生效；空响应在 kernel 侧只打 warning 后继续走 parse/decide。
  - 修复建议：在 kernel 层对空响应做兜底计数（达上限才接受），Kit 逻辑作为增强。

- **[S4] 陈旧 `pending_approval` 元数据在 run 开始时未清理**
  - 位置：`core/src/lamtools_core/kernel/loop.py:381-393`（只清理 no_progress 类 `pending_waiting_request`）。
  - 问题：上一轮未决的审批请求元数据残留于 state.metadata，若 app 层未消费会与新一轮审批状态混淆。
  - 修复建议：run 开始时清除 `pending_approval` 及 permission 类 `pending_waiting_request`。

- **[S4] `_persist_external_cancellation` 不写回历史，与正常收尾不一致**
  - 位置：`core/src/lamtools_core/kernel/loop.py:1221-1236`。
  - 问题：外部 `task.cancel()` 路径只存 state（且 `state.metadata.pop` 两个 pending 键），不调用 `_replace_history_checkpoint`——取消瞬间尚未落库的最后一条 assistant/工具结果丢失（下次 run 靠 repair 补合成失败结果，可接受但口径不同）。
  - 修复建议：取消路径复用统一收尾（shield 内同样执行历史 replace）。

## 3. 该区 Top 3 问题

1. **Hook 失败未隔离（S2，loop.py:2223/2304/2438/2466 + plugins/engine.py:202-215）**：`HookEngine._decision_from_text` 的 `json.loads` 未捕获，钩子输出非法 JSON 即可把异常抛进主循环杀死整个 run；循环外的 Stop/SessionStart/UserPromptSubmit 钩子异常直接逃出 `run()`。这是"钩子失败污染主循环"的直接违反，且复现路径只需要一个输出脏数据的钩子。
2. **循环外关键路径无异常保护（S2，loop.py:421-466、1172-1219）**：`on_run_start`/初始存档/hook 失败时 state 永久卡 "running" 且无清理；循环尾 `_replace_history_checkpoint`/`on_run_end`/Stop hook/终态事件失败时已完成的结果无法返回。主循环内的异常处理很完善，恰恰是两端的裸区最危险。
3. **无总步数/总时长硬上限 + 重试最坏 10 小时（S3，loop.py:2078-2079、policy.py:17-22、1559）**：`model_retries=100 × model_timeout_seconds=360` 且合作式取消只在流式路径生效；配合"intentionally no step budget"与 `tool_progress_incomplete` 强制 continue（1066-1069），run 的端到端时长在非流式/异常模型行为下实际无界，可用性与故障恢复成本最重。

## 4. 亮点

- **取消设计完备**：`run()` 对 `asyncio.CancelledError` 用 `asyncio.shield(self._persist_external_cancellation(...))` 统一终态持久化（291-296、1221-1236），流式路径按 `_is_external_cancelled` 合作式中断（1559-1560），并有 2b34c636 等历史事故的注释沉淀。
- **上下文压缩边界设计严谨**：`summary_seq` 边界 + `lam_compaction_resume` 标记 + 边界漂移回退（355-371、1480-1505、2887-2937），对"压缩后只余摘要幽灵"等坑有明确防护；`_strip_internal_message_metadata` 用 `dataclasses.replace` 避免污染共享历史对象（137-158）。
- **历史修复与恢复**：`_repair_incomplete_tool_history`（161-199）对中断的工具调用生成可见的合成失败结果，保证模型请求中 assistant tool_calls 与 tool 结果配对，兼顾 API 合法性与可解释性。
- **失败启发式分层克制**：重复工具失败（指纹窗口）、重复大 payload 挑战（`challenged` 标记 + 行相似度 0.98）、连续失败诊断提示、工具-only 进度门互相独立且均可配置/关闭，且统一收敛为 wait（可恢复）而非 failed。
- **审计痕迹**：`persist_steps` 步骤摘要、`runtime_audit`、`no_progress_observations`（上限 32 条）等设计克制（有界或显式开关）。

## 5. 审计范围与方法

- 通读 `core/src/lamtools_core/kernel/` 全部 9 个文件（loop.py 3398 行逐行）；交叉核对 `event/__init__.py`（EventSink/CoreEvent）、`plugins/engine.py`（HookEngine.run 异常路径）、`runtime/__init__.py`（RuntimeState/RuntimeTurnInput/RuntimeCheckpointStore/RuntimeTaskRegistry 取消事件生命周期）、`llm/retry.py`（complete_with_retry/stream_with_retry 重试与超时）、`app/default_agent.py` 与 `tool/sub_agent_runner.py`（kernel 实例化与调用方式）、`llm/policy.py`、`tokens.py`。
- 方法：全文件逐行阅读 + grep 交叉验证（`toolbox`、`emit_debug_events`、`kernel_steps`、`guidance_source` 消费语义、`accept_run`/`reset_cancel_event` 时序、`raw` 参数引用、git log 变更脉络）。
- 约束：全程只读，未运行任何测试或服务；所有发现均以 file:line 精确定位并复核。
- 未覆盖：`llm/` 客户端实现内部、`event/` 持久化 sink 的具体落库行为（事件量影响程度依赖其实现）、`context_compaction` 模块内部。
