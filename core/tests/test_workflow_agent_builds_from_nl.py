"""Real-model retest: a user says ONE plain sentence; the model builds a
workflow; the driver then runs that workflow and reports honestly.

Purity: the driver only sends the natural-language sentence. The system itself
injects the system prompt + the workflow-mode tool set (active_mode="workflow"
wires the 5 build tools). The driver injects NO instructions, NO guidance.

Run (from core/):
    python tests/test_workflow_agent_builds_from_nl.py [--model auto] [--prompt "..."]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lamtools_core.cli import CoreCliRunOptions, run_core_cli_task
from lamtools_core.project.workflow_store import WorkflowStore
from lamtools_core.runtime.workflow import WorkflowManager, WorkflowRunner
from lamtools_core.app.operation_catalog import OperationCatalog
from lamtools_core.app.workflow_operations import register_workflow_operations

DEFAULT_PROMPT = "帮我建一个新闻聚合工作流：从多个来源抓取新闻，去重翻译，质检后按质量分流，最后生成日报"
THREAD_ID = "wf_build"  # session prefix; the model names the workflow itself


def _section(title: str) -> None:
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


async def main(model_id: str, prompt: str) -> int:
    tmp = tempfile.mkdtemp(prefix="wf_retest_")
    work_root = Path(tmp)
    store = WorkflowStore()

    _section("USER PROMPT (pure natural language only)")
    print(prompt)
    print(f"model: {model_id} | thread: {THREAD_ID} | work_root: {work_root}")

    # Only the message. System prompt + workflow tool set are injected by the
    # system itself (active_mode="workflow"); the driver adds nothing.
    opts = CoreCliRunOptions(
        message=prompt,
        model_id=model_id,
        work_root=work_root,
        run_dir=Path(tmp) / "run",
        thread_id=THREAD_ID,
        active_mode="workflow",
        workflow_store=store,
        approval_policy="auto_approve",
        thinking_enabled=True,
        temperature=0.2,
    )
    summary = await run_core_cli_task(opts)
    print("\n--- kernel summary ---")
    print(json.dumps({k: v for k, v in summary.items() if k != "proof"}, ensure_ascii=False, indent=2)[:2000])

    workflows = await store.list(work_root=str(work_root))
    _section("AGENT-BUILT GRAPH(S)")
    if not workflows:
        print("no workflow was created by the agent.")
        return 1
    wf = workflows[0]
    nodes, edges = wf.nodes, wf.edges
    print(f"workflow name: {wf.name!r}  nodes: {len(nodes)}  edges: {len(edges)}")
    for n in nodes:
        ports = [(p.direction, p.name, p.type) for p in n.ports]
        print(f"  [{n.kind}] id={n.id} title={n.title!r} ports={ports}")
        if n.config:
            print(f"        config={{ {', '.join(f'{k}={str(v)[:50]!r}' for k,v in n.config.items())} }}")
    for e in edges:
        print(f"  edge: {e.source}.{e.source_port} -> {e.target}.{e.target_port}"
              + (f"  cond={e.condition!r}" if e.condition else "")
              + (f"  transform={e.transform!r}" if e.transform else ""))

    valid_kinds = {"ai", "command", "script", "content", "subgraph"}
    bad_kinds = [n.id for n in nodes if n.kind not in valid_kinds]
    edge_refs_ok = all(any(x.id == e.source for x in nodes) and any(x.id == e.target for x in nodes) for e in edges)
    print(f"\nvalid kinds: {'OK' if not bad_kinds else f'BAD {bad_kinds}'} | edge refs: {'OK' if edge_refs_ok else 'BROKEN'}")

    _section("RUN the agent-built workflow")
    catalog = OperationCatalog()
    runner = WorkflowRunner(llm_client=None, sub_agent_runner=None, workflow_store=store)
    register_workflow_operations(catalog, workflow_manager=WorkflowManager(store),
                                 runner=runner, list_tool_specs=lambda: [])
    rr = await catalog.execute("workflow.run", {"name": wf.name, "work_root": str(work_root)}, metadata={})
    status = str(getattr(rr, "status", "error") or "error")
    payload = getattr(rr, "payload", {}) or {}
    run = payload.get("run") or {}
    print(f"run op status: {status}")
    print(f"run.status: {run.get('status')}")
    if run.get("error"):
        print(f"run.error: {run['error']}")
    for nid, ns in (run.get("node_states") or {}).items():
        print(f"  {nid}: {ns.get('status')} err={ns.get('error') or ''}")
    out = run.get("output")
    print(f"output: {repr(out)[:400]}")

    _section("VERDICT")
    can_run = status == "ok" and run.get("status") in ("completed", "paused")
    print(f"can run: {'yes' if can_run else 'no'}")
    print(f"nodes {len(nodes)} / edges {len(edges)} / kinds_valid={'yes' if not bad_kinds else 'no'} / edges_self_consistent={'yes' if edge_refs_ok else 'no'}")
    print(f"effective output: {'yes' if (can_run and out) else 'no'}")
    return 0 if can_run else 2


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="auto")
    ap.add_argument("--prompt", default=DEFAULT_PROMPT)
    a = ap.parse_args()
    raise SystemExit(asyncio.run(main(a.model, a.prompt)))
