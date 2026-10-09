# Sunday Desktop 0.3.13 release audit

## What shipped

One change, on top of everything already released in 0.3.12:

- **Installing from the app now closes Sunday first, then the setup runs**
  (62c87329). The in-app hand-off used to leave the app running and depend on the
  installer to close it ("安装向导会要求先退出 Sunday"); now the installer is
  started so it outlives this process (it leaves the backend's kill-on-close job
  object, which now allows exactly that one escape) and the app then quits for
  real through `quit_app`. The installer is confirmed started *before* the app
  exits, so a failed hand-off leaves a running app with a visible error instead
  of nothing. Linux and macOS report `quit: false` and keep the app up — nothing
  there replaces a running app.

Two notes about what this build does **not** contain:

- The parallel session's finished batch (compaction anchored on provider usage;
  sub-agent members waking their parent; Chinese member names) was committed as
  45e415f8 *after* tag v0.3.13 and is therefore **not** in this installer. It is
  on the branch and will ship with the next release.
- The mobile app is unchanged: the phone already hands the verified APK to
  Android's package installer, which replaces the running app itself, so mobile
  stays at 0.1.48 and no new APK was built.

This round also republishes the website bundle. The 0.3.12 round published only
the installer and its manifest, so the site's own version label had drifted one
release behind (it still said 0.3.11 while the channel served 0.3.12).

## Test evidence

Run on the tagged tree plus the parallel batch that landed right after it (the
tag does not contain that batch; its focused tests are included in these
numbers): **backend 2502 passed / 2 skipped**, **UI 1066 passed** across 122
files with `npm run typecheck` clean, **mobile 290 passed** with `vue-tsc` clean,
desktop host **`cargo check`** clean. The update hand-off itself adds 3 backend
tests (spawn flags, the breakaway contract, the shell fallback, the non-Windows
`quit: false`) and 3 UI tests (exit on the host's word, no exit when the hand-off
does not replace the app, retryable state without a quit bridge).

## Build facts (GitHub Release, tag v0.3.13)

CI run `37905980608` (`Build & Release` for tag v0.3.13) **succeeded**
(08:36:17Z → 08:56:21Z): frontend → PyInstaller → backend smoke → WebSocket
handshake → Tauri `--no-bundle` → Inno Setup → install/upgrade/uninstall
lifecycle → upload. Assets (not draft, not prerelease):

| asset | bytes | digest |
| --- | --- | --- |
| `Sunday_0.3.13_x64-setup.exe` | 58,191,548 | `sha256:69e63994…eb52409` |
| `Sunday_0.3.13_amd64.deb` | 122,611,738 | — |
| `Sunday_0.3.13_amd64.AppImage` | 188,852,728 | — |

`https://github.com/Lam-Arc/LamTools/releases/tag/v0.3.13`;
`update check --json` reads `up_to_date` / `latest_version 0.3.13`,
`source: site`.

## Installer provenance

Same route as 0.3.11 / 0.3.12 (this machine cannot reach the GitHub API or the
release assets; the site channel is published from the server): fetch on the
server → digest checked against GitHub's own asset digest → pulled back over the
audited sftp key → verified locally (58,191,548 bytes, `69e63994…`) → installed
and exercised as the acceptance → uploaded from that same copy. One fetch
attempt was needed this time (`FETCH_OK` on the first mirror try).

## Setup acceptance (E:\setuptest\0.3.13)

Silent install succeeded from
`E:\LamTools\release\desktop\Sunday_0.3.13_x64-setup.exe` into
`E:\setuptest\0.3.13`; the payload carries `lamcore.exe` (FileVersion 0.3.13,
FileDescription “Sunday”) and `lamcore-backend\LamCore.exe`. Verified on the
**installed** payload:

- `scripts/verify-backend-ws.py --exe E:\setuptest\0.3.13\lamcore-backend\LamCore.exe`:
  `[OK] REST /api/health reachable` and `[OK] WebSocket initialize +
  plugin.enable(websearch) + study.session + websearch.widget.snapshot
  round-trip succeeded`;
- plugin boundary: `resources/plugins/bundled/` contains `git`, `imagegen`,
  `plan`, `study`, `websearch` — no `emotion-ball-pet`, no `workflow`. (The empty
  `MyProject/` directory that 0.3.11 and 0.3.12 shipped inside the backend
  payload is absent here.)

