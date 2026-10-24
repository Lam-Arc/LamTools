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
        while handle.state == "ready":
            await asyncio.sleep(1.0)
            if not _resources_alive(handle):
                return
            try:
                await _health(handle)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _failed(handle, "health", exc)
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
    digest = hashlib.sha1(str(entry).encode("utf-8")).hexdigest()[:12]
    package_name = f"_lamtools_plugin_{plugin.name.replace('-', '_')}_{digest}"
    spec = importlib.util.spec_from_file_location(
        package_name,
        entry,
        submodule_search_locations=[str(entry.parent)],
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load plugin backend: {entry}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[package_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        if sys.modules.get(package_name) is module:
            sys.modules.pop(package_name, None)
        raise
    return module


def load_plugin_backend(plugin: PluginManifest, context: PluginContext) -> PluginRuntimeHandle | None:
    """Load a plugin's optional backend (``backend`` declaration or convention).

    A backend may expose ``create_plugin(context)`` or ``create_runtime``.
    Missing backends are normal for declarative-only plugins.
    """
    entry = backend_entry(plugin)
    if entry is None:
        return None
    if not entry.is_file():
        raise ValueError(f"plugin backend entry does not exist: {entry}")
    module = _load_module(plugin, entry)
    factory = getattr(module, "create_plugin", None) or getattr(module, "create_runtime", None)
    # Hand each backend its own scene's model so a plugin never inherits the
    # main conversation's model (see PluginContext.for_scene).
    plugin_context = context.for_scene(scene_for_plugin(plugin))
    value = factory(plugin_context) if callable(factory) else module
    if inspect.isawaitable(value):
        if inspect.iscoroutine(value):
            value.close()
        raise TypeError("backend factory must be synchronous; use async start for initialization")
    if value is None:
        value = module
    if isinstance(value, PluginRuntimeHandle):
        value.context = context
        return value
    if isinstance(value, dict):
        return PluginRuntimeHandle(
            plugin=plugin,
            value=value.get("runtime", value),
            tool_handlers=dict(value.get("tool_handlers") or {}),
            tool_providers=list(value.get("tool_providers") or []),
            services=dict(value.get("services") or {}),
            context=context,
        )
    return PluginRuntimeHandle(
        plugin=plugin,
        value=value,
        tool_handlers=dict(getattr(value, "tool_handlers", {}) or {}),
        tool_providers=list(getattr(value, "tool_providers", []) or []),
        services=dict(getattr(value, "services", {}) or {}),
        context=context,
    )


def load_enabled_plugin_backends(
    plugins: list[PluginManifest],
    context: PluginContext,
    *,
    start: bool = False,
) -> list[PluginRuntimeHandle]:
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
            attach_plugin_runtime(handle, context)
            _monitor(handle)
    return handles


def attach_plugin_runtime(handle: PluginRuntimeHandle, context: PluginContext) -> None:
    context.set_service(handle.plugin.name, handle.value)
    for key, value in handle.services.items():
        context.set_service(f"{handle.plugin.name}.{key}", value)


async def start_plugin_backend(handle: PluginRuntimeHandle, context: PluginContext) -> None:
    async with handle.lock:
        if handle.stop_requested:
            raise PluginLifecycleError(handle.plugin.name, "start", RuntimeError("backend is stopping"), code="PLUGIN_BACKEND_BUSY")
        if handle.started and _resources_alive(handle):
            return
        if any(not task.done() for task in handle.pending_tasks):
            raise PluginLifecycleError(handle.plugin.name, "start", RuntimeError("previous lifecycle task has not terminated"), code="PLUGIN_BACKEND_BUSY")
        handle.context = context
        handle.managed = True
        handle.state = "starting"
        handle.started = False
        handle.error = None
        handle.attempts += 1
        handle.cleanup_needed = True
        _detach(handle)
        start = _member(handle, "start") or _member(handle, "on_load")
        try:
            if callable(start):
                await _bounded(handle, start(context) if _accepts_context(start) else start(), "start")
            await _health(handle)
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
        attach_plugin_runtime(handle, context)
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
            if callable(stop):
                await _bounded(handle, stop(), "stop")
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
    if not plugin.enabled:
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
