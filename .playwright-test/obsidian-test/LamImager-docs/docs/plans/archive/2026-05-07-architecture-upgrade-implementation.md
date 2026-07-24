# LamImager 架构升级实施计划

> **For agentic workers:** Use executing-plans skill to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现多会话并发生成、SSE 实时状态推送、规划/优化功能全面增强

**Architecture:** 基于 SSE 事件中心架构，新增 TaskManager 单例管理全局任务状态，通过 `/api/sessions/events` SSE 端点推送状态变更。前端使用 Map<TaskHandle> 替代全局 generating 标志，支持多会话并发。规划功能增加策略选择、步骤编辑、模板系统和 checkpoint 机制。

**Tech Stack:** Python 3.14+ / FastAPI / SQLAlchemy async / Vue3 / TypeScript / Pinia / SSE

---

## Phase 1: 基础设施（数据库 + TaskManager + SSE）

### Task 1: Session 模型新增 status 字段

**Files:** `backend/app/models/session.py`

**Steps:**
- [ ] 在 `session.py` 顶部新增 `import enum`
- [ ] 新增 `SessionStatus` 枚举类，包含 idle/generating/optimizing/planning/error 五个值
- [ ] 在 `Session` 类中新增 `status: Mapped[str] = mapped_column(String(20), default="idle", nullable=False)` 字段，位于 `title` 和 `created_at` 之间

**Verification:**
- [ ] 后端启动无报错
- [ ] `py -3.14 -c "from app.models.session import Session, SessionStatus; print(SessionStatus.generating)"` 输出 `SessionStatus.generating`

**Commit:** `feat: add SessionStatus enum and status field to Session model`

---

### Task 2: 数据库迁移 + 启动状态重置

**Files:** `backend/app/database.py`

**Steps:**
- [ ] 在 `init_db()` 函数中，现有迁移逻辑之后，新增 sessions 表的 status 列迁移：
  ```python
  result = await conn.execute(text("PRAGMA table_info('sessions')"))
  columns = [row[1] for row in result.fetchall()]
  if "status" not in columns:
      await conn.execute(text("ALTER TABLE sessions ADD COLUMN status VARCHAR(20) DEFAULT 'idle' NOT NULL"))
  ```
- [ ] 在迁移逻辑之后，新增启动时状态重置：
  ```python
  await conn.execute(text("UPDATE sessions SET status = 'idle' WHERE status != 'idle'"))
  ```

**Verification:**
- [ ] 删除 `data/lamimager.db`，重启后端，检查 sessions 表是否有 status 列且默认值为 'idle'
- [ ] 手动设置某 session status 为 'generating'，重启后端，检查该 session status 是否被重置为 'idle'

**Commit:** `feat: add status column migration and startup reset for sessions`

---

### Task 3: SessionResponse Schema 新增 status 字段

**Files:** `backend/app/schemas/session.py`

**Steps:**
- [ ] 在 `SessionResponse` 类中新增 `status: str = "idle"` 字段，位于 `title` 之后

**Verification:**
- [ ] `py -3.14 -c "from app.schemas.session import SessionResponse; print(SessionResponse.model_fields)"` 输出包含 `status`

**Commit:** `feat: add status field to SessionResponse schema`

---

### Task 4: 修复 N+1 查询 + 返回 status 字段

**Files:** `backend/app/services/session_manager.py`

**Steps:**
- [ ] 重写 `list_sessions()` 函数，使用单次 JOIN 查询替代循环子查询：
  ```python
  async def list_sessions(db: AsyncSession) -> list[dict]:
      result = await db.execute(
          select(
              Session,
              func.count(Message.id).label("message_count"),
              func.coalesce(func.sum(BillingRecord.cost), 0).label("cost"),
              func.coalesce(func.sum(BillingRecord.tokens_in + BillingRecord.tokens_out), 0).label("tokens"),
          )
          .outerjoin(Message, Message.session_id == Session.id)
          .outerjoin(BillingRecord, BillingRecord.session_id == Session.id)
          .group_by(Session.id)
          .order_by(Session.updated_at.desc())
      )
      response = []
      for row in result:
          s = row[0]
          response.append({
              "id": s.id,
              "title": s.title,
              "status": s.status,
              "created_at": str(s.created_at) if s.created_at else None,
              "updated_at": str(s.updated_at) if s.updated_at else None,
              "message_count": row.message_count,
              "cost": float(row.cost),
              "tokens": int(row.tokens),
          })
      return response
  ```
