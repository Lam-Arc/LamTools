from __future__ import annotations

"""LLM client for Writer.

Supports two API types via Xunfei MaaS:
1. OpenAI-compatible (/v2/chat/completions)
2. Anthropic-compatible (/anthropic/v1/messages)

Thinking mode: when enabled, sends thinking budget parameter
and extracts thinking content from the response.
"""
import json
import logging
from typing import Any, AsyncGenerator

import aiohttp

from lamtools_core.llm import LLMRequest, build_openai_payload, chat_message_from_openai, merge_system_messages
from lamtools_core.llm.profiles import (
    build_profiled_anthropic_request,
    build_profiled_openai_request,
    normalize_anthropic_response_with_profile,
    normalize_response_with_profile,
    normalize_stream_chunk_with_profile,
)
from lamtools_core.tokens import estimate_text_tokens
from app.utils.llm_adapter_profiles import resolve_adapter_profile

logger = logging.getLogger(__name__)

# ── Module-level connection pool ──
# Reuse a single aiohttp.ClientSession across all LLM calls
# to avoid creating new TCP connections per request.
# Closed via close_http_session() on app shutdown.
_http_session: aiohttp.ClientSession | None = None
_http_session_lock = None  # lazy import asyncio.Lock


def _get_http_session() -> aiohttp.ClientSession:
    """Lazy-init a shared aiohttp session with connection pooling."""
    global _http_session, _http_session_lock
    if _http_session is None or _http_session.closed:
        import asyncio
        if _http_session_lock is None:
            _http_session_lock = asyncio.Lock()
        # Use a connector with pooled connections
        connector = aiohttp.TCPConnector(
            limit=10,           # Max total connections
            limit_per_host=5,   # Max per host
            ttl_dns_cache=300,  # DNS cache TTL
            force_close=False,  # Allow keep-alive
        )
        timeout = aiohttp.ClientTimeout(total=1800, connect=30)
        _http_session = aiohttp.ClientSession(connector=connector, timeout=timeout)
    return _http_session


async def close_http_session() -> None:
    """Close the shared HTTP session. Called on app shutdown."""
    global _http_session
    if _http_session and not _http_session.closed:
        await _http_session.close()
        _http_session = None


class LLMResponse:
    """Parsed LLM response with thinking and tool call support."""

    content: str
    thinking: str
    usage: dict[str, int] | None
    tool_calls: list[dict] | None
    finish_reason: str

    def __init__(
        self,
        content: str = "",
        thinking: str = "",
        usage: dict | None = None,
        tool_calls: list[dict] | None = None,
        finish_reason: str = "stop",
    ):
        self.content = content
        self.thinking = thinking
        self.usage = usage
        self.tool_calls = tool_calls
        self.finish_reason = finish_reason


