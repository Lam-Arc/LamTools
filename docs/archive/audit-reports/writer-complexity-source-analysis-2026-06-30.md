# Writer 复杂度来源系统审查

日期：2026-06-30

目的：本报告只做系统性审查，不做代码重构。目标是为后续精简 Writer、下沉通用 agent 能力到 Core、删除兜底补丁和历史兼容层建立可执行依据。

关联文档：

- `docs/agent-architecture-north-star-2026-06-30.md`：Core/member 最终目标、6000 行硬上限和精美结构验收。
- `docs/core-member-architecture-refactor-design-2026-06-30.md`：Core/member 还原的接口设计、迁移阶段和验收门槛。
- `docs/complexity-and-loc-review-2026-06-30.md`：全仓行数与复杂度复核。
- `docs/agent-code-inventory-2026-06-30.md`：按 LLM 前/中/后/其他划分的全仓功能底图。

## 1. 总体判断

Writer 当前不是“缺少 Core”，而是 **已经接入 Core 主线之后，仍把太多通用 agent 能力和历史兼容路径留在 member 内**。

本轮目标口径调整为：

```text
Core + Writer member 才是一个完整 Writer 产品。
Writer member 不是另一个 agent runtime，而是 Core 的 member pack。
Writer 目录只保留 persona、prompt、Writer 专用工具声明、验收策略、产品 UI、极薄 adapter。
LLM、tool、permission、event、session、snapshot、state、provider/profile 等基础 agent 能力只能有 Core 一个实现源。
```

当前主线已经成立：

```text
GUI / CLI
  -> Writer App Server
  -> Writer service
  -> CoreLoopKernel + WriterKit
  -> LLM / tool / approval / verification
  -> Writer runtime event
  -> App Server event
  -> backend snapshot
  -> frontend selectors
  -> ChatThread / Workbench
```

但实际代码里还并行存在：

```text
REST session message path
Core HTTP compatibility path
TaskManager SSE
Writer runtime events
Writer SSE events
App Server events
transcript projection
thread snapshot
CLI legacy event formatter
frontend transcript/runtime helpers
```

所以复杂度来源不是单点大文件，而是多个事实源和多个协议族同时存在。当前 Writer 后端 runtime 为 **40,809 物理行**，占活跃 runtime 源码 **47.4%**；Writer 前后端合计 **48,831 行**，占 **56.7%**。这已经超过一个 member pack 应有的体量。新行数约束是：**Writer runtime 全部不得超过 6,000 行，其中 Writer 专属业务核心不得超过 1,500 行**。`6,000` 不是宽松目标，而是硬上限；超过它就说明 Writer 仍在承载 Core 应承担的基础 agent 能力，主次已经颠倒。目标形态应该是：Writer 只保留 persona、Writer Kit 注入、Writer 专用工具声明、验收策略和产品 UI；LLM、工具注册、权限 gate、事件协议、snapshot 骨架、状态 store 等通用能力必须成为 Core 的唯一实现。

最高优先级判断：

| 优先级 | 结论 | 证据 | 下一步 |
|---|---|---|---|
| P0 | Writer 事件/投影链路仍过长 | `writer_service.py` 曾同时写 transcript、runtime fact、App Server projection、final/session terminal、waiting request response、approved tool execution 和 continuation prompt；维护标注（2026-07-01）：服务层 app projection 持久化入口已改为 Core `RunItemEvent`，已停止构造/保存 `WriterRuntimeEvent` row，bridge 旧 adapter 和旧表模型/迁移壳已删除，后端 app 代码层 `runtime_event` 旧命名已清空，RuntimeFactRecorder、RuntimeTranscriptSink、RuntimeFinalizationSink、AppProjectionSink、runtime_waiting_request、runtime_approved_tool、runtime_continuation_prompts、runtime_input_context、runtime_runner 已从 service 拆出；Writer App Server snapshot 已新增由 Core reducer 生成的 `snapshot.core` canonical runtime 子树；前端 selectors 对运行 item/status 已优先读 `snapshot.core`，并合并 `snapshot.core.item_order` | 继续拆 session orchestration；后续 ChatThread/ledger 继续向 RunItemEvent 主事实收敛 |
| P0 | 旧 Writer event helper 仍需继续收尾 | 维护标注（2026-07-01）：`core_adapter.py`、CLI 旧 formatter、CLI verbose 旧 unknown writer event 展示、`writer_git_*`、旧 GitContextManager、`writer_agent_*`、`writer_thought_event`、`writer_workflow_event`、`events.py`、`WriterStepEvent`、`WriterStep` 后端 API/表/持久化、旧 `/runtime-events` REST 查询入口、前端 step/runtime REST store/API、`turn_parser.py` 旧 `response/thought/phase_transition/mode_transition` 兼容已删 | 继续处理 projection |
| P0 | 通用 LLM adapter 没有完全沉 Core | Core 有 `llm/helpers.py` 和 `llm/adapter.py`，Writer 仍有 `utils/llm_client.py`、`llm_adapter_profiles.py` 和 Kit 内 stream 转换 | Core 成为唯一 provider transformation 层 |
| P1 | 工具执行没有真正变成 Core toolkits | Core 有 `ToolRegistry`，Writer 仍在 `tool_specs.py`、`core_kernel_adapter.py` 处理工具；维护标注（2026-07-01 第七十二切片）：未接入运行主线的旧 `tool_executor.py` 和 `scope_guard.py` 已删除 | workspace/shell/git/web 沉 Core，Writer 留业务工具 |
| P1 | 前端主事实已收敛，但 UI 仍过重 | `appServer/store.ts` 已 snapshot-only；`ChatThread.vue` 仍 3,768 行并理解大量 part 语义 | UI 后拆，先稳定 event/snapshot |

判断标记：

- `可靠`：与成熟 agent 架构一致，职责清晰，仍是当前主线。
- `存疑`：功能必要，但边界不清、重复实现或历史负担明显。
- `债务`：不再服务当前主线，或复杂度大于收益，应删除、合并或下沉。

## 2. Writer 功能分类表

