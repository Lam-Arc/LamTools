# Project Diary

This is a compact reference of stable project decisions and lessons. It does
not record session chronology, releases, commits, routine maintenance, or raw
logs.

## Decisions and Lessons

- Keep current implementation and planning centered on `core/`; treat
  `archive/members/` as historical reference rather than a development target.
- Keep runtime persistence in SQLite and user-facing configuration in the
  unified `.lam/core/config/` JSONC tree. Default seeding must be idempotent so
  upgrades cannot overwrite user edits.
- Treat Tauri as the authoritative Core UI observation surface. Its Vite
  frontend and dynamically ported local backend are separate from the legacy
  repository startup scripts; restarting the wrong process can break the
  desktop dev URL.
- The website showcase is an integration consumer of `core/ui`, not a second
  hand-built UI. Preserve its Vue singleton alias and the shared component/data
  contracts when changing either surface.
- The product UI boundary is `LamToolsApp → Workbench → LamToolsTransport`.
  Desktop and mobile must keep the same Workbench/application; platform code
  belongs in runtime/native/connection adapters.
- Remote traffic is an authenticated Noise tunnel. The desktop Gateway keeps
  Core loopback-only, and the Relay forwards opaque encrypted tunnel payloads
  without interpreting Core business messages.
- Transport reconnects replace only the physical tunnel. The shared Workbench,
  conversation projection, and composer state remain alive across LAN/Relay
  route changes.
