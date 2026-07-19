# LamTools 去复杂化审查：多角度减法复核

日期：2026-06-29

维护标注（2026-06-30）：Writer 前端 reducer 主线已完成第一轮删除，`appServer/reducer.ts` 和 reducer 测试不再存在；当前前端只接收后端 snapshot，并通过 `snapshot.ts` 补齐默认字段后交给 selectors。本文保留其它角度的债务判断，但涉及前端 reducer 的条目已改为“已处理/剩余边界”。

前置材料：

- `docs/agent-code-inventory-2026-06-29.md`：功能底图，回答“代码分别服务什么能力”。
- `docs/core-simplification-review-2026-06-29.md`：Core/Member 复用路线，回答“哪些能力应该复用 Core”。
- `docs/decomplexity-interface-review-2026-06-29.md`：从入口 Interface 反推深模块，回答“用户入口和内部接口怎么收敛”。

本轮换几个角度继续审查。目标不是找更多可新增的模块，而是找“同一事实被多处维护”“同一协议被多次翻译”“已有 Core 能力没有被复用”的位置。判断标准沿用深模块原则：外部 Interface 越小、Implementation 越能集中复杂度，越可靠；一个 Seam 只有一套生产 Adapter 时，不急着继续抽象。

## 成熟方案参照

参考对象只取方向，不照搬命名：

- OpenAI Agents SDK 的主轴是 agent loop、tools、handoffs/agents-as-tools、guardrails、sessions、tracing。成熟点在于能力有明确层次，不让业务页面直接理解底层执行细节。
- Claude Code 的主轴是项目指令、subagents、权限/工具范围、settings/hooks。成熟点在于配置和权限是可审查的外部事实，不散落在执行代码中。

参考页：

- OpenAI Agents SDK: https://openai.github.io/openai-agents-python/
- OpenAI Agents SDK tools: https://openai.github.io/openai-agents-python/tools/
- OpenAI Agents SDK handoffs: https://openai.github.io/openai-agents-python/handoffs/
- OpenAI Agents SDK guardrails: https://openai.github.io/openai-agents-python/guardrails/
- Claude Code subagents: https://docs.anthropic.com/en/docs/claude-code/sub-agents
- Claude Code settings: https://docs.anthropic.com/en/docs/claude-code/settings
- Claude Code hooks: https://docs.anthropic.com/en/docs/claude-code/hooks

对应到 LamTools：`CoreLoopKernel + RuntimeKit` 是可靠主线；当前复杂度主要来自主线之外的重复投影、重复协议、重复工具注册和历史产物污染。

## 总结判断

这轮从八个角度看，收敛为一句话：

```text
事实只认一份，协议只解释一次，工具只注册一次，上下文只排序一次，UI 只渲染一次。
```

最高收益不是继续拆大文件，而是先把下面几个“重复事实源”关掉：

1. **状态事实源**：Writer 后端 `writer_app_events + writer_thread_snapshots` 已成为 UI 主事实源；前端 reducer 主线已删除，剩余问题是 transcript 与 app snapshot 的 owner 边界。
2. **事件协议**：Core event、Writer runtime event、App event、前端 app-server event 四层同时存在。
3. **工具执行**：Core 有 `ToolRegistry`，Writer/Artist 仍各自维护 spec、executor、权限和展示元数据。
4. **Prompt/上下文**：Core 有 fragment provider 机制，WriterKit 仍手写大量 prompt 拼接和上下文压缩周边逻辑。
5. **配置/模型**：Provider preset 已进入 Core UI，但后端 adapter profile 仍偏 Writer；SettingsView 仍持有过多配置知识。
6. **Kernel 内部职责**：主循环文件同时承担 stream、retry、compaction、approval、runtime.part 发射。
7. **UI 渲染**：ChatThread/Workbench 同时承担展示、协议兼容、状态推导和操作编排。
8. **验证与产物**：运行产物、历史 E2E、打包目录数量已经超过活跃代码文件数量，会污染全量阅读和搜索。

## 角度 1：状态事实源

审查问题：刷新后、实时流、CLI watch、历史回放看到的状态是否来自同一份事实。

代码证据：

