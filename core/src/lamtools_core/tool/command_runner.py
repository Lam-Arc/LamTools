from __future__ import annotations

import asyncio
import contextlib
import datetime
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lamtools_core.tool.command import (
    CommandExecution as _CommandExecution,
    format_command_output as _format_command_output,
    format_running_command_output as _format_running_command_output,
    run_subprocess as _run_subprocess,
    run_subprocess_blocking as _run_subprocess_blocking,
    run_subprocess_streaming_blocking as _run_subprocess_streaming_blocking,
    terminate_process_tree as _terminate_process_tree,
)


def _exception_summary(exc: BaseException) -> str:
    message = str(exc).strip()
    if message:
        return f"{type(exc).__name__}: {message}"
    return type(exc).__name__


@dataclass(frozen=True)
class _BackgroundProbeResult:
    ok: bool
    error: str = ""
    error_type: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class _BackgroundHttpProbe:
    url_value: str
    expected_text: str = ""
    port: int | None = None
    path: str = ""
    file_path: Path | None = None
    timeout_seconds: float = 4.0

    @property
    def url(self) -> str:
        return self.url_value


def _run_background_subprocess_blocking(
    argv: list[str] | str,
    *,
    cwd: Path,
    command: str,
    http_probe: _BackgroundHttpProbe | None = None,
    process_registry: Any | None = None,
    session_id: str = "",
    run_id: str = "",
    cancel_event: threading.Event | None = None,
) -> _CommandExecution:
    started_at = time.monotonic()
    log_dir = cwd / ".lamtools" / "background"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", command.strip())[:48].strip("-") or "command"
    stdout_path = log_dir / f"{stamp}-{safe_name}.out.log"
    stderr_path = log_dir / f"{stamp}-{safe_name}.err.log"
    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    stdout_handle = stdout_path.open("w", encoding="utf-8", errors="replace")
    stderr_handle = stderr_path.open("w", encoding="utf-8", errors="replace")
    try:
        process = subprocess.Popen(
            argv,
            cwd=str(cwd),
            shell=isinstance(argv, str),
            stdout=stdout_handle,
            stderr=stderr_handle,
            stdin=subprocess.DEVNULL,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
        )
    except Exception as exc:
        stdout_handle.close()
        stderr_handle.close()
        return _CommandExecution(
            exit_code=1,
            duration_seconds=time.monotonic() - started_at,
            error=f"Cannot start background command: {_exception_summary(exc)}",
            error_type=type(exc).__name__,
        )
    finally:
        try:
            stdout_handle.close()
        finally:
            stderr_handle.close()

    if cancel_event is not None and cancel_event.wait(0.5):
        _terminate_process_tree(process)
        return _CommandExecution(
            exit_code=-1,
            background=True,
            duration_seconds=time.monotonic() - started_at,
            error="Command cancelled by user",
            error_type="CancelledError",
            metadata={"pid": process.pid},
        )
    if cancel_event is None:
        time.sleep(0.5)
    if process.poll() is not None:
        stdout = stdout_path.read_text(encoding="utf-8", errors="replace") if stdout_path.exists() else ""
        stderr = stderr_path.read_text(encoding="utf-8", errors="replace") if stderr_path.exists() else ""
        error_type = "BackgroundExited"
        metadata = {
            "pid": process.pid,
            "stdout_log": str(stdout_path),
            "stderr_log": str(stderr_path),
        }
        if http_probe is not None:
            metadata.update({
                "server_probe_url": http_probe.url,
                "server_probe_path": http_probe.path,
                **({"server_port": http_probe.port} if http_probe.port is not None else {}),
                "readiness_text_checked": bool(http_probe.expected_text),
            })
            classified = _classify_background_start_failure(stderr=stderr, port=http_probe.port)
            if classified is not None:
                error_type, classified_metadata = classified
                metadata.update(classified_metadata)
        return _CommandExecution(
            exit_code=int(process.returncode or 0),
            stdout=stdout,
            stderr=stderr,
            background=True,
            duration_seconds=time.monotonic() - started_at,
            error=f"Background command exited early with code {process.returncode}",
            error_type=error_type,
            metadata=metadata,
        )

    if http_probe is not None:
        probe_result = _wait_for_background_http_probe(http_probe, cancel_event=cancel_event)
        if not probe_result.ok:
            _terminate_process_tree(process)
            stdout = stdout_path.read_text(encoding="utf-8", errors="replace") if stdout_path.exists() else ""
            stderr = stderr_path.read_text(encoding="utf-8", errors="replace") if stderr_path.exists() else ""
            return _CommandExecution(
                exit_code=1,
                stdout=stdout,
                stderr=stderr,
                background=True,
                duration_seconds=time.monotonic() - started_at,
                error=probe_result.error,
                error_type=probe_result.error_type,
                metadata={
                    "pid": process.pid,
                    "stdout_log": str(stdout_path),
                    "stderr_log": str(stderr_path),
                    "server_probe_url": http_probe.url,
                    "server_probe_path": http_probe.path,
                    **({"server_port": http_probe.port} if http_probe.port is not None else {}),
                    "readiness_text_checked": bool(http_probe.expected_text),
                    **probe_result.metadata,
                },
            )

    if cancel_event is not None and cancel_event.is_set():
        _terminate_process_tree(process)
        return _CommandExecution(
            exit_code=-1,
            background=True,
            duration_seconds=time.monotonic() - started_at,
            error="Command cancelled by user",
            error_type="CancelledError",
            metadata={"pid": process.pid},
        )

    if process_registry is not None:
        try:
            process_registry.register(
                process,
                session_id=session_id,
                run_id=run_id,
                work_root=cwd,
            )
        except Exception as exc:
            _terminate_process_tree(process)
            return _CommandExecution(
                exit_code=1,
                background=True,
                duration_seconds=time.monotonic() - started_at,
                error=f"Cannot register background process ownership: {_exception_summary(exc)}",
                error_type="BackgroundOwnershipRegistrationFailed",
                metadata={"pid": process.pid},
            )

    return _CommandExecution(
        exit_code=0,
        background=True,
        duration_seconds=time.monotonic() - started_at,
        stdout=(
            f"Background process started (pid {process.pid})."
            + (f"\nHTTP probe passed: {http_probe.url}" if http_probe is not None else "")
        ),
        metadata={
            "pid": process.pid,
            "stdout_log": str(stdout_path),
            "stderr_log": str(stderr_path),
            **({
                "server_probe_url": http_probe.url,
                "server_probe_path": http_probe.path,
                **({"server_port": http_probe.port} if http_probe.port is not None else {}),
                **({"url": f"http://127.0.0.1:{http_probe.port}/"} if http_probe.port is not None else {}),
                "readiness_text_checked": bool(http_probe.expected_text),
            } if http_probe is not None else {}),
        },
    )


