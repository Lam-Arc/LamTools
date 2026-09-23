//! Internal, synchronous V2 DAG execution slice.
//!
//! This runner has no queue, persistence, retries, permissions, side effects,
//! or host exposure. Only `content`, `passthrough`, `template`, `merge`, and
//! `join` are built in. A trusted host may register an additional node kind
//! through `WorkflowNodeExecutor`; dangerous built-in kinds remain refused.
//! Link expressions, lazy ports, branching, and non-abort error policies are
//! rejected before any node executes.

use crate::workflow_data_packet::WorkflowDataPacket;
use crate::workflow_document::{canonicalize_document, compile_document};
use serde_json::{Map, Value};
use std::collections::{BTreeMap, BTreeSet};
use std::sync::atomic::{AtomicBool, Ordering};

#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
#[error("{0}")]
pub struct WorkflowRunnerError(pub String);

type Result<T> = std::result::Result<T, WorkflowRunnerError>;

fn error(message: impl Into<String>) -> WorkflowRunnerError {
    WorkflowRunnerError(message.into())
}

fn field<'a>(value: &'a Value, key: &str, label: &str) -> Result<&'a Value> {
    value
        .get(key)
        .ok_or_else(|| error(format!("{label}.{key} is missing")))
}

fn string<'a>(value: &'a Value, label: &str) -> Result<&'a str> {
    value
        .as_str()
        .ok_or_else(|| error(format!("{label} must be a string")))
}

