# Sunday Desktop 0.3.16 release audit

## What this release carries

The materials library stopped drawing one grey icon for every file: items with
bytes now render themselves (images directly, a video via its first decoded
frame), and items without fall back to a cover drawn from the file's own type
and extension. Recursive search gained an entry and time budget so a scan cannot
run away with the call. Details and test counts are in the two commits
(`516beb79`, `e5dda9c6`).

## Test evidence

Backend `tests/test_workspace_files.py`: 52 passed. UI `materials-view`,
`core-settings`, `video-poster`: 46 passed across 3 files. CI `Build & Release`
run `37935145738` for tag `v0.3.16` gates the installer on the full suites plus
the desktop lifecycle check.

## Build facts (GitHub Release, tag v0.3.16 = e5dda9c6)

`Sunday_0.3.16_x64-setup.exe` — 58,231,193 bytes,
`sha256:16bc6aaeb34d77002c9db8880b9b60d2ccd918af03e00d2e7342794e6e964c9a`.
Release is not draft and not prerelease.

CI run `37935145738` finished **completed / success** with all three assets:

| asset | bytes |
|-------|-------|
| `Sunday_0.3.16_x64-setup.exe` | 58,231,193 |
| `Sunday_0.3.16_amd64.AppImage` | 188,885,496 |
| `Sunday_0.3.16_amd64.deb` | 122,656,912 |

The Linux job finished after the installer was already published, so for a few
minutes the release carried the installer alone and the product page's
version-pinned Linux links had nothing to resolve to. That window is closed; the
links now resolve to the assets above.

## How the bytes were verified

The installer never passed through this machine. The server fetched it from
GitHub and checked it against the size and digest **GitHub itself reports** for
the asset (`fetch-parallel`, 13:27:01–13:27:42), then re-checked the same two
values at publish time so a stage left behind by an aborted run could not ship.
Acceptance then downloaded the *published* file over the public URL and hashed
it against the published manifest, which exercises the URL a client actually
uses rather than a local copy of it.

## Update-channel acceptance

`scripts/verify-update-install.ps1`, output kept as `update-channel-acceptance.txt`:

1. manifest read: version 0.3.16, https download, sha256, size 58,231,193;
2. downloaded from the public URL — size and digest match the manifest;
3. `/SILENT /NORESTART /AUTORESTART=1` install → exit 0, application in place;
4. the setup started the application again by itself (pid 36416), bundled
   backend healthy (port 49813).

`update check --json` on the development tree reads back from the site channel:
`latest_version 0.3.16`, `source site`, `status up_to_date`.

## Cloud transaction

All times UTC, `KeepCommand=true`, per-step script + JSON + output kept here.

| step | CommandId | InvokeId | RequestId |
|------|-----------|----------|-----------|
| preflight | `c-hz06ziuguxjl88w` | `t-hz06ziuguxw2pz4` | `01A120D3-0307-5EC8-981E-A86229204093` |
| fetch-parallel | `c-hz06ziv00n2snwg` | `t-hz06ziv00naacxs` | `01A120D8-7969-581A-98BC-1E1B9703C38A` |
| publish | `c-hz06ziv3fqo5ji8` | `t-hz06ziv3fqvn8jk` | `01A120D9-72E4-5990-8ECA-2B28B5AECD4A` |
| site-authorize | `c-hz06ziv5lrxg8w0` | `t-hz06ziv5ls9xqm8` | `01A120DA-1110-5C9D-A6DA-7F13B423AB86` |
| site-publish | `c-hz06ziv6p9b6lmo` | `t-hz06ziv6p9ioao0` | `01A120DA-6115-5306-B3B4-51C324EDF1E5` |
| sync-public | `c-hz06ziv76p05szk` | `t-hz06ziv76p55log` | `01A120DA-8493-5D70-882F-68E15071C0D5` |
| site-cleanup | `c-hz06ziv7qj9mj9c` | `t-hz06ziv7qjh48ao` | `01A120DA-ACCC-5E5E-BDEB-4C35A5E577E7` |

What each mutation did:

- **publish** 13:28:04–13:28:15: previous latest archived as
  `Sunday-latest-x64-setup-0.3.15-before-0.3.16-20261009.exe`; versioned
  installer and `latest` verified by digest over the public origin (both 200,
  58,231,193 bytes); `desktop-update.json` written on the server from the staged
  file's own digest and mirrored byte-for-byte into
  `core/desktop/update-manifest.json` and this folder.
- **site-publish** 13:29:05–13:29:06: bundle extracted to
  `site-releases/0.3.16-mobile-0.1.48-20261009`, symlink repointed atomically;
  the live entry bundle reads 0.3.16.
- **sync-public** 13:29:14–13:29:15: the public domain stamped from the two
  published manifests (desktop 0.3.16, mobile 0.1.48), `/preview/` rebuilt from
  the bundle the site release now serves; live read-back confirmed and
  `--check` passed afterwards. Backups:
  `/var/backups/ainarit/sunday-before-20261009T132914Z.tar.gz` and
  `ainarit-preview-before-20261009T132914Z.tar.gz`.
- **site-cleanup** 13:29:25: the one restricted key removed,
  `/root/.ssh/authorized_keys` back to its 1-line baseline, no stages left in
  `/var/tmp`.

One code fix was needed inside this round's own tooling, not the product: the
verify step pointed at the wrong directory for the repository manifest and
reported a missing file before it checked anything. Corrected, then the check
read the published manifest, matched it against the repository copy, and
downloaded both the versioned installer and `latest` and hashed them.
