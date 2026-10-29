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
from typing import Any, Awaitable, Callable, TypeVar

from .services import HostServiceRegistry, RegistrationScope, ServiceError, ServiceKey, ServiceRef, ServiceRegistration, service_key

T = TypeVar("T")


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
    #: Services visible only to this context view (not shared with other
    #: plugin backends).  The host uses this for per-plugin secret views.
    scoped_services: dict[str, Any] = field(default_factory=dict)
    #: Host-owned secret store.  It is deliberately not a service: exposing the
    #: store would let one plugin read another plugin's namespace.
    _secret_store: Any = field(default=None, repr=False)
    metadata: dict[str, Any] = field(default_factory=dict)
    #: The context this view was derived from (set by :meth:`for_scene`).
    #: Late-bound fields assigned on the original *after* the view was created
    #: (``operation_catalog`` is set once the operation catalog exists) are
    #: resolved through this live reference.
    parent: "PluginContext | None" = None
    _service_registry: HostServiceRegistry | None = field(default=None, repr=False)
    _registration_scope: RegistrationScope | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self._service_registry is None:
            self._service_registry = HostServiceRegistry(self.services)
        self.work_root = Path(self.work_root).resolve()
        if self.data_dir is not None:
            self.data_dir = Path(self.data_dir).resolve()
        if self.app_data_dir is not None:
            self.app_data_dir = Path(self.app_data_dir).resolve()

    def service(self, name: str, default: Any = None) -> Any:
        if name in self.scoped_services:
            return self.scoped_services[name]
        local = self._registration_scope.local(name) if self._registration_scope is not None else None
        if local is not None:
            return local.value
        return self.services.get(name, default)

    def _active_registration_scope(self) -> RegistrationScope:
        if self._registration_scope is None:
            raise ServiceError("service/scope-unavailable", "context", "registration requires managed startup (start/on_load)")
        self._registration_scope.check_open()
        return self._registration_scope

    def _begin_registration_scope(self, owner: str, epoch: int) -> RegistrationScope:
        previous = self._registration_scope
        if previous is not None and not previous.disposed:
            raise ServiceError("service/cleanup-required", owner, "previous registration scope must finish cleanup")
        self._registration_scope = RegistrationScope(self._service_registry, owner, epoch)
        return self._registration_scope

    def register_service(self, key: ServiceKey[T] | str, value: T) -> ServiceRegistration[T]:
        # user:“宿主能力补齐和接口完善与文档更新”+(服务注册归当前插件启动所有，随停用撤回，不能覆盖其他插件或宿主)。
        return self._active_registration_scope().register(service_key(key), value)

    def bind_service(self, key: ServiceKey[T] | str) -> ServiceRef[T]:
        typed_key = service_key(key)
        requester = self._registration_scope
        if requester is not None:
            requester.check_open()
        def resolve():
            if typed_key.name in self.scoped_services:
                value = self.scoped_services[typed_key.name]
                token = value
            else:
                local = requester.local(typed_key.name) if requester is not None else None
                record = local or self._service_registry.record(typed_key.name)
                value = record.value if record is not None else self.services.get(typed_key.name)
                token = record if record is not None else value
            if value is None:
                raise ServiceError("service/unavailable", typed_key.name, "required service is missing")
            return value, token
        reference = ServiceRef(typed_key, resolve, requester)
        if requester is not None:
            requester.dependencies.append(reference)
        return reference

    def on_dispose(self, cleanup: Callable) -> None:
        self._active_registration_scope().on_dispose(cleanup)

    def effect(self, setup: Callable) -> None:
        self._active_registration_scope().effect(setup)

    @property
    def commands(self):
        # user:“宿主能力补齐和接口完善与文档更新”+(斜杠命令只登记到当前受管启动代，不能在工厂或停用后泄露注册)。
        return self.require_service("command_extensions").for_scope(self._active_registration_scope())

    @property
    def prompts(self):
        # user:“宿主能力补齐和接口完善与文档更新”+(提示词门面绑定当前插件启动代，沿用既有流水线)。
        waterfall = self.require_service("system_prompt_waterfall")
        return waterfall.for_scope(self._active_registration_scope())

    @property
    def tools(self):
        # user:“每一个地方 sunday 都有等价或者近似接口”+(工具贡献自动绑定当前插件代际，不要求插件自行维护全局注册表)。
        host = self.require_service("tool_extensions")
        return host.for_scope(self._active_registration_scope())

    def require_service(self, name: str) -> Any:
        # user:“宿主能力补齐和接口完善与文档更新”+(插件显式要求能力，缺失时给出可移植的错误，不能静默伪装成功)。
        value = self.service(name)
        if value is None:
            raise LookupError(f"host service '{name}' is missing; inspect describe_host()")
        return value

    def describe_host(self) -> dict[str, Any]:
        """Describe live names, without exporting service objects or credentials.

        This describes the Python context's call surface, not a Remote grant or
        a declaration that an external process can call back into the host.
        """
        names = sorted(set(self.services) | set(self.scoped_services))
        catalog = self.resolved_operation_catalog()
        descriptions = []
        for name in names:
            row = {"name": name, "available": self.service(name) is not None,
                   "scope": "plugin" if name in self.scoped_services else "host"}
            record = self._service_registry.record(name) if name not in self.scoped_services else None
            if record is not None:
                row.update(owner=record.scope.owner, version=record.key.version, epoch=record.scope.epoch)
            descriptions.append(row)
        return {
            "contractVersion": 1,
            "services": descriptions,
            "operations": catalog.list() if catalog is not None else [],
            "externalProcessHostCallbacks": False,
        }

    def set_service(self, name: str, value: Any) -> None:
        record = self._service_registry.record(name)
        if record is not None and value is not record.value:
            raise ServiceError("service/conflict", name, "cannot overwrite an owned service; withdraw it first")
        self.services[name] = value

    def remove_service(self, name: str) -> None:
        record = self._service_registry.record(name)
        if record is not None:
            record()
        self.services.pop(name, None)

    def set_scoped_service(self, name: str, value: Any) -> None:
        self.scoped_services[name] = value

    def remove_scoped_service(self, name: str) -> None:
        self.scoped_services.pop(name, None)

    def refresh_from(self, other: "PluginContext") -> "PluginContext":
        """Refresh host-level fields from a newer context, keeping scoped views.

        A backend keeps its plugin-scoped context (and therefore its secret
        view) across disable/enable and restart, while the host may hand in a
        context with a newer work root, catalog or service map.
        """
        self.work_root = Path(other.work_root)
        self.data_dir = Path(other.data_dir) if other.data_dir is not None else None
        self.app_data_dir = Path(other.app_data_dir) if other.app_data_dir is not None else None
        self.operation_catalog = other.operation_catalog
        self.permission_service = other.permission_service
        self.event_bus = other.event_bus
        self.runtime_task_registry = other.runtime_task_registry
        self.llm_client = other.llm_client
        self.model_id = other.model_id
        self.event_sink = other.event_sink
        self.services = other.services
        self._service_registry = other._service_registry
        if other._secret_store is not None:
            self._secret_store = other._secret_store
        return self

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
            scoped_services=dict(self.scoped_services),
            _secret_store=self._secret_store,
            metadata=self.metadata,
            _service_registry=self._service_registry,
            _registration_scope=self._registration_scope,
        )

    def for_scene(self, scene: str) -> "PluginContext":
        """Return a view whose ``model_id`` is the model of ``scene``.

        Each plugin backend is handed its own scene's model (Study → study,
        anything else → background) so a plugin's model calls never inherit
        the main conversation's model by accident.  The ``services`` dict is
        shared by reference, so services registered after the backend is
        created stay visible.
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
                scoped_services=dict(self.scoped_services),
                _secret_store=self._secret_store,
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
