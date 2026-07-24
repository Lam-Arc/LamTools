# LamImager Implementation Plan

> **Status: COMPLETED** (2026-05-06) - All 30 tasks implemented. See README.md and docs/ for current documentation.

> **For agentic workers:** Use executing-plans or subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Build a full-featured AI image generation task management program with LLM-powered task planning, prompt optimization, billing, skills/rules, and reference image management.

**Architecture:** Monolithic FastAPI backend serving Vue3 SPA frontend. SQLite for data persistence with AES-256-GCM encryption for sensitive data. Three-layer architecture: Router -> Service -> Model.

**Tech Stack:** Python 3.14+ / FastAPI / SQLAlchemy(async) / aiosqlite / Vue3 / TypeScript / Pinia / Vue Router / Vite / Lucide Icons

---

## Phase 1: Project Scaffolding

### Task 1: Initialize Backend Project

**Files:**
- `e:\LamImager\backend\app\__init__.py`
- `e:\LamImager\backend\app\config.py`
- `e:\LamImager\backend\app\database.py`
- `e:\LamImager\backend\app\main.py`
- `e:\LamImager\backend\requirements.txt`

**Steps:**
- [ ] Create directory structure: `backend/app/`, `backend/app/models/`, `backend/app/routers/`, `backend/app/services/`, `backend/app/schemas/`, `backend/app/utils/`
- [ ] Create `requirements.txt` with: fastapi, uvicorn, sqlalchemy[asyncio], aiosqlite, pydantic, python-multipart, aiohttp, cryptography, PyJWT, alembic
- [ ] Create `config.py` with Settings class using pydantic BaseSettings: DATA_DIR, DB_URL, ENCRYPTION_KEY derivation, CORS origins, API prefix
- [ ] Create `database.py` with async SQLAlchemy engine, async sessionmaker, Base declarative class, get_db dependency
- [ ] Create `main.py` with FastAPI app, CORS middleware, lifespan handler (init DB tables), health check endpoint
- [ ] Create all `__init__.py` files

**Verification:**
- [ ] Run `pip install -r requirements.txt` in backend dir
- [ ] Run `uvicorn app.main:app --reload` and verify health check returns 200

**Commit:** `feat: initialize backend project structure`

### Task 2: Initialize Frontend Project

**Files:**
- `e:\LamImager\frontend\package.json`
- `e:\LamImager\frontend\vite.config.ts`
- `e:\LamImager\frontend\tsconfig.json`
- `e:\LamImager\frontend\src\main.ts`
- `e:\LamImager\frontend\src\App.vue`
- `e:\LamImager\frontend\src\router\index.ts`
- `e:\LamImager\frontend\src\styles\global.css`

**Steps:**
- [ ] Run `npm create vite@latest frontend -- --template vue-ts` in LamImager root
- [ ] Install dependencies: `npm install vue-router@4 pinia axios lucide-vue-next`
- [ ] Configure `vite.config.ts` with proxy: `/api` -> `http://localhost:8000`
- [ ] Create global CSS with black/white/gray palette variables: --bg: #FAFAFA, --card: #FFFFFF, --border: #E5E5E5, --text: #1A1A1A, --text-secondary: #666666, --accent: #000000
- [ ] Create Vue Router with empty route placeholders for all pages
- [ ] Create Pinia store setup in main.ts
- [ ] Create App.vue with left nav layout (64px sidebar + main content area + top bar)

**Verification:**
- [ ] Run `npm run dev` and verify app loads with layout visible
- [ ] Verify proxy to backend works (health check)

**Commit:** `feat: initialize frontend project structure`

---

## Phase 2: Backend Core Utilities

### Task 3: Encryption Utility

**Files:**
- `e:\LamImager\backend\app\utils\crypto.py`

