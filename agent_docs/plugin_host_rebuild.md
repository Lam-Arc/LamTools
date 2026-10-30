# 插件宿主重建

新增实际运行能力与生命周期限制见 [第二阶段运行接口](plugin_phase2_runtime.md)；逐服务完成状态见 [71 项清单](dsh_phase2_completion.md)。最新公开接口包括条件文件修改、受管进程/PowerShell、环境贡献、后台作业、长文本保存、模型调用、持久任务、会话查询、后端审批和管理入口。

会话执行目录与原项目根分开保存，插件用for_session取得固定执行视图；检查点恢复仍走原操作，详见 [目录与恢复接口](plugin_session_recovery.md)。

具名子代理通过[context.subagents](plugin_subagent_access.md)使用原监督器和持久邮箱；插件停用撤回门面，已接受成员继续归原父会话所有。专用Git现与文件/命令工具采用相同的送审前目录固定规则。

2v增加单成员中断和已提交状态继续：原会话级暂停信号保持共享，不冒充单成员暂停；继续前验证提交状态及实际持有执行器，禁止恢复时退回全新运行。

user:“该重建就重建，到时候你试验的话，可以去复刻一下DSH的bill scroll这个插件，并完成验证，该调的模块就是该写的东西，都试一试，对比原版，能力应当只增不减”

## 架构

`PluginSupervisor` 是后端实例、状态、调用租约、代际与资源清理的唯一持有者。旧 `V2RuntimeManager` 仅为兼容别名。宿主上下文按宿主实例取得，同名多宿主不共享插件模块或状态。

安装/更新/启停/卸载全部经过 `management.py`：验证清单和本次插件冲突 → 撤销可用性 → 等待正在执行的调用 → 关闭 MCP 和后端 → 替换代码 → 验证新后端 → 重挂操作目录。旧 `plugin.*` 转发 `plugin.system.*`。操作、工具、命令、界面、资源和 MCP 共用就绪门；旧工具箱还要验证代际，不能继续调用旧代码。

`loading.py` 为每个插件根建立模块命名空间；跳过陈旧 pyc，更新统一失效。`storage.py` 在同盘准备代码，保留旧目录，启动成功才提交；启动失败、取消或文件占用恢复旧版本。原子事务账本支持进程退出后的恢复，已提交版本只延后旧目录清理。插件数据独立保存在 `plugin-data/<name>`，Windows junction 兼容原 `data/` 路径，默认卸载保留数据。

boot 尊重 `defaultEnabled:false`。安全模式不加载后端；不可替换恢复内核名单由 boot 与运行时共享。启用意图与实际可用状态分别展示，失败保留诊断并可重试；失败后配置退回默认表单，便于修复。

## 界面与窗口

区域与分屏统一 `mount(root, context)`、清理函数及 AbortSignal。独立窗口经 `/api/core/plugin-system/{plugin}/rpc` 调用真实操作目录与审批；不能随意调用其他插件操作。涉及模块覆盖、全局脚本及浏览器依赖模块缓存时提示重启，不承诺任意模块图热替换。

## MCP 与值班轮

MCP 注册表归属宿主，停用/更新前排空并关闭子进程。主代理与子代理均接入。通用路径模板支持 `PLUGIN_DIR`、`PLUGIN_DATA_DIR` 和插件 Python 环境，配置不写入本机路径。

bili-scroll 保留上游 2.2.2 的 34 个 MCP 工具，宿主业务重写为 Python/asyncio。值班运行档只有 `mcp`；执行侧补评论、私信、回复和额度闸。插件功能与验证边界见 `plugins/bili-scroll/差异表.md`。

## 取舍与边界

<!-- user:“宿主能力补齐和接口完善与文档更新”+(配置快照与原管理入口共用持久化，不建立虚假的自动应用结果)。 -->
[配置访问 v1](plugin_config_access.md)使用 context.config.read/validate/replace，绑定清单与启动代，SDK 强制内容修订检查并复用原内置/第三方路径。管理入口和旧内置 writer 共用文件锁；保存明确 applied=false，不执行自动重启或回滚。基础校验、无分层/volatile/脱敏投影的边界见契约；旧界面修订号接线留到前端统一处理，本批未改样式文件。

<!-- user:“宿主能力补齐和接口完善与文档更新”+(凭据复用原加密文件，受管门面撤回，状态查询不读取明文)。 -->
[凭据引用 v1](plugin_credentials.md)提供 context.credentials.resolve/describe/set/unset。原 secrets 文件按操作重读，合作进程通过文件锁串行读改写；坏文件不清空，失败写入不留内存假状态。新门面绑定 owner/启动代，describe 只返回元数据；环境回退、授权记录和更新事件未实现，旧原始 secrets 视图的生命周期行为保留。

