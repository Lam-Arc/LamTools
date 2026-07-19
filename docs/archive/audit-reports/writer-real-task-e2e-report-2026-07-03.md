# Writer 真实任务全角度测试报告（2026-07-03）

## 结论

本次测试覆盖了 Writer 浏览器工作台、设置页模型配置、GLM-5.2、Kimi-K2.6、思考开关开启/关闭、真实文件修改、命令执行、验证、历史落库与录屏。

核心任务产出可用：Writer 能通过浏览器输入框接收任务，调用真实模型完成一个小型工程任务，生成文件，通过测试，并完成第二轮验收复查。

但不能判定为“完全无问题”。发现 3 个用户可感知或验收相关问题：

1. 严重：用户任务里明确写了“不要提交”，Writer 仍在运行结束时创建了 Git checkpoint 提交。
2. 中等：会话侧栏存在重复 key 警告，项目分组重复时会触发 Vue warning。
3. 中等：数据库中的模型调用记录没有落 `provider/model` 字段，后续追溯“本轮实际用了哪个模型”证据不足。
4. 中等：本次录屏脚本等待条件不够严格，只等待最终回复标记出现，没有等待 UI 状态切换为 completed，导致最终截图仍显示 running。
5. 中等：过程中间轮的模型正文被渲染到了下方“最终回复/正文”位置，正文区边界不清。
6. 中等：过程区在高频事件到来时闪烁、重排，约 1:50 处肉眼明显。
7. 中等：多个阶段性模型正文被无分隔拼接成一段，约 2:33 处明显。

## 测试资产

| 类型 | 路径 |
|---|---|
| 原始 demo 视频 | `E:\LamTools\tmp\writer-real-task-e2e-2026-07-03\artifacts\final\writer-demo-full.webm` |
| Playwright 原始视频 | `E:\LamTools\tmp\writer-real-task-e2e-2026-07-03\artifacts\final\video\page@166b239b6b84cab80ea67ce1feb90f3d.webm` |
| 收尾截图 | `E:\LamTools\tmp\writer-real-task-e2e-2026-07-03\artifacts\final\final-screen.png` |
| 自动化进度日志 | `E:\LamTools\tmp\writer-real-task-e2e-2026-07-03\artifacts\final\progress.log` |
| 自动化结果 JSON | `E:\LamTools\tmp\writer-real-task-e2e-2026-07-03\artifacts\final\result.json` |
| 测试工作区 | `E:\LamTools\tmp\writer-real-task-e2e-2026-07-03\ops-pulse-formal` |
| 录屏脚本 | `E:\LamTools\tmp\writer-real-task-e2e-2026-07-03\run-writer-browser-demo.mjs` |

视频信息：

- 时长：311.76 秒。
- 大小：19,085,039 bytes。
- 录制方式：Playwright 浏览器上下文录制。
- 未做加速、未裁剪；记录从输入任务到最后回复文本出现的全过程。
- 注意：本次录屏脚本在最终回复标记出现后立即截图并结束，没有继续等待左侧状态徽标和输入区按钮切换到 completed/可发送态，因此视频末尾仍可能显示 running/stop。

## 测试计划

### 功能目录

| 编号 | 功能 | 来源 | 本次覆盖 |
|---|---|---|---|
| F1 | Writer 浏览器工作台打开与会话选择 | 文档+代码 | 覆盖 |
| F2 | 通过输入框输入任务并按回车发送 | 文档+代码 | 覆盖 |
| F3 | 模型快速切换 | 文档+代码 | 覆盖 |
| F4 | 思考开关切换 | 文档+代码 | 覆盖 |
| F5 | 内置 provider/model 列表展示 | 文档+代码 | 覆盖 |
| F6 | GLM-5.2 调用真实任务 | 代码 | 覆盖 |
| F7 | Kimi-K2.6 调用真实任务 | 代码 | 覆盖 |
| F8 | 真实文件读取、搜索、编辑与生成 | 文档+代码 | 覆盖 |
| F9 | 命令执行与测试验证 | 文档+代码 | 覆盖 |
| F10 | 运行过程与工具事件展示 | 文档+代码 | 覆盖 |
| F11 | 最终回复与收尾状态 | 文档+代码 | 覆盖 |
| F12 | 会话持久化与刷新后可追溯 | 代码 | 部分覆盖 |
| F13 | Git 状态/改动展示 | 文档+代码 | 覆盖 |
| F14 | 右侧检查点/自动存档行为 | 文档+代码 | 覆盖并发现问题 |

