# Core Project Final Fix Report

Baseline: `0d5ecd5`

Status: DONE (main-agent audit wave)

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

## Main-agent audit fixes

- Core persistence itself now protects canonical project metadata, including callers that bypass HTTP and App Server guards.
- Recreating a Core project returns its original initial session deterministically instead of whichever session was most recently updated.
- Writer project paths are immutable at the REST, App Server, runtime, and service boundaries. A project-owned session cannot drift away from its canonical workspace.
- Assigning a workspace to an unassigned Writer session creates or reuses the matching project and records the ownership relationship.
- Direct Writer `thread.start` materialization with a workspace now creates the same project association as REST and project creation.
- Writer REST session writes now use the shared write coordinator, avoiding transaction rollback or closed-session persistence gaps.
- Writer REST and App Server project creation use one service and create exactly one stable initial session.
- Legacy Writer `agents_md` values migrate once to the real workspace `AGENTS.md` when absent. Existing disk content wins, and inaccessible workspaces no longer break project loading.

## Verification

Targeted final checks:

- Core project/HTTP/CLI: 43 passed.
- Writer project/Core HTTP/App Server: 142 passed, then the focused App Server protocol suite: 107 passed.
- Core UI project contract: 13 passed.
- Writer frontend: 60 passed.

Full verification was rerun after the final changes:

- Core backend: 787 passed.
- Core UI contract: 161 passed.
- Writer backend: 758 passed.
- Writer frontend: 60 passed.
- `scripts/build.ps1 all`: passed.
- `git diff --check`: passed.

## Non-blocking observations

- The existing Windows asyncio/Proactor cleanup warnings appeared in the Core and Writer backend suites. All tests completed with exit code 0; this wave does not alter that lifecycle.
- Vite emitted its existing large chunk warning during production builds.

## Commit scope

Core project service, HTTP/App Server contract, shared project UI client/actions, Writer adapter/routes/workbench state, and focused regression coverage. Existing unrelated workspace artifacts and `core/ui/src/types.ts` remain outside the commit.

## Shared Agent frontend foundation follow-up

The eight reported frontend gaps were re-audited before implementation. Composer send/stop/queue, skill input, thinking controls, attachment staging, approval control, and App Server projection were already Core-owned and reused by Writer, so they were not duplicated.

The remaining duplicated foundations were moved into Core:

- Project, session, and AGENTS.md state and actions.
- Provider and model collection state and CRUD orchestration.
- UI density, content width, theme, and persistence.
- The complete shared settings surface, including provider presets, advanced adapter JSON, environment import, and command permission policies.

Writer now keeps adapters and product-specific routing/capability behavior only. Its settings view delegates to `CoreSettings`; the former project/session stores were replaced by one thin workspace adapter.

Follow-up verification:

- Browser: Writer workbench rendered project/session groups, composer, model selector, thinking mode, Shallow, send action, settings entry, and runtime panel.
- Core backend: 787 passed.
- Writer backend: 758 passed.
- Core UI contract: 163 passed.
- Writer UI contract: 59 passed.
- `scripts/build.ps1 all`: passed.
- `git diff --check`: passed.

Git/checkpoint/review/agent-branch capabilities remain outside this follow-up pending product-boundary decisions.
