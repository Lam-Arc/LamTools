# LamImager

AI Image Generation Manager — a full-stack desktop application for AI-powered image generation with conversation-based UI, LLM planning, and real-time streaming.

## Quick Start
Pre-built executables are available on the [Release](https://github.com/Laaaaaaaam/LamImager/releases) page. Download, extract, and run the `.exe`.

## Usage Guide

### 1. Configure API

Open the **API Manage** page. Providers are organized in two levels: **Vendor → Model**.

- **Add Vendor**: enter name, base URL, and API key. One key per vendor, shared by all models underneath.
- **Add Model**: expand a vendor, click "Add Model", enter model ID, type (LLM / Image Gen / Web Search), and pricing.

> Example: vendor `OpenAI` with base URL `https://api.openai.com`, key entered once, hosting `gpt-4o` (LLM) and `dall-e-3` (Image Gen) models.

Finally, go to **Settings** to set default models for prompt optimization, image generation, and task planning.

### 2. Session Generation

Select or create a session on the left, type a prompt in the center input, and press Enter.

- **Reference Images**: drag or paste images for img2img input
- **Refine Mode**: click "Refine" on a generated image to re-generate based on it
- **Context Images**: last 4 images auto-populate; right-click to pin/remove

### 3. Agent Mode

Enable the **"Smart"** toggle next to the input field. The system auto-detects your intent:

| Input | Type | Effect |
|-------|------|--------|
| "a cat" | Single | Direct generation |
| "3 cats, different styles" | Parallel | Multiple images at once |
| "sketch first, then refine" | Iterative | Step-by-step refinement |
| "a set of 6 emojis" | Radiate | Grid anchor → per-item expansion |

### 4. Sidebar Assistant

Open the **Dialog** tab in the right sidebar to chat freely with the LLM.

- **Web Search**: toggle the search switch to let the assistant query the web before responding
- **Response Style**: Default / Verbose / Concise
- **Context Mode** (gear settings): share session history / input only
- **Memory Mode** (gear settings): persist across windows / clear with session

### 5. Skills & Rules

- **Skills**: create reusable prompt templates in the Skills page. Use `{prompt}` as the user-input placeholder with optional custom parameters.
- **Rules**: configure global filters (e.g., auto-append negative prompt "blurry, low quality") and default params in the Rules page.

### 6. Plan Templates

Create multi-step generation templates in the Plan Templates page. Supports three strategies: `parallel`, `iterative`, `radiate`.

- Templates can include variables such as `{{subject}}` and `{{style}}`
- The Plan tab in the chat input area lets you select a template and fill in variable values
- AI-assisted creation: describe your workflow in natural language and let the LLM build the template

---

## Features

**Core Workflow**
- Conversation-based chat interface with session management
- Upload reference images (base64) for img2img generation
- Refine mode: selectively re-generate from generated images
- Context image auto-population with pin/remove support

**AI Assistance**
- LLM sidebar assistant for prompt optimization and planning
- Prompt optimization via 5 directions + custom, streamed via SSE
- Plan templates with variable substitution and AI-assisted generation
- Plan strategy support during session generation

**Real-time Streaming**
- SSE (Server-Sent Events) for live task status across all sessions
- Token-by-token streaming for LLM chat, optimization, and planning
- Multi-session concurrency: generate/optimize/plan across sessions simultaneously

**Management**
- API provider management with encrypted keys (AES-256-GCM)
- Skill system: reusable prompt templates with parameters
- Rule engine: global filters and default parameters
- Billing tracking: per-call and per-token cost tracking with CSV export
- Dashboard with session/image/generation stats

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3.14+ / FastAPI / SQLAlchemy (async) / aiosqlite |
| Frontend | Vue3 / TypeScript / Pinia / Vue Router / Vite |
| Desktop | PyInstaller + pywebview (Windows) |
| Database | SQLite (single file) |
| UI | Lucide Icons, BW-gray palette |

## Quick Start

### Prerequisites

- Python 3.14+
- Node.js 18+

### Development

```bash
# Backend
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Frontend (in another terminal)
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173` — the Vite dev server proxies `/api` to the backend.

### Production

```bash
cd frontend && npm run build
cd ../backend && uvicorn app.main:app --host 0.0.0.0 --port 8000
```

FastAPI serves the built frontend at the root path.

### Desktop App

```bash
python build.py
```

This packages the entire app into a standalone Windows executable via PyInstaller + pywebview. Output: `dist/LamImager/`.

## Project Structure

```
LamImager/
├── backend/
│   └── app/
│       ├── main.py              # FastAPI entry point
│       ├── config.py            # Settings (DATA_DIR, DB_URL, CORS)
│       ├── database.py          # Async SQLAlchemy setup
│       ├── models/              # SQLAlchemy models (10 tables)
│       ├── routers/             # FastAPI routers (11 modules)
│       ├── services/            # Business logic (17 services)
│       │   └── executors/       # 4 strategy executors (single, parallel, iterative, radiate)
│       ├── schemas/             # Pydantic request/response models
│       └── utils/               # crypto, llm_client, image_client
├── frontend/
│   └── src/
│       ├── views/               # 8 page components (Sessions.vue is main)
│       ├── api/                 # Axios API clients (12 modules)
│       ├── stores/              # Pinia stores (provider, billing, session)
│       ├── composables/         # Reusable composables (useSessionEvents, useDialog, useMarkdown, useDownload)
│       └── types/               # TypeScript interfaces
├── desktop/                     # Desktop app (PyInstaller + pywebview)
├── docs/                        # Architecture, API reference, runbook
│   ├── api-reference.md
│   ├── architecture.md
│   └── runbook.md
└── data/                        # Runtime data (SQLite, uploads)
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `DEBUG` | `true` | Enable debug mode |
| `DEFAULT_IMAGE_SIZE` | `1024x1024` | Default image dimensions |
| `LAMIMAGER_DATA_DIR` | `<project>/data` | Override runtime data directory |
| `LAMIMAGER_STATIC_DIR` | `<project>/frontend/dist` | Override frontend static files directory |

## Documentation

- [API Reference](docs/api-reference.md) — full API documentation
- [Architecture](docs/architecture.md) — data model, workflows, tiers
- [Runbook](docs/runbook.md) — deployment and troubleshooting

## Author

霖二 [@Laaaaaaaam](https://github.com/Laaaaaaaam)

## License

MIT
