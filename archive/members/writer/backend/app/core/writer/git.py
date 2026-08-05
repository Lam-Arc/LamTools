from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


logger = logging.getLogger(__name__)
WRITER_CHECKPOINT_BRANCH_PREFIX = "writer/checkpoint/"


def _git_env(extra_env: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    env.setdefault("GIT_ASKPASS", "")
    env.setdefault("GIT_PAGER", "")
    if extra_env:
        env.update(extra_env)
    return env


def writer_checkpoint_branch(session_id: str) -> str:
    clean = "".join(
        ch if ch.isalnum() or ch in {"-", "_"} else "-"
        for ch in (session_id or "session").strip()
    ).strip("-_")
    return f"{WRITER_CHECKPOINT_BRANCH_PREFIX}{clean[:96] or 'session'}"


class WriterGitSnapshot(BaseModel):
    work_root: str = ""
    is_git_repo: bool = False
    branch: str | None = None
    head: str | None = None
    status_porcelain: str = ""
    dirty_files: list[str] = Field(default_factory=list)
    staged_files: list[str] = Field(default_factory=list)
    untracked_files: list[str] = Field(default_factory=list)
    modified_files: list[str] = Field(default_factory=list)
    deleted_files: list[str] = Field(default_factory=list)
    dirty_hashes: dict[str, str] = Field(default_factory=dict)
    recent_commits: list[str] = Field(default_factory=list)
    captured_at: datetime = Field(default_factory=datetime.now)


class WriterGitCheckpoint(BaseModel):
    label: str
    reason: str = ""
    branch: str | None = None
    head: str | None = None
    commit: str | None = None
    paths: list[str] = Field(default_factory=list)
    allow_empty: bool = False
    base_head: str | None = None
    storage: Literal["current_branch", "checkpoint_branch"] = "current_branch"
    created_at: datetime = Field(default_factory=datetime.now)


class WriterGitMerge(BaseModel):
    target_branch: str
    source_ref: str
    source_head: str | None = None
    target_head_before: str | None = None
    target_head_after: str | None = None
    strategy: Literal["created", "fast_forward", "clean_merge", "cherry_pick", "noop"] = "noop"
    note: str = ""
    success: bool = False
    created_at: datetime = Field(default_factory=datetime.now)


class WriterAgentBranch(BaseModel):
    branch: str
    head: str | None = None
    worktree: str = ""
    dirty: bool = False
    files: list[str] = Field(default_factory=list)


class GitVersionCommit(BaseModel):
    """A single commit in the version graph."""
    sha: str
    message: str
    timestamp: str
    author: str


class GitVersionLane(BaseModel):
    """A horizontal lane representing a branch's commit history."""
    branch: str
    is_current: bool = False
    commits: list[GitVersionCommit] = Field(default_factory=list)


class GitVersionGraph(BaseModel):
    """Branch-linear version graph for frontend rendering.

    Normal users understand horizontal lanes per branch —
    not a full DAG. Current branch is always the first lane.
    """
    current_branch: str = ""
    head: str = ""
    lanes: list[GitVersionLane] = Field(default_factory=list)


@dataclass
class GitCommandResult:
    code: int
    stdout: str
    stderr: str


def _exception_summary(exc: BaseException) -> str:
    message = str(exc).strip()
    if message:
        return f"{type(exc).__name__}: {message}"
    return type(exc).__name__


def _windows_git_creationflags() -> int:
    if sys.platform != "win32":
        return 0
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _run_git_blocking(
    cwd: str | None,
    args: list[str],
    *,
    stdin: str | None = None,
    max_output_chars: int = 30000,
    extra_env: dict[str, str] | None = None,
) -> GitCommandResult:
    try:
        kwargs: dict[str, Any] = {
            "args": args,
            "cwd": cwd,
            "env": _git_env(extra_env),
            "input": stdin,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "stdin": None if stdin is not None else subprocess.DEVNULL,
            "encoding": "utf-8",
            "errors": "replace",
            "check": False,
        }
        if sys.platform == "win32":
            kwargs["creationflags"] = _windows_git_creationflags()
        completed = subprocess.run(**kwargs)
        out = completed.stdout or ""
        err = completed.stderr or ""
        if len(out) > max_output_chars:
            out = out[:max_output_chars] + "\n... [truncated]"
        if len(err) > max_output_chars:
            err = err[:max_output_chars] + "\n... [truncated]"
        return GitCommandResult(code=completed.returncode or 0, stdout=out, stderr=err)
    except Exception as exc:
        return GitCommandResult(code=1, stdout="", stderr=_exception_summary(exc))


async def _run_git(
    cwd: str | None,
    args: list[str],
    *,
    stdin: str | None = None,
    max_output_chars: int = 30000,
    extra_env: dict[str, str] | None = None,
) -> GitCommandResult:
    return await asyncio.to_thread(
        _run_git_blocking,
        cwd,
        args,
        stdin=stdin,
        max_output_chars=max_output_chars,
        extra_env=extra_env,
    )


@dataclass
class GitStatusEntry:
    code: str
    path: str


class WriterGitManager:
    """Small async git wrapper for Writer runtime state management."""

    def __init__(self, *, max_output_chars: int = 30000) -> None:
        self.max_output_chars = max_output_chars

    async def run(
        self,
        cwd: str,
        args: list[str],
        *,
        stdin: str | None = None,
        max_output_chars: int | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> GitCommandResult:
        return await _run_git(
            cwd,
            ["git", *args],
            stdin=stdin,
            max_output_chars=max_output_chars if max_output_chars is not None else self.max_output_chars,
            extra_env=extra_env,
        )

    async def repo_root(self, cwd: str) -> str | None:
        result = await self.run(cwd, ["rev-parse", "--show-toplevel"], max_output_chars=4096)
        text = result.stdout.strip()
        if result.code != 0 or not text:
            return None
        try:
            return str(Path(text).resolve())
        except OSError:
            return None

    async def is_repo(self, cwd: str) -> bool:
        repo_root = await self.repo_root(cwd)
        if repo_root is None:
            return False
        try:
            return Path(repo_root).resolve() == Path(cwd).resolve()
        except OSError:
            return False

    @staticmethod
    async def check_git_available() -> tuple[bool, str]:
        """Check whether ``git`` is installed and runnable.

        Returns ``(True, "version info")`` or ``(False, "failure reason")``.
        """
        result = await _run_git(None, ["git", "--version"], max_output_chars=4096)
        if result.code == 0:
            return True, result.stdout.strip()
        return False, result.stderr.strip() or "git returned non-zero"

    @staticmethod
    async def ensure_git_installed() -> tuple[bool, str]:
        """Report whether git is available without changing the machine."""
        ok, msg = await WriterGitManager.check_git_available()
        if ok:
            return True, msg
        return False, f"Git is required for project versioning. {msg}. See https://git-scm.com/downloads"

    async def init_repo(self, cwd: str, *, default_user: str = "Writer", default_email: str = "writer@lam.local") -> bool:
        """Ensure *cwd* is a git repository — init if missing.

        Creates the directory if it doesn't exist, runs ``git init``,
        and sets safe local defaults for ``user.name`` / ``user.email``
        so subsequent git operations never block on missing identity.

        Returns True if the directory is (or became) a git repo,
        False on failure.
        """
        if await self.is_repo(cwd):
            return True
        ok, msg = await self.check_git_available()
        if not ok:
            logger.warning("Git is required for project versioning — %s", msg)
            return False
        try:
            Path(cwd).mkdir(parents=True, exist_ok=True)
        except OSError:
            return False
        result = await self.run(cwd, ["init"], max_output_chars=4096)
        if result.code != 0:
            return False
        # Set safe local defaults so commits don't fail on missing identity
        await self.run(cwd, ["config", "user.name", default_user], max_output_chars=4096)
        await self.run(cwd, ["config", "user.email", default_email], max_output_chars=4096)
        if await self.head(cwd) is None:
            await self.checkpoint_all(
                cwd,
                reason="初始化当前工作区",
                label="checkpoint",
                allow_empty=True,
            )
        return await self.is_repo(cwd)

    async def current_branch(self, cwd: str) -> str | None:
        result = await self.run(cwd, ["branch", "--show-current"], max_output_chars=4096)
        text = result.stdout.strip()
        if result.code == 0 and text:
            return text
        fallback = await self.run(cwd, ["symbolic-ref", "--quiet", "--short", "HEAD"], max_output_chars=4096)
        text = fallback.stdout.strip()
        return text or None

    async def head(self, cwd: str) -> str | None:
        result = await self.run(cwd, ["rev-parse", "HEAD"], max_output_chars=4096)
        text = result.stdout.strip()
        if result.code != 0:
            return None
        return text or None

    async def ref_head(self, cwd: str, ref: str) -> str | None:
        result = await self.run(cwd, ["rev-parse", "--verify", ref], max_output_chars=4096)
        text = result.stdout.strip()
        if result.code != 0:
            return None
        return text or None

    async def branch_exists(self, cwd: str, branch: str) -> bool:
        result = await self.run(cwd, ["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], max_output_chars=4096)
        return result.code == 0

    async def is_ancestor(self, cwd: str, ancestor_ref: str, descendant_ref: str) -> bool:
        result = await self.run(
            cwd,
            ["merge-base", "--is-ancestor", ancestor_ref, descendant_ref],
            max_output_chars=4096,
        )
        return result.code == 0

    async def ensure_branch_ref(
        self,
        cwd: str,
        branch: str,
        start_point: str = "HEAD",
        *,
        force: bool = True,
    ) -> str | None:
        if not await self.is_repo(cwd):
            return None
        exists = await self.branch_exists(cwd, branch)
        if exists and force:
            result = await self.run(cwd, ["branch", "-f", branch, start_point], max_output_chars=4096)
        elif exists:
            result = GitCommandResult(code=0, stdout="", stderr="")
        else:
            result = await self.run(cwd, ["branch", branch, start_point], max_output_chars=4096)
        if result.code != 0:
            return None
        return branch

    async def checkout_branch(
        self,
        cwd: str,
        branch: str,
        start_point: str = "HEAD",
    ) -> bool:
        if not await self.is_repo(cwd):
            return False
        exists = await self.branch_exists(cwd, branch)
        if exists:
            result = await self.run(cwd, ["checkout", branch], max_output_chars=4096)
            return result.code == 0
        result = await self.run(cwd, ["checkout", "-B", branch, start_point], max_output_chars=4096)
        return result.code == 0

    async def create_worktree(
        self,
        cwd: str,
        *,
        branch: str,
        path: str,
        start_point: str = "HEAD",
    ) -> bool:
        if not await self.is_repo(cwd):
            return False
        target = Path(path)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            return False
        result = await self.run(
            cwd,
            ["worktree", "add", "-B", branch, str(target), start_point],
            max_output_chars=12000,
        )
        if result.code != 0:
            return False
        try:
            root = Path(cwd).resolve()
            exclude = root / ".git" / "info" / "exclude"
            exclude.parent.mkdir(parents=True, exist_ok=True)
            marker = ".writer/worktrees/"
            existing = exclude.read_text(encoding="utf-8", errors="replace") if exclude.exists() else ""
            if marker not in existing:
                with exclude.open("a", encoding="utf-8") as handle:
                    if existing and not existing.endswith("\n"):
                        handle.write("\n")
                    handle.write(f"{marker}\n")
        except OSError:
            pass
        await self.run(path, ["config", "user.name", "Writer"], max_output_chars=4096)
        await self.run(path, ["config", "user.email", "writer@lam.local"], max_output_chars=4096)
        return await self.is_repo(path)

    async def list_agent_branches(self, cwd: str) -> list[WriterAgentBranch]:
        if not await self.is_repo(cwd):
            return []
        branches_result = await self.run(
            cwd,
            ["for-each-ref", "--format=%(refname:short)|%(objectname)", "refs/heads/writer/agent/"],
            max_output_chars=12000,
        )
        if branches_result.code != 0:
            return []
        worktree_by_branch = await self._worktrees_by_branch(cwd)
        items: list[WriterAgentBranch] = []
        for line in branches_result.stdout.splitlines():
            if "|" not in line:
                continue
            branch, head = line.split("|", 1)
            branch = branch.strip()
            if not branch.startswith("writer/agent/"):
                continue
            worktree = worktree_by_branch.get(branch, "")
            files: list[str] = []
            dirty = False
            if worktree:
                snapshot = await self.status_snapshot(worktree)
                if snapshot is not None:
                    files = snapshot.dirty_files
                    dirty = bool(snapshot.dirty_files)
            diff_files = await self.changed_files_between(cwd, "HEAD", branch)
            items.append(WriterAgentBranch(
                branch=branch,
                head=head.strip() or None,
                worktree=worktree,
                dirty=dirty,
                files=sorted(dict.fromkeys([*diff_files, *files])),
            ))
        return sorted(items, key=lambda item: item.branch)

    async def branch_diff(self, cwd: str, source_ref: str, *, target_ref: str = "HEAD", max_chars: int = 30000) -> str | None:
        if not await self.is_repo(cwd):
            return None
        if not self._is_agent_branch(source_ref):
            return None
        result = await self.run(
            cwd,
            ["diff", "--stat", "--patch", f"{target_ref}...{source_ref}"],
            max_output_chars=max_chars,
        )
        if result.code != 0:
            return None
        return result.stdout

    async def changed_files_between(self, cwd: str, target_ref: str, source_ref: str) -> list[str]:
        result = await self.run(
            cwd,
            ["diff", "--name-only", f"{target_ref}...{source_ref}"],
            max_output_chars=12000,
        )
        if result.code != 0:
            return []
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    async def abandon_agent_branch(self, cwd: str, branch: str, *, delete_branch: bool = True) -> bool:
        if not await self.is_repo(cwd) or not self._is_agent_branch(branch):
            return False
        worktrees = await self._worktrees_by_branch(cwd)
        worktree = worktrees.get(branch, "")
        if worktree:
            remove = await self.run(cwd, ["worktree", "remove", "--force", worktree], max_output_chars=12000)
            if remove.code != 0:
                return False
        if delete_branch:
            delete = await self.run(cwd, ["branch", "-D", branch], max_output_chars=12000)
            return delete.code == 0
        return True

    async def _worktrees_by_branch(self, cwd: str) -> dict[str, str]:
        result = await self.run(cwd, ["worktree", "list", "--porcelain"], max_output_chars=30000)
        if result.code != 0:
            return {}
        mapping: dict[str, str] = {}
        current_path = ""
        current_branch = ""
        for line in [*result.stdout.splitlines(), ""]:
            if not line.strip():
                if current_path and current_branch:
                    mapping[current_branch] = current_path
                current_path = ""
                current_branch = ""
                continue
            if line.startswith("worktree "):
                current_path = line.removeprefix("worktree ").strip()
            elif line.startswith("branch refs/heads/"):
                current_branch = line.removeprefix("branch refs/heads/").strip()
        return mapping

    @staticmethod
    def _is_agent_branch(branch: str) -> bool:
        return branch.startswith("writer/agent/") and ".." not in branch and not branch.startswith("/")

    async def status_snapshot(self, cwd: str) -> WriterGitSnapshot | None:
        if not await self.is_repo(cwd):
            return None

        branch, head = await asyncio.gather(self.current_branch(cwd), self.head(cwd))
        status_result = await self.run(
            cwd,
            ["status", "--porcelain=v1", "--untracked-files=all", "--no-renames", "-z"],
            max_output_chars=12000,
        )
        if status_result.code != 0:
            return None

        entries = self._parse_status_entries(status_result.stdout)
        dirty_files: list[str] = []
        staged_files: list[str] = []
        untracked_files: list[str] = []
        modified_files: list[str] = []
        deleted_files: list[str] = []
        dirty_hashes: dict[str, str] = {}

        for entry in entries:
            dirty_files.append(entry.path)
            if entry.code == "??":
                untracked_files.append(entry.path)
            if entry.code and entry.code[0] != " ":
                staged_files.append(entry.path)
            if entry.code and entry.code[1] != " ":
                modified_files.append(entry.path)
            if "D" in entry.code:
                deleted_files.append(entry.path)
            dirty_hashes[entry.path] = await self._path_hash(cwd, entry.path)

        recent_result = await self.run(cwd, ["log", "--oneline", "-n", "5"], max_output_chars=4096)
        recent_commits = [line.strip() for line in recent_result.stdout.splitlines() if line.strip()]

        return WriterGitSnapshot(
            work_root=cwd,
            is_git_repo=True,
            branch=branch,
            head=head,
            status_porcelain=status_result.stdout,
            dirty_files=dirty_files,
            staged_files=staged_files,
            untracked_files=untracked_files,
            modified_files=modified_files,
            deleted_files=deleted_files,
            dirty_hashes=dirty_hashes,
            recent_commits=recent_commits,
        )

    @staticmethod
    def _is_transient_path(path: str) -> bool:
        normalized = path.replace("\\", "/").strip("/")
        parts = set(normalized.split("/"))
        if parts & {"__pycache__", ".pytest_cache", "node_modules", ".venv", "venv", "dist", "build"}:
            return True
        return normalized.endswith((".pyc", ".pyo", ".log", ".tmp"))

    @staticmethod
    def _transient_clean_target(path: str) -> str:
        normalized = path.replace("\\", "/").strip("/")
        parts = normalized.split("/")
        transient_dirs = {"__pycache__", ".pytest_cache", "node_modules", ".venv", "venv", "dist", "build"}
        for index, part in enumerate(parts):
            if part in transient_dirs:
                return "/".join(parts[: index + 1])
        return normalized

    async def clean_transient_paths(self, cwd: str) -> list[str]:
        """Remove untracked cache/test artifacts left by verification commands."""
        current = await self.status_snapshot(cwd)
        if current is None:
            return []
        transient = sorted(dict.fromkeys(
            self._transient_clean_target(path)
            for path in current.untracked_files
            if self._is_transient_path(path)
        ))
        if not transient:
            return []
        result = await self.run(cwd, ["clean", "-fd", "--", *transient], max_output_chars=4096)
        if result.code != 0:
            return []
        return transient

    async def checkpoint_all(
        self,
        cwd: str,
        *,
        reason: str,
        label: str = "checkpoint",
        allow_empty: bool = False,
    ) -> WriterGitCheckpoint | None:
        if not await self.is_repo(cwd):
            return None

        current = await self.status_snapshot(cwd)
        if current is None:
            return None

        paths = [
            path
            for path in current.dirty_files
            if not self._is_transient_path(path)
        ]
        if paths:
            add_result = await self.run(cwd, ["add", "-A", "--", *paths], max_output_chars=4096)
            if add_result.code != 0:
                return None

        if not paths and not allow_empty:
            return None

        commit_args = ["commit", "-m", self._normalize_commit_message(label, reason)]
        if allow_empty:
            commit_args.append("--allow-empty")
        commit_result = await self.run(cwd, commit_args, max_output_chars=4096)
        if commit_result.code != 0:
            return None

        await self.clean_transient_paths(cwd)
        new_snapshot = await self.status_snapshot(cwd)
        head = new_snapshot.head if new_snapshot else await self.head(cwd)
        branch = new_snapshot.branch if new_snapshot else await self.current_branch(cwd)
        return WriterGitCheckpoint(
            label=label,
            reason=reason,
            branch=branch,
            head=head,
            commit=head,
            paths=paths,
            allow_empty=allow_empty,
        )

    async def checkpoint_all_to_branch(
        self,
        cwd: str,
        branch: str,
        *,
        reason: str,
        label: str = "checkpoint",
        allow_empty: bool = False,
    ) -> WriterGitCheckpoint | None:
        if not await self.is_repo(cwd):
            return None

        current = await self.status_snapshot(cwd)
        if current is None:
            return None

        paths = [
            path
            for path in current.dirty_files
            if not self._is_transient_path(path)
        ]
        if not paths and not allow_empty:
            return None

        base_head = current.head or await self.head(cwd)
        fd, index_path = tempfile.mkstemp(prefix="writer-checkpoint-", suffix=".idx")
        os.close(fd)
        try:
            os.unlink(index_path)
        except OSError:
            pass
        extra_env = {"GIT_INDEX_FILE": index_path}

        try:
            if base_head:
                read_tree = await self.run(cwd, ["read-tree", base_head], extra_env=extra_env, max_output_chars=4096)
            else:
                read_tree = await self.run(cwd, ["read-tree", "--empty"], extra_env=extra_env, max_output_chars=4096)
            if read_tree.code != 0:
                return None

            if paths:
                add_result = await self.run(cwd, ["add", "-A", "--", *paths], extra_env=extra_env, max_output_chars=12000)
                if add_result.code != 0:
                    return None

            tree = await self.run(cwd, ["write-tree"], extra_env=extra_env, max_output_chars=4096)
            tree_id = tree.stdout.strip()
            if tree.code != 0 or not tree_id:
                return None

            parent = await self.ref_head(cwd, branch)
            if not parent:
                parent = base_head
            commit_args = ["commit-tree", tree_id]
            if parent:
                commit_args.extend(["-p", parent])
            commit_args.extend(["-m", self._normalize_commit_message(label, reason)])
            commit_result = await self.run(cwd, commit_args, extra_env=extra_env, max_output_chars=4096)
            commit = commit_result.stdout.strip()
            if commit_result.code != 0 or not commit:
                return None

            updated = await self.ensure_branch_ref(cwd, branch, commit, force=True)
            if updated is None:
                return None

            return WriterGitCheckpoint(
                label=label,
                reason=reason,
                branch=branch,
                head=commit,
                commit=commit,
                paths=paths,
                allow_empty=allow_empty,
                base_head=base_head,
                storage="checkpoint_branch",
            )
        finally:
            try:
                os.unlink(index_path)
            except OSError:
                pass

    async def commit_paths(
        self,
        cwd: str,
        paths: list[str],
        *,
        message: str,
        allow_empty: bool = False,
    ) -> WriterGitCheckpoint | None:
        if not await self.is_repo(cwd):
            return None

        normalized_paths = sorted(dict.fromkeys(
            path.replace("\\", "/").strip("/")
            for path in paths
            if path and not self._is_transient_path(path)
        ))
        if normalized_paths:
            add_result = await self.run(cwd, ["add", "-A", "--", *normalized_paths], max_output_chars=4096)
            if add_result.code != 0:
                return None
        if not normalized_paths and not allow_empty:
            return None

        commit_message = re.sub(r"\s+", " ", message.strip())[:72] or "chore: save writer changes"
        commit_args = ["commit", "-m", commit_message]
        if allow_empty:
            commit_args.append("--allow-empty")
        commit_result = await self.run(cwd, commit_args, max_output_chars=4096)
        if commit_result.code != 0:
            return None

        snapshot = await self.status_snapshot(cwd)
        head = snapshot.head if snapshot else await self.head(cwd)
        branch = snapshot.branch if snapshot else await self.current_branch(cwd)
        return WriterGitCheckpoint(
            label="commit",
            reason=commit_message,
            branch=branch,
            head=head,
            commit=head,
            paths=normalized_paths,
            allow_empty=allow_empty,
        )

    async def restore_checkpoint(self, cwd: str, commit: str) -> bool:
        if not await self.is_repo(cwd):
            return False
        if await self.ref_head(cwd, commit) is None:
            return False
        clean_before = await self.run(cwd, ["clean", "-fd"], max_output_chars=12000)
        if clean_before.code != 0:
            return False
        read_tree = await self.run(cwd, ["read-tree", "--reset", "-u", commit], max_output_chars=12000)
        if read_tree.code != 0:
            return False
        mixed = await self.run(cwd, ["reset", "--mixed", "HEAD"], max_output_chars=12000)
        return mixed.code == 0

    async def merge_branch(
        self,
        cwd: str,
        target_branch: str,
        source_ref: str,
    ) -> WriterGitMerge | None:
        if not await self.is_repo(cwd):
            return None

        target_head_before = await self.ref_head(cwd, target_branch)
        source_head = await self.ref_head(cwd, source_ref)
        if source_head is None:
            return None

        if target_head_before == source_head:
            return WriterGitMerge(
                target_branch=target_branch,
                source_ref=source_ref,
                source_head=source_head,
                target_head_before=target_head_before,
                target_head_after=source_head,
                strategy="noop",
                success=True,
                note="target already at source head",
            )

        if target_head_before is None:
            updated = await self.ensure_branch_ref(cwd, target_branch, source_head, force=True)
            if updated is None:
                return None
            return WriterGitMerge(
                target_branch=target_branch,
                source_ref=source_ref,
                source_head=source_head,
                target_head_before=None,
                target_head_after=source_head,
                strategy="created",
                success=True,
                note="target branch created at source head",
            )

        if await self.is_ancestor(cwd, target_branch, source_ref):
            current_branch = await self.current_branch(cwd)
            if current_branch == target_branch:
                ff_result = await self.run(cwd, ["merge", "--ff-only", source_ref], max_output_chars=12000)
                if ff_result.code != 0:
                    return None
                target_head_after = await self.ref_head(cwd, target_branch) or source_head
            else:
                updated = await self.ensure_branch_ref(cwd, target_branch, source_head, force=True)
                if updated is None:
                    return None
                target_head_after = source_head
            return WriterGitMerge(
                target_branch=target_branch,
                source_ref=source_ref,
                source_head=source_head,
                target_head_before=target_head_before,
                target_head_after=target_head_after,
                strategy="fast_forward",
                success=True,
                note="fast-forwarded target ref",
            )

        snapshot = await self.status_snapshot(cwd)
        if snapshot is None or snapshot.dirty_files:
            return None

        original_branch = snapshot.branch
        switched_to_target = False
        if original_branch != target_branch:
            switched_to_target = await self.checkout_branch(cwd, target_branch, target_head_before)
            if not switched_to_target:
                return None

        merge_result = await self.run(cwd, ["merge", "--no-edit", source_ref], max_output_chars=4096)
        if merge_result.code == 0:
            target_head_after = await self.ref_head(cwd, target_branch)
            if original_branch and original_branch != target_branch:
                await self.checkout_branch(cwd, original_branch, target_head_after or source_head)
            return WriterGitMerge(
                target_branch=target_branch,
                source_ref=source_ref,
                source_head=source_head,
                target_head_before=target_head_before,
                target_head_after=target_head_after or source_head,
                strategy="clean_merge",
                success=True,
                note=(merge_result.stdout or merge_result.stderr).strip(),
            )

        await self.run(cwd, ["merge", "--abort"], max_output_chars=4096)

        rev_list_result = await self.run(
            cwd,
            ["rev-list", "--reverse", f"{target_branch}..{source_ref}"],
            max_output_chars=4096,
        )
        commits = [line.strip() for line in rev_list_result.stdout.splitlines() if line.strip()]
        if not commits:
            if original_branch and original_branch != target_branch and switched_to_target:
                await self.checkout_branch(cwd, original_branch, target_head_before)
            return None

        applied: list[str] = []
        for commit in commits:
            cherry_result = await self.run(cwd, ["cherry-pick", "--no-edit", commit], max_output_chars=4096)
            if cherry_result.code != 0:
                await self.run(cwd, ["cherry-pick", "--abort"], max_output_chars=4096)
                if original_branch and original_branch != target_branch and switched_to_target:
                    await self.checkout_branch(cwd, original_branch, target_head_before)
                return None
            applied.append(commit)

        target_head_after = await self.ref_head(cwd, target_branch)
        if original_branch and original_branch != target_branch:
            await self.checkout_branch(cwd, original_branch, target_head_after or source_head)
        return WriterGitMerge(
            target_branch=target_branch,
            source_ref=source_ref,
            source_head=source_head,
            target_head_before=target_head_before,
            target_head_after=target_head_after or source_head,
            strategy="cherry_pick",
            success=True,
            note=f"applied {len(applied)} commit(s)",
        )

    # --- GitVersionGraph ---

    async def version_graph(self, cwd: str, max_commits: int = 50) -> GitVersionGraph | None:
        """Build a branch-linear version graph for the frontend.

        Returns horizontal lanes per branch with commits in chronological
        order — the format normal users understand (not a full DAG).
        """
        if not await self.is_repo(cwd):
            return None

        # 1. Get all branches
        branch_result = await self.run(
            cwd,
            ["for-each-ref", "--format=%(refname:short)", "refs/heads/"],
            max_output_chars=8192,
        )
        if branch_result.code != 0:
            return None
        branch_names = [
            b.strip()
            for b in branch_result.stdout.splitlines()
            if b.strip() and not b.strip().startswith(WRITER_CHECKPOINT_BRANCH_PREFIX)
        ]

        # 2. Get current branch + HEAD
        current_branch = await self.current_branch(cwd)
        head = await self.head(cwd)

        # 3. Collect commits per branch (lane)
        lanes: list[GitVersionLane] = []
        for branch in branch_names:
            log_result = await self.run(
                cwd,
                [
                    "log",
                    f"--max-count={max_commits}",
                    "--format=%H|%s|%ai|%an",
                    branch,
                ],
                max_output_chars=16384,
            )
            if log_result.code != 0:
                continue
            commits: list[GitVersionCommit] = []
            for line in log_result.stdout.splitlines():
                parts = line.split("|", 3)
                if len(parts) < 4:
                    continue
                commits.append(GitVersionCommit(
                    sha=parts[0],
                    message=parts[1],
                    timestamp=parts[2],
                    author=parts[3],
                ))
            lanes.append(GitVersionLane(
                branch=branch,
                is_current=branch == current_branch,
                commits=commits,
            ))

        # 4. Sort: current branch first, then alphabetically
        lanes.sort(key=lambda l: (not l.is_current, l.branch))

        return GitVersionGraph(
            current_branch=current_branch or "",
            head=head or "",
            lanes=lanes,
        )

    @staticmethod
    def _parse_status_entries(stdout: str) -> list[GitStatusEntry]:
        entries: list[GitStatusEntry] = []
        for raw in stdout.split("\0"):
            if not raw:
                continue
            code = raw[:2]
            path = raw[3:] if len(raw) > 3 else ""
            if not path:
                continue
            entries.append(GitStatusEntry(code=code, path=path))
        return entries

    @staticmethod
    def _normalize_commit_message(label: str, reason: str) -> str:
        text = f"{label}: {reason}".strip()
        text = re.sub(r"\s+", " ", text)
        return text[:72] if len(text) > 72 else text

    @staticmethod
    async def _path_hash(cwd: str, relative_path: str) -> str:
        path = Path(cwd) / relative_path
        try:
            if not path.exists():
                return "<deleted>"
            if path.is_dir():
                return "<directory>"
            digest = hashlib.sha256()
            digest.update(path.read_bytes())
            return digest.hexdigest()
        except Exception as exc:
            return f"<error:{exc}>"
