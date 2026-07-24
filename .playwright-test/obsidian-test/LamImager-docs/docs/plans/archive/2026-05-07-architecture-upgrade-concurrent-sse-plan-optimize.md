# LamImager 架构升级设计：多会话并发 + SSE 事件中心 + 规划优化增强

> 日期: 2026-05-07
> 状态: 已批准

## 目标

1. 支持用户在多个会话窗口同时进行生成/规划/优化任务，互不阻塞
2. 会话栏实时显示各会话状态（生成中/优化中/规划中/空闲/错误）
3. 补全优化方向、统一优化路径、增强规划功能（策略选择/步骤编辑/模板系统/checkpoint）

## 方案选择

选定 **方案 A：SSE 事件中心架构**，理由：
- 复用项目已有 SSE 流式聊天能力，不引入新技术栈
- 单一 EventSource 连接推送所有会话状态事件
- SSE 天然支持自动重连，断线恢复简单
- 不过度设计（WebSocket 在本项目场景下属于杀鸡用牛刀）

---

## 第一章：数据库层升级

### 1.1 Session 模型新增 `status` 字段

**文件**: `backend/app/models/session.py`

```python
class SessionStatus(str, enum.Enum):
    idle = "idle"
    generating = "generating"
    optimizing = "optimizing"
    planning = "planning"
    error = "error"

class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="新会话")
    status: Mapped[str] = mapped_column(String(20), default="idle", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
    messages = relationship("Message", back_populates="session", cascade="all, delete-orphan")
    billing_records = relationship("BillingRecord", back_populates="session")
```

### 1.2 数据迁移

**文件**: `backend/app/database.py` — `init_db()` 新增

对齐现有 `PRAGMA table_info` 迁移模式：

```python
result = await conn.execute(text("PRAGMA table_info('sessions')"))
columns = [row[1] for row in result.fetchall()]
if "status" not in columns:
    await conn.execute(text("ALTER TABLE sessions ADD COLUMN status VARCHAR(20) DEFAULT 'idle' NOT NULL"))
```

启动时重置非 idle 状态（防止崩溃后状态卡死）：

```python
await conn.execute(text("UPDATE sessions SET status = 'idle' WHERE status != 'idle'"))
```

### 1.3 修复 N+1 查询

**文件**: `backend/app/services/session_manager.py` — `list_sessions()`

当前 3N+1 次查询改为 1 次 JOIN 查询，返回类型不变（`list[dict]`）：

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

---

## 第二章：SSE 事件中心 + TaskManager

### 2.1 架构总览

```
┌─────────────────────────────────────────────────┐
│                  TaskManager (单例)                │
│  _tasks: dict[session_id, TaskInfo]              │
│  _queues: dict[queue_id, asyncio.Queue]          │
│  _semaphore: asyncio.Semaphore(5)                │
└────────┬──────────────────┬─────────────────────┘
         │                  │
    ┌────▼────┐      ┌──────▼──────┐
    │ 生成服务  │      │  SSE 端点    │
    │ 更新状态  │      │ 读取队列    │
    │ 写入事件  │      │ 推送客户端   │
    └─────────┘      └─────────────┘
```

### 2.2 TaskManager

**新文件**: `backend/app/services/task_manager.py`

```python
import asyncio
import json
from dataclasses import dataclass
from enum import StrEnum


class TaskStatus(StrEnum):
    IDLE = "idle"
    GENERATING = "generating"
    OPTIMIZING = "optimizing"
    PLANNING = "planning"
    ERROR = "error"


@dataclass
class TaskInfo:
    session_id: str
    status: TaskStatus
    progress: int = 0
    total: int = 0
    message: str = ""


class TaskManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._tasks: dict[str, TaskInfo] = {}
        self._queues: dict[str, asyncio.Queue] = {}
        self._queue_counter = 0
        self._semaphore = asyncio.Semaphore(5)

    async def acquire(self):
        await self._semaphore.acquire()

    def release(self):
        self._semaphore.release()

    def update_task(self, session_id: str, status: TaskStatus, progress: int = 0, total: int = 0, message: str = ""):
        self._tasks[session_id] = TaskInfo(
            session_id=session_id,
            status=status,
            progress=progress,
            total=total,
            message=message,
        )
        if status == TaskStatus.IDLE:
            del self._tasks[session_id]
        self._broadcast({
            "type": "task_update",
            "data": {
                "session_id": session_id,
                "status": str(status),
                "progress": progress,
                "total": total,
                "message": message,
            },
        })

    def get_task(self, session_id: str) -> TaskInfo | None:
        return self._tasks.get(session_id)

    def get_all_tasks(self) -> dict[str, dict]:
        return {sid: {"status": str(t.status), "progress": t.progress, "total": t.total, "message": t.message} for sid, t in self._tasks.items()}

    async def subscribe(self) -> tuple[str, asyncio.Queue]:
        self._queue_counter += 1
        queue_id = f"q_{self._queue_counter}"
        queue = asyncio.Queue()
        self._queues[queue_id] = queue
        return queue_id, queue

    def unsubscribe(self, queue_id: str):
        self._queues.pop(queue_id, None)

    def _broadcast(self, event: dict):
        for queue in self._queues.values():
            queue.put_nowait(event)
```

