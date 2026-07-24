# Artist 统一对话生图 — 实施计划

> **For agentic workers:** Use executing-plans or subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 恢复 Artist 运行时，扩展为统一对话+编排层；Image Agent（原 9 节点图）作为重型执行后端。Artist 负责聊天和编排，Image Agent 负责多步规划执行。Video Agent 预留接口。

**Architecture:** Artist = 编排层（对话 + 意图理解 + 任务拆解 + 委托）。Image Agent = 执行层（被委托时运行 9 节点管线）。前端统一消息流：`artist_*` SSE 事件 + `agent_*` SSE 事件共存于同一 `agentStreamStates` Map。

**Tech Stack:** Python 3.14+ / FastAPI / LangGraph / SQLAlchemy async / Vue3 / TypeScript / Pinia / SSE

---

## Phase 0: Restore Artist Core from Stash

> 从 stash 恢复 Artist 核心文件。**注意**：部分冲突文件需选择性合并，不能全量 pop stash。

### Task 0.1: Restore Artist Core Files

**Files:** `backend/app/core/artist/` (10 files from stash)

**Steps:**
- [ ] 1. 执行 `git checkout stash@{0} -- backend/app/core/artist/` 恢复所有 10 个 Artist 核心文件
- [ ] 2. 验证文件列表：`__init__.py`, `runtime.py`, `schemas.py`, `events.py`, `artifacts.py`, `turn_parser.py`, `transitions.py`, `normalizer.py`, `state_store.py`, `feedback.py`
- [ ] 3. 执行 `git checkout stash@{0} -- backend/app/services/artist_service.py` 恢复编排服务
- [ ] 4. 执行 `git checkout stash@{0} -- backend/app/core/persona.py` 恢复 persona 定义
- [ ] 5. 执行 `git checkout stash@{0} -- backend/tests/test_artist_*.py` 恢复测试文件

**Verification:**
- [ ] `Test-Path "backend/app/core/artist/runtime.py"` 返回 True
- [ ] `Test-Path "backend/app/services/artist_service.py"` 返回 True
- [ ] `Test-Path "backend/app/core/persona.py"` 返回 True

**Commit:** `restore: Artist core runtime from stash (10 core files + service + persona + tests)`

### Task 0.2: Merge Stash Frontend Changes

**Files:** `frontend/src/stores/session.ts`, `frontend/src/types/index.ts`, `frontend/src/components/session/MessageList.vue`, `frontend/src/components/session/ArtistImageMessageCard.vue`, `frontend/src/views/Sessions.vue`

**Steps:**
- [ ] 1. 执行 `git checkout stash@{0} -- frontend/src/components/session/ArtistImageMessageCard.vue`（新文件，安全）
- [ ] 2. 对于 `session.ts` / `types/index.ts` / `MessageList.vue` / `Sessions.vue`：先备份 HEAD 版本，再 checkout stash 版本
- [ ] 3. 对于冲突文件 `Lightbox.vue`：手动审查 diff，HEAD 版本优先

**Verification:**
- [ ] `Test-Path "frontend/src/components/session/ArtistImageMessageCard.vue"` 返回 True
- [ ] 前端 `npm run dev` 不报错

**Commit:** `restore: Artist frontend components and store from stash`

### Task 0.3: Merge Stash Backend Changes (Selective)

**Files:** `backend/app/services/generate_service.py`, `backend/app/services/image_context_resolver.py`, `backend/app/database.py`, `backend/app/core/agent/nodes/planner_node.py`

**Steps:**
- [ ] 1. **跳过** `backend/app/utils/llm_client.py` — stash 版本被截断，HEAD 有完整 LLMClient
- [ ] 2. **跳过** `backend/app/core/events/__init__.py` — stash 版本被截断，HEAD 有完整 LamEvent/EventLog
- [ ] 3. 对于 `generate_service.py`：手动 diff stash vs HEAD，只保留 Artist 相关新增函数（`build_artist_image_message_metadata`, `_run_artist_orchestrate`, lineage 函数），其他回退
- [ ] 4. 对于 `image_context_resolver.py`：手动审查，合入 stash 新增的 patterns/resolvers
- [ ] 5. 对于 `database.py`：手动审查，合入 stash 新增的行
- [ ] 6. 对于 `planner_node.py` / `critic_node.py`：HEAD 版本优先，只合入 stash 的 Artist-aware 逻辑

