"""Ownership registry for background processes started by Core tools."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from lamtools_core.tool.command import terminate_process_tree

if TYPE_CHECKING:
    from lamtools_core.runtime.persistent_process_store import PersistentProcessStore


@dataclass(frozen=True)
class BackgroundProcessRecord:
    pid: int
    session_id: str
    run_id: str
    work_root: str
    started_at: float
    persistent: bool = False
    command: str = ""
    stdout_log: str = ""
    stderr_log: str = ""

    def to_archive(self) -> dict[str, object]:
        return {
            "pid": self.pid,
            "session_id": self.session_id,
            "run_id": self.run_id,
            "work_root": self.work_root,
            "started_at": self.started_at,
            "persistent": self.persistent,
            "command": self.command,
            "stdout_log": self.stdout_log,
            "stderr_log": self.stderr_log,
        }

    @classmethod
    def from_archive(cls, data: dict[str, object]) -> BackgroundProcessRecord | None:
        try:
            pid = int(data.get("pid") or 0)
            started_at = float(data.get("started_at") or 0.0)
        except (TypeError, ValueError):
            return None
        if pid <= 0:
            return None
        return cls(
            pid=pid,
            session_id=str(data.get("session_id") or ""),
            run_id=str(data.get("run_id") or ""),
            work_root=str(data.get("work_root") or ""),
            started_at=started_at,
            persistent=bool(data.get("persistent")),
            command=str(data.get("command") or ""),
            stdout_log=str(data.get("stdout_log") or ""),
            stderr_log=str(data.get("stderr_log") or ""),
        )


@dataclass(frozen=True)
class BackgroundProcessStatus:
    """A registered process plus its live observability facts.

    ``owned`` means this backend process still holds the spawn handle and can
    terminate the process tree safely. Records adopted from the persistent
    archive after a backend restart are never owned: killing by bare pid
    risks an unrelated process after pid reuse, so they are display-only.
    """

    record: BackgroundProcessRecord
    alive: bool
    owned: bool

    @property
    def can_terminate(self) -> bool:
        return self.owned and self.alive


@dataclass
class _OwnedProcess:
    process: subprocess.Popen[object]
    record: BackgroundProcessRecord


def pid_alive(pid: int) -> bool:
    """Best-effort liveness probe for a pid without a spawn handle.

    Display-only: a live result does not make the process killable, because
    the probe cannot prove the pid still belongs to the registered command.
    """
    pid = int(pid)
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return exit_code.value == STILL_ACTIVE
            return True
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


class BackgroundProcessRegistry:
    """Track only subprocess handles created by this Core process.

    Keeping the ``Popen`` handle, rather than rediscovering a process by port or
    executable name, makes cleanup an ownership operation and avoids killing an
    unrelated process after PID reuse.

    Persistent records (long-lived processes that must survive turn ends) are
    exempt from run/session cleanup and only die on app shutdown, an explicit
    kill, or deletion of their owning session. Adopted records loaded from the
    persistent archive after a restart have no handle and are display-only.
    """

    def __init__(
        self,
        *,
        store: PersistentProcessStore | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._owned: dict[int, _OwnedProcess] = {}
        self._adopted: dict[int, BackgroundProcessRecord] = {}
        self._store = store
        if store is not None:
            self._load_adopted_locked()

    def attach_store(self, store: PersistentProcessStore | None) -> None:
        """Bind the durable archive and adopt its records.

        Replacing the store resets adopted records first, so re-binding to a
        fresh archive (tests, a second app instance) never accumulates stale
        adoption state.
        """
        with self._lock:
            self._store = store
            self._adopted.clear()
            if store is not None:
                self._load_adopted_locked()

    def _load_adopted_locked(self) -> None:
        assert self._store is not None
        for data in self._store.load():
            record = BackgroundProcessRecord.from_archive(data)
            if record is None or not record.persistent:
                continue
            if record.pid in self._owned or record.pid in self._adopted:
                continue
            self._adopted[record.pid] = record

    def register(
        self,
        process: subprocess.Popen[object],
        *,
        session_id: str,
        run_id: str,
        work_root: str | Path,
        persistent: bool = False,
        command: str = "",
        stdout_log: str = "",
        stderr_log: str = "",
    ) -> BackgroundProcessRecord:
        if process.poll() is not None:
            raise ValueError("cannot register an exited background process")
        record = BackgroundProcessRecord(
            pid=int(process.pid),
            session_id=str(session_id or ""),
            run_id=str(run_id or ""),
            work_root=str(Path(work_root).resolve()),
            started_at=time.time(),
            persistent=bool(persistent),
            command=str(command or ""),
            stdout_log=str(stdout_log or ""),
            stderr_log=str(stderr_log or ""),
        )
        with self._lock:
            self._prune_exited_locked()
            self._adopted.pop(record.pid, None)
            self._owned[record.pid] = _OwnedProcess(process=process, record=record)
            if record.persistent:
                self._sync_store_locked()
        return record

    def list(self, *, session_id: str = "", run_id: str = "") -> list[BackgroundProcessRecord]:
        with self._lock:
            self._prune_exited_locked()
            records: list[BackgroundProcessRecord] = [
                owned.record for owned in self._owned.values()
                if self._matches_scope(owned.record, session_id, run_id)
            ]
            records.extend(
                record for record in self._adopted.values()
                if self._matches_scope(record, session_id, run_id)
            )
            records.sort(key=lambda item: (item.started_at, item.pid))
            return records

    def list_status(self, *, session_id: str = "", run_id: str = "") -> list[BackgroundProcessStatus]:
        with self._lock:
            self._prune_exited_locked()
            statuses: list[BackgroundProcessStatus] = []
            for owned in self._owned.values():
                if not self._matches_scope(owned.record, session_id, run_id):
                    continue
                statuses.append(BackgroundProcessStatus(
                    record=owned.record,
                    alive=owned.process.poll() is None,
                    owned=True,
                ))
            for record in self._adopted.values():
                if not self._matches_scope(record, session_id, run_id):
                    continue
                statuses.append(BackgroundProcessStatus(record=record, alive=pid_alive(record.pid), owned=False))
            statuses.sort(key=lambda item: (item.record.started_at, item.record.pid))
            return statuses

    def kill(self, session_id: str, pid: int) -> str:
        """Terminate a registered process owned by this backend.

        Returns ``"terminated"``, ``"not_found"`` (no such record in the
        session scope), or ``"not_owned"`` (record exists but its handle was
        lost, e.g. after a backend restart — termination is refused).
        """
        pid = int(pid)
        with self._lock:
            self._prune_exited_locked()
            owned = self._owned.get(pid)
            if owned is not None and self._matches_scope(owned.record, session_id, ""):
                self._owned.pop(pid, None)
                was_persistent = owned.record.persistent
            else:
                owned = None
                was_persistent = False
            if owned is not None:
                if owned.process.poll() is None:
                    terminate_process_tree(owned.process)
                if was_persistent:
                    self._sync_store_locked()
                return "terminated"
            if pid in self._adopted and self._matches_scope(self._adopted[pid], session_id, ""):
                return "not_owned"
        return "not_found"

    def forget(self, session_id: str, pid: int) -> bool:
        """Drop a record without killing anything.

        Owned live processes cannot be forgotten — terminate them first.
        """
        pid = int(pid)
        with self._lock:
            self._prune_exited_locked()
            adopted = self._adopted.get(pid)
            if adopted is not None and self._matches_scope(adopted, session_id, ""):
                self._adopted.pop(pid, None)
                self._sync_store_locked()
                return True
            owned = self._owned.get(pid)
            if owned is not None and self._matches_scope(owned.record, session_id, ""):
                if owned.process.poll() is None:
                    return False
                self._owned.pop(pid, None)
                if owned.record.persistent:
                    self._sync_store_locked()
                return True
        return False

    def cleanup_run(self, session_id: str, run_id: str) -> list[int]:
        # Persistent processes are exempt: stopping or losing the run that
        # started them is exactly what they are designed to survive. Once the
        # spawn call registers them, a cancel racing the start must not undo
        # the registration either.
        return self._cleanup(
            lambda record: record.session_id == session_id and record.run_id == run_id,
            include_persistent=False,
        )

    def cleanup_session(self, session_id: str, *, include_children: bool = True, force: bool = False) -> list[int]:
        child_prefix = f"{session_id}:sub:"
        return self._cleanup(
            lambda record: record.session_id == session_id
            or (include_children and record.session_id.startswith(child_prefix)),
            include_persistent=force,
            include_adopted=force,
        )

    def shutdown(self) -> list[int]:
        # Adopted records have no handle and cannot be terminated here; they
        # stay archived so the next start can still account for them.
        return self._cleanup(lambda _record: True, include_persistent=True, include_adopted=False)

    def _cleanup(
        self,
        matches: Callable[[BackgroundProcessRecord], bool],
        *,
        include_persistent: bool,
        include_adopted: bool = False,
    ) -> list[int]:
        with self._lock:
            selected = [
                owned for owned in self._owned.values()
                if matches(owned.record)
                and (include_persistent or not owned.record.persistent)
            ]
            for owned in selected:
                self._owned.pop(owned.record.pid, None)
            dropped_adopted: list[int] = []
            if include_adopted:
                dropped_adopted = [
                    pid for pid, record in self._adopted.items()
                    if matches(record)
                ]
                for pid in dropped_adopted:
                    self._adopted.pop(pid, None)
            store_dirty = bool(selected and any(owned.record.persistent for owned in selected)) or bool(dropped_adopted)
        terminated: list[int] = []
        for owned in selected:
            if owned.process.poll() is None:
                terminate_process_tree(owned.process)
                terminated.append(owned.record.pid)
        if store_dirty:
            with self._lock:
                self._sync_store_locked()
        return terminated

    def _prune_exited_locked(self) -> None:
        # Persistent records stay listed after a natural exit so the session
        # (and the sidebar) can show "exited" until the record is removed.
        exited = [
            pid for pid, owned in self._owned.items()
            if owned.process.poll() is not None and not owned.record.persistent
        ]
        for pid in exited:
            self._owned.pop(pid, None)

    @staticmethod
    def _matches_scope(record: BackgroundProcessRecord, session_id: str, run_id: str) -> bool:
        if run_id and record.run_id != run_id:
            return False
        if not session_id:
            return True
        return record.session_id == session_id or record.session_id.startswith(f"{session_id}:sub:")

    def _sync_store_locked(self) -> None:
        if self._store is None:
            return
        records = [owned.record.to_archive() for owned in self._owned.values() if owned.record.persistent]
        records.extend(record.to_archive() for record in self._adopted.values())
        self._store.save(records)


def persistent_process_prompt(registry: BackgroundProcessRegistry | None, session_id: str) -> str:
    """Context block telling the agent which long-lived processes are running.

    Empty when the session has none, so normal sessions pay no token cost.
    """
    if registry is None or not str(session_id or "").strip():
        return ""
    running = [status for status in registry.list_status(session_id=str(session_id).strip()) if status.alive]
    if not running:
        return ""
    lines = [
        "[Persistent Background Processes]",
        "The processes below were started in this session and keep running after turns end. "
        "Check status with the list_processes tool; terminate with kill_process when no longer needed.",
    ]
    for status in running:
        record = status.record
        command = " ".join((record.command or "").split())
        if not command:
            command = "<unknown command>"
        if len(command) > 160:
            command = command[:157] + "..."
        lines.append(f"- pid {record.pid} | running | {command}")
    return "\n".join(lines)


def status_to_dict(status: BackgroundProcessStatus) -> dict[str, object]:
    record = status.record
    return {
        "pid": record.pid,
        "session_id": record.session_id,
        "run_id": record.run_id,
        "work_root": record.work_root,
        "started_at": record.started_at,
        "persistent": record.persistent,
        "command": record.command,
        "stdout_log": record.stdout_log,
        "stderr_log": record.stderr_log,
        "alive": status.alive,
        "owned": status.owned,
        "can_terminate": status.can_terminate,
    }


_DEFAULT_BACKGROUND_PROCESS_REGISTRY = BackgroundProcessRegistry()


def default_background_process_registry() -> BackgroundProcessRegistry:
    return _DEFAULT_BACKGROUND_PROCESS_REGISTRY


__all__ = [
    "BackgroundProcessRecord",
    "BackgroundProcessRegistry",
    "BackgroundProcessStatus",
    "default_background_process_registry",
    "persistent_process_prompt",
    "pid_alive",
    "status_to_dict",
]
