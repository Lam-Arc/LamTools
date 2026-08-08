from __future__ import annotations

import shlex
import sys
from pathlib import Path
from typing import Awaitable, Callable

from lamtools_core.event import CoreEvent
from lamtools_core.runtime.background_processes import (
    BackgroundProcessRegistry,
    default_background_process_registry,
)
from lamtools_core.tool import ToolArtifact, ToolCall, ToolResult
from lamtools_core.tool.command import CommandExecution as _CommandExecution
from lamtools_core.tool.command import format_command_output as _format_command_output
from lamtools_core.tool.command import format_running_command_output as _format_running_command_output
from lamtools_core.tool.command import run_subprocess as _run_subprocess
from lamtools_core.tool.command import validate_command_paths as _validate_command_paths
from lamtools_core.tool.command_runner import (
    _BackgroundHttpProbe,
    _cleanup_background_http_probe,
    _extract_local_server_port,
    _is_local_tcp_port_listening,
    _local_server_error_metadata,
    _looks_like_python_http_server,
    _make_background_http_probe,
    _make_readiness_http_probe,
    _normalize_windows_shell_command,
    _python_http_server_root,
    resolve_command_shell,
    _resolve_skill_script_paths,
    _run_background_subprocess,
    _run_subprocess,
    _validate_readiness_url,
)


def split_command_for_path_validation(command: str) -> list[str]:
    """Split a command for validation while preserving Windows shell behavior."""
    try:
        return shlex.split(command, posix=False)
    except ValueError:
        return command.split()


def _command_lifecycle_metadata(
    execution: _CommandExecution,
    *,
    readiness_requested: bool,
) -> dict[str, str]:
    if execution.background:
        has_process = isinstance(execution.metadata.get("pid"), int)
        if not execution.error:
            process_state = "running"
            shell_state = "running"
        elif not has_process:
            process_state = "not_started"
            shell_state = "not_started"
        elif execution.error_type == "BackgroundExited":
            process_state = "exited"
            shell_state = "exited"
        else:
            process_state = "terminated"
            shell_state = "exited"
    elif execution.timed_out or execution.error_type == "CancelledError":
        process_state = "terminated"
        shell_state = "exited"
    else:
        process_state = "exited"
        shell_state = "exited"

    readiness_state = "not_requested"
    if readiness_requested:
        readiness_state = "failed" if execution.error else "ready"
    return {
        "process_state": process_state,
        "shell_state": shell_state,
        "readiness_state": readiness_state,
    }

