"""Ownership and draining of detached live-operation finalizers."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any


_logger = logging.getLogger("lamtools_core.app.live_operations")


CANCEL_ESCALATION_DELAYS_SECONDS: tuple[float, ...] = (1.0, 8.0)


CANCEL_FINALIZER_TASK_WAIT_CAP_SECONDS = 60.0


_LIVE_BACKGROUND_TASKS: set[asyncio.Task[None]] = set()


def _spawn_live_background(
    coro: Coroutine[Any, Any, None],
    *,
    label: str,
    thread_id: str = "",
) -> asyncio.Task[None]:
    """Run a fire-and-forget finalizer with ownership and failure logging.

    The cancel paths never await persistence inline any more: the RPC/task
    must return immediately while bookkeeping settles in the background
    (Codex-style "ack first, settle later"). The task set keeps a strong
    reference so the loop cannot GC the work mid-flight; use
    ``wait_live_background_tasks`` in tests to drain it.
    """
    task = asyncio.create_task(coro, name=f"{label}:{thread_id}")
    _LIVE_BACKGROUND_TASKS.add(task)

    def _done(done: asyncio.Task[None]) -> None:
        _LIVE_BACKGROUND_TASKS.discard(done)
        if not done.cancelled() and done.exception() is not None:
            _logger.error(
                "[live] background task %s failed thread_id=%s: %s",
                label,
                thread_id,
                done.exception(),
            )

    task.add_done_callback(_done)
    return task


async def wait_live_background_tasks() -> None:
    """Wait for spawned background finalizers (test/introspection hook)."""
    while True:
        pending = [t for t in tuple(_LIVE_BACKGROUND_TASKS) if not t.done()]
        if not pending:
            return
        await asyncio.gather(*pending, return_exceptions=True)
