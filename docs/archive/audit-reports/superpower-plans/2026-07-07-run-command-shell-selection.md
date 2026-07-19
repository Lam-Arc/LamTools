# run_command Shell Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Windows `run_command` prefer Git Bash, fall back to UTF-8 PowerShell only when appropriate, and keep Writer on the shared Core command path.

**Architecture:** Core owns shell selection and command execution metadata. Writer keeps using Core command handlers and only updates the Windows platform prompt so the model does not keep preferring PowerShell after the runtime default changes.

**Tech Stack:** Python 3.14, pytest, LamTools Core command tooling, Writer backend prompt resources.

## Global Constraints

- Keep implementation in `core/src/lamtools_core/tool/command_runner.py` and `core/src/lamtools_core/tool/command_tools.py`; do not create a Writer-specific command path.
- Use Git Bash by default on Windows when available.
- Use PowerShell fallback only for unavailable/start-failed Git Bash or clearly PowerShell-specific commands.
- Do not retry a Git Bash command in PowerShell when Git Bash returns a nonzero exit code.
- PowerShell fallback must set UTF-8 input, output, and pipeline encoding before running the user command.
- Preserve existing `ToolResult` content/artifact shape; add only diagnostic metadata.
- Stage and commit only files touched by this task.

---

## File Structure

- Modify `core/src/lamtools_core/tool/command_runner.py`: Git Bash resolver, PowerShell syntax detection, shell argv builders, UTF-8 PowerShell wrapper.
- Modify `core/src/lamtools_core/tool/command_tools.py`: call the Core shell resolver, attach shell metadata, retry only Git Bash start failures through PowerShell.
- Modify `core/tests/test_command_tools.py`: unit tests for resolver, syntax detection, and UTF-8 wrapper text.
- Modify `members/writer/backend/tests/test_writer_core_kernel_adapter.py`: integration tests through `ReadWriteToolExecutor`.
- Modify `members/writer/backend/tests/test_prompt_assembler.py`: prompt contract test for Windows shell guidance.
- Modify `members/writer/backend/app/prompts/writer/platform_windows.md`: align user-facing model guidance with the runtime default.

---

### Task 1: Core Shell Resolver

**Files:**
- Modify: `core/tests/test_command_tools.py`
- Modify: `core/src/lamtools_core/tool/command_runner.py`

**Interfaces:**
- Produces: `_resolve_windows_git_bash_path(env=None, candidates=None, path_lookup=None) -> Path | None`
- Produces: `_looks_like_windows_powershell_command(command: str) -> bool`
- Produces: `_windows_git_bash_argv(path: Path, command: str) -> list[str]`
- Updates: `_windows_shell_argv(command: str) -> list[str>` so it sets UTF-8 in the PowerShell wrapper.

- [ ] **Step 1: Write failing resolver and wrapper tests**

Add these imports to `core/tests/test_command_tools.py`:

```python
from lamtools_core.tool.command_runner import (
    _looks_like_windows_powershell_command,
    _resolve_windows_git_bash_path,
    _windows_git_bash_argv,
    _windows_shell_argv,
)
```

Add these tests to `core/tests/test_command_tools.py`:

