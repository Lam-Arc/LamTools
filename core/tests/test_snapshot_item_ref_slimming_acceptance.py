"""Acceptance tests for Step 2 snapshot-item reference slimming and single-write sync journal.

user:“继续”+(核心快照条目超大正文改为轻量化事件引用落盘、读取与二次增量投影透明批量回填，大幅削减机械盘写放大并保持 100% 数据等价)。
"""
from __future__ import annotations

import base64
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
from lamtools_core.event import RunItemEvent
from lamtools_core.runtime import RuntimeTaskRegistry


async def _seed_bulky_and_incremental_thread(db: Any, thread_id: str) -> None:
    await db.persistence.append_batch_atomic(
        app_events=[
            AppEventInput(
                event_id=f"{thread_id}:start",
                thread_id=thread_id,
                method="thread/started",
                payload={"type": "thread", "status": "idle", "member_id": "core", "title": "Slim Ref Chat"},
            )
        ]
    )
    large_tool_text = "RESULT_BLOCK_" * 600  # ~7.8 KB (> 1 KB slimming threshold)
    img_b64 = base64.b64encode(b"PNGDATA" * 60_000).decode("ascii")

    # Turn 1: streamed multi-delta agentMessage + bulky tool_result + inline image artifact + terminal status
    await db.persistence.append_batch_atomic(
        app_events=[
            AppEventInput(
                event_id=f"{thread_id}:u1",
                thread_id=thread_id,
                method="item/started",
                turn_id="turn-1",
                item_id="user-1",
                payload={"type": "userMessage", "role": "user", "content": [{"type": "text", "text": "请检查磁盘并汇总"}]},
            )
        ],
        run_item_events=[
            RunItemEvent(
                event_id=f"{thread_id}:a1:1",
                thread_id=thread_id,
                turn_id="turn-1",
                run_id="turn-1",
                item_id="msg-1",
                kind="assistant_delta",
                status="running",
                payload={"type": "agentMessage", "delta": "第一段说明：" + ("详细内容_" * 200)},
            ),
            RunItemEvent(
                event_id=f"{thread_id}:tool:1",
                thread_id=thread_id,
                turn_id="turn-1",
                run_id="turn-1",
                item_id="tool-1",
                kind="tool_result",
                status="completed",
                payload={"type": "toolResult", "content": large_tool_text},
                artifacts=[
                    {
                        "artifact_id": "art-1",
                        "kind": "image",
                        "mime_type": "image/png",
                        "metadata": {"image_data_url": f"data:image/png;base64,{img_b64}"},
                    }
                ],
            ),
        ],
    )

    # Incremental append to already-slimmed item msg-1 + close turn-1 via status event
    await db.persistence.append_batch_atomic(
        run_item_events=[
            RunItemEvent(
                event_id=f"{thread_id}:a1:2",
                thread_id=thread_id,
                turn_id="turn-1",
                run_id="turn-1",
                item_id="msg-1",
                kind="assistant_delta",
                status="completed",
                payload={"type": "agentMessage", "delta": "；第二段追加：" + ("结论_" * 120)},
            ),
            RunItemEvent(
                event_id=f"{thread_id}:st1",
                thread_id=thread_id,
                turn_id="turn-1",
                run_id="turn-1",
                item_id="st-1",
                kind="status",
                status="completed",
                payload={"type": "turn", "status": "completed"},
            ),
        ]
    )


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
async def test_snapshot_items_store_lightweight_refs_and_preserve_lossless_parity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    py_path = tmp_path / "py_slim.db"
    rs_path = tmp_path / "rs_slim.db"

    async def _run(db_path: Path, *, disable_rust: bool) -> dict[str, Any]:
        if disable_rust:
            monkeypatch.setenv("LAMTOOLS_DISABLE_RUST_DB", "1")
        else:
            monkeypatch.delenv("LAMTOOLS_DISABLE_RUST_DB", raising=False)
        db = await open_core_app_db(db_path, workspace_id="ws-slim")
        sessions = CoreDbSessionStore(lambda: db)
        context = CoreLiveContext(
            session_factory=db.session_factory,
            persistence=db.persistence,
            operations=OperationCatalog(),
            runtime_task_registry=RuntimeTaskRegistry(),
        )
        context.host.session_store = sessions
        try:
            await _seed_bulky_and_incremental_thread(db, "t-slim")

            async with db.session_factory() as session:
                full_loaded = await db.persistence.load(session, "t-slim")

            read_res = await handle_thread_read_operation(
                request_id=1,
                params={"thread_id": "t-slim", "page_bytes": 131_072},
                context=context,
            )
            hist_res = await handle_thread_history_operation(
                request_id=2,
                params={"thread_id": "t-slim", "before_item_id": "tool-1", "page_bytes": 131_072},
                context=context,
            )
            around_res = await handle_thread_page_around_operation(
                request_id=3,
                params={"thread_id": "t-slim", "item_id": "msg-1", "page_bytes": 131_072},
                context=context,
            )
            outline_res = await handle_thread_outline_operation(
                request_id=4,
                params={"thread_id": "t-slim", "char_limit": 240},
                context=context,
            )
            return {
                "full": _norm_snap(full_loaded),
                "read": _norm_snap(read_res.response["result"]["snapshot"]),
                "history": _norm_snap(hist_res.response["result"]["snapshot_page"]),
                "around": _norm_snap(around_res.response["result"]["snapshot_page"]),
                "outline": {
                    **outline_res.response["result"],
                    "items": [
                        {**it, "timestamp": "<ts>" if it.get("timestamp") else None}
                        for it in outline_res.response["result"]["items"]
                    ],
                },
            }
        finally:
            context.runtime_task_registry.clear()
            await wait_live_background_tasks()
            await db.close()

    py_out = await _run(py_path, disable_rust=True)
    rs_out = await _run(rs_path, disable_rust=False)

    # 1. Stored rows in core_thread_snapshot_items on Rust DB must be slimmed refs (< 1 KB each)
    conn = sqlite3.connect(str(rs_path))
    try:
        rows = conn.execute(
            "SELECT item_id, item_json, length(item_json) FROM core_thread_snapshot_items WHERE thread_id = 't-slim'"
        ).fetchall()
    finally:
        conn.close()
    by_id = {iid: (json.loads(raw), sz) for iid, raw, sz in rows}
    assert "_body_ref" in by_id["msg-1"][0]
    assert "_body_ref" in by_id["tool-1"][0]
    assert by_id["msg-1"][1] < 600
    assert by_id["tool-1"][1] < 600

    # 2. Lossless hydration parity across full load, wire read/history/pageAround, and outline
    assert rs_out["full"] == py_out["full"]
    assert rs_out["read"] == py_out["read"]
    assert rs_out["history"] == py_out["history"]
    assert rs_out["around"] == py_out["around"]
    assert rs_out["outline"] == py_out["outline"]
    assert "第二段追加：" in rs_out["full"]["core"]["items"]["msg-1"]["content"]
    assert rs_out["read"]["core"]["items"]["tool-1"]["artifacts"][0]["availability"] == "reference"

    # 3. Even if Rust DB is disabled later on the slimmed DB, Python fallback hydrates cleanly!
    monkeypatch.setenv("LAMTOOLS_DISABLE_RUST_DB", "1")
    db_py_read = await open_core_app_db(rs_path, workspace_id="ws-slim")
    try:
        async with db_py_read.session_factory() as session:
            fallback_loaded = await db_py_read.persistence.load(session, "t-slim")
        assert _norm_snap(fallback_loaded) == py_out["full"]
    finally:
        await db_py_read.close()