async def _run_background_subprocess(
    argv: list[str] | str,
    *,
    cwd: Path,
    command: str,
    http_probe: _BackgroundHttpProbe | None = None,
    process_registry: Any | None = None,
    session_id: str = "",
    run_id: str = "",
) -> _CommandExecution:
    cancel_event = threading.Event()
    future = asyncio.create_task(
        asyncio.to_thread(
            _run_background_subprocess_blocking,
            argv,
            cwd=cwd,
            command=command,
            http_probe=http_probe,
            process_registry=process_registry,
            session_id=session_id,
            run_id=run_id,
            cancel_event=cancel_event,
        )
    )
    try:
        return await asyncio.shield(future)
    except asyncio.CancelledError:
        cancel_event.set()
        with contextlib.suppress(BaseException):
            await asyncio.shield(future)
        cleanup_run = getattr(process_registry, "cleanup_run", None)
        if callable(cleanup_run):
            cleanup_run(session_id, run_id)
        raise

def _looks_like_python_http_server(command: str) -> bool:
    lowered = command.strip().lower()
    return bool(re.search(r"\b(?:python|py)\s+(?:-[\w.]+\s+)*-m\s+http\.server\b", lowered))


def _extract_local_server_port(command: str) -> int | None:
    lowered = command.strip().lower()
    match = re.search(r"\b(?:python|py)\s+(?:-[\w.]+\s+)*-m\s+http\.server\s+(\d{2,5})\b", lowered)
    if match:
        try:
            port = int(match.group(1))
        except (TypeError, ValueError):
            return None
        return port if 1 <= port <= 65535 else None
    if _looks_like_python_http_server(command):
        return 8000
    return None


