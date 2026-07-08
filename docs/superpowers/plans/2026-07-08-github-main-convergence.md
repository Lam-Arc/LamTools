# GitHub Main Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 arccat-114 在 GitHub 上的结构整理、便携启动、隐藏 CMD 弹窗和 CI 改动吸收到本地代码线，修正误提交和破坏性入口移动，最终归一到本地 `main`，并在用户测试成功前不推送 GitHub。

**Architecture:** 以当前本地开发线为事实源，把 `origin/main` 自 `57e86b0` 之后的改动当作待筛选 patch。保留产品决策和有价值实现，拒绝坏 gitlink、弱 CI、入口破坏和未说明的数据迁移风险。最终通过本地整合分支合入本地 `main`。

**Tech Stack:** Git, GitHub Actions, PowerShell UTF-8, Python 3.14, FastAPI, Vue/Vite, Electron, PyInstaller.

## Global Constraints

- 不直接 `git pull` 或整包 merge `origin/main`。
- 不推送 GitHub；上传必须等用户本机测试通过后再执行。
- 当前远端协作者改动范围是 `57e86b0..origin/main`。
- 当前本地分支是 `codex/core-composer-commands`，相对 `origin/main` 已明显分叉。
- 打包产物例如 `LamWriter-win-unpacked-*.zip` 不纳入提交。
- 本计划文件自身作为首个文档提交纳入整合分支。
- PowerShell 涉及中文必须显式使用 UTF-8。
- 根目录 `AGENTS.md` 必须保留为 agent 规则入口。
- 根目录 `writer.cmd`、`artist.cmd`、`lamtools.cmd` 保留为薄入口；可同时保留 `scripts/` 下真实脚本。
- `members/writer/backend/测试1` gitlink 必须删除，不迁移。
- 数据目录改到项目内是产品决策；需要同步规则、启动脚本、旧库迁移或明确兼容说明。
- CI 的后端测试、前端 lint、前端 build 不能 `continue-on-error: true`。

---

## File Structure

- Modify: `AGENTS.md`
  - 记录新的 Writer 默认数据目录策略，保留根级 agent 入口。
- Modify/Create: `writer.cmd`, `artist.cmd`, `lamtools.cmd`
  - 保留根目录薄入口，内部转发到 `scripts/`。
- Modify/Create: `scripts/writer.cmd`, `scripts/artist.cmd`, `scripts/lamtools.cmd`
  - 保留整理后的脚本位置，供根入口调用。
- Create/Modify: `.github/workflows/ci.yml`
  - GitHub CI 入口，关键检查失败即失败。
- Modify: `members/writer/backend/app/config.py`
  - Writer 数据目录默认迁到项目内，并兼容旧 AppData 数据库。
- Modify: `members/writer/frontend/electron/main.cjs`
  - Packaged portable 模式显式设置 data/user-data 目录并隐藏后端窗口。
- Create/Modify: `start.bat`
  - 根目录一键启动入口，设置 UTF-8，调用 Writer 启动器。
- Create/Modify: `members/writer/start.bat`
  - Writer 目录内一键启动入口。
- Create/Modify: `members/writer/start.py`
  - Writer Web 便携启动器，负责 venv 检查、后端/前端启动、浏览器打开和进程控制。
- Modify: `members/writer/backend/requirements.txt`
  - 吸收远端新增依赖，但避免重复或无用项。
- Delete: `members/writer/backend/测试1`
  - 删除误提交 gitlink。
- Delete if still present and intentionally obsolete: `kbtool-task/`, `test-blog-project/`, `test-mod-site/`, `test-tool-result-demo/`, `test-website-demo/`, `test-website-demo2/`
  - 只删除已确认不属于当前协作源面和运行主线的 demo/test 产物。

---

### Task 1: Establish Safe Integration Branch

**Files:**
- Create: `docs/superpowers/plans/2026-07-08-github-main-convergence.md`

**Interfaces:**
- Consumes: local branch `codex/core-composer-commands`, remote `origin/main`.
- Produces: integration branch `codex/integrate-arccat-main` used by later tasks.

- [ ] **Step 1: Verify tracked working tree is clean except known artifacts**

Run:

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
git status --short
```

Expected: only untracked packaging artifacts such as `LamWriter-win-unpacked-20260707-1109-postcommit.zip` and the plan file `docs/superpowers/plans/2026-07-08-github-main-convergence.md`, or no output after the plan file is committed.

- [ ] **Step 2: Fetch current GitHub state**

Run:

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
git fetch origin --prune
git log --oneline --reverse 57e86b0..origin/main
```

Expected: the arccat-114 commit sequence ending at `97f7ffc fix: remove test syntax error`.

- [ ] **Step 3: Create the local integration branch**

