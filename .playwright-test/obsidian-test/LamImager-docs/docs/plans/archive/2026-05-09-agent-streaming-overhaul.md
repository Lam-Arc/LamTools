# Agent 流式输出全栈改造 — 实现计划

> **For agentic workers:** Use executing-plans or subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Agent 生成从"一次性 POST 等待"升级为全流式 SSE 广播管道，前端渐进式渲染时间线+卡片，Checkpoint 暂停恢复，图片多模态上下文。

**Architecture:** 后端：LamEvent v1 协议通过 TaskManager 广播到 GET /api/sessions/events SSE。前端：AgentStreamCard 组件渐进构建（左时间线+右流式内容）。Checkpoint 通过 asyncio.Event 统一暂停管道。

**Tech Stack:** Python/FastAPI/asyncio + Vue3/TypeScript/Pinia

---

## Task 1: 新建 LamEvent + EventLog

**Files:** `backend/app/core/events/__init__.py`（新建）

**Steps:**
- [ ] 创建 `backend/app/core/events/` 目录，新建 `__init__.py`
- [ ] 实现 `LamEvent` dataclass，字段：`event_id: str`（UUID）、`timestamp: int`（ms）、`source_product: str`（默认 `"lamimager"`）、`target_product: str | None`（默认 None）、`event_type: str`、`correlation_id: str`、`payload: dict`
- [ ] 实现 `EventLog` 类：`max_size=2000` 环形缓冲区
  - `append(event) -> str`：生成 `sse_id = f"{event.timestamp}-{self._next_seq:04d}"`，存入 `_events: list[tuple[str, LamEvent]]`
  - `replay_since(last_event_id: str) -> list[tuple[str, LamEvent]]`：找到 last_event_id 之后的事件返回

```python
# backend/app/core/events/__init__.py
from __future__ import annotations

import time
from dataclasses import dataclass, field
from uuid import uuid4


@dataclass
class LamEvent:
    event_id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: int = field(default_factory=lambda: int(time.time() * 1000))
    source_product: str = "lamimager"
    target_product: str | None = None
    event_type: str = ""
    correlation_id: str = ""
    payload: dict = field(default_factory=dict)


class EventLog:
    def __init__(self, max_size: int = 2000):
        self._events: list[tuple[str, LamEvent]] = []
        self._next_seq: int = 0

    def append(self, event: LamEvent) -> str:
        sse_id = f"{event.timestamp}-{self._next_seq:04d}"
        self._next_seq += 1
        self._events.append((sse_id, event))
        if len(self._events) > self.max_size:
            self._events = self._events[-self.max_size:]
        return sse_id

    def replay_since(self, last_event_id: str) -> list[tuple[str, LamEvent]]:
        for i, (eid, _) in enumerate(self._events):
            if eid == last_event_id:
                return self._events[i + 1 :]
        return []

    @property
    def max_size(self) -> int:
        return self._events._max_size if hasattr(self._events, '_max_size') or True else 2000
```

需要在 `EventLog.__init__` 中正确保存 `max_size` 引用。修正实现：

```python
class EventLog:
    def __init__(self, max_size: int = 2000):
        self.max_size = max_size
        self._events: list[tuple[str, LamEvent]] = []
        self._next_seq: int = 0

    def append(self, event: LamEvent) -> str:
        sse_id = f"{event.timestamp}-{self._next_seq:04d}"
        self._next_seq += 1
        self._events.append((sse_id, event))
        if len(self._events) > self.max_size:
            self._events = self._events[-self.max_size :]
        return sse_id

    def replay_since(self, last_event_id: str | None) -> list[tuple[str, LamEvent]]:
        if not last_event_id:
            return []
        for i, (eid, _) in enumerate(self._events):
            if eid == last_event_id:
                return self._events[i + 1 :]
        return []
```

**Verification:**
- [ ] `python -c "from app.core.events import LamEvent, EventLog; e = LamEvent(event_type='test', correlation_id='x'); log = EventLog(); sid = log.append(e); assert len(log.replay_since(sid)) == 0"`

**Commit:** `feat(core): add LamEvent dataclass and EventLog ring buffer`

---

## Task 2: 升级 TaskManager — EventLog + 广播 LamEvent + 统一 Checkpoint

