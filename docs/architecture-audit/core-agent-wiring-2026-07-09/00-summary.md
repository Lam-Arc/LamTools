# Core Agent 接线审计总报告（2026-07-09）

维护标注：本文件记录的是接线前审计结论。随后已完成 Core-first 接线、共享配置库拆分、Writer overlay 简化和真实入口验收；实施后状态见 [06-final-acceptance.md](06-final-acceptance.md)，2026-07-10 的最终自审见 [07-final-summary-20260710.md](07-final-summary-20260710.md)。

## 结论

Core 现在不是“没有基础 Agent 能力”，而是“能力已经分散实现，但没有收敛到 Core 自己可用的统一入口”。如果摒弃 member，只看 Core，当前只能证明一条很窄的 `core.cmd run -> CoreLoopKernel -> write_document` 链路可用；不能证明 Core 已经是完整基础 Agent。

主验收判断：Core 需要一个统一的基础 Agent 装配层。CLI、HTTP、GUI/operation 都应调用这一个装配层；member 只提供 persona、业务工具、路径配置和展示规则。

## 审计方式

- 5 个 GPT-5.5 high 子 Agent 并行只读审计。
- 主线程复核关键源码证据。
- 主线程执行 Core 测试全集：`py -3.14 -m pytest core\tests -q`，结果 `572 passed`。
- 本次只新增报告文档，不修改运行代码。

## 分报告

- [01-entrypoints-runtime.md](01-entrypoints-runtime.md)：入口、Kernel、AgentApp、HTTP operation。
- [02-tools-permissions.md](02-tools-permissions.md)：默认工具箱、权限、审批、批准后执行。
- [03-plugins-hooks-skills.md](03-plugins-hooks-skills.md)：Plugin、Hook、Skill。
- [04-mcp-subagents.md](04-mcp-subagents.md)：MCP、SubAgent、外部扩展。
- [05-storage-http-memory.md](05-storage-http-memory.md)：Session、Event、Snapshot、Usage、Memory、HTTP 管理面。

## 当前能力验收表

| 能力 | Core 有实现 | Core 自己可用 | 主验收 |
|---|---:|---:|---|
| 模型调用与工具循环 | 是 | 部分 | CLI 走 `CoreLoopKernel`，但只接 `write_document`。 |
| 默认工具箱 | 是 | 否 | 文件、命令、Git、Web 等工具在 Core，但未接到 Core 默认 Agent。 |
| 权限/审批 | 是 | 否 | `ApprovalGate` 和 Kernel 等待点都有，但 Core 默认入口没统一使用。 |
| Hook | 是 | 否 | Kernel 支持 `PreToolUse`，CLI 未注入 HookEngine。 |
| Plugin operation | 是 | Core CLI/HTTP 否 | Core 有 catalog，Writer 暴露了，Core 自己没有统一 operation 面。 |
| Skill | 半成品 | 否 | Core 只有 roots 支撑；`load_skill` 仍在 Writer。 |
| MCP | 半成品 | 否 | Core 有调用包装；registry/client/config 仍在 Writer。 |
| SubAgent | 半成品 | 否 | Core 有定义解析和范围校验；运行器仍在 Writer。 |
| SQL 事件/快照 | 是 | Core CLI 否 | Core 有适配器，Writer 已复用；Core CLI 仍写临时 JSON。 |
| HTTP `/api/core` | 是 | 管理面可用 | 只做 CRUD/管理，不触发真实 Agent run。 |
| Usage | 是 | 未接运行链路 | 只有内存 ledger 和 HTTP 管理面。 |
| Memory | 协议级 | 否 | 只有协议、预算和 prompt 格式化，没有具体 store。 |

## 核心问题

1. 入口分裂：CLI 走 Kernel，AgentApp 是另一条单轮模型路径，HTTP 只是管理面。
2. 工具分裂：通用工具在 Core，工具 schema/权限/执行组合主要由 Writer 重新拼。
3. 权限分裂：Core 有审批判断和 Kernel 等待点，但审批标记和批准后执行由 Writer 补接。
4. 扩展分裂：插件能发现 skill/MCP/agents，但运行时只真正消费 hooks；Skill/MCP/SubAgent 可运行接线还在 Writer。
5. 存储分裂：Core 有 SQL event/snapshot 适配器，Writer 已复用；Core CLI/HTTP/AgentApp 没有形成同一条运行事实链。

## 建议的 Core 基础 Agent 装配层

建议新增或收敛一个小而深的 Core 装配接口，暂称 `CoreAgentRuntime`：

- 输入：`RuntimeKit`、`LLMClient`、`work_root`、`data_dir`、模型配置、权限策略、启用工具、插件根、存储适配器。
- 输出：统一 operation catalog，至少包含 `turn.start`、`approval.respond`、`turn.cancel`、`plugin.*`、`hook.*`、`skill.*`。
- 内部唯一运行路径：`CoreLoopKernel + RuntimeKit`。
- 成员接入：Writer 只传 Writer persona、Writer 专用工具、默认路径和 UI 映射。

## P0 实施顺序

1. 收敛运行入口：`create_core_agent_operations("turn.start")` 和 Core CLI 都进入同一个 `CoreLoopKernel` 装配层。
2. Core 默认工具箱：从 Core 生成通用工具 schema、执行器、权限、验证器，Writer 删除重复通用工具定义。
3. Core 权限/审批闭环：所有工具调用先过统一权限机；批准后也回同一执行器。
4. Hook/Plugin/Skill 接线：Core CLI/App/HTTP 能 list/enable/trust/load/use。
5. MCP/SubAgent 下沉：把 Writer 的可运行 registry/client/runner 泛化到 Core，member 只传策略。
6. 存储统一：真实 run 写入 `RunItemEvent -> core/runItem app event -> snapshot`，CLI/HTTP/GUI 可恢复同一状态。

## 不应下沉 Core

- Writer persona、Writer 业务 prompt、Writer 专用工具和展示投影。
- `write_document` 这种证明用工具和“超过 10 行文档”验收任务。
- 产品数据库默认路径和设置页语义。
- `delegate_to_member` 这类产品路由语义。
