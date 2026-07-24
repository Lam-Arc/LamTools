# Agent 内联渐进式显示 — 实施计划

> **For agentic workers:** Use executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Agent 执行过程的显示从黑盒卡片重构为内联渐进式，每个步骤作为独立内联元素散布在消息流中。

**Architecture:** 去掉 AgentStreamCard 外层包裹，拆为 4 个轻量组件（AgentInlineStep / AgentToolCall / AgentCheckpoint / AgentStatusLine）。Pinia store 为唯一数据源，SSE 事件处理移入 store actions，Sessions.vue 只做路由。

**Tech Stack:** Vue 3 / Pinia / TypeScript

---

## Task 1: 更新类型定义

**Files:** `frontend/src/types/index.ts`

**Steps:**
- [ ] 在 `AgentStreamState` 中添加 `startedAt: number | null` 字段（用于计算耗时）
- [ ] 在 `AgentStreamStep` 中添加 `group?: 'internal' | 'key'` 字段（区分内部节点和关键节点，影响默认折叠行为和颜色）

**Verification:**
- [ ] TypeScript 编译无错误

**Commit:** `refactor(types): add startedAt and group to agent stream types`

---

## Task 2: 重构 Pinia store — 添加 agent stream actions

**Files:** `frontend/src/stores/session.ts`

**Steps:**
- [ ] 将 `agentStreamStates` 从 `ref<Map<...>>` 改为 `reactive(new Map<...>())`，消除每次 set 时创建新 Map 的开销
- [ ] 同样将 `checkpointStates` 改为 `reactive(new Map<...>())`
- [ ] 添加 `handleAgentStarted(sessionId: string, event: LamEvent)` action：创建 AgentStreamState，设置 startedAt = Date.now()
- [ ] 添加 `handleNodeProgress(sessionId: string, event: LamEvent)` action：从 Sessions.vue 的 onAgentEvent 中迁移 agent_node_progress 处理逻辑，包含 decision rollback
- [ ] 添加 `handleToolCall(sessionId: string, event: LamEvent)` action：迁移 agent_tool_call 逻辑
- [ ] 添加 `handleToolResult(sessionId: string, event: LamEvent)` action：迁移 agent_tool_result 逻辑
- [ ] 添加 `handleAgentToken(sessionId: string, event: LamEvent)` action：迁移 agent_token 逻辑
- [ ] 添加 `handleAgentDone(sessionId: string, event: LamEvent)` action：迁移 agent_done 逻辑，去掉 500ms setTimeout，直接标记 done
- [ ] 添加 `handleAgentError(sessionId: string, event: LamEvent)` action：迁移 agent_error 逻辑，去掉 500ms setTimeout
- [ ] 添加 `handleAgentCancelled(sessionId: string, event: LamEvent)` action：迁移 agent_cancelled 逻辑
- [ ] 添加 `handleCheckpoint(sessionId: string, event: LamEvent)` action：迁移 checkpoint_required 逻辑
- [ ] 添加 `handleToolWarning(sessionId: string, event: LamEvent)` action：迁移 agent_tool_warning 逻辑
- [ ] 添加 `handleTaskCompleted(sessionId: string, event: LamEvent)` action：迁移 task_completed/task_failed 清理逻辑
- [ ] 更新 `setAgentStream` / `clearAgentStream` 适配 reactive Map（不再需要创建新 Map 触发响应）
- [ ] 更新 `setCheckpoint` / `clearCheckpoint` 适配 reactive Map
- [ ] 在 handleNodeProgress 中，为步骤设置 group 字段：intent/planner/executor/critic/decision 为 'key'，其余为 'internal'

**Verification:**
- [ ] TypeScript 编译无错误
- [ ] 所有 action 函数签名正确

**Commit:** `refactor(store): add agent stream actions, migrate SSE event handling`

---

## Task 3: 创建 AgentInlineStep.vue 组件

**Files:** `frontend/src/components/session/AgentInlineStep.vue` (新建)

