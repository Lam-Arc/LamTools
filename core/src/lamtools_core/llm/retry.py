from __future__ import annotations

import asyncio
import inspect
import logging
import time as time_module
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

from lamtools_core.llm import LLMClient, LLMRequest, LLMResponse, LLMStreamEvent
from lamtools_core.llm.policy import DEFAULT_DELAY_SEQUENCE_SECONDS, RetryPolicy

_logger = logging.getLogger(__name__)

#: Upper bound for honoring a provider Retry-After header.
MAX_RETRY_AFTER_SECONDS = 120.0

T = TypeVar("T")


@dataclass(frozen=True)
class ModelRetryEvent:
    attempt: int
    max_retries: int
    delay_seconds: float
    kind: str
    error: Exception


class ModelRetryExhausted(RuntimeError):
    def __init__(self, *, attempts: int, last_error: Exception) -> None:
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(f"Model call failed after {attempts} attempts: {last_error}")


ModelRetrySink = Callable[[ModelRetryEvent], Awaitable[None] | None]
SleepFn = Callable[[float], Awaitable[None]]


def classify_model_error(exc: Exception) -> str:
    """Classify an LLM error for retry decisions.

    Returns one of:
      - ``"fatal"``       — config/programming error, never retry (e.g. unknown model)
      - ``"token_overflow"`` — context window exceeded, never retry
      - ``"rate_limit"``  — transient, retry with backoff + retry-after
      - ``"retryable"``   — unknown transient, retry with backoff

    Structured providers (``LLMProviderError`` / ``RateLimitError``) are
    classified by HTTP status code first: 4xx (except 429/408) is a client
    error that retrying cannot fix, 5xx is transient. Message-text matching
    remains only as a fallback for untyped errors (audit 10 S2).
    """
    name = type(exc).__name__
    if name == "TokenOverflowError":
        return "token_overflow"
    if name == "RateLimitError":
        return "rate_limit"
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        if status_code == 429:
            return "rate_limit"
        if status_code in (408, 409, 425, 500, 502, 503, 504):
            return "retryable"
        if 400 <= status_code < 500:
            return "fatal"
        if status_code >= 500:
            return "retryable"
    msg = str(exc).lower()
    if any(
        marker in msg
        for marker in (
            "context length",
            "context window",
            "maximum context",
            "too long",
            "token limit",
            "max_tokens",
        )
    ):
        return "token_overflow"
    if any(marker in msg for marker in ("rate limit", "rate_limit", "429", "too many requests")):
        return "rate_limit"
    # Configuration errors — retrying is pointless and causes retry storms
    if any(marker in msg for marker in ("model not found", "unknown model", "model not available", "provider unavailable", "provider not available")):
        return "fatal"
    return "retryable"


def model_retry_delay(retry_policy: RetryPolicy, attempt: int) -> float:
    sequence = retry_policy.delay_sequence_seconds or DEFAULT_DELAY_SEQUENCE_SECONDS
    delay = float(sequence[min(attempt, len(sequence) - 1)])
    if retry_policy.jitter:
        import random

        delay = delay * (0.5 + random.random())
    return delay


async def complete_with_retry(
    llm_client: LLMClient,
    request: LLMRequest,
    *,
    max_attempts: int,
    timeout_seconds: float | None,
    retry_policy: RetryPolicy | None = None,
    on_retry: ModelRetrySink | None = None,
    sleep: SleepFn | None = None,
) -> LLMResponse:
    async def operation() -> LLMResponse:
        call = llm_client.complete(request)
        timeout = request.timeout if request.timeout is not None else timeout_seconds
        if timeout is not None and timeout > 0:
            return await asyncio.wait_for(call, timeout=timeout)
        return await call

    return await run_with_model_retry(
        operation,
        max_attempts=max_attempts,
        retry_policy=retry_policy,
        on_retry=on_retry,
        sleep=sleep,
    )


