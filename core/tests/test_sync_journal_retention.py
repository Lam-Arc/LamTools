"""The sync journal must stay a bounded replay window.

`core_sync_changes` copies a full payload per event and had grown to 3.3GB /
211k rows on the 2026-11-09 database, five times the size of an ordinary
journal and one of the reasons every write took seconds. The existing
`compact_sync_journal` maintenance command only folds `runtime` rows, so event
rows had no bound at all. `CoreSyncJournal.prune` keeps the newest window and
lets older cursors fall back to the snapshot contract that already exists.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select

from lamtools_core.app.core_db import CoreSyncChange, open_core_app_db


async def _append_changes(db, count: int, *, start: int = 0) -> None:
    async def action(session):
        for index in range(start, start + count):
            db.sync_journal.append(
                session,
                entity_type="thread.event",
                operation="upsert",
                entity_id=f"event-{index}",
                thread_id="thread-1",
                entity={"index": index, "payload": "x" * 64},
            )

    await db.persistence.write(action)


async def _count(db) -> int:
    async with db.session_factory() as session:
        return int((await session.scalar(select(func.count()).select_from(CoreSyncChange))) or 0)


@pytest.mark.asyncio
async def test_prune_keeps_the_newest_window_and_advances_the_oldest_cursor(tmp_path: Path) -> None:
    db = await open_core_app_db(tmp_path / "journal.db", workspace_id="journal-test")
    try:
        await _append_changes(db, 40)
        assert await _count(db) == 40
        newest_before = await db.sync_journal.current_cursor()
        oldest_before = await db.sync_journal.oldest_cursor()

        removed = await db.sync_journal.prune(keep=10)

        assert removed == 30
        assert await _count(db) == 10
        assert await db.sync_journal.current_cursor() == newest_before
        oldest_after = await db.sync_journal.oldest_cursor()
        assert oldest_after is not None and oldest_before is not None
        assert oldest_after > oldest_before
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_prune_is_a_noop_below_the_window(tmp_path: Path) -> None:
    db = await open_core_app_db(tmp_path / "journal-small.db", workspace_id="journal-test")
    try:
        await _append_changes(db, 5)
        assert await db.sync_journal.prune(keep=10) == 0
        assert await _count(db) == 5
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_prune_keeps_recent_rows_for_a_lagging_client(tmp_path: Path) -> None:
    """游标还在窗口内的客户端应当还能补差，只有掉出窗口的才会被要求全量快照。"""
    db = await open_core_app_db(tmp_path / "journal-cursor.db", workspace_id="journal-test")
    try:
        await _append_changes(db, 30)
        cursor = await db.sync_journal.current_cursor()
        await _append_changes(db, 5, start=30)
        await db.sync_journal.prune(keep=10)

        async with db.session_factory() as session:
            replay = await db.sync_journal.list_after(session, cursor)
        assert len(replay) == 5
        oldest = await db.sync_journal.oldest_cursor()
        assert oldest is not None and oldest < cursor
    finally:
        await db.close()
