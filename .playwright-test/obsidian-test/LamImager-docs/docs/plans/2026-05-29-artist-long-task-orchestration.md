# Artist 长任务编排技术设计

> **状态:** 设计阶段 | **日期:** 2026-05-29 | **分支:** `complextask`

---

## 1. 实际问题

### 1.1 当前限制

Artist 模式目前只支持**单轮交互**：用户发一条消息 → LLM 返回一个 `ArtistTurn`（含 message + actions）→ 执行 actions → 返回结果 → 等待下一条用户消息。 这意味着：

1. **无法处理批量生成请求**：用户说「画50张不同风格的猫」，Artist 只有一个 turn，无法自动拆分为多轮执行。
2. **长任务无进度感知**：即使通过 `generate_pack` 生成 6 张，前端也只有一个 `artist_image_ready` 流。超过 6 张的请求无法处理。
3. **无法暂停/恢复**：生图途中如果网络中断或用户关闭页面，任务状态丢失。
4. **无超时/取消机制**：后端 `asyncio.create_task` 启动后没有超时控制，长时间卡住时用户只能刷新页面。
5. **编排能力弱**：Artist 的 `ArtistTurn` 是平的 action 列表，没有嵌套的计划（plan）层。无法表达「先画锚点→审核→再画变体→再精修」这种多阶段流程。
6. **与 Agent 图割裂**：Agent 模式有完整的 9-node 图（planner → executor → critic → decision 循环），但 Artist 模式完全不走这个流程。

### 1.2 用户痛点

| 场景 | 痛点 |
|------|------|
| 用户想批量生成一套表情包（16 张） | 只能一次 6 张，需要多次对话 |
| 用户想生成一个漫画分镜（12 格） | 无法在一个请求中表达分镜需求 |
| 用户说「画一套塔罗牌」 | 22 张大阿尔卡纳，需要多次请求 |
| 用户想迭代精修到满意 | 当前只能手动一次次 refine |
| 用户启动大批量生成后离开 | 回来不知道进度、不知道哪些成功了 |

---

## 2. 现有代码盘点

### 2.1 核心模块（已有，无需大改）

| 模块 | 路径 | 关键能力 | 复用程度 |
|------|------|---------|---------|
| `ArtistRuntime` | `core/artist/runtime.py` | handle_turn 单轮驱动 | **核心扩展点** |
| `ArtistSessionState` | `core/artist/schemas.py` | 会话状态（phase/head/last_head_url） | **需扩展** |
| `ArtistAction` | `core/artist/schemas.py` | 14 种 action type | 新增 2-3 种 |
| `ExecutionEngine` | `services/executors/engine.py` | 单步/并行/分组执行 | **直接复用** |
| `ExecutionPlan` | `schemas/execution.py` | 步骤序列化 + 依赖关系 | **直接复用** |
| `PlanningContext` | `schemas/planning.py` | 上下文组装 + token 预算 | **直接复用** |
| `generate_images_core` | `services/generate_service.py` | 三层降级生图 | **直接复用** |
| `TaskManager` | `services/task_manager.py` | SSE 发布/订阅 + checkpoint | **直接复用** |
| Agent 9-node 图 | `core/agent/graph.py` | planner → executor → critic → decision | **桥接复用** |
| `artist_service.py` | `services/artist_service.py` | artist_orchestrate + event_publish | **需扩展** |
| `lineage_tree` | `schemas/lineage.py` | DAG 节点/分支管理 | **直接复用** |
| SSE 事件系统 | `core/artist/events.py` | 15 种 artist_* 事件 | 新增 5-6 种 |

### 2.2 前端模块（已有）

| 模块 | 路径 | 关键能力 |
|------|------|---------|
| `sessionStore` | `stores/session.ts` | ArtistStreamState + 7 个 handler |
| `MessageList` | `components/session/MessageList.vue` | Artist 流式渲染 |
| `ArtistImageMessageCard` | `components/session/ArtistImageMessageCard.vue` | 图片卡片 |
| `GeneratingIndicator` | `components/session/GeneratingIndicator.vue` | 加载态 |
| SSE 连接 | `composables/useSessionEvents.ts` | 断线重连 + 事件路由 |

