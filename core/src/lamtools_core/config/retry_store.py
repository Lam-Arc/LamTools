"""Model request retry configuration stored in a single jsonc file.

Retry knobs that used to be hard-coded defaults live at
``{config_dir}/model_retry.jsonc``::

    {
      "retry_delays_seconds": [1, 1, 2, 5, 5],
      "model_retries": 10,
      "model_timeout_seconds": 360,
      "model_stream_idle_timeout_seconds": 120,
      "empty_response_retries": 3,
      "jitter": true
    }

``retry_delays_seconds`` is the sole source of retry timing: element i is the
wait before retry i, and attempts beyond the sequence length reuse the tail
value. An empty/missing list falls back to the default rhythm
``1, 1, 2, 5, 5`` (``llm.policy.DEFAULT_DELAY_SEQUENCE_SECONDS``). All keys
are optional; invalid or missing values fall back to the defaults below
(which mirror ``kernel.policy.LoopPolicy`` / ``llm.policy.RetryPolicy``
defaults).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lamtools_core.config.root import core_config_file
from lamtools_core.llm.policy import DEFAULT_DELAY_SEQUENCE_SECONDS, RetryPolicy
from lamtools_core.llm.profiles import load_jsonc

MODEL_RETRY_FILENAME = "model_retry.jsonc"

# Mirrors the current hard-coded defaults (kernel/policy.py + llm/policy.py).
# The default rhythm 1,1,2,5,5 with a tail value of 5s is the sane baseline;
# the former 0.5s x 100 attempts was a stopgap for a flaky provider.
DEFAULT_MODEL_RETRY_CONFIG: dict[str, Any] = {
    "retry_delays_seconds": list(DEFAULT_DELAY_SEQUENCE_SECONDS),
    "model_retries": 10,
    "model_timeout_seconds": 360,
    "model_stream_idle_timeout_seconds": 120,
    "empty_response_retries": 3,
    "jitter": True,
}

DEFAULT_MODEL_RETRY_JSONC = """\
// 模型请求重试配置（model_retry.jsonc）
// 全部字段可选，缺省用代码内默认值；修改后下个回合生效，无需重启。
//
// retry_delays_seconds：第 i 个元素 = 第 i 次重试前的等待秒数；
//   超出数组长度后一律使用最后一个值作为固定间隔。
//   留空 [] 表示使用默认节奏 1,1,2,5,5（5s 封顶）。
//   默认节奏：快速重试两次后逐步放慢，适合一般 provider；
//   频繁瞬时失败的服务（如讯飞）可显式配置短间隔 + 大次数。
// model_retries：最大尝试次数（含首次）。
// model_timeout_seconds：单次尝试超时（秒）。
// model_stream_idle_timeout_seconds：流式空闲超时（秒），null 表示禁用。
// empty_response_retries：空响应重试次数。
// jitter：每次等待加 0.5x~1.5x 随机抖动。
{
  "retry_delays_seconds": [1, 1, 2, 5, 5],
  "model_retries": 10,
  "model_timeout_seconds": 360,
  "model_stream_idle_timeout_seconds": 120,
  "empty_response_retries": 3,
  "jitter": true
}
"""


def model_retry_path() -> Path:
    """Return the model_retry.jsonc path (unified config directory)."""
    return core_config_file(MODEL_RETRY_FILENAME)


def _as_float_list(value: Any) -> list[float]:
    if not isinstance(value, list):
        return []
    result: list[float] = []
    for item in value:
        try:
            number = float(item)
        except (TypeError, ValueError):
            continue
        if number >= 0:
            result.append(number)
    return result


def _coerce(config: dict[str, Any]) -> dict[str, Any]:
    """Validate raw values and fall back to defaults for invalid keys."""
    raw = config if isinstance(config, dict) else {}
    out = dict(DEFAULT_MODEL_RETRY_CONFIG)
    delays = _as_float_list(raw.get("retry_delays_seconds"))
    if delays:
        out["retry_delays_seconds"] = delays
    try:
        retries = int(raw["model_retries"])
        if retries >= 1:
            out["model_retries"] = retries
    except (KeyError, TypeError, ValueError):
        pass
    try:
        timeout = float(raw["model_timeout_seconds"])
        if timeout > 0:
            out["model_timeout_seconds"] = timeout
    except (KeyError, TypeError, ValueError):
        pass
    idle_key = "model_stream_idle_timeout_seconds"
    if idle_key in raw:
        idle = raw[idle_key]
        if idle is None:
            out[idle_key] = None
        else:
            try:
                idle_seconds = float(idle)
                if idle_seconds > 0:
                    out[idle_key] = idle_seconds
            except (TypeError, ValueError):
                pass
    try:
        empty_retries = int(raw["empty_response_retries"])
        if empty_retries >= 0:
            out["empty_response_retries"] = empty_retries
    except (KeyError, TypeError, ValueError):
        pass
    if isinstance(raw.get("jitter"), bool):
        out["jitter"] = raw["jitter"]
    return out


def load_model_retry_config(path: Path | None = None) -> dict[str, Any]:
    """Load and validate model_retry.jsonc; missing/invalid input falls back to defaults."""
    target = path or model_retry_path()
    try:
        data = load_jsonc(target)
    except (OSError, ValueError):
        data = {}
    return _coerce(data)


def loop_policy_overrides(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the ``kernel.policy.LoopPolicy`` subset of a retry config."""
    merged = config if config is not None else load_model_retry_config()
    return {
        "model_retries": merged["model_retries"],
        "model_timeout_seconds": merged["model_timeout_seconds"],
        "model_stream_idle_timeout_seconds": merged["model_stream_idle_timeout_seconds"],
        "empty_response_retries": merged["empty_response_retries"],
    }


def retry_policy_from_config(config: dict[str, Any] | None = None) -> RetryPolicy:
    """Build the transport ``RetryPolicy`` (explicit delay sequence + jitter)."""
    merged = config if config is not None else load_model_retry_config()
    return RetryPolicy(
        delay_sequence_seconds=tuple(merged["retry_delays_seconds"]),
        jitter=bool(merged["jitter"]),
    )


__all__ = [
    "DEFAULT_MODEL_RETRY_CONFIG",
    "DEFAULT_MODEL_RETRY_JSONC",
    "MODEL_RETRY_FILENAME",
    "load_model_retry_config",
    "loop_policy_overrides",
    "model_retry_path",
    "retry_policy_from_config",
]
