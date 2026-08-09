from __future__ import annotations

from datetime import datetime

import pytest
import asyncio
from sqlalchemy import DateTime, Integer, JSON, String, UniqueConstraint
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from lamtools_core.app import (
    CORE_RUN_ITEM_METHOD,
    CoreAppSnapshotProjector,
    CoreAgentPaths,
    CoreAgentSpec,
    SqlAlchemyAppEventStore,
    SqlAlchemyThreadSnapshotStore,
    create_core_agent_operations,
)
from lamtools_core.app.live_hub import CoreAppEventHub
from lamtools_core.app.default_agent import _persist_core_event_live, _persist_run_items
from lamtools_core.app.base_agent import core_events_to_run_items
from lamtools_core.llm import LLMRequest, LLMResponse, LLMStreamEvent, LLMToolCall
from lamtools_core.event import CoreEvent


class Base(DeclarativeBase):
    pass


class AppEventRow(Base):
    __tablename__ = "test_operation_app_events"
    __table_args__ = (
        UniqueConstraint("thread_id", "seq", name="uq_test_operation_app_events_thread_seq"),
    )

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    turn_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    item_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    parent_item_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    client_message_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    method: Mapped[str] = mapped_column(String(100), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)


class ThreadSnapshotRow(Base):
    __tablename__ = "test_operation_thread_snapshots"

    thread_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    snapshot_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)


class SnapshotItemRow(Base):
    __tablename__ = "test_operation_thread_snapshot_items"

    thread_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    item_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    item_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)


class ScriptedReadLLM:
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("Core operation should use streaming")

    async def stream(self, request: LLMRequest):
        self.requests.append(request)
        if len(self.requests) == 1:
            yield LLMStreamEvent(kind="thinking_delta", content="Need to read.")
            yield LLMStreamEvent(
                kind="done",
                tool_calls=[LLMToolCall(id="call-read", name="read_file", arguments={"path": "input.txt"})],
            )
            return
        yield LLMStreamEvent(kind="content_delta", content="Read input.txt.")
        yield LLMStreamEvent(kind="done")


class ScriptedApprovalLLM:
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("Core operation should use streaming")

    async def stream(self, request: LLMRequest):
        self.requests.append(request)
        if len(self.requests) == 1:
            yield LLMStreamEvent(kind="thinking_delta", content="Need a write.")
            yield LLMStreamEvent(
                kind="done",
                tool_calls=[
                    LLMToolCall(
                        id="call-write",
                        name="write_file",
                        arguments={"path": "approved.md", "content": "approved\n"},
                    )
                ],
            )
            return
        yield LLMStreamEvent(kind="content_delta", content="Saved approved.md.")
        yield LLMStreamEvent(kind="done")


class BlockingApprovalContinuationLLM:
    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("Core operation should use streaming")

    async def stream(self, request: LLMRequest):
        self.requests.append(request)
        if len(self.requests) == 1:
            yield LLMStreamEvent(
                kind="done",
                tool_calls=[
                    LLMToolCall(
                        id="call-write",
                        name="write_file",
                        arguments={"path": "approved.md", "content": "approved\n"},
                    )
                ],
            )
            return
        yield LLMStreamEvent(kind="thinking_delta", content="continuing after approval")
        await self.release.wait()
        yield LLMStreamEvent(kind="content_delta", content="Saved approved.md.")
        yield LLMStreamEvent(kind="done")


class BlockingLiveLLM:
    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("Core operation should use streaming")

    async def stream(self, request: LLMRequest):
        self.requests.append(request)
        yield LLMStreamEvent(kind="thinking_delta", content="live thinking")
        await self.release.wait()
        yield LLMStreamEvent(kind="content_delta", content="done")
        yield LLMStreamEvent(kind="done")


async def _persistence(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'core-operation.db'}", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    event_store = SqlAlchemyAppEventStore(AppEventRow, protocol_version="test.v1")
    snapshot_store = SqlAlchemyThreadSnapshotStore(ThreadSnapshotRow, item_model=SnapshotItemRow, projector=CoreAppSnapshotProjector())
    return engine, session_factory, event_store, snapshot_store


