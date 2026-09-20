from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from lamtools_core.app.core_db import open_core_app_db
from lamtools_core.runtime.arrange import ArrangeManager, ArrangeRunner, InMemoryArrangeStore


NOW = datetime(2026, 7, 16, 8, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_stale_same_worker_token_cannot_mutate_reclaimed_job() -> None:
    store = InMemoryArrangeStore()
    manager = ArrangeManager(store)
    job = await manager.create(
        thread_id="thread-1",
        work_root="test-proj",
        kind="routine",
        operation="turn.start",
        payload={"message": "resume"},
        trigger={"type": "once", "run_at": NOW.isoformat()},
        now=NOW,
    )

    first = (await store.claim_due(
        now=NOW,
        worker_id="reused-worker",
        lease_seconds=5,
        limit=1,
    ))[0]
    assert first.fencing_token == 1
    assert await store.claim_due(
        now=NOW + timedelta(seconds=6),
        worker_id="reused-worker",
        lease_seconds=5,
        limit=1,
    ) == []
    second = (await store.claim_due(
        now=NOW + timedelta(seconds=6),
        worker_id="reused-worker",
        lease_seconds=5,
        limit=1,
    ))[0]
    assert second.fencing_token == 2

    with pytest.raises(RuntimeError, match="lease lost"):
        await store.checkpoint_run(
            job_id=job.id,
            worker_id="reused-worker",
            now=NOW,
            checkpoint={"step": "stale"},
            fencing_token=first.fencing_token,
        )
    with pytest.raises(RuntimeError, match="lease lost"):
        await store.complete_run(
            job_id=job.id,
            worker_id="reused-worker",
            now=NOW,
            fencing_token=first.fencing_token,
        )
    assert await store.renew_lease(
        job_id=job.id,
        worker_id="reused-worker",
        now=NOW,
        lease_seconds=5,
        fencing_token=first.fencing_token,
    ) is False

    saved = await store.checkpoint_run(
        job_id=job.id,
        worker_id="reused-worker",
        now=NOW,
        checkpoint={"step": "current"},
        fencing_token=second.fencing_token,
    )
    assert saved.checkpoint == {"step": "current"}


@pytest.mark.asyncio
async def test_runner_checkpoint_helper_uses_claim_fence() -> None:
    store = InMemoryArrangeStore()
    manager = ArrangeManager(store)
    job = await manager.create(
        thread_id="thread-1",
        work_root="test-proj",
        kind="routine",
        operation="turn.start",
        payload={"message": "checkpoint"},
        trigger={"type": "once", "run_at": NOW.isoformat()},
        now=NOW,
    )
    runner: ArrangeRunner
    checkpointed = asyncio.Event()

    async def execute(claimed):
        await runner.checkpoint(claimed.id, {"completed": ["first"]})
        checkpointed.set()
        return {"status": "ok"}

    runner = ArrangeRunner(store, execute, clock=lambda: NOW)
    assert await runner.run_due_once() == 1
    await asyncio.wait_for(checkpointed.wait(), timeout=1)
    while runner._active_tasks:
        await asyncio.sleep(0)

    saved = await manager.get(job.id)
    assert saved is not None
    assert saved.status == "completed"
    assert saved.checkpoint == {"completed": ["first"]}


@pytest.mark.asyncio
async def test_sql_arrange_checkpoint_and_fence_survive_reopen(tmp_path) -> None:
    db_path = tmp_path / "core.db"
    db = await open_core_app_db(db_path)
    try:
        manager = ArrangeManager(db.arrange_store)
        job = await manager.create(
            thread_id="thread-1",
            work_root="test-proj",
            kind="routine",
            operation="turn.start",
            payload={"message": "persist"},
            trigger={"type": "once", "run_at": NOW.isoformat()},
            now=NOW,
        )
        claimed = (await db.arrange_store.claim_due(
            now=NOW,
            worker_id="worker-1",
            lease_seconds=5,
            limit=1,
        ))[0]
        await db.arrange_store.checkpoint_run(
            job_id=job.id,
            worker_id="worker-1",
            now=NOW,
            checkpoint={"module": "grammar", "offset": 3},
            fencing_token=claimed.fencing_token,
        )
    finally:
        await db.close()

    db = await open_core_app_db(db_path)
    try:
        saved = await db.arrange_store.get(job.id)
        assert saved is not None
        assert saved.fencing_token == 1
        assert saved.checkpoint == {"module": "grammar", "offset": 3}
    finally:
        await db.close()
