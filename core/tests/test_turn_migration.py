"""Upgrade backfill from the snapshot older builds persisted."""

from __future__ import annotations

import pytest

from lamtools_core.app.core_db import open_core_app_db
from lamtools_core.turn import TurnStore
from lamtools_core.turn.migrate import backfill_snapshot


@pytest.mark.asyncio
async def test_backfill_keeps_an_open_question_answerable(tmp_path):
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        store = TurnStore(db.session_factory, db.persistence.write_coordinator)
        thread_id = "thread-old"
        turn_id = f"{thread_id}:turn:1"
        snapshot = {
            "thread_id": thread_id,
            "status": "waiting",
            "turns": {
                turn_id: {
                    "turn_id": turn_id,
                    "status": "waiting",
                    "run_id": turn_id,
                    "seq": 1,
                    "last_seq": 4,
                }
            },
            "core": {
                "status": "waiting",
                "turns": {},
                "requests": {
                    "old-request": {
                        "request_id": "old-request",
                        "turn_id": turn_id,
                        "status": "open",
                        "item_id": f"{turn_id}:question",
                        "tool_name": "question",
                        "message": "Which source?",
                        "context": "legacy context",
                        "options": [{"id": "option-1", "label": "A", "response": "A"}],
                    }
                },
            },
        }

        assert await backfill_snapshot(store, thread_id, snapshot) == 2
        turn = await store.get_turn(turn_id)
        assert turn is not None and turn.status == "waiting"
        interaction = await store.get_interaction("old-request")
        assert interaction is not None
        assert interaction.kind == "question"
        assert interaction.status == "open"
        assert interaction.context == "legacy context"
        assert interaction.options[0].id == "option-1"
        assert interaction.expires_at_ms > 0

        # A second startup pass must not duplicate or overwrite the rows.
        assert await backfill_snapshot(store, thread_id, snapshot) == 0
        assert await store.get_interaction("old-request") is not None
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_backfill_never_expires_an_approval(tmp_path):
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        store = TurnStore(db.session_factory, db.persistence.write_coordinator)
        thread_id = "thread-approval"
        turn_id = f"{thread_id}:turn:1"
        snapshot = {
            "turns": {turn_id: {"turn_id": turn_id, "status": "waiting", "run_id": turn_id}},
            "core": {
                "status": "waiting",
                "turns": {},
                "requests": {
                    "approval-1": {
                        "request_id": "approval-1",
                        "turn_id": turn_id,
                        "status": "open",
                        "tool_name": "run_command",
                        "message": "Approve command",
                    }
                },
            },
        }
        await backfill_snapshot(store, thread_id, snapshot)
        interaction = await store.get_interaction("approval-1")
        assert interaction is not None
        assert interaction.kind == "approval"
        assert interaction.expires_at_ms == 0
    finally:
        await db.close()
