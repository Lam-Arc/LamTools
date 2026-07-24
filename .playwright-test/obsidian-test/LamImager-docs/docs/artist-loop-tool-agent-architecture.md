# Artist Loop + Tool/Agent 架构设计

日期：2026-05-30

状态：已落地主要运行链路。Phase 1 完成；Phase 2/3 后端路径完成；Phase 4 已具备 inline long task 执行、SSE、DB 记录、查询/状态 API 和前端进度感知。真正后台暂停/恢复执行仍作为后续增强。

## 1. 背景

当前 Artist 已经完成了一个重要迁移：图像生成不再直接散落在 Artist 运行时里，而是通过 `ExecutionEngine` 执行 `ExecutionPlan`。这解决了“先画线稿再上色”这类同轮依赖、lineage parent/root 追踪和 radiate 组图的一部分问题。

但当前核心模型仍然是：

```text
用户消息
  → artist_orchestrate()
  → LLM 输出 ArtistTurn(message + actions)
  → ArtistRuntime.handle_turn() 一次性执行 actions
  → 保存 artist message
```

这个模型适合简单单轮任务，但对复杂创作任务适配性不足：

- 无法在一次用户请求内进行多轮内部观察、计划、执行、复盘。
- `ArtistAction` 同时承担 LLM 输出协议、工具协议和执行协议，边界混乱。
- 复杂任务只能扩展 action type，Runtime 会越来越像一个巨大的分支执行器。
- Agent 图已有 planner / executor / critic / decision 能力，但 Artist 只能在外层二选一，不能在必要时委托后再回到 Artist 语境。
- 长任务、批量任务、搜索参考、风格学习、lineage 操作需要不同执行策略，当前单次 action list 难以表达。

目标是把 Artist 改造成一个有边界的创作 loop：Artist 保留人格和视觉上下文判断，执行能力通过 tool 层封装，复杂非图像任务可委托 Agent，结果再回到 Artist 汇总。

## 2. 设计目标

### 2.1 核心目标

让 Artist 从“LLM 输出 actions 后一次性执行”升级为：

```text
Observe → Think/Plan → Act(tool/agent) → Review → Respond
```

并且这个 loop 是代码可控、可观测、可测试、可中断的。

### 2.2 必须满足

- 简单任务保持快路径，不引入明显额外延迟。
- Artist 不直接调用 `generate_images_core`，图像执行继续委托 `ExecutionEngine`。
- LLM 不直接决定数据库写入、HEAD 切换、计费和最终 SSE 生命周期。
- Agent 是可委托能力，不替代 Artist 人格。
- 所有 tool 调用都要结构化记录，方便测试、debug、lineage 重建。
- loop 必须有最大步数和退出条件，不能无限循环。

### 2.3 暂不在第一阶段解决

- 完整 long task DB 表。
- 前端 LongTaskCard。
- 暂停 / 恢复 / 取消 API。
- 多 Agent 协作。
- 自动 Skill 写回。

这些能力需要依赖 loop/tool 基础，但不应混入第一阶段。

## 3. 总体架构

```text
GenerateRequest
  ↓
handle_artist_generate()
  ↓
artist_orchestrate()
  ↓
ArtistLoopRuntime
  ├─ Observe: 构建 ArtistLoopContext
  ├─ Plan: LLM / 规则生成 ArtistToolCall[]
  ├─ Act: ArtistToolExecutor 执行工具
  ├─ Review: 判断是否继续、结束、澄清、委托
  └─ Respond: 输出 ArtistLoopResult
  ↓
handle_artist_generate() 保存 message + metadata
```

### 3.1 现有模块保留定位

| 模块 | 新定位 |
| --- | --- |
| `generate_service.handle_artist_generate()` | HTTP 入口、消息落库、provider 解析、lineage context 准备 |
| `artist_service.artist_orchestrate()` | Artist 依赖适配层：PER/CON、LLM client、ExecutionEngine callback、event publish |
| `ArtistRuntime` | 第一阶段保留，逐步收敛为 loop facade 或兼容层 |
| `ExecutionEngine` | 图像执行工具的底层执行器 |
| `ImageContextResolver` | Observe 阶段的一部分 |
| `lineage_service` | lineage 事实源，tool 可读取 / 更新 |
| Agent graph | 被 `delegate_agent` tool 调用，不直接成为 Artist 主流程 |