```python
def _touch_executable_placeholder(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return path


def test_resolve_windows_git_bash_path_prefers_candidate_over_wsl(tmp_path: Path):
    git_bash = _touch_executable_placeholder(tmp_path / "Git" / "bin" / "bash.exe")
    wsl_bash = _touch_executable_placeholder(tmp_path / "Windows" / "System32" / "bash.exe")

    result = _resolve_windows_git_bash_path(
        env={},
        candidates=(git_bash,),
        path_lookup=lambda _name: str(wsl_bash),
    )

    assert result == git_bash


def test_resolve_windows_git_bash_path_uses_valid_env_override(tmp_path: Path):
    env_bash = _touch_executable_placeholder(tmp_path / "CustomGit" / "bin" / "bash.exe")
    default_bash = _touch_executable_placeholder(tmp_path / "Git" / "bin" / "bash.exe")

    result = _resolve_windows_git_bash_path(
        env={"LAMTOOLS_GIT_BASH_PATH": str(env_bash)},
        candidates=(default_bash,),
        path_lookup=lambda _name: None,
    )

    assert result == env_bash


def test_resolve_windows_git_bash_path_rejects_wsl_path_hit(tmp_path: Path):
    wsl_bash = _touch_executable_placeholder(tmp_path / "Windows" / "System32" / "bash.exe")

    result = _resolve_windows_git_bash_path(
        env={},
        candidates=(),
        path_lookup=lambda _name: str(wsl_bash),
    )

    assert result is None


@pytest.mark.parametrize(
    "command",
    [
        "Get-ChildItem -Recurse -File | Select-Object -First 1",
        "powershell -NoProfile -Command Get-Date",
        "pwsh -NoProfile -Command Get-Date",
        "echo hi | Where-Object { $_ }",
        "Write-Output '中文-OK'",
    ],
)
def test_windows_powershell_syntax_is_detected(command: str):
    assert _looks_like_windows_powershell_command(command)


@pytest.mark.parametrize(
    "command",
    [
        "printf 'hello'",
        "git status --short",
        "python -m pytest",
        "npm test",
    ],
)
def test_bash_or_plain_commands_are_not_detected_as_powershell(command: str):
    assert not _looks_like_windows_powershell_command(command)


def test_windows_git_bash_argv_uses_login_command_mode(tmp_path: Path):
    git_bash = tmp_path / "Git" / "bin" / "bash.exe"

    assert _windows_git_bash_argv(git_bash, "printf 'ok'") == [
        str(git_bash),
        "-lc",
        "printf 'ok'",
    ]


def test_windows_powershell_wrapper_sets_utf8_encoding():
    argv = _windows_shell_argv("Write-Output '中文-OK'")
    script = argv[-1]

    assert argv[:4] == [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
    ]
    assert "[Console]::InputEncoding = $__lamtools_utf8" in script
    assert "[Console]::OutputEncoding = $__lamtools_utf8" in script
    assert "$OutputEncoding = $__lamtools_utf8" in script
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
py -3.14 -m pytest core/tests/test_command_tools.py -q
```

Expected: FAIL because `_resolve_windows_git_bash_path`, `_looks_like_windows_powershell_command`, and `_windows_git_bash_argv` do not exist, and the PowerShell wrapper does not set UTF-8.

- [ ] **Step 3: Implement resolver helpers and UTF-8 PowerShell wrapper**

In `core/src/lamtools_core/tool/command_runner.py`, add imports:

```python
import os
import shutil
from collections.abc import Callable, Mapping
```

Add this block immediately before `_normalize_windows_shell_command`:

```python
_DEFAULT_WINDOWS_GIT_BASH_CANDIDATES = (
    Path("C:/Program Files/Git/bin/bash.exe"),
    Path("C:/Program Files/Git/usr/bin/bash.exe"),
)

_WINDOWS_POWERSHELL_COMMAND_PATTERN = re.compile(
    r"\b(?:"
    r"Get-ChildItem|Select-Object|Where-Object|ForEach-Object|"
    r"Write-Output|Write-Error|Out-String|Out-File|"
    r"Get-Content|Set-Content|Add-Content|"
    r"New-Item|Remove-Item|Copy-Item|Move-Item|"
    r"Test-Path|Join-Path"
    r")\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _WindowsCommandShell:
    argv: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)


def _is_git_for_windows_bash_path(path: Path) -> bool:
    normalized = path.as_posix().lower()
    return (
        path.name.lower() == "bash.exe"
        and "/git/" in normalized
        and "/windows/system32/" not in normalized
        and "/windowsapps/" not in normalized
    )


def _resolve_windows_git_bash_path(
    env: Mapping[str, str] | None = None,
    *,
    candidates: tuple[Path, ...] | None = None,
    path_lookup: Callable[[str], str | None] | None = None,
) -> Path | None:
    env_map = os.environ if env is None else env
    env_value = (env_map.get("LAMTOOLS_GIT_BASH_PATH") or "").strip()
    if env_value:
        env_path = Path(env_value)
        if env_path.is_file():
            return env_path

    for candidate in _DEFAULT_WINDOWS_GIT_BASH_CANDIDATES if candidates is None else candidates:
        if candidate.is_file():
            return candidate

    lookup = shutil.which if path_lookup is None else path_lookup
    for executable in ("bash.exe", "bash"):
        found = lookup(executable)
        if not found:
            continue
        path = Path(found)
        if _is_git_for_windows_bash_path(path):
            return path
    return None


def _looks_like_windows_powershell_command(command: str) -> bool:
    stripped = command.strip()
    lowered = stripped.lower()
    if re.match(r"^(?:powershell(?:\.exe)?|pwsh(?:\.exe)?)\b", lowered):
        return True
    return bool(_WINDOWS_POWERSHELL_COMMAND_PATTERN.search(stripped))


def _windows_git_bash_argv(path: Path, command: str) -> list[str]:
    return [str(path), "-lc", command]
```

