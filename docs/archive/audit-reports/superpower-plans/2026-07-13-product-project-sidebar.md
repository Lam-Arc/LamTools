# Product Project Sidebar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a product-labelled project sidebar with durable pinning and automatic Recent/Earlier activity sections.

**Architecture:** Keep project/session data unchanged. `SessionSidebar` derives sections from existing timestamps and owns a storage-key-scoped pinned-id preference; `WorkspaceShell` receives a separate concise sidebar title so full product branding remains available elsewhere.

**Tech Stack:** Vue 3, TypeScript, CSS, Vitest, Vue Test Utils, localStorage.

## Global Constraints

- Core displays `Core`; Writer displays `Writer`.
- Recent means activity within the last 30 days.
- No backend schema or API changes.
- Preserve existing project and session actions.

---

### Task 1: Section derivation and persistence

**Files:**
- Modify: `core/ui/src/components/SessionSidebar.vue`
- Test: `core/ui/tests/session-sidebar.test.ts`

**Interfaces:**
- Consumes: `ProjectGroup.sessions[].updatedAt`, `createdAt`, and `pinStorageKey`.
- Produces: `PINNED`, `RECENT`, and `EARLIER` sections plus durable pin toggles.

- [ ] Write component tests proving time classification, ordering, pin/unpin, and storage restoration.
- [ ] Run `npm --prefix core/ui run test:contract -- session-sidebar.test.ts` and confirm the new tests fail.
- [ ] Add the minimal section derivation and localStorage-backed pin behavior.
- [ ] Re-run the focused tests and confirm they pass.

### Task 2: Product menus and session hover actions

**Files:**
- Modify: `core/ui/src/components/WorkspaceShell.vue`
- Modify: `core/ui/src/styles/layout.css`
- Modify: `core/ui/src/demo/App.vue`
- Modify: `members/writer/frontend/src/views/CoreWorkbenchView.vue`

**Interfaces:**
- Consumes: `sidebarTitle` with fallback to `productName`, and per-product pin storage keys.
- Produces: `Core` / `Writer` headings, reference-aligned flat project groups, a restrained project action menu, and session hover actions.

- [ ] Add `sidebarTitle` to the shared shell and pass `Core` or `Writer` at each workbench.
- [ ] Pass stable, product-specific pin storage keys to the session sidebar.
- [ ] Move project actions into an ellipsis menu with outside-click and Escape dismissal.
- [ ] Replace each session status point with pin/delete buttons on hover or focus and persist pinned session ordering.
- [ ] Restyle section labels, projects, sessions, menus, hover/focus states, and narrow-width overflow using existing theme tokens.
- [ ] Run Core UI typechecking and the Writer frontend build.

### Task 3: Acceptance verification

**Files:**
- Verify only; do not change runtime data.

**Interfaces:**
- Consumes: built Core demo and Writer workbench.
- Produces: visual and interaction evidence for the final handoff.

- [ ] Run the full Core UI contract suite.
- [ ] Start an isolated frontend surface and inspect the sidebar at desktop and narrow widths.
- [ ] Confirm pin persistence, Recent/Earlier placement, project expansion, and accessible controls.
- [ ] Run `git diff --check` and review the scoped diff before committing.
