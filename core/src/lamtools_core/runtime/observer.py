"""Managed observer scripts that emit durable Arrange signals over JSON Lines.

user:“Observer 可靠事件投递、ACK、去重与重放；Observer 正常退出与失败重启策略”
+(v1 协议原样保留但只保证尽力而为；v2 在宿主事务提交之后回 ACK，观察器只有收到
ACK 才能推进自己的游标，从而做到“重复投递可以，丢事件不可以”)。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Protocol, runtime_checkable

from lamtools_core.config.network import subprocess_env

from .arrange import ArrangeJob, ArrangeManager, ArrangeStore

_logger = logging.getLogger(__name__)

OBSERVER_PROTOCOL = "lamtools.signal.v1"
OBSERVER_PROTOCOL_V2 = "lamtools.signal.v2"
SUPPORTED_PROTOCOLS = frozenset({OBSERVER_PROTOCOL, OBSERVER_PROTOCOL_V2})
_ACTIVE_JOB_STATUSES = frozenset({"scheduled", "waiting", "running"})

# 生命周期状态。正常退出是终态：只有人显式 rearm 才会重新拉起。
DESIRED_ACTIVE = "active"
DESIRED_STOPPED_SUCCESSFULLY = "stopped_successfully"
DESIRED_SUSPENDED = "suspended"


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
    if protocol not in SUPPORTED_PROTOCOLS:
        raise ValueError(f"unsupported observer protocol: {protocol}")
    restart = str(observer.get("restart") or "always").strip().lower()
    if restart not in {"always", "on-failure"}:
        raise ValueError("observer restart must be always or on-failure")
    return {
        "entry": relative.as_posix(),
        "work_root": str(root),
        "protocol": protocol,
        "runtime": "python",
        "restart": restart,
        "approved_sha256": _file_sha256(resolved),
    }


@runtime_checkable
class ObserverLifecycleStore(Protocol):
    """持久化的观察器生命周期，保证“正常退出”跨进程重启仍然有效。"""

    async def get(self, observer_id: str) -> dict[str, Any] | None: ...

    async def upsert(self, observer_id: str, **fields: Any) -> dict[str, Any]: ...


class InMemoryObserverLifecycleStore:
    def __init__(self) -> None:
        self._items: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def get(self, observer_id: str) -> dict[str, Any] | None:
        async with self._lock:
            item = self._items.get(str(observer_id or ""))
            return deepcopy(item) if item is not None else None

    async def upsert(self, observer_id: str, **fields: Any) -> dict[str, Any]:
        async with self._lock:
            key = str(observer_id or "")
            current = dict(self._items.get(key) or {"observer_id": key})
            current.update(deepcopy(fields))
            current["updated_at"] = _utcnow_iso()
            self._items[key] = current
            return deepcopy(current)


@dataclass
class _ObserverProcess:
    job: ArrangeJob
    process: asyncio.subprocess.Process
    task: asyncio.Task[None]
    expected_stop: bool = False
    acks_sent: int = 0
    acks_dropped: int = 0


@dataclass
class _RuntimeState:
    status: str = "disabled"
    pid: int | None = None
    restart_count: int = 0
    last_error: str = ""
    last_stderr: str = ""
    last_signal_at: str = ""
    last_event_id: str = ""
    last_started_at: str = ""
    last_stopped_at: str = ""
    last_exit_code: int | None = None
    last_exit_reason: str = ""
    retry_in_seconds: float = 0.0
    unsupported_lines: int = 0
    oversized_lines: int = 0
    acks_sent: int = 0
    acks_dropped: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


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
        lifecycle_store: ObserverLifecycleStore | None = None,
        max_backoff: float = 60.0,
    ) -> None:
        self.store = store
        self.manager = ArrangeManager(store)
        self.data_dir = Path(data_dir).resolve()
        self.wake_runner = wake_runner
        self.poll_interval = max(0.05, poll_interval)
        self.max_line_bytes = max(1024, max_line_bytes)
        self.lifecycle_store = lifecycle_store or InMemoryObserverLifecycleStore()
        self.max_backoff = max(self.poll_interval, max_backoff)
        self._processes: dict[str, _ObserverProcess] = {}
        self._states: dict[str, _RuntimeState] = {}
        self._next_start: dict[str, float] = {}
        self._wake = asyncio.Event()
        self._stopping = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._consecutive_failures = 0
        self._last_error = ""
        self._last_error_at: str = ""

    # ------------------------------------------------------------------ 生命周期
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
        state = self._states.get(str(job_id or ""))
        if state is None:
            return {"status": "disabled"}
        # 只回已经真实发生过的字段：空串/0 不出现，
        # 这样 `status(...).get("last_signal_at") is not None` 仍然是
        # “收到过信号”的判断，不会因为默认值提前为真。
        payload: dict[str, Any] = {"status": state.status}
        for key, value in state.__dict__.items():
            if key in {"status", "extra"}:
                continue
            if value in (None, "") or value == 0:
                continue
            payload[key] = deepcopy(value)
        for key, value in state.extra.items():
            if value in (None, ""):
                continue
            payload[key] = deepcopy(value)
        return payload

    def health(self) -> dict[str, Any]:
        task = self._task
        backoff = sum(
            1
            for state in self._states.values()
            if state.status == "backoff"
        )
        return {
            "alive": bool(task is not None and not task.done() and not self._stopping.is_set()),
            "running": len(self._processes),
            "backoff": backoff,
            "observers": len(self._states),
            "consecutive_failures": self._consecutive_failures,
            "last_error": self._last_error,
            "last_error_at": self._last_error_at,
        }

    async def rearm(self, job_id: str) -> dict[str, Any]:
        """把“正常退出”的终态清掉，允许下一次 reconcile 重新拉起。"""
        key = str(job_id or "").strip()
        if not key:
            raise ValueError("job_id is required")
        await self.lifecycle_store.upsert(
            key,
            desired_state=DESIRED_ACTIVE,
            last_exit_reason="",
            last_exit_code=None,
            next_retry_at="",
            restart_count=0,
        )
        self._next_start.pop(key, None)
        state = self._states.setdefault(key, _RuntimeState())
        state.status = "rearmed"
        state.last_exit_reason = ""
        state.last_exit_code = None
        state.restart_count = 0
        self.wake()
        return self.status(key)

    # ------------------------------------------------------------------ 调度
    async def reconcile_once(self) -> None:
        jobs = await self.store.list()
        desired = {
            job.id: job for job in jobs if job.observer and job.status in _ACTIVE_JOB_STATUSES
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
            lifecycle = await self.lifecycle_store.get(job_id) or {}
            if str(lifecycle.get("desired_state") or DESIRED_ACTIVE) != DESIRED_ACTIVE:
                # 终态：正常退出过，或被人为挂起。跨进程重启也不许自己回来。
                self._set_state(
                    job_id,
                    status="stopped"
                    if lifecycle.get("desired_state") == DESIRED_STOPPED_SUCCESSFULLY
                    else "suspended",
                    last_exit_reason=str(lifecycle.get("last_exit_reason") or ""),
                )
                continue
            await self._start_process(job)

    async def _run(self) -> None:
        while not self._stopping.is_set():
            self._wake.clear()
            try:
                await self.reconcile_once()
                self._consecutive_failures = 0
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — 循环级自愈
                # user:“后台调度器异常自愈及健康检查”+(一次数据库抖动不能让
                # 整个观察器监管永久停摆；记录、退避、继续)。
                self._consecutive_failures += 1
                self._last_error = f"{type(exc).__name__}: {exc}"
                self._last_error_at = _utcnow_iso()
                delay = min(
                    self.max_backoff,
                    self.poll_interval * float(2 ** min(self._consecutive_failures - 1, 5)),
                )
                _logger.warning(
                    "observer reconcile failed (%s in a row), retrying in %.2fs: %s",
                    self._consecutive_failures,
                    delay,
                    exc,
                )
                try:
                    await asyncio.wait_for(self._stopping.wait(), timeout=delay)
                except TimeoutError:
                    pass
                continue
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.poll_interval)
            except TimeoutError:
                pass

    # ------------------------------------------------------------------ 进程
    async def _start_process(self, job: ArrangeJob) -> None:
        try:
            entry, work_root = _resolve_approved_entry(job.observer)
        except ValueError as exc:
            self._set_state(job.id, status="approval_required", last_error=str(exc))
            return
        state_dir = self.data_dir / "observers" / job.id
        state_dir.mkdir(parents=True, exist_ok=True)
        env = subprocess_env()
        env.update({
            "LAMTOOLS_OBSERVER_ID": job.id,
            "LAMTOOLS_OBSERVER_JOB_ID": job.id,
            "LAMTOOLS_OBSERVER_WORK_ROOT": str(work_root),
            "LAMTOOLS_OBSERVER_STATE_DIR": str(state_dir),
            "LAMTOOLS_OBSERVER_EVENT_TYPE": str(job.trigger.get("event_type") or ""),
            "LAMTOOLS_OBSERVER_PROTOCOL": str(job.observer.get("protocol") or OBSERVER_PROTOCOL),
            "PYTHONUTF8": "1",
            "PYTHONUNBUFFERED": "1",
        })
        creationflags = 0
        if os.name == "nt":
            # 独立进程组：停止时要能连带收掉观察器自己起的孙进程，
            # 否则“关闭后无残留子进程”只能靠运气。
            creationflags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        try:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-u",
                str(entry),
                cwd=str(work_root),
                env=env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=creationflags,
                start_new_session=os.name != "nt",
            )
        except OSError as exc:
            await self._schedule_restart(job, str(exc))
            return
        task = asyncio.create_task(
            self._monitor(job, process),
            name=f"arrange-observer:{job.id}",
        )
        previous = self._states.get(job.id) or _RuntimeState()
        self._processes[job.id] = _ObserverProcess(job=job, process=process, task=task)
        self._set_state(
            job.id,
            status="running",
            pid=process.pid,
            restart_count=previous.restart_count,
            last_started_at=_utcnow_iso(),
            last_error="",
        )
        await self.lifecycle_store.upsert(
            job.id,
            desired_state=DESIRED_ACTIVE,
            restart_policy=str(job.observer.get("restart") or "always"),
            last_started_at=_utcnow_iso(),
            last_pid=process.pid,
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
            # user:“Observer 正常退出与失败重启策略”+(on-failure 的语义是
            # 只在失败时重启；正常退出是终态，必须写进持久层，否则下一轮
            # reconcile 会把它当 desired 又拉起来，形成热循环)。
            self._set_state(
                job.id,
                status="stopped",
                pid=None,
                last_stopped_at=_utcnow_iso(),
                last_exit_code=0,
                last_exit_reason="success",
                restart_count=0,
            )
            await self.lifecycle_store.upsert(
                job.id,
                desired_state=DESIRED_STOPPED_SUCCESSFULLY,
                last_exit_code=0,
                last_exit_reason="success",
                last_stopped_at=_utcnow_iso(),
                next_retry_at="",
            )
            return
        await self._schedule_restart(job, f"observer exited with code {return_code}", return_code)
        self.wake()

    # ------------------------------------------------------------------ 读流
    async def _iter_bounded_lines(
        self, reader: asyncio.StreamReader, job_id: str
    ) -> AsyncIterator[bytes]:
        """有界、可恢复的 JSONL 读取。

        直接用 ``readline(limit)`` 会让超长行抛 ValueError 并杀死整个读取任务，
        之后所有事件都读不到；这里改成按块读、自行切行、超限丢弃并计数。
        """
        buffer = bytearray()
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                if buffer:
                    yield bytes(buffer)
                return
            buffer.extend(chunk)
            while True:
                index = buffer.find(b"\n")
                if index < 0:
                    break
                line = bytes(buffer[:index])
                del buffer[: index + 1]
                if len(line) > self.max_line_bytes:
                    state = self._states.get(job_id) or _RuntimeState()
                    self._set_state(
                        job_id,
                        oversized_lines=state.oversized_lines + 1,
                        last_error="observer signal line is too large",
                    )
                    continue
                yield line
            if len(buffer) > self.max_line_bytes:
                state = self._states.get(job_id) or _RuntimeState()
                self._set_state(
                    job_id,
                    oversized_lines=state.oversized_lines + 1,
                    last_error="observer signal line is too large",
                )
                buffer.clear()

    async def _read_stdout(self, job: ArrangeJob, process: asyncio.subprocess.Process) -> None:
        reader = process.stdout
        if reader is None:
            return
        async for line in self._iter_bounded_lines(reader, job.id):
            stripped = line.strip()
            if not stripped:
                continue
            protocol = ""
            try:
                payload = json.loads(stripped.decode("utf-8", errors="replace"))
                signal = payload.get("signal") if payload.get("type") == "signal" else payload
                if not isinstance(signal, dict):
                    raise ValueError("observer output must be a JSON object")
                protocol = str(signal.get("protocol") or "")
                if protocol not in SUPPORTED_PROTOCOLS:
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
                # 有界重试：瞬时写库失败不该让一条已经离开观察器的事件消失。
                # 重试次数固定、间隔固定，不做无限重试；耗尽后记录并让 v2
                # 观察器凭缺失的 ACK 重发（数据库按 event_id 去重）。
                emission = await self._emit_with_retry(job, signal)
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
                if protocol == OBSERVER_PROTOCOL_V2:
                    # 只有事务提交成功才回 ACK；观察器据此推进自己的游标。
                    await self._send_ack(job, original_event_id)
            except Exception as exc:  # noqa: BLE001 — 单行处理失败不能杀死读取循环
                _logger.warning(
                    "arrange observer read failed for %s", job.id, exc_info=True
                )
                state = self._states.get(job.id) or _RuntimeState()
                self._set_state(
                    job.id,
                    last_error=str(exc),
                    unsupported_lines=state.unsupported_lines + 1,
                )

    async def _emit_with_retry(self, job: ArrangeJob, signal: dict[str, Any]) -> Any:
        delays = (0.05, 0.15, 0.35)
        last_error: BaseException | None = None
        for attempt in range(len(delays) + 1):
            try:
                return await self.manager.emit_signal(signal, job_id=job.id)
            except Exception as exc:  # noqa: BLE001 — 边界重试，次数固定
                last_error = exc
                if attempt >= len(delays):
                    break
                await asyncio.sleep(delays[attempt])
        assert last_error is not None
        raise last_error

    async def _send_ack(self, job: ArrangeJob, event_id: str) -> None:
        active = self._processes.get(job.id)
        stdin = active.process.stdin if active is not None else None
        if stdin is None:
            self._bump_ack(job.id, sent=False)
            return
        frame = json.dumps(
            {
                "type": "ack",
                "protocol": OBSERVER_PROTOCOL_V2,
                "event_id": event_id,
                "observer_id": job.id,
            },
            ensure_ascii=False,
        )
        try:
            stdin.write((frame + "\n").encode("utf-8"))
            # 观察器若不读 stdin，管道会写满；超时就放弃这条 ACK 并计数。
            # 放弃是安全的：观察器会重发同一 ID，数据库按 event_id 去重。
            await asyncio.wait_for(stdin.drain(), timeout=1.0)
        except (TimeoutError, ConnectionResetError, BrokenPipeError, RuntimeError) as exc:
            _logger.warning("observer ack failed for %s: %s", job.id, exc)
            self._bump_ack(job.id, sent=False)
            return
        self._bump_ack(job.id, sent=True)

    def _bump_ack(self, job_id: str, *, sent: bool) -> None:
        state = self._states.get(job_id) or _RuntimeState()
        if sent:
            self._set_state(job_id, acks_sent=state.acks_sent + 1)
        else:
            self._set_state(job_id, acks_dropped=state.acks_dropped + 1)

    async def _read_stderr(self, job: ArrangeJob, process: asyncio.subprocess.Process) -> None:
        reader = process.stderr
        if reader is None:
            return
        async for line in self._iter_bounded_lines(reader, job.id):
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
            _terminate_tree(process)
            try:
                await asyncio.wait_for(process.wait(), timeout=3)
            except TimeoutError:
                process.kill()
                await process.wait()
        await asyncio.gather(active.task, return_exceptions=True)
        if self._processes.get(job_id) is active:
            self._processes.pop(job_id, None)

    async def _schedule_restart(
        self, job: ArrangeJob, error: str, exit_code: int | None = None
    ) -> None:
        state = self._states.get(job.id) or _RuntimeState()
        restart_count = state.restart_count + 1
        delay = min(self.max_backoff, float(2 ** min(restart_count - 1, 6)))
        self._next_start[job.id] = asyncio.get_running_loop().time() + delay
        self._set_state(
            job.id,
            status="backoff",
            pid=None,
            restart_count=restart_count,
            retry_in_seconds=delay,
            last_error=error,
            last_stopped_at=_utcnow_iso(),
            last_exit_code=exit_code,
            last_exit_reason="failure",
        )
        await self.lifecycle_store.upsert(
            job.id,
            desired_state=DESIRED_ACTIVE,
            restart_policy=str(job.observer.get("restart") or "always"),
            last_exit_code=exit_code,
            last_exit_reason="failure",
            restart_count=restart_count,
            next_retry_at=_utcnow_iso(),
            last_stopped_at=_utcnow_iso(),
        )

    def _set_state(self, job_id: str, **changes: Any) -> None:
        state = self._states.setdefault(job_id, _RuntimeState())
        for key, value in changes.items():
            if hasattr(state, key):
                setattr(state, key, value)
            else:
                state.extra[key] = value


def _terminate_tree(process: asyncio.subprocess.Process) -> None:
    """终止观察器及其子进程。

    Windows 上 terminate() 只杀直接子进程；用 taskkill /T 才能连带进程树。
    POSIX 上进程以独立 session 启动，用 killpg 收整组。
    """
    pid = process.pid
    if pid is None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                timeout=5,
                check=False,
            )
            return
        except (OSError, subprocess.TimeoutExpired):
            _logger.warning("taskkill failed for observer pid %s", pid, exc_info=True)
    else:
        try:
            os.killpg(os.getpgid(pid), 15)
            return
        except OSError:
            _logger.warning("killpg failed for observer pid %s", pid, exc_info=True)
    try:
        process.terminate()
    except ProcessLookupError:
        pass


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


__all__ = [
    "DESIRED_ACTIVE",
    "DESIRED_STOPPED_SUCCESSFULLY",
    "DESIRED_SUSPENDED",
    "InMemoryObserverLifecycleStore",
    "OBSERVER_PROTOCOL",
    "OBSERVER_PROTOCOL_V2",
    "ObserverLifecycleStore",
    "ObserverSupervisor",
    "prepare_observer",
]
