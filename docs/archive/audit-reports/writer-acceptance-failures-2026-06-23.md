# Writer 实时链路验收记录（2026-06-23）

## 范围

本文件记录本轮围绕 Writer 实时显示链路的失败项、根因、修复状态和验收门禁。

验收依据：

- `docs/writer-db-transcript-design.md`
- `docs/writer-queued-input-and-realtime-design.md`

核心原则：

```text
后端结构化事实 -> DB transcript -> transcript API -> 前端渲染
```

前端主聊天区不得从 SSE、本地草稿、本地队列或临时运行态拼接业务正文。SSE 可以用于发起运行、生命周期通知和触发刷新，但不能成为 transcript 内容来源。

## 当前结论

本轮阻断项已修复并通过自动验收：

- 运行态 `model_text` 已入库但不显示：已修复。
- `waiting_request(permission)` live 分支没有可点击审批入口：已修复。
- 工具返回块重复或不能持续更新：已修复稳定块 ID 和覆盖更新。
- 命令执行中看不到过程输出：已新增命令 stdout/stderr 运行中更新。
- active 轮询粒度过大造成“大块跳出”风险：已从 700ms 降至 250ms。
- destructive 手工脚本进入 pytest collection：已删除 `test_original_task.py`，但后端全量 pytest 仍有历史失败，不能把全量 suite 视为绿色门禁。
- 旧 SSE store 内部正文/思考草稿会制造双链路认知负担：已删除 `assistantDraft`、`reasoningDraft` 及相关累加逻辑。

仍需注意的边界：

- 旧 SSE store 仍存在，但当前主聊天区只消费 DB transcript 投影；SSE 活动流只保留在运行通知和右侧辅助信息里。
- 命令输出按 stdout/stderr 行级或管道 flush 更新。没有产生可观察中间输出的工具，例如一次性 `write_file`，只能显示工具开始和完成事实，不能伪造不存在的中间结果。

## 已修复项

### 1. 运行态过程正文显示

根因：

- 前端把 DB `model_text` 映射成 `plan`，而 live 渲染分支过滤了 `plan`。

修复：

- `model_text` 成为独立的消息 part 类型。
- final reply 指向的 `model_text` 只渲染为最终回复。
- 非 final `model_text` 作为过程正文按 DB 顺序渲染。
- live 和 replay 使用同一 transcript 投影语义，区别只在展开策略。

验收：

- `members/writer/frontend/tests/runtime/transcript.test.ts`
- `members/writer/frontend/tests/runtime/transcriptProjectionProtocol.test.ts`
- `core/ui/tests/chat-thread-process.test.ts`

### 2. 权限等待审批入口

根因：

- `decision` 卡片只在非 live/history 分支渲染；waiting turn 被标记为 live 后，权限等待只能显示为普通过程行。

修复：

- live 分支复用同一套 `decision-card`。
- 点击批准/拒绝仍走已有 decision 提交流程，不新增平行审批链路。
- 后端在 permission request 出现时先落 `tool_call` waiting 块，再落 `waiting_request`。

验收：

- live waiting 和 replay waiting 都能显示可点击决策卡。
- 未审批时不生成 tool result，不把等待误显示成工具失败。

### 3. DB 持续写入与稳定更新

根因：

- 普通 `runtime.reply_delta` 过去只在 finish/usage 时同步 DB，运行中正文不会持续进入 transcript。
- `runtime.part(tool_result)` 缺少稳定 result block ID，容易产生重复块或刷新前后不一致。

修复：

- 每个模型调用使用稳定 `model_text` block ID。
- delta 到来即更新 DB，并递增 transcript revision。
- `tool_result` 使用稳定 `{tool_call_id}:result` block ID。
- 同一个 block 的后续更新覆盖可见内容，不创建重复块。

验收：

- `members/writer/backend/tests/test_writer_realtime_transcript_contract.py`
- `members/writer/frontend/tests/runtime/transcriptProjectionProtocol.test.ts`

### 4. 命令输出过程可见

根因：

- `run_command` 过去只在命令结束后返回完整 stdout/stderr，运行中没有可投影的工具结果事实。

修复：

- 命令启动时已有 `tool_call` running 块。
- 命令 stdout/stderr 产生时，后端持续写入同一个 running `tool_result` 块。
- 工具结果元数据去掉 `_runtime_*` 内部字段，避免内部运行上下文泄漏到公开 tool result。