**Steps:**
- [ ] Implement `derive_key()` - derive AES key from machine fingerprint (MAC address + hostname -> SHA-256)
- [ ] Implement `encrypt(plaintext: str) -> str` - AES-256-GCM encrypt, return Base64 encoded nonce+ciphertext+tag
- [ ] Implement `decrypt(ciphertext: str) -> str` - AES-256-GCM decrypt from Base64
- [ ] Implement `mask_key(key: str) -> str` - return "****" + last 4 chars

**Verification:**
- [ ] Write and run a test script: encrypt a string, decrypt it, verify match; verify mask_key output

**Commit:** `feat: implement AES-256-GCM encryption utility`

### Task 4: LLM Client Utility

**Files:**
- `e:\LamImager\backend\app\utils\llm_client.py`

**Steps:**
- [ ] Implement `LLMClient` class with `__init__(base_url, api_key, model_id)`
- [ ] Implement `async chat(messages: list, temperature: float = 0.7) -> dict` - call OpenAI-compatible chat completions API
- [ ] Implement `async chat_stream(messages: list, temperature: float = 0.7) -> AsyncGenerator` - streaming chat
- [ ] Implement `async test_connection() -> bool` - simple test call to verify API connectivity
- [ ] Add proper error handling with custom exceptions: LLMConnectionError, LLMResponseError

**Verification:**
- [ ] Unit test with mock server or manual test with real API key

**Commit:** `feat: implement OpenAI-compatible LLM client`

### Task 5: Image Generation Client Utility

**Files:**
- `e:\LamImager\backend\app\utils\image_client.py`

**Steps:**
- [ ] Implement `ImageClient` class with `__init__(base_url, api_key, model_id)`
- [ ] Implement `async generate(prompt: str, negative_prompt: str = "", n: int = 1, size: str = "1024x1024", **kwargs) -> dict` - call /v1/images/generations
- [ ] Implement `async test_connection() -> bool` - verify API connectivity
- [ ] Add error handling: ImageGenError, ImageGenConnectionError

**Verification:**
- [ ] Unit test with mock or manual test

**Commit:** `feat: implement OpenAI-compatible image generation client`

---

## Phase 3: Database Models

### Task 6: Create All SQLAlchemy Models

**Files:**
- `e:\LamImager\backend\app\models\api_provider.py`
- `e:\LamImager\backend\app\models\task.py`
- `e:\LamImager\backend\app\models\skill.py`
- `e:\LamImager\backend\app\models\rule.py`
- `e:\LamImager\backend\app\models\billing.py`
- `e:\LamImager\backend\app\models\reference.py`
- `e:\LamImager\backend\app\models\__init__.py`

**Steps:**
- [ ] Create `api_provider.py` with ApiProvider model: id(UUID), nickname, base_url, model_id, api_key_enc, provider_type(Enum: image_gen/llm), billing_type(Enum: per_call/per_token), unit_price(Decimal), currency, is_active, created_at, updated_at
- [ ] Create `task.py` with Task model: id(UUID), title, description, status(Enum), provider_id(FK), llm_provider_id(FK), skill_id(FK nullable), image_count(int), reference_ids(JSON), created_at, updated_at; SubTask model: id(UUID), task_id(FK), prompt, negative_prompt, status(Enum), result_urls(JSON), token_usage(JSON), cost(Decimal), started_at, completed_at
- [ ] Create `skill.py` with Skill model: id(UUID), name, description, prompt_template, parameters(JSON), is_builtin, created_at
- [ ] Create `rule.py` with Rule model: id(UUID), name, rule_type(Enum: default_params/filter/workflow), config(JSON), is_active, priority(int), created_at
- [ ] Create `billing.py` with BillingRecord model: id(UUID), task_id(FK), sub_task_id(FK), provider_id(FK), billing_type(Enum), tokens_in(int), tokens_out(int), cost(Decimal), currency, detail(JSON), created_at
- [ ] Create `reference.py` with ReferenceImage model: id(UUID), name, file_path, file_type, file_size, thumbnail, is_global, strength(float), crop_config(JSON), created_at
- [ ] Create `__init__.py` importing all models

