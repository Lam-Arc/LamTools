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
| `ctx.hmr` | candidate | context.plugins.reload / plugin.system.reload；[core/src/lamtools_core/plugin_system/management.py](../core/src/lamtools_core/plugin_system/management.py), [core/tests/test_plugin_management_access.py](../core/tests/test_plugin_management_access.py) | 2 | 显式受管重载近似；不提供自动文件监控、任意模块图热替换或 UI HMR。 |
| `ctx.pluginRegistryProbe` | gap | 补齐 pluginRegistryProbe 的 Sunday 公开接口或提供方注册 | 3 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.pluginManager` | candidate | context.plugins + plugin.system.*；[core/src/lamtools_core/plugin_system/management.py](../core/src/lamtools_core/plugin_system/management.py), [core/tests/test_plugin_management_access.py](../core/tests/test_plugin_management_access.py) | 2 | 真实列表/启停/显式重载仍走原目录和 supervisor；自停拒绝。不复制整个 Cordis 插件管理 API。 |
| `ctx.pluginMarket` | candidate | plugin.market.*；[core/src/lamtools_core/plugin_system/market.py](../core/src/lamtools_core/plugin_system/market.py) | 3 | 需适配源、搜索、安装状态与取消。 |
| `ctx.profileContext` | candidate | context.profiles.list/resolve；[core/src/lamtools_core/plugin_system/profiles.py](../core/src/lamtools_core/plugin_system/profiles.py), [core/tests/test_plugin_management_access.py](../core/tests/test_plugin_management_access.py) | 2 | 原运行档声明与解析只读查询；非 Cordis 当前组合 Context、来源树或安装目录隔离。 |
| `ctx.connection` | candidate | LamToolsTransport；[core/ui/src/transport/index.ts](../core/ui/src/transport/index.ts) | 3 | 现有传输不同于 Typert；需协议适配，不转发未知方法。 |
| `ctx.forge` | gap | 补齐 forge 的 Sunday 公开接口或提供方注册 | 4 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.forgeSession` | gap | 补齐 forgeSession 的 Sunday 公开接口或提供方注册 | 4 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.forgePanel` | gap | 补齐 forgePanel 的 Sunday 公开接口或提供方注册 | 4 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.worktrees` | gap | 补齐 worktrees 的 Sunday 公开接口或提供方注册 | 4 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.workingDirectory` | candidate | context.working_directory + context.for_session + main file/Git/command request snapshot；[core/src/lamtools_core/plugin_system/filesystem_access.py](../core/src/lamtools_core/plugin_system/filesystem_access.py), [core/tests/test_plugin_filesystem_access.py](../core/tests/test_plugin_filesystem_access.py), [core/tests/test_plugin_working_directory.py](../core/tests/test_plugin_working_directory.py), [core/tests/test_main_execution_directory.py](../core/tests/test_main_execution_directory.py), [core/tests/test_git_execution_directory.py](../core/tests/test_git_execution_directory.py) | 2 | 原会话目录/CAS，保留项目配置身份；主代理文件/Git/命令送审前固定目标，目录变化追加尾部通知，失效时恢复原项目。MCP等其他服务保留项目身份，子代理、即时通知及DSH事件协议仍有差异。 |
| `ctx.mcpResources` | candidate | context.mcp_resources；[core/src/lamtools_core/plugin_system/mcp_resources.py](../core/src/lamtools_core/plugin_system/mcp_resources.py) | 2 | 原配置与真实MCP传输，资源/模板列表、读资源与连接回收；无自动模型工具/DSH Agent注册协议。 |
| `ctx.browserUse` | candidate | context.browser_use；[core/src/lamtools_core/plugin_system/capability_seams.py](../core/src/lamtools_core/plugin_system/capability_seams.py) | 2 | 上游服务本身为独占名称槽；对应受管槽及异步清理，实际浏览器工具仍须提供方。 |
| `ctx.computerUse` | candidate | context.computer_use；[core/src/lamtools_core/plugin_system/capability_seams.py](../core/src/lamtools_core/plugin_system/capability_seams.py) | 2 | 上游独占名称槽近似，实际桌面操作及系统许可不包含在此注册服务。 |
| `ctx.cuaAccess` | gap | 补齐 cuaAccess 的 Sunday 公开接口或提供方注册 | 4 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.officeToPdf` | gap | 补齐 officeToPdf 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.attachments` | candidate | context.attachments；[core/src/lamtools_core/app/plugin_session_data.py](../core/src/lamtools_core/app/plugin_session_data.py) | 2 | 会话及项目隔离的原存储附件创建/引用/列表/预览；无DSH图片准入、opaque refs或文件流。 |
| `ctx.fileUploads` | gap | 补齐 fileUploads 的 Sunday 公开接口或提供方注册 | 3 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.llm` | candidate | context.llm.complete/stream + context.models；[core/src/lamtools_core/plugin_system/model_catalog.py](../core/src/lamtools_core/plugin_system/model_catalog.py), [core/src/lamtools_core/plugin_system/model_access.py](../core/src/lamtools_core/plugin_system/model_access.py), [core/tests/test_plugin_model_access.py](../core/tests/test_plugin_model_access.py), [core/tests/test_plugin_llm_access.py](../core/tests/test_plugin_llm_access.py) | 2 | 实际调用、结构化异步流和固定项目/模型路由；原生协议及有限大小/截止时间，不含 DSH adapter/prepareCall 全协议。 |
| `ctx.deepseekLlmApiExtensions` | gap | 补齐 deepseekLlmApiExtensions 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.tokenMeter` | candidate | context.llm.estimate + provider usage；[core/tests/test_plugin_llm_access.py](../core/tests/test_plugin_llm_access.py) | 2 | 只有本地启发式估算与实际响应 usage；没有 DSH replay-aware surface/request pricing 投影。 |
| `ctx.toolResultPruner` | candidate | context.tool_result_pruner；[core/src/lamtools_core/plugin_system/content_access.py](../core/src/lamtools_core/plugin_system/content_access.py) | 2 | Unicode文本计数及纯内容头尾裁剪，保留富内容；无Session shadow事件/历史重放。 |
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
| `ctx.sessionPersistence` | candidate | SESSIONS.events + context.checkpoints；[core/src/lamtools_core/app/core_session_store.py](../core/src/lamtools_core/app/core_session_store.py), [core/tests/test_plugin_checkpoint_access.py](../core/tests/test_plugin_checkpoint_access.py) | 2 | 原持久事件读取及检查点创建/对话恢复/回退/分叉；真实SQLite历史，文件不回退。没有DSH单写者日志句柄、append/flush屏障或原样崩溃重放。 |
| `ctx.configEditor` | candidate | context.config 快照/条件保存 + config_store；[core/src/lamtools_core/plugin_system/config_store.py](../core/src/lamtools_core/plugin_system/config_store.py), [core/src/lamtools_core/plugin_system/config_access.py](../core/src/lamtools_core/plugin_system/config_access.py), [core/tests/test_plugin_config_access.py](../core/tests/test_plugin_config_access.py) | 2 | 已验收当前插件快照、内容修订条件保存和共用管理入口；保存不等于应用，不提供 DSH profile overlay、重载失败回滚或注释保留。 |
| `ctx.settings` | candidate | context.config 基础校验 + 原 config schema / config_store；[core/src/lamtools_core/plugin_system/config_store.py](../core/src/lamtools_core/plugin_system/config_store.py), [core/src/lamtools_core/plugin_system/config_access.py](../core/src/lamtools_core/plugin_system/config_access.py), [core/tests/test_plugin_config_access.py](../core/tests/test_plugin_config_access.py) | 2 | 基础文件读写已验收；完整 Config 校验、volatile 引用、动态 namespace、secret 字段投影、继承重置与 UI 修订号接线仍待实施。 |
| `ctx.subagentModelSelection` | candidate | context.models.select 的只读查询 + 子代理与模型配置；[core/src/lamtools_core/app/default_agent.py](../core/src/lamtools_core/app/default_agent.py) | 2 | 只读目录和场景选择可供调用方使用；子会话获准路由、发现政策、默认值覆盖和持久化尚未提供 DSH 等价契约，目录成员不等于授权。 |
| `ctx.credentials` | candidate | context.credentials 引用子集 + 插件私有 secrets；[core/src/lamtools_core/plugin_system/secrets.py](../core/src/lamtools_core/plugin_system/secrets.py), [core/src/lamtools_core/plugin_system/credentials.py](../core/src/lamtools_core/plugin_system/credentials.py), [core/tests/test_plugin_credentials.py](../core/tests/test_plugin_credentials.py) | 2 | 已验收受管 resolve/describe/set/unset 与当前 owner 隔离，磁盘按操作重读和跨进程锁防止丢写。无全局环境回退、授权记录、modifyRecord 或变更事件。 |
| `ctx.deepseekAccount` | gap | 补齐 deepseekAccount 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.authorization` | gap | 补齐 authorization 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.productAnalytics` | gap | 补齐 productAnalytics 的 Sunday 公开接口或提供方注册 | 3 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.otel` | gap | 补齐 otel 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.productTelemetry` | gap | 补齐 productTelemetry 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.sessionTelemetry` | gap | 补齐 sessionTelemetry 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.storage` | candidate | context.storage 的插件 JSON KV + 原独立数据目录；[core/src/lamtools_core/plugin_system/plugin_data.py](../core/src/lamtools_core/plugin_system/plugin_data.py), [core/src/lamtools_core/plugin_system/storage_access.py](../core/src/lamtools_core/plugin_system/storage_access.py), [core/tests/test_plugin_storage_access.py](../core/tests/test_plugin_storage_access.py) | 2 | 已验收插件所有的同步 SQLite JSON KV、精确单元版本、条件写与失败隔离；不提供 DSH 后端/form 注册或通用领域设施。 |
| `ctx.storageDomain` | candidate | context.storage 插件隔离 JSON KV（需人工改造领域）；[core/src/lamtools_core/plugin_system/plugin_data.py](../core/src/lamtools_core/plugin_system/plugin_data.py) | 2 | 基础 KV 可作人工重构目标，但 schema、tables/global、compatibleVersions、内存同步域、后端路由、异步写链与 domain/changed 均未实现 DSH 等价契约。 |
| `ctx.messageFeedback` | candidate | context.message_feedback；[core/src/lamtools_core/app/plugin_feedback.py](../core/src/lamtools_core/app/plugin_feedback.py) | 2 | 真实插件私有消息反馈CAS/版本墓碑，复用会话持久化；非DSH Session反馈事件。 |
| `ctx.sessionFeedback` | candidate | context.session_feedback；[core/src/lamtools_core/app/plugin_feedback.py](../core/src/lamtools_core/app/plugin_feedback.py) | 2 | 真实插件私有会话反馈与请求去重；原会话存储，允许冷会话，无隐式上传。 |
| `ctx.workspaceRegistry` | candidate | 项目与会话操作；[core/src/lamtools_core/app/default_agent.py](../core/src/lamtools_core/app/default_agent.py) | 3 | 需对齐工作区身份、排序、归档和会话归属。 |
| `ctx.sessionQuery` | candidate | context.session_query.query；[core/src/lamtools_core/app/core_session_store.py](../core/src/lamtools_core/app/core_session_store.py), [core/tests/test_plugin_session_query.py](../core/tests/test_plugin_session_query.py) | 2 | 有限只读扫描、可见性与不透明分页；不导出元数据，不是 DSH 全量查询投影协议。 |
| `ctx.fileReferences` | candidate | context.file_references；[core/src/lamtools_core/plugin_system/content_access.py](../core/src/lamtools_core/plugin_system/content_access.py) | 2 | 本地有限引用候选与唯一成果路径恢复；不包含DSH Agent或跨平台身份。 |
| `ctx.sessionReferenceResolver` | gap | 补齐 sessionReferenceResolver 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.sessionTitle` | candidate | context.session_title；[core/src/lamtools_core/app/plugin_session_data.py](../core/src/lamtools_core/app/plugin_session_data.py) | 2 | 原持久标题读写/CAS及默认标题保护；不替换原自动生成器。 |
| `ctx.systemPrompt` | candidate | context.prompts.section/variable/on_assemble + system_prompt_waterfall；[core/src/lamtools_core/plugin_system/prompt_waterfall.py](../core/src/lamtools_core/plugin_system/prompt_waterfall.py), [core/src/lamtools_core/plugin_system/prompt_extensions.py](../core/src/lamtools_core/plugin_system/prompt_extensions.py), [core/tests/test_plugin_prompt_extensions.py](../core/tests/test_plugin_prompt_extensions.py) | 2 | 已验收受管同步 section/variable/assemble、插件排序及会话/agent_id 覆盖。追加于内置段之后；完整替换、动态上下文、集中顺序表、change 事件、工具 schema 及 DSH 失败语义仍需适配。 |
| `ctx.tools` | candidate | context.tools.register/restrict/guard/on + 清单 tools.jsonc；[core/src/lamtools_core/plugin_system/capabilities.py](../core/src/lamtools_core/plugin_system/capabilities.py), [core/src/lamtools_core/plugin_system/tool_extensions.py](../core/src/lamtools_core/plugin_system/tool_extensions.py), [core/tests/test_plugin_tool_extensions.py](../core/tests/test_plugin_tool_extensions.py) | 2 | 动态注册、收窄、守卫与 pre/post/result 基础子集已验收；仅扁平 schema，原数值审批。execute 包装、参数改写、动态 ask 与 DSH 决策语义仍需适配。 |
| `ctx.userQuestions` | candidate | context.questions.ask/answer；[core/tests/test_plugin_question_access.py](../core/tests/test_plugin_question_access.py) | 2 | 独立程序化表单问答、单终端受管回答者、校验及取消/撤回/超时；无Agent身份、waterfall、计时继续、持久投影或前端接线，不充当审批。 |
| `ctx.planMode` | candidate | context.plan_mode；[core/src/lamtools_core/plugin_system/content_access.py](../core/src/lamtools_core/plugin_system/content_access.py) | 2 | 当前启动代/视图只读工具白名单，原审批继续生效；不持久化、不代替评审，不撤销已执行副作用。 |
| `ctx.agentPresets` | candidate | agent_presets；[core/src/lamtools_core/plugin_system/agent_presets.py](../core/src/lamtools_core/plugin_system/agent_presets.py) | 2 | 已有组合和服务注册；需逐会话版本与撤回语义适配。 |
| `ctx.commands` | candidate | context.commands.register + command.catalog/execute + 声明式 commands；[core/src/lamtools_core/plugin_system/commands.py](../core/src/lamtools_core/plugin_system/commands.py), [core/src/lamtools_core/plugin_system/command_extensions.py](../core/src/lamtools_core/plugin_system/command_extensions.py), [core/tests/test_plugin_command_extensions.py](../core/tests/test_plugin_command_extensions.py) | 2 | 已验收受管文本 handler、会话覆盖、目录/执行、撤回与排空。Sunday 裁剪输入空白；附件、完整行解析、稳定定义 ID、变更通知及 DSH 日志需适配。界面当前仅查询全局目录。 |
| `ctx.sessionProjections` | candidate | context.session_projections；[core/src/lamtools_core/app/plugin_session_data.py](../core/src/lamtools_core/app/plugin_session_data.py) | 2 | 原数据库最新摘要与有限事件页，无扩展投影定义/DSH重放。 |
| `ctx.sessionProjectionCache` | gap | 补齐 sessionProjectionCache 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.skills` | candidate | context.skills.register + 清单 skills 与 SkillRegistry；[core/src/lamtools_core/plugin_system/capabilities.py](../core/src/lamtools_core/plugin_system/capabilities.py), [core/src/lamtools_core/plugin_system/skill_extensions.py](../core/src/lamtools_core/plugin_system/skill_extensions.py), [core/tests/test_plugin_skill_extensions.py](../core/tests/test_plugin_skill_extensions.py) | 2 | 静态目录迁移与受管全局内存技能已验收，模型/用户调用策略分别检查。磁盘优先；动态目录、远程 provider、scope、snapshot/invalidate 与 change 事件未覆盖。 |
| `ctx.agents` | candidate | PluginContext 的 sub_agent_runner / run_profile；[core/src/lamtools_core/app/default_agent.py](../core/src/lamtools_core/app/default_agent.py) | 2 | 需统一 create/resume/followup/steer/cancel/dispose；保留 Sunday 现有调度权威。 |
| `ctx.agentDefaultModel` | candidate | context.models.select(scene) / 场景模型记忆；[core/src/lamtools_core/plugin_system/model_catalog.py](../core/src/lamtools_core/plugin_system/model_catalog.py), [core/src/lamtools_core/plugin_system/model_access.py](../core/src/lamtools_core/plugin_system/model_access.py), [core/tests/test_plugin_model_access.py](../core/tests/test_plugin_model_access.py) | 2 | Sunday 按 chat/study/background 场景只读解析，已验收同场景替换和显式错误；不提供 DSH 单一进程默认值、saveSelection 或会话最终选模。 |
| `ctx.agentLoop` | candidate | Sunday 主代理循环；[core/src/lamtools_core/app/default_agent.py](../core/src/lamtools_core/app/default_agent.py) | 2 | 不是可直接替换的 Cordis loop；扩展点先映射到现有循环。 |
| `ctx.schedule` | candidate | context.schedule + original Arrange Runner；[core/src/lamtools_core/plugins/bundled/workflow/backend/runner_scheduler.py](../core/src/lamtools_core/plugins/bundled/workflow/backend/runner_scheduler.py), [core/tests/test_plugin_durable_access.py](../core/tests/test_plugin_durable_access.py) | 2 | 原持久任务触发/执行/暂停/取消，固定项目与插件 ID；提醒格式、cron、投递历史与 DSH 不同。 |
| `ctx.goals` | candidate | context.goals + original GoalManager；[core/src/lamtools_core/runtime/goal.py](../core/src/lamtools_core/runtime/goal.py), [core/tests/test_plugin_durable_access.py](../core/tests/test_plugin_durable_access.py) | 2 | 持久多目标、固定插件/项目身份及重复创建回执；非 DSH 单会话目标投影、轮数、CAS 引用或续跑激活。 |
| `ctx.ssh` | gap | 补齐 ssh 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.subprocess` | candidate | context.processes.spawn/run + lookup/environment；[core/src/lamtools_core/plugin_system/process_access.py](../core/src/lamtools_core/plugin_system/process_access.py), [core/tests/test_plugin_process_access.py](../core/tests/test_plugin_process_access.py), [core/tests/test_plugin_owned_processes.py](../core/tests/test_plugin_owned_processes.py) | 2 | Windows Job 原生进程、有限输出与回收；启动到分配存在竞争窗口，无 stdin/raw stdio/control/PTY/远程协议。 |
| `ctx.shell` | candidate | context.shell.resolve/execute + owned native processes；[core/tests/test_plugin_shell_access.py](../core/tests/test_plugin_shell_access.py) | 2 | PowerShell近似，显式期限、有限字节尾及原Job回收；无stdin、onExpiry:none、消费游标、spill、PTY、沙箱或远程后端。 |
| `ctx.shellEnv` | candidate | context.shell_env.register/list/collect；[core/tests/test_plugin_shell_access.py](../core/tests/test_plugin_shell_access.py) | 2 | 受管SUNDAY_*声明、每次收集、冲突/撤回与5秒期限；不伪造DSH身份或profile。session_id仅标签，无模型工具自动接线。 |
| `ctx.terminals` | gap | 补齐 terminals 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.sandbox` | gap | 补齐 sandbox 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.sandboxPolicy` | gap | 补齐 sandboxPolicy 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.approval` | candidate | context.approvals.request/answer + native tool approval；[core/src/lamtools_core/app/default_agent.py](../core/src/lamtools_core/app/default_agent.py), [core/tests/test_plugin_approval_access.py](../core/tests/test_plugin_approval_access.py) | 2 | 已有活动回合请求、受管单回答者与持久审计；默认缺失不放行。没有前端卡片、waterfall、持久 setPolicy 或 DSH turn-enclosed 编码。 |
| `ctx.permissionPresets` | candidate | context.permissions.catalog/read / 既有权限操作；[core/src/lamtools_core/app/plugin_permissions.py](../core/src/lamtools_core/app/plugin_permissions.py), [core/tests/test_plugin_permission_access.py](../core/tests/test_plugin_permission_access.py) | 2 | 已验收固定 Sunday 预设目录和会话偏好只读查询；不返回授权，不改策略。无 DSH sandbox 组合、custom、Auto review 或动态目录。 |
| `ctx.ptcRuntime` | gap | 补齐 ptcRuntime 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.fs` | candidate | context.filesystem；[core/src/lamtools_core/plugin_system/filesystem_access.py](../core/src/lamtools_core/plugin_system/filesystem_access.py), [core/tests/test_plugin_filesystem_access.py](../core/tests/test_plugin_filesystem_access.py), [core/tests/test_plugin_filesystem_ranges.py](../core/tests/test_plugin_filesystem_ranges.py), [core/tests/test_plugin_filesystem_stream.py](../core/tests/test_plugin_filesystem_stream.py), [core/tests/test_plugin_filesystem_mutations.py](../core/tests/test_plugin_filesystem_mutations.py), [core/tests/test_plugin_file_watch.py](../core/tests/test_plugin_file_watch.py), [core/tests/test_plugin_file_targets.py](../core/tests/test_plugin_file_targets.py) | 2 | 读取、范围、流、最终链接及条件写入/编辑；本地路径转换与有限元数据轮询监听。1MiB 修改、内容修订与合作路径锁；无原生事件、递归监听、远程后端或完整 DSH 目标身份。 |
| `ctx.compaction` | candidate | context.compaction.compact_now / 既有 agent preset compaction；[core/src/lamtools_core/app/plugin_compaction.py](../core/src/lamtools_core/app/plugin_compaction.py), [core/tests/test_plugin_compaction_access.py](../core/tests/test_plugin_compaction_access.py) | 2 | 已验收桌面空闲会话手动压缩子集，修订冲突、取消、排他与停用租约；无自动/区间 API、持久锁或 DSH 检查点协议。 |
| `ctx.subagents` | candidate | context.subagents + original SubAgentSupervisor；[core/src/lamtools_core/app/default_agent.py](../core/src/lamtools_core/app/default_agent.py), [core/tests/test_plugin_subagent_access.py](../core/tests/test_plugin_subagent_access.py), [core/tests/test_plugin_subagent_continuation.py](../core/tests/test_plugin_subagent_continuation.py) | 2 | 原监督器/邮箱的具名持久成员create/list/get/message/close及单成员interrupt/resume；固定插件/项目和可见父会话，恢复验证非live提交状态及实际继续执行器。不覆盖共享暂停、目录捕获、DSH activation/外部提供方/完整父子协议。 |
| `ctx.speechToText` | gap | 补齐 speechToText 的 Sunday 公开接口或提供方注册 | 4 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.agentTeams` | gap | 补齐 agentTeams 的 Sunday 公开接口或提供方注册 | 4 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.claudeCodeMods` | gap | 补齐 claudeCodeMods 的 Sunday 公开接口或提供方注册 | 4 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.inspector` | gap | 补齐 inspector 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.jobs` | candidate | context.jobs.start/get/list/read/wait/kill/remove；[core/tests/test_plugin_jobs_access.py](../core/tests/test_plugin_jobs_access.py) | 2 | 插件启动代/项目内异步回调作业、有限输出/记录与实际取消join；session仅标签，无DSH控制器、消费读取、通知、持久化或会话ACL。 |
| `ctx.web` | candidate | context.web；[core/src/lamtools_core/plugin_system/content_access.py](../core/src/lamtools_core/plugin_system/content_access.py) | 2 | 原搜索提供方及HTTP抓取工具的受管SDK，保留原结果/失败；不授予模型审批。 |
| `ctx.spillStore` | candidate | context.spill_store.save_text；[core/tests/test_plugin_spill_access.py](../core/tests/test_plugin_spill_access.py) | 2 | 插件/会话标签分组的真实本地UTF-8持久文件及精确字节数；8MiB上限，无自动预览/过期/远程或读取授权。 |
| `ctx.directoryPicker` | gap | 补齐 directoryPicker 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.webServer` | candidate | 插件 HTTP 路由；[core/src/lamtools_core/plugin_system/plugin_http.py](../core/src/lamtools_core/plugin_system/plugin_http.py) | 3 | 已有具名 operation 路由；缺通用 upgrade 和 index 注入等价契约。 |
| `ctx.webApp` | gap | 补齐 webApp 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.clientModules` | candidate | Sunday 插件 UI 注册；[core/ui/src/plugins/registry.ts](../core/ui/src/plugins/registry.ts) | 3 | Vue 与 React/Cordis 模块图不同；保留既有 UI 生命周期。 |
| `ctx.workflowEngine` | candidate | workflow 插件后端；[core/src/lamtools_core/plugins/bundled/workflow/backend/operations.py](../core/src/lamtools_core/plugins/bundled/workflow/backend/operations.py) | 4 | 需公开脚本/子任务/取消协议；不可假设 PTC 源码可直接运行。 |
| `ctx.webhookRuntime` | candidate | 插件 HTTP routes → operation；[core/src/lamtools_core/plugin_system/plugin_http.py](../core/src/lamtools_core/plugin_system/plugin_http.py) | 4 | 需认证交付、规则注册和会话创建映射。 |
| `ctx.lsp` | candidate | context.lsp；[core/src/lamtools_core/plugin_system/capability_seams.py](../core/src/lamtools_core/plugin_system/capability_seams.py) | 2 | 真实受管提供方注册/扩展选择/四类规范查询；语言服务器须另行安装，不伪造结果。 |
| `ctx.dynamicCordisRunner` | gap | 补齐 dynamicCordisRunner 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.cordisInspect` | gap | 补齐 cordisInspect 的 Sunday 公开接口或提供方注册 | 2 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.liveshareShares` | gap | 补齐 liveshareShares 的 Sunday 公开接口或提供方注册 | 4 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |

## 已验收的 Sunday 基础契约

- `config` v1（verified-python）：[接口与限制](../agent_docs/plugin_config_access.md)。
  `context.config.read`、`context.config.validate`、`context.config.replace`、`ConfigSnapshot`、`ConfigValidation`、`ConfigSaveResult`、`ConfigError`。
- `credentials` v1（verified-python）：[接口与限制](../agent_docs/plugin_credentials.md)。
  `context.credentials.resolve`、`context.credentials.describe`、`context.credentials.set`、`context.credentials.unset`、`CredentialInfo`、`ResolvedCredential`、`CredentialError`。
- `storage` v1（verified-python）：[接口与限制](../agent_docs/plugin_storage_access.md)。
  `context.storage.open`、`StorageUnit.get`、`StorageUnit.put`、`StorageUnit.delete`、`StorageUnit.keys`、`StorageUnit.close`、`StoredValue`、`StorageKeyPage`、`StorageError`。
- `models` v1（verified-python）：[接口与限制](../agent_docs/plugin_model_access.md)。
  `context.models.list`、`context.models.resolve`、`context.models.select`、`ModelDescriptor`、`ModelSelection`、`ModelAccessError`。
- `skills` v1（verified-python）：[接口与限制](../agent_docs/plugin_skill_extensions.md)。
  `context.skills.register`、`skill.list`、`load_skill`、`Skill.model_invocable`、`Skill.user_invocable`。
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
- `filesystem` v5（verified-python）：[接口与限制](../agent_docs/plugin_filesystem_access.md)。
  `context.filesystem.root`、`context.filesystem.stat`、`context.filesystem.read_bytes`、`context.filesystem.read_text`、`context.filesystem.list_dir`、`FileInfo`、`DirectoryListing`、`FilesystemError`、`context.filesystem.lstat`、`context.filesystem.read_byte_range`、`context.filesystem.stream_text`、`context.filesystem.observe`、`context.filesystem.write_text`、`context.filesystem.edit_text`、`FileObservation`、`FileWriteResult`、`context.filesystem.watch`、`context.filesystem.resolve`、`context.filesystem.process_path`、`context.filesystem.file_url`、`context.filesystem.contains`、`context.filesystem.process_path_from_host_path`、`FileWatchEvent`、`FileWatchResult`。