Update `_windows_shell_argv()` so `wrapped` starts with this UTF-8 preamble:

```python
def _windows_shell_argv(command: str) -> list[str]:
    wrapped = (
        "$__lamtools_utf8 = [System.Text.UTF8Encoding]::new($false); "
        "[Console]::InputEncoding = $__lamtools_utf8; "
        "[Console]::OutputEncoding = $__lamtools_utf8; "
        "$OutputEncoding = $__lamtools_utf8; "
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
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        wrapped,
    ]
```

- [ ] **Step 4: Run resolver tests to verify they pass**

Run:

```powershell
py -3.14 -m pytest core/tests/test_command_tools.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

```powershell
git add core/src/lamtools_core/tool/command_runner.py core/tests/test_command_tools.py
git commit -m "feat(core): resolve Windows command shells"
```

---

### Task 2: Runtime Shell Selection and Metadata

**Files:**
- Modify: `core/src/lamtools_core/tool/command_runner.py`
- Modify: `core/src/lamtools_core/tool/command_tools.py`
- Modify: `members/writer/backend/tests/test_writer_core_kernel_adapter.py`

**Interfaces:**
- Produces: `_windows_command_shell(command: str) -> _WindowsCommandShell`
- Produces: `_windows_powershell_command_shell(command: str, *, reason: str) -> _WindowsCommandShell`
- Consumes: `_WindowsCommandShell.argv` and `_WindowsCommandShell.metadata`
- Adds metadata keys on command results: `shell`, `shell_path`, `shell_reason`

- [ ] **Step 1: Write failing Writer integration tests**

In `members/writer/backend/tests/test_writer_core_kernel_adapter.py`, add this helper near the existing run command tests:

```python
def _require_windows_git_bash() -> None:
    if sys.platform != "win32":
        pytest.skip("Windows-specific shell diagnostic")
    if not any(
        path.is_file()
        for path in (
            Path("C:/Program Files/Git/bin/bash.exe"),
            Path("C:/Program Files/Git/usr/bin/bash.exe"),
        )
    ):
        pytest.skip("Git Bash is not installed")
```

Add these tests to the existing run command test area:

```python
@pytest.mark.asyncio
async def test_run_command_windows_defaults_to_git_bash(self, tmp_path):
    _require_windows_git_bash()

    work_root = tmp_path / "project"
    work_root.mkdir()
    executor = ReadWriteToolExecutor(work_root)
    result = await executor.run_command(
        ToolCall(
            id="tc-rt-win-git-bash-default",
            name="run_command",
            arguments={"command": "printf 'bash-default-ok'", "timeout": 30},
        )
    )

    assert result.status == "ok"
    assert result.metadata["exit_code"] == 0
    assert result.metadata["shell"] == "git_bash"
    assert result.metadata["shell_reason"] == "default"
    assert str(result.metadata["shell_path"]).lower().endswith("bash.exe")
    assert "bash-default-ok" in result.content