### 2.3 关键数据流（当前）

```
用户消息 → generate_service._run_artist_background()
  → artist_orchestrate() → ArtistRuntime.handle_turn()
    → LLM 调用 → parse_artist_turn → ArtistTurn{actions}
    → 分离 gen/non-gen action
    → gen action → build_plan_steps → ExecutionPlan(单轮)
    → ExecutionEngine.run_all() → generate_images_core
    → _trace_to_artifacts → ArtistArtifact[]
    → SSE: artist_turn_started → reply_delta → action_started → image_ready → turn_done
  → 保存消息 → 刷新 lineage → 返回
```

**瓶颈点**：`ArtistTurn` 是扁平 action 列表，`ExecutionPlan` 只在本 turn 内生效，没有跨 turn 的调度器。

---

## 3. 功能增删表

### 3.1 新增功能

| 编号 | 功能 | 优先级 | 说明 |
|------|------|--------|------|
| F1 | **TaskOrchestrator** | P0 | 长任务调度器，管理任务生命周期 |
| F2 | **LongTaskState** | P0 | 长任务状态模型（plan/queue/progress/results） |
| F3 | `plan_complex_task` action | P1 | Artist LLM 可产出多阶段执行计划 |
| F4 | `delegate_to_agent` action | P1 | Artist 将复杂子任务委托给 Agent 图 |
| F5 | `long_task_progress` SSE 事件 | P0 | 长任务进度实时推送 |
| F6 | `long_task_card` 前端组件 | P0 | 进度卡片 UI（步骤列表 + 完成状态） |
| F7 | 任务暂停/恢复/取消 | P1 | TaskManager 扩展 + `cancel_long_task` API |
| F8 | 任务超时控制 | P2 | 单步超时 + 总超时配置 |
| F9 | Skill 自进化记录 | P2 | 成功任务 → 提取 prompt pattern → 更新 Skill |
| F10 | 编排-工具-动作三层抽象 | P1 | 代码层清晰分层，LLM prompt 注入分层语义 |

### 3.2 修改功能

| 编号 | 功能 | 改动范围 | 说明 |
|------|------|---------|------|
| M1 | `ArtistRuntime.handle_turn` | `runtime.py` | 支持 `long_task` 模式分支 |
| M2 | `ArtistSessionState` | `schemas.py` | 新增 `active_long_task_id`、`task_queue` 字段 |
| M3 | `ArtistAction` | `schemas.py` | 新增 `plan_complex_task`、`delegate_to_agent` |
| M4 | `artist_service.py` | `artist_service.py` | 支持 orchestrator 回调注入 |
| M5 | `generate_service.py` | `generate_service.py` | 支持长任务后台执行 + 状态查询 API |
| M6 | `task_manager.py` | `task_manager.py` | 扩展 checkpoint 支持长任务步骤级暂停 |
| M7 | 前端 `sessionStore` | `session.ts` | 新增 `LongTaskState` + handler |
| M8 | 前端 `MessageList` | `MessageList.vue` | 渲染 `LongTaskCard` |

### 3.3 删除/废弃

无。所有新功能在现有架构上增量添加，不破坏现有路径。

---

## 4. 设计目的

### 4.1 核心目标

让 Artist 从「单轮响应式助手」进化为「多轮编排式创作伙伴」，能够：

1. **理解复杂创作意图**：自动将「画一套塔罗牌」「生成漫画分镜」「批量出图50张」拆解为多步骤执行计划。
2. **管理长任务生命周期**：启动→进度→暂停→恢复→取消→完成，全程可控。
3. **保持 Artist 人格一致性**：不变成冷冰冰的 Agent 模式——Artist 仍然聊天、吐槽、给建议，只是在「干活」时转入编排模式。

### 4.2 设计原则

| 原则 | 说明 |
|------|------|
| **渐进增强** | 简单请求走原路径，只有复杂请求才触发编排 |
| **Persona 穿透** | 编排过程中的消息仍保持 Artist 语气 |
| **可观测** | 每个步骤状态实时可见 |
| **可中断** | 任一步骤可暂停/恢复，不丢进度 |
| **向后兼容** | 现有单 turn 流程零改动 |