| 功能种类 | 目的 | 是否必要 | 当前实现位置 | 复杂度来源 | 初步判断 |
|---|---|---|---|---|---|
| 任务入口 | 让用户从 GUI/CLI/API 发起任务 | 必要 | GUI `frontend/src/views/CoreWorkbenchView.vue`；CLI `writer_cli/__main__.py`、`app_server_client.py`；REST `routers/session.py`；Core HTTP `routers/core_http.py`；App Server `app_server/connection.py` | GUI/CLI/REST/Core HTTP 多入口并行；普通入口和调试入口混在 CLI | 存疑 |
| 会话管理 | 创建、读取、重命名、删除、恢复会话 | 必要 | `routers/session.py`、`routers/core_http.py`、`models/session.py`、`services/session_lifecycle.py`、`frontend/src/stores/session.ts`、`core/ui/src/components/SessionSidebar.vue` | REST 会话、Core HTTP 会话、App Server thread 三套词汇 | 存疑 |
| prompt 组装 | 把 persona、项目规则、上下文、memory 变成模型输入 | 必要 | `core/persona.py`、`core/prompt_assembler.py`、`core/prompt_files.py`、`core/writer/project_instructions.py`、`core/writer/core_kernel_adapter.py`、`prompts/writer/*.md` | Core 已有 `PromptPart/BasePromptAssembler`，Writer Kit 仍手写大量拼接 | 存疑 |
| 模型调用 | 根据 provider/model 配置调用 LLM，支持 stream、thinking、tool calls、usage | 必要 | `utils/llm_client.py`、`utils/llm_adapter_profiles.py`、`llm_adapters/*.jsonc`、`core/writer/core_kernel_adapter.py`、`services/llm_config_service.py` | Core 已有 LLM protocol/helpers/adapter；Writer 又实现 OpenAI/Anthropic/profile/stream 兼容 | 债务倾向 |
| agent loop 适配 | 把 Writer 业务注入 CoreLoopKernel | 必要 | `core/writer/core_kernel_adapter.py`，Core `core/src/lamtools_core/kernel/*` | WriterKit 过大，混合 prompt、工具、MCP、验收、展示事件 | 存疑 |
| 工具调用 | 文件、命令、Git、Web、MCP、sub_agent、计划等工具执行 | 必要 | `core/writer/tool_specs.py`、`core_kernel_adapter.py`、`core/mcp/**` | Tool spec、权限、执行、展示元数据分散；通用工具没有沉 Core；维护标注（2026-07-01 第七十二切片）：旧 `tool_executor.py` 已删除 | 存疑 |
| 文件读写 | coding agent 的工作区读写、搜索、编辑 | 必要 | `core_kernel_adapter.py`、`permission.py` | 路径校验和读写工具仍在 Writer 内实现，未来 member 会重复；维护标注（2026-07-01 第七十二切片）：未使用的 `scope_guard.py` compatibility methods 已删除 | 应下沉 Core 通用 toolkit |
| Git 操作 | 记录工作区状态、diff、checkpoint、branch/merge、commit review | 必要，但 Writer UI 策略专用 | `core/writer/git.py`、`routers/session.py`、`checkpoint_service.py`、`commit_review_service.py`、`writer_service.py`、`writer_cli/__main__.py`；维护标注（2026-07-01 第七十五切片）：旧 `git_context.py` 已删除 | 维护标注（2026-07-01）：`writer_git_*` 事件族和未实例化 `GitContextManager` 已删除；checkpoint 与 commit review request persistence 已从 `writer_service.py` 拆出 | 存疑 |
| 权限与审批 | 危险工具前等待用户确认，支持批准/拒绝/指导 | 必要 | Core `tool/permission.py`、Writer `permission.py`、`app_server/approvals.py`、`app_server/connection.py`、`writer_service.py`、前端 `appServer/store.ts` 和 `ChatThread.vue` | 权限词汇在 Core，策略和投影在 Writer；审批同时穿过 transcript、App Server request、UI decision card；维护标注（2026-07-01 第七十二切片）：旧 `scope_guard.py` 已删除 | 存疑 |
| 记忆 | 会话内工具输出、git 事件、知识召回、长期记忆 | 必要但需验证收益 | Core `mem/__init__.py`；Novel memory；维护标注（2026-07-01 第七十四切片）：旧 `core/writer/session_memory.py` 无生产入边，已删除；维护标注（2026-07-01 第七十六切片）：旧 Writer 私有 `core/mem/**` 未接入主线，已删除 | 通用记忆协议已有；Writer 不再保留一套未使用的私有 MEM store/recall | 存疑 |
| sub agent | 把子任务委派给临时 agent 或架构 agent | 有必要但不应扩张 | Core `agent.py`；Writer `agent_runtime.py`、`agents/architecture_agent.py`、`tool_specs.py`、Settings UI | Core 有协议，Writer 运行时和 CLI 可直接跑 agent，工具/权限上下文与主 agent 不完全一致 | 存疑 |
| 验收 / 自评 | 判断任务是否完成，必要时修复 | 必要但不应隐式拦截普通任务最终回复 | `failure_specs.py`、Novel self review；维护标注（2026-07-01 第七十三切片）：普通 `self_review.py` 未接入生产主线，已删除；维护标注（2026-07-01 第七十四切片）：旧 `verification_specs.py` 未被调用，已删除；维护标注（2026-07-08）：旧 `completion_verifier.py` 自研自动完成验收层已删除，显式语法/构建检查改由任务 prompt 要求模型调用工具执行 | 自动验收曾试图弥补模型不稳定，但会在最终回复后续跑并污染对话边界 | 债务已删除 |
| transcript / snapshot / projection | 支持刷新恢复、历史展示、实时状态 | 必要，但事实源应唯一 | `models/transcript.py`、`services/transcript_service.py`、`models/app_server.py`、`app_server/reducer.py`、`snapshot.py`、`runtime_bridge.py`、前端 `appServer/*`、`runtime/transcript.ts` | transcript、runtime event、app event、thread snapshot 并行；projection 失败可被吞掉继续跑 | 存疑到债务 |
| 事件流 / SSE / App Server event | 实时显示运行过程 | 必要，但只应有一条产品主线 | App Server `router.py`、`connection.py`、`hub.py`、`protocol.py`；`routers/session.py`、Core `sse/__init__.py` | 维护标注（2026-07-01）：`services/task_manager.py` 与 `test_task_manager.py` 已删除；App Server snapshot 是当前产品主线，剩余问题转为旧 REST/CoreEvent side channel 与 Core SSE 边界 | 存疑 |
| CLI | 用户运行任务、恢复、观察 | 必要，但需保持薄入口 | `writer_cli/__main__.py`、`writer_cli/app_server_client.py`、根 `writer.cmd`、`scripts/member_cli.py` | 维护标注（2026-06-30）：`agent/tool/debug/message/step`、`quick/chat` 顶层旁路已删除；formatter 已收敛为 app-server event 主线 | 可靠到存疑 |
| 前端工作台 | 输入、模型选择、thinking、队列、审批、展示、右侧面板 | 必要 | `frontend/src/views/CoreWorkbenchView.vue`、`appServer/store.ts`、`selectors.ts`、`core/ui/*` | 页面直接知道 App Server 方法、队列、审批、模型路由、thinking 预算、scroll | 存疑 |
| 设置与 provider/model | 管理供应商、模型、路由、agent、工具、主题 | 必要 | `frontend/src/views/SettingsView.vue`、`stores/config.ts`、`routers/config.py`、`services/llm_config_service.py`、Core UI `provider-presets.ts` | Provider preset 已共享，但 SettingsView 和后端 profile 仍混合多类配置知识 | 存疑 |
| 测试与历史兼容 | 防回归、保护已知修复 | 必要，但应保护主线 | `members/writer/backend/tests/**`、`frontend/tests/**`、`core/ui/tests/**` | 多个测试仍保护 `core_adapter`、TaskManager SSE、旧 parser key；维护标注（2026-07-01）：legacy projection cleanup 测试已随启动清理链路删除 | 存疑到债务 |

## 3. 架构复杂度分析

| 功能区 | 是否应存在 | 是否应在 Writer | 平行实现 | 层级是否过多 | 是否混合运行/展示/持久化 | 历史兼容影响 | 判断 |
|---|---|---|---|---|---|---|---|
| 任务入口 | 是 | GUI/CLI adapter 在 Writer，operation 协议应 Core 化 | GUI App Server、REST `/messages`、Core HTTP、CLI | 是 | CLI 已对齐 app-server event；服务端仍有多投影 | 维护标注（2026-06-30）：`message/debug/step` 注入入口、`chat/quick` 别名、旧 CLI event formatter 已删除 | 存疑 |
| 会话管理 | 是 | 数据模型在 Writer，通用 session 协议在 Core | Writer session、Core session、App thread | 是 | 维护标注（2026-07-01）：TaskManager 依赖已删除，运行态来自 Core runtime registry、transcript projection、snapshot | mode legacy normalize、旧 REST | 存疑 |
| prompt 组装 | 是 | Writer 只保留 prompt 内容和 provider | Core prompt 协议 + Writer 手写 Kit | 是 | Kit 同时拼 prompt 和执行工具 | prompt assembler 历史类已测试不暴露 | 存疑 |
| 模型调用 | 是 | HTTP 凭据读取可在 Writer，payload/stream 转换应 Core | Core LLM adapter + Writer LLMClient + WriterKit stream | 是 | LLM client 还处理 thinking、usage、tool call | 多 provider path fallback | 债务倾向 |
| agent loop 适配 | 是 | WriterKit 是业务注入点 | 无旧 runtime 主线，但 Kit 内部过宽 | 中 | 是，Kit 处理 runtime display part | 多 fallback 和历史 metadata | 可靠到存疑 |
| 工具调用 | 是 | Writer 工具留 Writer，通用工具沉 Core | ToolExecutor、Extended/ReadWrite executor、Kit dispatch、MCP | 是 | 工具结果同时给模型、event、memory、UI | legacy WriterRuntime 已删，但 shape 仍多 | 存疑 |
| 文件/Git | 是 | Git review/checkpoint UI 留 Writer；基础文件/Git 工具沉 Core | Writer file tools、session router undo/checkpoint；维护标注（2026-07-01 第七十五切片）：旧 `git_context.py` 纯函数已删除 | 是 | Git state 同时是工具、artifact、session state、UI 右栏 | 维护标注（2026-06-30）：`writer_git_*` 旧事件已删除 | 存疑 |
| 权限审批 | 是 | 策略在 Writer，gate 协议沉 Core | Core permission tier、Writer policy、App request、transcript waiting_request | 是 | 审批写 transcript、snapshot、UI decision card | waiting_request 历史投影 | 存疑 |
| 记忆 | 是 | Writer 专用记忆内容留 Writer，store/recall 协议沉 Core | Core mem + Novel memory；维护标注（2026-07-01 第七十四切片）：旧 `session_memory.py` 已删除；维护标注（2026-07-01 第七十六切片）：旧 Writer 私有 `core/mem/**` 已删除 | 是 | tool output/git/knowledge 与 prompt 拼接耦合 | deprecated cross-session memory 测试已随 `test_mem.py` 删除 | 存疑 |
| sub agent | 是 | Agent 定义和角色留 Writer，协议沉 Core | Core sub_agent spec + Writer runtime | 是 | agent 工具、LLM、权限、workspace 隔离混合 | 维护标注（2026-06-30）：CLI direct agent 已删除；fallback_reason 仍被测试保护 | 存疑 |
| 验收 | 是 | Writer | completion verifier、自评、failure specs、Novel self review | 中 | 验收结果进入事件、CLI、repair | completion verifier 太大 | 存疑 |
| transcript/snapshot | 是 | snapshot 协议未来应 Core 化，Writer DB adapter 留 Writer | transcript projection、runtime events、app events、snapshot | 是 | 是，`writer_service.py` 最明显 | 维护标注（2026-07-01）：启动 cleanup 修旧 app event 已删除 | 存疑到债务 |
| 事件流 | 是 | App Server adapter 可先 Writer，通用 event schema 应 Core | App Server event、runtime fact、CoreEvent side channel | 是 | 是 | 维护标注（2026-07-01）：TaskManager SSE、core_adapter 已删除；剩余是 runtime fact -> App snapshot 仍在 Writer adapter 内 | 存疑 |
| CLI | 是 | 用户入口留 Writer，dev 入口分层 | CLI 直连 App Server | 低到中 | formatter 只理解 app-server event；运行事实仍来自服务端投影 | 维护标注（2026-06-30）：REST debug、local agent/tool import、旧 Writer event formatter 已删除 | 可靠到存疑 |
| 前端工作台 | 是 | UI 留 Writer，state model 应共享 | Core controller `createMessage` 与 Writer app-server store | 是 | 页面混合操作和展示 | snapshot-only 已收敛，但 runtime helpers 仍在 | 存疑 |
| 设置页 | 是 | 产品 UI 留 Writer，共享 provider catalog/Core config protocol | Core provider preset + Writer SettingsView + backend profile | 中 | UI 持有 provider/model/agent/tool/theme | legacy local key / default model fallback | 存疑 |
| 测试 | 是 | 是，但应保护主线 | 主线测试和历史兼容测试混杂 | 中 | 测试让旧模块继续有存在理由 | 多处 legacy/fallback 测试 | 存疑到债务 |

