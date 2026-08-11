"""Tests for model_retry.jsonc (model request retry configuration)."""
from __future__ import annotations

from pathlib import Path

import pytest

from lamtools_core.config.retry_store import (
    DEFAULT_MODEL_RETRY_CONFIG,
    load_model_retry_config,
    loop_policy_overrides,
    model_retry_path,
    retry_policy_from_config,
)
from lamtools_core.llm.policy import RetryPolicy
from lamtools_core.llm.retry import model_retry_delay


def _write_retry_config(isolated_config_root: Path, text: str) -> Path:
    path = isolated_config_root / "model_retry.jsonc"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_missing_file_returns_defaults(isolated_config_root: Path) -> None:
    config = load_model_retry_config()
    assert config == DEFAULT_MODEL_RETRY_CONFIG
    assert config["model_retries"] == 10
    assert config["retry_delays_seconds"] == [1, 1, 2, 5, 5]
    assert not model_retry_path().exists()


def test_partial_config_only_overrides_present_keys(isolated_config_root: Path) -> None:
    _write_retry_config(
        isolated_config_root,
        '{ "retry_delays_seconds": [1, 2, 4], "model_retries": 4 }\n',
    )
    config = load_model_retry_config()
    assert config["retry_delays_seconds"] == [1, 2, 4]
    assert config["model_retries"] == 4
    assert config["model_timeout_seconds"] == 360
    assert config["jitter"] is True


def test_full_override(isolated_config_root: Path) -> None:
    _write_retry_config(
        isolated_config_root,
        (
            '{\n'
            '  "retry_delays_seconds": [0.5],\n'
            '  "model_retries": 5,\n'
            '  "model_timeout_seconds": 30,\n'
            '  "model_stream_idle_timeout_seconds": 15,\n'
            '  "empty_response_retries": 0,\n'
            '  "jitter": false\n'
            '}\n'
        ),
    )
    assert load_model_retry_config() == {
        "retry_delays_seconds": [0.5],
        "model_retries": 5,
        "model_timeout_seconds": 30,
        "model_stream_idle_timeout_seconds": 15,
        "empty_response_retries": 0,
        "jitter": False,
    }


def test_invalid_values_fall_back_to_defaults(isolated_config_root: Path) -> None:
    _write_retry_config(
        isolated_config_root,
        (
            '{\n'
            '  "retry_delays_seconds": [0, -2, "x"],\n'
            '  "model_retries": -1,\n'
            '  "model_timeout_seconds": "abc",\n'
            '  "model_stream_idle_timeout_seconds": -5,\n'
            '  "empty_response_retries": -3,\n'
            '  "jitter": "yes"\n'
            '}\n'
        ),
    )
    config = load_model_retry_config()
    # Zero is legal (immediate retry); negatives and non-numeric entries are
    # dropped from the sequence.
    assert config["retry_delays_seconds"] == [0.0]
    assert config["model_retries"] == 10
    assert config["model_timeout_seconds"] == 360
    assert config["model_stream_idle_timeout_seconds"] == 120
    assert config["empty_response_retries"] == 3
    assert config["jitter"] is True


def test_stream_idle_null_disables_timeout(isolated_config_root: Path) -> None:
    _write_retry_config(isolated_config_root, '{ "model_stream_idle_timeout_seconds": null }\n')
    assert load_model_retry_config()["model_stream_idle_timeout_seconds"] is None


def test_jsonc_comments_and_trailing_commas_are_tolerated(isolated_config_root: Path) -> None:
    _write_retry_config(
        isolated_config_root,
        (
            '// 模型请求重试配置\n'
            '{\n'
            '  "retry_delays_seconds": [1, 2,], // 每次重试前等待秒数\n'
            '  "model_retries": 4,\n'
            '}\n'
        ),
    )
    config = load_model_retry_config()
    assert config["retry_delays_seconds"] == [1, 2]
    assert config["model_retries"] == 4


def test_broken_jsonc_returns_defaults(isolated_config_root: Path) -> None:
    _write_retry_config(isolated_config_root, "{ not json at all !!\n")
    assert load_model_retry_config() == DEFAULT_MODEL_RETRY_CONFIG


def test_loop_policy_overrides_maps_loop_fields(isolated_config_root: Path) -> None:
    _write_retry_config(
        isolated_config_root,
        (
            '{\n'
            '  "model_retries": 7,\n'
            '  "model_timeout_seconds": 99,\n'
            '  "model_stream_idle_timeout_seconds": 45,\n'
            '  "empty_response_retries": 2\n'
            '}\n'
        ),
    )
    overrides = loop_policy_overrides()
    assert overrides == {
        "model_retries": 7,
        "model_timeout_seconds": 99,
        "model_stream_idle_timeout_seconds": 45,
        "empty_response_retries": 2,
    }


def test_retry_policy_from_config_builds_sequence(isolated_config_root: Path) -> None:
    _write_retry_config(
        isolated_config_root,
        '{ "retry_delays_seconds": [1, 2, 4], "jitter": false }\n',
    )
    policy = retry_policy_from_config()
    assert policy.delay_sequence_seconds == (1.0, 2.0, 4.0)
    assert policy.jitter is False