#[derive(Debug, Clone, PartialEq)]
pub struct NodeResult {
    pub status: NodeStatus,
    /// Output port ID to legacy JSON value. No result is fabricated on failure.
    pub outputs: BTreeMap<String, Value>,
    pub error: Option<String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NodeStatus {
    Done,
    Failed,
    Cancelled,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RunStatus {
    Done,
    Failed,
    Cancelled,
}

#[derive(Debug, Clone, PartialEq)]
pub struct RunResult {
    pub status: RunStatus,
    pub nodes: BTreeMap<String, NodeResult>,
    /// Interface output name to JSON value; one output is unwrapped, matching
    /// the Python runner's V2 projection.
    pub output: Option<Value>,
    pub error: Option<String>,
}

/// Trusted extension boundary. Inputs and outputs are validated packets, so
/// an executor cannot accidentally pass a malformed marked packet onward.
pub trait WorkflowNodeExecutor {
    fn supports(&self, type_id: &str) -> bool;
    fn execute(
        &self,
        type_id: &str,
        params: &Value,
        inputs: &BTreeMap<String, WorkflowDataPacket>,
    ) -> std::result::Result<BTreeMap<String, WorkflowDataPacket>, String>;
}

pub struct NoExternalNodes;

impl WorkflowNodeExecutor for NoExternalNodes {
    fn supports(&self, _: &str) -> bool {
        false
    }
    fn execute(
        &self,
        _: &str,
        _: &Value,
        _: &BTreeMap<String, WorkflowDataPacket>,
    ) -> std::result::Result<BTreeMap<String, WorkflowDataPacket>, String> {
        Err("no external node executor registered".into())
    }
}

#[derive(Clone)]
struct Port {
    id: String,
    name: String,
    data_type: String,
    default: Option<Value>,
    required: bool,
}

fn ports(node: &Value, direction: &str) -> Result<Vec<Port>> {
    let id = string(field(node, "id", "node")?, "node.id")?;
    let values = field(node, "ports", "node")?
        .as_array()
        .ok_or_else(|| error("node.ports must be an array"))?;
    values
        .iter()
        .filter(|p| p["direction"] == direction)
        .map(|p| {
            Ok(Port {
                id: string(field(p, "id", "port")?, "port.id")?.into(),
                name: string(field(p, "name", "port")?, "port.name")?.into(),
                data_type: string(field(p, "data_type", "port")?, "port.data_type")?.into(),
                default: p.get("default").cloned(),
                required: p["required"].as_bool().unwrap_or(false),
            })
        })
        .collect::<Result<Vec<_>>>()
        .map_err(|e| error(format!("node {id}: {e}")))
}

fn check_type(value: Value, data_type: &str, label: &str) -> Result<Value> {
    let kind = data_type.trim().to_ascii_lowercase();
    let accepted = match kind.as_str() {
        "any" | "*" => true,
        "string" | "str" | "text" => value.is_string(),
        "number" | "int" | "integer" | "float" => value.is_number(),
        "boolean" | "bool" => value.is_boolean(),
        "object" | "dict" => value.is_object(),
        "array" | "list" => value.is_array(),
        _ => {
            return Err(error(format!(
                "{label} uses unsupported data type {data_type:?}"
            )))
        }
    };
    if accepted {
        Ok(value)
    } else {
        Err(error(format!("{label} expected {data_type}, got {value}")))
    }
}

fn coerce_linked(value: Value, target_type: &str) -> Value {
    // The V2 compiler accepts number/boolean -> string links. Match the
    // Python binder's JSON spelling for those two declared conversions.
    if matches!(
        target_type.trim().to_ascii_lowercase().as_str(),
        "string" | "str" | "text"
    ) && (value.is_number() || value.is_boolean())
    {
        Value::String(value.to_string())
    } else {
        value
    }
}

fn active_expression(value: Option<&Value>) -> bool {
    value.is_some_and(|v| !v.is_null() && v.as_str() != Some(""))
}

fn builtin(kind: &str) -> bool {
    matches!(
        kind,
        "content" | "passthrough" | "template" | "merge" | "join"
    )
}

fn forbidden(kind: &str) -> bool {
    matches!(
        kind,
        "ai" | "model"
            | "agent"
            | "command"
            | "script"
            | "subgraph"
            | "wait_event"
            | "approval"
            | "condition"
    )
}

fn preflight(document: &Value, prompt: &Value, executor: &dyn WorkflowNodeExecutor) -> Result<()> {
    if document["policies"]
        .as_object()
        .is_some_and(|policies| !policies.is_empty())
    {
        return Err(error(
            "workflow policies are unsupported by the synchronous runner",
        ));
    }
    for node in document["graph"]["nodes"]
        .as_array()
        .ok_or_else(|| error("graph.nodes must be an array"))?
    {
        let id = string(field(node, "id", "node")?, "node.id")?;
        let kind = string(
            field(field(node, "type", "node")?, "id", "node.type")?,
            "node.type.id",
        )?;
        if forbidden(kind) || (!builtin(kind) && !executor.supports(kind)) {
            return Err(error(format!(
                "node {id} has unsupported executor kind {kind:?}"
            )));
        }
        if node["type"]["version"].as_i64() != Some(1) {
            return Err(error(format!("node {id} type version is unsupported")));
        }
        if node["execution"]["on_error"]["strategy"]
            .as_str()
            .is_some_and(|s| s != "abort")
        {
            return Err(error(format!("node {id} error strategy is unsupported")));
        }
        if node["execution"]["permissions"]
            .as_array()
            .is_some_and(|permissions| !permissions.is_empty())
        {
            return Err(error(format!(
                "node {id} permissions require a host capability gate"
            )));
        }
        for port in node["ports"]
            .as_array()
            .ok_or_else(|| error("node.ports must be an array"))?
        {
            if port["lazy"] == true {
                return Err(error(format!("node {id} has an unsupported lazy port")));
            }
            // Recognize every declared type before execution, even if a port
            // never receives a value during this run.
            let ty = port["data_type"].as_str().unwrap_or("any");
            if !matches!(
                ty.to_ascii_lowercase().as_str(),
                "any"
                    | "*"
                    | "string"
                    | "str"
                    | "text"
                    | "number"
                    | "int"
                    | "integer"
                    | "float"
                    | "boolean"
                    | "bool"
                    | "object"
                    | "dict"
                    | "array"
                    | "list"
            ) {
                return Err(error(format!("node {id} has unsupported data type {ty:?}")));
            }
        }
        if kind == "template"
            && node["params"].as_object().is_some_and(|p| {
                ["template", "text", "content"]
                    .iter()
                    .find_map(|k| p.get(*k))
                    .is_some_and(|value| !value.is_string())
            })
        {
            return Err(error(format!(
                "node {id} uses an unsupported template expression"
            )));
        }
    }
    for link in document["graph"]["links"]
        .as_array()
        .ok_or_else(|| error("graph.links must be an array"))?
    {
        if active_expression(link.get("transform")) || active_expression(link.get("condition")) {
            return Err(error(format!(
                "link {} uses an unsupported transform or condition",
                link["id"]
            )));
        }
    }
    for input in document["interface"]["inputs"]
        .as_array()
        .ok_or_else(|| error("interface.inputs must be an array"))?
    {
        if let Some(target) = input.get("target") {
            let node_id = string(&target["node_id"], "input target node_id")?;
            let port_id = string(&target["port_id"], "input target port_id")?;
            if prompt["nodes"][node_id]["inputs"][port_id]
                .get("links")
                .is_some()
            {
                return Err(error(format!(
                    "interface input {} targets linked port {node_id}.{port_id}",
                    input["name"]
                )));
            }
        }
    }
    if prompt["format"] != "lamtools.execution-prompt" || prompt["version"] != 1 {
        return Err(error("unsupported execution prompt"));
    }
    Ok(())
}

/// Validate the static execution contract without evaluating inputs or nodes.
/// Hosts can use this to reject unsupported graphs before starting execution.
pub fn validate_document(document: &Value, executor: &dyn WorkflowNodeExecutor) -> Result<()> {
    let canonical = canonicalize_document(document).map_err(|e| error(e.to_string()))?;
    let prompt = compile_document(&canonical).map_err(|e| error(e.to_string()))?;
    preflight(&canonical, &prompt, executor)
}

fn render_template(template: &str, inputs: &BTreeMap<String, Value>) -> String {
    let mut result = String::new();
    let mut remaining = template;
    while let Some(start) = remaining.find("{{") {
        result.push_str(&remaining[..start]);
        let rest = &remaining[start + 2..];
        let Some(end) = rest.find("}}") else {
            result.push_str(&remaining[start..]);
            return result;
        };
        let key = rest[..end].trim();
        let value = inputs.get(key).unwrap_or(&Value::Null);
        if !value.is_null() {
            result.push_str(value.as_str().unwrap_or(&value.to_string()));
        }
        remaining = &rest[end + 2..];
    }
    result.push_str(remaining);
    result
}

fn run_builtin(
    kind: &str,
    node: &Value,
    inputs: &BTreeMap<String, Value>,
) -> Result<BTreeMap<String, Value>> {
    let outputs = ports(node, "out")?;
    let ordered_inputs = ports(node, "in")?
        .into_iter()
        .filter_map(|port| inputs.get(&port.name).cloned())
        .collect::<Vec<_>>();
    let params = &node["params"];
    let fallback = ordered_inputs
        .first()
        .cloned()
        .or_else(|| params.get("value").cloned())
        .unwrap_or(Value::Null);
    let selected = match kind {
        "template" => {
            let raw = params
                .get("template")
                .or_else(|| params.get("text"))
                .or_else(|| params.get("content"));
            let template = raw.and_then(Value::as_str).unwrap_or("");
            Value::String(render_template(template, inputs))
        }
        "merge" => ordered_inputs
            .iter()
            .flat_map(|v| v.as_array().cloned().unwrap_or_else(|| vec![v.clone()]))
            .next()
            .ok_or_else(|| error("merge has no active input"))?,
        "join" => Value::Object(inputs.iter().map(|(k, v)| (k.clone(), v.clone())).collect()),
        _ => fallback.clone(),
    };
    let mut result = BTreeMap::new();
    for port in outputs {
        let value = match kind {
            "content" => port.default.unwrap_or(Value::Null),
            "passthrough" => inputs
                .get(&port.name)
                .cloned()
                .unwrap_or_else(|| fallback.clone()),
            _ => selected.clone(),
        };
        result.insert(port.id, value);
    }
    Ok(result)
}

/// Execute a canonical V2 document through its compiled, deterministic DAG.
/// `inputs` are named by interface input name (or `node_id.port_id` for an
/// orphaned port). Cancellation is observed before each node.
pub fn run_document(
    document: &Value,
    inputs: &Map<String, Value>,
    executor: &dyn WorkflowNodeExecutor,
    cancellation: Option<&AtomicBool>,
) -> Result<RunResult> {
    let document = canonicalize_document(document).map_err(|e| error(e.to_string()))?;
    let prompt = compile_document(&document).map_err(|e| error(e.to_string()))?;
    preflight(&document, &prompt, executor)?;
    let mut nodes_by_id = BTreeMap::new();
    for node in document["graph"]["nodes"]
        .as_array()
        .ok_or_else(|| error("graph.nodes must be an array"))?
    {
        nodes_by_id.insert(string(&node["id"], "node.id")?.to_owned(), node);
    }
    let mut seeds: BTreeMap<(String, String), Value> = BTreeMap::new();
    let interface = &document["interface"];
    let mut names = BTreeSet::new();
    for input in interface["inputs"]
        .as_array()
        .ok_or_else(|| error("interface.inputs must be an array"))?
    {
        let name = string(&input["name"], "interface input name")?;
        if !names.insert(name.to_owned()) {
            return Err(error(format!("duplicate interface input name {name:?}")));
        }
        let value = inputs.get(name).or_else(|| input.get("default"));
        let Some(value) = value else {
            if input["required"] == true {
                return Err(error(format!("required workflow input is missing: {name}")));
            }
            continue;
        };
        let value = check_type(
            value.clone(),
            input["data_type"].as_str().unwrap_or("any"),
            name,
        )?;
        if let Some(target) = input.get("target") {
            let node_id = string(&target["node_id"], "input target node_id")?;
            let port_id = string(&target["port_id"], "input target port_id")?;
            if seeds
                .insert((node_id.into(), port_id.into()), value)
                .is_some()
            {
                return Err(error(format!(
                    "multiple interface inputs target {node_id}.{port_id}"
                )));
            }
        }
    }
    let mut values: BTreeMap<(String, String), Value> = BTreeMap::new();
    let mut states = BTreeMap::new();
    let order = prompt["order"]
        .as_array()
        .ok_or_else(|| error("prompt.order must be an array"))?;
    for id_value in order {
        let id = string(id_value, "prompt.order entry")?;
        if cancellation.is_some_and(|flag| flag.load(Ordering::SeqCst)) {
            states.insert(
                id.into(),
                NodeResult {
                    status: NodeStatus::Cancelled,
                    outputs: BTreeMap::new(),
                    error: None,
                },
            );
            return Ok(RunResult {
                status: RunStatus::Cancelled,
                nodes: states,
                output: None,
                error: None,
            });
        }
        let node = nodes_by_id
            .get(id)
            .ok_or_else(|| error(format!("prompt references unknown node {id}")))?;
        let kind = string(&node["type"]["id"], "node type")?;
        let prompt_node = &prompt["nodes"][id];
        let mut bound = BTreeMap::new();
        for port in ports(node, "in")? {
            let binding = prompt_node["inputs"].get(&port.id);
            let raw = if let Some(links) = binding
                .and_then(|b| b.get("links"))
                .and_then(Value::as_array)
            {
                let mut linked = Vec::new();
                for link in links {
                    let source = (
                        string(&link["node_id"], "link node_id")?.to_owned(),
                        string(&link["port_id"], "link port_id")?.to_owned(),
                    );
                    linked.push(
                        values
                            .get(&source)
                            .ok_or_else(|| {
                                error(format!(
                                    "source output {}.{} is unavailable",
                                    source.0, source.1
                                ))
                            })?
                            .clone(),
                    );
                }
                Some(if linked.len() == 1 {
                    linked.remove(0)
                } else {
                    Value::Array(linked)
                })
            } else {
                seeds
                    .get(&(id.into(), port.id.clone()))
                    .cloned()
                    .or_else(|| binding.and_then(|b| b.get("literal")).cloned())
                    .or_else(|| inputs.get(&format!("{id}.{}", port.id)).cloned())
            };
            match raw {
                Some(value) => {
                    let value = if binding
                        .and_then(|b| b.get("links"))
                        .and_then(Value::as_array)
                        .is_some_and(|l| l.len() > 1)
                    {
                        value // Python aggregates multiple links, regardless of declared scalar type.
                    } else {
                        check_type(
                            if binding.and_then(|b| b.get("links")).is_some() {
                                coerce_linked(value, &port.data_type)
                            } else {
                                value
                            },
                            &port.data_type,
                            &format!("{id}.{}", port.name),
                        )?
                    };
                    bound.insert(port.name, value);
                }
                None if port.required => {
                    return Err(error(format!(
                        "required node input is missing: {id}.{}",
                        port.id
                    )))
                }
                None => {}
            }
        }
        let result = if builtin(kind) {
            run_builtin(kind, node, &bound)
        } else {
            let packets = bound
                .iter()
                .map(|(name, value)| {
                    WorkflowDataPacket::from_legacy(value)
                        .map(|packet| (name.clone(), packet))
                        .map_err(|e| error(e.to_string()))
                })
                .collect::<Result<BTreeMap<_, _>>>()?;
            executor
                .execute(kind, &node["params"], &packets)
                .map_err(error)
                .and_then(|packet_outputs| {
                    packet_outputs
                        .into_iter()
                        .map(|(port_id, packet)| {
                            let checked = WorkflowDataPacket::from_value(&packet.to_value())
                                .map_err(|e| error(e.to_string()))?;
                            // Legacy JSON can represent only item.json. Preserve
                            // the packet envelope when references or lineage are
                            // present so that no metadata disappears at this seam.
                            let has_metadata = checked.items.iter().any(|item| {
                                item.binary.is_some()
                                    || !item.paired.is_empty()
                                    || !item.lineage.is_empty()
                            });
                            Ok((
                                port_id,
                                if has_metadata {
                                    checked.to_value()
                                } else {
                                    checked.to_legacy()
                                },
                            ))
                        })
                        .collect()
                })
        };
        let outputs = match result {
            Ok(outputs) => outputs,
            Err(cause) => {
                let message = format!("Node '{id}' failed: {cause}");
                states.insert(
                    id.into(),
                    NodeResult {
                        status: NodeStatus::Failed,
                        outputs: BTreeMap::new(),
                        error: Some(cause.to_string()),
                    },
                );
                return Ok(RunResult {
                    status: RunStatus::Failed,
                    nodes: states,
                    output: None,
                    error: Some(message),
                });
            }
        };
        let declared = ports(node, "out")?;
        let allowed: BTreeSet<_> = declared.iter().map(|port| port.id.as_str()).collect();
        if let Some(unknown) = outputs.keys().find(|key| !allowed.contains(key.as_str())) {
            let message = format!("Node '{id}' returned undeclared output {unknown:?}");
            states.insert(
                id.into(),
                NodeResult {
                    status: NodeStatus::Failed,
                    outputs: BTreeMap::new(),
                    error: Some(message.clone()),
                },
            );
            return Ok(RunResult {
                status: RunStatus::Failed,
                nodes: states,
                output: None,
                error: Some(message),
            });
        }
        for port in &declared {
            if !outputs.contains_key(&port.id) {
                let message = format!("Node '{id}' omitted output {:?}", port.id);
                states.insert(
                    id.into(),
                    NodeResult {
                        status: NodeStatus::Failed,
                        outputs: BTreeMap::new(),
                        error: Some(message.clone()),
                    },
                );
                return Ok(RunResult {
                    status: RunStatus::Failed,
                    nodes: states,
                    output: None,
                    error: Some(message),
                });
            }
        }
        for port in declared {
            let value = match check_type(
                outputs[&port.id].clone(),
                &port.data_type,
                &format!("{id}.{}", port.name),
            ) {
                Ok(value) => value,
                Err(cause) => {
                    let message = format!("Node '{id}' failed: {cause}");
                    states.insert(
                        id.into(),
                        NodeResult {
                            status: NodeStatus::Failed,
                            outputs: BTreeMap::new(),
                            error: Some(cause.to_string()),
                        },
                    );
                    return Ok(RunResult {
                        status: RunStatus::Failed,
                        nodes: states,
                        output: None,
                        error: Some(message),
                    });
                }
            };
            values.insert((id.into(), port.id), value);
        }
        states.insert(
            id.into(),
            NodeResult {
                status: NodeStatus::Done,
                outputs,
                error: None,
            },
        );
    }
    let mut projected = Map::new();
    for output in interface["outputs"]
        .as_array()
        .ok_or_else(|| error("interface.outputs must be an array"))?
    {
        let name = string(&output["name"], "interface output name")?;
        let source = &output["source"];
        let key = (
            string(&source["node_id"], "output node_id")?.to_owned(),
            string(&source["port_id"], "output port_id")?.to_owned(),
        );
        let value = values
            .get(&key)
            .ok_or_else(|| error(format!("interface output {name} is unavailable")))?;
        projected.insert(name.into(), value.clone());
    }
    let output = match projected.len() {
        0 => {
            let linked: BTreeSet<_> = document["graph"]["links"]
                .as_array()
                .unwrap()
                .iter()
                .map(|l| {
                    (
                        l["source"]["node_id"].as_str().unwrap_or("").to_owned(),
                        l["source"]["port_id"].as_str().unwrap_or("").to_owned(),
                    )
                })
                .collect();
            let mut terminals = Map::new();
            for ((node_id, port_id), value) in
                values.iter().filter(|(key, _)| !linked.contains(*key))
            {
                let node = nodes_by_id
                    .get(node_id)
                    .ok_or_else(|| error(format!("unknown terminal node {node_id}")))?;
                let port_name = ports(node, "out")?
                    .into_iter()
                    .find(|port| port.id == *port_id)
                    .ok_or_else(|| error(format!("unknown terminal output {node_id}.{port_id}")))?
                    .name;
                terminals.insert(format!("{node_id}.{port_name}"), value.clone());
            }
            if terminals.len() == 1 {
                terminals.values().next().cloned()
            } else if terminals.is_empty() {
                None
            } else {
                Some(Value::Object(terminals))
            }
        }
        1 => projected.values().next().cloned(),
        _ => Some(Value::Object(projected)),
    };
    Ok(RunResult {
        status: RunStatus::Done,
        nodes: states,
        output,
        error: None,
    })
}
