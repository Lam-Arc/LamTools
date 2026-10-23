"""Runtime protocol types and interfaces."""

import asyncio
import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal, Protocol, runtime_checkable

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

RuntimeStatus = Literal["idle", "running", "waiting", "paused", "completed", "failed", "cancelled"]
RuntimeLoopState = Literal["continue", "wait", "paused", "done", "failed"]


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
    guidance_source: Callable[[], list[Any]] | None = field(default=None, repr=False, compare=False)
    guidance_finalizer: Callable[[], list[Any] | None | Awaitable[list[Any] | None]] | None = field(default=None, repr=False, compare=False)
    guidance_acknowledger: Callable[[list[str]], Any] | None = field(default=None, repr=False, compare=False)

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
    async def get_history(self, session_id: str, *, after_seq: int = 0) -> list[dict[str, Any]]: ...
    async def history_max_seq(self, session_id: str) -> int: ...
    async def save_checkpoint(self, state: RuntimeState, history: list[dict[str, Any]]) -> None: ...
    async def append_history(self, session_id: str, messages: list[dict[str, Any]]) -> None: ...
    async def replace_history(self, session_id: str, messages: list[dict[str, Any]]) -> None: ...


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

    async def get_history(self, session_id: str, *, after_seq: int = 0) -> list[dict[str, Any]]:
        return deepcopy(self._history.get(session_id, [])[after_seq:])

    async def history_max_seq(self, session_id: str) -> int:
        return len(self._history.get(session_id, []))

    async def save_checkpoint(self, state: RuntimeState, history: list[dict[str, Any]]) -> None:
        self._states[state.session_id] = state
        self._history[state.session_id] = list(history)

    async def append_history(self, session_id: str, messages: list[dict[str, Any]]) -> None:
        if not messages:
            return
        existing = self._history.get(session_id, [])
        existing.extend(deepcopy(msg) for msg in messages)
        self._history[session_id] = existing

    async def replace_history(self, session_id: str, messages: list[dict[str, Any]]) -> None:
        self._history[session_id] = [deepcopy(msg) for msg in messages]

    async def find_pending_approval(self, request_id: str) -> RuntimeState | None:
        for state in self._states.values():
            pending = state.metadata.get("pending_approval") if isinstance(state.metadata, dict) else None
            tool_call = pending.get("tool_call") if isinstance(pending, dict) else None
            pending_request_id = pending.get("request_id") if isinstance(pending, dict) else None
            tool_call_id = tool_call.get("id") if isinstance(tool_call, dict) else None
            if request_id in {str(pending_request_id or ""), str(tool_call_id or "")}:
                return state
        return None

    async def find_threads_with_metadata_key(self, key: str) -> list[str]:
        """Thread ids whose state metadata carries ``key`` (mirrors the SQL store)."""
        if not key:
            return []
        return [
            session_id
            for session_id, state in self._states.items()
            if isinstance(state.metadata, dict) and state.metadata.get(key) is not None
        ]

    async def list_thread_ids(self) -> list[str]:
        """Every thread with a state (mirrors the SQL store)."""
        return list(self._states.keys())

    def clear(self) -> None:
        self._states.clear()
        self._history.clear()


def normalize_run_id(thread_id: str, run_id: str | None) -> str:
    """把同一个 round 的两种写法归一到短 run id。

    同一个 round 在系统里有两种写法：`<thread>:turn:<run>`（对外事件与 turn/steer
    携带的形式）和 `<run>`（内核运行输入里的形式）。注册方与消费方各用一种写法时，
    按原文比较就会对不上——引导正是这样丢的：turn/steer 按 `<thread>:turn:<run>`
    存进登记表，内核按 `<run>` 去取，永远取到空（2026-10-09）。统一在比较处归一，
    两种写法都能命中同一个 round。
    """
    value = str(run_id or "").strip()
    prefix = f"{str(thread_id or '').strip()}:turn:"
    if prefix != ":turn:" and value.startswith(prefix):
        return value[len(prefix):]
    return value


