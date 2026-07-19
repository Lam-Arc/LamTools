<!-- 历史参考，不代表当前架构 -->
# LamWriter 小说写作子功能 — 设计文档

> **定位**：Writer 可调用的子功能，非独立产品。Writer 是匠人——代码和文字都做。小说写作是他文字能力的最高复杂度场景。
>
> **版本**：v1.1 / 2026-05-26
>
> **状态**：设计阶段，未落地代码

---

## 文档索引

| 文档 | 用途 |
|------|------|
| `docs/2026-05-20-writer-architecture.md` | Writer 主架构设计，本文档的子功能集成目标 |
| `docs/mental-model.md` | PER/CON/PLAN/Skill 心智模型，本文档的记忆体系基础 |
| `docs/writer-per-v1.md` | Writer PER 定义，小说子功能遵循此人格 |
| `docs/ROADMAP.md` | P3/P4 技术路线 |
| `docs/PLAN.md` | 总控计划（Phase 6: LamWriter） |

---

## 一、背景与目标

### 1.1 为什么需要小说写作子功能

Writer 的文本能力覆盖邮件、文档、翻译、方案。但小说/网文创作是文本能力的**最高复杂度场景**：

| 复杂度来源 | 具体挑战 |
|-----------|---------|
| 长度 | 百万字级别，远超 LLM 上下文窗口 |
| 时间跨度 | 连载数月甚至数年，跨 session 一致性要求极高 |
| 文风一致性 | 同一本书内文风渐变（早期 vs 后期），不能一刀切 |
| 伏笔追踪 | 前 10 章埋的伏笔，第 300 章要回收；已弃用的伏笔要标记 |
| 角色一致性 | 数十个角色，每个人的性格、语言指纹、蜕变弧线不能断裂 |
| 世界观连贯 | 规则体系一旦确立，不能前后矛盾 |
| 情绪节奏 | 高潮/低谷的交替频率，紧张感的梯度控制 |

这不是"让 LLM 写一段小说"能解决的问题。这是**长周期、跨 session、多维度一致性的系统工程问题**。

### 1.2 设计目标

| 目标 | 衡量标准 |
|------|---------|
| **文风指纹提取** | 从用户提供的文本样本中提取多维结构化风格指纹，可量化、可注入 |
| **文风一致性保障** | 生成文本经指纹标注后，风格漂移可自动检测 |
| **伏笔追踪** | 跨章节伏笔状态机管理，种草/暗示/回收/弃用全生命周期 |
| **记忆不丢** | 百万字场景下，当前场景需要的上下文（角色/世界观/上一章摘要）精准注入 |
| **与 Writer 无缝集成** | 作为 Writer 的子功能，复用 PER/CON/PLAN/MEM/Prompt 组装线 |

### 1.3 非目标

- 不做完整的"AI 写小说"独立产品
- 不做前端小说编辑界面（复用 Writer 对话流）
- 不做多人协作创作（v1 单用户）
- 不做自动发布/连载管理
- 不做封面/插图生成（可委托 Artist，但非本子系统范围）

---

## 二、创作流程拆解

### 2.1 三阶段模型

```
Pre-writing（筹备）
  ├── 世界观设定（地图、历史、规则体系）
  ├── 角色创建（性格、背景、欲望/恐惧、关系图）
  ├── 大纲设计（幕/卷/章/节层级结构）
  ├── 文风定调（参考文本采样 → StyleFingerprint 提取）
  └── 节奏规划（高潮/低谷分布、情绪曲线）

Writing（写作循环）
  ├── 章节规划（单个章节的 scene/beat 拆解）
  ├── 场景写作（实际文本生成，注入 StyleFingerprint）
  ├── 伏笔管理（新伏笔记录、已有伏笔状态更新、即将到期伏笔提醒）
  ├── 连续性自审（角色言行一致 / 世界观规则验证 / 前后逻辑检查）
  └── 风格漂移检测（STYLEDISTANCE 与基准指纹对比）

Post-writing（后处理）
  ├── 全文一致性遍历
  ├── 伏笔回收率统计
  ├── 角色弧线完整性评估
  └── 文风演化分析报告
```

### 2.2 创作循环（单次 Writing Turn）

Writer 的 while(true) loop 框架内，小说写作子功能的一次 turn：

```
1. 用户输入 → WriterRuntime.handle_turn()
2. 意图解析 → task_type = PROSE_NOVEL
3. PER + CON + Hot CON 组装
   ├── PER: Writer 人格（极简匠人）
   ├── Hot CON: 上一章摘要 + 当前章节大纲 + 相关角色/世界观
   ├── StyleFingerprint: 当前创作阶段的风格基线 → 注入 System Prompt
   └── 伏笔台账: 当前章需要涉及和即将到期的伏笔 → 注入 System Prompt
4. LLM 生成文本
5. 连续性自审（check_character_consistency / check_world_rules / check_foreshadowing）
6. WriterTurn 返回（文本 + 审阅结果 + 记忆写回）
7. 记忆写回
   ├── 新伏笔 → NovelTagSystem.record()
   ├── 已回收伏笔 → NovelTagSystem.update_status(resolved)
   ├── 角色状态更新 → CharacterProfile 修订
   ├── 章节摘要 → Cold CON conversation_summaries
   └── 风格漂移检测 → 如果漂移超阈值，生成告警
```

---

## 三、文风指纹体系（StyleFingerprint）

### 3.1 设计原则

**文风不是标签，是多维向量。** "冷峻"、"细腻"、"诗化" 这类标签太模糊，无法精确注入 prompt。正确的做法是：**数据定方向 + 锚点定质感**。

- **数据方向**：量化的风格指标（平均句长、定语比例、感官词密度等），用于约束生成
- **锚点质感**：用户原文代表性段落（最多 1000 字 few-shot 样本），让 LLM 直觉理解文风

### 3.2 指纹结构

