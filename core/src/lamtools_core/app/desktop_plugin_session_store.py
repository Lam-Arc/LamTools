"""Persistent mapping between desktop plugins and their dedicated sessions."""

from __future__ import annotations

import json
from pathlib import Path
from threading import RLock

from lamtools_core.config.root import atomic_write_text


class DesktopPluginSessionStore:
    """Store the authoritative ``desktop plugin -> session`` association.

    The file is deliberately separate from the plugin enablement registry and
    from the session database.  Deleting a session therefore leaves a stale
    mapping that ``ensure`` can detect and replace on its next call.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._lock = RLock()

    def get(self, plugin_id: str) -> str | None:
        key = str(plugin_id).strip()
        if not key:
            return None
        with self._lock:
            entry = self._load().get(key)
            if not isinstance(entry, dict):
                return None
            session_id = entry.get("session_id")
            return str(session_id).strip() or None if session_id is not None else None

    def set(self, plugin_id: str, session_id: str) -> None:
        key = str(plugin_id).strip()
        value = str(session_id).strip()
        if not key or not value:
            raise ValueError("plugin_id and session_id are required")
        with self._lock:
            data = self._load()
            data[key] = {"session_id": value}
            self._save(data)

    def delete(self, plugin_id: str) -> None:
        key = str(plugin_id).strip()
        if not key:
            return
        with self._lock:
            data = self._load()
            if key not in data:
                return
            del data[key]
            self._save(data)

    def _load(self) -> dict[str, object]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, json.JSONDecodeError):
            return {}
        if not isinstance(raw, dict):
            return {}
        return raw

    def _save(self, data: dict[str, object]) -> None:
        atomic_write_text(
            self.path,
            json.dumps(data, ensure_ascii=False, indent=2),
        )


__all__ = ["DesktopPluginSessionStore"]