**Verification:**
- [ ] 后端 `py -3.14 -m uvicorn app.main:app --port 6171` 启动不报错
- [ ] `lsp_diagnostics` 对 `generate_service.py` 无 error

**Commit:** `merge: Artist backend changes (selective, preserving HEAD llm_client and events)`

---

## Phase 1: Enable Conversation as First-Class Citizen

> 把 `chat_only` 从"JSON 解析失败的回退"提升为"对话的默认路径"。

### Task 1.1: Promote chat_only in Turn Parser

**Files:** `backend/app/core/artist/turn_parser.py`

**Steps:**
- [ ] 1. 修改 `parse_artist_turn()`：当 LLM 输出不含 `actions` 字段时，默认视为 `chat_only`（而不是先尝试 JSON 解析再回退）
- [ ] 2. 去掉 `chat_only` 的 200 字符截断（`text[:200]`），保留完整文本
- [ ] 3. 新增响应模式参数：`response_format` 可选 `"auto" | "json" | "text"`。`"auto"` 时 LLM 自主决定是否输出 JSON；从 Artist 传来的消息默认用 `"auto"`
- [ ] 4. 当 `response_format="text"` 时，跳过 JSON 解析，整个 LLM 输出视为 `chat_only` 的 message

**Verification:**
- [ ] `parse_artist_turn("你好，今天天气真好")` 返回 `ArtistTurn(actions=[chat_only], reply_blocks=["你好，今天天气真好"])`
- [ ] message 未被截断

**Commit:** `artist: promote chat_only to first-class citizen with auto/text/json modes`

### Task 1.2: Relax Artist Persona for General Conversation

**Files:** `backend/app/core/persona.py`

**Steps:**
- [ ] 1. 修改 `ARTIST` persona 的 `boundaries`：从 `"Only create visual content"` 改为 `"Prioritize visual content, but can converse freely"`
- [ ] 2. 新增对话相关 `proactive_rules`：`"When user asks non-visual question -> answer naturally without trying to generate images"`, `"When user seems confused -> explain briefly"`
- [ ] 3. 新增 `ARTIST_PROMPT_CHAT` 系统提示词（纯对话用），替代 `ARTIST_TURN_SYSTEM`（生图用）
- [ ] 4. 在 `prompt_assembler.py` 中根据当前意图选择使用 `ARTIST_PROMPT_CHAT` 还是 `ARTIST_TURN_SYSTEM`

**Verification:**
- [ ] `ARTIST_PROMPT_CHAT` 包含对话引导，不要求 JSON 输出
- [ ] Persona 不再拒绝非视觉问题

**Commit:** `artist: relax persona boundaries for general conversation`

### Task 1.3: Remove Hardcoded response_format in Artist Service

**Files:** `backend/app/services/artist_service.py`

**Steps:**
- [ ] 1. 找到 `_llm_call` 闭包中的 `response_format={"type": "json_object"}` 硬编码
- [ ] 2. 改为参数化：接受 `response_format_mode` 参数（`"json"` | `"text"` | `"auto"`）
- [ ] 3. `"auto"` 模式：根据历史上下文判断（上轮有生图 → json；纯对话 → text）
- [ ] 4. `"text"` 模式：不传 `response_format` 参数，让 LLM 自由输出

**Verification:**
- [ ] 对话时 LLM 不会被强制输出 JSON
- [ ] 生图时 LLM 仍然输出 JSON

**Commit:** `artist: parameterize response_format mode in artist_service`

---

## Phase 2: Artist Orchestration Layer

> Artist 现在可以聊天 + 识别意图 + 委托 Image Agent 执行复杂生图任务。

### Task 2.1: Add agent_persona to GenerateRequest

**Files:** `backend/app/schemas/session.py`

**Steps:**
- [ ] 1. 在 `GenerateRequest` pydantic model 中新增字段 `agent_persona: str | None = None`
- [ ] 2. 后端 schema 文件路径：`backend/app/schemas/session.py`
- [ ] 3. 前端 types 文件同步更新：`frontend/src/types/index.ts`

**Verification:**
- [ ] `GenerateRequest.model_validate({"session_id":"x","prompt":"hi","agent_persona":"artist"})` 不报错
- [ ] 前端 TypeScript 编译通过

**Commit:** `schema: add agent_persona field to GenerateRequest`

### Task 2.2: Route agent_persona="artist" in Session Router

**Files:** `backend/app/routers/session.py`

