# LamTools 核心简化审查

日期：2026-06-29

维护标注（2026-06-30）：Writer 前端 `members/writer/frontend/src/appServer/reducer.ts` 已删除，产品主线已改为后端权威 snapshot + 前端 `snapshot.ts` hydration + selectors。本文中关于“前端 reducer”的描述属于 2026-06-29 审查时状态；剩余债务集中在事件词汇、transcript/app snapshot 边界、工具和 prompt 复用。

目标：在不牺牲 Writer/Artist 当前能力的前提下，把核心代码压到更简单、更通用、更少故障的形态。原则是：能复用已有 Core 的，不在 member 重写；能删除兼容层的，不再增加新层；能用一个权威状态表达的，不做多次翻译。

参考成熟方案：

- OpenAI Agents SDK：agent loop、tools、guardrails、handoffs/agents-as-tools、sessions、tracing 是主干能力。
- Claude Code：项目指令、subagents、权限/工具范围、记忆与上下文是分层能力。

对应到 LamTools：`CoreLoopKernel + RuntimeKit` 是正确方向，但当前实现的问题是“主线之外的重复翻译和重复实现太多”，不是缺少新能力。

## 总结判断

当前最该优化的不是继续加 agent 功能，而是做四类减法：

1. **复用 Core 协议**：LLM、Prompt、Tool、Event、Memory、Guardrail 已经有 Core 协议，Writer/Artist 不应继续各自维护相同转换逻辑。
2. **收窄核心循环**：Kernel 只保留循环骨架，流式 UI part、上下文压缩、approval 文案、重试展示都应从主循环文件移出去。
3. **建立单一权威事件形状**：Writer 已删掉前端 reducer 主线，但仍有 CoreEvent、WriterRuntimeEvent、AppEvent 和 transcript/app snapshot 边界需要继续收敛。
4. **把大文件改成深模块，不是拆成碎片**：拆分目标是减少调用者需要知道的接口，而不是把一个大文件拆成更多浅文件。

## 最高收益优化点

### 1. LLM 适配统一：只保留一个 Core 适配主线

现状：

- Core 已有 `core/src/lamtools_core/llm/adapter.py` 和 `helpers.py`，负责 `LLMRequest` 到 OpenAI-compatible payload、响应、流式 chunk 的转换。
- Writer 又在 `members/writer/backend/app/utils/llm_client.py` 和 `members/writer/backend/app/core/writer/core_kernel_adapter.py` 里重复做消息转换、tool call 解析、thinking/usage/stream 兼容。
- Artist 也在 `members/artist/backend/app/utils/llm_client.py` 和 `members/artist/backend/app/core/artist/core_kernel_adapter.py` 里做一套类似转换。

简化方案：

- Core 增强为唯一 provider transformation 层：`LLMRequest -> payload -> LLMResponse/LLMStreamEvent`。
- Writer/Artist 的 LLM client 只保留三件事：配置读取、HTTP 调用、错误包装。
- `WriterLLMClientAdapter`、`ArtistLLMClientAdapter` 不再手写消息转换，直接调用 Core adapter。
- `llm_adapter_profiles.py` 中 provider profile 能力保留，但挂到 Core adapter 使用，而不是 Writer 独占。

收益：

- tool call、usage、thinking、stream 只修一次。
- 新模型/新供应商只新增 profile 或 adapter，不碰 WriterKit/ArtistKit。
- Core 更通用，member 更薄。

判定：可靠方向。优先级 P0。

### 2. Prompt 拼接改为 fragment provider，WriterKit 不再手写大段拼接

现状：

- Core 已有 `PromptContext`、`PromptPart`、`BasePromptAssembler`。
- Writer 的静态 prompt、项目规则、skills、runtime now、git、session memory、plan progress、failure recovery 都拼在 `WriterKit.build_model_request`。
- Artist 仍有单独 `PromptAssembler`，但能力较薄。

简化方案：

把 prompt 拆成 provider，而不是在 Kit 中拼字符串：

- `StaticPromptProvider`：persona、platform、reply contract、execution discipline。
- `ProjectInstructionProvider`：AGENTS.md、project instructions。
- `MemoryPromptProvider`：session memory、cross-session memory。
- `RuntimeContextProvider`：时间、git、active plan、queued guidance、recent failures。
- `SkillPromptProvider`：skills 和资源目录。

目标接口：

