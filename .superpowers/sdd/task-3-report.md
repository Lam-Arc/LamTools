# Task 3 Report: Core Command Catalog Loader

## Scope

- Task brief: `E:\LamTools\.superpowers\sdd\task-3-brief.md`
- Allowed write scope only:
  - `core/command/compact.json`
  - `core/command/fork.json`
  - `core/src/lamtools_core/composer_commands.py`
  - `core/tests/test_composer_commands.py`
  - `core/src/lamtools_core/__init__.py`
  - this report file

## Mature-solution check

- Checked current OpenAI / Claude product patterns for slash-command style interaction at a high level before implementation.
- Chosen shape stays minimal and mature-aligned: static command metadata files, normalized names, product-neutral loader, member additions after core, no member override of active core names, member-local disable list for core commands.
- No extra runtime routing, caching, or product-specific branching was added in Core.

## TDD Evidence

### RED

1. Added failing tests in `core/tests/test_composer_commands.py`.
2. Ran:

```powershell
py -3.14 -m pytest core\tests\test_composer_commands.py -q
```

3. Observed expected failure:

```text
ModuleNotFoundError: No module named 'lamtools_core.composer_commands'
```

This matches the brief expectation that the loader module did not exist yet.

### GREEN

Implemented:

- Core command resource files:
  - `core/command/compact.json`
  - `core/command/fork.json`
- Core loader:
  - `core/src/lamtools_core/composer_commands.py`
- Core exports:
  - `core/src/lamtools_core/__init__.py`

Behavior implemented:

- Load JSON command definitions from `command/*.json`
- Ignore invalid or unreadable JSON files
- Load core commands first
- Append member commands after core commands
- Block member command names from overriding active core command names
- Apply member `command/config.json` `disabled_core_commands` against core commands only
- Keep command names normalized and product-neutral

4. Re-ran targeted tests:

```powershell
py -3.14 -m pytest core\tests\test_composer_commands.py -q
```

5. Result:

```text
2 passed in 0.11s
```

## Required Verification

### 1) Targeted Task 3 tests

Command:

```powershell
py -3.14 -m pytest core\tests\test_composer_commands.py -q
```

Result:

```text
2 passed in 0.11s
```

### 2) Full Core test suite

Command:

```powershell
py -3.14 -m pytest core\tests -q
```

Result:

```text
1 failed, 496 passed in 5.58s
```

Failure details:

- Failing test: `core/tests/test_member_template.py::test_member_template_does_not_include_generated_runtime_artifacts`
- Verified cause:
  - Existing generated artifact under `E:\LamTools\core\templates\member\backend\tests\__pycache__\test_member_kit.cpython-314-pytest-9.0.3.pyc`
- Assessment:
  - This is pre-existing template pollution outside the Task 3 allowed write scope.
  - Task 3 changes did not touch template files or template generation paths.

## Files Changed

- `E:\LamTools\core\command\compact.json`
- `E:\LamTools\core\command\fork.json`
- `E:\LamTools\core\src\lamtools_core\composer_commands.py`
- `E:\LamTools\core\src\lamtools_core\__init__.py`
- `E:\LamTools\core\tests\test_composer_commands.py`
- `E:\LamTools\.superpowers\sdd\task-3-report.md`

## Self-review

- Scope stayed inside allowed paths.
- Core runtime remains product-neutral; no product names were introduced in `core/src/lamtools_core`.
- Loader logic is intentionally small and data-driven.
- Invalid definitions are ignored rather than raising, which matches the brief.
- Member disable config only affects core commands for the requesting member set.
- Member commands cannot override active core command names.
- Export surface was added so downstream Task 4 can import from Core cleanly.

## Concerns

1. Required full-suite verification is not fully green because of a pre-existing `__pycache__` artifact in `core/templates/member/backend/tests`.
2. That failure is outside the allowed write scope for this task, so it was documented rather than changed here.

## Controller Verification After Generated Artifact Cleanup

The controller removed the ignored generated runtime artifact that blocked the full Core suite:

- `core\templates\member\backend\tests\__pycache__\test_member_kit.cpython-314-pytest-9.0.3.pyc`
- empty directory `core\templates\member\backend\tests\__pycache__`

