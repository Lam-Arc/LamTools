# Novel Writing Engine v2 — 实施计划

> 目标：把当前“文风模仿器 + 设定资料库”升级为“可稳定推进长篇的叙事引擎”。
>
> 范围：TaskMode / PremiseLock / StoryBible Rewriter / NarrativeState / ChapterExecutor / TransitionRule / ForeshadowScheduler。

---

## 一、目标与验收

### 目标

解决当前 E2E 暴露出的三类问题：

1. **原作重力过强**：系统把“原创长篇”写成“原作主线变体”
2. **章节推进失控**：逐字重复开头、场景硬跳切、角色忽隐忽现
3. **信息释放失控**：每章都像第一章、每章都在开新坑

### 验收标准

| 维度 | 标准 |
|------|------|
| TaskMode | 能区分 `canon_rewrite / canon_side_story / original_in_canon_world / style_transfer_only / fully_original` |
| PremiseLock | 可以禁止前 N 章触碰原作主线 |
| ChapterPlan | 每章有非空 `summary` + `required_beats` + `forbidden_beats` |
| NarrativeState | 每章写回 `ending_location / ending_characters / ending_hook` |
| Transition | 5 章测试中不再出现逐字重复开头；跨地点/跨时间存在显式过渡 |
| E2E | 5 章验证通过，人工评审认为“连续可读，不再像拼接文本” |

---

## 二、分阶段实施

### Phase 1：TaskMode 与 PremiseLock

#### 目标
先判断任务到底是“重写原作”还是“原创长篇”，再决定资料如何使用。

#### 任务

1. `backend/app/core/writer/novel/task_mode.py`
   - 定义 `TaskMode` 枚举
   - 提供 `classify_task_mode(user_request, source_profile)`

2. `backend/app/core/writer/novel/premise_lock.py`
   - 定义 `PremiseLock`
   - 提供 `build_premise_lock(task_mode, user_request)`

3. `planner.py`
   - Planner 输出 `task_mode`
   - Planner 输出 `premise_lock`

#### 验收
- 单元测试：不同用户请求得到不同 mode
- 示例："白王回归高中" 被判为 `original_in_canon_world`

---

### Phase 2：StoryBible Rewriter

#### 目标
把原作资料从“剧情骨架”降级为“素材库”。

#### 任务

1. `backend/app/core/writer/novel/story_bible.py`
   - 统一 `WorldProfile / StyleProfile / CharacterProfile / CanonFacts`

2. `backend/app/core/writer/novel/story_bible_rewriter.py`
   - 根据 `premise_lock` 过滤可用原作锚点
   - 生成：
     - `active_world_rules`
     - `active_characters`
     - `forbidden_story_paths`
     - `delayed_canon_arcs`

#### 验收
- 测试：当 mode = `original_in_canon_world` 时，前 20 章禁止自动落入“古德里安招生线”

---

### Phase 3：NarrativeState + ChapterPlan 真正接入链路

#### 目标
让“当前故事推进到哪了”成为生成入口，而不是只靠上一章截断文本。

#### 任务

1. `schemas.py`
   - 已有 `NarrativeState / ChapterPlan`，补必要字段如果缺失

2. `planner.py`
   - 生成前 10 章完整 `ChapterPlan`
   - 每章包含：
     - `chapter_function`
     - `required_beats`
     - `forbidden_beats`
     - `viewpoint_character`
     - `must_end_with`

3. `run_novel_e2e.py` / 未来 runtime 集成
   - 用 `ChapterPlan` 驱动 prompt，而不是只用 summary

#### 验收
- 每章 prompt 中含 required beats
- 5 章样章明显呈现章节功能差异

---

### Phase 4：Transition Engine

#### 目标
把“上一章在哪里结束、这一章怎么接”做成显式规则。

#### 任务

1. `backend/app/core/writer/novel/transition_engine.py`
   - `validate(from_state, to_content)`
   - `generate_hint(from_state, chapter_plan)`

2. 规则覆盖：
   - 地点变化
   - 时间跳跃
   - POV 切换
   - 角色入场/退场

#### 验收
- 5 章验证：Ch2→3、Ch3→4 有显式过渡
- 不再出现“大厅 → 三天后图书馆后面”这种无桥接跳变

---

### Phase 5：ForeshadowScheduler

#### 目标
让伏笔从“记账本”变成“导演排期器”。

#### 任务

1. `backend/app/core/writer/novel/foreshadow_scheduler.py`
   - 计算 `must_hint / should_hint / must_resolve / expiring_soon`

2. Hot CON 注入
   - P1 / P2 不再只是“所有 pending 伏笔”
   - 而是“本章该处理的伏笔”

#### 验收
- 生成的 prompt 中有本章必须处理的伏笔清单
- 20 章测试中，至少有 planted→hinted 的推进

---

### Phase 6：ChapterCompletionJudge

#### 目标
让系统知道一章什么时候算写完，而不是“模型停了就算完”。

#### 任务

1. `backend/app/core/writer/novel/chapter_executor.py`
   - `ChapterCompletionJudge.judge(content, plan, prev_state)`
   - 检查：
     - required beats 是否完成
     - transition 是否合法
     - 字数是否达标
     - 本章是否有钩子

2. 若未完成：
   - 自动生成 continuation nudge
   - 再续写一轮

#### 验收
- 单章不会因为只写了一半就提前收章
- 不再出现“每章都像第一章”的不完整感

---

## 三、测试计划

### 单元测试

新增测试文件：

- `test_task_mode.py`
- `test_premise_lock.py`
- `test_story_bible_rewriter.py`
- `test_transition_engine.py`
- `test_foreshadow_scheduler.py`
- `test_chapter_executor.py`

### 集成测试

更新：

- `tests/run_novel_e2e.py`
  - 使用新的 `TaskMode / PremiseLock / ChapterPlan / NarrativeState`

### 人工评审标准

重点审 5 章：

1. 开头是否重复
2. 场景是否硬跳切
3. 原作主线是否过早侵入
4. 是否像“原创长篇”而非“原作重写”
5. 每章是否有不同的功能和推进

---

## 四、风险与应对

| 风险 | 说明 | 应对 |
|------|------|------|
| LLM 仍被原作锚点拖回主线 | 即使有 PremiseLock 也可能被龙族语料吸回去 | 在 prompt 中显式列出 `forbidden_story_paths` |
| required_beats 太硬，文本变僵 | 写成 checklist prose | 增加 optional beats，保留创作弹性 |
| Transition 规则太多导致写作迟滞 | 每章都在解释移动 | 限制只管时间/地点/POV 三类关键跳变 |
| ForeshadowScheduler 过强导致剧情僵硬 | 每章都像在对账 | 用 must/should 两级优先级 |

---

## 五、最小落地顺序（推荐）

如果要最快止损，推荐顺序：

1. TaskMode + PremiseLock
2. StoryBible Rewriter
3. ChapterPlan.required_beats
4. NarrativeState ending_state
5. Transition Engine
6. Foreshadow Scheduler
7. ChapterCompletionJudge

这个顺序可以先把“重写原作”拉回“原创长篇”，再逐步修连续性和完成度。

---

## 六、完成标准

此计划完成时，应满足：

- 前 5 章不再出现明显重复开头
- 前 5 章具备可读的因果承接
- “白王回归高中”不会被自动改写成“古德里安招生线重演”
- 系统能够区分“原作重写”与“原作世界观下原创长篇”
- 文档与实现保持一致，可继续扩展到 50 章 / 200 章稳定生成