```python
class StyleFingerprint:
    """文风指纹：结构化 + 锚点"""

    # ─── 第一层：词法统计（Layer 1: 本地测量 pystylometry）───
    lexical: LexicalProfile
    #   avg_sentence_length: float        # 平均句长
    #   sentence_length_std: float        # 句长标准差（节奏变化幅度）
    #   type_token_ratio: float           # 词汇丰富度
    #   hapax_legomena_ratio: float       # 只用一次的词汇占比
    #   avg_word_length: float            # 平均词长
    #   punctuation_density: float        # 标点密度

    # ─── 第二层：句式统计 ───
    syntactic: SyntacticProfile
    #   modifier_ratio: float             # 定语比例（形容词/定语从句密度）
    #   subordinate_clause_ratio: float   # 从句嵌套深度
    #   passive_voice_ratio: float        # 被动语态占比
    #   sentence_openings: dict[str, float] # 句首词分布（"他"、"突然"、"那时"...）
    #   paragraph_length_avg: float       # 平均段落长度
    #   dialogue_ratio: float             # 对话占比
    #   fragment_sentence_ratio: float    # 破碎句/不完整句占比

    # ─── 第三层：修辞密度 ───
    rhetorical: RhetoricalProfile
    #   metaphor_density: float           # 隐喻密度
    #   simile_density: float             # 明喻密度
    #   personification_density: float    # 拟人密度
    #   rhetorical_question_ratio: float  # 反问占比
    #   repetition_patterns: list[str]    # 重复模式（排比、首语重复等）
    #   allusion_complexity: float        # 用典复杂度（0-1）

    # ─── 第四层：感官分布 ───
    sensory: SensoryProfile
    #   visual_ratio: float               # 视觉描写占比
    #   auditory_ratio: float             # 听觉描写占比
    #   tactile_ratio: float              # 触觉描写占比
    #   olfactory_ratio: float            # 嗅觉描写占比
    #   gustatory_ratio: float            # 味觉描写占比
    #   kinesthetic_ratio: float          # 动觉描写占比
    #   interior_monologue_ratio: float   # 心理描写占比

    # ─── 第五层：情绪节奏 ───
    rhythm: RhythmProfile
    #   avg_tension: float                # 平均紧张度（0-1）
    #   tension_variance: float           # 紧张度波动
    #   climax_spacing: float             # 高潮间隔（平均章节数）
    #   emotional_valence: float          # 情绪效价（-1消极 ~ 1积极）
    #   emotional_arc: list[float]        # 情绪曲线（逐章节 tension 向量）

    # ─── 第六层：叙述者特征 ───
    narrator: NarratorProfile
    #   pov_type: str                     # "first_person" | "third_limited" | "third_omniscient" | "second_person"
    #   narrator_distance: float          # 叙述距离（0=沉浸式内心独白，1=全知评述）
    #   narrator_subjectivity: float      # 叙述者主观性（0=客观报道，1=主观心理）
    #   tense: str                        # "past" | "present" | "mixed"
    #   narrative_speed: float            # 叙述速度（0=场景实时，1=概述跳跃）

    # ─── 第七层：留白与隐晦 ───
    implicitness: ImplicitnessProfile
    #   subtext_density: float            # 潜文本密度（言外之意占比）
    #   ellipsis_ratio: float             # 省略/留白占比
    #   ambiguity_tolerance: float        # 歧义容忍度（0=直白，1=混沌）
    #   irony_density: float              # 反讽密度
    #   show_vs_tell: float               # Show/Tell 比（0=纯叙述，1=纯展示）

    # ─── 第八层：锚点段落 ───
    anchors: StyleAnchors
    #   excerpts: list[StyleExcerpt]      # 代表性文本段落（每段 100-300 字）
    #   patterns: list[str]               # 标志性句式/语汇（自然语言描述）
    #   voice_notes: str                  # LLM 合成的文风综述（一段话，用于 Prompt 注入）
    #   anti_patterns: list[str]          # 应该避免的风格特征

    # ─── 元信息 ───
    metadata: FingerprintMetadata
    #   source_volume: int                # 来源卷号（文风按卷分别提取）
    #   sample_chapters: list[int]        # 采样章节
    #   sample_word_count: int            # 采样总字数
    #   extraction_method: str            # "pystylometry+llm" | "llm_only" | "pystylometry_only"
    #   extracted_at: str                 # ISO 时间戳
    #   confidence: float                 # 指纹置信度（采样量越大越高）
```

### 3.3 三层混合提取架构

```
Layer 1: 本地统计测量（pystylometry）
  └── 输入：用户提供的 TXT 文本（按卷分章）
  └── 输出：LexicalProfile + SyntacticProfile + SensoryProfile（纯数值）
  └── 工具：pystylometry（MIT 许可，50+指标/11模块）
  └── 优势：精确、可复现、零 token 消耗、可在本地运行
  └── 局限：无法理解"反讽密度"、“潜文本”等语义维度

Layer 2: LLM 合成指纹（结构化分类）
  └── 输入：用户原文锚点段落（100-300字×5-10段）+ Layer 1 统计数值
  └── 输出：RhetoricalProfile + NarratorProfile + ImplicitnessProfile + voice_notes + anti_patterns
  └── 工具：任何 LLM（Prompt: "分析以下文本段落的修辞特征、叙述者特征、留白风格..."）
  └── 优势：语义理解（反讽、潜文本、Show/Tell）
  └── 局限：token 消耗、采样偏差、不可复现

Layer 3: 风格漂移检测（STYLEDISTANCE）
  └── 输入：基准 StyleFingerprint + 当前生成的文本
  └── 输出：风格距离分数 + 偏差维度列表
  └── 工具：STYLEDISTANCE 开源风格嵌入模型（HuggingFace）
  └── 触发：每次生成新章节后自动运行
  └── 阈值：距离 > 0.7 触发告警（"本章风格与基线偏差较大：句长骤降30%，感官描写缺失"）
```

**为什么不是纯 LLM 提取**：纯 LLM 提取虽然灵活，但有以下问题：
- 不可复现：同一文本两次提取结果可能不同
- Token 消耗高：百万字全文喂给 LLM 不现实
- 量化精度低：LLM 说"句长中等"不如 pystylometry 的 `avg_sentence_length=18.3` 精确

**为什么不是纯统计提取**：统计只能做到词法/句法层，对修辞风格、叙述者、潜文本等语义维度无能为力。两层互补：统计提供精度，LLM 提供理解。

### 3.4 风格随卷演化

同一本书内，文风会渐变。所以**不按书做全局指纹，按卷分别提取**。

```python
# 存为列表，按 volume 索引
novel_style_timeline: list[StyleFingerprint]  # [vol1指纹, vol2指纹, vol3指纹, ...]

# 当前创作时：取最近一卷的指纹 + 上一卷的指纹（检测渐变）
# 风格漂移检测参照：当前卷指纹
# 全书风格演化分析：所有指纹的时间序列
```

### 3.5 Prompt 注入策略

StyleFingerprint 如何进 Writer 的 System Prompt：

```
注入位置：Hot CON 段，紧跟 PER 之后
注入内容（按体积裁剪）：

[文风基线 - 第3卷]
  句长：18.3 ± 7.2 字 | 定语密度：0.23 | 对话占比：0.41
  感官：视觉 0.52 / 听觉 0.18 / 心理 0.22 / 触觉 0.05
  叙述：第三人称有限视角，中距离叙述（0.6），过去时
  节奏：平均紧张度 0.47，高潮间隔 ~5 章
  留白：潜文本密度 0.31，Show/Tell=0.67

[风格锚点]
  标志性句式："xxx不是...，而是..."、"那时的他还不知道..."
  避免：过长的景物描写、冗余心理活动、违背角色性格的对话

[锚点段落]
  （插入 2 段原文，每段不超过 200 字）
```

---

## 四、CON 标签体系（NovelTagSystem）

### 4.1 标签体系设计的哲学转变

Artist 的标签体系面向**模糊语义匹配**：`style="赛博朋克"`、`mood="冷蓝调"` 这类标签用于召回时的"大概相关"。

小说写作的标签体系面向**精确状态过滤**：需要知道"伏笔 X 当前是 planted 还是 hinted"、"角色 Y 在第 3 卷第 12 章发生了什么"、"这个世界观规则在哪些章节被使用了"。

**Artist 标签 = 模糊语义检索。NovelTagSystem = 精确状态机过滤。**

| 维度 | Artist 标签 | NovelTagSystem |
|------|------------|----------------|
| 标签数量 | ~8 种 task_type | ~7 种 entity_type + 状态字段 |
| 匹配方式 | 语义相似度 | 确定性地过滤 + 窗口内匹配 |
| 生命周期 | 对话结束时打标 | 实体创建时打标，状态机持续更新 |
| 检索精度 | "大概相关" | "精确命中" |
| 典型查询 | style≈"Q版" | type=foreshadow AND status=planted AND chapter<=current |

### 4.2 标签体系定义

```python
class NovelTag(str, Enum):
    """小说专用实体类型标签"""
    WORLD_RULE = "world_rule"           # 世界观规则（"在这个世界里，魔法消耗生命力"）
    CHARACTER = "character"             # 角色档案
    FORESHADOW = "foreshadow"           # 伏笔记录
    CHAPTER_SUMMARY = "chapter_summary" # 章节摘要
    VOLUME_OUTLINE = "volume_outline"   # 卷大纲
    PLOT_POINT = "plot_point"           # 关键情节点
    SCENE_DETAIL = "scene_detail"       # 场景细节（时间、地点、氛围）

class ForeshadowStatus(str, Enum):
    PLANTED = "planted"     # 已埋下
    HINTED = "hinted"       # 已暗示（第2次提及）
    RESOLVED = "resolved"   # 已回收
    ABANDONED = "abandoned" # 已弃用

class NovelEntityTag:
    entity_type: NovelTag               # 实体类型
    foreshadow_status: ForeshadowStatus | None  # 伏笔状态（仅 FORESHADOW 类型）
    volume: int                         # 所属卷号
    chapter: int                        # 所属章节号
    importance: float                   # 重要性 0-1（1=核心世界观规则/主线伏笔）
    rigidity: float                     # 刚性 0-1（1=不可修改的铁律，0=可灵活调整的倾向）
    character_names: list[str]          # 关联角色名
    location: str                       # 关联地点
    keywords: list[str]                 # 检索关键词
    created_at_chapter: int             # 创建时的章节号
    updated_at_chapter: int             # 最后更新时的章节号
```

