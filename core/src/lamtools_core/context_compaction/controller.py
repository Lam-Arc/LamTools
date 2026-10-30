"""Orchestration for the context-compaction pipeline.

Compaction is not a one-time state: a session may compact any number of times;
there is no permanent "already compacted" status.
"""

from __future__ import annotations

import asyncio
from math import ceil
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Any

from lamtools_core.context_compaction_budget import (
    DEFAULT_SUMMARY_OUTPUT_TOKENS,
    SummaryTokenBudget,
    TokenBudget,
    TokenMeasurement,
    load_retained_steps,
    calibrated_tokens,
    resolve_retained_steps,
)
from lamtools_core.llm import ChatMessage, LLMClient
from lamtools_core.llm.policy import RetryPolicy
from lamtools_core.llm.retry import ModelRetrySink
from lamtools_core.tokens import estimate_message_tokens

from .fitter import CompactionFitter
from .formatting import (
    RECENT_USER_MESSAGES_METADATA_KEY,
    extract_recent_user_messages,
    strip_recent_user_messages,
)
from .models import (
    CompactionBudgetExceeded,
    CompactionDeltaSink,
    CompactionEventSink,
    CompactionFitInput,
    CompactionOptions,
    CompactionTokenEstimator,
    ContextCompactionError,
    ContextCompactionRequest,
    ContextCompactionResult,
)
from .planner import compaction_segment_input_limit, select_context_compaction_layout
from .summarizer import (
    emit_event_sink as _emit_event_sink,
    summarize_context_messages,
)


@dataclass(frozen=True, slots=True)
class CompactionExecution:
    """A request-level compaction decision plus the pipeline result."""

    result: ContextCompactionResult | None
    measurement: TokenMeasurement
    execution_model: str = ""
    strategy: str = ""


