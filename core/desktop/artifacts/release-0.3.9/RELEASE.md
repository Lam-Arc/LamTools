# Sunday Desktop 0.3.9 release audit

This record covers the **official-site channel** for 0.3.9. The GitHub side was cut by
the release workflow: tag `v0.3.9` on commit `2d0bf435`, CI run `36518406766`,
release `https://github.com/Lam-Arc/LamTools/releases/tag/v0.3.9` published at
2026-09-29T03:53:56Z with `Sunday_0.3.9_x64-setup.exe` (58,244,167 B). The Linux
assets (AppImage/deb) were still building in the same run when this record was
written.

## What shipped

- Guided instructions appear where the kernel actually drains them, so the visible
  user bubble sits after everything already written and before everything written
  afterwards; the composer's direct steer path is visible in the transcript too.
- Reasoning ladders follow each model's own declaration (20 of 25 adapter profiles
  declare a real one, 5 have none), the model jsonc can override it, and a level a
  model never declared is neither offered nor sent.
- The composer draft is kept per conversation and persisted (survives a restart).
- Markdown forms while it streams: closed segments render through the full pipeline,
  the open tail is rate-limited, mermaid/SVG/plot blocks still wait for the turn to
  end, and a code block containing a blank line is no longer split.
- The operator's own send/stop button size tweak, which was in the tree uncommitted.

## Why this record exists at all

Installed clients read `downloads/desktop-update.json` first (the official site is the
primary channel; GitHub Releases is the fallback, and the tie-break prefers the site).
After the GitHub release the site still described 0.3.8, so a fresh download would have
fetched the 0.3.8 installer and an installed 0.3.8 would only have been offered 0.3.9
through the GitHub fallback. This session closed that gap.

## Evidence

- Installer channel: `Sunday_0.3.9_x64-setup.exe` and `Sunday-latest-x64-setup.exe`
  both 200 at 58,244,167 bytes; the previous latest (58,235,160 B, sha256
  `c76b6761…`) archived as
  `Sunday-latest-x64-setup-0.3.8-before-0.3.9-20260929.exe`; a full public GET of the
  versioned installer hashes to
  `7b4860b9424c09bd34d310e77e7dd449ab16c2eb5bc8788bc7e3ac6a4fd9bca9`, equal to the
  local file and to the published manifest.
- Manifest: `desktop-update.json` reads version 0.3.9 (published_at
  2026-09-29T04:00:33Z) with that digest; its published body hashes to
  `7d86aae2e13b56a442efd256eab9ffc9008c1966083a8306680c29e6081d9b23`, and
  `deploy.check_manifest()` refused to upload until the repository copy
  `core/desktop/update-manifest.json` agreed field for field.
- Site: republished as `site-releases/0.3.9-mobile-0.1.46-20260929` (previous
  `0.3.8-mobile-0.1.45-20260928` preserved); the bundle `main-DwpZxDCC.js` carries
  both the 0.3.9 and the 0.1.46 labels — the mobile APK and its manifest were
  published in the same pass, recorded in
  `core/mobile/artifacts/release-1046/RELEASE.md`.
- In-app update check from the released tree: `current 0.3.9 / latest 0.3.9 /
  source "site" / up_to_date`, so an installed 0.3.8 is now offered 0.3.9 through
  the site channel.
- Rollback: hard-link the archived 0.3.8 installer back over
  `Sunday-latest-x64-setup.exe`, restore the 0.3.8 manifest
  (`core/desktop/artifacts/release-0.3.8/desktop-update.json`), and repoint `site`
  at `site-releases/0.3.8-mobile-0.1.45-20260928`.

## Cloud transaction

All times UTC, `KeepCommand=true`, per-step script + JSON + output here. Preflight
(read-only) 03:59:59; installer authorize/upload/publish 04:00:09–04:00:36; manifest
published 04:00:50; its key revoked at 04:01:03; site authorize/upload/publish
04:01:13–04:01:25 and revoked at 04:01:36. `authorized_keys` returned to its one-line
baseline after every transfer and both services stayed active.

| step | CommandId | InvokeId | RequestId |
| --- | --- | --- | --- |
| preflight | c-hz06yhruz6pz5z4 | t-hz06yhruz6uyyo0 | 01A0EB51-BF4D-54B4-9677-B1FB8A92F32A |
| authorize | c-hz06yhrvinqhm2o | t-hz06yhrvio2z3sw | 01A0EB51-E6E4-5C46-9DB4-7ABA3C4B73AE |
| publish | c-hz06yhrwu2rl7gg | t-hz06yhrwu2z2whs | 01A0EB52-46DB-5BFB-82D6-C5CAA0859CB1 |
| manifest | c-hz06yhrxpmafe9s | t-hz06yhrxpmmww00 | 01A0EB52-86E8-53E1-BDAD-244DF5AE922F |
| cleanup | c-hz06yhryew8fu2o | t-hz06yhryewkxbsw | 01A0EB52-BA29-55F1-98E0-0FF709BB601F |
| site-authorize | c-hz06yhryzaelrsw | t-hz06yhryzajlkhs | 01A0EB52-E37C-5CF2-95A1-7AD1C3175D13 |
| site-publish | c-hz06yhrzkyrvp4w | t-hz06yhrzkyzde68 | 01A0EB53-0F76-57DE-9B59-F902BAD28F9F |
| site-cleanup | c-hz06yhs07lorf9c | t-hz06yhs07lyr0n4 | 01A0EB53-3D37-5A40-8E83-414BDD9C9EE9 |

## Public verification

`verify_public.py`, every assertion passed: both installer URLs answer 200 at
58,244,167 bytes; a full public GET hashes to `7b4860b9…`; the published manifest
matches on version, digest and body hash; the site's bundle carries both labels.

## Retargeting note for the next release

The 0.3.8 toolchain was copied and retargeted. Two things the retarget missed on the
first pass and the verifier caught: `release.json.manifest_sha256` (the published
manifest's own digest — the mobile `deploy.py` fills this itself, the desktop `deploy.py`
only checks a manifest that must already exist) and the *mobile* version constant inside
`verify_public.py`, which still said 0.1.45 after the desktop bump. The read-only
preflight script also carries a hardcoded previous-version archive name; it listed a
nonexistent path (harmless, no assertion) because `old_version` moved from 0.3.7 to
0.3.8.
