"""user:“每一个地方 sunday 都有等价或者近似接口”+(提示词贡献绑定已有启动所有权，复用原提示词流水线)。"""

from __future__ import annotations

import inspect
import math
import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Callable

from .services import RegistrationScope

_VARIABLE = re.compile(r"[a-z][a-z0-9_]*\Z")
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_.:-]{0,127}\Z")
_GROUP = re.compile(r"\{\{([^{}]*)\}\}")


def _scope_id(value):
    if value is not None and (not isinstance(value, str) or not value.strip() or len(value) > 256):
        raise ValueError("prompt scope must be a non-empty ID or None")
    return value


def _order(value):
    if type(value) is not int and (type(value) is not float or not math.isfinite(value)):
        raise ValueError("prompt order must be finite")
    return value


def _sync_callable(callback):
    if not callable(callback):
        raise TypeError("prompt provider must be callable")
    if inspect.iscoroutinefunction(callback) or inspect.iscoroutinefunction(getattr(callback, "__call__", None)):
        raise TypeError("prompt providers must be synchronous")


def _sync_result(value):
    if inspect.isawaitable(value):
        close = getattr(value, "close", None)
        if callable(close):
            close()
        raise TypeError("prompt providers must be synchronous")
    return value


@dataclass(eq=False)
class _Entry:
    scope: RegistrationScope
    kind: str
    name: str
    provider: object
    order: int | float
    session_id: str | None
    agent_id: str | None
    interpolate: bool = True
    live: bool = True

    def visible(self, context):
        return (self.live and self.scope.accepting and self.scope.published
                and (self.session_id is None or self.session_id == context.session_id)
                and (self.agent_id is None or self.agent_id == context.agent_id))


class PluginPromptAPI:
    """A synchronous facade pinned to one managed plugin start."""

    def __init__(self, host: PromptContributions, scope: RegistrationScope):
        self._host, self._scope = host, scope

    def section(self, name: str, text: str | Callable, *, order=100, session_id=None, agent_id=None, interpolate=True):
        self._scope.check_open()
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            raise ValueError("invalid prompt section name")
        if callable(text):
            _sync_callable(text)
        elif not isinstance(text, str):
            raise TypeError("prompt section text must be string or synchronous provider")
        if type(interpolate) is not bool:
            raise TypeError("interpolate must be a boolean")
        return self._host.add(_Entry(self._scope, "section", name, text, _order(order),
                                    _scope_id(session_id), _scope_id(agent_id), interpolate))

    def variable(self, name: str, provider: Callable, *, session_id=None, agent_id=None):
        self._scope.check_open()
        if not isinstance(name, str) or not _VARIABLE.fullmatch(name):
            raise ValueError("invalid prompt variable name; expected [a-z][a-z0-9_]*")
        _sync_callable(provider)
        return self._host.add(_Entry(self._scope, "variable", name, provider, 0,
                                    _scope_id(session_id), _scope_id(agent_id)))

    def on_assemble(self, callback: Callable, *, order=100, session_id=None, agent_id=None):
        self._scope.check_open()
        _sync_callable(callback)
        session_id, agent_id, order = _scope_id(session_id), _scope_id(agent_id), _order(order)
        scope = self._scope
        def wrapped(context, assembly):
            if not scope.accepting or not scope.published:
                return None
            if session_id is not None and context.session_id != session_id:
                return None
            if agent_id is not None and context.agent_id != agent_id:
                return None
            return callback(context, assembly)
        remove = self._host.waterfall.register(wrapped, plugin=scope.owner, order=order)
        scope.on_dispose(remove)
        return remove


class PromptContributions:
    def __init__(self, waterfall):
        self.waterfall = waterfall
        self.entries: list[_Entry] = []

    def for_scope(self, scope):
        scope.check_open()
        return PluginPromptAPI(self, scope)

    def add(self, entry):
        entry.scope.check_open()
        for previous in self.entries:
            if not previous.live or not previous.scope.accepting or previous.kind != entry.kind or previous.name != entry.name:
                continue
            if entry.kind == "variable" and previous.scope.owner != entry.scope.owner:
                raise ValueError(f"prompt variable owner conflict: {entry.name}")
            if previous.scope.owner == entry.scope.owner and (previous.session_id, previous.agent_id) == (entry.session_id, entry.agent_id):
                raise ValueError(f"prompt contribution conflict: {entry.name}")
        self.entries.append(entry)
        def remove():
            entry.live = False
            if entry in self.entries:
                self.entries.remove(entry)
        entry.scope.on_dispose(remove)
        return remove

    def apply(self, context, assembly):
        # user:“宿主能力补齐和接口完善与文档更新”+(同一插件的具体会话/代理贡献遮蔽全局默认，其他会话保留默认)。
        selected = {}
        for entry in list(self.entries):
            if not entry.visible(context):
                continue
            key = (entry.kind, entry.scope.owner, entry.name)
            rank = (entry.session_id is not None, entry.agent_id is not None)
            previous = selected.get(key)
            if previous is None or rank > (previous.session_id is not None, previous.agent_id is not None):
                selected[key] = entry
        variables = {}
        for entry in selected.values():
            if entry.kind == "variable":
                variables[entry.name] = self.resolve(entry, context)
        sections = sorted((entry for entry in selected.values() if entry.kind == "section"),
                          key=lambda entry: (entry.order, f"{entry.scope.owner}:{entry.name}"))
        for entry in sections:
            value = self.resolve(entry, context)
            if value is None:
                continue
            if entry.interpolate:
                value = _interpolate(value, variables)
            assembly.append_section(f"{entry.scope.owner}:{entry.name}", value, order=entry.order,
                                    metadata={"plugin": entry.scope.owner, "epoch": entry.scope.epoch})
        return assembly

    @staticmethod
    def resolve(entry, context):
        try:
            value = entry.provider(deepcopy(context)) if callable(entry.provider) else entry.provider
            value = _sync_result(value)
            if value is not None and not isinstance(value, str):
                raise TypeError("prompt provider must return str or None")
            return value
        except Exception as error:
            raise RuntimeError(f"prompt {entry.kind} '{entry.scope.owner}:{entry.name}' failed: {error}") from error


def _interpolate(text, variables):
    # Matches the pinned upstream's complete simple groups; an unmatched opening
    # without a later closing group remains literal prose.
    parts, offset = [], 0
    while (opening := text.find("{{", offset)) >= 0:
        parts.append(text[offset:opening])
        group = _GROUP.match(text, opening)
        if group is None:
            if text.find("}}", opening + 2) >= 0:
                raise ValueError("malformed prompt variable reference")
            parts.append("{{")
            offset = opening + 2
            continue
        name = group[1]
        if not _VARIABLE.fullmatch(name):
            raise ValueError(f"malformed prompt variable reference: {name!r}")
        if name not in variables or variables[name] is None:
            raise ValueError(f"unresolved prompt variable: {name}")
        parts.append(variables[name])
        offset = group.end()
    parts.append(text[offset:])
    return "".join(parts)
