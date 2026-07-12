# Task 5: Writer Core-Contract Migration

## Scope

- Baseline: `20a7a08`.
- Writer now leaves generic `project.*` operations to the Core workbench catalog and supplies Writer persistence through the Core operation adapter.
- Writer keeps its existing project/session IDs, `config`, and cached `agents_md` business fields in its own database.

## Contract Changes

- `project.create` returns the Core shape with `project` and an initial Writer session.
- `project.delete` returns `deleted: true`.
- `project.agents_md.get` and `project.agents_md.update` return `agents_md` with `content` and `exists`.
- Ordinary project creation creates the work root but never initializes Git or creates `.git`.

## UI Boundary

- `CoreWorkbenchView.vue` imports `CoreProjectCreate` and `CoreAgentsEditor` from `@lamtools/ui`.
- The Writer-local new-project form and AGENTS.md textarea implementation were removed.
- Writer retains only loading, error, session-selection, and Writer-store adaptation around the shared components.

## Verification

- RED: the new frontend boundary test failed before the migration because `CoreProjectCreate` was absent.
- GREEN backend: `py -3.14 -m pytest backend/tests/test_project_crud.py backend/tests/test_writer_app_server_protocol.py -q` -> `110 passed`.
- GREEN frontend: `npm run lint`, `npm test`, and `npm run build` -> all passed; frontend tests report `56 passed`.
- `git diff --check` passed for the Task 5 source and test paths.

## Residual Note

- The backend test run emits existing Windows asyncio transport cleanup warnings after successful completion. They do not fail the targeted suite.

## Review Repair

- Core now exports the shared workspace normalization, directory creation, project-name, and UTF-8 `AGENTS.md` helpers. Both CoreProjectStore and Writer use them; Writer keeps only its database records, cached business fields, and error mapping.
- Writer frontend parses `agents_md.content` and `agents_md.exists`, and saves the exact `CoreAgentsEditor` emitted content.
- `project.create` preserves the returned initial Writer session. The UI inserts and selects that session without a second create request.
- Writer project deletion now rejects `running`, `waiting`, and `interrupting` sessions with the Core-compatible active-session message and a `409` error payload.
- CoreProjectCreate exposes an opt-in path action slot. Writer injects its existing directory picker there; Core remains browser- and Git-neutral.
- Removed obsolete Writer connection methods and catalog parameters for Core-owned `project.*` operations. The Writer overlay retains only `project.directory.pick`.

## Review Verification

- Core store: `py -3.14 -m pytest core/tests/test_core_project_store.py -q` -> `9 passed`.
- Core UI: `npm run typecheck` and `npm run test:contract -- core-project-components.test.ts` -> typecheck passed, `7 passed`.
- Writer backend: `py -3.14 -m pytest backend/tests/test_project_crud.py backend/tests/test_writer_app_server_protocol.py -q` -> `113 passed`.
- Writer frontend: `npm run lint`, `npm test`, and `npm run build` -> all passed; frontend tests report `57 passed`.
- `git diff --check` passed before staging.
