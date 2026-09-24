//! Control tools: the task checklist and the question the agent can ask.
//!
//! The desktop's `write_checklist` / `update_checklist` maintain the plan the
//! UI renders as checkboxes, and `question` pauses the run until the user
//! answers. Both are model-facing tools with the same schemas here, so a model
//! that learned them on one host uses them the same way on the other.
use async_trait::async_trait;
use serde_json::{json, Value};
use std::sync::Mutex;

use crate::{DeviceCapabilities, RuntimeError, ToolCall, ToolDefinition, ToolPermission, ToolRuntime};

/// The plan one session is working through, newest state only: the UI renders
/// the current checklist, and the history is in the transcript.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PlanState {
    pub design_summary: String,
    pub files: Vec<String>,
    pub steps: Vec<PlanStep>,
    pub current_step_id: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PlanStep {
    pub id: String,
    pub description: String,
    pub deliverables: Vec<String>,
    pub status: String,
}

impl PlanState {
    fn to_value(&self) -> Value {
        json!({
            "design_summary": self.design_summary,
            "files": self.files,
            "current_step_id": self.current_step_id,
            "steps": self.steps.iter().map(|step| json!({
                "id": step.id,
                "description": step.description,
                "deliverables": step.deliverables,
                "status": step.status,
            })).collect::<Vec<_>>(),
        })
    }

    fn step(&mut self, id: &str) -> Option<&mut PlanStep> {
        self.steps.iter_mut().find(|step| step.id == id)
    }
}

/// The checklist tools and the question tool, sharing one plan.
pub struct PlanTools {
    state: Mutex<PlanState>,
}

impl Default for PlanTools {
    fn default() -> Self {
        Self::new()
    }
}

impl PlanTools {
    pub fn new() -> Self {
        Self {
            state: Mutex::new(PlanState::default()),
        }
    }

    /// The current plan, for hosts that publish it alongside the transcript.
    pub fn snapshot(&self) -> Value {
        self.state
            .lock()
            .map(|state| state.to_value())
            .unwrap_or_else(|_| json!({}))
    }

    fn write_plan(&self, arguments: &Value) -> Result<Value, RuntimeError> {
        let summary = arguments
            .get("design_summary")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .trim()
            .to_owned();
        if summary.is_empty() {
            return Err(RuntimeError::Tool("design_summary is required".into()));
        }
        let steps = plan_steps(arguments.get("steps"))?;
        if steps.is_empty() {
            return Err(RuntimeError::Tool("steps must not be empty".into()));
        }
        let files = string_list(arguments.get("files"));
        let mut state = self
            .state
            .lock()
            .map_err(|_| RuntimeError::Tool("plan state is poisoned".into()))?;
        state.design_summary = summary;
        state.files = files;
        state.current_step_id = steps
            .first()
            .map(|step| step.id.clone())
            .unwrap_or_default();
        state.steps = steps;
        Ok(state.to_value())
    }

