"""Acceptance tests for Step 1 disk pressure & lock-contention optimizations.

user:“规划并实现”+(WAL 超体积空闲自动 TRUNCATE 缩容、Python/Rust 共用写锁消除双锁 5 秒空等、回合落盘取消写后全量重读)。
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from lamtools_core.app.core_db import open_core_app_db
from lamtools_core.app.default_agent import _persist_run_items
from lamtools_core.app.event_store import AppEventInput
from lamtools_core.app.persistence_host import AppPersistenceHost
from lamtools_core.app.rust_db import get_rust_db
from lamtools_core.app.sqlite_write import (
    SQLiteWriteCoordinator,
    configure_sqlite_engine,
    database_identity,
    wal_maintenance_tick,
)
from lamtools_core.event import RunItemEvent


@pytest.mark.asyncio
async def test_wal_maintenance_truncates_oversized_wal_even_when_pending_is_zero(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "wal_bloat.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}")
    configure_sqlite_engine(engine)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE TABLE pad (id INTEGER PRIMARY KEY, body TEXT)"))
            # Grow WAL above 128 KiB without hitting 128 MiB autocheckpoint
            payload = "W" * 4096
            for i in range(45):
                await conn.execute(
                    text("INSERT INTO pad (id, body) VALUES (:id, :body)"),
                    {"id": i, "body": payload},
                )
        wal_path = db_path.with_name(f"{db_path.name}-wal")
        assert wal_path.exists() and wal_path.stat().st_size >= 64 * 1024

        # First tick with wal_max_bytes above current size only runs PASSIVE (pending drops to 0, size stays big)
        passive_res = await wal_maintenance_tick(
            session_factory,
            pending_pages=2048,
            wal_max_bytes=1024 * 1024 * 1024,
            allow_truncate=True,
        )
        assert passive_res["pending"] == 0
        assert wal_path.stat().st_size >= 64 * 1024

        # Next tick with realistic wal_max_bytes threshold MUST run TRUNCATE even when pending == 0
        trunc_res = await wal_maintenance_tick(
            session_factory,
            pending_pages=2048,
            wal_max_bytes=64 * 1024,
            allow_truncate=True,
        )
        assert trunc_res["truncated"] is True
        assert wal_path.stat().st_size == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_python_write_coordinator_and_rust_write_ops_serialize_on_same_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LAMTOOLS_DISABLE_RUST_DB", raising=False)
    db_path = tmp_path / "shared_lock.db"
    db = await open_core_app_db(db_path, workspace_id="ws-lock")
    # Zero retries + tiny busy timeout cleanly proves zero file-lock collision!
    strict_coord = SQLiteWriteCoordinator(
        db.session_factory,
        identity=database_identity(db.session_factory),
        retry_delays=(),
    )
    rust_db = get_rust_db(db.session_factory)
    assert rust_db is not None and rust_db.is_active
    try:
        await db.persistence.append_batch_atomic(
            app_events=[
                AppEventInput(
                    event_id="s-lock:start",
                    thread_id="s-lock",
                    method="thread/started",
                    payload={"type": "thread", "status": "idle", "member_id": "core", "title": "Lock Test"},
                )
            ]
        )

        # Verify asyncio-level mutex holds Rust write behind Python coordinator without entering SQLite busy wait
        events_order: list[str] = []
        hold_gate = asyncio.Event()
        entered_py = asyncio.Event()

        async def _py_holder() -> None:
            async def _act(session: Any) -> None:
                events_order.append("py:enter")
                entered_py.set()
                await hold_gate.wait()
                await session.execute(text("SELECT COUNT(*) FROM core_thread_snapshots"))
                events_order.append("py:exit")

            await strict_coord.run(_act)

        holder_task = asyncio.create_task(_py_holder())
        await entered_py.wait()

        rust_task = asyncio.create_task(
            rust_db.call("session_patch", {"session_id": "s-lock", "patch": {"title": "From Rust"}})
        )
        await asyncio.sleep(0.05)
        # Rust write must wait on the shared in-process lock rather than racing while Python holds it
        assert not rust_task.done()
        hold_gate.set()
        await holder_task
        await rust_task
        assert events_order == ["py:enter", "py:exit"]

        # Concurrent stress burst: 15 Python transactions + 15 Rust writes must ALL finish with zero lock errors
        async def _py_write(idx: int) -> None:
            async def _act(session: Any) -> None:
                await session.execute(
                    text("UPDATE core_thread_snapshots SET revision = revision WHERE thread_id = 's-lock'")
                )

            await strict_coord.run(_act)

        async def _rs_write(idx: int) -> None:
            await db.persistence.append_batch_atomic(
                run_item_events=[
                    RunItemEvent(
                        event_id=f"s-lock:r:{idx}",
                        thread_id="s-lock",
                        turn_id="t1",
                        run_id="t1",
                        item_id=f"it-{idx}",
                        kind="assistant_delta",
                        status="completed",
                        payload={"type": "agentMessage", "delta": f"chunk-{idx}"},
                    )
                ]
            )

        tasks = [*[_py_write(i) for i in range(15)], *[_rs_write(i) for i in range(15)]]
        await asyncio.gather(*tasks)
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_persist_run_items_avoids_redundant_post_append_full_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LAMTOOLS_DISABLE_RUST_DB", raising=False)
    db_path = tmp_path / "no_reload.db"
    db = await open_core_app_db(db_path, workspace_id="ws-nr")
    load_calls = 0
    orig_load = AppPersistenceHost.load

    async def _counting_load(self: AppPersistenceHost, *args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal load_calls
        load_calls += 1
        return await orig_load(self, *args, **kwargs)

    monkeypatch.setattr(AppPersistenceHost, "load", _counting_load)
    try:
        await db.persistence.append_batch_atomic(
            app_events=[
                AppEventInput(
                    event_id="s-nr:start",
                    thread_id="s-nr",
                    method="thread/started",
                    payload={"type": "thread", "status": "idle", "member_id": "core", "title": "No Reload"},
                )
            ]
        )
        run_items = [
            RunItemEvent(
                event_id="s-nr:msg:1",
                thread_id="s-nr",
                turn_id="turn-1",
                run_id="turn-1",
                item_id="msg-1",
                kind="assistant_delta",
                status="completed",
                payload={"type": "agentMessage", "delta": "完成内容"},
            ),
            RunItemEvent(
                event_id="s-nr:st:1",
                thread_id="s-nr",
                turn_id="turn-1",
                run_id="turn-1",
                item_id="st-1",
                kind="status",
                status="completed",
                payload={"type": "turn", "status": "completed"},
            ),
        ]
        snap = await _persist_run_items(
            run_items,
            db_session_factory=db.session_factory,
            app_event_store=db.event_store,
            thread_snapshot_store=db.snapshot_store,
            write_coordinator=db.persistence.write_coordinator,
        )
        assert snap is not None
        assert snap["core"]["items"]["msg-1"]["content"] == "完成内容"
        assert snap["status"] == "completed"
        assert load_calls == 0
    finally:
        await db.close()