@pytest.mark.asyncio
async def test_run_command_windows_powershell_syntax_uses_powershell_fallback(self, tmp_path):
    if sys.platform != "win32":
        pytest.skip("Windows-specific shell diagnostic")

    work_root = tmp_path / "project"
    work_root.mkdir()
    (work_root / "note.txt").write_text("ok", encoding="utf-8")
    executor = ReadWriteToolExecutor(work_root)
    result = await executor.run_command(
        ToolCall(
            id="tc-rt-win-powershell-fallback",
            name="run_command",
            arguments={"command": "Get-ChildItem -Recurse -File | Select-Object -First 1", "timeout": 30},
        )
    )

    assert result.status == "ok"
    assert result.metadata["exit_code"] == 0
    assert result.metadata["shell"] == "powershell"
    assert result.metadata["shell_reason"] == "powershell_syntax"


@pytest.mark.asyncio
async def test_run_command_windows_powershell_utf8_output_is_readable(self, tmp_path):
    if sys.platform != "win32":
        pytest.skip("Windows-specific shell diagnostic")

    work_root = tmp_path / "project"
    work_root.mkdir()
    executor = ReadWriteToolExecutor(work_root)
    result = await executor.run_command(
        ToolCall(
            id="tc-rt-win-powershell-utf8",
            name="run_command",
            arguments={"command": "Write-Output '中文-OK'", "timeout": 30},
        )
    )

    assert result.status == "ok"
    assert result.metadata["shell"] == "powershell"
    assert result.metadata["shell_reason"] == "powershell_syntax"
    assert "中文-OK" in result.content


@pytest.mark.asyncio
async def test_run_command_windows_git_bash_nonzero_is_not_retried_in_powershell(self, tmp_path):
    _require_windows_git_bash()

    work_root = tmp_path / "project"
    work_root.mkdir()
    executor = ReadWriteToolExecutor(work_root)
    result = await executor.run_command(
        ToolCall(
            id="tc-rt-win-git-bash-nonzero",
            name="run_command",
            arguments={"command": "printf 'bash-failed'; exit 7", "timeout": 30},
        )
    )

    assert result.status == "failed"
    assert result.metadata["exit_code"] == 7
    assert result.metadata["shell"] == "git_bash"
    assert result.metadata["shell_reason"] == "default"
    assert "bash-failed" in result.content
```

Update the existing `test_run_command_windows_shell_diagnostic` assertions so it also checks PowerShell metadata:

```python
assert result.status == "ok"
assert result.metadata["exit_code"] == 0
assert result.metadata["shell"] == "powershell"
assert result.metadata["shell_reason"] == "powershell_syntax"
```

- [ ] **Step 2: Run integration tests to verify they fail**

Run:

```powershell
py -3.14 -m pytest members/writer/backend/tests/test_writer_core_kernel_adapter.py -q -k "windows_defaults_to_git_bash or powershell_syntax_uses_powershell_fallback or powershell_utf8_output_is_readable or git_bash_nonzero_is_not_retried or windows_shell_diagnostic"
```

Expected: FAIL because `run_command` still always uses PowerShell and does not emit shell metadata.

- [ ] **Step 3: Add shell spec factories**

In `core/src/lamtools_core/tool/command_runner.py`, add this block after `_windows_git_bash_argv()`:

```python
def _windows_powershell_command_shell(command: str, *, reason: str) -> _WindowsCommandShell:
    return _WindowsCommandShell(
        argv=_windows_shell_argv(command),
        metadata={
            "shell": "powershell",
            "shell_path": "powershell.exe",
            "shell_reason": reason,
        },
    )


def _windows_command_shell(command: str) -> _WindowsCommandShell:
    if _looks_like_windows_powershell_command(command):
        return _windows_powershell_command_shell(command, reason="powershell_syntax")

    git_bash_path = _resolve_windows_git_bash_path()
    if git_bash_path is None:
        return _windows_powershell_command_shell(command, reason="git_bash_unavailable")

    return _WindowsCommandShell(
        argv=_windows_git_bash_argv(git_bash_path, command),
        metadata={
            "shell": "git_bash",
            "shell_path": str(git_bash_path),
            "shell_reason": "default",
        },
    )
```

- [ ] **Step 4: Wire shell spec into command execution**

In `core/src/lamtools_core/tool/command_tools.py`, update the import from `lamtools_core.tool.command_runner` to include:

```python
    _windows_command_shell,
    _windows_powershell_command_shell,
