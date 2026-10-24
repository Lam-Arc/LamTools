"""Track the live plugin context behind each v2 backend.

The legacy lifecycle loader is reused unchanged: a v2 plugin that declares a
``backend`` gets the same factory, start hooks, health monitoring and services.
This module only remembers which context belongs to which plugin so operation
handlers and tools can reach it later in the same process.

user:“插件可以有自己的后端”+不重造生命周期，沿用已有装载器，只补上下文查表。
"""

from __future__ import annotations

from typing import Any

_CONTEXTS: dict[str, Any] = {}


def remember_context(plugin: str, context: Any) -> None:
    if plugin and context is not None:
        _CONTEXTS[plugin] = context


def context_for(plugin: str) -> Any | None:
    return _CONTEXTS.get(str(plugin))


def forget_context(plugin: str) -> None:
    _CONTEXTS.pop(str(plugin), None)


def remember_handles(handles: list[Any]) -> None:
    for handle in handles:
        plugin = getattr(getattr(handle, "plugin", None), "name", "")
        remember_context(str(plugin), getattr(handle, "context", None))


__all__ = ["context_for", "forget_context", "remember_context", "remember_handles"]
