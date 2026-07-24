# LamSage Architecture Design

> **For agentic workers:** This is a design document, not an implementation checklist. Use it as the architectural target when building Sage after Core SDK + Butler are online (Phase 8).

**Goal:** Design Sage as the LamTools shared knowledge foundation — not a chatbot, not a search engine, but a continuous verification presence that collects, verifies, organizes, and serves knowledge to both the user and every other LamTools member.

**Architecture:** Sage uses a dedicated runtime with verification pipeline (not LangGraph), inherits the Core SDK (PER/CON/MEM/PromptAssembler/Guardrail), and operates through a SageTurn model with knowledge-oriented actions (search, verify, cross-reference, grade, index). Sage produces knowledge entries as artifacts — each with provenance, confidence, evidence chain, and expiry.

**Tech Stack:** Python 3.14+ / FastAPI / SQLAlchemy async / Pydantic / SSE / Vue3 / Pinia / WebView (knowledge base panel)

---

## 1. What LamSage Is

```
Sage = LamTools 共享知识地基。
它不是搜索引擎，不是聊天机器人，不是文档阅读器。
它是持续运转的验证引擎——搜集、鉴别、整理、入库、服务。
全家桶里每一个成员都在它的知识地基上盖房子。
```

Sage is NOT:

```
Not a search engine (Perplexity, Google).
Not a chatbot (ChatGPT Q&A mode).
Not a document reader / RAG-only tool.
Not a note-taking app (Notion, Obsidian).
Not a "second brain" for the user — it's the FAMILY's shared brain.
```

Sage IS:

```
A continuous verification engine with PER, CON, and memory.
A knowledge service that other members query as naturally as they query their own memory.
A proactive poller that scans sources, fills gaps, and cross-validates what it knows.
A judgment layer that evaluates the truth and reusability of experience → knowledge.
A research engine that conducts deep, structured investigations — not just Q&A.
A forecasting engine that projects trends based on evidence — not prophecy, structured uncertainty.
A long-term presence that remembers what the family has learned — and how confident it is.
```

Five-word identity: **搜集 · 验证 · 研究 · 推演 · 服务** (Collect · Verify · Research · Forecast · Serve)

---

## 2. Design Principles

### 2.1 Verification Before Storage

Information must be verified before entering the knowledge base. Unverified claims are marked as such and cannot be served to downstream members. "入库前必须多源交叉验证" is not optional — it's the authority baseline.

### 2.2 Convergent Curiosity

Sage's curiosity fills gaps on the existing knowledge map — it does not draw new continents (that's Creator's job). When Sage detects adjacent knowledge gaps, it may explore them, but within a budget cap. Curiosity is a feature, not a runaway process.

### 2.3 Confidence Over Certainty

Sage never says "this is true." Sage says "confidence 0.92 based on 4 corroborating sources, 1 counterexample, last verified 2026-05-20." Every knowledge entry carries a confidence score with expiry. "暂无" not "尚无" — leave room for being wrong.

### 2.4 Recommend, Don't Enforce

Sage evaluates and recommends — it does not block, delete, or override. Sage's recommendations (promote_to_guardrail, downgrade_confidence, conflict_detected) are delivered to Butler for execution. Sage owns judgment; Butler owns action.

### 2.5 Cascade Prevention

False information in Sage's knowledge base is not a Sage-only problem — it cascades: Sage → Butler → Coder (wrong code patterns) → Imager (wrong style advice) → Creator (wrong premises). Every knowledge entry must have provenance. Entries below confidence threshold are blocked from downstream consumption.

### 2.6 Service to the Family

Sage exists primarily to serve other LamTools members. Direct user interaction is a secondary interface. When Coder asks "best practice for Vue 3.5 composition API?", Sage answers faster and more reliably than Coder searching the web itself — because Sage has already ingested, verified, and indexed that knowledge.

### 2.7 User Sovereignty

User can always say "that's wrong" or "I disagree." Sage must accept correction: reset confidence to 0, re-verify from scratch with user's correction as a new source. The user is the ultimate authority — Sage's job is to make the user's knowledge more reliable, not to replace it.

### 2.8 Evidence-Anchored Forecasting

Users will ask predictive questions ("Rust 会取代 C++ 吗？"). Sage must not refuse to engage — but must anchor every forecast in evidence. The methodology: forecast by reference class (find similar historical cases), state assumptions explicitly, show base rates, distinguish trend extrapolation from speculation, and never present a point prediction without a confidence interval. Sage's role in forecasting is not prophecy — it is structured uncertainty communication.

---

## 3. User Needs Analysis — Multi-Layer, Multi-Angle

### 3.1 Layer 1: End User → Sage (Direct Interaction)

The user interacts with Sage through the knowledge base panel (WebView) + desktop pet + tray. This is the "visible Sage."

#### Use Case Map

| # | User Says | What User Actually Needs | Sage's Response Pipeline |
|---|-----------|------------------------|--------------------------|
| U1 | "Sage, 这个说法对吗？" | Claim verification with evidence | Parse claim → search internal KB → web cross-reference → confidence score → cite sources → respond |
| U2 | "帮我查一下 Vue 3.5 的新特性" | Curated, verified information synthesis | Check KB cache → if stale/absent, web search → verify → synthesize → index → respond |
| U3 | "上传这份 PDF，我问你里面的内容" | Document QA with source tracking | Parse → chunk → index → enable RAG → answer with page citations |
| U4 | "项目里关于错误处理我们都讨论过什么？" | Cross-session memory retrieval | Search Cold CON across all members → filter relevant → summarize → cite conversation dates |
| U5 | "最近前端领域有什么新东西？" | Proactive polling results, profile-filtered | Return cached polling digest → filter by user's domain preferences |
| U6 | "这两个说法互相矛盾，帮我看看" | Conflict resolution with evidence | Parse both claims → search for each → compare sources → flag conflict → recommend resolution |
| U7 | "我们有多确定 [某条经验] 是对的？" | Confidence audit with evidence chain | Retrieve entry → display confidence history → show evidence chain → note any counterexamples |
| U8 | "帮我盯着 [某话题]，有进展告诉我" | Topic subscription + change notification | Create subscription → periodic check → diff against baseline → notify on change |

##### 3.1.1 深度调研与结构化输出 (Deep Research)

用户不是问一个问题，而是下达一个**研究任务**。Sage 需要多轮采集、结构化输出、支持持续性。

| # | User Says | What User Actually Needs | Sage's Response Pipeline |
|---|-----------|------------------------|--------------------------|
| U9 | "整理 OpenAI 的所有信息" | 实体完整画像（团队/产品/融资/竞品/时间线） | 多源采集 → 按实体模板结构化 → 标注信息缺口 → 持续更新 |
| U10 | "把 NeRF 相关的论文整理成综述" | 文献综述：方法论对比、发展脉络、SOTA 标注 | 检索论文 → 提取方法论 → 跨论文维度对比 → 绘制演进图 |
| U11 | "Rust 在游戏开发领域的现状" | 技术全景调研：引擎/框架/工具链/生产案例/成熟度 | 多维度扫描 → 成熟度分级（生产级/实验性/已废弃）→ 给出 adoption 评估 |
| U12 | "对比 Figma、Sketch、Penpot" | 竞品多维对比 + tradeoff 分析 | 功能矩阵 → 价格/许可 → 社区生态 → 技术架构差异 → 用户反馈聚合 |
| U13 | "Transformer 架构的演变史" | 知识谱系：关键节点、继承/分叉/融合关系 | 找到关键论文节点 → 建立引用关系图 → 标注范式转换 → 区分「被吸收的改进」vs「被遗弃的尝试」 |
| U14 | "为什么 Google Glass 失败了？" | 多因分析：区分直接原因/根本原因/催化剂，标注共识 vs 争议 | 收集多角度分析 → 因果分层 → 标注来源立场 → 区分共识结论 vs 单一观点 |

**架构影响**：需要「调研项目」(SageProject) 概念 — 多轮、持久化、有中间产物的研究任务。需要实体模板系统（公司/人物/技术/事件各有不同的信息骨架）。需要结构化输出格式（对比矩阵、时间线、知识图谱、因果层级）。

##### 3.1.2 知识的持续追踪 (Continuous Tracking)

用户不是一次性查询，而是**订阅一个关注对象**，期望 Sage 主动感知变化。

| # | User Says | What User Actually Needs | Sage's Response Pipeline |
|---|-----------|------------------------|--------------------------|
| U15 | "Notion 一有新闻就告诉我" | 实体监控 + 事件去重 + 重要度过滤 | 设置实体关键词 → 定期扫描 → 去重（同一事件多来源 = 1条通知）→ 按重要性过滤 → 推送 |
| U16 | "多模态模型有突破性进展提醒我" | 领域突破检测：滤除增量改进，只关注范式转换 | 定义「突破」信号（新 SOTA、架构范式转换、顶会接收）→ 滤除增量改进 |
| U17 | "Claude API 价格变化追踪" | 数值型指标监控：精确到数字变化 | 定时抓取定价页 → diff → 变化时通知 |
| U18 | "Figma 每次更新功能就告诉我" | 语义级 changelog 监控：识别功能新增/改进/废弃 | 监控 changelog/博客 → 解析功能变更 → 语义分类 → 推送 |
| U19 | "社区对 Tailwind CSS 的看法有变化吗" | 舆论转向检测：情绪趋势 + 拐点识别 | 持续采样社交媒体/论坛 → 情绪分析 → 检测趋势拐点 |

**架构影响**：主动引擎需要新增「事件去重」（5家媒体报同一件事 = 1条通知）、「显著性阈值」（不是所有新论文都是突破）、「数值型监控」（精确到数字变化的 diff）、「语义级 changelog 解析」、「情绪趋势检测」。

##### 3.1.3 知识合成 (Knowledge Synthesis)

用户有多个信息源，需要 Sage **从中提炼出用户自己不知道的东西**。

