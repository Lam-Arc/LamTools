"""Directory-backed long-term memory shared by the tool, RPC and CLI.

Memory is plain files under two tiers:

- ``global``  — ``<core_config_dir>/memory/`` (cross-project, user level)
- ``project`` — ``<work_root>/.lam/memory/`` (per workspace)

The directory tree *is* the index.  Each tier carries a reserved
``INDEX.md`` that is fully generated from the tree (directory layout plus a
one-line summary per file) and injected into every session, so the model
learns what is stored without reading every file.  The model then uses the
``memory`` tool to list, read and edit the files.

``INDEX.md`` is generated output: it is never searched for content, never
returned as a memory file, and cannot be written, renamed or deleted through
any surface.  The name is reserved at every depth of the tree, so a memory
file may never shadow the index of its tier.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from lamtools_core.config.root import core_config_dir
from lamtools_core.tool.workspace import is_within_path

SCOPE_GLOBAL = "global"
SCOPE_PROJECT = "project"

INDEX_FILENAME = "INDEX.md"

#: Paths the tool and RPC refuse to write to / delete / rename.
RESERVED_NAMES: frozenset[str] = frozenset({INDEX_FILENAME})

#: Hard cap for a single ``read`` so a runaway file cannot flood the context.
MAX_READ_CHARS = 200_000

#: Cap for the injected index (matches other context files).
MAX_INDEX_CHARS = 20_000

#: Files considered when rendering the index; beyond this the tree is
#: summarised instead of enumerated.
MAX_INDEX_ENTRIES = 400

_MAX_SUMMARY_CHARS = 100
_SUMMARY_READ_BYTES = 4096


class MemoryError(Exception):
    """Base error for memory operations; ``code`` maps to the tool error code."""

    code = "memory_error"


class MemoryPathError(MemoryError):
    code = "invalid_path"


class MemoryNotFoundError(MemoryError):
    code = "not_found"


class MemoryReservedError(MemoryError):
    code = "reserved_name"


class MemoryConflictError(MemoryError):
    code = "conflict"


@dataclass
class MemoryEntry:
    path: str
    is_dir: bool
    size: int = 0
    modified: str = ""
    summary: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "is_dir": self.is_dir,
            "size": self.size,
            "modified": self.modified,
            "summary": self.summary,
        }


def memory_root(scope: str, work_root: str | Path | None) -> Path:
    """Return the memory directory for *scope* (never created here)."""
    normalized = _normalize_scope(scope)
    if normalized == SCOPE_GLOBAL:
        return core_config_dir() / "memory"
    if not work_root:
        raise MemoryPathError("project scope requires a workspace root")
    return Path(work_root).expanduser() / ".lam" / "memory"


_memory_root = memory_root


def _normalize_scope(scope: str) -> str:
    value = str(scope or "").strip().lower()
    if value in ("", "local", "workspace", "project"):
        return SCOPE_PROJECT
    if value in ("global", "user"):
        return SCOPE_GLOBAL
    raise MemoryPathError(f"unknown memory scope '{scope}' (expected project or global)")


def normalize_scope(scope: str) -> str:
    return _normalize_scope(scope)


# ---------------------------------------------------------------------------
# Path resolution / sandbox
# ---------------------------------------------------------------------------


def _clean_relative(relative: str) -> str:
    raw = str(relative or "").strip().replace("\\", "/")
    if raw.startswith("/"):
        raise MemoryPathError("memory paths are relative to the memory root")
    if len(raw) >= 2 and raw[1] == ":":
        raise MemoryPathError("memory paths must not contain a drive letter")
    parts: list[str] = []
    for segment in raw.split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            raise MemoryPathError("memory paths must not contain '..'")
        parts.append(segment)
    return "/".join(parts)


def _require_relative(relative: str) -> str:
    """Clean a path argument that must name an entry inside the tier.

    An empty path would otherwise resolve to the tier root itself, and a
    file-level mutation would then create/replace a *file* at the tier
    directory's path.
    """
    cleaned = _clean_relative(relative)
    if not cleaned:
        raise MemoryPathError("a memory file path is required")
    return cleaned


def resolve_memory_path(
    scope: str,
    work_root: str | Path | None,
    relative: str = "",
    *,
    allow_index: bool = False,
) -> Path:
    """Resolve *relative* inside the tier, refusing anything outside it."""
    root = _memory_root(scope, work_root)
    cleaned = _clean_relative(relative)
    if cleaned.split("/")[-1] in RESERVED_NAMES and not allow_index:
        raise MemoryReservedError(f"'{INDEX_FILENAME}' is generated and cannot be modified")
    target = (root / cleaned).resolve() if cleaned else root.resolve()
    if not is_within_path(target, root):
        raise MemoryPathError("memory path escapes the memory root")
    return target


# ---------------------------------------------------------------------------
# Mutations (each one refreshes the tier index)
# ---------------------------------------------------------------------------


def list_entries(
    scope: str,
    work_root: str | Path | None,
    *,
    path: str = "",
    recursive: bool = True,
    max_depth: int = 0,
) -> list[MemoryEntry]:
    """List files and directories under *path* (``INDEX.md`` is skipped)."""
    base = resolve_memory_path(scope, work_root, path, allow_index=True)
    if not base.is_dir():
        if not _clean_relative(path):
            return []
        raise MemoryNotFoundError(f"no such memory directory: {path}")
    root = _memory_root(scope, work_root).resolve()
    entries: list[MemoryEntry] = []
    for current, dirnames, filenames in os.walk(base):
        current_path = Path(current)
        depth = len(current_path.relative_to(base).parts)
        if not recursive:
            dirnames[:] = []
        elif max_depth and depth >= max_depth:
            dirnames[:] = []
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for name in sorted(filenames):
            if name in RESERVED_NAMES or name.startswith("."):
                continue
            file_path = current_path / name
            entries.append(_entry_for(file_path, root, is_dir=False))
        for name in dirnames:
            entries.append(_entry_for(current_path / name, root, is_dir=True))
    return entries


def read_memory(scope: str, work_root: str | Path | None, path: str) -> str:
    target = resolve_memory_path(scope, work_root, path)
    if not target.is_file():
        raise MemoryNotFoundError(f"memory file not found: {path}")
    try:
        text = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise MemoryError(f"could not read memory file: {exc}") from exc
    if len(text) > MAX_READ_CHARS:
        text = text[:MAX_READ_CHARS] + "\n\n[truncated: file exceeds the read limit]"
    return text


def write_memory(scope: str, work_root: str | Path | None, path: str, content: str) -> MemoryEntry:
    target = resolve_memory_path(scope, work_root, _require_relative(path))
    if target.is_dir():
        raise MemoryPathError(f"'{path}' is a directory")
    target.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(target, str(content or ""))
    refresh_index(scope, work_root)
    return _entry_for(target, _memory_root(scope, work_root).resolve(), is_dir=False)


def append_memory(scope: str, work_root: str | Path | None, path: str, content: str) -> MemoryEntry:
    target = resolve_memory_path(scope, work_root, _require_relative(path))
    if target.is_dir():
        raise MemoryPathError(f"'{path}' is a directory")
    existing = ""
    if target.is_file():
        try:
            existing = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            existing = ""
    addition = str(content or "")
    if existing and not existing.endswith("\n"):
        existing += "\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(target, existing + addition)
    refresh_index(scope, work_root)
    return _entry_for(target, _memory_root(scope, work_root).resolve(), is_dir=False)


def edit_memory(
    scope: str,
    work_root: str | Path | None,
    path: str,
    old_string: str,
    new_string: str,
    *,
    occurrence: int | None = None,
) -> MemoryEntry:
    """Replace *old_string* with *new_string*.

    Without *occurrence*, an ambiguous match is refused rather than guessed at;
    pass a 1-based *occurrence* to pick one when the text genuinely repeats.
    """
    target = resolve_memory_path(scope, work_root, _require_relative(path))
    if not target.is_file():
        raise MemoryNotFoundError(f"memory file not found: {path}")
    old = str(old_string or "")
    if not old:
        raise MemoryPathError("old_string must not be empty")
    try:
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise MemoryError(f"could not read memory file: {exc}") from exc
    matches = text.count(old)
    if matches == 0:
        raise MemoryNotFoundError("old_string not found in the memory file")
    if matches > 1 and (occurrence is None or occurrence <= 0):
        raise MemoryConflictError(
            f"old_string matched {matches} times; pass occurrence (1-based) or a longer unique string"
        )
    index = 1 if occurrence is None or occurrence <= 0 else occurrence
    if index > matches:
        raise MemoryConflictError(f"occurrence {index} exceeds the {matches} matches found")
    start = -1
    scan = 0
    for _ in range(index):
        start = text.find(old, scan)
        scan = start + len(old)
    updated = text[:start] + str(new_string or "") + text[start + len(old):]
    _atomic_write(target, updated)
    refresh_index(scope, work_root)
    return _entry_for(target, _memory_root(scope, work_root).resolve(), is_dir=False)


def delete_memory(scope: str, work_root: str | Path | None, path: str) -> str:
    target = resolve_memory_path(scope, work_root, path)
    if target == _memory_root(scope, work_root).resolve():
        raise MemoryPathError("refusing to delete the memory root")
    if target.is_dir():
        shutil.rmtree(target)
    elif target.is_file():
        target.unlink()
    else:
        raise MemoryNotFoundError(f"memory entry not found: {path}")
    refresh_index(scope, work_root)
    return path


def rename_memory(scope: str, work_root: str | Path | None, path: str, new_path: str) -> str:
    source = resolve_memory_path(scope, work_root, _require_relative(path))
    if not source.exists():
        raise MemoryNotFoundError(f"memory entry not found: {path}")
    destination = resolve_memory_path(scope, work_root, _require_relative(new_path))
    if destination.exists():
        raise MemoryConflictError(f"destination already exists: {new_path}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.replace(source, destination)
    refresh_index(scope, work_root)
    return new_path


def make_directory(scope: str, work_root: str | Path | None, path: str) -> str:
    target = resolve_memory_path(scope, work_root, path)
    if target.exists() and not target.is_dir():
        raise MemoryConflictError(f"'{path}' already exists as a file")
    target.mkdir(parents=True, exist_ok=True)
    refresh_index(scope, work_root)
    return path


# ---------------------------------------------------------------------------
# Index generation
# ---------------------------------------------------------------------------


def render_index(scope: str, work_root: str | Path | None) -> str:
    """Render the generated index for *scope* (never reads ``INDEX.md``)."""
    normalized = _normalize_scope(scope)
    root = _memory_root(normalized, work_root)
    label = "Global Memory Index" if normalized == SCOPE_GLOBAL else "Project Memory Index"
    scope_hint = (
        "跨项目共享的全局记忆" if normalized == SCOPE_GLOBAL else "仅当前项目生效的项目记忆"
    )
    lines = [
        f"# {label}",
        "",
        "> 本文件由 LamTools 按记忆库目录结构自动生成，请勿手动编辑。",
        f"> 档位：{scope_hint}。使用 memory 工具（scope={normalized}）读取或写入本档记忆。",
        "",
    ]
    if not root.is_dir():
        lines.append("（本档暂无记忆）")
        return "\n".join(lines).rstrip() + "\n"

    entries = _tree_entries(root)
    if not entries:
        lines.append("（本档暂无记忆）")
        return "\n".join(lines).rstrip() + "\n"

    lines.append("## 目录")
    lines.append("")
    truncated = len(entries) > MAX_INDEX_ENTRIES
    for entry in entries[:MAX_INDEX_ENTRIES]:
        indent = "  " * (entry.path.count("/"))
        name = entry.path.rsplit("/", 1)[-1]
        if entry.is_dir:
            lines.append(f"{indent}- `{name}/`")
        else:
            summary = f" — {entry.summary}" if entry.summary else ""
            stamp = f" ({entry.modified})" if entry.modified else ""
            lines.append(f"{indent}- `{name}`{summary}{stamp}")
    if truncated:
        lines.append("")
        lines.append(f"（其余 {len(entries) - MAX_INDEX_ENTRIES} 项已省略，请用 memory 工具列出）")
    text = "\n".join(lines).rstrip() + "\n"
    if len(text) > MAX_INDEX_CHARS:
        text = text[:MAX_INDEX_CHARS] + "\n\n[index truncated]\n"
    return text


def refresh_index(scope: str, work_root: str | Path | None) -> str:
    """Regenerate the index, write it when it drifted, and return its text.

    Returns the empty string when the tier cannot be resolved at all (e.g. a
    project scope with no workspace); write failures never fail the caller —
    the on-disk copy is a convenience, the rendered text is what matters.
    """
    try:
        root = _memory_root(scope, work_root)
    except MemoryError:
        return ""
    text = render_index(scope, work_root)
    target = root / INDEX_FILENAME
    try:
        root.mkdir(parents=True, exist_ok=True)
        existing = target.read_text(encoding="utf-8") if target.is_file() else None
        if existing != text:
            _atomic_write(target, text)
    except OSError:
        return text
    return text


def has_content(scope: str, work_root: str | Path | None) -> bool:
    """Whether the tier holds at least one real memory file.

    Pure existence check: nothing is created and the generated ``INDEX.md`` is
    ignored, so probing empty or untouched projects leaves them untouched.
    """
    try:
        root = _memory_root(scope, work_root)
    except MemoryError:
        return False
    return root.is_dir() and any(_iter_files(root))


def index_text_for_prompt(scope: str, work_root: str | Path | None) -> str:
    """Regenerate the index and return its text (empty when there is nothing)."""
    if not has_content(scope, work_root):
        return ""
    return refresh_index(scope, work_root).strip()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tree_entries(root: Path) -> list[MemoryEntry]:
    """Depth-first listing so the generated index mirrors the folder tree."""
    entries: list[MemoryEntry] = []

    def walk(directory: Path) -> None:
        try:
            children = sorted(
                directory.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())
            )
        except OSError:
            return
        for child in children:
            if child.name.startswith(".") or child.name in RESERVED_NAMES:
                continue
            if child.is_dir():
                entries.append(_entry_for(child, root, is_dir=True))
                walk(child)
            else:
                entries.append(_entry_for(child, root, is_dir=False))

    walk(root)
    return entries


def _iter_files(root: Path):
    for current, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if name in RESERVED_NAMES or name.startswith("."):
                continue
            yield Path(current) / name


def _entry_for(path: Path, root: Path, *, is_dir: bool) -> MemoryEntry:
    if path.is_dir():
        return MemoryEntry(path=_rel(path, root), is_dir=True)
    size = 0
    modified = ""
    summary = ""
    try:
        stat = path.stat()
        size = int(stat.st_size)
        modified = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
    except OSError:
        pass
    if not is_dir:
        summary = _summarize(path)
    return MemoryEntry(
        path=_rel(path, root),
        is_dir=is_dir,
        size=size,
        modified=modified,
        summary=summary,
    )


def _rel(path: Path, root: Path) -> str:
    if path == root:
        return ""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _summarize(path: Path) -> str:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            chunk = handle.read(_SUMMARY_READ_BYTES)
    except OSError:
        return ""
    for line in chunk.splitlines():
        text = line.strip()
        if not text:
            continue
        text = text.lstrip("#>*- ").strip()
        if not text:
            continue
        if text[:3] in ("[ ]", "[x]"):
            # A todo checkbox marker is structure, not content.
            text = text[3:].lstrip()
        return text[:_MAX_SUMMARY_CHARS]
    return ""


def reveal_memory(scope: str, work_root: str | Path | None) -> str:
    """Ensure the tier folder exists, open it in the OS file manager, and
    return its path — the human entry to a memory library.

    Memory is literally a folder of plain files, so the file manager IS the
    interface: the model edits it through the ``memory`` tool, the user
    browses it with Explorer/Finder.
    """
    from lamtools_core.attachment.files import open_with_default_app

    root = memory_root(scope, work_root)
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise MemoryError(f"could not create memory folder: {exc}") from exc
    open_with_default_app(root)
    return str(root)


def _atomic_write(path: Path, text: str) -> None:
    """Replace *path* atomically (tmp file + fsync + rename).

    Windows can briefly reject the replace while another process (an indexer,
    a scanner, a second agent turn) holds either file open. Keep the original
    intact and retry only the known sharing/access-denied errors (audit 11);
    surface the final error if the file stays unavailable.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    retry_delays = (0.025, 0.05, 0.1, 0.2) if sys.platform == "win32" else ()
    for delay in (*retry_delays, None):
        try:
            os.replace(tmp, path)
            return
        except OSError as exc:
            if delay is None or getattr(exc, "winerror", None) not in (5, 32, 33):
                with contextlib.suppress(OSError):
                    tmp.unlink(missing_ok=True)
                raise
            time.sleep(delay)


__all__ = [
    "INDEX_FILENAME",
    "MAX_INDEX_CHARS",
    "MAX_READ_CHARS",
    "RESERVED_NAMES",
    "SCOPE_GLOBAL",
    "SCOPE_PROJECT",
    "MemoryConflictError",
    "MemoryEntry",
    "MemoryError",
    "MemoryNotFoundError",
    "MemoryPathError",
    "MemoryReservedError",
    "append_memory",
    "delete_memory",
    "edit_memory",
    "has_content",
    "index_text_for_prompt",
    "list_entries",
    "make_directory",
    "memory_root",
    "normalize_scope",
    "read_memory",
    "refresh_index",
    "rename_memory",
    "render_index",
    "resolve_memory_path",
    "reveal_memory",
    "write_memory",
]
