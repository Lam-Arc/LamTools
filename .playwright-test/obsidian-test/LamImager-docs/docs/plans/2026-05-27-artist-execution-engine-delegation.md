# Artist → ExecutionEngine 委派重构计划

## 问题根因

Artist runtime 的 `_execute_action()` 直接调用 `deps.image_generate` (= `generate_images_core`)，完全绕过了 Agent 的 ExecutionEngine。后果：

1. **多步意图无法顺序执行**: "先画线稿再上色" → LLM 输出 `[anchor, refine]` → `asyncio.gather` 并行执行 → refine 的 parent_url 为空
2. **没有 reference_step_indices**: 父子关系靠 runtime 手工拼 parent_url/root_url，容易出错且与 lineage tree 机制不一致
3. **辐射策略缺失**: `generate_pack` (表情包) 只出多图，没有 ExecutionEngine 的 anchor→crop→expand 流程
4. **谱系图 bug**: ExecutionEngine 已验证正确（iterative sequential、radiate anchor→crop→expand、StepContextResolver reference delivery），Artist 绕过了这一切

## 设计目标

- Artist 保留对话编排（PER → LLM → turn → actions）
- Artist 必须有 **零直接生图能力**，所有生图执行委派给 ExecutionEngine
- 委派后谱系图 bug 自然修复（ExecutionEngine 已有正确的 reference_step_indices + StepContextResolver + group_steps() 顺序执行）

## 架构桥接设计

### ArtistAction → ExecutionPlan 映射

Artist LLM 输出 `actions`，ExecutionEngine 需要 `ExecutionPlan(steps, strategy)`。需要一个 **策略推断层** 把 gen_actions 转换为 ExecutionPlan：

| gen_actions 组合 | 策略 | PlanStep 构建 |
|---|---|---|
| 单个 `generate_anchor` | `single` | 1 step, image_count=1, 无 reference_step_indices |
| 单个 `refine_target` / `replace_image` | `single` | 1 step, image_count=N, reference_images 从 action.reference_images 填入 PlanningContext |
| `generate_anchor` + `refine_target` (先X再Y) | `iterative` | step[0]: anchor, step[1]: refine, reference_step_indices=[0] |
| `generate_anchor` + 多个 `refine_target` | `iterative` | step[0]: anchor, step[i>0]: refine, reference_step_indices=[0] |
| `generate_pack` (套图) | `radiate` | step[0]: anchor grid, step[1..N]: individual items, reference_step_indices=[0], metadata.crop_from_anchor |
| `generate_anchor` + `generate_pack` | `iterative` + `radiate` 混合 | 暂不支持，退化为 sequential iterative |

### 策略推断算法

```python
def infer_strategy(gen_actions: list[ArtistAction]) -> str:
    if len(gen_actions) == 1:
        action = gen_actions[0]
        if action.type == "generate_pack":
            return "radiate"
        return "single"
    
    # 多步: check if any refine follows an anchor
    has_anchor = any(a.type == "generate_anchor" for a in gen_actions)
    has_refine = any(a.type in ("refine_target", "replace_image", "style_reference") for a in gen_actions)
    
    if has_anchor and has_refine:
        return "iterative"
    
    # All same type (e.g., multiple packs) → parallel (future)
    return "iterative"  # default fallback for multi-step
```

### PlanStep 构建算法

```python
def build_plan_steps(gen_actions: list[ArtistAction], strategy: str) -> list[dict]:
    steps = []
    anchor_index = None
    
    for i, action in enumerate(gen_actions):
        step_dict = {
            "prompt": action.prompt,
            "negative_prompt": action.negative_prompt or "",
            "description": action.type,  # use action type as description
            "image_count": _resolve_count(action),
            "image_size": action.image_size or "",
        }
        
        if action.type == "generate_anchor":
            anchor_index = i
            step_dict["image_count"] = 1  # anchor always 1 image
        
        elif action.type == "generate_pack":
            step_dict["image_count"] = action.image_count or effective_pack_count
            if strategy == "radiate" and anchor_index is not None:
                step_dict["reference_step_indices"] = [anchor_index]
                step_dict["metadata"] = {"crop_from_anchor": True, "items": [...]}
        
        elif action.type in ("refine_target", "replace_image", "style_reference"):
            if anchor_index is not None and strategy == "iterative":
                step_dict["reference_step_indices"] = [anchor_index]
            # For single refine without anchor: reference comes from PlanningContext
        
        steps.append(step_dict)
    
    return steps
```