## 4. 分层设计

### 4.1 Artist Persona Layer

职责：

- PER / CON / MEM 注入。
- Artist 语气和创作偏好。
- 根据用户输入做艺术判断。
- 输出简短、自然的用户可见回复。

不负责：

- 直接生图。
- 直接改数据库。
- 直接切换 lineage HEAD。
- 直接调用 Agent graph。

### 4.2 Artist Loop Layer

新增核心概念：`ArtistLoopRuntime`。

职责：

- 持有 loop 上下文。
- 控制最大循环次数。
- 调用 planner 生成 tool calls。
- 调用 tool executor。
- 聚合 artifacts / tokens / cost / phase。
- 形成最终 `ArtistLoopResult`。

第一阶段可以只跑一个 loop iteration，但代码结构必须支持后续多轮。

### 4.3 Artist Tool Layer

新增内部工具协议：`ArtistToolCall` / `ArtistToolResult`。

工具层职责：

- 把 Artist 能力拆成小工具。
- 每个工具只做一件事。
- 工具输入输出结构化。
- 所有工具调用可以被测试和回放。

### 4.4 Execution Layer

图像相关工具统一通过 `ExecutionEngine`：

- 单图生成
- refine
- replace
- style reference
- pack / radiate
- iterative multi-step

### 4.5 Agent Delegation Layer

Agent 只在必要时被 Artist tool 调用：

- 需要搜索资料或参考。
- 需要复杂 planner / critic / decision。
- 需要非图像工具链。
- 需要执行现有 Agent mode 更擅长的任务。

Agent 输出不能直接作为最终 Artist 响应，必须回到 Artist loop 做汇总。

## 5. 数据结构设计

### 5.1 ArtistLoopContext

建议新建：`backend/app/core/artist/loop.py` 或 `backend/app/core/artist/loop_schemas.py`。

```python
class ArtistLoopContext(BaseModel):
    session_id: str
    prompt: str
    artist_turn_id: str
    messages: list[dict] = []
    state: ArtistSessionState
    image_map: dict[str, str] = {}
    reference_images: list[str] = []
    source_image_urls: list[str] = []
    default_size: str = "1024x1024"
    default_count: int = 1
    negative_prompt: str = ""
    image_provider_id: str | None = None
    response_format_mode: str = "auto"
    refine_mode: bool = False
    lineage_context: str = ""
    max_loop_steps: int = 4
```

### 5.2 ArtistToolCall

```python
ArtistToolName = Literal[
    "chat",
    "ask_clarification",
    "execute_image_plan",
    "review_artifacts",
    "inspect_lineage",
    "set_lineage_head",
    "delegate_agent",
]

class ArtistToolCall(BaseModel):
    id: str
    name: ArtistToolName
    args: dict = {}
    reason: str = ""
    source_action_type: str = ""
```

第一阶段只需要实现：

- `chat`
- `ask_clarification`
- `execute_image_plan`

其余先定义契约或留空，不强行接入。

### 5.3 ArtistToolResult

```python
class ArtistToolResult(BaseModel):
    call_id: str
    name: str
    status: Literal["ok", "failed", "skipped"]
    message: str = ""
    artifacts: list[ArtistArtifact] = []
    data: dict = {}
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0
    error: str = ""
```

### 5.4 ArtistLoopResult

```python
class ArtistLoopResult(BaseModel):
    message: str
    blocks: list[str] = []
    artifacts: list[ArtistArtifact] = []
    phase: ArtistRuntimePhase = "idle"
    tool_calls: list[ArtistToolCall] = []
    tool_results: list[ArtistToolResult] = []
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0
    delegated_agent: bool = False
    needs_clarification: bool = False
```

## 6. 从 ArtistAction 到 ArtistToolCall

第一阶段不要求 LLM 直接输出 tool calls，保持当前 `ArtistTurn` JSON 协议，然后增加转换层：

```text
LLM output
  → parse_artist_turn()
  → ArtistTurn(actions)
  → action_to_tool_calls()
  → ArtistToolExecutor.execute()
```

