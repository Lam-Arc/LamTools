from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from lamtools_core.plugins.bundled.workflow.backend.document import (
    DOCUMENT_FORMAT,
    WorkflowDocumentError,
    canonicalize_document,
    compile_document,
    document_from_workflow_def,
    export_comfyui,
    import_comfyui,
    semantic_graph,
    workflow_def_from_document,
)
from lamtools_core.plugins.bundled.workflow.backend.runtime import (
    WorkflowConflictError,
    WorkflowDef,
    WorkflowEdge,
    WorkflowManager,
    WorkflowNode,
    WorkflowPort,
    WorkflowRunner,
)
from lamtools_core.plugins.bundled.workflow.backend.store import WorkflowStore
from lamtools_core.app.base_agent import build_core_plugin_operation_catalog
from lamtools_core.plugins.context import PluginContext
from lamtools_core.plugins.registry import bundled_plugins_dir


def _legacy() -> WorkflowDef:
    return WorkflowDef(
        id="wf-stable", name="v2", revision=3,
        nodes=[
            WorkflowNode(id="a", kind="content", ports=[WorkflowPort(id="a-out", name="out", type="string", direction="out", value="hello")], position={"x": 10, "y": 20}),
            WorkflowNode(id="b", kind="script", config={"script": "result = text"}, ports=[
                WorkflowPort(id="b-in", name="text", type="string", direction="in"),
                WorkflowPort(id="b-out", name="result", type="string", direction="out"),
            ]),
        ],
        edges=[WorkflowEdge(id="l1", source="a", source_port="out", source_port_id="a-out", target="b", target_port="text", target_port_id="b-in")],
        output_port="b.result",
    )


def test_v2_round_trip_and_compiler_strip_canvas() -> None:
    doc = document_from_workflow_def(_legacy())
    assert doc["format"] == DOCUMENT_FORMAT
    restored = workflow_def_from_document(doc)
    assert restored.edges[0].source_port_id == "a-out"
    prompt = compile_document(doc)
    assert prompt["order"] == ["a", "b"]
    assert "canvas" not in prompt
    assert prompt["nodes"]["b"]["inputs"]["b-in"]["links"][0] == {
        "node_id": "a", "port_id": "a-out"
    }


def test_parent_id_round_trips_in_canvas_only_and_clear_does_not_revive() -> None:
    definition = _legacy()
    definition.nodes[1].parent_id = "group-a"

    legacy_payload = definition.nodes[1].to_dict()
    assert legacy_payload["parent_id"] == "group-a"
    legacy_alias_payload = {key: value for key, value in legacy_payload.items() if key != "parent_id"}
    legacy_alias_payload["parentId"] = "group-a"
    assert WorkflowNode.from_dict(legacy_alias_payload).parent_id == "group-a"
    assert WorkflowNode.from_dict({**legacy_payload, "parent_id": None, "parentId": "stale"}).parent_id is None

    document = document_from_workflow_def(definition)
    assert document["canvas"]["node_views"]["b"]["parent_id"] == "group-a"
    assert "parent_id" not in document["graph"]["nodes"][1]
    prompt = compile_document(document)
    assert all("parent_id" not in node for node in prompt["nodes"].values())

    restored = workflow_def_from_document(document)
    assert restored.nodes[1].parent_id == "group-a"
    restored.nodes[1].parent_id = None
    cleared = document_from_workflow_def(restored)
    assert "parent_id" not in cleared["canvas"]["node_views"]["b"]
    assert workflow_def_from_document(cleared).nodes[1].parent_id is None


def test_port_display_rename_does_not_break_link() -> None:
    doc = document_from_workflow_def(_legacy())
    source = doc["graph"]["nodes"][0]["ports"][0]
    source["name"] = "renamed"
    normalized = canonicalize_document(doc)
    assert normalized["graph"]["links"][0]["source"]["port_id"] == "a-out"
    assert compile_document(normalized)["nodes"]["b"]["inputs"]["b-in"]["links"][0]["port_id"] == "a-out"


@pytest.mark.parametrize("source_type", ["number", "boolean", "int", "bool"])
def test_v2_preserves_legacy_scalar_to_string_compatibility(source_type: str) -> None:
    doc = document_from_workflow_def(_legacy())
    doc["graph"]["nodes"][0]["ports"][0]["data_type"] = source_type
    assert canonicalize_document(doc)["graph"]["links"][0]["id"] == "l1"


