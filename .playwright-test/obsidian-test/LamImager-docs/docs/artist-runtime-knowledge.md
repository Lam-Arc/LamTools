# Artist Runtime Knowledge Base

更新时间：2026-05-30

本文档是 Artist 当前运行逻辑的源码级知识库，用于后续开发前快速恢复上下文，避免每次全量阅读代码。结论以当前源码为准；历史计划文档仅作背景参考。

## 一句话模型

Artist 不是单纯的生图接口，而是一个“会话编排层”：

1. `handle_artist_generate()` 保存用户消息、准备会话图像和 lineage 上下文。
2. `artist_orchestrate()` 组装 PER/CON、历史消息、视觉输入，调用 LLM 得到“回复 + 动作”。
3. `ArtistRuntime.handle_turn()` 解析动作，发 Artist SSE，委托 `ExecutionEngine` 生图，把执行结果转成 `ArtistArtifact`，更新 Artist 状态。
4. `handle_artist_generate()` 保存最终 artist 消息到数据库，lineage 服务再从消息 metadata 重建 DAG。
5. 前端只消费流式临时状态，最终显示仍依赖重新拉取消息列表。

## 关键文件

| 关注点 | 文件 |
| --- | --- |
| Artist 总入口 | `backend/app/services/generate_service.py` |
| LLM 编排层 | `backend/app/services/artist_service.py` |
| Runtime 核心 | `backend/app/core/artist/runtime.py` |
| Action / State / Artifact schema | `backend/app/core/artist/schemas.py` |
| LLM 输出解析 | `backend/app/core/artist/turn_parser.py` |
| Artist SSE payload | `backend/app/core/artist/events.py` |
| Artist 状态持久化 | `backend/app/core/artist/state_store.py` |
| Artifact 类型映射 | `backend/app/core/artist/artifacts.py` |
| Artist Tool 映射 | `backend/app/core/artist/tools.py` |
| 图像上下文解析 | `backend/app/services/image_context_resolver.py` |
| Lineage DAG 重建 | `backend/app/services/lineage_service.py` |
| 执行引擎 | `backend/app/services/executors/engine.py` |
| 前端 SSE 分发 | `frontend/src/views/Sessions.vue` |
| 前端 Artist 临时流状态 | `frontend/src/stores/session.ts` |

注意：`AGENTS.md` 提到的 `docs/plans/PLAN.md` 在当前工作树不存在。当前实际文档入口是 `docs/ROADMAP.md` 和 `docs/plans/*.md`。

## 主调用链

### 1. `handle_artist_generate()`

位置：`backend/app/services/generate_service.py`

职责：

- 校验 prompt，不允许空输入。
- 先保存用户消息：metadata 包含 `agent_mode=True`、`persona=artist`。
- 解析默认 LLM provider 和 image provider。
- 构建当前 session 图片列表：`_build_session_images()`。
- 从 `context_messages` 提取用户显式选中的上下文图片。
- 构建 Artist 历史消息：`_build_artist_history()`。
- 调用 `build_lineage_tree()` 获取当前 HEAD，并构造 `build_lineage_context_text()` 给 LLM。
- 调用 `_apply_image_context_resolution()`，把“改图 / 风格参考 / 新生成”的语义结果写到 `GenerateRequest` 临时字段，例如 `_source_image_urls`、`_generation_mode`，也可能补充 `reference_images`。
- 如果 lineage HEAD 和内存中的 Artist state 不一致，会把 state 的 `last_head_url` 同步到 lineage HEAD。
- 发布 `task_started`，然后调用 `artist_orchestrate()`。
- 把返回的 message / artifacts / blocks 保存成 `message_type="artist"` 的系统消息。
- 自动把 session metadata 的 `lineage_head_url` 更新为本轮最后一张生成图。

它是 HTTP generate 请求进入 Artist 模式后的真正入口。

### 2. `artist_orchestrate()`

位置：`backend/app/services/artist_service.py`

职责：

- 创建 `MEMModule(member=persona_name)`、`PromptAssembler(persona_name)`、`ArtistAdapter()`。
- 汇总 CON：
  - `mem.get_hot_con_text()`
  - `cold_con.user_preferences`
  - `artist_adapter.recall_preferences(query=prompt)`
