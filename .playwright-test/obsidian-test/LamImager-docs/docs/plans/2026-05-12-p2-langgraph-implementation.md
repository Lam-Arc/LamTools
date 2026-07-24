# P2: LangGraph + LLM 自主规划 实施计划

> **For agentic workers:** Use executing-plans or subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** P2A: 用 LangGraph StateGraph 替换 sidebar assistant 的 `run_agent_loop()`，行为不变，deprecate 旧 loop。P2B: 扩展为 7-node 完整图（skill/context/planner/prompt_builder/critic/decision/checkpoint）。

**Architecture:** P2A 最小 2-node 图 (`agent_node → tools_node → agent_node` loop) 替换 `routers/prompt.py` 中的 `_stream_with_tools()`。P2B 逐节点扩展。Skill 数据模型在 P2A 先重定义为 planner bias 载体。整个阶段不引入新执行器、不改前端路由、不碰 `handle_agent_generate()` 主 agent 路径。

**Tech Stack:** Python 3.14 / LangGraph 1.1.10 / FastAPI / SQLAlchemy async / Vue3 / SSE / tiktoken

---

## Python 版本要求

**强制 Python 3.14+。** 放弃 Python 3.9（已在 PyInstaller 打包中使用 cf68585）。

- `langgraph>=1.1.10` 要求 Python >= 3.10
- `tiktoken>=0.7.0` 要求 Python >= 3.9
- 全栈开发统一到 3.14

确保 venv 或系统 Python 指向 3.14：
```bash
py -3.14 -m pip install -r backend/requirements.txt
cd backend && py -3.14 -m uvicorn app.main:app --reload --port 8000
```

---

## 四项目前决定

| # | 决定 | 值 |
|---|------|-----|
| 1 | LangGraph 版本 | `>=1.1.10,<1.2.0`（禁止 `1.1.7`，已 yanked） |
| 2 | Sessions.vue 拆分 | 已完成 (P1 收尾)，P2 标记跳过 |
| 3 | P2A 图切换策略 | 并存：`use_langgraph=true` 默认新图，旧 `run_agent_loop` 回退 |
| 4 | Tokenizer | `tiktoken>=0.7.0`，`cl100k_base` 编码，失败时日志报错不阻塞 |

---

## 模块依赖约束

| 规则 | 约束 |
|------|------|
| R1 | `graph.py` 内部节点不能直接 import `generate_service.py`（通过 adapter 间接调用） |
| R2 | `PlanExecutionService` 保持独立，graph 节点通过 adapter 调用它 |
| R3 | SSE 事件格式不变 — `agent_bridge.py` 的 `agent_event_to_lam_event()` 保持现有映射 |
| R4 | `deprecated` 标记的旧函数只保留，不新增调用 |
| R5 | 所有新代码在 `backend/app/core/agent/` 下 |

---

## P2A: 桥接 + 最小图迁移 (Month 2)

### P2A 图结构 (最小化)

```
agent_node (LLM call with tools) → tools_node (execute tools) → [conditional] → agent_node / END
```

3-node 图（含 `__start__`），替换 `run_agent_loop()` 的调度层。LLM 调用和工具执行逻辑复用现有代码。

### Task 2.0a: Skill 模型重定义为 Planner Bias 载体

**Files:**
- `backend/app/models/skill.py` (modify)
- `backend/app/schemas/skill.py` (modify)
- `backend/app/schemas/planning.py` (modify, SkillInterface 同步)
- `backend/app/services/skill_engine.py` (modify)

**Steps:**
- [ ] **2.0a.1**: `Skill` 模型新增 4 列：
  ```python
  strategy_hint: Mapped[str] = mapped_column(String(20), default="")
  planning_bias: Mapped[dict] = mapped_column(JSON, default=dict)
  constraints: Mapped[dict] = mapped_column(JSON, default=dict)
  prompt_bias: Mapped[dict] = mapped_column(JSON, default=dict)
  ```
  保留已有 `strategy` 和 `steps` 列不变（P1 遗留，向后兼容）。