### 4.3 伏笔状态机

这是 NovelTagSystem 的杀手级应用场景。

```
planted ──→ hinted ──→ resolved
  │           │
  └───────────┼──→ abandoned
              │
              └──→ abandoned
```

**状态转换规则**：

- `planted`：首次埋下伏笔。例子：第3章提到"角色A左手的疤痕在阴天会疼"。
- `planted → hinted`：再次提及该伏笔，增强读者记忆。例子：第27章再次提到"疤痕隐隐作痛"。
- `hinted → resolved`：伏笔回收，揭示真相。例子：第54章揭示"疤痕是夺舍的魔力印记"。
- `* → abandoned`：作者决定抛弃该伏笔（主线改道或忘记回收了）。标记为 abandoned 防止未来被误用。

**状态机守卫规则**：
- 伏笔 planted 后超过 30 章未 hinted → 生成提醒（"伏笔 X 已埋 30 章未再提及"）
- 伏笔 hinted 后超过 50 章未 resolved → 生成提醒（"伏笔 X 暗示后已过 50 章未回收"）
- 伏笔 resolved 后 → 不再参与提醒，但保留在台账中供全文一致性检查
- 伏笔 abandoned → 不参与提醒，不注入 prompt，但保留在台账中供审计

### 4.4 Hot CON 组装策略

小说写作场景的 Hot CON 组装与代码场景完全不同，分三个注入级别：

```python
# P0 确定性注入（无条件注入，token 预算最优先保障）
# 当前场景绝对需要的上下文
p0_injections = [
    # 上一章完整摘要
    get_previous_chapter_summary(current_chapter),

    # 当前章节大纲 / 节拍表
    get_current_outline(current_chapter),

    # 当前场景涉及的角色档案（角色列表 + 关键特征 + 当前状态）
    get_characters_in_scene(scene_id),

    # 当前场景涉及的世界观规则（场景地点 → 关联规则）
    get_world_rules_for_location(scene_location),

    # 当前卷的风格基线（StyeFingerprint）
    get_current_volume_style_fingerprint(),
]

# P1 窗口注入（当前章节 ± N 章范围内的相关实体）
p1_injections = [
    # 前 N 章内埋下的未回收伏笔（planted/hinted 状态）
    get_pending_foreshadows(window_before=10, window_after=0),

    # 前 N 章内出场的角色的最新状态
    get_recent_characters(window=5),

    # 当前章节到下一高潮的节奏要求
    get_rhythm_target(climax_distance),
]

# P2 关联注入（重要性高的全局实体）
p2_injections = [
    # 核心世界观规则（importance >= 0.8 且与当前卷相关）
    get_high_importance_world_rules(threshold=0.8),

    # 主线角色蜕变弧线（全角色重要性 >= 0.7）
    get_character_arcs(importance_threshold=0.7),

    # 即将到期的伏笔（hinted 超过 30 章未 resolved）
    get_expiring_foreshadows(threshold=30),
]
```

**注入顺序规定**（遵循 PER → Skill → Hot CON 的 PromptAssembler 规范）：

```
PER（Writer 人格，不变）
  → Skill（如用户加载了特定写作 Skill）
    → P0 Hot CON（确定性注入：上一章 + 大纲 + 角色 + 世界观 + 指纹）
      → P1 Hot CON（窗口注入：伏笔 + 近期角色 + 节奏）
        → P2 Hot CON（关联注入：核心规则 + 弧线 + 到期伏笔）
          → 对话历史（固定窗口）
            → 用户输入
```

**Token 预算分配**（小说场景默认总预算 8000 token）：

| 优先级 | 内容 | Token 预算 | 超出策略 |
|--------|------|-----------|---------|
| P0 | 确定性注入 | 4000 | 优先保证，P1/P2 压缩 |
| P1 | 窗口注入 | 2500 | 按 importance 排序截断 |
| P2 | 关联注入 | 1500 | 按 importance/expiry 排序截断 |

---

## 五、记忆分层

### 5.1 六大记忆维度及优先级

小说写作需要的记忆点远超代码场景。按重要性分三级：

**P0 级（当前场景必需，缺失即断裂）**

| 记忆维度 | 内容 | 存储位置 | 注入方式 |
|---------|------|---------|---------|
| 角色当前状态 | 角色现在在哪、和谁在一起、什么情绪/动机 | CharacterProfile.current_state | P0 确定性注入 |
| 上一章摘要 | 刚发生了什么 | CHAPTER_SUMMARY | P0 确定性注入 |
| 当前章节大纲 | 本章要完成什么 | VOLUME_OUTLINE | P0 确定性注入 |
| 当前卷风格基线 | 文风参数 | StyleFingerprint | P0 确定性注入 |
| 场景世界观 | 当前场景地的规则约束 | WORLD_RULE | P0 确定性注入 |

**P1 级（近期窗口相关，缺失会不连贯）**

| 记忆维度 | 内容 | 存储位置 | 注入方式 |
|---------|------|---------|---------|
| 近期伏笔 | 前10章内的 planted/hinted | FORESHADOW | P1 窗口注入 |
| 近期角色互动 | 前5章内的角色对话/关系变化 | CHARACTER + CHAPTER_SUMMARY | P1 窗口注入 |
| 情绪节奏 | 前几章的 tension 曲线 | RhythmProfile | P1 窗口注入 |
| 章节间连续性标记 | "第X章结尾在...处" | CHAPTER_SUMMARY + PLOT_POINT | P1 窗口注入 |

**P2 级（全局关联，缺失不会有立即问题但长期会崩塌）**

| 记忆维度 | 内容 | 存储位置 | 注入方式 |
|---------|------|---------|---------|
| 角色蜕变弧线 | 角色的完整转变轨迹 + 当前进度 | CharacterProfile.arc | P2 关联注入 |
| 核心世界观规则 | importance >= 0.8 的铁律 | WORLD_RULE | P2 关联注入 |
| 全书节奏规划 | 高潮分布图、卷间桥段 | RhythmProfile.emotional_arc | P2 关联注入 |
| 长期伏笔 | 超过10章的老伏笔 | FORESHADOW | P2 到期提醒 |
| 角色关系图谱 | 角色间的爱恨/联盟/敌对 | CharacterProfile.relationships | P2 关联注入 |

### 5.2 Cold CON 新增索引

Writer 小说子功能需要在 Cold CON 中新增以下结构化索引：

```python
class NovelColdCONIndex:
    """小说写作专用的 Cold CON 索引"""
    world_rules: list[WorldRule]             # 世界观规则库
    character_profiles: list[CharacterProfile] # 角色档案库
    foreshadow_ledger: list[ForeshadowEntry]  # 伏笔台账
    chapter_summaries: list[ChapterSummary]   # 章节摘要（按卷/章索引）
    volume_outlines: list[VolumeOutline]      # 卷大纲
    style_timeline: list[StyleFingerprint]    # 按卷的风格指纹时间序列
    plot_points: list[PlotPoint]              # 关键情节点
    continuity_checks: list[ContinuityCheck]  # 连续性检查记录
```

---

## 六、架构设计

