"""user:“上下文应当能够被精确召回”+(真实数据库分页读取和旧档案兼容)。"""

import pytest

from lamtools_core.app import open_core_app_db
from lamtools_core.app.core_db import CoreHistoryEntry, CoreRuntimeSession
from lamtools_core.runtime import RuntimeState


@pytest.mark.asyncio
async def test_sqlite_page_is_bounded_and_uses_original_sequence(tmp_path):
    db = await open_core_app_db(tmp_path / "history.db")
    try:
        store = db.runtime_state_store
        await store.save(RuntimeState(session_id="a", metadata={"context_compaction": {"summary": "summary", "summary_seq": 900}}))
        await store.append_history("a", [{"role": "user", "content": f"original-{i}"} for i in range(8)])
        await store.append_history("b", [{"role": "user", "content": "PRIVATE"}])
        rows = await store.read_history_page("a", after_seq=2, limit=2)
        assert [r["metadata"]["history_seq"] for r in rows] == [3, 4]
        assert [r["content"] for r in rows] == ["original-2", "original-3"]
        assert await store.read_history_page("a", after_seq=999, limit=2) == []
        assert await store.read_history_page("missing", limit=2) == []
        assert (await store.get("a")).metadata["context_compaction"]["summary_seq"] == 900
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_legacy_blob_page_keeps_exact_positions_without_migration(tmp_path):
    db = await open_core_app_db(tmp_path / "legacy.db")
    try:
        await db.runtime_state_store.save(RuntimeState(session_id="legacy"))
        async def seed(session):
            row = await session.get(CoreRuntimeSession, "legacy")
            row.history_json = [{"role": "user", "content": "first"}, {"role": "user", "content": "second"}, {"role": "user", "content": "third"}]
        await db.runtime_state_store.write_coordinator.run(seed)
        rows = await db.runtime_state_store.read_history_page("legacy", after_seq=1, limit=1)
        assert rows[0]["content"] == "second"
        assert rows[0]["metadata"]["history_seq"] == 2
        async with db.session_factory() as session:
            from sqlalchemy import select
            assert (await session.execute(select(CoreHistoryEntry).where(CoreHistoryEntry.thread_id == "legacy"))).scalars().all() == []
    finally:
        await db.close()
