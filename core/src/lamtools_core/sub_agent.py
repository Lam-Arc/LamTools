from __future__ import annotations

import inspect
import re
import time
import uuid

from lamtools_core.event import CoreEvent, EventSink


def normalize_sub_session_agent_name(agent_name: str | None) -> str:
    """Canonical member name used in child session ids and tool routing."""
    value = str(agent_name or "").strip().lower().replace(" ", "_").replace("-", "_")
    value = re.sub(r"[^a-z0-9_]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "sub"


class CallableEventSink:
    """Adapt a plain event callback to the ``EventSink`` protocol."""

    def __init__(self, callback: Any) -> None:
        self._callback = callback

    async def emit(self, event: CoreEvent) -> None:
        result = self._callback(event)
        if inspect.isawaitable(result):
            await result


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
        type: str = "",
        model_id: str = "",
        reasoning_level: str = "",
        started_at: float | None = None,
        invocation_id: str = "",
        parent_source_provider: Any = None,
    ) -> None:
        self._parent_sink = (
            CallableEventSink(parent_sink)
            if parent_sink is not None
            and not callable(getattr(parent_sink, "emit", None))
            and callable(parent_sink)
            else parent_sink
        )
        self._parent_session_id = parent_session_id
        self._agent = agent
        self._task = task
        self._parent_call_id = parent_call_id
        self._parent_run_id = parent_run_id
        self._parent_turn_id = parent_turn_id
        self._type = type
        self._model_id = model_id
        self._reasoning_level = reasoning_level
        self._started_at = started_at or time.time()
        # A continuation of an existing child run reuses that run's scope so its
        # events update the items the run already created (an answered question
        # resolves the card that asked it instead of orphaning it).
        self._invocation_id = str(invocation_id or "").strip() or uuid.uuid4().hex
        # 谁算这次子代理输出的“来源指令”：父代理运行中途补的指令由内核在下一个
        # 步边界消化，之后产生的事件属于那条补充的调用行，而不是本回合开头那条。
        self._parent_source_provider = parent_source_provider

    @property
    def invocation_id(self) -> str:
        return self._invocation_id

    def _follow_delivery_source(self) -> None:
        """Follow the instruction the child is working on right now.

        user:“修”+(补充消息被消化后，子代理后续事件必须归属到这条补充的调用行：
        界面按 ``sub_agent.parent_call_id`` 认亲，归属不切换就会把补充画在它触发的
        输出后面，读起来像父代理在事后补充)。
        """
        provider = self._parent_source_provider
        if provider is None:
            return
        try:
            source = provider()
        except Exception:  # noqa: BLE001 — 归属只是记账，绝不能吞掉子代理事件
            return
        if isinstance(source, dict):
            call_id = str(source.get("call_id") or source.get("parent_call_id") or "")
            run_id = str(source.get("run_id") or source.get("parent_run_id") or "")
            turn_id = str(source.get("turn_id") or source.get("parent_turn_id") or "")
        elif isinstance(source, (tuple, list)) and len(source) >= 3:
            call_id, run_id, turn_id = (str(value or "") for value in source[:3])
        else:
            return
        if not call_id:
            return
        self._parent_call_id = call_id
        self._parent_run_id = run_id or self._parent_run_id
        self._parent_turn_id = turn_id or self._parent_turn_id

    async def emit(self, event: CoreEvent) -> None:
        # Events are forwarded, not retained. The previous buffer appended
        # every child delta and was never read, so a long child duplicated its
        # entire stream in memory for the duration of the run.
        if self._parent_sink is None or not _is_visible_child_event(event):
            return
        self._follow_delivery_source()
        payload = dict(event.payload or {})
        payload["sub_agent"] = {
            "agent": self._agent,
            "name": self._agent,
            "type": self._type,
            "task": self._task,
            "summary": str(payload.get("summary") or payload.get("content") or "")[:1000],
            "status": str(payload.get("status") or event.name.removeprefix("runtime.")),
            "session_id": event.session_id,
            "sub_session_id": event.session_id,
            "run_id": event.run_id,
            "invocation_id": self._invocation_id,
            "model_id": self._model_id,
            "reasoning_level": self._reasoning_level,
            "started_at": self._started_at,
            "completed_at": time.time() if event.name in {"runtime.done", "runtime.failed", "runtime.cancelled"} else None,
            "elapsed_ms": int((time.time() - self._started_at) * 1000),
            "parent_item_key": f"{self._parent_session_id}:sub:{self._agent}",
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
        "deliverables/presented",
    }:
        return True
    return event.name == "runtime.part"


__all__ = ["CallableEventSink", "SubAgentEventForwardingSink", "normalize_sub_session_agent_name"]