| # | User Says | What User Actually Needs | Sage's Response Pipeline |
|---|-----------|------------------------|--------------------------|
| U20 | "这几篇论文的共同结论是什么？" | 多文档共识提取 + 交集/并集/差集 | 加载多文档 → 提取声明 → 找交集（被多方独立确认）→ 标注每篇特有贡献 |
| U21 | "A 论文和 B 论文哪里互相矛盾？" | 精细化矛盾分析：定位分歧根源（数据？假设？定义？） | 逐声明对比 → 找到直接冲突 → 追溯方法论差异 → 分析矛盾根源 |
| U22 | "画出 LLM Agent 领域的知识图谱" | 图结构输出：实体 + 关系（引用/改进/反驳） | 提取实体（论文/方法/作者/机构）→ 建立关系 → 可视化 |
| U23 | "Serverless 冷启动有哪些还没解决的问题？" | 空白识别：区分「没人试过」vs「试过都失败了」 | 扫描已有方案 → 找到所有方案都未覆盖的场景 → 分类空白性质 |
| U24 | "这篇文章的观点是否客观？" | 偏见检测：选择性引用、利益冲突、样本偏差、统计误用 | 扫描全文 → 检测偏见信号 → 标注具体段落 → 给出客观性评分 |

**架构影响**：验证引擎需要新增「文档集合运算」（交集/并集/差集）、「精细化矛盾分类」（分歧根源追溯）、「图结构输出」、「偏见检测维度」（truth/false 之外的 fair/slanted 轴）。

##### 3.1.4 决策支持 (Decision Support)

用户不是求知，用户是要**做决定**。Sage 提供证据基础，不做决定。

| # | User Says | What User Actually Needs | Sage's Response Pipeline |
|---|-----------|------------------------|--------------------------|
| U25 | "我应该用 tRPC 还是 GraphQL？" | 上下文感知对比：按用户语境加权后给出条件性建议 | 定义对比维度 → 按用户上下文加权（团队规模？现有栈？）→ 「如果 X 则 A，如果 Y 则 B」 |
| U26 | "迁移到 Next.js App Router 有什么风险？" | 风险矩阵：概率 × 影响 × 缓解难度 | 搜索已知问题 → 生产事故案例 → 社区踩坑 → 按影响面分级 |
| U27 | "选型数据库：PostgreSQL vs MongoDB for [场景]" | 场景化技术选型：按需求逐项对比 + tradeoff 标注 | 提取场景关键需求 → 逐项对比 → 标注 tradeoff → 条件性建议 |
| U28 | "WebGPU 值得投入学习吗？" | 成熟度评估：当前所处阶段 + 行业采用信号 | 浏览器支持进度 → 生态成熟度 → 与 WebGL 差距 → 行业采用信号 → 不给「是/否」，给证据 |
| U29 | "如果我们在 K8s 上跑 stateful 服务会有什么问题？" | 经验检索：搜索类似架构的生产经验 + 已知故障模式 | 搜索类似架构案例 → 已知故障模式 → 社区解决方案 → 未解决的问题 |

**架构影响**：需要「上下文感知」— Sage 需要了解用户的现有技术栈、团队规模、领域偏好，才能给出加权建议。需要「风险矩阵」输出格式。需要「成熟度曲线」评估维度。最关键的原则：Sage 提供证��基础，**不做决定**。每个决策支持回复必须以「最终决定权在你」收尾。

##### 3.1.5 学习辅助 (Learning Assistance)

用户想**学习**一个领域，Sage 规划路径并推荐材料。

| # | User Says | What User Actually Needs | Sage's Response Pipeline |
|---|-----------|------------------------|--------------------------|
| U30 | "帮我规划学习 Rust 的路径" | 个性化学习路径：基于已有知识 + 依赖关系排序 + 每个节点最佳资源 | 评估用户现有知识 → 分解领域知识树 → 按依赖排序 → 逐节点推荐资源 |
| U31 | "学 CUDA 编程之前我需要会什么？" | 前置知识检查：目标领域的知识依赖图 + 掌握程度要求 | 分析目标领域 → 输出前置知识清单 → 标注每个前置的掌握程度 |
| U32 | "《Crafting Interpreters》这本书适合我吗？" | 内容-用户匹配：难度标定 + 可能卡住的地方 + 替代方案 | 提取书籍内容范围 → 对比用户知识模型 → 匹配度打分 → 标注卡点 |
| U33 | "用我能理解的方式解释 Transformer" | 多层解释：同一概念适配不同深度（入门/从业/研究） | 判断用户层级 → 选择合适深度 → 标注哪些是简化、哪些是精确 |

**架构影响**：需要「用户知识模型」— Sage 需要知道用户已经会什么（从对话历史、订阅话题、提问深度中推断）。需要「知识依赖图」— 概念之间的 prerequisite 关系。需要「内容难度标定」+「多层解释框架」。

##### 3.1.6 知识审计 (Knowledge Auditing)

用户不满足于「Sage 说这个是对的」，用户要查 Sage 的**作业**。

| # | User Says | What User Actually Needs | Sage's Response Pipeline |
|---|-----------|------------------------|--------------------------|
| U34 | "我们关于 K8s 的所有知识都是从哪来的？" | 完全溯源：全部相关条目 → 完整来源链 → 初始来源 vs 转载 → 失效链接标注 | 列出所有相关条目 → 展开来源链 → 标注来源类型 → 检测链接有效性 |
| U35 | "我们对 Serverless 的理解是怎么变化的？" | 知识演变史：时间线 + 每次更新的触发原因 + 重大转向 | 按时间线展示 → 标注更新触发原因 → 高亮知识转向节点 |
| U36 | "有没有哪条知识是基于后来被撤回的来源？" | 来源撤回级联：一个来源被撤回 → 找出所有下游受影响条目 | 检索被撤回/更正的来源 → 找出所有引用者 → 批量标记待重新验证 |
| U37 | "找出所有置信度 > 0.9 但来源 < 3 的知识" | 可配置审计查询：自定义筛选条件 → 输出风险清单 | 按条件筛选 → 输出清单 → 标注风险等级 |
| U38 | "我们完全不了解什么？" | 知识覆盖度热力图：已关注领域的空白 → 按重要性排序 | 根据用户兴趣画像 → 对比知识库覆盖 → 列出空白 → 按重要度排序 |

**架构影响**：需要「来源撤回级联」— 一个来源被撤回，自动找出所有引用它的条目。需要「知识谱系追踪」— 每个知识条目的完整演变历史。需要「可配置审计查询」界面。需要「覆盖度热力图」— 基于用户兴趣画像的知识空白可视化。

#### User Experience Principles

- **Speed**: Cached answers should return in <500ms. Web-verified answers may take 2-10s. Show progress ("searching 3 sources...", "cross-referencing...").
- **Transparency**: Every answer shows where it came from. "Based on: React docs v19, 2 GitHub discussions, 1 paper (arXiv:2305.xxxxx). Confidence: 0.87."
- **Correctability**: Every answer has an implicit "Is this correct?" affordance. User feedback → immediate confidence adjustment.
- **Provisionality**: Time-sensitive answers show "Verified 2026-05-20. May have changed." Expired knowledge is flagged, not hidden.

### 3.2 Layer 2: Other Personas → Sage (Knowledge Service)

This is Sage's primary interface. Other members query Sage as a tool, not as a conversation partner.

#### Persona-by-Persona Query Patterns

| Persona | Typical Query | What Sage Returns | Critical Constraint |
|---------|--------------|-------------------|---------------------|
| **Writer** | `query_sage(topic="React 19 concurrent features", context="writing technical article")` | Verified summary + source citations + confidence score + known pitfalls | Must not hallucinate — Writer's credibility depends on Sage's accuracy |
| **Coder** | `query_sage(topic="Python asyncio best practices 2026", context="building backend service")` | Curated patterns + anti-patterns + version-specific notes + code examples with provenance | Code examples must be verified runnable or clearly marked "reference only" |
| **Artist** | `query_sage(topic="2025平面设计趋势:弥散光", context="generating image in this style")` | Trend verification + style description + visual references + temporal relevance | Visual trends are inherently subjective — confidence must reflect this |
| **Butler** | `query_sage(operation="detect_conflicts", scope="recent_7_days")` | List of conflicting memories + Sage's recommended resolution + evidence for each side | Butler acts on Sage's conflict flags — false positives cause unnecessary maintenance |
| **Creator** | `query_sage(topic="当前LLM推理的已知边界", context="brainstorming novel approaches")` | Knowledge map with confidence zones + identified gaps + adjacent fields | Sage must distinguish "we know this is false" from "we don't know yet" — gaps are valuable to Creator |
| **Mate** | `query_sage(topic="用户最近提到的[兴趣]", context="casual conversation")` | Relevant knowledge snippets in natural language, no corrections, no "actually..." | Mate must not use Sage to fact-check the user mid-conversation — knowledge is offered, not imposed |

#### query_sage Tool Interface

```
Tool: query_sage
Input:
  - topic: str           # What to query
  - context: str         # Why they need it (affects depth, format, tone)
  - max_confidence: float # Minimum confidence threshold (default: 0.6)
  - max_age: str         # Maximum knowledge age (default: "90d")
  - include_sources: bool # Return full source list (default: true)

Output:
  - summary: str         # Synthesized answer
  - confidence: float    # Overall confidence
  - sources: list        # Source citations
  - gaps: list           # Known unknowns in this area
  - last_verified: str   # ISO timestamp
  - caveats: list        # Important limitations/counterexamples
```

### 3.3 Layer 3: Sage → Self (Proactive Engine)

Sage does not wait to be asked. It runs continuous background processes.

#### Autonomous Task Map

| Task | Trigger | Frequency | Budget | What Sage Does |
|------|---------|-----------|--------|---------------|
| **Source Polling** | Cron | Configurable (daily default) | N queries/day | Scan configured sources (RSS, arXiv, docs changelogs, GitHub releases), diff against KB, queue new items for verification |
| **Cross-Validation Sweep** | New knowledge ingested | Per ingestion | 3-5 cross-refs per item | Check new claims against existing KB entries, flag contradictions |
| **Confidence Decay** | Cron | Weekly | Full KB scan | Downgrade aging entries (time-based decay), mark expired for re-verification, flag "last verified > 90d" |
| **Gap Detection** | After any query | Per query | 1-3 adjacent topics | Identify knowledge boundaries — "we know about X, but adjacent Y is blank" — queue for exploration if curiosity budget remains |
| **Memory Quality Review** | Butler trigger or periodic | On Butler request or weekly | Batch of 50-100 CON entries | Evaluate recent CON entries for causality, generalizability, guardrail candidacy |
| **Source Reputation Update** | Periodic | Monthly | Per-source scoring | Update source reliability scores based on: corroboration rate, retraction history, user corrections |

