"""RPC operations contributed by the bundled Workflow plugin."""

from __future__ import annotations

import asyncio
import inspect
import uuid
from typing import Any

from lamtools_core.app.operation_catalog import OperationRequest, OperationResult
from lamtools_core.plugins.context import PluginContext
from lamtools_core.session import build_session_record

from .runtime import WorkflowDef, WorkflowExecutionContext, WorkflowNodeState, WorkflowRunResult
from .queue import TERMINAL_STATUSES, WorkflowQueueItem
from .document import (
    canonicalize_document,
    compile_document,
    document_from_workflow_def,
    export_comfyui,
    import_comfyui,
    is_v2_document,
    semantic_graph,
)
from .activations import (
    WorkflowActivationError,
    activation_view,
    build_arrange_activation_payload,
    is_workflow_activation_job,
    normalize_workflow_trigger,
)
from .human_tasks import HumanTaskCenter, task_scope


def _runtime(context: PluginContext | None) -> Any:
    if context is None:
        raise RuntimeError("workflow plugin context is not configured")
    runtime = context.service("workflow")
    if runtime is None:
        raise RuntimeError("workflow plugin is not loaded")
    return runtime


def _queue(context: PluginContext | None) -> Any:
    queue = getattr(_runtime(context), "queue", None)
    if queue is None:
        raise RuntimeError("workflow queue service is not configured")
    return queue


def _node_registry(context: PluginContext | None) -> Any:
    runtime = _runtime(context)
    registry = getattr(runtime, "node_registry", None)
    if registry is None:
        registry = getattr(getattr(runtime, "runner", None), "node_registry", None)
    if registry is None:
        raise RuntimeError("workflow node registry is not configured")
    return registry


def _human_tasks(context: PluginContext | None) -> HumanTaskCenter:
    """Build the derived task center from the current workflow runtime."""

    runtime = _runtime(context)
    return HumanTaskCenter.from_context(context, runtime=runtime)


def _name(payload: dict[str, Any]) -> str:
    return str(payload.get("name") or "").strip()


def _optional_text(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        if key in payload:
            value = str(payload.get(key) or "").strip()
            return value or None
    return None


def _scoped_work_root(
    context: PluginContext | None,
    payload: dict[str, Any],
) -> str | None:
    work_root = _optional_text(payload, "work_root", "workRoot")
    if work_root:
        runtime = _runtime(context)
        watch = getattr(runtime, "watch_work_root", None)
        if callable(watch):
            watch(work_root)
    return work_root


def _error(request: OperationRequest, error: object) -> OperationResult:
    return OperationResult(name=request.name, status="error", payload={"error": str(error)})


def _expected_revision(payload: dict[str, Any]) -> int | None:
    raw = payload.get("expected_revision", payload.get("expectedRevision"))
    if raw in (None, ""):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("expected_revision must be an integer") from exc


def _provided_mapping(
    payload: dict[str, Any], *keys: str
) -> tuple[bool, dict[str, Any] | None]:
    """Read an optional mapping without manufacturing an empty override.

    A missing prior-state field must stay ``None`` so WorkflowRunner can load
    the durable snapshot.  An explicitly supplied empty mapping remains an
    intentional caller override.
    """
    selected = next((key for key in keys if key in payload), None)
    if selected is None:
        return False, None
    raw = payload.get(selected)
    if raw is None:
        return True, None
    if not isinstance(raw, dict):
        raise TypeError(f"{selected} must be an object")
    return True, dict(raw)


def _execution_context(
    request: OperationRequest,
    context: PluginContext | None,
    work_root: str,
    thread_id: str,
    run_id: str,
) -> WorkflowExecutionContext:
    metadata = dict(request.metadata or {})
    session_metadata = metadata.get("_runtime_session_metadata")
    if isinstance(session_metadata, dict):
        metadata = {**session_metadata, **metadata}
    nested = metadata.get("execution_context")
    if isinstance(nested, dict):
        # A workflow-as-tool caller can forward a serialized parent context;
        # request metadata remains authoritative for correlation and policy.
        metadata = {**nested, **metadata}
    permissions = metadata.get("runtime_permissions") or metadata.get("permissions") or {}
    payload = request.payload if isinstance(request.payload, dict) else {}
    if not permissions and isinstance(payload.get("permissions"), dict):
        permissions = payload.get("permissions")
    registry = context.runtime_task_registry if context is not None else None
    cancellation = None
    get_cancel_event = getattr(registry, "get_cancel_event", None)
    if callable(get_cancel_event):
        cancellation = get_cancel_event(thread_id)
    raw_lineage = metadata.get("lineage") or metadata.get("parent_lineage") or ()
    if isinstance(raw_lineage, str):
        lineage = (raw_lineage,) if raw_lineage else ()
    elif isinstance(raw_lineage, (list, tuple)):
        lineage = tuple(str(item) for item in raw_lineage if str(item))
    else:
        lineage = ()
    raw_stack = metadata.get("workflow_stack") or metadata.get("active_workflows") or ()
    if isinstance(raw_stack, str):
        workflow_stack = (raw_stack,) if raw_stack else ()
    elif isinstance(raw_stack, (list, tuple)):
        workflow_stack = tuple(str(item) for item in raw_stack if str(item))
    else:
        workflow_stack = ()
    try:
        depth = max(0, int(metadata.get("depth", metadata.get("nesting_depth", 0)) or 0))
    except (TypeError, ValueError):
        depth = 0
    raw_max_depth = metadata.get("max_depth", metadata.get("max_nesting_depth"))
    try:
        # Preserve an explicit zero: it is the useful policy for allowing the
        # root workflow while disallowing nested calls.
        max_depth = max(0, int(16 if raw_max_depth in (None, "") else raw_max_depth))
    except (TypeError, ValueError):
        max_depth = 16
    attachments = metadata.get("attachments", payload.get("attachments", []))
    if not isinstance(attachments, list):
        attachments = list(attachments) if isinstance(attachments, (tuple, set)) else []
    runtime_snapshot = metadata.get(
        "runtime_snapshot",
        metadata.get("snapshot", payload.get("runtime_snapshot", payload.get("snapshot"))),
    )
    environment = metadata.get("environment", payload.get("environment", {}))
    capabilities = metadata.get("capabilities", payload.get("capabilities", {}))
    return WorkflowExecutionContext(
        parent_session_id=str(metadata.get("session_id") or metadata.get("thread_id") or thread_id),
        parent_run_id=str(metadata.get("run_id") or run_id),
        parent_turn_id=str(metadata.get("turn_id") or metadata.get("parent_turn_id") or ""),
        parent_call_id=str(
            metadata.get("tool_call_id")
            or metadata.get("call_id")
            or metadata.get("parent_call_id")
            or ""
        ),
        cwd=work_root,
        cancellation=cancellation,
        permissions=dict(permissions) if isinstance(permissions, dict) else {},
        attachments=attachments,
        runtime_snapshot=runtime_snapshot,
        environment=dict(environment) if isinstance(environment, dict) else {},
        capabilities=dict(capabilities) if isinstance(capabilities, dict) else {},
        trace_id=str(metadata.get("trace_id") or metadata.get("traceId") or ""),
        lineage=lineage,
        workflow_stack=workflow_stack,
        depth=depth,
        max_depth=max_depth,
        event_metadata={
            key: metadata[key]
            for key in ("trace_id", "correlation_id", "actor_id", "actor_kind")
            if key in metadata
        } | {"permission_policy_required": True},
    )


def _session_id(definition: WorkflowDef) -> str:
    return f"workflow:{definition.id}"


def _session_metadata(definition: WorkflowDef) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "owner_plugin": "workflow",
        "resource_type": "workflow",
        "resource_id": definition.id,
    }
    if definition.work_root:
        metadata["work_root"] = definition.work_root
    return metadata


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


