"""Track the live plugin context behind each plugin backend.

user:“装配与生命周期分层”+管理器唯一持有后端句柄，启停随插件开关走；
装载与启动细节在 :mod:`plugin_system.lifecycle`。
"""

from __future__ import annotations

from typing import Any

from .lifecycle import backend_entry

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
    """Own the backend handles and drive start/stop on enable transitions.

    One manager per process is the goal (finish-up plan, step 2); this class
    owns the ``get``/``is_enabled``/``start``/``stop`` surface hosts use.
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
        if backend_entry(manifest) is None:
            return True
        handle = self.get(plugin)
        if handle is None:
            return False
        return getattr(handle, "state", "") not in {"failed", "stopped", "stopping"}

    async def start(self, plugin: str) -> bool:
        import asyncio

        from .lifecycle import load_plugin_backend, start_plugin_backend

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

        from .lifecycle import stop_plugin_backend

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
    # user:“后端生命周期进程级唯一”+同一宿主只建一个管理器；重复注册只
    # 刷新句柄引用（装配每轮调用，管理器不能跟着换）。
    existing = getattr(host, "backend_manager", None)
    if isinstance(existing, V2RuntimeManager):
        existing.handles = list(handles)
        existing.context = context or existing.context
        remember_handles(handles)
        return existing
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
