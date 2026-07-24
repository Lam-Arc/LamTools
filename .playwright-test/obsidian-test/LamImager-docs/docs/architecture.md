# LamImager Architecture

## System Overview

LamImager is a monolithic web application for managing AI image generation tasks with a conversation-based UI. It combines a FastAPI backend (Python 3.14+) with a Vue3 frontend, using SQLite for data persistence.

```
┌─────────────────────────────────────────────────────────────┐
│                        Browser                               │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                 Vue3 SPA (Vite)                      │   │
│  │  Pinia Stores ← API Clients (Axios)                  │   │
│  │  Sessions.vue (Main UI with Assistant Sidebar)       │   │
│  └──────────────────────┬──────────────────────────────┘   │
└─────────────────────────┼───────────────────────────────────┘
                          │ HTTP/REST
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI Backend                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
│  │   Routers   │→ │  Services   │→ │   Models    │        │
│  │ (11 modules)│  │ (17 services)│  │ (10 tables)│        │
│  └─────────────┘  └─────────────┘  └──────┬──────┘        │
│                                           │                │
│  ┌────────────────────────────────────────┼──────────────┐ │
│  │              External APIs              │              │ │
│  │  LLM Client ──────► OpenAI-compatible LLM API         │ │
│  │  Image Client ────► OpenAI-compatible Image API       │ │
│  │  (chat_edit also uses /v1/chat/completions for img2img) │ │
│  └───────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                     SQLite Database                         │
│  data/lamimager.db (AES-256-GCM encrypted API keys)        │
└─────────────────────────────────────────────────────────────┘
```

## Core Components

### Backend (FastAPI)

| Component | Purpose | Files |
|-----------|---------|-------|
| Routers | HTTP endpoint definitions | `app/routers/*.py` |
| Services | Business logic, external API calls | `app/services/*.py` (16: agent_bridge, agent_intent, agent_service, api_manager, billing, generate, plan_execution, plan_template, planning_context, prompt_optimizer, reference, rule_engine, session_manager, settings, skill_engine, task_manager) |
| Models | SQLAlchemy ORM definitions | `app/models/*.py` |
| Schemas | Pydantic validation/serialization | `app/schemas/*.py` |
| Utils | Crypto, LLM client, Image client | `app/utils/*.py` |
| Middleware | SSRF protection for image proxy | `app/middleware/` |

### Frontend (Vue3)

| Component | Purpose | Files |
|-----------|---------|-------|
| Views | Page components | `src/views/*.vue` |
| API Clients | Axios HTTP clients | `src/api/*.ts` (12 modules incl. sse.ts) |
| Stores | Pinia state management | `src/stores/*.ts` |
| Composables | Reusable composition functions | `src/composables/*.ts` (useSessionEvents, useDialog, useMarkdown, useDownload) |
| Components | Shared UI components | `src/components/` (ConfirmDialog, ErrorBoundary) + `src/components/session/` (15: Lightbox, CompareOverlay, ContextMenu, GeneratingIndicator, ContextImageStrip, ComposerControls, TextMessageCard, OptimizationCard, ImageMessageCard, PlanMessageCard, AgentMessageCard, AssistantSidebar, MessageList, AgentStreamCard, CheckpointOverlay) |
| Types | TypeScript interfaces | `src/types/index.ts` |

## Data Models

| Model | Purpose |
|-------|---------|
| `api_vendors` | API vendors (name, base_url, encrypted API key); one key per vendor |
| `api_providers` | Models under a vendor (linked via `vendor_id`); stores model_id, type, billing, price |
| `skills` | Reusable prompt templates |
| `rules` | Global configuration rules (default_params/filter/workflow) |
| `billing_records` | Cost tracking per API call (linked to sessions) |
| `reference_images` | Reference image metadata with strength/crop config |
| `sessions` | Conversation sessions for the chat-based UI |
| `messages` | Messages within sessions (user/assistant/system/agent) |
| `app_settings` | Application settings (default providers, image size, max_concurrent, search_retry_count, download_directory, agent_checkpoint_rules) |
| `plan_templates` | Plan templates with variables for template-based planning, auto-versioning via `builtin_version` |

## Data Flow

### Session-Based Generation Flow

