from __future__ import annotations

from typing import Any

import pytest

from lamtools_core.app import AppEventInput, OperationCatalog, open_core_app_db
from lamtools_core.app.live_hub import CoreAppEventHub
from lamtools_core.app.live_operations import (
    CoreLiveContext,
    reconcile_terminal_turns,
    recover_stale_active_turns,
)
from lamtools_core.app.queue_state import ACTIVE_TURN_STATUSES, latest_active_turn_id
from lamtools_core.event import RunItemEvent
from lamtools_core.runtime import InMemoryRuntimeStateStore, RuntimeState
from lamtools_core.runtime.memory_guard import HOST_MEMORY_EXHAUSTED, pending_memory_resume


async def _append_dangling_tool_call(db: Any, *, session_id: str, turn_id: str) -> str:
    """Seed the exact leftover of a crash mid-step: a tool_call still running."""
    item_id = f"{turn_id}:tool:write_file"
    async def write(session: Any) -> None:
        await db.persistence.append_run_item(
            session,
            RunItemEvent(
                kind="tool_call",
                thread_id=session_id,
                turn_id=turn_id,
                item_id=item_id,
                status="running",
                payload={"type": "dynamicToolCall", "tool_name": "write_file"},
            ),
        )
    await db.persistence.write(write)
    return item_id


async def _append_turn_start(db: Any, *, session_id: str, turn_id: str, text: str) -> None:
    """Seed a durably-running turn exactly like handle_turn_start_operation does
    right before the background task writes a terminal status — i.e. the exact
    state a crash leaves behind."""
    async def write(session: Any) -> None:
        await db.persistence.append_many(
            session,
            [
                AppEventInput(
                    thread_id=session_id,
                    turn_id=turn_id,
                    method="turn/accepted",
                    payload={"type": "turn", "status": "running", "input": [{"type": "text", "text": text}]},
                ),
                AppEventInput(
                    thread_id=session_id,
                    turn_id=turn_id,
                    item_id=f"{turn_id}:user",
                    method="item/started",
                    payload={
                        "type": "userMessage",
                        "status": "completed",
                        "content": [{"type": "text", "text": text}],
                    },
                ),
                AppEventInput(
                    thread_id=session_id,
                    turn_id=turn_id,
                    item_id=f"{turn_id}:running",
                    method="core/runItem",
                    payload=RunItemEvent(
                        kind="status",
                        thread_id=session_id,
                        turn_id=turn_id,
                        item_id=f"{turn_id}:running",
                        status="running",
                        payload={"type": "turn", "status": "running"},
                    ).to_dict(),
                ),
            ],
        )

    await db.persistence.write(write)


@pytest.mark.asyncio
async def test_startup_reaper_preserves_a_turn_owned_by_another_live_process(tmp_path):
    from lamtools_core.runtime_owner import owner_token
    db = await open_core_app_db(tmp_path / "core.db")
    store = InMemoryRuntimeStateStore()
    thread_id = "parent:sub:worker"
    turn_id = f"{thread_id}:turn:owned"
    await store.save(RuntimeState(session_id=thread_id, run_id=turn_id, status="running",
                                  metadata={"runtime_owner": owner_token()}))
    context = CoreLiveContext(operations=OperationCatalog(), session_factory=db.session_factory,
                              persistence=db.persistence, runtime_state_store=store, hub=CoreAppEventHub())
    try:
        await _append_turn_start(db, session_id=thread_id, turn_id=turn_id, text="working")
        assert await recover_stale_active_turns(context=context) == 0
        assert (await store.get(thread_id)).status == "running"
        async with db.session_factory() as session:
            snapshot = await db.persistence.load(session, thread_id)
        assert snapshot["core"]["turns"][turn_id]["status"] == "running"
    finally:
        await db.close()


