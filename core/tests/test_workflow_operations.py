"""Safety-net coverage for the Workflow operation surface."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import uuid

import pytest

from lamtools_core.app.base_agent import build_core_plugin_operation_catalog
from lamtools_core.app.operation_catalog import OperationRequest, OperationResult
from lamtools_core.plugins.bundled.workflow.backend.operations import workflow_tools_list
from lamtools_core.plugins.bundled.workflow.backend.runtime import (
    WorkflowDef,
    WorkflowEdge,
    WorkflowInputParam,
    WorkflowNode,
    WorkflowPort,
    WorkflowRunner,
)
from lamtools_core.plugins.bundled.workflow.backend.build_tools import workflow_build_tool_handlers
from lamtools_core.plugins.bundled.workflow.backend.tools import workflow_tool_specs
from lamtools_core.plugins.bundled.workflow.backend.store import WorkflowStore
from lamtools_core.plugins.context import PluginContext
from lamtools_core.plugins.registry import bundled_plugins_dir
from lamtools_core.tool import ToolCall, ToolSpec
from lamtools_core.tool.default_toolbox import build_core_toolbox
from lamtools_core.runtime import RuntimeTaskRegistry


def _definition(name: str = "demo") -> WorkflowDef:
    return WorkflowDef(
        name=name,
        nodes=[
            WorkflowNode(
                id="content",
                kind="content",
                ports=[WorkflowPort(name="out", type="string", direction="out", value="ok")],
            )
        ],
    )


@pytest.mark.asyncio
async def test_workflow_tool_catalog_comes_from_agent_execution_toolbox(tmp_path: Path) -> None:
    class AgentRunner:
        def available_tool_specs(self, *, mode: str = "") -> list[ToolSpec]:
            assert mode == "agent"
            return [
                ToolSpec(
                    name="read_file",
                    description="Read a file",
                    input_schema={"type": "object", "properties": {}},
                ),
                ToolSpec(
                    name="web_search",
                    description="Search the web",
                    input_schema={"type": "object", "properties": {}},
                ),
            ]

    context = PluginContext(
        work_root=tmp_path,
        services={"sub_agent_runner": AgentRunner()},
    )

    result = await workflow_tools_list(
        OperationRequest(name="workflow.tools.list", payload={}),
        context=context,
    )

    assert result.status == "ok"
    assert [tool["name"] for tool in result.payload["tools"]] == ["read_file", "web_search"]


def _input_workflow() -> WorkflowDef:
    return WorkflowDef(
        name="inputs",
        nodes=[
            WorkflowNode(
                id="input",
                kind="script",
                ports=[
                    WorkflowPort(name="value", type="integer", direction="in"),
                    WorkflowPort(name="required", type="integer", direction="in"),
                    WorkflowPort(name="optional", type="string", direction="in"),
                    WorkflowPort(name="out", type="integer", direction="out"),
                ],
                config={"script": "out = value + required"},
            )
        ],
        input_params=[
            WorkflowInputParam(
                name="input.value",
                type="integer",
                description="Optional value",
                required=False,
                default=7,
            ),
            WorkflowInputParam(
                name="input.required",
                type="integer",
                description="Required value",
                required=True,
            ),
            WorkflowInputParam(
                name="input.optional",
                type="string",
                required=False,
            ),
        ],
    )


def _catalog(tmp_path: Path, store: WorkflowStore):
    data_dir = tmp_path / "data"
    context = PluginContext(
        work_root=tmp_path,
        data_dir=data_dir,
        services={"workflow_store": store},
    )
    return build_core_plugin_operation_catalog(
        data_dir=data_dir,
        work_root=tmp_path,
        plugin_roots=[bundled_plugins_dir()],
        context=context,
    )


class _MemorySessionStore:
    def __init__(self) -> None:
        self.records = {}

    async def create(self, record):
        if record.id in self.records:
            raise ValueError(record.id)
        self.records[record.id] = record
        return record

    async def get(self, session_id):
        return self.records.get(session_id)

    async def patch(self, session_id, *, title=None, metadata=None):
        record = self.records.get(session_id)
        if record is None:
            return None
        if title is not None:
            record.title = title
        if metadata is not None:
            record.metadata = dict(metadata)
        return record


def test_workflow_tool_schema_preserves_input_required_and_default_contract() -> None:
    spec = workflow_tool_specs([_input_workflow()])[0]
    schema = spec.input_schema

    assert schema["required"] == ["input.required"]
    assert schema["properties"]["input.value"]["default"] == 7
    assert schema["properties"]["input.value"]["type"] == "integer"
    assert "input.optional" not in schema["required"]
    assert "default" not in schema["properties"]["input.optional"]


@pytest.mark.asyncio
async def test_workflow_runner_applies_defaults_and_validates_missing_required_input(
    tmp_path: Path,
) -> None:
    workflow = _input_workflow()
    missing = await WorkflowRunner().run(workflow, work_root=str(tmp_path), run_id="missing")
    assert missing.status == "failed"
    assert "input.required" in missing.error

    completed = await WorkflowRunner().run(
        workflow,
        inputs={"input.required": 5},
        work_root=str(tmp_path),
        run_id="with-default",
    )
    assert completed.status == "completed"
    assert completed.output == 12


@pytest.mark.asyncio
async def test_workflow_operations_cover_create_list_get_update_expose_run_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LAMTOOLS_HOME", str(tmp_path / "home"))
    store = WorkflowStore()
    catalog = _catalog(tmp_path, store)

    created = await catalog.execute("workflow.create", _definition().to_dict())
    assert created.status == "ok"
    assert created.payload["workflow"]["name"] == "demo"

    listed = await catalog.execute("workflow.list")
    assert [item["name"] for item in listed.payload["workflows"]] == ["demo"]

    fetched = await catalog.execute("workflow.get", {"name": "demo"})
    assert fetched.payload["workflow"]["name"] == "demo"

    updated = await catalog.execute("workflow.update", {"name": "demo", "description": "updated"})
    assert updated.payload["workflow"]["description"] == "updated"

    exposed = await catalog.execute("workflow.expose", {"name": "demo"})
    assert exposed.payload["workflow"]["exposed"] is True

    run = await catalog.execute("workflow.run", {"name": "demo", "run_id": "operation-run"})
    assert run.status == "ok"
    assert run.payload["run"]["status"] == "completed"
    assert run.payload["run"]["output"] == "ok"

    hidden = await catalog.execute("workflow.unexpose", {"name": "demo"})
    assert hidden.payload["workflow"]["exposed"] is False

    deleted = await catalog.execute("workflow.delete", {"name": "demo"})
    assert deleted.payload["deleted"] is True
    assert (await catalog.execute("workflow.list")).payload["workflows"] == []


@pytest.mark.asyncio
async def test_workflow_activation_reuses_arrange_and_pins_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LAMTOOLS_HOME", str(tmp_path / "home"))
    store = WorkflowStore()
    catalog = _catalog(tmp_path, store)
    jobs: list[dict[str, Any]] = []

    async def arrange_list(request):
        return OperationResult(name=request.name, payload={"jobs": list(jobs)})

    async def arrange_create(request):
        job = {
            **request.payload,
            "id": f"arrange_{len(jobs) + 1}",
            "status": "waiting" if request.payload["trigger"]["type"] == "event" else "scheduled",
            "next_run_at": None,
            "run_count": 0,
            "last_error": "",
            "revision": 1,
        }
        jobs.append(job)
        return OperationResult(name=request.name, payload={"job": job})

    async def arrange_cancel(request):
        job = next(item for item in jobs if item["id"] == request.payload["job_id"])
        job["status"] = "cancelled"
        job["revision"] += 1
        return OperationResult(name=request.name, payload={"job": job})

    async def arrange_resume(request):
        job = next(item for item in jobs if item["id"] == request.payload["job_id"])
        job["status"] = "waiting"
        job["revision"] += 1
        return OperationResult(name=request.name, payload={"job": job})

    catalog.register("arrange.list", arrange_list)
    catalog.register("arrange.create", arrange_create)
    catalog.register("arrange.cancel", arrange_cancel)
    catalog.register("arrange.resume", arrange_resume)

    definition = _definition("activated")
    definition.work_root = str(tmp_path)
    created = await catalog.execute("workflow.create", definition.to_dict())
    fetched = await catalog.execute(
        "workflow.get", {"name": "activated", "work_root": str(tmp_path)}
    )
    document = fetched.payload["document"]
    document["triggers"] = [
        {"id": "build", "type": "event", "event_type": "build.completed"}
    ]
    saved = await catalog.execute(
        "workflow.document.save",
        {
            "document": document,
            "work_root": str(tmp_path),
            "expected_revision": created.payload["workflow"]["revision"],
        },
    )
    current_revision = saved.payload["workflow"]["revision"]

    activated = await catalog.execute(
        "workflow.activate", {"name": "activated", "work_root": str(tmp_path)}
    )
    assert activated.status == "ok"
    assert activated.payload["activated"][0]["workflow_revision"] == current_revision
    assert jobs[0]["operation"] == "workflow.run"
    assert jobs[0]["payload"]["workflow_revision"] == current_revision

    reused = await catalog.execute(
        "workflow.activate", {"name": "activated", "work_root": str(tmp_path)}
    )
    assert reused.payload["activated"] == []
    assert reused.payload["reused"][0]["trigger_id"] == "build"

    listed = await catalog.execute(
        "workflow.activation.list", {"name": "activated", "work_root": str(tmp_path)}
    )
    assert [item["trigger_id"] for item in listed.payload["activations"]] == ["build"]

    deactivated = await catalog.execute(
        "workflow.deactivate", {"name": "activated", "work_root": str(tmp_path)}
    )
    assert deactivated.payload["cancelled"] == ["arrange_1"]


@pytest.mark.asyncio
async def test_workflow_run_rpc_resumes_durable_snapshot_without_prior_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RPC omission must let Runner hydrate values/state from its snapshot."""
    monkeypatch.setenv("LAMTOOLS_HOME", str(tmp_path / "home"))
    store = WorkflowStore()
    catalog = _catalog(tmp_path, store)
    definition = WorkflowDef(
        name="inputs",
        nodes=[
            WorkflowNode(
                id="seed",
                kind="script",
                ports=[
                    WorkflowPort(name="value", type="integer", direction="in"),
                    WorkflowPort(name="out", type="integer", direction="out"),
                ],
                config={"script": "out = value"},
            ),
            WorkflowNode(
                id="sum",
                kind="script",
                ports=[
                    WorkflowPort(name="seed", type="integer", direction="in"),
                    WorkflowPort(name="required", type="integer", direction="in"),
                    WorkflowPort(name="out", type="integer", direction="out"),
                ],
                config={"script": "out = seed + required"},
            ),
        ],
        edges=[
            WorkflowEdge(
                id="seed-to-sum",
                source="seed",
                source_port="out",
                target="sum",
                target_port="seed",
            )
        ],
        input_params=[
            WorkflowInputParam(name="seed.value", type="integer", required=False, default=7),
            WorkflowInputParam(name="sum.required", type="integer", required=True),
        ],
    )
    definition.work_root = str(tmp_path)
    created = await catalog.execute("workflow.create", definition.to_dict())
    assert created.status == "ok"

    first = await catalog.execute(
        "workflow.run",
        {
            "name": "inputs",
            "work_root": str(tmp_path),
            "inputs": {"sum.required": 5},
            "thread_id": "workflow:inputs-resume",
            "run_id": "resume-rpc",
            "max_steps": 1,
        },
        metadata={"permissions": {"run_command": True}},
    )
    assert first.payload["run"]["status"] == "paused"
    # Deliberately omit both prior_values and prior_node_states.  The required
    # input and the value table must come from the durable paused snapshot.
    second = await catalog.execute(
        "workflow.run",
        {
            "name": "inputs",
            "work_root": str(tmp_path),
            "thread_id": "workflow:inputs-resume",
            "run_id": "resume-rpc",
        },
        metadata={"permissions": {"run_command": True}},
    )
    assert second.payload["run"]["status"] == "completed"
    assert second.payload["run"]["output"] == 12
    assert second.payload["run"]["node_states"]["seed"]["status"] == "done"


