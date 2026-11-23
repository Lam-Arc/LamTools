"""Phase 3 acceptance tests: Rust sub-agent supervisor SQLite + unified control-plane writes.

user:“开始”+(第 3 期先行验收测试：覆盖子代理注册表/邮箱/唤醒与并发非阻塞、以及会话增删改与排队/取消/启动等控制面写入统一走 Rust 引擎的等价性与热缓存保持)。
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from lamtools_core.app.core_db import (
    CoreAppEvent,
    CoreArtifact,
    CoreAttachment,
    CoreHistoryEntry,
    CoreSyncChange,
    CoreThreadSnapshot,
    CoreThreadSnapshotItem,
    open_core_app_db,
    persist_core_run_items,
)
from lamtools_core.app.core_session_store import CoreDbSessionStore
from lamtools_core.app.live_operations import CoreLiveContext, wait_live_background_tasks
from lamtools_core.app.operation_catalog import OperationCatalog, OperationResult
from lamtools_core.event.run_item import RunItemEvent
from lamtools_core.runtime import RuntimeTaskRegistry
from lamtools_core.session import SessionRecord
from lamtools_core.sub_agent_supervisor import (
    SubAgentRecord,
    SubAgentSupervisor,
    acknowledge_parent_guidance,
    auto_release_unanswered,
    bump_wake_counts,
    drain_parent_mailbox,
    list_threads_with_pending_wakes,
    mark_mailbox_wake_delivered,
    mark_member_events_delivered,
    migrate_pending_member_events_to_wake,
    peek_member_events,
    peek_wake_messages,
)
from sqlalchemy import select


@dataclass
class _StubRunner:
    async def run(self, *args: Any, **kwargs: Any) -> Any:
        return None


class _StubHub:
    def __init__(self) -> None:
        self.published: list[Any] = []
        self.broadcasts: list[dict[str, Any]] = []

    async def publish(self, event: Any) -> None:
        self.published.append(event)

    async def broadcast(self, message: dict[str, Any]) -> None:
        self.broadcasts.append(dict(message))


class _StubRuntimeRegistry:
    def __init__(self) -> None:
        self.active: dict[str, str] = {}
        self.cancelled: list[tuple[str, str | None, bool]] = []

    def try_claim_run(self, thread_id: str, *, run_id: str, turn_id: str | None = None) -> bool:
        if thread_id in self.active:
            return False
        self.active[thread_id] = run_id
        return True

    def is_running(self, thread_id: str) -> bool:
        return thread_id in self.active

    def release_run(self, thread_id: str, *, run_id: str | None = None) -> None:
        if run_id is None or self.active.get(thread_id) == run_id:
            self.active.pop(thread_id, None)

    def cancel(self, thread_id: str, *, run_id: str | None = None, force: bool = False) -> bool:
        self.cancelled.append((thread_id, run_id, force))
        return True

    def clear(self) -> None:
        self.active.clear()


def _create_legacy_mailbox_db(path: Path) -> None:
    """Seed an old-schema `sub_agent_mailbox` table to test in-place migration."""
    with sqlite3.connect(path) as db:
        db.execute(
            """
            CREATE TABLE sub_agent_mailbox (
              id TEXT PRIMARY KEY,
              parent_thread_id TEXT NOT NULL,
              name TEXT NOT NULL,
              direction TEXT NOT NULL,
              body TEXT NOT NULL,
              digest TEXT NOT NULL,
              created_at REAL NOT NULL,
              delivered_at REAL
            )
            """
        )
        db.execute(
            """
            INSERT INTO sub_agent_mailbox(id, parent_thread_id, name, direction, body, digest, created_at, delivered_at)
            VALUES('legacy-1', 'p-mig', 'scout', 'child_to_parent', 'old report', 'abc', 100.0, NULL)
            """
        )


@pytest.mark.asyncio
async def test_sub_agent_rust_registry_mailbox_wake_and_fencing_parity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _run_scenario(db_dir: Path, *, disable_rust: bool) -> dict[str, Any]:
        if disable_rust:
            monkeypatch.setenv("LAMTOOLS_DISABLE_RUST_DB", "1")
        else:
            monkeypatch.delenv("LAMTOOLS_DISABLE_RUST_DB", raising=False)
        db_dir.mkdir(parents=True, exist_ok=True)
        db_path = db_dir / "sub_agents.db"
        _create_legacy_mailbox_db(db_path)

        sup = SubAgentSupervisor(
            database_path=db_path,
            parent_thread_id="p-mig",
            runner=_StubRunner(),
        )
        try:
            # Verify migrated legacy row survives
            drained_legacy = drain_parent_mailbox(db_path, "p-mig", mark_delivered=True)

            # Save + execution token fencing
            rec_a = SubAgentRecord(
                parent_thread_id="p-mig",
                name="alpha",
                type="execute",
                model_id="test-model",
                reasoning_level="medium",
                status="running",
                started_at=time.time() - 1.0,
                execution_token="tok-1",
            )
            rec_b = SubAgentRecord(
                parent_thread_id="p-mig",
                name="beta",
                type="execute",
                model_id="test-model",
                reasoning_level="low",
                status="running",
                started_at=time.time() - 2.0,
                execution_token="tok-b",
            )
            sup._save(rec_a)
            sup._save(rec_b)

            loaded_a = sup._load("alpha")
            assert loaded_a is not None and loaded_a.execution_token == "tok-1"

            # Wrong execution token must be rejected
            stale_copy = SubAgentRecord(**loaded_a.to_dict())
            stale_copy.status = "completed"
            fenced_wrong = sup._save_if_current(stale_copy, "wrong-tok")
            # Matching token must succeed
            fenced_ok = sup._save_if_current(stale_copy, "tok-1")
            # Subsequent write after completed->terminated fencing
            term_copy = SubAgentRecord(**stale_copy.to_dict())
            term_copy.status = "terminated"
            sup._save(term_copy)
            fenced_after_term = sup._save_if_current(stale_copy, "tok-1")

            # List & recover (beta had status='running' and no live owner -> interrupted)
            listed_before = await sup.list()
            await sup.recover()
            beta_after_recover = sup._load("beta")
            assert beta_after_recover is not None

            # parent_to_child mail dedup + pending + ack
            ins1 = sup._mail(
                "alpha",
                "parent_to_child",
                "first guidance",
                message_key="k1",
                source_call_id="c1",
                source_run_id="r1",
                source_turn_id="t1",
            )
            ins_dup = sup._mail(
                "alpha",
                "parent_to_child",
                "first guidance",
                message_key="k1",
            )
            pending_g = sup.pending_guidance("alpha")
            sup.acknowledge_guidance("alpha", [row["id"] for row in pending_g])
            pending_g_after = sup.pending_guidance("alpha")

            # child_to_parent wake + bump + auto-release
            sup._mail(
                "alpha",
                "child_to_parent",
                "need user choice",
                message_key="q1",
                tags="question",
                wake=1,
            )
            wake_threads = list_threads_with_pending_wakes(db_path)
            wakes = peek_wake_messages(db_path, "p-mig")
            q_ids = [w["id"] for w in wakes]
            acknowledge_parent_guidance(db_path, "p-mig", [f"sub-agent:p-mig:alpha:q1"])
            # Reset delivered_at check: verify wake_count + auto_release
            bumped = bump_wake_counts(db_path, "p-mig", q_ids)
            bumped = bump_wake_counts(db_path, "p-mig", q_ids)
            mark_mailbox_wake_delivered(db_path, "p-mig", q_ids)
            released = auto_release_unanswered(db_path, "p-mig", limit=2)
            release_guidance = sup.pending_guidance("alpha")

            # member events peek + mark + drain + migrate
            sup2 = SubAgentSupervisor(
                database_path=db_path,
                parent_thread_id="p-mig-2",
                runner=_StubRunner(),
            )
            try:
                rec2 = SubAgentRecord(
                    parent_thread_id="p-mig-2",
                    name="gamma",
                    type="execute",
                    model_id="test-model",
                    reasoning_level="medium",
                    status="completed",
                    summary="done!",
                    execution_token="tok-g",
                )
                sup2._save(rec2)
                ev_id = sup2._write_member_event(rec2, "member_finished")
                pending_ev_cnt = sup2._pending_mail_count()
                peeked_evs = peek_member_events(db_path, "p-mig-2")
                mark_member_events_delivered(db_path, [ev_id])
                drained_evs = await sup2.drain_member_events()

                # Fresh event migrated to wake
                rec2_b = SubAgentRecord(**rec2.to_dict())
                rec2_b.status = "failed"
                rec2_b.summary = "boom"
                sup2._write_member_event(rec2_b, "member_failed")
                migrated = migrate_pending_member_events_to_wake(db_path)
                migrated_wakes = peek_wake_messages(db_path, "p-mig-2")
            finally:
                sup2.release_db()

            return {
                "drained_legacy_bodies": [r["body"] for r in drained_legacy],
                "fenced_wrong": fenced_wrong,
                "fenced_ok": fenced_ok,
                "fenced_after_term": fenced_after_term,
                "listed_names": [r["name"] for r in listed_before],
                "beta_recovered_status": beta_after_recover.status,
                "ins1": ins1,
                "ins_dup": ins_dup,
                "pending_g_bodies": [r["body"] for r in pending_g],
                "pending_g_after": pending_g_after,
                "wake_threads": wake_threads,
                "wake_bodies": [w["body"] for w in wakes],
                "bumped": bumped,
                "released": released,
                "release_guidance_bodies": [r["body"] for r in release_guidance],
                "pending_ev_cnt": pending_ev_cnt,
                "peeked_ev_names": [e["payload"].get("event") for e in peeked_evs],
                "drained_evs": drained_evs,
                "migrated": migrated,
                "migrated_wake_names": [w["name"] for w in migrated_wakes],
                "migrated_wake_tags": [w["tags"] for w in migrated_wakes],
            }
        finally:
            sup.release_db()

    py_out = await _run_scenario(tmp_path / "py", disable_rust=True)
    rs_out = await _run_scenario(tmp_path / "rs", disable_rust=False)
    assert rs_out == py_out


@pytest.mark.asyncio
async def test_sub_agent_concurrent_mailbox_and_core_db_share_engine_smoothly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LAMTOOLS_DISABLE_RUST_DB", raising=False)
    db_path = tmp_path / "shared_core.db"
    db = await open_core_app_db(db_path, workspace_id="ws-shared")
    sessions = CoreDbSessionStore(lambda: db)
    await sessions.create(SessionRecord(id="parent-1", member_id="core", title="Parent", status="idle"))
    sup = SubAgentSupervisor(
        database_path=db_path,
        parent_thread_id="parent-1",
        runner=_StubRunner(),
    )
    try:
        assert sup._rust_db is not None
        assert db.rust_db is not None

        max_loop_lag_ms = 0.0
        stop_ticker = False

        async def _heartbeat() -> None:
            nonlocal max_loop_lag_ms
            prev = time.perf_counter()
            while not stop_ticker:
                await asyncio.sleep(0.01)
                now = time.perf_counter()
                lag = max(0.0, (now - prev - 0.01) * 1000.0)
                if lag > max_loop_lag_ms:
                    max_loop_lag_ms = lag
                prev = now

        async def _agent_worker(idx: int) -> None:
            name = f"worker-{idx}"
            rec = SubAgentRecord(
                parent_thread_id="parent-1",
                name=name,
                type="execute",
                model_id="m",
                reasoning_level="medium",
                status="running",
                started_at=time.time(),
                execution_token=f"tok-{idx}",
            )
            await asyncio.to_thread(sup._save, rec)
            for step in range(15):
                await asyncio.to_thread(
                    sup._mail,
                    name,
                    "child_to_parent",
                    f"progress-{step}",
                    message_key=f"mk-{idx}-{step}",
                    tags="message",
                    wake=1 if step == 14 else 0,
                )
                await persist_core_run_items(
                    db,
                    [
                        RunItemEvent(
                            event_id=f"sa-{idx}-{step}",
                            thread_id="parent-1",
                            turn_id="t1",
                            run_id="r1",
                            item_id=f"item-{idx}",
                            kind="assistant_delta",
                            status="running" if step < 14 else "completed",
                            payload={"type": "agentMessage", "delta": f"[{idx}:{step}]"},
                        )
                    ],
                )
            rec.status = "completed"
            await asyncio.to_thread(sup._save_if_current, rec, f"tok-{idx}")
            await asyncio.to_thread(sup._write_member_event, rec, "member_finished")

        async def _reader_poller() -> None:
            for _ in range(15):
                rows = await sup.list()
                _ = list_threads_with_pending_wakes(db_path)
                _ = peek_wake_messages(db_path, "parent-1")
                assert isinstance(rows, list)
                await asyncio.sleep(0.005)

        ticker_task = asyncio.create_task(_heartbeat())
        try:
            await asyncio.gather(
                *(_agent_worker(i) for i in range(4)),
                _reader_poller(),
            )
        finally:
            stop_ticker = True
            await ticker_task

        assert max_loop_lag_ms < 250.0, f"event loop blocked too long: {max_loop_lag_ms:.1f}ms"
        final_rows = await sup.list()
        assert len(final_rows) == 4
        assert all(r["status"] == "completed" for r in final_rows)
        events = await sup.drain_member_events()
        assert len(events) == 4
        wakes = peek_wake_messages(db_path, "p-mig" if False else "parent-1")
        assert len(wakes) == 8  # 4 progress wake messages + 4 member_finished wake messages
    finally:
        sup.release_db()
        await db.close()


@pytest.mark.asyncio
async def test_session_crud_and_delete_cascade_rust_parity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _run_crud(base_dir: Path, *, disable_rust: bool) -> dict[str, Any]:
        if disable_rust:
            monkeypatch.setenv("LAMTOOLS_DISABLE_RUST_DB", "1")
        else:
            monkeypatch.delenv("LAMTOOLS_DISABLE_RUST_DB", raising=False)
        base_dir.mkdir(parents=True, exist_ok=True)
        blob_keep = base_dir / "keep.bin"
        blob_drop = base_dir / "drop.bin"
        blob_keep.write_bytes(b"keep-me")
        blob_drop.write_bytes(b"drop-me")

        db = await open_core_app_db(base_dir / "core.db", workspace_id="ws-crud")
        try:
            store = CoreDbSessionStore(lambda: db)
            await store.create(
                SessionRecord(
                    id="s-del",
                    member_id="core",
                    title="新会话",
                    status="idle",
                    metadata={"work_root": "e:/proj", "project_id": "p1"},
                )
            )
            await store.create(
                SessionRecord(
                    id="s-keep",
                    member_id="core",
                    title="Keep",
                    status="idle",
                )
            )
            # Duplicate create must fail
            dup_raised = False
            try:
                await store.create(SessionRecord(id="s-del", member_id="core", title="dup", status="idle"))
            except ValueError:
                dup_raised = True

            # only_if_title_default skips when title already customized after rename
            patched_1 = await store.patch("s-del", title="Custom Title", only_if_title_default=True)
            patched_skip = await store.patch("s-del", title="Should Skip", only_if_title_default=True)

            # Seed attachments (one library-referenced -> must survive deletion, one unreferenced -> deleted)
            async def _seed_rows(conn: Any) -> None:
                conn.add(CoreAttachment(id="att-drop", session_id="s-del", filename="drop.bin", mime_type="text/plain", size=7, storage_path=str(blob_drop), preview_type="binary"))
                conn.add(CoreAttachment(id="att-keep", session_id="s-del", filename="keep.bin", mime_type="text/plain", size=7, storage_path=str(blob_keep), preview_type="binary"))
                conn.add(CoreArtifact(id="art-keep", normalized_path="attachment://att-keep", path="attachment://att-keep", name="saved", deleted=False))
                conn.add(CoreHistoryEntry(thread_id="s-del", seq=1, revision=1, message_json={"t": 1}))
                conn.add(CoreAppEvent(event_id="ev-del-1", thread_id="s-del", seq=1, method="thread/started", payload_json={}))
                conn.add(CoreThreadSnapshotItem(thread_id="s-del", item_id="it-1", seq=1, item_json={"x": 1}))
                await conn.flush()

            await db.persistence.write(_seed_rows)

            deleted = await store.delete("s-del")
            remaining_sessions = await store.list()

            async with db.session_factory() as conn:
                snap_del = await conn.get(CoreThreadSnapshot, "s-del")
                att_drop = await conn.get(CoreAttachment, "att-drop")
                att_keep = await conn.get(CoreAttachment, "att-keep")
                sync_ops = [
                    (r.entity_id, r.operation)
                    for r in (
                        await conn.execute(select(CoreSyncChange).order_by(CoreSyncChange.seq.asc()))
                    ).scalars().all()
                ]
            stats = db.rust_db.stats() if db.rust_db is not None else {}
            return {
                "dup_raised": dup_raised,
                "patched_1_title": patched_1.title if patched_1 else None,
                "patched_skip_is_none": patched_skip is None,
                "deleted": deleted,
                "remaining_ids": [r.id for r in remaining_sessions],
                "snap_del_none": snap_del is None,
                "att_drop_none": att_drop is None,
                "att_keep_exists": att_keep is not None,
                "blob_drop_exists": blob_drop.exists(),
                "blob_keep_exists": blob_keep.exists(),
                "sync_ops": sync_ops,
                "write_txs": stats.get("write_txs", 0),
            }
        finally:
            await db.close()

    py_out = await _run_crud(tmp_path / "py_crud", disable_rust=True)
    rs_out = await _run_crud(tmp_path / "rs_crud", disable_rust=False)
    assert rs_out.pop("write_txs") >= 4
    py_out.pop("write_txs")
    assert rs_out == py_out


@pytest.mark.asyncio
async def test_live_control_operations_unified_rust_write_parity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lamtools_core.app.live.queue import (
        handle_queue_create_operation,
        handle_queue_delete_operation,
        handle_queue_reorder_operation,
        handle_queue_update_operation,
    )
    from lamtools_core.app.live.threads import handle_thread_read_operation, handle_thread_start_operation
    from lamtools_core.app.live.turn_cancel import handle_turn_force_reset_operation

    async def _run_control(db_path: Path, *, disable_rust: bool) -> dict[str, Any]:
        if disable_rust:
            monkeypatch.setenv("LAMTOOLS_DISABLE_RUST_DB", "1")
        else:
            monkeypatch.delenv("LAMTOOLS_DISABLE_RUST_DB", raising=False)

        db = await open_core_app_db(db_path, workspace_id="ws-ctrl")
        sessions = CoreDbSessionStore(lambda: db)
        ops = OperationCatalog()

        async def _fake_turn_start(req: Any) -> OperationResult:
            return OperationResult(name="turn.start", payload={"ok": True})

        ops.register("turn.start", _fake_turn_start)
        context = CoreLiveContext(
            session_factory=db.session_factory,
            persistence=db.persistence,
            operations=ops,
            runtime_task_registry=RuntimeTaskRegistry(),
        )
        context.host.session_store = sessions
        try:
            start_1 = await handle_thread_start_operation(
                request_id=1,
                params={"thread_id": "t-ctrl", "title": "Ctrl", "require_new": True},
                context=context,
            )
            start_dup = await handle_thread_start_operation(
                request_id=2,
                params={"thread_id": "t-ctrl", "title": "Ctrl", "require_new": True},
                context=context,
            )
            # Mark a running turn + active item in Rust/Py snapshot so cancel/queue operate realistically
            await persist_core_run_items(
                db,
                [
                    RunItemEvent(
                        event_id="ev-run-1",
                        thread_id="t-ctrl",
                        turn_id="turn-a",
                        run_id="turn-a",
                        item_id="msg-a",
                        kind="assistant_delta",
                        status="running",
                        payload={"type": "agentMessage", "delta": "working"},
                    )
                ],
            )
            q1 = await handle_queue_create_operation(
                request_id=3,
                params={
                    "thread_id": "t-ctrl",
                    "input": [{"type": "text", "text": "first queued"}],
                    "client_message_id": "cq-1",
                },
                context=context,
            )
            q2 = await handle_queue_create_operation(
                request_id=4,
                params={
                    "thread_id": "t-ctrl",
                    "input": [{"type": "text", "text": "second queued"}],
                    "client_message_id": "cq-2",
                },
                context=context,
            )
            q1_id = q1.response["result"]["queue_item"]["queue_item_id"]
            q2_id = q2.response["result"]["queue_item"]["queue_item_id"]
            q_upd = await handle_queue_update_operation(
                request_id=5,
                params={"thread_id": "t-ctrl", "queue_item_id": q1_id, "text": "updated first"},
                context=context,
            )
            q_reord = await handle_queue_reorder_operation(
                request_id=6,
                params={"thread_id": "t-ctrl", "order": [q1_id, q2_id]},
                context=context,
            )
            q_del = await handle_queue_delete_operation(
                request_id=7,
                params={"thread_id": "t-ctrl", "queue_item_id": q1_id},
                context=context,
            )
            reset_out = await handle_turn_force_reset_operation(
                request_id=8,
                params={"thread_id": "t-ctrl", "turn_id": "turn-a"},
                context=context,
            )
            before_misses = db.rust_db.stats()["snapshot_cache_misses"] if db.rust_db is not None else 0
            read_out = await handle_thread_read_operation(
                request_id=9,
                params={"thread_id": "t-ctrl"},
                context=context,
            )
            after_misses = db.rust_db.stats()["snapshot_cache_misses"] if db.rust_db is not None else 0
            snap = read_out.response["result"]["snapshot"]
            stats = db.rust_db.stats() if db.rust_db is not None else {}
            return {
                "start_ok": "result" in start_1.response,
                "start_dup_code": start_dup.response["error"]["data"]["code"],
                "q_upd_input": q_upd.response["result"]["events"][0]["payload"]["input"],
                "reordered_matches": q_reord.response["result"]["events"][0]["payload"]["order"] == [q1_id, q2_id],
                "remaining_queue_texts": [item["input"][0]["text"] for item in snap.get("queue", [])],
                "reset_status": reset_out.response["result"]["status"],
                "final_status": snap.get("status"),
                "core_status": (snap.get("core") or {}).get("status"),
                "write_txs": stats.get("write_txs", 0),
                "cache_misses_on_read": after_misses - before_misses,
            }
        finally:
            context.runtime_task_registry.clear()
            await wait_live_background_tasks()
            await db.close()

    py_res = await _run_control(tmp_path / "py_ctrl.db", disable_rust=True)
    rs_res = await _run_control(tmp_path / "rs_ctrl.db", disable_rust=False)

    assert rs_res.pop("write_txs") >= 7
    assert rs_res.pop("cache_misses_on_read") == 0
    py_res.pop("write_txs")
    py_res.pop("cache_misses_on_read")
    assert rs_res == py_res