| 事实 | 代码位置 | 判断 |
|---|---|---|
| Writer app-server 已有事件账本和快照表 | `members/writer/backend/app/models/app_server.py`、`members/writer/backend/app/database.py` | 可靠主线 |
| 后端 reducer 负责把 app event 压成 snapshot | `members/writer/backend/app/app_server/reducer.py`、`snapshot.py` | 可靠主线 |
| WebSocket/RPC 多数 mutating 操作已返回 snapshot | `members/writer/backend/app/app_server/connection.py` | 可靠主线 |
| 前端 snapshot-only 主线 | `members/writer/frontend/src/appServer/store.ts`、`snapshot.ts`、`selectors.ts` | 已处理：前端不再 reduce event |
| transcript 另有独立投影事实 | `members/writer/backend/app/services/transcript_service.py`、`members/writer/frontend/src/runtime/transcript.ts` | 存疑，需明确 owner |

去复杂化方案：

1. 已完成：Writer UI 权威事实为后端 snapshot，前端 reducer 已删除。
2. `thread/resume` 可以继续返回 events 作为协议事实，但 UI 主线只 hydrate snapshot，不 replay events。
3. transcript 与 app snapshot 只保留一个对 UI 可见的最终投影；另一份只能是审计/恢复底账。
4. `store.ts` 中的迁移旗标已删除；后续不再把“是否使用权威 snapshot”做成产品分支。

收益：

- live/refresh/resume 三条路径不会出现不同解释。
- waiting request、final reply、queue status 这类历史高发 bug 会减少。
- UI 测试只需要固定 snapshot fixture，不需要模拟整条事件账本。

优先级：P0。

## 角度 2：事件与协议词汇

审查问题：同一个运行步骤是否被多个事件名、多个字段结构重复表达。

代码证据：

| 层 | 代码位置 | 当前职责 | 判断 |
|---|---|---|---|
| Core event | `core/src/lamtools_core/event/__init__.py`、`run_event/__init__.py` | Kernel 内部事件、运行事件 store | 可靠 |
| Writer runtime event | `members/writer/backend/app/core/writer/events.py`、`models/runtime_event.py` | Writer 运行落库事件 | 存疑 |
| App event | `members/writer/backend/app/app_server/protocol.py`、`runtime_bridge.py` | app-server 对 GUI/CLI 的事件协议 | 可靠到存疑 |
| 前端 event/snapshot | `members/writer/frontend/src/appServer/protocol.ts`、`snapshot.ts`、`selectors.ts`、`store.ts` | 接收后端 snapshot 并提供展示 selector | 已收敛主线，仍需 schema/contract 防漂移 |
| UI part | `core/src/lamtools_core/kernel/loop.py` 多处发 `runtime.part` | 直接带展示语义 | 存疑 |

复杂度来源：

- `runtime_bridge.py` 大量方法把 Writer runtime event 转成 App event，说明真正稳定的协议在 app-server 层。
- `events.py` 中同时存在 `writer_*_event`、`make_*_event`、`emit_*` 多组构造函数，历史层未收敛。
- `CoreLoopKernel` 直接发 `runtime.part`，导致 Core 知道太多展示形状。

去复杂化方案：

1. 选定唯一对外协议：`RunItemEvent -> ThreadSnapshot`。
2. Core 只发抽象执行事实：model started/delta/completed、tool started/completed、approval requested、context compacted。
3. Writer 只在一个 Adapter 中把 Core fact 转成 App event，不再同时维护多组 Writer event helper。
4. 前端只接受 snapshot 和 selector 输出，不再解释 event 方法。
5. 旧 runtime event 可以短期保留为审计日志，但不能再作为 UI 主线。

收益：

- 协议字段减少，新增状态只改一处。
- Core 不再绑定 Writer UI part 形状。
- 事件测试从“每层都测一遍”变成“Adapter contract + snapshot selector”。

优先级：P0。

## 角度 3：工具、权限与执行

审查问题：工具能力是否通过一个深 Module 暴露，还是 spec、权限、执行、展示散在多处。

代码证据：

