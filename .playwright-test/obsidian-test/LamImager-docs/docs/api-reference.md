# LamImager API Reference

Base URL: `http://localhost:8000/api`

## Authentication

None (single-user desktop application).

## Common Response Format

### Success
```json
{
  "id": "uuid-string",
  "field1": "value1",
  "created_at": "2026-05-06T12:00:00"
}
```

### Error
```json
{
  "detail": "Error message"
}
```

---

## Sessions

### List Sessions
```
GET /api/sessions
```

Response: `Session[]`

```json
[
  {
    "id": "uuid",
    "title": "New Session",
    "status": "idle",
    "created_at": "2026-05-07T12:00:00",
    "updated_at": "2026-05-07T12:00:00",
    "message_count": 5,
    "cost": 0.15,
    "tokens": 1234
  }
]
```

### Real-time Task Events (SSE)
```
GET /api/sessions/events
```

Content-Type: `text/event-stream`

SSE Events:
- `data: {"type": "snapshot", "data": {"session_id": {"status": "generating", ...}}}` - Initial state dump
- `data: {"type": "task_update", "data": {"session_id": "uuid", "status": "generating", "progress": 2, "total": 4, "message": "..."}}` - Task status change
- `data: {"type": "ping", "data": {}}` - 30s keepalive

### Create Session
```
POST /api/sessions
```

Body:
```json
{
  "title": "My Session"
}
```

Response: `Session`

### Get Session
```
GET /api/sessions/{id}
```

Response: `Session`

### Update Session
```
PUT /api/sessions/{id}
```

Body:
```json
{
  "title": "Updated Title"
}
```

### Delete Session
```
DELETE /api/sessions/{id}
```

### Get Session Messages
```
GET /api/sessions/{id}/messages
```

Response: `Message[]`

```json
[
  {
    "id": "uuid",
    "session_id": "uuid",
    "role": "user",
    "content": "Generate a cat",
    "message_type": "text",
    "metadata": {},
    "created_at": "2026-05-07T12:00:00"
  }
]
```

### Add Message to Session
```
POST /api/sessions/{id}/messages
```

Body:
```json
{
  "content": "Message text",
  "message_type": "text",
  "metadata": {}
}
```

Message types: `text` | `image` | `optimization` | `plan` | `skill` | `error` | `agent`

Plan message metadata:
```json
{
  "type": "plan",
  "steps": [
    {"prompt": "English prompt for API", "negative_prompt": "...", "description": "Chinese step description"}
  ],
  "description": "Original user input"
}
```

Response: `Message`

### Generate Images in Session
```
POST /api/sessions/{id}/generate
```

Body:
```json
{
  "prompt": "A fluffy cat sitting on a chair",
  "negative_prompt": "blurry, low quality",
  "image_count": 1,
  "image_size": "1024x1024",
  "skill_ids": [],
  "optimize_directions": ["detail_enhancement"],
  "custom_optimize_instruction": "",
  "reference_images": ["data:image/png;base64,..."],
  "reference_labels": [{"index": 1, "source": "upload", "name": "photoA.png"}],
  "context_messages": [{"role": "user", "content": "...", "image_urls": ["http://localhost:8000/api/images/xxx.png"]}],
  "plan_strategy": "parallel",
  "agent_mode": false,
  "agent_tools": ["web_search", "image_search", "generate_image", "plan"],
  "agent_plan_strategy": ""
}
```

> **Note**: `agent_plan_strategy` is deprecated — the backend now determines strategy automatically based on intent parsing. The field is accepted but ignored.

Response: `Message` (assistant message with generated images)

> **Image-to-Image**: When `reference_images` is non-empty, the backend uses a 3-tier fallback:
> 1. `POST /v1/chat/completions` with multimodal messages + numbered labels (图1, 图2...)
> 2. `POST /v1/images/edits` (native OpenAI, may fail on some proxies)
> 3. Vision LLM description → `POST /v1/images/generations` (text-only fallback)
>
> **Multimodal Context**: `context_messages` can include `image_urls` for LLM visual context.
> When present, backend builds multimodal messages via `_build_multimodal_context()`.
>
> **Agent Mode**: When `agent_mode` is `true`, the endpoint delegates to `handle_agent_generate`
> which invokes `AgentLoop` with the specified `agent_tools`. Available tools: `web_search`,
> `image_search`, `generate_image`, `plan`. The LLM autonomously decides tool invocation order.

### Cancel Agent Task
```
POST /api/sessions/{id}/cancel
```
Cancels ongoing agent task. Sets `asyncio.Event` per session, agent loop checks between rounds.

Response: `{"message": "Cancelled"}`

