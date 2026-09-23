use lamtools_runtime::workflow_document::{
    canonicalize_document, compile_document, document_from_workflow_def, export_comfyui,
    import_comfyui, semantic_graph, stable_id, workflow_def_from_document, WorkflowDocumentError,
};
use serde_json::{json, Value};

fn legacy_workflow() -> Value {
    json!({
        "id": "wf-stable",
        "name": "v2",
        "description": "fixture",
        "revision": 3,
        "nodes": [
            {
                "id": "a", "kind": "content", "title": "A",
                "ports": [{"id": "a-out", "name": "out", "type": "string", "direction": "out", "value": "hello"}],
                "position": {"x": 10, "y": 20}
            },
            {
                "id": "b", "kind": "script", "config": {"script": "result = text"},
                "ports": [
                    {"id": "b-in", "name": "text", "type": "string", "direction": "in"},
                    {"id": "b-out", "name": "result", "type": "string", "direction": "out"}
                ]
            }
        ],
        "edges": [{
            "id": "l1", "source": "a", "source_port": "out", "source_port_id": "a-out",
            "target": "b", "target_port": "text", "target_port_id": "b-in"
        }],
        "output_port": "b.result"
    })
}

#[test]
fn v2_projection_compiles_without_canvas_and_round_trips_stable_endpoints() {
    let document = document_from_workflow_def(&legacy_workflow()).unwrap();
    let restored = workflow_def_from_document(&document).unwrap();
    let prompt = compile_document(&document).unwrap();

    assert_eq!(document["format"], "lamtools.workflow");
    assert_eq!(prompt["order"], json!(["a", "b"]));
    assert!(prompt.get("canvas").is_none());
    assert_eq!(
        prompt["nodes"]["b"]["inputs"]["b-in"]["links"][0],
        json!({"node_id": "a", "port_id": "a-out"})
    );
    assert_eq!(restored["edges"][0]["source_port_id"], "a-out");
    assert_eq!(restored["edges"][0]["target_port_id"], "b-in");
}

#[test]
fn canonicalization_validates_types_cycles_and_secret_material() {
    let document = document_from_workflow_def(&legacy_workflow()).unwrap();
    let mut renamed = document.clone();
    renamed["graph"]["nodes"][0]["ports"][0]["name"] = json!("renamed");
    let normalized = canonicalize_document(&renamed).unwrap();
    assert_eq!(
        normalized["graph"]["links"][0]["source"]["port_id"],
        "a-out"
    );

    let mut cycle = normalized.clone();
    cycle["graph"]["links"].as_array_mut().unwrap().push(json!({
        "id": "l2", "source": {"node_id": "b", "port_id": "b-out"},
        "target": {"node_id": "b", "port_id": "b-in"}
    }));
    assert!(canonicalize_document(&cycle)
        .unwrap_err()
        .to_string()
        .contains("cycle"));

    let mut secret = normalized;
    secret["graph"]["nodes"][0]["params"] = json!({"api_key": "sk-secret"});
    assert!(canonicalize_document(&secret)
        .unwrap_err()
        .to_string()
        .contains("secret"));
}

#[test]
fn semantic_focus_is_one_hop_and_adjacency_stays_page_bounded() {
    let mut document = document_from_workflow_def(&legacy_workflow()).unwrap();
    document["graph"]["nodes"]
        .as_array_mut()
        .unwrap()
        .push(json!({
            "id": "c", "type": {"id": "script", "version": 1}, "title": "C",
            "ports": [
                {"id": "c-in", "name": "in", "direction": "in", "data_type": "string"},
                {"id": "c-out", "name": "out", "direction": "out", "data_type": "string"}
            ], "params": {}, "execution": {"enabled": true}
        }));
    document["graph"]["links"] = json!([
        {"id": "l2", "source": {"node_id": "b", "port_id": "b-out"}, "target": {"node_id": "c", "port_id": "c-in"}},
        {"id": "l1", "source": {"node_id": "a", "port_id": "a-out"}, "target": {"node_id": "b", "port_id": "b-in"}}
    ]);
    let focused = semantic_graph(&document, Some(&["a".into()]), 0, 100).unwrap();
    assert_eq!(
        focused["nodes"]
            .as_array()
            .unwrap()
            .iter()
            .map(|node| node["id"].clone())
            .collect::<Vec<_>>(),
        vec![json!("a"), json!("b")]
    );
    assert_eq!(focused["topological_order"], json!(["a", "b"]));
    assert_eq!(focused["adjacency"][0]["link_id"], "l1");
    assert_eq!(focused["adjacency"].as_array().unwrap().len(), 1);

    let paged = semantic_graph(&document, None, 0, 1).unwrap();
    assert_eq!(paged["page"]["total"], 3);
    assert_eq!(paged["page"]["has_more"], true);
}

