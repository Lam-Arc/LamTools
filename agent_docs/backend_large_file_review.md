# 后端大文件审查与拆分

用户需求：“审查后端大文件并拆分”“拆分后依旧很大”“你尽可能的做好，避免后续再次为这部分拆分工作”。

## 完成范围

本轮完成三个已审查大文件的职责拆分。它们现在保留兼容导入入口，业务实现进入各自的职责模块。此前提取的历史分页、模型客户端、命令报告和工作流数据模型继续保留。

| 文件 | 本轮前 | 当前 | 实现位置 |
| --- | ---: | ---: | --- |
| `app/live_operations.py` | 6,953 行 | 318 行 | 同目录 `live/` |
| `cli.py` | 5,627 行 | 349 行 | 同目录 `cli_commands/` |
| `plugins/bundled/workflow/backend/runtime.py` | 5,801 行 | 269 行 | 同目录 `runner.py`、`runner_*.py`、`models.py` |

三个入口合计减少 17,445 行。新实现中最大的文件为 `cli_commands/task.py`（708 行），工作流状态宿主 `runner.py` 为 511 行。行数包含注释和空行。

## 会话操作：app/live/

| 模块 | 职责 |
| --- | --- |
| `context.py`、`dispatch.py` | 共享上下文、宿主、结果类型和操作注册 |
| `params.py`、`events.py`、`background.py` | 参数校验、持久化事件边界、后台收尾任务的所有权 |
| `threads.py`、`turn_start.py`、`turn_options.py` | 会话读取、回合接收/续接、冻结的运行选项 |
| `turn_pause.py`、`turn_cancel.py` | 可恢复暂停、终止、强制重置和相应收尾 |
| `approvals.py`、`interactions.py`、`continuations.py` | 审批决策、交互生命周期、持久化续接任务 |
| `queue.py`、`queue_dispatch.py`、`steering.py` | 队列变更、下一条输入派发、运行中指导 |
| `runtime_tasks.py`、`terminal_state.py`、`recovery.py` | 启动与完成、终态持久化、启动恢复 |
| `commands.py`、`attachments.py`、`processes.py`、`permissions.py` | 命令、附件、后台进程和权限操作 |

历史分页继续由 `app/thread_history.py` 负责。实现不反向导入兼容入口。控制与续接的交叉调用，在调用处明确导入，避免初始化阶段的循环依赖。

## 命令入口：cli_commands/

| 模块 | 职责 |
| --- | --- |
| `entry.py`、`parser.py`、`parse_*.py` | 入口退出处理、组合注册与插件命令、按用途注册参数 |
| `connection.py`、`config.py` | 连接清理、共享参数校验、模型存储上下文和资源路径 |
| `task.py`、`sessions.py`、`server.py` | 本地任务/事件观察、会话操作、服务与维护 |
| `agents.py`、`library.py`、`plugins.py` | 子代理与安排、项目与计划库、插件与技能 |
| `settings.py`、`preferences.py`、`resources.py`、`office.py` | 配置、偏好、资源、文档服务 |

原先 1,260 行的 `build_parser` 改为组合注册函数。命令的参数、默认值、选项和处理函数保持一致。模型网络实现由 `llm/http_client.py` 负责，统计和脱敏由 `cli_reporting.py` 负责。

## 工作流：plugins/bundled/workflow/backend/

| 模块 | 职责 |
| --- | --- |
| `models.py`、`runner_context.py`、`runner_state.py` | 图/结果模型、执行上下文/领域错误、活动记录/协调锁 |
| `runner.py` | 持有服务依赖与运行状态，保留原方法签名、文档和覆盖入口 |
| `runner_run.py`、`runner_scheduler.py` | 运行生命周期、互斥认领、图调度 |
| `runner_admission.py`、`runner_attempts.py` | 流控租约、持久化认领、节点重试与缓存策略 |
| `runner_signals.py`、`runner_persistence.py`、`runner_cancellation.py` | 等待与恢复、快照与事件、取消感知等待 |
| `runner_ai.py`、`runner_data_nodes.py`、`runner_expansion.py` | 模型/代理节点、数据节点、动态展开/子工作流 |
| `runner_process_nodes.py`、`runner_process.py` | 权限门后的命令/脚本节点、进程和环境处理 |
| `runner_graph.py`、`runner_validation.py`、`runner_expressions.py` | 图数据绑定、验证、表达式 |
| `runner_authority.py`、`runner_security.py`、`runner_values.py`、`runner_manager.py` | 授权边界、凭据、数据转换、定义管理 |

