//! The native document-only Workflow operation boundary.
//!
//! The host owns both the store root and the optional project scope. Request
//! payloads can select a workflow, but cannot select a filesystem location.

use crate::workflow_document::{
    canonicalize_document, compile_document, export_comfyui, import_comfyui, is_v2_document,
    semantic_graph, workflow_def_from_document, WorkflowDocumentError,
};
use crate::workflow_runner::{
    run_document, validate_document, NoExternalNodes, NodeStatus, RunStatus,
};
use crate::workflow_store::{WorkflowStore, WorkflowStoreError};
use serde_json::{json, Value};
use std::path::Path;
use std::sync::atomic::AtomicBool;
use thiserror::Error;
use uuid::Uuid;

#[derive(Debug, Error)]
pub enum WorkflowOperationError {
    #[error("{0}")]
    Invalid(String),
    #[error("Workflow not found: {0}")]
    NotFound(String),
    #[error("Workflow operation is unavailable without the execution backend: {0}")]
    Unsupported(String),
    #[error(transparent)]
    Document(#[from] WorkflowDocumentError),
    #[error(transparent)]
    Store(#[from] WorkflowStoreError),
}

pub type WorkflowOperationResult<T> = Result<T, WorkflowOperationError>;

fn field<'a>(params: &'a Value, names: &[&str]) -> Option<&'a Value> {
    names
        .iter()
        .find_map(|name| params.get(name).filter(|value| !value.is_null()))
}

fn text_field(params: &Value, names: &[&str]) -> String {
    field(params, names)
        .and_then(Value::as_str)
        .unwrap_or("")
        .trim()
        .to_owned()
}

fn expected_revision(params: &Value) -> WorkflowOperationResult<Option<u64>> {
    let Some(raw) = field(params, &["expected_revision", "expectedRevision"]) else {
        return Ok(None);
    };
    if raw == "" {
        return Ok(None);
    }
    raw.as_u64()
        .or_else(|| {
            raw.as_str()
                .and_then(|text| text.trim().parse::<u64>().ok())
        })
        .map(Some)
        .ok_or_else(|| {
            WorkflowOperationError::Invalid(
                "expected_revision must be a non-negative integer".into(),
            )
        })
}

fn find_document(
    store: &WorkflowStore,
    params: &Value,
    project_root: Option<&Path>,
) -> WorkflowOperationResult<Value> {
    let name = text_field(params, &["name"]);
    let id = text_field(params, &["workflow_id", "workflowId"]);
    if name.is_empty() && id.is_empty() {
        return Err(WorkflowOperationError::Invalid(
            "name or workflow_id is required".into(),
        ));
    }
    let document = if id.is_empty() {
        store.get(&name, project_root)?
    } else {
        store.get_by_id(&id, project_root)?
    };
    document.ok_or_else(|| WorkflowOperationError::NotFound(if id.is_empty() { name } else { id }))
}

fn session_id(document: &Value) -> String {
    format!(
        "workflow:{}",
        document["resource"]["id"].as_str().unwrap_or("")
    )
}

fn saved_payload(document: Value) -> WorkflowOperationResult<Value> {
    let workflow = workflow_def_from_document(&document)?;
    Ok(json!({
        "document": document,
        "workflow": workflow,
        "session_id": session_id(&document),
    }))
}

