# Agent 节点内容可见性与持久化方案

> **For agentic workers:** Use executing-plans to implement this plan.

**Goal:** 节点完成后显示 LLM 产出摘要，agent_done 后 timeline 不消失，持久化为历史消息卡。

---

## Task F1: 节点产出内容摘要显示

**Files:**
- 修改 `backend/app/core/agent/nodes/intent_node.py`
- 修改 `backend/app/core/agent/nodes/planner_node.py`
- 修改 `backend/app/core/agent/nodes/prompt_builder_node.py`
- 修改 `backend/app/core/agent/nodes/critic_node.py`
- 修改 `backend/app/core/agent/nodes/decision_node.py`
- 修改 `frontend/src/views/Sessions.vue`
- 修改 `frontend/src/components/session/AgentStreamCard.vue`

**Steps:**

- [ ] 1. 各 LLM 节点 emit 时追加 `content` 字段：
  - `intent_node`：`content = f"分类为 {task_type}，置信度 {confidence}。{reason}"`
  - `planner_node`：`content = f"{strategy} 策略，{len(steps)} 步：\n" + "\n".join(f"{i+1}. {s.description}" for i,s in enumerate(plan_steps[:8]))`
  - `prompt_builder_node`：`content = f"优化了 {len(optimized)} 个提示词"`
  - `critic_node`：`content = f"平均 {avg_score:.1f} 分，{len(critic_results)} 张图已评估"`
  - `decision_node`：`content = f"{'通过' if result=='pass' else '重试'}（{reason}）"`
- [ ] 2. 非 LLM 节点也 emit 内容摘要：
  - `skill_matcher_node`：`content = f"匹配到 {matched_count} 个技能：{skill_names}"`
  - `skill_node`：`content = f"加载偏置：{bias_summary}"`
  - `context_enrichment_node`：`content = f"上下文：{image_count} 张参考图，token 预算 {budget}"`
- [ ] 3. 前端 `AgentStreamCard.vue` — `node_progress` 类型 step 渲染 `content` 文本，等宽字体灰色小字。

**Verification:**
- [ ] 每个节点卡片下有文本摘要（如 planner 显示 "radiate 策略，6 步：\n1. 锚点图\n2. 开心表情..."）

**Commit:** `feat: graph nodes emit content summary alongside progress events`

---

## Task F2: AgentStreamCard 持久化为消息

**Files:**
- 修改 `frontend/src/views/Sessions.vue`
- 修改 `frontend/src/stores/session.ts`
- 修改 `frontend/src/components/session/MessageList.vue`
- 修改 `frontend/src/components/session/AgentStreamCard.vue`

**Steps:**

- [ ] 1. `agent_done` 时，不销毁 `agentStreamState`，而是将其快照写入当前会话的 `messages` 列表（插入一条 `type: 'agent_timeline'` 的虚拟消息）。
- [ ] 2. `MessageList.vue` — 渲染 `agent_timeline` 类型消息时，使用 `AgentStreamCard` 的只读模式（`readonly` prop，隐藏光标闪烁动画）。
- [ ] 3. `AgentStreamCard.vue` — 新增 `readonly` prop，为 true 时：
  - 隐藏闪烁光标
  - 所有 step 状态固定显示（不再更新）
  - 忽略后续 SSE 事件（不再追加 step）
- [ ] 4. 图像结果卡（`ImageMessageCard`）在 timeline 卡下方独立显示。
- [ ] 5. 下一次 agent 任务开始时，`agentStreamState` 重新创建新的（不覆盖旧的 timeline 消息）。

**Verification:**
- [ ] agent_done 后消息列表中出现只读 timeline 卡 + 图像卡
- [ ] 刷新页面后 timeline 卡仍存在（通过消息持久化）
- [ ] 再次发指令时新的 AgentStreamCard 独立工作，不影响旧 timeline

**Commit:** `feat: persist agent timeline as message after generation completes`

---

## 变更总结

| 文件 | 操作 | 变更量 |
|------|------|--------|
| 5 个 LLM 节点 | emit 追加 content 字段 | +15 |
| 3 个非 LLM 节点 | emit 追加 content 字段 | +10 |
| `AgentStreamCard.vue` | content 渲染 + readonly 模式 | +20 |
| `Sessions.vue` | agent_done timeline 持久化 | +15 |
| `MessageList.vue` | agent_timeline 消息类型渲染 | +10 |
| `session.ts` | timeline 消息 store 逻辑 | +10 |

**净变化：** ~+80 行。
