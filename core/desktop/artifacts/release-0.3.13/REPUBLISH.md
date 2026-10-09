# 0.3.13 second build — same version, site channel only

The 0.3.13 release record above covers the CI build of tag v0.3.13. This note
covers a **second build of the same version**, published by the owner's decision
("小改动，版本号不用变"): the running-turn guidance fix (cf1cbb8b) — a steering
message sent while a turn runs was silently dropped when the registry compared
the two spellings of a run id without normalizing them, and a client bubble could
hang forever waiting for a turn that could no longer consume it.

## Why this is not a normal release

- **No version bump, by request.** The tag, the five version files and the mobile
  app are untouched; nothing about the version's meaning changes.
- **The site channel is the only channel that moved.** GitHub Release v0.3.13
  still holds the first build (`69e63994…`, 58,191,548 bytes): its assets cannot
  be replaced without repository credentials this machine does not have, and the
  tag that produced them is immutable.
- **Consequence for users, stated plainly:** an install older than 0.3.13 gets
  this build from the update button (the site manifest describes it); an install
  that is already 0.3.13 sees "已是最新" and is *not* offered it, because the
  version did not change. The in-app upgrade path is therefore also the delivery
  path for this fix.

## Build provenance (and a build that was thrown away)

`scripts/package.ps1` builds the frozen backend with whatever Python is on the
machine. Run that way, the bundle came out **218 MB** and the installer
**94,429,796 bytes**: this machine's environment also carries numpy, matplotlib,
pandas, cryptography and friends, and PyInstaller collected them. That build was
never published — it was discarded.

The published build follows CI's recipe instead (`pip install -e "core[desktop]"`
+ `pyinstaller` in an otherwise empty venv, then the repository's own
`build-installer.ps1`):

- backend bundle `core/dist/LamCore` → **120 MB** (CI's installed payload: 122 MB);
- plugin boundary verified on the fresh bundle: `git`, `imagegen`, `plan`,
  `study`, `websearch` — no `emotion-ball-pet`, no `workflow`;
- packaged backend smoke on the fresh bundle: `[OK] REST /api/health` and
  `[OK] WebSocket initialize + plugin.enable(websearch) + study.session +
  websearch.widget.snapshot round-trip`;
- installer `Sunday_0.3.13_x64-setup.exe` → **57,928,936 bytes**, SHA256
  `81a9dc00284264fd7df43930212be1c95e33c9d052ba2e7552f40a625d6eb383`
  (CI's build1: 58,191,548 / `69e63994…`; the small size difference is the local
  Inno Setup 6.6.1 compiler).

## Setup acceptance (this build)

The deferred GUI item from the 0.3.11 / 0.3.13 records is **closed for this
build**: with the owner's dev window closed,
`install_setup.ps1 -Version 0.3.13 -SetupPath ...\Sunday_0.3.13_x64-setup.exe`
reports

```json
{ "status": "ok", "version": "0.3.13", "install_directory": "E:\\setuptest\\0.3.13",
  "app_file_version": "0.3.13", "main_process_id": 24464, "backend_process_ids": [31700] }
```

— that is, the installed `lamcore.exe` stayed up and its backend started, both
from the install directory (the earlier failures were the single-instance
hand-off to a running dev window, never a packaging problem).

## Cloud transaction

All times UTC, `KeepCommand=true`, per-step script + JSON + output here. The
republish mirrors the audited shape with the two preconditions a same-version
republish needs: what is on the channel must be the first build (so an
interleaved publish would fail here instead of being replaced silently), and the
versioned file already exists, so the first build is archived before the swap.

Preflight (read-only) 10:09:08 confirmed both services active, `latest` and the
versioned installer both `69e63994…`, the manifest `0016a410…`, the one-line
`authorized_keys` baseline, and every republish path absent. Authorize 10:09:16 →
upload 57,928,936 bytes → publish 10:09:31 (first build archived as
`Sunday-latest-x64-setup-0.3.13-build1-before-republish-20261009.exe`, versioned
and `latest` verified by digest) → manifest 10:09:40 (`c5d0cea2…`) → cleanup
10:09:44. `authorized_keys` back to its one-line baseline; both services active.

| step | CommandId | InvokeId | RequestId |
| --- | --- | --- | --- |
| republish-preflight | c-hz06zidcin2h91c | t-hz06zidcin9yy2o | 01A12023-4C79-503C-9994-A4FFC3F69E78 |
| republish-authorize | c-hz06zidcymt2hvk | t-hz06zidcyn0k6ww | 01A12023-6D8D-565C-B08C-9D2BCC3F4D57 |
| republish-publish | c-hz06ziddmorvj7k | t-hz06ziddmowvbwg | 01A12023-9E56-5484-8FAE-A1DB1BB987B9 |
| republish-manifest | c-hz06zide9wwvk74 | t-hz06zide9x6v5kw | 01A12023-CD5E-580B-ABE5-2A2EE49944AB |
| republish-cleanup | c-hz06zidefd0eygw | t-hz06zidefd5er5s | 01A12023-D878-57C9-BBCC-B8DA3DDF059E |

## Public verification

From this machine, against the public origin: the versioned installer and
`latest` both answer 200 with 57,928,936 bytes; a full public GET hashes to
`81a9dc00…`; `/downloads/desktop-update.json` reads version 0.3.13 with that same
digest and size (`c5d0cea2…`, 349 bytes).

## Rollback

Hard-link
`Sunday-latest-x64-setup-0.3.13-build1-before-republish-20261009.exe` back over
`Sunday-latest-x64-setup.exe` **and** over `Sunday_0.3.13_x64-setup.exe` (the
first build is the one the GitHub Release serves, so both channel files should
go back together), then restore the first manifest — its digest was
`0016a410549484de8b8e22777891e977a98b49645f778e94f8c0a40befa197ce`; regenerate it
from `Sunday_0.3.13_x64-setup-build1-20261009.exe` (kept in
`E:\LamTools\release\desktop\`) with `scripts/build-desktop-update.py`.
