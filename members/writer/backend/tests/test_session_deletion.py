import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.app_server import WriterAppEvent, WriterArtifact, WriterThreadSnapshot
from app.models.attachment import WriterAttachment
from app.models.message import WriterMessage
from app.models.session import WriterSession
from app.services.session_deletion import delete_writer_session_records


@pytest.mark.asyncio
async def test_delete_writer_session_records_removes_thread_records(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'session-delete.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with session_factory() as db:
            db.add(WriterSession(id="session-delete", title="Delete me", work_root=""))
            db.add(WriterMessage(id="message-delete", session_id="session-delete", role="user", content="hello"))
            db.add(
                WriterAttachment(
                    id="attachment-delete",
                    session_id="session-delete",
                    filename="note.txt",
                    storage_path=str(tmp_path / "note.txt"),
                )
            )
            db.add(
                WriterAppEvent(
                    event_id="event-delete",
                    thread_id="session-delete",
                    seq=1,
                    method="thread/test",
                    payload_json={"thread_id": "session-delete"},
                )
            )
            db.add(
                WriterThreadSnapshot(
                    thread_id="session-delete",
                    snapshot_seq=1,
                    snapshot_json={"thread_id": "session-delete"},
                )
            )
            db.add(
                WriterArtifact(
                    artifact_id="artifact-delete",
                    thread_id="session-delete",
                    kind="file",
                    name="note.txt",
                    path=str(tmp_path / "note.txt"),
                )
            )
            await db.commit()

        async with session_factory() as db:
            await delete_writer_session_records(db, "session-delete")
            await db.commit()

        async with session_factory() as db:
            assert await db.get(WriterSession, "session-delete") is None
            assert await db.get(WriterMessage, "message-delete") is None
            assert await db.get(WriterAttachment, "attachment-delete") is None
            assert await db.get(WriterAppEvent, "event-delete") is None
            assert await db.get(WriterThreadSnapshot, "session-delete") is None
            assert await db.get(WriterArtifact, "artifact-delete") is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_delete_writer_session_records_rejects_running_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'active-session-delete.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with session_factory() as db:
            db.add(WriterSession(id="session-running", title="Running", work_root="", status="running"))
            await db.commit()

            with pytest.raises(ValueError, match="Stop the active session"):
                await delete_writer_session_records(db, "session-running")
            assert await db.get(WriterSession, "session-running") is not None
    finally:
        await engine.dispose()
