# Agent 流程 Bug 修复计划

> **For agentic workers:** Use executing-plans skill to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 agent 执行流程中发现的 5 个 bug，保证多轮工具调用正确、计费完整、错误处理健壮。

**Architecture:** 所有修复均在后端 Python 层，无新依赖，无接口变更。

**Tech Stack:** Python / FastAPI / SQLAlchemy async

---

## Task 1: 修复 tool_calls arguments 格式错误（最高优先）

**Files:** `backend/app/utils/llm_client.py`

**背景:** `chat_stream_with_tools` 将 `arguments` 解析为 dict（line 193），但 OpenAI API 规范要求 `assistant` 消息中 `tool_calls[].function.arguments` 必须是 JSON 字符串。当前代码把 dict 追加进 `working_messages`，多轮工具调用时下一轮 LLM 调用收到格式错误的历史消息。

**Steps:**
- [ ] 在 `chat_stream_with_tools` 的 `resolved` 构建处（line 189-195），保持 `arguments` 为原始 JSON 字符串，不做 `json.loads`：
  ```python
  resolved.append({
      "id": tc["id"],
      "function": {
          "name": tc["function"]["name"],
          "arguments": args_str,   # 保持字符串，不解析为 dict
      },
  })
  ```
- [ ] `agent_service.py` 中 `_parse_fn_args` 已经处理字符串/dict 两种情况，无需改动

**Verification:**
- [ ] `python -m py_compile backend/app/utils/llm_client.py` 无报错
- [ ] `resolved[].function.arguments` 类型为 `str`

**Commit:** `fix(llm_client): keep tool_calls arguments as JSON string for OpenAI spec compliance`

---

## Task 2: 修复 generate_image 工具路径计费缺失

**Files:** `backend/app/tools/generate_image.py`

**背景:** 工具调用 `generate_images_core` 后，`tokens_in/tokens_out` 被 `_` 丢弃，图像生成成本完全不被记录。

**Steps:**
- [ ] `execute()` 中接收完整返回值：
  ```python
  urls, tokens_in, tokens_out = await generate_images_core(...)
  ```
- [ ] 在返回 `ToolResult` 前，将计费信息写入 meta，由 `handle_agent_generate` 的调用方处理：
  ```python
  return ToolResult(
      content=f"已生成 {len(urls)} 张图片",
      meta={"image_urls": urls, "prompt": prompt, "count": count,
            "tokens_in": tokens_in, "tokens_out": tokens_out},
  )
  ```
- [ ] `_generate_grid` 同样接收并透传：
  ```python
  urls, tokens_in, tokens_out = await generate_images_core(...)
  # ...
  return ToolResult(
      content=...,
      meta={..., "tokens_in": tokens_in, "tokens_out": tokens_out},
  )
  ```
- [ ] `handle_agent_generate` 中处理 `generate_image` tool_result 时，读取 meta 中的 tokens 并调用 `record_billing`：
  在 `generate_service.py` line 803-810 的 `generate_image` 处理块中，追加：
  ```python
  t_in = event.meta.get("tokens_in", 0)
  t_out = event.meta.get("tokens_out", 0)
  if (t_in or t_out) and image_provider_id:
      img_provider = await db.execute(select(ApiProvider).where(ApiProvider.id == image_provider_id))
      img_prov = img_provider.scalar_one_or_none()
      if img_prov:
          img_cost = calc_cost(img_prov, tokens_in=t_in, tokens_out=t_out, call_count=len(urls))
          await record_billing(db, session_id=session_id, provider_id=img_prov.id,
              billing_type=img_prov.billing_type.value, tokens_in=t_in, tokens_out=t_out,
              cost=img_cost, currency=img_prov.currency,
              detail={"type": "image_gen", "agent": True, "image_count": len(urls)})
          cost_total += img_cost
  ```
- [ ] `handle_agent_generate` 需要在函数开头解析 `image_provider_id`（复用已有的 `_get_default_provider` 逻辑）

**Verification:**
- [ ] `python -m py_compile backend/app/tools/generate_image.py` 无报错
- [ ] `python -m py_compile backend/app/services/generate_service.py` 无报错
- [ ] `generate_image` 工具 meta 包含 `tokens_in`/`tokens_out` 字段

**Commit:** `fix(agent): record billing for generate_image tool calls`

---

## Task 3: 修复 error 事件时孤立用户消息

**Files:** `backend/app/services/generate_service.py`

**背景:** `handle_agent_generate` 遇到 `error` 事件直接 `return`，但用户消息已写入 session，没有对应的 agent 回复消息，UI 出现孤立消息。

**Steps:**
- [ ] 将 `line 789-792` 的 error 处理改为：不直接 return，而是 break 出循环，让后续的 `add_system_message` 统一写入错误消息：
  ```python
  elif event.type == "error":
      task_manager.update_task(session_id, TaskStatus.ERROR, message=event.error)
      final_output = f"Agent 执行失败: {event.error}"
      break
  ```
- [ ] 循环结束后的 `add_system_message` 已有 `cancel_label` 逻辑，error 情况下 `final_output` 已包含错误信息，会被正常写入

**Verification:**
- [ ] `python -m py_compile backend/app/services/generate_service.py` 无报错
- [ ] error 路径下 session 中有且仅有一条用户消息 + 一条 agent 错误消息

**Commit:** `fix(agent): write agent error message to session instead of early return`

---

## Task 4: 修复 Tier 2 非 ImageGenError 异常不降级到 Tier 3

**Files:** `backend/app/services/generate_service.py`

**背景:** `generate_images_core` 中 Tier 2（`client.edit()`）只捕获 `ImageGenError`，网络错误等其他异常会向上冒泡，跳过 Tier 3。

**Steps:**
- [ ] 将 Tier 2 的 except 改为捕获所有异常：
  ```python
  except Exception as e:
      logger.warning(f"Image edit not supported or failed: {e}")
  ```

**Verification:**
- [ ] `python -m py_compile backend/app/services/generate_service.py` 无报错
- [ ] Tier 2 任何异常都会继续执行 `if not all_image_urls:` 的 Tier 3 判断

**Commit:** `fix(generate): catch all exceptions in Tier 2 to allow Tier 3 fallback`

---

## Task 5: 修复 round_idx 在 max_rounds=0 时未定义

**Files:** `backend/app/services/agent_service.py`

**背景:** `line 322` 使用 `round_idx`，但若 `max_rounds=0` 循环从不执行，`round_idx` 未定义会抛 `NameError`。

**Steps:**
- [ ] 在循环前初始化：
  ```python
  round_idx = -1
  for round_idx in range(max_rounds):
      ...
  cost = calc_cost(..., call_count=max(round_idx + 1, 1))
  ```

**Verification:**
- [ ] `python -m py_compile backend/app/services/agent_service.py` 无报错
- [ ] `round_idx` 初始值 `-1`，`max(round_idx + 1, 1)` = `max(0, 1)` = `1`，计费不会出错

**Commit:** `fix(agent): initialize round_idx to prevent NameError when max_rounds=0`

---

## 执行顺序

Tasks 1、3、4、5 相互独立，可并行。Task 2 依赖对 `generate_images_core` 返回值的理解，建议最后执行。

```
Tasks 1, 3, 4, 5  — 并行
Task 2            — 最后（涉及两个文件的协调改动）
```