#[test]
fn comfyui_v04_and_v1_round_trip_editor_metadata_and_schema_only_nodes() {
    let document = document_from_workflow_def(&legacy_workflow()).unwrap();
    let v04 = export_comfyui(&document, "0.4").unwrap();
    assert_eq!(v04["version"], json!(0.4));
    assert!(v04["links"][0].is_array());
    let imported = import_comfyui(&v04, "roundtrip").unwrap();
    assert_eq!(imported["graph"]["nodes"].as_array().unwrap().len(), 2);
    assert_eq!(imported["graph"]["links"].as_array().unwrap().len(), 1);
    assert_eq!(
        imported["canvas"]["node_views"]["a"]["position"]["x"],
        json!(10.0)
    );

    let foreign = import_comfyui(
        &json!({
            "version": 1,
            "nodes": [{"id": 9, "type": "KSampler", "inputs": [], "outputs": [], "widgets_values": [42]}],
            "links": []
        }),
        "unknown",
    )
    .unwrap();
    assert_eq!(
        foreign["graph"]["nodes"][0]["execution"]["schema_only"],
        true
    );
    let error = compile_document(&foreign).unwrap_err();
    assert!(error.to_string().contains("schema-only"));
}

#[test]
fn comfyui_real_v1_extensions_stay_canvas_only_and_round_trip() {
    let payload = json!({
        "version": 1,
        "state": {"lastGroupId": 4, "lastNodeId": 17, "lastLinkId": 23, "lastRerouteId": 8},
        "nodes": [
            {
                "id": 2, "type": "ForeignSource", "pos": [11, 22], "size": [210, 90],
                "flags": {"collapsed": false}, "order": 0, "mode": 0,
                "inputs": [], "outputs": [{
                    "name": "IMAGE", "type": "IMAGE", "links": [23], "shape": 3,
                    "slot_index": 7, "label_on": "ready", "widget": {"name": "preview"},
                    "vendor_slot": {"color": "cyan"}
                }],
                "properties": {"Node name for S&R": "ForeignSource", "vendor": {"rev": 3}},
                "widgets_values": [512, {"seed": 42}], "shape": 2,
                "widgets": [{"name": "vendor-control", "serialize": true}]
            },
            {
                "id": 17, "type": "ForeignSink", "pos": [330, 22], "size": [220, 100],
                "flags": {}, "order": 1, "mode": 0,
                "inputs": [{
                    "name": "IMAGE", "type": "IMAGE", "link": 23, "shape": 1,
                    "slot_index": 4, "label_on": "connected", "widget": {"name": "receiver"},
                    "vendor_slot": ["x", 2]
                }], "outputs": [], "properties": {"Node name for S&R": "ForeignSink"},
                "widgets_values": {"named": {"strength": 0.75}}
            }
        ],
        "links": [{
            "id": 23, "origin_id": 2, "origin_slot": 0, "target_id": 17,
            "target_slot": 0, "type": "IMAGE", "hidden": true, "label": "preview",
            "parentId": 8, "vendor_link": {"route": "fast"}
        }],
        "groups": [{"id": 4, "title": "group", "bounding": [0, 0, 600, 300]}],
        "reroutes": [{"id": 8, "pos": [250, 60], "linkIds": [23]}],
        "extra": {"ds": {"scale": 0.8, "offset": [4, 5]}}
    });
    let document = import_comfyui(&payload, "real-v1").unwrap();
    assert_eq!(document["graph"]["nodes"][0]["params"], json!({}));
    assert_eq!(
        document["canvas"]["node_views"]["2"]["comfyui"]["raw"]["widgets_values"],
        json!([512, {"seed": 42}])
    );
    let exported = export_comfyui(&document, "1").unwrap();
    assert_eq!(
        exported["state"],
        json!({"lastGroupId": 4, "lastNodeId": 17, "lastLinkId": 23, "lastRerouteId": 8})
    );
    assert_eq!(exported["links"], payload["links"]);
    assert_eq!(exported["nodes"][0]["id"], json!(2));
    assert_eq!(exported["nodes"][0]["shape"], json!(2));
    assert_eq!(
        exported["nodes"][0]["widgets"],
        payload["nodes"][0]["widgets"]
    );
    assert_eq!(
        exported["nodes"][0]["widgets_values"],
        payload["nodes"][0]["widgets_values"]
    );
    assert_eq!(
        exported["nodes"][0]["properties"]["vendor"],
        json!({"rev": 3})
    );
    assert_eq!(
        exported["nodes"][0]["outputs"][0],
        payload["nodes"][0]["outputs"][0]
    );
    assert_eq!(
        exported["nodes"][1]["inputs"][0],
        payload["nodes"][1]["inputs"][0]
    );
    assert_eq!(
        exported["nodes"][1]["widgets_values"],
        payload["nodes"][1]["widgets_values"]
    );
}

