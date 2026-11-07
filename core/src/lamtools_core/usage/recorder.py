"""Bridge between the LLM client and the usage ledger.

Kept as a separate module so the HTTP client stays free of ledger/import-time
side effects and tests can monkeypatch one function.
"""

from __future__ import annotations

from typing import Any

from .ledger import record_model_call


def record_llm_call(config: Any, usage: Any, *, session_id: str = "") -> None:
    """Record one completed model call for ``config``.

    ``config`` is an :class:`~lamtools_core.llm.http_client.LLMConfig`; only its
    identity fields are read so this module never needs to import the LLM
    package (which would create a cycle at client import time).
    """
    model_record_id = str(getattr(config, "model_record_id", "") or "").strip()
    if not model_record_id:
        return
    prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0) if usage is not None else 0
    completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0) if usage is not None else 0
    cached_tokens = int(getattr(usage, "cached_tokens", 0) or 0) if usage is not None else 0
    record_model_call(
        model_record_id=model_record_id,
        model_id=str(getattr(config, "model_id", "") or ""),
        provider_id=str(getattr(config, "provider_id", "") or ""),
        provider_name=str(getattr(config, "provider_name", "") or ""),
        session_id=session_id,
        input_tokens=prompt_tokens,
        output_tokens=completion_tokens,
        cached_tokens=cached_tokens,
        usage_available=usage is not None,
    )


__all__ = ["record_llm_call"]
