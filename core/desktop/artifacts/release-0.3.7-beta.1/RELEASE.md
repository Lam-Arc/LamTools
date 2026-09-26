# Sunday Desktop 0.3.7-beta.1 release audit

## What shipped

The desktop update path: 「下载安装包」 now downloads the installer in place,
verifies it against the digest the official-site manifest publishes, and runs it
(Windows) or reveals it (Linux/macOS). Same contract as the phone, so the shared
update section and the update banner behave identically on both.

The release is a **prerelease**: `v0.3.7-beta.1` carries
`prerelease: true`, GitHub's `releases/latest` still answers `v0.3.6`, and the
site manifest still points at 0.3.6. Stable users are not offered a beta; it is
obtained deliberately from the release page. The workflow now derives that flag
from the tag (`prerelease: ${{ contains(github.ref_name, '-') }}`) — before this,
a hyphenated tag would have become the release GitHub reports as "latest".

## Two packaging defects fixed on the way (both release-blocking)

1. **A new module was not in the frozen build.** `lamtools-core-backend.spec`
   lists the modules the packaged backend imports explicitly, and
   `lamtools_core.update.installer` was missing; `update.operations` imports it,
   so the packaged backend failed at import and never answered `/api/health`.
   Added, and reproduced/fixed locally by freezing and starting the binary.

2. **A required dependency was never declared.** The packaged backend died with
   `ModuleNotFoundError: No module named 'greenlet'` — `sqlalchemy.ext.asyncio`
   needs it, `pyproject.toml` asked for plain `sqlalchemy`, and greenlet had only
   ever arrived transitively. A fresh release environment no longer receives it,
   which is why development installs and earlier builds hid it. Now declared as
   `sqlalchemy[asyncio]`, with `greenlet` also listed in the spec's hiddenimports
   because sqlalchemy imports it conditionally.

   Verified by reproducing the release environment exactly: a fresh venv,
   `pip install -e "core[desktop]" pyinstaller`, a freeze from the spec, and the
   same start-and-poll smoke test — health 200 after 2 s where it previously
   died.

The smoke step also now keeps the frozen backend's stdout/stderr and prints them
(plus the listening sockets) when the probe fails. That change is what made
defect 2 visible at all; the failure had been undiagnosable from the log.

## Evidence

- Run `36226186784` (tag `v0.3.7-beta.1`, commit `0fdb50ad`): `build-windows`
  success (freeze, backend smoke, WebSocket smoke, Tauri build, Inno packaging,
  install/upgrade/uninstall/data-preservation lifecycle), `build-linux` success.
- Release assets: `Sunday_0.3.7-beta.1_x64-setup.exe` (58,167,053 B),
  `Sunday_0.3.7-beta.1_amd64.AppImage` (188,742,136 B),
  `Sunday_0.3.7-beta.1_amd64.deb` (122,463,870 B).
- In-app update check from this tree:
  `{"current_version":"0.3.7-beta.1","latest_version":"0.3.6","source":"site","notes_source":"github","status":"up_to_date"}`
  — `source: site` confirms the official-site manifest channel is live again
  (it answered 404 before 2026-09-26).
- `releases/latest` still resolves to `v0.3.6` (prerelease filtering works).

## Rollback

Delete the `v0.3.7-beta.1` release and tag; stable users are unaffected either
way because neither the site manifest nor `releases/latest` points at it.

## Still open

- The beta is deliberately absent from the website's download section (the page
  advertises the stable 0.3.6) and from the site manifest. Promoting a beta to
  the stable channel would be a separate, explicit decision.
- Automatic install is Windows-only: Linux and macOS have no single "run this
  installer" contract, so those platforms get the verified file revealed.
