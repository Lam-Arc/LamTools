from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, TypeVar
from weakref import WeakValueDictionary

from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine


SQLITE_BUSY_TIMEOUT_MS = 5000
SQLITE_WRITE_RETRY_DELAYS = (0.05, 0.15, 0.35)

T = TypeVar("T")
WriteAction = Callable[[Any], Awaitable[T]]

_WRITE_LOCKS: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()


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
        lock = _WRITE_LOCKS.get(self.identity)
        if lock is None:
            lock = asyncio.Lock()
            _WRITE_LOCKS[self.identity] = lock
        self._lock = lock

    async def run(self, action: WriteAction[T]) -> T:
        async with self._lock:
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
