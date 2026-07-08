"""Shared context compaction helpers for Core runtimes."""

from __future__ import annotations

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
    "Summarize this agent session context for continuation. Preserve only high-value "
    "state needed to continue the task. Be concise, factual, and structured.\n\n"
    f"Output format: the first line must be exactly {COMPACTION_PREFIX}.\n\n"
    "Required sections:\n"
    "1. Current Goal\n"
    "2. User History, Instructions, And Decisions\n"
    "3. Completed Work\n"
    "4. Key Decisions And Constraints\n"
    "5. Files, APIs, Commands, And Results\n"
    "6. Open Issues Or Risks\n"
    "7. Next Best Actions\n\n"
    "Rules: user messages are high-value context. Preserve every explicit user instruction, "
    "correction, business decision, acceptance criterion, permission choice, and scope change. "
    "Keep exact wording when it is short or decision-bearing. Preserve exact file paths, "
    "identifiers, commands, failing errors, approval/permission state, and test results. "
    "Drop redundant chatter and long raw outputs."
)


class ContextCompactionError(RuntimeError):
    """Raised when model-backed context compaction cannot produce a summary."""


CompactionDeltaSink = Callable[[str], Awaitable[None] | None]
CompactionTokenEstimator = Callable[[list[ChatMessage]], int]


@dataclass(frozen=True)
class ContextCompactionRequest:
    """Input for the single Core context compaction interface."""

    trigger: str
    messages: list[ChatMessage]
    llm_client: LLMClient | None = None
    model: str = ""
    timeout: float | None = None
    target_tokens: int = 4096
    existing_summary: str = ""
    on_delta: CompactionDeltaSink | None = None
    retain_tail_count: int = 0
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
    target_tokens: int = 0
    display_payload: dict[str, Any] = field(default_factory=dict)

    @property
    def compacted_count(self) -> int:
        return len(self.compacted_messages)

    @property
    def retained_count(self) -> int:
        return len(self.retained_messages)


@dataclass(frozen=True)
class _ContextCompactionLayout:
    prefix_messages: list[ChatMessage]
    compacted_messages: list[ChatMessage]
    retained_messages: list[ChatMessage]