Run:

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
git switch -c codex/integrate-arccat-main
```

Expected: switched to `codex/integrate-arccat-main`.

- [ ] **Step 4: Commit the plan file**

Run:

```powershell
git add docs/superpowers/plans/2026-07-08-github-main-convergence.md
git commit -m "docs: plan GitHub main convergence"
```

Expected: one documentation commit is created.

- [ ] **Step 5: Verify branch setup state**

Run:

```powershell
git status --short
```

Expected: only untracked packaging artifacts, or no output.

---

### Task 2: Import Remote Changes Selectively Without Breaking Root Entrypoints

**Files:**
- Modify/Create: `.github/workflows/ci.yml`
- Modify: `README.md`
- Modify: `core/src/lamtools_core/tool/command.py`
- Modify: `members/writer/backend/app/core/mcp/client.py`
- Modify: `members/writer/backend/app/core/writer/git.py`
- Modify: `members/writer/backend/app/utils/llm_client.py`
- Modify: `members/writer/backend/desktop_server.py`
- Modify: `members/writer/backend/novel_launcher.py`
- Modify: `members/writer/backend/requirements.txt`
- Modify: `members/writer/frontend/electron/main.cjs`
- Modify/Create: `start.bat`
- Modify/Create: `members/writer/start.bat`
- Modify/Create: `members/writer/start.py`
- Modify/Create: `scripts/writer.cmd`
- Modify/Create: `scripts/artist.cmd`
- Modify/Create: `scripts/lamtools.cmd`
- Delete: `members/writer/backend/测试1`

**Interfaces:**
- Consumes: remote diff `57e86b0..origin/main`.
- Produces: local files containing the useful implementation intent, while preserving root `AGENTS.md` and root command entrypoints.

- [ ] **Step 1: Apply only the non-rename, non-gitlink remote patch set with 3-way fallback**

Run:

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
git diff --binary 57e86b0..origin/main -- `
  .github/workflows/ci.yml `
  README.md `
  core/src/lamtools_core/tool/command.py `
  members/writer/.gitignore `
  members/writer/backend/app/core/mcp/client.py `
  members/writer/backend/app/core/writer/git.py `
  members/writer/backend/app/utils/llm_client.py `
  members/writer/backend/desktop_server.py `
  members/writer/backend/novel_launcher.py `
  members/writer/backend/requirements.txt `
  members/writer/frontend/electron/main.cjs `
  members/writer/frontend/src/views/CoreWorkbenchView.vue `
  members/writer/lamwriter-backend.spec `
  members/writer/rebuild.ps1 `
  members/writer/start.bat `
  members/writer/start.py `
  start.bat |
  git apply --3way
```

Expected: patch applies or reports specific conflicts. If conflicts occur, resolve by keeping current local behavior unless the remote change directly implements portable launch, hidden CMD windows, or CI.

- [ ] **Step 2: Restore root agent and command entrypoints**

If the remote patch or later merge removed root files, restore them from local history:

```powershell
git checkout HEAD -- AGENTS.md writer.cmd artist.cmd lamtools.cmd
```

Expected:

```powershell
Test-Path AGENTS.md
Test-Path writer.cmd
Test-Path artist.cmd
Test-Path lamtools.cmd
```

All four commands return `True`.

- [ ] **Step 3: Create or keep script-level command targets**

If `scripts/writer.cmd`, `scripts/artist.cmd`, or `scripts/lamtools.cmd` do not exist, create them by moving the real implementation there and making root files thin wrappers. The root wrapper shape is:

```bat
@echo off
chcp 65001 >nul
cd /d "%~dp0"
call "%~dp0scripts\writer.cmd" %*
```

Use the same pattern for `artist.cmd` and `lamtools.cmd` with the matching script target.

- [ ] **Step 4: Delete the bad gitlink if present**

Run:

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
git rm --ignore-unmatch "members/writer/backend/测试1"
git ls-files -s "members/writer/backend/测试1"
```

Expected: `git ls-files` prints nothing for that path.

- [ ] **Step 5: Format-check before committing**

Run:

```powershell
git diff --check
```

Expected: no output and exit code 0.

- [ ] **Step 6: Commit selective import**

Run:

```powershell
git add .github README.md core members start.bat scripts writer.cmd artist.cmd lamtools.cmd AGENTS.md
git commit -m "chore: integrate collaborator launcher and structure changes"
```

Expected: one commit containing only selected collaborator changes and local compatibility fixes.

---

### Task 3: Make Project-Local Writer Data Safe and Explicit

**Files:**
- Modify: `AGENTS.md`
- Modify: `members/writer/backend/app/config.py`
- Modify: `members/writer/start.py`
- Modify: `members/writer/frontend/electron/main.cjs`
- Modify/Create: `members/writer/docs/portable-data.md`