**Steps:**
- [ ] 创建组件，props: `step: AgentStreamStep`, `readonly?: boolean`, `defaultExpanded?: boolean`
- [ ] emits: `toggle-expand`, `open-image`
- [ ] 运行中状态：braille spinner（CSS animation，8帧 80ms 间隔）+ 节点标签，文字颜色 #000
- [ ] 完成状态：`▸` 折叠箭头 + 标签 + 摘要，文字颜色 #666（key 节点）或 #999（internal 节点）
- [ ] 错误状态：`✕` + 标签，文字颜色 #e04040
- [ ] 点击 ▸ 切换展开/折叠
- [ ] 展开内容区域：左侧 2px #000 边框 + #fafafa 背景 + padding
- [ ] 展开内容根据 step.name 渲染不同子模板：
  - intent: 任务类型标签 + 置信度 + 原因
  - planner: 策略标签 + 步骤列表
  - executor: 完成步骤列表 + 缩略图
  - critic: 评分信息
  - decision: 决策结果
  - 其他: content 文本
- [ ] 缩略图显示：折叠态在标签右侧显示最多 4 张缩略图（40x40），超出显示 +N
- [ ] 样式：黑白灰极简，无 emoji，Lucide SVG 图标

**Verification:**
- [ ] 组件文件创建完成
- [ ] TypeScript 编译无错误

**Commit:** `feat(ui): create AgentInlineStep component`

---

## Task 4: 创建 AgentToolCall.vue 组件

**Files:** `frontend/src/components/session/AgentToolCall.vue` (新建)

**Steps:**
- [ ] 创建组件，props: `step: AgentStreamStep`, `readonly?: boolean`
- [ ] emits: `toggle-expand`, `open-image`
- [ ] 调用中状态：braille spinner + `> toolName` + 参数摘要（如 ×3），文字颜色 #000
- [ ] 完成状态：`✓ toolName` + 结果摘要（如 · 3张），文字颜色 #666
- [ ] 错误状态：`✕ toolName`，文字颜色 #e04040
- [ ] 点击展开参数/结果详情面板（左侧 2px #e5e5e5 边框 + #fafafa 背景）
- [ ] 展开内容：args 键值对列表 + result 文本 + 图片缩略图

**Verification:**
- [ ] 组件文件创建完成
- [ ] TypeScript 编译无错误

**Commit:** `feat(ui): create AgentToolCall component`

---

## Task 5: 创建 AgentCheckpoint.vue 组件

**Files:** `frontend/src/components/session/AgentCheckpoint.vue` (新建)

**Steps:**
- [ ] 创建组件，props: `checkpointState: CheckpointInfo`
- [ ] emits: `approve`, `retry`, `replan`, `cancel`, `open-image`
- [ ] 黄色左边框（2px #fde68a）+ #fffbeb 背景
- [ ] Checkpoint 标签 + 消息文本
- [ ] 预览图缩略图（80x80），点击触发 open-image
- [ ] 操作按钮行：继续（黑底白字）、重做此步（橙色）、重新规划（蓝色）、终止（红色）

**Verification:**
- [ ] 组件文件创建完成
- [ ] TypeScript 编译无错误

**Commit:** `feat(ui): create AgentCheckpoint component`

---

## Task 6: 创建 AgentStatusLine.vue 组件

**Files:** `frontend/src/components/session/AgentStatusLine.vue` (新建)

**Steps:**
- [ ] 创建组件，props: `state: AgentStreamState`
- [ ] 计算耗时：从 state.startedAt 到当前时间（运行中）或固定值（完成）
- [ ] 正常完成：`▣ Agent · ¥cost · Xs` — 黑色圆点 + Agent + 费用 + 耗时，文字颜色 #999
- [ ] 错误：`▣ Agent · 错误 · Xs` — 红色圆点 #e04040
- [ ] 取消：`▣ Agent · 已取消 · Xs` — 灰色圆点 #999
- [ ] 运行中：`▣ Agent · thinking...` — 黑色圆点 + 状态文字

**Verification:**
- [ ] 组件文件创建完成
- [ ] TypeScript 编译无错误

**Commit:** `feat(ui): create AgentStatusLine component`

---

## Task 7: 重构 MessageList.vue

**Files:** `frontend/src/components/session/MessageList.vue`

