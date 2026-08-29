"""Shared context compaction helpers for Core runtimes."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any

from lamtools_core.context_compaction_budget import (
    SummaryTokenBudget,
    TokenBudget,
    measure_for_compaction_trigger,
)
from lamtools_core.llm import ChatMessage, LLMClient
from lamtools_core.llm.policy import RetryPolicy
from lamtools_core.llm.retry import ModelRetrySink
from lamtools_core.tokens import estimate_message_tokens, estimate_text_tokens

from .models import (
    COMPACTION_PREFIX,
    COMPACTION_PROMPT,
    CompactionBudgetExceeded,
    CompactionDeltaSink,
    CompactionEventSink,
    CompactionFitInput,
    CompactionFitResult,
    CompactionOptions,
    CompactionPlan,
    CompactionSummary,
    CompactionTokenEstimator,
    ContextCompactionError,
    ContextCompactionRequest,
    ContextCompactionResult,
)
from .formatting import (
    format_messages_for_compaction,
    inherit_prior_protected_context as _inherit_prior_protected_context,
    parse_compaction_summary,
    truncate_text_to_tokens,
    with_compaction_prefix,
)
from .fallback import (
    compress_structured_compaction_summary,
    fallback_structured_compaction_summary,
)
from .planner import (
    CompactionPlanner,
    _semantic_message_groups,
    compaction_segment_input_limit,
    select_context_compaction_layout,
)
from .summarizer import (
    emit_event_sink as _emit_event_sink,
    summarize_context_messages,
)

_logger = logging.getLogger(__name__)


MAX_FIT_ATTEMPTS = 8


class ContextCompactor:
    """Facade shared by automatic and manual context-compaction entrypoints.

    The existing ``compact_context`` function remains the compatibility
    implementation of the planner/summarizer/fitter pipeline.  This facade
    resolves the concrete budget and invocation options before entering that
    pipeline, so callers do not maintain separate manual and automatic
    request construction paths.
    """

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
        pipeline: Callable[..., Awaitable[ContextCompactionResult]] | None = None,
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
        self._pipeline = pipeline

    async def compact(
        self,
        messages: list[ChatMessage],
        *,
        budget: TokenBudget,
        options: CompactionOptions | None = None,
        trigger: str | None = None,
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
        target_tokens = resolved_options.target_tokens or budget.target_tokens
        if not resolved_options.force and not _skip_trigger_check:
            measurement = measure_for_compaction_trigger(
                messages,
                trigger_tokens=budget.trigger_tokens,
                fast_estimate=self._estimate_tokens,
                exact_estimate=self._estimate_exact_tokens,
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
            existing_summary=self._existing_summary,
            on_delta=self._on_delta,
            on_event=self._on_event,
            estimate_tokens=self._estimate_tokens,
            estimate_exact_tokens=self._estimate_exact_tokens,
            summary_budget=self._summary_budget,
            model_retries=self._model_retries,
            model_timeout_seconds=self._model_timeout_seconds,
            retry_policy=self._retry_policy or RetryPolicy(),
            on_model_retry=self._on_model_retry,
            options=resolved_options,
        )
        if self._pipeline is not None:
            return await self._pipeline(request)
        return await compact_context(request)


def _minimal_compaction_summary() -> str:
    return CompactionSummary().render()


class CompactionFitter:
    """Fit a summary and recent tail with a bounded deterministic strategy."""

    def __init__(self, estimate_tokens: CompactionTokenEstimator) -> None:
        self._estimate_tokens = estimate_tokens

    def fit(self, fit_input: CompactionFitInput) -> CompactionFitResult:
        if fit_input.target_tokens <= 0:
            raise CompactionBudgetExceeded(
                "required context target must be positive",
                estimated_tokens=self._estimate_tokens(
                    [*fit_input.system_prefix, *fit_input.recent_messages]
                ),
                target_tokens=fit_input.target_tokens,
            )

        prefix = list(fit_input.system_prefix)
        recent = list(fit_input.recent_messages)
        summary_content = str(fit_input.summary_message.content or "")
        required_recent = self._required_recent_messages(recent)
        required_tokens = self._estimate_tokens([*prefix, *required_recent])
        if required_tokens > fit_input.target_tokens:
            raise CompactionBudgetExceeded(
                "required latest turn exceeds target token budget",
                estimated_tokens=required_tokens,
                target_tokens=fit_input.target_tokens,
            )

        def candidate(content: str, retained: list[ChatMessage]) -> list[ChatMessage]:
            summary = replace(fit_input.summary_message, content=content)
            return [*prefix, summary, *retained]

        current_messages = candidate(summary_content, recent)
        current_tokens = self._estimate_tokens(current_messages)
        attempts = 1
        if current_tokens <= fit_input.target_tokens:
            return CompactionFitResult(
                messages=current_messages,
                estimated_tokens=current_tokens,
                attempts=attempts,
                strategy="original",
            )

        strategies = (
            ("compress_summary_once", self._compress_summary),
            ("compress_summary_twice", self._compress_summary),
            ("drop_oldest_recent_turn", self._drop_oldest_recent_turn),
            ("drop_oldest_recent_turn_again", self._drop_oldest_recent_turn),
            ("truncate_summary", self._truncate_summary),
            ("minimal_summary", self._minimal_summary),
            ("latest_user_only", self._latest_user_only),
        )
        for strategy, shrink in strategies:
            if attempts >= MAX_FIT_ATTEMPTS:
                break
            next_content, next_recent = shrink(
                summary_content,
                recent,
                prefix=prefix,
                target_tokens=fit_input.target_tokens,
            )
            next_messages = candidate(next_content, next_recent)
            next_tokens = self._estimate_tokens(next_messages)
            attempts += 1
            if next_tokens >= current_tokens:
                _logger.warning(
                    "compaction fitter strategy did not reduce exact token count "
                    "strategy=%s attempt=%d current=%d next=%d",
                    strategy,
                    attempts,
                    current_tokens,
                    next_tokens,
                )
            else:
                summary_content = next_content
                recent = next_recent
                current_messages = next_messages
                current_tokens = next_tokens
            if current_tokens <= fit_input.target_tokens:
                return CompactionFitResult(
                    messages=current_messages,
                    estimated_tokens=current_tokens,
                    attempts=attempts,
                    strategy=strategy,
                )

        raise CompactionBudgetExceeded(
            "required context remains over the compaction target after bounded fitting",
            estimated_tokens=current_tokens,
            target_tokens=fit_input.target_tokens,
        )

    @staticmethod
    def _required_recent_messages(recent: list[ChatMessage]) -> list[ChatMessage]:
        groups = _semantic_message_groups(recent)
        latest_user = next(
            (message for message in reversed(recent) if message.role == "user"),
            None,
        )
        if latest_user is not None:
            for group in groups:
                if any(message is latest_user for message in group):
                    return list(group)
        return list(groups[-1] if groups else [])

    def _compress_summary(
        self,
        content: str,
        recent: list[ChatMessage],
        *,
        prefix: list[ChatMessage],
        target_tokens: int,
    ) -> tuple[str, list[ChatMessage]]:
        base_tokens = self._estimate_tokens(
            [*prefix, ChatMessage(role="system", content=""), *recent]
        )
        current_text_tokens = estimate_text_tokens(content)
        available_tokens = target_tokens - base_tokens
        if available_tokens <= 0 or current_text_tokens <= available_tokens:
            return content, list(recent)
        next_budget = max(1, current_text_tokens - max(1, current_text_tokens // 3))
        next_budget = min(next_budget, available_tokens)
        next_content = compress_structured_compaction_summary(content, next_budget)
        if next_content == content or estimate_text_tokens(next_content) >= current_text_tokens:
            next_content = truncate_text_to_tokens(content, next_budget)
        return next_content, list(recent)

    def _drop_oldest_recent_turn(
        self,
        content: str,
        recent: list[ChatMessage],
        *,
        prefix: list[ChatMessage],
        target_tokens: int,
    ) -> tuple[str, list[ChatMessage]]:
        _ = content, prefix, target_tokens
        groups = _semantic_message_groups(recent)
        required = self._required_recent_messages(recent)
        for index, group in enumerate(groups):
            if any(message is required_message for message in required for required_message in group):
                continue
            return content, [message for group in groups[index + 1 :] for message in group]
        return content, list(recent)

    def _truncate_summary(
        self,
        content: str,
        recent: list[ChatMessage],
        *,
        prefix: list[ChatMessage],
        target_tokens: int,
    ) -> tuple[str, list[ChatMessage]]:
        _ = self
        high = estimate_text_tokens(content)
        low = 0
        best = ""
        while low <= high:
            middle = (low + high) // 2
            candidate_content = compress_structured_compaction_summary(content, middle)
            if estimate_text_tokens(candidate_content) > middle:
                candidate_content = truncate_text_to_tokens(candidate_content, middle)
            candidate = [
                *prefix,
                ChatMessage(role="system", content=candidate_content),
                *recent,
            ]
            if self._estimate_tokens(candidate) <= target_tokens:
                best = candidate_content
                low = middle + 1
            else:
                high = middle - 1
        return best, list(recent)

    @staticmethod
    def _minimal_summary(
        content: str,
        recent: list[ChatMessage],
        *,
        prefix: list[ChatMessage],
        target_tokens: int,
    ) -> tuple[str, list[ChatMessage]]:
        _ = content, prefix, target_tokens
        return _minimal_compaction_summary(), list(recent)

    def _latest_user_only(
        self,
        content: str,
        recent: list[ChatMessage],
        *,
        prefix: list[ChatMessage],
        target_tokens: int,
    ) -> tuple[str, list[ChatMessage]]:
        _ = content, prefix, target_tokens
        return _minimal_compaction_summary(), self._required_recent_messages(recent)


async def compact_context(request: ContextCompactionRequest) -> ContextCompactionResult:
    """Compact context and return both replacement messages and display data."""
    options = request.options
    if options.target_tokens is not None and options.target_tokens != request.limit_tokens:
        request = replace(request, limit_tokens=options.target_tokens)
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
        limit_tokens=request.limit_tokens,
        estimate_tokens=lambda messages: _estimate_compaction_tokens(request, messages),
    )
    before_tokens = _estimate_compaction_tokens(
        request,
        request.messages,
        exact=request.estimate_exact_tokens is not None,
    )
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
            },
        )
        await _emit_compaction_event(request, result.display_payload)
        return result

    try:
        summary, segment_count = await summarize_context_messages(
            layout.compacted_messages,
            llm_client=request.llm_client,
            model=request.model,
            timeout=request.timeout,
            limit_tokens=request.limit_tokens,
            input_limit_tokens=request.input_limit_tokens,
            summary_budget=request.summary_budget,
            existing_summary=request.existing_summary,
            on_delta=request.on_delta,
            on_event=lambda payload: _emit_compaction_event(request, payload),
            model_retries=request.model_retries,
            model_timeout_seconds=request.model_timeout_seconds,
            retry_policy=request.retry_policy,
            on_model_retry=request.on_model_retry,
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
    summary = _inherit_prior_protected_context(
        summary,
        [request.existing_summary, *(
            str(message.content or "")
            for message in layout.compacted_messages
            if message.metadata.get("key") == "context_compaction_summary"
        )],
    )
    parsed_summary = parse_compaction_summary(summary)
    if parsed_summary is None:
        parsed_summary = parse_compaction_summary(
            fallback_structured_compaction_summary(
                layout.compacted_messages,
                existing_summary=request.existing_summary,
            )
        )
    if parsed_summary is None:
        raise ContextCompactionError("Context compaction failed: invalid structured summary")
    summary = parsed_summary.render()
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
                target_tokens=request.limit_tokens,
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
    retained_messages = replacement_messages[prefix_count + 1 :]
    after_tokens = fit_result.estimated_tokens
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


def _estimate_compaction_tokens(
    request: ContextCompactionRequest,
    messages: list[ChatMessage],
    *,
    exact: bool = False,
) -> int:
    estimator = request.estimate_exact_tokens if exact else request.estimate_tokens
    if estimator is not None:
        return max(0, int(estimator(messages)))
    return estimate_message_tokens([message.to_dict() for message in messages])


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


__all__ = [
    "COMPACTION_PREFIX",
    "COMPACTION_PROMPT",
    "CompactionBudgetExceeded",
    "CompactionFitInput",
    "CompactionFitResult",
    "CompactionFitter",
    "CompactionOptions",
    "CompactionPlan",
    "CompactionPlanner",
    "CompactionSummary",
    "ContextCompactionError",
    "ContextCompactor",
    "ContextCompactionRequest",
    "ContextCompactionResult",
    "compact_context",
    "compress_structured_compaction_summary",
    "compaction_segment_input_limit",
    "fallback_structured_compaction_summary",
    "format_messages_for_compaction",
    "parse_compaction_summary",
    "select_context_compaction_layout",
    "summarize_context_messages",
    "truncate_text_to_tokens",
    "with_compaction_prefix",
]