async def stream_with_retry(
    llm_client: LLMClient,
    request: LLMRequest,
    *,
    max_attempts: int,
    timeout_seconds: float | None,
    retry_policy: RetryPolicy | None = None,
    on_retry: ModelRetrySink | None = None,
    sleep: SleepFn | None = None,
) -> AsyncIterator[LLMStreamEvent]:
    attempts = max(1, int(max_attempts or 1))
    policy = retry_policy or RetryPolicy()
    sleep_fn = sleep or asyncio.sleep
    last_error: Exception | None = None
    _start_ts = time_module.time()
    _logger.info("[retry:stream_with_retry] attempting stream model=%s messages=%d max_attempts=%d timeout=%s",
                  request.model, len(request.messages), attempts, timeout_seconds)
    for attempt in range(attempts):
        emitted = False
        try:
            stream = llm_client.stream(request)
            if inspect.isawaitable(stream):
                stream = await stream
            if not hasattr(stream, "__aiter__"):
                raise NotImplementedError
            # No wall-clock timeout around the whole stream: that would kill a
            # still-live stream whenever event handling is slow, and it
            # contradicts the per-event idle semantics of
            # model_stream_idle_timeout_seconds (audit 10 S3). Idle detection
            # is the caller's job (kernel._next_stream_event).
            async for event in stream:
                if event.kind == "error":
                    raise RuntimeError(event.error or "model stream failed")
                emitted = True
                yield event
            return
        except (AttributeError, NotImplementedError):
            raise
        except Exception as exc:
            if emitted:
                raise
            last_error = exc
            kind = classify_model_error(exc)
            if kind in ("token_overflow", "fatal"):
                raise
            if attempt >= attempts - 1:
                break
            delay = _delay_for_error(policy, attempt, kind, exc)
            _logger.warning(
                "[retry:stream_with_retry] attempt %d/%d failed model=%s kind=%s delay=%.2fs error=%s",
                attempt + 1, attempts, request.model, kind, delay, exc,
            )
            await _notify_retry(
                on_retry,
                ModelRetryEvent(
                    attempt=attempt + 1,
                    max_retries=max(0, attempts - 1),
                    delay_seconds=delay,
                    kind=kind,
                    error=exc,
                ),
            )
            await sleep_fn(delay)
    if last_error is None:
        last_error = RuntimeError("model stream did not start")
    _elapsed = time_module.time() - _start_ts
    _logger.error("[retry:stream_with_retry] exhausted %d attempts model=%s elapsed=%.2fs last_error=%s",
                   attempts, request.model, _elapsed, last_error)
    raise ModelRetryExhausted(attempts=attempts, last_error=last_error)


async def run_with_model_retry(
    operation: Callable[[], Awaitable[T]],
    *,
    max_attempts: int,
    retry_policy: RetryPolicy | None = None,
    on_retry: ModelRetrySink | None = None,
    sleep: SleepFn | None = None,
) -> T:
    attempts = max(1, int(max_attempts or 1))
    policy = retry_policy or RetryPolicy()
    sleep_fn = sleep or asyncio.sleep
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return await operation()
        except Exception as exc:
            last_error = exc
            kind = classify_model_error(exc)
            if kind in ("token_overflow", "fatal"):
                raise
            if attempt >= attempts - 1:
                break
            delay = _delay_for_error(policy, attempt, kind, exc)
            await _notify_retry(
                on_retry,
                ModelRetryEvent(
                    attempt=attempt + 1,
                    max_retries=max(0, attempts - 1),
                    delay_seconds=delay,
                    kind=kind,
                    error=exc,
                ),
            )
            await sleep_fn(delay)
    if last_error is None:
        last_error = RuntimeError("model call did not start")
    raise ModelRetryExhausted(attempts=attempts, last_error=last_error)


def _delay_for_error(policy: RetryPolicy, attempt: int, kind: str, exc: Exception) -> float:
    if kind == "rate_limit":
        retry_after = getattr(exc, "retry_after", None)
        try:
            value = float(retry_after) if retry_after is not None else None
        except (TypeError, ValueError):
            # Non-numeric (e.g. an unparsed HTTP-date slipped through) — fall
            # back to the fixed sequence rather than crashing the retry path
            # (audit 10 S3).
            value = None
        if value is not None and value > 0:
            return min(value, MAX_RETRY_AFTER_SECONDS)
    return model_retry_delay(policy, attempt)


async def _notify_retry(on_retry: ModelRetrySink | None, event: ModelRetryEvent) -> None:
    if on_retry is None:
        return
    result = on_retry(event)
    if inspect.isawaitable(result):
        await result