def test_core_event_projection_keeps_protocol_json_out_of_visible_messages():
    events = [
        CoreEvent(
            event_id="finish-metadata",
            name="runtime.reply_delta",
            category="message",
            session_id="thread-visible",
            run_id="run-visible",
            turn_id="turn-visible",
            sequence=1,
            payload={
                "content": "",
                "finish_reason": "tool_calls",
                "usage": {"prompt_tokens": 12, "completion_tokens": 3},
                "response_index": 0,
            },
        ),
        CoreEvent(
            event_id="final-text",
            name="runtime.part",
            category="message",
            session_id="thread-visible",
            run_id="run-visible",
            turn_id="turn-visible",
            sequence=2,
            payload={
                "part_id": "run-visible:response-1:text",
                "part_type": "text",
                "status": "completed",
                "content": "最终 **正文**",
                "label": "Reply",
                "final_response": True,
                "has_tool_calls": False,
                "response_index": 1,
            },
        ),
    ]

    run_items = core_events_to_run_items(events, thread_id="thread-visible")

    visible_items = [item for item in run_items if item.kind != "usage"]
    usage_items = [item for item in run_items if item.kind == "usage"]

    assert len(visible_items) == 1
    assert visible_items[0].payload["content"] == "最终 **正文**"
    assert "finish_reason" not in visible_items[0].payload["content"]
    assert len(usage_items) == 1
    assert usage_items[0].usage["total_tokens"] == 15


@pytest.mark.asyncio
async def test_core_operation_persists_run_items_and_snapshot(tmp_path):
    engine, session_factory, event_store, snapshot_store = await _persistence(tmp_path)
    try:
        work_root = tmp_path / "work"
        work_root.mkdir()
        (work_root / "input.txt").write_text("hello\n", encoding="utf-8")
        llm = ScriptedReadLLM()
        catalog = create_core_agent_operations(
            spec=CoreAgentSpec(),
            paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=work_root),
            model_provider=llm,
            db_session_factory=session_factory,
            app_event_store=event_store,
            thread_snapshot_store=snapshot_store,
        )

        result = await catalog.execute("turn.start", {"thread_id": "thread-persist", "message": "read"})

        async with session_factory() as db:
            events = await event_store.list_thread(db, thread_id="thread-persist")
            snapshot = await snapshot_store.load(db, "thread-persist")

        assert result.status == "ok"
        assert len(events) == len(result.payload["run_items"])
        assert {event.method for event in events} == {CORE_RUN_ITEM_METHOD}
        assert snapshot["snapshot_seq"] == len(events)
        assert snapshot["status"] == "completed"
        assert snapshot["core"]["status"] == "completed"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_core_operation_publishes_run_items_while_turn_is_running(tmp_path):
    engine, session_factory, event_store, snapshot_store = await _persistence(tmp_path)
    try:
        work_root = tmp_path / "work"
        work_root.mkdir()
        llm = BlockingLiveLLM()
        hub = CoreAppEventHub()
        subscription = hub.subscribe("thread-live")
        catalog = create_core_agent_operations(
            spec=CoreAgentSpec(),
            paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=work_root),
            model_provider=llm,
            db_session_factory=session_factory,
            app_event_store=event_store,
            thread_snapshot_store=snapshot_store,
            app_event_hub=hub,
        )

        task = asyncio.create_task(catalog.execute("turn.start", {"thread_id": "thread-live", "message": "stream"}))
        live_event = await asyncio.wait_for(subscription.get(), timeout=1)

        assert live_event.method == CORE_RUN_ITEM_METHOD
        assert live_event.seq == 0
        assert live_event.payload["kind"] == "thinking"
        assert not task.done()

        async with session_factory() as db:
            events = await event_store.list_thread(db, thread_id="thread-live")
            snapshot = await snapshot_store.load(db, "thread-live")

        assert all(event.event_id != live_event.event_id for event in events)
        assert snapshot["status"] == "idle"
        assert snapshot["snapshot_seq"] == 0

        llm.release.set()
        result = await task
        assert result.status == "ok"
    finally:
        hub.unsubscribe("thread-live", subscription)
        await engine.dispose()


