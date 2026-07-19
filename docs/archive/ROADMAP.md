<!-- 历史参考，不代表当前架构 -->
# LamTools 执行路线

> 当前阶段：lamartist P3B（功能增强）。P1-P2 已完成，P3A 架构层已完成，P3B-1~P3B-9 已完成，P3B-10 Artist Completion Before P4 进行中。
>
> **主从关系**：`docs/plans/PLAN.md` 是总控计划，决定整体执行顺序。本文档是 P3/P4 技术路线，提供架构层任务细节。如两者冲突：执行顺序以 PLAN 为准，P3/P4 任务定义以本文档为准。

## 文档索引

| 文档                             | 内容                                                    | 用途                 |
| ------------------------------ | ----------------------------------------------------- | ------------------ |
| `docs/plans/PLAN.md`           | 总控计划：P2收尾→发布→前端→P3A→P3B→P4→全家桶                        | 执行顺序               |
| `docs/ROADMAP.md`              | 本文档：P3/P4 技术路线                                        | 架构任务细节             |
| `docs/mental-model.md`         | PER/CON/PLAN/Skill 心智模型 + MEM 模块 + CON/Butler/Sage 分工 | 成员内部决策架构           |
| `docs/lamtools-ecosystem.md` | 全家桶职责/画像/协作/角色/哲学 + UI Shell 策略 | 产品家族定义 |
| `docs/lamtools-philosophy.md` | LamTools/LamTwo 哲学命题、漏洞拆解、主体性验证框架 | 哲学探讨 |
| `docs/lamtwo-persona-v0.1.md` | LamTwo 人格画像、权力观、腐化预警、遗漏项 | LamTwo 人格定义 |
| `docs/artist-per-v1.md`        | Artist PER v1                                         | Artist 人格与行为       |
| `docs/writer-per-v1.md`         | Writer PER v1                                   | Writer 人格与行为 |
| `docs/writer-architecture.md`   | Writer 架构                                       | Writer 技术设计  |
| `docs/butler-per-v1.md`        | Butler PER v1                                         | Butler 人格与职能       |
| `docs/design-language.md`      | 品牌 Slogan + 语义体系                                      | 品牌语言               |
| `docs/competitive-research.md` | 五产品竞品分析                                               | 竞品参考               |

---

## P3 重新定义

P3 原定的"偏好评分"和"Plan 自动保存"与学习资料识别的改造项高度重合（90%/80%），不是额外工作而是同一件事。P4 要抽取 Core SDK，但 Core SDK 需要先有东西可抽——P3 必须先把 PER/CON/Skill/Prompt 组装线做好。交叉论证入口见 `docs/2026-05-20-writer-architecture.md`，源码资料在 `docs/learning files/`。

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

- [x] **P3A-1 PER 层** — `PersonaDef` + `PERSONAS` 注册表
  - 新增 `backend/app/core/persona.py`
  - sidebar_assistant / Artist 两个角色定义
  - `skill_whitelist` / `tool_whitelist` 过滤字段
  - 修改 `graph.py`（绑定 persona）、`graph_llm.py`（读取 persona）
  - 交付标准：`PersonaDef` 可实例化 + sidebar/agent mode 绑定不同 persona

- [x] **P3A-2 Skill 两层注入** — `SkillInjector` Layer 1/Layer 2 + PER 过滤
  - 新增 `backend/app/core/skill_injector.py`
  - Layer 1：名称+描述注入 system prompt（~100 token/skill），经 PER 过滤
  - Layer 2：按需加载完整内容（~2000 token/skill），LLM 通过 tool 调用触发
  - 修改 `skill_node.py`（改用 injector）、`skill_engine.py`（提供 layer1/layer2 接口）
  - 交付标准：Layer 1 描述注入生效 + token 消耗下降

