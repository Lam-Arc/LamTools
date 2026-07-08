# run_command Shell Selection Design

## Product Goal

`run_command` on Windows should behave like a coding-agent command surface: prefer Bash-compatible commands through Git Bash, fall back to PowerShell only when Git Bash is unavailable or the command is clearly PowerShell-specific, and keep Chinese output readable.

## Current Context

- The real command implementation now lives in `core/src/lamtools_core/tool/command_tools.py` and `core/src/lamtools_core/tool/command_runner.py`.
- Writer imports this Core command behavior through thin compatibility modules, so Writer should not grow a separate shell path.
- The current Windows path always wraps commands with PowerShell. Existing tests verify PowerShell syntax, but this no longer matches the desired default.
- The worktree is dirty outside this task; this change must stay scoped to command execution and focused tests.

## External Alignment

- OpenAI Codex documents agent mode as a local project workflow that can read files, run commands, and write changes. That supports treating command execution as a first-class Core capability rather than a Writer-specific feature.
- Claude Code documents the exact Windows precedent requested here: with Git for Windows it uses Git Bash for the Bash tool, and without Git for Windows it uses PowerShell as the shell tool.
- Microsoft documents that PowerShell encoding behavior differs by version; Windows PowerShell defaults are not consistently UTF-8. PowerShell fallback must therefore set UTF-8 explicitly before running user commands.

## Recommended Architecture

Keep shell selection in Core:

- Add a small Windows shell resolver in `core/src/lamtools_core/tool/command_runner.py`.
- Keep `CommandToolHandlers.run_command()` as the single orchestration point for validation, background handling, progress events, artifacts, and result formatting.
- Keep Writer files as compatibility re-exports only.

This avoids a parallel Writer command implementation and preserves the existing Core/Member boundary.

## Behavior

### Default Shell

- On Windows, prefer Git Bash when available.
- Resolve Git Bash in this order:
  1. Environment override such as `LAMTOOLS_GIT_BASH_PATH`, if valid.
  2. `C:/Program Files/Git/bin/bash.exe`.
  3. `C:/Program Files/Git/usr/bin/bash.exe`.
  4. A PATH hit that points to Git for Windows, not WSL `bash.exe`.
- Run the command as `bash.exe -lc <command>`.
- On non-Windows platforms, keep the current command behavior.

### PowerShell Fallback

Use PowerShell when:

- Git Bash cannot be found or cannot be started.
- The command has an explicit PowerShell prefix such as `powershell`, `powershell.exe`, or `pwsh`.
- The command is clearly PowerShell syntax, such as `Get-ChildItem`, `Select-Object`, `Where-Object`, `Write-Output`, `Remove-Item`, or `Set-Content`.

Do not fallback just because Git Bash returns a nonzero exit code. Test failures, lint failures, and build failures must remain visible as the actual command result.

### Encoding

PowerShell fallback must set UTF-8 inside the wrapper before invoking the user command:

- `[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)`
- `[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)`
- `$OutputEncoding = [System.Text.UTF8Encoding]::new($false)`

The subprocess reader should continue decoding stdout and stderr as UTF-8 with replacement for invalid bytes.

### Metadata

Command results should expose shell metadata for diagnosis:

- `shell`: `git_bash`, `powershell`, or existing non-Windows value if useful.
- `shell_path`: resolved executable path when known.
- `shell_reason`: `default`, `git_bash_unavailable`, `git_bash_start_failed`, or `powershell_syntax`.

Metadata must not change `status`, `content`, or artifact shape in a breaking way.

## Tests

Use TDD. Add focused tests before production edits:

- Git Bash resolver prefers `C:/Program Files/Git/bin/bash.exe` over generic WSL bash.
- Windows default command metadata says `git_bash` when Git Bash is available.
- A PowerShell command uses PowerShell fallback and succeeds.
- A command that prints Chinese through PowerShell returns readable UTF-8 text.
- A Git Bash command that exits nonzero does not rerun through PowerShell.
- Existing path-boundary validation still rejects paths outside `work_root`.

Run the smallest affected tests first, then the broader command-related Writer tests:

```powershell
py -3.14 -m pytest core/tests/test_command_tools.py -q
py -3.14 -m pytest members/writer/backend/tests/test_writer_core_kernel_adapter.py -q -k "run_command or run_tests or background"
py -3.14 -m pytest members/writer/backend/tests/test_tool_contracts.py -q -k "run_command or run_tests"
```

## Acceptance

- On this Windows machine, ordinary commands execute through Git Bash by default.
- PowerShell-specific commands still work.
- Chinese PowerShell output is not garbled.
- Failed commands return the original failure instead of being retried in another shell.
- Writer keeps using the shared Core command path.