- [ ] **2.0a.2**: `SkillCreate/Update/Response/Import` 四 schema 新增对应字段 (带默认值空)
- [ ] **2.0a.3**: `SkillInterface` (planning.py) 新增 `strategy_hint/planning_bias/constraints/prompt_bias`
- [ ] **2.0a.4**: `skill_engine.py` 新增 `skill_to_planner_hints(skill) -> dict`:
  ```python
  def skill_to_planner_hints(skill: Skill) -> dict:
      return {
          "strategy_hint": skill.strategy_hint or None,
          "planning_bias": skill.planning_bias or {},
          "constraints": skill.constraints or {},
          "prompt_bias": skill.prompt_bias or {},
      }
  ```
- [ ] **2.0a.5**: `apply_skill()` 重定义返回值语义：
  - 如果 skill 有 `steps` (P1 遗留): 返回 `ExecutionPlan` (旧行为)
  - 如果 skill 有 `strategy_hint/planning_bias/constraints`: 返回 `planner_hints` dict (新行为)
  - 两者都没有: 返回 `str` (prompt 拼接, 最旧行为)

**Verification:**
- [ ] 创建 skill 时填写 `strategy_hint="iterative"`, `constraints={"quality":"photorealistic"}` → 入库确认
- [ ] `skill_to_planner_hints()` 返回结构化 dict
- [ ] `apply_skill()` 三种返回类型 (ExecutionPlan / dict / str) 均正常
- [ ] 前端 Skill 类型同步新增 `strategy_hint`, `planning_bias`, `constraints`, `prompt_bias`

**Commit:** `refactor(skill): redefine skills as planner bias carriers with new columns`

---

### Task 2.0b: Sessions.vue 组件拆分 → 已完成

**状态：通过验收。** 14 个新组件，4082 → 1731 行，构建通过。

**本 Task 仅需确认:**
- [ ] 搜索 `Sessions.vue` 确认 `<div class="checkpoint-overlay">` 已移除（为 Task 2.5 预留）

---

### Task 2.0c: 依赖安装 + 生态文档更新

**Files:**
- `backend/requirements.txt` (modify)
- `docs/plans/2026-05-09-lamtools-ecosystem.md` (modify, Phase 2 章节记录 4 项决定)

**Steps:**
- [ ] `requirements.txt` 追加:
  ```
  langgraph>=1.1.10,<1.2.0
  tiktoken>=0.7.0
  ```
- [ ] `py -3.14 -m pip install langgraph>=1.1.10,<1.2.0 tiktoken>=0.7.0` 安装到 3.14 环境
- [ ] `backend/requirements.txt` 全部依赖用 3.14 重装验证:
  ```bash
  py -3.14 -m pip install -r backend/requirements.txt
  ```
- [ ] 数据库迁移: `init_db()` 中新增 `use_langgraph` 到 `app_settings` 表（默认 `{"value": true}`）
- [ ] 生态文档 Phase 2 章节追加 4 项决定记录
- [ ] 更新 `build.py` 和 `AGENTS.md` 中 Python 版本要求：`3.9` → `3.14`

**Verification:**
- [ ] `py -3.14 -c "import langgraph; print(langgraph.__version__)"` 成功
- [ ] `py -3.14 -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"` 成功
- [ ] `py -3.14 -c "from app.main import app"` 在 backend 目录下通过

**Commit:** `chore(p2a): add langgraph + tiktoken deps, use_langgraph setting, bump python to 3.14`

---

### Task 2.1: Agent Loop → LangGraph 最小图迁移

**核心理解：** `run_agent_loop()` 仅在 `routers/prompt.py:_stream_with_tools()` 中被调用（sidebar assistant SSE 端点）。主 agent 生成路径 `handle_agent_generate()` 不走此函数，P2A 不动它。

**Files:**
- `backend/app/core/agent/state.py` (new, GraphState TypedDict)
- `backend/app/core/agent/graph.py` (new, 图组装 + conditional edge)
- `backend/app/core/agent/graph_llm.py` (new, agent_node — LLM streaming)
- `backend/app/core/agent/graph_tools.py` (new, tools_node — 工具执行)
- `backend/app/routers/prompt.py` (modify, `_stream_with_tools` 切到 graph)
- `backend/app/services/agent_service.py` (modify, `run_agent_loop` 加 deprecated 注释)

**Steps:**