**Verification:**
- [ ] Start app, verify tables are created in SQLite file
- [ ] Check table schemas match design

**Commit:** `feat: create all SQLAlchemy data models`

### Task 7: Create Pydantic Schemas

**Files:**
- `e:\LamImager\backend\app\schemas\api_provider.py`
- `e:\LamImager\backend\app\schemas\task.py`
- `e:\LamImager\backend\app\schemas\skill.py`
- `e:\LamImager\backend\app\schemas\rule.py`
- `e:\LamImager\backend\app\schemas\billing.py`
- `e:\LamImager\backend\app\schemas\reference.py`
- `e:\LamImager\backend\app\schemas\__init__.py`

**Steps:**
- [ ] For each model, create Create/Update/Response schemas with proper typing
- [ ] ApiProvider schemas: mask api_key in response (show only last 4 chars), include test_connection result field
- [ ] Task schemas: include sub_tasks list in response, status enum validation
- [ ] Billing schemas: include aggregated summary schema (daily/monthly totals)
- [ ] All schemas use UUID as str, datetime as ISO format

**Verification:**
- [ ] Import all schemas, verify no import errors
- [ ] Test schema validation with sample data

**Commit:** `feat: create all Pydantic request/response schemas`

---

## Phase 4: API Provider Management

### Task 8: API Provider Backend

**Files:**
- `e:\LamImager\backend\app\routers\api_provider.py`
- `e:\LamImager\backend\app\services\api_manager.py`

**Steps:**
- [ ] Create `api_manager.py` service with methods: create_provider, update_provider, delete_provider, get_provider, list_providers, test_connection
- [ ] Encrypt api_key on create/update using crypto utility, decrypt on test_connection
- [ ] Create router with endpoints: POST /api/providers, GET /api/providers, GET /api/providers/{id}, PUT /api/providers/{id}, DELETE /api/providers/{id}, POST /api/providers/{id}/test
- [ ] Test connection endpoint: decrypt key, create LLMClient or ImageClient based on provider_type, call test_connection()

**Verification:**
- [ ] Create provider via API, verify encrypted key in DB
- [ ] List providers, verify key is masked
- [ ] Test connection with real or mock API

**Commit:** `feat: implement API provider management backend`

### Task 9: API Provider Frontend

**Files:**
- `e:\LamImager\frontend\src\views\ApiManage.vue`
- `e:\LamImager\frontend\src\components\ApiProviderDrawer.vue`
- `e:\LamImager\frontend\src\stores\apiProvider.ts`
- `e:\LamImager\frontend\src\api\apiProvider.ts`
- `e:\LamImager\frontend\src\types\apiProvider.ts`

**Steps:**
- [ ] Create TypeScript types matching backend schemas
- [ ] Create API client module with axios calls to all provider endpoints
- [ ] Create Pinia store for provider state management
- [ ] Create ApiManage.vue: table listing all providers (nickname, type, model_id, status, actions), add button in top bar
- [ ] Create ApiProviderDrawer.vue: side drawer form for create/edit with fields: nickname, base_url, model_id, api_key, provider_type dropdown, billing_type dropdown, unit_price, test connection button with status indicator

**Verification:**
- [ ] Navigate to /api-manage, see empty table
- [ ] Add a provider, verify it appears in table
- [ ] Edit provider, verify changes persist
- [ ] Test connection, see result

**Commit:** `feat: implement API provider management frontend`

---

## Phase 5: Task Management Core

### Task 10: Task Backend

**Files:**
- `e:\LamImager\backend\app\routers\task.py`
- `e:\LamImager\backend\app\services\task_executor.py`

