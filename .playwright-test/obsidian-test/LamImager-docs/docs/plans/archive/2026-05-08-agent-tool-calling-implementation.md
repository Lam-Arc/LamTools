# Agent 工具调用系统 — 实施计划

> **For agentic workers:** Use executing-plans or subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 LamImager 引入 Function Calling 基础设施 + Serper 网络/图片搜索，双入口（侧边栏 + Agent 模式）共享同一工具库。

**Architecture:** 新建 `tools/` 工具包 + `agent_service.py` 编排器，LLM 自主决策调用工具 → 执行 → 结果注入循环。SSE 流式输出 tool_call/tool_result/token/done 事件。

**Tech Stack:** Python 3.14+ / FastAPI / aiohttp / Serper.dev API / Vue3 / TypeScript

---

## Task 1: 后端模型和 Schema 扩展

**Files:** 
- `backend/app/models/api_provider.py`
- `backend/app/models/message.py`
- `backend/app/schemas/session.py`
- `backend/app/schemas/prompt.py`

**Steps:**
- [ ] 在 `ApiProviderProviderType` 枚举中新增 `tool = "tool"`
- [ ] 在 `MessageType` 枚举中新增 `agent = "agent"`
- [ ] 在 `GenerateRequest` 中新增 3 个字段：`agent_mode: bool = False`、`agent_tools: list[str] = []`、`agent_plan_strategy: str = ""`
- [ ] 在 `prompt.py` `PromptOptimizeRequest` 中新增 `tools: list[str] | None = None`（或在 routers 的 StreamRequest 中新增；根据实际使用位置决定 — 侧边栏 stream chat 用 StreamRequest，故在 `routers/prompt.py` 的 `StreamRequest` 中新增 `tools: list[str] | None = None`）

**Verification:**
- [ ] 运行 `cd backend && python -c "from app.models.api_provider import ProviderType; print(ProviderType.tool.value)"` 输出 `tool`
- [ ] 运行 `cd backend && python -c "from app.models.message import MessageType; print(MessageType.agent.value)"` 输出 `agent`
- [ ] 运行 `cd backend && python -c "from app.schemas.session import GenerateRequest; g=GenerateRequest(prompt='test',agent_mode=True,agent_tools=['web_search']); print(g.agent_mode,g.agent_tools)"` 无错误

**Commit:** `feat: extend models/schemas for agent tool calling support`

---

## Task 2: 工具抽象层 + 注册表

**Files:**
- `backend/app/tools/__init__.py` (新建)
- `backend/app/tools/base.py` (新建)

**Steps:**

`tools/base.py`:
- [ ] 创建 `ToolResult` dataclass：`content: str`、`meta: dict | None = None`
- [ ] 创建 `Tool` 抽象基类：类级别属性 `name: str`、`description: str`、`parameters: dict`（JSON Schema），方法 `async execute(self, **kwargs) -> ToolResult`、`to_openai_schema(self) -> dict`

`tools/__init__.py`:
- [ ] 创建 `ToolRegistry` 类：
  - `_tools: dict[str, Tool] = {}`
  - `register(tool: Tool)` — 注册工具
  - `get(name: str) -> Tool | None` — 按名查找
  - `list_openai_schemas() -> list[dict]` — 返回所有工具的 OpenAI function schema
  - `list_for_openai(tool_names: list[str] | None) -> list[dict] | None` — 返回指定工具的 schema，None=不启用工具
- [ ] 创建模块级单例 `registry = ToolRegistry()`
- [ ] 创建 `register_tool(tool: Tool) -> Tool` 装饰器风格函数

**Verification:**
- [ ] 运行 `cd backend && python -c "from app.tools.base import Tool, ToolResult; print(ToolResult(content='test'))"` 无错误
- [ ] 运行 `cd backend && python -c "from app.tools import registry; print(type(registry))"` 输出 `<class 'app.tools.ToolRegistry'>`

**Commit:** `feat: add tool abstraction layer and registry`

---

## Task 3: Serper 搜索工具

**Files:**
- `backend/app/tools/web_search.py` (新建)
- `backend/app/tools/image_search.py` (新建)

**Steps:**