- [ ] **2.1a: GraphState 定义** (`state.py`)
  ```python
  from typing import TypedDict
  from langgraph.graph.message import add_messages
  
  class AgentState(TypedDict):
      session_id: str
      messages: Annotated[list, add_messages]
      provider_id: str
      tools: list[str]
      cancel_event: object | None
      total_tokens_in: int
      total_tokens_out: int
      total_cost: float
      rounds: int
      tools_used: list[str]
      # P2B 预留字段
      intent: dict | None
      skill_hints: dict | None
      planning_context: dict | None
      execution_plan: dict | None
      artifacts: list[dict]
  ```

- [ ] **2.1b: agent_node** (`graph_llm.py`)
  - 输入: `state.messages`, `state.provider_id`, `state.tools`
  - 流程:
    1. 解析 provider → 解密 API key → 构造 `LLMClient`
    2. 调用 LLM stream (带 tools 定义)
    3. **每 token 通过 `TaskManager.publish()` 广播 `agent_token` LamEvent**
    4. 收集完整 response (content + tool_calls + usage)
    5. 返回 `{"messages": [AIMessage(content=..., tool_calls=...)], "total_tokens_in": ..., "total_tokens_out": ...}`
  - 取消检查: `state.cancel_event.is_set()` → 终止流式
  - 复用 `agent_service.py` 的 `ALL_TOOLS` / `TRUNCATE_PROMPT` 常量，不重复定义

- [ ] **2.1c: tools_node** (`graph_tools.py`)
  - 输入: `state.messages` (最后一条 AIMessage 的 `tool_calls`)
  - 流程:
    1. 遍历 tool_calls
    2. 每 tool 调用 **先广播 `agent_tool_call` LamEvent**
    3. 执行工具 (复用 `agent_service.py` tool execution: registry lookup → execute → truncate → billing)
    4. 广播 `agent_tool_result` LamEvent
    5. 返回 `{"messages": [ToolMessage(content=..., tool_call_id=...), ...]}`
  - 工具定义复用现有 `ALL_TOOLS` + Tool registry (不改现有 tool 实现)

- [ ] **2.1d: 图组装 + conditional edge** (`graph.py`)
  ```python
  from langgraph.graph import StateGraph, END
  
  def build_agent_graph():
      builder = StateGraph(AgentState)
      builder.add_node("agent", agent_node)
      builder.add_node("tools", tools_node)
      builder.add_edge("__start__", "agent")
      builder.add_conditional_edges(
          "agent",
          should_continue,
          {"tools": "tools", END: END},
      )
      builder.add_edge("tools", "agent")
      return builder.compile()
  ```
  - `should_continue`: return `"tools"` if last message has `tool_calls`, else `END`
  - `recursion_limit = max_rounds * 2` (每轮 agent+tools 两个节点)
  - `checkpointer = None` (P2A 不设 checkpoint, 由 P2B Task 2.5 接入)

- [ ] **2.1e: prompt.py 切到 graph** (`routers/prompt.py`)
  - 旧 `_stream_with_tools` → 重命名为 `_stream_with_tools_legacy`
  - 新增 `_stream_with_graph(db, data)` 函数
  - `api_stream_chat` / `api_plan_stream` 在 `data.tools` 存在时调用新函数 (默认 `use_langgraph=true`)
  - 旧函数保留作为回退入口

- [ ] **2.1f: agent_service.py 标记 deprecated**
  - `run_agent_loop()` 函数上方加: `# @deprecated: 使用 app.core.agent.graph.build_agent_graph() 替代`
  - 函数体不变

**Verification:**
- [ ] 助手对话框输入 "hello" → 发送 → 流式回复正常
- [ ] 助手对话框 + 搜索开启 → web_search tool_call 卡片出现 → 搜索结果展示
- [ ] 助手对话框 + 搜索开启 → "生成一只猫" → image_search + generate_image → 图片展示
- [ ] 连续 3 轮对话 → agent loop 不超时不卡死
- [ ] 关闭 `use_langgraph` → 切回旧 loop → 行为一致
- [ ] SSE 事件格式与拆分前完全一致 (前端 `AgentStreamCard` 无改动)

**Commit:** `feat(p2a): migrate agent loop to LangGraph StateGraph with feature flag`

---

### P2A 里程碑: LangGraph 迁移完成

