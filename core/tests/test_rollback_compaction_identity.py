"""user:“修”+(回退与恢复后保留未压缩消息，并恢复已有异常会话的上下文)。"""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from lamtools_core.app.core_db import (
    CoreCheckpointV2SessionHistory, CoreHistoryEntry, CoreRuntimeSession, open_core_app_db,
)
from lamtools_core.checkpoint import CoreCheckpointConversationBackend, _conversation_runtime_payload
from lamtools_core.context_compaction.state import load_compaction_history, rebase_compaction_history
from lamtools_core.runtime import RuntimeState


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["rollback", "checkpoint", "materialized"])
@pytest.mark.parametrize("include_compacted_row", [False, True])
async def test_rewritten_history_keeps_compaction_identity(tmp_path, route, include_compacted_row):
    db = await open_core_app_db(tmp_path / "isolated.db")
    store = db.runtime_state_store
    sid = "parent:sub:identity"
    metadata = {"context_compaction": {
        "summary": "Old task summary", "summary_seq": 855,
        "compacted_history_seqs": list(range(1, 856)),
    }}
    history = [{"role": "user", "content": "Draw Xi using moss", "metadata": {"history_seq": 856}}]
    if include_compacted_row:
        history.insert(0, {"role": "user", "content": "Already summarized", "metadata": {"history_seq": 854}})
    try:
        await store.save(RuntimeState(session_id=sid, metadata=deepcopy(metadata)))

        async def seed(session):
            for message in history:
                seq = message["metadata"]["history_seq"]
                session.add(CoreHistoryEntry(thread_id=sid, seq=seq, revision=seq, message_json=message))
            session.add(CoreCheckpointV2SessionHistory(checkpoint_id="boundary", history_json=deepcopy(history)))
        await store.write_coordinator.run(seed)
        before = await load_compaction_history(store, sid, metadata)
        assert [m.content for m in before] == ["Old task summary", "Draw Xi using moss"]
        backend = CoreCheckpointConversationBackend(db.session_factory)
        if route == "rollback":
            async with db.session_factory() as session:
                runtime = await session.get(CoreRuntimeSession, sid)
                payload = {"runtime": _conversation_runtime_payload(
                    runtime, session_id=sid, history=deepcopy(history), boundary_seq=1, turn_id="removed",
                    context_state=runtime.runtime_state_json,
                ), "projection": {"snapshot_seq": 1, "snapshot_json": {}}, "events": []}
            backend.conversation_payload_before_turn = AsyncMock(return_value=(payload, 1))
            await store.write_coordinator.run(lambda session: backend.rollback_conversation_before_turn(
                session, session_id=sid, turn_id="removed",
            ))
        elif route == "checkpoint":
            checkpoint = SimpleNamespace(id="boundary", session_id=sid, event_seq=1,
                                         runtime_state_json={"session_id": sid, "metadata": deepcopy(metadata)})
            await store.write_coordinator.run(lambda session: backend.restore_v2(session, sid, checkpoint))
        else:
            materialized = SimpleNamespace(history_json=deepcopy(history), runtime_present=True,
                runtime_json={"runtime_state_json": {"session_id": sid, "metadata": deepcopy(metadata)}},
                events_present=False)
            await store.write_coordinator.run(lambda session: backend._restore_materialized(
                session, sid, materialized, event_seq=1,
            ))
        state = await store.get(sid)
        restored = await load_compaction_history(store, sid, state.metadata)
        assert [m.content for m in restored] == ["Old task summary", "Draw Xi using moss"]
        await store.append_history(sid, [{"role": "user", "content": "Who is Xi?"}])
        # Reload again: a message accepted this turn must survive the next turn too.
        state = await store.get(sid)
        following = await load_compaction_history(store, sid, state.metadata)
        assert [m.content for m in following] == ["Old task summary", "Draw Xi using moss", "Who is Xi?"]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_existing_stale_compaction_recovers_without_hiding_new_messages(tmp_path):
    db = await open_core_app_db(tmp_path / "stale.db")
    store = db.runtime_state_store
    sid = "stale"
    try:
        state = RuntimeState(session_id=sid, metadata={"context_compaction": {
            "summary": "Old task summary", "summary_seq": 855,
            "compacted_history_seqs": list(range(1, 856)),
        }})
        await store.save(state)
        await store.append_history(sid, [{"role": "user", "content": "Draw Xi using moss"}])
        view = await load_compaction_history(store, sid, state.metadata)
        assert [m.content for m in view] == ["Old task summary", "Draw Xi using moss"]
        # Persist the repair so later appends cannot eventually make the stale anchor look valid.
        await store.save(state)
        reloaded = await store.get(sid)
        assert reloaded.metadata["context_compaction"]["summary_seq"] == 0
        assert not reloaded.metadata["context_compaction"].get("compacted_history_seqs")
    finally:
        await db.close()


def test_restoring_an_already_corrupt_snapshot_does_not_make_stale_filter_permanent():
    state = {"metadata": {"context_compaction": {
        "summary": "Old task summary", "summary_seq": 855,
        "compacted_history_seqs": list(range(1, 856)),
    }}}
    history = [{"role": "user", "content": "Draw Xi using moss", "metadata": {"history_seq": 188}}]
    original = deepcopy(state)
    restored = rebase_compaction_history(state, history)
    assert restored["metadata"]["context_compaction"]["compacted_history_seqs"] == []
    assert restored["metadata"]["context_compaction"]["summary_seq"] == 0
    assert history[0]["metadata"]["history_seq"] == 1
    assert state == original


def test_legacy_prefix_only_snapshot_keeps_compacted_and_retained_rows_distinct():
    state = {"metadata": {"context_compaction": {"summary": "Old task summary", "summary_seq": 855}}}
    history = [
        {"role": "user", "content": "Already summarized", "metadata": {"history_seq": 854}},
        {"role": "user", "content": "Draw Xi using moss", "metadata": {"history_seq": 856}},
    ]
    restored = rebase_compaction_history(state, history)
    assert restored["metadata"]["context_compaction"]["compacted_history_seqs"] == [1]
    assert restored["metadata"]["context_compaction"]["summary_seq"] == 1