---

## 5. 架构设计

### 5.1 总体架构

```
┌─────────────┐
│  用户消息    │
└──────┬──────┘
       ▼
┌──────────────────┐
│  ArtistRuntime   │  ← 入口不变
│  handle_turn()   │
└──────┬───────────┘
       │
       ├── 简单请求（无 complex plan）→ 原路径（不变）
       │
       └── 复杂请求（有 plan_complex_task）→ 新路径
              │
              ▼
       ┌──────────────────────┐
       │   TaskOrchestrator   │  ← 新增核心
       │   - 解析 ExecutionPlan │
       │   - 步骤调度          │
       │   - 进度追踪          │
       │   - 暂停/恢复         │
       │   - delegate to Agent │
       └──────┬───────────────┘
              │
              ├── 生图步骤 → ExecutionEngine → generate_images_core
              ├── 审核步骤 → critic_node（复用 Agent 图 critic）
              ├── 精修步骤 → ExecutionEngine（带 reference_step_indices）
              └── 委托步骤 → Agent 图（完整 9-node）
```

### 5.2 TaskOrchestrator 设计

```python
# 新文件: backend/app/services/executors/orchestrator.py

class TaskOrchestrator:
    """长任务编排器"""

    def __init__(self, deps: OrchestratorDeps): ...

    # --- 生命周期 ---
    async def start(self, plan: ExecutionPlan, context: PlanningContext) -> str:
        """启动长任务，返回 task_run_id"""
        ...

    async def resume(self, task_run_id: str) -> None:
        """恢复暂停的任务"""
        ...

    async def cancel(self, task_run_id: str) -> None:
        """取消任务"""
        ...

    # --- 内部 ---
    async def _run(self, task_run_id: str) -> ExecutionTrace:
        """执行步骤循环（内部协程）"""
        ...

    async def _step(self, step: PlanStep, trace: StepTrace) -> StepTrace:
        """执行单步骤（复用 ExecutionEngine.step）"""
        ...

    async def _critic_step(self, artifacts: list[dict]) -> list[dict]:
        """审核步骤（复用 critic_node 逻辑）"""
        ...

    async def _delegate_step(self, step: PlanStep) -> ExecutionTrace:
        """委托给 Agent 图执行"""
        ...
```

### 5.3 触发条件判断

Artist LLM 在解析用户意图时，满足以下任一条件则产出 `plan_complex_task` action：

| 条件 | 判定逻辑 |
|------|---------|
| 用户明确要求批量 | 「画N张」且 N > pack_count (默认 6) |
| 用户要求多阶段 | 「先画A再画B然后精修」 |
| 用户要求分镜/系列 | 「漫画分镜」「一套表情包」「塔罗牌」 |
| 用户要求审核+修改 | 「画完给我看看再改」 |

**不触发条件**：简单的「画一只猫」「把这张图变亮」仍然走原单 turn 路径。

---

## 6. 交互流程

### 6.1 长任务完整生命周期

```
用户: "画一套 12 张的星座表情包"
     │
     ▼
Artist LLM 解析 → plan_complex_task action
     │
     ▼
TaskOrchestrator.start()
     ├── 创建 LongTaskRun
     ├── SSE: long_task_created { task_run_id, total_steps: 12, name: "星座表情包" }
     │
     ▼
循环执行 12 个步骤:
     │
     ├── Step 1: 白羊座
     │   ├── SSE: long_task_step_started { step: 1, name: "白羊座" }
     │   ├── generate_images_core(...)
     │   ├── SSE: long_task_step_completed { step: 1, artifact_url: "..." }
     │   └── SSE: long_task_progress { completed: 1, total: 12 }
     │
     ├── Step 2: 金牛座 ... (同上)
     │
     ├── ... Step 3-12 ...
     │
     └── 全部完成后:
         ├── SSE: long_task_completed { task_run_id, total_artifacts: 12 }
         └── 保存 Artist 消息（含所有 artifacts metadata）
```

### 6.2 暂停/恢复