**Steps:**
- [ ] Create `task_executor.py` service: create_task, update_task, delete_task, get_task, list_tasks, cancel_task
- [ ] Implement `execute_sub_task(sub_task, provider)` - call ImageClient.generate(), save result_urls, record billing
- [ ] Implement `execute_task(task)` - gather all pending sub_tasks, execute with asyncio.gather (configurable concurrency), update task status
- [ ] Create router: POST /api/tasks, GET /api/tasks, GET /api/tasks/{id}, PUT /api/tasks/{id}, DELETE /api/tasks/{id}, POST /api/tasks/{id}/cancel, POST /api/tasks/{id}/execute
- [ ] Add WebSocket endpoint /ws/tasks/{id} for real-time progress updates

**Verification:**
- [ ] Create task via API, verify in DB
- [ ] Execute task with mock provider, verify sub_tasks complete
- [ ] Connect WebSocket, verify progress updates

**Commit:** `feat: implement task management backend with parallel execution`

### Task 11: Task Frontend

**Files:**
- `e:\LamImager\frontend\src\views\TaskList.vue`
- `e:\LamImager\frontend\src\views\TaskDetail.vue`
- `e:\LamImager\frontend\src\components\TaskCreateDrawer.vue`
- `e:\LamImager\frontend\src\components\SubTaskProgress.vue`
- `e:\LamImager\frontend\src\stores\task.ts`
- `e:\LamImager\frontend\src\api\task.ts`
- `e:\LamImager\frontend\src\types\task.ts`

**Steps:**
- [ ] Create TypeScript types for Task, SubTask, TaskStatus
- [ ] Create API client module for task endpoints
- [ ] Create Pinia store with WebSocket connection for real-time updates
- [ ] Create TaskList.vue: table with title, status, provider, image_count, created_at, actions; status filter; create button
- [ ] Create TaskCreateDrawer.vue: form with title, description, provider selection, image_count input, prompt textarea, negative_prompt textarea, reference image selector, optional LLM planning toggle, optional prompt optimization toggle
- [ ] Create TaskDetail.vue: task info header, sub_task list with progress bars, result image grid, billing summary
- [ ] Create SubTaskProgress.vue: progress bar + status indicator for each sub_task

**Verification:**
- [ ] Create task from UI, verify it appears in list
- [ ] Open task detail, see sub_tasks
- [ ] Execute task, see real-time progress
- [ ] View generated images in result grid

**Commit:** `feat: implement task management frontend`

---

## Phase 6: LLM Task Planning

### Task 12: Task Planner Service

**Files:**
- `e:\LamImager\backend\app\services\task_planner.py`

**Steps:**
- [ ] Implement `plan_task(description: str, llm_provider: ApiProvider, skill: Skill = None, rules: list[Rule] = None) -> list[SubTaskCreate]`
- [ ] Build system prompt for task decomposition: instruct LLM to analyze the image generation requirement and output JSON with sub_tasks array, each containing prompt, negative_prompt
- [ ] Include skill prompt_template in system prompt if skill is provided
- [ ] Apply rule filters (default_params, filter) to the planning context
- [ ] Parse LLM response JSON, validate structure, return sub_task list
- [ ] Add endpoint POST /api/tasks/plan - accepts description + llm_provider_id + optional skill_id, returns planned sub_tasks

**Verification:**
- [ ] Call plan endpoint with sample description, verify sub_tasks returned
- [ ] Verify skill template is applied when provided
- [ ] Verify rules are applied when active

**Commit:** `feat: implement LLM-powered task planning service`

### Task 13: Task Planner Frontend

**Files:**
- `e:\LamImager\frontend\src\components\TaskPlanner.vue`

**Steps:**
- [ ] Create TaskPlanner.vue component: description textarea, LLM provider dropdown, skill dropdown (optional), "Plan" button
- [ ] On plan click: call /api/tasks/plan, display returned sub_tasks in editable list
- [ ] Each sub_task row: prompt textarea (editable), negative_prompt textarea (editable), delete button
- [ ] Allow adding manual sub_tasks to the planned list
- [ ] "Confirm & Execute" button to create task with planned sub_tasks

**Verification:**
- [ ] Enter description, select LLM provider, click Plan
- [ ] Verify sub_tasks appear and are editable
- [ ] Confirm and execute, verify task runs