### 6.1 子功能定位

小说写作是 **Writer 的一个子功能**，不是独立 Runtime。它共享 Writer 的 while(true) loop，但在以下环节插入小说专用逻辑：

```
WriterRuntime.handle_turn()
  │
  ├── 1. 意图解析 → task_type = PROSE_NOVEL
  │
  ├── 2. NovelHotCONAssembler.assemble()
  │       ├── 从 Cold CON 加载 NovelColdCONIndex
  │       ├── 按 P0 → P1 → P2 组装 Hot CON
  │       └── StyleFingerprint 注入
  │
  ├── 3. WriterPromptAssembler.build()
  │       ├── PER → Skill → P0 Hot CON → P1 Hot CON → P2 Hot CON
  │       └── 对话历史 + 用户输入
  │
  ├── 4. LLM 生成文本
  │
  ├── 5. NovelGuardrail.check()
  │       ├── CharacterConsistencyChecker: 角色言行一致
  │       ├── WorldRuleValidator: 世界观规则验证
  │       ├── ForeshadowingTracker: 伏笔状态检查
  │       └── StyleDriftDetector: 风格漂移检测（STYLEDISTANCE）
  │
  ├── 6. NovelSelfReview.review()
  │       ├── 人物对话是否出戏
  │       ├── 场景描写是否符合作者感官偏好
  │       ├── 节奏是否符合本章要求
  │       └── 伏笔是否正确提及/回收
  │
  └── 7. NovelMemoryWriteback.write()
          ├── 新伏笔 → FORESHADOW 写入
          ├── 章节摘要 → CHAPTER_SUMMARY 写入
          ├── 角色状态更新 → CharacterProfile
          ├── 风格漂移记录 → continuity_checks
          └── Cold CON 持久化
```

### 6.2 模块结构

```
backend/app/core/writer/
├── runtime.py                         # WriterRuntime（已有）
├── schemas.py                         # WriterTurn, WriterAction（已有，扩展小说 action）
├── prompts/
│   └── novel_prompt_assembler.py      # NovelHotCONAssembler（新建）
├── style/
│   ├── fingerprint.py                 # StyleFingerprint 数据结构（新建）
│   ├── layers.py                      # Layer1(pystylometry) + Layer2(LLM) 提取器（新建）
│   └── drift_detector.py             # Layer3 STYLEDISTANCE 漂移检测（新建）
├── novel/
│   ├── tag_system.py                  # NovelTagSystem 标签体系（新建）
│   ├── foreshadow.py                  # ForeshadowEntry + 状态机（新建）
│   ├── character.py                   # CharacterProfile（新建）
│   ├── world_state.py                 # WorldState + WorldRule（新建）
│   ├── narrative_plan.py              # NarrativePlan + VolumeOutline（新建）
│   ├── guardrail.py                   # NovelGuardrail: 角色/世界观/伏笔/风格四层检查（新建）
│   ├── self_review.py                 # NovelSelfReview（新建）
│   └── memory_writeback.py            # NovelMemoryWriteback（新建）
├── mem/
│   └── adapters/
│       └── novel_writer.py            # NovelWriterAdapter（新建，扩展 WriterAdapter）
└── events.py                          # 新增 novel_* SSE 事件

backend/tests/
└── writer/
    └── novel/                         # 小说子功能测试（新建）
```

### 6.3 与 Writer 集成的数据流

```
┌─────── 用户输入 ──────┐
│ "继续写第3卷第12章"    │
└──────────┬────────────┘
           ▼
    WriterRuntime
           │
           ├─ 意图解析: task_type=PROSE_NOVEL
           │
           ├─ NovelHotCONAssembler
           │    ├─ Cold CON → NovelColdCONIndex
           │    ├─ P0: 上一章(ch11)摘要 + 角色状态 + 世界观规则 + 第3卷风格指纹
           │    ├─ P1: 近期伏笔(planted/hinted, ch2-ch11) + 近期角色互动
           │    └─ P2: 核心规则 + 角色弧线 + 长期伏笔提醒
           │
           ├─ PromptAssembler
           │    ├─ PER: "你是 LamWriter。24岁匠人..."
           │    ├─ Skill: null（无加载）
           │    ├─ P0 Hot CON: [上一章摘要][当前大纲][角色状态][风格指纹]
           │    ├─ P1 Hot CON: [伏笔台账: F1(planted,ch3), F2(hinted,ch7)]
           │    ├─ P2 Hot CON: [世界观铁律 ×3][角色弧线: 主角→蜕变中]
           │    └─ Messages: 对话历史 + 用户输入
           │
           ├─ LLM 生成 ──→ 文本输出
           │
           ├─ NovelGuardrail
           │    ├─ CharacterChecker: PASS（角色A没说出格的话）
           │    ├─ WorldRuleChecker: PASS（魔法规则未被违反）
           │    ├─ ForeshadowingChecker: WARN（伏笔F2 hinted后已过5章，建议再次提及）
           │    └─ StyleDriftDetector: PASS（距离0.23 < 0.7阈值）
           │
           ├─ NovelSelfReview
           │    └─ 审查通过 | 3个建议: "角色B的对话偏口语化，与设定不符"
           │
           └─ NovelMemoryWriteback
                ├─ 新增伏笔F3(planted,ch12): "老者提到北方来的信使"
                ├─ 更新章节摘要 ch12
                ├─ 更新角色A状态（完成本章弧线节点）
                └─ 更新 Cold CON 索引
```

### 6.4 三层混合架构示意图

```
用户提供 TXT
      │
      ▼
┌─────────────────┐
│   Layer 1       │  pystylometry（本地计算，零 token）
│   本地统计测量    │  输入: 文本 → 输出: Lexical + Syntactic + Sensory 数值
└────────┬────────┘
         │ 数值向量
         ▼
┌─────────────────┐
│   Layer 2       │  LLM 合成（结构化分类）
│   LLM 合成指纹    │  输入: 锚点段落 + Layer1 数值
│                  │  输出: Rhetorical + Narrator + Implicitness + voice_notes
└────────┬────────┘
         │ 完整 StyleFingerprint
         ▼
┌─────────────────┐
│   Layer 3       │  STYLEDISTANCE（漂移检测）
│   风格漂移检测    │  输入: 基准指纹 + 新生成文本
│                  │  输出: 风格距离 + 偏差维度
└─────────────────┘
         │
         ▼
  NovelGuardrail 报告
```

---

## 六点五、TaskMode / PremiseLock / StoryBible Rewriter

> **新增（v1.2）**：长篇 E2E 暴露出的更深层问题不是“模型不会写”，而是系统没有把**任务意图**压过**原作语料惯性**。当用户说“用龙族的世界观和江南的文风写一本新小说”时，系统会被原作里最强的主线锚点（古德里安招生、卡塞尔学院、芝加哥）拖回“重写原作”的轨道。为解决这个问题，本章引入 TaskMode、PremiseLock 和 StoryBible Rewriter。

### 6.5.1 问题定位：为什么系统会把“原创”写成“重写”

当前失败模式不是文风漂移，而是**任务模式判断错误**：

| 用户真实任务 | 系统误判 |
|-------------|----------|
| 原作世界观下原创长篇 | 原作主线改写 |
| 借原作文风写新故事 | 延续原作高权重情节锚点 |
| 角色保留、时间线重置 | 世界观+剧情一起继承 |

这说明系统缺少一层：**在召回任何原作资料之前，先判定本次写作任务属于哪一类。**

### 6.5.2 TaskMode：先判定这次到底在做什么

```python
class TaskMode(str, Enum):
    CANON_REWRITE = "canon_rewrite"                     # 重写原作某段剧情
    CANON_SIDE_STORY = "canon_side_story"               # 原作世界观下支线/外传
    ORIGINAL_IN_CANON_WORLD = "original_in_canon_world" # 原作世界观下原创长篇
    STYLE_TRANSFER_ONLY = "style_transfer_only"         # 只借文风，不借剧情
    FULLY_ORIGINAL = "fully_original"                   # 完全原创
```