**Steps:**
- [ ] 1. 在 `POST /{session_id}/generate` 的处理函数中（约 line 115-145），找到 `if data.agent_mode:` 分支
- [ ] 2. 新增 `elif data.agent_persona == "artist"` 分支，调用 `_run_artist_background(db, session_id, data)`
- [ ] 3. 创建 `_run_artist_background()` 函数，与 `_run_agent_background()` 结构相同：`asyncio.create_task(handle_artist_generate(...))`
- [ ] 4. 创建 `handle_artist_generate()` 函数（在 `generate_service.py` 中），调用 `artist_orchestrate()`

**Verification:**
- [ ] 发 `POST /sessions/{id}/generate` with `{"agent_persona":"artist","prompt":"hi"}` 返回 `task_started` SSE 事件

**Commit:** `router: add artist persona routing to session generate endpoint`

### Task 2.3: Create Delegation Bridge — Artist → Image Agent

**Files:** `backend/app/services/generate_service.py`

**Steps:**
- [ ] 1. 在 `artist_orchestrate()` 中，当 LLM 输出 `generate_*` action 时，不直接调用 `generate_images_core`
- [ ] 2. 改为调用 `_run_agent_mode_graph()`，将 Artist 的意图作为 `skeleton_intent` 传入（跳过 Agent 的 `intent_node` LLM 调用）
- [ ] 3. 如果 `skeleton_intent.strategy == "single"`（单图），直接用 `generate_images_core`（跳过 9 节点图，减少 LLM 开销）
- [ ] 4. 如果 `skeleton_intent.strategy` in `["parallel", "iterative", "radiate"]`（多步），委托给 `_run_agent_mode_graph()`
- [ ] 5. Agent 返回的 `artifacts` 流回 Artist 的 lineage/state 追踪

**Verification:**
- [ ] Artist 输出 `generate_anchor` → 成功调用 generate_images_core 并收到结果
- [ ] Artist 输出 `batch_execute`（多步策略） → 成功委托给 Agent 图执行

**Commit:** `artist: add delegation bridge to Image Agent (9-node graph)`

### Task 2.4: Artist SSE Events — Backend

**Files:** `backend/app/core/artist/events.py`

**Steps:**
- [ ] 1. 审查 stash 恢复的 `events.py`：确认 `artist_turn_started()`, `artist_reply_delta()`, `artist_action_started()`, `artist_image_ready()`, `artist_turn_done()` 工厂函数存在
- [ ] 2. 确保所有事件工厂函数调用 `task_manager.publish(LamEvent(...))`，`event_type="task_progress"`，`payload.type` 分别为 `artist_turn_started` / `artist_reply_delta` / `artist_action_started` / `artist_image_ready` / `artist_turn_done`
- [ ] 3. 在 `artist_bridge.py`（新增或扩展 `agent_bridge.py`）中添加 `artist_event_to_lam_event()` 映射函数

**Verification:**
- [ ] 调用 `artist_turn_started("session-1", "turn-1")` → EventLog 中出现对应 LamEvent

**Commit:** `artist: implement SSE event factories for artist turn lifecycle`

---

## Phase 3: Frontend — Artist SSE Handling & Rendering

### Task 3.1: Extend SSE Event Routing (useSessionEvents)

**Files:** `frontend/src/composables/useSessionEvents.ts`

**Steps:**
- [ ] 1. 在 `connect()` 函数的事件分发 switch 中（约 line 100），新增 `artist_turn_started` / `artist_reply_delta` / `artist_action_started` / `artist_image_ready` / `artist_turn_done` 到路由列表
- [ ] 2. 所有 `artist_*` 事件路由到 `onAgentEvent()` 回调（与 `agent_*` 共用同一个回调）

**Verification:**
- [ ] SSE stream 收到 `{"event_type":"task_progress","payload":{"type":"artist_turn_started"}}` → `onAgentEvent` 被调用

**Commit:** `frontend: add artist event types to SSE routing`

### Task 3.2: Extend Types for Artist Events

**Files:** `frontend/src/types/index.ts`

**Steps:**
- [ ] 1. 新增 `ArtistStreamState` 接口：`{ sessionId, status, content, turns: ArtistTurnInfo[], cost, startedAt }`
- [ ] 2. 新增 `ArtistTurnInfo` 接口：`{ turnId, phase, replyBlocks: string[], actions: ArtistActionInfo[] }`
- [ ] 3. 新增 `ArtistActionInfo` 接口：`{ actionType, status, message?, imageUrl?, prompt? }`
- [ ] 4. 扩展 `Message.message_type` union 添加 `'artist'`
- [ ] 5. 扩展 `LamEventPayload` 添加 artist 字段：`phase?`, `blocks?`, `artifacts?`

