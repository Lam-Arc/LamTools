"""Durable continuation worker.

Continuation jobs are persisted before any long work starts.  The worker
claims one job per thread, runs the supplied handler, and records success or a
bounded retry.  A process crash after enqueue therefore loses nothing: the
pending row is picked up by the next worker.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from .store import TurnStore

_logger = logging.getLogger(__name__)

JobHandler = Callable[[dict[str, Any]], Awaitable[None]]


class TurnWorker:
    def __init__(
        self,
        store: TurnStore,
        handler: JobHandler,
        *,
        max_attempts: int = 3,
        retry_delay_ms: int = 1_000,
        poll_seconds: float = 0.5,
    ) -> None:
        self.store = store
        self.handler = handler
        self.max_attempts = max(1, int(max_attempts))
        self.retry_delay_ms = max(0, int(retry_delay_ms))
        self.poll_seconds = max(0.05, float(poll_seconds))
        self._task: asyncio.Task[Any] | None = None
        self._stopping = False

    async def enqueue(
        self,
        *,
        thread_id: str,
        turn_id: str,
        run_id: str,
        kind: str,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        return await self.store.enqueue_job(
            thread_id=thread_id,
            turn_id=turn_id,
            run_id=run_id,
            kind=kind,
            payload=payload,
            idempotency_key=idempotency_key,
        )

    async def run_once(self, thread_id: str) -> bool:
        job = await self.store.claim_next_job(thread_id)
        if job is None:
            return False
        await self._execute_claimed(job, propagate=False)
        return True

    async def run_job(self, job_id: str) -> bool:
        """Claim and execute one specific durable job.

        The approval RPC uses this instead of ``run_thread`` so two calls can
        never consume each other's job: only the task that wins the claim runs
        it, and both callers are settled by that handler's result.
        """
        job = await self.store.claim_job(job_id)
        if job is None:
            return False
        await self._execute_claimed(job, propagate=True)
        return True

    async def _execute_claimed(
        self, job: dict[str, Any], *, propagate: bool
    ) -> None:
        try:
            await self.handler(job)
        except asyncio.CancelledError:
            # A pause/terminate may already have settled this job as
            # cancelled. Do not revive it as pending; only requeue a job that
            # is still owned by a live run.
            current = await self.store.get_job(job["job_id"])
            if current is not None and str(current.get("status") or "") == "running":
                await self.store.finish_job(
                    job["job_id"],
                    status="pending",
                    error="worker cancelled",
                    retry_after_ms=self.retry_delay_ms,
                )
            raise
        except BaseException as exc:
            _logger.exception(
                "[turn-worker] job failed thread_id=%s job_id=%s kind=%s",
                job.get("thread_id"),
                job.get("job_id"),
                job.get("kind"),
            )
            if int(job.get("attempts") or 0) < self.max_attempts:
                await self.store.finish_job(
                    job["job_id"],
                    status="pending",
                    error=str(exc),
                    retry_after_ms=self.retry_delay_ms,
                )
            else:
                await self.store.finish_job(
                    job["job_id"], status="failed", error=str(exc)
                )
            if propagate:
                raise
            return
        await self.store.finish_job(job["job_id"], status="completed")

    async def run_thread(self, thread_id: str) -> int:
        """Drain this thread's durable jobs, honouring retry delays.

        The one-shot task that acknowledges an approval owns this loop, so the
        continuation does not depend on a polling daemon being alive. A job
        whose retry is scheduled in the future is slept on rather than dropped;
        the loop ends only when no pending/leased job remains for the thread.
        """
        handled = 0
        while True:
            handled_now = await self.run_once(thread_id)
            if handled_now:
                handled += 1
                continue
            if not await self.store.has_pending_jobs(thread_id):
                return handled
            await asyncio.sleep(self.poll_seconds)

    async def run_all_once(self) -> int:
        handled = 0
        for thread_id in await self.store.list_pending_job_threads():
            while await self.run_once(thread_id):
                handled += 1
        return handled

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stopping = False
        self._task = asyncio.create_task(self._loop(), name="turn-worker")

    async def stop(self) -> None:
        self._stopping = True
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except BaseException:
                pass

    async def _loop(self) -> None:
        while not self._stopping:
            try:
                await self.run_all_once()
            except asyncio.CancelledError:
                raise
            except BaseException:
                _logger.exception("[turn-worker] pass failed")
            try:
                await asyncio.sleep(self.poll_seconds)
            except asyncio.CancelledError:
                raise


__all__ = ["TurnWorker"]