### Agent Checkpoint
```
POST /api/sessions/{id}/agent/checkpoint
```
Approve, retry, or replan agent checkpoint (e.g. anchor grid quality check). Checkpoint auto-rejects after 300s timeout.

Body:
```json
{
  "action": "approve",
  "feedback": "",
  "retry_level": "approve"
}
```

`action` values: `"approve"` (continue) | `"retry_step"` (re-execute current step) | `"replan"` (back to planner). Any other value is treated as rejection.

`retry_level` values: `"approve"` | `"retry_step"` | `"replan"` — if omitted, derived from `action`.

Response:
```json
{
  "status": "approved",
  "step": "anchor_grid"
}
```

### Proxy Image
```
GET /api/images/proxy?url=<encoded_url>
```
Fetches an external image server-side and returns the bytes. Used by the frontend to fetch cross-origin generated images for iterative refinement, avoiding browser CORS restrictions.

Security: Only `http`/`https` URLs allowed. DNS resolution blocks private/loopback IPs. Response Content-Type must be `image/*`.

Response: raw image bytes with appropriate `Content-Type` header.

---

## Settings

### Get Default Models
```
GET /api/settings/default-models
```

Response:
```json
{
  "default_optimize_provider_id": "uuid",
  "default_image_provider_id": "uuid",
  "default_plan_provider_id": "uuid",
  "default_image_width": 1024,
  "default_image_height": 1024,
  "max_concurrent": 5
}
```

### Update Default Models
```
PUT /api/settings/default-models
```

Body:
```json
{
  "default_optimize_provider_id": "uuid",
  "default_image_provider_id": "uuid",
  "default_plan_provider_id": "uuid",
  "default_image_width": 1024,
  "default_image_height": 1024,
  "max_concurrent": 5
}
```

### Get Arbitrary Setting
```
GET /api/settings/{key}
```

Supported keys: `search_retry_count`, `download_directory`

Response:
```json
{
  "key": "download_directory",
  "value": {
    "value": "D:\\Downloads\\images"
  }
}
```

### Set Arbitrary Setting
```
PUT /api/settings/{key}
```

Body:
```json
{
  "value": "D:\\Downloads\\images"
}
```

---

## Vendors

### List Vendors
```
GET /api/vendors
```

Response: `Vendor[]`

```json
[
  {
    "id": "uuid",
    "name": "OpenAI",
    "base_url": "https://api.openai.com",
    "api_key_masked": "****xxxx",
    "is_active": true,
    "model_count": 3,
    "created_at": "2026-05-10T12:00:00",
    "updated_at": "2026-05-10T12:00:00"
  }
]
```

### Create Vendor
```
POST /api/vendors
```

Body:
```json
{
  "name": "OpenAI",
  "base_url": "https://api.openai.com",
  "api_key": "sk-xxxxx",
  "is_active": true
}
```

Response: `Vendor` (api_key masked)

### Get / Update / Delete Vendor
```
GET /api/vendors/{id}
PUT /api/vendors/{id}
DELETE /api/vendors/{id}
```

### Test Vendor Connection
```
POST /api/vendors/{id}/test
```

Response:
```json
{
  "success": true,
  "message": "Connection successful"
}
```

### List Models Under Vendor
```
GET /api/vendors/{id}/models
```

Response: `ApiProvider[]`

### Create Model Under Vendor
```
POST /api/vendors/{id}/models
```

Body:
```json
{
  "nickname": "GPT-4o",
  "model_id": "gpt-4o",
  "provider_type": "llm",
  "billing_type": "per_token",
  "unit_price": 0.01,
  "currency": "USD"
}
```
Note: `base_url` and `api_key` are inherited from vendor.

---

## Providers

### List Providers
```
GET /api/providers
```

Query Parameters:
- `provider_type` (optional): `image_gen` | `llm` | `web_search`

Response: `ApiProvider[]`

### Create Provider
```
POST /api/providers
```

Body (standalone, with own key):
```json
{
  "nickname": "OpenAI GPT-4",
  "base_url": "https://api.openai.com",
  "model_id": "gpt-4o",
  "api_key": "sk-xxxxx",
  "provider_type": "llm",
  "billing_type": "per_token",
  "unit_price": 0.01,
  "currency": "USD",
  "is_active": true
}
```

Body (under vendor, inherits base_url/api_key):
```json
{
  "nickname": "GPT-4o",
  "model_id": "gpt-4o",
  "vendor_id": "uuid",
  "provider_type": "llm",
  "billing_type": "per_token",
  "unit_price": 0.01
}
```

Query parameters for list:
- `provider_type` (optional): `image_gen` | `llm` | `web_search`
- `vendor_id` (optional): filter by vendor

Response: `ApiProvider` (api_key masked as `****xxxx`)

