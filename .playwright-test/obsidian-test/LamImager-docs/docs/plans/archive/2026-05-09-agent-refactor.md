# Agent 模式重构实施计划

> **For agentic workers:** Use executing-plans skill to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 agent 工具复用已有服务层逻辑，消除冗余代码，修复所有已知 bug，并实现流式 token 输出。

**Architecture:** 分两阶段——Phase A 修复正确性问题（bug fix + 重构复用），Phase B 实现流式 agent loop。

**Tech Stack:** Python / FastAPI / SQLAlchemy async，无新依赖。

---

## Phase A：正确性修复与重构

### Task 1: 修复 `image_search.py` 重复类体

**Files:** `backend/app/tools/image_search.py`

**Steps:**
- [ ] 删除第 66–137 行（第二个重复的 `parameters` 和 `execute` 定义）
- [ ] 保留第 1–65 行（使用 `_search_with_retry` 的正确实现）

**Verification:**
- [ ] 文件只有一个 `parameters` 和一个 `execute`，且 `execute` 调用 `_search_with_retry`

**Commit:** `fix(tools): remove duplicate ImageSearchTool class body`

---

### Task 2: 修复 `plan` 工具的 `generate` 占位符

**Files:** `backend/app/tools/plan.py`, `backend/app/services/agent_service.py`

**Steps:**
- [ ] `plan.py` `description` 字符串：删除第 4 行 `"4. generate — 根据需求生成一个新的计划..."` 以及第 1 行 `"支持四种操作"` 改为 `"支持三种操作"`
- [ ] `plan.py` `action` 参数 `description`：删除 `, generate=生成新计划` 字样
- [ ] `agent_service.py` `AGENT_SYSTEM_PROMPT`：检查是否提及 `generate` action，若有则删除

**Verification:**
- [ ] `plan.py` 和 `AGENT_SYSTEM_PROMPT` 中不再出现 `generate` action 描述

**Commit:** `fix(tools): remove unimplemented plan generate action`

---

### Task 3: 修复 `_execute_radiate` items 回退错误

**Files:** `backend/app/services/generate_service.py`

**Steps:**
- [ ] 找到 `plan_meta.get("items", data.agent_tools)` 这行
- [ ] 改为 `items = plan_meta.get("items") or []`
- [ ] 若 `items` 为空列表，提前返回错误消息

**Verification:**
- [ ] 当 plan meta 缺少 `items` 时，函数返回明确错误消息，不使用工具名列表

**Commit:** `fix(generate): _execute_radiate items fallback must not use agent_tools`

---

### Task 4: 将 `_urls_to_base64` 移入 `ImageClient`

**Files:** `backend/app/utils/image_client.py`, `backend/app/tools/generate_image.py`

**Steps:**
- [ ] 在 `image_client.py` 中新增静态方法 `ImageClient.urls_to_base64(urls: list[str]) -> list[str]`，内容从 `generate_image.py` 的 `_urls_to_base64` 复制
- [ ] `generate_image.py` 删除 `_urls_to_base64` 函数，改为调用 `ImageClient.urls_to_base64()`
- [ ] 删除 `generate_image.py` 中因 `_urls_to_base64` 而引入的 `import aiohttp`（如无其他使用）

**Verification:**
- [ ] `generate_image.py` 不再定义 `_urls_to_base64`
- [ ] `image_client.py` 有 `urls_to_base64` 静态方法

**Commit:** `refactor(image_client): move urls_to_base64 to ImageClient`

---

### Task 5: 提取 `generate_images_core` 函数

**Files:** `backend/app/services/generate_service.py`

**背景:** `handle_generate()` 中的 3 层降级生图逻辑（`chat_edit` → `edit` → vision fallback）需要被工具复用，但 `handle_generate()` 本身还负责 session 消息和计费，不能直接调用。

**Steps:**
- [ ] 新增函数签名：
  ```python
  async def generate_images_core(
      db: AsyncSession,
      provider_id: str,
      prompt: str,
      image_count: int = 1,
      image_size: str = "1024x1024",
      reference_images: list[str] | None = None,
      negative_prompt: str = "",
  ) -> list[str]:
  ```
- [ ] 函数内容：查询 provider → 解密 key → 构建 `ImageClient` → 执行 3 层降级逻辑 → 返回 URL 列表
- [ ] 3 层降级逻辑从 `handle_generate()` 现有代码中提取移动
- [ ] `handle_generate()` 内部改为调用 `generate_images_core()`，行为不变

**Verification:**
- [ ] `handle_generate()` 生图部分代码量明显减少，逻辑委托给 `generate_images_core`
- [ ] `generate_images_core` 无 session/billing 副作用

**Commit:** `refactor(generate): extract generate_images_core for reuse`

---

### Task 6: 重写 `generate_image` 工具，复用 `generate_images_core`

**Files:** `backend/app/tools/generate_image.py`