```
用户: "暂停一下" 或 点击暂停按钮
     │
     ▼
POST /api/sessions/{sid}/long-task/{run_id}/pause
     │
     ▼
TaskOrchestrator.pause(task_run_id)
     ├── 等待当前步骤完成（不中断生图 API 调用）
     ├── SSE: long_task_paused { task_run_id, completed: 5, total: 12 }
     └── 持久化当前进度到 LongTaskRun

用户: "继续"
     │
     ▼
POST /api/sessions/{sid}/long-task/{run_id}/resume
     │
     ▼
TaskOrchestrator.resume(task_run_id)
     ├── 从 DB 恢复 LongTaskRun
     ├── SSE: long_task_resumed { task_run_id }
     └── 从暂停点继续执行
```

### 6.3 委托 Agent 图

```
Artist LLM: "这个需求太复杂，让我用 Agent 模式来处理"
     │
     ▼
delegate_to_agent action { sub_prompt: "...", strategy_hint: "radiate" }
     │
     ▼
TaskOrchestrator._delegate_step()
     ├── 构建 AgentState
     ├── 调用 _run_agent_mode_graph()  ← 复用现有 9-node 图
     ├── 收集 Agent 产出的 artifacts
     ├── SSE: long_task_step_delegated { step, sub_task_id, status }
     └── 将 Agent 产物注入当前步骤的 artifacts
```

### 6.4 错误恢复

```
某步骤失败:
     ├── 重试（最多 3 次）
     ├── 重试 3 次后仍失败:
     │   ├── SSE: long_task_step_failed { step, error }
     │   ├── 标记步骤为 failed
     │   └── 询问用户: long_task_checkpoint { step, action: "skip/retry/abort" }
     │
     └── 用户选 skip → 继续下一步
         用户选 retry → 再试 3 次
         用户选 abort → 终止任务，已完成的保留
```

---

## 7. 数据模型

### 7.1 新增模型（Python/Pydantic）

```python
# backend/app/schemas/long_task.py

from pydantic import BaseModel, ConfigDict
from datetime import datetime

class LongTaskStep(BaseModel):
    """长任务中的单个步骤"""
    model_config = ConfigDict(from_attributes=True)

    index: int
    name: str                          # 步骤名称
    prompt: str                        # 生图提示词
    status: str = "pending"            # pending/running/completed/failed/skipped
    artifact_urls: list[str] = []      # 产出图片 URL
    artifact_type: str = "pack"        # artifact 类型
    reference_step_indices: list[int] = []  # 依赖的步骤索引
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None
    metadata: dict = {}                # 扩展数据


class LongTaskPlan(BaseModel):
    """长任务执行计划"""
    model_config = ConfigDict(from_attributes=True)

    task_run_id: str                   # UUID
    session_id: str
    name: str                          # 任务名称（如"星座表情包"）
    strategy: str                      # single/parallel/iterative/radiate
    total_steps: int
    steps: list[LongTaskStep]
    status: str = "created"            # created/running/paused/completed/failed/cancelled
    completed_steps: int = 0
    failed_steps: int = 0
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    plan_meta: dict = {}               # planner 产出的元数据


class LongTaskRun(BaseModel):
    """长任务运行时状态（持久化到 DB）"""
    model_config = ConfigDict(from_attributes=True)

    task_run_id: str
    session_id: str
    plan: LongTaskPlan
    current_step_index: int = 0
    status: str = "created"            # created/running/paused/completed/failed/cancelled
    artifacts: list[dict] = []         # 所有已产出 artifacts
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0
    created_at: str
    updated_at: str
```

### 7.2 DB 表（新增 SQLAlchemy 模型）

```python
# backend/app/models/long_task.py

class LongTaskRunModel(Base):
    __tablename__ = "long_task_runs"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=False)
    name = Column(String(200), nullable=False)
    plan_json = Column(JSON, nullable=False)      # LongTaskPlan 序列化
    current_step = Column(Integer, default=0)
    status = Column(String(20), default="created")
    artifacts_json = Column(JSON, default=list)
    tokens_in = Column(Integer, default=0)
    tokens_out = Column(Integer, default=0)
    cost = Column(Numeric(10, 6), default=0)
    created_at = Column(DateTime, default=now)
    updated_at = Column(DateTime, default=now, onupdate=now)
```