- `compaction` v1（verified-python）：[接口与限制](../agent_docs/plugin_compaction_access.md)。
  `context.compaction.compact_now`、`CompactionResult`、`CompactionError`。
- `permissions` v1（verified-python）：[接口与限制](../agent_docs/plugin_permission_access.md)。
  `context.permissions.catalog`、`context.permissions.read`、`PermissionPresetInfo`、`PermissionCatalog`、`SessionPermissionView`、`PermissionAccessError`。
- `processLookup` v1（verified-python）：[接口与限制](../agent_docs/plugin_process_access.md)。
  `context.processes.resolve_executable`、`context.processes.environment`、`ProcessAccessError`。
- `ownedProcesses` v1（verified-python）：[接口与限制](../agent_docs/plugin_phase2_runtime.md)。
  `context.processes.spawn`、`context.processes.run`、`OwnedProcess.wait`、`OwnedProcess.terminate`、`OwnedProcess.read_output`、`ProcessOutcome`、`ProcessOutput`。
- `llmCalls` v1（verified-python）：[接口与限制](../agent_docs/plugin_phase2_runtime.md)。
  `context.llm.complete`、`context.llm.stream`、`context.llm.estimate`、`LLMAccessError`、`TokenEstimate`。
- `durableTasks` v1（verified-python）：[接口与限制](../agent_docs/plugin_phase2_runtime.md)。
  `context.goals.create/get/list/update`、`context.schedule.create/get/list/update/control`、`DurableAccessError`。
