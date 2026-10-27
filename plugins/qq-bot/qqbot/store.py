"""Per-peer preferences persisted in the plugin data directory.

The upstream plugin stores ``model-prefs.json`` under ``~/.dsh-qqbot``.  The
host gives every plugin an isolated data directory, so the same file lives
there and survives updates/uninstall-with-keep-data.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from .util import write_json


class PrefsStore:
    def __init__(self, data_dir: Path) -> None:
        self.path = Path(data_dir) / "prefs.json"
        self._lock = threading.RLock()
        self._data: dict[str, Any] = {
            "overrides": {},
            "sessionIds": {},
            "presets": {},
            "generations": {},
        }
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for key in ("overrides", "sessionIds", "presets", "generations"):
                    value = raw.get(key)
                    if isinstance(value, dict):
                        self._data[key] = value
        except Exception:
            pass

    def _write(self) -> None:
        try:
            write_json(self.path, self._data)
        except Exception:
            pass

    # ── model override ─────────────────────────────────────────────────────
    def get_override(self, key: str) -> dict[str, str] | None:
        with self._lock:
            value = self._data["overrides"].get(key)
            if isinstance(value, dict) and value.get("provider") and value.get("model"):
                return {"provider": str(value["provider"]), "model": str(value["model"])}
            return None

    def set_override(self, key: str, provider: str, model: str) -> None:
        with self._lock:
            self._data["overrides"][key] = {"provider": str(provider), "model": str(model)}
            self._write()

    def clear_override(self, key: str) -> None:
        with self._lock:
            self._data["overrides"].pop(key, None)
            self._write()

    # ── session id ─────────────────────────────────────────────────────────
    def get_session_id(self, key: str) -> str | None:
        with self._lock:
            value = self._data["sessionIds"].get(key)
            return str(value) if value else None

    def set_session_id(self, key: str, session_id: str) -> None:
        with self._lock:
            if session_id:
                self._data["sessionIds"][key] = str(session_id)
            else:
                self._data["sessionIds"].pop(key, None)
            self._write()

    # ── preset ─────────────────────────────────────────────────────────────
    def get_preset(self, key: str) -> str | None:
        with self._lock:
            value = self._data["presets"].get(key)
            return str(value) if value else None

    def set_preset(self, key: str, preset_id: str) -> None:
        with self._lock:
            if preset_id:
                self._data["presets"][key] = str(preset_id)
            else:
                self._data["presets"].pop(key, None)
            self._write()

    # ── generation (new session) ───────────────────────────────────────────
    def get_generation(self, key: str) -> int:
        with self._lock:
            try:
                return int(self._data["generations"].get(key) or 0)
            except Exception:
                return 0

    def bump_generation(self, key: str) -> int:
        with self._lock:
            value = self.get_generation(key) + 1
            self._data["generations"][key] = value
            self._write()
            return value


__all__ = ["PrefsStore"]