### 任务设计

| 任务 | 模型 | 思考 | 目标 | 覆盖 |
|---|---|---|---|---|
| T1 真实工程交付 | GLM-5.2 | Max 思考 | 修复 Ops Pulse 小工具，生成 CLI、测试、文档和输出文件 | F1-F4, F6, F8-F14 |
| T2 用户验收复查 | Kimi-K2.6 | 无思考 | 复查 T1 结果，读取产物、运行测试、报告是否可 demo | F2-F4, F7-F13 |
| T3 设置页核验 | 不调用 | 不调用 | 确认内置模型和思考预算在设置页可见 | F5 |

## 执行记录

### 服务状态

| 检查项 | 结果 |
|---|---|
| 后端端口 | `127.0.0.1:6173` 已监听 |
| 前端端口 | `127.0.0.1:6174` 已监听 |
| 后端健康检查 | `{"status":"ok","app":"LamWriter","writer_service":"ok"}` |
| 当前 Provider | 讯飞 MaaS，API key 已配置 |
| 当前默认模型 | Kimi-K2.6 |

### 设置页

设置页 `/settings` 可见讯飞 MaaS provider，且模型列表包含：

- GLM-5.2，上下文 500000，输出 16384，思考 10000。
- Kimi-K2.6，上下文 256000，输出 16384，思考 10000。

### T1：GLM-5.2 + Max 思考

操作方式：

- 打开 `http://127.0.0.1:6174/?session=edf8689a39ed46e4a1cd978b9a58d017`。
- 在输入区模型选择 `GLM-5.2`。
- 在输入区思考选择 `Max 思考`。
- 在输入框填入真实工程任务，按回车发送。

证据：

- `progress.log` 记录 `model_selected: GLM-5.2`、`thinking_selected: Max 思考`、`prompt_sent`。
- 后端日志显示请求 payload 使用 `xopglm52`。
- 后端日志显示首轮出现 `thinking_len=89`，证明思考内容有返回。
- 最终回复出现标记 `E2E_DONE_GLM52_MAX_THINKING`。

实际产出：

- 修复 `src/ops_pulse.py`。
- 更新 `README.md`。
- 新增 `docs/runbook.md`。
- 新增 `docs/stakeholder-email.md`。
- 生成 `dist/daily-brief.md`。
- 生成 `dist/summary.json`。
- 执行 `py -3.14 -m pytest -q`。

验收结果：

- `pytest`：2 passed。
- `dist/summary.json` 包含 `open: 2`。
- `dist/daily-brief.md` 包含 `INC-1001`、`backend: 1`、`cli: 1`。
- `README.md/src/docs/tests` 无 TODO 命中。

### T2：Kimi-K2.6 + 无思考

操作方式：

- 在同一浏览器会话中切换模型为 `Kimi-K2.6`。
- 切换思考为 `无思考`。
- 在输入框填入用户验收复查任务，按回车发送。

证据：

- `progress.log` 记录 `model_selected: Kimi-K2.6`、`thinking_selected: 无思考`、`prompt_sent`。
- 收尾截图显示输入区模型为 `Kimi-K2.6`，思考为 `无思考`，但状态仍显示 `running`，原因是截图早于后端完成落库约 0.53 秒。
- 最终回复出现标记 `E2E_DONE_KIMI26_NO_THINKING`。
- 后端会话 API 显示会话最终为 `completed`。

验收结果：

- Writer 读取 README、summary、daily brief、runbook、stakeholder email。
- Writer 再次运行 `py -3.14 -m pytest -q`。
- Writer 最终判断 Ops Pulse ready for demo。

备注：数据库模型调用表没有记录实际 `model` 字段，因此 Kimi 轮的后端模型归因只能由页面选择、默认 resolved config、录屏和 progress log 交叉证明，不能由数据库单点证明。

## 发现的问题

### P1：用户要求“不要提交”，但运行结束仍创建 Git checkpoint 提交

影响：

