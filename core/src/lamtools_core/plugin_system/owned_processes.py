"""user:“继续，把 2 阶段都做完”+(原生进程由插件启动代拥有，真实 Windows Job 回收后才报告范围已退出)。"""
from __future__ import annotations

import asyncio
import math
import os
import subprocess
import threading
import time
from dataclasses import dataclass

from lamtools_core.tool.command import (
    _windows_command_creationflags, _windows_job_assign, _windows_job_active_processes,
    _windows_job_release, terminate_process_tree,
)
from .process_access import ProcessAccessError


@dataclass(frozen=True)
class ProcessOutcome:
    exit_code: int | None
    status: str
    quiescent: bool
    error_code: str = ""


@dataclass(frozen=True)
class ProcessOutput:
    stdout: bytes
    stderr: bytes
    stdout_after: int
    stderr_after: int
    stdout_lost: bool
    stderr_lost: bool
    complete: bool


async def _join(task):
    """Cleanup remains owned through repeated cancellation of its caller."""
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
    return task.result()


class OwnedProcess:
    def __init__(self, scope, argv, cwd, env, timeout, limit, *, stdin_enabled=False):
        self._scope, self._argv, self._cwd, self._env = scope, argv, cwd, env
        # user:“给我把 2 阶段做完，前端除外”+(交互输入仍归同一Windows Job，写入期限到达先回收进程再返回)。
        self._stdin_enabled, self._stdin_lock = stdin_enabled, asyncio.Lock()
        self._timeout, self._limit = timeout, limit
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._buffers = [b"", b""]
        self._totals = [0, 0]
        self._process, self._job = None, None
        self._readers = []
        self._cleaned = False
        self._reader_failed = False
        self._retry_task = None
        self.pid = 0
        self._loop = asyncio.get_running_loop()
        self._ready = self._loop.create_future()
        self._task = asyncio.create_task(asyncio.to_thread(self._worker), name="plugin-owned-process")
        self._task.add_done_callback(self._finished)

    def _finished(self, task):
        if not self._ready.done():
            result = task.result() if not task.cancelled() and task.exception() is None else None
            self._ready.set_exception(ProcessAccessError(result.error_code if result else "process/spawn-failed", "Process could not be published"))

    def _publish(self):
        if not self._ready.done():
            self._ready.set_result(None)

    def _read(self, pipe, index):
        try:
            while True:
                data = pipe.read1(8192)
                if not data:
                    break
                with self._lock:
                    self._totals[index] += len(data)
                    self._buffers[index] = (self._buffers[index] + data)[-self._limit:]
        except Exception:
            self._reader_failed = True
        finally:
            pipe.close()

    def _reclaim(self):
        process = self._process
        if process is None:
            self._cleaned = True
            return
        if self._job is not None:
            terminate_process_tree(process, job_handle=self._job)
            for _ in range(250):
                count = _windows_job_active_processes(self._job)
                if count == 0:
                    break
                if count is None:
                    raise ProcessAccessError("process/owner-unknown", "Cannot observe owned process range")
                time.sleep(0.01)
            else:
                raise ProcessAccessError("process/cleanup-failed", "Owned process range has not exited")
        elif process.poll() is None:
            terminate_process_tree(process)
        process.wait(timeout=3)
        if process.stdin is not None:
            process.stdin.close()
        if not self._readers:
            for pipe in (process.stdout, process.stderr):
                if pipe is not None:
                    pipe.close()
        for reader in self._readers:
            reader.join(timeout=1)
        if any(reader.is_alive() for reader in self._readers):
            raise ProcessAccessError("process/output-open", "Output pipes remain open after owned range exit")
        if self._job is not None:
            _windows_job_release(self._job)
            self._job = None
        self._cleaned = True

    def _worker(self):
        started = time.monotonic()
        status = "exited"
        exit_code = None
        try:
            self._process = subprocess.Popen(self._argv, cwd=str(self._cwd), env=self._env, shell=False,
                stdin=subprocess.PIPE if self._stdin_enabled else subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=_windows_command_creationflags())
            self.pid = self._process.pid
            self._job = _windows_job_assign(self._process)
            if self._job is None:
                raise ProcessAccessError("process/owner-unavailable", "A Windows Job owner is required")
            self._readers = [threading.Thread(target=self._read, args=(pipe, index), daemon=True)
                             for index, pipe in enumerate((self._process.stdout, self._process.stderr))]
            for reader in self._readers:
                reader.start()
            self._loop.call_soon_threadsafe(self._publish)
            while True:
                if self._stop.is_set():
                    status = "stopped"
                    break
                if time.monotonic() - started >= self._timeout:
                    status = "timed_out"
                    break
                exit_code = self._process.poll()
                if exit_code is not None:
                    break
                self._stop.wait(0.02)
            self._reclaim()
            if self._reader_failed:
                return ProcessOutcome(self._process.returncode, "failed", True, "process/output-failed")
            return ProcessOutcome(self._process.returncode if exit_code is None else exit_code, status, True)
        except Exception as error:
            code = error.code if isinstance(error, ProcessAccessError) else "process/spawn-failed"
            try:
                self._reclaim()
            except Exception:
                return ProcessOutcome(exit_code, "failed", False, "process/cleanup-failed")
            return ProcessOutcome(exit_code, "failed", True, code)

    async def ready(self):
        try:
            await asyncio.shield(self._ready)
        except asyncio.CancelledError:
            self._stop.set()
            await _join(self._task)
            # Consume a possible unpublished-spawn error after cancellation.
            if self._ready.done() and not self._ready.cancelled():
                self._ready.exception()
            raise

    async def write_stdin(self, data, *, timeout=5):
        self._scope.acquire()
        task = None
        try:
            if type(data) is not bytes or len(data) > 16384 or type(timeout) not in {int, float} or not math.isfinite(timeout) or not 0 < timeout <= 30:
                raise ProcessAccessError("process/invalid-input", "stdin accepts at most 16 KiB bytes with timeout in (0, 30]")
            if not self._stdin_enabled or self._cleaned or self._process is None or self._process.stdin is None:
                raise ProcessAccessError("process/stdin-closed", "This process has no open interactive input")
            def write():
                self._process.stdin.write(data)
                self._process.stdin.flush()
            try:
                async with asyncio.timeout(timeout):
                    async with self._stdin_lock:
                        self._scope.check_open()
                        task = asyncio.create_task(asyncio.to_thread(write), name="plugin-process-stdin")
                        await asyncio.shield(task)
                return len(data)
            except (TimeoutError, asyncio.CancelledError) as error:
                if task is not None:
                    await self.shutdown()
                    try:
                        await _join(task)
                    except Exception:
                        pass
                if isinstance(error, asyncio.CancelledError):
                    raise
                raise ProcessAccessError("process/stdin-timeout", "stdin deadline expired; an admitted writer's owned process range was reclaimed") from None
            except (OSError, ValueError):
                raise ProcessAccessError("process/stdin-closed", "Process input is closed; bytes may have been delivered") from None
        finally:
            self._scope.release()

    async def wait(self) -> ProcessOutcome:
        self._scope.check_open()
        result = await asyncio.shield(self._task)
        if result.status == "failed":
            raise ProcessAccessError(result.error_code, "Process failed; inspect cleanup state before retrying")
        return result

    async def terminate(self) -> ProcessOutcome:
        # Stale handles may only stop/join their own native owner, never target a PID supplied by a caller.
        caller = asyncio.current_task()
        cancelling = caller.cancelling()
        self._stop.set()
        result = await _join(self._task)
        if not self._cleaned:
            await self._retry_reclaim()
        if caller.cancelling() > cancelling:
            raise asyncio.CancelledError
        if not result.quiescent:
            return ProcessOutcome(result.exit_code, "stopped", True)
        return result

    def read_output(self, *, stdout_after=0, stderr_after=0) -> ProcessOutput:
        self._scope.check_open()
        offsets = (stdout_after, stderr_after)
        with self._lock:
            if any(type(value) is not int or value < 0 or value > self._totals[index] for index, value in enumerate(offsets)):
                raise ProcessAccessError("process/invalid-cursor", "Output offsets must be observed non-negative byte positions")
            chunks, lost = [], []
            for index, offset in enumerate(offsets):
                start = self._totals[index] - len(self._buffers[index])
                lost.append(offset < start)
                chunks.append(self._buffers[index][max(offset, start) - start:])
            return ProcessOutput(*chunks, *self._totals, *lost, self._task.done() and self._cleaned and not self._reader_failed)

    async def _retry_reclaim(self):
        if self._retry_task is None or self._retry_task.done():
            self._retry_task = asyncio.create_task(asyncio.to_thread(self._reclaim), name="plugin-process-reclaim")
        await _join(self._retry_task)

    async def shutdown(self):
        self._stop.set()
        await _join(self._task)
        if not self._cleaned:
            await self._retry_reclaim()


__all__ = ["OwnedProcess", "ProcessOutcome", "ProcessOutput"]
