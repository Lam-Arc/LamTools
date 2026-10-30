"""Local compaction estimates carry the agreed 2.5x safety factor."""

from __future__ import annotations

from lamtools_core.context_compaction_budget import (
    LOCAL_ESTIMATE_SCALE,
    calibrated_tokens,
)


def test_local_estimate_scale_is_2_5() -> None:
    assert LOCAL_ESTIMATE_SCALE == 2.5


def test_calibration_multiplies_once_and_rounds_up() -> None:
    assert calibrated_tokens(0) == 0
    assert calibrated_tokens(1) == 3
    assert calibrated_tokens(10) == 25
