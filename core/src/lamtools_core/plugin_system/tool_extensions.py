"""Owned dynamic tools and restrictive hooks over the existing tool pipeline.

user:“宿主能力补齐和接口完善与文档更新”+(工具与策略沿用插件启动所有权，钩子不替代审批，最终观察在真实结果边界执行)。
"""

from __future__ import annotations

import inspect
import json
import logging
import re
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, replace
from types import MappingProxyType, SimpleNamespace
from typing import Any, Callable, Mapping

from lamtools_core.tool import ToolCall, ToolContext, ToolResult, ToolSpec
from .services import RegistrationScope
from .tool_schema import check_schema, check_arguments

_logger = logging.getLogger(__name__)
_context: ContextVar[ToolContext | None] = ContextVar("plugin_tool_context", default=None)
_defer: ContextVar[bool] = ContextVar("plugin_tool_defer_observers", default=False)
BINDING = "_sunday_tool_binding"


@contextmanager
def tool_execution_context(context: ToolContext):
    token = _context.set(context)
    try:
        yield
    finally:
        _context.reset(token)


@contextmanager
def kernel_tool_result_boundary():
    token = _defer.set(True)
    try:
        yield
    finally:
        _defer.reset(token)


def observers_deferred() -> bool:
    return _defer.get()


def current_session(fallback: str = "") -> str:
    context = _context.get()
    return context.session_id if context is not None else fallback


def _freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if value is None or isinstance(value, (str, int, float, bool, bytes)):
        return value
    raise TypeError("tool hook snapshots require JSON values or immutable bytes")


def _session(value: str | None) -> str | None:
    if value is not None and (not isinstance(value, str) or not value.strip() or len(value) > 256):
        raise ValueError("session_id must be a non-empty string or None")
    return value


def _name(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]{0,127}", value):
        raise ValueError("tool name must be a non-empty ASCII identifier")
    return value


@dataclass(frozen=True)
class ToolInvocation:
    call_id: str
    name: str
    arguments: Mapping[str, Any]
    session_id: str
    run_id: str
    work_root: str


@dataclass(frozen=True)
class ToolOutcome:
    invocation: ToolInvocation
    result: Mapping[str, Any]


@dataclass(frozen=True)
class ToolDecision:
    kind: str = "allow"
    reason: str = ""

    def __post_init__(self):
        if self.kind not in {"allow", "deny"} or not isinstance(self.reason, str):
            raise ValueError("tool decision supports allow/deny only; ask_user belongs to the existing permission gate")


@dataclass(frozen=True)
class ToolPatch:
    content: str | None = None

    def __post_init__(self):
        if self.content is not None and not isinstance(self.content, str):
            raise TypeError("tool patch content must be a string")


@dataclass(eq=False)
class _Contribution:
    scope: RegistrationScope
    session_id: str | None
    kind: str
    callback: Callable | None = None
    spec: ToolSpec | None = None
    allow: frozenset[str] | None = None
    deny: frozenset[str] = frozenset()
    live: bool = True
    token: str = ""

    def visible(self, session_id: str) -> bool:
        return self.live and self.scope.accepting and self.scope.published and (self.session_id is None or self.session_id == session_id)


class PluginToolAPI:
    def __init__(self, host: ToolExtensionsHost, scope: RegistrationScope) -> None:
        self._host, self._scope = host, scope

    def register(self, spec: ToolSpec, handler: Callable, *, session_id: str | None = None, level: int | None = None) -> Callable[[], None]:
        self._scope.check_open()
        if not isinstance(spec, ToolSpec) or not callable(handler):
            raise TypeError("register requires ToolSpec and callable handler")
        _name(spec.name)
        if spec.name in self._host.reserved or spec.name.startswith("mcp__"):
            raise ValueError(f"tool reserved name: {spec.name}")
        previous = self._host.tools.get(spec.name)
        if previous is not None and previous.live and previous.scope.accepting:
            raise ValueError(f"tool name conflict: {spec.name}")
        copied = deepcopy(spec)
        if not isinstance(copied.description, str) or not isinstance(copied.metadata, dict):
            raise TypeError("tool description and metadata must be string/object")
        json.dumps(copied.metadata, allow_nan=False)
        if not isinstance(copied.input_schema, dict):
            raise ValueError("tool schema must be an object")
        copied.input_schema = copied.input_schema or {"type": "object"}
        check_schema(copied.input_schema)
        if copied.permission == "unspecified":
            copied.permission = "ask_user"
        if copied.permission not in {"auto_allow", "ask_user", "hard_block"}:
            raise ValueError("invalid tool permission")
        declared_level = copied.metadata.get("operation_level", 3) if level is None else level
        if type(declared_level) is not int or not 0 <= declared_level <= 3:
            raise ValueError("operation level must be an integer in [0, 3]")
        copied.metadata["operation_level"] = declared_level
        if declared_level == 0:
            copied.permission = "hard_block"
        if copied.output_schema:
            raise ValueError("output schema is not implemented by dynamic tool contract v1")
        copied.metadata.update(plugin=self._scope.owner, plugin_dynamic=True, plugin_owned_tool=True)
        entry = _Contribution(self._scope, _session(session_id), "tool", handler, copied, token=uuid.uuid4().hex)
        self._host.tools[copied.name] = entry
        self._host.known.add(copied.name)
        return self._host.own(entry)

    def restrict(self, *, allow=None, deny=(), session_id: str | None = None) -> Callable[[], None]:
        def names(value):
            if isinstance(value, str):
                raise ValueError("tool name sets must be collections, not strings")
            return frozenset(_name(name) for name in value)
        entry = _Contribution(self._scope, _session(session_id), "restrict",
                              allow=None if allow is None else names(allow), deny=names(deny))
        return self._host.own(entry)

    def guard(self, callback: Callable, *, session_id: str | None = None) -> Callable[[], None]:
        return self._hook("guard", callback, session_id)

    def on(self, event: str, callback: Callable, *, session_id: str | None = None) -> Callable[[], None]:
        if event not in {"tools/pre-execute", "tools/post-execute", "tools/result"}:
            raise ValueError(f"tool event not implemented: {event}")
        return self._hook(event, callback, session_id)

    def _hook(self, kind, callback, session_id):
        if not callable(callback):
            raise TypeError("tool hook must be callable")
        return self._host.own(_Contribution(self._scope, _session(session_id), kind, callback))