- `sessionQuery` v1（verified-python）：[接口与限制](../agent_docs/plugin_phase2_runtime.md)。
  `context.session_query.query`、`SessionSummary`、`SessionQueryPage`、`SessionQueryError`。
- `approvalRequests` v1（verified-python）：[接口与限制](../agent_docs/plugin_phase2_runtime.md)。
  `context.approvals.request`、`context.approvals.answer`、`ApprovalRequest`、`ApprovalResult`、`ApprovalAccessError`。
- `management` v1（verified-python）：[接口与限制](../agent_docs/plugin_phase2_runtime.md)。
  `context.plugins.list/enable/disable/reload`、`context.profiles.list/resolve`、`HostOperationError`。
- `shell` v1（verified-python）：[接口与限制](../agent_docs/plugin_phase2_runtime.md)。
  `context.shell.resolve`、`context.shell.execute`、`ShellExecution.result`、`ShellExecution.read_output`、`ShellExecution.kill`、`context.shell_env.register`、`context.shell_env.list`、`context.shell_env.collect`、`ShellExecutionSpec`、`ShellExecutionResult`、`ShellEnvironmentContext`、`ShellEnvironmentDeclaration`、`ShellAccessError`。
- `jobs` v1（verified-python）：[接口与限制](../agent_docs/plugin_phase2_runtime.md)。
  `context.jobs.start`、`context.jobs.get`、`context.jobs.list`、`context.jobs.read`、`context.jobs.wait`、`context.jobs.kill`、`context.jobs.remove`、`PluginJob.emit`、`PluginJob.progress`、`JobView`、`JobOutput`、`JobAccessError`。
