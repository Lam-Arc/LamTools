from __future__ import annotations

import asyncio
import socket
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from lamtools_core.tool.command import (
    CommandExecution,
    detect_test_command,
    format_command_output,
    format_running_command_output,
    run_subprocess,
    validate_command_paths,
)
import lamtools_core.tool.command as command_module
import lamtools_core.tool.command_runner as command_runner
import lamtools_core.tool.command_tools as command_tools_module
from lamtools_core.tool import ToolCall
from lamtools_core.tool.command_tools import CommandToolHandlers, split_command_for_path_validation
from lamtools_core.runtime.background_processes import BackgroundProcessRegistry


def test_command_execution_defaults_are_tool_friendly():
    execution = CommandExecution(exit_code=0)

    assert execution.stdout == ""
    assert execution.stderr == ""
    assert execution.metadata == {}


@pytest.mark.parametrize("quoted_path", ["'../outside.txt'", '"../outside.txt"'])
def test_command_path_guard_rejects_quoted_parent_paths_in_strict_mode(
    tmp_path: Path, quoted_path: str
):
    """严格模式（allow_outside=False）保留越界拒绝，供仍需要边界的调用方使用。"""
    with pytest.raises(ValueError, match="escapes work_root"):
        validate_command_paths(["cat", quoted_path], tmp_path, allow_outside=False)


@pytest.mark.parametrize("quoted_path", ["'../outside.txt'", '"../outside.txt"'])
def test_command_path_guard_allows_quoted_parent_paths_by_default(
    tmp_path: Path, quoted_path: str
):
    """默认不再限制工作目录之外（2026-09-27 产品决定）。"""
    validate_command_paths(["cat", quoted_path], tmp_path)


def test_command_path_guard_allows_quoted_in_root_paths(tmp_path: Path):
    tokens = split_command_for_path_validation('cat "subdir/inside file.txt"')
    validate_command_paths(["shell", *tokens], tmp_path)


@pytest.mark.parametrize(
    "command",
    [
        'cat ./".."/../outside.txt',
        "cat ./ '..'/../outside.txt",
        'cat --output=".."/outside.txt',
        'Get-Content -LiteralPath ./".."/../outside.txt',
        'cat "../outside path.txt',
    ],
)
def test_command_path_guard_fails_closed_for_embedded_or_unmatched_quotes(
    tmp_path: Path, command: str,
):
    with pytest.raises(ValueError):
        tokens = split_command_for_path_validation(command)
        validate_command_paths(["shell", *tokens], tmp_path, allow_outside=False)


@pytest.mark.parametrize("shell_kind", ["wsl", "git-bash", "powershell", "pwsh"])
@pytest.mark.parametrize(
    "command",
    [
        'cat ./".."/../outside.txt',
        "cat ./ '..'/../outside.txt",
        'cat --output=".."/outside.txt',
        'Get-Content -LiteralPath ./".."/../outside.txt',
    ],
)
def test_shell_aware_path_validation_rejects_quote_concatenation(
    tmp_path: Path, shell_kind: str, command: str,
):
    with pytest.raises(ValueError):
        tokens = split_command_for_path_validation(command, shell_kind=shell_kind)
        validate_command_paths([shell_kind, *tokens], tmp_path, allow_outside=False)


@pytest.mark.parametrize("shell_kind", ["wsl", "git-bash", "powershell", "pwsh"])
@pytest.mark.parametrize("command", ['cat "core"/pyproject.toml', 'cat ./"core"/pyproject.toml'])
def test_shell_aware_path_validation_allows_in_root_quote_concatenation(
    tmp_path: Path, shell_kind: str, command: str,
):
    tokens = split_command_for_path_validation(command, shell_kind=shell_kind)
    validate_command_paths([shell_kind, *tokens], tmp_path)


@pytest.mark.parametrize("shell_kind", ["wsl", "git-bash", "powershell", "pwsh"])
def test_shell_aware_path_splitter_rejects_unmatched_quotes(shell_kind: str) -> None:
    with pytest.raises(ValueError):
        split_command_for_path_validation('cat "../outside path.txt', shell_kind=shell_kind)


# --- Reported Linux environment-probe command: quoting must not block it ---

