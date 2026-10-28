from __future__ import annotations

import asyncio
import contextlib
import codecs
import io
import json
import logging
import re
import shlex
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from lamtools_core.tool.workspace import is_within_path

DEFAULT_MAX_TEXT_LENGTH = 50_000

logger = logging.getLogger(__name__)


class _BoundedOutput:
    # user:“该修修，该重构重构，有必要就重新设计架构或者迁到 Rust”+(限制捕获阶段的内存，超长单行也只保留首尾，不能等显示时才截断)。
    def __init__(self, limit: int = DEFAULT_MAX_TEXT_LENGTH) -> None:
        self.limit = limit
        self.total = 0
        self.head = ""
        self.tail = ""

    def append(self, text: str) -> None:
        self.total += len(text)
        head_limit = self.limit // 2
        take = min(len(text), head_limit - len(self.head))
        self.head += text[:take]
        self.tail = (self.tail + text[take:])[-(self.limit - head_limit):]

    def snapshot(self) -> str:
        if self.total <= self.limit:
            return self.head + self.tail
        omitted = self.total - len(self.head) - len(self.tail)
        return self.head + f"\n[... {omitted} characters truncated ...]\n" + self.tail


def read_command_log(path: Path) -> str:
    """Preview a possibly huge log without reading the entire file."""
    if not path.exists():
        return ""
    with path.open("rb") as handle:
        size = handle.seek(0, 2)
        handle.seek(0)
        if size <= DEFAULT_MAX_TEXT_LENGTH:
            return handle.read(DEFAULT_MAX_TEXT_LENGTH).decode("utf-8", errors="replace")
        half = DEFAULT_MAX_TEXT_LENGTH // 2
        head = handle.read(half).decode("utf-8", errors="replace")
        handle.seek(-half, 2)
        tail = handle.read(half).decode("utf-8", errors="replace")
    return head + f"\n[... {size - 2 * half} bytes truncated ...]\n" + tail


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


def _windows_command_creationflags() -> int:
    if sys.platform != "win32":
        return 0
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return flags


def terminate_process_tree(
    process: subprocess.Popen[Any],
    *,
    job_handle: int | None = None,
) -> None:
    pid = process.pid
    if job_handle is not None and _terminate_windows_job(job_handle):
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            check=False,
            creationflags=_windows_command_creationflags(),
        )
        return
    process.kill()


# Windows Job Object plumbing (ctypes, win32 only). A job guarantees the whole
# descendant tree dies on TerminateJobObject: taskkill /T can miss children
# whose intermediate process already restructured, and a survivor inherits the
# stdout/stderr pipe handles so the parent's communicate() never sees EOF —
# exactly the "interrupt never returns" failure mode.
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00000200
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
_JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION_CLASS = 1
_WINDOWS_JOB_HANDLES: set[int] = set()

if sys.platform == "win32":
    import ctypes as _ctypes
    from ctypes import wintypes as _wintypes

    _kernel32 = _ctypes.WinDLL("kernel32", use_last_error=True)
    # Explicit argtypes are mandatory: without them ctypes narrows pointer
    # arguments to 32-bit ints, which corrupts buffer addresses on x64.
    _kernel32.CreateJobObjectW.restype = _wintypes.HANDLE
    _kernel32.CreateJobObjectW.argtypes = [_wintypes.LPCWSTR, _wintypes.LPCWSTR]
    _kernel32.SetInformationJobObject.restype = _wintypes.BOOL
    _kernel32.SetInformationJobObject.argtypes = [
        _wintypes.HANDLE, _ctypes.c_int, _ctypes.c_void_p, _wintypes.DWORD,
    ]
    _kernel32.QueryInformationJobObject.restype = _wintypes.BOOL
    _kernel32.QueryInformationJobObject.argtypes = [
        _wintypes.HANDLE, _ctypes.c_int, _ctypes.c_void_p, _wintypes.DWORD,
        _ctypes.POINTER(_wintypes.DWORD),
    ]
    _kernel32.AssignProcessToJobObject.restype = _wintypes.BOOL
    _kernel32.AssignProcessToJobObject.argtypes = [_wintypes.HANDLE, _wintypes.HANDLE]
    _kernel32.TerminateJobObject.restype = _wintypes.BOOL
    _kernel32.TerminateJobObject.argtypes = [_wintypes.HANDLE, _wintypes.UINT]
    _kernel32.CloseHandle.restype = _wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [_wintypes.HANDLE]
