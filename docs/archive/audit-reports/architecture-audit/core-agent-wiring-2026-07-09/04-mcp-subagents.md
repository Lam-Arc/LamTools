# 04 - MCP / SubAgent / 外部扩展审计

## 主验收结论

Core 已有 MCP 调用包装、插件 MCP 文件发现、SubAgent 定义解析和写入范围校验；但可运行的 MCP registry/client/config 和 SubAgent runtime 仍在 Writer。也就是说 Core 有“协议碎片”，没有完整运行装配。

## Core MCP 现状

Core 已有：

- `MCPToolCaller` 协议。
- `execute_mcp_tool_call`。
- `mcp_tool` 和 `mcp__*` 两种调用形态。
- 参数清洗和 MCP result 格式化。
- plugin manifest 中的 `mcp_files` 路径发现。

证据：

- `core/src/lamtools_core/tool/mcp_tools.py:10`。
- `core/src/lamtools_core/tool/mcp_tools.py:25`。
- `core/src/lamtools_core/plugins/models.py:22`。
- `core/src/lamtools_core/plugins/registry.py:91`。
- `core/src/lamtools_core/plugins/operations.py:31`。

Core 缺少：

- `MCPServerConfig` / `MCPTool` 模型。
- stdio MCP client。
- MCP registry。
- config loader。
- `tools/list`、`tools/call`。
- lifecycle close。

这些现在在 Writer：

- `members/writer/backend/app/core/mcp/config.py:12`。
- `members/writer/backend/app/core/mcp/client.py:32`。
- `members/writer/backend/app/core/mcp/registry.py:15`。
- `members/writer/backend/app/core/writer/runtime_resources.py:185`。

## Core SubAgent 现状

Core 已有：

- `SubAgentDefinition`。
- frontmatter 解析。
- 渲染、写入、删除 `.lamtools/agents/{name}.md`。
- 写入范围判断和冲突判断。
- 子会话状态引用。

证据：

- `core/src/lamtools_core/tool/sub_agent.py:16`。
- `core/src/lamtools_core/tool/sub_agent.py:40`。
- `core/src/lamtools_core/tool/sub_agent.py:106`。
- `core/src/lamtools_core/tool/sub_agent.py:208`。
- `core/src/lamtools_core/sub_session.py:28`。

Core 缺少：

- AgentRegistry。
- AgentRuntime。
- agent definition loader 对项目/插件/用户目录的统一加载。
- sub agent 工具执行器。
- 嵌套 Kernel runner。

这些现在在 Writer：

- `members/writer/backend/app/core/writer/agent_runtime.py:227`。
- `members/writer/backend/app/core/writer/agent_runtime.py:246`。
- `members/writer/backend/app/core/writer/agent_runtime.py:487`。
- `members/writer/backend/app/core/writer/core_kernel_adapter.py:395`。
- `members/writer/backend/app/core/writer/core_kernel_adapter.py:440`。

## Writer 当前补接

- Writer 负责 MCP config：环境变量、工作区配置、内置 Playwright MCP。
- Writer 负责 MCP client/registry/lifecycle cache。
- Writer 在模型请求中追加 MCP 动态工具。
- Writer 在执行时路由 `mcp_tool/mcp__*`。
- Writer 负责 AgentRuntime 和嵌套 CoreLoopKernel。

## 仍应留在 member 的部分

- Writer persona。
- Writer 静态 prompt。
- Writer 工具清单和默认启用策略。
- Writer workspace factory。
- Writer UI 能力展示。
- `delegate_to_member` 这类产品路由。

## 接线建议

1. MCP 下沉到 Core：把 Writer 的 `schemas/client/registry/config loader` 泛化到 Core。
2. Core MCP registry 输入：项目根、显式 config 文件、插件 `mcp_files`、默认禁用/启用策略。
3. Core MCP registry 输出：模型工具定义、`call()`、`close()`。
4. 插件 `mcpServers` 从“可发现”接到“可运行”。
5. AgentRuntime 下沉到 Core，但 runner、LLM client、工具清单和 member persona 作为依赖注入。
6. 插件 `agents` 从“可发现”接到可加载的 agent definition registry。

## 优先级

- P0：Core 化 MCP registry/client/config loader。
- P0：Core 化 AgentRuntime/AgentRegistry，并修正项目 SubAgent definition 被运行时忽略的问题。
- P1：插件 `mcpServers/agents` 接入运行时。
- P1：Writer 集成测试覆盖 MCP 动态工具追加、调用、关闭，以及 sub_agent 嵌套 Kernel。
- P2：整理 UI/设置页展示。

## 验收用例

- Core 用假 MCP server 从 config/plugin 加载工具、调用工具、关闭进程。
- `.lamtools/agents/*.md`、插件 agents、用户 agents 能统一加载。
- `sub_agent` 执行必须经过注入的 Kernel runner。
- Writer 只传路径、LLM client、工具策略和 UI 映射，不再维护 MCP runtime 主体。