**Verification:**
- [ ] `npm run build` 类型检查通过

**Commit:** `frontend: add ArtistStreamState and artist event types`

### Task 3.3: Add Artist Handlers to Session Store

**Files:** `frontend/src/stores/session.ts`

**Steps:**
- [ ] 1. 新增 `artistStreamStates: Map<string, ArtistStreamState>` ref
- [ ] 2. 新增 `handleArtistTurnStarted(sid, event)`: 创建新的 `ArtistTurnInfo`，推入 `artistStreamStates[sid].turns`
- [ ] 3. 新增 `handleArtistReplyDelta(sid, event)`: 追加到当前 turn 的 `replyBlocks`
- [ ] 4. 新增 `handleArtistActionStarted(sid, event)`: 创建 `ArtistActionInfo`，推入当前 turn 的 `actions`
- [ ] 5. 新增 `handleArtistImageReady(sid, event)`: 更新 action 状态为 `done`，设置 `imageUrl`
- [ ] 6. 新增 `handleArtistTurnDone(sid, event)`: 更新 turn 状态为 `done`，更新 `artistStreamStates[sid].phase`

**Verification:**
- [ ] 调用 `handleArtistTurnStarted("s1", payload)` → `artistStreamStates.get("s1").turns.length === 1`

**Commit:** `frontend: add artist event handlers to session store`

### Task 3.4: Dispatch Artist Events in Sessions.vue

**Files:** `frontend/src/views/Sessions.vue`

**Steps:**
- [ ] 1. 在 `onAgentEvent` 回调的 switch 语句中（约 line 485-527），新增 `artist_*` cases：
  - `case 'artist_turn_started'`: `store.handleArtistTurnStarted(sid, event)`
  - `case 'artist_reply_delta'`: `store.handleArtistReplyDelta(sid, event)`
  - `case 'artist_action_started'`: `store.handleArtistActionStarted(sid, event)`
  - `case 'artist_image_ready'`: `store.handleArtistImageReady(sid, event)`
  - `case 'artist_turn_done'`: `store.handleArtistTurnDone(sid, event)`

**Verification:**
- [ ] `onAgentEvent` switch 包含所有 5 个 artist case

**Commit:** `frontend: dispatch artist events in Sessions.vue`

### Task 3.5: Render Artist Messages in MessageList

**Files:** `frontend/src/components/session/MessageList.vue`

**Steps:**
- [ ] 1. 在历史消息渲染区（约 line 3-58），新增 `msg.message_type === 'artist'` 分支
- [ ] 2. Artist 消息渲染：每个 turn 显示 Artist 的回复文本（Markdown） + action 卡片（图片缩略图）
- [ ] 3. 在 live stream 区域（约 line 60-78），新增 `artistStreamState` 活跃时的渲染
- [ ] 4. 复用 `AgentInlineStep`/`AgentToolCall` 组件或创建轻量 `ArtistStep.vue`

**Verification:**
- [ ] `message_type: 'artist'` 的消息正确渲染为对话气泡 + 图片卡片
- [ ] live streaming 时实时更新文字和图片

**Commit:** `frontend: render artist messages and live stream in MessageList`

---

## Phase 4: Video Agent Placeholder

### Task 4.1: Reserve Video Agent Interface

**Files:** `backend/app/core/artist/schemas.py`, `backend/app/core/artist/runtime.py`

**Steps:**
- [ ] 1. 在 `ArtistActionType` 中确认 `generate_video` / `extract_frame` / `trim_video` / `adjust_video` 类型已存在（stash schemas 中已包含）
- [ ] 2. 在 `ArtistRuntime._execute_action` 中为 video 类型预留 `TODO: delegate to Video Agent` 注释
- [ ] 3. 在 `events.py` 中确认 `artist_clip_ready` / `artist_video_ready` 事件工厂已存在
- [ ] 4. 创建 `backend/app/core/agent/video_agent_placeholder.py`（只含类定义和 docstring，不实现）

**Verification:**
- [ ] Video action type 在 ArtistAction 枚举中
- [ ] 调用 `generate_video` action → 不崩溃，返回"Video Agent not yet implemented"提示

**Commit:** `video: reserve Video Agent interface in Artist runtime`

---

## Phase 5: End-to-End Test — Natural Language Scenarios