- `spill` v1（verified-python）：[接口与限制](../agent_docs/plugin_phase2_runtime.md)。
  `context.spill_store.save_text`、`SpillReference`、`SpillAccessError`。
- `questions` v1（verified-python）：[接口与限制](../agent_docs/plugin_phase2_runtime.md)。
  `context.questions.ask`、`context.questions.answer`、`UserQuestion`、`QuestionRequest`、`UserAnswer`、`QuestionResult`、`QuestionAccessError`。
- `workingDirectory` v3（verified-python）：[接口与限制](../agent_docs/plugin_session_recovery.md)。
  `context.working_directory.get`、`context.working_directory.set`、`context.working_directory.ensure`、`context.for_session`、`PluginContext.execution_root`、`WorkingDirectoryState`、`WorkingDirectoryError`、`run_command.cwd`、`CoreToolbox.refresh_execution_directory`、`git_status.cwd`、`git_diff.cwd`。
- `checkpoints` v1（verified-python）：[接口与限制](../agent_docs/plugin_session_recovery.md)。
  `context.checkpoints.list`、`context.checkpoints.create`、`context.checkpoints.restore`、`context.checkpoints.rollback`、`context.checkpoints.fork`、`CheckpointAccessError`。
- `subagents` v2（verified-python）：[接口与限制](../agent_docs/plugin_subagent_access.md)。
  `context.subagents.create`、`context.subagents.list`、`context.subagents.get`、`context.subagents.message`、`context.subagents.close`、`SubagentAccessError`、`context.subagents.interrupt`、`context.subagents.resume`、`sub_agent.interrupt_member`、`sub_agent.resume_member`。
