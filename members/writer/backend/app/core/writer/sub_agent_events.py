from __future__ import annotations

from typing import Any, Awaitable, Callable

from lamtools_core.event import CoreEvent

from app.core.writer.agent_types import AgentCall


class SubAgentEventForwardingSink:
    def __init__(
        self,
        *,
        event_log: Any,
        core_event_callback: Callable[[CoreEvent], Awaitable[None]] | None,
        agent_name: str,
        call: AgentCall,
    ) -> None:
        self._event_log = event_log
        self._core_event_callback = core_event_callback
        self._agent_name = agent_name
        self._call = call
        self._sub_line_id = str(call.options.get("_sub_line_id") or "")
        self._agent_run_id = str(call.options.get("_agent_run_id") or "")

    async def emit(self, event: CoreEvent) -> None:
        self._event_log.append(event)
        if event.name == "runtime.approval_request":
            return
        await self.forward(event)

    async def forward(self, event: CoreEvent) -> None:
        if self._core_event_callback is None:
            return
        if event.name not in {
            "runtime.part",
            "runtime.tool.started",
            "runtime.tool.finished",
            "runtime.approval_request",
        }:
            return
        payload = dict(event.payload or {})
        payload["sub_agent"] = {
            "sub_line_id": self._sub_line_id,
            "agent_run_id": self._agent_run_id,
            "agent": self._agent_name,
            "task": self._call.task,
        }
        if self._sub_line_id:
            payload["sub_line_id"] = self._sub_line_id
        if self._agent_run_id:
            payload["agent_run_id"] = self._agent_run_id
        await self._core_event_callback(CoreEvent(
            name=event.name,
            category=event.category,
            payload=payload,
            session_id=str(self._call.options.get("_parent_session_id") or event.session_id),
            run_id=str(self._call.options.get("_parent_run_id") or event.run_id),
            turn_id=event.turn_id,
            sequence=event.sequence,
            source="sub_agent",
            correlation_id=event.correlation_id,
            tags=list(event.tags),
            metadata=dict(event.metadata or {}),
        ))
