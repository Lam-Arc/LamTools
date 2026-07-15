"""Event protocol types and interfaces."""

import inspect
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from lamtools_core.event.run_item import RunItemEvent, RunItemKind, RunItemStatus
from lamtools_core.event.runtime_projection import (
    DEFAULT_RUNTIME_PREVIEW_CHARS,
    RuntimeProjectionBuffer,
    RuntimeProjectionInput,
    event_model_call_id,
    event_response_index,
    event_run_id,
    raw_tool_call_id_from_payload,
    runtime_fact_to_run_item_events,
    runtime_group_from_event_name,
    runtime_payload_preview,
    runtime_projection_to_run_item_events,
    runtime_summary_from_event_name,
    tool_args_from_payload,
    tool_call_id_from_payload,
    usage_tokens,
    visible_runtime_part_content,
)

EventCategory = Literal[
    "lifecycle",
    "progress",
    "message",
    "tool",
    "decision",
    "verification",
    "artifact",
    "error",
]

EventTag = Literal[
    "reply",
    "tool",
    "artifact",
    "decision",
    "progress",
    "state",
    "error",
    "done",
    "debug",
]


def _new_event_id() -> str:
    return uuid.uuid4().hex[:16]


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class CoreEvent:
    name: str
    category: EventCategory
    payload: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=_new_event_id)
    session_id: str = ""
    run_id: str = ""
    turn_id: str = ""
    sequence: int | None = None
    timestamp_ms: int = field(default_factory=_now_ms)
    source: str = ""
    correlation_id: str = ""
    tags: list[EventTag] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "category": self.category,
            "payload": self.payload,
            "event_id": self.event_id,
            "timestamp_ms": self.timestamp_ms,
        }
        if self.session_id:
            d["session_id"] = self.session_id
        if self.run_id:
            d["run_id"] = self.run_id
        if self.turn_id:
            d["turn_id"] = self.turn_id
        if self.sequence is not None:
            d["sequence"] = self.sequence
        if self.source:
            d["source"] = self.source
        if self.correlation_id:
            d["correlation_id"] = self.correlation_id
        if self.tags:
            d["tags"] = self.tags
        if self.metadata:
            d["metadata"] = self.metadata
        return d


@runtime_checkable
class EventSink(Protocol):
    async def emit(self, event: CoreEvent) -> None: ...


@runtime_checkable
class EventEmitter(Protocol):
    def on(self, name: str, handler: Any) -> None: ...
    async def emit(self, event: CoreEvent) -> None: ...


@runtime_checkable
class EventLog(Protocol):
    def append(self, event: CoreEvent) -> str: ...
    def replay_since(self, event_id: str | None = None, tail: int = 0) -> list[tuple[str, CoreEvent]]: ...


class InMemoryEventLog:
    def __init__(self) -> None:
        self._events: list[tuple[str, CoreEvent]] = []

    def append(self, event: CoreEvent) -> str:
        self._events.append((event.event_id, event))
        return event.event_id

    def replay_since(self, event_id: str | None = None, tail: int = 0) -> list[tuple[str, CoreEvent]]:
        if tail > 0:
            return self._events[-tail:]
        if event_id is None:
            return list(self._events)
        for i, (eid, _) in enumerate(self._events):
            if eid == event_id:
                return list(self._events[i + 1 :])
        return list(self._events)

    def clear(self) -> None:
        self._events.clear()


class CollectingEventSink:
    """In-memory ``EventSink`` that stores events and optionally forwards them."""

    def __init__(
        self,
        live_callback: Any | None = None,
        should_collect: Any | None = None,
    ) -> None:
        self._events: list[CoreEvent] = []
        self._live_callback = live_callback
        self._should_collect = should_collect

    async def emit(self, event: CoreEvent) -> None:
        if self._should_collect is None or self._should_collect(event):
            self._events.append(event)
        if self._live_callback is None:
            return
        result = self._live_callback(event)
        if inspect.isawaitable(result):
            await result

    @property
    def events(self) -> list[CoreEvent]:
        return list(self._events)

    def clear(self) -> None:
        self._events.clear()


__all__ = [
    "EventCategory",
    "EventTag",
    "CoreEvent",
    "EventSink",
    "EventEmitter",
    "EventLog",
    "InMemoryEventLog",
    "CollectingEventSink",
    "RunItemEvent",
    "RunItemKind",
    "RunItemStatus",
    "DEFAULT_RUNTIME_PREVIEW_CHARS",
    "RuntimeProjectionBuffer",
    "RuntimeProjectionInput",
    "event_model_call_id",
    "event_response_index",
    "event_run_id",
    "raw_tool_call_id_from_payload",
    "runtime_fact_to_run_item_events",
    "runtime_group_from_event_name",
    "runtime_payload_preview",
    "runtime_projection_to_run_item_events",
    "runtime_summary_from_event_name",
    "tool_args_from_payload",
    "tool_call_id_from_payload",
    "usage_tokens",
    "visible_runtime_part_content",
]
