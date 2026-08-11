from __future__ import annotations

import os
from pathlib import Path


def is_within_path(path: Path, root: Path) -> bool:
    resolved = path.resolve()
    boundary = root.resolve()
    resolved_norm = os.path.normcase(str(resolved))
    boundary_norm = os.path.normcase(str(boundary))
    return resolved_norm == boundary_norm or resolved_norm.startswith(boundary_norm + os.sep)


def validate_workspace_path(
    path: str | Path,
    work_root: str | Path,
    *,
    allow_outside: bool = False,
) -> Path:
    root = Path(work_root).resolve()
    resolved = (root / path).resolve()
    if not allow_outside and not is_within_path(resolved, root):
        raise ValueError(f"Path '{path}' is outside work_root '{work_root}'")
    return resolved


def relative_workspace_uri(path: Path, work_root: Path) -> str:
    try:
        return path.relative_to(work_root).as_posix()
    except ValueError:
        return path.as_posix()


def format_file_size(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes}B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f}KB"
    return f"{num_bytes / (1024 * 1024):.1f}MB"


def line_count(content: str) -> int:
    return content.count("\n") + (1 if content and not content.endswith("\n") else 0)


__all__ = [
    "format_file_size",
    "is_within_path",
    "line_count",
    "relative_workspace_uri",
    "validate_workspace_path",
]
