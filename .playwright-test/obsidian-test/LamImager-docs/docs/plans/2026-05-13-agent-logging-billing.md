# 全链路日志与计费补全方案

> **For agentic workers:** Use executing-plans to implement this plan task-by-task.

**Goal:** agent graph 每个 LLM 节点（intent/planner/prompt_builder/critic/context）记录入参内容、出参内容、token 用量、调用计费；message 存盘包含完整决策链（intent/plan/critic/decision/node trace）；回环迭代可追踪。

**Architecture:** 三层改造 — (1) 共用 `record_llm_call()` 封装 token 提取+日志+计费；(2) 各节点接入；(3) `_run_agent_mode_graph` 收尾将 state 中的完整决策数据写入 message metadata。

---

## Task L1: 创建 LLM 调用记录封装

**Files:**
- 新增 `backend/app/services/llm_call_logger.py`

**Steps:**
- [ ] 1. 新建 `llm_call_logger.py`，提供 `async def record_llm_call()`：
  ```python
  async def record_llm_call(
      db: AsyncSession,
      session_id: str,
      node_name: str,           # "intent" | "planner" | "prompt_builder" | "critic" | "context"
      provider_id: str,
      system_prompt: str,
      user_content: str | list, # 多模态时是 list
      response: dict,           # LLMClient.chat() 原始返回
      billing_type: str = "agent",
      metadata: dict | None = None,
  ) -> dict:
      """
      提取 response 中的 token 用量，写日志，记计费，返回 tokens 摘要。
      返回: {"tokens_in": int, "tokens_out": int, "cost": float}
      """
  ```
  
  实现内容：
  - `tokens_in = response["usage"]["prompt_tokens"]`
  - `tokens_out = response["usage"]["completion_tokens"]`
  - 记录 billing: `detail.type = billing_type, detail.node = node_name, detail.metadata = metadata`
  - logger.info: `f"[{node_name}] tokens_in={ti} tokens_out={to} prompt_snip={system[:80]}... user_snip={user[:80]}... response_snip={text[:200]}"`
  - 返回 token 摘要

- [ ] 2. 同时导出 `def log_node_decision(node_name: str, decision: dict)`:
  ```python
  def log_node_decision(node_name: str, decision: dict):
      logger.info(f"[{node_name}] decision: {json.dumps(decision, ensure_ascii=False)[:500]}")
  ```
- [ ] 3. 导出 `def extract_tokens(response: dict) -> tuple[int, int]` 独立函数供不记费场景使用。

**Verification:**
- [ ] `py -3.14 -c "from app.services.llm_call_logger import record_llm_call; print('OK')"` 无导入错误

**Commit:** `feat: shared LLM call logger with auto token extraction + billing + content logging`

---

## Task L2: 各 LLM 节点接入 record_llm_call

**Files:**
- 修改 `backend/app/core/agent/nodes/intent_node.py`
- 修改 `backend/app/core/agent/nodes/planner_node.py`
- 修改 `backend/app/core/agent/nodes/prompt_builder_node.py`
- 修改 `backend/app/core/agent/nodes/critic_node.py`
- 修改 `backend/app/core/agent/nodes/context_node.py`

**Steps:**
- [ ] 1. intent_node：LLM 调用后调用 `record_llm_call(db, session_id, "intent", ...)`，将 tokens 返回写入 state `total_tokens_in/out`。
- [ ] 2. planner_node：无论成功还是 2 次重试，每次 LLM 调用后记费。fallback 路径不记费（无 LLM 调用）。tokens 累加到 state。
- [ ] 3. prompt_builder_node：per-step 循环中，每个 LLM 调用记费。tokens 累加。
- [ ] 4. critic_node：per-artifact 循环中，每个 LLM 调用记费。非多模态回退不记费。
- [ ] 5. context_node：`cache_image_descriptions()` 中每次 vision LLM 调用记费（`billing_type="vision"`）。tokens 累加到 state。

**关键改动模式（每个节点相同）：**
```python
# Before: just call LLM
response = await client.chat(messages, temperature=0.7)

# After: call + record
response = await client.chat(messages, temperature=0.7)
summary = await record_llm_call(
    db=db, session_id=session_id, node_name="planner",
    provider_id=llm_provider_id,
    system_prompt=system_prompt, user_content=user_msg,
    response=response, billing_type="agent",
    metadata={"task_type": task_type, "attempt": attempt + 1},
)
state_inc["total_tokens_in"] += summary["tokens_in"]
state_inc["total_tokens_out"] += summary["tokens_out"]
```

**Verification:**
- [ ] 每个节点文件中存在 `record_llm_call` 调用
- [ ] billing 记录中能看到 `detail.node` 字段区分节点

**Commit:** `feat: wire all LLM graph nodes to shared billing + content logging`

---

## Task L3: Message 元数据补全 + Node Trace

**Files:**
- 修改 `backend/app/core/agent/state.py`
- 修改 `backend/app/services/generate_service.py`

**Steps:**
- [ ] 1. 在 `AgentState` TypedDict 中新增字段：
  ```python
  "node_trace": list[dict],   # [{node, tokens_in, tokens_out, decision_summary}]
  ```
