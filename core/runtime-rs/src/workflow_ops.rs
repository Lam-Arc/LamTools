//! The native document-only Workflow operation boundary.
//!
//! The host owns both the store root and the optional project scope. Request
//! payloads can select a workflow, but cannot select a filesystem location.

use crate::workflow_document::{
    canonicalize_document, compile_document, export_comfyui, import_comfyui, is_v2_document,
    document_from_workflow_def, semantic_graph, workflow_def_from_document,
    WorkflowDocumentError,
};
use crate::workflow_runner::{
    run_document, validate_document, NoExternalNodes, NodeStatus, RunStatus,
};
use crate::workflow_store::{
    WorkflowRuntimeBucket, WorkflowStore, WorkflowStoreError,
};
use serde_json::{json, Value};
use std::collections::{BTreeMap, HashMap};
use std::path::Path;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, OnceLock};
use thiserror::Error;
use uuid::Uuid;

const MAX_QUEUE_ITEMS: usize = 500;
const TERMINAL_QUEUE_STATUSES: &[&str] = &["completed", "failed", "cancelled"];

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

#[derive(Clone)]
struct ActiveRun {
    thread_id: String,
    cancellation: Arc<AtomicBool>,
}

fn active_runs() -> &'static Mutex<HashMap<String, ActiveRun>> {
    static RUNS: OnceLock<Mutex<HashMap<String, ActiveRun>>> = OnceLock::new();
    RUNS.get_or_init(|| Mutex::new(HashMap::new()))
}

struct ActiveRunGuard(String);

impl Drop for ActiveRunGuard {
    fn drop(&mut self) {
        if let Ok(mut runs) = active_runs().lock() {
            runs.remove(&self.0);
        }
    }
}

fn register_active_run(
    run_id: &str,
    thread_id: &str,
) -> WorkflowOperationResult<(Arc<AtomicBool>, ActiveRunGuard)> {
    let mut runs = active_runs()
        .lock()
        .map_err(|_| WorkflowOperationError::Invalid("workflow run registry is unavailable".into()))?;
    if runs.contains_key(run_id) {
        return Err(WorkflowOperationError::Invalid(format!(
            "workflow run is already active: {run_id}"
        )));
    }
    let cancellation = Arc::new(AtomicBool::new(false));
    runs.insert(
        run_id.to_owned(),
        ActiveRun {
            thread_id: thread_id.to_owned(),
            cancellation: Arc::clone(&cancellation),
        },
    );
    Ok((cancellation, ActiveRunGuard(run_id.to_owned())))
}

fn cancel_active_run(thread_id: &str, run_id: &str) -> bool {
    let Ok(runs) = active_runs().lock() else {
        return false;
    };
    let matches = runs.iter().filter(|(id, run)| {
        (run_id.is_empty() || id.as_str() == run_id)
            && (thread_id.is_empty() || run.thread_id == thread_id)
    });
    let mut cancelled = false;
    for (_, run) in matches {
        run.cancellation.store(true, Ordering::SeqCst);
        cancelled = true;
    }
    cancelled
}

fn active_run_exists(run_id: &str) -> bool {
    active_runs()
        .lock()
        .map(|runs| runs.contains_key(run_id))
        .unwrap_or(false)
}

