"""Runtime contributions for the bundled Workflow plugin."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from lamtools_core.plugins.context import PluginContext

from .build_tools import workflow_build_tool_handlers, workflow_build_tool_specs
from .adapters import (
    AgentInvoker,
    AgentInvokerAdapter,
    LLMInvoker,
    LegacyAgentInvokerAdapter,
    LegacyModelInvokerAdapter,
    LegacyNodeExecutorAdapter,
    ModelInvoker,
    ModelInvokerAdapter,
    NodeExecutor,
    NodeExecutorAdapter,
    SubAgentInvoker,
    SubAgentInvokerAdapter,
    WorkflowDataPacketAdapter,
    adapt_data_packet,
    adapt_workflow_data,
)
from .cache import WorkflowContentCache
from .claims import ClaimAcquireResult, WorkflowClaimLease, WorkflowClaimStore
from .activations import (
    ACTIVATION_MARKER,
    WorkflowActivationError,
    activation_view,
    arrange_trigger,
    build_arrange_activation_payload,
    is_workflow_activation_job,
    normalize_workflow_trigger,
)
from .capabilities import (
    CapabilityDeclaration,
    CapabilityError,
    NodeCapability,
    NodeCapabilityRegistry,
    NodeCapabilities,
    ResourceClass,
    WorkflowCapabilityRegistry,
    WorkflowNodeCapabilities,
)
from .credentials import (
    CredentialError,
    CredentialRef,
    CredentialReference,
    CredentialResolver,
    WorkflowCredentialRef,
    WorkflowCredentialResolver,
    assert_no_secrets,
    redact_workflow_value,
    serialize_credential_ref,
    serialize_workflow_value,
)
from .data_packet import (
    ArtifactRef,
    AttachmentRef,
    DataPacket,
    DataPacketItem,
    WorkflowDataItem,
    WorkflowDataPacket,
    WorkflowDataPacketError,
    adapt_legacy_value,
    is_data_packet,
    packet_to_legacy,
)
from .document import (
    DOCUMENT_FORMAT,
    DOCUMENT_VERSION,
    PROMPT_FORMAT,
    PROMPT_VERSION,
    SEMANTIC_FORMAT,
    SEMANTIC_VERSION,
    WorkflowDocumentError,
    canonicalize_document,
    compile_document,
    document_from_workflow_def,
    export_comfyui,
    import_comfyui,
    semantic_graph,
    workflow_def_from_document,
    workflow_flow_control_policy,
)
from .flow_control import (
    ConcurrencyPolicy,
    DebounceMode,
    DebouncePolicy,
    FlowControlAcquireResult,
    FlowControlDecision,
    FlowControlError,
    FlowControlLease,
    FlowControlPolicy,
    FlowControlPolicyError,
    FlowControlResult,
    FlowControlStore,
    RateLimitPolicy,
    ThrottlePolicy,
    WorkflowConcurrencyPolicy,
    WorkflowRateLimitPolicy,
    WorkflowThrottlePolicy,
    WorkflowDebouncePolicy,
    WorkflowFlowControlPolicy,
    WorkflowFlowControlStore,
    canonical_scope_key,
    canonicalize_flow_control,
    canonicalize_flow_control_policy,
    canonicalize_policy,
    flow_control_from_document,
    flow_control_scope_key,
    make_scope_key,
    normalize_flow_control,
    normalize_flow_control_policy,
    normalize_policy,
    parse_flow_control,
    stable_scope_key,
)
from .node_versions import (
    NodeMigration,
    NodeMigrationRegistry,
    NodeVersionError,
    parse_node_version,
    resolve_node_version,
)
from .durable import (
    NodeExecutionPolicy,
    WorkflowAttempt,
    WorkflowNodeRun,
    WorkflowRun,
    WorkflowRunEvent,
    WorkflowRunEventStore,
    WorkflowRunProjector,
)
from .expressions import (
    EXPRESSION_SCHEMA,
    EXPRESSION_VERSION,
    ExpressionError,
    ExpressionLimits,
    evaluate as evaluate_expression,
    parse as parse_expression,
    validate as validate_expression,
)
from .executors import (
    DynamicExpansion,
    DynamicNodeExpansion,
    Expansion,
    NodeExecutionResult,
    NodeExecutorRegistry,
    WorkflowDynamicExpansion,
    WorkflowExpansion,
    WorkflowExpansionError,
    WorkflowExecutorError,
    WorkflowNodeExecutionResult,
    WorkflowExecutorRegistry,
    WorkflowNodeExecutor,
    normalize_execution_result,
    normalize_node_result,
)
from .history import WorkflowRunHistory
from .queue import QUEUE_STORE_VERSION, WorkflowRunQueue
from .registry import WorkflowNodeRegistry
from .runtime import WorkflowCapabilityError, WorkflowManager, WorkflowRunner
from .snapshots import WorkflowSnapshotStore
from .store import WorkflowStore
from .tools import WorkflowToolBundle, workflow_tool_provider
from .watcher import WorkflowFileWatcher


@dataclass
class WorkflowPluginRuntime:
    context: PluginContext
    store: WorkflowStore
    manager: WorkflowManager
    runner: WorkflowRunner
    node_registry: WorkflowNodeRegistry | None = None
    executor_registry: WorkflowExecutorRegistry | None = None
    queue: WorkflowRunQueue | None = None
    watcher: WorkflowFileWatcher | None = None
    _pending_work_roots: set[str] = field(default_factory=set, repr=False)
    _enabled: bool = field(default=True, init=False, repr=False)

    @property
    def tool_providers(self) -> list[Any]:
        return [self.workflow_tool_provider]

    @property
    def tool_handlers(self) -> dict[str, Any]:
        if not self._enabled:
            return {}
        return self.build_tool_handlers

    @property
    def build_tool_handlers(self) -> dict[str, Any]:
        executor = self.context.operation_executor()
        # Handlers resolve the active project from ToolCall.metadata. Do not
        # capture the project that happened to be open when the plugin loaded.
        return workflow_build_tool_handlers(executor)

    @property
    def tool_specs(self) -> list[Any]:
        if not self._enabled:
            return []
        return workflow_build_tool_specs()

    def workflow_tool_provider(self, work_root: str | None = None) -> Any:
        if not self._enabled:
            return WorkflowToolBundle(specs=[], handlers={}, names={})
        # Rebuild the provider with the active work root so project switching
        # never reuses the root captured at application startup.
        scoped_context = self.context.for_work_root(work_root or self.context.work_root)
        return workflow_tool_provider(
            self.store,
            scoped_context.operation_executor(),
            work_root=scoped_context.work_root,
        )()

    async def start(self, context: PluginContext | None = None) -> None:
        context = context or self.context
        self._enabled = True
        if self.watcher is None and context.event_bus is not None:
            roots = [str(context.work_root), *sorted(self._pending_work_roots)]
            self.watcher = WorkflowFileWatcher(
                self.store,
                context.event_bus,
                poll_interval=2.0,
                work_roots=roots,
            )
        if self.watcher is not None:
            await self.watcher.start()
        if self.queue is not None:
            await self.queue.start()

    async def stop(self) -> None:
        self._enabled = False
        if self.queue is not None:
            await self.queue.stop()
        if self.watcher is not None:
            await self.watcher.stop()
            self.watcher = None
        shutdown = getattr(self.runner, "shutdown", None)
        if callable(shutdown):
            result = shutdown()
            if hasattr(result, "__await__"):
                await result

    def watch_work_root(self, work_root: str | None) -> None:
        if not work_root:
            return
        from pathlib import Path

        root = str(Path(work_root).expanduser().resolve())
        self._pending_work_roots.add(root)
        if self.watcher is not None:
            self.watcher.add_work_root(root)


def create_plugin(context: PluginContext) -> WorkflowPluginRuntime:
    # Hosts may provide a store-compatible object for embedded/legacy local
    # runs.  Normal HTTP/GUI hosts leave this unset and the plugin owns its
    # durable WorkflowStore instance.
    store = context.service("workflow_store") or WorkflowStore()
    node_registry = context.service("workflow_node_registry") or WorkflowNodeRegistry()
    executor_registry = context.service("workflow_executor_registry") or WorkflowExecutorRegistry(node_registry)
    snapshot_store = context.service("workflow_snapshot_store") or WorkflowSnapshotStore(
        root=context.work_root,
        data_dir=context.data_dir,
    )
    event_store = context.service("workflow_event_store") or WorkflowRunEventStore(
        root=context.work_root,
        data_dir=context.data_dir,
    )
    cache_store = context.service("workflow_cache_store") or WorkflowContentCache(context.work_root)
    credential_resolver = context.service("credential_resolver")
    runtime = WorkflowPluginRuntime(
        context=context,
        store=store,
        manager=WorkflowManager(store, node_registry=node_registry),
        runner=WorkflowRunner(
            llm_client=context.llm_client,
            sub_agent_runner=context.service("sub_agent_runner"),
            emit=context.emit,
            runtime_task_registry=context.runtime_task_registry,
            workflow_store=store,
            permission_service=context.permission_service,
            snapshot_store=snapshot_store,
            event_store=event_store,
            cache_store=cache_store,
            credential_resolver=credential_resolver,
            node_registry=node_registry,
            executor_registry=executor_registry,
        ),
        node_registry=node_registry,
        executor_registry=executor_registry,
    )
    runtime.queue = WorkflowRunQueue(
        manager=runtime.manager,
        runner=runtime.runner,
        work_root=context.work_root,
        data_dir=context.data_dir,
        emit=context.emit,
    )
    return runtime


__all__ = [
    "WorkflowContentCache",
    "ACTIVATION_MARKER",
    "WorkflowActivationError",
    "activation_view",
    "arrange_trigger",
    "build_arrange_activation_payload",
    "is_workflow_activation_job",
    "normalize_workflow_trigger",
    "ArtifactRef",
    "AttachmentRef",
    "DataPacket",
    "DataPacketItem",
    "WorkflowDataItem",
    "WorkflowDataPacket",
    "WorkflowDataPacketError",
    "adapt_legacy_value",
    "is_data_packet",
    "packet_to_legacy",
    "CredentialError",
    "CredentialRef",
    "CredentialReference",
    "CredentialResolver",
    "WorkflowCredentialRef",
    "WorkflowCredentialResolver",
    "assert_no_secrets",
    "redact_workflow_value",
    "serialize_credential_ref",
    "serialize_workflow_value",
    "CapabilityDeclaration",
    "CapabilityError",
    "NodeCapability",
    "NodeCapabilityRegistry",
    "NodeCapabilities",
    "ResourceClass",
    "WorkflowCapabilityRegistry",
    "WorkflowNodeCapabilities",
    "NodeMigration",
    "NodeMigrationRegistry",
    "NodeVersionError",
    "parse_node_version",
    "resolve_node_version",
    "DOCUMENT_FORMAT",
    "DOCUMENT_VERSION",
    "PROMPT_FORMAT",
    "PROMPT_VERSION",
    "SEMANTIC_FORMAT",
    "SEMANTIC_VERSION",
    "WorkflowDocumentError",
    "canonicalize_document",
    "compile_document",
    "document_from_workflow_def",
    "export_comfyui",
    "import_comfyui",
    "semantic_graph",
    "workflow_def_from_document",
    "workflow_flow_control_policy",
    "ConcurrencyPolicy",
    "DebounceMode",
    "DebouncePolicy",
    "FlowControlAcquireResult",
    "FlowControlDecision",
    "FlowControlError",
    "FlowControlLease",
    "FlowControlPolicy",
    "FlowControlPolicyError",
    "FlowControlResult",
    "FlowControlStore",
    "RateLimitPolicy",
    "ThrottlePolicy",
    "WorkflowConcurrencyPolicy",
    "WorkflowRateLimitPolicy",
    "WorkflowThrottlePolicy",
    "WorkflowDebouncePolicy",
    "WorkflowFlowControlPolicy",
    "WorkflowFlowControlStore",
    "canonical_scope_key",
    "canonicalize_flow_control",
    "canonicalize_flow_control_policy",
    "canonicalize_policy",
    "flow_control_from_document",
    "flow_control_scope_key",
    "make_scope_key",
    "normalize_flow_control",
    "normalize_flow_control_policy",
    "normalize_policy",
    "parse_flow_control",
    "stable_scope_key",
    "AgentInvoker",
    "AgentInvokerAdapter",
    "LLMInvoker",
    "LegacyAgentInvokerAdapter",
    "LegacyModelInvokerAdapter",
    "LegacyNodeExecutorAdapter",
    "ModelInvoker",
    "ModelInvokerAdapter",
    "NodeExecutor",
    "NodeExecutorAdapter",
    "SubAgentInvoker",
    "SubAgentInvokerAdapter",
    "WorkflowDataPacketAdapter",
    "adapt_data_packet",
    "adapt_workflow_data",
    "NodeExecutionResult",
    "NodeExecutorRegistry",
    "DynamicExpansion",
    "DynamicNodeExpansion",
    "Expansion",
    "WorkflowDynamicExpansion",
    "WorkflowExpansion",
    "WorkflowExpansionError",
    "WorkflowExecutorError",
    "WorkflowNodeExecutionResult",
    "WorkflowExecutorRegistry",
    "WorkflowNodeExecutor",
    "normalize_execution_result",
    "normalize_node_result",
    "WorkflowNodeRegistry",
    "ClaimAcquireResult",
    "WorkflowClaimLease",
    "WorkflowClaimStore",
    "NodeExecutionPolicy",
    "WorkflowAttempt",
    "WorkflowNodeRun",
    "WorkflowRun",
    "WorkflowRunEvent",
    "WorkflowRunEventStore",
    "WorkflowRunProjector",
    "EXPRESSION_SCHEMA",
    "EXPRESSION_VERSION",
    "ExpressionError",
    "ExpressionLimits",
    "evaluate_expression",
    "parse_expression",
    "validate_expression",
    "WorkflowPluginRuntime",
    "WorkflowCapabilityError",
    "WorkflowRunHistory",
    "WorkflowRunQueue",
    "QUEUE_STORE_VERSION",
    "WorkflowSnapshotStore",
    "create_plugin",
]