- 用户以为只是查看 diff / 不提交，实际工作区产生了 Git 提交。
- 这会破坏用户对“不要提交”的语义预期，也会影响后续 review、revert、提交历史管理。

证据：

```text
git log --oneline --decorate --max-count=2
5e4eb9d (HEAD -> master) checkpoint: 本轮完成自动存档
2ee1bd6 test seed
```

本轮任务文本明确包含：

```text
Run git status and git diff, but do not commit.
```

根因：

- 运行开始前会尝试自动存档。
- 运行结束后如果工作区有改动，也会执行自动 checkpoint。
- 这条路径不读取用户任务中的“不要提交”约束，也不区分用户显式提交与内部 checkpoint。

定位：

- `members/writer/backend/app/services/writer_service.py`：运行开始前 `checkpoint_if_dirty(..., reason="本轮开始前自动存档")`。
- `members/writer/backend/app/services/runtime_runner.py`：运行结束后 `checkpoint_if_dirty(..., reason="本轮完成自动存档")`。

建议：

- 自动 checkpoint 可以继续使用 Git 保存恢复点，但必须落在 Writer 内部 checkpoint 分支，不能移动用户当前分支，也不能更新用户可见的 `session.branch`。
- 用户明示 `do not commit` 时，不应靠任务文本正则跳过内部存档；真正要禁止的是用户可见正式提交、commit review 审批提交和当前分支历史污染。
- 版本图和会话投影必须区分内部存档分支与用户工作分支。

维护标注（2026-07-03）：初版修复曾采用识别 `do not commit/不要提交` 后跳过自动 checkpoint 的方案，已废弃。当前修复改为保留自动存档，但写入 `writer/checkpoint/{session_id}` 内部分支，并用 checkpoint 记录的 `base_head` 做回退/差异计算。

### P2：侧栏项目分组重复 key 警告

影响：

- 页面可继续使用，但控制台持续出现 Vue warning。
- 当多个会话共享同一 work root 或分组重复时，侧栏渲染可能出现状态错乱风险。

证据：

`result.json` 记录多条：

```text
[Vue warn]: Duplicate keys found during update
```

建议：

- 项目分组 key 不应只用 work root 或展示名，应使用稳定唯一 project id。
- 对历史重复项目做归并或迁移。

### P2：模型调用缺少可追溯字段

影响：

- 页面选择了模型，但数据库 `writer_transcript_model_calls` 中 `provider/model` 字段为空。
- 审计时不能只靠数据库确认每次调用实际使用的模型和思考参数。

证据：

- `writer_transcript_model_calls` 有调用记录、token 和状态，但 `provider/model` 为空。
- 后端日志能看到 GLM-5.2 的 `xopglm52` payload。
- Kimi 轮依赖 UI、progress log 和默认配置交叉证明。

建议：

- 每次模型调用落库时写入 provider id、model id、thinking_enabled、thinking_budget。
- 把这几个字段加入会话报告或运行面板，便于用户审计。

### P2：录屏脚本没有等待 UI 完成态

影响：

- 视频和截图能证明最终回复文本出现，但不能证明用户界面已经完成收尾。
- 用户审核视频时会看到左侧会话仍显示 `running`、输入区按钮仍是 `stop`，这会造成“是否真的结束”的疑问。

证据：

```text
2026-07-03T06:55:57.913Z marker_seen: E2E_DONE_KIMI26_NO_THINKING
2026-07-03T06:55:58.293Z screenshot_saved
2026-07-03T06:55:58.820Z 后端 session updated_at，status=completed
```

根因：

- 自动化脚本只等待最终回复标记出现在页面中。
- 脚本没有继续等待会话状态、左侧 badge、输入区按钮完成刷新。

建议：

- 补录正式 demo 时，等待 `GET /api/sessions/{id}` 返回 `status=completed`，再等页面上的 `stop` 按钮消失、左侧 badge 变为 `completed`。
- 报告中的收尾截图只能作为“最终文本已出现”的证据，不能作为“UI 完成态”的证据。

### P2：中间失败事件会把侧栏会话短暂标成 failed

影响：

- Playwright 原始视频约 1 分钟处，当前会话左侧 badge 从 `running` 短暂变为 `failed`，随后又恢复 `running` 并继续完成任务。
- 用户观看视频时会误以为整轮任务已经失败。

证据：