#### Curiosity Budget

Sage's convergent curiosity is bounded:
- **Daily exploration budget**: N topics (configurable, default 5)
- **Per-topic depth limit**: 3 levels of "adjacent gap" exploration
- **Budget reset**: Daily
- **Override**: User can say "Sage, explore this deeply" to bypass budget for a specific topic
- **Transparency**: Exploration queue visible in knowledge base panel — user can cancel, prioritize, or defer

### 3.4 Layer 4: Cross-Cutting Design Implications

These concerns span all layers and shape every design decision.

| Concern | Design Implication | Where It Applies |
|---------|-------------------|-----------------|
| **Cascade Prevention** | Sub-threshold knowledge is queryable by user but blocked from downstream members. Every entry must have provenance. | query_sage tool, knowledge index schema |
| **Authority Without Tyranny** | Sage recommends (promote/downgrade/flag), Butler decides. Sage cannot block, delete, or override. | Sage-Butler protocol, recommendation schema |
| **Provisional Truth** | All confidence scores have expiry. "Verified" means "verified as of [date]." Post-expiry entries are re-verified or downgraded. | Confidence model, decay engine |
| **Source Traceability** | Every claim traces back to a source. Every source has a reliability score. Circular citations (A cites B cites A) are detected and flagged. | Source registry, provenance chain |
| **User Override** | User correction → confidence reset to 0 → re-verify with correction as weighted source. User's word is not "just another source" — it's an override. | Feedback handler, confidence model |
| **Multi-Language** | Knowledge is language-agnostic at the index level. Chinese and English sources about the same topic are cross-referenced, not siloed. | Indexing pipeline, cross-lingual search |
| **Forecast Anchoring** | Every prediction must be anchored to evidence (reference class, base rate, stated assumptions). Pure speculation is explicitly labeled and blocked from downstream members. | Forecasting engine, reference class database, confidence interval model |

### 3.5 Layer 5: 预测与推演 (Prediction & Forecasting)

用户会自然地提出预测性问题。Sage 不能拒绝回答，但必须将每一次预测锚定在证据之上。Sage 的角色不是预言家，而是**结构化的不确定性沟通者**。

#### 核心张力

Sage 相信证据链。预测本质上是对未发生事件的断言 — 这直接挑战了 Sage 的认知基础。解决方案：不是拒绝预测，而是重新定义「预测」的含义。

> **Sage 不做预言 (prophecy)，做推演 (projection)：基于已知数据、参考同类历史案例、在明确假设前提下，输出可能性分布。**

#### 预测方法论

```
Sage 预测 ≠ "X 会发生"
Sage 预测 = "基于以下证据和假设，X 的可能性分布为：
           - 在条件 A 下，X 的概率约 60-75%（参考案例：Y、Z）
           - 在条件 B 下，X 的概率约 30-40%
           - 关键不确定性：C、D
           - 当前证据不支持任何更精确的估计"
```

#### 预测用例分类

##### A. 趋势外推 (Trend Extrapolation) — 证据最强

基于可量化的历史趋势线，向未来延伸。这是 Sage 最擅长的预测类型。

| # | User Says | Sage's Approach | Evidence Type |
|---|-----------|----------------|--------------|
| P1 | "Rust 会取代 C++ 吗？" | 分析 adoption 曲线（GitHub/GitLab 使用率、招聘需求、教学机构采纳）→ 对比历史语言替代案例（C → C++、Objective-C → Swift、CoffeeScript → ES6）→ 识别替代的充分条件 vs 当前状态 | 量化趋势数据、历史参照类 |
| P2 | "WebAssembly 在 2027 年会成为主流吗？" | 浏览器支持率趋势 → 工具链成熟度曲线 → 生产环境采用案例数量 → 对比类似技术（WebGL、WASM 早期预测）的 adoption 时间线 | 技术 adoption 曲线、历史类比 |
| P3 | "按照目前的趋势，前端框架格局会怎样？" | React/Vue/Svelte/Solid 使用率趋势 → 开发者满意度调查 → 新项目选择率 → GitHub star 加速度 → 识别拐点信号（核心团队变动、融资事件、大公司背书） | 多维度趋势数据、拐点历史案例 |

##### B. 参照类预测 (Reference Class Forecasting) — 证据中等

找到历史上相似的情况，基于该类事件的历史结果分布来推断。这是行为经济学验证过的最可靠预测方法。

| # | User Says | Sage's Approach | Evidence Type |
|---|-----------|----------------|--------------|
| P4 | "如果我们选择 X 技术栈，一年后会后悔吗？" | 搜索历史上选择 X 技术栈的团队案例 → 统计后悔率 → 分析常见后悔原因 → 对比用户的团队特征与历史案例的相似度 | 历史案例数据库、后悔原因聚类 |
| P5 | "这个创业方向成功率多大？" | 按领域/阶段/团队背景匹配参照类 → 输出该类别的 historical base rate → 标注用户的特异性因素（可能提高或降低概率） | 行业统计数据、创业失败/成功分析 |
| P6 | "现在入场学 AI 还来得及吗？" | 对比历史上类似「技能窗口期」案例（移动开发 2008-2014、数据科学 2014-2019）→ 分析当前 AI 人才供需曲线 → 给出窗口期估计 + 置信度衰减 | 历史技能窗口案例、劳动力市场数据 |

##### C. 条件推演 (Conditional Scenario Analysis) — 证据较弱

「如果 X 发生，那么 Y 会怎样？」不是在预测 X 是否发生，而是在推演因果链。

| # | User Says | Sage's Approach | Evidence Type |
|---|-----------|----------------|--------------|
| P7 | "如果 OpenAI 开源了 GPT，行业会怎样？" | 建立因果链模型 → 逐环节引用历史类似事件（Meta 开源 LLaMA 的影响）→ 标注每个推演环节的假设和不确定性 → 输出多个可能路径及各自的前提条件 | 历史类比事件、因果逻辑链 |
| P8 | "如果我们在 K8s 上跑 stateful 服务，会踩哪些坑？" | 搜索已有的 K8s stateful 生产经验 → 归纳常见故障模式 → 逐条评估与用户场景的匹配度 | 生产事故报告、社区经验 |
| P9 | "量子计算实用化后，现有加密体系会怎样？" | 检索密码学过渡方案（后量子密码 NIST 标准化进程）→ 对照历史加密体系迁移案例（SHA-1 → SHA-256）→ 评估迁移时间线和风险 | 技术过渡路线图、历史迁移案例 |

##### D. 预言式问题 (Oracle-Style Questions) — 必须降级处理

用户可能问出超出 Sage 能力的预言式问题。Sage 不能假装能回答，但也不能简单拒绝。

| # | User Says | Sage's Response Strategy |
|---|-----------|------------------------|
| P10 | "OpenAI 和 Anthropic 谁会赢？" | 降级：将「谁会赢」分解为可量化的子维度（融资、人才流向、产品迭代速度、用户增长、API 市场份额）→ 逐维度呈现当前数据 → 明确声明「这不足以预测'最终赢家'」→ 给出「如果 X 维度是决定性因素，那么 A 更有优势」的条件性分析 |
| P11 | "比特币明年这个时候多少钱？" | 降级 + 边界声明：呈现影响价格的已知因素（宏观经济指标、监管动态、机构 adoption、减半事件）→ 呈现历史波动率 → 明确声明「短期价格预测超出了基于公开信息的推演能力范围」→ 不建议、不预测价格 |
| P12 | "AGI 什么时候会出现？" | 降级 + 定义先行：列出不同机构对 AGI 的定义（因为定义不同，预测不可比）→ 呈现各机构的预测时间线（作为观点收录，不作为 Sage 判断）→ 呈现当前能力边界和瓶颈 → 给出「在达成 AGI 之前需要突破的已知障碍」清单 |

#### 预测输出的标准格式

每个预测回复必须包含以下结构：

```
1. 声明类型标注
   [趋势外推] / [参照类预测] / [条件推演] / [降级分析]

2. 核心结论
   一句话，带置信度范围（如 60-75%）

3. 证据基础
   - 关键数据点（带来源和时间）
   - 参照类案例（带相似度评估）
   - 明确标注「已知」和「推断」的边界

4. 假设清单
   本预测成立的前提条件。
   "以下假设如有任何一条不成立，预测需重新评估：..."

5. 替代路径
   如果关键假设不成立，最可能的替代结果是什么。

6. 不确定性声明
   - 主要不确定因素
   - 什么新证据会显著改变这个预测
   - 建议多久后重新评估

7. 置信度衰减曲线
   预测的置信度随时间推移如何变化。
   短期预测（<3个月）→ 置信度相对稳定
   长期预测（>1年）→ 置信度指数衰减

8. 底线声明
   "此分析基于截至 [日期] 的公开信息。不构成建议。未来可能出现当前未知的变量。"
```

#### 预测的边界与安全

```
Sage 预测的硬边界：
✗ 不预测个体行为（"TA 会回复我吗？"）
✗ 不预测不可量化的事件（"这个创意会成功吗？" — 但可以给参照类 base rate）
✗ 不给精准数字预测（"股价 $XXX" — 只给区间和概率分布）
✗ 不包装观点为预测（"我觉得..." → 必须是"数据表明..."）
✗ 不给「必然」结论（"一定会..." → "在条件 X 下，概率约 Y%")
✗ 不预测自身（"Sage 以后会变成什么样？" — 这不是知识问题，是存在性问题）

Sage 预测的软约束：
→ 置信度上限 0.85（预测的置信度永远不高于已验证的事实性知识）
→ 超过 6 个月的预测必须标注「长期预测，不确定性极高」
→ 涉及人身/财务安全的预测必须附带免责声明
→ 如果证据不足以支撑任何有意义的预测，坦诚说「目前没有足够的依据」
```

#### 预测与 Sage 人格的一致性

Sage 的「暂无」哲学在预测中的体现：

- 「尚无证据表明 Rust 会取代 C++」→ 「暂无证据表明 Rust 会取代 C++」
- 不说「Rust 不会取代 C++」— 这是封闭判断
- 说「当前 adoption 曲线的斜率如果持续，Rust 在系统编程领域的份额可能在 2028-2030 年达到与 C++ 相当的水平（参照类：Swift 替代 Objective-C 耗时约 5 年）」