**Steps:**
- [ ] 移除 AgentStreamCard 和 AgentMessageCard 的 import
- [ ] 添加 AgentInlineStep, AgentToolCall, AgentCheckpoint, AgentStatusLine 的 import
- [ ] 重构 props：移除 `agentStreamState`, `agentProgress`, `checkpointState`，改为接收 `agentStreamState` 从 store computed
- [ ] 历史 agent 消息（msg.message_type === 'agent'）：遍历 agentToStreamState(msg).steps，每个 step 根据类型渲染 AgentInlineStep 或 AgentToolCall（readonly=true）
- [ ] 活跃 agent 流：从 store 获取 streamState，遍历 steps 渲染对应组件
- [ ] Checkpoint：在 executor 步骤后渲染 AgentCheckpoint（从 store 获取 checkpointState）
- [ ] 完成后：渲染 AgentStatusLine
- [ ] 删除 DEBUG 信息 div（69-71行）
- [ ] 删除 agentToStreamState 中的 step.group 设置逻辑（已在 store 中处理）
- [ ] 保留 agentToStreamState 函数但适配新类型（添加 group 字段）

**Verification:**
- [ ] TypeScript 编译无错误
- [ ] 无 DEBUG 信息残留

**Commit:** `refactor(ui): rewrite MessageList to use inline agent components`

---

## Task 8: 重构 Sessions.vue

**Files:** `frontend/src/views/Sessions.vue`

**Steps:**
- [ ] 移除 `agentStreamState` local ref（199行）
- [ ] 移除 `agentProgress` local ref（200行）
- [ ] 移除 `agentCheckpointState` local ref（202行）
- [ ] 添加 computed：`agentStreamState` 从 store.getAgentStream(currentSessionId) 获取
- [ ] 添加 computed：`agentCheckpointState` 从 store.getCheckpoint(currentSessionId) 获取
- [ ] 简化 onAgentEvent 回调为路由函数，调用 store actions：
  ```
  task_started → store.handleAgentStarted
  agent_token → store.handleAgentToken
  agent_tool_call → store.handleToolCall
  agent_tool_result → store.handleToolResult
  agent_node_progress → store.handleNodeProgress
  agent_tool_warning → store.handleToolWarning
  agent_done → store.handleAgentDone
  agent_error → store.handleAgentError
  agent_cancelled → store.handleAgentCancelled
  checkpoint_required → store.handleCheckpoint
  task_completed/task_failed → store.handleTaskCompleted
  ```
- [ ] 更新 MessageList 的 props 传递：移除 :agent-progress，:checkpoint-state 改用 computed
- [ ] 更新 selectSession 函数：移除 agentStreamState/agentCheckpointState 的恢复逻辑（现在从 store computed 自动获取）
- [ ] 更新 resolveAgentCheckpoint：使用 store.getCheckpoint 获取 correlationId
- [ ] 更新 cancelAgent：使用 store.getAgentStream 获取 sessionId
- [ ] 移除 onTaskUpdate 中的 agentProgress 更新（已在 store 中处理）

**Verification:**
- [ ] TypeScript 编译无错误
- [ ] 无 local ref 残留

**Commit:** `refactor(views): simplify Sessions.vue, delegate to store actions`

---

## Task 9: 删除废弃组件

**Files:**
- `frontend/src/components/session/AgentStreamCard.vue` (删除)
- `frontend/src/components/session/AgentMessageCard.vue` (删除)
- `frontend/src/components/session/CheckpointOverlay.vue` (删除)

**Steps:**
- [ ] 删除 AgentStreamCard.vue
- [ ] 删除 AgentMessageCard.vue
- [ ] 删除 CheckpointOverlay.vue
- [ ] 搜索项目中是否还有对这三个组件的引用，如有则清理

**Verification:**
- [ ] 三个文件已删除
- [ ] 无残留引用

**Commit:** `chore: remove obsolete AgentStreamCard, AgentMessageCard, CheckpointOverlay`

---

## Task 10: 验证构建与清理

**Steps:**
- [ ] 运行 `cd frontend && npm run build` 确认构建成功
- [ ] 检查浏览器控制台无错误
- [ ] 验证 SSE 事件流正常工作：task_started → node_progress → tool_call → tool_result → agent_done
- [ ] 验证 checkpoint 流程正常
- [ ] 验证 session 切换时 agent 状态正确恢复
- [ ] 验证历史 agent 消息正确渲染

**Verification:**
- [ ] 构建成功
- [ ] 运行时无错误

**Commit:** (无单独 commit，包含在前面的 commit 中)