- [x] **P3A-3 Prompt 组装线** — `PromptAssembler`
  - 新增 `backend/app/core/prompt_assembler.py`
  - 五层组装顺序：PER → Skill → Hot CON(任务) → Hot CON(画像) → 历史PLAN
  - 修改 `capability_prompts.py`（降级为片段提供者）
  - 修改各节点（改用 assembler 替代硬编码组装）
  - 交付标准：`PromptAssembler` 替换所有节点的硬编码组装

- [x] **P3A-4 MEM Lite / CON 六层基础** — `MEMModule`
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

- [x] **P3B-1 ImagerProfile 画像** — 从生成历史提取审美偏好
  - 新增 `backend/app/services/profile.py`
  - 维度：style_preferences、color_tendencies、iteration_patience、quality_sensitivity、size_habits
  - 单成员临时偏好，低置信度，不设权重天花板
  - 作为 CON(画像) 层注入 prompt（只有高权重进 HotCON）
  - 依赖：P3A-4 MEM Lite + P3A-3 Prompt 组装线

- [x] **P3B-2 PLAN 持久化 + 依赖图** — `ExecutionPlanV2` + blockedBy + JSON 持久化
  - 修改 `backend/app/schemas/execution.py`（增加 dependencies 字段）
  - 新增 `backend/app/services/plan_persistence.py`（JSON 文件持久化 + 断点续执行）
  - `next_ready_steps()` 计算可执行步骤
  - 依赖：P3A-4 MEM Lite（ColdCON 存历史 PLAN）

- [x] **P3B-3 micro_compact** — 每轮静默压缩旧 tool result
  - 修改 `backend/app/core/mem/lifecycle.py`（HotCON.compact()）
  - 保留最近 3 个 tool result，旧结果替换为摘要
  - 依赖：P3A-4 MEM Lite

- [x] **P3B-4 身份重注入** — 压缩后自动重注入 PER 身份块
  - 修改 `backend/app/core/mem/lifecycle.py`（compact 后检查是否需要重注入）
  - 防止 Agent 在上下文压缩后忘记角色
  - 依赖：P3A-1 PER 层 + P3A-4 MEM Lite

- [x] **P3B-5 Nag Reminder** — executor 长时间不更新进度时注入提醒
  - 修改 `backend/app/core/agent/graph.py`（executor_node 循环中检查）
  - 3 轮无进度更新时注入 system reminder
  - 无强依赖，可独立推进

- [x] **P3B-6 Plan 自动保存与复用** — P3 原定项
  - 新增 `backend/app/core/agent/nodes/plan_saver_node.py`
  - 每次生成的 plan 永久保存，支持精确匹配复用
  - 依赖：P3B-2 PLAN 持久化

- [x] **P3B-7 CriticOutput 标准化** — P3 原定项
  - 修改 `backend/app/core/agent/critic_interface.py`
  - 修改 `backend/app/core/agent/nodes/critic_node.py`
  - 修改 `backend/app/core/agent/nodes/decision_node.py`
  - CriticOutput 从 P2 的 dataclass 升级为 P3 的结构化输出
  - 无强依赖，可独立推进

- [x] **P3B-8 Mask 精修** — P3 原定项
  - 新增 `backend/app/services/mask_refinement.py`
  - 图像局部编辑能力
  - 无强依赖，可独立推进

- [x] **P3B-9 Guardrail / Error Patterns** — 从错误模式生成执行前检查
  - 新增 `backend/app/core/guardrail.py`
  - 从 MEM Lite 的 `error_patterns` 生成 preflight checks
  - 先内置 `modify_intent_missing_reference_image`
  - 每次生成前检查，命中时自动修正或追问
  - 依赖：P3A-4 MEM Lite

