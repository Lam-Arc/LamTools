# Core Project Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Core-owned projects with persisted name/path, project-grouped sessions, real `AGENTS.md` editing, and no Git initialization, then migrate Writer to consume the Core contracts.

**Architecture:** Add `CoreProject` beside existing Core thread snapshots and expose one project service through HTTP, App Server operations, CLI, and Core UI. Sessions retain `project_id` and `work_root` in snapshot metadata. Writer adapts its existing persistence to the Core contract and imports Core UI components while retaining only product additions.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy async + SQLite, argparse, Vue 3, TypeScript 6, Vite 8, Vitest 4, pytest 9.

## Global Constraints

- Create missing work-root directories and parent directories.
- Never initialize Git or create `.git` during project creation.
- Never delete the work-root directory or disk files during project deletion.
- Use the real UTF-8 `<work_root>/AGENTS.md`; DB content is not authoritative.
- Normalize work roots to unique absolute paths; duplicate creation reuses the existing project.
- Reject deletion while associated sessions are running, waiting, or interrupting.
- Core owns generic project identity, grouping, paths, session association, and `AGENTS.md`.
- HTTP, App Server, CLI, and GUI use the same project semantics.

## File Map

- Create `core/src/lamtools_core/app/project_store.py`: project CRUD, directory creation, session association, `AGENTS.md` access.
- Modify `core/src/lamtools_core/app/core_db.py`: `CoreProject` table.
- Modify `core/src/lamtools_core/app/core_session_store.py`: project-aware session queries.
- Modify `core/src/lamtools_core/app/http_agent_app.py`, `core/src/lamtools_core/http/routes.py`, and `core/src/lamtools_core/app/operation_groups.py`: shared project interfaces.
- Modify `core/src/lamtools_core/cli.py`: project CLI.
- Create `core/ui/src/projects/`: public project client/types.
- Create `core/ui/src/components/CoreProjectCreate.vue` and `CoreAgentsEditor.vue`: shared UI.
- Modify `core/ui/src/demo/App.vue`: persisted grouping and actions.
- Modify Writer backend/frontend only as Core contract adapters.

---

### Task 1: Core Project Persistence And Filesystem

**Files:**
- Create: `core/src/lamtools_core/app/project_store.py`
- Modify: `core/src/lamtools_core/app/core_db.py`
- Modify: `core/src/lamtools_core/app/__init__.py`
- Test: `core/tests/test_core_project_store.py`

**Interfaces:**
- Produces `CoreProjectRecord` and `CoreProjectStore`.
- `create(work_root, name=None) -> tuple[CoreProjectRecord, bool]`.
- `list()`, `get(project_id)`, `rename(project_id, name)`, `delete(project_id)`.
- `read_agents_md(project_id)` and `write_agents_md(project_id, content)`.

- [ ] **Step 1: Write failing project and file tests**

```python
@pytest.mark.asyncio
async def test_create_project_creates_directory_deduplicates_and_skips_git(tmp_path):
    db = await open_core_app_db(tmp_path / "core.db")
    store = CoreProjectStore(db)
    root = tmp_path / "missing" / "workspace"
    first, created = await store.create(root, name="Docs")
    second, duplicate_created = await store.create(root / ".", name="Ignored")
    assert root.is_dir()
    assert (created, duplicate_created) == (True, False)
    assert second.id == first.id
    assert second.name == "Docs"
    assert not (root / ".git").exists()
    await db.close()

@pytest.mark.asyncio
async def test_agents_file_and_project_delete_leave_disk_content(tmp_path):
    db = await open_core_app_db(tmp_path / "core.db")
    store = CoreProjectStore(db)
    project, _ = await store.create(tmp_path / "workspace")
    assert await store.read_agents_md(project.id) == {"content": "", "exists": False}
    await store.write_agents_md(project.id, "使用 UTF-8。\n")
    await store.delete(project.id)
    assert (tmp_path / "workspace" / "AGENTS.md").read_text(encoding="utf-8") == "使用 UTF-8。\n"
    await db.close()
```

- [ ] **Step 2: Verify RED**

Run from `core/`: `py -3.14 -m pytest tests/test_core_project_store.py -q`.

Expected: import failure because the project store and table do not exist.

- [ ] **Step 3: Implement the minimal table and store**

