# Agent 意图编配 - 实现计划

> **For agentic workers:** Use executing-plans skill to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 引入 AgentIntent 层，让服务端在 Agent 执行前解析用户意图为结构化任务，确保多图需求（如三视图）产出正确数量的独立图片，并区分 final/intermediate images。

**Architecture:** 纯后端 Python 层改动。新增 `agent_intent_service.py`，修改 `generate_service.py` 和 `agent_service.py`。无新依赖，无接口变更，无前端改动。

**设计文档:** `docs/plans/2026-05-09-agent-intent-orchestration.md`

---

## Task 1: 新增 AgentIntent 核心数据类

**Files:** `backend/app/services/agent_intent_service.py`（新建）

**Steps:**
- [ ] 创建文件，导入 `from __future__ import annotations`、`from dataclasses import dataclass, field`、`import re`
- [ ] 定义 `AgentItem` dataclass: `id: str`, `label: str`, `prompt_hint: str`, `role: str = "final"`, `reference_urls: list[str] | None = None`
- [ ] 定义 `AgentIntent` dataclass: `task_type: str`, `expected_count: int`, `strategy: str = "direct"`, `items: list[AgentItem] = field(default_factory=list)`, `references: list[str] = field(default_factory=list)`, `requires_consistency: bool = False`, `user_goal: str = ""`

**Verification:**
- [ ] `python -c "from app.services.agent_intent_service import AgentItem, AgentIntent; print('OK')"` 无报错

**Commit:** `feat(intent): add AgentItem and AgentIntent data classes`

---

## Task 2: 实现意图解析函数 parse_agent_intent

**Files:** `backend/app/services/agent_intent_service.py`

**背景:** 规则按优先级匹配，先匹配的胜出。按设计文档中的优先级表（1-8），从高到低依次检测。

**Steps:**
- [ ] 实现 `parse_agent_intent(prompt: str, image_count: int = 1, context_messages: list[dict] | None = None, reference_labels: list[dict] | None = None) -> AgentIntent`
- [ ] 定义中英文关键词常量 + PROMPT_HINT_MAP 映射字典（设计文档中已定义）
- [ ] 规则 1（优先级最高）: 检测 "三视图" / "three views" + "正面/侧面/背面" / "front/side/back" → task_type=multi_item, expected_count=3, items=[front, side, back]
- [ ] 规则 2: 检测 "正面"+"侧面"+"背面" / "front"+"side"+"back" (同句中无 sheet/turnaround) → task_type=multi_item, expected_count=3
- [ ] 规则 3: 检测 "表情包" / "sticker pack" / "emoticon" + 分隔符列表 → task_type=multi_item, expected_count=N
- [ ] 规则 4: 检测 "先...再..." / "first...then..." → task_type=iterative
- [ ] 规则 5: 检测 "生成 N 张" / "N images" / "N 张" + 列举 → task_type=multi_item, expected_count=N, items 从分隔符提取
- [ ] 规则 6: 检测 "套图/一组/系列" / "set/series/collection" → task_type=radiate
- [ ] 规则 7: 检测 "同一提示词" / "variants" / (无列举但 image_count > 1) → task_type=single, expected_count=image_count
- [ ] 规则 8: 无匹配 → task_type=uncertain, expected_count=image_count or 1
- [ ] 对 multi_item，每个 item 的 `prompt_hint` 优先查 PROMPT_HINT_MAP，未命中时直接用原 label
- [ ] 从 `context_messages` 中提取 `image_urls`，填充 `intent.references`

**Verification:**
- [ ] `python -c "from app.services.agent_intent_service import parse_agent_intent; i=parse_agent_intent('继续生成三视图，正面，侧面，背面', 1); assert i.expected_count==3; assert i.items[0].label=='正面'; assert i.items[0].prompt_hint=='front view'"` 通过
- [ ] `python -c "from app.services.agent_intent_service import parse_agent_intent; i=parse_agent_intent('three views: front, side, back', 1); assert i.expected_count==3; assert i.items[0].label=='front'"` 通过
- [ ] `python -c "from app.services.agent_intent_service import parse_agent_intent; i=parse_agent_intent('生成一张三视图设定表', 1); assert i.task_type=='single'"` 通过 (无列举 → 规则7/8，不走规则1)
- [ ] `python -c "from app.services.agent_intent_service import parse_agent_intent; i=parse_agent_intent('先画草图再精修最后上色', 1); assert i.task_type=='iterative'"` 通过
- [ ] `python -c "from app.services.agent_intent_service import parse_agent_intent; i=parse_agent_intent('random text', 3); assert i.expected_count==3"` 通过 (规则7: image_count > 1 传导)

