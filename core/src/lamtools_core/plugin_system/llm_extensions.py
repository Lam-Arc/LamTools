"""user:“每一个地方 sunday 都有等价或者近似接口”+(扩展字段受原插件注册权威管理，准备不可变快照，HTTP接收回调恰好一次)。"""
import asyncio
import hashlib
import inspect
import json
import re
from dataclasses import dataclass
from types import MappingProxyType

from lamtools_core.async_tasks import finish_on_cancel
from .services import ServiceKey, ServiceError


class LLMExtensionError(RuntimeError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def _freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(v) for v in value)
    return value


def _thaw(value):
    if isinstance(value, (dict, MappingProxyType)):
        return {k: _thaw(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_thaw(v) for v in value]
    return value


def _clone(value, limit):
    encoded = json.dumps(_thaw(value), allow_nan=False, ensure_ascii=False).encode("utf8")
    if len(encoded) > limit:
        raise ValueError("Extension JSON exceeds its bound")
    return _freeze(json.loads(encoded))


@dataclass(frozen=True)
class ExtensionRequest:
    body: object
    session_id: str | None
    purpose: str | None


async def _invoke(registration, callback, *args):
    if not registration.live:
        raise ServiceError("service/stale", registration.key.name, "Extension provider was withdrawn")
    scope = registration.scope
    scope.acquire()
    try:
        async with asyncio.timeout(5):
            result = callback(*args)
            return await result if inspect.isawaitable(result) else result
    finally:
        scope.release()


class PreparedExtensions:
    def __init__(self, scope, fields, callbacks, omitted):
        self.fields, self.omitted = MappingProxyType(fields), MappingProxyType(omitted)
        self._scope, self._callbacks, self._acceptance = scope, callbacks, None

    def fields_for_wire(self):
        return _thaw(self.fields)

    async def _accept(self):
        self._scope.acquire()
        try:
            outcomes = await asyncio.gather(*[_invoke(reg, callback) for reg, callback in self._callbacks], return_exceptions=True)
            if any(isinstance(row, BaseException) for row in outcomes):
                raise LLMExtensionError("llm-extension/accept-failed", "One or more extension acceptance callbacks failed after HTTP acceptance")
        finally:
            self._scope.release()

    async def accept(self):
        # user:“审查当前代码，然后继续”+(接收任务只创建一次；所有租约在执行回调的同一Task内取得和释放)。
        if self._acceptance is None:
            self._acceptance = asyncio.create_task(self._accept(), name="plugin-llm-extension-accept")
        async def join():
            return await asyncio.shield(self._acceptance)
        await finish_on_cancel(join(), name="plugin-llm-extension-accept-join")


class PluginLLMExtensionsAPI:
    def __init__(self, context, scope):
        self._context, self._scope = context, scope
        self._prefix = "llm.extension." + hashlib.sha256(str(context.work_root).encode()).hexdigest()[:24] + "."

    def _entries(self):
        self._scope.check_open()
        registry = self._scope.registry
        entries = {name: row for name, row in registry.records.items()
                   if name.startswith(self._prefix) and registry.record(name) is row}
        entries.update({name: row for name, row in self._scope.entries.items() if name.startswith(self._prefix)})
        return entries

    def has_providers(self):
        return bool(self._entries())

    def register(self, field, prepare):
        self._scope.check_open()
        if type(field) is not str or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", field) or not callable(prepare):
            raise LLMExtensionError("llm-extension/invalid-provider", "Use a bounded field identifier and a callable prepare(request)")
        if field in {"model", "messages", "stream", "tools", "tool_choice", "max_tokens", "temperature", "top_p", "response_format"}:
            raise LLMExtensionError("llm-extension/base-field", "Extensions cannot replace native base request fields")
        name = self._prefix + field
        if name in self._scope.registry.values:
            raise ServiceError("service/conflict", name, "Extension field already has a published provider")
        return self._scope.register(ServiceKey(name), prepare)

    async def prepare(self, body, *, session_id=None, purpose=None):
        self._scope.acquire()
        try:
            if (type(body) is not dict
                    or (session_id is not None and (type(session_id) is not str or not session_id.strip() or len(session_id) > 256 or "\x00" in session_id))
                    or (purpose is not None and (type(purpose) is not str or purpose not in {"compaction", "session-title"}))):
                raise LLMExtensionError("llm-extension/invalid-request", "Use an object body, optional bounded session label and supported purpose")
            try:
                request = ExtensionRequest(_clone(body, 1048576), session_id, purpose)
            except Exception:
                raise LLMExtensionError("llm-extension/invalid-request", "Base request must be bounded finite JSON") from None
            entries = self._entries()
            if len(entries) > 32:
                raise LLMExtensionError("llm-extension/too-many", "At most 32 extension fields per project request")
            fields, callbacks, omitted = {}, [], {}
            for name, row in sorted(entries.items()):
                field = name[len(self._prefix):]
                # user:“宿主能力补齐和接口完善与文档更新”+(冲突检查与提供方读取使用同一冻结请求，等待期间原对象变化不能改变字段归属)。
                if field in request.body:
                    omitted[field] = "base-field-conflict"
                    continue
                try:
                    result = await _invoke(row, row.value, request)
                    if result is None:
                        continue
                    if type(result) is not dict or set(result) - {"value", "accept"} or "value" not in result or (result.get("accept") is not None and not callable(result["accept"])):
                        raise ValueError
                    fields[field] = _clone(result["value"], 65536)
                    if result.get("accept") is not None:
                        callbacks.append((row, result["accept"]))
                except Exception:
                    omitted[field] = "provider-failed"
            return PreparedExtensions(self._scope, fields, callbacks, omitted)
        finally:
            self._scope.release()

    async def prepare_from_http(self, body, metadata):
        metadata = metadata if isinstance(metadata, dict) else {}
        purpose = metadata.get("purpose")
        return await self.prepare(body, session_id=metadata.get("_runtime_session_id"),
                                  purpose=purpose if type(purpose) is str and purpose in {"compaction", "session-title"} else None)
