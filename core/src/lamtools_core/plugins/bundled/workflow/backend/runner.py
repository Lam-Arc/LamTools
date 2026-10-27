"""Workflow runner state ownership and compatibility methods for execution services."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import asyncio
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from typing import Any, Literal
from lamtools_core.event.run_item import RunItemStatus
from .adapters import (
    AgentInvoker,
    ModelInvoker,
    NodeExecutor,
    adapt_agent_invoker,
    adapt_model_invoker,
    adapt_node_executor,
)
from .cache import WorkflowContentCache
from .claims import WorkflowClaimStore, claim_store_for_runtime
from .durable import WorkflowRunEvent, WorkflowRunEventStore
from .executors import WorkflowExecutorRegistry, WorkflowExpansion
from .flow_control import FlowControlDecision, FlowControlLease, FlowControlPolicy, FlowControlStore
from .models import WorkflowDef, WorkflowNode, WorkflowNodeState, WorkflowRunResult, _utcnow
from .registry import WorkflowNodeRegistry
from .runner_context import WorkflowExecutionContext
from .runner_state import WorkflowEventCallback, _ActiveWorkflowRun
from .snapshots import WorkflowSnapshotStore


class WorkflowRunner:
    """Executes a :class:`WorkflowDef` deterministically.

    Execution order is the topological sort of the node graph. Data flows along
    typed named ports. Each node may retry up to ``config.retries`` times before
    the run aborts (failure-as-abort is the core guarantee that workflows
    "eliminate uncertainty"). Per-node state is streamed via an injected
    ``emit`` callback as :class:`RunItemEvent` objects (``kind="status"``,
    ``item_id=<node_id>``) so the existing ``core/runItem`` GUI reducer renders
    node state without a new channel.
    """

    def __init__(
        self,
        *,
        llm_client: Any = None,
        sub_agent_runner: Any = None,
        model_invoker: ModelInvoker | Any = None,
        agent_invoker: AgentInvoker | Any = None,
        emit: WorkflowEventCallback | None = None,
        runtime_task_registry: Any = None,
        workflow_store: Any = None,
        permission_service: Any = None,
        snapshot_store: WorkflowSnapshotStore | None = None,
        event_store: WorkflowRunEventStore | None = None,
        claim_store: WorkflowClaimStore | None = None,
        flow_control_store: FlowControlStore | Any = None,
        flow_store: FlowControlStore | Any = None,
        cache_store: WorkflowContentCache | None = None,
        credential_resolver: Any = None,
        node_registry: WorkflowNodeRegistry | None = None,
        executor_registry: WorkflowExecutorRegistry | Any = None,
        node_executors: dict[str, Any] | None = None,
        node_executor: Any = None,
        max_nesting_depth: int = 16,
        max_depth: int | None = None,
        max_expansion_nodes: int = 128,
        max_expansion_edges: int = 512,
        emit_lifecycle_events: bool = False,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        # Keep the legacy attributes public for embedders that inspect them,
        # but make all actual service calls through the explicit adapters.
        self.llm_client = llm_client
        self.sub_agent_runner = sub_agent_runner
        self.model_invoker = adapt_model_invoker(model_invoker if model_invoker is not None else llm_client)
        self.agent_invoker = adapt_agent_invoker(agent_invoker if agent_invoker is not None else sub_agent_runner)
        self.emit = emit
        self.runtime_task_registry = runtime_task_registry
        # ``workflow_store`` enables subworkflow nodes to resolve and run other
        # workflow definitions by name.
        self.workflow_store = workflow_store
        self.permission_service = permission_service
        self.snapshot_store = snapshot_store
        self.event_store = event_store
        self.claim_store = claim_store or claim_store_for_runtime(event_store, snapshot_store)
        # Flow-control is opt-in at the document boundary.  Keep an explicitly
        # supplied store for hosts/tests; otherwise run-scoped stores are
        # lazily created from the workflow root so separate projects do not
        # share a coordinator file accidentally.
        self.flow_control_store = flow_control_store if flow_control_store is not None else flow_store
        self._flow_control_stores: dict[str, FlowControlStore] = {}
        self.cache_store = cache_store or WorkflowContentCache()
        self.credential_resolver = credential_resolver
        supplied_schema_registry = getattr(executor_registry, "schema_registry", None)
        # Older embedders passed the schema registry itself through the
        # ``executor_registry`` slot.  It already exposes ``get_executor``
        # and ``register_executor``; preserve that shape instead of silently
        # constructing a second schema registry that cannot see its custom
        # node types.
        executor_is_schema_registry = (
            supplied_schema_registry is None
            and callable(getattr(executor_registry, "get_executor", None))
            and callable(getattr(executor_registry, "register_executor", None))
        )
        self.node_registry = (
            node_registry
            if node_registry is not None
            else supplied_schema_registry
            if supplied_schema_registry is not None
            else executor_registry
            if executor_is_schema_registry
            else WorkflowNodeRegistry()
        )
        self.executor_registry = (
            executor_registry
            if executor_registry is not None
            else WorkflowExecutorRegistry(self.node_registry)
        )
        self.max_nesting_depth = max(
            0,
            int(max_depth if max_depth is not None else max_nesting_depth),
        )
        # Zero is useful as a host policy to disable dynamic expansion while
        # retaining ordinary registered nodes.  Keep that explicit setting
        # instead of silently widening it to one node.
        self.max_expansion_nodes = max(0, int(max_expansion_nodes))
        self.max_expansion_edges = max(0, int(max_expansion_edges))
        # A singular host executor is a convenience for embedding and is still
        # subject to the same schema/trust checks when a node has a custom kind.
        self.node_executor = adapt_node_executor(node_executor) if node_executor is not None else None
        if node_executors:
            for type_id, executor in node_executors.items():
                self._register_node_executor_compat(type_id, executor)
        # Existing direct Runner consumers receive the historical per-node
        # event stream. Queue-backed runs opt into lifecycle events (queued is
        # emitted by the queue itself; Runner emits progress/paused).
        self.emit_lifecycle_events = emit_lifecycle_events
        self.clock = clock
        self._active_runs: dict[tuple[str, str], _ActiveWorkflowRun] = {}
        self._active_tasks: dict[tuple[str, str], asyncio.Task[Any]] = {}
        self._run_snapshots: dict[tuple[str, str], WorkflowRunResult] = {}
        self._run_locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._signal_locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._run_lock_users: dict[tuple[str, str], int] = {}
        self._signal_lock_users: dict[tuple[str, str], int] = {}
        self._terminal_results: OrderedDict[tuple[str, str], WorkflowRunResult] = OrderedDict()
        self._max_terminal_results = 1024

    def _register_node_executor_compat(self, type_id: str, executor: Any) -> None:
        """Install a host-supplied executor while preserving old registries."""
        # ``WorkflowNodeRegistry`` calls this operation ``register_executor``;
        # ``WorkflowExecutorRegistry`` uses ``register`` for the same action.
        # Prefer the explicit name so a schema registry passed for legacy
        # compatibility is not mistaken for its schema-only ``register``
        # alias.
        register = getattr(self.executor_registry, "register_executor", None)
        if not callable(register):
            register = getattr(self.executor_registry, "register", None)
        if not callable(register):
            raise TypeError("workflow executor registry must expose register()")
        clean_type = str(type_id or "").strip()
        # ``node_executors`` is an explicit host-owned surface, so it is
        # trusted by definition.  The registry still requires a matching
        # schema, preventing an unregistered node from reaching execution.
        register(clean_type, executor, plugin_id="workflow", trusted=True)

    def _remember_terminal(
        self, key: tuple[str, str], result: WorkflowRunResult
    ) -> None:
        self._terminal_results[key] = WorkflowRunResult.from_dict(result.to_dict())
        self._terminal_results.move_to_end(key)
        while len(self._terminal_results) > self._max_terminal_results:
            self._terminal_results.popitem(last=False)

    def _flow_control_policy(self, workflow: WorkflowDef) -> FlowControlPolicy:
        """Read the canonical V2 scheduling policy, if this is a V2 run."""
        from .runner_admission import _flow_control_policy as _impl__flow_control_policy
        return _impl__flow_control_policy(self, workflow)

    def _flow_control_store_for_run(self, workflow: WorkflowDef, work_root: str) -> Any:
        from .runner_admission import _flow_control_store_for_run as _impl__flow_control_store_for_run
        return _impl__flow_control_store_for_run(self, workflow, work_root)

    @staticmethod
    def _flow_control_scope_key(workflow: WorkflowDef, workflow_identity: str, work_root: str) -> str:
        from .runner_admission import _flow_control_scope_key as _impl__flow_control_scope_key
        return _impl__flow_control_scope_key(workflow, workflow_identity, work_root)

    @staticmethod
    def _flow_control_lease_id(workflow_identity: str, thread_id: str, run_id: str) -> str:
        from .runner_admission import _flow_control_lease_id as _impl__flow_control_lease_id
        return _impl__flow_control_lease_id(workflow_identity, thread_id, run_id)

    @staticmethod
    def _normalize_flow_control_decision(value: Any) -> FlowControlDecision:
        from .runner_admission import _normalize_flow_control_decision as _impl__normalize_flow_control_decision
        return _impl__normalize_flow_control_decision(value)

    async def _flow_control_admit(self, workflow: WorkflowDef, *, workflow_identity: str, work_root: str, thread_id: str, run_id: str, workflow_revision: int, workflow_digest: str, previous: WorkflowRunResult | None, prior_values: dict[str, Any] | None, prior_node_states: dict[str, WorkflowNodeState] | None, started_at: datetime, inputs: dict[str, Any] | None) -> tuple[FlowControlPolicy, Any, FlowControlLease | Mapping[str, Any] | None, asyncio.Task[Any] | None, asyncio.Event | None, WorkflowRunResult | None]:
        """Admit one actual run, returning a paused result when blocked."""
        from .runner_admission import _flow_control_admit as _impl__flow_control_admit
        return await _impl__flow_control_admit(self, workflow, workflow_identity=workflow_identity, work_root=work_root, thread_id=thread_id, run_id=run_id, workflow_revision=workflow_revision, workflow_digest=workflow_digest, previous=previous, prior_values=prior_values, prior_node_states=prior_node_states, started_at=started_at, inputs=inputs)

    async def _flow_control_heartbeat(self, store: Any, lease: FlowControlLease | Mapping[str, Any], lost: asyncio.Event) -> None:
        from .runner_admission import _flow_control_heartbeat as _impl__flow_control_heartbeat
        return await _impl__flow_control_heartbeat(self, store, lease, lost)

    async def _flow_control_release(self, store: Any, lease: FlowControlLease | Mapping[str, Any] | None, heartbeat: asyncio.Task[Any] | None) -> None:
        from .runner_admission import _flow_control_release as _impl__flow_control_release
        return await _impl__flow_control_release(self, store, lease, heartbeat)

    async def _execute_durable_claim(self, kind: Literal['run', 'signal'], thread_id: str, run_id: str, operation: Callable[[], Awaitable[WorkflowRunResult]], *, request_fingerprint: str, mismatch_result: Callable[[], WorkflowRunResult] | None=None) -> WorkflowRunResult:
        """Execute under a SQLite lease and fence; waiters observe its result."""
        from .runner_admission import _execute_durable_claim as _impl__execute_durable_claim
        return await _impl__execute_durable_claim(self, kind, thread_id, run_id, operation, request_fingerprint=request_fingerprint, mismatch_result=mismatch_result)

    def _executor_for_node(self, node: WorkflowNode) -> NodeExecutor | None:
        """Resolve a plugin executor from the schema/execution registry."""
        from .runner_authority import _executor_for_node as _impl__executor_for_node
        return _impl__executor_for_node(self, node)

    def _validate_executable_nodes(self, workflow: WorkflowDef) -> None:
        """Reject schema-only or unknown custom nodes before any side effect."""
        from .runner_authority import _validate_executable_nodes as _impl__validate_executable_nodes
        return _impl__validate_executable_nodes(self, workflow)

    def _check_node_authority(self, node: WorkflowNode, execution_context: WorkflowExecutionContext | None) -> None:
        """Enforce registry declarations against host grants, fail closed.

            A registry declaration describes requirements; it is never itself a
            grant.  Empty declarations retain the historical compatibility path.
            """
        from .runner_authority import _check_node_authority as _impl__check_node_authority
        return _impl__check_node_authority(self, node, execution_context)

    def _builtin_executor_name(self, node: WorkflowNode) -> str | None:
        """Resolve only host-owned built-in executor aliases from node schema."""
        from .runner_authority import _builtin_executor_name as _impl__builtin_executor_name
        return _impl__builtin_executor_name(self, node)

    @staticmethod
    def _child_context(context: WorkflowExecutionContext | None, *, session_id: str, run_id: str, call_id: str, child_workflow_id: str, parent_workflow_id: str) -> WorkflowExecutionContext | None:
        """Build a nested context and seed the root workflow stack lazily.

            Explicit root contexts are passed unchanged to the first Agent/Model
            invocation for legacy identity compatibility.  The stack is seeded at
            the first nested boundary, where it is needed for cycle detection.
            """
        from .runner_authority import _child_context as _impl__child_context
        return _impl__child_context(context, session_id=session_id, run_id=run_id, call_id=call_id, child_workflow_id=child_workflow_id, parent_workflow_id=parent_workflow_id)

    async def run(self, workflow: WorkflowDef, *, inputs: dict[str, Any] | None=None, work_root: str='', thread_id: str='', run_id: str='', prior_values: dict[str, Any] | None=None, prior_node_states: dict[str, WorkflowNodeState] | None=None, max_steps: int | None=None, start_node: str | None=None, single_node: str | None=None, execution_context: WorkflowExecutionContext | None=None, _run_lock_held: bool=False, _process_run_lock_held: bool=False, _durable_run_claim_held: bool=False) -> WorkflowRunResult:
        """Run a workflow and convert caller cancellation to a stable result.

            The operation layer deliberately uses task cancellation for prompt
            interruption (especially while a command/script subprocess is
            blocked).  Keeping this conversion at the public Runner boundary
            means callers still receive the same ``status=cancelled`` contract and
            the node state that was in flight is not lost.
            """
        from .runner_run import run as _impl_run
        return await _impl_run(self, workflow, inputs=inputs, work_root=work_root, thread_id=thread_id, run_id=run_id, prior_values=prior_values, prior_node_states=prior_node_states, max_steps=max_steps, start_node=start_node, single_node=single_node, execution_context=execution_context, _run_lock_held=_run_lock_held, _process_run_lock_held=_process_run_lock_held, _durable_run_claim_held=_durable_run_claim_held)

    async def _persist_snapshot(self, thread_id: str, run_id: str, result: WorkflowRunResult, *, workflow: WorkflowDef, inputs: dict[str, Any] | None) -> None:
        """Persist the latest resumable state when a store is configured."""
        from .runner_persistence import _persist_snapshot as _impl__persist_snapshot
        return await _impl__persist_snapshot(self, thread_id, run_id, result, workflow=workflow, inputs=inputs)

    async def _append_durable_event(self, event: WorkflowRunEvent) -> None:
        """Append before/after side effects when durable journaling is enabled.

            Unlike GUI emission, journal failure is not swallowed: executing a
            side effect without a durable attempt identity would make recovery
            unsafe and must fail closed.
            """
        from .runner_persistence import _append_durable_event as _impl__append_durable_event
        return await _impl__append_durable_event(self, event)

    async def _persist_active_snapshot(self, *, workflow: WorkflowDef, thread_id: str, run_id: str, inputs: dict[str, Any], node_states: dict[str, WorkflowNodeState], values: dict[str, Any], steps_remaining: int) -> None:
        """Write a resumable snapshot after each observable node transition."""
        from .runner_persistence import _persist_active_snapshot as _impl__persist_active_snapshot
        return await _impl__persist_active_snapshot(self, workflow=workflow, thread_id=thread_id, run_id=run_id, inputs=inputs, node_states=node_states, values=values, steps_remaining=steps_remaining)

    async def _run_impl(self, workflow: WorkflowDef, *, inputs: dict[str, Any] | None=None, work_root: str='', thread_id: str='', run_id: str='', prior_values: dict[str, Any] | None=None, prior_node_states: dict[str, WorkflowNodeState] | None=None, max_steps: int | None=None, start_node: str | None=None, single_node: str | None=None, execution_context: WorkflowExecutionContext | None=None) -> WorkflowRunResult:
        """Run the workflow.

            ``max_steps=None`` runs to completion (整跑); an integer runs at most
            that many *ready* nodes then returns ``status="paused"`` (单步调试).
            ``prior_values`` / ``prior_node_states`` resume a paused run.
            ``start_node`` runs the subgraph from that node onward (nodes before it
            are skipped; their outputs must be in ``prior_values``).
            ``single_node`` runs exactly one node in isolation.
            """
        from .runner_scheduler import _run_impl as _impl__run_impl
        return await _impl__run_impl(self, workflow, inputs=inputs, work_root=work_root, thread_id=thread_id, run_id=run_id, prior_values=prior_values, prior_node_states=prior_node_states, max_steps=max_steps, start_node=start_node, single_node=single_node, execution_context=execution_context)

    def _cancelled_result(self, key: tuple[str, str]) -> WorkflowRunResult:
        """Build a complete cancellation result from the in-flight snapshot."""
        from .runner_persistence import _cancelled_result as _impl__cancelled_result
        return _impl__cancelled_result(self, key)

    def _paused_result(self, key: tuple[str, str]) -> WorkflowRunResult:
        """Build a resumable result from an in-flight run after shutdown."""
        from .runner_persistence import _paused_result as _impl__paused_result
        return _impl__paused_result(self, key)

    async def interrupt(self, thread_id: str, run_id: str) -> WorkflowRunResult | None:
        """Persist a resumable snapshot for a queue/process shutdown.

            This is intentionally separate from user cancellation: queue shutdown
            asks the runner to preserve progress, while an explicit cancel keeps
            the terminal ``cancelled`` result.
            """
        from .runner_signals import interrupt as _impl_interrupt
        return await _impl_interrupt(self, thread_id, run_id)

    def _wait_descriptor(self, node: WorkflowNode, *, workflow: WorkflowDef, thread_id: str, run_id: str, kind: str) -> dict[str, Any]:
        from .runner_signals import _wait_descriptor as _impl__wait_descriptor
        return _impl__wait_descriptor(self, node, workflow=workflow, thread_id=thread_id, run_id=run_id, kind=kind)

    async def signal(self, *, thread_id: str, run_id: str, resume_token: str, event_type: str, payload: Mapping[str, Any] | None=None, decision: str='', _signal_lock_held: bool=False, _process_signal_lock_held: bool=False, _durable_signal_claim_held: bool=False) -> WorkflowRunResult:
        """Resume a persisted wait without polling or occupying a worker."""
        from .runner_signals import signal as _impl_signal
        return await _impl_signal(self, thread_id=thread_id, run_id=run_id, resume_token=resume_token, event_type=event_type, payload=payload, decision=decision, _signal_lock_held=_signal_lock_held, _process_signal_lock_held=_process_signal_lock_held, _durable_signal_claim_held=_durable_signal_claim_held)

    async def shutdown(self) -> None:
        """Cancel and join Runner-owned workflow tasks during plugin unload."""
        from .runner_signals import shutdown as _impl_shutdown
        return await _impl_shutdown(self)

    # -- node execution ----------------------------------------------------

    async def _execute_with_retries(self, node: WorkflowNode, bound_inputs: dict[str, Any], work_root: str, state: WorkflowNodeState, values: dict[str, Any] | None=None, *, thread_id: str='', run_id: str='', execution_context: WorkflowExecutionContext | None=None) -> dict[str, Any]:
        from .runner_attempts import _execute_with_retries as _impl__execute_with_retries
        return await _impl__execute_with_retries(self, node, bound_inputs, work_root, state, values, thread_id=thread_id, run_id=run_id, execution_context=execution_context)

    def _cache_enabled(self, node: WorkflowNode) -> bool:
        """Return true only for an explicit pure + deterministic declaration."""
        from .runner_attempts import _cache_enabled as _impl__cache_enabled
        return _impl__cache_enabled(self, node)

    async def _invoke_node_executor(self, executor: NodeExecutor, node: WorkflowNode, bound_inputs: dict[str, Any], execution_context: WorkflowExecutionContext | None) -> Any:
        """Call a registered executor through the explicit adapter boundary."""
        from .runner_attempts import _invoke_node_executor as _impl__invoke_node_executor
        return await _impl__invoke_node_executor(self, executor, node, bound_inputs, execution_context)

    async def _execute_expansion(self, node: WorkflowNode, expansion: WorkflowExpansion, bound_inputs: dict[str, Any], work_root: str, thread_id: str, run_id: str, execution_context: WorkflowExecutionContext | None) -> dict[str, Any]:
        """Run a trusted executor's bounded declarative expansion.

            Expansion data is converted to the normal workflow model and then
            passes through the same validation, cycle, depth, permission, and
            cancellation gates as a saved subgraph.  There is no import/eval path
            from the expansion payload.
            """
        from .runner_expansion import _execute_expansion as _impl__execute_expansion
        return await _impl__execute_expansion(self, node, expansion, bound_inputs, work_root, thread_id, run_id, execution_context)

    def _expansion_definition(self, node: WorkflowNode, expansion: WorkflowExpansion) -> WorkflowDef:
        """Convert a ``WorkflowExpansion`` wire object to a WorkflowDef."""
        from .runner_expansion import _expansion_definition as _impl__expansion_definition
        return _impl__expansion_definition(self, node, expansion)

    async def _execute_ai(self, node: WorkflowNode, bound_inputs: dict[str, Any], work_root: str, execution_context: WorkflowExecutionContext | None=None, audit: dict[str, Any] | None=None) -> dict[str, Any]:
        """Unified AI node. ``config.mode`` selects the execution strategy:

            * ``single`` (default) — one LLM completion call.
            * ``loop`` — self-judging loop: the model prefixes its final answer
              with ``[DONE]``; iterate up to ``loop_max_iterations``.
            * ``agent`` — full sub-agent with tools and multi-turn decision.
            """
        from .runner_ai import _execute_ai as _impl__execute_ai
        return await _impl__execute_ai(self, node, bound_inputs, work_root, execution_context, audit)

    async def _execute_ai_llm(self, node: WorkflowNode, bound_inputs: dict[str, Any], work_root: str, is_loop: bool, execution_context: WorkflowExecutionContext | None=None, audit: dict[str, Any] | None=None) -> dict[str, Any]:
        from .runner_ai import _execute_ai_llm as _impl__execute_ai_llm
        return await _impl__execute_ai_llm(self, node, bound_inputs, work_root, is_loop, execution_context, audit)

    async def _execute_ai_agent(self, node: WorkflowNode, bound_inputs: dict[str, Any], work_root: str, execution_context: WorkflowExecutionContext | None=None, audit: dict[str, Any] | None=None) -> dict[str, Any]:
        from .runner_ai import _execute_ai_agent as _impl__execute_ai_agent
        return await _impl__execute_ai_agent(self, node, bound_inputs, work_root, execution_context, audit)

    def _split_or_fallback(self, node: WorkflowNode, raw: str) -> dict[str, Any]:
        """Distribute structured JSON output across named ports, else fall back.

            When the node has named output ports and ``raw`` parses to a JSON object,
            each key matching a port name flows to that port (missing keys default to
            None). When there are no named ports, or parsing fails, the entire value
            goes to the default output port as a string.
            """
        from .runner_ai import _split_or_fallback as _impl__split_or_fallback
        return _impl__split_or_fallback(self, node, raw)

    async def _execute_content(self, node: WorkflowNode, bound_inputs: dict[str, Any], work_root: str) -> dict[str, Any]:
        """Content nodes emit each output port's configured constant value."""
        from .runner_data_nodes import _execute_content as _impl__execute_content
        return await _impl__execute_content(self, node, bound_inputs, work_root)

    def _execute_passthrough(self, node: WorkflowNode, bound_inputs: dict[str, Any]) -> dict[str, Any]:
        """Map same-name inputs to outputs, with a predictable single-value fallback."""
        from .runner_data_nodes import _execute_passthrough as _impl__execute_passthrough
        return _impl__execute_passthrough(self, node, bound_inputs)

    def _execute_template(self, node: WorkflowNode, bound_inputs: dict[str, Any], *, execution_context: WorkflowExecutionContext | None=None) -> dict[str, Any]:
        from .runner_data_nodes import _execute_template as _impl__execute_template
        return _impl__execute_template(self, node, bound_inputs, execution_context=execution_context)

    def _execute_condition(self, node: WorkflowNode, bound_inputs: dict[str, Any], *, execution_context: WorkflowExecutionContext | None=None) -> dict[str, Any]:
        from .runner_data_nodes import _execute_condition as _impl__execute_condition
        return _impl__execute_condition(self, node, bound_inputs, execution_context=execution_context)

    def _execute_merge(self, node: WorkflowNode, bound_inputs: dict[str, Any]) -> dict[str, Any]:
        from .runner_data_nodes import _execute_merge as _impl__execute_merge
        return _impl__execute_merge(self, node, bound_inputs)

    def _execute_join(self, node: WorkflowNode, bound_inputs: dict[str, Any]) -> dict[str, Any]:
        from .runner_data_nodes import _execute_join as _impl__execute_join
        return _impl__execute_join(self, node, bound_inputs)

    async def _execute_subgraph(self, node: WorkflowNode, bound_inputs: dict[str, Any], work_root: str, thread_id: str, run_id: str, execution_context: WorkflowExecutionContext | None=None) -> dict[str, Any]:
        """Execute a referenced workflow with an optional iteration mode.

            ``config.workflow_name`` selects the target workflow definition.
            ``config.iterate`` selects how the sub-workflow is run:

            * ``none`` (default) — run once; bound inputs feed the sub-workflow's
              orphaned in-ports.
            * ``loop`` — run repeatedly; the sub-workflow's output feeds back into
              the next iteration's inputs; exits when ``config.condition`` (a Python
              expression evaluated against the last output) is true, or
              ``config.max_iterations`` is reached.
            * ``map`` — the first bound input value (expected to be a list) provides
              the elements; the sub-workflow runs once per element; results are
              collected into an array.
            """
        from .runner_expansion import _execute_subgraph as _impl__execute_subgraph
        return await _impl__execute_subgraph(self, node, bound_inputs, work_root, thread_id, run_id, execution_context)

    @staticmethod
    def _map_entry_inputs(sub_def: WorkflowDef, bound_inputs: dict[str, Any]) -> dict[str, Any]:
        """Map bound inputs to a sub-workflow's orphaned in-port names.

            If the sub-workflow has exactly one orphaned input, all bound values
            are flattened into it (first non-sentinel). Otherwise, bound input port
            names are matched directly to sub-workflow input names.
            """
        from .runner_expansion import _map_entry_inputs as _impl__map_entry_inputs
        return _impl__map_entry_inputs(sub_def, bound_inputs)

    async def _execute_command(self, node: WorkflowNode, bound_inputs: dict[str, Any], work_root: str, execution_context: WorkflowExecutionContext | None=None) -> dict[str, Any]:
        """command node: run a shell command (invoke CLI tools).

            Uses the same persisted shell resolution as run_command on Windows,
            feeds bound inputs as stdin JSON + INPUT_<PORT> env vars, and splits
            JSON stdout to same-named output ports (else whole stdout to default).
            """
        from .runner_process_nodes import _execute_command as _impl__execute_command
        return await _impl__execute_command(self, node, bound_inputs, work_root, execution_context)

    async def _run_command(self, cfg: dict[str, Any], bound_inputs: dict[str, Any], work_root: str) -> str:
        from .runner_process_nodes import _run_command as _impl__run_command
        return await _impl__run_command(self, cfg, bound_inputs, work_root)

    async def _execute_script(self, node: WorkflowNode, bound_inputs: dict[str, Any], work_root: str, execution_context: WorkflowExecutionContext | None=None) -> dict[str, Any]:
        """script node: Python binder. Runs the script via a generated runner
            that binds input-port names as locals and reads output-port names back;
            stdout JSON flows through _split_or_fallback to the output ports.
            """
        from .runner_process_nodes import _execute_script as _impl__execute_script
        return await _impl__execute_script(self, node, bound_inputs, work_root, execution_context)

    async def _run_script(self, node: WorkflowNode, cfg: dict[str, Any], bound_inputs: dict[str, Any], work_root: str) -> str:
        """Python binder: input/output PORT NAMES are program variables.

            The user's ``config.script`` is plain Python. Input-port names are
            available as variables (node ``IN x`` → ``x`` in code); assigning to an
            output-port name produces that output (``OUT y`` → ``y = ...``). No
            stdin parsing, no print, no JSON, no shell, no quoting — the model just
            writes ``y = x * 2``.

            Implementation: persist the user source to a real file under
            ``work_root/.lam/workflow_scripts/<nodeId>.py`` (config.script is the
            source of truth; rewritten only when its content hash changes), then
            run a generated ``<nodeId>.runner.py`` via ``sys.executable`` as an
            isolated subprocess. The runner binds inputs as locals, execs the user
            file (redirecting stray prints so they don't corrupt the output JSON),
            then prints a JSON object mapping each output-port name to its bound
            value. That stdout flows through ``_split_or_fallback`` unchanged.
            """
        from .runner_process_nodes import _run_script as _impl__run_script
        return await _impl__run_script(self, node, cfg, bound_inputs, work_root)

    # -- streaming + cancel helpers ---------------------------------------

    async def _check_execution_permission(self, command: str, *, work_root: str, node: WorkflowNode, execution_context: WorkflowExecutionContext | None=None) -> None:
        from .runner_authority import _check_execution_permission as _impl__check_execution_permission
        return await _impl__check_execution_permission(self, command, work_root=work_root, node=node, execution_context=execution_context)

    def _cancel_event(self, thread_id: str) -> Any:
        from .runner_persistence import _cancel_event as _impl__cancel_event
        return _impl__cancel_event(self, thread_id)

    async def _emit_state(self, node: WorkflowNode, status: RunItemStatus, thread_id: str, run_id: str, *, workflow_id: str='', error: str='', cache_status: str='', cache_key: str='') -> None:
        from .runner_persistence import _emit_state as _impl__emit_state
        return await _impl__emit_state(self, node, status, thread_id, run_id, workflow_id=workflow_id, error=error, cache_status=cache_status, cache_key=cache_key)

    async def _emit_run_status(self, status: str, thread_id: str, run_id: str, *, workflow_id: str='', node_id: str='', **details: Any) -> None:
        """Emit lifecycle progress without changing legacy node events."""
        from .runner_persistence import _emit_run_status as _impl__emit_run_status
        return await _impl__emit_run_status(self, status, thread_id, run_id, workflow_id=workflow_id, node_id=node_id, **details)