class CommandToolHandlers:
    def __init__(
        self,
        *,
        work_root: Path,
        command_timeout: int,
        loaded_skill_roots: set[Path],
        core_event_callback: Callable[[CoreEvent], Awaitable[None]] | None = None,
        background_process_registry: BackgroundProcessRegistry | None = None,
    ) -> None:
        self._work_root = work_root
        self._command_timeout = command_timeout
        self._loaded_skill_roots = loaded_skill_roots
        self._core_event_callback = core_event_callback
        self._background_process_registry = (
            background_process_registry or default_background_process_registry()
        )

    async def run_command(self, call: ToolCall) -> ToolResult:
        """Execute a shell command inside *work_root*.

        On Unix (Linux/macOS): commands are split via ``shlex.split`` and
        executed without shell expansion.

        On Windows: Git Bash is preferred when available. PowerShell 7 or
        Windows PowerShell 5.1 are safe fallbacks when Git Bash is unavailable.

        Path validation applies regardless of platform. Risk approval is
        handled by the caller's command policy before this method executes.
        """
        args = call.arguments if isinstance(call.arguments, dict) else {}
        command = args.get("command", "")
        timeout = args.get("timeout", None)
        background = bool(args.get("background")) if args.get("background") is not None else False
        readiness_url = args.get("readiness_url")
        readiness_text = args.get("readiness_text")

        if not command or not isinstance(command, str):
            return ToolResult(
                call_id=call.id, name=call.name,
                status="failed", error="Missing or invalid 'command' argument",
            )
        if readiness_url is not None and not isinstance(readiness_url, str):
            return ToolResult(
                call_id=call.id, name=call.name,
                status="failed", error="'readiness_url' must be a string or null",
            )
        readiness_url = (readiness_url or "").strip()
        if readiness_text is not None and not isinstance(readiness_text, str):
            return ToolResult(
                call_id=call.id, name=call.name,
                status="failed", error="'readiness_text' must be a string or null",
            )
        readiness_text = readiness_text or ""
        background_inferred = not background and _looks_like_python_http_server(command)
        if readiness_url and not (background or background_inferred):
            return ToolResult(
                call_id=call.id, name=call.name,
                status="failed", error="'readiness_url' requires background=true",
            )
        if readiness_url:
            try:
                readiness_url = _validate_readiness_url(readiness_url)
            except ValueError as exc:
                return ToolResult(
                    call_id=call.id, name=call.name,
                    status="failed", error=str(exc),
                )

        if timeout is not None:
            try:
                timeout = int(timeout)
            except (TypeError, ValueError):
                return ToolResult(
                    call_id=call.id, name=call.name,
                    status="failed", error=f"Invalid timeout value: {args.get('timeout')!r}",
                )
        else:
            timeout = self._command_timeout
        if timeout <= 0:
            return ToolResult(
                call_id=call.id, name=call.name,
                status="failed", error=f"Invalid timeout value: {timeout}",
            )

        command = _resolve_skill_script_paths(command, self._work_root, self._loaded_skill_roots)

        if sys.platform == 'win32':
            command_shell = resolve_command_shell()
            shell_command = (
                _normalize_windows_shell_command(command)
                if command_shell.kind in {"powershell", "pwsh"}
                else command
            )
            argv = command_shell.argv(shell_command)
            validation_argv = [command_shell.kind, *split_command_for_path_validation(shell_command)]
        else:
            command_shell = resolve_command_shell()
            try:
                argv = shlex.split(command)
            except ValueError as exc:
                return ToolResult(
                    call_id=call.id, name=call.name,
                    status="failed", error=f"Invalid command syntax: {exc}",
                )
            validation_argv = argv

        if not argv:
            return ToolResult(
                call_id=call.id, name=call.name,
                status="failed", error="Empty command",
            )

        try:
            _validate_command_paths(
                validation_argv,
                self._work_root,
                tuple(sorted(self._loaded_skill_roots, key=lambda item: item.as_posix())),
            )
        except ValueError as exc:
            return ToolResult(
                call_id=call.id, name=call.name,
                status="failed", error=str(exc),
            )

        run_in_background = background or background_inferred
        http_probe: _BackgroundHttpProbe | None = None
        execution: _CommandExecution | None = None
        try:
            if run_in_background and readiness_url:
                http_probe = _make_readiness_http_probe(readiness_url, readiness_text)
            elif run_in_background and _looks_like_python_http_server(command):
                requested_port = _extract_local_server_port(command)
                if requested_port is not None:
                    if _is_local_tcp_port_listening(requested_port):
                        execution = _CommandExecution(
                            exit_code=1,
                            background=True,
                            error=(
                                f"Port {requested_port} is already listening on 127.0.0.1. "
                                "Do not retry the same port; choose a free port."
                            ),
                            error_type="PortInUse",
                            metadata=_local_server_error_metadata(
                                error_kind="port_in_use",
                                recommended_action="choose_free_port",
                                port=requested_port,
                            ),
                        )
                    else:
                        try:
                            probe_root = _python_http_server_root(command, self._work_root)
                            http_probe = _make_background_http_probe(probe_root, requested_port)
                        except OSError as exc:
                            return ToolResult(
                                call_id=call.id,
                                name=call.name,
                                status="failed",
                                error=f"Cannot create local server probe file: {exc}",
                                metadata={
                                    "command": command,
                                    "port": requested_port,
                                    "error_type": "LocalServerProbeSetupFailed",
                                    "error_kind": "probe_setup_failed",
                                    "retryable": False,
                                    "recommended_action": "report_probe_setup_failure",
                                    "background": True,
                                },
                            )
            if execution is None:
                if run_in_background:
                    runtime_session_id = str(call.metadata.get("_runtime_session_id") or "")
                    runtime_run_id = str(call.metadata.get("_runtime_run_id") or "")
                    execution = await _run_background_subprocess(
                        argv,
                        cwd=self._work_root,
                        command=command,
                        http_probe=http_probe,
                        process_registry=self._background_process_registry,
                        session_id=runtime_session_id,
                        run_id=runtime_run_id,
                    )
                else:
                    async def _emit_command_progress(stdout: str, stderr: str) -> None:
                        if self._core_event_callback is None:
                            return
                        session_id = str(call.metadata.get("_runtime_session_id") or "")
                        if not session_id:
                            return
                        run_id = str(call.metadata.get("_runtime_run_id") or "")
                        await self._core_event_callback(CoreEvent(
                            name="runtime.part",
                            category="tool",
                            payload={
                                "part_type": "tool_result",
                                "status": "running",
                                "content": _format_running_command_output(stdout, stderr, command),
                                "tool_call_id": call.id,
                                "call_id": call.id,
                                "tool_name": call.name,
                                "tool_args": args,
                                "part_id": f"{call.id}:result",
                            },
                            session_id=session_id,
                            run_id=run_id,
                            tags=["tool", "part", "progress"],
                        ))

                    execution = await _run_subprocess(
                        argv,
                        cwd=self._work_root,
                        timeout=timeout,
                        progress_callback=_emit_command_progress if self._core_event_callback is not None else None,
                    )
        finally:
            _cleanup_background_http_probe(http_probe)
        public_call_metadata = {
            key: value
            for key, value in dict(call.metadata or {}).items()
            if not str(key).startswith("_runtime_")
        }
        lifecycle = _command_lifecycle_metadata(
            execution,
            readiness_requested=http_probe is not None,
        )
        output = _format_command_output(
            execution.stdout,
            execution.stderr,
            execution.exit_code,
            command,
            timed_out=execution.timed_out,
            timeout_val=timeout,
            **lifecycle,
            background_requested=background,
            background_inferred=background_inferred,
        )
        metadata = {
            **public_call_metadata,
            "command": command,
            "shell": command_shell.name,
            "shell_executable": command_shell.executable,
            "argv": argv,
            "exit_code": execution.exit_code,
            "timed_out": execution.timed_out,
            "background": execution.background,
            "background_requested": background,
            "background_inferred": background_inferred,
            "duration_seconds": execution.duration_seconds,
            **lifecycle,
            **({"readiness_url": readiness_url} if readiness_url else {}),
            **({"readiness_text": readiness_text} if readiness_url and readiness_text else {}),
            **execution.metadata,
        }
        if execution.error_type:
            metadata["error_type"] = execution.error_type
        artifact = ToolArtifact(
            kind="command_output",
            uri="",
            content=output,
            metadata={
                "command": command,
                "shell": command_shell.name,
                "shell_executable": command_shell.executable,
                "exit_code": execution.exit_code,
                "timed_out": execution.timed_out,
                "background": execution.background,
                "background_requested": background,
                "background_inferred": background_inferred,
                "duration_seconds": execution.duration_seconds,
                **lifecycle,
                "stdout": execution.stdout,
                "stderr": execution.stderr,
                **({"error": execution.error} if execution.error else {}),
                **({"error_type": execution.error_type} if execution.error_type else {}),
                **execution.metadata,
            },
        )

        if execution.error:
            return ToolResult(
                call_id=call.id,
                name=call.name,
                status="failed",
                content=output,
                error=execution.error,
                artifacts=[artifact],
                metadata=metadata,
            )

        if execution.background:
            return ToolResult(
                call_id=call.id, name=call.name,
                status="ok", content=output,
                artifacts=[artifact],
                metadata=metadata,
            )

        if execution.exit_code != 0:
            return ToolResult(
                call_id=call.id, name=call.name,
                status="failed",
                content=output,
                error=f"Command exited with code {execution.exit_code}",
                artifacts=[artifact],
                metadata=metadata,
            )

        return ToolResult(
            call_id=call.id, name=call.name,
            status="ok", content=output,
            artifacts=[artifact],
            metadata=metadata,
        )