**Deferred item — the GUI main program**, the same one the 0.3.11 audit
recorded: `install_setup.ps1` reports `lamcore.exe did not remain running within
20s` because a Tauri dev window (PID 21696, `core/desktop/src-tauri/target/debug/
lamcore.exe`, started 16:36 local) holds the single-instance lock, so the freshly
installed app hands off and exits by design. The paying-the-way-forward part is
that this release's own change is what makes the in-app upgrade close the old app
without relying on the wizard. Closing that dev window and re-running
`install_setup.ps1 -Version 0.3.13` completes the check.

## Cloud transaction

All times UTC, `KeepCommand=true`, per-step script + JSON + output here.
Preflight (read-only) 08:35:20 confirmed both services active, site at
`0.3.11-mobile-0.1.48-20261008`, `latest` = 0.3.12 (`285e0b2f…`) with a matching
manifest, the one-line `authorized_keys` baseline, and every 0.3.13 path absent.
Installer: authorize 08:58:27 (the fetched stage verified against the published
digest), publish 09:00:01 (previous latest archived as
`Sunday-latest-x64-setup-0.3.12-before-0.3.13-20261009.exe`), manifest 09:00:11
(`desktop-update.json`, 349 bytes, `0016a410…`, answered HTTP/2 200 by Caddy),
cleanup 09:00:14. Site bundle: authorize 09:00:45, publish 09:00:56 (2,610,000
bytes extracted into `site-releases/0.3.13-mobile-0.1.48-20261009`, label check
`grep -R 0.3.13 assets` and Caddy serving both), cleanup 09:00:59. The first
site-authorize attempt (09:00:23) **failed on purpose**: it asserts the installer
channel digest it expects to see, and this round publishes the installer *before*
the bundle, so the guard caught its own stale baseline; the baseline was corrected
to this round's digest and the step re-ran. `authorized_keys` is back to its
one-line baseline and both services stayed active throughout.

| step | CommandId | InvokeId | RequestId |
| --- | --- | --- | --- |
| preflight | c-hz06zi4zad89e68 | t-hz06zi4zadd96v4 | 01A11FCD-6C09-5DC0-B419-3659EA2C3EAF |
| fetch-parallel | c-hz06zi6sstrxn28 | t-hz06zi6sstzfc3k | 01A11FE0-19F3-5D76-8049-9FDF568AF122 |
| authorize | c-hz06zi71j8vb9j4 | t-hz06zi71j95auww | 01A11FE2-96C6-56F5-88D5-D2D54DE32CB0 |
| publish | c-hz06zi76h5pyqkg | t-hz06zi76h5uyj9c | 01A11FE3-FFFA-53C8-AF11-A75E219B4946 |
| manifest | c-hz06zi772to9am8 | t-hz06zi772u0qscg | 01A11FE4-2BE0-52C5-9583-6D072361D5DA |
| cleanup | c-hz06zi77859h05c | t-hz06zi7785gyp6o | 01A11FE4-36AB-52A9-84D5-6CADC3C14491 |
| site-authorize | c-hz06zi78y4aa9ds | t-hz06zi78y4fa22o | 01A11FE4-B451-5AE0-8A95-007D18F48CE2 |
| site-publish | c-hz06zi79iudy9z4 | t-hz06zi79iunxvcw | 01A11FE4-DE5C-54A0-A194-658669AC5E6E |
| site-cleanup | c-hz06zi79o2ft340 | t-hz06zi79o2psohs | 01A11FE4-E8D6-596E-A443-1CF6D51C8C44 |

## Public verification

`verify_public.py` (run from this machine, against the public origin), all
assertions passed: the versioned installer and `latest` both answer 200 with
58,191,548 bytes; a full public GET hashes to `69e63994…`; the published
`/downloads/desktop-update.json` reads version 0.3.13 with that digest and size
(`published_sha_ok` true for `0016a410…`); the site bundle (`main-BdVEiPP3.js`)
carries the 0.3.13 label, so the homepage is back in step with the channel.

## Rollback

Hard-link `Sunday-latest-x64-setup-0.3.12-before-0.3.13-20261009.exe` back over
`Sunday-latest-x64-setup.exe`, restore the 0.3.12 manifest
(`core/desktop/artifacts/release-0.3.12/desktop-update.json`, `1ac866a4…`), and
repoint `site` at `site-releases/0.3.11-mobile-0.1.48-20261008` if the bundle is
rolled back too. GitHub Releases keeps v0.3.13 regardless.