# The command shape from the report: `;`/`|` compounds, balanced quotes in a
# regex, and absolute paths such as /etc/os-release.
PROBE_COMMAND = (
    "id; echo; hostname; uname -a; head -2 /etc/os-release; "
    'ip -4 addr show | grep -E "^[0-9]|inet "; ip route; df -h / | tail -1'
)
PATH_VALIDATION_SHELL_KINDS = ["wsl", "git-bash", "powershell", "pwsh"]
# Tokenizing a double-quoted absolute path whose value contains an apostrophe
# leaves a bare quote in the token; a PowerShell backtick-escaped quote does the
# same.  Both are resolvable by the executor's shell, so they are not invalid.
EMBEDDED_QUOTE_COMMAND = 'head -2 "/tmp/it\'s.txt"'
POWERSHELL_ESCAPED_QUOTE_COMMAND = 'head -2 "/etc/os`"release"'


@pytest.mark.parametrize("shell_kind", PATH_VALIDATION_SHELL_KINDS)
def test_reported_environment_probe_passes_without_boundary(
    shell_kind: str, tmp_path: Path
) -> None:
    """契约：不强制边界时，合法复合探查命令不得被引号检查拦下。"""
    tokens = split_command_for_path_validation(PROBE_COMMAND, shell_kind=shell_kind)
    validate_command_paths([shell_kind, *tokens], tmp_path)


@pytest.mark.parametrize("shell_kind", PATH_VALIDATION_SHELL_KINDS)
def test_embedded_quote_in_quoted_path_is_skipped_without_boundary(
    shell_kind: str, tmp_path: Path
) -> None:
    """契约：token 残留引号且无法静态消解时，不强制边界必须跳过而不是拒整条。

    旧实现在此无条件抛错（回归点）；下限断言保证 token 里确实还有引号，
    否则这条测试会空过。
    """
    tokens = split_command_for_path_validation(EMBEDDED_QUOTE_COMMAND, shell_kind=shell_kind)
    assert any("'" in token for token in tokens)

    validate_command_paths([shell_kind, *tokens], tmp_path)


@pytest.mark.parametrize("shell_kind", ["powershell", "pwsh"])
def test_powershell_escaped_quote_in_path_is_skipped_without_boundary(
    shell_kind: str, tmp_path: Path
) -> None:
    tokens = split_command_for_path_validation(
        POWERSHELL_ESCAPED_QUOTE_COMMAND, shell_kind=shell_kind
    )
    assert any('"' in token for token in tokens)

    validate_command_paths([shell_kind, *tokens], tmp_path)


@pytest.mark.parametrize("shell_kind", PATH_VALIDATION_SHELL_KINDS)
def test_embedded_quote_in_quoted_path_is_rejected_with_actionable_message_in_strict_mode(
    shell_kind: str, tmp_path: Path
) -> None:
    """契约：只有强制边界的调用方才硬拒绝，且提示说明原因与出路。"""
    tokens = split_command_for_path_validation(EMBEDDED_QUOTE_COMMAND, shell_kind=shell_kind)

    with pytest.raises(ValueError) as excinfo:
        validate_command_paths([shell_kind, *tokens], tmp_path, allow_outside=False)

    message = str(excinfo.value)
    assert "cannot be verified to stay inside the workspace" in message
    assert "consistent quoting" in message
    assert "split the command into separate calls" in message


@pytest.mark.parametrize("shell_kind", PATH_VALIDATION_SHELL_KINDS)
def test_unmatched_quote_reported_as_invalid_syntax_not_a_bounds_question(
    shell_kind: str,
) -> None:
    """真不平衡引号由执行器自己的分词器判为无效语法（fail closed）。

    选择「分词层拒绝」而非「边界层跳过」：执行器本来就会拒绝这种语法，
    在边界层再报一次只会给出与真实原因无关的越界/引号提示。
    """
    with pytest.raises(ValueError):
        split_command_for_path_validation('grep -E "^[0-9', shell_kind=shell_kind)


def test_permissive_bounds_check_skips_token_with_unmatched_quote(tmp_path: Path) -> None:
    validate_command_paths(["head", "-2", '/tmp/"broken'], tmp_path)


def test_strict_bounds_check_rejects_token_with_unmatched_quote(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="cannot be verified to stay inside the workspace"):
        validate_command_paths(["head", "-2", '/tmp/"broken'], tmp_path, allow_outside=False)


