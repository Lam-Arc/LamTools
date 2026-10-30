# 插件会话执行目录与检查点入口

user:“继续，把 2 阶段都做完”+(继续补齐持久目录和已有恢复能力，明确插件视图与主代理接线、Sunday事件与DSH事件的差异)。

这是第二阶段 2r 的桌面 Python 近似契约。完整进度仍以 [71项清单](dsh_phase2_completion.md)为准，不能把本文视为整个 workingDirectory/sessionPersistence 服务或 DSH 运行兼容已完成。未改动前端文件。

## 持久执行目录

官方依据：[固定上游工作目录手册](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/session/working-directory/README.zh.md)。DSH 保留原项目身份，当前目录通过会话状态恢复，已有进程保留各自目录；Sunday 本轮先落实插件执行视图的同类边界。

```python
state = await context.working_directory.get(session_id)
state = await context.working_directory.set(
    session_id, "subdirectory", expected_revision=state.revision
)
execution = await context.for_session(session_id)
text = execution.filesystem.read_text("notes.txt", max_bytes=65536)
outcome, output = await execution.processes.run(["python", "worker.py"], timeout=30)
```

get 返回不可变 WorkingDirectoryState(session_id, project_root, path, revision, exists)。project_root 来自会话原 metadata.work_root；path 为持久 metadata.execution_directory，未设置时为原项目根。revision 是原会话的条件写入修订号，**不是** last_event_seq，也不是只针对目录的单独版本。get 复用原可见性，元数据和修订在同一次数据库行读取中取得；不执行旧权限偏好迁移，不刷新运行权限缓存，不激活Agent。

set 的路径可为原项目内相对路径或绝对路径，只允许现有目录，拒绝父级跳转、越界、链接和已观察到的路径重定向。当前近似不允许切到原项目以外，也不把路径选择当作额外授权。必须显式提供非负64位 expected_revision；会话任何并发变更都可能冲突，报 working-directory/conflict，调用方重新读取后自行决定，不自动覆盖。

写入复用 CoreDbSessionStore.patch、原数据库协调器和同步通知；原 work_root/project_id 保持。它是会话级选择，不按插件另建目录状态。更新仍遵守原会话可见性，没有新增按插件划分的会话ACL。读写门面绑定插件启动代，宿主关闭或替换后明确失败。

for_session 每次读取最新持久选择，返回一个固定的 PluginContext 执行视图：work_root 仍是原项目，独立 execution_root 只供 filesystem、processes、shell 和 shell_env 使用。模型目录/调用、配置、持久目标等仍按原项目身份工作。旧文件/进程门面以及已经启动的进程不会随之后的目录变更切换。for_scene 保留执行目录，显式 for_work_root 则重新选择项目并清除执行覆盖；原上下文不被修改。

get 对已删除的当前目录返回 exists=false；for_session 此时拒绝创建新执行视图。显式调用 `await context.working_directory.ensure(session_id, expected_revision=...)` 可在原项目仍存在时恢复原项目根；原项目也缺失则明确失败，不创建新目录、不另选仓库。观察到链接/无效持久状态时拒绝，而非静默修复。使用时的路径检查仍不能抵御敌对并发文件系统替换。

变更提交已开始后，取消会等待原写入收尾，再传播取消；状态可能已保存。其他写入/回执失败可能带 WorkingDirectoryError.may_have_changed=true，此时先get核对，禁止盲重试。稳定错误包括 invalid-id/revision/path/state、not-found、conflict、unavailable、missing、closed、host-changed、operation-failed。

插件代码仍需显式使用for_session；主代理的文件工具/run_command与尾部通知现已按下节2s接通。DSH目录事件回放、项目外目录、远程FS及其他工具的目录行为继续保留差异。

## 主代理接线（2s）

user:“继续”+(主代理使用已保存的执行目录，同时保持项目配置、审批目标和已有进程身份)。

桌面统一工具箱构造路径已安装同一目录服务的读取源。主代理每次构造模型请求（包括纯聊天）前，从原会话行读取当前目录；目录消失时用原修订条件更新恢复原项目，遇并发选择最多重新读取3次，不覆盖更新的目录选择。原项目也缺失则失败。构造工具箱前另做项目存在检查，防止其原有mkdir行为把空目录当成项目恢复；这些路径检查仍不提供敌对并发删除/替换下的原子保证。尚未安装桌面会话服务的CLI继续使用原目录行为。

read_file、write_file、edit_file、list_dir、search_files、search_content 的相对path在模型响应转为工具调用时，以最近一次请求验证的目录固定成绝对路径。run_command新增可选cwd；未提供时固定为该目录，相对cwd也在送审前固定。参数经过原审批流程，审批恢复不重新解释已有绝对目标。因此目录改变后，已经送审的文件调用和命令仍操作原目标；新模型请求产生的调用使用新目录。目录改变发生在模型请求与工具解析之间时，本轮仍使用该请求的目录快照，不作即时重定向。

命令处理器真正以该cwd进行shell选择/路径检查、前台或后台进程启动、预备探测；不修改处理器的项目根、系统进程cwd或已启动的进程。显式cwd限原项目内的现有普通目录，观察到链接或非法目录时在进程启动前报command/invalid-cwd。这不把shell执行变成沙箱；原命令可执行内容与审批权威保持。

初始目录和目录变化进入原运行上下文尾部，以 `Current working directory: <JSON quoted path>.` 表示；未变化不重复追加，压缩后的上下文快照也包含最近已验证值。下一次请求再次验证并补充变化。沿用原tail消息标记与适配器降为用户尾部的规则，不改稳定系统提示词、不改变模型/插件/项目配置根，也不修改历史通知。

