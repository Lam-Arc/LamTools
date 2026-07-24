# LamTools 执行路线

> 当前阶段：LamImager P3A（架构层搭建）。P1-P2 已完成，P3 重新定义为 P3A+P3B。
>
> **主从关系**：`docs/plans/PLAN.md` 是总控计划，决定整体执行顺序。本文档是 P3/P4 技术路线，提供架构层任务细节。如两者冲突：执行顺序以 PLAN 为准，P3/P4 任务定义以本文档为准。

## 文档索引

| 文档                             | 内容                                                    | 用途                 |
| ------------------------------ | ----------------------------------------------------- | ------------------ |
| `docs/plans/PLAN.md`           | 总控计划：P2收尾→发布→前端→P3A→P3B→P4→全家桶                        | 执行顺序               |
| `docs/ROADMAP.md`              | 本文档：P3/P4 技术路线                                        | 架构任务细节             |
| `docs/mental-model.md`         | PER/CON/PLAN/Skill 心智模型 + MEM 模块 + CON/Butler/Sage 分工 | 成员内部决策架构           |
| `docs/lamtools-ecosystem.md`   | 全家桶职责/画像/协作/角色/哲学 + UI Shell 策略                       | 产品家族定义             |
| `docs/artist-per-v1.md`        | Artist PER v1                                         | Artist 人格与行为       |
| `docs/coder-per-v1.md`         | Coder/Writer PER v1                                   | Coder/Writer 人格与行为 |
| `docs/coder-architecture.md`   | Coder/Writer 架构                                       | Coder/Writer 技术设计  |
| `docs/butler-per-v1.md`        | Butler PER v1                                         | Butler 人格与职能       |
| `docs/design-language.md`      | 品牌 Slogan + 语义体系                                      | 品牌语言               |
| `docs/competitive-research.md` | 五产品竞品分析                                               | 竞品参考               |

---

## P3 重新定义

P3 原定的"偏好评分"和"Plan 自动保存"与 learning-report 识别的改造项高度重合（90%/80%），不是额外工作而是同一件事。P4 要抽取 Core SDK，但 Core SDK 需要先有东西可抽——P3 必须先把 PER/CON/Skill/Prompt 组装线做好。详见 `docs/learning-report.md` 第十节。

---

## P3A：架构层搭建（PER/CON/Skill/Prompt 组装线/MEM Lite）

建立 mental-model.md 定义的运行时系统，替换现有硬编码逻辑。

### 依赖顺序

```
ImageContextResolver（独立，无依赖）
PER ──→ Skill 两层注入（需要 PER 过滤）
  │
  ├──→ Prompt 组装线（需要 PER + Skill + CON）
  │
  └──→ MEM Lite / CON 六层基础（组装线消费 HotCON）
```

> MEN 层已砍掉（见 `mental-model.md`）：PER 锁住人格基调，CON 提供情境信号，LLM 结合两者自行调节思维模式，不需要预设模式集和运行时切换。

### 任务清单

- [x] **P3A-0 ImageContextResolver** — 修改意图自动转发目标图
  - 新增 `backend/app/core/image_context_resolver.py`
  - 检测 modify/refine/reference/batch intent
  - 目标唯一时自动转发 reference_images
  - 多图歧义时返回追问
  - 无修改意图不自动污染 reference_images
  - 交付标准：用户说"改一下/线稿化"时自动携带上一张图进入编辑链路

- [ ] **P3A-1 PER 层** — `PersonaDef` + `PERSONAS` 注册表
  - 新增 `backend/app/core/persona.py`
  - sidebar_assistant / imager 两个角色定义
  - `skill_whitelist` / `tool_whitelist` 过滤字段
  - 修改 `graph.py`（绑定 persona）、`graph_llm.py`（读取 persona）
  - 交付标准：`PersonaDef` 可实例化 + sidebar/agent mode 绑定不同 persona

- [ ] **P3A-2 Skill 两层注入** — `SkillInjector` Layer 1/Layer 2 + PER 过滤
  - 新增 `backend/app/core/skill_injector.py`
  - Layer 1：名称+描述注入 system prompt（~100 token/skill），经 PER 过滤
  - Layer 2：按需加载完整内容（~2000 token/skill），LLM 通过 tool 调用触发
  - 修改 `skill_node.py`（改用 injector）、`skill_engine.py`（提供 layer1/layer2 接口）
  - 交付标准：Layer 1 描述注入生效 + token 消耗下降

