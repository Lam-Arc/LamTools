from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException


def normalize_work_root(value: str | None, *, field: str = "work_root") -> str:
    raw = (value or "").strip()
    if not raw:
        return ""

    expanded = Path(raw).expanduser().resolve()
    if not expanded.is_absolute():
        raise HTTPException(
            status_code=400,
            detail=f"{field} must be an absolute path",
        )
    return str(expanded)


def ensure_work_root(value: str | None, *, field: str = "work_root") -> str:
    work_root = normalize_work_root(value, field=field)
    if not work_root:
        return ""
    path = Path(work_root)
    if path.exists() and not path.is_dir():
        raise HTTPException(
            status_code=400,
            detail=f"{field} must point to a directory",
        )
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"{field} cannot be created: {exc}",
        ) from exc
    return str(path.resolve())
