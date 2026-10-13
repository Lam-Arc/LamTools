"""Short-lived search commands with bounded output and descendant cleanup."""

from __future__ import annotations

import asyncio
import contextlib
import math
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time

from lamtools_core.tool.command import (
    _terminate_windows_job,
    _windows_command_creationflags,
    _windows_job_assign,
    _windows_job_active_processes,
    _windows_job_release,
)

from .http_requests import MAX_SEARCH_RESPONSE_BYTES


class SearchProcessError(RuntimeError):
    pass


def _cleanup(process: subprocess.Popen, job_handle: int | None) -> None:
    """Kill the short-lived search tree, then reap its root without waiting on EOF."""
    if sys.platform == "win32":
        if job_handle is None or not _terminate_windows_job(job_handle):
            with contextlib.suppress(OSError, subprocess.TimeoutExpired):
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL, timeout=2, check=False,
                    creationflags=_windows_command_creationflags(),
                )
    else:
        with contextlib.suppress(OSError):
            os.killpg(process.pid, signal.SIGKILL)
    if process.poll() is None:
        with contextlib.suppress(OSError):
            process.kill()
    with contextlib.suppress(OSError, subprocess.TimeoutExpired):
        process.wait(timeout=1)
    if job_handle is not None:
        # TerminateJobObject is asynchronous. Let its descendants finish so
        # the common command helper can close rather than retain this handle.
        deadline = time.monotonic() + 1
        while _windows_job_active_processes(job_handle) not in (0, None) and time.monotonic() < deadline:
            time.sleep(0.01)
    _windows_job_release(job_handle)


def _run_blocking(
    argv: list[str], timeout: float, env: dict[str, str], cancel: threading.Event,
    max_output_bytes: int,
) -> tuple[int, bytes, bytes]:
    if not math.isfinite(timeout) or timeout <= 0:
        raise SearchProcessError("Search process timeout must be finite and positive")
    deadline = time.monotonic() + timeout
    # Descendants may inherit these regular file handles, but never hold up a
    # communicate()/EOF wait. The temporary data is deleted on handle close.
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        process = subprocess.Popen(
            argv, stdin=subprocess.DEVNULL, stdout=out, stderr=err, env=env,
            creationflags=_windows_command_creationflags(),
            start_new_session=sys.platform != "win32",
        )
        job_handle = _windows_job_assign(process)
        try:
            while True:
                if cancel.is_set():
                    raise SearchProcessError("Search command cancelled")
                if os.fstat(out.fileno()).st_size + os.fstat(err.fileno()).st_size > max_output_bytes:
                    raise SearchProcessError(f"Search command output exceeds the {max_output_bytes} byte limit")
                if process.poll() is not None:
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise SearchProcessError(f"Search command exceeded its {timeout:g}s total time limit")
                cancel.wait(min(0.05, remaining))
        finally:
            # Success is also terminal: an external search command must not
            # leave a helper daemon alive after returning its JSON result.
            _cleanup(process, job_handle)
        out.seek(0)
        err.seek(0)
        stdout = out.read(max_output_bytes + 1)
        stderr = err.read(max_output_bytes + 1)
        if len(stdout) + len(stderr) > max_output_bytes:
            raise SearchProcessError(f"Search command output exceeds the {max_output_bytes} byte limit")
        return process.returncode, stdout, stderr


async def run_search_process(
    argv: list[str], *, timeout: float, env: dict[str, str],
    max_output_bytes: int = MAX_SEARCH_RESPONSE_BYTES,
) -> tuple[int, bytes, bytes]:
    cancel = threading.Event()
    worker = asyncio.create_task(asyncio.to_thread(_run_blocking, argv, timeout, env, cancel, max_output_bytes))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        cancel.set()
        # Cleanup uses finite OS waits and never drains a pipe. Keep the
        # cancellation visible only after its process has been cleaned up.
        with contextlib.suppress(BaseException):
            await asyncio.shield(worker)
        raise