async def _ensure_workflow_session(
    context: PluginContext | None,
    definition: WorkflowDef,
    *,
    title: str | None = None,
    force_title: bool = False,
) -> str:
    """Bind the workflow resource to one stable Core session when available."""
    session_id = _session_id(definition)
    if context is None:
        return session_id
    store = context.service("session_store")
    if store is None:
        return session_id
    metadata = _session_metadata(definition)
    existing = await _maybe_await(store.get(session_id))
    session_title = str(title or definition.name).strip() or definition.name
    if existing is None:
        record = build_session_record(
            session_id=session_id,
            member_id="core",
            title=session_title,
            metadata=metadata,
        )
        try:
            await _maybe_await(store.create(record))
        except ValueError:
            # A concurrent read/create may have won the race. Re-read and
            # continue with the durable record instead of failing the workflow.
            existing = await _maybe_await(store.get(session_id))
            if existing is None:
                raise
        else:
            return session_id

    current_metadata = dict(getattr(existing, "metadata", {}) or {})
    current_metadata.update(metadata)
    patch = getattr(store, "patch", None)
    if callable(patch):
        await _maybe_await(
            patch(
                session_id,
                title=session_title if force_title else None,
                metadata=current_metadata,
            )
        )
    else:
        existing.metadata = current_metadata
        if force_title:
            existing.title = session_title
        await _maybe_await(store.update(existing))
    return session_id


async def _delete_workflow_session(context: PluginContext | None, definition: WorkflowDef) -> None:
    if context is None:
        return
    store = context.service("session_store")
    delete = getattr(store, "delete", None) if store is not None else None
    if callable(delete):
        await _maybe_await(delete(_session_id(definition)))


async def workflow_create(request: OperationRequest, *, context: PluginContext | None = None, **_: Any) -> OperationResult:
    payload = request.payload
    try:
        definition = WorkflowDef.from_dict(dict(payload))
        if not definition.name:
            return _error(request, "name is required")
        definition = await _runtime(context).manager.create(definition)
        session_id = await _ensure_workflow_session(context, definition)
    except (RuntimeError, TypeError, ValueError) as exc:
        return _error(request, exc)
    return OperationResult(name=request.name, payload={"workflow": definition.to_dict(), "session_id": session_id})


async def workflow_get(request: OperationRequest, *, context: PluginContext | None = None, **_: Any) -> OperationResult:
    name = _name(request.payload)
    workflow_id = str(request.payload.get("workflow_id") or request.payload.get("workflowId") or "").strip()
    if not name and not workflow_id:
        return _error(request, "name or workflow_id is required")
    try:
        runtime = _runtime(context)
        work_root = _scoped_work_root(context, request.payload)
        definition = None
        if workflow_id:
            definitions = await runtime.manager.list(work_root=work_root)
            definition = next((item for item in definitions if item.id == workflow_id), None)
        else:
            definition = await runtime.manager.get(name, work_root=work_root)
    except RuntimeError as exc:
        return _error(request, exc)
    if definition is None:
        return _error(request, f"Workflow not found: {name or workflow_id}")
    session_id = await _ensure_workflow_session(context, definition)
    return OperationResult(name=request.name, payload={
        "workflow": definition.to_dict(),
        "document": document_from_workflow_def(definition),
        "session_id": session_id,
    })


async def _document_definition(
    request: OperationRequest, context: PluginContext | None
) -> tuple[Any, str | None]:
    name = _name(request.payload)
    workflow_id = str(request.payload.get("workflow_id") or request.payload.get("workflowId") or "").strip()
    if not name and not workflow_id:
        raise ValueError("name or workflow_id is required")
    runtime = _runtime(context)
    work_root = _scoped_work_root(context, request.payload)
    if workflow_id:
        definitions = await runtime.manager.list(work_root=work_root)
        definition = next((item for item in definitions if item.id == workflow_id), None)
    else:
        definition = await runtime.manager.get(name, work_root=work_root)
    if definition is None:
        raise LookupError(f"Workflow not found: {name or workflow_id}")
    return definition, work_root


async def workflow_document_get(
    request: OperationRequest, *, context: PluginContext | None = None, **_: Any
) -> OperationResult:
    try:
        definition, _ = await _document_definition(request, context)
        document = document_from_workflow_def(definition)
    except (LookupError, RuntimeError, TypeError, ValueError) as exc:
        return _error(request, exc)
    return OperationResult(name=request.name, payload={"document": document})


async def workflow_document_save(
    request: OperationRequest, *, context: PluginContext | None = None, **_: Any
) -> OperationResult:
    raw = request.payload.get("document")
    if not isinstance(raw, dict) or not is_v2_document(raw):
        return _error(request, "document must be a canonical lamtools.workflow V2 object")
    try:
        document = canonicalize_document(raw)
        work_root = _scoped_work_root(context, request.payload)
        definition = await _runtime(context).manager.save_document(
            document,
            work_root=work_root,
            expected_revision=_expected_revision(request.payload),
        )
        session_id = await _ensure_workflow_session(context, definition)
    except (LookupError, RuntimeError, TypeError, ValueError) as exc:
        return _error(request, exc)
    return OperationResult(name=request.name, payload={
        "document": document_from_workflow_def(definition),
        "workflow": definition.to_dict(),
        "session_id": session_id,
    })


