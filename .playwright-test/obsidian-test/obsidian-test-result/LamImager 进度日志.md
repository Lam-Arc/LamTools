# LamImager 进度日志

> 状态：⚠️ 历史记录，非当前架构真相 | 来源：progress-log.md
>
> ⚠️ AGENTS.md 明确标注：progress-log.md 是历史日志，不是当前架构真相。

## Phase 1 — Pre-LangGraph 执行内核 ✅

- PlanningContext 统一输入
- 四个执行器：Single / Parallel / Iterative / Radiate
- 三入口收敛：Agent / Workbench / Skill → PlanExecutionService
- Sessions.vue 拆分：4082 → 1731 行

## Phase 2 — LangGraph 集成 ✅

### P2B: 8 节点图
- skill_node + context_enrichment_node
- planner_node + prompt_builder_node
- critic_node + decision_node
- Checkpoint 泛化
- PlanningContext 升级

### P2 Task 8: Skill Matcher
- skill_matcher_node（关键词重叠 + strategy_hint 评分）
- 图结构更新：intent → skill_matcher → skill → context_enrichment → planner → ...

### 10 个已知 Bug 修复
| # | 严重度 | 问题 |
|---|---|---|
| 7 | Blocker | executor_node 不接收 image_provider_id |
| 1 | Blocker | RadiateExecutor 读 plan_meta 但 planner 不产出 |
| 4 | High | intent_node items/references 未转发 |
| 8 | High | context_enrichment image_descriptions 被丢弃 |
| 10 | High | search_context 被忽略 |
| 2 | High | prompt_builder retry 不读 critic feedback |
| 3 | High | planner replan 不读 critic feedback |
| 5 | Medium | planner prompt 无策略感知 |
| 6 | Low | critic 需多模态 LLM 无通知 |
| 9 | Low | token_budget 计算但未使用 |

### Agent 日志与计费
- llm_call_logger 统一 LLM 调用日志 + 计费
- 5 节点计费（intent/planner/prompt_builder/critic/context）
- 搜索调用计费

## Phase 3 — 重新定义 ⚠️

P3 重新定义为 P3A（架构层）+ P3B（功能增强），吸收 learning-report 研读成果。

### 关键决策
- LangGraph >=1.1.10,<1.2.0（1.1.7 yanked）
- Python 3.14+ required
- `use_langgraph` 移除——图是唯一路径
- `decision_node` 是唯一的 retry 决策者
- `critic_mode=on` 默认开启
- 意图分类纯 LLM（无正则）

## 关联

- 开发路线 → [[LamImager 开发路线图]]
- 计划文档 → [[LamImager 计划演进链]]
- 已知问题 → [[LamImager 已知问题]]
