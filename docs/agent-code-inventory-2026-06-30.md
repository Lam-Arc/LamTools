# LamTools Agent 代码功能底图

日期：2026-06-30

维护标注：本版继承 `docs/agent-code-inventory-2026-06-29.md` 的层级口径，按当前工作区再次更新。旧版保留为 2026-06-29 快照；本版作为后续删减和接口收敛的当前路由文档。

目的：为后续精简代码建立“功能区 -> 文件路径 -> 删减判断”映射。这里继续按 agent 运行链路划分为四个大类：LLM 前、LLM 中、LLM 后、其他。每个小类都归属到一个中类，每个中类都归属到一个大类。

范围说明：

- 活跃产品源码：`core/src`、`core/ui/src`、`members/writer/backend/app`、`members/writer/backend/writer_cli`、`members/writer/frontend/src`、`members/artist/backend/app`、`members/artist/frontend/src`、`scripts`、根入口 `lamtools.cmd`、`writer.cmd`、`artist.cmd`
- 验证代码：`core/tests`、`core/ui/tests`、`members/*/tests`、`members/writer/frontend/tests`、`tests`、`e2e/tests`
- 历史/运行产物：`.archives`、`tmp`、`.writer-artifacts`、`.codex-runtime`、`e2e/real-task-runs`、`test-*`、打包 `release/win-unpacked`、`src-tauri/target` 不纳入活跃功能区，只列为清理候选
- 第三方依赖：`node_modules`、打包内 `_internal` 不纳入项目代码
- 当前可维护源码口径：约 334 个 `py/ts/vue/js/ps1/cmd` 文件；若把 CSS、JSON/JSONC、Markdown 配置计入活跃维护面，约 350 个文件

外部成熟方案对照（2026-06-30 复核）：

- OpenAI Agents SDK 的成熟主干仍是 Agent/Runner 管 turns、tools、guardrails、handoffs、sessions，并配套 tracing、MCP 与流式事件。
- Claude Code 的成熟主干是项目指令、记忆、subagents、hooks、权限/工具范围与 SDK 化 agent loop。
- LamTools 当前方向中，`CoreLoopKernel + Kit`、工具协议、会话/事件协议属于可靠主线；自研 prompt、memory、sub-agent、display projection、桌面封装继续标为存疑；运行产物、旧入口、历史兼容和重复投影是优先减法对象。

