# Sub-agent 当前能力与调用指南

本文描述 Writer 当前真实运行链路。它区分已实现能力、内部兼容字段和尚未实现能力，避免把规划当成现状。

## 产品定位

Writer 当前采用 manager/worker 模式：主 Agent 始终负责最终答复，sub-agent 是主 Agent 同步调用的辅助工具。子 Agent 完成后把结果正文返回给主 Agent，由主 Agent 继续判断、整合和验收。

这不是控制权转移式 handoff。OpenAI 对两种模式的区分是：handoff 会把当前对话控制权交给专用 Agent；agent-as-tool 则由主 Agent 保持答复所有权。Writer 当前属于后者。

## 调用字段

模型调用 `sub_agent` 时使用以下对象：

```json
{
  "task": "核实权限链并给出文件与行号证据",
  "agent": "permission_auditor",
  "model": null,
  "expected_output": "结论、证据、风险和下一步建议"
}
```

| 字段 | 是否必须出现 | 可否为空 | 作用 |
| --- | --- | --- | --- |
| `task` | 是 | 否 | 自包含的委派任务。主 Agent 应把必要背景写进任务，不应假设子 Agent 看过完整主对话。 |
| `agent` | 是 | 是 | 稳定的子 session 名。相同父 session 内使用同名会复用同一子 session；空值使用 `sub`。 |
| `model` | 是 | 是 | 可选模型 ID 覆盖；空值沿用 sub-agent 路由或默认模型。 |
| `expected_output` | 是 | 是 | 期望交付内容，只用于提示和验收导向，不是强制结构化输出校验。 |

公开工具协议不接受其他字段。内部运行层虽然已有 `context`、`role` 等兼容入口，但模型侧协议尚未开放，不应作为可用接口依赖。

## 轮次和结束条件

sub-agent 不再配置固定工具调用轮次，也不存在“最多 5 轮”的真实运行限制。旧定义文件里的 `maxTurns`、`maxToolRounds` 或 `max_tool_rounds` 会被忽略，新保存的定义不再写出这些字段。

运行会持续到以下任一条件发生：

- 子 Agent 给出不含工具调用的最终回复；
- 进入等待或失败状态；
- 模型请求超时或重试耗尽；
- 模型上下文容量报错；
- 工具或运行时安全规则终止执行。

“无固定轮次”不等于“不可停止”。模型超时、权限、递归深度和重复失败保护仍然有效。Writer 当前没有单个子 Agent 的即时取消：父任务取消要等正在执行的子调用返回后才能继续生效；子运行也没有启用 Core 主动上下文压缩，超出模型容量时仍可能直接失败。

## 权限机制

Writer 当前权限规则如下：

1. 子 Agent 只看到主 Agent 当前可见工具集合，并强制移除 `sub_agent`，因此不能继续派发孙 Agent。
2. 工具调用仍经过同一权限和审批执行链；子 Agent 的消息不能批准权限，也不能提升权限。
3. 子 Agent 与主 Agent 共享当前工作目录。当前没有接通独立 worktree，也没有接通按子 Agent 限制写入路径的 `write_scope`。
4. 子 Agent 不继承完整主对话，只收到委派任务包，以及同一子 session 自己保留的短历史。

通用 Core runner 还支持通过 Agent 定义里的 `tools` 收窄工具列表；但 Writer 当前实时路径以父 Agent 工具集合为准，项目 Agent 定义中的工具列表尚未成为 Writer 的真实权限边界。配置页展示与运行时权限仍需后续收敛。

## 子 session

Writer 为每个父 session 内的稳定 `agent` 名分配一个逻辑子 session：

```text
父 session
└─ parent:sub:001:permission_auditor
```

- 同一个父 session、同一个 `agent` 名：复用同一子 session。
- 同一个父 session、不同 `agent` 名：创建不同编号的子 session。
- 不同父 session：不会共享子 session。
- 子 session 有独立运行状态和自己的短历史，当前最多回载最近 20 条 user/assistant 记录。
- 子状态内嵌在父 session 的运行状态中，不是独立顶层 session 数据行。

Core 独立 CLI 的通用 runner 当前每次调用生成临时内存 session；Writer 上述同名复用语义不要反向假定到所有 Core 调用面。

## 交接与补发信息

当前交接是同步工具返回：子 Agent 的最终正文、工具记录、推理记录、诊断信息和变更文件摘要被包装成 `sub_agent` 工具结果，回到主 Agent 的下一轮上下文。主 Agent 仍然负责最终结论和验收。

当前支持：

- 子 Agent 完成后，主 Agent 再次调用相同 `agent` 名进行追问或补充任务；
- 复用该子 session 的短历史继续工作。

当前不支持：

- 向正在运行的子 Agent 定向发送消息；
- 对单个子 Agent 执行 pause、interrupt 或 cancel；
- 子 Agent 主动把控制权切换给主 Agent 的独立 handoff API；
- 子 Agent 之间互发消息。

因此，“补发信息”目前是完成后的同名 follow-up，不是运行中的 `send_message`。

## 前端展示

子 session 不出现在左侧顶层 session 列表中。它显示在父 session 的主对话时间线内：

- 默认以子 Agent 卡片显示编号、名称和运行中/完成/失败状态；
- 卡片内展示委派任务、推理、工具调用和最终结果；
- 可显示交付分支、变更文件数量等运行摘要；
- 子 Agent 的最终文本若已经汇总到卡片，会抑制主时间线里的重复副本。

这是一条嵌套时间线，不是可单独导航、单独聊天的完整 session 页面。

## 当前限制与后续优先级

按风险和收益排序：

1. 接通父权限上限与子 Agent profile 的交集，避免配置页工具范围与真实执行不一致。
2. 复用已有 workspace/write-scope 能力，为写入型子 Agent 提供明确隔离。
3. 增加稳定 `agent_id` 寻址，以及运行中 `send`、完成后 `followup/resume`、`interrupt` 操作。
4. 前端增加可展开的子 session 树和定向补发入口，同时保持子 session 不占用顶层列表。
5. 补充并发上限、单子 Agent 成本/时间预算和可观测统计；这些是安全边界，不应重新变成固定工具轮次。

## 成熟方案对照

- OpenAI Agents SDK 将 handoff 和 agents-as-tools 分开；Writer 当前应保持 agents-as-tools 语义：<https://developers.openai.com/api/docs/guides/agents/orchestration>
- OpenAI 的 agent loop 会按需跨多轮调用工具，并提供 session、trace、guardrail 和可恢复审批：<https://developers.openai.com/api/docs/guides/agents>
- OpenAI Multi-agent 提供 `spawn_agent`、`send_message`、`followup_task`、`interrupt_agent`、`wait_agent` 和 `list_agents` 等协作动作：<https://developers.openai.com/api/docs/guides/tools-multi-agent>
- Claude Code subagents 使用独立上下文、工具权限和可选 `maxTurns`；不设置 `maxTurns` 不等于取消权限或运行安全边界：<https://code.claude.com/docs/en/sub-agents>
