# Sunday Desktop 0.3.8 release audit

This record covers the **official-site channel** for 0.3.8. The GitHub side was cut
by the release workflow before this session started: tag `v0.3.8` (moved from
`558d1e80` to `1adec8b7` after the first run failed the plugin-widget smoke test),
CI run `36400175623` succeeded, and release
`https://github.com/Lam-Arc/LamTools/releases/tag/v0.3.8` was published at
2026-09-28T09:04:55Z with `Sunday_0.3.8_x64-setup.exe` (58,235,160 B),
`Sunday_0.3.8_amd64.AppImage` (188,799,480 B) and `Sunday_0.3.8_amd64.deb`
(122,531,014 B).

## What shipped

The installer carries, in this order of the history it was built from:

- the plugin and skill **platform classes** (`platforms: desktop | mobile |
  universal` in plugin manifests and skill frontmatter, with discovery, install
  and payload behaviour following it — commit `7782c469`);
- the plan plugin (three skills and the tool behind them — `6d12ecaa`);
- the release-flow fix that made the plugin-widget smoke test enable the search
  plugin first (`1adec8b7`), which is why the tag was moved and the first CI run
  is recorded as a failure.

## Why this record exists at all

Installed clients read `downloads/desktop-update.json` first (the official site is
the primary channel; GitHub Releases is the fallback, and the tie-break prefers the
site). After the GitHub release the site still described 0.3.7: a fresh download
would have fetched the 0.3.7 installer and an installed 0.3.7 would only have been
offered 0.3.8 through the GitHub fallback. This session closed that gap.

## Evidence

- Installer channel: `Sunday_0.3.8_x64-setup.exe` and `Sunday-latest-x64-setup.exe`
  both 200 at 58,235,160 bytes; the previous latest (58,166,212 B, sha256
  `93338593…`) archived as
  `Sunday-latest-x64-setup-0.3.7-before-0.3.8-20260928.exe`; a full public GET of
  the versioned installer hashes to `c76b67615955c870a8cdaab61fecf4e1c08e4d29b04bb1a123dd74b45b8c5e6e`,
  equal to the local file and to the built manifest.
- Manifest: `desktop-update.json` now reads version 0.3.8 with that digest and a
  `download_url` that resolves to the same length; its published body hashes to
  `cdaa2daace3a2e192f7651bb07bfd4d976f1a1592e2be3c51831b963e16345da`, equal to the
  repository copy `core/desktop/update-manifest.json` (checked by
  `deploy.check_manifest()` before the upload).
- Site: republished as `site-releases/0.3.8-mobile-0.1.45-20260928` (previous
  `0.3.7-mobile-0.1.45-20260928` preserved); the bundle `main-B8o9YTys.js` carries
  both the 0.3.8 and the 0.1.45 labels.
- Rollback: hard-link the archived 0.3.7 installer back over
  `Sunday-latest-x64-setup.exe`, restore the 0.3.7 manifest (recorded in
  `core/desktop/artifacts/release-0.3.7/desktop-update.json`), and repoint `site`
  at `site-releases/0.3.7-mobile-0.1.45-20260928`.

## Cloud transaction

All times UTC, `KeepCommand=true`, per-step script + JSON + output here. Preflight
(read-only) 10:21:52; installer authorize/upload/publish 10:22:24–10:23:14, its key
revoked at 10:23:50; manifest authorize/upload/publish/cleanup
10:25:28–10:25:35; site authorize/upload/publish/cleanup 10:27:08–10:27:49.
`authorized_keys` returned to its one-line baseline after every transfer and both
services stayed active.

One step failed on the way and is worth recording: the first
`deploy.py manifest` run aborted in `check_manifest()` because the manifest had
been generated next to the installer (`release/desktop/`) instead of in this
directory — no remote command ran, but the chain's `cleanup` still executed (the
shell pipeline's exit status came from `tail`), which left the site serving the
0.3.8 installer with the 0.3.7 manifest for about two minutes. No mutation was
wrong: the installer publish itself had completed and verified. `manifest_republish.py`
exists for exactly that state — it authorizes with the *new* digest (the
precondition `deploy.py authorize` can assert only before the publish), uploads the
manifest, publishes it and revokes the key.