async def workflow_compile(
    request: OperationRequest, *, context: PluginContext | None = None, **_: Any
) -> OperationResult:
    try:
        raw = request.payload.get("document")
        if isinstance(raw, dict):
            document = canonicalize_document(raw)
        else:
            definition, _ = await _document_definition(request, context)
            document = document_from_workflow_def(definition)
        prompt = compile_document(document)
    except (LookupError, RuntimeError, TypeError, ValueError) as exc:
        return _error(request, exc)
    return OperationResult(name=request.name, payload={"prompt": prompt})


async def workflow_semantic(
    request: OperationRequest, *, context: PluginContext | None = None, **_: Any
) -> OperationResult:
    try:
        definition, _ = await _document_definition(request, context)
        raw_ids = request.payload.get("node_ids") or request.payload.get("nodeIds") or []
        node_ids = [str(item) for item in raw_ids] if isinstance(raw_ids, list) else []
        graph = semantic_graph(
            document_from_workflow_def(definition), node_ids=node_ids,
            offset=int(request.payload.get("offset") or 0),
            limit=int(request.payload.get("limit") or 100),
        )
    except (LookupError, RuntimeError, TypeError, ValueError) as exc:
        return _error(request, exc)
    return OperationResult(name=request.name, payload={"semantic": graph})


async def workflow_import_comfyui(
    request: OperationRequest, *, context: PluginContext | None = None, **_: Any
) -> OperationResult:
    raw = request.payload.get("workflow") or request.payload.get("document")
    if not isinstance(raw, dict):
        return _error(request, "workflow must be a ComfyUI workflow object")
    try:
        document = import_comfyui(raw, name=_name(request.payload))
        work_root = _scoped_work_root(context, request.payload)
        definition = await _runtime(context).manager.save_document(
            document, work_root=work_root,
            expected_revision=_expected_revision(request.payload),
        )
        session_id = await _ensure_workflow_session(context, definition)
    except (LookupError, RuntimeError, TypeError, ValueError) as exc:
        return _error(request, exc)
    return OperationResult(name=request.name, payload={
        "document": document_from_workflow_def(definition),
        "workflow": definition.to_dict(), "session_id": session_id,
    })


async def workflow_export_comfyui(
    request: OperationRequest, *, context: PluginContext | None = None, **_: Any
) -> OperationResult:
    try:
        definition, _ = await _document_definition(request, context)
        exported = export_comfyui(
            document_from_workflow_def(definition),
            version=str(request.payload.get("version") or "1"),
        )
    except (LookupError, RuntimeError, TypeError, ValueError) as exc:
        return _error(request, exc)
    return OperationResult(name=request.name, payload={"workflow": exported})


async def workflow_list(request: OperationRequest, *, context: PluginContext | None = None, **_: Any) -> OperationResult:
    try:
        definitions = await _runtime(context).manager.list(
            work_root=_scoped_work_root(context, request.payload)
        )
        for definition in definitions:
            await _ensure_workflow_session(context, definition)
    except RuntimeError as exc:
        return _error(request, exc)
    return OperationResult(name=request.name, payload={"workflows": [item.to_dict() for item in definitions]})


async def workflow_list_grouped(request: OperationRequest, *, context: PluginContext | None = None, **_: Any) -> OperationResult:
    raw = request.payload.get("work_roots") or request.payload.get("workRoots") or []
    roots = [str(item) for item in raw if str(item)] if isinstance(raw, (list, tuple)) else []
    try:
        runtime = _runtime(context)
        watch = getattr(runtime, "watch_work_root", None)
        if callable(watch):
            for root in roots:
                watch(root)
        grouped = await runtime.manager.list_grouped(work_roots=roots)
        # Listing is also the resource-discovery path used by the Workflow
        # sidebar. Ensure every discovered definition has its stable
        # plugin-owned Session before the UI attempts to activate it.
        for definitions in grouped.values():
            for definition in definitions:
                await _ensure_workflow_session(context, definition)
    except RuntimeError as exc:
        return _error(request, exc)
    return OperationResult(name=request.name, payload={"groups": {key: [item.to_dict() for item in value] for key, value in grouped.items()}})


async def workflow_update(request: OperationRequest, *, context: PluginContext | None = None, **_: Any) -> OperationResult:
    payload = request.payload
    name = _name(payload)
    if not name:
        return _error(request, "name is required")
    try:
        definition = await _runtime(context).manager.update_fields(
            name,
            work_root=_scoped_work_root(context, payload),
            description=str(payload.get("description") or "") if "description" in payload else None,
            nodes=list(payload.get("nodes") or []) if "nodes" in payload else None,
            edges=list(payload.get("edges") or []) if "edges" in payload else None,
            input_params=(list(payload.get("input_params") or payload.get("inputParams") or []) if "input_params" in payload or "inputParams" in payload else None),
            output_port=(str(payload.get("output_port") or payload.get("outputPort") or "") if "output_port" in payload or "outputPort" in payload else None),
            exposed=bool(payload.get("exposed")) if "exposed" in payload else None,
            tool_name=(str(payload.get("tool_name") or payload.get("toolName") or "") if "tool_name" in payload or "toolName" in payload else None),
            expected_revision=_expected_revision(payload),
        )
    except (LookupError, RuntimeError, TypeError, ValueError) as exc:
        return _error(request, exc)
    session_id = await _ensure_workflow_session(context, definition)
    return OperationResult(name=request.name, payload={"workflow": definition.to_dict(), "session_id": session_id})


async def workflow_save(request: OperationRequest, *, context: PluginContext | None = None, **_: Any) -> OperationResult:
    """Create or replace a workflow definition through the plugin boundary."""
    raw = request.payload.get("workflow")
    # Accept both ``{"workflow": {...}, "work_root": ...}`` and a flat
    # definition.  Scope/CAS fields supplied beside the nested definition must
    # not disappear when the nested object omits them.
    payload = {**dict(request.payload), **dict(raw)} if isinstance(raw, dict) else dict(request.payload)
    name = str(payload.get("name") or "").strip()
    if not name:
        return _error(request, "name is required")
    work_root = _scoped_work_root(context, payload)
    try:
        runtime = _runtime(context)
        existing = await runtime.manager.get(name, work_root=work_root)
        if existing is None:
            definition = await runtime.manager.create(WorkflowDef.from_dict(payload))
        else:
            definition = await runtime.manager.update_fields(
                name,
                work_root=work_root,
                description=str(payload.get("description") or "") if "description" in payload else None,
                nodes=list(payload.get("nodes") or []) if "nodes" in payload else None,
                edges=list(payload.get("edges") or []) if "edges" in payload else None,
                input_params=list(payload.get("input_params") or payload.get("inputParams") or []) if "input_params" in payload or "inputParams" in payload else None,
                output_port=str(payload.get("output_port") or payload.get("outputPort") or "") if "output_port" in payload or "outputPort" in payload else None,
                exposed=bool(payload.get("exposed")) if "exposed" in payload else None,
                tool_name=str(payload.get("tool_name") or payload.get("toolName") or "") if "tool_name" in payload or "toolName" in payload else None,
                expected_revision=_expected_revision(payload),
            )
        session_id = await _ensure_workflow_session(context, definition)
    except (LookupError, RuntimeError, TypeError, ValueError) as exc:
        return _error(request, exc)
    return OperationResult(name=request.name, payload={"workflow": definition.to_dict(), "session_id": session_id})