- 组装系统提示词：
  - `build_hot_con_task()`
  - `build_hot_con_defaults()`
  - `ARTIST_TURN_SYSTEM`
- 注入 lineage context，作为独立 system message。
- 注入历史消息。对 user message，如果 metadata 里有外部可访问的 `reference_images`，会转成 vision blocks。
- 构建当前用户消息 vision blocks：
  - refine target 最优先，作为 `图0`
  - 用户 pinned context images
  - session_images，倒序，最近优先
  - reference_images
  - 最多 8 张
- 构建 `image_map`：把 `图0`、`图1` 等标签映射到真实 URL，供 Runtime 执行动作前解析。
- 解析 LLM provider，创建 `LLMClient`。
- 定义 `_llm_call()`：
  - 调 `client.chat_stream()`
  - 累积完整文本和 usage
  - 同时向前端发布 legacy `artist_token`
- 定义 `_execution_engine_run()`：
  - 创建 `ExecutionEngine(plan, context, llm_call=_multimodal_call)`
  - 调 `engine.run_all()`
- 定义 `_event_publish()`：
  - 把 runtime 产出的 Artist SSE payload 包进 `LamEvent(event_type="task_progress")`
- 创建共享 `ArtistStateStore` 和 `ArtistRuntimeDeps`，调用 `ArtistRuntime.handle_turn()`。
- 对 runtime 结果进行 billing：`log_and_bill()`。
- 把 `ArtistArtifact` 转成对外 artifacts dict。
- 如果有 artifacts：
  - `_vision_review()` 做图像总结。
  - `extract_artist_feedback()` 把用户反馈写入 MEM。
  - 把输出索引写入 MEM `output_index`。
- 发布 legacy `artist_done`、`agent_node_progress done`。

它是 Artist 的“LLM + 运行时依赖适配层”。

### 3. `ArtistRuntime.handle_turn()`

位置：`backend/app/core/artist/runtime.py`

职责：

1. 从 `ArtistStateStore` 取 session state。
2. 发布 `artist_turn_started`。
3. 可选注入 `image_context_resolver` 返回的 recent image context。
4. 调 `deps.llm_call()` 获取完整 LLM 输出和 usage。
5. 用 `_extract_message()` 从 JSON 中取 `message`，并用 `_stream_deltas()` 切块发布 `artist_reply_delta`。
6. 用 `parse_artist_turn()` 解析为 `ArtistTurn`。
7. 用 `image_map` 把 action 中的 `reference_images=["图0"]` 解析成真实 URL。
8. 用 `action_to_tool_calls()` 把 `ArtistAction` 映射为内部 `ArtistToolCall`：
   - `chat_only` → `chat`
   - `ask_clarification` → `ask_clarification`
   - `self_critique` → `review_artifacts`
   - 图像生成 / 编辑 action → `execute_image_plan`
9. Runtime 按 tool call 执行，并记录 `tool_results`。
10. `chat` / `ask_clarification` / `review_artifacts` 当前保持轻量行为：发布 `artist_thinking` 和 `artist_action_started`，不产生 artifacts。
11. `execute_image_plan`：
    - `infer_strategy()` 推导执行策略。
    - `build_plan_steps()` 转成 `ExecutionPlan` steps。
    - `_collect_initial_refs()` 决定 `PlanningContext.reference_images`。
    - 调 `deps.execution_engine_run(plan, context, db, task_manager)`。
    - `radiate` 策略走 `_crop_grid_to_artifacts()`；否则走 `_trace_to_artifacts()`。
    - 对每个 artifact 发布 `artist_image_ready`。
12. 累加 execution trace 的 cost / tokens。
13. 更新 Artist state：
    - `_update_state()` 写 pending prompt / pack count。
    - `_state_updates()` 写 head、root、group、branch 等关键字段。
14. 发布 `artist_turn_done`。
15. 返回 message、blocks、artifacts、phase、tokens、cost，以及调试用 `tool_calls` / `tool_results`。

Runtime 是 Artist 行为最集中的地方。

## LLM 输出协议

系统提示词常量：`ARTIST_TURN_SYSTEM`。

核心规则：

- 纯聊天：LLM 可以直接输出纯文本，不包 JSON。
- 需要图像动作：LLM 必须输出 JSON：