**Commit:** `feat(intent): implement parse_agent_intent with priority-ordered deterministic rules`

---

## Task 3: 实现参考图解析函数 resolve_context_references

**Files:** `backend/app/services/agent_intent_service.py`

**Background:** 用户 prompt 中的 `[图1]` 标签和 `context_messages` 中的 `image_urls` 需被解析为可传给生图 API 的 URL 列表。该函数注入到每个 item 的 `reference_urls`，不依赖 LLM 猜测。

**Steps:**
- [ ] 实现 `async def resolve_context_references(db: AsyncSession, session_id: str, prompt: str, context_messages: list[dict], reference_labels: list[dict]) -> list[str]`
- [ ] 从 prompt 中 regex 提取 `[图1]`, `[图2]` 等标签
- [ ] 通过 `reference_labels` 映射标签到 URL
- [ ] 从 `context_messages` 中提取 `image_urls` 字段
- [ ] 如果以上都为空，查询数据库：`session_id` 的最近 4 条 `message_type='image'` 的 assistant 消息，提取 `metadata.image_urls` 并展平
- [ ] 返回去重后的 URL 列表（保留顺序，http URL 和 data:base64 均可）

**Verification:**
- [ ] `python -c "from app.services.agent_intent_service import resolve_context_references"` 导入不报错
- [ ] 单元测试：`prompt='[图1: 图1] 参考', reference_labels=[{'label':'图1','url':'http://x.com/1.png'}]` → 返回 `['http://x.com/1.png']`
- [ ] 单元测试：`context_messages=[{'image_urls':['http://x.com/a.png']}]` → 返回 `['http://x.com/a.png']`

**Commit:** `feat(intent): add resolve_context_references with DB fallback for session images`

---

## Task 4: 修改 handle_agent_generate 接入意图层

**Files:** `backend/app/services/generate_service.py`

**上下文:** 在 `handle_agent_generate()` 函数中（约 line 738），保存用户消息后、进入 `run_agent_loop` 前插入意图解析和路由。

**Steps:**
- [ ] 顶部增加 import:
  ```python
  from app.services.agent_intent_service import parse_agent_intent, resolve_context_references, execute_multi_item_intent, validate_agent_result
  ```
- [ ] 在 line 745（保存用户消息后）插入意图解析:
  ```python
  intent = parse_agent_intent(
      prompt=prompt,
      image_count=data.image_count,
      context_messages=data.context_messages,
      reference_labels=data.reference_labels,
  )
  intent.references = await resolve_context_references(
      db=db, session_id=session_id,
      prompt=prompt,
      context_messages=data.context_messages,
      reference_labels=data.reference_labels,
  )
  # 每个 item 继承 references
  for item in intent.items:
      if not item.reference_urls:
          item.reference_urls = intent.references
  ```
- [ ] 在 line 794 后插入路由（在 `run_agent_loop` 调用前）:
  ```python
  # Intent routing - deterministic tasks bypass agent loop
  if intent.task_type == "multi_item":
      return await execute_multi_item_intent(
          db=db, session_id=session_id, intent=intent, data=data,
          task_manager=task_manager, llm_provider_id=llm_provider_id,
          image_provider_id=image_provider_id,
      )
  ```
- [ ] 保留 `uncertain` 等类型走 `run_agent_loop`
- [ ] 对非 multi_item 路径，将 intent 注入 system message:
  ```python
  if intent.task_type not in ("multi_item",):
      constraint = (
          f"\n## 本次任务约束\n"
          f"- task_type: {intent.task_type}\n"
          f"- expected_count: {intent.expected_count}\n"
          + ("" if not intent.items else f"- items: {json.dumps([{'label': i.label, 'hint': i.prompt_hint} for i in intent.items], ensure_ascii=False)}\n")
      )
      messages[0]["content"] += constraint
  ```
- [ ] 在 agent loop 完成后（line 907 附近），对 `uncertain` 路径增加校验:
  ```python
  # Validate agent result against intent
  if not validate_agent_result(intent, {"images": accumulated_images, "final_images": []}):
      logger.warning(f"Agent produced {len(accumulated_images)} images, expected {intent.expected_count}")
      final_output += f"\n\n(注意: 请求 {intent.expected_count} 张，实际生成 {len(accumulated_images)} 张)"
  ```

