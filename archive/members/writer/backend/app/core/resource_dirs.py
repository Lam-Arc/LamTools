from __future__ import annotations

import os
import sys
from pathlib import Path


def _split_env_paths(name: str) -> list[Path]:
    value = os.environ.get(name, "")
    if not value:
        return []
    return [Path(item) for item in value.split(os.pathsep) if item.strip()]


def _dedupe(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        key = os.path.normcase(str(resolved))
        if key in seen:
            continue
        seen.add(key)
        result.append(resolved)
    return result


def _find_repo_root() -> Path | None:
    starts = [Path.cwd(), Path(__file__).resolve()]
    for start in starts:
        for candidate in (start, *start.parents):
            if (candidate / "core" / "src" / "lamtools_core").is_dir() and (candidate / "members").is_dir():
                return candidate
    return None


def _packaged_resources_dir() -> Path | None:
    if not getattr(sys, "frozen", False):
        return None
    executable = Path(sys.executable).resolve()
    resources = executable.parent.parent
    if (resources / "backend").exists() or (resources / "runtime").exists():
        return resources
    return None


def runtime_root() -> Path | None:
    env = os.environ.get("LAMTOOLS_RUNTIME_ROOT")
    if env:
        return Path(env).resolve()
    resources = _packaged_resources_dir()
    if resources is not None:
        return (resources / "runtime").resolve()
    return None


def repo_root() -> Path | None:
    env = os.environ.get("LAMTOOLS_REPO_ROOT")
    if env:
        return Path(env).resolve()
    return _find_repo_root()


def core_resource_roots() -> list[Path]:
    roots: list[Path] = []
    roots.extend(_split_env_paths("LAMTOOLS_CORE_RESOURCE_DIR"))
    root = runtime_root()
    if root is not None:
        roots.append(root / "core")
    repo = repo_root()
    if repo is not None:
        roots.append(repo / "core")
    return _dedupe(roots)


def member_resource_roots(member_id: str) -> list[Path]:
    member_key = member_id.upper().replace("-", "_")
    roots: list[Path] = []
    roots.extend(_split_env_paths(f"LAM{member_key}_MEMBER_RESOURCE_DIR"))
    roots.extend(_split_env_paths("LAMTOOLS_MEMBER_RESOURCE_DIR"))
    root = runtime_root()
    if root is not None:
        roots.append(root / "members" / member_id)
    repo = repo_root()
    if repo is not None:
        roots.append(repo / "members" / member_id)
    return _dedupe(roots)


def writer_resource_roots() -> list[Path]:
    return member_resource_roots("writer")


def appdata_writer_dir() -> Path | None:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    return Path(appdata) / "LamWriter"
