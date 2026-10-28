"""HTTP model client shared by desktop runtime and command-line execution."""
from __future__ import annotations

import copy
import json
import uuid
from dataclasses import dataclass, field, replace
from typing import Any
from urllib.parse import urlsplit

import httpx

from lamtools_core.config.network import httpx_client_kwargs
from lamtools_core.llm import ChatMessage, LLMRequest, LLMResponse, LLMStreamEvent, LLMToolCall, normalize_usage
from lamtools_core.llm.forensics import recorded_request, record_id, drain_recording
from lamtools_core.llm.reasoning import reasoning_level_from_legacy
from lamtools_core.llm.session_affinity import provider_session_affinity
from lamtools_core.llm.profiles import (
    build_profiled_anthropic_request,
    build_profiled_gemini_request,
    build_profiled_openai_request,
    build_profiled_responses_request,
    normalize_anthropic_response_with_profile,
    normalize_gemini_response_with_profile,
    normalize_gemini_stream_event,
    normalize_response_with_profile,
    normalize_responses_response_with_profile,
    normalize_responses_stream_event,
    normalize_stream_chunk_with_profile,
    finalize_provider_stream_state,
    update_provider_stream_state,
)

# user:“审查后端大文件并拆分”+(按职责独立维护实现，原模块保留导入入口以兼容现有调用。)


@dataclass(frozen=True)
class LLMConfig:
    provider_name: str
    provider_api_type: str
    base_url: str
    api_key: str
    model_record_id: str
    model_id: str
    display_name: str
    context_window: int = 0
    max_output_tokens: int = 4096
    temperature: float = 0.2
    thinking_supported: bool = False
    thinking_budget: int = 10000
    reasoning_effort: str = ""
    capability: str = ""  # "text" | "multimodal" | "" (resolved at request time)
    provider_extra: dict[str, Any] = field(default_factory=dict)
    model_extra: dict[str, Any] = field(default_factory=dict)
    notes: str = ""


def _messages_with_model_notes(
    messages: list[ChatMessage],
    notes: str,
) -> list[ChatMessage]:
    """Return a non-mutating request message list with model notes in system context."""

    normalized = str(notes or "").strip()
    if not normalized:
        return messages

    note_block = f"Current model notes: {normalized}"
    system_index = next(
        (index for index, message in enumerate(messages) if message.role == "system"),
        None,
    )
    if system_index is None:
        return [ChatMessage(role="system", content=note_block), *messages]

    system_message = messages[system_index]
    content = system_message.content
    if isinstance(content, str):
        if note_block in content:
            return messages
        separator = "" if not content or content.endswith("\n") else "\n"
        merged_content: str | list[dict[str, Any]] = f"{content}{separator}{note_block}"
    else:
        if any(
            isinstance(part, dict)
            and isinstance(part.get("text"), str)
            and note_block in part["text"]
            for part in content
        ):
            return messages
        merged_content = [*content, {"type": "text", "text": note_block}]

    updated = list(messages)
    updated[system_index] = replace(system_message, content=merged_content)
    return updated