### 2.3 SSE 端点

**文件**: `backend/app/routers/session.py` 新增

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

### 2.4 事件格式

```json
{"type": "task_update", "data": {"session_id": "xxx", "status": "generating", "progress": 2, "total": 4, "message": "生成中 2/4"}}
{"type": "snapshot", "data": {"tasks": {"sid1": {"status": "generating", ...}}}}
{"type": "ping", "data": {}}
```

### 2.5 与现有 SSE 的关系

`/api/prompt/stream` 保持不变，继续用于流式文本输出。`/api/sessions/events` 是正交的全局事件通道。

---

## 第三章：前端多会话并发架构

### 3.1 核心改造：Map<TaskHandle> 替代全局 generating

**文件**: `frontend/src/views/Sessions.vue`

```typescript
interface TaskHandle {
  sessionId: string
  type: 'generate' | 'optimize' | 'plan'
  status: 'running' | 'done' | 'error'
  progress: number
  total: number
  abortController: AbortController | null
}

const activeTasks = ref<Map<string, TaskHandle>>(new Map())

function isSessionBusy(sessionId: string): boolean {
  const task = activeTasks.value.get(sessionId)
  return task?.status === 'running'
}
```

### 3.2 SSE 事件监听器

**新文件**: `frontend/src/composables/useSessionEvents.ts`

```typescript
export function useSessionEvents(
  onTaskUpdate: (event: TaskUpdateEvent) => void,
  onSnapshot: (tasks: Record<string, TaskInfo>) => void,
) {
  let eventSource: EventSource | null = null

  function connect() {
    eventSource = new EventSource('/api/sessions/events')
    eventSource.addEventListener('task_update', (e) => {
      onTaskUpdate(JSON.parse(e.data))
    })
    eventSource.addEventListener('snapshot', (e) => {
      onSnapshot(JSON.parse(e.data))
    })
    eventSource.onerror = () => {
      // EventSource 内置自动重连
    }
  }

  function disconnect() {
    eventSource?.close()
  }

  return { connect, disconnect }
}
```

### 3.3 Session Store 改造

**文件**: `frontend/src/stores/session.ts`

- `SessionInfo` 新增 `status` 字段
- `generate()` 接受 `sessionId` 参数（不再绑定 `currentSessionId`）
- 仅当生成的是当前会话时才刷新消息

### 3.4 sendGenerate 改造

- 使用 `activeTasks` Map 追踪任务
- 不再使用全局 `generating` / `generatingSessionId`
- 任务完成后保留 3 秒显示完成状态

### 3.5 executePlan 并发改造

- 并发池执行（最多 3 步同时）
- 实时更新 `activeTasks` 进度
- 支持三种策略：parallel / sequential / iterative

### 3.6 会话列表 UI 状态显示

```html
<div class="session-item" :class="{ active: s.id === currentSessionId }">
  <div class="session-title-row">
    <span class="session-title">{{ s.title }}</span>
    <span v-if="getSessionStatus(s.id) === 'generating'" class="status-badge generating">
      <Loader2 class="icon-spin" :size="12" /> 生成中
    </span>
    <span v-else-if="getSessionStatus(s.id) === 'optimizing'" class="status-badge optimizing">
      <Loader2 class="icon-spin" :size="12" /> 优化中
    </span>
    <span v-else-if="getSessionStatus(s.id) === 'planning'" class="status-badge planning">
      <Loader2 class="icon-spin" :size="12" /> 规划中
    </span>
    <span v-else-if="getSessionStatus(s.id) === 'error'" class="status-badge error">
      <AlertCircle :size="12" /> 错误
    </span>
  </div>
  <div class="session-meta">
    <span>{{ s.cost > 0 ? '¥' + s.cost.toFixed(2) : '¥0.00' }}</span>
    <span>{{ formatTokens(s.tokens) }}</span>
    <span v-if="getTaskProgress(s.id)" class="task-progress">{{ getTaskProgress(s.id) }}</span>
  </div>
</div>
```

CSS 状态徽章遵循黑白灰调色板：