| step | CommandId | InvokeId | RequestId |
| --- | --- | --- | --- |
| preflight | c-hz06yf5gx7rl14w | t-hz06yf5gx81kmio | 01A0E789-0AD0-54C6-9FF2-DA5589EE1E2F |
| authorize | c-hz06yf5indimbk0 | t-hz06yf5indv3ta8 | 01A0E789-896E-516E-9C82-8A1B2BB5F340 |
| publish | c-hz06yf5l7u4b7cw | t-hz06yf5l7u9b01s | 01A0E78A-4D2F-5672-A235-892765D4A56E |
| cleanup | c-hz06yf5nagqlkao | t-hz06yf5nagy39c0 | 01A0E78A-DB60-566C-B53D-9C5F55B03CEA |
| manifest-authorize | c-hz06yf5si1o3mdc | t-hz06yf5si1t3f28 | 01A0E78C-57B1-5C62-BC97-054CCC56A647 |
| manifest | c-hz06yf5spgv84jk | t-hz06yf5spha7im8 | 01A0E78C-66D9-5702-B464-532C3682CE2A |
| manifest-cleanup | c-hz06yf5sux19edc | t-hz06yf5sux69728 | 01A0E78C-71CE-5C73-AB62-B2A1FD2E7457 |
| site-authorize | c-hz06yf5xv6ih14w | t-hz06yf5xv6uyiv4 | 01A0E78D-E054-5537-864E-9071D5FF8B0B |
| site-publish | c-hz06yf5zw4x7g1s | t-hz06yf5zw54p534 | 01A0E78E-7349-5B82-892E-12FEA1AD08D2 |
| site-cleanup | c-hz06yf60290ri0w | t-hz06yf60295raps | 01A0E78E-8016-51C5-84AD-437EDE9F55D8 |

The `cleanup` row is the installer key's revocation from the aborted chain (that
step ran and verified the published installer and manifest); the `requestId` values
are the result polls, as in the mobile records.

## Public verification

`verify_public.py`, all assertions passed: both installer URLs answer 200 with
58,235,160 bytes; a full public GET hashes to `c76b6761…` (the local build); the
published manifest reads version 0.3.8 with the installer's digest, its body hashes
to the recorded manifest digest, and its `download_url` resolves to the same
length; the site bundle carries both the 0.3.8 and 0.1.45 labels.

## Installed-build acceptance

`install_setup.ps1` installed the release into `E:/setuptest/0.3.8` from
`release/desktop/Sunday_0.3.8_x64-setup.exe` and launched it. The first attempt
timed out ("lamcore.exe did not remain running within 20s", PID 2804): a Tauri dev
instance from this session was still running against the same app data, and the
installed app exits behind it. After stopping the dev instance the installed build
came up and stayed up — `lamcore.exe` PID 23972 and its backend
`E:/setuptest/0.3.8/lamcore-backend/LamCore.exe` PID 26152, both from the 0.3.8
install directory.

Screenshots next to this record (`E:/LamTools/release/desktop/setup-0.3.8-*.png`):

- the shell renders with the project list read from its backend ("MyProject",
  "暂无会话 · 新建会话") — the HTML-as-JSON failure mode would have produced an
  error here instead;
- 设置 → 模型与供应商 renders its list from the backend (empty state, "还没有供应商",
  with 新增供应商) — no provider was written during this acceptance;
- 设置 → 关于与更新 reads 当前版本 0.3.8 and, after its own update check through the
  backend, 已是最新版本（v0.3.8 · 来源：官网） — i.e. the installed build detects
  itself as current from the manifest this session published, on the official-site
  channel rather than the GitHub fallback.

## Still open

- Automatic install stays Windows-only; Linux and macOS get the verified file
  revealed (unchanged from 0.3.7).
- The in-app check emulation from an installed 0.3.7 was not repeated here: the
  site manifest now carries the same version, digest and download URL that the
  check reads, which is what the emulation asserted.
