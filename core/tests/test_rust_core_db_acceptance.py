"""Acceptance tests for the Rust native database engine (sunday-core-db).

user:“加载/切换/多会话多 agent 同时读写”+(先把加载、切换与多会话多代理并发读写的验收测试写好，再实现 Rust 存储引擎与 Python 桥接)。
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from lamtools_core.app.core_db import (
    CoreAppEvent,
    CoreRuntimeSession,
    CoreThreadSnapshot,
    CoreThreadSnapshotItem,
    CoreTurnInteraction,
    list_core_sessions,
    open_core_app_db,
    show_core_session,
)
from lamtools_core.app.core_session_store import CoreDbSessionStore
from lamtools_core.app.event_store import AppEventInput
from lamtools_core.runtime import RuntimeState, RuntimeStateConflictError
from lamtools_core.session import SessionRecord
from lamtools_core.turn.model import AgentRun
from lamtools_core.turn.store import TurnStore


async def _seed_rich_sessions(db: Any, count: int = 8) -> list[str]:
    """Populate realistic multi-session data with items, turns, events, plans and interactions."""
    store = CoreDbSessionStore(lambda: db)
    base_time = datetime(2026, 11, 17, 10, 0, 0)
    thread_ids: list[str] = []

    async def write(session: Any) -> None:
        for idx in range(count):
            tid = f"thread-{idx:02d}"
            thread_ids.append(tid)
            is_orphan_running = idx == 1
            turns: dict[str, Any] = {}
            item_order: list[str] = []
            items_inline: dict[str, Any] = {}
            for t in range(12):
                turn_id = f"{tid}:turn:{t}"
                u_id = f"{tid}:user:{t}"
                a_id = f"{tid}:agent:{t}"
                item_order.extend([u_id, a_id])
                items_inline[u_id] = {
                    "id": u_id,
                    "type": "userMessage",
                    "turn_id": turn_id,
                    "seq": t * 2 + 1,
                    "content": [{"type": "text", "text": f"Prompt {t} " + ("x" * 256)}],
                }
                status = "running" if (is_orphan_running and t == 11) else "completed"
                turns[turn_id] = {
                    "id": turn_id,
                    "status": status,
                    "items": [u_id, a_id],
                }
                session.add(
                    CoreThreadSnapshotItem(
                        thread_id=tid,
                        item_id=a_id,
                        seq=t * 2 + 2,
                        item_json={
                            "id": a_id,
                            "type": "agentMessage",
                            "turn_id": turn_id,
                            "status": "completed",
                            "content": [{"type": "text", "text": f"Answer {t} for {tid} " + ("y" * 512)}],
                        },
                        updated_at=base_time + timedelta(seconds=idx * 10 + t),
                    )
                )

            snapshot_payload = {
                "thread_id": tid,
                "status": "running" if is_orphan_running else "idle",
                "snapshot_seq": 24,
                "revision": idx + 1,
                "session": {
                    "id": tid,
                    "member_id": "core" if idx % 2 == 0 else "researcher",
                    "title": f"Session {idx}",
                    "status": "running" if is_orphan_running else "idle",
                    "created_at": (base_time + timedelta(minutes=idx)).isoformat(),
                    "metadata": {
                        "work_root": f"e:/work/proj_{idx % 3}",
                        "runtime_preferences": {"approval_policy": "default"},
                        **({"owner_plugin": "hidden-plugin"} if idx == 2 else {}),
                    },
                },
                "core": {
                    "thread_id": tid,
                    "status": "running" if is_orphan_running else "idle",
                    "item_order": item_order,
                    "items": items_inline,
                    "turns": turns,
                    "resource_usage_version": 1,
                    "resource_usage": {"input_tokens": 100 + idx, "output_tokens": 50 + idx},
                },
            }
            session.add(
                CoreThreadSnapshot(
                    thread_id=tid,
                    snapshot_seq=24,
                    revision=idx + 1,
                    active_turn_id=f"{tid}:turn:11" if is_orphan_running else None,
                    snapshot_json=snapshot_payload,
                    updated_at=base_time + timedelta(minutes=idx),
                )
            )
            session.add(
                CoreAppEvent(
                    event_id=f"{tid}:evt:1",
                    thread_id=tid,
                    seq=1,
                    turn_id=f"{tid}:turn:0",
                    item_id=f"{tid}:agent:0",
                    method="core/run_item",
                    payload_json={"kind": "status", "status": "completed", "payload": {"type": "turn"}},
                    created_at=base_time + timedelta(minutes=idx),
                )
            )
            if idx == 0:
                session.add(
                    CoreTurnInteraction(
                        interaction_id=f"{tid}:int:1",
                        thread_id=tid,
                        turn_id=f"{tid}:turn:11",
                        kind="approval",
                        status="open",
                        title="Approve tool",
                        body="Run check",
                        facts_json=[{"label": "cmd", "value": "dir"}],
                        options_json=[{"id": "allow", "label": "Allow"}],
                        default_answer_json={},
                        metadata_json={},
                    )
                )
                session.add(
                    CoreRuntimeSession(
                        thread_id=tid,
                        revision=1,
                        runtime_state_json={
                            "session_id": tid,
                            "status": "idle",
                            "metadata": {
                                "task_plan": {
                                    "title": "Main Plan",
                                    "steps": [{"id": "s1", "title": "Step 1", "status": "pending"}],
                                }
                            },
                        },
                        history_json=[],
                        pending_approval_json={},
                        last_event_seq=0,
                        updated_at=base_time + timedelta(minutes=idx),
                    )
                )

    await db.persistence.write(write)
    assert store is not None
    return thread_ids


@pytest.mark.asyncio
async def test_rust_db_engine_is_active_and_closes_cleanly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LAMTOOLS_DISABLE_RUST_DB", raising=False)
    db_path = tmp_path / "lifecycle.db"
    db = await open_core_app_db(db_path, workspace_id="ws-rust")
    try:
        assert db.rust_db is not None
        assert db.rust_db.is_active is True
    finally:
        await db.close()
    # All Rust & SQLAlchemy file handles must be released on close (critical on Windows).
    db_path.unlink()
    assert not db_path.exists()


@pytest.mark.asyncio
async def test_fast_session_loading_parity_and_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "loading.db"

    # 1. Seed once and collect Python baseline.
    monkeypatch.setenv("LAMTOOLS_DISABLE_RUST_DB", "1")
    py_db = await open_core_app_db(db_path, workspace_id="ws-load")
    try:
        assert py_db.rust_db is None
        await _seed_rich_sessions(py_db, count=10)
        py_sessions_store = CoreDbSessionStore(
            lambda: py_db,
            session_visible=lambda _sid, meta: meta.get("owner_plugin") != "hidden-plugin",
        )
        py_list = await py_sessions_store.list()
        py_core_list = await list_core_sessions(py_db)
        async with py_db.session_factory() as py_conn:
            py_sync_snapshot = await py_db.sync_journal.build_snapshot(py_conn)
    finally:
        await py_db.close()

    # 2. Re-open with Rust enabled and verify exact parity + cache hits.
    monkeypatch.delenv("LAMTOOLS_DISABLE_RUST_DB", raising=False)
    rs_db = await open_core_app_db(db_path, workspace_id="ws-load")
    try:
        assert rs_db.rust_db is not None
        rs_sessions_store = CoreDbSessionStore(
            lambda: rs_db,
            session_visible=lambda _sid, meta: meta.get("owner_plugin") != "hidden-plugin",
        )
        rs_list = await rs_sessions_store.list()
        rs_core_list = await list_core_sessions(rs_db)

        assert [(s.id, s.member_id, s.title, s.status, s.metadata, s.created_at, s.updated_at) for s in rs_list] == [
            (s.id, s.member_id, s.title, s.status, s.metadata, s.created_at, s.updated_at) for s in py_list
        ]
        assert rs_core_list == py_core_list

        # Second list call must hit the Rust summary cache for every unchanged thread.
        before_hits = rs_db.rust_db.stats()["summary_cache_hits"]
        rs_list_cached = await rs_sessions_store.list()
        after_hits = rs_db.rust_db.stats()["summary_cache_hits"]
        assert len(rs_list_cached) == len(rs_list)
        assert after_hits - before_hits >= 10

        async with rs_db.session_factory() as conn:
            rs_sync_snapshot = await rs_db.sync_journal.build_snapshot(conn)
        assert [t["id"] for t in rs_sync_snapshot["threads"]] == [t["id"] for t in py_sync_snapshot["threads"]]

        # Mutating one session invalidates only that session and reflects immediately.
        await rs_sessions_store.patch("thread-00", title="Renamed Session 0")
        rs_list_after_patch = await rs_sessions_store.list()
        by_id = {s.id: s for s in rs_list_after_patch}
        assert by_id["thread-00"].title == "Renamed Session 0"
    finally:
        await rs_db.close()


@pytest.mark.asyncio
async def test_fast_session_switching_and_bounded_page_parity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "switching.db"

    monkeypatch.setenv("LAMTOOLS_DISABLE_RUST_DB", "1")
    py_db = await open_core_app_db(db_path, workspace_id="ws-switch")
    try:
        thread_ids = await _seed_rich_sessions(py_db, count=6)
        py_pages: dict[str, dict[str, Any]] = {}
        py_outlines: dict[str, dict[str, Any]] = {}
        py_shows: dict[str, dict[str, Any]] = {}
        async with py_db.session_factory() as session:
            for tid in thread_ids:
                py_pages[tid] = await py_db.snapshot_store.load_page(
                    session, tid, item_byte_budget=2500
                )
                py_outlines[tid] = await py_db.snapshot_store.load_items_by_kind(
                    session, tid, text_marker="agentMessage"
                )
        py_shows["thread-00"] = await show_core_session(py_db, "thread-00")
        async with py_db.session_factory() as session:
            py_around = await py_db.snapshot_store.load_page_around(
                session, "thread-00", item_id="thread-00:agent:5", item_byte_budget=2500
            )
    finally:
        await py_db.close()

    monkeypatch.delenv("LAMTOOLS_DISABLE_RUST_DB", raising=False)
    rs_db = await open_core_app_db(db_path, workspace_id="ws-switch")
    try:
        assert rs_db.rust_db is not None
        rs_sessions = CoreDbSessionStore(lambda: rs_db)
        # Switch repeatedly across all 6 sessions (exceeds old Python cache limit of 2).
        for _ in range(2):
            for tid in thread_ids:
                assert await rs_sessions.exists(tid) is True
                async with rs_db.session_factory() as session:
                    rs_page = await rs_db.snapshot_store.load_page(
                        session, tid, item_byte_budget=2500
                    )
                assert rs_page["core"]["items"] == py_pages[tid]["core"]["items"]
                assert rs_page["core"]["_page_has_older_items"] == py_pages[tid]["core"]["_page_has_older_items"]
                assert rs_page["core"]["_page_total_items"] == py_pages[tid]["core"]["_page_total_items"]
                assert rs_page["core"]["decisions"] == py_pages[tid]["core"]["decisions"]
                assert rs_page["core"]["task_plan"] == py_pages[tid]["core"]["task_plan"]

        assert rs_db.rust_db.stats()["snapshot_cache_hits"] >= len(thread_ids)

        async with rs_db.session_factory() as session:
            rs_outline = await rs_db.snapshot_store.load_items_by_kind(
                session, "thread-03", text_marker="agentMessage"
            )
            rs_around = await rs_db.snapshot_store.load_page_around(
                session, "thread-00", item_id="thread-00:agent:5", item_byte_budget=2500
            )
        assert rs_outline["core"]["items"] == py_outlines["thread-03"]["core"]["items"]
        assert rs_around[0] == py_around[0]
        assert rs_around[1]["core"]["items"] == py_around[1]["core"]["items"]

        rs_show = await show_core_session(rs_db, "thread-00")
        assert rs_show["events"] == py_shows["thread-00"]["events"]
        assert rs_show["snapshot"]["core"]["items"] == py_shows["thread-00"]["snapshot"]["core"]["items"]
        assert await rs_sessions.exists("missing-thread") is False
    finally:
        await rs_db.close()


@pytest.mark.asyncio
async def test_multi_session_multi_agent_concurrent_read_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LAMTOOLS_DISABLE_RUST_DB", raising=False)
    db = await open_core_app_db(tmp_path / "concurrent.db", workspace_id="ws-conc")
    try:
        assert db.rust_db is not None
        sessions_store = CoreDbSessionStore(lambda: db)
        turn_store = TurnStore(db.session_factory, db.persistence.write_coordinator)

        # Create 4 sessions first.
        session_ids = [f"conc-session-{i}" for i in range(4)]
        for sid in session_ids:
            await sessions_store.create(
                SessionRecord(id=sid, member_id="core", title=f"Thread {sid}", status="idle")
            )

        async def session_writer(sid: str) -> None:
            state = RuntimeState(session_id=sid, run_id=f"run-{sid}", status="running")
            await db.runtime_state_store.save(state)
            for step in range(25):
                state.metadata["step"] = step
                state.turn_count = step
                await db.runtime_state_store.save(state)
                await db.runtime_state_store.append_history(
                    sid, [{"role": "user", "content": f"msg-{sid}-{step}"}]
                )
                await db.runtime_state_store.append_dialogue_record(
                    sid, kind="compaction", record={"step": step}, branch_epoch=1, watermark=step
                )

                def _mutate(st: RuntimeState) -> None:
                    st.metadata["patched_step"] = step

                patched = await db.runtime_state_store.patch(sid, _mutate)
                assert patched is not None
                state = patched

        async def agent_worker(worker_idx: int) -> None:
            parent_tid = session_ids[worker_idx % len(session_ids)]
            run_id = f"agent-run-{worker_idx}"
            for step in range(20):
                await turn_store.upsert_agent_run(
                    AgentRun(
                        agent_run_id=run_id,
                        parent_thread_id=parent_tid,
                        parent_turn_id=f"{parent_tid}:turn:0",
                        name=f"worker-{worker_idx}",
                        status="running" if step < 19 else "completed",
                        summary=f"step {step}",
                        started_at_ms=1000 + worker_idx,
                        completed_at_ms=2000 if step == 19 else 0,
                    )
                )
                async def _append_evt(session):
                    return await db.persistence.append(
                        session,
                        AppEventInput(
                            thread_id=parent_tid,
                            method="item/started",
                            turn_id=f"{parent_tid}:turn:0",
                            item_id=f"{run_id}:item:{step}",
                            payload={"type": "agentMessage", "status": "completed"},
                        ),
                    )

                await db.persistence.write(_append_evt)

        async def concurrent_poller() -> None:
            for _ in range(40):
                await sessions_store.list()
                for sid in session_ids:
                    await sessions_store.exists(sid)
                    await db.runtime_state_store.get(sid)
                    await db.runtime_state_store.read_history_page(sid, after_seq=0, limit=50)
                    await turn_store.list_agent_runs(parent_thread_id=sid)

        results = await asyncio.gather(
            *(session_writer(sid) for sid in session_ids),
            *(agent_worker(i) for i in range(8)),
            concurrent_poller(),
            concurrent_poller(),
            return_exceptions=True,
        )
        errors = [r for r in results if isinstance(r, BaseException)]
        assert not errors, errors

        for sid in session_ids:
            final_state = await db.runtime_state_store.get(sid)
            assert final_state is not None
            assert final_state.metadata["step"] == 24
            assert final_state.metadata["patched_step"] == 24
            assert await db.runtime_state_store.history_max_seq(sid) == 25
            records = await db.runtime_state_store.list_dialogue_records(sid)
            assert [r["seq"] for r in records] == list(range(1, 26))
            runs = await turn_store.list_agent_runs(parent_thread_id=sid)
            assert len(runs) == 2
            assert all(r.status == "completed" for r in runs)

        assert db.engine.pool.checkedout() == 0

        # Verify stale-revision conflict protection against a live owner in Rust.
        stale_state = RuntimeState(session_id=session_ids[0], run_id="rogue-run", status="running")
        with pytest.raises(RuntimeStateConflictError):
            await db.runtime_state_store.save(stale_state)
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_project_store_sessions_and_pins_parity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "projects.db"
    work_root = str((tmp_path / "proj_a").resolve())
    Path(work_root).mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("LAMTOOLS_DISABLE_RUST_DB", "1")
    py_db = await open_core_app_db(db_path, workspace_id="ws-proj")
    try:
        proj, s1, _ = await py_db.project_store.ensure_session(work_root, "p-s1", title="Session 1")
        _, s2, _ = await py_db.project_store.ensure_session(work_root, "p-s2", title="Session 2")
        await py_db.project_store.pin_session(proj.id, s2.id)
        py_sessions = [s.id for s in await py_db.project_store.list_sessions(proj.id)]
        py_pinned = await py_db.project_store.pinned_session_ids(proj.id)
    finally:
        await py_db.close()

    monkeypatch.delenv("LAMTOOLS_DISABLE_RUST_DB", raising=False)
    rs_db = await open_core_app_db(db_path, workspace_id="ws-proj")
    try:
        assert rs_db.rust_db is not None
        assert [s.id for s in await rs_db.project_store.list_sessions(proj.id)] == py_sessions
        assert await rs_db.project_store.pinned_session_ids(proj.id) == py_pinned
        await rs_db.project_store.pin_session(proj.id, s1.id)
        assert await rs_db.project_store.pinned_session_ids(proj.id) == [s1.id, s2.id]
        await rs_db.project_store.unpin_session(proj.id, s2.id)
        assert await rs_db.project_store.pinned_session_ids(proj.id) == [s1.id]
    finally:
        await rs_db.close()
