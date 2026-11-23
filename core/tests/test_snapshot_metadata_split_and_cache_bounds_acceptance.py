"""Acceptance tests for Batch 3: splitting snapshot artifacts/turns out of the hot row and bounding Rust EngineCache.

user:“嗯”+(将大体积 core.artifacts 与 turns 从核心热点行 snapshot_json 中拆出按增量持久化，并为 Rust 缓存设置条目与字节上限，消减机械盘写放大与内存上涨)。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from lamtools_core.app.core_db import open_core_app_db
from lamtools_core.app.core_session_store import CoreDbSessionStore
from lamtools_core.app.event_store import AppEventInput
from lamtools_core.app.live.threads import (
    handle_thread_history_operation,
    handle_thread_outline_operation,
    handle_thread_read_operation,
)
from lamtools_core.app.live_operations import CoreLiveContext, wait_live_background_tasks
from lamtools_core.app.operation_catalog import OperationCatalog
from lamtools_core.event import RunItemEvent
from lamtools_core.runtime import RuntimeTaskRegistry
from lamtools_core.session import SessionRecord


async def _seed_heavy_artifacts_and_turns_thread(db: Any, thread_id: str) -> None:
    await db.persistence.append_batch_atomic(
        app_events=[
            AppEventInput(
                event_id=f"{thread_id}:start",
                thread_id=thread_id,
                method="thread/started",
                payload={"type": "thread", "status": "idle", "member_id": "core", "title": "Heavy Split"},
            )
        ]
    )
    for t_idx in range(1, 5):
        tid = f"turn-{t_idx}"
        await db.persistence.append_batch_atomic(
            app_events=[
                AppEventInput(
                    event_id=f"{thread_id}:acc:{t_idx}",
                    thread_id=thread_id,
                    method="turn/accepted",
                    turn_id=tid,
                    item_id=f"{tid}:user",
                    payload={
                        "type": "turn",
                        "turn_id": tid,
                        "user_item_id": f"{tid}:user",
                        "input": [{"type": "text", "text": f"问题 {t_idx}"}],
                    },
                ),
                AppEventInput(
                    event_id=f"{thread_id}:usr:{t_idx}",
                    thread_id=thread_id,
                    method="item/started",
                    turn_id=tid,
                    item_id=f"{tid}:user",
                    payload={
                        "type": "userMessage",
                        "item_id": f"{tid}:user",
                        "turn_id": tid,
                        "content": [{"type": "text", "text": f"问题 {t_idx}"}],
                    },
                ),
            ],
            run_item_events=[
                RunItemEvent(
                    event_id=f"{thread_id}:cmd:{t_idx}",
                    thread_id=thread_id,
                    turn_id=tid,
                    run_id=f"run-{t_idx}",
                    item_id=f"cmd-{t_idx}",
                    kind="tool_result",
                    status="completed",
                    payload={"type": "commandExecution", "command": "pytest", "content": "ok"},
                    artifacts=[
                        {
                            "artifact_id": f"art-{t_idx}",
                            "kind": "command_output",
                            "metadata": {
                                "command": "pytest",
                                "stdout": f"OUT-{t_idx}:" + ("S" * 18_000),
                                "stderr": "",
                            },
                        }
                    ],
                ),
                RunItemEvent(
                    event_id=f"{thread_id}:msg:{t_idx}",
                    thread_id=thread_id,
                    turn_id=tid,
                    run_id=f"run-{t_idx}",
                    item_id=f"msg-{t_idx}",
                    kind="message",
                    status="completed",
                    payload={"type": "agentMessage", "content": f"第 {t_idx} 轮结论完成"},
                ),
                RunItemEvent(
                    event_id=f"{thread_id}:st:{t_idx}",
                    thread_id=thread_id,
                    turn_id=tid,
                    run_id=f"run-{t_idx}",
                    item_id=f"{tid}:status",
                    kind="status",
                    status="completed",
                    payload={"type": "turn", "status": "completed", "duration_ms": 100 + t_idx},
                ),
            ],
        )


def _norm_snap(snap: dict[str, Any]) -> dict[str, Any]:
    out = json.loads(json.dumps(snap, ensure_ascii=False))
    for turns_map in (out.get("turns"), (out.get("core") or {}).get("turns")):
        if isinstance(turns_map, dict):
            for t in turns_map.values():
                if isinstance(t, dict) and t.get("created_at"):
                    t["created_at"] = "<ts>"
    return out


@pytest.mark.asyncio
async def test_snapshot_splits_artifacts_and_turns_out_of_hot_row_with_lossless_parity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    py_path = tmp_path / "py_split.db"
    rs_path = tmp_path / "rs_split.db"

    async def _run(db_path: Path, *, disable_rust: bool) -> dict[str, Any]:
        if disable_rust:
            monkeypatch.setenv("LAMTOOLS_DISABLE_RUST_DB", "1")
        else:
            monkeypatch.delenv("LAMTOOLS_DISABLE_RUST_DB", raising=False)
        db = await open_core_app_db(db_path, workspace_id="ws-split")
        sessions = CoreDbSessionStore(lambda: db)
        context = CoreLiveContext(
            session_factory=db.session_factory,
            persistence=db.persistence,
            operations=OperationCatalog(),
            runtime_task_registry=RuntimeTaskRegistry(),
        )
        context.host.session_store = sessions
        try:
            await _seed_heavy_artifacts_and_turns_thread(db, "t-split")

            async with db.session_factory() as session:
                full_loaded = await db.persistence.load(session, "t-split")
                meta_loaded = await db.persistence.load_metadata(session, "t-split")

            read_res = await handle_thread_read_operation(
                request_id=1,
                params={"thread_id": "t-split", "page_bytes": 131_072},
                context=context,
            )
            hist_res = await handle_thread_history_operation(
                request_id=2,
                params={"thread_id": "t-split", "before_item_id": "turn-4:status", "page_bytes": 131_072},
                context=context,
            )
            return {
                "full": _norm_snap(full_loaded),
                "meta_turns": _norm_snap({"turns": meta_loaded.get("turns"), "core": {"turns": (meta_loaded.get("core") or {}).get("turns")}}),
                "read": _norm_snap(read_res.response["result"]["snapshot"]),
                "history": _norm_snap(hist_res.response["result"]["snapshot_page"]),
            }
        finally:
            context.runtime_task_registry.clear()
            await wait_live_background_tasks()
            await db.close()

    py_out = await _run(py_path, disable_rust=True)
    rs_out = await _run(rs_path, disable_rust=False)

    # 1. Stored core_thread_snapshots.snapshot_json on Rust DB must NOT carry bulky inline artifacts/turns!
    conn = sqlite3.connect(str(rs_path))
    try:
        raw_snap = conn.execute(
            "SELECT snapshot_json FROM core_thread_snapshots WHERE thread_id = 't-split'"
        ).fetchone()[0]
        sj = json.loads(raw_snap)
        art_count = conn.execute(
            "SELECT count(*) FROM core_thread_snapshot_artifacts WHERE thread_id = 't-split'"
        ).fetchone()[0]
        turn_count = conn.execute(
            "SELECT count(*) FROM core_thread_snapshot_turns WHERE thread_id = 't-split'"
        ).fetchone()[0]
    finally:
        conn.close()

    assert sj["core"]["artifacts"] == {}
    assert sj["core"]["turns"] == {}
    assert sj["turns"] == {}
    assert len(raw_snap) < 4096
    assert art_count == 4
    assert turn_count == 4

    # 2. Lossless hydration parity across load(), load_metadata(), thread.read, and thread.history
    assert rs_out["full"] == py_out["full"]
    assert rs_out["meta_turns"] == py_out["meta_turns"]
    assert rs_out["read"] == py_out["read"]
    assert rs_out["history"] == py_out["history"]
    assert len(rs_out["full"]["core"]["artifacts"]) == 4

    # 3. Legacy unmigrated inline snapshot row shrinks automatically on the first Rust write and cleans up on delete
    monkeypatch.delenv("LAMTOOLS_DISABLE_RUST_DB", raising=False)
    legacy_path = tmp_path / "legacy_inline.db"
    monkeypatch.setenv("LAMTOOLS_DISABLE_RUST_DB", "1")
    py_legacy = await open_core_app_db(legacy_path, workspace_id="ws-leg-split")
    try:
        await _seed_heavy_artifacts_and_turns_thread(py_legacy, "t-leg")
    finally:
        await wait_live_background_tasks()
        await py_legacy.close()

    monkeypatch.delenv("LAMTOOLS_DISABLE_RUST_DB", raising=False)
    rs_migrated = await open_core_app_db(legacy_path, workspace_id="ws-leg-split")
    try:
        await rs_migrated.persistence.append_batch_atomic(
            run_item_events=[
                RunItemEvent(
                    event_id="mig-ev-1",
                    thread_id="t-leg",
                    turn_id="turn-4",
                    run_id="run-4",
                    item_id="msg-4",
                    kind="message",
                    status="completed",
                    payload={"type": "agentMessage", "delta": " 追加一小句"},
                )
            ]
        )
        conn = sqlite3.connect(str(legacy_path))
        try:
            migrated_raw = conn.execute(
                "SELECT snapshot_json FROM core_thread_snapshots WHERE thread_id = 't-leg'"
            ).fetchone()[0]
            mig_sj = json.loads(migrated_raw)
            mig_art = conn.execute(
                "SELECT count(*) FROM core_thread_snapshot_artifacts WHERE thread_id = 't-leg'"
            ).fetchone()[0]
            mig_turn = conn.execute(
                "SELECT count(*) FROM core_thread_snapshot_turns WHERE thread_id = 't-leg'"
            ).fetchone()[0]
        finally:
            conn.close()
        assert mig_sj["core"]["artifacts"] == {}
        assert mig_sj["core"]["turns"] == {}
        assert mig_sj["turns"] == {}
        assert mig_art == 4
        assert mig_turn == 4

        async with rs_migrated.session_factory() as session:
            reloaded = await rs_migrated.persistence.load(session, "t-leg")
        assert len(reloaded["core"]["artifacts"]) == 4
        assert len(reloaded["core"]["turns"]) == 4
        assert "追加一小句" in reloaded["core"]["items"]["msg-4"]["content"]

        # Python fallback reading the migrated DB must also hydrate artifacts/turns losslessly!
        monkeypatch.setenv("LAMTOOLS_DISABLE_RUST_DB", "1")
        async with rs_migrated.session_factory() as session:
            py_reloaded = await rs_migrated.persistence.load(session, "t-leg")
        assert _norm_snap(py_reloaded) == _norm_snap(reloaded)

        # Deleting the session removes all split rows cleanly
        monkeypatch.delenv("LAMTOOLS_DISABLE_RUST_DB", raising=False)
        sessions = CoreDbSessionStore(lambda: rs_migrated)
        await sessions.delete("t-leg")
        conn = sqlite3.connect(str(legacy_path))
        try:
            rem_art = conn.execute(
                "SELECT count(*) FROM core_thread_snapshot_artifacts WHERE thread_id = 't-leg'"
            ).fetchone()[0]
            rem_turn = conn.execute(
                "SELECT count(*) FROM core_thread_snapshot_turns WHERE thread_id = 't-leg'"
            ).fetchone()[0]
        finally:
            conn.close()
        assert rem_art == 0
        assert rem_turn == 0
    finally:
        await wait_live_background_tasks()
        await rs_migrated.close()


@pytest.mark.asyncio
async def test_rust_engine_cache_eviction_bounds_metadata_outlines_and_summaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LAMTOOLS_DISABLE_RUST_DB", raising=False)
    db = await open_core_app_db(tmp_path / "cache_bounds.db", workspace_id="ws-cache")
    sessions = CoreDbSessionStore(lambda: db)
    context = CoreLiveContext(
        session_factory=db.session_factory,
        persistence=db.persistence,
        operations=OperationCatalog(),
        runtime_task_registry=RuntimeTaskRegistry(),
    )
    context.host.session_store = sessions
    try:
        for idx in range(20):
            tid = f"t-cap-{idx}"
            await sessions.create(SessionRecord(id=tid, member_id="core", title=f"Thread {idx}", status="idle"))
            await db.persistence.append_batch_atomic(
                app_events=[
                    AppEventInput(
                        event_id=f"{tid}:acc",
                        thread_id=tid,
                        method="turn/accepted",
                        turn_id="turn-1",
                        item_id="turn-1:user",
                        payload={
                            "type": "turn",
                            "turn_id": "turn-1",
                            "user_item_id": "turn-1:user",
                            "input": [{"type": "text", "text": f"hi {idx}"}],
                        },
                    )
                ],
                run_item_events=[
                    RunItemEvent(
                        event_id=f"{tid}:msg",
                        thread_id=tid,
                        turn_id="turn-1",
                        run_id="run-1",
                        item_id="msg-1",
                        kind="message",
                        status="completed",
                        payload={"type": "agentMessage", "content": f"reply {idx}"},
                    )
                ],
            )
            await handle_thread_read_operation(
                request_id=idx + 1,
                params={"thread_id": tid},
                context=context,
            )
            await handle_thread_outline_operation(
                request_id=100 + idx,
                params={"thread_id": tid, "char_limit": 200},
                context=context,
            )

        stats = db.rust_db.stats()
        assert int(stats["metadata_cache_entries"]) <= 8
        assert int(stats["outline_cache_entries"]) <= 64
        assert int(stats["summary_cache_entries"]) <= 512
    finally:
        context.runtime_task_registry.clear()
        await wait_live_background_tasks()
        await db.close()
