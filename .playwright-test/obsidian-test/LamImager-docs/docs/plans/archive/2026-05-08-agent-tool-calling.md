# Agent 工具调用系统

> 设计日期：2026-05-08 | 状态：已审批

## 目标

为 LamImager 引入 Function Calling 基础设施，使 LLM 能够自主调用外部工具（优先实现网络搜索），并为后续多步规划（LangGraph）预留迁移空间。

### 核心原则

1. **工具注册表 + AgentLoop**：即插即用工具框架，不做过度设计
2. **双入口共享工具库**：侧边栏聊天 + 会话 Agent 模式共用同一套工具
3. **LangGraph 预留**：工具接口与 LangChain BaseTool 签名对齐，AgentLoop 挂起/恢复映射到 interrupt/resume
4. **混合执行**：默认自治运行，关键步骤可配置检查点等待用户确认

---

## 设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 工具框架 | 自建 Tool 抽象 + AgentLoop | LangGraph 对 MVP 过重，但 Tool 接口预留对齐 |
| 搜索 API | Serper.dev | 免费额度高(2500次/月)，支持图片搜索，API 简单 |
| 交互入口 | 双入口（侧边栏 + Agent模式） | 侧边栏聊方案，Agent 模式执行方案 |
| 执行模式 | 混合：默认自治 + 可配检查点 | 降低初版复杂度，保留审批能力 |
| Stage 1 范围 | 不实现反馈闭环 | 易浪费 token，延迟到后期 |
| 优先级 | 工具调用(C) → 多步规划(B) | 先做基础设施，再做复杂编排 |

---

## 架构

### 目录结构（新增/修改）

```
backend/app/
├── tools/                    ← 新增：即插即用工具包
│   ├── __init__.py           → ToolRegistry 单例 + register_tool 装饰器
│   ├── base.py               → Tool 抽象基类 + ToolResult 数据类
│   ├── web_search.py         → Serper 文本搜索工具
│   └── image_search.py       → Serper 图片搜索工具
├── services/
│   ├── agent_service.py      ← 新增：工具调用编排 + SSE 流式
│   ├── prompt_optimizer.py   ← 修改：侧边栏流式走 AgentLoop
│   └── generate_service.py   ← 修改：agent_mode 分支逻辑
├── routers/
│   ├── prompt.py             ← 修改：stream 端点支持 tools 参数
│   └── session.py            ← 修改：generate 端点支持 agent_mode
├── models/
│   └── message.py            ← 修改：message_type 增加 "agent"
└── schemas/
    ├── prompt.py             ← 修改：增加 tools 字段
    └── session.py            ← 修改：增加 agent_mode / agent_tools
```

### 工具抽象接口

```python
class Tool:
    name: str              # "web_search"
    description: str       # LLM function description
    parameters: dict       # JSON Schema for function parameters

    async def execute(self, **kwargs) -> ToolResult:
        ...

class ToolResult:
    content: str            # 文本结果（注入回 LLM 对话）
    meta: dict | None       # 额外元数据（搜索来源、图片URL等）
```

### AgentLoop 编排器

核心是 `async generator`，逐事件 SSE 推流：

```
run_agent_loop(messages, tools, checkpoints) → AsyncGenerator[AgentEvent]
  ├── LLM 请求 → tool_calls?
  ├── checkpoint? → 挂起等待用户确认
  ├── 执行工具 → 注入结果 → 循环
  └── finish_reason=stop → 返回
```

### SSE 事件协议

| 事件类型 | 用途 | 数据 |
|----------|------|------|
| `token` | 文本流（兼容现有） | `{type:"token", content:"..."}` |
| `tool_call` | 工具调用开始 | `{type:"tool_call", name:"web_search", args:{query:"..."}}` |
| `tool_result` | 工具执行结果 | `{type:"tool_result", name:"web_search", content:"...", meta:{...}}` |
| `checkpoint` | 挂起等待审批 | `{type:"checkpoint", name:"generate_image", args:{...}}` |
| `done` | 完成 | `{type:"done", usage:{tokens_in, tokens_out}}` |

---

## 双入口集成

### 入口一：侧边栏小助手

```
POST /api/prompt/stream
  { messages, stream_type:"assistant", tools: ["web_search"] }
  → agent_service.run_agent_loop(tools)
  → SSE 流
```

**UI 变化**：
- 输入框旁新增搜索开关（默认关闭）
- 工具调用过程展示为可折叠卡片
- 其他行为不变

### 入口二：Agent 模式生图

```
POST /api/sessions/{id}/generate
  { prompt, agent_mode: true, agent_tools: ["web_search", "image_search"] }
  → generate_service → agent_service.run_agent_loop
  → 结果存为 message(type="agent") + metadata.steps[]
```

**UI 变化**：
- 输入栏左侧加 Agent 模式切换按钮
- Agent 模式下隐藏大部分控件，仅保留规划策略+搜索开关
- 消息区展示动态增长的 Agent 执行卡片（含步骤列表）

---

## LangGraph 预留与迁移路径

### 预留点映射

| 当前实现 | LangGraph 对应物 |
|----------|-----------------|
| `Tool` 抽象接口 | `langchain_core.tools.BaseTool`（接口签名一致） |
| `ToolRegistry` | `ToolNode(tools)` |
| AgentLoop 检查点 | `graph.interrupt()` + `Command(resume=...)` |
| `AsyncGenerator[AgentEvent]` | `graph.astream_events()`（事件模型同构） |
| `message.type="agent"` | LangGraph `State` 序列化 |

