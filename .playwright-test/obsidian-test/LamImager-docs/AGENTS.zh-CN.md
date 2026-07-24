# LamImager - AI 图像生成管理器

## 项目概述

LamImager 是一个全栈 AI 图像生成应用，采用对话式界面。它管理 API 提供商，协调图像生成（可选 LLM 驱动的规划和提示词优化），追踪账单，并提供极简的 Vue3 前端。

## 架构

- **后端**: Python 3.14+ / FastAPI / SQLAlchemy (async) / aiosqlite
- **单体架构**: FastAPI 同时提供 API 和 Vue3 静态文件
- **数据库**: SQLite 配合 async SQLAlchemy，API 密钥使用 AES-256-GCM 加密
- **前端**: Vue3 SPA 配合 Pinia 状态管理，开发时通过 Vite 代理
- **UI**: 对话式界面，支持会话管理，LLM 助手侧边栏

## 关键目录

```
backend/app/
├── main.py              # 入口，路由注册
├── config.py            # 配置 (DATA_DIR, DB_URL, CORS)
├── database.py          # 异步引擎，session maker
├── models/              # SQLAlchemy 模型 (10 张表)
├── routers/             # FastAPI 路由 (11 个模块，50+ 端点)
├── services/            # 业务逻辑 (16 个服务: agent_bridge, agent_intent, agent_service, api_manager, billing, generate, plan_execution, plan_template, planning_context, prompt_optimizer, reference, rule_engine, session_manager, settings, skill_engine, task_manager)
│   └── executors/       # 4 个策略执行器 (single, parallel, iterative, radiate) + base + utils
├── schemas/             # Pydantic 请求/响应模型
├── tools/               # Agent Function Calling 工具 (web_search, image_search, generate_image, plan)
└── utils/               # crypto.py, llm_client.py, image_client.py (generate, edit, chat_edit, extract_images, extract_images_from_chat, urls_to_base64)

frontend/src/
├── views/               # 8 个页面组件 (Sessions.vue 是主页面)
├── api/                 # Axios API 客户端 (12 个模块，含 sse.ts)
├── stores/              # Pinia stores (provider, billing, session)
├── composables/         # 可复用组合式函数 (useSessionEvents, useDialog, useMarkdown, useDownload)
├── components/          # 共享组件 (ConfirmDialog, ErrorBoundary)
│   └── session/         # 会话页子组件 (15 个)
├── types/               # TypeScript 接口
└── styles/              # 全局 CSS (黑白灰配色)
```

## 数据模型

| 模型 | 用途 |
|------|------|
| `api_vendors` | API 供应商（名称、接口地址、加密 API 密钥）；一个供应商一把 key |
| `api_providers` | 属于供应商的模型（通过 `vendor_id` 关联）；存储 model_id、类型、计费、单价 |
| `skills` | 可复用的提示词模板 |
| `rules` | 全局配置规则 (default_params/filter/workflow) |
| `billing_records` | 每次 API 调用的费用追踪 (通过 session_id 关联会话) |
| `reference_images` | 参考图片元数据，包含强度/裁剪配置 |
| `sessions` | 聊天式 UI 的会话 |
| `messages` | 会话内的消息 (user/assistant/system) |
| `app_settings` | 应用设置 (默认提供商，图片尺寸，max_concurrent，search_retry_count，download_directory) |
| `plan_templates` | 规划模板，含变量用于模板化规划，通过 `builtin_version` 自动版本更新 |

## API 快速参考