@pytest.mark.parametrize("shell_kind", PATH_VALIDATION_SHELL_KINDS)
@pytest.mark.parametrize("command", ['grep -E "^[0-9]|inet " sub/file.txt', "cat 'sub/file.txt'"])
def test_balanced_quoting_passes_even_in_strict_mode(
    shell_kind: str, command: str, tmp_path: Path
) -> None:
    """契约：成对引号（含正则里的 | 与 [0-9]）在强制边界下也必须通过。"""
    tokens = split_command_for_path_validation(command, shell_kind=shell_kind)

    validate_command_paths([shell_kind, *tokens], tmp_path, allow_outside=False)


@pytest.mark.parametrize("shell_kind", PATH_VALIDATION_SHELL_KINDS)
def test_reported_probe_outside_paths_still_rejected_in_strict_mode(
    shell_kind: str, tmp_path: Path
) -> None:
    """安全语义不变：强制边界的调用方仍拒绝真正越出工作区的绝对路径。"""
    tokens = split_command_for_path_validation(PROBE_COMMAND, shell_kind=shell_kind)

    with pytest.raises(ValueError, match="escapes work_root"):
        validate_command_paths([shell_kind, *tokens], tmp_path, allow_outside=False)


def test_windows_command_creationflags_hide_console(monkeypatch):
    monkeypatch.setattr(command_module.sys, "platform", "win32")
    monkeypatch.setattr(command_module.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, raising=False)
    monkeypatch.setattr(command_module.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)

    flags = command_module._windows_command_creationflags()

    assert flags & 0x200
    assert flags & 0x08000000


def test_windows_command_shell_prefers_git_bash(monkeypatch, tmp_path: Path):
    bash = tmp_path / "bash.exe"
    bash.write_text("", encoding="utf-8")
    monkeypatch.setattr(command_runner.sys, "platform", "win32")
    monkeypatch.setattr(command_runner, "_git_bash_path", lambda: bash)
    monkeypatch.delenv("LAMTOOLS_COMMAND_SHELL", raising=False)
    monkeypatch.setattr(command_runner, "_stored_shell_preference", lambda: "auto")
    monkeypatch.setattr(command_runner, "_wsl_available", lambda: True)

    shell = command_runner.resolve_command_shell()

    assert shell.name == "WSL"
    assert shell.kind == "wsl"


def test_windows_command_shell_honors_explicit_powershell(monkeypatch):
    monkeypatch.setattr(command_runner.sys, "platform", "win32")
    monkeypatch.setattr(command_runner, "_stored_shell_preference", lambda: None)
    monkeypatch.setattr(command_runner, "_wsl_available", lambda: False)
    monkeypatch.setenv("LAMTOOLS_COMMAND_SHELL", "powershell")

    shell = command_runner.resolve_command_shell()

    assert shell.name == "Windows PowerShell 5.1"
    assert shell.executable == "powershell.exe"
    assert "Windows PowerShell 5.1" in command_runner.command_shell_prompt()
    assert "powershell.exe" in command_runner.command_shell_prompt()


def test_windows_command_shell_falls_back_when_wsl_has_no_distro_or_git_bash(monkeypatch):
    monkeypatch.setattr(command_runner.sys, "platform", "win32")
    monkeypatch.setattr(command_runner, "_git_bash_path", lambda: None)
    monkeypatch.setattr(command_runner, "_stored_shell_preference", lambda: "auto")
    monkeypatch.setattr(command_runner, "_wsl_available", lambda: False)
    monkeypatch.setattr(command_runner.shutil, "which", lambda _name: None)
    monkeypatch.delenv("LAMTOOLS_COMMAND_SHELL", raising=False)

    shell = command_runner.resolve_command_shell()

    assert shell.name == "Windows PowerShell 5.1"


def test_wsl_probe_rejects_launcher_without_usable_default_distro(monkeypatch):
    monkeypatch.setattr(command_runner, "_wsl_path", lambda: "wsl.exe")
    monkeypatch.setattr(
        command_runner.subprocess,
        "run",
        lambda *_args, **_kwargs: command_runner.subprocess.CompletedProcess(
            args=["wsl.exe", "--exec", "bash", "-lc", "exit 0"], returncode=1, stdout=b"", stderr=b""
        ),
    )
    command_runner._wsl_available.cache_clear()
    try:
        assert command_runner._wsl_available() is False
    finally:
        command_runner._wsl_available.cache_clear()


