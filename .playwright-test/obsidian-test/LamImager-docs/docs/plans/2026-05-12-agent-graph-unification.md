# Agent Graph 统一方案实施计划

> **For agentic workers:** Use executing-plans or subagent-driven-development to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 将 agent 模式统一到 LangGraph 全链路 — LLM 全权决策（去掉正则意图解析），修复数据流断裂，启用 critic/decision 回环，注入 LLM 能力感知层，移除旧双路径冗余。

**Architecture:** 单一执行路径 handle_agent_generate → _run_agent_mode_graph → 8节点 graph，每个 LLM 节点都能感知系统能力，decision 节点根据评分决定 pass/retry_prompt/retry_step/replan，回退节点读取 critic 反馈闭环优化。

**Tech Stack:** Python 3.14+, LangGraph >=1.1.10, FastAPI, SQLAlchemy async

---

## 审计发现的所有问题

### 致命 (Blocker)
| # | 节点 | 问题 |
|---|------|------|
| 7 | executor | context_enrichment_node 的 to_dict() 不含 image_provider_id，executor 构造 PlanningContext 时该字段为 None，所有策略执行崩溃 |
| 1 | executor | RadiateExecutor 读 plan.plan_meta.items/style/theme，planner_node 不产出这些字段，radiate 策略必然失败 |

### 高优先级
| # | 节点 | 问题 |
|---|------|------|
| 4 | planner | intent_node 解析的 items（如 [正面/侧面/背面]）和 references（"上一张"指向的具体 URL）未传给 planner_node |
| 8 | planner/prompt_builder | context_enrichment_node 调用 vision LLM 生成的 image_descriptions 不被下游节点使用，白白花 token |
| 10 | planner | search_context（搜索结果）在 state 中已存在，planner_node 不读，增强搜索白做 |
| 2 | prompt_builder | decision 判 retry_prompt 后回路到 prompt_builder，但不读取 critic_results，等于没优化 |
| 3 | planner | decision 判 replan 后回路到 planner，但不读取 critic_results，大概率产出相同计划 |

### 中优先级
| # | 节点 | 问题 |
|---|------|------|
| 5 | planner | planner prompt 对所有 4 种策略用同一个通用模板，旧路径有 3 个专门 prompt，规划质量下降 |
| - | 全部 LLM 节点 | 所有 LLM 节点都不知道系统实际能力（策略执行机制、model 限制、可用资源），规划出的方案可能不可执行 |

### 低优先级
| # | 节点 | 问题 |
|---|------|------|
| 6 | critic | 需要多模态 LLM，否则静默回退到默认分 7.0。在 Settings 提示用户 |
| 9 | context | token_budget 计算后不用于截断，不传给 planner |

---

## 节点数据流设计

每个节点需要注入的信息：

`
intent_node       ← 策略执行机制说明 + 可用资源概况
planner_node      ← 策略执行机制说明 + 可用资源详情 + intent.items/references
                    + context image_descriptions + search_context + skill constraints
                    + token_budget（剩余 token 上限）
prompt_builder    ← model 能力/限制 + context image_descriptions + skill prompt_bias
                    + critic feedback (on retry)
critic_node       ← 评分维度说明 + 多模态能力检查
executor_node     ← image_provider_id (从 state 顶层显式注入到 PlanningContext)
context_enrichment ← token_budget 截断执行（砍 search → history → auto_context）
`

---

## Task 1: 纯 LLM 意图分类 + 能力感知提示词

**Files:**
- 新增 ackend/app/core/agent/nodes/intent_node.py
- 修改 ackend/app/services/agent_intent_service.py
- 新增 ackend/app/core/agent/capability_prompts.py

