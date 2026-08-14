from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from lamtools_core.runtime.arrange import ArrangeManager, ArrangeRunner, InMemoryArrangeStore


NOW = datetime(2026, 7, 16, 8, 0, tzinfo=timezone.utc)


async def _wait_idle(runner: ArrangeRunner, timeout: float = 5.0) -> None:
    """run_due_once no longer awaits its spawned tasks (audit 07 S3 — the
    poll loop must stay responsive); wait for them before asserting side
    effects."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while runner._active_tasks and loop.time() < deadline:
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_once_job_runs_and_completes() -> None:
    store = InMemoryArrangeStore()
    manager = ArrangeManager(store)
    seen: list[dict] = []
    job = await manager.create(
        thread_id="thread-1",
        work_root="test-proj",
        kind="focus",
        operation="turn.start",
        payload={"message": "check competitors"},
        trigger={"type": "once", "run_at": NOW.isoformat()},
        now=NOW,
    )
    runner = ArrangeRunner(store, lambda claimed: seen.append(claimed.to_dict()), clock=lambda: NOW)

    assert await runner.run_due_once() == 1
    await _wait_idle(runner)

    saved = await manager.get(job.id)
    assert saved is not None
    assert saved.status == "completed"
    assert saved.run_count == 1
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_interval_job_reschedules_until_max_runs() -> None:
    current = NOW
    store = InMemoryArrangeStore()
    manager = ArrangeManager(store)
    job = await manager.create(
        thread_id="thread-1",
        work_root="test-proj",
        kind="routine",
        operation="turn.start",
        payload={"message": "weekly digest"},
        trigger={"type": "interval", "every_seconds": 60, "start_at": NOW.isoformat()},
        max_runs=2,
    )
    runner = ArrangeRunner(store, lambda _job: None, clock=lambda: current)

    assert await runner.run_due_once() == 1
    await _wait_idle(runner)
    first = await manager.get(job.id)
    assert first is not None
    assert first.status == "scheduled"
    assert first.next_run_at == NOW + timedelta(seconds=60)

    current = NOW + timedelta(seconds=60)
    assert await runner.run_due_once() == 1
    await _wait_idle(runner)
    finished = await manager.get(job.id)
    assert finished is not None
    assert finished.status == "completed"
    assert finished.run_count == 2


@pytest.mark.asyncio
async def test_event_job_waits_until_signalled() -> None:
    store = InMemoryArrangeStore()
    manager = ArrangeManager(store)
    job = await manager.create(
        thread_id="thread-1",
        work_root="test-proj",
        kind="focus",
        operation="turn.start",
        payload={"message": "inspect release"},
        trigger={"type": "event", "key": "project.released"},
    )
    runner = ArrangeRunner(store, lambda _job: None, clock=lambda: NOW)

    assert await runner.run_due_once() == 0
    assert await manager.signal("project.released", now=NOW) == 1
    assert await runner.run_due_once() == 1
    await _wait_idle(runner)
    assert (await manager.get(job.id)).status == "waiting"  # type: ignore[union-attr]

    assert await manager.signal("project.released", now=NOW) == 1
    assert await runner.run_due_once() == 1
    await _wait_idle(runner)
    assert (await manager.get(job.id)).run_count == 2  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_event_signal_keeps_payload_and_queues_while_job_is_busy() -> None:
    store = InMemoryArrangeStore()
    manager = ArrangeManager(store)
    started = asyncio.Event()
    release = asyncio.Event()
    seen: list[dict] = []

    async def execute(claimed):
        seen.append(claimed.signal)
        started.set()
        await release.wait()

    job = await manager.create(
        thread_id="thread-1",
        work_root="test-proj",
        kind="focus",
        operation="turn.start",
        payload={"message": "inspect the event"},
        trigger={"type": "event", "event_type": "code.review.requested"},
    )
    first = await manager.emit_signal(
        {
            "event_id": "evt-1",
            "event_type": "code.review.requested",
            "occurred_at": NOW.isoformat(),
            "source": "example-provider",
            "subject": "change/42",
            "data": {"url": "https://example.test/change/42", "revision": "abc123"},
            "references": [{"type": "url", "value": "https://example.test/change/42.diff"}],
        },
        now=NOW,
    )
    runner = ArrangeRunner(store, execute, clock=lambda: NOW)
    running = asyncio.create_task(runner.run_due_once())
    await started.wait()

    second = await manager.emit_signal(
        {
            "event_id": "evt-2",
            "event_type": "code.review.requested",
            "occurred_at": (NOW + timedelta(seconds=1)).isoformat(),
            "data": {"url": "https://example.test/change/43"},
        },
        now=NOW + timedelta(seconds=1),
    )
    duplicate = await manager.emit_signal(
        {
            "event_id": "evt-2",
            "event_type": "code.review.requested",
            "occurred_at": (NOW + timedelta(seconds=1)).isoformat(),
        },
        now=NOW + timedelta(seconds=2),
    )

    assert first.created is True and len(first.occurrences) == 1
    assert second.created is True and len(second.occurrences) == 1
    assert duplicate.created is False and duplicate.occurrences == ()
    assert len(await manager.list_occurrences(job_id=job.id)) == 2

    release.set()
    await running
    # run_due_once no longer awaits its spawned tasks (audit 07 S3); wait for
    # the busy job to actually finish before the next claim round.
    await _wait_idle(runner)
    assert seen[0]["event_id"] == "evt-1"
    assert seen[0]["data"]["revision"] == "abc123"

    assert await runner.run_due_once() == 1
    await _wait_idle(runner)
    assert [item["event_id"] for item in seen] == ["evt-1", "evt-2"]
    occurrences = await manager.list_occurrences(job_id=job.id)
    assert [item.status for item in occurrences] == ["completed", "completed"]


@pytest.mark.asyncio
async def test_one_signal_can_trigger_multiple_jobs() -> None:
    store = InMemoryArrangeStore()
    manager = ArrangeManager(store)
    for thread_id in ("thread-1", "thread-2"):
        await manager.create(
            thread_id=thread_id,
            work_root="test-proj",
            kind="focus",
            operation="turn.start",
            payload={"message": "inspect"},
            trigger={"type": "event", "event_type": "artifact.changed"},
        )

    emitted = await manager.emit_signal(
        {
            "event_id": "evt-many",
            "event_type": "artifact.changed",
            "occurred_at": NOW.isoformat(),
            "data": {"path": "report.md"},
        },
        now=NOW,
    )

    assert emitted.created is True
    assert len(emitted.occurrences) == 2


@pytest.mark.asyncio
async def test_runner_recovers_abandoned_job_from_same_occurrence() -> None:
    store = InMemoryArrangeStore()
    manager = ArrangeManager(store)
    job = await manager.create(
        thread_id="thread-1",
        work_root="test-proj",
        kind="focus",
        operation="turn.start",
        payload={"message": "resume durable task"},
        trigger={"type": "once", "run_at": NOW.isoformat()},
        now=NOW,
    )
    claimed = await store.claim_due(now=NOW, worker_id="dead-worker", lease_seconds=30, limit=1)
    assert claimed[0].occurrence_id

    # Lease (30s) has not expired yet: recover must NOT steal the job from a
    # possibly-alive worker (audit 07 S2).  Only after the lease expires does
    # the job become reclaimable.
    assert await store.recover_running(now=NOW + timedelta(seconds=1)) == 0
    seen_occurrences: list[str] = []
    runner = ArrangeRunner(
        store,
        lambda item: seen_occurrences.append(item.occurrence_id),
        clock=lambda: NOW + timedelta(seconds=31),
    )

    assert await store.recover_running(now=NOW + timedelta(seconds=31)) == 1
    assert await runner.run_due_once() == 1
    await _wait_idle(runner)
    assert seen_occurrences == [claimed[0].occurrence_id]
    assert (await manager.get(job.id)).status == "completed"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_paused_event_job_resumes_waiting_for_its_event() -> None:
    manager = ArrangeManager(InMemoryArrangeStore())
    job = await manager.create(
        thread_id="thread-1",
        work_root="test-proj",
        kind="focus",
        operation="turn.start",
        payload={"message": "watch"},
        trigger={"type": "event", "key": "source.changed"},
    )

    paused = await manager.update_status(job.id, "paused", now=NOW)
    resumed = await manager.update_status(job.id, "scheduled", now=NOW)

    assert paused.status == "paused"
    assert resumed.status == "waiting"
    assert resumed.next_run_at is None


@pytest.mark.asyncio
async def test_paused_event_job_runs_signal_received_while_paused() -> None:
    store = InMemoryArrangeStore()
    manager = ArrangeManager(store)
    job = await manager.create(
        thread_id="thread-1",
        work_root="test-proj",
        kind="focus",
        operation="turn.start",
        payload={"message": "watch"},
        trigger={"type": "event", "event_type": "source.changed"},
    )
    await manager.update_status(job.id, "paused", now=NOW)
    emitted = await manager.emit_signal(
        {
            "event_id": "evt-paused",
            "event_type": "source.changed",
            "occurred_at": NOW.isoformat(),
            "data": {"revision": "abc123"},
        },
        now=NOW,
    )

    resumed = await manager.update_status(job.id, "scheduled", now=NOW)

    assert emitted.occurrences[0].status == "pending"
    assert resumed.status == "scheduled"
    assert resumed.next_run_at == NOW


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("target_status", "expected_occurrence_status"),
    [("paused", "pending"), ("cancelled", "cancelled")],
)
async def test_stopping_running_job_updates_occurrence(
    target_status: str,
    expected_occurrence_status: str,
) -> None:
    store = InMemoryArrangeStore()
    manager = ArrangeManager(store)
    job = await manager.create(
        thread_id="thread-1",
        work_root="test-proj",
        kind="focus",
        operation="turn.start",
        payload={"message": "run"},
        trigger={"type": "once", "run_at": NOW.isoformat()},
        now=NOW,
    )
    claimed = await store.claim_due(
        now=NOW,
        worker_id="worker-1",
        lease_seconds=30,
        limit=1,
    )

    updated = await manager.update_status(job.id, target_status, now=NOW)
    occurrence = await manager.get_occurrence(claimed[0].occurrence_id)

    assert updated.status == target_status
    assert occurrence is not None
    assert occurrence.status == expected_occurrence_status
    assert occurrence.completed_at == (NOW if target_status == "cancelled" else None)


@pytest.mark.asyncio
async def test_runner_records_operation_result_on_occurrence() -> None:
    store = InMemoryArrangeStore()
    manager = ArrangeManager(store)
    job = await manager.create(
        thread_id="thread-1",
        work_root="test-proj",
        kind="focus",
        operation="turn.start",
        payload={"message": "run"},
        trigger={"type": "once", "run_at": NOW.isoformat()},
        now=NOW,
    )
    runner = ArrangeRunner(
        store,
        lambda _job: {"status": "ok", "payload": {"turn_id": "turn-1"}},
        clock=lambda: NOW,
    )

    assert await runner.run_due_once() == 1
    await _wait_idle(runner)
    saved = await manager.get(job.id)
    occurrence = await manager.get_occurrence(saved.occurrence_id)  # type: ignore[union-attr]

    assert occurrence is not None
    assert occurrence.result == {"status": "ok", "payload": {"turn_id": "turn-1"}}


@pytest.mark.asyncio
async def test_runner_can_cancel_an_active_execution_without_marking_it_failed() -> None:
    store = InMemoryArrangeStore()
    manager = ArrangeManager(store)
    started = asyncio.Event()

    async def execute(_job):
        started.set()
        await asyncio.Event().wait()

    job = await manager.create(
        thread_id="thread-1",
        work_root="test-proj",
        kind="focus",
        operation="turn.start",
        payload={"message": "watch"},
        trigger={"type": "once", "run_at": NOW.isoformat()},
        now=NOW,
    )
    runner = ArrangeRunner(store, execute, clock=lambda: NOW)
    run = asyncio.create_task(runner.run_due_once())
    await started.wait()

    assert await runner.cancel(job.id) is True
    await run
    cancelled = await manager.update_status(job.id, "cancelled", now=NOW)

    assert cancelled.status == "cancelled"
    assert cancelled.last_error == ""


@pytest.mark.asyncio
async def test_expired_lease_is_reclaimed_with_same_occurrence() -> None:
    store = InMemoryArrangeStore()
    manager = ArrangeManager(store)
    job = await manager.create(
        thread_id="thread-1",
        work_root="test-proj",
        kind="routine",
        operation="turn.start",
        payload={"message": "refresh"},
        trigger={"type": "once", "run_at": NOW.isoformat()},
        now=NOW,
    )
    first = await store.claim_due(now=NOW, worker_id="worker-1", lease_seconds=5, limit=1)

    # Lease expired: the job is reset to scheduled but must NOT be re-claimed
    # in the same round (its previous owner may still be finishing — audit
    # 07 S2).  The next poll round claims it.
    first_reset = await store.claim_due(
        now=NOW + timedelta(seconds=6),
        worker_id="worker-2",
        lease_seconds=5,
        limit=1,
    )
    assert first_reset == []
    assert (await manager.get(job.id)).status == "scheduled"  # type: ignore[union-attr]

    reclaimed = await store.claim_due(
        now=NOW + timedelta(seconds=6),
        worker_id="worker-2",
        lease_seconds=5,
        limit=1,
    )

    assert reclaimed[0].id == job.id
    assert reclaimed[0].occurrence_id == first[0].occurrence_id
    assert reclaimed[0].lease_owner == "worker-2"


@pytest.mark.asyncio
async def test_arrange_cancel_is_idempotent() -> None:
    manager = ArrangeManager(InMemoryArrangeStore())
    job = await manager.create(
        thread_id="thread-1",
        work_root="test-proj",
        kind="routine",
        operation="turn.start",
        payload={"message": "refresh"},
        trigger={"type": "once", "run_at": NOW.isoformat()},
        now=NOW,
    )

    cancelled = await manager.update_status(job.id, "cancelled", now=NOW)
    repeated = await manager.update_status(job.id, "cancelled", now=NOW)

    assert repeated == cancelled


@pytest.mark.asyncio
async def test_daily_calendar_job_keeps_local_wall_clock_time() -> None:
    store = InMemoryArrangeStore()
    manager = ArrangeManager(store)
    created_at = datetime(2026, 7, 16, 0, 30, tzinfo=timezone.utc)
    job = await manager.create(
        thread_id="thread-1",
        work_root="test-proj",
        kind="routine",
        operation="turn.start",
        payload={"message": "breakfast recommendation"},
        trigger={
            "type": "calendar",
            "frequency": "daily",
            "timezone": "Asia/Shanghai",
            "time": "09:00",
        },
        now=created_at,
    )

    assert job.next_run_at == datetime(2026, 7, 16, 1, 0, tzinfo=timezone.utc)

    runner = ArrangeRunner(store, lambda _job: None, clock=lambda: job.next_run_at)  # type: ignore[arg-type]
    assert await runner.run_due_once() == 1
    await _wait_idle(runner)
    repeated = await manager.get(job.id)
    assert repeated is not None
    assert repeated.status == "scheduled"
    assert repeated.next_run_at == datetime(2026, 7, 17, 1, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_monthly_calendar_job_schedules_requested_day() -> None:
    manager = ArrangeManager(InMemoryArrangeStore())

    job = await manager.create(
        thread_id="thread-1",
        work_root="test-proj",
        kind="routine",
        operation="turn.start",
        payload={"message": "monthly review"},
        trigger={
            "type": "calendar",
            "frequency": "monthly",
            "timezone": "Asia/Shanghai",
            "time": "09:00",
            "day": 1,
        },
        now=datetime(2026, 7, 16, 0, 0, tzinfo=timezone.utc),
    )

    assert job.next_run_at == datetime(2026, 8, 1, 1, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_once_job_accepts_local_date_time_and_rejects_past_time() -> None:
    manager = ArrangeManager(InMemoryArrangeStore())
    now = datetime(2026, 7, 16, 0, 0, tzinfo=timezone.utc)

    job = await manager.create(
        thread_id="thread-1",
        work_root="test-proj",
        kind="routine",
        operation="turn.start",
        payload={"message": "prepare report"},
        trigger={
            "type": "once",
            "date": "2026-08-12",
            "time": "09:00",
            "timezone": "Asia/Shanghai",
        },
        now=now,
    )

    assert job.next_run_at == datetime(2026, 8, 12, 1, 0, tzinfo=timezone.utc)
    assert job.trigger["local_at"] == "2026-08-12T09:00:00+08:00"

    with pytest.raises(ValueError, match="future"):
        await manager.create(
            thread_id="thread-1",
            work_root="test-proj",
            kind="routine",
            operation="turn.start",
            payload={"message": "too late"},
            trigger={"type": "once", "run_at": "2025-12-12T01:00:00+00:00"},
            now=now,
        )


@pytest.mark.asyncio
async def test_runner_cancel_persists_cancelled_status() -> None:
    """Audit 07 S2: cancel must persist the cancelled status so the job is
    not re-claimed (and re-executed) after its lease expires."""
    store = InMemoryArrangeStore()
    manager = ArrangeManager(store)
    job = await manager.create(
        thread_id="thread-1",
        work_root="test-proj",
        kind="routine",
        operation="turn.start",
        payload={"message": "slow"},
        trigger={"type": "once", "run_at": NOW.isoformat()},
        now=NOW,
    )
    started = asyncio.Event()

    async def blocking_executor(item) -> dict[str, Any]:
        started.set()
        await asyncio.sleep(10)

    runner = ArrangeRunner(store, blocking_executor, clock=lambda: NOW)
    assert await runner.run_due_once() == 1
    await _wait_idle(runner)
    await asyncio.wait_for(started.wait(), timeout=1)

    assert await runner.cancel(job.id) is True
    cancelled = await manager.get(job.id)
    assert cancelled is not None
    assert cancelled.status == "cancelled"
