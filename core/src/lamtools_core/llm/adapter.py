"""LLM adapter protocol and OpenAI-compatible implementation.

Converts Core LLM types to/from provider-specific payloads using
provider-neutral helpers. No network dependencies — pure transformation.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Protocol, runtime_checkable

from lamtools_core.llm import (
    LLMRequest,
    LLMResponse,
    LLMStreamEvent,
)
from lamtools_core.llm.helpers import (
    build_openai_payload,
    normalize_openai_response,
    normalize_stream_chunk,
)


@runtime_checkable
class LLMAdapter(Protocol):
    """Provider adapter protocol: converts Core types to/from provider payloads.

    Each provider implementation translates between the Core universal
    types (LLMRequest, LLMResponse, LLMStreamEvent) and the provider's
    native payload format.
    """

    def build_payload(self, request: LLMRequest, *, stream: bool = False) -> dict[str, Any]:
        """Convert LLMRequest to provider-specific payload."""
        ...

    def parse_response(self, response: dict[str, Any]) -> LLMResponse:
        """Convert provider response dict to LLMResponse."""
        ...

    def parse_stream_chunk(self, chunk: dict[str, Any]) -> LLMStreamEvent | None:
        """Convert provider stream chunk to LLMStreamEvent."""
        ...

    def normalize_base_url(self, base_url: str) -> str:
        """Normalize provider base URL (handle /v1, /v2, /openai suffixes)."""
        ...


class OpenAICompatibleAdapter:
    """OpenAI-compatible adapter using Core helper functions.

    Handles URL normalization and delegates to helpers for payload
    construction and response parsing. Suitable for any OpenAI-compatible
    API (OpenAI, Azure, Mistral, local servers like Ollama/vLLM).
    """

    def __init__(self, base_url: str = "", model_id: str = "") -> None:
        self.base_url = self.normalize_base_url(base_url)
        self.model_id = model_id

    # -- LLMAdapter implementation ------------------------------------------

    def build_payload(self, request: LLMRequest, *, stream: bool = False) -> dict[str, Any]:
        """Convert LLMRequest to OpenAI-compatible payload.

        Overrides model if adapter has a default model_id and request
        model is empty.
        """
        payload = build_openai_payload(request, stream=stream)
        # Override model if request didn't specify one
        if not payload.get("model") and self.model_id:
            payload["model"] = self.model_id
        return payload

    def parse_response(self, response: dict[str, Any]) -> LLMResponse:
        """Convert OpenAI-compatible response to LLMResponse."""
        return normalize_openai_response(response)

    def parse_stream_chunk(self, chunk: dict[str, Any]) -> LLMStreamEvent | None:
        """Convert OpenAI-compatible stream chunk to LLMStreamEvent."""
        event = normalize_stream_chunk(chunk)
        # The legacy adapter API treats a provider finish chunk as the
        # terminal event.  The profile-based Core HTTP client distinguishes
        # provider ``finish`` from transport ``done`` so it can still consume
        # a following usage chunk; keep that newer distinction out of this
        # older standalone adapter contract.
        if event is not None and event.kind == "finish":
            return replace(event, kind="done")
        return event

    def normalize_base_url(self, base_url: str) -> str:
        """Normalize a provider base URL.

        Handles URLs that may or may not include API version paths.
        Strips trailing slashes.

        Examples:
            'https://api.openai.com'       → 'https://api.openai.com/v1'
            'https://api.openai.com/v1'    → 'https://api.openai.com/v1'
            'https://api.openai.com/v2/'   → 'https://api.openai.com/v2'
            'https://api.mistral.ai/v1'    → 'https://api.mistral.ai/v1'
            'https://llm.example.com/openai' → 'https://llm.example.com/openai'
        """
        url = base_url.strip().rstrip("/")

        if not url:
            return ""

        # Already has a recognized API version or path suffix
        for suffix in ("/v1", "/v2", "/openai", "/v1/chat/completions"):
            if url.endswith(suffix):
                return url

        return f"{url}/v1"


__all__ = [
    "LLMAdapter",
    "OpenAICompatibleAdapter",
]
