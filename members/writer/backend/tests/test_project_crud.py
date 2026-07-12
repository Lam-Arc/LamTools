import tempfile
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
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