`tools/web_search.py`:
- [ ] 创建 `WebSearchTool(Tool)`：
  - `name = "web_search"`
  - `description = "搜索互联网获取最新信息、参考和趋势。适用于查找设计风格、VI规范、色彩方案等。"`
  - `parameters`：`query`(string, required)、`max_results`(integer, default=5)
  - `execute()`：调用 `POST https://google.serper.dev/search`，读取 `SERPER_API_KEY` 从 `app.config` 或环境变量，解析返回的 `organic[]` 列表，构造 `ToolResult(content=每条:"N. [title](url)\n  snippet", meta={sources:[], query})`

`tools/image_search.py`:
- [ ] 同 `WebSearchTool` 模式，`name = "image_search"`，URL 改为 `https://google.serper.dev/images`，解析 `images[]` 列表，返回 `content` 含图片标题+URL+来源，`meta` 含图片URL数组供前端展示

**注意**：API Key 从 `os.getenv("SERPER_API_KEY")` 读取，后续可通过 ApiProvider 管理。

**Verification:**
- [ ] 临时设 `SERPER_API_KEY` 环境变量，运行 `cd backend && python -c "import asyncio; from app.tools.web_search import WebSearchTool; t=WebSearchTool(); r=asyncio.run(t.execute(query='test',max_results=2)); print(r.content[:100])"` 输出搜索结果

**Commit:** `feat: add Serper web_search and image_search tools`

---

## Task 4: LLM Client 扩展 — Function Calling 支持

**Files:**
- `backend/app/utils/llm_client.py`

**Steps:**
- [ ] 在 `chat()` 方法新增参数 `tools: list[dict] | None = None`、`tool_choice: str = "auto"`，在 payload 中条件加入 `tools` 和 `tool_choice`
- [ ] 新增方法 `chat_stream_with_tools()` — 类似 `chat_stream` 但在 payload 中加入 tools，且 yield 的对象改为带 `type` 字段的 dict：
  - `{"type": "token", "content": "..."}` — 文本 token
  - `{"type": "tool_call_delta", "tool_calls": [...]}` — 工具调用增量（需累积 index→name→arguments）
  - `{"type": "usage", "tokens_in": ..., "tokens_out": ...}` — usage
- [ ] 新增静态方法 `extract_tool_calls(response: dict) -> list[dict]` — 从非流式响应提取 `choices[0].message.tool_calls`

**Verification:**
- [ ] 运行 `cd backend && python -c "from app.utils.llm_client import LLMClient; print(hasattr(LLMClient, 'extract_tool_calls'))"` 输出 `True`

**Commit:** `feat: extend LLMClient with function calling support`

---

## Task 5: AgentService — 工具调用编排器

**Files:**
- `backend/app/services/agent_service.py` (新建)

**Steps:**
- [ ] 定义 `AgentEvent` 类型（dataclasses）：`TokenEvent(content)`、`ToolCallEvent(name, args)`、`ToolResultEvent(name, content, meta)`、`DoneEvent(tokens_in, tokens_out, cost)`
- [ ] 创建异步生成器 `run_agent_loop(db, provider_id, messages, tools, session_id, max_rounds=5, checkpoints=None, signal=None) -> AsyncGenerator[AgentEvent]`:
  - 循环（最多 max_rounds 轮）：
    1. 调用 `LLMClient.chat(messages, tools=tool_schemas)` — 非流式
    2. 提取 content 文本 — yield `TokenEvent(content)`
    3. 提取 tool_calls — 若无 → break
    4. 对每个 tool_call：
       - yield `ToolCallEvent(name, args)`
       - 若 name 在 checkpoints 中 → 挂起等待（后续 Phase 2 实现，当前 yield toolkit_call 后直接执行）
       - 从 `registry.get(name)` 获取工具 → `await tool.execute(**args)`
       - yield `ToolResultEvent(name, result.content, result.meta)`
       - 将 tool result 作为 `role: "tool"` 消息追加到 messages
    5. 将 assistant message（含 tool_calls）追加到 messages，继续下一轮
  - 根据 usage 计算 cost，调用 `record_billing()`（detail.type="agent"）
  - yield `DoneEvent` + 最终计数
