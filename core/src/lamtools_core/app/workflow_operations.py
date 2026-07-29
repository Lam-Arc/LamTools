"""Workflow operations shared by HTTP, GUI, and CLI.

Mirrors :mod:`lamtools_core.app.durable_operations`: a single
``register_workflow_operations`` function that installs handlers for every name
in :data:`CORE_WORKFLOW_OPERATION_NAMES` onto an :class:`OperationCatalog`.

``workflow.run`` executes the graph inline (the runner streams per-node state
through the injected ``emit`` callback *during* the run, so a subscribed GUI
receives ``core/runItem`` events before the request returns). Cooperative
cancellation is wired through ``RuntimeTaskRegistry.get_cancel_event`` so a
concurrent ``workflow.cancel`` aborts at the next node boundary.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from lamtools_core.runtime.workflow import WorkflowDef, WorkflowManager, WorkflowRunner

from .operation_catalog import OperationCatalog, OperationRequest, OperationResult
from .operation_groups import CORE_WORKFLOW_OPERATION_NAMES


def register_workflow_operations(
    catalog: OperationCatalog,
    *,
    workflow_manager: WorkflowManager,
    runner: WorkflowRunner,
    runtime_task_registry: Any = None,
    list_tool_specs: Callable[[], list[Any]] | None = None,
    session_store: Any = None,
) -> None:
    """Register all workflow.* operations onto ``catalog``."""

    async def workflow_create(request: OperationRequest) -> OperationResult:
        payload = request.payload
        try:
            definition = WorkflowDef.from_dict(dict(payload))
            if not definition.name:
                return _error(request, "name is required")
            definition = await workflow_manager.create(definition)
        except (TypeError, ValueError) as exc:
            return _error(request, exc)
        return OperationResult(name=request.name, payload={"workflow": definition.to_dict()})

    async def workflow_get(request: OperationRequest) -> OperationResult:
        name = _name(request.payload)
        if not name:
            return _error(request, "name is required")
        work_root = _optional_text(request.payload, "work_root", "workRoot")
        definition = await workflow_manager.get(name, work_root=work_root)
        if definition is None:
            return _error(request, f"Workflow not found: {name}")
        return OperationResult(name=request.name, payload={"workflow": definition.to_dict()})

    async def workflow_list(request: OperationRequest) -> OperationResult:
        work_root = _optional_text(request.payload, "work_root", "workRoot")
        defs = await workflow_manager.list(work_root=work_root)
        return OperationResult(
            name=request.name,
            payload={"workflows": [d.to_dict() for d in defs]},
        )

    async def workflow_list_grouped(request: OperationRequest) -> OperationResult:
        raw = request.payload.get("work_roots") or request.payload.get("workRoots") or []
        work_roots = [str(r) for r in raw if str(r)] if isinstance(raw, (list, tuple)) else []
        grouped = await workflow_manager.list_grouped(work_roots=work_roots)
        return OperationResult(
            name=request.name,
            payload={
                "groups": {
                    key: [d.to_dict() for d in defs]
                    for key, defs in grouped.items()
                },
            },
        )

    async def workflow_update(request: OperationRequest) -> OperationResult:
        payload = request.payload
        name = _name(payload)
        if not name:
            return _error(request, "name is required")
        work_root = _optional_text(payload, "work_root", "workRoot")
        try:
            definition = await workflow_manager.update_fields(
                name,
                work_root=work_root,
                description=(str(payload.get("description") or "") if "description" in payload else None),
                nodes=list(payload.get("nodes") or []) if "nodes" in payload else None,
                edges=list(payload.get("edges") or []) if "edges" in payload else None,
                input_params=list(payload.get("input_params") or payload.get("inputParams") or []) if "input_params" in payload or "inputParams" in payload else None,
                output_port=(str(payload.get("output_port") or payload.get("outputPort") or "") if "output_port" in payload or "outputPort" in payload else None),
                exposed=bool(payload.get("exposed")) if "exposed" in payload else None,
                tool_name=(str(payload.get("tool_name") or payload.get("toolName") or "") if "tool_name" in payload or "toolName" in payload else None),
            )
        except (LookupError, TypeError, ValueError) as exc:
            return _error(request, exc)
        return OperationResult(name=request.name, payload={"workflow": definition.to_dict()})

    async def workflow_delete(request: OperationRequest) -> OperationResult:
        name = _name(request.payload)
        if not name:
            return _error(request, "name is required")
        work_root = _optional_text(request.payload, "work_root", "workRoot")
        removed = await workflow_manager.delete(name, work_root=work_root)
        return OperationResult(name=request.name, payload={"deleted": removed, "name": name})

    async def workflow_expose(request: OperationRequest, exposed: bool) -> OperationResult:
        name = _name(request.payload)
        if not name:
            return _error(request, "name is required")
        work_root = _optional_text(request.payload, "work_root", "workRoot")
        try:
            definition = await workflow_manager.set_exposed(name, exposed, work_root=work_root)
        except LookupError as exc:
            return _error(request, exc)
        return OperationResult(name=request.name, payload={"workflow": definition.to_dict()})

    async def workflow_run(request: OperationRequest) -> OperationResult:
        payload = request.payload
        name = _name(payload)
        if not name:
            return _error(request, "name is required")
        work_root = _optional_text(payload, "work_root", "workRoot")
        definition = await workflow_manager.get(name, work_root=work_root)
        if definition is None:
            return _error(request, f"Workflow not found: {name}")
        if not work_root:
            work_root = definition.work_root
        thread_id = str(payload.get("thread_id") or payload.get("threadId") or f"workflow_thread_{uuid.uuid4().hex}")
        run_id = str(payload.get("run_id") or payload.get("runId") or f"workflow_run_{uuid.uuid4().hex[:12]}")
        inputs = dict(payload.get("inputs") or {})
        max_steps = payload.get("max_steps", payload.get("maxSteps"))
        if max_steps in ("", None):
            max_steps = None
        else:
            try:
                max_steps = int(max_steps)
            except (TypeError, ValueError):
                max_steps = None
        start_node = str(payload.get("start_node") or payload.get("startNode") or "") or None
        single_node = str(payload.get("single_node") or payload.get("singleNode") or "") or None
        prior_values = dict(payload.get("prior_values") or payload.get("priorValues") or {})
        prior_states_raw = payload.get("prior_node_states") or payload.get("priorNodeStates") or {}
        prior_states: dict[str, Any] = {}
        if isinstance(prior_states_raw, dict):
            from lamtools_core.runtime.workflow import WorkflowNodeState

            for nid, raw in prior_states_raw.items():
                prior_states[nid] = (
                    raw if isinstance(raw, WorkflowNodeState)
                    else WorkflowNodeState(node_id=nid, status=str((raw or {}).get("status") or "idle"), output=(raw or {}).get("output"), error=str((raw or {}).get("error") or ""))
                )

        # Accept a runtime_task_registry to enable cooperative cancellation.
        registry = runtime_task_registry
        if registry is not None:
            try:
                registry.accept_run(thread_id, run_id)
            except Exception:  # noqa: BLE001 — cancellation is best-effort
                pass

        try:
            result = await runner.run(
                definition,
                inputs=inputs,
                work_root=work_root or "",
                thread_id=thread_id,
                run_id=run_id,
                prior_values=prior_values,
                prior_node_states=prior_states or None,
                max_steps=max_steps,
                start_node=start_node,
                single_node=single_node,
            )
        except Exception as exc:  # noqa: BLE001 — surface as operation error
            return _error(request, exc)
        return OperationResult(
            name=request.name,
            payload={"run": result.to_dict(), "thread_id": thread_id, "run_id": run_id},
        )

    async def workflow_cancel(request: OperationRequest) -> OperationResult:
        thread_id = str(request.payload.get("thread_id") or request.payload.get("threadId") or "")
        run_id = str(request.payload.get("run_id") or request.payload.get("runId") or "")
        if not thread_id:
            return _error(request, "thread_id is required")
        if runtime_task_registry is None:
            return _error(request, "cancellation not available in this host")
        try:
            runtime_task_registry.cancel(thread_id, run_id=run_id or None, force=True)
        except Exception as exc:  # noqa: BLE001
            return _error(request, exc)
        return OperationResult(
            name=request.name,
            payload={"cancelled": True, "thread_id": thread_id, "run_id": run_id},
        )

    async def workflow_edit(request: OperationRequest) -> OperationResult:
        """Natural-language graph editing: one structured LLM call that returns
        ``{reply, graph}``. The graph is validated, saved, and returned.

        The conversation (user + assistant messages) is persisted to a Core
        session thread bound to the workflow (``wf_edit_<name>``), so it
        survives refreshes and belongs to the workflow, not the frontend."""
        payload = request.payload
        name = _name(payload)
        if not name:
            return _error(request, "name is required")
        work_root = _optional_text(payload, "work_root", "workRoot")
        message = str(payload.get("message") or "").strip()
        if not message:
            return _error(request, "message is required")
        model_id = str(payload.get("model_id") or payload.get("modelId") or "") or None
        reasoning_effort = str(payload.get("reasoning_effort") or payload.get("reasoningEffort") or "") or None
        temperature = payload.get("temperature")

        definition = await workflow_manager.get(name, work_root=work_root)
        if definition is None:
            return _error(request, f"Workflow not found: {name}")
        if not work_root:
            work_root = definition.work_root

        thread_id = _workflow_edit_thread_id(name)
        # Load prior conversation from the session (the source of truth).
        history = await _load_edit_messages(session_store, thread_id)
        await _append_edit_message(session_store, thread_id, "user", message)

        from lamtools_core.llm import ChatMessage, LLMRequest

        system_prompt = _workflow_edit_system_prompt(definition)
        messages: list[ChatMessage] = [ChatMessage(role="system", content=system_prompt)]
        for entry in history:
            messages.append(ChatMessage(role=str(entry.get("role")), content=str(entry.get("content"))))
        messages.append(ChatMessage(role="user", content=message))

        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "workflow_edit",
                "schema": {
                    "type": "object",
                    "properties": {
                        "reply": {"type": "string", "description": "简短说明这次做了什么改动"},
                        "graph": {
                            "type": "object",
                            "description": "完整的 WorkflowDef JSON（修改后的整个图）",
                            "properties": {
                                "name": {"type": "string"},
                                "description": {"type": "string"},
                                "nodes": {"type": "array"},
                                "edges": {"type": "array"},
                                "input_params": {"type": "array"},
                                "output_port": {"type": "string"},
                                "exposed": {"type": "boolean"},
                                "tool_name": {"type": "string"},
                            },
                            "required": ["name", "nodes", "edges"],
                        },
                    },
                    "required": ["reply", "graph"],
                },
            },
        }

        try:
            request_obj = LLMRequest(
                messages=messages,
                model=model_id,
                temperature=float(temperature) if temperature is not None else None,
                response_format=response_format,
                metadata={"reasoning_effort": reasoning_effort} if reasoning_effort else {},
            )
            response = await runner.llm_client.complete(request_obj)
        except Exception as exc:  # noqa: BLE001
            return _error(request, f"LLM call failed: {exc}")

        import json as _json

        reply_text = ""
        edited_def = None
        try:
            parsed = _json.loads(response.content)
            reply_text = str(parsed.get("reply") or "")
            graph = parsed.get("graph")
            if isinstance(graph, dict):
                graph.setdefault("name", definition.name)
                graph["work_root"] = work_root
                edited_def = WorkflowDef.from_dict(graph)
        except (TypeError, ValueError) as exc:
            return _error(request, f"failed to parse LLM graph output: {exc}")

        if edited_def is None:
            await _append_edit_message(session_store, thread_id, "assistant", reply_text or response.content)
            conv = await _load_edit_messages(session_store, thread_id)
            return OperationResult(
                name=request.name,
                payload={
                    "reply": reply_text or response.content,
                    "workflow": definition.to_dict(),
                    "applied": False,
                    "messages": conv,
                },
            )

        try:
            saved = await workflow_manager.update_fields(
                name,
                work_root=work_root,
                description=edited_def.description,
                nodes=[n.to_dict() for n in edited_def.nodes],
                edges=[e.to_dict() for e in edited_def.edges],
                input_params=[p.to_dict() for p in edited_def.input_params],
                output_port=edited_def.output_port,
                exposed=edited_def.exposed,
                tool_name=edited_def.tool_name,
            )
        except (LookupError, TypeError, ValueError) as exc:
            return _error(request, exc)
        await _append_edit_message(session_store, thread_id, "assistant", reply_text)
        conv = await _load_edit_messages(session_store, thread_id)
        return OperationResult(
            name=request.name,
            payload={"reply": reply_text, "workflow": saved.to_dict(), "applied": True, "messages": conv},
        )

    async def workflow_edit_read(request: OperationRequest) -> OperationResult:
        """Load the persisted NL-edit conversation for a workflow."""
        name = _name(request.payload)
        if not name:
            return _error(request, "name is required")
        thread_id = _workflow_edit_thread_id(name)
        messages = await _load_edit_messages(session_store, thread_id)
        return OperationResult(name=request.name, payload={"messages": messages, "thread_id": thread_id})

    async def workflow_tools_list(request: OperationRequest) -> OperationResult:
        specs: list[Any] = []
        if list_tool_specs is not None:
            try:
                raw = list_tool_specs()
                if raw:
                    specs = [
                        {"name": getattr(s, "name", ""), "description": getattr(s, "description", "")}
                        for s in raw
                    ]
            except Exception:  # noqa: BLE001 — listing must not fail the op
                specs = []
        return OperationResult(name=request.name, payload={"tools": specs})

    handlers = {
        "workflow.create": workflow_create,
        "workflow.get": workflow_get,
        "workflow.list": workflow_list,
        "workflow.list_grouped": workflow_list_grouped,
        "workflow.update": workflow_update,
        "workflow.delete": workflow_delete,
        "workflow.run": workflow_run,
        "workflow.cancel": workflow_cancel,
        "workflow.edit": workflow_edit,
        "workflow.edit.read": workflow_edit_read,
        "workflow.expose": lambda req: workflow_expose(req, True),
        "workflow.unexpose": lambda req: workflow_expose(req, False),
        "workflow.tools.list": workflow_tools_list,
    }
    for name in CORE_WORKFLOW_OPERATION_NAMES:
        catalog.register(name, handlers[name])


def _name(payload: dict[str, Any]) -> str:
    return str(payload.get("name") or "").strip()


def _optional_text(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        if key in payload:
            value = str(payload.get(key) or "").strip()
            return value or None
    return None


def _error(request: OperationRequest, error: object) -> OperationResult:
    return OperationResult(name=request.name, status="error", payload={"error": str(error)})


def _workflow_edit_system_prompt(definition: WorkflowDef) -> str:
    """System prompt describing the WorkflowDef schema + current graph."""
    import json as _json

    current_graph = _json.dumps(definition.to_dict(), ensure_ascii=False, indent=2)
    return (
        "你是一个工作流图的编辑助手。用户会用自然语言描述对工作流的修改，"
        "你需要返回修改后的【完整】工作流图（不是增量，是整个图）。\n\n"
        "工作流图结构（WorkflowDef）：\n"
        "- name: 工作流名称（通常不改）\n"
        "- description: 描述\n"
        "- nodes: 节点数组。每个节点：{id, kind, title, config, ports, position}\n"
        "  - kind: 'llm' | 'agent' | 'action'（没有 input/output 节点类型）\n"
        "  - config: 节点配置（llm: instruction/mode/allowed_tools/model_id 等；"
        "action: action_type/command 等；agent: tools 等）\n"
        "  - ports: [{name, type, direction('in'|'out')}]。每个节点通常有一个 in 端口和"
        "一个 out 端口，节点间通过端口连线\n"
        "  - position: {x, y} 画布坐标\n"
        "- edges: 连线数组。{id, source, source_port, target, target_port}，"
        "把某节点的 out 端口连到另一节点的 in 端口\n"
        "- input_params/output_port: 保留空即可\n"
        "- exposed/tool_name: 暴露相关，通常不改\n\n"
        "工作流输入/输出的确定方式（无需声明）：\n"
        "- 输入：任何【没有被连线喂入】的节点 in 端口，自动成为工作流入参，"
        "命名形如 nodeId.portName。\n"
        "- 输出：任何【没有连线引出】的节点 out 端口，自动成为工作流输出。\n\n"
        "规则：\n"
        "1. 返回完整图（包含未改动的节点），不要只给增量。\n"
        "2. 新节点要给唯一 id 和合理 position（避免重叠），并带 in/out 端口。\n"
        "3. 连线要引用真实存在的节点 id 和端口名（out → in）。\n"
        "4. reply 用一句话简述改动。\n\n"
        f"当前工作流图 JSON：\n{current_graph}"
    )


def _workflow_edit_thread_id(workflow_name: str) -> str:
    """Stable thread id for a workflow's NL-edit conversation."""
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in workflow_name)
    return f"wf_edit_{safe}"


