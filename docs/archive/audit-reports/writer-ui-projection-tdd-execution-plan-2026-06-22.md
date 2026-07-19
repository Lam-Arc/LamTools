# Writer 消息流显示改造 TDD 执行计划

> 日期：2026-06-22  
> 归档基线：`967d78b chore: archive writer message flow baseline`  
> 设计文档：`docs/writer-ui-projection-redesign-2026-06-22.md`  
> 参考文档：`docs/消息流参考.txt`、`docs/writer-db-transcript-design.md`、`docs/writer-queued-input-and-realtime-design.md`  
> 执行要求：先测试，后实现；每个纵向切片完成后自审；除测试外，本计划阶段不写实现代码。

## 1. 当前红灯

本计划写入前已先补测试，并确认当前代码失败。

### 后端状态红灯

文件：

```text
members/writer/backend/tests/test_writer_transcript_service.py
```

新增测试：

```text
test_stale_status_cache_does_not_make_turn_running
```

当前失败：

```text
assert 'running' == 'failed'
```

含义：`status_cache="running"` 仍会把没有 final reply、没有 waiting request、没有 active producer 的 turn 投成 running。设计要求 cache 只能是历史项，不能作为当前状态事实。

### 前端 projection 协议红灯

文件：

```text
members/writer/frontend/tests/runtime/transcriptProjectionProtocol.test.ts
```

新增测试：

```text
transcript patch and refreshed snapshot render the same chat thread
transcript patch gap requires snapshot refetch instead of local guessing
```

当前失败：

```text
ERR_MODULE_NOT_FOUND: src/runtime/transcriptProjectionProtocol.ts
```

含义：前端还没有唯一的 projection update 接口，无法保证直播 patch 和刷新 snapshot 进入同一 store 后渲染一致。

## 2. 总体验收

实现完成后必须满足：

1. 刷新前后 transcript 样式一致。
2. 运行中工具调用先显示 running block，再持续更新输出和产物。
3. 聊天区不再消费 `assistantDraft`、`activityFeed`、raw OpenAI chunk、旧 writer_step/progress 作为主显示内容。
4. SSE 只做 revision/patch 通知，不拥有业务事实。
5. queue tray 只来自 queued-inputs projection；发送按钮在运行中仍允许创建队列项。
6. `status_cache` 不再决定当前状态。
7. patch 丢失或 revision 不连续时，前端 refetch snapshot，不本地猜。
8. 工具审批/ask/upload 等 waiting 不显示为工具失败。
9. 每个删除项都有测试或 grep 证据证明不再被主链路使用。

## 3. 执行原则

1. 每次只做一个纵向切片：红灯 -> 最小实现 -> 测试通过 -> 删除债务 -> 自审。
2. 不做横向大改：不要先改完所有后端，再改所有前端。
3. 不新增第三套直播态：如果某个改法需要新的前端本地业务状态，先停下审查。
4. 不用 fallback 掩盖根因：gap 可以 refetch snapshot，但不能在本地拼半截业务内容。
5. 优先复用现有 transcript、queued_input、revision、projector。
6. 任何继续保留的旧事件分支必须证明只服务 debug/历史兼容，不进入主 renderer。

## 4. 纵向切片

### Slice 1：状态事实优先

目的：修掉 stale running 根因。

红灯：

```powershell
py -3.14 -m pytest members/writer/backend/tests/test_writer_transcript_service.py -q
```

最小实现方向：

1. 当前状态推导只看：
   - completed final reply block
   - terminal failure
   - open waiting request
   - open active producer
2. `status_cache` 仅作为投影缓存或历史字段，不参与当前状态判断。
3. 如需保留 cache 写入，只能在 projection 后同步缓存，不能反向覆盖事实。

完成条件：

```text
test_stale_status_cache_does_not_make_turn_running 通过
原有 transcript status tests 仍通过
```

清理：