    fn update_plan(&self, arguments: &Value) -> Result<Value, RuntimeError> {
        let action = arguments
            .get("action")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .trim()
            .to_owned();
        let mut state = self
            .state
            .lock()
            .map_err(|_| RuntimeError::Tool("plan state is poisoned".into()))?;
        if state.steps.is_empty() && action != "replace_plan" && action != "add_step" {
            return Err(RuntimeError::Tool(
                "no active checklist; call write_checklist first".into(),
            ));
        }
        match action.as_str() {
            "add_step" => {
                let step = plan_step(arguments)?
                    .ok_or_else(|| RuntimeError::Tool("step_id and description are required".into()))?;
                if state.steps.iter().any(|existing| existing.id == step.id) {
                    return Err(RuntimeError::Tool(format!("step {} already exists", step.id)));
                }
                state.steps.push(step);
            }
            "update_step" => {
                let id = step_id(arguments)?;
                let status = arguments
                    .get("status")
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .trim()
                    .to_owned();
                let description = arguments.get("description").and_then(Value::as_str);
                // `deliverables` present-but-empty clears the list; absent keeps it.
                let deliverables = arguments
                    .as_object()
                    .filter(|map| map.contains_key("deliverables"))
                    .map(|_| string_list(arguments.get("deliverables")));
                let step = state
                    .step(&id)
                    .ok_or_else(|| RuntimeError::Tool(format!("step {id} does not exist")))?;
                if let Some(description) = description {
                    step.description = description.trim().to_owned();
                }
                if let Some(deliverables) = deliverables {
                    step.deliverables = deliverables;
                }
                if !status.is_empty() {
                    if !KNOWN_STEP_STATUSES.contains(&status.as_str()) {
                        return Err(RuntimeError::Tool(format!("unknown step status: {status}")));
                    }
                    step.status = status.clone();
                    state.current_step_id = if step.status == "in_progress" {
                        step.id.clone()
                    } else if step.status == "completed" || step.status == "skipped" {
                        // The next unfinished step becomes current, so the panel
                        // shows where the work is without another call.
                        state
                            .steps
                            .iter()
                            .find(|candidate| !matches!(candidate.status.as_str(), "completed" | "skipped"))
                            .map(|candidate| candidate.id.clone())
                            .unwrap_or_default()
                    } else {
                        state.current_step_id.clone()
                    };
                }
            }
            "complete_step" | "block_step" => {
                let id = step_id(arguments)?;
                let reason = arguments.get("reason").and_then(Value::as_str).unwrap_or_default();
                let status = if action == "complete_step" { "completed" } else { "blocked" };
                let step = state
                    .step(&id)
                    .ok_or_else(|| RuntimeError::Tool(format!("step {id} does not exist")))?;
                step.status = status.to_owned();
                if action == "block_step" && !reason.trim().is_empty() {
                    step.description = format!("{}（阻塞：{}）", step.description, reason.trim());
                }
                if action == "complete_step" {
                    state.current_step_id = state
                        .steps
                        .iter()
                        .find(|candidate| !matches!(candidate.status.as_str(), "completed" | "skipped"))
                        .map(|candidate| candidate.id.clone())
                        .unwrap_or_default();
                }
            }
            "split_step" => {
                let id = step_id(arguments)?;
                let replacements = plan_steps(arguments.get("steps"))?;
                if replacements.is_empty() {
                    return Err(RuntimeError::Tool("split requires the replacement steps".into()));
                }
                let index = state
                    .steps
                    .iter()
                    .position(|step| step.id == id)
                    .ok_or_else(|| RuntimeError::Tool(format!("step {id} does not exist")))?;
                state.steps.splice(index..=index, replacements);
            }
            "replace_plan" => {
                let steps = plan_steps(arguments.get("steps"))?;
                if steps.is_empty() {
                    return Err(RuntimeError::Tool("steps must not be empty".into()));
                }
                if let Some(summary) = arguments.get("design_summary").and_then(Value::as_str) {
                    state.design_summary = summary.trim().to_owned();
                }
                if arguments.get("files").is_some() {
                    state.files = string_list(arguments.get("files"));
                }
                state.current_step_id = steps
                    .first()
                    .map(|step| step.id.clone())
                    .unwrap_or_default();
                state.steps = steps;
            }
            other => {
                return Err(RuntimeError::Tool(format!(
                    "unknown checklist action: {other}"
                )));
            }
        }
        Ok(state.to_value())
    }
}

const KNOWN_STEP_STATUSES: [&str; 6] = [
    "pending",
    "in_progress",
    "completed",
    "blocked",
    "skipped",
    "replaced",
];

fn step_id(arguments: &Value) -> Result<String, RuntimeError> {
    let id = arguments
        .get("step_id")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .trim()
        .to_owned();
    if id.is_empty() {
        return Err(RuntimeError::Tool("step_id is required".into()));
    }
    Ok(id)
}

fn string_list(value: Option<&Value>) -> Vec<String> {
    value
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(Value::as_str)
                .map(|item| item.trim())
                .filter(|item| !item.is_empty())
                .map(str::to_owned)
                .collect()
        })
        .unwrap_or_default()
}

fn plan_step(arguments: &Value) -> Result<Option<PlanStep>, RuntimeError> {
    let id = arguments
        .get("id")
        .or_else(|| arguments.get("step_id"))
        .and_then(Value::as_str)
        .unwrap_or_default()
        .trim()
        .to_owned();
    let description = arguments
        .get("description")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .trim()
        .to_owned();
    if id.is_empty() || description.is_empty() {
        return Ok(None);
    }
    Ok(Some(PlanStep {
        id,
        description,
        deliverables: string_list(arguments.get("deliverables")),
        status: arguments
            .get("status")
            .and_then(Value::as_str)
            .filter(|value| KNOWN_STEP_STATUSES.contains(value))
            .unwrap_or("pending")
            .to_owned(),
    }))
}

fn plan_steps(value: Option<&Value>) -> Result<Vec<PlanStep>, RuntimeError> {
    let Some(items) = value.and_then(Value::as_array) else {
        return Ok(Vec::new());
    };
    let mut steps = Vec::new();
    for item in items {
        if let Some(step) = plan_step(item)? {
            steps.push(step);
        }
    }
    Ok(steps)
}

