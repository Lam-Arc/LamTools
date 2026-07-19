# LamTools Agent 代码功能底图

日期：2026-06-29

维护标注（2026-06-30）：新版当前快照见 `docs/agent-code-inventory-2026-06-30.md`。本文保留为 2026-06-29 历史基线。

目的：为后续精简代码建立第一版“功能区 -> 文件路径”映射。这里按 agent 运行链路划分为四个大类：LLM 前、LLM 中、LLM 后、其他。每个小类都归属到一个中类，每个中类都归属到一个大类。

范围说明：

- 活跃产品源码：`core/src`、`core/ui/src`、`members/writer/backend/app`、`members/writer/frontend/src`、`members/artist/backend/app`、`members/artist/frontend/src`、`scripts`
- 验证代码：`core/tests`、`core/ui/tests`、`members/*/tests`、`members/writer/frontend/tests`、`tests`、`e2e/tests`
- 历史/运行产物：`.archives`、`tmp`、`.writer-artifacts`、`.codex-runtime`、`e2e/real-task-runs`、`test-*`、打包 `release/win-unpacked` 不纳入活跃功能区，只列为清理候选
- 第三方依赖：`node_modules`、打包内 `_internal` 不纳入项目代码

成熟方案对照：

- OpenAI Agents SDK 的成熟主干是 agent loop、tools、handoffs/agents-as-tools、guardrails、sessions、human-in-the-loop、tracing、MCP。
- Claude Code 的成熟主干是项目指令文件、可配置 subagent、权限/工具范围、记忆与上下文装载。
- LamTools 当前方向中，`CoreLoopKernel + Kit`、工具协议、事件和会话协议属于可靠主线；自研 prompt/memory/sub-agent/display 需要继续按真实任务验证；运行产物和历史兼容层是优先减法对象。

## 总览

| 大类 | 中类 | 小类数量 | 覆盖重点 |
|---|---:|---:|---|
| LLM 前 | 任务入口、上下文、prompt、模型配置、记忆召回、资源装载 | 22 | 用户输入进入模型前的整理、筛选、拼接、预算、配置 |
| LLM 中 | 模型调用、循环控制、工具调用、权限、人机协作、子代理、流式事件 | 30 | 模型调用期间的 agent loop、工具执行、状态推进和中断恢复 |
| LLM 后 | 结果解析、验收、自评、记忆写回、持久化、前端投影、产物管理 | 24 | 模型输出之后的解释、落库、展示、验证和可恢复状态 |
| 其他 | 产品壳、共享 UI、数据库、桌面、测试、脚本、文档、历史产物 | 25 | 非核心 agent 但影响运行、维护和删减判断的代码 |

## LLM 前

### 1. 任务入口与会话上下文

小类：

- Web/API 入口：`members/writer/backend/app/routers/session.py`、`members/writer/backend/app/routers/core_http.py`、`members/artist/backend/app/routers/session.py`、`members/artist/backend/app/routers/core_http.py`
- CLI 入口：`members/writer/backend/writer_cli/**`、`members/artist/backend/app/cli.py`、`writer.cmd`、`artist.cmd`、`scripts/member_cli.py`
- App Server 输入接收：`members/writer/backend/app/app_server/router.py`、`connection.py`、`queue.py`
- 前端输入框与工作台入口：`members/writer/frontend/src/views/CoreWorkbenchView.vue`、`members/artist/frontend/src/views/CoreWorkbenchView.vue`、`core/ui/src/components/ComposerBar.vue`
- 会话/项目选择上下文：`members/writer/frontend/src/stores/session.ts`、`project.ts`、`members/artist/frontend/src/stores/session.ts`、`core/ui/src/components/SessionSidebar.vue`

判断：可靠到存疑。入口完整，但 Writer Web、App Server、CLI、TUI 多入口并存，后续要确认每个入口是否仍是主线。

### 2. Persona 与项目规则装载

小类：

- Writer persona：`members/writer/backend/app/core/persona.py`、`members/writer/backend/app/prompts/writer/persona.md`
- Writer 固定规则片段：`members/writer/backend/app/prompts/writer/execution_discipline.md`、`reply_contract.md`、`platform.md`、`platform_windows.md`
- AGENTS/project instructions：`members/writer/backend/app/core/writer/project_instructions.py`、`members/writer/backend/app/core/prompt_files.py`、`members/writer/backend/app/prompts/writer/prompt_files.md`
- 资源目录：`members/writer/backend/app/core/resource_dirs.py`、`core/skills/README.md`、`members/writer/skills/README.md`
- Artist 身份与回复规则：`members/artist/backend/app/core/artist/identity.py`、`reply.py`