映射规则：

| ArtistAction | Tool |
| --- | --- |
| `chat_only` | `chat` |
| `ask_clarification` | `ask_clarification` |
| `generate_anchor` | `execute_image_plan` |
| `generate_pack` | `execute_image_plan` |
| `refine_target` | `execute_image_plan` |
| `replace_image` | `execute_image_plan` |
| `style_reference` | `execute_image_plan` |
| `self_critique` | 第一阶段并入 `chat` 或 `review_artifacts` |
| `delegate_to_agent` | `delegate_agent`，第二阶段实现 |
| `plan_complex_task` | `execute_image_plan` 或 long task，第三阶段实现 |

这样做可以在不破坏现有 prompt 协议的情况下，先完成架构迁移。

## 7. Artist Loop 流程

### 7.1 第一阶段流程

```text
handle_turn()
  ↓
state_store.get()
  ↓
publish artist_turn_started
  ↓
LLM call
  ↓
parse_artist_turn()
  ↓
action_to_tool_calls()
  ↓
execute tools
  ↓
update state
  ↓
publish artist_turn_done
  ↓
return result
```

行为上与当前版本一致，但 Runtime 内部不再直接按 action type 大分支执行，而是通过 tool executor。

### 7.2 第二阶段流程

```text
loop step 1:
  LLM plan tool calls
  execute image/search/lineage tools

loop step 2:
  feed tool results back to LLM
  LLM decide finish / refine / delegate / ask

loop step 3:
  execute next tool or respond
```

退出条件：

- planner 返回 `finish`。
- 出现 `ask_clarification`。
- 达到 `max_loop_steps`。
- 工具失败且不可恢复。
- 用户取消。

## 8. 工具设计

### 8.1 `chat`

输入：

```python
{"message": str, "blocks": list[str]}
```

行为：

- 发布 `artist_reply_delta`。
- 不产生 artifacts。
- phase 保持 LLM 返回的 phase 或 `idle`。

### 8.2 `ask_clarification`

输入：

```python
{"message": str}
```

行为：

- 发布 `artist_action_started`。
- phase 设为 `waiting_clarification`。
- 不执行后续生成工具。

### 8.3 `execute_image_plan`

输入：

```python
{
    "actions": list[ArtistAction],
    "reference_images": list[str],
    "source_image_urls": list[str],
}
```

行为：

- 调现有：
  - `infer_strategy()`
  - `build_plan_steps()`
  - `_collect_initial_refs()`
  - `ExecutionEngine`
  - `_trace_to_artifacts()` / `_crop_grid_to_artifacts()`
- 发布：
  - `artist_action_started`
  - `artist_image_ready`
- 返回 artifacts、cost、tokens。

### 8.4 `review_artifacts`

第二阶段实现。

输入：

```python
{"artifacts": list[ArtistArtifact], "criteria": dict}
```

行为：

- 可调用轻量 vision review。
- 判断是否需要自动补救。
- 不直接写 MEM，MEM 写入仍由 `artist_orchestrate()` 统一处理。

### 8.5 `inspect_lineage`

第二阶段实现。

行为：

- 读取 `build_lineage_tree()`。
- 返回当前 HEAD、branch、root、候选可编辑图片。

### 8.6 `set_lineage_head`

第二阶段实现。

行为：

- 只能调用 `update_lineage_head()`。
- 必须验证 image_url 属于当前 session。
- 发布 lineage 相关事件时再设计前端消费。

### 8.7 `delegate_agent`

第二阶段实现。

输入：

```python
{
    "sub_prompt": str,
    "reason": str,
    "allowed_tools": list[str],
    "return_contract": str
}
```

行为：

- 调用现有 `_run_agent_mode_graph()` 或抽出 `run_agent_graph()` service。
- Agent 结果转为 tool result。
- Artist loop 再决定最终回复。

不允许：

- Agent 直接保存 artist message。
- Agent 直接覆盖 Artist phase。
- Agent 输出绕过 Artist persona。

## 9. 状态机

建议让代码控制 phase，不再完全相信 LLM 的 `next_phase`。

