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

import json
import threading
import uuid
from pathlib import Path
from typing import Any

from lamtools_core.config.root import core_config_file
from lamtools_core.llm.profiles import load_jsonc

SETTINGS_FILENAME = "settings.jsonc"

_EMPTY = object()
_SETTINGS_LOCK = threading.RLock()


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
    from .change_notice import observe_config_files

    observe_config_files("settings", [target])
    try:
        data = load_jsonc(target)
    except FileNotFoundError:
        return {}
    except ValueError:
        _backup_corrupt_file(target)
        return {}
    if not isinstance(data, dict):
        _backup_corrupt_file(target)
        return {}
    return data


def _backup_corrupt_file(target: Path) -> Path:
    """Move malformed settings aside without ever replacing an older backup.

    If preservation fails, propagate the filesystem error.  A write must not
    continue from an empty map and destroy the only recoverable copy.
    """
    backup = target.with_name(f"{target.name}.corrupt-{uuid.uuid4().hex}.bak")
    target.rename(backup)
    return backup


def _validate_namespace(namespace: str) -> tuple[str, str]:
    group, key = _split_namespace(namespace)
    if not group:
        raise ValueError("settings namespace group must not be empty")
    return group, key


def get_setting(namespace: str, *, path: Path | None = None) -> Any:
    """Return the value for a two-level namespace, or ``None`` when absent."""
    group, key = _validate_namespace(namespace)
    with _SETTINGS_LOCK:
        data = _read_map(path)
        group_value = data.get(group)
        if not isinstance(group_value, dict):
            return None
        if not key:
            return group_value
        return group_value.get(key)


def set_setting(namespace: str, value: Any, *, path: Path | None = None) -> Path:
    """Write a two-level namespace value to settings.jsonc (atomic)."""
    group, key = _validate_namespace(namespace)
    target = path or settings_path()
    with _SETTINGS_LOCK:
        data = _read_map(target)
        group_value = data.get(group)
        if not isinstance(group_value, dict):
            group_value = {}
        if key:
            group_value[key] = value
        else:
            group_value = value if isinstance(value, dict) else {}
        data[group] = group_value
        from lamtools_core.config.root import atomic_write_text

        atomic_write_text(target, json.dumps(data, ensure_ascii=False, indent=2))
    from .change_notice import mark_self_written

    mark_self_written(target)
    return target


def delete_setting(namespace: str, *, path: Path | None = None) -> bool:
    """Remove a two-level namespace; returns True when something was removed."""
    group, key = _validate_namespace(namespace)
    target = path or settings_path()
    with _SETTINGS_LOCK:
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
        from lamtools_core.config.root import atomic_write_text

        atomic_write_text(target, json.dumps(data, ensure_ascii=False, indent=2))
    from .change_notice import mark_self_written

    mark_self_written(target)
    return True


__all__ = [
    "SETTINGS_FILENAME",
    "delete_setting",
    "get_setting",
    "set_setting",
    "settings_path",
]