<!-- user:“宿主能力补齐和接口完善与文档更新”+(插件 JSON KV 复用现有数据身份，事务失败和启动失败的持久状态语义明确)。 -->
[插件存储 v1](plugin_storage_access.md)通过 context.storage 提供同步 JSON KV，文件放在原稳定 plugin-data 目录。SQLite 提供条件 revision、原子提交与锁协调；提交确认不确定隔离句柄，启动失败不回滚已提交业务状态。类型化领域、多后端路由和变更通知尚未实现；配置/凭据继续使用原专门服务。

<!-- user:“宿主能力补齐和接口完善与文档更新”+(模型目录视图固定当前项目和启动代，选择保留原场景权威且只读)。 -->
[模型访问 v1](plugin_model_access.md)使用 `context.models.list/resolve/select`，固定项目视图并区分记录 ID 与上游 ID；场景查询复用原 chat/study/background 选择器，不跨场景猜测，也不写配置或发模型请求。适配器、流协议、全局默认写入与子助手获准路由政策未覆盖。

<!-- user:“宿主能力补齐和接口完善与文档更新”+(全局内存技能共享原发现和加载路径，停用撤回且不授予文件目录权限)。 -->
[内存技能 v1](plugin_skill_extensions.md)使用 `context.skills.register`，复用原 SkillRegistry、模型 load_skill、用户展开和管理目录。model/user 两个调用开关独立检查，主/子助手与克隆共享禁用账本；内存项无文件路径，不能通过文件删除或加载取得额外目录授权。动态文件挂载、远程 provider、scope 层级及 change/invalidate 协议尚未实现。

<!-- user:“宿主能力补齐和接口完善与文档更新”+(动态命令与原命令目录/动作执行保持同一入口，撤回后不能落到旧处理器)。 -->
[动态命令 v1](plugin_command_extensions.md)使用 `context.commands.register`，复用 `command.catalog/execute` 和 live 分派，支持受管启停、会话覆盖、调用排空与取消。当前文本输入保留 Sunday 的空白裁剪；界面会话目录、附件、稳定定义 ID、change 通知和 DSH 专用日志格式未覆盖。

<!-- user:“宿主能力补齐和接口完善与文档更新”+(提示词与插件启动代共用所有权，失败回退未修改的内置结果)。 -->
[提示词扩展 v1](plugin_prompt_extensions.md)通过 `context.prompts` 提供受管 section、variable 和 assemble 钩子，显式匹配会话/agent_id。所有变换在副本上组装，异常或结构损坏不会污染内置提示词。当前仅同步追加基础子集，不含 DSH complete、动态上下文、抑制/刷新和 change 事件；错误时沿用 Sunday 的日志与回退策略。

<!-- user:“宿主能力补齐和接口完善与文档更新”+(动态工具复用同一个生命周期、工具箱和审批权威)。 -->
[动态工具与钩子 v1](plugin_tool_extensions.md)通过 `context.tools` 提供受管注册、工具集收窄、最终守卫及 pre/post/result 子集。主/子代理共用装配路径，停用撤回、调用排空、旧审批令牌隔离；默认按数值等级 3 审批。复杂 schema、参数改写、动态 ask 和 execute/waterfall 尚未实现。

<!-- user:“每一个地方 sunday 都有等价或者近似接口”+(DSH 兼容复用本宿主权威，按契约与行为分阶段验收)。 -->
DSH 对齐与迁移入口见 [兼容实施说明](dsh_compatibility.md)和[逐项能力对照](dsh_compatibility_matrix.md)。第一阶段提供宿主能力发现和静态迁移准备；同名服务的运行兼容仍需后续逐项实现，不改变本页的 supervisor、审批和代际权威。

第二阶段 2a 已将[受管服务注册、依赖引用与清理](plugin_owned_services.md)接到原有生命周期：健康检查通过后公开服务，撤回后排空调用，逆序清理已登记资源。服务注册 epoch 是启动实例身份，不替代代码更新 generation；会话和工具等具体能力仍按后续批次补齐。

第二阶段 2b 的[桌面会话控制](plugin_session_control.md)已公开为 SESSIONS v1。它先于插件 start 就绪，复用 live 接收与持久事件；提供新建、文本队列/引导、取消、状态、历史与等待。项目/preset 绑定、附件、完整 Agent 工厂和动态工具仍未由该批次覆盖。

