# Core Project Workspace Design

## Goal

Make project/workspace management a standalone Core Agent capability. Core must group sessions by project, retain the project path, and read/write the real `AGENTS.md` in that path. Git initialization is explicitly excluded.

## Ownership

Core owns:

- Project identity, display name, and absolute work root.
- Project persistence and restart recovery.
- Project/session association and sidebar grouping.
- Work-root directory creation.
- Reading and writing `<work_root>/AGENTS.md`.
- Generic HTTP, App Server, CLI, and UI contracts.

Writer owns only incremental product behavior. It may add Writer-specific fields and workflows, but must call the Core project contract rather than reimplement project identity, grouping, paths, or `AGENTS.md` access.

Git repository creation, Git initialization, branches, checkpoints, and review workflows are not part of Core project creation.

## Data Model

Add a Core-owned project table in the Core database:

- `id`: stable UUID/string primary key.
- `name`: user-visible project name.
- `work_root`: normalized absolute path, unique.
- `created_at`: creation timestamp.
- `updated_at`: last metadata update timestamp.

Core sessions retain their current thread snapshot storage. Their session metadata gains:

- `project_id`: owning Core project ID.
- `work_root`: normalized project path.

The project table is authoritative for project identity. Session metadata is the execution context and compatibility projection.

## Project Lifecycle

### Create

Input:

- `name`: optional; defaults to the final directory segment.
- `work_root`: required absolute or resolvable local path.

Behavior:

1. Normalize and resolve `work_root`.
2. Create the directory and missing parent directories.
3. Reuse the existing project when the normalized path already exists in Core DB.
4. Persist the project.
5. Create its initial Core session and associate `project_id` and `work_root`.
6. Do not run any Git command and do not create `.git`.

### Update

Project name may be changed. Work-root relocation is excluded from this slice because moving or rebinding disk assets needs a separate safety design.

### Delete

Deleting a project removes its Core project record and associated Core session/runtime records only after active sessions have stopped. It never deletes the work-root directory, `AGENTS.md`, or other disk content.

## AGENTS.md

- Read from `<work_root>/AGENTS.md` as UTF-8.
- A missing file returns empty content and `exists: false`.
- Save creates or replaces the file using UTF-8 and returns the saved content.
- Reject access when the project does not exist or its resolved target escapes the project root.
- Core does not cache file content as an authoritative DB copy.

## Interfaces

Use the same project semantics on every surface.

### App Server Operations

- `project.list`
- `project.create`
- `project.get`
- `project.update`
- `project.delete`
- `project.sessions.list`
- `project.agents_md.get`
- `project.agents_md.update`

These names move into the Core workbench operation set. Members may not shadow them.

### HTTP

- `GET /api/core/projects`
- `POST /api/core/projects`
- `GET /api/core/projects/{project_id}`
- `PATCH /api/core/projects/{project_id}`
- `DELETE /api/core/projects/{project_id}`
- `GET /api/core/projects/{project_id}/sessions`
- `GET /api/core/projects/{project_id}/agents-md`
- `PUT /api/core/projects/{project_id}/agents-md`

### CLI

- `core project list`
- `core project create <work_root> [--name <name>]`
- `core project show <project_id>`
- `core project rename <project_id> <name>`
- `core project delete <project_id>`
- `core project agents get <project_id>`
- `core project agents set <project_id> <file>`

## Core UI

The left sidebar groups sessions by persisted project. Each group shows:

- Project name.
- Absolute project path.
- Associated sessions and their runtime status.
- New-session action scoped to the project.
- Project actions for rename, edit `AGENTS.md`, and delete record.

The global add action opens a Core-owned new-project form with name and work-root fields. Submitting creates the directory, project, and initial session, then selects that session.

The `AGENTS.md` editor uses a Core-owned reusable component and shows explicit loading, save, missing-file, and error states.

## Writer Migration

Writer adapts its existing project records to the Core project contract during this slice:

- Writer UI imports the Core project creation/grouping/editor components.
- Writer App Server registers Core project handlers and supplies Writer persistence adapters where existing Writer IDs must be preserved.
- Writer-specific Git initialization is removed from ordinary project creation.
- Existing Writer project and session data remain readable; no destructive database migration is required.

Writer may retain product-specific project panels and Git workflows, but project name/path/session grouping/`AGENTS.md` behavior must flow through Core contracts.

## Errors And Safety

- Empty work root: validation error.
- Path cannot be created: return the operating-system error without creating a DB record.
- Duplicate normalized path: return/reuse the existing project deterministically.
- Active session during project deletion: reject until stopped.
- Disk directory deletion: never performed by project deletion.
- `AGENTS.md` encoding: UTF-8 only.
- Partial failure after project insert but before initial session creation: roll back the database transaction; the newly created empty directory may remain.

## Testing And Acceptance

Backend tests must prove:

- Missing directories are automatically created.
- Equivalent paths deduplicate to one project.
- Projects and session associations survive service restart.
- Creating a project creates and selects an initial session contractually.
- `AGENTS.md` missing/read/write behavior uses the real file.
- Project deletion removes records but leaves disk files and directories untouched.
- Active sessions block project deletion.
- No Git command is invoked and no `.git` directory is created.
- HTTP, App Server, and CLI return consistent project data.

Frontend tests must prove:

- Sidebar grouping uses persisted project IDs and paths.
- New-project success selects the initial session.
- New sessions inherit project ID and work root.
- `AGENTS.md` editor handles load, save, missing, and failure states.
- Writer consumes Core project UI/contracts without duplicating the generic implementation.

Final acceptance uses an isolated data directory and work root, restarts Core, verifies grouping and `AGENTS.md`, then confirms project deletion leaves the directory intact.
