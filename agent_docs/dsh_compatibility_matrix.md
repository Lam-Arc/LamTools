# DSH → Sunday 宿主能力对照

user:“每一个地方 sunday 都有等价或者近似接口”+(以固定上游版本逐项补齐，候选位置不代表已经兼容)。

上游提交：`f3803c96974ad4a94195fb97e5c637e9c2a3afe3`。

来源：[官方能力目录](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/docs/capability-seams.zh.md)。

本表由 `python scripts/dsh_compat.py --matrix` 生成；修改同包 surface.json 后同步生成。

candidate = 已找到可复用的 Sunday 位置，仍需公开契约、语义适配及验收；gap = 尚无已核实的等价公开接口。

阶段 2：核心宿主；阶段 3：前端与 Remote；阶段 4：其余提供方、实验能力与真实插件。

所有项目尚未获得 DSH 运行兼容认证。浏览器、React/Cordis 与 Python/Vue 的差异需显式处理。

| DSH 服务 | 状态 | Sunday 候选 / 补齐方向 | 阶段 | 行为边界 |
| --- | --- | --- | --- | --- |
| `ctx.actionCards` | gap | 补齐 actionCards 的 Sunday 公开接口或提供方注册 | 4 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.pluginRecommendations` | gap | 补齐 pluginRecommendations 的 Sunday 公开接口或提供方注册 | 4 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.headlessStartup` | gap | 补齐 headlessStartup 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.cotTranslation` | gap | 补齐 cotTranslation 的 Sunday 公开接口或提供方注册 | 4 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.translator` | gap | 补齐 translator 的 Sunday 公开接口或提供方注册 | 4 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.hmr` | candidate | 显式 plugin.system.reload；[core/src/lamtools_core/plugin_system/management.py](../core/src/lamtools_core/plugin_system/management.py) | 2 | 显式重载可复用；不承诺任意模块图自动热替换。 |
| `ctx.pluginRegistryProbe` | gap | 补齐 pluginRegistryProbe 的 Sunday 公开接口或提供方注册 | 3 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.pluginManager` | candidate | plugin.system.* 管理操作；[core/src/lamtools_core/plugin_system/management.py](../core/src/lamtools_core/plugin_system/management.py) | 2 | 复用 supervisor 与事务，不新增第二份生命周期状态。 |
| `ctx.pluginMarket` | candidate | plugin.market.*；[core/src/lamtools_core/plugin_system/market.py](../core/src/lamtools_core/plugin_system/market.py) | 3 | 需适配源、搜索、安装状态与取消。 |
| `ctx.profileContext` | candidate | profile.list / profile.resolve；[core/src/lamtools_core/plugin_system/profiles.py](../core/src/lamtools_core/plugin_system/profiles.py) | 2 | 需公开当前组合、来源与路径的只读视图。 |
| `ctx.connection` | candidate | LamToolsTransport；[core/ui/src/transport/index.ts](../core/ui/src/transport/index.ts) | 3 | 现有传输不同于 Typert；需协议适配，不转发未知方法。 |
| `ctx.forge` | gap | 补齐 forge 的 Sunday 公开接口或提供方注册 | 4 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.forgeSession` | gap | 补齐 forgeSession 的 Sunday 公开接口或提供方注册 | 4 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.forgePanel` | gap | 补齐 forgePanel 的 Sunday 公开接口或提供方注册 | 4 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.worktrees` | gap | 补齐 worktrees 的 Sunday 公开接口或提供方注册 | 4 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.workingDirectory` | candidate | PluginContext.for_work_root；[core/src/lamtools_core/plugin_system/context.py](../core/src/lamtools_core/plugin_system/context.py) | 2 | 已有工作目录视图；缺会话持久目录变更与运行中进程边界。 |
| `ctx.mcpResources` | candidate | MCP 声明与装配；[core/src/lamtools_core/plugin_system/capabilities.py](../core/src/lamtools_core/plugin_system/capabilities.py) | 2 | MCP 工具已有；资源读写/订阅的作用域契约需单独核验。 |
| `ctx.browserUse` | gap | 补齐 browserUse 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.computerUse` | gap | 补齐 computerUse 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.cuaAccess` | gap | 补齐 cuaAccess 的 Sunday 公开接口或提供方注册 | 4 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.officeToPdf` | gap | 补齐 officeToPdf 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.attachments` | gap | 补齐 attachments 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.fileUploads` | gap | 补齐 fileUploads 的 Sunday 公开接口或提供方注册 | 3 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.llm` | candidate | llm_client / model_catalog；[core/src/lamtools_core/plugin_system/model_catalog.py](../core/src/lamtools_core/plugin_system/model_catalog.py) | 2 | 模型目录与客户端已有；缺 DSH registerAdapter、消息与流适配。 |
| `ctx.deepseekLlmApiExtensions` | gap | 补齐 deepseekLlmApiExtensions 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.tokenMeter` | gap | 补齐 tokenMeter 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.toolResultPruner` | gap | 补齐 toolResultPruner 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.sessions` | candidate | SESSIONS / sessions 公开契约 + session_store；[core/src/lamtools_core/app/core_session_store.py](../core/src/lamtools_core/app/core_session_store.py) | 2 | Python 已公开创建、状态、文本投递、取消、队列和持久事件；Sunday 事件格式不同，仍需 DSH 语义适配，非原样 append 日志。 |
| `ctx.speechController` | gap | 补齐 speechController 的 Sunday 公开接口或提供方注册 | 4 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.sessionController` | candidate | SESSIONS / sessions 公开契约 + 桌面 live 控制；[core/src/lamtools_core/app/default_agent.py](../core/src/lamtools_core/app/default_agent.py) | 3 | 需适配请求字段、消息回执、等待和流；操作存在不代表 Remote 方法等价。 |
| `ctx.sessionFileReferences` | gap | 补齐 sessionFileReferences 的 Sunday 公开接口或提供方注册 | 3 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.sessionSkillCatalog` | candidate | 技能装配；[core/src/lamtools_core/plugin_system/capabilities.py](../core/src/lamtools_core/plugin_system/capabilities.py) | 3 | 需冷会话可读的技能目录及权限过滤。 |
| `ctx.jobController` | gap | 补齐 jobController 的 Sunday 公开接口或提供方注册 | 3 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.credentialsController` | gap | 补齐 credentialsController 的 Sunday 公开接口或提供方注册 | 3 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.settingsController` | gap | 补齐 settingsController 的 Sunday 公开接口或提供方注册 | 3 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.workspaceFiles` | candidate | 现有文件工具与插件 RPC；[core/src/lamtools_core/plugin_system/context.py](../core/src/lamtools_core/plugin_system/context.py) | 3 | 需受工作区约束的 stat/read/readBytes/list/changes 公开契约。 |
| `ctx.workspaceChanges` | gap | 补齐 workspaceChanges 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.terminalController` | candidate | 桌面终端状态；[core/src/lamtools_core/app/live/terminal_state.py](../core/src/lamtools_core/app/live/terminal_state.py) | 3 | 现有状态不是通用 PTY Remote 服务，需显式适配。 |
| `ctx.workspaceController` | candidate | 现有项目与会话操作；[core/src/lamtools_core/app/default_agent.py](../core/src/lamtools_core/app/default_agent.py) | 3 | 需 Remote 请求、状态基线及重连同步契约。 |
| `ctx.directoryPickerController` | gap | 补齐 directoryPickerController 的 Sunday 公开接口或提供方注册 | 3 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.typert` | gap | 补齐 typert 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.typertGateway` | gap | 补齐 typertGateway 的 Sunday 公开接口或提供方注册 | 3 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.remoteAccess` | gap | 补齐 remoteAccess 的 Sunday 公开接口或提供方注册 | 3 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.sessionPersistence` | candidate | CoreSessionStore；[core/src/lamtools_core/app/core_session_store.py](../core/src/lamtools_core/app/core_session_store.py) | 2 | 需公开冷读取、恢复、持久化与分叉边界。 |
| `ctx.configEditor` | candidate | config_store；[core/src/lamtools_core/plugin_system/config_store.py](../core/src/lamtools_core/plugin_system/config_store.py) | 2 | 需对齐写入、重载事务与配置作用域。 |
| `ctx.settings` | candidate | config schema / config_store；[core/src/lamtools_core/plugin_system/config_store.py](../core/src/lamtools_core/plugin_system/config_store.py) | 2 | 已有表单与持久配置；需动态 namespace、脱敏读写契约。 |
| `ctx.subagentModelSelection` | candidate | 子代理与模型配置；[core/src/lamtools_core/app/default_agent.py](../core/src/lamtools_core/app/default_agent.py) | 2 | 需明确委派时的默认值、覆盖和持久化。 |
| `ctx.credentials` | candidate | 插件私有 secrets；[core/src/lamtools_core/plugin_system/secrets.py](../core/src/lamtools_core/plugin_system/secrets.py) | 2 | 仅当前插件凭据视图；不可映射为任意插件凭据读取。 |
| `ctx.deepseekAccount` | gap | 补齐 deepseekAccount 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.authorization` | gap | 补齐 authorization 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.productAnalytics` | gap | 补齐 productAnalytics 的 Sunday 公开接口或提供方注册 | 3 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.otel` | gap | 补齐 otel 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.productTelemetry` | gap | 补齐 productTelemetry 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.sessionTelemetry` | gap | 补齐 sessionTelemetry 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.storage` | candidate | 插件独立数据目录；[core/src/lamtools_core/plugin_system/plugin_data.py](../core/src/lamtools_core/plugin_system/plugin_data.py) | 2 | 文件目录不是通用存储 service；需公开 KV/domain 原语。 |
| `ctx.storageDomain` | candidate | 插件数据隔离；[core/src/lamtools_core/plugin_system/plugin_data.py](../core/src/lamtools_core/plugin_system/plugin_data.py) | 2 | 需类型化领域与多后端初始化契约。 |
| `ctx.messageFeedback` | gap | 补齐 messageFeedback 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.sessionFeedback` | gap | 补齐 sessionFeedback 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.workspaceRegistry` | candidate | 项目与会话操作；[core/src/lamtools_core/app/default_agent.py](../core/src/lamtools_core/app/default_agent.py) | 3 | 需对齐工作区身份、排序、归档和会话归属。 |
| `ctx.sessionQuery` | candidate | CoreSessionStore；[core/src/lamtools_core/app/core_session_store.py](../core/src/lamtools_core/app/core_session_store.py) | 2 | 需公开过滤、游标与跨会话读取权限。 |
| `ctx.fileReferences` | gap | 补齐 fileReferences 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.sessionReferenceResolver` | gap | 补齐 sessionReferenceResolver 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.sessionTitle` | candidate | 会话自动标题；[core/src/lamtools_core/app/session_autotitle.py](../core/src/lamtools_core/app/session_autotitle.py) | 2 | 需公开标题提供方注册与持久状态。 |
| `ctx.systemPrompt` | candidate | context.prompts.section/variable/on_assemble + system_prompt_waterfall；[core/src/lamtools_core/plugin_system/prompt_waterfall.py](../core/src/lamtools_core/plugin_system/prompt_waterfall.py), [core/src/lamtools_core/plugin_system/prompt_extensions.py](../core/src/lamtools_core/plugin_system/prompt_extensions.py), [core/tests/test_plugin_prompt_extensions.py](../core/tests/test_plugin_prompt_extensions.py) | 2 | 已验收受管同步 section/variable/assemble、插件排序及会话/agent_id 覆盖。追加于内置段之后；完整替换、动态上下文、集中顺序表、change 事件、工具 schema 及 DSH 失败语义仍需适配。 |
| `ctx.tools` | candidate | context.tools.register/restrict/guard/on + 清单 tools.jsonc；[core/src/lamtools_core/plugin_system/capabilities.py](../core/src/lamtools_core/plugin_system/capabilities.py), [core/src/lamtools_core/plugin_system/tool_extensions.py](../core/src/lamtools_core/plugin_system/tool_extensions.py), [core/tests/test_plugin_tool_extensions.py](../core/tests/test_plugin_tool_extensions.py) | 2 | 动态注册、收窄、守卫与 pre/post/result 基础子集已验收；仅扁平 schema，原数值审批。execute 包装、参数改写、动态 ask 与 DSH 决策语义仍需适配。 |
| `ctx.userQuestions` | candidate | 交互请求与频道回答路径；[core/src/lamtools_core/app/default_agent.py](../core/src/lamtools_core/app/default_agent.py) | 2 | 需公开 provider 无关的问答接口，不得以审批假代普通问题。 |
| `ctx.planMode` | candidate | plan 内置插件清单；[core/src/lamtools_core/plugins/bundled/plan/plugin.json](../core/src/lamtools_core/plugins/bundled/plan/plugin.json) | 2 | 需公开计划状态、评审和退出模式；不以提示词代替强制限制。 |
| `ctx.agentPresets` | candidate | agent_presets；[core/src/lamtools_core/plugin_system/agent_presets.py](../core/src/lamtools_core/plugin_system/agent_presets.py) | 2 | 已有组合和服务注册；需逐会话版本与撤回语义适配。 |
| `ctx.commands` | candidate | context.commands.register + command.catalog/execute + 声明式 commands；[core/src/lamtools_core/plugin_system/commands.py](../core/src/lamtools_core/plugin_system/commands.py), [core/src/lamtools_core/plugin_system/command_extensions.py](../core/src/lamtools_core/plugin_system/command_extensions.py), [core/tests/test_plugin_command_extensions.py](../core/tests/test_plugin_command_extensions.py) | 2 | 已验收受管文本 handler、会话覆盖、目录/执行、撤回与排空。Sunday 裁剪输入空白；附件、完整行解析、稳定定义 ID、变更通知及 DSH 日志需适配。界面当前仅查询全局目录。 |
| `ctx.sessionProjections` | gap | 补齐 sessionProjections 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.sessionProjectionCache` | gap | 补齐 sessionProjectionCache 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.skills` | candidate | 清单 skills 与 SkillRegistry；[core/src/lamtools_core/plugin_system/capabilities.py](../core/src/lamtools_core/plugin_system/capabilities.py) | 2 | 可迁移静态技能目录；动态 provider 与加载行为需适配。 |
| `ctx.agents` | candidate | PluginContext 的 sub_agent_runner / run_profile；[core/src/lamtools_core/app/default_agent.py](../core/src/lamtools_core/app/default_agent.py) | 2 | 需统一 create/resume/followup/steer/cancel/dispose；保留 Sunday 现有调度权威。 |
| `ctx.agentDefaultModel` | candidate | model_catalog.default / 模型配置；[core/src/lamtools_core/plugin_system/model_catalog.py](../core/src/lamtools_core/plugin_system/model_catalog.py) | 2 | 需明确会话选择与全局默认的写入边界。 |
| `ctx.agentLoop` | candidate | Sunday 主代理循环；[core/src/lamtools_core/app/default_agent.py](../core/src/lamtools_core/app/default_agent.py) | 2 | 不是可直接替换的 Cordis loop；扩展点先映射到现有循环。 |
| `ctx.schedule` | candidate | workflow 调度器；[core/src/lamtools_core/plugins/bundled/workflow/backend/runner_scheduler.py](../core/src/lamtools_core/plugins/bundled/workflow/backend/runner_scheduler.py) | 2 | 插件调度不等价于全局持久定时消息服务，需提升宿主契约。 |
| `ctx.goals` | candidate | 目标状态与延续驱动；[core/src/lamtools_core/runtime/goal.py](../core/src/lamtools_core/runtime/goal.py) | 2 | 需定义持久目标、轮次驱动与停止的公开契约。 |
| `ctx.ssh` | gap | 补齐 ssh 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.subprocess` | gap | 补齐 subprocess 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.shell` | gap | 补齐 shell 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.shellEnv` | gap | 补齐 shellEnv 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.terminals` | gap | 补齐 terminals 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.sandbox` | gap | 补齐 sandbox 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.sandboxPolicy` | gap | 补齐 sandboxPolicy 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.approval` | candidate | permission_service / approval.respond；[core/src/lamtools_core/app/default_agent.py](../core/src/lamtools_core/app/default_agent.py) | 2 | 保留原审批链；需转换一次性请求、取消和回答者生命周期。 |
| `ctx.permissionPresets` | candidate | 权限操作和预设；[core/src/lamtools_core/app/default_agent.py](../core/src/lamtools_core/app/default_agent.py) | 2 | 需模型工具/用户终端分别定义授权，不自动提升权限。 |
| `ctx.ptcRuntime` | gap | 补齐 ptcRuntime 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.fs` | gap | 补齐 fs 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.compaction` | candidate | agent preset compaction 服务；[core/src/lamtools_core/context_compaction/controller.py](../core/src/lamtools_core/context_compaction/controller.py) | 2 | 已有 compact_now 路径；需统一压力测量、手动调用和失败恢复。 |
| `ctx.subagents` | candidate | sub_agent_runner / sub_agent_runner_factory；[core/src/lamtools_core/app/default_agent.py](../core/src/lamtools_core/app/default_agent.py) | 2 | 需对齐 continuation、fork、控制句柄与所有权。 |
| `ctx.speechToText` | gap | 补齐 speechToText 的 Sunday 公开接口或提供方注册 | 4 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.agentTeams` | gap | 补齐 agentTeams 的 Sunday 公开接口或提供方注册 | 4 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.claudeCodeMods` | gap | 补齐 claudeCodeMods 的 Sunday 公开接口或提供方注册 | 4 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.inspector` | gap | 补齐 inspector 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.jobs` | gap | 补齐 jobs 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.web` | gap | 补齐 web 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.spillStore` | gap | 补齐 spillStore 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.directoryPicker` | gap | 补齐 directoryPicker 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.webServer` | candidate | 插件 HTTP 路由；[core/src/lamtools_core/plugin_system/plugin_http.py](../core/src/lamtools_core/plugin_system/plugin_http.py) | 3 | 已有具名 operation 路由；缺通用 upgrade 和 index 注入等价契约。 |
| `ctx.webApp` | gap | 补齐 webApp 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.clientModules` | candidate | Sunday 插件 UI 注册；[core/ui/src/plugins/registry.ts](../core/ui/src/plugins/registry.ts) | 3 | Vue 与 React/Cordis 模块图不同；保留既有 UI 生命周期。 |
| `ctx.workflowEngine` | candidate | workflow 插件后端；[core/src/lamtools_core/plugins/bundled/workflow/backend/operations.py](../core/src/lamtools_core/plugins/bundled/workflow/backend/operations.py) | 4 | 需公开脚本/子任务/取消协议；不可假设 PTC 源码可直接运行。 |
| `ctx.webhookRuntime` | candidate | 插件 HTTP routes → operation；[core/src/lamtools_core/plugin_system/plugin_http.py](../core/src/lamtools_core/plugin_system/plugin_http.py) | 4 | 需认证交付、规则注册和会话创建映射。 |
| `ctx.lsp` | gap | 补齐 lsp 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.dynamicCordisRunner` | gap | 补齐 dynamicCordisRunner 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.cordisInspect` | gap | 补齐 cordisInspect 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.liveshareShares` | gap | 补齐 liveshareShares 的 Sunday 公开接口或提供方注册 | 4 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |

