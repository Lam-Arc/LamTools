"""Detect external edits to the jsonc config and surface them to the user.

Provider / model / settings jsonc files can be rewritten behind the app's back:
cloud-drive or backup sync, a text editor, a second instance on the same
machine, or restoring a backup.  The stores used to reload the new values
silently, so the next model call simply used whatever the file now said while
the user had no idea anything changed.

This module keeps a process-wide observation baseline (independent of any one
store instance's cache lifetime) and records a notice whenever a file the app
did not itself write appears with a different mtime/size, or a file is added
or removed.  Notices are drained by ``config.notices.drain`` and shown by the
UI, so an external change is always announced instead of silently applied.

Only file identity + change kind is recorded — never file contents, so an
api key can never leak through this path.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

#: Kinds of config file the watcher understands (also the UI's label source).
KIND_LABELS = {
    "provider": "供应商配置",
    "model": "模型配置",
    "settings": "应用设置",
}

CHANGE_LABELS = {
    "modified": "被外部修改",
    "added": "新增",
    "removed": "被删除",
}

#: Bound on queued notices so a pathological sync loop cannot grow unbounded.
MAX_PENDING_NOTICES = 50

_lock = threading.RLock()
#: kind → {resolved path str: (mtime_ns, size)} as last observed by this process.
_baseline: dict[str, dict[str, tuple[int, int]]] = {}
#: path str → (mtime_ns, size) snapshot of a write this process just performed.
_self_written: dict[str, tuple[int, int]] = {}
_pending: list["ConfigChangeNotice"] = []


@dataclass(frozen=True)
class ConfigChangeNotice:
    kind: str
    path: str
    name: str
    change: str

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "path": self.path,
            "name": self.name,
            "change": self.change,
            "message": self.message,
        }

    @property
    def message(self) -> str:
        kind_label = KIND_LABELS.get(self.kind, self.kind)
        change_label = CHANGE_LABELS.get(self.change, self.change)
        target = self.name or "配置"
        return f"{kind_label}「{target}」{change_label}，已按新内容生效"


def _stat_key(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def _label(path: Path) -> str:
    return path.stem or path.name


def _queue(notice: ConfigChangeNotice) -> None:
    _pending.append(notice)
    if len(_pending) > MAX_PENDING_NOTICES:
        del _pending[: len(_pending) - MAX_PENDING_NOTICES]


def observe_config_files(kind: str, paths) -> list[ConfigChangeNotice]:
    """Compare ``paths`` with the process baseline and queue change notices.

    The first observation of a kind only establishes the baseline (the app's own
    start-up load is not a change).  A file this process just wrote is treated as
    expected and refreshes the baseline without producing a notice.
    """
    resolved: list[Path] = []
    seen: set[str] = set()
    for raw in paths:
        try:
            path = Path(raw).resolve()
        except (OSError, ValueError):
            continue
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        resolved.append(path)

    with _lock:
        previous = _baseline.get(kind)
        current: dict[str, tuple[int, int]] = {}
        notices: list[ConfigChangeNotice] = []
        for path in resolved:
            key = str(path)
            key_stat = _stat_key(path)
            if key_stat is None:
                continue
            current[key] = key_stat
            self_written = _self_written.pop(key, None)
            if self_written is not None:
                continue  # our own write; baseline only
            if previous is None:
                continue  # first observation of this kind
            if key in previous:
                if previous[key] != key_stat:
                    notices.append(ConfigChangeNotice(kind, key, _label(path), "modified"))
            else:
                notices.append(ConfigChangeNotice(kind, key, _label(path), "added"))
        if previous is not None:
            for key in previous:
                if key not in current:
                    notices.append(ConfigChangeNotice(kind, key, _label(Path(key)), "removed"))
        _baseline[kind] = current
        for notice in notices:
            _queue(notice)
        return notices


def mark_self_written(path) -> None:
    """Record that this process is about to write ``path``.

    The next observation of that exact file state refreshes the baseline
    without a notice, so the app never reports its own configuration writes
    as external edits.
    """
    try:
        resolved = Path(path).resolve()
    except (OSError, ValueError):
        return
    with _lock:
        _self_written[str(resolved)] = _stat_key(resolved) or (0, 0)


def drain_config_change_notices() -> list[dict[str, str]]:
    """Return and clear queued notices (the UI's single drain point)."""
    with _lock:
        drained = [notice.to_dict() for notice in _pending]
        _pending.clear()
        return drained


def reset_config_change_notices() -> None:
    """Drop all baselines and queued notices (tests / process-level reset)."""
    with _lock:
        _baseline.clear()
        _self_written.clear()
        _pending.clear()


__all__ = [
    "CHANGE_LABELS",
    "KIND_LABELS",
    "MAX_PENDING_NOTICES",
    "ConfigChangeNotice",
    "drain_config_change_notices",
    "mark_self_written",
    "observe_config_files",
    "reset_config_change_notices",
]
