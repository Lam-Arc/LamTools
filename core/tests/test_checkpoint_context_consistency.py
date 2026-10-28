"""user:“修”+(边界摘要、历史与编号必须一起恢复，兼容路径和分叉不能继续漏上下文)。"""
from copy import deepcopy

import pytest

from lamtools_core.app import AppEventInput, open_core_app_db
from lamtools_core.app.core_db import CoreCheckpointV2SessionHistory
from lamtools_core.checkpoint import CoreCheckpointConversationBackend, CoreCheckpointCoordinator
from lamtools_core.context_compaction.state import load_compaction_history
from lamtools_core.runtime import RuntimeState


async def append_turn(db, sid, turn):
    async def write(session):
        await db.persistence.append_many(session, [AppEventInput(
            thread_id=sid, turn_id=turn, method="turn/accepted",
            payload={"input": [{"type": "text", "text": turn}]},
        )])
    await db.persistence.write(write)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["rollback", "turn_fork", "checkpoint_fork", "first_turn"])
async def test_boundary_does_not_inherit_future_summary(tmp_path, mode):
    db = await open_core_app_db(tmp_path / "boundary.db")
    sid = "source"
    store = db.runtime_state_store
    try:
        old_metadata = {"context_compaction": {"summary": "Historical summary", "summary_seq": 0}}
        await store.save(RuntimeState(session_id=sid, metadata=deepcopy(old_metadata)))
        await store.append_history(sid, [{"role": "user", "content": "earlier instruction"}])
        await append_turn(db, sid, "first")
        coordinator = CoreCheckpointCoordinator(work_root=tmp_path, session_factory=db.session_factory,
                                                write_coordinator=store.write_coordinator)
        checkpoint = await coordinator.begin_turn(session_id=sid, turn_id="second", actor_kind="main")
        state = await store.get(sid)
        state.metadata["context_compaction"] = {
            "summary": "FUTURE REMOVED CONTENT", "summary_seq": 1, "compacted_history_seqs": [1],
        }
        await store.save(state)
        await append_turn(db, sid, "second")
        backend = CoreCheckpointConversationBackend(db.session_factory)
        if mode == "checkpoint_fork":
            forked = await coordinator.fork(checkpoint.id, new_session_id="fork", title="Fork")
            target = forked.session_id
            async with db.session_factory() as session:
                captured = await session.get(CoreCheckpointV2SessionHistory, forked.id)
                assert [m["content"] for m in captured.history_json] == ["earlier instruction"]
        elif mode == "turn_fork":
            async def fork(session):
                payload, _ = await backend.conversation_payload_through_turn(session, session_id=sid, turn_id="first")
                await backend.fork(session, source_session_id=sid, new_session_id="fork", payload=payload,
                                   title="Fork", options={})
            await store.write_coordinator.run(fork)
            target = "fork"
        else:
            await store.write_coordinator.run(lambda session: backend.rollback_conversation_before_turn(
                session, session_id=sid, turn_id="first" if mode == "first_turn" else "second",
            ))
            target = sid
        restored = await store.get(target)
        view = await load_compaction_history(store, target, restored.metadata)
        assert all("FUTURE REMOVED CONTENT" not in str(m.content) for m in view)
        if mode == "first_turn":
            assert view == []
        else:
            assert [m.content for m in view] == ["Historical summary", "earlier instruction"]
        await store.append_history(target, [{"role": "user", "content": "Next input"}])
        following = await store.get(target)
        following_view = await load_compaction_history(store, target, following.metadata)
        assert [m.content for m in following_view] == [m.content for m in view] + ["Next input"]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_legacy_restore_without_runtime_discards_orphan_history(tmp_path):
    db = await open_core_app_db(tmp_path / "absent.db")
    store = db.runtime_state_store
    try:
        # A partially deleted/migrated session can have rows without a runtime shell.
        await store.append_history("orphan", [{"role": "user", "content": "Discarded branch"}])
        backend = CoreCheckpointConversationBackend(db.session_factory)
        await store.write_coordinator.run(lambda session: backend.restore(session, "orphan", {"runtime": None}))
        assert await store.get_history("orphan") == []
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_sparse_fork_survives_appends_and_reload(tmp_path):
    db = await open_core_app_db(tmp_path / "fork.db")
    store = db.runtime_state_store
    try:
        metadata = {"context_compaction": {"summary": "Historical summary", "summary_seq": 855,
                                           "compacted_history_seqs": list(range(1, 856))}}
        history = [{"role": "user", "content": "Already summarized", "metadata": {"history_seq": 854}}]
        history += [{"role": "user", "content": f"retained-{n}", "metadata": {"history_seq": n}}
                    for n in range(856, 1712)]
        backend = CoreCheckpointConversationBackend(db.session_factory)
        await store.write_coordinator.run(lambda session: backend.fork(
            session, source_session_id="source", new_session_id="fork", title="Fork", options={},
            payload={"runtime": {"runtime_state_json": {"metadata": metadata}, "history_json": history}},
        ))
        for index in range(2):
            await store.append_history("fork", [{"role": "user", "content": f"new-{index}"}])
            state = await store.get("fork")
            view = await load_compaction_history(store, "fork", state.metadata)
            expected = [f"retained-{n}" for n in range(856, 1712)] + [f"new-{n}" for n in range(index + 1)]
            assert [m.content for m in view if m.role == "user"] == expected
    finally:
        await db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("history", [[], [{"role": "user", "content": "Restored branch"}]])
async def test_legacy_restore_replaces_authoritative_history(tmp_path, history):
    db = await open_core_app_db(tmp_path / "legacy.db")
    store = db.runtime_state_store
    try:
        await store.save(RuntimeState(session_id="source"))
        await store.append_history("source", [{"role": "user", "content": "Discarded branch"}])
        backend = CoreCheckpointConversationBackend(db.session_factory)
        await store.write_coordinator.run(lambda session: backend.restore(session, "source", {
            "runtime": {"runtime_state_json": {"session_id": "source", "metadata": {}}, "history_json": history},
        }))
        assert [m["content"] for m in await store.get_history("source")] == [m["content"] for m in history]
        await store.append_history("source", [{"role": "user", "content": "Next input"}])
        assert [m["content"] for m in await store.get_history("source")] == [m["content"] for m in history] + ["Next input"]
    finally:
        await db.close()
