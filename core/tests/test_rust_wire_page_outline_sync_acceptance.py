"""Phase 4 acceptance tests: Rust wire-page slicing, thread outline extraction, and incremental sync journal.

user:“继续”+(第 4 期先行验收测试：覆盖分页按字节裁剪+大图引用、大纲直出与增量同步日志通道的 Rust 等价性与性能表现)。
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import pytest

from lamtools_core.app.core_db import open_core_app_db
from lamtools_core.app.core_session_store import CoreDbSessionStore
from lamtools_core.app.event_store import AppEventInput
from lamtools_core.app.live.threads import (
    handle_sync_start_operation,
    handle_thread_history_operation,
    handle_thread_outline_operation,
    handle_thread_page_around_operation,
    handle_thread_read_operation,
    handle_thread_resume_operation,
)
from lamtools_core.app.live_operations import CoreLiveContext, wait_live_background_tasks
from lamtools_core.app.operation_catalog import OperationCatalog
from lamtools_core.app.sync_store import CoreSyncJournal
from lamtools_core.event import RunItemEvent
from lamtools_core.runtime import RuntimeTaskRegistry
from lamtools_core.session import SessionRecord


async def _seed_rich_thread(db: Any, thread_id: str) -> None:
    await db.persistence.append_batch_atomic(
        app_events=[
            AppEventInput(
                event_id=f"{thread_id}:start",
                thread_id=thread_id,
                method="thread/started",
                payload={"type": "thread", "status": "idle", "member_id": "core", "title": "Rich Chat"},
            ),
        ]
    )
    # 6 completed turns + 1 active turn with CJK text + oversized inline image + sub-agent + protocol envelope
    for t_idx in range(1, 7):
        tid = f"turn-{t_idx}"
        turn_app_events = [
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
                    "input": [{"type": "text", "text": f"第{t_idx}轮问题：中文多字节测试 " + ("内容" * 120)}],
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
                    "content": [{"type": "text", "text": f"第{t_idx}轮问题：中文多字节测试 " + ("内容" * 120)}],
                },
            ),
        ]
        turn_run_items = [
            RunItemEvent(
                event_id=f"{thread_id}:a:{t_idx}",
                thread_id=thread_id,
                turn_id=tid,
                run_id=tid,
                item_id=f"msg-{t_idx}",
                kind="assistant_delta",
                status="completed",
                payload={"type": "agentMessage", "delta": f"第{t_idx}轮回复：" + ("详情" * 800)},
            ),
            RunItemEvent(
                event_id=f"{thread_id}:child:{t_idx}",
                thread_id=thread_id,
                turn_id=tid,
                run_id=tid,
                item_id=f"child-{t_idx}",
                kind="assistant_delta",
                status="completed",
                payload={
                    "type": "agentMessage",
                    "delta": "SUBAGENT INTERNAL REPLY",
                    "sub_agent": {"name": "helper"},
                },
            ),
            RunItemEvent(
                event_id=f"{thread_id}:proto:{t_idx}",
                thread_id=thread_id,
                turn_id=tid,
                run_id=tid,
                item_id=f"proto-{t_idx}",
                kind="assistant_delta",
                status="completed",
                payload={
                    "type": "agentMessage",
                    "delta": '{"jsonrpc":"2.0","method":"ping","params":{}}',
                },
            ),
        ]
        if t_idx == 4:
            big_b64 = base64.b64encode(b"IMG" * 100_000).decode("ascii")
            turn_run_items.append(
                RunItemEvent(
                    event_id=f"{thread_id}:bigimg",
                    thread_id=thread_id,
                    turn_id=tid,
                    run_id=tid,
                    item_id="item-bigimg",
                    kind="tool_result",
                    status="completed",
                    payload={"type": "toolResult", "content": "image ready"},
                    artifacts=[
                        {
                            "artifact_id": "art-big",
                            "kind": "image",
                            "mime_type": "image/png",
                            "metadata": {"image_data_url": f"data:image/png;base64,{big_b64}"},
                        }
                    ],
                )
            )
        turn_run_items.append(
            RunItemEvent(
                event_id=f"{thread_id}:done:{t_idx}",
                thread_id=thread_id,
                turn_id=tid,
                run_id=tid,
                item_id=f"st-{t_idx}",
                kind="status",
                status="completed",
                payload={"type": "turn", "status": "completed"},
            )
        )
        await db.persistence.append_batch_atomic(app_events=turn_app_events, run_item_events=turn_run_items)

    await db.persistence.append_batch_atomic(
        app_events=[
            AppEventInput(
                event_id=f"{thread_id}:acc:7",
                thread_id=thread_id,
                method="turn/accepted",
                turn_id="turn-7",
                item_id="user-7",
                payload={
                    "type": "turn",
                    "turn_id": "turn-7",
                    "user_item_id": "user-7",
                    "status": "running",
                    "input": [{"type": "text", "text": "正在运行的第7轮"}],
                },
            ),
            AppEventInput(
                event_id=f"{thread_id}:usr:7",
                thread_id=thread_id,
                method="item/started",
                turn_id="turn-7",
                item_id="user-7",
                payload={
                    "type": "userMessage",
                    "role": "user",
                    "content": [{"type": "text", "text": "正在运行的第7轮"}],
                },
            ),
        ],
        run_item_events=[
            RunItemEvent(
                event_id=f"{thread_id}:a:7",
                thread_id=thread_id,
                turn_id="turn-7",
                run_id="turn-7",
                item_id="msg-7",
                kind="assistant_delta",
                status="running",
                payload={"type": "agentMessage", "delta": "第7轮输出中..."},
            )
        ],
    )


@pytest.mark.asyncio
async def test_wire_page_and_page_around_rust_parity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _run(db_path: Path, *, disable_rust: bool) -> dict[str, Any]:
        if disable_rust:
            monkeypatch.setenv("LAMTOOLS_DISABLE_RUST_DB", "1")
        else:
            monkeypatch.delenv("LAMTOOLS_DISABLE_RUST_DB", raising=False)
        db = await open_core_app_db(db_path, workspace_id="ws-p4")
        sessions = CoreDbSessionStore(lambda: db)
        context = CoreLiveContext(
            session_factory=db.session_factory,
            persistence=db.persistence,
            operations=OperationCatalog(),
            runtime_task_registry=RuntimeTaskRegistry(),
        )
        context.host.session_store = sessions
        try:
            await _seed_rich_thread(db, "t-wire")
            resume_out = await handle_thread_resume_operation(
                request_id=1,
                params={"thread_id": "t-wire", "page_bytes": 65536, "turn_limit": 2},
                context=context,
            )
            read_out = await handle_thread_read_operation(
                request_id=2,
                params={"thread_id": "t-wire", "page_bytes": 65536, "turn_limit": 2},
                context=context,
            )
            # Walk backward through history pages using cursors
            pages: list[dict[str, Any]] = []
            cursor_id = read_out.response["result"]["snapshot"]["history_page"]["next_before_item_id"]
            cursor_seq = read_out.response["result"]["snapshot"]["history_page"]["next_before_seq"]
            while cursor_id or cursor_seq:
                h_out = await handle_thread_history_operation(
                    request_id=10 + len(pages),
                    params={
                        "thread_id": "t-wire",
                        "before_item_id": cursor_id,
                        "before_seq": cursor_seq,
                        "page_bytes": 65536,
                        "turn_limit": 2,
                    },
                    context=context,
                )
                sp = h_out.response["result"]["snapshot_page"]
                pages.append(sp)
                hp = sp["history_page"]
                if not hp["has_more"]:
                    break
                cursor_id = hp["next_before_item_id"]
                cursor_seq = hp["next_before_seq"]

            around_hit = await handle_thread_page_around_operation(
                request_id=20,
                params={"thread_id": "t-wire", "item_id": "item-bigimg", "page_bytes": 65536, "turn_limit": 3},
                context=context,
            )
            around_miss = await handle_thread_page_around_operation(
                request_id=21,
                params={"thread_id": "t-wire", "item_id": "missing-item", "page_bytes": 65536},
                context=context,
            )
            # Strip non-deterministic created_at/updated_at in turn metadata for pure parity
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

            return {
                "resume_snap": _norm_snap(resume_out.response["result"]["snapshot"]),
                "read_snap": _norm_snap(read_out.response["result"]["snapshot"]),
                "history_pages": [_norm_snap(p) for p in pages],
                "around_hit": {
                    **around_hit.response["result"],
                    "snapshot_page": _norm_snap(around_hit.response["result"]["snapshot_page"]),
                },
                "around_miss": around_miss.response["result"],
                "big_item_ref": around_hit.response["result"]["snapshot_page"]["core"]["items"]["item-bigimg"]["artifacts"][0],
            }
        finally:
            context.runtime_task_registry.clear()
            await wait_live_background_tasks()
            await db.close()

    py_res = await _run(tmp_path / "py_wire.db", disable_rust=True)
    rs_res = await _run(tmp_path / "rs_wire.db", disable_rust=False)
    assert rs_res["big_item_ref"]["availability"] == "reference"
    assert rs_res["around_miss"]["found"] is False
    assert len(rs_res["history_pages"]) >= 1
    assert rs_res == py_res


@pytest.mark.asyncio
async def test_thread_outline_rust_parity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _run(db_path: Path, *, disable_rust: bool) -> dict[str, Any]:
        if disable_rust:
            monkeypatch.setenv("LAMTOOLS_DISABLE_RUST_DB", "1")
        else:
            monkeypatch.delenv("LAMTOOLS_DISABLE_RUST_DB", raising=False)
        db = await open_core_app_db(db_path, workspace_id="ws-ol")
        sessions = CoreDbSessionStore(lambda: db)
        context = CoreLiveContext(
            session_factory=db.session_factory,
            persistence=db.persistence,
            operations=OperationCatalog(),
            runtime_task_registry=RuntimeTaskRegistry(),
        )
        context.host.session_store = sessions
        try:
            await _seed_rich_thread(db, "t-outline")
            out_default = await handle_thread_outline_operation(
                request_id=1,
                params={"thread_id": "t-outline"},
                context=context,
            )
            out_short = await handle_thread_outline_operation(
                request_id=2,
                params={"thread_id": "t-outline", "char_limit": 24},
                context=context,
            )
            def _norm_outline(res: dict[str, Any]) -> dict[str, Any]:
                return {
                    **res,
                    "items": [{**it, "timestamp": "<ts>" if it.get("timestamp") else None} for it in res["items"]],
                }
            return {
                "default": _norm_outline(out_default.response["result"]),
                "short": _norm_outline(out_short.response["result"]),
            }
        finally:
            context.runtime_task_registry.clear()
            await wait_live_background_tasks()
            await db.close()

    py_ol = await _run(tmp_path / "py_ol.db", disable_rust=True)
    rs_ol = await _run(tmp_path / "rs_ol.db", disable_rust=False)
    assert len(rs_ol["default"]["items"]) == 7
    assert "SUBAGENT" not in rs_ol["default"]["items"][0]["response_excerpt"]
    assert "jsonrpc" not in rs_ol["default"]["items"][0]["response_excerpt"]
    assert len(rs_ol["short"]["items"][0]["response_excerpt"]) == 24
    assert rs_ol == py_ol


@pytest.mark.asyncio
async def test_sync_journal_full_rust_parity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _run(db_path: Path, *, disable_rust: bool) -> dict[str, Any]:
        if disable_rust:
            monkeypatch.setenv("LAMTOOLS_DISABLE_RUST_DB", "1")
        else:
            monkeypatch.delenv("LAMTOOLS_DISABLE_RUST_DB", raising=False)
        db = await open_core_app_db(db_path, workspace_id="ws-sync")
        sessions = CoreDbSessionStore(lambda: db)
        journal = CoreSyncJournal(
            db.session_factory,
            db.persistence.write_coordinator,
            workspace_id="ws-sync",
        )
        sessions.set_sync_journal(journal)
        context = CoreLiveContext(
            session_factory=db.session_factory,
            persistence=db.persistence,
            operations=OperationCatalog(),
            runtime_task_registry=RuntimeTaskRegistry(),
        )
        context.host.session_store = sessions
        context.host.sync_journal = journal
        try:
            await sessions.create(SessionRecord(id="s-1", member_id="core", title="One", status="idle"))
            boot = await handle_sync_start_operation(
                request_id=1, params={"cursor": None}, context=context
            )
            cursor_0 = boot.response["result"]["cursor"]

            await sessions.patch("s-1", title="One Renamed")
            await _seed_rich_thread(db, "s-1")

            delta = await handle_sync_start_operation(
                request_id=2, params={"cursor": cursor_0, "limit": 50}, context=context
            )
            changes = delta.response["result"]["changes"]
            last_change_id = changes[-1]["change_id"]
            full_change = await journal.get_change(last_change_id)
            hdr_change = await journal.get_change_header(last_change_id)

            pruned = await journal.prune(keep=2)
            expired = await handle_sync_start_operation(
                request_id=3, params={"cursor": 0}, context=context
            )

            def _norm_change(c: dict[str, Any] | None) -> dict[str, Any] | None:
                if c is None:
                    return None
                return {**c, "change_id": "<cid>", "created_at": "<ts>"}

            def _norm_snap_threads(ts: list[dict[str, Any]]) -> list[dict[str, Any]]:
                return [
                    {**t, "created_at": "<ts>", "updated_at": "<ts>"}
                    for t in ts
                ]

            return {
                "boot_mode": boot.response["result"]["mode"],
                "boot_threads": _norm_snap_threads(boot.response["result"]["threads"]),
                "delta_mode": delta.response["result"]["mode"],
                "delta_count": len(changes),
                "delta_has_more": delta.response["result"]["has_more"],
                "hdr_has_payload": "payload" in (hdr_change or {}),
                "full_has_payload": "payload" in (full_change or {}),
                "full_event_method": ((full_change or {}).get("entity") or {}).get("event", {}).get("method"),
                "hdr_norm": _norm_change(hdr_change),
                "pruned_gt_zero": pruned > 0,
                "expired_ok": expired.response["result"]["ok"],
                "expired_err": expired.response["result"].get("error"),
            }
        finally:
            context.runtime_task_registry.clear()
            await wait_live_background_tasks()
            await db.close()

    py_sync = await _run(tmp_path / "py_sync.db", disable_rust=True)
    rs_sync = await _run(tmp_path / "rs_sync.db", disable_rust=False)
    assert rs_sync["hdr_has_payload"] is False
    assert rs_sync["full_has_payload"] is True
    assert rs_sync["pruned_gt_zero"] is True
    assert rs_sync["expired_err"] == "SYNC_CURSOR_EXPIRED"
    assert rs_sync == py_sync


@pytest.mark.asyncio
async def test_wire_page_preserves_system_message_turn_header_across_page_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """user:“查一下 constant 内会话为什么出现了：部分消息在最新消息的下方”
    +(systemMessage 触发的回合跨分页边界时，Python 与 Rust 分页都必须保留该回合的开场头条，防止前端将其当成无主条目甩到最新消息下方)。"""

    async def _run(db_path: Path, *, disable_rust: bool) -> dict[str, Any]:
        if disable_rust:
            monkeypatch.setenv("LAMTOOLS_DISABLE_RUST_DB", "1")
        else:
            monkeypatch.delenv("LAMTOOLS_DISABLE_RUST_DB", raising=False)
        db = await open_core_app_db(db_path, workspace_id="ws-sys-hdr")
        sessions = CoreDbSessionStore(lambda: db)
        context = CoreLiveContext(
            session_factory=db.session_factory,
            persistence=db.persistence,
            operations=OperationCatalog(),
            runtime_task_registry=RuntimeTaskRegistry(),
        )
        context.host.session_store = sessions
        try:
            await db.persistence.append_batch_atomic(
                app_events=[
                    AppEventInput(
                        event_id="sys-start",
                        thread_id="t-sys",
                        method="thread/started",
                        payload={"type": "thread", "status": "idle", "member_id": "core", "title": "Sys"},
                    ),
                    AppEventInput(
                        event_id="sys-t1-acc",
                        thread_id="t-sys",
                        method="turn/accepted",
                        turn_id="turn-sys",
                        item_id="turn-sys:user",
                        payload={
                            "type": "turn",
                            "turn_id": "turn-sys",
                            "user_item_id": "turn-sys:user",
                            "item_type": "systemMessage",
                            "input": [{"type": "text", "text": "- 子代理 worker 已完成"}],
                        },
                    ),
                    AppEventInput(
                        event_id="sys-t1-user",
                        thread_id="t-sys",
                        method="item/started",
                        turn_id="turn-sys",
                        item_id="turn-sys:user",
                        payload={
                            "type": "systemMessage",
                            "item_id": "turn-sys:user",
                            "turn_id": "turn-sys",
                            "content": [{"type": "text", "text": "- 子代理 worker 已完成"}],
                        },
                    ),
                ],
                run_item_events=[
                    RunItemEvent(
                        event_id="sys-r1",
                        thread_id="t-sys",
                        turn_id="turn-sys",
                        run_id="run-sys",
                        item_id="sys-big-1",
                        kind="message",
                        status="completed",
                        payload={"type": "agentMessage", "content": "历史分段一：" + ("A" * 20_000)},
                    ),
                    RunItemEvent(
                        event_id="sys-r2",
                        thread_id="t-sys",
                        turn_id="turn-sys",
                        run_id="run-sys",
                        item_id="sys-big-2",
                        kind="message",
                        status="completed",
                        payload={"type": "agentMessage", "content": "历史分段二：" + ("B" * 20_000)},
                    ),
                    RunItemEvent(
                        event_id="sys-done",
                        thread_id="t-sys",
                        turn_id="turn-sys",
                        run_id="run-sys",
                        item_id="turn-sys:status",
                        kind="status",
                        status="completed",
                        payload={"type": "turn", "status": "completed"},
                    ),
                ],
            )
            await db.persistence.append_batch_atomic(
                app_events=[
                    AppEventInput(
                        event_id="sys-t2-acc",
                        thread_id="t-sys",
                        method="turn/accepted",
                        turn_id="turn-latest",
                        item_id="turn-latest:user",
                        payload={
                            "type": "turn",
                            "turn_id": "turn-latest",
                            "user_item_id": "turn-latest:user",
                            "input": [{"type": "text", "text": "最新提问"}],
                        },
                    ),
                    AppEventInput(
                        event_id="sys-t2-user",
                        thread_id="t-sys",
                        method="item/started",
                        turn_id="turn-latest",
                        item_id="turn-latest:user",
                        payload={
                            "type": "userMessage",
                            "item_id": "turn-latest:user",
                            "turn_id": "turn-latest",
                            "content": [{"type": "text", "text": "最新提问"}],
                        },
                    ),
                ],
                run_item_events=[
                    RunItemEvent(
                        event_id="lat-r1",
                        thread_id="t-sys",
                        turn_id="turn-latest",
                        run_id="run-lat",
                        item_id="lat-msg",
                        kind="message",
                        status="completed",
                        payload={"type": "agentMessage", "content": "最新回复"},
                    ),
                    RunItemEvent(
                        event_id="lat-done",
                        thread_id="t-sys",
                        turn_id="turn-latest",
                        run_id="run-lat",
                        item_id="turn-latest:status",
                        kind="status",
                        status="completed",
                        payload={"type": "turn", "status": "completed"},
                    ),
                ],
            )
            read_res = await handle_thread_read_operation(
                request_id=1,
                params={"thread_id": "t-sys", "page_bytes": 65_536},
                context=context,
            )
            snap = read_res.response["result"]["snapshot"]
            return {
                "top_order": snap["item_order"],
                "core_order": snap["core"]["item_order"],
                "has_sys_header": "turn-sys:user" in snap["items"],
            }
        finally:
            context.runtime_task_registry.clear()
            await wait_live_background_tasks()
            await db.close()

    py_out = await _run(tmp_path / "py_sys.db", disable_rust=True)
    rs_out = await _run(tmp_path / "rs_sys.db", disable_rust=False)
    assert py_out["has_sys_header"] is True
    assert rs_out["has_sys_header"] is True
    assert rs_out == py_out