判断：存疑。方向与 Claude 的项目指令机制一致，但需要控制长度、冲突和装载顺序。

### 3. Prompt 拼接与预算

小类：

- Core prompt 协议：`core/src/lamtools_core/prompt/__init__.py`
- Writer prompt 组装：`members/writer/backend/app/core/prompt_assembler.py`
- Artist prompt 组装：`members/artist/backend/app/core/prompt_assembler.py`
- token 估算：`core/src/lamtools_core/tokens.py`
- 上下文规格：`members/writer/backend/app/core/writer/context_specs.py`
- 任务可行性估算：`members/writer/backend/app/core/writer/runtime_feasibility.py`

判断：存疑。能力闭环存在，但 Writer prompt 拼接与上下文预算散在多个模块，后续应收敛成一个更深的模块。

### 4. 记忆召回与上下文窗口

小类：

- Core 记忆协议：`core/src/lamtools_core/mem/__init__.py`
- Writer 记忆 schema/store/budget/recall/lifecycle/provenance：`members/writer/backend/app/core/mem/**`
- Writer 会话记忆：`members/writer/backend/app/core/writer/session_memory.py`
- Novel 记忆适配：`members/writer/backend/app/core/mem/adapters/novel_writer.py`
- Artist 记忆适配：`members/artist/backend/app/core/mem/**`
- Artist 视觉上下文：`members/artist/backend/app/services/visual_workspace.py`、`image_context_resolver.py`、`members/artist/backend/app/core/artist/image_context.py`

判断：存疑。记忆是成熟 agent 的必要能力，但当前自研层较多，需用真实任务验证召回收益。

### 5. 模型与供应商配置

小类：

- Core provider/LLM 协议：`core/src/lamtools_core/provider/__init__.py`、`core/src/lamtools_core/llm/__init__.py`
- Writer 模型配置：`members/writer/backend/app/models/llm_config.py`、`services/llm_config_service.py`、`routers/config.py`
- Writer 适配配置：`members/writer/backend/app/llm_adapters/*.jsonc`、`utils/llm_adapter_profiles.py`
- Writer 设置页：`members/writer/frontend/src/views/SettingsView.vue`、`stores/config.ts`
- Artist provider 配置：`members/artist/backend/app/models/api_provider.py`、`services/api_manager.py`、`routers/api_provider.py`
- Artist 设置/API 页：`members/artist/frontend/src/views/ApiManage.vue`、`SettingsView.vue`、`stores/provider.ts`

判断：可靠到存疑。配置能力完整；多供应商兼容逻辑应该优先向标准 Responses/Chat/Anthropic Messages 适配层收敛。

## LLM 中

### 6. 核心循环

小类：

- Core loop：`core/src/lamtools_core/kernel/loop.py`
- Kit 协议：`core/src/lamtools_core/kernel/kit.py`
- loop 策略/状态/错误/追踪：`core/src/lamtools_core/kernel/policy.py`、`state.py`、`errors.py`、`tracing.py`
- Writer Kit 适配：`members/writer/backend/app/core/writer/core_kernel_adapter.py`
- Artist Kit 适配：`members/artist/backend/app/core/artist/core_kernel_adapter.py`

判断：可靠主线。`CoreLoopKernel + Kit` 是当前最接近成熟 agent loop 的部分。但两个 member adapter 过大，是首批深模块拆分候选。

### 7. 模型调用与流式接入

小类：

- Core LLM helper：`core/src/lamtools_core/llm/helpers.py`、`adapter.py`、`policy.py`
- Writer LLM client：`members/writer/backend/app/utils/llm_client.py`
- Artist LLM client：`members/artist/backend/app/utils/llm_client.py`
- Writer app-server stream：`members/writer/backend/app/app_server/connection.py`、`runtime_bridge.py`
- Artist session stream：`members/artist/frontend/src/api/sse.ts`、`composables/useSessionEvents.ts`
- SSE 格式化：`core/src/lamtools_core/sse/__init__.py`

判断：可靠到存疑。核心协议有测试，但 Writer/Artist 各自仍有流式兼容和展示映射。

### 8. 工具规格、执行与权限

小类：

