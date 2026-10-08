# Sunday Desktop 0.3.11 release audit

## What shipped

Everything on `codex/multiplatform-dev` since v0.3.10 (3d40ee4e):

- **The library is curated by the agent, not filled automatically** (2b6a…, the
  `feat(core)` library commit): a new built-in `library` tool (list / register /
  favorite / folder / remove / restore, auto-allowed) files deliverables into the
  project catalog (资料库) deliberately; the persistence path no longer registers
  anything on the side, so intermediate debris stops piling up and a bookkeeping
  failure can no longer take a turn down.
- **The sub-agent runs beside the chat** (97318b6d): tapping a delegation row
  splits the conversation area and shows the child's own process — reasoning,
  tool calls and final answer. The projector used to read `sub_agent_message` as
  "a sentence was sent", so a delegated run could never show what it did; the
  backend also stamps `sub_agent_message` with the current run now (26936120), so
  children no longer file their timeline under a phantom parent.
- **审批 / 提问 reads as a card you answer in place** (5b804f58) and **the
  library walks its layers** (40a7b7fa).
- **Fixes**: one plan card per batched checklist update (7ee47737); optional
  arguments a model fills with the literal `"null"` are read as unset (fed75a45);
  a gateway's undecodable reply stays retryable (cd0c1849); the streaming idle
  timeout default moves 120s → 180s so a slow first token is not mistaken for a
  stall (3a42545f).

## Test evidence

Run against the tree this installer was built from (df82d2f4):