fn run_workflow(
    store: &WorkflowStore,
    params: &Value,
    project_root: Option<&Path>,
) -> WorkflowOperationResult<Value> {
    if params.get("permissions").is_some_and(|value| {
        value.as_array().is_some_and(|items| !items.is_empty())
            || value.as_object().is_some_and(|items| !items.is_empty())
    }) {
        return Err(WorkflowOperationError::Unsupported(
            "This mobile runner supports built-in nodes only; requested runtime permissions need the full execution backend.".into(),
        ));
    }
    if [
        "prior_values",
        "prior_node_states",
        "continuation_token",
        "continuation_state",
        "start_node",
        "single_node",
        "max_steps",
    ]
    .iter()
    .any(|key| params.get(key).is_some_and(|value| !value.is_null()))
    {
        return Err(WorkflowOperationError::Unsupported(
            "This mobile runner does not support resumed or partial workflow runs yet.".into(),
        ));
    }
    let document = find_document(store, params, project_root)?;
    let inputs = match params.get("inputs") {
        None | Some(Value::Null) => serde_json::Map::new(),
        Some(Value::Object(inputs)) => inputs.clone(),
        Some(_) => {
            return Err(WorkflowOperationError::Invalid(
                "workflow inputs must be an object".into(),
            ))
        }
    };
    validate_document(&document, &NoExternalNodes).map_err(|error| {
        WorkflowOperationError::Unsupported(format!(
            "This workflow cannot run in the mobile built-in runner: {error}"
        ))
    })?;
    let cancellation = AtomicBool::new(false);
    let result = run_document(&document, &inputs, &NoExternalNodes, Some(&cancellation))
        .map_err(|error| WorkflowOperationError::Invalid(error.to_string()))?;
    let mut node_states = serde_json::Map::new();
    let mut values = serde_json::Map::new();
    for (id, node) in &result.nodes {
        let status = match node.status {
            NodeStatus::Done => "done",
            NodeStatus::Failed => "error",
            NodeStatus::Cancelled => "cancelled",
        };
        node_states.insert(
            id.clone(),
            json!({
                "node_id": id,
                "status": status,
                "output": node.outputs,
                "error": node.error,
            }),
        );
        if let Some(declared) = document["graph"]["nodes"].as_array().and_then(|nodes| {
            nodes
                .iter()
                .find(|candidate| candidate["id"].as_str() == Some(id.as_str()))
        }) {
            if let Some(ports) = declared["ports"].as_array() {
                for port in ports.iter().filter(|port| port["direction"] == "out") {
                    let Some(port_id) = port["id"].as_str() else {
                        continue;
                    };
                    let Some(port_name) = port["name"].as_str() else {
                        continue;
                    };
                    if let Some(value) = node.outputs.get(port_id) {
                        values.insert(format!("{id}.{port_name}"), value.clone());
                    }
                }
            }
        }
    }
    let status = match result.status {
        RunStatus::Done => "done",
        RunStatus::Failed => "failed",
        RunStatus::Cancelled => "cancelled",
    };
    let run_id = text_field(params, &["run_id", "runId"]);
    let run_id = if run_id.is_empty() {
        Uuid::new_v4().to_string()
    } else {
        run_id
    };
    let thread_id = text_field(params, &["thread_id", "threadId"]);
    let thread_id = if thread_id.is_empty() {
        session_id(&document)
    } else {
        thread_id
    };
    Ok(json!({
        "thread_id": thread_id,
        "run_id": run_id,
        "run": {
            "status": status,
            "output": result.output,
            "node_states": node_states,
            "values": values,
            "cache": {},
            "error": result.error.unwrap_or_default(),
            "run_id": run_id,
            "steps_remaining": 0,
        }
    }))
}

