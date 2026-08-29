"""Generic plugin backend loading and lifecycle helpers."""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import importlib.util
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

from .context import PluginContext
from .models import PluginManifest

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

    def __getattr__(self, name: str) -> Any:
        return getattr(self.value, name)


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
    spec.loader.exec_module(module)
    return module


def load_plugin_backend(plugin: PluginManifest, context: PluginContext) -> PluginRuntimeHandle | None:
    """Load a plugin's optional ``backend/__init__.py`` convention.

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
    value = factory(context) if callable(factory) else module
    if value is None:
        value = module
    if isinstance(value, PluginRuntimeHandle):
        return value
    if isinstance(value, dict):
        return PluginRuntimeHandle(
            plugin=plugin,
            value=value.get("runtime", value),
            tool_handlers=dict(value.get("tool_handlers") or {}),
            tool_providers=list(value.get("tool_providers") or []),
            services=dict(value.get("services") or {}),
        )
    return PluginRuntimeHandle(
        plugin=plugin,
        value=value,
        tool_handlers=dict(getattr(value, "tool_handlers", {}) or {}),
        tool_providers=list(getattr(value, "tool_providers", []) or []),
        services=dict(getattr(value, "services", {}) or {}),
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
            _logger.warning("[plugins:backend] failed to load %s: %s", plugin.name, exc, exc_info=True)
            continue
        if handle is None:
            continue
        attach_plugin_runtime(handle, context)
        handles.append(handle)
        if start:
            _schedule_start(handle, context)
    return handles


def attach_plugin_runtime(handle: PluginRuntimeHandle, context: PluginContext) -> None:
    context.set_service(handle.plugin.name, handle.value)
    for key, value in handle.services.items():
        context.set_service(f"{handle.plugin.name}.{key}", value)


async def start_plugin_backend(handle: PluginRuntimeHandle, context: PluginContext) -> None:
    if handle.started:
        return
    start = getattr(handle.value, "start", None) or getattr(handle.value, "on_load", None)
    if callable(start):
        result = start(context) if _accepts_context(start) else start()
        if asyncio.iscoroutine(result):
            await result
    handle.started = True


async def stop_plugin_backend(handle: PluginRuntimeHandle) -> None:
    if not handle.started and not callable(
        getattr(handle.value, "stop", None) or getattr(handle.value, "on_unload", None)
    ):
        return
    stop = getattr(handle.value, "stop", None) or getattr(handle.value, "on_unload", None)
    if callable(stop):
        result = stop()
        if asyncio.iscoroutine(result):
            await result
    handle.started = False


class PluginRuntimeManager:
    """Own the live backend handles and support enable/disable transitions."""

    def __init__(
        self,
        handles: list[PluginRuntimeHandle],
        context: PluginContext,
        *,
        plugin_resolver: Any,
    ) -> None:
        self.handles = handles
        self.context = context
        self.plugin_resolver = plugin_resolver
        # Keep stopped handles around so an enable transition can reactivate
        # the same runtime object.  Existing toolboxes may still hold a bound
        # provider; reusing the handle makes that provider recover on enable
        # instead of leaving a stale, permanently disabled closure behind.
        self._stopped_handles: dict[str, PluginRuntimeHandle] = {}

    def get(self, plugin_name: str) -> PluginRuntimeHandle | None:
        return next((item for item in self.handles if item.plugin.name == plugin_name), None)

    def is_enabled(self, plugin_name: str) -> bool:
        """Return whether a plugin contribution may execute right now."""
        plugin = self.plugin_resolver(plugin_name)
        if plugin is None or not plugin.enabled:
            return False
        # Declarative-only plugins have no live handle and are available as
        # soon as their manifest is enabled. Backends require an attached
        # handle; a stopped backend is intentionally unavailable until start
        # has reattached it.
        if plugin.backend_entry is not None:
            return self.get(plugin_name) is not None
        return True

    async def stop(self, plugin_name: str) -> bool:
        handle = self.get(plugin_name)
        if handle is None:
            return False
        await stop_plugin_backend(handle)
        self.handles[:] = [item for item in self.handles if item is not handle]
        self._stopped_handles[plugin_name] = handle
        self.context.remove_service(plugin_name)
        for key in handle.services:
            self.context.remove_service(f"{plugin_name}.{key}")
        return True

    async def start(self, plugin_name: str) -> bool:
        if self.get(plugin_name) is not None:
            return True
        plugin = self.plugin_resolver(plugin_name)
        if plugin is None or not plugin.enabled:
            return False
        handle = self._stopped_handles.pop(plugin_name, None)
        if handle is None:
            handle = load_plugin_backend(plugin, self.context)
        if handle is None:
            return False
        attach_plugin_runtime(handle, self.context)
        self.handles.append(handle)
        await start_plugin_backend(handle, self.context)
        return True

    async def shutdown(self) -> None:
        await shutdown_plugin_backends(self.handles)
        self.handles.clear()
        self._stopped_handles.clear()


def _schedule_start(handle: PluginRuntimeHandle, context: PluginContext) -> None:
    start = getattr(handle.value, "start", None) or getattr(handle.value, "on_load", None)
    if not callable(start):
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(
        start_plugin_backend(handle, context),
        name=f"plugin:{handle.plugin.name}:on-load",
    )
    context.services.setdefault("plugin.lifecycle.tasks", []).append(task)


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


__all__ = [
    "PluginRuntimeHandle",
    "backend_entry",
    "load_plugin_backend",
    "load_enabled_plugin_backends",
    "attach_plugin_runtime",
    "start_plugin_backend",
    "stop_plugin_backend",
    "PluginRuntimeManager",
    "shutdown_plugin_backends",
]
