from __future__ import annotations

import pytest

from lamtools_core.context_compaction_budget import (
    TokenBudget,
    TokenMeasurement,
    measure_for_compaction_trigger,
)
from lamtools_core.llm import ChatMessage


def test_budget_from_ratios():
    budget = TokenBudget.from_policy(
        context_window=10_000,
        trigger_ratio=0.8,
        target_ratio=0.6,
    )

    assert budget.trigger_tokens == 8_000
    assert budget.target_tokens == 6_000


def test_explicit_tokens_override_ratio():
    budget = TokenBudget.from_policy(
        context_window=10_000,
        trigger_ratio=0.8,
        target_ratio=0.6,
        trigger_tokens=7_000,
        target_tokens=2_000,
    )

    assert budget.trigger_tokens == 7_000
    assert budget.target_tokens == 2_000


def test_max_input_reserves_output():
    budget = TokenBudget(
        context_window=10_000,
        trigger_tokens=8_000,
        target_tokens=6_000,
        reserved_output_tokens=1_000,
        safety_margin_tokens=250,
    )

    assert budget.max_input_tokens == 8_750


def test_invalid_target_above_trigger_rejected():
    with pytest.raises(ValueError, match="target_tokens"):
        TokenBudget(context_window=10_000, trigger_tokens=6_000, target_tokens=7_000)


def test_negative_reserve_rejected():
    with pytest.raises(ValueError, match="reserved_output_tokens"):
        TokenBudget(
            context_window=10_000,
            trigger_tokens=8_000,
            target_tokens=6_000,
            reserved_output_tokens=-1,
        )


def test_cjk_context_triggers_exact_measurement():
    measurement = measure_for_compaction_trigger(
        [ChatMessage(role="user", content="中" * 1500)],
        trigger_tokens=1_000,
    )

    assert measurement.exact is True
    assert measurement.tokens >= 1_000


def test_emoji_context_triggers_exact_measurement():
    measurement = measure_for_compaction_trigger(
        [ChatMessage(role="user", content="🙂" * 500)],
        trigger_tokens=1_000,
    )

    assert measurement.exact is True
    assert measurement.tokens >= 1_000


def test_small_ascii_context_uses_fast_path():
    measurement = measure_for_compaction_trigger(
        [ChatMessage(role="user", content="small prompt")],
        trigger_tokens=2_000,
    )

    assert measurement.exact is False


def test_custom_request_estimator_is_used_for_exact_measurement():
    calls: list[str] = []

    def fast(messages: list[ChatMessage]) -> int:
        calls.append("fast")
        return len(messages) * 20

    def exact(messages: list[ChatMessage]) -> int:
        calls.append("exact")
        return 101

    measurement = measure_for_compaction_trigger(
        [ChatMessage(role="user", content="payload")],
        trigger_tokens=100,
        fast_estimate=fast,
        exact_estimate=exact,
    )

    assert measurement == TokenMeasurement(tokens=101, exact=True)
    assert calls == ["fast", "exact"]