- Core tool 协议：`core/src/lamtools_core/tool/__init__.py`、`tool/permission.py`
- Writer tool specs：`members/writer/backend/app/core/writer/tool_specs.py`
- Writer tool executor：`members/writer/backend/app/core/writer/tool_executor.py`
- Writer 命令权限：`members/writer/backend/app/core/writer/permission.py`、`scope_guard.py`、`members/writer/backend/app/app_server/security.py`
- Writer MCP：`members/writer/backend/app/core/mcp/**`
- Artist tool specs/tools：`members/artist/backend/app/core/artist/tool_specs.py`、`tools.py`
- Artist 图像执行器：`members/artist/backend/app/services/executors/**`、`generate_service.py`

判断：可靠到存疑。工具与权限是必要主线；MCP 和浏览/联网类工具属于存疑，需确认重试、隔离、权限和失败语义。

### 9. 人机协作、审批与队列

小类：

- Core guardrail：`core/src/lamtools_core/guardrail/__init__.py`
- Writer guardrail：`members/writer/backend/app/core/guardrail.py`
- App Server 审批：`members/writer/backend/app/app_server/approvals.py`
- 队列输入与 steer：`members/writer/backend/app/app_server/queue.py`、`models/queued_input.py`、`services/queued_input_service.py`
- 前端等待/审批操作：`members/writer/frontend/src/appServer/**`、`CoreWorkbenchView.vue`
- Artist 检查点/反馈：`members/artist/backend/app/core/artist/feedback.py`、`visual_review.py`

判断：可靠到存疑。方向与 human-in-the-loop 一致，但 Writer 队列、审批、运行中输入的状态投影仍是高风险区。

### 10. 子代理与多代理

小类：

- Core agent 协议：`core/src/lamtools_core/agent.py`
- Writer agent runtime：`members/writer/backend/app/core/writer/agent_runtime.py`
- Architecture agent：`members/writer/backend/app/core/writer/agents/architecture_agent.py`
- Writer 子代理配置 UI：`members/writer/frontend/src/views/SettingsView.vue`
- 子代理事件：`members/writer/backend/app/core/writer/events.py`

判断：存疑。概念与 OpenAI handoffs/agents-as-tools、Claude subagents 对齐，但当前 Writer 子代理有上下文、权限、workspace 差异，后续应先收敛协议再扩功能。

### 11. 运行事件与实时投影

小类：

- Core event：`core/src/lamtools_core/event/__init__.py`、`run_event/__init__.py`
- Writer runtime event：`members/writer/backend/app/core/writer/events.py`、`models/runtime_event.py`、`routers/runtime_event.py`
- App Server ledger/snapshot/reducer：`members/writer/backend/app/app_server/ledger.py`、`snapshot.py`、`reducer.py`
- 前端 snapshot/selectors/store：`members/writer/frontend/src/appServer/snapshot.ts`、`selectors.ts`、`store.ts`
- 共享运行面板：`core/ui/src/components/RuntimePanel.vue`、`helpers/runtimeSteps.ts`
- Artist 事件：`members/artist/backend/app/core/artist/events.py`、`core/events/__init__.py`、`members/artist/frontend/src/stores/session.ts`

判断：存疑。事件体系是必要主线；Writer 前端投影重复已先删掉，但 Core event、Writer event、App Server event 与 transcript/app snapshot 边界仍需继续收敛。

## LLM 后

### 12. 输出解析与状态转换

小类：

- Core runtime 结果协议：`core/src/lamtools_core/runtime/__init__.py`
- Writer schema/parser/transition：`members/writer/backend/app/core/writer/schemas.py`、`turn_parser.py`、`transitions.py`
- Writer action/part/artifact：`members/writer/backend/app/core/writer/artifacts.py`
- Artist schema/parser/transition：`members/artist/backend/app/core/artist/schemas.py`、`turn_parser.py`、`transitions.py`、`normalizer.py`、`parse_helpers.py`
- Artist artifact/contact sheet：`members/artist/backend/app/core/artist/artifacts.py`、`artifact_registry.py`、`contact_sheet.py`

判断：可靠到存疑。解析层必要，但兼容旧字段的代码要逐步压缩到明确迁移层。

### 13. 验收、自评与修复请求

小类：

- Writer completion verifier：`members/writer/backend/app/core/writer/completion_verifier.py`
- Writer verification specs：`members/writer/backend/app/core/writer/verification_specs.py`
- Writer failure specs：`members/writer/backend/app/core/writer/failure_specs.py`
- Writer self review：`members/writer/backend/app/core/writer/self_review.py`
- Artist visual review：`members/artist/backend/app/core/artist/visual_review.py`
- Novel guardrail/self review：`members/writer/backend/app/core/writer/novel/guardrail.py`、`self_review.py`