def test_wsl_probe_bounds_a_hanging_default_distro(monkeypatch):
    captured: dict[str, object] = {}

    def hanging_probe(args, **kwargs):
        captured["args"] = args
        captured.update(kwargs)
        raise command_runner.subprocess.TimeoutExpired(args, kwargs["timeout"])

    monkeypatch.setattr(command_runner, "_wsl_path", lambda: "wsl.exe")
    monkeypatch.setattr(command_runner.subprocess, "run", hanging_probe)
    command_runner._wsl_available.cache_clear()
    try:
        assert command_runner._wsl_available() is False
        assert captured["timeout"] == 4
    finally:
        command_runner._wsl_available.cache_clear()


def test_saved_shell_preference_overrides_legacy_environment(monkeypatch, tmp_path: Path):
    bash = tmp_path / "bash.exe"
    bash.write_text("", encoding="utf-8")
    monkeypatch.setattr(command_runner.sys, "platform", "win32")
    monkeypatch.setenv("LAMTOOLS_COMMAND_SHELL", "powershell")
    monkeypatch.setattr(command_runner, "_git_bash_path", lambda: bash)
    monkeypatch.setattr(command_runner, "_wsl_available", lambda: False)
    monkeypatch.setattr(command_runner, "_stored_shell_preference", lambda: "git-bash")
    assert command_runner.resolve_command_shell().kind == "git-bash"


def test_windows_command_shell_auto_prefers_wsl_then_git_bash(monkeypatch, tmp_path: Path):
    bash = tmp_path / "bash.exe"
    bash.write_text("", encoding="utf-8")
    monkeypatch.setattr(command_runner.sys, "platform", "win32")
    monkeypatch.setattr(command_runner, "_stored_shell_preference", lambda: "auto")
    monkeypatch.setattr(command_runner, "_wsl_available", lambda: True)
    monkeypatch.setattr(command_runner, "_wsl_path", lambda: "wsl.exe")
    monkeypatch.setattr(command_runner, "_git_bash_path", lambda: bash)
    assert command_runner.resolve_command_shell().kind == "wsl"

    monkeypatch.setattr(command_runner, "_wsl_available", lambda: False)
    shell = command_runner.resolve_command_shell()
    assert shell.kind == "git-bash"
    assert shell.argv("pwd && ls") == [str(bash), "--noprofile", "--norc", "-lc", "pwd && ls"]


