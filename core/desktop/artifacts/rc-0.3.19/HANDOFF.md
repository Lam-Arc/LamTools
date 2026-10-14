# Infrastructure Task 3 — pending Windows candidate acceptance

> Superseded by completed acceptance in REPORT.md. Final production installer
> and hashes are in artifact-inventory.json. acceptance-result.txt is passed;
> Python final suite: 3,017 passed / 2 skipped. Local candidate GO; stable
> publication NO-GO pending required Tauri user acceptance. No publication,
> commit, tag, or production deployment was performed. Resume from REPORT.md,
> not the historical pending instructions below.

User requested local release-candidate preparation from the existing working
tree. Do not commit, tag, publish, deploy services, or overwrite public artifacts.
Six-digit WAN pairing is deprecated/unsupported and is not a release gate.
Mobile, runtime migration, repository extraction and unrelated refactoring are
outside scope. All model testing must use local mocks, not paid calls.

## Current work

- Locally synchronized five primary version sources to 0.3.19 using
  scripts/bump-version.ps1; desktop package-lock root version also synchronized.
  No 0.3.19 installer existed before starting, so prior stable installers remain.
- Full Python suite is running: python-tests.log / python-tests.exit.txt.
  Three failures appeared around 21%; diagnose final traceback when complete.
- UI initial run: 1363 passed, 9 failed. Fixed missing Resume/retry translations
  in all four locales and corrected stale tests for current Library copy and
  composer queue-panel/glass placement. No coverage removed.
- UI final: all 147 files / 1372 tests passed. UI typecheck passed (exit file 0).
- Desktop Rust: 70 passed for 0.3.19.
- Fixed brittle release-skill assertion in test_plugin_packaging_boundary.py:
  now parses the explicit required-plugin list and requires exactly the same
  three IDs, independent of punctuation. Full-suite collection may have loaded
  the old test; rerun this test separately.
- Fixed bump-version.ps1's dangerous printed bulk tag-push advice; it now
  recommends pushing only the approved new tag. Nothing was pushed.
- Production scripts/package.ps1 is running, logs package.log / package.exit.txt.
  Uses actual Vite, PyInstaller, Tauri --no-bundle, Inno Setup pipeline.
- post-build.ps1 is queued to await successful build, hash/copy the installer
  into this evidence directory, run required installer skill under
  E:\setuptest\0.3.19, then close only that isolated app and run CI's installer
  lifecycle acceptance. Inspect post-build.log and phase logs for actual results.

## Remaining work / current recommendation

NO-GO until remaining results are assessed. Diagnose/fix release-blocking
failures and rebuild/reverify if product source changes. Record exact installer
path, size and hash; audit bundled resources, optional-plugin exclusion and
required git/websearch/imagegen inclusion. Workflow is an optional plugin and
must remain excluded from the installer; test persistence with an isolated
external plugin fixture if packaged acceptance needs it.

Run focused integration regressions for same-turn Stop/Resume, sub-agent
consistency, steering, plugin lifecycle, Workflow persistence, raw recording,
Core API security and settings-draft protection. Source tests are automated
evidence; actual Tauri appearance/click behavior is not verified by them.

Verify upgrade **from 0.3.18 to 0.3.19** using the existing preserved 0.3.18
installer and isolated data/config/projects/conversation fixtures. Existing
verify-desktop-lifecycle.ps1 only upgrades the candidate over itself and checks
marker preservation: this is insufficient for the requested cross-version DB
history/config acceptance. Do not touch real user installations or data.
Check rollback behavior, including schema/data compatibility and backup recovery.

Inspect official metadata and GitHub fallback read-only; create candidate
metadata privately in this evidence directory. scripts/build-desktop-update.py
normally writes website/public manifest copies: do NOT invoke its main unless
those outputs are explicitly redirected/kept local. No production publication.
Prepare changelog, artifact inventory, tested/unverified matrix and GO/NO-GO.

Read .agents/skills/release-lamtools/SKILL.md and
.agents/skills/lamtools-setup-install/SKILL.md for release/installer contracts.
User overrides clean-worktree/commit/tag/publication steps for this candidate.
No Computer Use allowed; user appearance confirmation remains unperformed.
