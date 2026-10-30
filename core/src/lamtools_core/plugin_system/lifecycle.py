"""Plugin backend loading and lifecycle helpers for the unified system.

user:“装配与生命周期分层”+装载器按 v2 清单工作（backend 声明或
backend/__init__.py 约定），句柄管理归 backend_runtime 的管理器；
这里只负责“怎么加载、怎么启动、怎么停”。
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import importlib.util
import inspect
import logging
import sys
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

from .context import PluginContext
from .manifest import PluginManifest

_logger = logging.getLogger(__name__)


@dataclass
class PluginRuntimeHandle:
    """Normalized result of a plugin backend factory."""

    plugin: PluginManifest
    value: Any
    tool_handlers: dict[str, Any] = field(default_factory=dict)
    tool_providers: list[Any] = field(default_factory=list)
    services: dict[str, Any] = field(default_factory=dict)
    started: bool = False
    state: str = "loaded"
    error: dict[str, Any] | None = None
    last_error: dict[str, Any] | None = None
    attempts: int = 0
    managed: bool = False
    stop_requested: bool = False
    cleanup_needed: bool = True
    context: PluginContext | None = field(default=None, repr=False)
    startup_task: asyncio.Task[Any] | None = field(default=None, repr=False)
    monitor_task: asyncio.Task[Any] | None = field(default=None, repr=False)
    pending_tasks: set[asyncio.Future[Any]] = field(default_factory=set, repr=False)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.value, name)


class PluginLifecycleError(RuntimeError):
    def __init__(self, name: str, phase: str, cause: BaseException, *, code: str = "PLUGIN_BACKEND_FAILED") -> None:
        self.plugin_name, self.phase, self.code = name, phase, code
        super().__init__(f"Plugin '{name}' {phase} failed: {str(cause) or type(cause).__name__}")


def _member(handle: PluginRuntimeHandle, name: str, default: Any = None) -> Any:
    return handle.value.get(name, default) if isinstance(handle.value, dict) else getattr(handle.value, name, default)


def _detach(handle: PluginRuntimeHandle) -> None:
    if handle.context is None:
        return
    # user:“每一个地方 sunday 都有等价或者近似接口”+(失败和停用先撤回本代服务，资源清理仍由原有 lifecycle 驱动)。
    if handle.context._registration_scope is not None:
        handle.context._registration_scope.revoke()
    for name, value in {handle.plugin.name: handle.value, **{
        f"{handle.plugin.name}.{key}": value for key, value in handle.services.items()
    }}.items():
        if handle.context.service(name) is value:
            handle.context.remove_service(name)


def _failed(handle: PluginRuntimeHandle, phase: str, cause: BaseException, *, code: str = "PLUGIN_BACKEND_FAILED") -> PluginLifecycleError:
    error = cause if isinstance(cause, PluginLifecycleError) else PluginLifecycleError(handle.plugin.name, phase, cause, code=code)
    handle.started = False
    handle.state = "failed"
    handle.error = handle.last_error = {
        "code": error.code, "phase": error.phase, "message": str(error),
        "type": type(cause).__name__, "at": datetime.now(timezone.utc).isoformat(),
    }
    _detach(handle)
    _logger.warning("%s", error, exc_info=(type(cause), cause, cause.__traceback__))
    return error


def _timeout(handle: PluginRuntimeHandle, phase: str) -> float:
    value = handle.context.service(f"plugin.lifecycle.{phase}_timeout", 30.0) if handle.context else 30.0
    try:
        value = float(value)
        return value if 0 < value < float("inf") else 30.0
    except (TypeError, ValueError):
        return 30.0


def _track_pending(handle: PluginRuntimeHandle, task: asyncio.Future[Any]) -> None:
    handle.pending_tasks.add(task)
    def settled(future: asyncio.Future[Any]) -> None:
        handle.pending_tasks.discard(future)
        if not future.cancelled():
            future.exception()
    task.add_done_callback(settled)


async def _bounded(handle: PluginRuntimeHandle, value: Any, phase: str) -> Any:
    if not inspect.isawaitable(value):
        return value
    task = asyncio.ensure_future(value)
    try:
        done, _ = await asyncio.wait({task}, timeout=_timeout(handle, phase))
    except asyncio.CancelledError:
        task.cancel()
        _track_pending(handle, task)
        raise
    if not done:
        task.cancel()
        _track_pending(handle, task)
        raise PluginLifecycleError(handle.plugin.name, phase, TimeoutError("lifecycle deadline exceeded"), code="PLUGIN_BACKEND_TIMEOUT")
    if task.cancelled():
        raise RuntimeError(f"{phase} callback was cancelled")
    return task.result()


def _resources_alive(handle: PluginRuntimeHandle) -> bool:
    if handle.state != "ready":
        return False
    try:
        for task in _member(handle, "lifecycle_tasks", ()) or ():
            if task.done():
                cause = RuntimeError("backend task was cancelled") if task.cancelled() else task.exception() or RuntimeError("backend task terminated")
                raise cause
        for process in _member(handle, "lifecycle_processes", ()) or ():
            code = process.poll() if callable(getattr(process, "poll", None)) else process.returncode
            if code is not None:
                raise RuntimeError(f"backend process terminated (exit {code})")
    except Exception as exc:
        _failed(handle, "health", exc)
        return False
    return True


async def _health(handle: PluginRuntimeHandle) -> None:
    probe = _member(handle, "health_check")
    if callable(probe):
        result = await _bounded(handle, probe(), "health")
        if result is False or isinstance(result, dict) and result.get("ready") is False:
            raise RuntimeError(str(result.get("error") or "backend is not ready") if isinstance(result, dict) else "backend is not ready")


def _monitor(handle: PluginRuntimeHandle) -> None:
    if handle.monitor_task is not None and not handle.monitor_task.done():
        return
    async def watch() -> None:
        async def cleanup_failure() -> None:
            diagnostic = handle.error
            try:
                await stop_plugin_backend(handle)
            except Exception as error:
                if diagnostic is not None:
                    diagnostic = {**diagnostic, "cleanup_error": str(error)}
            handle.started, handle.state = False, "failed"
            handle.error = handle.last_error = diagnostic

        while handle.state == "ready":
            await asyncio.sleep(1.0)
            if not _resources_alive(handle):
                await cleanup_failure()
                return
            try:
                await _health(handle)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _failed(handle, "health", exc)
                await cleanup_failure()
                return
    if any(_member(handle, name) is not None for name in ("health_check", "lifecycle_tasks", "lifecycle_processes")):
        try:
            handle.monitor_task = asyncio.get_running_loop().create_task(watch(), name=f"plugin:{handle.plugin.name}:health")
        except RuntimeError:
            pass


def backend_entry(plugin: PluginManifest) -> Path | None:
    raw = plugin.raw.get("backend") if isinstance(plugin.raw, dict) else None
    if isinstance(raw, str) and raw.strip():
        candidate = (plugin.root / raw[2:] if raw.startswith("./") else Path(raw)).resolve()
        if not candidate.is_relative_to(plugin.root):
            raise ValueError(f"plugin backend path is outside plugin root: {raw}")
        return candidate
    candidate = plugin.root / "backend" / "__init__.py"
    return candidate if candidate.is_file() else None


def _bundled_module_name(entry: Path) -> str | None:
    marker = Path("lamtools_core") / "plugins" / "bundled"
    parts = entry.resolve().parts
    marker_parts = marker.parts
    for index in range(len(parts) - len(marker_parts)):
        if tuple(parts[index:index + len(marker_parts)]) == marker_parts:
            plugin = parts[index + len(marker_parts)]
            if index + len(marker_parts) + 1 < len(parts) and parts[index + len(marker_parts) + 1] == "backend":
                return f"lamtools_core.plugins.bundled.{plugin}.backend"
    return None


def _load_module(plugin: PluginManifest, entry: Path) -> ModuleType:
    bundled_name = _bundled_module_name(entry)
    if bundled_name:
        return importlib.import_module(bundled_name)
    from .loading import load_entry
    return load_entry(plugin.root, entry)


def load_plugin_backend(plugin: PluginManifest, context: PluginContext) -> PluginRuntimeHandle | None:
    """Load a plugin's optional backend (``backend`` declaration or convention).

    A backend may expose ``create_plugin(context)`` or ``create_runtime``.
    Missing backends are normal for declarative-only plugins.
    """
    from .safety import safe_mode
    if safe_mode():
        return None
    from .process_runtime import ProcessBackend, process_runtime_spec

    # Hand each backend its own scene's model so a plugin never inherits the
    # main conversation's model (see PluginContext.for_scene).  Scoped services
    # stay private to this plugin even though the shared services dict is not.
    plugin_context = context.for_scene(scene_for_plugin(plugin))
    secret_store = getattr(context, "_secret_store", None)
    if secret_store is not None and hasattr(secret_store, "view"):
        plugin_context.set_scoped_service("secrets", secret_store.view(plugin.name))

    process_spec = process_runtime_spec(plugin)
    if process_spec is not None:
        backend = ProcessBackend(plugin, process_spec, plugin_context)
        return PluginRuntimeHandle(
            plugin=plugin,
            value=backend,
            tool_handlers=backend.tool_handlers,
            context=plugin_context,
        )
    entry = backend_entry(plugin)
    if entry is None:
        return None
    if not entry.is_file():
        raise ValueError(f"plugin backend entry does not exist: {entry}")
    module = _load_module(plugin, entry)
    factory = getattr(module, "create_plugin", None) or getattr(module, "create_runtime", None)
    value = factory(plugin_context) if callable(factory) else module
    if inspect.isawaitable(value):
        if inspect.iscoroutine(value):
            value.close()
        raise TypeError("backend factory must be synchronous; use async start for initialization")
    if value is None:
        value = module
    if isinstance(value, PluginRuntimeHandle):
        value.context = plugin_context
        return value
    if isinstance(value, dict):
        return PluginRuntimeHandle(
            plugin=plugin,
            value=value.get("runtime", value),
            tool_handlers=dict(value.get("tool_handlers") or {}),
            tool_providers=list(value.get("tool_providers") or []),
            services=dict(value.get("services") or {}),
            context=plugin_context,
        )
    return PluginRuntimeHandle(
        plugin=plugin,
        value=value,
        tool_handlers=dict(getattr(value, "tool_handlers", {}) or {}),
        tool_providers=list(getattr(value, "tool_providers", []) or []),
        services=dict(getattr(value, "services", {}) or {}),
        context=plugin_context,
    )


def load_enabled_plugin_backends(
    plugins: list[PluginManifest],
    context: PluginContext,
    *,
    start: bool = False,
) -> list[PluginRuntimeHandle]:
    from .safety import safe_mode
    if safe_mode():
        return []
    handles: list[PluginRuntimeHandle] = []
    for plugin in plugins:
        if not plugin.enabled:
            continue
        try:
            handle = load_plugin_backend(plugin, context)
        except Exception as exc:  # noqa: BLE001 — one plugin must not kill Core
            handle = PluginRuntimeHandle(plugin=plugin, value=None, context=context, managed=start)
            _failed(handle, "load", exc)
            handles.append(handle)
            continue
        if handle is None:
            continue
        handles.append(handle)
        handle.managed = start
        if start:
            _schedule_start(handle, context)
        else:
            # Public synchronous assembly has always offered factory-only
            # embedding. Its host opts out of start hooks explicitly.
            handle.state = "ready"
            attach_plugin_runtime(handle, handle.context or context)
            _monitor(handle)
    return handles


def attach_plugin_runtime(handle: PluginRuntimeHandle, context: PluginContext) -> None:
    context.set_service(handle.plugin.name, handle.value)
    for key, value in handle.services.items():
        context.set_service(f"{handle.plugin.name}.{key}", value)


async def start_plugin_backend(handle: PluginRuntimeHandle, context: PluginContext) -> None:
    async with handle.lock:
        if handle.value is None:
            raise PluginLifecycleError(handle.plugin.name, "start", RuntimeError("backend failed to load; reload required"))
        if handle.stop_requested:
            raise PluginLifecycleError(handle.plugin.name, "start", RuntimeError("backend is stopping"), code="PLUGIN_BACKEND_BUSY")
        if handle.started and _resources_alive(handle):
            return
        if any(not task.done() for task in handle.pending_tasks):
            raise PluginLifecycleError(handle.plugin.name, "start", RuntimeError("previous lifecycle task has not terminated"), code="PLUGIN_BACKEND_BUSY")
        runtime_context = handle.context.refresh_from(context) if handle.context is not None else context
        handle.context = runtime_context
        handle.managed = True
        handle.state = "starting"
        handle.started = False
        handle.error = None
        handle.attempts += 1
        handle.cleanup_needed = True
        _detach(handle)
        start = _member(handle, "start") or _member(handle, "on_load")
        try:
            # user:“宿主能力补齐和接口完善与文档更新”+(每代配置门面绑定实际加载的清单，不用可串到其他插件的全局配置缓存)。
            scope = runtime_context._begin_registration_scope(handle.plugin.name, handle.attempts, manifest=handle.plugin)
            if callable(start):
                await _bounded(handle, start(runtime_context) if _accepts_context(start) else start(), "start")
            await _health(handle)
            scope.publish({handle.plugin.name, *(f"{handle.plugin.name}.{key}" for key in handle.services)})
            handle.state = "ready"
            if not _resources_alive(handle):
                raise RuntimeError("backend resources terminated during startup")
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            if isinstance(exc, asyncio.CancelledError) and handle.stop_requested:
                handle.state = "stopping"
                raise
            error = _failed(handle, "start", exc)
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise error from exc
        handle.started = True
        handle.error = None
        attach_plugin_runtime(handle, runtime_context)
        _monitor(handle)


async def stop_plugin_backend(handle: PluginRuntimeHandle) -> None:
    handle.stop_requested = True
    try:
        await _stop_backend(handle)
    finally:
        handle.stop_requested = False


async def _stop_backend(handle: PluginRuntimeHandle) -> None:
    handle.state = "stopping"
    handle.started = False
    _detach(handle)
    startup = handle.startup_task
    if startup is not None and startup is not asyncio.current_task() and not startup.done():
        startup.cancel()
        await asyncio.gather(startup, return_exceptions=True)
    monitor = handle.monitor_task
    if monitor is not None and monitor is not asyncio.current_task():
        monitor.cancel()
        await asyncio.gather(monitor, return_exceptions=True)
    async with handle.lock:
        handle.state = "stopping"
        if not handle.cleanup_needed:
            handle.state = "stopped"
            return
        stop = _member(handle, "stop") or _member(handle, "on_unload")
        try:
            scope = handle.context._registration_scope if handle.context is not None else None
            if scope is not None:
                # The bounded await runs in a separate Task, so check the
                # initiating service caller before scheduling the drain.
                scope.check_can_drain()
                await _bounded(handle, scope.drain(), "stop")
            try:
                if callable(stop):
                    await _bounded(handle, stop(), "stop")
            finally:
                if scope is not None:
                    await _bounded(handle, scope.dispose(), "stop")
            pending = {task for task in handle.pending_tasks if not task.done()}
            if pending:
                _, still_pending = await asyncio.wait(pending, timeout=_timeout(handle, "stop"))
                if still_pending:
                    raise PluginLifecycleError(handle.plugin.name, "stop", TimeoutError("a previous lifecycle task has not terminated"), code="PLUGIN_BACKEND_TIMEOUT")
            # Resources are explicitly owned inventories, never inferred PIDs.
            for task in _member(handle, "lifecycle_tasks", ()) or ():
                if not task.done():
                    task.cancel()
                    await _bounded(handle, asyncio.gather(task, return_exceptions=True), "stop")
                elif not task.cancelled():
                    task.exception()
            for process in _member(handle, "lifecycle_processes", ()) or ():
                code = process.poll() if callable(getattr(process, "poll", None)) else process.returncode
                if code is None:
                    process.terminate()
                    wait = process.wait
                    await _bounded(handle, wait() if inspect.iscoroutinefunction(wait) else asyncio.to_thread(wait), "stop")
        except asyncio.CancelledError as exc:
            _failed(handle, "stop", exc)
            raise
        except Exception as exc:
            raise _failed(handle, "stop", exc) from exc
        handle.state = "stopped"
        handle.cleanup_needed = False


def plugin_backend_available(plugin: PluginManifest, handles: list[PluginRuntimeHandle]) -> bool:
    from .safety import safe_mode
    if safe_mode() or not plugin.enabled:
        return False
    if backend_entry(plugin) is None:
        return True
    handle = next((item for item in handles if item.plugin.name == plugin.name), None)
    return handle is not None and _resources_alive(handle)


def _schedule_start(handle: PluginRuntimeHandle, context: PluginContext) -> None:
    handle.state = "starting"
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(
        _start_managed(handle, context),
        name=f"plugin:{handle.plugin.name}:on-load",
    )
    handle.startup_task = task
    task.add_done_callback(lambda result: None if result.cancelled() else result.exception())
    context.services.setdefault("plugin.lifecycle.tasks", []).append(task)


async def _start_managed(handle: PluginRuntimeHandle, context: PluginContext) -> None:
    try:
        await start_plugin_backend(handle, context)
    except (Exception, asyncio.CancelledError):
        if handle.stop_requested:
            # The host stop that cancelled startup owns cleanup. Do not call
            # the hook again from the cancelled startup task.
            raise
        diagnostic = handle.error
        try:
            await stop_plugin_backend(handle)
        except (Exception, asyncio.CancelledError) as cleanup:
            if diagnostic is not None:
                diagnostic = {**diagnostic, "cleanup_error": str(cleanup)}
        handle.started, handle.state = False, "failed"
        handle.error = handle.last_error = diagnostic
        raise


async def await_plugin_backends(handles: list[PluginRuntimeHandle]) -> None:
    """Join isolated, bounded startups before the host reports readiness."""
    tasks = []
    for handle in handles:
        if handle.managed and handle.state in {"loaded", "starting"} and handle.startup_task is None:
            _schedule_start(handle, handle.context)
        if handle.startup_task is not None:
            tasks.append(handle.startup_task)
    await asyncio.gather(*tasks, return_exceptions=True)


def _accepts_context(func: Any) -> bool:
    try:
        import inspect

        return len(inspect.signature(func).parameters) > 0
    except (TypeError, ValueError):
        return False


async def shutdown_plugin_backends(handles: list[PluginRuntimeHandle]) -> None:
    for handle in reversed(handles):
        try:
            await stop_plugin_backend(handle)
        except Exception:  # noqa: BLE001 — shutdown is best effort
            _logger.warning("[plugins:backend] failed to stop %s", handle.plugin.name, exc_info=True)


def scene_for_plugin(plugin: PluginManifest) -> str:
    from lamtools_core.config.model_selection import scene_for_plugin as _scene_for_plugin

    return _scene_for_plugin(plugin)


__all__ = [
    "PluginRuntimeHandle",
    "PluginLifecycleError",
    "plugin_backend_available",
    "await_plugin_backends",
    "backend_entry",
    "load_plugin_backend",
    "load_enabled_plugin_backends",
    "attach_plugin_runtime",
    "start_plugin_backend",
    "stop_plugin_backend",
    "shutdown_plugin_backends",
]
