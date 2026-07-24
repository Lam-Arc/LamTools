# Checkpoint SSE 修复方案

> **For agentic workers:** Use executing-plans to implement this plan.

**Goal:** 修复 checkpoint 事件 → SSE → 前端弹窗的全链路，恢复 checkpoint 功能。

**Root cause:** planner prompt 中 checkpoint 字段被移除（暂避 SSE 断连），SSE 重连 replay 已修复但未验证。

---

## Task C1: 恢复 planner 中的 checkpoint 字段

**Files:**
- `backend/app/core/agent/capability_prompts.py`

**Steps:**
- [ ] 1. 恢复 `build_planner_system_prompt()` 中的 checkpoint 字段定义：
  ```python
  '  - "checkpoint" (object with "enabled": true/false, optional)\n\n',
  ```
- [ ] 2. `PLANNER_STRATEGY_GUIDE` 中 iterative 策略恢复 checkpoint 建议：
  ```
  - Consider adding a checkpoint after the first step for user review.
  ```

**Verification:**
- [ ] planner prompt 包含 `"checkpoint"` 字段

**Commit:** `fix: restore checkpoint field in planner prompt`

---

## Task C2: SSE 连接诊断 + 保底修复

**Files:**
- `backend/app/routers/session.py`
- `frontend/src/composables/useSessionEvents.ts`

**Steps:**
- [ ] 1. SSE connect 时 log `[SSE] connected`，disconnect 时 log `[SSE] disconnected`（已在 B-1 中添加，验证生效）
- [ ] 2. 确认 `session_id` query param 传递和 replay 生效 — `subscribe(session_id=session_id, last_event_id=last_event_id)` 已实现
- [ ] 3. 若 SSE 仍断连：在 `useSessionEvents.ts` 的 `connect()` 最开头加入 `console.log('[SSE] connecting, session_id:', currentSessionId)`

**Verification:**
- [ ] 日志中 `SSE connected` 和 `publish: delivered>=1` 同时出现
- [ ] checkpoint 事件发射时 SSE 队列非空

**Commit:** `fix: SSE connection diagnostics and stability`

---

## Task C3: 前端 CheckpointOverlay 补全

**Files:**
- `frontend/src/views/Sessions.vue`
- `frontend/src/components/session/CheckpointOverlay.vue`

**Steps:**
- [ ] 1. `agentCheckpointState` 增加 `stepDescription` 提取（已在 V2 问题 4 修复中完成 — 验证）
- [ ] 2. 确认 CheckpointOverlay 的 approve/retryStep/replan/cancel 四个按钮能正确调用 `sessionApi.checkpoint()`
- [ ] 3. 确认 approve 后前端能清除 checkpoint 状态，retry/replan 后 AgentStreamCard 能刷新

**Verification:**
- [ ] checkpoint 弹窗显示步骤描述
- [ ] 点击"继续"后 graph 正常恢复执行
- [ ] 点击"重做此步"后 executor 重新执行当前步骤

**Commit:** `fix: checkpoint overlay step description and action flow`

---

## 变更总结

| 文件 | 变更 | 量 |
|------|------|----|
| `capability_prompts.py` | 恢复 checkpoint 字段 | +2 |
| `useSessionEvents.ts` | SSE 连接日志 | +1 |
| `Sessions.vue` | stepDescription 提取 | verify |
| **净变化** | | +3 |

---

## 测试方法

1. 发一条带 checkpoint 的指令（如 `先画草图再精修` — planner 会在第一步后插入 checkpoint）
2. 预期 AgentStreamCard 执行第一步后弹出 checkpoint 弹窗
3. 点击"继续"→ 第二步执行
4. 点击"重做"→ 第一步重生成
5. 点击"重新规划"→ 回到 planner
6. 点击"终止"→ 任务取消