```json
{
  "message": "简短回复",
  "actions": [
    {
      "type": "generate_anchor",
      "prompt": "实际生图提示词",
      "image_count": 1
    }
  ],
  "next_phase": "anchor_pending"
}
```

解析逻辑在 `turn_parser.py`：

- `response_format_mode="text"`：整段输出变成 `chat_only`。
- `response_format_mode="auto"`：先尝试 JSON，失败则降级为 `chat_only`。
- `response_format_mode="json"`：严格 JSON，解析失败不自动转文本。
- 如果 JSON 有 `message` 但没有动作，会补一个 `chat_only` safety net。
- 同一轮如果同时出现 video action 和 image action，会移除 image action。

## Action 类型

Schema 在 `schemas.py`。

当前 Runtime 已主要支持的图像 action：

- `chat_only`：纯聊天。
- `ask_clarification`：反问澄清。
- `generate_anchor`：生成一个主图。
- `generate_pack`：生成一组图。单 action 默认走 `radiate`。
- `refine_target`：基于目标图精修。
- `replace_image`：替换目标图。
- `style_reference`：按参考风格生成或修改。
- `self_critique`：非生成动作，目前主要发事件。

Schema 里还有 video / batch / series 预留字段：

- `generate_video`
- `extract_frame`
- `trim_video`
- `adjust_video`
- `plan_series`
- `batch_execute`
- `batch_correct`

这些类型已出现在 schema / events / artifact map，但当前 `ArtistRuntime.handle_turn()` 对 video/batch/series 没有完整专用执行分支；新增能力时要先确认 `ExecutionEngine` 是否支持这些 action 对应的 plan step。

## 策略推导

函数：`infer_strategy(gen_actions)`。

规则：

- 只有一个 action：
  - `generate_pack` → `radiate`
  - 其他 → `single`
- 多个 action：
  - 同时有 `generate_anchor` 和 refine/replace/style → `iterative`
  - 有 `generate_pack` → `radiate`
  - 其他 → `iterative`

`build_plan_steps()` 把 Artist action 转成 ExecutionEngine step：

- `generate_anchor`：强制 `image_count=1`。
- `generate_pack` + `radiate`：只生成一张 grid anchor，后续由 Runtime 裁切。
- `generate_pack` + 非 radiate：按 `image_count` 或 `artist_pack_count` 多张生成。
- refine/replace/style：如果同一轮前面有 anchor 且策略是 iterative，会设置 `reference_step_indices=[anchor_index]`。

## Radiate 模式

`generate_pack` 的单 action 默认走 `radiate`：

1. ExecutionEngine 只生成一张 grid anchor。
2. Runtime 创建 anchor artifact。
3. 尝试 `_detect_grid_multimodal()` 用多模态 LLM 判断 grid 行列。
4. 失败则 `_compute_grid_config()` 用数量启发式：
   - 1-2：`n x 1`
   - 3-4：`2 x 2`
   - 5-6：`3 x 2`
   - 7-9：`3 x 3`
   - 更多：`4 x ceil(n/4)`
5. `_crop_cell_async()` 裁切每个 cell。
6. `_persist_base64_urls()` 把裁切出来的 base64 保存成 HTTP URL。
7. 每个 cell 变成 `artifact_type="pack"`，parent/root 指向 anchor。

重要风险：radiate 的 cell prompt 当前是 `"{pack_action.prompt}, cell N"`，不使用 `series_prompts` 的逐项提示词。

## Artifact 与 Lineage

`ArtistArtifact` 字段重点：

- `artifact_id`
- `parent_artifact_id`
- `root_artifact_id`
- `parent_url`
- `root_url`
- `branch_name`
- `group_id`
- `index_in_group`
- `prompt`

Runtime 只把 artifact 信息返回给 `handle_artist_generate()`。真正持久化发生在 artist 消息 metadata 中：

```text
metadata.artifacts[]
metadata.images
metadata.final_images
metadata.source_image_urls
metadata.generation_mode
metadata.artist_turn_id
```

`lineage_service.build_lineage_tree()` 不读取 ArtistStateStore，而是读取 session 全部 message metadata 重建 DAG：