- [ ] 错误处理：LLM 调用失败、工具执行失败 → yield 错误信息 + break

**Verification:**
- [ ] 临时 mock 一个工具 `mock_tool(name="echo", execute=lambda x: ToolResult(content=x))` 注册到 registry，用 mock LLM 响应测试 AgentLoop 流式输出

**Commit:** `feat: add AgentService with tool calling orchestration`

---

## Task 6: 侧边栏流式聊天接入工具

**Files:**
- `backend/app/routers/prompt.py`
- `backend/app/services/prompt_optimizer.py`

**Steps:**

`routers/prompt.py`:
- [ ] `StreamRequest` 新增字段 `tools: list[str] | None = None`（在 Task 1 已做则跳过）
- [ ] `api_stream_chat` 中若 `data.tools` 非空，调用 `agent_service.run_agent_loop()` 替代 `stream_llm_chat`，将 agent events 转为 SSE 行

`services/prompt_optimizer.py`:
- [ ] `stream_llm_chat` 函数签名新增 `tools: list[str] | None = None` 参数

**Verification:**
- [ ] 运行 `cd backend && uvicorn app.main:app --port 8000`，用 curl 测试 `POST /api/prompt/stream` 带 `tools:["web_search"]` 参数，观察 SSE 输出

**Commit:** `feat: wire tool calling into sidebar stream chat endpoint`

---

## Task 7: 会话 Agent 模式接入

**Files:**
- `backend/app/routers/session.py`
- `backend/app/services/generate_service.py`

**Steps:**

`routers/session.py`:
- [ ] `api_generate` 中若 `data.agent_mode` 为 True，调用新增的 `handle_agent_generate(db, data)` 替代 `handle_generate`

`services/generate_service.py`:
- [ ] 新增函数 `handle_agent_generate(db, data: GenerateRequest) -> dict`：
  1. 保存用户消息（同现有 `handle_generate`）
  2. 构建 agent messages：`[{"role":"system","content":AGENT_SYSTEM_PROMPT}, {"role":"user","content":prompt}]`
  3. 获取 LLM provider（优化用的 default provider）
  4. 调用 `agent_service.run_agent_loop(...)` 
  5. 收集所有 events，汇总 tool_calls 序列 + images + final text
  6. 将 agent 执行结果作为 `message_type="agent"` 的消息存储
  7. 若 agent 调用生成了图片 → 以 `message_type="image"` 额外存储图片消息
  8. 计费已由 agent_service 内部处理
- [ ] 定义 `AGENT_SYSTEM_PROMPT` 常量：指导 LLM 使用搜索工具辅助生图

**Verification:**
- [ ] curl 测试 `POST /api/sessions/{id}/generate` 带 `agent_mode:true, agent_tools:["web_search"]`

**Commit:** `feat: add agent mode to session generate endpoint`

---

## Task 8: 计费扩展

**Files:**
- `backend/app/services/billing_service.py`

**Steps:**
- [ ] 在 `TYPE_LABELS` 字典中新增 `"agent": "AI Agent"`、`"tool": "工具调用"`
- [ ] 确保 Agent 产生的计费记录（detail.type="agent" 或 "tool"）在 breakdown 中正确归类

**Verification:**
- [ ] 运行 `cd backend && python -c "from app.services.billing_service import get_breakdown; print('agent' in {'agent':'AI Agent'})"` 无错误

**Commit:** `feat: add agent and tool billing type labels`

---

## Task 9: 前端类型扩展

**Files:**
- `frontend/src/types/index.ts`

**Steps:**
- [ ] `Message.message_type` 联合类型新增 `'agent'`
- [ ] `GenerateRequest` 接口新增 `agent_mode?: boolean`、`agent_tools?: string[]`、`agent_plan_strategy?: string`
- [ ] `ApiProvider.provider_type` 联合类型新增 `'tool'`
- [ ] 新增 `AgentStepEvent` 接口：`{ type: 'tool_call' | 'tool_result'; name: string; args?: Record<string,unknown>; content?: string; meta?: Record<string,unknown> }`

**Verification:**
- [ ] 运行 `cd frontend && npx tsc --noEmit` 无新增类型错误