fn run_workflow(
    store: &WorkflowStore,
    params: &Value,
    project_root: Option<&Path>,
) -> WorkflowOperationResult<Value> {
    let permissions = params.get("permissions").or_else(|| {
        params
            .get("metadata")
            .and_then(|metadata| metadata.get("runtime_permissions"))
    });
    if permissions.is_some_and(|value| {
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
        "continuation",
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
    let (cancellation, _active_run) = register_active_run(&run_id, &thread_id)?;
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

fn timestamp() -> String {
    chrono::Utc::now().to_rfc3339()
}

fn create_workflow(
    store: &WorkflowStore,
    params: &Value,
    project_root: Option<&Path>,
) -> WorkflowOperationResult<Value> {
    let document = document_from_workflow_def(params)?;
    let name = document["resource"]["name"].as_str().unwrap_or("");
    if store.get(name, project_root)?.is_some() {
        return Err(WorkflowOperationError::Invalid(format!(
            "Workflow already exists: {name}"
        )));
    }
    if store
        .get_by_id(
            document["resource"]["id"].as_str().unwrap_or(""),
            project_root,
        )?
        .is_some()
    {
        return Err(WorkflowOperationError::Invalid(
            "workflow id already exists".into(),
        ));
    }
    saved_payload(store.save_document(&document, project_root, Some(0))?)
}

fn rename_workflow(
    store: &WorkflowStore,
    params: &Value,
    project_root: Option<&Path>,
) -> WorkflowOperationResult<Value> {
    let new_name = text_field(params, &["new_name", "newName"]);
    if new_name.is_empty() {
        return Err(WorkflowOperationError::Invalid(
            "new_name is required".into(),
        ));
    }
    let mut document = find_document(store, params, project_root)?;
    document["resource"]["name"] = Value::String(new_name);
    saved_payload(store.save_document(
        &document,
        project_root,
        expected_revision(params)?,
    )?)
}

fn set_workflow_exposed(
    store: &WorkflowStore,
    params: &Value,
    project_root: Option<&Path>,
    exposed: bool,
) -> WorkflowOperationResult<Value> {
    let mut document = find_document(store, params, project_root)?;
    document["exposure"]["enabled"] = Value::Bool(exposed);
    saved_payload(store.save_document(
        &document,
        project_root,
        expected_revision(params)?,
    )?)
}

fn grouped_workflows(
    store: &WorkflowStore,
    project_root: Option<&Path>,
) -> WorkflowOperationResult<Value> {
    let mut groups = BTreeMap::<String, Vec<Value>>::new();
    for document in store.list(project_root)? {
        let workflow = workflow_def_from_document(&document)?;
        let root = document["resource"]["work_root"]
            .as_str()
            .unwrap_or_default()
            .to_owned();
        groups.entry(root).or_default().push(workflow);
    }
    Ok(json!({ "groups": groups }))
}

fn builtin_node_schemas() -> BTreeMap<String, Value> {
    let definitions = [
        (
            "content",
            "Content",
            "Emit a constant JSON-compatible value",
            "workflow/data",
            json!({"required": {}, "optional": {}}),
            json!({"output": {"type":"any", "default":""}}),
            "content",
        ),
        (
            "passthrough",
            "Pass Through",
            "Pass an input value to the output",
            "workflow/data",
            json!({"required": {}, "optional": {"value":{"type":"any"}}}),
            json!({"output":{"type":"any"}}),
            "passthrough",
        ),
        (
            "template",
            "Template",
            "Render a text template from named inputs",
            "workflow/transform",
            json!({"required": {}, "optional": {"values":{"type":"object"}}}),
            json!({"output":{"type":"string"}}),
            "template",
        ),
        (
            "merge",
            "Merge",
            "Emit the first active input",
            "workflow/control",
            json!({"required": {}, "optional": {"values":{"type":"any"}}}),
            json!({"output":{"type":"any"}}),
            "merge",
        ),
        (
            "join",
            "Join",
            "Collect active named inputs into one object",
            "workflow/control",
            json!({"required": {}, "optional": {"values":{"type":"any"}}}),
            json!({"output":{"type":"object"}}),
            "join",
        ),
    ];
    definitions
        .into_iter()
        .map(|(id, title, description, category, input, output, executor)| {
            (
                id.to_owned(),
                json!({
                    "name": id,
                    "type_id": id,
                    "title": title,
                    "display_name": title,
                    "description": description,
                    "category": category,
                    "input": input,
                    "output": output,
                    "output_name": ["output"],
                    "output_is_list": [false],
                    "executor": executor,
                    "plugin_id": "workflow",
                    "builtin": true,
                    "pure": true,
                    "deterministic": true,
                    "type_version": 1,
                    "version": 1,
                    "visible": true,
                    "hidden": false,
                    "deprecated": false,
                    "legacy": false,
                }),
            )
        })
        .collect()
}

fn builtin_node_info(params: &Value) -> WorkflowOperationResult<Value> {
    let schemas = builtin_node_schemas();
    let requested = text_field(params, &["name", "node_type", "nodeType"]);
    let result = if requested.is_empty() {
        schemas
    } else {
        let schema = schemas.get(&requested).ok_or_else(|| {
            WorkflowOperationError::NotFound(format!("workflow node type: {requested}"))
        })?;
        BTreeMap::from([(requested, schema.clone())])
    };
    Ok(json!({ "node_types": result, "object_info": result }))
}

fn public_workflow_value(value: &Value) -> Value {
    match value {
        Value::Object(object) => {
            let mut public = serde_json::Map::new();
            for (key, nested) in object {
                let mut normalized = String::new();
                for character in key.chars() {
                    if character.is_ascii_uppercase() {
                        normalized.push('_');
                        normalized.push(character.to_ascii_lowercase());
                    } else {
                        normalized.push(if character == '-' { '_' } else { character });
                    }
                }
                let private = normalized.ends_with("_password")
                    || normalized.ends_with("_secret")
                    || normalized.ends_with("_token")
                    || normalized.ends_with("_api_key")
                    || matches!(
                        normalized.as_str(),
                        "api_key" | "apikey" | "analysis" | "reasoning" | "thinking"
                    );
                if !private {
                    public.insert(key.clone(), public_workflow_value(nested));
                }
            }
            Value::Object(public)
        }
        Value::Array(items) => {
            Value::Array(items.iter().map(public_workflow_value).collect())
        }
        _ => value.clone(),
    }
}

fn queue_record_by_id<'a>(records: &'a [Value], queue_id: &str, run_id: &str) -> Option<&'a Value> {
    if !queue_id.is_empty() {
        if let Some(item) = records
            .iter()
            .find(|item| item["queue_id"].as_str() == Some(queue_id))
        {
            return Some(item);
        }
    }
    if !run_id.is_empty() {
        return records
            .iter()
            .find(|item| item["run_id"].as_str() == Some(run_id));
    }
    None
}

fn queue_payload(item: &Value) -> Value {
    public_workflow_value(item)
}

fn queue_envelope(item: Value) -> Value {
    let item = queue_payload(&item);
    json!({
        "queue": item,
        "item": item,
        "queue_id": item["queue_id"],
        "run_id": item["run_id"],
    })
}

fn queue_matches(item: &Value, params: &Value) -> bool {
    let workflow_id = text_field(params, &["workflow_id", "workflowId"]);
    let workflow_name = text_field(params, &["name", "workflow_name", "workflowName"]);
    let work_root = text_field(params, &["work_root", "workRoot"]);
    let status = field(params, &["status"]);
    let id_matches = workflow_id.is_empty()
        || item["workflow_id"].as_str() == Some(workflow_id.as_str());
    let name_matches = workflow_name.is_empty()
        || item["workflow_name"].as_str() == Some(workflow_name.as_str());
    let root_matches = work_root.is_empty()
        || item["work_root"].as_str() == Some(work_root.as_str());
    let status_matches = status.is_none_or(|expected| {
        if let Some(expected) = expected.as_str() {
            item["status"].as_str() == Some(expected)
        } else if let Some(expected) = expected.as_array() {
            expected.iter().any(|status| item["status"] == *status)
        } else {
            false
        }
    });
    id_matches && name_matches && root_matches && status_matches
}

fn requested_limit(params: &Value) -> WorkflowOperationResult<Option<usize>> {
    let Some(raw) = field(params, &["limit"]) else {
        return Ok(None);
    };
    let value = raw
        .as_u64()
        .or_else(|| raw.as_str().and_then(|text| text.trim().parse::<u64>().ok()))
        .ok_or_else(|| WorkflowOperationError::Invalid("limit must be a non-negative integer".into()))?;
    Ok(Some((value as usize).min(MAX_QUEUE_ITEMS)))
}

fn queue_list(
    store: &WorkflowStore,
    params: &Value,
    project_root: Option<&Path>,
    history: bool,
) -> WorkflowOperationResult<Value> {
    let include_history = params
        .get("include_history")
        .or_else(|| params.get("includeHistory"))
        .and_then(Value::as_bool)
        .unwrap_or(true);
    let include_active = params
        .get("include_active")
        .or_else(|| params.get("includeActive"))
        .and_then(Value::as_bool)
        .unwrap_or(false);
    let limit = requested_limit(params)?;
    let mut items = store.runtime_records(WorkflowRuntimeBucket::Queue, project_root)?;
    items.retain(|item| {
        if !queue_matches(item, params) {
            return false;
        }
        if history {
            include_active
                || field(params, &["status"]).is_some()
                || TERMINAL_QUEUE_STATUSES.contains(&item["status"].as_str().unwrap_or(""))
                || item["status"] == "paused"
        } else {
            include_history
                || !TERMINAL_QUEUE_STATUSES.contains(&item["status"].as_str().unwrap_or(""))
        }
    });
    items.sort_by(|a, b| {
        a["created_at"]
            .as_str()
            .unwrap_or_default()
            .cmp(b["created_at"].as_str().unwrap_or_default())
            .then_with(|| {
                a["queue_id"]
                    .as_str()
                    .unwrap_or_default()
                    .cmp(b["queue_id"].as_str().unwrap_or_default())
            })
    });
    if let Some(limit) = limit {
        items.truncate(limit);
    }
    let items = items.iter().map(queue_payload).collect::<Vec<_>>();
    Ok(if history {
        json!({ "history": items, "items": items })
    } else {
        json!({ "queue": items, "items": items })
    })
}

fn enqueue_workflow(
    store: &WorkflowStore,
    params: &Value,
    project_root: Option<&Path>,
) -> WorkflowOperationResult<Value> {
    let document = find_document(store, params, project_root)?;
    let workflow_id = document["resource"]["id"].as_str().unwrap_or_default();
    let workflow_name = document["resource"]["name"].as_str().unwrap_or_default();
    let queue_id = text_field(params, &["queue_id", "queueId"]);
    let queue_id = if queue_id.is_empty() {
        format!("wfq_{}", Uuid::new_v4().simple())
    } else {
        queue_id
    };
    let run_id = text_field(params, &["run_id", "runId"]);
    let run_id = if run_id.is_empty() {
        format!("workflow_run_{}", Uuid::new_v4().simple())
    } else {
        run_id
    };
    let thread_id = text_field(params, &["thread_id", "threadId"]);
    let thread_id = if thread_id.is_empty() {
        session_id(&document)
    } else {
        thread_id
    };
    let inputs = match params.get("inputs") {
        None | Some(Value::Null) => json!({}),
        Some(Value::Object(inputs)) => Value::Object(inputs.clone()),
        Some(_) => {
            return Err(WorkflowOperationError::Invalid(
                "workflow inputs must be an object".into(),
            ))
        }
    };
    let created_at = timestamp();
    let item = json!({
        "queue_id": queue_id,
        "id": queue_id,
        "workflow_id": workflow_id,
        "workflow_revision": document["resource"]["revision"],
        "workflow_name": workflow_name,
        "name": workflow_name,
        "work_root": document["resource"]["work_root"],
        "thread_id": thread_id,
        "run_id": run_id,
        "inputs": inputs,
        "status": "queued",
        "priority": 0,
        "created_at": created_at,
        "updated_at": created_at,
        "started_at": Value::Null,
        "finished_at": Value::Null,
        "max_steps": Value::Null,
        "start_node": Value::Null,
        "single_node": Value::Null,
        "prior_values": {},
        "prior_node_states": {},
        "result": Value::Null,
        "error": "",
        "metadata": params.get("metadata").cloned().unwrap_or_else(|| json!({})),
    });
    let queue_id = item["queue_id"].as_str().unwrap_or_default().to_owned();
    let run_id = item["run_id"].as_str().unwrap_or_default().to_owned();
    let (accepted, is_new) = store.mutate_runtime_records(
        WorkflowRuntimeBucket::Queue,
        project_root,
        |items| {
            if let Some(existing) = queue_record_by_id(items, &queue_id, &run_id) {
                return (existing.clone(), false);
            }
            items.push(item.clone());
            if items.len() > MAX_QUEUE_ITEMS {
                let remove_count = items.len() - MAX_QUEUE_ITEMS;
                items.drain(0..remove_count);
            }
            (item.clone(), true)
        },
    )?;
    if !is_new {
        return Ok(queue_envelope(accepted));
    }
    let started_at = timestamp();
    let _ = store.mutate_runtime_records(
        WorkflowRuntimeBucket::Queue,
        project_root,
        |items| {
            if let Some(item) = items.iter_mut().find(|item| {
                item["queue_id"].as_str() == Some(queue_id.as_str())
            }) {
                item["status"] = Value::String("running".into());
                item["started_at"] = Value::String(started_at.clone());
                item["updated_at"] = Value::String(started_at.clone());
            }
        },
    )?;
    let mut run_params = params.clone();
    if let Some(object) = run_params.as_object_mut() {
        object.insert("workflow_id".into(), Value::String(workflow_id.into()));
        object.insert("thread_id".into(), Value::String(thread_id));
        object.insert("run_id".into(), Value::String(run_id.clone()));
    }
    let result = run_workflow(store, &run_params, project_root);
    let finished_at = timestamp();
    let (status, run, error) = match result {
        Ok(response) => {
            let raw_status = response["run"]["status"].as_str().unwrap_or("failed");
            let status = match raw_status {
                "done" => "completed",
                "cancelled" => "cancelled",
                "failed" => "failed",
                _ => "failed",
            };
            (status, response["run"].clone(), String::new())
        }
        Err(error) => (
            "failed",
            json!({
                "status": "failed",
                "output": Value::Null,
                "node_states": {},
                "values": {},
                "cache": {},
                "error": error.to_string(),
                "run_id": run_id,
                "steps_remaining": 0,
            }),
            error.to_string(),
        ),
    };
    let updated = store.mutate_runtime_records(
        WorkflowRuntimeBucket::Queue,
        project_root,
        |items| {
            let Some(item) = items
                .iter_mut()
                .find(|item| item["queue_id"].as_str() == Some(queue_id.as_str()))
            else {
                return None;
            };
            item["status"] = Value::String(status.into());
            item["updated_at"] = Value::String(finished_at.clone());
            item["finished_at"] = Value::String(finished_at.clone());
            item["result"] = run.clone();
            item["error"] = Value::String(error.clone());
            Some(item.clone())
        },
    )?;
    Ok(queue_envelope(updated.unwrap_or(accepted)))
}

fn cancel_queue_item(
    store: &WorkflowStore,
    params: &Value,
    project_root: Option<&Path>,
) -> WorkflowOperationResult<Value> {
    let queue_id = text_field(params, &["queue_id", "queueId", "id"]);
    let run_id = text_field(params, &["run_id", "runId"]);
    if queue_id.is_empty() && run_id.is_empty() {
        return Err(WorkflowOperationError::Invalid(
            "queue_id or run_id is required".into(),
        ));
    }
    let existing = store
        .runtime_records(WorkflowRuntimeBucket::Queue, project_root)?
        .into_iter()
        .find(|item| queue_record_by_id(std::slice::from_ref(item), &queue_id, &run_id).is_some())
        .ok_or_else(|| WorkflowOperationError::NotFound("workflow queue item".into()))?;
    let status = existing["status"].as_str().unwrap_or_default();
    let cancellation_requested = if status == "running" {
        cancel_active_run(
            existing["thread_id"].as_str().unwrap_or_default(),
            existing["run_id"].as_str().unwrap_or_default(),
        )
    } else {
        false
    };
    let cancelled_at = timestamp();
    let updated = store.mutate_runtime_records(
        WorkflowRuntimeBucket::Queue,
        project_root,
        |items| {
            let Some(item) = items.iter_mut().find(|item| {
                (queue_id.is_empty() || item["queue_id"].as_str() == Some(queue_id.as_str()))
                    && (run_id.is_empty() || item["run_id"].as_str() == Some(run_id.as_str()))
            }) else {
                return None;
            };
            if item["status"] == "queued" {
                item["status"] = Value::String("cancelled".into());
                item["error"] = Value::String("cancelled".into());
                item["finished_at"] = Value::String(cancelled_at.clone());
                item["updated_at"] = Value::String(cancelled_at.clone());
                item["result"] = json!({
                    "status":"cancelled", "output":Value::Null, "node_states":{},
                    "values":{}, "cache":{}, "error":"cancelled",
                    "run_id":item["run_id"], "steps_remaining":0,
                });
            }
            Some(item.clone())
        },
    )?;
    let item = updated.ok_or_else(|| WorkflowOperationError::NotFound("workflow queue item".into()))?;
    let mut envelope = queue_envelope(item);
    envelope["cancelled"] = Value::Bool(
        envelope["queue"]["status"] == "cancelled" || cancellation_requested,
    );
    envelope["cancellation_requested"] = Value::Bool(cancellation_requested);
    Ok(envelope)
}

fn clear_queue(
    store: &WorkflowStore,
    params: &Value,
    project_root: Option<&Path>,
) -> WorkflowOperationResult<Value> {
    if params.get("confirm").and_then(Value::as_bool) != Some(true) {
        return Err(WorkflowOperationError::Invalid(
            "clearing workflow queue/history requires confirm=true".into(),
        ));
    }
    let all_items = field(params, &["all", "all_items", "allItems", "clear_all"])
        .and_then(Value::as_bool)
        .unwrap_or(false);
    let mut removed = 0usize;
    store.mutate_runtime_records(
        WorkflowRuntimeBucket::Queue,
        project_root,
        |items| {
            items.retain(|item| {
                let terminal = TERMINAL_QUEUE_STATUSES
                    .contains(&item["status"].as_str().unwrap_or(""));
                let matches_scope = queue_matches(item, params);
                let active_run = item["status"] == "running"
                    && active_run_exists(item["run_id"].as_str().unwrap_or_default());
                let keep = !(matches_scope && (all_items || terminal) && !active_run);
                if !keep {
                    removed += 1;
                }
                keep
            });
        },
    )?;
    Ok(json!({ "cleared": removed, "count": removed, "all": all_items }))
}

fn workflow_cancel(params: &Value) -> WorkflowOperationResult<Value> {
    let thread_id = text_field(params, &["thread_id", "threadId"]);
    let run_id = text_field(params, &["run_id", "runId"]);
    if thread_id.is_empty() {
        return Err(WorkflowOperationError::Invalid("thread_id is required".into()));
    }
    let cancelled = cancel_active_run(&thread_id, &run_id);
    Ok(json!({ "cancelled": cancelled, "thread_id": thread_id, "run_id": run_id }))
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
        "workflow.list_grouped" => grouped_workflows(store, project_root),
        "workflow.create" => create_workflow(store, params, project_root),
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
        "workflow.cancel" => workflow_cancel(params),
        "workflow.rename" => rename_workflow(store, params, project_root),
        "workflow.expose" => set_workflow_exposed(store, params, project_root, true),
        "workflow.unexpose" => set_workflow_exposed(store, params, project_root, false),
        "workflow.object_info" | "workflow.node_types" => builtin_node_info(params),
        "workflow.activation.list" => {
            let _ = find_document(store, params, project_root)?;
            Ok(json!({ "activations": [] }))
        }
        "workflow.activate" | "workflow.deactivate" => Err(WorkflowOperationError::Unsupported(
            "Workflow scheduling requires the Arrange scheduler, which is unavailable in the mobile native host.".into(),
        )),
        "workflow.queue.enqueue" => enqueue_workflow(store, params, project_root),
        "workflow.queue.list" => queue_list(store, params, project_root, false),
        "workflow.queue.history" => queue_list(store, params, project_root, true),
        "workflow.queue.get" => {
            let queue_id = text_field(params, &["queue_id", "queueId", "id"]);
            let run_id = text_field(params, &["run_id", "runId"]);
            if queue_id.is_empty() && run_id.is_empty() {
                return Err(WorkflowOperationError::Invalid(
                    "queue_id or run_id is required".into(),
                ));
            }
            let records = store.runtime_records(WorkflowRuntimeBucket::Queue, project_root)?;
            let item = queue_record_by_id(&records, &queue_id, &run_id)
                .ok_or_else(|| WorkflowOperationError::NotFound("workflow queue item".into()))?;
            Ok(queue_envelope(item.clone()))
        }
        "workflow.queue.cancel" => cancel_queue_item(store, params, project_root),
        "workflow.queue.clear" => clear_queue(store, params, project_root),
        "workflow.human_task.list" => Ok(json!({ "tasks": [], "pending": [], "count": 0 })),
        "workflow.human_task.get"
        | "workflow.human_task.complete"
        | "workflow.human_task.timeout"
        | "workflow.signal" => Err(WorkflowOperationError::Unsupported(
            "Signals and human tasks require wait_event/approval nodes and the full execution backend.".into(),
        )),
        "workflow.pause" | "workflow.resume" => Err(WorkflowOperationError::Unsupported(
            "The synchronous mobile runner does not support pausing or resuming workflow runs.".into(),
        )),
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
    fn import_is_persisted_and_runtime_catalog_is_explicit() {
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
        assert_eq!(
            dispatch(&store, "workflow.queue.list", &json!({}), Some(&project)).unwrap()["queue"],
            json!([])
        );
        std::fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn create_grouped_list_rename_exposure_and_native_node_catalog_work() {
        let (store, root, project) = fixture();
        let created = dispatch(
            &store,
            "workflow.create",
            &json!({ "name":"native", "nodes":[], "edges":[], "work_root":"attacker" }),
            Some(&project),
        )
        .unwrap();
        let id = created["workflow"]["id"].as_str().unwrap();
        assert_eq!(created["workflow"]["work_root"], project.to_string_lossy().as_ref());
        assert_eq!(created["session_id"], format!("workflow:{id}"));

        let grouped = dispatch(&store, "workflow.list_grouped", &json!({}), Some(&project))
            .unwrap();
        assert_eq!(grouped["groups"][project.to_string_lossy().as_ref()][0]["id"], id);

        let renamed = dispatch(
            &store,
            "workflow.rename",
            &json!({ "name":"native", "new_name":"renamed", "expected_revision":1 }),
            Some(&project),
        )
        .unwrap();
        assert_eq!(renamed["workflow"]["name"], "renamed");
        assert_eq!(renamed["workflow"]["revision"], 2);
        let exposed = dispatch(&store, "workflow.expose", &json!({"workflow_id":id}), Some(&project))
            .unwrap();
        assert_eq!(exposed["workflow"]["exposed"], true);
        assert_eq!(
            dispatch(&store, "workflow.unexpose", &json!({"workflow_id":id}), Some(&project))
                .unwrap()["workflow"]["exposed"],
            false
        );

        let info = dispatch(&store, "workflow.object_info", &json!({}), Some(&project)).unwrap();
        for type_id in ["content", "passthrough", "template", "merge", "join"] {
            assert_eq!(info["object_info"][type_id]["type_id"], type_id);
        }
        assert!(info["object_info"].get("command").is_none());
        std::fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn queued_run_is_durable_and_projects_into_queue_and_history_contracts() {
        let (store, root, project) = fixture();
        store
            .save_document(
                &runnable_document("queued", "result", "content"),
                Some(&project),
                None,
            )
            .unwrap();
        let queued = dispatch(
            &store,
            "workflow.queue.enqueue",
            &json!({ "name":"queued", "run_id":"workflow_run_1", "inputs":{} }),
            Some(&project),
        )
        .unwrap();
        assert_eq!(queued["queue"]["status"], "completed");
        assert_eq!(queued["queue"]["result"]["output"], "result");
        assert_eq!(queued["queue"]["workflow_revision"], 1);
        assert_eq!(
            dispatch(
                &store,
                "workflow.queue.list",
                &json!({"include_history":false, "workflow_id":queued["queue"]["workflow_id"]}),
                Some(&project),
            )
            .unwrap()["queue"],
            json!([])
        );
        let history = dispatch(
            &WorkflowStore::new(root.join("home")),
            "workflow.queue.history",
            &json!({"workflow_id":queued["queue"]["workflow_id"]}),
            Some(&project),
        )
        .unwrap();
        assert_eq!(history["history"].as_array().unwrap().len(), 1);
        assert_eq!(history["history"][0]["run_id"], "workflow_run_1");
        assert_eq!(
            dispatch(
                &store,
                "workflow.queue.get",
                &json!({"run_id":"workflow_run_1"}),
                Some(&project),
            )
            .unwrap()["queue"]["status"],
            "completed"
        );
        assert!(matches!(
            dispatch(&store, "workflow.queue.clear", &json!({}), Some(&project)),
            Err(WorkflowOperationError::Invalid(_))
        ));
        assert_eq!(
            dispatch(
                &store,
                "workflow.queue.clear",
                &json!({"confirm":true}),
                Some(&project),
            )
            .unwrap()["count"],
            1
        );
        std::fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn cancellation_registry_and_unavailable_scheduler_wait_controls_are_explicit() {
        let (cancellation, active) = register_active_run("run-cancel", "thread-cancel").unwrap();
        assert_eq!(
            workflow_cancel(&json!({"thread_id":"thread-cancel", "run_id":"run-cancel"}))
                .unwrap()["cancelled"],
            true
        );
        assert!(cancellation.load(Ordering::SeqCst));
        drop(active);

        let (store, root, project) = fixture();
        store
            .save_document(&document("manual"), Some(&project), None)
            .unwrap();
        assert_eq!(
            dispatch(
                &store,
                "workflow.activation.list",
                &json!({"name":"manual"}),
                Some(&project),
            )
            .unwrap()["activations"],
            json!([])
        );
        for method in [
            "workflow.activate",
            "workflow.deactivate",
            "workflow.signal",
            "workflow.pause",
            "workflow.resume",
            "workflow.human_task.complete",
        ] {
            assert!(matches!(
                dispatch(&store, method, &json!({"name":"manual"}), Some(&project)),
                Err(WorkflowOperationError::Unsupported(_))
            ), "{method} should report unsupported on the native host");
        }
        assert_eq!(
            dispatch(&store, "workflow.human_task.list", &json!({}), Some(&project)).unwrap()["tasks"],
            json!([])
        );
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