### 会话 (主 UI)
- `GET/POST /api/sessions` - 列出/创建会话
- `GET/PUT/DELETE /api/sessions/{id}` - 会话 CRUD
- `GET /api/sessions/{id}/messages` - 获取会话消息
- `POST /api/sessions/{id}/generate` - 生成图片。支持 `reference_images` base64, `reference_labels`, `context_messages`（含 `image_urls` 多模态上下文）, `plan_strategy`。新增: `agent_mode`, `agent_tools`, `agent_plan_strategy` 用于 Agent 驱动流程。
- `POST /api/sessions/{id}/execute-plan` - 执行计划（含明确的步骤和策略）
- `POST /api/sessions/{id}/messages` - 添加消息到会话
- `POST /api/sessions/{id}/cancel` - 取消正在执行的 agent 任务
- `POST /api/sessions/{id}/agent/checkpoint` - Agent 检查点确认/拒绝 (body: `{action: "approve"|"reject", feedback?: string, retry_level?: string}`)
- `GET /api/sessions/events` - SSE 事件流，实时任务状态 (snapshot + task_update + ping + tool_call + tool_result)

### 设置
- `GET/PUT /api/settings/default-models` - 默认提供商设置 (含 `max_concurrent`)
- `GET /api/settings/{key}` - 获取任意设置值
- `PUT /api/settings/{key}` - 设置任意设置值 (JSON body: `{"value": ...}`)
- 支持的键: `search_retry_count`, `download_directory`

### 提示词 (LLM)
- `POST /api/prompt/optimize` - 通过 LLM 优化提示词 (支持 5 个方向 + 自定义 + 多方向组合), 支持 `session_id` 计费
- `POST /api/prompt/optimize/stream` - 流式优化 (SSE，逐 token)
- `POST /api/prompt/stream` - 流式 LLM 对话 (SSE，逐 token), 支持 `stream_type` (`"assistant"` 默认), 支持 `session_id` 计费, 可选 `agent_tools` 启用网络/图片搜索
- `POST /api/prompt/plan` - 流式规划生成 (SSE), 通过 `stream_type="plan"` 区分计费

### 供应商/模型
- `GET/POST /api/vendors` - 列出/创建供应商
- `GET/PUT/DELETE /api/vendors/{id}` - 供应商 CRUD
- `POST /api/vendors/{id}/test` - 测试连接
- `GET/POST /api/vendors/{id}/models` - 列出/添加供应商下的模型
- `GET/POST /api/providers` - 列出/创建提供商（类型：`llm`、`image_gen`、`web_search`）；支持 `vendor_id` 参数
- `POST /api/providers/{id}/test` - 测试连接

### 账单
- `GET /api/billing/summary` - 今日/本月/总计费用
- `GET /api/billing/export` - CSV 导出
- `GET /api/billing/details` - 分页账单记录 (按 session_id, provider_id, 日期范围过滤)
- `GET /api/billing/breakdown` - 按提供商和操作类型的费用明细 (image_gen/optimize/assistant/plan/vision/agent/tool)

### 仪表盘
- `GET /api/dashboard/stats` - total_sessions, total_images, total_generations, monthly_cost

### 下载
- `POST /api/download/image` - 下载图片到指定目录。Body: `{url, filename}`。需先在设置页面配置 `download_directory`。

### 技能 & 规则 & 参考图
- `/api/skills`, `/api/rules`, `/api/references` 完整 CRUD

### 规划模板
- `/api/plan-templates` 完整 CRUD
- `POST /api/plan-templates/{id}/apply` - 变量替换应用模板

## Agent 系统

Agent 模式使用**代码驱动的策略路由** — 后端决定任务类型和执行策略，而非 LLM 或前端。

### LangGraph 架构 (Phase 2)

Agent 系统基于 LangGraph StateGraph，两种共存的图配置：

**侧边栏助手 (2 节点循环)** — `build_agent_graph()`:
```
agent_node (LLM + 工具) ⇄ tools_node (执行) → END
```

**Agent 模式 (9 节点)** — `build_agent_mode_graph()`:
```
intent → skill_matcher → skill → context_enrichment → planner → prompt_builder → executor → (critic → decision → retry) → END
```

