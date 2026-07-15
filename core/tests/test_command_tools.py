from __future__ import annotations

import asyncio
import sys
import time
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
from lamtools_core.tool.command_tools import CommandToolHandlers


def test_command_execution_defaults_are_tool_friendly():
    execution = CommandExecution(exit_code=0)

    assert execution.stdout == ""
    assert execution.stderr == ""
    assert execution.metadata == {}


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

    shell = command_runner.resolve_command_shell()

    assert shell.name == "Git Bash"
    assert shell.argv("pwd && ls") == [
        str(bash),
        "--noprofile",
        "--norc",
        "-lc",
        "pwd && ls",
    ]


def test_windows_command_shell_honors_explicit_powershell(monkeypatch):
    monkeypatch.setattr(command_runner.sys, "platform", "win32")
    monkeypatch.setenv("LAMTOOLS_COMMAND_SHELL", "powershell")

    shell = command_runner.resolve_command_shell()

    assert shell.name == "Windows PowerShell 5.1"
    assert shell.executable == "powershell.exe"
    assert "Windows PowerShell 5.1" in command_runner.command_shell_prompt()
    assert "&&" in command_runner.command_shell_prompt()


def test_windows_command_shell_falls_back_when_git_bash_is_missing(monkeypatch):
    monkeypatch.setattr(command_runner.sys, "platform", "win32")
    monkeypatch.setattr(command_runner, "_git_bash_path", lambda: None)
    monkeypatch.setattr(command_runner.shutil, "which", lambda _name: None)
    monkeypatch.delenv("LAMTOOLS_COMMAND_SHELL", raising=False)

    shell = command_runner.resolve_command_shell()

    assert shell.name == "Windows PowerShell 5.1"


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


def test_validate_command_paths_blocks_escape(tmp_path: Path):
    with pytest.raises(ValueError, match="escapes work_root"):
        validate_command_paths(["py", "-m", "pytest", "../outside"], tmp_path)


def test_validate_command_paths_allows_resource_roots(tmp_path: Path):
    skill_root = tmp_path.parent / "skill-root"
    script = skill_root / "scripts" / "check.py"
    script.parent.mkdir(parents=True)
    script.write_text("print('ok')\n", encoding="utf-8")

    with pytest.raises(ValueError, match="escapes work_root"):
        validate_command_paths(["py", str(script)], tmp_path)

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
