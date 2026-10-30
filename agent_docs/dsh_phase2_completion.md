# 第二阶段完成清单

user:“继续，把 2 阶段都做完”+(以现有 71 项服务范围为准，继续补齐，不把基础子集或缺失提供方冒充完整完成)。

验收基线：固定上游提交 f3803c96974ad4a94195fb97e5c637e9c2a3afe3。每项必须有可调用契约、参数/返回/错误、作用域、取消/清理及适用的持久行为证据；近似接口须列出差异。缺少提供方或受前端并行改造阻塞的项目保留未勾选并说明。

已勾选表示该服务已有经过行为验收的近似公开接口，**不表示所有DSH方法或运行协议等价**。原插件语义差异必须由迁移agent处理；未勾选仍属于本阶段待完成范围。

## 连续实施记录

- [x] 文件写入/编辑和修订冲突控制。
- [x] 受管进程句柄、输出、终止、取消与所有权回收。
- [x] 模型实际调用/流、使用量与估算接口。
- [x] 有限会话查询、原持久目标/计划入口。
- [x] 后端审批请求/回答者/审计及插件管理、运行档读取。
- [x] 本地路径转换及有限轮询监听。
- [x] PowerShell执行、环境贡献、插件后台作业及长文本保存近似接口。
- [x] 独立普通程序化问答、回答者及取消边界；Web/持久继续协议未纳入此项。
- [x] 会话持久执行目录/CAS、固定插件执行视图及原生检查点恢复/分叉入口。
- [x] 主代理六种文件工具/run_command按请求固定目录，模型尾部通知与目录失效恢复。
- [x] 专用Git目录固定与工具目录归属核对；原生具名子代理创建/投递/查询/关闭门面。
- [x] 单成员中断与已提交状态恢复，兄弟隔离、父暂停保护和实际执行器继续能力检查。
- [ ] 会话工作目录持久化、恢复与子代理完整控制。
- [ ] 配置/技能/提示词剩余公共契约。
- [ ] 外部能力提供方、审批与隔离契约，按依赖逐项验收。
- [ ] 逐行核验以下 71 项，更新迁移脚本和文档，执行相关新增测试。

## 逐服务验收（71 项）