| 事实 | 代码位置 | 判断 |
|---|---|---|
| Core 已有通用 `ToolSpec/ToolCall/ToolResult/ToolRegistry` | `core/src/lamtools_core/tool/__init__.py` | 可靠 |
| Core 已有权限等级词汇 | `core/src/lamtools_core/tool/permission.py` | 可靠 |
| Writer 工具 spec 已集中到单文件，但仍是 dict 列表 | `members/writer/backend/app/core/writer/tool_specs.py` | 存疑 |
| Writer 工具执行一部分在 `ToolExecutor`，一部分仍在 `WriterKit`/`ReadOnlyToolExecutor` | `tool_executor.py`、`core_kernel_adapter.py` | 债务 |
| Writer 权限来源依赖 tool spec，但命令安全另在 policy 中处理 | `permission.py`、`app_server/security.py` | 存疑 |
| Artist 有 `ARTIST_TOOL_SPECS` 和旧 `ArtistToolExecutor` 形状 | `members/artist/backend/app/core/artist/tool_specs.py`、`tools.py` | 存疑 |

去复杂化方案：

1. 把工具定义统一为 Core `ToolSpec` 对象，Writer/Artist 只提供注册清单。
2. 建少数通用 toolset：workspace read、workspace write、shell、git、web。它们放 Core 或 Core optional 包，但必须不含 Writer persona。
3. Writer 特有工具保留在 Writer：checklist、completion verifier、architecture handoff、commit review。
4. 子代理不再复制工具实现，只传入同一 ToolRegistry 的 scoped adapter。
5. 权限策略成为工具执行前置 Gate，而不是散落在每个工具实现里。

删除/合并候选：

- `ReadOnlyToolExecutor` 与 `ToolExecutor` 的读文件/搜索/list_dir 重复实现。
- WriterKit 内工具 dispatch 分支。
- Artist 旧 `ArtistToolExecutor`，如果 CoreKernel 路径已经覆盖，应降级为 legacy。

收益：

- 工具失败、路径校验、权限审批只修一次。
- 子代理和主代理行为更一致。
- 新 member 可以注册工具，不需要复制 Writer 工具代码。

优先级：P1。

## 角度 4：Prompt、项目规则与上下文预算

审查问题：进入模型前的上下文是否有一个可测试的排序和预算策略。

代码证据：

| 事实 | 代码位置 | 判断 |
|---|---|---|
| Core 已有 `PromptPart`、`PromptFragmentProvider`、`BasePromptAssembler` | `core/src/lamtools_core/prompt/__init__.py` | 可靠 |
| Writer 已加载 persona、项目指令、skill index 等静态 prompt | `members/writer/backend/app/core/writer/core_kernel_adapter.py`、`project_instructions.py` | 可靠到存疑 |
| WriterKit 仍手写 runtime context、git、active plan、failures、memory 等拼接 | `core_kernel_adapter.py` | 债务 |
| Writer 有独立 context compaction 辅助 | `members/writer/backend/app/core/writer/context_specs.py` | 存疑 |
| Artist PromptAssembler 是独立轻量实现 | `members/artist/backend/app/core/prompt_assembler.py` | 存疑 |

去复杂化方案：

1. Writer/Artist 都使用 Core `BasePromptAssembler`。
2. 每类上下文成为 provider：StaticPrompt、ProjectInstructions、Memory、RuntimeContext、GitContext、PlanContext、FailureRecovery、SkillIndex。
3. provider 返回 `PromptPart(kind, priority, budget_tokens)`，排序和预算只在 assembler 里测。
4. Kit 只决定“启用哪些 provider”，不拼字符串。
5. 上下文压缩保留在 Core 内部策略，但摘要模板和保留字段由 member 配置。

收益：

- prompt 拼接顺序可单测，不再靠阅读大函数确认。
- 新增上下文不会继续膨胀 WriterKit。
- Artist 可以复用成熟预算逻辑，不需要自己维护一套 prompt assembler。

优先级：P1。

## 角度 5：模型、供应商与配置

审查问题：配置是否是可审查的数据，还是 UI、后端、profile 各自理解一套。

代码证据：