async def compact_context(request: ContextCompactionRequest) -> ContextCompactionResult:
    """Compact context and return both replacement messages and display data."""
    layout = select_context_compaction_layout(
        request.messages,
        retain_tail_count=request.retain_tail_count,
        preserve_latest_user=request.preserve_latest_user,
    )
    before_tokens = _estimate_compaction_tokens(request, request.messages)
    if layout is None:
        return ContextCompactionResult(
            status="skipped",
            trigger=request.trigger,
            replacement_messages=list(request.messages),
            before_tokens=before_tokens,
            after_tokens=before_tokens,
            target_tokens=request.target_tokens,
            display_payload={
                "type": "compaction",
                "trigger": request.trigger,
                "status": "skipped",
                "label": "暂无可压缩上下文",
                "before_tokens": before_tokens,
                "after_tokens": before_tokens,
                "target_tokens": request.target_tokens,
                "compacted_messages": 0,
                "retained_messages": len(request.messages),
                "removed_messages": 0,
            },
        )

    summary = await summarize_context_messages(
        layout.compacted_messages,
        llm_client=request.llm_client,
        model=request.model,
        timeout=request.timeout,
        target_tokens=request.target_tokens,
        existing_summary=request.existing_summary,
        on_delta=request.on_delta,
        model_retries=request.model_retries,
        model_timeout_seconds=request.model_timeout_seconds,
        retry_policy=request.retry_policy,
        on_model_retry=request.on_model_retry,
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
    after_tokens = _fit_replacement_to_target(
        request,
        replacement_messages,
        summary_message,
    )
    if after_tokens > request.target_tokens:
        raise ContextCompactionError(
            f"Context compaction failed to fit within target budget: {after_tokens} > {request.target_tokens} tokens"
        )

    summary_content = str(summary_message.content or "")
    display_payload = {
        "type": "compaction",
        "trigger": request.trigger,
        "status": "completed",
        "label": "上下文已压缩",
        "content": summary_content[:20_000],
        "before_tokens": before_tokens,
        "after_tokens": after_tokens,
        "target_tokens": request.target_tokens,
        "compacted_messages": len(layout.compacted_messages),
        "retained_messages": len(layout.retained_messages),
        "removed_messages": len(layout.compacted_messages),
    }
    return ContextCompactionResult(
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
        target_tokens=request.target_tokens,
        display_payload=display_payload,
    )


def select_context_compaction_layout(
    messages: list[ChatMessage],
    *,
    retain_tail_count: int = 0,
    preserve_latest_user: bool = True,
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
        if retain_tail_count > 0:
            return _ContextCompactionLayout(
                prefix_messages=list(messages[:prefix_end]),
                compacted_messages=[],
                retained_messages=[],
            )
        return None

    retained_body_indexes: set[int] = set()
    if retain_tail_count > 0:
        retained_count = min(retain_tail_count, max(0, len(body) - 1))
        start = len(body) - retained_count
        retained_body_indexes.update(range(start, len(body)))
    elif preserve_latest_user:
        for index in range(len(body) - 1, -1, -1):
            if body[index].role == "user":
                retained_body_indexes.add(index)
                break

    compacted_messages = [
        message
        for index, message in enumerate(body)
        if index not in retained_body_indexes
    ]
    if not compacted_messages:
        return None
    retained_messages = [
        message
        for index, message in enumerate(body)
        if index in retained_body_indexes
    ]
    return _ContextCompactionLayout(
        prefix_messages=list(messages[:prefix_end]),
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


def _fit_replacement_to_target(
    request: ContextCompactionRequest,
    replacement_messages: list[ChatMessage],
    summary_message: ChatMessage,
) -> int:
    after_tokens = _estimate_compaction_tokens(request, replacement_messages)
    while request.target_tokens > 0 and after_tokens > request.target_tokens:
        summary_tokens = estimate_text_tokens(str(summary_message.content or ""))
        if summary_tokens <= 0:
            break
        next_budget = max(0, summary_tokens - (after_tokens - request.target_tokens) - 64)
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
    target_tokens: int = 4096,
    existing_summary: str = "",
    on_delta: CompactionDeltaSink | None = None,
    model_retries: int = 1,
    model_timeout_seconds: float | None = None,
    retry_policy: RetryPolicy | None = None,
    on_model_retry: ModelRetrySink | None = None,
) -> str:
    """Return a structured summary for replacing compacted context."""
    transcript = format_messages_for_compaction(messages, existing_summary=existing_summary)
    summary_budget = max(512, min(4096, target_tokens // 3 if target_tokens > 0 else 4096))
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
            max_tokens=summary_budget,
            timeout=timeout,
        )
        try:
            content, emitted_delta = await _stream_compaction_content(
                llm_client,
                summary_request,
                on_delta=on_delta,
                model_retries=model_retries,
                model_timeout_seconds=model_timeout_seconds,
                retry_policy=retry_policy,
                on_model_retry=on_model_retry,
            )
        except (AttributeError, NotImplementedError):
            content = ""
        except ModelRetryExhausted as exc:
            if exc.attempts <= 1:
                raise ContextCompactionError(f"Context compaction failed: {exc.last_error}") from exc
            raise ContextCompactionError(f"Context compaction failed: {exc}") from exc
        except Exception as exc:
            raise ContextCompactionError(f"Context compaction failed: {exc}") from exc
        try:
            if not content:
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
            if exc.attempts <= 1:
                raise ContextCompactionError(f"Context compaction failed: {exc.last_error}") from exc
            raise ContextCompactionError(f"Context compaction failed: {exc}") from exc
        except Exception as exc:
            raise ContextCompactionError(f"Context compaction failed: {exc}") from exc
        if not content:
            raise ContextCompactionError("Context compaction failed: model returned an empty summary")
    if not content:
        content = fallback_structured_compaction_summary(messages, existing_summary=existing_summary)
    summary = with_compaction_prefix(content)
    if on_delta is not None and not emitted_delta:
        await _emit_compaction_delta(on_delta, summary)
    return summary


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
        "1. Current Goal\n"
        "- Continue the active user task using the latest uncompressed user message.\n\n"
        "2. User History, Instructions, And Decisions\n"
        f"{user_body}\n\n"
        "3. Completed Work\n"
        f"{body}\n\n"
        "4. Key Decisions And Constraints\n"
        "- Prior user messages are high-value context; preserve explicit corrections, decisions, and acceptance criteria.\n"
        "- Preserve the latest user instructions and repository constraints.\n\n"
        "5. Files, APIs, Commands, And Results\n"
        "- See completed work snippets above.\n\n"
        "6. Open Issues Or Risks\n"
        "- Summary was generated by local fallback because no model compaction client was provided.\n\n"
        "7. Next Best Actions\n"
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
        for line in lines:
            stripped = " ".join(line.strip().split())
            if not stripped:
                continue
            if len(stripped) > 260:
                omitted = True
                continue
            compacted_lines.append(stripped)
            kept += 1
            if kept >= 3:
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
                if lines[index].startswith("- ") and "User History, Instructions, And Decisions" not in lines[index]
            ),
            len(lines) - 1,
        )
        lines.pop(removable)
    return "\n".join(lines).strip()


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
    "fallback_structured_compaction_summary",
    "format_messages_for_compaction",
    "select_context_compaction_layout",
    "summarize_context_messages",
    "truncate_text_to_tokens",
    "with_compaction_prefix",
]