1. 搜索 `status_cache` 当前状态判断点。
2. 删除或降级所有“cache -> current status”的主链路。

### Slice 2：前端 projection update 接口

目的：建立 snapshot/patch 同形入口。

红灯：

```powershell
cd members/writer/frontend
npm test -- --test-reporter=spec tests/runtime/transcriptProjectionProtocol.test.ts
```

最小实现方向：

新增一个小而深的前端模块，接口只做一件事：

```text
applyTranscriptProjectionUpdate(current, update) -> snapshot | null
```

约束：

1. `transcript.snapshot` 直接替换当前 snapshot。
2. `transcript.patch` 只有在 `current.revision == patch.base_revision` 时合并。
3. patch gap 返回 `null`，由调用方触发 refetch。
4. 合并后的 snapshot 继续交给现有 `projectTranscriptSnapshot()`。

完成条件：

```text
patch 合并后的 ChatThread 消息 = 完整 snapshot 的 ChatThread 消息
gap 测试返回 null
```

清理：

1. 不要把合并逻辑写进 Vue view。
2. 不要让 SSE store 直接生成 MessagePart。

### Slice 3：后端 committed projection patch

目的：让后端在 DB commit 后提供同形 patch，而不是 raw runtime event。

先补测试：

```text
tests/test_writer_transcript_projection_patch.py
```

建议行为测试：

1. `upsert_block` 后，patch operation 的 block shape 与 snapshot block shape 一致。
2. patch revision 单调递增。
3. patch 必须在 commit 后可被 snapshot 读到。
4. tool_call running block 在 tool_result 前可见。

最小实现方向：

1. 复用现有 transcript projection 的 `_project_block` 形状。
2. 如果第一阶段不发 patch 内容，就发 revision notification 并 refetch snapshot；但测试仍应保护 patch 形状，避免未来乱做。
3. 后端不能再发送 raw chunk 给 chat renderer。

完成条件：

```text
后端 patch 形状测试通过
前端 patch/snapshot 等价测试通过
```

清理：

1. 标记并逐步删除主路径里的 `writer_reply_delta`、OpenAI chunk 前端正文拼接。
2. 保留 transport 事件时，字段名应表达 notification，不表达 UI content。

### Slice 4：单一前端 transcript store

目的：直播和刷新都进入同一份前端 projection state。

先补测试：

```text
前端 store 测试：snapshot replace 与 patch apply 后 messages 一致
前端 store 测试：patch gap 会调用 refetch，不会本地猜
```

最小实现方向：

1. `refreshCoreTranscript()` 走 `transcript.snapshot` update。
2. SSE 收到 revision/patch 走 `applyTranscriptProjectionUpdate()`。
3. `messages` 只由 `projectTranscriptSnapshot(currentSnapshot)` 生成。

完成条件：

1. 刷新和直播对同一 fixture 输出同一 messages。
2. Vue view 不再合并 SSE activity/draft 进 chat thread。

清理：

1. `assistantDraft`、`reasoningDraft`、`activityFeed` 不得作为 chat thread 主输入。
2. 如果右侧调试面板仍需要 activity，只能读取 transcript projection 或 debug-only 数据。

### Slice 5：工具调用流式可见

目的：修复运行工具时用户看不到任何过程。

先补测试：

```text
后端：runtime.tool.started 创建 running tool_call block
后端：runtime.tool.finished 更新同 call_id 的 result/artifact
前端：running tool_call 在未完成 turn 中展开显示
```

最小实现方向：

1. 工具开始立即落库为 `tool_call` block。
2. stdout/stderr/result preview 批量更新同一 block 或子 block。
3. artifact 只存 id/path/type，不内联大内容。
4. turn 未完成时默认全部展开；完成后折叠。

完成条件：

1. 命令运行时 ChatThread 可见 tool block。
2. 刷新后同一个 tool block 仍存在，样式一致。

清理：