```text
idle
  → observing
  → planning
  → acting
  → reviewing
  → responding
  → idle

中断/特殊:
  waiting_clarification
  waiting_checkpoint
  delegated_to_agent
  failed_recoverable
  cancelled
```

第一阶段仍兼容现有 phase：

- `chat_only` → `idle`
- `ask_clarification` → `waiting_clarification`
- `generate_anchor` → LLM next_phase 或 `anchor_pending`
- `generate_pack` → LLM next_phase 或 `pack_ready`
- `refine_target` / `replace_image` → LLM next_phase 或 `refining`

第二阶段再引入内部 loop phase，不急着暴露给前端。

## 10. SSE 设计

第一阶段保持现有 SSE：

- `artist_turn_started`
- `artist_reply_delta`
- `artist_action_started`
- `artist_image_ready`
- `artist_turn_done`
- legacy `artist_done`

新增调试型事件可后置，不在第一阶段增加前端负担。

第二阶段可新增：

- `artist_tool_started`
- `artist_tool_done`
- `artist_loop_step_started`
- `artist_loop_step_done`
- `artist_delegate_started`
- `artist_delegate_done`

这些事件先供开发调试，前端不一定立即渲染。

## 11. 与 Agent 图的边界

### 11.1 Artist 适合做

- 图像目标理解。
- 图像上下文和 lineage 判断。
- 生图 prompt 决策。
- 创作风格一致性。
- 最终用户表达。

### 11.2 Agent 适合做

- 搜索和资料整理。
- 复杂计划拆解。
- 多工具任务。
- 非图像流程。
- critic / decision 循环。

### 11.3 委托原则

Artist 委托 Agent 时必须传清楚：

- 子任务目标。
- 可用工具。
- 允许输出范围。
- 返回格式。
- 是否允许生成图片。

Agent 返回后必须回到 Artist：

```text
Agent result
  → ArtistToolResult
  → Artist Loop Review
  → Artist Respond
```

## 12. 文件规划

第一阶段建议新增：

```text
backend/app/core/artist/loop.py
backend/app/core/artist/tools.py
```

或更细：

```text
backend/app/core/artist/loop_schemas.py
backend/app/core/artist/tool_executor.py
backend/app/core/artist/tool_mapping.py
```

第一阶段修改：

```text
backend/app/core/artist/runtime.py
backend/app/core/artist/schemas.py
backend/app/services/artist_service.py
backend/tests/test_artist_runtime_unit.py
backend/tests/test_artist_clarification.py
backend/tests/test_artist_image_context.py
docs/artist-runtime-knowledge.md
```

暂不修改前端。

## 13. 分阶段实施计划

### 当前实施状态

已完成：

- `ArtistToolCall` / `ArtistToolResult` / `ArtistLoopResult` 数据结构。
- `action_to_tool_calls()` 映射层。
- `ArtistToolExecutor`。
- `ArtistRuntime.handle_turn()` 内部改为 bounded tool loop。
- `self_critique` 可触发 `review_artifacts`，review 返回的下一批 image actions 会在 `max_loop_steps` 内继续执行。
- `delegate_to_agent` 已进入 `ArtistActionType`，并可通过 `artist_service` 注入的 Agent graph 回调执行；Agent 结果作为 Artist tool result 回流，不直接保存 Artist 输出。
- `inspect_lineage` / `set_lineage_head` 已接入 tool loop，可读取 lineage tree、切换 HEAD，并驱动后续 refine 使用新 HEAD 作为 parent/reference。
- `plan_complex_task` 已映射为 `start_long_task`，会按 `series_prompts` 顺序执行步骤并发射 `long_task_*` SSE。
- long task 完成后会写入 `long_task_runs`，并提供 list/get/pause/resume/cancel/checkpoint API；当前 pause/resume/cancel 是状态记录，不中断 inline 执行。
- 前端 `sessionStore` 和 `Sessions.vue` 已能消费 long task SSE 并显示当前任务进度，`sessionApi` 已有 long task API 方法。
- mock 生图验证已覆盖 prompt/reference 传递。

待实施：

- 面向前端的 `artist_tool_*` / `artist_loop_*` 调试事件。
- long task 真后台执行、运行中暂停/恢复、步骤级 checkpoint 交互。

