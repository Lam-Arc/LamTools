# Project Core Technologies

Only foundational technologies and constraints are recorded here. Detailed
dependency inventories belong to the package manifests and module documents.

## Languages and Runtimes

- Python `>=3.14` for `lamtools-core`.
- TypeScript/JavaScript with Node `>=24.17.0 <25` and npm `>=11.17.0` for the
  shared UI and website.
- Rust 2021 edition for the Tauri desktop shell.

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
- Tauri `2.x` provides the desktop shell and native bridge; the configured
  Windows bundle target is NSIS. The website uses anime.js `4.x` for motion.

## Build, Test, and Development Tools

- Backend tests: `py -3.14 -m pytest` from `core/` (or the repository test
  script). UI tests: `npm run test:contract` in `core/ui/`; UI type checking
  and builds are defined in `core/ui/package.json`.
- Desktop development/build uses `npm run tauri dev` and `tauri build` from
  `core/desktop/`; its Vite dev server is configured for port `5173`.
- Website development/build uses `npm run dev` and `npm run build` from
  `website/`. Repository scripts provide Core startup, packaging, versioning,
  and release automation.

## External Services and Infrastructure

- Model/provider adapters call configured external LLM APIs, including
  OpenAI-compatible and named provider presets documented by the project.
- MCP is an optional integration surface for external tools.
- Update checking queries GitHub's latest-release API; downloading/installing
  remains user-guided.
- The desktop packages the backend for Windows so the installed app does not
  require a separate Python or Node runtime.

## Important Technical Constraints

- User-editable Core configuration is JSONC under `.lam/core/config/`, seeded
  idempotently without overwriting existing files. Provider API keys are stored
  in provider config files; list RPCs mask them.
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
