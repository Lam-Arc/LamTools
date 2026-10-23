"""Domain/store contracts for the turn-control read models."""

from __future__ import annotations

import asyncio

import pytest

from lamtools_core.app.core_db import open_core_app_db
from lamtools_core.turn import (
    AgentRun,
    ControlIntent,
    Interaction,
    InteractionAnswer,
    InteractionOption,
    Run,
    Turn,
    TurnStore,
    can_transition,
    new_run_id,
    new_turn_id,
    now_ms,
)


@pytest.mark.asyncio
async def test_turn_store_transition_is_epoch_cas(tmp_path):
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        store = TurnStore(db.session_factory, db.persistence.write_coordinator)
        turn_id = new_turn_id("thread")
        turn = Turn(turn_id=turn_id, thread_id="thread", status="queued")
        await store.create_turn(turn)

        started = await store.transition_turn(
            turn_id,
            expected_epoch=0,
            expected_status="queued",
            status="running",
            event="run_started",
            active_run_id="run-1",
        )
        assert started is not None and started.status == "running"

        # A second writer holding the old epoch must lose.
        stale = await store.transition_turn(
            turn_id,
            expected_epoch=0,
            expected_status="queued",
            status="cancelled",
            event="cancel_applied",
        )
        assert stale is None
        current = await store.get_turn(turn_id)
        assert current is not None and current.status == "running"

        paused = await store.transition_turn(
            turn_id,
            expected_epoch=0,
            expected_status="running",
            status="paused",
            event="pause_applied",
            bump_epoch=True,
        )
        assert paused is not None and paused.status == "paused" and paused.epoch == 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_interaction_resolution_is_idempotent(tmp_path):
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        store = TurnStore(db.session_factory, db.persistence.write_coordinator)
        interaction = Interaction(
            interaction_id="int-1",
            turn_id="turn-1",
            thread_id="thread",
            kind="question",
            title="Pick one",
            options=[InteractionOption(id="option-1", label="A"), InteractionOption(id="option-2", label="B")],
            expires_at_ms=now_ms() + 1000,
        )
        await store.create_interaction(interaction)

        resolved = await store.resolve_interaction(
            "int-1",
            status="answered",
            answer=InteractionAnswer(kind="option", option_id="option-1", text="A"),
        )
        assert resolved is not None and resolved.status == "answered"

        duplicate = await store.resolve_interaction(
            "int-1",
            status="answered",
            answer=InteractionAnswer(kind="option", option_id="option-2", text="B"),
        )
        assert duplicate is None
        current = await store.get_interaction("int-1")
        assert current is not None and current.answer is not None
        assert current.answer.option_id == "option-1"

        found = await store.find_interaction("thread", "int-1")
        assert found is not None and found.interaction_id == "int-1"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_job_enqueue_is_idempotent_and_claimable(tmp_path):
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        store = TurnStore(db.session_factory, db.persistence.write_coordinator)
        first = await store.enqueue_job(
            thread_id="thread",
            turn_id="turn",
            run_id="run",
            kind="interaction_answered",
            payload={"interaction_id": "int-1"},
            idempotency_key="int-1",
        )
        second = await store.enqueue_job(
            thread_id="thread",
            turn_id="turn",
            run_id="run",
            kind="interaction_answered",
            payload={"interaction_id": "int-1"},
            idempotency_key="int-1",
        )
        assert first["job_id"] == second["job_id"]

        claimed = await store.claim_next_job("thread")
        assert claimed is not None and claimed["status"] == "running"
        assert await store.claim_next_job("thread") is None
        assert await store.finish_job(claimed["job_id"], status="completed")
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_agent_run_upsert_and_live_query(tmp_path):
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        store = TurnStore(db.session_factory, db.persistence.write_coordinator)
        run = AgentRun(
            agent_run_id="agent-run-1",
            parent_turn_id="turn-1",
            parent_thread_id="thread",
            name="researcher",
            status="running",
            lease_until_ms=now_ms() + 60_000,
        )
        await store.upsert_agent_run(run)
        run.status = "paused"
        await store.upsert_agent_run(run)
        loaded = await store.get_agent_run("agent-run-1")
        assert loaded is not None and loaded.status == "paused"
        live = await store.list_agent_runs(parent_thread_id="thread", live_only=True)
        assert [item.agent_run_id for item in live] == ["agent-run-1"]
    finally:
        await db.close()


def test_transition_table_rejects_terminal_changes():
    assert can_transition("running", "pause_applied") == "paused"
    assert can_transition("paused", "resume_applied") == "running"
    assert can_transition("completed", "run_completed") is None
    assert can_transition("cancelled", "resume_applied") is None


def test_run_identity_helpers_are_stable():
    turn_id = new_turn_id("thread")
    assert turn_id.startswith("thread:turn:")
    assert new_run_id() != new_run_id()


