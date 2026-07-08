# Agent Plugin Hooks Design

日期：2026-07-08

## 背景

当前 LamTools 已有 `CoreLoopKernel + RuntimeKit` 主线、Writer skills、MCP 加载、工具权限和 app-server 事件/快照，但这些能力还是分散入口。用户从 Codex、Claude Code 等成熟 Agent 生态迁移过来时，会自然预期“下载一个插件”可以同时带来 skills、hooks、scripts、MCP server 和子 Agent 定义，并能在设置里启用、审查和信任。

本设计的目标是支持这种完整插件生态心智，而不是只在内部代码里增加几个回调。

成熟方案对照：

- OpenAI Codex Hooks：hooks 是向 agentic loop 注入确定性脚本的扩展框架；支持 `PreToolUse`、`PermissionRequest`、`PostToolUse`、`PreCompact`、`PostCompact`、`UserPromptSubmit`、`SubagentStart`、`SubagentStop`、`Stop` 等事件；非托管 hooks 需要审查和信任。参考：<https://developers.openai.com/codex/hooks>
- OpenAI Codex Plugins：插件可打包 hooks 和 MCP server；插件 hooks 与其他 hook 来源走同一信任流程；默认 hook 文件可为 `hooks/hooks.json`，也可由 manifest 指定。参考：<https://developers.openai.com/codex/plugins/build>
- Claude Code Hooks：hooks 支持 command、HTTP、prompt、MCP tool 等 handler；常见事件包括 `SessionStart`、`UserPromptSubmit`、`PreToolUse`、`PermissionRequest`、`PostToolUse`、`Stop`、`SubagentStop`、`PreCompact`；hook 可阻断、修改工具输入、修改工具输出或追加上下文。参考：<https://code.claude.com/docs/en/hooks>
- Claude Skills：skills 是可携带支持文件的模块化能力；插件 skills 单独由插件管理。参考：<https://code.claude.com/docs/en/skills>

## 产品目标

LamTools 支持插件式扩展包。一个插件安装并启用后，可以同时注册：

- `skills/`：任务工作流、知识和可调用能力说明。
- `hooks/`：生命周期拦截器和自动动作。
- `scripts/`：hook 或 skill 调用的本地脚本。
- `mcp/` 或 `.mcp.json`：MCP server 声明。
- `agents/`：可选子 Agent 定义。
- `plugin.json`：插件名称、版本、入口、权限、启用状态和信任要求。

验收标准：

- 插件目录可扫描、列出、启用、禁用。
- 插件可同时声明 skills、hooks、MCP server 和 scripts。
- Core Agent 使用现有文件/命令能力把一个有效插件包放入插件目录后，系统能自然完成发现、审查、启用和加载；这只是验收场景，不要求新增独立“一键安装插件”入口。
- 插件 hooks 默认未信任；用户审查后按 hook 定义 hash 信任。
- hooks 支持 Codex/Claude 主流事件名和配置形状。
- `PreToolUse` 能允许、拒绝、要求用户审批、修改工具输入或追加上下文。
- `PostToolUse` 能修改工具输出或追加模型可见上下文。
- `UserPromptSubmit` 能阻断用户输入或追加上下文。
- `Stop` 能在一轮结束时执行检查并阻断“完成”状态。
- Hook 执行有超时、日志、错误隔离和审计事件。
- GUI 与 CLI 使用同一操作入口管理插件、hooks 和信任。

## 方案选择

用户选择方案三：**完全复刻成熟生态能力**。

这里的“完全复刻”指用户可见能力和配置心智完整对齐：

- 支持插件包同时携带 skills、hooks、scripts、MCP、agents。
- 支持 Codex 风格 `plugin.json` / `hooks/hooks.json` / `.mcp.json`。
- 支持 Claude 风格 hook 事件、handler 类型、stdin/JSON 输入输出、阻断语义。
- 支持用户审查、信任、禁用和插件级 MCP 工具审批。

内部实现不复制旧 `HookSet`。LamTools 继续保持：

- Kernel 管流程。
- Kit 管业务。
- Hook Engine 是 Core 生命周期上的扩展执行器。
- Plugin Registry 是配置和资源发现层。

## 架构

新增四个深模块，接口小，行为集中：

1. `PluginRegistry`

   负责发现、解析、启用、禁用插件。

   输入：

   - 全局插件目录。
   - 项目插件目录。
   - 内置插件目录。
   - 用户配置中的启用状态。

   输出：

   - 已安装插件列表。
   - 每个插件的资源根目录。
   - skills、hooks、MCP、agents 的规范化清单。

