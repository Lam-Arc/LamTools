# 01 - Core 入口与运行链路审计

## 主验收结论

Core 的真实工具循环已经存在，核心是 `CoreLoopKernel + RuntimeKit`；但 Core 对外入口没有统一。当前只有 `core.cmd run` 走 Kernel，`AgentApp` 和 `/api/core` 是平行路径。

## 当前入口

| 入口 | 当前作用 | 验收判断 |
|---|---|---|
| `core.cmd` | Windows 根命令，转发到 `scripts/core.cmd`。 | 薄封装。 |
| `scripts/core.cmd` | 设置 Python 路径并运行 `lamtools_core.cli`。 | 薄封装。 |
| `core run` | 调用 `run_core_cli_task`，创建 `CoreLoopKernel`。 | 真实 Kernel 路径，但工具很薄。 |
| `CoreLoopKernel` | 模型调用、工具解析、工具执行、状态保存、事件发出。 | 应成为唯一基础 Agent 路径。 |
| `AgentApp` | 单轮模型输出 + user/assistant/status 事件。 | 平行路径，不执行工具循环。 |
| `create_core_agent_operations` | 注册 `turn.start` / `approval.respond`。 | `turn.start` 走 AgentApp，`approval.respond` 是占位。 |
| `/api/core` | session/message/event/provider/usage CRUD。 | 管理面，不是 Agent run 面。 |

## 证据

- CLI Kit 只内置 `write_document`：`core/src/lamtools_core/cli.py:185`、`core/src/lamtools_core/cli.py:194`。
- CLI 创建 Kernel：`core/src/lamtools_core/cli.py:384`。
- CLI 使用内存状态：`core/src/lamtools_core/cli.py:387`。
- CLI 只提供 `run` 参数面：`core/src/lamtools_core/cli.py:505`。
- `AgentApp` 是独立类：`core/src/lamtools_core/app/agent_app.py:75`。
- `turn.start` 由 default agent 注册：`core/src/lamtools_core/app/default_agent.py:79`、`core/src/lamtools_core/app/default_agent.py:117`。
- `approval.respond` 返回占位错误：`core/src/lamtools_core/app/default_agent.py:110`。
- HTTP factory 只挂 `create_core_router()`：`core/src/lamtools_core/app/factory.py:111`、`core/src/lamtools_core/app/factory.py:113`。

## 已实现但未接线

- Kernel 已有审批等待点，但 Core operation 没有真正恢复等待态。
- Kernel 已有 `hook_engine`，但 Core CLI 不传。
- Kernel 已有 runtime part、thinking、tool started/finished 等事件；AgentApp 只产简单 RunItemEvent。
- LoopPolicy 支持超时、重试、并行工具、上下文压缩等；这些没有作为 Core 基础 Agent operation 统一暴露。

## 接线建议

1. 废止 `AgentApp` 作为真实运行路径，保留为测试/轻量 contract 或迁移到 Kernel 装配层。
2. `create_core_agent_operations("turn.start")` 改为调用统一 `CoreAgentRuntime.run_turn`。
3. `approval.respond` 接入 Kernel pending approval 恢复；如果暂不实现，不应暴露成假入口。
4. CLI 不再私有装配 CLI-only Kit，而是调用同一 operation。
5. HTTP 增加 operation endpoint，至少支持真实 `turn.start`。

## 验收用例

- 用 Core CLI 跑一个需要两轮工具调用的任务，确认进入 `CoreLoopKernel`。
- 用 HTTP operation 发 `turn.start`，确认不是只创建 session/event。
- 制造一个 `requires_approval` 工具调用，确认 `approval.respond` 能恢复并继续 loop。