```text
00:55 左侧仍为 running，页面显示正在运行 pytest。
00:60 左侧短暂显示 failed。
00:65 左侧恢复 running，Writer 已识别测试失败并继续修复。
```

事件事实：

- `06:51:39`：`py -3.14 -m pytest -q` 返回 exit code 1，两个测试失败。这是任务种子里的预期失败，用于驱动修复，不代表会话失败。
- `06:51:43`：一个保护性工具调用失败，提示“先改生产代码再继续跑命令”。
- `06:51:43`：模型 API 返回一次 503：`The system is busy, please try again later`。
- `06:51:52`：Writer 继续输出“测试失败很明确”，并开始修复。

根因判断：

- UI 把子事件的 `failed` 状态投影到了会话 badge 上。
- 会话级状态应由 turn/session lifecycle 决定，不能被单个工具失败、预期测试失败或可恢复模型重试覆盖。

建议：

- 侧栏会话状态只读 session lifecycle：`running/completed/failed` 应来自 turn 终态。
- 工具失败、测试失败、模型可恢复重试只显示在时间线中，不能把整个会话打成 failed。

### P2：可恢复模型错误缺少明确重试/加载可视反馈

影响：

- Playwright 原始视频约 `00:06` 处，页面出现红点 `error` 和 503 文案，但没有明显转圈、加载条、倒计时或“正在重试”的稳定提示。
- 右下角仍是 `stop`，左侧会话仍为 `running`，说明任务未结束；但用户只能看到错误行，无法判断 Writer 是否还在自动重试。
- 该错误行右侧被省略号截断，完整 provider 错误内容无法直接从页面读取、展开或复制。

证据：

```text
00:05.5-00:10.0：画面持续显示 error 行，未看到明确 spinner / retry 状态。
00:06 画面：错误文本显示到 `type":"serve...` 后被截断。
06:50:51：事件 seq=4，LLM API error 503。
06:50:52：事件 seq=5，模型请求重试中 (1/9)。
06:50:53：事件 seq=6，模型请求重试中 (2/9)。
06:50:59：事件 seq=8，模型继续输出正文，说明重试成功恢复。
```

帧证据：

- `tmp/writer-real-task-e2e-2026-07-03/artifacts/final/review-frames/t006_0.png`
- `tmp/writer-real-task-e2e-2026-07-03/artifacts/final/review-frames/t010_0.png`

根因判断：

- 后端已经发出重试状态事件，但前端没有把该状态以稳定、醒目的方式投影到用户可见区域。
- 当前展示更像“已失败”，而不是“遇到可恢复错误，正在自动重试”。
- 错误详情使用单行截断展示，缺少展开、复制或详情弹层，降低用户和测试人员定位问题的能力。

建议：

- 可恢复 provider 错误应显示为“重试中”状态，而不是只保留红色 error 行。
- 同一模型请求的 error/retry/recovered 应在同一个过程项内原位更新，例如：`模型繁忙，正在重试 2/9`。
- 错误行应支持展开完整详情和一键复制，默认可显示简短摘要，但不能只保留不可查看的省略文本。
- 只有最终放弃重试后，才把该模型请求显示为终态失败。

### P2：中间轮正文被落到最终回复位置

影响：

- Playwright 原始视频约 55-65 秒处，下方正文区出现了类似 `I'll start by inspecting...`、`I have enough context...` 这类中间轮模型正文。
- 这些内容属于过程中的阶段性输出，不是最终回复。
- 用户会误以为 Writer 已经给出了最终答案，或者误判“最终回复”内容不完整、不准确。

预期：

- 下方非过程正文区只应展示最后一轮、终态的 assistant 正文。
- 中间轮的模型正文、计划、阶段性说明、工具前后说明应留在过程时间线里，或作为过程项折叠展示。
- `runtime.part` / `model_text` 这类中间事件不能直接等同于最终回复。

证据：

```text
00:55-00:65：任务仍在 running，测试还未修复完成，但下方正文区已经出现阶段性 assistant 文本。
```

根因判断：

- 前端投影没有严格区分“过程模型文本”和“终态最终回复”。
- 或者后端投影把中间 `model_text` 事件标成了可作为正文展示的消息。

建议：

