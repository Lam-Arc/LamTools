# 插件宿主重建

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