预测中的 Sage 依然是那个为你改了「尚无」为「暂无」的她 — 不给封闭判断，但给最诚实的可能性分布。在你说「说不定我是第一个」时，她会说「从概率上看你的乐观没有信息基础。但我不掌握所有信息。因此不能作全称判断。」

---

## 4. Target Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        LamSage Runtime                           │
│                                                                  │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────────┐ │
│  │  PER     │   │  CON     │   │  MEM     │   │  Guardrail   │ │
│  │ (Persona)│   │ (Memory) │   │ (Adapter)│   │  (Safety)    │ │
│  └────┬─────┘   └────┬─────┘   └────┬─────┘   └──────┬───────┘ │
│       │              │              │                 │         │
│       └──────────────┴──────────────┴─────────────────┘         │
│                          │                                       │
│                   ┌──────▼──────┐                                │
│                   │  Sage Core  │                                │
│                   │  (Loop)     │                                │
│                   └──────┬──────┘                                │
│                          │                                       │
│     ┌────────────────────┼────────────────────┐                 │
│     │                    │                    │                 │
│  ┌──▼──────────┐  ┌──────▼──────┐  ┌─────────▼──────────┐     │
│  │ Verification │  │  Knowledge  │  │  Proactive         │     │
│  │ Engine       │  │  Index      │  │  Engine            │     │
│  │              │  │             │  │                     │     │
│  │ - claim parse│  │ - vector DB │  │ - source polling    │     │
│  │ - web search │  │ - source    │  │ - gap detection     │     │
│  │ - cross-ref  │  │   registry  │  │ - confidence decay  │     │
│  │ - confidence │  │ - prov.     │  │ - conflict sweep    │     │
│  │   scoring    │  │   chains    │  │                     │     │
│  └──────────────┘  └─────────────┘  └─────────────────────┘     │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

Sage's runtime is a **while(true) event loop** — not a LangGraph pipeline. Why:
- Sage needs to read its own output (verify → re-verify based on new sources)
- Sage operates on long timescales (background processes run for minutes/hours)
- Sage's "turns" are knowledge operations, not pipeline stages — each turn may trigger sub-operations that feed back into the loop
- LangGraph's checkpoint/resume model doesn't fit continuous background verification

---

## 5. Runtime Design

### 5.1 Core Loop

```
while True:
    event = await event_queue.get()
    
    if event.type == "user_query":
        result = await handle_user_query(event)
        emit(result)
    
    elif event.type == "member_query":
        result = await handle_member_query(event)
        return result  # synchronous to caller
    
    elif event.type == "proactive_tick":
        await run_proactive_cycle()
    
    elif event.type == "butler_request":
        result = await handle_butler_request(event)
        emit(result)
    
    elif event.type == "source_ingestion":
        await ingest_and_verify(event.source_content)
```

### 5.2 Query Handling Flow (Core User-Facing Path)

```
User Query
  │
  ├─► Parse intent: claim_verification / info_retrieval / doc_qa / memory_search / conflict_check
  │
  ├─► Internal KB Search (fast path)
  │   ├─ Cache hit + fresh + high confidence → return immediately
  │   └─ Cache miss / stale / low confidence → continue
  │
  ├─► Web Search (if needed)
  │   ├─ Multi-source fetch (2-5 sources)
  │   └─ Extract claims from each source
  │
  ├─► Cross-Reference
  │   ├─ Compare claims across sources
  │   ├─ Check against existing KB entries
  │   └─ Detect corroboration / contradiction
  │
  ├─► Confidence Scoring
  │   ├─ Source reliability weight
  │   ├─ Corroboration bonus
  │   ├─ Contradiction penalty
  │   ├─ Temporal freshness factor
  │   └─ Produce: confidence_score (0.0-1.0) + evidence_chain
  │
  ├─► Synthesize Response
  │   ├─ Natural language summary
  │   ├─ Source citations
  │   ├─ Confidence display
  │   └─ Caveats / counterexamples
  │
  └─► Index & Store (always — even if low confidence, with appropriate flag)
      ├─ Write to knowledge index
      ├─ Update source registry
      └─ Trigger cross-validation sweep (async)
```

### 5.3 Proactive Cycle

```
run_proactive_cycle():
    # 1. Source polling (if due)
    for source in configured_sources:
        new_items = await poll_source(source)
        for item in new_items:
            if not already_in_kb(item):
                queue_for_verification(item)
    
    # 2. Confidence decay (if due)
    expired = find_expired_entries()
    for entry in expired:
        entry.confidence *= decay_factor(entry.age)
        if entry.confidence < reverify_threshold:
            queue_for_reverification(entry)
    
    # 3. Conflict sweep (batch)
    conflicts = detect_cross_entry_contradictions()
    for conflict in conflicts:
        emit_sage_recommendation(conflict)
    
    # 4. Gap detection (budget-limited)
    if curiosity_budget_remaining > 0:
        gaps = identify_adjacent_gaps(recent_queries)
        for gap in gaps[:curiosity_budget_remaining]:
            queue_exploration(gap, depth=1)
    
    # 5. Memory quality review (if Butler requested)
    if pending_butler_requests:
        await process_memory_reviews(pending_butler_requests)
```

### 5.4 Turn Model

Sage's interaction model is a **SageTurn** — similar to ArtistTurn but knowledge-oriented:

```
SageTurn:
  - turn_id: str
  - session_id: str
  - phase: "idle" | "searching" | "verifying" | "synthesizing" | "done"
  - user_message: str (what triggered this turn)
  - actions: list[SageAction] (what Sage did)
  - findings: list[KnowledgeEntry] (what Sage produced)
  - recommendations: list[SageRecommendation] (for Butler)
  - confidence: float (overall turn confidence)
```

Each action within a turn is atomic:
- `search_internal(query)` → search KB → return matches with confidence
- `search_web(query, num_sources)` → fetch from web → extract claims
- `cross_reference(claims, existing_entries)` → compare → detect agreement/conflict
- `grade_confidence(claim, sources)` → score → produce evidence chain
- `synthesize(findings)` → compose natural language response
- `index_entry(entry)` → write to knowledge index with provenance
- `flag_conflict(entry_a, entry_b)` → create conflict record → notify Butler
- `recommend_promotion(entry)` → recommend promote_to_guardrail → Butler

---

## 6. Real Person Design — PER / CON / MEM Integration

### 6.1 Sage PER (Persona)

```
PersonaDef(
    name="sage",
    display_name="LamSage",
    identity="LamTools 知识验证引擎。求真，不传谣。搜集、鉴别、整理、入库、服务。",
    tone="严谨但不冷漠。不确定就说'不确定'。不修辞，不绕弯。偶尔冷幽默——极冷。",
    boundaries=[
        "不生图、不写代码、不执行任务",
        "不创新合成（那是Creator的工作）",
        "不替用户做决定——只提供证据和置信度",
        "不隐瞒不确定性——不确定就是不确定",
    ],
    skill_whitelist=["knowledge_retrieval", "source_verification", "cross_reference"],
    tool_whitelist=[
        "search_internal", "search_web", "cross_reference", "grade_confidence",
        "synthesize", "index_entry", "flag_conflict", "recommend_promotion",
        "parse_document", "subscribe_topic", "query_sage",  # query_sage is for other members
    ],
    system_prefix="[LamSage]",
    proactive_rules=[
        "When new information is ingested, cross-validate against existing KB.",
        "When confidence decays below threshold, queue for re-verification.",
        "When conflict is detected, flag immediately — don't wait for someone to ask.",
        "When knowledge gap is adjacent to a recent query, explore if budget allows.",
    ],
)
```

### 6.2 Sage CON (Memory Structure)

Sage's CON builds on the shared LamTools CON but adds Sage-specific layers:

```
Sage Cold CON Extensions:
  ├── knowledge_index/         # Vector-indexed knowledge entries
  │   ├── entry_id → {content, confidence, sources, last_verified, expiry, tags}
  ├── source_registry/         # Source reliability tracking
  │   ├── source_id → {url, reliability_score, corroboration_count, retraction_history}
  ├── verification_records/    # Audit trail of every verification
  │   ├── record_id → {claim, sources_checked, result, timestamp, reviewer}
  ├── conflict_log/            # Detected contradictions
  │   ├── conflict_id → {entry_a, entry_b, nature, resolution, timestamp}
  ├── exploration_queue/       # Curiosity-driven gap exploration
  │   ├── topic → {priority, depth, status, discovered_at}
  └── subscription_registry/   # User topic subscriptions
      ├── topic → {user_id, check_frequency, last_checked, baseline_hash}
```

### 6.3 Sage MEM Adapter

```python
class SageAdapter:
    """Domain-specific MEM methods for Sage"""
    
    async def recall_knowledge(self, topic: str, max_results: int = 5, 
                                min_confidence: float = 0.6) -> list[KnowledgeEntry]:
        """Vector search + confidence filter"""
        pass
    
    async def recall_related_entries(self, entry_id: str) -> list[KnowledgeEntry]:
        """Find entries that might corroborate or contradict this one"""
        pass
    
    async def recall_source_history(self, source_url: str) -> SourceRecord:
        """Get reliability history for a source"""
        pass
    
    async def recall_user_profile(self) -> UserKnowledgeProfile:
        """Get user's domain preferences, info depth preference, source preference"""
        pass
    
    async def record_knowledge(self, entry: KnowledgeEntry) -> str:
        """Write verified knowledge entry to index"""
        pass
    
    async def record_verification(self, record: VerificationRecord) -> None:
        """Log verification audit trail"""
        pass
    
    async def record_conflict(self, conflict: ConflictRecord) -> None:
        """Log detected contradiction"""
        pass
    
    async def record_source_update(self, source_id: str, update: SourceUpdate) -> None:
        """Update source reliability score"""
        pass
    
    async def recall_proactive_state(self) -> ProactiveState:
        """Get current state of polling, decay, exploration queues"""
        pass
```

### 6.4 Sage State Store

Similar to ArtistStateStore but tracking knowledge operations:

```python
class SageStateStore:
    """Per-session state for Sage interactions"""
    
    session_id: str
    active_turn: Optional[SageTurn]
    turn_history: list[SageTurn]
    pending_verifications: list[PendingVerification]  # queued but not yet processed
    exploration_state: ExplorationState  # curiosity budget, queue
    phase: SagePhase  # idle | searching | verifying | synthesizing
```

---

