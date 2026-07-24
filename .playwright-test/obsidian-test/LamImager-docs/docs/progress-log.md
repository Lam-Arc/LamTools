# Progress Log

> Last updated: 2026-05-14

## Phase 1 — Pre-LangGraph Execution Kernel (Completed)

### Core Models + Template Output
- `PlanningContext` — unified input bag (`schemas/planning.py`)
- `ExecutionPlan` / `PlanStep` / `Artifact` / `StepTrace` / `ExecutionTrace` (`schemas/execution.py`)

### Four Executors
- `services/executors/single.py` — SingleExecutor
- `services/executors/parallel.py` — ParallelExecutor (asyncio.Semaphore)
- `services/executors/iterative.py` — IterativeExecutor (prev step → next step)
- `services/executors/radiate.py` — RadiateExecutor (anchor grid → PIL crop → chat_edit expand → fallback)

### Triple Entry Point Convergence
- Agent: `handle_agent_generate()` → `_build_execution_plan()` → `PlanExecutionService`
- Workbench: `handle_execute_plan()` → `PlanExecutionService`
- Skill: `_execute_skill_plan()` → `PlanExecutionService`

### Frontend Split
- `Sessions.vue` 4082 → 1731 lines (-57%)
- 14 sub-components extracted to `components/session/`

---

## Phase 2 — LangGraph Integration (Completed)

### P2B: Full 8-Node Graph
| Task | Status | Key Files |
|------|--------|-----------|
| 2.2 skill_node + context_enrichment_node | Done | `core/agent/nodes/skill_node.py`, `context_node.py` |
| 2.3 planner_node + prompt_builder_node | Done | `core/agent/nodes/planner_node.py`, `prompt_builder_node.py` |
| 2.4 critic_node + decision_node | Done | `core/agent/nodes/critic_node.py`, `decision_node.py`, `critic_interface.py` |
| 2.5 Checkpoint generalization | Done | `graph.py` (executor_node checkpoint emit), `routers/session.py` (retry_level), `CheckpointOverlay.vue` |
| 2.6 PlanningContext upgrade | Done | `services/planning_context.py` (budget_tokens, dedup, image cache, relevance filter) |

### P2 Task 8: Agent-Driven Skill Matching (2026-05-13)
| Task | Status | Key Files |
|------|--------|-----------|
| 8.1 skill_matcher_node | Done | `core/agent/nodes/skill_matcher_node.py` (new), `core/agent/graph.py` |
| 8.2 skill_node boundary | Verified | `core/agent/nodes/skill_node.py` (no changes needed) |

**Graph structure updated:** `intent → skill_matcher → skill → context_enrichment → planner → ...`

Skill matcher uses keyword overlap + strategy_hint scoring, top-3 activation, merges with user manual picks.

### 10 Known Bugs Fixed via Unification Plan (2026-05-13)
See `docs/plans/2026-05-12-agent-graph-unification.md` for full details.

| # | Severity | Issue | Fixed |
|---|----------|-------|-------|
| 7 | Blocker | executor_node doesn't receive image_provider_id | executor_node injects image_provider_id/llm_provider_id/session_id into PlanningContext |
| 1 | Blocker | RadiateExecutor reads plan_meta items but planner_node doesn't produce them | RadiateExecutor falls back to extracting items from plan.steps; planner_prompt requires radiate plan_meta |
| 4 | High | intent_node items/references not forwarded to planner_node | planner_node user_data includes items + references |
| 8 | High | context_enrichment image_descriptions computed then discarded | planner_node + prompt_builder_node inject image_descriptions into LLM prompts |
| 10 | High | search_context in state, planner_node ignores it | planner_node user_data includes search_context |
| 2 | High | prompt_builder retry doesn't read critic feedback | prompt_builder reads critic_results + retry_step_index, injects issues |
| 3 | High | planner replan doesn't read critic feedback | planner reads critic_results, injects previous_issues/avg_score/replan_reason |
| 5 | Medium | planner prompt strategy-agnostic, no capability awareness | capability_prompts.py: STRATEGY_EXECUTION_MECHANISM, PLANNER_STRATEGY_GUIDE, IMAGE_PROVIDER_CAPABILITIES, PROMPT_BUILDER_GUIDE, build_planner_system_prompt() |
| 6 | Low | critic requires multimodal LLM, needs user notification | critic_node checks model_id for multimodal keywords, warns, returns default scores |
| 9 | Low | token_budget computed but never used for truncation | context_enrichment_node truncates search_context → auto_context → non-pinned history at 6000 hard cap |

