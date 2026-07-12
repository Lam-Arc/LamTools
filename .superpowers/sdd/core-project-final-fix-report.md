# Core Project Final Fix Report

Baseline: `0d5ecd5`

Status: DONE (second final-fix wave)

## Completed fixes

- Blank project names are optional during creation and normalize to the workspace directory name. Renames still reject blank values across HTTP, App Server, and CLI.
- Project-owned Core session metadata is immutable through generic PATCH. The persistence write transaction preserves canonical `project_id` and `work_root`; unowned sessions cannot inject either field.
- Writer AGENTS.md loading, success, error, and completion state now all require the current request token and project ID. Saving captures the opening project and remains disabled until the current read completes.
- Writer duplicate-project migration now runs in the explicit write coordinator before list reads. It commits the session reassignment and duplicate deletion before returning results.
- Generic Writer `project.update` now rejects `agents_md` and directs callers to `project.agents_md.update`.
- Writer workbench now uses Core `buildCoreProjectGroups`, keyed strictly by persisted `project_id`. Sessions with a missing or invalid ID share one unmanaged `Unassigned` group. The orphan pseudo-project deletion path was removed.
- Core project storage now owns project-session creation under the SQLite write coordinator. It validates the project in the same write transaction and writes canonical `project_id` and `work_root`.
- HTTP, App Server, and shared UI use the project-session entrypoint. Generic session creation rejects client-supplied project IDs.
- Writer provides the equivalent project-owned creation path. Its delete/create race is serialized through the Writer persistence host and leaves no orphan session.
- Recreating an existing Writer project path now preserves a user-renamed project. Only actual duplicate records are merged, retaining the canonical record name.
- AGENTS.md reads now return disk-backed project-local data without mutating the database cache. The workbench uses target ID plus request token to discard stale reads, and each editor save handler captures its opening project ID.
- Core rejects blank project names and blank work roots. HTTP returns 4xx, App Server returns a validation error, and CLI exits nonzero.

## Verification

Targeted final checks:

- Core project/HTTP/CLI: 43 passed.
- Writer project/Core HTTP/App Server: 142 passed, then the focused App Server protocol suite: 107 passed.
- Core UI project contract: 13 passed.
- Writer frontend: 60 passed.

Full verification was rerun after the final changes:

- Core backend: 785 passed.
- Core UI contract: 161 passed.
- Writer backend: 754 passed.
- Writer frontend: 60 passed.
- `scripts/build.ps1 all`: passed.
- `git diff --check`: passed.

## Non-blocking observations

- The existing Windows asyncio/Proactor cleanup warnings appeared in the Core and Writer backend suites. All tests completed with exit code 0; this wave does not alter that lifecycle.
- Vite emitted its existing large chunk warning during production builds.

## Commit scope

Core project service, HTTP/App Server contract, shared project UI client/actions, Writer adapter/routes/workbench state, and focused regression coverage. Existing unrelated workspace artifacts and `core/ui/src/types.ts` remain outside the commit.
