# Core Project Task 4 Report

## Delivered Scope

- Added shared Core project REST client, project grouping, creation form, and inline `AGENTS.md` editor.
- Replaced the synthetic Core group with persisted projects, visible work roots, per-project session creation, rename, instruction read/write, guarded deletion, and one `Unassigned` compatibility group.
- Kept the project workbench inside existing Core controls and avoided Git options, modals, and a separate visual language.

## Initial TDD Evidence

- RED: the project client, components, and grouping module were absent; the three targeted test files failed to resolve their imports.
- GREEN: after the initial implementation, the targeted project suite passed.
- Initial verification: `npm run test:contract`, `npm run typecheck`, and `npm run build` passed before review.

## Review Fixes

1. The creation form now has `width: 100%` and `min-width: 0`; its right-aligned popover is constrained to the drawer's usable width with `min(340px, calc(var(--left-card-width) - 28px), calc(100vw - 48px))`. It remains an inline popover, so drawer clipping cannot hide it on narrow screens.
2. Project management is now a native button with explicit Enter and Space handling. Group folding remains on its separate control.
3. Per-project session creation has an in-flight set. `busyProjectIds` is passed to `SessionSidebar`, which disables and marks only the affected project's add button until the request settles.
4. Demo tests now use the same project workspace action helper as the Demo. They verify initial-session selection, project metadata, duplicate suppression, rename, `AGENTS.md` read/write, and deletion calls. Component tests verify keyboard activation, busy disablement, and the narrow-width CSS contract.
5. Restored the historical `.superpowers/sdd/task-4-report.md` from baseline `2a87f1d`; this report is the dedicated Core project record.

## Final Verification

Results after the review fixes:

- `npm run test:contract`: 27 files and 159 tests passed.
- `npm run typecheck`: passed.
- `npm run build`: passed.
- `git diff --check`: passed with no diff errors.
