"""独立工作树：每个 Ticket 一个 worktree + 一条分支，互不覆盖。

user:“独立 Worktree”“两张 Ticket 同时修改同一代码仓库不同分支时，worktree 不交叉”
+(所以这里不允许复用同一个目录：ticket 号进分支名和目录名，创建失败要能回滚)。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import re
import subprocess
from typing import Any

_ALLOWED_BRANCH = re.compile(r"^[A-Za-z0-9._\-/]+$")


class WorktreeError(RuntimeError):
    pass


def _run_git(args: list[str], *, cwd: Path, timeout: float = 60.0) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:  # git 没装
        raise WorktreeError("git is not available on this machine") from exc
    except subprocess.TimeoutExpired as exc:
        raise WorktreeError(f"git {args[0]} timed out") from exc


class WorktreeManager:
    """管理 ok-or-raise 的 worktree 生命周期。"""

    def __init__(self, base_dir: str | Path, *, allowed_repo_roots: tuple[str, ...] = ()) -> None:
        self.base_dir = Path(base_dir).resolve()
        self.allowed_repo_roots = tuple(str(Path(item).resolve()) for item in allowed_repo_roots if item)

    def _check_repo(self, repo: str | Path) -> Path:
        path = Path(repo).resolve()
        if self.allowed_repo_roots and not any(
            str(path).lower().startswith(root.lower()) for root in self.allowed_repo_roots
        ):
            raise WorktreeError(f"repo is outside the authorized roots: {path}")
        if not (path / ".git").exists():
            raise WorktreeError(f"not a git repository: {path}")
        return path

    def _branch_name(self, ticket_id: str) -> str:
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", str(ticket_id or "")).strip("-")
        if not slug:
            raise WorktreeError("ticket_id is required")
        branch = f"ticket/{slug}"
        if not _ALLOWED_BRANCH.match(branch):
            raise WorktreeError(f"unsafe branch name: {branch}")
        return branch

    async def ensure(
        self, ticket_id: str, repo: str | Path, base_branch: str = "main"
    ) -> dict[str, Any]:
        return await asyncio.to_thread(self._ensure_sync, ticket_id, repo, base_branch)

    async def remove(self, ticket_id: str, repo: str | Path) -> bool:
        return await asyncio.to_thread(self._remove_sync, ticket_id, repo)

    # ------------------------------------------------------------------ 同步实现
    def _ensure_sync(self, ticket_id: str, repo: str | Path, base_branch: str) -> dict[str, Any]:
        repo_path = self._check_repo(repo)
        branch = self._branch_name(ticket_id)
        target = self.base_dir / "worktrees" / branch.replace("/", "-")
        if (target / ".git").exists():
            return {"path": str(target), "branch": branch, "created": False, "repo": str(repo_path)}
        target.parent.mkdir(parents=True, exist_ok=True)

        # 基分支可能不叫 main（很多仓库默认 master，或只有远端分支），
        # 找不到就退回当前 HEAD，避免因为分支名假设直接失败。
        base = base_branch or "HEAD"
        if _run_git(["rev-parse", "--verify", base], cwd=repo_path).returncode != 0:
            base = "HEAD"
        if _run_git(["rev-parse", "--verify", base], cwd=repo_path).returncode != 0:
            raise WorktreeError(f"base branch is not resolvable: {base_branch}")

        exists = _run_git(["rev-parse", "--verify", branch], cwd=repo_path)
        if exists.returncode == 0:
            result = _run_git(["worktree", "add", str(target), branch], cwd=repo_path)
        else:
            result = _run_git(
                ["worktree", "add", "-b", branch, str(target), base], cwd=repo_path
            )
        if result.returncode != 0:
            # 失败要把半成品清掉，否则下次 ensure 会看到目录存在而误判成功。
            _run_git(["worktree", "remove", "--force", str(target)], cwd=repo_path)
            raise WorktreeError(
                f"git worktree add failed: {result.stderr.strip() or result.stdout.strip()}"
            )
        return {"path": str(target), "branch": branch, "created": True, "repo": str(repo_path)}

    def _remove_sync(self, ticket_id: str, repo: str | Path) -> bool:
        repo_path = self._check_repo(repo)
        branch = self._branch_name(ticket_id)
        target = self.base_dir / "worktrees" / branch.replace("/", "-")
        if not (target / ".git").exists():
            return False
        result = _run_git(["worktree", "remove", "--force", str(target)], cwd=repo_path)
        return result.returncode == 0

    def list_worktrees(self, repo: str | Path) -> list[dict[str, str]]:
        repo_path = self._check_repo(repo)
        result = _run_git(["worktree", "list", "--porcelain"], cwd=repo_path)
        if result.returncode != 0:
            raise WorktreeError(result.stderr.strip() or "git worktree list failed")
        items: list[dict[str, str]] = []
        current: dict[str, str] = {}
        for line in result.stdout.splitlines():
            if not line.strip():
                if current:
                    items.append(current)
                    current = {}
                continue
            key, _, value = line.partition(" ")
            current[key] = value
        if current:
            items.append(current)
        return items


__all__ = ["WorktreeError", "WorktreeManager"]
