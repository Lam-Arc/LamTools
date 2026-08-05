"""Tests for WriterStateStore."""

import pytest

from app.core.writer.schemas import WriterSessionState
from app.core.writer.state_store import WriterStateStore
from app.models.session import WriterSession


class TestWriterStateStore:
    @pytest.mark.asyncio
    async def test_save_then_get_returns_same_state(self, data_dir):
        store = WriterStateStore(data_dir)
        state = WriterSessionState(
            session_id="test-session-1",
            work_root="/tmp/test",
            phase="executing",
        )
        await store.save(state)

        retrieved = await store.get("test-session-1")
        assert retrieved is not None
        assert retrieved.session_id == "test-session-1"
        assert retrieved.work_root == "/tmp/test"
        assert retrieved.phase == "executing"

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self, data_dir):
        store = WriterStateStore(data_dir)
        result = await store.get("nonexistent-session")
        assert result is None

    @pytest.mark.asyncio
    async def test_create_method(self, data_dir):
        store = WriterStateStore(data_dir)
        state = await store.create(
            session_id="created-session",
            work_root="/tmp/create-test",
        )
        assert state.session_id == "created-session"
        assert state.work_root == "/tmp/create-test"
        assert state.mode == "EXECUTE"
        assert state.phase == "idle"

        # Verify it was saved
        retrieved = await store.get("created-session")
        assert retrieved is not None
        assert retrieved.mode == "EXECUTE"

    @pytest.mark.asyncio
    async def test_save_updates_existing_state(self, data_dir):
        store = WriterStateStore(data_dir)
        state = WriterSessionState(session_id="update-test", turn_count=0)
        await store.save(state)

        # Modify and save again
        state.turn_count = 5
        state.phase = "verifying"
        await store.save(state)

        retrieved = await store.get("update-test")
        assert retrieved is not None
        assert retrieved.turn_count == 5
        assert retrieved.phase == "verifying"

    @pytest.mark.asyncio
    async def test_save_preserves_existing_compaction_state_from_database(self, data_dir):
        store = WriterStateStore(data_dir)
        state = WriterSessionState(
            session_id="compact-preserve",
            context_summary="[Compacted Context]\nold summary",
            turn_count=1,
        )
        await store.save(state)

        db = await store._get_db()
        try:
            session = await db.get(WriterSession, "compact-preserve")
            assert session is not None
            session.context_summary = "[Compacted Context]\nlatest summary"
            session.runtime_state = {
                **(session.runtime_state or {}),
                "manual_compaction": {
                    "compacted_at": "2026-07-08T00:00:00+00:00",
                    "compacted_message_ids": ["m-1", "m-2"],
                    "retained_message_ids": ["m-3"],
                    "retained_message_count": 1,
                },
            }
            await db.commit()
        finally:
            await db.close()

        state.turn_count = 2
        await store.save(state)

        verify_db = await store._get_db()
        try:
            session = await verify_db.get(WriterSession, "compact-preserve")
            assert session is not None
            assert session.context_summary == "[Compacted Context]\nlatest summary"
            assert session.runtime_state["manual_compaction"]["compacted_message_ids"] == ["m-1", "m-2"]
            assert session.runtime_state["manual_compaction"]["retained_message_ids"] == ["m-3"]
            assert session.turn_count == 2
        finally:
            await verify_db.close()

    @pytest.mark.asyncio
    async def test_delete_removes_state(self, data_dir):
        store = WriterStateStore(data_dir)
        state = WriterSessionState(session_id="delete-test")
        await store.save(state)

        # Verify it exists
        retrieved = await store.get("delete-test")
        assert retrieved is not None

        await store.delete("delete-test")
        result = await store.get("delete-test")
        assert result is None

    @pytest.mark.asyncio
    async def test_state_persistence_across_instances(self, data_dir):
        store1 = WriterStateStore(data_dir)
        state = WriterSessionState(
            session_id="persist-test",
            work_root="/tmp/persist",
            turn_count=3,
        )
        await store1.save(state)

        # New store instance with same data_dir
        store2 = WriterStateStore(data_dir)
        retrieved = await store2.get("persist-test")
        assert retrieved is not None
        assert retrieved.session_id == "persist-test"
        assert retrieved.work_root == "/tmp/persist"
        assert retrieved.turn_count == 3

    @pytest.mark.asyncio
    async def test_delete_nonexistent_no_error(self, data_dir):
        store = WriterStateStore(data_dir)
        await store.delete("nonexistent-session")
        # Should not raise

    @pytest.mark.asyncio
    async def test_list_sessions(self, data_dir):
        store = WriterStateStore(data_dir)
        await store.save(WriterSessionState(session_id="list-1"))
        await store.save(WriterSessionState(session_id="list-2"))

        sessions = await store.list_sessions()
        assert len(sessions) == 2
        session_ids = {s.session_id for s in sessions}
        assert "list-1" in session_ids
        assert "list-2" in session_ids

    @pytest.mark.asyncio
    async def test_create_with_defaults(self, data_dir):
        store = WriterStateStore(data_dir)
        state = await store.create(session_id="default-test")
        assert state.session_id == "default-test"
        assert state.work_root == ""
        assert state.mode == "EXECUTE"
        assert state.todos == []
        assert state.turn_count == 0