- 对 `message_type="artist"`，优先从 `metadata.artifacts[]` 的 `parent_url` 建立每个输出 URL 的父子关系。
- 如果 artifact 没有 parent，会退回到顶层 `source_image_urls`。
- root 是没有 source 的 URL。
- 分支分配规则：同一个 parent 的第一个 child 继承父分支，后续 child 自动成为 `branch-N`。
- HEAD 存在 session metadata：`lineage_head_url`。
- 分支重命名存在 session metadata：`lineage_branch_renames`。

这意味着：如果要修 lineage，优先检查消息 metadata，不要只看 `data/artist_state/*.json`。

## 图像上下文解析

核心：`ImageContextResolver.resolve_image_context()`。

优先级：

1. `refine_mode + manual_refine_images`：强制 `edit_target`。
2. `refine_mode` 无显式图：用 `selected_image_url` 或最新可编辑图。
3. 非 refine 但有 `selected_image_url`：结合 prompt intent 判断 edit/batch/style。
4. prompt 显式引用 `第N张`、`图N`、裸数字：按 session_images 序号定位。
5. prompt 引用原图 / 初始图：找当前 lineage root。
6. prompt 引用回退 / 回到：解析 rollback target。
7. 否则按 intent：
   - `new_generation`
   - `style_reference`
   - `batch_edit`
   - `edit_target`

`handle_artist_generate()` 会调用 `_apply_image_context_resolution()`，把解析结果注入 `GenerateRequest`。如果识别为 edit/style/batch 且有 lineage HEAD，会把 HEAD 注入 `context_images`，让 LLM 看到 `图0`。

## Artist StateStore

`ArtistStateStore` 是运行时状态缓存 + JSON 文件持久化：

- 默认目录：`data/artist_state`
- key：`session_id`
- get 时优先内存，其次读 JSON 文件，否则创建默认 `ArtistSessionState`

关键字段：

- `phase`
- `anchor_group_id`
- `last_group_id`
- `pending_prompt`
- `pack_count`
- `head_artifact_id`
- `last_head_url`
- `last_head_root_url`
- `last_head_root_artifact_id`
- `active_branch`
- `previous_head_children`
- `branch_counter`

注意边界：

- StateStore 用于 Runtime 当前轮的 parent/head 判断。
- Lineage Drawer 和长期 DAG 以数据库 message metadata + session metadata 为准。
- `handle_artist_generate()` 已尝试把 `state.last_head_url` 同步到 lineage HEAD，但只同步 URL，没有同步 `head_artifact_id` 等全部字段。

## SSE 事件

后端 payload 定义在 `events.py`。Artist 当前主链路发出的事件：

1. `artist_turn_started`
2. `artist_reply_delta`
3. `artist_action_started`
4. `artist_image_ready`
5. `artist_turn_done`
6. legacy `artist_done`
7. 最外层任务事件：`task_started`、`task_completed`、`task_failed`

包装方式：

- Runtime 只产出 payload dict。
- `artist_service._event_publish()` 把这些 payload 包成 `LamEvent(event_type="task_progress", correlation_id=f"agent-{session_id}")`。
- 前端根据 `event.payload.type` 分发。

前端消费：

- `frontend/src/views/Sessions.vue` 的 `useSessionEvents()` 回调 switch Artist payload type。
- `frontend/src/stores/session.ts`：
  - `handleArtistTurnStarted()` 创建临时流状态。
  - `handleArtistReplyDelta()` 累积内容。
  - `handleArtistActionStarted()` 追加 action。
  - `handleArtistImageReady()` 标记 action done，记录 artifact / imageUrl。
  - `handleArtistTurnDone()` 标记 done。
  - `handleArtistFinalize()` 在 task 完成或失败后重新 `fetchMessages()`，然后删除临时流状态。

## 数据落库边界

用户输入：

- `handle_artist_generate()` 一开始保存 user message。

Artist 输出：

- Runtime 不直接写 message 表。
- `handle_artist_generate()` 最后保存 `message_type="artist"` 的系统消息。

Billing：

- `artist_orchestrate()` 在 Runtime 返回后调用 `log_and_bill()`。

MEM：

- `artist_orchestrate()` 读取热/冷 CON。
- 生成 artifacts 后做 `_vision_review()` 并写 `output_index`。
- 用户反馈命中 `extract_artist_feedback()` 后写 preference 或 output feedback。

Lineage：

- `handle_artist_generate()` 保存 artist message metadata。
- 然后自动更新 session metadata `lineage_head_url=all_urls[-1]`。