- desktop backend: **2465 passed / 2 skipped** (the count moved with the plan and
  memory work that landed before this batch; this batch adds 10 backend tests and
  replaces one containment test with the stricter "persistence never touches the
  artifact store" contract).
- shared UI: **1038 passed** across 121 files, `npm run typecheck` (vue-tsc incl.
  tsconfig.test.json) clean.
- mobile: 290 passed, `vue-tsc` clean.

## Build facts (GitHub Release, tag v0.3.11)

CI run `37758569728` (`Build & Release` for tag v0.3.11) **succeeded**: frontend
build → PyInstaller → backend smoke → WebSocket handshake smoke → Tauri
`--no-bundle` → Inno Setup → install/upgrade/uninstall lifecycle with data
retention → upload. Release assets (not draft, not prerelease):

| asset | bytes | digest |
| --- | --- | --- |
| `Sunday_0.3.11_x64-setup.exe` | 58,057,917 | `sha256:8f823e3e…aec6ef` |
| `Sunday_0.3.11_amd64.deb` | 122,494,636 | — |
| `Sunday_0.3.11_amd64.AppImage` | 188,738,040 | — |

`https://github.com/Lam-Arc/LamTools/releases/tag/v0.3.11`;
`update check --json` reads `up_to_date` / `latest_version 0.3.11` with
`source: site`.

## Installer provenance (different from 0.3.9 / 0.3.10)

This machine cannot reach the GitHub API or release assets: a local relay answers
`api.github.com` with a certificate for another host
(`x509: certificate is valid for api.arcuid.dev`), and `github.com` over the
proxy returns nothing at all. The installer therefore came to the site the other
way round:

1. the **server** fetched the release asset (`fetch`, then `fetch-parallel`);
2. it came back down over the audited sftp key and was verified locally —
   58,057,917 bytes, `8f823e3e…`, equal to the digest GitHub reports for the
   asset and to the local copy;
3. the setup acceptance ran on that local copy;
4. that same copy was uploaded to the publish stage.

Three failed fetches are recorded and were discarded:

- a single-stream `curl` ran at ~19 KB/s and was cut at the command timeout;
- the first parallel attempt also used HTTP/2 → `curl: (92) PROTOCOL_ERROR`, and
  the parts it left behind were written by a **stray curl from a stopped
  invocation** — it produced a full-size file whose digest did not match. The
  digest check rejected it, which is why the check exists. The stray processes
  were killed (`codex-fetch-cleanup`) and the work directory cleared;
- the public mirror `gh-proxy.com` (~1 MB/s, 20× the canonical host from here)
  then produced bytes hashing to GitHub's own asset digest, so it was accepted.
  The canonical host stays in the script as the fallback. The mirror could not
  have faked the artifact: the size and digest both come from GitHub's release
  metadata.

## Setup acceptance (E:\setuptest\0.3.11)

Silent install succeeded from
`E:\LamTools\release\desktop\Sunday_0.3.11_x64-setup.exe` into
`E:\setuptest\0.3.11`; payload carries `lamcore.exe` (FileVersion 0.3.11,
FileDescription “Sunday”) and `lamcore-backend\LamCore.exe`. Verified on the
**installed** payload:

- `scripts/verify-backend-ws.py --exe E:\setuptest\0.3.11\lamcore-backend\LamCore.exe`:
  `[OK] REST /api/health reachable` and `[OK] WebSocket initialize +
  plugin.enable(websearch) + study.session + websearch.widget.snapshot
  round-trip succeeded`;
- plugin boundary: `resources/plugins/bundled/` contains `git`, `imagegen`,
  `plan`, `study`, `websearch` — no `emotion-ball-pet`, no `workflow`;
- notice (pre-existing, also in 0.3.10): the payload ships an empty `MyProject/`
  directory inside `lamcore-backend/`.

**Deferred item — the GUI main program.** `install_setup.ps1` reports
`lamcore.exe did not remain running within 20s`: the app uses
`tauri_plugin_single_instance`, and two other instances were live — the owner's
Tauri dev window (`core/desktop/src-tauri/target/debug/lamcore.exe`, PID 4100)
and a demo-video instance (`E:\LamDemo\cargo-target\debug\lamcore.exe`, PID
23768). A detached install cannot outbid them, and neither was closed for this
run (the demo instance belongs to another session's take). The 0.3.10 audit hit
the same symptom and closed the dev instance before the check passed; closing
them is a one-line repeat of the same helper call.

## Cloud transaction

All times UTC, `KeepCommand=true`, per-step script + JSON + output here.
Preflight (read-only) 09:48:13 confirmed services active, site at
`0.3.10-mobile-0.1.47-20260930`, `latest` = 0.3.10 (`c0af8309…`), manifest =
0.3.10, the one-line `authorized_keys` baseline, and every new path absent.
Publish 10:56:25–10:56:45: the previous latest archived as
`Sunday-latest-x64-setup-0.3.10-before-0.3.11-20261008.exe`, versioned installer
and `latest` verified by digest, `desktop-update.json` (349 bytes, digest
`b14e8d2b…`) published and answered 200 by Caddy. `authorized_keys` back to its
one-line baseline; both services stayed active. The site bundle itself
(`0.3.11-mobile-0.1.48-20261008`, both labels) was republished by the mobile flow
in `core/mobile/artifacts/release-1048`.

| step | CommandId | InvokeId | RequestId |
| --- | --- | --- | --- |
| preflight | c-hz06zer0z26po1s | t-hz06zer0z2gp9fk | 01A11AE9-CD36-522C-B0FA-07D749453F13 |
| fetch-parallel | c-hz06zewlrkcnwg0 | t-hz06zewlrkp5e68 | 01A11B23-0B81-57DF-B2AF-4B94AE007E35 |
| authorize | c-hz06zewx8hawjcw | t-hz06zewx8hne134 | 01A11B26-5050-539D-93E2-A0A9932C2CAE |
| publish | c-hz06zex401vh5a8 | t-hz06zex4020gxz4 | 01A11B28-3E8F-53DF-9756-AB065638E79E |
| manifest | c-hz06zex4l8mgu0w | t-hz06zex4l8rgmps | 01A11B28-6983-5C9C-A54D-527B56ACE167 |
| cleanup | c-hz06zex50ysg2rk | t-hz06zex50z2fo5c | 01A11B28-893F-527F-882F-63A40AD6C17B |

Discarded attempts (all read-only towards the site): `fetch` c-hz06zerbmj5jncw /
t-hz06zerbmjd1ce8, `fetch-parallel` (HTTP/2) c-hz06zesr6582p6o / t-hz06zesr65d2hvk
and c-hz06zeu7b3… / t-hz06zeu7b3svjsw, `fetch-cleanup` (stray curl) invoked
t-hz06zewk4rx6yo0.

## Public verification

`verify_public.py` (run from this machine, against the public origin), all
assertions passed: the versioned installer and `latest` both answer 200 with
58,057,917 bytes; a full public GET of
`/downloads/Sunday_0.3.11_x64-setup.exe` hashes to `8f823e3e…`; the published
`/downloads/desktop-update.json` reads version 0.3.11 with that digest and size
(and the published file's digest `b14e8d2b…` matches the uploaded copy); the
site bundle carries the 0.3.11 label.

## Rollback

Hard-link `Sunday-latest-x64-setup-0.3.10-before-0.3.11-20261008.exe` back over
`Sunday-latest-x64-setup.exe` and restore the 0.3.10 manifest
(`core/desktop/artifacts/release-0.3.10/desktop-update.json`; the repository copy
`core/desktop/update-manifest.json` is generated and ignored, and would have to
be regenerated with `scripts/build-desktop-update.py`). GitHub Releases keeps
v0.3.11 regardless.
