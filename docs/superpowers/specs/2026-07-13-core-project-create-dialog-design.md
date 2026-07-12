# Core Project Create Dialog Design

## Goal

Replace the narrow sidebar popover with one shared Core-owned project creation dialog. Writer supplies only directory selection and project creation adapters.

## Surface

- Centered modal over a restrained backdrop.
- One continuous monochrome panel with no nested cards.
- Title: `新建项目`.
- Primary field: required project path with an embedded folder action.
- Secondary field: optional project name; an empty name uses the directory name.
- Short note that `AGENTS.md` is created automatically.
- Inline error area shown only when needed.
- Footer actions: `取消` and `创建项目`.

## Interaction

- Focus the project path when opened.
- Escape and backdrop click cancel unless creation is running.
- Directory selection is injected as an async function returning a path.
- Core owns selecting and submitting visual states.
- All controls remain keyboard accessible and expose clear accessible names.

## Responsive Behavior

- Desktop width is compact and capped.
- Mobile uses the viewport width with reduced padding; actions remain stable and do not overflow.

## Ownership

- Core owns markup, styling, state, validation, focus, and responsive behavior.
- Members own directory-picker implementation and submit handling only.
- No Git initialization option is present.

## Verification

- Core component tests cover submit, cancel, browse, focus, loading, error, and ownership boundaries.
- Core and Writer builds/tests pass.
- Browser screenshots are reviewed at desktop and mobile widths for Core and Writer.