### 7.3 ArtistAction 扩展

```python
# 在 ArtistAction 中新增 2 种 action type:

# 1. plan_complex_task — Artist 产出多步骤计划
ArtistAction(
    type="plan_complex_task",
    message="好的，我来画一套 12 张的星座表情包，逐个星座来～",
    series_prompts=[
        {"name": "白羊座", "prompt": "Aries zodiac emoticon, cute chibi style..."},
        {"name": "金牛座", "prompt": "Taurus zodiac emoticon, cute chibi style..."},
        # ... 12 个
    ],
    series_style_lock={
        "style": "cute chibi emoticon",
        "color": "pastel",
        "size": "512x512"
    },
    image_count=1  # 每个子 prompt 生成 1 张
)

# 2. delegate_to_agent — 委托子任务给 Agent
ArtistAction(
    type="delegate_to_agent",
    prompt="画一套 Cyberpunk 2077 风格的城市景观，4 个不同区域",
    message="这个需求比较复杂，我用 Agent 模式来规划一下～",
)
```

---

## 8. SSE 事件

### 8.1 新增事件

| 事件类型 | payload | 说明 |
|---------|---------|------|
| `long_task_created` | `{task_run_id, name, total_steps, strategy}` | 长任务创建 |
| `long_task_step_started` | `{task_run_id, step_index, step_name, prompt}` | 步骤开始 |
| `long_task_step_completed` | `{task_run_id, step_index, artifact_urls, tokens, cost}` | 步骤完成 |
| `long_task_step_failed` | `{task_run_id, step_index, error, retry_count}` | 步骤失败 |
| `long_task_progress` | `{task_run_id, completed, total, failed, current_step_name}` | 进度更新 |
| `long_task_paused` | `{task_run_id, completed, total, paused_at}` | 任务暂停 |
| `long_task_resumed` | `{task_run_id, resumed_at}` | 任务恢复 |
| `long_task_completed` | `{task_run_id, total_artifacts, total_tokens, total_cost}` | 任务完成 |
| `long_task_cancelled` | `{task_run_id, reason}` | 任务取消 |
| `long_task_checkpoint` | `{task_run_id, step_index, error, actions: ["skip","retry","abort"]}` | 步骤级检查点 |

### 8.2 事件工厂函数

```python
# backend/app/core/artist/events.py 新增

def long_task_created(session_id: str, task_run_id: str, name: str,
                      total_steps: int, strategy: str) -> dict:
    return {
        "type": "long_task_created",
        "session_id": session_id,
        "task_run_id": task_run_id,
        "name": name,
        "total_steps": total_steps,
        "strategy": strategy,
    }

def long_task_step_started(session_id: str, task_run_id: str,
                           step_index: int, step_name: str, prompt: str) -> dict: ...

def long_task_step_completed(session_id: str, task_run_id: str,
                             step_index: int, artifact_urls: list[str],
                             tokens: int, cost: float) -> dict: ...

def long_task_progress(session_id: str, task_run_id: str,
                       completed: int, total: int, failed: int,
                       current_step_name: str) -> dict: ...

def long_task_paused(session_id: str, task_run_id: str,
                     completed: int, total: int, paused_at: str) -> dict: ...

def long_task_resumed(session_id: str, task_run_id: str,
                      resumed_at: str) -> dict: ...

def long_task_completed(session_id: str, task_run_id: str,
                        total_artifacts: int, total_tokens: int,
                        total_cost: float) -> dict: ...

def long_task_cancelled(session_id: str, task_run_id: str,
                        reason: str) -> dict: ...

def long_task_step_failed(session_id: str, task_run_id: str,
                          step_index: int, error: str,
                          retry_count: int) -> dict: ...

def long_task_checkpoint(session_id: str, task_run_id: str,
                         step_index: int, error: str,
                         actions: list[str]) -> dict: ...
```

### 8.3 完整 SSE 事件流