- [ ] 删除原有的循环子查询代码和 logging 导入

**Verification:**
- [ ] `GET /api/sessions` 返回的每个 session 对象包含 `status` 字段
- [ ] 后端日志中不再有 N+1 查询（观察 SQLAlchemy echo 日志，应只有 1 条 SELECT 语句）

**Commit:** `fix: resolve N+1 query in list_sessions and include status field`

---

### Task 5: 实现 TaskManager 单例

**Files:** `backend/app/services/task_manager.py`（新建）

**Steps:**
- [ ] 创建 `task_manager.py`，实现完整的 `TaskManager` 类：
  - `TaskStatus` 枚举（idle/generating/optimizing/planning/error）
  - `TaskInfo` 数据类（session_id, status, progress, total, message）
  - `TaskManager` 单例类，包含：
    - `_tasks: dict[str, TaskInfo]` — 活跃任务
    - `_queues: dict[str, asyncio.Queue]` — SSE 订阅队列
    - `_queue_counter: int` — 队列 ID 计数器
    - `_semaphore: asyncio.Semaphore(5)` — 全局限流
    - `acquire()` / `release()` — 信号量操作
    - `update_task()` — 更新任务状态并广播事件
    - `get_task()` / `get_all_tasks()` — 查询任务
    - `subscribe()` / `unsubscribe()` — SSE 订阅管理
    - `_broadcast()` — 向所有队列推送事件

**Verification:**
- [ ] `py -3.14 -c "from app.services.task_manager import TaskManager; tm = TaskManager(); print(type(tm))"` 无报错
- [ ] `TaskManager()` 多次调用返回同一实例（单例验证）

**Commit:** `feat: implement TaskManager singleton for task state and SSE broadcasting`

---

### Task 6: SSE /api/sessions/events 端点

**Files:** `backend/app/routers/session.py`

**Steps:**
- [ ] 在文件顶部新增导入：
  ```python
  import asyncio
  import json
  from fastapi.responses import StreamingResponse
  from app.services.task_manager import TaskManager
  ```
- [ ] 新增 SSE 端点：
  ```python
  @router.get("/events")
  async def session_events():
      task_manager = TaskManager()
      queue_id, queue = await task_manager.subscribe()

      async def event_generator():
          try:
              yield f"data: {json.dumps({'type': 'snapshot', 'data': task_manager.get_all_tasks()})}\n\n"
              while True:
                  try:
                      event = await asyncio.wait_for(queue.get(), timeout=30)
                      yield f"data: {json.dumps(event)}\n\n"
                  except asyncio.TimeoutError:
                      yield f"data: {json.dumps({'type': 'ping', 'data': {}})}\n\n"
          finally:
              task_manager.unsubscribe(queue_id)

      return StreamingResponse(event_generator(), media_type="text/event-stream")
  ```
- [ ] 注意：此端点必须放在 `/{session_id}` 路由之前，避免 "events" 被当作 session_id 解析

**Verification:**
- [ ] 启动后端，用浏览器访问 `http://localhost:8000/api/sessions/events`，应看到 SSE 事件流（snapshot + 定期 ping）
- [ ] 用 `curl -N http://localhost:8000/api/sessions/events` 验证事件流格式

**Commit:** `feat: add SSE /api/sessions/events endpoint for real-time task updates`

---

### Task 7: generate_service 集成 TaskManager

**Files:** `backend/app/services/generate_service.py`

**Steps:**
- [ ] 在文件顶部新增 `from app.services.task_manager import TaskManager, TaskStatus`
- [ ] 在 `handle_generate()` 函数开头，获取 TaskManager 实例并更新状态：
  ```python
  task_manager = TaskManager()
  task_manager.update_task(session_id, TaskStatus.GENERATING, message="生成中")
  ```
- [ ] 在优化阶段（`if data.optimize_directions:`），更新状态为 optimizing：
  ```python
  task_manager.update_task(session_id, TaskStatus.OPTIMIZING, message="优化提示词中")
  ```
  优化完成后恢复为 generating：
  ```python
  task_manager.update_task(session_id, TaskStatus.GENERATING, message="生成中")
  ```
- [ ] 在生成图片的 `asyncio.gather` 之前，更新进度信息：
  ```python
  task_manager.update_task(session_id, TaskStatus.GENERATING, progress=0, total=data.image_count, message=f"生成中 0/{data.image_count}")
  ```
