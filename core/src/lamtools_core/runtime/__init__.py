"""Runtime protocol types and interfaces."""

import asyncio
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Protocol, runtime_checkable

from lamtools_core.llm import LLMResponse
from lamtools_core.tool import ToolCall, ToolResult
from lamtools_core.event import CoreEvent
from .background_processes import (
    BackgroundProcessRegistry,
    default_background_process_registry,
)
from .plan import (
    apply_checklist_update,
    auto_advance_plan,
    find_plan_step,
    format_checklist_markdown,
    has_delivery_progress,
    new_plan_revision,
    normalize_checklist_steps,
    plan_is_completed,
    plan_to_active_plan,
    start_next_pending_step,
)

RuntimeStatus = Literal["idle", "running", "waiting", "completed", "failed", "cancelled"]
RuntimeLoopState = Literal["continue", "wait", "done", "failed"]


class RuntimeStateConflictError(RuntimeError):
    pass


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
    run_id: str = ""
    turn_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    guidance_source: Callable[[], list[str]] | None = field(default=None, repr=False, compare=False)
    guidance_finalizer: Callable[[], list[str] | None] | None = field(default=None, repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"user_message": self.user_message}
        if self.user_content is not None:
            d["user_content"] = self.user_content
        if self.state is not None:
            d["state"] = self.state.to_dict()
        if self.run_id:
            d["run_id"] = self.run_id
        if self.turn_id:
            d["turn_id"] = self.turn_id
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
    blocked: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "summary": self.summary,
            "checks": [c.to_dict() for c in self.checks],
            "repair_instruction": self.repair_instruction,
            "blocked": self.blocked,
        }


@runtime_checkable
class RuntimeStateStore(Protocol):
    async def get(self, session_id: str) -> RuntimeState | None: ...
    async def save(self, state: RuntimeState) -> None: ...


@runtime_checkable
class RuntimeCheckpointStore(RuntimeStateStore, Protocol):
    async def get_history(self, session_id: str) -> list[dict[str, Any]]: ...
    async def save_checkpoint(self, state: RuntimeState, history: list[dict[str, Any]]) -> None: ...


@runtime_checkable
class RuntimeApprovalStore(RuntimeStateStore, Protocol):
    async def find_pending_approval(self, request_id: str) -> RuntimeState | None: ...


class InMemoryRuntimeStateStore:
    """Simple in-memory ``RuntimeStateStore`` implementation."""

    def __init__(self) -> None:
        self._states: dict[str, RuntimeState] = {}
        self._history: dict[str, list[dict[str, Any]]] = {}

    async def get(self, session_id: str) -> RuntimeState | None:
        return self._states.get(session_id)

    async def save(self, state: RuntimeState) -> None:
        self._states[state.session_id] = state

    async def get_history(self, session_id: str) -> list[dict[str, Any]]:
        return deepcopy(self._history.get(session_id, []))

    async def save_checkpoint(self, state: RuntimeState, history: list[dict[str, Any]]) -> None:
        self._states[state.session_id] = state
        self._history[state.session_id] = list(history)

    async def find_pending_approval(self, request_id: str) -> RuntimeState | None:
        for state in self._states.values():
            pending = state.metadata.get("pending_approval") if isinstance(state.metadata, dict) else None
            tool_call = pending.get("tool_call") if isinstance(pending, dict) else None
            pending_request_id = pending.get("request_id") if isinstance(pending, dict) else None
            tool_call_id = tool_call.get("id") if isinstance(tool_call, dict) else None
            if request_id in {str(pending_request_id or ""), str(tool_call_id or "")}:
                return state
        return None

    def clear(self) -> None:
        self._states.clear()
        self._history.clear()


@dataclass
class _RuntimeTaskEntry:
    run_id: str
    task: asyncio.Task[Any] | None = None
    guidance_open: bool = True
    guidance: list[tuple[str, str]] = field(default_factory=list)
    guidance_ids: set[str] = field(default_factory=set)