@pytest.mark.asyncio
async def test_live_sink_then_final_replay_does_not_duplicate_trimmed_run_item(tmp_path):
    engine, session_factory, event_store, snapshot_store = await _persistence(tmp_path)
    try:
        event = CoreEvent(
            event_id="live-event-1",
            name="runtime.reply_delta",
            category="message",
            session_id="thread-live",
            run_id="run-1",
            turn_id="turn-1",
            sequence=1,
            payload={"content": "once"},
        )
        await _persist_core_event_live(
            event,
            thread_id="thread-live",
            db_session_factory=session_factory,
            app_event_store=event_store,
            thread_snapshot_store=snapshot_store,
            app_event_hub=CoreAppEventHub(),
        )
        async with session_factory() as db:
            row = await db.get(ThreadSnapshotRow, "thread-live")
            assert row is not None
            row.snapshot_seq = 2001
            state = dict(row.snapshot_json)
            core = dict(state.get("core") or {})
            row.snapshot_json = {
                **state,
                "snapshot_seq": 2001,
                "seen_event_ids": [f"event-{index}" for index in range(2, 2002)],
                "core": {
                    **core,
                    "seen_event_ids": [f"event-{index}" for index in range(2, 2002)],
                },
            }
            await db.commit()

        await _persist_run_items(
            core_events_to_run_items([event], thread_id="thread-live"),
            db_session_factory=session_factory,
            app_event_store=event_store,
            thread_snapshot_store=snapshot_store,
        )
        async with session_factory() as db:
            snapshot = await snapshot_store.load(db, "thread-live")

        contents = [item.get("content") for item in snapshot["core"]["items"].values() if isinstance(item, dict)]
        assert contents == ["once"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_core_approval_continuation_persists_approved_tool_and_final_snapshot(tmp_path):
    engine, session_factory, event_store, snapshot_store = await _persistence(tmp_path)
    try:
        work_root = tmp_path / "work"
        work_root.mkdir()
        llm = ScriptedApprovalLLM()
        catalog = create_core_agent_operations(
            spec=CoreAgentSpec(),
            paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=work_root),
            model_provider=llm,
            db_session_factory=session_factory,
            app_event_store=event_store,
            thread_snapshot_store=snapshot_store,
        )

        waiting = await catalog.execute("turn.start", {"thread_id": "thread-approval", "message": "write"})
        approved = await catalog.execute("approval.respond", {"thread_id": "thread-approval", "action": "approve"})

        async with session_factory() as db:
            events = await event_store.list_thread(db, thread_id="thread-approval")
            snapshot = await snapshot_store.load(db, "thread-approval")

        assert waiting.payload["decision"] == "wait"
        assert approved.status == "ok"
        assert approved.payload["turn_id"] == waiting.payload["turn_id"]
        assert (work_root / "approved.md").read_text(encoding="utf-8") == "approved\n"
        assert len(events) == len(waiting.payload["run_items"]) + len(approved.payload["run_items"])
        assert {event.turn_id for event in events if event.turn_id} == {waiting.payload["turn_id"]}
        assert any(event.payload.get("kind") == "tool_result" for event in events)
        assert snapshot["status"] == "completed"
        assert snapshot["core"]["status"] == "completed"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_core_approval_response_is_published_before_continuation_finishes(tmp_path):
    engine, session_factory, event_store, snapshot_store = await _persistence(tmp_path)
    hub = CoreAppEventHub()
    subscription = hub.subscribe("thread-approval-live")
    approval_task = None
    llm = BlockingApprovalContinuationLLM()
    try:
        work_root = tmp_path / "work"
        work_root.mkdir()
        catalog = create_core_agent_operations(
            spec=CoreAgentSpec(),
            paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=work_root),
            model_provider=llm,
            db_session_factory=session_factory,
            app_event_store=event_store,
            thread_snapshot_store=snapshot_store,
            app_event_hub=hub,
        )

        waiting = await catalog.execute(
            "turn.start", {"thread_id": "thread-approval-live", "message": "write"}
        )
        while not subscription.empty():
            subscription.get_nowait()

        approval_task = asyncio.create_task(
            catalog.execute(
                "approval.respond",
                {"thread_id": "thread-approval-live", "action": "approve"},
            )
        )
        live_event = await asyncio.wait_for(subscription.get(), timeout=1)

        assert waiting.payload["decision"] == "wait"
        assert live_event.method == CORE_RUN_ITEM_METHOD
        assert live_event.payload["kind"] == "approval_response"
        assert live_event.payload["status"] == "completed"
        assert not approval_task.done()
    finally:
        llm.release.set()
        if approval_task is not None:
            await approval_task
        hub.unsubscribe("thread-approval-live", subscription)
        await engine.dispose()