## Tool 化状态

当前已完成 Phase 1，并具备 Phase 2/3 的后端可验证骨架：

- `backend/app/core/artist/tools.py` 定义 `ArtistToolCall`、`ArtistToolResult`、`ArtistLoopResult`。
- `action_to_tool_calls()` 保持现有 LLM `ArtistTurn` 协议不变，只在 Runtime 内部转换。
- `ArtistToolExecutor` 负责执行 `chat`、`ask_clarification`、`execute_image_plan`、`review_artifacts`、`delegate_agent`。
- `ArtistRuntime.handle_turn()` 已变成 bounded tool loop；`max_loop_steps` 默认 4。
- 所有图像类 action 会被合并为一个 `execute_image_plan` tool call，继续复用 `ExecutionEngine`。
- `self_critique` 会在已有 artifacts 基础上调用 review；如果 review LLM 返回新的 image actions，会继续进入下一轮 tool execution。
- `delegate_to_agent` 已加入 schema 和系统 prompt；`artist_service` 会注入 Agent graph 回调，结果作为 Artist tool result 回流。
- `inspect_lineage` / `set_lineage_head` 已加入 schema 和 tool executor，可读取当前 lineage tree、切换 HEAD，并让后续 refine 使用新 HEAD URL 作为 parent/reference。
- `plan_complex_task` 已映射为 `start_long_task`，当前 inline 执行 `series_prompts`，发射 `long_task_created`、`long_task_step_started`、`long_task_step_completed`、`long_task_progress`、`long_task_completed`。
- long task 完成后写入 `long_task_runs`，`backend/app/routers/long_task.py` 提供 list/get/pause/resume/cancel/checkpoint API；当前 pause/resume/cancel 是状态记录，不中断 inline 执行。
- 前端 `sessionStore` 和 `Sessions.vue` 已能消费 long task SSE 并显示当前会话的长任务进度，`sessionApi` 已有 long task API 方法。
- 当前未改变前端 SSE，`artist_turn_started` / `artist_reply_delta` / `artist_action_started` / `artist_image_ready` / `artist_turn_done` 仍是主链路。
- long task 真后台执行、运行中暂停/恢复、步骤级 checkpoint 交互仍是后续增强。

设计文档见：`docs/artist-loop-tool-agent-architecture.md`。

## 常见修改入口

### 想改“什么时候画，什么时候只聊天”

优先看：

- `ARTIST_TURN_SYSTEM`
- `turn_parser.py`
- `image_context_resolver.py`

风险点：

- `ARTIST_TURN_SYSTEM` 影响 LLM 输出协议。
- `response_format_mode` 会改变解析分支。
- 修改 intent pattern 可能影响 lineage parent 归属。

### 想改“图0 / 图1 怎么选”

优先看：

- `artist_service.py` 中 all_vision_urls 构建顺序。
- `ImageContextResolver.resolve_image_context()`。
- `handle_artist_generate()` 中 lineage HEAD 注入 `context_images` 的逻辑。

当前顺序：refine target → pinned context → session_images 最近优先 → reference_images。

### 想改“生图策略”

优先看：

- `infer_strategy()`
- `build_plan_steps()`
- `ExecutionEngine.run_all()`

避免只改 prompt。Artist action 到 ExecutionEngine plan 的转换才决定真实执行形态。

### 想改“组图 / 表情包”

优先看：

- `generate_pack`
- `radiate`
- `_crop_grid_to_artifacts()`
- `_detect_grid_multimodal()`
- `_compute_grid_config()`

当前 radiate 是“生成一张大图再裁切”，不是 N 次独立生成。

### 想改“分支 / 回退 / HEAD”

优先看：

- `lineage_service.py`
- `image_context_resolver.py`
- `handle_artist_generate()` 中 state 和 lineage HEAD 同步逻辑。
- `ArtistRuntime._trace_to_artifacts()`

判断问题时按这个顺序查：

1. artist message metadata 里的 artifacts parent/root 是否正确。
2. session metadata 的 `lineage_head_url` 是否正确。
3. StateStore 的 `last_head_url` 是否和 lineage HEAD 一致。
4. 前端 LineageDrawer 是否只是展示层问题。

## 已知不一致 / 风险点

