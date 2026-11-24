from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from lamtools_core.app import open_core_app_db
from lamtools_core.app.core_session_store import CoreDbSessionStore
from lamtools_core.app.event_store import AppEventInput
from lamtools_core.checkpoint import CoreCheckpointConversationBackend, CoreCheckpointCoordinator
from lamtools_core.runtime import RuntimeState
from lamtools_core.session import SessionRecord

from .test_core_checkpoint_graph import _append_production_turn


async def seed_turns(db):
    await _append_production_turn(db, "source", "old", "source: keep this text")
    await _append_production_turn(db, "source", "new", "message outside boundary")
    await db.runtime_state_store.save(RuntimeState(session_id="source", status="completed", metadata={
        "context_compaction": {"summary": "summary from the later turn", "summary_seq": 1, "compacted_history_seqs": [1]},
    }))
    await db.runtime_state_store.append_history("source", [
        {"role": "user", "content": "source: keep this text", "metadata": {"turn_id": "old"}},
        {"role": "assistant", "content": "old reply", "metadata": {"turn_id": "old"}},
        {"role": "user", "content": "message outside boundary", "metadata": {"turn_id": "new"}},
    ])


# user:“分叉/编辑 稳定性/速度 找优化点进行优化”+(目标回合之后的事件不展开，也不能混入所选历史)。
@pytest.mark.parametrize("route", ["fork", "edit"])
async def test_historical_operation_reads_only_prefix_and_ignores_late_old_turn_events(tmp_path, monkeypatch, route):
    db = await open_core_app_db(tmp_path / "history.db")
    backend = CoreCheckpointConversationBackend(db.session_factory, event_store=db.event_store,
                                                snapshot_store=db.snapshot_store)
    try:
        await seed_turns(db)
        await db.persistence.write(lambda session: db.persistence.append(session, AppEventInput(
            thread_id="source", turn_id="old", method="item/started", item_id="late-old-event",
            payload={"type": "agentMessage", "content": "late old event"},
        )))
        monkeypatch.setattr(db.snapshot_store, "load", AsyncMock(side_effect=AssertionError("full snapshot loaded")))
        read_events = db.event_store.list_thread

        async def assert_bounded(session, **kwargs):
            assert kwargs.get("through_seq") is not None, "unbounded event lookup"
            return await read_events(session, **kwargs)

        monkeypatch.setattr(db.event_store, "list_thread", assert_bounded)

        async def capture(session):
            if route == "fork":
                return await backend.conversation_payload_through_turn(session, session_id="source", turn_id="old")
            payload, seq = await backend.conversation_payload_before_turn(session, session_id="source", turn_id="new")
            assert await backend.rollback_conversation_before_turn(session, session_id="source", turn_id="new") == seq
            return payload, seq

        payload, boundary = await db.persistence.write(capture)
        assert boundary > 0
        assert {record["turn_id"] for record in payload["events"] if record.get("turn_id")} == {"old"}
        assert all(record.get("item_id") != "late-old-event" for record in payload["events"])
        assert [entry["content"] for entry in payload["runtime"]["history_json"]] == [
            "source: keep this text", "old reply",
        ]
        assert "context_compaction" not in payload["runtime"]["runtime_state_json"]["metadata"]
    finally:
        await db.close()


async def test_fork_keeps_literal_message_text_and_tool_arguments_that_resemble_session_ids(tmp_path):
    db = await open_core_app_db(tmp_path / "history.db")
    backend = CoreCheckpointConversationBackend(db.session_factory, event_store=db.event_store,
                                                snapshot_store=db.snapshot_store)
    try:
        await seed_turns(db)

        async def fork(session):
            payload, _ = await backend.conversation_payload_through_turn(session, session_id="source", turn_id="old")
            payload["runtime"]["history_json"][1]["tool_calls"] = [{"id": "source:call:1", "name": "tool",
                "arguments": {"name": "source: do not rename this argument"}}]
            await backend.fork(session, source_session_id="source", new_session_id="fork", payload=payload,
                               title="Fork", options={})

        await db.persistence.write(fork)
        history = await db.runtime_state_store.get_history("fork")
        assert history[0]["content"] == "source: keep this text"
        assert history[1]["tool_calls"][0]["arguments"] == {"name": "source: do not rename this argument"}
        async with db.session_factory() as session:
            events = await db.event_store.list_thread(session, thread_id="fork")
        user_message = next(event for event in events if event.item_id == "fork:turn:old:user")
        assert user_message.payload["content"][0]["text"] == "source: keep this text"
    finally:
        await db.close()


async def test_older_history_can_still_fork_from_its_saved_boundary(tmp_path):
    db = await open_core_app_db(tmp_path / "legacy.db")
    backend = CoreCheckpointConversationBackend(db.session_factory, event_store=db.event_store, snapshot_store=db.snapshot_store)
    coordinator = CoreCheckpointCoordinator(work_root=tmp_path, session_factory=db.session_factory,
                                            write_coordinator=db.persistence.write_coordinator)
    try:
        await _append_production_turn(db, "source", "old", "kept")
        state = RuntimeState(session_id="source", status="completed", metadata={"context_compaction": {
            "summary": "previous summary", "summary_seq": 0,
        }})
        await db.runtime_state_store.save_checkpoint(state, [{"role": "user", "content": "kept"}])
        await coordinator.begin_turn(session_id="source", turn_id="new", actor_kind="main")
        await _append_production_turn(db, "source", "new", "removed")
        async with db.session_factory() as session:
            payload, _ = await backend.conversation_payload_through_turn(session, session_id="source", turn_id="old")
        assert [entry["content"] for entry in payload["runtime"]["history_json"]] == ["kept"]
        assert payload["runtime"]["runtime_state_json"]["metadata"]["context_compaction"]["summary"] == "previous summary"
    finally:
        await db.close()


async def test_fork_title_uses_source_project_and_only_its_numbering(tmp_path):
    db = await open_core_app_db(tmp_path / "title.db")
    sessions = CoreDbSessionStore(lambda: db)
    backend = CoreCheckpointConversationBackend(db.session_factory, event_store=db.event_store, snapshot_store=db.snapshot_store)
    work_root = str(tmp_path / "project")
    try:
        for session_id, title, root in [
            ("source", "Plan", work_root), ("same-project", "Plan（3）", work_root),
            ("other-project", "Plan（10）", str(tmp_path / "other")),
        ]:
            await sessions.create(SessionRecord(id=session_id, title=title, status="idle", member_id="core",
                                                metadata={"work_root": root}))
        await seed_turns(db)

        async def fork(session):
            payload, _ = await backend.conversation_payload_through_turn(session, session_id="source", turn_id="old")
            await backend.fork(session, source_session_id="source", new_session_id="fork", payload=payload,
                               title="", options={})

        await db.persistence.write(fork)
        record = await sessions.get("fork")
        assert record is not None and record.title == "Plan（4）"
        assert record.metadata["work_root"] == work_root
    finally:
        await db.close()