## 实施步骤（精确到文件和行号）

### Step 1: 修改 `ArtistRuntimeDeps` — 替换 `image_generate` 为 `execution_engine_run`

**文件**: `backend/app/core/artist/runtime.py` (line 49-55)

**变更**:
- 移除 `image_generate: Callable[..., Coroutine[Any, Any, tuple[list[str], int, int]]]`
- 添加 `execution_engine_run: Callable[..., Coroutine[Any, Any, ExecutionTrace]]`

新的 callback 签名：
```python
execution_engine_run: Callable[
    [ExecutionPlan, PlanningContext, AsyncSession, "TaskManager"],
    Coroutine[Any, Any, ExecutionTrace]
]
```

### Step 2: 修改 `handle_turn` — 用 ExecutionPlan 替代 asyncio.gather

**文件**: `backend/app/core/artist/runtime.py` (line 158-182)

**当前逻辑**:
```python
# Line 158-182: asyncio.gather parallel execution
if gen_actions:
    import asyncio
    async def _run_one(action): ...
    results = await asyncio.gather(*[_run_one(a) for a in gen_actions])
```

**新逻辑**:
```python
if gen_actions:
    strategy = infer_strategy(gen_actions)
    plan_steps = build_plan_steps(gen_actions, strategy, effective_pack_count=effective_pack_count)
    
    plan = ExecutionPlan.from_steps(
        steps=plan_steps,
        strategy=strategy,
        source="artist",
        intent_meta={"artist_turn_id": artist_turn_id, "actions": [a.type for a in gen_actions]},
        plan_meta={"context_reference_urls": reference_images or []},
    )
    
    context = PlanningContext(
        session_id=session_id,
        prompt=gen_actions[0].prompt,
        negative_prompt=negative_prompt,
        image_count=default_count,
        image_size=default_size,
        reference_images=_collect_initial_refs(gen_actions, reference_images, state),
        image_provider_id=image_provider_id,
    )
    
    trace = await self.deps.execution_engine_run(plan, context, db, task_manager)
    
    # Convert ExecutionTrace → ArtistArtifact list
    artifacts = _trace_to_artifacts(trace, gen_actions, state, artist_turn_id)
```

**注意**: `handle_turn` 需要接收 `db` 和 `task_manager` 参数（当前没有），需要新增。

### Step 3: 新增 `infer_strategy` 和 `build_plan_steps` 函数

**文件**: `backend/app/core/artist/runtime.py` (在 class 定义之前)

```python
def infer_strategy(gen_actions: list[ArtistAction]) -> str:
    """Infer ExecutionEngine strategy from Artist gen_actions."""
    if len(gen_actions) == 1:
        action = gen_actions[0]
        if action.type == "generate_pack":
            return "radiate"
        return "single"
    
    has_anchor = any(a.type == "generate_anchor" for a in gen_actions)
    has_refine = any(a.type in ("refine_target", "replace_image", "style_reference") for a in gen_actions)
    
    if has_anchor and has_refine:
        return "iterative"
    
    if any(a.type == "generate_pack" for a in gen_actions):
        return "radiate"
    
    return "iterative"


def build_plan_steps(
    gen_actions: list[ArtistAction],
    strategy: str,
    effective_pack_count: int = 6,
) -> list[dict]:
    """Convert Artist gen_actions to ExecutionPlan step dicts."""
    steps = []
    anchor_index = None
    
    for i, action in enumerate(gen_actions):
        step_dict = {
            "prompt": action.prompt,
            "negative_prompt": action.negative_prompt or "",
            "description": f"artist:{action.type}",
            "image_size": action.image_size or "",
        }
        
        # Resolve image_count based on action type
        if action.type == "generate_anchor":
            step_dict["image_count"] = 1
            anchor_index = i
        elif action.type == "generate_pack":
            step_dict["image_count"] = action.image_count or effective_pack_count
            if strategy == "radiate":
                # Pack in radiate mode: first step is anchor grid
                # Re-structure: step 0 = anchor (1 grid), step 1..N = items
                # This requires special handling - see radiate strategy below
                pass
        elif action.type in ("refine_target", "replace_image", "style_reference"):
            step_dict["image_count"] = action.image_count or 1
            if anchor_index is not None and strategy == "iterative":
                step_dict["reference_step_indices"] = [anchor_index]
        else:
            step_dict["image_count"] = action.image_count or 1
        
        # Metadata for action type tracking
        step_dict["metadata"] = {"artist_action_type": action.type}
        
        steps.append(step_dict)
    
    return steps


def _collect_initial_refs(
    gen_actions: list[ArtistAction],
    reference_images: list[str] | None,
    state: ArtistSessionState,
) -> list[str]:
    """Collect initial reference images for PlanningContext."""
    refs = list(reference_images or [])
    # Auto-add most recent head image for refine actions
    for action in gen_actions:
        if action.reference_images:
            for ref in action.reference_images:
                if ref not in refs:
                    refs.append(ref)
    # If no refs but has refine actions and state has last_head_url
    has_refine = any(a.type in ("refine_target", "replace_image", "style_reference") for a in gen_actions)
    if not refs and has_refine and state.last_head_url:
        refs.append(state.last_head_url)
    return refs
```