async def _append_turn_waiting(db: Any, *, session_id: str, turn_id: str, text: str) -> None:
    """Seed a turn parked on tool approval ('waiting') — the other active status
    a crash can leave behind."""
    async def write(session: Any) -> None:
        await db.persistence.append_many(
            session,
            [
                AppEventInput(
                    thread_id=session_id,
                    turn_id=turn_id,
                    method="turn/accepted",
                    payload={"type": "turn", "status": "running", "input": [{"type": "text", "text": text}]},
                ),
                AppEventInput(
                    thread_id=session_id,
                    turn_id=turn_id,
                    item_id=f"{turn_id}:running",
                    method="core/runItem",
                    payload=RunItemEvent(
                        kind="status",
                        thread_id=session_id,
                        turn_id=turn_id,
                        item_id=f"{turn_id}:running",
                        status="running",
                        payload={"type": "turn", "status": "running"},
                    ).to_dict(),
                ),
                AppEventInput(
                    thread_id=session_id,
                    turn_id=turn_id,
                    item_id=f"{turn_id}:waiting",
                    method="core/runItem",
                    payload=RunItemEvent(
                        kind="status",
                        thread_id=session_id,
                        turn_id=turn_id,
                        item_id=f"{turn_id}:waiting",
                        status="waiting",
                        payload={"type": "turn", "status": "waiting"},
                    ).to_dict(),
                ),
            ],
        )

    await db.persistence.write(write)


async def _load_snapshot(db: Any, thread_id: str) -> dict[str, Any]:
    async with db.session_factory() as session:
        return await db.persistence.load(session, thread_id)


