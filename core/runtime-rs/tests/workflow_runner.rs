use lamtools_runtime::workflow_data_packet::WorkflowDataPacket;
use lamtools_runtime::workflow_runner::{
    run_document, NoExternalNodes, NodeStatus, RunStatus, WorkflowNodeExecutor,
};
use serde_json::{json, Map, Value};
use std::collections::BTreeMap;
use std::sync::atomic::AtomicBool;

fn graph() -> Value {
    json!({
        "format": "lamtools.workflow", "version": 2,
        "resource": {"id": "wf", "name": "Runner"},
        "graph": {
            "nodes": [
                {"id": "source", "type": {"id": "content", "version": 1},
                 "ports": [{"id": "source-out", "name": "text", "direction": "out", "data_type": "string", "default": "hello"}]},
                {"id": "format", "type": {"id": "template", "version": 1},
                 "params": {"template": "{{text}} {{suffix}}"},
                 "ports": [
                     {"id": "format-in", "name": "text", "direction": "in", "data_type": "string"},
                     {"id": "suffix-in", "name": "suffix", "direction": "in", "data_type": "string"},
                     {"id": "format-out", "name": "result", "direction": "out", "data_type": "string"}
                 ]},
                {"id": "end", "type": {"id": "passthrough", "version": 1},
                 "ports": [
                     {"id": "end-in", "name": "result", "direction": "in", "data_type": "string"},
                     {"id": "end-out", "name": "result", "direction": "out", "data_type": "string"}
                 ]}
            ],
            "links": [
                {"id": "a", "source": {"node_id": "source", "port_id": "source-out"}, "target": {"node_id": "format", "port_id": "format-in"}},
                {"id": "b", "source": {"node_id": "format", "port_id": "format-out"}, "target": {"node_id": "end", "port_id": "end-in"}}
            ]
        },
        "interface": {
            "inputs": [{"id": "suffix", "name": "suffix", "data_type": "string", "required": true,
                        "default": "world", "target": {"node_id": "format", "port_id": "suffix-in"}}],
            "outputs": [{"id": "final", "name": "final", "source": {"node_id": "end", "port_id": "end-out"}}]
        }
    })
}

#[test]
fn runs_compiled_dag_with_defaults_explicit_inputs_and_projection() {
    let empty = Map::new();
    let result = run_document(&graph(), &empty, &NoExternalNodes, None).unwrap();
    assert_eq!(result.status, RunStatus::Done);
    assert_eq!(result.output, Some(json!("hello world")));
    assert_eq!(result.nodes.len(), 3);
    assert_eq!(result.nodes["format"].outputs["format-out"], "hello world");
    assert_eq!(result.nodes["end"].status, NodeStatus::Done);

    let mut explicit = Map::new();
    explicit.insert("suffix".into(), json!("Rust"));
    let changed = run_document(&graph(), &explicit, &NoExternalNodes, None).unwrap();
    assert_eq!(changed.output, Some(json!("hello Rust")));

    let mut convertible = graph();
    convertible["graph"]["nodes"][0]["ports"][0]["data_type"] = json!("number");
    convertible["graph"]["nodes"][0]["ports"][0]["default"] = json!(7);
    let converted = run_document(&convertible, &empty, &NoExternalNodes, None).unwrap();
    assert_eq!(converted.output, Some(json!("7 world")));
}

#[test]
fn rejects_missing_required_inputs_and_wrong_types() {
    let mut document = graph();
    document["interface"]["inputs"][0]
        .as_object_mut()
        .unwrap()
        .remove("default");
    let error = run_document(&document, &Map::new(), &NoExternalNodes, None).unwrap_err();
    assert!(error
        .to_string()
        .contains("required workflow input is missing: suffix"));

    let mut wrong = Map::new();
    wrong.insert("suffix".into(), json!(9));
    let error = run_document(&graph(), &wrong, &NoExternalNodes, None).unwrap_err();
    assert!(error.to_string().contains("suffix expected string"));
}

#[test]
fn unsupported_execution_fails_before_side_effects_or_partial_success() {
    let mut document = graph();
    document["graph"]["nodes"][1]["type"]["id"] = json!("command");
    let error = run_document(&document, &Map::new(), &NoExternalNodes, None).unwrap_err();
    assert!(error.to_string().contains("unsupported executor kind"));

    let mut document = graph();
    document["graph"]["links"][0]["transform"] = json!("$.text");
    let error = run_document(&document, &Map::new(), &NoExternalNodes, None).unwrap_err();
    assert!(error
        .to_string()
        .contains("unsupported transform or condition"));

    let mut document = graph();
    document["graph"]["nodes"][1]["params"]["template"] = json!({"format": "expression"});
    let error = run_document(&document, &Map::new(), &NoExternalNodes, None).unwrap_err();
    assert!(error
        .to_string()
        .contains("unsupported template expression"));
}

struct FailingExecutor;

impl WorkflowNodeExecutor for FailingExecutor {
    fn supports(&self, type_id: &str) -> bool {
        type_id == "fixture"
    }

    fn execute(
        &self,
        type_id: &str,
        _: &Value,
        inputs: &BTreeMap<String, WorkflowDataPacket>,
    ) -> std::result::Result<BTreeMap<String, WorkflowDataPacket>, String> {
        assert_eq!(type_id, "fixture");
        assert_eq!(inputs["text"].to_legacy(), json!("hello"));
        Err("fixture failed".into())
    }
}