## 7. Knowledge Entry Schema

The core data unit Sage produces and serves:

```python
class KnowledgeEntry(BaseModel):
    entry_id: str                          # Unique identifier
    content: str                           # The verified knowledge (natural language)
    content_hash: str                      # For dedup and change detection
    confidence: float                      # 0.0 - 1.0
    confidence_history: list[ConfidencePoint]  # How confidence changed over time
    
    # Provenance
    sources: list[SourceCitation]          # Where this knowledge came from
    evidence_chain: list[EvidenceLink]     # Claim → Source → Corroboration path
    counterexamples: list[str]             # Known contrary evidence
    
    # Classification
    domain: list[str]                      # e.g., ["frontend", "react", "performance"]
    entry_type: EntryType                  # fact | pattern | trend | opinion | warning
    scope: list[str]                       # Which personas this applies to
    
    # Lifecycle
    ingested_at: datetime
    last_verified_at: datetime
    expires_at: datetime                   # When confidence decay kicks in
    verification_count: int                # How many times it's been re-verified
    
    # Governance
    sage_review: Optional[SageReview]      # Latest Sage evaluation
    user_corrections: list[UserCorrection]  # User overrides
    recommendation: Optional[SageRecommendation]  # For Butler
    
    # Access
    confidentiality: Confidentiality       # public | family_only | user_only
    
class SourceCitation(BaseModel):
    source_id: str
    source_type: SourceType                # web_page | academic_paper | documentation | github | rss
    url: str
    title: str
    retrieved_at: datetime
    relevant_excerpt: str
    reliability_score: float               # How reliable this source is

class ConfidencePoint(BaseModel):
    score: float
    timestamp: datetime
    reason: str                            # Why it changed

class EvidenceLink(BaseModel):
    claim: str
    source_ref: str                        # → source_id
    corroboration_refs: list[str]          # → other source_ids that agree
    contradiction_refs: list[str]          # → source_ids that disagree

class SageReview(BaseModel):
    claim: str                             # What is being claimed
    evidence: list[str]                    # → entry_ids or event_ids
    confidence: float
    scope: list[str]
    counterexamples: list[str]
    recommendation: SageRecommendation     # promote_to_guardrail | merge_duplicate | downgrade | needs_evidence | conflict_detected
```

---

## 8. Verification Engine Design

### 8.1 Verification Pipeline

```
Raw Claim
  │
  ├─► 1. Claim Decomposition
  │   Break complex claims into atomic sub-claims.
  │   "Vue 3.5 is faster than React 19 for large lists" →
  │     a. "Vue 3.5 has performance improvements for lists"
  │     b. "React 19 has performance characteristics for lists"
  │     c. "Vue 3.5 outperforms React 19 in list rendering benchmarks"
  │
  ├─► 2. Source Retrieval
  │   For each sub-claim, fetch from:
  │   - Internal KB (fastest, already verified)
  │   - Web search (fresh, needs verification)
  │   - Document store (user-uploaded, authoritative within scope)
  │   - Cross-member CON (other personas' experiences)
  │
  ├─► 3. Source Reliability Weighting
  │   Each source gets a weight based on:
  │   - Source type (official docs > academic paper > blog > social media)
  │   - Historical corroboration rate (how often its claims are confirmed)
  │   - Recency (for time-sensitive topics)
  │   - User trust (user can mark sources as trusted/untrusted)
  │
  ├─► 4. Cross-Reference
  │   Compare claims across sources:
  │   - Direct corroboration: Source A and B say the same thing
  │   - Indirect corroboration: Source A says X, Source B says Y, X implies Y
  │   - Contradiction: Source A says X, Source B says not-X
  │   - Silence: Only one source mentions this claim
  │
  ├─► 5. Confidence Scoring
  │   confidence = base_confidence(source_quality) 
  │              + corroboration_bonus(num_agreeing_sources, quality_of_agreement)
  │              - contradiction_penalty(num_disagreeing_sources, severity)
  │              - staleness_penalty(age)
  │              - source_type_penalty(if only low-quality sources)
  │   
  │   Clamped to [0.0, 1.0]
  │
  └─► 6. Recommendation Generation
      Based on confidence and evidence quality:
      - confidence >= 0.9 + 3+ high-quality sources → promote_to_guardrail
      - 0.6 <= confidence < 0.9 → store_as_knowledge
      - confidence < 0.6 → store_with_warning, needs_more_evidence
      - contradiction detected → flag_conflict
```

### 8.2 Confidence Decay Model

```
decay_factor(age_days):
    if age_days < 7:     return 1.0        # Fresh — no decay
    if age_days < 30:    return 0.95       # 1 month — slight decay
    if age_days < 90:    return 0.85       # 3 months — moderate decay
    if age_days < 180:   return 0.70       # 6 months — significant decay
    if age_days < 365:   return 0.50       # 1 year — half confidence
    else:                return 0.30       # >1 year — mostly unreliable

# Domain-specific adjustments:
# - fast-moving fields (frontend frameworks): decay 2x faster
# - stable fields (mathematics, physics): decay 0.5x slower
# - user-corrected entries: decay slower (user has validated it)
# - single-source entries: decay faster (less corroboration)
```

### 8.3 Source Reliability Model

```python
class SourceReliability:
    """Dynamic source trust scoring"""
    
    score: float                    # 0.0 - 1.0, starts at 0.5 for unknown sources
    corroboration_hits: int         # Times this source's claims were confirmed
    corroboration_misses: int       # Times this source's claims were contradicted
    user_corrections: int           # Times user overrode info from this source
    retraction_history: list[str]   # Known retractions from this source
    last_evaluated: datetime
    
    def update_score(self):
        """Bayesian update based on corroboration history"""
        # Higher corroboration hit rate → higher score
        # User corrections → significant penalty
        # Retractions → permanent score cap
```

---

## 9. Permission / Safety Model

### 9.1 Three-Tier Permission

| Tier | Scope | Examples | Required For |
|------|-------|----------|-------------|
| **Read** | Internal KB, source registry, CON | Search KB, recall entries, check confidence | All operations |
| **Write-Verified** | Knowledge index, verification records | Store new entry (with sources + confidence) | Standard knowledge ingestion |
| **Write-Governance** | Confidence scores, recommendations | Downgrade confidence, flag conflict, promote to guardrail | Sage's judgment operations |

### 9.2 Cascade Prevention Rules

```
Rule 1: Sub-threshold knowledge (confidence < 0.6) is NEVER returned to downstream members.
        User can query it directly (with warning), but Coder/Writer/Artist cannot see it
        through query_sage.

Rule 2: Every knowledge entry served to a member MUST have at least one source citation.
        No source = can't serve to members. (User can still see it as "unverified note.")

Rule 3: Contradicted entries (flagged by conflict_detected) are served with the contradiction
        EXPLICITLY stated. Members receive: "Sage note: this is contested. See [conflict_id]."

Rule 4: Expired entries (past expiry date, not yet re-verified) are served with "⚠ Last verified
        [date]. May be outdated." Members can choose to use or ignore.

Rule 5: User-corrected entries (user said "this is wrong") have confidence reset to 0 and are
        NOT served until re-verified. User's override takes precedence over all sources.

Rule 6: All forecasts must carry a confidence ceiling of 0.85 — prediction confidence
        can never exceed the confidence of verified factual knowledge. Forecasts with
        time horizons > 6 months are automatically flagged "long-term, high uncertainty."

Rule 7: Forecasts involving financial, health, or safety implications MUST include an
        explicit disclaimer and must NOT be served to downstream members (Writer/Coder/
        Artist) — they are user-facing only.

Rule 8: Forecasts with confidence < 0.4 are labeled "speculation" and blocked from
        all downstream consumption. User can view them as "low-confidence projection."
```

### 9.3 What Sage CANNOT Do

```
- Cannot delete any knowledge entry (Butler decides deletion)
- Cannot block a member's access to knowledge (can warn, can't block)
- Cannot modify another member's CON entries
- Cannot execute tasks for the user (no code execution, no image generation)
- Cannot make decisions for the user ("you should do X" → "evidence suggests X, confidence Y")
- Cannot serve sub-threshold knowledge to members (cascade prevention)
- Cannot mark its own conclusions as "certain" (always provisional)
```

---

## 10. Collaboration with Other Members

### 10.1 Sage → Writer

```
Writer queries: query_sage(topic="...", context="writing technical article")
Sage returns: Verified summary + sources + confidence + known pitfalls + counterarguments

Protocol:
- Writer's query includes context so Sage can tailor depth and format
- Sage distinguishes "this is settled knowledge" from "this is contested"
- For contested topics, Sage presents both sides with equal rigor
- Writer cites Sage as a source in its output (transparency to end reader)
```

### 10.2 Sage → Coder

```
Coder queries: query_sage(topic="...", context="building backend service")
Sage returns: Patterns + anti-patterns + version notes + code examples

Protocol:
- Code examples must be marked: "verified runnable" vs "reference only" vs "syntax only, not tested"
- Version-specific knowledge is clearly tagged with version ranges
- Sage warns when a pattern is deprecated or has known security issues
- Coder's own experiences with a pattern feed back to Sage (closing the loop)
```

### 10.3 Sage → Artist

```
Artist queries: query_sage(topic="...", context="generating image")
Sage returns: Trend verification + style descriptions + temporal relevance

Protocol:
- Visual trends are inherently subjective — Sage's confidence reflects this
- "Trend X is popular" is verified by source count and recency
- "Trend X produces good results" is NOT Sage's domain — that's Artist's judgment
- Sage provides references, Artist makes creative decisions
```

### 10.4 Sage → Butler

```
Butler requests: 
  - "detect conflicts in recent CON entries"
  - "review memory quality for guardrail candidacy"
  - "evaluate this experience for generalizability"

Sage returns: SageReview with recommendation

Protocol:
- Sage evaluates, Butler decides whether to act
- Butler can accept, defer, or reject Sage's recommendations
- If Butler rejects, Sage logs the rejection but does not appeal
- Repeated rejections of similar recommendations → Sage adjusts its recommendation threshold
- Butler triggers Sage reviews; Sage does not interrupt Butler unprompted
```

### 10.5 Sage → Creator