/// Dispatch the Python public document/storage slice. The `project_root` is
/// selected by the native host; `work_root` and `workRoot` in `params` are never
/// used as paths. A missing scope means global storage.
pub fn dispatch(
    store: &WorkflowStore,
    method: &str,
    params: &Value,
    project_root: Option<&Path>,
) -> WorkflowOperationResult<Value> {
    if !params.is_object() {
        return Err(WorkflowOperationError::Invalid(
            "workflow params must be an object".into(),
        ));
    }
    match method {
        "workflow.list" => {
            let workflows = store
                .list(project_root)?
                .iter()
                .map(workflow_def_from_document)
                .collect::<Result<Vec<_>, _>>()?;
            Ok(json!({ "workflows": workflows }))
        }
        "workflow.get" => {
            let document = find_document(store, params, project_root)?;
            Ok(json!({
                "workflow": workflow_def_from_document(&document)?,
                "document": document,
                "session_id": session_id(&document),
            }))
        }
        "workflow.document.get" => {
            let document = find_document(store, params, project_root)?;
            Ok(json!({ "document": document, "session_id": session_id(&document) }))
        }
        "workflow.document.save" => {
            let raw = params.get("document").ok_or_else(|| {
                WorkflowOperationError::Invalid(
                    "document must be a canonical lamtools.workflow V2 object".into(),
                )
            })?;
            if !is_v2_document(raw) {
                return Err(WorkflowOperationError::Invalid(
                    "document must be a canonical lamtools.workflow V2 object".into(),
                ));
            }
            let document = canonicalize_document(raw)?;
            saved_payload(store.save_document(
                &document,
                project_root,
                expected_revision(params)?,
            )?)
        }
        "workflow.compile" => {
            let document = match params.get("document").filter(|raw| raw.is_object()) {
                Some(raw) => canonicalize_document(raw)?,
                None => find_document(store, params, project_root)?,
            };
            Ok(json!({ "prompt": compile_document(&document)? }))
        }
        "workflow.semantic" => {
            let document = find_document(store, params, project_root)?;
            let node_ids = field(params, &["node_ids", "nodeIds"])
                .and_then(Value::as_array)
                .map(|items| {
                    items
                        .iter()
                        .map(|item| match item {
                            Value::String(text) => text.clone(),
                            _ => item.to_string(),
                        })
                        .collect::<Vec<_>>()
                })
                .unwrap_or_default();
            let offset = params
                .get("offset")
                .and_then(Value::as_i64)
                .unwrap_or(0)
                .max(0) as usize;
            let limit = params
                .get("limit")
                .and_then(Value::as_i64)
                .unwrap_or(100)
                .max(0) as usize;
            Ok(json!({ "semantic": semantic_graph(&document, Some(&node_ids), offset, limit)? }))
        }
        "workflow.import.comfyui" => {
            let raw = field(params, &["workflow", "document"])
                .filter(|value| value.is_object())
                .ok_or_else(|| {
                    WorkflowOperationError::Invalid(
                        "workflow must be a ComfyUI workflow object".into(),
                    )
                })?;
            let document = import_comfyui(raw, &text_field(params, &["name"]))?;
            saved_payload(store.save_document(
                &document,
                project_root,
                expected_revision(params)?,
            )?)
        }
        "workflow.export.comfyui" => {
            let document = find_document(store, params, project_root)?;
            let version = text_field(params, &["version"]);
            Ok(
                json!({ "workflow": export_comfyui(&document, if version.is_empty() { "1" } else { &version })? }),
            )
        }
        "workflow.run" => run_workflow(store, params, project_root),
        "workflow.delete" => {
            let name = text_field(params, &["name"]);
            if name.is_empty() {
                return Err(WorkflowOperationError::Invalid("name is required".into()));
            }
            Ok(json!({ "deleted": store.delete(&name, project_root)?, "name": name }))
        }
        other if other.starts_with("workflow.") => {
            Err(WorkflowOperationError::Unsupported(other.into()))
        }
        other => Err(WorkflowOperationError::Invalid(format!(
            "unknown workflow operation: {other}"
        ))),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::workflow_document::document_from_workflow_def;
    use uuid::Uuid;

    fn fixture() -> (WorkflowStore, std::path::PathBuf, std::path::PathBuf) {
        let root = std::env::temp_dir().join(format!("workflow-ops-{}", Uuid::new_v4()));
        let project = root.join("project");
        (WorkflowStore::new(root.join("home")), root, project)
    }

    fn document(name: &str) -> Value {
        document_from_workflow_def(&json!({ "name": name, "nodes": [], "edges": [] })).unwrap()
    }

    fn runnable_document(name: &str, value: &str, kind: &str) -> Value {
        document_from_workflow_def(&json!({
            "name": name,
            "nodes": [{
                "id": "source", "kind": kind,
                "ports": [{"id":"out", "name":"out", "direction":"out", "type":"string", "value":value}]
            }],
            "edges": [], "output_port": "source.out"
        })).unwrap()
    }

    #[test]
    fn save_get_list_compile_semantic_export_delete_contract() {
        let (store, root, project) = fixture();
        let first = dispatch(
            &store,
            "workflow.document.save",
            &json!({
                "document": document("first"), "expected_revision": 0,
                "work_root": root.join("attacker").to_string_lossy(),
            }),
            Some(&project),
        )
        .unwrap();
        assert_eq!(first["workflow"]["revision"], 1);
        assert_eq!(
            first["document"]["resource"]["work_root"],
            project.to_string_lossy().as_ref()
        );
        let id = first["workflow"]["id"].as_str().unwrap();
        assert_eq!(first["session_id"], format!("workflow:{id}"));
        assert_eq!(
            dispatch(
                &store,
                "workflow.get",
                &json!({"workflowId": id}),
                Some(&project)
            )
            .unwrap()["workflow"]["name"],
            "first"
        );
        assert_eq!(
            dispatch(
                &store,
                "workflow.document.get",
                &json!({"name":"first"}),
                Some(&project)
            )
            .unwrap()["document"],
            first["document"]
        );
        assert_eq!(
            dispatch(&store, "workflow.list", &json!({}), Some(&project)).unwrap()["workflows"]
                .as_array()
                .unwrap()
                .len(),
            1
        );
        assert!(dispatch(
            &store,
            "workflow.compile",
            &json!({"name":"first"}),
            Some(&project)
        )
        .unwrap()["prompt"]
            .is_object());
        assert!(dispatch(
            &store,
            "workflow.semantic",
            &json!({"name":"first"}),
            Some(&project)
        )
        .unwrap()["semantic"]
            .is_object());
        assert!(dispatch(
            &store,
            "workflow.export.comfyui",
            &json!({"name":"first"}),
            Some(&project)
        )
        .unwrap()["workflow"]
            .is_object());
        assert_eq!(
            dispatch(
                &store,
                "workflow.delete",
                &json!({"name":"first"}),
                Some(&project)
            )
            .unwrap()["deleted"],
            true
        );
        assert!(matches!(
            dispatch(
                &store,
                "workflow.get",
                &json!({"name":"first"}),
                Some(&project)
            ),
            Err(WorkflowOperationError::NotFound(_))
        ));
        std::fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn expected_revision_is_checked_and_global_scope_is_distinct() {
        let (store, root, project) = fixture();
        let original = document("same");
        let global = dispatch(
            &store,
            "workflow.document.save",
            &json!({"document": original, "expectedRevision": "0"}),
            None,
        )
        .unwrap();
        let project_saved = dispatch(
            &store,
            "workflow.document.save",
            &json!({"document": document("same")}),
            Some(&project),
        )
        .unwrap();
        assert_eq!(global["document"]["resource"]["work_root"], "");
        assert_ne!(global["workflow"]["id"], project_saved["workflow"]["id"]);
        let stale = dispatch(
            &store,
            "workflow.document.save",
            &json!({"document": project_saved["document"], "expected_revision": 0}),
            Some(&project),
        );
        assert!(matches!(
            stale,
            Err(WorkflowOperationError::Store(
                WorkflowStoreError::Conflict { .. }
            ))
        ));
        assert!(matches!(
            dispatch(
                &store,
                "workflow.document.save",
                &json!({"document": project_saved["document"], "expected_revision": "bad"}),
                Some(&project)
            ),
            Err(WorkflowOperationError::Invalid(_))
        ));
        assert_eq!(
            dispatch(&store, "workflow.get", &json!({"name":"same"}), None).unwrap()["workflow"]
                ["id"],
            global["workflow"]["id"]
        );
        std::fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn import_is_persisted_and_non_run_execution_operations_remain_unsupported() {
        let (store, root, project) = fixture();
        let imported = dispatch(
            &store,
            "workflow.import.comfyui",
            &json!({
                "name": "foreign", "workflow": {"version": 1, "nodes": [], "links": []}
            }),
            Some(&project),
        )
        .unwrap();
        assert_eq!(imported["workflow"]["name"], "foreign");
        assert!(matches!(
            dispatch(&store, "workflow.queue.list", &json!({}), Some(&project)),
            Err(WorkflowOperationError::Unsupported(_))
        ));
        std::fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn run_executes_supported_builtin_and_returns_shared_ui_contract_in_host_scope() {
        let (store, root, project) = fixture();
        store
            .save_document(&runnable_document("same", "global", "content"), None, None)
            .unwrap();
        store
            .save_document(
                &runnable_document("same", "project", "content"),
                Some(&project),
                None,
            )
            .unwrap();

        let response = dispatch(
            &store,
            "workflow.run",
            &json!({"name":"same", "inputs":{}, "thread_id":"thread-1", "run_id":"run-1", "work_root":"../ignored"}),
            Some(&project),
        ).unwrap();

        assert_eq!(response["thread_id"], "thread-1");
        assert_eq!(response["run_id"], "run-1");
        assert_eq!(response["run"]["run_id"], "run-1");
        assert_eq!(response["run"]["status"], "done");
        assert_eq!(response["run"]["output"], "project");
        assert_eq!(response["run"]["node_states"]["source"]["status"], "done");
        assert_eq!(response["run"]["values"]["source.out"], "project");
        assert!(response["run"]["cache"].is_object());
        std::fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn run_rejects_unsupported_nodes_and_runtime_permissions_before_execution() {
        let (store, root, project) = fixture();
        store
            .save_document(
                &runnable_document("script", "ignored", "script"),
                Some(&project),
                None,
            )
            .unwrap();
        let error = dispatch(
            &store,
            "workflow.run",
            &json!({"name":"script"}),
            Some(&project),
        )
        .unwrap_err();
        assert!(matches!(error, WorkflowOperationError::Unsupported(_)));
        assert!(error.to_string().contains("built-in runner"));

        store
            .save_document(
                &runnable_document("builtin", "ok", "content"),
                Some(&project),
                None,
            )
            .unwrap();
        let error = dispatch(
            &store,
            "workflow.run",
            &json!({"name":"builtin", "permissions":["filesystem.write"]}),
            Some(&project),
        )
        .unwrap_err();
        assert!(matches!(error, WorkflowOperationError::Unsupported(_)));
        assert!(error.to_string().contains("runtime permissions"));
        std::fs::remove_dir_all(root).unwrap();
    }
}