**Steps:**
- [ ] 1.1 新建 capability_prompts.py — 定义 STRATEGY_EXECUTION_MECHANISM 和 IMAGE_SYSTEM_CONSTRAINTS 两个常量，描述四种策略的实际执行机制（single=单调用N张、parallel=并发独立prompt、iterative=顺序上步参考下步、radiate=锚点图→裁剪→逐项扩展）和系统约束（不能修图只能生图、跨图角色一致性无保证、img2img 只提供风格指导不保留精确内容）。
- [ ] 1.2 删除 gent_intent_service.py 中所有正则代码：parse_agent_intent()、_count_n_images、_has_different_style_keyword、_make_intent、_extract_item_labels、HYBRID_CONFIDENCE_THRESHOLD、4 个优先级规则代码块。删除 hybrid_parse_intent()、_pick_best_intent()。删除死代码 execute_multi_independent()、_generate_item_prompts()、_generate_iterative_steps()、_generate_radiate_params()、_extract_style_from_text()。重命名 _classify_intent_with_llm → classify_intent_with_llm。保留 AgentIntent、AgentItem、STRATEGY_MAP、TASK_TYPE_LABELS、PROMPT_HINT_MAP、resolve_context_references()、validate_agent_result()、has_search_intent()、_build_multimodal_user_content()、_extract_context_image_urls()（generate_service.py 仍引用，等 Task 5 统一清理）。
- [ ] 1.3 新建 
odes/intent_node.py — async def intent_node(state, config) 函数。system prompt 拼接 STRATEGY_EXECUTION_MECHANISM + IMAGE_SYSTEM_CONSTRAINTS + 分类任务说明（含决策规则：不同风格→multi_independent、同角色多图→radiate、先X再Y→iterative、基于上一张改一下→single、默认→single）。LLM 调用作分类，解析返回 {task_type, expected_count, confidence, items, references, reason}。failback 返回 single。

**Verification:**
- [ ] py -3.14 -c "from app.core.agent.nodes.intent_node import intent_node; print('OK')"
- [ ] py -3.14 -c "from app.core.agent.capability_prompts import STRATEGY_EXECUTION_MECHANISM; print('OK')"

**Commit:** eat: pure LLM intent classification with capability-aware prompts, remove all regex rules

---

## Task 2: 修复 Graph 数据流断裂

**Files:**
- 修改 ackend/app/core/agent/graph.py（executor_node + _after_executor）
- 修改 ackend/app/core/agent/nodes/planner_node.py
- 修改 ackend/app/core/agent/nodes/prompt_builder_node.py
- 修改 ackend/app/core/agent/nodes/context_node.py（token_budget 截断）
- 修改 ackend/app/services/executors/radiate.py
- 修改 ackend/app/schemas/planning.py

**Steps:**
- [ ] 2.1 修复 Issue 7（executor 收不到 image_provider_id）：在 executor_node 中构造 PlanningContext 后，显式注入 context.image_provider_id = state.get("image_provider_id", "") or None; context.llm_provider_id = state.get("llm_provider_id", "") or None; context.session_id = state.get("session_id", "")。
- [ ] 2.2 修复 Issue 4（intent items/references 丢失）：修改 planner_node 的 LLM user_msg，增加 "items": intent.get("items", []) 和 "references": intent.get("references", [])。
- [ ] 2.3 修复 Issue 8（image_descriptions 浪费）：planner_node 从 state.planning_context.image_descriptions 读取并注入 user_msg；prompt_builder_node 同样注入 image_descriptions 到优化指令。
- [ ] 2.4 修复 Issue 1（RadiateExecutor plan_meta 不兼容）：RadiateExecutor.execute() 在 plan_meta.items 为空时从 plan.steps 中提取 items（label=step.description, prompt=step.prompt）。注意：planner prompt 中 radiate 的 plan_meta 输出要求由 Task 3.1 的 PLANNER_STRATEGY_GUIDE 统一处理，此处不修改 planner prompt。
- [ ] 2.5 修正 _after_executor 的 critic_mode 默认值：删除硬编码 critic_mode = "off"，改为从 state 读取（默认 "on"）。同步修改 schemas/planning.py 中 PlanningContext 的 critic_mode 默认值为 "on"。
- [ ] 2.6 更新 graph.py — 删除本地 sync def intent_node() 定义（lines 43-101），改为 rom app.core.agent.nodes.intent_node import intent_node。同时清理 graph.py 中不再需要的 import（hybrid_parse_intent）。
- [ ] 2.7 修复 Issue 9（token_budget 投入使用）：context_enrichment_node 在计算 token_budget 后，按优先级截断低价值内容——超预算时依次砍 search_context→非钉选 history→auto_context。钉选图和用户上传参考图不可截断。截断后的实际内容写入 state，让 downstream 节点拿到的是已截断版本。
- [ ] 2.8 修复 Issue 10（search_context 传递到 planner）：planner_node 的 LLM user_msg 增加 "search_context": state.get("search_context", "")。搜索结果作为补充设计参考注入，但不覆盖用户原始意图。