```python
messages = await prompt_assembler.assemble(context)
return LLMRequest(messages=messages, tools=tool_registry.model_tools())
```

收益：

- prompt 顺序可测试，新增上下文不用改 Kit 主体。
- 可复用 Core 的预算裁剪。
- Writer/Artist 可以共享 fragment 机制，只保留不同 provider。

判定：存疑转可靠的关键一步。优先级 P1。

### 3. 工具执行改为 ToolRegistry + PermissionPolicy，不再让 WriterKit 管全部工具细节

现状：

- Core 已有 `ToolRegistry`、`ToolSpec`、`ToolCall`、`ToolResult`。
- Writer 的读写文件、搜索、命令、Git、Web、browser、skill、checklist、agent、MCP 都混在 `core_kernel_adapter.py`。
- WriterKit 同时负责工具可见性、权限注入、MCP dispatch、agent dispatch、工具结果格式化。
- Artist 也有 `ARTIST_TOOL_SPECS` 和旧 `ArtistToolExecutor` 两套工具形状。

简化方案：

保持 Core 不认产品名，但抽出通用可选 toolkit：

- `core.toolkits.workspace_read`：read/list/search/inspect。
- `core.toolkits.workspace_write`：write/edit，必须依赖权限策略。
- `core.toolkits.shell`：run_command/run_tests，必须依赖权限策略。
- `core.toolkits.git`：status/diff/commit review 的通用部分。
- `core.toolkits.web`：web_fetch/web_search/browser_check。

member 只做注册：

```python
registry = ToolRegistry()
register_workspace_tools(registry, work_root, permission_policy)
register_writer_control_tools(registry, writer_state)
register_mcp_tools(registry, mcp_registry)
```

收益：

- Tool 的 spec、权限、执行、展示元数据分开。
- 子代理也复用同一套工具注册，不再复制 allowlist/worktree 逻辑。
- Artist 或未来 Editor 可复用 workspace/image/web 工具，不必复制 Writer 代码。

注意：只把通用工具能力抽 Core；Writer 特有的 checklist、completion verifier、architecture handoff 留在 Writer。

判定：高收益，但要分阶段迁移。优先级 P1。

### 4. Writer 事件链路合并：只保留一个权威状态表达

现状：

- `CoreEvent` 是 Kernel 输出。
- `WriterRuntimeEvent` 是 Writer 落库事件。
- `runtime_bridge.py` 再转成 App Server event。
- 审查时后端 `app_server/reducer.py` 和前端 `appServer/reducer.ts` 各自维护一份 reducer；2026-06-30 已删除前端 reducer，前端只 hydrate 后端 snapshot。
- 前端还有 transcript projection 和 selectors。

这导致同一件事被多次解释：状态、tool item、approval、metrics、artifact、final reply 都可能在不同层有不同语义。

简化方案：

选一个权威形状：建议是 **RunItemSnapshot**，接近前端真正要展示的结构：

- turn
- item
- request
- artifact
- queue
- metrics
- status

后端 reducer 生成权威 snapshot，前端只做 selectors：

```text
CoreEvent -> canonical run item event -> server snapshot -> frontend selectors -> UI
```

前端不再重复 reducer；如果必须离线 replay，则从后端生成 TypeScript reducer 或放到共享包，不手写两份。

收益：

- 状态漂移直接减少一半。
- “waiting_request(permission) 可点 / replay 可见 / live 可见”这类 bug 会少很多。
- UI 只关心展示，不再解释 runtime 协议。

判定：P0。比拆大文件更先做，因为这是历史 bug 高发区。

### 5. CoreLoopKernel 瘦身：循环文件不承载展示协议

现状：

`core/src/lamtools_core/kernel/loop.py` 现在既做主循环，也做：

- streaming 聚合和 fallback
- tool argument 安全摘要
- retry 展示事件
- request compaction 和 summary prompt
- approval request payload/message
- 多种 `runtime.part` UI 事件

这些都是有用能力，但它们让 Kernel 从“流程骨架”变成“流程 + UI协议 + prompt摘要 + 展示策略”。

简化方案：

Kernel 主文件只保留主循环：

```text
load state
kit.start
build request
model caller
parse output
approval gate
tool runner
verify
decide
writeback
save state
finish
```

移出的深模块：