```css
.status-badge { display: inline-flex; align-items: center; gap: 4px; font-size: 11px; padding: 1px 6px; border-radius: 3px; white-space: nowrap; }
.status-badge.generating { background: #000; color: #fff; }
.status-badge.optimizing, .status-badge.planning { background: #E5E5E5; color: #000; }
.status-badge.error { background: #000; color: #fff; }
.icon-spin { animation: spin 1s linear infinite; }
@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
```

### 3.7 聊天区生成动画改造

从 `activeTasks` 读取状态，而非全局 `generating`。

### 3.8 发送按钮逻辑

```html
<button :disabled="!inputText.trim() || isSessionBusy(currentSessionId)">
  {{ isSessionBusy(currentSessionId) ? '任务进行中...' : '发送' }}
</button>
```

---

## 第四章：规划/优化功能增强

### 4.1 统一优化路径

**问题**: 前端 `doOptimize()` 绕过后端 `optimize_prompt()`，使用自构的通用 system prompt，导致两条优化路径结果不一致。

**方案**: 新增 `POST /api/prompt/optimize/stream` SSE 端点，使用后端的 `OPTIMIZATION_PROMPTS`。

**文件**: `backend/app/routers/prompt.py` 新增

```python
@router.post("/optimize/stream")
async def api_optimize_prompt_stream(data: PromptOptimizeRequest, db: AsyncSession = Depends(get_db)):
    return StreamingResponse(
        optimize_prompt_stream(db, data),
        media_type="text/event-stream",
    )
```

前端 `doOptimize()` 改为调用此端点。

### 4.2 补全 5 个优化方向 + custom + 多方向组合

**文件**: `backend/app/services/prompt_optimizer.py`

新增 `color_adjustment` 和 `lighting_enhancement` 方向的 system prompt。

新增 `CUSTOM_OPTIMIZATION_PROMPT` 处理自定义方向。

新增 `build_optimization_prompt()` 函数，支持多方向组合：
- 单方向：直接使用对应 prompt
- 多方向：组合所有方向的 prompt，要求 LLM 同时应用
- custom：注入用户自定义指令

### 4.3 动态规划系统提示词

规划 system prompt 动态构建，注入当前配置信息：

```
当前配置：
- 图像数量: {image_count}
- 图像尺寸: {image_size}
- 优化方向: {optimize_directions}
- 参考图片: {has_references}
- 执行策略: {strategy}
```

### 4.4 规划步骤扩展

```typescript
interface PlanStep {
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
  condition?: {
    type: 'manual_select' | 'auto_quality' | 'none'
    on_pass?: { reference_indices: number[] }
    on_fail?: { retry: boolean; max_retries: number }
  }
}
```

### 4.5 规划策略

```typescript
const planStrategies = [
  { key: 'parallel', label: '并发生成', desc: '所有步骤同时执行，互不依赖' },
  { key: 'sequential', label: '顺序执行', desc: '按步骤逐一执行，每步依赖前一步结果' },
  { key: 'iterative', label: '迭代优化', desc: '每步基于前一步结果优化，逐步精炼' },
]
```

### 4.6 步骤编辑增强

- 上移/下移排序
- 复制步骤
- 插入步骤
- 删除步骤
- 每步可设置 image_count 和 image_size

### 4.7 Checkpoint 机制

执行到标记了 checkpoint 的步骤时暂停，等待用户确认后继续。

UI 使用覆盖层提示用户操作。

### 4.8 优化消息可追溯

优化消息增加"使用原始"按钮，用户可选择使用优化前或优化后的提示词。

### 4.9 规划模板系统

> 注意：模板复用需要慎重设计，可先做基础版本后续迭代增强。

#### 三种进入规划的方式（模板为可选）

1. **自由规划**（默认）：直接输入需求 → LLM 生成步骤 → 编辑 → 执行
2. **模板规划**：选择模板 → 填变量 → 加载步骤 → 编辑 → 执行
3. **手动规划**：不调用 LLM，直接手动添加步骤 → 执行

#### 模板数据模型

**新文件**: `backend/app/models/plan_template.py`

```python
class PlanTemplate(Base):
    __tablename__ = "plan_templates"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    strategy: Mapped[str] = mapped_column(String(20), default="parallel")
    steps: Mapped[dict] = mapped_column(JSON, default=list)
    variables: Mapped[dict] = mapped_column(JSON, default=dict)
    is_builtin: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
```

#### 模板变量系统

```typescript
interface TemplateVariable {
  key: string
  type: 'string' | 'select' | 'number'
  label: string
  default: string
  options?: string[]
  required?: boolean
}
```

步骤中使用 `{{variable_key}}` 占位符，应用模板时替换为实际值。

#### 三种模板制作方式