```
User Input (with optional attachments + reference images)
    │
    ▼
┌──────────────────┐
│ Sessions.vue     │  Chat input with file upload (base64)
│                  │  contextImageList strip with numbered badges
│                  │  Sends context_messages with optional image_urls
└────────┬─────────┘
         │ POST /api/sessions/{id}/generate
         │  { prompt, reference_images, reference_labels, context_messages }
         ▼
┌──────────────────┐
│ session.py router│  Validates input, creates message
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ generate_service │  Applies skills/rules, builds multimodal context
│                  │  Passes reference_images to ImageClient
│                  │  reference_labels provide [图N] numbered mapping
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ ImageClient      │  Image-to-Image 3-tier fallback:
│                  │  Tier 1: chat_edit() → /v1/chat/completions (multimodal, numbered labels)
│                  │  Tier 2: edit()      → /v1/images/edits (native)
│                  │  Tier 3: Vision LLM  → /v1/images/generations (text-only)
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ Billing created  │  Cost recorded automatically
└──────────────────┘
```

**Iterative Refinement**: When using `plan_strategy: "iterative"`, the frontend fetches previous step outputs via `/api/images/proxy?url=` (server-side proxy, avoids CORS) and passes them as `reference_images` to the next step, enabling chained image-to-image refinement.

### LLM Assistant Flow (Streaming)

```
User Message (with optional attachments)
    │
    ▼
┌──────────────────┐
│ Sessions.vue     │  Assistant sidebar dialog / optimize / plan
└────────┬─────────┘
         │ POST /api/prompt/stream (SSE)
         ▼
┌──────────────────┐
│ stream_llm_chat  │  Calls LLM API with streaming
└────────┬─────────┘
         │ token by token (SSE)
         ▼
┌──────────────────┐
│ Frontend renders │  Real-time streaming display
└────────┬─────────┘
         │ [DONE] event
         ▼
┌──────────────────┐
│ Billing created  │  Token usage recorded
└──────────────────┘
```

## Security

### API Key Encryption

- Algorithm: AES-256-GCM
- Key derivation: SHA-256 from a file-based seed (`<DATA_DIR>/.encryption_seed`), auto-created on first run
- Storage: Base64(nonce + ciphertext + tag) in SQLite (`api_vendors.api_key_enc` for vendor mode, `api_providers.api_key_enc` for legacy)
- Resolution: `resolve_provider_vendor()` prefers vendor key, falls back to provider's own key
- Portability: Copy the `.encryption_seed` file alongside the database to preserve keys when moving to a new machine
- Response masking: Show only last 4 characters
- Decrypt error handling: Caught and logged, never crashes the request

### Encryption Flow

```python
# Encrypt
key = derive_key()  # From file-based seed (<DATA_DIR>/.encryption_seed)
nonce = os.urandom(12)
ciphertext = AESGCM(key).encrypt(nonce, plaintext, None)
stored = base64.b64encode(nonce + ciphertext)

# Decrypt
combined = base64.b64decode(stored)
nonce, ciphertext = combined[:12], combined[12:]
plaintext = AESGCM(key).decrypt(nonce, ciphertext, None)
```

### SSRF Protection (Image Proxy)

The `/api/images/proxy` endpoint implements server-side URL fetching with security controls:

1. **Scheme validation**: Only `http` and `https` URLs are allowed
2. **DNS resolution check**: Target hostname is resolved via `socket.getaddrinfo()`, and the resulting IP is checked against private/loopback/link-local/reserved ranges
3. **Content-Type validation**: Response must have `image/*` Content-Type

### Path Traversal Protection (Download)

The `/api/download/image` endpoint validates user-supplied filenames:

1. **Filename whitelist**: Regex `^[\w\u4e00-\u9fff.\-]+$` allows only alphanumeric, CJK, dots, and hyphens
2. **Path containment**: `filepath.resolve().is_relative_to(save_dir.resolve())` ensures the resolved path stays within the target directory

### XSS Prevention (Frontend)

The `useMarkdown.ts` composable sanitizes markdown rendering:

1. **HTML entity escaping**: All `<`, `>`, `&` are escaped before markdown parsing
2. **Dangerous protocol filtering**: `javascript:`, `data:`, `vbscript:` links are neutralized
3. **Safe external links**: `rel="noopener noreferrer"` + `target="_blank"` added to all external links

## Billing

### Cost Calculation
- `calc_cost(provider, tokens_in, tokens_out, call_count)` in `billing_service.py` — unified formula for all paths
  - `per_token`: `unit_price × (tokens_in + tokens_out) / 1000` (with fallback to `unit_price × call_count` when tokens unavailable)
  - `per_call`: `unit_price × call_count`
- `record_billing()` in `billing_service.py` — single entry point for creating billing records
- All billing records use `provider.billing_type.value` (no hardcoded `"per_token"`)

