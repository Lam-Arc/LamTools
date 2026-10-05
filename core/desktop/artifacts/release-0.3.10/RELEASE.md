# Sunday Desktop 0.3.10 release audit

## What shipped

Everything on `codex/multiplatform-dev` since v0.3.9 (2d0bf435):

- **The plan workbench** (57e4cb45, 081f5f09): a full editor for plan packages
  (方案) in the shared UI — every field editable with optimistic concurrency,
  per-revision rollback with restore, soft-delete recovery, and a start button
  that hands the plan to a session. The plan plugin is `universal`, so the same
  workbench ships on the phone (mobile 0.1.47).
- **The plan skills rewritten around a conversation** (d0eb9769): draft/refine/
  execute now collect by chat, keep requirement/success/non-goals in the user's
  language, and allow technical wording only in the checklist steps; each skill
  ships 8 eval cases plus a wiring-only manifest, and a new end-to-end test
  covers the start-plan path (goal and steps install as-is; the document stays
  untouched).
- **Message edit, fork and rollback without checkpoints** (1a065aa1, a7893976):
  editing any message re-sends from it (the first message included), forks split
  at the tapped turn and inherit the title, rollback no longer requires a
  checkpoint.
- **Model/config trust fixes** (16829ac2): the running model never changes
  without the user (the global default model is gone); non-ASCII API keys are
  rejected; config edited outside the app is noticed, not overwritten; 401/403
  errors name the provider, address and model; a pending approval takes over the
  input area instead of fighting it.
- Smaller shared fixes: an approved out-of-workspace file no longer fails the
  run (1f6c15a7); the study composer stays usable while a turn runs (8292ecf1);
  a stopped turn keeps its context for the next message (7a95ea1c — the phone
  side ships in mobile 0.1.47).

## Test evidence

Run against 5f8fe921 + version bumps:

- desktop backend: **2474 passed / 2 skipped**.
- shared UI: **947 passed**, `vue-tsc` clean.
- mobile (same tree): 284 passed, `vue-tsc` clean; mobile Rust host 46/46.

## Build facts (GitHub Release, tag v0.3.10)

CI run 36605371916 (`Build & Release` for tag v0.3.10) succeeded: frontend build
→ PyInstaller → backend smoke → Tauri `--no-bundle` → Inno Setup →
install/upgrade/uninstall lifecycle with data retention → upload. Release
assets: `Sunday_0.3.10_x64-setup.exe` (58,305,830 bytes, SHA256
`c0af83099da29797ffdc3ed5f33ce0eac8b17dbe662e0c762eda5028af3d0548`),
`Sunday_0.3.10_amd64.deb`, `Sunday_0.3.10_amd64.AppImage`; not draft, not
prerelease. `update check --json` reads `up_to_date` / `latest_version 0.3.10`
from the site channel.

## Official-site channel

Same audited shape as previous releases (per-step script + JSON + output here,
`KeepCommand=true`, times UTC). Preflight 17:54:20 confirmed services active,
site manifest = 0.3.9, latest hash = 0.3.9 installer, the one-line
`authorized_keys` baseline, all new paths absent. Authorize 17:54:33 → upload
58,305,830 bytes → publish 17:54:47 (previous latest archived as
`Sunday-latest-x64-setup-0.3.9-before-0.3.10-20260930.exe`; versioned installer
and `Sunday-latest-x64-setup.exe` verified by hash) → manifest 17:54:51
(`downloads/desktop-update.json`, 349 bytes, digest `d39ebefa…`, Caddy answers
200) → cleanup 17:54:54 (transfer key revoked, baseline restored, services
active). The site bundle itself (`0.3.10-mobile-0.1.47-20260930`, both version
labels) was republished by the mobile flow in `core/mobile/artifacts/release-1047`.

| step | CommandId | InvokeId | RequestId |
| --- | --- | --- | --- |
| preflight | c-hz06yjuad7cc9og | t-hz06yjuad7mbv28 | 01A0EE4D-9B48-514D-BEA9-B97E0F51E720 |
| authorize | c-hz06yjub3o0mh34 | t-hz06yjub3oam2gw | 01A0EE4D-D116-59EA-B89F-9881C935E81C |
| publish | c-hz06yjubrdrwt1c | t-hz06yjubre4eark | 01A0EE4E-0124-5EDA-AEE1-3C5AAD8A8731 |
| manifest | c-hz06yjuc2msy70g | t-hz06yjuc2n5foqo | 01A0EE4E-17FF-54B7-A2D7-E6C2C7B672A6 |
| cleanup | c-hz06yjuc7z0ncow | t-hz06yjuc7zd4uf4 | 01A0EE4E-22CE-5025-A039-86737E7BEF20 |

## Setup acceptance (E:\setuptest\0.3.10)

First start attempt failed because a leftover dev-mode instance answered the
single-instance handoff; after it was closed, `install_setup.ps1` reports
status ok: main `lamcore.exe` (PID 6236) and backend `LamCore.exe` (PID 31644)
both running from the install directory, file version 0.3.10. Verified against
the live backend on its local port: plugin boundary holds
(`git`/`imagegen`/`plan`/`study`/`websearch` present; no `emotion-ball-pet`, no
`workflow`); the app-server initializes and answers `project.list` with real
JSON (no HTML-as-JSON); a provider was created, read back (key masked as
`********`) and deleted.

## Rollback

Hard-link `Sunday-latest-x64-setup-0.3.9-before-0.3.10-20260930.exe` back over
`Sunday-latest-x64-setup.exe` and restore the 0.3.9 manifest (digest
`7d86aae2…`); GitHub Releases keeps v0.3.10 regardless. For the site bundle,
repoint `site` at `site-releases/0.3.9-mobile-0.1.46-20260929`.
