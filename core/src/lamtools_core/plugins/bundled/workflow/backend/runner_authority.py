"""Trusted executor lookup and host authorization boundaries."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import asyncio
from dataclasses import replace
from .adapters import NodeExecutor, adapt_node_executor
from .executors import WorkflowExecutorError
from .models import WorkflowDef, WorkflowNode
from .runner_context import WorkflowExecutionContext


def _executor_for_node(runner, node: WorkflowNode) -> NodeExecutor | None:
    """Resolve a plugin executor from the schema/execution registry."""
    from .runner_values import _is_executor_surface
    getter = getattr(runner.executor_registry, "get", None)
    executor = getter(node.kind) if callable(getter) else None
    # ``WorkflowNodeRegistry.get`` returns a schema, not an executor.  A
    # host may intentionally pass that schema registry in the executor
    # slot for backwards compatibility, so never adapt a descriptive
    # schema object into a callable bridge.
    if executor is not None and not _is_executor_surface(executor):
        executor = None
    if executor is None:
        getter = getattr(runner.node_registry, "get_executor", None)
        executor = getter(node.kind) if callable(getter) else None
    if executor is None and runner.node_executor is not None:
        # A singular executor may only handle a declared custom type.  It
        # is never used to bypass schema validation for arbitrary kinds.
        spec = runner.node_registry.get(node.kind) if runner.node_registry is not None else None
        if spec is not None and runner._builtin_executor_name(node) is None:
            executor = runner.node_executor
    return adapt_node_executor(executor) if executor is not None else None


def _validate_executable_nodes(runner, workflow: WorkflowDef) -> None:
    """Reject schema-only or unknown custom nodes before any side effect."""
    for node in workflow.nodes:
        if runner._builtin_executor_name(node) is not None:
            continue
        spec = runner.node_registry.get(node.kind) if runner.node_registry is not None else None
        if spec is None:
            raise WorkflowExecutorError(
                f"workflow node type is not registered: {node.kind}"
            )
        if runner._executor_for_node(node) is None:
            raise WorkflowExecutorError(
                f"workflow node executor is not registered: {node.kind}"
            )


def _check_node_authority(
    runner,
    node: WorkflowNode,
    execution_context: WorkflowExecutionContext | None,
) -> None:
    """Enforce registry declarations against host grants, fail closed.

    A registry declaration describes requirements; it is never itself a
    grant.  Empty declarations retain the historical compatibility path.
    """

    from .runner_context import WorkflowCapabilityError
    from .runner_security import _workflow_authorization_grants, _workflow_resource_authorized
    spec = runner.node_registry.get(node.kind) if runner.node_registry is not None else None
    if spec is None:
        return
    required_capabilities = tuple(
        str(value).strip()
        for value in (getattr(spec, "capabilities", ()) or ())
        if str(value).strip()
    )
    resource_class = str(getattr(spec, "resource_class", "default") or "default").strip()
    requirements = getattr(spec, "resource_requirements", {}) or {}
    if not required_capabilities and resource_class in {"", "default"} and not requirements:
        return
    if execution_context is None:
        raise WorkflowCapabilityError(
            f"workflow node '{node.kind}' requires an authorized execution context"
        )
    grants = _workflow_authorization_grants(execution_context)
    missing = [name for name in required_capabilities if name not in grants.capabilities]
    if missing:
        raise WorkflowCapabilityError(
            f"workflow node '{node.kind}' requires capabilities: {', '.join(missing)}"
        )
    if resource_class not in {"", "default"} or requirements:
        if not _workflow_resource_authorized(
            resource_class or "default", requirements, grants.resources
        ):
            detail = resource_class or "default"
            raise WorkflowCapabilityError(
                f"workflow node '{node.kind}' requires authorized resource class: {detail}"
            )


def _builtin_executor_name(runner, node: WorkflowNode) -> str | None:
    """Resolve only host-owned built-in executor aliases from node schema."""
    spec = runner.node_registry.get(node.kind) if runner.node_registry is not None else None
    if spec is None or not bool(getattr(spec, "builtin", False)):
        return None
    name = str(getattr(spec, "executor", "") or "")
    return name if name in _BUILTIN_EXECUTORS else None


def _child_context(
    context: WorkflowExecutionContext | None,
    *,
    session_id: str,
    run_id: str,
    call_id: str,
    child_workflow_id: str,
    parent_workflow_id: str,
) -> WorkflowExecutionContext | None:
    """Build a nested context and seed the root workflow stack lazily.

    Explicit root contexts are passed unchanged to the first Agent/Model
    invocation for legacy identity compatibility.  The stack is seeded at
    the first nested boundary, where it is needed for cycle detection.
    """
    if context is None:
        return None
    base = context
    if not base.workflow_stack and parent_workflow_id:
        base = replace(base, workflow_stack=(str(parent_workflow_id),))
    return base.child(
        session_id=session_id,
        run_id=run_id,
        call_id=call_id,
        workflow_id=child_workflow_id,
    )


async def _check_execution_permission(
    runner,
    command: str,
    *,
    work_root: str,
    node: WorkflowNode,
    execution_context: WorkflowExecutionContext | None = None,
) -> None:
    from .runner_context import WorkflowPermissionError
    permissions = execution_context.permissions if execution_context is not None else {}
    explicit = permissions.get("run_command")
    if explicit is None:
        allowed_operations = permissions.get("allowed_operations")
        if isinstance(allowed_operations, (list, tuple, set)):
            explicit = "run_command" in allowed_operations
    if explicit is not None:
        if not bool(explicit):
            raise WorkflowPermissionError("workflow command blocked by execution context")
        return
    service = runner.permission_service
    if service is None:
        if execution_context is not None and execution_context.event_metadata.get("permission_policy_required"):
            raise WorkflowPermissionError("workflow command requires an explicit permission policy")
        return
    payload = {
        "command": command,
        "work_root": work_root,
        "source": "workflow",
        "node_id": node.id,
        "node_kind": node.kind,
        "execution_context": execution_context.metadata() if execution_context else {},
    }
    checker = getattr(service, "check", None)
    if callable(checker):
        decision = checker("run_command", payload)
    elif callable(service):
        decision = service("run_command", payload)
    else:
        raise WorkflowPermissionError("Workflow execution permission service is invalid")
    if asyncio.iscoroutine(decision):
        decision = await decision
    allowed = bool(getattr(decision, "allowed", decision.get("allowed", False) if isinstance(decision, dict) else decision))
    blocked = bool(getattr(decision, "blocked", decision.get("blocked", False) if isinstance(decision, dict) else False))
    requires_approval = bool(
        getattr(
            decision,
            "requires_approval",
            decision.get("requires_approval", False) if isinstance(decision, dict) else False,
        )
    )
    if not allowed or blocked or requires_approval:
        reason = str(
            getattr(
                decision,
                "reason",
                decision.get("reason", "") if isinstance(decision, dict) else "",
            )
            or "workflow command requires permission",
        )
        raise WorkflowPermissionError(reason)


_BUILTIN_EXECUTORS = {
    "ai", "model", "agent", "command", "script", "content", "subgraph",
    "passthrough", "template", "condition", "merge", "join", "wait_event", "approval",
}