### Step 4: 新增 `_trace_to_artifacts` 函数

**文件**: `backend/app/core/artist/runtime.py`

把 ExecutionTrace 的结果转回 ArtistArtifact 列表，保持现有的 lineage metadata 逻辑。

```python
def _trace_to_artifacts(
    trace: ExecutionTrace,
    gen_actions: list[ArtistAction],
    state: ArtistSessionState,
    artist_turn_id: str,
) -> list[ArtistArtifact]:
    """Convert ExecutionTrace step artifacts to ArtistArtifact list."""
    artifacts = []
    group_id = state.anchor_group_id or str(uuid4())[:8]
    
    # Map step artifacts to actions
    for step_idx, step_trace in enumerate(trace.step_traces):
        if step_idx >= len(gen_actions):
            break
        action = gen_actions[step_idx]
        artifact_type = action_type_to_artifact_type(action.type)
        
        for img_idx, artifact in enumerate(step_trace.artifacts):
            url = artifact.url
            if not url:
                continue
            
            # Compute lineage metadata from step relationships
            parent_url = ""
            root_url = ""
            parent_artifact_id = ""
            root_artifact_id = ""
            branch_name = state.active_branch
            
            if artifact_type == "anchor":
                # Anchor is the root
                root_url = url
                root_artifact_id = str(uuid4())[:8]
            elif state.head_artifact_id:
                parent_url = state.last_head_url
                root_url = state.last_head_root_url or parent_url
                parent_artifact_id = state.head_artifact_id
                root_artifact_id = state.last_head_root_artifact_id or state.head_artifact_id
            
            art = ArtistArtifact(
                artifact_id=str(uuid4())[:8],
                artifact_type=artifact_type,
                url=url,
                prompt=action.prompt,
                artist_turn_id=artist_turn_id,
                group_id=group_id,
                index_in_group=img_idx,
                parent_url=parent_url,
                root_url=root_url or url,
                parent_artifact_id=parent_artifact_id,
                root_artifact_id=root_artifact_id or art.artifact_id,
                branch_name=branch_name,
                source_message_id="",
            )
            
            if artifact_type == "anchor" or not state.head_artifact_id:
                art.root_url = art.url
                art.root_artifact_id = art.artifact_id
            
            artifacts.append(art)
    
    # Branch detection for multi-artifact turns
    if state.head_artifact_id and artifacts:
        state.branch_counter += 1
        branch_name = f"分支-{state.branch_counter}"
        state.active_branch = branch_name
        for art in artifacts:
            art.branch_name = branch_name
    
    return artifacts
```

### Step 5: 修改 `artist_service.py` — 绑定 ExecutionEngine 到 deps

**文件**: `backend/app/services/artist_service.py` (line 284-312)

**当前逻辑**:
```python
async def _image_gen(**kwargs):
    return await generate_images_core(db=db, provider_id=image_provider_id, ...)

deps = ArtistRuntimeDeps(
    state_store=state_store,
    llm_call=_llm_call,
    image_generate=_image_gen,
    event_publish=_event_publish,
)
```