### Get Provider
```
GET /api/providers/{id}
```

Response: `ApiProvider`

### Update Provider
```
PUT /api/providers/{id}
```

Body: Partial `ApiProviderCreate` (omit `api_key` to keep current)

Response: `ApiProvider`

### Delete Provider
```
DELETE /api/providers/{id}
```

Response: `{"message": "Provider deleted"}`

### Test Connection
```
POST /api/providers/{id}/test
```

Response:
```json
{
  "success": true,
  "message": "Connection successful"
}
```

---

## Skills

### List Skills
```
GET /api/skills
```

Response: `Skill[]`

### Create Skill
```
POST /api/skills
```

Body:
```json
{
  "name": "Product Photography",
  "description": "Professional product shot style",
  "prompt_template": "Professional product photo of {subject}, studio lighting, white background, {prompt}",
  "parameters": {"subject": "product"},
  "is_builtin": false
}
```

Response: `Skill`

### Import Skill
```
POST /api/skills/import
```

Body: Same as Create Skill

Response: `Skill`

### Update/Delete Skill
```
PUT /api/skills/{id}
DELETE /api/skills/{id}
```

---

## Rules

### List Rules
```
GET /api/rules
```

Query Parameters:
- `rule_type` (optional): `default_params` | `filter` | `workflow`

Response: `Rule[]`

### Create Rule
```
POST /api/rules
```

Body:
```json
{
  "name": "Default Negative Prompt",
  "rule_type": "filter",
  "config": {
    "negative_keywords": ["blurry", "low quality", "watermark"]
  },
  "is_active": true,
  "priority": 10
}
```

Response: `Rule`

### Toggle Rule Active
```
PUT /api/rules/{id}/toggle
```

Response: `Rule`

---

## Billing

### Get Summary
```
GET /api/billing/summary
```

Response:
```json
{
  "today": 1.23,
  "month": 45.67,
  "total": 123.45,
  "currency": "CNY"
}
```

### Get Details
```
GET /api/billing/details
```

Query Parameters:
- `start_date`: ISO date string
- `end_date`: ISO date string
- `provider_id`: UUID
- `session_id`: UUID
- `page`: int (default 1)
- `page_size`: int (default 20)

Response:
```json
{
  "total": 100,
  "page": 1,
  "page_size": 20,
  "records": [BillingRecord]
}
```

### Export CSV
```
GET /api/billing/export
```

Query Parameters:
- `start_date`, `end_date`

Response: `text/csv` attachment

### Get Breakdown
```
GET /api/billing/breakdown
```

Response:
```json
{
  "by_provider": [
    {"provider_id": "uuid", "nickname": "GPT-Image-2", "cost": 5.70, "tokens": 18011}
  ],
  "by_type": [
    {"type": "image_gen", "label": "图像生成", "cost": 5.70, "tokens": 18011, "count": 53},
    {"type": "optimize", "label": "提示词优化", "cost": 0.01, "tokens": 5000, "count": 5},
    {"type": "assistant", "label": "小助手对话", "cost": 0.02, "tokens": 8000, "count": 10},
    {"type": "plan", "label": "规划生成", "cost": 0.01, "tokens": 3000, "count": 2},
    {"type": "vision", "label": "视觉分析", "cost": 0.005, "tokens": 2000, "count": 1}
  ]
}
```

Operation types: `image_gen` | `optimize` | `assistant` | `plan` | `vision` | `agent` | `tool`

---

## References

### List References
```
GET /api/references
```

Query Parameters:
- `is_global`: boolean

Response: `ReferenceImage[]`

### Upload Reference
```
POST /api/references/upload
```

Content-Type: `multipart/form-data`

Form Fields:
- `file`: File
- `name`: string
- `is_global`: boolean
- `strength`: float (0-1)

Response: `ReferenceImage`

### Update Reference
```
PUT /api/references/{id}
```

Body:
```json
{
  "name": "New name",
  "is_global": true,
  "strength": 0.7,
  "crop_config": {"x": 0, "y": 0, "width": 100, "height": 100}
}
```

---

## Prompt Optimization

### Optimize Prompt
```
POST /api/prompt/optimize
```

Body:
```json
{
  "prompt": "A cat sitting on a chair",
  "direction": "detail_enhancement",
  "llm_provider_id": "uuid",
  "session_id": "uuid",
  "multimodal_context": null
}
```

Directions: `detail_enhancement` | `style_unification` | `composition_optimization` | `color_adjustment` | `lighting_enhancement` | `custom:<instruction>`

Multiple directions can be combined with comma: `detail_enhancement,style_unification`

Optional field `session_id` links billing record to session.

