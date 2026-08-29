"""Shared context compaction helpers for Core runtimes."""

from __future__ import annotations

import asyncio
import json
import inspect
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import Any

from lamtools_core.context_compaction_budget import (
    SummaryTokenBudget,
    TokenBudget,
    measure_for_compaction_trigger,
)
from lamtools_core.llm import ChatMessage, LLMClient, LLMRequest
from lamtools_core.llm.policy import RetryPolicy
from lamtools_core.llm.retry import ModelRetryExhausted, ModelRetrySink, complete_with_retry, stream_with_retry
from lamtools_core.tokens import estimate_message_tokens, estimate_text_tokens

_logger = logging.getLogger(__name__)

COMPACTION_PREFIX = "[Compacted Context]"

COMPACTION_PROMPT = (
    "Compact for continuation.\n\n"
    f"Output format: the first line must be exactly {COMPACTION_PREFIX}.\n\n"
    "Required sections:\n"
    "1. Current Objective And Done Criteria\n"
    "2. Active User Instructions\n"
    "3. External Action Authorization\n"
    "4. Confirmed Facts And Decisions\n"
    "5. Current Execution State\n"
    "6. Verification Evidence\n"
    "7. Open Issues, Risks, And Hypotheses\n"
    "8. Rejected Or Superseded Directions\n"
    "9. Next Actions\n\n"
    "Rules:\n"
    "- Never invent state, permission, completion.\n"
    "- Preserve user requirements, corrections, and done criteria. The latest explicit user instruction wins; "
    "quote prohibitions and permissions.\n"
    "- Separate outcomes from external authorization; facts/evidence/done/not-done from plans/hypotheses. Put rejections in section 8.\n"
    "- Keep artifacts, results, errors, and approvals; order actions.\n"
    "- Use the user's language; keep headings.\n"
    "\n"
    "Output requirements:\n"
    "- Output ONLY the numbered sections above, in order, with their exact headings.\n"
    "- No preamble, no commentary, no markdown code fences, and no closing remarks.\n"
    "- Every section must be present; write \"None\" when a section has nothing to record."
)


_COMPACTION_SUMMARY_FIELDS = (
    "goals",
    "active_user_instructions",
    "external_action_authorization",
    "confirmed_facts_and_decisions",
    "current_execution_state",
    "verification_evidence",
    "open_issues_risks_and_hypotheses",
    "rejected_or_superseded_directions",
    "next_actions",
)
_COMPACTION_SUMMARY_TITLES = (
    "1. Current Objective And Done Criteria",
    "2. Active User Instructions",
    "3. External Action Authorization",
    "4. Confirmed Facts And Decisions",
    "5. Current Execution State",
    "6. Verification Evidence",
    "7. Open Issues, Risks, And Hypotheses",
    "8. Rejected Or Superseded Directions",
    "9. Next Actions",
)
_LEGACY_SUMMARY_TITLES = (
    "1. Current Goal",
    "2. User History, Instructions, And Decisions",
    "3. Completed Work",
    "4. Key Decisions And Constraints",
    "5. Files, APIs, Commands, And Results",
    "6. Open Issues Or Risks",
    "7. Next Best Actions",
    "8. Rejected Or Superseded Directions",
    "9. Next Actions",
)


@dataclass(slots=True)
class CompactionSummary:
    """Canonical internal representation of the nine-part summary contract."""

    goals: str = ""
    active_user_instructions: str = ""
    external_action_authorization: str = ""
    confirmed_facts_and_decisions: str = ""
    current_execution_state: str = ""
    verification_evidence: str = ""
    open_issues_risks_and_hypotheses: str = ""
    rejected_or_superseded_directions: str = ""
    next_actions: str = ""

    def render(self) -> str:
        """Render the canonical external text format, including its prefix."""
        sections = []
        for title, field_name in zip(_COMPACTION_SUMMARY_TITLES, _COMPACTION_SUMMARY_FIELDS):
            content = str(getattr(self, field_name) or "").strip() or "- None."
            sections.append(f"{title}\n{content}")
        return with_compaction_prefix("\n\n".join(sections))


def parse_compaction_summary(text: str) -> CompactionSummary | None:
    """Parse only the exact ordered nine-section summary contract."""
    raw = str(text or "").strip()
    if not raw:
        return None
    lines = raw.splitlines()
    if lines and lines[0].strip() == COMPACTION_PREFIX:
        lines = lines[1:]

    headings = [
        (index, line.strip())
        for index, line in enumerate(lines)
        if _numbered_section_number(line) is not None
    ]
    if [title for _, title in headings] != list(_COMPACTION_SUMMARY_TITLES):
        return None

    values: dict[str, str] = {}
    for position, (start, _) in enumerate(headings):
        end = headings[position + 1][0] if position + 1 < len(headings) else len(lines)
        values[_COMPACTION_SUMMARY_FIELDS[position]] = "\n".join(
            lines[start + 1 : end]
        ).strip()
    return CompactionSummary(**values)