核心架构问题可以压缩成三句话：

1. **WriterKit 是唯一业务注入点，但实现不够薄**：`core_kernel_adapter.py` 同时承担 LLM bridge、prompt、MCP、工具、计划、验收、runtime event 格式化。
2. **App Server snapshot 是正确方向，但旧事件仍未完全退场**：`appServer/store.ts` 只 hydrate snapshot 是可靠主线；维护标注（2026-07-01）：TaskManager SSE 和 Writer SSE -> CoreEvent enrichment 已删除，剩余问题是 runtime fact -> app snapshot adapter 仍在 Writer。
3. **Core 已有协议，但 Writer 只部分复用**：LLM、Prompt、Tool、Memory、Provider、Guardrail、Session 都有 Core 协议，Writer 仍在 member 内实现大量转换和策略骨架。

## 4. 最优路径审查

### 4.1 当前 GUI 主链路

```text
用户输入
  -> members/writer/frontend/src/views/CoreWorkbenchView.vue
  -> members/writer/frontend/src/appServer/store.ts startTurn()
  -> members/writer/frontend/src/appServer/client.ts JSON-RPC websocket
  -> members/writer/backend/app/app_server/router.py /api/app-server
  -> members/writer/backend/app/app_server/connection.py _turn_start()
  -> members/writer/backend/app/services/writer_service.py send_message()
  -> writer_service.py _run_core_kernel_path()
  -> members/writer/backend/app/core/writer/core_kernel_adapter.py run_core_kernel()
  -> core/src/lamtools_core/kernel/loop.py CoreLoopKernel.run()
  -> WriterKit build_model_request / execute_tool / verify_completion
  -> runtime_runner.py / RuntimeFactRecorder -> transcript + app projection
  -> app_server/runtime_bridge.py runtime_event_to_app_event_inputs()
  -> app_server/snapshot.py apply_event_to_snapshot()
  -> app_server/connection.py thread/snapshot notification
  -> frontend appServer/store.ts hydrate()
  -> frontend appServer/selectors.ts
  -> core/ui/src/components/ChatThread.vue
```

评价：主链路能成立，但过长。真正应该稳定的 interface 是 `turn/start -> CoreLoopKernel -> canonical run item event -> snapshot -> selector`。维护标注（2026-07-01）：service 已停止保存旧 runtime event row，Core run orchestration 已迁入 `runtime_runner.py`，Writer App Server snapshot 已携带 `snapshot.core` canonical runtime 子树；前端 selectors 已对运行 item/status 优先读 `snapshot.core`，且 runtime item 可只依赖 `snapshot.core.item_order` 进入消息流。剩余问题是产品 AppEvent 仍作为外层 ledger，ChatThread 仍理解较多 Writer part 语义。

### 4.2 当前 CLI 主链路

```text
writer run/resume/watch
  -> members/writer/backend/writer_cli/__main__.py
  -> writer_cli/app_server_client.py initialize/thread/resume/turn/start
  -> App Server websocket
  -> 同 GUI 主链路
  -> CLI CliRunFormatter 格式化 app-server event
```

评价：CLI 已对齐 App Server，这是可靠方向。维护标注（2026-06-30）：本地 `agent/tool/debug/message/step` 入口、`quick/chat` 别名、`writer_runtime_event` 与旧 `writer_*` formatter 分支已删除；下一步矛盾转移到服务端旧 event helper 和三重投影。

### 4.3 旧 REST / Core HTTP 旁路

```text
/api/sessions/{id}/messages
  -> routers/session.py send_message()
  -> writer_service.py send_message()
  -> 旧 REST 响应 / transcript 投影

/api/core/sessions/{id}/messages
  -> routers/core_http.py create_message()
  -> Writer session/message projection
```

评价：REST 和 Core HTTP 可作为兼容或内部接口，但不能再是产品运行主线。`routers/session.py` 还包含 debug decision/step、changes undo、agent branches、checkpoint、commit review 等大量操作，这些应该通过 Operation Catalog 明确分层。

### 4.4 是否复用已有功能

| 检查项 | Core/共享已有能力 | Writer 当前情况 | 结论 |
|---|---|---|---|
| LLM 请求/响应/stream | `core/llm/__init__.py`、`helpers.py`、`adapter.py` | `utils/llm_client.py` 和 `core_kernel_adapter.py` 仍转换 payload、thinking、usage、stream chunk | 重复，应下沉 |
| Prompt fragment | `core/prompt/__init__.py` | Writer 有 prompt assembler，但 Kit 仍拼大量上下文 | 重复，应下沉排序和预算 |
| Tool registry | `core/tool/__init__.py` | Writer 有 specs/executor/Kit dispatch/MCP 多处工具逻辑 | 重复，应抽通用 toolkits |
| Permission tier | `core/tool/permission.py` | Writer `permission.py`、`app_server/security.py` 各自处理部分策略；维护标注（2026-07-01 第七十二切片）：`scope_guard.py` 已删除 | 重复，需统一 gate |
| Memory protocol | `core/mem/__init__.py` | 维护标注（2026-07-01 第七十四切片）：旧 `session_memory.py` 已删除；维护标注（2026-07-01 第七十六切片）：旧 Writer 私有 `core/mem/**` 已删除 | 通用协议留 Core，领域内容留 member |
| Agent/sub agent | `core/agent.py` | Writer `agent_runtime.py`、architecture agent、CLI direct agent | 协议可复用，runtime 需收敛 |
| Session protocol | `core/session/__init__.py` | Writer DB session + Core HTTP mapper + App thread | 词汇重复，需要 operation/session facade |
| UI shell | `core/ui` | Writer Workbench 仍绕过 Core controller 调 app-server | Core controller interface 名称仍偏 `createMessage`，需改成 turn operation |
| Provider preset | `core/ui/src/data/provider-presets.ts` | Writer Settings 使用，但后端 adapter profile 仍 Writer-local | 已部分复用，后端 profile 待沉 |

### 4.5 不可调用/死代码初筛

当前没有直接证明大量完全死代码；更多是“被测试和旧入口保护的债务”。疑似死代码应按删除前核实：