- [ ] 在 `generate_one` 函数中，每次成功生成后更新进度（需在 semaphore 内部处理）
- [ ] 在函数末尾（成功和失败路径），清除任务状态：
  ```python
  task_manager.update_task(session_id, TaskStatus.IDLE)
  ```
  失败时：
  ```python
  task_manager.update_task(session_id, TaskStatus.ERROR, message=str(e))
  ```
  然后延迟清除：
  ```python
  await asyncio.sleep(3)
  task_manager.update_task(session_id, TaskStatus.IDLE)
  ```

**Verification:**
- [ ] 触发一次图像生成，在 SSE 事件流中观察到 task_update 事件（status 从 generating → idle）
- [ ] 触发带优化的生成，观察到 status 变化：generating → optimizing → generating → idle

**Commit:** `feat: integrate TaskManager into generate_service for real-time status updates`

---

## Phase 2: 前端并发支持

### Task 8: TypeScript 类型更新

**Files:** `frontend/src/types/index.ts`

**Steps:**
- [ ] 在 `SessionInfo` 接口中新增 `status: 'idle' | 'generating' | 'optimizing' | 'planning' | 'error'` 字段，位于 `updated_at` 之后
- [ ] 新增 `TaskHandle` 接口：
  ```typescript
  export interface TaskHandle {
    sessionId: string
    type: 'generate' | 'optimize' | 'plan'
    status: 'running' | 'done' | 'error'
    progress: number
    total: number
    abortController: AbortController | null
  }
  ```
- [ ] 新增 `TaskUpdateEvent` 接口：
  ```typescript
  export interface TaskUpdateEvent {
    session_id: string
    status: string
    progress: number
    total: number
    message: string
  }
  ```
- [ ] 扩展 `PlanStep` 接口（替换现有的内联类型）：
  ```typescript
  export interface PlanStep {
    prompt: string
    negative_prompt: string
    description: string
    image_count?: number
    image_size?: string
    reference_step_indices?: number[]
    checkpoint?: {
      enabled: boolean
      message: string
      auto_continue_seconds?: number
    }
  }
  ```
- [ ] 新增 `TemplateVariable` 接口：
  ```typescript
  export interface TemplateVariable {
    key: string
    type: 'string' | 'select' | 'number'
    label: string
    default: string
    options?: string[]
    required?: boolean
  }
  ```
- [ ] 新增 `PlanTemplate` 接口：
  ```typescript
  export interface PlanTemplate {
    id: string
    name: string
    description: string
    strategy: 'parallel' | 'sequential' | 'iterative'
    steps: PlanStep[]
    variables: TemplateVariable[]
    is_builtin: boolean
    created_at: string
    updated_at: string
  }
  ```
- [ ] 在 `GenerateRequest` 接口中新增 `plan_strategy: string` 字段

**Verification:**
- [ ] `cd frontend && npx tsc --noEmit` 无类型错误

**Commit:** `feat: add TypeScript types for TaskHandle, PlanStep, PlanTemplate, and session status`

---

### Task 9: useSessionEvents composable

**Files:** `frontend/src/composables/useSessionEvents.ts`（新建）

**Steps:**
- [ ] 创建 `useSessionEvents.ts`，实现 SSE 事件监听 composable：
  ```typescript
  import type { TaskUpdateEvent } from '../types'

  export function useSessionEvents(
    onTaskUpdate: (event: TaskUpdateEvent) => void,
    onSnapshot: (tasks: Record<string, { status: string; progress: number; total: number; message: string }>) => void,
  ) {
    let eventSource: EventSource | null = null

    function connect() {
      eventSource = new EventSource('/api/sessions/events')

      eventSource.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data)
          if (data.type === 'task_update') {
            onTaskUpdate(data.data)
          } else if (data.type === 'snapshot') {
            onSnapshot(data.data)
          }
        } catch { /* ignore parse errors */ }
      }

      eventSource.onerror = () => {
        // EventSource 内置自动重连
      }
    }

    function disconnect() {
      eventSource?.close()
      eventSource = null
    }

    return { connect, disconnect }
  }
  ```

**Verification:**
- [ ] `cd frontend && npx tsc --noEmit` 无类型错误
- [ ] 在浏览器控制台手动测试：`const { connect } = useSessionEvents(console.log, console.log); connect()` 无报错

**Commit:** `feat: add useSessionEvents composable for SSE task updates`

---

### Task 10: Session Store 改造

**Files:** `frontend/src/stores/session.ts`

