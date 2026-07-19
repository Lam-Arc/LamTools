# 02 - Core 工具箱与权限审计

## 主验收结论

Core 已经有通用工具协议、文件工具、命令工具、Git/Web 工具、MCP 包装、verification 和审批判断；但 Core 没有默认工具箱装配层。当前 Core CLI 只暴露 `write_document`，Writer 仍在重复维护通用工具 schema、权限表和部分执行接线。

## Core 已有工具能力

| 能力 | 现状 |
|---|---|
| 工具协议 | `ToolSpec`、`ToolCall`、`ToolResult`、`ToolRegistry` 已有。 |
| 文件 | 读文件、列目录、搜文件、搜内容、写文件、编辑文件、路径边界校验。 |
| 命令 | `run_command`、`run_tests`，含超时、后台服务 readiness、输出 artifact。 |
| Git | `git_status`、`git_diff`，没有危险写操作。 |
| Web | `web_search`、`web_fetch`、`browser_check`。 |
| MCP | `execute_mcp_tool_call` 包装。 |
| Verification | 写文件/HTML 引用结果验证。 |
| SubAgent 辅助 | 定义解析、写入范围检查。 |

## 证据

- 工具协议和注册表：`core/src/lamtools_core/tool/__init__.py:11`、`core/src/lamtools_core/tool/__init__.py:33`、`core/src/lamtools_core/tool/__init__.py:152`。
- 文件工具：`core/src/lamtools_core/tool/workspace_files.py:76`、`core/src/lamtools_core/tool/workspace_files.py:328`、`core/src/lamtools_core/tool/workspace_files.py:429`。
- 命令工具：`core/src/lamtools_core/tool/command_tools.py:55`、`core/src/lamtools_core/tool/command_tools.py:324`。
- Git 工具：`core/src/lamtools_core/tool/git_tools.py:20`、`core/src/lamtools_core/tool/git_tools.py:37`。
- Web 工具：`core/src/lamtools_core/tool/web_tools.py:30`、`core/src/lamtools_core/tool/web_tools.py:149`、`core/src/lamtools_core/tool/web_tools.py:206`。
- MCP 包装：`core/src/lamtools_core/tool/mcp_tools.py:25`。
- verification：`core/src/lamtools_core/tool/verification.py:10`。

## Core 入口实际可用工具

Core CLI 当前只暴露 `write_document`：

- tool spec：`core/src/lamtools_core/cli.py:194`。
- 模型请求只带 `write_document`：`core/src/lamtools_core/cli.py:228`。
- 第一轮强制调用：`core/src/lamtools_core/cli.py:256`。
- 执行器拒绝其他工具：`core/src/lamtools_core/cli.py:280`。

因此下列 Core 工具“已实现但 Core 自己不可用”：`read_file`、`list_dir`、`search_files`、`search_content`、`write_file`、`edit_file`、`run_command`、`run_tests`、`git_status`、`git_diff`、`web_search`、`web_fetch`、`browser_check`、`mcp_tool`、verification。

## 权限与审批现状

Core 已有权限与审批基础：

- 权限 tier：`core/src/lamtools_core/tool/permission.py:17`。
- `ApprovalGate`：`core/src/lamtools_core/tool/approval.py:95`。
- 路径/命令/敏感文件检查：`core/src/lamtools_core/tool/approval.py:119`、`core/src/lamtools_core/tool/approval.py:128`、`core/src/lamtools_core/tool/approval.py:151`。
- Kernel 等待审批：`core/src/lamtools_core/kernel/loop.py:337`。
- Hook 可把工具改为 `ask_user`：`core/src/lamtools_core/kernel/loop.py:1086`。

但 Core Kernel 不主动调用 `ApprovalGate`，它只消费 `ToolCall.requires_approval` 或 hook decision。Core 默认工具箱不存在，所以权限机没有形成“所有工具统一前置”的闭环。

## Writer 重复/补接情况

- Writer 复用 Core `ApprovalGate`：`members/writer/backend/app/core/writer/permission.py:8`、`members/writer/backend/app/core/writer/permission.py:53`。
- Writer 自己维护通用工具顺序和权限：`members/writer/backend/app/core/writer/tool_specs.py:155`。
- `write_file`、`edit_file`、`web_fetch`、`mcp_tool` 在 Writer spec 中是 `ASK_USER`：`members/writer/backend/app/core/writer/tool_specs.py:190`、`:213`、`:365`、`:585`。
- 但 Writer 当前只显式给命令类工具标记审批：`members/writer/backend/app/core/writer/core_kernel_adapter.py:328`、`:340`、`:707`。
- 批准后执行只支持 `run_command/run_tests`：`members/writer/backend/app/services/runtime_approved_tool.py:20`。

## 风险

- 高：权限声明与实际审批路径不一致，尤其是 `write_file/edit_file/web_fetch/mcp_tool`。
- 中：Core 工具已实现但没有默认工具箱，member 重复维护 schema、权限、display、失败语义。
- 中：Core 的 `approval.respond` 是占位，批准后执行仍在 Writer 服务层补洞。
- 中低：`browser_check` 名称容易误导，它是 HTTP 文本检查，不是真实浏览器。

## 接线建议

Core 应提供“基础工具箱接口”，一次返回：

- 模型可见工具规格。
- 工具执行器。
- 权限/审批策略。
- verification。
- 可选禁用清单和 member 专用扩展点。

所有工具调用先过统一权限机：自动执行、等待审批、硬阻断。批准后也回到同一个 Core 工具执行器，Writer 不再维护通用工具表，只追加 Writer 专用工具。

## 验收用例

- `read_file` 自动放行。
- `write_file/edit_file` 进入等待或按策略执行。
- 危险命令进入等待或阻断。
- 路径越界阻断。
- `web_fetch file://` 阻断。
- `mcp_tool` 走同一审批路径。
- 模型可见工具、capabilities、executor 三者一致。

