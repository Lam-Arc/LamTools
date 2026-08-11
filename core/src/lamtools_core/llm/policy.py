"""Transport-level LLM policy types.

Transport-level retry configuration (delay sequence, jitter). Does NOT
duplicate kernel.LoopPolicy (model_retries, model_timeout_seconds) which
controls runtime retry *count* — these control HOW retries behave.

Separation of concerns:
  - kernel.LoopPolicy.model_retries → how many times to retry (count)
  - RetryPolicy                       → how long to wait between retries
"""

from __future__ import annotations

from dataclasses import dataclass

#: Default per-retry wait sequence (seconds): element i is the wait before
#: retry i; attempts beyond the sequence reuse the tail value (5s). The sole
#: source of truth for the default rhythm — model_retry.jsonc mirrors it.
DEFAULT_DELAY_SEQUENCE_SECONDS: tuple[float, ...] = (1.0, 1.0, 2.0, 5.0, 5.0)


@dataclass
class RetryPolicy:
    """Transport-level retry policy.

    The wait before each retry is taken from ``delay_sequence_seconds``:
    element i is the wait before retry i, and attempts beyond the sequence
    length reuse the last value. An empty sequence falls back to the default
    rhythm ``DEFAULT_DELAY_SEQUENCE_SECONDS``.

    The *number* of retries is controlled by kernel.LoopPolicy.model_retries.

    Example:
        policy = RetryPolicy(delay_sequence_seconds=(1.0, 2.0, 4.0), jitter=False)
    """

    delay_sequence_seconds: tuple[float, ...] = DEFAULT_DELAY_SEQUENCE_SECONDS
    jitter: bool = True


__all__ = [
    "DEFAULT_DELAY_SEQUENCE_SECONDS",
    "RetryPolicy",
]