**Files:** `backend/app/services/task_manager.py`

**Steps:**
- [ ] 顶部导入 `from app.core.events import LamEvent, EventLog` 和 `import json, time`
- [ ] `__init__` 中新增 `self._event_log = EventLog(max_size=2000)`
- [ ] 新增 `_serialize_sse(event: LamEvent, sse_id: str) -> str`：格式化为 `event: {event_type}\nid: {sse_id}\ndata: {json.dumps(vars(event), ensure_ascii=False)}\n\n`
- [ ] 新增 `async def publish(self, event: LamEvent) -> str`：
  - `sse_id = self._event_log.append(event)`
  - 从 `event.payload.get("session_id")` 取 session_id（若有）
  - 若 session_id 在 `_queues` 中，构造 SSE 行写入所有队列
  - 返回 sse_id
- [ ] 升级 `subscribe()` 签名改为 `async def subscribe(self, session_id: str | None = None, last_event_id: str | None = None) -> tuple[str, asyncio.Queue]`：
  - queue_id 按 session_id 分组存入 `_queues.setdefault(session_id, []).append(q)`
  - 若有 last_event_id，重放该 session 的历史事件
  - queue 改为 `asyncio.Queue(maxsize=256)`
- [ ] 升级 `_broadcast()` 改为发布 LamEvent：穿入 `event: LamEvent`
- [ ] 新增 `set_checkpoint_event(self, session_id: str, event: LamEvent) -> asyncio.Event`：创建 `asyncio.Event`，存入 `_checkpoint_states[session_id]`（event, event_obj, created_at）
- [ ] 新增 `resolve_checkpoint(self, session_id: str, approved: bool) -> bool`：取出 checkpoint，`event_obj.set()`，返回 True；不存在返回 False
- [ ] 升级 `cancel_task(self, session_id: str)`：增加 checkpoint 清理逻辑——若 `session_id in self._checkpoint_states`，取出并 `event_obj.set()`（等同于 reject）
- [ ] 将 `_queues` 从 `dict[str, asyncio.Queue]` 改为 `dict[str, list[asyncio.Queue]]`
- [ ] 升级 `unsubscribe()` 支持按 (session_id, queue) 移除

**Verification:**
- [ ] 启动 uvicorn，确认无 import 错误
- [ ] 在 Python REPL 中测试：`TaskManager().publish(LamEvent(...))` 不报错

**Commit:** `feat(task_manager): add EventLog, LamEvent publish/subscribe, unified checkpoint`

---

## Task 3: Tool 基类增加 checkpoint 字段

**Files:** `backend/app/tools/base.py`, `backend/app/tools/generate_image.py`

**Steps:**
- [ ] 在 `Tool` 基类增加属性 `checkpoint: bool = False`
- [ ] 在 `GenerateImageTool` 类设置 `checkpoint = True`

```python
# base.py diff
class Tool(ABC):
    name: str = ""
    description: str = ""
    parameters: dict = {}
    checkpoint: bool = False  # NEW: 执行前是否暂停等待审批
```

```python
# generate_image.py diff
class GenerateImageTool(Tool):
    name = "generate_image"
    checkpoint = True  # NEW
    ...
```

**Verification:**
- [ ] `from app.tools import registry; assert registry.get('generate_image').checkpoint == True`

**Commit:** `feat(tools): add checkpoint flag to Tool base and GenerateImageTool`

---

## Task 4: 新建 agent_bridge.py — AgentEvent → LamEvent 适配

**Files:** `backend/app/services/agent_bridge.py`（新建）

**Steps:**
- [ ] 创建文件，导入 `LamEvent`、`AgentEvent` 子类（从 `agent_service`）
- [ ] 实现 `agent_event_to_lam_event(agent_evt, session_id: str, correlation_id: str) -> LamEvent`：
  - TokenEvent → `("task_progress", "agent_token", {"content": …, "session_id": …})`
  - ToolCallEvent → `("task_progress", "agent_tool_call", {"name": …, "args": …, "session_id": …})`
  - ToolResultEvent → `("task_progress", "agent_tool_result", {"name": …, "content": …, "meta": …, "session_id": …})`
  - WarningEvent → `("task_progress", "agent_tool_warning", {"name": …, "reason": …, "retry_count": …, "session_id": …})`
  - DoneEvent → `("task_completed", "agent_done", {"tokens_in": …, "tokens_out": …, "cost": …, "session_id": …})`
  - ErrorEvent → `("task_failed", "agent_error", {"error": …, "session_id": …})`
  - CancelledEvent → `("task_completed", "agent_cancelled", {"partial_output": …, "tokens_in": …, "tokens_out": …, "session_id": …})`