else:
    _kernel32 = None


def _windows_job_assign(process: subprocess.Popen[Any]) -> int | None:
    """Put *process* into a kill-on-close job; returns the job handle or None."""
    if _kernel32 is None:
        return None
    try:
        import struct

        job = _kernel32.CreateJobObjectW(None, None)
        if not job:
            return None
        # JOBOBJECT_EXTENDED_LIMIT_INFORMATION with LimitFlags at offset 40.
        # The canonical x64 size is 168; some sandboxed/layered environments
        # expect a shorter 144-byte layout, so probe a small size ladder on
        # ERROR_BAD_LENGTH. LimitFlags sits at offset 40 in every variant.
        assigned = False
        for size in (168, 144):
            buffer = _ctypes.create_string_buffer(size)
            struct.pack_into("<I", buffer, 40, _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE)
            if _kernel32.SetInformationJobObject(
                job,
                _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
                _ctypes.c_void_p(_ctypes.addressof(buffer)),
                size,
            ):
                assigned = True
                break
        if not assigned:
            _kernel32.CloseHandle(job)
            return None
        if not _kernel32.AssignProcessToJobObject(job, _wintypes.HANDLE(process._handle)):
            _kernel32.CloseHandle(job)
            return None
        handle = int(job)
        _WINDOWS_JOB_HANDLES.add(handle)
        return handle
    except Exception:
        return None


def _terminate_windows_job(job_handle: int) -> bool:
    if _kernel32 is None:
        return False
    try:
        return bool(_kernel32.TerminateJobObject(_wintypes.HANDLE(job_handle), 1))
    except Exception:
        return False


def _windows_job_active_processes(job_handle: int) -> int | None:
    if _kernel32 is None:
        return None
    try:
        import ctypes as _ct

        class _BasicAccounting(_ct.Structure):
            _fields_ = [
                ("TotalUserTime", _ct.c_int64),
                ("TotalKernelTime", _ct.c_int64),
                ("ThisPeriodTotalUserTime", _ct.c_int64),
                ("ThisPeriodTotalKernelTime", _ct.c_int64),
                ("TotalPageFaultCount", _wintypes.DWORD),
                ("TotalProcesses", _wintypes.DWORD),
                ("ActiveProcesses", _wintypes.DWORD),
                ("TotalTerminatedProcesses", _wintypes.DWORD),
            ]

        info = _BasicAccounting()
        if not _kernel32.QueryInformationJobObject(
            _wintypes.HANDLE(job_handle),
            _JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION_CLASS,
            _ct.c_void_p(_ct.addressof(info)),
            _ct.sizeof(info),
            None,
        ):
            return None
        return int(info.ActiveProcesses)
    except Exception:
        return None


def _windows_job_release(job_handle: int | None) -> None:
    """Drop the job handle unless processes are still alive inside it.

    Closing the handle of a kill-on-close job while a detached descendant is
    still alive would kill a process the command legitimately left running,
    so the handle is kept (tracked) until backend exit in that case; the
    exit hook closes it, which deliberately reaps survivors.
    """
    if job_handle is None or _kernel32 is None:
        return
    _WINDOWS_JOB_HANDLES.discard(job_handle)
    try:
        if _windows_job_active_processes(job_handle) != 0:
            _WINDOWS_JOB_HANDLES.add(job_handle)
            return
        _kernel32.CloseHandle(_wintypes.HANDLE(job_handle))
    except Exception:
        pass


