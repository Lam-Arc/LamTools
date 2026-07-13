from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.writer.git import GitCommandResult, WriterGitManager
from app.models.session import WriterSession
from lamtools_core.attachment import open_with_default_app

_git_manager = WriterGitManager()


async def get_git_graph_response(db: AsyncSession, session_id: str) -> dict[str, Any]:
    session = await _get_session(db, session_id)
    work_root = session.work_root
    if not work_root:
        raise ValueError("Session has no work_root set")

    graph = await _git_manager.version_graph(work_root)
    if graph is None:
        return {
            "current_branch": "",
            "head": "",
            "lanes": [],
        }
    return graph.model_dump()


async def get_session_changes_response(db: AsyncSession, session_id: str) -> dict[str, Any]:
    session = await _get_session(db, session_id)
    work_root = session.work_root
    if not work_root:
        return _changes_response(source="none")
    if not await _git_manager.is_repo(work_root):
        return _changes_response(source="not_git")

    source = "working_tree"
    ref: str | None = None
    numstat = await _git_manager.run(
        work_root,
        ["diff", "--numstat", "--"],
        max_output_chars=30000,
    )
    if numstat.code != 0:
        raise ValueError(numstat.stderr or "Git diff failed")

    if not numstat.stdout.strip():
        git_state = (session.runtime_state or {}).get("git_state", {})
        checkpoint = git_state.get("last_checkpoint") or {}
        commit = checkpoint.get("commit")
        if commit and checkpoint.get("storage") != "checkpoint_branch":
            source = "checkpoint"
            ref = str(commit)
            base_ref = str(checkpoint.get("base_head") or "")
            if base_ref:
                numstat = await _git_manager.run(
                    work_root,
                    ["diff", "--numstat", base_ref, str(commit), "--"],
                    max_output_chars=30000,
                )
            else:
                numstat = await _git_manager.run(
                    work_root,
                    ["show", "--numstat", "--format=", str(commit)],
                    max_output_chars=30000,
                )
            if numstat.code != 0:
                numstat = GitCommandResult(code=0, stdout="", stderr="")

    files: list[dict[str, Any]] = []
    total_additions = 0
    total_deletions = 0
    for line in numstat.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        add_raw, del_raw, path = parts[0], parts[1], parts[2]
        binary = add_raw == "-" or del_raw == "-"
        additions = None if binary else int(add_raw or 0)
        deletions = None if binary else int(del_raw or 0)
        if additions is not None:
            total_additions += additions
        if deletions is not None:
            total_deletions += deletions
        files.append(
            {
                "path": path,
                "additions": additions,
                "deletions": deletions,
                "binary": binary,
            }
        )

    untracked = await _git_manager.run(
        work_root,
        ["ls-files", "--others", "--exclude-standard"],
        max_output_chars=30000,
    )
    untracked_paths = [
        line.strip()
        for line in (untracked.stdout if untracked.code == 0 else "").splitlines()
        if line.strip()
    ]
    tracked_paths = {str(item["path"]) for item in files}
    untracked_files: list[dict[str, Any]] = []
    for path in untracked_paths:
        if path in tracked_paths:
            continue
        additions, binary = _untracked_file_stats(work_root, path)
        if additions is not None:
            total_additions += additions
        untracked_files.append(
            {
                "path": path,
                "additions": additions,
                "deletions": 0 if additions is not None else None,
                "binary": binary,
            }
        )
    files.extend(untracked_files)

    if source == "checkpoint" and ref:
        git_state = (session.runtime_state or {}).get("git_state", {})
        checkpoint = git_state.get("last_checkpoint") or {}
        base_ref = str(checkpoint.get("base_head") or "")
        if base_ref:
            stat = await _git_manager.run(
                work_root,
                ["diff", "--stat", base_ref, ref, "--"],
                max_output_chars=12000,
            )
            patch = await _git_manager.run(
                work_root,
                ["diff", "--unified=80", base_ref, ref, "--", *[str(item["path"]) for item in files[:12]]],
                max_output_chars=60000,
            )
        else:
            stat = await _git_manager.run(
                work_root,
                ["show", "--stat", "--format=", ref],
                max_output_chars=12000,
            )
            patch = await _git_manager.run(
                work_root,
                ["show", "--format=", "--unified=80", ref, "--", *[str(item["path"]) for item in files[:12]]],
                max_output_chars=60000,
            )
    else:
        stat = await _git_manager.run(
            work_root,
            ["diff", "--stat", "--"],
            max_output_chars=12000,
        )
        patch = await _git_manager.run(
            work_root,
            ["diff", "--unified=80", "--", *[str(item["path"]) for item in files[:12]]],
            max_output_chars=60000,
        )
        if untracked_files:
            untracked_stat = _untracked_diff_stat(untracked_files)
            untracked_patch = _untracked_diff(work_root, untracked_files[:12], max_chars=30000)
            stat_stdout = stat.stdout if stat.code == 0 else ""
            patch_stdout = patch.stdout if patch.code == 0 else ""
            stat = GitCommandResult(
                code=0,
                stdout="\n".join(part for part in (stat_stdout, untracked_stat) if part.strip()),
                stderr="",
            )
            patch = GitCommandResult(
                code=0,
                stdout="\n".join(part for part in (patch_stdout, untracked_patch) if part.strip()),
                stderr="",
            )

    return _changes_response(
        files=files,
        total_additions=total_additions,
        total_deletions=total_deletions,
        diff_stat=stat.stdout if stat.code == 0 else "",
        diff=patch.stdout if patch.code == 0 else "",
        source=source,
        ref=ref,
    )