- 2-node graph 可用
- sidebar assistant 行为不变
- 旧 agent loop 仍可回退

---

## P2B: 完整 7-Node 图 (Month 3-4)

> 条件：P2A Task 2.0a-2.1 全部完成且通过回归。

### P2B 图结构 (完整 7 节点)

```
                     ┌─────────────┐
                     │ intent_node │  代码驱动，输出 task_type
                     └──────┬──────┘
                            │
                     ┌──────▼──────┐
                     │ skill_node  │  skill_engine.apply_skill()
                     │ → planner   │  → planning_bias + constraints
                     │   hints     │
                     └──────┬──────┘
                            │
                     ┌──────▼──────┐
                     │ context_enrichment_node │
                     │ PlanningContext 标准化   │
                     │ token预算 + 图片缓存     │
                     └──────┬──────┘
                            │
                     ┌──────▼──────┐
                     │ planner_node │  LLM 在 task_type 约束下
                     │ → ExecutionPlan │  生成完整 ExecutionPlan
                     └──────┬──────┘
                            │
                     ┌──────▼──────┐
                     │ prompt_builder_node │
                     │ LLM 逐 step 多模态  │
                     │ 优化 prompt        │
                     └──────┬──────┘
                            │
                     ┌──────▼──────┐
                     │ executor_node │  PlanExecutionService.execute()
                     └──────┬──────┘
                            │
                 ┌──────────┴──────────┐
                 │                     │
         ┌───────▼───────┐    ┌───────▼───────┐
         │ critic_node   │    │ checkpoint    │
         │ vision LLM    │    │ graph.        │
         │ score+tags    │    │ interrupt()   │
         │ +issues       │    └───────┬───────┘
         └───────┬───────┘            │
                 │             approve → 继续
                 │            retry_step → prompt_builder
          ┌──────▼──────┐   replan → planner_node
          │decision_node│
          │retry_score  │
          │→ 决策路由   │
          └──────┬──────┘
                 │
     score ≥ 7.0 → 输出结果
     score < 7.0 → 路由: warn / retry_prompt / retry_step
```

### Task 2.2: skill_node + context_enrichment_node

**Files:**
- `backend/app/core/agent/nodes/skill_node.py` (new)
- `backend/app/core/agent/nodes/context_node.py` (new)
- `backend/app/core/agent/graph.py` (modify, 加新节点)
- `backend/app/services/skill_engine.py` (已有, P2A 已重定义)

**Steps:**
- [ ] skill_node: 读取 `state.skill_ids` → 调用 `skill_engine.apply_skill()` → 产出 `planner_hints` → 写入 `state.skill_hints`
- [ ] context_enrichment_node (最小版): 图片去重 (同 URL 在多来源中只保留一份) + token 预算壳 (优先级分层接口位)
- [ ] 图更新: `intent → skill → context → planner`

**Verification:**
- [ ] skill bias 正确传递到 planner (如 `strategy_hint="iterative"` → plan steps ≥ 3)
- [ ] 无 skill 选中时正常生成 (空 hints 不报错)

**Commit:** `feat(p2b): add skill_node and context_enrichment_node`

---

### Task 2.3: planner_node + prompt_builder_node

**Files:**
- `backend/app/core/agent/nodes/planner_node.py` (new)
- `backend/app/core/agent/nodes/prompt_builder_node.py` (new)
- `backend/app/core/agent/graph.py` (modify)
- `backend/app/services/prompt_optimizer.py` (modify, 加 `context_images` 参数)

**Steps:**
- [ ] planner_node: LLM 在 `task_type` 约束下生成 `ExecutionPlan` (自主决定 steps/dependencies/checkpoint 位置)
- [ ] prompt_builder_node: LLM 逐 step 多模态优化 prompt (context_images → vision LLM)
- [ ] `prompt_optimizer.py.optimize_prompt()` 新增 `context_images` 参数

**Verification:**
- [ ] "做一套6个表情包" → planner 在 radiate 约束下生成 6 items + anchor
- [ ] 有参考图时 prompt builder 产出体现参考图风格

**Commit:** `feat(p2b): add LLM-driven planner and multimodal prompt builder`

---

### Task 2.4: critic_node + decision_node