> **原则**：所有场景集中在一个文件 `backend/tests/test_artist_e2e.py`，每个场景模拟真实用户自然语言输入 → 完整对话 → 期望回复。不拆散到多个文件。

### 测试基础设施

**Mock 策略**：复用现有 test pattern（`conftest.py` + `mocker.patch`），不 mock 整个 HTTP 层，直接调用后端服务函数入口 `handle_artist_generate()`。

**关键 Mock 点**：
| Mock 目标 | 原因 | 方式 |
|-----------|------|------|
| `LLMClient.chat_stream` / `chat_stream_with_tools` | 不调用真实 LLM | `build_mock_artist_rounds()` → 返回预设 JSON |
| `generate_images_core` | 不调用真实图像 API | `AsyncMock(return_value=([url], 0, 0))` |
| `ImageContextResolver`（可选） | 无历史图片时不调用 | 无需 mock（首次会话无上下文） |

**自定义 Mock 构造器** `build_mock_artist_turn()`：
```python
def build_mock_artist_turn(reply_text: str, actions: list[dict] | None = None) -> AsyncMock:
    """
    构造一个 mock LLM，模拟 Artist 的 JSON 输出。
    
    返回的 async generator yield 格式：
      {"type": "token", "content": delta}  — SSE 流 token
      {"type": "usage", "tokens_in": N, "tokens_out": M}
    
    即使 Artist 用 chat_stream（非 chat_stream_with_tools），
    也统一用 stream_with_tools 的 mock 模式，因为最终流格式一致。
    
    关键：返回的 content 必须是 JSON 字符串（Artist 的 response_format=json_object），
    parse_artist_turn 会解析它。
    """
    full_json = json.dumps({
        "message": reply_text,
        "actions": actions or [],
        "next_phase": "idle" if not actions else "pack_ready",
    }, ensure_ascii=False)
    async def gen(*args, **kwargs):
        yield {"type": "token", "content": full_json}
        yield {"type": "usage", "tokens_in": 100, "tokens_out": 50}
    return gen
```

---

### Task 5.1: 场景 1 — 纯聊寒暄

**模拟对话**：
```
用户: 你好呀
Artist: 嗨！今天想画点什么？还是随便聊聊？
```

**Files:** `backend/tests/test_artist_e2e.py`

**Steps:**
- [ ] 1. Mock LLM 返回 JSON：`{"message": "嗨！今天想画点什么？还是随便聊聊？", "actions": [], "next_phase": "idle"}`
- [ ] 2. 调用 `handle_artist_generate(test_db, GenerateRequest(session_id=.., agent_persona="artist", prompt="你好呀"))`
- [ ] 3. 断言：`result["message_type"] == "artist"`
- [ ] 4. 断言：`result["images"]` 为空列表
- [ ] 5. 断言：`result["artist_turn"].actions` 为空（无生图 action）
- [ ] 6. 断言：`result["artist_turn"].reply_blocks[0]` 包含 "画点什么" 或纯文本回复
- [ ] 7. 断言：SSE 事件序列为 `[artist_turn_started, artist_reply_delta, artist_turn_done]`，无 `artist_action_started` / `artist_image_ready`

**Verification:**
- [ ] `pytest backend/tests/test_artist_e2e.py::test_chat_greeting -v` 通过

---

### Task 5.2: 场景 2 — 纯聊知识问答

**模拟对话**：
```
用户: 什么是赛博朋克风格？
Artist: 赛博朋克是科幻的一种分支，特点是高科技低生活，
        视觉上以霓虹灯、雨夜城市、义体改造为主...
```

**Files:** `backend/tests/test_artist_e2e.py`

**Steps:**
- [ ] 1. Mock LLM 返回 JSON：`{"message": "赛博朋克是科幻的一种分支，特点是...", "actions": [], "next_phase": "idle"}`
- [ ] 2. 调用 `handle_artist_generate(... prompt="什么是赛博朋克风格？")`
- [ ] 3. 断言：回复包含 "赛博朋克" + "霓虹" 或 "高科技" 等关键词
- [ ] 4. 断言：无生图 action，无图片产出
- [ ] 5. **关键断言**：JSON 解析成功，`message` 字段未被截断（验证 `chat_only` 不再被 200 字符截断）
- [ ] 6. 断言：`artist_turn.phase == "idle"`（纯聊后保持 idle，不进入生成状态机）

**Verification:**
- [ ] `pytest backend/tests/test_artist_e2e.py::test_chat_knowledge_question -v` 通过
- [ ] 验证 message 完整保留（长度 > 20）

