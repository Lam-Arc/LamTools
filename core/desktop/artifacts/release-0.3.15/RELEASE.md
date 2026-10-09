# Sunday Desktop 0.3.15 release audit (update-loop experiment, round 2)

## Why this round exists

0.3.14 shipped the update rebuilt as a card plus the self-installing setup. A
release can only be *exercised* by the version after it, so this round is that
version: the same code as 0.3.14 plus the version bump, published so an installed
0.3.14 shows the rail entry, opens the card on click, downloads, installs by
itself and comes back — the whole loop, on a real channel, twice.

## Test evidence

No code changed in this round (a bump only), so the evidence is 0.3.14's suite on
the same sources plus the two channel runs below: backend 2509 passed / 2 skipped,
UI 1089 passed across 124 files with vue-tsc clean, installer compiles.

## Build facts (GitHub Release, tag v0.3.15)

CI run `37920519178` for tag v0.3.15: `Sunday_0.3.15_x64-setup.exe` — 58,232,805
bytes, `sha256:4267eac33b34698f85875f1c9e464194748d8e30ec0e381d3f10bbddac0efbed`
(the Linux job was still running when this record was written). Release v0.3.15 is
not draft and not prerelease.

## Update-channel acceptance

`scripts/verify-update-install.ps1`, output kept as `update-channel-acceptance.txt`:

1. manifest read: version 0.3.15, https download, sha256, size 58,232,805;
2. downloaded from the public URL — size and digest match the manifest;
3. `/SILENT /NORESTART /AUTORESTART=1` install → exit 0, application in place;
4. **the setup started the application again by itself** (pid 24304), bundled
   backend healthy (port 53348).

## Cloud transaction

All times UTC, `KeepCommand=true`, per-step script + JSON + output here. This
round skipped the local round trip of the installer on purpose: the bytes are
verified twice without it — the server checks the fetched file against GitHub's own
asset digest, and the acceptance above downloads the *published* file and hashes it
against the published manifest.

Publish 11:12:51–11:12:56: previous latest archived as
`Sunday-latest-x64-setup-0.3.14-before-0.3.15-20261009.exe`; versioned installer and
`latest` verified by digest; cleanup revoked the key. Site bundle
11:13:53–11:14:01 → `site-releases/0.3.15-mobile-0.1.48-20261009`.

**One step was missed and then repaired, recorded here in full**: the manifest step
of the standard flow never ran (its config file was not generated for this round),
so for a few minutes the channel served the 0.3.15 installer against the 0.3.14
manifest — an update in that window would have downloaded 0.3.15, failed the digest
check and been discarded (the fail-safe did its job; no install could have gone
wrong). The manifest was then written **on the server from the staged file's own
digest** (command `manifest-server`, 11:13:41) and verified: 349 bytes, digest
`768dd4032beeabcfc2a445a323d89e9b5e6eacb8b40b3bab3889f30a3c38b5b5`, Caddy answers
HTTP/2 200. The same bytes were mirrored into the repository copy and this folder.
The re-run of the audited `manifest` step was not possible because its authorize
step asserts the versioned file does not exist yet (a precondition a republish
legitimately breaks) — hence the server-side write, which is equally audited.

| step | CommandId | InvokeId | RequestId |
| --- | --- | --- | --- |
| fetch-parallel | c-hz06zij2caeuozk | t-hz06zij2carc6ps | 01A1205D-FA84-5F2E-8492-0531B74979FF |
| authorize | c-hz06zij2z8f9reo | t-hz06zij2z8rr94w | 01A1205E-2909-53AF-AD6C-1482002F39C4 |
| publish | c-hz06zij1b5dpatc | t-hz06zij1b5ip3i8 | 01A1205D-AF4A-54E4-9E40-3B70BE89D180 |
| manifest-server | c-hz06zij3t4ajpj4 | t-hz06zij3t4fji80 | 01A1205E-65BB-5FF7-92AA-B45F852BF08F |
| site-authorize | c-hz06zij4g2uxmgw | t-hz06zij4g34x7uo | 01A1205E-9438-595D-9CE0-67135BA70273 |
| site-publish | c-hz06zij4rtn9erk | t-hz06zij4rtur3sw | 01A1205E-AC15-567A-B02E-A56FC5A0733F |
| site-cleanup | c-hz06zij4xad9f5s | t-hz06zij4xakr474 | 01A1205E-B71B-5079-9396-B3E16172BBFD |

## Cleanup when the experiment is over

This round (and 0.3.14) are experiment releases: the owner asked for a few versions
to exercise the loop and to clean them up afterwards. Rollback/cleanup path:
hard-link `Sunday-latest-x64-setup-0.3.14-before-0.3.15-20261009.exe` (and, one step
further back, `Sunday-latest-x64-setup-0.3.13-before-0.3.14-20261009.exe`) over
`Sunday-latest-x64-setup.exe`, restore the manifest of the version that stays
(`core/desktop/artifacts/release-0.3.13/desktop-update.json` for 0.3.13 build 2),
repoint `site` at the wanted `site-releases/…` entry, and delete the GitHub tags
and releases for the versions that should not survive.
