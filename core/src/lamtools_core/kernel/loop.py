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
import json
import logging
import re
import uuid
import time as time_module
from dataclasses import dataclass, field, replace
from typing import Any, TYPE_CHECKING

_logger = logging.getLogger(__name__)

from lamtools_core.context_compaction import (
    ContextCompactionError,
    ContextCompactionRequest,
    ContextCompactionResult,
    compact_context,
    compaction_segment_input_limit,
)
from lamtools_core.event import CoreEvent, EventCategory, EventSink
from lamtools_core.llm import ChatMessage, LLMClient, LLMRequest, LLMResponse, LLMStreamEvent, LLMToolCall
from lamtools_core.llm.helpers import merge_tool_call_deltas, resolve_tool_calls
from lamtools_core.llm.policy import RetryPolicy
from lamtools_core.llm.retry import (
    ModelRetryEvent,
    ModelRetryExhausted,
    classify_model_error,
    complete_with_retry,
    stream_with_retry,
)
from lamtools_core.plugins import HookEvent
from lamtools_core.runtime import (
    CompletionGate,
    RuntimeCheckpointStore,
    RuntimeState,
    RuntimeStateStore,
    RuntimeToolStep,
    RuntimeTurnInput,
)
from lamtools_core.runtime.audit import build_kernel_audit
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
# after this the gate yields to the Kit's verdict (audit 05 S3: unbounded
# forced continue was an infinite-loop entry).
TOOL_PROGRESS_INCOMPLETE_ROUND_LIMIT = 3


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


def _status_from_decision(decision: LoopDecision) -> str:
    mapping = {
        "continue": "running",
        "wait": "waiting",
        "done": "completed",
        "failed": "failed",
    }
    return mapping.get(decision, "failed")


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
    )


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


