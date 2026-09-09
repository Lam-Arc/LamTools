# Project Structure

LamTools is a multi-surface repository whose active product is Core. Stable
ownership and integration boundaries are summarized here; generated files and
feature-level inventories belong in their module documentation.

## Directory Layout

- `core/`: active Core product. Python backend is under
  `core/src/lamtools_core/`; shared Vue/TypeScript UI is under `core/ui/`;
  the Tauri desktop shell is under `core/desktop/`.
- `core/mobile/` is the mobile client surface; `core/remote/relay/` contains
  the opaque relay surface. `core/tests/`, `core/ui/tests/`, `core/config/`,
  `core/docs/`, `core/skills/`, and `core/templates/` support Core.
- `website/`: independent Vue/Vite website. Its showcase imports real
  components and types from `core/ui`.
- `archive/members/`: archived Writer, Sage, and Imager products kept for
  historical reference; they are not the current product target.
- `docs/`, `scripts/`, and `.github/workflows/` contain repository-level
  documentation, maintenance/build scripts, and CI/release workflows.
- `data/core.db` is the documented Core session/runtime data location.

## Modules and Responsibilities

- `lamtools_core.app` assembles the FastAPI application, persistence,
  sessions, live operations, plugins, and runtime services.
- `kernel`, `llm`, `tool`, `runtime`, `session`, `config`, `plugins`, `member`,
  `mcp`, `mem`, `attachment`, `artifact`, `export`, and `update` provide the
  Core execution, model, tool, durable-runtime, configuration, extension,
  content, export, and update domains.
- `core/ui/src` exposes the shared `LamToolsApp`, Workbench, workspace shell,
  session/chat/composer components, runtime/settings/project/plugin surfaces,
  transport helpers, and shared types through `core/ui/src/index.ts`.
- `core/desktop/src-tauri` owns native Tauri commands, window management,
  packaging, and the authenticated RemoteGateway; `core/desktop/src` boots
  the shared UI with DirectTransport and bridges native commands.
- `core/mobile/src` owns only the mobile host lifecycle, pairing/trusted-device
  flow, native capabilities, route selection, secure wire, and
  RemoteTransport. Its APP screen mounts the shared `LamToolsApp`.
- `core/remote/relay` authenticates desktop/mobile tunnel presence and forwards
  opaque encrypted frames; it has no Core session or message model.

## Main Interfaces and Integration Boundaries

- `lamtools_core.app.factory.create_app` creates the FastAPI app; Core routes
  are mounted below `/api/core` and member routes below `/api/{member_id}`.
- The live Core app-server is a WebSocket endpoint at
  `/api/core/app-server` using the `core.app_server.v1` JSON-RPC/event
  protocol. REST endpoints cover health, sessions, configuration, projects,
  attachments, plugins, and related operations.
- In Tauri, Rust publishes a dynamically selected loopback backend URL through
  `get_api_base`; the desktop bootstrap constructs DirectTransport and passes
  the resulting runtime to the shared UI.
- Mobile pairing provisions a trusted device and RemoteTransport credentials;
  Workbench RPC/HTTP requests and Core events then use the same encrypted
  tunnel regardless of whether ConnectionManager selected LAN or Relay.
- The desktop Vite dev URL is `http://127.0.0.1:5173`; the Core backend CLI
  can serve independently through Uvicorn.

## Tests and Supporting Assets

- Python tests live in `core/tests/` and are configured by `core/pyproject.toml`.
- UI contract/unit tests live in `core/ui/tests/` and run through Vitest.
- Desktop pet logic has a Node test script; native Rust tests are colocated
  with the Tauri source. End-to-end material is under `e2e/`.
