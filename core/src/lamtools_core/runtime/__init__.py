"""Runtime protocol types and interfaces."""

import asyncio
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from lamtools_core.llm import LLMResponse
from lamtools_core.tool import ToolCall, ToolResult
from lamtools_core.event import CoreEvent

RuntimeStatus = Literal["idle", "running", "waiting", "completed", "failed", "cancelled"]
RuntimeLoopState = Literal["continue", "wait", "done", "failed"]


@dataclass
class RuntimeState:
    session_id: str
    run_id: str = ""
    status: RuntimeStatus = "idle"
    position: str = ""
    loop_state: RuntimeLoopState = "continue"
    turn_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "session_id": self.session_id,
            "run_id": self.run_id,
            "status": self.status,
            "position": self.position,
            "loop_state": self.loop_state,
            "turn_count": self.turn_count,
        }
        if self.metadata:
            d["metadata"] = self.metadata
        return d


@dataclass
class RuntimeToolStep:
    call: ToolCall
    result: ToolResult | None = None
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"call": self.call.to_dict()}
        if self.result is not None:
            d["result"] = self.result.to_dict()
        if self.error:
            d["error"] = self.error
        return d


@dataclass
class RuntimeTurnInput:
    user_message: str = ""
    user_content: str | list[dict[str, Any]] | None = None
    state: RuntimeState | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"user_message": self.user_message}
        if self.user_content is not None:
            d["user_content"] = self.user_content
        if self.state is not None:
            d["state"] = self.state.to_dict()
        return d


@dataclass
class RuntimeTurnResult:
    message: str = ""
    loop_state: RuntimeLoopState = "continue"
    complete: bool = False
    needs_user_input: bool = False
    model_response: LLMResponse | None = None
    tool_steps: list[RuntimeToolStep] = field(default_factory=list)
    events: list[CoreEvent] = field(default_factory=list)
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "message": self.message,
            "loop_state": self.loop_state,
            "complete": self.complete,
            "needs_user_input": self.needs_user_input,
        }
        if self.model_response is not None:
            d["model_response"] = self.model_response.to_dict()
        if self.tool_steps:
            d["tool_steps"] = [s.to_dict() for s in self.tool_steps]
        if self.error:
            d["error"] = self.error
        return d


@dataclass
class CompletionCheck:
    name: str
    passed: bool
    output: str = ""
    skipped: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "output": self.output,
            "skipped": self.skipped,
        }


@dataclass
class CompletionResult:
    passed: bool
    summary: str
    checks: list[CompletionCheck] = field(default_factory=list)
    repair_instruction: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "summary": self.summary,
            "checks": [c.to_dict() for c in self.checks],
            "repair_instruction": self.repair_instruction,
        }


@runtime_checkable
class RuntimeStateStore(Protocol):
    async def get(self, session_id: str) -> RuntimeState | None: ...
    async def save(self, state: RuntimeState) -> None: ...


class InMemoryRuntimeStateStore:
    """Simple in-memory ``RuntimeStateStore`` implementation."""

    def __init__(self) -> None:
        self._states: dict[str, RuntimeState] = {}

    async def get(self, session_id: str) -> RuntimeState | None:
        return self._states.get(session_id)

    async def save(self, state: RuntimeState) -> None:
        self._states[state.session_id] = state

    def clear(self) -> None:
        self._states.clear()


class RuntimeTaskRegistry:
    """Track active runtime tasks and cooperative cancellation signals."""

    def __init__(self) -> None:
        self._tasks: dict[str, tuple[str, asyncio.Task[Any]]] = {}
        self._cancel_events: dict[str, asyncio.Event] = {}

    def get_cancel_event(self, thread_id: str) -> asyncio.Event:
        if thread_id not in self._cancel_events:
            self._cancel_events[thread_id] = asyncio.Event()
        return self._cancel_events[thread_id]

    def reset_cancel_event(self, thread_id: str) -> asyncio.Event:
        event = self.get_cancel_event(thread_id)
        event.clear()
        return event

    def register(self, thread_id: str, task: asyncio.Task[Any], *, run_id: str = "") -> None:
        self._tasks[thread_id] = (run_id, task)

        def _cleanup(done_task: asyncio.Task[Any]) -> None:
            entry = self._tasks.get(thread_id)
            if entry is not None and entry[0] == run_id and entry[1] is done_task:
                self._tasks.pop(thread_id, None)

        task.add_done_callback(_cleanup)

    def task(self, thread_id: str, *, run_id: str | None = None) -> asyncio.Task[Any] | None:
        entry = self._tasks.get(thread_id)
        if entry is None:
            return None
        active_run_id, task = entry
        if task.done():
            self._tasks.pop(thread_id, None)
            return None
        if run_id is not None and active_run_id != run_id:
            return None
        return task

    def cancel(self, thread_id: str, *, run_id: str | None = None, force: bool = False) -> None:
        task = self.task(thread_id, run_id=run_id)
        if run_id is not None and task is None:
            return
        self.get_cancel_event(thread_id).set()
        if not force:
            return
        if task is not None and not task.done():
            task.cancel()

    def is_running(self, thread_id: str, *, run_id: str | None = None) -> bool:
        return self.task(thread_id, run_id=run_id) is not None

    def clear(self) -> None:
        self._tasks.clear()
        self._cancel_events.clear()


_DEFAULT_TASK_REGISTRY = RuntimeTaskRegistry()


def default_runtime_task_registry() -> RuntimeTaskRegistry:
    return _DEFAULT_TASK_REGISTRY


@runtime_checkable
class CompletionGate(Protocol):
    async def verify(self, state: RuntimeState, context: dict[str, Any]) -> CompletionResult: ...


@runtime_checkable
class RuntimeDriver(Protocol):
    async def run(self, state: RuntimeState, user_message: str) -> RuntimeTurnResult: ...


__all__ = [
    "RuntimeStatus",
    "RuntimeLoopState",
    "RuntimeState",
    "RuntimeToolStep",
    "RuntimeTurnInput",
    "RuntimeTurnResult",
    "CompletionCheck",
    "CompletionResult",
    "RuntimeStateStore",
    "InMemoryRuntimeStateStore",
    "RuntimeTaskRegistry",
    "default_runtime_task_registry",
    "CompletionGate",
    "RuntimeDriver",
]
