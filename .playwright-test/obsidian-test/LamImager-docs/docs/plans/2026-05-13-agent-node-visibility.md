# Agent 节点进度可见性方案

> **For agentic workers:** Use executing-plans to implement this plan.

**Goal:** 9 个 graph 节点全部发射 SSE progress 事件，AgentStreamCard 实时显示节点进度，消除 30-50 秒黑箱静默期。

**Architecture:** 每个节点完成后调用 `task_manager.publish(agent_node_progress)` → 前端 `AgentStreamCard` 新增 `agent_node_progress` case 渲染节点卡片。

---

## Task V1: 后端 — 各节点发射进度事件

**Files:**
- 修改 `backend/app/core/agent/graph.py`（executor_node）
- 修改 `backend/app/core/agent/nodes/intent_node.py`
- 修改 `backend/app/core/agent/nodes/skill_matcher_node.py`
- 修改 `backend/app/core/agent/nodes/skill_node.py`
- 修改 `backend/app/core/agent/nodes/context_node.py`
- 修改 `backend/app/core/agent/nodes/planner_node.py`
- 修改 `backend/app/core/agent/nodes/prompt_builder_node.py`
- 修改 `backend/app/core/agent/nodes/critic_node.py`
- 修改 `backend/app/core/agent/nodes/decision_node.py`

**Steps:**
- [ ] 1. 定义统一事件格式。每个节点完成后 publish：
  ```python
  await task_manager.publish(LamEvent(
      event_type="task_progress",
      correlation_id=f"agent-{session_id}",
      payload={
          "type": "agent_node_progress",
          "session_id": session_id,
          "node": "planner",          # 节点名
          "status": "done",           # running | done | error
          "message": "生成执行计划",    # 中文简述
          "detail": {                 # 可选：节点特有数据
              "strategy": "radiate",
              "steps": 6
          }
      },
  ))
  ```
- [ ] 2. 各节点插入 publish 调用：
  - `intent_node`: LLM 分类完成后 → `{node: "intent", message: "解析意图", detail: {task_type, confidence}}`
  - `skill_matcher_node`: 匹配完成后 → `{node: "skill_matcher", message: "匹配技能", detail: {matched_count}}`
  - `skill_node`: hints 构建后 → `{node: "skill", message: "加载技能偏置"}`
  - `context_enrichment_node`: 去重/截断/描述后 → `{node: "context", message: "整理上下文", detail: {images, budget}}`
  - `planner_node`: LLM 规划完成后 → `{node: "planner", message: "生成执行计划", detail: {strategy, steps}}`（已有旧 publish，保留并增强 detail）
  - `prompt_builder_node`: 全部 step 优化后 → `{node: "prompt_builder", message: "优化提示词", detail: {step_count}}`
  - `executor_node`: 执行完成后 → 已有 publish，保持
  - `critic_node`: 全部 artifact 评分后 → `{node: "critic", message: "评估结果", detail: {avg_score, artifact_count}}`
  - `decision_node`: 决策完成后 → `{node: "decision", message: "通过"\|"重试"\|"重规划", detail: {result, avg_score}}`

**Verification:**
- [ ] 每个节点文件中存在 `task_manager.publish` 调用，payload.type 为 `agent_node_progress`

**Commit:** `feat: all graph nodes emit agent_node_progress SSE events`

---

## Task V2: 前端 — AgentStreamCard 渲染节点进度

**Files:**
- 修改 `frontend/src/views/Sessions.vue`
- 修改 `frontend/src/components/session/AgentStreamCard.vue`
- 修改 `frontend/src/types/index.ts`

**Steps:**
- [ ] 1. `types/index.ts` — `AgentStreamStep.type` 新增 `'node_progress'`。
- [ ] 2. `Sessions.vue` — `onAgentEvent` 的 switch 新增 `agent_node_progress` case：
  ```typescript
  case 'agent_node_progress':
    const nodeStep = state.steps.find(s => s.name === event.payload.node)
    if (nodeStep) {
      nodeStep.status = event.payload.status
      nodeStep.content = event.payload.message
      nodeStep.meta = event.payload.detail
    } else {
      state.steps.push({
        id: event.event_id,
        type: 'node_progress',
        name: event.payload.node,
        status: event.payload.status,
        content: event.payload.message,
        meta: event.payload.detail,
      })
    }
    break
  ```
- [ ] 3. `AgentStreamCard.vue` — step 类型为 `node_progress` 时渲染节点名 + 消息 + 图标（每个节点一个 Lucide 图标，如 intent=Lightbulb, planner=ClipboardList, executor=Play, critic=Star, decision=CheckCircle）。
- [ ] 4. **修复问题 2**：executor 进度在 AgentStreamCard 可见。`task_progress` 事件（步骤进度）额外触发 agentToken 逻辑或新增 `agent_step_progress` case。
- [ ] 5. **修复问题 5**：`task_started` 事件去掉 `task_type/strategy` 硬编码，改为 graph 结束后由 `agent_done` 事件统一携带真实值（本就可从 metadata 读取）。
- [ ] 6. **修复问题 6**：`MessageList.vue` 渲染 `AgentStreamCard` 时传入 `:progress="activeProgress"`，跟踪 executor 内部步骤进度。
- [ ] 7. **修复问题 3**：Sessions.vue switch 新增 `agent_tool_warning` case，显示警告。
- [ ] 8. **修复问题 4**：`agentCheckpointState` 增加 `stepDescription` 字段，从后端 `step.description` 提取。

**Verification:**
- [ ] AgentStreamCard 在 agent 执行期间逐步渲染节点卡片（intent → skill_matcher → skill → context → planner → prompt_builder → executor → critic → decision）
- [ ] 每个节点卡片显示对应 Lucide 图标和中文消息

**Commit:** `feat: AgentStreamCard renders real-time node progress timeline`

---

## 变更总结

| 文件 | 操作 | 变更量 |
|------|------|--------|
| 9 个 graph 节点 | 各 +5 行 publish 调用 | +45 |
| `Sessions.vue` | switch 新增 3 case + 修复 | +30 |
| `AgentStreamCard.vue` | node_progress 渲染 + 图标 | +25 |
| `types/index.ts` | 新增 node_progress 类型 | +2 |
| `MessageList.vue` | progress prop 传入 | +3 |

**净变化：** ~+105 行。修复 7 个可见性问题。