@pytest.mark.asyncio
async def test_projection_mirrors_an_interaction_and_its_resolution(tmp_path):
    from lamtools_core.app.default_agent import _mirror_run_items_as_interactions
    from lamtools_core.event import RunItemEvent

    db = await open_core_app_db(tmp_path / "core.db")
    try:
        request = RunItemEvent(
            kind="approval_request",
            thread_id="thread",
            turn_id="turn",
            run_id="run",
            item_id="item-1",
            event_id="event-1",
            status="waiting",
            payload={
                "type": "serverRequest",
                "request_id": "request-1",
                "kind": "question",
                "message": "Which one?",
                "tool_name": "question",
                "context": "background",
                "options": [{"id": "option-1", "label": "A", "response": "A"}],
            },
        )
        await _mirror_run_items_as_interactions(
            [request],
            db_session_factory=db.session_factory,
            write_coordinator=db.persistence.write_coordinator,
        )
        store = TurnStore(db.session_factory, db.persistence.write_coordinator)
        open_items = await store.list_open_interactions(thread_id="thread")
        assert len(open_items) == 1
        assert open_items[0].kind == "question"
        assert open_items[0].context == "background"
        assert open_items[0].options[0].id == "option-1"
        assert open_items[0].expires_at_ms > 0

        response = RunItemEvent(
            kind="approval_response",
            thread_id="thread",
            turn_id="turn",
            run_id="run",
            item_id="item-1",
            event_id="event-2",
            status="completed",
            payload={
                "type": "serverRequest",
                "request_id": "request-1",
                "status": "resolved",
                "decision": "approve",
                "guidance": "A",
            },
        )
        await _mirror_run_items_as_interactions(
            [response],
            db_session_factory=db.session_factory,
            write_coordinator=db.persistence.write_coordinator,
        )
        resolved = await store.get_interaction("request-1")
        assert resolved is not None
        assert resolved.status == "answered"
        assert resolved.answer is not None and resolved.answer.text == "A"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_snapshot_exposes_open_interactions_outside_the_transcript_window(tmp_path):
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        store = TurnStore(db.session_factory, db.persistence.write_coordinator)
        await store.create_interaction(
            Interaction(
                interaction_id="old-card",
                turn_id="old-turn",
                thread_id="thread",
                kind="question",
                title="old question",
                context="old context",
                options=[InteractionOption(id="option-1", label="A")],
                expires_at_ms=now_ms() + 60_000,
            )
        )
        await store.create_interaction(
            Interaction(
                interaction_id="answered-card",
                turn_id="old-turn",
                thread_id="thread",
                kind="question",
                title="answered",
                status="answered",
            )
        )
        async with db.session_factory() as session:
            rows = await db.snapshot_store._load_open_interactions(session, "thread")
        assert [row["interaction_id"] for row in rows] == ["old-card"]
        assert rows[0]["context"] == "old context"
        assert rows[0]["options"][0]["id"] == "option-1"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_job_claim_is_single_owner_and_reclaims_expired_leases(tmp_path):
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        store = TurnStore(db.session_factory, db.persistence.write_coordinator)
        job = await store.enqueue_job(
            thread_id="thread",
            turn_id="turn",
            run_id="run",
            kind="approval.respond",
            payload={"params": {"decision": "approve"}},
            idempotency_key="approval-1",
        )
        duplicate = await store.enqueue_job(
            thread_id="thread",
            turn_id="turn",
            run_id="run",
            kind="approval.respond",
            payload={"params": {"decision": "approve"}},
            idempotency_key="approval-1",
        )
        assert duplicate["job_id"] == job["job_id"]

        claimed = await store.claim_job(job["job_id"], lease_ms=1_000)
        assert claimed is not None and claimed["status"] == "running"
        # A second task cannot claim a live lease.
        assert await store.claim_job(job["job_id"], lease_ms=1_000) is None

        # An expired lease is reclaimable: this is crash recovery without a
        # restart, and it never runs two handlers at once.
        await asyncio.sleep(1.05)
        reclaimed = await store.claim_job(job["job_id"], lease_ms=1_000)
        assert reclaimed is not None and reclaimed["attempts"] == 2

        assert await store.requeue_running_jobs() == 1
        requeued = await store.get_job(job["job_id"])
        assert requeued is not None and requeued["status"] == "pending"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_settle_thread_jobs_closes_pending_and_claimed_work(tmp_path):
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        store = TurnStore(db.session_factory, db.persistence.write_coordinator)
        pending = await store.enqueue_job(
            thread_id="thread",
            turn_id="turn",
            run_id="run",
            kind="approval.respond",
            payload={},
            idempotency_key="job-pending",
        )
        claimed = await store.enqueue_job(
            thread_id="thread",
            turn_id="turn",
            run_id="run",
            kind="approval.respond",
            payload={},
            idempotency_key="job-claimed",
        )
        assert await store.claim_job(claimed["job_id"]) is not None

        settled = await store.settle_thread_jobs(
            "thread", status="cancelled", error="turn paused"
        )
        assert settled == 2
        for job in (pending, claimed):
            row = await store.get_job(job["job_id"])
            assert row is not None
            assert row["status"] == "cancelled"
            assert row["last_error"] == "turn paused"
        assert await store.has_pending_jobs("thread") is False
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_decision_pool_sequence_hash_and_lifecycle_transitions(tmp_path):
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        store = TurnStore(db.session_factory, db.persistence.write_coordinator)
        first = await store.create_interaction(
            Interaction(
                interaction_id="dec-a",
                turn_id="turn-1",
                thread_id="thread-1",
                kind="question",
                title="First",
            )
        )
        second = await store.create_interaction(
            Interaction(
                interaction_id="dec-b",
                turn_id="turn-1",
                thread_id="thread-1",
                kind="approval",
                title="Second",
            )
        )
        assert (first.created_seq, second.created_seq) == (1, 2)
        assert first.decision_id.startswith("dec_")
        assert first.decision_id != second.decision_id

        processing = await store.mark_interaction_processing("dec-a")
        assert processing is not None
        assert processing.status == "processing"
        assert processing.created_seq == 1
        assert processing.lifecycle_state == "processing"
        assert [item.interaction_id for item in await store.list_open_interactions(thread_id="thread-1")] == ["dec-a", "dec-b"]

        reverted = await store.revert_interaction_processing("dec-a")
        assert reverted is not None and reverted.status == "open"
        await store.mark_interaction_processing("dec-a")
        ended = await store.resolve_interaction("dec-a", status="answered")
        assert ended is not None and ended.lifecycle_state == "ending"
        assert [item.interaction_id for item in await store.list_open_interactions(thread_id="thread-1")] == ["dec-b"]
    finally:
        await db.close()
