"""Kernel error types."""

from __future__ import annotations


class KernelError(Exception):
    """Base error for Core Loop Kernel operations."""


class ModelCallError(KernelError):
    """LLM model call failed after retries."""


class TokenOverflowError(KernelError):
    """Request exceeded model context window. Not retryable — the request
    must be compacted or shortened before retrying."""


class RateLimitError(KernelError):
    """Provider returned a rate-limit error (HTTP 429). Should honor
    Retry-After header if available."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class LLMProviderError(KernelError):
    """Provider returned a non-2xx HTTP status.

    Carries the status code so ``classify_model_error`` can treat 4xx (except
    429/408) as fatal and 5xx as retryable instead of guessing from message
    text — previously a 401/403/400 was classified "retryable" and retried
    up to 10 times (~34s of useless waiting, audit 10 S2).
    """

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class StateSaveError(KernelError):
    """Failed to save runtime state."""


__all__ = [
    "KernelError",
    "ModelCallError",
    "TokenOverflowError",
    "RateLimitError",
    "LLMProviderError",
    "StateSaveError",
]
