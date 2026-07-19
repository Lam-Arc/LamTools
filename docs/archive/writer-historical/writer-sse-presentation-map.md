# Writer SSE Presentation Map

> 目标：把 Writer SSE 分成“前端需要呈现”和“不需要呈现”，并记录建议呈现方式与当前实际呈现方式。

维护标注（2026-07-02 Step 12 后）：本文是历史展示映射，不再代表 Writer 当前产品主线。旧 `POST /api/sessions/{session_id}/chat`、`GET /api/sessions/events`、debug SSE/decision/step 入口和 canonical Writer SSE 事件族已经从生产主线移除；当前 GUI/CLI 运行展示以 app-server websocket、App Server event ledger、`snapshot.core` 和 Core `RunItemEvent` 投影为准。

## 入口

- 主任务流：`POST /api/sessions/{session_id}/chat`
- 长连接监听：`GET /api/sessions/events?session_id=...`
- 完整运行日志：维护标注（2026-07-01）：旧 `GET /api/sessions/{session_id}/runtime-events/{event_id}` 已删除；运行展示以 App Server snapshot / event 主线为准，runtime event 仅保留内部过渡投影。
- 调试注入：`POST /api/sessions/{session_id}/debug/sse`
- 调试决策点：`POST /api/sessions/{session_id}/debug/decision-point`
- 调试步骤：`POST /api/sessions/{session_id}/debug/step`

当前 canonical SSE 只有 6 类：

- `writer_step`
- `writer_progress`
- `writer_response`
- `writer_decision`
- `writer_git`
- `writer_lifecycle`

旧事件名仍可能通过兼容路径或调试接口出现，但新代码应优先使用 canonical 事件。

## 展示总规则

聊天区按发送流程分层：

1. 无论如何都展示：用户消息、正式 `reply`、决策卡、sub line。
2. 普通过程信息：LLM 过程、tool、step、progress、Git/status 过程在 `reply` 前展开显示；`reply` 出现后折叠成一行“已处理 N 项过程”，展开后可看明细。
3. Agent 暂称 `sub line`：调用 Agent 后，在当前 Writer 主线下开启一条子时间线。右侧显示 Writer 派发给 Agent 的消息，左侧显示 sub agent 自己的运行时间线。完整逐字过程必须以后端持久日志为准，不能依赖前端 SSE 内存。
4. 决策：必须显示要做什么决策、原因/阻塞项、计划内容、选项和选项说明。
5. 理论上没有业务 SSE 可以静默丢弃。只有 `connected`、`ping`、流结束信号属于传输控制，不进业务 UI。

核心映射规则：

```text
event -> tag -> display_group -> renderer
```

`display_group` 按最终显示归宿分组，而不是按 SSE 事件来源分组：

| display_group | 显示归宿 | 默认标签 |
|---|---|---|
| `writer_reply` | Writer 正式气泡 / CLI reply 行 | `reply`, `message:reply` |
| `user_message` | 用户消息 | `message:user` |
| `decision_card` | 决策卡 / CLI 交互决策 | `decision`, `plan_ready`, `waiting_for_user` |
| `sub_line` | Agent 子时间线 | `agent`, `delegation`, `design_agent` |
| `processed_flow` | 过程流；reply 后折叠为“已处理 N 项过程” | `llm`, `model`, `plan`, `progress`, `tool`, `file`, `step`, `verify`, `workflow`, `mode`, `phase`, `state` |
| `git_panel` | 右侧 Git / 改动审核 | `git`, `checkpoint`, `branch`, `diff`, `changes` |
| `error_card` | 失败/错误卡 | `failed`, `error`, `cancelled` |
| `status_bar` | 顶部/右侧状态；CLI 短状态行 | `done`, `resumed`, `wait`, `running`, `idle` |
| `debug_log` | 完整日志和调试原文 | `raw_log`, `full_text`, `runtime_event`, `debug` |

后续显隐、折叠、过滤都应改 `display_group/tag` 映射，不再直接按事件名写 UI 分支。

## 需要呈现