- `sessionData` v1（verified-python）：[接口与限制](../agent_docs/plugin_phase2_public_ports.md)。
  `context.attachments.create`、`context.attachments.reference`、`context.attachments.list`、`context.attachments.get`、`context.attachments.preview`、`context.session_title.get`、`context.session_title.set`、`context.session_projections.get`、`context.session_projections.events`。
- `feedback` v1（verified-python）：[接口与限制](../agent_docs/plugin_phase2_public_ports.md)。
  `context.message_feedback.list`、`context.message_feedback.put`、`context.message_feedback.delete`、`context.session_feedback.record`、`context.session_feedback.list`。
- `capabilitySeams` v1（verified-python）：[接口与限制](../agent_docs/plugin_phase2_public_ports.md)。
  `context.browser_use.register`、`context.browser_use.provider_name`、`context.computer_use.register`、`context.computer_use.provider_name`、`context.lsp.register_provider`、`context.lsp.query`。
- `mcpResources` v1（verified-python）：[接口与限制](../agent_docs/plugin_phase2_public_ports.md)。
  `context.mcp_resources.servers`、`context.mcp_resources.open`、`connection.list`、`connection.templates`、`connection.read`。
- `contentAccess` v1（verified-python）：[接口与限制](../agent_docs/plugin_phase2_public_ports.md)。
  `context.tool_result_pruner.measure_content`、`context.tool_result_pruner.prune_content`、`context.file_references.list`、`context.file_references.resolve`、`context.web.fetch`、`context.web.search`、`context.plan_mode.enter`、`context.plan_mode.get`、`context.plan_mode.exit`。

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