def test_retry_policy_defaults_when_no_config(isolated_config_root: Path) -> None:
    policy = retry_policy_from_config()
    assert policy.delay_sequence_seconds == (1.0, 1.0, 2.0, 5.0, 5.0)
    assert policy.jitter is True


def test_model_retry_delay_sequence_tail_reuse() -> None:
    policy = RetryPolicy(delay_sequence_seconds=(1.0, 2.0, 4.0), jitter=False)
    assert model_retry_delay(policy, 0) == 1.0
    assert model_retry_delay(policy, 1) == 2.0
    assert model_retry_delay(policy, 2) == 4.0
    # Attempts beyond the sequence reuse the tail value.
    assert model_retry_delay(policy, 3) == 4.0
    assert model_retry_delay(policy, 99) == 4.0


def test_model_retry_delay_sequence_jitter_range() -> None:
    policy = RetryPolicy(delay_sequence_seconds=(1.0,), jitter=True)
    import random

    random.seed(42)
    for _ in range(50):
        delay = model_retry_delay(policy, 0)
        assert 0.5 <= delay <= 1.5


def test_empty_sequence_falls_back_to_default_rhythm() -> None:
    policy = RetryPolicy(delay_sequence_seconds=(), jitter=False)
    assert model_retry_delay(policy, 0) == 1.0
    assert model_retry_delay(policy, 1) == 1.0
    assert model_retry_delay(policy, 2) == 2.0
    assert model_retry_delay(policy, 3) == 5.0
    assert model_retry_delay(policy, 99) == 5.0  # tail value reused


# --- assembly integration: create_kernel reads the config file ---


class _Dummy:
    def __init__(self, **kwargs: object) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)


@pytest.fixture
def kernel_args() -> dict[str, object]:
    return {
        "kit": _Dummy(),
        "llm_client": _Dummy(),
        "state_store": _Dummy(),
        "event_sink": _Dummy(),
    }


def test_create_kernel_applies_config_file(isolated_config_root: Path, kernel_args: dict[str, object]) -> None:
    from lamtools_core.app.default_agent import create_kernel

    _write_retry_config(
        isolated_config_root,
        '{ "retry_delays_seconds": [1, 3], "model_retries": 9, "jitter": false }\n',
    )
    kernel = create_kernel(**kernel_args)
    assert kernel.policy.model_retries == 9
    assert kernel.policy.model_timeout_seconds == 360
    assert kernel.retry_policy.delay_sequence_seconds == (1.0, 3.0)
    assert kernel.retry_policy.jitter is False


def test_create_kernel_explicit_args_beat_config_file(
    isolated_config_root: Path, kernel_args: dict[str, object]
) -> None:
    from lamtools_core.app.default_agent import create_kernel

    _write_retry_config(isolated_config_root, '{ "model_retries": 9, "model_timeout_seconds": 77 }\n')
    kernel = create_kernel(**kernel_args, model_retries=3, model_timeout_seconds=120)
    assert kernel.policy.model_retries == 3
    assert kernel.policy.model_timeout_seconds == 120
    # Other knobs still come from the config file (default sequence here).
    assert kernel.retry_policy.delay_sequence_seconds == (1.0, 1.0, 2.0, 5.0, 5.0)


def test_create_kernel_explicit_retry_policy_wins(
    isolated_config_root: Path, kernel_args: dict[str, object]
) -> None:
    from lamtools_core.app.default_agent import create_kernel

    _write_retry_config(isolated_config_root, '{ "retry_delays_seconds": [9] }\n')
    explicit = RetryPolicy(delay_sequence_seconds=(2.0, 2.0), jitter=False)
    kernel = create_kernel(**kernel_args, retry_policy=explicit)
    assert kernel.retry_policy is explicit


def test_create_kernel_defaults_when_no_config_file(
    isolated_config_root: Path, kernel_args: dict[str, object]
) -> None:
    from lamtools_core.app.default_agent import create_kernel

    kernel = create_kernel(**kernel_args)
    assert kernel.policy.model_retries == 10
    assert kernel.policy.model_timeout_seconds == 360
    assert kernel.policy.model_stream_idle_timeout_seconds == 120
    assert kernel.retry_policy.delay_sequence_seconds == (1.0, 1.0, 2.0, 5.0, 5.0)
    assert kernel.retry_policy.jitter is True


def test_ensure_default_config_files_seeds_model_retry_jsonc(
    isolated_config_root: Path,
) -> None:
    from lamtools_core.config.defaults import ensure_default_config_files

    created = ensure_default_config_files()
    target = isolated_config_root / "model_retry.jsonc"
    assert target in created
    assert target.exists()
    # Idempotent: user edits are never overwritten.
    target.write_text('{ "model_retries": 5 }\n', encoding="utf-8")
    ensure_default_config_files()
    assert target.read_text(encoding="utf-8") == '{ "model_retries": 5 }\n'
