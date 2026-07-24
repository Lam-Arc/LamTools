# Runtime Removed Feature Inventory

2026-05-31 决策：LamImager 当前只保留 Runtime 主内核。以下功能从 active API / UI /旧测试中切掉，后续按 Runtime tool/agent contract 重新开发。

## 旧 Agent 图

- 功能：两节点工具聊天、九节点 Agent Mode、意图解析、技能匹配、上下文整理、规划、提示词优化、执行、视觉 critic、retry decision。
- 原因：与 Runtime 主 loop 重叠，且会错误接管视觉任务。
- 后续重做：拆成 Runtime tool，而不是恢复图作为主编排器。

## 旧 Persona 注册表

- 功能：sidebar assistant、agent、imager、artist 的统一人格注册。
- 原因：当前 Artist 系统提示词已经内聚到 Runtime，注册表没有被主链读取。
- 后续重做：如果需要多角色，直接作为 Runtime profile/mode 注入。

## Prompt 工具流与提示词优化

- 功能：`/api/prompt/stream`、`/api/prompt/optimize`、带 tools 的流式聊天、侧边栏提示词优化。
- 原因：不属于当前 Runtime 主链路。
- 后续重做：作为 Runtime 的 prompt/refine tool。

## Skill / Rule

- 功能：技能 CRUD、规则 CRUD、技能偏置、规则应用。
- 原因：当前 Runtime 不读取这些配置。
- 后续重做：作为 Runtime memory/tool policy，而不是旧 planner 偏置。

## Plan Template / Execute Plan

- 功能：规划模板管理、手动计划执行、Agent checkpoint。
- 原因：当前 Runtime 自己决定 action 和 long task，不再走手动 plan endpoint。
- 后续重做：作为 Runtime plan artifact 或 task template。

## 旧 Planner 上下文预算

- 功能：skill bias/token budget、历史相关性过滤、旧 planner 图像描述缓存。
- 原因：Runtime 当前不消费这些策略结果，保留会制造错误心智模型。
- 后续重做：作为 visual memory 压缩器或 Runtime context policy。

## 旧直连 Agent fallback

- 功能：Agent 图失败后直接调生图 API 并写 agent 消息。
- 原因：主入口已统一到 Artist Runtime，不再需要第二套失败路径。
- 后续重做：如果需要降级，做成 Runtime 内部 recover action。

## 旧前端 Agent 进度展示

- 功能：按 intent / planner / executor / critic / decision 节点展示 Agent 时间线。
- 原因：前端进度已统一为 Runtime timeline，不再暴露旧 Agent 节点模型。
- 后续重做：新增工具或子 agent 时，只接入 `RuntimeProgressState` 和 `RuntimeProgressPanel`。
