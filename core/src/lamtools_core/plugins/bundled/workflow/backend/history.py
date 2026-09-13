"""Read/clear facade for durable Workflow run history.

The queue owns writes so history and queue views cannot diverge.  This small
facade keeps the responsibilities explicit for hosts that only need to inspect
or prune terminal runs.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .queue import TERMINAL_STATUSES, WorkflowQueueItem, WorkflowQueueStore


class WorkflowRunHistory:
    def __init__(self, store: WorkflowQueueStore | None = None, *, root: str | Path | None = None, data_dir: str | Path | None = None) -> None:
        self.store = store or WorkflowQueueStore(root=root, data_dir=data_dir)

    async def list(
        self,
        *,
        status: str | Iterable[str] | None = None,
        workflow_id: str = "",
        workflow_name: str = "",
        work_root: str | Path | None = None,
        limit: int | None = None,
        include_active: bool = False,
    ) -> list[WorkflowQueueItem]:
        values = await self.store.values()
        statuses = {str(item) for item in status} if isinstance(status, (list, tuple, set, frozenset)) else ({str(status)} if status else None)
        root = str(Path(work_root).expanduser().resolve()) if work_root else ""
        values = [
            item for item in values
            if (statuses is None or item.status in statuses)
            and (include_active or item.status in TERMINAL_STATUSES or item.status == "paused")
            and (not workflow_id or item.workflow_id == workflow_id)
            and (not workflow_name or item.workflow_name == workflow_name)
            and (not root or _same_root(item.work_root, root))
        ]
        values.sort(key=lambda item: (item.created_at, item.queue_id))
        if limit is not None and limit >= 0:
            values = values[:limit]
        return values

    async def get(self, queue_id: str = "", *, run_id: str = "") -> WorkflowQueueItem | None:
        values = await self.store.values()
        for item in values:
            if queue_id and item.queue_id == queue_id:
                return item
            if run_id and item.run_id == run_id:
                return item
        return None

    async def clear(
        self,
        *,
        confirm: bool = False,
        all_items: bool = False,
        workflow_id: str = "",
        workflow_name: str = "",
    ) -> int:
        if not confirm:
            raise ValueError("clearing workflow history requires confirm=True")
        return await self.store.clear(
            confirm=True,
            predicate=lambda item: (
                (all_items or item.status in TERMINAL_STATUSES)
                and (not workflow_id or item.workflow_id == workflow_id)
                and (not workflow_name or item.workflow_name == workflow_name)
            ),
        )


WorkflowHistory = WorkflowRunHistory


def _same_root(value: str, root: str) -> bool:
    try:
        return Path(value).expanduser().resolve() == Path(root).expanduser().resolve()
    except OSError:
        return str(value) == str(root)


__all__ = ["WorkflowHistory", "WorkflowRunHistory"]