| SSE | 业务含义 | 应该怎么呈现 | 现在怎么呈现 |
|---|---|---|---|
| `writer_message` | 已持久化消息同步。通常来自消息 API 或监听流回放。 | 按 `role` 放入会话消息区：用户消息右侧，`parts.reply=true` 的 Writer 消息作为正式回复；`parts.decision` 渲染决策卡。 | `sse.ts` 调 `sessionStore.upsertMessage()`；`WorkbenchView` 只把显式 reply 标记识别为正式回复，避免把中间诊断误折叠。 |
| `writer_response` + `output_type=reply` | Writer 给用户看的正式回复。 | 作为 Writer 左侧回复气泡。流式增量时更新同一个草稿；`output_meta.final=true` 时替换旧草稿，避免残留失败总结。 | 已这样做：`assistantDraft` 更新本地 `local-reply`；最终回复替换草稿。任务结束后重新拉消息，避免重复追加。 |
| `writer_response` + `output_type=text/code/email/...` | Writer 直接输出内容或过程说明。 | 进入过程流；`reply` 前展开，`reply` 后折叠。后端要给用户看的最终答复必须用 `output_type=reply`。 | 当前进入 `activityFeed` 的 LLM 过程组，不再静默。 |
| `writer_response` + `output_type=thought` | 内部思考、过程短语、模型中间文本。 | 进入过程流；不刷成聊天气泡；`reply` 后折叠。 | 当前以“LLM 过程”进入过程流，并保留原始内容用于展开查看。 |
| `writer_step` | 步骤、工具、验证、agent、决策步骤的状态变化。 | 普通步骤作为紧凑运行卡；`reply` 前展开，`reply` 后折叠。Agent 步骤进入 `sub line`：右侧是 Writer 派发消息，左侧是 sub agent 运行时间线。 | 已进入 `stepStore`；只读步骤聚合；当前仍有 Agent 特殊卡片残留；普通完成步骤在 reply 后折叠为“已处理 N 项过程”。 |
| `writer_progress` + `phase` | Runtime 阶段变化，如规划、执行、验证、完成。 | 更新顶部阶段、状态栏、运行占位文案；不产生聊天消息。 | 当前更新 `latestProgress` 和 `statusText`；顶部显示中文状态。 |
| `writer_progress` + `plan_progress` | 计划进度。 | 顶部/运行卡展示“已完成/总数、当前步骤、下一步”；长期任务可显示进度条。 | 已在顶部、运行占位卡、右侧 Status 显示计划进度条，并兼容 `total/total_steps`、`pct/progress_pct`。 |
| `writer_progress` + `verification` | 完成验证开始/结果。 | 验证开始显示“正在验证”；验证通过可以进入完成总结；验证失败显示可读失败摘要并引导修复。 | 当前主要更新状态栏；详细验证结果会作为 step 或最终回复间接呈现。 |
| `writer_progress` + `workflow` | 写作 Workflow phase 转换。 | 不进聊天正文；运行状态显示当前写作阶段。 | `WriterProgressEvent` 已保留 `workflow` 字段；前端在运行占位和右侧 Status 显示当前 Workflow。 |
| `writer_decision` + `decision_type=decision_point` | 真实决策点。 | 主消息区显示阻塞决策卡：标题、原因、阻塞项、选项和选项说明；输入区允许继续/补充。 | 已显示完整决策卡；后续 waiting 事件会合并到同一张卡，不再刷空卡。 |
| `writer_decision` + `decision_type=plan_ready` | 计划确认。 | 决策卡内展示目标、步骤、产出、验收标准、约束和选项。 | 已渲染计划内容；随后到达的 waiting 文案会补进同一张计划卡。 |
| `writer_decision` + `decision_type=waiting_for_user` | Writer 等用户输入。 | 顶部状态显示等待；输入栏解禁；若已有 plan/decision 卡，则合并问题；否则显示轻量等待卡。 | 已合并到已有决策卡，避免重复空卡。 |
| `writer_git` + `git_type=snapshot` | Git 当前状态快照。 | 不刷聊天；刷新右侧 Git 状态、脏文件摘要、审核入口。 | 已触发 `gitRefreshTick`，工作台即时刷新右侧 Git 图和 session changes。 |
| `writer_git` + `git_type=branch` | Writer 切换/创建任务分支。 | 右侧 Git 区更新当前分支；可短暂显示“切到分支”。 | 已即时刷新右侧 Git 图，并用中文状态显示“Git：分支更新”。 |
| `writer_git` + `git_type=checkpoint` | 生成检查点 commit。 | 右侧 Git 图新增 commit；运行状态可显示“已保存检查点”。 | 已即时刷新右侧 Git 图和改动审核入口，并显示“Git：检查点”。 |
| `writer_git` + `git_type=merge` | 推进 `writer/main` 或合并任务结果。 | 右侧 Git 图更新目标分支；不进聊天正文。 | 已即时刷新右侧 Git 图，并显示“Git：合并完成”。 |
| `writer_lifecycle` + `done` | 本轮完成。 | 停止运行态；状态变“已完成”；如果有最终回复，保留最终回复。 | 已停止运行态并显示“已完成”。 |
| `writer_lifecycle` + `failed` | 本轮失败。 | 停止运行态；在主消息区显示失败卡或失败回复，包含原因和可执行下一步。 | 已生成本地失败卡，显示原因和 details 摘要；状态栏同步中文失败原因。 |
| `writer_lifecycle` + `error` | Runtime 异常。 | 停止运行态；主消息区显示错误卡；状态栏显示“出错”。 | 已生成本地错误卡，显示原因和 details 摘要；状态栏同步“出错”。 |
| `writer_lifecycle` + `cancelled` | 用户取消。 | 停止运行态；状态栏“已取消”；可保留当前步骤现场。 | 当前停止运行态并显示“已取消”。 |
| `writer_lifecycle` + `resumed` | 从暂停恢复。 | 隐藏暂停态；状态栏显示“继续执行”。 | 当前设置 `awaitingUser=false`，状态栏显示“继续执行”。 |

## 传输控制，不进业务 UI

