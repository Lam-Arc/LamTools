# Future Roadmap with Skill / Context / Plan Layering

> **For agentic workers:** Use executing-plans or subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在当前 L2 可用基础上，梳理 `docs/plans/` 中仍未执行的主线计划，并把 `skill / context / plan` 的定位与分工正式纳入后续架构路线，形成一份可逐步落地的未来计划文档。

**Architecture:** 保留当前“规则驱动 task_type + 固定 strategy 映射 + LLM 规划增强”的可用架构，先完成 P0 收尾验证，再进入 P1 的 `ExecutionPlan -> PlanExecutionService -> Executor` 收敛；在此基础上，将 `skill` 定位为思考偏置层、`context` 定位为运行时事实层、`plan` 定位为执行结构层，为后续 LangGraph、LamAssistant、LamArtist 留出一致的语义边界。

**Tech Stack:** Python / FastAPI / SQLAlchemy async / Vue3 / SSE / 未来 LangGraph

---

## 一、当前 `docs/plans/` 未执行主线梳理

### 当前仍然有效、且尚未正式执行的核心文档

#### 1. `2026-05-09-plan-system-gaps.md`

**定位：** 当前 P0/P1 之间的缺口修复文档。

**主要未执行内容：**
- radiate checkpoint 真正阻塞
- 模板动态变量控件
- 模板预览
- 模板导入导出
- step 级结果索引
- radiate 在工作台 UI 中显式暴露

**依赖关系：**
- 一部分属于 P0 收尾（用户可见 bug）
- 一部分应放到 P1/P2（plan 与执行内核收敛后再做）

#### 2. `2026-05-10-pre-langgraph-ideal-architecture.md`

**定位：** Pre-LangGraph 的目标架构蓝图。

**主要未执行内容：**
- `ExecutionPlan`
- `Artifact`
- `ExecutionTrace`
- `PlanExecutionService`
- Agent / Workbench 共用后端执行入口

**依赖关系：**
- 这是 P1 的设计约束，不直接执行，但必须作为实施对照

#### 3. `2026-05-10-pre-langgraph-implementation.md`

**定位：** Pre-LangGraph 的主施工文档。

**主要未执行内容：**
- 核心执行模型
- 模板 apply 输出结构化
- PlanExecutionService
- single / parallel / iterative / radiate 执行器收敛
- Workbench 不再前端执行
- Artifact / Trace / 测试

**依赖关系：**
- 这是 P1 的主实施计划

#### 4. `2026-05-09-lamtools-ecosystem.md`

**定位：** 总路线图。

**主要未执行内容：**
- P1 后端目录重组 `core/` / `imager/`
- 跨产品 invoke / capabilities 预埋
- EventBus / Artifact 协议
- Monorepo / LamAssistant / Tauri 后续路线

**依赖关系：**
- 作为总纲，不应在 P0 阶段直接展开执行

### 当前应视为历史参考、但不再作为主执行依据的文档

- `2026-05-10-agent-pipeline.md`
  - 已被当前代码大量吸收（固定 strategy 路由、4 类 task_type、执行器方向）
  - 仍可当历史记录，但不再作为主计划
- `2026-05-10-priority-sorted-unfinished-tasks.md`
  - 作为优先级导航仍有效，但需要被本文档更新覆盖
- `architecture-current-vs-ideal.html`
  - 作为结构展示材料有效，但不是执行计划

---

## 二、未来架构的新增原则：Skill / Context / Plan 三层分工

### 1. Skill：思考偏置层

负责：
- 思考方式
- 计划总方针
- 创作偏置
- 约束原则
- 质量偏好

不负责：
- 具体步骤
- 执行顺序
- 具体工具调用
- 最终 prompt 全文

一句话：

> `skill` 决定“怎么想”，不直接决定“怎么做”。

### 2. Context：运行时事实层

负责：
- 用户当前输入
- 参考图 / 上下文图
- 搜索结果
- 历史消息
- 用户偏好（未来 memory）
- 模式（agent / workbench / assistant）

不负责：
- 决定任务哲学
- 决定高层创作原则

一句话：

> `context` 决定“当前真实条件是什么”。

### 3. Plan：执行结构层

负责：
- strategy
- steps
- step dependencies
- checkpoint
- expected outputs
- tool-level execution structure

不负责：
- 创作哲学
- 长期偏置
- 高层审美取向

一句话：

> `plan` 决定“具体怎么做”。

### 4. 三层关系

建议采用以下工程解释，而不是严格的数学可逆类比：

- `skill` 与 `plan` 是两个不同语义层
- 二者不是严格可逆，不要求精确互转
- `context` 会调制 `skill -> plan` 的转换结果
- LLM 是近似转换器，不是确定性函数

可写成：

```text
ExecutionPlan ≈ Planner(skill, context, intent) + LLM uncertainty
```

---

## 三、路线图更新：把三层分工纳入后续实施

### Phase 0（当前）：L2 验证收尾

**目标：**
- 不再新增大功能
- 先验证当前 4 类任务是否稳定：
  - `single`
  - `multi_independent`
  - `iterative`
  - `radiate`

**重点观察：**
- 隐式 iterative 表达是否仍漏判
- radiate items 是否提取完整
- radiate anchor 是否混入 final images
- checkpoint 是否只在 radiate anchor 触发
- 会话级图片上下文是否真的进入思考链

**阶段结束标准：**
- P0 用户视角验证通过
- GitHub 已推送并可小范围内测

---

### Phase 1（下一主线）：执行内核收敛

**目标：**
把当前“规则驱动 task_type + LLM 辅助规划”的可用架构，收敛成统一执行内核。