def _release_windows_jobs_at_exit() -> None:
    for handle in tuple(_WINDOWS_JOB_HANDLES):
        _WINDOWS_JOB_HANDLES.discard(handle)
        try:
            import ctypes

            ctypes.windll.kernel32.CloseHandle(handle)
        except Exception:
            pass


if sys.platform == "win32":
    import atexit

    atexit.register(_release_windows_jobs_at_exit)


def _close_pipes(process: subprocess.Popen[Any]) -> None:
    """Close our pipe read ends so a surviving descendant cannot wedge reads.

    communicate()/readline() only return at EOF; a grandchild holding the
    write end keeps the pipe open even after the direct child is dead.
    """
    for stream in (process.stdout, process.stderr):
        try:
            if stream is not None and not stream.closed:
                stream.close()
        except Exception:
            pass


def run_subprocess_blocking(
    argv: list[str] | str,
    *,
    cwd: Path,
    timeout: int,
    env: dict[str, str] | None = None,
    cancel_event: threading.Event | None = None,
) -> CommandExecution:
    # user:“该修修，该重构重构，有必要就重新设计架构或者迁到 Rust”+(普通命令与实时命令共用有界捕获，避免 communicate 无上限缓存)。
    return run_subprocess_streaming_blocking(
        argv, cwd=cwd, timeout=timeout, env=env, cancel_event=cancel_event,
        progress=lambda _stdout, _stderr: None,
    )


def _collect_after_terminate(process: subprocess.Popen[Any]) -> tuple[str, str]:
    """Read output after a forced terminate without ever hanging or raising.

    A terminated tree usually closes the pipes promptly. If a survivor still
    holds the write end, the pipe read ends are closed so no reader can wedge
    on EOF — output is best-effort at this point, and the caller already has
    its own cancel/timeout result.
    """
    try:
        return process.communicate(timeout=2)
    except Exception:
        _close_pipes(process)
        with contextlib.suppress(Exception):
            process.wait(timeout=2)
        return "", ""


def run_subprocess_streaming_blocking(
    argv: list[str] | str,
    *,
    cwd: Path,
    timeout: int,
    progress: Callable[[str, str], None],
    env: dict[str, str] | None = None,
    cancel_event: threading.Event | None = None,
) -> CommandExecution:
    started_at = time.monotonic()
    creationflags = _windows_command_creationflags()
    process: subprocess.Popen[str] | None = None
    job_handle: int | None = None
    stdout_parts = _BoundedOutput()
    stderr_parts = _BoundedOutput()
    threads: list[threading.Thread] = []
    lock = threading.Lock()
    last_progress = 0.0

    def _metadata() -> dict[str, Any]:
        with lock:
            return {"stdout_chars": stdout_parts.total, "stderr_chars": stderr_parts.total,
                    "output_truncated": stdout_parts.total > stdout_parts.limit or stderr_parts.total > stderr_parts.limit}

    def _snapshot() -> tuple[str, str]:
        with lock:
            return stdout_parts.snapshot(), stderr_parts.snapshot()

    def _append_and_emit(parts: _BoundedOutput, text: str) -> None:
        nonlocal last_progress
        with lock:
            parts.append(text)
            now = time.monotonic()
            if now - last_progress < 0.1:
                return
            last_progress = now
            stdout = stdout_parts.snapshot()
            stderr = stderr_parts.snapshot()
        progress(stdout, stderr)

    def _reader(pipe: Any, parts: _BoundedOutput) -> None:
        try:
            decoder = io.IncrementalNewlineDecoder(
                codecs.getincrementaldecoder("utf-8")(errors="replace"), translate=True
            )
            while True:
                # read1 returns available bytes, so short progress lines remain
                # responsive without letting readline allocate a giant line.
                chunk = pipe.read1(8192)
                if not chunk:
                    break
                _append_and_emit(parts, decoder.decode(chunk))
            tail = decoder.decode(b"", final=True)
            if tail:
                _append_and_emit(parts, tail)
        finally:
            try:
                pipe.close()
            except Exception:
                pass

    try:
        process = subprocess.Popen(
            argv,
            cwd=str(cwd),
            env=env,
            shell=isinstance(argv, str),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        threads = [
            threading.Thread(target=_reader, args=(process.stdout, stdout_parts), daemon=True),
            threading.Thread(target=_reader, args=(process.stderr, stderr_parts), daemon=True),
        ]
        for thread in threads:
            thread.start()
        job_handle = _windows_job_assign(process)
        deadline = time.monotonic() + timeout
        while True:
            if cancel_event is not None and cancel_event.is_set():
                terminate_process_tree(process, job_handle=job_handle)
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
                    metadata=_metadata(),
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
            metadata=_metadata(),
        )
    except subprocess.TimeoutExpired as exc:
        if process is not None:
            terminate_process_tree(process, job_handle=job_handle)
            # The job kill closes every write end; the reader threads see EOF
            # promptly. Close our read ends too so a stray survivor cannot
            # wedge a daemon reader on a blocked readline.
            _close_pipes(process)
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
            metadata=_metadata(),
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
    finally:
        _windows_job_release(job_handle)


