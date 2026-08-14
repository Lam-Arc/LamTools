"""Runtime event record types and in-memory store."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable


def _new_event_id() -> str:
    return uuid.uuid4().hex[:16]


@dataclass
class RuntimeEventRecord:
    """A single runtime event logged during a session / run."""

    id: str
    session_id: str
    name: str
    category: str
    payload: dict[str, Any] = field(default_factory=dict)
    run_id: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    sequence: int = 0

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "session_id": self.session_id,
            "name": self.name,
            "category": self.category,
            "payload": self.payload,
            "created_at": self.created_at.isoformat(),
        }
        if self.run_id:
            d["run_id"] = self.run_id
        if self.sequence:
            d["sequence"] = self.sequence
        return d


@runtime_checkable
class RuntimeEventStore(Protocol):
    """Protocol for storing and querying runtime event records."""

    def append(self, event: RuntimeEventRecord) -> str:
        """Persist an event record and return its id."""
        ...

    def list(
        self,
        session_id: str | None = None,
        run_id: str | None = None,
    ) -> list[RuntimeEventRecord]:
        """Return events ordered by sequence, optionally filtered by session / run."""
        ...

    def clear(self, session_id: str | None = None) -> None:
        """Clear all events, or only those for a specific session."""
        ...


class InMemoryRuntimeEventStore:
    """Simple in-memory implementation of RuntimeEventStore."""

    def __init__(self) -> None:
        self._events: list[RuntimeEventRecord] = []
        # Monotonic high-water mark for sequence allocation. Deriving the next
        # sequence from len(self._events) alone is wrong after the hub trims
        # old events: kept records retain their original (high) sequences while
        # the list shrinks, so the next append would collide with a kept
        # record's sequence and go backwards (audit 07: replay/cursor
        # consumers break on non-monotonic sequences).
        self._max_sequence = 0

    def _next_sequence(self) -> int:
        return self._max_sequence + 1

    def append(self, event: RuntimeEventRecord) -> str:
        if event.sequence == 0:
            event.sequence = self._next_sequence()
        if event.sequence > self._max_sequence:
            self._max_sequence = event.sequence
        self._events.append(event)
        return event.id

    def list(
        self,
        session_id: str | None = None,
        run_id: str | None = None,
    ) -> list[RuntimeEventRecord]:
        result = list(self._events)
        if session_id is not None:
            result = [e for e in result if e.session_id == session_id]
        if run_id is not None:
            result = [e for e in result if e.run_id == run_id]
        result.sort(key=lambda e: e.sequence)
        return result

    def clear(self, session_id: str | None = None) -> None:
        if session_id is None:
            self._events.clear()
        else:
            self._events = [
                e for e in self._events if e.session_id != session_id
            ]


__all__ = [
    "RuntimeEventRecord",
    "RuntimeEventStore",
    "InMemoryRuntimeEventStore",
    "RuntimeEventHub",
]

from .hub import RuntimeEventHub