```
用户请求 "画 12 张星座表情包"
  │
  ├─ event: artist_turn_started         { turn_id }
  ├─ event: artist_reply_delta          { content: "好的，我来画一套..." }
  ├─ event: artist_action_started       { action_type: "plan_complex_task" }
  ├─ event: long_task_created           { task_run_id, name: "星座表情包", total: 12 }
  │
  ├─ event: long_task_step_started      { step: 1, name: "白羊座" }
  ├─ event: long_task_progress          { completed: 0, total: 12 }
  ├─ event: artist_image_ready          { artifact: {...} }
  ├─ event: long_task_step_completed    { step: 1, urls: [...] }
  ├─ event: long_task_progress          { completed: 1, total: 12 }
  │
  ├─ ... (重复 2-11) ...
  │
  ├─ event: long_task_step_started      { step: 12, name: "双鱼座" }
  ├─ event: artist_image_ready          { artifact: {...} }
  ├─ event: long_task_step_completed    { step: 12, urls: [...] }
  ├─ event: long_task_progress          { completed: 12, total: 12 }
  │
  ├─ event: long_task_completed         { total_artifacts: 12, ... }
  └─ event: artist_turn_done            { phase: "idle" }
```

### 8.4 前端路由

```typescript
// Sessions.vue 新增事件路由

case 'long_task_created':      store.handleLongTaskCreated(eventSid, event); break
case 'long_task_step_started': store.handleLongTaskStepStarted(eventSid, event); break
case 'long_task_step_completed':store.handleLongTaskStepCompleted(eventSid, event); break
case 'long_task_progress':     store.handleLongTaskProgress(eventSid, event); break
case 'long_task_paused':       store.handleLongTaskPaused(eventSid, event); break
case 'long_task_resumed':      store.handleLongTaskResumed(eventSid, event); break
case 'long_task_completed':    store.handleLongTaskCompleted(eventSid, event); break
case 'long_task_cancelled':    store.handleLongTaskCancelled(eventSid, event); break
case 'long_task_step_failed':  store.handleLongTaskStepFailed(eventSid, event); break
case 'long_task_checkpoint':   store.handleLongTaskCheckpoint(eventSid, event); break
```

---

## 9. 风险评估

### 9.1 技术风险

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| Artist LLM 错误拆分任务 | 中 | 用户体验差 | `plan_complex_task` 产出后先展示给用户确认（类似 checkpoint） |
| 长任务中间步骤失败 | 高 | 任务中断 | 自动重试 3 次 + checkpoint 让用户选 skip/retry/abort |
| LLM token 超限（长上下文） | 中 | prompt 截断 | `_smart_truncate` 已存在，按优先级裁剪历史 |
| 数据库写入竞争 | 低 | 数据不一致 | SQLite 单写模式天然串行；步骤级 `await` 避免并发写 |
| 内存占用（大量 artifacts） | 中 | OOM | 限制最大步骤数 50；每 5 步持久化一次 |
| 与现有 Artist 路径冲突 | 低 | 单 turn 行为改变 | 新路径完全在 `handle_turn` 内部分支，不影响现有流程 |

### 9.2 产品风险

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| 用户体验变复杂 | 中 | 用户困惑 | 长任务卡片 UI 简洁；单 turn 用户无感知 |
| Artist 人格在编排中丢失 | 中 | 不像聊天 | 编排中的消息仍在 Artist persona 下生成 |
| 用户不信任自动拆分 | 高 | 放弃使用 | 首次展示计划，用户可手动调整后确认 |

---

## 10. 兼容性

### 10.1 API 兼容性

| 端点 | 兼容性 | 说明 |
|------|--------|------|
| `POST /api/sessions/{id}/generate` | **完全兼容** | 请求参数不变，后端自动判断是否走长任务 |
| `GET /api/sessions/{id}/messages` | **完全兼容** | 长任务消息 `message_type="artist"`，metadata 含 `long_task` 字段 |
| `GET /api/sessions/events` | **完全兼容** | 新增事件类型，旧客户端忽略即可 |
| `GET /api/sessions/{id}/lineage-tree` | **完全兼容** | 长任务产出的 artifacts 正常加入 lineage DAG |

