import tempfile
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.app_server.operations import handle_project_create_operation, handle_project_delete_operation
from app.core.writer.git import WriterGitManager
from app.database import Base
from app.models.project import WriterProject
from app.models.session import WriterSession
from app.routers.project import ProjectCreate, create_project, list_projects
from app.routers.session import SessionCreate, create_session


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

            project = await create_project(ProjectCreate(work_root=work_root), db)
            assert project.id == canonical.id

        await engine.dispose()

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