def _normalize_legacy_compaction_summary(text: str) -> str:
    """Canonicalize the pre-contract fixture format during migration."""
    lines = str(text or "").strip().splitlines()
    headings = [
        line.strip()
        for line in lines
        if _numbered_section_number(line) is not None
    ]
    if headings != list(_LEGACY_SUMMARY_TITLES):
        return text
    replacements = dict(zip(_LEGACY_SUMMARY_TITLES, _COMPACTION_SUMMARY_TITLES))
    return "\n".join(replacements.get(line.strip(), line) for line in lines)


class ContextCompactionError(RuntimeError):
    """Raised when model-backed context compaction cannot produce a summary."""


class CompactionBudgetExceeded(ContextCompactionError):
    """Raised when required context cannot fit the compaction target."""

    def __init__(
        self,
        message: str,
        *,
        estimated_tokens: int = 0,
        target_tokens: int = 0,
    ) -> None:
        super().__init__(message)
        self.estimated_tokens = estimated_tokens
        self.target_tokens = target_tokens


CompactionDeltaSink = Callable[[str], Awaitable[None] | None]
CompactionEventSink = Callable[[dict[str, Any]], Awaitable[None] | None]
CompactionTokenEstimator = Callable[[list[ChatMessage]], int]
MAX_COMPACTION_SEGMENT_INPUT_TOKENS = 64_000
MAX_FIT_ATTEMPTS = 8


@dataclass(frozen=True, slots=True)
class CompactionOptions:
    """Per-invocation controls shared by automatic and manual compaction."""

    force: bool = False
    target_tokens: int | None = None

    def __post_init__(self) -> None:
        if self.target_tokens is not None:
            if isinstance(self.target_tokens, bool) or self.target_tokens <= 0:
                raise ValueError("target_tokens must be positive when provided")


@dataclass(frozen=True)
class ContextCompactionRequest:
    """Input for the single Core context compaction interface."""

    trigger: str
    messages: list[ChatMessage]
    llm_client: LLMClient | None = None
    model: str = ""
    timeout: float | None = None
    limit_tokens: int = 4096
    input_limit_tokens: int = 0
    existing_summary: str = ""
    on_delta: CompactionDeltaSink | None = None
    on_event: CompactionEventSink | None = None
    preserve_latest_user: bool = True
    estimate_tokens: CompactionTokenEstimator | None = None
    estimate_exact_tokens: CompactionTokenEstimator | None = None
    summary_budget: SummaryTokenBudget | None = None
    model_retries: int = 1
    model_timeout_seconds: float | None = None
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    on_model_retry: ModelRetrySink | None = None
    options: CompactionOptions = field(default_factory=CompactionOptions)


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


@dataclass(frozen=True)
class ContextCompactionResult:
    """Output from context compaction, including replacement and display data."""

    status: str
    trigger: str
    summary: str = ""
    summary_message: ChatMessage | None = None
    prefix_messages: list[ChatMessage] = field(default_factory=list)
    compacted_messages: list[ChatMessage] = field(default_factory=list)
    retained_messages: list[ChatMessage] = field(default_factory=list)
    replacement_messages: list[ChatMessage] = field(default_factory=list)
    before_tokens: int = 0
    after_tokens: int = 0
    limit_tokens: int = 0
    segment_count: int = 0
    display_payload: dict[str, Any] = field(default_factory=dict)

    @property
    def compacted_count(self) -> int:
        return len(self.compacted_messages)

    @property
    def retained_count(self) -> int:
        return len(self.retained_messages)


@dataclass(slots=True)
class CompactionFitInput:
    """Inputs to the bounded replacement-message fitter."""

    system_prefix: list[ChatMessage]
    summary_message: ChatMessage
    recent_messages: list[ChatMessage]
    target_tokens: int


@dataclass(slots=True)
class CompactionFitResult:
    """A replacement that the exact estimator proved fits its target."""

    messages: list[ChatMessage]
    estimated_tokens: int
    attempts: int
    strategy: str


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