判断：存疑。验收是 agent 质量关键，但 Writer verifier 单文件过大，后续应按“验收输入、判定策略、修复触发、可视化证据”拆深模块。

### 14. 持久化、会话和 transcript

小类：

- Core session/usage：`core/src/lamtools_core/session/__init__.py`、`usage/__init__.py`
- Writer DB 与模型：`members/writer/backend/app/database.py`、`models/**`
- Writer session lifecycle：`members/writer/backend/app/services/session_lifecycle.py`
- Writer transcript：`members/writer/backend/app/services/transcript_service.py`、`models/transcript.py`
- Writer project/attachment/step：`routers/project.py`、`attachment.py`、`step.py`、`services/attachment_service.py`
- Artist DB 与模型：`members/artist/backend/app/database.py`、`models/**`
- Artist session/reference/billing：`services/session_manager.py`、`reference_manager.py`、`billing_service.py`

判断：可靠到存疑。SQLite 单文件符合本地产品；手写迁移和多套状态表需要继续压缩。

### 15. 前端消息渲染与状态展示

小类：

- 共享聊天线程：`core/ui/src/components/ChatThread.vue`
- Writer transcript projection：`members/writer/frontend/src/runtime/transcript.ts`、`runtimeParts.ts`、`sessionStatus.ts`
- Writer Markdown 渲染：`members/writer/frontend/src/components/MarkdownRenderer.vue`
- Writer workbench 展示：`members/writer/frontend/src/views/CoreWorkbenchView.vue`
- Artist workbench 展示：`members/artist/frontend/src/views/CoreWorkbenchView.vue`
- Artist 图片查看/血缘：`members/artist/frontend/src/components/session/Lightbox.vue`、`LineageDrawer.vue`

判断：存疑。UI 能跑，但 `ChatThread.vue`、Writer workbench 都过大，且投影层是历史问题高发区。

### 16. 产物、文件和 Git

小类：

- Writer artifacts：`members/writer/backend/app/app_server/artifacts.py`、`core/writer/artifacts.py`
- Writer Git：`members/writer/backend/app/core/writer/git.py`、`git_context.py`
- Writer 文件范围：`scope_guard.py`、`permission.py`
- Artist 下载与图片文件：`members/artist/backend/app/routers/download.py`、`services/generate_service.py`、`utils/image_client.py`
- 前端下载：`members/artist/frontend/src/api/download.ts`、`composables/useDownload.ts`

判断：可靠到存疑。文件/Git 是 coding agent 的核心能力，但权限、路径和桌面环境差异必须继续作为硬门槛。

## 其他

### 17. 产品壳、共享 UI 与主题

小类：

- Core UI shell：`core/ui/src/components/WorkspaceShell.vue`、`SettingsShell.vue`
- Core UI controller/layout/theme：`core/ui/src/composables/**`、`helpers/**`、`data/theme-presets.ts`
- Writer theme/labels：`members/writer/frontend/src/lib/**`
- Artist theme/settings：`members/artist/frontend/src/views/SettingsView.vue`
- UI 基础类型：`core/ui/src/types.ts`、`members/*/frontend/src/types/index.ts`

判断：可靠到存疑。共享 UI 有价值；但设置页和主题逻辑重复，后续可抽通用设置模块或删减非必要定制。

### 18. 后端应用壳与桌面

小类：

- Core app/http：`core/src/lamtools_core/app/factory.py`、`http/routes.py`
- Writer FastAPI：`members/writer/backend/app/main.py`
- Writer desktop：`members/writer/backend/desktop_server.py`、`members/writer/frontend/electron/**`、`members/writer/frontend/src-tauri/**`
- Artist FastAPI：`members/artist/backend/app/main.py`
- Artist 配置迁移：`members/artist/backend/app/config.py`

判断：存疑。桌面封装同时存在 Electron/Tauri/PyInstaller 痕迹，是后续删减重点。

### 19. 测试与验证

小类：

- Core 单元/契约：`core/tests/**`、`core/ui/tests/**`
- Writer 后端测试：`members/writer/backend/tests/**`
- Writer 前端测试：`members/writer/frontend/tests/**`
- Artist 后端测试：`members/artist/backend/tests/**`
- E2E：`e2e/tests/**`、`tests/*.spec.ts`
- 运行验证脚本：`members/writer/frontend/scripts/**`、`members/writer/backend/*.ps1`

判断：存疑到债务。有效测试很多，但 mock、真实外部依赖、历史 E2E、运行脚本混杂，必须分层。

### 20. 脚本、模板和文档

小类：

