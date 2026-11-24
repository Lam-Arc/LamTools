"""user:“修吧 让用户更易用”+(暂停后回退不能再留下幽灵暂停回合)。

回退会把暂停回合从消息条目和 snapshot_json 里删掉，但分表
``core_thread_snapshot_turns`` 仍留着那一行。读取元数据时这一行又会被合并
回来，服务端便认为会话还处于暂停：用户每次发送都得到
``SESSION_PAUSED``（界面上的“有会话处于暂停”），而界面又没有可继续的回合。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from lamtools_core.app import AppEventInput, open_core_app_db
from lamtools_core.app.live.terminal_state import _paused_turn_id
from lamtools_core.checkpoint import CoreCheckpointConversationBackend
from lamtools_core.event import RunItemEvent


async def _seed_paused_turn(db, thread_id: str, turn_id: str) -> None:
    await db.persistence.append_batch_atomic(
        app_events=[
            AppEventInput(
                event_id=f"{thread_id}:{turn_id}:accepted",
                thread_id=thread_id,
                method="turn/accepted",
                turn_id=turn_id,
                item_id=f"{turn_id}:user",
                payload={
                    "type": "turn",
                    "turn_id": turn_id,
                    "user_item_id": f"{turn_id}:user",
                    "input": [{"type": "text", "text": f"问题 {turn_id}"}],
                },
            ),
            AppEventInput(
                event_id=f"{thread_id}:{turn_id}:user",
                thread_id=thread_id,
                method="item/started",
                turn_id=turn_id,
                item_id=f"{turn_id}:user",
                payload={
                    "type": "userMessage",
                    "item_id": f"{turn_id}:user",
                    "turn_id": turn_id,
                    "content": [{"type": "text", "text": f"问题 {turn_id}"}],
                },
            ),
        ],
        run_item_events=[
            RunItemEvent(
                event_id=f"{thread_id}:{turn_id}:message",
                thread_id=thread_id,
                turn_id=turn_id,
                run_id=f"run-{turn_id}",
                item_id=f"{turn_id}:message",
                kind="message",
                status="completed",
                payload={"type": "agentMessage", "content": f"回答 {turn_id}"},
            ),
            RunItemEvent(
                event_id=f"{thread_id}:{turn_id}:status",
                thread_id=thread_id,
                turn_id=turn_id,
                run_id=f"run-{turn_id}",
                item_id=f"{turn_id}:status",
                kind="status",
                status="paused",
                payload={"type": "turn", "status": "paused"},
            ),
        ],
    )


def _split_turn_statuses(db_path: Path, thread_id: str) -> dict[str, str]:
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT turn_id, status FROM core_thread_snapshot_turns WHERE thread_id = ?",
            (thread_id,),
        ).fetchall()
    finally:
        conn.close()
    return {str(turn_id): str(status) for turn_id, status in rows}


async def _ensure_split_turn_row(db, db_path: Path, thread_id: str, turn_id: str) -> None:
    """Make the bug reproducible even without the Rust projector.

    In production the Rust projection writes this row. On hosts without the
    native store, seed the same row from the currently loaded turn so the
    rollback test still exercises the stale-row path.
    """
    if turn_id in _split_turn_statuses(db_path, thread_id):
        return
    async with db.session_factory() as session:
        meta = await db.persistence.load_metadata(session, thread_id)
    turns = meta.get("turns") or {}
    core_turns = (meta.get("core") or {}).get("turns") or {}
    core_turn = core_turns.get(turn_id) or turns.get(turn_id) or {}
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT OR REPLACE INTO core_thread_snapshot_turns "
            "(thread_id, turn_id, seq, status, core_turn_json, app_turn_json, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
            (
                thread_id,
                turn_id,
                int(core_turn.get("last_seq") or core_turn.get("seq") or 0),
                str(core_turn.get("status") or "paused"),
                json.dumps(core_turn, ensure_ascii=False),
                json.dumps(turns.get(turn_id) or {}, ensure_ascii=False),
            ),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_rollback_of_paused_turn_leaves_no_ghost_paused_turn(tmp_path: Path) -> None:
    db_path = tmp_path / "rollback-ghost.db"
    db = await open_core_app_db(db_path, workspace_id="ws-ghost")
    thread_id = "thread-ghost"
    turn_id = "turn-paused"
    try:
        await _seed_paused_turn(db, thread_id, turn_id)
        await _ensure_split_turn_row(db, db_path, thread_id, turn_id)

        async with db.session_factory() as session:
            before = await db.persistence.load_metadata(session, thread_id)
        assert _paused_turn_id(before) == turn_id

        backend = CoreCheckpointConversationBackend(db.session_factory)
        await db.persistence.write_coordinator.run(
            lambda session: backend.rollback_conversation_before_turn(
                session, session_id=thread_id, turn_id=turn_id,
            )
        )

        async with db.session_factory() as session:
            after = await db.persistence.load_metadata(session, thread_id)
            page = await db.persistence.load(session, thread_id)
        assert _paused_turn_id(after) == ""
        assert turn_id not in ((after.get("core") or {}).get("turns") or {})
        assert turn_id not in (after.get("turns") or {})
        assert _paused_turn_id(page) == ""
        # 分表里也不能留下这一回合；否则下一次读元数据又把它合并回来。
        assert turn_id not in _split_turn_statuses(db_path, thread_id)
    finally:
        await db.close()
