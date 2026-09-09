"""LLM-backed context summarization and streaming support."""

from __future__ import annotations

import inspect
from typing import Any

from lamtools_core.context_compaction_budget import SummaryTokenBudget
from lamtools_core.llm import ChatMessage, LLMClient, LLMRequest
from lamtools_core.llm.policy import RetryPolicy
from lamtools_core.llm.retry import (
    ModelRetryExhausted,
    ModelRetrySink,
    complete_with_retry,
    stream_with_retry,
)
from lamtools_core.tokens import estimate_message_tokens, estimate_text_tokens

from .formatting import format_messages_for_compaction, truncate_text_to_tokens
from .models import (
    COMPACTION_PROMPT,
    CompactionDeltaSink,
    CompactionEventSink,
    ContextCompactionError,
)
from .planner import (
    _pair_compaction_messages,
    _split_compaction_messages,
    _summary_output_limit,
)


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
    """Return the model's summary text and the number of source segments used."""
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
        await emit_event_sink(
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
        await emit_event_sink(
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

    summary_text = summaries[0] if summaries else ""
    if not summary_text:
        raise ContextCompactionError("Context compaction failed: model returned an empty summary")
    return summary_text, max(1, segment_count)


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
                await emit_compaction_delta(on_delta, delta)
            await emit_event_sink(
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
            streamed, emitted_delta = await stream_compaction_content(
                llm_client,
                summary_request,
                on_delta=emit_delta,
                model_retries=model_retries,
                model_timeout_seconds=model_timeout_seconds,
                retry_policy=retry_policy,
                on_model_retry=on_model_retry,
            )
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
            # Whitespace-only streams are not summaries. Do not leave their
            # transient deltas marked as the completed result when falling
            # back to the non-streaming completion path.
            emitted_delta = False
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
    summary = content
    if estimate_text_tokens(summary) > output_tokens:
        summary = truncate_text_to_tokens(summary, output_tokens)
    if not emitted_delta:
        if on_delta is not None:
            await emit_compaction_delta(on_delta, summary)
        await emit_event_sink(
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


async def emit_event_sink(
    sink: CompactionEventSink | None,
    payload: dict[str, Any],
) -> None:
    if sink is None:
        return
    result = sink(payload)
    if inspect.isawaitable(result):
        await result


async def emit_compaction_delta(on_delta: CompactionDeltaSink, text: str) -> None:
    result = on_delta(text)
    if inspect.isawaitable(result):
        await result


async def stream_compaction_content(
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
                await emit_compaction_delta(on_delta, event.content)
                emitted_delta = True
    return "".join(parts).strip(), emitted_delta


__all__ = [
    "emit_event_sink",
    "summarize_context_messages",
]
