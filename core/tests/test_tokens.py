"""Local compaction measurements carry the agreed 2.5x safety factor."""

from __future__ import annotations

from lamtools_core.context_compaction_budget import (
    LOCAL_ESTIMATE_SCALE,
    measure_for_compaction_trigger,
)
from lamtools_core.llm import ChatMessage


def test_local_estimate_scale_is_2_5() -> None:
    assert LOCAL_ESTIMATE_SCALE == 2.5


def test_fast_measurement_is_scaled() -> None:
    messages = [ChatMessage(role="user", content="x")]
    measurement = measure_for_compaction_trigger(
        messages,
        trigger_tokens=100_000,
        fast_estimate=lambda _: 10,
        exact_estimate=lambda _: 10,
    )
    assert measurement.tokens == 25
    assert measurement.exact is False


def test_exact_measurement_is_scaled() -> None:
    messages = [ChatMessage(role="user", content="x")]
    measurement = measure_for_compaction_trigger(
        messages,
        trigger_tokens=100_000,
        fast_estimate=lambda _: 100_000,
        exact_estimate=lambda _: 10,
    )
    assert measurement.tokens == 25
    assert measurement.exact is True
