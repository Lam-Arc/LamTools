import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.session import WriterSession
from app.models.transcript import WriterTranscriptBlock
from app.services.transcript_service import (
    close_active_producers,
    create_turn,
    derive_turn_status,
    ensure_active_producer,
    ensure_model_call,
    mark_turn_terminal,
    project_transcript,
    upsert_block,
)


@pytest.mark.asyncio
async def test_transcript_status_is_projected_from_facts(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'transcript.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        session = WriterSession(id="session-1", title="Test")
        db.add(session)
        await db.commit()

        turn = await create_turn(db, session_id=session.id, user_text="开始", user_message_id=None)
        call = await ensure_model_call(db, turn=turn, run_id="call-1")
        await ensure_active_producer(db, turn=turn, producer_id="producer-1", model_call_id=call.id)
        await db.commit()

        assert await derive_turn_status(db, turn) == "running"

        await close_active_producers(db, turn_id=turn.id, reason="waiting")
        await upsert_block(
            db,
            turn=turn,
            block_id="wait-1",
            model_call_id=call.id,
            block_type="waiting_request",
            sequence=1,
            event_sequence=1,
            status="waiting",
            content="是否继续？",
            producer_id="producer-1",
            request_kind="permission",
        )
        await db.commit()

        assert await derive_turn_status(db, turn) == "waiting"

        wait_block = await upsert_block(
            db,
            turn=turn,
            block_id="wait-1",
            model_call_id=call.id,
            block_type="waiting_request",
            sequence=1,
            event_sequence=1,
            status="completed",
            content="是否继续？",
            producer_id="producer-1",
            request_kind="permission",
            response_json={"answer": "yes"},
        )
        assert wait_block.completed_at is not None
        await ensure_active_producer(db, turn=turn, producer_id="producer-2", model_call_id=call.id)
        await db.commit()

        assert await derive_turn_status(db, turn) == "running"

        final = await upsert_block(
            db,
            turn=turn,
            block_id="final-1",
            model_call_id=call.id,
            block_type="model_text",
            sequence=2,
            event_sequence=2,
            status="completed",
            content="完成。",
            producer_id="producer-2",
        )
        turn.final_reply_block_id = final.id
        await close_active_producers(db, turn_id=turn.id, reason="completed")
        await db.commit()

        assert await derive_turn_status(db, turn) == "completed"
        projected = await project_transcript(db, session.id)
        assert projected["status"] == "idle"
        assert projected["turns"][0]["status"] == "completed"
        assert turn.status_cache == "completed"
        assert projected["turns"][0]["final_reply_block_id"] == "final-1"
        assert projected["turns"][0]["model_calls"][0]["blocks"][1]["is_final_reply"] is True
        assert projected["revision"] > 0


@pytest.mark.asyncio
async def test_transcript_failed_requires_terminal_fact_without_final_reply(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'failed.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        session = WriterSession(id="session-1", title="Test")
        db.add(session)
        await db.commit()

        turn = await create_turn(db, session_id=session.id, user_text="开始", user_message_id=None)
        call = await ensure_model_call(db, turn=turn, run_id="call-1")
        await ensure_active_producer(db, turn=turn, producer_id="producer-1", model_call_id=call.id)
        await mark_turn_terminal(db, turn=turn, reason="user_stop", error="用户停止")
        await db.commit()

        assert await derive_turn_status(db, turn) == "failed"
        projected = await project_transcript(db, session.id)
        assert projected["status"] == "failed"
        assert projected["turns"][0]["status"] == "failed"
        assert turn.status_cache == "failed"


@pytest.mark.asyncio
async def test_stale_status_cache_does_not_make_turn_running(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'stale-cache.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        session = WriterSession(id="session-1", title="Test")
        db.add(session)
        await db.commit()

        turn = await create_turn(db, session_id=session.id, user_text="开始", user_message_id=None)
        turn.status_cache = "running"
        await db.commit()

        assert await derive_turn_status(db, turn) == "failed"
        projected = await project_transcript(db, session.id)
        assert projected["status"] == "failed"
        assert projected["turns"][0]["status"] == "failed"


@pytest.mark.asyncio
async def test_completed_block_insert_gets_terminal_timestamp(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'completed-block.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        session = WriterSession(id="session-1", title="Test")
        db.add(session)
        await db.commit()

        turn = await create_turn(db, session_id=session.id, user_text="开始", user_message_id=None)
        call = await ensure_model_call(db, turn=turn, run_id="call-1")
        block = await upsert_block(
            db,
            turn=turn,
            block_id="tool-result-1",
            model_call_id=call.id,
            block_type="tool_result",
            sequence=1,
            event_sequence=1,
            status="completed",
            content="ok",
            tool_name="read_file",
            tool_call_id="tool-1",
        )
        await db.commit()

        assert block.completed_at is not None
        assert block.duration_ms is not None


@pytest.mark.asyncio
async def test_projected_completed_block_without_completed_at_has_unknown_duration(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'legacy-duration.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        session = WriterSession(id="session-1", title="Test")
        db.add(session)
        await db.commit()

        turn = await create_turn(db, session_id=session.id, user_text="开始", user_message_id=None)
        call = await ensure_model_call(db, turn=turn, run_id="call-1")
        db.add(WriterTranscriptBlock(
            id="legacy-result",
            turn_id=turn.id,
            model_call_id=call.id,
            sequence=1,
            event_sequence=1,
            type="tool_result",
            status="completed",
            content="legacy",
            tool_name="read_file",
            tool_call_id="tool-1",
        ))
        await db.commit()

        projected = await project_transcript(db, session.id)
        block = projected["turns"][0]["model_calls"][0]["blocks"][0]

        assert block["duration_ms"] is None
