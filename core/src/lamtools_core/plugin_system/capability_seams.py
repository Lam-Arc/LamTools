"""user:“每一个地方 sunday 都有等价或者近似接口”+(可选外部能力具有真实受管注册/调用契约，未安装提供方必须明确失败)。"""
import asyncio
import copy
import inspect
import json
import math
import re

from .filesystem_access import PluginFilesystemAPI
from .services import ServiceError, ServiceKey


class CapabilityError(RuntimeError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def _name(value):
    if type(value) is not str or not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_.-]{0,63}", value):
        raise CapabilityError("capability/invalid-name", "Use a provider name of at most 64 letters, digits, dots, hyphens or underscores")
    return value


class NamedCapabilityAPI:
    """The upstream browser/computer seam reserves a name, not operation methods."""
    def __init__(self, context, scope, kind):
        self._scope, self._kind = scope, kind
        registry = context._service_registry
        if not hasattr(registry, "_named_capability_slots"):
            registry._named_capability_slots = {}
        self._slots = registry._named_capability_slots

    @property
    def provider_name(self):
        self._scope.check_open()
        slot = self._slots.get(self._kind)
        return slot[1] if slot else None

    def register(self, name, *, cleanup=None):
        self._scope.check_open()
        _name(name)
        if cleanup is not None and not callable(cleanup):
            raise CapabilityError("capability/invalid-provider", "cleanup must be callable")
        if self._kind in self._slots:
            raise CapabilityError("capability/conflict", "A provider already owns this capability")
        token = object()
        slot = (token, name)
        self._slots[self._kind] = slot
        task = None
        async def close():
            nonlocal task
            async def run():
                if cleanup is not None:
                    result = cleanup()
                    if inspect.isawaitable(result):
                        await result
                # A failed cleanup deliberately retains the reservation for retry.
                if self._slots.get(self._kind) is slot:
                    self._slots.pop(self._kind)
            if task is None or task.done() and (task.cancelled() or task.exception() is not None):
                task = asyncio.create_task(run(), name="capability-close:" + self._kind)
                task.add_done_callback(lambda t: None if t.cancelled() else t.exception())
            await asyncio.shield(task)
        self._scope.on_dispose(close)
        return close


def _position(value):
    return (type(value) is dict and set(value) == {"line", "character"}
            and all(type(x) is int and 0 <= x <= 2**31 - 1 for x in value.values()))


def _range(value):
    return (type(value) is dict and set(value) == {"start", "end"} and _position(value["start"])
            and _position(value["end"]) and (value["start"]["line"], value["start"]["character"])
            <= (value["end"]["line"], value["end"]["character"]))


def _lsp_result(value, operation):
    try:
        if len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf8")) > 1048576:
            raise ValueError
        if type(value) is not dict:
            raise ValueError
        if operation == "hover":
            hover = value["hover"]
            if value["kind"] != "hover" or hover is not None and (type(hover) is not dict or type(hover.get("contents")) is not str
                    or "range" in hover and not _range(hover["range"])):
                raise ValueError
        else:
            if value["kind"] != "locations" or type(value["locations"]) is not list or len(value["locations"]) > 1000 or type(value["resolvedWorkspaceUri"]) is not str:
                raise ValueError
            for location in value["locations"]:
                if type(location) is not dict or type(location.get("uri")) is not str or not _range(location.get("range")):
                    raise ValueError
    except Exception:
        raise CapabilityError("capability/invalid-result", "Provider returned an invalid or oversized normalized LSP result") from None
    return copy.deepcopy(value)


class _LspProvider:
    def __init__(self, callback):
        self.query = callback


class PluginLspAPI:
    def __init__(self, context, scope):
        self._context, self._scope, self._root = context, scope, context.work_root
        registry = context._service_registry
        if not hasattr(registry, "_lsp_reservations"):
            registry._lsp_reservations = {}
        self._reservations = registry._lsp_reservations

    def register_provider(self, provider_id, extension_to_language, query):
        self._scope.check_open()
        _name(provider_id)
        if type(extension_to_language) is not dict or not 1 <= len(extension_to_language) <= 100 or not callable(query):
            raise CapabilityError("capability/invalid-provider", "Provide 1–100 extension mappings and a query callback")
        for extension, language in extension_to_language.items():
            if type(extension) is not str or not re.fullmatch(r"\.[a-z0-9_-]{1,32}", extension) or type(language) is not str or not language or len(language) > 64:
                raise CapabilityError("capability/invalid-provider", "Extensions must be lowercase with a leading dot; language IDs must be bounded")
        keys = ["lsp.provider." + provider_id] + ["lsp.extension" + extension for extension in extension_to_language]
        for key in keys:
            previous = self._reservations.get(key)
            if previous is not None and previous.live or key in self._scope.registry.values or key in self._scope.entries:
                raise CapabilityError("capability/conflict", "Provider ID or extension is already registered")
        provider = _LspProvider(query)
        entries = []
        for key in keys:
            entry = self._scope.register(ServiceKey(key), provider)
            self._reservations[key] = entry
            entries.append(entry)
        provider.languages = dict(extension_to_language)
        def dispose():
            for entry in entries:
                entry()
                if self._reservations.get(entry.key.name) is entry:
                    self._reservations.pop(entry.key.name)
        self._scope.on_dispose(dispose)
        return dispose

    async def query(self, operation, file_path, *, line, character, timeout=30):
        self._scope.acquire()
        try:
            if operation not in {"goToDefinition", "findReferences", "goToImplementation", "hover"} or not _position({"line": line, "character": character}):
                raise CapabilityError("capability/invalid-query", "Use a supported operation and nonnegative zero-based UTF-16 coordinates")
            if type(timeout) not in {int, float} or not math.isfinite(timeout) or not 0 < timeout <= 120:
                raise CapabilityError("capability/invalid-query", "timeout must be in (0, 120] seconds")
            path = PluginFilesystemAPI(self._root, self._scope).resolve(file_path)
            if not path.is_file():
                raise CapabilityError("capability/invalid-query", "Source must be an existing project file")
            extension = path.suffix.lower()
            try:
                ref = self._context.bind_service("lsp.extension" + extension)
            except ServiceError as error:
                if error.code == "service/unavailable":
                    raise CapabilityError("capability/unavailable", "No LSP provider is installed for this extension") from None
                raise
            provider = ref.get()
            request = {"operation": operation, "filePath": str(path), "workspaceRoot": str(self._root),
                       "position": {"line": line, "character": character}, "languageId": provider.languages[extension]}
            try:
                async with asyncio.timeout(timeout):
                    result = await ref.call("query", request)
            except TimeoutError:
                raise CapabilityError("capability/timeout", "LSP query exceeded its deadline") from None
            return _lsp_result(result, operation)
        finally:
            self._scope.release()