**Steps:**
- [ ] 在 `SessionInfo` 类型导入中确认包含 `status` 字段（已在 Task 8 更新）
- [ ] 修改 `generate()` 函数签名，接受 `sessionId` 作为第一个参数：
  ```typescript
  async function generate(sessionId: string, data: { ... }) {
    try {
      const { data: result } = await sessionApi.generate({
        ...data,
        session_id: sessionId,
        skill_ids: selectedSkillIds.value,
      })
      if (sessionId === currentSessionId.value) {
        await fetchMessages(sessionId)
      }
      await fetchSessions()
      return result
    } catch (e) {
      console.error('Failed to generate:', e)
      throw e
    }
  }
  ```
- [ ] 更新 return 中的 `generate` 导出

**Verification:**
- [ ] `cd frontend && npx tsc --noEmit` 无类型错误
- [ ] 现有生成功能仍可正常工作（需配合 Sessions.vue 的调用修改）

**Commit:** `refactor: update session store generate() to accept sessionId parameter`

---

### Task 11: Sessions.vue — activeTasks + 状态徽章 + 生成动画改造

**Files:** `frontend/src/views/Sessions.vue`

**Steps:**
- [ ] 新增导入：
  ```typescript
  import { useSessionEvents } from '../composables/useSessionEvents'
  import { Loader2, AlertCircle } from 'lucide-vue-next'
  import type { TaskHandle, TaskUpdateEvent } from '../types'
  ```
- [ ] 替换 `generating` 和 `generatingSessionId` 为 `activeTasks`：
  ```typescript
  const activeTasks = ref<Map<string, TaskHandle>>(new Map())

  function isSessionBusy(sessionId: string): boolean {
    const task = activeTasks.value.get(sessionId)
    return task?.status === 'running'
  }

  function getSessionStatus(sessionId: string): string {
    const task = activeTasks.value.get(sessionId)
    if (task?.status === 'running') return task.type === 'optimize' ? 'optimizing' : task.type === 'plan' ? 'planning' : 'generating'
    if (task?.status === 'done') return 'idle'
    if (task?.status === 'error') return 'error'
    return 'idle'
  }

  function getTaskProgress(sessionId: string): string {
    const task = activeTasks.value.get(sessionId)
    if (!task || task.status !== 'running' || !task.total) return ''
    return `${task.progress}/${task.total}`
  }
  ```
- [ ] 在 `onMounted` 中初始化 SSE 连接：
  ```typescript
  const { connect: connectEvents, disconnect: disconnectEvents } = useSessionEvents(
    (event: TaskUpdateEvent) => {
      const task = activeTasks.value.get(event.session_id)
      if (task) {
        task.progress = event.progress
        task.total = event.total
        if (event.status === 'idle' || event.status === 'error') {
          task.status = event.status === 'error' ? 'error' : 'done'
          setTimeout(() => activeTasks.value.delete(event.session_id), 3000)
        }
      }
      store.fetchSessions()
    },
    (tasks) => {
      for (const [sid, info] of Object.entries(tasks)) {
        if (info.status !== 'idle') {
          activeTasks.value.set(sid, {
            sessionId: sid,
            type: info.status === 'generating' ? 'generate' : info.status === 'optimizing' ? 'optimize' : 'plan',
            status: 'running',
            progress: info.progress,
            total: info.total,
            abortController: null,
          })
        }
      }
    },
  )
  connectEvents()
  ```
- [ ] 在 `onUnmounted` 中断开 SSE：`disconnectEvents()`
- [ ] 修改会话列表模板，添加状态徽章（在 session-title 同行显示）
- [ ] 修改聊天区生成动画，从 `activeTasks` 读取状态
- [ ] 修改发送按钮 disabled 逻辑

**Verification:**
- [ ] 会话列表中正在生成的会话显示黑色"生成中"徽章和旋转 Loader2 图标
- [ ] 切换到另一个会话时，之前会话的徽章仍然显示
- [ ] 生成完成后徽章 3 秒后消失
- [ ] `cd frontend && npx tsc --noEmit` 无类型错误

**Commit:** `feat: replace global generating flag with activeTasks Map and add session status badges`

---

### Task 12: sendGenerate 改造

**Files:** `frontend/src/views/Sessions.vue`