**Verification:**
- [ ] 确认 executor_node 中 context.image_provider_id 被正确设置
- [ ] 确认 planner_node 的 user_data 包含 items、references、context_image_descriptions、search_context
- [ ] 确认 context_enrichment_node 超 token_budget 硬顶 6000 时执行截断
- [ ] 确认 _after_executor 默认返回 "critic" 而非 END
- [ ] py -3.14 -c "from app.core.agent.graph import build_agent_mode_graph; g = build_agent_mode_graph(); print(list(g.nodes.keys()))" 输出 8 节点

**Commit:** ix: repair graph data flow — image_provider_id, intent items, image_descriptions, radiate plan_meta, token_budget truncation, search_context, critic_mode

---

## Task 3: LLM 能力感知提示词层

**Files:**
- 修改 ackend/app/core/agent/capability_prompts.py
- 修改 ackend/app/core/agent/nodes/planner_node.py
- 修改 ackend/app/core/agent/nodes/prompt_builder_node.py
- 修改 ackend/app/core/agent/nodes/critic_node.py

**Steps:**
- [ ] 3.1 扩展 capability_prompts.py，新增：PLANNER_STRATEGY_GUIDE（每种策略的规划规则，含 radiate plan_meta 输出要求）、IMAGE_PROVIDER_CAPABILITIES（{model_id}/{supported_sizes} 模板）、PROMPT_BUILDER_GUIDE（优化规则）、build_planner_system_prompt() 函数（组装 planner 完整 system prompt）。
- [ ] 3.2 改造 planner_node 使用 uild_planner_system_prompt() 替换旧的 _build_planner_prompt()。
- [ ] 3.3 改造 prompt_builder_node — system prompt 合并 PROMPT_BUILDER_GUIDE + IMAGE_PROVIDER_CAPABILITIES。
- [ ] 3.4 改造 critic_node — system prompt 增加评分维度说明。新增多模态 LLM 可用性检查（从 provider.model_id 判断，非多模态时 log warning + 返回默认分）。

**Verification:**
- [ ] py -3.14 -c "from app.core.agent.capability_prompts import build_planner_system_prompt; print('OK')"
- [ ] 确认 planner_node 的 system prompt 包含策略执行机制、provider 能力、约束

**Commit:** eat: inject LLM capability awareness into all LLM node prompts

---

## Task 4: 启用 critic → decision 回环（含反馈注入）

**Files:**
- 修改 ackend/app/core/agent/nodes/prompt_builder_node.py
- 修改 ackend/app/core/agent/nodes/planner_node.py
- 修改 ackend/app/core/agent/nodes/decision_node.py
- 修改 ackend/app/core/agent/nodes/critic_node.py

**Steps:**
- [ ] 4.1 修复 Issue 2（prompt_builder retry 盲）：在 prompt_builder_node 中读取 state.critic_results 和 state.retry_step_index，找到对应 step 的 critic issues，注入到优化指令 "Previous attempt issues: {issues}. Fix these in the new prompt."。
- [ ] 4.2 修复 Issue 3（planner replan 盲）：在 planner_node 中读取 state.critic_results，如果有则注入 user_data.previous_issues、user_data.previous_avg_score、user_data.replan_reason。
- [ ] 4.3 Step tracking 与 retry 目标确定：executor_node 正常完成时设 
etry_step_index = -1。decision_node 在判 retry_step/retry_prompt 时，从 critic_results 中找出最低分 artifact 对应的 step index，写入 state.retry_step_index。多 artifact 关联同一步的情况下取该步的平均分。prompt_builder_node 收到 retry_prompt 时通过 retry_step_index 定位到具体 step 的 issues。

**Verification:**
- [ ] 确认 prompt_builder_node 在有 critic_results 时注入 issues 到优化指令
- [ ] 确认 planner_node 在有 critic_results 时注入到 replan user_msg
- [ ] 确认 decision_node 在判 retry_step/retry_prompt 时输出 retry_step_index

**Commit:** eat: enable critic-decision retry loop with feedback injection

---

## Task 5: 生成服务统一到 Graph 路径

**Files:**
- 修改 ackend/app/services/generate_service.py