---

### Task 5.3: 场景 3 — 聊 → 生图（单图）

**模拟对话**：
```
用户: 帮我画一只在太空中的猫
Artist: 收到！太空猫，听起来很有意思，我这就画。
       [生成中...]
       [图：一只穿宇航服的猫漂浮在星空中]
       画好了！这是你想要的太空猫吗？
```

**Files:** `backend/tests/test_artist_e2e.py`

**Steps:**
- [ ] 1. Mock LLM 返回 JSON：
  ```json
  {
    "message": "收到！太空猫马上安排。",
    "actions": [{"type": "generate_anchor", "prompt": "a cat in space, wearing astronaut suit, floating in starry cosmos, detailed, cinematic", "image_count": 1, "image_size": "1024x1024"}],
    "next_phase": "anchor_pending"
  }
  ```
- [ ] 2. Mock `generate_images_core` 返回 `(["https://fake.test/space_cat.png"], 0, 0)`
- [ ] 3. 调用 `handle_artist_generate(... prompt="帮我画一只在太空中的猫")`
- [ ] 4. 断言：`result["images"]` 包含 `space_cat.png`
- [ ] 5. 断言：`result["artist_turn"].actions[0].type == "generate_anchor"`
- [ ] 6. 断言：回复文本含 "收到" 或 "太空猫"
- [ ] 7. 断言 SSE 序列：
  ```
  artist_turn_started → artist_reply_delta → 
  artist_action_started → artist_image_ready → 
  artist_turn_done
  ```
- [ ] 8. 断言 `artist_turn_done.phase == "anchor_pending"`

**Verification:**
- [ ] `pytest backend/tests/test_artist_e2e.py::test_chat_then_generate_single -v` 通过

---

### Task 5.4: 场景 4 — 聊 → 生图（多步策略委托 Image Agent）

**模拟对话**：
```
用户: 做一套6个赛博朋克表情包
Artist: 表情包！我先生成一个锚点图，然后展开6个变体。稍等...
       [...委托 Image Agent 执行 radiate 策略...]
       [锚点图] [变体1-6]
       好了！看看哪个表情最满意？
```

**Files:** `backend/tests/test_artist_e2e.py`

**Steps:**
- [ ] 1. Mock Artist LLM 返回 JSON：
  ```json
  {
    "message": "表情包！我先出锚点再展开6个。",
    "actions": [{"type": "batch_execute", "series_prompts": ["赛博朋克猫表情1", "..."], "series_style_lock": true, "image_count": 6}],
    "next_phase": "producing"
  }
  ```
- [ ] 2. Mock `generate_images_core` —— 7 次调用（1 锚点 + 6 变体）
- [ ] 3. 调用入口后，验证：Artist 将 `batch_execute` 委托给 `_run_agent_mode_graph()`（或 `ExecutionEngine`）
- [ ] 4. 断言：`result["images"]` 长度为 7
- [ ] 5. 断言：`result["steps"]` 体现多步执行（有 `intent → planner → executor` 节点记录）
- [ ] 6. **关键断言**：Artist 的回复仍然出现在结果中（"表情包！我先出锚点..."），不因委托 Agent 而消失

**Verification:**
- [ ] `pytest backend/tests/test_artist_e2e.py::test_chat_then_generate_batch_radiate -v` 通过

---

### Task 5.5: 场景 5 — Clarification 交互

**模拟对话**：
```
用户: 画一只猫
Artist: 什么风格的猫？写实、卡通、赛博朋克还是水墨风？
用户: 赛博朋克风格
Artist: 明白了！一只赛博朋克风格的猫...
       [生成中...]
       [图]
```

**Files:** `backend/tests/test_artist_e2e.py`

**Steps:**
- [ ] 1. **Turn 1**：Mock LLM 返回 JSON：
  ```json
  {"message": "什么风格的猫？写实、卡通、赛博朋克还是水墨风？", "actions": [{"type": "ask_clarification", "message": "什么风格的猫？"}], "next_phase": "waiting_clarification"}
  ```
- [ ] 2. 调用 `handle_artist_generate(... prompt="画一只猫")`，断言 `phase == "waiting_clarification"`，无图片
- [ ] 3. **Turn 2**：用户回复 "赛博朋克风格"，Mock LLM 这次返回：
  ```json
  {"message": "明白了！赛博朋克猫，马上画。", "actions": [{"type": "generate_anchor", "prompt": "cyberpunk style cat, neon lights, mechanical parts, futuristic dystopia", "image_count": 1}], "next_phase": "anchor_pending"}
  ```
