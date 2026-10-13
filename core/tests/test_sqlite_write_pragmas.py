"""Connection-setup pragmas: journal mode set once, a failure never fatal.

The journal mode is a persistent property of the database file. Re-issuing
``PRAGMA journal_mode=WAL`` on every connection made a read fail with
"database is locked" whenever another connection was writing, because that
statement does not honour the busy timeout. These tests pin the fix: the mode is
set once per engine, a failure degrades to a warning and is retried later, and
concurrent readers plus a writer keep working.
"""
from __future__ import annotations

import asyncio
import sqlite3

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from lamtools_core.app.sqlite_write import (
    _PragmaState,
    _apply_connection_pragmas,
    configure_sqlite_engine,
)


class _RecordingCursor:
    def __init__(self, *, fail_journal_mode: bool = False, fail_times: int = 0) -> None:
        self.statements: list[str] = []
        self.fail_journal_mode = fail_journal_mode
        self.fail_times = fail_times
        self.journal_failures = 0

    def execute(self, statement: str):
        self.statements.append(statement)
        if "journal_mode" in statement and (self.fail_journal_mode or self.journal_failures < self.fail_times):
            self.journal_failures += 1
            raise sqlite3.OperationalError("database is locked")
        return self


def test_journal_mode_is_issued_once_and_a_failure_is_non_fatal():
    state = _PragmaState()
    first = _RecordingCursor()
    _apply_connection_pragmas(first, state, busy_timeout_ms=5000)

    assert sum("journal_mode" in s for s in first.statements) == 1
    assert state.journal_mode_ensured is True
    assert any("busy_timeout" in s for s in first.statements)
    assert any("synchronous" in s for s in first.statements)

    # Every later connection skips the journal-mode statement entirely.
    second = _RecordingCursor()
    _apply_connection_pragmas(second, state, busy_timeout_ms=5000)
    assert not any("journal_mode" in s for s in second.statements)
    assert any("busy_timeout" in s for s in second.statements)

    # A locked journal-mode statement must not raise; it retries next connection.
    failing_state = _PragmaState()
    locked = _RecordingCursor(fail_journal_mode=True)
    _apply_connection_pragmas(locked, failing_state, busy_timeout_ms=5000)
    assert failing_state.journal_mode_ensured is False
    assert any("synchronous" in s for s in locked.statements)

    retry = _RecordingCursor()
    _apply_connection_pragmas(retry, failing_state, busy_timeout_ms=5000)
    assert any("journal_mode" in s for s in retry.statements)
    assert failing_state.journal_mode_ensured is True


@pytest.mark.asyncio
async def test_concurrent_readers_and_a_writer_setup_does_not_raise(tmp_path):
    """Concurrent connection setup plus writes must not raise on pragmas."""
    path = tmp_path / "pragmas.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}", future=True)
    configure_sqlite_engine(engine)
    try:
        async with engine.begin() as conn:
            await conn.exec_driver_sql("CREATE TABLE t (x INTEGER)")
            await conn.exec_driver_sql("INSERT INTO t VALUES (1)")

        stop = asyncio.Event()

        async def reader():
            while not stop.is_set():
                try:
                    async with engine.connect() as conn:
                        await conn.exec_driver_sql("SELECT count(*) FROM t")
                except Exception as exc:  # noqa: BLE001 - the point is the message
                    raise AssertionError(f"reader failed: {exc}") from exc

        async def writer():
            value = 0
            while not stop.is_set():
                value += 1
                async with engine.begin() as conn:
                    await conn.exec_driver_sql("INSERT INTO t VALUES (?)", (value,))

        tasks = [asyncio.create_task(reader()) for _ in range(6)]
        tasks.append(asyncio.create_task(writer()))
        await asyncio.sleep(0.75)
        stop.set()
        await asyncio.gather(*tasks, return_exceptions=False)

        async with engine.connect() as conn:
            rows = (await conn.exec_driver_sql("PRAGMA journal_mode")).fetchone()
        assert str(rows[0]).lower() == "wal"
    finally:
        await engine.dispose()
