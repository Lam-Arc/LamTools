# Novel Writing Engine v2.1 — 整改设计文档

> 版本: v2.1 / 2026-05-28
> 定位: 把当前"线性 prompt 注入管线"升级为"预校验+生成+抽取+状态更新+再校验"闭环引擎
> 范围: 不改 StyleFingerprint/NovelTagSystem/VolumeActPlanner骨架/RealityState概念,只补三道检查站和一个状态抽取层

---

## 一、当前架构 vs 目标架构

### 当前(线性管线)

StyleFingerprint → ChapterPlan → Hot CON → RealityState → prompt → LLM → process_chapter

问题: ChapterPlan不校验 / 生成文本不扫描 / 状态不抽取 / 信息不预算。LLM训练记忆从任何空隙渗透。

### 目标(闭环引擎)

ChapterPlan → PreGate → LLM → PostGate → StateExtractor → NarrativeState → 下一章

每章经过: 预校验(计划是否合法) → 生成 → 后校验(事实是否一致) → 状态抽取(文本变结构化事实) → 状态写回。

---

## 二、整改项

### 整改1: PreGate — 生成前校验

**现状**: ConstraintValidator已实现但未接入。build_chapter_prompt()直接从ChapterPlan拼prompt。

**目标**: LLM落笔之前先判定ChapterPlan是否合法。检查项:
- 所有must_appear角色的地点可达性
- required_beats文本中出现的所有已知角色名
- 信息预算超限
- 禁止事件清单命中
- 时间线阶段约束

如果passed=False,不生成正文,注入修正提示回退到ChapterPlan修正(最多3轮)。

**文件变更**: constraint_validator.py扩展为pregate_check() / run_novel_e2e.py调用位置 / 新增test_pregate.py

### 整改2: StateExtractor — 生成后状态抽取

**现状**: memory_writeback只提取了ending_location + ending_characters。没有抽取本章建立了哪些新事实。

**目标**: 从生成文本抽取结构化StateDelta:
- new_facts: 本章建立的新事实
- character_updates: 角色位置/知识/关系变化
- location_changes: 地点迁移记录
- knowledge_boundary_breaches: 知识边界被突破的记录
- 新增/丢失物品

StateDelta以增量追加到NarrativeState。下一章prompt可看到上一章建立了哪些新事实。

**为什么最重要**: 当前Ch2的prompt只有Ch1结尾200字。LLM不知道Ch1发生了什么。有了StateDelta,Ch2看到的事实成为硬约束。

**文件变更**: 新增state_extractor.py / schemas.py加StateDelta / memory_writeback调用 / run_novel_e2e注入

### 整改3: PostGate — 生成后校验

**现状**: process_chapter做了drift/guardrail/self_review但没做事实一致性校验。

**目标**: 硬检查(不通过则拒绝): 角色地点违规 / 时间线冲突 / 知识边界突破。软告警(通过但标记): 信息密度超标 / 角色名未被canon覆盖。

硬检查非空时尝试自动修复(最多3轮),失败标记needs_review。

**文件变更**: constraint_validator.py加PostGate类 / run_novel_e2e调用 / 新增test_postgate.py

### 整改4: InfoBudget — 信息预算控制

**现状**: 不存在。LLM可自由释放全部龙族剧情。

**目标**: 每章限制新信息点数量。预算随章节递增:
- Ch1-5: 新角色≤2, 新地点≤1, 揭示≤1, 未来事件≤2
- Ch6-15: 新角色≤3, 新地点≤2, 揭示≤2, 未来事件≤3
- Ch16-30: 逐步放宽
- Ch31+: 自由(故事已确立)

ChapterPlan新增: max_reveal_count / allowed_future_events / forbidden_future_events

**文件变更**: 新增info_budget.py / schemas.py加字段 / run_novel_e2e注入

### 整改5: WikiEnricher补全

补全卡塞尔学院入学时期(Ch1-12)的时间线/角色出场顺序/知识边界数据:
- should_appear角色列表
- appears_later角色及出场章节
- never_appears_here角色(仕兰中学角色)
- 每个角色的knowledge_state(knows/hides)

**文件变更**: wiki_enricher.py补全DRAGON_CLAN_VERIFIED_FACTS

---

## 三、实施路线

### 阶段A(核心闭环)
1. PreGate接入build_chapter_prompt()
2. StateExtractor实现并写入NarrativeState
3. PostGate接入process_chapter()
验收: 5章不再出现训练记忆泄露(陈雯雯/婶婶/楚子航黑框眼镜)

### 阶段B(质量加固)
1. InfoBudget实现
2. WikiEnricher补全
3. DeviationLedger全面激活(区分根因vs级联)
验收: 前5章信息点数受控,偏差台账完整

### 阶段C(系统化)
1. StateExtractor升级为LLM-based
2. ChapterPlan修正循环自动化
3. 知识图谱后端(SQLite)替代JSON存储

---

## 四、不改的部分

以下模块正确且不需要修改: StyleFingerprint三层提取 / NovelTagSystem+ForeshadowingStateMachine / VolumeActPlanner骨架 / RealityState概念 / HotCONAssembler的P0/P1/P2 / NovelGuardrail+NovelSelfReview / NovelMemoryWriteback文件落地

这些层需要被挂在正确位置(PreGate前/PostGate后),不需要重写。

---

## 五、风险

PreGate过严导致大量章节被拒: 初始阈值宽松+自动修正提示而非直接拒绝
StateExtractor不可靠: 先用确定性规则(角色名匹配/地点关键词),LLM作为增强
InfoBudget限制导致空洞: 预算随章节递增,required_beats随预算同步增长
新增检查增加耗时: PreGate/PostGate与主生成流程可并行
