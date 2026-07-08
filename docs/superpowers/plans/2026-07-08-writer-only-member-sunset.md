# Writer-Only Member Sunset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove unverified non-Writer members from the active LamTools product surface so the repo becomes Writer + Core first, with Artist reserved for a future clean rebuild.

**Architecture:** Keep `core/` as the shared base and `members/writer/` as the only active product member. Delete `members/artist/` and the unregistered `members/imager/`, then remove active scripts, ports, docs, and smoke tests that expose those members as runnable products. Historical docs can continue to mention Artist when they are clearly historical.

**Tech Stack:** Python 3.14, PowerShell, Vue/Vite frontends, Playwright smoke tests, existing LamTools scripts.

## Global Constraints

- PowerShell involving Chinese must use UTF-8; avoid here-string or pipe-passed Chinese test text.
- Do not modify unrelated dirty files.
- Do not touch `core/` or `members/writer/` business code unless a live Artist/Imager reference breaks Writer-only operation.
- Do not recreate Artist in this task.
- Do not commit unless explicitly requested.
- Treat `members/artist/` as deleted source, not archived source; Git history is the rollback path.

---

### Task 1: Remove Active Member Directories And CLI Shims

**Files:**
- Delete: `members/artist/`
- Delete: `members/imager/`
- Delete: `artist.cmd`
- Delete: `scripts/artist.cmd`

**Interfaces:**
- Consumes: user confirmation that only Writer remains active.
- Produces: filesystem has no active Artist/Imager member directories or Artist root command.

- [ ] **Step 1: Verify delete targets are inside the repo**

Run:

```powershell
$root = (Resolve-Path -LiteralPath '.').Path
$targets = @('members\artist', 'members\imager', 'artist.cmd', 'scripts\artist.cmd')
$targets | ForEach-Object {
  $path = Join-Path $root $_
  if (Test-Path -LiteralPath $path) {
    $resolved = (Resolve-Path -LiteralPath $path).Path
    if (-not $resolved.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
      throw "Refusing to delete outside repo: $resolved"
    }
    $resolved
  }
}
```

Expected: all printed paths begin with `E:\LamTools`.

- [ ] **Step 2: Delete the confirmed targets**

Run:

```powershell
Remove-Item -LiteralPath 'members\artist' -Recurse -Force
Remove-Item -LiteralPath 'members\imager' -Recurse -Force
Remove-Item -LiteralPath 'artist.cmd' -Force
Remove-Item -LiteralPath 'scripts\artist.cmd' -Force
```

Expected: commands complete without error.

- [ ] **Step 3: Verify active member directories**

Run:

```powershell
Get-ChildItem -LiteralPath 'members' -Directory | Select-Object -ExpandProperty Name
```

Expected: `writer` only.

### Task 2: Convert Root Docs And Governance To Writer-Only

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `PRODUCT.md`

**Interfaces:**
- Consumes: Task 1 deletes non-Writer members.
- Produces: current entry docs describe Writer as the only active member and Artist as future rebuild, not runnable current product.

- [ ] **Step 1: Update `README.md`**

Change the directory tree, component table, development commands, component links, and migration note so they no longer present Artist as active.

- [ ] **Step 2: Update `AGENTS.md`**

Change structure wording from “Writer、Artist 等” to “当前仅 Writer”； remove Artist commands from the common entry block; clarify future members must be scaffolded cleanly.

- [ ] **Step 3: Update `PRODUCT.md`**

Change product purpose from “LamWriter, LamArtist, and future member products” to “LamWriter first, with future member products rebuilt from the current Core base.”

- [ ] **Step 4: Search current docs for remaining active-entry claims**

Run:

```powershell
rg -n "members/artist|artist\.cmd|dev\.ps1 artist|LamArtist|Artist 产品" README.md AGENTS.md PRODUCT.md
```

Expected: no active runnable Artist entry remains in these current entry docs.

### Task 3: Remove Artist From Scripts And Ports

**Files:**
- Modify: `scripts/ports.json`
- Modify: `scripts/dev.ps1`
- Modify: `scripts/build.ps1`
- Modify: `scripts/test.ps1`
- Modify: `scripts/lamtools_cli.py`
- Modify: `scripts/member_cli.py`

**Interfaces:**
- Consumes: active members are `core` and `writer`.
- Produces: `lamtools` and PowerShell scripts no longer accept or start Artist.

- [ ] **Step 1: Update `scripts/ports.json`**