### Operation Types (detail.type)
| Type | Label | Path |
|---|---|---|
| `image_gen` | 图像生成 | `handle_generate` |
| `optimize` | 提示词优化 | `optimize_prompt`, `optimize_prompt_stream` |
| `assistant` | 小助手对话 | `stream_llm_chat` (stream_type="assistant") |
| `plan` | 规划生成 | `stream_llm_chat` (stream_type="plan") via `/api/prompt/plan` |
| `vision` | 视觉分析 | `_describe_reference_images` |
| `agent` | Agent执行 | `llm_call_logger.log_and_bill()` (per LLM node in graph) |
| `tool` | 工具调用 | `_enhance_with_search()` (web_search/image_search), `llm_call_logger.log_and_bill()` (graph LLM nodes) |

### Image Generation
- Per-call billing: Call count = image_count
- Per-token billing: Uses token usage from chat_edit API responses (Chat API returns usage; Images API does not)
- Image-to-image: chat_edit charges via Chat API (per-token), edit charges via Images API

### LLM Services
- Prompt optimization, planning, assistant dialog all use per-token billing with API usage extraction
- Vision fallback (image description) billed per token
- Streaming via `/api/prompt/stream` and `/api/prompt/plan` (SSE)
- Billing records created in `prompt_optimizer.py` and `generate_service.py`

### Session Cost Aggregation
- `list_sessions()` uses subqueries (`msg_subq` + `billing_subq`) to avoid cartesian product from dual OUTER JOINs
- Session `cost` = SUM of all billing records for that session
- Session `tokens` = SUM of all `tokens_in + tokens_out` for that session

### Breakdown API
- `GET /api/billing/breakdown` returns costs grouped by provider and by operation type
- Frontend billing drawer displays both tables (API spending + operation type breakdown)

## Agent System

The Agent system provides LLM-driven autonomous task orchestration, now powered by LangGraph StateGraph (Phase 2).

### LangGraph Architecture

Two co-existing graph configurations:

**Sidebar Assistant (2-node loop)** — replaces old `AgentLoop`:
```
agent_node (LLM + tools) ⇄ tools_node (execution) → END
```

**Agent Mode (9-node)** — full planning pipeline:
```
intent → skill_matcher → skill → context_enrichment → planner → prompt_builder → executor → (critic → decision → retry)
```

See `AGENTS.md` for full node descriptions.

### Graph Files
| File | Purpose |
|------|---------|
| `core/agent/state.py` | `AgentState` TypedDict shared across all nodes |
| `core/agent/graph.py` | `build_agent_graph()` (2-node) + `build_agent_mode_graph()` (9-node) + `executor_node` + routing functions |
| `core/agent/graph_llm.py` | `agent_node` — LLM streaming with tool calling |
| `core/agent/graph_tools.py` | `tools_node` — tool execution + billing |
| `core/agent/capability_prompts.py` | Strategy-aware system prompts: PLANNER_STRATEGY_GUIDE, IMAGE_PROVIDER_CAPABILITIES, PROMPT_BUILDER_GUIDE, CRITIC_EVALUATION_DIMENSIONS |
| `core/agent/llm_call_logger.py` | Unified LLM call logging + billing: LLMCallRecord, extract_tokens, log_and_bill, LLMTimer |
| `core/agent/nodes/intent_node.py` | Pure LLM intent classification via `classify_intent_with_llm()` |
| `core/agent/nodes/skill_matcher_node.py` | Keyword overlap + strategy_hint scoring, top-3 activation |
| `core/agent/nodes/skill_node.py` | Reads skill_ids → outputs skill_hints |
| `core/agent/nodes/context_node.py` | Delegates to `PlanningContextManager`, token budget truncation |
| `core/agent/nodes/planner_node.py` | LLM-driven `ExecutionPlan` generation with capability prompts |
| `core/agent/nodes/prompt_builder_node.py` | Multimodal prompt optimization, critic feedback injection |
| `core/agent/nodes/critic_node.py` | Vision LLM scoring (0-10), multimodal model check |
| `core/agent/nodes/decision_node.py` | Retry routing (pass/warn/retry_prompt/retry_step), retry_step_index |
| `core/agent/critic_interface.py` | `CriticOutput` dataclass (P2↔P3) |
| `services/planning_context.py` | `PlanningContextManager` — token budget, dedup, cache, relevance filter |

### Tools (backend/app/tools/)
- **base.py**: `Tool` abstract class + `ToolResult` dataclass
- **web_search.py** / **image_search.py**: Serper.dev integration, internal 3x retry
- **generate_image.py**: Wraps ImageClient, supports `grid_config` for multi-item sets
- **plan.py**: Wraps plan_template_service CRUD + template matching