### 核心设计
- **意图解析**: `classify_intent_with_llm()` 通过纯 LLM 分类将 prompt 分类为 **4 种任务类型**，失败时回退到 `single`
- **搜索增强**: `has_search_intent()` 检测搜索语义，触发 `_enhance_with_search()` 预搜索
- **固定策略映射**: `STRATEGY_MAP` 将任务类型 → 策略确定性映射 (代码决定，非 LLM)
- **LLM 驱动规划**: `planner_node` 在 `task_type` 约束内自主决定步骤数、依赖、检查点位置。使用 `build_planner_system_prompt()` 提供策略感知系统提示
- **上下文优化**: `context_enrichment_node` + `PlanningContextManager` 处理 token 预算 (6000 硬上限)、图片去重、图片描述缓存
- **技能作为规划偏置**: 技能提供 `strategy_hint/planning_bias/constraints/prompt_bias` — 注入 planner_node 和 prompt_builder_node
- **Critic 反馈注入**: 重试时 `decision_node` 计算 `retry_step_index`；`prompt_builder_node` 和 `planner_node` 读取 `critic_results` 注入反馈
- **LLM 调用日志**: `llm_call_logger.py` 为所有 5 个 LLM 节点 (intent/planner/prompt_builder/critic/context) 提供统一的 token 提取、延迟测量和计费
- **Agent 元数据**: Agent 消息在 DB 中存储完整决策轨迹: `plan`、`critic`、`decision`、`node_trace`、`image_descriptions`

### 任务类型与策略映射

| 任务类型 | 策略 | 执行器 | 示例 |
|----------|------|--------|------|
| `single` | `single` | `SingleExecutor` → `generate_images_core()` | "画一只猫" |
| `multi_independent` | `parallel` | `ParallelExecutor` → `asyncio.gather` | "画3张不同风格的猫" |
| `iterative` | `iterative` | `IterativeExecutor` → 顺序执行 | "先出草图再精修" |
| `radiate` | `radiate` | `RadiateExecutor` → 锚点网格 → PIL 裁剪 → 逐项 `chat_edit()` | "做一套6个表情包" |

### 工具 (仅侧边栏助手)
| 工具 | 用途 |
|------|------|
| `web_search` | Serper 文本搜索 (设计趋势、参考资料) |
| `image_search` | Serper 图片搜索 (风格情绪板) |
| `generate_image` | 封装 ImageClient — prompt, count(仅1), 可选 reference_urls, reference_images, reference_labels |
| `plan` | 封装 plan_template_service — list/apply/create 操作 |

### 双入口
1. **侧边栏助手**: 搜索开关 → LLM 对话 + 工具调用 (使用 agent loop)
2. **Agent 模式 (会话输入栏)**: 「智能」开关 → 意图路由 → 直接执行 (无 agent loop)

### 辐射策略 (Radiate)
- LLM 通过 planner_node 生成 items/style/overall_theme
- `RadiateExecutor` 生成锚点网格 → PIL 裁剪 → 逐项 `chat_edit()` 扩展
- 网格裁切失败回退到直接逐项生成
- `grid_config` 为计划内部参数 (LLM 不可见)

### SSE 事件 (LamEvent v1 广播)
Agent 事件通过 `TaskManager.publish()` 广播到 `GET /api/sessions/events`

| LamEvent.event_type | payload.type | 说明 |
|---|---|---|
| `task_started` | `task_started` | 任务开始，含 `task_type` 和 `strategy` |
| `task_progress` | `task_progress` | 进度更新 |
| `task_progress` | `agent_token` | LLM 输出 token (侧边栏助手) |
| `task_progress` | `agent_tool_call` | 工具调用发起 (侧边栏助手) |
| `task_progress` | `agent_tool_result` | 工具执行结果 (侧边栏助手) |
| `task_progress` | `agent_tool_warning` | 工具重试耗尽 |
| `checkpoint_required` | `agent_checkpoint` | 暂停等待用户审批 |
| `task_completed` | `agent_done` | 完成 |
| `task_failed` | `agent_error` | 错误 |
| `task_completed` | `agent_cancelled` | 取消 |