| 事实 | 代码位置 | 判断 |
|---|---|---|
| Provider preset 已集中到 Core UI | `core/ui/src/data/provider-presets.ts`、`core/ui/src/index.ts` | 可靠，已完成一处减法 |
| Writer SettingsView 直接消费 preset 并创建 provider/model | `members/writer/frontend/src/views/SettingsView.vue` | 存疑 |
| Writer 后端 adapter profile 仍在 Writer utils 和 jsonc 目录 | `members/writer/backend/app/utils/llm_adapter_profiles.py`、`llm_adapters/*.jsonc` | 存疑 |
| Core 有 ProviderRegistry 和 LLM adapter/helper | `core/src/lamtools_core/provider/__init__.py`、`llm/**` | 可靠 |
| Artist 仍有 Vendor/Provider 命名 | `members/artist/backend/app/models/api_provider.py`、`services/api_manager.py` | 存疑 |

去复杂化方案：

1. 保持 Provider preset 是共享 UI 数据，不再在各产品页面复制。
2. 把 adapter profile 能力下沉到 Core LLM adapter 层，Writer 只保留本地 profile 目录作为扩展输入。
3. 用户层统一叫“供应商/模型”；Artist 内部 `vendor` 只作为实现细节。
4. `SettingsView` 拆成配置 Module 的内部 panel，但 `/settings` 外部 Interface 不增加。
5. 模型路由设置只暴露少数业务用途，不让 UI 直接知道底层 profile 字段。

收益：

- 新增供应商不会同时改前端 preset、后端 profile、Settings 表单多个位置。
- Writer/Artist 配置语义一致。
- Settings 页面从“持有全部知识”变成“调用配置 Module”。

优先级：P1。

## 角度 6：Kernel 内部职责

审查问题：Core loop 是否只表达循环，还是把展示、压缩、重试、审批都塞进主文件。

代码证据：

| 事实 | 代码位置 | 判断 |
|---|---|---|
| `CoreLoopKernel.run()` 已是可靠主循环 | `core/src/lamtools_core/kernel/loop.py` | 可靠 |
| 同一文件处理 streaming fallback、tool call delta、retry event | `loop.py` | 存疑 |
| 同一文件处理 context compaction、summary prompt、approval request | `loop.py` | 存疑 |
| `runtime.part` 由 Kernel 直接发出 | `loop.py`、`kernel/display.py` | 债务趋势 |

去复杂化方案：

Kernel 对外 Interface 不变，只做内部瘦身：

```text
CoreLoopKernel.run()
  -> ModelCaller
  -> ToolRunner
  -> ApprovalGate
  -> ContextCompactor
  -> RuntimeFactEmitter
```

关键约束：

- 这些是 Kernel 内部 Module，不对 member 暴露新接口。
- `RuntimeFactEmitter` 发通用执行事实，不发 Writer/UI part。
- member 仍只感知 `RuntimeKit` Interface。

收益：

- Kernel 主流程更短，异常策略更容易独立测试。
- Core 不继续吸收 UI 协议复杂度。
- 不会因为重试/压缩/审批策略改动误伤整个 loop。

优先级：P2。要等事件协议收敛后再做，否则会把旧协议拆成更多碎片。

## 角度 7：UI 渲染与状态所有权

审查问题：UI Module 是否只渲染，还是承担协议兼容和状态推导。

代码证据：

| 事实 | 代码位置 | 判断 |
|---|---|---|
| Shared ChatThread 超大，承担多种 part 展示和兼容逻辑 | `core/ui/src/components/ChatThread.vue` | 存疑 |
| Writer Workbench 同时管 session、app-server、queue、approval、scroll、projection | `members/writer/frontend/src/views/CoreWorkbenchView.vue` | 存疑 |
| SettingsView 同时管 Provider、Model、Agent、Tool、Theme、localStorage | `members/writer/frontend/src/views/SettingsView.vue` | 存疑 |
| SessionSidebar 支持 rename emit，但 member 接线不完整 | `core/ui/src/components/SessionSidebar.vue`、两个 `CoreWorkbenchView.vue` | 债务 |

去复杂化方案：

