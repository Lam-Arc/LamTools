"""user:“继续，把 2 阶段都做完”+(公开实际模型调用、结构化流和估算，固定项目与启动代，复用现有模型/提供方)。"""
from __future__ import annotations

import asyncio
import copy
import inspect
import json
import math
from dataclasses import dataclass

from lamtools_core.llm import LLMRequest, LLMResponse, LLMStreamEvent
from lamtools_core.tokens import estimate_message_tokens, estimate_text_tokens


class LLMAccessError(RuntimeError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class TokenEstimate:
    tokens: int
    exact: bool = False
    method: str = "sunday-local-heuristic"


def _bounded(value, maximum, code):
    try:
        if len(json.dumps(value.to_dict(), ensure_ascii=False, allow_nan=False).encode("utf-8")) > maximum:
            raise ValueError
    except Exception:
        raise LLMAccessError(code, "Model protocol payload must be bounded finite JSON") from None
    result = copy.deepcopy(value)
    if hasattr(result, "raw"):
        result.raw = None
    for tool in getattr(result, "tool_calls", []):
        tool.raw = None
    return result


class PluginLLMAPI:
    def __init__(self, scope, work_root, client, models, bound_model=""):
        self._scope, self._root, self._client, self._models = scope, str(work_root), client, models
        self._bound_model = bound_model
        self._streams = set()
        self._cleanup_registered = False

    def _request(self, request):
        self._scope.check_open()
        if not isinstance(request, LLMRequest):
            raise LLMAccessError("llm/invalid-request", "Use the public LLMRequest protocol")
        value = _bounded(request, 1048576, "llm/invalid-request")
        timeout = value.timeout if value.timeout is not None else 60
        if type(timeout) not in {int, float} or not math.isfinite(timeout) or not 0 < timeout <= 300:
            raise LLMAccessError("llm/invalid-request", "Timeout must be finite and within (0, 300] seconds")
        if value.max_tokens is not None and (type(value.max_tokens) is not int or not 1 <= value.max_tokens <= 65536):
            raise LLMAccessError("llm/invalid-request", "max_tokens must be an integer within [1, 65536]")
        return value, timeout

    def _prepare(self, request, scene, ref):
        value, timeout = self._request(request)
        if self._models is None or self._client is None:
            raise LLMAccessError("llm/unavailable", "Configured model host is unavailable")
        if ref is not None and value.model and ref != value.model:
            raise LLMAccessError("llm/invalid-request", "Conflicting request model and explicit reference")
        try:
            selected = self._models.select(scene, ref=ref or value.model or None).model
        except Exception:
            raise LLMAccessError("llm/model-unavailable", "Resolve an unambiguous usable model in this scene before calling") from None
        if selected.max_output_tokens and value.max_tokens and value.max_tokens > selected.max_output_tokens:
            raise LLMAccessError("llm/invalid-request", "Requested output exceeds configured model output limit")
        client = self._client
        if getattr(client, "uses_config_routing", False):
            try:
                client = client.with_runtime_options(model_id=selected.id, work_root=self._root)
            except Exception:
                raise LLMAccessError("llm/route-unavailable", "Configured client cannot bind the requested project route") from None
            value.model = selected.id
        elif self._bound_model in {selected.id, selected.model_id}:
            value.model = selected.model_id
        else:
            raise LLMAccessError("llm/route-unavailable", "This direct client is not explicitly bound to the selected model")
        value.timeout = timeout
        return client, value, timeout

    def estimate(self, request: LLMRequest) -> TokenEstimate:
        value, _ = self._request(request)
        tokens = estimate_message_tokens([message.to_dict() for message in value.messages])
        tokens += sum(estimate_text_tokens(json.dumps(tool, ensure_ascii=False)) for tool in value.tools)
        return TokenEstimate(tokens)

    async def complete(self, request: LLMRequest, *, scene="background", ref=None) -> LLMResponse:
        self._scope.acquire()
        try:
            client, value, timeout = self._prepare(request, scene, ref)
            try:
                async with asyncio.timeout(timeout):
                    result = await client.complete(value)
                if not isinstance(result, LLMResponse):
                    raise LLMAccessError("llm/invalid-response", "Provider returned no LLMResponse")
                return _bounded(result, 8388608, "llm/invalid-response")
            except TimeoutError:
                raise LLMAccessError("llm/timeout", "Model call exceeded its deadline") from None
            except LLMAccessError:
                raise
            except Exception:
                raise LLMAccessError("llm/provider-error", "Configured model provider failed") from None
        finally:
            self._scope.release()

    def stream(self, request: LLMRequest, *, scene="background", ref=None):
        client, value, timeout = self._prepare(request, scene, ref)
        return PluginLLMStream(self, client, value, timeout)

    async def _dispose_streams(self):
        for stream in tuple(self._streams):
            await stream.aclose()


class PluginLLMStream:
    def __init__(self, api, client, request, timeout):
        self._api, self._client, self._request, self._timeout = api, client, request, timeout
        self._source = None
        self._closed = False
        self._close_task = None
        self._terminal = False
        self._bytes = 0
        self._pulling = False

    async def __aenter__(self):
        scope = self._api._scope
        scope.acquire()
        try:
            if self._source is not None or self._closed:
                raise LLMAccessError("llm/invalid-stream", "Stream context can only be entered once")
            if len(self._api._streams) >= 8:
                raise LLMAccessError("llm/busy", "At most 8 open model streams per view")
            if not self._api._cleanup_registered:
                scope.on_dispose(self._api._dispose_streams)
                self._api._cleanup_registered = True
            self._deadline = asyncio.get_running_loop().time() + self._timeout
            self._api._streams.add(self)
            async with asyncio.timeout(self._timeout):
                source = self._client.stream(self._request)
                self._source = await source if inspect.isawaitable(source) else source
            return self
        except TimeoutError:
            await self.aclose()
            raise LLMAccessError("llm/timeout", "Model stream initialization exceeded its deadline") from None
        except LLMAccessError:
            await self.aclose()
            raise
        except Exception:
            await self.aclose()
            raise LLMAccessError("llm/provider-error", "Model stream initialization failed") from None
        except BaseException:
            await self.aclose()
            raise
        finally:
            scope.release()

    def __aiter__(self):
        return self

    async def __anext__(self):
        self._api._scope.acquire()
        if self._pulling:
            self._api._scope.release()
            raise LLMAccessError("llm/busy", "Only one pending read is allowed per stream")
        self._pulling = True
        try:
            if self._closed:
                raise StopAsyncIteration
            if self._source is None:
                raise LLMAccessError("llm/invalid-stream", "Enter the stream with async with before reading")
            async with asyncio.timeout_at(self._deadline):
                event = await anext(self._source)
            if not isinstance(event, LLMStreamEvent) or event.kind == "error":
                raise LLMAccessError("llm/provider-error", "Model stream returned an error or invalid event")
            event = _bounded(event, 8388608, "llm/invalid-response")
            self._bytes += len(json.dumps(event.to_dict(), ensure_ascii=False).encode("utf-8"))
            if self._bytes > 8388608:
                raise LLMAccessError("llm/output-limit", "Stream exceeds 8 MiB protocol output limit")
            if event.kind in {"finish", "done"}:
                self._terminal = True
            return event
        except StopAsyncIteration:
            await self.aclose()
            if not self._terminal:
                raise LLMAccessError("llm/incomplete-stream", "Stream ended without a terminal event") from None
            raise
        except TimeoutError:
            await self.aclose()
            raise LLMAccessError("llm/timeout", "Model stream exceeded its total deadline") from None
        except LLMAccessError:
            await self.aclose()
            raise
        except Exception:
            await self.aclose()
            raise LLMAccessError("llm/provider-error", "Configured model stream failed") from None
        except BaseException:
            await self.aclose()
            raise
        finally:
            self._pulling = False
            self._api._scope.release()

    async def aclose(self):
        if self._close_task is None or (self._close_task.done() and self._close_task.exception() is not None):
            self._close_task = asyncio.create_task(self._close(), name="plugin-llm-stream-close")
        while not self._close_task.done():
            try:
                await asyncio.shield(self._close_task)
            except asyncio.CancelledError:
                continue
        self._close_task.result()

    async def _close(self):
        self._closed = True
        if self._source is not None:
            close = getattr(self._source, "aclose", None)
            if callable(close):
                try:
                    await close()
                except Exception:
                    raise LLMAccessError("llm/cleanup-failed", "Provider stream did not close; cleanup must be retried") from None
        self._api._streams.discard(self)

    async def __aexit__(self, *args):
        await self.aclose()


__all__ = ["PluginLLMAPI", "LLMAccessError", "TokenEstimate"]