- [ ] 4. 调用 `handle_artist_generate(... prompt="赛博朋克风格")`（同一 session），断言 `phase == "anchor_pending"`，出图
- [ ] 5. **关键断言**：Turn 1 的状态（`waiting_clarification`）在 Turn 2 后正确转换为 `anchor_pending`

**Verification:**
- [ ] `pytest backend/tests/test_artist_e2e.py::test_chat_clarification_interaction -v` 通过

---

### Task 5.6: 场景 6 — 多轮连贯对话

**模拟对话**：
```
用户: 分析一下上一张图
Artist: 上一张是赛博朋克猫，霓虹灯调色，构图居中...有什么想调整的吗？
用户: 把背景色调暖一点，太蓝了
Artist: 好，给你改一下色温...
       [生成中...]
       [新图]
       现在背景暖了一些，猫的霓虹细节更突出了。
用户: 不错，这张很好
Artist: 谢谢！还有什么想画的吗？
```

**Files:** `backend/tests/test_artist_e2e.py`

**Steps:**
- [ ] 1. **Turn 1**：Mock LLM（self_critique 模式）返回：
  ```json
  {"message": "上一张是赛博朋克猫，霓虹灯调色，居中构图...有什么想调整的吗？", "actions": [], "next_phase": "idle"}
  ```
  断言：纯聊，无生图

- [ ] 2. **Turn 2**：用户说 "把背景色调暖一点"，Mock LLM 返回：
  ```json
  {"message": "好，给你改一下色温...", "actions": [{"type": "refine_target", "prompt": "warm up the background color temperature, less blue, more amber, keep the cyberpunk cat and neon details", "image_count": 1}], "next_phase": "refining"}
  ```
  断言：`generate_*` action 被触发，出图，`phase=refining`

- [ ] 3. **Turn 3**：用户 "不错，这张很好"，Mock LLM 返回：
  ```json
  {"message": "谢谢！还有什么想画的吗？", "actions": [], "next_phase": "idle"}
  ```
  断言：回复自然，phase 回到 idle

- [ ] 4. **关键断言**：三次 turns 的 `artist_turn_id` 递增，同一 session 的 `ArtistSessionState` 正确追踪阶段变化

**Verification:**
- [ ] `pytest backend/tests/test_artist_e2e.py::test_multiturn_conversation_with_refine -v` 通过

---

### Task 5.7: 场景 7 — 混合：评价 + 重新生成

**模拟对话**：
```
用户: 上次那张第三张太暗了，调亮一点
Artist: 我来调整...（如果 AI 能定位图3就精修，否则先确认）
       [生成中...]
       [新图]
       调亮了！效果如何？
```

**Files:** `backend/tests/test_artist_e2e.py`

**Steps:**
- [ ] 1. 前置：在当前 session 中有 3 张已生成图片（DB 中预插入 messages）
- [ ] 2. Mock LLM 返回 JSON：
  ```json
  {"message": "我来调整第三张...", "actions": [{"type": "replace_image", "prompt": "brighter version, increase exposure, keep same composition and subject", "replace_index": 2, "image_count": 1}], "next_phase": "refining"}
  ```
- [ ] 3. 调用入口，断言：`replace_image` action 的 `replace_index=2`（0-based，指向图3）
- [ ] 4. 断言：新图产出，`result["images"]` 不空
- [ ] 5. 断言：`ImageContextResolver` 参与了图片定位

**Verification:**
- [ ] `pytest backend/tests/test_artist_e2e.py::test_chat_evaluate_and_regenerate -v` 通过

---

### Task 5.8: 场景 8 — context_refs 自动携带 + SSE 校验

**场景**：验证从 SSE 事件中获取的 payload 在多个前后端流转环节中保持一致
- 用户发一条消息 → SSE 事件发出 → 前端收到 → 渲染

**Files:** `backend/tests/test_artist_e2e.py`

**Steps:**
- [ ] 1. 无需 mock LLM，用真实但预置的 SSE 事件流
- [ ] 2. Mock `task_manager.publish()`，收集所有发布的 `LamEvent`
- [ ] 3. 执行一个简单 turn（纯聊），收集 SSE 事件列表
- [ ] 4. 断言 SSE 事件序列格式正确：
  ```
  event_type = "task_progress"
  payload.type = "artist_turn_started"  → 含 session_id, correlation_id
  payload.type = "artist_reply_delta"    → 含 content（非空）
  payload.type = "artist_turn_done"      → 含 phase, active_branch（null 时也传）
  ```