**Steps:**
- [ ] 重写 `sendGenerate()` 函数：
  ```typescript
  async function sendGenerate() {
    if (!inputText.value.trim() && !attachments.value.length) return
    const sid = currentSessionId.value
    if (!sid || isSessionBusy(sid)) return

    const abortController = new AbortController()
    activeTasks.value.set(sid, {
      sessionId: sid,
      type: 'generate',
      status: 'running',
      progress: 0,
      total: imageCount.value,
      abortController,
    })

    let promptWithContext = inputText.value
    const referenceImages: string[] = []
    // ... 附件处理逻辑保持不变 ...

    const contextMessages = messages.value.slice(-10).map(m => ({
      role: m.role,
      content: m.content,
    }))

    try {
      await store.generate(sid, {
        prompt: promptWithContext,
        negative_prompt: negativePrompt.value,
        image_count: imageCount.value,
        image_size: noSizeLimit.value ? undefined : `${imageWidth.value}x${imageHeight.value}`,
        optimize_directions: selectedDirections.value.filter(d => d !== 'custom'),
        custom_optimize_instruction: customInstruction.value,
        reference_images: referenceImages.length ? referenceImages : undefined,
        context_messages: contextMessages,
      })
      inputText.value = ''
      negativePrompt.value = ''
      selectedImages.value = []
      attachments.value = []
    } catch (e: any) {
      dialog.showAlert('发送失败: ' + (e.message || '未知错误'))
    } finally {
      const task = activeTasks.value.get(sid)
      if (task) task.status = 'done'
      setTimeout(() => activeTasks.value.delete(sid), 3000)
      billingStore.fetchSummary()
    }
  }
  ```

**Verification:**
- [ ] 点击发送后，会话列表显示"生成中"徽章
- [ ] 生成期间切换到另一个会话，原会话徽章仍显示
- [ ] 在另一个空闲会话中可以正常发送新的生成请求
- [ ] 两个会话同时生成时，各自独立显示状态

**Commit:** `feat: refactor sendGenerate to use activeTasks for multi-session concurrency`

---

## Phase 3: 规划/优化增强

### Task 13: 后端补全 5 个优化方向 + custom + 多方向组合

**Files:** `backend/app/services/prompt_optimizer.py`

**Steps:**
- [ ] 在 `OPTIMIZATION_PROMPTS` 字典中新增 `color_adjustment` 和 `lighting_enhancement` 两个方向的 system prompt
- [ ] 新增 `CUSTOM_OPTIMIZATION_PROMPT` 常量，处理自定义优化指令
- [ ] 新增 `build_optimization_prompt()` 函数，支持多方向组合：
  - 单方向：直接使用对应 prompt
  - 多方向：组合所有方向的 prompt，要求 LLM 同时应用
  - 包含 custom：注入用户自定义指令
- [ ] 修改 `optimize_prompt()` 函数，使用 `build_optimization_prompt()` 替代直接查表

**Verification:**
- [ ] `POST /api/prompt/optimize` 传入 `direction="color_adjustment"` 不再回退到 detail_enhancement
- [ ] 传入 `direction="detail_enhancement,style_unification"` 时使用组合 prompt
- [ ] 传入 `direction="custom:make it more vivid"` 时使用 custom prompt

**Commit:** `feat: add color_adjustment and lighting_enhancement optimization directions with multi-direction support`

---

### Task 14: 流式优化 SSE 端点

**Files:** `backend/app/services/prompt_optimizer.py`, `backend/app/routers/prompt.py`

**Steps:**
- [ ] 在 `prompt_optimizer.py` 中新增 `optimize_prompt_stream()` 异步生成器函数：
  - 解析方向（支持多方向组合 + custom）
  - 使用 `build_optimization_prompt()` 构建 system prompt
  - 调用 `LLMClient.chat_stream()` 流式输出
  - 逐 token yield SSE 格式
  - 流结束后创建 BillingRecord
- [ ] 在 `prompt.py` 路由中新增端点：
  ```python
  @router.post("/optimize/stream")
  async def api_optimize_prompt_stream(data: PromptOptimizeRequest, db: AsyncSession = Depends(get_db)):
      return StreamingResponse(
          optimize_prompt_stream(db, data),
          media_type="text/event-stream",
      )
  ```

**Verification:**
- [ ] `curl -N -X POST http://localhost:8000/api/prompt/optimize/stream -H "Content-Type: application/json" -d '{"prompt":"a cat","direction":"detail_enhancement","llm_provider_id":"<id>"}'` 返回 SSE 流

**Commit:** `feat: add /api/prompt/optimize/stream SSE endpoint for streaming optimization`

---

### Task 15: 前端 API — optimizeStream + plan template API

**Files:** `frontend/src/api/prompt.ts`, `frontend/src/api/planTemplate.ts`（新建）