async def run_subprocess(
    argv: list[str] | str,
    *,
    cwd: Path,
    timeout: int,
    progress_callback: Callable[[str, str], Awaitable[None]] | None = None,
    env: dict[str, str] | None = None,
) -> CommandExecution:
    cancel_event = threading.Event()
    if progress_callback is None:
        future = asyncio.create_task(
            asyncio.to_thread(run_subprocess_blocking, argv, cwd=cwd, timeout=timeout, env=env, cancel_event=cancel_event)
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
            future.cancel()
            logger.debug("Command progress callback failed", exc_info=True)

    future = asyncio.create_task(
        asyncio.to_thread(
            run_subprocess_streaming_blocking,
            argv,
            cwd=cwd,
            timeout=timeout,
            progress=_progress,
            env=env,
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
    process_state: str = "",
    shell_state: str = "",
    readiness_state: str = "",
    background_requested: bool | None = None,
    background_inferred: bool | None = None,
    persistent: bool | None = None,
    max_length: int = DEFAULT_MAX_TEXT_LENGTH,
) -> str:
    sections: list[str] = [f"[command] {command}"]
    if timed_out:
        sections.append(f"[exit_code: -1] [TIMED OUT after {timeout_val}s]")
    else:
        sections.append(f"[exit_code: {exit_code}]")
    if process_state:
        sections.append(f"[process_state: {process_state}]")
    if shell_state:
        sections.append(f"[shell_state: {shell_state}]")
    if readiness_state:
        sections.append(f"[readiness_state: {readiness_state}]")
    if background_requested is not None:
        sections.append(f"[background_requested: {str(background_requested).lower()}]")
    if background_inferred is not None:
        sections.append(f"[background_inferred: {str(background_inferred).lower()}]")
    if persistent:
        sections.append("[persistent: true] process survives turn end; registered for this session")
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
    sections: list[str] = [
        f"[command] {command}",
        "[status: running]",
        "[process_state: running]",
        "[shell_state: running]",
        "[readiness_state: not_requested]",
    ]
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


@dataclass(frozen=True)
class CommandPathArgument:
    """A command argument that may name a filesystem path."""

    position: int
    raw: str
    value: str
    #: Path-shaped quoting that cannot be resolved safely (``cat "a'b"``).
    quoting_unverifiable: bool
    #: Tilde/parameter/command expansion: the shell resolves it, not us.
    expansion: bool


def _command_path_arguments(args: list[str]) -> Iterator[CommandPathArgument]:
    """Classify which arguments reach the workspace-bounds check.

    Shared by the enforcing validator and the approval gate's "would this
    escape the workspace?" detector so both use one tokenization rule.
    """
    for i, raw_arg in enumerate(args):
        if i == 0:
            continue

        # Windows-oriented tokenization deliberately preserves quote marks.
        # Remove balanced shell quoting before resolving paths so e.g.
        # `cat '../outside'` cannot pass validation as a literal filename.
        arg = _strip_matching_quotes(raw_arg)

        if "=" in arg:
            value = _strip_matching_quotes(arg.split("=", 1)[1])
            if not value:
                continue
        elif arg.startswith("-") or (arg.startswith("/") and len(arg) <= 4 and arg[1:].isalpha()):
            continue
        else:
            value = arg

        has_path_syntax = (
            value in {".", ".."}
            or value.startswith(("./", ".\\", "../", "..\\"))
            or "/" in value
            or "\\" in value
            or re.match(r"^[A-Za-z]:[\\/]", value) is not None
        )
        bounds_candidate = (
            value in {".", ".."}
            or value.startswith("/")
            or value.startswith("~")
            or re.match(r"^[A-Za-z]:[\\/]", value)
            or "/" in value
            or "\\" in value
        )
        if not bounds_candidate:
            continue
        yield CommandPathArgument(
            position=i,
            raw=raw_arg,
            value=value,
            quoting_unverifiable=has_path_syntax and any(char in value for char in "'\""),
            expansion=value.startswith("~") or any(ch in value for ch in "$`"),
        )


def command_path_roots(
    work_root: Path,
    resource_roots: tuple[Path, ...] = (),
) -> tuple[Path, ...]:
    return (work_root.resolve(), *(root.resolve() for root in resource_roots))


def outside_workdir_path_arguments(
    args: list[str],
    work_root: Path,
    resource_roots: tuple[Path, ...] = (),
) -> list[str]:
    """Return path arguments that resolve beyond the workspace and its roots.

    Unverifiable quoting is skipped — the executor rejects those as invalid
    syntax, so they are not a consent question.  Expansion tokens (``~``,
    ``$VAR``, backticks) count as outside because only the shell can resolve
    them.
    """
    allowed_roots = command_path_roots(work_root, resource_roots)
    outside: list[str] = []
    for item in _command_path_arguments(args):
        if item.quoting_unverifiable:
            continue
        if item.expansion:
            outside.append(item.raw)
            continue
        resolved = (Path(work_root) / item.value).resolve()
        if not any(is_within_path(resolved, root) for root in allowed_roots):
            outside.append(item.raw)
    return outside


def validate_command_paths(
    args: list[str],
    work_root: Path,
    resource_roots: tuple[Path, ...] = (),
    *,
    allow_outside: bool = True,
) -> None:
    """Reject path arguments outside the workspace only when asked to.

    The workspace boundary is no longer enforced (2026-09-27), so the default
    is permissive: an argument whose quoting cannot be resolved statically is
    skipped, matching ``outside_workdir_path_arguments``.  An explicit
    ``allow_outside=False`` restores the strict bounds check for callers that
    still require it.
    """
    for item in _command_path_arguments(args):
        if item.quoting_unverifiable:
            if allow_outside:
                # Not a bounds question while the boundary is not enforced:
                # genuinely invalid syntax is rejected by the executor's own
                # tokenizer, and a resolvable path is authorized anyway.
                continue
            raise ValueError(
                f"Path argument '{item.raw}' (position {item.position}) uses mixed or unmatched "
                "quoting, so it cannot be verified to stay inside the workspace: use consistent "
                "quoting or split the command into separate calls"
            )
        if allow_outside:
            continue
        # Tilde / parameter / command expansion cannot be statically resolved —
        # the shell would expand the token outside work_root
        # (``cat ~/.ssh/id_rsa``, ``cat $HOME/.ssh/id_rsa``,
        # ``echo x > ~/.bashrc``).  Reject instead of letting the literal
        # path pass the bounds check (audit 06 S1).
        if item.expansion:
            raise ValueError(
                f"Path argument '{item.raw}' (position {item.position}) uses shell expansion "
                "that cannot be validated against the workspace"
            )
        resolved = (work_root / item.value).resolve()
        if not any(is_within_path(resolved, root) for root in command_path_roots(work_root, resource_roots)):
            raise ValueError(f"Path argument '{item.raw}' (position {item.position}) escapes work_root")


def _strip_matching_quotes(value: str) -> str:
    while len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return value


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