**Verification:**
- [ ] 单元测试：传入 TokenEvent(content="hello")，验证返回的 LamEvent 有正确 event_type、payload.type、payload.content

**Commit:** `feat(agent): add agent_bridge to convert AgentEvent to LamEvent`

---

## Task 5: 升级 agent_service.py — 截断 + 硬顶 + Checkpoint 暂停

**Files:** `backend/app/services/agent_service.py`

**Steps:**
- [ ] 新增 `_truncate_tool_result(content, tool_name, max_chars=800) -> str`：
  - 若 content 短于 max_chars，直接返回
  - 若 tool_name == "web_search"，保留前 3 条 + 附加"其余 N 条已省略"
  - 否则截断 + "…[truncated]"
- [ ] 新增 `_estimate_tokens(messages: list[dict]) -> int`：`sum(len(json.dumps(m)) // 3 for m in messages)`
- [ ] 在 `run_agent_loop()` 的 tool_result 处理后调用 `_truncate_tool_result()` 截断存入 working_messages 的 content
- [ ] 在每轮循环开始前（line 226 for 循环体开始处）检查 working_messages 硬顶：若 `_estimate_tokens(working_messages) > 6000`，保留 system message + 最近 8 条
- [ ] 修改 checkpoint 逻辑（line 280-282）：
  - 从 `checkpoints` 参数解析（Tool 的 checkpoint 属性已经在调用方收集）
  - 遇到 checkpoint 时：`yield ToolCallEvent` → `task_manager.set_checkpoint_event(sid, lam_event)` → `yield` 一个 checkpoint_required 的 LamEvent（通过新的回调注入） → `await checkpoint_event.wait()` → 继续执行
  - **关键**：`run_agent_loop()` 不直接依赖 `TaskManager`，改为接受可选回调参数 `on_checkpoint: Callable | None = None`
  - 当 `on_checkpoint` 存在且 fn_name 在 checkpoints 中时：`approved = await on_checkpoint(fn_name, fn_args)`，若 not approved 则 yield CancelledEvent 并 break

```python
# 新增回调参数
async def run_agent_loop(
    ...
    on_checkpoint: callable | None = None,
) -> AsyncGenerator[AgentEvent, None]:
```

在 checkpoint 处：
```python
if fn_name in checkpoints and on_checkpoint:
    approved = await on_checkpoint(fn_name, fn_args)
    if not approved:
        yield CancelledEvent(partial_output=partial_output, tokens_in=total_tokens_in, tokens_out=total_tokens_out)
        return
```

**Verification:**
- [ ] 现有 agent 测试通过（无 checkpoint 时行为不变）
- [ ] 手动构造 checkpoint 触发场景，验证暂停-恢复

**Commit:** `feat(agent): add tool result truncation, working_messages cap, checkpoint callback`

---

## Task 6: 升级 generate_service.py — 发布到 TaskManager + 图片上下文 + token 预算

**Files:** `backend/app/services/generate_service.py`

**Steps:**
- [ ] 导入 `TaskManager`、`LamEvent`、`agent_event_to_lam_event`、`asyncio`
- [ ] 修改 `handle_agent_generate()`：
  - **移除** `async for event in run_agent_loop(...)` 的原地消费逻辑
  - **改为**：`task_manager.publish(task_started LamEvent)` → 启动 `run_agent_loop()` → 对每个 event 调用 `agent_event_to_lam_event()` → `task_manager.publish()` → 同时异步累积 `final_output`、`steps`、`images`
  - Checkpoint 回调：`on_checkpoint` → `task_manager.publish(checkpoint_required LamEvent)` → `await task_manager.set_checkpoint_event(sid, lam_event).wait()` → 检查 `_checkpoint_states[sid].get("approved")` 返回 True/False
  - 使用 `asyncio.create_task()` 启动 agent loop + 事件消费，主协程不阻塞
