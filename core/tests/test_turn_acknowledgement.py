"""Indexed acceptance receipts and concurrent/lost-ack retries."""
import asyncio
import sqlite3

import pytest

from lamtools_core.app import open_core_app_db, OperationCatalog
from lamtools_core.app.live_operations import CoreLiveContext, wait_live_background_tasks


@pytest.mark.asyncio
async def test_existing_database_gains_bounded_client_lookup(tmp_path):
    path = tmp_path / "core.db"
    db = await open_core_app_db(path)
    await db.close()
    with sqlite3.connect(path) as conn:
        conn.execute("DROP INDEX idx_core_events_client_message")
        conn.executemany(
            "INSERT INTO core_app_events (event_id,thread_id,seq,method,payload_json,workspace_id,entity_type,entity_id,event_seq,revision,event_type,created_at) VALUES (?,?,?,?,?,'','thread.event','large-thread',0,0,'core/runItem',CURRENT_TIMESTAMP)",
            [(f"event-{i}","large-thread",i,"core/runItem",'{}') for i in range(1,30001)],
        )
        query = "SELECT * FROM core_app_events WHERE thread_id=? AND client_message_id=? AND method IN (?) ORDER BY seq LIMIT 1"
        args = ("large-thread","missing-submission","turn/accepted")
        steps = []
        conn.set_progress_handler(lambda: steps.append(1) or 0, 1000)
        assert conn.execute(query,args).fetchone() is None
        assert len(steps) > 100  # old path scans the thread, even for a fresh ID
        conn.set_progress_handler(None,0)
    db = await open_core_app_db(path)  # current schema version, existing table
    await db.close()
    with sqlite3.connect(path) as conn:
        plan = conn.execute("EXPLAIN QUERY PLAN " + query,args).fetchall()
        assert any("idx_core_events_client_message" in row[3] for row in plan), plan
        steps = []
        conn.set_progress_handler(lambda: steps.append(1) or 0, 1000)
        assert conn.execute(query,args).fetchone() is None
        assert len(steps) < 2
        conn.set_progress_handler(None,0)
        assert conn.execute("SELECT COUNT(*) FROM core_app_events").fetchone()[0] == 30000


@pytest.mark.asyncio
async def test_active_turn_retry_returns_original_receipt_without_second_run(tmp_path):
    db = await open_core_app_db(tmp_path / "core.db")
    operations = OperationCatalog()
    async def hold(request):
        await asyncio.Event().wait()
    operations.register("turn.start",hold)
    context = CoreLiveContext(session_factory=db.session_factory,persistence=db.persistence,
        operations=operations,runtime_state_store=db.runtime_state_store)
    params = {"thread_id":"receipt","client_message_id":"send-once","input":[{"type":"text","text":"task"}],"include_snapshot":False}
    try:
        first = await asyncio.wait_for(context.host.execute("turn.start",request_id=1,params=params,context=context),10)
        turn = first.runtime_start["turn_id"]
        task = context.runtime_task_registry.task("receipt")
        retries = await asyncio.wait_for(asyncio.gather(*[
            context.host.execute("turn.start",request_id=i,params=params,context=context) for i in (2,3)
        ]),10)
        for outcome in retries:
            assert "error" not in outcome.response,outcome.response
            assert outcome.response["result"]["events"][0]["turn_id"] == turn
            assert outcome.runtime_start is None
        assert context.runtime_task_registry.task("receipt") is task
        different = await context.host.execute("turn.start",request_id=4,params={**params,"client_message_id":"new"},context=context)
        assert different.response["error"]["data"]["code"] == "SESSION_BUSY"
        async with db.session_factory() as session:
            events = await db.persistence.list_after(session,thread_id="receipt",after_seq=0)
        assert len([e for e in events if e.method=="turn/accepted"]) == 1
    finally:
        context.runtime_task_registry.clear()
        task.cancel()
        await asyncio.gather(task,return_exceptions=True)
        await wait_live_background_tasks()
        await db.close()