### AgentLoop (backend/app/services/agent_service.py)
- `run_agent_loop()`: async generator yielding `AgentEvent` types (TokenEvent, ToolCallEvent, ToolResultEvent, DoneEvent, CancelledEvent, WarningEvent)
- Used as fallback for sidebar assistant when `use_langgraph=false`
- `tool_choice`: `"required"` on rounds 0-1 (forces at least one tool call early), `"auto"` from round 2
- Tool provider injection: web_search and image_gen API keys decrypted and passed to tool execution
- Billing per round (LLM) + per tool call
- Cancel support: `asyncio.Event` per session
- Checkpoint timeout: `wait_checkpoint()` with 300s default, auto-rejects on timeout

### Search Enhancement (backend/app/services/generate_service.py)
- `has_search_intent()` in `agent_intent_service.py` detects search semantics: 参考/搜索/趋势/流行/reference/search/trend/popular
- When triggered and `web_search` provider is configured, `_enhance_with_search()` executes before strategy routing:
  1. Calls `WebSearchTool` and `ImageSearchTool` via Serper API
  2. Injects search results into the prompt as context
  3. Creates system messages showing search results to user
- Falls back gracefully if no `web_search` provider configured

### Intent-Based Strategy Routing
For multi-item generation (e.g. "3 emoji pack"), handled via code-driven intent routing:

1. **Intent classification**: `classify_intent_with_llm()` classifies prompts into 4 task types via pure LLM classification (no regex)
2. **single** (画一只猫): `SingleExecutor` → `generate_images_core()`
3. **multi_independent** (画3张不同风格的猫): `ParallelExecutor` → LLM prompts + parallel `generate_images_core()`
4. **iterative** (先出草图再精修): `IterativeExecutor` → sequential execution
5. **radiate** (做一套6个表情包): `RadiateExecutor` → anchor grid → PIL crops → per-item `chat_edit()`

Strategy executors are in `backend/app/services/executors/` (single, parallel, iterative, radiate). `PlanExecutionService` in `plan_execution_service.py` dispatches to the appropriate executor.

### SSE Events (LamEvent v1 broadcast)
Agent events broadcast via `TaskManager.publish()` to `GET /api/sessions/events`. Frontend receives via `fetch`+`ReadableStream`.

| LamEvent.event_type | payload.type | Description |
|---|---|---|
| `task_started` | `task_started` | Task started, includes `task_type` and `strategy` |
| `task_progress` | `task_progress` | Progress update, includes `task_type`, `strategy`, `message` |
| `task_progress` | `agent_token` | LLM output token (sidebar assistant) |
| `task_progress` | `agent_tool_call` | Tool invocation started (sidebar assistant) |
| `task_progress` | `agent_tool_result` | Tool execution result (sidebar assistant) |
| `task_progress` | `agent_tool_warning` | Tool retry exhausted |
| `checkpoint_required` | `agent_checkpoint` | Agent paused awaiting user approval |
| `task_completed` | `agent_done` | Agent finished |
| `task_failed` | `agent_error` | Agent error |
| `task_completed` | `agent_cancelled` | Agent cancelled |

## Concurrency Model

- Backend: Async/await with asyncio
- Database: aiosqlite for async SQLite
- TaskManager singleton: Global task state + SSE broadcast to all connected clients
- Image generation: `asyncio.Semaphore` for rate limiting
- Frontend: SSE EventSource for real-time task status (snapshot + task_update + ping), no WebSocket needed
- Multi-session: activeTasks Map enables concurrent generation across multiple sessions

## Configuration

| Setting | Default | Location |
|---------|---------|----------|
| `DATA_DIR` | `./data` | `config.py` |
| `DB_URL` | `sqlite+aiosqlite:///data/lamimager.db` | `config.py` |
| `MAX_CONCURRENT_TASKS` | 5 | `config.py` / app_settings |
| `CORS_ORIGINS` | `["http://localhost:5173"]` | `config.py` |

## Deployment

### Requirements
- Python 3.14+ (standard GIL mode, NOT free-threaded `python3.14t`)
- Node.js 18+

### Development
- Frontend: Vite dev server on port 5173
- Backend: Uvicorn on port 8000
- Vite proxy forwards `/api` to backend

### Production
- Build frontend: `npm run build` → `frontend/dist/`
- FastAPI serves static files from `frontend/dist/`
- Single process handles both API and static files