- `ModelCaller`：stream/complete fallback、retry、timeout。
- `ContextCompactor`：压缩触发、摘要、fallback。
- `RuntimeEventEmitter`：CoreEvent 到 runtime item event 的发射。
- `ApprovalGate`：approval pending state 和 request 事件。
- `ToolRunner`：并发工具、timeout、权限前置。

关键是外部接口不要变多。Kernel 可以内部组合这些模块，但对 member 仍只暴露 `run(turn_input)`。

收益：

- 核心循环可读性大幅提升。
- 每个策略可单测，减少改一处影响全链路。
- Core 更适合未来成员复用。

判定：P1。先统一事件，再瘦 Kernel。

### 6. StateStore/EventSink 复用 Core，删掉 member 内部重复 in-memory 实现

现状：

- Core 有 `InMemoryEventLog`、`InMemorySessionStore`、`InMemoryRuntimeEventStore`。
- Writer 有 `_InMemoryStateStore`。
- Artist 有 `InMemoryRuntimeStateStore` 和 `InMemoryEventSink`。

简化方案：

- Core 增加或导出一个通用 `InMemoryRuntimeStateStore`。
- Core 增加 `CollectingEventSink`，可选 live callback。
- Writer/Artist 删除本地重复实现。

收益：

- 减少测试夹具和 member adapter 样板。
- Core 协议示例更完整。

判定：低风险 P2。

### 7. ChatThread 和 Workbench 瘦身：UI 只渲染 canonical parts

现状：

- `core/ui/src/components/ChatThread.vue` 超过 3000 行，里面既有渲染，又有 part 标准化、agent timeline、decision、tool grouping、metrics 格式化。
- Writer `CoreWorkbenchView.vue` 同时管理 session、app server、queue、approval、composer、scroll、projection。
- Writer `SettingsView.vue` 同时管理模型、agent、工具、主题、provider preset、local storage。

简化方案：

- `ChatThread.vue` 只负责模板和简单展示状态。
- part 归一化移到 `core/ui/src/helpers/messageParts.ts`。
- agent/process/decision/checklist 各自成为小的纯展示模块，但对外仍是一个 `ChatThread` Interface。
- Workbench 只接收权威 snapshot + selectors，不再解释 runtime。
- Settings 拆成 domain panels：ModelSettings、AgentSettings、ToolSettings、ThemeSettings。外部仍由 SettingsView 组合。

收益：

- UI bug 更容易定位。
- Writer/Artist 共享 UI 的复用价值提升。
- 减少模板里混入协议兼容逻辑。

判定：P2。事件统一后做，避免先拆 UI 又被协议变化返工。

## 复用矩阵

| 能力 | 当前位置 | 简化后应该复用 |
|---|---|---|
| LLM payload/response/stream 转换 | Core + Writer + Artist 重复 | Core LLM adapter |
| Prompt 片段排序和预算 | Core 有，Writer 手写 | Core PromptAssembler + member providers |
| 工具 spec/registry | Core 有，Writer/Artist 各自 list | Core ToolRegistry |
| workspace 文件工具 | Writer 内嵌 | Core optional workspace toolkit |
| shell/git/web 工具 | Writer 内嵌 | Core optional toolkits，member 按需注册 |
| permission | Core tier + Writer policy | Core permission vocabulary + member policy |
| runtime state store | Writer/Artist 各自内存 store | Core InMemoryRuntimeStateStore |
| runtime event sink | Core event + member sink | Core CollectingEventSink |
| app snapshot reducer | 后端和前端两份 | 后端权威；前端 selectors |
| ChatThread part 归一化 | ChatThread 内部 | core/ui helper |

## 不应该抽到 Core 的内容

为了简单，Core 也不能变成“万能业务层”。以下内容应继续留在 member：

- Writer persona、执行纪律、completion verifier。
- Writer checklist/architecture handoff/commit review 的产品策略。
- Artist 图像生成、谱系、视觉验收、参考图选择。
- Novel 专用记忆、canon、story bible、style drift。
- 产品设置页的文案和默认 preset。

判断标准：两个成员都需要的才抽 Core；只有一个成员需要的，只抽通用协议，不抽业务。

## 建议执行顺序

### 阶段 0：禁止继续扩散

- 新能力默认先复用 Core 协议。
- 不新增第三套事件/状态/展示协议。
- 不在 `core_kernel_adapter.py` 继续塞大段工具或 prompt 逻辑。

### 阶段 1：事件链路减法