def compaction_segment_input_limit(context_window_tokens: int) -> int:
    """Return the per-request input ceiling used by every compaction entrypoint.

    Segmentation is only meaningful when the model's context window itself
    cannot hold the full compaction input (e.g. switching from a 1M model to
    a 200k model).  Within the same window the model can always accept its own
    window worth of input, so we return the window itself rather than an
    arbitrary cap.  ``MAX_COMPACTION_SEGMENT_INPUT_TOKENS`` is only a fallback
    when the window is unknown.
    """
    window = max(0, int(context_window_tokens or 0))
    if window <= 0:
        return MAX_COMPACTION_SEGMENT_INPUT_TOKENS
    return window


@dataclass(frozen=True)
class _ContextCompactionLayout:
    prefix_messages: list[ChatMessage]
    compacted_messages: list[ChatMessage]
    retained_messages: list[ChatMessage]


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


def select_context_compaction_layout(
    messages: list[ChatMessage],
    *,
    preserve_latest_user: bool = True,
    limit_tokens: int = 0,
    estimate_tokens: CompactionTokenEstimator | None = None,
) -> _ContextCompactionLayout | None:
    """Return stable prefix, compacted messages, and raw retained messages."""
    prefix_end = 0
    for index, message in enumerate(messages):
        if message.role != "system":
            break
        if message.metadata.get("key") == "context_compaction_summary":
            break
        prefix_end = index + 1

    body = list(messages[prefix_end:])
    if not body:
        return None

    estimator = estimate_tokens or (
        lambda values: estimate_message_tokens([message.to_dict() for message in values])
    )
    prefix_messages = list(messages[:prefix_end])
    fixed_tokens = estimator(prefix_messages)
    retained_budget = max(0, limit_tokens - fixed_tokens - _summary_output_limit(limit_tokens))
    groups = _semantic_message_groups(body)
    retained_ids: set[int] = set()

    def retained_values(extra: list[ChatMessage] | None = None) -> list[ChatMessage]:
        selected = set(retained_ids)
        selected.update(id(message) for message in (extra or []))
        return [message for message in body if id(message) in selected]

    def retained_token_count(extra: list[ChatMessage] | None = None) -> int:
        return max(0, estimator([*prefix_messages, *retained_values(extra)]) - fixed_tokens)

    latest_group_index = len(groups) - 1
    if preserve_latest_user:
        latest_user = next((message for message in reversed(body) if message.role == "user"), None)
        if latest_user is not None:
            latest_group_index = next(
                index for index, group in enumerate(groups) if any(message is latest_user for message in group)
            )
            latest_group = groups[latest_group_index]
            required = (
                latest_group
                if retained_token_count(latest_group) <= retained_budget
                else [latest_user]
            )
            retained_ids.update(id(message) for message in required)

    start_index = latest_group_index if preserve_latest_user else len(groups)
    for group in reversed(groups[:start_index]):
        if len(retained_ids) + len(group) >= len(body):
            continue
        if retained_token_count(group) > retained_budget:
            break
        retained_ids.update(id(message) for message in group)

    retained_messages = retained_values()
    compacted_messages = [message for message in body if id(message) not in retained_ids]
    if not compacted_messages:
        return None
    return _ContextCompactionLayout(
        prefix_messages=prefix_messages,
        compacted_messages=compacted_messages,
        retained_messages=retained_messages,
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


async def summarize_context_messages(
    messages: list[ChatMessage],
    *,
    llm_client: LLMClient | None = None,
    model: str = "",
    timeout: float | None = None,
    limit_tokens: int = 4096,
    input_limit_tokens: int = 0,
    summary_budget: SummaryTokenBudget | None = None,
    existing_summary: str = "",
    on_delta: CompactionDeltaSink | None = None,
    on_event: CompactionEventSink | None = None,
    model_retries: int = 1,
    model_timeout_seconds: float | None = None,
    retry_policy: RetryPolicy | None = None,
    on_model_retry: ModelRetrySink | None = None,
) -> tuple[str, int]:
    """Return a structured summary and the number of source segments used."""
    summary_input_limit = (
        summary_budget.max_input_tokens
        if summary_budget is not None
        else input_limit_tokens
    )
    summary_output_tokens = _summary_output_limit(limit_tokens)
    if summary_budget is not None:
        summary_output_tokens = min(summary_output_tokens, summary_budget.output_tokens)
    chunks = _split_compaction_messages(
        messages,
        input_limit_tokens=summary_input_limit,
        existing_summary=existing_summary,
    )
    segment_count = len(chunks)
    summaries: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        await _emit_event_sink(
            on_event,
            {
                "status": "running",
                "phase": "segment",
                "segment": index,
                "segments": segment_count,
                "label": f"正在压缩上下文 · 第 {index}/{segment_count} 段",
                "content": "",
            },
        )
        summary = await _summarize_compaction_chunk(
            chunk,
            llm_client=llm_client,
            model=model,
            timeout=timeout,
            output_tokens=summary_output_tokens,
            input_limit_tokens=summary_input_limit,
            existing_summary=existing_summary if index == 1 else "",
            on_delta=on_delta,
            on_event=on_event,
            phase="segment",
            segment=index,
            segments=segment_count,
            model_retries=model_retries,
            model_timeout_seconds=model_timeout_seconds,
            retry_policy=retry_policy,
            on_model_retry=on_model_retry,
        )
        summaries.append(summary)

    merge_round = 0
    while len(summaries) > 1:
        merge_round += 1
        if merge_round > 12:
            raise ContextCompactionError("Context compaction failed: segmented summaries did not converge")
        summary_messages = [
            ChatMessage(
                role="assistant",
                content=value,
                metadata={"key": "compaction_segment_summary"},
            )
            for value in summaries
        ]
        merge_chunks = _split_compaction_messages(
            summary_messages,
            input_limit_tokens=summary_input_limit,
            existing_summary="",
        )
        if len(merge_chunks) >= len(summaries):
            merge_chunks = _pair_compaction_messages(summary_messages, summary_input_limit)
        await _emit_event_sink(
            on_event,
            {
                "status": "running",
                "phase": "merge",
                "segments": segment_count,
                "merge_round": merge_round,
                "label": f"正在整理压缩结果 · {segment_count} 段",
                "content": "",
            },
        )
        merged: list[str] = []
        for index, chunk in enumerate(merge_chunks, start=1):
            merged.append(
                await _summarize_compaction_chunk(
                    chunk,
                    llm_client=llm_client,
                    model=model,
                    timeout=timeout,
                    output_tokens=summary_output_tokens,
                    input_limit_tokens=summary_input_limit,
                    existing_summary="",
                    on_delta=on_delta,
                    on_event=on_event,
                    phase="merge",
                    segment=index,
                    segments=len(merge_chunks),
                    model_retries=model_retries,
                    model_timeout_seconds=model_timeout_seconds,
                    retry_policy=retry_policy,
                    on_model_retry=on_model_retry,
                )
            )
        summaries = merged

    summary_text = summaries[0] if summaries else fallback_structured_compaction_summary(
        messages,
        existing_summary=existing_summary,
    )
    parsed_summary = parse_compaction_summary(summary_text)
    if parsed_summary is None:
        parsed_summary = parse_compaction_summary(
            fallback_structured_compaction_summary(
                messages,
                existing_summary=existing_summary,
            )
        )
    if parsed_summary is None:
        raise ContextCompactionError("Context compaction failed: invalid structured summary")
    return parsed_summary.render(), max(1, segment_count)


def _summary_output_limit(limit_tokens: int) -> int:
    return max(256, min(4096, limit_tokens // 3 if limit_tokens > 0 else 4096))


def _semantic_message_groups(messages: list[ChatMessage]) -> list[list[ChatMessage]]:
    groups: list[list[ChatMessage]] = []
    current: list[ChatMessage] = []
    for message in messages:
        starts_group = message.role == "user" or message.metadata.get("key") == "compaction_segment_summary"
        if starts_group and current:
            groups.append(current)
            current = []
        current.append(message)
    if current:
        groups.append(current)
    return groups


def _compaction_request_tokens(messages: list[ChatMessage], existing_summary: str = "") -> int:
    transcript = format_messages_for_compaction(messages, existing_summary=existing_summary)
    return estimate_message_tokens(
        [
            ChatMessage(role="system", content=COMPACTION_PROMPT).to_dict(),
            ChatMessage(role="user", content=transcript).to_dict(),
        ]
    )


def _split_compaction_messages(
    messages: list[ChatMessage],
    *,
    input_limit_tokens: int,
    existing_summary: str,
) -> list[list[ChatMessage]]:
    if not messages:
        return [[]]
    if input_limit_tokens <= 0 or _compaction_request_tokens(messages, existing_summary) <= input_limit_tokens:
        return [list(messages)]

    chunks: list[list[ChatMessage]] = []
    current: list[ChatMessage] = []
    semantic_groups: list[list[ChatMessage]] = []
    for group in _semantic_message_groups(messages):
        group_existing = existing_summary if not semantic_groups else ""
        if _compaction_request_tokens(group, group_existing) > input_limit_tokens:
            semantic_groups.extend(_split_oversized_semantic_group(group))
        else:
            semantic_groups.append(group)

    for group in semantic_groups:
        candidate = [*current, *group]
        candidate_existing = existing_summary if not chunks else ""
        if current and _compaction_request_tokens(candidate, candidate_existing) > input_limit_tokens:
            chunks.append(current)
            current = list(group)
        else:
            current = candidate
        current_existing = existing_summary if not chunks else ""
        if _compaction_request_tokens(current, current_existing) > input_limit_tokens:
            raise ContextCompactionError(
                "Context compaction failed: one complete conversation turn exceeds the model input limit"
            )
    if current:
        chunks.append(current)
    return chunks


def _split_oversized_semantic_group(messages: list[ChatMessage]) -> list[list[ChatMessage]]:
    """Split one oversized turn while keeping assistant/tool-result units intact."""
    groups: list[list[ChatMessage]] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        if message.role != "assistant":
            groups.append([message])
            index += 1
            continue
        unit = [message]
        index += 1
        while index < len(messages) and messages[index].role == "tool":
            unit.append(messages[index])
            index += 1
        groups.append(unit)
    return groups


def _pair_compaction_messages(
    messages: list[ChatMessage], input_limit_tokens: int
) -> list[list[ChatMessage]]:
    pairs: list[list[ChatMessage]] = []
    for index in range(0, len(messages), 2):
        pair = messages[index : index + 2]
        if input_limit_tokens > 0 and _compaction_request_tokens(pair) > input_limit_tokens:
            source_pair = pair
            budget = max(16, (input_limit_tokens - _compaction_request_tokens([])) // max(1, len(pair)))
            while True:
                pair = [
                    ChatMessage(
                        role=message.role,
                        content=compress_structured_compaction_summary(str(message.content or ""), budget),
                    )
                    for message in source_pair
                ]
                if _compaction_request_tokens(pair) <= input_limit_tokens or budget <= 16:
                    break
                budget = max(16, budget - max(8, budget // 8))
        if input_limit_tokens > 0 and _compaction_request_tokens(pair) > input_limit_tokens:
            raise ContextCompactionError(
                "Context compaction failed: intermediate summaries exceed the model input limit"
            )
        pairs.append(pair)
    return pairs


async def _summarize_compaction_chunk(
    messages: list[ChatMessage],
    *,
    llm_client: LLMClient | None,
    model: str,
    timeout: float | None,
    output_tokens: int,
    input_limit_tokens: int,
    existing_summary: str,
    on_delta: CompactionDeltaSink | None,
    on_event: CompactionEventSink | None,
    phase: str,
    segment: int,
    segments: int,
    model_retries: int,
    model_timeout_seconds: float | None,
    retry_policy: RetryPolicy | None,
    on_model_retry: ModelRetrySink | None,
) -> str:
    transcript = format_messages_for_compaction(messages, existing_summary=existing_summary)
    content = ""
    emitted_delta = False
    if llm_client is not None:
        summary_request = LLMRequest(
            messages=[
                ChatMessage(role="system", content=COMPACTION_PROMPT),
                ChatMessage(role="user", content=transcript),
            ],
            model=model,
            temperature=0,
            max_tokens=output_tokens,
            timeout=timeout,
        )
        request_tokens = estimate_message_tokens([message.to_dict() for message in summary_request.messages])
        if input_limit_tokens > 0 and request_tokens > input_limit_tokens:
            raise ContextCompactionError(
                f"Context compaction request exceeds model input limit: {request_tokens} > {input_limit_tokens} tokens"
            )

        async def emit_delta(delta: str) -> None:
            nonlocal content
            content += delta
            if on_delta is not None:
                await _emit_compaction_delta(on_delta, delta)
            await _emit_event_sink(
                on_event,
                {
                    "status": "running",
                    "phase": phase,
                    "segment": segment,
                    "segments": segments,
                    "label": (
                        f"正在压缩上下文 · 第 {segment}/{segments} 段"
                        if phase == "segment"
                        else f"正在整理压缩结果 · {segments} 段"
                    ),
                    "delta": delta,
                    "content": content[:20_000],
                },
            )

        try:
            streamed, emitted_delta = await _stream_compaction_content(
                llm_client,
                summary_request,
                on_delta=emit_delta,
                model_retries=model_retries,
                model_timeout_seconds=model_timeout_seconds,
                retry_policy=retry_policy,
                on_model_retry=on_model_retry,
            )
            if streamed:
                content = streamed
        except NotImplementedError:
            content = ""
        except AttributeError:
            raise
        except ModelRetryExhausted as exc:
            detail = exc.last_error if exc.attempts <= 1 else exc
            raise ContextCompactionError(f"Context compaction failed: {detail}") from exc
        except ContextCompactionError:
            raise
        except Exception as exc:
            raise ContextCompactionError(f"Context compaction failed: {exc}") from exc
        if not content:
            try:
                response = await complete_with_retry(
                    llm_client,
                    summary_request,
                    max_attempts=model_retries,
                    timeout_seconds=model_timeout_seconds,
                    retry_policy=retry_policy,
                    on_retry=on_model_retry,
                )
                content = (response.content or "").strip()
            except ModelRetryExhausted as exc:
                detail = exc.last_error if exc.attempts <= 1 else exc
                raise ContextCompactionError(f"Context compaction failed: {detail}") from exc
            except Exception as exc:
                raise ContextCompactionError(f"Context compaction failed: {exc}") from exc
        if not content:
            raise ContextCompactionError("Context compaction failed: model returned an empty summary")
    parsed_summary = parse_compaction_summary(content)
    if parsed_summary is None:
        parsed_summary = parse_compaction_summary(
            _normalize_legacy_compaction_summary(content)
        )
    if parsed_summary is None:
        parsed_summary = parse_compaction_summary(
            fallback_structured_compaction_summary(
                messages,
                existing_summary=existing_summary,
            )
        )
    if parsed_summary is None:
        raise ContextCompactionError("Context compaction failed: invalid structured summary")
    summary = parsed_summary.render()
    if estimate_text_tokens(summary) > output_tokens:
        summary = compress_structured_compaction_summary(summary, output_tokens)
    if not emitted_delta:
        if on_delta is not None:
            await _emit_compaction_delta(on_delta, summary)
        await _emit_event_sink(
            on_event,
            {
                "status": "running",
                "phase": phase,
                "segment": segment,
                "segments": segments,
                "label": (
                    f"正在压缩上下文 · 第 {segment}/{segments} 段"
                    if phase == "segment"
                    else f"正在整理压缩结果 · {segments} 段"
                ),
                "delta": summary,
                "content": summary[:20_000],
            },
        )
    return summary


async def _emit_event_sink(
    sink: CompactionEventSink | None, payload: dict[str, Any]
) -> None:
    if sink is None:
        return
    result = sink(payload)
    if inspect.isawaitable(result):
        await result


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


async def _emit_compaction_delta(on_delta: CompactionDeltaSink, text: str) -> None:
    result = on_delta(text)
    if inspect.isawaitable(result):
        await result


async def _stream_compaction_content(
    llm_client: LLMClient,
    request: LLMRequest,
    *,
    on_delta: CompactionDeltaSink | None,
    model_retries: int,
    model_timeout_seconds: float | None,
    retry_policy: RetryPolicy | None,
    on_model_retry: ModelRetrySink | None,
) -> tuple[str, bool]:
    parts: list[str] = []
    emitted_delta = False
    async for event in stream_with_retry(
        llm_client,
        request,
        max_attempts=model_retries,
        timeout_seconds=model_timeout_seconds,
        retry_policy=retry_policy,
        on_retry=on_model_retry,
    ):
        if event.kind == "content_delta" and event.content:
            parts.append(event.content)
            if on_delta is not None:
                await _emit_compaction_delta(on_delta, event.content)
                emitted_delta = True
    return "".join(parts).strip(), emitted_delta


def with_compaction_prefix(content: str) -> str:
    text = str(content or "").strip()
    if text.startswith(COMPACTION_PREFIX):
        return text
    return f"{COMPACTION_PREFIX}\n{text}".strip()


def _has_structured_sections(content: str) -> bool:
    """Return whether the content contains all nine numbered compaction sections."""
    return parse_compaction_summary(content) is not None


def _inherit_prior_protected_context(summary: str, prior_summaries: list[str]) -> str:
    protected_sections = (
        (
            2,
            "2. Active User Instructions",
            ("2. Active User Instructions", "2. User History, Instructions, And Decisions"),
            _denies_user_instructions,
        ),
        (
            3,
            "3. External Action Authorization",
            ("3. External Action Authorization",),
            _denies_external_action_authorization,
        ),
    )
    result = summary
    for number, title, accepted_titles, denies_content in protected_sections:
        inherited: list[str] = []
        for prior_summary in prior_summaries:
            if _numbered_summary_section_title(prior_summary, number) not in accepted_titles:
                continue
            for line in _numbered_summary_section(prior_summary, number):
                normalized = " ".join(line.split())
                if normalized and normalized not in inherited:
                    inherited.append(normalized)
        if not inherited:
            continue

        current = []
        if _numbered_summary_section_title(result, number) in accepted_titles:
            current = [
                line
                for line in _numbered_summary_section(result, number)
                if not denies_content(line)
            ]
        merged = [*inherited, *(line for line in current if " ".join(line.split()) not in inherited)]
        lines = result.splitlines()
        start, end = _numbered_summary_section_bounds(lines, number)
        section = [title, *merged]
        if start is None:
            result = "\n".join([*lines, "", *section]).strip()
        else:
            result = "\n".join([*lines[:start], *section, "", *lines[end:]]).strip()
    return result


def _numbered_summary_section(text: str, number: int) -> list[str]:
    lines = str(text or "").splitlines()
    start, end = _numbered_summary_section_bounds(lines, number)
    if start is None:
        return []
    return [line.strip() for line in lines[start + 1 : end] if line.strip()]


def _numbered_summary_section_title(text: str, number: int) -> str:
    lines = str(text or "").splitlines()
    start, _ = _numbered_summary_section_bounds(lines, number)
    return lines[start].strip() if start is not None else ""


def _numbered_summary_section_bounds(lines: list[str], number: int) -> tuple[int | None, int]:
    prefix = f"{number}. "
    start = next((index for index, line in enumerate(lines) if line.strip().startswith(prefix)), None)
    if start is None:
        return None, len(lines)
    end = next(
        (
            index
            for index in range(start + 1, len(lines))
            if lines[index].strip()
            and lines[index].strip()[0].isdigit()
            and ". " in lines[index].strip()[:4]
        ),
        len(lines),
    )
    while end > start + 1 and not lines[end - 1].strip():
        end -= 1
    return start, end


def _denies_user_instructions(line: str) -> bool:
    normalized = " ".join(line.lower().split())
    return any(
        marker in normalized
        for marker in (
            "no explicit user instruction",
            "no prior user instruction",
            "no user instruction",
            "无明确用户指令",
            "没有明确用户指令",
            "无用户指令",
        )
    )


def _denies_external_action_authorization(line: str) -> bool:
    normalized = " ".join(line.lower().split())
    return any(
        marker in normalized
        for marker in (
            "none confirmed",
            "no external action authorization",
            "no action authorization",
            "no authorization confirmed",
            "无外部操作授权",
            "未确认外部操作授权",
            "未获得外部操作授权",
        )
    )


def format_messages_for_compaction(
    messages: list[ChatMessage],
    *,
    existing_summary: str = "",
) -> str:
    lines: list[str] = []
    if existing_summary.strip():
        lines.extend(["## Existing Compacted Summary", existing_summary.strip(), ""])
    for index, message in enumerate(messages, start=1):
        content = message.content
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        lines.append(f"## Message {index}: {message.role}")
        if message.name:
            lines.append(f"name: {message.name}")
        if message.tool_call_id:
            lines.append(f"tool_call_id: {message.tool_call_id}")
        if message.tool_calls:
            lines.append("tool_calls:")
            for tool_call in message.tool_calls:
                lines.append(f"- {tool_call.name}: {tool_call.arguments}")
        lines.append(content)
        lines.append("")
    return "\n".join(lines).strip()


def fallback_structured_compaction_summary(
    messages: list[ChatMessage],
    *,
    existing_summary: str = "",
) -> str:
    snippets: list[str] = []
    user_snippets: list[str] = []
    if existing_summary.strip():
        snippets.append(f"- existing summary: {existing_summary.strip()[:800]}")
    for message in messages:
        content = message.content
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        text = " ".join(content.split())
        if not text:
            continue
        snippets.append(f"- {message.role}: {text[:500]}")
        if message.role == "user":
            user_snippets.append(f"- {text[:500]}")
    body = "\n".join(snippets) if snippets else "- No compactable details captured."
    user_body = "\n".join(user_snippets) if user_snippets else "- No prior user instructions in compacted span."
    return CompactionSummary(
        goals=(
            "- Continue the active user task using the latest uncompressed user message.\n"
            "- Completion criteria were not independently reconstructed by the local fallback."
        ),
        active_user_instructions=user_body,
        external_action_authorization=(
            "- Preserve explicit approval and prohibition language from the active user instructions.\n"
            "- Do not infer permission for commits, pushes, pull requests, deployments, messages, purchases, or destructive actions."
        ),
        confirmed_facts_and_decisions=(
            "- Only details present in the compacted messages are confirmed; do not promote guesses to facts."
        ),
        current_execution_state=body,
        verification_evidence=(
            "- Preserve exact paths, identifiers, commands, errors, and test results from the execution-state snippets above."
        ),
        open_issues_risks_and_hypotheses=(
            "- This summary was generated by local fallback; inferred causes remain unverified."
        ),
        rejected_or_superseded_directions=(
            "- Retain only rejected or superseded directions explicitly present in the compacted messages."
        ),
        next_actions="- Continue from the latest user request and verify with tests where applicable.",
    ).render()


def compress_structured_compaction_summary(text: str, max_tokens: int) -> str:
    if max_tokens <= 0:
        return ""

    raw_lines = [line.rstrip() for line in text.splitlines()]
    if raw_lines and raw_lines[0].strip() == COMPACTION_PREFIX:
        raw_lines = raw_lines[1:]

    sections: list[tuple[str, list[str]]] = []
    current_title = ""
    current_lines: list[str] = []
    for line in raw_lines:
        stripped = line.strip()
        if stripped and len(stripped) > 3 and stripped[0].isdigit() and ". " in stripped[:4]:
            if current_title:
                sections.append((current_title, current_lines))
            current_title = stripped
            current_lines = []
            continue
        if current_title:
            current_lines.append(line)
    if current_title:
        sections.append((current_title, current_lines))

    if not sections:
        return truncate_text_to_tokens(text, max_tokens)

    compacted_lines = [COMPACTION_PREFIX]
    for title, lines in sections:
        compacted_lines.extend(["", title])
        kept = 0
        omitted = False
        is_protected_section = title.startswith(("2. ", "3. "))
        for line in lines:
            stripped = " ".join(line.strip().split())
            if not stripped:
                continue
            if len(stripped) > 260:
                if is_protected_section:
                    stripped = stripped[:260]
                else:
                    omitted = True
                    continue
            compacted_lines.append(stripped)
            kept += 1
            if kept >= 3 and not is_protected_section:
                break
        if omitted:
            compacted_lines.append("- Details omitted because this section exceeded the compaction budget.")
        if kept == 0 and not omitted:
            compacted_lines.append("- No durable details retained.")

    candidate = "\n".join(compacted_lines).strip()
    if estimate_text_tokens(candidate) <= max_tokens:
        return candidate

    lines = candidate.splitlines()
    while lines and estimate_text_tokens("\n".join(lines)) > max_tokens:
        def can_remove(index: int, *, headings: bool = False) -> bool:
            stripped = lines[index].strip()
            if stripped == COMPACTION_PREFIX or _line_is_in_numbered_sections(lines, index, {2, 3}):
                return False
            return headings or _numbered_section_number(stripped) is None

        remove_index = next(
            (
                index
                for index in range(len(lines) - 1, -1, -1)
                if lines[index].startswith("- ")
                and can_remove(index)
            ),
            next(
                (
                    index
                    for index in range(len(lines) - 1, -1, -1)
                    if can_remove(index)
                ),
                next(
                    (
                        index
                        for index in range(len(lines) - 1, -1, -1)
                        if lines[index].startswith("- ")
                        and can_remove(index, headings=True)
                    ),
                    next(
                        (
                            index
                            for index in range(len(lines) - 1, -1, -1)
                            if can_remove(index, headings=True)
                        ),
                        -1,
                    ),
                ),
            ),
        )
        if remove_index < 0:
            break
        lines.pop(remove_index)
    return "\n".join(lines).strip()


def _numbered_section_number(line: str) -> int | None:
    stripped = line.strip()
    if not stripped or not stripped[0].isdigit() or ". " not in stripped[:4]:
        return None
    return int(stripped.split(".", 1)[0])


def _line_is_in_numbered_sections(lines: list[str], index: int, numbers: set[int]) -> bool:
    for line in reversed(lines[:index]):
        number = _numbered_section_number(line)
        if number is not None:
            return number in numbers
    return False


def truncate_text_to_tokens(text: str, max_tokens: int) -> str:
    if max_tokens <= 0:
        return ""
    if estimate_text_tokens(text) <= max_tokens:
        return text

    marker = "\n...[compaction summary truncated to fit budget]"
    marker_tokens = estimate_text_tokens(marker)
    if marker_tokens >= max_tokens:
        marker = ""
        marker_tokens = 0

    available_tokens = max_tokens - marker_tokens
    low = 0
    high = len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if estimate_text_tokens(text[:middle]) <= available_tokens:
            low = middle
        else:
            high = middle - 1

    return f"{text[:low]}{marker}"


__all__ = [
    "COMPACTION_PREFIX",
    "COMPACTION_PROMPT",
    "CompactionBudgetExceeded",
    "CompactionFitInput",
    "CompactionFitResult",
    "CompactionFitter",
    "CompactionOptions",
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