**Steps:**
- [ ] `execute()` 改为从 `kwargs` 取 `db` 和 `image_provider_id`
- [ ] 调用 `generate_images_core(db, image_provider_id, prompt, count, image_size, reference_base64)`
- [ ] `reference_urls` 处理：调用 `ImageClient.urls_to_base64()` 转换后传入
- [ ] `_generate_grid` 内部同样改为调用 `generate_images_core` 而非直接 `client.generate()`
- [ ] 删除工具内所有直接 `ImageClient` 实例化和 `client.generate()` / `client.chat_edit()` 调用
- [ ] 删除不再需要的 `import`（`PIL`、`aiohttp` 若已无直接使用）

**Verification:**
- [ ] `generate_image.py` 不再直接实例化 `ImageClient`
- [ ] agent 生图路径享有与普通生图相同的 3 层降级保护

**Commit:** `refactor(tools): generate_image tool delegates to generate_images_core`

---

### Task 7: `agent_service.py` 注入 `image_provider_id` 和 `image_size`

**Files:** `backend/app/services/agent_service.py`

**Steps:**
- [ ] 保留 `image_provider` 查询逻辑，但 `exec_kwargs` 改为注入：
  ```python
  exec_kwargs["image_provider_id"] = image_provider.id if image_provider else ""
  exec_kwargs["image_size"] = image_size
  ```
- [ ] 删除 `exec_kwargs["image_api_key"]`、`exec_kwargs["image_base_url"]`、`exec_kwargs["image_model_id"]` 三行
- [ ] 删除 `image_api_key`、`image_base_url`、`image_model_id` 三个局部变量（及相关的 `decrypt` 调用）
- [ ] `image_size` 读取：复用 `settings_service.get_setting(db, "default_image_size")`，默认 `"1024x1024"`

**Verification:**
- [ ] `agent_service.py` 不再解密 image provider 的 API key
- [ ] `image_size` 正确注入

**Commit:** `fix(agent): inject image_provider_id and image_size, remove raw credential passing`

---

### Task 8: 清理次要问题

**Files:** `backend/app/utils/image_client.py`, `backend/app/services/generate_service.py`, `backend/app/utils/llm_client.py`

**Steps:**
- [ ] `image_client.py`: `logging.info` 打印图像数据的行改为 `logging.debug`
- [ ] `generate_service.py`: `limit(10)` + `[-8:]` 改为 `limit(8)`
- [ ] `llm_client.py`: 全局搜索 `chat_stream_with_tools` 的调用方；确认无调用方后删除该方法

**Verification:**
- [ ] `image_client.py` 无 `logging.info` 打印图像前缀
- [ ] `chat_stream_with_tools` 已删除

**Commit:** `chore: cleanup logging, dead code, redundant slice`

---

## Phase B：流式 Agent Loop

### Task 9: `llm_client.py` 新增流式 + 工具调用方法

**Files:** `backend/app/utils/llm_client.py`

**背景:** 当前 agent loop 使用非流式 `chat()`，用户看不到逐 token 输出。需要一个能同时流式输出 token 又能处理 tool_calls 的方法。

**Steps:**
- [ ] 新增方法 `chat_stream_with_tools(messages, tools, temperature) -> AsyncGenerator`，yield 两种事件：
  - `{"type": "token", "content": "..."}` — 每个 token delta
  - `{"type": "tool_calls", "tool_calls": [...]}` — 当 `finish_reason == "tool_calls"` 时，yield 完整的 tool_calls 列表
- [ ] 内部使用 `stream=True`，累积 tool call deltas（按 `index` 合并）
- [ ] 删除旧的同名方法（如果存在且未被使用）

**Verification:**
- [ ] 方法能正确 yield token 事件和 tool_calls 事件
- [ ] tool call arguments 正确拼接（多个 delta 合并为完整 JSON 字符串）

**Commit:** `feat(llm_client): add streaming chat_stream_with_tools method`

---

### Task 10: `agent_service.py` 改用流式 LLM 调用

**Files:** `backend/app/services/agent_service.py`

**Steps:**
- [ ] `run_agent_loop` 每轮将 `client.chat(...)` 替换为 `client.chat_stream_with_tools(...)`
- [ ] 处理流式事件：
  - `token` 事件 → 直接 `yield TokenEvent(content=delta)`（逐 token，非整段）
  - `tool_calls` 事件 → 提取 tool_calls，后续逻辑不变
- [ ] `usage` token 计数：从流末尾的最后一个 chunk 中提取 `usage`；若 API 不返回，使用 `len(content) // 4` 估算 `tokens_out`，`tokens_in` 用 `len(str(messages)) // 4` 估算

**Verification:**
- [ ] agent 运行时，SSE 事件流中出现多个 `token` 事件（逐 token），而非一次性整段
- [ ] tool_calls 仍能正确触发工具执行

**Commit:** `feat(agent): switch agent loop to streaming LLM calls`

---

## 执行顺序

```
Phase A:
  Tasks 1, 2, 3  — 独立，可并行
  Task 4         — 独立
  Task 5         — 独立（为 Task 6 前置）
    Task 6       — 依赖 Task 4 + Task 5
      Task 7     — 依赖 Task 6
  Task 8         — 独立

Phase B:
  Task 9 → Task 10（串行）
```

Phase A 全部完成并验证后，再执行 Phase B。