### 提供商
- `web_search` 提供商类型存储 Serper API 密钥 (AES-256-GCM 加密)
- AgentLoop 首次遇到活跃 `web_search` 提供商时自动检测

## 开发命令

```bash
# 后端
cd backend && pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 前端
cd frontend && npm install && npm run dev

# 生产环境
cd frontend && npm run build
cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 重要模式

### API 密钥加密
- 密钥在存储前使用 AES-256-GCM 加密
- 加密密钥从文件种子派生 (`<DATA_DIR>/.encryption_seed`)，首次运行自动创建
- API 响应只显示最后 4 个字符 (`****5678`)

### 基于会话的生成流程
1. 用户创建/选择一个会话
2. 用户输入提示词，可选附件 (图片/文档)
3. 上传的图片编码为 base64，作为 `reference_images` 发送
4. 最近的聊天历史作为 `context_messages` 发送，用于上下文感知生成
5. `POST /api/sessions/{id}/generate` 触发生成
6. 后端添加用户消息，应用技能/规则
7. 图生图（当存在 `reference_images` 时）使用三级降级：
   - **第一级（优先）**: `chat_edit()` → `POST /v1/chat/completions` 多模态消息（兼容大多数代理服务）
   - **第二级**: `edit()` → `POST /v1/images/edits` （原生 OpenAI，部分代理可能不支持）
   - **第三级**: Vision LLM 视觉描述 → `POST /v1/images/generations` （纯文字兜底）
8. 结果存储为助手消息，包含图片 URL
9. 自动创建账单记录，包含 `session_id`

### LLM 账单
- 提示词优化、规划生成、助手对话按 token 计费
- 通过 `/api/prompt/stream` 的流式 LLM 调用使用 SSE (Server-Sent Events)
- 费用 = unit_price × (tokens_in + tokens_out) / 1000

### 前端状态
- Pinia stores: `provider`, `billing`, `session`
- `src/api/` 中的 API 客户端使用 axios，base URL 为 `/api`
- 开发时 Vite 代理将 `/api` 转发到后端

## UI 设计约束

- **无 emoji** - 仅使用 Lucide 线性 SVG 图标
- **黑白灰配色** - #FAFAFA 背景, #FFFFFF 卡片, #E5E5E5 边框, #000000 强调色
- **无卡片堆叠** - 数据用表格展示，表单用侧边抽屉
- **账单在顶栏** - 单行显示"本月 ¥xxx"，点击展开抽屉
- **对话式 UI** - 左侧会话列表，中间聊天区域，右侧助手侧边栏
- **灯箱** - 图片点击打开覆盖层预览（非新标签页）
- **流式动画** - 优化/规划流式输出时的脉冲边框动画
- **规划卡片** - 规划消息显示为可折叠卡片，包含步骤描述

## 常见任务

### 添加新的 API 端点
1. 在 `backend/app/routers/<module>.py` 添加路由
2. 在 `backend/app/services/<service>.py` 添加服务方法
3. 在 `backend/app/schemas/<module>.py` 添加 schema
4. 在 `frontend/src/api/<module>.ts` 添加 API 客户端方法
5. 如需要，在 `frontend/src/stores/<store>.ts` 更新 store

### 添加新页面
1. 创建 `frontend/src/views/NewPage.vue`
2. 在 `frontend/src/router/index.ts` 添加路由
3. 在 `frontend/src/App.vue` 添加导航项

## 已知限制

- 无用户认证（单用户桌面应用）
- 无深色主题
- 参考图片本地存储（非云存储）
- 文件上传在客户端处理（非上传到服务器）
- 参考图片作为 base64 发送到图像生成 API
- `/v1/images/edits` 端点（原生 OpenAI img2img）部分代理可能不支持，系统会降级到 Chat API 多模态和 Vision LLM 视觉描述