def test_manual_unavailable_shell_falls_back_to_auto(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(command_runner.sys, "platform", "win32")
    monkeypatch.setattr(command_runner, "_stored_shell_preference", lambda: "wsl")
    monkeypatch.setattr(command_runner, "_wsl_available", lambda: False)
    bash = tmp_path / "bash.exe"
    bash.write_text("", encoding="utf-8")
    monkeypatch.setattr(command_runner, "_git_bash_path", lambda: bash)
    assert command_runner.resolve_command_shell().kind == "git-bash"


def test_wsl_command_argv_cwd_and_env_preserve_linux_path(monkeypatch, tmp_path: Path):
    shell = command_runner.CommandShell(name="WSL", executable="wsl.exe", kind="wsl")
    assert shell.argv_for("printf '%s' \"one arg\"", cwd=tmp_path) == [
        "wsl.exe", "--cd", str(tmp_path), "--exec", "bash", "-lc", "printf '%s' \"one arg\"",
    ]
    env = shell.prepare_environment(
        {"PATH": r"C:\Windows", "TOKEN": "value", "WSLENV": "PATH/p:OLD"},
        forward_names={"TOKEN"},
    )
    assert env is not None
    assert env["WSLENV"] == "OLD:TOKEN"


def test_warm_command_shell_pays_the_probe_once_before_the_first_request(monkeypatch):
    """The bounded WSL probe must not be deferred to the first model request."""
    probes: list[list[str]] = []

    def fake_run(args, **_kwargs):
        probes.append(list(args))
        return command_runner.subprocess.CompletedProcess(
            args=args, returncode=0, stdout=b"", stderr=b""
        )

    monkeypatch.setattr(command_runner.sys, "platform", "win32")
    monkeypatch.setattr(command_runner, "_stored_shell_preference", lambda: "auto")
    monkeypatch.setattr(command_runner, "_git_bash_path", lambda: None)
    monkeypatch.setattr(command_runner, "_wsl_path", lambda: "wsl.exe")
    monkeypatch.setattr(command_runner.subprocess, "run", fake_run)
    command_runner._wsl_available.cache_clear()
    try:
        assert command_runner.warm_command_shell().kind == "wsl"
        assert len(probes) == 1

        # The model-request path reuses the cached start-up decision.
        assert "Current shell: WSL" in command_runner.command_shell_prompt()
        assert len(probes) == 1
    finally:
        command_runner._wsl_available.cache_clear()


@pytest.mark.asyncio
async def test_run_command_uses_resolved_shell_and_reports_it(monkeypatch, tmp_path: Path):
    shell = command_runner.CommandShell(
        name="Git Bash",
        executable=r"C:\Program Files\Git\bin\bash.exe",
        kind="git-bash",
    )
    captured: dict[str, object] = {}

    async def fake_run(argv, **_kwargs):
        captured["argv"] = argv
        return CommandExecution(exit_code=0, stdout="ok\n")

    monkeypatch.setattr(command_tools_module.sys, "platform", "win32")
    monkeypatch.setattr(command_tools_module, "resolve_command_shell", lambda: shell)
    monkeypatch.setattr(command_tools_module, "_run_subprocess", fake_run)
    handlers = CommandToolHandlers(
        work_root=tmp_path,
        command_timeout=10,
        loaded_skill_roots=set(),
    )

    result = await handlers.run_command(
        ToolCall(id="shell-call", name="run_command", arguments={"command": "pwd && ls"})
    )

    assert result.status == "ok"
    assert captured["argv"] == [
        shell.executable,
        "--noprofile",
        "--norc",
        "-lc",
        "pwd && ls",
    ]
    assert result.metadata["shell"] == "Git Bash"
    assert result.metadata["shell_executable"] == shell.executable
    assert result.metadata["process_state"] == "exited"
    assert result.metadata["shell_state"] == "exited"
    assert result.metadata["readiness_state"] == "not_requested"
    assert "[process_state: exited]" in result.content


@pytest.mark.asyncio
@pytest.mark.parametrize("command", [PROBE_COMMAND, EMBEDDED_QUOTE_COMMAND])
async def test_run_command_accepts_reported_probe_and_embedded_quote_paths(
    monkeypatch, tmp_path: Path, command: str
):
    """端到端回归：默认（不强制边界）下这两条命令都不得被预检拒绝（旧实现拒整条）。"""
    shell = command_runner.CommandShell(
        name="Git Bash",
        executable=r"C:\Program Files\Git\bin\bash.exe",
        kind="git-bash",
    )
    captured: dict[str, object] = {}

    async def fake_run(argv, **_kwargs):
        captured["argv"] = argv
        return CommandExecution(exit_code=0, stdout="ok\n")

    monkeypatch.setattr(command_tools_module.sys, "platform", "win32")
    monkeypatch.setattr(command_tools_module, "resolve_command_shell", lambda: shell)
    monkeypatch.setattr(command_tools_module, "_run_subprocess", fake_run)
    handlers = CommandToolHandlers(
        work_root=tmp_path,
        command_timeout=10,
        loaded_skill_roots=set(),
    )

    result = await handlers.run_command(
        ToolCall(id="probe", name="run_command", arguments={"command": command})
    )

    assert result.status == "ok", result.error
    assert captured["argv"] == [shell.executable, "--noprofile", "--norc", "-lc", command]


@pytest.mark.asyncio
async def test_run_command_reports_actionable_message_for_unmatched_quote(
    monkeypatch, tmp_path: Path
):
    """契约：真不平衡引号仍会失败，但提示必须给出下一步（改引号或拆命令）。"""
    shell = command_runner.CommandShell(
        name="Git Bash",
        executable=r"C:\Program Files\Git\bin\bash.exe",
        kind="git-bash",
    )
    monkeypatch.setattr(command_tools_module.sys, "platform", "win32")
    monkeypatch.setattr(command_tools_module, "resolve_command_shell", lambda: shell)
    handlers = CommandToolHandlers(
        work_root=tmp_path,
        command_timeout=10,
        loaded_skill_roots=set(),
    )

    result = await handlers.run_command(
        ToolCall(id="bad-quote", name="run_command", arguments={"command": 'grep -E "^[0-9'})
    )

    assert result.status == "failed"
    assert "Invalid command syntax" in (result.error or "")
    assert "consistent quoting" in (result.error or "")
    assert "split the command into separate calls" in (result.error or "")


@pytest.mark.asyncio
async def test_run_command_does_not_forward_windows_environment_to_wsl(monkeypatch, tmp_path: Path):
    shell = command_runner.CommandShell(name="WSL", executable="wsl.exe", kind="wsl")
    captured: dict[str, object] = {}

    async def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured.update(kwargs)
        return CommandExecution(exit_code=0, stdout="ok\n")

    monkeypatch.setattr(command_tools_module.sys, "platform", "win32")
    monkeypatch.setattr(command_tools_module, "resolve_command_shell", lambda: shell)
    monkeypatch.setattr(command_tools_module, "_run_subprocess", fake_run)
    monkeypatch.setenv("SHELL_TEST_VALUE", "secret-value")
    monkeypatch.setenv("WSLENV", "USER_EXISTING/p:PATH/p")
    handlers = CommandToolHandlers(
        work_root=tmp_path,
        command_timeout=10,
        loaded_skill_roots=set(),
    )

    result = await handlers.run_command(
        ToolCall(id="wsl-call", name="run_command", arguments={"command": "printf '%s' \"$SHELL_TEST_VALUE\""})
    )

    assert result.status == "ok"
    assert captured["argv"] == [
        "wsl.exe", "--cd", str(tmp_path), "--exec", "bash", "-lc",
        "printf '%s' \"$SHELL_TEST_VALUE\"",
    ]
    assert captured["env"] is None


@pytest.mark.asyncio
async def test_python_http_server_is_inferred_as_background_and_probes_served_directory(
    monkeypatch,
    tmp_path: Path,
):
    site = tmp_path / "site"
    site.mkdir()
    captured: dict[str, object] = {}

    async def fake_background(argv, **kwargs):
        captured["argv"] = argv
        captured["http_probe"] = kwargs["http_probe"]
        return CommandExecution(
            exit_code=0,
            background=True,
            stdout="Background process started (pid 4321).",
            metadata={"pid": 4321, "server_probe_url": kwargs["http_probe"].url},
        )

    monkeypatch.setattr(command_tools_module, "_run_background_subprocess", fake_background)
    handlers = CommandToolHandlers(
        work_root=tmp_path,
        command_timeout=2,
        loaded_skill_roots=set(),
    )

    result = await handlers.run_command(ToolCall(
        id="server-call",
        name="run_command",
        arguments={"command": "python -m http.server 8765 --directory site"},
    ))

    probe = captured["http_probe"]
    assert probe is not None
    assert probe.file_path is not None
    assert probe.file_path.parent == site
    assert result.status == "ok"
    assert result.metadata["background_requested"] is False
    assert result.metadata["background_inferred"] is True
    assert result.metadata["process_state"] == "running"
    assert result.metadata["shell_state"] == "running"
    assert result.metadata["readiness_state"] == "ready"
    assert "[readiness_state: ready]" in result.content
    assert "[background_requested: false]" in result.content
    assert "[background_inferred: true]" in result.content


@pytest.mark.asyncio
async def test_python_http_server_lifecycle_contract_with_real_process(tmp_path: Path, monkeypatch):
    # This readiness contract serves a Windows-created temp directory and
    # probes IPv4 loopback; keep both the shell and bind address deterministic.
    monkeypatch.setenv("LAMTOOLS_COMMAND_SHELL", "git-bash")
    monkeypatch.setattr(command_runner, "_stored_shell_preference", lambda: None)
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("ready from served directory", encoding="utf-8")
    with socket.socket() as free_socket:
        free_socket.bind(("127.0.0.1", 0))
        port = int(free_socket.getsockname()[1])

    registry = BackgroundProcessRegistry()
    handlers = CommandToolHandlers(
        work_root=tmp_path,
        command_timeout=4,
        loaded_skill_roots=set(),
        background_process_registry=registry,
    )
    result = await handlers.run_command(ToolCall(
        id="real-server-call",
        name="run_command",
        arguments={"command": f"python -m http.server {port} --bind 127.0.0.1 --directory site"},
        metadata={"_runtime_session_id": "server-test", "_runtime_run_id": "turn-test"},
    ))
    try:
        assert result.status == "ok", f"{result.error}; metadata={result.metadata}"
        assert result.metadata["process_state"] == "running"
        assert result.metadata["shell_state"] == "running"
        assert result.metadata["readiness_state"] == "ready"
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2) as response:
            assert "ready from served directory" in response.read().decode("utf-8")
    finally:
        registry.cleanup_run("server-test", "turn-test")

    assert registry.list() == []


