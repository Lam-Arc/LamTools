# Sunday Desktop 0.3.14 release audit

## What shipped

Everything since v0.3.13 (ab73a720), which is the in-app update rebuilt end to end:

- **The update grows out of the rail into a card** (071f2367). The new version no
  longer announces itself as a banner across the top of the window: the left rail
  gains a soft rounded tile above the account icon, only while something is
  installable, and clicking it grows a card out of the tile with a `back.out`
  overshoot (transform-only, GSAP scoped to the component, `prefers-reduced-motion`
  gets a plain fade). The card shows current → new version, the release notes when
  the manifest has them, a real percentage, and 取消 / 更新.
- **The install runs itself, then brings Sunday back** (9d00c758). `update.install`
  hands the setup `/SILENT /NORESTART /AUTORESTART=1 /LOG=…`; the installer reads
  `/AUTORESTART=1` in `CurStepChanged(ssDone)` and starts the app again, because
  `[Run]`'s launch entry is skipped in a silent install. `update.cancel` stops a
  running download between chunks and reports `cancelled` — a normal ending, not a
  failure — so 取消 during a download really stops it.
- **The install-and-come-back contract is now part of the release acceptance**: the
  installer lifecycle script (which CI runs) installs with the in-app switches and
  asserts the setup started Sunday again; the new
  `scripts/verify-update-install.ps1` walks the public channel, and the release
  skill lists it as a release step.

## Test evidence

Run on the tagged tree (ab73a720): backend **2509 passed / 2 skipped**; UI **1089
passed** across 124 files with `npm run typecheck` (vue-tsc incl. the test config)
clean; the installer compiles with the new `[Code]` section (local Inno Setup
6.6.1, 26.9s). The update path adds backend tests (cancel raises and cleans up, the
worker maps a cancel to `cancelled`, cancelling when idle is a no-op, the install
switches) and UI tests (card states, cancel, Escape, scrim; rail entry presence and
position; host wiring).

## Build facts (GitHub Release, tag v0.3.14)

CI run `37918719012` for tag v0.3.14: the Windows job produced
`Sunday_0.3.14_x64-setup.exe` (58,216,595 bytes,
`sha256:c421d41eb452ae80c7d79a6a5fb06e4ab36c2ea1750c46774bd6c4ff4f3c1dc8`); the
Linux bundles were still building when this record was written. Release v0.3.14 is
not draft and not prerelease.

The installer came to the site the same way as 0.3.11–0.3.13: fetched on the server
(the canonical asset host is throttled here; the mirror's bytes are accepted only
because they hash to GitHub's own digest), pulled back over the audited sftp key,
verified locally, installed for the acceptance, and uploaded from that same copy.

## Setup acceptance (E:\setuptest\0.3.14)

`install_setup.ps1 -Version 0.3.14` reports `status ok`: `main_process_id 26500`,
`backend_process_ids [33848]`, both from the install directory, file version 0.3.14
— the GUI half of this acceptance is no longer deferred (no other instance was
running to take the single-instance hand-off).

## Update-channel acceptance (the new release step)

`scripts/verify-update-install.ps1` against the public channel, output kept as
`update-channel-acceptance.txt`:

1. manifest read: version 0.3.14, https download, sha256, size 58,216,595;
2. download from the public URL, size and digest match the manifest;
3. `SILENT/NORESTART/AUTORESTART=1` install → exit 0, application in place;
4. **the setup started the application again by itself** (pid 23496) and its
   bundled backend answers `/api/health` (port 55240).

Run twice, passed twice.

## Cloud transaction

All times UTC, `KeepCommand=true`, per-step script + JSON + output here. This round
has no separate preflight step: the authorize step carries the pre-state
assertions (latest installer = 0.3.13's `81a9dc00…`, the fetched stage hashing to
the published digest, the one-line `authorized_keys` baseline, and the target paths
absent). Publish 10:50:42: previous latest archived as
`Sunday-latest-x64-setup-0.3.13-before-0.3.14-20261009.exe`; versioned installer and
`latest` verified by digest; manifest 10:50:46 (`desktop-update.json`, 349 bytes,
`b7842a83…`, answered HTTP/2 200 by Caddy); cleanup 10:50:49. Site bundle
10:52:11–10:52:19 → `site-releases/0.3.14-mobile-0.1.48-20261009`.

One step failed on purpose and is recorded: the first site-bundle publish was
refused because the recorded tarball digest was still the previous round's — the
guard compared the staged file and stopped before touching the site. The digest was
corrected to this round's tarball and the step re-ran clean.

| step | CommandId | InvokeId | RequestId |
| --- | --- | --- | --- |
| fetch-parallel | c-hz06zigs9pnirr4 | t-hz06zigs9pv0gsg | 01A12046-9481-52F5-A96C-C2FE631ED1B8 |
| authorize | c-hz06zigzids28zk | t-hz06zigzidzjy0w | 01A12048-A53D-5944-A358-CB548CC131BE |
| publish | c-hz06zih1wr45xq8 | t-hz06zih1wr95qf4 | 01A12049-5452-5951-BD34-2897829B1E79 |
| manifest | c-hz06zih284xidj4 | t-hz06zih2852i680 | 01A12049-6B47-5521-9612-B73641B0F224 |
| cleanup | c-hz06zih2da9z6dc | t-hz06zih2daeyz28 | 01A12049-75F9-5AD1-BC55-24F23D0C99D6 |
| site-authorize | c-hz06zih6syft728 | t-hz06zih6sykszr4 | 01A1204A-B964-5B60-9064-1C58452C5A94 |
| site-publish | c-hz06zih72s7f9q8 | t-hz06zih72shev40 | 01A1204A-CD65-5A76-BE1F-B3DD492FFE09 |
| site-cleanup | c-hz06zih7829p8u8 | t-hz06zih782jou80 | 01A1204A-D828-5828-85CD-042023E493B3 |

## Rollback

Hard-link `Sunday-latest-x64-setup-0.3.13-before-0.3.14-20261009.exe` back over
`Sunday-latest-x64-setup.exe`, restore the 0.3.13 manifest
(`core/desktop/artifacts/release-0.3.13/desktop-update.json`), and repoint `site` at
`site-releases/0.3.13-mobile-0.1.48-20261009` if the bundle is rolled back too.
GitHub Releases keeps v0.3.14 regardless.
