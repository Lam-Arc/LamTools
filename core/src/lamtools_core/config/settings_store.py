"""Namespaced app settings stored in a single jsonc file.

Replaces the former ``app_settings`` table in the shared config DB. Settings
live at ``{config_dir}/settings.jsonc`` under two-level namespaces, e.g.::

    {
      "lamtools": {
        "modelRouting": { "routes": { "core": { "model_id": "..." } } }
      },
      "core": {
        "imagegen":   { "enabled": false, "api_url": "", "api_key": "", "model": "" },
        "dreaming":   { "enabled": false, "min_turns": 3 },
        "onboarding": { "completed": false }
      }
    }

``get_setting("core.dreaming")`` reads ``["core"]["dreaming"]``; setting a
namespace creates intermediate objects as needed. Missing namespaces return
``None`` so callers can fall back to their defaults.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lamtools_core.config.root import core_config_file
from lamtools_core.llm.profiles import load_jsonc

SETTINGS_FILENAME = "settings.jsonc"

_EMPTY = object()


def settings_path() -> Path:
    """Return the settings.jsonc path (unified config directory)."""
    return core_config_file(SETTINGS_FILENAME)


def _split_namespace(namespace: str) -> tuple[str, str]:
    parts = str(namespace or "").split(".", 1)
    group = parts[0].strip()
    key = parts[1].strip() if len(parts) > 1 else ""
    return group, key


def _read_map(path: Path | None = None) -> dict[str, Any]:
    target = path or settings_path()
    try:
        data = load_jsonc(target)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def get_setting(namespace: str, *, path: Path | None = None) -> Any:
    """Return the value for a two-level namespace, or ``None`` when absent."""
    group, key = _split_namespace(namespace)
    data = _read_map(path)
    group_value = data.get(group)
    if not isinstance(group_value, dict):
        return None
    if not key:
        return group_value
    return group_value.get(key)


def set_setting(namespace: str, value: Any, *, path: Path | None = None) -> Path:
    """Write a two-level namespace value to settings.jsonc (atomic-ish)."""
    group, key = _split_namespace(namespace)
    target = path or settings_path()
    data = _read_map(target)
    group_value = data.get(group)
    if not isinstance(group_value, dict):
        group_value = {}
    if key:
        group_value[key] = value
    else:
        group_value = value if isinstance(value, dict) else {}
    data[group] = group_value
    target.parent.mkdir(parents=True, exist_ok=True)
    import json

    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def delete_setting(namespace: str, *, path: Path | None = None) -> bool:
    """Remove a two-level namespace; returns True when something was removed."""
    group, key = _split_namespace(namespace)
    target = path or settings_path()
    data = _read_map(target)
    group_value = data.get(group)
    if not isinstance(group_value, dict):
        return False
    if key:
        if key not in group_value:
            return False
        del group_value[key]
    else:
        if group not in data:
            return False
        del data[group]
    import json

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


__all__ = [
    "SETTINGS_FILENAME",
    "delete_setting",
    "get_setting",
    "set_setting",
    "settings_path",
]