| SSE | 含义 | 应该怎么处理 | 现在怎么处理 |
|---|---|---|---|
| `connected` | SSE 握手成功。 | 不进业务 UI；可用于调试连接状态。 | 前端没有专门处理；默认忽略。 |
| `ping` | keepalive。 | 不呈现；只保持连接活跃。 | 前端没有专门处理；默认忽略。 |
| `TaskManager.signal_done()` 的 `None` | 结束 SSE 流。 | 不是业务事件；不呈现。 | 后端结束流，前端 `startStream` finally 停止运行态。 |

## 旧兼容事件

旧事件不是“不显示”，而是映射到同一套 UI：

- `writer_done` → lifecycle done。
- `writer_failed` → lifecycle failed。
- `writer_error` → lifecycle error。
- `writer_waiting_for_user` →等待用户。
- `writer_resumed` →继续执行。
- `writer_agent_started/progress/completed` →过程流的 Agent 组。
- `writer_git_branch/checkpoint/merge/snapshot` →应继续迁移到 `writer_git`；前端主路径不依赖旧名。

CLI 也遵守同一口径：先把 canonical 顶层字段和旧式 `data` 字段归一化，再按标签展示业务语义。除完整逐字日志外，CLI 默认不静默丢弃业务信息。真实 `writer_progress.loop_position=llm_call_started` 显示为 `model`；`writer_message` 显示为 `message:*` 或 `reply`；LLM 过程显示为 `llm`；文件类工具显示为 `file`；普通工具显示为 `tool`；`writer_step` 显示为 `step/tool/file/agent/verify`；`writer_progress.workflow/mode/verification` 显示为 `workflow/mode/verify`；`writer_decision` 显示为 `decision` 并触发交互输入；`writer_lifecycle` 负责 `done/failed/error/resumed/cancelled` 和 watch 退出。后续是否显示、折叠或过滤，应基于这些标签配置，而不是重新按事件名分叉。

## 当前差距

2026-06-21 实测新增差距：

1. 显示链路已开始转为“持久化优先”。后端收到可恢复运行事件后先写入 runtime event，再发 SSE；逐 token reply delta 不再写入 runtime event。剩余差距：前端主展示仍是 SSE 内存 + 持久化恢复混合模式，下一步应变成从持久化事件增量读取。
2. `AbortError` 不再等同于用户取消。前端连接被动中断会显示同步记录，并触发持久化历史刷新；只有后端 lifecycle/session status 为 cancelled 时才显示“已取消”。
3. Sub agent 已收敛到 `sub line` 方向。后端提供稳定 `sub_line_id` / `agent_run_id`，前端把同归属的思考、正文、工具、文件、diff、错误和最终结论挂入同一条子线。剩余差距：需要真实任务验收并行 sibling sub line 的视觉排序和折叠表现。
4. 并行 Agent 不应展示成一个额外的 `parallel` Agent。一次 Writer 输出里同时调用多个 Agent 时，应同时开启多条同级 `sub line`，按派发顺序排列；`parallel` 只是调度事实，不是一个可见业务节点。
5. 模型配置入口已收敛到 `lamwriter.modelRouting`。设置页和输入框下方模型切换都写同一份 Writer/Agent 模型分配；旧路由规则不再作为用户可操作入口。

已落实：

1. `writer_git` 事件会驱动右侧 Git 图和 session changes 即时刷新。
2. `writer_lifecycle.failed/error` 会进入主消息区失败/错误卡。
3. `writer_progress.plan_progress` 有独立进度条。
4. `writer_workflow_event()` 的 `workflow` 字段已进入 schema，不再丢失。
5. `docs/writer-integration-test.md` 已改为 canonical SSE 口径。

本轮新增：

6. `writer_response` 的非 reply/thought 不再静默，统一进入过程流。
7. 普通过程在 reply 后折叠，Agent 和决策卡不折叠。
8. 设计决策事件携带 question、task、blocking、potential decision、token estimate，前端完整展示。
9. DesignAgent 每轮成功输出不再丢弃，完整原文写入 runtime event；实时 SSE 只发摘要、预览和 `log_id`，避免长输出卡死 UI。
10. 正式回复改为显式 `parts.reply=true` 契约，前端不再把所有 assistant 文本猜成 reply。
11. 普通过程折叠和 activity 折叠状态已拆开；activity 默认每组只显示最近 5 条，展开后看更多。

## 建议规则

- 聊天正文固定显示用户消息、正式 Writer 回复、决策卡、失败/错误卡、sub line。
- 工具、读文件、搜索、验证、LLM 过程进入过程卡；reply 前展开，reply 后折叠。
- Agent 不跟普通过程一起折叠；以 `sub line` 表达 Agent 调用。每条 sub line 必须显示 Writer 派发消息、sub agent 进度、返回信息，展开时按 `log_id` 或持久事件加载完整逐字日志。
- Git 只更新右侧 Git 区和审核入口，不进聊天正文。
- keepalive、connected 和流结束信号不进业务 UI。
- 后端如果希望用户看到文本，必须发 `writer_response` 且 `output_type=reply`。
- 后端持久化正式回复时必须写 `parts.reply=true`。
- 后端如果只是过程状态，使用 `writer_step`、`writer_progress` 或非 reply `writer_response`，前端会进入过程流。
