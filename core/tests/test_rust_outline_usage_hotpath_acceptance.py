"""Acceptance tests for eliminating outline/history Python fallbacks and full-blob LIKE scans.

user:“规划并实现”+(消除老会话 usage hydration 回退、去掉大纲对 usage 的依赖、为快照条目补充类型索引并持久化增量大纲缓存)。
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
    handle_thread_page_around_operation,
    handle_thread_read_operation,
)
from lamtools_core.app.live_operations import CoreLiveContext, wait_live_background_tasks
from lamtools_core.app.operation_catalog import OperationCatalog
from lamtools_core.app.rust_db import get_rust_db
from lamtools_core.event import RunItemEvent
from lamtools_core.runtime import RuntimeTaskRegistry


async def _seed_thread_and_strip_usage_version(
    db: Any,
    *,
    db_path: Path,
    thread_id: str,
    turns: int = 4,
    tool_results_per_turn: int = 8,
    tool_blob_bytes: int = 24_000,
) -> None:
    await db.persistence.append_batch_atomic(
        app_events=[
            AppEventInput(
                event_id=f"{thread_id}:start",
                thread_id=thread_id,
                method="thread/started",
                payload={"type": "thread", "status": "idle", "member_id": "core", "title": "Legacy Usage Chat"},
            ),
        ]
    )
    filler = "X" * tool_blob_bytes
    for t_idx in range(1, turns + 1):
        tid = f"turn-{t_idx}"
        app_events = [
            AppEventInput(
                event_id=f"{thread_id}:acc:{t_idx}",
                thread_id=thread_id,
                method="turn/accepted",
                turn_id=tid,
                item_id=f"user-{t_idx}",
                payload={
                    "type": "turn",
                    "turn_id": tid,
                    "user_item_id": f"user-{t_idx}",
                    "input": [{"type": "text", "text": f"问题 {t_idx}：如何排查卡顿"}],
                },
            ),
            AppEventInput(
                event_id=f"{thread_id}:usr:{t_idx}",
                thread_id=thread_id,
                method="item/started",
                turn_id=tid,
                item_id=f"user-{t_idx}",
                payload={
                    "type": "userMessage",
                    "role": "user",
                    "content": [{"type": "text", "text": f"问题 {t_idx}：如何排查卡顿"}],
                },
            ),
        ]
        run_items = [
            RunItemEvent(
                event_id=f"{thread_id}:u1:{t_idx}",
                thread_id=thread_id,
                turn_id=tid,
                run_id=tid,
                item_id=f"usage-{t_idx}",
                kind="usage",
                status="completed",
                usage={"input_tokens": 100 * t_idx, "output_tokens": 25 * t_idx},
            ),
            RunItemEvent(
                event_id=f"{thread_id}:ccm:{t_idx}",
                thread_id=thread_id,
                turn_id=tid,
                run_id=tid,
                item_id=f"ccm-{t_idx}",
                parent_item_id=f"sub-{t_idx}",
                kind="usage",
                status="completed",
                payload={"replace": True},
                usage={"prompt_tokens": 300 + t_idx},
            ),
        ]
        for b_idx in range(tool_results_per_turn):
            run_items.append(
                RunItemEvent(
                    event_id=f"{thread_id}:tool:{t_idx}:{b_idx}",
                    thread_id=thread_id,
                    turn_id=tid,
                    run_id=tid,
                    item_id=f"tool-{t_idx}-{b_idx}",
                    kind="tool_result",
                    status="completed",
                    payload={"type": "toolResult", "content": f"tool-{b_idx}:{filler}"},
                )
            )
        run_items.extend([
            RunItemEvent(
                event_id=f"{thread_id}:ans:{t_idx}",
                thread_id=thread_id,
                turn_id=tid,
                run_id=tid,
                item_id=f"msg-{t_idx}",
                kind="assistant_delta",
                status="completed",
                payload={"type": "agentMessage", "delta": f"结论 {t_idx}：已优化核心路径"},
            ),
            RunItemEvent(
                event_id=f"{thread_id}:done:{t_idx}",
                thread_id=thread_id,
                turn_id=tid,
                run_id=tid,
                item_id=f"st-{t_idx}",
                kind="status",
                status="completed",
                payload={"type": "turn", "status": "completed"},
            ),
        ])
        await db.persistence.append_batch_atomic(app_events=app_events, run_item_events=run_items)

    # Simulate a legacy pre-history snapshot on disk: remove resource_usage_version and usage dicts
    # from snapshot_json, AND null out item_type so both legacy usage hydration and legacy NULL item_type
    # backfill paths are exercised on read.
    await db.close()
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT snapshot_json FROM core_thread_snapshots WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()
        assert row is not None
        snap = json.loads(row[0])
        snap["core"].pop("resource_usage_version", None)
        for turn in snap["core"].get("turns", {}).values():
            turn.pop("usage", None)
            turn.pop("usage_calls", None)
            turn.pop("child_context_metrics", None)
        for turn in snap.get("turns", {}).values():
            turn.pop("usage", None)
        conn.execute(
            "UPDATE core_thread_snapshots SET snapshot_json = ? WHERE thread_id = ?",
            (json.dumps(snap, ensure_ascii=False), thread_id),
        )
        cols = {
            r[1]
            for r in conn.execute("PRAGMA table_info(core_thread_snapshot_items)").fetchall()
        }
        if "item_type" in cols:
            conn.execute(
                "UPDATE core_thread_snapshot_items SET item_type = NULL WHERE thread_id = ?",
                (thread_id,),
            )
        conn.commit()
    finally:
        conn.close()


def _norm_snap(s: dict[str, Any]) -> dict[str, Any]:
    copy = {**s}
    for key in ("turns",):
        if isinstance(copy.get(key), dict):
            copy[key] = {
                k: {**v, "created_at": "<ts>"} if isinstance(v, dict) and "created_at" in v else v
                for k, v in copy[key].items()
            }
    if isinstance(copy.get("core"), dict) and isinstance(copy["core"].get("turns"), dict):
        copy["core"] = {
            **copy["core"],
            "turns": {
                k: {**v, "created_at": "<ts>"} if isinstance(v, dict) and "created_at" in v else v
                for k, v in copy["core"]["turns"].items()
            },
        }
    return copy


@pytest.mark.asyncio
async def test_legacy_thread_with_usage_stays_on_rust_for_outline_and_wire_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Seed identical legacy DBs for Python reference vs Rust native path
    py_path = tmp_path / "py_legacy.db"
    rs_path = tmp_path / "rs_legacy.db"

    for path in (py_path, rs_path):
        monkeypatch.delenv("LAMTOOLS_DISABLE_RUST_DB", raising=False)
        db = await open_core_app_db(path, workspace_id="ws-leg")
        try:
            await _seed_thread_and_strip_usage_version(db, db_path=path, thread_id="t-leg")
        finally:
            await wait_live_background_tasks()

    async def _exercise(path: Path, *, disable_rust: bool) -> dict[str, Any]:
        if disable_rust:
            monkeypatch.setenv("LAMTOOLS_DISABLE_RUST_DB", "1")
        else:
            monkeypatch.delenv("LAMTOOLS_DISABLE_RUST_DB", raising=False)
        db = await open_core_app_db(path, workspace_id="ws-leg")
        sessions = CoreDbSessionStore(lambda: db)
        context = CoreLiveContext(
            session_factory=db.session_factory,
            persistence=db.persistence,
            operations=OperationCatalog(),
            runtime_task_registry=RuntimeTaskRegistry(),
        )
        context.host.session_store = sessions
        try:
            rust_db = get_rust_db(db.session_factory)
            rust_wire_direct = None
            rust_outline_direct = None
            if rust_db is not None and rust_db.is_active:
                rust_wire_direct = await rust_db.call(
                    "load_wire_page",
                    {"thread_id": "t-leg", "turn_limit": 2, "byte_limit": 131_072},
                )
                rust_outline_direct = await rust_db.call(
                    "build_thread_outline",
                    {"thread_id": "t-leg", "char_limit": 200},
                )

            read_out = await handle_thread_read_operation(
                request_id=1,
                params={"thread_id": "t-leg", "turn_limit": 2, "page_bytes": 131_072},
                context=context,
            )
            hist_out = await handle_thread_history_operation(
                request_id=2,
                params={"thread_id": "t-leg", "before_item_id": "msg-3", "turn_limit": 2, "page_bytes": 131_072},
                context=context,
            )
            around_out = await handle_thread_page_around_operation(
                request_id=3,
                params={"thread_id": "t-leg", "item_id": "msg-2", "turn_limit": 2, "page_bytes": 131_072},
                context=context,
            )
            outline_out = await handle_thread_outline_operation(
                request_id=4,
                params={"thread_id": "t-leg", "char_limit": 200},
                context=context,
            )
            return {
                "rust_wire_needs_hydration": (rust_wire_direct or {}).get("needs_usage_hydration"),
                "rust_outline_needs_hydration": (rust_outline_direct or {}).get("needs_usage_hydration"),
                "read": _norm_snap(read_out.response["result"]["snapshot"]),
                "history": _norm_snap(hist_out.response["result"]["snapshot_page"]),
                "around": _norm_snap(around_out.response["result"]["snapshot_page"]),
                "outline": {
                    **outline_out.response["result"],
                    "items": [
                        {**it, "timestamp": "<ts>" if it.get("timestamp") else None}
                        for it in outline_out.response["result"]["items"]
                    ],
                },
            }
        finally:
            context.runtime_task_registry.clear()
            await wait_live_background_tasks()
            await db.close()

    py_res = await _exercise(py_path, disable_rust=True)
    rs_res = await _exercise(rs_path, disable_rust=False)

    # Critical assertion: legacy threads with usage events MUST NOT fall back to Python!
    assert rs_res["rust_wire_needs_hydration"] is False
    assert rs_res["rust_outline_needs_hydration"] is False
    assert rs_res["read"] == py_res["read"]
    assert rs_res["history"] == py_res["history"]
    assert rs_res["around"] == py_res["around"]
    assert rs_res["outline"] == py_res["outline"]
    # Usage must actually be hydrated on the returned snapshot
    assert rs_res["read"]["turns"]["turn-4"]["usage"]["input_tokens"] == 400
    assert rs_res["read"]["core"]["turns"]["turn-4"]["child_context_metrics"]["sub-4"]["prompt_tokens"] == 304


@pytest.mark.asyncio
async def test_outline_persists_cache_backfills_item_type_and_invalidates_on_append(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LAMTOOLS_DISABLE_RUST_DB", raising=False)
    db_path = tmp_path / "outline_cache.db"
    db = await open_core_app_db(db_path, workspace_id="ws-oc")
    try:
        await _seed_thread_and_strip_usage_version(
            db, db_path=db_path, thread_id="t-cache", turns=3, tool_results_per_turn=6, tool_blob_bytes=4_096
        )
    finally:
        await wait_live_background_tasks()

    db = await open_core_app_db(db_path, workspace_id="ws-oc")
    sessions = CoreDbSessionStore(lambda: db)
    context = CoreLiveContext(
        session_factory=db.session_factory,
        persistence=db.persistence,
        operations=OperationCatalog(),
        runtime_task_registry=RuntimeTaskRegistry(),
    )
    context.host.session_store = sessions
    try:
        # First cold outline: computes outline, persists core_thread_outlines, and backfills NULL item_type
        out1 = await handle_thread_outline_operation(
            request_id=1, params={"thread_id": "t-cache", "char_limit": 200}, context=context
        )
        items1 = out1.response["result"]["items"]
        assert len(items1) == 3
        assert items1[2]["response_excerpt"].startswith("结论 3：")

        conn = sqlite3.connect(str(db_path))
        try:
            cached_rows = conn.execute(
                "SELECT char_limit, revision, snapshot_seq FROM core_thread_outlines WHERE thread_id = ?",
                ("t-cache",),
            ).fetchall()
            null_types = conn.execute(
                "SELECT COUNT(*) FROM core_thread_snapshot_items WHERE thread_id = ? AND item_type IS NULL",
                ("t-cache",),
            ).fetchone()[0]
            agent_types = conn.execute(
                "SELECT COUNT(*) FROM core_thread_snapshot_items WHERE thread_id = ? AND item_type = 'agentMessage'",
                ("t-cache",),
            ).fetchone()[0]
        finally:
            conn.close()
        assert len(cached_rows) == 1
        assert cached_rows[0][0] == 200
        assert null_types == 0
        assert agent_types == 3

        # Reopen DB cleanly: persistent SQLite outline cache survives restart
        await wait_live_background_tasks()
        await db.close()
        db = await open_core_app_db(db_path, workspace_id="ws-oc")
        sessions = CoreDbSessionStore(lambda: db)
        context = CoreLiveContext(
            session_factory=db.session_factory,
            persistence=db.persistence,
            operations=OperationCatalog(),
            runtime_task_registry=RuntimeTaskRegistry(),
        )
        context.host.session_store = sessions

        out2 = await handle_thread_outline_operation(
            request_id=2, params={"thread_id": "t-cache", "char_limit": 200}, context=context
        )
        assert out2.response["result"] == out1.response["result"]

        # Append turn-4: both item_type for new rows and outline cache invalidation must work cleanly
        await db.persistence.append_batch_atomic(
            app_events=[
                AppEventInput(
                    event_id="t-cache:usr:4",
                    thread_id="t-cache",
                    method="item/started",
                    turn_id="turn-4",
                    item_id="user-4",
                    payload={"type": "userMessage", "role": "user", "content": [{"type": "text", "text": "第四问"}]},
                )
            ],
            run_item_events=[
                RunItemEvent(
                    event_id="t-cache:ans:4",
                    thread_id="t-cache",
                    turn_id="turn-4",
                    run_id="turn-4",
                    item_id="msg-4",
                    kind="assistant_delta",
                    status="completed",
                    payload={"type": "agentMessage", "delta": "第四答：刷新成功"},
                )
            ],
        )
        out3 = await handle_thread_outline_operation(
            request_id=3, params={"thread_id": "t-cache", "char_limit": 200}, context=context
        )
        items3 = out3.response["result"]["items"]
        assert len(items3) == 4
        assert items3[3]["response_excerpt"] == "第四答：刷新成功"

        conn = sqlite3.connect(str(db_path))
        try:
            new_row_type = conn.execute(
                "SELECT item_type FROM core_thread_snapshot_items WHERE thread_id = ? AND item_id = ?",
                ("t-cache", "msg-4"),
            ).fetchone()
        finally:
            conn.close()
        assert new_row_type is not None and new_row_type[0] == "agentMessage"
    finally:
        context.runtime_task_registry.clear()
        await wait_live_background_tasks()
        await db.close()
