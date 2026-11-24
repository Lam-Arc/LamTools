from __future__ import annotations

import asyncio

from sqlalchemy import event

from lamtools_core.app import open_core_app_db
from lamtools_core.app.event_store import AppEventInput
from lamtools_core.app.steering import pending_steering, record_consumed_guidance

from .test_core_checkpoint_graph import _append_production_turn, _runtime, _tool_call_history
from .test_message_operation_retries import context_for, seed_transcript


# user:“全修”+(旧稿提交遇到更新历史时只报冲突，原历史和新回合都留在数据库里)。
async def test_stale_message_edit_refuses_to_truncate_newer_turn(tmp_path):
    db = await open_core_app_db(tmp_path / "recovery.db")
    context = context_for(db)
    try:
        await seed_transcript(db, tmp_path)
        async with db.session_factory() as session:
            old_revision = await db.persistence.current_revision(session, "source")
        await _append_production_turn(db, "source", "newer-turn", "newer")
        transcript = _tool_call_history("original") + _tool_call_history("newer")
        await _runtime(db, "source", history=transcript)
        outcome = await context.host.execute("turn.replace", request_id=1, context=context, params={
            "thread_id": "source", "replace_turn_id": "old-turn", "client_message_id": "stale-edit",
            "expected_revision": old_revision, "input": [{"type": "text", "text": "replacement"}],
            "include_snapshot": False,
        })
        assert outcome.response["error"]["data"]["code"] == "REVISION_CONFLICT"
        assert context.runtime_task_registry.active_run_id("source") is None
        async with db.session_factory() as session:
            events = await db.event_store.list_thread(session, thread_id="source")
        assert any(e.turn_id == "newer-turn" for e in events)
        assert not any(e.client_message_id == "stale-edit" or e.method == "session/rollback" for e in events)
        assert len(await db.runtime_state_store.get_history("source")) == len(transcript)
    finally:
        task = context.runtime_task_registry.task("source")
        if task is not None:
            await asyncio.wait_for(task, 5)
        await db.close()


async def test_receipt_lookup_is_scoped_and_never_starts_or_replays_a_write(tmp_path):
    db = await open_core_app_db(tmp_path / "recovery.db")
    context = context_for(db)
    try:
        async def seed(session):
            for thread_id, message_id, method in [("source", "sent", "turn/accepted"),
                                                  ("source", "queued", "queue/itemAccepted"),
                                                  ("different", "foreign", "turn/accepted")]:
                await db.persistence.append(session, AppEventInput(
                    thread_id=thread_id, method=method, client_message_id=message_id,
                ))
        await db.persistence.write(seed)
        response = await context.host.execute("thread.writeReceipts", request_id=1, context=context, params={
            "thread_id": "source", "client_message_ids": ["sent", "queued", "missing", "foreign"],
        })
        assert {(e["client_message_id"], e["method"]) for e in response.response["result"]["events"]} == {
            ("sent", "turn/accepted"), ("queued", "queue/itemAccepted"),
        }
        assert context.runtime_task_registry.active_run_id("source") is None
    finally:
        await db.close()


async def test_guidance_recovery_reads_history_only_for_unconfirmed_ids(tmp_path):
    db = await open_core_app_db(tmp_path / "recovery.db")
    statements: list[str] = []

    def capture(_conn, _cursor, statement, *_args):
        statements.append(statement)

    async def read(turn_id=None):
        return await pending_steering(db.session_factory, "source", turn_id=turn_id,
                                      event_store=db.event_store, write_coordinator=db.persistence.write_coordinator)

    try:
        async def seed(session):
            for guide, turn in [("ack", "old"), ("handoff", "old"), ("legacy", "old"), ("pending", "new")]:
                await db.persistence.append(session, AppEventInput(
                    thread_id="source", method="turn/steered", turn_id=turn, client_message_id=guide,
                    payload={"guidance_id": guide, "input": [{"type": "text", "text": guide}]},
                ))
            await db.persistence.append(session, AppEventInput(thread_id="source", method="queue/itemAccepted",
                item_id="q", payload={"guidance_handoff_ids": ["handoff"]}))
        await db.persistence.write(seed)
        await record_consumed_guidance(db.session_factory, thread_id="source", turn_id="old", guidance_ids=["ack"],
                                       event_store=db.event_store, write_coordinator=db.persistence.write_coordinator)
        await db.runtime_state_store.append_history("source", [
            {"role": "user", "content": "legacy receipt", "metadata": {"guidance_ids": ["legacy"]}},
        ])
        event.listen(db.engine.sync_engine, "before_cursor_execute", capture)
        assert await read("source:turn:old") == []
        assert any("core_history_entries" in sql for sql in statements)
        statements.clear()
        assert await read("source:turn:old") == []
        assert all("core_history_entries" not in sql for sql in statements)
        assert [item["id"] for item in await read()] == ["pending"]
    finally:
        if event.contains(db.engine.sync_engine, "before_cursor_execute", capture):
            event.remove(db.engine.sync_engine, "before_cursor_execute", capture)
        await db.close()