async def workflow_rename(request: OperationRequest, *, context: PluginContext | None = None, **_: Any) -> OperationResult:
    payload = request.payload
    name = _name(payload)
    new_name = str(payload.get("new_name") or payload.get("newName") or payload.get("title") or "").strip()
    if not name:
        return _error(request, "name is required")
    if not new_name:
        return _error(request, "new_name is required")
    try:
        runtime = _runtime(context)
        definition = await runtime.manager.rename(
            name,
            new_name,
            work_root=_scoped_work_root(context, payload),
        )
        session_id = await _ensure_workflow_session(context, definition, title=definition.name, force_title=True)
    except (LookupError, RuntimeError, TypeError, ValueError) as exc:
        return _error(request, exc)
    return OperationResult(name=request.name, payload={"workflow": definition.to_dict(), "session_id": session_id})


async def workflow_delete(request: OperationRequest, *, context: PluginContext | None = None, **_: Any) -> OperationResult:
    name = _name(request.payload)
    if not name:
        return _error(request, "name is required")
    try:
        runtime = _runtime(context)
        work_root = _scoped_work_root(context, request.payload)
        definition = await runtime.manager.get(name, work_root=work_root)
        removed = await runtime.manager.delete(name, work_root=work_root)
        if definition is not None and removed:
            await _delete_workflow_session(context, definition)
    except RuntimeError as exc:
        return _error(request, exc)
    return OperationResult(name=request.name, payload={"deleted": removed, "name": name})


async def workflow_expose(request: OperationRequest, *, context: PluginContext | None = None, **_: Any) -> OperationResult:
    return await _set_exposed(request, context, True)


async def workflow_unexpose(request: OperationRequest, *, context: PluginContext | None = None, **_: Any) -> OperationResult:
    return await _set_exposed(request, context, False)


async def _set_exposed(request: OperationRequest, context: PluginContext | None, exposed: bool) -> OperationResult:
    name = _name(request.payload)
    if not name:
        return _error(request, "name is required")
    try:
        definition = await _runtime(context).manager.set_exposed(
            name,
            exposed,
            work_root=_scoped_work_root(context, request.payload),
        )
    except (LookupError, RuntimeError) as exc:
        return _error(request, exc)
    session_id = await _ensure_workflow_session(context, definition)
    return OperationResult(name=request.name, payload={"workflow": definition.to_dict(), "session_id": session_id})


