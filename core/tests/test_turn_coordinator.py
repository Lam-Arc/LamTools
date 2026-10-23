"""Turn coordinator and continuation worker contracts."""

from __future__ import annotations

import asyncio

import pytest

from types import SimpleNamespace

from lamtools_core.app.core_db import open_core_app_db
from lamtools_core.app.live_operations import (
    handle_interaction_list_operation,
    handle_interaction_respond_operation,
)
from lamtools_core.turn import (
    Interaction,
    InteractionOption,
    Turn,
    TurnCoordinator,
    TurnStore,
    TurnWorker,
    new_turn_id,
    now_ms,
)


@pytest.mark.asyncio
async def test_coordinator_pause_resume_and_epoch_guard(tmp_path):
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        store = TurnStore(db.session_factory, db.persistence.write_coordinator)
        coordinator = TurnCoordinator(store)
        turn_id = new_turn_id("thread")
        await coordinator.ensure_turn(thread_id="thread", turn_id=turn_id)
        run = await coordinator.start_run(turn_id, "run-1")
        assert run is not None
        assert (await store.get_turn(turn_id)).status == "running"  # type: ignore[union-attr]

        await store.create_interaction(
            Interaction(
                interaction_id="int-1",
                turn_id=turn_id,
                thread_id="thread",
                kind="question",
                title="Q?",
                options=[InteractionOption(id="option-1", label="A")],
            )
        )
        waiting = await coordinator.open_interactions(turn_id, ["int-1"])
        assert waiting is not None and waiting.status == "waiting"

        paused = await coordinator.pause(turn_id)
        assert paused is not None and paused.status == "paused"
        assert paused.epoch == 1
        deferred = await store.get_interaction("int-1")
        assert deferred is not None and deferred.status == "deferred"

        # A stale run result must not overwrite the pause.
        ignored = await coordinator.finish_run(turn_id, "run-1", status="completed")
        assert ignored is not None and ignored.status == "paused"

        resumed = await coordinator.resume(turn_id)
        assert resumed is not None
        turn, new_run = resumed
        assert turn.status == "waiting"
        assert new_run is None
        reopened = await store.get_interaction("int-1")
        assert reopened is not None and reopened.status == "open"

        await store.resolve_interaction("int-1", status="answered")
        run2 = await coordinator.start_run(turn_id, "run-2")
        assert run2 is None  # a waiting turn is continued by an answer, not start_run
        resumed_again = await coordinator.resume(turn_id)
        assert resumed_again is None  # not paused
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_coordinator_cancel_closes_interactions(tmp_path):
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        store = TurnStore(db.session_factory, db.persistence.write_coordinator)
        coordinator = TurnCoordinator(store)
        turn_id = new_turn_id("thread")
        await coordinator.ensure_turn(thread_id="thread", turn_id=turn_id)
        await coordinator.start_run(turn_id, "run-1")
        await store.create_interaction(
            Interaction(interaction_id="int-1", turn_id=turn_id, thread_id="thread", kind="approval")
        )
        stopping = await coordinator.cancel(turn_id, terminate=True)
        assert stopping is not None and stopping.status == "stopping"
        cancelled = await coordinator.settle_stopped(turn_id)
        assert cancelled is not None and cancelled.status == "cancelled"
        closed = await store.get_interaction("int-1")
        assert closed is not None and closed.status == "cancelled"
        assert (await coordinator.settle_stopped(turn_id)).status == "cancelled"  # type: ignore[union-attr]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_interaction_api_lists_open_cards_and_rejects_unknown_options(tmp_path):
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        store = TurnStore(db.session_factory, db.persistence.write_coordinator)
        await store.create_interaction(
            Interaction(
                interaction_id="int-api",
                turn_id="turn",
                thread_id="thread",
                kind="question",
                title="Which?",
                context="background",
                options=[
                    InteractionOption(id="option-1", label="A", response="A"),
                    InteractionOption(id="option-2", label="B", response="B"),
                ],
            )
        )
        context = SimpleNamespace(turn_store=store)

        listed = await handle_interaction_list_operation(
            request_id=1, params={"thread_id": "thread"}, context=context
        )
        payload = listed.response["result"]
        assert [item["interaction_id"] for item in payload["interactions"]] == ["int-api"]
        assert payload["interactions"][0]["kind"] == "question"

        rejected = await handle_interaction_respond_operation(
            request_id=2,
            params={
                "thread_id": "thread",
                "interaction_id": "int-api",
                "answer": {"kind": "option", "option_id": "option-9"},
            },
            context=context,
        )
        assert "error" in rejected.response
        assert "unknown interaction option" in rejected.response["error"]["message"]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_worker_claims_a_job_exactly_once(tmp_path):
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        store = TurnStore(db.session_factory, db.persistence.write_coordinator)
        handled: list[str] = []
        started = asyncio.Event()

        async def handler(job):
            handled.append(job["job_id"])
            started.set()

        worker = TurnWorker(store, handler, poll_seconds=0.05)
        job = await worker.enqueue(
            thread_id="thread",
            turn_id="turn",
            run_id="run",
            kind="interaction_answered",
            payload={"interaction_id": "int-1"},
            idempotency_key="int-1",
        )
        duplicate = await worker.enqueue(
            thread_id="thread",
            turn_id="turn",
            run_id="run",
            kind="interaction_answered",
            payload={"interaction_id": "int-1"},
            idempotency_key="int-1",
        )
        assert job["job_id"] == duplicate["job_id"]

        assert await worker.run_once("thread")
        await asyncio.wait_for(started.wait(), timeout=1)
        assert handled == [job["job_id"]]
        assert not await worker.run_once("thread")
        jobs = await store.list_jobs("thread")
        assert jobs[0]["status"] == "completed"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_worker_retries_then_fails(tmp_path):
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        store = TurnStore(db.session_factory, db.persistence.write_coordinator)
        attempts = 0

        async def handler(job):
            nonlocal attempts
            attempts += 1
            raise RuntimeError("boom")

        worker = TurnWorker(store, handler, max_attempts=2, retry_delay_ms=0, poll_seconds=0.05)
        await worker.enqueue(
            thread_id="thread",
            turn_id="turn",
            run_id="run",
            kind="interaction_answered",
            payload={},
            idempotency_key="int-2",
        )
        assert await worker.run_once("thread")
        assert await worker.run_once("thread")
        assert attempts == 2
        jobs = await store.list_jobs("thread")
        assert jobs[0]["status"] == "failed"
        assert "boom" in jobs[0]["last_error"]
    finally:
        await db.close()