#[test]
fn comfyui_real_v04_uses_array_links_and_extra_reroutes() {
    let payload = json!({
        "version": 0.4, "last_node_id": 41, "last_link_id": 7,
        "nodes": [
            {"id": 5, "type": "A", "pos": [0, 0], "inputs": [], "outputs": [{"name": "x", "type": "*", "links": [7]}]},
            {"id": 41, "type": "B", "pos": [100, 0], "inputs": [{"name": "x", "type": "*", "link": 7}], "outputs": []}
        ],
        "links": [[7, 5, 0, 41, 0, "*"]], "groups": [],
        "extra": {"ds": {"scale": 1.2, "offset": [7, 9]}, "reroutes": [{"id": 6, "pos": [50, 10], "linkIds": [7]}]}
    });
    let document = import_comfyui(&payload, "real-v04").unwrap();
    assert_eq!(document["canvas"]["reroutes"], payload["extra"]["reroutes"]);
    let exported = export_comfyui(&document, "0.4").unwrap();
    assert_eq!(exported["last_node_id"], json!(41));
    assert_eq!(exported["last_link_id"], json!(7));
    assert_eq!(exported["links"], payload["links"]);
    assert_eq!(exported["extra"]["reroutes"], payload["extra"]["reroutes"]);
}

#[test]
fn comfyui_import_rejects_malformed_slot_indices_instead_of_using_slot_zero() {
    let payload = json!({
        "version": 1,
        "nodes": [
            {"id": 1, "type": "Source", "inputs": [], "outputs": [{"name": "out", "type": "*"}]},
            {"id": 2, "type": "Sink", "inputs": [{"name": "in", "type": "*"}], "outputs": []}
        ],
        "links": [{
            "id": 1, "origin_id": 1, "origin_slot": "malformed",
            "target_id": 2, "target_slot": 0, "type": "*"
        }]
    });

    assert!(import_comfyui(&payload, "malformed-slot").is_err());
}

#[test]
fn comfyui_import_does_not_silently_drop_nodes_without_ids() {
    let payload = json!({
        "version": 1,
        "nodes": [{"type": "ForeignNode", "inputs": [], "outputs": []}],
        "links": []
    });

    assert!(import_comfyui(&payload, "missing-node-id").is_err());
}

#[test]
fn comfyui_import_treats_unknown_port_types_as_any_like_python() {
    let payload = json!({
        "version": 1,
        "nodes": [
            {"id": 1, "type": "Source", "inputs": [], "outputs": [{"name": "image", "type": "IMAGE"}]},
            {"id": 2, "type": "Sink", "inputs": [{"name": "text", "type": "STRING"}], "outputs": []}
        ],
        "links": [{
            "id": 1, "origin_id": 1, "origin_slot": 0,
            "target_id": 2, "target_slot": 0, "type": "IMAGE"
        }]
    });

    assert!(import_comfyui(&payload, "unknown-port-types").is_ok());
}

#[test]
fn trigger_policy_aliases_and_stable_ids_match_boundary_contract() {
    let document = canonicalize_document(&json!({
        "format": "lamtools.workflow", "version": 2,
        "resource": {"name": "contract"}, "graph": {"nodes": [], "links": []},
        "triggers": [{"kind": "manual"}, {"type": "interval", "seconds": 5}],
        "policies": {"timeout_seconds": 10, "permissions": ["read"]}
    }))
    .unwrap();
    assert_eq!(document["triggers"][0]["type"], "manual");
    assert_eq!(document["triggers"][1]["every_seconds"], 5);
    assert_eq!(document["policies"]["permissions"], json!(["read"]));
    assert_eq!(
        stable_id("port", &["wf", "node", "out", "value"]),
        stable_id("port", &["wf", "node", "out", "value"])
    );
}

#[test]
fn errors_remain_structured_for_callers() {
    let error = canonicalize_document(&json!({"format": "wrong", "version": 1})).unwrap_err();
    let _: WorkflowDocumentError = error.clone();
    assert!(!error.message().is_empty());
}