**默认规则**：

- 用户明确提到“重写”“改写”“如果当时……” → `CANON_REWRITE`
- 用户明确提到“同人”“外传”“新故事” → `CANON_SIDE_STORY` 或 `ORIGINAL_IN_CANON_WORLD`
- 用户只给文风样本，不给世界观/人物 → `STYLE_TRANSFER_ONLY`
- 用户不给任何参考文本 → `FULLY_ORIGINAL`

### 6.5.3 PremiseLock：把这次任务的核心命题锁死

`PremiseLock` 是本次任务的最高约束，高于原作资料召回。

```python
class PremiseLock(BaseModel):
    """本次小说任务的最高约束。"""
    task_mode: TaskMode

    # 这本书真正要讲的命题
    core_premise: str
    # 例: "路明非因白王权能回到高中，这一次他要在日常世界线里主动改命"

    # 前 N 章禁止触碰的原作主线
    forbidden_canon_arcs_before_chapter: dict[int, list[str]] = Field(default_factory=dict)
    # {20: ["古德里安标准招生线", "直接进入卡塞尔学院主线"]}

    # 前 N 章必须优先完成的阶段任务
    required_initial_stage: list[str] = Field(default_factory=list)
    # ["重返日常", "发现世界线偏差", "验证白王权能副作用"]

    # 原作可继承内容
    allowed_canon_material: list[str] = Field(default_factory=list)
    # ["文风", "术语系统", "角色底色", "世界观铁律"]

    # 原作不可直接继承内容
    forbidden_canon_gravity: list[str] = Field(default_factory=list)
    # ["原作出场顺序自动复现", "原作主线最近路径优先"]
```

**原则**：

> 原作资料只能作为素材库，不能自动成为剧情主骨架。

### 6.5.4 StoryBible Rewriter：原作资料进入系统前先“改写”

原始 `StoryBible` 只是抽取出的角色/世界观/伏笔资料。但在 `TaskMode != CANON_REWRITE` 时，需要先经过一个“改写器”，将原作资料压缩成**可继承的素材**。

```python
class StoryBibleRewriter:
    """根据 TaskMode 和 PremiseLock 重写 StoryBible 的权重。"""

    def rewrite(self,
                source_world_profile: WorldProfile,
                source_style_profile: StyleProfile,
                premise_lock: PremiseLock) -> dict:
        """
        返回:
        {
            "active_world_rules": [...],
            "active_characters": [...],
            "delayed_canon_arcs": [...],
            "style_constraints": [...],
            "forbidden_story_paths": [...],
        }
        """
```

#### 重写规则

| 原作资料 | 在 `ORIGINAL_IN_CANON_WORLD` 模式下如何处理 |
|---------|--------------------------------------------|
| 世界观规则 | 保留，作为铁律 |
| 角色底色 | 保留，作为人格约束 |
| 原作主线情节 | 降级为“可参考，不可自动执行” |
| 原作出场顺序 | 禁止自动复现 |
| 原作大反派身份揭露时机 | 只有在 PremiseLock 允许时才可召回 |

### 6.5.5 任务模式示例

#### 模式 A：原作改写

```text
任务: "如果楚子航没有离开高天原，那晚会怎样？"
task_mode = CANON_REWRITE

允许:
- 直接复用原作情节锚点
- 复用原作场景顺序

目标:
- 改写一个关键决策点
```

#### 模式 B：原作世界观下原创长篇

```text
任务: "路明非因白王权能回到高中，写一本新长篇"
task_mode = ORIGINAL_IN_CANON_WORLD

允许:
- 复用龙族世界观
- 复用路明非/楚子航/诺诺的人格底色
- 复用术语和超凡规则

禁止:
- 自动走古德里安招生线
- 自动重演卡塞尔学院主线
- 原作关键情节点按最近路径复现
```

#### 模式 C：只有文风，没有世界观

```text
任务: "模仿江南的文风写一篇现代校园悬疑"
task_mode = STYLE_TRANSFER_ONLY

允许:
- 复用句长/比喻/叙事距离/感官分布

禁止:
- 自动引入龙族、卡塞尔、诺玛等原作元素
```

#### 模式 D：完全原创

```text
任务: "写一个赛博朋克侦探长篇"
task_mode = FULLY_ORIGINAL

允许:
- 仅使用 GenrePreset

禁止:
- 任何参考书的剧情/角色/术语污染
```

### 6.5.6 Premise-first Pipeline（新的优先级）

```
用户任务
  ↓
TaskModeClassifier
  ↓
PremiseLockBuilder
  ↓
StoryBibleRewriter
  ↓
NarrativeState / ChapterPlan / Hot CON
  ↓
LLM 生成
```

注意顺序：

```text
任务意图 > PremiseLock > StoryBible > StyleFingerprint
```

不是：

```text
原作资料 > 用户意图
```

### 6.5.7 与现有架构的关系

`TaskMode / PremiseLock / StoryBibleRewriter` 位于 Planner 和 Narrative Engine 之间：

```
现有:
  Source TXT → Planner → StoryBible → Hot CON → LLM

v1.2:
  Source TXT → Planner
              → TaskModeClassifier
              → PremiseLockBuilder
              → StoryBibleRewriter
              → NarrativeState / ChapterPlan
              → Hot CON
              → LLM
```

这层改动不替代 StyleFingerprint、NovelTagSystem、Guardrail，而是防止“原作情节惯性”在大纲阶段就把任务带偏。

---

## 七、Narrative State 与 Chapter Executor

> **新增（v1.1）**：本章是 E2E 测试暴露的核心缺口——系统有 Style 层和 Story Bible 层，但缺少"故事推进到哪了"的状态机层。本章定义 Narrative State、章节执行器和过渡规则，解决章节重复、场景跳变、角色忽隐忽现等问题。

### 7.1 问题定位：为什么会出现章节重复和场景跳变

经过前 6 章 E2E 测试，暴露了以下现象：

| 现象 | 根因 |
|------|------|
| Ch4/5 开头逐字重复 | LLM 不知道上章已经写过"车厢里的死侍攻击"，从同一 prompt 起笔重新生成 |
| Ch5→6 无过渡跳变 | 上一章结束在"卡塞尔学院大厅"，下一章开头已是"三天后图书馆后面"——没有任何过渡 |
| 角色忽隐忽现 | 楚子航/诺诺在不同章节反复出现又消失，无叙事解释 |
| 章内场景从不推进 | LLM 没有"这章必须完成哪些情节"的约束，所以选择最稳定的保守重复 |

**根本原因**：系统缺少一个显式的"故事现在在哪"的状态机，以及"这章必须做什么"的执行器。

当前系统分层：

```
✅ Style Layer（怎么写）— 句长、对话占比、比喻密度
✅ Story Bible Layer（世界里有什么）— 角色档案、世界观规则、伏笔台账
❌ Narrative State Layer（此刻推进到哪）— 缺失
❌ Chapter Executor Layer（这章何时算完成）— 缺失
```

### 7.2 NarrativeState：故事推进状态机

`NarrativeState` 是跨章节的故事状态的单一来源。每章生成后更新，下章生成前注入。

