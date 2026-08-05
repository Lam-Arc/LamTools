from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.config import Settings
from app.core.writer.core_kernel_adapter import run_core_kernel
from app.models.base import now
from app.models.message import WriterMessage
from app.models.session import WriterSession
from app.models.transcript import WriterTranscriptTurn
from app.services import writer_service as writer_service_module
from app.services.runtime_input_context import prepare_runtime_input_context
from app.services.session_compaction_service import compact_session_context_response
from lamtools_core.llm import LLMResponse, LLMStreamEvent
from lamtools_core.llm.policy import RetryPolicy


class _FakeLLMClient:
    def __init__(self) -> None:
        self.last_request = None

    async def complete(self, request):
        self.last_request = request
        return LLMResponse(content="done", finish_reason="stop")

    async def stream(self, request):
        raise NotImplementedError


class _CompactionLLMClient(_FakeLLMClient):
    async def complete(self, request):
        self.last_request = request
        return LLMResponse(
            content=(
                "1. Current Goal\n"
                "- Continue.\n\n"
                "2. User History, Instructions, And Decisions\n"
                "- Preserve explicit user decisions from compacted history.\n\n"
                "3. Completed Work\n"
                "- Old turns were summarized by the shared Core compactor.\n\n"
                "4. Key Decisions And Constraints\n"
                "- Use one compaction interface.\n\n"
                "5. Files, APIs, Commands, And Results\n"
                "- None.\n\n"
                "6. Open Issues Or Risks\n"
                "- None.\n\n"
                "7. Next Best Actions\n"
                "- Continue."
            ),
            finish_reason="stop",
        )


class _FailingCompactionLLMClient(_FakeLLMClient):
    async def complete(self, request):
        self.last_request = request
        raise RuntimeError("compaction model unavailable")


class _FlakyCompactionLLMClient(_CompactionLLMClient):
    def __init__(self, *, failures: int) -> None:
        super().__init__()
        self.failures = failures
        self.call_count = 0
        self.stream_count = 0

    async def complete(self, request):
        self.call_count += 1
        self.last_request = request
        return await super().complete(request)

    async def stream(self, request):
        self.stream_count += 1
        self.last_request = request
        if self.failures > 0:
            self.failures -= 1
            raise RuntimeError("transient compaction model unavailable")
        yield LLMStreamEvent(kind="content_delta", content="1. Current Goal\n- Continue.\n\n")
        yield LLMStreamEvent(
            kind="content_delta",
            content=(
                "2. User History, Instructions, And Decisions\n"
                "- Preserve explicit user decisions from compacted history.\n\n"
                "3. Completed Work\n"
                "- Old turns were summarized by the shared Core compactor.\n\n"
                "4. Key Decisions And Constraints\n"
                "- Use one compaction interface.\n\n"
                "5. Files, APIs, Commands, And Results\n"
                "- None.\n\n"
                "6. Open Issues Or Risks\n"
                "- None.\n\n"
                "7. Next Best Actions\n"
                "- Continue."
            ),
        )
        yield LLMStreamEvent(kind="done", metadata={"finish_reason": "stop"})


class _WriterStyleCompactionClient:
    def __init__(self) -> None:
        self.last_messages = None
        self.last_max_tokens = None

    async def chat_full(self, messages, temperature=None, max_tokens=None, *, tools=None):
        self.last_messages = messages
        self.last_max_tokens = max_tokens
        return LLMResponse(
            content=(
                "1. Current Goal\n"
                "- Continue via Writer-style client.\n\n"
                "2. User History, Instructions, And Decisions\n"
                "- Preserve selected command behavior.\n\n"
                "3. Completed Work\n"
                "- Manual compact used Writer client adapter.\n\n"
                "4. Key Decisions And Constraints\n"
                "- Writer client exposes chat_full, not complete.\n\n"
                "5. Files, APIs, Commands, And Results\n"
                "- None.\n\n"
                "6. Open Issues Or Risks\n"
                "- None.\n\n"
                "7. Next Best Actions\n"
                "- Continue."
            ),
            finish_reason="stop",
        )