1. UI 只接受 selector 输出：messages、runtimeItems、queue、approval、artifacts、metrics。
2. `ChatThread` 外部 Interface 保持一个，但内部把 decision/tool/agent/process/checklist 拆成纯展示 Module。
3. Workbench 只编排用户操作和页面布局，不再理解 app event replay。
4. 可见控件必须有 owner：control -> operation id -> adapter method -> backend persistence -> refresh 验证。
5. 没有 owner 的控件先隐藏，不再保留“看起来能点”的入口。

收益：

- UI bug 可以通过 snapshot fixture 定位。
- Shared UI 真正复用，不让 Writer/Artist 各自绕过。
- 减少局部补丁造成刷新后失效。

优先级：P2。

## 角度 8：测试、文档与运行产物

审查问题：验证资产是在保护主线，还是反过来污染搜索和默认测试。

代码证据：

| 事实 | 代码位置 | 判断 |
|---|---|---|
| Core 测试大量使用 mock kit 验证 loop contract | `core/tests/test_kernel.py` | 可靠 |
| Writer 后端有大型服务测试，历史用例混杂 | `members/writer/backend/tests/**` | 存疑 |
| E2E real-task-runs 内有大量 JSON/截图/历史 UI 文本 | `e2e/real-task-runs/**` | 债务 |
| `.gitignore` 已忽略 `.archives/`、`.codex-runtime/`、`.writer-artifacts/`、`tmp/`、Tauri target | `.gitignore` | 可靠 |
| 当前运行产物/历史目录下可搜索文件数量高于活跃代码文件数量 | 本轮 `rg --files` 粗略统计：运行/历史类约 1566，活跃代码约 530 | 债务 |

去复杂化方案：

1. 默认搜索/审查脚本排除 `.archives`、`tmp`、`.writer-artifacts`、`.codex-runtime`、`e2e/real-task-runs`、`src-tauri/target`。
2. E2E 真实运行产物保留索引和最小证据，不把大段 UI 文本长期留在主树。
3. 默认测试只跑稳定单元、契约、核心集成；真实 LLM/浏览器/历史运行显式分组。
4. 文档清单继续维护“保留/删除/人工判断”，避免旧文档成为新架构事实。

收益：

- 全量阅读不会被历史产物淹没。
- `rg` 结果更接近真实源码。
- 默认测试更稳定，历史失败不会遮住当前回归。

优先级：P0 文档/搜索止血，P2 测试分层。

## 横向复用矩阵

| 能力 | 现在的重复点 | 复用目标 | 是否抽 Core |
|---|---|---|---|
| 状态投影 | 后端 reducer + transcript projection；前端 reducer 已删除 | 后端 snapshot + 前端 selectors | 否，保留 Writer app-server 事实源 |
| 运行事件 | Core event + Writer event + App event + UI event | Core fact + member adapter + snapshot | Core 放 fact，member 放业务 adapter |
| 工具注册 | Core Registry + Writer dict + Artist dict | Core ToolRegistry + member registration | 通用 toolset 可抽，业务工具不抽 |
| 权限 | Core tier + Writer command policy + app security | Core 词汇 + member PermissionPolicy | 词汇抽 Core，策略留 member |
| Prompt 排序 | Core assembler + Writer 手写 + Artist 手写 | Core assembler + member providers | 机制抽 Core，内容留 member |
| LLM 适配 | Core helper + Writer profile + Artist client | Core adapter/profile resolver | 抽 Core |
| UI 渲染 | Shared ChatThread + member workbench 推导 | selector 输出 + 纯展示 Module | Shared UI 保持产品无关 |
| 配置 preset | Core UI preset + Writer backend profile | ProviderCatalog + Core LLM profile | 共享数据抽 Core，产品路由留 member |
| 测试夹具 | Core mock + member mock +历史 E2E | contract fixture + live/e2e 显式分层 | Core 只放契约夹具 |

## 不应上抽 Core 的内容

为了简单，Core 不能变成业务总线。以下内容继续留在 member：

- Writer persona、执行纪律、completion verifier、Git/commit 业务策略。
- Writer architecture handoff、checklist、project inspection 的产品语义。
- Artist 生图策略、视觉验收、lineage、reference image 选择。
- Novel 记忆、style drift、story bible、角色设定。
- Settings 中产品文案、默认业务用途、面向用户的解释。