**Commit:** `feat: add frontend types for agent tool calling`

---

## Task 10: 前端 API 客户端扩展

**Files:**
- `frontend/src/api/prompt.ts`
- `frontend/src/api/session.ts`

**Steps:**

`prompt.ts`:
- [ ] `streamChat` 方法新增 `tools?: string[]` 参数，body 中传入 `tools`
- [ ] `streamChat` 的 SSE 解析扩展：识别 `tool_call`、`tool_result` 事件，通过新的 `streamChatWithTools` async generator yield `{type: 'token'|'tool_call'|'tool_result'|'done', data}` 结构

`sessions.ts`:
- [ ] `generate` 方法 body 新增 `agent_mode`、`agent_tools`、`agent_plan_strategy` 字段

**Verification:**
- [ ] 在 console 中 import promptApi 测试 `streamChat` 新签名接受 tools 参数

**Commit:** `feat: extend frontend API clients for agent tool events`

---

## Task 11: 侧边栏搜索开关 + 工具调用卡片

**Files:**
- `frontend/src/views/Sessions.vue`

**Steps:**
- [ ] 侧边栏 assistant 面板底部输入栏：在现有输入框右侧新增搜索开关（toggle switch），变量 `searchEnabled: ref(false)`
- [ ] 发送时若 `searchEnabled` 为 true，`streamChat` 调用传入 `tools: ['web_search', 'image_search']`
- [ ] 接收 SSE 流时，`tool_call` 事件 → 在对话区渲染工具调用卡片（可折叠：显示工具名+参数）
- [ ] `tool_result` 事件 → 更新对应卡片显示结果摘要
- [ ] 工具调用结束后，后续 token 正常流式渲染文字
- [ ] 卡片样式：`border: 1px solid var(--border); border-radius: var(--radius); padding: 8px 12px; margin: 4px 0;` 折叠时显示工具名，展开时显示参数和结果

**Verification:**
- [ ] 打开侧边栏对话框，开启搜索开关，输入"搜索赛博朋克风格的特点"，观察工具调用卡片出现并展示搜索结果

**Commit:** `feat: add search toggle and tool call cards to assistant sidebar`

---

## Task 12: Agent 模式切换 + Agent 执行卡片

**Files:**
- `frontend/src/views/Sessions.vue`

**Steps:**
- [ ] 会话输入栏左侧新增 Agent 模式切换按钮 `🧠 Agent`（使用 lucide `Brain` 图标），变量 `agentMode: ref(false)`
- [ ] Agent 模式激活时：隐藏技能选择器、优化方向、图片数量、图片尺寸、负向词输入；仅保留规划策略选择器 + 搜索开关
- [ ] 发送时传入 `agent_mode: true, agent_tools: [...]`，`generate` API 扩展相应字段
- [ ] 消息区新增 Agent 执行卡片组件（在现有消息列表条件渲染）：
  - 卡片头部："🧠 Agent 执行中..."
  - 步骤列表：每步显示序号、工具名、状态（执行中/完成）
  - 完成后的图片以现有图片网格渲染
- [ ] 卡片样式：`background: var(--card); border-left: 3px solid #000; padding: 16px; margin: 8px 0;`

**Verification:**
- [ ] 点击 Agent 模式按钮，确认输入区控件切换。发送"帮我查一下赛博朋克风格的特点然后生成一张图"，观察 Agent 执行卡片实时展示步骤。

- [ ] **必须手动启动后端测试**，通过实际 Serper API Key 验证完整的 Agent 流程（搜索 → 结果 → 生成）

**Commit:** `feat: add agent mode toggle and execution card to session UI`

---

## 附录：后续 LangGraph 迁移要点

当前 AgentLoop 设计已预留的三个迁移锚点：

1. **Tool 接口**：`Tool.execute()` 签名与 `langchain_core.tools.BaseTool._arun()` 对齐
2. **AgentLoop 挂起**：`checkpoints` 参数位置对应 `graph.interrupt_before` 配置
3. **SSE 事件**：`AgentEvent` 类型直接映射到 `graph.astream_events()` 的事件模型

迁移时替换范围限于 `agent_service.py`，其余代码零改动。