@pytest.mark.asyncio
async def test_workflow_operation_grouped_list_keeps_project_scope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LAMTOOLS_HOME", str(tmp_path / "home"))
    project = tmp_path / "project"
    store = WorkflowStore()
    await store.save(_definition("global"))
    await store.save(WorkflowDef(**{**_definition("project").__dict__, "work_root": str(project)}))

    catalog = _catalog(tmp_path, store)

    result = await catalog.execute("workflow.list_grouped", {"work_roots": [str(project)]})
    assert [item["name"] for item in result.payload["groups"]["global"]] == ["global"]
    assert [item["name"] for item in result.payload["groups"][str(project)]] == ["project"]


@pytest.mark.asyncio
async def test_workflow_grouped_list_creates_sessions_for_discovered_resources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LAMTOOLS_HOME", str(tmp_path / "home"))
    project = tmp_path / "project"
    session_store = _MemorySessionStore()
    store = WorkflowStore()
    global_workflow = _definition("global")
    project_workflow = WorkflowDef(
        **{**_definition("project").__dict__, "work_root": str(project)}
    )
    await store.save(global_workflow)
    await store.save(project_workflow)
    context = PluginContext(
        work_root=project,
        data_dir=tmp_path / "data",
        services={"workflow_store": store, "session_store": session_store},
    )
    catalog = build_core_plugin_operation_catalog(
        data_dir=tmp_path / "data",
        work_root=project,
        plugin_roots=[bundled_plugins_dir()],
        context=context,
    )

    result = await catalog.execute(
        "workflow.list_grouped", {"work_roots": [str(project)]}
    )

    assert result.status == "ok"
    assert {f"workflow:{global_workflow.id}", f"workflow:{project_workflow.id}"} == set(
        session_store.records
    )
    for record in session_store.records.values():
        assert record.metadata["owner_plugin"] == "workflow"
        assert record.metadata["resource_type"] == "workflow"


