# Task 2 Report: DONE_WITH_CONCERNS

## Scope and baseline

- Baseline: `ac8d7b9 feat(core): add persistent project workspaces`
- No `core_db.py` schema change was needed. The existing durable session snapshot metadata already carries `project_id` and `work_root`; all project-session lifecycle writes use the existing SQLite write coordinator.
- Official implementation-pattern check: OpenAI Agents and Claude Code documentation endpoints both returned HTTP 200 before implementation. The local HTTP/App Server operation catalog remains the appropriate mature pattern for this repository.

## RED

Command:

```powershell
py -3.14 -m pytest tests/test_core_project_store.py tests/test_core_http_agent_app.py tests/test_operation_groups.py -q
```

Key output: `5 failed, 19 passed in 1.82s`.

The failures proved the missing `create_with_initial_session()` lifecycle, project HTTP routes, App Server operation registration, and shared operation names.

## Implemented Core changes

- Project creation now creates the project and an idle Core session in one coordinated write. The session metadata is exactly `{project_id, work_root}`.
- Project session listing and deletion use the durable snapshot metadata. Project deletion rejects active sessions and atomically removes the project session's event, runtime, and snapshot rows before deleting the project.
- HTTP routes expose project list/create/get/update/delete, linked-session listing, and real `AGENTS.md` read/write.
- The Core App Server registers all eight project operations. `project.create` returns `{project, session}`.
- The shared operation catalog lists the Core project contracts. Member overlays cannot override any Core operation, including `project.*`.

## GREEN

Command:

```powershell
py -3.14 -m pytest tests/test_core_project_store.py tests/test_core_http_agent_app.py tests/test_operation_groups.py tests/test_core_live_client_e2e.py -q
```

Key output: `25 passed, 3 warnings in 3.29s`.

Warnings are existing `websockets.legacy` deprecations from the real WebSocket E2E test.

## Task 5 migration concern

- The existing Writer project overlay still uses the eight `project.*` operation names.
- Its three ownership assertions are a known Task 5 migration item. They do not block Task 2: Core now owns the contracts and no member override exemption remains.
- No Writer files were modified in this task.

## Files changed

- `core/src/lamtools_core/app/project_store.py`
- `core/src/lamtools_core/app/core_session_store.py`
- `core/src/lamtools_core/app/http_agent_app.py`
- `core/src/lamtools_core/app/operation_groups.py`
- `core/src/lamtools_core/http/routes.py`
- `core/tests/test_core_project_store.py`
- `core/tests/test_core_http_agent_app.py`
- `core/tests/test_operation_groups.py`
- `.superpowers/sdd/task-2-report.md`

## Self-review and commit

- Self-review completed: deletion cleanup has direct event/runtime/snapshot regression coverage; HTTP restart, real `AGENTS.md`, active-session `409`, and App Server project creation are covered.
- `git diff --check` passed.
- Commit: `feat(core): expose project workspace contracts`.

## Concern

Task 5 must migrate Writer's legacy project overlay to the Core contracts and update its ownership assertions. This is an accepted cross-task concern, not a Task 2 blocker.

## Review Follow-up

### Fixed Important findings

- Public `create()` retains its `(project, created)` signature and now uses the same private row-level lifecycle helper as `create_with_initial_session()`. A newly created project always receives its initial Core session.
- Public `delete()` and `delete_with_sessions()` both use one private coordinated deletion path. Active `running`, `waiting`, and `interrupting` sessions are rejected, while event, runtime, and snapshot records are removed before the project row.
- Added direct public-entry regressions for initial-session creation, linked-record cleanup, and all three active statuses.

### App Server coverage

Added real WebSocket request/response coverage for `project.get`, `project.update`, `project.delete`, `project.sessions.list`, `project.agents_md.get`, and `project.agents_md.update`.

### Verification

```powershell
py -3.14 -m pytest tests/test_core_project_store.py tests/test_core_http_agent_app.py tests/test_operation_groups.py tests/test_core_live_client_e2e.py -q
```

Output: `27 passed, 3 warnings in 3.59s`. The warnings are existing `websockets.legacy` deprecations in the live WebSocket E2E test.

`git diff --check` passed before commit.
