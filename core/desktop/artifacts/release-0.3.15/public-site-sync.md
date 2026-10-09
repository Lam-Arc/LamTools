# Public domain brought in step with the published channel

## What was wrong

The registered domain `ainarit.com` does not serve `/var/www/lamtools/site`; it
serves its own copies:

| path | what it is | state found |
|------|------------|-------------|
| `/var/www/ainarit/sunday.html` | the Sunday product page with the download block | labels still `SUNDAY 0.3.10` / `SUNDAY MOBILE 0.1.47` |
| `/var/www/ainarit-preview` | the product UI embedded by that page at `/preview/` | bundle built 2026-09-30, carrying `0.3.10` |
| `/var/www/ainarit/index.html` | the AINARIT brand page | no version references |

The release pipeline repoints `/var/www/lamtools/site` only (and the update
manifests), so nothing in it has ever touched these three. Two consequences were
visible to a visitor: the download block read 0.3.10 eleven releases after that
version shipped, and the two Linux links were broken outright — they point at
`releases/latest/download/Sunday_0.3.10_amd64.{AppImage,deb}`, and the latest
release v0.3.15 contains only `Sunday_0.3.15_amd64.{AppImage,deb}` (confirmed by
listing the release's assets), so both resolved to 404.

`47.114.43.99.nip.io` was already correct throughout: its entry bundle and its
preview chunk both carry 0.3.15, and no cache header on that host holds a stale
page (only `Etag`/`Last-Modified`, so revalidation is heuristic and immediate).

## What was done

One command, `codex-sync-public-site-versions` (CommandId `c-hz06zikwmvwv0g0`,
InvokeId `t-hz06zikwmw1ut4w`, RequestId `01A12070-E101-57AE-80CE-54C841BEFE9B`,
2026-10-09T11:33:51Z), with these effects:

1. `Sunday [0-9.]* · X64`, `SUNDAY MOBILE [0-9.]* · APK` and
   `Sunday_[0-9.]*_amd64` rewritten across `/var/www/ainarit` from the *published
   manifests*, not from a hardcoded version: `desktop-update.json` →
   0.3.15, `mobile-update.json` → 0.1.48. Only `sunday.html` needed a change.
2. `/var/www/ainarit-preview` rebuilt from the released site bundle: the bundle
   copied, `preview.html` promoted to `index.html`, and `/assets/` rewritten to
   `/preview/assets/` for the path Caddy strips. Every one of the 31 asset
   references the new `index.html` makes was checked to exist before the
   directory swap, and the old directory was replaced atomically.

Before either mutation: `/var/backups/ainarit/sunday-before-20261009T113351Z.tar.gz`
and `ainarit-preview-before-20261009T113351Z.tar.gz`.

Rollback: unpack those two archives over `/var/www/ainarit` and `/var/www`. A
second pair was written by the repair rehearsal below
(`-20261009T113656Z`), covering the same content.

## Verification

- `https://ainarit.com/sunday.html` now reads `SUNDAY 0.3.15` and
  `SUNDAY MOBILE 0.1.48`, and links `Sunday_0.3.15_amd64.AppImage` / `.deb`.
- Those two asset names are exactly the ones in GitHub release v0.3.15
  (`Sunday_0.3.15_amd64.AppImage` 188,881,400 bytes, `Sunday_0.3.15_amd64.deb`
  122,637,988 bytes), so the previously broken links resolve.
- `https://ainarit.com/preview/` serves `/preview/assets/preview-CKm9j5Ku.js`;
  that bundle reports `0.3.15`, and all 31 assets it references answer 200.
- `caddy-lamtools` and `lamtools-relay` active before and after.

## Made permanent

`scripts/sync-public-site.sh` is the release step now: it reads the two published
manifests, stamps the page, rebuilds `/preview/` from the released bundle, and
verifies the live domain. `--check` is read-only and exits 1 when out of step, so
release acceptance can gate on it. Installed at
`/usr/local/bin/sync-public-site.sh` (sha256
`8537de804f89df78c134a8e3ae2aa33ab9502494ade925780a3cd5399e1ee9f3`).

Rehearsed, not assumed: command `codex-test-public-site-repair`, CommandId
`c-hz06zil6hnqoow0`, InvokeId `t-hz06zil6hnvohkw`, RequestId
`01A12073-AFE6-5599-BE1A-150901EF72A5`. It set the page to a wrong version
(`0.3.9`), confirmed `--check` reported "out of step", ran the step, and
confirmed the page returned to 0.3.15 with the live check passing.