def test_legacy_on_error_migrates_only_to_execution_policy() -> None:
    legacy = _legacy()
    legacy.nodes[1].config["on_error"] = {"strategy": "continue"}
    doc = document_from_workflow_def(legacy)
    migrated = doc["graph"]["nodes"][1]
    assert migrated["execution"]["on_error"] == {"strategy": "continue"}
    assert "on_error" not in migrated["params"]


def test_semantic_graph_is_compact_focused_and_paginated() -> None:
    graph = semantic_graph(document_from_workflow_def(_legacy()), node_ids=["b"], limit=1)
    assert graph["format"] == "lamtools.semantic-graph"
    assert len(graph["nodes"]) == 1
    assert graph["page"]["total"] == 2
    assert "params" not in graph["nodes"][0]
    assert "canvas" not in graph


@pytest.mark.parametrize("version", ["0.4", "1"])
def test_comfyui_editor_adapter_round_trip(version: str) -> None:
    exported = export_comfyui(document_from_workflow_def(_legacy()), version=version)
    imported = import_comfyui(exported, name="roundtrip")
    assert len(imported["graph"]["nodes"]) == 2
    assert len(imported["graph"]["links"]) == 1
    assert imported["canvas"]["node_views"]["a"]["position"] == {"x": 10.0, "y": 20.0}


def test_comfyui_v1_real_shape_uses_object_links_state_and_preserves_extensions() -> None:
    payload = {
        "version": 1,
        "state": {"lastGroupId": 4, "lastNodeId": 17, "lastLinkId": 23, "lastRerouteId": 8},
        "nodes": [
            {
                "id": 2, "type": "ForeignSource", "pos": [11, 22], "size": [210, 90],
                "flags": {"collapsed": False}, "order": 0, "mode": 0,
                "inputs": [], "outputs": [{
                    "name": "IMAGE", "type": "IMAGE", "links": [23],
                    "shape": 3, "slot_index": 7, "label_on": "ready",
                    "widget": {"name": "preview"}, "vendor_slot": {"color": "cyan"},
                }],
                "properties": {"Node name for S&R": "ForeignSource", "vendor": {"rev": 3}},
                "widgets_values": [512, {"seed": 42}], "shape": 2,
                "widgets": [{"name": "vendor-control", "serialize": True}],
            },
            {
                "id": 17, "type": "ForeignSink", "pos": [330, 22], "size": [220, 100],
                "flags": {}, "order": 1, "mode": 0,
                "inputs": [{
                    "name": "IMAGE", "type": "IMAGE", "link": 23,
                    "shape": 1, "slot_index": 4, "label_on": "connected",
                    "widget": {"name": "receiver"}, "vendor_slot": ["x", 2],
                }], "outputs": [],
                "properties": {"Node name for S&R": "ForeignSink"},
                "widgets_values": {"named": {"strength": 0.75}},
            },
        ],
        "links": [{
            "id": 23, "origin_id": 2, "origin_slot": 0,
            "target_id": 17, "target_slot": 0, "type": "IMAGE",
            "hidden": True, "label": "preview", "parentId": 8,
            "vendor_link": {"route": "fast"},
        }],
        "groups": [{"id": 4, "title": "group", "bounding": [0, 0, 600, 300]}],
        "reroutes": [{"id": 8, "pos": [250, 60], "linkIds": [23]}],
        "extra": {"ds": {"scale": 0.8, "offset": [4, 5]}},
    }
    doc = import_comfyui(payload, name="real-v1")
    # Foreign editor metadata must remain canvas-only and never become input
    # to the canonical execution prompt.
    assert doc["graph"]["nodes"][0]["params"] == {}
    assert doc["canvas"]["node_views"]["2"]["comfyui"]["raw"]["widgets_values"] == [512, {"seed": 42}]
    exported = export_comfyui(doc, version="1")
    assert exported["state"] == {
        "lastGroupId": 4, "lastNodeId": 17, "lastLinkId": 23, "lastRerouteId": 8,
    }
    assert exported["links"] == payload["links"]
    source = exported["nodes"][0]
    assert source["id"] == 2
    assert source["shape"] == 2
    assert source["widgets"] == [{"name": "vendor-control", "serialize": True}]
    assert source["widgets_values"] == [512, {"seed": 42}]
    assert source["properties"]["vendor"] == {"rev": 3}
    assert source["properties"]["Node name for S&R"] == "ForeignSource"
    assert source["outputs"][0] == payload["nodes"][0]["outputs"][0]
    sink = exported["nodes"][1]
    assert sink["inputs"][0] == payload["nodes"][1]["inputs"][0]
    assert sink["widgets_values"] == {"named": {"strength": 0.75}}