### Phase 1: Tool 化，但保持行为兼容

目标：不改变用户可见行为，只改变内部执行结构。

任务：

1. 新增 loop/tool schema。
2. 新增 `action_to_tool_calls()`。
3. 新增 `ArtistToolExecutor`。
4. 把 Runtime 当前 gen/non-gen action 执行迁移到 ToolExecutor。
5. 保持所有现有 SSE payload 不变。
6. 更新单元测试。

验收：

- 现有 Artist runtime 单测通过。
- clarification 行为不变。
- image_context 注入行为不变。
- 生成类 action 仍走 ExecutionEngine。

### Phase 2: 引入真实 bounded loop

目标：允许一次用户 turn 内最多多轮 plan/act/review。

任务：

1. 增加 loop step 记录。
2. 工具结果回灌到 LLM。
3. LLM 可输出 `finish` / next tool calls。
4. 增加最大步数保护。
5. 增加 `review_artifacts`。

验收：

- 简单任务仍只走一轮。
- 复杂任务可以执行后 review 再结束。
- loop 超限能稳定退出。

### Phase 3: Agent delegation

目标：Artist 能把复杂子问题交给 Agent，再收回结果。

任务：

1. 抽出 `_run_agent_mode_graph()` 为可复用 service。
2. 实现 `delegate_agent` tool。
3. 设计 Agent return contract。
4. 增加测试：delegate 被调用、结果回到 Artist。

验收：

- 搜索/资料类任务可以委托 Agent。
- Agent 不直接保存 Artist 输出。
- 最终回复仍由 Artist 生成。

### Phase 4: Long task orchestration

目标：大批量和可恢复任务。

任务：

1. 引入 long task schema / model。
2. 引入 TaskOrchestrator。
3. 增加 long_task SSE。
4. 增加前端 LongTaskCard。
5. 增加 pause/resume/cancel。

验收：

- 大批量任务可按步骤执行。已完成 inline 版本。
- 断线后能查状态。已完成完成态 DB 查询。
- 前端能展示进度。已完成当前会话流式进度。

## 14. 测试策略

### 14.1 单元测试

重点覆盖：

- `action_to_tool_calls()`
- `ArtistToolExecutor.chat`
- `ArtistToolExecutor.ask_clarification`
- `ArtistToolExecutor.execute_image_plan`
- loop 最大步数退出
- tool failure handling

允许 mock 外部依赖。

### 14.2 Pipeline 测试

重点覆盖：

- `artist_orchestrate()` → loop runtime → ExecutionEngine callback。
- mock LLM 和生图外部 API。
- 不 mock 内部模块。

### 14.3 E2E 测试

后续功能稳定后再做，不在 Phase 1 强制。

必须遵守项目规则：

- 真实后端。
- 真实 provider。
- HTTP 客户端。
- 同一 session 多轮。
- 禁止 mock。

## 15. 风险与约束

### 15.1 风险

- 如果第一阶段就改 LLM 输出协议，容易导致 Artist 行为漂移。
- 如果同时引入 long task DB，会扩大回归面。
- 如果让 Agent 直接接管 Artist，会丢失 Artist persona 和 lineage 语义。
- 如果 tool result 没有结构化，后续 review 和回放会困难。

### 15.2 规避

- Phase 1 保持 LLM `ArtistTurn` 协议不变。
- Phase 1 不加前端新事件。
- Phase 1 不引入 long task。
- Agent delegation 放到 Phase 3。
- 所有新结构写单元测试。

## 16. 第一阶段建议实现边界

第一阶段只做以下事情：

- 新增 `ArtistToolCall` / `ArtistToolResult` / `ArtistLoopResult`。
- 新增 `action_to_tool_calls()`。
- 新增 `ArtistToolExecutor`。
- `ArtistRuntime.handle_turn()` 内部改为：

```text
parse ArtistTurn
  → action_to_tool_calls
  → tool_executor.execute_all
  → aggregate result
```

- 不改 `ARTIST_TURN_SYSTEM`。
- 不改前端。
- 不改数据库。
- 不新增 long task API。

这样可以先把架构骨架立起来，同时保持现有用户行为稳定。