## 已验收的 Sunday 基础契约

- `commands` v1（verified-python）：[接口与限制](../agent_docs/plugin_command_extensions.md)。
  `context.commands.register`、`command.catalog`、`command.execute`、`CommandInvocation`、`CommandResult`。
- `prompts` v1（verified-python）：[接口与限制](../agent_docs/plugin_prompt_extensions.md)。
  `context.prompts.section`、`context.prompts.variable`、`context.prompts.on_assemble`、`PromptContext`、`PromptAssembly`、`PromptSection`。
- `tools` v1（verified-python）：[接口与限制](../agent_docs/plugin_tool_extensions.md)。
  `context.tools.register`、`context.tools.restrict`、`context.tools.guard`、`context.tools.on`、`ToolDecision`、`ToolPatch`。
- `sessions` v1（verified-python）：[接口与限制](../agent_docs/plugin_session_control.md)。
  `SESSIONS`、`sessions.create`、`sessions.state`、`sessions.prompt`、`sessions.update_queue`、`sessions.cancel`、`sessions.events`、`sessions.follow`、`sessions.wait`。
- `ownedServices` v1（verified-python）：[接口与限制](../agent_docs/plugin_owned_services.md)。
  `ServiceKey`、`ServiceRef.call`、`PluginContext.register_service`、`PluginContext.bind_service`、`PluginContext.effect`、`PluginContext.on_dispose`。

