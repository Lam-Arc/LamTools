"""Token budgets used by context compaction.

The public policy may be expressed as ratios, while compaction algorithms
should operate on concrete token counts.  This module is intentionally small
so the policy-to-budget conversion has one well-defined home before the rest
of the compaction implementation is split into separate components.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from lamtools_core.llm import ChatMessage
from lamtools_core.tokens import estimate_message_tokens


FAST_ESTIMATE_SAFETY_FACTOR = 8.0


@dataclass(frozen=True, slots=True)
class TokenBudget:
    """Concrete token limits for one context-compaction policy."""

    context_window: int
    trigger_tokens: int
    target_tokens: int
    reserved_output_tokens: int = 0
    safety_margin_tokens: int = 0

    def __post_init__(self) -> None:
        if self.context_window <= 0:
            raise ValueError("context_window must be positive")
        if not 0 < self.target_tokens <= self.trigger_tokens:
            raise ValueError("expected 0 < target_tokens <= trigger_tokens")
        if self.trigger_tokens > self.context_window:
            raise ValueError("trigger_tokens cannot exceed context_window")
        if self.reserved_output_tokens < 0:
            raise ValueError("reserved_output_tokens cannot be negative")
        if self.safety_margin_tokens < 0:
            raise ValueError("safety_margin_tokens cannot be negative")

    @property
    def max_input_tokens(self) -> int:
        """Return the context window left for model input after reserves."""
        return max(
            0,
            self.context_window
            - self.reserved_output_tokens
            - self.safety_margin_tokens,
        )

    @classmethod
    def from_policy(
        cls,
        *,
        context_window: int,
        trigger_ratio: float,
        target_ratio: float,
        trigger_tokens: int | None = None,
        target_tokens: int | None = None,
        reserved_output_tokens: int = 0,
        safety_margin_tokens: int = 0,
    ) -> "TokenBudget":
        """Resolve ratio defaults while letting explicit token values win."""
        resolved_trigger = (
            trigger_tokens
            if trigger_tokens is not None
            else int(context_window * trigger_ratio)
        )
        resolved_target = (
            target_tokens
            if target_tokens is not None
            else int(context_window * target_ratio)
        )
        return cls(
            context_window=context_window,
            trigger_tokens=resolved_trigger,
            target_tokens=resolved_target,
            reserved_output_tokens=reserved_output_tokens,
            safety_margin_tokens=safety_margin_tokens,
        )


@dataclass(frozen=True, slots=True)
class TokenMeasurement:
    """A token estimate and whether it used the exact estimator."""

    tokens: int
    exact: bool


MessageTokenEstimator = Callable[[list[ChatMessage]], int]


def measure_for_compaction_trigger(
    messages: Sequence[ChatMessage],
    *,
    trigger_tokens: int,
    fast_estimate: MessageTokenEstimator | None = None,
    exact_estimate: MessageTokenEstimator | None = None,
    fast_safety_factor: float = FAST_ESTIMATE_SAFETY_FACTOR,
) -> TokenMeasurement:
    """Use the fast estimator only when it is safely below the trigger.

    Fast estimation is deliberately treated as a lower-bound-like signal:
    Unicode-heavy text can be substantially undercounted.  Once the scaled
    fast estimate is near the trigger, the caller's exact estimator is used.
    Custom estimators let callers include request-level overhead such as tool
    definitions and response formats.
    """
    values = list(messages)
    fast_fn = fast_estimate or (
        lambda current: estimate_message_tokens(
            [message.to_dict() for message in current],
            fast=True,
        )
    )
    exact_fn = exact_estimate or (
        lambda current: estimate_message_tokens(
            [message.to_dict() for message in current],
            fast=False,
        )
    )
    fast_tokens = max(0, int(fast_fn(values)))
    if fast_tokens * fast_safety_factor < trigger_tokens:
        return TokenMeasurement(tokens=fast_tokens, exact=False)
    return TokenMeasurement(tokens=max(0, int(exact_fn(values))), exact=True)


__all__ = [
    "FAST_ESTIMATE_SAFETY_FACTOR",
    "TokenBudget",
    "TokenMeasurement",
    "measure_for_compaction_trigger",
]
