# Project Structure

LamTools is a multi-surface repository whose active product is Core. Stable
ownership and integration boundaries are summarized here; generated files and
feature-level inventories belong in their module documentation.

## Directory Layout

- `core/`: active Core product. Python backend is under
  `core/src/lamtools_core/`; shared Vue/TypeScript UI is under `core/ui/`;
  the Tauri desktop shell is under `core/desktop/`.
- `core/ui/src/right-sidebar/` contains the right-rail module contracts and
  `core/ui/src/components/RightSidebar*.vue` contains the host, module frame,
  layout editor, widget renderer, and built-in Runtime/Web Search/RAG surfaces.
- `core/mobile/` is the mobile client surface. `core/mobile/src-tauri/` owns
  the in-progress Tauri mobile host and native runtime bridge; `core/runtime-rs/`
  contains the partial Rust runtime migration. `core/remote/relay/` contains
  the opaque relay surface. `core/tests/`, `core/ui/tests/`, `core/config/`,
  `core/docs/`, `core/skills/`, and `core/templates/` support Core.
- `website/`: independent Vue/Vite website. Its showcase imports real
  components and types from `core/ui`.
- `archive/members/`: archived Writer, Sage, and Imager products kept for
  historical reference; they are not the current product target.
- `docs/`, `scripts/`, and `.github/workflows/` contain repository-level
  documentation, maintenance/build scripts, and CI/release workflows.
- `data/core.db` is the documented Core session/runtime data location.
- `scripts/package-linux.sh` is the Linux-native distribution entry point. It
  stages the source and toolchain in an E-backed WSL2 filesystem, builds the
  Linux PyInstaller sidecar and Tauri bundles, and validates packaged startup.
  Generated Linux artifacts are written under
  `core/desktop/src-tauri/target/release/bundle/`; the standalone sidecar
  verification copy is `artifacts/linux-x64/sidecar/LamCore`.

## Modules and Responsibilities

- `lamtools_core.app` assembles the FastAPI application, persistence,
  sessions, live operations, plugins, and runtime services.
- `kernel`, `llm`, `tool`, `runtime`, `session`, `config`, `plugins`, `member`,
  `mcp`, `mem`, `attachment`, `artifact`, `export`, and `update` provide the
  Core execution, model, tool, durable-runtime, configuration, extension,
  content, export, and update domains.
- `lamtools_core.config.model_store` and `provider_store` own separate
  file-backed model/provider records under the unified JSONC root;
  `model_group_store` owns `model_groups.jsonc` and ordered many-to-many model
  memberships. `config.operations` exposes their RPC catalog and performs
  model-record/provider validation and rollback for composite creation.
- `core/src/lamtools_core/plugins/bundled/workflow/backend/` owns the Workflow
  registry and schemas, V2 document/compiler/adapters, durable runtime, queue,
  event history, snapshots, cache, activations, expression evaluator, and
  DataPacket/credential/capability contracts. Its UI sibling owns the dynamic
  node catalog, schema editor, canvas, run/queue/resource panels, and trigger
  surface.
- `lamtools_core.plugins` owns widget manifests, validation, scoped operation
  dispatch, and the `plugin.widget.*` RPCs; the bundled Web Search plugin owns
  its snapshot/health operations. The CLI mirrors widget list/show/action
  access.
- `core/ui/src` exposes the shared `LamToolsApp`, Workbench, workspace shell,
  session/chat/composer components, runtime/settings/project/plugin surfaces,
  transport helpers, and shared types through `core/ui/src/index.ts`.
- `core/ui/src/components/CoreModelCatalogViewToggle.vue` is shared by the
  main model picker and `CoreSettings`' 模型与供应商 catalog. `LamToolsApp`
  loads model groups and the persisted `core.modelCatalog.classification`
  setting, then routes group/provider changes through config RPCs.
- `core/desktop/src-tauri` owns native Tauri commands, window management,
  packaging, and the authenticated RemoteGateway; `core/desktop/src` boots
  the shared UI with DirectTransport and bridges native commands.
- `core/mobile/src` owns only the mobile host lifecycle, pairing/trusted-device
  flow, native capabilities, route selection, secure wire, and mobile UI
  integration. The Tauri host under `core/mobile/src-tauri/` provides native
  runtime commands; migration of the Study, model, and Workflow internal
  runners remains partial. Stop and snapshot recovery are implemented, while
  phone visual confirmation of sidebar and system inset fixes is pending.
- `core/remote/relay` authenticates desktop/mobile tunnel presence and forwards
  opaque encrypted frames; it has no Core session or message model.

## Main Interfaces and Integration Boundaries

- `lamtools_core.app.factory.create_app` creates the FastAPI app; Core routes
  are mounted below `/api/core` and member routes below `/api/{member_id}`.
- The live Core app-server is a WebSocket endpoint at
  `/api/core/app-server` using the `core.app_server.v1` JSON-RPC/event
  protocol. REST endpoints cover health, sessions, configuration, projects,
  attachments, plugins, and related operations.
- Plugin widget operations are available through the app-server's
  `plugin.widget.list/get/invoke` methods. The sidebar host consumes those
  descriptors and snapshots while preserving a mobile right rail.
- Workflow RPC and CLI operations expose document validation, execution,
  history/queue inspection, activation/deactivation, and durable resume/signal
  behavior. Workflow invokes Agent/Model/plugin nodes through explicit
  `WorkflowExecutionContext` adapters rather than shared runtime state.
- Model/provider RPCs expose provider and model listing/CRUD, model-group
  listing/CRUD/reorder/member replacement, and atomic new-model-plus-provider
  creation. The CLI exposes the same surface through `models` and
  `models groups` commands. A model's local record ID is used at these
  boundaries while its upstream `model_id` is preserved for provider calls.
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
- Workflow backend coverage is under `core/tests/test_workflow_*.py`; Workflow
  UI contracts are under `core/ui/tests/workflow-*.test.ts`.
- Desktop pet logic has a Node test script; native Rust tests are colocated
  with the Tauri source. End-to-end material is under `e2e/`.
- Linux package acceptance includes REST/WebSocket/Study backend smoke,
  AppImage extraction, Debian contents inspection, and an Xvfb plus isolated
  D-Bus launch that records the bundled sidecar PID and checks for survivors.