**Commit:** `feat: implement task planner frontend component`

---

## Phase 7: Prompt Optimization

### Task 14: Prompt Optimizer Service

**Files:**
- `e:\LamImager\backend\app\services\prompt_optimizer.py`
- `e:\LamImager\backend\app\routers\prompt.py`

**Steps:**
- [ ] Implement `optimize_prompt(prompt: str, direction: str, llm_provider: ApiProvider) -> OptimizedPrompt`
- [ ] Define optimization directions as enum: detail_enhancement, style_unification, composition_optimization
- [ ] Build direction-specific system prompts:
  - detail_enhancement: "Enhance the prompt with more specific visual details, textures, lighting..."
  - style_unification: "Refine the prompt for consistent artistic style, color harmony..."
  - composition_optimization: "Optimize the prompt for better composition, framing, focal point..."
- [ ] Call LLM with system prompt + user prompt, parse optimized result
- [ ] Create router: POST /api/prompt/optimize - accepts prompt, direction, llm_provider_id; returns original + optimized prompt
- [ ] Add billing record for LLM usage

**Verification:**
- [ ] Call optimize endpoint with each direction, verify optimized prompt returned
- [ ] Verify billing record created

**Commit:** `feat: implement prompt optimization service`

### Task 15: Prompt Optimizer Frontend

**Files:**
- `e:\LamImager\frontend\src\components\PromptOptimizer.vue`
- `e:\LamImager\frontend\src\api\prompt.ts`

**Steps:**
- [ ] Create PromptOptimizer.vue: prompt textarea, direction selector (3 radio buttons), LLM provider dropdown, "Optimize" button
- [ ] Display result: side-by-side comparison of original vs optimized prompt
- [ ] "Use Optimized" / "Use Original" buttons to select which to apply
- [ ] Manual edit field for fine-tuning the selected prompt
- [ ] Integrate into TaskCreateDrawer as optional step

**Verification:**
- [ ] Enter prompt, select direction, click Optimize
- [ ] Verify side-by-side comparison displays
- [ ] Select optimized, verify it populates the task prompt field

**Commit:** `feat: implement prompt optimizer frontend component`

---

## Phase 8: Skill & Rule System

### Task 16: Skill Backend

**Files:**
- `e:\LamImager\backend\app\routers\skill.py`
- `e:\LamImager\backend\app\services\skill_engine.py`

**Steps:**
- [ ] Create `skill_engine.py` service: create_skill, update_skill, delete_skill, get_skill, list_skills, import_skill (from JSON)
- [ ] Create router: CRUD endpoints + POST /api/skills/import (accept JSON file upload)
- [ ] Add seed data for 2-3 built-in skills (e.g., "Photography", "Anime Style", "Product Shot")
- [ ] Implement `apply_skill(prompt: str, skill: Skill, params: dict) -> str` - merge prompt with skill template and params

**Verification:**
- [ ] CRUD operations work via API
- [ ] Import skill from JSON works
- [ ] Apply skill transforms prompt correctly

**Commit:** `feat: implement skill management backend`

### Task 17: Skill Frontend

**Files:**
- `e:\LamImager\frontend\src\views\SkillManage.vue`
- `e:\LamImager\frontend\src\components\SkillEditor.vue`
- `e:\LamImager\frontend\src\stores\skill.ts`
- `e:\LamImager\frontend\src\api\skill.ts`
- `e:\LamImager\frontend\src\types\skill.ts`

**Steps:**
- [ ] Create TypeScript types for Skill
- [ ] Create API client and Pinia store
- [ ] Create SkillManage.vue: table listing skills (name, type built-in/custom, description, actions), import button, create button
- [ ] Create SkillEditor.vue: side drawer form with name, description, prompt_template (with variable placeholders like {{variable}}), parameters JSON editor, preview section showing how template renders with sample params