1. **从现有规划保存**：编辑好步骤后点"保存为模板"，系统自动扫描 `{{xxx}}` 变量和重复短语
2. **LLM 辅助生成**：描述需求 → LLM 生成模板结构
3. **手动创建**：在规划 Tab 中直接创建

#### 内置模板（4 个）

| 模板名 | 策略 | 步骤数 | 变量 |
|--------|------|--------|------|
| 产品展示套图 | parallel | 4 | product, style, background |
| 角色设计 | iterative | 3 | character, art_style, pose |
| 四季风景 | parallel | 4 | scene, art_style |
| 迭代精修 | iterative | 3 | subject, style |

#### 模板 CRUD API

```
GET    /api/plan-templates
POST   /api/plan-templates
GET    /api/plan-templates/{id}
PUT    /api/plan-templates/{id}
DELETE /api/plan-templates/{id}
POST   /api/plan-templates/{id}/apply
```

---

## 第五章：变更清单

### 新增文件

| 文件 | 用途 |
|------|------|
| `backend/app/services/task_manager.py` | TaskManager 单例 |
| `backend/app/models/plan_template.py` | PlanTemplate 数据模型 |
| `backend/app/routers/plan_template.py` | 规划模板 CRUD API |
| `backend/app/schemas/plan_template.py` | 规划模板 Schema |
| `backend/app/services/plan_template_service.py` | 规划模板服务 |
| `frontend/src/composables/useSessionEvents.ts` | SSE 事件监听 |

### 修改文件

| 文件 | 变更 |
|------|------|
| `backend/app/models/session.py` | 新增 status 字段 + SessionStatus 枚举 |
| `backend/app/database.py` | 新增迁移 + 启动状态重置 |
| `backend/app/services/session_manager.py` | N+1 修复 + status 字段返回 |
| `backend/app/services/generate_service.py` | 集成 TaskManager 状态更新 |
| `backend/app/services/prompt_optimizer.py` | 补全 5 方向 + custom + 多方向组合 + 流式优化端点 |
| `backend/app/routers/session.py` | 新增 /events SSE 端点 |
| `backend/app/routers/prompt.py` | 新增 /optimize/stream 端点 |
| `backend/app/schemas/session.py` | SessionInfo 新增 status + GenerateRequest 新增 plan_strategy |
| `backend/app/main.py` | 注册新路由 |
| `frontend/src/types/index.ts` | SessionInfo 新增 status + PlanStep 扩展 + TaskHandle |
| `frontend/src/stores/session.ts` | generate() 接受 sessionId 参数 + status 字段 |
| `frontend/src/api/session.ts` | 新增 events SSE 连接 |
| `frontend/src/api/prompt.ts` | 新增 optimizeStream 方法 |
| `frontend/src/views/Sessions.vue` | 全面改造：activeTasks + 状态徽章 + 规划增强 + checkpoint |
| `frontend/src/views/Settings.vue` | 新增默认并发数配置 |

### 实施顺序

```
Phase 1: 基础设施（数据库 + TaskManager + SSE）
  ├─ 1.1 Session 模型新增 status + 迁移
  ├─ 1.2 TaskManager 实现
  ├─ 1.3 SSE /api/sessions/events 端点
  └─ 1.4 N+1 查询修复

Phase 2: 前端并发支持
  ├─ 2.1 useSessionEvents composable
  ├─ 2.2 Session Store 改造
  ├─ 2.3 Sessions.vue activeTasks + 状态徽章
  └─ 2.4 executePlan 并发池

Phase 3: 规划/优化增强
  ├─ 3.1 后端补全 5 方向 + custom + 多方向组合
  ├─ 3.2 流式优化 SSE 端点
  ├─ 3.3 动态规划系统提示词
  ├─ 3.4 规划步骤扩展 + 步骤编辑 UI
  ├─ 3.5 规划策略选择
  └─ 3.6 Checkpoint 机制

Phase 4: 规划模板（慎重设计，可后续迭代）
  ├─ 4.1 PlanTemplate 数据模型 + 迁移
  ├─ 4.2 规划模板 CRUD API
  ├─ 4.3 内置模板
  ├─ 4.4 变量替换系统
  └─ 4.5 前端模板 UI
```

### 风险与缓解

| 风险 | 缓解措施 |
|------|---------|
| SQLite 并发写入限制 | asyncio.Semaphore(5) 限流 + WAL 模式 |
| SSE 连接断开 | EventSource 内置自动重连 + snapshot 事件恢复状态 |
| 多会话并发时计费混乱 | BillingRecord 始终关联 session_id |
| 规划模板变量注入安全 | 仅支持 {{variable}} 占位符，不执行代码 |
| 前端状态复杂度增加 | activeTasks Map 集中管理，SSE 事件驱动更新 |