def _is_local_tcp_port_listening(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
            return True
    except OSError:
        return False


def _local_server_error_metadata(
    *,
    error_kind: str,
    recommended_action: str,
    retryable: bool = True,
    port: int | None = None,
    probe_url: str = "",
    probe_path: str = "",
) -> dict[str, Any]:
    return {
        "error_kind": error_kind,
        "retryable": retryable,
        "recommended_action": recommended_action,
        **({"server_port": port} if port is not None else {}),
        **({"server_probe_url": probe_url} if probe_url else {}),
        **({"server_probe_path": probe_path} if probe_path else {}),
    }


def _classify_background_start_failure(
    *,
    stderr: str,
    port: int | None,
) -> tuple[str, dict[str, Any]] | None:
    lowered = stderr.lower()
    port_failure_markers = (
        "address already in use",
        "only one usage of each socket address",
        "winerror 10013",
        "permissionerror",
        "errno 98",
    )
    if port is not None and any(marker in lowered for marker in port_failure_markers):
        return (
            "PortInUse",
            _local_server_error_metadata(
                error_kind="port_in_use",
                recommended_action="choose_free_port",
                port=port,
            ),
        )
    return None


def _validate_readiness_url(value: str) -> str:
    from urllib.parse import urlparse

    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("readiness_url must use http:// or https://")
    host = (parsed.hostname or "").lower()
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("readiness_url must target localhost/127.0.0.1")
    return value


def _make_background_http_probe(work_root: Path, port: int) -> _BackgroundHttpProbe:
    token = f"lamtools-http-probe-{uuid.uuid4().hex}"
    filename = f".lamtools-http-probe-{uuid.uuid4().hex}.txt"
    path = work_root / filename
    path.write_text(token, encoding="utf-8")
    return _BackgroundHttpProbe(
        url_value=f"http://127.0.0.1:{port}/{filename}",
        expected_text=token,
        port=port,
        path=filename,
        file_path=path,
    )


def _make_readiness_http_probe(url: str, expected_text: str = "") -> _BackgroundHttpProbe:
    from urllib.parse import urlparse

    parsed = urlparse(url)
    port = parsed.port
    if port is None and parsed.scheme == "http":
        port = 80
    elif port is None and parsed.scheme == "https":
        port = 443
    return _BackgroundHttpProbe(
        url_value=url,
        expected_text=expected_text,
        port=port,
    )


def _cleanup_background_http_probe(probe: _BackgroundHttpProbe | None) -> None:
    if probe is None:
        return
    try:
        if probe.file_path is not None and probe.file_path.is_file():
            probe.file_path.unlink()
    except OSError:
        pass


def _wait_for_background_http_probe(
    probe: _BackgroundHttpProbe,
    *,
    cancel_event: threading.Event | None = None,
) -> _BackgroundProbeResult:
    import urllib.error
    import urllib.request

    deadline = time.monotonic() + probe.timeout_seconds
    last_error = ""
    last_error_type = "LocalServerUnreachable"
    last_metadata = _local_server_error_metadata(
        error_kind="probe_unreachable",
        recommended_action="check_server_startup_or_choose_free_port",
        port=probe.port,
        probe_url=probe.url,
        probe_path=probe.path,
    )
    while time.monotonic() < deadline:
        if cancel_event is not None and cancel_event.is_set():
            return _BackgroundProbeResult(
                ok=False,
                error="Command cancelled by user",
                error_type="CancelledError",
                metadata={"error_kind": "cancelled", "retryable": False},
            )
        try:
            with urllib.request.urlopen(probe.url, timeout=0.75) as response:
                body = response.read().decode("utf-8", errors="replace")
                if not probe.expected_text or probe.expected_text in body:
                    return _BackgroundProbeResult(ok=True)
                if probe.file_path is not None:
                    last_error_type = "LocalServerWrongRoot"
                    last_error = (
                        f"HTTP probe reached {probe.url}, but response did not match the current work_root probe. "
                        "The port may be serving a different directory or process."
                    )
                    last_metadata = _local_server_error_metadata(
                        error_kind="wrong_server",
                        recommended_action="serve_current_work_root_or_choose_free_port",
                        port=probe.port,
                        probe_url=probe.url,
                        probe_path=probe.path,
                    )
                else:
                    last_error_type = "ReadinessTextMissing"
                    last_error = f"HTTP probe reached {probe.url}, but readiness_text was not present."
                    last_metadata = _local_server_error_metadata(
                        error_kind="readiness_text_missing",
                        recommended_action="check_readiness_text_or_server_output",
                        port=probe.port,
                        probe_url=probe.url,
                        probe_path=probe.path,
                    )
        except urllib.error.HTTPError as exc:
            if probe.file_path is not None:
                last_error_type = "LocalServerWrongRoot"
                last_error = (
                    f"HTTP probe {probe.url} returned {exc.code}; "
                    "the server did not serve the current work_root probe."
                )
                last_metadata = _local_server_error_metadata(
                    error_kind="wrong_server",
                    recommended_action="serve_current_work_root_or_choose_free_port",
                    port=probe.port,
                    probe_url=probe.url,
                    probe_path=probe.path,
                )
            else:
                last_error_type = "ReadinessHttpError"
                last_error = f"HTTP probe {probe.url} returned {exc.code}."
                last_metadata = _local_server_error_metadata(
                    error_kind="probe_http_error",
                    recommended_action="check_readiness_url_or_server_route",
                    port=probe.port,
                    probe_url=probe.url,
                    probe_path=probe.path,
                )
        except OSError as exc:
            last_error_type = "LocalServerUnreachable"
            last_error = f"HTTP probe {probe.url} failed: {exc}"
            last_metadata = _local_server_error_metadata(
                error_kind="probe_unreachable",
                recommended_action="check_server_startup_or_choose_free_port",
                port=probe.port,
                probe_url=probe.url,
                probe_path=probe.path,
            )
        if cancel_event is not None:
            cancel_event.wait(0.2)
        else:
            time.sleep(0.2)
    return _BackgroundProbeResult(
        ok=False,
        error=last_error or f"HTTP probe {probe.url} did not become reachable.",
        error_type=last_error_type,
        metadata=last_metadata,
    )


def _resolve_skill_script_paths(command: str, work_root: Path, skill_roots: set[Path]) -> str:
    """Rewrite skill script relative paths to absolute paths when the file does
    not exist under *work_root* but does exist under a loaded skill root.

    Skill SKILL.md files instruct the agent to run commands like
    ``node .agents/skills/impeccable/scripts/context.mjs`` using a relative path.
    When the skill lives in ``~/.agents/`` (not ``<work_root>/.agents/``), the
    relative path resolves to a non-existent location under *work_root*, causing
    ``MODULE_NOT_FOUND`` or similar errors.  This function detects such cases and
    rewrites the path to the real location inside the matching skill root.
    """
    if not skill_roots:
        return command

    for skill_root in skill_roots:
        if skill_root.parent.name != "skills" or skill_root.parent.parent.name not in (".agents", ".codex", ".claude"):
            continue
        dir_name = skill_root.parent.parent.name
        rel_prefix = f"{dir_name}/skills/{skill_root.name}/"
        abs_prefix = str(skill_root).replace("\\", "/") + "/"
        idx = 0
        while True:
            pos = command.find(rel_prefix, idx)
            if pos == -1:
                break
            if pos > 0 and command[pos - 1] not in (" ", "\t", "'", '"', "=", ";", "|", "&", "(", "{", "`"):
                idx = pos + len(rel_prefix)
                continue
            end = pos + len(rel_prefix)
            after = command[end:]
            tail_match = re.match(r"([^\s'\",;|&)}`]+)", after)
            if not tail_match:
                idx = end
                continue
            tail = tail_match.group(1)
            rel_path = rel_prefix + tail
            work_root_candidate = (work_root / rel_path).resolve()
            if work_root_candidate.is_file():
                idx = pos + len(rel_path)
                continue
            abs_path = abs_prefix + tail
            if Path(abs_path).is_file():
                command = command[:pos] + abs_path + command[pos + len(rel_path):]
                idx = pos + len(abs_path)
                continue
            idx = end
    return command


def _normalize_windows_shell_command(command: str) -> str:
    """Remove a redundant outer cmd wrapper before passing to Windows PowerShell."""
    stripped = command.strip()
    lowered = stripped.lower()
    for prefix in ("cmd.exe /d /c ", "cmd /d /c ", "cmd.exe /c ", "cmd /c "):
        if lowered.startswith(prefix):
            return stripped[len(prefix):].strip()
    return stripped


@dataclass(frozen=True)
class CommandShell:
    name: str
    executable: str
    kind: str

    def argv(self, command: str) -> list[str]:
        if self.kind == "git-bash":
            return [self.executable, "--noprofile", "--norc", "-lc", command]
        if self.kind == "pwsh":
            return _powershell_argv(command, executable=self.executable)
        return _powershell_argv(command, executable=self.executable)


def _git_bash_path() -> Path | None:
    candidates: list[Path] = []
    explicit = os.environ.get("LAMTOOLS_GIT_BASH", "").strip()
    if explicit:
        candidates.append(Path(explicit))

    for executable in ("bash.exe", "bash"):
        resolved = shutil.which(executable)
        if resolved:
            candidates.append(Path(resolved))

    git = shutil.which("git.exe") or shutil.which("git")
    if git:
        git_root = Path(git).resolve().parent.parent
        candidates.extend(
            (git_root / "bin" / "bash.exe", git_root / "usr" / "bin" / "bash.exe")
        )

    for env_name in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        base = os.environ.get(env_name, "").strip()
        if base:
            candidates.extend(
                (
                    Path(base) / "Git" / "bin" / "bash.exe",
                    Path(base) / "Programs" / "Git" / "bin" / "bash.exe",
                )
            )

    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate).casefold()
        if key in seen:
            continue
        seen.add(key)
        if "windows\\system32" in key.replace("/", "\\"):
            continue
        if candidate.is_file():
            return candidate.resolve()
    return None