#[test]
fn trusted_executor_receives_packets_and_failure_remains_visible() {
    let mut document = graph();
    document["graph"]["nodes"][1]["type"]["id"] = json!("fixture");
    let result = run_document(&document, &Map::new(), &FailingExecutor, None).unwrap();
    assert_eq!(result.status, RunStatus::Failed);
    assert_eq!(result.nodes["source"].status, NodeStatus::Done);
    assert_eq!(result.nodes["format"].status, NodeStatus::Failed);
    assert_eq!(
        result.nodes["format"].error.as_deref(),
        Some("fixture failed")
    );
    assert!(result.nodes.get("end").is_none());
    assert_eq!(result.output, None);
}

#[test]
fn cancellation_stops_before_first_node() {
    let cancelled = AtomicBool::new(true);
    let result = run_document(&graph(), &Map::new(), &NoExternalNodes, Some(&cancelled)).unwrap();
    assert_eq!(result.status, RunStatus::Cancelled);
    assert_eq!(result.nodes.len(), 1);
    assert_eq!(result.nodes["source"].status, NodeStatus::Cancelled);
}

#[test]
fn merge_uses_declared_input_order_and_join_collects_named_values() {
    let mut document = graph();
    document["graph"]["nodes"] = json!([
        {"id": "merge", "type": {"id": "merge", "version": 1}, "ports": [
            {"id": "z", "name": "z", "direction": "in", "data_type": "any", "default": "first"},
            {"id": "a", "name": "a", "direction": "in", "data_type": "any", "default": "second"},
            {"id": "out", "name": "selected", "direction": "out", "data_type": "string"}
        ]},
        {"id": "join", "type": {"id": "join", "version": 1}, "ports": [
            {"id": "selected", "name": "selected", "direction": "in", "data_type": "string"},
            {"id": "extra", "name": "extra", "direction": "in", "data_type": "number", "default": 2},
            {"id": "joined", "name": "joined", "direction": "out", "data_type": "object"}
        ]}
    ]);
    document["graph"]["links"] = json!([{
        "id": "merge-join", "source": {"node_id": "merge", "port_id": "out"},
        "target": {"node_id": "join", "port_id": "selected"}
    }]);
    document["interface"] = json!({"inputs": [], "outputs": [{
        "id": "final", "name": "final", "source": {"node_id": "join", "port_id": "joined"}
    }]});
    let result = run_document(&document, &Map::new(), &NoExternalNodes, None).unwrap();
    assert_eq!(result.status, RunStatus::Done);
    assert_eq!(
        result.output,
        Some(json!({"selected": "first", "extra": 2}))
    );
}

struct WrongTypeExecutor;

impl WorkflowNodeExecutor for WrongTypeExecutor {
    fn supports(&self, type_id: &str) -> bool {
        type_id == "fixture"
    }
    fn execute(
        &self,
        _: &str,
        _: &Value,
        _: &BTreeMap<String, WorkflowDataPacket>,
    ) -> std::result::Result<BTreeMap<String, WorkflowDataPacket>, String> {
        Ok(BTreeMap::from([(
            "format-out".into(),
            WorkflowDataPacket::from_legacy(&json!(1)).unwrap(),
        )]))
    }
}

#[test]
fn executor_output_type_error_marks_owning_node_failed() {
    let mut document = graph();
    document["graph"]["nodes"][1]["type"]["id"] = json!("fixture");
    let result = run_document(&document, &Map::new(), &WrongTypeExecutor, None).unwrap();
    assert_eq!(result.status, RunStatus::Failed);
    assert_eq!(result.nodes["format"].status, NodeStatus::Failed);
    assert!(result.nodes["format"]
        .error
        .as_ref()
        .unwrap()
        .contains("expected string"));
    assert_eq!(result.output, None);
}

struct MetadataExecutor;

impl WorkflowNodeExecutor for MetadataExecutor {
    fn supports(&self, type_id: &str) -> bool {
        type_id == "fixture"
    }
    fn execute(
        &self,
        _: &str,
        _: &Value,
        _: &BTreeMap<String, WorkflowDataPacket>,
    ) -> std::result::Result<BTreeMap<String, WorkflowDataPacket>, String> {
        let packet = WorkflowDataPacket::from_value(&json!({
            "format": "lamtools.workflow.data-packet", "version": 1,
            "items": [{"json": "hello", "lineage": ["source"]}]
        }))
        .unwrap();
        Ok(BTreeMap::from([("format-out".into(), packet)]))
    }
}

#[test]
fn trusted_executor_packet_lineage_survives_projection() {
    let mut document = graph();
    document["graph"]["nodes"][1]["type"]["id"] = json!("fixture");
    document["graph"]["nodes"][1]["ports"][2]["data_type"] = json!("any");
    document["graph"]["nodes"][2]["ports"][0]["data_type"] = json!("any");
    document["graph"]["nodes"][2]["ports"][1]["data_type"] = json!("any");
    let result = run_document(&document, &Map::new(), &MetadataExecutor, None).unwrap();
    assert_eq!(result.status, RunStatus::Done);
    let output = result.output.unwrap();
    assert_eq!(output["format"], "lamtools.workflow.data-packet");
    assert_eq!(output["items"][0]["lineage"], json!(["source"]));
}

#[test]
fn terminal_projection_uses_node_and_port_names() {
    let mut document = graph();
    document["interface"]["outputs"] = json!([]);
    document["graph"]["nodes"].as_array_mut().unwrap().push(json!({
        "id": "other", "type": {"id": "content", "version": 1},
        "ports": [{"id": "other-out", "name": "extra", "direction": "out", "data_type": "number", "default": 2}]
    }));
    let result = run_document(&document, &Map::new(), &NoExternalNodes, None).unwrap();
    assert_eq!(result.status, RunStatus::Done);
    assert_eq!(
        result.output,
        Some(json!({"end.result": "hello world", "other.extra": 2}))
    );
}
