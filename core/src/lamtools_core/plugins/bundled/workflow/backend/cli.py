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


async def workflow_run(args: Any) -> int:
    payload: dict[str, Any] = {"name": args.name}
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
    "workflow_describe",
    "workflow_expose",
    "workflow_list",
    "workflow_new",
    "workflow_run",
    "workflow_unexpose",
]