**Verification:**
- [ ] View built-in skills in table
- [ ] Create custom skill, verify it appears
- [ ] Edit skill template, verify preview renders

**Commit:** `feat: implement skill management frontend`

### Task 18: Rule Backend

**Files:**
- `e:\LamImager\backend\app\routers\rule.py`
- `e:\LamImager\backend\app\services\rule_engine.py`

**Steps:**
- [ ] Create `rule_engine.py` service: create_rule, update_rule, delete_rule, get_rule, list_rules, toggle_rule
- [ ] Implement `apply_rules(context: dict, rules: list[Rule]) -> dict` - apply active rules in priority order to modify task parameters
- [ ] rule_type behaviors: default_params -> merge default values into task config; filter -> filter/modify prompts; workflow -> add processing steps
- [ ] Create router: CRUD endpoints + PUT /api/rules/{id}/toggle

**Verification:**
- [ ] CRUD operations work
- [ ] Apply rules modifies context correctly

**Commit:** `feat: implement rule management backend`

### Task 19: Rule Frontend

**Files:**
- `e:\LamImager\frontend\src\views\RuleManage.vue`
- `e:\LamImager\frontend\src\components\RuleEditor.vue`
- `e:\LamImager\frontend\src\stores\rule.ts`
- `e:\LamImager\frontend\src\api\rule.ts`
- `e:\LamImager\frontend\src\types\rule.ts`

**Steps:**
- [ ] Create TypeScript types for Rule
- [ ] Create API client and Pinia store
- [ ] Create RuleManage.vue: table with name, type, active status toggle, priority, actions
- [ ] Create RuleEditor.vue: side drawer form with name, rule_type dropdown, config JSON editor, priority input, is_active toggle

**Verification:**
- [ ] Create rule, verify it appears in table
- [ ] Toggle active status, verify state persists
- [ ] Edit rule config, verify changes save

**Commit:** `feat: implement rule management frontend`

---

## Phase 9: Billing System

### Task 20: Billing Backend

**Files:**
- `e:\LamImager\backend\app\routers\billing.py`
- `e:\LamImager\backend\app\services\billing_service.py`

**Steps:**
- [ ] Create `billing_service.py`: record_billing, get_billing_summary, get_billing_details, export_billing
- [ ] Implement `record_billing(task_id, sub_task_id, provider_id, usage_data)` - called automatically after each API call
- [ ] Implement `get_summary(period: str)` - aggregate billing by day/month, return {today, month, total}
- [ ] Implement `get_details(filters)` - paginated billing records with filters (date range, provider, task)
- [ ] Implement `export_billing(format: str, filters)` - export to CSV
- [ ] Create router: GET /api/billing/summary, GET /api/billing/details, GET /api/billing/export

**Verification:**
- [ ] Execute a task, verify billing record created
- [ ] Get summary, verify totals correct
- [ ] Export CSV, verify format

**Commit:** `feat: implement billing management backend`

### Task 21: Billing Frontend

**Files:**
- `e:\LamImager\frontend\src\components\BillingSummary.vue`
- `e:\LamImager\frontend\src\components\BillingDrawer.vue`
- `e:\LamImager\frontend\src\stores\billing.ts`
- `e:\LamImager\frontend\src\api\billing.ts`
- `e:\LamImager\frontend\src\types\billing.ts`

**Steps:**
- [ ] Create TypeScript types for BillingRecord, BillingSummary
- [ ] Create API client and Pinia store
- [ ] Create BillingSummary.vue: single line text "本月 ¥{amount}" displayed in top bar, clickable
- [ ] Create BillingDrawer.vue: right drawer with summary stats (today/month/total), detail table (date, task, provider, tokens, cost), date range filter, export button
- [ ] Integrate BillingSummary into App.vue top bar

**Verification:**
- [ ] Top bar shows billing amount
- [ ] Click amount, drawer opens with details
- [ ] Filter by date range works
- [ ] Export CSV downloads file

**Commit:** `feat: implement billing frontend components`

