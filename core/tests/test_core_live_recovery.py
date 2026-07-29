from __future__ import annotations

from typing import Any

import pytest

from lamtools_core.app import AppEventInput, OperationCatalog, open_core_app_db
from lamtools_core.app.live_hub import CoreAppEventHub
from lamtools_core.app.live_operations import CoreLiveContext, recover_stale_active_turns
from lamtools_core.app.queue_state import ACTIVE_TURN_STATUSES, latest_active_turn_id
from lamtools_core.event import RunItemEvent
from lamtools_core.runtime import InMemoryRuntimeStateStore, RuntimeState


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
