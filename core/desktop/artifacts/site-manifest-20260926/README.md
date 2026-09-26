# The desktop update manifest was never published (404), and the desktop had no in-app install

Date: 2026-09-26. Status: **manifest published and verified**; the in-app
download/install is implemented and tested, and ships with the next desktop
release.

## Symptom

`https://47.114.43.99.nip.io/downloads/desktop-update.json` answered **404**.
The desktop checker (`core/src/lamtools_core/update/checker.py`) reads that
manifest first and falls back to GitHub Releases, so every install silently used
GitHub: workable here, poor exactly where the site exists for — regions where
GitHub is slow or blocked. Nothing in the release flow uploaded the manifest, and
`core/desktop/update-manifest.json` (the repository copy
`scripts/build-desktop-update.py` writes) did not exist either, so the gap was
invisible from the repository.

The second half of the problem was the install step itself: 「下载安装包」 opened a
browser at the installer URL and the settings section said "下载完成后请先退出
Sunday，再运行安装包完成升级". Nothing downloaded, verified or ran anything.

## Fix

1. **Published the manifest.** `scripts/build-desktop-update.py` now embeds the
   installer's `sha256` and `size` (and `linux_sha256`/`linux_size` when a Linux
   bundle exists), the repository copy is regenerated from the **published
   installer** — the local bundle has no 0.3.6 artifact, so it was downloaded from
   the site and hashed — and
   `core/desktop/artifacts/site-manifest-20260926/deploy.py` uploaded it with the
   same audited shape a mobile release uses (restricted key, verify, publish,
   revoke).

   ```
   HTTP/2 200   content-length: 346
   { "version": "0.3.6", "download_url": "…/Sunday_0.3.6_x64-setup.exe",
     "sha256": "2c0f61c0…", "size": 94081829, … }
   ```

   The tree has moved to `0.3.7-beta.1` while 0.3.6 is still the published stable,
   so the manifest describes the published artifact and was generated with
   `--allow-version-mismatch` — the flag's documented purpose. When 0.3.7 ships,
   the release regenerates it from the new installer with the versions matching.

2. **In-app download → verify → run** (`core/src/lamtools_core/update/installer.py`
   + `operations.py`): `update.download` re-reads the manifest for its URL and
   digest rather than trusting the caller, streams the installer with httpx into
   the update directory, and only renames it out of its `.part` name when the
   digest matches; `update.install` runs only a file this process verified, via
   `os.startfile` on Windows and by revealing the folder elsewhere. The UI grows
   the digest-gated 「下载安装包」 → 「立即安装」 flow shared with mobile.

## Test evidence

`core/tests/test_update_installer.py`, 12 tests: verified download over loopback,
digest mismatch discards the artifact *and* the partial, unusable digest refused
before any request, plain http refused away from loopback, traversal attempts
reduced to a base name, an unsafe name refused, `run_installer` refuses an
unverified path and refuses when nothing was downloaded, the Windows launch path
via a patched `os.startfile`, `update.download` refusing without a digest, and
the operation using the manifest it just read.

## Evidence in this directory

`deploy.py`, `cloud.py`, `desktop-update.json` (946 bytes… 346 bytes as published),
per-step JSON and shell scripts from the runner, and `local-transfer.json`.

Published state, verified from outside: 200 with the digest above; server-side
`sha256sum /var/www/lamtools/desktop-update.json` matches
`e06c9001cbaedb57…`; `authorized_keys` back to its one-line baseline.

## Still open

- The desktop change reaches users with the **next desktop release**: the version
  is already `0.3.7-beta.1` in the tree, and shipping it means a tag push that
  triggers `release.yml`. Until then, stable 0.3.6 installs get the working site
  manifest but keep the browser-based download.
- Automatic install is Windows-only by design (Linux/macOS have no single
  "run this installer" contract); those platforms get the verified file revealed.