- `docs/plans/PLAN.md` 不存在，AGENTS 索引滞后。
- `transitions.py` 定义了状态机，但当前 `ArtistRuntime.handle_turn()` 主要直接采用 LLM 返回的 `next_phase`，没有显式调用 `apply_transition()`。
- `normalizer.py` 存在工具名归一化，但当前主链路直接从 LLM JSON 解析 `ArtistAction`，未看到 Runtime 主路径使用 `normalize_action()`。
- schema 中 video / batch / series 字段较多，但 Runtime 主执行路径仍按“非生成 / 生成后交给 ExecutionEngine”处理，专用能力需要逐项核实。
- `ArtistStateStore` 和 lineage DB metadata 是两个事实源：长期 UI 以 DB metadata 重建，Runtime 当轮可能依赖 StateStore。
- `handle_artist_generate()` 同步 lineage HEAD 到 StateStore 时只同步 `last_head_url`，不补全 `head_artifact_id/root`，某些 parent artifact id 可能为空，只能靠 URL fallback。
- `radiate` 模式没有使用 `series_prompts` 逐项 prompt，且裁切质量依赖 grid 检测。

## 快速调试清单

收到一个 Artist bug，先按顺序看：

1. 用户消息是否进入 `handle_artist_generate()`，是否保存为 `persona=artist`。
2. `_apply_image_context_resolution()` 输出的 `_generation_mode` 和 `_source_image_urls` 是否正确。
3. `lineage_context` 是否指向正确 HEAD。
4. `artist_orchestrate()` 构建的 `image_map` 中 `图0` 是否是预期目标。
5. LLM 原始输出是否符合 JSON 协议。
6. `parse_artist_turn()` 后的 actions 是否正确。
7. `infer_strategy()` 和 `build_plan_steps()` 是否把 action 转成预期 plan。
8. `ExecutionEngine` trace 是否有 artifacts。
9. `_trace_to_artifacts()` 或 `_crop_grid_to_artifacts()` 生成的 parent/root 是否正确。
10. artist message metadata 是否保存了完整 artifacts。
11. `build_lineage_tree()` 是否从 metadata 重建出正确 DAG。
12. 前端临时流状态是否只是显示中间态，最终消息是否已重新拉取。

## 测试边界

测试规则仍按 AGENTS：

- 单元测试：允许 mock 外部依赖。
- pipeline 集成测试：可 mock LLM / 生图外部 API，不 mock 内部模块。
- e2e：必须真实后端、真实 provider、HTTP 客户端、同一 session 多轮对话、禁止 mock。

Artist 相关现有测试入口：

- `backend/tests/test_artist_runtime_unit.py`
- `backend/tests/test_artist_pipeline.py`
- `backend/tests/test_artist_orchestrate.py`
- `backend/tests/test_artist_image_context.py`
- `backend/tests/test_artist_clarification.py`
- `backend/tests/test_artist_e2e_smoke.py`
- `backend/tests/test_artist_e2e_rigorous.py`

## 2026-05-31 Artist 套系真实测试记录

测试目标：验证 Artist 是否能用 anchor 统一套系，并在后续轮次准确改指定物料。

业务判断：

- Anchor 策略有效。先生成品牌设定图，再生成物料，能明显提高 logo、配色、图形母题和版式语言的一致性。
- `artifact_id` 引用有效。用户说“杯身图案那张”时，后续改图能挂到杯身 artifact，不会误挂到 anchor 或招牌。
- 谱系正确。完整 5 物料测试中，anchor 是唯一 root，五个物料从 anchor 分叉，杯身极简改图从杯身继续派生。
- 长任务不能全串行。完整 5 物料串行会超时；改为“先 anchor，后续同级物料并发”后，真实测试可完成。
- 当前视觉质量可用于方向稿。品牌感和套系感成立，但文字、小字和最终生产稿仍需要后期设计处理。
- 主要产品问题不在谱系，而在交付类型意识。Artist 需要区分效果图、平面稿、生产稿、社媒成图、门店空间图。

后续优化优先级：

