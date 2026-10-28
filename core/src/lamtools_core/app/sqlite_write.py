from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from time import perf_counter
from typing import Any, TypeVar
from weakref import WeakKeyDictionary, WeakValueDictionary

from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

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


class _PragmaState:
    """Which one-time pragmas a connection hook has already established.

    ``journal_mode`` is a persistent property of the database file, so it only
    has to be set once per engine. Re-issuing it on every new connection made a
    pure read fail whenever another connection was mid-write: setting the mode
    wants a lock, and that statement does not honour the busy timeout, so it
    surfaced as ``database is locked`` at connection creation.
    """

    def __init__(self) -> None:
        self.journal_mode_ensured = False


def _apply_connection_pragmas(
    cursor: Any,
    state: _PragmaState,
    *,
    busy_timeout_ms: int = SQLITE_BUSY_TIMEOUT_MS,
) -> None:
    """Apply the per-connection pragmas; a failure never kills the connection.

    ``busy_timeout`` and ``synchronous`` are per-connection. The
    journal mode is set once (until it succeeds) and skipped afterwards. Every
    statement is best-effort: a transient lock must degrade to a warning instead
    of turning a read into a user-visible error.
    """
    # user:“一次 PRAGMA synchronous 要 0.4–1.4 秒”+(连接初始化可能受 I/O 压力影响，依靠连接复用摊薄成本)。
    started = perf_counter()
    try:
        cursor.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
    except Exception:  # noqa: BLE001 - best-effort connection setup
        logger.warning(
            "[sqlite] PRAGMA busy_timeout failed after %.3fs",
            perf_counter() - started,
            exc_info=True,
        )
    else:
        elapsed = perf_counter() - started
        if elapsed >= 0.05:
            logger.warning("[sqlite] PRAGMA busy_timeout took %.3fs", elapsed)
    if not state.journal_mode_ensured:
        started = perf_counter()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            state.journal_mode_ensured = True
        except Exception:  # noqa: BLE001 - retried on the next connection
            logger.warning(
                "[sqlite] PRAGMA journal_mode=WAL failed after %.3fs; a database "
                "not yet in WAL stays in its current mode until this succeeds",
                perf_counter() - started,
                exc_info=True,
            )
        else:
            logger.info(
                "[sqlite] initial PRAGMA journal_mode=WAL completed in %.3fs",
                perf_counter() - started,
            )
    started = perf_counter()
    try:
        cursor.execute("PRAGMA synchronous=NORMAL")
    except Exception:  # noqa: BLE001 - best-effort connection setup
        logger.warning(
            "[sqlite] PRAGMA synchronous=NORMAL failed after %.3fs",
            perf_counter() - started,
            exc_info=True,
        )
    else:
        elapsed = perf_counter() - started
        if elapsed >= 0.05:
            logger.warning("[sqlite] PRAGMA synchronous=NORMAL took %.3fs", elapsed)


def configure_sqlite_engine(engine: AsyncEngine, *, busy_timeout_ms: int = SQLITE_BUSY_TIMEOUT_MS) -> None:
    state = _PragmaState()

    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        try:
            _apply_connection_pragmas(cursor, state, busy_timeout_ms=busy_timeout_ms)
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
                    # user:“该修修，该重构重构，有必要就重新设计架构或者迁到 Rust”+(重复取消不得穿透数据库操作；事务回滚完成才释放写入所有权)。
                    cancelled = asyncio.Event()
                    transaction = asyncio.create_task(
                        self._transaction(action, cancelled), name="sqlite-write-transaction"
                    )
                    try:
                        return await asyncio.shield(transaction)
                    except asyncio.CancelledError:
                        cancelled.set()
                        # SQLite's worker continues executing even when its
                        # asyncio waiter is cancelled. Drain the same owner,
                        # including rollback/connection close, despite a second
                        # Stop escalation. Never hand its connection to a new writer.
                        while not transaction.done():
                            try:
                                await asyncio.shield(transaction)
                            except asyncio.CancelledError:
                                continue
                            except Exception:
                                break
                        if not transaction.cancelled():
                            transaction.exception()  # retrieve any failure while preserving cancellation
                        raise
                except OperationalError as exc:
                    if not _is_sqlite_locked_error(exc) or attempt >= len(self.retry_delays):
                        raise
                    await asyncio.sleep(self.retry_delays[attempt])
        raise RuntimeError("SQLite write retry exhausted")

    async def _transaction(self, action: WriteAction[T], cancelled: asyncio.Event) -> T:
        async with self.session_factory() as session:
            try:
                await session.execute(text("BEGIN IMMEDIATE"))
                if cancelled.is_set():
                    await session.rollback()
                    return None  # type: ignore[return-value]  # cancelled caller never consumes this result
                result = await action(session)
                if cancelled.is_set():
                    await session.rollback()
                else:
                    await session.commit()
                return result
            except BaseException:
                await session.rollback()
                raise


def _is_sqlite_locked_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    return "database is locked" in message or "database table is locked" in message


__all__ = [
    "SQLITE_BUSY_TIMEOUT_MS",
    "SQLiteWriteCoordinator",
    "_PragmaState",
    "_apply_connection_pragmas",
    "configure_sqlite_engine",
    "database_identity",
]