**Steps:**
- [ ] 在 `prompt.ts` 中新增 `optimizeStream` 方法（类似 `streamChat`，但调用 `/prompt/optimize/stream`）：
  ```typescript
  optimizeStream: async function* (
    prompt: string,
    direction: string,
    llmProviderId: string,
    sessionId: string | null = null,
    signal?: AbortSignal,
  ): AsyncGenerator<string, void, unknown> {
    const response = await fetch('/api/prompt/optimize/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt, direction, llm_provider_id: llmProviderId, session_id: sessionId }),
      signal,
    })
    // ... 同 streamChat 的 SSE 解析逻辑 ...
  },
  ```
- [ ] 新建 `planTemplate.ts`，实现规划模板 API：
  ```typescript
  import api from './client'
  import type { PlanTemplate } from '../types'

  export const planTemplateApi = {
    list: () => api.get<PlanTemplate[]>('/plan-templates'),
    get: (id: string) => api.get<PlanTemplate>(`/plan-templates/${id}`),
    create: (data: Partial<PlanTemplate>) => api.post<PlanTemplate>('/plan-templates', data),
    update: (id: string, data: Partial<PlanTemplate>) => api.put<PlanTemplate>(`/plan-templates/${id}`, data),
    delete: (id: string) => api.delete(`/plan-templates/${id}`),
    apply: (id: string, variables: Record<string, string>) => api.post<PlanTemplate>(`/plan-templates/${id}/apply`, { variables }),
  }
  ```

**Verification:**
- [ ] `cd frontend && npx tsc --noEmit` 无类型错误

**Commit:** `feat: add optimizeStream API and planTemplate API client`

---

### Task 16: doOptimize 改用流式优化端点

**Files:** `frontend/src/views/Sessions.vue`

**Steps:**
- [ ] 重写 `doOptimize()` 函数，改用 `promptApi.optimizeStream()` 替代手动构造 system prompt + `streamChat()`
- [ ] 删除手动构造的 `systemPrompt` 变量
- [ ] 保留流式输出和结果保存逻辑

**Verification:**
- [ ] 优化功能正常工作，流式输出优化结果
- [ ] 优化方向正确传递到后端（通过 SSE 端点）

**Commit:** `refactor: use optimizeStream API endpoint in doOptimize`

---

### Task 17: 动态规划系统提示词

**Files:** `frontend/src/views/Sessions.vue`

**Steps:**
- [ ] 修改 `doPlan()` 函数中的 system prompt，动态注入当前配置：
  ```typescript
  const optimizeDirs = selectedDirections.value.filter(d => d !== 'custom').join(', ') || '无'
  const hasRefs = attachments.value.some(a => a.type.startsWith('image/'))
  const strategyDesc = planStrategies.find(s => s.key === selectedPlanStrategy.value)?.desc || '并发生成'

  const systemPrompt = `你是一个AI图像生成任务规划师。根据用户的图像生成需求，将其分解为具体的子任务。

当前配置：
- 图像数量: ${imageCount.value}
- 图像尺寸: ${noSizeLimit.value ? '不限' : `${imageWidth.value}x${imageHeight.value}`}
- 优化方向: ${optimizeDirs}
- 参考图片: ${hasRefs ? '有' : '无'}
- 执行策略: ${strategyDesc}

对于每个子任务，请提供：
- prompt: 详细的图像生成提示词（英文，用于API调用）
- negative_prompt: 需要避免的元素
- description: 该步骤的中文说明
- image_count: 该步骤生成的图片数量（可选，默认为1）
- image_size: 该步骤的图片尺寸（可选，默认为${noSizeLimit.value ? '不限' : `${imageWidth.value}x${imageHeight.value}`}）

输出格式必须为JSON数组：
[
  {
    "prompt": "...",
    "negative_prompt": "...",
    "description": "...",
    "image_count": 1,
    "image_size": "${imageWidth.value}x${imageHeight.value}"
  }
]

规则：
1. prompt用英文撰写，要具体且描述性强
2. 包含风格、构图、光照和氛围细节
3. negative_prompt列出需要避免的常见问题
4. description用中文简要说明该步骤的目标
5. 将复杂需求分解为聚焦的子任务
6. ${selectedPlanStrategy.value === 'parallel' ? '各步骤应独立，可并发生成' : selectedPlanStrategy.value === 'iterative' ? '后续步骤应基于前一步结果进行优化' : '步骤按顺序执行'}
7. 只输出JSON数组，不要其他文字`
  ```