```python
class CoreProject(CoreDbBase):
    __tablename__ = "core_projects"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    work_root: Mapped[str] = mapped_column(String(2048), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
```

Normalize with `Path(work_root).expanduser().resolve()`, create with `mkdir(parents=True, exist_ok=True)`, derive the default name from the final path segment, and read/write only `<work_root>/AGENTS.md` using UTF-8. Do not import a Git module.

- [ ] **Step 4: Verify GREEN**

Run: `py -3.14 -m pytest tests/test_core_project_store.py tests/test_core_runtime_persistence.py -q`.

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add core/src/lamtools_core/app/project_store.py core/src/lamtools_core/app/core_db.py core/src/lamtools_core/app/__init__.py core/tests/test_core_project_store.py
git commit -m "feat(core): add persistent project workspaces"
```

### Task 2: Project Sessions, HTTP, And App Server

**Files:**
- Modify: `core/src/lamtools_core/app/project_store.py`
- Modify: `core/src/lamtools_core/app/core_session_store.py`
- Modify: `core/src/lamtools_core/app/http_agent_app.py`
- Modify: `core/src/lamtools_core/app/operation_groups.py`
- Modify: `core/src/lamtools_core/http/routes.py`
- Test: `core/tests/test_core_project_store.py`
- Test: `core/tests/test_core_http_agent_app.py`
- Test: `core/tests/test_operation_groups.py`

**Interfaces:**
- Adds `create_with_initial_session()`, `list_sessions(project_id)`, and `delete_with_sessions()`.
- Adds Core operations `project.list/create/get/update/delete/sessions.list/agents_md.get/agents_md.update`.
- Adds matching `/api/core/projects` HTTP routes.
- `project.create` returns `{"project": project, "session": initial_session}`.

- [ ] **Step 1: Write failing lifecycle and interface tests**

```python
def test_project_http_round_trip_survives_restart(tmp_path):
    with core_client(tmp_path) as client:
        root = tmp_path / "workspace"
        created = client.post("/api/core/projects", json={"name": "Docs", "work_root": str(root)})
        assert created.status_code == 201
        result = created.json()
        project_id = result["project"]["id"]
        assert result["session"]["metadata"] == {"project_id": project_id, "work_root": str(root.resolve())}
    with core_client(tmp_path) as restarted:
        assert restarted.get(f"/api/core/projects/{project_id}").json()["name"] == "Docs"

def test_core_owns_project_operations():
    names = set(CORE_WORKBENCH_OPERATION_NAMES)
    assert {"project.list", "project.create", "project.get", "project.update", "project.delete",
            "project.sessions.list", "project.agents_md.get", "project.agents_md.update"} <= names
```

Add tests that `AGENTS.md` HTTP read/write uses the real file and active sessions cause project deletion to return `409`.

- [ ] **Step 2: Verify RED**

Run: `py -3.14 -m pytest tests/test_core_project_store.py tests/test_core_http_agent_app.py tests/test_operation_groups.py -q`.

Expected: project endpoints return 404 and operation names are absent.

- [ ] **Step 3: Implement one transactional lifecycle**

Create project plus initial `CoreThreadSnapshot` through the existing write coordinator. Store `project_id` and `work_root` in session metadata. On deletion, reject active statuses, then delete associated event/runtime/snapshot rows and the project row in one coordinated write. Register the same store methods in HTTP and App Server handlers.

- [ ] **Step 4: Verify GREEN**

Run: `py -3.14 -m pytest tests/test_core_project_store.py tests/test_core_http_agent_app.py tests/test_operation_groups.py tests/test_core_live_client_e2e.py -q`.

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add core/src/lamtools_core/app/project_store.py core/src/lamtools_core/app/core_session_store.py core/src/lamtools_core/app/http_agent_app.py core/src/lamtools_core/app/operation_groups.py core/src/lamtools_core/http/routes.py core/tests/test_core_project_store.py core/tests/test_core_http_agent_app.py core/tests/test_operation_groups.py
git commit -m "feat(core): expose project workspace contracts"
```

### Task 3: Core Project CLI

**Files:**
- Modify: `core/src/lamtools_core/cli.py`
- Modify: `core.cmd`
- Modify: `scripts/core.cmd`
- Test: `core/tests/test_core_cli.py`