**新逻辑**:
```python
async def _execution_engine_run(plan, context, db_session, task_mgr):
    from app.services.executors.engine import ExecutionEngine
    engine = ExecutionEngine(plan, context)
    return await engine.run_all(db_session, task_mgr)

deps = ArtistRuntimeDeps(
    state_store=state_store,
    llm_call=_llm_call,
    execution_engine_run=_execution_engine_run,
    event_publish=_event_publish,
)
```

**移除**: `from app.services.generate_service import generate_images_core` (line 19) — Artist 不再直接调用。

### Step 6: 修改 `handle_turn` 签名 — 新增 `db` 和 `task_manager` 参数

**文件**: `backend/app/core/artist/runtime.py` (line 62-81)

```python
async def handle_turn(
    self,
    session_id: str,
    prompt: str,
    artist_turn_id: str,
    messages: list[dict] | None = None,
    system_prompt: str = "",
    image_context: dict | None = None,
    default_size: str = "1024x1024",
    default_count: int = 1,
    image_provider_id: str | None = None,
    reference_images: list[str] | None = None,
    image_map: dict[str, str] | None = None,
    negative_prompt: str = "",
    artist_pack_count: int = 6,
    artist_model_mode: str = "auto",
    artist_anchor_first: bool = True,
    response_format_mode: str = "auto",
    refine_mode: bool = False,
    db: AsyncSession | None = None,        # 新增
    task_manager: "TaskManager | None" = None,  # 新增
) -> dict:
```

### Step 7: 修改 `artist_service.py` 传参 — 把 db 和 task_manager 传给 handle_turn

**文件**: `backend/app/services/artist_service.py` (line 314-331)

```python
rt = ArtistRuntime(deps=deps)
runtime_result = await rt.handle_turn(
    session_id=session_id,
    prompt=prompt,
    artist_turn_id=artist_turn_id,
    messages=messages,
    system_prompt="",
    default_size=image_size,
    default_count=image_count,
    image_provider_id=image_provider_id,
    reference_images=reference_images,
    image_map=image_map,
    negative_prompt=negative_prompt,
    artist_pack_count=artist_pack_count,
    artist_model_mode=artist_model_mode,
    artist_anchor_first=artist_anchor_first,
    response_format_mode=response_format_mode,
    refine_mode=refine_mode,
    db=db,                    # 新增
    task_manager=task_manager, # 新增
)
```

### Step 8: 移除 `_execute_action` 方法

**文件**: `backend/app/core/artist/runtime.py` (line 211-298)

整个 `_execute_action` 方法删除。这是 Artist 直接生图的唯一路径，移除后 Artist 不可直接生图。

**同时移除相关 imports**:
- `from app.core.artist.artifacts import action_type_to_artifact_type, build_image_artifacts` — `build_image_artifacts` 不再需要（`_trace_to_artifacts` 用 `action_type_to_artifact_type` 但不用 `build_image_artifacts`）
- 注意：`action_type_to_artifact_type` 在 `_trace_to_artifacts` 中仍需要

### Step 9: 更新 ARTIST_TURN_SYSTEM — 添加多步示例

**文件**: `backend/app/core/artist/runtime.py` (line 7-32)

添加 iterative 和 radiate 的示例：

```
先画线稿再上色 → {"message":"先出线稿","actions":[{"type":"generate_anchor","prompt":"Architectural line drawing, modern building, clean lines, blueprint style","image_count":1},{"type":"refine_target","prompt":"Colorized version of the line drawing, realistic materials, glass and steel","image_count":1,"reference_images":["图0"]}],"next_phase":"refining"}

做一套4个表情包 → {"message":"来 做套表情","actions":[{"type":"generate_pack","prompt":"Set of 4 cute emoji stickers, various expressions","image_count":4,"reference_images":["图0"]}],"next_phase":"pack_ready"}
```

### Step 10: 更新 billing — ExecutionEngine 已内置 billing

**文件**: `backend/app/services/artist_service.py` (line 377-391)

当前 artist_service.py 在 orchestrate 后手动做 billing。ExecutionEngine.run_all() 已内置 billing（每步完成后 calc_cost + record_billing）。

**变更**: 移除 artist_orchestrate 中的手动 billing 循环，改为从 ExecutionTrace 提取 total_cost。

## 辐射策略（generate_pack）特殊处理

`generate_pack` 需要辐射策略，但当前 LLM 输出的 action 只有一个 `generate_pack`，没有 anchor + items 分步。