2s当时的接线范围限上述文件工具和run_command；专用Git现已按下节2t补齐。MCP、资料库、记忆等继续使用原项目根，子代理保留既有独立执行权威，不要求其运行ID存在于主会话目录表，不自动跟随父会话目录。尚无变更时的即时Agent邮箱通知、DSH目录投影/事件回放或完整跨后端协议。

test_main_execution_directory.py 已验证实际文件读取/写入、真实PowerShell cwd、目录切换后的旧审批目标保持、原系统前缀保持及通知去重、压缩快照、自动恢复与并发选择冲突、原项目缺失不重建、子代理兼容，以及真实工具箱工厂接线。模型请求测试使用真实请求构造器，不调用付费模型。

## 专用Git与其他工具边界（2t）

user:“继续”+(专用Git采用同一请求快照，其他服务保持各自项目/会话身份，不随目录选择串项目)。

git_status/git_diff增加可选cwd，与run_command一样在送审前固定；同一工厂函数覆盖普通和内置插件Git处理器。Git真正以该目录启动，返回metadata.cwd供核对。目录在原项目内且存在，观察到链接或非法cwd时在启动前报git/invalid-cwd。git_diff的path仍相对已固定的cwd解释，非法类型或越界过滤报git/invalid-path；原输出大小、退出码与失败语义保持。

目录切换后，已固定的Git调用继续访问旧目录；旧目录消失则失败，不改投新目录或另一仓库。原Git原生语义仍适用：cwd选择仓库/相对路径基准，不保证status或无path的diff仅展示该子目录，仍可能展示整个仓库。没有修改用户项目的Git索引或提交历史。

| 工具/服务 | 当前目录规则 | 保留的边界 |
| --- | --- | --- |
| 六种文件工具 | 每次请求后的执行目录快照，送审前固定绝对path | 原文件权限与审批流程 |
| run_command | 同一快照固定cwd | 已有进程保持各自cwd；MCP拦截使用原配置 |
| git_status/git_diff | 同一快照固定cwd，diff过滤相对该cwd | 原Git仓库语义，不重新解释旧调用 |
| MCP、技能目录、模型和插件配置 | 原项目根 | 服务发现、依赖、模型路由不随执行目录切换 |
| 资料库、记忆、图像/网页工具的原项目上下文 | 原项目根 | 原成果归属、存储和提供方配置保持 |
| 目标、安排、计划及交互 | 原项目/会话身份 | 不因为执行目录改变而更换持久任务或会话 |
| 子代理 | 原独立执行权威 | 不自动跟随父目录；新持久成员入口见[子代理接口](plugin_subagent_access.md) |

test_git_execution_directory.py 使用两个临时真实仓库验证status/diff及旧调用保持、新调用切换、内置插件处理器、非法参数启动前拒绝和旧仓库消失不回退。Git写入仅发生于测试临时目录，未在用户工作区运行add/commit/reset。

## 原生检查点与恢复

公开 `context.checkpoints.list/create/restore/rollback/fork`，共用现有 session.checkpoints.*、session.rollback 和 session.fork 操作，不创建新存储或恢复管理器。

```python
saved = await context.checkpoints.create(session_id, label="修改前")
checkpoint_id = saved["checkpoint"]["id"]
await context.checkpoints.restore(session_id, checkpoint_id)
forked = await context.checkpoints.fork(
    session_id, checkpoint_id=checkpoint_id, new_session_id="new-session"
)
# 也可选择一个回合边界：fork(..., turn_id=...) 或 rollback(..., turn_id=...)
```

每次先用原只读会话读取检查可见性。list 只读；create/restore/rollback/fork 拒绝运行、等待、暂停或已被运行注册表占用的会话，底层继续使用原操作的准入检查。包装层不新增会话actor锁或跨进程排他保证，检查与操作之间仍沿用原宿主并发边界，不提供新的调用方CAS事务。

restore 只允许对话范围，不暴露 workspace/all 参数；恢复原对话和运行历史，不回退项目文件、成果或外部副作用。fork 必须明确且仅选择 checkpoint_id 或 turn_id；可指定new_session_id及title，否则使用原生生成规则。不能把检查点恢复当作继续中断回合、任意DSH日志追加或重新执行外部工具。

返回原操作payload的有限JSON副本（最多1MiB），不是DSH SessionHandle/Agent。label/title最多256字符，标识符最多256字符。list的底层原查询仍可能一次读全部检查点，包装层只限制返回大小，尚无数据库分页契约。服务、原操作目录或启动代变化后旧门面拒绝调用。

修改调用取消后等待已开始的原操作结束，再传播取消；检查点或新会话可能已提交。失败、拒绝或结果过大返回 CheckpointAccessError（code/details/may_have_changed），不要盲重试分叉；用list或已有会话查询核对。没有新增request_id去重、DSH单写者日志句柄、flush屏障或崩溃重放协议。原检查点恢复的工作目录元数据仍沿用原恢复行为；不存在保证保留最新目录选择的额外合并策略。

## 验收

test_plugin_working_directory.py 覆盖实际SQLite持久化、启动代重建、并发修订冲突、项目身份保留、目录消失后的显式恢复、隐藏会话、关闭/撤回、取消提交收尾，以及真实Windows进程在目录变更后保持原cwd。

test_plugin_checkpoint_access.py 通过原数据库与实际检查点操作验证对话恢复和分叉后的历史内容、文件保持、真实运行注册表拒绝、错误检查点/隐藏会话/撤回，以及取消后实际提交收尾。迁移报告仅给目录方法人工候选，保持 agent-required/runtimeVerified=false；不把DSH持久化open/append/flush映射成这些恢复操作。