| 文件/模块 | 疑似死代码 | 证据 | 删除风险 | 建议 |
|---|---|---|---|---|
| `core/writer/core_adapter.py` | 维护标注（2026-06-30）：已删除 | 反向适配已不再是当前代码事实 | 已处理 | 防止恢复 Writer SSE -> CoreEvent 方向 |
| `services/task_manager.py` | 维护标注（2026-07-01）：已删除 | App Server websocket/snapshot 与 Core runtime registry 已取代旧 SSE manager | 已处理 | 不再恢复旧 SSE manager |
| `writer_git_*` event helpers | 维护标注（2026-06-30）：已删除 | 当前扫描只剩正常 `app.core.writer.git` 模块引用，旧 `writer_git_*` helper 不再存在 | 已处理 | Git 状态继续走 session state/router/service，后续再决定是否抽 Core Git toolkit |
| `routers/session.py` debug endpoints | 产品主线外开发注入 | 维护标注（2026-06-30）：`/debug/decision-point`、`/debug/step` 和对应 CLI 注入命令已删除 | 已处理 | 无需迁移 |
| `writer_cli/__main__.py` `agent/tool` direct commands | 绕开 App Server 主链路 | 维护标注（2026-06-30）：CLI 本地 import `AgentRuntime`、`ExtendedToolExecutor` 的入口已删除 | 已处理 | 无需迁移 |
| `core/writer/turn_parser.py` 旧 key fallback | 维护标注（2026-07-01 第七十五切片）：模块已删除 | 该解析器只被旧测试触达，生产模型输出已走 Core tool call / RunItemEvent 主线 | 已处理 | 不再恢复旧 WriterTurn 解析器 |
| `app_server/cleanup.py` repair functions | 维护标注（2026-07-01）：已删除 | 原先处理 `legacy_runtime_part_display_event` 和截断 final reply，并在启动时执行 | 已处理 | 不再迁移为 doctor/migrate；无用户兼容要求下直接移出运行主线 |
| `frontend/runtime/transcript.ts` | App snapshot 主线外历史投影类型 | 前端主线使用 `appServer/selectors.ts`；但 ChatThread 和测试仍覆盖 transcript live timeline | 中 | 确认 UI 不再读 transcript 后删除或降为审计视图 |
| `core/ui` fallback slot tests | 不是 Writer 死代码 | `slotValidation.ts` 是共享 UI slot 兼容 | 低 | 不作为 Writer 删除目标 |
| `tests/test_wave3_p2.py` writer_delegation_queued | 维护标注（2026-06-30）：已删除旧 event helper 测试 | 当前测试只保留模型行为；不再保护 `writer_delegation_queued` | 已处理 | 后续不恢复 delegation 专用 SSE event |

## 5. 核心代码 vs 兜底策略

| 功能区 | 核心代码 | 兜底策略 | 兜底存在原因 | 是否仍需要 | 更优雅方案 |
|---|---|---|---|---|---|
| 任务运行 | `app_server/connection.py` `turn/start`；`writer_service.py`；`core_kernel_adapter.py`；Core `kernel/loop.py` | REST `/sessions/{id}/messages`、Core HTTP `create_message` | 旧 GUI/CLI/API 路径 | 短期可留，不能主推 | Operation Catalog 标记 stable/dev/deprecated |
| 会话状态 | `writer_thread_snapshots`、`app_server/snapshot.py`、前端 `appServer/store.ts` | 维护标注（2026-07-01）：`TaskManager.is_running()` 已删除；当前使用 Core runtime registry 与 session lifecycle 推断 | 运行态仍分布在 registry/session/transcript | 继续收敛 | App Server runtime registry + snapshot status |
| LLM 调用 | Core `LLMRequest/LLMResponse/LLMStreamEvent` + Writer config | Writer `_WriterToCoreBridge`、`llm_adapter_profiles` path fallback、多 provider response path | 适配不同供应商和历史 profile | 只保留真实 provider 差异 | Core provider/profile adapter 统一处理 |
| prompt | Writer persona/prompt files + Core prompt protocol | Kit 内多段字符串拼接、静态 prompt cache signature | 快速接入 CoreLoopKernel 时累积 | 部分需要 | Prompt fragment providers + budget test |
| 工具 | Core `ToolRegistry`、Writer tool specs、tool executor | Kit 内 dispatch、ExtendedToolExecutor、ReadWriteToolExecutor、多处路径校验 | 旧 runtime 和 CLI direct tool 需要 | 不应长期保留 | Core optional workspace/shell/git/web toolkits |
| 文件写入 | `core_kernel_adapter.py` Read/Write executors | `old_string` 失败类型、preview/diff 字符串解析；维护标注（2026-07-01 第七十二切片）：旧 `tool_executor.py` 与 `scope_guard.py` 已删除 | 保护编辑安全 | 编辑安全需要，旧 compatibility 不需要 | Core file toolkit 输出结构化 diff/result |
| Git | `git.py`、commit review routes；维护标注（2026-07-01 第七十五切片）：旧 `git_context.py` 已删除 | 维护标注（2026-06-30）：`writer_git_*` 旧事件和 CLI 特判已删除 | 历史事件展示 | 已删除 | 后续只保留 session state / artifact / route 事实 |
| 权限/审批 | Core permission tier + Writer command policy + App Server request | transcript `waiting_request` 同步、fallback wait question priority | UI 需要刷新恢复 | waiting_request 作为展示事实可由 snapshot 表达 | ApprovalGate + request snapshot，transcript 只审计 |
| 记忆 | 维护标注（2026-07-01 第七十四切片）：旧 `session_memory.py` 已删除；维护标注（2026-07-01 第七十六切片）：旧 Writer 私有 `core/mem/**` 已删除 | fallback code strategy、deprecated cross-session memory 不召回 | 旧记忆策略 | 已删除 | Core recall ranking + member domain adapter 后续在 Core 协议上重建 |
| sub agent | Core agent spec + Writer AgentRuntime | missing kernel runner fallback、exception fallback_reason、CLI `--no-llm` | 子代理早期不稳定 | 运行失败记录需要，伪输出不需要 | 统一 AgentRunResult 错误协议 |
| 验收 | 维护标注（2026-07-08）：旧 `completion_verifier.py` 已删除；维护标注（2026-07-01 第七十四切片）：旧 `verification_specs.py` 已删除 | 自动验收续跑、repair fallback、final reply fallback | 弥补模型不稳定但破坏最终回复边界 | 已删除 | 显式语法/构建检查由模型按任务要求调用工具完成 |
| transcript/snapshot | `writer_app_events` + `writer_thread_snapshots` | 维护标注（2026-07-01）：`app_server/cleanup.py` 历史事件归档/修复已删除；仍有 `transcript_service.py` legacy duration | 修旧显示 bug的启动副作用已删除 | cleanup 已处理；legacy duration 待审 | snapshot reducer + canonical event contract |
| 前端展示 | `appServer/selectors.ts` -> `ChatThread.vue` | ChatThread flat content fallback、legacy dirty runtime projection drop、runtime/transcript helpers | 兼容旧消息形状 | 部分需要 | Canonical message part schema + migration |
| CLI | AppServerClient + run/resume/watch | 维护标注（2026-07-01）：旧 Writer event formatter、runtime_event formatter、verbose unknown writer event 展示已删除 | 曾兼容旧输出 | 用户层不需要 | 继续保持 CLI 只认 app-server/display event |
| Provider/model/thinking | `config.ts`、`SettingsView.vue`、`store.ts` turn options、backend config | Settings legacy local key、legacy default_model_id migration、provider-specific UI 判断 | 旧设置与 provider 差异 | 迁移后删 | Core model capability probe + model run params |

原则：核心代码继续压缩、清晰化；兜底策略先全量登记，再逐项删除。不能把历史兜底继续包装成新抽象。

## 6. 应下沉 Core 的能力清单

| 能力 | 当前 Writer 实现 | 是否应下沉 Core | 下沉内容 | 不应下沉内容 | 理由 |
|---|---|---|---|---|---|
| prompt 组装 | `core/prompt_assembler.py`、`core/writer/core_kernel_adapter.py`、prompt files | 是 | `PromptFragmentProvider` 排序、预算、截断、冲突处理、测试夹具 | Writer persona、执行纪律、reply contract、项目规则内容 | 所有 agent 都需要上下文排序与预算 |
| 记忆 | Core memory protocol、Novel memory；维护标注（2026-07-01 第七十四切片）：旧 `session_memory.py` 已删除；维护标注（2026-07-01 第七十六切片）：旧 Writer 私有 `core/mem/**` 已删除 | 部分 | Memory store/recall/budget/provenance 协议与通用 ranking | Novel story bible、Writer 工具输出语义 | Writer/Artist/未来 member 都会需要 recall，但领域内容不同 |
| 文件预览/读写/搜索 | `core_kernel_adapter.py` | 是 | workspace read/write/edit/search/list_dir toolkit、结构化结果、diff/artifact 协议 | Writer checklist、验收触发 | coding agent 基础能力，Artist/未来 Editor 也会需要 |
| Git 基础能力 | `git.py`；维护标注（2026-07-01 第七十五切片）：旧 `git_context.py` 已删除 | 部分 | status/diff/branch/commit metadata、artifact event | Writer commit review UX、session checkpoint 策略 | Git 是通用 coding agent 能力，review 策略是 Writer 产品 |
| web fetch/search | Writer tool specs/Kit/MCP | 是 | web_fetch/web_search tool interface、权限、结果 artifact | Writer 对搜索结果的写作用途 | 多 agent 复用 |
| ask / 等待用户输入 | `ApprovalGate` 分散在 Core loop、Writer app requests、transcript waiting_request | 是 | generic server request / approval / ask_user 协议和 event | Writer UI 文案、具体 option labels | human-in-the-loop 是 agent 基础能力 |
| 自动重试 | Core loop policy + Writer fallback | 是 | retry policy、error classification、backoff、retry events | Writer completion repair 文案 | 所有模型/工具调用都需要一致失败语义 |
| tool permission | Core permission tier + Writer policy | 是 | PermissionGate interface、risk tiers、approval result protocol | Writer command allowlist 和 workspace policy | Core 已有词汇，缺统一 gate |
| MCP | `core/mcp/**` 在 Writer 内 | 是，但可 optional | MCP registry/client/protocol、tool registration adapter | Writer 内置 MCP 默认项 | MCP 是通用工具生态 |
| sub agent | Core `agent.py` + Writer runtime | 部分 | sub-agent tool schema、handoff prompt skeleton、AgentRunResult、scoped tool registry | architecture_agent persona、Writer sub-agent presets | 多 agent 协议通用，角色和验收留 member |
| event/display/session protocol | Core event/display/session + Writer runtime/app event | 是 | canonical RunItemEvent、ThreadSnapshot skeleton、DisplayFact | Writer-specific item labels | 当前最大重复源 |
| snapshot/projection | `app_server/reducer.py`、`snapshot.py`、前端 selectors | 部分 | reducer/snapshot contract、idempotency、schema generation | Writer queue semantics 和 UI copy | Writer/Artist 都需要 refresh-safe realtime state |
| provider/model 配置 | Writer provider/model DB + Core provider registry + Core UI presets | 是 | provider profile registry、model capability schema、run params | Writer model routing defaults | thinking/tool-call/usage 差异不应每个 member 重写 |
| usage/cost | Core `usage`、Writer runtime event usage | 是 | normalized usage/cost protocol and aggregation | Writer billing display copy | 所有 agent 都需要 |
| verification 结果协议 | Writer completion verifier | 部分 | generic `VerificationResult`、evidence artifact、repair request protocol | Writer 验收标准、Novel 质量规则 | 协议通用，判断策略业务专用 |
| artifact 协议 | Writer app artifacts、transcript artifacts、tool artifacts | 是 | artifact model: uri/path/content/diff/preview/ownership | Writer artifact presentation | 工具、生成、Git 都需要统一 artifact |

