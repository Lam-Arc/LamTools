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
| `ctx.headlessStartup` | candidate | context.headless_startup.get + original run-local CLI；[core/src/lamtools_core/plugin_system/startup_access.py](../core/src/lamtools_core/plugin_system/startup_access.py), [core/src/lamtools_core/cli_commands/task.py](../core/src/lamtools_core/cli_commands/task.py), [core/tests/test_plugin_headless_startup.py](../core/tests/test_plugin_headless_startup.py) | 2 | 原run-local CLI在factory装配前提供真实任务/请求会话ID/实际thread_id/已解析权限的只读副本，正常或kernel失败收尾撤回。raw为JSON summary而非DSH NDJSON；无add-dir授权、DSH CLI语法/精确既有Session采用或stdin读取协议。 |
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
| `ctx.workingDirectory` | candidate | context.working_directory + context.for_session + main file/Git/command request snapshot；[core/src/lamtools_core/plugin_system/filesystem_access.py](../core/src/lamtools_core/plugin_system/filesystem_access.py), [core/tests/test_plugin_filesystem_access.py](../core/tests/test_plugin_filesystem_access.py), [core/tests/test_plugin_working_directory.py](../core/tests/test_plugin_working_directory.py), [core/tests/test_main_execution_directory.py](../core/tests/test_main_execution_directory.py), [core/tests/test_git_execution_directory.py](../core/tests/test_git_execution_directory.py) | 2 | 原持久目录/CAS和主代理文件/Git/命令固定；SDK子代理创建捕获目录，重新开启保留、子工具请求核对；原生未提供目录仍用项目根，无DSH事件/即时通知。 |
| `ctx.mcpResources` | candidate | context.mcp_resources；[core/src/lamtools_core/plugin_system/mcp_resources.py](../core/src/lamtools_core/plugin_system/mcp_resources.py) | 2 | 原配置与真实MCP传输，资源/模板列表、读资源与连接回收；无自动模型工具/DSH Agent注册协议。 |
| `ctx.browserUse` | candidate | context.browser_use；[core/src/lamtools_core/plugin_system/capability_seams.py](../core/src/lamtools_core/plugin_system/capability_seams.py) | 2 | 上游服务本身为独占名称槽；对应受管槽及异步清理，实际浏览器工具仍须提供方。 |
| `ctx.computerUse` | candidate | context.computer_use；[core/src/lamtools_core/plugin_system/capability_seams.py](../core/src/lamtools_core/plugin_system/capability_seams.py) | 2 | 上游独占名称槽近似，实际桌面操作及系统许可不包含在此注册服务。 |
| `ctx.cuaAccess` | gap | 补齐 cuaAccess 的 Sunday 公开接口或提供方注册 | 4 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.officeToPdf` | candidate | context.office_to_pdf.convert；[core/src/lamtools_core/plugin_system/office_access.py](../core/src/lamtools_core/plugin_system/office_access.py), [core/tests/test_plugin_office_access.py](../core/tests/test_plugin_office_access.py) | 2 | 真实LibreOffice CLI+原Windows Job；docx/xlsx/pptx字节准入，16MiB输入/64MiB解包声明/32MiB输出，取消及期限后回收scratch。无DSH延迟授权读取、优先队列、去重缓存、generation或字体诊断；非隔离沙箱。 过长LibreOffice临时profile目录可能无PDF，返回invalid-output；验收使用实际系统临时根。 |
| `ctx.attachments` | candidate | context.attachments；[core/src/lamtools_core/app/plugin_session_data.py](../core/src/lamtools_core/app/plugin_session_data.py) | 2 | 会话及项目隔离的原存储附件创建/引用/列表/预览；无DSH图片准入、opaque refs或文件流。 |
| `ctx.fileUploads` | gap | 补齐 fileUploads 的 Sunday 公开接口或提供方注册 | 3 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.llm` | candidate | context.llm.complete/stream + context.models；[core/src/lamtools_core/plugin_system/model_catalog.py](../core/src/lamtools_core/plugin_system/model_catalog.py), [core/src/lamtools_core/plugin_system/model_access.py](../core/src/lamtools_core/plugin_system/model_access.py), [core/tests/test_plugin_model_access.py](../core/tests/test_plugin_model_access.py), [core/tests/test_plugin_llm_access.py](../core/tests/test_plugin_llm_access.py) | 2 | 实际调用、结构化异步流和固定项目/模型路由；原生协议及有限大小/截止时间，不含 DSH adapter/prepareCall 全协议。 |
| `ctx.deepseekLlmApiExtensions` | candidate | context.llm_extensions + native HTTP request extension boundary；[core/src/lamtools_core/plugin_system/llm_extensions.py](../core/src/lamtools_core/plugin_system/llm_extensions.py), [core/src/lamtools_core/llm/request_extensions.py](../core/src/lamtools_core/llm/request_extensions.py), [core/src/lamtools_core/llm/http_client.py](../core/src/lamtools_core/llm/http_client.py), [core/tests/test_plugin_llm_extensions.py](../core/tests/test_plugin_llm_extensions.py) | 2 | 原注册/撤回与项目范围，最终serialized base不可变快照、独占字段和clone/freeze，SDK原HTTP complete/stream实际派发并于HTTP2xx头后幂等accept。准备失败省略字段，接收失败显式报错；仅SDK调用及明确支持的原客户端，无全局DeepSeek adapter接线，逐字段协作期限5秒。 |
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
| `ctx.workspaceFiles` | candidate | context.workspace_files.stat/list/read/read_bytes/changes + 明确一元Remote人工映射；[core/src/lamtools_core/plugin_system/workspace_files.py](../core/src/lamtools_core/plugin_system/workspace_files.py), [core/src/lamtools_core/plugin_system/context.py](../core/src/lamtools_core/plugin_system/context.py), [core/tests/test_plugin_workspace_files.py](../core/tests/test_plugin_workspace_files.py), [agent_docs/plugin_workspace_files.md](../agent_docs/plugin_workspace_files.md), [core/src/lamtools_core/plugin_system/workspace_file_changes.py](../core/src/lamtools_core/plugin_system/workspace_file_changes.py), [core/tests/test_plugin_workspace_file_changes.py](../core/tests/test_plugin_workspace_file_changes.py), [core/tests/test_plugin_remote_stream.py](../core/tests/test_plugin_remote_stream.py) | 3 | 可见会话/原执行目录限定的真实文件控制器；SDK base_file同根关联二进制读取及轮询合并ready/change流已验收，aclose/取消/停用真实回收。更严格限根/限额，显式Sunday multipart字节出口；显式ndjson服务端JSON流已验收；无DSH精确流协议、codec/envelope、双向流或远程后端。 |
| `ctx.workspaceChanges` | candidate | context.workspace_changes；[core/src/lamtools_core/plugin_system/workspace_changes.py](../core/src/lamtools_core/plugin_system/workspace_changes.py) | 2 | 受管Git状态快照/状态差异，固定仓库根、隔离GIT_DIR等变量、NUL路径/rename；status_revision非内容指纹，无文件历史/DSH投影。 |
| `ctx.terminalController` | candidate | 桌面终端状态；[core/src/lamtools_core/app/live/terminal_state.py](../core/src/lamtools_core/app/live/terminal_state.py) | 3 | 现有状态不是通用 PTY Remote 服务，需显式适配。 |
| `ctx.workspaceController` | candidate | 现有项目与会话操作；[core/src/lamtools_core/app/default_agent.py](../core/src/lamtools_core/app/default_agent.py) | 3 | 需 Remote 请求、状态基线及重连同步契约。 |
| `ctx.directoryPickerController` | gap | 补齐 directoryPickerController 的 Sunday 公开接口或提供方注册 | 3 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.typert` | candidate | context.types + ServiceKey/ServiceRef；[core/src/lamtools_core/plugin_system/host_views.py](../core/src/lamtools_core/plugin_system/host_views.py) | 2 | 原本地类型验证、注册、可选查询和受管调用引用；不是生成的Typert Remote/schema/resource运行时。 |
| `ctx.typertGateway` | candidate | 明确http.remote一元映射 + 原插件HTTP操作入口；[core/src/lamtools_core/plugin_system/remote_gateway.py](../core/src/lamtools_core/plugin_system/remote_gateway.py), [core/src/lamtools_core/plugin_system/plugin_http.py](../core/src/lamtools_core/plugin_system/plugin_http.py), [core/tests/test_plugin_remote_gateway.py](../core/tests/test_plugin_remote_gateway.py), [agent_docs/plugin_phase3_remote.md](../agent_docs/plugin_phase3_remote.md), [core/src/lamtools_core/plugin_system/remote_binary.py](../core/src/lamtools_core/plugin_system/remote_binary.py), [core/tests/test_plugin_remote_binary.py](../core/tests/test_plugin_remote_binary.py), [core/src/lamtools_core/plugin_system/remote_stream.py](../core/src/lamtools_core/plugin_system/remote_stream.py), [core/tests/test_plugin_remote_stream.py](../core/tests/test_plugin_remote_stream.py) | 3 | 已验收明确方法/精确扁平参数、一元HTTP入口及原认证/归属/审批；逐次取当前描述符，撤回不降级。非DSH生成codec/Peer/资源lookup、二进制/双向流或完整Gateway。 显式resultEncoding=multipart可返回有界原始字节附件，路径相对Sunday envelope；不是DSH codec/关联ID协议。 显式ndjson服务端JSON流含原认证/代际校验、断连、背压和真实迭代器回收；不是DSH流wire或双向流。 |
| `ctx.remoteAccess` | gap | 补齐 remoteAccess 的 Sunday 公开接口或提供方注册 | 3 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.sessionPersistence` | candidate | SESSIONS.events + context.checkpoints；[core/src/lamtools_core/app/core_session_store.py](../core/src/lamtools_core/app/core_session_store.py), [core/tests/test_plugin_checkpoint_access.py](../core/tests/test_plugin_checkpoint_access.py) | 2 | 原持久事件读取及检查点创建/对话恢复/回退/分叉；真实SQLite历史，文件不回退。没有DSH单写者日志句柄、append/flush屏障或原样崩溃重放。 |
| `ctx.configEditor` | candidate | context.config 快照/条件保存 + config_store；[core/src/lamtools_core/plugin_system/config_store.py](../core/src/lamtools_core/plugin_system/config_store.py), [core/src/lamtools_core/plugin_system/config_access.py](../core/src/lamtools_core/plugin_system/config_access.py), [core/tests/test_plugin_config_access.py](../core/tests/test_plugin_config_access.py) | 2 | 已验收当前插件快照、内容修订条件保存和共用管理入口；保存不等于应用，不提供 DSH profile overlay、重载失败回滚或注释保留。 |
| `ctx.settings` | candidate | context.settings；[core/src/lamtools_core/plugin_system/settings_access.py](../core/src/lamtools_core/plugin_system/settings_access.py) | 2 | 原Config/CAS上的Draft2020-12校验、安全有限错误、默认重置和保守secret投影；无动态namespace/volatile/继承重置/前端接线。 |
| `ctx.subagentModelSelection` | candidate | context.subagent_models + context.subagents；[core/src/lamtools_core/plugin_system/subagent_models.py](../core/src/lamtools_core/plugin_system/subagent_models.py), [core/tests/test_plugin_subagent_models.py](../core/tests/test_plugin_subagent_models.py) | 2 | SDK插件/父会话持久allowlist/default与原会话CAS；创建/投递/继续检查路由身份和提供方可用性，同wire多路由拒绝。非全局工具ACL、最终HTTP授权或配置代际锁，无DSH投影/发现开关/父模型继承/推理默认协议。 |
| `ctx.credentials` | candidate | context.credentials 引用子集 + 插件私有 secrets；[core/src/lamtools_core/plugin_system/secrets.py](../core/src/lamtools_core/plugin_system/secrets.py), [core/src/lamtools_core/plugin_system/credentials.py](../core/src/lamtools_core/plugin_system/credentials.py), [core/tests/test_plugin_credentials.py](../core/tests/test_plugin_credentials.py) | 2 | 已验收受管 resolve/describe/set/unset 与当前 owner 隔离，磁盘按操作重读和跨进程锁防止丢写。无全局环境回退、授权记录、modifyRecord 或变更事件。 |
| `ctx.deepseekAccount` | candidate | context.deepseek_account.open → account client；[core/src/lamtools_core/plugin_system/account_access.py](../core/src/lamtools_core/plugin_system/account_access.py), [core/src/lamtools_core/plugin_system/credentials.py](../core/src/lamtools_core/plugin_system/credentials.py), [core/tests/test_plugin_account_access.py](../core/tests/test_plugin_account_access.py) | 2 | 官方Platform auth_init/auth_exchange PKCE及CSRF，原授权控制器条件提交/回读、DPAPI凭据CAS、origin限令牌、资料/余额/退出/取消均经本地真实HTTP验收。需显式open和调用方callback bridge；无内置浏览器/HTTP回调、DSH即时startSignIn/watch/bonus、全局账户或生产登录验证。 |
| `ctx.authorization` | candidate | context.authorization；[core/src/lamtools_core/plugin_system/authorization_access.py](../core/src/lamtools_core/plugin_system/authorization_access.py) | 2 | 真实受管授权流，提交并回读提供方凭据才成功；发起方/提供方撤回均取消排空，同流互斥，无DeepSeek平台OAuth。 |
| `ctx.productAnalytics` | gap | 补齐 productAnalytics 的 Sunday 公开接口或提供方注册 | 3 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.otel` | candidate | context.otel.create_event_reporter/create_session_reporter；[core/src/lamtools_core/plugin_system/telemetry_access.py](../core/src/lamtools_core/plugin_system/telemetry_access.py) | 2 | 真实OTLP JSON HTTP报告器，默认关闭、显式端点/共享选择；有界队列及关闭、错误/丢弃计数，无重放/自动会话捕获。 |
| `ctx.productTelemetry` | candidate | context.otel.create_event_reporter → reporter.emit；[core/src/lamtools_core/plugin_system/telemetry_access.py](../core/src/lamtools_core/plugin_system/telemetry_access.py) | 2 | 显式配置默认关闭的普通事件报告器；只发选定记录，HTTP响应不等于仓库落库，非DSH自动产品统计。 |
| `ctx.sessionTelemetry` | candidate | context.otel.create_session_reporter → reporter.emit；[core/src/lamtools_core/plugin_system/telemetry_access.py](../core/src/lamtools_core/plugin_system/telemetry_access.py) | 2 | 报告器sharing=disabled/feedback-only/full，反馈筛选与有界排空；无自动canonical Session采集、DSH record waterfall或Session-log格式。 |
| `ctx.storage` | candidate | context.storage 的插件 JSON KV + 原独立数据目录；[core/src/lamtools_core/plugin_system/plugin_data.py](../core/src/lamtools_core/plugin_system/plugin_data.py), [core/src/lamtools_core/plugin_system/storage_access.py](../core/src/lamtools_core/plugin_system/storage_access.py), [core/tests/test_plugin_storage_access.py](../core/tests/test_plugin_storage_access.py) | 2 | 已验收插件所有的同步 SQLite JSON KV、精确单元版本、条件写与失败隔离；不提供 DSH 后端/form 注册或通用领域设施。 |
| `ctx.storageDomain` | candidate | context.storage_domain；[core/src/lamtools_core/plugin_system/storage_domain.py](../core/src/lamtools_core/plugin_system/storage_domain.py) | 2 | 原SQLite单快照事务的同步领域表/全局槽、整域CAS、精确版本和本地通知；≤1MiB、≤64表。无DSH schema推断/兼容迁移/远程后端/跨进程通知。 |
| `ctx.messageFeedback` | candidate | context.message_feedback；[core/src/lamtools_core/app/plugin_feedback.py](../core/src/lamtools_core/app/plugin_feedback.py) | 2 | 真实插件私有消息反馈CAS/版本墓碑，复用会话持久化；非DSH Session反馈事件。 |
| `ctx.sessionFeedback` | candidate | context.session_feedback；[core/src/lamtools_core/app/plugin_feedback.py](../core/src/lamtools_core/app/plugin_feedback.py) | 2 | 真实插件私有会话反馈与请求去重；原会话存储，允许冷会话，无隐式上传。 |
| `ctx.workspaceRegistry` | candidate | 项目与会话操作；[core/src/lamtools_core/app/default_agent.py](../core/src/lamtools_core/app/default_agent.py) | 3 | 需对齐工作区身份、排序、归档和会话归属。 |
| `ctx.sessionQuery` | candidate | context.session_query.query；[core/src/lamtools_core/app/core_session_store.py](../core/src/lamtools_core/app/core_session_store.py), [core/tests/test_plugin_session_query.py](../core/tests/test_plugin_session_query.py) | 2 | 有限只读扫描、可见性与不透明分页；不导出元数据，不是 DSH 全量查询投影协议。 |
| `ctx.fileReferences` | candidate | context.file_references；[core/src/lamtools_core/plugin_system/content_access.py](../core/src/lamtools_core/plugin_system/content_access.py) | 2 | 本地有限引用候选与唯一成果路径恢复；不包含DSH Agent或跨平台身份。 |
| `ctx.sessionReferenceResolver` | candidate | context.session_references；[core/src/lamtools_core/app/plugin_session_references.py](../core/src/lamtools_core/app/plugin_session_references.py) | 2 | 原项目可见会话候选与有限不可变摘录；显式选择，返回截断/摘要指纹，不自动模型总结或pre-step注入。 |
| `ctx.sessionTitle` | candidate | context.session_title；[core/src/lamtools_core/app/plugin_session_data.py](../core/src/lamtools_core/app/plugin_session_data.py) | 2 | 原持久标题读写/CAS及默认标题保护；不替换原自动生成器。 |
| `ctx.systemPrompt` | candidate | context.prompts.section/variable/on_assemble + system_prompt_waterfall；[core/src/lamtools_core/plugin_system/prompt_waterfall.py](../core/src/lamtools_core/plugin_system/prompt_waterfall.py), [core/src/lamtools_core/plugin_system/prompt_extensions.py](../core/src/lamtools_core/plugin_system/prompt_extensions.py), [core/tests/test_plugin_prompt_extensions.py](../core/tests/test_plugin_prompt_extensions.py) | 2 | 已验收受管同步 section/variable/assemble、插件排序及会话/agent_id 覆盖。追加于内置段之后；完整替换、动态上下文、集中顺序表、change 事件、工具 schema 及 DSH 失败语义仍需适配。 |
| `ctx.tools` | candidate | context.tools.register/restrict/guard/on + 清单 tools.jsonc；[core/src/lamtools_core/plugin_system/capabilities.py](../core/src/lamtools_core/plugin_system/capabilities.py), [core/src/lamtools_core/plugin_system/tool_extensions.py](../core/src/lamtools_core/plugin_system/tool_extensions.py), [core/tests/test_plugin_tool_extensions.py](../core/tests/test_plugin_tool_extensions.py) | 2 | 动态注册、收窄、守卫与 pre/post/result 基础子集已验收；仅扁平 schema，原数值审批。execute 包装、参数改写、动态 ask 与 DSH 决策语义仍需适配。 |
| `ctx.userQuestions` | candidate | context.questions.ask/answer；[core/tests/test_plugin_question_access.py](../core/tests/test_plugin_question_access.py) | 2 | 独立程序化表单问答、单终端受管回答者、校验及取消/撤回/超时；无Agent身份、waterfall、计时继续、持久投影或前端接线，不充当审批。 |
| `ctx.planMode` | candidate | context.plan_mode；[core/src/lamtools_core/plugin_system/content_access.py](../core/src/lamtools_core/plugin_system/content_access.py) | 2 | 当前启动代/视图只读工具白名单，原审批继续生效；不持久化、不代替评审，不撤销已执行副作用。 |
| `ctx.agentPresets` | candidate | context.agent_presets；[core/src/lamtools_core/plugin_system/host_views.py](../core/src/lamtools_core/plugin_system/host_views.py) | 2 | 原AgentPresetRegistry列表/解析/组合和受管服务调用，JSON快照；无DSH逐会话mount/revoke协议。 |
| `ctx.commands` | candidate | context.commands.register + command.catalog/execute + 声明式 commands；[core/src/lamtools_core/plugin_system/commands.py](../core/src/lamtools_core/plugin_system/commands.py), [core/src/lamtools_core/plugin_system/command_extensions.py](../core/src/lamtools_core/plugin_system/command_extensions.py), [core/tests/test_plugin_command_extensions.py](../core/tests/test_plugin_command_extensions.py) | 2 | 已验收受管文本 handler、会话覆盖、目录/执行、撤回与排空。Sunday 裁剪输入空白；附件、完整行解析、稳定定义 ID、变更通知及 DSH 日志需适配。界面当前仅查询全局目录。 |
| `ctx.sessionProjections` | candidate | context.session_projections；[core/src/lamtools_core/app/plugin_session_data.py](../core/src/lamtools_core/app/plugin_session_data.py) | 2 | 原数据库最新摘要与有限事件页，无扩展投影定义/DSH重放。 |
| `ctx.sessionProjectionCache` | candidate | context.session_projection_cache；[core/src/lamtools_core/plugin_system/host_views.py](../core/src/lamtools_core/plugin_system/host_views.py) | 2 | 真实启动代/项目内128会话缓存，每次get回原权威核对运行/修订字段，返回副本；无DSH自定义投影。 |
| `ctx.skills` | candidate | context.skills.register + 清单 skills 与 SkillRegistry；[core/src/lamtools_core/plugin_system/capabilities.py](../core/src/lamtools_core/plugin_system/capabilities.py), [core/src/lamtools_core/plugin_system/skill_extensions.py](../core/src/lamtools_core/plugin_system/skill_extensions.py), [core/tests/test_plugin_skill_extensions.py](../core/tests/test_plugin_skill_extensions.py) | 2 | 静态目录迁移与受管全局内存技能已验收，模型/用户调用策略分别检查。磁盘优先；动态目录、远程 provider、scope、snapshot/invalidate 与 change 事件未覆盖。 |
| `ctx.agents` | candidate | context.agents；[core/src/lamtools_core/plugin_system/agent_access.py](../core/src/lamtools_core/plugin_system/agent_access.py) | 2 | 真实插件/项目根代理句柄，原创建/队列/引导/回执/暂停继续/取消/历史；同ID修复交接，目录存在检查。无DSH AgentHandle/activation或任意插件工厂。 |
| `ctx.agentDefaultModel` | candidate | context.models.select(scene) / 场景模型记忆；[core/src/lamtools_core/plugin_system/model_catalog.py](../core/src/lamtools_core/plugin_system/model_catalog.py), [core/src/lamtools_core/plugin_system/model_access.py](../core/src/lamtools_core/plugin_system/model_access.py), [core/tests/test_plugin_model_access.py](../core/tests/test_plugin_model_access.py) | 2 | Sunday 按 chat/study/background 场景只读解析，已验收同场景替换和显式错误；不提供 DSH 单一进程默认值、saveSelection 或会话最终选模。 |
| `ctx.agentLoop` | candidate | context.agent_loop → original root session/kernel；[core/src/lamtools_core/plugin_system/agent_access.py](../core/src/lamtools_core/plugin_system/agent_access.py) | 2 | context.agent_loop复用已验收原根会话工厂/控制句柄与桌面kernel；创建、取句柄和暂停继续均走原权威。不是可替换Cordis循环，不提供自建Session writer、scope插件挂载或DSH crash-closer重放。 |
| `ctx.schedule` | candidate | context.schedule + original Arrange Runner；[core/src/lamtools_core/plugins/bundled/workflow/backend/runner_scheduler.py](../core/src/lamtools_core/plugins/bundled/workflow/backend/runner_scheduler.py), [core/tests/test_plugin_durable_access.py](../core/tests/test_plugin_durable_access.py) | 2 | 原持久任务触发/执行/暂停/取消，固定项目与插件 ID；提醒格式、cron、投递历史与 DSH 不同。 |
| `ctx.goals` | candidate | context.goals + original GoalManager；[core/src/lamtools_core/runtime/goal.py](../core/src/lamtools_core/runtime/goal.py), [core/tests/test_plugin_durable_access.py](../core/tests/test_plugin_durable_access.py) | 2 | 持久多目标、固定插件/项目身份及重复创建回执；非 DSH 单会话目标投影、轮数、CAS 引用或续跑激活。 |
| `ctx.ssh` | candidate | context.ssh.connect → connection.execute/close；[core/src/lamtools_core/plugin_system/ssh_access.py](../core/src/lamtools_core/plugin_system/ssh_access.py), [core/tests/test_plugin_ssh_access.py](../core/tests/test_plugin_ssh_access.py) | 2 | 真实OpenSSH公钥/明确known-host校验与原Windows Job命令执行，关闭等待已准入启动、取消回收本机进程。每命令独立连接，无DSH POSIX helper/hash/hello/RPC/流转发/心跳租约；不能保证远端子进程清理，request/connectStream仍交agent移植。 |
| `ctx.subprocess` | candidate | context.processes.spawn/run + lookup/environment；[core/src/lamtools_core/plugin_system/process_access.py](../core/src/lamtools_core/plugin_system/process_access.py), [core/tests/test_plugin_process_access.py](../core/tests/test_plugin_process_access.py), [core/tests/test_plugin_owned_processes.py](../core/tests/test_plugin_owned_processes.py) | 2 | Windows Job 原生进程、有限输出与回收；启动到分配存在竞争窗口，无 stdin/raw stdio/control/PTY/远程协议。 |
| `ctx.shell` | candidate | context.shell.resolve/execute + owned native processes；[core/tests/test_plugin_shell_access.py](../core/tests/test_plugin_shell_access.py) | 2 | PowerShell近似，显式期限、有限字节尾及原Job回收；无stdin、onExpiry:none、消费游标、spill、PTY、沙箱或远程后端。 |
| `ctx.shellEnv` | candidate | context.shell_env.register/list/collect；[core/tests/test_plugin_shell_access.py](../core/tests/test_plugin_shell_access.py) | 2 | 受管SUNDAY_*声明、每次收集、冲突/撤回与5秒期限；不伪造DSH身份或profile。session_id仅标签，无模型工具自动接线。 |
| `ctx.terminals` | candidate | context.terminals；[core/src/lamtools_core/plugin_system/terminal_access.py](../core/src/lamtools_core/plugin_system/terminal_access.py) | 2 | 真实受管交互stdin管道与输出/关闭；pty=false，无信号/窗口大小或重启持久化。 |
| `ctx.sandbox` | candidate | context.sandbox.run；[core/src/lamtools_core/plugin_system/sandbox_access.py](../core/src/lamtools_core/plugin_system/sandbox_access.py), [core/runtime/windows-sandbox/package-lock.json](../core/runtime/windows-sandbox/package-lock.json), [core/tests/test_plugin_sandbox_access.py](../core/tests/test_plugin_sandbox_access.py) | 2 | 已安装并锁定的官方Windows ACL runner+原Job，真实run限制文件写入，enforcement=partial、取消/临时回收；缺失运行时拒绝，显式danger-full-access才不限制。Node22+及独立npm依赖必需；无DSH confine返回argv协议、额外根、读/网络隔离或普通工具自动接线，工作区ACL为常驻改动。 |
| `ctx.sandboxPolicy` | candidate | context.sandbox_policy.resolve/set；[core/src/lamtools_core/plugin_system/sandbox_access.py](../core/src/lamtools_core/plugin_system/sandbox_access.py), [core/runtime/windows-sandbox/package-lock.json](../core/runtime/windows-sandbox/package-lock.json), [core/tests/test_plugin_sandbox_access.py](../core/tests/test_plugin_sandbox_access.py) | 2 | 原会话元数据CAS上的插件私有模式，默认read-only，同次读取原目录/修订，sandbox.run真实消费；显式override不是审批。无DSH session事件/模型快照、额外写根、主工具/terminal/fs统一政策或授权变更。 |
| `ctx.approval` | candidate | context.approvals.request/answer + native tool approval；[core/src/lamtools_core/app/default_agent.py](../core/src/lamtools_core/app/default_agent.py), [core/tests/test_plugin_approval_access.py](../core/tests/test_plugin_approval_access.py) | 2 | 已有活动回合请求、受管单回答者与持久审计；默认缺失不放行。没有前端卡片、waterfall、持久 setPolicy 或 DSH turn-enclosed 编码。 |
| `ctx.permissionPresets` | candidate | context.permissions.catalog/read / 既有权限操作；[core/src/lamtools_core/app/plugin_permissions.py](../core/src/lamtools_core/app/plugin_permissions.py), [core/tests/test_plugin_permission_access.py](../core/tests/test_plugin_permission_access.py) | 2 | 已验收固定 Sunday 预设目录和会话偏好只读查询；不返回授权，不改策略。无 DSH sandbox 组合、custom、Auto review 或动态目录。 |
| `ctx.ptcRuntime` | candidate | context.ptc_runtime；[core/src/lamtools_core/plugin_system/program_access.py](../core/src/lamtools_core/plugin_system/program_access.py) | 2 | 真实Windows Job Python程序执行、结构化结果/异常/期限和取消回收；confined=false，无DSH SDK/Node/宿主回调。 |
| `ctx.fs` | candidate | context.filesystem；[core/src/lamtools_core/plugin_system/filesystem_access.py](../core/src/lamtools_core/plugin_system/filesystem_access.py), [core/tests/test_plugin_filesystem_access.py](../core/tests/test_plugin_filesystem_access.py), [core/tests/test_plugin_filesystem_ranges.py](../core/tests/test_plugin_filesystem_ranges.py), [core/tests/test_plugin_filesystem_stream.py](../core/tests/test_plugin_filesystem_stream.py), [core/tests/test_plugin_filesystem_mutations.py](../core/tests/test_plugin_filesystem_mutations.py), [core/tests/test_plugin_file_watch.py](../core/tests/test_plugin_file_watch.py), [core/tests/test_plugin_file_targets.py](../core/tests/test_plugin_file_targets.py) | 2 | 读取、范围、流、最终链接及条件写入/编辑；本地路径转换与有限元数据轮询监听。1MiB 修改、内容修订与合作路径锁；无原生事件、递归监听、远程后端或完整 DSH 目标身份。 |
| `ctx.compaction` | candidate | context.compaction.compact_now / 既有 agent preset compaction；[core/src/lamtools_core/app/plugin_compaction.py](../core/src/lamtools_core/app/plugin_compaction.py), [core/tests/test_plugin_compaction_access.py](../core/tests/test_plugin_compaction_access.py) | 2 | 已验收桌面空闲会话手动压缩子集，修订冲突、取消、排他与停用租约；无自动/区间 API、持久锁或 DSH 检查点协议。 |
| `ctx.subagents` | candidate | context.subagents + original SubAgentSupervisor；[core/src/lamtools_core/app/default_agent.py](../core/src/lamtools_core/app/default_agent.py), [core/tests/test_plugin_subagent_access.py](../core/tests/test_plugin_subagent_access.py), [core/tests/test_plugin_subagent_continuation.py](../core/tests/test_plugin_subagent_continuation.py) | 2 | 原监督器/邮箱的具名持久成员create/list/get/message/close及单成员interrupt/resume；固定插件/项目和可见父会话，恢复验证非live提交状态及实际继续执行器。不覆盖共享暂停、目录捕获、DSH activation/外部提供方/完整父子协议。 |
| `ctx.speechToText` | gap | 补齐 speechToText 的 Sunday 公开接口或提供方注册 | 4 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.agentTeams` | gap | 补齐 agentTeams 的 Sunday 公开接口或提供方注册 | 4 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.claudeCodeMods` | gap | 补齐 claudeCodeMods 的 Sunday 公开接口或提供方注册 | 4 | 尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。 |
| `ctx.inspector` | candidate | context.inspector；[core/src/lamtools_core/plugin_system/host_views.py](../core/src/lamtools_core/plugin_system/host_views.py) | 2 | 真实本地服务/操作描述发现和精确只读查询；无服务值、执行入口或浏览器运行时。 |
| `ctx.jobs` | candidate | context.jobs.start/get/list/read/wait/kill/remove；[core/tests/test_plugin_jobs_access.py](../core/tests/test_plugin_jobs_access.py) | 2 | 插件启动代/项目内异步回调作业、有限输出/记录与实际取消join；session仅标签，无DSH控制器、消费读取、通知、持久化或会话ACL。 |
| `ctx.web` | candidate | context.web；[core/src/lamtools_core/plugin_system/content_access.py](../core/src/lamtools_core/plugin_system/content_access.py) | 2 | 原搜索提供方及HTTP抓取工具的受管SDK，保留原结果/失败；不授予模型审批。 |
| `ctx.spillStore` | candidate | context.spill_store.save_text；[core/tests/test_plugin_spill_access.py](../core/tests/test_plugin_spill_access.py) | 2 | 插件/会话标签分组的真实本地UTF-8持久文件及精确字节数；8MiB上限，无自动预览/过期/远程或读取授权。 |
| `ctx.directoryPicker` | candidate | context.directory_picker.capability；[core/src/lamtools_core/plugin_system/directory_picker.py](../core/src/lamtools_core/plugin_system/directory_picker.py), [core/tests/test_plugin_directory_picker.py](../core/tests/test_plugin_directory_picker.py) | 2 | 本地固定项目根的同步browse能力，真实限额列举/单子目录创建、截断与根内祖先；复用原文件路径规则，拒绝网络/非固定盘及已观察链接。无native对话框、根外workspace选择、远程浏览或扫描中断/持久选择。 |
| `ctx.webServer` | candidate | 插件 HTTP 路由；[core/src/lamtools_core/plugin_system/plugin_http.py](../core/src/lamtools_core/plugin_system/plugin_http.py), [core/tests/test_plugin_http_routes.py](../core/tests/test_plugin_http_routes.py), [agent_docs/plugin_phase3_remote.md](../agent_docs/plugin_phase3_remote.md) | 3 | 已有插件声明的具名HTTP operation路由、归属/审批检查和令牌认证；非ASCII令牌返回401，认证头不转交操作。仅原HTTP接入基础经过验收，缺通用upgrade、index注入和完整DSH协议。 原插件HTTP请求体≤1MiB，声明长度及实际分块均受限，超限413且不派发操作；不是文件上传或Typert流能力。 |
| `ctx.webApp` | candidate | context.web_app.get_advertised_url + original HTTP composition；[core/src/lamtools_core/plugin_system/web_app.py](../core/src/lamtools_core/plugin_system/web_app.py), [core/src/lamtools_core/app/http_agent_app.py](../core/src/lamtools_core/app/http_agent_app.py), [core/src/lamtools_core/cli_commands/server.py](../core/src/lamtools_core/cli_commands/server.py), [core/tests/test_plugin_web_app.py](../core/tests/test_plugin_web_app.py) | 2 | 原HTTP静态宿主启动前发布明确配置URL，原serve启动者提供已知端口/协议，关闭撤回；不取请求Host或导出token。仅已有frontend_dir+advertised_url组合，无Tauri origin猜测、浏览器打开/DSH_WEB_URL/前端重写，端口0未知不提供。 |
| `ctx.clientModules` | candidate | Sunday 插件 UI 注册；[core/ui/src/plugins/registry.ts](../core/ui/src/plugins/registry.ts) | 3 | Vue 与 React/Cordis 模块图不同；保留既有 UI 生命周期。 |
| `ctx.workflowEngine` | candidate | workflow 插件后端；[core/src/lamtools_core/plugins/bundled/workflow/backend/operations.py](../core/src/lamtools_core/plugins/bundled/workflow/backend/operations.py) | 4 | 需公开脚本/子任务/取消协议；不可假设 PTC 源码可直接运行。 |
| `ctx.webhookRuntime` | candidate | 插件 HTTP routes → operation；[core/src/lamtools_core/plugin_system/plugin_http.py](../core/src/lamtools_core/plugin_system/plugin_http.py) | 4 | 需认证交付、规则注册和会话创建映射。 |
| `ctx.lsp` | candidate | context.lsp；[core/src/lamtools_core/plugin_system/capability_seams.py](../core/src/lamtools_core/plugin_system/capability_seams.py) | 2 | 真实受管提供方注册/扩展选择/四类规范查询；语言服务器须另行安装，不伪造结果。 |
| `ctx.dynamicCordisRunner` | candidate | context.dynamic_runner；[core/src/lamtools_core/plugin_system/program_access.py](../core/src/lamtools_core/plugin_system/program_access.py) | 2 | 真实Python内容定义和原作业运行/停止/撤回，关闭准入后排空；非Cordis VM/TS或客户端半边，host_callbacks=false。 |
| `ctx.cordisInspect` | candidate | context.inspector；[core/src/lamtools_core/plugin_system/host_views.py](../core/src/lamtools_core/plugin_system/host_views.py) | 2 | 原宿主本地只读发现近似；非Cordis事件/配置/slot反射，不含客户端查询。 |
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
- `sessionReferences` v1（verified-python）：[接口与限制](../agent_docs/plugin_phase2_public_ports.md)。
  `context.session_references.list_candidates`、`context.session_references.prepare`。
- `programRuntime` v1（verified-python）：[接口与限制](../agent_docs/plugin_phase2_public_ports.md)。
  `context.ptc_runtime.run`。
- `dynamicPrograms` v1（verified-python）：[接口与限制](../agent_docs/plugin_phase2_public_ports.md)。
  `context.dynamic_runner.define`、`context.dynamic_runner.run`、`context.dynamic_runner.stop`、`context.dynamic_runner.undefine`。
- `terminals` v1（verified-python）：[接口与限制](../agent_docs/plugin_phase2_public_ports.md)。
  `context.terminals.open`、`terminal.send`、`terminal.read`、`terminal.wait`、`terminal.close`。
- `authorization` v1（verified-python）：[接口与限制](../agent_docs/plugin_phase2_public_ports.md)。
  `context.authorization.register_flow`、`context.authorization.list`、`context.authorization.begin`、`context.authorization.cancel`。
- `hostViews` v1（verified-python）：[接口与限制](../agent_docs/plugin_phase2_public_ports.md)。
  `context.agent_presets.compose`、`context.agent_presets.list`、`context.agent_presets.resolve`、`context.inspector.query`、`context.inspector.snapshot`、`context.session_projection_cache.get`、`context.session_projection_cache.invalidate`、`context.types.get`、`context.types.register`、`context.types.require`。
- `storageDomain` v1（verified-python）：[接口与限制](../agent_docs/plugin_phase2_public_ports.md)。
  `context.storage_domain.open`、`domain.read`、`domain.commit`、`domain.on_change`、`domain.close`。
- `agentControl` v1（verified-python）：[接口与限制](../agent_docs/plugin_phase2_public_ports.md)。
  `context.agents.create`、`context.agents.attach`、`handle.followup`、`handle.steer`、`handle.state`、`handle.wait`、`handle.events`、`handle.cancel`、`handle.resume`、`handle.dispose`、`context.agent_loop.create`、`context.agent_loop.attach`。
- `telemetry` v1（verified-python）：[接口与限制](../agent_docs/plugin_phase2_public_ports.md)。
  `context.otel.create_event_reporter`、`context.otel.create_session_reporter`、`reporter.emit`、`reporter.status`、`reporter.flush`、`reporter.shutdown`。
- `settings` v1（verified-python）：[接口与限制](../agent_docs/plugin_phase2_public_ports.md)。
  `context.settings.read`、`context.settings.validate`、`context.settings.replace`、`context.settings.reset`、`context.settings.public`。
- `workspaceChanges` v1（verified-python）：[接口与限制](../agent_docs/plugin_phase2_public_ports.md)。
  `context.workspace_changes.snapshot`、`context.workspace_changes.compare_status`。
- `subagentModels` v1（verified-python）：[接口与限制](../agent_docs/plugin_phase2_public_ports.md)。
  `context.subagent_models.read`、`context.subagent_models.set`、`context.subagent_models.select`。
- `officeToPdf` v1（verified-python）：[接口与限制](../agent_docs/plugin_phase2_public_ports.md)。
  `context.office_to_pdf.convert`。
- `headlessStartup` v1（verified-python）：[接口与限制](../agent_docs/plugin_phase2_public_ports.md)。
  `context.headless_startup.get`。
- `directoryPicker` v1（verified-python）：[接口与限制](../agent_docs/plugin_phase2_public_ports.md)。
  `context.directory_picker.capability`、`capability.list`、`capability.create_directory`。
- `llmExtensions` v1（verified-python）：[接口与限制](../agent_docs/plugin_phase2_public_ports.md)。
  `context.llm_extensions.register`、`context.llm_extensions.prepare`、`prepared.accept`。
- `ssh` v1（verified-python）：[接口与限制](../agent_docs/plugin_phase2_public_ports.md)。
  `context.ssh.connect`、`connection.execute`、`connection.close`。
- `sandbox` v1（verified-python）：[接口与限制](../agent_docs/plugin_phase2_public_ports.md)。
  `context.sandbox.run`。
- `sandboxPolicy` v1（verified-python）：[接口与限制](../agent_docs/plugin_phase2_public_ports.md)。
  `context.sandbox_policy.resolve/set`。
- `webApp` v1（verified-python）：[接口与限制](../agent_docs/plugin_phase2_public_ports.md)。
  `context.web_app.get_advertised_url`。
- `deepseekAccount` v1（verified-python）：[接口与限制](../agent_docs/plugin_phase2_public_ports.md)。
  `context.deepseek_account.open`、`account.get_state`、`account.sign_in`、`account.cancel_sign_in`、`account.sign_out`、`account.get_profile`、`account.get_balance`、`account.resolve_token`、`account.reject_token`、`account.get_platform_session`、`account.get_device_identity`、`context.credentials.compare_exchange`。
- `remoteGateway` v3（verified-python）：[接口与限制](../agent_docs/plugin_phase3_remote.md)。
  `POST /api/core/plugin-remote/{plugin}/{namespace}/{method}`、`plugin.json http.remote`、`plugin.json http.remote.resultEncoding`、`plugin.json http.remote.resultEncoding=ndjson`。
- `workspaceFiles` v2（verified-python）：[接口与限制](../agent_docs/plugin_workspace_files.md)。
  `context.workspace_files.stat/list/read/read_bytes/changes`。

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