def resolve_command_shell() -> CommandShell:
    if sys.platform != "win32":
        return CommandShell(name="Direct POSIX execution", executable="", kind="direct")

    preferred = os.environ.get("LAMTOOLS_COMMAND_SHELL", "git-bash").strip().lower()
    if preferred in {"git-bash", "gitbash", "bash", ""}:
        git_bash = _git_bash_path()
        if git_bash is not None:
            return CommandShell(name="Git Bash", executable=str(git_bash), kind="git-bash")
    elif preferred in {"pwsh", "powershell7", "powershell-7"}:
        pwsh = shutil.which("pwsh.exe") or shutil.which("pwsh")
        if pwsh:
            return CommandShell(name="PowerShell 7", executable=pwsh, kind="pwsh")
    elif preferred in {"powershell", "windows-powershell", "powershell5", "powershell-5.1"}:
        return CommandShell(name="Windows PowerShell 5.1", executable="powershell.exe", kind="powershell")

    pwsh = shutil.which("pwsh.exe") or shutil.which("pwsh")
    if pwsh:
        return CommandShell(name="PowerShell 7", executable=pwsh, kind="pwsh")
    return CommandShell(name="Windows PowerShell 5.1", executable="powershell.exe", kind="powershell")


def command_shell_prompt() -> str:
    shell = resolve_command_shell()
    if shell.kind == "git-bash":
        syntax = "Use Bash syntax and Unix commands. Do not use PowerShell cmdlets or Windows PowerShell quoting."
    elif shell.kind == "direct":
        syntax = "Commands are executed directly without shell expansion. Avoid shell-only pipelines and redirection."
    elif shell.kind == "pwsh":
        syntax = "Use PowerShell 7 syntax. Do not assume Windows PowerShell 5.1 limitations or Bash syntax."
    else:
        syntax = "Use Windows PowerShell 5.1 syntax. Do not use PowerShell 7-only operators such as && or Bash syntax."
    return f"[Command Shell]\nrun_command uses {shell.name} ({shell.executable}). {syntax}"


def _powershell_argv(command: str, *, executable: str = "powershell.exe") -> list[str]:
    wrapped = (
        "$ErrorActionPreference = 'Stop'; "
        f"try {{ $__lamtools_output = & {{ {command} }}; "
        "$__lamtools_exit_ok = $?; "
        "$__lamtools_exit_code = $LASTEXITCODE; } "
        "catch { Write-Error $_; exit 1 }; "
        "if ($null -ne $__lamtools_output) { "
        "$__lamtools_output | Out-String -Width 4096 | Write-Output "
        "}; "
        "if ($null -ne $__lamtools_exit_code) { exit $__lamtools_exit_code }; "
        "if ($__lamtools_exit_ok) { exit 0 } else { exit 1 }"
    )
    return [
        executable,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        wrapped,
    ]


def _windows_shell_argv(command: str) -> list[str]:
    """Compatibility wrapper for callers that explicitly require Windows PowerShell."""
    return _powershell_argv(command)