- [ ] 升级 `_build_agent_context()`：
  - 改为 `limit=20` 取消息
  - 从足底啊往前积累，按 token 预算 `max_tokens=3000` 截断（`len(content)//3` 估算）
  - 返回 `list[dict]`（role + content）
- [ ] 新增注入图片上下文逻辑：检查 `data.reference_images`（base64）、`data.context_messages[].image_urls`（URL），构建多模态 user message
- [ ] 移除 `_build_agent_context` 中的 500 字符硬截断，改为 token 预算

**Verification:**
- [ ] Agent 生成正常触发，前端 SSE 实时收到 token/tool_call/tool_result 事件
- [ ] 历史消息超过 3000 token 预算时能正确截断

**Commit:** `feat(generate): publish agent events via TaskManager, add image context, token-budget context`

---

## Task 7: 升级 SSE events 端点 — LamEvent 格式 + Last-Event-ID 重放

**Files:** `backend/app/routers/session.py`

**Steps:**
- [ ] 升级 `session_events()`：
  - 从 request 读取 `Last-Event-ID` header
  - 调用 `task_manager.subscribe(session_id=None, last_event_id=last_event_id)`（全局订阅）
  - event_generator 中：首次发送 snapshot（保持兼容），后续从 queue 中读出的是已序列化的 SSE 行（行尾已有 `\n\n`），直接 `yield sse_line`
  - 移除 `json.dumps(event)` 包装——line 已由 TaskManager._serialize_sse 生成

- [ ] 修改 snapshot 格式：仍发送 `data: {"type":"snapshot","data":...}\n\n` 保持前端兼容

**Verification:**
- [ ] `curl -N http://localhost:8000/api/sessions/events` 看到 `ping` 事件
- [ ] 断开重连时带 `Last-Event-ID` header，能收到历史事件

**Commit:** `feat(session): upgrade SSE events to LamEvent format with Last-Event-ID replay`

---

## Task 8: 激活 checkpoint 端点

**Files:** `backend/app/routers/session.py`

**Steps:**
- [ ] 修改 `api_agent_checkpoint()`：
  - 调用 `task_manager.resolve_checkpoint(session_id, approved=data.approved)`
  - 若 approved，返回 `{"status": "resolved"}`
  - 若 rejected，返回 `{"status": "cancelled"}`

**Verification:**
- [ ] Agent 过程中触发 checkpoint → endpoint 可正常 resolve

**Commit:** `feat(session): activate checkpoint endpoint with TaskManager resolve`

---

## Task 9: 添加 agent_checkpoint_rules 到 settings

**Files:** `backend/app/models/app_settings.py`（或 settings 相关 migration）

**Steps:**
- [ ] 确保 `app_settings` 表支持 `agent_checkpoint_rules` 键
- [ ] 默认值：`{"agent_checkpoint_rules": []}`
- [ ] 不在此任务实现规则检查逻辑（规则检查逻辑在 Task 6 的 `run_agent_loop` 回调中后续扩展）

**Verification:**
- [ ] 启动后 settings API 能读写 `agent_checkpoint_rules`

**Commit:** `feat(settings): add agent_checkpoint_rules default config`

---

## Task 10: 前端 — 新增 TypeScript 类型

**Files:** `frontend/src/types/index.ts`

**Steps:**
- [ ] 新增 `LamEventPayload` 接口：`{ type: string; session_id: string; content?: string; name?: string; args?: Record<string, any>; meta?: Record<string, any>; [key: string]: any }`
- [ ] 新增 `LamEvent` 接口：`{ event_id: string; timestamp: number; source_product: string; target_product: string | null; event_type: string; correlation_id: string; payload: LamEventPayload }`
- [ ] 新增 `AgentStreamState` 接口：`{ sessionId: string; status: 'connecting' | 'thinking' | 'tool_running' | 'paused' | 'done' | 'error'; content: string; steps: AgentStreamStep[]; cost: number | null }`
- [ ] 新增 `AgentStreamStep` 接口：`{ id: string; type: 'tool_call' | 'tool_result' | 'checkpoint' | 'plan'; name: string; status: 'pending' | 'running' | 'done' | 'error'; args?: Record<string, any>; content?: string; meta?: Record<string, any> }`

**Verification:**
- [ ] `npm run typecheck` 通过