抽 Core 的硬规则：

1. 两个成员都真实使用。
2. 抽出来后 caller 知道的事实更少。
3. Core 不出现 Writer/Artist 产品名。
4. 兼容旧路径必须有删除日期。

## 推荐执行顺序

### Phase 0：事实源和搜索止血

- 已完成：Writer 前端主线改为 snapshot-only，前端 reducer 已删除。
- 运行/历史产物从默认搜索和全量审查中排除。
- 文档清单加入本审查，后续减法只认当前审查链路。

验收：

- live、refresh、resume、watch 对同一会话状态一致。
- `rg` 默认不会扫到历史运行 JSON 和打包 target。

### Phase 1：协议和工具收敛

- 定义 Core runtime fact 和 Writer App event 的唯一 Adapter。
- Writer/Artist 工具改为 ToolRegistry 注册。
- 子代理复用同一工具注册和权限策略，只改变 scope。

验收：

- 新增 tool 不再同时改 spec、permission、executor、UI metadata 多处。
- event contract 测试覆盖 Core fact -> snapshot。

### Phase 2：Prompt 与配置收敛

- Writer/Artist 接入 Core prompt provider。
- adapter profile resolver 进入 Core LLM 层。
- SettingsView 拆内部 panel，但不新增用户路由。

验收：

- prompt 顺序有单测。
- provider/model 配置术语统一。

### Phase 3：Kernel 和 UI 内部瘦身

- Kernel 内部拆 ModelCaller、ToolRunner、ApprovalGate、ContextCompactor、RuntimeFactEmitter。
- ChatThread 只渲染 selector 输出。
- Workbench 只编排操作，不 replay 协议。

验收：

- Kernel 对外 Interface 不变。
- UI snapshot fixture 能覆盖主要展示状态。

## 立即可删/可降级候选

| 候选 | 处理建议 | 前置条件 |
|---|---|---|
| `members/writer/frontend/src/appServer/reducer.ts` | 已删除，前端主线改为 snapshot-only | 2026-06-30 已完成；Writer 前端测试和构建通过 |
| Writer `events.py` 中历史 helper | 标 legacy，逐步删除 | `runtime_bridge.py` 统一从 Core fact 转换 |
| WriterKit 中读文件/搜索/list_dir 重复实现 | 合并到 workspace toolset | ToolRegistry 注册完毕 |
| Artist 旧 `ArtistToolExecutor` | 降级或删除 | CoreKernel path 覆盖所有活跃入口 |
| `runtime.part` UI 语义 | 从 Kernel 移到 member adapter | Core runtime fact 定义完成 |
| 未形成入口的 HTTP 能力 | 内部化或删除 | Operation Catalog 标 owner |
| `e2e/real-task-runs/**` 大产物 | 归档索引化 | 保留必要验收证据 |

## 最终收敛图

```text
User operation
  -> Operation Catalog
  -> member adapter
  -> CoreLoopKernel.run()
     -> Prompt providers
     -> Core LLM adapter
     -> ToolRegistry + PermissionPolicy
     -> Core runtime facts
  -> member event adapter
  -> authoritative snapshot
  -> frontend selectors
  -> shared UI render
```

最终判断：LamTools 现在不缺 agent 能力，缺的是“每个事实只有一个 owner”。下一步减法应优先处理状态事实源、事件协议、工具注册和运行产物污染；这些收敛后，再拆 Kernel 和 UI 大文件才不会变成更多浅模块。

## 实施记录

### 2026-06-30：Writer 前端 snapshot-only

- 删除 `members/writer/frontend/src/appServer/reducer.ts` 和对应 reducer 测试。
- 新增轻量 `snapshot.ts`，只做 snapshot hydration 默认字段补齐。
- `store.ts` 不再从 app-server events 推导前端状态，只接收后端权威 snapshot。
- selectors 测试改为直接使用 snapshot fixture，避免测试继续依赖前端 replay reducer。

验证：

- `npm test` in `members/writer/frontend`
- `npm run build` in `members/writer/frontend`
