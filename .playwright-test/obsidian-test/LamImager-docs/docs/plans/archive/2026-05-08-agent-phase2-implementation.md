# Agent Phase 2: 打通输入到生成全流程 — 实施计划

> **For agentic workers:** Use executing-plans to implement this plan task-by-task.

**Goal:** Agent 模式新增 `generate_image` 和 `plan` 工具，LLM 自主搜索→规划→生图，结果即时存入会话。

**Architecture:** 工具直接调用现有 Service/Client（薄包装），搜索工具内部机械重试 3 次，AgentLoop 注入 image_provider。

**Tech Stack:** Python 3.14+ / FastAPI / aiohttp / Vue3 / TypeScript

---

## Task 1: generate_image 工具

**Files:** `backend/app/tools/generate_image.py` (新建)

**Steps:**
- [ ] 创建 `GenerateImageTool(Tool)`：
  - `name = "generate_image"`, `description` 说明可生成 N 张图、可选参考图 URL
  - `parameters`: `prompt`(str,required), `count`(int,default=1), `reference_urls`(list[str],optional)
  - `execute()`: 接收 `api_key`, `base_url`, `model_id`, `image_size` 从 kwargs，`reference_urls` → `fetchImageAsBase64(url)` → `ImageClient(*).generate()` → `extract_images()`。支持 `count > 1` 时 `asyncio.gather` 并行。
  - 返回 `ToolResult(content="已生成N张", meta={image_urls: [...]})`

**Verification:**
- [ ] `cd backend && python -c "from app.tools.generate_image import GenerateImageTool; print(GenerateImageTool().name)"` 输出 `generate_image`

**Commit:** `feat: add generate_image tool wrapping ImageClient`

---

## Task 2: plan 工具

**Files:** `backend/app/tools/plan.py` (新建)

**Steps:**
- [ ] 创建 `PlanTool(Tool)`：
  - `name = "plan"`, `description` 说明四种 action
  - `parameters`: `action`(str, enum:list/apply/create/generate), `template_id`(str), `variables`(dict), `name`(str), `description`(str), `steps`(list), `strategy`(str)
  - `execute(action, **kwargs)`: 路由到对应 Service：
    - `list` → `plan_template_service.list_templates(db)` → 返回模板摘要列表
    - `apply` → `get_template(db, id)` → `apply_template(db, template, variables)` → 返回步骤列表
    - `create` → `create_template(db, data)` → 返回新模板 ID
    - `generate` → 返回提示 LLM 自行生成计划（不调 API，由 system prompt 驱动）
  - db session 从 kwargs 注入

**Verification:**
- [ ] `cd backend && python -c "from app.tools.plan import PlanTool; print(PlanTool().name)"` 输出 `plan`

**Commit:** `feat: add plan tool wrapping plan_template_service`

---

## Task 3: 搜索工具内部重试

**Files:** `backend/app/tools/web_search.py`, `backend/app/tools/image_search.py` (修改)

**Steps:**
- [ ] 两个文件各新增 `_search_with_retry(query, api_key, max_retries=3)` 内部函数：
  - 每次 retry 在 query 后追加不同限定词（"参考"、"设计"、"trending"），或用英文重搜
  - 收集所有 attempt 的结果，取 `organic`/`images` 条数最多的作为最优结果
  - 返回 `(content, sources, attempts_count, best_attempt_index)`
- [ ] `execute()` 改为调用 `_search_with_retry`，meta 新增 `attempts` 和 `best_attempt`

**Verification:**
- [ ] `cd backend && python -c "from app.tools.web_search import WebSearchTool; print('retry' in str(WebSearchTool.execute.__code__.co_names))"` 验证重试逻辑存在

**Commit:** `feat: add internal retry (3x) to search tools`

---

## Task 4: AgentService 扩展

**Files:** `backend/app/services/agent_service.py` (修改)

**Steps:**
- [ ] 新增 `WarningEvent(type="tool_warning", name, reason, retry_count)` dataclass
- [ ] `run_agent_loop` 查找 image_provider（`ProviderType.image_gen` 且 `is_active`），解密 key，注入 `exec_kwargs["api_key"]` + `["base_url"]` + `["model_id"]` + `["image_size"]`
- [ ] 工具执行前后不变，WarningEvent 仅在搜索工具返回 `meta.attempts >= retry_count` 且有内容贫乏时触发（当前暂不主动触发，预留类型）
- [ ] `_stream_with_tools` (in routers/prompt.py) 新增 `tool_warning` 事件 SSE 发送

**Verification:**
- [ ] `cd backend && python -c "from app.services.agent_service import WarningEvent; print(WarningEvent(type='tool_warning').type)"` 输出 `tool_warning`

**Commit:** `feat: add WarningEvent and image provider injection to AgentLoop`

---

## Task 5: 注册新工具

**Files:** `backend/app/tools/__init__.py` (修改)

**Steps:**
- [ ] 导入 `GenerateImageTool` 和 `PlanTool`
- [ ] `registry.register(GenerateImageTool())` + `registry.register(PlanTool())`

**Verification:**
- [ ] `cd backend && python -c "from app.tools import registry; names = [t.name for t in registry._tools.values()]; print(names)"` 输出 `['web_search', 'image_search', 'generate_image', 'plan']`

**Commit:** `feat: register generate_image and plan tools`

---

## Task 6: 生图结果即时存入消息

**Files:** `backend/app/services/generate_service.py` (修改)

**Steps:**
- [ ] `handle_agent_generate` 中 ToolResultEvent(name="generate_image") 时：
  - 从 `event.meta.image_urls` 取 URL 列表
  - `await add_system_message(message_type="image", metadata={image_urls, prompt})`
  - 累积到 `accumulated_images` 列表
- [ ] 最终 agent message metadata 新增 `images: accumulated_images`

**Verification:**
- [ ] `cd backend && python -c "from app.services.generate_service import handle_agent_generate; print('OK')"`

**Commit:** `feat: save generated images as messages during agent mode`

---

## Task 7: 后端验证

**Files:** 无

**Steps:**
- [ ] `cd backend && python -c "from app.main import app; print('Backend OK')"`
- [ ] `cd backend && python -c "from app.tools import registry; [print(t.name) for t in registry._tools.values()]"`

**Verification:**
- [ ] 输出含 `generate_image` 和 `plan`

**Commit:** 无（验证步骤）

---

## 实施顺序

```
Task 1 → Task 2 → Task 3 → Task 4 → Task 5 → Task 6 → Task 7
 (独立)   (独立)   (依赖1,2) (依赖5)   (依赖1,2) (依赖4,5) (整体验证)
```