```python
class NarrativeState(BaseModel):
    """跨章节的故事推进状态——每章写回，下章注入。"""

    # 当前进度
    current_chapter: int
    current_volume: int

    # 上一章结尾状态（下章开头的起点）
    ending_location: str = ""           # "卡塞尔学院大厅"
    ending_characters: list[str] = Field(default_factory=list)  # ["路明非", "楚子航"]
    ending_emotional_tone: str = ""     # "紧张，刚刚觉醒权能"
    ending_hook: str = ""               # "全息投影突然亮起"
    ending_unresolved: str = ""         # "老唐留下后离开，路明非独自面对入学"

    # 本章必须完成的情节 beats
    required_beats: list[str] = Field(default_factory=list)
    # ["建立卡塞尔学院第一印象", "路明非接触至少一个新角色", "本章结尾得到下一条线索"]

    # 可选 beats
    optional_beats: list[str] = Field(default_factory=list)

    # 本章约束
    must_appear_characters: list[str] = Field(default_factory=list)  # 必须出场的角色
    must_not_kill: list[str] = Field(default_factory=list)           # 不能死的角色
    max_time_skip: str = "same_day"      # 允许的时间跨度: same_day | next_day | days(N) | free

    # 场景约束
    allowed_locations: list[str] = Field(default_factory=list)  # 允许切换到的地点
    forbidden_transitions: list[str] = Field(default_factory=list)  # 禁止的跳变

    # 伏笔调度
    foreshadow_hints_due: list[str] = Field(default_factory=list)   # 本章必须 hint 的伏笔 ID
    foreshadow_resolve_due: list[str] = Field(default_factory=list) # 本章应回收的伏笔 ID
```

### 7.3 ChapterPlan：本章必须完成什么

`ChapterPlan` 从大纲派生，由 Planner 生成或用户指定。不是"这章大概写什么"的模糊描述，而是"这章必须完成哪些 beats"的硬约束。

```python
class ChapterPlan(BaseModel):
    """单章执行计划——硬约束，不是模糊描述。"""
    chapter: int
    title: str
    summary: str                         # 1-2 句话概要

    # 硬约束：不完成不能收章
    required_beats: list[str] = Field(default_factory=list)
    # 例: [
    #   "路明非进入卡塞尔学院大厅",
    #   "至少出现一个新角色并完成互动",
    #   "本章结尾获得关于'白王回归'的第一条线索"
    # ]

    # 本章角色
    viewpoint_character: str = ""        # 主视角角色
    must_appear: list[str] = Field(default_factory=list)

    # 本章场景
    primary_location: str = ""
    allowed_locations: list[str] = Field(default_factory=list)

    # 与前后章的关系
    starts_from: str = ""                # "上一章结尾：全息投影亮起"
    must_end_with: str = ""              # "路明非发现XX线索"
    max_time_span: str = "same_day"      # same_day | next_day | days(N)

    # 完成判定
    completion_criteria: str = ""        # "all_required_beats_done"
```

### 7.4 ChapterCompletionJudge：本章何时算完成

生成后自动判定，不依赖 LLM 自觉。

```python
class ChapterCompletionJudge:
    """自动判定章节是否完成——不依赖 LLM 自觉。"""

    def judge(self, content: str, plan: ChapterPlan,
              prev_state: NarrativeState | None = None) -> dict:
        """
        返回:
        {
            "completed": bool,
            "beats_done": [...],       # 已完成的 beats
            "beats_missing": [...],     # 未完成的 beats
            "transition_valid": bool,   # 场景过渡是否合法
            "issues": [...],            # 问题列表
            "should_rewrite": bool,     # 是否需要重写
        }
        """
```

**判定规则（v1 heuristics）**：

| 规则 | 检查方法 |
|------|---------|
| 字数达标 | `len(content) >= 2000` |
| 场景未重复上章开头 | 前 50 字与上一章前 50 字相似度 < 0.7 |
| 角色硬约束 | `must_appear` 中每个名字都出现在 text 中 |
| 地点过渡合法 | 新地点在 `allowed_locations` 中，或存在过渡标记（"第二天"/"来到"/"走向"） |
| 时间跨度合法 | 有过渡文本，且不超过 `max_time_span` |
| 章末有钩子 | 最后 200 字包含？/……/——或明显悬念句式 |

### 7.5 TransitionRule：场景过渡合法性

防止"上一章在火车站，下一章突然在图书馆蹲三天"。

```python
class TransitionRule:
    """场景过渡规则——防止无解释跳变。"""

    # 硬规则：以下模式必须包含过渡文本
    LOCATION_CHANGE = "location_change"       # 地点变化 → 需要"走向XX"
    TIME_SKIP = "time_skip"                   # 时间跳跃 → 需要"第二天/三天后"
    CHARACTER_ENTER = "character_enter"       # 新角色登场 → 需要引入
    CHARACTER_EXIT = "character_exit"         # 角色退场 → 需要交代
    CONFLICT_RESOLVE = "conflict_resolve"     # 冲突解决 → 需要明确结果

    def validate(self, from_state: NarrativeState,
                 to_content: str) -> list[str]:
        """验证过渡是否合法。返回问题列表。"""

    def generate_hint(self, from_state: NarrativeState,
                      target_location: str) -> str:
        """生成过渡提示文本，注入 prompt。"""
```

### 7.6 ForeshadowScheduler：主动伏笔调度

将伏笔从"被动账本"升级为"主动调度器"。

```python
class ForeshadowScheduler:
    """伏笔主动调度——不只是记账，而是决定本章该处理哪条。"""

    def schedule(self, current_chapter: int,
                 ledger: list[ForeshadowEntry]) -> dict:
        """
        返回:
        {
            "must_hint": [...],     # 本章必须暗示的伏笔
            "should_hint": [...],   # 建议暗示的伏笔
            "must_resolve": [...],  # 本章必须回收的伏笔
            "expiring_soon": [...], # 即将到期的伏笔警告
            "can_ignore": [...],    # 本章可忽略的伏笔
        }
        """
```

**调度规则**：

| 条件 | 动作 | 优先级 |
|------|------|--------|
| planted 超过 25 章未 hinted | 提升到 `must_hint` | 高 |
| hinted 超过 40 章未 resolved | 提升到 `must_resolve` | 最高 |
| 当前章在伏笔的 `planted_chapter + 5` 范围内 | `should_hint` | 中 |
| 当前章 >= 伏笔预设的 `planned_resolve_chapter` | `must_resolve` | 高 |

### 7.7 完整写作循环（v1.1 修正版）

```
Pre-writing（筹备）
  ├── 世界观设定
  ├── 角色创建
  ├── 大纲设计 → 生成 ChapterPlan 列表（每章含 required_beats）
  ├── 文风定调 → StyleFingerprint
  └── 初始 NarrativeState（chapter=1, location=起点, required_beats=[...])

Writing 循环（逐章）:
  1. ForeshadowScheduler.schedule(chapter) → 本章伏笔清单
  2. NovelHotCONAssembler.assemble()
     ├── P0: 上章 NarrativeState.ending_* + 本章 ChapterPlan + StyleFingerprint
     ├── P1: 伏笔调度结果 + 近期角色状态
     └── P2: 核心世界观规则 + 角色弧线
  3. LLM 生成文本
  4. ChapterCompletionJudge.judge() → beats 是否完成？过渡是否合法？
     ├── 未完成 → 注入"还没写完，继续"的 nudge → 回到步骤 3
     └── 完成 → 继续
  5. NovelGuardrail.check()
  6. NovelSelfReview.review()
  7. NovelMemoryWriteback.write()
     ├── 更新 NarrativeState（从生成文本提取 ending_* 字段）
     ├── 更新 ChapterSummary（结构化 key_events, location, next_hook）
     ├── 更新 ForeshadowEntry（新增/回收）
     └── 更新 CharacterProfile.current_state
  8. chapter += 1 → 回到步骤 1
```

### 7.8 与现有架构的关系

`NarrativeState` 不替代任何现有模块，而是在现有模块之间插入一层状态机：

```
现有:  StyleFingerprint → Hot CON → LLM → Guardrail → SelfReview → Writeback
新增:                    ↑                           ↑
              NarrativeState 注入              NarrativeState 写回
                    ↑                           ↑
              ChapterPlan.beats          ChapterCompletionJudge
```