### 10.2 新增 API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/sessions/{sid}/long-task/{run_id}/pause` | POST | 暂停长任务 |
| `/api/sessions/{sid}/long-task/{run_id}/resume` | POST | 恢复长任务 |
| `/api/sessions/{sid}/long-task/{run_id}/cancel` | POST | 取消长任务 |
| `/api/sessions/{sid}/long-task/{run_id}` | GET | 获取长任务状态 |
| `/api/sessions/{sid}/long-tasks` | GET | 获取会话的所有长任务 |

### 10.3 数据兼容性

- `Message.metadata` 新增可选字段 `long_task_run_id: str | None` — 旧消息该字段为 None，不影响。
- `LongTaskRunModel` 是新表，不影响现有表结构。
- `ArtistSessionState` 新增字段有默认值，旧 state JSON 反序列化时自动填充。

---

## 11. 设计决策

### 11.1 为什么不用 Agent 9-node 图直接替代？

| 维度 | Agent 图 | Artist 长任务编排 |
|------|---------|-----------------|
| 人格 | 冷冰冰的 planner-executor | 保留 Artist 聊天人格 |
| 灵活性 | 严格的 plan→execute→critic 循环 | LLM 自由决定下一步 |
| 步数控制 | graph 编译时固定 | 运行时动态 |
| 用户交互 | checkpoint 阻断式 | 流式进度 + 可选暂停 |
| SSE 事件 | agent_node_progress | artist_* 系列（丰富） |

**结论**：Agent 图作为子任务**委托目标**（`delegate_to_agent`），但主流程由 TaskOrchestrator 驱动以保持 Artist 人格。

### 11.2 为什么不直接用 ExecutionEngine.run_all() 循环？

`ExecutionEngine.run_all()` 是一个同步阻塞循环，执行期间无法：
- 接收用户暂停指令
- 发送中间进度
- 处理步骤级失败后的 checkpoint

TaskOrchestrator 在每一步之间插入 `asyncio.sleep(0)` 让出事件循环，检查暂停/取消信号。

### 11.3 为什么计划要用户确认？

LLM 拆分任务可能不合理（如把 12 个星座拆成 6+6 而不是 12 独立步骤）。首次实施时展示计划给用户确认，后续可以根据用户反馈训练 Skill（见第 14 章）。

---

## 12. 待讨论问题

| 编号 | 问题 | 选项 | 建议 |
|------|------|------|------|
| Q1 | 长任务是否默认需要用户确认计划？ | A: 始终确认 / B: 智能判断（单步<10不自询） | B — 简单任务不过度打断 |
| Q2 | 失败步骤的数据（空 artifacts）是否保留？ | A: 保留占位 / B: 不保存 | A — 用户可能想查看哪些失败了 |
| Q3 | `delegate_to_agent` 的 Agent 输出如何融入 Artist 对话？ | A: 静默执行 / B: Agent 的 plan 展示给用户 | B — 透明度更好 |
| Q4 | 长任务是否支持并发步骤？ | A: 纯串行 / B: 支持分组并发 | B — 复用 ExecutionEngine.group_steps() |
| Q5 | 长任务数据存在内存还是 DB？ | A: 内存 / B: SQLite | B — 支持跨进程重启恢复 |
| Q6 | 最大步骤数限制？ | A: 不限 / B: 50 步硬限制 | B — 防止滥用 |
| Q7 | Artist 能否在长任务进行中继续聊天？ | A: 可以 / B: 阻塞直到完成 | A — 但限制为轻量对话，不触发新任务 |

---

## 13. 编排-工具-动作三层架构

### 13.1 三层定义

```
┌────────────────────────────────────────────┐
│           编排层 (Orchestration)             │
│  TaskOrchestrator — plan, schedule, resume │
│  Agent Graph — planner, decision, critic   │
│  Skill Engine — strategy select, bias      │
└────────────────┬───────────────────────────┘
                 │ 调用
┌────────────────▼───────────────────────────┐
│            工具层 (Tools)                    │
│  generate_images_core — 三层降级生图        │
│  ImageClient — generate/edit/chat_edit     │
│  LLMClient — chat_stream, vision           │
│  WebSearchTool, ImageSearchTool            │
│  billing_service, image_proxy              │
└────────────────┬───────────────────────────┘
                 │ 执行
┌────────────────▼───────────────────────────┐
│            动作层 (Actions)                  │
│  ArtistAction — 14 种原子动作               │
│  parse_artist_turn — LLM 输出 → Action     │
│  ExecutionEngine — Action → 工具调用        │
└────────────────────────────────────────────┘
```