async def _load_edit_messages(session_store: Any, thread_id: str) -> list[dict[str, Any]]:
    """Read the workflow's edit conversation from the session store."""
    if session_store is None:
        return []
    try:
        records = await session_store.list_messages(thread_id)
    except Exception:  # noqa: BLE001 — missing session is not fatal
        return []
    return [
        {"role": str(getattr(m, "role", "")), "content": str(getattr(m, "content", ""))}
        for m in records
        if getattr(m, "role", "") in ("user", "assistant")
    ]


async def _append_edit_message(session_store: Any, thread_id: str, role: str, content: str) -> None:
    """Persist one edit-conversation message, creating the session if needed."""
    if session_store is None:
        return
    import uuid

    from lamtools_core.session import MessageRecord, SessionRecord

    # Ensure the session exists (first message creates it).
    if getattr(session_store, "get", None) is not None:
        existing = await session_store.get(thread_id)
        if existing is None:
            try:
                await session_store.create(
                    SessionRecord(
                        id=thread_id,
                        member_id="workflow",
                        title=f"工作流编辑：{thread_id}",
                        status="active",
                        metadata={"kind": "workflow_edit"},
                    )
                )
            except Exception:  # noqa: BLE001 — may already exist concurrently
                pass
    message = MessageRecord(
        id=uuid.uuid4().hex,
        session_id=thread_id,
        role=role,
        content=content,
    )
    try:
        await session_store.add_message(message)
    except Exception:  # noqa: BLE001 — persistence must not break the op
        pass


__all__ = ["register_workflow_operations"]