**Verification:**
- [ ] 生成规划时，system prompt 包含当前配置信息
- [ ] 不同策略选择生成不同风格的规划步骤

**Commit:** `feat: dynamic plan system prompt with current config injection`

---

### Task 18: 规划策略选择 + 步骤编辑增强

**Files:** `frontend/src/views/Sessions.vue`

**Steps:**
- [ ] 新增规划策略选项：
  ```typescript
  const planStrategies = [
    { key: 'parallel', label: '并发生成', desc: '所有步骤同时执行，互不依赖' },
    { key: 'sequential', label: '顺序执行', desc: '按步骤逐一执行，每步依赖前一步结果' },
    { key: 'iterative', label: '迭代优化', desc: '每步基于前一步结果优化，逐步精炼' },
  ]
  const selectedPlanStrategy = ref('parallel')
  ```
- [ ] 新增步骤操作函数：`moveStep()`, `duplicateStep()`, `insertStep()`, `removeStep()`
- [ ] 修改规划 Tab 模板，添加策略选择 radio 和步骤操作按钮
- [ ] 修改 `planSteps` 的类型为 `PlanStep[]`，支持 `image_count` 和 `image_size`

**Verification:**
- [ ] 规划 Tab 显示三种策略选项
- [ ] 步骤可以上移/下移/复制/插入/删除
- [ ] 每个步骤可以设置独立的 image_count 和 image_size

**Commit:** `feat: add plan strategy selection and enhanced step editing UI`

---

### Task 19: executePlan 并发执行 + 进度追踪

**Files:** `frontend/src/views/Sessions.vue`

**Steps:**
- [ ] 重写 `executePlan()` 函数，支持三种策略：
  - parallel：并发池执行（最多 3 步同时）
  - sequential：逐个 await
  - iterative：逐步 + 前一步结果作为 reference
- [ ] 集成 `activeTasks` 进度追踪
- [ ] 实现并发池调度函数 `executeConcurrent()`

**Verification:**
- [ ] parallel 策略：多步骤同时执行，进度实时更新
- [ ] sequential 策略：步骤逐一执行
- [ ] iterative 策略：每步完成后获取前一步图片作为参考

**Commit:** `feat: implement concurrent plan execution with strategy support and progress tracking`

---

### Task 20: Checkpoint 机制

**Files:** `frontend/src/views/Sessions.vue`

**Steps:**
- [ ] 新增 checkpoint 状态：
  ```typescript
  const planCheckpoint = ref<{ stepIndex: number; message: string; autoContinueSeconds: number } | null>(null)
  let planCheckpointResolve: (() => void) | null = null
  ```
- [ ] 在 `executePlan()` 中，步骤执行后检查 checkpoint
- [ ] 新增 `continuePlan()` 和 `abortPlan()` 函数
- [ ] 新增 checkpoint 覆盖层 UI

**Verification:**
- [ ] 带有 checkpoint 的步骤执行后暂停，显示提示信息
- [ ] 点击"继续执行"后继续后续步骤
- [ ] 点击"终止规划"后停止执行

**Commit:** `feat: add checkpoint mechanism for plan execution with manual intervention`

---

### Task 21: 优化消息"使用原始"按钮

**Files:** `frontend/src/views/Sessions.vue`

**Steps:**
- [ ] 在优化消息模板中，新增"使用原始"按钮：
  ```html
  <div class="optimization-actions">
    <button @click="applyOptimized(msg.metadata?.optimized)">使用优化</button>
    <button @click="applyOptimized(msg.metadata?.original)">使用原始</button>
  </div>
  ```

**Verification:**
- [ ] 优化消息显示两个按钮
- [ ] 点击"使用优化"将优化后的提示词填入输入框
- [ ] 点击"使用原始"将原始提示词填入输入框

**Commit:** `feat: add 'use original' button to optimization messages`

---

## Phase 4: 规划模板系统

### Task 22: PlanTemplate 数据模型 + 迁移

**Files:** `backend/app/models/plan_template.py`（新建）, `backend/app/database.py`

**Steps:**
- [ ] 创建 `plan_template.py`，定义 `PlanTemplate` 模型（id, name, description, strategy, steps JSON, variables JSON, is_builtin, created_at, updated_at）
- [ ] 在 `database.py` 的 `init_db()` 中确保 `Base.metadata.create_all` 会创建新表（自动处理）

**Verification:**
- [ ] 重启后端，检查 `plan_templates` 表是否创建
- [ ] `py -3.14 -c "from app.models.plan_template import PlanTemplate; print(PlanTemplate.__tablename__)"` 输出 `plan_templates`

