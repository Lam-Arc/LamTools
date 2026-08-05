from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.app_server.artifacts import open_artifact, read_artifact
from app.database import Base
from app.models.app_server import WriterArtifact


@pytest.mark.asyncio
async def test_artifact_read_returns_metadata_for_same_thread(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'artifacts.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with session_factory() as db:
            db.add(
                WriterArtifact(
                    artifact_id="artifact-1",
                    thread_id="thread-1",
                    turn_id="turn-1",
                    item_id="item-1",
                    kind="text",
                    name="report.txt",
                    path=str(tmp_path / "report.txt"),
                    mime_type="text/plain",
                    size_bytes=12,
                    metadata_={"preview": "ok"},
                )
            )
            await db.commit()

            artifact = await read_artifact(db, thread_id="thread-1", artifact_id="artifact-1")

            assert artifact["artifact_id"] == "artifact-1"
            assert artifact["thread_id"] == "thread-1"
            assert artifact["metadata"] == {"preview": "ok"}

            with pytest.raises(LookupError):
                await read_artifact(db, thread_id="other-thread", artifact_id="artifact-1")
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_artifact_open_validates_path_and_uses_injected_opener(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'open-artifacts.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    artifact_path = tmp_path / "report.txt"
    artifact_path.write_text("hello", encoding="utf-8")
    opened: list[str] = []

    try:
        async with session_factory() as db:
            db.add(
                WriterArtifact(
                    artifact_id="artifact-1",
                    thread_id="thread-1",
                    kind="text",
                    name="report.txt",
                    path=str(artifact_path),
                    mime_type="text/plain",
                    size_bytes=5,
                )
            )
            await db.commit()

            artifact = await open_artifact(
                db,
                thread_id="thread-1",
                artifact_id="artifact-1",
                opener=opened.append,
            )

            assert artifact["opened"] is True
            assert opened == [str(artifact_path)]

            artifact_path.unlink()
            with pytest.raises(FileNotFoundError):
                await open_artifact(db, thread_id="thread-1", artifact_id="artifact-1", opener=opened.append)
    finally:
        await engine.dispose()