## 7. 复杂度来源总结与死代码 / 重复代码 / 历史兼容候选

### 7.1 复杂度来源总结

| 优先级 | 复杂度来源 | 影响 | 证据 | 处理建议 |
|---|---|---|---|---|
| P0 | 重复事件 / projection | 同一运行事实仍被表达为 CoreEvent、runtime fact、App Server event、transcript block、thread snapshot，显示问题会跨层扩散 | 维护标注（2026-07-01）：旧 Writer SSE event helper 已删除；`runtime_bridge.py` 已提供 Core `RunItemEvent` 主入口，`writer_service.py` 已停止保存 `WriterRuntimeEvent`，bridge 旧 adapter、旧表模型和删除清理已删除，`runtime_event` 旧命名已从后端 app 代码层清空，RuntimeFactRecorder、RuntimeTranscriptSink、RuntimeFinalizationSink、AppProjectionSink、RuntimeRunner 已独立，Writer snapshot 已同步生成 `snapshot.core` canonical runtime 子树，前端 selectors 已优先消费 core runtime items 并合并 core item order | 继续减少 session 编排；下一步让 ChatThread 更少理解 Writer AppEvent 语义，或让 ledger 直接存 RunItemEvent |
| P0 | 旧传输仍参与产品链路 | App Server snapshot 已是主线；维护标注（2026-07-01）：TaskManager SSE 产品链路已删除，旧传输债务降为 REST/Core SSE/CoreEvent side channel 的边界问题 | `services/task_manager.py` 和 `test_task_manager.py` 已不存在；`session_lifecycle.py` 使用 Core runtime registry | 不再恢复产品 SSE manager；继续明确 REST/Core SSE 是否仅保留为开发接口 |
| P0 | 旧 Writer event helper 未完全退场 | 旧 Writer event helper 曾让 agent 局部路径保留旧事件词汇 | 维护标注（2026-07-01）：`core_adapter.py`、`TaskManager`、CLI 旧 formatter、`writer_git_*`、`writer_agent_*`、`writer_thought_event`、`writer_workflow_event`、`events.py`、`WriterStepEvent`、`WriterStep` 后端 API/表/持久化已删 | 继续清理前端孤儿定义和 runtime projection |
| P0 | 通用 LLM/provider 转换仍在 Writer | Provider profile、thinking、tool call、usage、stream chunk 转换如果留在 Writer，Artist/新成员会继续复制 | Core 有 `lamtools_core/llm/*`；Writer 仍有 `utils/llm_client.py`、`utils/llm_adapter_profiles.py`、`llm_adapters/*.jsonc`，`core_kernel_adapter.py` 也处理 stream/tool metadata | Core `LLMAdapter` 成为唯一转换层；Writer 只保留本地 provider/model 配置读取 |
| P1 | 通用工具没有沉到 Core | 文件、shell、Git、web、MCP 的 spec、权限、执行、展示元数据分散在 Writer，member 变厚 | Core 有 `ToolRegistry`/`ToolPermission`；Writer 仍在 `tool_specs.py`、`core_kernel_adapter.py`、`core/mcp/**` 处理通用工具；维护标注（2026-07-01 第七十二切片）：旧孤儿 `tool_executor.py` 与 `scope_guard.py` 已删除 | 抽 Core optional workspace/shell/git/web/MCP toolkits；Writer 留业务工具和验收策略 |
| P1 | 大文件大函数承载过多知识 | 单文件修改风险高，测试只能覆盖内部细节，调用方需要理解过多隐含协议 | 维护标注（2026-07-01）：`core_kernel_adapter.py` 已降到 5,324 行，`writer_service.py` 已降到 685 行，`writer_cli/__main__.py` 已降到 716 行；`ChatThread.vue` 3,768 行；`CoreWorkbenchView.vue` 2,618 行 | 只按 interface 深模块化拆分：Kernel adapter、runtime runner/recorder、projection/finalization/waiting-request/approved-tool/prompt builder/checkpoint/review/input-context service、UI selectors/renderers 分离 |
| P1 | CLI / GUI / REST / Core HTTP 多入口并行 | 用户入口、开发入口和旧兼容入口混在一起，难以判断哪条链路是真主线 | GUI 走 App Server websocket；CLI 也走 App Server；`routers/session.py` 和 `routers/core_http.py` 仍提供消息旁路；维护标注（2026-06-30）：CLI `agent/tool/debug/message/step`、`quick/chat` 和旧 formatter 已删除 | Operation Catalog 标记 stable/dev/deprecated；普通 CLI 只保留 run/resume/watch/session |
| P1 | 前端状态与展示语义过重 | 前端共享组件理解后端 runtime part、审批、工具、transcript 兼容，阻碍后端协议收敛 | `appServer/store.ts` 已只 hydrate snapshot；但 `ChatThread.vue` 仍做 part normalization 和旧 content fallback；`types/index.ts` 仍 re-export `runtime/transcript` | UI 只认 snapshot selectors 和 canonical parts；ChatThread 降为纯渲染组件 |
| P1 | 测试保护旧路径 | 删除债务时测试会反向要求旧合同继续存在，造成“有测试所以保留”的错觉 | 维护标注（2026-07-01）：`test_writer_core_adapter.py`、`test_task_manager.py`、`test_writer_app_cleanup.py` 已删除；维护标注（2026-07-01 第七十五切片）：`test_turn_parser.py`、`test_context_specs.py`、`test_git_context.py` 已随孤儿模块删除；仍需复核 `test_writer_cli.py`、`core/ui/tests/chat-thread-process.test.ts` 是否保护旧 key | 每删除一个旧模块，同步把测试迁移为 canonical event/snapshot contract test |
| P2 | 历史兼容和兜底解析分散 | legacy key、fallback parser、旧迁移壳让主线难以证明，异常后继续猜测会掩盖协议缺陷 | `llm_config_service.py` 有 legacy default model fallback；`SettingsView.vue` 有 legacy local key；维护标注（2026-07-01）：`app_server/cleanup.py` 启动历史修复已删除；维护标注（2026-07-01 第七十五切片）：旧 `turn_parser.py` 已删除 | 启动和产品主路不再执行历史修复；剩余 legacy 配置做删除或一次性迁移 |
| P2 | Writer 业务与通用 agent 能力混在一起 | Writer 不能变薄，Core 也无法被 Artist/新成员真正复用 | `core_kernel_adapter.py` 同时含 Writer prompt、LLM bridge、MCP、工具、verification、event adapter；`agent_runtime.py` 与主工具/权限上下文不完全一致 | WriterKit 只保留 persona、业务工具、验收、UI label；LLM/tool/permission/prompt/event/session 骨架沉 Core |

### 7.2 死代码 / 重复代码 / 历史兼容候选

