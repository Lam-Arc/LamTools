from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import shlex
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from lamtools_core.tool.workspace import is_within_path

DEFAULT_MAX_TEXT_LENGTH = 50_000

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CommandExecution:
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    background: bool = False
    duration_seconds: float = 0.0
    error: str = ""
    error_type: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


def _exception_summary(exc: BaseException) -> str:
    message = str(exc).strip()
    if message:
        return f"{type(exc).__name__}: {message}"
    return type(exc).__name__


def _decode_timeout_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def terminate_process_tree(process: subprocess.Popen[Any]) -> None:
    pid = process.pid
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return
    process.kill()


def run_subprocess_blocking(
    argv: list[str] | str,
    *,
    cwd: Path,
    timeout: int,
    cancel_event: threading.Event | None = None,
) -> CommandExecution:
    """Run a command without depending on the active asyncio loop's subprocess support."""
    started_at = time.monotonic()
    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        creationflags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process: subprocess.Popen[str] | None = None
    try:
        process = subprocess.Popen(
            argv,
            cwd=str(cwd),
            shell=isinstance(argv, str),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
        )
        deadline = time.monotonic() + timeout
        while True:
            if cancel_event is not None and cancel_event.is_set():
                terminate_process_tree(process)
                stdout, stderr = process.communicate(timeout=2)
                return CommandExecution(
                    exit_code=-1,
                    stdout=stdout or "",
                    stderr=stderr or "",
                    duration_seconds=time.monotonic() - started_at,
                    error="Command cancelled by user",
                    error_type="CancelledError",
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(argv, timeout)
            try:
                stdout, stderr = process.communicate(timeout=min(0.2, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
        return CommandExecution(
            exit_code=int(process.returncode or 0),
            stdout=stdout or "",
            stderr=stderr or "",
            duration_seconds=time.monotonic() - started_at,
        )
    except subprocess.TimeoutExpired as exc:
        if process is not None:
            terminate_process_tree(process)
            try:
                stdout, stderr = process.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate(timeout=2)
        else:
            stdout = _decode_timeout_output(exc.stdout)
            stderr = _decode_timeout_output(exc.stderr)
        return CommandExecution(
            exit_code=-1,
            stdout=_decode_timeout_output(stdout),
            stderr=_decode_timeout_output(stderr),
            timed_out=True,
            duration_seconds=time.monotonic() - started_at,
            error=f"Command timed out after {timeout}s",
            error_type=type(exc).__name__,
        )
    except OSError as exc:
        return CommandExecution(
            exit_code=1,
            duration_seconds=time.monotonic() - started_at,
            error=f"Cannot execute command: {_exception_summary(exc)}",
            error_type=type(exc).__name__,
        )
    except Exception as exc:
        return CommandExecution(
            exit_code=1,
            duration_seconds=time.monotonic() - started_at,
            error=f"Command execution failed: {_exception_summary(exc)}",
            error_type=type(exc).__name__,
        )


def run_subprocess_streaming_blocking(
    argv: list[str] | str,
    *,
    cwd: Path,
    timeout: int,
    progress: Callable[[str, str], None],
    cancel_event: threading.Event | None = None,
) -> CommandExecution:
    started_at = time.monotonic()
    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        creationflags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process: subprocess.Popen[str] | None = None
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    threads: list[threading.Thread] = []
    lock = threading.Lock()

    def _snapshot() -> tuple[str, str]:
        with lock:
            return "".join(stdout_parts), "".join(stderr_parts)

    def _append_and_emit(parts: list[str], text: str) -> None:
        with lock:
            parts.append(text)
            stdout = "".join(stdout_parts)
            stderr = "".join(stderr_parts)
        progress(stdout, stderr)

    def _reader(pipe: Any, parts: list[str]) -> None:
        try:
            while True:
                text = pipe.readline()
                if not text:
                    break
                _append_and_emit(parts, text)
        finally:
            try:
                pipe.close()
            except Exception:
                pass

    try:
        process = subprocess.Popen(
            argv,
            cwd=str(cwd),
            shell=isinstance(argv, str),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creationflags,
        )
        threads = [
            threading.Thread(target=_reader, args=(process.stdout, stdout_parts), daemon=True),
            threading.Thread(target=_reader, args=(process.stderr, stderr_parts), daemon=True),
        ]
        for thread in threads:
            thread.start()
        deadline = time.monotonic() + timeout
        while True:
            if cancel_event is not None and cancel_event.is_set():
                terminate_process_tree(process)
                for thread in threads:
                    thread.join(timeout=0.2)
                stdout, stderr = _snapshot()
                return CommandExecution(
                    exit_code=-1,
                    stdout=stdout,
                    stderr=stderr,
                    duration_seconds=time.monotonic() - started_at,
                    error="Command cancelled by user",
                    error_type="CancelledError",
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(argv, timeout)
            try:
                process.wait(timeout=min(0.2, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
        for thread in threads:
            thread.join(timeout=1)
        stdout, stderr = _snapshot()
        return CommandExecution(
            exit_code=int(process.returncode or 0),
            stdout=stdout,
            stderr=stderr,
            duration_seconds=time.monotonic() - started_at,
        )
    except subprocess.TimeoutExpired as exc:
        if process is not None:
            terminate_process_tree(process)
            for thread in threads:
                thread.join(timeout=0.2)
            stdout, stderr = _snapshot()
        else:
            stdout = _decode_timeout_output(exc.stdout)
            stderr = _decode_timeout_output(exc.stderr)
        return CommandExecution(
            exit_code=-1,
            stdout=_decode_timeout_output(stdout),
            stderr=_decode_timeout_output(stderr),
            timed_out=True,
            duration_seconds=time.monotonic() - started_at,
            error=f"Command timed out after {timeout}s",
            error_type=type(exc).__name__,
        )
    except OSError as exc:
        return CommandExecution(
            exit_code=1,
            duration_seconds=time.monotonic() - started_at,
            error=f"Cannot execute command: {_exception_summary(exc)}",
            error_type=type(exc).__name__,
        )
    except Exception as exc:
        return CommandExecution(
            exit_code=1,
            duration_seconds=time.monotonic() - started_at,
            error=f"Command execution failed: {_exception_summary(exc)}",
            error_type=type(exc).__name__,
        )


async def run_subprocess(
    argv: list[str] | str,
    *,
    cwd: Path,
    timeout: int,
    progress_callback: Callable[[str, str], Awaitable[None]] | None = None,
) -> CommandExecution:
    cancel_event = threading.Event()
    if progress_callback is None:
        future = asyncio.create_task(
            asyncio.to_thread(run_subprocess_blocking, argv, cwd=cwd, timeout=timeout, cancel_event=cancel_event)
        )
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            cancel_event.set()
            with contextlib.suppress(BaseException):
                await asyncio.shield(future)
            raise

    loop = asyncio.get_running_loop()

    def _progress(stdout: str, stderr: str) -> None:
        future = asyncio.run_coroutine_threadsafe(progress_callback(stdout, stderr), loop)
        try:
            future.result(timeout=5)
        except Exception:
            logger.debug("Command progress callback failed", exc_info=True)

    future = asyncio.create_task(
        asyncio.to_thread(
            run_subprocess_streaming_blocking,
            argv,
            cwd=cwd,
            timeout=timeout,
            progress=_progress,
            cancel_event=cancel_event,
        )
    )
    try:
        return await asyncio.shield(future)
    except asyncio.CancelledError:
        cancel_event.set()
        with contextlib.suppress(BaseException):
            await asyncio.shield(future)
        raise


def format_command_output(
    stdout: str,
    stderr: str,
    exit_code: int,
    command: str,
    *,
    timed_out: bool = False,
    timeout_val: int | None = None,
    max_length: int = DEFAULT_MAX_TEXT_LENGTH,
) -> str:
    sections: list[str] = [f"[command] {command}"]
    if timed_out:
        sections.append(f"[exit_code: -1] [TIMED OUT after {timeout_val}s]")
    else:
        sections.append(f"[exit_code: {exit_code}]")
    if stdout:
        sections.append("[stdout]")
        sections.append(stdout.rstrip("\n"))
    if stderr:
        sections.append("[stderr]")
        sections.append(stderr.rstrip("\n"))
    if not stdout and not stderr:
        sections.append("[no output]")
    result = "\n".join(sections)
    if len(result) > max_length:
        result = result[:max_length] + "\n[... output truncated]"
    return result


def format_running_command_output(
    stdout: str,
    stderr: str,
    command: str,
    *,
    max_length: int = DEFAULT_MAX_TEXT_LENGTH,
) -> str:
    sections: list[str] = [f"[command] {command}", "[status: running]"]
    if stdout:
        sections.append("[stdout]")
        sections.append(stdout.rstrip("\n"))
    if stderr:
        sections.append("[stderr]")
        sections.append(stderr.rstrip("\n"))
    if not stdout and not stderr:
        sections.append("[no output yet]")
    result = "\n".join(sections)
    if len(result) > max_length:
        result = result[:max_length] + "\n[... output truncated]"
    return result


def validate_command_paths(args: list[str], work_root: Path, resource_roots: tuple[Path, ...] = ()) -> None:
    for i, arg in enumerate(args):
        if i == 0:
            continue

        if "=" in arg:
            value = arg.split("=", 1)[1]
            if not value:
                continue
        elif arg.startswith("-") or (arg.startswith("/") and len(arg) <= 4 and arg[1:].isalpha()):
            continue
        else:
            value = arg

        if (
            value.startswith("/")
            or value.startswith("~")
            or re.match(r"^[A-Za-z]:[\\/]", value)
            or "/" in value
            or "\\" in value
        ):
            resolved = (work_root / value).resolve()
            allowed_roots = (work_root.resolve(), *(root.resolve() for root in resource_roots))
            if not any(is_within_path(resolved, root) for root in allowed_roots):
                raise ValueError(f"Path argument '{arg}' (position {i}) escapes work_root")


def detect_test_command(work_root: Path) -> str:
    package_json = work_root / "package.json"
    if package_json.is_file():
        try:
            data = json.loads(package_json.read_text(encoding="utf-8", errors="replace"))
            scripts = data.get("scripts") if isinstance(data, dict) else None
            if isinstance(scripts, dict):
                if "test" in scripts:
                    return "npm test"
                if "build" in scripts:
                    return "npm run build"
        except (OSError, json.JSONDecodeError):
            pass

    python_test_cmd = "py -m pytest" if sys.platform == "win32" else f"{shlex.quote(sys.executable)} -m pytest"
    if (work_root / "pytest.ini").is_file() or (work_root / "pyproject.toml").is_file():
        return python_test_cmd
    if any(work_root.glob("test_*.py")) or (work_root / "tests").is_dir():
        return python_test_cmd
    return ""