- [ ] **P3A-3 Prompt 组装线** — `PromptAssembler`
  - 新增 `backend/app/core/prompt_assembler.py`
  - 五层组装顺序：PER → Skill → Hot CON(任务) → Hot CON(画像) → 历史PLAN
  - 修改 `capability_prompts.py`（降级为片段提供者）
  - 修改各节点（改用 assembler 替代硬编码组装）
  - 交付标准：`PromptAssembler` 替换所有节点的硬编码组装

- [ ] **P3A-4 MEM Lite / CON 六层基础** — `MEMModule`
  - 新增 `backend/app/core/mem/` 目录
    - `schemas.py` — CON 六层 schema（Messages / Hot CON / Active State / Open Loops / Cold CON / Log）
    - `stores.py` — Cold CON / Log 读写
    - `recall.py` — 三层召回管线（确定性 → 语义标签 → LLM rerank）
    - `writer.py` — 规则提取 + LLM 摘要写入 + schema 校验
    - `lifecycle.py` — Hot CON / Active State / Open Loops 生命周期
    - `budget.py` — token 预算分配与裁剪
    - `provenance.py` — 偏好溯源
    - `adapters/artist.py` — Artist 成员适配器
  - Cold CON 存储：`output_index` / `user_preferences` / `error_patterns` / `conversation_summaries` / `plan_library` / `open_loops_index`
  - 简单加权召回，不做复杂评分
  - 不做 Sage / Butler / 跨成员治理 / 自动知识抽象 / 完整 snapshot rollback
  - 预留 `mem_maintainer` 接口（compress / merge / audit / reconcile），不实现
  - 预留 `sage_review` schema，不实现
  - 修改 `planning_context.py`（降级为 HotCON 的计算引擎）
  - 交付标准：六层可分别读写 + 简单召回生效 + Artist adapter 可用

---

## P3B：功能增强（画像/PLAN 持久化/压缩/身份重注入/Guardrail）

在 P3A 架构层之上，叠加具体功能。包含 P3 原定项。

### 依赖顺序

```
MEM Lite / CON 六层基础 ──→ ImagerProfile（画像进 HotCON）
      │
      ├──→ PLAN 持久化（ColdCON 存历史 PLAN）
      │         │
      │         └──→ Plan 自动保存与复用
      │
      ├──→ micro_compact（HotCON 内部压缩）
      │         │
      │         └──→ 身份重注入（compact 后重注入 PER）
      │
      ├──→ Guardrail / Error Patterns（从 MEM Lite 的 error_patterns 生成 preflight checks）
      │
      └──→ ImagerProfile + PLAN 持久化 ──→ 历史PLAN 匹配

独立（无 P3A 强依赖）：
  ImageContextResolver → Nag Reminder → CriticOutput 标准化 → Mask 精修
```

### 任务清单

- [ ] **P3B-1 ImagerProfile 画像** — 从生成历史提取审美偏好
  - 新增 `backend/app/services/profile.py`
  - 维度：style_preferences、color_tendencies、iteration_patience、quality_sensitivity、size_habits
  - 单成员临时偏好，低置信度，不设权重天花板
  - 作为 CON(画像) 层注入 prompt（只有高权重进 HotCON）
  - 依赖：P3A-4 MEM Lite + P3A-3 Prompt 组装线

- [ ] **P3B-2 PLAN 持久化 + 依赖图** — `ExecutionPlanV2` + blockedBy + JSON 持久化
  - 修改 `backend/app/schemas/execution.py`（增加 dependencies 字段）
  - 新增 `backend/app/services/plan_persistence.py`（JSON 文件持久化 + 断点续执行）
  - `next_ready_steps()` 计算可执行步骤
  - 依赖：P3A-4 MEM Lite（ColdCON 存历史 PLAN）

- [ ] **P3B-3 micro_compact** — 每轮静默压缩旧 tool result
  - 修改 `backend/app/core/mem/lifecycle.py`（HotCON.compact()）
  - 保留最近 3 个 tool result，旧结果替换为摘要
  - 依赖：P3A-4 MEM Lite

