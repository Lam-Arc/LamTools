from __future__ import annotations

from lamtools_core.event import CoreEvent, EventSink


class SubAgentEventForwardingSink:
    """Collect child events and expose its visible process on the parent timeline."""

    def __init__(
        self,
        *,
        parent_sink: EventSink | None,
        parent_session_id: str,
        agent: str,
        task: str,
        parent_call_id: str = "",
        parent_run_id: str = "",
        parent_turn_id: str = "",
    ) -> None:
        self._parent_sink = parent_sink
        self._parent_session_id = parent_session_id
        self._agent = agent
        self._task = task
        self._parent_call_id = parent_call_id
        self._parent_run_id = parent_run_id
        self._parent_turn_id = parent_turn_id
        self._events: list[CoreEvent] = []

    @property
    def events(self) -> list[CoreEvent]:
        return list(self._events)

    async def emit(self, event: CoreEvent) -> None:
        self._events.append(event)
        if self._parent_sink is None or not _is_visible_child_event(event):
            return
        payload = dict(event.payload or {})
        payload["sub_agent"] = {
            "agent": self._agent,
            "task": self._task,
            "session_id": event.session_id,
            "run_id": event.run_id,
            "parent_call_id": self._parent_call_id,
            "parent_run_id": self._parent_run_id,
            "parent_turn_id": self._parent_turn_id,
        }
        await self._parent_sink.emit(CoreEvent(
            name=event.name,
            category=event.category,
            payload=payload,
            session_id=self._parent_session_id or event.session_id,
            run_id=self._parent_run_id or event.run_id,
            turn_id=self._parent_turn_id or event.turn_id,
            sequence=event.sequence,
            source="sub_agent",
            correlation_id=event.correlation_id,
            tags=list(event.tags),
            metadata={**dict(event.metadata or {}), "sub_agent": payload["sub_agent"]},
        ))


def _is_visible_child_event(event: CoreEvent) -> bool:
    if event.name in {
        "runtime.reply_delta",
        "runtime.tool.started",
        "runtime.tool.finished",
        "runtime.approval_request",
        "runtime.approval_response",
        "runtime.waiting",
        "runtime.done",
        "runtime.failed",
        "runtime.cancelled",
        "runtime.usage",
        "runtime.metrics",
    }:
        return True
    return event.name == "runtime.part"


__all__ = ["SubAgentEventForwardingSink"]