### 迁移步骤（预计 0.5-1 天）

1. `pip install langgraph langchain-core`
2. `Tool` 子类改为继承 `BaseTool`（接口签名一致）
3. 用 `ToolNode(tools)` 替换 AgentLoop 中的手动 `tool.execute()`
4. `StateGraph` 定义 planner → tools → router 的图结构
5. `checkpoint` 列表转为图中的 `interrupt_before` 配置
6. `run_agent_loop` 改为调用 `graph.astream_events()`
7. **Router 层、前端 SSE 处理、计费系统、消息存储 — 全都不需要改动**

### 迁移触发条件

- 工具数量 > 5（手动循环路由逻辑变复杂）
- 需要并行工具调用（LangGraph `Send()` API 原生支持）
- 检查点复杂度高（多层嵌套审批）
- 需要持久化状态（用户关闭页面再恢复 Agent 进度）

---

## 工具清单

### Phase 1 实现

| 工具 | API | 用途 | 输入 | 输出 |
|------|-----|------|------|------|
| `web_search` | Serper `/search` | 文本搜索 | query, max_results=5 | 标题+链接+摘要 |
| `image_search` | Serper `/images` | 图片搜索 | query, max_results=5 | 缩略图URL+原图URL+来源 |

### Phase 2 预留

| 工具 | 用途 |
|------|------|
| `analyze_image` | Vision LLM 评估图像质量 |
| `upload_cdn` | 外部存储上传 |

---

## 计费

### 新增计费类型

`detail.type: "tool"` — 工具调用消耗的 API 成本

```python
await record_billing(
    session_id=session_id,
    provider_id=search_provider_id,  # Serper 的 ApiProvider
    billing_type="per_call",
    call_count=1,
    detail={"type": "tool", "tool_name": "web_search"}
)
```

### 计费类型汇总

| type | 标签 | 来源 |
|------|------|------|
| `image_gen` | 图像生成 | 现有 |
| `optimize` | 提示词优化 | 现有 |
| `assistant` | 小助手对话 | 现有 |
| `plan` | 规划生成 | 现有 |
| `vision` | 视觉分析 | 现有 |
| `tool` | 工具调用 | **新增** |

---

## 配置项

| 配置 | 位置 | 默认值 | 说明 |
|------|------|--------|------|
| Serper API Key | ApiProvider (type=tool) | 无 | 用户自行注册配置 |
| `search_max_results` | app_settings | 5 | 单次搜索最大结果数 |
| `agent_max_rounds` | app_settings | 5 | Agent 最大循环轮次（防无限循环） |

---

## 数据模型变更

### Message 模型

```diff
+ message_type: "text" | "image" | "plan" | "optimization" | "skill" | "error" | "agent"

# agent 类型消息的 metadata 结构:
+ {
+   "steps": [
+     { "type": "tool_call", "name": "web_search", "args": {...}, "result": {...} },
+     { "type": "tool_call", "name": "generate_image", ... },
+   ],
+   "final_output": "...",
+   "images": ["http://...", ...]
+ }
```

---

## 实施顺序

```
Step 1: 后端基础设施（不可见，零破坏）
  ├── tools/base.py            Tool 抽象
  ├── tools/__init__.py        ToolRegistry 单例
  ├── tools/web_search.py      Serper 文本搜索
  └── tools/image_search.py    Serper 图片搜索

Step 2: AgentLoop 编排器（后端核心）
  ├── services/agent_service.py  AgentLoop + AgentEvent 类型
  └── 计费集成（detail.type="tool"）

Step 3: 侧边栏接入（最小可见改动）
  ├── routers/prompt.py         支持 tools 参数
  ├── schemas/prompt.py         新增 tools 字段
  └── 前端：搜索开关 + 工具调用卡片

Step 4: Agent 模式接入（生图流程）
  ├── routers/session.py        generate 支持 agent_mode
  ├── generate_service.py       agent_mode 分支
  ├── models/message.py         增加 "agent" 类型
  ├── schemas/session.py        新增 agent 字段
  └── 前端：模式切换 + Agent 执行卡片

Step 5: 验证 & 调试
  └── 端到端测试：侧边栏搜索 → Agent 模式执行 → 计费记录
```

---

## 文件清单

| 层 | 文件 | 动作 |
|----|------|------|
| 后端 | `backend/app/tools/__init__.py` | 新建 |
| 后端 | `backend/app/tools/base.py` | 新建 |
| 后端 | `backend/app/tools/web_search.py` | 新建 |
| 后端 | `backend/app/tools/image_search.py` | 新建 |
| 后端 | `backend/app/services/agent_service.py` | 新建 |
| 后端 | `backend/app/routers/prompt.py` | 修改 |
| 后端 | `backend/app/routers/session.py` | 修改 |
| 后端 | `backend/app/services/generate_service.py` | 修改 |
| 后端 | `backend/app/services/prompt_optimizer.py` | 修改 |
| 后端 | `backend/app/models/message.py` | 修改 |
| 后端 | `backend/app/schemas/session.py` | 修改 |
| 后端 | `backend/app/schemas/prompt.py` | 修改 |
| 前端 | `frontend/src/api/prompt.ts` | 修改 |
| 前端 | `frontend/src/views/Sessions.vue` | 修改 |
| 前端 | `frontend/src/types/index.ts` | 修改 |

---

## 约束

- Python 3.14+ (standard GIL)
- 不引入 LangGraph（MVP阶段）
- 搜索工具依赖 Serper.dev 外部 API
- 不实现反馈闭环（Vision Critic），延迟到后期