- [ ] **P3B-4 身份重注入** — 压缩后自动重注入 PER 身份块
  - 修改 `backend/app/core/mem/lifecycle.py`（compact 后检查是否需要重注入）
  - 防止 Agent 在上下文压缩后忘记角色
  - 依赖：P3A-1 PER 层 + P3A-4 MEM Lite

- [ ] **P3B-5 Nag Reminder** — executor 长时间不更新进度时注入提醒
  - 修改 `backend/app/core/agent/graph.py`（executor_node 循环中检查）
  - 3 轮无进度更新时注入 system reminder
  - 无强依赖，可独立推进

- [ ] **P3B-6 Plan 自动保存与复用** — P3 原定项
  - 新增 `backend/app/core/agent/nodes/plan_saver_node.py`
  - 每次生成的 plan 永久保存，支持精确匹配复用
  - 依赖：P3B-2 PLAN 持久化

- [ ] **P3B-7 CriticOutput 标准化** — P3 原定项
  - 修改 `backend/app/core/agent/critic_interface.py`
  - 修改 `backend/app/core/agent/nodes/critic_node.py`
  - 修改 `backend/app/core/agent/nodes/decision_node.py`
  - CriticOutput 从 P2 的 dataclass 升级为 P3 的结构化输出
  - 无强依赖，可独立推进

- [ ] **P3B-8 Mask 精修** — P3 原定项
  - 新增 `backend/app/services/mask_refinement.py`
  - 图像局部编辑能力
  - 无强依赖，可独立推进

- [ ] **P3B-9 Guardrail / Error Patterns** — 从错误模式生成执行前检查
  - 新增 `backend/app/core/guardrail.py`
  - 从 MEM Lite 的 `error_patterns` 生成 preflight checks
  - 先内置 `modify_intent_missing_reference_image`
  - 每次生成前检查，命中时自动修正或追问
  - 依赖：P3A-4 MEM Lite

---

## P4：Core SDK 抽取

P3 完成后，LamImager 内部已有 PER/CON/PLAN/Skill/MEM 的完整架构层。P4 的任务是从 Imager 中把这些架构层**抽取**为 Core SDK，而不是开发新功能。

### 任务清单

- [ ] Core SDK 抽取
  - `PersonaDef` → `lamtools-core/persona/`
  - `MEMModule` → `lamtools-core/mem/`（base + adapters）
  - `SkillInjector` → `lamtools-core/skill/`
  - `PromptAssembler` → `lamtools-core/prompt/`
  - `ImagerProfile` → `lamtools-core/profile/`（泛化为通用画像接口）
  - `LamEvent` + `EventLog` → `lamtools-core/event/`
  - `Guardrail` → `lamtools-core/guardrail/`
  - 计费模块 → `lamtools-core/billing/`
  - LLM 客户端 → `lamtools-core/llm/`

### Imager 独立仓库化

Core SDK 抽取完成后，Imager 迁移至 `import lamtools_core`，成为独立仓库。

---

## 后续成员启动条件

| 成员 | 启动条件 | 核心差异 |
|------|---------|---------|
| LamCoder | Core SDK 可用 | while(true) loop + 文件系统权限 + Coder adapter |
| LamButler | Core SDK + Coder + Imager 在线 | MEM Maintainer + 跨成员调度 + 评价三档 |
| LamSage | Core SDK + Butler 在线 | MEM Judgment + 入库验证 + 多源交叉印证 |
| LamMate | Core SDK + 多成员活动数据 | 画像推断人格 + 情感陪伴 + 成员活动反向同步 |

---

## 待定项

| 项 | 说明 | 优先级 |
|----|------|--------|
| 跨设备账号同步 | Butler v2 远程同步，架构不留死路 | 远期 |
| 隐私边界控制 | 用户可控画像采集维度开关 | 远期 |
| MCP 工具层集成 | 工具标准化接口，等 Coder/Writer 工具需求爆发时引入 | 中期 |
| 版式设计画布 | Loomic 式空白画布 AI 自由排版 | 备选 |
| 桌宠 Native Shell | 存在感层，等全家桶多成员并行时引入 | 中期 |