def test_format_command_output_keeps_stdout_and_stderr_separate():
    output = format_command_output("out\n", "err\n", 2, "pytest")

    assert "[command] pytest" in output
    assert "[exit_code: 2]" in output
    assert "[stdout]\nout" in output
    assert "[stderr]\nerr" in output


def test_format_command_output_truncates_long_output():
    output = format_command_output("abcdef", "", 0, "echo", max_length=24)

    assert output.endswith("[... output truncated]")


def test_format_running_command_output_marks_status():
    output = format_running_command_output("", "", "npm test")

    assert "[status: running]" in output
    assert "[no output yet]" in output


def test_validate_command_paths_allows_workspace_paths(tmp_path: Path):
    validate_command_paths(["py", "-m", "pytest", "tests/"], tmp_path)


def test_validate_command_paths_blocks_escape_in_strict_mode(tmp_path: Path):
    with pytest.raises(ValueError, match="escapes work_root"):
        validate_command_paths(["py", "-m", "pytest", "../outside"], tmp_path, allow_outside=False)


def test_validate_command_paths_allows_escape_by_default(tmp_path: Path):
    validate_command_paths(["py", "-m", "pytest", "../outside"], tmp_path)


def test_validate_command_paths_allows_escape_when_outside_access_is_enabled(tmp_path: Path):
    validate_command_paths(
        ["py", "-m", "pytest", "../outside"],
        tmp_path,
        allow_outside=True,
    )


