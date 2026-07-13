# Sub-agent 当前能力与调用指南

## 产品定义

Sub-agent 不是另一种 Agent，也没有专用 persona、Prompt 或模型路由。它是同一个 Agent 在父 session 所属的子 session 中继续运行。

主 Agent 调用 `sub_agent` 等价于向指定子 session 发送一条普通 `user` 消息。子 Agent 的最终回复再作为 `sub_agent` 工具结果返回父 Agent，由主 Agent 继续整合、验收并回复用户。这属于 agent-as-tool，不是把对话控制权永久转移出去的 handoff。

主、子 Agent 共用：

- 同一个模型实例、模型参数和 thinking 配置；
- 同一套 system prompt 与 Prompt 拼接顺序；
- 同一套 Agent loop、工具执行、审批、错误处理和 token 驱动自动压缩；
- 同一工作目录和父 Agent 当前可用的工具权限。

编排层只保留三个差异：子 session 从属于父 session；子工具集合移除 `sub_agent`；子回复作为工具结果回到父 Agent。

## 调用接口

模型调用时必须传入且只能传入两个字段：

```json
{
  "task": "核实权限链并给出文件与行号证据",
  "agent": "permission_auditor"
}
```

| 字段 | 必须出现 | 可为空 | 作用 |
| --- | --- | --- | --- |
| `task` | 是 | 否 | 作为一条原样的 `user` 消息发送给子 session。需要的任务背景应直接写在这里。 |
| `agent` | 是 | 是 | 子 session 名/复用标识。相同父 session 内同名复用；`null` 或空值使用 `sub`。它不代表角色、权限 profile 或模型。 |

不再支持 `model`、`expected_output`、`role`、`developer_instructions`、`context`、`write_scope`、`isolated` 或 `maxTurns`。项目/user/plugin 中的旧 Agent profile 不再被运行时读取，Writer 配置接口也不再提供 profile CRUD。

## 上下文与自动压缩

首次调用某个名字时，该 `task` 是子 session 的第一条用户消息。之后再次调用相同 `agent` 名时，新 `task` 会作为下一条普通用户消息追加，子 session 会看到自己的完整会话历史。

主 session 和子 session 都不按“最近 20 条”硬截断。两者使用同一个 token 窗口和压缩阈值：请求接近模型上下文窗口时，由统一 Kernel 对旧上下文做结构化摘要压缩。压缩后的摘要继续留在该 session 的历史中。

子 session 不会自动继承父 session 的完整对话记录。父 Agent 需要把本次委派所需的信息写进 `task`；这与用户向一个已有 session 发送新消息的语义一致。

## 模型、Prompt 与权限

- 不存在 `sub_agent` 或 `sub_agent:{name}` 模型路由；旧路由配置会被清理并忽略。
- 子 Agent 直接复用父 Agent 已解析完成的 LLM client，不会重新查询数据库，也不能在调用中覆盖模型。
- Writer 子 Agent 使用与主 Writer 相同的 system prompt 组装；Core 子 Agent使用与父 Core Agent 相同的 instructions。
- 子 Agent 继承父 Agent 当前可见工具集合，并在运行时强制移除 `sub_agent`。因此它不能继续创建孙 Agent。
- 其余工具仍经过与主 Agent相同的执行器、权限和审批规则；Prompt 不能提升权限。
- 子 Agent 触发审批时，审批请求显示在父 session；父流程进入等待。批准或指导后先恢复原子 session，子 Agent 完成后再把结果交回主 Agent。
- 子 Agent 与父 Agent 使用同一工作目录，不创建专用 worktree，也没有独立 `write_scope`。
- 父任务取消会转发到正在运行的子 Kernel；模型超时、重试耗尽、审批阻塞和显式失败仍可终止运行。

工具调用轮次没有固定上限，也不存在“最多 5 轮”。任务会在无工具的最终回复、等待、失败、取消或运行时错误时结束。

## 子 session 身份

Writer 在每个父 session 内按 `agent` 名分配稳定编号，例如：

```text
parent-session
├─ parent-session:sub:001:permission_auditor
└─ parent-session:sub:002:test_fixer
```

- 同一父 session + 同一 `agent`：复用同一个子 session 和历史；
- 同一父 session + 不同 `agent`：创建不同子 session；
- 不同父 session：不会共享子 session；
- 子状态与历史存放在父 session 的运行状态内，不是顶层 session 数据行。

Core 独立运行面同样以“父 session + `agent` 名”作为子 session 身份，并使用父 runtime 的 checkpoint store；父 Agent 跨轮重建运行器后仍会恢复原子 session 历史。

## handoff、补发信息与主 Agent控制

当前 handoff 是同步工具返回：子 Agent 的正文、工具记录、推理记录和诊断信息被包装成 `sub_agent` 工具结果，进入主 Agent 的下一轮上下文。主 Agent拥有最终回复权。

主 Agent 可以在子 Agent 完成后再次调用相同 `agent`，把补充信息作为下一条用户消息发送到原子 session。当前不支持向仍在运行的子 Agent 实时插入消息，也没有单独公开的 pause、interrupt 或子 Agent 之间互发消息接口。

## 前端展示

子 session 不占用左侧顶层 session 列表，也没有独立路由页面。它显示在父 session 的对话时间线内：

- 一个子 Agent 对应一条可展开的嵌套运行记录；
- 展示子 session 名/编号、运行状态、委派任务、推理、工具调用和最终结果；
- 最终正文进入该卡片，并同时作为主 Agent可见的工具结果，避免另建一条顶层对话；
- 同名 follow-up 继续归入同一逻辑子 session。

## 成熟方案对照

- OpenAI 将 handoff 与 agent-as-tool 分开；当前实现采用主 Agent保留控制权的 agent-as-tool：<https://developers.openai.com/api/docs/guides/agents/orchestration>
- OpenAI agent loop 按需跨多轮调用工具，并由 session、trace、guardrail 和审批控制边界：<https://developers.openai.com/api/docs/guides/agents>
- Claude Code subagent 也使用独立上下文和受控工具集合；LamTools MVP 进一步收敛为与父 Agent同模型、同 Prompt、同权限，仅禁止递归委派：<https://code.claude.com/docs/en/sub-agents>
