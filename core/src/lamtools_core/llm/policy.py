"""Transport-level LLM policy types.

Transport-level retry configuration (algorithm, delays, jitter).
Does NOT duplicate kernel.LoopPolicy (model_retries, model_timeout_seconds)
which controls runtime retry *count* — these control HOW retries behave.

Separation of concerns:
  - kernel.LoopPolicy.model_retries → how many times to retry (count)
  - RetryPolicy                       → how to retry (strategy, backoff, jitter)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class BackoffStrategy(Enum):
    """Backoff algorithm for transport-level retries."""

    FIXED = "fixed"
    LINEAR = "linear"
    EXPONENTIAL = "exponential"


@dataclass
class RetryPolicy:
    """Transport-level retry policy.

    Defines the backoff strategy for retrying failed LLM calls.
    The *number* of retries is controlled by kernel.LoopPolicy.model_retries.

    Example:
        policy = RetryPolicy(
            backoff_strategy=BackoffStrategy.FIXED,
            initial_delay_seconds=0.5,
            max_delay_seconds=0.5,
            jitter=False,
        )
    """

    backoff_strategy: BackoffStrategy = BackoffStrategy.FIXED
    initial_delay_seconds: float = 0.5
    jitter: bool = True
    staged_delay_seconds: tuple[float, ...] = ()


__all__ = [
    "BackoffStrategy",
    "RetryPolicy",
]