def test_comfyui_v04_uses_array_links_extra_reroutes_and_max_numeric_node_id() -> None:
    payload = {
        "version": 0.4, "last_node_id": 41, "last_link_id": 7,
        "nodes": [
            {"id": 5, "type": "A", "pos": [0, 0], "inputs": [], "outputs": [{"name": "x", "type": "*", "links": [7]}]},
            {"id": 41, "type": "B", "pos": [100, 0], "inputs": [{"name": "x", "type": "*", "link": 7}], "outputs": []},
        ],
        "links": [[7, 5, 0, 41, 0, "*"]], "groups": [],
        "extra": {"ds": {"scale": 1.2, "offset": [7, 9]}, "reroutes": [{"id": 6, "pos": [50, 10], "linkIds": [7]}]},
    }
    doc = import_comfyui(payload, name="real-v04")
    assert doc["canvas"]["reroutes"] == payload["extra"]["reroutes"]
    exported = export_comfyui(doc, version="0.4")
    assert exported["last_node_id"] == 41
    assert exported["last_link_id"] == 7
    assert exported["links"] == [[7, 5, 0, 41, 0, "*"]]
    assert exported["extra"]["reroutes"] == payload["extra"]["reroutes"]


def test_semantic_focus_is_exactly_one_hop_and_never_has_dangling_adjacency() -> None:
    doc = document_from_workflow_def(_legacy())
    third = {
        "id": "c", "type": {"id": "script", "version": 1}, "title": "C",
        "ports": [
            {"id": "c-in", "name": "in", "direction": "in", "data_type": "string", "description": "", "required": False, "lazy": False},
            {"id": "c-out", "name": "out", "direction": "out", "data_type": "string", "description": "", "required": False, "lazy": False},
        ],
        "params": {"script": "out = in"},
        "execution": {"enabled": True, "schema_only": False, "cache": "auto", "on_error": {"strategy": "abort"}, "permissions": []},
    }
    doc["graph"]["nodes"].append(third)
    # Put b->c first to reproduce the former order-dependent set expansion.
    doc["graph"]["links"] = [
        {"id": "l2", "source": {"node_id": "b", "port_id": "b-out"}, "target": {"node_id": "c", "port_id": "c-in"}},
        doc["graph"]["links"][0],
    ]
    focused = semantic_graph(doc, node_ids=["a"])
    assert [node["id"] for node in focused["nodes"]] == ["a", "b"]
    assert focused["topological_order"] == ["a", "b"]
    assert [edge["link_id"] for edge in focused["adjacency"]] == ["l1"]
    visible = {node["id"] for node in focused["nodes"]}
    assert all(edge["from"][0] in visible and edge["to"][0] in visible for edge in focused["adjacency"])


def test_unknown_comfyui_node_is_truthful_schema_only() -> None:
    doc = import_comfyui({"version": 1, "nodes": [{"id": 1, "type": "KSampler", "inputs": [], "outputs": []}], "links": []}, name="unknown")
    node = doc["graph"]["nodes"][0]
    assert node["type"]["id"] == "KSampler"
    assert node["execution"]["schema_only"] is True
    with pytest.raises(WorkflowDocumentError, match="schema-only"):
        compile_document(doc)


async def test_store_prefers_atomic_v2_and_retains_legacy_files(tmp_path: Path) -> None:
    definition = _legacy()
    definition.work_root = str(tmp_path)
    store = WorkflowStore()
    await store.save(definition)
    folder = tmp_path / ".lam" / "workflows" / "v2"
    assert (folder / "workflow.json").is_file()
    assert (folder / "config.json").is_file()
    assert (folder / "a.json").is_file()
    raw = json.loads((folder / "workflow.json").read_text(encoding="utf-8"))
    assert raw["format"] == DOCUMENT_FORMAT
    # A stale legacy mutation is ignored because canonical V2 has precedence.
    config = json.loads((folder / "config.json").read_text(encoding="utf-8"))
    config["name"] = "wrong"
    (folder / "config.json").write_text(json.dumps(config), encoding="utf-8")
    loaded = await store.get("v2", work_root=str(tmp_path))
    assert loaded is not None and loaded.name == "v2"


