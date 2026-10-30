"""Core Loop Kernel: shared main loop skeleton.

Kernel owns the loop structure. Kit owns the business logic.
Kernel does NOT branch on product name.

Enhanced from runtime loop experience:
- Assistant response is appended to history before tool results
- Cancel signal supported via cancel() method
- LoopPhase tracked per step
- VerificationResult tracks attempt/max_attempts for Kit-managed repair loop
  (Kernel does NOT auto-inject repair_prompt; Kit owns repair semantics)
"""

from __future__ import annotations

import copy
import asyncio
import hashlib
import inspect
import json
import logging
import re
import uuid
import time as time_module
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import Any, TYPE_CHECKING

_logger = logging.getLogger(__name__)

from lamtools_core.context_compaction import (
    ContextCompactionController,
    ContextCompactionError,
    ContextCompactionResult,
    RECENT_USER_MESSAGES_METADATA_KEY,
    extract_recent_user_messages,
)
from lamtools_core.context_compaction.state import load_compaction_history, persist_compaction
from lamtools_core.context_compaction_budget import (
    calibrated_tokens,
    context_measurement,
    TokenBudget,
    TokenMeasurement,
    load_retained_steps,
    resolve_compaction_budget,
    resolve_retained_steps,
)
from lamtools_core.dialogue_records import COMPACTION_RECORD, build_compaction_record
from lamtools_core.event import CoreEvent, EventCategory, EventSink
from lamtools_core.llm import (
    HISTORICAL_TAIL_SYSTEM_MESSAGE_MARKER,
    TAIL_SYSTEM_MESSAGE_MARKER,
    ChatMessage,
    LLMClient,
    LLMRequest,
    LLMResponse,
    LLMStreamEvent,
    LLMToolCall,
)
from lamtools_core.llm.cache_diagnostics import record_cache_observation
from lamtools_core.llm.forensics import runtime_context as forensic_runtime_context
from lamtools_core.llm.helpers import merge_tool_call_deltas, resolve_tool_calls
from lamtools_core.llm.image_payload import MESSAGE_ADDED_AT_STEP
from lamtools_core.llm.policy import RetryPolicy
from lamtools_core.llm.session_affinity import provider_session_affinity
from lamtools_core.llm.retry import (
    ModelRetryEvent,
    ModelRetryExhausted,
    classify_model_error,
    complete_with_retry,
    stream_with_retry,
)
from lamtools_core.plugin_system.hooks import HookEvent
from lamtools_core.prompt.movable import (
    MOVABLE_CONTEXT_METADATA_KEY,
    is_movable_context_notice,
)
from lamtools_core.runtime.context_delta import is_runtime_context_delta, RUNTIME_CONTEXT_METADATA_KEY
from lamtools_core.app.tool_freeze import reset_session_tool_freeze
from lamtools_core.runtime.goal_continuation import (
    GOAL_CONTINUATION_KEY,
    goal_continuation_message,
    is_goal_continuation,
)
from lamtools_core.runtime import (
    CompletionGate,
    RuntimeCheckpointStore,
    RuntimeState,
    RuntimeStateStore,
    RuntimeToolStep,
    RuntimeTurnInput,
)
from lamtools_core.runtime.audit import build_kernel_audit
from lamtools_core.runtime.memory_guard import (
    HOST_MEMORY_EXHAUSTED,
    clear_failure_detail,
    clear_memory_resume_streak,
    clear_pending_memory_resume,
    is_memory_exhaustion,
    memory_exhausted_message_for,
    note_memory_interruption,
)
from lamtools_core.runtime.member_wake import (
    clear_member_wake_streak,
    consume_member_wake_autostart,
)
from lamtools_core.runtime_owner import LIVE_RUN_STATES, is_own_token, read_owner
from lamtools_core.tokens import estimate_message_tokens, estimate_text_tokens
from lamtools_core.tool import ToolCall, ToolResult

from .errors import KernelError, ModelCallError, TokenOverflowError
from .kit import RuntimeKit
from .policy import LoopPolicy
from .state import KernelResult, KernelStep, KernelTurn, LoopDecision, LoopPhase, VerificationResult
from .tracing import NoopTracer, Tracer

if TYPE_CHECKING:
    pass


_TOOL_INPUT_PROGRESS_CHARS = 512
_STREAM_TEXT_PROGRESS_CHARS = 128
# Bound on how many rounds the tool-progress gate may force a continuation
# while the model keeps emitting text+tools without the required structure —
# 成员事件一律不在回合内消费：父回合产出最终答复即结束，成员结果由 member-wake
# watchdog 作为**下一个回合**投递（见 _announce_active_members 与
# app/memory_resume_supervisor.py）。这样成员结果永远不会被本回合的最终总结
# 卷走，主代理也不会为了成员把回合拖成看起来卡住。


def _message_reference_ids(messages: list[ChatMessage]) -> list[str]:
    ids: list[str] = []
    for message in messages:
        metadata = message.metadata if isinstance(message.metadata, dict) else {}
        raw_id = (
            metadata.get("message_id")
            or metadata.get("id")
        )
        message_id = str(raw_id or "").strip()
        if message_id:
            ids.append(message_id)
    return ids


def _new_run_id() -> str:
    return uuid.uuid4().hex[:12]


def _json_safe_metadata(value: Any) -> Any:
    """Metadata that can be handed to a plugin hook or a provider.

    Hook events and provider requests are serialized, so a live callback that
    reached the turn metadata fails the run before its first model call
    ("Object of type function is not JSON serializable"). Dropping only what
    cannot be serialized keeps the rest of the metadata usable instead of
    losing the whole run (2026-10-14).
    """
    if isinstance(value, dict):
        return {
            str(key): _json_safe_metadata(item)
            for key, item in value.items()
            if not callable(item)
        }
    if isinstance(value, (list, tuple)):
        return [_json_safe_metadata(item) for item in value if not callable(item)]
    if isinstance(value, (set, frozenset)):
        return [_json_safe_metadata(item) for item in value]
    if callable(value):
        return None
    return value


def _status_from_decision(decision: LoopDecision) -> str:
    mapping = {
        "continue": "running",
        "wait": "waiting",
        "done": "completed",
        "failed": "failed",
    }
    return mapping.get(decision, "failed")


class _KernelPause(Exception):
    """Internal signal: the app layer asked this run to pause.

    Raised from inside the streaming loop (where a half-received model answer
    must be dropped instead of committed) and caught by the step loop, which
    ends the run with the non-terminal ``paused`` status. Distinct from
    :class:`asyncio.CancelledError` so a pause can never be mistaken for the
    external-cancel path, which converges on the terminal ``cancelled`` state.
    """


def _chat_message_from_dict(value: Any) -> ChatMessage | None:
    if not isinstance(value, dict):
        return None
    role = str(value.get("role") or "")
    if role not in {"system", "user", "assistant", "tool"}:
        return None
    raw_tool_calls = value.get("tool_calls") if isinstance(value.get("tool_calls"), list) else []
    tool_calls = []
    for raw in raw_tool_calls:
        if not isinstance(raw, dict):
            continue
        tool_calls.append(
            LLMToolCall(
                id=str(raw.get("id") or ""),
                name=str(raw.get("name") or ""),
                arguments=raw.get("arguments") if isinstance(raw.get("arguments"), (dict, str)) else {},
                metadata=dict(raw.get("metadata") or {}),
            )
        )
    content = value.get("content")
    if not isinstance(content, (str, list)):
        content = ""
    return ChatMessage(
        role=role,  # type: ignore[arg-type]
        content=content,
        name=str(value.get("name") or ""),
        tool_call_id=str(value.get("tool_call_id") or ""),
        tool_calls=tool_calls,
        metadata=dict(value.get("metadata") or {}),
        provider_state=copy.deepcopy(value.get("provider_state"))
        if "provider_state" in value
        else None,
    )


def _message_history_seq(message: ChatMessage) -> int:
    raw = message.metadata.get("history_seq")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 0
    return value if value > 0 else 0


def _retained_history_messages(
    history: list[ChatMessage],
    replacement_messages: list[ChatMessage],
    request_only_ids: set[int],
) -> list[ChatMessage]:
    """Map request-bound retained copies back to their durable originals.

    user:“图片以原图发送，那么在压缩之后还是以原图追加吗？”+压缩保留的消息如果只是
    请求期的降级副本，必须按 history_seq 找回原始历史，避免图片被 id 过滤掉或把低清副本写回存储。
    """
    originals_by_seq: dict[int, ChatMessage] = {}
    for message in history:
        seq = _message_history_seq(message)
        if seq > 0:
            originals_by_seq[seq] = message
    result: list[ChatMessage] = []
    for message in replacement_messages:
        metadata = message.metadata if isinstance(message.metadata, dict) else {}
        if message.role == "system" and metadata.get("key") == "context_compaction_summary":
            continue
        seq = _message_history_seq(message)
        original = originals_by_seq.get(seq) if seq > 0 else None
        if original is not None:
            if metadata.get("lam_compaction_resume"):
                if not isinstance(original.metadata, dict):
                    original.metadata = {}
                original.metadata["lam_compaction_resume"] = True
            result.append(original)
            continue
        if id(message) in request_only_ids:
            continue
        result.append(message)
    return result


def compaction_input_messages(messages: list[ChatMessage]) -> list[ChatMessage]:
    """Return the messages a summarizer may read.

    Context notices, runtime deltas and goal-continuation reminders are
    bookkeeping added by Sunday, not conversation; summarizing them would turn
    one internal reminder into permanent summary text.
    """
    return [
        message
        for message in messages
        if not is_movable_context_notice(message)
        and not is_runtime_context_delta(message)
        and not is_goal_continuation(message)
    ]


def _history_seq_set(value: Any) -> set[int]:
    if not isinstance(value, list):
        return set()
    result: set[int] = set()
    for item in value:
        try:
            parsed = int(item)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            result.add(parsed)
    return result


def _summary_recent_user_messages(
    compaction: dict[str, Any], summary_text: str
) -> list[str]:
    raw = compaction.get(RECENT_USER_MESSAGES_METADATA_KEY)
    if isinstance(raw, list) and all(isinstance(item, str) for item in raw):
        return list(raw)
    return extract_recent_user_messages(summary_text)


_INTERNAL_MESSAGE_METADATA_KEYS = ("history_seq", "lam_compaction_resume")


def _strip_internal_message_metadata(messages: list[ChatMessage]) -> list[ChatMessage]:
    """Copy messages without internal bookkeeping keys before model dispatch.

    Uses ``dataclasses.replace`` so the shared objects still referenced by the
    in-memory history keep their seq/marker tags for later compactions.
    """
    result: list[ChatMessage] = []
    for message in messages:
        if not isinstance(message.metadata, dict):
            result.append(message)
            continue
        if any(key in message.metadata for key in _INTERNAL_MESSAGE_METADATA_KEYS):
            message = replace(
                message,
                metadata={
                    key: value
                    for key, value in message.metadata.items()
                    if key not in _INTERNAL_MESSAGE_METADATA_KEYS
                },
            )
        result.append(message)
    return result


def _historical_tail_copy(message: ChatMessage) -> ChatMessage:
    """Store an emitted tail update as an in-place historical message.

    user:“当存在更改时，将更改内容追加到最后，但是不动前面的”+通知只在发出它的那一步位于末尾；
    写进持久历史后原地不动，下一步起成为可复用前缀的一部分。
    """
    metadata = message.metadata if isinstance(message.metadata, dict) else {}
    return replace(
        message,
        metadata={
            **metadata,
            TAIL_SYSTEM_MESSAGE_MARKER: False,
            HISTORICAL_TAIL_SYSTEM_MESSAGE_MARKER: True,
        },
    )


def _stamp_message_origin(message: ChatMessage, step_index: int) -> None:
    """Record the model-response counter at which *message* entered history.

    Neutral bookkeeping, not policy: the kernel does not decide how long an
    image may stay visible, but the app layer needs the arrival counter to know
    when a picture is past its full-fidelity request (see
    ``lamtools_core.llm.image_payload``).
    """
    if not isinstance(message.metadata, dict):
        message.metadata = {}
    message.metadata.setdefault(MESSAGE_ADDED_AT_STEP, int(step_index))


def _repair_incomplete_tool_history(
    messages: list[ChatMessage],
    *,
    session_id: str = "",
) -> list[ChatMessage]:
    repaired: list[ChatMessage] = []
    pending: dict[str, LLMToolCall] = {}
    # Observability only: the repair itself must stay byte-for-byte identical.
    # Every entry records where the rewrite happened so the backend log can
    # explain a one-off prompt-cache miss ("history was repaired at index N").
    closed_calls: list[dict[str, Any]] = []
    orphan_results: list[dict[str, Any]] = []

    def close_pending() -> None:
        for call in pending.values():
            closed_calls.append({
                "index": len(repaired),
                "call_id": str(call.id or ""),
                "tool": str(call.name or ""),
            })
            repaired.append(ChatMessage(
                role="tool",
                name=call.name,
                tool_call_id=call.id,
                content=(
                    "status: failed\n"
                    "error: Tool execution was interrupted before a result was recorded."
                ),
                metadata={"history_repair": "interrupted_tool_call"},
            ))
        pending.clear()

    def keep_orphan_result(message: ChatMessage) -> None:
        """Re-label a tool result no pending call can own as user context.

        A provider rejects any ``tool`` message that does not directly follow
        the assistant message that requested it, so an orphaned result (its
        assistant message was dropped by trimming, or guidance/other messages
        were interleaved before it) must not stay in the tool role.  Keep the
        payload — dropping it would silently lose the model's own tool output —
        and merge into a preceding user message so no provider sees two user
        turns in a row.
        """
        content = message.content
        previous = repaired[-1] if repaired else None
        if (
            previous is not None
            and previous.role == "user"
            and isinstance(previous.content, str)
            and isinstance(content, str)
        ):
            orphan_results.append({
                "index": len(repaired) - 1,
                "call_id": str(message.tool_call_id or ""),
                "merged_into_previous_user": True,
                "content_chars": len(content),
            })
            previous.content = f"{previous.content}\n\n{content}" if content else previous.content
            previous.metadata = {
                **dict(previous.metadata or {}),
                "history_repair": "orphaned_tool_result",
            }
            return
        orphan_results.append({
            "index": len(repaired),
            "call_id": str(message.tool_call_id or ""),
            "merged_into_previous_user": False,
            "content_chars": len(content) if isinstance(content, str) else None,
        })
        repaired.append(ChatMessage(
            role="user",
            content=content,
            metadata={
                **dict(message.metadata or {}),
                "history_repair": "orphaned_tool_result",
            },
        ))

    for message in messages:
        if message.role == "tool":
            call_id = str(message.tool_call_id or "")
            if call_id and call_id in pending:
                repaired.append(message)
                pending.pop(call_id, None)
            else:
                keep_orphan_result(message)
            continue
        if pending:
            close_pending()
        repaired.append(message)
        if message.role == "assistant":
            pending = {
                str(call.id): call
                for call in message.tool_calls
                if str(call.id or "").strip()
            }
    if pending:
        close_pending()
    if closed_calls or orphan_results:
        # One warning per repaired load, greppable as [kernel:history-repair].
        # Only counts, ids and positions are logged — never message content.
        _logger.warning(
            "[kernel:history-repair] session=%s messages=%d dangling_calls=%d "
            "orphan_results=%d first_repair_index=%d closed_calls=%s orphan_results_detail=%s "
            "cache_note=provider_request_changes_at_the_first_repair_index_so_the_prefix_"
            "before_it_may_be_re_read_once",
            session_id or "-",
            len(messages),
            len(closed_calls),
            len(orphan_results),
            min(
                [entry["index"] for entry in closed_calls]
                + [entry["index"] for entry in orphan_results]
            ),
            json.dumps(closed_calls[:20], ensure_ascii=False, sort_keys=True),
            json.dumps(orphan_results[:20], ensure_ascii=False, sort_keys=True),
        )
    return repaired


@dataclass
class _TurnScopedEventSink:
    delegate: EventSink
    turn_id: str

    async def emit(self, event: CoreEvent) -> None:
        if not event.turn_id:
            event.turn_id = self.turn_id
        await self.delegate.emit(event)


