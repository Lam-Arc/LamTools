"""Managed observer scripts that emit durable Arrange signals over JSON Lines."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from .arrange import ArrangeJob, ArrangeManager, ArrangeStore


OBSERVER_PROTOCOL = "lamtools.signal.v1"
_ACTIVE_JOB_STATUSES = frozenset({"scheduled", "waiting", "running"})


def prepare_observer(observer: dict[str, Any], *, work_root: str | Path) -> dict[str, Any]:
    """Validate one Python observer and bind approval to its current file content."""
    if not isinstance(observer, dict):
        raise ValueError("observer must be an object")
    if not str(work_root or "").strip():
        raise ValueError("observer work_root is required")
    root = Path(work_root).resolve()
    entry_value = str(observer.get("entry") or "").strip()
    if not entry_value:
        raise ValueError("observer entry is required")
    entry = Path(entry_value)
    resolved = (root / entry).resolve() if not entry.is_absolute() else entry.resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("observer entry must stay inside work_root") from exc
    if not resolved.is_file():
        raise ValueError(f"observer entry does not exist: {relative.as_posix()}")
    if resolved.suffix.lower() != ".py":
        raise ValueError("observer entry must be a Python script")
    protocol = str(observer.get("protocol") or OBSERVER_PROTOCOL).strip()
    if protocol != OBSERVER_PROTOCOL:
        raise ValueError(f"unsupported observer protocol: {protocol}")
    restart = str(observer.get("restart") or "always").strip().lower()
    if restart not in {"always", "on-failure"}:
        raise ValueError("observer restart must be always or on-failure")
    return {
        "entry": relative.as_posix(),
        "work_root": str(root),
        "protocol": OBSERVER_PROTOCOL,
        "runtime": "python",
        "restart": restart,
        "approved_sha256": _file_sha256(resolved),
    }


@dataclass
class _ObserverProcess:
    job: ArrangeJob
    process: asyncio.subprocess.Process
    task: asyncio.Task[None]
    expected_stop: bool = False


class ObserverSupervisor:
    """Reconciles persisted Arrange observers with managed child processes."""

    def __init__(
        self,
        store: ArrangeStore,
        *,
        data_dir: str | Path,
        wake_runner: Callable[[], Any] | None = None,
        poll_interval: float = 2.0,
        max_line_bytes: int = 1_000_000,
    ) -> None:
        self.store = store
        self.manager = ArrangeManager(store)
        self.data_dir = Path(data_dir).resolve()
        self.wake_runner = wake_runner
        self.poll_interval = max(0.05, poll_interval)
        self.max_line_bytes = max(1024, max_line_bytes)
        self._processes: dict[str, _ObserverProcess] = {}
        self._states: dict[str, dict[str, Any]] = {}
        self._next_start: dict[str, float] = {}
        self._wake = asyncio.Event()
        self._stopping = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._stopping.clear()
        await self.reconcile_once()
        self._task = asyncio.create_task(self._run(), name="arrange-observer-supervisor")

    async def stop(self) -> None:
        self._stopping.set()
        self._wake.set()
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await asyncio.gather(
            *(self._stop_process(job_id) for job_id in list(self._processes)),
            return_exceptions=True,
        )

    def wake(self) -> None:
        self._wake.set()

    def status(self, job_id: str) -> dict[str, Any]:
        return deepcopy(self._states.get(str(job_id or ""), {"status": "disabled"}))

    async def reconcile_once(self) -> None:
        jobs = await self.store.list()
        desired = {
            job.id: job
            for job in jobs
            if job.observer and job.status in _ACTIVE_JOB_STATUSES
        }
        for job_id in list(self._processes):
            current = desired.get(job_id)
            running = self._processes[job_id]
            if current is None or current.observer != running.job.observer:
                await self._stop_process(job_id)
                if current is None:
                    self._next_start.pop(job_id, None)
        loop_time = asyncio.get_running_loop().time()
        for job_id, job in desired.items():
            if job_id in self._processes or loop_time < self._next_start.get(job_id, 0):
                continue
            await self._start_process(job)

    async def _run(self) -> None:
        while not self._stopping.is_set():
            self._wake.clear()
            await self.reconcile_once()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.poll_interval)
            except TimeoutError:
                pass

    async def _start_process(self, job: ArrangeJob) -> None:
        try:
            entry, work_root = _resolve_approved_entry(job.observer)
        except ValueError as exc:
            self._set_state(job.id, status="approval_required", last_error=str(exc))
            return
        state_dir = self.data_dir / "observers" / job.id
        state_dir.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env.update({
            "LAMTOOLS_OBSERVER_ID": job.id,
            "LAMTOOLS_OBSERVER_JOB_ID": job.id,
            "LAMTOOLS_OBSERVER_WORK_ROOT": str(work_root),
            "LAMTOOLS_OBSERVER_STATE_DIR": str(state_dir),
            "LAMTOOLS_OBSERVER_EVENT_TYPE": str(job.trigger.get("event_type") or ""),
            "PYTHONUTF8": "1",
            "PYTHONUNBUFFERED": "1",
        })
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-u",
                str(entry),
                cwd=str(work_root),
                env=env,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=creationflags,
                limit=self.max_line_bytes + 1,
            )
        except OSError as exc:
            self._schedule_restart(job, str(exc))
            return
        task = asyncio.create_task(
            self._monitor(job, process),
            name=f"arrange-observer:{job.id}",
        )
        self._processes[job.id] = _ObserverProcess(job=job, process=process, task=task)
        previous_restarts = int(self._states.get(job.id, {}).get("restart_count") or 0)
        self._set_state(
            job.id,
            status="running",
            pid=process.pid,
            restart_count=previous_restarts,
            last_started_at=_utcnow_iso(),
            last_error="",
        )

    async def _monitor(self, job: ArrangeJob, process: asyncio.subprocess.Process) -> None:
        stdout_task = asyncio.create_task(self._read_stdout(job, process))
        stderr_task = asyncio.create_task(self._read_stderr(job, process))
        return_code = await process.wait()
        await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
        active = self._processes.get(job.id)
        expected = active.expected_stop if active is not None else self._stopping.is_set()
        if active is not None and active.process is process:
            self._processes.pop(job.id, None)
        if expected or self._stopping.is_set():
            self._set_state(job.id, status="stopped", pid=None, last_stopped_at=_utcnow_iso())
            return
        restart_policy = str(job.observer.get("restart") or "always")
        if restart_policy == "on-failure" and return_code == 0:
            self._set_state(job.id, status="stopped", pid=None, last_stopped_at=_utcnow_iso())
            return
        self._schedule_restart(job, f"observer exited with code {return_code}")
        self.wake()

    async def _read_stdout(self, job: ArrangeJob, process: asyncio.subprocess.Process) -> None:
        reader = process.stdout
        if reader is None:
            return
        while True:
            line = await reader.readline()
            if not line:
                return
            if len(line) > self.max_line_bytes:
                self._set_state(job.id, last_error="observer signal line is too large")
                continue
            try:
                payload = json.loads(line.decode("utf-8"))
                signal = payload.get("signal") if payload.get("type") == "signal" else payload
                if not isinstance(signal, dict):
                    raise ValueError("observer output must be a JSON object")
                if str(signal.get("protocol") or "") != OBSERVER_PROTOCOL:
                    raise ValueError("observer output uses an unsupported protocol")
                expected_type = str(job.trigger.get("event_type") or "")
                if str(signal.get("event_type") or "") != expected_type:
                    raise ValueError(f"observer event_type must be {expected_type}")
                original_event_id = str(signal.get("event_id") or "").strip()
                if not original_event_id:
                    raise ValueError("observer event_id is required")
                metadata = dict(signal.get("metadata") or {})
                metadata.update({
                    "observer_id": job.id,
                    "source_event_id": original_event_id,
                })
                signal = {
                    **signal,
                    "event_id": _bound_event_id(job.id, original_event_id),
                    "source": str(signal.get("source") or f"observer:{job.id}"),
                    "metadata": metadata,
                }
                emission = await self.manager.emit_signal(signal, job_id=job.id)
                self._set_state(
                    job.id,
                    last_signal_at=_utcnow_iso(),
                    last_event_id=original_event_id,
                    last_error="",
                )
                if emission.occurrences and self.wake_runner is not None:
                    result = self.wake_runner()
                    if hasattr(result, "__await__"):
                        await result
            except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
                self._set_state(job.id, last_error=str(exc))

    async def _read_stderr(self, job: ArrangeJob, process: asyncio.subprocess.Process) -> None:
        reader = process.stderr
        if reader is None:
            return
        while True:
            line = await reader.readline()
            if not line:
                return
            message = line.decode("utf-8", errors="replace").strip()
            if message:
                self._set_state(job.id, last_stderr=message[-2000:])

    async def _stop_process(self, job_id: str) -> None:
        active = self._processes.get(job_id)
        if active is None:
            return
        active.expected_stop = True
        process = active.process
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=3)
            except TimeoutError:
                process.kill()
                await process.wait()
        await asyncio.gather(active.task, return_exceptions=True)
        if self._processes.get(job_id) is active:
            self._processes.pop(job_id, None)

    def _schedule_restart(self, job: ArrangeJob, error: str) -> None:
        state = self._states.get(job.id, {})
        restart_count = int(state.get("restart_count") or 0) + 1
        delay = min(60.0, 2 ** min(restart_count - 1, 6))
        self._next_start[job.id] = asyncio.get_running_loop().time() + delay
        self._set_state(
            job.id,
            status="backoff",
            pid=None,
            restart_count=restart_count,
            retry_in_seconds=delay,
            last_error=error,
            last_stopped_at=_utcnow_iso(),
        )

    def _set_state(self, job_id: str, **changes: Any) -> None:
        self._states[job_id] = {**self._states.get(job_id, {}), **changes}


def _resolve_approved_entry(observer: dict[str, Any]) -> tuple[Path, Path]:
    work_root = Path(str(observer.get("work_root") or "")).resolve()
    entry = (work_root / str(observer.get("entry") or "")).resolve()
    try:
        entry.relative_to(work_root)
    except ValueError as exc:
        raise ValueError("observer entry escaped work_root") from exc
    if not entry.is_file():
        raise ValueError("observer entry is missing")
    approved = str(observer.get("approved_sha256") or "")
    if not approved or _file_sha256(entry) != approved:
        raise ValueError("observer script changed after approval")
    return entry, work_root


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bound_event_id(job_id: str, event_id: str) -> str:
    digest = hashlib.sha256(f"{job_id}:{event_id}".encode("utf-8")).hexdigest()[:32]
    return f"observer:{digest}"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = ["OBSERVER_PROTOCOL", "ObserverSupervisor", "prepare_observer"]