def _repair_incomplete_tool_history(messages: list[ChatMessage]) -> list[ChatMessage]:
    repaired: list[ChatMessage] = []
    pending: dict[str, LLMToolCall] = {}

    def close_pending() -> None:
        for call in pending.values():
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

    for message in messages:
        if message.role == "tool":
            call_id = str(message.tool_call_id or "")
            if call_id and call_id in pending:
                repaired.append(message)
                pending.pop(call_id, None)
            elif not pending:
                repaired.append(message)
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
    backup_tool_names: tuple[str, ...] = ("write_file", "edit_file")
    completion_gate: CompletionGate | None = None
    memory_store: Any | None = None  # MemoryStoreProtocol; Any to avoid import cycle
    _cancel_event: asyncio.Event = field(default_factory=asyncio.Event, init=False, repr=False)
    # External cancel signal source (e.g. RuntimeTaskRegistry.get_cancel_event).
    # When set by the app layer's turn.cancel path, the kernel can detect it
    # mid-stream and abort the model call cooperatively instead of waiting for
    # the next loop iteration — which may never arrive if the call is blocked
    # on a slow/streaming response. None for sub-agent kernels (no external
    # cancel). See live_operations.handle_turn_cancel_operation.
    cancel_event_source: asyncio.Event | None = field(default=None, repr=False)
    _base_event_sink: EventSink = field(init=False, repr=False)

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

    async def run(self, turn_input: RuntimeTurnInput) -> KernelResult:
        try:
            return await self._run(turn_input)
        except asyncio.CancelledError:
            # task.cancel() bypasses the cooperative cancel check below. Keep
            # terminal persistence in Kernel so main, delegated, and CLI runs
            # all converge through the same state boundary.
            await asyncio.shield(self._persist_external_cancellation(turn_input))
            raise

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
        # Reset cancel event for this run
        self._cancel_event.clear()

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

        # Apply persisted compaction boundary: load only messages after the
        # compaction boundary and prepend the summary so build_model_request
        # sees [summary, *recent_messages] without touching the original history.
        compaction_meta = state.metadata.get("context_compaction") if isinstance(state.metadata, dict) else None
        summary_text = str(compaction_meta.get("summary") or "") if isinstance(compaction_meta, dict) else ""
        if isinstance(compaction_meta, dict) and summary_text.strip():
            # A summary exists whenever compaction happened; the boundary seq
            # is the first retained row minus one and may legitimately be 0.
            boundary = int(compaction_meta.get("summary_seq") or 0)
            if boundary > 0:
                history = await self._load_history(state.session_id, after_seq=boundary)
                # Boundary drift guard: when nothing loads past the anchor the
                # stored seq is stale (history was rebuilt/cleared externally).
                # Fall back to the full history so context is not reduced to
                # the summary alone; the next compaction re-anchors from rows.
                if not history:
                    full_history = await self._load_history(state.session_id)
                    if full_history:
                        history = full_history
            else:
                history = await self._load_history(state.session_id)
            history.insert(0, ChatMessage(
                role="system",
                content=summary_text,
                metadata={"key": "context_compaction_summary"},
            ))
        else:
            history = await self._load_history(state.session_id)
        _logger.info("[kernel:_run] history loaded sid=%s len=%d", state.session_id, len(history))

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

        # 2. Mark running
        state.status = "running"
        await self.state_store.save(state)
        _logger.info("[kernel:_run] state saved as running sid=%s", state.session_id)

        # 3. Kit on_run_start
        await self.kit.on_run_start(state, turn_input)
        # Expose the empty-response retry budget to the Kit (which owns
        # empty-stop retry logic in decide_next). The Kit reads this from
        # state.metadata instead of holding a separate policy reference.
        if state.metadata is None:
            state.metadata = {}
        state.metadata.setdefault("empty_response_retries", int(self.policy.empty_response_retries or 0))

        # 3b. SessionStart hook
        await self._apply_session_start_hook(state, turn_input)

        # 4. Extend persisted conversation history with this user input.
        current_user_content = (
            turn_input.user_content
            if turn_input.user_content is not None
            else turn_input.user_message
        )
        # 4b. UserPromptSubmit hook（先于消息入历史——hook 的
        # additional_context 注入用户消息并随历史持久化，C2 共识）。
        hook_user_content = await self._apply_user_prompt_submit_hook(
            state, turn_input, current_user_content
        )
        if hook_user_content:
            current_user_content = hook_user_content
        new_messages: list[ChatMessage] = []
        if current_user_content:
            user_msg = ChatMessage(role="user", content=current_user_content)
            history.append(user_msg)
            new_messages.append(user_msg)
        await self._append_history_checkpoint(state, new_messages)
        _logger.info("[kernel:_run] checkpoint saved sid=%s", state.session_id)

        steps: list[KernelStep] = []
        latest_message = ""
        final_decision: LoopDecision = "continue"
        error_msg = ""
        recent_tool_result_fingerprints: list[str] = []
        recent_successful_payloads: list[dict[str, Any]] = []
        explicit_input_errors: dict[str, ToolResult] = {}
        consecutive_failure_rounds = 0
        tool_only_rounds = 0
        tool_progress_pending = False
        tool_progress_blocked_rounds = 0
        tool_progress_incomplete_rounds = 0

        # Emit runtime.started event
        await self._emit_state_event(state, "runtime.started", "run started")

        _logger.info("[kernel:_run] entering main loop sid=%s run=%s tools=%d history=%d",
                      state.session_id, state.run_id,
                      len(self.kit.toolbox.tool_specs()) if self.kit.toolbox else 0,
                      len(history))

        # 5. Main loop. There is intentionally no step budget: complex tasks
        # may need many model/tool rounds. Cancellation, explicit failure,
        # waiting for the user, or a no-tool final response ends the run.
        index = 0
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

                await self._consume_guidance(state, turn_input, history, index)

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
                        trimmed = len(history) - cut
                        del history[:cut]
                        await self._replace_history_checkpoint(state, history)
                        await self._emit_history_compacted(state, trimmed, len(history))

                context = await self.kit.build_context(state, turn_input, history, index)

                # 5.3 Build model request
                request = await self.kit.build_model_request(state, context)
                await self._compact_request_if_needed(state, request, history=history)
                # Strip internal bookkeeping metadata (history seq / resume
                # marker) before the request reaches the model — the shared
                # objects in `history` keep their tags for later compactions.
                request.messages = _strip_internal_message_metadata(request.messages)

                # 5.4 Call model — try streaming first
                _step_start = time_module.time()
                _logger.info("[kernel:_run] step=%d calling stream model sid=%s", index, state.session_id)
                response = await self._stream_model(request, state, response_index=index)
                streamed_response = response is not None
                if response is None:
                    response = await self._call_model(request, state=state, response_index=index)
                _step_elapsed = time_module.time() - _step_start
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
                if response.usage is not None and not streamed_response:
                    await self.event_sink.emit(CoreEvent(
                        name="runtime.usage",
                        category="usage",
                        payload={"usage": response.usage.to_dict(), "response_index": index},
                        session_id=state.session_id,
                        run_id=state.run_id,
                        tags=["usage"],
                    ))
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
                tool_progress_structured = (
                    tool_progress_pending
                    and bool(turn.reply.strip())
                    and self._has_tool_progress_structure(turn.reply)
                )
                tool_progress_completed = (
                    tool_progress_pending
                    and bool(turn.reply.strip())
                    and (
                        not turn.tool_calls
                        or tool_progress_structured
                    )
                )
                tool_progress_incomplete = (
                    tool_progress_pending
                    and bool(turn.reply.strip())
                    and bool(turn.tool_calls)
                    and not tool_progress_completed
                )

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
                        role="system",
                        content=(
                            "[DUPLICATE_INPUT_ERROR] Some tool calls match previous input errors. "
                            "Ensure the arguments below are corrected before retrying:\n"
                            + "\n".join(input_error_warnings)
                        ),
                    ))
                approval_calls = [
                    call
                    for call in turn.tool_calls
                    if call.id not in blocked_results and call.requires_approval
                ]
                if approval_calls:
                    approval_call = approval_calls[0]
                    # PermissionRequest hook — allows hook-driven auto-approve / deny
                    perm_hook_result = await self._apply_permission_request_hook(state, approval_call)
                    if not approval_call.requires_approval:
                        # Hook auto-approved the call — skip waiting gate, proceed
                        pass
                    elif perm_hook_result is not None:
                        # Hook denied the call — treat as blocked
                        blocked_results[approval_call.id] = perm_hook_result
                    else:
                        state.metadata["pending_approval"] = {
                            "request_id": approval_call.id,
                            "tool_call": approval_call.to_dict(),
                            "response_index": index,
                            "status": "waiting",
                        }
                        state.metadata["pending_waiting_request"] = {
                            "request_kind": "permission",
                            "tool_call_id": approval_call.id,
                            "tool_name": approval_call.name,
                            "arguments": approval_call.arguments,
                            "metadata": dict(approval_call.metadata),
                            "message": self._approval_request_message(approval_call),
                        }
                        step.metadata["pending_approval"] = state.metadata["pending_approval"]
                        decision = "wait"
                        step.decision = decision
                        final_decision = decision
                        await self.kit.writeback(state, turn, tool_results, VerificationResult(passed=True), decision)
                        state.loop_state = decision
                        if self.policy.persist_steps:
                            steps_log = state.metadata.setdefault("kernel_steps", [])
                            steps_log.append(self._summarize_step(step))
                        await self._save_checkpoint(state)
                        await self._emit_tool_waiting_for_approval(
                            state,
                            approval_call,
                            response_index=index,
                        )
                        await self._emit_approval_request(state, approval_call, response_index=index)
                        break
                parallel_names = set(self.policy.parallel_tool_names)
                can_parallelize_named_tools = (
                    bool(parallel_names)
                    and len(turn.tool_calls) > 1
                    and all(call.name in parallel_names for call in turn.tool_calls)
                )
                if (self.policy.parallel_tool_calls or can_parallelize_named_tools) and len(turn.tool_calls) > 1:
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
                    executed_results = await self._execute_tools_parallel(state, executable_calls) if executable_calls else []
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
                        history.append(tool_message)
                        await self._save_checkpoint(state)
                else:
                    # Sequential execution (OpenAI Codex default for shell-safety)
                    for call_index, call in enumerate(turn.tool_calls):
                        await self._emit_tool_started(state, call, response_index=index)
                        if call.id in blocked_results:
                            result = blocked_results[call.id]
                        else:
                            result = await self._execute_tool(state, call)
                            # PostToolUse / PostToolUseFailure hook
                            result = await self._apply_post_tool_hook(state, call, result)
                        tool_results.append(result)
                        step.tool_steps.append(RuntimeToolStep(call=call, result=result))
                        await self._emit_tool_finished(state, call, result, response_index=index)
                        # 5.9 Append formatted tool result to history
                        tool_message = await self.kit.format_tool_result_for_model(state, call, result)
                        history.append(tool_message)
                        await self._save_checkpoint(state)
                        if not await self._consume_guidance(state, turn_input, history, index):
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
                        break

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
                    tool_progress_pending = True
                    history.append(ChatMessage(
                        role="system",
                        content=(
                            "[SUBSTANTIVE_PAYLOAD_REASSESSMENT_REQUIRED] A successful tool call reused a "
                            "materially identical large payload under different arguments. Reuse the existing "
                            "artifact or result, or explain what genuinely new evidence another call would add "
                            "before choosing a materially different action."
                        ),
                    ))
                    step.metadata["substantive_payload_reassessment_required"] = True
                    await self._save_checkpoint(state)

                executed_tool_round = any(result.status != "blocked" for result in tool_results)

                progress_gate_blocked = any(
                    bool(result.metadata.get("tool_progress_required")) for result in tool_results
                )
                if progress_gate_blocked:
                    tool_progress_blocked_rounds += 1
                    if tool_progress_blocked_rounds >= 2:
                        message = (
                            "Tool progress did not converge after two reminders. The run is paused and can be "
                            "resumed after reporting confirmed facts, remaining uncertainty, and the next action."
                        )
                        step.decision = "wait"
                        step.metadata["tool_progress_no_progress"] = True
                        state.metadata["tool_progress"] = {
                            "status": "waiting",
                            "response_index": index,
                            "recoverable": True,
                        }
                        state.metadata["pending_waiting_request"] = {
                            "request_kind": "no_progress",
                            "message": message,
                        }
                        final_decision = "wait"
                        state.loop_state = "wait"
                        await self.kit.writeback(
                            state,
                            turn,
                            tool_results,
                            VerificationResult(passed=False, required=True, summary=message),
                            "wait",
                        )
                        if self.policy.persist_steps:
                            state.metadata.setdefault("kernel_steps", []).append(self._summarize_step(step))
                        await self._save_checkpoint(state)
                        break

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
                    history.append(ChatMessage(role="system", content=recovery_prompt))
                    step.metadata["no_progress_recovery_required"] = True
                    state.metadata["no_progress_recovery"] = {
                        "status": "required",
                        "response_index": index,
                    }
                    await self._save_checkpoint(state)

                if (
                    tool_progress_completed
                    and not payload_reassessment_required
                    and not duplicate_payload_blocked
                ):
                    tool_progress_pending = False
                    tool_only_rounds = 0
                    tool_progress_blocked_rounds = 0
                    tool_progress_incomplete_rounds = 0
                    step.metadata["tool_progress_completed"] = True
                    state.metadata["tool_progress"] = {
                        "status": "completed",
                        "response_index": index,
                    }
                    await self._save_checkpoint(state)
                elif tool_progress_incomplete:
                    history.append(ChatMessage(
                        role="system",
                        content=(
                            "[TOOL_PROGRESS_INCOMPLETE] Respond with these three headings before more tools: "
                            "[已确认事实] [剩余不确定性] [下一步]. Keep it concise and reuse existing evidence."
                        ),
                    ))
                    step.metadata["tool_progress_incomplete"] = True
                    await self._save_checkpoint(state)
                elif turn.tool_calls and not turn.reply.strip() and executed_tool_round:
                    tool_only_rounds += 1
                    limit = self.policy.max_tool_only_rounds_without_progress
                    if limit is not None and limit > 0 and tool_only_rounds >= limit:
                        history.append(ChatMessage(
                            role="system",
                            content=(
                                "[TOOL_PROGRESS_REQUIRED] Before using more tools, briefly report "
                                "[已确认事实] [剩余不确定性] [下一步]. Do not repeat prior evidence, and do not "
                                "claim a result that has not been observed."
                            ),
                        ))
                        step.metadata["tool_progress_required"] = True
                        state.metadata["tool_progress"] = {
                            "status": "required",
                            "response_index": index,
                            "tool_only_rounds": tool_only_rounds,
                        }
                        await self._save_checkpoint(state)
                elif turn.reply.strip():
                    tool_only_rounds = 0

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
                        history.append(ChatMessage(role="system", content=prompt))
                        step.metadata["failure_diagnosis_hint"] = True
                        state.metadata["failure_diagnosis"] = {
                            "status": "hint",
                            "response_index": index,
                            "consecutive_rounds": threshold,
                        }
                        await self._save_checkpoint(state)
                else:
                    consecutive_failure_rounds = 0

                # 5.9b Track MCP server activation from mcp_activate tool calls
                for result in tool_results:
                    if (
                        result.name == "mcp_activate"
                        and result.status == "ok"
                        and isinstance(result.metadata, dict)
                    ):
                        server = str(result.metadata.get("activated_server") or "").strip()
                        if server:
                            activated = [
                                s
                                for s in state.metadata.get("activated_mcp_servers", [])
                                if isinstance(s, str)
                            ]
                            if server not in activated:
                                activated.append(server)
                                state.metadata["activated_mcp_servers"] = activated

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
                if tool_progress_incomplete or (tool_progress_completed and tool_progress_structured):
                    # The progress gate may only force a continuation while the
                    # Kit itself wants to keep going (continue/done); overriding
                    # a terminal Kit verdict (wait/failed) would defeat it
                    # (audit 05 S3).  A model that keeps replying text+tools
                    # without the required structure gets a bounded number of
                    # forced rounds, then we stop forcing and surface a wait.
                    if tool_progress_incomplete:
                        if decision in {"continue", "done"}:
                            tool_progress_incomplete_rounds += 1
                            if tool_progress_incomplete_rounds >= TOOL_PROGRESS_INCOMPLETE_ROUND_LIMIT:
                                decision = "wait"
                                step.metadata["tool_progress_no_progress"] = True
                                state.metadata["tool_progress_no_progress"] = True
                            else:
                                decision = "continue"
                                step.metadata["tool_progress_retry_required"] = True
                    elif decision in {"continue", "done"}:
                        decision = "continue"
                elif turn.tool_calls and decision == "done":
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
                    if await self._consume_guidance(state, turn_input, history, index, finalize=True):
                        decision = "continue"
                        step.metadata["guidance_force_continue"] = True

                if decision == "done" and self.completion_gate is not None:
                    should_verify = getattr(self.completion_gate, "should_verify", None)
                    if callable(should_verify) and not should_verify(state):
                        state.metadata.pop("goal_completion", None)
                        step.metadata.pop("goal_completion", None)
                    else:
                        completion = await self.completion_gate.verify(state, {
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
                                    role="system",
                                    content=f"[GOAL_INCOMPLETE] {repair_instruction}",
                                ))
                                await self._save_checkpoint(state)
                                decision = "continue"

                step.decision = decision
                final_decision = decision

                # Update LoopPhase from Kit
                step.phase = state.position if state.position in ("idle", "plan", "execute", "verify") else "execute"

                # 5.12 Writeback
                await self.kit.writeback(state, turn, tool_results, verification, decision)

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

            except KernelError as e:
                error_msg = str(e)
                step.error = error_msg
                final_decision = "failed"
                break
            except ContextCompactionError as e:
                error_msg = str(e)
                step.error = error_msg
                final_decision = "failed"
                break
            except Exception as e:
                _logger.exception("[kernel:_run] unexpected error sid=%s step=%d",
                                  state.session_id, index)
                error_msg = f"Unexpected error: {e}"
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
        state.loop_state = final_decision
        await self._replace_history_checkpoint(state, history)

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

        return result

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

    async def _persist_external_cancellation(self, turn_input: RuntimeTurnInput) -> None:
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
        history = await self._load_history(state.session_id)
        await self._replace_history_checkpoint(state, history)

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
        await self._finalize_run(state, result, getattr(self, "_run_span", None))
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

    @staticmethod
    def _has_tool_progress_structure(reply: str) -> bool:
        raw_text = str(reply or "").strip()
        text = raw_text.lower()
        required_groups = (
            ("已确认事实", "confirmed facts"),
            ("剩余不确定性", "remaining uncertainty"),
            ("下一步", "next action", "next step"),
        )
        if all(any(marker in text for marker in group) for group in required_groups):
            return True
        substantive_lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        return len(raw_text) >= 80 and len(substantive_lines) >= 3

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
        return _repair_incomplete_tool_history(messages)

    async def _save_checkpoint(self, state: RuntimeState) -> None:
        """Persist runtime state metadata (mid-loop checkpoint).

        Only state metadata is saved here; conversation history is NOT
        written. History is persisted separately at well-defined boundaries:
        the initial checkpoint after the user message
        (``_append_history_checkpoint``), after context compaction, and at
        loop exit (``_replace_history_checkpoint``). Writing history on every
        mid-loop step would be wasteful; the boundary checkpoints are
        sufficient for crash recovery.
        """
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
                await self.state_store.append_history(
                    state.session_id, [m.to_dict() for m in messages]
                )
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
            self._recompute_compaction_boundary(state, history)
            await self.state_store.replace_history(
                state.session_id, [m.to_dict() for m in history]
            )
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
        try:
            stream_iterator = stream.__aiter__()
            while True:
                try:
                    event = await self._next_stream_event(stream_iterator)
                except StopAsyncIteration:
                    break
                # Cooperative cancel during streaming: the app-layer Stop
                # button sets the registry cancel event. Abort the stream
                # immediately rather than waiting for the model to finish —
                # without this a long/slow stream makes Stop appear to do
                # nothing (the 2b34c636 "stop 无效" symptom).
                if self._is_external_cancelled():
                    raise asyncio.CancelledError()
                if event.metadata and event.metadata.get("finish_reason"):
                    stream_finish_reason = str(event.metadata["finish_reason"])
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
                elif event.kind == "done":
                    # Prefer tool_calls from the done event (some providers
                    # include complete tool_calls in the final chunk);
                    # otherwise merge accumulated deltas.
                    tool_calls = event.tool_calls or []
                    if not tool_calls and pending_tool_calls:
                        tool_calls = resolve_tool_calls(pending_tool_calls)
                    if not accumulated and not thinking and not tool_calls:
                        await self._emit_stream_fallback(state, "流式响应未返回内容")
                        return None
                    await self._emit_final_stream_tool_input_delta_parts(
                        state,
                        response_index=response_index,
                        tool_calls=tool_calls,
                        emitted_arguments=emitted_tool_input_arguments,
                        raw=event.raw,
                    )
                    await self._emit_final_stream_text_parts(
                        state,
                        response_index=response_index,
                        accumulated=accumulated,
                        thinking=thinking,
                        emitted_text=emitted_text,
                        emitted_thinking=emitted_thinking,
                        raw=event.raw,
                    )
                    # Emit a terminal delta so members can format the done chunk
                    finish_reason = event.metadata.get("finish_reason", "stop") if event.metadata else "stop"
                    usage = event.usage or pending_usage
                    usage_dict = usage.to_dict() if usage else None
                    await self.event_sink.emit(CoreEvent(
                        name="runtime.reply_delta",
                        category="message",
                        payload={
                            "content": "",
                            "finish_reason": finish_reason,
                            "usage": usage_dict,
                            "response_index": response_index,
                        },
                        session_id=state.session_id,
                        run_id=state.run_id,
                        tags=["reply", "done"],
                    ))
                    return LLMResponse(
                        content=accumulated,
                        thinking=thinking,
                        tool_calls=tool_calls,
                        usage=usage,
                        finish_reason=finish_reason,
                        metadata=event.metadata or {},
                    )
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

        # Stream ended without a done event — build response from accumulated data
        merged_tool_calls = resolve_tool_calls(pending_tool_calls) if pending_tool_calls else []
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
        )

    async def _consume_guidance(
        self,
        state: RuntimeState,
        turn_input: RuntimeTurnInput,
        history: list[ChatMessage],
        response_index: int,
        *,
        finalize: bool = False,
    ) -> bool:
        if finalize and turn_input.guidance_finalizer is not None:
            guidance_items = turn_input.guidance_finalizer() or []
        else:
            source = turn_input.guidance_source
            guidance_items = source() if source is not None else []
        guidance = [str(item).strip() for item in guidance_items if str(item).strip()]
        if not guidance:
            return False
        for item in guidance:
            history.append(ChatMessage(role="user", content=item))
            await self.event_sink.emit(CoreEvent(
                name="runtime.guidance_received",
                category="message",
                payload={"content": item, "response_index": response_index},
                session_id=state.session_id,
                run_id=state.run_id,
                tags=["guidance"],
            ))
        await self._save_checkpoint(state)
        return True

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

    async def _backup_file_for_writer_tool(self, state: RuntimeState, call: ToolCall) -> None:
        """Back up file before a write_file / edit_file tool executes."""
        if self.checkpoint_coordinator is None:
            return
        if call.name not in self.backup_tool_names:
            return
        file_path = (
            call.arguments.get("path")
            or call.arguments.get("file_path")
            or call.arguments.get("filePath")
            or call.arguments.get("target_file")
            or call.arguments.get("target")
        )
        if not file_path or not isinstance(file_path, str):
            return
        try:
            await self.checkpoint_coordinator.backup_file(
                session_id=state.session_id,
                path=file_path,
            )
        except Exception:
            _logger.warning("[kernel:_backup_file_for_writer_tool] backup skipped sid=%s path=%s",
                            state.session_id, file_path, exc_info=True)

    async def _execute_tool(self, state: RuntimeState, call: ToolCall) -> ToolResult:
        """Execute a single tool call via Kit.

        Approval-required calls are intercepted by the main loop before this
        method. Reaching this branch with requires_approval=True means a caller
        bypassed the waiting-gate contract; do not emit a second approval event
        or execute the tool.
        """
        await self._backup_file_for_writer_tool(state, call)
        if call.requires_approval:
            return ToolResult(
                call_id=call.id,
                name=call.name,
                status="blocked",
                error="Tool requires approval and was not routed through a waiting request.",
                metadata={"approval_contract_violation": True},
            )
        execution = self.kit.execute_tool(state, call)
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

    async def _apply_pre_tool_hook(
        self,
        state: RuntimeState,
        call: ToolCall,
    ) -> ToolResult | None:
        if self.hook_engine is None:
            return None
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
        return None

    # ── Post‑tool hook (PostToolUse / PostToolUseFailure) ────────

    def _tool_result_as_dict(self, result: ToolResult) -> dict[str, Any]:
        """Export ToolResult fields into a plain dict for hook payload."""
        return {
            "call_id": result.call_id,
            "name": result.name,
            "status": result.status,
            "content": result.content,
            "error": result.error,
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
            metadata=dict(turn_input.metadata),
        ))
        if decision.status_message:
            await self._emit_hook_status(state, "", decision.status_message)

    async def _dream_if_needed(self, state: RuntimeState, result: Any) -> None:
        """Consolidate session memory after a run (LamTools "dreaming").

        Fires only when ``policy.dreaming_enabled`` is True and the turn
        produced something worth dreaming (a compaction summary or tool use).
        The entire body is wrapped in try/except so a dreaming failure can
        never kill the run — it is best-effort background consolidation.
        """
        if self.memory_store is None:
            return
        if not getattr(self.policy, "dreaming_enabled", False):
            return
        try:
            from lamtools_core.mem.dreaming import dream_session, should_dream, record_dream_turn

            metadata = state.metadata if isinstance(state.metadata, dict) else {}
            compaction = metadata.get("context_compaction")
            had_compaction = isinstance(compaction, dict) and bool(compaction.get("summary"))
            # A run that executed at least one tool step is "worth dreaming".
            had_tool_use = len(getattr(result, "steps", [])) > 0
            if not should_dream(
                state, policy=self.policy, had_compaction=had_compaction, had_tool_use=had_tool_use
            ):
                return

            # Reload history from the store — at this point history is already
            # persisted (``_replace_history_checkpoint`` ran before the stop
            # hook). Use the same loader the kernel uses elsewhere.
            history: list[ChatMessage] = []
            if isinstance(self.state_store, RuntimeCheckpointStore):
                raw = await self.state_store.get_history(state.session_id)
                history = [
                    msg for item in raw if (msg := _chat_message_from_dict(item)) is not None
                ]

            compaction_summary: str | None = None
            if isinstance(compaction, dict):
                raw_summary = compaction.get("summary")
                if isinstance(raw_summary, str) and raw_summary.strip():
                    compaction_summary = raw_summary

            work_root = str(metadata.get("work_root") or "")
            active_model = str(metadata.get("model_id") or "")

            await dream_session(
                session_id=state.session_id,
                work_root=work_root,
                history=history,
                compaction_summary=compaction_summary,
                memory_store=self.memory_store,
                llm_client=self.llm_client,
                model=active_model,
                policy=self.policy,
            )
            record_dream_turn(state)
            # Persist the updated last_dream_turn marker.
            if isinstance(self.state_store, RuntimeCheckpointStore):
                await self.state_store.save(state)
        except Exception:  # noqa: BLE001 - dreaming must never kill the run
            # Swallow: dreaming is best-effort. The run has already succeeded;
            # a memory-consolidation failure should not surface to the user.
            pass

    async def _apply_session_stop_hook(
        self,
        state: RuntimeState,
        result: KernelResult,
    ) -> None:
        # Dreaming runs before external Stop hooks so the consolidated memory
        # is available to any downstream process observing the run's end.
        await self._dream_if_needed(state, result)
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
            metadata=dict(turn_input.metadata),
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

    async def _execute_tools_parallel(
        self, state: RuntimeState, calls: list[ToolCall]
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
                    return await self._execute_tool(state, c)

            return list(await asyncio.gather(*(_bounded(c) for c in calls)))
        return list(await asyncio.gather(*(self._execute_tool(state, c) for c in calls)))

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

    def _estimate_request_tokens(self, request: LLMRequest) -> int:
        """Estimate full request tokens, including tool definitions.

        Uses the fast estimation path because the result is only used for
        context-window trigger checks — ±20 % is acceptable here.
        """
        total = estimate_message_tokens(
            [m.to_dict() for m in request.messages], fast=True
        )
        if request.tools:
            total += estimate_text_tokens(
                json.dumps(request.tools, ensure_ascii=False), fast=True
            )
        if request.response_format:
            total += estimate_text_tokens(
                json.dumps(request.response_format, ensure_ascii=False), fast=True
            )
        return total

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
        """Structurally summarize old context when the request nears budget."""
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
        window = self.policy.context_window_tokens
        if window is None or window <= 0:
            return

        trigger_ratio = min(max(self.policy.compact_trigger_ratio, 0.01), 1.0)
        limit_ratio = min(max(self.policy.compact_limit_ratio, 0.01), trigger_ratio)
        trigger_tokens = int(self.policy.compact_trigger_tokens or int(window * trigger_ratio))
        limit_tokens = int(self.policy.compact_limit_tokens or int(window * limit_ratio))
        trigger_tokens = min(max(1, trigger_tokens), window)
        limit_tokens = min(max(1, limit_tokens), trigger_tokens)
        before_tokens = self._estimate_request_tokens(request)
        request.metadata["estimated_prompt_tokens"] = before_tokens
        request.metadata["context_window_tokens"] = window
        request.metadata["context_compaction_trigger_tokens"] = trigger_tokens
        state.metadata["runtime_context_metrics"] = {
            **metrics,
            "estimated_prompt_tokens": before_tokens,
            "context_window_tokens": window,
            "context_compaction_trigger_tokens": trigger_tokens,
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

        before_messages = len(request.messages)
        request_messages_before_compaction = list(request.messages)

        def estimate_compaction_tokens(messages: list[ChatMessage]) -> int:
            original_messages = request.messages
            request.messages = messages
            try:
                return self._estimate_request_tokens(request)
            finally:
                request.messages = original_messages

        async def attempt_compaction(
            *,
            model: str,
            model_window: int,
            strategy: str,
            fallback_on_terminal: bool,
        ) -> ContextCompactionResult:
            async def on_compaction_delta(delta: str) -> None:
                await self._emit_stream_part(
                    state,
                    part_id=f"{state.run_id}:context-compaction",
                    part_type="compaction",
                    status="running",
                    label="正在压缩上下文",
                    delta=delta,
                    transient=True,
                )

            async def on_compaction_event(payload: dict[str, Any]) -> None:
                event_payload = dict(payload)
                if event_payload.get("status") == "running" and event_payload.get("delta"):
                    return
                if fallback_on_terminal and event_payload.get("status") in {"failed", "not_needed"}:
                    event_payload.update(
                        {
                            "status": "running",
                            "phase": "fallback",
                            "label": "原模型压缩未完成 · 正在改用当前模型",
                        }
                    )
                await self.event_sink.emit(
                    CoreEvent(
                        name="runtime.part",
                        category="message",
                        payload={
                            "part_id": f"{state.run_id}:context-compaction",
                            "part_type": "compaction",
                            "execution_model": model,
                            "strategy": strategy,
                            **event_payload,
                        },
                        session_id=state.session_id,
                        run_id=state.run_id,
                        tags=["stream", "compaction"],
                    )
                )

            return await compact_context(
                ContextCompactionRequest(
                    trigger="model_switch" if model_switched else "auto",
                    messages=list(request.messages),
                    llm_client=self.llm_client,
                    model=model,
                    timeout=request.timeout,
                    limit_tokens=limit_tokens,
                    input_limit_tokens=compaction_segment_input_limit(model_window),
                    estimate_tokens=estimate_compaction_tokens,
                    on_delta=on_compaction_delta,
                    on_event=on_compaction_event,
                    model_retries=self.policy.model_retries,
                    model_timeout_seconds=self.policy.model_timeout_seconds,
                    retry_policy=self.retry_policy,
                    on_model_retry=lambda retry: self._emit_model_retry_from_event(
                        retry,
                        state=state,
                        response_index=None,
                    ),
                )
            )

        allow_previous = request.metadata.get("allow_previous_model_compaction") is not False
        used_previous_model = (
            model_switched
            and allow_previous
            and previous_window > 0
            and before_tokens <= previous_window
        )
        if used_previous_model:
            result = await attempt_compaction(
                model=previous_model,
                model_window=previous_window,
                strategy="previous_model_once",
                fallback_on_terminal=True,
            )
        else:
            result = None
        if result is None or result.status != "compacted":
            result = await attempt_compaction(
                model=current_model,
                model_window=window,
                strategy="segmented_current_model" if model_switched else "current_model",
                fallback_on_terminal=False,
            )
            execution_model = current_model
            compaction_strategy = "segmented_current_model" if model_switched else "current_model"
        else:
            execution_model = previous_model
            compaction_strategy = "previous_model_once"
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

        request.messages[:] = result.replacement_messages
        # Do NOT overwrite persisted history.  Store the compaction summary +
        # boundary seq in state.metadata so the next _run loads only the
        # retained span after the boundary and prepends the summary.  The
        # boundary is the row seq of the first retained message MINUS one —
        # never the history tail, otherwise the retained span (c) is dropped
        # on the next run and context degrades to a summary-only ghost.
        compaction_boundary = 0
        retained_messages = result.retained_messages
        if retained_messages:
            first_retained = retained_messages[0]
            first_seq = (
                first_retained.metadata.get("history_seq")
                if isinstance(first_retained.metadata, dict)
                else None
            )
            if isinstance(first_seq, int) and first_seq > 0:
                compaction_boundary = first_seq - 1
                # Resume marker travels with the first retained message so any
                # later full history rewrite (truncation / loop exit) can
                # re-anchor summary_seq after rows are renumbered.
                first_retained.metadata["lam_compaction_resume"] = True
            else:
                # No known row seq (e.g. a message synthesized by tool-history
                # repair): fall back to loading everything so nothing is lost.
                compaction_boundary = 0
        state.metadata["context_compaction"] = {
            "summary": result.summary,
            "summary_seq": compaction_boundary,
            "compacted_count": result.compacted_count,
            "retained_count": result.retained_count,
            "before_tokens": result.before_tokens,
            "after_tokens": result.after_tokens,
        }
        # Mutate the in-memory history list so the rest of this run sees the
        # compacted view, but do NOT persist the replacement over the original
        # and do NOT let the summary message leak into history rows.
        if history is not None:
            history_message_ids = {id(message) for message in history}
            if any(id(message) in history_message_ids for message in request_messages_before_compaction):
                request_only_ids = {
                    id(message)
                    for message in request_messages_before_compaction
                    if id(message) not in history_message_ids
                }
                history[:] = [
                    message
                    for message in result.replacement_messages
                    if id(message) not in request_only_ids
                    and message.metadata.get("key") != "context_compaction_summary"
                ]
        request.metadata["estimated_prompt_tokens"] = result.after_tokens

        request.metadata["context_compacted"] = True
        request.metadata["context_compaction_mode"] = "structured_summary"
        request.metadata["context_compaction_strategy"] = compaction_strategy
        request.metadata["context_compaction_execution_model"] = execution_model
        request.metadata["context_tokens_before_compaction"] = result.before_tokens
        request.metadata["context_tokens_after_compaction"] = result.after_tokens
        request.metadata["context_messages_before_compaction"] = before_messages
        request.metadata["context_messages_after_compaction"] = len(request.messages)
        state.metadata["runtime_context_metrics"] = {
            **metrics,
            "estimated_prompt_tokens": result.after_tokens,
            "context_window_tokens": window,
            "context_compaction_trigger_tokens": trigger_tokens,
            "context_compacted": True,
            "context_compaction_mode": "structured_summary",
            "context_tokens_before_compaction": result.before_tokens,
            "context_tokens_after_compaction": result.after_tokens,
            "context_messages_before_compaction": before_messages,
            "context_messages_after_compaction": len(request.messages),
            "context_compaction_strategy": compaction_strategy,
            "context_compaction_execution_model": execution_model,
            "model_id": current_model,
        }
        await self._persist_runtime_context_metrics(state, history=None)
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

    async def _emit_tool_finished(
        self,
        state: RuntimeState,
        call: ToolCall,
        result: ToolResult,
        *,
        response_index: int | None = None,
    ) -> None:
        """Emit a tool finished event."""
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
                **({"response_index": response_index} if response_index is not None else {}),
            },
            session_id=state.session_id,
            run_id=state.run_id,
            tags=["tool"],
        )
        await self.event_sink.emit(event)
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
    ) -> None:
        """Emit an approval request event before executing a tool that
        requires approval (OpenAI Codex-style ExecApprovalRequest)."""
        options, message = self._approval_request_options_and_message(call)
        event = CoreEvent(
            name="runtime.approval_request",
            category="decision",
            payload={
                "tool_call_id": call.id,
                "request_id": call.id,
                "tool_name": call.name,
                "arguments": call.arguments,
                "reason": call.reason,
                "request_kind": "permission",
                "message": message,
                "metadata": dict(call.metadata) if isinstance(call.metadata, dict) else {},
                "options": options,
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
            message = str(args.get("question") or "等待用户确认")
            raw_options = args.get("options")
            if isinstance(raw_options, list) and raw_options:
                options = [
                    {
                        "id": str(opt.get("label") or opt.get("id") or f"option-{i + 1}"),
                        "label": str(opt.get("label") or f"选项 {i + 1}"),
                        "description": str(opt.get("description") or ""),
                        "response": str(opt.get("label") or ""),
                    }
                    for i, opt in enumerate(raw_options)
                    if isinstance(opt, dict)
                ]
            else:
                options = [
                    {"id": "confirm", "label": "确认", "description": "确认继续", "response": "confirm"},
                    {"id": "cancel", "label": "取消", "description": "取消当前操作", "response": "cancel"},
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
        return options, self._approval_request_message(call)

    @staticmethod
    def _approval_request_message(call: ToolCall) -> str:
        args = call.arguments if isinstance(call.arguments, dict) else {}
        command = str(args.get("command") or "").strip()
        if command:
            return f"需要授权后才能执行命令：{command}"
        return f"需要授权后才能执行工具：{call.name}"

    async def _emit_terminal_event(
        self, state: RuntimeState, result: KernelResult
    ) -> None:
        """Emit the final terminal event based on decision."""
        runtime_metrics = (
            dict(state.metadata.get("runtime_context_metrics"))
            if isinstance(state.metadata.get("runtime_context_metrics"), dict)
            else None
        )
        if result.decision == "done":
            event = CoreEvent(
                name="runtime.done",
                category="lifecycle",
                payload={
                    "message": result.message,
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
                    **({"runtime_metrics": runtime_metrics} if runtime_metrics else {}),
                },
                session_id=state.session_id,
                run_id=state.run_id,
                tags=["cancel"],
            )
        elif result.decision == "failed":
            event = CoreEvent(
                name="runtime.failed",
                category="error",
                payload={
                    "error": result.error,
                    "message": result.message,
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
