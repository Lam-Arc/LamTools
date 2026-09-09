"""Per-session serialization for live workspace mutations.

The actor is deliberately small: SQLite remains the durable source of truth,
while this registry gives one Core process a single ordering point for live
commands that touch the same session. It does not queue Agent turns; the turn
runtime registry still rejects a second active turn explicitly.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar


T = TypeVar("T")


class SessionActorBusyError(RuntimeError):
    """Raised when a caller asks for a non-queued session mutation."""

    def __init__(self, thread_id: str) -> None:
        self.thread_id = str(thread_id)
        super().__init__(f"Session actor is busy: {self.thread_id}")


@dataclass
class _SessionActor:
    lock: asyncio.Lock
    users: int = 0


class SessionActorRegistry:
    """Serialize short live mutations by ``thread_id``."""

    def __init__(self) -> None:
        self._actors: dict[str, _SessionActor] = {}
        self._registry_lock = asyncio.Lock()

    async def _actor_for(self, thread_id: str) -> _SessionActor:
        async with self._registry_lock:
            actor = self._actors.get(thread_id)
            if actor is None:
                actor = _SessionActor(lock=asyncio.Lock())
                self._actors[thread_id] = actor
            actor.users += 1
            return actor

    async def _release_actor(self, thread_id: str, actor: _SessionActor) -> None:
        async with self._registry_lock:
            actor.users = max(0, actor.users - 1)
            if actor.users == 0 and not actor.lock.locked():
                self._actors.pop(thread_id, None)

    async def run(self, thread_id: str, operation: Callable[[], Awaitable[T]]) -> T:
        normalized = str(thread_id or "").strip()
        if not normalized:
            return await operation()
        actor = await self._actor_for(normalized)
        try:
            async with actor.lock:
                return await operation()
        finally:
            await self._release_actor(normalized, actor)

    async def try_run(self, thread_id: str, operation: Callable[[], Awaitable[T]]) -> T:
        """Run a short mutation without waiting behind another mutation.

        The actor lock is checked and acquired without an intervening await,
        so two callers on the same event loop cannot both pass the check.  A
        caller that loses the race gets a structured busy error at the live
        protocol boundary instead of sitting behind a possibly slow command.
        """

        normalized = str(thread_id or "").strip()
        if not normalized:
            return await operation()
        actor = await self._actor_for(normalized)
        if actor.lock.locked():
            await self._release_actor(normalized, actor)
            raise SessionActorBusyError(normalized)
        await actor.lock.acquire()
        try:
            return await operation()
        finally:
            actor.lock.release()
            await self._release_actor(normalized, actor)

    async def close(self) -> None:
        """Drop idle actor metadata during application shutdown."""

        async with self._registry_lock:
            self._actors = {
                thread_id: actor
                for thread_id, actor in self._actors.items()
                if actor.lock.locked() or actor.users > 0
            }


__all__ = ["SessionActorBusyError", "SessionActorRegistry"]
