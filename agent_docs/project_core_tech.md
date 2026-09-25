# Project Core Technologies

Only foundational technologies and constraints are recorded here. Detailed
dependency inventories belong to the package manifests and module documents.

## Languages and Runtimes

- Python `>=3.14` for `lamtools-core`.
- TypeScript/JavaScript with Node `>=24.17.0 <25` and npm `>=11.17.0` for the
  shared UI and website.
- Rust 2021 edition for the Tauri desktop shell and the in-progress Rust
  runtime/mobile host. The Rust runtime migration is partial; Study, model, and
  Workflow internal runners are not yet a complete replacement for Python.

## Frameworks and Libraries

- FastAPI/Uvicorn provide the Python HTTP application and server boundary;
  SQLAlchemy with aiosqlite provides SQLite persistence; httpx supports HTTP
  model/service calls.
- Vue `3.5.x`, Vite `8.x`, and TypeScript `6.x` provide the UI/build stack;
  Vitest is used for UI tests. Core UI also uses marked, Mermaid, KaTeX,
  DOMPurify, CodeMirror, Vue Flow, and GSAP for its rendered/editor surfaces.
- Core UI exposes a connection-neutral `LamToolsTransport` and shared
  Workbench. Desktop uses DirectTransport; Capacitor mobile uses RemoteTransport
  over a Noise-secured tunnel selected by ConnectionManager.
- The bundled Workflow backend provides a versioned document/adapter boundary,
  durable run engine, SQLite-backed queue, append-only event journal and
  snapshot projector, expression AST evaluator, DataPacket/Attachment
  contracts, credential references, capability gates, and Arrange-backed
  activations.
- The shared UI's `RightSidebarHost` renders built-in and plugin modules through
  a trusted loader registry. Declarative plugin widgets use bounded JSON
  snapshots and schema-driven actions; trusted Vue contributions are loaded
  in-process only from registered modules.
- Tauri `2.x` provides the desktop shell and native bridge; the Windows
  installer is the repository-owned Inno Setup script
  (`core/desktop/installer/Sunday.iss`), not Tauri's NSIS bundler; Linux
  targets AppImage and Debian bundles.
  The website uses anime.js `4.x` for motion.
- The mobile client is being moved to a Tauri host with Rust runtime commands;
  its Stop and snapshot-recovery paths are implemented. Sidebar and system
  inset source fixes have not yet received phone visual confirmation.

## Build, Test, and Development Tools

- Backend tests: `py -3.14 -m pytest` from `core/` (or the repository test
  script). UI tests: `npm run test:contract` in `core/ui/`; UI type checking
  and builds are defined in `core/ui/package.json`.
- Desktop development/build uses `npm run tauri dev` and `tauri build` from
  `core/desktop/`; its Vite dev server is configured for port `5173`.
- Linux distribution builds use `scripts/package-linux.sh` on native Linux
  (including WSL2). The script keeps Node, Python, Rust, Cargo, package
  caches, and staging on the Linux filesystem, rejects `/mnt/c`, builds an
  extensionless PyInstaller `LamCore`, and injects it into both Tauri bundles
  as `lamcore-backend/LamCore`. CI and release jobs call this script instead of
  treating a Windows or bare Tauri build as Linux evidence.
- Website development/build uses `npm run dev` and `npm run build` from
  `website/`. Repository scripts provide Core startup, packaging, versioning,
  and release automation.

## External Services and Infrastructure

- Model/provider adapters call configured external LLM APIs, including
  OpenAI-compatible and named provider presets documented by the project.
- Provider JSONC records own `api_type`, `base_url`, API key, connection
  defaults, and provider-level adapter/request customization. Model JSONC
  records own the safe local record ID, unchanged upstream `model_id`, provider
  reference, capability/limits, thinking metadata, and optional model-level
  adapter/request customization.
- Adapter resolution is ordered: explicit model profile, explicit provider
  profile, model matcher, provider/base matcher, then protocol default. Inline
  request overrides are merged provider first and model second, so model
  configuration wins over provider configuration.
- MCP is an optional integration surface for external tools.
- Update checking queries GitHub's latest-release API; downloading/installing
  remains user-guided.
- The desktop packages the backend for Windows and Linux so the installed app
  does not require a separate Python or Node runtime. Linux mutable state uses
  Tauri `app_data_dir()`/XDG paths, hooks use `XDG_CONFIG_HOME`, and the
  keyring uses the persistent Linux Secret Service backend. macOS packaging is
  not currently provided.

## Important Technical Constraints

- User-editable Core configuration is JSONC under `.lam/core/config/`, seeded
  idempotently without overwriting existing files. Provider API keys are stored
  in provider config files; list RPCs mask them.
- User-defined model groups are persisted in
  `.lam/core/config/model_groups.jsonc`. The catalog stores stable group IDs,
  unique names, ordered many-to-many memberships, and a revision for
  optimistic concurrency. Memberships reference model record IDs, not upstream
  API model IDs; missing records are surfaced as dangling memberships and
  “未分组” is a UI projection.
- `settings.jsonc` stores the global catalog classification at
  `core.modelCatalog.classification`; the same value drives the main model
  picker and Settings → 模型与供应商. The shared
  `CoreModelCatalogViewToggle` implements the compact capsule control.
- Configuration RPCs include `config.model_groups.list`,
  `config.model_group.create|update|delete`,
  `config.model_group.members.set`, `config.model_groups.reorder`, and
  `config.model.create_with_provider`. The CLI mirrors group CRUD/member
  operations under `models groups` and new model creation under
  `models create --group`.
- Core runtime data is local SQLite. Do not introduce the retired config DB
  tables or `LAMTOOLS_LLM_CONFIG_DB` configuration path.
- Workflow runs pin an immutable definition revision. Durable execution records
  distinguish Workflow, Version, Run, NodeRun, and Attempt; retries, timeouts,
  cancellation, wait/signal, idempotency, and cache policy are engine contracts.
  The current single-flight guard is process-local, so cross-process execution
  still requires a transactional claim/lock layer.
- Workflow data is item-oriented and reference-based: large binary values travel
  through Attachment/Artifact references, and resolved credential secrets remain
  attempt-local and are excluded from event history, snapshots, logs, metadata,
  and results. Built-in nodes retain legacy raw-value compatibility while
  trusted plugin executors use the packet boundary.
- Workflow activation reuses Core Arrange for once, interval, calendar, and
  event triggers; no second scheduler is introduced. Durable wait/human-task
  support currently has no complete HumanTask center, and HTTP/MCP/external
  connector nodes remain deferred until their host permission boundary exists.
- Tauri development is a separate frontend/backend lifecycle from the
  repository `dev.ps1` flow; UI verification is performed in the Tauri window.
- The website showcase must keep Vue as a single instance and reuse the real
  Core UI components/styles. Its build is independent from Core's desktop
  build.
- Core remote security uses one-time pairing, device credentials, Noise XX
  identity verification, version negotiation, per-connection sequence/replay
  guards, and separate secret/metadata storage. The Gateway bridges to
  loopback Core; Relay never sees tunnel plaintext.
- Plugin widget operations are exposed through `plugin.widget.list`,
  `plugin.widget.get`, and `plugin.widget.invoke`, with manifest validation,
  scoped context, ownership/schema checks, dangerous-action confirmation, and
  idempotency for mutations. Web Search provides snapshot and real health
  operations. The bundled RAG widget reports unavailable when no RAG provider
  is installed; it does not synthesize index statistics.