def test_validate_command_paths_allows_resource_roots(tmp_path: Path):
    skill_root = tmp_path.parent / "skill-root"
    script = skill_root / "scripts" / "check.py"
    script.parent.mkdir(parents=True)
    script.write_text("print('ok')\n", encoding="utf-8")

    with pytest.raises(ValueError, match="escapes work_root"):
        validate_command_paths(["py", str(script)], tmp_path, allow_outside=False)

    validate_command_paths(["py", str(script)], tmp_path, (skill_root,))


def test_detect_test_command_prefers_package_test_script(tmp_path: Path):
    (tmp_path / "package.json").write_text('{"scripts":{"test":"vitest run","build":"vite build"}}', encoding="utf-8")

    assert detect_test_command(tmp_path) == "npm test"


def test_detect_test_command_uses_python_project_markers(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")

    assert "pytest" in detect_test_command(tmp_path)


@pytest.mark.asyncio
async def test_run_subprocess_returns_output(tmp_path: Path):
    result = await run_subprocess(
        [sys.executable, "-c", "print('core-command-ok')"],
        cwd=tmp_path,
        timeout=10,
    )

    assert result.exit_code == 0
    assert result.stdout.strip() == "core-command-ok"
    assert not result.timed_out


@pytest.mark.asyncio
async def test_run_subprocess_reports_timeout(tmp_path: Path):
    result = await run_subprocess(
        [sys.executable, "-c", "import time; time.sleep(5)"],
        cwd=tmp_path,
        timeout=1,
    )

    assert result.exit_code == -1
    assert result.timed_out
    assert result.error_type == "TimeoutExpired"


@pytest.mark.asyncio
async def test_run_subprocess_cancellation_terminates_child(tmp_path: Path):
    marker = tmp_path / "finished.txt"
    script = (
        "import pathlib, time; "
        "time.sleep(5); "
        f"pathlib.Path({str(marker)!r}).write_text('done', encoding='utf-8')"
    )
    task = asyncio.create_task(
        run_subprocess([sys.executable, "-c", script], cwd=tmp_path, timeout=30)
    )

    await asyncio.sleep(0.3)
    started_at = time.monotonic()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert time.monotonic() - started_at < 3
    await asyncio.sleep(1)
    assert not marker.exists()


@pytest.mark.asyncio
async def test_run_command_persistent_flag_reaches_background_runner(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    captured: dict[str, object] = {}

    async def fake_background(argv, **kwargs):
        captured.update(kwargs)
        return CommandExecution(
            exit_code=0,
            background=True,
            metadata={"pid": 321, "stdout_log": "out.log", "stderr_log": "err.log", "persistent": True},
        )

    monkeypatch.setattr(command_tools_module.sys, "platform", "linux")
    monkeypatch.setattr(command_tools_module, "_run_background_subprocess", fake_background)
    handlers = CommandToolHandlers(
        work_root=tmp_path,
        command_timeout=10,
        loaded_skill_roots=set(),
        background_process_registry=BackgroundProcessRegistry(),
    )

    result = await handlers.run_command(
        ToolCall(
            id="call-persistent",
            name="run_command",
            arguments={"command": "python sleep fixture", "persistent": True},
            metadata={"_runtime_session_id": "session-1", "_runtime_run_id": "run-1"},
        )
    )

    assert result.status == "ok"
    assert captured["persistent"] is True
    assert result.metadata["persistent"] is True
    assert "[persistent: true]" in (result.content or "")


@pytest.mark.asyncio
async def test_list_and_kill_process_tools_are_session_scoped(tmp_path: Path):
    registry = BackgroundProcessRegistry()
    handlers = CommandToolHandlers(
        work_root=tmp_path,
        command_timeout=10,
        loaded_skill_roots=set(),
        background_process_registry=registry,
    )
    registry.register(
        _RegisteredFakeProcess(654),
        session_id="session-1",
        run_id="run-1",
        work_root=tmp_path,
        persistent=True,
        command="python -m http.server 8123",
    )

    listed = await handlers.list_processes(
        ToolCall(id="list-1", name="list_processes", arguments={}, metadata={"_runtime_session_id": "session-1"})
    )
    assert listed.status == "ok"
    assert "pid 654" in (listed.content or "")
    assert "persistent" in (listed.content or "")
    assert listed.metadata["processes"][0]["pid"] == 654

    foreign = await handlers.list_processes(
        ToolCall(id="list-2", name="list_processes", arguments={}, metadata={"_runtime_session_id": "session-2"})
    )
    assert foreign.metadata["processes"] == []

    wrong_session = await handlers.kill_process(
        ToolCall(id="kill-1", name="kill_process", arguments={"pid": 654}, metadata={"_runtime_session_id": "session-2"})
    )
    assert wrong_session.status == "failed"
    assert "No registered background process" in (wrong_session.error or "")

    killed = await handlers.kill_process(
        ToolCall(id="kill-2", name="kill_process", arguments={"pid": 654}, metadata={"_runtime_session_id": "session-1"})
    )
    assert killed.status == "ok"
    assert killed.metadata["terminated"] is True
    assert registry.list() == []


class _RegisteredFakeProcess:
    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode


@pytest.mark.asyncio
@pytest.mark.parametrize("placeholder", ["null", "NULL", "None", "undefined", " n/a "])
async def test_run_command_treats_placeholder_readiness_args_as_unset(
    monkeypatch, tmp_path: Path, placeholder: str
):
    """模型把用不上的可选参数填成占位串时，前台命令必须照常执行。"""
    shell = command_runner.CommandShell(
        name="Git Bash",
        executable=r"C:\Program Files\Git\bin\bash.exe",
        kind="git-bash",
    )

    async def fake_run(argv, **_kwargs):
        return CommandExecution(exit_code=0, stdout="ok\n")

    monkeypatch.setattr(command_tools_module.sys, "platform", "win32")
    monkeypatch.setattr(command_tools_module, "resolve_command_shell", lambda: shell)
    monkeypatch.setattr(command_tools_module, "_run_subprocess", fake_run)
    handlers = CommandToolHandlers(
        work_root=tmp_path,
        command_timeout=10,
        loaded_skill_roots=set(),
    )

    result = await handlers.run_command(
        ToolCall(
            id="placeholder-readiness",
            name="run_command",
            arguments={
                "command": "ls -la",
                "background": False,
                "readiness_url": placeholder,
                "readiness_text": placeholder,
            },
        )
    )

    assert result.status == "ok"
    assert result.metadata["readiness_state"] == "not_requested"
    assert "readiness_url" not in result.metadata


@pytest.mark.asyncio
async def test_run_command_real_readiness_url_still_requires_background(tmp_path: Path):
    """真正的探活地址仍然只能配后台进程，不被占位串处理放过。"""
    handlers = CommandToolHandlers(
        work_root=tmp_path,
        command_timeout=10,
        loaded_skill_roots=set(),
    )

    result = await handlers.run_command(
        ToolCall(
            id="readiness-without-background",
            name="run_command",
            arguments={"command": "ls -la", "readiness_url": "http://127.0.0.1:8000"},
        )
    )

    assert result.status == "failed"
    assert result.error == "'readiness_url' requires background=true"
