"""Runtime dependencies exposed to plugin backends.

The context is intentionally capability-oriented.  A plugin receives one
object instead of importing the HTTP application or reaching into Core's
private state.  ``services`` is the escape hatch for host integrations which
are not part of the stable minimum protocol.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable


PluginEventSink = Callable[[Any], Awaitable[None] | None]


@dataclass
class PluginContext:
    """Dependencies available to one plugin instance.

    ``work_root`` is deliberately mutable through :meth:`for_work_root`; a
    long-lived plugin must not infer the active project from process startup.
    """

    work_root: Path
    data_dir: Path | None = None
    app_data_dir: Path | None = None
    operation_catalog: Any | None = None
    permission_service: Any | None = None
    event_bus: Any | None = None
    runtime_task_registry: Any | None = None
    llm_client: Any | None = None
    model_id: str = ""
    event_sink: PluginEventSink | None = None
    services: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    #: The context this view was derived from (set by :meth:`for_scene`).
    #: Late-bound fields assigned on the original *after* the view was created
    #: (``operation_catalog`` is set once the operation catalog exists) are
    #: resolved through this live reference.
    parent: "PluginContext | None" = None

    def __post_init__(self) -> None:
        self.work_root = Path(self.work_root).resolve()
        if self.data_dir is not None:
            self.data_dir = Path(self.data_dir).resolve()
        if self.app_data_dir is not None:
            self.app_data_dir = Path(self.app_data_dir).resolve()

    def service(self, name: str, default: Any = None) -> Any:
        return self.services.get(name, default)

    def set_service(self, name: str, value: Any) -> None:
        self.services[name] = value

    def remove_service(self, name: str) -> None:
        self.services.pop(name, None)

    def for_work_root(self, work_root: str | Path | None) -> "PluginContext":
        """Return a shallow context view for the active project root."""
        if not work_root:
            return self
        return PluginContext(
            work_root=Path(work_root),
            data_dir=self.data_dir,
            app_data_dir=self.app_data_dir,
            operation_catalog=self.operation_catalog,
            permission_service=self.permission_service,
            event_bus=self.event_bus,
            runtime_task_registry=self.runtime_task_registry,
            llm_client=self.llm_client,
            model_id=self.model_id,
            event_sink=self.event_sink,
            services=self.services,
            metadata=self.metadata,
        )

    def for_scene(self, scene: str) -> "PluginContext":
        """Return a view whose ``model_id`` is the model of ``scene``.

        Each plugin backend is handed its own scene's model (Study → study,
        the desktop pet → desktop_pet, anything else → background) so a
        plugin's model calls never inherit the main conversation's model by
        accident.  The ``services`` dict is shared by reference, so services
        registered after the backend is created stay visible.
        """
        view = self.for_work_root(self.work_root)
        if view is self:
            view = PluginContext(
                work_root=self.work_root,
                data_dir=self.data_dir,
                app_data_dir=self.app_data_dir,
                operation_catalog=self.operation_catalog,
                permission_service=self.permission_service,
                event_bus=self.event_bus,
                runtime_task_registry=self.runtime_task_registry,
                llm_client=self.llm_client,
                event_sink=self.event_sink,
                services=self.services,
                metadata=self.metadata,
            )
        from lamtools_core.config.model_selection import ModelResolutionError, resolve_scene_model

        # Keep a live link to the originating context: fields it assigns later
        # (notably ``operation_catalog``) must stay reachable from this view.
        view.parent = self
        try:
            view.model_id = resolve_scene_model(scene).model_id
        except ModelResolutionError:
            # No model for this scene: leave it empty so the plugin's model
            # call fails with the explicit "请先添加供应商/模型" message instead
            # of silently borrowing another scene's model.
            view.model_id = ""
        return view

    def operation_executor(self) -> Callable[[str, dict[str, Any], dict[str, Any]], Awaitable[Any]]:
        """Build the common operation executor used by plugin tools."""
        async def execute(name: str, payload: dict[str, Any], metadata: dict[str, Any] | None = None) -> Any:
            catalog = self.resolved_operation_catalog()
            if catalog is None:
                raise RuntimeError("operation catalog is not configured")
            return await catalog.execute(name, payload, metadata=metadata or {})

        return execute

    def resolved_operation_catalog(self) -> Any | None:
        """Return the operation catalog, following the parent chain.

        The catalog is assigned to the originating context *after* plugin
        backends are loaded, so a derived view (``for_scene``) must read it
        through the live parent reference rather than the value it copied.
        """
        context: PluginContext | None = self
        while context is not None:
            if context.operation_catalog is not None:
                return context.operation_catalog
            context = context.parent
        return None

    async def emit(self, event: Any) -> None:
        """Deliver a plugin event through the host's event sink if present."""
        sink = self.event_sink
        if sink is not None:
            result = sink(event)
            if inspect.isawaitable(result):
                await result
            return
        bus = self.event_bus
        publish = getattr(bus, "publish", None)
        if callable(publish):
            result = publish(event)
            if inspect.isawaitable(result):
                await result


__all__ = ["PluginContext", "PluginEventSink"]
