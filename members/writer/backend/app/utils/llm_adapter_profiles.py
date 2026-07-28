from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from lamtools_core.llm.profiles import (
    load_adapter_profiles_from_dirs,
    resolve_adapter_profile_from_profiles,
)

from app.core.resource_dirs import appdata_writer_dir, core_resource_roots, writer_resource_roots


def _writer_source_profile_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "llm_adapters"


def _core_builtin_profile_dirs() -> list[Path]:
    return _dedupe_dirs([root / "config" / "llm_adapters" for root in core_resource_roots()])


def _writer_builtin_profile_dirs() -> list[Path]:
    return [_writer_source_profile_dir()]


def _runtime_profile_dirs() -> list[Path]:
    dirs: list[Path] = []
    for root in writer_resource_roots():
        dirs.extend([
            root / "llm_adapters",
            root / "backend" / "app" / "llm_adapters",
        ])
    return _dedupe_dirs(dirs)


def _default_profile_dirs() -> list[Path]:
    dirs: list[Path] = []
    dirs.extend(_core_builtin_profile_dirs())
    dirs.extend(_writer_builtin_profile_dirs())
    dirs.extend(_runtime_profile_dirs())
    return _dedupe_dirs(dirs)


def _user_profile_dirs() -> list[Path]:
    dirs: list[Path] = []
    env_dir = os.environ.get("LAMWRITER_LLM_ADAPTER_DIR")
    if env_dir:
        dirs.append(Path(env_dir))
    appdata = appdata_writer_dir()
    if appdata is not None:
        dirs.append(appdata / "llm-adapters")
    return _dedupe_dirs(dirs)


def _dedupe_dirs(dirs: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for directory in dirs:
        key = os.path.normcase(str(directory.resolve()))
        if key in seen:
            continue
        seen.add(key)
        result.append(directory)
    return result


@lru_cache(maxsize=1)
def load_adapter_profiles() -> dict[str, dict[str, Any]]:
    return load_adapter_profiles_from_dirs([*_default_profile_dirs(), *_user_profile_dirs()])


def resolve_adapter_profile(
    *,
    api_type: str,
    base_url: str,
    provider_extra: dict[str, Any] | None = None,
    model_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return resolve_adapter_profile_from_profiles(
        load_adapter_profiles(),
        api_type=api_type,
        base_url=base_url,
        provider_extra=provider_extra,
        model_extra=model_extra,
    )


__all__ = [
    "load_adapter_profiles",
    "resolve_adapter_profile",
]