现有模块（StyleFingerprint、NovelTagSystem、Guardrail、SelfReview）全部保持不变。新增层只负责"推进状态"这一个职责。

---

## 八、数据结构

### 8.1 角色档案

```python
class CharacterProfile:
    name: str                          # 角色名
    aliases: list[str]                 # 别名/绰号
    role: Literal["protagonist", "antagonist", "supporting", "minor", "cameo"]

    # 性格
    traits: dict[str, float]           # {"勇敢": 0.8, "冲动": 0.7, "善良": 0.9}
    mbti_hint: str                     # 性格类型提示（非精确MBTI，辅助建模）
    core_desire: str                   # 核心欲望
    core_fear: str                     # 核心恐惧
    flaw: str                          # 致命缺陷

    # 背景
    background: str                    # 背景故事（500字内）
    trauma: str                        # 创伤事件
    secret: str                        # 秘密

    # 关系
    relationships: dict[str, Relationship]  # {角色名: Relationship}

    # 语言指纹
    voice: CharacterVoice
    #   vocabulary_level: float         # 词汇复杂度
    #   sentence_length_pref: float     # 句长偏好
    #   filler_words: list[str]         # 口头禅
    #   formality: float                # 正式度
    #   speech_patterns: list[str]      # 标志性说话方式（"总把'不是'说成'不似'"）
    #   dialogue_examples: list[str]    # 代表性对话片段（few-shot锚点）

    # 蜕变弧线
    arc: CharacterArc
    #   starting_state: str             # 初始状态
    #   ending_state: str               # 目标状态
    #   key_milestones: list[ArcMilestone]  # 关键节点
    #   current_progress: float         # 当前进度 0-1

    # 当前状态
    current_state: CharacterState
    #   location: str                   # 当前位置
    #   with_characters: list[str]      # 与谁在一起
    #   emotional_state: str            # 当前情绪
    #   physical_state: str             # 身体状况
    #   active_goals: list[str]         # 当前目标
    #   last_appeared_chapter: int      # 最后出场章节

    # 元信息
    created_at_chapter: int
    updated_at_chapter: int
    is_active: bool                    # 是否仍在故事中活跃
```

### 8.2 伏笔台账条目

```python
class ForeshadowEntry:
    id: str                            # 唯一 ID
    description: str                   # 伏笔内容描述
    status: ForeshadowStatus           # planted | hinted | resolved | abandoned
    planted_chapter: int               # 首次埋下章节
    hinted_chapter: int | None         # 暗示章节
    resolved_chapter: int | None       # 回收章节
    abandoned_chapter: int | None      # 弃用章节
    importance: float                  # 重要性 0-1
    related_characters: list[str]      # 关联角色
    resolution_detail: str | None      # 回收方式描述
    hints: list[ForeshadowHint]        # 每次提及记录
    #   chapter: int
    #   content: str                   # 提及的具体文本
    #   hint_level: float              # 暗示明显度 0-1
```

### 8.3 世界观规则

```python
class WorldRule:
    id: str
    category: Literal["magic", "technology", "society", "geography", "history", "creature", "economy", "custom"]
    description: str                   # 规则描述
    rigidity: float                    # 刚性 0-1（1=不可破的铁律）
    exceptions: list[str]              # 已知例外
    established_chapter: int           # 确立章节
    used_in_chapters: list[int]        # 被使用/引用的章节
    importance: float                  # 重要度 0-1
```

### 8.4 章节摘要

```python
class ChapterSummary:
    chapter: int
    volume: int
    title: str
    summary: str                       # 500-800字摘要
    key_events: list[str]              # 关键事件列表
    characters_appeared: list[str]     # 出场角色
    locations: list[str]               # 场景地点
    foreshadows_planted: list[str]     # 本章埋下的伏笔 ID
    foreshadows_resolved: list[str]    # 本章回收的伏笔 ID
    emotional_arc_point: float         # 本章情绪曲线位置
    cliffhanger: bool                  # 是否有悬念结尾
    word_count: int                    # 字数
    compacted_at: str                  # ISO 时间戳
```

---

## 九、API 设计

### 9.1 风格指纹提取

```
POST /api/writer/novel/style/extract
  Body:
    text: str                          # 用户提供的文本样本（单卷/全书TXT）
    volume: int                        # 卷号
    sample_chapters: list[int]         # 采样章节列表
    extract_layers: list[str]          # ["pystylometry", "llm", "styledistance"]
  Response:
    fingerprint: StyleFingerprint      # 完整指纹
    layer1_stats: LexicalProfile       # Layer1 纯统计
    extraction_duration_ms: int
    confidence: float
```

### 9.2 风格漂移检测

```
POST /api/writer/novel/style/check-drift
  Body:
    generated_text: str                # 新生成的章节文本
    baseline_fingerprint_id: str       # 基准指纹 ID
    volume: int
    chapter: int
  Response:
    drift_score: float                 # 风格距离 0-1
    exceeded: bool                     # 是否超过阈值
    deviated_dimensions: list[{
      dimension: str,                  # 偏差维度（如 "avg_sentence_length"）
      expected: float,
      actual: float,
      deviation_pct: float
    }]
    recommendation: str                # 建议（如 "句长偏短 30%，建议适当扩展"）
```

### 9.3 伏笔台账查询

```
GET /api/writer/novel/foreshadows?status=planted&before_chapter=12
  Response:
    foreshadows: list[ForeshadowEntry]
    expiring: list[ForeshadowEntry]    # 即将到期（hinted 超过阈值）
    stats: {
      total: int,
      planted: int,
      hinted: int,
      resolved: int,
      abandoned: int,
      resolution_rate: float           # 回收率
    }
```

### 9.4 连续性检查

```
POST /api/writer/novel/check-continuity
  Body:
    text: str                          # 要检查的文本
    chapter: int
    volume: int
    check_types: list[str]             # ["character", "world_rule", "foreshadow", "style"]
  Response:
    passed: bool
    issues: list[{
      type: str,
      severity: "error" | "warning" | "suggestion",
      location: str,                   # 文本位置
      description: str,
      suggestion: str
    }]
    summary: str                       # 检查报告摘要
```

---

## 十、与 Writer 架构的一致性

### 10.1 PER 遵循

小说写作子功能不改变 Writer 的 PER。Writer 就是 Writer——极简匠人，做代码也一样，做小说也一样。不因为小说创作就变得文艺冗长。

```
# Writer PER（不变）
"你是 LamWriter。24岁。匠人。代码和文字都做。
极简。能用两个字不用一句话。能用代码不用解释。
凌晨改了你随口提的伏笔，注释'顺手'。"
```

### 10.2 CON 扩展

小说子功能在 Writer 现有 CON 基础上新增 Cold CON 索引（NovelColdCONIndex），不解耦或替代现有索引。WriterAdapter 扩展为 NovelWriterAdapter，新增 `recall_for_prose_task()` 分支。

### 10.3 Prompt 组装线

遵循 PER → Skill → Hot CON 的五层注入顺序。小说场景的 Hot CON 分 P0/P1/P2 三级，但最终仍注入 Hot CON 段，不改变 PromptAssembler 的架构。

### 10.4 while(true) loop 复用

小说写作复用 Writer 的 while(true) loop。区别在于：
- loop 出口条件不变（LLM 纯文本回复无 tool call = done）
- 新增 NovelGuardrail 作为 loop 内 check 点
- 新增 NovelMemoryWriteback 作为 loop 后的写回逻辑

### 10.5 Guardrail 扩展

Writer 现有 Guardrail 处理 `modify_intent_missing_reference_image` 等图像场景错误模式。NovelGuardrail 新增四层检查：

1. **CharacterConsistencyChecker**：角色言行是否与 CharacterProfile 一致
2. **WorldRuleValidator**：是否违反已确立的世界观规则
3. **ForeshadowingTracker**：伏笔是否正确提及/回收
4. **StyleDriftDetector**：风格漂移是否超过阈值