class ContextCompactor:
    """Facade shared by automatic and manual context-compaction entrypoints."""

    def __init__(
        self,
        *,
        llm_client: LLMClient | None = None,
        model: str = "",
        timeout: float | None = None,
        input_limit_tokens: int | None = None,
        existing_summary: str = "",
        on_delta: CompactionDeltaSink | None = None,
        on_event: CompactionEventSink | None = None,
        estimate_tokens: CompactionTokenEstimator | None = None,
        estimate_exact_tokens: CompactionTokenEstimator | None = None,
        summary_budget: SummaryTokenBudget | None = None,
        model_retries: int = 1,
        model_timeout_seconds: float | None = None,
        retry_policy: RetryPolicy | None = None,
        on_model_retry: ModelRetrySink | None = None,
        retained_steps: int | None = None,
        pipeline: Callable[..., Awaitable[ContextCompactionResult]] | None = None,
        request_metadata: dict[str, Any] | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._model = model
        self._timeout = timeout
        self._input_limit_tokens = input_limit_tokens
        self._existing_summary = existing_summary
        self._on_delta = on_delta
        self._on_event = on_event
        self._estimate_tokens = estimate_tokens
        self._estimate_exact_tokens = estimate_exact_tokens
        self._summary_budget = summary_budget
        self._model_retries = model_retries
        self._model_timeout_seconds = model_timeout_seconds
        self._retry_policy = retry_policy
        self._on_model_retry = on_model_retry
        self._retained_steps = retained_steps
        self._pipeline = pipeline
        self._request_metadata = dict(request_metadata or {})

    async def compact(
        self,
        messages: list[ChatMessage],
        *,
        budget: TokenBudget,
        options: CompactionOptions | None = None,
        trigger: str | None = None,
        retained_steps: int | None = None,
        authoritative_tokens: int = 0,
        _skip_trigger_check: bool = False,
    ) -> ContextCompactionResult | None:
        """Run the common compaction pipeline when the invocation warrants it.

        Automatic calls return ``None`` while still below the trigger.  A
        forced call bypasses that check and preserves the existing manual
        behavior.  ``_skip_trigger_check`` is for callers that already had to
        measure a request with provider-specific overhead (the kernel); it
        does not change the compaction pipeline itself.
        """
        resolved_options = options or CompactionOptions()
        effective_retained_steps = (
            retained_steps
            if retained_steps is not None
            else self._retained_steps
            if self._retained_steps is not None
            else resolved_options.retained_steps
        )
        if effective_retained_steps != resolved_options.retained_steps:
            resolved_options = replace(
                resolved_options,
                retained_steps=effective_retained_steps,
            )
        target_tokens = resolved_options.target_tokens or budget.target_tokens
        measurement: TokenMeasurement | None = None
        if not resolved_options.force and not _skip_trigger_check:
            # user:“压缩的数值只应该使用一种权威值”+(触发也用同一个估算口径，
            # 不再分快慢两路，避免小波动时切换口径)。
            estimator = self._estimate_exact_tokens or self._estimate_tokens
            estimate = (
                estimator(list(messages))
                if estimator is not None
                else estimate_message_tokens(
                    [message.to_dict() for message in messages]
                )
            )
            measurement = TokenMeasurement(
                tokens=calibrated_tokens(estimate),
                exact=True,
                source="estimate",
            )
            if measurement.tokens < budget.trigger_tokens:
                return None

        input_limit_tokens = self._input_limit_tokens
        if input_limit_tokens is None:
            input_limit_tokens = budget.max_input_tokens or budget.context_window
        request = ContextCompactionRequest(
            trigger=trigger or ("manual" if resolved_options.force else "auto"),
            messages=list(messages),
            llm_client=self._llm_client,
            model=self._model,
            timeout=self._timeout,
            limit_tokens=target_tokens,
            input_limit_tokens=input_limit_tokens,
            authoritative_tokens=(
                authoritative_tokens
                if authoritative_tokens > 0
                else (measurement.tokens if measurement is not None else 0)
            ),
            existing_summary=self._existing_summary,
            request_metadata=dict(self._request_metadata),
            on_delta=self._on_delta,
            on_event=self._on_event,
            # user:“去重构吧”+(外部估算回调统一输入原始值，进入压缩预算时只乘一次)。
            estimate_tokens=(
                lambda values: calibrated_tokens(self._estimate_tokens(values))
            ) if self._estimate_tokens is not None else None,
            estimate_exact_tokens=(
                lambda values: calibrated_tokens(self._estimate_exact_tokens(values))
            ) if self._estimate_exact_tokens is not None else None,
            summary_budget=self._summary_budget,
            model_retries=self._model_retries,
            model_timeout_seconds=self._model_timeout_seconds,
            retry_policy=self._retry_policy or RetryPolicy(),
            on_model_retry=self._on_model_retry,
            retained_steps=resolved_options.retained_steps,
            options=resolved_options,
        )
        if self._pipeline is not None:
            return await self._pipeline(request)
        return await compact_context(request)


def _summary_output_allowance(
    *,
    explicit: int | None,
    model_output_tokens: int | None,
    model_window: int,
    limit_tokens: int,
) -> int:
    """Return the output allowance for one summary model call.

    Compaction must not invent a smaller cap than the model can produce.  With
    the old fixed 4096-token default a long-but-valid summary ended with
    ``finish_reason=length``, and a truncated summary is rejected outright — so
    a context that actually needed compacting could never be compacted twice in
    a row on the same session.

    Priority: an explicit policy value, then the main model's own output limit
    (the same number its ordinary requests use), then the legacy heuristic.  The
    model limit is capped to leave at least half the window for the summary
    *input*; without that guard a large output limit would collapse the input
    budget to zero and compaction could not run at all.
    """
    if explicit is not None and explicit > 0:
        return explicit
    if model_output_tokens is not None and model_output_tokens > 0:
        ceiling = max(256, model_window // 2) if model_window > 0 else model_output_tokens
        return max(256, min(model_output_tokens, ceiling))
    return max(
        256,
        min(
            DEFAULT_SUMMARY_OUTPUT_TOKENS,
            limit_tokens // 3 if limit_tokens > 0 else DEFAULT_SUMMARY_OUTPUT_TOKENS,
            max(256, model_window // 8),
        ),
    )


class ContextCompactionController:
    """Coordinate request measurement and model-selection fallback.

    The controller knows how to invoke the context pipeline, but it does not
    know runtime state, persistence, or kernel events.  Callers provide a
    request-level estimator so tool definitions and response-format overhead
    participate in the same trigger decision as message content.
    """

    def __init__(
        self,
        *,
        llm_client: LLMClient | None,
        estimate_request_tokens: Callable[[list[ChatMessage], bool], int],
        on_delta: CompactionDeltaSink | None = None,
        on_event: CompactionEventSink | None = None,
        model_retries: int = 1,
        model_timeout_seconds: float | None = None,
        retry_policy: RetryPolicy | None = None,
        on_model_retry: ModelRetrySink | None = None,
        summary_output_tokens: int | None = None,
        model_output_tokens: int | None = None,
        safety_margin_tokens: int | None = None,
        request_metadata: dict[str, Any] | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._estimate_request_tokens = estimate_request_tokens
        self._on_delta = on_delta
        self._on_event = on_event
        self._model_retries = model_retries
        self._model_timeout_seconds = model_timeout_seconds
        self._retry_policy = retry_policy or RetryPolicy()
        self._on_model_retry = on_model_retry
        self._summary_output_tokens = summary_output_tokens
        self._model_output_tokens = model_output_tokens
        self._safety_margin_tokens = safety_margin_tokens
        self._request_metadata = dict(request_metadata or {})

    def measure(
        self,
        messages: list[ChatMessage],
        *,
        trigger_tokens: int,
    ) -> TokenMeasurement:
        """Measure a full request using the shared safe trigger policy."""
        # user:“去重构吧”+(触发、规划、拟合共用同一种占用单位，不再分别选择快慢估算)。
        return TokenMeasurement(
            tokens=calibrated_tokens(self._estimate_request_tokens(list(messages), False)),
            exact=True, source="estimate",
        )

    async def compact(
        self,
        messages: list[ChatMessage],
        *,
        budget: TokenBudget,
        timeout: float | None,
        current_model: str,
        previous_model: str = "",
        previous_window: int = 0,
        model_switched: bool = False,
        allow_previous_model: bool = True,
        trigger: str = "auto",
        measurement: TokenMeasurement | None = None,
        force: bool = False,
        retained_steps: int | None = None,
    ) -> CompactionExecution:
        """Run bounded compaction, retrying once with the current model.

        ``force`` only bypasses the outer trigger-threshold decision.  The
        selected budget, layout, fitter, summary limits, and retry behavior
        remain exactly the same as an automatic compaction.
        """
        resolved_measurement = measurement or self.measure(
            messages,
            trigger_tokens=budget.trigger_tokens,
        )
        if not force and resolved_measurement.tokens < budget.trigger_tokens:
            return CompactionExecution(
                result=None,
                measurement=resolved_measurement,
            )

        limit_tokens = budget.target_tokens

        async def attempt(
            *,
            model: str,
            model_window: int,
            strategy: str,
            fallback_on_terminal: bool,
        ) -> ContextCompactionResult:
            summary_output_tokens = _summary_output_allowance(
                explicit=self._summary_output_tokens,
                model_output_tokens=self._model_output_tokens,
                model_window=model_window,
                limit_tokens=limit_tokens,
            )
            summary_budget = SummaryTokenBudget.for_context_window(
                context_window=model_window,
                output_tokens=summary_output_tokens,
                # Request-level estimators already account for message framing
                # and the compaction prompt. Keep a bounded provider reserve
                # for larger production windows without starving small tests.
                protocol_tokens=(
                    min(1024, max(0, model_window // 10))
                    if model_window >= 8_192
                    else 0
                ),
                safety_margin_tokens=(
                    self._safety_margin_tokens
                    if self._safety_margin_tokens is not None
                    else (int(model_window * 0.03) if model_window >= 8_192 else 0)
                ),
            )

            async def on_attempt_event(payload: dict[str, Any]) -> None:
                event_payload = dict(payload)
                # Deltas are delivered through on_delta as transient stream
                # parts; do not duplicate them as regular progress events.
                if event_payload.get("status") == "running" and event_payload.get("delta"):
                    return
                if fallback_on_terminal and event_payload.get("status") in {
                    "failed",
                    "not_needed",
                }:
                    event_payload.update(
                        {
                            "status": "running",
                            "phase": "fallback",
                            "label": "原模型压缩未完成 · 正在改用当前模型",
                        }
                    )
                await _emit_event_sink(
                    self._on_event,
                    {
                        "execution_model": model,
                        "strategy": strategy,
                        **event_payload,
                    },
                )

            fast_estimate = lambda current: self._estimate_request_tokens(
                list(current), True
            )
            exact_estimate = lambda current: self._estimate_request_tokens(
                list(current), False
            )
            compactor = ContextCompactor(
                llm_client=self._llm_client,
                model=model,
                timeout=timeout,
                input_limit_tokens=compaction_segment_input_limit(model_window),
                estimate_tokens=fast_estimate,
                estimate_exact_tokens=exact_estimate,
                summary_budget=summary_budget,
                on_delta=self._on_delta,
                on_event=on_attempt_event,
                model_retries=self._model_retries,
                model_timeout_seconds=self._model_timeout_seconds,
                retry_policy=self._retry_policy,
                on_model_retry=self._on_model_retry,
                request_metadata=self._request_metadata,
            )
            attempt_window = max(1, model_window, limit_tokens)
            return await compactor.compact(
                list(messages),
                budget=TokenBudget(
                    context_window=attempt_window,
                    trigger_tokens=max(1, limit_tokens),
                    target_tokens=limit_tokens,
                ),
                options=CompactionOptions(force=False, target_tokens=limit_tokens),
                trigger=trigger,
                retained_steps=retained_steps,
                authoritative_tokens=resolved_measurement.tokens,
                _skip_trigger_check=True,
            )

        used_previous_model = (
            model_switched
            and allow_previous_model
            and previous_window > 0
            and resolved_measurement.tokens <= previous_window
        )
        if used_previous_model:
            result = await attempt(
                model=previous_model,
                model_window=previous_window,
                strategy="previous_model_once",
                fallback_on_terminal=True,
            )
        else:
            result = None

        if result is None or result.status != "compacted":
            result = await attempt(
                model=current_model,
                model_window=budget.context_window,
                strategy=(
                    "segmented_current_model" if model_switched else "current_model"
                ),
                fallback_on_terminal=False,
            )
            execution_model = current_model
            strategy = "segmented_current_model" if model_switched else "current_model"
        else:
            execution_model = previous_model
            strategy = "previous_model_once"
        return CompactionExecution(
            result=result,
            measurement=resolved_measurement,
            execution_model=execution_model,
            strategy=strategy,
        )


async def compact_context(request: ContextCompactionRequest) -> ContextCompactionResult:
    """Compact context and return both replacement messages and display data."""
    options = request.options
    if options.target_tokens is not None and options.target_tokens != request.limit_tokens:
        request = replace(request, limit_tokens=options.target_tokens)
    effective_retained_steps = (
        request.retained_steps
        if request.retained_steps is not None
        else request.options.retained_steps
    )
    effective_retained_steps = (
        resolve_retained_steps(effective_retained_steps)
        if effective_retained_steps is not None
        else load_retained_steps()
    )
    await _emit_compaction_event(
        request,
        {
            "status": "running",
            "phase": "preparing",
            "label": "正在压缩上下文",
            "content": "",
        },
    )
    layout = select_context_compaction_layout(
        request.messages,
        preserve_latest_user=request.preserve_latest_user,
        compact_all=request.options.compact_all,
        limit_tokens=request.limit_tokens,
        retained_steps=(
            request.retained_steps
            if request.retained_steps is not None
            else request.options.retained_steps
        ),
        # Planning decides which preferred Step/user units must yield to the
        # hard target, so use the same exact estimator as the fitter.
        estimate_tokens=lambda messages: _estimate_compaction_tokens(
            request,
            messages,
            exact=True,
        ),
    )
    estimated_before = _estimate_compaction_tokens(
        request,
        request.messages,
        exact=request.estimate_exact_tokens is not None,
    )
    # user:“before_tokens应作为唯一权威实际值”+(调用方给的真实口径优先，
    # 没有时估算兜底；下游所有判断都从这一个数派生)。
    before_tokens = (
        max(0, int(request.authoritative_tokens))
        if request.authoritative_tokens > 0
        else estimated_before
    )
    raw_total = _estimate_compaction_tokens(request, request.messages, exact=True)
    # A manual command may be available in a runtime that has no model client
    # (for example a local command catalog).  If the history already fits the
    # requested target, report a harmless no-op instead of trying to summarize
    # with an unavailable adapter.  Oversized history still proceeds to the
    # normal failed result so callers can surface the missing capability.
    if request.llm_client is None and before_tokens <= request.limit_tokens:
        result = ContextCompactionResult(
            status="not_needed",
            trigger=request.trigger,
            replacement_messages=list(request.messages),
            before_tokens=before_tokens,
            after_tokens=before_tokens,
            limit_tokens=request.limit_tokens,
            display_payload={
                "type": "compaction",
                "trigger": request.trigger,
                "status": "not_needed",
                "reason": "no_content",
                "label": "无需压缩",
                "before_tokens": before_tokens,
                "after_tokens": before_tokens,
                "limit_tokens": request.limit_tokens,
                "compacted_messages": 0,
                "retained_messages": len(request.messages),
                "removed_messages": 0,
                "retained_steps": effective_retained_steps,
            },
        )
        await _emit_compaction_event(request, result.display_payload)
        return result
    if layout is None:
        result = ContextCompactionResult(
            status="not_needed",
            trigger=request.trigger,
            replacement_messages=list(request.messages),
            before_tokens=before_tokens,
            after_tokens=before_tokens,
            limit_tokens=request.limit_tokens,
            display_payload={
                "type": "compaction",
                "trigger": request.trigger,
                "status": "not_needed",
                "reason": "no_content",
                "label": "无需压缩",
                "before_tokens": before_tokens,
                "after_tokens": before_tokens,
                "limit_tokens": request.limit_tokens,
                "compacted_messages": 0,
                "retained_messages": len(request.messages),
                "removed_messages": 0,
                "retained_steps": effective_retained_steps,
            },
        )
        await _emit_compaction_event(request, result.display_payload)
        return result

    # user:“用户消息那个也许可以取消？”+(取消最多 50 条原话的常驻附录；当前请求保留原角色，历史原文由召回工具按需读取)。
    existing_recent = extract_recent_user_messages(request.existing_summary)
    required_tail = [message for message in layout.retained_messages if message.role == "user" and not message.metadata.get("internal")][-1:]
    protected_tokens = _scale_authoritative_tokens(
        before_tokens,
        _estimate_compaction_tokens(
            request,
            [*layout.prefix_messages, *required_tail],
            exact=True,
        ),
        raw_total,
    )
    if protected_tokens > request.limit_tokens:
        result = _failed_compaction_result(
            request,
            before_tokens=before_tokens,
            reason="protected_tail_over_limit",
            message=(
                "Context compaction failed to fit within limit: latest user "
                "message requires "
                f"{protected_tokens} > {request.limit_tokens} tokens"
            ),
        )
        await _emit_compaction_event(request, result.display_payload)
        return result

    # user:“before_tokens应作为唯一权威实际值”+(整段请求的权威总量直接决定
    # 摘要分成几段，不再从本地估算里猜可摘要部分)。
    summarizable_authoritative = before_tokens
    try:
        messages_for_summary = [
            replace(
                message,
                content=strip_recent_user_messages(
                    str(message.content or ""),
                    _message_recent_user_messages(message),
                ),
            )
            if message.metadata.get("key") == "context_compaction_summary"
            else message
            for message in layout.compacted_messages
        ]
        summary, segment_count = await summarize_context_messages(
            messages_for_summary,
            llm_client=request.llm_client,
            model=request.model,
            timeout=request.timeout,
            limit_tokens=request.limit_tokens,
            input_limit_tokens=request.input_limit_tokens,
            summary_budget=request.summary_budget,
            existing_summary=strip_recent_user_messages(
                request.existing_summary,
                existing_recent if existing_recent else None,
            ),
            authoritative_tokens=summarizable_authoritative or None,
            prefix_messages=layout.prefix_messages,
            on_delta=request.on_delta,
            on_event=lambda payload: _emit_compaction_event(request, payload),
            model_retries=request.model_retries,
            model_timeout_seconds=request.model_timeout_seconds,
            retry_policy=request.retry_policy,
            on_model_retry=request.on_model_retry,
            request_metadata=request.request_metadata,
        )
    except asyncio.CancelledError:
        result = _failed_compaction_result(
            request,
            before_tokens=before_tokens,
            reason="cancelled",
            message="上下文压缩已取消",
        )
        await _emit_compaction_event(request, result.display_payload)
        raise
    except ContextCompactionError as exc:
        result = _failed_compaction_result(
            request,
            before_tokens=before_tokens,
            message=str(exc),
        )
        await _emit_compaction_event(request, result.display_payload)
        return result
    summary_message = ChatMessage(
        role="system",
        content=summary,
        metadata={
            "key": "context_compaction_summary",
            "kind": "history",
            "trigger": request.trigger,
            "compacted_messages": len(layout.compacted_messages),
        },
    )
    fitter = CompactionFitter(
        lambda messages: _estimate_compaction_tokens(request, messages, exact=True)
    )
    try:
        fit_result = fitter.fit(
            CompactionFitInput(
                system_prefix=list(layout.prefix_messages),
                summary_message=summary_message,
                recent_messages=list(layout.retained_messages),
                # The fitter works in raw local units; project the one
                # authoritative target into that unit so the final ratio still
                # lands under limit_tokens.
                target_tokens=(
                    ceil(request.limit_tokens * raw_total / before_tokens)
                    if 0 < before_tokens < raw_total
                    else request.limit_tokens
                ),
            )
        )
    except CompactionBudgetExceeded as exc:
        estimated_tokens = max(0, int(exc.estimated_tokens))
        result = _failed_compaction_result(
            request,
            before_tokens=before_tokens,
            reason="over_limit",
            message=(
                "Context compaction failed to fit within limit: "
                f"{estimated_tokens} > {request.limit_tokens} tokens"
            ),
        )
        await _emit_compaction_event(request, result.display_payload)
        return result

    replacement_messages = fit_result.messages
    prefix_count = len(layout.prefix_messages)
    summary_message = replacement_messages[prefix_count]
    fitted_recent_user_messages = list(fit_result.recent_user_messages)
    summary_message.metadata[RECENT_USER_MESSAGES_METADATA_KEY] = (
        fitted_recent_user_messages
    )
    retained_messages = replacement_messages[prefix_count + 1 :]
    # The authoritative ratio says whether compaction gained anything; the
    # smaller estimate keeps the reported number in a sane unit for the UI.
    after_ratio_tokens = _scale_authoritative_tokens(
        before_tokens,
        _estimate_compaction_tokens(request, replacement_messages, exact=True),
        raw_total,
    )
    after_tokens = min(after_ratio_tokens, fit_result.estimated_tokens)
    if after_tokens >= before_tokens:
        result = ContextCompactionResult(
            status="not_needed",
            trigger=request.trigger,
            replacement_messages=list(request.messages),
            before_tokens=before_tokens,
            after_tokens=before_tokens,
            limit_tokens=request.limit_tokens,
            segment_count=segment_count,
            display_payload={
                "type": "compaction",
                "trigger": request.trigger,
                "status": "not_needed",
                "reason": "no_gain",
                "label": "无需压缩",
                "before_tokens": before_tokens,
                "after_tokens": before_tokens,
                "limit_tokens": request.limit_tokens,
                "segments": segment_count,
                "compacted_messages": 0,
                "retained_messages": len(request.messages),
                "removed_messages": 0,
                "retained_steps": effective_retained_steps,
            },
        )
        await _emit_compaction_event(request, result.display_payload)
        return result
    if after_tokens > request.limit_tokens:
        result = _failed_compaction_result(
            request,
            before_tokens=before_tokens,
            reason="over_limit",
            message=(
                "Context compaction failed to fit within limit: "
                f"{after_tokens} > {request.limit_tokens} tokens"
            ),
        )
        await _emit_compaction_event(request, result.display_payload)
        return result

    summary_content = str(summary_message.content or "")
    display_payload = {
        "type": "compaction",
        "trigger": request.trigger,
        "status": "compacted",
        "label": "上下文已压缩",
        "content": summary_content[:20_000],
        "before_tokens": before_tokens,
        "after_tokens": after_tokens,
        "limit_tokens": request.limit_tokens,
        "segments": segment_count,
        "compacted_messages": len(layout.compacted_messages),
        "retained_messages": len(retained_messages),
        "removed_messages": len(layout.compacted_messages)
        + len(layout.retained_messages)
        - len(retained_messages),
        "retained_steps": effective_retained_steps,
        "recent_user_messages": len(fitted_recent_user_messages),
    }
    result = ContextCompactionResult(
        status="compacted",
        trigger=request.trigger,
        summary=summary_content,
        summary_message=summary_message,
        prefix_messages=layout.prefix_messages,
        compacted_messages=layout.compacted_messages,
        retained_messages=retained_messages,
        replacement_messages=replacement_messages,
        before_tokens=before_tokens,
        after_tokens=after_tokens,
        limit_tokens=request.limit_tokens,
        segment_count=segment_count,
        recent_user_messages=fitted_recent_user_messages,
        display_payload=display_payload,
    )
    await _emit_compaction_event(request, display_payload)
    return result


def _failed_compaction_result(
    request: ContextCompactionRequest,
    *,
    before_tokens: int,
    message: str,
    reason: str = "",
) -> ContextCompactionResult:
    display_payload = {
        "type": "compaction",
        "trigger": request.trigger,
        "status": "failed",
        "phase": "failed",
        "label": "压缩未完成",
        "message": message,
        "before_tokens": before_tokens,
        "after_tokens": before_tokens,
        "limit_tokens": request.limit_tokens,
        "compacted_messages": 0,
        "retained_messages": len(request.messages),
        "removed_messages": 0,
        "retained_steps": (
            resolve_retained_steps(
                request.retained_steps
                if request.retained_steps is not None
                else request.options.retained_steps
            )
            if request.retained_steps is not None or request.options.retained_steps is not None
            else load_retained_steps()
        ),
    }
    if reason:
        display_payload["reason"] = reason
    return ContextCompactionResult(
        status="failed",
        trigger=request.trigger,
        replacement_messages=list(request.messages),
        before_tokens=before_tokens,
        after_tokens=before_tokens,
        limit_tokens=request.limit_tokens,
        display_payload=display_payload,
    )


def _scale_authoritative_tokens(
    authoritative: int, raw_part: int, raw_total: int
) -> int:
    """Project a local raw estimate into the authoritative token unit."""
    if authoritative <= 0 or raw_total <= 0:
        return max(0, raw_part)
    return ceil(authoritative * max(0, raw_part) / raw_total)


def _estimate_compaction_tokens(
    request: ContextCompactionRequest,
    messages: list[ChatMessage],
    *,
    exact: bool = False,
) -> int:
    estimator = request.estimate_exact_tokens if exact else request.estimate_tokens
    if estimator is not None:
        return max(0, int(estimator(messages)))
    return calibrated_tokens(estimate_message_tokens([message.to_dict() for message in messages]))


async def _emit_compaction_event(
    request: ContextCompactionRequest, payload: dict[str, Any]
) -> None:
    await _emit_event_sink(
        request.on_event,
        {
            "type": "compaction",
            "trigger": request.trigger,
            "limit_tokens": request.limit_tokens,
            **payload,
        },
    )


def _message_recent_user_messages(message: ChatMessage) -> list[str] | None:
    """Return trusted suffix metadata from a summary message, if present."""
    raw = message.metadata.get(RECENT_USER_MESSAGES_METADATA_KEY)
    if isinstance(raw, list) and all(isinstance(item, str) for item in raw):
        return list(raw)
    return None


__all__ = [
    "CompactionExecution",
    "ContextCompactionController",
    "ContextCompactor",
    "compact_context",
]
