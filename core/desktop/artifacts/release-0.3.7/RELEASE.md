# Sunday Desktop 0.3.7 stable release audit

## What shipped

The stable release of the update path, plus the mobile-side batch that was
already published: 「下载安装包」 downloads the installer in place, verifies it
against the digest the official-site manifest carries, and runs it (Windows) or
reveals it (Linux/macOS).

Promoted from 0.3.7-beta.1 to 0.3.7 (via `scripts/bump-version.ps1`, the five
version places) so the release is a normal one: GitHub's `releases/latest`
resolves to v0.3.7 and every stable install is offered it.

## Review before releasing

Three defects were found reviewing the mobile system-download path and fixed
before the stable cut (they ship as mobile 0.1.36):

- a verified record whose file is gone (Android cleans its own external
  directory) offered an install that could only fail, with no way back;
- the system download's completion notification carried a tap-to-install
  shortcut around the digest check; it is now a progress-only notification;
- the destination is nested under the app's external directory, which the system
  downloader does not create for you — created before enqueue.

No blockers were found in the desktop path, the shared update section, or the
release flow.

## Evidence

- Release `v0.3.7`: `prerelease: false`, assets `Sunday_0.3.7_x64-setup.exe`
  (58,166,212 B), `Sunday_0.3.7_amd64.AppImage` (188,746,232 B),
  `Sunday_0.3.7_amd64.deb` (122,463,700 B); CI run 36230958332 (Windows memory:
  freeze, backend smoke, WebSocket smoke, Tauri build, Inno packaging,
  install/upgrade/uninstall/data-preservation lifecycle; Linux: sidecar + both
  bundles).
- Site channel: `Sunday_0.3.7_x64-setup.exe` and `Sunday-latest-x64-setup.exe`
  both 200 at 58,166,212 bytes; the previous latest (94,124,582 B,
  sha256 `41fedc6c…`) archived as
  `Sunday-latest-x64-setup-0.3.6-before-0.3.7-20260926.exe`; the published
  manifest carries version 0.3.7 and the installer's digest
  (`93338593…`), asserted equal to `core/desktop/update-manifest.json`.
- Site archive republished as `site-releases/0.3.7-mobile-0.1.36-20260926`,
  which carries both the desktop 0.3.7 and mobile 0.1.36 labels.
- In-app check emulated from an installed 0.3.6:
  `{"status":"update_available","latest_version":"0.3.7","source":"site",
  "sha256":"93338593…","install_supported":true}` — the user is offered 0.3.7
  from the official channel, with the digest, and can install it in place.

## Rollback

Copy `Sunday-latest-x64-setup-0.3.6-before-0.3.7-20260926.exe` over
`Sunday-latest-x64-setup.exe`, restore the desktop manifest to the 0.3.6 one
(the 0.3.6 manifest is recorded in
`core/desktop/artifacts/site-manifest-20260926/desktop-update.json`), and repoint
`site` at `site-releases/0.3.6-mobile-0.1.35-20260926`. The GitHub release can
stay: it is what 0.3.7 installs update from.

## Still open

- Automatic install is Windows-only; Linux and macOS get the verified file
  revealed.
- The desktop's in-app install does not resume across an app restart: the
  verified-path list is in memory, so a restart means downloading again. The
  phone persists the equivalent record; the desktop has not needed it yet.