Response:
```json
{
  "original": "A cat sitting on a chair",
  "optimized": "A fluffy calico cat gracefully perched on a vintage wooden chair, soft afternoon sunlight streaming through lace curtains, shallow depth of field, warm color palette, photorealistic style",
  "direction": "detail_enhancement"
}
```

### Stream Optimize Prompt
```
POST /api/prompt/optimize/stream
```

Content-Type: `text/event-stream` (SSE)

Body:
```json
{
  "prompt": "A cat sitting on a chair",
  "direction": "detail_enhancement",
  "llm_provider_id": "uuid",
  "session_id": "uuid"
}
```

SSE Events: Same format as Stream LLM Chat (token-by-token).

### Stream LLM Chat
```
POST /api/prompt/stream
```

Content-Type: `text/event-stream` (SSE)

Body:
```json
{
  "messages": [{"role": "user", "content": "Hello"}],
  "provider_id": "uuid",
  "session_id": "uuid",
  "temperature": 0.7,
  "stream_type": "assistant",
  "agent_tools": ["web_search", "image_search"]
}
```

`stream_type`: `"assistant"` (default) for general chat, used for billing categorization.

`agent_tools` (optional): List of tool names the LLM can invoke. Supported values: `web_search`, `image_search`, `generate_image`, `plan`. When provided, the backend enables function calling and the response stream includes `tool_call` and `tool_result` events in addition to regular tokens.

SSE Events:
- `data: {"token": "word"}` - Each generated token
- `data: {"tool_call": {"name": "web_search", "args": {"query": "..."}}}` - Tool invocation
- `data: {"tool_result": {"name": "web_search", "content": "...", "meta": {...}}}` - Tool execution result
- `data: {"tool_warning": {"name": "...", "reason": "...", "retry_count": 0}}` - Tool retry exhausted
- `data: {"done": true, "cost": 0.001}` - Completion event with billing
- `data: {"error": "message"}` - Error event

### Image Proxy
```
GET /api/images/proxy?url=<encoded_url>
```

Server-side image proxy to avoid CORS issues. Used by the frontend when fetching previous generation outputs for iterative refinement.

---

## Dashboard

### Get Stats
```
GET /api/dashboard/stats
```

Response:
```json
{
  "total_sessions": 10,
  "total_images": 35,
  "total_generations": 7,
  "monthly_cost": 12.34
}
```

---

## Plan Templates

### List Templates
```
GET /api/plan-templates
```

Response: `PlanTemplate[]`

```json
[
  {
    "id": "uuid",
    "name": "Product Showcase",
    "description": "Professional product photography template",
    "strategy": "parallel",
    "steps": [{"prompt": "...", "description": "..."}],
    "variables": [{"key": "product", "type": "string", "label": "Product name", "default": ""}],
    "is_builtin": true,
    "builtin_version": 1,
    "created_at": "2026-05-07T12:00:00",
    "updated_at": "2026-05-07T12:00:00"
  }
]
```

### Create Template
```
POST /api/plan-templates
```

Body:
```json
{
  "name": "My Template",
  "description": "Custom workflow",
  "strategy": "parallel",
  "steps": [
    {"prompt": "{{subject}} portrait, professional lighting", "description": "Portrait shot", "image_count": 1}
  ],
  "variables": [
    {"key": "subject", "type": "string", "label": "Subject", "default": "person"}
  ]
}
```

### Get / Update / Delete Template
```
GET /api/plan-templates/{id}
PUT /api/plan-templates/{id}
DELETE /api/plan-templates/{id}
```

### Apply Template (variable substitution)
```
POST /api/plan-templates/{id}/apply
```

Body:
```json
{
  "variables": {"subject": "cat", "background": "garden"}
}
```

Response:
```json
{
  "steps": [
    {"prompt": "cat portrait, professional lighting, garden background", ...}
  ]
}
```

---

## Download

### Download Image to Directory
```
POST /api/download/image
```

Saves an image from a URL to the configured download directory. Requires `download_directory` to be set via `PUT /api/settings/download_directory`.

Security: Filename validated against whitelist regex `^[\w\u4e00-\u9fff.\-]+$`. Resolved path must be within download directory (path traversal protection).

Body:
```json
{
  "url": "https://example.com/image.png",
  "filename": "image.png"
}
```

If the file already exists, a counter is appended: `image (1).png`, `image (2).png`, etc.

Response:
```json
{
  "success": true,
  "path": "D:\\Downloads\\images\\image.png",
  "size": 123456
}
```

Errors:
- `400` — Download directory not configured or path doesn't exist
- `502` — Failed to download image from source URL

---

## Health Check

```
GET /api/health
```

Response:
```json
{
  "status": "ok",
  "version": "0.4.0-alpha",
  "author": "霖二",
  "license": "MIT"
}
```