@dataclass
class CoreLoopKernel:
    """Core Loop Kernel: orchestrates the main runtime loop.

    Responsibilities:
    - Load and save RuntimeState
    - Create run_id, maintain turn_count
    - Emit generic lifecycle events
    - Call Kit to build context
    - Call model via Core LLMClient
    - Call Kit to parse model output
    - Append assistant response to history (model must see its prior output)
    - Execute tool calls from Kit
    - Write back tool results as model-visible messages
    - Call Kit to verify (non-blocking: Kernel does NOT auto-inject repair_prompt)
    - Call Kit to decide next (including LoopPhase updates)
    - Handle continue / wait / done / failed
    - Handle max steps, cancellation, exceptions

    NOT responsible:
    - Any product-specific business logic
    - Image generation, file operations, Git, etc.
    - Frontend rendering
    - FastAPI / SQLite / WebView binding
    """

    kit: RuntimeKit
    llm_client: LLMClient
    state_store: RuntimeStateStore
    event_sink: EventSink
    policy: LoopPolicy = field(default_factory=LoopPolicy)
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    tracer: Tracer = field(default_factory=NoopTracer)
    hook_engine: Any | None = None
    checkpoint_coordinator: Any | None = None
    # Tool names whose file writes get backed up before execution. Kept as a
    # configurable field rather than a hardcoded branch so products with
    # differently-named writer tools can opt in at the assembly point
    # (audit 05 S4: "Kernel 不按产品分支").
    completion_gate: CompletionGate | None = None
    # Called after the final request context is assembled and cleaned, just
    # before the request crosses into the LLM client.  The callback is
    # observational: failures must never prevent the actual model call.
    model_context_sink: Callable[[RuntimeState, LLMRequest], Awaitable[None] | None] | None = field(default=None, repr=False)
    _cancel_event: asyncio.Event = field(default_factory=asyncio.Event, init=False, repr=False)
    _run_started_at: float = field(default=0.0, init=False, repr=False)
    # Monotonic instant the previous model response arrived (0.0 before the
    # run's first call).  Feeds the per-step "gap_since_last_result" log line,
    # which is the only way to tell provider wait apart from the local work
    # between two calls (tool execution, history writeback, state save).
    _last_response_at: float = field(default=0.0, init=False, repr=False)
    # External cancel signal source (e.g. RuntimeTaskRegistry.get_cancel_event).
    # When set by the app layer's turn.cancel path, the kernel can detect it
    # mid-stream and abort the model call cooperatively instead of waiting for
    # the next loop iteration — which may never arrive if the call is blocked
    # on a slow/streaming response. None for sub-agent kernels (no external
    # cancel). See live_operations.handle_turn_cancel_operation.
    cancel_event_source: asyncio.Event | None = field(default=None, repr=False)
    # External pause signal source (e.g. RuntimeTaskRegistry.get_pause_event).
    # A pause is the cooperative sibling of the cancel signal above: the run
    # stops, drops the step it was in the middle of, and leaves a resumable
    # state behind instead of a terminal one. None for sub-agent kernels that
    # answer to no session-level pause.
    pause_event_source: asyncio.Event | None = field(default=None, repr=False)
    # Sticky record of "a pause was requested during this run". The event source
    # can be cleared (or belong to a registry that another run reset) while the
    # task is still unwinding, and the CancelledError handler must still tell
    # a pause apart from a terminate.
    _pause_requested: bool = field(default=False, init=False, repr=False)
    #: Reason reported by the pause request that stopped this run.
    _pause_reason: str = field(default="", init=False, repr=False)
    _base_event_sink: EventSink = field(init=False, repr=False)
    # The in-memory conversation list of the run currently executing. Assistant
    # replies and tool results live here until loop exit, so the external-cancel
    # path must persist this list; reloading from the store instead dropped
    # everything the stopped turn had already produced. None outside a run.
    _live_history: list[ChatMessage] | None = field(default=None, init=False, repr=False)
    # user:“该修修，该重构重构，有必要就重新设计架构或者迁到 Rust”+(准备阶段也能取消，追踪尚未开始时按空值收尾)。
    _run_span: Any | None = field(default=None, init=False, repr=False)
    # Number of leading _live_history entries already present as store rows.
    # The run flushes history incrementally (append-only) instead of rewriting
    # the whole table at loop exit. None = unaligned (request-local compaction
    # rewrote the list) or not a checkpoint store — fall back to full replace.
    _persisted_len: int | None = field(default=None, init=False, repr=False)
    # Fire-and-forget finalizers spawned by the external-cancel path so the
    # cancelled turn task exits immediately while persistence continues.
    _background_finalizers: set[asyncio.Task[None]] = field(default_factory=set, init=False, repr=False)
    # Generation of the composer settings patch already applied to this run.
    # user:“模式、权限、思考强度在下一步生效（即时生效）”+(同一步内重复取到同一个
    # 补丁时不再重复应用；新补丁的 generation 更大)。
    _applied_settings_generation: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        self._base_event_sink = self.event_sink

    def cancel(self) -> None:
        """Signal the kernel to stop at the next loop iteration.

        The running loop will detect this signal, mark the result as
        failed with error='cancelled', and return.
        """
        self._cancel_event.set()

    def _is_external_cancelled(self) -> bool:
        """Check the external cancel source (registry event) and mirror it.

        The app layer's ``turn.cancel`` path sets the
        ``RuntimeTaskRegistry`` cancel event rather than calling
        ``kernel.cancel()`` directly (it may not even hold a kernel
        reference — the task is cancelled via ``task.cancel()``). Polling
        this event from the streaming loop lets us abort a blocked model
        call cooperatively, instead of relying on ``asyncio.CancelledError``
        to unwind through arbitrary await points (which can stall on a
        DB-locked persistence write — the 2b34c636 hang).
        """
        if self.cancel_event_source is not None and self.cancel_event_source.is_set():
            self._cancel_event.set()
            return True
        return self._cancel_event.is_set()

    def _external_pause_requested(self) -> bool:
        """Whether the app layer asked this run to pause instead of to stop.

        Cancel wins when both are set: an explicit terminate must never be
        downgraded into a pause by a pause request that raced it.
        """
        if self._cancel_event.is_set():
            return False
        if self.cancel_event_source is not None and self.cancel_event_source.is_set():
            return False
        if self.pause_event_source is not None and self.pause_event_source.is_set():
            self._pause_requested = True
            reason = str(getattr(self.pause_event_source, "pause_reason", "") or "").strip()
            if reason:
                self._pause_reason = reason
            return True
        return False

    async def run(self, turn_input: RuntimeTurnInput) -> KernelResult:
        try:
            return await self._run(turn_input)
        except asyncio.CancelledError:
            # task.cancel() bypasses the cooperative cancel check below.
            # Terminal persistence runs as a detached task: the turn task must
            # exit immediately so the registry claim is released and the UI is
            # never held hostage by a slow write on a huge session (the
            # Codex-style "ack first, settle in background" contract).
            history = self._live_history
            run_span = self._run_span
            self._run_span = None
            # A pause request tears down a tool that cannot check the pause
            # event (a long-running command, a blocking write). That is still a
            # pause: the durable state must stay resumable, not become a
            # cancellation the user never asked for.
            if self._is_external_cancelled():
                self._spawn_external_cancel_persist(turn_input, history, run_span)
            elif self._external_pause_requested() or self._pause_requested:
                self._spawn_external_pause_persist(turn_input, history, run_span)
            else:
                self._spawn_external_cancel_persist(turn_input, history, run_span)
            raise
        finally:
            self._live_history = None
            self._persisted_len = None

    def _spawn_external_cancel_persist(
        self,
        turn_input: RuntimeTurnInput,
        history: list[ChatMessage] | None,
        run_span: Any | None,
    ) -> None:
        task = asyncio.get_running_loop().create_task(
            self._persist_external_cancellation(turn_input, history=history, run_span=run_span)
        )
        self._track_background_finalizer(task, turn_input, label="external-cancel")

    def _spawn_external_pause_persist(
        self,
        turn_input: RuntimeTurnInput,
        history: list[ChatMessage] | None,
        run_span: Any | None,
    ) -> None:
        task = asyncio.get_running_loop().create_task(
            self._persist_external_pause(turn_input, history=history, run_span=run_span)
        )
        self._track_background_finalizer(task, turn_input, label="external-pause")

    def _track_background_finalizer(
        self,
        task: asyncio.Task[None],
        turn_input: RuntimeTurnInput,
        *,
        label: str,
    ) -> None:
        self._background_finalizers.add(task)

        def _done(done: asyncio.Task[None]) -> None:
            self._background_finalizers.discard(done)
            if not done.cancelled() and done.exception() is not None:
                _logger.error(
                    "[kernel] %s persistence failed sid=%s: %s",
                    label,
                    str(turn_input.metadata.get("session_id") or ""),
                    done.exception(),
                )

        task.add_done_callback(_done)

    async def await_background_persistence(self) -> None:
        """Wait for detached cancel-finalizer tasks (test/introspection hook)."""
        while True:
            pending = [t for t in tuple(self._background_finalizers) if not t.done()]
            if not pending:
                return
            await asyncio.gather(*pending, return_exceptions=True)

    async def _run(self, turn_input: RuntimeTurnInput) -> KernelResult:
        """Execute the main loop.

        One run() call = one Task (OpenAI Codex terminology). A Task is the
        work unit that responds to a single user input. A Session may span
        multiple Tasks (multiple run() calls sharing the same session_id).
        Within a Task, the loop iterates over Turns (steps) until termination.

        Algorithm:
        1. load state
        2. mark running
        3. kit.on_run_start
        4. append user input to history
        5. repeat until terminal decision:
           5.1 check cancel → break if cancelled
           5.2 build context
           5.3 build model request
           5.4 call model with timeout/retry
           5.5 parse model output
           5.6 emit reply and kit events
           5.7 append assistant response to history
           5.8 execute tool calls
           5.9 append formatted tool results to history
           5.10 verify (non-blocking, no repair retry)
           5.11 decide next
           5.12 writeback
           5.13 save state
           5.14 break on wait/done/failed
        6. kit.on_run_end
        7. emit final event
        8. return KernelResult
        """
        self._run_started_at = time_module.monotonic()

        # Reset cancel event for this run
        self._cancel_event.clear()
        # A run starts unpaused; the app layer sets its own pause event before
        # the kernel is handed the turn, and a fresh run must not inherit the
        # previous run's pause.
        self._pause_requested = False

        # 1. Load or create state
        state: RuntimeState
        if turn_input.state is not None:
            state = turn_input.state
        else:
            session_id = turn_input.metadata.get("session_id", "")
            loaded = await self.state_store.get(session_id) if session_id else None
            if loaded is not None:
                state = loaded
            else:
                state = RuntimeState(session_id=session_id or _new_run_id())
            _logger.info("[kernel:_run] state loaded sid=%s existing=%s", state.session_id, loaded is not None)

        # user:“去重构吧”+(自动与手动共用摘要视图加载，原始消息不随压缩删除)。
        history = (
            _repair_incomplete_tool_history(
                await load_compaction_history(self.state_store, state.session_id, state.metadata),
                session_id=state.session_id,
            )
            if isinstance(self.state_store, RuntimeCheckpointStore) else []
        )
        _logger.info("[kernel:_run] history loaded sid=%s len=%d", state.session_id, len(history))
        # Hand the live list to the external-cancel path: history is only
        # written to the store at loop exit, so a run cut short by Stop must
        # persist this list or the turn's own assistant/tool content is lost.
        self._live_history = history
        # Everything loaded came from the store (the request-local compaction
        # summary inserted above is never persisted): the tail flush starts
        # after it.
        self._persisted_len = len(history)

        # Each user turn is a new run inside the same session. Persisted state
        # carries session memory and turn_count, but a stale run_id/status from
        # a crashed or failed prior run must not leak into the next run.
        state.run_id = str(turn_input.run_id or "").strip() or _new_run_id()
        turn_id = str(turn_input.turn_id or "").strip() or f"{state.session_id}:turn:{state.run_id}"
        state.metadata["turn_id"] = turn_id
        if "goal_id" in turn_input.metadata:
            goal_id = str(turn_input.metadata.get("goal_id") or "").strip()
            state.metadata.pop("goal_completion", None)
            if goal_id:
                state.metadata["goal_id"] = goal_id
            else:
                state.metadata.pop("goal_id", None)
        state.metadata.pop("no_progress", None)
        state.metadata.pop("failure_diagnosis", None)
        # Stale per-turn waiting state from a crashed/failed prior run must not
        # leak into the new run: both the no_progress pause and the permission
        # approval gate persist this metadata across checkpoints, and a stale
        # entry would shadow the fresh gate state set later in this run
        # (audit 05 S4). The approval resume path is guidance-driven, so
        # dropping these keys here cannot break pending-approval recovery.
        state.metadata.pop("pending_approval", None)
        state.metadata.pop("pending_waiting_request", None)
        state.metadata.pop("cancellation_reason", None)
        state.metadata["runtime_audit"] = build_kernel_audit(
            policy=self.policy,
            kernel_module_path=__file__,
        )
        self.event_sink = _TurnScopedEventSink(self._base_event_sink, turn_id)
        state.loop_state = "continue"
        state.position = ""

        # A checkpoint belongs to the accepted agent turn, not to an
        # individual model/tool step.  Keeping this seam in Kernel means main
        # and delegated agents cannot accidentally drift into two policies.
        if self.checkpoint_coordinator is not None:
            actor_kind = str(turn_input.metadata.get("actor_kind") or "main")
            _logger.info("[kernel:_run] checkpoint begin_turn sid=%s actor=%s", state.session_id, actor_kind)
            await self.checkpoint_coordinator.begin_turn(
                session_id=state.session_id,
                turn_id=turn_id,
                actor_kind=actor_kind,
            )

        # Start root trace span for this run (after state is loaded so we have ids).
        # Keep a self reference so the external-cancellation path (which unwinds
        # through run()'s CancelledError handler, past this local) can still close
        # the span inside _finalize_run.
        run_span = self.tracer.start_span(
            "kernel.run", session_id=state.session_id, run_id=state.run_id
        )
        self._run_span = run_span

        # 2-4. Mark running, run the start hooks, and persist the user input.
        # The whole setup sits inside one guard: a failure in any step of it
        # (state store, Kit, hook, checkpoint) must converge the run instead of
        # leaving the session marked "running" with no terminal event
        # (2026-09-25 audit P3).
        try:
            new_messages = await self._begin_run(state, turn_input, history)
            # _begin_run appended (and persisted) this turn's input rows.
            self._persisted_len = len(history)
            await self._acknowledge_guidance(
                turn_input, [
                    *list(turn_input.metadata.get("initial_guidance_ids") or []),
                    *list(turn_input.metadata.get("input_acknowledgement_ids") or []),
                ]
            )
        except Exception as exc:  # noqa: BLE001 — the run still needs a terminal state
            _logger.exception("[kernel:_run] run setup failed sid=%s", state.session_id)
            state.status = _status_from_decision("failed")
            state.loop_state = "failed"
            try:
                await self._replace_history_checkpoint(state, history)
            except Exception:  # noqa: BLE001 — the terminal event still has to fire
                _logger.exception(
                    "[kernel:_run] failed to persist the terminal state sid=%s", state.session_id
                )
            result = KernelResult(
                session_id=state.session_id,
                run_id=state.run_id,
                decision="failed",
                message="",
                steps=[],
                state=state,
                error=f"run setup failed: {exc or type(exc).__name__}",
            )
            await self._finalize_run(state, result, run_span)
            self._run_span = None
            return result

        steps: list[KernelStep] = []
        latest_message = ""
        final_decision: LoopDecision = "continue"
        error_msg = ""
        recent_tool_result_fingerprints: list[str] = []
        recent_successful_payloads: list[dict[str, Any]] = []
        explicit_input_errors: dict[str, ToolResult] = {}
        consecutive_failure_rounds = 0

        # Emit runtime.started event
        await self._emit_state_event(state, "runtime.started", "run started")

        _logger.info("[kernel:_run] entering main loop sid=%s run=%s tools=%d history=%d",
                      state.session_id, state.run_id,
                      len(self.kit.toolbox.tool_specs()) if self.kit.toolbox else 0,
                      len(history))

        # 5. Main loop. There is intentionally no step budget: complex tasks
        # may need many model/tool rounds. Cancellation, explicit failure,
        # waiting for the user, or a no-tool final response ends the run.
        # Step numbering MUST continue across approval-wait resumes: response
        # item ids are derived from response_index (`{run_id}:response-{index}`),
        # and a fresh `index = 0` on every kernel.run would reuse the previous
        # run's item ids — the frontend projection merges by item_id, so new
        # output overwrites the old parts and the sort order breaks (reply
        # after ask-user showed the new text before the approval card).
        # state.metadata.kernel_steps survives checkpoints, so its length is
        # the cumulative step count across resumes.
        steps_log = state.metadata.get("kernel_steps")
        index = len(steps_log) if isinstance(steps_log, list) else 0
        while True:
            step = KernelStep(index=index, state_before=self._copy_state(state))
            steps.append(step)
            step_span = self.tracer.start_span(
                "kernel.step", parent_id=run_span, step_index=index
            )

            try:
                # 5.1 Check cancel
                if self._cancel_event.is_set():
                    error_msg = "cancelled"
                    step.error = error_msg
                    final_decision = "failed"
                    break
                if self._external_pause_requested():
                    # The user asked to pause. Stop before starting another step
                    # and leave the turn resumable: the model answer of this step
                    # was never received, so there is nothing to commit for it.
                    error_msg = "paused"
                    step.error = error_msg
                    final_decision = "failed"
                    _logger.info(
                        "[kernel:_run] paused before step=%d sid=%s reason=%s",
                        index,
                        state.session_id,
                        str(state.metadata.get("pause_reason") or self._pause_reason or "user_pause"),
                    )
                    break

                await self._consume_guidance(state, turn_input, history, index)
                # user:“模式、权限、思考强度在下一步生效（即时生效）”+(先落参数组，
                # 再构建下一步的提示词、工具数组与模型请求)。
                await self._apply_runtime_settings(state, turn_input)

                # 5.2 Build context
                # Pre-sampling history compaction (OpenAI-style): trim history
                # to max_history_messages before build_context. Preserves
                # assistant→tool_result pairs to avoid orphaned tool results.
                max_hist = self.policy.max_history_messages
                if max_hist is not None and len(history) > max_hist:
                    cut = len(history) - max_hist
                    while cut > 0 and history[cut].role == "tool":
                        cut -= 1
                    if cut > 0:
                        # `trimmed` is what was dropped, not what is left —
                        # computing it before the delete reported the remainder
                        # (2026-09-25 审计 P3).
                        trimmed = cut
                        del history[:cut]
                        await self._replace_history_checkpoint(state, history)
                        # The rewrite renumbered the rows; the live list now
                        # maps 1:1 onto the store again.
                        self._persisted_len = len(history)
                        await self._emit_history_compacted(state, trimmed, len(history))

                context = await self.kit.build_context(state, turn_input, history, index)

                # 5.3 Build model request
                request = await self.kit.build_model_request(state, context)
                # user:“当存在更改时，将更改内容追加到最后，但是不动前面的”+Kit 把变化生成为尾部通知；这里把它写进持久历史，之后每一步和重启后都留在原位。
                movable_notices = request.metadata.pop("_movable_context_notices", None)
                runtime_deltas = request.metadata.pop("_runtime_context_delta", None)
                movable_seeded = bool(
                    request.metadata.pop("_movable_context_seeded", False)
                )
                committed_updates = [
                    *(runtime_deltas or []),
                    *(movable_notices or []),
                ]
                if committed_updates:
                    history.extend(
                        _historical_tail_copy(message)
                        for message in committed_updates
                    )
                if committed_updates or movable_seeded:
                    await self._save_checkpoint(state)
                # user:“子代理和主代理用一个 id”+(运行时身份保持子会话；缓存路由亲和
                # 回到父会话，OpenCode 官方客户端同样让子会话沿用父会话 id。)
                affinity_metadata = {
                    **(state.metadata or {}),
                    **(turn_input.metadata or {}),
                }
                request.metadata.update(
                    _runtime_session_id=state.session_id,
                    _provider_session_affinity=provider_session_affinity(
                        state.session_id, affinity_metadata
                    ),
                    _runtime_run_id=state.run_id,
                    _runtime_step=index,
                )
                await self._compact_request_if_needed(state, request, history=history)
                # Strip internal bookkeeping metadata (history seq / resume
                # marker) before the request reaches the model — the shared
                # objects in `history` keep their tags for later compactions.
                request.messages = _strip_internal_message_metadata(request.messages)
                # Recorded before dispatch so the usage anchor built from the
                # response can be tied back to exactly what the provider saw.
                sent_message_count = len(request.messages)
                if self.model_context_sink is not None:
                    try:
                        captured = self.model_context_sink(state, request)
                        if captured is not None:
                            await captured
                    except Exception:  # noqa: BLE001 — capture must not break a run
                        _logger.exception(
                            "[kernel:_run] model context capture failed sid=%s step=%d",
                            state.session_id,
                            index,
                        )

                # 5.4 Call model — try streaming first
                _step_start = time_module.monotonic()
                _logger.info(
                    "[kernel:_run] step=%d dispatching model request sid=%s "
                    "gap_since_last_result=%.2fs messages=%d tools=%d model=%s",
                    index, state.session_id,
                    (_step_start - self._last_response_at) if self._last_response_at else 0.0,
                    len(request.messages), len(request.tools or []), request.model,
                )
                response = await self._stream_model(request, state, response_index=index)
                streamed_response = response is not None
                if response is None:
                    response = await self._call_model(request, state=state, response_index=index)
                _response_at = time_module.monotonic()
                _step_elapsed = _response_at - _step_start
                self._last_response_at = _response_at
                _logger.info(
                    "[kernel:_run] model response received sid=%s step=%d "
                    "streamed=%s content_len=%d tool_calls=%d elapsed=%.2fs",
                    state.session_id, index, streamed_response,
                    len(response.content or ""), len(response.tool_calls or []),
                    _step_elapsed,
                )
                # A turn is one processed model response; count it exactly once
                # per loop iteration here (not in each decision branch) so the
                # approval-wait / progress-gate / no-progress / normal exits and
                # later error paths all share one consistent 口径 (audit 05 S4).
                state.turn_count += 1
                # Emit one canonical per-response usage fact for both streaming
                # and non-streaming calls.  Providers are allowed to omit token
                # usage, but a successful response is still one model call.
                usage_payload = response.usage.to_dict() if response.usage is not None else {}
                usage_payload["llm_calls"] = 1
                usage_payload["usage_available"] = response.usage is not None
                usage_payload["usage_status"] = "reported" if response.usage is not None else "missing"
                usage_payload["usage_source"] = "provider"
                try:
                    response_metadata = response.metadata if isinstance(response.metadata, dict) else {}
                    cache_diagnostic = record_cache_observation(
                        state.session_id,
                        request,
                        response.usage,
                        response_metadata.get("cache_diagnostic_route"),
                    )
                    if cache_diagnostic is not None:
                        usage_payload["cache_diagnostic"] = cache_diagnostic
                        _logger.warning(
                            "[cache-diagnostic] sid=%s %s",
                            state.session_id,
                            json.dumps(cache_diagnostic, ensure_ascii=False, sort_keys=True),
                        )
                except Exception:  # noqa: BLE001 — diagnostics must never break a turn
                    _logger.exception(
                        "[cache-diagnostic] recording failed sid=%s step=%d",
                        state.session_id,
                        index,
                    )
                await self.event_sink.emit(CoreEvent(
                    name="runtime.usage",
                    category="usage",
                    payload={"usage": usage_payload, "response_index": index},
                    session_id=state.session_id,
                    run_id=state.run_id,
                    tags=["usage"],
                ))
                # user:“该修修”+(模型真实用量由执行循环记账，缺失时保守估算；耗尽立即停止)。
                run_budget = getattr(self.kit.toolbox, "run_budget", None) if hasattr(self.kit, "toolbox") else None
                if run_budget is not None:
                    tool_text = json.dumps([{"name": call.name, "arguments": call.arguments} for call in response.tool_calls], ensure_ascii=False)
                    estimate = max(1, (sum(len(str(message.content)) for message in request.messages) + len(response.content or "") + len(tool_text)) // 3)
                    run_budget.record_model_usage(response.usage, estimated_tokens=estimate)
                # user:“有真实 usage 时使用真实 usage，无真实 usage 使用兜底估算值”
                # +把上一次成功响应的 prompt tokens 记下来，下一次触发直接用它。
                self._record_context_usage(state, request, response)
                if response.thinking and not streamed_response:
                    await self._emit_stream_part(
                        state,
                        part_id=f"{state.run_id}:response-{index}:reasoning",
                        part_type="reasoning",
                        status="completed",
                        label="思考",
                        content=response.thinking,
                        response_index=index,
                        raw=response.raw,
                    )
                # 5.5 Parse model output
                if not (response.content or "").strip() and not response.tool_calls:
                    _logger.warning(
                        "[kernel:_run] empty model response sid=%s step=%d "
                        "finish_reason=%s usage=%s",
                        state.session_id, index,
                        response.finish_reason,
                        str(getattr(response, 'usage', None))[:120],
                    )
                turn = await self.kit.parse_model_output(state, response)
                invalid_tool_argument_errors: dict[str, str] = {}
                # Match response calls to turn calls by id so the error is
                # attributed correctly even if the Kit reorders or filters
                # calls; index alignment is only a fallback for id-less calls
                # (audit 05 S4).
                turn_calls_by_id = {call.id: call for call in (turn.tool_calls or [])}
                for response_index, response_call in enumerate(response.tool_calls or []):
                    metadata = response_call.metadata if isinstance(response_call.metadata, dict) else {}
                    if not metadata.get("arguments_parse_error"):
                        continue
                    turn_call = turn_calls_by_id.get(response_call.id)
                    if turn_call is None and response_index < len(turn.tool_calls):
                        turn_call = turn.tool_calls[response_index]
                    if turn_call is None:
                        continue
                    raw_chars = int(metadata.get("raw_arguments_chars") or 0)
                    finish_reason = str(response.finish_reason or "unknown")
                    invalid_tool_argument_errors[turn_call.id] = (
                        "Model tool arguments were incomplete or invalid JSON and were not executed "
                        f"(finish_reason={finish_reason}, received={raw_chars} chars). "
                        "Generate one complete call with all required fields; if the payload is large, "
                        "split it into smaller calls."
                    )
                step.turn = turn
                # Kernel-level natural-stop signal (OpenAI-style): model
                # produced a text reply with no tool calls. Kit MAY consume
                # turn.is_natural_stop in decide_next as a done candidate.
                if not turn.tool_calls and turn.reply:
                    turn.is_natural_stop = True

                # 5.6 Emit reply and kit events
                if turn.reply:
                    latest_message = turn.reply
                    if turn.tool_calls:
                        await self._emit_text_part(
                            state,
                            turn.reply,
                            response_index=index,
                            final_response=False,
                            has_tool_calls=True,
                        )
                    else:
                        await self._emit_reply(state, turn.reply, response_index=index)

                for event in turn.events:
                    await self.event_sink.emit(event)
                    step.events.append(event)

                # 5.7 Append assistant response to history
                #    Model must see its prior output in the next iteration.
                if turn.reply or turn.tool_calls:
                    assistant_content = turn.reply or ""
                    history.append(ChatMessage(
                        role="assistant",
                        content=assistant_content,
                        tool_calls=[
                            LLMToolCall(
                                id=call.id,
                                name=call.name,
                                arguments=call.arguments,
                                raw=call.raw,
                                metadata={
                                    **call.metadata,
                                    **({"reason": call.reason} if call.reason else {}),
                                    **({"goal": call.goal} if call.goal else {}),
                                },
                            )
                            for call in turn.tool_calls
                        ],
                        provider_state=copy.deepcopy(response.provider_state),
                    ))
                    await self._save_checkpoint(state)

                # 5.8 Execute tool calls
                tool_results: list[ToolResult] = []
                blocked_results: dict[str, ToolResult] = {
                    call.id: ToolResult(
                        call_id=call.id,
                        name=call.name,
                        status="failed",
                        error=invalid_tool_argument_errors[call.id],
                    )
                    for call in turn.tool_calls
                    if call.id in invalid_tool_argument_errors
                }
                # A permission-preset switch can land between the model
                # producing this call and the waiting gate below.  Every call
                # carries the ``requires_approval`` decision computed when it
                # was parsed, so re-run the approval boundary against the
                # toolbox's live (current-session) permission state before
                # deciding whether to surface a card.  A preset that already
                # auto-approves the call must not produce a stale card; the
                # one exception is ``question``, which is a user-input request
                # rather than a permission decision and is never auto-released
                # (plan A, 2026-10-12).  This runs before the PreToolUse hook
                # so a hook's own ask_user decision is never overwritten.
                self._refresh_live_approval_requirements(turn.tool_calls, blocked_results)
                payload_matches: dict[str, tuple[dict[str, Any], dict[str, Any] | None]] = {}
                for call in turn.tool_calls:
                    payload = self._substantive_tool_payload(call)
                    prior_payload = next(
                        (
                            prior
                            for prior in reversed(recent_successful_payloads)
                            if payload is not None and self._substantive_payloads_match(payload, prior)
                        ),
                        None,
                    )
                    if payload is not None:
                        payload_matches[call.id] = (payload, prior_payload)
                    # Block calls whose substantive payload matches a prior
                    # call that was already challenged — the model was told
                    # to reconsider but sent the same large payload again.
                    if (
                        prior_payload is not None
                        and bool(prior_payload.get("challenged"))
                        and call.id not in blocked_results
                    ):
                        blocked_results[call.id] = ToolResult(
                            call_id=call.id,
                            name=call.name,
                            status="blocked",
                            content="Skipped: substantive payload duplicates a previously challenged call.",
                            metadata={"duplicate_substantive_payload": True},
                        )
                    if call.id not in blocked_results:
                        blocked = await self._apply_pre_tool_hook(state, call)
                        if blocked is not None:
                            blocked_results[call.id] = blocked
                input_error_warnings: list[str] = []
                for call in turn.tool_calls:
                    prior_input_error = explicit_input_errors.get(self._tool_call_fingerprint(call))
                    if prior_input_error is None:
                        continue
                    input_error_warnings.append(
                        f"- {call.name}: {prior_input_error.error}"
                    )
                    if call.id not in blocked_results:
                        blocked_results[call.id] = ToolResult(
                            call_id=call.id,
                            name=call.name,
                            status="blocked",
                            content="Skipped: identical to a previous input error.",
                            error=prior_input_error.error,
                            metadata={"duplicate_input_error": True},
                        )
                if input_error_warnings:
                    history.append(ChatMessage(
                        role="user",
                        content=(
                            "[DUPLICATE_INPUT_ERROR] Some tool calls match previous input errors. "
                            "Ensure the arguments below are corrected before retrying:\n"
                            + "\n".join(input_error_warnings)
                        ),
                        metadata={"key": "duplicate_input_error", "internal": True},
                    ))
                approval_calls = [
                    call
                    for call in turn.tool_calls
                    if call.id not in blocked_results and call.requires_approval
                ]
                #: True when this step's tool calls were fully handled inside
                #: the approval gate, so the normal parallel/sequential block
                #: must not execute them a second time.
                approval_batch_handled = False
                if approval_calls:
                    # Commit every call that does not need a decision before
                    # parking. The assistant message is already in history; if
                    # these stay unexecuted, history repair later fabricates an
                    # "interrupted" result for work that was never attempted.
                    for call in [
                        candidate
                        for candidate in turn.tool_calls
                        if candidate.id not in blocked_results and candidate not in approval_calls
                    ]:
                        tool_results.append(
                            await self._execute_call_and_writeback(
                                state,
                                call,
                                blocked_results=blocked_results,
                                step=step,
                                index=index,
                                history=history,
                            )
                        )

                    waiting_call: ToolCall | None = None
                    deferred_calls: list[ToolCall] = []
                    for position, candidate in enumerate(approval_calls):
                        # PermissionRequest hook — allows hook-driven
                        # auto-approve / deny for each call in the batch.
                        perm_hook_result = await self._apply_permission_request_hook(
                            state, candidate
                        )
                        if not candidate.requires_approval:
                            tool_results.append(
                                await self._execute_call_and_writeback(
                                    state,
                                    candidate,
                                    blocked_results=blocked_results,
                                    step=step,
                                    index=index,
                                    history=history,
                                )
                            )
                            continue
                        if perm_hook_result is not None:
                            blocked_results[candidate.id] = perm_hook_result
                            tool_results.append(
                                await self._execute_call_and_writeback(
                                    state,
                                    candidate,
                                    blocked_results=blocked_results,
                                    step=step,
                                    index=index,
                                    history=history,
                                )
                            )
                            continue
                        waiting_call = candidate
                        deferred_calls = list(approval_calls[position + 1:])
                        break

                    approval_batch_handled = True
                    if waiting_call is None:
                        # Every call was auto-approved or denied by a hook; all
                        # results are already committed above.
                        pass
                    else:
                        # The provider's tool-call id is only unique within one
                        # response. Two agents (or two sessions) can both use
                        # ``call_0``; the durable request identity must be
                        # globally unambiguous because it is the routing key
                        # for approval.respond.
                        request_id = f"{state.session_id}:{state.run_id}:{waiting_call.id}"
                        question_args = (
                            waiting_call.arguments
                            if waiting_call.name == "question"
                            and isinstance(waiting_call.arguments, dict)
                            else {}
                        )
                        question_context = str(question_args.get("context") or "").strip()
                        raw_questions = question_args.get("questions")
                        questions_payload = raw_questions if isinstance(raw_questions, list) else []
                        request_kind = (
                            "question" if waiting_call.name == "question" else "permission"
                        )
                        request_options, request_message = self._approval_request_options_and_message(
                            waiting_call
                        )
                        state.metadata["pending_approval"] = {
                            "request_id": request_id,
                            "tool_call": waiting_call.to_dict(),
                            "response_index": index,
                            "status": "waiting",
                            "asked_at_ms": int(time_module.time() * 1000),
                            # Calls after the waiting one stay owned by this
                            # batch. They get explicit results on continuation
                            # instead of vanishing or being re-executed twice.
                            "deferred_calls": [call.to_dict() for call in deferred_calls],
                            # A crash between the checkpoint and the card event
                            # used to leave a waiting turn with nothing to
                            # answer. Recovery rebuilds the card from this
                            # payload instead of guessing.
                            "request_payload": {
                                "request_id": request_id,
                                "tool_name": waiting_call.name,
                                "arguments": waiting_call.arguments,
                                "request_kind": request_kind,
                                "message": request_message,
                                "metadata": dict(waiting_call.metadata),
                                "options": request_options,
                                **(
                                    {"context": question_context}
                                    if question_context
                                    else {}
                                ),
                                **({"questions": questions_payload} if questions_payload else {}),
                            },
                        }
                        state.metadata["pending_waiting_request"] = {
                            "request_id": request_id,
                            "request_kind": request_kind,
                            "tool_call_id": waiting_call.id,
                            "tool_name": waiting_call.name,
                            "arguments": waiting_call.arguments,
                            "metadata": dict(waiting_call.metadata),
                            "message": request_message,
                            # Recovery may rebuild the card from this record when
                            # pending_approval was lost. Without the real options
                            # it produced a card that asked the same question but
                            # offered different (or no) choices.
                            "options": request_options,
                            **({"context": question_context} if question_context else {}),
                            **({"questions": questions_payload} if questions_payload else {}),
                        }
                        step.metadata["pending_approval"] = state.metadata["pending_approval"]
                        decision = "wait"
                        step.decision = decision
                        final_decision = decision
                        await self.kit.writeback(
                            state, turn, tool_results, VerificationResult(passed=True), decision
                        )
                        state.loop_state = decision
                        if self.policy.persist_steps:
                            steps_log = state.metadata.setdefault("kernel_steps", [])
                            steps_log.append(self._summarize_step(step))
                        await self._save_checkpoint(state)
                        # The pending record is durable now, so a permission
                        # switch that landed in the window between the
                        # pre-emission check and this save becomes visible
                        # here. If the live preset already covers the call,
                        # release it on the spot instead of surfacing a stale
                        # card.
                        released_call = self._release_approval_if_live_preset_covers(
                            state, step, waiting_call
                        )
                        if released_call is not None:
                            for _position, _existing in enumerate(turn.tool_calls):
                                if _existing.id == released_call.id:
                                    turn.tool_calls[_position] = released_call
                                    break
                            # Re-evaluate the deferred approvals against the
                            # same live preset; execute what is now allowed and
                            # hand the rest back as explicit deferrals.
                            released = [released_call]
                            still_waiting: list[ToolCall] = []
                            for candidate in deferred_calls:
                                refreshed = self._reprepare_against_live_permissions(candidate)
                                if refreshed.requires_approval:
                                    still_waiting.append(refreshed)
                                else:
                                    released.append(refreshed)
                            for candidate in released:
                                tool_results.append(
                                    await self._execute_call_and_writeback(
                                        state,
                                        candidate,
                                        blocked_results=blocked_results,
                                        step=step,
                                        index=index,
                                        history=history,
                                    )
                                )
                            for candidate in still_waiting:
                                blocked_results[candidate.id] = ToolResult(
                                    call_id=candidate.id,
                                    name=candidate.name,
                                    status="blocked",
                                    content=(
                                        "Deferred: this call still requires its own approval. "
                                        "Re-issue it as a separate call if it is still needed."
                                    ),
                                    metadata={"deferred_approval": True},
                                )
                                tool_results.append(
                                    await self._execute_call_and_writeback(
                                        state,
                                        candidate,
                                        blocked_results=blocked_results,
                                        step=step,
                                        index=index,
                                        history=history,
                                    )
                                )
                            decision = "continue"
                            step.decision = decision
                            final_decision = decision
                            state.metadata.pop("pending_approval", None)
                            state.metadata.pop("pending_waiting_request", None)
                            step.metadata.pop("pending_approval", None)
                            state.loop_state = decision
                            await self.kit.writeback(
                                state,
                                turn,
                                tool_results,
                                VerificationResult(passed=True),
                                decision,
                            )
                            await self._save_checkpoint(state)
                        else:
                            await self._emit_tool_waiting_for_approval(
                                state,
                                waiting_call,
                                response_index=index,
                            )
                            await self._emit_approval_request(
                                state,
                                waiting_call,
                                response_index=index,
                                request_id=request_id,
                            )
                            break
                parallel_names = set(self.policy.parallel_tool_names)
                can_parallelize_named_tools = (
                    bool(parallel_names)
                    and len(turn.tool_calls) > 1
                    and all(call.name in parallel_names for call in turn.tool_calls)
                )
                if not approval_batch_handled and (self.policy.parallel_tool_calls or can_parallelize_named_tools) and len(turn.tool_calls) > 1:
                    # Parallel execution (OpenAI Agents SDK style): emit all
                    # started events, run concurrently with optional cap,
                    # then emit finished events and write back in original order.
                    preflight = getattr(self.kit, "preflight_tool_calls", None)
                    if callable(preflight):
                        maybe_blocked = await preflight(state, turn.tool_calls)
                        if isinstance(maybe_blocked, dict):
                            blocked_results.update({
                                str(call_id): result
                                for call_id, result in maybe_blocked.items()
                                if isinstance(result, ToolResult)
                            })
                    for call in turn.tool_calls:
                        await self._emit_tool_started(state, call, response_index=index)
                    executable_calls = [call for call in turn.tool_calls if call.id not in blocked_results]
                    executed_results = await self._execute_tools_parallel(state, executable_calls, forensic_step=index) if executable_calls else []
                    # PostToolUse / PostToolUseFailure hooks for parallel execution
                    executed_results = [
                        await self._apply_post_tool_hook(state, call, result)
                        for call, result in zip(executable_calls, executed_results)
                    ] if executable_calls else []
                    executed_by_id = {call.id: result for call, result in zip(executable_calls, executed_results)}
                    tool_results = [
                        blocked_results.get(call.id) or executed_by_id[call.id]
                        for call in turn.tool_calls
                    ]
                    for call, result in zip(turn.tool_calls, tool_results):
                        step.tool_steps.append(RuntimeToolStep(call=call, result=result))
                        await self._emit_tool_finished(state, call, result, response_index=index)
                        tool_message = await self.kit.format_tool_result_for_model(state, call, result)
                        _stamp_message_origin(tool_message, state.turn_count)
                        history.append(tool_message)
                        await self._save_checkpoint(state)
                elif not approval_batch_handled:
                    # Sequential execution (OpenAI Codex default for shell-safety)
                    for call_index, call in enumerate(turn.tool_calls):
                        await self._emit_tool_started(state, call, response_index=index)
                        if call.id in blocked_results:
                            result = blocked_results[call.id]
                        else:
                            result = await self._execute_tool(state, call, forensic_step=index)
                            # PostToolUse / PostToolUseFailure hook
                            result = await self._apply_post_tool_hook(state, call, result)
                        tool_results.append(result)
                        step.tool_steps.append(RuntimeToolStep(call=call, result=result))
                        await self._emit_tool_finished(state, call, result, response_index=index)
                        # 5.9 Append formatted tool result to history
                        tool_message = await self.kit.format_tool_result_for_model(state, call, result)
                        _stamp_message_origin(tool_message, state.turn_count)
                        history.append(tool_message)
                        await self._save_checkpoint(state)
                        # Collect (do not yet apply) new guidance: the rest of the
                        # batch has to be written back first.  A provider rejects
                        # any tool result that does not directly follow the
                        # assistant message that requested it, so a guidance user
                        # message inserted here would orphan the skipped results
                        # behind it (2026-09-27: every steered sub-agent died with
                        # "Messages with role 'tool' must be a response to a
                        # preceding message with 'tool_calls'").
                        guidance = await self._collect_guidance(turn_input)
                        if not guidance:
                            continue
                        remaining_calls = turn.tool_calls[call_index + 1:]
                        for skipped_call in remaining_calls:
                            await self._emit_tool_started(state, skipped_call, response_index=index)
                            skipped = ToolResult(
                                call_id=skipped_call.id,
                                name=skipped_call.name,
                                status="blocked",
                                content="Skipped because new user guidance changed the active turn.",
                                metadata={"guidance_interrupted": True},
                            )
                            tool_results.append(skipped)
                            step.tool_steps.append(RuntimeToolStep(call=skipped_call, result=skipped))
                            await self._emit_tool_finished(
                                state, skipped_call, skipped, response_index=index
                            )
                            history.append(await self.kit.format_tool_result_for_model(
                                state, skipped_call, skipped
                            ))
                        if remaining_calls:
                            step.metadata["guidance_interrupted_tool_batch"] = True
                            await self._save_checkpoint(state)
                        await self._apply_guidance(state, history, index, guidance)
                        await self._acknowledge_guidance(turn_input, [
                            str(metadata["guidance_id"]) for _, metadata in guidance
                            if metadata.get("guidance_id")
                        ])
                        break

                # user:“直接把这个功能删掉，一点都不要留”+(工具调用不再附加汇报计数、提示或暂停门槛)。
                payload_reassessment_required = False
                duplicate_payload_blocked = any(
                    bool(result.metadata.get("duplicate_substantive_payload"))
                    for result in tool_results
                )
                for call, result in zip(turn.tool_calls, tool_results):
                    matched = payload_matches.get(call.id)
                    if matched is None or result.status in {"failed", "blocked"}:
                        continue
                    payload, prior_payload = matched
                    payload = {**payload, "challenged": False}
                    if prior_payload is not None and not bool(prior_payload.get("challenged")):
                        prior_payload["challenged"] = True
                        payload["challenged"] = True
                        payload_reassessment_required = True
                    recent_successful_payloads.append(payload)
                    del recent_successful_payloads[:-int(self.policy.identical_tool_result_window or 12)]
                if payload_reassessment_required:
                    history.append(ChatMessage(
                        role="user",
                        content=(
                            "[SUBSTANTIVE_PAYLOAD_REASSESSMENT_REQUIRED] A successful tool call reused a "
                            "materially identical large payload under different arguments. Reuse the existing "
                            "artifact or result, or explain what genuinely new evidence another call would add "
                            "before choosing a materially different action."
                        ),
                        metadata={"key": "substantive_payload_reassessment", "internal": True},
                    ))
                    step.metadata["substantive_payload_reassessment_required"] = True
                    await self._save_checkpoint(state)

                repeat_observation = self._observe_repeated_tool_failures(
                    turn.tool_calls,
                    tool_results,
                    recent_tool_result_fingerprints,
                    explicit_input_errors,
                )
                observation_audit = repeat_observation.get("audit")
                if isinstance(observation_audit, dict):
                    runtime_audit = state.metadata.get("runtime_audit")
                    if isinstance(runtime_audit, dict):
                        observations = runtime_audit.setdefault("no_progress_observations", [])
                        if isinstance(observations, list):
                            observations.append(observation_audit)
                            del observations[:-32]
                no_progress = repeat_observation.get("no_progress")
                if isinstance(no_progress, str) and no_progress:
                    step.decision = "wait"
                    step.metadata["no_progress"] = True
                    state.metadata["no_progress"] = {
                        "message": no_progress,
                        "response_index": index,
                        "recoverable": True,
                    }
                    state.metadata["pending_waiting_request"] = {
                        "request_kind": "no_progress",
                        "message": no_progress,
                    }
                    final_decision = "wait"
                    state.loop_state = "wait"
                    await self.kit.writeback(
                        state,
                        turn,
                        tool_results,
                        VerificationResult(passed=False, required=True, summary=no_progress),
                        "wait",
                    )
                    if self.policy.persist_steps:
                        state.metadata.setdefault("kernel_steps", []).append(self._summarize_step(step))
                    await self._save_checkpoint(state)
                    break
                recovery_prompt = repeat_observation.get("recovery_prompt")
                if isinstance(recovery_prompt, str) and recovery_prompt:
                    history.append(ChatMessage(
                        role="user",
                        content=recovery_prompt,
                        metadata={"key": "no_progress_recovery", "internal": True},
                    ))
                    step.metadata["no_progress_recovery_required"] = True
                    state.metadata["no_progress_recovery"] = {
                        "status": "required",
                        "response_index": index,
                    }
                    await self._save_checkpoint(state)

                failed_pairs = [
                    (call, result)
                    for call, result in zip(turn.tool_calls, tool_results)
                    if result.status == "failed"
                ]
                if failed_pairs:
                    consecutive_failure_rounds += 1
                    threshold = self.policy.consecutive_failure_rounds_threshold
                    if threshold and threshold > 0 and consecutive_failure_rounds >= threshold:
                        consecutive_failure_rounds = 0
                        prompt = self._failure_diagnosis_prompt(failed_pairs)
                        history.append(ChatMessage(
                            role="user",
                            content=prompt,
                            metadata={"key": "failure_diagnosis_required", "internal": True},
                        ))
                        step.metadata["failure_diagnosis_hint"] = True
                        state.metadata["failure_diagnosis"] = {
                            "status": "hint",
                            "response_index": index,
                            "consecutive_rounds": threshold,
                        }
                        await self._save_checkpoint(state)
                else:
                    consecutive_failure_rounds = 0

                # 5.10 Verify (non-blocking: verification failure does NOT
                #     trigger automatic repair retry. The model receives tool
                #     results directly and self-corrects on the next turn.)
                verification = await self.kit.verify(state, turn, tool_results)
                step.verification = verification

                for event in verification.events:
                    await self.event_sink.emit(event)
                    step.events.append(event)

                await self._emit_verification(state, verification)

                # 5.11 Decide next
                decision = await self.kit.decide_next(state, turn, verification, step)
                if turn.tool_calls and decision == "done":
                    # OpenAI/Claude-style loop contract: tool use is not a
                    # terminal answer. A run may only complete after the model
                    # returns a no-tool final response.
                    decision = "continue"
                    step.metadata["tool_calls_force_continue"] = True
                    state.metadata["tool_calls_force_continue"] = True
                elif decision == "done" and not turn.reply.strip():
                    # A natural completion must be visible final text. Empty
                    # no-tool output is not a successful answer.
                    decision = "wait"
                    step.metadata["done_without_final_text"] = True
                    state.metadata["done_without_final_text"] = True

                if decision == "done" and not turn.tool_calls:
                    if await self._consume_guidance(state, turn_input, history, index):
                        decision = "continue"
                        step.metadata["guidance_force_continue"] = True
                    # Members are NOT consumed here, and the members-running fact
                    # is not published here either: a final no-tool answer can
                    # still be turned back into a continue by the completion gate
                    # below, so publishing now would latch the fact on a turn that
                    # is still running. It is published once, after the terminal
                    # status is written (see _run).

                if decision == "done" and self.completion_gate is not None:
                    should_verify = getattr(self.completion_gate, "should_verify", None)
                    if callable(should_verify) and not should_verify(state):
                        state.metadata.pop("goal_completion", None)
                        step.metadata.pop("goal_completion", None)
                    else:
                        completion = await self.completion_gate.verify(state, {
                            "session_id": state.session_id,
                            "turn_input": turn_input,
                            "turn": turn,
                            "tool_results": tool_results,
                            "verification": verification,
                            "step": step,
                            "history": list(history),
                        })
                        state.metadata["goal_completion"] = completion.to_dict()
                        step.metadata["goal_completion"] = completion.to_dict()
                        if not completion.passed:
                            if completion.blocked:
                                decision = "wait"
                            else:
                                repair_instruction = completion.repair_instruction.strip()
                                if not repair_instruction:
                                    repair_instruction = (
                                        "The active goal is not complete. Address the remaining gap, "
                                        "then provide a new final response."
                                    )
                                history.append(ChatMessage(
                                    role="user",
                                    content=f"[GOAL_INCOMPLETE] {repair_instruction}",
                                    metadata={"key": "goal_incomplete", "internal": True},
                                ))
                                await self._save_checkpoint(state)
                                decision = "continue"

                # Completion verification can continue the run. Seal guidance
                # only after it passes, and catch input arriving while it awaits.
                if decision == "done" and not turn.tool_calls:
                    if await self._consume_guidance(state, turn_input, history, index, finalize=True):
                        decision = "continue"
                        step.metadata["guidance_force_continue"] = True
                step.decision = decision
                final_decision = decision

                # Update LoopPhase from Kit
                step.phase = state.position if state.position in ("idle", "plan", "execute", "verify") else "execute"

                # 5.12 Writeback
                await self.kit.writeback(state, turn, tool_results, verification, decision)
                await self._emit_checklist_snapshots(
                    state,
                    turn,
                    tool_results,
                    response_index=index,
                )

                # Update state
                state.loop_state = decision

                # 5.12b Persist step summary (OpenAI Rollout-style audit trail)
                if self.policy.persist_steps:
                    steps_log = state.metadata.setdefault("kernel_steps", [])
                    steps_log.append(self._summarize_step(step))

                # 5.13 Save state
                await self._save_checkpoint(state)

                # 5.14 Break on terminal decisions
                if decision != "continue":
                    break
                index += 1

            except MemoryError as e:
                # Host memory exhaustion gets its own branch: it is the most
                # common way a long turn dies, and it needs the threshold text
                # the resume watchdog honours (runtime/memory_guard.py). The
                # generic branch below would report "Unexpected error: " with an
                # empty detail, because MemoryError's str() is empty.
                _logger.error(
                    "[kernel:_run] host memory exhausted sid=%s step=%d",
                    state.session_id, index,
                )
                error_msg = self._record_memory_exhaustion(state)
                step.error = error_msg
                final_decision = "failed"
                break
            except KernelError as e:
                error_msg = str(e)
                if is_memory_exhaustion(e):
                    error_msg = self._record_memory_exhaustion(state)
                step.error = error_msg
                final_decision = "failed"
                break
            except ContextCompactionError as e:
                error_msg = str(e)
                step.error = error_msg
                final_decision = "failed"
                break
            except _KernelPause:
                # The pause was requested while this step was streaming. The
                # step leaves no trace of its own (no answer, no tool result);
                # everything already committed stays, which is what the resumed
                # run continues from.
                error_msg = "paused"
                step.error = error_msg
                step.decision = "paused"
                final_decision = "failed"
                break
            except Exception as e:
                if getattr(e, "budget_exhausted", False):
                    error_msg = str(e)
                    step.error = error_msg
                    final_decision = "failed"
                    break
                _logger.exception("[kernel:_run] unexpected error sid=%s step=%d",
                                  state.session_id, index)
                error_msg = f"Unexpected error: {e}"
                if is_memory_exhaustion(e):
                    error_msg = self._record_memory_exhaustion(state)
                step.error = error_msg
                final_decision = "failed"
                break
            finally:
                self.tracer.end_span(
                    step_span,
                    status="error" if step.error else "ok",
                    decision=step.decision,
                )

        # Update final status
        state.status = _status_from_decision(final_decision)
        # Cancelled is a distinct RuntimeStatus even though it flows through
        # the "failed" decision path for backward compatibility with Kit
        # decision-matching (which expects only continue/wait/done/failed).
        if error_msg == "cancelled":
            state.status = "cancelled"
        elif error_msg == "paused":
            # A pause is not a failure: the turn keeps its place and the user
            # continues it later. ``loop_state`` carries the same word so the
            # runtime store tells a paused turn apart from a waiting one.
            state.status = "paused"
            state.loop_state = "paused"
        elif str(state.metadata.get("failure_code") or "") == HOST_MEMORY_EXHAUSTED:
            # Running out of host memory parks the turn rather than failing it:
            # the resume watchdog continues it once memory is available again.
            # The reason rides the metadata so the log can tell this pause apart
            # from a user pause while the interface shows one paused state.
            state.status = "paused"
            state.loop_state = "paused"
            state.metadata["pause_reason"] = "host_memory"
            _logger.warning(
                "[kernel:_run] paused after host memory exhaustion sid=%s",
                state.session_id,
            )
        else:
            state.loop_state = final_decision
        if str(state.metadata.get("failure_code") or "") != HOST_MEMORY_EXHAUSTED:
            # This turn did not end in memory exhaustion, so the chain of
            # consecutive memory interruptions is broken: the next one gets the
            # full auto-resume budget again. The previous explanation goes with
            # it — otherwise a later, unrelated failure would inherit "memory
            # exhausted" and could arm a resume nothing asked for.
            clear_memory_resume_streak(state)
            clear_failure_detail(state)
        await self._persist_history_tail(state, history)

        # Build result
        result = KernelResult(
            session_id=state.session_id,
            run_id=state.run_id,
            decision=final_decision,
            message=latest_message,
            steps=steps,
            state=state,
            error=error_msg,
        )

        # Collect all artifacts from steps into result metadata
        all_artifacts = []
        for s in steps:
            step_artifacts = s.metadata.get("artifacts", [])
            if step_artifacts:
                all_artifacts.extend(step_artifacts)
        if all_artifacts:
            result.metadata["artifacts"] = all_artifacts

        # 7-8. Converge the terminal tail: Kit on_run_end, Stop hook, terminal
        # event, and trace span close — shared with the cancel path so a
        # cancelled run notifies observers identically (audit 02).
        await self._finalize_run(state, result, run_span)
        self._run_span = None
        # Publish the members-running fact only now that the turn's terminal
        # status is written. Done from inside the loop it could ride a turn that
        # was still running (the completion gate at the done decision can set a
        # continue), and the interface reads any fact on a running turn as "the
        # main agent stopped" — which hid the stop affordance during a real run.
        # The supervisor records this turn so it can retract the fact when the
        # last of these members finishes.
        if final_decision == "done":
            await self._announce_active_members(state, max(len(steps) - 1, 0))

        return result

    async def _begin_run(
        self,
        state: RuntimeState,
        turn_input: RuntimeTurnInput,
        history: list[ChatMessage],
    ) -> list[ChatMessage]:
        """Mark the run running, run the start hooks, persist this turn's input.

        Extracted so ``_run`` can guard the whole setup with one try/except:
        the caller converges a failed setup into a ``failed`` KernelResult
        (2026-09-25 audit P3).  Returns the messages appended to history.
        """
        # Mark running
        previous_status = str(state.status or "")
        previous_owner = read_owner(state.metadata)
        state.status = "running"
        # A new turn means nothing is waiting to be resumed in this thread: the
        # user (or the resume watchdog, which clears the descriptor before it
        # starts) has moved on. Without this, a turn sent by hand while an
        # auto-resume was armed would be continued a second time later. The
        # previous failure's explanation goes too — a turn that has not failed
        # yet must not advertise an old reason.
        clear_pending_memory_resume(state)
        clear_failure_detail(state)
        # The automatic member wake has the same "a new turn moves the thread on"
        # rule, but its own continuation turn must not reset the streak it is
        # counting: the watchdog marks the state before starting that turn, so
        # only a turn the user (or the memory resume) started clears the streak.
        if not consume_member_wake_autostart(state):
            clear_member_wake_streak(state)
        # A run that was in flight but belongs to a process that is gone is
        # being taken over here.  Leave a durable trace instead of silently
        # overwriting it, so a crashed CLI run can be told apart from a clean
        # continuation when reading the session later.
        if previous_status in LIVE_RUN_STATES and not is_own_token(previous_owner):
            state.metadata["adopted_stale_run"] = {
                "previous_run_id": state.run_id,
                "previous_status": previous_status,
                "previous_owner": previous_owner,
                "adopted_at": time_module.time(),
            }
            _logger.warning(
                "[kernel:_run] adopting stale session %s (previous run %s, status %s, owner pid %s)",
                state.session_id,
                state.run_id,
                previous_status,
                previous_owner.get("pid"),
            )
        await self.state_store.save(state)
        _logger.info("[kernel:_run] state saved as running sid=%s", state.session_id)

        # Kit on_run_start
        await self.kit.on_run_start(state, turn_input)
        # Expose the empty-response retry budget to the Kit (which owns
        # empty-stop retry logic in decide_next). The Kit reads this from
        # state.metadata instead of holding a separate policy reference.
        if state.metadata is None:
            state.metadata = {}
        state.metadata.setdefault("empty_response_retries", int(self.policy.empty_response_retries or 0))

        # SessionStart hook
        await self._apply_session_start_hook(state, turn_input)

        # Extend persisted conversation history with this user input.
        current_user_content = (
            turn_input.user_content
            if turn_input.user_content is not None
            else turn_input.user_message
        )
        # UserPromptSubmit hook（先于消息入历史——hook 的
        # additional_context 注入用户消息并随历史持久化，C2 共识）。
        hook_user_content = (
            None if turn_input.metadata.get("origin") == "turn_resume"
            else await self._apply_user_prompt_submit_hook(state, turn_input, current_user_content)
        )
        if hook_user_content:
            current_user_content = hook_user_content
        new_messages: list[ChatMessage] = []
        if current_user_content:
            turn_origin = str(
                turn_input.metadata.get("origin")
                or turn_input.metadata.get("turn_origin")
                or ""
            ).strip()
            if turn_origin in {"member_wake", "turn_resume"}:
                # The live transcript already records this input as the
                # systemMessage item. Keep the model-visible copy as one
                # marked system entry at the history tail so OpenAI-style
                # protocols preserve its role/order and Anthropic/Gemini can
                # apply their explicit trailing-user fallback.
                user_msg = ChatMessage(
                    role="system",
                    content=current_user_content,
                    metadata={
                        "origin": turn_origin,
                        TAIL_SYSTEM_MESSAGE_MARKER: True,
                        **(
                            {"turn_id": str(state.metadata.get("turn_id") or state.run_id).strip()}
                            if str(state.metadata.get("turn_id") or state.run_id).strip()
                            else {}
                        ),
                    },
                )
            else:
                user_msg = ChatMessage(role="user", content=current_user_content,
                                       metadata={"turn_id": str(state.metadata.get("turn_id") or state.run_id)})
            if turn_input.metadata.get(GOAL_CONTINUATION_KEY):
                user_msg.metadata[GOAL_CONTINUATION_KEY] = True
            initial_ids = list(turn_input.metadata.get("initial_guidance_ids") or [])
            if initial_ids:
                user_msg.metadata["guidance_ids"] = initial_ids
            known_ids = {
                str(message_id) for message in history
                for message_id in message.metadata.get("guidance_ids", [])
            }
            if not initial_ids or not set(initial_ids).issubset(known_ids):
                # user:“作为下一轮的输入时，它应该是以自己本身的清晰度输入”+用户本轮带入的图片
                # 和下一条工具图片使用同一个计数口径，保证第一次请求仍看原图。
                _stamp_message_origin(user_msg, state.turn_count)
                history.append(user_msg)
                new_messages.append(user_msg)
        # user:“不是合并成一条消息，是都追加进去，但不是同一条消息”+排队消息保持原样，
        # 目标提醒单独成一条，压缩时只剔除提醒。
        reminder = str(turn_input.metadata.get("goal_continuation_text") or "").strip()
        if reminder:
            reminder_msg = goal_continuation_message(reminder)
            history.append(reminder_msg)
            new_messages.append(reminder_msg)
        await self._append_history_checkpoint(state, new_messages)
        _logger.info("[kernel:_run] checkpoint saved sid=%s", state.session_id)
        return new_messages

    async def _finalize_run(
        self, state: RuntimeState, result: KernelResult, run_span: Any | None = None
    ) -> None:
        """Run the terminal convergence sequence for a kernel run.

        Shared by the normal finish path and the external-cancellation path:
        Kit ``on_run_end``, Stop hook, terminal event, and trace span close.
        Each step is individually guarded so a hook failure can never swallow
        the result or strand the span (audit 02 / 05).
        """
        try:
            await self.kit.on_run_end(state, result)
        except Exception:
            _logger.exception(
                "[kernel:_finalize_run] on_run_end failed sid=%s", state.session_id
            )
        try:
            await self._apply_session_stop_hook(state, result)
        except Exception:
            _logger.exception(
                "[kernel:_finalize_run] Stop hook failed sid=%s", state.session_id
            )
        try:
            await self._emit_terminal_event(state, result)
        except Exception:
            _logger.exception(
                "[kernel:_finalize_run] terminal event failed sid=%s", state.session_id
            )
        if run_span is not None:
            self.tracer.end_span(
                run_span,
                status="error" if result.decision == "failed" else "ok",
                decision=result.decision,
                steps=len(result.steps),
            )

    async def _persist_external_cancellation(
        self,
        turn_input: RuntimeTurnInput,
        *,
        history: list[ChatMessage] | None,
        run_span: Any | None,
    ) -> None:
        state = turn_input.state
        if state is None:
            session_id = str(turn_input.metadata.get("session_id") or "")
            state = await self.state_store.get(session_id) if session_id else None
        if state is None:
            return
        expected_run_id = str(turn_input.run_id or "").strip()
        if expected_run_id and state.run_id != expected_run_id:
            return
        state.status = "cancelled"
        state.loop_state = "failed"
        state.metadata.pop("pending_approval", None)
        state.metadata.pop("pending_waiting_request", None)
        # Persist what this run already produced. The store holds only the rows
        # written at run start (the user message); assistant replies and tool
        # results are still in the live list until loop exit, so reloading from
        # the store here discarded them and the next message was sent with no
        # record of the stopped turn. Fall back to the store only when the run
        # never reached the history load.
        if history is None:
            history = await self._load_history(state.session_id)
        await self._persist_history_tail(state, history)

        # Converge the same terminal tail as the normal finish path (audit 02:
        # the cancel path previously skipped on_run_end / Stop hook / terminal
        # event and leaked the run span).
        result = KernelResult(
            session_id=state.session_id,
            run_id=state.run_id,
            decision="failed",
            message="",
            steps=[],
            state=state,
            error="cancelled",
        )
        await self._finalize_run(state, result, run_span)
        self._run_span = None

    async def _persist_external_pause(
        self,
        turn_input: RuntimeTurnInput,
        *,
        history: list[ChatMessage] | None,
        run_span: Any | None,
    ) -> None:
        """Converge a run that was torn down for a pause instead of a cancel.

        The pause request sets the registry pause event, and any in-flight tool
        that cannot check it is aborted with ``task.cancel()``; both roads must
        end in the resumable ``paused`` state, never in ``cancelled``. Otherwise
        the shape mirrors the cancellation path, including persisting the live
        history tail so the resumed run keeps every finished step.
        """
        state = turn_input.state
        if state is None:
            session_id = str(turn_input.metadata.get("session_id") or "")
            state = await self.state_store.get(session_id) if session_id else None
        if state is None:
            return
        expected_run_id = str(turn_input.run_id or "").strip()
        if expected_run_id and state.run_id != expected_run_id:
            return
        state.status = "paused"
        state.loop_state = "paused"
        # The parked approval/question descriptors belong to a run that is no
        # longer executing; the resumed run rebuilds them from the committed
        # request rows.
        state.metadata.pop("pending_approval", None)
        state.metadata.pop("pending_waiting_request", None)
        if history is None:
            history = await self._load_history(state.session_id)
        try:
            await self._persist_history_tail(state, history)
        except Exception:
            # The app layer settles the paused state itself before this detached
            # writer runs, so its own write wins and this one can be refused by
            # the owner guard. That is a race between two writers of the same
            # parked state, not a failure: only report it when the stored state
            # does not already say paused.
            stored = await self.state_store.get(state.session_id)
            if stored is None or str(getattr(stored, "status", "") or "") != "paused":
                raise
            _logger.info(
                "[kernel] pause state already settled by the app layer sid=%s",
                state.session_id,
            )

        result = KernelResult(
            session_id=state.session_id,
            run_id=state.run_id,
            decision="failed",
            message="",
            steps=[],
            state=state,
            error="paused",
        )
        await self._finalize_run(state, result, run_span)
        self._run_span = None

    @staticmethod
    def _tool_call_fingerprint(call: ToolCall) -> str:
        return json.dumps(
            {"tool": call.name, "arguments": call.arguments},
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )

    @staticmethod
    def _substantive_tool_payload(call: ToolCall) -> dict[str, Any] | None:
        values: list[str] = []

        def collect(value: Any) -> None:
            if isinstance(value, str):
                if len(value) >= _TOOL_INPUT_PROGRESS_CHARS:
                    values.append(value)
                return
            if isinstance(value, dict):
                for nested in value.values():
                    collect(nested)
                return
            if isinstance(value, list):
                for nested in value:
                    collect(nested)

        collect(call.arguments)
        if not values:
            return None
        return CoreLoopKernel._substantive_text_signature(call.name, values)

    @staticmethod
    def _substantive_text_signature(tool: str, values: list[str]) -> dict[str, Any]:
        exact = hashlib.sha256(
            json.dumps(values, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        lines = {
            hashlib.sha256(line.strip().encode("utf-8")).hexdigest()
            for value in values
            for line in value.splitlines()
            if line.strip()
        }
        return {"tool": tool, "exact": exact, "lines": lines}

    @staticmethod
    def _substantive_payloads_match(left: dict[str, Any], right: dict[str, Any]) -> bool:
        if left.get("tool") != right.get("tool"):
            return False
        if left.get("exact") == right.get("exact"):
            return True
        left_lines = left.get("lines")
        right_lines = right.get("lines")
        if not isinstance(left_lines, set) or not isinstance(right_lines, set):
            return False
        smaller = min(len(left_lines), len(right_lines))
        if smaller < 8:
            return False
        return len(left_lines & right_lines) / smaller >= 0.98

    @staticmethod
    def _is_explicit_input_error(result: ToolResult) -> bool:
        metadata = result.metadata if isinstance(result.metadata, dict) else {}
        return result.status == "failed" and metadata.get("input_error") is True

    @staticmethod
    def _failure_diagnosis_prompt(
        failed_pairs: list[tuple[ToolCall, ToolResult]],
    ) -> str:
        def bounded(value: Any, limit: int) -> str:
            text = str(value or "")
            if len(text) <= limit:
                return text
            return f"{text[:limit]}\n...[truncated {len(text) - limit} characters]"

        evidence = [
            {
                "tool": call.name,
                "arguments": bounded(
                    json.dumps(call.arguments, ensure_ascii=False, sort_keys=True, default=str),
                    2_000,
                ),
                "status": result.status,
                "content": bounded(result.content, 4_000),
                "error": bounded(result.error, 4_000),
                "error_code": result.error_code,
                "exit_code": result.metadata.get("exit_code"),
                "error_type": result.metadata.get("error_type"),
                "timed_out": result.metadata.get("timed_out"),
            }
            for call, result in failed_pairs
        ]
        return (
            "[FAILURE_DIAGNOSIS_REQUIRED] Multiple consecutive rounds have failed tool calls. "
            "Pause and investigate root causes before continuing. "
            "Suggested format: 根因 (root cause), 证据 (evidence), 修复方向 (fix direction), 验证信号 (verification signal). "
            "Do not repeat the exact failing call with the same arguments.\n"
            f"Failure evidence:\n{json.dumps(evidence, ensure_ascii=False, sort_keys=True, default=str)}"
        )

    def _observe_repeated_tool_failures(
        self,
        calls: list[ToolCall],
        results: list[ToolResult],
        recent_fingerprints: list[str],
        explicit_input_errors: dict[str, ToolResult],
    ) -> dict[str, Any]:
        threshold = self.policy.max_identical_tool_results
        if threshold is None or threshold <= 0:
            return {}
        window = max(threshold, int(self.policy.identical_tool_result_window or threshold))
        observation: dict[str, Any] = {}
        for call, result in zip(calls, results):
            call_fingerprint = self._tool_call_fingerprint(call)
            if self._is_explicit_input_error(result):
                explicit_input_errors[call_fingerprint] = result
            fingerprint = json.dumps(
                {
                    "tool": call.name,
                    "arguments": call.arguments,
                    "status": "failed" if result.metadata.get("duplicate_input_error") else result.status,
                    "content": result.content,
                    "error": result.error,
                    "exit_code": result.metadata.get("exit_code"),
                    "error_type": result.metadata.get("error_type"),
                    "timed_out": result.metadata.get("timed_out"),
                },
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
            recent_fingerprints.append(fingerprint)
            if len(recent_fingerprints) > window:
                del recent_fingerprints[:-window]
            count = recent_fingerprints.count(fingerprint)
            audit = {
                "fingerprint_sha256": hashlib.sha256(fingerprint.encode("utf-8")).hexdigest(),
                "count": count,
                "window": window,
                "threshold": threshold,
            }
            if count >= threshold:
                status_label = "failed" if result.status in {"failed", "blocked"} else "successful"
                return {"audit": audit, "no_progress": (
                    "No progress observed: the same exact tool call and result "
                    f"occurred {count} times within the last {window} tool results. "
                    "The run is paused and can be resumed after changing the approach or explicitly continuing."
                )}
            if count > 1:
                observation["audit"] = audit
        return observation

    async def _load_history(self, session_id: str, *, after_seq: int = 0) -> list[ChatMessage]:
        if not isinstance(self.state_store, RuntimeCheckpointStore):
            return []
        raw_history = await self.state_store.get_history(session_id, after_seq=after_seq)
        messages: list[ChatMessage] = []
        for index, item in enumerate(raw_history):
            message = _chat_message_from_dict(item)
            if message is None:
                continue
            # Tag each loaded message with its persistent row seq (based on the
            # raw row order, before repair) so context compaction can anchor the
            # resume boundary at the first retained message instead of the
            # tail of history.  Rows written by this version already carry the
            # tag; older rows get it filled in here.  The tag is stripped from
            # model-bound requests, never from persisted history.
            if isinstance(message.metadata, dict) and "history_seq" not in message.metadata:
                message.metadata["history_seq"] = after_seq + index + 1
            messages.append(message)
        # Skip persisted summary rows: compaction summaries live in
        # state.metadata only and must never appear as history rows (legacy
        # pollution guard — the summary is prepended below instead).
        messages = [
            message
            for message in messages
            if not (
                message.role == "system"
                and message.metadata.get("key") == "context_compaction_summary"
            )
        ]
        return _repair_incomplete_tool_history(messages, session_id=session_id)

    async def _history_max_seq(self, session_id: str) -> int | None:
        """Read the durable history high-water mark when the store exposes it."""
        getter = getattr(self.state_store, "history_max_seq", None)
        if not callable(getter):
            return None
        try:
            value = getter(session_id)
            if inspect.isawaitable(value):
                value = await value
            if isinstance(value, bool):
                return None
            return max(0, int(value))
        except (TypeError, ValueError, OSError):
            return None

    async def _save_checkpoint(self, state: RuntimeState) -> None:
        """Persist runtime state metadata (mid-loop checkpoint) and the history tail.

        State is saved on every mid-loop step. The conversation history rides
        along as an incremental append of only the unpersisted tail — messages
        reach history complete, so an early flush is always well-formed. This
        is what makes loop exit / external cancellation cheap: there is no
        whole-session rewrite left to do when a run ends.
        """
        await self._flush_history_delta(state, self._live_history)
        await self.state_store.save(state)

    @staticmethod
    def _is_request_local_summary(message: ChatMessage) -> bool:
        return (
            message.role == "system"
            and isinstance(message.metadata, dict)
            and message.metadata.get("key") == "context_compaction_summary"
        )

    async def _flush_history_delta(
        self, state: RuntimeState, history: list[ChatMessage] | None
    ) -> None:
        """Append unpersisted live-history messages as new store rows.

        Only valid while the live list still aligns with the row table: the
        alignment counter starts at the loaded length and advances with each
        flush, and outside writers (approval backfill, sub-agent approval)
        only append between runs — each run re-aligns at load. A request-local
        compaction rewrote the list mid-run → ``_persisted_len`` is None and
        this becomes a no-op; ``_persist_history_tail`` falls back to a full
        replace there.
        """
        if history is None or not isinstance(self.state_store, RuntimeCheckpointStore):
            return
        start = self._persisted_len
        if start is None or start >= len(history):
            return
        pending = [
            message
            for message in history[start:]
            if not self._is_request_local_summary(message)
        ]
        if pending:
            await self._append_durable_messages(state, pending)
        self._persisted_len = len(history)

    async def _append_durable_messages(self, state: RuntimeState, messages: list[ChatMessage]) -> None:
        # user:“去重构吧”+(原始消息持续追加，使用存储实际分配的序号锚定摘要视图)。
        rows = [message.to_dict() for message in messages]
        await self.state_store.append_history(state.session_id, rows)
        # Production stores return assigned sequences through each row. The
        # high-water fallback keeps legacy test/plugin stores compatible.
        maximum = None
        if any(not row.get("metadata", {}).get("history_seq") for row in rows):
            maximum = await self._history_max_seq(state.session_id)
        for index, (message, row) in enumerate(zip(messages, rows)):
            seq = row.get("metadata", {}).get("history_seq")
            if not isinstance(seq, int) and maximum is not None:
                seq = maximum - len(rows) + index + 1
            if isinstance(seq, int) and seq > 0:
                message.metadata["history_seq"] = seq

    async def _persist_history_tail(
        self, state: RuntimeState, history: list[ChatMessage]
    ) -> None:
        """Persist the unpersisted history tail at loop exit / cancellation.

        Aligned runs append only the delta; runs whose in-memory list was
        rewritten by request-local compaction keep the exact historical
        contract of one full ``replace_history`` (renumbering + boundary
        re-anchor) because the compaction decision must land atomically.
        """
        if self._persisted_len is None or not isinstance(self.state_store, RuntimeCheckpointStore):
            await self._replace_history_checkpoint(state, history)
            self._persisted_len = len(history)
            return
        await self._flush_history_delta(state, history)
        # The terminal status/loop_state are applied after the last mid-loop
        # checkpoint; the old full-replace path persisted them via its
        # trailing save. Keep that contract on the incremental path too.
        await self.state_store.save(state)

    async def _append_history_checkpoint(
        self, state: RuntimeState, messages: list[ChatMessage]
    ) -> None:
        """Append new messages to incremental history storage and save state.

        Used after appending a user message — only the new messages are
        written, avoiding a full history rewrite.
        """
        if isinstance(self.state_store, RuntimeCheckpointStore):
            if messages:
                await self._append_durable_messages(state, messages)
            await self.state_store.save(state)
            return
        await self.state_store.save(state)

    async def _replace_history_checkpoint(
        self, state: RuntimeState, history: list[ChatMessage]
    ) -> None:
        """Replace the entire persisted history (after compaction / truncation).

        Falls back to ``save_checkpoint`` for stores that don't support
        incremental operations.
        """
        if isinstance(self.state_store, RuntimeCheckpointStore):
            # Compaction summaries are request-local context rows. Keep them
            # available to later steps in this run, but never persist them or
            # let them shift the resume marker index during a full rewrite.
            persisted_history = [
                message
                for message in history
                if not (
                    message.role == "system"
                    and message.metadata.get("key") == "context_compaction_summary"
                )
            ]
            self._recompute_compaction_boundary(state, persisted_history)
            await self.state_store.replace_history(
                state.session_id, [m.to_dict() for m in persisted_history]
            )
            # ``replace_history`` assigns fresh row sequence numbers.  The
            # manual-compaction filter set belongs to the old numbering and
            # must not survive a successful rewrite; keeping it until after
            # the write preserves crash recovery if the rewrite fails.
            compaction = state.metadata.get("context_compaction") if isinstance(state.metadata, dict) else None
            if isinstance(compaction, dict):
                compaction.pop("compacted_history_seqs", None)
            await self.state_store.save(state)
            return
        await self.state_store.save(state)

    @staticmethod
    def _recompute_compaction_boundary(
        state: RuntimeState, history: list[ChatMessage]
    ) -> None:
        """Re-anchor ``summary_seq`` after a full replace renumbers the rows.

        The resume marker travels with the first retained message; the newest
        marker wins because each compaction keeps a smaller tail.  When no
        marker is present and the stored anchor exceeds the rewritten row
        count, the anchor is stale (history was rebuilt) — reset to zero so
        the next run loads everything instead of nothing.
        """
        if not isinstance(state.metadata, dict):
            return
        compaction = state.metadata.get("context_compaction")
        if not isinstance(compaction, dict):
            return
        marker_indexes = [
            index
            for index, message in enumerate(history)
            if message.metadata.get("lam_compaction_resume") is True
        ]
        if marker_indexes:
            compaction["summary_seq"] = max(marker_indexes)
        elif int(compaction.get("summary_seq") or 0) > len(history):
            compaction["summary_seq"] = 0

    async def _stream_model(
        self,
        request: LLMRequest,
        state: RuntimeState,
        *,
        response_index: int,
    ) -> LLMResponse | None:
        """Try streaming model call.  Returns a complete LLMResponse on success,
        or None when streaming is not available so the caller can fall back."""
        _logger.info("[kernel:_stream_model] starting stream sid=%s run=%s model=%s",
                      state.session_id, state.run_id, request.model)
        stream = stream_with_retry(
            self.llm_client,
            request,
            max_attempts=self.policy.model_retries,
            # Streaming is bounded per idle gap by _next_stream_event().
            # Retries only apply to stream-setup failures — once the stream
            # starts emitting tokens, mid-stream errors cannot be replayed
            # and are NOT retried.  The non-streaming fallback remains
            # bounded by model_timeout_seconds.
            timeout_seconds=None,
            retry_policy=self.retry_policy,
            on_retry=lambda retry: self._emit_model_retry_from_event(
                retry,
                state=state,
                response_index=response_index,
            ),
            sleep=asyncio.sleep,
        )

        accumulated = ""
        thinking = ""
        emitted_text = ""
        emitted_thinking = ""
        pending_tool_calls: dict[int, dict] = {}
        emitted_tool_call_indexes: set[int] = set()
        emitted_tool_input_arguments: dict[int, str] = {}
        # Some providers send usage in a standalone chunk (usage present but no
        # delta / finish_reason); keep it so the done event can carry it.
        pending_usage = None
        # Some providers (DeepSeek-style) fold finish_reason into the same
        # chunk as the last content/thinking delta instead of emitting a
        # separate done chunk (audit 10 S3). Track it so the stream-ended
        # fallback below still reports the real finish reason + usage.
        stream_finish_reason: str | None = None
        terminal_tool_calls: list[LLMToolCall] = []
        provider_state: Any = None
        cache_diagnostic_route: dict[str, Any] | None = None
        # Time-to-first-event is measured from here: constructing the generator
        # sends nothing, the first __anext__ is what crosses the network.  A
        # stalled gateway shows up as a large ttft, never as a large elapsed.
        _dispatch_at = time_module.monotonic()
        _first_event_seen = False
        try:
            stream_iterator = stream.__aiter__()
            while True:
                try:
                    event = await self._next_stream_event(stream_iterator)
                except StopAsyncIteration:
                    break
                if not _first_event_seen:
                    _first_event_seen = True
                    _logger.info(
                        "[kernel:_stream_model] step=%s first stream event sid=%s "
                        "kind=%s ttft=%.2fs",
                        response_index, state.session_id, event.kind,
                        time_module.monotonic() - _dispatch_at,
                    )
                # Cooperative cancel during streaming: the app-layer Stop
                # button sets the registry cancel event. Abort the stream
                # immediately rather than waiting for the model to finish —
                # without this a long/slow stream makes Stop appear to do
                # nothing (the 2b34c636 "stop 无效" symptom).
                if self._is_external_cancelled():
                    raise asyncio.CancelledError()
                if self._external_pause_requested():
                    # Abort the stream and drop everything received so far: a
                    # paused step keeps no half-written answer, so the resumed
                    # run asks the model for that step again.
                    _logger.info(
                        "[kernel:_stream_model] paused mid-stream sid=%s step=%s chars=%d reason=%s",
                        state.session_id,
                        response_index,
                        len(accumulated),
                        str(state.metadata.get("pause_reason") or self._pause_reason or "user_pause"),
                    )
                    raise _KernelPause()
                event_finish_reason = event.finish_reason or (
                    event.metadata.get("finish_reason") if event.metadata else None
                )
                if event_finish_reason:
                    stream_finish_reason = str(event_finish_reason)
                if event.usage is not None:
                    # A few gateways attach usage to the final content/tool
                    # delta instead of sending a separate usage-only chunk.
                    pending_usage = event.usage
                if event.provider_state is not None:
                    provider_state = copy.deepcopy(event.provider_state)
                route = event.metadata.get("cache_diagnostic_route") if isinstance(event.metadata, dict) else None
                if isinstance(route, dict):
                    cache_diagnostic_route = dict(route)
                if event.kind == "content_delta" and event.content:
                    accumulated += event.content
                    await self.event_sink.emit(CoreEvent(
                        name="runtime.reply_delta",
                        category="message",
                        payload={
                            "content": event.content,
                            "part_id": f"{state.run_id}:response-{response_index}:text",
                            "response_index": response_index,
                        },
                        session_id=state.session_id,
                        run_id=state.run_id,
                        tags=["reply"],
                        metadata={"delivery": "transient"},
                    ))
                    if not emitted_text or len(accumulated) - len(emitted_text) >= _STREAM_TEXT_PROGRESS_CHARS:
                        await self._emit_stream_part(
                            state,
                            part_id=f"{state.run_id}:response-{response_index}:text",
                            part_type="text",
                            status="running",
                            label="输出",
                            content=accumulated,
                            response_index=response_index,
                            raw=event.raw,
                            # Transient: streaming progress snapshots are UI-only.
                            # Persisting them on the hot path means projecting the
                            # whole thread snapshot per 128 chars (measured 1.7-2.3s
                            # on 55MB threads) — the final state is persisted once
                            # when the turn finishes.
                            transient=True,
                        )
                        emitted_text = accumulated
                elif event.kind == "thinking_delta" and event.content:
                    thinking += event.content
                    await self._emit_stream_part(
                        state,
                        part_id=f"{state.run_id}:response-{response_index}:reasoning",
                        part_type="reasoning",
                        status="running",
                        label="思考",
                        delta=event.content,
                        response_index=response_index,
                        raw=event.raw,
                        transient=True,
                    )
                    if not emitted_thinking or len(thinking) - len(emitted_thinking) >= _STREAM_TEXT_PROGRESS_CHARS:
                        await self._emit_stream_part(
                            state,
                            part_id=f"{state.run_id}:response-{response_index}:reasoning",
                            part_type="reasoning",
                            status="running",
                            label="思考",
                            content=thinking,
                            response_index=response_index,
                            raw=event.raw,
                            transient=True,
                        )
                        emitted_thinking = thinking
                elif event.kind == "refusal_delta" and event.refusal:
                    await self.event_sink.emit(CoreEvent(
                        name="runtime.reply_delta",
                        category="message",
                        payload={
                            "content": "",
                            "refusal": event.refusal,
                        },
                        session_id=state.session_id,
                        run_id=state.run_id,
                        tags=["reply", "refusal"],
                    ))
                elif event.kind == "tool_call_delta":
                    tc_delta = event.metadata.get("tool_calls_delta") if event.metadata else None
                    if tc_delta:
                        pending_tool_calls = merge_tool_call_deltas(pending_tool_calls, {"tool_calls": tc_delta})
                        for tool_index in sorted(pending_tool_calls):
                            if tool_index in emitted_tool_call_indexes:
                                continue
                            fn = pending_tool_calls[tool_index].get("function")
                            if not isinstance(fn, dict) or not str(fn.get("name") or "").strip():
                                continue
                            await self._emit_stream_tool_call_part(
                                state,
                                response_index=response_index,
                                tool_index=tool_index,
                                accumulated_call=pending_tool_calls[tool_index],
                                raw=event.raw,
                            )
                            emitted_tool_call_indexes.add(tool_index)
                        incoming_tool_deltas = tc_delta if isinstance(tc_delta, list) else [tc_delta]
                        for incoming_tool_delta in incoming_tool_deltas:
                            if not isinstance(incoming_tool_delta, dict):
                                continue
                            fn_delta = incoming_tool_delta.get("function")
                            fn_delta = fn_delta if isinstance(fn_delta, dict) else {}
                            argument_delta = fn_delta.get("arguments")
                            if not argument_delta:
                                continue
                            tool_index = int(incoming_tool_delta.get("index") or 0)
                            accumulated_call = pending_tool_calls.get(tool_index)
                            if accumulated_call:
                                fn = accumulated_call.get("function") if isinstance(accumulated_call, dict) else {}
                                fn = fn if isinstance(fn, dict) else {}
                            arguments_text = str(fn.get("arguments") or "")
                            previous_arguments = emitted_tool_input_arguments.get(tool_index)
                            await self._emit_stream_tool_input_delta_part(
                                state,
                                response_index=response_index,
                                tool_index=tool_index,
                                accumulated_call=accumulated_call,
                                delta=str(argument_delta),
                                raw=event.raw,
                                transient=True,
                            )
                            if (
                                    previous_arguments is None
                                    or len(arguments_text) - len(previous_arguments) >= _TOOL_INPUT_PROGRESS_CHARS
                                ):
                                    await self._emit_stream_tool_input_delta_part(
                                        state,
                                        response_index=response_index,
                                        tool_index=tool_index,
                                        accumulated_call=accumulated_call,
                                        delta=str(argument_delta),
                                        raw=event.raw,
                                    )
                                    emitted_tool_input_arguments[tool_index] = arguments_text
                elif event.kind == "usage":
                    pending_usage = event.usage or pending_usage
                elif event.kind == "finish":
                    # ``finish`` ends generation, not the provider
                    # transport. A usage-only chunk may still follow before
                    # the explicit ``done`` event or natural EOF.
                    if event.usage is not None:
                        pending_usage = event.usage
                    if event.tool_calls:
                        terminal_tool_calls = event.tool_calls
                elif event.kind == "done":
                    # [DONE] is the transport terminator. Keep final tool
                    # calls, then finalize once after the stream loop.
                    if event.tool_calls:
                        terminal_tool_calls = event.tool_calls
                    break
                elif event.kind == "error":
                    await self._emit_stream_fallback(state, event.error or "stream error")
                    return None  # fall back to non-streaming
        except (AttributeError, NotImplementedError):
            return None
        except ModelRetryExhausted as exc:
            await self._emit_stream_fallback(state, str(exc))
            return None
        except Exception as exc:
            await self._emit_stream_fallback(state, str(exc) or exc.__class__.__name__)
            return None  # fall back to non-streaming
        finally:
            await stream.aclose()

        # Stream ended without a done event — build response from accumulated data
        merged_tool_calls = terminal_tool_calls or (
            resolve_tool_calls(pending_tool_calls) if pending_tool_calls else []
        )
        if not accumulated and not thinking and not merged_tool_calls:
            await self._emit_stream_fallback(state, "流式响应未返回内容")
            return None
        await self._emit_final_stream_tool_input_delta_parts(
            state,
            response_index=response_index,
            tool_calls=merged_tool_calls,
            emitted_arguments=emitted_tool_input_arguments,
        )
        await self._emit_final_stream_text_parts(
            state,
            response_index=response_index,
            accumulated=accumulated,
            thinking=thinking,
            emitted_text=emitted_text,
            emitted_thinking=emitted_thinking,
        )
        # Emit a terminal delta so consumers can finalize the visible part.
        # The canonical usage event is emitted by _run after this response;
        # this copy is marked separately to prevent projection double counts.
        usage_dict = pending_usage.to_dict() if pending_usage else None
        await self.event_sink.emit(CoreEvent(
            name="runtime.reply_delta",
            category="message",
            payload={
                "content": "",
                "finish_reason": stream_finish_reason or "stop",
                "usage": usage_dict,
                "usage_reported_separately": True,
                "response_index": response_index,
            },
            session_id=state.session_id,
            run_id=state.run_id,
            tags=["reply", "done"],
        ))
        # Some providers end the stream with a usage-only chunk (no done
        # event) — carry the captured usage so the turn still gets its token /
        # cache-hit metrics instead of silently dropping them. Same for a
        # finish_reason folded into the final delta chunk (audit 10 S3).
        return LLMResponse(
            content=accumulated,
            thinking=thinking,
            tool_calls=merged_tool_calls,
            usage=pending_usage,
            finish_reason=stream_finish_reason or "stop",
            metadata=(
                {"cache_diagnostic_route": cache_diagnostic_route}
                if cache_diagnostic_route is not None
                else {}
            ),
            provider_state=copy.deepcopy(provider_state),
        )

    async def _collect_guidance(
        self,
        turn_input: RuntimeTurnInput,
        *,
        finalize: bool = False,
    ) -> list[tuple[str, dict[str, Any]]]:
        """Read pending guidance into normalized ``(content, metadata)`` pairs.

        Draining is split from :meth:`_apply_guidance` so callers that must
        finish writing back the current tool batch before the guidance lands in
        history can do exactly that.
        """
        if finalize and turn_input.guidance_finalizer is not None:
            guidance_items = turn_input.guidance_finalizer() or []
        else:
            source = turn_input.guidance_source
            guidance_items = source() if source is not None else []
        if inspect.isawaitable(guidance_items):
            guidance_items = await guidance_items or []
        guidance: list[tuple[str, dict[str, Any]]] = []
        for item in guidance_items:
            if isinstance(item, dict):
                content = str(item.get("content") or item.get("text") or "").strip()
                metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            else:
                content = str(item).strip()
                metadata = {}
            if content:
                guidance.append((content, metadata))
        return guidance

    async def _apply_guidance(
        self,
        state: RuntimeState,
        history: list[ChatMessage],
        response_index: int,
        guidance: list[tuple[str, dict[str, Any]]],
    ) -> None:
        """Append already-collected guidance to history and announce it."""
        known_ids = {
            str(message_id)
            for message in history
            for message_id in message.metadata.get("guidance_ids", [])
        }
        received_events: list[CoreEvent] = []
        for content, metadata in guidance:
            guidance_id = str(metadata.get("guidance_id") or "")
            if guidance_id and guidance_id in known_ids:
                continue
            history.append(ChatMessage(
                # user:“把它作为一个引导信息发进去”+(带附件的恢复补充也以同一条
                # 引导入历史，文字仍用于界面显示，内容块用于模型实际读取)。
                role="user", content=metadata.get("user_content") or content,
                metadata={"guidance_ids": [guidance_id]} if guidance_id else {},
            ))
            if guidance_id:
                known_ids.add(guidance_id)
            received_events.append(CoreEvent(
                name="runtime.guidance_received",
                category="message",
                payload={
                    "content": content,
                    "response_index": response_index,
                    **({"metadata": {key: value for key, value in metadata.items()
                                     if key != "user_content"}} if metadata else {}),
                },
                session_id=state.session_id,
                run_id=state.run_id,
                tags=["guidance"],
            ))
        await self._save_checkpoint(state)
        for event in received_events:
            await self.event_sink.emit(event)

    @staticmethod
    async def _acknowledge_guidance(turn_input: RuntimeTurnInput, ids: list[str]) -> None:
        acknowledger = turn_input.guidance_acknowledger or getattr(turn_input.guidance_source, "acknowledger", None)
        if ids and acknowledger is not None:
            result = acknowledger(ids)
            if inspect.isawaitable(result):
                await result

    async def _consume_guidance(
        self,
        state: RuntimeState,
        turn_input: RuntimeTurnInput,
        history: list[ChatMessage],
        response_index: int,
        *,
        finalize: bool = False,
    ) -> bool:
        guidance = await self._collect_guidance(turn_input, finalize=finalize)
        if not guidance:
            return False
        await self._apply_guidance(state, history, response_index, guidance)
        await self._acknowledge_guidance(turn_input, [
            str(metadata["guidance_id"]) for _, metadata in guidance
            if metadata.get("guidance_id")
        ])
        return True

    async def _apply_runtime_settings(
        self,
        state: RuntimeState,
        turn_input: RuntimeTurnInput,
    ) -> None:
        """Apply the newest composer parameter group before the next step.

        user:“模式、权限、思考强度在下一步生效（即时生效）”+(运行中的回合在步边界
        取走最新值；模型不在此列，仍按回合生效)。
        """
        source = getattr(turn_input, "settings_source", None)
        if not callable(source):
            return
        try:
            result = source(self._applied_settings_generation)
        except Exception:  # noqa: BLE001 — settings must never break a run
            _logger.warning(
                "[kernel:_run] settings pull failed sid=%s", state.session_id, exc_info=True
            )
            return
        if not result:
            return
        generation, patch = result
        if not isinstance(patch, dict) or not patch:
            return
        self._applied_settings_generation = int(generation)

        applier = getattr(self.kit, "apply_runtime_settings", None)
        if not callable(applier):
            return
        try:
            changed = set(applier(state, patch) or ())
        except Exception:  # noqa: BLE001 — a bad patch must not break the run
            _logger.warning(
                "[kernel:_run] settings apply failed sid=%s", state.session_id, exc_info=True
            )
            return
        if not changed:
            return

        # Mode and permission change which tools exist.  Dropping the frozen
        # array is what makes the next request advertise the new set; the
        # leading prompt stays frozen and the differences ride the existing
        # tail notices.
        if changed & {"active_mode", "permission_preset"}:
            reset_session_tool_freeze(state.session_id)

        if "shallow_thinking_enabled" in changed:
            setter = getattr(self.llm_client, "set_enabled", None)
            if callable(setter):
                setter(bool(patch.get("shallow_thinking_enabled")))

        labels: list[str] = []
        if "active_mode" in changed:
            labels.append(f"mode={state.metadata.get('active_mode')}")
        if "reasoning_level" in changed:
            labels.append(f"thinking={state.metadata.get('reasoning_level')}")
        if "shallow_thinking_enabled" in changed:
            labels.append(f"shallow={state.metadata.get('shallow_thinking_enabled')}")
        if "permission_preset" in changed:
            labels.append(f"permission={state.metadata.get('permission_preset')}")
        await self._emit_state_event(
            state,
            "runtime.settings_applied",
            "settings applied at next step" + (": " + ", ".join(labels) if labels else ""),
        )

    # ── 子代理事件：只上报”仍在运行”，绝不在此消费 ──────────────────
    #
    # 成员的完成/失败/关闭/被中断由 harness 落成持久事件。父回合一旦产出最终
    # 答复就立刻结束；成员结果是**下一个回合**的内容，由 member-wake watchdog
    # 另开新回合投递。本函数只记录”主代理已停、这些成员仍在跑”，供界面区分
    # (a)/(b)，不 drain、不等待、不接续——因此本回合结构上不可能把成员结果卷进
    # 它的最终总结里。

    async def _announce_active_members(self, state: RuntimeState, response_index: int) -> None:
        from lamtools_core.sub_agent_supervisor import find_sub_agent_supervisor

        supervisor = None
        for candidate in (state.session_id,):
            supervisor = find_sub_agent_supervisor(candidate)
            if supervisor is not None:
                break
        if supervisor is None:
            return
        try:
            if not await supervisor.has_active_members():
                return
            members = await supervisor.active_member_status()
        except BaseException:
            return
        if not members:
            # The last member finished between the two checks above; there is
            # nothing left to announce and the drain path already retracted it.
            return
        turn_id = str(state.metadata.get("turn_id") or "")
        # Record which turn this fact belongs to so the supervisor can retract
        # it for the same turn once the last of these members finishes.
        supervisor.note_member_wait_turn(turn_id)
        await self.event_sink.emit(CoreEvent(
            name="runtime.sub_agent_wait",
            category="message",
            payload={
                "wait_seconds": 0,
                "response_index": response_index,
                "members": members,
            },
            session_id=state.session_id,
            run_id=state.run_id,
            turn_id=turn_id,
            tags=["sub_agent", "wait"],
        ))
        # Close the race where a member finished between the liveness check and
        # this publish: its own drain retraction already ran, so nothing else
        # would clear the fact we just wrote.
        try:
            if not await supervisor.has_active_members():
                await supervisor.report_members_drained()
        except BaseException:
            pass

    async def _next_stream_event(self, stream_iterator: Any) -> LLMStreamEvent:
        timeout = self.policy.model_stream_idle_timeout_seconds
        if timeout is not None and timeout > 0:
            return await asyncio.wait_for(stream_iterator.__anext__(), timeout=timeout)
        return await stream_iterator.__anext__()

    async def _emit_stream_part(
        self,
        state: RuntimeState,
        *,
        part_id: str,
        part_type: str,
        status: str,
        label: str,
        response_index: int | None = None,
        content: str = "",
        detail: str = "",
        raw: Any = None,
        tool_name: str | None = None,
        call_id: str | None = None,
        tool_args: dict[str, Any] | None = None,
        delta: str | None = None,
        arguments_text: str | None = None,
        transient: bool = False,
    ) -> None:
        payload: dict[str, Any] = {
            "part_id": part_id,
            "part_type": part_type,
            "status": status,
            "label": label,
            "content": content,
            "detail": detail,
        }
        if response_index is not None:
            payload["response_index"] = response_index
        if tool_name is not None:
            payload["tool_name"] = tool_name
        if call_id is not None:
            payload["call_id"] = call_id
            payload["tool_call_id"] = call_id
        if tool_args is not None:
            payload["tool_args"] = tool_args
        if delta is not None:
            payload["delta"] = delta
        if arguments_text is not None:
            payload["arguments_text"] = arguments_text
        await self.event_sink.emit(CoreEvent(
            name="runtime.part",
            category="message",
            payload=payload,
            session_id=state.session_id,
            run_id=state.run_id,
            tags=["stream", part_type],
            metadata={"delivery": "transient"} if transient else {},
        ))

    async def _emit_stream_tool_call_part(
        self,
        state: RuntimeState,
        *,
        response_index: int,
        tool_index: int,
        accumulated_call: dict[str, Any],
        raw: Any = None,
    ) -> None:
        fn = accumulated_call.get("function") if isinstance(accumulated_call, dict) else {}
        fn = fn if isinstance(fn, dict) else {}
        tool_name = str(fn.get("name") or "").strip()
        raw_arguments = str(fn.get("arguments") or "")
        call_id = str(accumulated_call.get("id") or "").strip()
        if not call_id:
            call_id = f"functions.{tool_name or 'invalid_tool_call'}:{tool_index}"
        tool_args = self._summarize_tool_arguments(raw_arguments)
        label = f"准备调用 {tool_name}" if tool_name else "准备工具调用"
        detail = self._tool_call_detail(tool_args=tool_args, raw_arguments=raw_arguments)
        # Transient: this placeholder fires the moment the tool name resolves,
        # before arguments finish streaming. It must NOT be persisted — a crash
        # mid-stream would otherwise leave an orphaned running tool_call event
        # with empty arguments (the exact corruption seen in 2b34c636…). The
        # authoritative, persisted "tool running" event is emitted by
        # _emit_tool_started once arguments are complete and the tool is
        # actually dispatched for execution.
        await self._emit_stream_part(
            state,
            part_id=f"{state.run_id}:response-{response_index}:tool-call-{tool_index}",
            part_type="tool_call",
            status="running",
            label=label,
            content=label,
            detail=detail,
            response_index=response_index,
            raw=raw,
            tool_name=tool_name,
            call_id=call_id,
            tool_args=tool_args,
            transient=True,
        )

    async def _emit_stream_tool_input_delta_part(
        self,
        state: RuntimeState,
        *,
        response_index: int,
        tool_index: int,
        accumulated_call: dict[str, Any],
        delta: str,
        raw: Any = None,
        transient: bool = False,
    ) -> None:
        fn = accumulated_call.get("function") if isinstance(accumulated_call, dict) else {}
        fn = fn if isinstance(fn, dict) else {}
        tool_name = str(fn.get("name") or "").strip()
        arguments_text = str(fn.get("arguments") or "")
        call_id = str(accumulated_call.get("id") or "").strip()
        if not call_id:
            call_id = f"functions.{tool_name or 'invalid_tool_call'}:{tool_index}"
        await self._emit_stream_part(
            state,
            part_id=f"{state.run_id}:response-{response_index}:tool-call-{tool_index}:input",
            part_type="tool_input_delta",
            status="running",
            label="工具输入生成中",
            content="",
            detail=f"参数生成中：{len(arguments_text)} chars",
            response_index=response_index,
            raw=raw,
            tool_name=tool_name,
            call_id=call_id,
            delta=delta,
            arguments_text=arguments_text,
            transient=transient,
        )

    async def _emit_final_stream_tool_input_delta_parts(
        self,
        state: RuntimeState,
        *,
        response_index: int,
        tool_calls: list[LLMToolCall],
        emitted_arguments: dict[int, str],
        raw: Any = None,
    ) -> None:
        for tool_index, call in enumerate(tool_calls):
            tool_name = str(call.name or "").strip()
            arguments_text = self._tool_call_arguments_text(call)
            if not arguments_text or emitted_arguments.get(tool_index) == arguments_text:
                continue
            accumulated_call = {
                "id": str(call.id or "").strip(),
                "type": "function",
                "function": {
                    "name": tool_name,
                    "arguments": arguments_text,
                },
            }
            await self._emit_stream_tool_input_delta_part(
                state,
                response_index=response_index,
                tool_index=tool_index,
                accumulated_call=accumulated_call,
                delta="",
                raw=raw,
            )
            emitted_arguments[tool_index] = arguments_text

    @staticmethod
    def _tool_call_arguments_text(call: LLMToolCall) -> str:
        metadata = call.metadata if isinstance(call.metadata, dict) else {}
        raw_arguments = metadata.get("raw_arguments")
        if isinstance(raw_arguments, str) and raw_arguments:
            return raw_arguments
        arguments = call.arguments if isinstance(call.arguments, dict) else {}
        if not arguments:
            return ""
        return json.dumps(arguments, ensure_ascii=False)

    @staticmethod
    def _summarize_tool_arguments(raw_arguments: str) -> dict[str, Any]:
        if not raw_arguments:
            return {}
        try:
            parsed = json.loads(raw_arguments)
        except (json.JSONDecodeError, TypeError):
            return CoreLoopKernel._summarize_partial_tool_arguments(raw_arguments)
        if not isinstance(parsed, dict):
            return {}
        return CoreLoopKernel._safe_tool_arguments(parsed)

    @staticmethod
    def _summarize_partial_tool_arguments(raw_arguments: str) -> dict[str, Any]:
        summary: dict[str, Any] = {}
        for key in ("path", "command", "query", "url", "pattern", "file", "filename", "action"):
            match = re.search(rf'"{re.escape(key)}"\s*:\s*"([^"]*)', raw_arguments)
            if match:
                summary[key] = match.group(1)[:500]
        return summary

    @staticmethod
    def _safe_tool_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
        safe: dict[str, Any] = {}
        for key, value in arguments.items():
            if key in {"content", "new_string", "old_string"} and isinstance(value, str):
                safe[key] = {
                    "chars": len(value),
                    "preview": value[:240],
                }
            elif isinstance(value, str):
                safe[key] = value[:1000]
            elif isinstance(value, (int, float, bool)) or value is None:
                safe[key] = value
            elif isinstance(value, list):
                safe[key] = f"{len(value)} items"
            elif isinstance(value, dict):
                safe[key] = f"{len(value)} keys"
            else:
                safe[key] = str(value)[:500]
        return safe

    @staticmethod
    def _tool_call_detail(*, tool_args: dict[str, Any], raw_arguments: str) -> str:
        if tool_args:
            parts = [f"{key}: {CoreLoopKernel._short_arg_value(value)}" for key, value in tool_args.items()]
            return "; ".join(parts[:6])
        if raw_arguments:
            return f"参数生成中：{len(raw_arguments)} chars"
        return "模型正在生成工具调用。"

    @staticmethod
    def _short_arg_value(value: Any) -> str:
        if isinstance(value, dict):
            if "chars" in value:
                return f"{value.get('chars')} chars"
            return json.dumps(value, ensure_ascii=False)[:160]
        return str(value)[:160]

    async def _emit_stream_fallback(self, state: RuntimeState, reason: str) -> None:
        await self._emit_stream_part(
            state,
            part_id=f"{state.run_id}:stream-fallback",
            part_type="error",
            status="error",
            label="流式响应中断",
            content="已切换为完整响应。",
            detail=reason[:500],
        )

    async def _call_model(
        self,
        request: LLMRequest,
        *,
        state: RuntimeState | None = None,
        response_index: int | None = None,
    ) -> LLMResponse:
        """Call model with timeout, retry, and backoff.

        Error classification (OpenAI-style three-tier):
        - TokenOverflowError: context window exceeded → abort immediately,
          no retry (retrying the same oversized request is wasteful).
        - RateLimitError: HTTP 429 → honor Retry-After if present, otherwise
          fall back to retry_policy backoff.
        - Other errors: retry per retry_policy.
        """
        try:
            return await complete_with_retry(
                self.llm_client,
                request,
                max_attempts=self.policy.model_retries,
                timeout_seconds=self.policy.model_timeout_seconds,
                retry_policy=self.retry_policy,
                on_retry=lambda retry: self._emit_model_retry_from_event(
                    retry,
                    state=state,
                    response_index=response_index,
                ),
                sleep=asyncio.sleep,
            )
        except ModelRetryExhausted as exc:
            raise ModelCallError(str(exc)) from exc.last_error
        except Exception as exc:
            if classify_model_error(exc) == "token_overflow":
                raise TokenOverflowError(
                    f"Model context window exceeded: {exc}"
                ) from exc
            raise

    async def _emit_model_retry_from_event(
        self,
        retry: ModelRetryEvent,
        *,
        state: RuntimeState | None,
        response_index: int | None,
    ) -> None:
        await self._emit_model_retry(
            state=state,
            attempt=retry.attempt,
            max_retries=retry.max_retries,
            delay_seconds=retry.delay_seconds,
            kind=retry.kind,
            error=retry.error,
            response_index=response_index,
        )

    async def _emit_model_retry(
        self,
        *,
        state: RuntimeState | None,
        attempt: int,
        max_retries: int,
        delay_seconds: float,
        kind: str,
        error: Exception,
        response_index: int | None,
    ) -> None:
        if state is None:
            return
        label = f"模型请求重试中 ({attempt}/{max_retries})"
        await self.event_sink.emit(CoreEvent(
            name="runtime.part",
            category="progress",
            payload={
                "part_id": f"{state.run_id}:model-retry:{response_index if response_index is not None else 'unknown'}",
                "part_type": "status",
                "status": "retrying",
                "label": label,
                "content": label,
                "detail": f"{delay_seconds:g}s 后重试：{str(error)[:500]}",
                "attempt": attempt,
                "max_retries": max_retries,
                "delay_seconds": delay_seconds,
                "error_kind": kind,
                "error": str(error)[:1000],
                "response_index": response_index,
            },
            session_id=state.session_id,
            run_id=state.run_id,
            tags=["progress"],
        ))

    async def _execute_tool(
        self, state: RuntimeState, call: ToolCall, *, forensic_step: int | None = None,
    ) -> ToolResult:
        """Execute a single tool call via Kit.

        Approval-required calls are intercepted by the main loop before this
        method. Reaching this branch with requires_approval=True means a caller
        bypassed the waiting-gate contract; do not emit a second approval event
        or execute the tool.
        """
        if call.requires_approval:
            return ToolResult(
                call_id=call.id,
                name=call.name,
                status="blocked",
                error="Tool requires approval and was not routed through a waiting request.",
                metadata={"approval_contract_violation": True},
            )
        forensic_token = forensic_runtime_context.set({
            "session_id": state.session_id, "run_id": state.run_id,
            "step": forensic_step,
        })
        # user:“记忆也应当保存记忆时的精确位置”+(在统一执行入口用真实历史绑定来源，覆盖普通、并行与恢复调用)。
        if call.name == "memory":
            from lamtools_core.mem.context import attach_context
            attach_context(call, state, getattr(self, "_live_history", None) or [])
        # user:“ok，那就这么做”+(将原始档案绑定到当前执行任务，工具参数不能跨会话扩大读取范围)。
        async def execute_bound_tool():
            from lamtools_core.tool.context_history import history_scope
            from lamtools_core.plugin_system.tool_extensions import kernel_tool_result_boundary
            with history_scope(self.state_store, state.session_id, self._live_history or []), kernel_tool_result_boundary():
                return await self.kit.execute_tool(state, call)

        execution = execute_bound_tool()
        timeout = self.policy.tool_timeout_seconds
        try:
            if timeout is None or timeout <= 0:
                return await execution
            return await asyncio.wait_for(execution, timeout=timeout)
        except TimeoutError:
            return ToolResult(
                call_id=call.id,
                name=call.name,
                status="failed",
                error=f"Tool timed out after {timeout} seconds",
            )
        except Exception as exc:
            # user:“一次性处理干净 不要留尾巴”+(预算耗尽是运行终止信号，不降级为可重试的工具失败)。
            if getattr(exc, "budget_exhausted", False):
                raise
            return ToolResult(
                call_id=call.id,
                name=call.name,
                status="failed",
                error=f"Tool execution failed: {exc}",
                metadata={
                    "tool_exception": True,
                    "error_type": type(exc).__name__,
                },
            )
        finally:
            forensic_runtime_context.reset(forensic_token)

    def _refresh_live_approval_requirements(
        self,
        calls: list[ToolCall],
        blocked_results: dict[str, ToolResult],
    ) -> None:
        """Re-evaluate prepared calls against the live session permissions.

        ``toolbox.prepare_call`` refreshes the approval gate from the session's
        current permission state and re-checks the manifest/mode boundaries, so
        calling it here turns a stale ``requires_approval`` (computed when the
        model output was parsed) into the current truth.  A call that is no
        longer approval-gated is left in ``turn.tool_calls`` and simply executes
        normally; a call that became blocked keeps its blocked metadata and will
        be refused by ``toolbox.execute``.
        """
        for index, call in enumerate(calls):
            if call.id in blocked_results or not call.requires_approval:
                continue
            calls[index] = self._reprepare_against_live_permissions(call)

    def _reprepare_against_live_permissions(self, call: ToolCall) -> ToolCall:
        """Re-run one call through the toolbox's live permission boundary.

        Returns a refreshed call when the toolbox can prepare it.  ``question``
        is deliberately untouched: it is a user-input request, not a permission
        decision, so no preset ever auto-releases it.
        """
        if call.name == "question":
            return call
        prepare = getattr(getattr(self.kit, "toolbox", None), "prepare_call", None)
        if not callable(prepare):
            return call
        try:
            return prepare(call)
        except Exception:  # noqa: BLE001 - keep the parsed decision on refresh failure
            return call

    def _release_approval_if_live_preset_covers(
        self,
        state: RuntimeState,
        step: KernelStep,
        call: ToolCall,
    ) -> ToolCall | None:
        """Release a just-persisted approval when the live preset covers it.

        The pre-emission refresh cannot close the whole race: a permission
        switch may look for a pending card *before* this one became durable, so
        its own release pass misses it.  Re-checking immediately after the card
        is persisted closes exactly that window — the switch side has already
        updated the session by then — without introducing any periodic work.

        Returns the refreshed, now approval-free call after clearing the pending
        record, or ``None`` to keep the card (still required, or hard-blocked).
        """
        # A PreToolUse hook that escalated this call to ``ask_user`` did so on
        # purpose and independently of the session preset; a preset switch must
        # not silently cancel that ask.  Only gate-derived waits are releasable.
        metadata = call.metadata if isinstance(call.metadata, dict) else {}
        if "hook_permission_reason" in metadata:
            return None
        refreshed = self._reprepare_against_live_permissions(call)
        approval = refreshed.metadata.get("approval") if isinstance(refreshed.metadata, dict) else None
        if refreshed.requires_approval or (isinstance(approval, dict) and approval.get("blocked")):
            return None
        state.metadata.pop("pending_approval", None)
        state.metadata.pop("pending_waiting_request", None)
        step.metadata.pop("pending_approval", None)
        if self.policy.persist_steps:
            steps_log = state.metadata.get("kernel_steps")
            if isinstance(steps_log, list) and steps_log:
                # Drop the "wait" audit entry this gate just appended: the turn
                # is not waiting after all.
                steps_log.pop()
        state.loop_state = "continue"
        return refreshed

    async def _apply_pre_tool_hook(
        self,
        state: RuntimeState,
        call: ToolCall,
    ) -> ToolResult | None:
        if self.hook_engine is None:
            return await self._apply_owned_pre_tool_hook(state, call)
        decision = await self.hook_engine.run(HookEvent(
            event_name="PreToolUse",
            session_id=state.session_id,
            run_id=state.run_id,
            tool_call_id=call.id,
            cwd=str(call.metadata.get("cwd") or ""),
            project_root=str(call.metadata.get("work_root") or call.metadata.get("project_root") or ""),
            metadata=dict(call.metadata),
            tool_name=call.name,
            tool_input=dict(call.arguments if isinstance(call.arguments, dict) else {}),
        ))

        if decision.updated_input is not None:
            call.arguments = dict(decision.updated_input)
        if decision.additional_context:
            call.metadata["hook_additional_context"] = decision.additional_context
        if decision.permission_decision == "ask_user":
            call.requires_approval = True
            call.metadata["hook_permission_reason"] = decision.permission_decision_reason
        if decision.permission_decision == "deny" or decision.decision == "block":
            reason = decision.permission_decision_reason or decision.reason or "blocked by hook"
            return ToolResult(
                call_id=call.id,
                name=call.name,
                status="blocked",
                content=reason,
                error=reason,
                metadata={
                    "hook_decision": "blocked",
                    "hook_audit": decision.audit_events,
                },
            )
        if decision.audit_events:
            call.metadata["hook_audit"] = decision.audit_events
        if decision.status_message:
            await self._emit_hook_status(state, call.name, decision.status_message)
        return await self._apply_owned_pre_tool_hook(state, call)

    async def _apply_owned_pre_tool_hook(self, state: RuntimeState, call: ToolCall) -> ToolResult | None:
        # user:“宿主能力补齐和接口完善与文档更新”+(原审批等待前执行受管守卫，无旧钩子引擎时也不能跳过)。
        callback = getattr(getattr(self.kit, "toolbox", None), "pre_tool_call", None)
        if not callable(callback):
            return None
        from lamtools_core.tool import ToolContext
        return await callback(call, ToolContext(session_id=state.session_id, run_id=state.run_id,
                                                work_root=str(call.metadata.get("work_root") or "")))

    # ── Post‑tool hook (PostToolUse / PostToolUseFailure) ────────

    def _tool_result_as_dict(self, result: ToolResult) -> dict[str, Any]:
        """Export ToolResult fields into a plain dict for hook payload."""
        return {
            "call_id": result.call_id,
            "name": result.name,
            "status": result.status,
            "content": result.content,
            "error": result.error,
            **({"error_code": result.error_code} if result.error_code else {}),
        }

    def _apply_tool_result_updates(self, result: ToolResult, updates: dict[str, Any]) -> ToolResult:
        """Return a new ToolResult with fields merged from *updates*."""
        return ToolResult(
            call_id=result.call_id,
            name=result.name,
            status=str(updates.get("status") or result.status),
            content=str(updates.get("content") or result.content),
            error=str(updates.get("error") or result.error),
            artifacts=result.artifacts,
            usage=result.usage,
            error_code=str(updates.get("error_code") or result.error_code),
            metadata={
                **result.metadata,
                **({"hook_updated_output": True} if updates else {}),
            },
        )

    async def _apply_post_tool_hook(
        self,
        state: RuntimeState,
        call: ToolCall,
        result: ToolResult,
    ) -> ToolResult:
        if self.hook_engine is None:
            return result
        if result.status == "blocked":
            # Tool was blocked at pre‑tool stage — never executed; skip post‑hook.
            return result
        event_name = (
            "PostToolUse" if result.status == "ok"
            else "PostToolUseFailure"
        )
        decision = await self.hook_engine.run(HookEvent(
            event_name=event_name,
            session_id=state.session_id,
            run_id=state.run_id,
            tool_call_id=call.id,
            cwd=str(call.metadata.get("cwd") or ""),
            project_root=str(call.metadata.get("work_root") or call.metadata.get("project_root") or ""),
            metadata=dict(call.metadata),
            tool_name=call.name,
            tool_input=dict(call.arguments if isinstance(call.arguments, dict) else {}),
            tool_result=self._tool_result_as_dict(result),
            error=result.error,
            error_type=result.metadata.get("error_type", ""),
        ))
        if decision.updated_output is not None:
            result = self._apply_tool_result_updates(result, decision.updated_output)
        if decision.additional_context:
            call.metadata["hook_additional_context"] = decision.additional_context
        if decision.audit_events:
            call.metadata["hook_audit"] = decision.audit_events
        if decision.status_message:
            await self._emit_hook_status(state, call.name, decision.status_message)
        if decision.decision == "block":
            reason = decision.reason or "blocked by post‑tool hook"
            return ToolResult(
                call_id=call.id,
                name=call.name,
                status="blocked",
                content=reason,
                error=reason,
                metadata={
                    "hook_decision": "blocked",
                    "hook_audit": decision.audit_events,
                },
            )
        return result

    # ── Session lifecycle hooks ──────────────────────────────────

    async def _apply_session_start_hook(
        self,
        state: RuntimeState,
        turn_input: RuntimeTurnInput,
    ) -> None:
        if self.hook_engine is None:
            return
        cwd = str(turn_input.metadata.get("cwd") or "")
        project_root = str(turn_input.metadata.get("work_root") or turn_input.metadata.get("project_root") or "")
        decision = await self.hook_engine.run(HookEvent(
            event_name="SessionStart",
            session_id=state.session_id,
            run_id=state.run_id,
            cwd=cwd,
            project_root=project_root,
            metadata=_json_safe_metadata(dict(turn_input.metadata)),
        ))
        if decision.status_message:
            await self._emit_hook_status(state, "", decision.status_message)

    async def _apply_session_stop_hook(
        self,
        state: RuntimeState,
        result: KernelResult,
    ) -> None:
        if self.hook_engine is None:
            return
        cwd = str(result.metadata.get("cwd") or "")
        project_root = str(result.metadata.get("project_root") or "")
        decision = await self.hook_engine.run(HookEvent(
            event_name="Stop",
            session_id=state.session_id,
            run_id=state.run_id,
            cwd=cwd,
            project_root=project_root,
            metadata={
                "decision": result.decision,
                "error": result.error,
                "steps": len(result.steps),
                **result.metadata,
            },
        ))
        if decision.status_message:
            await self._emit_hook_status(state, "", decision.status_message)

    # ── UserPromptSubmit hook ────────────────────────────────────

    async def _apply_user_prompt_submit_hook(
        self,
        state: RuntimeState,
        turn_input: RuntimeTurnInput,
        user_content: str,
    ) -> str | None:
        """运行 UserPromptSubmit hook；返回注入 additional_context 后的
        用户消息（无注入返回 None）。"""
        if self.hook_engine is None:
            return None
        cwd = str(turn_input.metadata.get("cwd") or "")
        project_root = str(turn_input.metadata.get("work_root") or turn_input.metadata.get("project_root") or "")
        decision = await self.hook_engine.run(HookEvent(
            event_name="UserPromptSubmit",
            session_id=state.session_id,
            run_id=state.run_id,
            cwd=cwd,
            project_root=project_root,
            metadata=_json_safe_metadata(dict(turn_input.metadata)),
            user_message=user_content or "",
        ))
        if decision.status_message:
            await self._emit_hook_status(state, "", decision.status_message)
        # C2 共识：此前 additional_context 被整体丢弃（只消费 status_message），
        # 现在拼入用户消息，随历史持久化后由 build_model_request 带给模型。
        additional = str(decision.additional_context or "").strip()
        if additional:
            return f"{user_content}\n\n{additional}" if user_content else additional
        return None

    # ── PermissionRequest hook ───────────────────────────────────

    async def _apply_permission_request_hook(
        self,
        state: RuntimeState,
        call: ToolCall,
    ) -> ToolResult | None:
        """Let hooks inspect / auto‑resolve a permission request.

        Returns:
            None  → no resolution; normal approval flow continues.
            ToolResult  → block the call outright (hook denied).
            In both cases the hook may have modified call.requires_approval.
        """
        if self.hook_engine is None:
            return None
        cwd = str(call.metadata.get("cwd") or "")
        project_root = str(call.metadata.get("work_root") or call.metadata.get("project_root") or "")
        decision = await self.hook_engine.run(HookEvent(
            event_name="PermissionRequest",
            session_id=state.session_id,
            run_id=state.run_id,
            tool_call_id=call.id,
            cwd=cwd,
            project_root=project_root,
            metadata=dict(call.metadata),
            tool_name=call.name,
            tool_input=dict(call.arguments if isinstance(call.arguments, dict) else {}),
            permission_request={
                "tool_name": call.name,
                "tool_call_id": call.id,
                "arguments": call.arguments,
                "permission_reason": call.metadata.get("hook_permission_reason", ""),
            },
        ))
        # Auto‑approve: clear the requirement
        if decision.permission_decision == "allow":
            call.requires_approval = False
            call.metadata["hook_permission_auto_approved"] = True
        # Auto‑deny
        if decision.permission_decision == "deny" or decision.decision == "block":
            reason = decision.permission_decision_reason or decision.reason or "denied by permission hook"
            return ToolResult(
                call_id=call.id,
                name=call.name,
                status="blocked",
                content=reason,
                error=reason,
                metadata={
                    "hook_decision": "blocked",
                    "hook_audit": decision.audit_events,
                },
            )
        if decision.status_message:
            await self._emit_hook_status(state, call.name, decision.status_message)
        return None

    # ── Hook status visibility ───────────────────────────────────

    async def _emit_hook_status(self, state: RuntimeState, tool_name: str, message: str) -> None:
        await self.event_sink.emit(CoreEvent(
            name="runtime.hook_status",
            category="progress",
            payload={
                "tool_name": tool_name,
                "message": message,
            },
            session_id=state.session_id,
            run_id=state.run_id,
            tags=["hook", "status"],
        ))

    async def _emit_final_stream_text_parts(
        self,
        state: RuntimeState,
        *,
        response_index: int,
        accumulated: str,
        thinking: str,
        emitted_text: str,
        emitted_thinking: str,
        raw: Any = None,
    ) -> None:
        # Emit in the model-stream order (thinking first, then text) so the
        # persisted event sequence matches what the client rendered live.
        # Emitting text first here would reverse the order for every reloaded
        # snapshot (item_order anchors to the first-event seq) — the thinking
        # would render below the message it belongs with after a reload.
        if thinking and thinking != emitted_thinking:
            await self._emit_stream_part(
                state,
                part_id=f"{state.run_id}:response-{response_index}:reasoning",
                part_type="reasoning",
                status="running",
                label="思考",
                content=thinking,
                response_index=response_index,
                raw=raw,
            )
        # Streamed reasoning parts are only ever emitted with status=running;
        # without a terminal completed part the persisted item stays "running"
        # forever — history turns keep live 流光 and process-group summaries
        # remain stuck on 思考中… after the turn finished.
        if thinking:
            await self._emit_stream_part(
                state,
                part_id=f"{state.run_id}:response-{response_index}:reasoning",
                part_type="reasoning",
                status="completed",
                label="思考",
                content=thinking,
                response_index=response_index,
                raw=raw,
            )
        if accumulated and accumulated != emitted_text:
            await self._emit_stream_part(
                state,
                part_id=f"{state.run_id}:response-{response_index}:text",
                part_type="text",
                status="running",
                label="输出",
                content=accumulated,
                response_index=response_index,
                raw=raw,
            )

    async def _execute_call_and_writeback(
        self,
        state: RuntimeState,
        call: ToolCall,
        *,
        blocked_results: dict[str, ToolResult],
        step: KernelStep,
        index: int,
        history: list[ChatMessage],
    ) -> ToolResult:
        """Execute one call and commit its result before a batch parks.

        When a step contains both side-effecting calls and an approval wait,
        the non-approval calls must run *before* the run ends.  Otherwise the
        history repair later fabricates "interrupted" results for work that was
        never attempted and the model loses both the output and the request.
        """
        await self._emit_tool_started(state, call, response_index=index)
        if call.id in blocked_results:
            result = blocked_results[call.id]
        else:
            result = await self._execute_tool(state, call, forensic_step=index)
            result = await self._apply_post_tool_hook(state, call, result)
        step.tool_steps.append(RuntimeToolStep(call=call, result=result))
        await self._emit_tool_finished(state, call, result, response_index=index)
        tool_message = await self.kit.format_tool_result_for_model(state, call, result)
        _stamp_message_origin(tool_message, state.turn_count)
        history.append(tool_message)
        await self._save_checkpoint(state)
        return result

    async def _execute_tools_parallel(
        self, state: RuntimeState, calls: list[ToolCall], *, forensic_step: int | None = None,
    ) -> list[ToolResult]:
        """Execute multiple tool calls concurrently with optional cap.

        Results are returned in the same order as calls. Uses a semaphore
        when max_concurrent_tools is set to bound concurrency.
        """
        cap = self.policy.max_concurrent_tools
        if cap is not None and cap > 0:
            sem = asyncio.Semaphore(cap)

            async def _bounded(c: ToolCall) -> ToolResult:
                async with sem:
                    return await self._execute_tool(state, c, forensic_step=forensic_step)

            coroutines = [_bounded(c) for c in calls]
        else:
            coroutines = [self._execute_tool(state, c, forensic_step=forensic_step) for c in calls]
        tasks = [asyncio.create_task(coroutine) for coroutine in coroutines]
        try:
            return list(await asyncio.gather(*tasks))
        except BaseException:
            # Terminal budget/cancellation must leave no sibling tools running.
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

    def _copy_state(self, state: RuntimeState) -> RuntimeState:
        return RuntimeState(
            session_id=state.session_id,
            run_id=state.run_id,
            status=state.status,
            position=state.position,
            loop_state=state.loop_state,
            turn_count=state.turn_count,
            metadata=copy.deepcopy(state.metadata),
        )

    @staticmethod
    def _summarize_step(step: KernelStep) -> dict[str, Any]:
        """Produce a serializable step summary for persist_steps audit trail.

        Excludes state_before (large) and raw events — keeps only the fields
        needed for post-run debugging and audit.
        """
        summary: dict[str, Any] = {
            "index": step.index,
            "decision": step.decision,
            "phase": step.phase,
            "error": step.error,
            "tool_calls": [
                {
                    "name": ts.call.name,
                    "status": ts.result.status if ts.result else "unknown",
                }
                for ts in step.tool_steps
            ],
        }
        if step.verification is not None:
            v = step.verification
            summary["verification"] = {
                "passed": v.passed,
                "required": v.required,
                "attempt": v.attempt,
                "max_attempts": v.max_attempts,
                "summary": v.summary,
            }
        if step.turn is not None and step.turn.reply:
            summary["reply_preview"] = step.turn.reply[:200]
        return summary

    def _estimate_request_tokens(self, request: LLMRequest, *, fast: bool = True) -> int:
        """Estimate full request tokens, including tool definitions.

        The fast path is used for cheap metrics by default.  Trigger checks
        switch to the exact path near the threshold so Unicode-heavy prompts
        cannot be delayed by a fast-estimator undercount.
        """
        total = estimate_message_tokens(
            [m.to_dict() for m in request.messages], fast=fast
        )
        if request.tools:
            total += estimate_text_tokens(
                json.dumps(request.tools, ensure_ascii=False), fast=fast
            )
        if request.response_format:
            total += estimate_text_tokens(
                json.dumps(request.response_format, ensure_ascii=False), fast=fast
            )
        return total

    def _record_context_usage(
        self,
        state: RuntimeState,
        request: LLMRequest,
        response: LLMResponse,
    ) -> None:
        """Record the provider's real prompt count for the next trigger.

        The value describes the request that was just sent; the 20% headroom
        below the window absorbs the one-request lag. No prefix/anchor matching
        is needed: real usage wins when present, estimate is the fallback.
        """
        # user:“有真实 usage 时使用真实 usage，无真实 usage 使用兜底估算值”
        # +只保留最新响应的测量；缺失时立即失效旧值，允许下一次检查使用估算。
        metrics = state.metadata.setdefault("runtime_context_metrics", {})
        usage = getattr(response, "usage", None)
        try:
            tokens = max(0, int(getattr(usage, "prompt_tokens", 0) or 0))
        except (TypeError, ValueError):
            tokens = 0
        metrics.pop("context_usage_prompt_tokens", None)
        if tokens > 0:
            metrics["context_usage_prompt_tokens"] = tokens
        metrics["model_id"] = str(request.model or "")
        measurement = context_measurement(
            metrics, model_id=str(request.model or ""),
            estimate=lambda: self._estimate_request_tokens(request, fast=False),
        )
        metrics.update(context_tokens=measurement.tokens, estimated_prompt_tokens=measurement.tokens,
                       context_measurement_source=measurement.source)

    async def _persist_runtime_context_metrics(
        self,
        state: RuntimeState,
        *,
        history: list[ChatMessage] | None,
    ) -> None:
        metrics = state.metadata.get("runtime_context_metrics")
        if not isinstance(metrics, dict):
            return
        if history is None:
            await self.state_store.save(state)
        else:
            await self._save_checkpoint(state)
        await self.event_sink.emit(CoreEvent(
            name="runtime.metrics",
            category="progress",
            payload={"runtime_metrics": dict(metrics)},
            session_id=state.session_id,
            run_id=state.run_id,
            tags=["progress"],
        ))

    async def _compact_request_if_needed(
        self,
        state: RuntimeState,
        request: LLMRequest,
        *,
        history: list[ChatMessage] | None = None,
    ) -> None:
        """Structurally summarize old context when the request nears budget.

        Compaction is not a one-time state: a session may compact any number of
        times; there is no permanent "already compacted" status.
        """
        previous_metrics = state.metadata.get("runtime_context_metrics")
        metrics = dict(previous_metrics) if isinstance(previous_metrics, dict) else {}
        previous_model = str(metrics.get("model_id") or "").strip()
        previous_window = int(metrics.get("context_window_tokens") or 0)
        current_model = str(request.model or "").strip()
        model_switched = bool(previous_model and current_model and previous_model != current_model)
        # Session-cumulative kernel step counter. This is NOT a per-call usage
        # counter — per-call usage events carry `llm_calls: 1` for each model
        # call. Keep the names distinct so aggregators never treat cumulative
        # steps as calls (the legacy `llm_calls` key is dropped, not migrated).
        metrics.pop("llm_calls", None)
        metrics["steps_total"] = int(metrics.get("steps_total") or 0) + 1
        state.metadata["runtime_context_metrics"] = metrics
        total_window = self.policy.context_window_tokens
        if total_window is None or total_window <= 0:
            return

        reserved_output_tokens = max(0, int(request.max_tokens or 0))
        window = total_window - reserved_output_tokens
        if window <= 0:
            raise ValueError(
                "Model max output tokens must be smaller than its total context window: "
                f"{reserved_output_tokens} >= {total_window}"
            )

        budget = self._resolve_compaction_budget(window)
        trigger_tokens = budget.trigger_tokens
        limit_tokens = budget.target_tokens
        retained_steps = (
            resolve_retained_steps(getattr(self.policy, "compact_retained_steps", None))
            if getattr(self.policy, "compact_retained_steps", None) is not None
            else load_retained_steps()
        )

        reserved_snapshot: ChatMessage | None = None

        def estimate_request_messages(messages: list[ChatMessage], *, fast: bool) -> int:
            original_messages = request.messages
            request.messages = [*messages, *([reserved_snapshot] if reserved_snapshot is not None else [])]
            try:
                return self._estimate_request_tokens(request, fast=fast)
            finally:
                request.messages = original_messages

        compaction_controller = ContextCompactionController(
            llm_client=self.llm_client,
            estimate_request_tokens=lambda messages, fast: estimate_request_messages(
                messages, fast=fast
            ),
            on_delta=lambda delta: self._emit_stream_part(
                state,
                part_id=f"{state.run_id}:context-compaction",
                part_type="compaction",
                status="running",
                label="正在压缩上下文",
                delta=delta,
                transient=True,
            ),
            on_event=lambda payload: self._emit_compaction_part_event(state, payload),
            model_retries=self.policy.model_retries,
            model_timeout_seconds=self.policy.model_timeout_seconds,
            retry_policy=self.retry_policy,
            summary_output_tokens=self.policy.compact_summary_output_tokens,
            # The summary must be allowed as much output as this turn's own
            # request uses; a summary truncated at a smaller cap is rejected
            # wholesale and leaves the session unable to compact.
            model_output_tokens=request.max_tokens,
            safety_margin_tokens=self.policy.compact_safety_margin_tokens,
            request_metadata={key: request.metadata[key] for key in
                              ("_runtime_session_id", "_runtime_run_id", "_runtime_step")
                              if key in request.metadata},
            on_model_retry=lambda retry: self._emit_model_retry_from_event(
                retry,
                state=state,
                response_index=None,
            ),
        )
        measurement = context_measurement(
            metrics, model_id=current_model,
            estimate=lambda: self._estimate_request_tokens(request, fast=False),
        )
        before_tokens = measurement.tokens
        metrics["context_measurement_source"] = measurement.source
        metrics["context_tokens"] = before_tokens
        if measurement.source != "usage":
            metrics.pop("context_usage_prompt_tokens", None)
        # Keep raw request-only overhead separate from calibrated occupancy;
        # manual /compact must never subtract different units to infer it.
        history_tokens = estimate_message_tokens([m.to_dict() for m in (history or [])])
        metrics["context_request_overhead_tokens"] = max(
            0, self._estimate_request_tokens(request, fast=False) - history_tokens,
        )
        request.metadata["estimated_prompt_tokens"] = before_tokens
        request.metadata["context_window_tokens"] = window
        request.metadata["total_context_window_tokens"] = total_window
        request.metadata["reserved_output_tokens"] = reserved_output_tokens
        request.metadata["context_compaction_trigger_tokens"] = trigger_tokens
        request.metadata["context_compaction_retained_steps"] = retained_steps
        state.metadata["runtime_context_metrics"] = {
            **metrics,
            "estimated_prompt_tokens": before_tokens,
            "context_window_tokens": window,
            "total_context_window_tokens": total_window,
            "reserved_output_tokens": reserved_output_tokens,
            "context_compaction_trigger_tokens": trigger_tokens,
            "context_compaction_retained_steps": retained_steps,
            "context_compacted": False,
            "model_id": current_model,
        }
        # Clear stale compaction stats from a prior run so that
        # context_compacted=False is not paired with old before/after values.
        stale = state.metadata["runtime_context_metrics"]
        for stale_key in (
            "context_tokens_before_compaction",
            "context_tokens_after_compaction",
            "context_messages_before_compaction",
            "context_messages_after_compaction",
        ):
            stale.pop(stale_key, None)
        await self._persist_runtime_context_metrics(state, history=history)
        if before_tokens < trigger_tokens:
            return
        # user:“压缩不是一次性状态”+(每次超过阈值都可以产生压缩信号，不按 run_id 禁用)。
        before_messages = len(request.messages)
        request_messages_before_compaction = list(request.messages)
        allow_previous = request.metadata.get("allow_previous_model_compaction") is not False
        # user:“压缩时把最新的给它（相当于把后面的所有差异都给合并，修回成一个正版）”+通知不再参与压缩，压缩后顶部会直接换成最新内容。
        # user:“但是用压缩后自动追加用户消息里面剔除”+目标续跑自动追加的提醒不进入压缩输入。
        compaction_messages = compaction_input_messages(request.messages)
        # Prepare new system/runtime baselines on an isolated state. Budget
        # their final representation before fitting; cancellation changes none
        # of the live baseline or durable summary.
        candidate_state = copy.deepcopy(state)
        rebuild_movable = getattr(self.kit, "rebuild_movable_system_context", None)
        if callable(rebuild_movable):
            rebuild_movable(candidate_state)
            epoch = candidate_state.metadata.get(MOVABLE_CONTEXT_METADATA_KEY)
            if isinstance(epoch, dict) and isinstance(epoch.get("system_prompt"), str) and compaction_messages and compaction_messages[0].role == "system":
                compaction_messages[0] = replace(compaction_messages[0], content=epoch["system_prompt"])
        emit_snapshot = getattr(self.kit, "emit_runtime_context_snapshot", None)
        if callable(emit_snapshot):
            reserved_snapshot = emit_snapshot(candidate_state)
        execution = await compaction_controller.compact(
            compaction_messages,
            budget=budget,
            timeout=request.timeout,
            current_model=current_model,
            previous_model=previous_model,
            previous_window=previous_window,
            model_switched=model_switched,
            allow_previous_model=allow_previous,
            trigger="model_switch" if model_switched else "auto",
            measurement=TokenMeasurement(
                tokens=before_tokens,
                exact=True,
                source=str(metrics.get("context_measurement_source") or "estimate"),
            ),
            retained_steps=retained_steps,
        )
        result = execution.result
        execution_model = execution.execution_model
        compaction_strategy = execution.strategy
        if result is None:
            return
        if result.status == "failed":
            raise ContextCompactionError(
                str(result.display_payload.get("message") or "Context compaction failed")
            )
        if result.status != "compacted":
            request.metadata["context_compaction_status"] = result.status
            state.metadata["runtime_context_metrics"] = {
                **dict(state.metadata["runtime_context_metrics"]),
                "context_compaction_status": result.status,
            }
            await self._persist_runtime_context_metrics(state, history=history)
            return

        # user:“去重构吧”+(所有追加内容先进入最终预算检查，合格后才提交摘要与基线)。
        replacement = list(result.replacement_messages)
        if callable(rebuild_movable) and replacement and compaction_messages and replacement[0].role == "system":
            replacement[0] = compaction_messages[0]
        if reserved_snapshot is not None:
            replacement.append(reserved_snapshot)
        final_request = replace(request, messages=replacement)
        final_tokens = calibrated_tokens(self._estimate_request_tokens(final_request, fast=False))
        if final_tokens > limit_tokens:
            raise ContextCompactionError(
                f"Final compacted context exceeds target: {final_tokens} > {limit_tokens} tokens"
            )
        result = replace(result, replacement_messages=replacement, after_tokens=final_tokens)
        snapshot_row = _historical_tail_copy(reserved_snapshot) if reserved_snapshot is not None else None
        await persist_compaction(
            self.state_store, candidate_state, result=result, execution=execution,
            source_messages=request_messages_before_compaction,
            budget=budget, retained_steps=retained_steps, before_messages=before_messages,
            total_context_window_tokens=total_window, reserved_output_tokens=reserved_output_tokens,
            trigger="model_switch" if model_switched else "auto",
            extra_messages=[snapshot_row] if snapshot_row is not None else [],
        )
        state.metadata = candidate_state.metadata
        if hasattr(candidate_state, "_runtime_store_revision"):
            setattr(state, "_runtime_store_revision", candidate_state._runtime_store_revision)
        request.messages[:] = replacement
        if history is not None:
            request_only_ids = {
                id(message) for message in request_messages_before_compaction
                if id(message) not in {id(m) for m in history}
            }
            # user:“去重构吧”+(历史只接收保留的原始消息；系统前缀不落入历史，完整快照单独追加一次)。
            retained = _retained_history_messages(history, result.retained_messages, request_only_ids)
            history[:] = [*([result.summary_message] if result.summary_message is not None else []), *retained]
            # The view changed, but every source row was flushed before the
            # signal. New work continues as ordinary append-only checkpoints.
            if snapshot_row is not None:
                history.append(snapshot_row)
            self._persisted_len = len(history)
        reset_session_tool_freeze(state.session_id)
        request.metadata.update(
            estimated_prompt_tokens=final_tokens, context_compacted=True,
            context_compaction_mode="structured_summary",
            context_compaction_strategy=compaction_strategy,
            context_compaction_execution_model=execution_model,
            context_tokens_before_compaction=result.before_tokens,
            context_tokens_after_compaction=final_tokens,
            context_messages_before_compaction=before_messages,
            context_messages_after_compaction=len(request.messages),
        )
        await self._persist_runtime_context_metrics(state, history=history)
        await self._emit_context_compacted(
            state,
            removed=result.compacted_count,
            before_messages=before_messages,
            after_messages=len(request.messages),
            before_tokens=result.before_tokens,
            after_tokens=result.after_tokens,
            trigger_tokens=trigger_tokens,
            limit_tokens=limit_tokens,
            window_tokens=window,
            summary=result.summary,
            trigger="auto",
            compacted_message_ids=_message_reference_ids(result.compacted_messages),
            retained_message_ids=_message_reference_ids(result.retained_messages),
        )
        # Double-write: append the complete compaction product (full summary,
        # folded/retained identity, parameters, watermark) to the thread's
        # append-only dialogue log.  This does not change the rewrite/load
        # behaviour above; it only makes the decision durable and replayable.
        await self._persist_dialogue_compaction_record(
            state,
            result=result,
            trigger="auto",
            trigger_tokens=trigger_tokens,
            limit_tokens=limit_tokens,
            retained_steps=retained_steps,
            execution_model=execution_model,
            strategy=compaction_strategy,
            prefix_count=len(result.prefix_messages),
            before_messages=before_messages,
            sent_messages=list(request.messages[len(result.prefix_messages):]),
        )

    async def _persist_dialogue_compaction_record(
        self,
        state: RuntimeState,
        *,
        result: ContextCompactionResult,
        trigger: str,
        trigger_tokens: int,
        limit_tokens: int,
        retained_steps: int,
        execution_model: str,
        strategy: str,
        prefix_count: int,
        before_messages: int,
        sent_messages: list[ChatMessage],
    ) -> None:
        """Append one compaction control record; never fail the run over it."""
        append = getattr(self.state_store, "append_dialogue_record", None)
        if not callable(append) or result.summary_message is None:
            return
        try:
            record = build_compaction_record(
                trigger=trigger,
                summary_message=result.summary_message,
                retained=list(result.retained_messages),
                folded=list(result.compacted_messages),
                sent_messages=sent_messages,
                prefix_count=prefix_count,
                limit_tokens=limit_tokens,
                trigger_tokens=trigger_tokens,
                retained_steps=retained_steps,
                before_tokens=result.before_tokens,
                after_tokens=result.after_tokens,
                before_messages=before_messages,
                after_messages=len(sent_messages),
                segments=result.segment_count,
                strategy=strategy,
                execution_model=execution_model,
                recent_user_messages=list(result.recent_user_messages),
            )
            await append(
                state.session_id,
                kind=COMPACTION_RECORD,
                record=record,
                watermark=int(record.get("watermark") or 0),
            )
        except Exception:  # noqa: BLE001 — bookkeeping must never break a run
            _logger.warning(
                "[kernel:_persist_dialogue_compaction_record] failed sid=%s",
                state.session_id,
                exc_info=True,
            )

    def _resolve_compaction_budget(self, window: int) -> TokenBudget:
        """Resolve user-facing ratio policy into concrete compaction limits."""
        return resolve_compaction_budget(
            context_window=window,
            trigger_ratio=self.policy.compact_trigger_ratio,
            target_ratio=self.policy.compact_limit_ratio,
            trigger_tokens=self.policy.compact_trigger_tokens,
            target_tokens=self.policy.compact_limit_tokens,
        )

    async def _emit_compaction_part_event(
        self, state: RuntimeState, payload: dict[str, Any]
    ) -> None:
        """Adapt controller progress payloads to kernel runtime-part events."""
        await self.event_sink.emit(
            CoreEvent(
                name="runtime.part",
                category="message",
                payload={
                    "part_id": f"{state.run_id}:context-compaction",
                    "part_type": "compaction",
                    **payload,
                },
                session_id=state.session_id,
                run_id=state.run_id,
                tags=["stream", "compaction"],
            )
        )

    async def _emit_state_event(self, state: RuntimeState, name: str, message: str) -> None:
        """Emit a state lifecycle event."""
        event = CoreEvent(
            name=name,
            category="lifecycle",
            payload={"message": message, "status": state.status},
            session_id=state.session_id,
            run_id=state.run_id,
            tags=["state"],
        )
        await self.event_sink.emit(event)

    async def _emit_reply(self, state: RuntimeState, reply: str, *, response_index: int | None = None) -> None:
        """Emit a reply event for user-visible text."""
        event = CoreEvent(
            name="runtime.reply",
            category="message",
            payload={
                "content": reply,
                **({"response_index": response_index} if response_index is not None else {}),
            },
            session_id=state.session_id,
            run_id=state.run_id,
            tags=["reply"],
        )
        await self.event_sink.emit(event)
        await self._emit_text_part(
            state,
            reply,
            response_index=response_index,
            final_response=True,
            has_tool_calls=False,
        )

    async def _emit_text_part(
        self,
        state: RuntimeState,
        text: str,
        *,
        response_index: int | None = None,
        final_response: bool = False,
        has_tool_calls: bool = False,
    ) -> None:
        """Emit an LLM text block with response-level display semantics."""
        await self.event_sink.emit(CoreEvent(
            name="runtime.part",
            category="message",
            payload={
                "part_type": "text",
                "status": "completed",
                "content": text,
                "label": "Reply",
                "final_response": final_response,
                "has_tool_calls": has_tool_calls,
                "part_id": (
                    f"{state.run_id}:response-{response_index}:text"
                    if response_index is not None
                    else f"{state.run_id}:response-text"
                ),
                "message_id": state.run_id or "",
                **({"response_index": response_index} if response_index is not None else {}),
            },
            session_id=state.session_id,
            run_id=state.run_id,
            tags=["reply", "part"],
        ))

    async def _emit_tool_started(
        self,
        state: RuntimeState,
        call: ToolCall,
        *,
        response_index: int | None = None,
    ) -> None:
        """Emit a tool started event."""
        event = CoreEvent(
            name="runtime.tool.started",
            category="tool",
            payload={
                "tool_name": call.name,
                "call_id": call.id,
                "arguments": call.arguments if isinstance(call.arguments, dict) else {},
                **({"response_index": response_index} if response_index is not None else {}),
            },
            session_id=state.session_id,
            run_id=state.run_id,
            tags=["tool"],
        )
        await self.event_sink.emit(event)
        # Also emit a part event for rich UI rendering
        await self.event_sink.emit(CoreEvent(
            name="runtime.part",
            category="tool",
            payload={
                "part_type": "tool_call",
                "status": "running",
                "tool_name": call.name,
                "label": call.name,
                "detail": str(call.arguments.get("description", "")) if isinstance(call.arguments, dict) else "",
                "tool_args": call.arguments if isinstance(call.arguments, dict) else {},
                "part_id": f"part-{call.id}",
                "message_id": state.run_id or "",
                **({"response_index": response_index} if response_index is not None else {}),
            },
            session_id=state.session_id,
            run_id=state.run_id,
            tags=["tool", "part"],
        ))

    async def _emit_tool_waiting_for_approval(
        self,
        state: RuntimeState,
        call: ToolCall,
        *,
        response_index: int | None = None,
    ) -> None:
        """Persist a tool call as waiting before user approval.

        This is not a tool result. The tool has not finished; the turn is
        blocked behind a durable user gate.
        """
        await self.event_sink.emit(CoreEvent(
            name="runtime.part",
            category="tool",
            payload={
                "part_type": "tool_call",
                "status": "waiting",
                "tool_name": call.name,
                "label": call.name,
                "detail": self._approval_request_message(call),
                "tool_args": call.arguments if isinstance(call.arguments, dict) else {},
                "metadata": {
                    **(dict(call.metadata) if isinstance(call.metadata, dict) else {}),
                    "requires_approval": True,
                },
                "part_id": f"part-{call.id}",
                "message_id": state.run_id or "",
                **({"response_index": response_index} if response_index is not None else {}),
            },
            session_id=state.session_id,
            run_id=state.run_id,
            tags=["tool", "approval", "part"],
        ))

    async def _emit_checklist_snapshots(
        self,
        state: RuntimeState,
        turn: KernelTurn,
        tool_results: list[ToolResult],
        *,
        response_index: int | None = None,
    ) -> None:
        """Publish the post-writeback checklist projection for the UI.

        Checklist tool results are emitted before writeback so the model can see
        them immediately. The second, replace-style part carries the canonical
        state after update actions and automatic deliverable advancement.

        A round may batch several checklist updates into one response, and every
        one of them would carry the same post-writeback plan — the UI then stacks
        identical plan cards. Only the round's last update owns the card; the
        earlier ones are marked merged so the timeline keeps a single card while
        the round's final plan state stays the one on screen.
        """
        task_plan = state.metadata.get("task_plan")
        if not isinstance(task_plan, dict) or not task_plan.get("steps"):
            return
        active_plan = state.metadata.get("active_plan")
        active_plan = active_plan if isinstance(active_plan, dict) else {}
        checklist_results = {
            result.call_id: result
            for result in tool_results
            if result.status == "ok" and result.name in {"write_checklist", "update_checklist"}
        }
        if not checklist_results:
            return

        ordered_calls = [
            call for call in turn.tool_calls if call.id in checklist_results
        ]
        if not ordered_calls:
            return
        snapshot_call_id = ordered_calls[-1].id

        for call in ordered_calls:
            result = checklist_results[call.id]
            metadata = dict(result.metadata) if isinstance(result.metadata, dict) else {}
            if call.id == snapshot_call_id:
                metadata.update({
                    "task_plan": copy.deepcopy(task_plan),
                    "active_plan": copy.deepcopy(active_plan),
                    "checklist_snapshot": True,
                })
            else:
                metadata["checklist_merged"] = True
            await self.event_sink.emit(CoreEvent(
                name="runtime.part",
                category="tool",
                payload={
                    "part_type": "tool_result",
                    "status": "completed",
                    "tool_name": call.name,
                    "label": "Checklist updated",
                    "detail": (result.content or "")[:200],
                    "tool_result": result.content or "",
                    "replace": True,
                    "tool_args": call.arguments if isinstance(call.arguments, dict) else {},
                    "metadata": metadata,
                    "part_id": f"part-{call.id}",
                    "message_id": state.run_id or "",
                    **({"response_index": response_index} if response_index is not None else {}),
                },
                session_id=state.session_id,
                run_id=state.run_id,
                tags=["tool", "part"],
            ))

    async def _emit_tool_finished(
        self,
        state: RuntimeState,
        call: ToolCall,
        result: ToolResult,
        *,
        response_index: int | None = None,
    ) -> None:
        """Emit a tool finished event."""
        # user:“每一个地方 sunday 都有等价或者近似接口”+(最终观察发生在新旧 post 钩子之后，普通工具箱调用与内核调用不重复通知)。
        observer = getattr(getattr(self.kit, "toolbox", None), "observe_tool_result", None)
        if callable(observer):
            from lamtools_core.tool import ToolContext
            await observer(call, result, ToolContext(session_id=state.session_id, run_id=state.run_id,
                                                     work_root=str(call.metadata.get("work_root") or "")))
        event = CoreEvent(
            name="runtime.tool.finished",
            category="tool",
            payload={
                "tool_name": call.name,
                "call_id": call.id,
                "status": result.status,
                "content": result.content or "",
                "error": result.error or "",
                "artifacts": [artifact.to_dict() for artifact in result.artifacts],
                "metadata": result.metadata if isinstance(result.metadata, dict) else {},
                **({"error_code": result.error_code} if result.error_code else {}),
                **({"response_index": response_index} if response_index is not None else {}),
            },
            session_id=state.session_id,
            run_id=state.run_id,
            tags=["tool"],
        )
        await self.event_sink.emit(event)
        if result.artifacts:
            # user:“该做就做”+(工具产物同时作为交付物事件发出，通道和 UI 不
            # 必只靠扫描 tool.finished 才发现文件)。
            await self.event_sink.emit(CoreEvent(
                name="deliverables/presented",
                category="artifact",
                payload={
                    "files": [artifact.to_dict() for artifact in result.artifacts],
                    "tool_name": call.name,
                    "call_id": call.id,
                },
                session_id=state.session_id,
                run_id=state.run_id,
                tags=["artifact", "deliverable"],
            ))
        # Also emit a part event for rich UI rendering
        part_status = "error" if result.status == "failed" else "completed"
        await self.event_sink.emit(CoreEvent(
            name="runtime.part",
            category="tool",
            payload={
                "part_type": "tool_call",
                "status": part_status,
                "tool_name": call.name,
                "label": f"{'Completed' if part_status == 'completed' else 'Failed'}: {call.name}",
                "detail": (result.content or "")[:200],
                "tool_result": (result.content or "")[:2000],
                "tool_error": (result.error or "") if result.status == "failed" else "",
                "tool_args": call.arguments if isinstance(call.arguments, dict) else {},
                "metadata": result.metadata if isinstance(result.metadata, dict) else {},
                **({"error_code": result.error_code} if result.error_code else {}),
                "part_id": f"part-{call.id}",
                "message_id": state.run_id or "",
                **({"response_index": response_index} if response_index is not None else {}),
            },
            session_id=state.session_id,
            run_id=state.run_id,
            tags=["tool", "part"],
        ))

    async def _emit_verification(
        self, state: RuntimeState, verification: VerificationResult
    ) -> None:
        """Emit a verification result event."""
        event = CoreEvent(
            name="runtime.verification",
            category="verification",
            payload={
                "passed": verification.passed,
                "required": verification.required,
                "summary": verification.summary,
                "attempt": verification.attempt,
                "max_attempts": verification.max_attempts,
            },
            session_id=state.session_id,
            run_id=state.run_id,
            tags=["progress"],
        )
        await self.event_sink.emit(event)

    async def _emit_history_compacted(
        self, state: RuntimeState, trimmed: int, remaining: int
    ) -> None:
        """Emit a history compaction event (pre-sampling trim)."""
        event = CoreEvent(
            name="runtime.history_compacted",
            category="progress",
            payload={"trimmed": trimmed, "remaining": remaining},
            session_id=state.session_id,
            run_id=state.run_id,
            tags=["compaction"],
        )
        await self.event_sink.emit(event)

    async def _emit_context_compacted(
        self,
        state: RuntimeState,
        *,
        removed: int,
        before_messages: int,
        after_messages: int,
        before_tokens: int,
        after_tokens: int,
        trigger_tokens: int,
        limit_tokens: int,
        window_tokens: int,
        summary: str = "",
        trigger: str = "",
        compacted_message_ids: list[str] | None = None,
        retained_message_ids: list[str] | None = None,
    ) -> None:
        """Emit a token-budget context compaction event."""
        event = CoreEvent(
            name="runtime.context_compacted",
            category="progress",
            payload={
                "removed": removed,
                "before_messages": before_messages,
                "after_messages": after_messages,
                "before_tokens": before_tokens,
                "after_tokens": after_tokens,
                "trigger_tokens": trigger_tokens,
                "limit_tokens": limit_tokens,
                "window_tokens": window_tokens,
                "summary": summary[:20_000],
                "trigger": trigger or "auto",
                "compacted_message_ids": list(compacted_message_ids or []),
                "retained_message_ids": list(retained_message_ids or []),
            },
            session_id=state.session_id,
            run_id=state.run_id,
            tags=["compaction", "token_budget"],
        )
        await self.event_sink.emit(event)

    async def _emit_approval_request(
        self,
        state: RuntimeState,
        call: ToolCall,
        *,
        response_index: int | None = None,
        request_id: str = "",
    ) -> None:
        """Emit an approval request event before executing a tool that
        requires approval (OpenAI Codex-style ExecApprovalRequest)."""
        options, message = self._approval_request_options_and_message(call)
        args = call.arguments if isinstance(call.arguments, dict) else {}
        context = str(args.get("context") or "").strip() if call.name == "question" else ""
        event = CoreEvent(
            name="runtime.approval_request",
            category="decision",
            payload={
                "tool_call_id": call.id,
                "request_id": request_id or call.id,
                "tool_name": call.name,
                "arguments": call.arguments,
                "reason": call.reason,
                "request_kind": "question" if call.name == "question" else "permission",
                "message": message,
                "metadata": dict(call.metadata) if isinstance(call.metadata, dict) else {},
                "options": options,
                **({"context": context} if context else {}),
                **({"response_index": response_index} if response_index is not None else {}),
            },
            session_id=state.session_id,
            run_id=state.run_id,
            tags=["approval"],
        )
        await self.event_sink.emit(event)

    def _approval_request_options_and_message(self, call: ToolCall) -> tuple[list[dict[str, Any]], str]:
        """Build the options list and message for an approval request.

        For the ``question`` tool the options and message come from the tool
        arguments (the model-supplied question text and selectable choices).
        All other tools use the standard approve/deny pair.
        """
        if call.name == "question":
            args = call.arguments if isinstance(call.arguments, dict) else {}
            raw_questions = args.get("questions")
            first_question = (
                raw_questions[0]
                if isinstance(raw_questions, list)
                and raw_questions
                and isinstance(raw_questions[0], dict)
                else None
            )
            if first_question is not None:
                message = str(first_question.get("question") or "等待用户确认")
                raw_options = first_question.get("options")
            else:
                message = str(args.get("question") or "等待用户确认")
                raw_options = args.get("options")
            if isinstance(raw_options, list) and raw_options:
                options = [
                    {
                        # The label is display text, never an identity or a
                        # decision verb. Using it as the option id made a
                        # literal "cancel" option mean "user declined".
                        "id": f"option-{i + 1}",
                        "label": str(opt.get("label") or f"选项 {i + 1}"),
                        "description": str(opt.get("description") or ""),
                        "response": str(opt.get("label") or f"选项 {i + 1}"),
                    }
                    for i, opt in enumerate(raw_options)
                    if isinstance(opt, dict)
                ]
            else:
                options = [
                    {
                        "id": "option-confirm",
                        "label": "确认并继续",
                        "description": "确认继续",
                        "response": "确认并继续",
                    },
                    {
                        "id": "option-skip",
                        "label": "跳过问题",
                        "description": "不回答，按合理默认继续",
                        "response": "（用户跳过了这个问题，未提供回答。）",
                    },
                ]
            return options, message
        options = [
            {
                "id": "approve",
                "label": "批准执行",
                "description": "允许后端继续执行这个工具调用。",
                "response": "approve",
            },
            {
                "id": "deny",
                "label": "拒绝执行",
                "description": "不执行这个工具调用，本轮停在等待点。",
                "response": "deny",
            },
        ]
        # user:“一次性处理干净 不要留尾巴”+(同一个审批选项同时进入聊天卡片和确认面板)。
        approval = call.metadata.get("approval", {})
        if isinstance(approval.get("level"), int) and approval["level"] > 1 and not approval.get("blocked"):
            options.insert(1, {"id": "trust", "label": "批准并信任", "description": "执行这次操作，并将完全相同操作的等级永久降低一级。", "response": "trust"})
        return options, self._approval_request_message(call)

    @staticmethod
    def _approval_request_message(call: ToolCall) -> str:
        approval = call.metadata.get("approval") if isinstance(call.metadata, dict) else None
        if isinstance(approval, dict) and approval.get("outside_workdir"):
            # Say what the user is consenting to (the concrete path) instead of
            # only naming the tool that asked.
            reason = str(approval.get("reason") or "").strip()
            if reason:
                return f"需要授权：{reason}"
        args = call.arguments if isinstance(call.arguments, dict) else {}
        command = str(args.get("command") or "").strip()
        if command:
            return f"需要授权后才能执行命令：{command}"
        return f"需要授权后才能执行工具：{call.name}"

    def _record_memory_exhaustion(self, state: RuntimeState) -> str:
        """Name a memory-caused interruption on the state.

        The code, the explanation and the pending auto-resume ride the state —
        not just the step error — so every terminal writer (kernel event,
        app-layer failure record, startup/periodic reconcile) can tell the user
        what happened and the resume watchdog knows what to wait for.
        """
        note_memory_interruption(state)
        message = memory_exhausted_message_for(state)
        state.metadata["failure_message"] = message
        return message

    @staticmethod
    def _failure_detail(state: RuntimeState) -> dict[str, Any]:
        """``failure_code`` / ``failure_message`` from the state, when present."""
        metadata = state.metadata if isinstance(state.metadata, dict) else {}
        detail: dict[str, Any] = {}
        for key in ("failure_code", "failure_message"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                detail[key] = value.strip()
        return detail

    async def _emit_terminal_event(
        self, state: RuntimeState, result: KernelResult
    ) -> None:
        """Emit the final terminal event based on decision."""
        duration_ms = max(
            0,
            round((time_module.monotonic() - self._run_started_at) * 1000),
        )
        runtime_metrics = (
            dict(state.metadata.get("runtime_context_metrics"))
            if isinstance(state.metadata.get("runtime_context_metrics"), dict)
            else None
        )
        failure_detail = self._failure_detail(state)
        if result.decision == "done":
            event = CoreEvent(
                name="runtime.done",
                category="lifecycle",
                payload={
                    "message": result.message,
                    "duration_ms": duration_ms,
                    **({"runtime_metrics": runtime_metrics} if runtime_metrics else {}),
                },
                session_id=state.session_id,
                run_id=state.run_id,
                tags=["done"],
            )
        elif state.status == "cancelled":
            # Both the in-loop cancel break (error == "cancelled") and the
            # external-cancellation path converge here (audit 02). Emitting
            # runtime.cancelled instead of runtime.failed keeps the projected
            # turn status "cancelled" rather than "failed".
            event = CoreEvent(
                name="runtime.cancelled",
                category="lifecycle",
                payload={
                    "error": result.error or "cancelled",
                    "message": result.message,
                    "duration_ms": duration_ms,
                    **({"runtime_metrics": runtime_metrics} if runtime_metrics else {}),
                },
                session_id=state.session_id,
                run_id=state.run_id,
                tags=["cancel"],
            )
        elif state.status == "paused":
            # The turn stopped on the user's request and is resumable, so this
            # is a decision event rather than a terminal one: the projected turn
            # status becomes "paused" and the composer offers Continue. The
            # duration is frozen at the pause instant so the row stops counting.
            event = CoreEvent(
                name="runtime.paused",
                category="decision",
                payload={
                    "message": result.message or "已暂停。",
                    "duration_ms": duration_ms,
                    "pause_reason": str(state.metadata.get("pause_reason") or self._pause_reason or "user_pause"),
                    **failure_detail,
                    **({"runtime_metrics": runtime_metrics} if runtime_metrics else {}),
                },
                session_id=state.session_id,
                run_id=state.run_id,
                tags=["decision", "pause"],
            )
        elif result.decision == "failed":
            event = CoreEvent(
                name="runtime.failed",
                category="error",
                payload={
                    "error": result.error,
                    "message": result.message,
                    **failure_detail,
                    "duration_ms": duration_ms,
                    **({"runtime_metrics": runtime_metrics} if runtime_metrics else {}),
                },
                session_id=state.session_id,
                run_id=state.run_id,
                tags=["error"],
            )
        elif result.decision == "wait":
            waiting_request = {}
            if isinstance(state.metadata, dict):
                raw_waiting_request = state.metadata.get("pending_waiting_request")
                if isinstance(raw_waiting_request, dict):
                    waiting_request = dict(raw_waiting_request)
            event = CoreEvent(
                name="runtime.waiting",
                category="decision",
                payload={
                    "message": result.message or str(waiting_request.get("message") or ""),
                    **waiting_request,
                },
                session_id=state.session_id,
                run_id=state.run_id,
                tags=["decision"],
            )
        else:
            event = CoreEvent(
                name="runtime.ended",
                category="lifecycle",
                payload={"decision": result.decision},
                session_id=state.session_id,
                run_id=state.run_id,
                tags=["state"],
            )
        await self.event_sink.emit(event)


__all__ = [
    "CoreLoopKernel",
]
