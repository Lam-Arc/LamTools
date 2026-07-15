"""Ownership registry for background processes started by Core tools."""

from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from lamtools_core.tool.command import terminate_process_tree


@dataclass(frozen=True)
class BackgroundProcessRecord:
    pid: int
    session_id: str
    run_id: str
    work_root: str
    started_at: float


@dataclass
class _OwnedProcess:
    process: subprocess.Popen[object]
    record: BackgroundProcessRecord


class BackgroundProcessRegistry:
    """Track only subprocess handles created by this Core process.

    Keeping the ``Popen`` handle, rather than rediscovering a process by port or
    executable name, makes cleanup an ownership operation and avoids killing an
    unrelated process after PID reuse.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._owned: dict[int, _OwnedProcess] = {}

    def register(
        self,
        process: subprocess.Popen[object],
        *,
        session_id: str,
        run_id: str,
        work_root: str | Path,
    ) -> BackgroundProcessRecord:
        if process.poll() is not None:
            raise ValueError("cannot register an exited background process")
        record = BackgroundProcessRecord(
            pid=int(process.pid),
            session_id=str(session_id or ""),
            run_id=str(run_id or ""),
            work_root=str(Path(work_root).resolve()),
            started_at=time.time(),
        )
        with self._lock:
            self._prune_exited_locked()
            self._owned[record.pid] = _OwnedProcess(process=process, record=record)
        return record

    def list(self, *, session_id: str = "", run_id: str = "") -> list[BackgroundProcessRecord]:
        with self._lock:
            self._prune_exited_locked()
            return [
                owned.record
                for owned in self._owned.values()
                if (not session_id or owned.record.session_id == session_id)
                and (not run_id or owned.record.run_id == run_id)
            ]

    def cleanup_run(self, session_id: str, run_id: str) -> list[int]:
        return self._cleanup(
            lambda record: record.session_id == session_id and record.run_id == run_id
        )

    def cleanup_session(self, session_id: str, *, include_children: bool = True) -> list[int]:
        child_prefix = f"{session_id}:sub:"
        return self._cleanup(
            lambda record: record.session_id == session_id
            or (include_children and record.session_id.startswith(child_prefix))
        )

    def shutdown(self) -> list[int]:
        return self._cleanup(lambda _record: True)

    def _cleanup(self, matches: Callable[[BackgroundProcessRecord], bool]) -> list[int]:
        with self._lock:
            selected = [
                owned for owned in self._owned.values()
                if matches(owned.record)
            ]
            for owned in selected:
                self._owned.pop(owned.record.pid, None)
        terminated: list[int] = []
        for owned in selected:
            if owned.process.poll() is None:
                terminate_process_tree(owned.process)
                terminated.append(owned.record.pid)
        return terminated

    def _prune_exited_locked(self) -> None:
        exited = [pid for pid, owned in self._owned.items() if owned.process.poll() is not None]
        for pid in exited:
            self._owned.pop(pid, None)


_DEFAULT_BACKGROUND_PROCESS_REGISTRY = BackgroundProcessRegistry()


def default_background_process_registry() -> BackgroundProcessRegistry:
    return _DEFAULT_BACKGROUND_PROCESS_REGISTRY


__all__ = [
    "BackgroundProcessRecord",
    "BackgroundProcessRegistry",
    "default_background_process_registry",
]