**Interfaces:**
- Produces `core project list/create/show/rename/delete`.
- Produces `core project agents get/set`.
- Uses `CoreProjectStore`; no duplicate SQL/filesystem code.

- [ ] **Step 1: Write failing CLI tests**

```python
def test_core_project_cli_creates_workspace_and_round_trips_agents(tmp_path, capsys):
    rules = tmp_path / "rules.md"
    rules.write_text("# Core rules\n", encoding="utf-8")
    assert main(["project", "create", str(tmp_path / "workspace"), "--name", "Docs"]) == 0
    project_id = parse_project_id(capsys.readouterr().out)
    assert main(["project", "agents", "set", project_id, str(rules)]) == 0
    assert main(["project", "agents", "get", project_id]) == 0
    assert "# Core rules" in capsys.readouterr().out
```

- [ ] **Step 2: Verify RED**

Run: `py -3.14 -m pytest tests/test_core_cli.py -q`.

Expected: argparse rejects `project`.

- [ ] **Step 3: Implement CLI subcommands**

Resolve the same Core DB as `serve`, open `CoreProjectStore`, execute its methods, print stable IDs/names/paths, and close the DB. `agents set` reads the supplied file as UTF-8 before calling the store.

- [ ] **Step 4: Verify GREEN**

Run: `py -3.14 -m pytest tests/test_core_cli.py tests/test_core_project_store.py -q`.

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add core/src/lamtools_core/cli.py core.cmd scripts/core.cmd core/tests/test_core_cli.py
git commit -m "feat(core): add project workspace CLI"
```

### Task 4: Shared Core Project UI And Demo

**Files:**
- Create: `core/ui/src/projects/types.ts`
- Create: `core/ui/src/projects/client.ts`
- Create: `core/ui/src/components/CoreProjectCreate.vue`
- Create: `core/ui/src/components/CoreAgentsEditor.vue`
- Modify: `core/ui/src/demo/App.vue`
- Modify: `core/ui/src/index.ts`
- Test: `core/ui/tests/core-project-client.test.ts`
- Test: `core/ui/tests/core-project-components.test.ts`
- Test: `core/ui/tests/core-project-demo.test.ts`

**Interfaces:**
- `createCoreProjectClient(apiBase)` exposes list/create/get/rename/delete/listSessions/readAgents/writeAgents.
- `CoreProjectCreate` emits `submit({name, work_root})` and `cancel()`.
- `CoreAgentsEditor` emits `save(content)` and `close()`.

- [ ] **Step 1: Write failing client/component/grouping tests**

```ts
it('submits name and path without a Git option', async () => {
  const wrapper = mount(CoreProjectCreate)
  await wrapper.get('[data-project-name]').setValue('Docs')
  await wrapper.get('[data-project-root]').setValue('E:\\docs')
  await wrapper.get('form').trigger('submit')
  expect(wrapper.emitted('submit')).toEqual([[{ name: 'Docs', work_root: 'E:\\docs' }]])
  expect(wrapper.text()).not.toContain('Git')
})

it('groups sessions by persisted project and displays its path', () => {
  const groups = buildCoreProjectGroups(projects, sessions)
  expect(groups[0]).toMatchObject({ id: 'project-1', name: 'Docs', workRoot: 'E:\\docs' })
})
```

- [ ] **Step 2: Verify RED**

Run from `core/ui/`: `npm exec vitest run tests/core-project-client.test.ts tests/core-project-components.test.ts tests/core-project-demo.test.ts`.

Expected: missing modules/components/helper.

- [ ] **Step 3: Implement shared UI and replace the synthetic group**

Use existing Core controls and states. The global plus opens project creation; success selects the returned initial session. Per-project plus creates a session with project metadata. Sidebar groups show project name/path. Project actions support rename, `AGENTS.md`, and safe record deletion. Keep one “Unassigned” compatibility group for historical sessions without `project_id`.

- [ ] **Step 4: Verify GREEN**

Run: `npm run test:contract; npm run typecheck; npm run build`.

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add core/ui/src/projects core/ui/src/components/CoreProjectCreate.vue core/ui/src/components/CoreAgentsEditor.vue core/ui/src/demo/App.vue core/ui/src/index.ts core/ui/tests/core-project-client.test.ts core/ui/tests/core-project-components.test.ts core/ui/tests/core-project-demo.test.ts
git commit -m "feat(core-ui): add project workspaces"
```