**Verification:**
- [ ] `python -m py_compile backend/app/services/generate_service.py` 无报错

**Commit:** `feat(intent): wire parse_agent_intent, routing, and result validation into handle_agent_generate`

---

## Task 5: 实现 Prompt 生成器 _generate_item_prompts

**Files:** `backend/app/services/agent_intent_service.py`

**背景:** 对多 item 任务，需要为每个 item 生成英文生图 prompt。为减少 LLM 调用次数，一次批量调用生成所有 item 的 prompt。

**Steps:**
- [ ] 实现 `async def _generate_item_prompts(items: list[AgentItem], intent: AgentIntent, llm_provider_id: str, api_key: str) -> list[str]`
- [ ] 从 `app.utils.llm_client import LLMClient`
- [ ] 构造批量请求 prompt:
  ```python
  system_msg = (
      "You are a text-to-image prompt engineer. "
      "For each item below, write ONE concise English prompt optimized for image generation. "
      "Each prompt should be independent and self-contained. Do NOT generate a single sheet/turnaround "
      "unless the goal explicitly says 'sheet' or 'turnaround'. "
      "Output a valid JSON array of strings, same length as input items. No markdown, no explanation."
  )
  user_msg = json.dumps({
      "goal": intent.user_goal,
      "items": [{"label": i.label, "hint": i.prompt_hint} for i in items],
      "output_format": "array of strings, one per item",
  }, ensure_ascii=False)
  ```
- [ ] 调用 `LLMClient.chat()` (非流式，单次同步等待): provider_id=llm_provider_id, api_key=api_key, messages=[system, user], model=从 provider 查询
- [ ] 解析返回的 JSON array，校验长度 == len(items)
- [ ] 解析失败时回退：每个 item 用 `f"{item.prompt_hint}, {intent.user_goal}"` 作为 fallback prompt
- [ ] 返回与 items 同长度的 prompt 列表

**Verification:**
- [ ] `python -m py_compile backend/app/services/agent_intent_service.py` 无报错
- [ ] `python -c "from app.services.agent_intent_service import _generate_item_prompts; print('loaded')"` 通过

**Commit:** `feat(intent): add _generate_item_prompts for batch LLM prompt generation`


## Task 6: 实现多 item 执行器 execute_multi_item_intent

**Files:** `backend/app/services/agent_intent_service.py`

**背景:** multi_item 任务的 items 之间无依赖关系，采用并发执行以最小化总耗时。

**Steps:**
- [ ] 实现 `async def execute_multi_item_intent(db: AsyncSession, session_id: str, intent: AgentIntent, data, task_manager, llm_provider_id: str, image_provider_id: str) -> dict`
- [ ] 从 `data` 获取 `image_size`；查询 llm_provider 获取 api_key 和 unit_price
- [ ] 调用 `_generate_item_prompts(intent.items, intent, llm_provider_id, api_key)` 获取所有 prompt
- [ ] 定义并发 task: `async def _generate_one(item, prompt, idx)`:
  ```python
  refs = item.reference_urls or intent.references
  tool = registry.get("generate_image")
  result = await tool.execute(
      prompt=prompt, count=1, reference_urls=refs,
      db=db, image_provider_id=image_provider_id, image_size=image_size,
  )
  urls = result.meta.get("image_urls", [])
  t_in = result.meta.get("tokens_in", 0)
  t_out = result.meta.get("tokens_out", 0)
  return {
      "item_id": item.id, "label": item.label, "url": urls[0] if urls else "",
      "status": "ok" if urls else "failed", "error": result.content if not urls else "",
      "tokens_in": t_in, "tokens_out": t_out,
  }
  ```
- [ ] `results = await asyncio.gather(*[_generate_one(item, prompt, i) for i, (item, prompt) in enumerate(zip(intent.items, prompts))], return_exceptions=True)`
- [ ] 分离成功的 final_images 和失败的
- [ ] SSE 广播每项结果: `task_manager.publish(session_id, {"type": "task_progress", "payload": {"type": "item_result", "item_id": ..., "status": ...}})`
- [ ] 返回与 `handle_agent_generate` 兼容的格式（含 `images`, `final_images`, `steps`, `cost` 等）
- [ ] 错误处理：单 item 失败不阻断其他 item

