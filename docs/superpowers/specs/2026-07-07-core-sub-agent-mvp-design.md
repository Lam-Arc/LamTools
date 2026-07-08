# Core Sub Agent MVP Design

日期：2026-07-07

## 背景

当前 Writer 子代理已有嵌套运行主循环的雏形，但外层混入了命名角色、工具白名单、写入范围、隔离工作区、分支交付、并行冲突检查和项目配置文件。MVP 目标是先验证“主会话委托可复用子会话”这件事，不继续扩展旧复杂度。

成熟方案对照：

- OpenAI Agents 的核心经验是由运行时负责 agent loop、tools、sessions 和 handoff，产品层只提供业务配置。
- Claude Code subagents 的核心经验是独立上下文、工具/模型可配置、结果回传主会话；但 MVP 不引入多角色配置和并行工作区。

## 产品目标

Writer 运行中可以把一个任务委托给 sub agent。sub agent 是一个由 Writer 操控的可复用 sub session，不是一次性文本调用。

验收标准：

- Writer 可以调用 `sub_agent` 完成一个聚焦任务，并收到可读 handoff 结果。
- 同一个父会话内，同名 agent 再次被调用时继续同一个独立上下文。
- 不同 agent 名字对应不同独立上下文。
- Core 为 agent 隐式分配稳定编号 `001`、`002`，用于日志、事件和排查。
- sub agent 使用与主体等同的工具和权限，但不能继续调用 `sub_agent`。
- MVP 不暴露并行 sub agent，不做 lock、queue、冲突检测、工作区隔离、branch 交付、`write_scope` 或角色模板。

## MVP 语义

`sub_agent` 是主会话调用的普通工具。主循环没有并行 sub agent 能力，因此同一轮只按现有工具执行路径运行它，不新增并发治理。

调用输入只保留最小必要项：

- `task`：委托任务。
- `agent` / `name`：可选，Writer 自己取名；用户不管理。
- `model`：可选，Writer 显式指定本次 sub session 使用的工作模型。

如果没有 agent 名字，Core 使用默认名字 `sub`。编号只在父会话内稳定递增，不跨父会话全局共享。

示例：

```text
parent session A
  001 repo_reader -> sub session A/sub/repo_reader
  002 test_fixer  -> sub session A/sub/test_fixer
```

再次调用 `repo_reader` 时继续 `001` 的上下文。

## 架构分工

Core 负责通用能力：

- 创建和复用 sub session。
- 管理 `parent_session_id + agent_name -> sub_session_id + agent_index` 映射。
- 复用现有主循环运行 sub session。
- 生成子会话可见工具列表：主体工具减去 `sub_agent`。
- 生成通用 handoff 输入和结果元数据。
- 转发或标记事件，让日志能按父会话、子会话、编号查询。

Writer 负责薄适配：

- 在模型提示里允许 Writer 自行选择 agent 名字。
- 提供 Writer 的 Kit、模型解析、工具执行、状态存储和事件出口。
- 把 sub agent 结果作为普通工具结果交回主 Writer。

Core 不写 Writer persona、Writer 专用工具策略、产品 UI 逻辑或 provider 业务判断。

## 复用策略

优先复用现有主循环和 Writer Kit：

- sub session 仍跑同一套 Core 主循环。
- 工具执行复用主体当前 executor，只在 sub session 的模型工具表里移除 `sub_agent`。
- 权限判断复用主体权限配置，不新建子代理权限层。
- 状态存储优先复用现有 runtime state store 的 session_id 机制。
- 事件投影优先复用现有 Core event 结构，只补充 sub session 标识。

旧实现中以下能力不进入 MVP 路径：

- `default` / `explorer` / `worker` / `reviewer` 多角色定义。
- `.lamtools/agents`、`.writer/agents`、`.claude/agents` 定义加载。
- 子代理工具白名单。
- `write_scope`。
- git worktree / branch delivery。
- 并行 scope 冲突检测。

## 模型路由

MVP 只支持 Writer 在调用时显式传入模型，或走默认 sub agent 模型路由。

优先级：

1. 调用参数里的 `model`。
2. 通用 `sub_agent` 路由配置。
3. 主 Writer 模型。

不做基于角色、能力标签或 agent 名字的复杂自动路由。

## 错误处理

MVP 错误只需要清晰可恢复：

- sub session 运行失败：返回失败原因、agent 编号、agent 名字、sub session id。
- 模型不可用：按现有模型 fallback 规则处理，或返回配置错误。
- 工具不可用：沿用主循环工具错误格式。
- 子 agent 试图调用 `sub_agent`：工具不可见；如模型仍构造出来，返回“不可用工具”。

## 测试计划

先写失败测试，再实现：

- Core：同名 agent 复用同一个 sub session 和编号。
- Core：不同 agent 名字获得不同 sub session 和递增编号。
- Core：sub session 工具表继承主体工具但移除 `sub_agent`。
- Core：sub session 通过同一主循环运行并返回 handoff 结果。
- Writer：`sub_agent` 工具调用走 Core sub-session runner，而不是旧角色定义路径。
- Writer：不再要求 `write_scope`。
- Writer：`sub_agent` 不进入并行工具名单。

## 非目标

- 不做并行 sub agent。
- 不做锁、队列、冲突检测。
- 不做工作区或分支隔离。
- 不做 UI 配置页。
- 不做用户显式管理 agent。
- 不做多角色模板。
- 不做能力标签自动模型路由。