现有桌面插件、操作和工具都在同一 Python 事件循环。先统一权威，避免再造一份 Rust 状态表；代码与数据事务已独立，后续可下沉 Rust。插件仍是受信任的本机代码，不将此生命周期重建描述为进程安全隔离。

仅面向桌面。未发布、未替换用户当前安装。后续用户明确授权后，已完成一次真实评论/私信/收藏验证并回读。验收结果见 [验收报告](plugin_host_rebuild_acceptance.md)。本页更新旧生命周期文档中的状态与管理流程；不改变需要重启的模块覆盖边界。

## 2k 固定目录只读文件子集

user:“每一个地方 sunday 都有等价或者近似接口”+(文件能力以明确的近似契约提供，避免冒充完整提供方)。

受管插件可取得 context.filesystem；root/stat/read_bytes/read_text/list_dir 固定工作目录与启动代。复用工作目录路径规则并显式拒绝越界和观察到的重解析点，读取限 1 MiB、目录列表限 1000 且返回截断标记。它是同步可信插件便捷 API，路径检查与打开不是原子安全隔离，无截止时间或快照。没有 DSH FsTarget、写入、监听与会话目录持久化。详见 [接口与移植差异](plugin_filesystem_access.md)。

## 2l 手动会话压缩

user:“每一个地方 sunday 都有等价或者近似接口”+(手动压缩用已存在的桌面命令，而不是第二套压缩状态机)。

context.compaction.compact_now 接到 compaction_control，由桌面会话宿主一并安装，不覆盖旧 preset compaction。固定目录与启动代，要求空闲已知会话和显式事件流修订号；沿用运行认领、控制事件、实际摘要与运行存储。停用等待已接收调用结束。错误带 may_have_changed，不自动重试或回滚；没有持久锁、跨存储事务、区间压缩或自动策略注册。详见 [手动压缩契约](plugin_compaction_access.md)。

## 2m 权限目录与会话偏好读侧

user:“每一个地方 sunday 都有等价或者近似接口”+(权限预设只读侧使用真实会话来源，与实际批准流程保持明确边界)。

context.permissions.catalog/read 经 permission_access 暴露现有 Sunday 目录及会话偏好解析；会话存储 get_readonly 保持可见性且不迁移旧数据。原 get 的迁移和缓存行为保留。返回不可变视图，免问线和基础上限分开，既不授权操作也不切换策略。异步读取受启动代租约约束，宿主关闭/存储替换后拒绝旧读侧。没有 DSH Auto review、一次性审批 request、sandbox 组合或预设贡献协议。详见 [权限读取](plugin_permission_access.md)。

## 2n 程序解析和环境构造

user:“宿主能力补齐和接口完善与文档更新”+(公开进程基础子集，完整进程运行与回收另行验收)。

context.processes 提供受管启动代内的本地 resolve_executable/environment，同步操作不启动进程，不返回运行句柄。查找只用 PATH 绝对目录及 Windows PATHEXT，有条目上限；环境采用名称过滤、显式覆盖和总量限制，返回不可变副本。没有 DSH 远程世界、代理特殊覆盖、标准流或终端。完整运行、取消和受管范围退出证明仍未完成。详见 [进程基础接口](plugin_process_access.md)，状态按 [清单](dsh_compatibility_checklist.md)勾选。

## 2o 文件窗口读取与链接元数据

user:“宿主能力补齐和接口完善与文档更新”+(扩展原只读文件门面，保持目录/启动代和不穿透上级链接的约束)。

filesystem v2 增加 read_byte_range 和 lstat。前者直接定位后按最多 1 MiB 窗口读取原始字节；后者允许最终链接本身的元数据查询，但根/中间链接仍被拒绝。原 stat/read/list 语义保留。路径检查不是原子安全边界，没有快照、取消或 I/O 截止时间。写入/编辑、流、监听和远程后端继续未完成。详见 [文件接口](plugin_filesystem_access.md)。

## 2p 有界文本流

user:“宿主能力补齐和接口完善与文档更新”+(流式文本不增加长期打开资源，部分结果与完整验证必须明确区分)。

filesystem v3 的 stream_text 是有限同步迭代器：总量最多 64 MiB，单次读最多 64 KiB，跨块 UTF-8 解码，yield 时不持有文件句柄。每次恢复迭代检查启动代及文件身份/大小/修改时间，检测普通变化；不承诺原子快照。尾部异常可在合法前缀之后出现，调用方须正常耗尽才算完整验证。详见 [文件契约](plugin_filesystem_access.md)。