@dataclass
class _RuntimeTaskEntry:
    run_id: str
    # user:“严格分离回合编号和执行编号，拒绝过期写入”+登记表要记住这次执行属于
    # 哪个逻辑回合；缺它就只能拿 run_id 猜回合，旧的暂停便会打到新执行上。
    turn_id: str = ""
    task: asyncio.Task[Any] | None = None
    guidance_open: bool = True
    guidance: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)
    guidance_ids: set[str] = field(default_factory=set)
    staged_guidance_ids: set[str] = field(default_factory=set)
    offered_guidance_ids: set[str] = field(default_factory=set)
    guidance_changed: asyncio.Event = field(default_factory=asyncio.Event)


class RuntimeTaskRegistry:
    """Track active tasks and stage/offer guidance until checkpoint acknowledgement."""

    def __init__(self, *, background_process_registry: BackgroundProcessRegistry | None = None) -> None:
        self._entries: dict[str, _RuntimeTaskEntry] = {}
        # user:“修 问题严重的话 就重新设计”+(执行代次保留到任务退出之后，迟到的控制收尾不能作用于新执行)。
        self._control_generations: dict[str, int] = {}
        self._cancel_events: dict[str, asyncio.Event] = {}
        # Pause requests are their own signal: a pause keeps the run resumable
        # while the cancel event above keeps its terminal meaning.
        self._pause_events: dict[str, asyncio.Event] = {}
        self._background_process_registry = (
            background_process_registry or default_background_process_registry()
        )

    @property
    def background_process_registry(self) -> BackgroundProcessRegistry:
        return self._background_process_registry

    def get_cancel_event(self, thread_id: str) -> asyncio.Event:
        if thread_id not in self._cancel_events:
            self._cancel_events[thread_id] = asyncio.Event()
        return self._cancel_events[thread_id]

    def reset_cancel_event(self, thread_id: str) -> asyncio.Event:
        event = self.get_cancel_event(thread_id)
        event.clear()
        return event

    def get_pause_event(self, thread_id: str) -> asyncio.Event:
        if thread_id not in self._pause_events:
            self._pause_events[thread_id] = asyncio.Event()
        return self._pause_events[thread_id]

    def reset_pause_event(self, thread_id: str) -> asyncio.Event:
        event = self.get_pause_event(thread_id)
        event.clear()
        return event

    def request_pause(
        self,
        thread_id: str,
        *,
        run_id: str | None = None,
        turn_id: str | None = None,
        force: bool = False,
        reason: str = "user_pause",
    ) -> bool:
        """Ask the live run of *thread_id* to pause instead of to stop.

        The kernel polls this event mid-stream and between steps, so a blocked
        provider request stops promptly. ``force`` additionally cancels the task
        to tear down a tool that never checks the event; the kernel tells that
        teardown apart from a cancel and still converges on the paused state.
        The active-run claim stays untouched: the paused turn owns the session
        until the user continues or terminates it.
        """
        self._drop_done_entry(thread_id)
        entry = self._entries.get(thread_id)
        if entry is None:
            return False
        if run_id is not None and normalize_run_id(thread_id, entry.run_id) != normalize_run_id(thread_id, run_id):
            return False
        # user:“只有一个控制服务能决定暂停”+请求点名的回合必须就是这条执行的回合；
        # 对不上（含登记表还没记下回合）就不发信号、不取消，旧回合的暂停到此为止。
        if turn_id is not None and str(turn_id or "").strip():
            wanted = str(turn_id or "").strip()
            known = str(getattr(entry, "turn_id", "") or "").strip()
            if not known or known != wanted:
                return False
        event = self.get_pause_event(thread_id)
        # The kernel reads the reason off the event it polls, so the log and the
        # durable metadata can tell a user pause from the memory watchdog.
        setattr(event, "pause_reason", str(reason or "user_pause"))
        event.set()
        task = entry.task
        if force and task is not None and not task.done():
            task.cancel()
        return task is not None and not task.done()

    def accept_run(self, thread_id: str, run_id: str, *, turn_id: str = "") -> bool:
        thread_id = str(thread_id or "").strip()
        run_id = str(run_id or "").strip()
        if not thread_id or not run_id:
            return False
        self._drop_done_entry(thread_id)
        entry = self._entries.get(thread_id)
        if entry is not None:
            # user:“修 问题严重的话 就重新设计”+(失败的所有权申请不能修改当前执行的身份)。
            if entry.run_id != run_id:
                return False
            if entry.turn_id == "" and turn_id:
                # The first claim may not know the logical turn yet; a later
                # precise claim fills it in so a pause can be scoped.
                entry.turn_id = str(turn_id)
            return entry.run_id == run_id
        self.reset_cancel_event(thread_id)
        # A fresh run starts unpaused: the resume clears the request that
        # parked the previous run.
        self.reset_pause_event(thread_id)
        self._control_generations[thread_id] = self.control_generation(thread_id) + 1
        self._entries[thread_id] = _RuntimeTaskEntry(run_id=run_id, turn_id=str(turn_id or ""))
        return True

    def control_generation(self, thread_id: str) -> int:
        return self._control_generations.get(thread_id, 0)

    def active_run_id(self, thread_id: str) -> str | None:
        self._drop_done_entry(thread_id)
        entry = self._entries.get(thread_id)
        return entry.run_id if entry is not None else None

    def active_turn_id(self, thread_id: str) -> str:
        """The logical turn the live execution belongs to ("" when unclaimed).

        A pause/terminate request names a turn; the registry names an execution.
        Without this the handler can only compare two run ids, which is exactly
        how a stale pause reached a newer execution.
        """
        self._drop_done_entry(thread_id)
        entry = self._entries.get(thread_id)
        return str(getattr(entry, "turn_id", "") or "") if entry is not None else ""

    def register(
        self,
        thread_id: str,
        task: asyncio.Task[Any],
        *,
        run_id: str = "",
        turn_id: str = "",
    ) -> bool:
        self._drop_done_entry(thread_id)
        entry = self._entries.get(thread_id)
        if entry is None:
            if not self.accept_run(thread_id, run_id, turn_id=turn_id):
                return False
            entry = self._entries[thread_id]
        if normalize_run_id(thread_id, entry.run_id) != normalize_run_id(thread_id, run_id):
            return False
        if turn_id:
            if entry.turn_id and entry.turn_id != turn_id:
                return False
            entry.turn_id = turn_id
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
        if run_id is not None and normalize_run_id(thread_id, entry.run_id) != normalize_run_id(thread_id, run_id):
            return None
        return task

    def request_cancel(self, thread_id: str, *, run_id: str | None = None, force: bool = False) -> bool:
        """Signal cancellation without releasing the active-run claim.

        Stop uses this before its persistence round-trip so a blocked provider
        request is interrupted immediately.  The regular ``cancel`` method is
        still responsible for releasing the claim and cleaning up once the
        interrupting state has been recorded.
        """
        self._drop_done_entry(thread_id)
        entry = self._entries.get(thread_id)
        if entry is None or (run_id is not None and normalize_run_id(thread_id, entry.run_id) != normalize_run_id(thread_id, run_id)):
            return False
        task = entry.task
        self.get_cancel_event(thread_id).set()
        entry.guidance_open = False
        entry.guidance.clear()
        entry.guidance_ids.clear()
        entry.staged_guidance_ids.clear()
        entry.offered_guidance_ids.clear()
        entry.guidance_changed.set()
        if force and task is not None and not task.done():
            task.cancel()
        return task is not None and not task.done()

    def cancel(self, thread_id: str, *, run_id: str | None = None, force: bool = False) -> None:
        self._drop_done_entry(thread_id)
        entry = self._entries.get(thread_id)
        if entry is None:
            self._control_generations[thread_id] = self.control_generation(thread_id) + 1
            self.get_cancel_event(thread_id).set()
            self._background_process_registry.cleanup_session(thread_id)
            return
        if run_id is not None and normalize_run_id(thread_id, entry.run_id) != normalize_run_id(thread_id, run_id):
            return
        self._control_generations[thread_id] = self.control_generation(thread_id) + 1
        task = entry.task
        self.get_cancel_event(thread_id).set()
        entry.guidance_open = False
        entry.guidance.clear()
        entry.guidance_ids.clear()
        entry.staged_guidance_ids.clear()
        entry.offered_guidance_ids.clear()
        entry.guidance_changed.set()
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
        metadata: dict[str, Any] | None = None,
        ready: bool = True,
    ) -> Literal["accepted", "duplicate", "closed", "not_active"]:
        self._drop_done_entry(thread_id)
        entry = self._entries.get(thread_id)
        guidance = str(text or "").strip()
        if entry is None or normalize_run_id(thread_id, entry.run_id) != normalize_run_id(thread_id, run_id) or entry.task is None or not guidance:
            return "not_active"
        if not entry.guidance_open:
            return "closed"
        normalized_id = str(guidance_id or "").strip() or uuid.uuid4().hex
        if normalized_id and normalized_id in entry.guidance_ids:
            return "duplicate"
        entry.guidance.append((normalized_id, guidance, deepcopy(metadata or {})))
        if normalized_id:
            entry.guidance_ids.add(normalized_id)
            if not ready:
                entry.staged_guidance_ids.add(normalized_id)
        entry.guidance_changed.set()
        return "accepted"

    def publish_guidance(self, thread_id: str, *, run_id: str, guidance_id: str) -> None:
        """Expose a reserved offer only after its acceptance transaction commits."""
        entry = self._entries.get(thread_id)
        if entry is not None and normalize_run_id(thread_id, entry.run_id) == normalize_run_id(thread_id, run_id):
            entry.staged_guidance_ids.discard(guidance_id)
            entry.guidance_changed.set()

    def has_guidance(self, thread_id: str, *, run_id: str, guidance_id: str) -> bool:
        entry = self._entries.get(thread_id)
        return bool(entry is not None
                    and normalize_run_id(thread_id, entry.run_id) == normalize_run_id(thread_id, run_id)
                    and guidance_id in entry.guidance_ids)

    def acknowledge_guidance(self, thread_id: str, *, run_id: str, guidance_ids: list[str]) -> None:
        entry = self._entries.get(thread_id)
        if entry is None or normalize_run_id(thread_id, entry.run_id) != normalize_run_id(thread_id, run_id):
            return
        ids = set(guidance_ids)
        entry.guidance = [item for item in entry.guidance if item[0] not in ids]
        entry.offered_guidance_ids.difference_update(ids)
        entry.guidance_changed.set()

    def offer_guidance(self, thread_id: str, *, run_id: str) -> list[Any]:
        """Reserve committed guidance until the shared kernel checkpoints/ACKs it."""
        self._drop_done_entry(thread_id)
        entry = self._entries.get(thread_id)
        if entry is None or normalize_run_id(thread_id, entry.run_id) != normalize_run_id(thread_id, run_id) or entry.task is None:
            return []
        items = [item for item in entry.guidance if item[0] not in entry.staged_guidance_ids
                 and item[0] not in entry.offered_guidance_ids]
        entry.offered_guidance_ids.update(item[0] for item in items)
        return [{"content": text, "metadata": {**deepcopy(metadata), "guidance_id": guidance_id}}
                for guidance_id, text, metadata in items]

    def inject_guidance(
        self,
        thread_id: str,
        text: str,
        *,
        run_id: str = "",
        guidance_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Queue one instruction for the matching active runtime task."""
        return self.accept_guidance(
            thread_id,
            text,
            run_id=run_id,
            guidance_id=guidance_id,
            metadata=metadata,
        ) in {"accepted", "duplicate"}

    def consume_guidance(
        self,
        thread_id: str,
        *,
        run_id: str = "",
        include_metadata: bool = False,
    ) -> list[Any]:
        self._drop_done_entry(thread_id)
        entry = self._entries.get(thread_id)
        if entry is None or normalize_run_id(thread_id, entry.run_id) != normalize_run_id(thread_id, run_id) or entry.task is None:
            return []
        guidance = [
            ({"content": text, "metadata": {**deepcopy(metadata), "guidance_id": guidance_id}} if include_metadata else text)
            for guidance_id, text, metadata in entry.guidance if guidance_id not in entry.staged_guidance_ids
        ]
        entry.guidance = [item for item in entry.guidance if item[0] in entry.staged_guidance_ids]
        return guidance

    def close_guidance_if_empty(
        self,
        thread_id: str,
        *,
        run_id: str,
        include_metadata: bool = False,
    ) -> list[Any] | None:
        """Atomically consume pending guidance or seal an empty run."""
        self._drop_done_entry(thread_id)
        entry = self._entries.get(thread_id)
        if entry is None or normalize_run_id(thread_id, entry.run_id) != normalize_run_id(thread_id, run_id) or entry.task is None:
            return None
        if not entry.guidance_open:
            return []
        if entry.staged_guidance_ids:
            return []  # the async production finalizer waits for commit/rollback
        if entry.guidance:
            if include_metadata:
                return self.offer_guidance(thread_id, run_id=run_id)
            guidance = [
                ({"content": text, "metadata": deepcopy(metadata)} if include_metadata else text)
                for _guidance_id, text, metadata in entry.guidance
            ]
            entry.guidance.clear()
            return guidance
        entry.guidance_open = False
        return []

    def guidance_source(
        self,
        thread_id: str,
        *,
        run_id: str = "",
        include_metadata: bool = False,
    ) -> Callable[[], list[Any]]:
        if include_metadata:
            def source():
                return self.offer_guidance(thread_id, run_id=run_id)
            source.acknowledger = lambda ids: self.acknowledge_guidance(
                thread_id, run_id=run_id, guidance_ids=ids,
            )
            return source
        return lambda: self.consume_guidance(
            thread_id,
            run_id=run_id,
            include_metadata=include_metadata,
        )

    def guidance_finalizer(
        self,
        thread_id: str,
        *,
        run_id: str,
        include_metadata: bool = False,
    ) -> Callable[[], Any]:
        if include_metadata:
            async def finalize():
                while True:
                    entry = self._entries.get(thread_id)
                    if entry is None or normalize_run_id(thread_id, entry.run_id) != normalize_run_id(thread_id, run_id):
                        return None
                    entry.guidance_changed.clear()
                    if not entry.staged_guidance_ids:
                        return self.close_guidance_if_empty(thread_id, run_id=run_id, include_metadata=True)
                    await entry.guidance_changed.wait()
            return finalize
        return lambda: self.close_guidance_if_empty(
            thread_id,
            run_id=run_id,
            include_metadata=include_metadata,
        )

    def retract_guidance(self, thread_id: str, *, run_id: str, guidance_id: str) -> None:
        entry = self._entries.get(thread_id)
        if entry is None or normalize_run_id(thread_id, entry.run_id) != normalize_run_id(thread_id, run_id) or not guidance_id:
            return
        pending = [item for item in entry.guidance if item[0] == guidance_id]
        if not pending:
            return
        entry.guidance = [item for item in entry.guidance if item[0] != guidance_id]
        entry.guidance_ids.discard(guidance_id)
        entry.staged_guidance_ids.discard(guidance_id)
        entry.offered_guidance_ids.discard(guidance_id)
        entry.guidance_changed.set()

    def release_run(self, thread_id: str, *, run_id: str) -> None:
        entry = self._entries.get(thread_id)
        if entry is not None and entry.run_id == run_id:
            entry.guidance_changed.set()
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
