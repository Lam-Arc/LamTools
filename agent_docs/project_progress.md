# Project Progress

## Goal

Deliver the Core single-UI, multi-Transport architecture: one shared
Workbench and application for desktop and mobile, with connection-specific
code isolated behind DirectTransport, RemoteTransport, the desktop Gateway,
and the opaque Relay tunnel.

## Overall Progress

The refactor is implemented. Core UI no longer uses the former demo entry;
desktop and mobile both mount `core/ui/src/app/LamToolsApp.vue`. The Workbench
depends on `LamToolsTransport`, desktop uses DirectTransport, and mobile keeps
one stable RemoteTransport while ConnectionManager selects the secure LAN or
Relay route. Pairing, device identity, secure-storage separation, Noise
authentication, replay protection, protocol versioning, reconnect handling,
and multi-client response ownership are in place.

## Current Position

- Shared UI/runtime: `core/ui/src/app/`, `core/ui/src/workbench/`, and
  `core/ui/src/transport/`.
- Mobile-only code is limited to pairing, native capabilities, lifecycle,
  discovery, secure storage, and connection/wire code; its APP screen mounts
  the shared `LamToolsApp`.
- The Tauri Gateway keeps Core loopback-only and bridges authenticated,
  encrypted tunnel frames; Relay forwards opaque tunnel traffic without
  parsing Core business messages.
- Context-compaction trigger behavior was corrected so precise planning is not
  skipped by a fast estimate and short no-LLM histories return `not_needed`.

## Verification

- Core: `1677 passed, 2 skipped`.
- Shared UI: 67 test files / 471 tests; typecheck and build pass.
- Mobile: 9 test files / 33 tests; typecheck, build, and Capacitor sync pass.
- Desktop Rust: 49 tests, `cargo check`, and format check pass.
- Relay Rust: 10 tests and format check pass.
- Android Debug APK builds successfully from the synchronized Capacitor project.
- Docker Compose configuration validates with an example domain; the image
  build still depends on Docker Hub network access in the local environment.
- Website build passes.
- LamTools design audit: 69 files scanned, 0 deviations.
- `git diff --check` passes.

## Next Milestone

Run real-device LAN/Relay pairing and reconnect validation when deployment
credentials and target devices are available. The remaining infrastructure
verification is the real Docker image build once Docker Hub access is
available. Keep new business features in the shared UI/Workbench and add new
network paths only below RemoteTransport.