**Files:**
- `backend/app/core/agent/nodes/critic_node.py` (new)
- `backend/app/core/agent/nodes/decision_node.py` (new)
- `backend/app/core/agent/critic_interface.py` (new, P2↔P3 接口)
- `backend/app/core/agent/graph.py` (modify)

**Steps:**
- [ ] critic_node: vision LLM 评分 (0-10) + 标签 + 缺陷列表 → `CriticOutput`
- [ ] decision_node: 纯数学决策 (score ≥ 7 → pass; 5-7 → warn; 3-5 → retry_prompt; < 3 → retry_step)
- [ ] `critic_mode` 配置: `off/radiate_anchor_only/all` (默认 `radiate_anchor_only`)

**Verification:**
- [ ] Critic 输出不含 retry 建议
- [ ] decision_node 独立决策，阈值验证正确

**Commit:** `feat(p2b): add critic_node and decision_node, decoupled from scoring`

---

### Task 2.5: Checkpoint 通用化

**Files:**
- `backend/app/core/agent/graph.py` (modify, `interrupt()` 集成)
- `backend/app/routers/session.py` (modify, 加 `retry_level`)
- `frontend/src/components/session/CheckpointOverlay.vue` (modify)

**Steps:**
- [ ] `PlanStep.checkpoint=true` 的任意 step → executor 执行前 `graph.interrupt()`
- [ ] `POST /checkpoint` 加 `retry_level: approve | retry_step | replan`
- [ ] 前端 CheckpointOverlay 改为 3 按钮 + 可选 feedback 输入

**Verification:**
- [ ] 任意带 checkpoint 的 step → 执行后暂停
- [ ] approve → 继续 / retry_step → 重做当前步 / replan → 重规划

**Commit:** `feat(p2b): generalize checkpoint to all PlanStep types with 3-level resume`

---

### Task 2.6: PlanningContext 深度升级

**Files:**
- `backend/app/schemas/planning.py` (modify)
- `backend/app/services/planning_context.py` (new)
- `backend/app/services/generate_service.py` (modify)

**Steps:**
- [ ] Token 预算: `budget_tokens()` 方法，6 级优先级分层，硬顶 6000
- [ ] 图片描述缓存: vision LLM 产出文本描述，缓存到 message metadata，同图不重传 base64
- [ ] 相关性过滤: prompt 关键字 vs 上下文标签 overlap，低相关降权不剔除

**Verification:**
- [ ] 超 6000 token → 自动截断，钉选图保留
- [ ] 同图 3 次引用 → 1 次 vision 调用

**Commit:** `feat(p2b): upgrade PlanningContext with token budget, image caching, and relevance filter`

---

### P2B 里程碑: 7-node 完整图可用

---

## 执行顺序

```
P2A (Month 2):
  Task 2.0a (skill redef) ─┐
                           ├─ 并行 ─→ Task 2.1 (minimal graph)
  Task 2.0c (deps + doc)  ─┘           │
                                        ↓
                           2-node graph 可用, SSE 行为不变
                           旧 run_agent_loop 可回退

  ←── P2A 里程碑 ──→

P2B (Month 3-4, 条件: P2A 全部通过):
  Task 2.2 (skill_node + context_enrichment)
      ↓
  Task 2.6 并行开始 (PlanningContext 深度, 不阻塞 2.3)
      ↓
  Task 2.3 (planner + prompt_builder) — Task 2.6 需在此之前完成
      ↓
  Task 2.4 (critic + decision)
      ↓
  Task 2.5 (checkpoint 通用化)

  ←── P2B 里程碑 ──→
```

Task 2.0b (Sessions.vue 拆分) **已完成，跳过。**

---

## P2 → P3 接口交付物

| 接口 | 位置 | P3 消费者 |
|------|------|----------|
| `CriticOutput(score, tags, issues)` | `critic_interface.py` | `scorer.py` → 双维评分 |
| `PreferenceScore` 桩 | `scorer.py` (预留) | Task 3.1 |
| `optimize_prompt()` 加 `context_images` | `prompt_optimizer.py` | Task 3.2A |
| `PlanStep.checkpoint` 通用化 | 图节点 + router | P2 自消耗 |
| `PlanningContext.budget_tokens()` | `planning_context.py` | 长期使用 |
