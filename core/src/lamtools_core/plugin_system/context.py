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
    _plugin_manifest: Any | None = field(default=None, repr=False)
    # user:“继续，把 2 阶段都做完”+(执行目录独立于配置/模型/项目根；不改变现有构造参数顺序)。
    execution_root: Path | None = None

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

    def _begin_registration_scope(self, owner: str, epoch: int, *, manifest=None) -> RegistrationScope:
        previous = self._registration_scope
        if previous is not None and not previous.disposed:
            raise ServiceError("service/cleanup-required", owner, "previous registration scope must finish cleanup")
        self._registration_scope = RegistrationScope(self._service_registry, owner, epoch)
        self._plugin_manifest = manifest
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
    def subagents(self):
        # user:“继续”+(具名子代理门面复用原监督器和持久邮箱，原项目/插件决定命名空间)。
        from .subagent_access import PluginSubagentAPI
        return PluginSubagentAPI(self, self._active_registration_scope())

    @property
    def attachments(self):
        # user:“给我把 2 阶段做完，前端除外”+(受管附件接口固定项目和会话归属)。
        from .session_data import PluginAttachmentAPI
        return PluginAttachmentAPI(self.require_service("session_data"), self._active_registration_scope(), self.work_root, "attachments")

    @property
    def browser_use(self):
        # user:“每一个地方 sunday 都有等价或者近似接口”+(对应上游独占提供方名称槽，不冒充浏览器操作)。
        from .capability_seams import NamedCapabilityAPI
        return NamedCapabilityAPI(self, self._active_registration_scope(), "browser-use")

    @property
    def computer_use(self):
        from .capability_seams import NamedCapabilityAPI
        return NamedCapabilityAPI(self, self._active_registration_scope(), "computer-use")

    @property
    def lsp(self):
        from .capability_seams import PluginLspAPI
        return PluginLspAPI(self, self._active_registration_scope())

    @property
    def mcp_resources(self):
        # user:“给我把 2 阶段做完，前端除外”+(每个插件/项目视图复用有限资源连接，停用统一回收)。
        from .mcp_resources import PluginMcpResourcesAPI
        scope = self._active_registration_scope()
        key = (scope, str(self.work_root))
        cached = getattr(self, "_mcp_resources_cache", None)
        if cached is None or cached[0] != key:
            cached = (key, PluginMcpResourcesAPI(self, scope))
            self._mcp_resources_cache = cached
        return cached[1]

    @property
    def session_title(self):
        from .session_data import PluginTitleAPI
        return PluginTitleAPI(self.require_service("session_data"), self._active_registration_scope(), self.work_root, "title")

    @property
    def tool_result_pruner(self):
        # user:“给我把 2 阶段做完，前端除外”+(Unicode裁剪保留富内容，不改历史或伪造压缩重放)。
        from .content_access import PluginResultPrunerAPI
        return PluginResultPrunerAPI(self._active_registration_scope())

    @property
    def file_references(self):
        from .content_access import PluginFileReferencesAPI
        return PluginFileReferencesAPI(self.execution_root or self.work_root, self._active_registration_scope())

    @property
    def web(self):
        from .content_access import PluginWebAPI
        return PluginWebAPI(self, self._active_registration_scope())

    @property
    def ptc_runtime(self):
        # user:“给我把 2 阶段做完，前端除外”+(程序使用真实Windows Job所有者，明确无DSH SDK桥或隔离承诺)。
        from .program_access import PluginProgramAPI
        return PluginProgramAPI(self, self._active_registration_scope())

    @property
    def terminals(self):
        # user:“给我把 2 阶段做完，前端除外”+(交互终端沿用同一受管进程，停用回收)。
        from .terminal_access import PluginTerminalsAPI
        return PluginTerminalsAPI(self, self._active_registration_scope())

    @property
    def authorization(self):
        # user:“给我把 2 阶段做完，前端除外”+(授权流程与工具审批分开；使用真实凭据提交和双端租约)。
        from .authorization_access import PluginAuthorizationAPI
        return PluginAuthorizationAPI(self, self._active_registration_scope())

    @property
    def dynamic_runner(self):
        from .program_access import PluginDynamicRunnerAPI
        scope = self._active_registration_scope()
        key = (scope, str(self.work_root), str(self.execution_root))
        cached = getattr(self, "_dynamic_runner_cache", None)
        if cached is None or cached[0] != key:
            cached = (key, PluginDynamicRunnerAPI(self, scope))
            self._dynamic_runner_cache = cached
        return cached[1]

    @property
    def plan_mode(self):
        from .content_access import PluginPlanModeAPI
        scope = self._active_registration_scope()
        cached = getattr(self, "_plan_mode_cache", None)
        if cached is None or cached[0] is not scope:
            cached = (scope, PluginPlanModeAPI(self, scope))
            self._plan_mode_cache = cached
        return cached[1]

    @property
    def session_projections(self):
        from .session_data import PluginProjectionAPI
        return PluginProjectionAPI(self.require_service("session_data"), self._active_registration_scope(), self.work_root, "projections")

    @property
    def message_feedback(self):
        # user:“给我把 2 阶段做完，前端除外”+(反馈使用会话持久化和版本控制，不依赖界面)。
        from .session_data import PluginFeedbackAPI
        return PluginFeedbackAPI(self.require_service("session_data"), self._active_registration_scope(), self.work_root, "message-feedback")

    @property
    def session_feedback(self):
        from .session_data import PluginFeedbackAPI
        return PluginFeedbackAPI(self.require_service("session_data"), self._active_registration_scope(), self.work_root, "session-feedback")

    @property
    def session_references(self):
        # user:“给我把 2 阶段做完，前端除外”+(跨会话引用须显式选择与有限摘录，不自动泄露或注入)。
        from .session_data import PluginSessionReferencesAPI
        return PluginSessionReferencesAPI(self.require_service("session_data"), self._active_registration_scope(), self.work_root, "references")

    @property
    def checkpoints(self):
        # user:“继续，把 2 阶段都做完”+(原检查点操作的受管入口，固定调用时的宿主，保留原恢复范围)。
        from .checkpoint_access import PluginCheckpointAPI
        return PluginCheckpointAPI(self, self._active_registration_scope())

    @property
    def working_directory(self):
        return self.require_service("working_directory").for_scope(self._active_registration_scope())

    async def for_session(self, session_id: str) -> "PluginContext":
        # user:“继续，把 2 阶段都做完”+(按持久目录取得固定执行视图，项目配置仍按原项目解析)。
        scope = self._active_registration_scope()
        state = await self.working_directory.get(session_id)
        scope.check_open()
        if not state.exists:
            from .working_directory import WorkingDirectoryError
            raise WorkingDirectoryError("working-directory/missing", "Execution directory is missing; explicitly ensure or select another directory")
        view = self.for_work_root(state.project_root)
        view.execution_root = Path(state.path)
        view.parent = self
        return view

    @property
    def questions(self):
        # user:“继续，把 2 阶段都做完”+(普通问答独立于审批，回答者和请求绑定启动代)。
        from .question_access import PluginQuestionAPI
        scope = self._active_registration_scope()
        cached = getattr(self, "_question_access_cache", None)
        if cached is None or cached[0] is not scope:
            cached = (scope, PluginQuestionAPI(self, scope))
            self._question_access_cache = cached
        return cached[1]

    @property
    def spill_store(self):
        # user:“继续，把 2 阶段都做完”+(长文本定位返回真实插件数据文件，保存不等于模型读取授权)。
        from .spill_access import PluginSpillAPI
        return PluginSpillAPI(self, self._active_registration_scope())

    @property
    def jobs(self):
        # user:“继续，把 2 阶段都做完”+(后台工作按插件启动代与项目视图缓存，停用取消并 join 回调)。
        from .jobs_access import PluginJobsAPI
        scope = self._active_registration_scope()
        key = (scope, str(self.work_root))
        cached = getattr(self, "_jobs_access_cache", None)
        if cached is None or cached[0] != key:
            cached = (key, PluginJobsAPI(scope))
            self._jobs_access_cache = cached
        return cached[1]

    @property
    def shell_env(self):
        # user:“继续，把 2 阶段都做完”+(环境注册绑定启动代，共享宿主贡献表，不改变系统环境)。
        from .shell_access import PluginShellEnvironmentAPI
        return PluginShellEnvironmentAPI(self, self._active_registration_scope())

    @property
    def shell(self):
        # user:“继续，把 2 阶段都做完”+(shell 复用受管原生进程，显式命令/超时，不冒充终端或沙箱)。
        from .shell_access import PluginShellAPI
        return PluginShellAPI(self, self._active_registration_scope())

    @property
    def plugins(self):
        # user:“继续，把 2 阶段都做完”+(插件管理使用现有事务，禁止在自己的活跃调用中停止自身)。
        from .management_access import PluginManagementAPI
        return PluginManagementAPI(self, self._active_registration_scope(), "plugin.system")

    @property
    def profiles(self):
        # user:“继续，把 2 阶段都做完”+(运行档读取直接复用当前宿主解析结果，不改审批/工具面)。
        from .management_access import PluginManagementAPI
        return PluginManagementAPI(self, self._active_registration_scope(), "profile")

    @property
    def approvals(self):
        # user:“继续，把 2 阶段都做完”+(审批请求绑定启动代和原会话宿主，默认缺少回答者不允许执行)。
        return self.require_service("approval_access").for_scope(self._active_registration_scope())

    @property
    def session_query(self):
        # user:“继续，把 2 阶段都做完”+(会话目录查询绑定当前启动代，复用宿主可见性与有限扫描)。
        return self.require_service("session_query").for_scope(self._active_registration_scope())

    @property
    def goals(self):
        # user:“继续，把 2 阶段都做完”+(持久目标固定插件与项目，复用实际业务目录)。
        from .durable_access import PluginDurableAPI
        return PluginDurableAPI(self, self._active_registration_scope(), "goal")

    @property
    def schedule(self):
        # user:“继续，把 2 阶段都做完”+(持久计划使用已有安排 Runner，停用不删除已提交意图)。
        from .durable_access import PluginDurableAPI
        return PluginDurableAPI(self, self._active_registration_scope(), "arrange")

    @property
    def llm(self):
        # user:“继续，把 2 阶段都做完”+(实际模型调用绑定当前启动代、项目和宿主客户端，不能用只读目录冒充调用能力)。
        from .llm_access import PluginLLMAPI
        scope = self._active_registration_scope()
        service = self.service("model_catalog")
        key = (scope, str(self.work_root), id(self.llm_client), id(service))
        cached = getattr(self, "_llm_access_cache", None)
        if cached is None or cached[0] != key:
            models = service.for_scope(scope, self.work_root) if service is not None else None
            cached = (key, PluginLLMAPI(scope, self.work_root, self.llm_client, models, self.model_id))
            self._llm_access_cache = cached
        return cached[1]

    @property
    def processes(self):
        # user:“宿主能力补齐和接口完善与文档更新”+(进程基础工具绑定当前启动代，不暴露未经生命周期验收的 spawn)。
        from .process_access import PluginProcessAPI
        scope = self._active_registration_scope()
        directory = self.execution_root if self.execution_root is not None else self.work_root
        key = (scope, str(directory))
        cached = getattr(self, "_process_access_cache", None)
        if cached is None or cached[0] != key:
            cached = (key, PluginProcessAPI(scope, directory))
            self._process_access_cache = cached
        return cached[1]

    @property
    def permissions(self):
        # user:“宿主能力补齐和接口完善与文档更新”+(权限读侧绑定启动代，不返回策略修改器或批准凭证)。
        scope = self._active_registration_scope()
        return self.require_service("permission_access").for_scope(scope)

    @property
    def compaction(self):
        # user:“宿主能力补齐和接口完善与文档更新”+(手动压缩固定当前插件代与目录，由桌面会话宿主执行)。
        return self.require_service("compaction_control").for_scope(self._active_registration_scope(), self.work_root)

    @property
    def filesystem(self):
        # user:“宿主能力补齐和接口完善与文档更新”+(文件视图固定当前工作目录和启动代，后续目录变化不改写已有视图)。
        from .filesystem_access import PluginFilesystemAPI
        scope = self._active_registration_scope()
        directory = self.execution_root if self.execution_root is not None else self.work_root
        key = (scope, str(directory), str(self.data_dir))
        cached = getattr(self, "_filesystem_access_cache", None)
        if cached is None or cached[0] != key:
            cached = (key, PluginFilesystemAPI(directory, scope, self.data_dir))
            self._filesystem_access_cache = cached
        return cached[1]

    @property
    def config(self):
        # user:“宿主能力补齐和接口完善与文档更新”+(配置只能取当前受管启动对应的清单，不能自行指定其他插件路径)。
        scope = self._active_registration_scope()
        if self._plugin_manifest is None or self._plugin_manifest.name != scope.owner:
            raise LookupError("Managed plugin manifest is unavailable")
        from .config_access import PluginConfigAPI
        return PluginConfigAPI(self._plugin_manifest, scope, self.data_dir)

    @property
    def credentials(self):
        # user:“每一个地方 sunday 都有等价或者近似接口”+(凭据只能从宿主私有存储取得当前 owner 的受管视图，不能指定其他插件)。
        scope = self._active_registration_scope()
        if self._secret_store is None:
            raise LookupError("Host credential store is unavailable")
        return self._secret_store.for_scope(scope)

    @property
    def storage(self):
        # user:“宿主能力补齐和接口完善与文档更新”+(存储命名空间由当前启动代 owner 决定，调用方不能指定另一个插件)。
        return self.require_service("plugin_storage").for_scope(self._active_registration_scope())

    @property
    def models(self):
        # user:“每一个地方 sunday 都有等价或者近似接口”+(模型读取只返回安全元数据，并保持当前插件代与项目范围)。
        return self.require_service("model_catalog").for_scope(self._active_registration_scope(), self.work_root)

    @property
    def skills(self):
        # user:“宿主能力补齐和接口完善与文档更新”+(技能门面只登记当前受管启动代的内存说明)。
        return self.require_service("skill_extensions").for_scope(self._active_registration_scope())

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
        self.execution_root = other.execution_root
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
            _plugin_manifest=self._plugin_manifest,
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
        view.execution_root = self.execution_root
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