class RuntimeTaskRegistry:
    """Track active runtime tasks, cancellation signals, and transient guidance."""

    def __init__(self, *, background_process_registry: BackgroundProcessRegistry | None = None) -> None:
        self._entries: dict[str, _RuntimeTaskEntry] = {}
        self._cancel_events: dict[str, asyncio.Event] = {}
        self._background_process_registry = (
            background_process_registry or default_background_process_registry()
        )

    def get_cancel_event(self, thread_id: str) -> asyncio.Event:
        if thread_id not in self._cancel_events:
            self._cancel_events[thread_id] = asyncio.Event()
        return self._cancel_events[thread_id]

    def reset_cancel_event(self, thread_id: str) -> asyncio.Event:
        event = self.get_cancel_event(thread_id)
        event.clear()
        return event

    def accept_run(self, thread_id: str, run_id: str) -> bool:
        thread_id = str(thread_id or "").strip()
        run_id = str(run_id or "").strip()
        if not thread_id or not run_id:
            return False
        self._drop_done_entry(thread_id)
        entry = self._entries.get(thread_id)
        if entry is not None:
            return entry.run_id == run_id
        self.reset_cancel_event(thread_id)
        self._entries[thread_id] = _RuntimeTaskEntry(run_id=run_id)
        return True

    def active_run_id(self, thread_id: str) -> str | None:
        self._drop_done_entry(thread_id)
        entry = self._entries.get(thread_id)
        return entry.run_id if entry is not None else None

    def register(self, thread_id: str, task: asyncio.Task[Any], *, run_id: str = "") -> bool:
        self._drop_done_entry(thread_id)
        entry = self._entries.get(thread_id)
        if entry is None:
            if not self.accept_run(thread_id, run_id):
                return False
            entry = self._entries[thread_id]
        if entry.run_id != run_id:
            return False
        if entry.task is not None and entry.task is not task and not entry.task.done():
            return False
        entry.task = task

        def _cleanup(done_task: asyncio.Task[Any]) -> None:
            current = self._entries.get(thread_id)
            if current is not None and current.run_id == run_id and current.task is done_task:
                self._entries.pop(thread_id, None)
                self._background_process_registry.cleanup_session(thread_id)

        task.add_done_callback(_cleanup)
        return True

    def task(self, thread_id: str, *, run_id: str | None = None) -> asyncio.Task[Any] | None:
        self._drop_done_entry(thread_id)
        entry = self._entries.get(thread_id)
        if entry is None:
            return None
        task = entry.task
        if task is None:
            return None
        if run_id is not None and entry.run_id != run_id:
            return None
        return task

    def cancel(self, thread_id: str, *, run_id: str | None = None, force: bool = False) -> None:
        self._drop_done_entry(thread_id)
        entry = self._entries.get(thread_id)
        if entry is None:
            self.get_cancel_event(thread_id).set()
            self._background_process_registry.cleanup_session(thread_id)
            return
        if run_id is not None and entry.run_id != run_id:
            return
        task = entry.task
        self.get_cancel_event(thread_id).set()
        entry.guidance_open = False
        entry.guidance.clear()
        entry.guidance_ids.clear()
        self._entries.pop(thread_id, None)
        self._background_process_registry.cleanup_session(thread_id)
        if not force:
            return
        if task is not None and not task.done():
            task.cancel()

    def is_running(self, thread_id: str, *, run_id: str | None = None) -> bool:
        return self.task(thread_id, run_id=run_id) is not None

    def accept_guidance(
        self,
        thread_id: str,
        text: str,
        *,
        run_id: str,
        guidance_id: str,
    ) -> Literal["accepted", "duplicate", "closed", "not_active"]:
        self._drop_done_entry(thread_id)
        entry = self._entries.get(thread_id)
        guidance = str(text or "").strip()
        if entry is None or entry.run_id != run_id or entry.task is None or not guidance:
            return "not_active"
        if not entry.guidance_open:
            return "closed"
        normalized_id = str(guidance_id or "").strip()
        if normalized_id and normalized_id in entry.guidance_ids:
            return "duplicate"
        entry.guidance.append((normalized_id, guidance))
        if normalized_id:
            entry.guidance_ids.add(normalized_id)
        return "accepted"

    def inject_guidance(
        self,
        thread_id: str,
        text: str,
        *,
        run_id: str = "",
        guidance_id: str = "",
    ) -> bool:
        """Queue one transient instruction for the matching active runtime task."""
        return self.accept_guidance(
            thread_id,
            text,
            run_id=run_id,
            guidance_id=guidance_id,
        ) in {"accepted", "duplicate"}

    def consume_guidance(self, thread_id: str, *, run_id: str = "") -> list[str]:
        self._drop_done_entry(thread_id)
        entry = self._entries.get(thread_id)
        if entry is None or entry.run_id != run_id or entry.task is None:
            return []
        guidance = [text for _guidance_id, text in entry.guidance]
        entry.guidance.clear()
        return guidance

    def close_guidance_if_empty(self, thread_id: str, *, run_id: str) -> list[str] | None:
        """Atomically consume pending guidance or seal an empty run."""
        self._drop_done_entry(thread_id)
        entry = self._entries.get(thread_id)
        if entry is None or entry.run_id != run_id or entry.task is None:
            return None
        if not entry.guidance_open:
            return []
        if entry.guidance:
            guidance = [text for _guidance_id, text in entry.guidance]
            entry.guidance.clear()
            return guidance
        entry.guidance_open = False
        return []

    def guidance_source(self, thread_id: str, *, run_id: str = "") -> Callable[[], list[str]]:
        return lambda: self.consume_guidance(thread_id, run_id=run_id)

    def guidance_finalizer(self, thread_id: str, *, run_id: str) -> Callable[[], list[str] | None]:
        return lambda: self.close_guidance_if_empty(thread_id, run_id=run_id)

    def retract_guidance(self, thread_id: str, *, run_id: str, guidance_id: str) -> None:
        entry = self._entries.get(thread_id)
        if entry is None or entry.run_id != run_id or not guidance_id:
            return
        pending = [(item_id, text) for item_id, text in entry.guidance if item_id == guidance_id]
        if not pending:
            return
        entry.guidance = [(item_id, text) for item_id, text in entry.guidance if item_id != guidance_id]
        entry.guidance_ids.discard(guidance_id)

    def release_run(self, thread_id: str, *, run_id: str) -> None:
        entry = self._entries.get(thread_id)
        if entry is not None and entry.run_id == run_id:
            self._entries.pop(thread_id, None)
            self._background_process_registry.cleanup_session(thread_id)

    def _drop_done_entry(self, thread_id: str) -> None:
        entry = self._entries.get(thread_id)
        if entry is not None and entry.task is not None and entry.task.done():
            self._entries.pop(thread_id, None)
            self._background_process_registry.cleanup_session(thread_id)

    def clear(self) -> None:
        self._entries.clear()
        self._cancel_events.clear()

    async def shutdown(self) -> None:
        """Cancel and join every tracked task before its event loop is closed."""

        entries = list(self._entries.items())
        tasks = [entry.task for _thread_id, entry in entries if entry.task is not None]
        for thread_id, entry in entries:
            self.cancel(thread_id, run_id=entry.run_id, force=True)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.clear()
        self._background_process_registry.shutdown()


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
    "RuntimeCheckpointStore",
    "RuntimeApprovalStore",
    "RuntimeStateConflictError",
    "InMemoryRuntimeStateStore",
    "RuntimeTaskRegistry",
    "BackgroundProcessRegistry",
    "default_background_process_registry",
    "default_runtime_task_registry",
    "CompletionGate",
    "RuntimeDriver",
    "apply_checklist_update",
    "auto_advance_plan",
    "find_plan_step",
    "format_checklist_markdown",
    "has_delivery_progress",
    "new_plan_revision",
    "normalize_checklist_steps",
    "plan_is_completed",
    "plan_to_active_plan",
    "start_next_pending_step",
]