class ToolExtensionProvider:
    def __init__(self, host: ToolExtensionsHost) -> None:
        self.host = host

    def __call__(self, *, work_root: str = "", session_id: str = ""):
        specs, handlers = [], {}
        for name, entry in list(self.host.tools.items()):
            if not entry.visible(session_id) or not self.host.allows(name, session_id):
                continue
            specs.append(deepcopy(entry.spec))
            async def execute(call, captured=entry):
                return await self.host.dispatch(captured, call, work_root)
            handlers[name] = execute
        return SimpleNamespace(specs=specs, handlers=handlers)


class ToolExtensionsHost:
    def __init__(self, reserved_names=()) -> None:
        self.reserved = set(reserved_names)
        self.tools: dict[str, _Contribution] = {}
        self.known: set[str] = set()
        self.contributions: list[_Contribution] = []
        self.provider = ToolExtensionProvider(self)

    def reserve(self, names) -> None:
        names = set(names)
        for name in names:
            entry = self.tools.get(name)
            if entry is not None and entry.live and entry.scope.accepting:
                raise ValueError(f"dynamic tool conflicts with reserved tool: {name}")
        self.reserved.update(names)

    def for_scope(self, scope: RegistrationScope) -> PluginToolAPI:
        scope.check_open()
        return PluginToolAPI(self, scope)

    def own(self, entry: _Contribution) -> Callable[[], None]:
        entry.scope.check_open()
        self.contributions.append(entry)
        def remove():
            entry.live = False
            if entry in self.contributions:
                self.contributions.remove(entry)
            if entry.spec is not None and self.tools.get(entry.spec.name) is entry:
                self.tools.pop(entry.spec.name)
        entry.scope.on_dispose(remove)
        return remove

    def allows(self, name: str, session_id: str) -> bool:
        for entry in self.contributions:
            if entry.kind == "restrict" and entry.visible(session_id):
                if name in entry.deny or entry.allow is not None and name not in entry.allow:
                    return False
        return True

    def binding_error(self, call: ToolCall, session_id: str) -> ToolResult | None:
        if not self.allows(call.name, session_id):
            return self.block(call, "Tool is restricted in this session", "tool/restricted")
        if call.name not in self.known:
            return None
        entry = self.tools.get(call.name)
        if entry is None or not entry.visible(session_id):
            return self.block(call, "Dynamic tool is unavailable", "tool/unavailable")
        old = call.metadata.get(BINDING)
        if old is not None and old != entry.token:
            return self.block(call, "Dynamic tool registration changed; prepare a new call", "tool/stale-binding")
        call.metadata[BINDING] = entry.token
        return None

    @staticmethod
    def block(call, reason, code):
        return ToolResult(call.id, call.name, status="blocked", error=reason, error_code=code)

    @staticmethod
    def invocation(call: ToolCall, context: ToolContext) -> ToolInvocation:
        return ToolInvocation(call.id, call.name, _freeze(deepcopy(call.arguments)), context.session_id, context.run_id, context.work_root)

    def matching(self, kind: str, session_id: str):
        return [entry for entry in self.contributions if entry.kind == kind and entry.visible(session_id)]

    async def invoke(self, entry, value):
        entry.scope.acquire()
        try:
            result = entry.callback(value)
            return await result if inspect.isawaitable(result) else result
        finally:
            entry.scope.release()

    async def before(self, call: ToolCall, context: ToolContext) -> ToolResult | None:
        blocked = self.binding_error(call, context.session_id)
        if blocked is not None:
            return blocked
        pre = self.matching("tools/pre-execute", context.session_id)
        guards = self.matching("guard", context.session_id)
        if not pre and not guards:
            return None
        try:
            invocation = self.invocation(call, context)
            signature = (self, call.id, call.name, context.session_id, context.run_id, context.work_root, json.dumps(call.arguments, sort_keys=True, allow_nan=False),
                         tuple(id(entry) for entry in pre), call.metadata.get(BINDING))
            seen = getattr(call, "_sunday_tool_preflight", {})
            run_pre = seen.get(id(self)) != signature
            for stage in ("pre", "guard"):
                entries = (pre if run_pre else []) if stage == "pre" else self.matching("guard", context.session_id)
                for entry in entries:
                    if not entry.visible(context.session_id):
                        continue
                    decision = await self.invoke(entry, invocation)
                    if decision is not None and not isinstance(decision, ToolDecision):
                        raise TypeError("tool gate must return ToolDecision or None")
                    if decision is not None and decision.kind == "deny":
                        return self.block(call, decision.reason or "Denied by tool policy", "tool/denied")
                if stage == "guard" and entries != self.matching("guard", context.session_id):
                    return self.block(call, "Tool guards changed during preflight; retry with current policy", "tool/policy-changed")
            # This attribute is deliberately absent from ToolCall.to_dict():
            # restored approval calls re-run policy, not a serialized promise.
            seen = dict(seen)
            seen[id(self)] = signature
            call._sunday_tool_preflight = seen
            return self.binding_error(call, context.session_id)
        except Exception as error:
            return self.block(call, f"Tool policy failed: {error}", "tool/policy-error")

    async def dispatch(self, entry, call: ToolCall, work_root: str) -> ToolResult:
        context = _context.get() or ToolContext(work_root=work_root)
        if not entry.visible(context.session_id) or call.metadata.get(BINDING) != entry.token or not self.allows(call.name, context.session_id):
            return self.block(call, "Dynamic tool registration is no longer available", "tool/stale-binding")
        entry.scope.acquire()
        try:
            check_arguments(entry.spec.input_schema, call.arguments)
            invocation = self.invocation(call, replace(context, work_root=context.work_root or work_root))
            result = entry.callback(invocation)
            result = await result if inspect.isawaitable(result) else result
            if not isinstance(result, ToolResult) or result.name != call.name or result.call_id != call.id or result.status not in {"ok", "failed", "blocked", "skipped"}:
                raise TypeError("dynamic handler must return a ToolResult for the same call")
            return result
        except Exception as error:
            # user:“宿主能力补齐和接口完善与文档更新”+(保留宿主预算终止信号，让 kernel 结束本轮，不能降为普通工具失败)。
            if getattr(error, "budget_exhausted", False):
                raise
            return ToolResult(call.id, call.name, status="failed", error=str(error), error_code="tool/handler-error")
        finally:
            entry.scope.release()

    async def after(self, call: ToolCall, result: ToolResult, context: ToolContext) -> ToolResult:
        if result.status in {"blocked", "skipped"}:
            return result
        for entry in self.matching("tools/post-execute", context.session_id):
            if not entry.visible(context.session_id):
                continue
            try:
                patch = await self.invoke(entry, ToolOutcome(self.invocation(call, context), _freeze(deepcopy(result.to_dict()))))
                if patch is not None:
                    if not isinstance(patch, ToolPatch):
                        raise TypeError("post hook must return ToolPatch or None")
                    if patch.content is not None:
                        result = replace(result, content=patch.content)
            except Exception as error:
                errors = list(result.metadata.get("tool_hook_errors") or [])
                errors.append({"owner": entry.scope.owner, "phase": "post-execute", "error": str(error)})
                result = replace(result, metadata={**result.metadata, "tool_hook_errors": errors})
        return result

    async def observe(self, call: ToolCall, result: ToolResult, context: ToolContext) -> None:
        for entry in self.matching("tools/result", context.session_id):
            if not entry.visible(context.session_id):
                continue
            try:
                returned = await self.invoke(entry, ToolOutcome(self.invocation(call, context), _freeze(deepcopy(result.to_dict()))))
                if returned is not None:
                    raise TypeError("result observer must return None")
            except Exception:
                _logger.warning("Tool result observer failed: owner=%s tool=%s", entry.scope.owner, call.name, exc_info=True)


def ensure_tool_extensions(context, *, reserved_names=()) -> ToolExtensionsHost:
    host = context.service("tool_extensions")
    if host is None:
        host = ToolExtensionsHost(reserved_names)
        context.set_service("tool_extensions", host)
    else:
        host.reserve(reserved_names)
    return host


__all__ = ["ToolDecision", "ToolPatch", "ToolInvocation", "ToolOutcome", "PluginToolAPI"]
