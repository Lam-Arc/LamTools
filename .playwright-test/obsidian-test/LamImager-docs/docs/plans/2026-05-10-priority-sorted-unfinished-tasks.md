# LamImager 未完成事项优先级文档

**目标**：梳理当前所有仍值得推进的事项，按业务价值、架构依赖、实施时机排序，避免明天开工时被旧计划淹没。

**排序原则**：
1. 先影响当前可用性和上线质量的
2. 再影响核心架构收敛的
3. 再做体验增强
4. 最后做生态级、桌面级、大重构

---

## Priority P0：当前必须先做

这些事项直接关系到 Agent 模式能不能稳定上线给朋友用，以及做架构收敛时会不会踩雷。

### P0-1. 规划系统显性缺口修复
**来源文档**：`2026-05-09-plan-system-gaps.md`

**为什么最高优先**
- 很多是"现在就会出错"的问题
- 直接影响套图、模板、规划执行正确性

**重点项**
- 内置 radiate 模板变量替换
- radiate checkpoint 实际不阻塞
- plan 模板 schema 与真实消费不一致
- 前后端 parallel / iterative 语义不一致
- 模板验证缺失
- 结果缺少 step 级关联

**建议状态**：明天开工先看这份

---

### P0-2. Agent 模式剩余功能 bug 与回归
**来源文档**：`2026-05-09-lamtools-ecosystem.md` 的 Phase 0

**为什么高优先**
- 自己说现在仍在 P0
- 上 GitHub 和初步宣传前，必须把当前用户可见问题压下去

**重点项**
- 套图、单图、多图、搜索、取消、checkpoint 的完整回归
- SSE 行为检查
- 计费完整性检查
- session 消息一致性检查

**建议状态**：和 P0-1 并行思考，但先修最影响使用的 bug

---

### P0-3. 发布准备
**来源文档**：`2026-05-09-lamtools-ecosystem.md`

**包括**
- README
- LICENSE
- 版本号
- CHANGELOG
- .gitignore
- 配置教程

**为什么是 P0**
- 功能不发布就没有真实反馈
- 不是技术债，是项目推进的关键动作

---

## Priority P1：下一阶段主线，必须做的架构收敛

这些不是"立刻上线阻塞"，但它们是引入 LangGraph 前最重要的基础工程。如果不做，LangGraph、LamAssistant、LamArtist 都会建立在松散地基上。

### P1-1. Pre-LangGraph 执行内核收敛
**来源文档**：`2026-05-12-p1-pre-langgraph.md`

**这是最值得作为主执行文档的一份。**

**核心目标**
- 统一 ExecutionPlan
- 统一 PlanStep
- 统一 Artifact
- 统一 ExecutionTrace
- 新增 PlanExecutionService
- 把 single / parallel / iterative / radiate 收敛成统一后端执行器

**为什么是 P1**
- 不是当前 bug 修复
- 但决定未来所有能力会不会继续分散
- 是 LangGraph 前的必要收敛步骤

**建议执行顺序**
1. 核心模型
2. 模板输出统一
3. PlanExecutionService
4. 四种执行器
5. Agent / Workbench 两入口收敛
6. Artifact / Trace / 测试
7. skill / context / plan 三层接口位与语义边界

---

### P1-2. Pre-LangGraph 理想架构对照
**来源文档**：`2026-05-10-pre-langgraph-ideal-architecture.md`

**定位**：设计约束文档，不是主施工文档

**为什么重要**
- 开工时如果不参照，很容易在局部 patch 中偏航
- 提醒以下原则：
  - Agent 和 Workbench 要共享同一个执行内核
  - 不要再把 parallel / iterative 留在前端
  - 不要继续让 handle_agent_generate() 做一堆策略特判
  - 不要只返回 image_urls，要走 Artifact
  - skill / context / plan 是三层语义，不应继续混层

**建议**：开工时开着，每完成一个任务回头核对

---

### P1-3. 规划执行链的一致性修复
P0 和 P1 的交叉项，值得单独列出。

**核心问题**
- plan tool 有了，但 plan 不是统一执行入口
- Agent 模式和 Workbench 模式执行方式不同
- radiate / parallel / iterative 三种 strategy 的宿主不一致

**落地目标**
- plan -> ExecutionPlan -> Executor
- 不再有时前端、有时后端、有时 Agent 自己 consume tool result 后分派

---

### P1-4. Skill / Context / Plan 分层落地
**来源文档**：`2026-05-11-future-roadmap-skill-context-plan.md`

**为什么是 P1**
- skill 现在几乎废弃，必须在 P1 里恢复其“思考偏置层”角色
- context 现在仍然散传，不是 planner 的统一输入
- 不先分层，LangGraph 会接到混乱语义而不是清晰模块