class LLMClient:
    """LLM client supporting OpenAI and Anthropic API types.

    Configured via Settings:
    - llm_api_type: "openai" or "anthropic"
    - llm_base_url: base URL for the API
    - llm_api_key: API key (format: "key:secret" for Anthropic)
    - llm_model: model ID
    - llm_thinking_enabled: enable thinking/extended reasoning
    - llm_thinking_budget: token budget for thinking
    - llm_max_tokens: max output tokens
    - llm_temperature: sampling temperature
    """

    def __init__(
        self,
        base_url: str = "",
        api_key: str = "",
        model_id: str = "astron-code-latest",
        api_type: str = "openai",
        thinking_enabled: bool = True,
        thinking_budget: int = 10000,
        max_tokens: int = 16384,
        temperature: float = 1.0,
        top_p: float = 0.95,
        context_window: int = 200000,
        adapter_profile: dict[str, Any] | None = None,
        provider_extra: dict[str, Any] | None = None,
        model_extra: dict[str, Any] | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_id = model_id
        self.api_type = api_type
        self.thinking_enabled = thinking_enabled
        self.thinking_budget = thinking_budget
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.top_p = top_p
        self.context_window = context_window
        self.adapter_profile = adapter_profile or resolve_adapter_profile(
            api_type=api_type,
            base_url=self.base_url,
            provider_extra=provider_extra,
            model_extra=model_extra,
        )

    def _parse_api_key(self) -> tuple[str, str]:
        """Parse 'key:secret' format for Anthropic API."""
        if ":" in self.api_key:
            parts = self.api_key.split(":", 1)
            return parts[0], parts[1]
        return self.api_key, self.api_key

    def _openai_payload(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float,
        max_tokens: int,
        tools: list[dict] | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        return build_openai_payload(
            self._openai_request(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=tools,
            ),
            stream=stream,
        )

    def _openai_request(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float,
        max_tokens: int,
        tools: list[dict] | None = None,
    ) -> LLMRequest:
        return LLMRequest(
            messages=merge_system_messages([chat_message_from_openai(message) for message in messages or []]),
            model=self.model_id,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=self.top_p,
            tools=tools or [],
        )

    async def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Send a chat request and return response content string.

        For thinking mode, thinking content is logged but not returned.
        Use chat_full() to get both content and thinking.
        """
        response = await self.chat_full(messages, temperature, max_tokens)
        if response.thinking:
            logger.info(f"Writer thinking: {response.thinking[:200]}...")
        return response.content

    async def chat_full(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
        *,
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        """Send a chat request and return full response with thinking and tool calls."""
        temp = temperature if temperature is not None else self.temperature
        tokens = max_tokens if max_tokens is not None else self.max_tokens

        if self.api_type == "anthropic":
            return await self._chat_anthropic(messages, temp, tokens)
        else:
            return await self._chat_openai(messages, temp, tokens, tools=tools)

    async def _chat_openai(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        """OpenAI-compatible chat completions with optional tool calling."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Debug: log message count and types before sending
        msg_summary = []
        for m in messages:
            role = m.get("role", "?")
            has_tc = "tool_calls" in m
            content_len = len(m.get("content", "") or "")
            msg_summary.append(f"{role}(content={content_len},tool_calls={has_tc})")
        logger.info(f"Sending {len(messages)} messages to LLM: {msg_summary}")

        assembled = build_profiled_openai_request(
            self._openai_request(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=tools,
            ),
            self.adapter_profile,
            thinking_enabled=self.thinking_enabled,
            thinking_budget=self.thinking_budget,
        )
        url = f"{self.base_url}{assembled['endpoint']}"
        payload = assembled["payload"]

        # Debug: log message roles and sizes before sending
        msg_summary = []
        for msg in messages:
            role = msg.get("role", "?")
            content_len = len(msg.get("content", "")) if msg.get("content") else 0
            has_tc = "tool_calls" in msg
            msg_summary.append(f"{role}(content={content_len},tool_calls={has_tc})")
        logger.info(f"LLM request: {len(messages)} messages: {msg_summary}")

        # Validate payload is JSON-serializable before sending
        try:
            payload_json = json.dumps(payload, ensure_ascii=False)
            logger.info(f"Payload size: {len(payload_json)} chars")
        except (TypeError, ValueError) as e:
            logger.error(f"Payload not JSON-serializable: {e}")
            # Try to identify the problematic message
            for i, m in enumerate(messages):
                try:
                    json.dumps(m, ensure_ascii=False)
                except (TypeError, ValueError) as e2:
                    logger.error(f"Message {i} (role={m.get('role')}) not serializable: {e2}")
            raise

        session = _get_http_session()
        async with session.post(url, json=payload, headers=headers) as resp:
            if resp.status != 200:
                text = await resp.text()
                logger.error(f"LLM API error {resp.status}: {text[:500]}")
                raise RuntimeError(f"LLM API error {resp.status}: {text[:300]}")
            data = await resp.json()

        logger.debug(f"LLM response keys: {list(data.keys()) if isinstance(data, dict) else 'non-dict'}")

        normalized = normalize_response_with_profile(data, self.adapter_profile)
        content = str(normalized.get("content") or "")
        thinking = str(normalized.get("thinking") or "")
        tool_calls = normalized.get("tool_calls")
        finish_reason = str(normalized.get("finish_reason") or "stop")

        if tool_calls:
            tc_names = [tc.get("function", {}).get("name", "?") if isinstance(tc, dict) else getattr(tc, "name", "?") for tc in tool_calls]
            logger.info(f"Tool calls received: {tc_names}")

        usage = normalized.get("usage") if isinstance(normalized.get("usage"), dict) else None
        if usage:
            logger.info(
                f"LLM response: finish_reason={finish_reason}, "
                f"content_len={len(content)}, thinking_len={len(thinking)}, "
                f"tool_calls={len(tool_calls) if tool_calls else 0}, "
                f"tokens: prompt={usage.get('prompt_tokens',0)} "
                f"completion={usage.get('completion_tokens',0)} "
                f"total={usage.get('total_tokens',0)}"
            )
        else:
            logger.info(f"LLM response: finish_reason={finish_reason}, content_len={len(content)}, tool_calls={len(tool_calls) if tool_calls else 0}")
        return LLMResponse(
            content=content,
            thinking=thinking,
            usage=usage,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
        )

    async def _chat_anthropic(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> LLMResponse:
        """Anthropic-compatible messages API."""
        api_key, api_secret = self._parse_api_key()

        assembled = build_profiled_anthropic_request(
            messages,
            self.adapter_profile,
            model=self.model_id,
            max_tokens=max_tokens,
            temperature=temperature,
            thinking_enabled=self.thinking_enabled,
            thinking_budget=self.thinking_budget,
        )
        url = f"{self.base_url}{assembled['endpoint']}"
        headers = {
            "x-api-key": api_secret,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        payload = assembled["payload"]

        session = _get_http_session()
        async with session.post(url, json=payload, headers=headers) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"Anthropic API error {resp.status}: {text[:300]}")
            data = await resp.json()

        normalized = normalize_anthropic_response_with_profile(data, self.adapter_profile)
        usage = normalized.get("usage") if isinstance(normalized.get("usage"), dict) else None
        return LLMResponse(
            content=str(normalized.get("content") or ""),
            thinking=str(normalized.get("thinking") or ""),
            usage=usage,
            finish_reason=str(normalized.get("finish_reason") or "stop"),
        )

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncGenerator[tuple[str, dict | None], None]:
        """Stream a chat completion, yielding (delta_text, usage) tuples.

        Only supports OpenAI-compatible streaming for now.
        """
        temp = temperature if temperature is not None else self.temperature
        tokens = max_tokens if max_tokens is not None else self.max_tokens

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        assembled = build_profiled_openai_request(
            self._openai_request(
                messages,
                temperature=temp,
                max_tokens=tokens,
            ),
            self.adapter_profile,
            stream=True,
            thinking_enabled=self.thinking_enabled,
            thinking_budget=self.thinking_budget,
        )
        url = f"{self.base_url}{assembled['endpoint']}"
        payload = assembled["payload"]

        usage_data = None

        session = _get_http_session()
        async with session.post(url, json=payload, headers=headers) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"LLM API error {resp.status}: {text[:300]}")
            async for line in resp.content:
                line_str = line.decode("utf-8").strip()
                if not line_str or not line_str.startswith("data: "):
                    continue
                data_str = line_str[6:]
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    event = normalize_stream_chunk_with_profile(chunk, self.adapter_profile)
                    if event and event.kind == "content_delta" and event.content:
                        yield event.content, None
                    if event and event.kind == "usage" and event.usage:
                        usage_data = event.usage.to_dict()
                except json.JSONDecodeError:
                    continue

            if usage_data:
                yield "", usage_data

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Rough token estimate for context window budgeting."""
        return estimate_text_tokens(text)