**方案**: 当 `infer_strategy` 返回 `radiate` 时，在 `build_plan_steps` 中自动拆解：
1. Step 0: anchor grid（1 张网格图，prompt 加 "grid arrangement" suffix）
2. Step 1..N: individual items（从 anchor crop + refine）

这需要 `plan_meta` 中包含 items 信息，StepContextResolver 的 crop_from_anchor 机制会自动处理。

```python
if action.type == "generate_pack" and strategy == "radiate":
    count = action.image_count or effective_pack_count
    # Split into: anchor (1 grid) + count individual items
    anchor_step = {
        "prompt": f"{action.prompt}, grid arrangement of {count} items, 2x2 layout",
        "image_count": 1,
        "description": "artist:generate_pack_anchor",
        "image_size": action.image_size or "",
        "metadata": {"artist_action_type": "generate_pack_anchor"},
    }
    steps.append(anchor_step)
    
    items = [{"label": f"item_{j}", "index": j} for j in range(count)]
    for j in range(count):
        item_step = {
            "prompt": f"{action.prompt}, item {j+1}",
            "image_count": 1,
            "description": f"artist:generate_pack_item_{j}",
            "image_size": action.image_size or "",
            "reference_step_indices": [0],  # reference the anchor
            "metadata": {
                "artist_action_type": "generate_pack_item",
                "crop_from_anchor": True,
                "crop_region": {"row": j // 2, "col": j % 2},
                "item_index": j,
                "items": items,
            },
        }
        steps.append(item_step)
```

## 不变的部分

- `handle_turn` 的 LLM 调用流程不变（PER → LLM → turn → actions 解析）
- `non_gen_actions` 处理不变（chat_only, ask_clarification, self_critique）
- `_update_state`, `_state_updates` 不变（状态更新逻辑）
- `_stream_deltas`, `_extract_message` 不变
- artist_service.py 的 PER/CON 组装、vision blocks、image_map 不变
- artist_service.py 的 billing 后处理、vision_review、feedback writeback 不变
- SSE 事件流不变（artist_turn_started → artist_reply_delta → ... → artist_turn_done）

## 验证计划

1. **LSP diagnostics**: 每个修改文件运行 `lsp_diagnostics` 确认无类型错误
2. **单元测试**: 验证 ArtistRuntimeDeps 没有 image_generate 字段
3. **单元测试**: 验证 infer_strategy() 对各种 action 组合返回正确策略
4. **E2E 测试**: 
   - Turn 1: "画一个现代建筑的线稿" → expect single strategy, 1 image (anchor)
   - Turn 2: "给线稿上色" → expect single strategy, 1 image, parent=Turn1
   - Turn 3: "画线稿然后上色" → expect iterative strategy, 2 images, step[1] references step[0]
   - Turn 4: "做一套4个表情包" → expect radiate strategy, 5 images (1 anchor + 4 items)
   - Turn 5: "参考上色的配色改一下漆画" → expect single, parent=Turn2
   - 所有父子关系验证: lineage tree API 返回正确的 parent-child 关系

## 依赖关系

Step 1 (Deps 变更) → Step 3 (新增函数) → Step 2 (handle_turn 修改) → Step 4 (_trace_to_artifacts) → Step 6 (handle_turn 签名) → Step 5 (artist_service 绑定) → Step 7 (传参) → Step 8 (移除 _execute_action) → Step 9 (prompt 更新) → Step 10 (billing 简化)

必须按顺序执行，不可并行。

## 风险

1. **ExecutionEngine billing 双重计费**: ExecutionEngine 内部做了 billing，artist_service 之前也做了。移除 artist_service 的手动 billing 后需确认不会遗漏。
2. **radiate 策略拆解**: 拆解 generate_pack 为 anchor+items 需要正确的 crop_from_anchor metadata，否则图片会出错。
3. **image_map → PlanningContext.reference_images 桥接**: image_map (图0→url) 解析后的 reference_images 需要正确传入 PlanningContext，否则 StepContextResolver 无法为后续 step 提供参考图。
4. **artist_image_ready SSE 事件**: 当前 `_execute_action` 在每张图生成后立即发 `artist_image_ready`。ExecutionEngine.run_all() 不发此事件。需要决定：是在 run_all 完成后批量发送，还是在 ExecutionEngine 中加入回调。