**核心目标**
- 引入 `PlanningContext`
- 重定义 skill 数据模型
- 让 skill 真正进入 planner / prompt builder 主链
- 让 plan 退回执行结构层

---

## Priority P2：中期增强，收敛后再做

### P2-1. Agent 流式体验完善
**来源文档**：`2026-05-09-agent-streaming-overhaul.md`

**为什么是 P2**
- 当前更缺"执行正确性"，不是"流得多漂亮"
- 但后续用户体验会强依赖它

**内容**：更完整的 token/tool/step 级事件流，前端更细粒度展示，断线恢复/事件回放

---

### P2-2. 意图编排进一步稳定
**来源文档**：
- `2026-05-09-agent-intent-orchestration.md`
- `2026-05-09-agent-intent-orchestration-implementation.md`

**为什么是 P2**
- intent routing 已开始起作用
- 当前更大的问题是执行链不统一
- 等 P1 收敛完，intent 才更容易接到稳定执行器上

---

### P2-3. 模板与工作台体验增强
**来源文档**：`2026-05-09-plan-system-gaps.md` Phase 3

**内容**
- 动态变量控件
- 模板预览
- 模板导入导出
- radiate 策略在 UI 暴露
- step 级结果关联

---

### P2-4. image-aware / refinement / 计费细化
**来源文档**：
- `2026-05-08-image-aware-context-and-refinement*.md`
- `2026-05-08-billing-token-fixes.md`
- `2026-05-09-image-count-*.md`

**原因**：都是增强项或局部优化，不应在当前主架构未收敛时优先推进。

---

## Priority P3：长期规划，暂缓

这些事项明确重要，但不是现在该投入主要精力的。

### P3-1. LamTools 生态总路线
**来源文档**：`2026-05-09-lamtools-ecosystem.md`

**定位**：顶层路线图，决定大方向。防止当前局部改动破坏未来 LamAssistant/LamArtist/Monorepo/Tauri 方向。

---

### P3-2. Monorepo / Core 抽包 / Cross-Product Invoke
现在先知道方向，不急着实现。等 LamImager 的 pre-LangGraph 内核稳定后再做。

---

### P3-3. 桌面应用与打包
**来源文档**：
- `2026-05-07-desktop-app-implementation.md`
- `2026-05-07-desktop-app-packaging.md`

**原因**：已明确现在还在 P0，桌面壳不是当前核心矛盾。

---

### P3-4. 早期历史文档
包括 `2026-05-06-*`、`2026-05-07-remove-tasks-merge-into-sessions*`、`2026-05-08-agent-phase2-*`、`2026-05-08-agent-phase3-*`、`2026-05-08-agent-tool-calling*`

**建议**：不删除，作为历史设计参考，不再作为当前执行依据。

---

## 建议保留的当前有效计划文档

明天真正要看的，更新为这 5 份：

### 1. `2026-05-09-plan-system-gaps.md`
规划系统缺口修复清单，P0 主文档

### 2. `2026-05-12-p1-pre-langgraph.md`
P1 当前主施工文档（已替代 2026-05-10 版本）

### 3. `2026-05-10-pre-langgraph-ideal-architecture.md`
理想架构蓝图，P1 设计约束文档

### 4. `2026-05-11-future-roadmap-skill-context-plan.md`
skill / context / plan 三层分工专项路线图

### 5. `2026-05-09-lamtools-ecosystem.md`
生态总路线图，总纲文档

---

## 明天实施的推荐顺序

### 阶段 1：先修当前最致命问题
看 `2026-05-09-plan-system-gaps.md`，把会直接影响当前使用的问题修掉

### 阶段 2：开始 pre-LangGraph 内核收敛
看 `2026-05-12-p1-pre-langgraph.md` + `2026-05-10-pre-langgraph-ideal-architecture.md`

### 阶段 2.5：始终用三层语义边界防跑偏
看 `2026-05-11-future-roadmap-skill-context-plan.md`

### 阶段 3：始终用总路线图防跑偏
看 `2026-05-09-lamtools-ecosystem.md`，所有改动都不违背 LamTools 未来方向

---

## 最终优先级摘要

| 优先级 | 文档 | 动作 |
|--------|------|------|
| P0 | `2026-05-09-plan-system-gaps.md` | 修缺口，修 bug |
| P0 | `2026-05-09-lamtools-ecosystem.md` Phase 0 | 发布准备 |
| P1 | `2026-05-12-p1-pre-langgraph.md` | 统一执行内核 |
| P1 | `2026-05-10-pre-langgraph-ideal-architecture.md` | 设计约束对照 |
| P1 | `2026-05-11-future-roadmap-skill-context-plan.md` | skill/context/plan 分层落地 |
| P2 | 流式 / intent / 模板体验 / 计费细化 | 增强项 |
| P3 | Monorepo / LamAssistant / Tauri / 老文档 | 暂缓 |
