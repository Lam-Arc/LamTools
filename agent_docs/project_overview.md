# Project Overview

LamTools is a local-first AI Agent framework. The current product focus is
Core: an independently usable agent backend, shared UI, and Tauri desktop
application. See `project_structure.md` for ownership boundaries and
`project_core_tech.md` for toolchain constraints.

## Purpose

Provide a local agent runtime that can route model requests, execute approved
tools, persist sessions and runtime state, and expose the same Core capabilities
through CLI, HTTP, WebSocket, one shared UI, desktop DirectTransport, and
mobile RemoteTransport surfaces.

## Scope

Active work is confined to `core/`. `website/` is an independent product site
that reuses the real Core UI for its showcase. `archive/members/` contains
historical Writer, Sage, and Imager products and is not part of current Core
development.

## Architecture

The shared Vue/TypeScript UI is rooted at `core/ui/src/app/LamToolsApp.vue`
and consumes a Workbench backed only by `LamToolsTransport`. Tauri supplies a
DirectTransport to the loopback Core; Capacitor mobile supplies a
RemoteTransport whose ConnectionManager selects an authenticated LAN or Relay
Noise tunnel. The desktop Gateway bridges the tunnel to Core without involving
the desktop Vue process, and Relay forwards opaque tunnel bytes. The Python
`lamtools_core` application is assembled as FastAPI, exposes REST routes under
`/api/core`, and streams the live app-server over the
`core.app_server.v1` WebSocket/JSON-RPC protocol.

The Core right rail is a modular `RightSidebarHost`: a roughly 320px,
single-column separator stack rendered on one token-driven liquid-glass host
surface. The host owns module ordering, visibility, collapse state, and
per-project layout persistence. Built-in modules cover Runtime, Resources, Web
Search, RAG status/search, and Artifacts. Plugin contributions are either
validated declarative snapshots or trusted in-process Vue components selected
through the loader registry; raw plugin markup is not evaluated. Three.js and
runtime visualization remain deferred.

Sunday Workflow is a local-first durable subsystem under the bundled workflow
plugin. Its canonical V2 document is compiled into a canvas-free execution
prompt and a compact semantic graph; ComfyUI import/export is an adapter at this
boundary. Runs use a persistent SQLite-backed queue, an append-only event
journal, derived snapshots, and separate Workflow/Version/Run/NodeRun/Attempt
records. The engine owns retry, timeout, cancellation, wait/signal, activation,
idempotency, and cache policy, while Core Arrange remains the scheduler for
activations. Data packets carry item JSON plus Attachment/Artifact references;
credentials and capabilities are resolved only through explicit host contracts.
Agent and Workflow cooperate through explicit execution contexts and adapters,
without sharing implicit runtime state.

## Main Workflows

- Configure providers, models, settings, retry behavior, tools, and agent
  guidance through the unified JSONC configuration tree.
- Run Core directly through the CLI or serve it with Uvicorn for the desktop/UI
  clients; stream turns and runtime events through the app-server WebSocket.
- Persist sessions, checkpoints/snapshots, projects, attachments, artifacts,
  goals, and Arrange jobs; use tool permissions and approval flows for guarded
  execution.
- Author, validate, version, queue, resume, and inspect durable Workflows from
  the CLI, RPC, and shared UI; keep editor metadata separate from execution
  semantics and preserve ComfyUI-compatible import/export.
- Inspect and invoke plugin sidebar widgets through the manifest-backed
  `plugin.widget.list/get/invoke` contract and its matching CLI commands. Widget
  operations receive scoped context, validate schemas and ownership, require
  confirmation for dangerous actions, and require idempotency keys for
  mutations.
- Check GitHub releases for updates and guide the user to download them; the
  product does not silently install updates.
- Pair mobile devices once, store secrets separately from device metadata, and
  keep session/event truth in Core while desktop and mobile act as parallel
  clients.

## Desktop Distribution

Linux x64 is supported as a native PyInstaller/Tauri distribution through
`scripts/package-linux.sh`, producing an AppImage and a Debian package. The
Linux sidecar is an extensionless `LamCore` executable and is stored inside
both packages at `lamcore-backend/LamCore`. Linux mutable state follows the
Tauri XDG data/config roots and Linux Secret Service provides persistent
credential storage. Windows keeps its existing portable layout. macOS is
deferred and is not a supported artifact in the current distribution scope.

## Major Decisions

- Core is the only active product surface; archived members remain for
  traceability.
- GUI capabilities must have corresponding CLI support.
- Runtime state uses SQLite, while user-facing model/provider/settings and
  related configuration uses JSONC under `.lam/core/config/` (overridable by
  `LAMTOOLS_CORE_CONFIG_ROOT`); no configuration database is used.
- Tauri is the only UI observation environment for Core. The website showcase
  is a separate build and directly mounts real `core/ui` components.
- `core/ui/src/demo` is not a product entry point; new product UI belongs in
  the shared app and Workbench.
- The right-sidebar host is the single owner of rail layout state. RAG is
  explicitly unavailable when its plugin is absent: the UI shows no fabricated
  counts and only attempts legacy search after a user action; refresh is
  deterministic and there is no event-push dependency in this round.