- [ ] `headlessStartup`：补齐 headlessStartup 的 Sunday 公开接口或提供方注册。当前边界：尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。
- [x] `hmr`：context.plugins.reload / plugin.system.reload。已验收近似接口；差异：显式受管重载近似；不提供自动文件监控、任意模块图热替换或 UI HMR。
- [x] `pluginManager`：context.plugins + plugin.system.*。已验收近似接口；差异：真实列表/启停/显式重载仍走原目录和 supervisor；自停拒绝。不复制整个 Cordis 插件管理 API。
- [x] `profileContext`：context.profiles.list/resolve。已验收近似接口；差异：原运行档声明与解析只读查询；非 Cordis 当前组合 Context、来源树或安装目录隔离。
- [ ] `workingDirectory`：context.working_directory + context.for_session + main file/Git/command request snapshot。当前边界：原会话目录/CAS，保留项目配置身份；主代理文件/Git/命令送审前固定目标，目录变化追加尾部通知，失效时恢复原项目。MCP等其他服务保留项目身份，子代理、即时通知及DSH事件协议仍有差异。
- [x] `mcpResources`：context.mcp_resources。已验收近似接口；差异：原配置与真实MCP传输，资源/模板列表、读资源与连接回收；无自动模型工具/DSH Agent注册协议。
- [x] `browserUse`：context.browser_use。已验收近似接口；差异：上游服务本身为独占名称槽；对应受管槽及异步清理，实际浏览器工具仍须提供方。
- [x] `computerUse`：context.computer_use。已验收近似接口；差异：上游独占名称槽近似，实际桌面操作及系统许可不包含在此注册服务。
- [ ] `officeToPdf`：补齐 officeToPdf 的 Sunday 公开接口或提供方注册。当前边界：尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。
- [x] `attachments`：context.attachments。已验收近似接口；差异：会话及项目隔离的原存储附件创建/引用/列表/预览；无DSH图片准入、opaque refs或文件流。
- [x] `llm`：context.llm.complete/stream + context.models。已验收近似接口；差异：实际调用、结构化异步流和固定项目/模型路由；原生协议及有限大小/截止时间，不含 DSH adapter/prepareCall 全协议。
- [ ] `deepseekLlmApiExtensions`：补齐 deepseekLlmApiExtensions 的 Sunday 公开接口或提供方注册。当前边界：尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。
- [x] `tokenMeter`：context.llm.estimate + provider usage。已验收近似接口；差异：只有本地启发式估算与实际响应 usage；没有 DSH replay-aware surface/request pricing 投影。
- [x] `toolResultPruner`：context.tool_result_pruner。已验收近似接口；差异：Unicode文本计数及纯内容头尾裁剪，保留富内容；无Session shadow事件/历史重放。
- [x] `sessions`：SESSIONS / sessions 公开契约 + session_store。已验收近似接口；差异：Python 已公开创建、状态、文本投递、取消、队列和持久事件；Sunday 事件格式不同，仍需 DSH 语义适配，非原样 append 日志。
- [ ] `workspaceChanges`：补齐 workspaceChanges 的 Sunday 公开接口或提供方注册。当前边界：尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。
- [ ] `typert`：补齐 typert 的 Sunday 公开接口或提供方注册。当前边界：尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。
- [x] `sessionPersistence`：SESSIONS.events + context.checkpoints。已验收近似接口；差异：原持久事件读取及检查点创建/对话恢复/回退/分叉；真实SQLite历史，文件不回退。没有DSH单写者日志句柄、append/flush屏障或原样崩溃重放。
- [x] `configEditor`：context.config 快照/条件保存 + config_store。已验收近似接口；差异：已验收当前插件快照、内容修订条件保存和共用管理入口；保存不等于应用，不提供 DSH profile overlay、重载失败回滚或注释保留。
- [ ] `settings`：context.config 基础校验 + 原 config schema / config_store。当前边界：基础文件读写已验收；完整 Config 校验、volatile 引用、动态 namespace、secret 字段投影、继承重置与 UI 修订号接线仍待实施。
- [ ] `subagentModelSelection`：context.models.select 的只读查询 + 子代理与模型配置。当前边界：只读目录和场景选择可供调用方使用；子会话获准路由、发现政策、默认值覆盖和持久化尚未提供 DSH 等价契约，目录成员不等于授权。
- [x] `credentials`：context.credentials 引用子集 + 插件私有 secrets。已验收近似接口；差异：已验收受管 resolve/describe/set/unset 与当前 owner 隔离，磁盘按操作重读和跨进程锁防止丢写。无全局环境回退、授权记录、modifyRecord 或变更事件。
- [ ] `deepseekAccount`：补齐 deepseekAccount 的 Sunday 公开接口或提供方注册。当前边界：尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。
- [ ] `authorization`：补齐 authorization 的 Sunday 公开接口或提供方注册。当前边界：尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。
- [ ] `otel`：补齐 otel 的 Sunday 公开接口或提供方注册。当前边界：尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。
- [ ] `productTelemetry`：补齐 productTelemetry 的 Sunday 公开接口或提供方注册。当前边界：尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。
- [ ] `sessionTelemetry`：补齐 sessionTelemetry 的 Sunday 公开接口或提供方注册。当前边界：尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。
- [x] `storage`：context.storage 的插件 JSON KV + 原独立数据目录。已验收近似接口；差异：已验收插件所有的同步 SQLite JSON KV、精确单元版本、条件写与失败隔离；不提供 DSH 后端/form 注册或通用领域设施。
- [ ] `storageDomain`：context.storage 插件隔离 JSON KV（需人工改造领域）。当前边界：基础 KV 可作人工重构目标，但 schema、tables/global、compatibleVersions、内存同步域、后端路由、异步写链与 domain/changed 均未实现 DSH 等价契约。
- [x] `messageFeedback`：context.message_feedback。已验收近似接口；差异：真实插件私有消息反馈CAS/版本墓碑，复用会话持久化；非DSH Session反馈事件。
- [x] `sessionFeedback`：context.session_feedback。已验收近似接口；差异：真实插件私有会话反馈与请求去重；原会话存储，允许冷会话，无隐式上传。
- [x] `sessionQuery`：context.session_query.query。已验收近似接口；差异：有限只读扫描、可见性与不透明分页；不导出元数据，不是 DSH 全量查询投影协议。
- [x] `fileReferences`：context.file_references。已验收近似接口；差异：本地有限引用候选与唯一成果路径恢复；不包含DSH Agent或跨平台身份。
- [ ] `sessionReferenceResolver`：补齐 sessionReferenceResolver 的 Sunday 公开接口或提供方注册。当前边界：尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。
- [x] `sessionTitle`：context.session_title。已验收近似接口；差异：原持久标题读写/CAS及默认标题保护；不替换原自动生成器。
- [x] `systemPrompt`：context.prompts.section/variable/on_assemble + system_prompt_waterfall。已验收近似接口；差异：已验收受管同步 section/variable/assemble、插件排序及会话/agent_id 覆盖。追加于内置段之后；完整替换、动态上下文、集中顺序表、change 事件、工具 schema 及 DSH 失败语义仍需适配。
- [x] `tools`：context.tools.register/restrict/guard/on + 清单 tools.jsonc。已验收近似接口；差异：动态注册、收窄、守卫与 pre/post/result 基础子集已验收；仅扁平 schema，原数值审批。execute 包装、参数改写、动态 ask 与 DSH 决策语义仍需适配。
- [x] `userQuestions`：context.questions.ask/answer。已验收近似接口；差异：独立程序化表单问答、单终端受管回答者、校验及取消/撤回/超时；无Agent身份、waterfall、计时继续、持久投影或前端接线，不充当审批。
- [x] `planMode`：context.plan_mode。已验收近似接口；差异：当前启动代/视图只读工具白名单，原审批继续生效；不持久化、不代替评审，不撤销已执行副作用。
- [ ] `agentPresets`：agent_presets。当前边界：已有组合和服务注册；需逐会话版本与撤回语义适配。
- [x] `commands`：context.commands.register + command.catalog/execute + 声明式 commands。已验收近似接口；差异：已验收受管文本 handler、会话覆盖、目录/执行、撤回与排空。Sunday 裁剪输入空白；附件、完整行解析、稳定定义 ID、变更通知及 DSH 日志需适配。界面当前仅查询全局目录。
- [x] `sessionProjections`：context.session_projections。已验收近似接口；差异：原数据库最新摘要与有限事件页，无扩展投影定义/DSH重放。
- [ ] `sessionProjectionCache`：补齐 sessionProjectionCache 的 Sunday 公开接口或提供方注册。当前边界：尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。
- [x] `skills`：context.skills.register + 清单 skills 与 SkillRegistry。已验收近似接口；差异：静态目录迁移与受管全局内存技能已验收，模型/用户调用策略分别检查。磁盘优先；动态目录、远程 provider、scope、snapshot/invalidate 与 change 事件未覆盖。
- [ ] `agents`：PluginContext 的 sub_agent_runner / run_profile。当前边界：需统一 create/resume/followup/steer/cancel/dispose；保留 Sunday 现有调度权威。
- [x] `agentDefaultModel`：context.models.select(scene) / 场景模型记忆。已验收近似接口；差异：Sunday 按 chat/study/background 场景只读解析，已验收同场景替换和显式错误；不提供 DSH 单一进程默认值、saveSelection 或会话最终选模。
- [ ] `agentLoop`：Sunday 主代理循环。当前边界：不是可直接替换的 Cordis loop；扩展点先映射到现有循环。
- [x] `schedule`：context.schedule + original Arrange Runner。已验收近似接口；差异：原持久任务触发/执行/暂停/取消，固定项目与插件 ID；提醒格式、cron、投递历史与 DSH 不同。
- [x] `goals`：context.goals + original GoalManager。已验收近似接口；差异：持久多目标、固定插件/项目身份及重复创建回执；非 DSH 单会话目标投影、轮数、CAS 引用或续跑激活。
- [ ] `ssh`：补齐 ssh 的 Sunday 公开接口或提供方注册。当前边界：尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。
- [x] `subprocess`：context.processes.spawn/run + lookup/environment。已验收近似接口；差异：Windows Job 原生进程、有限输出与回收；启动到分配存在竞争窗口，无 stdin/raw stdio/control/PTY/远程协议。
- [x] `shell`：context.shell.resolve/execute + owned native processes。已验收近似接口；差异：PowerShell近似，显式期限、有限字节尾及原Job回收；无stdin、onExpiry:none、消费游标、spill、PTY、沙箱或远程后端。
- [x] `shellEnv`：context.shell_env.register/list/collect。已验收近似接口；差异：受管SUNDAY_*声明、每次收集、冲突/撤回与5秒期限；不伪造DSH身份或profile。session_id仅标签，无模型工具自动接线。
- [ ] `terminals`：补齐 terminals 的 Sunday 公开接口或提供方注册。当前边界：尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。
- [ ] `sandbox`：补齐 sandbox 的 Sunday 公开接口或提供方注册。当前边界：尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。
- [ ] `sandboxPolicy`：补齐 sandboxPolicy 的 Sunday 公开接口或提供方注册。当前边界：尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。
- [x] `approval`：context.approvals.request/answer + native tool approval。已验收近似接口；差异：已有活动回合请求、受管单回答者与持久审计；默认缺失不放行。没有前端卡片、waterfall、持久 setPolicy 或 DSH turn-enclosed 编码。
- [x] `permissionPresets`：context.permissions.catalog/read / 既有权限操作。已验收近似接口；差异：已验收固定 Sunday 预设目录和会话偏好只读查询；不返回授权，不改策略。无 DSH sandbox 组合、custom、Auto review 或动态目录。
- [ ] `ptcRuntime`：补齐 ptcRuntime 的 Sunday 公开接口或提供方注册。当前边界：尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。
- [x] `fs`：context.filesystem。已验收近似接口；差异：读取、范围、流、最终链接及条件写入/编辑；本地路径转换与有限元数据轮询监听。1MiB 修改、内容修订与合作路径锁；无原生事件、递归监听、远程后端或完整 DSH 目标身份。
- [x] `compaction`：context.compaction.compact_now / 既有 agent preset compaction。已验收近似接口；差异：已验收桌面空闲会话手动压缩子集，修订冲突、取消、排他与停用租约；无自动/区间 API、持久锁或 DSH 检查点协议。
- [x] `subagents`：context.subagents + original SubAgentSupervisor。已验收近似接口；差异：原监督器/邮箱的具名持久成员create/list/get/message/close及单成员interrupt/resume；固定插件/项目和可见父会话，恢复验证非live提交状态及实际继续执行器。不覆盖共享暂停、目录捕获、DSH activation/外部提供方/完整父子协议。
- [ ] `inspector`：补齐 inspector 的 Sunday 公开接口或提供方注册。当前边界：尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。
- [x] `jobs`：context.jobs.start/get/list/read/wait/kill/remove。已验收近似接口；差异：插件启动代/项目内异步回调作业、有限输出/记录与实际取消join；session仅标签，无DSH控制器、消费读取、通知、持久化或会话ACL。
- [x] `web`：context.web。已验收近似接口；差异：原搜索提供方及HTTP抓取工具的受管SDK，保留原结果/失败；不授予模型审批。
- [x] `spillStore`：context.spill_store.save_text。已验收近似接口；差异：插件/会话标签分组的真实本地UTF-8持久文件及精确字节数；8MiB上限，无自动预览/过期/远程或读取授权。
- [ ] `directoryPicker`：补齐 directoryPicker 的 Sunday 公开接口或提供方注册。当前边界：尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。
- [ ] `webApp`：补齐 webApp 的 Sunday 公开接口或提供方注册。当前边界：尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。
- [x] `lsp`：context.lsp。已验收近似接口；差异：真实受管提供方注册/扩展选择/四类规范查询；语言服务器须另行安装，不伪造结果。
- [ ] `dynamicCordisRunner`：补齐 dynamicCordisRunner 的 Sunday 公开接口或提供方注册。当前边界：尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。
- [ ] `cordisInspect`：补齐 cordisInspect 的 Sunday 公开接口或提供方注册。当前边界：尚未核实同等公开契约；先确认参数、返回值、作用域、取消、权限、错误和卸载行为，再实现。

## 说明

前面 2a–2p 的基础子集验收仍有效，详见 [阶段清单](dsh_compatibility_checklist.md)；这里按整个第二阶段服务范围审计，不默认视为已完全覆盖。阶段 3 的前端/Remote 和阶段 4 的真实插件全面移植不纳入本阶段完成勾选。