@pytest.mark.asyncio
async def test_workflow_run_releases_session_claim_after_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A completed run must not block a later run on the same workflow Session."""
    monkeypatch.setenv("LAMTOOLS_HOME", str(tmp_path / "home"))
    registry = RuntimeTaskRegistry()
    store = WorkflowStore()
    context = PluginContext(
        work_root=tmp_path,
        data_dir=tmp_path / "data",
        runtime_task_registry=registry,
        services={"workflow_store": store},
    )
    catalog = build_core_plugin_operation_catalog(
        data_dir=tmp_path / "data",
        work_root=tmp_path,
        plugin_roots=[bundled_plugins_dir()],
        context=context,
    )
    created = await catalog.execute("workflow.create", _definition("repeatable").to_dict())
    assert created.status == "ok"
    thread_id = created.payload["session_id"]

    first = await catalog.execute(
        "workflow.run",
        {"name": "repeatable", "thread_id": thread_id, "run_id": "first"},
    )
    second = await catalog.execute(
        "workflow.run",
        {"name": "repeatable", "thread_id": thread_id, "run_id": "second"},
    )

    assert first.payload["run"]["status"] == "completed"
    assert second.payload["run"]["status"] == "completed"
    assert registry.active_run_id(thread_id) is None
    await registry.shutdown()


@pytest.mark.asyncio
async def test_workflow_project_switch_uses_current_root_for_operations_and_dynamic_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LAMTOOLS_HOME", str(tmp_path / "home"))
    project_a = tmp_path / "project-a"
    project_b = tmp_path / "project-b"
    store = WorkflowStore()
    await store.save(
        WorkflowDef(
            **{
                **_definition("shared").__dict__,
                "description": "project A",
                "work_root": str(project_a),
                "exposed": True,
            }
        )
    )
    await store.save(
        WorkflowDef(
            **{
                **_definition("shared").__dict__,
                "description": "project B",
                "work_root": str(project_b),
                "exposed": True,
            }
        )
    )
    context = PluginContext(
        work_root=project_a,
        data_dir=tmp_path / "data",
        services={"workflow_store": store},
    )
    catalog = build_core_plugin_operation_catalog(
        data_dir=tmp_path / "data",
        work_root=project_a,
        plugin_roots=[bundled_plugins_dir()],
        context=context,
    )

    listed_a = await catalog.execute("workflow.list", {"work_root": str(project_a)})
    listed_b = await catalog.execute("workflow.list", {"work_root": str(project_b)})
    assert [(item["name"], item["description"]) for item in listed_a.payload["workflows"]] == [
        ("shared", "project A")
    ]
    assert [(item["name"], item["description"]) for item in listed_b.payload["workflows"]] == [
        ("shared", "project B")
    ]

    runtime = context.service("plugin.runtime_manager").get("workflow").value
    tools_a = runtime.workflow_tool_provider(str(project_a)).specs
    tools_b = runtime.workflow_tool_provider(str(project_b)).specs
    assert [(spec.metadata["workflow_name"], spec.description) for spec in tools_a] == [
        ("shared", "project A")
    ]
    assert [(spec.metadata["workflow_name"], spec.description) for spec in tools_b] == [
        ("shared", "project B")
    ]


@pytest.mark.asyncio
async def test_workflow_disabled_at_start_can_reenable_and_restart_watcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LAMTOOLS_HOME", str(tmp_path / "home"))
    from lamtools_core.plugins.registry import PluginStateStore

    data_dir = tmp_path / "data"
    state = PluginStateStore(data_dir / "plugins.jsonc")
    state.set_enabled("workflow", False)
    store = WorkflowStore()
    await store.save(_definition("survives-disable"))

    class _EventBus:
        async def broadcast(self, event: dict[str, Any]) -> None:
            del event

    context = PluginContext(
        work_root=tmp_path,
        data_dir=data_dir,
        event_bus=_EventBus(),
        services={"workflow_store": store},
    )
    catalog = build_core_plugin_operation_catalog(
        data_dir=data_dir,
        work_root=tmp_path,
        plugin_roots=[bundled_plugins_dir()],
        context=context,
    )
    manager = context.service("plugin.runtime_manager")

    assert manager.get("workflow") is None
    assert not catalog.has("workflow.run")
    assert (await catalog.execute("plugin.ui.list")).payload["modes"] == []

    enabled = await catalog.execute("plugin.enable", {"name": "workflow"})
    assert enabled.payload["enabled"] is True
    handle = manager.get("workflow")
    assert handle is not None
    assert handle.value.watcher is not None
    assert catalog.has("workflow.run")
    listed = await catalog.execute("workflow.list")
    assert [item["name"] for item in listed.payload["workflows"]] == ["survives-disable"]

    disabled = await catalog.execute("plugin.disable", {"name": "workflow"})
    assert disabled.payload["enabled"] is False
    assert handle.value.watcher is None
    assert not catalog.has("workflow.run")
    # Disable/re-enable only affects capabilities; it never deletes workflow data.
    assert (await store.get("survives-disable")) is not None

    reenabled = await catalog.execute("plugin.enable", {"name": "workflow"})
    assert reenabled.payload["enabled"] is True
    restored = await catalog.execute("workflow.list")
    assert [item["name"] for item in restored.payload["workflows"]] == ["survives-disable"]
    assert manager.get("workflow") is not None
    assert manager.get("workflow").value.watcher is not None


@pytest.mark.asyncio
async def test_workflow_disable_removes_old_toolbox_capabilities_and_reenable_restores_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A live toolbox must observe plugin disable/enable without a restart."""
    monkeypatch.setenv("LAMTOOLS_HOME", str(tmp_path / "home"))
    store = WorkflowStore()
    context = PluginContext(
        work_root=tmp_path,
        data_dir=tmp_path / "data",
        services={"workflow_store": store},
    )
    catalog = build_core_plugin_operation_catalog(
        data_dir=tmp_path / "data",
        work_root=tmp_path,
        plugin_roots=[bundled_plugins_dir()],
        context=context,
    )
    manager = context.service("plugin.runtime_manager")
    handle = manager.get("workflow")
    assert handle is not None
    runtime = handle.value

    created = await catalog.execute(
        "workflow.create",
        {**_definition("exposed").to_dict(), "exposed": True},
    )
    assert created.status == "ok"
    old_provider = runtime.workflow_tool_provider
    old_specs = list(runtime.tool_specs)
    for spec in old_specs:
        spec.metadata["plugin"] = "workflow"
    old_handlers = runtime.tool_handlers
    toolbox = build_core_toolbox(
        work_root=tmp_path,
        plugin_tool_specs=old_specs,
        plugin_tool_handlers=old_handlers,
        plugin_tool_providers=[old_provider],
        plugin_availability=manager.is_enabled,
    )
    assert "workflow_graph" in {spec.name for spec in toolbox.tool_specs()}
    assert "workflow_exposed" in {spec.name for spec in toolbox.tool_specs()}

    ui_before = await catalog.execute("plugin.ui.list")
    assert any(item["pluginId"] == "workflow" for item in ui_before.payload["modes"])

    disabled = await catalog.execute("plugin.disable", {"name": "workflow"})
    assert disabled.payload["enabled"] is False
    assert not catalog.has("workflow.run")
    with pytest.raises(KeyError):
        await catalog.execute("workflow.run", {"name": "exposed"})
    assert runtime.workflow_tool_provider(str(tmp_path)).specs == []
    assert "workflow_graph" not in {spec.name for spec in toolbox.tool_specs()}
    blocked = await toolbox.execute(ToolCall(id="disabled", name="workflow_graph", arguments={}))
    assert blocked.status == "blocked"
    ui_after_disable = await catalog.execute("plugin.ui.list")
    assert not any(item["pluginId"] == "workflow" for item in ui_after_disable.payload["modes"])

    enabled = await catalog.execute("plugin.enable", {"name": "workflow"})
    assert enabled.payload["enabled"] is True
    assert catalog.has("workflow.run")
    assert manager.get("workflow").value is runtime
    assert "workflow_graph" in {spec.name for spec in toolbox.tool_specs()}
    assert "workflow_exposed" in {spec.name for spec in old_provider(str(tmp_path)).specs}
    ui_after_enable = await catalog.execute("plugin.ui.list")
    assert any(item["pluginId"] == "workflow" for item in ui_after_enable.payload["modes"])


