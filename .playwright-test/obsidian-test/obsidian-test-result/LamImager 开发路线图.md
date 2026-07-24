# LamImager 开发路线图

> 状态：✅ 有效 | 来源：ROADMAP.md, progress-log.md, CHANGELOG.md
>
> 完整的开发阶段：从初始发布到 P4 Core SDK 抽取计划。

## 阶段总览

```
Phase 1 (P1) — Pre-LangGraph 执行内核        ✅ 完成
Phase 2 (P2) — LangGraph 集成                 ✅ 完成
Phase 3A     — 架构层搭建 (PER/CON/Skill/Prompt/MEM)  ⚠️ 部分完成
Phase 3B     — 功能增强 (画像/PLAN持久化/压缩...)     ❌ 未完成
Phase 4 (P4) — Core SDK 抽取                   ❌ 未完成
```

## Phase 1 — Pre-LangGraph 执行内核 ✅

- PlanningContext 统一输入
- ExecutionPlan / PlanStep / Artifact / StepTrace schema
- 四个执行器：Single / Parallel / Iterative / Radiate
- 三入口收敛：Agent / Workbench / Skill → PlanExecutionService
- Sessions.vue 拆分：4082 → 1731 行（-57%），14 个子组件

## Phase 2 — LangGraph 集成 ✅

### P2A: 侧边栏助手 2 节点图
```
agent_node (LLM + tools) ⇄ tools_node → END
```

### P2B: Agent Mode 9 节点图
```
intent → skill_matcher → skill → context_enrichment → planner 
→ prompt_builder → executor → critic → decision
```

### 关键变更
- Python 3.9 → 3.14
- 意图分类：~550 行正则 → 纯 LLM 分类
- critic_mode 默认开启
- 全链路 LLM 调用计费
- 10 个已知数据流 bug 修复

## Phase 3A — 架构层搭建 ⚠️

| 任务 | 状态 | 说明 |
|---|---|---|
| P3A-0 ImageContextResolver | ✅ | 修改意图自动转发目标图 |
| P3A-1 PER 层 | ❌ | PersonaDef + PERSONAS 注册表 |
| P3A-2 Skill 两层注入 | ❌ | SkillInjector Layer 1/Layer 2 |
| P3A-3 Prompt 组装线 | ❌ | PromptAssembler 五层组装 |
| P3A-4 MEM Lite / CON 六层 | ❌ | MEMModule（schemas/stores/recall/writer...） |

> ⚠️ 注意：runtime-removed-feature-inventory.md 显示旧 Agent 图、旧 Persona 注册表等已被移除。P3A 的 PER/Skill/Prompt 组装线可能已被 Artist Runtime 内聚实现替代，而非按原计划落地。需对照源码确认。

## Phase 3B — 功能增强 ❌

| 任务 | 说明 |
|---|---|
| P3B-1 ImagerProfile 画像 | 从生成历史提取审美偏好 |
| P3B-2 PLAN 持久化 + 依赖图 | ExecutionPlanV2 + blockedBy |
| P3B-3 micro_compact | 每轮静默压缩旧 tool result |
| P3B-4 身份重注入 | 压缩后自动重注入 PER |
| P3B-5 Nag Reminder | executor 长时间无进度时注入提醒 |
| P3B-6 Plan 自动保存与复用 | 每次生成的 plan 永久保存 |
| P3B-7 CriticOutput 标准化 | dataclass → 结构化输出 |
| P3B-8 Mask 精修 | 图像局部编辑 |
| P3B-9 Guardrail / Error Patterns | 从错误模式生成执行前检查 |

## Phase 4 — Core SDK 抽取 ❌

从 LamImager 内部抽取架构层为独立 SDK：
- PersonaDef → `lamtools-core/persona/`
- MEMModule → `lamtools-core/mem/`
- SkillInjector → `lamtools-core/skill/`
- PromptAssembler → `lamtools-core/prompt/`
- LamEvent + EventLog → `lamtools-core/event/`
- 计费/LLM客户端 → `lamtools-core/billing/`, `lamtools-core/llm/`

> P4 完成后，Imager 迁移至 `import lamtools_core`，成为独立仓库。这就是 LamTools 的诞生路径。

## 后续成员启动条件

| 成员 | 启动条件 |
|---|---|
| LamCoder | Core SDK 可用 |
| LamButler | Core SDK + Coder + Imager 在线 |
| LamSage | Core SDK + Butler 在线 |
| LamMate | Core SDK + 多成员活动数据 |

## 关联

- 进度详情 → [[LamImager 进度日志]]
- 计划文档 → [[LamImager 计划演进链]]
- 心智模型 → [[LamImager 心智模型]]
- 生态设计 → [[LamTools 生态设计]]