目标：后端权威 snapshot，前端只 selector。

动作：

1. 定义 canonical run item event。
2. 让 `runtime_bridge.py` 输出 canonical event。
3. 后端 reducer 保留为唯一 reducer。
4. 前端 `appServer/reducer.ts` 已删除，当前薄 hydration 位于 `appServer/snapshot.ts`。
5. `ChatThread` 输入只接受 selector 输出。

验收：

- live 和 replay 展示一致。
- approval/waiting request 只在一个地方解释。
- metrics/artifact/final reply 不再重复推断。

### 阶段 2：LLM adapter 收敛

目标：Writer/Artist 不再手写 provider 转换。

动作：

1. 把 Writer adapter profile 接到 Core `OpenAICompatibleAdapter`。
2. Artist LLM client 改为使用 Core payload builder/response parser。
3. Writer streaming 使用 Core stream chunk parser。
4. 删除重复 message/tool_call/usage 转换。

验收：

- Writer/Artist 同一 provider profile 行为一致。
- tool_call delta、usage、thinking 的测试只维护一套核心用例。

### 阶段 3：Prompt fragment 化

目标：Kit 不拼 prompt，只选择 providers。

动作：

1. 为 Writer 静态 prompt、项目规则、memory、git、plan、failure 建 provider。
2. `WriterKit.build_model_request` 改为调用 assembler。
3. Artist 接入同一 assembler。

验收：

- prompt 顺序有单测。
- 每个 fragment 有独立预算和开关。
- 新增上下文不改 Kit 主循环。

### 阶段 4：工具注册表化

目标：工具执行从 WriterKit 主体移出。

动作：

1. 建 `WorkspaceToolset`，承接 read/list/search/inspect。
2. 建 `ShellToolset` 和 `GitToolset`，接入 permission policy。
3. WriterKit 只调用 registry。
4. 子代理复用 registry + scoped work_root。

验收：

- Writer 主代理和子代理使用同一工具实现。
- 读写路径、权限、资源根测试集中在 toolset。
- `core_kernel_adapter.py` 明显减少工具处理代码。

### 阶段 5：Kernel 内部瘦身

目标：核心循环主文件只表达流程。

动作：

1. 抽 `ModelCaller`。
2. 抽 `ContextCompactor`。
3. 抽 `ApprovalGate`。
4. 抽 `RuntimeEventEmitter`。
5. 保持 Kernel 对外 Interface 不变。

验收：

- `CoreLoopKernel.run()` 能在一屏内看清完整流程。
- 复杂策略都有独立测试。
- member 不知道这些内部模块。

## 删除/合并候选

优先确认后处理：

- 前端 `appServer/reducer.ts`：已删除；后端 snapshot 为权威，前端只保留 `snapshot.ts` 默认字段补齐和 selectors。
- Writer/Artist 本地 in-memory runtime store：合并到 Core。
- Writer/Artist LLM message conversion：复用 Core helper。
- Artist legacy tool executor：若 CoreKernel 路径已经覆盖，应标记历史或迁移。
- `core/ui/src/components/ChatThread.vue` 内的协议兼容函数：迁移到 helper 或由后端 snapshot 消化。
- `members/writer/backend/app/core/writer/core_kernel_adapter.py` 内的工具实现：迁移到 toolsets。
- 运行产物和打包产物：继续按上一份功能底图清理。

## 风险提醒

- 不要为了“拆文件”制造浅模块。拆分后的外部 Interface 必须更小。
- 不要把 Writer 业务能力上抽 Core。Core 只放协议、循环、通用 toolkit。
- 不要同时保留旧协议和新协议长期并行。兼容层必须有删除日期。
- 不要先拆 UI。先统一事件和 snapshot，否则 UI 会重复返工。
- 不要让子代理绕过主工具/权限注册表。子代理差异应来自 scope 和 policy，不来自复制工具实现。

## 最终目标形态

理想主链路：

```text
User input
  -> member service resolves session/config
  -> CoreLoopKernel.run()
     -> RuntimeKit selects prompt providers + tool registry
     -> Core LLM adapter calls provider
     -> Core ToolRunner executes registered tools under permission policy
     -> canonical runtime events
  -> backend snapshot reducer
  -> frontend selectors
  -> shared UI render
```

一句话：核心只管循环，member 只管业务，UI 只管展示，事件只解释一次。
