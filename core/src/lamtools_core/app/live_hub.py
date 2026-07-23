from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Any


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CoreAppEventGap:
    thread_id: str
    reason: str = "subscriber_overflow"


class CoreAppEventHub:
    def __init__(self, *, queue_size: int = 256) -> None:
        self._queue_size = queue_size
        self._subscribers: dict[str, set[asyncio.Queue[Any | None]]] = defaultdict(set)

    def subscribe(self, thread_id: str) -> asyncio.Queue[Any | None]:
        queue: asyncio.Queue[Any | None] = asyncio.Queue(maxsize=self._queue_size)
        self._subscribers[thread_id].add(queue)
        return queue

    def unsubscribe(self, thread_id: str, queue: asyncio.Queue[Any | None]) -> None:
        subscribers = self._subscribers.get(thread_id)
        if not subscribers:
            return
        subscribers.discard(queue)
        if not subscribers:
            self._subscribers.pop(thread_id, None)

    async def publish(self, event: Any) -> None:
        thread_id = str(getattr(event, "thread_id", "") or "")
        if not thread_id and isinstance(event, dict):
            thread_id = str(event.get("thread_id") or "")
        if not thread_id:
            return
        subscribers = list(self._subscribers.get(thread_id, set()))
        for queue in subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(CoreAppEventGap(thread_id=thread_id))
                self.unsubscribe(thread_id, queue)
                logger.warning(
                    "Core app-server subscriber overflow for thread %s; forcing reconnect/resume",
                    thread_id,
                )
        await asyncio.sleep(0)

    async def broadcast(self, event: Any) -> None:
        """Push an event to all connected subscribers regardless of thread_id."""
        for subscribers in self._subscribers.values():
            for queue in list(subscribers):
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    pass  # best-effort for global notifications
        await asyncio.sleep(0)


hub = CoreAppEventHub()


__all__ = ["CoreAppEventGap", "CoreAppEventHub", "hub"]