async def open_session_change_file_response(
    db: AsyncSession,
    session_id: str,
    path: str,
    *,
    opener: Callable[[Path], None] = open_with_default_app,
    fallback_opener: Callable[[Path], None] | None = None,
) -> dict[str, Any]:
    session = await _get_session(db, session_id)
    work_root = session.work_root
    if not work_root:
        raise ValueError("Session has no work_root set")
    target = _resolve_work_root_file(work_root, path)
    if not target.exists() or not target.is_file():
        raise FileNotFoundError(f"File not found: {path}")

    try:
        opener(target)
        opened_with = "default"
    except OSError:
        fallback = fallback_opener or open_with_notepad
        fallback(target)
        opened_with = "notepad"

    return {
        "status": "opened",
        "path": _relative_file_path(Path(work_root).resolve(), target),
        "opened_with": opened_with,
    }


def open_with_notepad(path: Path) -> None:
    if not sys.platform.startswith("win"):
        raise OSError("notepad fallback is only available on Windows")
    subprocess.Popen(["notepad", str(path)])


def _resolve_work_root_file(work_root: str, path: str) -> Path:
    if not path.strip():
        raise ValueError("path is required")
    root = Path(work_root).resolve()
    candidate = Path(path)
    target = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("File must be inside work_root") from exc
    return target


def _relative_file_path(root: Path, target: Path) -> str:
    return target.relative_to(root).as_posix()


async def _get_session(db: AsyncSession, session_id: str) -> WriterSession:
    result = await db.execute(select(WriterSession).where(WriterSession.id == session_id))
    session = result.scalar_one_or_none()
    if session is None:
        raise LookupError("Session not found")
    return session


def _changes_response(
    *,
    files: list[dict[str, Any]] | None = None,
    total_additions: int = 0,
    total_deletions: int = 0,
    diff_stat: str = "",
    diff: str = "",
    source: str = "git",
    ref: str | None = None,
) -> dict[str, Any]:
    return {
        "files": files or [],
        "total_additions": total_additions,
        "total_deletions": total_deletions,
        "diff_stat": diff_stat,
        "diff": diff,
        "source": source,
        "ref": ref,
    }


def _untracked_file_stats(work_root: str, rel_path: str) -> tuple[int | None, bool]:
    root = Path(work_root).resolve()
    target = (root / rel_path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return None, True
    if not target.exists() or not target.is_file():
        return None, True
    try:
        raw = target.read_bytes()
    except OSError:
        return None, True
    if b"\x00" in raw:
        return None, True
    text = raw.decode("utf-8", errors="replace")
    return len(text.splitlines()), False


def _untracked_diff_stat(files: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for item in files:
        if item["binary"]:
            lines.append(f" {item['path']} | Bin 0 -> ? bytes")
        else:
            additions = int(item["additions"] or 0)
            lines.append(f" {item['path']} | {additions} +{'+' * min(additions, 60)}")
    if files:
        lines.append(f" {len(files)} untracked file(s)")
    return "\n".join(lines)


def _untracked_diff(work_root: str, files: list[dict[str, Any]], *, max_chars: int) -> str:
    root = Path(work_root).resolve()
    chunks: list[str] = []
    used = 0
    for item in files:
        item_path = str(item["path"])
        target = (root / item_path).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            continue
        if item["binary"]:
            chunk = f"diff --git a/{item_path} b/{item_path}\nnew file mode 100644\nBinary files /dev/null and b/{item_path} differ\n"
        else:
            try:
                text = target.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            body = "".join(f"+{line}\n" for line in text.splitlines())
            line_count = len(text.splitlines())
            chunk = (
                f"diff --git a/{item_path} b/{item_path}\n"
                "new file mode 100644\n"
                "index 0000000..0000000\n"
                "--- /dev/null\n"
                f"+++ b/{item_path}\n"
                f"@@ -0,0 +1,{line_count} @@\n"
                f"{body}"
            )
        if used + len(chunk) > max_chars:
            chunks.append("\n... untracked diff truncated ...\n")
            break
        chunks.append(chunk)
        used += len(chunk)
    return "\n".join(chunks)