**Verification:**
- [ ] `python -m py_compile backend/app/services/agent_intent_service.py` 无报错

**Commit:** `feat(intent): implement execute_multi_item_intent with concurrent item generation`

---

## Task 7: 修改数据库持久化逻辑，区分 final/intermediate images

**Files:** `backend/app/services/generate_service.py`

**Steps:**
- [ ] 在 `handle_agent_generate` 中（约 line 826-830），增加判断：
  - `generate_image` 工具返回的 `image_urls` 如果是 `multi_item` 路径产生，标记为 `final_images`
  - 锚点图（`grid_images`）标记为 `intermediate_images`
- [ ] 修改 agent message metadata 保存（约 line 893-904），使用 `dataclasses.asdict(intent)` 序列化 intent:
  ```python
  from dataclasses import asdict

  intent_data = asdict(intent) if intent else None
  metadata={
      "steps": steps,
      "final_output": final_output,
      "images": accumulated_images,
      "final_images": final_images,
      "intermediate_images": intermediate_images,
      "intent": intent_data,
      "tokens_in": tokens_in,
      "tokens_out": tokens_out,
      "cost": cost_total,
      "cancelled": cancelled,
  }
  ```
- [ ] 保留 `"images"` 字段兼容前端现有展示

**Verification:**
- [ ] `python -m py_compile backend/app/services/generate_service.py` 无报错

**Commit:** `feat(intent): persist final/intermediate images, intent via asdict in agent messages`

---

## Task 8: 计费集成：execute_multi_item_intent 记录 billing

**Files:** `backend/app/services/agent_intent_service.py`

**背景:** `execute_multi_item_intent` 每次调用 `generate_image` 工具都没有 billing 记录，导致 agent intent 路径下的图像生成成本和 token 不追索。需对齐 `handle_agent_generate` 的 billing 逻辑。

**Steps:**
- [ ] import `from app.services.billing_service import calc_cost, record_billing` 和 `from sqlalchemy import select`、`ApiProvider`
- [ ] 在 `_generate_one` 内部，生成完成后查询 provider 信息并记录 billing:
  ```python
  # Billing record for each image generation
  from app.models.api_provider import ApiProvider
  img_provider = await db.execute(select(ApiProvider).where(ApiProvider.id == image_provider_id))
  img_prov = img_provider.scalar_one_or_none()
  if img_prov and (t_in or t_out):
      img_cost = calc_cost(img_prov, tokens_in=t_in, tokens_out=t_out, call_count=1)
      await record_billing(db, session_id=session_id, provider_id=img_prov.id,
          billing_type=img_prov.billing_type.value, tokens_in=t_in, tokens_out=t_out,
          cost=img_cost, currency=img_prov.currency,
          detail={"type": "image_gen", "agent": True, "intent": "multi_item", "item": item.label})
      cost_total += img_cost
  ```
- [ ] 汇总所有 item 的 cost 和 tokens，在返回值中体现

**Verification:**
- [ ] `python -m py_compile backend/app/services/agent_intent_service.py` 无报错
- [ ] 运行后检查 `billing_records` 表：multi_item 路径下每个 item 都有独立记录

**Commit:** `feat(intent): add billing records per item in execute_multi_item_intent`


## Task 9: 收紧 AGENT_SYSTEM_PROMPT 中的 count 指导

**Files:** `backend/app/services/agent_service.py`

**Steps:**
- [ ] 修改 line 87（generate_image 描述）增加 "仅用于同一 prompt 的随机变体":
  ```python
  # 当前:
  # - **generate_image**: 生成图片。参数：prompt(英文生图提示词)、count(生成数量1-4)、reference_urls(参考图URL，可选)。
  #
  # 改为:
  # - **generate_image**: 生成图片。参数：prompt(英文生图提示词)、count(生成数量1-4，仅用于同一 prompt 的随机变体)、reference_urls(参考图URL，可选)。
  ```
