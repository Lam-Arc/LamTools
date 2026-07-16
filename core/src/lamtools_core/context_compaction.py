"""Shared context compaction helpers for Core runtimes."""

from __future__ import annotations

import asyncio
import json
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from lamtools_core.llm import ChatMessage, LLMClient, LLMRequest
from lamtools_core.llm.policy import RetryPolicy
from lamtools_core.llm.retry import ModelRetryExhausted, ModelRetrySink, complete_with_retry, stream_with_retry
from lamtools_core.tokens import estimate_message_tokens, estimate_text_tokens

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
    "- Use the user's language; keep headings."
)


class ContextCompactionError(RuntimeError):
    """Raised when model-backed context compaction cannot produce a summary."""


CompactionDeltaSink = Callable[[str], Awaitable[None] | None]
CompactionEventSink = Callable[[dict[str, Any]], Awaitable[None] | None]
CompactionTokenEstimator = Callable[[list[ChatMessage]], int]
MAX_COMPACTION_SEGMENT_INPUT_TOKENS = 64_000


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
    model_retries: int = 1
    model_timeout_seconds: float | None = None
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    on_model_retry: ModelRetrySink | None = None


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


def compaction_segment_input_limit(context_window_tokens: int) -> int:
    """Return the per-request input ceiling used by every compaction entrypoint."""
    window = max(0, int(context_window_tokens or 0))
    if window <= 0:
        return MAX_COMPACTION_SEGMENT_INPUT_TOKENS
    return max(1, min(MAX_COMPACTION_SEGMENT_INPUT_TOKENS, window // 2))


@dataclass(frozen=True)
class _ContextCompactionLayout:
    prefix_messages: list[ChatMessage]
    compacted_messages: list[ChatMessage]
    retained_messages: list[ChatMessage]


async def compact_context(request: ContextCompactionRequest) -> ContextCompactionResult:
    """Compact context and return both replacement messages and display data."""
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
    before_tokens = _estimate_compaction_tokens(request, request.messages)
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
    replacement_messages = [
        *layout.prefix_messages,
        summary_message,
        *layout.retained_messages,
    ]
    after_tokens = _fit_replacement_to_limit(
        request,
        replacement_messages,
        summary_message,
    )
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
        "retained_messages": len(layout.retained_messages),
        "removed_messages": len(layout.compacted_messages),
    }
    result = ContextCompactionResult(
        status="compacted",
        trigger=request.trigger,
        summary=summary_content,
        summary_message=summary_message,
        prefix_messages=layout.prefix_messages,
        compacted_messages=layout.compacted_messages,
        retained_messages=layout.retained_messages,
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
) -> int:
    if request.estimate_tokens is not None:
        return request.estimate_tokens(messages)
    return estimate_message_tokens([message.to_dict() for message in messages])


def _fit_replacement_to_limit(
    request: ContextCompactionRequest,
    replacement_messages: list[ChatMessage],
    summary_message: ChatMessage,
) -> int:
    after_tokens = _estimate_compaction_tokens(request, replacement_messages)
    while request.limit_tokens > 0 and after_tokens > request.limit_tokens:
        summary_tokens = estimate_text_tokens(str(summary_message.content or ""))
        if summary_tokens <= 0:
            break
        next_budget = max(0, summary_tokens - (after_tokens - request.limit_tokens) - 64)
        next_content = compress_structured_compaction_summary(
            str(summary_message.content or ""),
            next_budget,
        )
        if next_content == summary_message.content:
            next_content = truncate_text_to_tokens(str(summary_message.content or ""), next_budget)
        summary_message.content = next_content
        next_tokens = _estimate_compaction_tokens(request, replacement_messages)
        if next_tokens >= after_tokens:
            summary_message.content = truncate_text_to_tokens(
                str(summary_message.content or ""),
                max(0, next_budget - 128),
            )
            next_tokens = _estimate_compaction_tokens(request, replacement_messages)
        after_tokens = next_tokens
    return after_tokens


async def summarize_context_messages(
    messages: list[ChatMessage],
    *,
    llm_client: LLMClient | None = None,
    model: str = "",
    timeout: float | None = None,
    limit_tokens: int = 4096,
    input_limit_tokens: int = 0,
    existing_summary: str = "",
    on_delta: CompactionDeltaSink | None = None,
    on_event: CompactionEventSink | None = None,
    model_retries: int = 1,
    model_timeout_seconds: float | None = None,
    retry_policy: RetryPolicy | None = None,
    on_model_retry: ModelRetrySink | None = None,
) -> tuple[str, int]:
    """Return a structured summary and the number of source segments used."""
    chunks = _split_compaction_messages(
        messages,
        input_limit_tokens=input_limit_tokens,
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
            output_tokens=_summary_output_limit(limit_tokens),
            input_limit_tokens=input_limit_tokens,
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
            input_limit_tokens=input_limit_tokens,
            existing_summary="",
        )
        if len(merge_chunks) >= len(summaries):
            merge_chunks = _pair_compaction_messages(summary_messages, input_limit_tokens)
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
                    output_tokens=_summary_output_limit(limit_tokens),
                    input_limit_tokens=input_limit_tokens,
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

    summary = summaries[0] if summaries else with_compaction_prefix(
        fallback_structured_compaction_summary(messages, existing_summary=existing_summary)
    )
    return summary, max(1, segment_count)


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
        except (AttributeError, NotImplementedError):
            content = ""
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
    if not content:
        content = fallback_structured_compaction_summary(messages, existing_summary=existing_summary)
    summary = with_compaction_prefix(content)
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
    return (
        "1. Current Objective And Done Criteria\n"
        "- Continue the active user task using the latest uncompressed user message.\n"
        "- Completion criteria were not independently reconstructed by the local fallback.\n\n"
        "2. Active User Instructions\n"
        f"{user_body}\n\n"
        "3. External Action Authorization\n"
        "- Preserve explicit approval and prohibition language from the active user instructions.\n"
        "- Do not infer permission for commits, pushes, pull requests, deployments, messages, purchases, or destructive actions.\n\n"
        "4. Confirmed Facts And Decisions\n"
        "- Only details present in the compacted messages are confirmed; do not promote guesses to facts.\n\n"
        "5. Current Execution State\n"
        f"{body}\n\n"
        "6. Verification Evidence\n"
        "- Preserve exact paths, identifiers, commands, errors, and test results from the execution-state snippets above.\n\n"
        "7. Open Issues, Risks, And Hypotheses\n"
        "- This summary was generated by local fallback; inferred causes remain unverified.\n\n"
        "8. Rejected Or Superseded Directions\n"
        "- Retain only rejected or superseded directions explicitly present in the compacted messages.\n\n"
        "9. Next Actions\n"
        "- Continue from the latest user request and verify with tests where applicable."
    )


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
        removable = next(
            (
                index
                for index in range(len(lines) - 1, -1, -1)
                if lines[index].startswith("- ")
                and not _line_is_in_numbered_sections(lines, index, {2, 3})
            ),
            next(
                (
                    index
                    for index in range(len(lines) - 1, -1, -1)
                    if _numbered_section_number(lines[index]) not in {None, 2, 3}
                ),
                next(
                    (index for index in range(len(lines) - 1, -1, -1) if lines[index].startswith("- ")),
                    len(lines) - 1,
                ),
            ),
        )
        lines.pop(removable)
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
    if estimate_text_tokens(text) <= max_tokens:
        return text
    if max_tokens <= 0:
        return ""
    return text[: max_tokens * 3] + "\n...[compaction summary truncated to fit budget]"


__all__ = [
    "COMPACTION_PREFIX",
    "COMPACTION_PROMPT",
    "ContextCompactionError",
    "ContextCompactionRequest",
    "ContextCompactionResult",
    "compact_context",
    "compress_structured_compaction_summary",
    "compaction_segment_input_limit",
    "fallback_structured_compaction_summary",
    "format_messages_for_compaction",
    "select_context_compaction_layout",
    "summarize_context_messages",
    "truncate_text_to_tokens",
    "with_compaction_prefix",
]