- 跨成员脚本：`scripts/dev.ps1`、`build.ps1`、`test.ps1`、`scaffold-member.ps1`
- 新成员模板：`core/templates/member/**`
- 根文档：`README.md`、`PRODUCT.md`、`docs/**`
- 成员文档：`members/writer/docs/**`、`members/artist/docs/**`

判断：可靠到债务。脚本和模板有主线价值；旧规划文档里仍有 HookSet、mock、过期入口等信息，文档也需要删减。

### 21. 历史/运行产物与样例工程

小类：

- 运行产物：`tmp/**`、`.writer-artifacts/**`、`.codex-runtime/**`、`tmp_writer_*.log`
- 历史归档：`.archives/**`
- E2E 大型产物：`e2e/real-task-runs/**`
- 打包产物：`members/writer/frontend/release/**`、`members/writer/frontend/src-tauri/target/**`
- 示例/夹具工程：`test-*`、`test-blog-project/**`、`kbtool-task/**`
- 个人简历文件：`resume.*`

判断：债务为主。它们会污染搜索、误导“全量代码阅读”、增加仓库体积，应优先建立归档/删除策略。

## 首轮删减优先级

1. 运行产物和打包产物：先确认哪些已被 `.gitignore` 忽略，仓库只保留最小可复现夹具。
2. Writer 事件/投影链路：合并 Core event、Writer event、App Server event、前端 transcript projection 的重复语义。
3. 大文件深模块化：优先处理 `core_kernel_adapter.py`、`ChatThread.vue`、`writer_service.py`、`CoreWorkbenchView.vue`、`SettingsView.vue`。
4. 桌面封装路线：Electron、Tauri、PyInstaller 不应长期并行作为同等主线。
5. 测试分层：默认测试只跑稳定单元/契约/核心集成；真实外部 E2E、历史演示、mock pipeline 显式分组。
6. 文档清理：旧 HookSet、旧 mock 计划、旧入口文档要标记为历史或删除。

## 最大文件信号

| 文件 | 行数 | 功能区 | 初步判断 |
|---|---:|---|---|
| `members/writer/backend/app/core/writer/core_kernel_adapter.py` | 5376 | LLM 中/核心循环 | 存疑，过深且混合 prompt、执行、事件、验收 |
| `core/ui/src/components/ChatThread.vue` | 3475 | LLM 后/展示 | 存疑，共享 UI 承担过多消息状态 |
| `members/writer/backend/app/services/writer_service.py` | 2300 | LLM 前/中/后桥接 | 存疑，入口编排和展示事件混合 |
| `members/writer/frontend/src/views/CoreWorkbenchView.vue` | 2273 | LLM 前/后展示 | 存疑，工作台、队列、审批、投影混合 |
| `members/writer/frontend/src/views/SettingsView.vue` | 2133 | 其他/设置 | 存疑，模型、agent、工具、主题混合 |
| `members/artist/backend/app/core/artist/core_kernel_adapter.py` | 1769 | LLM 中/核心循环 | 存疑，仍含旧兼容路径 |
| `members/writer/backend/app/core/writer/agents/architecture_agent.py` | 1721 | LLM 中/子代理 | 存疑，独立 agent 逻辑过大 |
| `core/src/lamtools_core/kernel/loop.py` | 1502 | LLM 中/核心循环 | 可靠但需谨慎改动 |

## 覆盖校验

本底图用路径覆盖活跃代码：

- `core/src/lamtools_core/**` 覆盖在 LLM 前/中/后基础协议与 Other 应用壳。
- `core/ui/src/**` 覆盖在 LLM 前输入、LLM 后展示、Other UI shell。
- `members/writer/backend/app/**` 覆盖在 Writer 的 LLM 前/中/后与 Other 数据/API。
- `members/writer/frontend/src/**` 覆盖在 Writer 输入、配置、投影、展示与桌面前端。
- `members/artist/backend/app/**` 覆盖在 Artist 的 LLM 前/中/后与 Other 数据/API。
- `members/artist/frontend/src/**` 覆盖在 Artist 输入、配置、事件、展示。
- `scripts/**` 覆盖在 Other/脚本入口。
- 测试与历史产物不计入 agent 功能闭环，但列入删减对象。

## 下一步建议

先做“减法清单”而不是重构实现：

1. 生成可删除/归档候选列表，按产物、历史样例、旧文档、并行入口四类分组。
2. 为 Writer 事件链路画当前数据流，确认唯一主线和兼容层。
3. 对 Writer 核心适配做二级拆分方案，但先不动代码，避免把大文件拆成更多浅模块。
