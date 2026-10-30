from __future__ import annotations

import pytest

from lamtools_core.context_compaction_budget import (
    SummaryTokenBudget,
    TokenBudget,
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


def test_summary_budget_reserves_output_protocol_and_safety():
    budget = SummaryTokenBudget(
        context_window=1_000,
        output_tokens=200,
        protocol_tokens=100,
        safety_margin_tokens=0,
    )

    assert budget.max_input_tokens == 700


def test_summary_budget_factory_uses_three_percent_safety_margin():
    budget = SummaryTokenBudget.for_context_window(
        context_window=10_000,
        output_tokens=2_000,
        protocol_tokens=500,
    )

    assert budget.safety_margin_tokens == 300
    assert budget.max_input_tokens == 7_200


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
