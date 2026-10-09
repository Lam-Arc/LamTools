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
DEFAULT_SUMMARY_OUTPUT_TOKENS = 4_096
DEFAULT_SUMMARY_PROTOCOL_TOKENS = 1_024
DEFAULT_SUMMARY_SAFETY_RATIO = 0.03

# Structural context retention defaults.  These values are deliberately kept
# beside the token-budget policy so every compaction entrypoint uses one
# canonical policy rather than carrying its own fallback.
DEFAULT_RETAINED_STEPS = 0
MAX_RETAINED_STEPS = 100
MAX_RETAINED_USER_MESSAGES = 20
CONTEXT_COMPACTION_NAMESPACE = "core.contextCompaction"


def resolve_retained_steps(value: Any = None) -> int:
    """Validate a retained-step setting, falling back to the public default.

    Settings are JSON values, so only an actual integer is accepted.  In
    particular, booleans (which are ``int`` subclasses in Python), floats and
    numeric strings are invalid and resolve to the default.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return DEFAULT_RETAINED_STEPS
    if not 0 <= value <= MAX_RETAINED_STEPS:
        return DEFAULT_RETAINED_STEPS
    return value


def load_retained_steps() -> int:
    """Read the global context-compaction setting with safe fallback.

    The import is lazy to keep this low-level budget module independent of the
    config package at import time (the config package itself imports model and
    LLM helpers used by this module).
    """
    try:
        from lamtools_core.config.settings_store import get_setting

        value = get_setting(CONTEXT_COMPACTION_NAMESPACE)
        if isinstance(value, dict):
            value = value.get("retained_steps")
        return resolve_retained_steps(value)
    except Exception:
        # A malformed/unavailable settings file must never disable context
        # compaction.  The documented default remains safe and deterministic.
        return DEFAULT_RETAINED_STEPS


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


def resolve_compaction_budget(
    *,
    context_window: int,
    trigger_ratio: float = 0.8,
    target_ratio: float = 0.6,
    trigger_tokens: int | None = None,
    target_tokens: int | None = None,
) -> TokenBudget:
    """Resolve the shared automatic/manual compaction policy."""
    window = max(1, int(context_window))
    resolved_trigger_ratio = min(max(float(trigger_ratio), 0.01), 1.0)
    resolved_target_ratio = min(
        max(float(target_ratio), 0.01), resolved_trigger_ratio
    )
    resolved_trigger = int(
        trigger_tokens or int(window * resolved_trigger_ratio)
    )
    resolved_target = int(target_tokens or int(window * resolved_target_ratio))
    resolved_trigger = min(max(1, resolved_trigger), window)
    resolved_target = min(max(1, resolved_target), resolved_trigger)
    return TokenBudget(
        context_window=window,
        trigger_tokens=resolved_trigger,
        target_tokens=resolved_target,
    )


@dataclass(frozen=True, slots=True)
class SummaryTokenBudget:
    """Input/output budget for one model-backed summary request."""

    context_window: int
    output_tokens: int
    protocol_tokens: int
    safety_margin_tokens: int

    def __post_init__(self) -> None:
        if self.context_window <= 0:
            raise ValueError("context_window must be positive")
        if self.output_tokens < 0:
            raise ValueError("output_tokens cannot be negative")
        if self.protocol_tokens < 0:
            raise ValueError("protocol_tokens cannot be negative")
        if self.safety_margin_tokens < 0:
            raise ValueError("safety_margin_tokens cannot be negative")

    @property
    def max_input_tokens(self) -> int:
        """Return the input budget after output and protocol reserves."""
        return max(
            0,
            self.context_window
            - self.output_tokens
            - self.protocol_tokens
            - self.safety_margin_tokens,
        )

    @classmethod
    def for_context_window(
        cls,
        *,
        context_window: int,
        output_tokens: int = DEFAULT_SUMMARY_OUTPUT_TOKENS,
        protocol_tokens: int = DEFAULT_SUMMARY_PROTOCOL_TOKENS,
        safety_margin_tokens: int | None = None,
    ) -> "SummaryTokenBudget":
        """Build a conservative budget with a three-percent safety reserve."""
        resolved_safety = (
            int(context_window * DEFAULT_SUMMARY_SAFETY_RATIO)
            if safety_margin_tokens is None
            else safety_margin_tokens
        )
        return cls(
            context_window=context_window,
            output_tokens=output_tokens,
            protocol_tokens=protocol_tokens,
            safety_margin_tokens=resolved_safety,
        )


@dataclass(frozen=True, slots=True)
class TokenMeasurement:
    """A token estimate, how exact it is, and where it came from.

    ``source`` names the measurement route for diagnostics: ``fast_estimate``
    and ``exact_estimate`` are local estimators, ``provider_anchor`` means the
    bulk of the prompt came from real provider usage with only the appended
    tail estimated (see ``context_compaction.usage_anchor``).
    """

    tokens: int
    exact: bool
    source: str = ""

    @property
    def resolved_source(self) -> str:
        """Return ``source``, deriving it from ``exact`` for legacy callers."""
        return self.source or ("exact_estimate" if self.exact else "fast_estimate")


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
        return TokenMeasurement(tokens=fast_tokens, exact=False, source="fast_estimate")
    return TokenMeasurement(
        tokens=max(0, int(exact_fn(values))),
        exact=True,
        source="exact_estimate",
    )


__all__ = [
    "CONTEXT_COMPACTION_NAMESPACE",
    "DEFAULT_SUMMARY_OUTPUT_TOKENS",
    "DEFAULT_SUMMARY_PROTOCOL_TOKENS",
    "DEFAULT_SUMMARY_SAFETY_RATIO",
    "DEFAULT_RETAINED_STEPS",
    "FAST_ESTIMATE_SAFETY_FACTOR",
    "MAX_RETAINED_STEPS",
    "MAX_RETAINED_USER_MESSAGES",
    "SummaryTokenBudget",
    "TokenBudget",
    "TokenMeasurement",
    "load_retained_steps",
    "measure_for_compaction_trigger",
    "resolve_retained_steps",
    "resolve_compaction_budget",
]
