"""Sync-journal compaction must shrink the journal without losing state.

user:“在这一次的更新中，自动把之前的数据库进行一遍去重和缩小”+(同一会话的历史运行时
快照没有读者，只保留最新一条；事件、项目等其它变更必须原样保留，压缩后的库仍能被
应用正常打开。)
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from lamtools_core.app.core_db import CoreDbBase, CoreSyncChange
from lamtools_core.sync_journal_maintenance import (
    THREAD_REVISION_INDEX,
    compact_sync_journal,
)


async def _create_schema(path: Path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(CoreDbBase.metadata.create_all)
    await engine.dispose()


def _seed(path: Path) -> None:
    rows = [
        (1, "runtime", "t1"),
        (2, "runtime", "t1"),
        (3, "runtime", "t1"),
        (4, "thread.event", "t1"),
        (5, "runtime", "t2"),
        (6, "runtime", "t2"),
        (7, "project", "p1"),
    ]
    payload = '{"payload": "%s"}' % ("x" * 4096)
    connection = sqlite3.connect(path)
    try:
        connection.executemany(
            "INSERT INTO core_sync_changes (seq, change_id, workspace_id, entity_type, "
            "event_type, operation, entity_id, thread_id, revision, entity_json, created_at) "
            "VALUES (?, ?, '', ?, ?, 'upsert', ?, ?, ?, ?, '2026-11-07T00:00:00')",
            [
                (
                    seq,
                    f"c{seq}",
                    entity_type,
                    f"{entity_type}.upsert",
                    entity_id,
                    entity_id,
                    seq,
                    payload,
                )
                for seq, entity_type, entity_id in rows
            ],
        )
        connection.commit()
    finally:
        connection.close()


def _seqs(path: Path) -> list[int]:
    connection = sqlite3.connect(path)
    try:
        return [
            int(row[0])
            for row in connection.execute("SELECT seq FROM core_sync_changes ORDER BY seq")
        ]
    finally:
        connection.close()


@pytest.mark.asyncio
async def test_compaction_keeps_newest_runtime_snapshot_and_preserves_events(tmp_path):
    db = tmp_path / "core.db"
    await _create_schema(db)
    _seed(db)

    report = compact_sync_journal(db, apply=True, vacuum=True, backup=True)

    assert report.ok is True
    assert report.applied is True
    assert report.vacuumed is True
    assert report.total_changes_before == 7
    assert report.runtime_changes_before == 5
    assert report.runtime_entities == 2
    assert report.other_changes == 2
    assert report.deleted_changes == 3
    assert report.total_changes_after == 4
    assert report.runtime_changes_after == 2
    # Keep the newest runtime row for each session, plus every non-runtime row.
    assert _seqs(db) == [3, 4, 6, 7]
    # The cursor high-water mark never moves backwards.
    assert report.max_seq_after == report.max_seq_before == 7
    # A pre-compaction copy exists and the covering index was created.
    assert report.backup_path and Path(report.backup_path).is_file()
    assert report.index_created is True
    connection = sqlite3.connect(db)
    try:
        index = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?",
            (THREAD_REVISION_INDEX,),
        ).fetchone()
    finally:
        connection.close()
    assert index is not None
    assert report.after_bytes <= report.before_bytes


@pytest.mark.asyncio
async def test_dry_run_does_not_modify_the_journal(tmp_path):
    db = tmp_path / "core.db"
    await _create_schema(db)
    _seed(db)

    report = compact_sync_journal(db, apply=False)

    assert report.applied is False
    assert report.total_changes_before == 7
    assert report.runtime_entities == 2
    assert _seqs(db) == [1, 2, 3, 4, 5, 6, 7]


@pytest.mark.asyncio
async def test_compaction_is_idempotent(tmp_path):
    db = tmp_path / "core.db"
    await _create_schema(db)
    _seed(db)

    compact_sync_journal(db, apply=True, vacuum=False, backup=False)
    report = compact_sync_journal(db, apply=True, vacuum=False, backup=False)

    assert report.deleted_changes == 0
    assert report.total_changes_after == report.total_changes_before
    assert _seqs(db) == [3, 4, 6, 7]


@pytest.mark.asyncio
async def test_compacted_database_still_opens_with_the_app_schema(tmp_path):
    db = tmp_path / "core.db"
    await _create_schema(db)
    _seed(db)
    compact_sync_journal(db, apply=True, vacuum=True, backup=False)

    engine = create_async_engine(f"sqlite+aiosqlite:///{db}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            total = int(await session.scalar(select(func.count()).select_from(CoreSyncChange)) or 0)
            newest = await session.scalar(
                select(CoreSyncChange.entity_json).where(CoreSyncChange.seq == 6)
            )
        assert total == 4
        assert newest is not None
    finally:
        await engine.dispose()