参考源：OpenAI [Agents SDK guide](https://developers.openai.com/api/docs/guides/agents)、[Agents](https://openai.github.io/openai-agents-python/agents/)、[Guardrails](https://openai.github.io/openai-agents-python/guardrails/)；Claude Code [memory](https://code.claude.com/docs/en/memory)、[subagents](https://code.claude.com/docs/en/sub-agents)、[hooks](https://code.claude.com/docs/en/hooks)、[Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview)。

## 本版更新重点

- 新增 Core 维护入口：`lamtools.cmd`、`scripts/lamtools_cli.py`，覆盖 `dev/build/test/open/doctor/members/scaffold`。
- Member 入口继续收敛：`scripts/member_cli.py` 已覆盖 Writer `session show/rename/delete`，Artist 只保留子命令式入口。
- Writer TUI 已从活跃源码中移除：不再保留 member 内并行 Textual UI、状态 store、reducer 和 app-server 旧事件投影。
- Artist 旧 `turn_parser.py` 已删除；当前 Artist 输出解析保留在 Kit 使用的 `parse_helpers.py`，并移除 `plan.steps` 旧 schema 转换。
- Writer CLI 已直接消费 App Server 标准事件 envelope；Writer Git 上下文不再双发 `writer_git_*` 旧别名，事件测试改为断言 canonical `object`。
- Artist 生命周期/回复实时展示已改为直接透传 Core display `kind`；`artist_turn_started`、`artist_reply_delta`、`artist_turn_done`、旧 `core_adapter.py` 和对应测试已删除。
- GUI 会话重命名已从共享侧栏事件接到 Writer/Artist 工作台持久化。
- Writer 当前工作区出现 composer thinking 模式链路：前端选择 -> App Server `turn/start` 参数 -> 后端运行时 -> LLM client provider payload。
- 最大文件信号更新：除两个 core adapter 外，`core/ui/src/components/ChatThread.vue`、`core/ui/src/styles/layout.css`、Writer workbench、Writer CLI、session router 都已经进入删减/深模块化观察名单。

## 总览

| 大类 | 中类 | 小类数量 | 覆盖重点 |
|---|---:|---:|---|
| LLM 前 | 任务入口、上下文、prompt、模型配置、记忆召回、资源装载 | 31 | 用户输入进入模型前的整理、筛选、拼接、预算、配置 |
| LLM 中 | 模型调用、循环控制、工具调用、权限、人机协作、子代理、流式事件 | 36 | 模型调用期间的 agent loop、工具执行、状态推进和中断恢复 |
| LLM 后 | 结果解析、验收、自评、记忆写回、持久化、前端投影、产物管理 | 32 | 模型输出之后的解释、落库、展示、验证和可恢复状态 |
| 其他 | 产品壳、共享 UI、数据库、桌面、测试、脚本、文档、历史产物 | 33 | 非核心 agent 但影响运行、维护和删减判断的代码 |

## LLM 前

### 1. 任务入口与会话上下文

小类：

- Web/API 入口：`members/writer/backend/app/routers/session.py`、`members/writer/backend/app/routers/core_http.py`、`members/artist/backend/app/routers/session.py`、`members/artist/backend/app/routers/core_http.py`
- 产品 CLI 入口：`members/writer/backend/writer_cli/**`、`members/artist/backend/app/cli.py`、`writer.cmd`、`artist.cmd`、`scripts/member_cli.py`
- 会话 CLI 操作：Writer `session list/new/show/messages/status/result/rename/delete`，Artist `session/copy/rename` 包装入口
- App Server 输入接收：`members/writer/backend/app/app_server/router.py`、`members/writer/backend/app/app_server/connection.py`、`members/writer/backend/app/app_server/queue.py`
- 前端输入框与工作台入口：`members/writer/frontend/src/views/CoreWorkbenchView.vue`、`members/artist/frontend/src/views/CoreWorkbenchView.vue`、`core/ui/src/components/ComposerBar.vue`
- 会话/项目选择上下文：`members/writer/frontend/src/stores/session.ts`、`members/writer/frontend/src/stores/project.ts`、`members/artist/frontend/src/stores/session.ts`、`core/ui/src/components/SessionSidebar.vue`

判断：可靠到存疑。用户入口更完整，Writer 当前保留 Web/App Server/CLI 三类入口；后续要继续确认主线入口，开发/调试入口应迁到 developer 层。

### 2. Persona 与项目规则装载

小类：

- Writer persona：`members/writer/backend/app/core/persona.py`、`members/writer/backend/app/prompts/writer/persona.md`
- Writer 固定规则片段：`members/writer/backend/app/prompts/writer/execution_discipline.md`、`members/writer/backend/app/prompts/writer/reply_contract.md`、`members/writer/backend/app/prompts/writer/platform.md`、`members/writer/backend/app/prompts/writer/platform_windows.md`
- AGENTS/project instructions：`members/writer/backend/app/core/writer/project_instructions.py`、`members/writer/backend/app/core/prompt_files.py`、`members/writer/backend/app/prompts/writer/prompt_files.md`
- 资源目录：`members/writer/backend/app/core/resource_dirs.py`、`core/skills/README.md`、`members/writer/skills/README.md`
- Artist 身份与回复规则：`members/artist/backend/app/core/artist/identity.py`、`members/artist/backend/app/core/artist/reply.py`

判断：存疑。方向与 Claude 项目指令机制一致，但冲突处理、装载顺序和长度预算仍需要收敛成可测接口。

### 3. Prompt 拼接与预算

小类：

- Core prompt 协议：`core/src/lamtools_core/prompt/__init__.py`
- Writer prompt 组装：`members/writer/backend/app/core/prompt_assembler.py`
- Artist prompt 组装：维护标注（2026-07-01 第七十八切片）：旧 `members/artist/backend/app/core/prompt_assembler.py` 无生产入边，已删除；当前 Artist prompt/context 由 `core/artist/core_kernel_adapter.py` 和 Core prompt/runtime 输入承担
- token 估算：`core/src/lamtools_core/tokens.py`
- 上下文规格：维护标注（2026-07-01 第七十五切片）：旧 `members/writer/backend/app/core/writer/context_specs.py` 只被测试触达，已删除；当前上下文由 `WriterKit.build_context()` 与 Core runtime state 输入承担
- 任务可行性估算：`members/writer/backend/app/core/writer/runtime_feasibility.py`

判断：存疑。能力闭环存在，但 prompt 拼接、上下文预算和任务可行性散在多处；后续应形成更深的 prompt/context 模块，而不是继续加平行 helper。

### 4. 记忆召回与上下文窗口

小类：

- Core 记忆协议：`core/src/lamtools_core/mem/__init__.py`
- Writer 私有 MEM：维护标注（2026-07-01 第七十六切片）：`members/writer/backend/app/core/mem/**` 只在 `writer_service.py` 初始化但未被使用，其余只被 `test_mem.py` 触达，已删除；通用 memory 协议归属 `core/src/lamtools_core/mem/__init__.py`
- Writer 会话记忆：维护标注（2026-07-01 第七十四切片）：旧 `members/writer/backend/app/core/writer/session_memory.py` 无生产入边，已删除；当前 Writer 会话内 Core runtime state 存在 `WriterSessionState.session_memory`
- Novel 记忆适配：Novel 当前使用 `members/writer/backend/app/core/writer/novel/memory_writeback.py` 与 `tag_system.py`，不再保留旧 `core/mem/adapters/novel_writer.py`
- Artist 记忆适配：维护标注（2026-07-01 第七十八切片）：旧 `members/artist/backend/app/core/mem/**` stub 无生产入边，已删除；通用 memory 协议归属 Core
- Artist 视觉上下文：`members/artist/backend/app/services/visual_workspace.py`、`members/artist/backend/app/services/image_context_resolver.py`；维护标注（2026-07-01 第七十八切片）：旧 `core/artist/image_context.py` 无生产入边，已删除

判断：存疑。记忆是成熟 agent 的必要能力，但当前自研层较多；删减前先用真实任务验证召回收益、写回收益和预算成本。

### 5. 模型与供应商配置

小类：

- Core provider/LLM 协议：`core/src/lamtools_core/provider/__init__.py`、`core/src/lamtools_core/llm/__init__.py`
- Writer 模型配置：`members/writer/backend/app/models/llm_config.py`、`members/writer/backend/app/services/llm_config_service.py`、`members/writer/backend/app/routers/config.py`
- Writer adapter profile：`members/writer/backend/app/llm_adapters/*.jsonc`、`members/writer/backend/app/utils/llm_adapter_profiles.py`
- Writer 设置页：`members/writer/frontend/src/views/SettingsView.vue`、`members/writer/frontend/src/stores/config.ts`
- Writer thinking 参数入口：`members/writer/frontend/src/views/CoreWorkbenchView.vue`、`members/writer/frontend/src/appServer/store.ts`、`members/writer/frontend/src/types/index.ts`
- Artist provider 配置：`members/artist/backend/app/models/api_provider.py`、`members/artist/backend/app/services/api_manager.py`、`members/artist/backend/app/routers/api_provider.py`
- Artist 设置/API 页：`members/artist/frontend/src/views/ApiManage.vue`、`members/artist/frontend/src/views/SettingsView.vue`、`members/artist/frontend/src/stores/provider.ts`
- 共享 provider preset/type：`core/ui/src/data/provider-presets.ts`、`core/ui/src/types.ts`

判断：可靠到存疑。配置能力完整；thinking 选择有真实需求，但当前更像 Writer/App Server 局部能力，应收敛为模型运行参数接口，避免 UI、协议、provider payload 各自理解一遍。

## LLM 中

### 6. 核心循环

小类：

- Core loop：`core/src/lamtools_core/kernel/loop.py`
- Kit 协议：`core/src/lamtools_core/kernel/kit.py`
- loop 策略/状态/错误/追踪：`core/src/lamtools_core/kernel/policy.py`、`core/src/lamtools_core/kernel/state.py`、`core/src/lamtools_core/kernel/errors.py`、`core/src/lamtools_core/kernel/tracing.py`
- Writer Kit 适配：`members/writer/backend/app/core/writer/core_kernel_adapter.py`
- Artist Kit 适配：`members/artist/backend/app/core/artist/core_kernel_adapter.py`

判断：可靠主线。`CoreLoopKernel + Kit` 是当前最接近成熟 agent loop 的部分；两个 member adapter 过大，是首批深模块拆分候选。

### 7. 模型调用与流式接入

小类：

- Core LLM helper：`core/src/lamtools_core/llm/helpers.py`、`core/src/lamtools_core/llm/adapter.py`、`core/src/lamtools_core/llm/policy.py`
- Writer LLM client：`members/writer/backend/app/utils/llm_client.py`
- Writer thinking provider payload：`members/writer/backend/app/app_server/connection.py`、`members/writer/backend/app/utils/llm_client.py`
- Writer app-server stream：`members/writer/backend/app/app_server/connection.py`、`members/writer/backend/app/app_server/runtime_bridge.py`
- Artist LLM client：`members/artist/backend/app/utils/llm_client.py`
- Artist session stream：`members/artist/frontend/src/api/sse.ts`、`members/artist/frontend/src/composables/useSessionEvents.ts`
- SSE 格式化：`core/src/lamtools_core/sse/__init__.py`

判断：可靠到存疑。核心协议有测试；thinking、SSE、runtime snapshot、前端 projection 仍散在多层，后续应统一成“模型运行参数 + 标准事件流 + 投影适配”三段。

### 8. 工具规格、执行与权限

小类：

- Core tool 协议：`core/src/lamtools_core/tool/__init__.py`、`core/src/lamtools_core/tool/permission.py`
- Writer tool specs：`members/writer/backend/app/core/writer/tool_specs.py`
- Writer tool executor：`members/writer/backend/app/core/writer/core_kernel_adapter.py` 中的 `ReadOnlyToolExecutor` / `ReadWriteToolExecutor`。维护标注（2026-07-01）：旧孤儿 `tool_executor.py` 已删除。
- Writer 命令权限：`members/writer/backend/app/core/writer/permission.py`、`members/writer/backend/app/app_server/security.py`。维护标注（2026-07-01）：未接入生产主线的 `scope_guard.py` 已删除。
- Writer MCP：`members/writer/backend/app/core/mcp/**`
- Artist tool specs/tools：`members/artist/backend/app/core/artist/tool_specs.py`、`members/artist/backend/app/core/artist/image_prep.py`、`members/artist/backend/app/core/artist/core_kernel_adapter.py`；维护标注（2026-07-01 第七十八切片）：旧 `core/artist/tools.py` 无生产入边，已删除
- Artist 图像执行器：`members/artist/backend/app/services/executors/**`、`members/artist/backend/app/services/generate_service.py`

判断：可靠到存疑。工具与权限是必要主线；MCP 和浏览/联网类工具属于存疑，需确认重试、隔离、权限和失败语义。

### 9. 人机协作、审批与队列

小类：

- Core guardrail：`core/src/lamtools_core/guardrail/__init__.py`
- Writer guardrail：维护标注（2026-07-01 第七十七切片）：旧 `members/writer/backend/app/core/guardrail.py` 无生产入边，已删除；当前普通工具权限由 `members/writer/backend/app/core/writer/permission.py` 和 Core permission 词汇承担
- App Server 审批：`members/writer/backend/app/app_server/approvals.py`
- 队列输入与 steer：`members/writer/backend/app/app_server/queue.py`、`members/writer/backend/app/models/queued_input.py`、`members/writer/backend/app/services/queued_input_service.py`
- 前端等待/审批操作：`members/writer/frontend/src/appServer/**`、`members/writer/frontend/src/views/CoreWorkbenchView.vue`
- Artist 检查点/反馈：`members/artist/backend/app/core/artist/core_kernel_adapter.py` 中的 VLM verification / artifact review status；维护标注（2026-07-01 第七十八切片）：旧 `feedback.py`、`visual_review.py` 无生产入边，已删除

判断：可靠到存疑。方向与 human-in-the-loop 一致，但 Writer 队列、审批、运行中输入的状态投影仍是高风险区。

### 10. 子代理与多代理

小类：

- Core agent 协议：`core/src/lamtools_core/agent.py`
- Writer agent runtime：`members/writer/backend/app/core/writer/agent_runtime.py`
- Architecture agent：`members/writer/backend/app/core/writer/agents/architecture_agent.py`
- Writer 子代理配置 UI：`members/writer/frontend/src/views/SettingsView.vue`
- 子代理事件：`members/writer/backend/app/core/writer/events.py`

判断：存疑。概念与 OpenAI handoffs/agents-as-tools、Claude subagents 对齐，但当前 Writer 子代理有上下文、权限、workspace 差异；先收敛协议，再扩功能。

### 11. 运行事件与实时投影

小类：

- Core event/display：`core/src/lamtools_core/event/__init__.py`、`core/src/lamtools_core/run_event/__init__.py`、`core/src/lamtools_core/kernel/display.py`
- Writer runtime event：`members/writer/backend/app/models/runtime_event.py`。维护标注（2026-07-01）：旧 `core/writer/events.py` 和旧 `/runtime-events` REST router 已删除；runtime event 暂仅作为内部投影 adapter 保留。
- App Server ledger/snapshot/reducer：`members/writer/backend/app/app_server/ledger.py`、`members/writer/backend/app/app_server/snapshot.py`、`members/writer/backend/app/app_server/reducer.py`
- 前端 snapshot/selectors/store：`members/writer/frontend/src/appServer/snapshot.ts`、`members/writer/frontend/src/appServer/selectors.ts`、`members/writer/frontend/src/appServer/store.ts`
- 共享运行面板：`core/ui/src/components/RuntimePanel.vue`、`core/ui/src/helpers/runtimeSteps.ts`
- Artist 产品事件与 display 消费：`members/artist/backend/app/core/events/__init__.py`、`members/artist/frontend/src/stores/session.ts`；维护标注（2026-07-01 第七十九切片）：旧 `members/artist/backend/app/core/artist/events.py` 无生产入边，已删除，当前生命周期/回复展示继续直接透传 Core display `kind`

判断：可靠到存疑。Artist 生命周期/回复展示已收敛到 Core display，Artist 只保留图片、视频、批任务、长任务等产品事件；Writer event、App Server event 与 transcript/app snapshot 边界仍需继续收敛，避免修一个展示问题时同时改四套语义。

## LLM 后

### 12. 输出解析与状态转换

小类：

- Core runtime 结果协议：`core/src/lamtools_core/runtime/__init__.py`
- Writer schema/parser/transition：`members/writer/backend/app/core/writer/schemas.py`；维护标注（2026-07-01 第七十四切片）：旧 `transitions.py` 无生产入边，已删除；维护标注（2026-07-01 第七十五切片）：旧 `turn_parser.py` 只被测试触达，已删除，当前模型输出通过 Core tool call / RunItemEvent 主线进入 Writer
- Writer action/part/artifact：维护标注（2026-07-01 第七十四切片）：旧 `members/writer/backend/app/core/writer/artifacts.py` 无生产入边，已删除；当前 App Server artifact 主线在 `members/writer/backend/app/app_server/artifacts.py` 和 `models/app_server.py`
- Artist schema/parser/transition：`members/artist/backend/app/core/artist/schemas.py`、`members/artist/backend/app/core/artist/parse_helpers.py`；维护标注（2026-07-01 第七十八切片）：旧 `transitions.py`、`normalizer.py` 无生产入边，已删除
- Artist artifact/contact sheet：`members/artist/backend/app/core/artist/artifact_registry.py`、`members/artist/backend/app/core/artist/contact_sheet.py`；维护标注（2026-07-01 第七十八切片）：旧 `artifacts.py` 无生产入边，已删除

判断：可靠到存疑。解析层必要，但兼容旧字段的代码要逐步压缩到明确迁移层。

### 13. 验收、自评与修复请求

小类：

- Writer completion verifier：维护标注（2026-07-08）：旧 `members/writer/backend/app/core/writer/completion_verifier.py` 自研完成验收层已删除；Writer 不再在自然最终回复后自动跑语法/浏览器/产物扫描，后续需要检查时由用户或任务 prompt 显式要求模型调用工具执行。
- Writer verification specs：维护标注（2026-07-01 第七十四切片）：旧 `members/writer/backend/app/core/writer/verification_specs.py` 只是未被调用的说明常量，已删除；维护标注（2026-07-08）：当前普通任务不再保留自动完成验收主线，只保留 `failure_specs.py` 等失败恢复提示。
- Writer failure specs：`members/writer/backend/app/core/writer/failure_specs.py`
- Writer 普通自审：维护标注（2026-07-01 第七十三切片）：`members/writer/backend/app/core/writer/self_review.py` 未接入生产主线，已删除；维护标注（2026-07-08）：普通任务自动完成验收层已删除，显式语法/构建检查走模型工具调用。
- Artist visual review：当前主线在 `members/artist/backend/app/core/artist/core_kernel_adapter.py` 的 VLM verification；维护标注（2026-07-01 第七十八切片）：旧 `visual_review.py` 无生产入边，已删除
- Novel guardrail/self review：`members/writer/backend/app/core/writer/novel/guardrail.py`、`members/writer/backend/app/core/writer/novel/self_review.py`

判断：维护标注（2026-07-08）：旧判断已过期。自研自动完成验收收益不足且会破坏最终回复边界，已按减法删除；显式检查需求不再沉为运行时隐式层。

### 14. 持久化、会话和 transcript

小类：

- Core session/usage：`core/src/lamtools_core/session/__init__.py`、`core/src/lamtools_core/usage/__init__.py`
- Writer DB 与模型：`members/writer/backend/app/database.py`、`models/**`
- Writer session lifecycle：`members/writer/backend/app/services/session_lifecycle.py`
- Writer transcript：`members/writer/backend/app/services/transcript_service.py`、`members/writer/backend/app/models/transcript.py`
- Writer app-server 可恢复状态：`members/writer/backend/app/app_server/ledger.py`、`members/writer/backend/app/app_server/snapshot.py`、`members/writer/backend/app/app_server/cleanup.py`
- Writer project/attachment/step：`members/writer/backend/app/routers/project.py`、`members/writer/backend/app/routers/attachment.py`、`members/writer/backend/app/routers/step.py`、`members/writer/backend/app/services/attachment_service.py`
- Artist DB 与模型：`members/artist/backend/app/database.py`、`models/**`
- Artist session/reference/billing：`members/artist/backend/app/services/session_manager.py`、`members/artist/backend/app/services/reference_manager.py`、`members/artist/backend/app/services/billing_service.py`

判断：可靠到存疑。SQLite 单文件符合本地产品；手写迁移、多套状态表和 snapshot/transcript 双路径需要继续压缩。维护标注（2026-07-01 第八十七切片）：`load_snapshot()` 已删除历史 snapshot JSON shape 自动补齐逻辑，读取路径不再承担旧数据迁移壳。

### 15. 前端消息渲染与状态展示

小类：

- 共享聊天线程：`core/ui/src/components/ChatThread.vue`
- Writer transcript projection：`members/writer/frontend/src/runtime/transcript.ts`、`members/writer/frontend/src/runtime/runtimeParts.ts`、`members/writer/frontend/src/runtime/sessionStatus.ts`
- Writer Markdown 渲染：`members/writer/frontend/src/components/MarkdownRenderer.vue`
- Writer app-server store/selectors：`members/writer/frontend/src/appServer/store.ts`、`members/writer/frontend/src/appServer/selectors.ts`、`members/writer/frontend/src/appServer/snapshot.ts`
- Writer workbench 展示：`members/writer/frontend/src/views/CoreWorkbenchView.vue`
- Artist workbench 展示：`members/artist/frontend/src/views/CoreWorkbenchView.vue`
- Artist 图片查看/血缘：`members/artist/frontend/src/components/session/Lightbox.vue`、`members/artist/frontend/src/components/session/LineageDrawer.vue`

判断：存疑。UI 能跑，但 `core/ui/src/components/ChatThread.vue`、Writer workbench 和 app-server projection 都过大；展示层仍是历史问题高发区。

### 16. 产物、文件和 Git

小类：

- Writer artifacts：`members/writer/backend/app/app_server/artifacts.py`；维护标注（2026-07-01 第七十四切片）：旧 `core/writer/artifacts.py` 已删除，artifact 持久化与展示以 App Server 主线为准
- Writer Git：`members/writer/backend/app/core/writer/git.py`；维护标注（2026-07-01 第七十五切片）：旧 `git_context.py` 只被测试触达，已删除
- Writer 文件范围：`members/writer/backend/app/core/writer/core_kernel_adapter.py` 路径校验、`members/writer/backend/app/core/writer/permission.py`
- Writer 桌面/前端产物读取：`members/writer/frontend/src-tauri/**`、`members/writer/frontend/src/api/**`
- Artist 下载与图片文件：`members/artist/backend/app/routers/download.py`、`members/artist/backend/app/services/generate_service.py`、`members/artist/backend/app/utils/image_client.py`
- 前端下载：`members/artist/frontend/src/api/download.ts`、`members/artist/frontend/src/composables/useDownload.ts`

判断：可靠到存疑。文件/Git 是 coding agent 的核心能力，但权限、路径、桌面环境差异和打包产物污染必须继续作为硬门槛。

## 其他

### 17. 产品壳、共享 UI 与主题

小类：

- Core UI shell：`core/ui/src/components/WorkspaceShell.vue`、`core/ui/src/components/SettingsShell.vue`
- Core UI controller/layout/theme：`core/ui/src/composables/**`、`core/ui/src/helpers/**`、`core/ui/src/data/theme-presets.ts`
- 共享侧栏会话操作：`core/ui/src/components/SessionSidebar.vue`
- Writer theme/labels：`members/writer/frontend/src/lib/**`
- Artist theme/settings：`members/artist/frontend/src/views/SettingsView.vue`
- UI 基础类型：`core/ui/src/types.ts`、`members/*/frontend/src/types/index.ts`
- 大型布局样式：`core/ui/src/styles/layout.css`、`core/ui/src/styles/base.css`、`core/ui/src/styles/variables.css`

判断：可靠到存疑。共享 UI 有价值；GUI 会话重命名已接通，但设置页、主题和布局样式膨胀，后续应抽深模块或删减非必要定制。

### 18. 后端应用壳与桌面

小类：

- Core app/http：`core/src/lamtools_core/app/factory.py`、`core/src/lamtools_core/http/routes.py`
- Writer FastAPI：`members/writer/backend/app/main.py`
- Writer app-server websocket：`members/writer/backend/app/app_server/**`
- Writer desktop：`members/writer/backend/desktop_server.py`、`members/writer/frontend/electron/**`、`members/writer/frontend/src-tauri/**`
- Artist FastAPI：`members/artist/backend/app/main.py`
- Artist 桌面/配置：`members/artist/desktop/**`、`members/artist/backend/app/config.py`

判断：存疑。桌面封装同时存在 Electron/Tauri/PyInstaller/pywebview 痕迹，是后续删减重点。

### 19. 测试与验证

小类：

- Core 单元/契约：`core/tests/**`、`core/ui/tests/**`
- Writer 后端测试：`members/writer/backend/tests/**`
- Writer 前端测试：`members/writer/frontend/tests/**`
- Artist 后端测试：`members/artist/backend/tests/**`
- E2E：`e2e/tests/**`、`tests/*.spec.ts`
- 运行验证脚本：`members/writer/frontend/scripts/**`、`members/writer/backend/*.ps1`

判断：存疑到债务。有效测试很多，但 mock、真实外部依赖、历史 E2E、运行脚本混杂；默认测试入口必须继续分层。

### 20. 脚本、模板和文档

小类：

- 根维护 CLI：`lamtools.cmd`、`scripts/lamtools_cli.py`
- 成员 CLI 包装：`writer.cmd`、`artist.cmd`、`scripts/member_cli.py`
- 跨成员脚本：`scripts/dev.ps1`、`scripts/build.ps1`、`scripts/test.ps1`、`scripts/scaffold-member.ps1`
- 端口与运行配置：`scripts/ports.json`
- 新成员模板：`core/templates/member/**`
- 根文档：`README.md`、`PRODUCT.md`、`docs/**`
- 成员文档：`members/writer/docs/**`、`members/artist/docs/**`
- CLI/GUI 当前文档：`docs/cli-guide.md`、`docs/gui-guide.md`、`docs/cli-gui-entry-implementation-review-2026-06-30.md`

判断：可靠到债务。`lamtools` 作为 Core 维护入口是可靠方向；但 developer 命令、operation catalog、provider/model CLI 还未完全收敛，旧规划文档里仍有过期入口，需要维护标注或删除。

### 21. 历史/运行产物与样例工程

小类：

- 运行产物：`tmp/**`、`.writer-artifacts/**`、`.codex-runtime/**`、`tmp_writer_*.log`
- 历史归档：`.archives/**`
- E2E 大型产物：`e2e/real-task-runs/**`
- 打包产物：`members/writer/frontend/release/**`、`members/writer/frontend/src-tauri/target/**`
- 示例/夹具工程：`test-*`、`test-blog-project/**`、`kbtool-task/**`
- 个人临时文件：`resume.*`

判断：债务为主。它们会污染搜索、误导“全量代码阅读”、增加仓库体积，应优先建立归档/删除策略。

## 首轮删减优先级

1. 运行产物和打包产物：先确认哪些已被 `.gitignore` 忽略，仓库只保留最小可复现夹具。
2. 事件/投影链路：已删 Writer TUI 旁路、CLI 旧事件翻译、Git 旧别名双发，并删掉 Artist 生命周期旧事件和旧 `core_adapter.py`；维护标注（2026-07-01 第八十切片）：`runtime.*` fact 到 `RunItemEvent` 的映射已下沉到 Core `lamtools_core.event.runtime_projection`，Writer `runtime_bridge.py` 只保留产品持久化适配。维护标注（2026-07-01 第八十一切片）：Writer 私有 `services/runtime_fact_projection.py` 已删除，part-growth 缓冲也归 Core。维护标注（2026-07-01 第八十二切片）：CoreEvent 归类、默认摘要和 payload preview 也已归 Core runtime projection。维护标注（2026-07-01 第八十三切片）：Writer 私有 `services/runtime_fact_helpers.py` 已删除，runtime payload 基础解释 helper 也归 Core。维护标注（2026-07-01 第八十四切片）：KernelResult / CoreEvent 展示摘要已下沉到 Core `lamtools_core.kernel.summary`，Writer adapter 不再维护摘要实现。维护标注（2026-07-01 第八十五切片）：Writer adapter 中旧 kernel summary 名称别名已删除，通用摘要能力只通过 Core 正式 contract 使用。剩余重点是 Core event、App Server event、transcript snapshot 与前端 projection 边界继续收敛。
3. 大文件深模块化：优先处理 `members/writer/backend/app/core/writer/core_kernel_adapter.py`、`core/ui/src/components/ChatThread.vue`、`core/ui/src/styles/layout.css`、`members/writer/backend/app/services/writer_service.py`、`members/writer/frontend/src/views/CoreWorkbenchView.vue`、`members/writer/frontend/src/views/SettingsView.vue`、`members/writer/backend/writer_cli/__main__.py`。
4. 入口层继续减法：把 developer 命令下沉到 `writer dev ...` / `artist dev ...`，把根维护入口固定在 `lamtools`，普通产品入口只保留用户任务和会话操作。维护标注（2026-07-01 第八十六切片）：Writer session API 已删除 `CODE` / `CODING` / `DEFAULT` / `EXEC` mode 旧别名兼容，普通会话入口不再为历史 mode 名称做自动纠偏。
5. 桌面封装路线：Electron、Tauri、PyInstaller、pywebview 不应长期并行作为同等主线。
6. 测试分层：默认测试只跑稳定单元/契约/核心集成；真实外部 E2E、历史演示、mock pipeline 显式分组。
7. 文档清理：旧 HookSet、旧 mock 计划、旧入口文档要标记为历史或删除。

## 最大文件信号

| 文件 | 行数 | 功能区 | 初步判断 |
|---|---:|---|---|
| `members/writer/backend/app/core/writer/core_kernel_adapter.py` | 5109 | LLM 中/核心循环 | 存疑，过深且混合 prompt、执行、事件、验收；KernelResult/CoreEvent 摘要已迁出，旧摘要别名已删除 |
| `core/ui/src/components/ChatThread.vue` | 3475 | LLM 后/展示 | 存疑，共享 UI 承担过多消息状态 |
| `core/ui/src/styles/layout.css` | 2417 | 其他/UI 布局 | 存疑，样式膨胀且跨产品影响大 |
| `members/writer/frontend/src/views/CoreWorkbenchView.vue` | 2404 | LLM 前/后展示 | 存疑，输入、队列、审批、投影、thinking 设置混合 |
| `members/writer/backend/app/services/writer_service.py` | 2300 | LLM 前/中/后桥接 | 存疑，入口编排和展示事件混合 |
| `members/writer/frontend/src/views/SettingsView.vue` | 2016 | 其他/设置 | 存疑，模型、agent、工具、主题混合 |
| `members/artist/backend/app/core/artist/core_kernel_adapter.py` | 1741 | LLM 中/核心循环 | 存疑，仍偏大但已是 Artist Kit 主线 |
| `members/writer/backend/app/core/writer/agents/architecture_agent.py` | 1721 | LLM 中/子代理 | 存疑，独立 agent 逻辑过大 |
| `core/src/lamtools_core/kernel/loop.py` | 1502 | LLM 中/核心循环 | 可靠但需谨慎改动 |
| `members/writer/backend/writer_cli/__main__.py` | 1674 | LLM 前/产品 CLI | 存疑，用户命令和开发命令仍需拆层 |
| `members/writer/backend/app/routers/session.py` | 1319 | LLM 前/后会话 API | 存疑，会话 API 承担过多历史兼容 |
| `members/writer/backend/app/core/writer/completion_verifier.py` | 1166 | LLM 后/验收 | 存疑，验收策略需要深模块化 |
| `members/artist/backend/app/services/artist_service.py` | 1127 | LLM 前/中/后桥接 | 存疑，仍混合入口编排、产物落库和服务响应 |
| `members/artist/backend/app/services/generate_service.py` | 1107 | LLM 中/工具执行 | 存疑，图像执行和状态更新耦合 |
| `members/artist/backend/app/cli.py` | 1073 | LLM 前/产品 CLI | 存疑，后端 CLI 仍是位置参数实现 |

## 覆盖校验

本底图用路径覆盖活跃代码：

- `core/src/lamtools_core/**` 覆盖在 LLM 前/中/后基础协议与 Other 应用壳。
- `core/ui/src/**` 覆盖在 LLM 前输入、LLM 后展示、Other UI shell/主题/布局。
- `members/writer/backend/app/**` 覆盖在 Writer 的 LLM 前/中/后与 Other 数据/API/app-server。
- `members/writer/backend/writer_cli/**` 覆盖在 LLM 前产品入口和 Other 产品壳；旧 `members/writer/backend/writer_tui/**` 已删除，不再作为当前功能区。
- `members/writer/frontend/src/**` 覆盖在 Writer 输入、配置、投影、展示与 GUI。
- `members/artist/backend/app/**` 覆盖在 Artist 的 LLM 前/中/后与 Other 数据/API。
- `members/artist/frontend/src/**` 覆盖在 Artist 输入、配置、Core display 消费、产品事件和展示。
- `lamtools.cmd`、`writer.cmd`、`artist.cmd`、`scripts/**` 覆盖在 Other/脚本入口；其中 `scripts/member_cli.py` 也连接 LLM 前产品入口。
- 测试与历史产物不计入 agent 功能闭环，但列入删减对象。

## 下一步建议

先做“减法清单”而不是重构实现：

1. 生成可删除/归档候选列表，按产物、历史样例、旧文档、并行入口四类分组。
2. 为 Writer 事件链路画当前数据流，确认唯一主线和兼容层。
3. 对 Writer 核心适配、ChatThread、Writer workbench 做二级拆分方案，但先不动代码，避免把大文件拆成更多浅模块。
4. 把 thinking 参数收敛为模型运行参数接口，避免 GUI、App Server、LLM client 三处并行解释。