async def test_store_reload_preserves_parent_id_in_canonical_and_legacy_node_files(tmp_path: Path) -> None:
    definition = _legacy()
    definition.work_root = str(tmp_path)
    definition.nodes[1].parent_id = "group-a"
    store = WorkflowStore()
    await store.save(definition)
    folder = tmp_path / ".lam" / "workflows" / "v2"
    canonical = json.loads((folder / "workflow.json").read_text(encoding="utf-8"))
    legacy_node = json.loads((folder / "b.json").read_text(encoding="utf-8"))
    assert canonical["canvas"]["node_views"]["b"]["parent_id"] == "group-a"
    assert legacy_node["parent_id"] == "group-a"

    loaded = await store.get("v2", work_root=str(tmp_path))
    assert loaded is not None
    assert loaded.nodes[1].parent_id == "group-a"


async def test_v2_save_uses_revision_cas(tmp_path: Path) -> None:
    manager = WorkflowManager(WorkflowStore())
    definition = _legacy()
    definition.work_root = str(tmp_path)
    created = await manager.create(definition)
    doc = document_from_workflow_def(created)
    first, second = await asyncio.gather(
        manager.save_document(doc, work_root=str(tmp_path), expected_revision=created.revision),
        manager.save_document(doc, work_root=str(tmp_path), expected_revision=created.revision),
        return_exceptions=True,
    )
    values = (first, second)
    assert sum(isinstance(item, WorkflowConflictError) for item in values) == 1
    assert sum(isinstance(item, WorkflowDef) for item in values) == 1


async def test_v2_interface_name_binds_target_and_output(tmp_path: Path) -> None:
    doc = document_from_workflow_def(_legacy())
    # Replace the graph with one input-driven node to prove public names do
    # not depend on node/port display names.
    doc["graph"]["nodes"] = [doc["graph"]["nodes"][1]]
    doc["graph"]["links"] = []
    doc["interface"]["inputs"] = [{
        "id": "public-in", "name": "message", "data_type": "string",
        "description": "", "required": True,
        "target": {"node_id": "b", "port_id": "b-in"},
    }]
    doc["interface"]["outputs"][0]["name"] = "answer"
    definition = workflow_def_from_document(doc)
    result = await WorkflowRunner().run(definition, inputs={"message": "ok"}, work_root=str(tmp_path))
    assert result.status == "completed"
    assert result.output == "ok"


async def test_v2_rpc_surface_has_document_compile_semantic_and_comfyui(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LAMTOOLS_HOME", str(tmp_path / "home"))
    data_dir = tmp_path / "data"
    context = PluginContext(work_root=tmp_path, data_dir=data_dir, services={"workflow_store": WorkflowStore()})
    catalog = build_core_plugin_operation_catalog(
        data_dir=data_dir, work_root=tmp_path,
        plugin_roots=[bundled_plugins_dir()], context=context,
    )
    definition = _legacy()
    definition.work_root = str(tmp_path)
    assert (await catalog.execute("workflow.create", definition.to_dict())).status == "ok"
    fetched = await catalog.execute("workflow.document.get", {"name": "v2", "work_root": str(tmp_path)})
    assert fetched.payload["document"]["version"] == 2
    compiled = await catalog.execute("workflow.compile", {"name": "v2", "work_root": str(tmp_path)})
    assert compiled.payload["prompt"]["order"] == ["a", "b"]
    semantic = await catalog.execute("workflow.semantic", {"name": "v2", "work_root": str(tmp_path), "limit": 1})
    assert semantic.payload["semantic"]["page"]["has_more"] is True
    exported = await catalog.execute("workflow.export.comfyui", {"name": "v2", "work_root": str(tmp_path), "version": "0.4"})
    assert exported.payload["workflow"]["version"] == 0.4
    imported = await catalog.execute("workflow.import.comfyui", {
        "name": "foreign", "work_root": str(tmp_path),
        "workflow": {"version": 1, "nodes": [{"id": 9, "type": "ForeignNode", "inputs": [], "outputs": []}], "links": []},
    })
    assert imported.status == "ok"
    run = await catalog.execute("workflow.run", {"name": "foreign", "work_root": str(tmp_path)})
    assert run.payload["run"]["status"] == "failed"
    assert "schema-only" in run.payload["run"]["error"]