1. 保持 anchor + artifact_id 谱系策略。
2. 继续优化物料类型表达，避免把“杯身图案”只做成杯子 mockup。
3. 对真实多图任务继续使用依赖分组并发，避免超时。
4. 跨会话真实并发需要单独改造：当前同时启动多个 Artist 会话会叠加 VLM、生图、本地图片处理和 SQLite 写入，容易超时或只完成部分轮次。后续需要全局队列、跨会话并发上限、tool 超时和取消回收；单会话内部的同级子项并行仍然保留。

T4-T7 续测判断：

- “切到某张继续改”不应默认生成新图。当前 Artist 会把上一轮修改意图带到新目标上，导致 T4 直接生成招牌极简版。
- “当前物料分支”还不够稳定。T5 识别到招牌，但 parent 回到原始招牌，而不是 T4 后的招牌 HEAD。
- “检查整套是否统一”目前更像单图修复。T6 判断到招牌不统一，但只修了招牌，没有真正对整套物料做多图比较和成套修复。
- “先查一下”没有稳定触发外部检索或 Agent。T7 只给了简短回复，没有搜索结果、方向分析或优化产物。
- T4-T7 的主要问题不是生图质量，而是任务状态和工具选择：切换目标、分支 HEAD、套系级审查、检索工具需要更明确的 loop 决策。

## 2026-05-31 Visual Workspace 混合方案

业务目标：让 Artist 在多轮视觉任务里知道“现在改哪张、这套图有哪些当前版本、什么时候该查资料”，不要只靠上一轮聊天猜。

已实现判断：

- 会话内维护当前视觉工作区。每个物料有 original 和 current，current 从谱系图重建，缓存只保存当前选择和快速索引。
- 用户说“切到门店招牌那张继续改”这类只切换目标的话，不生图，只更新当前目标。
- 用户继续说“招牌加冷白灯箱感”时，默认引用招牌当前版本，而不是最早的招牌。
- 用户说“检查整套/这套物料是否统一”时，只把各物料 current 版本放进本轮视觉上下文，避免旧版本干扰判断。
- 用户说“查一下/搜索/调研/常见视觉元素”时，Artist 不再进入旧 Agent 图；当前版本先基于已有上下文说明，后续按 Runtime tool contract 重做检索。
- “检查一下”不是调研意图，不能被误判成“查一下”。

当前边界：

- 物料名识别仍是轻量规则加谱系重建，适合常见物料；更开放的命名后续可交给 LLM 做结构化提取。
- 套系审查已经能看 current 版本，但“自动多图修复”还依赖 Artist 后续工具决策，不是强制全量修复。
- 旧 Agent 委托已移出主链；真实检索能力后续作为 Runtime tool 重建。

真实 T1-T7 复测结论：

- T1 纯视觉方向正常，不误生图。
- T2 能先生成品牌视觉设定，再生成主视觉海报、杯身图案、外卖袋、社媒方图、门店招牌；整体品牌名、logo、黑金太空咖啡调性一致。
- T3 正确沿杯身分支改极简，parent 指向原杯身。
- T4 正确只切换到门店招牌，不生成图片。
- T5 正确沿门店招牌分支继续改冷白灯箱，parent 指向原门店招牌。
- T6 初测暴露问题：套系检查被错误委托给 Agent 并反问用户。修复后，套系检查由 Artist 基于当前物料图判断，识别门店招牌不统一，并沿门店招牌当前版本修一版。
- T7 初测暴露问题：调研委托进入 Agent 图像规划并产出误图。修复后，调研委托改为文本调研链路，返回调研和优化建议，不生成图片。
- 当前谱系正确：anchor 是 root；五个物料从 anchor 分叉；杯身 current 是极简版；门店招牌 current 是 T6 修正版；visual workspace active target 为门店招牌 current。

## 2026-05-31 Runtime 主内核收敛

决策：Agent 图不再作为 LamImager 主执行链路。当前后端入口统一进入 Artist Runtime；旧 `handle_agent_generate()` 已从 active path 移除。

当前边界：

- Runtime 是主循环：接收 turn、维护状态、选择动作、调用工具、写回 artifact 和谱系。
- Agent 图不再由 Artist 委托调用，也不再由 CLI complex_task 调用。
- 调研类请求暂时留在 Runtime 内由 LLM 基于已有知识回答；当前版本不做外部检索，不生成调研误图。
- 后续需要 Agent 能力时，按 Runtime tool/agent contract 重新开发，不复用旧 Agent 图作为主编排器。