### Unification Plan Changes

### Agent Logging & Billing (2026-05-13)
| Task | Status | Key Files |
|------|--------|-----------|
| L1 llm_call_logger | Done | `core/agent/llm_call_logger.py` (new) |
| L2 5-node billing | Done | `nodes/intent_node.py`, `planner_node.py`, `prompt_builder_node.py`, `critic_node.py`, `context_node.py` |
| L3 metadata completion | Done | `services/generate_service.py` (plan/critic/decision/node_trace/image_descs in DB) |
| L4 search billing | Done | `services/generate_service.py` (web_search/image_search calls billed) |

All LLM calls in the agent graph now log tokens, latency, and bill automatically. Agent message metadata includes full decision trace.

### P2→P3 Design Decisions
- **Skill selection** (agent-driven): assigned to P2 scope — intent_node outputs skill-compatible features, skill_matcher to be added as P2 Task 8
- **Plan auto-save & reuse**: assigned to P3 scope — PlanTemplate infrastructure exists (P1), auto-save + exact match reuse is user value delivery beyond P2's scheduler upgrade boundary
- **Plan learning** (every generated plan permanently saved): P3 feature, requires new graph nodes (plan_matcher, plan_saver)

---

## Phase 3 — Architecture + Features (Redefinition)

### P3 Redefinition (2026-05-14)

P3 重新定义为 P3A（架构层搭建）+ P3B（功能增强），吸收 `learning-report.md` 研读成果。

**变更依据**：
- P3 原定"偏好评分"与 learning-report 的 ImagerProfile 画像 + CON(画像) 层 90% 重合
- P3 原定"Plan 自动保存"与 learning-report 的 PLAN 持久化 + 历史PLAN 回写 80% 重合
- P4 要抽取 Core SDK，但 Core SDK 需要先有东西可抽——P3 必须先把 PER/CON/MEN/Skill/Prompt 组装线做好
- 研读来源：Claude Code 2.4.3、OpenCode 1.14.50、learn-claude-code 教学项目

**P3A 任务清单**（架构层搭建，按依赖顺序）：
- [ ] P3A-0 ImageContextResolver — 修改意图自动转发目标图
- [ ] P3A-1 PER 层 — `PersonaDef` + `PERSONAS` 注册表
- [ ] P3A-2 Skill 两层注入 — `SkillInjector` Layer 1/Layer 2 + PER 过滤
- [ ] P3A-3 Prompt 组装线 — `PromptAssembler` 五层组装
- [ ] P3A-4 MEM Lite / CON 六层基础 — `MEMModule`（schemas/stores/recall/writer/lifecycle/budget/provenance/adapters）

> MEN 层已砍掉（见 `mental-model.md`）：PER 锁住人格基调，CON 提供情境信号，LLM 结合两者自行调节思维模式。

**P3B 任务清单**（功能增强）：
- [ ] P3B-1 ImagerProfile 画像
- [ ] P3B-2 PLAN 持久化 + 依赖图
- [ ] P3B-3 micro_compact
- [ ] P3B-4 身份重注入
- [ ] P3B-5 Nag Reminder
- [ ] P3B-6 Plan 自动保存与复用
- [ ] P3B-7 CriticOutput 标准化
- [ ] P3B-8 Mask 精修
- [ ] P3B-9 Guardrail / Error Patterns

**P3 原定项（已吸收到 P3B）**：
- ~~Preference/scoring system~~ → P3B-1 ImagerProfile 画像
- ~~Plan auto-save & reuse~~ → P3B-6 Plan 自动保存与复用
- ~~CriticOutput 标准化~~ → P3B-7 CriticOutput 标准化
- ~~Mask refinement~~ → P3B-8 Mask 精修

## Key Decisions
- LangGraph >=1.1.10,<1.2.0 (1.1.7 yanked — must skip)
- Python 3.14+ required (3.9 deprecated)
- `use_langgraph` removed — graph is now the only path; `_execute_direct()` is the minimal fallback
- `decision_node` is sole retry decision owner; `critic_node` outputs `{score, tags, issues}` only
- `critic_mode=on` by default (unification plan enables critic/decision flow)
- Intent classification is pure LLM (no regex); graph's intent_node handles classification
- `tiktoken>=0.7.0` for token budget; failure logs warning, never blocks
- No `from __future__ import annotations` in any Python file

## Verification Commands
```bash
# Backend (Python 3.14 required)
cd backend && py -3.14 -m uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend && npm run dev

# Desktop exe
py build.py [--clean] [--skip-frontend]
```
