"""RPC operations contributed by the bundled Workflow plugin."""

from __future__ import annotations

import asyncio
import inspect
import uuid
from typing import Any

from lamtools_core.app.operation_catalog import OperationRequest, OperationResult
from lamtools_core.plugins.context import PluginContext
from lamtools_core.session import build_session_record

from .runtime import WorkflowDef, WorkflowNodeState, WorkflowRunResult


def _runtime(context: PluginContext | None) -> Any:
    if context is None:
        raise RuntimeError("workflow plugin context is not configured")
    runtime = context.service("workflow")
    if runtime is None:
        raise RuntimeError("workflow plugin is not loaded")
    return runtime


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
    return OperationResult(name=request.name, payload={"workflow": definition.to_dict(), "session_id": session_id})


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
        )
    except (LookupError, RuntimeError, TypeError, ValueError) as exc:
        return _error(request, exc)
    session_id = await _ensure_workflow_session(context, definition)
    return OperationResult(name=request.name, payload={"workflow": definition.to_dict(), "session_id": session_id})


async def workflow_save(request: OperationRequest, *, context: PluginContext | None = None, **_: Any) -> OperationResult:
    """Create or replace a workflow definition through the plugin boundary."""
    raw = request.payload.get("workflow")
    payload = dict(raw) if isinstance(raw, dict) else dict(request.payload)
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


async def workflow_run(request: OperationRequest, *, context: PluginContext | None = None, **_: Any) -> OperationResult:
    payload = request.payload
    name = _name(payload)
    if not name:
        return _error(request, "name is required")
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
        prior_values = dict(payload.get("prior_values") or payload.get("priorValues") or {})
        prior_states_raw = payload.get("prior_node_states") or payload.get("priorNodeStates") or {}
        prior_states: dict[str, WorkflowNodeState] = {}
        if isinstance(prior_states_raw, dict):
            for node_id, raw in prior_states_raw.items():
                prior_states[str(node_id)] = raw if isinstance(raw, WorkflowNodeState) else WorkflowNodeState(
                    node_id=str(node_id), status=str((raw or {}).get("status") or "idle"), output=(raw or {}).get("output"), error=str((raw or {}).get("error") or ""),
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
        result = await runtime.runner.run(
            definition,
            inputs=inputs,
            work_root=work_root,
            thread_id=thread_id,
            run_id=run_id,
            prior_values=prior_values,
            prior_node_states=prior_states or None,
            max_steps=max_steps,
            start_node=start_node,
            single_node=single_node,
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


async def workflow_tools_list(request: OperationRequest, *, context: PluginContext | None = None, **_: Any) -> OperationResult:
    try:
        specs = _runtime(context).tool_specs
    except RuntimeError:
        specs = []
    return OperationResult(name=request.name, payload={"tools": [{"name": getattr(item, "name", ""), "description": getattr(item, "description", "")} for item in specs]})


__all__ = [
    "workflow_cancel", "workflow_create", "workflow_delete", "workflow_expose", "workflow_get",
    "workflow_list", "workflow_list_grouped", "workflow_run", "workflow_save", "workflow_rename",
    "workflow_tools_list", "workflow_unexpose", "workflow_update",
]