1. 删除 activity feed 对工具过程的主显示职责。
2. 删除“工具执行完成后才补一个结果”的延迟显示路径。

### Slice 6：排队输入不被 loading 禁用

目的：运行中发送应进入 queue tray，不回填输入框、不假消息。

先补测试：

```text
前端：running/loading 时 submit 非空文本会调用 createQueuedInput
前端：queue projection 返回前不插入聊天正文
后端：failed 不自动 dispatch，completed 才自动 FIFO dispatch
```

最小实现方向：

1. submit gate 只拦截空文本。
2. 是否 idle 由后端 projection 读取。
3. 非 idle 调 queued-inputs API。
4. queue tray 只读 queued-inputs API。

完成条件：

1. 运行中点 enter/send 后，文本进入托盘。
2. 输入框不闪回原文本，聊天区不出现假用户消息。

清理：

1. 删除 `loading` 对发送/排队入口的硬禁用。
2. 删除本地 pending 消息进入 transcript 的入口。

### Slice 7：旧直播态拔除

目的：根除双链路，而不是留下隐患。

检查清单：

```powershell
rg -n "assistantDraft|reasoningDraft|activityFeed|writer_reply_delta|chat.completion.chunk|writer_step|writer_progress|writer_part" members/writer/frontend/src
```

允许保留：

1. debug-only 面板。
2. transport 连接错误提示。
3. 历史事件兼容解析，但不能进入 chat renderer。

不允许保留：

1. 生成正文。
2. 生成工具过程。
3. 决定 running/waiting/completed/failed。
4. 决定发送还是排队。

完成条件：

1. grep 结果每一项都有归属说明。
2. 无法证明价值的旧代码删除。

## 5. 验证命令

后端：

```powershell
py -3.14 -m pytest members/writer/backend/tests/test_writer_transcript_service.py -q
py -3.14 -m pytest members/writer/backend/tests/test_queued_input_service.py -q
py -3.14 -m pytest members/writer/backend/tests/test_writer_service.py -q
```

前端：

```powershell
cd members/writer/frontend
npm test
npm run build
```

跨包影响：

```powershell
.\scripts\test.ps1 all
.\scripts\build.ps1 all
```

手动验收：

1. 新 session 发送简单任务。
2. 工具执行中观察 tool block 是否立即出现并持续更新。
3. 运行中发送第二句话，确认进入 queue tray。
4. 刷新页面，确认聊天区、过程、队列与刷新前一致。
5. 等 turn 完成，确认第一条队列自动派发。
6. 触发 permission waiting，确认出现决策卡，不是错误信息。

## 6. 债务登记

执行中遇到以下内容必须登记并清理：

| 债务类型 | 处理 |
|---|---|
| DB 没有事实但 UI 能显示业务内容 | 删除或改为 projection |
| 前端从事件名推断业务状态 | 删除或改为后端 status |
| 旧事件和新 projection 同时驱动 chat thread | 删除旧驱动 |
| 本地 queue/pending 与 DB queue 并存 | 删除本地 queue/pending |
| patch 形状和 snapshot 形状不一致 | 停止实现，回到设计修正 |
| 为单个截图写的样式/逻辑特判 | 删除或抽成通用规则 |

## 7. 自审

对照设计文档，本执行计划满足：

1. 先提交归档：已完成，基线 `967d78b`。
2. 先设计：已完成，见 `docs/writer-ui-projection-redesign-2026-06-22.md`。
3. 先测试：已新增并运行红灯测试。
4. TDD：每个切片都有红灯、最小实现、完成条件、清理项。
5. 不增加复杂度：只新增一个 projection update seam，删除旧双链路。
6. 不降低可用性：queue、tool、waiting、artifact、refresh/live 都覆盖。
7. 不留冗余：最后有 grep 清理和债务登记。

待后续执行者注意：如果实现过程中发现必须新增第三套状态或 renderer，说明计划偏离设计，应先暂停并回审，不应继续编码。
