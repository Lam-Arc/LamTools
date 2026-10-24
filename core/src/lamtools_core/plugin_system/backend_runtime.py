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



class V2RuntimeManager:
    """Own the v2 backend handles and drive start/stop on enable transitions.

    The legacy manager resolves plugins through the legacy registry and cannot
    see v2 manifests, so v2 gets its own small manager with the same shape:
    ``get``, ``is_enabled``, ``start`` and ``stop``.
    """

    def __init__(self, handles: list[Any], host: Any, context: Any) -> None:
        self.handles = list(handles)
        self.host = host
        self.context = context
        self._stopped: dict[str, Any] = {}
        self._locks: dict[str, Any] = {}

    def owns(self, plugin: str) -> bool:
        return self.host is not None and self.host.get(str(plugin)) is not None

    def get(self, plugin: str) -> Any | None:
        target = str(plugin)
        return next(
            (item for item in self.handles if getattr(item.plugin, "name", "") == target),
            None,
        )

    def is_enabled(self, plugin: str) -> bool:
        manifest = self.host.get(str(plugin)) if self.host is not None else None
        if manifest is None or not manifest.enabled:
            return False
        raw = manifest.raw if isinstance(manifest.raw, dict) else {}
        has_backend = bool(raw.get("backend")) or (
            manifest.root / "backend" / "__init__.py"
        ).is_file()
        if not has_backend:
            return True
        handle = self.get(plugin)
        if handle is None:
            return False
        return getattr(handle, "state", "") not in {"failed", "stopped", "stopping"}

    async def start(self, plugin: str) -> bool:
        import asyncio

        from lamtools_core.plugins.lifecycle import (
            load_plugin_backend,
            start_plugin_backend,
        )

        name = str(plugin)
        lock = self._locks.setdefault(name, asyncio.Lock())
        async with lock:
            manifest = self.host.get(name) if self.host is not None else None
            if manifest is None or not manifest.enabled:
                return False
            handle = self.get(name) or self._stopped.pop(name, None)
            if handle is None:
                handle = load_plugin_backend(manifest, self.context)
                if handle is None:
                    return True
            if handle not in self.handles:
                self.handles.append(handle)
            await start_plugin_backend(handle, handle.context or self.context)
            remember_context(name, handle.context)
            return True

    async def stop(self, plugin: str) -> bool:
        import asyncio

        from lamtools_core.plugins.lifecycle import stop_plugin_backend

        name = str(plugin)
        lock = self._locks.setdefault(name, asyncio.Lock())
        async with lock:
            handle = self.get(name)
            if handle is None:
                return False
            await stop_plugin_backend(handle)
            self.handles = [item for item in self.handles if item is not handle]
            self._stopped[name] = handle
            forget_context(name)
            return True


def register_manager(host: Any, handles: list[Any], context: Any) -> V2RuntimeManager:
    manager = V2RuntimeManager(handles, host, context)
    remember_handles(handles)
    if context is not None and hasattr(context, "set_service"):
        context.set_service("plugin.v2_runtime_manager", manager)
        context.set_service("plugin.v2_host", host)
    if host is not None:
        host.backend_manager = manager
    return manager


__all__ = [
    "V2RuntimeManager",
    "context_for",
    "forget_context",
    "register_manager",
    "remember_context",
    "remember_handles",
]