### Task 5: Writer Core-Contract Migration

**Files:**
- Modify: `members/writer/backend/app/app_server/operations.py`
- Modify: `members/writer/backend/app/services/project_management.py`
- Modify: `members/writer/backend/app/routers/project.py`
- Modify: `members/writer/frontend/src/views/CoreWorkbenchView.vue`
- Test: `members/writer/backend/tests/test_project_crud.py`
- Test: `members/writer/backend/tests/test_writer_app_server_protocol.py`
- Test: `members/writer/frontend/tests/runtime/coreProjectBoundary.test.ts`

**Interfaces:**
- Writer handlers implement Core-owned `project.*` payloads while preserving Writer IDs/extra fields.
- Writer imports `CoreProjectCreate` and `CoreAgentsEditor`.

- [ ] **Step 1: Write failing Git and UI-boundary tests**

```python
@pytest.mark.asyncio
async def test_writer_project_create_never_initializes_git(tmp_path, monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError("Git initialization must not run")
    monkeypatch.setattr(WriterGitManager, "init_repo", forbidden)
    project = await create_project_through_operation(tmp_path / "workspace")
    assert project["work_root"] == str((tmp_path / "workspace").resolve())
    assert not (tmp_path / "workspace" / ".git").exists()
```

```ts
test('Writer delegates generic project UI to Core', () => {
  assert.match(viewSource, /CoreProjectCreate/)
  assert.match(viewSource, /CoreAgentsEditor/)
  assert.doesNotMatch(viewSource, /class="new-project-popover"/)
})
```

- [ ] **Step 2: Verify RED**

Run backend from `members/writer/`: `py -3.14 -m pytest backend/tests/test_project_crud.py backend/tests/test_writer_app_server_protocol.py -q`.

Run frontend from `members/writer/frontend/`: `npm test`.

Expected: Git guard or duplicate UI assertion fails.

- [ ] **Step 3: Implement Writer adapters**

Remove ordinary creation calls to `WriterGitManager.init_repo`. Register Writer persistence handlers through the Core operation adapter instead of shadowing Core names. Replace Writer’s local project form and `AGENTS.md` editor with Core components; preserve product additions through props/slots.

- [ ] **Step 4: Verify GREEN**

Run backend targeted tests, then `npm run lint; npm test; npm run build` in Writer frontend.

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add members/writer/backend/app/app_server/operations.py members/writer/backend/app/services/project_management.py members/writer/backend/app/routers/project.py members/writer/backend/tests/test_project_crud.py members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/frontend/src/views/CoreWorkbenchView.vue members/writer/frontend/tests/runtime/coreProjectBoundary.test.ts
git commit -m "refactor(writer): use core project workspaces"
```

### Task 6: Full And Real Acceptance

**Files:**
- Create: `core/tests/test_core_project_acceptance.py` only when the real sequence lacks automated coverage.
- Modify: project ownership documentation that still states projects are Writer-only.

- [ ] **Step 1: Run full automated verification**

```powershell
.\scripts\test.ps1 all
.\scripts\build.ps1 all
git diff --check
```

Expected: all tests/builds pass and no whitespace errors.

- [ ] **Step 2: Run isolated real-service acceptance**

Start Core with isolated Core DB/data/work-root. Create a missing project directory, verify no `.git`, verify initial session metadata, save/read non-ASCII `AGENTS.md`, restart Core and verify grouping, confirm active deletion returns `409`, then stop/delete and prove the directory and file remain.

- [ ] **Step 3: Verify CLI parity**

```powershell
.\core.cmd project list
.\core.cmd project show <acceptance-project-id>
.\writer.cmd project list
```

Expected: shared project fields align; Writer may include additions.

- [ ] **Step 4: Scan ownership boundaries**

```powershell
rg -n "new-project-popover|WriterGitManager.*init_repo|project\.create|project\.agents_md" core members/writer
```

Expected: contracts/components live in Core; Writer contains adapters and product additions only; creation has no Git initialization.

- [ ] **Step 5: Commit acceptance/docs**

```powershell
git add core/tests/test_core_project_acceptance.py docs
git commit -m "test: verify core project workspace flow"
```
