# P2 Task 8: Agent 自主 Skill 选择

> **For agentic workers:** Use executing-plans to implement this plan.

**Goal:** Agent 根据 intent（task_type + user_goal + items）自动匹配已有 skill，不再依赖用户手动选择。Skill 创建仍由用户控制。

**Architecture:** 在 intent_node 和 skill_node 之间插入 `skill_matcher_node`（纯规则，不调 LLM）。读取 intent + 所有 skill，用 keyword overlap + strategy_hint 匹配计算分数，择优激活。

**Tech Stack:** Python 3.14+, LangGraph, SQLAlchemy async

---

## Task 8.1: 实现 skill_matcher_node

**Files:**
- 新增 `backend/app/core/agent/nodes/skill_matcher_node.py`
- 修改 `backend/app/core/agent/graph.py`

**Steps:**
- [ ] 1. 新建 `nodes/skill_matcher_node.py` — `async def skill_matcher_node(state, config) -> dict`：
  ```python
  async def skill_matcher_node(state: AgentState, config: RunnableConfig) -> dict:
      conf = config.get("configurable", {})
      db = conf.get("db")
      intent = state.get("intent", {})
      user_skill_ids = state.get("skill_ids", []) or []

      task_type = intent.get("task_type", "single")
      user_goal = intent.get("user_goal", "")
      items = intent.get("items", [])

      if not db:
          return {"skill_ids": user_skill_ids}

      from sqlalchemy import select
      from app.models.skill import Skill
      result = await db.execute(select(Skill).where(Skill.is_active == True))
      skills = result.scalars().all()

      # Compute match score for each skill
      scored: list[tuple[int, str, float]] = []
      intent_text = f"{user_goal} {' '.join(i.get('label', '') for i in items)}".lower()

      for skill in skills:
          skill_text = f"{skill.name or ''} {skill.description or ''}".lower()
          score = _match_score(intent_text, skill_text, task_type, skill.parameters or {})

          if score >= 0.3:
              scored.append((score, skill.id))

      # Sort by score descending, take top 3
      scored.sort(reverse=True)
      matched_ids = [sid for _, sid in scored[:3]]

      # Merge: user manual picks always included, add auto-matched
      merged = list(dict.fromkeys(user_skill_ids + matched_ids))

      logger.info(
          f"skill_matcher_node: user={user_skill_ids}, "
          f"matched={matched_ids}, merged={merged}"
      )
      return {"skill_ids": merged}

  def _match_score(
      intent_text: str,
      skill_text: str,
      task_type: str,
      params: dict,
  ) -> float:
      score = 0.0

      # Word overlap
      intent_words = set(intent_text.split())
      skill_words = set(skill_text.split())
      if skill_words:
          overlap = len(intent_words & skill_words)
          score += min(overlap / len(skill_words), 1.0) * 0.5

      # strategy_hint match
      hint = params.get("strategy_hint", "") if isinstance(params, dict) else ""
      if hint and hint.lower() == task_type:
          score += 0.3

      # Name exact keyword bonus
      if any(kw in intent_text for kw in skill_text.split()[:3]):
          score += 0.2

      return min(score, 1.0)
  ```

- [ ] 2. 在 graph.py 中：
  - import `skill_matcher_node`
  - 将图结构从 `intent → skill` 改为 `intent → skill_matcher → skill`
  - 新增 `_after_intent()` routing：`return "skill_matcher"`（取消/错误→END）
  - 新增 `_after_skill_matcher()` routing：`return "skill"`（取消/错误→END）
  - `build_agent_mode_graph()` 中插入节点和边

**Verification:**
- [ ] `py -3.14 -c "from app.core.agent.nodes.skill_matcher_node import skill_matcher_node; print('OK')"`
- [ ] `py -3.14 -c "from app.core.agent.graph import build_agent_mode_graph; g = build_agent_mode_graph(); print(list(g.nodes.keys()))"` 输出包含 `skill_matcher`

**Commit:** `feat: agent-driven skill matching between intent and skill nodes`

---

## Task 8.2: 数据流验证 + 边界处理

**Files:**
- 修改 `backend/app/core/agent/nodes/skill_node.py`

**Steps:**
- [ ] 1. skill_node 不再读取前端传入的原始 `skill_ids`，改为始终处理 graph state 中的 `skill_ids`（可能已被 skill_matcher 覆盖）。
- [ ] 2. 当 `skill_ids` 为空时：原逻辑不变（返回 `{"skill_hints": None}`）。
- [ ] 3. 当用户选中的 skill 被 skill_matcher 追加了其他 skill 时：hints 合并逻辑不变（已有顺序优先 + update）。
- [ ] 4. 边界：skill 被删除但 session 仍引用过期 ID → skill_node 已有 `if not skill: continue` 保护，无需改动。

**Verification:**
- [ ] 模拟 scenario：intent 是「画一套表情包」→ matcher 应匹配名为「表情包」「套图」「图标集」的 skill
- [ ] 模拟 scenario：用户手动选了一个 skill + matcher 追加了一个 → merged 包含两者

**Commit:** `fix: skill_node consumes state skill_ids (may be auto-matched)`

---

## 变更总结

| 文件 | 操作 | 变更量 |
|------|------|--------|
| `nodes/skill_matcher_node.py` | **新建** | +50 |
| `graph.py` | 插入 skill_matcher 节点 + routing | +20 |
| `nodes/skill_node.py` | 注释/日志微调 | ±0 |

**Graph 结构更新：**
```
intent → skill_matcher → skill → context_enrichment → planner → ...
```

**净变化：** +70 行。P2 闭环。
