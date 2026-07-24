# LamImager 已移除功能

> 状态：✅ 有效 | 来源：runtime-removed-feature-inventory.md
>
> 2026-05-31 决策：LamImager 当前只保留 Runtime 主内核。以下功能从 active API/UI 中移除。

## 移除清单

| 功能 | 原因 | 后续重做方向 |
|---|---|---|
| **旧 Agent 图**（2节点+9节点） | 与 Runtime 主 loop 重叠 | 拆成 Runtime tool |
| **旧 Persona 注册表** | Artist 系统提示词已内聚到 Runtime | 作为 Runtime profile/mode 注入 |
| **Prompt 工具流与提示词优化** | 不属于当前 Runtime 主链路 | 作为 Runtime prompt/refine tool |
| **Skill / Rule** | Runtime 不读取这些配置 | 作为 Runtime memory/tool policy |
| **Plan Template / Execute Plan** | Runtime 自己决定 action | 作为 Runtime plan artifact |
| **旧 Planner 上下文预算** | Runtime 不消费这些策略结果 | 作为 visual memory 压缩器 |
| **旧直连 Agent fallback** | 主入口已统一到 Artist Runtime | 做成 Runtime 内部 recover action |
| **旧前端 Agent 进度展示** | 前端已统一为 Runtime timeline | 只接入 RuntimeProgressState |

## 关联

- 架构设计 → [[LamImager 架构设计]]
- Artist Runtime → [[LamImager Artist Runtime]]
- 开发路线 → [[LamImager 开发路线图]]
