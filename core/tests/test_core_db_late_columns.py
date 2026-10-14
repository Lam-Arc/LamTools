"""Boot-time late-column checks must not scale with row count.

A per-boot pass that scans ``core_app_events`` (minutes on a large database) is
the defect this guards: the one-time thread-revision repair is decided from
schema/metadata and the small ``core_thread_snapshots`` table, never from the
event log, and it is recorded once applied.
"""

from __future__ import annotations

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from lamtools_core.app.core_db import (
    THREAD_REVISION_REPAIR_MARKER,
    CoreAppEvent,
    CoreDbBase,
    CoreDbMetadata,
    CoreThreadSnapshot,
    _ensure_late_columns,
)


def _record_statements(engine) -> list[str]:
    statements: list[str] = []

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def _recorder(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        statements.append(statement)

    return statements


async def _build_db(path: str, *, event_count: int, snapshot_revision: int | None = None):
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(CoreDbBase.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        session.add(
            CoreThreadSnapshot(
                thread_id="t1",
                snapshot_seq=event_count,
                revision=event_count if snapshot_revision is None else snapshot_revision,
                snapshot_json={},
            )
        )
        for index in range(event_count):
            session.add(
                CoreAppEvent(
                    event_id=f"e{index}",
                    thread_id="t1",
                    seq=index + 1,
                    method="core/runItem",
                    payload_json={"index": index},
                    revision=index + 1,
                )
            )
        await session.commit()
    return engine


async def _run_late_columns(path: str, event_count: int) -> list[str]:
    engine = await _build_db(path, event_count=event_count)
    statements = _record_statements(engine)
    async with engine.connect() as conn:
        await _ensure_late_columns(conn)
        await conn.commit()
    await engine.dispose()
    return statements


@pytest.mark.asyncio
async def test_late_columns_boot_path_is_independent_of_row_count(tmp_path):
    small = await _run_late_columns(str(tmp_path / "small.db"), 200)
    large = await _run_late_columns(str(tmp_path / "large.db"), 4000)

    # The exact statement stream is identical for a 20x row increase.
    assert small == large
    # And nothing in it reads the event log at all.
    assert not any("core_app_events" in statement and not statement.startswith("PRAGMA") for statement in large)


@pytest.mark.asyncio
async def test_late_columns_records_marker_and_skips_the_event_scan(tmp_path):
    engine = await _build_db(str(tmp_path / "ok.db"), event_count=500)
    statements = _record_statements(engine)
    async with engine.connect() as conn:
        await _ensure_late_columns(conn)
        await conn.commit()
    assert not any("core_app_events" in statement and not statement.startswith("PRAGMA") for statement in statements)
    assert not any("MAX(revision)" in statement for statement in statements)

    async with engine.connect() as conn:
        marker = await conn.scalar(
            select(CoreDbMetadata.value).where(CoreDbMetadata.key == THREAD_REVISION_REPAIR_MARKER)
        )
    assert marker == "1"

    # A second boot is a no-op: still no event scan.
    statements.clear()
    async with engine.connect() as conn:
        await _ensure_late_columns(conn)
        await conn.commit()
    assert not any("core_app_events" in statement and not statement.startswith("PRAGMA") for statement in statements)
    await engine.dispose()


@pytest.mark.asyncio
async def test_late_columns_still_repairs_a_legacy_default_revision_row(tmp_path):
    """Behaviour is preserved when the repair is actually needed: a default-0 row
    that already has projected content is raised to the event max, exactly once."""
    engine = await _build_db(str(tmp_path / "legacy.db"), event_count=7, snapshot_revision=0)
    # Restore the legacy signature: revision 0 while snapshot_seq is real.
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE core_thread_snapshots SET snapshot_seq = 5, revision = 0"))

    statements = _record_statements(engine)
    async with engine.connect() as conn:
        await _ensure_late_columns(conn)
        await conn.commit()
    assert any("MAX(revision)" in statement and "core_app_events" in statement for statement in statements)

    async with engine.connect() as conn:
        revision = await conn.scalar(select(CoreThreadSnapshot.revision).where(CoreThreadSnapshot.thread_id == "t1"))
    assert revision == 7

    # Idempotent: the second boot records nothing and does not scan.
    statements.clear()
    async with engine.connect() as conn:
        await _ensure_late_columns(conn)
        await conn.commit()
    assert not any("core_app_events" in statement and not statement.startswith("PRAGMA") for statement in statements)
    await engine.dispose()


@pytest.mark.asyncio
async def test_late_columns_runs_the_repair_when_the_column_is_just_added(tmp_path):
    """Upgrade path: adding the revision column this boot still triggers the
    repair, so an old database is fixed as before."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'upgrade.db'}", future=True)
    async with engine.begin() as conn:
        await conn.execute(text(
            "CREATE TABLE core_thread_snapshots ("
            "thread_id VARCHAR(64) PRIMARY KEY, snapshot_seq INTEGER NOT NULL DEFAULT 0, "
            "active_turn_id VARCHAR(64), snapshot_json JSON NOT NULL, "
            "updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        ))
        await conn.execute(text(
            "CREATE TABLE core_app_events ("
            "event_id VARCHAR(64) PRIMARY KEY, thread_id VARCHAR(64) NOT NULL, seq INTEGER NOT NULL, "
            "method VARCHAR(100) NOT NULL, payload_json JSON NOT NULL, "
            "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        ))
        await conn.execute(text(
            "CREATE TABLE core_db_metadata ("
            "key VARCHAR(128) PRIMARY KEY, value TEXT NOT NULL, "
            "updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        ))
        await conn.execute(text(
            "INSERT INTO core_thread_snapshots (thread_id, snapshot_seq, snapshot_json) "
            "VALUES ('t1', 4, '{\"revision\": 9}')"
        ))
        await conn.execute(text(
            "INSERT INTO core_app_events (event_id, thread_id, seq, method, payload_json) "
            "VALUES ('e1', 't1', 1, 'core/runItem', '{}')"
        ))

    statements = _record_statements(engine)
    async with engine.connect() as conn:
        await _ensure_late_columns(conn)
        await conn.commit()

    assert any(statement.startswith("ALTER TABLE core_thread_snapshots ADD COLUMN revision") for statement in statements)
    assert any("MAX(revision)" in statement and "core_app_events" in statement for statement in statements)
    async with engine.connect() as conn:
        revision = await conn.scalar(text("SELECT revision FROM core_thread_snapshots WHERE thread_id = 't1'"))
    assert revision == 9
    await engine.dispose()
