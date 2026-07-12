# Task 6 Core Project Workspace Acceptance

Status: DONE

Baseline: `eb959123939abd0c43a706c5c85dd674f32f7f00`

## Initial Findings And Fixes

1. `writer project list` was required for CLI parity but was not registered. The Writer app-server already exposed `project.list`.
   - Added a thin Writer CLI client call and `writer project list` command.
   - Output uses the Core-compatible `{"projects":[...]}` envelope.
2. Writer ordinary `session.create` and work-root update paths still called Git initialization.
   - Removed those implicit calls.
   - Kept explicit Git workflows unchanged.
   - Replaced the obsolete lock test with an assertion that ordinary session creation does not create `.git`.
3. Review follow-up found that the REST `POST /sessions` and `PATCH /sessions/{id}` routes still passed a Git manager into the session service.
   - Removed the Git manager parameters and the remaining session-service initialization branch.
   - Added real temporary-directory regression coverage for REST creation, REST work-root update, and App Server `session.update` work-root update.
   - Explicit Git initialization remains limited to the commit-review route that calls `_ensure_work_root_repo()`.

No current documentation was found that describes projects as Writer-only. The only matching text was this task plan's historical TODO, so no unrelated documentation was changed.

## Final Automated Verification

- `./scripts/test.ps1 all`: passed.
  - Core pytest: `781 passed, 3 warnings in 50.27s`.
  - Core UI Vitest: `27` files, `160` tests passed.
  - Writer backend pytest: `747 passed, 7 warnings in 360.59s`.
  - Writer UI Node tests: `57` passed, `0` failed.
  - Warnings are the existing Windows Proactor resource-release warning and Node experimental-transform warnings; no test failed.
- `./scripts/build.ps1 all`: passed.
- `git diff --check`: passed.
- Focused changed-area verification before the final full run: `183 passed, 1 warning`.
- Review follow-up targeted Writer tests: `test_project_crud.py`, `test_writer_app_server_protocol.py`, and `test_writer_sqlite_lifecycle.py`: `132 passed, 4 warnings in 37.17s`.
- Review follow-up complete Writer backend suite: `748 passed, 7 warnings in 377.82s`.

## Real Core Acceptance

All Core data and workspaces were isolated from user data under:

`C:\Users\Administrator\AppData\Local\Temp\lamtools-task6\isolated-20260712-1450`

Core API project record:

- Project ID: `8ef20982728440b18ed0501da4d7e34d`
- Initial session ID: `e39ae57f5f5d40858b08d435b0ddbc69`
- Work root: `C:\Users\Administrator\AppData\Local\Temp\lamtools-task6\isolated-20260712-1450\workspaces\missing-core-project`

Verified through the live Core API:

- A missing project directory was created without `.git`.
- The initial session was `idle` and its metadata contained the same `project_id` and `work_root`.
- UTF-8 Chinese `AGENTS.md` content round-tripped through raw HTTP bytes and the workspace file.
- After a Core restart using the same isolated database, the project and initial session remained present.
- Deleting the project while the session was `running`, `waiting`, or `interrupting` returned HTTP `409` in each case.
- After restoring `idle`, delete returned HTTP `204`; the work root and `AGENTS.md` remained on disk.

## CLI Parity And Writer No-Git Evidence

- `core project list` and `core project show <id>` returned project records with `id`, `name`, `work_root`, `created_at`, and `updated_at`.
- `writer project list` returned the same fields in the same project-list envelope, plus Writer-only `agents_md` and `config` fields.
- After restarting isolated Writer on port `6293`, the ordinary CLI session creation command returned session ID `b9c2cadb9a3848949b3712251c153fef`.
- Its created project record ID was `f38c38ebc8944045a570617d83991b52`.
- Its fresh work root was `C:\Users\Administrator\AppData\Local\Temp\lamtools-task6\isolated-20260712-1450\writer-workspaces\ordinary-session-no-git`.
- `.git` was absent after creation, and `writer project list` completed successfully.
- REST session creation, REST work-root update, and App Server `session.update` work-root update now each create a real fresh directory without `.git`.

## Ownership Scan

- Core owns the project operation group, HTTP project handlers, project persistence, and shared project UI client.
- Writer owns adapters, Writer persistence additions, and product-only fields.
- Core owns `project.create` and `project.agents_md.*` contracts; Writer forwards the same operation names through its adapter.
- REST and App Server ordinary project/session creation and work-root update do not receive a Git manager and do not initialize repositories.
- Writer project persistence no longer carries an obsolete Git manager dependency.
- The only remaining session-router initialization call is the explicit commit-review action through `_ensure_work_root_repo()`.

## Service Cleanup

The acceptance-only Core API (`6291`), Core UI (`6292`), and Writer API (`6293`) were stopped. A listener check confirmed all three ports were free. The isolated workspace directory remains only as temporary audit evidence and is not staged or committed.