Remove the `artist` port block and keep only `core` and `writer`.

- [ ] **Step 2: Update PowerShell scripts**

In `dev.ps1`, `build.ps1`, and `test.ps1`, remove Artist switch cases, remove Artist from `all`, and update usage/error text to `core|writer|all`.

- [ ] **Step 3: Update `scripts/lamtools_cli.py`**

Remove `artist` from target choices and `_targets("all")`. Keep member scanning generic, but active command choices should be `core`, `writer`, `all`.

- [ ] **Step 4: Update `scripts/member_cli.py`**

Remove Artist command dispatch. Keep Writer dispatch and unknown-member error.

- [ ] **Step 5: Verify script references**

Run:

```powershell
rg -n "artist|Artist|members\\artist|members/artist|artist\.cmd" scripts README.md AGENTS.md PRODUCT.md
```

Expected: no active script or current entry doc references remain.

### Task 4: Remove Artist Smoke Tests And Current Test Claims

**Files:**
- Delete: `e2e/tests/artist-smoke.spec.ts`
- Modify: `e2e/README.md`
- Modify: `docs/test-layering.md`

**Interfaces:**
- Consumes: Artist is no longer active.
- Produces: test docs and smoke suites no longer expect Artist to run.

- [ ] **Step 1: Delete Artist smoke spec**

Run:

```powershell
Remove-Item -LiteralPath 'e2e\tests\artist-smoke.spec.ts' -Force
```

Expected: file removed.

- [ ] **Step 2: Update E2E docs**

Remove Artist smoke instructions from `e2e/README.md`; keep Writer smoke.

- [ ] **Step 3: Update test layering docs**

Mark Artist tests as removed with the member; update current verification to Core + Writer.

- [ ] **Step 4: Verify E2E references**

Run:

```powershell
rg -n "artist|Artist|5174|6171" e2e docs/test-layering.md
```

Expected: no current smoke/test-layering reference requiring Artist.

### Task 5: Update Current Architecture Reports To Record The Sunset

**Files:**
- Modify: `docs/architecture-audit/2026-07-08-lamtools-architecture-summary.md`
- Modify: `docs/architecture-audit/2026-07-08-structure-organization-plan.md`

**Interfaces:**
- Consumes: this task changes active repo shape after the audit.
- Produces: audit docs remain historically useful but clearly marked as pre-sunset snapshots.

- [ ] **Step 1: Add maintenance note to structure plan**

Add a top note saying the report was written before the Writer-only sunset, and Artist module sections are retained as historical evidence for why deletion was chosen.

- [ ] **Step 2: Add maintenance note to summary**

Add a top note saying Artist/Imager have been removed from active product scope after this audit; future Artist should be rebuilt from a clean member.

- [ ] **Step 3: Verify notes**

Run:

```powershell
rg -n "Writer-only|下线|重做|historical|历史" docs/architecture-audit/2026-07-08-*.md
```

Expected: both current audit docs have clear maintenance notes.

### Task 6: Verify Writer-Only Surface

**Files:**
- No planned edits.

**Interfaces:**
- Consumes: all deletion and reference cleanup tasks.
- Produces: evidence that the active repo no longer exposes Artist/Imager and Writer/Core still have valid entry points.

- [ ] **Step 1: Check member list**

Run:

```powershell
.\lamtools.cmd members list --json
```

Expected: output lists `writer` and does not list `artist` or `imager`.

- [ ] **Step 2: Check active references**

Run:

```powershell
rg -n "members/artist|members\\artist|artist\.cmd|dev\.ps1 artist|test\.ps1 artist|build\.ps1 artist|LamArtist" README.md AGENTS.md PRODUCT.md scripts e2e docs/test-layering.md
```

Expected: no current active references.

- [ ] **Step 3: Run syntax checks for edited Python scripts**

Run:

```powershell
py -3.14 -m py_compile scripts\lamtools_cli.py scripts\member_cli.py
```

Expected: no output and exit code 0.

- [ ] **Step 4: Run whitespace check for touched files**

Run:

```powershell
git diff --check -- README.md AGENTS.md PRODUCT.md scripts e2e docs/test-layering.md docs/architecture-audit
```

Expected: no output and exit code 0.

- [ ] **Step 5: Show final status**

Run:

```powershell
git status --short
```

Expected: Artist deletions and the planned docs/scripts edits appear; unrelated pre-existing dirty files remain untouched.