fn checklist_definitions() -> Vec<ToolDefinition> {
    vec![
        ToolDefinition {
            name: "write_checklist".into(),
            description: "Optionally create the agent's planning/progress checklist for the task; simple tasks may skip it. \
                          For complex tasks use 3-7 non-overlapping steps whose deliverables are verifiable sub-items. \
                          Each step becomes a Markdown checkbox in the UI."
                .into(),
            input_schema: json!({
                "type": "object",
                "additionalProperties": false,
                "properties": {
                    "design_summary": {
                        "type": "string",
                        "description": "One short business-language sentence describing the goal."
                    },
                    "files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Files or deliverables expected to change; omit when there are none."
                    },
                    "steps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": false,
                            "properties": {
                                "id": {"type": "string", "description": "Stable id like s1, s2, s3."},
                                "description": {"type": "string", "description": "User-readable action item."},
                                "deliverables": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "Verifiable sub-items produced by this step."
                                }
                            },
                            "required": ["id", "description"]
                        }
                    }
                },
                "required": ["design_summary", "steps"]
            }),
        },
        ToolDefinition {
            name: "update_checklist".into(),
            description: "Update the active structured checklist. Mark a step complete immediately after verifying its \
                          deliverable; do not rewrite the whole checklist for ordinary progress."
                .into(),
            input_schema: json!({
                "type": "object",
                "additionalProperties": false,
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["add_step", "update_step", "split_step", "block_step", "complete_step", "replace_plan"]
                    },
                    "step_id": {"type": "string"},
                    "description": {"type": "string"},
                    "deliverables": {"type": "array", "items": {"type": "string"}},
                    "status": {
                        "type": "string",
                        "enum": ["pending", "in_progress", "completed", "blocked", "skipped", "replaced"],
                        "description": "New status for update_step."
                    },
                    "steps": {"type": "array", "items": {"type": "object"}},
                    "files": {"type": "array", "items": {"type": "string"}},
                    "design_summary": {"type": "string"},
                    "reason": {"type": "string"}
                },
                "required": ["action"]
            }),
        },
    ]
}

fn question_definition() -> ToolDefinition {
    ToolDefinition {
        name: "question".into(),
        description: "Ask the user a question or request confirmation when you need clarification, a decision between \
                      options, or explicit approval before proceeding. The run pauses until the user responds."
            .into(),
        input_schema: json!({
            "type": "object",
            "additionalProperties": false,
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The question or confirmation prompt to present to the user."
                },
                "options": {
                    "type": "array",
                    "description": "Selectable choices. Omit for a simple confirm/deny question.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string", "description": "Short option label."},
                            "description": {"type": "string", "description": "Optional detail."}
                        },
                        "required": ["label"]
                    }
                },
                "context": {
                    "type": "string",
                    "description": "Optional context or background for the question."
                }
            },
            "required": ["question"]
        }),
    }
}

#[async_trait]
impl ToolRuntime for PlanTools {
    fn definitions(&self, _capabilities: &DeviceCapabilities) -> Vec<ToolDefinition> {
        let mut definitions = checklist_definitions();
        definitions.push(question_definition());
        definitions
    }

    fn permission(&self, call: &ToolCall) -> ToolPermission {
        match call.name.as_str() {
            // Writing the plan is bookkeeping; asking is the whole point of the
            // question, so it asks whatever the session preset is.
            "write_checklist" | "update_checklist" => ToolPermission::AutoAllow,
            "question" => ToolPermission::AlwaysAsk,
            _ => ToolPermission::HardBlock,
        }
    }