```

Add this helper after `split_command_for_path_validation()`:

```python
def _should_retry_git_bash_start_with_powershell(
    execution: _CommandExecution,
    shell_metadata: dict[str, object],
) -> bool:
    return (
        sys.platform == "win32"
        and shell_metadata.get("shell") == "git_bash"
        and bool(execution.error)
        and execution.error_type in {"FileNotFoundError", "PermissionError", "OSError"}
    )
```

In `CommandToolHandlers.run_command()`, initialize shell metadata before the platform branch:

```python
        shell_metadata: dict[str, object] = {}
```

Replace the Windows branch with:

```python
        if sys.platform == 'win32':
            shell_command = _normalize_windows_shell_command(command)
            shell_spec = _windows_command_shell(shell_command)
            argv = shell_spec.argv
            shell_metadata = dict(shell_spec.metadata)
            validation_argv = ["cmd", *split_command_for_path_validation(shell_command)]
        else:
```

After each first foreground or background command execution, add this fallback block before leaving the `if execution is None` branch:

```python
                    if _should_retry_git_bash_start_with_powershell(execution, shell_metadata):
                        shell_spec = _windows_powershell_command_shell(
                            shell_command,
                            reason="git_bash_start_failed",
                        )
                        argv = shell_spec.argv
                        shell_metadata = dict(shell_spec.metadata)
                        execution = await _run_subprocess(
                            argv,
                            cwd=self._work_root,
                            timeout=timeout,
                            progress_callback=_emit_command_progress if self._core_event_callback is not None else None,
                        )
```

For the background branch, add the same pattern using `_run_background_subprocess()`:

```python
                    if _should_retry_git_bash_start_with_powershell(execution, shell_metadata):
                        shell_spec = _windows_powershell_command_shell(
                            shell_command,
                            reason="git_bash_start_failed",
                        )
                        argv = shell_spec.argv
                        shell_metadata = dict(shell_spec.metadata)
                        execution = await _run_background_subprocess(
                            argv,
                            cwd=self._work_root,
                            command=command,
                            http_probe=http_probe,
                        )
```

Add shell metadata to the public result metadata:

```python
            **shell_metadata,
```

Add shell metadata to the `command_output` artifact metadata:

```python
                **shell_metadata,
```

- [ ] **Step 5: Run integration tests to verify they pass**

Run:

```powershell
py -3.14 -m pytest members/writer/backend/tests/test_writer_core_kernel_adapter.py -q -k "windows_defaults_to_git_bash or powershell_syntax_uses_powershell_fallback or powershell_utf8_output_is_readable or git_bash_nonzero_is_not_retried or windows_shell_diagnostic"
```

Expected: PASS.

- [ ] **Step 6: Run Core command tests**

Run:

```powershell
py -3.14 -m pytest core/tests/test_command_tools.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit Task 2**

```powershell
git add core/src/lamtools_core/tool/command_runner.py core/src/lamtools_core/tool/command_tools.py core/tests/test_command_tools.py members/writer/backend/tests/test_writer_core_kernel_adapter.py
git commit -m "feat(core): prefer Git Bash for Windows commands"
```

---

### Task 3: Writer Prompt Alignment

**Files:**
- Modify: `members/writer/backend/tests/test_prompt_assembler.py`
- Modify: `members/writer/backend/app/prompts/writer/platform_windows.md`

**Interfaces:**
- Consumes: `load_writer_prompt("platform_windows") -> str`
- Produces: prompt text that says Windows `run_command` defaults to Git Bash and PowerShell fallback must use UTF-8.

- [ ] **Step 1: Write failing prompt contract test**

Add this test to `members/writer/backend/tests/test_prompt_assembler.py`:

```python
def test_windows_platform_prompt_guides_git_bash_default():
    prompt = load_writer_prompt("platform_windows")

    assert "Git Bash" in prompt
    assert "PowerShell" in prompt
    assert "UTF-8" in prompt
    assert "默认" in prompt
```

- [ ] **Step 2: Run prompt test to verify it fails**

