from __future__ import annotations

import asyncio
import logging
import sqlite3
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

# user:“发送耗时原则上不应随历史会话长度显著增长”+(SQLite 默认 wal_autocheckpoint
# 是 1000 页≈4MB，超过就把整段 WAL 回写并 fsync 在提交线程里同步做完。会话越长，
# 单次写入量越大（2400 条会话一次约 1.3MB，用户的 6000 条会话约 7.8MB），于是几乎
# 每次发送都撞上一次 0.6-1.0s 的检查点停顿：实测长会话发送确认 p95 从 84ms 变成
# 801ms，停顿全部落在提交上。这里把同步检查点抬到只作兜底的上界，改由后台在空闲时
# 做 PASSIVE 检查点，请求路径不再承担检查点成本。
SQLITE_WAL_AUTOCHECKPOINT_PAGES = 32768          # 兜底上界，约 128MB（仅在后台巡检卡住时才会用到）
SQLITE_WAL_MAINTENANCE_PENDING_PAGES = 2048      # 未回写页超过这个水位就报警，约 8MB
SQLITE_WAL_MAINTENANCE_INTERVAL = 1.0            # 巡检间隔（秒）；被动检查点很快，间隔短才抢得到空档
SQLITE_PRUNE_INTERVAL = 60.0                     # 派生数据（同步日志）裁剪间隔（秒）


def sqlite_database_path(session_factory: Any) -> Path | None:
    """Return the database file behind a session factory, when it is a file."""
    identity = database_identity(session_factory)
    if not identity.startswith("sqlite:"):
        return None
    return Path(identity[len("sqlite:"):])


async def wal_maintenance_once(session_factory: Any) -> dict[str, int]:
    """Run one PASSIVE checkpoint and report the WAL frame state.

    A passive checkpoint never waits for readers or writers, so running it from
    a background task keeps the write path free of checkpoint stalls. The
    returned frame counts are the only honest signal here: the WAL *file* keeps
    its size after a checkpoint and is simply reused, so file size says nothing
    about how much is actually outstanding.
    """
    path = sqlite_database_path(session_factory)
    if path is None:
        return {"state": "no_file"}
    wal = path.with_name(f"{path.name}-wal")
    if not wal.exists():
        return {"state": "no_wal"}
    # user:“调查并检修 constant 内 sunday 出现过的所有报错，整理并给出方案，然后修复，不要出错”+(维护不能等待已耗尽的业务读池；独立短连接在工作线程执行被动检查点，既不堵事件循环也不创建丢失的数据库)。
    def checkpoint():
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=rw", uri=True, timeout=0)
        try:
            return connection.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
        finally:
            connection.close()

    row = await asyncio.to_thread(checkpoint)
    values = [int(value or 0) for value in (row or (0, 0, 0))]
    while len(values) < 3:
        values.append(0)
    busy, log_frames, checkpointed = values[:3]
    return {
        "state": "ok",
        "busy": busy,
        "log": log_frames,
        "checkpointed": checkpointed,
        "pending": max(0, log_frames - checkpointed),
    }


async def wal_maintenance_loop(
    session_factory: Any,
    *,
    interval: float = SQLITE_WAL_MAINTENANCE_INTERVAL,
    pending_pages: int = SQLITE_WAL_MAINTENANCE_PENDING_PAGES,
    prune: Any = None,
    prune_interval: float = SQLITE_PRUNE_INTERVAL,
) -> None:
    """Keep the WAL draining and the derived tables bounded off the request path.

    ``prune`` is an optional awaitable that trims derived data (the sync
    journal); it runs on its own slow cadence and never blocks a turn.
    """
    next_prune = perf_counter() + prune_interval
    while True:
        await asyncio.sleep(interval)
        if prune is not None and perf_counter() >= next_prune:
            next_prune = perf_counter() + prune_interval
            try:
                removed = await prune()
                if removed:
                    logger.info("[sqlite] pruned %d stale sync journal row(s)", removed)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - maintenance must never kill the host
                logger.warning("[sqlite] sync journal prune failed", exc_info=True)
        try:
            result = await wal_maintenance_once(session_factory)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - maintenance must never kill the host
            logger.warning("[sqlite] WAL maintenance checkpoint failed", exc_info=True)
            continue
        if result.get("pending", 0) >= pending_pages:
            # Readers are pinning the WAL; surface it instead of letting the
            # file grow silently.
            logger.warning("[sqlite] WAL is not draining: %s", result)

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
    # 同步检查点只作兜底；常态由 wal_maintenance_loop 在空闲时被动检查点。
    try:
        cursor.execute(f"PRAGMA wal_autocheckpoint={SQLITE_WAL_AUTOCHECKPOINT_PAGES}")
    except Exception:  # noqa: BLE001 - best-effort connection setup
        logger.warning("[sqlite] PRAGMA wal_autocheckpoint failed", exc_info=True)
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