async def _execute_arrange(
    context: PluginContext | None,
    name: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if context is None or context.operation_catalog is None:
        raise RuntimeError("Core Arrange is not configured")
    result = await context.operation_executor()(
        name,
        payload,
        {"source": "workflow.activation"},
    )
    if not isinstance(result, OperationResult):
        raise RuntimeError(f"{name} returned an invalid result")
    if result.status != "ok":
        raise RuntimeError(str(result.payload.get("error") or f"{name} failed"))
    return dict(result.payload or {})


async def _schedule_human_task_timeout(
    context: PluginContext | None,
    *,
    work_root: str,
    thread_id: str,
    run_id: str,
    descriptor: dict[str, Any] | None,
) -> None:
    """Create one durable Arrange timer for a wait descriptor, if possible.

    The timer carries only the stable task/run/node identity.  Its resume
    token remains in the workflow snapshot and is resolved by
    ``workflow.human_task.timeout`` at execution time.
    """

    descriptor = descriptor if isinstance(descriptor, dict) else {}
    deadline = str(
        descriptor.get("deadline")
        or descriptor.get("due_at")
        or descriptor.get("dueAt")
        or ""
    ).strip()
    node_id = str(descriptor.get("node_id") or descriptor.get("nodeId") or "").strip()
    if not context or not work_root or not thread_id or not run_id or not node_id or not deadline:
        return
    if context.operation_catalog is None:
        return
    task_id = f"{run_id}:{node_id}"
    job_id = f"workflow_human_task_timeout:{run_id}:{node_id}"
    try:
        existing = await _execute_arrange(context, "arrange.get", {"job_id": job_id})
        if isinstance(existing.get("job"), dict):
            # Stable job id makes retries of workflow.run idempotent.  Do not
            # replace an existing timer or resurrect a terminal no-op.
            return
    except Exception:  # noqa: BLE001 - a missing job is the normal path
        pass
    timer_payload = {
        "task_id": task_id,
        "thread_id": thread_id,
        "run_id": run_id,
        "node_id": node_id,
        "work_root": work_root,
    }
    create_payload = {
        "job_id": job_id,
        "work_root": work_root,
        "thread_id": thread_id,
        "source_thread_id": thread_id,
        "session_strategy": "fixed",
        "kind": "routine",
        "operation": "workflow.human_task.timeout",
        "payload": timer_payload,
        "trigger": {"type": "once", "run_at": deadline},
        "title": "Workflow human task timeout",
        "max_runs": 1,
    }
    try:
        await _execute_arrange(context, "arrange.create", create_payload)
    except Exception as exc:  # noqa: BLE001 - scheduling must not fail a run
        # Two workflow.run retries can race before the first insert is
        # visible.  A duplicate stable id is success for our purposes.
        if "already exists" not in str(exc).lower():
            return


async def _workflow_activation_jobs(
    context: PluginContext | None,
    *,
    work_root: str,
    workflow_id: str,
) -> list[dict[str, Any]]:
    payload = await _execute_arrange(context, "arrange.list", {"work_root": work_root})
    raw_jobs = payload.get("jobs") or []
    jobs: list[dict[str, Any]] = []
    for raw in raw_jobs if isinstance(raw_jobs, list) else []:
        if not isinstance(raw, dict) or not is_workflow_activation_job(raw):
            continue
        view = activation_view(raw)
        if view["workflow_id"] == workflow_id:
            jobs.append(raw)
    return jobs


async def workflow_activation_list(
    request: OperationRequest, *, context: PluginContext | None = None, **_: Any
) -> OperationResult:
    try:
        definition, work_root = await _document_definition(request, context)
        root = work_root or definition.work_root or str(context.work_root if context else "")
        jobs = await _workflow_activation_jobs(
            context, work_root=root, workflow_id=definition.id
        )
    except (LookupError, RuntimeError, TypeError, ValueError) as exc:
        return _error(request, exc)
    return OperationResult(
        name=request.name,
        payload={"activations": [activation_view(item) for item in jobs]},
    )


async def workflow_activate(
    request: OperationRequest, *, context: PluginContext | None = None, **_: Any
) -> OperationResult:
    """Activate declared schedule/event triggers through Core Arrange."""
    try:
        definition, work_root = await _document_definition(request, context)
        root = work_root or definition.work_root or str(context.work_root if context else "")
        document = document_from_workflow_def(definition)
        raw_triggers = document.get("triggers") or []
        if not isinstance(raw_triggers, list):
            raise WorkflowActivationError("workflow triggers must be an array")
        requested_id = str(
            request.payload.get("trigger_id") or request.payload.get("triggerId") or ""
        ).strip()
        triggers = [
            normalize_workflow_trigger(item, index=index)
            for index, item in enumerate(raw_triggers)
            if isinstance(item, dict)
        ]
        if requested_id:
            triggers = [item for item in triggers if item["id"] == requested_id]
            if not triggers:
                raise WorkflowActivationError(f"workflow trigger not found: {requested_id}")
        schedulable = [
            item for item in triggers if item["enabled"] and item["type"] != "manual"
        ]
        if not schedulable:
            raise WorkflowActivationError("workflow has no enabled schedule/event trigger")

        existing = await _workflow_activation_jobs(
            context, work_root=root, workflow_id=definition.id
        )
        active_statuses = {"scheduled", "waiting", "running", "paused"}
        by_trigger: dict[str, list[dict[str, Any]]] = {}
        for job in existing:
            view = activation_view(job)
            if view["status"] in active_statuses:
                by_trigger.setdefault(view["trigger_id"], []).append(job)

        replace = bool(request.payload.get("replace", False))
        conflicts: list[str] = []
        for trigger in schedulable:
            for job in by_trigger.get(trigger["id"], []):
                view = activation_view(job)
                if view["workflow_revision"] != definition.revision and not replace:
                    conflicts.append(trigger["id"])
        if conflicts:
            names = ", ".join(sorted(set(conflicts)))
            raise WorkflowActivationError(
                f"active triggers use an older workflow revision ({names}); set replace=true"
            )

        activated: list[dict[str, Any]] = []
        reused: list[dict[str, Any]] = []
        for trigger in schedulable:
            current_jobs = by_trigger.get(trigger["id"], [])
            same = next(
                (
                    job
                    for job in current_jobs
                    if activation_view(job)["workflow_revision"] == definition.revision
                ),
                None,
            )
            if same is not None:
                view = activation_view(same)
                if view["status"] == "paused":
                    resumed = await _execute_arrange(
                        context, "arrange.resume", {"job_id": view["id"]}
                    )
                    same = dict(resumed.get("job") or same)
                reused.append(activation_view(same))
                continue
            if replace:
                for job in current_jobs:
                    await _execute_arrange(
                        context, "arrange.cancel", {"job_id": activation_view(job)["id"]}
                    )
            created = await _execute_arrange(
                context,
                "arrange.create",
                build_arrange_activation_payload(
                    workflow_id=definition.id,
                    workflow_name=definition.name,
                    workflow_revision=definition.revision,
                    work_root=root,
                    trigger=trigger,
                    source_thread_id=_session_id(definition),
                ),
            )
            raw_job = created.get("job")
            if not isinstance(raw_job, dict):
                raise RuntimeError("arrange.create did not return a job")
            activated.append(activation_view(raw_job))
    except (LookupError, RuntimeError, TypeError, ValueError) as exc:
        return _error(request, exc)
    return OperationResult(
        name=request.name,
        payload={"activated": activated, "reused": reused},
    )


async def workflow_deactivate(
    request: OperationRequest, *, context: PluginContext | None = None, **_: Any
) -> OperationResult:
    try:
        definition, work_root = await _document_definition(request, context)
        root = work_root or definition.work_root or str(context.work_root if context else "")
        requested_id = str(
            request.payload.get("trigger_id") or request.payload.get("triggerId") or ""
        ).strip()
        jobs = await _workflow_activation_jobs(
            context, work_root=root, workflow_id=definition.id
        )
        cancelled: list[str] = []
        for job in jobs:
            view = activation_view(job)
            if requested_id and view["trigger_id"] != requested_id:
                continue
            if view["status"] not in {"scheduled", "waiting", "running", "paused"}:
                continue
            await _execute_arrange(context, "arrange.cancel", {"job_id": view["id"]})
            cancelled.append(view["id"])
    except (LookupError, RuntimeError, TypeError, ValueError) as exc:
        return _error(request, exc)
    return OperationResult(name=request.name, payload={"cancelled": cancelled})


async def workflow_run(request: OperationRequest, *, context: PluginContext | None = None, **_: Any) -> OperationResult:
    payload = request.payload
    activation = payload.get("activation")
    activation = activation if isinstance(activation, dict) else {}
    name = _name(payload) or str(activation.get("workflow_name") or activation.get("workflowName") or "").strip()
    if not name:
        return _error(request, "name is required")
    requested_workflow_id = str(
        payload.get("workflow_id")
        or payload.get("workflowId")
        or activation.get("workflow_id")
        or activation.get("workflowId")
        or ""
    ).strip()
    raw_requested_revision = payload.get(
        "workflow_revision",
        payload.get(
            "workflowRevision",
            activation.get("workflow_revision", activation.get("workflowRevision")),
        ),
    )
    try:
        requested_revision = int(raw_requested_revision) if raw_requested_revision not in (None, "") else None
    except (TypeError, ValueError):
        return _error(request, "workflow_revision must be an integer")
    thread_id = ""
    run_id = ""
    registry: Any | None = None
    run_claimed = False
    try:
        runtime = _runtime(context)
        work_root = _scoped_work_root(context, payload)
        definition = await runtime.manager.get(name, work_root=work_root)
        if definition is None:
            return _error(request, f"Workflow not found: {name}")
        if requested_workflow_id and definition.id != requested_workflow_id:
            return _error(
                request,
                f"Workflow identity mismatch: requested {requested_workflow_id}, found {definition.id}",
            )
        if requested_revision is not None and definition.revision != requested_revision:
            return _error(
                request,
                f"Workflow revision {requested_revision} is not available; current revision is {definition.revision}",
            )
        work_root = work_root or definition.work_root or str(context.work_root if context else "")
        await _ensure_workflow_session(context, definition)
        thread_id = str(payload.get("thread_id") or payload.get("threadId") or _session_id(definition))
        run_id = str(payload.get("run_id") or payload.get("runId") or f"workflow_run_{uuid.uuid4().hex[:12]}")
        inputs = dict(payload.get("inputs") or {})
        raw_max_steps = payload.get("max_steps", payload.get("maxSteps"))
        if raw_max_steps in ("", None):
            max_steps = None
        else:
            try:
                max_steps = int(raw_max_steps)
            except (TypeError, ValueError):
                max_steps = None
        start_node = str(payload.get("start_node") or payload.get("startNode") or "") or None
        single_node = str(payload.get("single_node") or payload.get("singleNode") or "") or None
        prior_values_provided, prior_values = _provided_mapping(payload, "prior_values", "priorValues")
        prior_states_provided, prior_states_raw = _provided_mapping(
            payload, "prior_node_states", "priorNodeStates"
        )
        prior_states: dict[str, WorkflowNodeState] | None = None
        if isinstance(prior_states_raw, dict):
            prior_states = {}
            for node_id, raw in prior_states_raw.items():
                prior_states[str(node_id)] = raw if isinstance(raw, WorkflowNodeState) else WorkflowNodeState.from_dict(
                    raw or {}, node_id=str(node_id)
                )
        registry = context.runtime_task_registry if context is not None else None
        if registry is not None:
            if not registry.accept_run(thread_id, run_id):
                return _error(request, f"workflow thread already has an active run: {thread_id}")
            run_claimed = True
            current_task = asyncio.current_task()
            register = getattr(registry, "register", None)
            if current_task is not None and callable(register):
                if not register(thread_id, current_task, run_id=run_id):
                    registry.release_run(thread_id, run_id=run_id)
                    run_claimed = False
                    return _error(request, f"could not register workflow run: {run_id}")
        if getattr(runtime.runner, "sub_agent_runner", None) is None and context is not None:
            factory = context.service("sub_agent_runner_factory")
            if callable(factory):
                candidate = factory()
                runtime.runner.sub_agent_runner = await _maybe_await(candidate)
                # New runners invoke through the explicit AgentInvoker
                # boundary; keep the legacy attribute assignment above for
                # hosts that still inspect it.
                from .adapters import adapt_agent_invoker

                runtime.runner.agent_invoker = adapt_agent_invoker(runtime.runner.sub_agent_runner)
        run_kwargs: dict[str, Any] = {
            "inputs": inputs,
            "work_root": work_root,
            "thread_id": thread_id,
            "run_id": run_id,
            "max_steps": max_steps,
            "start_node": start_node,
            "single_node": single_node,
            "execution_context": _execution_context(request, context, work_root, thread_id, run_id),
        }
        if prior_values_provided:
            run_kwargs["prior_values"] = prior_values
        if prior_states_provided:
            run_kwargs["prior_node_states"] = prior_states
        result = await runtime.runner.run(definition, **run_kwargs)
        if result.status == "paused":
            await _schedule_human_task_timeout(
                context,
                work_root=work_root,
                thread_id=thread_id,
                run_id=run_id,
                descriptor=dict(result.wait_descriptor or {}),
            )
    except asyncio.CancelledError:
        # workflow.cancel force-cancels the registered operation task so a
        # command/script subprocess is interrupted immediately. Convert that
        # task cancellation back into the plugin's stable operation contract;
        # callers receive a normal ``run.status=cancelled`` response.
        cancelled = WorkflowRunResult(status="cancelled", error="cancelled", run_id=run_id)
        return OperationResult(
            name=request.name,
            payload={"run": cancelled.to_dict(), "thread_id": thread_id, "run_id": run_id},
        )
    except Exception as exc:  # noqa: BLE001 — operation boundary
        return _error(request, exc)
    finally:
        # The operation owns the registry claim for the complete run. The
        # runner's task registry is used for cancellation, but must not keep
        # the session claimed after a normal success/failure return.
        if run_claimed and registry is not None and thread_id and run_id:
            release = getattr(registry, "release_run", None)
            if callable(release):
                release(thread_id, run_id=run_id)
    return OperationResult(name=request.name, payload={"run": result.to_dict(), "thread_id": thread_id, "run_id": run_id})


async def workflow_cancel(request: OperationRequest, *, context: PluginContext | None = None, **_: Any) -> OperationResult:
    thread_id = str(request.payload.get("thread_id") or request.payload.get("threadId") or "")
    run_id = str(request.payload.get("run_id") or request.payload.get("runId") or "")
    if not thread_id:
        return _error(request, "thread_id is required")
    registry = context.runtime_task_registry if context is not None else None
    if registry is None:
        return _error(request, "cancellation not available in this host")
    try:
        registry.cancel(thread_id, run_id=run_id or None, force=True)
    except Exception as exc:  # noqa: BLE001
        return _error(request, exc)
    return OperationResult(name=request.name, payload={"cancelled": True, "thread_id": thread_id, "run_id": run_id})


async def workflow_signal(request: OperationRequest, *, context: PluginContext | None = None, **_: Any) -> OperationResult:
    payload = request.payload
    thread_id = str(payload.get("thread_id") or payload.get("threadId") or "").strip()
    run_id = str(payload.get("run_id") or payload.get("runId") or "").strip()
    resume_token = str(payload.get("resume_token") or payload.get("resumeToken") or "")
    event_type = str(payload.get("event_type") or payload.get("eventType") or "").strip()
    signal_payload = payload.get("payload")
    if signal_payload is not None and not isinstance(signal_payload, dict):
        return _error(request, "payload must be an object")
    try:
        runtime = _runtime(context)
        result = await runtime.runner.signal(
            thread_id=thread_id,
            run_id=run_id,
            resume_token=resume_token,
            event_type=event_type,
            payload=signal_payload,
            decision=str(payload.get("decision") or ""),
        )
        queue = getattr(runtime, "queue", None)
        update_queue = getattr(queue, "update_from_result", None)
        if callable(update_queue):
            await _maybe_await(update_queue(run_id, result))
        if result.status == "paused":
            await _schedule_human_task_timeout(
                context,
                work_root=str(
                    payload.get("work_root")
                    or payload.get("workRoot")
                    or getattr(context, "work_root", "")
                ),
                thread_id=thread_id,
                run_id=run_id,
                descriptor=dict(result.wait_descriptor or {}),
            )
    except (LookupError, RuntimeError, TypeError, ValueError) as exc:
        return _error(request, exc)
    return OperationResult(
        name=request.name,
        payload={"run": result.to_dict(), "thread_id": thread_id, "run_id": run_id},
    )


async def workflow_human_task_list(
    request: OperationRequest,
    *,
    context: PluginContext | None = None,
    **_: Any,
) -> OperationResult:
    """List the projected human-task center without bearer credentials."""

    payload = request.payload
    try:
        center = _human_tasks(context)
        root, include_all = task_scope(
            payload,
            default_work_root=str(context.work_root if context is not None else ""),
        )
        status = str(payload.get("status") or ("all" if payload.get("include_completed") else "pending"))
        tasks = await center.list(
            work_root=root,
            include_all=include_all,
            status=status,
            workflow_id=str(payload.get("workflow_id") or payload.get("workflowId") or ""),
            workflow_name=str(payload.get("workflow_name") or payload.get("workflowName") or ""),
            thread_id=str(payload.get("thread_id") or payload.get("threadId") or ""),
            limit=payload.get("limit", 100),
            include_audit=bool(payload.get("include_audit") or payload.get("includeAudit")),
        )
    except (RuntimeError, TypeError, ValueError) as exc:
        return _error(request, exc)
    return OperationResult(
        name=request.name,
        payload={
            "tasks": tasks,
            "pending": [item for item in tasks if item.get("status") == "pending"],
            "count": len(tasks),
        },
    )


async def workflow_human_task_get(
    request: OperationRequest,
    *,
    context: PluginContext | None = None,
    **_: Any,
) -> OperationResult:
    payload = request.payload
    task_id = str(payload.get("task_id") or payload.get("taskId") or payload.get("id") or "").strip()
    if not task_id:
        return _error(request, "task_id is required")
    try:
        center = _human_tasks(context)
        root, include_all = task_scope(
            payload,
            default_work_root=str(context.work_root if context is not None else ""),
        )
        task = await center.get(task_id, work_root=root, include_all=include_all)
    except (RuntimeError, TypeError, ValueError) as exc:
        return _error(request, exc)
    if task is None:
        return _error(request, f"Human task not found: {task_id}")
    return OperationResult(name=request.name, payload={"task": task, "audit": task.get("audit", [])})


async def workflow_human_task_complete(
    request: OperationRequest,
    *,
    context: PluginContext | None = None,
    **_: Any,
) -> OperationResult:
    payload = request.payload
    task_id = str(payload.get("task_id") or payload.get("taskId") or payload.get("id") or "").strip()
    if not task_id:
        return _error(request, "task_id is required")
    raw_data = payload.get("payload", payload.get("form_data", payload.get("formData", {})))
    if raw_data is None:
        raw_data = {}
    if not isinstance(raw_data, dict):
        return _error(request, "payload must be an object")
    try:
        center = _human_tasks(context)
        root, include_all = task_scope(
            payload,
            default_work_root=str(context.work_root if context is not None else ""),
        )
        result = await center.complete(
            task_id,
            decision=str(payload.get("decision") or payload.get("action") or ""),
            payload=raw_data,
            work_root=root,
            include_all=include_all,
        )
    except (LookupError, RuntimeError, TypeError, ValueError) as exc:
        return _error(request, exc)
    return OperationResult(name=request.name, payload=result)


async def workflow_human_task_timeout(
    request: OperationRequest,
    *,
    context: PluginContext | None = None,
    **_: Any,
) -> OperationResult:
    """Arrange-only timeout hook; its payload intentionally contains no token."""

    payload = request.payload
    task_id = str(payload.get("task_id") or payload.get("taskId") or "").strip()
    if not task_id:
        # The scheduler payload is permitted to identify a task by its stable
        # non-secret run/node tuple instead of copying a task id.
        run_id = str(payload.get("run_id") or payload.get("runId") or "").strip()
        node_id = str(payload.get("node_id") or payload.get("nodeId") or "").strip()
        if run_id and node_id:
            task_id = f"{run_id}:{node_id}"
    if not task_id:
        return _error(request, "task_id or run_id/node_id is required")
    try:
        center = _human_tasks(context)
        root, include_all = task_scope(
            payload,
            default_work_root=str(context.work_root if context is not None else ""),
        )
        result = await center.timeout(
            task_id,
            work_root=root,
            include_all=include_all,
        )
        run = result.get("run")
        if run is not None:
            runtime = _runtime(context)
            queue = getattr(runtime, "queue", None)
            update_queue = getattr(queue, "update_from_result", None)
            run_id = str(payload.get("run_id") or payload.get("runId") or "")
            if callable(update_queue) and run_id:
                await _maybe_await(update_queue(run_id, run))
    except (LookupError, RuntimeError, TypeError, ValueError) as exc:
        return _error(request, exc)
    return OperationResult(name=request.name, payload=result)


async def workflow_node_types(
    request: OperationRequest,
    *,
    context: PluginContext | None = None,
    **_: Any,
) -> OperationResult:
    """Return schema-only node metadata (the Workflow object-info surface)."""
    try:
        registry = _node_registry(context)
        requested = str(
            request.payload.get("name")
            or request.payload.get("node_type")
            or request.payload.get("nodeType")
            or ""
        ).strip()
        info = registry.object_info(requested or None)
    except (KeyError, RuntimeError, TypeError, ValueError) as exc:
        return _error(request, exc)
    return OperationResult(
        name=request.name,
        payload={"node_types": info, "object_info": info},
    )


async def workflow_object_info(
    request: OperationRequest,
    *,
    context: PluginContext | None = None,
    **_: Any,
) -> OperationResult:
    return await workflow_node_types(request, context=context)


def _queue_item_payload(item: WorkflowQueueItem) -> dict[str, Any]:
    return item.to_dict()


async def workflow_queue_enqueue(
    request: OperationRequest,
    *,
    context: PluginContext | None = None,
    **_: Any,
) -> OperationResult:
    payload = request.payload
    name = str(
        payload.get("name")
        or payload.get("workflow_name")
        or payload.get("workflowName")
        or ""
    ).strip()
    workflow_id = str(payload.get("workflow_id") or payload.get("workflowId") or "").strip()
    if not name and not workflow_id:
        return _error(request, "name or workflow_id is required")
    try:
        runtime = _runtime(context)
        work_root = _scoped_work_root(context, payload)
        definition = await runtime.manager.get(name, work_root=work_root) if name else None
        if definition is None and workflow_id:
            definitions = await runtime.manager.list(work_root=work_root)
            definition = next((item for item in definitions if item.id == workflow_id), None)
        if definition is None:
            return _error(request, f"Workflow not found: {name or workflow_id}")
        raw_max_steps = payload.get("max_steps", payload.get("maxSteps"))
        max_steps = int(raw_max_steps) if raw_max_steps not in (None, "") else None
        prior_values_provided, prior_values = _provided_mapping(payload, "prior_values", "priorValues")
        prior_states_provided, prior_states_raw = _provided_mapping(
            payload, "prior_node_states", "priorNodeStates"
        )
        queue_kwargs: dict[str, Any] = {
            "workflow_name": definition.name,
            "workflow_id": definition.id,
            "work_root": work_root or definition.work_root or (str(context.work_root) if context else ""),
            "inputs": dict(payload.get("inputs") or {}),
            "thread_id": str(payload.get("thread_id") or payload.get("threadId") or ""),
            "run_id": str(payload.get("run_id") or payload.get("runId") or ""),
            "max_steps": max_steps,
            "start_node": str(payload.get("start_node") or payload.get("startNode") or "") or None,
            "single_node": str(payload.get("single_node") or payload.get("singleNode") or "") or None,
            "metadata": {**dict(request.metadata or {}), **dict(payload.get("metadata") or {})},
        }
        if prior_values_provided:
            queue_kwargs["prior_values"] = prior_values
        if prior_states_provided:
            queue_kwargs["prior_node_states"] = prior_states_raw
        item = await _queue(context).enqueue(
            definition,
            **queue_kwargs,
        )
    except (LookupError, RuntimeError, TypeError, ValueError) as exc:
        return _error(request, exc)
    data = _queue_item_payload(item)
    return OperationResult(
        name=request.name,
        payload={"queue": data, "item": data, "queue_id": item.queue_id, "run_id": item.run_id},
    )


async def workflow_queue_list(
    request: OperationRequest,
    *,
    context: PluginContext | None = None,
    **_: Any,
) -> OperationResult:
    payload = request.payload
    try:
        work_root = _scoped_work_root(context, payload)
        status = payload.get("status")
        limit_raw = payload.get("limit")
        limit = int(limit_raw) if limit_raw not in (None, "") else None
        values = await _queue(context).list(
            status=status,
            work_root=work_root,
            workflow_id=str(payload.get("workflow_id") or payload.get("workflowId") or ""),
            workflow_name=str(payload.get("name") or payload.get("workflow_name") or ""),
            include_history=bool(payload.get("include_history", payload.get("includeHistory", False))),
            limit=limit,
        )
    except (RuntimeError, TypeError, ValueError) as exc:
        return _error(request, exc)
    return OperationResult(name=request.name, payload={"queue": [_queue_item_payload(item) for item in values], "items": [_queue_item_payload(item) for item in values]})


async def workflow_queue_history(
    request: OperationRequest,
    *,
    context: PluginContext | None = None,
    **_: Any,
) -> OperationResult:
    payload = request.payload
    try:
        limit_raw = payload.get("limit")
        limit = int(limit_raw) if limit_raw not in (None, "") else None
        values = await _queue(context).history(
            work_root=_scoped_work_root(context, payload),
            workflow_id=str(payload.get("workflow_id") or payload.get("workflowId") or ""),
            workflow_name=str(payload.get("name") or payload.get("workflow_name") or ""),
            status=payload.get("status"),
            limit=limit,
            include_active=bool(payload.get("include_active", payload.get("includeActive", False))),
        )
    except (RuntimeError, TypeError, ValueError) as exc:
        return _error(request, exc)
    return OperationResult(name=request.name, payload={"history": [_queue_item_payload(item) for item in values], "items": [_queue_item_payload(item) for item in values]})


async def workflow_queue_get(
    request: OperationRequest,
    *,
    context: PluginContext | None = None,
    **_: Any,
) -> OperationResult:
    payload = request.payload
    queue_id = str(payload.get("queue_id") or payload.get("queueId") or payload.get("id") or "").strip()
    run_id = str(payload.get("run_id") or payload.get("runId") or "").strip()
    if not queue_id and not run_id:
        return _error(request, "queue_id or run_id is required")
    try:
        item = await _queue(context).get(queue_id, run_id=run_id)
    except RuntimeError as exc:
        return _error(request, exc)
    if item is None:
        return _error(request, "workflow queue item not found")
    return OperationResult(name=request.name, payload={"queue": _queue_item_payload(item), "item": _queue_item_payload(item)})


async def workflow_queue_clear(
    request: OperationRequest,
    *,
    context: PluginContext | None = None,
    **_: Any,
) -> OperationResult:
    payload = request.payload
    # ``confirm`` is intentionally mandatory even though the default only
    # removes terminal history.  ``all`` additionally removes queued items.
    confirm = bool(payload.get("confirm", False))
    all_items = bool(
        payload.get(
            "all",
            payload.get("all_items", payload.get("allItems", payload.get("clear_all", False))),
        )
    )
    try:
        removed = await _queue(context).clear(
            confirm=confirm,
            all_items=all_items,
            work_root=_scoped_work_root(context, payload),
            workflow_id=str(payload.get("workflow_id") or payload.get("workflowId") or ""),
            workflow_name=str(payload.get("name") or payload.get("workflow_name") or ""),
        )
    except (RuntimeError, TypeError, ValueError) as exc:
        return _error(request, exc)
    return OperationResult(name=request.name, payload={"cleared": removed, "count": removed, "all": all_items})


async def workflow_queue_cancel(
    request: OperationRequest,
    *,
    context: PluginContext | None = None,
    **_: Any,
) -> OperationResult:
    payload = request.payload
    queue_id = str(payload.get("queue_id") or payload.get("queueId") or payload.get("id") or "").strip()
    run_id = str(payload.get("run_id") or payload.get("runId") or "").strip()
    if not queue_id and not run_id:
        return _error(request, "queue_id or run_id is required")
    try:
        item = await _queue(context).cancel(queue_id, run_id=run_id)
    except (RuntimeError, TypeError, ValueError) as exc:
        return _error(request, exc)
    if item is None:
        return _error(request, "workflow queue item not found")
    data = _queue_item_payload(item)
    return OperationResult(name=request.name, payload={"cancelled": item.status == "cancelled", "queue": data, "item": data})


async def workflow_tools_list(request: OperationRequest, *, context: PluginContext | None = None, **_: Any) -> OperationResult:
    try:
        specs = _runtime(context).tool_specs
    except RuntimeError:
        specs = []
    return OperationResult(name=request.name, payload={"tools": [{"name": getattr(item, "name", ""), "description": getattr(item, "description", "")} for item in specs]})


__all__ = [
    "workflow_activate", "workflow_activation_list", "workflow_cancel", "workflow_create",
    "workflow_deactivate", "workflow_delete", "workflow_expose", "workflow_get",
    "workflow_human_task_list", "workflow_human_task_get", "workflow_human_task_complete",
    "workflow_human_task_timeout",
    "workflow_list", "workflow_list_grouped", "workflow_run", "workflow_signal", "workflow_save", "workflow_rename",
    "workflow_tools_list", "workflow_unexpose", "workflow_update", "workflow_node_types",
    "workflow_object_info", "workflow_queue_enqueue", "workflow_queue_list",
    "workflow_queue_history", "workflow_queue_get", "workflow_queue_clear",
    "workflow_queue_cancel",
]
