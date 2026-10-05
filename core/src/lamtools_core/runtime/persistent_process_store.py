"""Durable archive of long-lived (persistent) background process records."""

from __future__ import annotations

import json
from pathlib import Path
from threading import RLock

from lamtools_core.config.root import atomic_write_text

_ARCHIVE_VERSION = 1


class PersistentProcessStore:
    """JSON archive of persistent background process records.

    The archive exists so a restarted backend can still show which long-lived
    processes a session had registered, and whether their pid is still alive.
    It is deliberately not the source of truth while the backend runs — the
    in-memory registry is; the archive is rewritten whenever the set of
    persistent records changes.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._lock = RLock()

    def load(self) -> list[dict[str, object]]:
        with self._lock:
            if not self.path.exists():
                return []
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                return []
            if not isinstance(raw, dict) or raw.get("version") != _ARCHIVE_VERSION:
                return []
            processes = raw.get("processes")
            if not isinstance(processes, list):
                return []
            return [dict(item) for item in processes if isinstance(item, dict)]

    def save(self, records: list[dict[str, object]]) -> None:
        payload = {"version": _ARCHIVE_VERSION, "processes": list(records)}
        with self._lock:
            atomic_write_text(self.path, json.dumps(payload, ensure_ascii=False, indent=2))


__all__ = ["PersistentProcessStore"]