## 事件、Remote 和 UI 扩展点

核心钩子、四个已核对 Remote 命名空间和常用 UI 位置。此子表不是上游全部方法/事件/插槽的穷尽清单；阶段2/3按包继续细化，107项服务目录是完整基线。

| 类型 | 入口 | 已核对方法 | 阶段 | 行为边界 |
| --- | --- | --- | --- | --- |
| event | [`agent/created`](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/docs/cookbook/extension-cookbook.zh.md) | — | 2 | 逐项适配通知/串行/waterfall 类型、决策、next 委托和卸载；不能只改事件名。 |
| event | [`agent/pre-step`](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/docs/cookbook/extension-cookbook.zh.md) | — | 2 | 逐项适配通知/串行/waterfall 类型、决策、next 委托和卸载；不能只改事件名。 |
| event | [`agent/request`](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/docs/cookbook/extension-cookbook.zh.md) | — | 2 | 逐项适配通知/串行/waterfall 类型、决策、next 委托和卸载；不能只改事件名。 |
| event | [`agent/request-error`](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/docs/cookbook/extension-cookbook.zh.md) | — | 2 | 逐项适配通知/串行/waterfall 类型、决策、next 委托和卸载；不能只改事件名。 |
| event | [`agent/assistant-stream`](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/docs/cookbook/extension-cookbook.zh.md) | — | 2 | 瞬态输出与持久 settlement 分开，并定义取消与断流。 |
| event | [`agent/turn-stopping`](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/docs/cookbook/extension-cookbook.zh.md) | — | 2 | 逐项适配通知/串行/waterfall 类型、决策、next 委托和卸载；不能只改事件名。 |
| event | [`tools/pre-execute`](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/docs/cookbook/extension-cookbook.zh.md) | — | 2 | 逐项适配通知/串行/waterfall 类型、决策、next 委托和卸载；不能只改事件名。 |
| event | [`tools/execute`](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/docs/cookbook/extension-cookbook.zh.md) | — | 2 | 逐项适配通知/串行/waterfall 类型、决策、next 委托和卸载；不能只改事件名。 |
| event | [`tools/post-execute`](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/docs/cookbook/extension-cookbook.zh.md) | — | 2 | 逐项适配通知/串行/waterfall 类型、决策、next 委托和卸载；不能只改事件名。 |
| event | [`tools/result`](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/docs/cookbook/extension-cookbook.zh.md) | — | 2 | 逐项适配通知/串行/waterfall 类型、决策、next 委托和卸载；不能只改事件名。 |
| event | [`session/event`](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/docs/cookbook/extension-cookbook.zh.md) | — | 2 | 需映射持久事实，不以实时 UI 通知代替。 |
| event | [`system-prompt/assemble`](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/docs/cookbook/extension-cookbook.zh.md) | — | 2 | context.prompts.on_assemble 已验证同步受管变换与失败回退；参数、动态上下文、完整替换与 DSH 严格失败语义仍需适配。 |
| remote | [`session`](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/session-controller/src/index.ts) | `list`, `search`, `create`, `rename`, `fork`, `prompt`, `updateQueue`, `cancel`, `selectModel`, `modelCatalog`, `initializeDefaultModel`, `attachment`, `events`, `page`, `state`, `wait`, `observeEvent`, `observeProjections`, `observeState`, `follow`, `projections`, `control`, `canOpenWorkspacePath`, `openWorkspacePath`, `workspacePathApplications` | 3 | 按固定上游请求/响应适配；含身份解析、权限、错误、取消、冷读取与流重连。 |
| remote | [`workspace`](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/workspace-controller/src/index.ts) | `create`, `initializeDefault`, `rename`, `delete`, `insertBefore`, `insertSessionBefore`, `archiveSession`, `unarchiveSession`, `pinSession`, `unpinSession`, `follow` | 3 | 按固定上游请求/响应适配；含身份解析、权限、错误、取消、冷读取与流重连。 |
| remote | [`workspaceFiles`](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/workspace-files/src/index.ts) | `stat`, `read`, `readBytes`, `list`, `changes` | 3 | 按固定上游请求/响应适配；含身份解析、权限、错误、取消、冷读取与流重连。 |
| remote | [`terminal`](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/terminal-controller/src/index.ts) | `environment`, `shells`, `list`, `create`, `retain`, `attach`, `rename`, `close` | 3 | 用户 PTY 与模型 shell 权限分别建模；双向流、取消、停用均需验收。 |
| slot | [`conversation.session.header.actions`](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/docs/subsystems/slots.zh.md) | — | 3 | React/Cordis 到 Vue 的语义迁移；核对单席位/列表/keyed/chain、会话绑定、依赖就绪与卸载。 |
| slot | [`conversation.session.header.utilities`](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/docs/subsystems/slots.zh.md) | — | 3 | React/Cordis 到 Vue 的语义迁移；核对单席位/列表/keyed/chain、会话绑定、依赖就绪与卸载。 |
| slot | [`conversation.input.left`](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/docs/subsystems/slots.zh.md) | — | 3 | React/Cordis 到 Vue 的语义迁移；核对单席位/列表/keyed/chain、会话绑定、依赖就绪与卸载。 |
| slot | [`conversation.input.right`](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/docs/subsystems/slots.zh.md) | — | 3 | React/Cordis 到 Vue 的语义迁移；核对单席位/列表/keyed/chain、会话绑定、依赖就绪与卸载。 |
| slot | [`conversation.input.overlay`](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/docs/subsystems/slots.zh.md) | — | 3 | React/Cordis 到 Vue 的语义迁移；核对单席位/列表/keyed/chain、会话绑定、依赖就绪与卸载。 |
| slot | [`conversation.composer.dock`](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/docs/subsystems/slots.zh.md) | — | 3 | React/Cordis 到 Vue 的语义迁移；核对单席位/列表/keyed/chain、会话绑定、依赖就绪与卸载。 |
| slot | [`conversation.input.attachments`](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/docs/subsystems/slots.zh.md) | — | 3 | React/Cordis 到 Vue 的语义迁移；核对单席位/列表/keyed/chain、会话绑定、依赖就绪与卸载。 |
| slot | [`conversation.input.model`](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/docs/subsystems/slots.zh.md) | — | 3 | React/Cordis 到 Vue 的语义迁移；核对单席位/列表/keyed/chain、会话绑定、依赖就绪与卸载。 |
| slot | [`conversation.input.permission`](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/docs/subsystems/slots.zh.md) | — | 3 | React/Cordis 到 Vue 的语义迁移；核对单席位/列表/keyed/chain、会话绑定、依赖就绪与卸载。 |
| slot | [`conversation.chat.node`](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/docs/subsystems/slots.zh.md) | — | 3 | React/Cordis 到 Vue 的语义迁移；核对单席位/列表/keyed/chain、会话绑定、依赖就绪与卸载。 |
| slot | [`tool.call.toolview`](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/docs/subsystems/slots.zh.md) | — | 3 | React/Cordis 到 Vue 的语义迁移；核对单席位/列表/keyed/chain、会话绑定、依赖就绪与卸载。 |
| slot | [`conversation.chat.reasoning.body`](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/docs/subsystems/slots.zh.md) | — | 3 | React/Cordis 到 Vue 的语义迁移；核对单席位/列表/keyed/chain、会话绑定、依赖就绪与卸载。 |
| slot | [`conversation.chat.assistant-actions`](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/docs/subsystems/slots.zh.md) | — | 3 | React/Cordis 到 Vue 的语义迁移；核对单席位/列表/keyed/chain、会话绑定、依赖就绪与卸载。 |
| slot | [`sidebar.right.pane.tab`](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/docs/subsystems/slots.zh.md) | — | 3 | React/Cordis 到 Vue 的语义迁移；核对单席位/列表/keyed/chain、会话绑定、依赖就绪与卸载。 |
| slot | [`sidebar.right.pane.tab.title`](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/docs/subsystems/slots.zh.md) | — | 3 | React/Cordis 到 Vue 的语义迁移；核对单席位/列表/keyed/chain、会话绑定、依赖就绪与卸载。 |
| slot | [`sidebar.right.tab.document`](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/docs/subsystems/slots.zh.md) | — | 3 | React/Cordis 到 Vue 的语义迁移；核对单席位/列表/keyed/chain、会话绑定、依赖就绪与卸载。 |
| slot | [`sidebar.right.tab.menu.item`](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/docs/subsystems/slots.zh.md) | — | 3 | React/Cordis 到 Vue 的语义迁移；核对单席位/列表/keyed/chain、会话绑定、依赖就绪与卸载。 |