**Commit:** `feat: add PlanTemplate SQLAlchemy model`

---

### Task 23: PlanTemplate Schema + Service + Router

**Files:** `backend/app/schemas/plan_template.py`（新建）, `backend/app/services/plan_template_service.py`（新建）, `backend/app/routers/plan_template.py`（新建）

**Steps:**
- [ ] 创建 Schema：`PlanTemplateCreate`, `PlanTemplateUpdate`, `PlanTemplateResponse`, `PlanTemplateApplyRequest`
- [ ] 创建 Service：`list_templates()`, `get_template()`, `create_template()`, `update_template()`, `delete_template()`, `apply_template()`
- [ ] 创建 Router：CRUD 端点 + `/apply` 端点
- [ ] 在 `main.py` 中注册路由：`app.include_router(plan_template.router)`

**Verification:**
- [ ] `GET /api/plan-templates` 返回空列表
- [ ] `POST /api/plan-templates` 可创建模板
- [ ] `POST /api/plan-templates/{id}/apply` 可应用模板变量替换

**Commit:** `feat: add PlanTemplate CRUD API with variable substitution`

---

### Task 24: 内置模板种子数据

**Files:** `backend/app/services/plan_template_service.py`

**Steps:**
- [ ] 在 `plan_template_service.py` 中新增 `seed_builtin_templates()` 函数，插入 4 个内置模板（产品展示套图、角色设计、四季风景、迭代精修）
- [ ] 在 `database.py` 的 `init_db()` 中调用 `seed_builtin_templates()`
- [ ] 使用 INSERT OR IGNORE 避免重复插入

**Verification:**
- [ ] 重启后端后，`GET /api/plan-templates` 返回 4 个内置模板
- [ ] 内置模板的 `is_builtin` 字段为 `true`

**Commit:** `feat: add 4 builtin plan templates with seed data`

---

### Task 25: 前端规划 Tab 模板集成

**Files:** `frontend/src/views/Sessions.vue`

**Steps:**
- [ ] 新增模板相关状态：
  ```typescript
  const planTemplates = ref<PlanTemplate[]>([])
  const selectedTemplateId = ref('')
  const templateVariableValues = ref<Record<string, string>>({})
  ```
- [ ] 新增模板加载、应用、保存函数
- [ ] 修改规划 Tab 模板，添加模板选择下拉框、变量填写区、保存为模板按钮
- [ ] 保存为模板使用侧边抽屉（遵循 UI 规范）

**Verification:**
- [ ] 规划 Tab 显示模板下拉框，可选择内置模板
- [ ] 选择模板后显示变量填写区
- [ ] 填写变量后点击"应用"加载步骤到编辑区
- [ ] 点击"保存为模板"弹出抽屉表单

**Commit:** `feat: integrate plan templates into planning tab with variable substitution`

---

### Task 26: 前端手动规划支持

**Files:** `frontend/src/views/Sessions.vue`

**Steps:**
- [ ] 在规划 Tab 中，当没有选择模板且未生成规划时，显示"手动添加步骤"按钮
- [ ] 点击后直接添加一个空步骤到 `planSteps`
- [ ] 用户可以不调用 LLM，直接手动编写步骤并执行

**Verification:**
- [ ] 不输入任何文字，直接点击"手动添加步骤"可添加空步骤
- [ ] 手动编写步骤后可直接执行

**Commit:** `feat: add manual plan step creation without LLM`

---

## 全局验证

### Task 27: 端到端测试

**Steps:**
- [ ] 创建两个会话，在会话 A 中触发图像生成
- [ ] 切换到会话 B，确认会话 A 仍显示"生成中"徽章
- [ ] 在会话 B 中触发另一个生成，确认两个会话同时生成
- [ ] 测试优化功能：选择多个方向，确认流式输出
- [ ] 测试规划功能：生成规划 → 编辑步骤 → 选择策略 → 执行
- [ ] 测试模板功能：选择内置模板 → 填变量 → 执行
- [ ] 测试 checkpoint：使用角色设计模板，确认在概念设计步骤后暂停
- [ ] 检查 SSE 事件流在浏览器断网重连后恢复正常

**Verification:**
- [ ] 所有测试场景通过
- [ ] 无控制台错误
- [ ] `cd frontend && npx tsc --noEmit` 无类型错误

**Commit:** `test: end-to-end verification of architecture upgrade`