- 明确 UI 分区规则：过程时间线展示所有中间输出；最终回复区只消费 turn 完成事件里的最终 message。
- 如果需要展示中间模型文本，应作为过程块显示，不应进入最终正文流。

### P2：过程区高频更新时闪烁、重排

影响：

- Playwright 原始视频约 1:50 处，过程区出现明显一闪一闪的视觉抖动。
- 用户会感觉过程面板不稳定，难以阅读当前正在发生什么。

证据：

```text
01:45-01:55：页面不断插入/完成 checklist 和 tool_call 过程项，同时夹杂模型 503 重试状态。
01:50 帧：过程块位于上方，正文区在下方累积阶段性内容，整体布局正在频繁重排。
```

对应事件：

- `06:52:34`：多个 checklist/tool_call 事件连续完成。
- `06:52:35`：模型 API 503。
- `06:52:36`：显示“模型请求重试中 (1/9)”。
- `06:52:37`：显示“模型请求重试中 (2/9)”。
- `06:52:40`：新的模型正文和工具调用继续进入页面。

根因判断：

- 过程项可能在 `running/completed/failed` 状态切换时被重新插入或重建，而不是稳定更新原有节点。
- 中间模型正文落到下方正文区后，与过程区共同推动页面重排。
- 高频 `runtime.part` / `tool_call` / `usage` 事件没有被前端合并节流或稳定定位。

建议：

- 每个过程项使用稳定 `item_id/event_id` 做原位更新，不要在状态变化时重建 DOM。
- 对同一工具调用的 partial/result 事件合并更新。
- 对 retry/status/usage 这类高频状态做节流或单行替换。
- 修复“中间轮正文进入最终正文区”后，再复测该处闪烁是否仍存在。

### P2：阶段性模型正文无分隔拼接

影响：

- Playwright 原始视频约 2:33 处，下方正文区出现多个阶段性模型回复直接拼接在一起：

```text
I'll start by inspecting...
...I have enough context...
...Let me set up a checklist...
...Now let me fix...
...Now complete...
...Let me verify...
...Now run the tests...
```

- 这些内容没有消息边界、没有换行分隔，读起来像一段错乱的最终回复。
- 用户无法分辨哪些是过程说明，哪些是最终结论。

对应事件：

- `06:53:21`：Writer 已创建 `docs/runbook.md`。
- `06:53:21`：Writer 已创建 `docs/stakeholder-email.md`。
- `06:53:21`：模型 API 又返回一次 503。
- `02:33` 画面处仍在 running，正文区已经累积了多轮阶段性文本。

根因判断：

- 前端把多个 `model_text` / `agentMessage` 片段追加到了同一个正文流。
- 不同模型调用轮次之间没有独立消息容器。
- 中间轮文本本不应进入最终正文区；即使展示，也必须按模型调用/turn/part 分段。

建议：

- 对正文消息按最终回复块 ID 或 turn terminal message 建立唯一来源。
- 中间 `model_text` 按 model call 分组放在过程区。
- 前端渲染时禁止把不同 model call 的文本直接字符串拼接。

## 外部不稳定因素

GLM-5.2 首轮多次遇到 503：

```text
The system is busy, please try again later.
```

Writer 的重试机制最终恢复并完成任务，没有导致本次测试失败。但 00:06 处可见状态不清晰：后端已经进入重试，UI 却主要停留在红色 error 行，用户无法确认是否仍在自动恢复。

## 修复记录（2026-07-03）

本轮已按上述问题做代码修复，原始视频问题保留为历史证据，后续需要重新录制 demo 才能覆盖视觉验收。