---

## Phase 10: Reference Image & File Upload

### Task 22: File Upload Backend

**Files:**
- `e:\LamImager\backend\app\routers\upload.py`
- `e:\LamImager\backend\app\services\file_service.py`

**Steps:**
- [ ] Create `file_service.py`: save_upload, get_file, delete_file, create_thumbnail
- [ ] Support formats: JPG, PNG, GIF, WEBP, TXT, MD, JSON
- [ ] Save files to data/uploads/ with UUID filenames, create thumbnails for images
- [ ] Create router: POST /api/upload (multipart), GET /api/files/{id}, DELETE /api/files/{id}
- [ ] Return file metadata including thumbnail URL

**Verification:**
- [ ] Upload image file, verify saved and thumbnail created
- [ ] Upload text file, verify saved
- [ ] Get file returns correct data

**Commit:** `feat: implement file upload backend`

### Task 23: Reference Image Backend

**Files:**
- `e:\LamImager\backend\app\routers\reference.py`
- `e:\LamImager\backend\app\services\reference_manager.py`

**Steps:**
- [ ] Create `reference_manager.py`: add_reference, update_reference, delete_reference, list_references, set_global, update_strength, update_crop
- [ ] Create router: CRUD endpoints + PUT /api/references/{id}/global, PUT /api/references/{id}/strength, PUT /api/references/{id}/crop
- [ ] Global references: mark is_global=True, auto-include in all tasks
- [ ] Strength: 0.0-1.0 float controlling reference image influence
- [ ] Crop: store crop_config {x, y, width, height} for image cropping

**Verification:**
- [ ] Upload and create reference image
- [ ] Set as global, verify flag
- [ ] Update strength and crop config

**Commit:** `feat: implement reference image management backend`

### Task 24: Reference Image & Upload Frontend

**Files:**
- `e:\LamImager\frontend\src\views\ReferenceManage.vue`
- `e:\LamImager\frontend\src\components\ImageUploader.vue`
- `e:\LamImager\frontend\src\components\ReferenceCard.vue`
- `e:\LamImager\frontend\src\components\CropDialog.vue`
- `e:\LamImager\frontend\src\stores\reference.ts`
- `e:\LamImager\frontend\src\api\reference.ts`
- `e:\LamImager\frontend\src\types\reference.ts`

**Steps:**
- [ ] Create TypeScript types for ReferenceImage
- [ ] Create API client and Pinia store
- [ ] Create ImageUploader.vue: drag-and-drop zone, click to browse, preview thumbnails, progress indicator
- [ ] Create ReferenceManage.vue: grid of reference images, global badge, upload button
- [ ] Create ReferenceCard.vue: thumbnail, name, global toggle, strength slider, crop button, delete button
- [ ] Create CropDialog.vue: modal with image and draggable crop area, confirm/cancel
- [ ] Integrate reference selector into TaskCreateDrawer

**Verification:**
- [ ] Upload image via drag-and-drop
- [ ] Set reference as global
- [ ] Adjust strength slider
- [ ] Crop image
- [ ] Select reference in task creation

**Commit:** `feat: implement reference image and upload frontend`

---

## Phase 11: Dashboard & Polish

### Task 25: Dashboard Page

**Files:**
- `e:\LamImager\frontend\src\views\Dashboard.vue`
- `e:\LamImager\backend\app\routers\dashboard.py`

**Steps:**
- [ ] Create backend endpoint GET /api/dashboard/stats returning: total_tasks, running_tasks, completed_tasks, total_images, monthly_cost
- [ ] Create Dashboard.vue: minimal stats display (numbers only, no cards), recent tasks table, quick action buttons (New Task, Manage APIs)
- [ ] Keep it simple - just numbers and a recent tasks list

**Verification:**
- [ ] Dashboard loads with stats
- [ ] Recent tasks display correctly

**Commit:** `feat: implement dashboard page`

### Task 26: Settings Page