2. `HookRegistry`

   负责把来自用户、项目、插件、托管配置的 hook 文件合并成可执行计划。

   职责：

   - 解析 Codex/Claude hook 配置。
   - 展开 `${PLUGIN_ROOT}`、`${PLUGIN_DATA}`、`${PROJECT_ROOT}` 等变量。
   - 按事件名和 matcher 过滤。
   - 计算 hook 定义 hash。
   - 标记 trusted、pending_review、disabled、managed。

3. `HookEngine`

   负责执行 hooks。

   职责：

   - 接收 Core 生命周期事件。
   - 生成兼容输入 JSON。
   - 执行 command / HTTP / prompt / MCP handler。
   - 合并执行结果。
   - 返回统一 `HookDecision`。
   - 记录审计事件。

4. `PluginOperationCatalog`

   负责给 GUI/CLI/app-server 暴露统一操作。

   操作名：

   - `plugin.list`
   - `plugin.enable`
   - `plugin.disable`
   - `plugin.inspect`
   - `hook.list`
   - `hook.trust`
   - `hook.disable`
   - `hook.run.dry`
   - `mcp.plugin.list`
   - `mcp.plugin.set_policy`

## 插件包布局

推荐插件布局：

```text
my-plugin/
  plugin.json
  skills/
    code-review/SKILL.md
  hooks/
    hooks.json
    pre_tool_use.ps1
    stop_check.py
  scripts/
    collect_context.py
  mcp/
    mcp.json
  agents/
    reviewer.md
```

`plugin.json` 最小形状：

```json
{
  "name": "repo-policy",
  "version": "0.1.0",
  "description": "Repository policy checks",
  "skills": ["./skills"],
  "hooks": ["./hooks/hooks.json"],
  "mcpServers": "./mcp/mcp.json",
  "agents": ["./agents"],
  "permissions": {
    "commands": "ask_user",
    "network": "ask_user",
    "filesystem": "project"
  }
}
```

兼容规则：

- 未声明 `hooks` 时，默认读取 `hooks/hooks.json`。
- 未声明 `mcpServers` 时，默认尝试 `.mcp.json` 和 `mcp/mcp.json`。
- manifest 路径必须以 `./` 开头，解析后必须仍在插件目录内。
- 插件脚本可读，执行前必须通过 hook 信任。
- 插件数据写入 `${PLUGIN_DATA}`，不写插件安装目录。

## Hook 事件

第一期必须支持这些事件名：

- `SessionStart`
- `UserPromptSubmit`
- `PreToolUse`
- `PermissionRequest`
- `PostToolUse`
- `Stop`
- `SubagentStart`
- `SubagentStop`
- `PreCompact`
- `PostCompact`

允许识别但暂不触发：

- `SessionEnd`
- `StopFailure`
- `PostToolUseFailure`
- `PostToolBatch`
- `InstructionsLoaded`
- `ConfigChange`
- `WorktreeCreate`
- `UserPromptExpansion`
- `MessageDisplay`

未触发事件必须在 `hook.list` 中显示为 `recognized_not_wired`，避免用户误判配置丢失。

## Hook 配置

