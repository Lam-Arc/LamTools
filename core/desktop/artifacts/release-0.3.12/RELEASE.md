# Sunday Desktop 0.3.12 release audit

## What shipped

Everything on `codex/multiplatform-dev` since v0.3.11 (`e3d0552a`):

- **Guidance waits in sight** (`a4d4f357`): mid-turn guidance used to be invisible
  until the model had already consumed it. The thread now shows a dashed,
  breathing "to be applied" bubble at the end of the process until the real
  entry lands, and an instruction sent before the turn ends goes back to the
  composer instead of vanishing. The durable record flattens typed input parts
  into the message body, so the wire form and the stored form read the same.
- **A plugin mode can keep its own tools** (`a4d4f357`): a mode that declares
  `exclusiveTools` gates only its plugin's own tools to that mode; generic tools
  stay available.
- **Library entries carry their file** (`a4d4f357`): each entry now resolves to a
  real absolute path (`file=…`), so the assistant can read an entry's file
  directly instead of guessing where it lives.

## Test evidence

Run against the working tree that became `a4d4f357` (code identical to the
tagged `3ce69717` apart from version strings):

- desktop backend: **2470 passed / 2 skipped** (`pytest tests`, 5m25s).
- shared UI: **1063 passed** across 122 files (`npm run test:contract`).
- Not run this time: `npm run typecheck` (vue-tsc). CI's desktop frontend step is
  `vite build` only, so the release does not depend on it.

## Build facts (GitHub Release, tag v0.3.12)

CI run `37873365047` (`Build & Release` for tag v0.3.12) created the release at
`2026-10-09T02:22:36Z` (not draft, not prerelease) — the Windows installer job
had passed its smoketests by then. At record time (`02:29Z`) the run is still
`in_progress` (the Linux artifacts are built after the Windows channel), so:

| asset | bytes | digest |
| --- | --- | --- |
| `Sunday_0.3.12_x64-setup.exe` | 58,187,338 | `sha256:285e0b2f…429d6` |

The `.deb` / `.AppImage` assets were not present yet when this was recorded; the
official-site desktop channel does not depend on them (and the manifest carries
no `linux_*` fields for this version — same as 0.3.11).

`https://github.com/Lam-Arc/LamTools/releases/tag/v0.3.12`

## Installer provenance (same shape as 0.3.11)

This machine cannot reach the GitHub API or release assets (a local relay answers
`api.github.com` with a certificate for another host). The installer therefore
came to the site the other way round:

1. the **server** fetched the release asset (`fetch-parallel`, 02:24:45–02:24:55Z):
   eight ranged requests against `gh-proxy.com`, then size **and** digest checked
   against GitHub's own metadata for the asset —
   `ASSET Sunday_0.3.12_x64-setup.exe 58187338 285e0b2f…` / `GOT … / FETCH_OK`;
2. it came back down over the audited sftp key (`download-back`) and was verified
   locally — 58,187,338 bytes, `285e0b2f…`, equal to the digest GitHub reports;
3. the setup acceptance ran on that local copy;
4. that same copy was uploaded to the publish stage, so the published bytes are
   the bytes the acceptance ran on.

## Setup acceptance (E:\setuptest\0.3.12)

Silent install succeeded from
`E:\LamTools\release\desktop\Sunday_0.3.12_x64-setup.exe` into
`E:\setuptest\0.3.12`. Verified on the **installed** payload:

- `lamcore.exe` (FileVersion **0.3.12**, FileDescription "Sunday");
- plugin boundary: `lamcore-backend/_internal/resources/plugins/bundled/` contains
  `git`, `imagegen`, `plan`, `study`, `websearch` — no `emotion-ball-pet`, no
  `workflow` (the same rule CI enforces);
- `scripts/verify-backend-ws.py --exe E:\setuptest\0.3.12\lamcore-backend\LamCore.exe`:
  `[OK] REST /api/health reachable` and `[OK] WebSocket initialize +
  plugin.enable(websearch) + study.session + websearch.widget.snapshot
  round-trip succeeded`.