- [ ] **P3B-10 Artist Completion Before P4** — Artist 作为默认创作主体，P4 前完成产品闭环
  - Artist 是独立 ArtistRuntime，不是 graph 内节点，也不是 `artist_service.py` 单函数原型
  - 核心循环：PER + CON → LLM action proposal → ArtistTurn schema 校验 → 受控 action 执行 → Artist artifact metadata → CON 写回
  - `persona_name="artist"` 绑定 `PersonaDef("artist")`，通过 PER 锁住人格基调
  - `persona_name="agent"` 保留直接执行 / 高级工具态；旧 `Artist` 命名仅作兼容 alias
  - `agent_mode` 继续表示是否走 agent pipeline，不承担 Artist / Agent 产品人格语义
  - 通过 CON 读取默认尺寸、默认数量、模型偏好、审美偏好、历史产出和 Open Loops
  - Prompt 组装顺序沿用 P3A：PER → Skill → Hot CON(任务) → Hot CON(画像) → 历史 PLAN
  - Workbench 是 Artist 的操作台 surface，不是独立人格或平级主模式
  - CON 不保存图像二进制本体；CON 只保存 image_id、artifact_url、visual_summary、aesthetic_notes、user_feedback、lineage 等索引
  - Artist 生成后经过 Vision Review 写入 output_index（visual_summary、style_tags）
  - UI 从工具面板体验转向 Artist 对话流体验：Artist stream、Artist artifact card、Lightbox、折叠设置面板
  - 锚点图 → 套图包 → 单张替换 / 精修必须由 ArtistSessionState 支撑，不靠 LLM 自由发挥
  - Artist 行为层：追问式接需求 / 创作思考流 / 审美立场 / 主动示弱 / 给你意外 / 署名
  - 依赖：P3A-0 ImageContextResolver、P3A-1 PER 层、P3A-3 Prompt 组装线、P3A-4 MEM Lite / CON 六层基础
  - 参考：`docs/plans/2026-05-14-artist-mode-design.md`、`docs/plans/2026-05-18-artist-before-p4-completion.md`、`docs/plans/2026-05-19-artist-realism-architecture.md`

---

## P4：Core SDK 抽取

P3 完成后，lamartist 内部已有 PER/CON/PLAN/Skill/MEM 的完整架构层，且 Artist 默认体验已完成。P4 的任务是从 Artist 中把这些架构层**抽取**为 Core SDK，而不是开发新功能或补 Artist 产品缺口。

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

### Artist 独立仓库化

Core SDK 抽取完成后，Artist 迁移至 `import lamtools_core`，成为独立仓库。

---

## 后续成员启动条件

> LamTwo 是远期人格收敛目标，不进入 P3/P4 实现范围。关系方向是六基础角色长期塑造 LamTwo，而不是 LamTwo 反向影响当前六角色。P3/P4 只建设 PER、CON/MEM、Guardrail、PromptAssembler、权限与边界等基础设施，保证后续成员独立可用并为长期趋同保留接口。

| 成员 | 启动条件 | 核心差异 |
|------|---------|---------|
| LamWriter → LamWriter | Core SDK 可用 | while(true) loop + 文件系统权限 + Writer adapter + Part消息模型 + Git策略 + 权限分级 + 22工具 + 上下文压缩 |
| LamButler | Core SDK + Writer + Artist 在线 | MEM Maintainer + 跨成员调度 + 评价三档 |
| LamSage | Core SDK + Butler 在线 | MEM Judgment + 入库验证 + 多源交叉印证 |
| LamMate | Core SDK + 多成员活动数据 | 画像推断人格 + 情感陪伴 + 成员活动反向同步 |

---

## 待定项

| 项 | 说明 | 优先级 |
|----|------|--------|
| 跨设备账号同步 | Butler v2 远程同步，架构不留死路 | 远期 |
| 隐私边界控制 | 用户可控画像采集维度开关 | 远期 |
| MCP 工具层集成 | 工具标准化接口，等 Writer 工具需求爆发时引入 | 中期 |
| 版式设计画布 | Loomic 式空白画布 AI 自由排版 | 备选 |
| 桌宠 Native Shell | 存在感层，等全家桶多成员并行时引入 | 中期 |