Re-ran:

```powershell
py -3.14 -m pytest core\tests -q
```

Observed:

```text
497 passed in 4.70s
```

## Review Fix: Reserve Disabled Core Command Names

Review requirement addressed:

- Member commands must never replace Core command names, including when a member disables a Core command through config.

### RED

Added focused regression coverage in `core/tests/test_composer_commands.py`:

- `test_member_cannot_replace_disabled_core_command_name`

Command:

```powershell
py -3.14 -m pytest core\tests\test_composer_commands.py -q
```

Observed before the fix:

```text
..F                                                                      [100%]
FAILED core/tests/test_composer_commands.py::test_member_cannot_replace_disabled_core_command_name
AssertionError: assert ['fork'] == []
1 failed, 2 passed in 0.19s
```

This proved the current loader let a member redefine `fork` after that Core command was disabled by member config.

### GREEN

Adjusted the loader so it:

- loads all Core command definitions first,
- reserves all Core command names before applying member disable filtering,
- filters disabled Core entries from the final Core list,
- still blocks member entries whose names match any Core command name.

Re-ran targeted verification:

```powershell
py -3.14 -m pytest core\tests\test_composer_commands.py -q
```

Observed after the fix:

```text
...                                                                      [100%]
3 passed in 0.11s
```

Re-ran full Core verification:

```powershell
py -3.14 -m pytest core\tests -q
```

Observed:

```text
498 passed in 4.77s
```

---

# Task 3: Core Project CLI Report

## Scope

- Baseline: `10f38bcd70e3de638389f3371afe68440a96d81b`
- Commands added: `core project list/create/show/rename/delete` and `core project agents get/set`.
- The CLI resolves its database with the same `_resolve_core_db` path used by `serve`, opens it with `open_core_app_db`, and delegates all project and `AGENTS.md` behavior to `CoreProjectStore`.

## TDD Evidence

### RED

Command:

```powershell
py -3.14 -m pytest tests/test_core_cli.py -q
```

Output before implementation:

```text
1 failed, 18 passed
argparse.ArgumentError: argument command: invalid choice: 'project'
```

### GREEN

Command:

```powershell
py -3.14 -m pytest tests/test_core_cli.py tests/test_core_project_store.py -q
```

Output:

```text
28 passed in 4.90s
```

## Real CLI Verification

Commands executed against one temporary Core database:

```powershell
py -3.14 -m lamtools_core.cli project create <workspace> --name Docs --core-db <core.db>
py -3.14 -m lamtools_core.cli project agents set <project-id> <rules.md> --core-db <core.db>
py -3.14 -m lamtools_core.cli project agents get <project-id> --core-db <core.db>
py -3.14 -m lamtools_core.cli project list --core-db <core.db>
```

Observed output excerpts:

```json
{"created": true, "project": {"id": "f969f686056d480bb5c34c0a3053b270", "name": "Docs", "work_root": "<workspace>"}, "session": {"metadata": {"project_id": "f969f686056d480bb5c34c0a3053b270", "work_root": "<workspace>"}, "status": "idle"}}
{"agents_md": {"content": "# Core rules\n", "exists": true}}
{"projects": [{"id": "f969f686056d480bb5c34c0a3053b270", "name": "Docs", "work_root": "<workspace>"}]}
```

## Files

- `core/src/lamtools_core/cli.py`
- `core.cmd`
- `scripts/core.cmd`
- `core/tests/test_core_cli.py`
- `.superpowers/sdd/task-3-report.md`

## Self Review

- No SQL or filesystem behavior was added to the CLI. Project persistence, initial-session creation, deletion rules, and `AGENTS.md` writes remain owned by `CoreProjectStore`.
- Each CLI command closes the Core DB handle in `finally`.
- JSON output is one stable, parseable object per command. Create explicitly returns the initial session created by the public store API.
- Both batch entry points default `LAMTOOLS_CORE_DB` to the same `data/core.db` selected by the shared resolver when no explicit path or environment value is supplied.
- `git diff --check` passed.

## Concerns

- No unresolved implementation concern. Project deletion still follows the existing store rule and rejects a project with an active initial session; this CLI intentionally preserves that behavior.
