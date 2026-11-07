"""用本机 gh 与 git 执行推送和开 PR：先查后建、可重试、可追踪。

user:“将推送分支和创建 PR 变成可控、可追踪、可重试的确定性操作，而不是完全依赖模型
执行 shell 命令”“根据仓库、源分支、目标分支查询已有 PR，避免重复创建”“网络超时后能够
核对实际结果并安全重试”“复用现有 GitHub CLI/API、认证和权限机制”
+(所以这里不建第二套 GitHub 客户端：认证交给本机 gh，写操作只有 git push 与 gh pr
create，重复判断交给 EffectOutbox 的幂等键 + 本模块的 lookup)。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
from pathlib import Path
import shutil
from typing import Any, Awaitable, Callable, Protocol, runtime_checkable

from .models import Effect


class GithubError(RuntimeError):
    """本机没有 gh、没登录、或者远端拒绝了这次操作。"""


@dataclass(frozen=True)
class PublishTarget:
    """一次发布要动的东西：哪个仓库、哪条分支、合到哪条基线。"""

    repo_root: str
    branch: str
    base_branch: str = "main"
    remote: str = "origin"
    title: str = ""
    body: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "PublishTarget":
        return cls(
            repo_root=str(payload.get("repo_root") or ""),
            branch=str(payload.get("branch") or ""),
            base_branch=str(payload.get("base_branch") or "main"),
            remote=str(payload.get("remote") or "origin"),
            title=str(payload.get("title") or ""),
            body=str(payload.get("body") or ""),
        )


CommandRunner = Callable[[list[str], str, float], Awaitable[tuple[int, str, str]]]


async def _default_runner(args: list[str], cwd: str, timeout: float) -> tuple[int, str, str]:
    executable = shutil.which(args[0])
    if executable is None:
        raise GithubError(f"command not found on this machine: {args[0]}")
    process = await asyncio.create_subprocess_exec(
        executable,
        *args[1:],
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        raise GithubError(f"{args[0]} {args[1] if len(args) > 1 else ''} timed out after {timeout}s")
    return (
        int(process.returncode or 0),
        stdout.decode("utf-8", "replace"),
        stderr.decode("utf-8", "replace"),
    )


@runtime_checkable
class PublishAdapter(Protocol):
    async def lookup(self, effect: Effect) -> str | None: ...

    async def perform(self, effect: Effect) -> str: ...


class GithubCliAdapter:
    """EffectAdapter 的 GitHub 实现：lookup 只读，perform 才真的写。"""

    def __init__(
        self,
        *,
        timeout: float = 180.0,
        runner: CommandRunner | None = None,
    ) -> None:
        self.timeout = timeout
        self._runner = runner or _default_runner

    # ---------------------------------------------------------------- 查询
    async def lookup(self, effect: Effect) -> str | None:
        target = PublishTarget.from_payload(effect.payload)
        if effect.kind == "push":
            return await self.lookup_push(target)
        if effect.kind == "create_pr":
            return await self.lookup_pr(target)
        return None

    async def lookup_push(self, target: PublishTarget) -> str | None:
        """远端已经指向同一个提交就算推过了。

        只比分支名不够：分支可能停在旧提交上，那种情况还得推。
        """
        self._require(target)
        code, out, _ = await self._run(
            ["git", "rev-parse", "HEAD"], target.repo_root
        )
        if code != 0:
            return None
        local = out.strip()
        code, out, _ = await self._run(
            ["git", "ls-remote", "--heads", target.remote, target.branch],
            target.repo_root,
        )
        if code != 0 or not out.strip():
            return None
        remote = out.split()[0].strip()
        if remote == local:
            return f"{target.remote}/{target.branch}"
        return None

    async def lookup_pr(self, target: PublishTarget) -> str | None:
        """按 仓库 + 源分支 + 目标分支 查已有 PR，避免重复创建。"""
        self._require(target)
        code, out, err = await self._run(
            [
                "gh",
                "pr",
                "list",
                "--head",
                target.branch,
                "--base",
                target.base_branch,
                "--state",
                "all",
                "--limit",
                "5",
                "--json",
                "url,state,number",
            ],
            target.repo_root,
        )
        if code != 0:
            raise GithubError(f"gh pr list failed: {err.strip() or out.strip()}")
        try:
            rows = json.loads(out or "[]")
        except json.JSONDecodeError:
            return None
        for row in rows if isinstance(rows, list) else []:
            url = str((row or {}).get("url") or "").strip()
            if url:
                return url
        return None

    async def pr_status(self, url: str, *, repo_root: str) -> dict[str, Any]:
        """回读 PR 状态，供工单展示。"""
        code, out, err = await self._run(
            ["gh", "pr", "view", url, "--json", "url,state,number,title,mergeable,mergedAt"],
            repo_root,
        )
        if code != 0:
            raise GithubError(f"gh pr view failed: {err.strip() or out.strip()}")
        try:
            data = json.loads(out or "{}")
        except json.JSONDecodeError as exc:
            raise GithubError(f"gh pr view returned non-json: {out[:200]}") from exc
        return data if isinstance(data, dict) else {}

    # ---------------------------------------------------------------- 写入
    async def perform(self, effect: Effect) -> str:
        target = PublishTarget.from_payload(effect.payload)
        self._require(target)
        if effect.kind == "push":
            return await self.perform_push(target)
        if effect.kind == "create_pr":
            return await self.perform_pr(target)
        raise GithubError(f"unsupported effect kind: {effect.kind}")

    async def perform_push(self, target: PublishTarget) -> str:
        code, out, err = await self._run(
            ["git", "push", "-u", target.remote, target.branch], target.repo_root
        )
        if code != 0:
            raise GithubError(f"git push failed: {err.strip() or out.strip()}")
        return f"{target.remote}/{target.branch}"

    async def perform_pr(self, target: PublishTarget) -> str:
        args = [
            "gh",
            "pr",
            "create",
            "--head",
            target.branch,
            "--base",
            target.base_branch,
            "--title",
            target.title or target.branch,
            "--body",
            target.body or "",
        ]
        code, out, err = await self._run(args, target.repo_root)
        if code != 0:
            message = f"{err.strip() or out.strip()}"
            # 并发或超时之后重试时，远端可能已经有了：再查一次，有就直接用。
            existing = await self.lookup_pr(target)
            if existing:
                return existing
            raise GithubError(f"gh pr create failed: {message}")
        url = ""
        for line in out.splitlines():
            if line.strip().startswith("http"):
                url = line.strip()
        if not url:
            existing = await self.lookup_pr(target)
            if existing:
                return existing
            raise GithubError(f"gh pr create produced no url: {out.strip()[:200]}")
        return url

    # ---------------------------------------------------------------- 内部
    @staticmethod
    def _require(target: PublishTarget) -> None:
        if not target.repo_root or not Path(target.repo_root).is_dir():
            raise GithubError(f"repository is not a directory: {target.repo_root or '(empty)'}")
        if not target.branch:
            raise GithubError("branch is required")

    async def _run(self, args: list[str], cwd: str) -> tuple[int, str, str]:
        return await self._runner(args, cwd, self.timeout)


__all__ = ["GithubCliAdapter", "GithubError", "PublishAdapter", "PublishTarget"]
