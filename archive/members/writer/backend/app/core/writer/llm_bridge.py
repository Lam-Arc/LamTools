from __future__ import annotations

import json
import inspect
import uuid
from typing import Any

from lamtools_core.llm import (
    ChatMessage,
    LLMClient,
    LLMRequest,
    LLMResponse,
    LLMStreamEvent,
    LLMToolCall,
    build_openai_payload,
    merge_tool_call_deltas,
    normalize_usage,
    resolve_tool_calls,
)
from lamtools_core.llm.profiles import build_profiled_openai_request, normalize_stream_chunk_with_profile

from app.core.writer.runtime_resources import stream_http_client
from app.utils.llm_adapter_profiles import resolve_adapter_profile


class WriterLLMClientAdapter:
    """Adapt a Writer-style LLM client to the Core LLMClient protocol."""

    def __init__(
        self,
        writer_client: Any | None = None,
        core_client: LLMClient | None = None,
    ) -> None:
        if core_client is not None:
            self._core = core_client
        elif writer_client is not None:
            self._core = _WriterToCoreBridge(writer_client)
        else:
            raise ValueError(
                "Either writer_client or core_client must be provided"
            )

    async def complete(self, request: LLMRequest) -> LLMResponse:
        return await self._core.complete(request)

    def stream(self, request: LLMRequest):
        return self._core.stream(request)


class _WriterToCoreBridge:
    """Bridge Writer llm_client.chat_full / stream to Core LLMClient."""

    def __init__(self, writer_client: Any) -> None:
        self._writer = writer_client

    @staticmethod
    def _convert_messages(request: LLMRequest) -> list[dict[str, Any]]:
        return build_openai_payload(LLMRequest(messages=request.messages, model=request.model))["messages"]

    async def complete(self, request: LLMRequest) -> LLMResponse:
        messages = self._convert_messages(request)
        tools = request.tools if request.tools else None
        chat_kwargs: dict[str, Any] = {"tools": tools}
        signature = inspect.signature(self._writer.chat_full)
        supports_kwargs = any(param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values())
        if supports_kwargs or "temperature" in signature.parameters:
            chat_kwargs["temperature"] = request.temperature
        if supports_kwargs or "max_tokens" in signature.parameters:
            chat_kwargs["max_tokens"] = request.max_tokens
        writer_response = await self._writer.chat_full(messages, **chat_kwargs)

        tool_calls: list[LLMToolCall] = []
        if writer_response.tool_calls:
            for tc in writer_response.tool_calls:
                if isinstance(tc, dict):
                    tc_id = tc.get("id", str(uuid.uuid4()))
                    func = tc.get("function", {})
                    tc_name = func.get("name", str(tc)) if isinstance(func, dict) else str(tc)
                    tc_args = func.get("arguments", {}) if isinstance(func, dict) else {}
                    if isinstance(tc_args, str):
                        try:
                            tc_args = json.loads(tc_args)
                        except (json.JSONDecodeError, TypeError):
                            tc_args = {}
                else:
                    tc_id = tc.id if hasattr(tc, "id") else str(uuid.uuid4())
                    tc_name = tc.name if hasattr(tc, "name") else str(tc)
                    tc_args = tc.arguments if hasattr(tc, "arguments") else {}

                tool_calls.append(
                    LLMToolCall(
                        id=tc_id,
                        name=tc_name,
                        arguments=tc_args if isinstance(tc_args, dict) else {},
                    )
                )

        usage = normalize_usage(getattr(writer_response, "usage", None))

        return LLMResponse(
            content=writer_response.content or "",
            thinking=getattr(writer_response, "thinking", "") or "",
            tool_calls=tool_calls,
            usage=usage,
            finish_reason=getattr(writer_response, "finish_reason", "stop") or "stop",
        )

    async def stream(self, request: LLMRequest):
        w = self._writer
        if getattr(w, "api_type", "openai") != "openai":
            raise NotImplementedError(
                f"Streaming not supported for api_type={getattr(w, 'api_type', '?')}"
            )

        tools = request.tools if request.tools else None
        adapter_profile = getattr(w, "adapter_profile", None) or resolve_adapter_profile(
            api_type=getattr(w, "api_type", "openai"),
            base_url=w.base_url,
        )

        headers = {
            "Authorization": f"Bearer {w.api_key}",
            "Content-Type": "application/json",
        }
        assembled = build_profiled_openai_request(
            LLMRequest(
                messages=request.messages,
                model=request.model or w.model_id,
                temperature=request.temperature if request.temperature is not None else w.temperature,
                max_tokens=request.max_tokens if request.max_tokens is not None else w.max_tokens,
                top_p=request.top_p,
                tools=tools or [],
                tool_choice=request.tool_choice,
                parallel_tool_calls=request.parallel_tool_calls,
                response_format=request.response_format,
            ),
            adapter_profile,
            stream=True,
            thinking_enabled=w.thinking_enabled,
            thinking_budget=w.thinking_budget,
        )
        url = f"{w.base_url}{assembled['endpoint']}"
        payload = assembled["payload"]

        client = await stream_http_client()
        async with client.stream("POST", url, json=payload, headers=headers) as resp:
            if resp.status_code != 200:
                text = await resp.aread()
                raise RuntimeError(
                    f"LLM API error {resp.status_code}: {text.decode('utf-8', errors='replace')[:300]}"
                )

            accumulated_tool_calls: dict[int, dict[str, Any]] = {}
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                event = normalize_stream_chunk_with_profile(chunk, adapter_profile)
                if event is None:
                    continue

                if event.kind == "tool_call_delta":
                    tc_delta = event.metadata.get("tool_calls_delta")
                    if tc_delta:
                        accumulated_tool_calls = merge_tool_call_deltas(
                            accumulated_tool_calls, {"tool_calls": tc_delta}
                        )
                    yield event
                    continue

                if event.kind == "done":
                    tool_calls = resolve_tool_calls(accumulated_tool_calls)
                    yield LLMStreamEvent(
                        kind="done",
                        tool_calls=tool_calls,
                        usage=event.usage,
                        metadata={"finish_reason": event.metadata.get("finish_reason", "stop")},
                    )
                    return

                yield event

            tool_calls = resolve_tool_calls(accumulated_tool_calls)
            yield LLMStreamEvent(
                kind="done",
                tool_calls=tool_calls,
                metadata={"finish_reason": "stop"},
            )


__all__ = ["WriterLLMClientAdapter"]
