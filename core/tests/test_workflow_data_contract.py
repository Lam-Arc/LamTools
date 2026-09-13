from __future__ import annotations

import pytest

from lamtools_core.plugins.bundled.workflow.backend.capabilities import WorkflowNodeCapabilities
from lamtools_core.plugins.bundled.workflow.backend.credentials import (
    CredentialError,
    CredentialRef,
    redact_workflow_value,
    serialize_workflow_value,
)
from lamtools_core.plugins.bundled.workflow.backend.data_packet import (
    ArtifactRef,
    AttachmentRef,
    WorkflowDataPacket,
    WorkflowDataPacketError,
    is_data_packet,
)
from lamtools_core.plugins.bundled.workflow.backend.document import (
    WorkflowDocumentError,
    canonicalize_document,
    export_comfyui,
    import_comfyui,
)
from lamtools_core.plugins.bundled.workflow.backend.registry import WorkflowNodeRegistry


def _document(**extra):
    return {
        "format": "lamtools.workflow",
        "version": 2,
        "resource": {"name": "contract"},
        "graph": {"nodes": [], "links": []},
        **extra,
    }


def test_data_packet_wraps_legacy_values_without_guessing_old_dicts():
    legacy = {"items": [1], "kind": "ordinary-config"}
    packet = WorkflowDataPacket.coerce(legacy)
    assert packet.items[0].json == legacy
    assert not is_data_packet(legacy)
    assert packet.to_legacy() == legacy


def test_data_packet_references_binary_and_round_trips_pairing_lineage():
    packet = WorkflowDataPacket([
        {
            "json": {"answer": 1},
            "binary": {"id": "att-1", "mime_type": "image/png", "size": 12},
            "paired": [{"item": 0}],
            "lineage": ["run-1", "node-a"],
        }
    ])
    assert packet.to_dict()["items"][0]["binary"] == {
        "id": "att-1", "mime_type": "image/png", "size": 12,
    }
    assert WorkflowDataPacket.from_dict(packet.to_dict()).to_dict() == packet.to_dict()


@pytest.mark.parametrize("value", [
    {"id": "att", "content": "inline"},
    {"id": "att", "data": "aGVsbG8="},
    {"id": "att", "uri": "data:text/plain;base64,SGk="},
])
def test_attachment_ref_rejects_embedded_binary(value):
    with pytest.raises(WorkflowDataPacketError):
        AttachmentRef.from_dict(value)


def test_artifact_ref_has_no_content_surface():
    ref = ArtifactRef(id="artifact-1", uri="workspace://out/result.json")
    assert ref.to_dict() == {"artifact_id": "artifact-1", "uri": "workspace://out/result.json"}
    with pytest.raises(WorkflowDataPacketError):
        ArtifactRef.from_dict({"artifact_id": "a", "path": "C:/secret.bin"})


def test_credential_refs_serialize_without_secret_and_reject_secret_payloads():
    ref = CredentialRef(id="prod", provider="openai")
    assert serialize_workflow_value({"credential": ref})["credential"] == ref.to_dict()
    with pytest.raises(CredentialError):
        serialize_workflow_value({"api_key": "sk-secret"})
    assert redact_workflow_value({"api_key": "sk-secret", "credential": ref})["api_key"] == "[REDACTED]"


def test_document_rejects_secret_and_normalizes_triggers_policies():
    document = canonicalize_document(_document(
        graph={"nodes": [{"id": "n", "type": {"id": "constant", "version": 1}, "params": {"credential": CredentialRef("prod")}, "ports": []}], "links": []},
        triggers=[{"kind": "manual"}, {"type": "interval", "seconds": 5}],
        policies={"timeout_seconds": 10, "permissions": ["read"]},
    ))
    assert [item["type"] for item in document["triggers"]] == ["manual", "interval"]
    assert document["triggers"][1]["every_seconds"] == 5
    assert document["policies"]["permissions"] == ["read"]
    with pytest.raises(WorkflowDocumentError):
        canonicalize_document(_document(graph={"nodes": [{"id": "n", "type": {"id": "constant"}, "params": {"api_key": "secret"}, "ports": []}], "links": []}))


def test_explicit_node_migration_chain_is_applied_and_gaps_are_rejected():
    registry = WorkflowNodeRegistry()
    registry.register_schema({"name": "vendor.node", "version": 3, "input": {}, "output": {}}, trusted=True)
    registry.register_migration("vendor.node", 1, 2, lambda node: {**node, "params": {"step": 1}})
    registry.register_migration("vendor.node", 2, 3, lambda node: {**node, "params": {**node["params"], "step2": True}})
    node = registry.migrate_node({"type": {"id": "vendor.node", "version": 1}, "params": {}})
    assert node["type"]["version"] == 3
    assert node["params"] == {"step": 1, "step2": True}
    with pytest.raises(ValueError):
        registry.migrate_node({"type": {"id": "vendor.node", "version": 2}, "params": {}}, target_version=4)


def test_registry_exposes_capability_resource_contract():
    registry = WorkflowNodeRegistry()
    registry.register_schema({
        "name": "vendor.gpu", "input": {}, "output": {},
        "capabilities": ["gpu", "network"], "resource_class": "accelerated",
        "resource_requirements": {"memory_mb": 1024},
    }, plugin_id="vendor", trusted=True)
    info = registry.object_info("vendor.gpu")["vendor.gpu"]
    assert info["capabilities"] == ["gpu", "network"]
    assert info["resource_class"] == "accelerated"
    assert info["resource_requirements"] == {"memory_mb": 1024}


def test_triggers_and_policies_survive_comfyui_extension_round_trip():
    document = canonicalize_document(_document(
        triggers=[{"type": "event", "event": "build.completed"}],
        policies={"max_concurrency": 2},
    ))
    round_trip = import_comfyui(export_comfyui(document), name="round-trip")
    assert round_trip["triggers"][0]["event_type"] == "build.completed"
    assert round_trip["policies"]["max_concurrency"] == 2


def test_expression_ast_survives_canonical_document_round_trip():
    expression = {
        "type": "binary",
        "op": "==",
        "left": {"type": "path", "root": "input", "segments": ["value"]},
        "right": {"type": "literal", "value": "ok"},
    }
    document = canonicalize_document(_document(graph={
        "nodes": [
            {"id": "a", "type": {"id": "constant", "version": 1}, "params": {}, "ports": [{"id": "out", "direction": "out"}]},
            {"id": "b", "type": {"id": "output", "version": 1}, "params": {}, "ports": [{"id": "in", "direction": "in"}]},
        ],
        "links": [{
            "id": "edge", "source": {"node_id": "a", "port_id": "out"},
            "target": {"node_id": "b", "port_id": "in"}, "condition": expression,
        }],
    }))
    assert document["graph"]["links"][0]["condition"] == expression
