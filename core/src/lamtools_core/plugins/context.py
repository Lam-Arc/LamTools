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

    def operation_executor(self) -> Callable[[str, dict[str, Any], dict[str, Any]], Awaitable[Any]]:
        """Build the common operation executor used by plugin tools."""
        async def execute(name: str, payload: dict[str, Any], metadata: dict[str, Any] | None = None) -> Any:
            catalog = self.operation_catalog
            if catalog is None:
                raise RuntimeError("operation catalog is not configured")
            return await catalog.execute(name, payload, metadata=metadata or {})

        return execute

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