- [ ] 2. 各节点执行完成后追加 trace 条目到 state，例如 planner_node：
  ```python
  trace_entry = {
      "node": "planner",
      "tokens_in": tokens_used,
      "tokens_out": tokens_used_out,
      "decision": f"strategy={strategy}, steps={len(plan_steps)}",
  }
  return {..., "node_trace": (state.get("node_trace") or []) + [trace_entry]}
  ```
- [ ] 3. 修改 `_run_agent_mode_graph()` 最终存盘 message metadata，字段从 `result_state` 中完整提取：
  ```python
  metadata={
      "steps": result_state.get("execution_plan", {}).get("steps", []),
      "strategy": result_state.get("execution_plan", {}).get("strategy", ""),
      "plan_meta": result_state.get("execution_plan", {}).get("plan_meta", {}),
      "intent": result_state.get("intent", {}),              # ← 用真实的
      "critic_results": result_state.get("critic_results", []),
      "decision_result": result_state.get("decision_result", ""),
      "retry_count": result_state.get("retry_count", 0),
      "node_trace": result_state.get("node_trace", []),
      "final_output": final_output,
      "images": all_urls,
      "final_images": all_urls,
      "intermediate_images": [],
      "tokens_in": result_state.get("total_tokens_in", 0),
      "tokens_out": result_state.get("total_tokens_out", 0),
      "cost": result_state.get("cost", 0.0),
      "cancelled": False,
      "task_type": result_state.get("intent", {}).get("task_type", ""),
      "strategy": result_state.get("intent", {}).get("strategy", ""),
  }
  ```
- [ ] 4. context_enrichment 的 image_descriptions 也写入 metadata 供分析：
  - `"image_descriptions": planning_context.get("image_descriptions", {})`
- [ ] 5. 修复 `_execute_direct` 回退路径中 cost 硬编码 0.0 的问题——从实际计费记录中读取。

**Verification:**
- [ ] 生成一张图后，查询 `GET /api/sessions/{id}/messages`，agent 消息的 metadata 包含 `intent`、`execution_plan`、`critic_results`、`node_trace`
- [ ] metadata.intent 的 `decision_trace.source` 为 `"llm_sole_classifier"`（确认是 graph 产出的真实 intent，而非骨架）

**Commit:** `feat: complete message metadata with intent/plan/critic/decision/node_trace`

---

## Task L4: 搜索增强计费

**Files:**
- 修改 `backend/app/services/generate_service.py`

**Steps:**
- [ ] 1. `_enhance_with_search()` 中，每次 web_search 或 image_search 调用后调用 `record_llm_call()`（或直接用 `record_billing()`）。
- [ ] 2. `billing_type = "tool"`, `detail = {"type": "tool", "tool": "web_search" | "image_search"}`。
- [ ] 3. 搜索结果也写入 message metadata: `"search_context": search_context[:500]`（截断存摘要）。

**Verification:**
- [ ] 带搜索意图的指令执行后，billing 表中出现 `detail.tool` 记录

**Commit:** `feat: billing for search enhancement API calls`

---

## 变更总结

| 文件 | 操作 | 变更量 |
|------|------|--------|
| `services/llm_call_logger.py` | **新建** | +60 |
| `nodes/intent_node.py` | 接入 record_llm_call | +10 |
| `nodes/planner_node.py` | 接入 record_llm_call + node_trace | +15 |
| `nodes/prompt_builder_node.py` | 接入 record_llm_call + node_trace | +15 |
| `nodes/critic_node.py` | 接入 record_llm_call + node_trace | +10 |
| `nodes/context_node.py` | 接入 record_llm_call + node_trace | +10 |
| `nodes/skill_matcher_node.py` | node_trace 条目 | +5 |
| `nodes/skill_node.py` | node_trace 条目 | +5 |
| `nodes/decision_node.py` | node_trace 条目 | +5 |
| `core/agent/state.py` | 新增 node_trace 字段 | +2 |
| `services/generate_service.py` | metadata 补全 + 搜索计费 | +30 |

**净变化：** +167 行。修复 7 个计费缺口 + 1 个 metadata 残缺 + 无 node 追踪问题。

---

## 完成后可分析的数据

| 数据 | 来源 | 用途 |
|------|------|------|
| 每次 LLM 调用的入参/出参/耗时 | `record_llm_call` 日志 | 排查规划质量，发现 prompt 偏差 |
| 每个节点的 token 用量和费用 | billing 表 `detail.node` | 成本归因，哪个节点最费钱 |
| 完整 intent 决策链 | message.metadata.intent | 验证 LLM 分类准确率 |
| 完整 execution_plan | message.metadata | 验证 planner 产出合理性 |
| per-artifact 评分和问题 | message.metadata.critic_results | 验证 critic 准确性 |
| retry 次数和原因 | message.metadata.retry_count + decision_result | 验证回环有效性 |
| node 执行顺序和决策摘要 | message.metadata.node_trace | 重建执行时间线 |
| 搜索增强用了什么 | message.metadata.search_context | 验证搜索相关性 |
| context 图片描述 | message.metadata.image_descriptions | 验证视觉分析准确性 |