**Steps:**
- [ ] 5.1 移除 handle_agent_generate() 中的 hybrid_parse_intent() 调用。替换为骨架 intent（graph 的 intent_node 会覆盖），只保留 resolve_context_references + reference_images/labels 赋值。
- [ ] 5.2 移除 feature flag 分支 — 始终走 _run_agent_mode_graph()。graph build 失败时调用新增的 _execute_direct() 最小回退。
- [ ] 5.3 新增 _execute_direct() — 直接调用 _execute_single()，不走 plan/build。
- [ ] 5.4 删除死代码函数：_build_execution_plan()、_execute_radiate()、_get_use_langgraph_setting()。
- [ ] 5.5 清理 import：删除 parse_agent_intent、hybrid_parse_intent、_generate_iterative_steps、_generate_radiate_params、_extract_style_from_text、_extract_context_image_urls（现在可以安全删除，generate_service.py 不再引用）。

**Verification:**
- [ ] py -3.14 -c "from app.services.generate_service import handle_agent_generate; print('OK')"
- [ ] 确认 handle_agent_generate 中无 hybrid_parse_intent、_build_execution_plan、_get_use_langgraph_setting 调用

**Commit:** 
efactor: unify agent generation to graph-only path, remove old code

---

## Task 6: 死角清理

**Files:**
- 删除 ackend/app/services/plan_executor.py
- 修改 ackend/app/services/agent_intent_service.py（最终清理 _extract_context_image_urls）

**Steps:**
- [ ] 6.1 删除 plan_executor.py（零引用死代码）。
- [ ] 6.2 确认 generate_service.py 和 agent_intent_service.py 中无残留死 import。此时可安全删除 agent_intent_service.py 中的 _extract_context_image_urls。

**Verification:**
- [ ] py -3.14 -c "from app.main import app; print('App loaded OK')" 无 ImportError

**Commit:** chore: remove dead code (plan_executor.py, unused imports)

---

## Task 7: 集成验证

**Files:** 无需修改代码

**Steps:**
- [ ] 7.1 cd backend; py -3.14 -c "from app.main import app; print('App loaded OK')"
- [ ] 7.2 py -3.14 -c "from app.core.agent.graph import build_agent_mode_graph; g = build_agent_mode_graph(); print('Nodes:', list(g.nodes.keys()))" 预期 8 节点
- [ ] 7.3 py -3.14 -c "from app.core.agent.capability_prompts import build_planner_system_prompt; print(build_planner_system_prompt('single', ['single'], '1024x1024', '', 'test-model', '1024x1024')[:100])"
- [ ] 7.4 更新 docs/progress-log.md
- [ ] 7.5 确认 uild_agent_graph()（sidebar assistant 2-node graph）未被本次修改影响——其使用的 agent_node/tools_node/_should_continue 均未改动

**Commit:** 	est: verify unified graph integration

---

## 变更总结

| 文件 | 操作 | 变更量 |
|------|------|--------|
| gent_intent_service.py | 删 ~400 行正则代码，重命名 1 函数，删 7 个死函数 | ~-550 |
| 
odes/intent_node.py | **新建** ~130 行纯 LLM 意图分类 | +130 |
| capability_prompts.py | **新建** ~150 行能力感知提示词 | +150 |
| graph.py | 删除旧 intent_node，修正 executor + _after_executor | -60/+25 |
| context_enrichment_node | token_budget 截断 + 写入 state | +25 |
| planner_node.py | 注入能力感知 + items/references/image_descs/search_context + critic feedback | +50 |
| prompt_builder_node.py | 注入 image_descs + critic feedback + 能力感知 | +40 |
| decision_node.py | retry_step_index 计算逻辑 | +15 |
| critic_node.py | 注入能力感知 prompt + 多模态检查 | +15 |
| generate_service.py | 删除双路径 + 4 个死函数 + feature flag | ~-250/+30 |
| executors/radiate.py | 兼容 plan_meta 缺失回退 | +20 |
| schemas/planning.py | critic_mode 默认改为 "on" | +1 |
| plan_executor.py | **删除** | -219 |

**净变化：** ~-1080 行，+500 行新代码。修复 10 个已识别问题。

---

## 重要说明

- **本窗口职责**：架构设计与方案修订，不进行代码实施
- **下一步**：执行 docs/plans/2026-05-12-agent-graph-unification.md 中的 Task 1-7
- **不受影响**：uild_agent_graph()（sidebar assistant 2-node graph）——其 agent_node/tools_node/_should_continue 均未改动
- **验证方式**：每个 Task 完成后运行其 Verification 步骤；Task 7 进行最终集成验证
