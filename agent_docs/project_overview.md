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

## Main Workflows

- Configure providers, models, settings, retry behavior, tools, and agent
  guidance through the unified JSONC configuration tree.
- Run Core directly through the CLI or serve it with Uvicorn for the desktop/UI
  clients; stream turns and runtime events through the app-server WebSocket.
- Persist sessions, checkpoints/snapshots, projects, attachments, artifacts,
  goals, and Arrange jobs; use tool permissions and approval flows for guarded
  execution.
- Check GitHub releases for updates and guide the user to download them; the
  product does not silently install updates.
- Pair mobile devices once, store secrets separately from device metadata, and
  keep session/event truth in Core while desktop and mobile act as parallel
  clients.

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
