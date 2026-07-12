# Task 4 Report: Shared Core Project UI And Demo

## Scope

- Added the shared project REST client, project grouping, creation form, and `AGENTS.md` editor.
- Replaced the Core demo's synthetic group with persisted project groups, project-root display, per-project session creation, rename, instruction editing, and guarded project-record deletion.
- Historical sessions without `project_id` now appear in one explicit `Unassigned` compatibility group.

## TDD Evidence

- RED: `npm exec vitest run tests/core-project-client.test.ts tests/core-project-components.test.ts tests/core-project-demo.test.ts` failed because the project client, components, and grouping module did not exist.
- GREEN: the same command passed with 3 files and 9 tests.
- Final: `npm run test:contract` passed with 27 files and 154 tests; `npm run typecheck` and `npm run build` passed.

## Interaction Review

- Create, rename, instruction save, and delete report backend errors and disable conflicting controls while requests run.
- The project form, action inputs, and editor use native labelled controls with inherited focus-visible handling. Escape works through the editor's close control and the create form has an explicit cancel action.
- The project-create popover moves left on narrow screens; editors use constrained widths and vertical resize only.
- Project deletion requires an explicit confirmation and the backend keeps active project sessions protected.

## Minimal Sidebar Extension

`SessionSidebar` now accepts the optional per-group `canManage` marker. This was necessary because its previous global action flags would render new-session, delete, click, and context actions for `Unassigned`, which is a compatibility group rather than a persisted project. Existing groups retain the prior behavior.
