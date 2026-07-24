# Changelog

## [0.4.2-beta] - 2026-05-16

### Added
- **ImageContextResolver**: intent-driven auto-forward of session images to generation context
- **Unified executor engine** (`engine.py`): replaces 5 separate executor files (single/parallel/iterative/radiate/base)
- **Agent inline progressive display**: 4 lightweight components replace AgentStreamCard

### Changed
- **5 executor files removed**, consolidated into single `engine.py`
- `plan_executor.py` removed (dead code)
- Intent detection simplified — ~550 lines regex replaced with LLM classification
- Skill model: added `strategy_hint` field for skill-to-strategy mapping
- Frontend: AssistantSidebar, Sessions, SkillManage, RuleManage, ReferenceManage UI refinements
- API: prompt router, session router, billing API updates

### Fixed
- Accept data: URLs in session image building and resolver
- 5 intent detection bugs in ImageContextResolver

## [0.4.1-beta] - 2026-05-13

### Added — Agent Graph Unification + Skill Matcher + Billing
- **9-node agent graph**: `intent → skill_matcher → skill → context_enrichment → planner → prompt_builder → executor → critic → decision`
- **`skill_matcher_node.py`**: keyword overlap + strategy_hint scoring, top-3 activation, merges with user manual picks
- **`intent_node.py`**: pure LLM intent classification via `classify_intent_with_llm()` (replaces regex+LLM hybrid)
- **`capability_prompts.py`**: strategy-aware system prompts — PLANNER_STRATEGY_GUIDE, IMAGE_PROVIDER_CAPABILITIES, PROMPT_BUILDER_GUIDE, CRITIC_EVALUATION_DIMENSIONS, build_planner_system_prompt()
- **`llm_call_logger.py`**: unified LLM call logging + billing — LLMCallRecord, extract_tokens, log_and_bill, LLMTimer
- **Agent message metadata**: full decision trace stored in DB — plan, critic, decision, node_trace, image_descriptions
- **Search enhancement billing**: web_search and image_search calls billed via record_billing()
- **Critic feedback injection**: decision_node computes retry_step_index; prompt_builder_node and planner_node read critic_results on retry

### Changed
- **`critic_mode` default**: "off" → "on" (critic/decision flow active by default)
- **`use_langgraph` removed** from agent mode path — graph is now the only path; `_execute_direct()` is minimal fallback
- **Intent classification**: `hybrid_parse_intent()` (~550 lines regex) replaced with pure LLM `classify_intent_with_llm()`
- **5 LLM nodes billing**: intent, planner, prompt_builder, critic, context all use llm_call_logger.log_and_bill()
- **State**: added `retry_step_index`, `search_context`, `image_provider_id`, `llm_provider_id` fields

### Removed
- `plan_executor.py` (zero references, dead code)
- `hybrid_parse_intent()`, `_execute_single()`, `_execute_radiate()`, `_build_execution_plan()`, `_get_use_langgraph_setting()` from generate_service.py
- ~550 lines of regex-based intent classification code from agent_intent_service.py

### Fixed — 10 Known Data Flow Bugs
- executor_node doesn't receive image_provider_id → injects into PlanningContext
- RadiateExecutor reads plan_meta items but planner doesn't produce them → fallback to plan.steps
- intent_node items/references not forwarded → planner_node user_data includes them
- context_enrichment image_descriptions discarded → injected into planner/prompt_builder LLM prompts
- search_context in state but planner ignores it → planner_node user_data includes it
- prompt_builder retry doesn't read critic feedback → reads critic_results + retry_step_index
- planner replan doesn't read critic feedback → injects previous_issues/avg_score/replan_reason
- planner prompt strategy-agnostic → capability_prompts provides strategy-aware system prompts
- critic requires multimodal LLM without notification → checks model_id, warns, returns default scores
- token_budget computed but never used → context_enrichment_node truncates at 6000 hard cap

## [0.4.0-beta] - 2026-05-12