**Commit:** `feat(types): add LamEvent, AgentStreamState, AgentStreamStep interfaces`

---

## Task 11: 前端 — 升级 useSessionEvents 支持 LamEvent + Last-Event-ID

**Files:** `frontend/src/composables/useSessionEvents.ts`

**Steps:**
- [ ] 修改接口：增加回调 `onAgentEvent?: (event: LamEvent) => void`
- [ ] 修改 `connect()` 解析逻辑：
  - 侦听 `event.type` 字段（来自 SSE `event:` 行）：
    - `task_update` → 调用 `onTaskUpdate(event.data)`（保持兼容）
    - `snapshot` → 调用 `onSnapshot(event.data)`
    - `task_progress` / `checkpoint_required` / `task_completed` / `task_failed` → 调用 `onAgentEvent(event.data)` 如果是 agent 相关
  - `EventSource` 不支持 `event:` 行时退化为全量 `onmessage` 解析
- [ ] 重连时设置 `Last-Event-ID`：`EventSource` 原生不支持自定义 `Last-Event-ID` header，改用 `fetch` + `ReadableStream` 替代：
  - `disconnect()` 时记录最后一个 `event_id`
  - `connect()` 时用 `fetch('/api/sessions/events', { headers: { 'Last-Event-ID': lastEventId } })` + `ReadableStream` reader
  - 手动解析 SSE 行

**Verification:**
- [ ] 断开后重连，验证 `Last-Event-ID` header 被发送

**Commit:** `feat(events): upgrade useSessionEvents to parse LamEvent format with Last-Event-ID`

---

## Task 12: 前端 — 新建 AgentStreamCard.vue 组件

**Files:** `frontend/src/components/session/AgentStreamCard.vue`（新建）

**Steps:**
- [ ] 创建 Vue3 组件，props: `state: AgentStreamState`
- [ ] Template 结构：
  ```html
  <div class="agent-stream-card">
    <div class="stream-header">
      <span class="agent-badge">Agent</span>
      <span class="stream-cost" v-if="state.cost !== null">费用 ¥{{ state.cost.toFixed(3) }}</span>
      <span class="stream-status">{{ statusLabel }}</span>
    </div>
    <div class="stream-body">
      <div class="stream-timeline">
        <div class="timeline-line"></div>
        <div v-for="step in state.steps" :key="step.id" class="timeline-node" :class="step.status">
          <span class="node-dot"></span>
          <span class="node-label">{{ step.type === 'tool_call' ? '>' : '<' }} {{ step.name }}</span>
        </div>
      </div>
      <div class="stream-content">
        <div class="stream-text" v-html="renderMarkdown(state.content)"></div>
        <span class="typing-cursor" v-if="state.status === 'thinking'"></span>
        <div v-for="step in completedSteps" :key="step.id" class="tool-result-card" :class="{ collapsed: step.collapsed }" @click="step.collapsed = !step.collapsed">
          <div class="card-header">{{ step.status === 'done' ? '✓' : '◉' }} {{ step.name }}</div>
          <div class="card-body" v-if="!step.collapsed" v-html="renderMarkdown(step.content || '')"></div>
        </div>
      </div>
    </div>
    <div class="stream-footer" v-if="!isFinal">
      <button class="btn btn-danger" @click="$emit('cancel')">取消</button>
    </div>
  </div>
  ```
- [ ] CSS（Sessions.vue 同目录或共用全局）：
  - `.agent-stream-card`：grid（timeline 80px + content 1fr）
  - `.stream-timeline`：竖线 + 节点圆点，`.node-dot` 完成态黑色、running 态 `pulse` 动画
  - `.typing-cursor`：`border-right: 2px solid black; animation: blink 0.8s infinite`
  - `.tool-result-card`：`max-height: 0→auto` transition
  - 动画 keyframes 定义在组件 scoped style 或 Sessions.vue 中

**Verification:**
- [ ] 组件能在故事板（或手动传 mock 数据）中正常渲染

**Commit:** `feat(frontend): add AgentStreamCard with timeline + streaming text + tool cards`

---

## Task 13: 前端 — 新建 CheckpointOverlay.vue 组件

**Files:** `frontend/src/components/session/CheckpointOverlay.vue`（新建）