- [ ] 5. 断言 `LamEvent.source_product == "imager"`
- [ ] 6. 断言 `LamEvent.event_id` 递增且唯一

**Verification:**
- [ ] `pytest backend/tests/test_artist_e2e.py::test_sse_event_payload_integrity -v` 通过

---

### Task 5.9: LSP Diagnostics & Build

**Steps:**
- [ ] 1. 后端：`lsp_diagnostics` 对 `backend/app/core/artist/`, `backend/app/services/generate_service.py`, `backend/app/routers/session.py` 无 error
- [ ] 2. 前端：`npm run build` 成功，无 type error
- [ ] 3. 后端：`py -3.14 -m uvicorn app.main:app --port 6171` 启动正常
- [ ] 4. 所有 8 个 Artist e2e 测试通过：`pytest backend/tests/test_artist_e2e.py -v`

**Verification:**
- [ ] 无 lint error
- [ ] Build 成功
- [ ] 8/8 tests passed

---

### 测试文件结构

`backend/tests/test_artist_e2e.py`:
```python
"""
Artist 端到端测试 — 自然语言场景
所有场景在一个文件内，模拟真实用户对话流程。
"""
from __future__ import annotations
import json
from unittest.mock import AsyncMock
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from app.schemas.session import GenerateRequest

# === Mock 构造器 ===
def build_mock_artist_turn(reply_text, actions=None, next_phase="idle"):
    """..."""

# === 场景 1 ===
async def test_chat_greeting(test_db, llm_provider, image_provider, test_session, mocker):
    ...

# === 场景 2 ===
async def test_chat_knowledge_question(test_db, ...):
    ...

# === 场景 3 ===
async def test_chat_then_generate_single(test_db, ...):
    ...

# === 场景 4 ===
async def test_chat_then_generate_batch_radiate(test_db, ...):
    ...

# === 场景 5 ===
async def test_chat_clarification_interaction(test_db, ...):
    ...

# === 场景 6 ===
async def test_multiturn_conversation_with_refine(test_db, ...):
    ...

# === 场景 7 ===
async def test_chat_evaluate_and_regenerate(test_db, ...):
    ...

# === 场景 8 ===
async def test_sse_event_payload_integrity(test_db, ...):
    ...
```

---

## Dependency Graph

```
Phase 0 (Restore) ──→ Phase 1 (Conversation) ──→ Phase 2 (Orchestration) ──→ Phase 3 (Frontend) ──→ Phase 4 (Video) ──→ Phase 5 (Tests)
                                                    │                                                        │
                                                    ├── 2.2 depends on 2.1                                  └── 5.1-5.8 依赖 Phase 2.3 完成
                                                    └── 2.3 depends on 2.2 + 2.4

Phase 5 内部无强顺序依赖（8 个场景独立），可并行编写：
  5.1 (寒暄)  5.2 (问答)  5.3 (单图)  5.4 (多步)  5.5 (澄清)  5.6 (多轮)  5.7 (重生成)  5.8 (SSE)
       ↓
  5.9 (Lint + Build) ← 全部通过后执行
```

## Key Decisions

1. **`llm_client.py` and `events/__init__.py` from stash are DISCARDED** — HEAD versions are authoritative. Stash versions were gutted to re-exports for a planned `lamtools-core` extraction that hasn't happened yet.

2. **Artist delegates to Image Agent, not the other way around** — Artist owns the conversation. When Artist decides `generate_*`, it delegates to the 9-node graph. When it decides `chat_only`, it responds directly.

3. **Unified test file: `backend/tests/test_artist_e2e.py`** — 所有 8 个端到端场景集中在一个文件。每个函数对应一个自然语言对话流程，从用户输入到 Artist 回复的完整链路。不做分散测试。

4. **Unified message_type: `'artist'`** — not a separate message type. Artist turns that include images also have `message_type='artist'`. Pure chat turns also use `'artist'`. This simplifies the `MessageList` switch.

5. **SSE event_type is always `'task_progress'`** — both `agent_*` and `artist_*` payloads go through `event_type='task_progress'`. The `payload.type` discriminates. This is how the existing Agent events work and Artist events should follow the same pattern.

6. **Video Agent is a placeholder** — reserved in schemas and action types, but no execution implementation. Artist's `_execute_action` has a TODO comment for video actions.