    async fn execute(&self, call: &ToolCall) -> Result<Value, RuntimeError> {
        match call.name.as_str() {
            "write_checklist" => Ok(json!({
                "ok": true,
                "plan": self.write_plan(&call.arguments)?,
            })),
            "update_checklist" => Ok(json!({
                "ok": true,
                "plan": self.update_plan(&call.arguments)?,
            })),
            "question" => {
                // Reaching here means the answer was already given through the
                // approval flow, which is what the guarded call carries.
                let prompt = call
                    .arguments
                    .get("question")
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .trim()
                    .to_owned();
                if prompt.is_empty() {
                    return Err(RuntimeError::Tool("question is required".into()));
                }
                Ok(json!({
                    "ok": true,
                    "question": prompt,
                    "answer": call
                        .arguments
                        .get("answer")
                        .and_then(Value::as_str)
                        .unwrap_or("answered by the user through the approval prompt"),
                }))
            }
            other => Err(RuntimeError::Tool(format!("unknown control tool: {other}"))),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn call(name: &str, arguments: Value) -> ToolCall {
        ToolCall {
            id: "call-1".into(),
            name: name.into(),
            arguments,
        }
    }

    #[tokio::test]
    async fn writing_and_updating_the_checklist_keeps_one_plan() {
        let tools = PlanTools::new();
        let capabilities = DeviceCapabilities::default();
        let names: Vec<String> = tools
            .definitions(&capabilities)
            .into_iter()
            .map(|definition| definition.name)
            .collect();
        assert_eq!(names, vec!["write_checklist", "update_checklist", "question"]);

        let written = tools
            .execute(&call(
                "write_checklist",
                json!({
                    "design_summary": "对齐移动端",
                    "files": ["a.rs", ""],
                    "steps": [
                        {"id": "s1", "description": "第一步", "deliverables": ["x"]},
                        {"id": "s2", "description": "第二步"},
                    ],
                }),
            ))
            .await
            .unwrap();
        assert_eq!(written["plan"]["design_summary"], "对齐移动端");
        assert_eq!(written["plan"]["files"], json!(["a.rs"]));
        assert_eq!(written["plan"]["current_step_id"], "s1");
        assert_eq!(written["plan"]["steps"][0]["status"], "pending");

        // Completing a step moves the pointer to the next unfinished one, which
        // is what the panel shows as the running step.
        let updated = tools
            .execute(&call(
                "update_checklist",
                json!({"action": "complete_step", "step_id": "s1"}),
            ))
            .await
            .unwrap();
        assert_eq!(updated["plan"]["steps"][0]["status"], "completed");
        assert_eq!(updated["plan"]["current_step_id"], "s2");

        // add_step appends; split_step replaces one step with several.
        let added = tools
            .execute(&call(
                "update_checklist",
                json!({"action": "add_step", "step_id": "s3", "description": "第三步"}),
            ))
            .await
            .unwrap();
        assert_eq!(added["plan"]["steps"].as_array().unwrap().len(), 3);
        let split = tools
            .execute(&call(
                "update_checklist",
                json!({"action": "split_step", "step_id": "s3", "steps": [
                    {"id": "s3a", "description": "第三步之一"},
                    {"id": "s3b", "description": "第三步之二"},
                ]}),
            ))
            .await
            .unwrap();
        let ids: Vec<String> = split["plan"]["steps"]
            .as_array()
            .unwrap()
            .iter()
            .map(|step| step["id"].as_str().unwrap().to_owned())
            .collect();
        assert_eq!(ids, vec!["s1", "s2", "s3a", "s3b"]);

        // replace_plan starts over and can carry a new summary.
        let replaced = tools
            .execute(&call(
                "update_checklist",
                json!({"action": "replace_plan", "design_summary": "新目标", "steps": [
                    {"id": "n1", "description": "新第一步"},
                ]}),
            ))
            .await
            .unwrap();
        assert_eq!(replaced["plan"]["design_summary"], "新目标");
        assert_eq!(replaced["plan"]["steps"].as_array().unwrap().len(), 1);
        assert_eq!(replaced["plan"]["current_step_id"], "n1");
    }

    #[tokio::test]
    async fn malformed_checklist_calls_are_refused_with_a_reason() {
        let tools = PlanTools::new();
        assert!(tools
            .execute(&call("write_checklist", json!({"steps": []})))
            .await
            .is_err());
        assert!(tools
            .execute(&call(
                "write_checklist",
                json!({"design_summary": "x", "steps": []}),
            ))
            .await
            .is_err());
        // Updating before writing is a mistake worth reporting, not a silent
        // empty plan.
        let error = tools
            .execute(&call(
                "update_checklist",
                json!({"action": "complete_step", "step_id": "s1"}),
            ))
            .await
            .unwrap_err();
        assert!(format!("{error}").contains("write_checklist"));
        assert!(tools
            .execute(&call("update_checklist", json!({"action": "explode"})))
            .await
            .is_err());
        assert!(tools
            .execute(&call("question", json!({"question": "  "})))
            .await
            .is_err());
    }

    #[tokio::test]
    async fn the_question_always_asks_and_reports_the_answer() {
        let tools = PlanTools::new();
        assert_eq!(
            tools.permission(&call("question", json!({}))),
            ToolPermission::AlwaysAsk
        );
        assert_eq!(
            tools.permission(&call("write_checklist", json!({}))),
            ToolPermission::AutoAllow
        );
        assert_eq!(
            tools.permission(&call("other", json!({}))),
            ToolPermission::HardBlock
        );
        let answered = tools
            .execute(&call("question", json!({"question": "继续吗？"})))
            .await
            .unwrap();
        assert_eq!(answered["question"], "继续吗？");
        assert!(answered["answer"].as_str().unwrap().contains("approval"));
    }
}
