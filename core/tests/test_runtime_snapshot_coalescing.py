"""Runtime snapshots are state, not history: the journal keeps one row per session.

user:“也不是完全发不出去 反正卡住了好久”+(每次运行时保存都追加一份整快照，长会话
一天能写几千份；写入侧改成覆盖后，同步日志不再随步数线性增长，客户端游标仍然只增。)
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from lamtools_core.app.core_db import open_core_app_db
from lamtools_core.runtime import RuntimeState


@pytest.mark.asyncio
async def test_runtime_saves_coalesce_to_one_journal_row(tmp_path):
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        await db.runtime_state_store.save_checkpoint(
            RuntimeState(session_id="thread-coalesce"), []
        )
        for step in range(4):
            state = await db.runtime_state_store.get("thread-coalesce")
            assert state is not None
            state.status = "running"
            state.metadata = {**(state.metadata or {}), "step": step}
            await db.runtime_state_store.save(state)

        async with db.session_factory() as session:
            count = await session.scalar(
                text(
                    "SELECT COUNT(*) FROM core_sync_changes "
                    "WHERE entity_type='runtime' AND entity_id='thread-coalesce'"
                )
            )
            latest_step = await session.scalar(
                text(
                    "SELECT json_extract(entity_json, '$.metadata.step') "
                    "FROM core_sync_changes WHERE entity_type='runtime' "
                    "AND entity_id='thread-coalesce'"
                )
            )
            max_seq = await session.scalar(text("SELECT MAX(seq) FROM core_sync_changes"))

        assert count == 1
        assert int(latest_step) == 3
        # The cursor high-water mark only moves forward, so clients that were
        # behind still receive the newest state.
        assert int(max_seq) > 0
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_runtime_coalescing_is_independent_per_session(tmp_path):
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        for thread_id in ("thread-a", "thread-b"):
            for step in range(3):
                state = await db.runtime_state_store.get(thread_id) or RuntimeState(
                    session_id=thread_id
                )
                state.status = "running"
                state.metadata = {**(state.metadata or {}), "step": step}
                await db.runtime_state_store.save(state)

        async with db.session_factory() as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT entity_id, COUNT(*) FROM core_sync_changes "
                        "WHERE entity_type='runtime' GROUP BY entity_id ORDER BY entity_id"
                    )
                )
            ).all()
        assert [(str(row[0]), int(row[1])) for row in rows] == [
            ("thread-a", 1),
            ("thread-b", 1),
        ]
    finally:
        await db.close()