| 文件/模块 | 疑似死代码/重复/兼容 | 证据 | 删除风险 | 建议 |
|---|---|---|---|---|
| `members/writer/backend/app/core/writer/core_adapter.py` | 维护标注（2026-06-30）：已删除 | 反向适配不再存在于当前代码 | 已处理 | 保持 Core fact -> app-server event 单向主线 |
| `members/writer/backend/app/services/task_manager.py` | 维护标注（2026-07-01）：已删除 | App Server 已有 `connection.py` + `hub.py`，运行取消/状态走 Core runtime registry | 已处理 | 不再恢复旧 SSE manager |
| `members/writer/backend/app/core/writer/events.py` / `step_persistence.py` / `routers/step.py` / `routers/runtime_event.py` / `frontend/src/stores/step.ts` | 旧 Writer event/step/runtime REST API 已删除 | 维护标注（2026-07-01）：`events.py`、`step_persistence.py`、`routers/step.py`、`WriterStep` model、旧 `/runtime-events` REST router、前端 step store、前端 `/steps` 和 `/runtime-events` API helper 已删除；不再维护 step 表/API 或 runtime event 外部查询能力 | 已处理 | 继续处理 projection 和 old parser key |
| `members/writer/backend/app/app_server/runtime_bridge.py` | 转换层过重 | 维护标注（2026-07-01）：生产持久化 API 已只剩 `persist_run_item_events_as_app_events()`；`writer_service.py` 已调用该入口并改用 `runtime_fact_to_run_item_events()`；旧直连 helper、旧 persist API、`runtime_event_to_run_item_events()` adapter、ORM fixture 测试、`WriterRuntimeEvent` 表模型均已删除；当前对所有 `RunItemEvent` 统一写 `core/runItem`，不再生成 Writer AppEvent carrier，也不再携带 `_core_run_item_event` | 低 | 后续减少 AppEvent ledger 对产品操作事实之外的责任 |
| `members/writer/backend/app/services/writer_service.py` | service 过宽 | 维护标注（2026-07-01）：已停止保存旧 runtime event row，RuntimeFactRecorder、AppProjectionSink、RuntimeFactProjectionBuffer、runtime fact helper、RuntimeTranscriptSink、RuntimeFinalizationSink、runtime_waiting_request、runtime_approved_tool、runtime_continuation_prompts、runtime_input_context、runtime_runner、checkpoint_service、commit_review_service 已拆出；session status/phase 收尾规则已合并，`send_message` 主要剩入口级 session/message 编排 | 中 | 继续拆 session lifecycle / message lifecycle，或把 runner 内通用 contract 下沉 Core |
| `members/writer/backend/app/routers/core_http.py` runtime event consumers | 维护标注（2026-07-01）：已移除 runtime event 统计和 `/api/core/sessions/{id}/events` 路由 | `/api/core/usage*` 曾从 `WriterRuntimeEvent` 派生 token usage；`/api/core/sessions/{id}/events` 曾把 runtime rows 映射成 Core event；当前 Core HTTP 不再导入 `WriterRuntimeEvent` | 已处理 | 真正 usage/event fact source 后续应来自 Core usage / app snapshot 协议，而不是 Writer runtime event |
| `members/writer/backend/app/routers/session.py` | REST 大杂烩 | session CRUD、messages、debug、Git graph、changes、agent branch、checkpoint、commit review 同文件 | 中 | 用 operation catalog 分层；debug/dev 单独迁移 |
| `members/writer/backend/writer_cli/__main__.py` | CLI 入口仍可继续瘦身 | 维护标注（2026-06-30）：旁路命令和旧 Writer event formatter 已删；当前只保留 app-server 主线、会话读取、健康检查 | 低到中 | 后续只做小幅拆分或留作薄入口，不再恢复旧 event 分支 |
| `members/writer/backend/app/core/writer/turn_parser.py` | 维护标注（2026-07-01 第七十五切片）：已删除 | 旧解析器只被测试触达，当前主线不再使用 WriterTurn 兜底解析 | 已处理 | 不再恢复 |
| `members/writer/backend/app/app_server/cleanup.py` | 维护标注（2026-07-01）：已删除 | 原先只归档 `legacy_runtime_part_display_event`、修截断 final reply，并在启动时执行 | 已处理 | 启动主路不再保留历史数据修复副作用；`writer_app_events_archive` 表模型和迁移已同步删除 |
| `members/writer/frontend/src/runtime/transcript.ts` | 旧投影类型 | App Server selectors 已是主线；Core UI 测试仍保护 transcript live timeline | 中 | 若 UI 不再走 transcript，删除或转审计视图 |
| `members/writer/frontend/src/views/SettingsView.vue` | legacy UI setting | `legacyUiSystemKey = 'lamwriter.settings.uiSystem'` | 低 | 做一次 localStorage 迁移后删 |
| `members/writer/backend/app/services/llm_config_service.py` | legacy default model route | `_fallback_model` 和 `legacy_default_model_id` | 中 | DB 配置迁移后删旧字段 |
| `members/writer/backend/tests/test_writer_core_adapter.py` | 测试保护债务 | 专门测试 Writer SSE -> Core contracts | 低 | 随 `core_adapter.py` 删除 |
| `members/writer/backend/tests/test_task_manager.py` | 维护标注（2026-07-01）：已删除 | 原测试保护旧 SSE pub/sub | 已处理 | 不再恢复 |
| `members/writer/backend/tests/test_writer_cli.py` | 已从旧 CLI event 测试迁移 | 维护标注（2026-06-30）：旧 `writer_git_snapshot`、`writer_part_updated`、`writer_runtime_event` 断言已删除，改为 app-server event 覆盖 | 低 | 后续保持测试只保护 app-server 主线 |
| `members/writer/backend/tests/test_turn_parser.py` | 维护标注（2026-07-01 第七十五切片）：已删除 | 测试只保护未接入生产主线的旧 WriterTurn parser | 已处理 | 后续只保护 Core tool call / RunItemEvent contract |
| `core/ui/tests/chat-thread-process.test.ts` | 保护 UI 对旧 transcript/runtime part 的兼容 | live transcript、running snapshot、model_text 历史展示 | 中 | canonical parts 稳定后收缩测试 |

## 8. 优先删减清单

### P0：事件与事实源减法

1. **移除 Writer SSE -> CoreEvent 反向适配**
   目标：`Core fact -> canonical event -> snapshot`，不再从 Writer 旧事件补 `core_event`。

2. **下线 Writer `TaskManager` SSE 产品主线**
   目标：App Server websocket + snapshot 是唯一实时主线。先替换 `is_running/cancel_task`，再删 SSE pub/sub。

3. **清理前端 step 孤儿定义与旧 parser key**
   目标：后端 `writer_git_*`、`writer_agent_*`、`events.py`、`WriterStep` API 已删除；下一步删除前端 step store/API/type 孤儿定义，继续清理 old response/thought/phase/mode parser key。

4. **拆出 `writer_service.py` 的投影职责**
   目标：service 只编排运行；transcript sink、app snapshot sink、approval sink 分离。

5. **收缩测试保护范围**
   目标：删旧模块时同步删除保护旧接口的测试，不让“有测试”成为保留债务的理由。

### P1：通用能力下沉 Core

1. Core LLM adapter 接管 provider profile、thinking、usage、stream chunk、tool call 转换。
2. Core prompt assembler 接管 fragment 排序、预算和截断。
3. Core ToolRegistry + optional toolkits 接管 workspace/shell/git/web。
4. Core PermissionGate 接管 ask_user/approval request 协议。
5. Core event/session/snapshot 协议定义 RunItemEvent/ThreadSnapshot 骨架。
6. Core MCP registry/client 从 Writer 内移出为 optional capability。

### P2：大文件深模块化

1. `core_kernel_adapter.py` 拆内部 Module：LLM bridge、Prompt providers、Tool registry builder、Verification adapter、Event adapter。
2. `ChatThread.vue` 拆内部 helper：part normalization、tool rendering、decision rendering、timeline grouping。
3. `CoreWorkbenchView.vue` 只保留 product composition；队列、审批、thinking、model selector、scroll 分离。
4. `SettingsView.vue` 拆 Provider/Model/Agent/Tool/Theme panels。
5. `routers/session.py` 按 session、git/change、dev/debug、review/checkpoint 拆分。

## 9. 后续重构建议

### 9.1 推荐阶段

| 阶段 | 目标 | 关键验收 |
|---|---|---|
| Phase 1 | 事件事实源收敛 | GUI/CLI 只从 app snapshot 展示；`TaskManager` 不再参与产品显示 |
| Phase 2 | LLM 和 provider 转换沉 Core | Writer/Artist 不再各自解析 stream chunk/tool call/thinking/usage |
| Phase 3 | 工具与权限沉 Core | workspace/shell/git/web 工具在 Core optional toolkit；Writer 只注册业务工具 |
| Phase 4 | prompt provider 化 | WriterKit 不再手写 prompt 大段拼接；prompt 顺序和预算有契约测试 |
| Phase 5 | UI/CLI 瘦身 | ChatThread/Workbench/CLI formatter 不再理解旧 Writer event |
| Phase 6 | 历史清理 | 维护标注（2026-07-01）：启动 cleanup 已直接删除；后续只处理仍在运行主线中的 legacy 配置/migration |

