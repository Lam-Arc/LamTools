from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, TypeVar
from weakref import WeakKeyDictionary, WeakValueDictionary

from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine


SQLITE_BUSY_TIMEOUT_MS = 5000
SQLITE_WRITE_RETRY_DELAYS = (0.05, 0.15, 0.35)

T = TypeVar("T")
WriteAction = Callable[[Any], Awaitable[T]]

# asyncio.Lock instances are bound to the event loop that first contends on
# them. The desktop app normally has one loop, but Starlette TestClient and
# embedding hosts can reuse one database from several loops. Keep one lock
# per (database, loop), while SQLite's BEGIN IMMEDIATE + retry policy still
# handles cross-loop/process contention.
_WRITE_LOCKS: WeakKeyDictionary[
    asyncio.AbstractEventLoop,
    WeakValueDictionary[str, asyncio.Lock],
] = WeakKeyDictionary()


def _write_lock(identity: str) -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    locks = _WRITE_LOCKS.get(loop)
    if locks is None:
        locks = WeakValueDictionary()
        _WRITE_LOCKS[loop] = locks
    lock = locks.get(identity)
    if lock is None:
        lock = asyncio.Lock()
        locks[identity] = lock
    return lock


def configure_sqlite_engine(engine: AsyncEngine, *, busy_timeout_ms: int = SQLITE_BUSY_TIMEOUT_MS) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
        finally:
            cursor.close()


def database_identity(session_factory: Any) -> str:
    bind = getattr(session_factory, "kw", {}).get("bind")
    url = getattr(bind, "url", None)
    database = getattr(url, "database", None)
    if database and database != ":memory:":
        return f"sqlite:{Path(database).resolve()}".lower()
    return f"engine:{id(bind)}"


class SQLiteWriteCoordinator:
    def __init__(
        self,
        session_factory: Any,
        *,
        identity: str | None = None,
        retry_delays: tuple[float, ...] = SQLITE_WRITE_RETRY_DELAYS,
    ) -> None:
        self.session_factory = session_factory
        self.identity = identity or database_identity(session_factory)
        self.retry_delays = retry_delays
    async def run(self, action: WriteAction[T]) -> T:
        async with _write_lock(self.identity):
            for attempt in range(len(self.retry_delays) + 1):
                try:
                    async with self.session_factory() as session:
                        try:
                            await session.execute(text("BEGIN IMMEDIATE"))
                            result = await action(session)
                            await session.commit()
                            return result
                        except BaseException:
                            await session.rollback()
                            raise
                except OperationalError as exc:
                    if not _is_sqlite_locked_error(exc) or attempt >= len(self.retry_delays):
                        raise
                    await asyncio.sleep(self.retry_delays[attempt])
        raise RuntimeError("SQLite write retry exhausted")


def _is_sqlite_locked_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    return "database is locked" in message or "database table is locked" in message


__all__ = [
    "SQLITE_BUSY_TIMEOUT_MS",
    "SQLiteWriteCoordinator",
    "configure_sqlite_engine",
    "database_identity",
]
