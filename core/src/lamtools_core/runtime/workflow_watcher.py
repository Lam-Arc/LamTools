"""Background file-watcher for workflow definition folders.

Polls the :class:`~lamtools_core.project.workflow_store.WorkflowStore` mtime
signature on a timer and broadcasts a ``workflow/changed`` event through the
app event hub when an external edit is detected, so connected canvases refresh
automatically.

The poll loop mirrors :class:`~lamtools_core.runtime.observe.ObserverSupervisor`:
``asyncio.create_task`` + ``asyncio.wait_for(wake.wait(), timeout)``. No
``watchdog``/inotify dependency — consistent with the rest of the codebase.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class WorkflowFileWatcher:
    """Polls workflow store signatures and broadcasts change events."""

    def __init__(
        self,
        store: Any,
        hub: Any,
        *,
        poll_interval: float = 2.0,
        work_roots: list[str] | None = None,
    ) -> None:
        self._store = store
        self._hub = hub
        self._poll_interval = max(0.1, poll_interval)
        self._work_roots: list[str] = [r for r in (work_roots or []) if r]
        # work_root → last signature (None = first poll, no broadcast).
        self._sigs: dict[str, Any] = {}
        self._wake = asyncio.Event()
        self._stopping = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def add_work_root(self, work_root: str) -> None:
        """Register an additional work_root to watch (idempotent)."""
        if work_root and work_root not in self._work_roots:
            self._work_roots.append(work_root)
            self._wake.set()

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stopping.clear()
        self._task = asyncio.create_task(self._run(), name="workflow-file-watcher")

    async def stop(self) -> None:
        self._stopping.set()
        self._wake.set()
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def wake(self) -> None:
        """Trigger an immediate poll."""
        self._wake.set()

    async def _run(self) -> None:
        while not self._stopping.is_set():
            self._wake.clear()
            try:
                await self._poll_once()
            except Exception:  # noqa: BLE001 — watcher must never crash the app
                logger.exception("workflow file watcher poll failed")
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self._poll_interval)
            except TimeoutError:
                pass

    async def _poll_once(self) -> None:
        roots = list(self._work_roots) or [""]
        for work_root in roots:
            key = work_root or ""
            try:
                sig = await asyncio.to_thread(self._store._signature, work_root or None)
            except Exception:  # noqa: BLE001
                continue
            prev = self._sigs.get(key)
            self._sigs[key] = sig
            if prev is not None and prev != sig:
                logger.debug("workflow store changed in %s", key or "<global>")
                await self._hub.broadcast({
                    "method": "workflow/changed",
                    "thread_id": "",
                    "payload": {"work_root": key},
                })
