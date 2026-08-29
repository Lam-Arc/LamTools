"""Token budgets used by context compaction.

The public policy may be expressed as ratios, while compaction algorithms
should operate on concrete token counts.  This module is intentionally small
so the policy-to-budget conversion has one well-defined home before the rest
of the compaction implementation is split into separate components.
"""

from __future__ import annotations

from dataclasses import dataclass


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


__all__ = ["TokenBudget"]