@pytest.mark.asyncio
async def test_manual_compaction_persists_summary_and_runtime_uses_it(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'compact.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with session_factory() as db:
            db.add(WriterSession(id="s1", title="Compaction"))
            base_time = now()
            db.add(
                WriterTranscriptTurn(
                    id="turn-1",
                    session_id="s1",
                    sequence=1,
                    user_text="继续",
                )
            )
            for index in range(12):
                db.add(
                    WriterMessage(
                        id=f"m-{index}",
                        session_id="s1",
                        role="user" if index % 2 == 0 else "assistant",
                        content=f"message-{index} " + ("x" * 1000),
                        created_at=base_time + timedelta(seconds=index),
                    )
                )
            await db.commit()

            result = await compact_session_context_response(db, session_id="s1")
            await db.refresh(await db.get(WriterSession, "s1"))

            session = await db.get(WriterSession, "s1")
            assert session is not None
            assert result["status"] == "compacted"
            assert result["compacted_messages"] > 0
            assert result["retained_messages"] > 0
            assert result["compacted_message_ids"] + result["retained_message_ids"] == [
                f"m-{index}" for index in range(12)
            ]
            assert result["before_tokens"] > 0
            assert result["after_tokens"] > 0
            assert result["limit_tokens"] == 6000
            assert "message-0" in (session.context_summary or "")
            assert session.runtime_state["manual_compaction"]["retained_message_count"] == result["retained_messages"]
            assert session.runtime_state["manual_compaction"]["compacted_message_ids"] == result["compacted_message_ids"]

            context = await prepare_runtime_input_context(
                db,
                session_id="s1",
                transcript_turn_id="turn-1",
                user_message="继续",
                raw_user_message="继续",
            )

            assert context.history[0] == {"role": "system", "content": session.context_summary}
            assert len(context.history[1:]) == result["retained_messages"]
            assert all(
                item["content"].startswith("message-")
                for item in context.history[1:]
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_manual_compaction_uses_stable_id_tiebreak_for_identical_timestamps(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'compact-tie-break.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with session_factory() as db:
            db.add(WriterSession(id="stable-order", title="Stable Order"))
            db.add(
                WriterTranscriptTurn(
                    id="turn-stable-order",
                    session_id="stable-order",
                    sequence=1,
                    user_text="继续",
                )
            )
            tied_time = now()
            for message_id in ("m-07", "m-03", "m-06", "m-02", "m-05", "m-01", "m-04", "m-00"):
                index = int(message_id.split("-")[1])
                db.add(
                    WriterMessage(
                        id=message_id,
                        session_id="stable-order",
                        role="user" if index % 2 == 0 else "assistant",
                        content=f"message-{index:02d} " + ("x" * 1000),
                        created_at=tied_time,
                    )
                )
            await db.commit()

            result = await compact_session_context_response(db, session_id="stable-order")
            session = await db.get(WriterSession, "stable-order")

            assert session is not None
            assert result["compacted_messages"] == 2
            assert session.runtime_state["manual_compaction"]["compacted_message_ids"] == ["m-00", "m-01"]

            context = await prepare_runtime_input_context(
                db,
                session_id="stable-order",
                transcript_turn_id="turn-stable-order",
                user_message="继续",
                raw_user_message="继续",
            )

            assert context.history[0]["role"] == "system"
            assert [item["content"].split()[0] for item in context.history[1:]] == [
                "message-02", "message-03", "message-04", "message-05", "message-06", "message-07"
            ]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_manual_compaction_uses_shared_model_compactor_when_client_is_provided(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'compact-model.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    llm = _CompactionLLMClient()
    events: list[dict] = []
    try:
        async with session_factory() as db:
            db.add(WriterSession(id="model-compact", title="Model Compact"))
            base_time = now()
            for index in range(8):
                db.add(
                    WriterMessage(
                        id=f"model-{index}",
                        session_id="model-compact",
                        role="user" if index % 2 == 0 else "assistant",
                        content=f"model-message-{index} " + ("x" * 1000),
                        created_at=base_time + timedelta(seconds=index),
                    )
                )
            await db.commit()

            result = await compact_session_context_response(
                db,
                session_id="model-compact",
                llm_client=llm,
                model="mock-compact-model",
                on_summary_event=events.append,
            )

            assert llm.last_request is not None
            assert llm.last_request.model == "mock-compact-model"
            assert "model-message-0" in str(llm.last_request.messages[-1].content)
            assert result["summary"].startswith("[Compacted Context]")
            assert "shared Core compactor" in result["summary"]
            assert events[-1]["status"] == "compacted"
            assert events[-1]["content"] == result["summary"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_manual_compaction_retries_model_calls_with_shared_policy(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'compact-model-retry.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    llm = _FlakyCompactionLLMClient(failures=2)
    events: list[dict] = []
    try:
        async with session_factory() as db:
            db.add(WriterSession(id="model-compact-retry", title="Model Compact Retry"))
            base_time = now()
            for index in range(8):
                db.add(
                    WriterMessage(
                        id=f"model-retry-{index}",
                        session_id="model-compact-retry",
                        role="user" if index % 2 == 0 else "assistant",
                        content=f"model-retry-message-{index} " + ("x" * 1000),
                        created_at=base_time + timedelta(seconds=index),
                    )
                )
            await db.commit()

            result = await compact_session_context_response(
                db,
                session_id="model-compact-retry",
                llm_client=llm,
                model="mock-compact-model",
                on_summary_event=events.append,
                model_retries=3,
                retry_policy=RetryPolicy(
                    initial_delay_seconds=0,
                    max_delay_seconds=0,
                    jitter=False,
                    staged_delay_seconds=(),
                ),
            )

            assert result["status"] == "compacted"
            assert llm.stream_count == 3
            assert llm.call_count == 0
            assert events[-1]["status"] == "compacted"
            session = await db.get(WriterSession, "model-compact-retry")
            assert session is not None
            runtime_state = session.runtime_state if isinstance(session.runtime_state, dict) else {}
            assert "manual_compaction" in runtime_state
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_manual_compaction_model_failure_does_not_persist_fallback_summary(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'compact-model-failure.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    llm = _FailingCompactionLLMClient()
    try:
        async with session_factory() as db:
            db.add(WriterSession(id="model-failure", title="Model Failure", context_summary=""))
            base_time = now()
            for index in range(8):
                db.add(
                    WriterMessage(
                        id=f"failure-{index}",
                        session_id="model-failure",
                        role="user" if index % 2 == 0 else "assistant",
                        content=f"failure-message-{index} " + ("x" * 1000),
                        created_at=base_time + timedelta(seconds=index),
                    )
                )
            await db.commit()

            result = await compact_session_context_response(
                db,
                session_id="model-failure",
                llm_client=llm,
                model="mock-compact-model",
            )
            assert result["status"] == "failed"

            session = await db.get(WriterSession, "model-failure")
            assert session is not None
            assert session.context_summary == ""
            runtime_state = session.runtime_state if isinstance(session.runtime_state, dict) else {}
            assert "manual_compaction" not in runtime_state
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_writer_service_compact_session_context_uses_resolved_model_without_type_error(tmp_path, monkeypatch):
    db_path = tmp_path / "writer-service-compact.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    llm = _WriterStyleCompactionClient()

    async def fake_resolve_llm_config(db, task_type, model_id=None):
        return {"provider": "test", "model": "mock-compact-model"}

    def fake_build_llm_client(resolved, **kwargs):
        return llm

    monkeypatch.setattr(writer_service_module, "resolve_llm_config", fake_resolve_llm_config)
    monkeypatch.setattr(writer_service_module, "build_llm_client", fake_build_llm_client)

    service = writer_service_module.writer_orchestrate(
        Settings(
            data_dir=str(tmp_path / "data"),
            database_url=f"sqlite+aiosqlite:///{db_path}",
        )
    )
    try:
        async with session_factory() as db:
            db.add(WriterSession(id="writer-service-compact", title="Writer Service Compact"))
            base_time = now()
            for index in range(8):
                db.add(
                    WriterMessage(
                        id=f"writer-service-{index}",
                        session_id="writer-service-compact",
                        role="user" if index % 2 == 0 else "assistant",
                        content=f"writer-service-message-{index}",
                        created_at=base_time + timedelta(seconds=index),
                    )
                )
            await db.commit()

            result = await service["compact_session_context"](db, session_id="writer-service-compact")

            assert result["status"] == "compacted"
            assert llm.last_messages is not None
            assert llm.last_messages[0]["role"] == "system"
            assert llm.last_max_tokens is not None
            assert result["summary"].startswith("[Compacted Context]")
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_manual_compaction_fails_when_summary_has_no_room_for_new_entries(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'compact-summary-cap.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with session_factory() as db:
            db.add(
                WriterSession(
                    id="summary-cap",
                    title="Summary Cap",
                    context_summary="x" * 20000,
                )
            )
            base_time = now()
            for index in range(8):
                db.add(
                    WriterMessage(
                        id=f"cap-{index}",
                        session_id="summary-cap",
                        role="user" if index % 2 == 0 else "assistant",
                        content=f"cap-message-{index}",
                        created_at=base_time + timedelta(seconds=index),
                    )
                )
            await db.commit()

            with pytest.raises(ValueError, match="Not enough summary space to compact history"):
                await compact_session_context_response(db, session_id="summary-cap")

            session = await db.get(WriterSession, "summary-cap")
            assert session is not None
            assert session.context_summary == "x" * 20000
            runtime_state = session.runtime_state if isinstance(session.runtime_state, dict) else {}
            assert "manual_compaction" not in runtime_state
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_manual_compaction_rejects_missing_session_and_compacts_short_history(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'compact-errors.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with session_factory() as db:
            with pytest.raises(LookupError, match="Session not found"):
                await compact_session_context_response(db, session_id="missing")

            db.add(WriterSession(id="empty", title="Empty"))
            db.add(WriterSession(id="short", title="Short"))
            base_time = now()
            for index in range(6):
                db.add(
                    WriterMessage(
                        id=f"s-{index}",
                        session_id="short",
                        role="user" if index % 2 == 0 else "assistant",
                        content=f"short-{index}",
                        created_at=base_time + timedelta(seconds=index),
                    )
                )
            await db.commit()

            empty_result = await compact_session_context_response(db, session_id="empty")
            empty_session = await db.get(WriterSession, "empty")
            assert empty_result["status"] == "not_needed"
            assert empty_result["compacted_messages"] == 0
            assert empty_result["retained_messages"] == 0
            assert empty_session is not None
            assert not empty_session.context_summary
            assert not empty_session.runtime_state or "manual_compaction" not in empty_session.runtime_state

            result = await compact_session_context_response(db, session_id="short")
            session = await db.get(WriterSession, "short")
            assert result["status"] == "not_needed"
            assert result["compacted_messages"] == 0
            assert result["retained_messages"] == 6
            assert session is not None
            assert not session.context_summary
            assert not session.runtime_state or "manual_compaction" not in session.runtime_state
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_core_runtime_preserves_system_summary_history():
    llm = _FakeLLMClient()

    await run_core_kernel(
        goal="continue",
        session_id="system-summary-history",
        llm_client=llm,
        history=[
            {"role": "system", "content": "Compacted session history:\n1. User: earlier"},
            {"role": "user", "content": "latest question"},
        ],
    )

    assert llm.last_request is not None
    system_messages = [message.content for message in llm.last_request.messages if message.role == "system"]
    assert "Compacted session history:\n1. User: earlier" in system_messages