**Deferred item — the GUI main program.** `install_setup.ps1` reports
`lamcore.exe did not remain running within 20s`: the owner's Tauri dev window
(`core/desktop/src-tauri/target/debug/lamcore.exe`, PID 22360) holds the
single-instance lock, and the skill forbids closing processes that do not belong
to the target install directory. A detached install cannot outbid it. Same
symptom and same handling as 0.3.10 / 0.3.11; closing the dev instance is a
one-line repeat of the same helper call when that window is free.

## Cloud transaction

All times UTC, `KeepCommand=true`, per-step script + JSON + output here.
Preflight (read-only) 02:14:37Z confirmed both services active, site at
`0.3.11-mobile-0.1.48-20261008`, `latest` = 0.3.11 (`8f823e3e…`) with a matching
manifest, the one-line `authorized_keys` baseline, and every 0.3.12 path absent.
Publish 02:27:18–02:27:20Z: previous latest archived as
`Sunday-latest-x64-setup-0.3.11-before-0.3.12-20261009.exe`, versioned installer
and `latest` verified by digest, `desktop-update.json` (`1ac866a4…`, 349 bytes,
`published_at 02:27:30Z`) published at 02:27:35Z and answered HTTP/2 200 by
Caddy. `authorized_keys` back to its one-line baseline at 02:27:44Z; both
services stayed active throughout.

| step | CommandId | InvokeId | RequestId |
| --- | --- | --- | --- |
| preflight | c-hz06zh70nw1m29s | t-hz06zh70nw6luyo | 01A11E70-DDFF-58C5-A9E0-1FD6AEC386EF |
| fetch-parallel | c-hz06zh7x9r4t0jk | t-hz06zh7x9r9st8g | 01A11E7A-2A04-574E-907C-A61BC8C23B75 |
| authorize | c-hz06zh7ygjh6nls | t-hz06zh7ygjto5c0 | 01A11E7A-8123-516C-A4B1-DD9D748E1DEE |
| publish | c-hz06zh85fnm7v9c | t-hz06zh85fntpkao | 01A11E7C-7E47-59CE-9A40-0EFCE349B629 |
| manifest | c-hz06zh86cidn30g | t-hz06zh86ciimvpc | 01A11E7C-C0F1-5CE4-B89E-BD5BBC1B7D3A |
| cleanup | c-hz06zh86rll22v4 | t-hz06zh86rlq1vk0 | 01A11E7C-DF5E-5132-907D-40AC70E1C2AD |
| ci-status (read-only) | c-hz06zh8a4tlb8ms | t-hz06zh8a4tuj4wg | 01A11E7C-F4E3-5C29-9F74-BF4DB4DC0CA4 |
| ci-status-2 (read-only) | c-hz06zh8cwuzsx6w | t-hz06zh8cwuza1nk | 01A11E7D-153B-54D4-8810-260248A20F71 |

## Public verification

`verify_public.py` (run from this machine, against the public origin):

- the versioned installer and `latest` both answer 200 with 58,187,338 bytes;
- a full public GET of `/downloads/Sunday_0.3.12_x64-setup.exe` hashes to
  `285e0b2f…` — equal to the CI asset's digest;
- the published `/downloads/desktop-update.json` reads version 0.3.12 with that
  digest and size (`version_ok` / `sha_ok` / `size_ok` / `published_sha_ok` all
  true).

`update check --json` from this machine: `up_to_date`, `latest_version 0.3.12`,
`source: site` (the GitHub source is unreachable from here and is reported as
unavailable — the site channel is the primary one).

**Pending, and expected to be pending:** the site *bundle* still carries the
0.3.11 label (`label_bundle=None`; the live `main-*.js` contains one `0.3.11`
and no `0.3.12`). The bundle is republished by the mobile flow — for 0.3.11 the
desktop audit recorded the same split (`0.3.11-mobile-0.1.48-20261008` was
published from `core/mobile/artifacts/release-1048`). The repository-side labels
were moved to 0.3.12 in this record's commit
(`website/src/components/Download.vue`, `.env.example`, `src/mock/runtime.ts`),
so the next site build carries it.

## Rollback

Hard-link `Sunday-latest-x64-setup-0.3.11-before-0.3.12-20261009.exe` back over
`Sunday-latest-x64-setup.exe` and restore the 0.3.11 manifest
(`core/desktop/artifacts/release-0.3.11/desktop-update.json`); the repository
copy `core/desktop/update-manifest.json` is generated and ignored. GitHub
Releases keeps v0.3.12 regardless.