### 9.2 深模块原则

后续不要把大文件机械拆成更多小文件。每次拆分都要满足：

- 调用方需要知道的 interface 变少。
- 复杂度集中到一个 seam 后面。
- 删除旧 module 后，复杂度不会在 3 个调用点重新出现。
- 测试通过新 interface 覆盖行为，而不是测试内部 fallback 分支。

### 9.3 建议目标形态

```text
Core
  agent loop
  LLM adapter/profile
  ToolRegistry + optional toolkits
  PermissionGate / Approval protocol
  Prompt assembler
  Memory protocol
  RunItemEvent / ThreadSnapshot skeleton
  Usage / Artifact / Verification protocol

Writer
  Writer persona and prompt fragments
  Writer-specific tool declarations
  Writer completion verifier / self review
  Writer sub-agent definitions
  Writer app adapter and DB adapter, thin only
  Writer UI
```

验收目标：

| 范围 | 当前行数 | 目标行数 | 验收含义 |
|---|---:|---:|---|
| Writer backend runtime | 40,809 | <=3,000 | 硬上限；不再实现基础 agent runtime，只保留 member pack、产品 adapter、Writer 验收 |
| Writer frontend src | 8,022 | <=2,500 | 硬上限；只保留 Writer 产品界面；状态、part normalization、通用 shell 能力回到 Core UI |
| Writer prompt/config/入口薄壳 | 约数百行 | <=500 | 硬上限；prompt/config/CLI 入口只能是薄壳 |
| **Writer runtime 合计** | **48,831** | **<=6,000** | **不可突破；超过即判定 Core/Member 职责未还原** |
| Writer 专属业务核心 | 混在 40k 内 | <=1,500 | 硬上限；只包含 persona、prompt、专用工具声明、验收、sub-agent 定义、UI 文案 |

删除测试：

```text
如果删除 Writer 目录中的某段代码后，复杂度不会在 Core 或调用方重新出现，
它大概率是历史壳、兼容层或重复实现，应删除。

如果删除后同一基础能力必须在 Writer/Artist/未来 member 各写一套，
它应该沉到 Core，而不是保留在 Writer。
```

判断原则：

- 如果某段代码不是 Writer persona、prompt、专用工具声明、验收策略、产品 UI 或极薄 adapter，默认不应留在 Writer。
- 如果为了保留 Writer 代码而让 Core 变薄、Writer 变厚，判定为主次颠倒。
- 如果 Writer 超过 6,000 行，即使功能可用，也视为架构目标未达成。

## 10. 遗漏角度提醒

| 角度 | 当前发现 | 是否纳入后续审查 | 建议 |
|---|---|---|---|
| 测试是否保护旧架构 | 是，`test_writer_core_adapter.py`、`test_task_manager.py`、`test_turn_parser.py`、CLI 旧事件测试都曾保护旧路径；维护标注（2026-07-01 第七十五切片）：`test_turn_parser.py`、`test_context_specs.py`、`test_git_context.py` 已删除 | 必须 | 每删一个旧模块，同步删/改测试 |
| 文档是否仍描述旧主线 | 是，历史 App Server/实时显示计划保留旧阶段描述，但已有维护标注 | 必须 | 保留历史，继续加当前状态标注 |
| 数据库迁移是否存在历史壳 | 维护标注（2026-07-01）：`cleanup.py` 启动修旧 app events 已删除，`writer_app_events_archive` 表也不再创建；`database.py` 仍有当前 schema 的 additive migrations | 部分 | 继续收缩剩余旧字段/配置迁移 |
| 默认数据库是否有旧事件或旧 snapshot | 已只读检查默认 DB：`writer_app_events` 63,418 条、`writer_thread_snapshots` 70 条；最新 snapshot 未发现 `legacy_runtime_part_display_event`、`writer_git`、`writer_part_updated`、`writer_runtime_event`；app event payload 文本中各有 1 条 `writer_git` / `writer_part_updated` 命中，样本是历史 tool delta 代码文本，不是 event method/type；维护标注（2026-07-01）：cleanup 已直接删除，不再为旧本地 DB 保留产品启动修复；`load_snapshot()` 只做当前 shape 归一化，确保旧 snapshot 读取时补齐 `snapshot.core` | 已处理到当前策略 | 后续只清理仍影响当前运行主线的数据/迁移 |
| 前端是否仅为旧事件展示分支 | 维护标注（2026-07-01）：`appServer/selectors.ts` 已对运行 item/status 优先读 `snapshot.core`，并合并 `snapshot.core.item_order`、`snapshot.core.artifacts`、`snapshot.core.turns[].usage` 与 `snapshot.core.requests`；`runtime_bridge.py` 已删除工具结果 artifact 的外层 `artifact/created` 投影、显式 artifact 的外层 `artifact/created` 投影、工具结果文本的外层 `item/delta` 投影、usage 的外层 `turn/metrics` 投影、普通工具开始的外层 `item/started` 投影、message/thinking 的外层 `item/started` / `item/delta` / `item/completed` 文本投影、status 的外层 `turn/completed` / `thread/status/changed` 投影、approval request 的外层 `item/started` / `item/requestApproval` 投影，以及 error 的外层 `error` carrier 投影；`runtime_bridge.py` 现在对所有 `RunItemEvent` 统一写 `core/runItem`，审批响应也改为独立 `core/runItem` approval_response + 外层产品回执，不再携带 `_core_run_item_event`；WriterArtifact 表与 WriterAppRequest 表保留读/打开/响应副作用；`ChatThread.vue` 和 core/ui tests 仍覆盖 transcript/runtime part 兼容 | 必须 | 继续把 ChatThread 的运行 part 语义迁到 canonical parts 后收缩 |
| CLI 是否开发/调试混在用户命令 | 维护标注（2026-06-30）：`agent/tool/debug/message/step` 与 `quick/chat` 已删除，普通 CLI 已只剩主线入口；旧 Writer event formatter 与旧 agent event helper 已删除 | 已处理到当前阶段 | 继续防止旧入口/旧 formatter 回流 |
| provider/model/thinking 参数是否多处解释 | 是，Settings、Workbench、store、backend config、LLM client、adapter profiles 都解释 | 必须 | Core model capability + run params |
| 错误处理是否靠字符串判断 | 是，tool failure types、test assertion failure、old_string、fallback_reason、phase 字符串大量存在 | 必须 | 结构化 error code |
| 状态是否唯一事实源 | 方向上是 snapshot；维护标注（2026-07-01）：runtime terminal status 已优先落入 `snapshot.core.status`，队列分发已改为 Core status 优先；维护标注（2026-07-01 第六十八切片）：`turn/steer` 与 `turn/interrupt` 也已优先按 `snapshot.core.turns` 判断终态，外层 turn running 不再压过 Core completed/failed；TaskManager 已删除，但 transcript/session 仍保留业务状态 | 必须 | 继续明确 UI/队列/控制入口只认 snapshot，session/transcript 只保留业务持久状态 |
| 删除代码后能否用更少测试覆盖同一行为 | 可以，但需要先定义 canonical event/snapshot contract | 必须 | 用 contract test 替代旧兼容分支测试 |

## 11. 维护标注：2026-07-01 reducer 旧投影收缩

本次维护已确认 `thread/status/changed`、`turn/metrics`、`item/delta`、`artifact/created` 在后端 app 生产代码中没有写入入口，并从 `app_server/reducer.py` 删除对应旧归约分支。快照重建测试已改为用 `core/runItem` message 验证 replay，运行文本只进入 `snapshot.core.items`，不再保护外层 Writer `items` 的旧 delta 投影。

历史保留项不是兼容层，而是当时仍属于产品操作事实的 `turn/accepted`、`turn/started`、`turn/interrupted`、`turn/completed`、`item/requestApproval`、`serverRequest/resolved`、queue 事件，以及审批继续失败时的外层 `error` 回执。后续维护已继续删除 `turn/completed`、`item/requestApproval`、外层 `error` 与重复 `item/completed`，并把控制入口收敛到 Core 终态判断。下一步复杂度重点应转向 ChatThread 的 canonical part 渲染，以及继续把产品操作与运行事实分层。

维护标注（2026-07-01 第六十切片）：CLI formatter 已直接识别 `core/runItem` 的 message、tool、approval、artifact、usage、status、error，并删除旧 `item/delta` 显示分支；CLI 测试不再保护旧文本 delta carrier。CLI 仍保留 turn start、queue、serverRequest resolved 等产品操作事件展示。

维护标注（2026-07-01 第六十一切片）：长上下文 App Server E2E 脚本已从旧 `item/delta` 观察改为 `core/runItem` message 观察，结果字段同步改为 `first_agent_message_event_ms` / `provider_message_observed`。活跃验证脚本不再把旧文本 delta carrier 当作实时链路事实。