### 10.6 工具扩展

Writer 现有 22 个工具，小说子功能**不新增用户可见工具**。所有小说专用能力通过 Guardrail/SelfReview/MemoryWriteback 在后台运行。

---

## 十一、局限性

### 11.1 文风指纹的精度边界

- **统计数据 ≠ 文风**：pystylometry 能算出平均句长，但算不出"这句话有没有才华"。文风的"神韵"部分无法量化。
- **采样偏差**：用户提供的参考文本如果只是前半本书，后半本书的风格演化无法捕捉。
- **跨语言限制**：pystylometry 主要面向英文，中文的句法分析精度偏低。中文场景需要替换为 jieba + 自定义分词统计。
- **STYLEDISTANCE 中文支持**：需要验证预训练模型对中文的嵌入质量。

### 11.2 伏笔状态机的覆盖缺口

- **隐晦伏笔**：作者自己都不确定是不是伏笔的"可能伏笔"，状态机无法处理。
- **跨书伏笔**：三部曲之间的伏笔跨越不同 Cold CON 索引，v1 不支持。
- **读者感知伏笔**：某些段落中"读者以为是伏笔但作者没那个意思"，状态机无法区分作者意图 vs 读者解读。

### 11.3 LLM 依赖风险

- **Layer 2 LLM 合成指纹的不可复现性**：同一文本两次提取可能得到不同的 RhetoricalProfile。缓解：锁定 temperature=0。
- **连续性自审的误报**：LLM 可能把"有意的风格突破"误判为"风格漂移"。缓解：Guardrail 只告警不强制修改，最终决定权在作者。
- **Token 消耗**：P0/P1/P2 三级注入 + 锚点段落 + 伏笔台账，单次 prompt 可能超过 12000 token。缓解：按预算裁剪 + compaction 策略。

### 11.4 pystylometry 中文适配

pystylometry 的 11 个模块中有部分依赖英文 NLP（如 syllable count、Gunning Fog index），中文场景下需要替换：

| 原模块 | 中文替代 |
|--------|---------|
| 词长统计（字符级） | 直接可用（中文按字统计） |
| 句长统计 | 直接可用 |
| 音节统计 | 需替换为声调/笔画统计 |
| 易读性指数（Gunning Fog） | 需替换为中文易读性公式（如小波指数） |
| 词性标注（POS tagging） | 需替换为 jieba.posseg 或 HanLP |
| 词汇丰富度（TTR） | 直接可用 |

---

## 十二、演进路线

### 12.1 v1.0（MVP，实现即可用）

| 功能 | 范围 |
|------|------|
| StyleFingerprint 提取 | Layer 1 pystylometry（中文适配版） + Layer 2 LLM 合成 |
| 风格漂移检测 | 基于 Layer 1 统计的简单阈值告警（不引入 STYLEDISTANCE） |
| 伏笔状态机 | planted → hinted → resolved，30章/50章到期提醒 |
| NovelTagSystem | 7 种实体标签 + 状态字段 |
| Hot CON P0 注入 | 上一章摘要 + 当前大纲 + 角色 + 世界观 |
| NovelGuardrail | 角色检查 + 世界观检查（LLM 兜底） |
| 章节摘要自动生成 | 每章写完后 LLM 生成 500 字结构化摘要 |

### 12.2 v1.5（精度提升）

| 功能 | 范围 |
|------|------|
| Layer 3 STYLEDISTANCE | 引入风格嵌入漂移检测 |
| Hot CON P1/P2 注入 | 窗口注入 + 关联注入 |
| 角色弧线追踪 | CharacterArc 进度可视化 |
| 情绪节奏曲线 | 全卷 tension 向量 + 高潮间隔检测 |
| NovelSelfReview | 自动化文本自审 |

### 12.3 v2.0（完整闭环）

| 功能 | 范围 |
|------|------|
| 按卷风格演化分析 | StyleTimeline 可视化 |
| 伏笔回收率仪表盘 | 统计视图 |
| 全文一致性遍历 | 批量检查工具 |
| 角色关系图谱 | 交互式可视化 |
| 文风"松弛度"调节 | 用户可以通过滑块调整句长/定语密度/对话占比等参数 |
| 与 Artist 协作 | 场景插图自动请求 |

---

## 十三、竞品参考

### 13.1 已分析的开源项目

| 项目 | 关键发现 | 复用价值 |
|------|---------|---------|
| **PlotPilot** (`shenminglinyi/PlotPilot`) | 中文 AI 小说写作最完整实现。FastAPI + SQLite + FAISS + Vue3，DDD 四层架构。有 style_fingerprint 节点、伏笔台账、声音漂移检测、章后管线 | 架构参考价值高，style_fingerprint 节点设计可借鉴 |
| **stylometric-transfer** (`ngpepin/stylometric-transfer`) | "本地计算 + LLM 合成"两阶段方案，与我们三层混合架构高度吻合 | 两阶段方法论直接对位 Layer1+Layer2 |
| **pystylometry** (`craigtrim/pystylometry`) | 50+ 指标 / 11 模块文体测量库，MIT 许可 | Layer 1 本地测量工具首选（需中文适配） |
| **STYLEDISTANCE** (HuggingFace) | 开源风格嵌入模型，可用于漂移检测 | Layer 3 漂移检测引擎 |
| **fiction-forge** (`geobond13/fiction-forge`) | 24 种 AI 写作痕迹检测 + MCP 上下文服务器 | NovelGuardrail 参考 |
| **novel-creator-skill** | style_fingerprint.py 提取算法 + novel_flow_executor.py 集成 + 全局风格库索引 | 实现细节参考 |
| **groundup-toolkit** | LLM-based style extraction prompt + 输出 JSON schema + samples.json 存储 | Prompt 模板参考 |

### 13.2 商业产品参考

| 产品 | 关键功能 | 借鉴点 |
|------|---------|--------|
| **Sudowrite Muse** | Style Examples（最多 1000 字原文样本作为风格锚点） | 锚点段落的商业验证 |
| **StyleVector (ACL 2025)** | 对比激活分析提取风格向量 | 风格嵌入方案 |
| **NovelAI** | 文风 slider 调节 | v2.0 风格松弛度调节 |

---

## 十四、附录：中文网文特有考虑

### 14.1 网文 vs 传统文学的风格差异

网文创作有一些传统文学不具备的特殊维度：

| 维度 | 传统文学 | 网文 |
|------|---------|------|
| 更新频率 | 无固定频率 | 日更/周更，稳定更新本身就是质量指标 |
| 章节结构 | 自然章节 | "章末钩子"（cliffhanger）几乎每章必须 |
| 节奏要求 | 有起有伏 | "爽点密度"（每 N 章必须有一个满足点） |
| 对话占比 | 视风格而定 | 通常更高（60%+），因为对话推进节奏快 |
| 世界观规模 | 自然扩展 | "换地图"（更换场景 = 全新世界观子系统），对一致性要求极高 |

### 14.2 网文特有记忆维度

在六大记忆维度之外，网文场景还需额外追踪：

- **爽点密度**：每 X 章需要有一个读者满足点（打脸/升级/揭秘/收获），节奏塌了读者会掉
- **章末钩子质量**：上章结尾的悬念是否在下一章前 500 字内被兑现？
- **等级体系一致性**：网文的等级/功法/境界体系一旦确立，不能前后矛盾（类似 RPG 游戏数值设计）
- **水字数检测**：网文有一个独有的负面评价叫"注水"，即无情节推进的纯填充内容占比过高

---

## 文档版本

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.0 | 2026-05-25 | 初稿：创作流程拆解、文风指纹体系、CON 标签体系、伏笔状态机、记忆分层、三层混合架构、API 设计、与 Writer 集成 |