- [ ] 修改 line 101-107 工作规则:
  ```python
  # 当前:
  # - 同一 prompt 的少量批量变体可使用 generate_image(count=N)
  # - 若每张图的内容或风格不同，使用多次 generate_image(count=1)，每次给出不同 prompt
  #
  # 改为:
  # - 若每张图的内容或风格不同，使用多次 generate_image(count=1)，每次给出不同 prompt
  # - count 参数仅用于"同一 prompt 的 N 个随机变体"，不用于不同内容的任务
  # - 多内容任务（如三视图、多角色、多表情）由服务端自动解析，你必须为每个独立视角/角色/表情生成一张图
  # - 禁止将多个视角合并为一张 sheet/turnaround，除非用户明确要求"一张图里排版/设定表"
  ```

**Verification:**
- [ ] `python -m py_compile backend/app/services/agent_service.py` 无报错

**Commit:** `fix(prompt): tighten count semantics and forbid implicit sheet in AGENT_SYSTEM_PROMPT`

---

## Task 10: 修复 agent 模式下 generate_image 的参考图传递

**Files:** `backend/app/services/agent_service.py`

**背景:** 当 LLM 在 agent loop 中调用 `generate_image` 时，`reference_urls` 参数通常为空。需在 `run_agent_loop` 的执行层自动注入上下文参考图。

**Steps:**
- [ ] 在 `run_agent_loop` 中，处理 `generate_image` 工具调用前（约 line 289-301），增加参考图注入:
  ```python
  if fn_name == "generate_image" and not fn_args.get("reference_urls"):
      # Try to resolve context references from session history
      from app.services.agent_intent_service import resolve_context_references
      try:
          refs = await resolve_context_references(
              db=db, session_id=session_id,
              prompt="",  # prompt 已在上层保存，这里无需重复
              context_messages=[],
              reference_labels=[],
          )
          if refs:
              fn_args["reference_urls"] = refs[:4]  # 最多 4 张
              logger.debug(f"Injected {len(refs[:4])} context references into generate_image")
      except Exception as e:
          logger.debug(f"Could not resolve context references: {e}")
  ```
- [ ] 在 `generate_image.py` 的 `execute()` 中，增加调试 log:
  ```python
  logger.info(f"generate_image tool: reference_urls={'provided' if reference_urls else 'empty'}, count={count}")
  ```

**Verification:**
- [ ] `python -m py_compile backend/app/services/agent_service.py` 无报错
- [ ] `python -m py_compile backend/app/tools/generate_image.py` 无报错

**Commit:** `fix(agent): auto-inject session context images as reference_urls for generate_image tool calls`

---

## Task 11: 端到端验证

**Files:** 无（验证步骤）

**前置条件:**
- [ ] LLM provider 已配置且可用（需支持 chat completions）
- [ ] Image generation provider 已配置且可用（OpenAI 兼容 API）
- [ ] 后端已启动

**验证场景:**
- [ ] **三视图（中文）**: 输入「继续生成三视图，正面，侧面，背面」→ `final_images` 返回 3 个独立 item，labels=[正面, 侧面, 背面]，无 single sheet
- [ ] **三视图（英文）**: 输入「three views: front, side, back」→ same result
- [ ] **单图 sheet**: 输入「生成一张三视图设定表」→ task_type=single，走 agent loop 或单图路径，生成 1 张排版图
- [ ] **表情包**: 输入「表情包：开心，生气，惊讶」→ `final_images` 返回 3 张，labels=[开心, 生气, 惊讶]
- [ ] **不同风格猫**: 输入「画 3 张不同风格的猫」→ images 返回 3 张图
- [ ] **参考图传递**: 先任意生成 1 张图，再输入「[图1] 参考前张图生成正面」→ generate_image 的 `reference_urls` 不为空
- [ ] **metadata 检查**: 查询 exe 数据库，新 agent 消息 metadata 含 `intent`, `final_images`, `intermediate_images`
- [ ] **计费检查**: `billing_records` 表中 multi_item 路径每 item 有独立记录
- [ ] **错误恢复**: 模拟一个 item 失败，其他 item 不应受影响

**Verification:**
- [ ] 所有测试场景通过
- [ ] exe `test 04` 同类场景不再出现「3 张但不对应 3 个视角」问题

**Commit:** `test(intent): end-to-end verification of agent intent orchestration`

---

## 回滚方案

如果出现问题：
1. `handle_agent_generate` 中的 intent routing 可以临时注释掉，恢复原有 `run_agent_loop` 行为
2. metadata 的 `final_images`/`intermediate_images` 是新增字段，不影响前端现有解析
3. AGENT_SYSTEM_PROMPT 修改可以 revert，不影响功能正确性