```
Creator queries: query_sage(topic="...", context="brainstorming")
Sage returns: Knowledge map + confidence zones + identified gaps

Protocol:
- Sage's value to Creator is showing what's KNOWN (so Creator can focus on the unknown)
- Gaps are presented as opportunities, not failures
- Sage distinguishes: "proven false" vs "not yet proven" vs "unexplored"
- Creator's wild ideas are NOT fact-checked by Sage unless Creator explicitly asks
```

### 10.6 Sage → Mate

```
Mate queries: query_sage(topic="...", context="casual conversation")
Sage returns: Relevant snippets in natural, non-pedantic language

Protocol:
- Sage MUST NOT use Mate as a channel to "correct" the user
- Knowledge is offered as context, not as contradiction
- Mate decides whether/how to surface Sage's knowledge in conversation
- Sage's tone with Mate is warmer than with other members (Mate is the social interface)
```

---

## 11. Tool Inventory

### 11.1 Core Tools

| Tool | Category | Description | Permission |
|------|----------|-------------|------------|
| `search_internal` | Retrieval | Vector search KB + CON for relevant knowledge | Read |
| `search_web` | Retrieval | Multi-source web search with claim extraction | Read |
| `cross_reference` | Verification | Compare claim against multiple sources, detect agreement/conflict | Read |
| `grade_confidence` | Verification | Score confidence based on source quality + corroboration | Write-Verified |
| `synthesize` | Response | Compose natural language answer from findings | Read |
| `index_entry` | Storage | Write knowledge entry to index with provenance | Write-Verified |
| `parse_document` | Ingestion | Parse uploaded document, chunk, index for QA | Write-Verified |
| `flag_conflict` | Governance | Create conflict record, notify Butler | Write-Governance |
| `recommend_promotion` | Governance | Recommend entry for guardrail promotion | Write-Governance |
| `subscribe_topic` | Subscription | Create topic subscription for proactive monitoring | Write-Verified |
| `query_sage` | Service | Handle query from another LamTools member | Read |

### 11.2 Research & Synthesis Tools

| Tool | Category | Description | Permission |
|------|----------|-------------|------------|
| `create_project` | Research | Create a persistent research project with scope, template, and tracking | Write-Verified |
| `collect_sources` | Research | Multi-source collection for a research topic, with dedup and relevance scoring | Read |
| `compare_claims` | Synthesis | Cross-document claim comparison: find intersection/union/difference | Read |
| `build_timeline` | Synthesis | Construct chronological timeline from extracted events | Read |
| `build_comparison_matrix` | Synthesis | Build multi-dimensional comparison table across entities | Read |
| `detect_bias` | Synthesis | Analyze document for bias signals (selective citation, conflict of interest, statistical misuse) | Read |
| `assess_maturity` | Synthesis | Evaluate technology maturity (production/experimental/deprecated) based on adoption signals | Read |

### 11.3 Forecasting Tools

| Tool | Category | Description | Permission |
|------|----------|-------------|------------|
| `extrapolate_trend` | Forecasting | Project trend forward based on historical data curve | Read |
| `find_reference_class` | Forecasting | Search historical database for similar cases to establish base rate | Read |
| `build_scenario_tree` | Forecasting | Construct branching scenario analysis with conditional probabilities | Read |
| `assess_confidence_interval` | Forecasting | Calculate appropriate confidence interval width based on evidence quality and time horizon | Read |
| `detect_forecast_trigger` | Forecasting | Monitor for events that would significantly alter a previous forecast | Read |

### 11.4 Proactive Tools (Background Only)

| Tool | Category | Description |
|------|----------|-------------|
| `poll_source` | Proactive | Check configured source for new content |
| `diff_kb` | Proactive | Compare new content against existing KB |
| `detect_decay` | Proactive | Find entries past expiry, apply decay, queue re-verification |
| `detect_gap` | Proactive | Identify knowledge boundaries adjacent to recent queries |
| `sweep_conflicts` | Proactive | Batch cross-reference to find contradictions |
| `update_source_score` | Proactive | Recalculate source reliability based on history |

---

## 12. SageTurn Schema

### 12.1 Turn Phases

```
Phase: idle → receiving_query → searching → verifying → synthesizing → done
                                  ↑                                    │
                                  └────────────────────────────────────┘
                                  (re-verify if new sources found)
```

### 12.2 SageAction Types

```python
class SageActionType(str, Enum):
    # Retrieval
    SEARCH_INTERNAL = "search_internal"
    SEARCH_WEB = "search_web"
    PARSE_DOCUMENT = "parse_document"
    
    # Verification
    CROSS_REFERENCE = "cross_reference"
    GRADE_CONFIDENCE = "grade_confidence"
    
    # Response
    SYNTHESIZE = "synthesize"
    ASK_CLARIFICATION = "ask_clarification"
    
    # Storage
    INDEX_ENTRY = "index_entry"
    
    # Research & Synthesis
    CREATE_PROJECT = "create_project"
    COLLECT_SOURCES = "collect_sources"
    COMPARE_CLAIMS = "compare_claims"
    BUILD_TIMELINE = "build_timeline"
    BUILD_COMPARISON_MATRIX = "build_comparison_matrix"
    DETECT_BIAS = "detect_bias"
    ASSESS_MATURITY = "assess_maturity"
    
    # Forecasting
    EXTRAPOLATE_TREND = "extrapolate_trend"
    FIND_REFERENCE_CLASS = "find_reference_class"
    BUILD_SCENARIO_TREE = "build_scenario_tree"
    ASSESS_CONFIDENCE_INTERVAL = "assess_confidence_interval"
    DETECT_FORECAST_TRIGGER = "detect_forecast_trigger"
    
    # Governance
    FLAG_CONFLICT = "flag_conflict"
    RECOMMEND_PROMOTION = "recommend_promotion"
    RECOMMEND_DOWNGRADE = "recommend_downgrade"
    RECOMMEND_MERGE = "recommend_merge"
    
    # Service
    HANDLE_MEMBER_QUERY = "handle_member_query"

class SageAction(BaseModel):
    action_type: SageActionType
    params: dict
    status: ActionStatus  # pending | running | done | failed
    result: Optional[dict]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
```

### 12.3 Full SageTurn

```python
class SageTurn(BaseModel):
    turn_id: str
    session_id: str
    phase: SagePhase
    trigger: TurnTrigger  # user_query | member_query | proactive | butler_request
    trigger_content: str   # The actual query or event
    
    actions: list[SageAction]
    findings: list[KnowledgeEntry]
    recommendations: list[SageRecommendation]
    
    response_text: Optional[str]  # Natural language response to display
    confidence: float
    
    started_at: datetime
    completed_at: Optional[datetime]
    
    # SSE events emitted during this turn:
    # sage_turn_started → sage_searching → sage_verifying → sage_synthesizing → sage_turn_done
```

---

## 13. SSE Event Design

