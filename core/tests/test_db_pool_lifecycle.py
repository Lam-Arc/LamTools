"""Regression tests for database connection-pool lifecycle and observability.

The failure these guard against is the one users saw as::

    QueuePool limit of size 4 overflow 4 reached, connection timed out,
    timeout 30.00

which is a symptom: some operations held every pooled connection while others
queued behind them with no way to tell who held what. These tests pin down the
two properties that must hold for the pool to be healthy:

1. every path (normal, exception, cancellation, shutdown) returns its
   connection, so ``checkedout()`` falls back to 0;
2. when the pool does saturate, the app logs the holders and the checkout wait
   instead of only surfacing a bare timeout in an unrelated request.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from lamtools_core.app.core_db import open_core_app_db
from lamtools_core.app.db_pool import (
    InstrumentedAsyncQueuePool,
    attach_pool_telemetry,
)
from lamtools_core.app.event_store import AppEventInput


def _event(index: int, thread_id: str = "pool-thread") -> AppEventInput:
    return AppEventInput(
        thread_id=thread_id,
        method="item/started",
        turn_id=f"turn{index}",
        item_id=f"item{index}",
        payload={
            "type": "assistantMessage",
            "status": "completed",
            "content": [{"type": "text", "text": "x" * 64}],
        },
    )


async def _write_one(db, index: int) -> None:
    async def action(session):
        return await db.persistence.append_batch(session, app_events=[_event(index)])

    await db.persistence.write(action)


async def _read_one(db, thread_id: str = "pool-thread") -> None:
    async with db.session_factory() as session:
        await db.persistence.load(session, thread_id)


@pytest.mark.asyncio
async def test_concurrent_reads_and_writes_return_every_connection(tmp_path: Path) -> None:
    """A burst of writers plus readers must leave the pool empty afterwards."""
    db = await open_core_app_db(tmp_path / "pool.db", workspace_id="pool-test")
    try:
        assert db.pool_telemetry is not None
        await asyncio.gather(*[_write_one(db, index) for index in range(40)])
        await asyncio.gather(*[_read_one(db) for _ in range(40)])
        mixed = [*(_write_one(db, 100 + i) for i in range(20)), *(_read_one(db) for _ in range(20))]
        await asyncio.gather(*mixed)

        assert db.engine.pool.checkedout() == 0
        snapshot = db.pool_telemetry.snapshot()
        assert snapshot.checked_out == 0
        assert snapshot.checkout_timeouts == 0
    finally:
        await db.close()
    assert db.engine.pool.checkedout() == 0


@pytest.mark.asyncio
async def test_cancelled_operations_release_their_connections(tmp_path: Path) -> None:
    """取消风暴：被取消的读写不能把连接留在池里。"""
    db = await open_core_app_db(tmp_path / "cancel.db", workspace_id="pool-test")
    try:
        tasks = [asyncio.create_task(_write_one(db, index)) for index in range(15)]
        tasks += [asyncio.create_task(_read_one(db)) for _ in range(15)]
        await asyncio.sleep(0)
        for task in tasks:
            task.cancel()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        assert all(isinstance(item, asyncio.CancelledError) for item in results)

        await asyncio.sleep(0.2)
        assert db.engine.pool.checkedout() == 0
        # The database must still be usable after the cancellation storm.
        await _write_one(db, 999)
        assert db.engine.pool.checkedout() == 0
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_exception_inside_write_rolls_back_and_frees_connection(tmp_path: Path) -> None:
    """异常注入：写事务里抛错后连接必须回池，库仍可继续写。"""
    db = await open_core_app_db(tmp_path / "boom.db", workspace_id="pool-test")
    try:
        async def failing(session):
            await db.persistence.append_batch(session, app_events=[_event(1)])
            raise RuntimeError("injected failure")

        for _ in range(10):
            with pytest.raises(RuntimeError):
                await db.persistence.write(failing)

        assert db.engine.pool.checkedout() == 0
        await _write_one(db, 2)
        async with db.session_factory() as session:
            count = (
                await session.execute(text("select count(*) from core_app_events"))
            ).scalar_one()
        # Only the successful writes survive; the failing ones rolled back.
        assert count == 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_close_reports_and_releases_every_connection(tmp_path: Path) -> None:
    """应用退出：关闭后池内连接全部释放，且重复关闭不报错。"""
    db = await open_core_app_db(tmp_path / "close.db", workspace_id="pool-test")
    await _write_one(db, 1)
    telemetry = db.pool_telemetry
    assert telemetry is not None
    await db.close()
    assert db.engine.pool.checkedout() == 0
    assert telemetry._task is None  # watchdog stopped
    # A second close (shutdown hooks can run twice) must not explode.
    await db.close()


@pytest.mark.asyncio
async def test_pool_absorbs_traffic_above_its_capacity(tmp_path: Path) -> None:
    """远超池容量的并发不能变成超时：多的请求排队，但全部完成且连接回落。"""
    db = await open_core_app_db(tmp_path / "burst.db", workspace_id="pool-test")
    capacity = db.engine.pool.size() + int(getattr(db.engine.pool, "_max_overflow", 0))
    try:
        projected = capacity * 12
        results = await asyncio.gather(
            *[(_write_one(db, index) if index % 2 else _read_one(db)) for index in range(projected)],
            return_exceptions=True,
        )
        failures = [item for item in results if isinstance(item, BaseException)]
        assert not failures, failures[:3]
        assert db.engine.pool.checkedout() == 0
        assert db.pool_telemetry is not None
        assert db.pool_telemetry.snapshot().checkout_timeouts == 0
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_long_mixed_run_never_pins_the_pool(tmp_path: Path) -> None:
    """长跑混合压力：持续读写 + 周期性取消 + 周期性异常，连接数必须始终回落。"""
    db = await open_core_app_db(tmp_path / "soak.db", workspace_id="pool-test")
    try:
        deadline = asyncio.get_running_loop().time() + 4.0
        rounds = 0
        while asyncio.get_running_loop().time() < deadline:
            rounds += 1
            batch = [asyncio.create_task(_write_one(db, rounds * 100 + index)) for index in range(8)]
            batch += [asyncio.create_task(_read_one(db)) for _ in range(8)]
            if rounds % 3 == 0:
                await asyncio.sleep(0)
                for task in batch[:4]:
                    task.cancel()
            if rounds % 4 == 0:
                async def failing(session):
                    raise RuntimeError("soak failure")

                with pytest.raises(RuntimeError):
                    await db.persistence.write(failing)
            await asyncio.gather(*batch, return_exceptions=True)
            assert db.engine.pool.checkedout() <= 2, f"round {rounds} left connections checked out"

        assert db.engine.pool.checkedout() == 0
        assert db.pool_telemetry is not None
        snapshot = db.pool_telemetry.snapshot()
        assert snapshot.checkout_timeouts == 0
        assert rounds > 5
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_writes_survive_a_fully_booked_read_pool(tmp_path: Path) -> None:
    """写不能被并发的读饿死：读池占满时事件写入仍必须成功。

    这就是 2026-11-09 那次 `Unexpected error: QueuePool limit ...` 的现场：
    15/16 条连接被界面轮询和会话读取占着，回合的下一次事件写入拿不到连接，
    整轮对话被判失败。写池独立后，读池再满也不影响落库。
    """
    db = await open_core_app_db(tmp_path / "split.db", workspace_id="pool-test")
    capacity = db.engine.pool.size() + int(getattr(db.engine.pool, "_max_overflow", 0))
    held = []
    try:
        for _ in range(capacity):
            session = db.session_factory()
            await session.execute(text("select 1"))
            held.append(session)
        assert db.engine.pool.checkedout() == capacity

        started = asyncio.get_running_loop().time()
        await asyncio.wait_for(_write_one(db, 1), timeout=10)
        elapsed = asyncio.get_running_loop().time() - started

        assert elapsed < 5.0, f"write waited {elapsed:.2f}s behind a full read pool"
        assert db.engine.pool.checkedout() == capacity, "the read pool is still fully booked"
        assert db.write_engine is not None
        assert db.write_engine.pool.checkedout() == 0
    finally:
        for session in held:
            await session.close()
        await db.close()
    assert db.write_engine.pool.checkedout() == 0


@pytest.mark.asyncio
async def test_long_hold_warning_names_the_checkout_site(caplog: pytest.LogCaptureFixture) -> None:
    """长持有告警必须点名调用处，否则只能看到“某条连接被占了 8 秒”。"""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=InstrumentedAsyncQueuePool,
        pool_size=2,
        max_overflow=0,
    )
    telemetry = attach_pool_telemetry(engine, long_hold_seconds=0.0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    holder = factory()
    try:
        await holder.execute(text("select 1"))
        await asyncio.sleep(0.02)
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="lamtools_core.db.pool"):
            telemetry._check()

        messages = [record.getMessage() for record in caplog.records]
        assert any("held" in message and "via " in message and " in " in message
                   for message in messages), messages
    finally:
        await holder.close()
        await telemetry.stop()
        await engine.dispose()


@pytest.mark.asyncio
async def test_saturation_warning_names_the_holders(caplog: pytest.LogCaptureFixture) -> None:
    """池满时日志必须指出占用者数量与最长持有时间，而不是只有超时。"""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=InstrumentedAsyncQueuePool,
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.2,
    )
    telemetry = attach_pool_telemetry(engine, capture_stacks=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        holder = factory()
        await holder.execute(text("select 1"))
        caplog.clear()
        with caplog.at_level(logging.ERROR, logger="lamtools_core.db.pool"):
            telemetry._check()
            # First sample only marks the episode start; the promise is "one
            # warning per sustained episode", not "one per sample".
            telemetry.saturation_seconds = 0.0
            await asyncio.sleep(0.01)
            telemetry._check()

        messages = [record.getMessage() for record in caplog.records]
        assert any("pool saturated" in message for message in messages), messages
        assert any("holders:" in message for message in messages), messages
        assert telemetry.saturation_episodes == 1

        # A timed-out checkout must explain itself instead of being a bare error.
        caplog.clear()
        with caplog.at_level(logging.ERROR, logger="lamtools_core.db.pool"):
            with pytest.raises(Exception):
                other = factory()
                await other.execute(text("select 1"))
        assert telemetry.checkout_timeouts == 1
        assert any("checkout timed out" in r.getMessage() for r in caplog.records)

        await holder.close()
    finally:
        await holder.close()
        await telemetry.stop()
        await engine.dispose()


@pytest.mark.asyncio
async def test_telemetry_counts_checkout_queue_wait() -> None:
    """检出排队时间要被记录：这是“池成了瓶颈”的唯一直接信号。"""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=InstrumentedAsyncQueuePool,
        pool_size=1,
        max_overflow=0,
        pool_timeout=5,
    )
    telemetry = attach_pool_telemetry(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    holder = factory()
    await holder.execute(text("select 1"))

    second = factory()
    waiter = asyncio.create_task(second.execute(text("select 1")))
    await asyncio.sleep(0.25)
    await holder.close()
    await waiter
    await second.close()

    stats = engine.pool.wait_stats()
    assert stats["count"] >= 2
    assert stats["max"] >= 0.2
    assert telemetry.snapshot().waits["max"] >= 0.2

    await telemetry.stop()
    await engine.dispose()