**Steps:**
- [ ] Props: `visible: boolean`, `message: string`, `previewUrl?: string`, `toolName?: string`
- [ ] Emits: `approve`, `reject`, `skip`
- [ ] Template：
  ```html
  <div v-if="visible" class="checkpoint-overlay">
    <div class="checkpoint-card">
      <h3>⏸ 检查点</h3>
      <p class="checkpoint-tool" v-if="toolName">{{ toolName }}</p>
      <p class="checkpoint-message">{{ message }}</p>
      <img v-if="previewUrl" :src="previewUrl" class="checkpoint-preview" />
      <div class="checkpoint-actions">
        <button class="btn btn-primary" @click="$emit('approve')">继续</button>
        <button class="btn" @click="$emit('skip')">跳过</button>
        <button class="btn btn-danger" @click="$emit('reject')">终止</button>
      </div>
    </div>
  </div>
  ```
- [ ] CSS：复用现有 `.checkpoint-overlay` 样式（来自 Sessions.vue line 3519-3548），提取为独立样式

**Verification:**
- [ ] 组件在 visible=true 时显示 overlay，点击按钮触发对应事件

**Commit:** `feat(frontend): add CheckpointOverlay component`

---

## Task 14: 前端 — 升级 Sessions.vue 核心集成

**Files:** `frontend/src/views/Sessions.vue`

**Steps:**
- [ ] 在 template 中添加 `AgentStreamCard` 渲染区域（消息列表内，当 streamState 存在时渲染流式卡片，替换最终 agent message 卡片）
- [ ] 添加 `CheckpointOverlay` 组件引用（`v-if="checkpointState.visible"`）
- [ ] 修改 `useSessionEvents` 调用：增加 `onAgentEvent` 回调
- [ ] `onAgentEvent` 处理逻辑：
  - `task_started` → 初始化 `agentStreamState`
  - `agent_token` → `state.content += payload.content`
  - `agent_tool_call` → `state.steps.push({ id: event.event_id, type: 'tool_call', name: payload.name, status: 'running', args: payload.args })`
  - `agent_tool_result` → 匹配 running 步骤标记 done，填入 content/meta
  - `agent_done` → `state.status = 'done'`, `state.cost = payload.cost`
  - `agent_error` → `state.status = 'error'`
  - `agent_cancelled` → `state.status = 'done'`, 并在 content 末尾加"已取消"标记
- [ ] Checkpoint 处理：`checkpoint_required` → `checkpointState.visible = true`, await approve/reject → `POST /checkpoint`
- [ ] 取消按钮升级：移除 `agentMode` 条件，改为 `isSessionBusy` 判断
- [ ] `sendGenerate()` agent 模式：移除 `await store.generate()` 的阻塞等待，改为 fire-and-forget（SSE 实时更新替代）

**Verification:**
- [ ] Agent 生成时，消息流中逐步显示 token、工具调用卡片、检查点暂停
- [ ] 取消按钮在生成中始终可见且可用

**Commit:** `feat(frontend): integrate AgentStreamCard, CheckpointOverlay, SSE agent events into Sessions`

---

## Task 15: 前端 — 升级 session store

**Files:** `frontend/src/stores/session.ts`

**Steps:**
- [ ] 新增 `agentStreamStates: Ref<Map<string, AgentStreamState>>`
- [ ] 新增 `getAgentStream(sid: string)` getter
- [ ] 新增 `setAgentStream(sid: string, state: AgentStreamState)` action
- [ ] 新增 `clearAgentStream(sid: string)` action
- [ ] `generate()` 方法：agent_mode 时不再 `await` 完整响应，改为仅发起请求（SSE 通道负责状态）

**Verification:**
- [ ] store 中 agentStreamStates 响应式更新触发视图重新渲染

**Commit:** `feat(store): add agentStreamStates to session store`

---

## 执行顺序

Tasks 1-3（协议 + 基础设施）→ Tasks 4-6（agent 管道）→ Tasks 7-9（端点升级）→ Tasks 10-11（前端协议）→ Tasks 12-13（前端组件）→ Tasks 14-15（前端集成）

后端完成 Task 9 后可独立验证流式输出（用 curl 监控 `/events` SSE 通道）。前端 Tasks 10-15 必须按顺序（类型 → composable → 组件 → 集成）。