### Added — P2 LangGraph Integration
- **LangGraph StateGraph architecture**: 2-node graph (`agent ⇄ tools`) for sidebar assistant, 8-node graph (`intent → skill → context → planner → prompt_builder → executor → critic → decision`) for agent mode
- **`core/agent/`** module: `state.py` (AgentState), `graph.py` (build_agent_graph + build_agent_mode_graph), `graph_llm.py` (LLM streaming node), `graph_tools.py` (tool execution node)
- **`core/agent/nodes/`**: `skill_node.py`, `context_node.py`, `planner_node.py`, `prompt_builder_node.py`, `critic_node.py`, `decision_node.py`
- **`critic_interface.py`**: `CriticOutput` dataclass — P2↔P3 preference scoring interface
- **`services/planning_context.py`**: `PlanningContextManager` — token budget, image dedup, relevance filter, image description cache
- **Skill bias model**: 4 new columns (`strategy_hint`, `planning_bias`, `constraints`, `prompt_bias`) on `skills` table, `skill_to_planner_hints()` in `skill_engine.py`
- **LLM-driven planner**: `planner_node` generates `ExecutionPlan` under `task_type` constraint with strategy whitelist
- **Multimodal prompt builder**: `prompt_builder_node` calls vision LLM when context_images present
- **Critic vision scoring**: `critic_node` rates images 0-10 with 6-dimension tags + Chinese issues list
- **Decision routing**: `decision_node` 4-tier retry (≥7 pass / 5-7 warn / 3-5 retry_prompt / <3 retry_step)
- **Checkpoint generalization**: `PlanStep.checkpoint.enabled=true` triggers `checkpoint_required` event via `executor_node`; `POST /checkpoint` supports `retry_level: approve|retry_step|replan`
- **CheckpointOverlay**: 4-button UI (continue/retry step/replan/cancel) with `stepDescription` prop
- **`context_enrichment_node`**: image deduplication across reference/context/history sources, auto image description caching via vision LLM
- **New app_settings**: `use_langgraph` (default true), `critic_mode` (default "off"), `critic_max_retry` (default 2)
- **Dependencies**: `langgraph>=1.1.10,<1.2.0`, `tiktoken>=0.7.0`
- **`PlanningContext`**: added `context_reference_urls`, `skill_hints`, `token_budget`, `critic_mode`, `critic_max_retry` fields + `budget_tokens()` method + `extra="ignore"` config

### Changed
- **Python**: migrated from 3.9 to 3.14 (build.py, requirements, AGENTS.md)
- **`Sessions.vue`**: 4082 → 1731 lines, 14 sub-components extracted
- **`_stream_with_tools`**: legacy path preserved as `_stream_with_tools_legacy`, new `_stream_with_graph` via `get_use_langgraph()`
- **`handle_agent_generate`**: graph path via `_run_agent_mode_graph()` when `use_langgraph=true`, falls back to old `_build_execution_plan()`
- **`optimize_prompt()`**: new `context_images` parameter for multimodal optimization (P3 interface)
- **`intent_node`**: skips re-parsing when state.intent already populated
- **All Python files**: removed `from __future__ import annotations` (not needed in 3.14)

### Fixed
- `context_enrichment_node`: refactored to use `PlanningContextManager` instead of inline duplicate logic
- `executor_node`: emits `checkpoint_required` LamEvent for plan steps with checkpoint enabled
- `PlanningContext`: `model_config = ConfigDict(extra="ignore")` prevents crash from extra dict keys

## [0.3.2] - 2026-05-12

### Fixed
- `_build_agent_context()` injects real multimodal image_url content parts
- `_build_agent_context()` now called by `agent_service.py:run_agent_loop()`
- Frontend contextMessages: agent messages with metadata.images now extracted
- Frontend shared context mode: image URLs injected as multimodal content parts
- `LamImager.spec`: explicit `python314.dll` binary entry

## [0.3.1-beta] - 2026-05-11

### Added
- `api_vendors` table, `vendor_id` FK on `api_providers`, vendor CRUD endpoints
- `resolve_provider_vendor()` vendor-first resolution with provider fallback

### Fixed
- `vendor_to_response` / `provider_to_response` MissingGreenlet errors
- `init_db()` guards against missing tables
- `resolve_provider_vendor` falls back to provider's own key on decrypt failure

### Changed
- Key derivation: machine fingerprint → file-based seed for portability
- Frontend ApiManage.vue: vendor table + expandable models sub-table
- Version bumped to 0.3.1-beta

## [0.2.1] - 2026-05-11

### Added
- `plan_executor.py` with `execute_parallel` and `execute_iterative`
- PlanTool `get_detail` action
- Template validation (strategy whitelist, min 1 step, required variables)
- User-selected `agent_plan_strategy` consumed by backend
- Frontend type-aware template variable inputs

### Fixed
- Builtin radiate template `{style}` → `{{style}}` syntax
- `_extract_items_from_text` placeholder fallback removed
- `PlanTool._apply_template` dead `template_id` kwarg removed
- Removed debug hardcoded paths

### Changed
- `PlanTemplate` model: added `builtin_version` column
- `PlanStepSchema`: removed dead `condition` field
- `TemplateVariableSchema.default` type changed from `str` to `Any`

## [0.2.0] - 2026-05-11

### Added
- Agent mode supports reference_images (base64) and reference_labels in all 4 executors
- Multimodal LLM reasoning in planning phase
- Hybrid intent parsing with confidence scoring + LLM fallback
- Upload buttons visible in agent mode UI

### Fixed
- `handle_agent_generate` previously ignored `data.reference_images`
- `_execute_single` passed raw URLs without base64 conversion
- `execute_iterative` had no initial reference image injection
- `_execute_radiate` had no reference image support
- `_build_agent_context` extracts image_urls from message metadata

## [0.1.0] - 2026-05-10

### Added
- Initial release with session-based conversation UI
- API provider management (LLM + image generation + web search)
- Agent mode with intent-based routing
- Prompt optimization with SSE streaming
- Plan template system
- Billing tracking
- Image proxy with SSRF protection