### 13.2 层级职责

| 层 | 职责 | 生命周期 | 对 LLM 可见 |
|----|------|---------|------------|
| **编排层** | 决定「做什么」— 分解任务、选择策略、调度步骤 | 跨 turn | 通过 system prompt 注入 |
| **工具层** | 提供「怎么做」的能力 — API 调用、降级、记账 | 单次调用 | 作为 function calling tools |
| **动作层** | 表达「现在做什么」— 原子操作、参数序列化 | 单 turn | LLM 直接输出 JSON action |

### 13.3 LLM Prompt 分层注入

```python
# 编排层 → system prompt
"You can plan multi-step tasks when the user requests more than 6 images
 or a multi-stage workflow. Use plan_complex_task action."

# 工具层 → function calling
tools = [
    {"name": "generate_image", ...},
    {"name": "image_search", ...},
    {"name": "web_search", ...},
]

# 动作层 → JSON output schema
"Output a JSON with 'message' and 'actions' fields.
 Available actions: generate_anchor, generate_pack, refine_target,
 replace_image, plan_complex_task, delegate_to_agent, ..."
```

---

## 14. Skill 自进化机制

### 14.1 概念

Skill 自进化让 LamImager 从成功的创作任务中自动学习，优化未来的任务分解和 prompt 构建。

### 14.2 机制设计

```
长任务完成 → 提取成功模式 → 更新 Skill
     │
     ├── 任务类型识别: "表情包批量生成"
     ├── prompt pattern 提取: series_prompts 结构
     ├── style_lock 提取: 统一的风格参数
     ├── 步骤数优化: 12 个 → 下次类似请求直接拆 12 步
     └── 写入 Skill: prompt_template + parameters
```

### 14.3 Skill 记录结构

```python
# backend/app/models/skill.py 扩展

class SkillEvolutionRecord(BaseModel):
    """Skill 自进化记录"""
    skill_id: str
    source_task_run_id: str       # 来源长任务
    task_type: str                # "emoji_pack", "tarot_deck", "comic_strip"
    learned_patterns: list[dict]  # 学到的 prompt pattern
    success_metrics: dict         # 成功率、用户反馈
    created_at: str

# 示例
{
    "skill_id": "skill_emoji_pack",
    "source_task_run_id": "run_abc123",
    "task_type": "emoji_pack",
    "learned_patterns": [
        {
            "trigger_keywords": ["表情包", "一套", "系列"],
            "default_count": 12,
            "prompt_template": "{theme} zodiac emoticon, cute chibi style, {color} background",
            "style_lock": {"style": "cute chibi", "format": "emoji", "size": "512x512"}
        }
    ],
    "success_metrics": {"completion_rate": 1.0, "user_modified": false}
}
```

### 14.4 触发与节制

| 触发条件 | 节制规则 |
|---------|---------|
| 长任务成功完成（所有步骤 completed） | 仅当 `completion_rate >= 0.8` 时记录 |
| 用户未修改计划（直接确认） | 用户修改过的计划不学习 |
| 同类型任务累计 >= 3 次 | 取 prompt pattern 的交集/众数 |
| 用户手动点赞/收藏结果 | 加权提升该 pattern 的优先级 |

### 14.5 应用方式

```
下次用户说 "画一套海贼王表情包":
  → Skill 引擎匹配 "emoji_pack" skill
  → 自动注入 learned_patterns:
      count: 12, prompt_template: "...", style_lock: {...}
  → Artist LLM 在 prompt 中看到 bias
  → 产出 plan_complex_task 时自动使用学到的参数
```

### 14.6 不做的事

- **不自动生成代码** — Skill 进化只更新 prompt/参数，不改执行逻辑。
- **不跨用户共享** — 每个用户的 Skill 进化数据隔离。
- **不覆盖用户手动设置** — 用户手动指定的 count/size/style 优先。