@pytest.mark.asyncio
async def test_workflow_project_a_and_b_are_isolated_even_with_same_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LAMTOOLS_HOME", str(tmp_path / "home"))
    project_a = tmp_path / "project-a"
    project_b = tmp_path / "project-b"
    store = WorkflowStore()
    await store.save(WorkflowDef(**{**_definition("shared").__dict__, "description": "A", "work_root": str(project_a)}))
    await store.save(WorkflowDef(**{**_definition("shared").__dict__, "description": "B", "work_root": str(project_b)}))

    assert (await store.get("shared", work_root=str(project_a))).description == "A"
    assert (await store.get("shared", work_root=str(project_b))).description == "B"
    grouped = await store.list_grouped(work_roots=[str(project_a), str(project_b)])
    assert [item.description for item in grouped[str(project_a)]] == ["A"]
    assert [item.description for item in grouped[str(project_b)]] == ["B"]

    assert await store.delete("shared", work_root=str(project_a)) is True
    assert await store.get("shared", work_root=str(project_a)) is None
    assert (await store.get("shared", work_root=str(project_b))).description == "B"


@pytest.mark.asyncio
async def test_workflow_rename_preserves_stable_id_and_session_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LAMTOOLS_HOME", str(tmp_path / "home"))
    project = tmp_path / "project"
    session_store = _MemorySessionStore()
    store = WorkflowStore()
    context = PluginContext(
        work_root=project,
        data_dir=tmp_path / "data",
        services={"workflow_store": store, "session_store": session_store},
    )
    catalog = build_core_plugin_operation_catalog(
        data_dir=tmp_path / "data",
        work_root=project,
        plugin_roots=[bundled_plugins_dir()],
        context=context,
    )

    created = await catalog.execute(
        "workflow.create",
        {**_definition("before").to_dict(), "work_root": str(project)},
    )
    workflow_before = created.payload["workflow"]
    session_id = created.payload["session_id"]
    assert session_id == f"workflow:{workflow_before['id']}"
    original_metadata = dict(session_store.records[session_id].metadata)

    renamed = await catalog.execute(
        "workflow.rename",
        {"name": "before", "new_name": "after", "work_root": str(project)},
    )
    workflow_after = renamed.payload["workflow"]

    assert workflow_after["id"] == workflow_before["id"]
    assert renamed.payload["session_id"] == session_id
    record = session_store.records[session_id]
    assert record.title == "after"
    assert record.metadata["owner_plugin"] == "workflow"
    assert record.metadata["resource_type"] == "workflow"
    assert record.metadata["resource_id"] == workflow_before["id"]
    assert record.metadata["resource_id"] == original_metadata["resource_id"]
    assert (await store.get("after", work_root=str(project))).id == workflow_before["id"]
    assert await store.get("before", work_root=str(project)) is None


