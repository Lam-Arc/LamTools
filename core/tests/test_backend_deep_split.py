"""Behavior and size acceptance for the backend responsibility split."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from lamtools_core import cli
from lamtools_core.app import live_operations as live
from lamtools_core.app.operation_catalog import OperationCatalog, OperationResult
from lamtools_core.plugins.bundled.workflow.backend import runtime as wf
from lamtools_core.plugins.bundled.workflow.backend.snapshots import WorkflowSnapshotStore
from lamtools_core.plugins.bundled.workflow.backend.durable import WorkflowRunEventStore

# user:“拆分后依旧很大”+(入口和新模块均须限制大小，同时保持命令、会话及工作流行为。)
ROOT = Path(__file__).resolve().parents[1] / "src" / "lamtools_core"


async def _context(tmp_path):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from lamtools_core.app.core_db import CoreDbBase, CoreAppEvent, CoreThreadSnapshot, CoreThreadSnapshotItem
    from lamtools_core.app import CoreAppSnapshotProjector
    from lamtools_core.app.event_store import SqlAlchemyAppEventStore
    from lamtools_core.app.snapshot_store import SqlAlchemyThreadSnapshotStore
    from lamtools_core.app.live_hub import CoreAppEventHub
    from lamtools_core.runtime import RuntimeTaskRegistry, InMemoryRuntimeStateStore

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'split.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(CoreDbBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, live.CoreLiveContext(session_factory=factory, operations=OperationCatalog(), hub=CoreAppEventHub(),
        runtime_task_registry=RuntimeTaskRegistry(), runtime_state_store=InMemoryRuntimeStateStore(),
        event_store=SqlAlchemyAppEventStore(CoreAppEvent), snapshot_store=SqlAlchemyThreadSnapshotStore(
            CoreThreadSnapshot, item_model=CoreThreadSnapshotItem, projector=CoreAppSnapshotProjector(member_defaults={"queue": []})))


def parser_contract(parser):
    def value(raw):
        if callable(raw):
            return raw.__name__
        if isinstance(raw, (tuple, list)):
            return [value(item) for item in raw]
        return raw

    actions = []
    for action in parser._actions:
        data = {key: value(getattr(action, key)) for key in (
            "option_strings", "dest", "nargs", "const", "default", "type", "required", "help", "metavar")}
        data["action"] = type(action).__name__
        if isinstance(action, argparse._SubParsersAction):
            data["commands"] = {name: parser_contract(child) for name, child in action.choices.items()}
        else:
            data["choices"] = value(action.choices)
        actions.append(data)
    return {"actions": actions, "defaults": {key: value(item) for key, item in parser._defaults.items()}}


def test_all_cli_flags_defaults_and_handlers_match_before_split(tmp_path, monkeypatch):
    for name in ("LAMTOOLS_CORE_API_URL", "LAMTOOLS_CORE_WS_PATH", "LAMTOOLS_CORE_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    parser = cli.build_parser(plugin_roots=[], plugin_state_path=tmp_path / "plugins.json")
    contract = json.dumps(parser_contract(parser), ensure_ascii=False, sort_keys=True)
    assert hashlib.sha256(contract.encode()).hexdigest() == "626449021d69beb2ddd9e083410e3c0fe607df6e23be8054f562f95ac7421def"


@pytest.mark.parametrize("relative", ["app/live_operations.py", "cli.py", "plugins/bundled/workflow/backend/runtime.py"])
def test_backend_entry_files_are_under_one_thousand_lines(relative):
    assert len((ROOT / relative).read_text(encoding="utf-8").splitlines()) <= 1_000


def test_extracted_modules_are_bounded_and_do_not_import_legacy_facades():
    import ast

    folders = [ROOT / "app" / "live", ROOT / "cli_commands"]
    files = [path for folder in folders for path in folder.rglob("*.py")]
    files += list((ROOT / "plugins/bundled/workflow/backend").glob("runner*.py"))
    assert len(files) >= 15
    for path in files:
        source = path.read_text(encoding="utf-8")
        assert len(source.splitlines()) <= 1_000, str(path)
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert node.end_lineno - node.lineno < 600, (str(path), node.name)
            if isinstance(node, ast.ImportFrom):
                assert node.module not in {"lamtools_core.cli", "lamtools_core.app.live_operations", "live_operations", "runtime"}, str(path)


def test_extracted_public_annotations_remain_resolvable():
    import importlib
    import typing

    files = [*ROOT.joinpath("app/live").glob("*.py"), *ROOT.joinpath("cli_commands").glob("*.py"),
             *ROOT.joinpath("plugins/bundled/workflow/backend").glob("runner*.py")]
    for path in files:
        if path.name == "__init__.py":
            continue
        module = importlib.import_module(".".join(path.relative_to(ROOT.parent).with_suffix("").parts))
        for obj in list(vars(module).values()):
            if (inspect.isfunction(obj) or inspect.isclass(obj)) and obj.__module__ == module.__name__:
                typing.get_type_hints(obj)
                if inspect.isclass(obj):
                    for method in vars(obj).values():
                        if isinstance(method, (classmethod, staticmethod)):
                            method = method.__func__
                        if inspect.isfunction(method):
                            typing.get_type_hints(method)


def test_split_resource_roots_still_resolve_to_repository():
    assert cli._repo_root() == ROOT.parents[2]
    assert live._bundled_config_resources_dir() == ROOT.parents[1] / "config" / "resources"


def test_legacy_configuration_entry_still_updates_the_shared_store(monkeypatch):
    module = inspect.getmodule(cli.configure_model_store_context)
    monkeypatch.setattr(module, "_default_model_store", None)
    monkeypatch.setattr(module, "_model_store_work_root", None)
    store = object()
    cli.configure_model_store_context(work_root="project", store=store)
    assert cli._get_model_store() is store
    assert module._model_store_work_root == "project"


@pytest.mark.asyncio
async def test_cli_live_connection_is_closed_on_operation_failure():
    module = inspect.getmodule(cli._invoke_live)
    from unittest.mock import patch

    client = SimpleNamespace(connect=AsyncMock(), close=AsyncMock())
    async def fail(_client):
        raise ValueError("operation failed")
    with patch.object(module, "CoreAppServerClient", return_value=client):
        with pytest.raises(ValueError, match="operation failed"):
            await cli._invoke_live(SimpleNamespace(base_url="url", ws_path="path", token="token"), fail)
    client.connect.assert_awaited_once()
    client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_live_host_still_dispatches_catalog_and_reports_busy(tmp_path):
    engine, context = await _context(tmp_path)
    try:
        async def custom(request):
            return OperationResult(name=request.name, payload={"echo": request.payload["value"]})
        context.operations.register("custom.echo", custom)
        result = await context.host.execute("custom.echo", request_id=1, params={"value": 42}, context=context)
        assert result.response["result"] == {"echo": 42}
        context.host.runtime_task_registry = SimpleNamespace(active_run_id=lambda thread: "active")
        result = await context.host.execute("turn.start", request_id=2, params={"thread_id": "thread"}, context=context)
        assert result.response["error"]["data"] == {"code": "SESSION_BUSY", "reason": "active_turn_exists", "active_run_id": "active"}
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_live_thread_queue_lifecycle_survives_split(tmp_path):
    engine, context = await _context(tmp_path)
    try:
        async def invoke(name, **params):
            result = await context.host.execute(name, request_id=1, params={"thread_id": "split", **params}, context=context)
            assert "error" not in result.response, result.response
            return result.response["result"]

        await invoke("thread.start", title="split")
        created = await invoke("queue.create", queue_item_id="q", client_message_id="client", input=[{"type": "text", "text": "first"}])
        repeated = await invoke("queue.create", queue_item_id="q", client_message_id="client", input=[{"type": "text", "text": "first"}])
        assert created["events"][0]["event_id"] == repeated["events"][0]["event_id"]
        await invoke("queue.update", queue_item_id="q", text="updated")
        read = await invoke("thread.read")
        assert "updated" in json.dumps(read, ensure_ascii=False)
        await invoke("queue.delete", queue_item_id="q")
        read = await invoke("thread.history", before_seq=999)
        assert read["snapshot_page"]["history_page"]["has_more"] is False
    finally:
        await live.wait_live_background_tasks()
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(("operation", "expected"), [("turn.pause", "paused"), ("turn.cancel", "cancelled")])
async def test_live_running_turn_controls_settle_both_saved_views(tmp_path, operation, expected):
    from lamtools_core.runtime import RuntimeState

    engine, context = await _context(tmp_path)
    started = asyncio.Event()
    task = None
    async def run(request):
        payload = request.payload
        await context.runtime_state_store.save(RuntimeState(session_id="thread", run_id=payload["turn_id"],
            status="running", metadata={"turn_id": payload["turn_id"]}))
        started.set()
        await asyncio.Future()

    context.operations.register("turn.start", run)
    try:
        outcome = await context.host.execute("turn.start", request_id=1, params={"thread_id": "thread",
            "input": [{"type": "text", "text": "wait"}]}, context=context)
        assert "error" not in outcome.response
        turn_id = outcome.runtime_start["turn_id"]
        task = context.runtime_task_registry.task("thread")
        await asyncio.wait_for(started.wait(), timeout=5)
        control = await context.host.execute(operation, request_id=2,
            params={"thread_id": "thread", "turn_id": turn_id}, context=context)
        assert "error" not in control.response
        await asyncio.gather(task, return_exceptions=True)
        await live.wait_live_background_tasks()
        async with context.session_factory() as db:
            snapshot = await context.persistence.load(db, "thread")
        assert snapshot["core"]["turns"][turn_id]["status"] == expected
        assert (await context.runtime_state_store.get("thread")).status == expected
        assert not context.runtime_task_registry.active_run_id("thread")
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await live.wait_live_background_tasks()
        await engine.dispose()


def content_node(identity, value):
    return wf.WorkflowNode(id=identity, kind="content", ports=[wf.WorkflowPort(name="out", direction="out", value=value)])


@pytest.mark.asyncio
async def test_workflow_scheduling_template_and_snapshot_roundtrip(tmp_path):
    graph = wf.WorkflowDef(id="wf", name="template", nodes=[content_node("source", "world"), wf.WorkflowNode(
        id="template", kind="template", config={"template": "Hello {{name}}"},
        ports=[wf.WorkflowPort(name="name", direction="in"), wf.WorkflowPort(name="out", direction="out")])],
        edges=[wf.WorkflowEdge(id="edge", source="source", source_port="out", target="template", target_port="name")], output_port="template.out")
    store = WorkflowSnapshotStore(root=tmp_path)
    runner = wf.WorkflowRunner(snapshot_store=store, event_store=WorkflowRunEventStore(root=tmp_path))
    result = await runner.run(graph, thread_id="thread", run_id="run")
    assert result.status == "completed"
    assert "world" in str(result.output)
    assert all(state.status == "done" for state in result.node_states.values())
    assert await store.get("thread", "run") is None
    assert wf.WorkflowRunResult.from_dict(result.to_dict()).to_dict() == result.to_dict()
    assert runner._active_runs == {}
    assert runner._run_locks == {}


@pytest.mark.asyncio
async def test_workflow_signal_resumes_persisted_wait_once(tmp_path):
    graph = wf.WorkflowDef(id="wait-wf", name="wait", nodes=[wf.WorkflowNode(id="wait", kind="wait_event",
        config={"event_type": "ready"}, ports=[wf.WorkflowPort(name="out", direction="out")])], output_port="wait.out")
    runner = wf.WorkflowRunner(snapshot_store=WorkflowSnapshotStore(root=tmp_path), event_store=WorkflowRunEventStore(root=tmp_path))
    paused = await runner.run(graph, thread_id="thread", run_id="wait-run")
    assert paused.status == "paused"
    token = paused.wait_descriptor["resume_token"]
    runner = wf.WorkflowRunner(snapshot_store=WorkflowSnapshotStore(root=tmp_path), event_store=WorkflowRunEventStore(root=tmp_path))
    with pytest.raises(ValueError, match="resume token"):
        await runner.signal(thread_id="thread", run_id="wait-run", resume_token="wrong", event_type="ready", payload={})
    args = dict(thread_id="thread", run_id="wait-run", resume_token=token, event_type="ready", payload={"value": 42})
    first, second = await asyncio.gather(runner.signal(**args), runner.signal(**args))
    assert first.status == second.status == "completed"
    assert first.output["payload"] == {"value": 42}
    assert runner._signal_locks == {}


@pytest.mark.asyncio
async def test_workflow_node_retry_and_cancellation_still_use_runner_hooks():
    graph = wf.WorkflowDef(name="retry", nodes=[wf.WorkflowNode(id="ai", kind="agent", config={"retries": 1,
        "retry_delay": 0, "instruction": "answer"}, ports=[wf.WorkflowPort(name="out", direction="out")])], output_port="ai.out")
    calls = 0
    class Agent:
        async def run(self, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise ValueError("retry")
            return SimpleNamespace(message="done")
    runner = wf.WorkflowRunner(sub_agent_runner=Agent())
    result = await runner.run(graph)
    assert result.status == "completed"
    assert calls == 2
    assert result.node_states["ai"].attempts == 2
    assert wf.WorkflowExecutionContext().enter_workflow("parent").child(session_id="s", run_id="r").workflow_stack == ("parent",)


@pytest.mark.asyncio
async def test_workflow_caller_cancellation_cleans_active_run_and_locks():
    started = asyncio.Event()
    class Agent:
        async def run(self, **kwargs):
            started.set()
            await asyncio.Future()

    runner = wf.WorkflowRunner(sub_agent_runner=Agent())
    graph = wf.WorkflowDef(name="cancel", nodes=[wf.WorkflowNode(id="agent", kind="agent", config={"instruction": "wait"},
        ports=[wf.WorkflowPort(name="out", direction="out")])])
    task = asyncio.create_task(runner.run(graph, thread_id="thread", run_id="cancel-run"))
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        task.cancel()
        result = await task
        assert result.status == "cancelled"
        assert result.node_states["agent"].status == "cancelled"
        assert runner._active_runs == {}
        assert runner._active_tasks == {}
        assert runner._run_locks == {}
        assert runner._run_lock_users == {}
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_workflow_nested_graph_keeps_context_and_static_helpers():
    child = wf.WorkflowDef(id="child", name="child", nodes=[content_node("value", 7)], output_port="value.out")
    store = SimpleNamespace(get=AsyncMock(return_value=child))
    parent = wf.WorkflowDef(id="parent", name="parent", nodes=[wf.WorkflowNode(id="nested", kind="subgraph",
        config={"workflow_name": "child"}, ports=[wf.WorkflowPort(name="out", direction="out")])], output_port="nested.out")
    runner = wf.WorkflowRunner(workflow_store=store)
    result = await runner.run(parent, execution_context=wf.WorkflowExecutionContext(trace_id="trace"))
    assert result.status == "completed", result.error
    assert result.output == 7
    store.get.assert_awaited_once()
    assert runner._active_runs == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["command", "script"])
async def test_workflow_execution_permission_is_checked_before_process_launch(kind):
    permission = SimpleNamespace(check=lambda name, payload: {"allowed": False, "reason": "denied by host"})
    runner = wf.WorkflowRunner(permission_service=permission)
    runner._run_command = AsyncMock()
    runner._run_script = AsyncMock()
    graph = wf.WorkflowDef(name="denied", nodes=[wf.WorkflowNode(id="process", kind=kind,
        config={"command": "echo test", "script": "out = 42"}, ports=[wf.WorkflowPort(name="out", direction="out")])])
    result = await runner.run(graph)
    assert result.status == "failed"
    assert "denied by host" in result.error
    runner._run_command.assert_not_awaited()
    runner._run_script.assert_not_awaited()


@pytest.mark.asyncio
async def test_workflow_script_service_keeps_real_process_data_flow(tmp_path):
    source = wf.WorkflowNode(id="source", kind="content", ports=[wf.WorkflowPort(name="x", direction="out", value=2)])
    script = wf.WorkflowNode(id="script", kind="script", config={"script": "y = x * 2"},
        ports=[wf.WorkflowPort(name="x", direction="in"), wf.WorkflowPort(name="y", direction="out")])
    graph = wf.WorkflowDef(name="script-flow", nodes=[source, script], edges=[wf.WorkflowEdge(id="edge", source="source",
        source_port="x", target="script", target_port="x")], output_port="script.y")
    result = await wf.WorkflowRunner().run(graph, work_root=str(tmp_path))
    assert result.status == "completed", result.error
    assert result.output == 4