| 问题 | 修复状态 | 修复内容 | 验证 |
|---|---|---|---|
| 自动 checkpoint 污染用户分支 | 已修复 | 自动存档保留，但写入 `writer/checkpoint/{session_id}` 内部分支；创建/恢复检查点不移动当前分支，`session.branch` 只代表用户可见分支；版本图过滤内部 checkpoint 分支；`do not commit` 不再作为文本跳过条件 | `test_checkpoint_is_stored_on_internal_branch_without_committing_user_branch`、`test_run_turn_keeps_internal_checkpoints_for_do_not_commit_task` |
| 侧栏项目分组 duplicate key | 已修复 | 项目组与孤儿会话组的展示 key 加 `project:` / `orphan:` 命名空间，保留原 workRoot 分组语义 | `npm run build` |
| 模型调用缺少 provider/model/thinking 审计字段 | 已修复 | model call 落 `provider/model/metadata.model_context`，投影结果也返回这些字段 | `test_runtime_reply_delta_updates_model_text_before_finish` |
| 录屏脚本未等待 completed UI | 已修复脚本 | marker 出现后继续等待后端 session `completed`，再等待页面 stop 按钮消失后截图 | `node --check tmp/.../run-writer-browser-demo.mjs` |
| 中间模型正文进入最终回复区 | 已修复 | 前端只把同一轮最后一个已完成 assistant 文本作为最终正文；运行中/中间文本留在过程 parts | `selectors only put the final completed agent message in assistant content` |
| 多段阶段性正文无分隔拼接 | 已修复 | 禁止多个 `agentMessage` 直接字符串拼接；中间 `model_text` 在过程区展开显示 | `npm test` |
| 可恢复错误把会话短暂标 failed | 已修复 | Core 快照区分过程项失败和 turn 终结失败；普通 failed message/error part 不再终结整轮 | `test_recoverable_item_error_does_not_fail_running_turn` |
| 503 错误被省略且不可展开 | 已修复 | 错误/状态过程项支持展开完整详情和复制，错误项默认展开 | `npm run build` |
| 过程区约 1:50 闪烁重排 | 已缓解，待重录验证 | 最终正文与过程文本分离，减少下方正文区随高频过程事件重排；视觉稳定性需用新 demo 视频确认 | 待新录屏 |

本轮验证命令：

```powershell
py -3.14 -m pytest core/tests/test_run_item_snapshot.py -q
py -3.14 -m pytest members/writer/backend/tests/test_writer_app_runtime_bridge.py members/writer/backend/tests/test_writer_app_queue.py members/writer/backend/tests/test_writer_realtime_transcript_contract.py -q
py -3.14 -m pytest members/writer/backend/tests/test_session_changes.py members/writer/backend/tests/test_writer_service.py::test_run_turn_keeps_internal_checkpoints_for_do_not_commit_task members/writer/backend/tests/test_writer_app_server_protocol.py::test_session_git_graph_and_changes_operations_return_git_state -q
py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py -q
py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_session_changes.py -q
npm test
npm run build
node --check tmp/writer-real-task-e2e-2026-07-03/run-writer-browser-demo.mjs
```

验证备注：

- `core/tests/test_run_item_snapshot.py` 单独运行通过：13 passed。
- backend runtime/app queue/realtime transcript 目标集合通过：39 passed。
- checkpoint/session 最小回归集合通过：10 passed。
- `test_writer_service.py` 全文件通过：24 passed。
- `test_writer_app_server_protocol.py` + `test_session_changes.py` 通过：63 passed。
- `npm test` 通过：24 passed。
- `npm run build` 通过。
- Windows Python 3.14 下 pytest 结束时仍出现 `_ProactorBasePipeTransport.__del__` 的关闭管道 warning；断言均已通过，和本次修复无关。
- 曾尝试把 `core/tests` 与 backend 测试放在同一个 pytest 命令中运行，因测试包导入名冲突报 `ModuleNotFoundError: No module named 'tests.test_run_item_snapshot'`；改为 Core 与 backend 分开执行后通过。

## 最终判定

| 维度 | 判定 |
|---|---|
| 浏览器真实输入路径 | 通过 |
| GLM-5.2 | 通过，有 503 重试但恢复；重试可视反馈不足 |
| Kimi-K2.6 | 通过 |
| 思考开启 | 通过 |
| 思考关闭 | 通过 |
| 真实文件任务完成度 | 通过 |
| 自动化验证 | 通过 |
| 用户无问题体验 | 原始视频不通过；代码层已修复，待重录验证 |
| 视频完成态证据 | 原始视频不通过；录屏脚本已修复，待重录 |
| 完全可用 | 待新 demo 视频确认 |

结论：原始视频不能证明 Writer “完全无问题”。本轮已修复自动 checkpoint 分支隔离、侧栏 key、模型审计、过程/最终正文边界、可恢复错误状态和错误详情展示，并修正录屏等待条件；下一步需要用修复后的代码重新录制完整 demo 视频做最终验收。