@pytest.mark.asyncio
async def test_workflow_graph_tools_resolve_canonical_session_id_without_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The UI's workflow:<uuid> session remains bound when metadata is absent."""

    monkeypatch.setenv("LAMTOOLS_HOME", str(tmp_path / "home"))
    store = WorkflowStore()
    context = PluginContext(
        work_root=tmp_path,
        data_dir=tmp_path / "data",
        services={"workflow_store": store},
    )
    catalog = build_core_plugin_operation_catalog(
        data_dir=tmp_path / "data",
        work_root=tmp_path,
        plugin_roots=[bundled_plugins_dir()],
        context=context,
    )
    created = await catalog.execute(
        "workflow.create",
        {**_definition("canonical").to_dict(), "work_root": str(tmp_path)},
    )
    workflow_id = created.payload["workflow"]["id"]
    session_id = f"workflow:{workflow_id}"
    handlers = workflow_build_tool_handlers(context.operation_executor(), work_root=tmp_path)

    graph = await handlers["workflow_graph"](
        ToolCall(
            id="graph",
            name="workflow_graph",
            metadata={"_runtime_session_id": session_id, "work_root": str(tmp_path)},
        )
    )
    assert graph.status == "ok"
    assert graph.metadata["operation_payload"]["name"] == "canonical"

    added = await handlers["workflow_add_node"](
        ToolCall(
            id="add",
            name="workflow_add_node",
            arguments={"kind": "constant", "node_id": "first"},
            metadata={"_runtime_session_id": session_id, "work_root": str(tmp_path)},
        )
    )
    assert added.status == "ok"
    saved = await catalog.execute(
        "workflow.get", {"workflow_id": workflow_id, "work_root": str(tmp_path)}
    )
    assert any(node["id"] == "first" for node in saved.payload["workflow"]["nodes"])

    global_created = await catalog.execute("workflow.create", _definition("global-canonical").to_dict())
    global_session_id = f"workflow:{global_created.payload['workflow']['id']}"
    global_graph = await handlers["workflow_graph"](
        ToolCall(
            id="global-graph",
            name="workflow_graph",
            metadata={"_runtime_session_id": global_session_id, "work_root": str(tmp_path)},
        )
    )
    assert global_graph.status == "ok"
    assert global_graph.metadata["operation_payload"]["name"] == "global-canonical"