**对应主文档：**
- `2026-05-10-pre-langgraph-implementation.md`

**新增调整要求：**
- `ExecutionPlan` 设计时，预留 `skill_constraints` 与 `planning_context` 输入接口
- `PlanExecutionService` 不只接 `plan`，还要接未来的 `PlanningContext`
- Workbench 后端执行统一后，前端只负责编辑和观察，不再承担执行语义

**本阶段不做：**
- LangGraph
- LamAssistant 跨产品调用
- skill 全量重做

---

### Phase 1.5（新增过渡阶段）：Skill 复活与 Context 显式化

这是本次讨论后新增的阶段，目的是避免 P1 完成后 skill 仍然废弃、context 仍然散传。

**目标：**
1. 定义最小 `PlanningContext`
2. 重定义 `skill` 数据模型
3. 让 `skill` 真正进入 Planner 输入

**建议交付：**
- `PlanningContext(prompt, context_images, reference_images, reference_labels, search_context, intent, expected_count, user_preferences)`
- `skill` 的结构化 schema（至少包含 `planning_bias`、`constraints`、`consistency_required`、`search_policy`）
- Planner 输入改为：

```text
intent + skill + context -> ExecutionPlan
```

**为什么必须有这一阶段：**
- 不然 skill 会继续废弃
- 不然 plan 会继续背负过多高层语义
- 不然 context 仍然不是一等公民

---

### Phase 2：LangGraph 接入

只有在以下条件满足后才建议开始：

1. `ExecutionPlan` 已稳定
2. `PlanExecutionService` 已落地
3. Workbench 不再前端执行
4. `Artifact` 与 step-level event 已形成基础协议
5. `PlanningContext` 至少已经定义出来

**LangGraph 在这里的角色：**
- 调度器升级
- 不是救火工具

**接入后节点建议：**
- `intent_node`
- `skill_node`
- `context_enrichment_node`
- `planner_node`
- `prompt_builder_node`
- `executor_node`
- `critic_node`

---

### Phase 3：LamTools 生态扩展

**目标：**
- LamAssistant
- Monorepo
- Cross-product invoke
- Tauri 桌面壳

**额外要求：**
- `skill / context / plan` 的语义边界必须在这之前固化，否则 LamAssistant 很容易把 skill 和 plan 再次混成一层“万能 agent prompt”。

---

## 四、接下来真正应该做的事（可逐步落地）

### Task 1: 更新总路线文档中的三层原则

**Files:** `docs/plans/2026-05-09-lamtools-ecosystem.md`

**Steps:**
- [ ] 新增 “规则 8：Skill / Context / Plan 语义分层原则”
- [ ] 明确三者各自负责什么 / 不负责什么
- [ ] 写明三者关系是上下文相关的近似转换，而不是严格可逆映射

**Verification:**
- [ ] 后续任何计划都能引用这条原则作为边界判断依据

**Commit:** `docs(arch): add skill context plan layering principle to ecosystem roadmap`

### Task 2: 更新 Pre-LangGraph 理想架构文档

**Files:** `docs/plans/2026-05-10-pre-langgraph-ideal-architecture.md`

**Steps:**
- [ ] 在 Planner 前显式加入 `skill constraints` 和 `context`
- [ ] 明确 LLM 的位置：Planner / Prompt Builder，而不是 Executor
- [ ] 增加一条说明：Agent / Workbench 最终都应通过 `PlanningContext` 输入 Planner

**Verification:**
- [ ] 文档中的理想链路变为：
  `intent -> skill -> context -> planner -> ExecutionPlan -> executor`

**Commit:** `docs(arch): integrate skill and context into pre-langgraph ideal architecture`

### Task 3: 更新 Pre-LangGraph 实施文档

**Files:** `docs/plans/2026-05-10-pre-langgraph-implementation.md`

**Steps:**
- [ ] 在 Task 1 前增加 `PlanningContext` 任务
- [ ] 增加 `skill` 数据模型重定义任务
- [ ] 增加“让 skill 进入 agent/planner 主链”的任务
- [ ] 调整执行顺序，使 `ExecutionPlan` 不再被设计成只吃 prompt / template / strategy

**Verification:**
- [ ] 文档不再把 skill 视为边缘功能
- [ ] `ExecutionPlan` 相关任务与 `PlanningContext` / `skill` 有清晰衔接

**Commit:** `docs(plan): update pre-langgraph implementation with skill-context-plan stages`

### Task 4: 新增 Skill / Context / Plan 专项落地文档

**Files:** `docs/plans/2026-05-11-future-roadmap-skill-context-plan.md`（本文档）

**Steps:**
- [ ] 记录当前未执行主线
- [ ] 记录三层分工原则
- [ ] 记录新增的 Phase 1.5
- [ ] 记录后续 LangGraph 的正确接入前提

**Verification:**
- [ ] 作为后续讨论和实现的总参照

**Commit:** `docs(plan): add future roadmap for skill context plan layering`

---

## 五、最终优先级

### 立刻执行
1. P0 验证收尾（用户可用性）
2. 更新 3 份主文档，把 skill/context/plan 原则补进去

### 下一阶段执行
3. `ExecutionPlan` / `PlanExecutionService` / Executor 收敛
4. `PlanningContext` 与 `skill` 数据模型落地

### 之后再做
5. LangGraph
6. LamAssistant / Monorepo / Tauri

---

## 六、一句话总结

未来的正确方向不是：

```text
prompt -> agent -> tool
```

而是：

```text
intent + skill + context -> planner -> ExecutionPlan -> executor
```

这份文档的目的，就是确保后续所有重构都朝这个方向逐步落地，而不是继续把 `skill` 废弃、把 `plan` 做成万能容器。