兼容 Codex/Claude 的事件 -> matcher group -> handlers 形状：

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "run_command",
        "hooks": [
          {
            "type": "command",
            "command": "python ${PLUGIN_ROOT}/hooks/block_danger.py",
            "timeout": 10,
            "statusMessage": "Checking command policy"
          }
        ]
      }
    ]
  }
}
```

支持 handler 类型：

- `command`：本地脚本，stdin 接 JSON，stdout 可返回 JSON。
- `http`：POST JSON 到本地或远端服务。
- `prompt`：返回追加给模型的上下文，不直接执行外部命令。
- `mcp`：调用已注册 MCP tool。

一期实现优先级：

1. `command`
2. `http`
3. `mcp`
4. `prompt`

如果实现排期要拆分，`command` 必须先做；其他类型可按同一接口补充。

## Hook 输入输出

所有 hook 输入包含通用字段：

- `event_name`
- `session_id`
- `run_id`
- `turn_id`
- `cwd`
- `project_root`
- `plugin_name`
- `plugin_root`
- `plugin_data`
- `transcript_path`
- `metadata`

事件特定字段：

- `UserPromptSubmit`：`prompt`
- `PreToolUse`：`tool_name`、`tool_input`
- `PermissionRequest`：`tool_name`、`tool_input`、`permission`
- `PostToolUse`：`tool_name`、`tool_input`、`tool_output`
- `Stop`：`final_message`、`decision`、`steps`
- `SubagentStart` / `SubagentStop`：`agent_name`、`parent_session_id`、`sub_session_id`
- `PreCompact` / `PostCompact`：`before_tokens`、`after_tokens`、`summary`

统一输出先支持这些字段：

```json
{
  "decision": "block",
  "reason": "Test suite must pass before finishing",
  "additionalContext": "Remember project rule ...",
  "updatedInput": {},
  "updatedToolOutput": "",
  "permissionDecision": "deny",
  "permissionDecisionReason": "Destructive command blocked"
}
```

决策合并规则：

- 任一 hook 返回 `block`，当前动作阻断。
- `PreToolUse.permissionDecision=deny` 阻断工具。
- `PreToolUse.permissionDecision=ask_user` 转入现有审批流。
- 多个 `additionalContext` 按 hook 来源顺序追加。
- 多个 `updatedInput` 顺序合并，后执行 hook 覆盖同名字段。
- 多个 `updatedToolOutput` 顺序应用，后执行 hook 覆盖前一结果。
- hook 执行失败默认不阻断，除非 hook 标记 `required=true`。

## 数据流

以工具调用为例：

1. 模型返回工具调用。
2. Kernel 生成 `PreToolUse` hook 输入。
3. HookEngine 执行匹配 hooks。
4. 如果结果阻断，Kernel 把工具结果记为 `blocked`，并把原因回给模型。
5. 如果结果要求审批，进入现有 `runtime.approval_request` 流程。
6. 如果结果修改输入，用新输入继续权限检查和工具执行。
7. 工具执行结束后触发 `PostToolUse`。
8. 如 hook 修改输出，模型看到修改后的工具结果。
9. Hook 审计事件进入同一 app event / runtime event 链路。

以插件安装为例：

1. 用户或 Core Agent 通过已有文件/命令能力把插件包放入插件目录。
2. `PluginRegistry` 扫描 manifest。
3. GUI/CLI 显示插件带来的 skills、hooks、MCP、agents。
4. 用户启用插件。
5. hooks 进入 pending review。
6. 用户审查 hook 命令、路径、hash、权限并信任。
7. HookEngine 才允许执行非托管 hook。

这个流程不是单独的安装器需求。只要插件协议、扫描、启用、信任和加载链路完整，Agent 自己挑选并放置一个插件包后，插件内的 skills、hooks、scripts、MCP 和 agents 就应该作为系统能力自然生效。

## 信任和安全

默认策略：

- 插件启用不等于 hooks 可信。
- 非托管 hook 必须按 hash 信任。
- hook 文件变化后，信任失效。
- 项目本地 hooks 只在项目被信任时加载。
- 托管 hooks 可由系统/企业策略标记为 trusted 且不可由普通用户禁用。
- command hook 默认禁止越出插件目录和项目目录读取脚本。
- hook 超时默认 10 秒，可由配置降低或提高到上限。
- hook 输出大小有上限，超限截断并记录。
- hooks 不得绕过现有工具权限；只能收紧、要求审批或追加上下文。允许放宽权限的 hook 必须来自 managed 来源。

审计必须记录：

- hook 来源：user/project/plugin/managed。
- hook hash。
- 是否 trusted。
- 执行耗时。
- exit code 或 HTTP status。
- decision。
- stderr 第一行或错误摘要。

## GUI 和 CLI

GUI 需要：

- 插件列表：名称、版本、来源、启用状态。
- 插件详情：skills、hooks、MCP servers、agents。
- Hook 审查页：命令、路径、hash、权限、最近执行结果。
- 一键信任当前 hook 定义。
- 禁用单个 hook 或整个插件。
- MCP server policy 设置：enabled、工具审批模式、enabled tools。

CLI 需要同接口：

```powershell
.\writer.cmd plugin list
.\writer.cmd plugin inspect repo-policy
.\writer.cmd plugin enable repo-policy
.\writer.cmd plugin disable repo-policy
.\writer.cmd hook list
.\writer.cmd hook trust <hook-id>
.\writer.cmd hook disable <hook-id>
.\writer.cmd hook run-dry <hook-id> --event PreToolUse --json
```

GUI 和 CLI 都调用 `PluginOperationCatalog`，不能各自实现一套。

## 与现有代码关系

复用：

- `CoreLoopKernel` 的运行主线。
- `RuntimeKit` 作为业务注入点。
- `ToolCall.requires_approval` 和现有审批事件。
- Writer 已有 `WriterSkillRegistry` 的技能发现经验。
- Writer 已有 MCP config/registry/client。
- `OperationCatalog` 作为 GUI/CLI/app-server 共用入口。
- app event / snapshot 作为可恢复事实链路。

新增：

- Core 级插件发现和 manifest 解析。
- Core 级 hook 配置、信任、执行。
- 插件级 MCP policy 和资源路径变量。
- GUI/CLI 插件管理入口。

删除或避免：

- 不恢复旧 `HookSet`。
- 不新增与 `RuntimeKit` 并行的业务注入层。
- 不让 Core 写入 Writer/Artist 产品名。
- 不把插件 scripts 当普通项目脚本直接无审查运行。
- 不让 hook 修改数据库或事件事实源，除非通过正式操作入口。

## 迁移策略

第一步只把新能力接到 Core，不改 Writer 用户路径：

1. Core 新增 PluginRegistry、HookRegistry、HookEngine。
2. Writer 通过 Core registry 读取插件 skills，但保留现有 skill 加载行为作为兼容。
3. Writer MCP 先支持插件声明的 MCP server，旧 `LAMWRITER_MCP_CONFIG` 继续保留。
4. Kernel 在工具调用前后触发 HookEngine。
5. app-server 增加 plugin/hook 操作。
6. GUI/CLI 增加管理入口。

后续再把 Writer 专属 skill/MCP 发现逻辑下沉到 Core，减少重复。

## 测试计划

Core 单元测试：

- 插件 manifest 解析：默认 hooks、显式 hooks、MCP、skills、agents。
- 路径安全：`../`、绝对路径、插件外路径必须拒绝。
- HookRegistry 合并多来源 hooks。
- hook hash 变化后 trust 失效。
- `PreToolUse` command hook 可阻断工具。
- `PreToolUse` command hook 可修改工具输入。
- `PostToolUse` hook 可修改工具输出。
- `UserPromptSubmit` hook 可追加上下文。
- `Stop` hook 可阻断完成。
- hook timeout 不阻断非 required hook。
- required hook 失败会阻断。

Writer 集成测试：

- 启用插件后 Writer 模型请求能看到插件 skill 索引。
- 插件 MCP tool 能进入 Writer 工具列表。
- 危险命令先过 hook，再进入现有审批流。
- 被 hook 阻断的工具在 UI 显示为 blocked。
- hook 审计事件刷新后仍存在。
- CLI 与 GUI 操作同一个 app-server operation。

安全回归测试：

- 未信任 hook 不执行。
- 插件启用但 hook 未信任时显示 pending review。
- 修改 hook 文件后必须重新信任。
- managed hook 不能被普通用户禁用。
- 非 managed hook 不能放宽工具权限。

## 分期

### Phase 1：Core 插件和 hook 骨架

- Plugin manifest 解析。
- Hook config 解析。
- Trust store。
- `hook.list` / `hook.trust` / `plugin.list` / `plugin.enable`。
- `PreToolUse` command hook。

### Phase 2：完整核心事件

- `UserPromptSubmit`。
- `PermissionRequest`。
- `PostToolUse`。
- `Stop`。
- 审计事件和 UI 展示。

### Phase 3：插件资源整合

- 插件 skills。
- 插件 MCP server。
- 插件 agents。
- `${PLUGIN_ROOT}` / `${PLUGIN_DATA}`。
- 插件级 MCP policy。

### Phase 4：Claude/Codex 兼容补齐

- HTTP hook。
- MCP hook。
- prompt hook。
- `SubagentStart` / `SubagentStop`。
- `PreCompact` / `PostCompact`。
- 识别但未触发事件的状态提示。

## 风险

- 范围大：必须按 Phase 推进，先打通 hook trust 和 `PreToolUse`，再扩事件。
- 安全风险高：默认未信任、hash 信任、路径限制和超时必须先做，不能后补。
- 与旧 `HookSet` 名称混淆：文档和代码都用 `HookEngine` / `HookRegistry`，不使用 `HookSet`。
- Writer 当前 skill/MCP 逻辑在 member 内：先兼容读取，后续再下沉，避免一次性大迁移。
- GUI/CLI parity 容易漏：所有管理能力先落在 OperationCatalog，再接 GUI/CLI。

## 非目标

- 不实现插件市场下载和发布。
- 不把“Agent 能安装一个插件包”做成专门功能；它只是插件协议完整后的验收场景。
- 不实现企业托管策略后台。
- 不支持未审查 hook 自动执行。
- 不允许普通插件提升自身权限。
- 不重写 CoreLoopKernel。
- 不把 Writer persona、项目规则或专用工具下沉到 Core。
- 不一次性删除现有 Writer skill/MCP 入口。
