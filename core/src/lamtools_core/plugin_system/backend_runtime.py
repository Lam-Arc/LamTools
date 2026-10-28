"""user:“该重建就重建”+(宿主唯一持有实例、状态、调用租约和代码代际)。"""
from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
from .lifecycle import backend_entry, plugin_backend_available
from .safety import safe_mode


_REMEMBERED_CONTEXTS: dict[str, object] = {}


def remember_context(plugin, context):
    """Keep the host context for a plugin whose manager is outside this host."""
    if context is not None:
        _REMEMBERED_CONTEXTS[str(plugin)] = context
    return context


def forget_context(plugin):
    _REMEMBERED_CONTEXTS.pop(str(plugin), None)


def context_for(plugin, host=None):
    manager = getattr(host, "backend_manager", None) if host is not None else None
    if manager is not None:
        handle = manager.get(plugin)
        return handle.context if handle is not None else manager.context
    return _REMEMBERED_CONTEXTS.get(str(plugin))


class PluginSupervisor:
    def __init__(self, handles, host, context):
        self.handles = handles if isinstance(handles, list) else list(handles)
        self.host, self.context = host, context
        self._stopped = {}
        self._locks = {}
        self.mutation_lock = asyncio.Lock()
        self.transitioning = set()
        self._active = {}
        self._idle = {}
        self.generation = {}
        self.resources = {}
        self.recoveries = {}
        self.recovery_errors = {}

    def owns(self, plugin):
        return self.host.get(str(plugin)) is not None

    def get(self, plugin):
        return next((item for item in self.handles if item.plugin.name == str(plugin)), None)

    def is_enabled(self, plugin):
        if safe_mode() or plugin in self.transitioning or plugin in self.recoveries:
            return False
        manifest = self.host.get(str(plugin))
        if manifest is None:
            return False
        try:
            return plugin_backend_available(manifest, self.handles)
        except Exception:
            return False

    def status(self, plugin):
        manifest = self.host.get(plugin)
        handle = self.get(plugin) or self._stopped.get(plugin)
        # user:“该修修 如果是架构问题就重构”+(恢复失败沿用界面已有的失败/重试契约，同时明确恢复原因)。
        recovery_error = {"code": "PLUGIN_RECOVERY_REQUIRED", "message": f"恢复未完成，请重试：{self.recovery_errors.get(plugin, '')}"} if plugin in self.recoveries else None
        return {
            "state": "safe_mode" if safe_mode() else "failed" if plugin in self.recoveries else "transitioning" if plugin in self.transitioning else
                     handle.state if handle is not None else "ready" if self.is_enabled(plugin) else "disabled" if manifest and not manifest.enabled else "not_loaded",
            "available": self.is_enabled(plugin), "managed": bool(handle and handle.managed),
            "attempts": handle.attempts if handle else 0,
            "error": recovery_error or (handle.error if handle else None), "last_error": handle.last_error if handle else None,
            "generation": self.generation.get(plugin, 0),
            "recovery_error": self.recovery_errors.get(plugin),
            "recovery_required": plugin in self.recoveries,
        }

    @asynccontextmanager
    async def mutation(self, plugin):
        # user:“该修修 如果是架构问题就重构”+(所有变更先关闭调用入口并串行执行，待恢复事务优先于后续变更)。
        async with self.mutation_lock:
            self.transitioning.add(plugin)
            try:
                await self.recover_pending(plugin)
                yield
            finally:
                self.transitioning.discard(plugin)

    async def recover_pending(self, plugin):
        recover = self.recoveries.get(plugin)
        if recover is None:
            return
        try:
            await recover()
        except BaseException as exc:
            self.recovery_errors[plugin] = str(exc)
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise RuntimeError(f"plugin '{plugin}' recovery required: {exc}") from exc
        self.recoveries.pop(plugin, None)
        self.recovery_errors.pop(plugin, None)

    @asynccontextmanager
    async def lease(self, plugin):
        if not self.is_enabled(plugin):
            raise RuntimeError(f"plugin '{plugin}' is not ready")
        self._active[plugin] = self._active.get(plugin, 0) + 1
        event = self._idle.setdefault(plugin, asyncio.Event())
        event.clear()
        try:
            yield
        finally:
            self._active[plugin] -= 1
            if not self._active[plugin]:
                event.set()

    def own_resource(self, plugin, close):
        self.resources.setdefault(plugin, set()).add(close)

    async def close_resources(self, plugin):
        for close in list(self.resources.get(plugin, ())):
            await close()
            self.resources[plugin].discard(close)

    async def drain(self, plugin):
        if self._active.get(plugin, 0):
            seconds = self.context.service("plugin.lifecycle.drain_timeout", 30) if self.context else 30
            await asyncio.wait_for(self._idle[plugin].wait(), seconds)

    async def start(self, plugin):
        from .lifecycle import load_plugin_backend, PluginRuntimeHandle, _failed, start_plugin_backend, stop_plugin_backend
        from .loading import invalidate_modules
        name = str(plugin)
        async with self._locks.setdefault(name, asyncio.Lock()):
            manifest = self.host.get(name)
            if safe_mode() or manifest is None or not manifest.enabled:
                return False
            handle = self.get(name) or self._stopped.pop(name, None)
            # user:“该重建就重建”+(修复加载失败后保留上次诊断供排查)。
            last_error = handle.last_error if handle is not None else None
            if handle is not None and handle.value is None:
                self.forget(name)
                invalidate_modules(manifest.root)
                handle = None
            if handle is None:
                try:
                    handle = load_plugin_backend(manifest, self.context)
                except Exception as exc:
                    handle = PluginRuntimeHandle(plugin=manifest, value=None, context=self.context, managed=True)
                    _failed(handle, "load", exc)
                if handle is None:
                    return backend_entry(manifest) is None
                if handle.last_error is None:
                    handle.last_error = last_error
            if handle not in self.handles:
                self.handles.append(handle)
            if handle.value is None:
                raise RuntimeError(str((handle.error or {}).get("message") or "backend load failed"))
            try:
                if handle.state == "failed" and handle.cleanup_needed:
                    await stop_plugin_backend(handle)
                await start_plugin_backend(handle, handle.context or self.context)
            except BaseException:
                diagnostic = handle.error
                try:
                    await stop_plugin_backend(handle)
                finally:
                    handle.state = "failed"
                    handle.error = handle.last_error = diagnostic
                raise
            return True

    async def stop(self, plugin):
        from .lifecycle import stop_plugin_backend
        name = str(plugin)
        async with self._locks.setdefault(name, asyncio.Lock()):
            await self.close_resources(name)
            handle = self.get(name)
            if handle is None:
                return False
            await stop_plugin_backend(handle)
            self.handles[:] = [item for item in self.handles if item is not handle]
            self._stopped[name] = handle
            return True

    def forget(self, plugin):
        handle = self.get(plugin) or self._stopped.get(plugin)
        if handle is not None and (handle.started or any(not item.done() for item in handle.pending_tasks)):
            raise RuntimeError(f"plugin '{plugin}' must finish stopping before unloading")
        self.handles[:] = [item for item in self.handles if item.plugin.name != plugin]
        self._stopped.pop(plugin, None)
        manifest = self.host.get(plugin)
        if manifest is not None:
            from .loading import invalidate_modules
            invalidate_modules(manifest.root)
        self.generation[plugin] = self.generation.get(plugin, 0) + 1


V2RuntimeManager = PluginSupervisor


def register_manager(host, handles, context):
    existing = getattr(host, "backend_manager", None)
    if isinstance(existing, PluginSupervisor):
        manager = existing
    else:
        manager = host.backend_manager = PluginSupervisor(handles, host, context)
    if context is not None:
        context.set_service("plugin.v2_runtime_manager", manager)
        context.set_service("plugin.v2_host", host)
    return manager


__all__ = ["PluginSupervisor", "V2RuntimeManager", "context_for", "forget_context", "register_manager", "remember_context"]