@pytest.mark.asyncio
async def test_workflow_id_lookup_isolated_when_global_and_project_ids_collide(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An ID lookup never crosses the requested global/project repository."""

    monkeypatch.setenv("LAMTOOLS_HOME", str(tmp_path / "home"))
    project = tmp_path / "project"
    shared_id = uuid.uuid4().hex
    store = WorkflowStore()
    global_definition = WorkflowDef(
        **{
            **_definition("global-duplicate").__dict__,
            "id": shared_id,
            "description": "global copy",
        }
    )
    project_definition = WorkflowDef(
        **{
            **_definition("project-duplicate").__dict__,
            "id": shared_id,
            "description": "project copy",
            "work_root": str(project),
        }
    )
    await store.save(global_definition)
    await store.save(project_definition)

    context = PluginContext(
        work_root=tmp_path,
        data_dir=tmp_path / "data",
        services={"workflow_store": store},
    )
    catalog = build_core_plugin_operation_catalog(
        data_dir=tmp_path / "data",
        work_root=tmp_path,
        plugin_roots=[bundled_plugins_dir()],
        context=context,
    )
    project_get = await catalog.execute(
        "workflow.get", {"workflow_id": shared_id, "work_root": str(project)}
    )
    assert project_get.status == "ok"
    assert project_get.payload["workflow"]["name"] == "project-duplicate"
    assert project_get.payload["workflow"]["description"] == "project copy"

    project_document = await catalog.execute(
        "workflow.document.get", {"workflow_id": shared_id, "work_root": str(project)}
    )
    assert project_document.status == "ok"
    assert project_document.payload["document"]["resource"]["name"] == "project-duplicate"

    handlers = workflow_build_tool_handlers(context.operation_executor(), work_root=project)
    graph = await handlers["workflow_graph"](
        ToolCall(
            id="graph",
            name="workflow_graph",
            metadata={"_runtime_session_id": f"workflow:{shared_id}", "work_root": str(project)},
        )
    )
    assert graph.status == "ok"
    assert graph.metadata["operation_payload"]["name"] == "project-duplicate"

    added = await handlers["workflow_add_node"](
        ToolCall(
            id="add",
            name="workflow_add_node",
            arguments={"kind": "constant", "node_id": "project-only"},
            metadata={"_runtime_session_id": f"workflow:{shared_id}", "work_root": str(project)},
        )
    )
    assert added.status == "ok"

    global_get = await catalog.execute("workflow.get", {"workflow_id": shared_id})
    assert global_get.status == "ok"
    assert global_get.payload["workflow"]["name"] == "global-duplicate"
    assert global_get.payload["workflow"]["description"] == "global copy"
    assert not any(
        node["id"] == "project-only" for node in global_get.payload["workflow"]["nodes"]
    )
    project_after = await store.get_by_id(shared_id, work_root=str(project))
    assert project_after is not None
    assert any(node.id == "project-only" for node in project_after.nodes)


@pytest.mark.asyncio
async def test_workflow_graph_tools_reject_noncanonical_ordinary_sessions(
    tmp_path: Path,
) -> None:
    store = WorkflowStore()
    context = PluginContext(
        work_root=tmp_path,
        data_dir=tmp_path / "data",
        services={"workflow_store": store},
    )
    catalog = build_core_plugin_operation_catalog(
        data_dir=tmp_path / "data",
        work_root=tmp_path,
        plugin_roots=[bundled_plugins_dir()],
        context=context,
    )
    handlers = workflow_build_tool_handlers(context.operation_executor(), work_root=tmp_path)
    invalid_session = f"workflow:{uuid.uuid4().hex[:-1]}z"

    graph = await handlers["workflow_graph"](
        ToolCall(id="graph", name="workflow_graph", metadata={"_runtime_session_id": invalid_session})
    )
    assert graph.status == "failed"
    assert graph.error == "no active workflow (session id missing)"

    added = await handlers["workflow_add_node"](
        ToolCall(
            id="add",
            name="workflow_add_node",
            arguments={"kind": "constant"},
            metadata={"_runtime_session_id": invalid_session},
        )
    )
    assert added.status == "failed"
    assert added.error == "no active workflow (session metadata missing)"


@pytest.mark.asyncio
async def test_workflow_graph_tools_reject_uuid_parser_variants_for_canonical_sessions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Canonical sessions accept only lowercase 32-character UUID hex IDs."""

    monkeypatch.setenv("LAMTOOLS_HOME", str(tmp_path / "home"))
    canonical_id = "0123456789abcdef0123456789abcdef"
    store = WorkflowStore()
    await store.save(
        WorkflowDef(
            **{
                **_definition("strict-canonical").__dict__,
                "id": canonical_id,
            }
        )
    )
    context = PluginContext(
        work_root=tmp_path,
        data_dir=tmp_path / "data",
        services={"workflow_store": store},
    )
    catalog = build_core_plugin_operation_catalog(
        data_dir=tmp_path / "data",
        work_root=tmp_path,
        plugin_roots=[bundled_plugins_dir()],
        context=context,
    )
    handlers = workflow_build_tool_handlers(context.operation_executor(), work_root=tmp_path)
    invalid_sessions = (
        f"workflow:{{{canonical_id}}}",
        f"workflow:{canonical_id.upper()}",
        "workflow:01234567-89ab-cdef-0123-456789abcdef",
        f"workflow: {canonical_id}",
        f"workflow:{canonical_id} ",
        f" workflow:{canonical_id}",
    )

    for invalid_session in invalid_sessions:
        result = await handlers["workflow_graph"](
            ToolCall(
                id="graph",
                name="workflow_graph",
                metadata={"_runtime_session_id": invalid_session},
            )
        )
        assert result.status == "failed", invalid_session
        assert result.error == "no active workflow (session id missing)"


@pytest.mark.asyncio
async def test_workflow_graph_tools_recover_incomplete_project_session_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LAMTOOLS_HOME", str(tmp_path / "home"))
    project = tmp_path / "project"
    store = WorkflowStore()
    definition = WorkflowDef(
        **{
            **_definition("partial-project-binding").__dict__,
            "id": uuid.uuid4().hex,
            "work_root": str(project),
        }
    )
    await store.save(definition)
    context = PluginContext(
        work_root=tmp_path,
        data_dir=tmp_path / "data",
        services={"workflow_store": store},
    )
    build_core_plugin_operation_catalog(
        data_dir=tmp_path / "data",
        work_root=tmp_path,
        plugin_roots=[bundled_plugins_dir()],
        context=context,
    )
    handlers = workflow_build_tool_handlers(context.operation_executor(), work_root=tmp_path)
    result = await handlers["workflow_graph"](
        ToolCall(
            id="graph",
            name="workflow_graph",
            metadata={
                "_runtime_session_id": f"workflow:{definition.id}",
                "_runtime_session_metadata": {
                    "owner_plugin": "workflow",
                    "resource_type": "workflow",
                    "resource_id": definition.id,
                },
                "work_root": str(project),
            },
        )
    )
    assert result.status == "ok"
    assert result.metadata["operation_payload"]["name"] == definition.name


@pytest.mark.asyncio
async def test_workflow_document_get_repairs_incomplete_plugin_session(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    store = WorkflowStore()
    session_store = _MemorySessionStore()
    context = PluginContext(
        work_root=project,
        data_dir=tmp_path / "data",
        services={"workflow_store": store, "session_store": session_store},
    )
    catalog = build_core_plugin_operation_catalog(
        data_dir=tmp_path / "data",
        work_root=project,
        plugin_roots=[bundled_plugins_dir()],
        context=context,
    )
    created = await catalog.execute(
        "workflow.create",
        {**_definition("document-repair").to_dict(), "work_root": str(project)},
    )
    workflow = created.payload["workflow"]
    session_id = created.payload["session_id"]
    session_store.records[session_id].metadata = {}

    result = await catalog.execute(
        "workflow.document.get",
        {"workflow_id": workflow["id"], "work_root": str(project)},
    )
    assert result.status == "ok"
    assert result.payload["session_id"] == session_id
    assert session_store.records[session_id].metadata["resource_id"] == workflow["id"]
    assert session_store.records[session_id].metadata["resource_work_root"] == str(project)
    assert "work_root" not in session_store.records[session_id].metadata


@pytest.mark.asyncio
async def test_workflow_document_get_repairs_stale_global_resource_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LAMTOOLS_HOME", str(tmp_path / "home"))
    store = WorkflowStore()
    session_store = _MemorySessionStore()
    context = PluginContext(
        work_root=tmp_path,
        data_dir=tmp_path / "data",
        services={"workflow_store": store, "session_store": session_store},
    )
    catalog = build_core_plugin_operation_catalog(
        data_dir=tmp_path / "data",
        work_root=tmp_path,
        plugin_roots=[bundled_plugins_dir()],
        context=context,
    )
    created = await catalog.execute("workflow.create", _definition("global-repair").to_dict())
    workflow = created.payload["workflow"]
    session_id = created.payload["session_id"]
    session_store.records[session_id].metadata["work_root"] = str(tmp_path / "stale")

    repaired = await catalog.execute("workflow.document.get", {"workflow_id": workflow["id"]})
    assert repaired.status == "ok"
    assert session_store.records[session_id].metadata["work_root"] == str(tmp_path / "stale")
    assert session_store.records[session_id].metadata["resource_work_root"] == ""

    handlers = workflow_build_tool_handlers(context.operation_executor(), work_root=tmp_path)
    graph = await handlers["workflow_graph"](
        ToolCall(
            id="graph",
            name="workflow_graph",
            metadata={
                "_runtime_session_id": session_id,
                "_runtime_session_metadata": dict(session_store.records[session_id].metadata),
            },
        )
    )
    assert graph.status == "ok"
    assert graph.metadata["operation_payload"]["name"] == workflow["name"]
