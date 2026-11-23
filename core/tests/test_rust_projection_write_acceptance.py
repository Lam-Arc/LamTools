"""Acceptance tests for Rust event append, snapshot projection, turn-start fast path, and wire page building.

user:“实现，我需要最后可感觉到的体验优化”+(先把事件批量落库、快照增量投影、发送确认快路径与分页裁剪的验收测试写好，再落地 Rust 实现)。
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from lamtools_core.app.core_db import (
    CoreAppEvent,
    CoreSyncChange,
    CoreThreadSnapshot,
    CoreThreadSnapshotItem,
    open_core_app_db,
    persist_core_run_items,
)
from lamtools_core.app.core_session_store import CoreDbSessionStore
from lamtools_core.app.event_store import AppEventInput
from lamtools_core.app.live_operations import CoreLiveContext, wait_live_background_tasks
from lamtools_core.app.operation_catalog import OperationCatalog, OperationResult
from lamtools_core.app.persistence_host import RevisionConflictError
from lamtools_core.event import RunItemEvent
from lamtools_core.runtime import RuntimeTaskRegistry
from lamtools_core.session import SessionRecord


def _sample_batches(thread_id: str) -> tuple[list[AppEventInput], list[RunItemEvent]]:
    app_events = [
        AppEventInput(
            event_id=f"{thread_id}:e1",
            thread_id=thread_id,
            method="thread/started",
            payload={"type": "thread", "status": "idle", "member_id": "core", "title": "Parity Chat"},
        ),
        AppEventInput(
            event_id=f"{thread_id}:e2",
            thread_id=thread_id,
            method="turn/accepted",
            turn_id="turn-1",
            client_message_id="cmsg-1",
            payload={
                "type": "turn",
                "status": "running",
                "input": [{"type": "text", "text": "hello"}],
                "work_root": "e:/proj",
            },
        ),
        AppEventInput(
            event_id=f"{thread_id}:e3",
            thread_id=thread_id,
            method="item/started",
            turn_id="turn-1",
            item_id="user-1",
            client_message_id="cmsg-1",
            payload={"type": "userMessage", "status": "completed", "content": [{"type": "text", "text": "hello"}]},
        ),
        AppEventInput(
            event_id=f"{thread_id}:q1",
            thread_id=thread_id,
            method="queue/itemAccepted",
            item_id="qi-1",
            payload={"queue_item_id": "qi-1", "input": [{"type": "text", "text": "next"}]},
        ),
        AppEventInput(
            event_id=f"{thread_id}:q2",
            thread_id=thread_id,
            method="queue/itemAccepted",
            item_id="qi-2",
            payload={"queue_item_id": "qi-2", "input": [{"type": "text", "text": "after"}]},
        ),
        AppEventInput(
            event_id=f"{thread_id}:q3",
            thread_id=thread_id,
            method="queue/itemReordered",
            payload={"order": ["qi-2", "qi-1"]},
        ),
        AppEventInput(
            event_id=f"{thread_id}:q4",
            thread_id=thread_id,
            method="queue/itemDeleted",
            item_id="qi-1",
            payload={"queue_item_id": "qi-1"},
        ),
    ]
    run_items = [
        RunItemEvent(
            event_id=f"{thread_id}:r1",
            thread_id=thread_id,
            turn_id="turn-1",
            run_id="run-1",
            item_id="msg-1",
            kind="assistant_delta",
            status="running",
            payload={"type": "agentMessage", "delta": "Hel"},
        ),
        RunItemEvent(
            event_id=f"{thread_id}:r2",
            thread_id=thread_id,
            turn_id="turn-1",
            run_id="run-1",
            item_id="msg-1",
            kind="assistant_delta",
            status="completed",
            payload={"type": "agentMessage", "delta": "lo!"},
        ),
        RunItemEvent(
            event_id=f"{thread_id}:r3",
            thread_id=thread_id,
            turn_id="turn-1",
            run_id="run-1",
            item_id="tool-1",
            kind="tool_call",
            status="running",
            payload={"type": "toolCall", "tool_name": "read_file", "tool_call_id": "tc-1"},
        ),
        RunItemEvent(
            event_id=f"{thread_id}:r4",
            thread_id=thread_id,
            turn_id="turn-1",
            run_id="run-1",
            item_id="tool-1",
            kind="tool_result",
            status="completed",
            payload={"type": "toolResult", "tool_name": "read_file", "content": "ok"},
            artifacts=[
                {
                    "artifact_id": "art-1",
                    "kind": "image",
                    "mime_type": "image/png",
                    "metadata": {"image_data_url": "data:image/png;base64," + ("A" * 300_000)},
                }
            ],
        ),
        RunItemEvent(
            event_id=f"{thread_id}:r5",
            thread_id=thread_id,
            turn_id="turn-1",
            run_id="run-1",
            item_id="usage-1",
            kind="usage",
            status="completed",
            usage={"input_tokens": 120, "output_tokens": 30, "cached_tokens": 40},
            payload={"kind": "usage"},
        ),
        RunItemEvent(
            event_id=f"{thread_id}:r6",
            thread_id=thread_id,
            turn_id="turn-1",
            run_id="run-1",
            item_id="turn-1:status",
            kind="status",
            status="completed",
            payload={"type": "turn", "status": "completed", "duration_ms": 420},
        ),
    ]
    return app_events, run_items


async def _dump_db_state(db: Any, thread_id: str) -> dict[str, Any]:
    async with db.session_factory() as session:
        snap_row = await session.get(CoreThreadSnapshot, thread_id)
        item_rows = (
            await session.execute(
                select(CoreThreadSnapshotItem)
                .where(CoreThreadSnapshotItem.thread_id == thread_id)
                .order_by(CoreThreadSnapshotItem.seq.asc(), CoreThreadSnapshotItem.item_id.asc())
            )
        ).scalars().all()
        event_rows = (
            await session.execute(
                select(CoreAppEvent)
                .where(CoreAppEvent.thread_id == thread_id)
                .order_by(CoreAppEvent.seq.asc())
            )
        ).scalars().all()
        sync_rows = (
            await session.execute(
                select(CoreSyncChange)
                .where(CoreSyncChange.thread_id == thread_id)
                .order_by(CoreSyncChange.seq.asc())
            )
        ).scalars().all()
        full_snap = await db.snapshot_store.load(session, thread_id)
    return {
        "snapshot_seq": int(snap_row.snapshot_seq or 0) if snap_row else 0,
        "revision": int(snap_row.revision or 0) if snap_row else 0,
        "active_turn_id": snap_row.active_turn_id if snap_row else None,
        "snapshot_json": dict(snap_row.snapshot_json or {}) if snap_row else {},
        "items": {r.item_id: (r.seq, r.item_json) for r in item_rows},
        "events": [
            (r.event_id, r.seq, r.method, r.revision, r.event_seq)
            for r in event_rows
        ],
        "sync_ids": [(r.change_id, r.entity_type, r.revision) for r in sync_rows],
        "loaded": full_snap,
    }


@pytest.mark.asyncio
async def test_append_batch_parity_app_and_run_items(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    py_path = tmp_path / "py.db"
    rs_path = tmp_path / "rs.db"
    app_events, run_items = _sample_batches("t-parity")

    # 1. Python baseline
    monkeypatch.setenv("LAMTOOLS_DISABLE_RUST_DB", "1")
    py_db = await open_core_app_db(py_path, workspace_id="ws-p")
    try:
        async def _py_write(session: Any):
            return await py_db.persistence.append_batch(
                session, app_events=app_events, run_item_events=run_items
            )

        py_envelopes = await py_db.persistence.write(_py_write)
        py_dump = await _dump_db_state(py_db, "t-parity")
    finally:
        await py_db.close()

    # 2. Rust path
    monkeypatch.delenv("LAMTOOLS_DISABLE_RUST_DB", raising=False)
    rs_db = await open_core_app_db(rs_path, workspace_id="ws-p")
    try:
        assert rs_db.rust_db is not None
        assert rs_db.persistence.can_use_rust_write is True
        rs_envelopes = await rs_db.persistence.append_batch_atomic(
            app_events=app_events, run_item_events=run_items
        )
        rs_dump = await _dump_db_state(rs_db, "t-parity")

        assert [(e.event_id, e.seq, e.revision, e.method) for e in rs_envelopes] == [
            (e.event_id, e.seq, e.revision, e.method) for e in py_envelopes
        ]
        assert rs_dump["snapshot_seq"] == py_dump["snapshot_seq"]
        assert rs_dump["revision"] == py_dump["revision"]
        assert rs_dump["active_turn_id"] == py_dump["active_turn_id"]
        assert rs_dump["events"] == py_dump["events"]
        assert rs_dump["sync_ids"] == py_dump["sync_ids"]
        # user:“继续”+(超过阈值的 tool-1 在 Rust 写入时落盘轻量 _body_ref，未超阈值的 msg-1 与 Python 完全一致；完整水合等价性由下文 loaded.core.items 验证)
        assert set(rs_dump["items"].keys()) == set(py_dump["items"].keys())
        assert rs_dump["items"]["msg-1"] == py_dump["items"]["msg-1"]
        assert "_body_ref" in rs_dump["items"]["tool-1"][1]
        assert rs_dump["items"]["tool-1"][0] == py_dump["items"]["tool-1"][0]
        assert rs_dump["snapshot_json"]["status"] == py_dump["snapshot_json"]["status"]
        # user:“嗯”+(turns 与 artifacts 已拆出热点快照行，由加载态 loaded 与核心快照同步校验等价性)
        assert rs_dump["snapshot_json"]["core"]["artifacts"] == {}
        assert rs_dump["snapshot_json"]["core"]["turns"] == {}
        assert rs_dump["snapshot_json"]["turns"] == {}
        rs_turns = {
            tid: {**t, "created_at": "<iso>"}
            for tid, t in rs_dump["loaded"]["turns"].items()
        }
        py_turns = {
            tid: {**t, "created_at": "<iso>"}
            for tid, t in py_dump["loaded"]["turns"].items()
        }
        assert rs_dump["loaded"]["turns"]["turn-1"]["created_at"]
        assert py_dump["loaded"]["turns"]["turn-1"]["created_at"]
        assert rs_turns == py_turns
        assert rs_dump["snapshot_json"]["queue"] == py_dump["snapshot_json"]["queue"]
        assert rs_dump["snapshot_json"]["core"]["item_order"] == py_dump["snapshot_json"]["core"]["item_order"]
        assert rs_dump["loaded"]["core"]["turns"] == py_dump["loaded"]["core"]["turns"]
        assert rs_dump["loaded"]["core"]["artifacts"] == py_dump["loaded"]["core"]["artifacts"]
        assert rs_dump["loaded"]["core"]["items"] == py_dump["loaded"]["core"]["items"]

        # Cache must already be warm after the Rust write (no cold miss on subsequent load_page!).
        before_misses = rs_db.rust_db.stats()["snapshot_cache_misses"]
        async with rs_db.session_factory() as session:
            page = await rs_db.snapshot_store.load_page(session, "t-parity")
        after_misses = rs_db.rust_db.stats()["snapshot_cache_misses"]
        assert after_misses == before_misses
        assert page["status"] == "completed"
    finally:
        await rs_db.close()


@pytest.mark.asyncio
async def test_append_batch_dedup_cas_and_no_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LAMTOOLS_DISABLE_RUST_DB", raising=False)
    db = await open_core_app_db(tmp_path / "cas.db", workspace_id="ws-cas")
    try:
        assert db.rust_db is not None
        first = AppEventInput(
            event_id="evt-fixed-1",
            thread_id="t1",
            method="thread/started",
            payload={"type": "thread", "status": "idle"},
        )
        envs1 = await db.persistence.append_batch_atomic(app_events=[first])
        assert len(envs1) == 1 and envs1[0].seq == 1 and envs1[0].revision == 1

        # Same event_id on same thread is idempotent.
        envs_dup = await db.persistence.append_batch_atomic(app_events=[first])
        assert envs_dup[0].seq == 1 and envs_dup[0].revision == 1

        # Same event_id on a different thread must fail cleanly.
        wrong_thread = AppEventInput(
            event_id="evt-fixed-1",
            thread_id="t2",
            method="thread/started",
            payload={"type": "thread", "status": "idle"},
        )
        with pytest.raises(ValueError, match="another thread"):
            await db.persistence.append_batch_atomic(app_events=[wrong_thread])

        # Wrong expected_revision must raise RevisionConflictError without inserting.
        next_evt = AppEventInput(
            event_id="evt-2",
            thread_id="t1",
            method="turn/accepted",
            turn_id="turn-x",
            payload={"type": "turn", "status": "running"},
        )
        with pytest.raises(RevisionConflictError):
            await db.persistence.append_batch_atomic(
                app_events=[next_evt],
                expected_revision=0,
                revision_thread_id="t1",
            )

        # project_snapshot=False writes event table without bumping snapshot revision.
        envs_unproj = await db.persistence.append_batch_atomic(
            app_events=[next_evt],
            project_snapshot=False,
        )
        assert envs_unproj[0].seq == 2
        async with db.session_factory() as session:
            meta = await db.snapshot_store.load_metadata(session, "t1")
        assert meta["revision"] == 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_turn_start_fast_path_and_wire_page_parity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lamtools_core.app.live.threads import handle_thread_read_operation
    from lamtools_core.app.live.turn_start import handle_turn_start_operation

    async def _run_scenario(db_path: Path, disable_rust: bool) -> dict[str, Any]:
        if disable_rust:
            monkeypatch.setenv("LAMTOOLS_DISABLE_RUST_DB", "1")
        else:
            monkeypatch.delenv("LAMTOOLS_DISABLE_RUST_DB", raising=False)
        db = await open_core_app_db(db_path, workspace_id="ws-turn")
        sessions = CoreDbSessionStore(lambda: db)
        await sessions.create(SessionRecord(id="t-turn", member_id="core", title="Turn", status="idle"))
        operations = OperationCatalog()
        started = asyncio.Event()

        async def _fake_op(req: Any) -> OperationResult:
            started.set()
            return OperationResult(name="turn.start", payload={"ok": True})

        operations.register("turn.start", _fake_op)
        context = CoreLiveContext(
            session_factory=db.session_factory,
            persistence=db.persistence,
            operations=operations,
            runtime_task_registry=RuntimeTaskRegistry(),
        )
        context.host.session_store = sessions
        try:
            r1 = await handle_turn_start_operation(
                request_id=1,
                params={
                    "thread_id": "t-turn",
                    "client_message_id": "cm-1",
                    "input": [{"type": "text", "text": "build rust engine"}],
                },
                context=context,
            )
            r_dup = await handle_turn_start_operation(
                request_id=2,
                params={
                    "thread_id": "t-turn",
                    "client_message_id": "cm-1",
                    "input": [{"type": "text", "text": "build rust engine"}],
                },
                context=context,
            )
            r_busy = await handle_turn_start_operation(
                request_id=3,
                params={
                    "thread_id": "t-turn",
                    "client_message_id": "cm-2",
                    "input": [{"type": "text", "text": "second"}],
                },
                context=context,
            )
            task = context.runtime_task_registry.task("t-turn")
            if task is not None:
                await asyncio.gather(task, return_exceptions=True)
            context.runtime_task_registry.clear()
            await wait_live_background_tasks()

            # Persist an oversized image artifact item to test wire-page referencing parity.
            turn_id = r1.response["result"]["runtime_start"]["turn_id"]
            await persist_core_run_items(
                db,
                [
                    RunItemEvent(
                        event_id="ev-big",
                        thread_id="t-turn",
                        turn_id=turn_id,
                        item_id="item-big",
                        kind="tool_result",
                        status="completed",
                        payload={"type": "toolResult", "content": "image ready"},
                        artifacts=[
                            {
                                "artifact_id": "img-big",
                                "kind": "image",
                                "mime_type": "image/png",
                                "metadata": {"image_data_url": "data:image/png;base64," + ("B" * 300_000)},
                            }
                        ],
                    ),
                    RunItemEvent(
                        event_id="ev-done",
                        thread_id="t-turn",
                        turn_id=turn_id,
                        item_id="turn-status",
                        kind="status",
                        status="completed",
                        payload={"type": "turn", "status": "completed"},
                    ),
                ],
            )
            read_outcome = await handle_thread_read_operation(
                request_id=4,
                params={"thread_id": "t-turn"},
                context=context,
            )
            return {
                "turn_id": turn_id,
                "r1_events": len(r1.response["result"]["events"]),
                "r1_first_event_id": r1.response["result"]["events"][0]["event_id"],
                "dup_events": len(r_dup.response["result"]["events"]),
                "dup_first_event_id": r_dup.response["result"]["events"][0]["event_id"],
                "dup_has_runtime_start": "runtime_start" in r_dup.response["result"],
                "busy_code": r_busy.response["error"]["data"]["code"],
                "snapshot": read_outcome.response["result"]["snapshot"],
            }
        finally:
            context.runtime_task_registry.clear()
            await wait_live_background_tasks()
            await db.close()

    py_res = await _run_scenario(tmp_path / "py_turn.db", disable_rust=True)
    rs_res = await _run_scenario(tmp_path / "rs_turn.db", disable_rust=False)

    assert rs_res["r1_events"] == py_res["r1_events"] == 3
    assert rs_res["dup_events"] == py_res["dup_events"] == 1
    assert rs_res["dup_first_event_id"] == rs_res["r1_first_event_id"]
    assert rs_res["dup_has_runtime_start"] is False
    assert rs_res["busy_code"] == py_res["busy_code"] == "SESSION_BUSY"
    assert rs_res["snapshot"]["status"] == py_res["snapshot"]["status"] == "completed"
    assert rs_res["snapshot"]["history_page"] == py_res["snapshot"]["history_page"]
    rs_items = {
        iid: {
            **item,
            "turn_id": "<turn_id>" if item.get("turn_id") == rs_res["turn_id"] else item.get("turn_id"),
        }
        for iid, item in rs_res["snapshot"]["core"]["items"].items()
    }
    py_items = {
        iid: {
            **item,
            "turn_id": "<turn_id>" if item.get("turn_id") == py_res["turn_id"] else item.get("turn_id"),
        }
        for iid, item in py_res["snapshot"]["core"]["items"].items()
    }
    assert rs_items == py_items


@pytest.mark.asyncio
async def test_concurrent_streaming_and_multi_session_writes_keep_cache_warm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LAMTOOLS_DISABLE_RUST_DB", raising=False)
    db = await open_core_app_db(tmp_path / "stream.db", workspace_id="ws-stream")
    try:
        assert db.rust_db is not None
        sessions = CoreDbSessionStore(lambda: db)
        tids = [f"stream-{i}" for i in range(4)]
        for tid in tids:
            await sessions.create(SessionRecord(id=tid, member_id="core", title=tid, status="idle"))

        async def writer(tid: str) -> None:
            for step in range(30):
                await persist_core_run_items(
                    db,
                    [
                        RunItemEvent(
                            event_id=f"{tid}:ev:{step}",
                            thread_id=tid,
                            turn_id=f"{tid}:turn:1",
                            run_id="r1",
                            item_id=f"{tid}:msg:{step // 5}",
                            kind="assistant_delta",
                            status="running" if step < 29 else "completed",
                            payload={"type": "agentMessage", "delta": f"[{step}]"},
                        )
                    ],
                )
            await persist_core_run_items(
                db,
                [
                    RunItemEvent(
                        event_id=f"{tid}:done",
                        thread_id=tid,
                        turn_id=f"{tid}:turn:1",
                        run_id="r1",
                        item_id=f"{tid}:status",
                        kind="status",
                        status="completed",
                        payload={"type": "turn", "status": "completed"},
                    )
                ],
            )

        async def reader() -> None:
            for _ in range(30):
                await sessions.list()
                for tid in tids:
                    async with db.session_factory() as s:
                        await db.snapshot_store.load_page(s, tid)

        results = await asyncio.gather(
            *(writer(tid) for tid in tids),
            reader(),
            reader(),
            return_exceptions=True,
        )
        errors = [r for r in results if isinstance(r, BaseException)]
        assert not errors, errors

        stats = db.rust_db.stats()
        assert stats["snapshot_cache_hits"] > 50
        assert db.engine.pool.checkedout() == 0

        for tid in tids:
            async with db.session_factory() as s:
                snap = await db.snapshot_store.load(s, tid)
            assert snap["status"] == "completed"
            assert snap["snapshot_seq"] == 31
    finally:
        await db.close()
