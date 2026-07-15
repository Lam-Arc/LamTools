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
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

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
    _cancel_event: asyncio.Event = field(default_factory=asyncio.Event, init=False, repr=False)
    _base_event_sink: EventSink = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._base_event_sink = self.event_sink

    def cancel(self) -> None:
        """Signal the kernel to stop at the next loop iteration.

        The running loop will detect this signal, mark the result as
        failed with error='cancelled', and return.
        """
        self._cancel_event.set()

    async def run(self, turn_input: RuntimeTurnInput) -> KernelResult:
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

        history = await self._load_history(state.session_id)

        # Each user turn is a new run inside the same session. Persisted state
        # carries session memory and turn_count, but a stale run_id/status from
        # a crashed or failed prior run must not leak into the next run.
        state.run_id = str(turn_input.run_id or "").strip() or _new_run_id()
        turn_id = str(turn_input.turn_id or "").strip() or f"{state.session_id}:turn:{state.run_id}"
        state.metadata["turn_id"] = turn_id
        state.metadata.pop("no_progress", None)
        state.metadata.pop("failure_diagnosis", None)
        prior_waiting = state.metadata.get("pending_waiting_request")
        if isinstance(prior_waiting, dict) and prior_waiting.get("request_kind") == "no_progress":
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
            await self.checkpoint_coordinator.begin_turn(
                session_id=state.session_id,
                turn_id=turn_id,
                actor_kind=actor_kind,
            )

        # Start root trace span for this run (after state is loaded so we have ids)
        run_span = self.tracer.start_span(
            "kernel.run", session_id=state.session_id, run_id=state.run_id
        )

        # 2. Mark running
        state.status = "running"
        await self.state_store.save(state)

        # 3. Kit on_run_start
        await self.kit.on_run_start(state, turn_input)

        # 4. Extend persisted conversation history with this user input.
        current_user_content = (
            turn_input.user_content
            if turn_input.user_content is not None
            else turn_input.user_message
        )
        if current_user_content:
            history.append(ChatMessage(role="user", content=current_user_content))
        await self._save_checkpoint(state, history)

        steps: list[KernelStep] = []
        latest_message = ""
        final_decision: LoopDecision = "continue"
        error_msg = ""
        recent_tool_result_fingerprints: list[str] = []
        explicit_input_errors: dict[str, ToolResult] = {}
        diagnosis_failed_calls: dict[str, ToolResult] = {}
        failure_diagnosis_pending = False
        failure_investigation_rounds = 0

        # Emit runtime.started event
        await self._emit_state_event(state, "runtime.started", "run started")

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
                        await self._save_checkpoint(state, history)
                        await self._emit_history_compacted(state, trimmed, len(history))

                context = await self.kit.build_context(state, turn_input, history, index)

                # 5.3 Build model request
                request = await self.kit.build_model_request(state, context)
                await self._compact_request_if_needed(state, request, history=history)

                # 5.4 Call model — try streaming first
                response = await self._stream_model(request, state, response_index=index)
                streamed_response = response is not None
                if response is None:
                    response = await self._call_model(request, state=state, response_index=index)
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
                turn = await self.kit.parse_model_output(state, response)
                step.turn = turn
                failure_diagnosis_completed = (
                    failure_diagnosis_pending
                    and bool(turn.reply.strip())
                    and self._has_failure_diagnosis_structure(turn.reply)
                )
                failure_diagnosis_incomplete = (
                    failure_diagnosis_pending
                    and bool(turn.reply.strip())
                    and not self._has_failure_diagnosis_structure(turn.reply)
                )

                # Kernel-level natural-stop signal (OpenAI-style): model
                # produced a text reply with no tool calls. Kit MAY consume
                # turn.is_natural_stop in decide_next as a done candidate.
                if not turn.tool_calls and turn.reply:
                    turn.is_natural_stop = True

                # 5.6 Emit reply and kit events
                if turn.reply:
                    latest_message = turn.reply
                    if turn.tool_calls or failure_diagnosis_completed or failure_diagnosis_incomplete:
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
                    await self._save_checkpoint(state, history)

                # 5.8 Execute tool calls
                tool_results: list[ToolResult] = []
                blocked_results: dict[str, ToolResult] = {}
                for call in turn.tool_calls:
                    blocked = await self._apply_pre_tool_hook(state, call)
                    if blocked is not None:
                        blocked_results[call.id] = blocked
                    prior_failed_call = diagnosis_failed_calls.get(self._tool_call_fingerprint(call))
                    if (
                        failure_diagnosis_pending
                        and prior_failed_call is not None
                        and self._tool_call_fingerprint(call) not in explicit_input_errors
                        and call.id not in blocked_results
                    ):
                        blocked_results[call.id] = ToolResult(
                            call_id=call.id,
                            name=call.name,
                            status="blocked",
                            content=prior_failed_call.content,
                            error=(
                                "Exact retry blocked while failure diagnosis is pending. "
                                "Investigate the existing evidence and complete the diagnosis first."
                            ),
                            metadata={
                                "failure_diagnosis_required": True,
                                "original_error": prior_failed_call.error,
                            },
                        )
                    if (
                        failure_diagnosis_pending
                        and not failure_diagnosis_completed
                        and failure_investigation_rounds >= 1
                        and call.id not in blocked_results
                    ):
                        blocked_results[call.id] = ToolResult(
                            call_id=call.id,
                            name=call.name,
                            status="blocked",
                            error=(
                                "Failure investigation already collected one round of evidence. "
                                "Complete the visible diagnosis before using more tools."
                            ),
                            metadata={
                                "failure_diagnosis_required": True,
                                "investigation_budget_exhausted": True,
                            },
                        )
                for call in turn.tool_calls:
                    prior_input_error = explicit_input_errors.get(self._tool_call_fingerprint(call))
                    if call.id in blocked_results or prior_input_error is None:
                        continue
                    blocked_results[call.id] = ToolResult(
                        call_id=call.id,
                        name=call.name,
                        status="blocked",
                        content=prior_input_error.content,
                        error=prior_input_error.error,
                        artifacts=list(prior_input_error.artifacts),
                        metadata={
                            **dict(prior_input_error.metadata),
                            "duplicate_input_error": True,
                        },
                    )
                approval_calls = [
                    call
                    for call in turn.tool_calls
                    if call.id not in blocked_results and call.requires_approval
                ]
                if approval_calls:
                    approval_call = approval_calls[0]
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
                    state.turn_count += 1
                    if self.policy.persist_steps:
                        steps_log = state.metadata.setdefault("kernel_steps", [])
                        steps_log.append(self._summarize_step(step))
                    await self._save_checkpoint(state, history)
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
                            blocked_results = {
                                str(call_id): result
                                for call_id, result in maybe_blocked.items()
                                if isinstance(result, ToolResult)
                            }
                    for call in turn.tool_calls:
                        await self._emit_tool_started(state, call, response_index=index)
                    executable_calls = [call for call in turn.tool_calls if call.id not in blocked_results]
                    executed_results = await self._execute_tools_parallel(state, executable_calls) if executable_calls else []
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
                        await self._save_checkpoint(state, history)
                else:
                    # Sequential execution (OpenAI Codex default for shell-safety)
                    for call in turn.tool_calls:
                        await self._emit_tool_started(state, call, response_index=index)
                        if call.id in blocked_results:
                            result = blocked_results[call.id]
                        else:
                            result = await self._execute_tool(state, call)
                        tool_results.append(result)
                        step.tool_steps.append(RuntimeToolStep(call=call, result=result))
                        await self._emit_tool_finished(state, call, result, response_index=index)
                        # 5.9 Append formatted tool result to history
                        tool_message = await self.kit.format_tool_result_for_model(state, call, result)
                        history.append(tool_message)
                        await self._save_checkpoint(state, history)

                if (
                    failure_diagnosis_pending
                    and not failure_diagnosis_completed
                    and any(result.status != "blocked" for result in tool_results)
                ):
                    failure_investigation_rounds += 1

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
                    state.turn_count += 1
                    await self.kit.writeback(
                        state,
                        turn,
                        tool_results,
                        VerificationResult(passed=False, required=True, summary=no_progress),
                        "wait",
                    )
                    if self.policy.persist_steps:
                        state.metadata.setdefault("kernel_steps", []).append(self._summarize_step(step))
                    await self._save_checkpoint(state, history)
                    break
                recovery_prompt = repeat_observation.get("recovery_prompt")
                if isinstance(recovery_prompt, str) and recovery_prompt:
                    history.append(ChatMessage(role="system", content=recovery_prompt))
                    step.metadata["no_progress_recovery_required"] = True
                    state.metadata["no_progress_recovery"] = {
                        "status": "required",
                        "response_index": index,
                    }
                    await self._save_checkpoint(state, history)

                failed_pairs = [
                    (call, result)
                    for call, result in zip(turn.tool_calls, tool_results)
                    if result.status == "failed"
                ]
                if failure_diagnosis_completed:
                    failure_diagnosis_pending = False
                    failure_investigation_rounds = 0
                    diagnosis_failed_calls.clear()
                    step.metadata["failure_diagnosis_completed"] = True
                    state.metadata["failure_diagnosis"] = {
                        "status": "completed",
                        "response_index": index,
                    }
                    if turn.tool_calls and not failed_pairs:
                        history.append(ChatMessage(
                            role="system",
                            content=(
                                "[FAILURE_DIAGNOSIS_RECORDED] The complete diagnosis is already visible. "
                                "After the selected tool calls, report only new verification evidence and "
                                "the final outcome; do not repeat the diagnosis body."
                            ),
                        ))
                    await self._save_checkpoint(state, history)
                elif failure_diagnosis_incomplete:
                    history.append(ChatMessage(
                        role="system",
                        content=(
                            "[FAILURE_DIAGNOSIS_INCOMPLETE] The visible diagnosis is missing required fields. "
                            "Respond without tool calls using exactly these headings: [根因] [证据] [方案1] "
                            "[方案2] [选择] [验证信号]. Field presence is required; do not invent evidence "
                            "or describe an unexecuted tool result as if it already happened."
                        ),
                    ))
                    step.metadata["failure_diagnosis_incomplete"] = True
                    await self._save_checkpoint(state, history)

                if failed_pairs:
                    for call, result in failed_pairs:
                        diagnosis_failed_calls[self._tool_call_fingerprint(call)] = result
                    if not failure_diagnosis_pending:
                        failure_diagnosis_pending = True
                        failure_investigation_rounds = 0
                        prompt = self._failure_diagnosis_prompt(failed_pairs)
                        history.append(ChatMessage(role="system", content=prompt))
                        step.metadata["failure_diagnosis_required"] = True
                        state.metadata["failure_diagnosis"] = {
                            "status": "required",
                            "response_index": index,
                        }
                        await self._save_checkpoint(state, history)

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
                if failure_diagnosis_incomplete:
                    decision = "continue"
                    step.metadata["failure_diagnosis_retry_required"] = True
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

                step.decision = decision
                final_decision = decision

                # Update LoopPhase from Kit
                step.phase = state.position if state.position in ("idle", "plan", "execute", "verify") else "execute"

                # 5.12 Writeback
                await self.kit.writeback(state, turn, tool_results, verification, decision)

                # Update state
                state.loop_state = decision
                state.turn_count += 1

                # 5.12b Persist step summary (OpenAI Rollout-style audit trail)
                if self.policy.persist_steps:
                    steps_log = state.metadata.setdefault("kernel_steps", [])
                    steps_log.append(self._summarize_step(step))

                # 5.13 Save state
                await self._save_checkpoint(state, history)

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
        await self._save_checkpoint(state, history)

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

        # 7. Kit on_run_end
        await self.kit.on_run_end(state, result)

        # 8. Emit final event
        await self._emit_terminal_event(state, result)

        # End root trace span
        self.tracer.end_span(
            run_span,
            status="error" if final_decision == "failed" else "ok",
            decision=final_decision,
            steps=len(steps),
        )

        return result

    @staticmethod
    def _tool_call_fingerprint(call: ToolCall) -> str:
        return json.dumps(
            {"tool": call.name, "arguments": call.arguments},
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )

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
            "[FAILURE_DIAGNOSIS_REQUIRED] A tool failed. Do not repeat the exact call and do not "
            "jump directly to another speculative fix. First investigate the real evidence. You may "
            "use one round of different tool calls to collect missing evidence; after that round, "
            "stop using tools until the diagnosis is visible. Before executing the selected "
            "solution, produce one visible diagnosis with: 根因、证据、至少两个实质不同的方案、"
            "明确选择的方案、以及可观察的验证信号. If the evidence is insufficient, say so and "
            "make the options diagnostic probes rather than inventing a cause. A verification signal "
            "is a future success criterion unless it was actually observed; never claim an unexecuted "
            "tool result as evidence.\n"
            f"Failure evidence:\n{json.dumps(evidence, ensure_ascii=False, sort_keys=True, default=str)}"
        )

    @staticmethod
    def _has_failure_diagnosis_structure(reply: str) -> bool:
        text = str(reply or "").lower()
        required_groups = (
            ("根因", "root cause"),
            ("证据", "evidence"),
            ("选择", "明确选择", "selection", "chosen solution", "selected option", "selected approach"),
            ("验证信号", "verification signal", "success signal"),
        )
        if not all(any(marker in text for marker in group) for group in required_groups):
            return False
        first_option = re.search(r"(?:方案|option)\s*(?:1|一|a)", text, re.IGNORECASE)
        second_option = re.search(r"(?:方案|option)\s*(?:2|二|b)", text, re.IGNORECASE)
        if first_option is not None and second_option is not None:
            return True
        has_options_heading = "options" in text or "方案" in text
        numbered_first = re.search(r"^\s*(?:[-*]\s*)?1[.)]\s+", text, re.MULTILINE)
        numbered_second = re.search(r"^\s*(?:[-*]\s*)?2[.)]\s+", text, re.MULTILINE)
        return has_options_heading and numbered_first is not None and numbered_second is not None

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
            if result.status in {"failed", "blocked"} and count >= threshold:
                return {"audit": audit, "no_progress": (
                    "No progress observed: the same exact failed tool call and result "
                    f"occurred {count} times within the last {window} failed tool results. "
                    "The run is paused and can be resumed after changing the approach or explicitly continuing."
                )}
            if result.status not in {"failed", "blocked"} and count >= threshold * 2:
                return {"audit": audit, "no_progress": (
                    "No progress observed: the same exact successful tool call and result "
                    f"occurred {count} times within the last {window} tool results, even after a rethink request. "
                    "The run is paused and can be resumed after changing the approach or explicitly continuing."
                )}
            if result.status not in {"failed", "blocked"} and count == threshold:
                return {"audit": audit, "recovery_prompt": (
                    "[NO_PROGRESS_REASSESSMENT_REQUIRED] The same exact tool call returned the same result "
                    f"{count} times. Before using tools again, explain what new evidence you expected, then choose "
                    "a materially different investigation or execution approach. Do not repeat the exact call."
                )}
            if count > 1:
                observation["audit"] = audit
        return observation

    async def _load_history(self, session_id: str) -> list[ChatMessage]:
        if not isinstance(self.state_store, RuntimeCheckpointStore):
            return []
        raw_history = await self.state_store.get_history(session_id)
        messages = [message for item in raw_history if (message := _chat_message_from_dict(item)) is not None]
        return _repair_incomplete_tool_history(messages)

    async def _save_checkpoint(self, state: RuntimeState, history: list[ChatMessage]) -> None:
        if isinstance(self.state_store, RuntimeCheckpointStore):
            await self.state_store.save_checkpoint(state, [message.to_dict() for message in history])
            return
        await self.state_store.save(state)

    async def _stream_model(
        self,
        request: LLMRequest,
        state: RuntimeState,
        *,
        response_index: int,
    ) -> LLMResponse | None:
        """Try streaming model call.  Returns a complete LLMResponse on success,
        or None when streaming is not available so the caller can fall back."""
        stream = stream_with_retry(
            self.llm_client,
            request,
            max_attempts=1,
            # Streaming is bounded per idle gap by _next_stream_event().  A
            # wall-clock timeout here would cancel long, healthy responses
            # that keep producing tokens (for example a large write_file
            # argument).  The non-streaming fallback remains bounded by
            # model_timeout_seconds.
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
        try:
            stream_iterator = stream.__aiter__()
            while True:
                try:
                    event = await self._next_stream_event(stream_iterator)
                except StopAsyncIteration:
                    break
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
                    usage_dict = event.usage.to_dict() if event.usage else None
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
                        usage=event.usage,
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
        return LLMResponse(
            content=accumulated,
            thinking=thinking,
            tool_calls=merged_tool_calls,
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
        await self._save_checkpoint(state, history)
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
                "part_id": f"{state.run_id}:model-retry:{response_index if response_index is not None else 'unknown'}:{attempt}",
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

    async def _execute_tool(self, state: RuntimeState, call: ToolCall) -> ToolResult:
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
        return None

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
        """Create a deep copy of state for step recording."""
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
        """Estimate full request tokens, including tool definitions."""
        total = estimate_message_tokens([m.to_dict() for m in request.messages])
        if request.tools:
            total += estimate_text_tokens(json.dumps(request.tools, ensure_ascii=False))
        if request.response_format:
            total += estimate_text_tokens(json.dumps(request.response_format, ensure_ascii=False))
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
            await self._save_checkpoint(state, history)
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
        metrics["llm_calls"] = int(metrics.get("llm_calls") or 0) + 1
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
                ]
                await self._save_checkpoint(state, history)
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
                "message": self._approval_request_message(call),
                "metadata": dict(call.metadata) if isinstance(call.metadata, dict) else {},
                "options": [
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
                ],
                **({"response_index": response_index} if response_index is not None else {}),
            },
            session_id=state.session_id,
            run_id=state.run_id,
            tags=["approval"],
        )
        await self.event_sink.emit(event)

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
