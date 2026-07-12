import asyncio
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.app_server.operations import (
    handle_project_create_operation,
    handle_project_delete_operation,
    handle_project_session_create_operation,
)
from app.core.writer.git import WriterGitManager
from app.database import Base
from app.models.project import WriterProject
from app.models.session import WriterSession
from app.routers.project import ProjectCreate, ProjectUpdate, create_project, list_projects, update_project
from app.routers.session import SessionCreate, SessionUpdate, create_session, update_session


@pytest.mark.asyncio
async def test_project_work_root_dedupe_merges_sessions():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        work_root = str((root / "e2e-full").resolve())

        engine = create_async_engine(f"sqlite+aiosqlite:///{root / 'test.db'}", future=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with session_factory() as db:
            canonical = WriterProject(
                id="project-good",
                name="e2e-full",
                work_root=work_root,
            )
            duplicate = WriterProject(
                id="project-duplicate",
                name="Untitled Project",
                work_root=work_root,
                agents_md="duplicate agents",
            )
            db.add_all([canonical, duplicate])
            db.add(
                WriterSession(
                    id="session-on-duplicate",
                    title="Duplicate session",
                    work_root=work_root,
                    project_id=duplicate.id,
                )
            )
            await db.commit()

            projects = await list_projects(limit=50, offset=0, db=db)
            matching = [project for project in projects if project.work_root == work_root]
            assert len(matching) == 1
            assert matching[0].id == canonical.id
            assert matching[0].name == "e2e-full"

            session = (
                await db.execute(
                    select(WriterSession).where(WriterSession.id == "session-on-duplicate")
                )
            ).scalar_one()
            assert session.project_id == canonical.id

        await engine.dispose()

        reopened_engine = create_async_engine(f"sqlite+aiosqlite:///{root / 'test.db'}", future=True)
        reopened_factory = async_sessionmaker(reopened_engine, expire_on_commit=False)
        async with reopened_factory() as db:
            projects = (await db.execute(select(WriterProject).where(WriterProject.work_root == work_root))).scalars().all()
            session = await db.get(WriterSession, "session-on-duplicate")
            assert [project.id for project in projects] == ["project-good"]
            assert session is not None
            assert session.project_id == "project-good"
        await reopened_engine.dispose()

@pytest.mark.asyncio
async def test_create_project_creates_missing_work_root():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        work_root = root / "missing" / "writer-workspace"

        engine = create_async_engine(f"sqlite+aiosqlite:///{root / 'test.db'}", future=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with session_factory() as db:
            project = await create_project(ProjectCreate(work_root=str(work_root), name="Custom REST Project"), db)

            assert work_root.is_dir()
            assert project.work_root == str(work_root.resolve())
            assert project.name == "Custom REST Project"

        await engine.dispose()


@pytest.mark.asyncio
async def test_writer_blank_create_name_uses_workspace_default_and_project_update_rejects_agents_cache(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'project-validation.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        work_root = tmp_path / "workspace"
        async with session_factory() as db:
            project = await create_project(ProjectCreate(work_root=str(work_root), name="   "), db)
            assert project.name == "workspace"

            with pytest.raises(Exception, match="project.agents_md.update"):
                await update_project(project.id, ProjectUpdate(agents_md="stale cache"), db)
            with pytest.raises(Exception, match="Project name is required"):
                await update_project(project.id, ProjectUpdate(name="   "), db)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_duplicate_project_create_preserves_the_existing_renamed_project_name(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'project-name.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        work_root = str((tmp_path / "workspace").resolve())
        async with session_factory() as db:
            first = await create_project(ProjectCreate(work_root=work_root, name="Renamed by user"), db)
            duplicate = await create_project(ProjectCreate(work_root=work_root, name="New default"), db)

            assert duplicate.id == first.id
            assert duplicate.name == "Renamed by user"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_project_session_creation_rejects_missing_or_deleted_projects(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'project-session.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        created = await handle_project_create_operation(
            request_id=1,
            params={"work_root": str(tmp_path / "workspace")},
            session_factory=session_factory,
        )
        project_id = created.response["result"]["project"]["id"]
        session = await handle_project_session_create_operation(
            request_id=2,
            params={"project_id": project_id, "title": "Inside project"},
            session_factory=session_factory,
        )
        assert session.response["result"]["session"]["project_id"] == project_id

        deleted = await handle_project_delete_operation(
            request_id=3,
            params={"project_id": project_id},
            session_factory=session_factory,
        )
        assert deleted.response["result"] == {"deleted": True}
        missing = await handle_project_session_create_operation(
            request_id=4,
            params={"project_id": project_id},
            session_factory=session_factory,
        )
        assert missing.response["error"]["message"] == "Project not found"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_project_delete_and_session_create_race_leaves_no_orphan(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'project-session-race.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        created = await handle_project_create_operation(
            request_id=1,
            params={"work_root": str(tmp_path / "workspace")},
            session_factory=session_factory,
        )
        project_id = created.response["result"]["project"]["id"]
        deleted, session = await asyncio.gather(
            handle_project_delete_operation(
                request_id=2,
                params={"project_id": project_id},
                session_factory=session_factory,
            ),
            handle_project_session_create_operation(
                request_id=3,
                params={"project_id": project_id},
                session_factory=session_factory,
            ),
        )

        assert deleted.response["result"] == {"deleted": True}
        assert "result" in session.response or session.response["error"]["message"] == "Project not found"
        async with session_factory() as db:
            assert await db.get(WriterProject, project_id) is None
            assert (await db.execute(select(WriterSession).where(WriterSession.project_id == project_id))).scalars().all() == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_writer_project_create_never_initializes_git(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'project-create.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def forbidden(*args, **kwargs):
        raise AssertionError("Git initialization must not run")

    monkeypatch.setattr(WriterGitManager, "init_repo", forbidden)
    work_root = tmp_path / "workspace"
    try:
        outcome = await handle_project_create_operation(
            request_id=1,
            params={"work_root": str(work_root)},
            session_factory=session_factory,
        )

        project = outcome.response["result"]["project"]
        assert project["work_root"] == str(work_root.resolve())
        assert not (work_root / ".git").exists()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["running", "waiting", "interrupting"])
async def test_writer_project_delete_rejects_active_sessions(tmp_path, status):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'project-delete.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with session_factory() as db:
            project = WriterProject(id="project-active", name="Active", work_root=str(tmp_path))
            db.add(project)
            db.add(WriterSession(
                id=f"session-{status}",
                title="Active session",
                work_root=str(tmp_path),
                project_id=project.id,
                status=status,
            ))
            await db.commit()

        outcome = await handle_project_delete_operation(
            request_id=1,
            params={"project_id": "project-active"},
            session_factory=session_factory,
        )

        assert outcome.response["error"]["data"]["code"] == 409
        async with session_factory() as db:
            assert await db.get(WriterProject, "project-active") is not None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_create_session_creates_missing_work_root():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        work_root = root / "missing-session-workspace"

        engine = create_async_engine(f"sqlite+aiosqlite:///{root / 'test.db'}", future=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with session_factory() as db:
            session = await create_session(
                SessionCreate(title="New workspace", work_root=str(work_root)),
                db,
            )

            assert work_root.is_dir()
            assert session["work_root"] == str(work_root.resolve())

        await engine.dispose()


@pytest.mark.asyncio
async def test_rest_session_create_and_work_root_update_never_initialize_git(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'rest-session-git.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    created_root = tmp_path / "rest-created"
    updated_root = tmp_path / "rest-updated"
    try:
        async with session_factory() as db:
            created = await create_session(
                SessionCreate(title="REST no Git", work_root=str(created_root)),
                db,
            )
            assert created_root.is_dir()
            assert not (created_root / ".git").exists()

            updated = await update_session(
                created["id"],
                SessionUpdate(work_root=str(updated_root)),
                db,
            )
            assert updated["work_root"] == str(updated_root.resolve())
            assert updated_root.is_dir()
            assert not (updated_root / ".git").exists()
    finally:
        await engine.dispose()