Run:

```powershell
py -3.14 -m pytest members/writer/backend/tests/test_prompt_assembler.py -q -k "windows_platform_prompt_guides_git_bash_default"
```

Expected: FAIL because the current Windows prompt only describes Windows/PowerShell and does not mention Git Bash.

- [ ] **Step 3: Update Windows prompt**

Replace the contents of `members/writer/backend/app/prompts/writer/platform_windows.md` with:

```markdown
当前环境是 Windows。`run_command` 默认通过 Git Bash 执行 Bash 兼容命令；只有明确 PowerShell 语法或 Git Bash 不可用时才会使用 PowerShell fallback。

涉及中文内容必须保持 UTF-8。不要通过 PowerShell 管道或 here-string 直传大段中文正文；优先使用 UTF-8 文件、JSON 转义或脚本内 Unicode 转义。启动本地长运行服务时使用后台进程能力，并在验证后给出可访问地址。
```

- [ ] **Step 4: Run prompt test to verify it passes**

Run:

```powershell
py -3.14 -m pytest members/writer/backend/tests/test_prompt_assembler.py -q -k "windows_platform_prompt_guides_git_bash_default"
```

Expected: PASS.

- [ ] **Step 5: Commit Task 3**

```powershell
git add members/writer/backend/tests/test_prompt_assembler.py members/writer/backend/app/prompts/writer/platform_windows.md
git commit -m "docs(writer): align Windows command prompt"
```

---

### Task 4: Final Verification

**Files:**
- Verify: `core/src/lamtools_core/tool/command_runner.py`
- Verify: `core/src/lamtools_core/tool/command_tools.py`
- Verify: `core/tests/test_command_tools.py`
- Verify: `members/writer/backend/tests/test_writer_core_kernel_adapter.py`
- Verify: `members/writer/backend/tests/test_prompt_assembler.py`
- Verify: `members/writer/backend/tests/test_tool_contracts.py`

**Interfaces:**
- Verifies: default Git Bash behavior, PowerShell fallback, UTF-8 output, no nonzero fallback, path validation, and Writer prompt alignment.

- [ ] **Step 1: Run focused command tests**

Run:

```powershell
py -3.14 -m pytest core/tests/test_command_tools.py -q
```

Expected: PASS.

- [ ] **Step 2: Run Writer command integration subset**

Run:

```powershell
py -3.14 -m pytest members/writer/backend/tests/test_writer_core_kernel_adapter.py -q -k "run_command or run_tests or background"
```

Expected: PASS.

- [ ] **Step 3: Run tool contract subset**

Run:

```powershell
py -3.14 -m pytest members/writer/backend/tests/test_tool_contracts.py -q -k "run_command or run_tests"
```

Expected: PASS.

- [ ] **Step 4: Run prompt alignment test**

Run:

```powershell
py -3.14 -m pytest members/writer/backend/tests/test_prompt_assembler.py -q -k "windows_platform_prompt_guides_git_bash_default"
```

Expected: PASS.

- [ ] **Step 5: Inspect scoped diff**

Run:

```powershell
git diff -- core/src/lamtools_core/tool/command_runner.py core/src/lamtools_core/tool/command_tools.py core/tests/test_command_tools.py members/writer/backend/tests/test_writer_core_kernel_adapter.py members/writer/backend/tests/test_prompt_assembler.py members/writer/backend/app/prompts/writer/platform_windows.md
```

Expected: Diff only contains shell selection, metadata, tests, and prompt alignment.

- [ ] **Step 6: Final commit if Task 4 found a missing cleanup**

If Task 4 required any cleanup edit, stage only touched task files:

```powershell
git add core/src/lamtools_core/tool/command_runner.py core/src/lamtools_core/tool/command_tools.py core/tests/test_command_tools.py members/writer/backend/tests/test_writer_core_kernel_adapter.py members/writer/backend/tests/test_prompt_assembler.py members/writer/backend/app/prompts/writer/platform_windows.md
git commit -m "test: verify Windows command shell selection"
```

If Task 4 required no cleanup edit, do not create an empty commit.