@pytest.mark.asyncio
async def test_recover_stale_active_turns_clears_running_waiting_and_is_idempotent(tmp_path):
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        # thread-stale: two leftover running turns (bypass paths can overlap),
        # plus a runtime state with a pending approval to be reconciled.
        await _append_turn_start(db, session_id="thread-stale", turn_id="turn-running", text="hello")
        await _append_turn_start(db, session_id="thread-stale", turn_id="turn-running-2", text="again")
        # thread-stale-2: one leftover 'waiting' turn
        await _append_turn_waiting(db, session_id="thread-stale-2", turn_id="turn-waiting", text="approve me")

        runtime_store = InMemoryRuntimeStateStore()
        await runtime_store.save(
            RuntimeState(
                session_id="thread-stale",
                run_id="turn-running",
                status="running",
                metadata={"pending_approval": {"request_id": "req-1"}},
            )
        )

        context = CoreLiveContext(
            operations=OperationCatalog(),
            session_factory=db.session_factory,
            persistence=db.persistence,
            runtime_state_store=runtime_store,
            hub=CoreAppEventHub(),
        )

        # Sanity: both threads currently have an active turn in the snapshot.
        assert latest_active_turn_id(await _load_snapshot(db, "thread-stale")) is not None
        assert latest_active_turn_id(await _load_snapshot(db, "thread-stale-2")) is not None
        async with db.session_factory() as session:
            assert set(await db.persistence.list_active_thread_ids(session)) == {
                "thread-stale",
                "thread-stale-2",
            }

        recovered = await recover_stale_active_turns(context=context)
        assert recovered == 3

        # Every active turn is now terminal — the durable-snapshot guard
        # (latest_active_turn_id) returns None, so turn.start is unblocked.
        snap_stale = await _load_snapshot(db, "thread-stale")
        snap_stale_2 = await _load_snapshot(db, "thread-stale-2")
        assert latest_active_turn_id(snap_stale) is None
        assert latest_active_turn_id(snap_stale_2) is None
        turns = snap_stale.get("turns", {})
        assert str(turns.get("turn-running", {}).get("status") or "") == "cancelled"
        assert str(turns.get("turn-running-2", {}).get("status") or "") == "cancelled"
        assert str(snap_stale_2.get("turns", {}).get("turn-waiting", {}).get("status") or "") == "cancelled"

        # The matching runtime state is reconciled (cancelled, approval cleared).
        state = await runtime_store.get("thread-stale")
        assert state is not None
        assert state.status == "cancelled"
        assert state.loop_state == "failed"
        assert "pending_approval" not in state.metadata

        # Idempotent: a second sweep finds nothing left to reap.
        recovered_again = await recover_stale_active_turns(context=context)
        assert recovered_again == 0
        async with db.session_factory() as session:
            assert await db.persistence.list_active_thread_ids(session) == []
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_recover_stale_active_turns_skips_terminal_threads(tmp_path):
    """A thread whose turn already completed normally must not be touched."""
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        await _append_turn_start(db, session_id="thread-done", turn_id="turn-ok", text="hi")
        async def write(session: Any) -> None:
            await db.persistence.append_run_item(
                session,
                RunItemEvent(
                    kind="status",
                    thread_id="thread-done",
                    turn_id="turn-ok",
                    item_id="turn-ok:terminal",
                    status="completed",
                    payload={"type": "turn", "status": "completed"},
                ),
            )
        await db.persistence.write(write)

        context = CoreLiveContext(
            operations=OperationCatalog(),
            session_factory=db.session_factory,
            persistence=db.persistence,
            runtime_state_store=InMemoryRuntimeStateStore(),
            hub=CoreAppEventHub(),
        )

        recovered = await recover_stale_active_turns(context=context)
        assert recovered == 0
        snap = await _load_snapshot(db, "thread-done")
        assert latest_active_turn_id(snap) is None
        assert str(snap.get("turns", {}).get("turn-ok", {}).get("status") or "") == "completed"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_reconcile_closes_a_turn_the_runtime_already_failed(tmp_path):
    """The 2026-10-10 shape: the state says memory exhaustion, the snapshot still
    says running, and a tool_call is left mid-stream. The session must stop
    claiming to be alive, and it must say why."""
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        await _append_turn_start(db, session_id="thread-oom", turn_id="turn-oom", text="make a PV")
        dangling_id = await _append_dangling_tool_call(db, session_id="thread-oom", turn_id="turn-oom")

        runtime_store = InMemoryRuntimeStateStore()
        await runtime_store.save(
            RuntimeState(
                session_id="thread-oom",
                run_id="turn-oom",
                status="failed",
                loop_state="failed",
                metadata={
                    # Exactly what the interrupted run wrote before it died.
                    "failure_code": HOST_MEMORY_EXHAUSTED,
                    "failure_message": "本机内存不足，本轮已中断。可用内存大于 4 GB 时 Sunday 会自动继续。",
                    "original_user_message": "make a PV",
                },
            )
        )
        context = CoreLiveContext(
            operations=OperationCatalog(),
            session_factory=db.session_factory,
            persistence=db.persistence,
            runtime_state_store=runtime_store,
            hub=CoreAppEventHub(),
        )

        closed = await reconcile_terminal_turns(context=context)
        assert closed >= 1
        assert latest_active_turn_id(await _load_snapshot(db, "thread-oom")) is None

        snap = await _load_snapshot(db, "thread-oom")
        turn = snap.get("turns", {}).get("turn-oom", {})
        assert str(turn.get("status") or "") == "failed"
        core_items = (snap.get("core") or {}).get("items") or {}
        terminal = core_items.get("turn-oom:terminal")
        assert terminal is not None
        assert terminal["status"] == "failed"
        assert terminal["payload"]["raw_end_reason"] == HOST_MEMORY_EXHAUSTED
        assert "内存不足" in terminal["payload"]["message"]
        # The half-streamed tool_call is closed too, so nothing renders as live.
        assert str(core_items.get(dangling_id, {}).get("status") or "") == "cancelled"

        # The auto resume is armed on the durable state (survives a restart).
        state = await runtime_store.get("thread-oom")
        assert state is not None
        pending = pending_memory_resume(state)
        assert pending is not None
        assert pending["original_message"] == "make a PV"

        # Idempotent: nothing left to reconcile.
        assert await reconcile_terminal_turns(context=context) == 0
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_reconcile_leaves_running_states_alone(tmp_path):
    """A turn whose state is still running might be alive — never guess."""
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        await _append_turn_start(db, session_id="thread-live", turn_id="turn-live", text="long tool")
        runtime_store = InMemoryRuntimeStateStore()
        await runtime_store.save(
            RuntimeState(session_id="thread-live", run_id="turn-live", status="running", metadata={})
        )
        context = CoreLiveContext(
            operations=OperationCatalog(),
            session_factory=db.session_factory,
            persistence=db.persistence,
            runtime_state_store=runtime_store,
            hub=CoreAppEventHub(),
        )

        assert await reconcile_terminal_turns(context=context) == 0
        assert latest_active_turn_id(await _load_snapshot(db, "thread-live")) == "turn-live"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_reconcile_ranks_a_named_failure_over_the_generic_text(tmp_path):
    """A non-memory failure keeps its own code and explanation."""
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        await _append_turn_start(db, session_id="thread-fail", turn_id="turn-fail", text="go")
        runtime_store = InMemoryRuntimeStateStore()
        await runtime_store.save(
            RuntimeState(
                session_id="thread-fail",
                run_id="turn-fail",
                status="failed",
                metadata={"failure_code": "model_retry_exhausted"},
            )
        )
        context = CoreLiveContext(
            operations=OperationCatalog(),
            session_factory=db.session_factory,
            persistence=db.persistence,
            runtime_state_store=runtime_store,
            hub=CoreAppEventHub(),
        )

        assert await reconcile_terminal_turns(context=context) >= 1
        snap = await _load_snapshot(db, "thread-fail")
        terminal = ((snap.get("core") or {}).get("items") or {}).get("turn-fail:terminal")
        assert terminal is not None
        assert terminal["payload"]["raw_end_reason"] == "model_retry_exhausted"
        # No resume is armed for a non-memory failure.
        state = await runtime_store.get("thread-fail")
        assert state is not None
        assert pending_memory_resume(state) is None
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_reaper_uses_the_recorded_reason_instead_of_burying_it(tmp_path):
    """The runtime already said why the turn ended; the startup cleanup must not
    stamp "unexpected shutdown" over it and swallow the auto resume. That is how
    a memory-interrupted PV session got closed anonymously (2026-10-10)."""
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        await _append_turn_start(db, session_id="thread-oom", turn_id="turn-oom", text="make a PV")
        await _append_dangling_tool_call(db, session_id="thread-oom", turn_id="turn-oom")

        runtime_store = InMemoryRuntimeStateStore()
        await runtime_store.save(
            RuntimeState(
                session_id="thread-oom",
                run_id="turn-oom",
                status="failed",
                metadata={"failure_code": HOST_MEMORY_EXHAUSTED, "original_user_message": "make a PV"},
            )
        )
        context = CoreLiveContext(
            operations=OperationCatalog(),
            session_factory=db.session_factory,
            persistence=db.persistence,
            runtime_state_store=runtime_store,
            hub=CoreAppEventHub(),
        )

        assert await recover_stale_active_turns(context=context) >= 1

        snap = await _load_snapshot(db, "thread-oom")
        turn = snap.get("turns", {}).get("turn-oom", {})
        assert str(turn.get("status") or "") == "failed"
        core_items = (snap.get("core") or {}).get("items") or {}
        terminal = core_items.get("turn-oom:terminal")
        assert terminal is not None
        assert terminal["payload"]["raw_end_reason"] == HOST_MEMORY_EXHAUSTED

        # The state keeps the reason it recorded, and the resume is armed.
        state = await runtime_store.get("thread-oom")
        assert state is not None
        assert state.status == "failed"
        assert pending_memory_resume(state) is not None
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_reaper_still_unblocks_a_thread_with_no_recorded_reason(tmp_path):
    """No evidence means the old behaviour: close it and unblock the thread."""
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        await _append_turn_start(db, session_id="thread-crash", turn_id="turn-crash", text="hi")
        runtime_store = InMemoryRuntimeStateStore()
        await runtime_store.save(
            RuntimeState(session_id="thread-crash", run_id="turn-crash", status="running", metadata={})
        )
        context = CoreLiveContext(
            operations=OperationCatalog(),
            session_factory=db.session_factory,
            persistence=db.persistence,
            runtime_state_store=runtime_store,
            hub=CoreAppEventHub(),
        )

        assert await recover_stale_active_turns(context=context) >= 1
        snap = await _load_snapshot(db, "thread-crash")
        assert str(snap.get("turns", {}).get("turn-crash", {}).get("status") or "") == "cancelled"
        state = await runtime_store.get("thread-crash")
        assert state is not None and state.status == "cancelled"
    finally:
        await db.close()