执行服务显式接收运行宿主，状态由 `WorkflowRunner` 统一持有。没有引入多重继承、动态执行源码或向模块全局注入依赖。原方法保留薄委托，已有嵌入方的实例覆盖入口继续可用。

## 防止重新集中

- 三个兼容入口不再添加业务实现。新功能放入对应职责模块，新调用优先引用所属模块，已有调用仍可使用原入口。
- 本次拆分模块最多 1,000 行，单个函数最多 600 行；验收检查会阻止重新集中成大文件。
- 新模块不得反向导入 `cli.py`、`live_operations.py` 或工作流 `runtime.py`。
- 回合状态由宿主和持久化边界维护；工作流状态由运行宿主持有，不在各执行服务中复制。
- 命令契约摘要固定了拆分前的全部选项、默认值及处理函数；有意调整命令时应同步更新检查。

## 验收

仅运行本次新增的 `core/tests/test_backend_module_split.py`、`core/tests/test_backend_deep_split.py`：**37 项通过**。

覆盖全部命令参数、连接清理、配置入口、资源路径、类型信息、宿主派发、忙碌保护、队列幂等增改删、中文分页、附件引用与脱敏、模型普通/流式回复；真实数据库中的回合暂停和停止同时核对快照、运行状态与认领释放；工作流调度、重试、取消清理、新存储实例恢复等待状态、并发恢复去重、嵌套工作流、进程启动前权限拒绝、实际 Python 脚本进程的数据流。另有文件/函数大小及依赖方向检查。

将 465 个迁移实现与本轮开始时的工作区快照比较：去除导入位置、方法接收参数命名、文档缩进差异后，业务实现一致。单独验证了重组后的命令契约，以及两个随目录移动调整的资源根路径。未运行全量测试，未进行界面或外部模型服务验证。

## 其他大文件盘点

以下文件不在本轮三个模块的修改范围，保留已有工作区内容。行数为此前盘点记录，不能视为已完成拆分：`kernel/loop.py`（4,943）、`runtime-rs/src/provider.rs`（4,493）、`app/default_agent.py`（3,760）、`runtime-rs/src/study.rs`（3,607）、`app/core_db.py`（2,978）、`checkpoint.py`（2,582）、`app/http_agent_app.py`（2,541）、`tool/default_toolbox.py`（2,451）、`sub_agent_supervisor.py`（2,449）、`runtime-rs/src/workflow_document.rs`（2,435）、`runtime-rs/src/lib.rs`（2,388）、`llm/profiles.py`（2,363）。

## a3 打包记录（2026-10-25）

user:“最近的改动，如果需要更新 wiki 的话，一并更新，比如说分屏还有一些文件的拆分，你看看有没有必要写”+(用户功能写入 Wiki，内部模块边界留在维护文档)。

文件职责拆分本身不作为用户功能新增 Wiki 词条；分屏、主聊天助手、MCP 查询与命令执行、按操作分级和精确信任属于可见行为，分别记入分屏、MCP、审批、命令和相关导航词条。a3 的本地打包从当前工作树收集这些拆分模块，不仅收集 Git 已跟踪文件。

后续新增的 MCP 命令与信任命令位于 `cli_commands/mcp.py`、`cli_commands/trust.py`，协议与本机路径解析位于 `mcp/`；按操作等级、信任账和审批仍各由对应模块负责。原有拆分验收数字是当时的检查记录；本次命令契约有意新增 MCP 与信任入口，其行为由本次新增验收覆盖。
