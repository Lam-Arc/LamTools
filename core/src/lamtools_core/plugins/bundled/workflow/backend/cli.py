"""CLI commands contributed by the bundled Workflow plugin."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from lamtools_core.app.live_client import CoreAppServerClient


async def _invoke_live(args: Any, operation: Any) -> dict[str, Any]:
    base_url = str(getattr(args, "base_url", "") or os.environ.get("LAMTOOLS_CORE_API_URL", "http://127.0.0.1:5172"))
    ws_path = str(getattr(args, "ws_path", "") or os.environ.get("LAMTOOLS_CORE_WS_PATH", "/api/core/app-server"))
    token = str(getattr(args, "token", "") or os.environ.get("LAMTOOLS_CORE_TOKEN", ""))
    client = CoreAppServerClient(base_url, path=ws_path, token=token)
    try:
        await client.connect()
        result = await operation(client)
        return result if isinstance(result, dict) else {}
    finally:
        await client.close()


def _print_raw(args: Any, result: dict[str, Any]) -> bool:
    if not bool(getattr(args, "raw", False)):
        return False
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return True


async def workflow_new(args: Any) -> int:
    definition = json.loads(Path(args.from_file).read_text(encoding="utf-8"))
    if not isinstance(definition, dict):
        print("error: --from-file must contain a JSON object", file=sys.stderr)
        return 1
    if args.name:
        definition["name"] = args.name
    definition["work_root"] = args.work_root
    if args.exposed:
        definition["exposed"] = True

    async def operation(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("workflow.create", definition)

    result = await _invoke_live(args, operation)
    if _print_raw(args, result):
        return 0
    workflow = result.get("workflow", {})
    print(f"[workflow] created {workflow.get('name', '?')}")
    print(f"  nodes: {len(workflow.get('nodes') or [])}  edges: {len(workflow.get('edges') or [])}")
    if workflow.get("exposed"):
        print(f"  exposed as tool: {workflow.get('tool_name') or ''}")
    return 0


async def workflow_list(args: Any) -> int:
    params: dict[str, Any] = {}
    if args.work_root:
        params["work_root"] = args.work_root

    async def operation(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("workflow.list", params)

    result = await _invoke_live(args, operation)
    if _print_raw(args, result):
        return 0
    workflows = result.get("workflows", [])
    if isinstance(workflows, list):
        for workflow in workflows:
            if isinstance(workflow, dict):
                name = str(workflow.get("name") or "?")[:32]
                nodes = len(workflow.get("nodes") or [])
                exposed = "exposed" if workflow.get("exposed") else "-"
                print(f"{name:32s}  nodes={nodes:<3d} {exposed}")
    return 0


async def workflow_list_grouped(args: Any) -> int:
    raw_roots = getattr(args, "work_root", []) or []
    roots = list(raw_roots) if isinstance(raw_roots, (list, tuple)) else [raw_roots]
    payload = {"work_roots": [str(root) for root in roots if str(root)]}

    async def operation(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("workflow.list_grouped", payload)

    result = await _invoke_live(args, operation)
    if _print_raw(args, result):
        return 0 if not result.get("error") else 1
    if result.get("error"):
        print(f"error: {result['error']}", file=sys.stderr)
        return 1
    groups = result.get("groups") or {}
    if isinstance(groups, dict):
        for group, workflows in groups.items():
            print(f"[{group}]")
            if isinstance(workflows, list):
                for workflow in workflows:
                    if isinstance(workflow, dict):
                        print(f"  {workflow.get('name') or '?'}")
    return 0


def _read_workflow_json(path: str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("workflow JSON must contain an object")
    return value


def _workflow_result_code(args: Any, result: dict[str, Any], *, label: str = "workflow") -> int:
    if _print_raw(args, result):
        return 0 if not result.get("error") else 1
    if result.get("error"):
        print(f"error: {result['error']}", file=sys.stderr)
        return 1
    workflow = result.get("workflow") or {}
    if isinstance(workflow, dict):
        print(f"[{label}] {workflow.get('name') or '?'}")
    return 0


async def workflow_save(args: Any) -> int:
    try:
        payload = _read_workflow_json(args.from_file)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.name:
        payload["name"] = args.name
    if args.work_root:
        payload["work_root"] = args.work_root
    if args.expected_revision is not None:
        payload["expected_revision"] = args.expected_revision
    if args.exposed:
        payload["exposed"] = True

    async def operation(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("workflow.save", payload)

    return _workflow_result_code(args, await _invoke_live(args, operation), label="workflow saved")


async def workflow_update(args: Any) -> int:
    payload: dict[str, Any] = {"name": args.name}
    if args.work_root:
        payload["work_root"] = args.work_root
    if args.from_file:
        try:
            patch = _read_workflow_json(args.from_file)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        payload.update(patch)
        payload["name"] = args.name
    for key in ("description", "output_port", "tool_name"):
        value = getattr(args, key, None)
        if value is not None:
            payload[key] = value
    for key in ("nodes", "edges", "input_params"):
        value = getattr(args, key, None)
        if value is not None:
            payload[key] = value
    if args.exposed:
        payload["exposed"] = True
    elif args.unexposed:
        payload["exposed"] = False
    if args.expected_revision is not None:
        payload["expected_revision"] = args.expected_revision

    async def operation(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("workflow.update", payload)

    return _workflow_result_code(args, await _invoke_live(args, operation), label="workflow updated")


async def workflow_rename(args: Any) -> int:
    payload: dict[str, Any] = {"name": args.name, "new_name": args.new_name}
    if args.work_root:
        payload["work_root"] = args.work_root

    async def operation(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("workflow.rename", payload)

    return _workflow_result_code(args, await _invoke_live(args, operation), label="workflow renamed")


async def workflow_delete(args: Any) -> int:
    payload: dict[str, Any] = {"name": args.name}
    if args.work_root:
        payload["work_root"] = args.work_root

    async def operation(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("workflow.delete", payload)

    result = await _invoke_live(args, operation)
    if _print_raw(args, result):
        return 0 if result.get("deleted") and not result.get("error") else 1
    if result.get("error") or not result.get("deleted"):
        print(f"error: {result.get('error') or 'workflow was not deleted'}", file=sys.stderr)
        return 1
    print(f"[workflow] deleted {args.name}")
    return 0


async def workflow_describe(args: Any) -> int:
    params: dict[str, Any] = {"name": args.name}
    if args.work_root:
        params["work_root"] = args.work_root

    async def operation(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("workflow.get", params)

    result = await _invoke_live(args, operation)
    if _print_raw(args, result):
        return 0
    workflow = result.get("workflow", {})
    if isinstance(workflow, dict):
        print(f"  name: {workflow.get('name')}")
        print(f"  description: {workflow.get('description', '')}")
        print(f"  nodes: {len(workflow.get('nodes') or [])}")
        for node in workflow.get("nodes") or []:
            if isinstance(node, dict):
                print(f"    - [{node.get('kind')}] {node.get('id')} {node.get('title') or ''}")
        print(f"  edges: {len(workflow.get('edges') or [])}")
        print(f"  output_port: {workflow.get('output_port', '')}")
        print(f"  exposed: {workflow.get('exposed', False)}")
        if workflow.get("exposed"):
            print(f"  tool_name: {workflow.get('tool_name', '')}")
    return 0


async def workflow_document(args: Any) -> int:
    payload: dict[str, Any] = {"name": args.name}
    if args.work_root:
        payload["work_root"] = args.work_root
    async def operation(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("workflow.document.get", payload)
    result = await _invoke_live(args, operation)
    if result.get("error"):
        print(f"error: {result['error']}", file=sys.stderr)
        return 1
    print(json.dumps(result.get("document") or {}, ensure_ascii=False, indent=2))
    return 0


async def workflow_compile(args: Any) -> int:
    payload: dict[str, Any] = {"name": args.name}
    if args.work_root:
        payload["work_root"] = args.work_root
    async def operation(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("workflow.compile", payload)
    result = await _invoke_live(args, operation)
    if result.get("error"):
        print(f"error: {result['error']}", file=sys.stderr)
        return 1
    print(json.dumps(result.get("prompt") or {}, ensure_ascii=False, indent=2))
    return 0


async def workflow_semantic(args: Any) -> int:
    payload: dict[str, Any] = {"name": args.name, "offset": args.offset, "limit": args.limit}
    if args.work_root:
        payload["work_root"] = args.work_root
    if args.node_id:
        payload["node_ids"] = args.node_id
    async def operation(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("workflow.semantic", payload)
    result = await _invoke_live(args, operation)
    if result.get("error"):
        print(f"error: {result['error']}", file=sys.stderr)
        return 1
    print(json.dumps(result.get("semantic") or {}, ensure_ascii=False, indent=2))
    return 0


async def workflow_import_comfyui(args: Any) -> int:
    try:
        source = _read_workflow_json(args.from_file)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    payload: dict[str, Any] = {"name": args.name, "workflow": source}
    if args.work_root:
        payload["work_root"] = args.work_root
    if args.expected_revision is not None:
        payload["expected_revision"] = args.expected_revision
    async def operation(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("workflow.import.comfyui", payload)
    return _workflow_result_code(args, await _invoke_live(args, operation), label="ComfyUI imported")


async def workflow_export_comfyui(args: Any) -> int:
    payload: dict[str, Any] = {"name": args.name, "version": args.version}
    if args.work_root:
        payload["work_root"] = args.work_root
    async def operation(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("workflow.export.comfyui", payload)
    result = await _invoke_live(args, operation)
    if result.get("error"):
        print(f"error: {result['error']}", file=sys.stderr)
        return 1
    rendered = json.dumps(result.get("workflow") or {}, ensure_ascii=False, indent=2)
    if args.to_file:
        Path(args.to_file).write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


async def workflow_run(args: Any) -> int:
    payload: dict[str, Any] = {"name": args.name}
    if getattr(args, "model_id", ""):
        payload["model_id"] = args.model_id
    if getattr(args, "allow_commands", False):
        payload["permissions"] = {"run_command": True}
    if args.work_root:
        payload["work_root"] = args.work_root
    if args.max_steps is not None:
        payload["max_steps"] = args.max_steps
    if args.start_node:
        payload["start_node"] = args.start_node
    if args.single_node:
        payload["single_node"] = args.single_node
    inputs = _parse_workflow_inputs(args.input)
    if inputs:
        payload["inputs"] = inputs

    async def operation(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("workflow.run", payload)

    result = await _invoke_live(args, operation)
    if _print_raw(args, result):
        run = result.get("run") if isinstance(result.get("run"), dict) else {}
        return 0 if str(run.get("status") or "") in {"completed", "paused"} else 1
    run = result.get("run", {})
    status = str(run.get("status") or "?")
    print(f"[workflow] run status={status} run_id={run.get('run_id', '')}")
    states = run.get("node_states") or {}
    if isinstance(states, dict):
        for node_id, state in states.items():
            if isinstance(state, dict):
                suffix = f" error={state.get('error')}" if state.get("error") else ""
                print(f"  {node_id}: {state.get('status')} attempts={state.get('attempts')}{suffix}")
    if run.get("error"):
        print(f"  error: {run['error']}", file=sys.stderr)
    output = run.get("output")
    if output is not None:
        if isinstance(output, str) and len(output) > 500:
            print(f"  output: {output[:500]}…")
        else:
            print(f"  output: {json.dumps(output, ensure_ascii=False) if not isinstance(output, str) else output}")
    return 0 if status in {"completed", "paused"} else 1


async def workflow_cancel(args: Any) -> int:
    payload: dict[str, Any] = {"thread_id": args.thread_id}
    if args.run_id:
        payload["run_id"] = args.run_id

    async def operation(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("workflow.cancel", payload)

    result = await _invoke_live(args, operation)
    if _print_raw(args, result):
        return 0 if result.get("cancelled") else 1
    if result.get("cancelled"):
        print(f"[workflow] cancelled thread={args.thread_id} run_id={args.run_id or '*'}")
        return 0
    print(f"error: {result.get('error') or 'workflow run was not cancelled'}", file=sys.stderr)
    return 1


async def workflow_signal(args: Any) -> int:
    payload: dict[str, Any] = {
        "thread_id": args.thread_id,
        "run_id": args.run_id,
        "resume_token": args.resume_token,
        "event_type": args.event_type,
    }
    if args.decision:
        payload["decision"] = args.decision
    if isinstance(args.payload, dict):
        payload["payload"] = args.payload

    async def operation(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("workflow.signal", payload)

    result = await _invoke_live(args, operation)
    run = result.get("run") if isinstance(result.get("run"), dict) else {}
    status = str(run.get("status") or "")
    if _print_raw(args, result):
        return 0 if status in {"completed", "paused"} else 1
    if result.get("error"):
        print(f"error: {result['error']}", file=sys.stderr)
        return 1
    print(f"[workflow] signal status={status} run_id={args.run_id}")
    return 0 if status in {"completed", "paused"} else 1


def _human_task_payload(args: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for option, wire in (
        ("work_root", "work_root"),
        ("status", "status"),
        ("workflow_id", "workflow_id"),
        ("workflow_name", "workflow_name"),
        ("thread_id", "thread_id"),
    ):
        value = str(getattr(args, option, "") or "").strip()
        if value:
            payload[wire] = value
    limit = getattr(args, "limit", None)
    if limit is not None:
        payload["limit"] = limit
    if bool(getattr(args, "all_scopes", False)) or bool(getattr(args, "all", False)):
        payload["all"] = True
    return payload


async def workflow_human_task_list(args: Any) -> int:
    payload = _human_task_payload(args)

    async def operation(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("workflow.human_task.list", payload)

    result = await _invoke_live(args, operation)
    if _print_raw(args, result):
        return 0 if not result.get("error") else 1
    if result.get("error"):
        print(f"error: {result['error']}", file=sys.stderr)
        return 1
    tasks = result.get("tasks") or []
    if isinstance(tasks, list):
        for task in tasks:
            if not isinstance(task, dict):
                continue
            print(
                f"{str(task.get('task_id') or task.get('id') or '')[:44]:44s} "
                f"{str(task.get('status') or ''):10s} "
                f"{str(task.get('kind') or ''):10s} "
                f"{task.get('title') or task.get('node') or ''}"
            )
    return 0


async def workflow_human_task_get(args: Any) -> int:
    payload = _human_task_payload(args)
    payload["task_id"] = str(args.task_id)

    async def operation(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("workflow.human_task.get", payload)

    result = await _invoke_live(args, operation)
    if _print_raw(args, result):
        return 0 if not result.get("error") else 1
    if result.get("error"):
        print(f"error: {result['error']}", file=sys.stderr)
        return 1
    print(json.dumps(result.get("task") or {}, ensure_ascii=False, indent=2))
    return 0


async def workflow_human_task_complete(args: Any) -> int:
    payload = _human_task_payload(args)
    payload["task_id"] = str(args.task_id)
    decision = str(getattr(args, "decision", "") or "").strip()
    if decision:
        payload["decision"] = decision
    raw_payload = getattr(args, "payload", {})
    payload["payload"] = raw_payload if isinstance(raw_payload, dict) else {}

    async def operation(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("workflow.human_task.complete", payload)

    result = await _invoke_live(args, operation)
    if _print_raw(args, result):
        return 0 if not result.get("error") else 1
    if result.get("error"):
        print(f"error: {result['error']}", file=sys.stderr)
        return 1
    task = result.get("task") or {}
    print(f"[workflow] human task {task.get('task_id') or args.task_id} status={task.get('status', '?')}")
    return 0


def _queue_payload(args: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    work_root = str(getattr(args, "work_root", "") or "")
    if work_root:
        payload["work_root"] = work_root
    name = str(getattr(args, "name", "") or "")
    if name:
        payload["name"] = name
    queue_id = str(getattr(args, "queue_id", "") or "")
    if queue_id:
        payload["queue_id"] = queue_id
    run_id = str(getattr(args, "run_id", "") or "")
    if run_id:
        payload["run_id"] = run_id
    status = str(getattr(args, "status", "") or "")
    if status:
        payload["status"] = status
    limit = getattr(args, "limit", None)
    if limit is not None:
        payload["limit"] = limit
    return payload


async def workflow_queue_enqueue(args: Any) -> int:
    payload = _queue_payload(args)
    inputs = _parse_workflow_inputs(getattr(args, "input", []) or [])
    if inputs:
        payload["inputs"] = inputs
    for option in ("max_steps", "start_node", "single_node", "thread_id", "run_id"):
        value = getattr(args, option, None)
        if value not in (None, ""):
            payload[option] = value

    async def operation(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("workflow.queue.enqueue", payload)

    result = await _invoke_live(args, operation)
    if _print_raw(args, result):
        return 0 if not result.get("error") else 1
    item = result.get("queue") or result.get("item") or result.get("queue_item") or {}
    if result.get("error"):
        print(f"error: {result['error']}", file=sys.stderr)
        return 1
    print(f"[workflow] queued queue_id={item.get('queue_id', '')} run_id={item.get('run_id', '')}")
    return 0


async def workflow_queue_list(args: Any) -> int:
    payload = _queue_payload(args)
    payload["include_history"] = bool(getattr(args, "include_history", False))

    async def operation(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("workflow.queue.list", payload)

    result = await _invoke_live(args, operation)
    if _print_raw(args, result):
        return 0 if not result.get("error") else 1
    if result.get("error"):
        print(f"error: {result['error']}", file=sys.stderr)
        return 1
    _print_queue_items(result.get("queue") or result.get("items") or result.get("queue_items") or [])
    return 0


async def workflow_queue_history(args: Any) -> int:
    payload = _queue_payload(args)

    async def operation(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("workflow.queue.history", payload)

    result = await _invoke_live(args, operation)
    if _print_raw(args, result):
        return 0 if not result.get("error") else 1
    if result.get("error"):
        print(f"error: {result['error']}", file=sys.stderr)
        return 1
    _print_queue_items(result.get("history") or result.get("items") or result.get("queue_items") or [])
    return 0


async def workflow_queue_get(args: Any) -> int:
    payload = _queue_payload(args)

    async def operation(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("workflow.queue.get", payload)

    result = await _invoke_live(args, operation)
    if _print_raw(args, result):
        return 0 if not result.get("error") else 1
    if result.get("error"):
        print(f"error: {result['error']}", file=sys.stderr)
        return 1
    item = result.get("queue") or result.get("item") or result.get("queue_item") or {}
    print(json.dumps(item, ensure_ascii=False, indent=2))
    return 0


async def workflow_queue_clear(args: Any) -> int:
    payload = _queue_payload(args)
    payload["confirm"] = bool(getattr(args, "confirm", False))
    payload["all"] = bool(getattr(args, "all_items", False))

    async def operation(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("workflow.queue.clear", payload)

    result = await _invoke_live(args, operation)
    if _print_raw(args, result):
        return 0 if not result.get("error") else 1
    if result.get("error"):
        print(f"error: {result['error']}", file=sys.stderr)
        return 1
    print(f"[workflow] cleared {result.get('count', result.get('cleared', 0))} queue/history item(s)")
    return 0


async def workflow_queue_cancel(args: Any) -> int:
    payload = _queue_payload(args)

    async def operation(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("workflow.queue.cancel", payload)

    result = await _invoke_live(args, operation)
    if _print_raw(args, result):
        return 0 if result.get("cancelled") else 1
    if result.get("cancelled"):
        print(f"[workflow] cancelled queue item {payload.get('queue_id') or payload.get('run_id')}")
        return 0
    print(f"error: {result.get('error') or 'queue item was not cancelled'}", file=sys.stderr)
    return 1


async def workflow_node_types(args: Any) -> int:
    payload: dict[str, Any] = {}
    requested = str(getattr(args, "name", "") or "")
    if requested:
        payload["node_type"] = requested

    async def operation(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("workflow.node_types", payload)

    result = await _invoke_live(args, operation)
    if _print_raw(args, result):
        return 0 if not result.get("error") else 1
    if result.get("error"):
        print(f"error: {result['error']}", file=sys.stderr)
        return 1
    print(json.dumps(result.get("node_types") or result.get("object_info") or {}, ensure_ascii=False, indent=2))
    return 0


async def workflow_object_info(args: Any) -> int:
    payload: dict[str, Any] = {}
    requested = str(getattr(args, "name", "") or "")
    if requested:
        payload["name"] = requested

    async def operation(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("workflow.object_info", payload)

    result = await _invoke_live(args, operation)
    if _print_raw(args, result):
        return 0 if not result.get("error") else 1
    if result.get("error"):
        print(f"error: {result['error']}", file=sys.stderr)
        return 1
    print(json.dumps(result.get("object_info") or result.get("node_types") or {}, ensure_ascii=False, indent=2))
    return 0


async def workflow_tools_list(args: Any) -> int:
    async def operation(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("workflow.tools.list", {})

    result = await _invoke_live(args, operation)
    if _print_raw(args, result):
        return 0 if not result.get("error") else 1
    if result.get("error"):
        print(f"error: {result['error']}", file=sys.stderr)
        return 1
    tools = result.get("tools") or []
    if isinstance(tools, list):
        for item in tools:
            if isinstance(item, dict):
                print(f"{item.get('name') or '?'}\t{item.get('description') or ''}")
    return 0


def _print_queue_items(items: Any) -> None:
    if not isinstance(items, list):
        return
    for item in items:
        if isinstance(item, dict):
            print(
                f"{str(item.get('queue_id') or item.get('id') or '')[:28]:28s} "
                f"{str(item.get('status') or ''):10s} "
                f"{str(item.get('workflow_name') or item.get('name') or '')}"
            )


async def workflow_expose(args: Any) -> int:
    payload: dict[str, Any] = {"name": args.name}
    if args.work_root:
        payload["work_root"] = args.work_root

    async def operation(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("workflow.expose", payload)

    result = await _invoke_live(args, operation)
    if _print_raw(args, result):
        return 0
    workflow = result.get("workflow", {})
    print(f"[workflow] {workflow.get('name', args.name)} exposed as tool: {workflow.get('tool_name', '')}")
    return 0


async def workflow_unexpose(args: Any) -> int:
    payload: dict[str, Any] = {"name": args.name}
    if args.work_root:
        payload["work_root"] = args.work_root

    async def operation(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("workflow.unexpose", payload)

    result = await _invoke_live(args, operation)
    if _print_raw(args, result):
        return 0
    workflow = result.get("workflow", {})
    print(f"[workflow] {workflow.get('name', args.name)} unexposed")
    return 0


def _activation_payload(args: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": str(getattr(args, "name", "") or "")}
    work_root = str(getattr(args, "work_root", "") or "")
    trigger_id = str(getattr(args, "trigger_id", "") or "")
    if work_root:
        payload["work_root"] = work_root
    if trigger_id:
        payload["trigger_id"] = trigger_id
    if bool(getattr(args, "replace", False)):
        payload["replace"] = True
    return payload


async def workflow_activate(args: Any) -> int:
    payload = _activation_payload(args)

    async def operation(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("workflow.activate", payload)

    result = await _invoke_live(args, operation)
    if _print_raw(args, result):
        return 0 if not result.get("error") else 1
    if result.get("error"):
        print(f"error: {result['error']}", file=sys.stderr)
        return 1
    print(
        f"[workflow] activated={len(result.get('activated') or [])} "
        f"reused={len(result.get('reused') or [])}"
    )
    return 0


async def workflow_deactivate(args: Any) -> int:
    payload = _activation_payload(args)

    async def operation(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("workflow.deactivate", payload)

    result = await _invoke_live(args, operation)
    if _print_raw(args, result):
        return 0 if not result.get("error") else 1
    if result.get("error"):
        print(f"error: {result['error']}", file=sys.stderr)
        return 1
    print(f"[workflow] deactivated={len(result.get('cancelled') or [])}")
    return 0


async def workflow_activation_list(args: Any) -> int:
    payload = _activation_payload(args)

    async def operation(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("workflow.activation.list", payload)

    result = await _invoke_live(args, operation)
    if _print_raw(args, result):
        return 0 if not result.get("error") else 1
    if result.get("error"):
        print(f"error: {result['error']}", file=sys.stderr)
        return 1
    for item in result.get("activations") or []:
        if isinstance(item, dict):
            print(
                f"{str(item.get('trigger_id') or ''):24s} "
                f"{str(item.get('status') or ''):10s} "
                f"revision={int(item.get('workflow_revision') or 0)}"
            )
    return 0


def _parse_workflow_inputs(items: list[str]) -> dict[str, Any]:
    inputs: dict[str, Any] = {}
    for item in items or []:
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            continue
        parsed: Any = value
        stripped = value.strip()
        if stripped and (
            (stripped[0] == "{" and stripped[-1:] == "}")
            or (stripped[0] == "[" and stripped[-1:] == "]")
        ):
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                parsed = value
        elif stripped.lower() in {"true", "false"}:
            parsed = stripped.lower() == "true"
        else:
            try:
                parsed = int(stripped)
            except (TypeError, ValueError):
                pass
        inputs[key] = parsed
    return inputs


__all__ = [
    "workflow_activate",
    "workflow_activation_list",
    "workflow_describe",
    "workflow_document",
    "workflow_compile",
    "workflow_semantic",
    "workflow_import_comfyui",
    "workflow_export_comfyui",
    "workflow_cancel",
    "workflow_node_types",
    "workflow_object_info",
    "workflow_tools_list",
    "workflow_expose",
    "workflow_list",
    "workflow_list_grouped",
    "workflow_new",
    "workflow_save",
    "workflow_update",
    "workflow_rename",
    "workflow_delete",
    "workflow_deactivate",
    "workflow_queue_cancel",
    "workflow_queue_clear",
    "workflow_queue_enqueue",
    "workflow_queue_get",
    "workflow_queue_history",
    "workflow_queue_list",
    "workflow_run",
    "workflow_signal",
    "workflow_human_task_list",
    "workflow_human_task_get",
    "workflow_human_task_complete",
    "workflow_unexpose",
]