验收：

- `members/writer/backend/tests/test_writer_core_kernel_adapter.py::TestRunCommandSuccess::test_run_command_emits_running_output_parts`

### 5. 前端刷新粒度

根因：

- active polling 为 700ms，容易产生“大块跳出”的观感。

修复：

- active transcript polling 调整为 250ms。
- 前端仍然只读 transcript API，不用 SSE delta 拼正文。

验收：

- `members/writer/frontend/src/views/CoreWorkbenchView.vue`
- `members/writer/frontend/tests/runtime/transcriptProjectionProtocol.test.ts`

### 6. SSE 正文草稿减法

根因：

- 主聊天区已经只读 DB transcript 投影，但 SSE store 内仍维护 `assistantDraft`、`reasoningDraft` 等旧草稿状态。
- 这些状态没有被主聊天区消费，却会让代码看起来仍有“前端拼正文”的第二条链路。

修复：

- 删除 SSE store 内部正文/思考草稿累加。
- 删除只服务旧草稿链路的 reply attachment 合并和 final response 判断函数。
- SSE store 保留运行发起、生命周期状态、持久化事件刷新和右侧辅助活动，不再维护 transcript 正文。

验收：

- 扫描 `members/writer/frontend/src`，无 `assistantDraft`、`reasoningDraft`、`isFinalResponseTextPayload` 残留。
- 前端测试和构建通过。

### 7. 全量测试门禁

根因：

- `members/writer/backend/tests/test_original_task.py` 是历史手工脚本，却以 `test_*.py` 命名进入 pytest collection，并在导入时清理真实工作目录。

已修复：

- 删除该 destructive 手工脚本。
- 当前自动测试只使用 pytest 临时目录和受控 fixture。

当前验收：

- `test_original_task.py` 不再阻断 collection。
- 流式 transcript 相关 targeted backend suite 已通过。
- 但 `py -3.14 -m pytest -q` 仍失败：41 failed、876 passed、6 skipped。

主要失败类别：

1. 历史协议测试仍断言旧事件字段 `event`，当前事件协议已改为 OpenAI/typed object 形态。
2. 历史状态测试仍断言旧 `active/completed/cancelled` 写入值，当前投影更偏向底层事实状态，例如 idle/running/waiting/completed/failed。
3. 若干 async E2E 测试缺少合适的 pytest async 标记或插件入口。
4. novel/TUI 类 E2E 依赖外部服务或真实后端，当前本地返回 502。
5. 少量权限/验收事件测试仍按旧默认策略断言。

处理原则：

- 这些失败不应阻断本次 DB transcript 流式链路的 targeted 验收。
- 但它们必须作为单独债务处理，不能在后续对外宣称“后端全量测试已恢复”。
- 后续清理应按类别迁移测试到当前协议，或把真实外部 E2E 移出默认 unit suite。

## 当前门禁结果

后端：

```powershell
cd E:\LamTools\members\writer\backend
py -3.14 -m pytest tests/test_writer_realtime_transcript_contract.py tests/test_writer_service.py tests/test_writer_core_kernel_adapter.py -q
```

结果：197 passed，1 个既有 Windows asyncio transport warning。

后端全量：

```powershell
cd E:\LamTools\members\writer\backend
py -3.14 -m pytest -q
```

结果：41 failed、876 passed、6 skipped。失败集中在历史协议/状态断言、未标记 async E2E、外部服务型 E2E 和旧权限策略断言；本轮未扩大范围处理。

前端：

```powershell
cd E:\LamTools\members\writer\frontend
npm test -- --test-reporter=spec
npm run build
```

结果：11 passed，build passed。

共享 UI：

```powershell
cd E:\LamTools\core\ui
npm run test:contract
npm run build
```

结果：36 passed，build passed。

## 后续人工验收清单

1. 运行中：用户消息、思考、过程正文、工具调用、工具返回都从 DB transcript 显示。
2. 命令运行：先出现工具块，再逐步出现 stdout/stderr。
3. 权限等待：显示批准/拒绝按钮，刷新后仍可操作。
4. 运行中发第二条：进入输入框上方队列托盘，不进入聊天正文。
5. 完成后：过程条折叠，最终回复不重复。
6. 刷新页面：画面、顺序、状态与刷新前一致。