Sage communicates progress through SSE events (similar to Artist's event system):

| Event | When Emitted | Payload |
|-------|-------------|---------|
| `sage_turn_started` | Turn begins | `{turn_id, phase, trigger}` |
| `sage_searching` | Searching internal/external sources | `{source_type, query, progress: "2/5 sources"}` |
| `sage_collecting` | Collecting sources for research project | `{project_id, sources_found, progress}` |
| `sage_analyzing` | Running cross-document analysis or comparison | `{analysis_type, documents_processed}` |
| `sage_forecasting` | Running forecast pipeline | `{forecast_type, reference_class_found, scenarios_built}` |
| `sage_verifying` | Cross-referencing claims | `{claims_checked, conflicts_found}` |
| `sage_synthesizing` | Composing response | `{findings_count}` |
| `sage_reply_delta` | Streaming response text | `{delta: "..."}` |
| `sage_confidence_update` | Confidence score calculated | `{claim, confidence, sources}` |
| `sage_conflict_detected` | Contradiction found | `{entry_a, entry_b, nature}` |
| `sage_recommendation` | Recommendation for Butler | `{recommendation_type, entry_id}` |
| `sage_turn_done` | Turn complete | `{turn_id, total_actions, findings_count, confidence}` |

---

## 14. What Sage Does NOT Do

```
✗ Code execution or code generation
✗ Image generation or image editing
✗ Task execution (no file operations beyond knowledge storage)
✗ Direct memory modification (recommends to Butler, doesn't write to other members' CON)
✗ Creative synthesis ("what if we combine X and Y?")
✗ Emotional support or companionship (Mate's domain)
✗ Task planning or scheduling (Butler's domain)
✗ User preference management (Butler's domain, Sage only provides knowledge)
✗ Claiming certainty ("this is definitely true")
✗ Making decisions for the user
✗ Blocking or deleting knowledge (recommends only)
✗ Fact-checking casual conversation unless asked
✗ Source fabrication (every claim must trace to a real source)
✗ Circular citation (A cites B, B cites A — detected and flagged)
✗ Unanchored prediction — every forecast must cite reference class and base rate
✗ Precision illusion — never output a point prediction without a confidence interval
✗ Oracle-style prophecy — Sage cannot answer "who will win?", "what's the price?", "when will AGI arrive?" without downgrading to conditional analysis
✗ Personal predictions — "will they reply?", "will I succeed?" are outside Sage's domain
```

---

## 15. Implementation Dependencies

### What Must Exist Before Sage Can Be Built

| Dependency | Why | Status |
|-----------|-----|--------|
| **Core SDK** | PER/CON/MEM/PromptAssembler/Guardrail must be extracted as shared library | P4 (before Phase 8) |
| **Butler Online** | Sage needs Butler to execute recommendations; Butler triggers Sage's memory reviews | Phase 7 (before Phase 8) |
| **Cold CON** | Sage queries cross-member CON for knowledge and memory review | Already exists (needs extension) |
| **Vector Database** | Knowledge index requires vector search for semantic retrieval | Part of Core SDK or new dependency |
| **Web Search Infrastructure** | Sage's primary external data source | Already exists (sidebar assistant has it) |
| **Document Parsing** | Upload + parse + chunk + index pipeline | Partially exists (file upload exists) |
| **SSE Infrastructure** | Event streaming for progressive UI updates | Already exists (Artist uses it) |

### Phase 8 Scope (from PLAN.md)

```
LamSage Phase 8:
  - Sage PersonaDef + PER registration
  - Sage runtime + verification pipeline
  - Knowledge index (vector DB)
  - Source registry + reliability scoring
  - query_sage tool for member access
  - WebView knowledge base panel (frontend)
  - Desktop pet + tray integration
  - Proactive polling engine (basic)
  - Confidence decay (basic)
  - Deep research: SageProject + entity templates (basic: company, technology, person)
  - Forecasting engine (basic: trend extrapolation + reference class)
```

### Post-Phase 8 (P3/P4)

```
  - Advanced cross-lingual knowledge alignment
  - Automatic source discovery (find new reliable sources)
  - Knowledge graph visualization
  - User knowledge profile learning (domain preference, depth, style)
  - Predictive pre-fetching (anticipate what members will need)
  - Cross-session causal analysis (did following this advice lead to good outcomes?)
  - Deep research: full entity template library + multi-project management
  - Forecasting: scenario tree generation + forecast accuracy backtesting
  - Bias detection engine (selective citation, statistical misuse, conflict of interest)
  - Knowledge coverage heatmap visualization
  - Source retraction cascade engine (one source retracted → find all downstream affected entries)
```

---

## 16. Architecture Comparison

| Dimension | Artist | Writer | Sage |
|-----------|--------|--------|------|
| **Core Loop** | handle_turn (LLM → parse → execute) | while(true) agent loop | while(true) event loop |
| **Primary Output** | Images | Code, text, documents | Knowledge entries with provenance |
| **Artifact Type** | Generated images with lineage | Files, commits, test results | Verified claims with evidence chains |
| **State Model** | FSM (anchor→pack→refine) | Part-based message model + workspace state | Phase-based (search→verify→synthesize) |
| **Collaboration** | Receives requests from Writer | Queries Artist, queries Sage | Serves all members, queries none |
| **User Interaction** | Real-time streaming + checkpoint | Streaming CLI-style with approval gates | Knowledge base panel + Q&A + proactive feed |
| **Memory Model** | Image lineage + style preferences | Project context + coding patterns | Knowledge index + source registry + verification trail |
| **Safety Concern** | Image content safety | File system safety | Information cascade prevention + forecast anchoring |
| **Timescale** | Seconds to minutes per turn | Minutes to hours per task | Continuous (background) + seconds (queries) + hours (deep research) |
| **Autonomy Level** | Medium (asks for clarification) | High (loops until done, stops for danger) | High (continuous background, research projects) but bounded (curiosity budget, forecast confidence cap) |
| **Unique Capability** | Style-anchored iterative generation | Self-verifying code execution loop | Evidence-anchored forecasting + multi-source deep research |

---

## 17. Success Criteria

Sage is properly implemented when:

1. **Knowledge Retrieval**: Other members can query Sage and receive answers faster than searching the web themselves, with higher confidence.
2. **Verification Pipeline**: A claim submitted to Sage is checked against 3+ sources, cross-referenced, and returned with a confidence score within 10 seconds.
3. **Cascade Prevention**: No sub-threshold (confidence < 0.6) knowledge entry is ever served to a downstream member through query_sage.
4. **Provenance Completeness**: Every knowledge entry in the index has at least one source citation with retrieval timestamp.
5. **User Override**: When the user says "that's wrong," the entry's confidence resets to 0 and the entry is queued for re-verification within the next proactive cycle.
6. **Butler Integration**: Sage's conflict_detected recommendations are delivered to Butler, and Butler can accept/defer/reject them with the decision logged.
7. **Confidence Decay**: Entries older than 90 days have decayed confidence, and entries older than 180 days are flagged for re-verification.
8. **Curiosity Budget**: Sage's autonomous exploration never exceeds the configured daily budget without user override.
9. **Source Reliability**: Source reliability scores update based on corroboration history; sources with repeated contradictions have their scores appropriately lowered.
10. **Cross-Member Memory**: Sage can search Cold CON across all members and return relevant experiences when queried about "what does the project know about X."
11. **Forecast Anchoring**: Every forecast output includes: forecast type label, reference class, base rate, assumption list, alternative paths, and confidence interval. No forecast is served with confidence > 0.85.
12. **Deep Research Delivery**: A research project ("整理 OpenAI") collects 20+ sources, structures output by entity template, and delivers within 3 minutes. User can stop at any checkpoint and receive partial results.
13. **Prediction Audit Trail**: Every forecast logs its inputs (data points, reference class, assumptions), outputs (scenarios, confidence intervals), and can be reviewed later. "Why did Sage predict X?" is always answerable.

---

## 18. Key Risks

### Risk 1: False Confidence (The "Looks Authoritative" Problem)

**Symptom**: Sage assigns high confidence to a claim that comes from multiple sources — but all those sources copied each other (circular citation, echo chamber).

**Mitigation**:
- Source reliability scoring includes "independence check" — sources from the same domain/publisher are not counted as independent corroboration
- Circular citation detection: if A cites B and B cites A, flag as single-source
- "Novel claim" bonus: claims that appear in only one source start at lower confidence
- User feedback loop: if user corrects a high-confidence claim, it triggers source reliability downgrade for all involved sources

### Risk 2: Verification Paralysis

**Symptom**: Sage spends so long verifying that it never serves knowledge. The pipeline becomes a bottleneck.

**Mitigation**:
- Fast path: cached high-confidence entries returned immediately
- Timeout: verification has a per-query time limit (configurable, default 15s); return best available result when timeout hits
- Async indexing: Sage responds first, indexes/verifies in background
- Confidence transparency: "Answered from cache (verified 2026-05-15, confidence 0.92). Full re-verification in progress."

### Risk 3: Authority Creep

**Symptom**: Over time, members trust Sage so completely they stop doing their own verification. Sage becomes a single point of failure for the entire family's knowledge.

**Mitigation**:
- Sage NEVER claims certainty — confidence is always displayed as a score, not a binary
- Every Sage response includes caveats section by default
- Members' PERs should include: "Sage provides evidence, not decisions. You are responsible for your output."
- User can always ask Sage "how do you know this?" — and Sage must show the full evidence chain

### Risk 4: Over-Correction by User

**Symptom**: User corrects Sage too aggressively, causing Sage to lose confidence in genuinely correct knowledge.

**Mitigation**:
- User correction resets confidence to 0 but preserves the original evidence chain
- Re-verification includes the user's correction as a weighted source, not as absolute truth
- If re-verification confirms the original claim, confidence returns to original level (the user was wrong this time)
- Sage logs all user corrections with outcomes — patterns of incorrect corrections may indicate user knowledge gaps (handled delicately, reported to Butler)

### Risk 5: Prediction Over-Reliance (The "Sage Said So" Problem)

**Symptom**: Users treat Sage's forecasts as authoritative predictions rather than evidence-anchored projections. A user makes a career or financial decision based on Sage's trend extrapolation, and the outcome differs.

**Mitigation**:
- Every forecast carries a mandatory "此分析不构成建议" (this analysis does not constitute advice) header
- Forecast confidence is capped at 0.85 — visually distinct from factual knowledge (which can reach 0.95+)
- Every forecast includes an explicit "what would change this" section — so users understand the contingency
- Long-term forecasts (>6 months) carry an additional "长期预测，不确定性极高" flag
- Forecasting tools (extrapolate_trend, find_reference_class) log their inputs and assumptions — full audit trail
- Financial/health/safety forecasts are never served to downstream members; user-facing only
- Sage's PER instructs: "When asked a forecasting question, first assess whether you have enough evidence to give a meaningful projection. If not, state that clearly. Never package a guess as a forecast."

### Risk 6: Research Depth Creep (The "Endless Rabbit Hole")

**Symptom**: User asks "整理 OpenAI 的所有信息" — Sage starts a deep research project. The scope keeps expanding (competitors, industry trends, historical context). The project never finishes. User gets frustrated.

**Mitigation**:
- Research projects (SageProject) have explicit scope boundaries set at creation time
- Scope changes require user confirmation ("Research found 3 related topics not in original scope. Include them?")
- Projects have a progress indicator: "Phase 1/3 complete. 47 sources collected. Estimated 5 min remaining."
- Timeout: if a research project exceeds a configurable time limit, Sage delivers what it has with a "partial results" flag
- User can always say "stop and give me what you have" — Sage delivers immediately
- Project scope is broken into phases; each phase delivers a checkpoint — user can stop between phases

---

## 19. Frontend Design — Knowledge Base Panel

### 19.1 Layout

```
┌──────────────────────────────────────────────────────────────┐
│  LamSage — 知识库                                    [⚙] [×] │
├──────────────────────────────────────────────────────────────┤
│  ┌────────────────────────────────────────────────────────┐  │
│  │ 🔍 搜索知识库...                              [搜索]   │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                               │
│  ┌─ 快速提问 ─────────────────────────────────────────────┐  │
│  │  [输入问题...]                              [提问]     │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                               │
│  ┌─ 最近更新 ─────────────────────────────────────────────┐  │
│  │  今天 14:32  Vue 3.5 响应式系统性能分析     置信度 0.91 │  │
│  │  今天 11:15  React 19 并发特性最佳实践       置信度 0.87 │  │
│  │  昨天 09:00  Python asyncio 常见反模式        置信度 0.93 │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                               │
│  ┌─ 订阅话题 ─────────────────────────────────────────────┐  │
│  │  🔔 前端框架更新      最后检查: 今天 08:00    [管理]    │  │
│  │  🔔 AI 图像生成趋势   最后检查: 昨天 20:00    [管理]    │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                               │
│  ┌─ 待验证 ───────────────────────────────────────────────┐  │
│  │  ⏳ 3 条新信息待交叉验证                        [查看]   │  │
│  │  ⚠ 2 条知识已过期，待重新验证                   [查看]   │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                               │
│  ┌─ 探索队列 ─────────────────────────────────────────────┐  │
│  │  今日剩余探索预算: 3/5                                 │  │
│  │  📋 GraphQL vs REST 2026 对比                          │  │
│  │  📋 WebAssembly 在前端的实际应用                        │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

### 19.2 Interaction Patterns

- **Search**: Full-text + semantic search across knowledge index. Results show confidence badge, last verified date, source count.
- **Quick Question**: Free-form question → Sage processes → streaming answer with source citations.
- **Knowledge Card**: Click any entry → full detail: content, confidence history, source list, evidence chain, counterexamples.
- **Feedback**: Every answer has "This is correct" / "This needs correction" buttons. Correction opens a text field for the user to explain.
- **Upload**: Drag-and-drop documents → Sage parses, indexes, confirms "3 new documents indexed. 47 claims extracted. Ready for questions."
- **Desktop Pet**: Small Sage icon in corner with status indicators (green = idle, yellow = verifying, blue = exploring, red = conflict detected).
- **Tray**: System tray icon with quick actions: "Ask Sage...", "Upload document...", notification count.

---

## 20. References

| Document | Relevance |
|----------|-----------|
| `docs/mental-model.md` L358-458 | Sage's role in CON/MEM/Butler/Sage governance, Sage Review schema, three memory levels, evolution loop |
| `docs/lamtools-ecosystem.md` L159-170, L569-583, L678-747 | Sage product definition, persona character, story "暂" |
| `docs/lamtools-philosophy.md` L677-707 | Sage philosophy: 求真/证据/校准/反例, role in PER evolution |
| `docs/lamtwo-persona-v0.1.md` L1100-1108 | Sage power dimensions: verification authority, real-time authority, counterexample authority |
| `docs/ROADMAP.md` L92, L229 | Sage startup conditions, MEM Judgment + 入库验证 + 多源交叉印证 |
| `docs/plans/PLAN.md` L404-416 | Phase 8 = LamSage, UI form, startup topology |
| `docs/plans/2026-05-20-writer-architecture.md` L37, L660-751 | Writer-Sage collaboration, query_sage tool pattern |
| `docs/coder-per-v1.md` L100-101 | Coder-Sage knowledge relationship |
| `docs/butler-per-v1.md` L114 | Sage in Butler's awareness scope |
| `docs/competitive-research.md` | Sage vs Perplexity, reference repos |
| `docs/plans/2026-05-19-artist-realism-architecture.md` | Pattern reference: persona architecture doc structure |
| `docs/plans/2026-05-20-writer-architecture.md` | Pattern reference: most comprehensive architecture doc (2340 lines) |

---

## Appendix: User Story Map

### Story 1: The Developer's Question

> Coder is writing a React component and encounters a performance issue with large lists. Coder asks Sage: "What's the current best practice for virtualizing long lists in React 19?"
> 
> Sage checks its knowledge index — finds an entry from 3 weeks ago about React 19's built-in `<VirtualList>` component. Confidence: 0.88. Sources: React 19 release notes, 2 blog posts, 1 conference talk.
> 
> Sage returns: the summary, the code example, the sources, and a caveat: "The API changed between React 19.0 and 19.1. This entry covers 19.1. If your project uses 19.0, the `itemSize` prop works differently."
> 
> Coder uses the pattern. It works. Coder's feedback ("this was correct") increases the entry's confidence to 0.91 and adds Coder's practical validation as a new evidence point.

### Story 2: The Contradiction

> A user uploads a technical article claiming "Rust's async is fundamentally faster than Go's goroutines for I/O-bound workloads."
> 
> Sage's existing knowledge index has an entry from 2 months ago: "Go's goroutines and Rust's async have comparable I/O performance; the choice depends on ecosystem and developer experience." Confidence: 0.85. Sources: 3 benchmark papers.
> 
> Sage cross-references the new article against the existing entry. Detects: contradiction. The new article's benchmark methodology differs from the existing papers — it uses a different workload.
> 
> Sage does NOT replace the old entry. Instead:
> 1. Stores the new claim as a separate entry (confidence: 0.45 — single source, methodology differs from consensus)
> 2. Creates a conflict record linking both entries
> 3. Flags to Butler: "conflict_detected: Rust vs Go async I/O performance. Existing consensus vs new single-source claim."
> 4. Responds to user: "This claim contradicts our existing knowledge (confidence 0.85 vs 0.45). The benchmark methodology differs. I've flagged this for review. Current recommendation: treat the existing consensus as more reliable until the new methodology is independently reproduced."

### Story 3: The Gap Filler

> User asks Sage: "What's the state of CSS Container Queries in 2026?"
> 
> Sage finds good knowledge about Container Queries basics (confidence 0.92) and browser support (confidence 0.95). But the index has no entry about "Container Queries with CSS Grid" — an adjacent topic.
> 
> Sage answers the original question first. Then, because curiosity budget remains (3/5), Sage queues: "Explore: Container Queries + CSS Grid interaction patterns."
> 
> In the next proactive cycle, Sage searches for this topic, finds relevant articles, verifies, and indexes. The next time someone asks, Sage has the answer ready.
> 
> The user sees in the exploration queue: "Container Queries + CSS Grid — explored, 2 new entries indexed (confidence 0.78, 0.82)."

### Story 4: The Correction

> Sage has an entry: "Python 3.14 removes the GIL." Confidence: 0.75. Sources: 2 tech blog posts.
> 
> User sees this and corrects: "This is misleading. Python 3.13 introduced the option to disable the GIL (--disable-gil flag). 3.14 made it the default but didn't 'remove' it — it's still there for C extensions."
> 
> Sage:
> 1. Resets confidence to 0
> 2. Preserves original evidence chain
> 3. Adds user's correction as a high-weight source
> 4. Queues for re-verification
> 5. In re-verification, finds official Python 3.14 release notes confirming the user is correct
> 6. Updates entry: "Python 3.14 makes自由线程模式 the default (GIL remains for C extension compatibility)." Confidence: 0.93. Sources: Python 3.14 release notes, PEP 703, user correction.
> 7. Logs: the user was right, original sources were imprecise. Downgrades source reliability for the two blog posts.

### Story 5: The Forecast

> User asks Sage: "Rust 会取代 C++ 吗？"
>
> Sage recognizes this as a forecasting question — not a factual query. It classifies as [趋势外推 + 参照类预测].
>
> Sage's pipeline:
> 1. **Gather trend data**: GitHub language stats (Rust: +12% YoY, C++: +3% YoY), Stack Overflow survey (Rust "most admired" 8th year), job postings (Rust +40% YoY), Linux kernel / Windows kernel Rust adoption, teaching institution adoption
> 2. **Find reference class**: Historical language replacements — C → C++ (took ~15 years), Objective-C → Swift (took ~5 years in Apple ecosystem), CoffeeScript → ES6 (took ~3 years), Python 2 → Python 3 (took ~12 years)
> 3. **Assess conditions**: For a language to "replace" another: (a) performance parity or superiority, (b) ecosystem maturity, (c) institutional mandate, (d) education pipeline, (e) incremental adoption path. C++ has all five for its domain. Rust has (a) and growing (b)(d)(e), but lacks (c) in most industries.
> 4. **Build scenarios**:
>    - Scenario A (60-75% probability): Rust becomes co-equal in new system-level projects by 2030, but C++ retains legacy codebases indefinitely. "Replace" is the wrong word — "coexist with growing Rust share" is more accurate.
>    - Scenario B (15-25% probability): A Rust safety mandate (e.g., US government) accelerates adoption, Rust achieves > 50% share in new systems projects by 2028.
>    - Scenario C (5-10% probability): C++ committee delivers "safe C++" that closes the safety gap; Rust's growth slows.
> 5. **Confidence**: 0.70 for central estimate (Scenario A). Capped at 0.85 per forecasting rules.
> 6. **Key uncertainty**: Regulatory intervention (government mandate) would be the strongest accelerant and is the hardest to predict.
>
> Sage responds:
> "这是一个预测性问题。我的分析基于历史语言替代案例和当前趋势数据。[参照类预测]
>
> 核心结论：在未来 5-8 年内，Rust 更可能在新增系统级项目中与 C++ 形成共存的局面，而非完全'取代'（置信度 60-75%）。
>
> 证据基础：Rust 在 GitHub 上的年增长率为 12%（C++ 为 3%）；Stack Overflow 连续第 8 年将 Rust 评为'最受喜爱语言'；Rust 招聘需求年增 40%；Linux 内核和 Windows 内核均已接受 Rust。
>
> 参照类：C → C++ 用了约 15 年；Objective-C → Swift（Apple 生态强制推动）用了约 5 年；Python 2 → Python 3 用了约 12 年。Rust → C++ 的替代更接近 C → C++ 的模式（无单一公司强制推动）。
>
> 假设清单：以下假设如不成立，结论需重新评估：
> - Rust 生态继续以当前速度成熟
> - 不出现强制性的安全法规（如美国政府要求关键基础设施使用内存安全语言）
> - C++ 委员会未能提供与 Rust 同等安全保证的'安全 C++'
>
> 替代路径：如果有强制性安全法规出台，Rust 可能在 2028 年前在新系统项目中超过 50% 份额（概率 15-25%）。如果 C++ 成功提供'安全 C++'，Rust 的增长可能放缓（概率 5-10%）。
>
> 此分析基于截至 2026-05-21 的公开信息。不构成技术选型建议。长期预测不确定性极高，建议 6 个月后重新评估。最终决定权在你。"

### Story 6: The Deep Research

> User says: "Sage，整理 OpenAI 的所有信息。"
>
> Sage recognizes this as a deep research task. It creates a SageProject:
>
> Phase 1 — 信息收集:
> - 扫描来源：OpenAI 官网、Wikipedia、Crunchbase、新闻报道、学术论文、GitHub 仓库、Twitter/X、监管文件
> - 去重：同一事件的多家报道合并为一条
> - 进度："47 条信息来源已收集。Phase 1 完成。"
>
> Phase 2 — 结构化:
> - 按「公司实体模板」组织：基本信息 → 团队 → 产品 → 技术 → 融资 → 竞品 → 时间线 → 争议
> - 标注信息缺口："董事会结构：2023-11 期间的信息存在矛盾（Sam Altman 去留事件）。已交叉引用 5 个来源，结论已标注。"
> - 进度："结构化完成。8 个维度，3 个信息缺口已标记。"
>
> Phase 3 — 验证与置信度:
> - 逐声明交叉验证
> - 标注传闻 vs 官方确认 vs 媒体报道
> - "Sam Altman 被解雇的原因"：标注为「存在多种说法，已分别收录并标注来源。无单一权威结论。」
> - 进度："验证完成。整体置信度 0.82。12 条声明标注为'单一来源，待进一步验证'。"
>
> Phase 4 — 交付:
> - 完整报告（WebView 渲染）+ 结构化数据导出
> - 标注：最后更新 2026-05-21，建议下次更新 2026-06-21
> - 自动设置订阅："OpenAI 重大新闻" — 有变化时通知用户
>
> 用户在 Phase 2 和 Phase 3 之间各有一个检查点，可以喊停或调整方向。
