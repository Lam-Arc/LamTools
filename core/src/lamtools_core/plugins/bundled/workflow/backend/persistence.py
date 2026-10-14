"""Failure contract for required Workflow durability, distinct from UI delivery."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from pathlib import Path
from typing import TypeVar


class WorkflowPersistenceError(RuntimeError):
    code = "WORKFLOW_PERSISTENCE_FAILED"

    def __init__(self, operation: str, path: Path, cause: Exception) -> None:
        self.operation = operation
        self.path = path
        self.queue_id = ""
        self.run_id = ""
        super().__init__(f"Workflow persistence failed ({operation}): {cause}")


T = TypeVar("T")


async def finish_commit(commit: Awaitable[T]) -> T:
    """Hold the caller's store lock until its commit settles, even on cancellation.

    Cancelling to_thread does not stop a filesystem write. Let the transaction
    publish or roll back its cache before releasing the lock to another writer.
    """
    task = asyncio.ensure_future(commit)
    cancelled = False
    while True:
        try:
            result = await asyncio.shield(task)
            break
        except asyncio.CancelledError:
            if task.cancelled():
                raise
            cancelled = True
    if cancelled:
        raise asyncio.CancelledError
    return result