维护标注（2026-07-01 第六十二切片）：审批继续失败已改为独立 Core error + Core failed status run item；Writer reducer 和 CLI 删除外层 `error` AppEvent 分支。错误事实当前只应进入 `snapshot.core.last_error` / `snapshot.core.status`，外层 AppEvent 不再承载错误状态。

维护标注（2026-07-01 第六十三切片）：删除 Writer 后端根目录下旧 `/api/sessions/{id}/chat` SSE 验证脚本和配套截图产物：`quick_verify.ps1`、`regression_suite.ps1`、`run_all_phases.ps1`、`run_all_phases_v3.ps1`、`test_sse.ps1`、`screenshot1_initial.png`、`screenshot2_main.png`、`screenshot3_main.png`、`screenshot4_scrolled.png`。当前验证入口不再维护旧 `writer_*` SSE 事件采集脚本；`check_app_server.py` 因使用当前 App Server client 暂保留。

维护标注（2026-07-01 第六十四切片）：Writer CLI 删除外层 `item/started` / `item/completed` 对旧 agent/tool/serverRequest carrier 的显示兼容；运行文本、工具和审批请求只从 `core/runItem` 显示。外层 item 事件在 CLI 中只保留当前 user message 产品事实。

维护标注（2026-07-01 第六十五切片）：`item/requestApproval` 旧审批 carrier 已从 Writer App Server hub、reducer、CLI 和测试中删除；审批请求事实只由 Core `RunItemEvent(kind="approval_request")` 进入 `snapshot.core.requests`。外层 `serverRequest/resolved` 仍作为用户操作回执保留。

维护标注（2026-07-01 第六十六切片）：`turn/completed` 旧 runtime completion carrier 已从 Writer reducer、CLI 和相关测试中删除；队列调度、失败状态和快照重建均改用 Core `RunItemEvent(kind="status")` completed/failed。外层 turn 事件当前只保留用户操作和控制事实。

维护标注（2026-07-01 第六十七切片）：删除 `item/completed` 重复用户消息事件；turn/start 初始 AppEvent 从 4 条收缩到 3 条，外层 item 事件只剩当前产品输入事实 `item/started(userMessage)`。

维护标注（2026-07-01 第六十八切片）：`turn/steer` 与 `turn/interrupt` 已改为优先按 `snapshot.core.turns` 判断有效状态；Core 已完成/失败的 turn 不再因为外层 `snapshot.turns` 仍为 running 而接受 guidance 或 interrupt。运行终态不只进入展示和队列分发，也成为当前控制入口的权威事实。

维护标注（2026-07-01 第六十九切片）：删除 Writer 内未使用的 `app/core/events/__init__.py`；旧 `sse_event(event, data)` 包装函数没有调用方，属于已退出的 Writer SSE 事件语言残留。当前实时主线继续限定为 App Server websocket + snapshot 和 Core `RunItemEvent`。

维护标注（2026-07-01 第七十切片）：Writer member manifest 的 `/api/core` 能力说明已删除 `events`；旧 `/api/core/sessions/{id}/events` 路由此前已下线，当前 Core HTTP 兼容面只声明 sessions、messages、providers、usage，不再把 runtime events 暴露为外部能力。

维护标注（2026-07-01 第七十一切片）：删除 `writer_service.py` 中固定返回 `None` 的 `_infer_interaction_mode()` 和 `send_message()` 中对应的 dead branch。Writer 任务入口不再保留旧交互模式推断壳，session mode 只由明确的会话创建/更新路径维护。

维护标注（2026-07-01 第七十二切片）：删除未接入生产运行主线的 `app/core/writer/tool_executor.py`、`app/core/writer/scope_guard.py` 以及对应测试 `test_tool_executor.py`、`test_scope_guard.py`。当前工具执行主线只保留 `core_kernel_adapter.py` 内的 `ReadOnlyToolExecutor` / `ReadWriteToolExecutor`；这一步删除约 1,217 行孤儿工具/兼容测试代码，但通用工具仍需继续下沉 Core。

维护标注（2026-07-01 第八十切片）：`runtime.*` fact 到 canonical `RunItemEvent` 的映射已从 Writer `app_server/runtime_bridge.py` 下沉到 Core `lamtools_core.event.runtime_projection`。Writer bridge 当前只保留 `WriterArtifact` 和 approval request 的产品持久化副作用；测试也改为从 Core contract 导入映射函数。当前口径 Writer backend+CLI 31,432 行，Writer runtime 合计 39,313 行，距离 6,000 行目标仍有约 33k 行待收缩。

维护标注（2026-07-01 第八十一切片）：Writer 私有 `services/runtime_fact_projection.py` 已删除；其 `runtime.part` 增长缓冲能力下沉为 Core `RuntimeProjectionBuffer`，原回归测试迁入 Core `test_runtime_projection.py`。当前口径 Writer backend+CLI 31,365 行，Writer runtime 合计 39,246 行；运行事实输入/缓冲/映射已经不再是 Writer member 自有模块。

维护标注（2026-07-01 第八十二切片）：Writer `runtime_fact_recorder.py` 中 CoreEvent 运行类别、默认摘要和 payload preview 裁剪函数已下沉到 Core `runtime_projection`，`runtime_runner.py` 也不再从 Writer recorder 导入通用分类函数。当前口径 Writer backend+CLI 31,324 行，Writer runtime 合计 39,205 行；Writer recorder 边界进一步收缩到 transcript 同步与产品投影发布。

维护标注（2026-07-01 第八十三切片）：Writer 私有 `services/runtime_fact_helpers.py` 已删除；runtime payload 的 model call id、response index、tool id、tool args、usage token 和 visible content helper 已下沉到 Core `runtime_projection`。当前口径 Writer backend+CLI 31,239 行，Writer runtime 合计 39,120 行；`RuntimeTranscriptSink` 仍是 Writer transcript adapter，但不再拥有 runtime payload 基础解释规则。

维护标注（2026-07-01 第八十四切片）：KernelResult / CoreEvent 摘要能力已下沉到 Core `lamtools_core.kernel.summary`，覆盖 event compaction、response block grouping、progress dict 与 kernel result summary。Writer `core_kernel_adapter.py` 删除本地实现，`writer_service.py` 直接注入 Core `summarize_kernel_result`；纯摘要单测迁入 Core。当前口径 Writer backend+CLI 31,006 行，Writer runtime 合计 38,887 行；Writer adapter 仅临时保留旧名称别名，后续应清理调用面后删除。

维护标注（2026-07-01 第八十五切片）：Writer `core_kernel_adapter.py` 中 `writer_core_event_to_progress_dict` / `summarize_core_kernel_result` 旧名称别名已删除，通用 kernel summary 能力只保留 Core contract。当前口径 Writer backend+CLI 30,995 行，Writer runtime 合计 38,876 行；后续不得从 Writer adapter 重新导出 Core 摘要能力。

维护标注（2026-07-01 第八十六切片）：Writer session API 已删除 `CODE` / `CODING` / `DEFAULT` / `EXEC` mode 旧别名兼容，session mode 只保留当前空值默认和大小写规范化。当前口径 Writer backend+CLI 30,988 行，Writer runtime 合计 38,869 行；后续继续删除仅服务历史输入的别名和兜底。

维护标注（2026-07-01 第八十七切片）：Writer App Server `load_snapshot()` 已删除历史 snapshot JSON shape 自动补齐逻辑，对应旧 shape 测试也已删除。当前口径 Writer backend+CLI 30,981 行，Writer runtime 合计 38,862 行；snapshot 读取不再承担历史迁移壳，当前数据应由当前 reducer/rebuild 生成。

## 最终结论

Writer 的复杂度主要来自 **通用 agent 能力没有真正下沉 Core，以及旧事件/旧传输/旧 projection 没有彻底退出**。

必要复杂度：

- Writer persona 和产品 prompt。
- Writer 专用工具和验收策略。
- 本地 DB adapter 和产品 UI。
- App Server 在单成员阶段的产品适配。

历史债务：

- Writer SSE -> CoreEvent 反向适配。
- TaskManager SSE 产品链路。
- `writer_git_*`、`writer_part_updated`、`writer_agent_*`、old parser key 等旧事件族；维护标注（2026-06-30）：前三类代码 helper 已删除，剩余风险主要在历史数据、projection 和 old parser key。
- service 层同时做运行、投影、transcript、SSE。
- CLI 用户命令与开发命令混层。
- 测试继续保护旧路径。

下一轮不建议先拆 UI 或继续抽新框架。正确顺序是：

```text
先删旧事件/旧传输/旧投影
再把 LLM/tool/permission/prompt/event 协议沉 Core
最后拆 WriterKit、ChatThread、Workbench、SettingsView 大文件
```
