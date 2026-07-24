# LamImager - AI Image Generation Task Manager

> **Status: IMPLEMENTED** (2026-05-06) - See README.md, AGENTS.md, and docs/ for current documentation.

## Goal
Build a comprehensive AI image generation task management program with intelligent task planning, prompt optimization, billing management, and a minimalist black/white/gray UI.

## Tech Stack
- **Backend**: Python 3.14+ / FastAPI / SQLAlchemy (async) / aiosqlite
- **Frontend**: Vue3 + TypeScript + Pinia + Vue Router + Vite
- **Database**: SQLite (single file, encrypted sensitive data)
- **UI**: Lucide Icons, minimalist black/white/gray palette, no emoji
- **LLM Integration**: OpenAI-compatible API
- **Image Generation**: OpenAI-compatible API (/v1/images/generations)

## Architecture: Monolithic
- FastAPI serves both API and Vue3 static files
- Development: Vite dev server proxies to FastAPI
- Production: FastAPI hosts built Vue3 dist

## Data Models

### api_providers
- id (UUID PK), nickname, base_url, model_id, api_key_enc (AES-256-GCM)
- provider_type (image_gen / llm), billing_type (per_call / per_token)
- unit_price, currency, is_active, created_at, updated_at

### tasks
- id (UUID PK), title, description, status (planning/running/completed/failed/cancelled)
- provider_id (FK), llm_provider_id (FK), skill_id (FK nullable)
- image_count, reference_ids (JSON), created_at, updated_at

### sub_tasks
- id (UUID PK), task_id (FK), prompt, negative_prompt
- status (pending/running/completed/failed)
- result_urls (JSON), token_usage (JSON), cost, started_at, completed_at

### skills
- id (UUID PK), name, description, prompt_template, parameters (JSON)
- is_builtin, created_at

### rules
- id (UUID PK), name, rule_type (default_params/filter/workflow)
- config (JSON), is_active, priority, created_at

### billing_records
- id (UUID PK), task_id (FK), sub_task_id (FK), provider_id (FK)
- billing_type, tokens_in, tokens_out, cost, currency, detail (JSON), created_at

### reference_images
- id (UUID PK), name, file_path, file_type, file_size, thumbnail
- is_global, strength (0-1), crop_config (JSON), created_at

## UI Design
- **Color Palette**: Background #FAFAFA, Card #FFFFFF, Border #E5E5E5, Text #1A1A1A/#666666, Accent #000000
- **Layout**: Left nav (64px icons+text) + Main content + Top bar
- **Billing**: Top bar right side, one line "Month ¥xxx", click to expand detail drawer
- **No emoji**, Lucide linear SVG icons only
- **No card stacking**, tables for data, inline editing, side drawer forms
- **No dark theme** for now

## Core Workflows (All Optional Steps)

### Task Creation
1. User inputs image generation requirement
2. **Optional**: Enable LLM task planning -> decompose into sub-tasks + auto-generate prompts
3. **Optional**: Enable prompt optimization -> choose direction (detail/style/composition) -> LLM optimize -> compare
4. Set image count + reference images (optional)
5. Execute generation in parallel -> real-time progress -> results display
6. Auto-record billing

### Prompt Optimization Directions
- Detail Enhancement
- Style Unification
- Composition Optimization

### API Key Encryption
- AES-256-GCM symmetric encryption
- Key derived from machine fingerprint (MAC + hostname SHA-256)
- Base64 stored in SQLite
- API responses show only last 4 characters

## Key Decisions
- Monolithic architecture for simplicity
- SQLite for single-machine deployment
- OpenAI-compatible API for both LLM and image generation
- Optional task planning and prompt optimization
- Minimalist billing display in top bar