def _parse_retry_after(value: object) -> float | None:
    """Parse a Retry-After header (seconds or HTTP-date) into seconds."""
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        pass
    try:
        from email.utils import parsedate_to_datetime
        import datetime

        when = parsedate_to_datetime(str(value))
        now = datetime.datetime.now(when.tzinfo)
        return max(0.0, (when - now).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return None


def _http_provider_error(
    status_code: int,
    text: str,
    headers: object,
    *,
    provider_name: str = "",
    base_url: str = "",
    model: str = "",
    auth_scheme: str = "",
) -> Exception:
    """Build a structured provider error so retry classification can key on
    the status code instead of message text (audit 10 S2: 401/403/400 were
    classified "retryable" and retried ~10 times).

    The message also names the provider / address / model that failed: a bare
    ``LLM API error 403`` left the user guessing which of several providers
    was rejecting them (the upstream body alone carries no local identity).
    """
    from lamtools_core.kernel.errors import LLMProviderError, RateLimitError

    who = " ".join(
        part
        for part in (
            f"provider={provider_name}" if provider_name else "",
            f"base_url={base_url}" if base_url else "",
            f"model={model}" if model else "",
            f"auth={auth_scheme}" if auth_scheme else "",
        )
        if part
    )
    message = f"LLM API error {status_code}"
    if who:
        message = f"{message} ({who})"
    message = f"{message}: {text[:300]}"
    if status_code in (401, 403):
        message = (
            f"{message} — 该供应商的密钥/协议可能与该地址不匹配，请检查认证方式"
            "（例如该地址需要 Anthropic 的 x-api-key，却按 OpenAI 的 Bearer 发送）"
        )
    if status_code == 429:
        retry_after = _parse_retry_after(getattr(headers, "get", lambda _k: None)("retry-after"))
        return RateLimitError(message, retry_after=retry_after)
    return LLMProviderError(message, status_code=status_code)


def _normalize_anthropic_stream_event(
    event: dict[str, Any],
    profile: dict[str, Any],
) -> LLMStreamEvent | None:
    """Normalize Anthropic SSE data events into Core stream events."""
    del profile
    event_type = str(event.get("type") or "")
    if event_type == "error":
        error = event.get("error")
        message = error.get("message") if isinstance(error, dict) else error
        return LLMStreamEvent(kind="error", error=str(message or "Unknown error"), raw=event)

    if event_type == "content_block_start":
        block = event.get("content_block") if isinstance(event.get("content_block"), dict) else {}
        if block.get("type") == "tool_use":
            return LLMStreamEvent(
                kind="tool_call_delta",
                raw=event,
                metadata={"tool_calls_delta": [{
                    "index": int(event.get("index") or 0),
                    "id": str(block.get("id") or ""),
                    "type": "function",
                    "function": {"name": str(block.get("name") or "")},
                }]},
            )
        return None

    if event_type == "content_block_delta":
        delta = event.get("delta") if isinstance(event.get("delta"), dict) else {}
        delta_type = str(delta.get("type") or "")
        if delta_type == "thinking_delta":
            content = delta.get("thinking") or ""
            return LLMStreamEvent(kind="thinking_delta", content=str(content), raw=event) if content else None
        if delta_type == "signature_delta":
            # The signature is opaque provider state required on the next
            # Anthropic request; it is not user-visible reasoning text.
            return None
        if delta_type == "text_delta":
            content = delta.get("text") or ""
            return LLMStreamEvent(kind="content_delta", content=str(content), raw=event) if content else None
        if delta_type == "input_json_delta":
            partial = str(delta.get("partial_json") or "")
            if not partial:
                return None
            return LLMStreamEvent(
                kind="tool_call_delta",
                raw=event,
                metadata={"tool_calls_delta": [{
                    "index": int(event.get("index") or 0),
                    "function": {"arguments": partial},
                }]},
            )
        return None

    if event_type == "message_delta":
        usage = normalize_usage(event.get("usage"))
        delta = event.get("delta") if isinstance(event.get("delta"), dict) else {}
        stop_reason = str(delta.get("stop_reason") or "")
        if stop_reason or usage is not None:
            return LLMStreamEvent(
                kind="finish",
                finish_reason=stop_reason or "stop",
                usage=usage,
                raw=event,
            )
    if event_type == "message_start":
        message = event.get("message") if isinstance(event.get("message"), dict) else {}
        usage = normalize_usage(message.get("usage"))
        return LLMStreamEvent(kind="usage", usage=usage, raw=event) if usage is not None else None
    return None


class CoreHttpLLMClient:
    def __init__(
        self,
        *,
        config: LLMConfig,
        adapter_profile: dict[str, Any],
        thinking_enabled: bool,
        thinking_budget: int,
        reasoning_effort: str = "",
        reasoning_level: str = "",
        max_tokens: int,
        temperature: float,
    ) -> None:
        self.config = config
        self.adapter_profile = adapter_profile
        self.thinking_enabled = bool(thinking_enabled) and bool(config.thinking_supported)
        self.thinking_budget = thinking_budget
        self.reasoning_effort = reasoning_effort
        self.reasoning_level = (
            reasoning_level_from_legacy(
                reasoning_level=reasoning_level,
                thinking_enabled=self.thinking_enabled,
                reasoning_effort=reasoning_effort,
                fallback="high" if self.thinking_enabled else "off",
            )
            if config.thinking_supported
            else "off"
        )
        self.max_tokens = max_tokens
        self.temperature = temperature

    async def complete(self, request: LLMRequest) -> LLMResponse:
        prepared = self._request_with_defaults(request)
        assembled = self._assemble_request(prepared, stream=False)
        endpoint = f"{self.config.base_url.rstrip('/')}{assembled['endpoint']}"
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(360.0, connect=30.0),
            **httpx_client_kwargs(endpoint),
        ) as client:
            async with recorded_request(
                client, "POST", endpoint, context=self._forensic_context(prepared),
                json=assembled["payload"], headers=self._headers(prepared),
            ) as response:
                pass
        if response.status_code >= 400:
            raise self._provider_error(response.status_code, response.text[:300], response)
        normalized = self._normalize_response(response.json(), model=prepared.model)
        return LLMResponse(
            content=str(normalized.get("content") or ""),
            thinking=str(normalized.get("thinking") or ""),
            tool_calls=_llm_tool_calls_from_raw(normalized.get("tool_calls")),
            usage=normalize_usage(normalized.get("usage")),
            finish_reason=str(normalized.get("finish_reason") or "stop"),
            raw=None,
            metadata={"cache_diagnostic_route": {**self._cache_diagnostic_route(), "forensic_record_id": record_id(response)}},
            provider_state=normalized.get("provider_state"),
        )

    async def stream(self, request: LLMRequest):
        prepared = self._request_with_defaults(request)
        assembled = self._assemble_request(prepared, stream=True)
        provider_state: Any = None
        protocol = self._protocol()
        endpoint = f"{self.config.base_url.rstrip('/')}{assembled['endpoint']}"
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(360.0, connect=30.0),
            **httpx_client_kwargs(endpoint),
        ) as client:
            async with recorded_request(
                client, "POST", endpoint, stream=True, context=self._forensic_context(prepared),
                json=assembled["payload"],
                headers=self._headers(prepared),
            ) as response:
                if response.status_code >= 400:
                    text = await response.aread()
                    raise self._provider_error(
                        response.status_code,
                        text.decode("utf-8", errors="replace")[:300],
                        response,
                    )
                route = {**self._cache_diagnostic_route(), "forensic_record_id": record_id(response)}
                terminal_event = None
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    # SSE permits either ``data:value`` or ``data: value``;
                    # strip at most the single optional separator space.
                    data = line[5:]
                    if data.startswith(" "):
                        data = data[1:]
                    if data == "[DONE]":
                        terminal_event = LLMStreamEvent(
                            kind="done",
                            metadata={
                                "finish_reason": "stop",
                                "cache_diagnostic_route": route,
                            },
                            provider_state=finalize_provider_stream_state(provider_state),
                        )
                        await drain_recording(response)
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    provider_state = update_provider_stream_state(
                        provider_state,
                        chunk,
                        profile=self.adapter_profile,
                        protocol=protocol,
                        model=prepared.model,
                    )
                    event = self._normalize_stream_event(chunk)
                    if event is not None:
                        metadata = dict(event.metadata) if isinstance(event.metadata, dict) else {}
                        if event.kind in {"usage", "finish", "done"} or event.usage is not None:
                            metadata["cache_diagnostic_route"] = route
                        event = replace(
                            event,
                            metadata=metadata,
                            provider_state=copy.deepcopy(provider_state),
                        )
                        if event.kind == "done" and record_id(response) is not None:
                            terminal_event = event
                            await drain_recording(response)
                            break
                        else:
                            yield event
                if terminal_event is not None:
                    yield terminal_event

    def _forensic_context(self, request: LLMRequest) -> dict[str, Any]:
        metadata = request.metadata
        return {
            "session_id": metadata.get("_runtime_session_id"),
            "run_id": metadata.get("_runtime_run_id"),
            "step": metadata.get("_runtime_step"),
            "retry_index": metadata.get("_forensic_retry_index", 0),
            "model": request.model, "provider": self.config.provider_name,
            "protocol": self._protocol(),
        }

    def _protocol(self) -> str:
        protocol = str(self.adapter_profile.get("protocol") or "").strip().lower()
        if protocol:
            return protocol
        return "anthropic-messages" if self.config.provider_api_type.strip().lower() == "anthropic" else "openai-chat-completions"

    def _cache_diagnostic_route(self) -> dict[str, Any]:
        return {
            "provider": str(self.config.provider_name or ""),
            "protocol": self._protocol(),
            "model": str(self.config.model_id or ""),
            "endpoint_host": str(urlsplit(self.config.base_url).hostname or ""),
            "session_affinity_header": self._uses_opencode_session_header(),
        }

    def _assemble_request(self, request: LLMRequest, *, stream: bool) -> dict[str, Any]:
        protocol = self._protocol()
        kwargs = {
            "stream": stream,
            "thinking_enabled": self.thinking_enabled,
            "thinking_budget": self.thinking_budget,
            "reasoning_effort": self.reasoning_effort,
            "reasoning_level": self.reasoning_level,
            "capability": self.config.capability,
        }
        if protocol == "anthropic-messages":
            return build_profiled_anthropic_request(
                [message.to_dict() for message in request.messages],
                self.adapter_profile,
                model=request.model,
                max_tokens=int(request.max_tokens or self.max_tokens),
                temperature=float(request.temperature if request.temperature is not None else self.temperature),
                stream=stream,
                top_p=request.top_p,
                tools=request.tools,
                tool_choice=request.tool_choice,
                thinking_enabled=self.thinking_enabled,
                thinking_budget=self.thinking_budget,
                reasoning_level=self.reasoning_level,
                capability=self.config.capability,
            )
        if protocol in {"gemini", "gemini-generative-language"}:
            return build_profiled_gemini_request(request, self.adapter_profile, **kwargs)
        if protocol in {"openai-responses", "responses"}:
            return build_profiled_responses_request(request, self.adapter_profile, **kwargs)
        return build_profiled_openai_request(request, self.adapter_profile, **kwargs)

    def _normalize_response(self, response: dict[str, Any], *, model: str = "") -> dict[str, Any]:
        protocol = self._protocol()
        if protocol == "anthropic-messages":
            return normalize_anthropic_response_with_profile(response, self.adapter_profile, model=model)
        if protocol in {"gemini", "gemini-generative-language"}:
            return normalize_gemini_response_with_profile(response, self.adapter_profile, model=model)
        if protocol in {"openai-responses", "responses"}:
            return normalize_responses_response_with_profile(response, self.adapter_profile, model=model)
        return normalize_response_with_profile(response, self.adapter_profile, model=model)

    def _normalize_stream_event(self, chunk: dict[str, Any]) -> LLMStreamEvent | None:
        protocol = self._protocol()
        if protocol == "anthropic-messages":
            return _normalize_anthropic_stream_event(chunk, self.adapter_profile)
        if protocol in {"gemini", "gemini-generative-language"}:
            return normalize_gemini_stream_event(chunk, self.adapter_profile)
        if protocol in {"openai-responses", "responses"}:
            return normalize_responses_stream_event(chunk, self.adapter_profile)
        return normalize_stream_chunk_with_profile(chunk, self.adapter_profile)

    def _request_with_defaults(self, request: LLMRequest) -> LLMRequest:
        return LLMRequest(
            messages=_messages_with_model_notes(request.messages, self.config.notes),
            model=request.model or self.config.model_id,
            temperature=request.temperature if request.temperature is not None else self.temperature,
            max_tokens=request.max_tokens if request.max_tokens is not None else self.max_tokens,
            top_p=request.top_p,
            tools=request.tools,
            tool_choice=request.tool_choice,
            parallel_tool_calls=request.parallel_tool_calls,
            response_format=request.response_format,
            timeout=request.timeout,
            metadata=dict(request.metadata),
        )

    def _auth_scheme(self) -> str:
        """Name the auth header shape used for this provider.

        The mapping is protocol-driven (there is no per-provider ``auth``
        override today): Anthropic-compatible endpoints take ``x-api-key``,
        Gemini takes ``x-goog-api-key``, everything else takes a Bearer token.
        Surfacing the chosen scheme in an error makes a provider configured
        against the wrong protocol (a 401/403 whose body says "authentication
        failed") diagnosable instead of opaque.
        """
        protocol = self._protocol()
        auth = str(self.adapter_profile.get("auth") or protocol).strip().lower()
        if protocol in {"gemini", "gemini-generative-language"} or auth in {
            "gemini",
            "google-api-key",
            "x-goog-api-key",
        }:
            return "x-goog-api-key"
        if auth in {"anthropic", "anthropic-messages", "x-api-key"}:
            return "x-api-key"
        return "Bearer"

    def _uses_opencode_session_header(self) -> bool:
        """OpenCode inference endpoints use a stable session for routing/cache affinity."""
        provider_name = str(self.config.provider_name or "").strip().casefold()
        parsed = urlsplit(self.config.base_url)
        host = str(parsed.hostname or "").casefold()
        path = str(parsed.path or "").rstrip("/").casefold()
        return provider_name.startswith("opencode") or (
            host == "opencode.ai"
            and (path.startswith("/inference/") or path.startswith("/zen/"))
        )

    def _headers(self, request: LLMRequest | None = None) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        protocol = self._protocol()
        auth = str(self.adapter_profile.get("auth") or protocol).strip().lower()
        if protocol in {"gemini", "gemini-generative-language"} or auth in {
            "gemini",
            "google-api-key",
            "x-goog-api-key",
        }:
            headers["x-goog-api-key"] = self._validate_api_key()
        elif auth in {"anthropic", "anthropic-messages", "x-api-key"}:
            headers["x-api-key"] = self._validate_api_key()
            headers["anthropic-version"] = str(self.adapter_profile.get("anthropic_version") or "2023-06-01")
        else:
            headers["Authorization"] = f"Bearer {self._validate_api_key()}"
            if protocol == "anthropic-messages":
                headers["anthropic-version"] = str(self.adapter_profile.get("anthropic_version") or "2023-06-01")
        if self._uses_opencode_session_header():
            metadata = request.metadata if request is not None and isinstance(request.metadata, dict) else {}
            runtime_session_id = ""
            for key in ("_runtime_session_id", "session_id", "thread_id"):
                value = metadata.get(key)
                if isinstance(value, str) and value.strip():
                    runtime_session_id = value.strip()
                    break
            # user:“子代理和主代理用一个 id”+(OpenCode 按会话做路由与提示词缓存亲和；
            # 子会话沿用父会话 id，避免主/子代理被分到不同缓存桶。)
            session_id = provider_session_affinity(runtime_session_id, metadata)
            if not session_id:
                raise ValueError(
                    "OpenCode API requests require a stable conversation session ID "
                    "in request metadata (_runtime_session_id, session_id, thread_id, "
                    "or parent_session_id)."
                )
            headers["x-opencode-session"] = session_id
        return headers

    def _validate_api_key(self) -> str:
        """Return the api key, or fail locally with a clear identity.

        A key carrying non-ASCII characters (typically a Chinese label pasted
        along with it) cannot be encoded into an HTTP header. Without this
        check the failure surfaces as a bare ``'ascii' codec can't encode``
        with no provider/model, which reads like a transient network problem.
        """
        from lamtools_core.config.provider_store import ApiKeyValidationError, validate_api_key_text

        try:
            return validate_api_key_text(self.config.api_key)
        except ApiKeyValidationError as exc:
            raise ApiKeyValidationError(
                f"{exc} — provider={self.config.provider_name} "
                f"model={self.config.model_id}"
            ) from exc

    def _provider_error(self, status_code: int, text: str, response: object) -> Exception:
        return _http_provider_error(
            status_code,
            text,
            getattr(response, "headers", None) or {},
            provider_name=self.config.provider_name,
            base_url=self.config.base_url,
            model=self.config.model_id,
            auth_scheme=self._auth_scheme(),
        )


def _llm_tool_calls_from_raw(raw_tool_calls: Any) -> list[LLMToolCall]:
    calls: list[LLMToolCall] = []
    if not isinstance(raw_tool_calls, list):
        return calls
    for item in raw_tool_calls:
        if not isinstance(item, dict):
            continue
        fn = item.get("function") if isinstance(item.get("function"), dict) else {}
        args: Any = fn.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        calls.append(
            LLMToolCall(
                id=str(item.get("id") or uuid.uuid4().hex),
                name=str(fn.get("name") or ""),
                arguments=args if isinstance(args, dict) else {},
                raw=item,
            )
        )
    return calls