**Files:**
- `e:\LamImager\frontend\src\views\Settings.vue`
- `e:\LamImager\backend\app\routers\settings.py`

**Steps:**
- [ ] Create backend settings endpoint: GET/PUT /api/settings for app-level config (data dir, max concurrent tasks, default image size, etc.)
- [ ] Create Settings.vue: form with max concurrent tasks slider, default image size dropdown, data management (clear cache, export data)

**Verification:**
- [ ] Load settings, verify values
- [ ] Change setting, verify persistence

**Commit:** `feat: implement settings page`

### Task 27: Global Layout & Navigation Polish

**Files:**
- `e:\LamImager\frontend\src\App.vue`
- `e:\LamImager\frontend\src\components\SideNav.vue`
- `e:\LamImager\frontend\src\components\TopBar.vue`

**Steps:**
- [ ] Create SideNav.vue: vertical nav with icon + text for each page (Dashboard, Tasks, APIs, Skills, Rules, References, Settings), active state highlighting
- [ ] Create TopBar.vue: page title on left, billing summary on right
- [ ] Refine App.vue layout: fixed sidebar + top bar + scrollable content area
- [ ] Add responsive behavior: collapse sidebar to icon-only on narrow screens
- [ ] Add transition animations for page changes

**Verification:**
- [ ] Navigate between all pages
- [ ] Active nav item highlights correctly
- [ ] Billing amount shows in top bar
- [ ] Layout works on different screen widths

**Commit:** `feat: polish global layout and navigation`

### Task 28: Error Handling & Logging

**Files:**
- `e:\LamImager\backend\app\utils\logger.py`
- `e:\LamImager\backend\app\middleware\error_handler.py`
- `e:\LamImager\frontend\src\utils\errorHandler.ts`
- `e:\LamImager\frontend\src\components\ToastNotification.vue`

**Steps:**
- [ ] Create structured logger with file + console output, rotation
- [ ] Create FastAPI exception handler middleware: catch all exceptions, return consistent error response format {error: str, detail: str, code: str}
- [ ] Create frontend axios interceptor: catch HTTP errors, show toast notification
- [ ] Create ToastNotification.vue: simple top-right notification, auto-dismiss after 3s, black/white style
- [ ] Add operation logging for key actions (API create/delete, task create/execute, billing events)

**Verification:**
- [ ] Trigger backend error, verify consistent error response
- [ ] Trigger frontend error, verify toast appears
- [ ] Check log file for operation entries

**Commit:** `feat: implement error handling and logging`

---

## Phase 12: Integration & Final Polish

### Task 29: End-to-End Integration

**Files:**
- Various files across frontend and backend

**Steps:**
- [ ] Wire up complete task creation flow: create task -> optional plan -> optional optimize -> set references -> execute -> view results
- [ ] Verify billing records created for all API calls (LLM + image generation)
- [ ] Verify WebSocket progress updates work end-to-end
- [ ] Verify skill and rule application in task flow
- [ ] Test batch image generation with multiple images per sub_task
- [ ] Test result image display, selection, and download

**Verification:**
- [ ] Complete full workflow from task creation to result viewing
- [ ] All modules work together without errors

**Commit:** `feat: end-to-end integration testing and fixes`

### Task 30: Production Build Configuration

**Files:**
- `e:\LamImager\backend\app\main.py`
- `e:\LamImager\frontend\vite.config.ts`
- `e:\LamImager\start.py`

**Steps:**
- [ ] Configure FastAPI to serve Vue3 built static files from frontend/dist
- [ ] Configure Vite build output to backend/static or use separate path
- [ ] Create start.py script: build frontend, then start uvicorn
- [ ] Add proper CORS configuration for production
- [ ] Test production build: build frontend, start backend, verify SPA routing works

**Verification:**
- [ ] Run start.py, access app in browser
- [ ] All routes work (no 404 on refresh)
- [ ] API calls work in production mode

**Commit:** `feat: configure production build and deployment`