**Interfaces:**
- Consumes: existing `Settings.data_dir`, `Settings.database_url`, Electron `LAMWRITER_DATA_DIR`, and `members/writer/start.py` environment setup.
- Produces: a single documented Writer data policy:
  - source one-click launcher uses `members/writer/data/`
  - packaged app uses sibling `data/`
  - explicit `LAMWRITER_DATA_DIR` wins
  - old AppData database is treated as a migration source, not the new default

- [ ] **Step 1: Add failing backend tests for data directory precedence and legacy migration**

Create or extend `members/writer/backend/tests/test_config_data_dir.py` with tests equivalent to:

```python
from pathlib import Path

from app.config import _default_project_data_dir, _legacy_appdata_dir, _migrate_legacy_database


def test_default_project_data_dir_points_to_writer_data():
    data_dir = _default_project_data_dir()
    assert data_dir.name == "data"
    assert data_dir.parent.name == "writer"


def test_migrate_legacy_database_copies_only_when_new_db_missing(tmp_path):
    legacy = tmp_path / "legacy" / "LamWriter"
    target = tmp_path / "target"
    legacy.mkdir(parents=True)
    target.mkdir()
    (legacy / "lamwriter.db").write_bytes(b"old-db")

    copied = _migrate_legacy_database(target, legacy)

    assert copied is True
    assert (target / "lamwriter.db").read_bytes() == b"old-db"


def test_migrate_legacy_database_does_not_overwrite_existing_db(tmp_path):
    legacy = tmp_path / "legacy" / "LamWriter"
    target = tmp_path / "target"
    legacy.mkdir(parents=True)
    target.mkdir()
    (legacy / "lamwriter.db").write_bytes(b"old-db")
    (target / "lamwriter.db").write_bytes(b"new-db")

    copied = _migrate_legacy_database(target, legacy)

    assert copied is False
    assert (target / "lamwriter.db").read_bytes() == b"new-db"
```

Run:

```powershell
cd members\writer\backend
py -3.14 -m pytest tests/test_config_data_dir.py -q
```

Expected before implementation: import failure or assertion failure for the new helper functions.

- [ ] **Step 2: Implement explicit data directory helpers**

In `members/writer/backend/app/config.py`, implement helper functions with these names and behavior:

```python
def _default_project_data_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "data"


def _legacy_appdata_dir() -> Path:
    if platform.system() == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home()))
    elif platform.system() == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "LamWriter"


def _migrate_legacy_database(target_dir: Path, legacy_dir: Path | None = None) -> bool:
    legacy_dir = legacy_dir or _legacy_appdata_dir()
    source = legacy_dir / "lamwriter.db"
    target = target_dir / "lamwriter.db"
    if target.exists() or not source.exists():
        return False
    target_dir.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source.read_bytes())
    return True
```

Then update `Settings.model_post_init` so the precedence is:

```text
LAMWRITER_DATA_DIR or explicit settings value -> project data dir -> legacy migration source only
```

- [ ] **Step 3: Document the new policy in repo instructions**

Update `AGENTS.md` Writer database line from the old AppData-only default to:

```markdown
- Writer 默认数据目录为项目内 `members/writer/data/`；旧库 `C:/Users/Administrator/AppData/Roaming/LamWriter/lamwriter.db` 仅作为迁移来源。显式 `LAMWRITER_DATA_DIR` 优先。
```

- [ ] **Step 4: Add portable data doc**

Create `members/writer/docs/portable-data.md`:

```markdown
# Writer Portable Data

Writer 的默认数据目录是 `members/writer/data/`。

启动优先级：

1. 显式 `LAMWRITER_DATA_DIR`
2. 项目内 `members/writer/data/`
3. 旧 AppData 数据库仅在新库不存在时复制一次

Packaged Electron 应用使用程序目录旁的 `data/` 和 `user-data/`。
```

- [ ] **Step 5: Run focused tests and commit**

Run:

```powershell
cd members\writer\backend
py -3.14 -m pytest tests/test_config_data_dir.py tests/test_writer_service.py tests/test_writer_core_kernel_adapter.py -q
```

Expected: all selected tests pass.

Commit:

```powershell
git add AGENTS.md members/writer/backend/app/config.py members/writer/backend/tests/test_config_data_dir.py members/writer/docs/portable-data.md members/writer/start.py members/writer/frontend/electron/main.cjs
git commit -m "feat: make writer data project-local with legacy migration"
```

---

### Task 4: Harden CI So Green Means Useful

**Files:**
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: GitHub Actions workflow added by collaborator.
- Produces: CI where syntax, tests, lint, and build fail the workflow when they fail.

- [ ] **Step 1: Remove allow-failure from critical checks**

Edit `.github/workflows/ci.yml` so these steps do not have `continue-on-error: true`:

```yaml
- name: Run backend tests
  run: |
    cd members/writer/backend
    pytest tests/ -v --tb=short

- name: Lint frontend
  run: |
    cd members/writer/frontend
    npm run lint

- name: Build frontend
  run: |
    cd members/writer/frontend
    npm run build
```

The security report may stay non-blocking during this integration:

```yaml
- name: Run security check
  run: |
    pip install bandit
    bandit -r members/writer/backend/app -f json -o bandit-report.json || true
```

- [ ] **Step 2: Add whitespace check**

Add a job step before backend/frontend tests:

```yaml
- name: Check whitespace
  run: git diff --check
```

- [ ] **Step 3: Validate workflow locally as text**

Run:

```powershell
git diff --check -- .github/workflows/ci.yml
```

Expected: no trailing whitespace errors.

- [ ] **Step 4: Commit CI hardening**

Run:

```powershell
git add .github/workflows/ci.yml
git commit -m "ci: make collaborator checks enforce failures"
```

---

### Task 5: Verify Integrated Runtime Surface

**Files:**
- No planned source edits. Fix only failures found by verification.

**Interfaces:**
- Consumes: Tasks 2-4.
- Produces: evidence that the integrated local branch is ready for user testing.

- [ ] **Step 1: Run whitespace check**

Run:

```powershell
git diff --check
```

Expected: no output and exit code 0.

- [ ] **Step 2: Run backend and core focused tests**

Run:

```powershell
py -3.14 -m pytest core/tests -q
cd members\writer\backend
py -3.14 -m pytest tests/test_config_data_dir.py tests/test_writer_cli.py tests/test_writer_service.py tests/test_writer_core_kernel_adapter.py tests/test_writer_llm_client.py -q
```

Expected: all selected tests pass.

- [ ] **Step 3: Run frontend checks**

Run:

```powershell
cd members\writer\frontend
npm run lint
npm run build
```

Expected: lint and build exit 0.

- [ ] **Step 4: Run launch smoke check without pushing**

Run:

```powershell
.\start.bat
```

Expected: Writer starts from project-local data path and opens the browser. If manual UI observation is required, stop here and ask the user to test.

- [ ] **Step 5: Commit verification fixes if any**

If verification required code fixes:

```powershell
git add <changed-files>
git commit -m "fix: stabilize collaborator integration"
```

If no fixes were required, do not create an empty commit.

---

### Task 6: Converge Local Main Without Uploading GitHub

**Files:**
- No source edits expected.

**Interfaces:**
- Consumes: verified branch `codex/integrate-arccat-main`.
- Produces: local `main` containing the integrated result.

- [ ] **Step 1: Confirm integration branch is clean**

Run:

```powershell
git status --short
git branch --show-current
```

Expected: branch is `codex/integrate-arccat-main`; no tracked changes.

- [ ] **Step 2: Switch to local main**

Run:

```powershell
git switch main
```

Expected: switched to `main`.

- [ ] **Step 3: Merge the integration branch into local main**

Run:

```powershell
git merge --no-ff codex/integrate-arccat-main -m "merge: converge collaborator integration into main"
```

Expected: merge succeeds without conflicts.

- [ ] **Step 4: Verify local main state**

Run:

```powershell
git status -sb
git log --oneline -5
git rev-list --left-right --count main...origin/main
```

Expected: local `main` is ahead of `origin/main`; it is not pushed.

- [ ] **Step 5: Hand off to user testing**

Report:

```text
本地 main 已归一完成，尚未推送 GitHub。
请测试 Writer 启动、项目数据目录、已有数据库迁移、常用 CLI 入口和打包流程。
测试通过后再执行 GitHub 上传。
```

---

### Task 7: Upload GitHub Only After User Confirms

**Files:**
- No source edits expected.

**Interfaces:**
- Consumes: explicit user confirmation that local testing passed.
- Produces: updated GitHub `main`.

- [ ] **Step 1: Require explicit user confirmation**

Proceed only after the user says testing passed and asks to upload.

- [ ] **Step 2: Push local main**

Run:

```powershell
git switch main
git push origin main
```

Expected: GitHub `main` updates to local `main`.

- [ ] **Step 3: Verify remote ref**

Run:

```powershell
git ls-remote --heads origin main
```

Expected: remote `refs/heads/main` matches local `git rev-parse main`.

---

## Self-Review

- Spec coverage: covers selective collaborator import, project-local data policy, root entrypoint preservation, bad gitlink removal, CI hardening, local `main` convergence, and delayed GitHub upload.
- Placeholder scan: no `TBD`, no unspecified "handle edge cases", no upload before user confirmation.
- Type consistency: data helper names are introduced in Task 3 tests and implemented in Task 3 code.
- Residual risk: `start.bat` smoke test is interactive; if automation cannot validate the browser flow, stop and ask the user to test before Task 6 or Task 7.
