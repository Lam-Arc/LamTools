use async_trait::async_trait;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    sync::Arc,
    time::Duration,
};

pub const EVENT_SESSION_START: &str = "SessionStart";
pub const EVENT_USER_PROMPT_SUBMIT: &str = "UserPromptSubmit";
pub const EVENT_PRE_TOOL_USE: &str = "PreToolUse";
pub const EVENT_PERMISSION_REQUEST: &str = "PermissionRequest";
pub const EVENT_POST_TOOL_USE: &str = "PostToolUse";
pub const EVENT_POST_TOOL_USE_FAILURE: &str = "PostToolUseFailure";
pub const EVENT_STOP: &str = "Stop";

#[derive(Clone, Debug, Default, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct HookRunContext {
    #[serde(default)]
    pub session_id: String,
    #[serde(default)]
    pub run_id: String,
    #[serde(default)]
    pub cwd: String,
    #[serde(default)]
    pub project_root: String,
    #[serde(default)]
    pub plugin_name: String,
    #[serde(default)]
    pub plugin_root: String,
    #[serde(default)]
    pub plugin_data: String,
    #[serde(default)]
    pub transcript_path: String,
    #[serde(default)]
    pub metadata: Value,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct HookEvent {
    pub event_name: String,
    #[serde(default)]
    pub session_id: String,
    #[serde(default)]
    pub run_id: String,
    #[serde(default)]
    pub turn_id: String,
    #[serde(default)]
    pub cwd: String,
    #[serde(default)]
    pub project_root: String,
    #[serde(default)]
    pub plugin_name: String,
    #[serde(default)]
    pub plugin_root: String,
    #[serde(default)]
    pub plugin_data: String,
    #[serde(default)]
    pub transcript_path: String,
    #[serde(default)]
    pub metadata: Value,
    #[serde(default)]
    pub tool_name: String,
    #[serde(default)]
    pub tool_input: Value,
    #[serde(default)]
    pub tool_call_id: String,
    #[serde(default)]
    pub tool_result: Value,
    #[serde(default)]
    pub error: String,
    #[serde(default)]
    pub error_type: String,
    #[serde(default)]
    pub user_message: String,
    #[serde(default)]
    pub permission_request: Value,
}

impl HookEvent {
    pub fn new(event_name: impl Into<String>, turn_id: &str, context: &HookRunContext) -> Self {
        Self {
            event_name: event_name.into(),
            session_id: context.session_id.clone(),
            run_id: context.run_id.clone(),
            turn_id: turn_id.to_owned(),
            cwd: context.cwd.clone(),
            project_root: context.project_root.clone(),
            plugin_name: context.plugin_name.clone(),
            plugin_root: context.plugin_root.clone(),
            plugin_data: context.plugin_data.clone(),
            transcript_path: context.transcript_path.clone(),
            metadata: context.metadata.clone(),
            ..Default::default()
        }
    }
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct HookDecision {
    #[serde(default = "allow_decision")]
    pub decision: String,
    #[serde(default)]
    pub reason: String,
    #[serde(default)]
    pub additional_context: String,
    pub updated_input: Option<Value>,
    #[serde(default)]
    pub permission_decision: String,
    #[serde(default)]
    pub permission_decision_reason: String,
    pub updated_output: Option<Value>,
    #[serde(default)]
    pub status_message: String,
    #[serde(default)]
    pub audit_events: Vec<Value>,
}

impl Default for HookDecision {
    fn default() -> Self {
        Self {
            decision: allow_decision(),
            reason: String::new(),
            additional_context: String::new(),
            updated_input: None,
            permission_decision: String::new(),
            permission_decision_reason: String::new(),
            updated_output: None,
            status_message: String::new(),
            audit_events: Vec::new(),
        }
    }
}

fn allow_decision() -> String {
    "allow".into()
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct HookHandler {
    #[serde(rename = "type")]
    pub handler_type: String,
    #[serde(default)]
    pub command: String,
    #[serde(default)]
    pub url: String,
    #[serde(default)]
    pub tool: String,
    #[serde(default)]
    pub prompt: String,
    #[serde(default = "default_timeout")]
    pub timeout: f64,
    #[serde(default)]
    pub required: bool,
    #[serde(default)]
    pub status_message: String,
    #[serde(default)]
    pub raw: Value,
}

fn default_timeout() -> f64 {
    10.0
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
pub struct HookDefinition {
    pub id: String,
    pub event: String,
    pub matcher: String,
    pub source: String,
    pub source_name: String,
    pub config_path: String,
    pub plugin_name: String,
    pub plugin_root: String,
    pub handler: HookHandler,
    pub definition_hash: String,
    pub trusted: bool,
    pub status: String,
}

impl HookDefinition {
    pub fn list_item(&self) -> Value {
        serde_json::json!({
            "id": self.id,
            "event": self.event,
            "matcher": self.matcher,
            "source": self.source,
            "source_name": self.source_name,
            "plugin_name": self.plugin_name,
            "config_path": self.config_path,
            "handler_type": self.handler.handler_type,
            "command": self.handler.command,
            "definition_hash": self.definition_hash,
            "trusted": self.trusted,
            "status": self.status,
        })
    }
}

#[derive(Clone, Debug, Default, Deserialize, Serialize, PartialEq)]
pub struct HookListPayload {
    pub hooks: Vec<Value>,
    pub trustable_count: usize,
    pub total_count: usize,
    pub trusted_count: usize,
}

pub struct HookRegistry;

impl HookRegistry {
    #[allow(clippy::too_many_arguments)]
    pub fn load_value(
        config_path: &str,
        source: &str,
        source_name: &str,
        plugin_name: &str,
        plugin_root: &str,
        raw: &Value,
        trusted_hashes: &BTreeSet<String>,
    ) -> Vec<HookDefinition> {
        let Some(hooks) = raw.get("hooks").and_then(Value::as_object) else {
            return Vec::new();
        };
        let mut loaded = Vec::new();
        for (event, groups) in hooks {
            let Some(groups) = groups.as_array() else {
                continue;
            };
            for (group_index, group) in groups.iter().enumerate() {
                let Some(group) = group.as_object() else {
                    continue;
                };
                let matcher = group
                    .get("matcher")
                    .and_then(Value::as_str)
                    .filter(|value| !value.is_empty())
                    .unwrap_or("*")
                    .to_owned();
                let Some(handlers) = group.get("hooks").and_then(Value::as_array) else {
                    continue;
                };
                for (handler_index, raw_handler) in handlers.iter().enumerate() {
                    let Some(handler) = parse_handler(raw_handler) else {
                        continue;
                    };
                    let stable = Value::Object(Map::from_iter([
                        ("config_path".into(), Value::String(config_path.into())),
                        ("event".into(), Value::String(event.clone())),
                        ("handler".into(), raw_handler.clone()),
                        ("matcher".into(), Value::String(matcher.clone())),
                        ("plugin_name".into(), Value::String(plugin_name.into())),
                        ("source".into(), Value::String(source.into())),
                        ("source_name".into(), Value::String(source_name.into())),
                    ]));
                    let definition_hash = stable_hash(&stable);
                    let trusted = trusted_hashes.contains(&definition_hash);
                    loaded.push(HookDefinition {
                        id: format!(
                            "{source}:{source_name}:{event}:{group_index}:{handler_index}:{}",
                            &definition_hash[..12]
                        ),
                        event: event.clone(),
                        matcher: matcher.clone(),
                        source: source.into(),
                        source_name: source_name.into(),
                        config_path: config_path.into(),
                        plugin_name: plugin_name.into(),
                        plugin_root: plugin_root.into(),
                        handler,
                        definition_hash,
                        trusted,
                        status: if trusted { "trusted" } else { "pending_review" }.into(),
                    });
                }
            }
        }
        loaded
    }

    pub fn list_payload(hooks: &[HookDefinition]) -> HookListPayload {
        HookListPayload {
            hooks: hooks.iter().map(HookDefinition::list_item).collect(),
            trustable_count: hooks.iter().filter(|hook| !hook.trusted).count(),
            total_count: hooks.len(),
            trusted_count: hooks.iter().filter(|hook| hook.trusted).count(),
        }
    }
}

fn parse_handler(raw: &Value) -> Option<HookHandler> {
    let object = raw.as_object()?;
    let handler_type = object
        .get("type")
        .and_then(Value::as_str)
        .unwrap_or("command");
    if !matches!(handler_type, "command" | "http" | "mcp" | "prompt") {
        return None;
    }
    let text = |name: &str| {
        object
            .get(name)
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned()
    };
    Some(HookHandler {
        handler_type: handler_type.into(),
        command: text("command"),
        url: text("url"),
        tool: text("tool"),
        prompt: text("prompt"),
        timeout: object
            .get("timeout")
            .and_then(Value::as_f64)
            .filter(|value| value.is_finite() && *value > 0.0)
            .unwrap_or_else(default_timeout),
        required: object
            .get("required")
            .and_then(Value::as_bool)
            .unwrap_or(false),
        status_message: object
            .get("statusMessage")
            .or_else(|| object.get("status_message"))
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned(),
        raw: raw.clone(),
    })
}

pub fn stable_hash(value: &Value) -> String {
    let mut hasher = Sha256::new();
    hasher.update(python_style_json(value).as_bytes());
    format!("{:x}", hasher.finalize())
}

fn python_style_json(value: &Value) -> String {
    match value {
        Value::Null | Value::Bool(_) | Value::Number(_) | Value::String(_) => {
            serde_json::to_string(value).unwrap_or_else(|_| "null".into())
        }
        Value::Array(items) => format!(
            "[{}]",
            items
                .iter()
                .map(python_style_json)
                .collect::<Vec<_>>()
                .join(", ")
        ),
        Value::Object(object) => {
            let sorted = object.iter().collect::<BTreeMap<_, _>>();
            format!(
                "{{{}}}",
                sorted
                    .into_iter()
                    .map(|(key, value)| format!(
                        "{}: {}",
                        serde_json::to_string(key).unwrap_or_else(|_| "\"\"".into()),
                        python_style_json(value)
                    ))
                    .collect::<Vec<_>>()
                    .join(", ")
            )
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct HookCommandRequest {
    pub argv: Vec<String>,
    pub cwd: String,
    pub event_name: String,
    pub plugin_root: String,
    pub stdin: Vec<u8>,
    pub timeout: Duration,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct HookCommandOutput {
    pub exit_code: i32,
    pub stdout: String,
    pub stderr: String,
}

#[async_trait]
pub trait HookCommandRunner: Send + Sync {
    async fn run(&self, request: HookCommandRequest) -> Result<HookCommandOutput, String>;
}

#[async_trait]
pub trait HookMcpCaller: Send + Sync {
    async fn call(&self, tool_name: &str, arguments: Value) -> Result<String, String>;
}

#[async_trait]
pub trait HookExecutor: Send + Sync {
    async fn run(&self, event: HookEvent) -> HookDecision;
}

pub struct HookEngine {
    hooks: Vec<HookDefinition>,
    command_runner: Option<Arc<dyn HookCommandRunner>>,
    mcp_caller: Option<Arc<dyn HookMcpCaller>>,
    http: reqwest::Client,
}

impl HookEngine {
    pub fn new(hooks: Vec<HookDefinition>) -> Self {
        Self {
            hooks,
            command_runner: None,
            mcp_caller: None,
            http: reqwest::Client::new(),
        }
    }

    pub fn with_command_runner(mut self, runner: Arc<dyn HookCommandRunner>) -> Self {
        self.command_runner = Some(runner);
        self
    }

    pub fn with_mcp_caller(mut self, caller: Arc<dyn HookMcpCaller>) -> Self {
        self.mcp_caller = Some(caller);
        self
    }

    async fn run_one(&self, hook: &HookDefinition, event: &HookEvent) -> (HookDecision, Value) {
        match hook.handler.handler_type.as_str() {
            "prompt" => {
                let prompt = expand(&hook.handler.prompt, hook, event, true);
                (
                    HookDecision {
                        additional_context: prompt,
                        ..Default::default()
                    },
                    audit(hook, "completed", None),
                )
            }
            "http" => self.run_http(hook, event).await,
            "mcp" => self.run_mcp(hook, event).await,
            "command" => self.run_command(hook, event).await,
            _ => (
                HookDecision::default(),
                audit(hook, "skipped_unsupported", None),
            ),
        }
    }

    async fn run_http(&self, hook: &HookDefinition, event: &HookEvent) -> (HookDecision, Value) {
        if hook.handler.url.trim().is_empty() {
            return failure(hook, "required http hook missing url", "missing url");
        }
        let request = self
            .http
            .post(&hook.handler.url)
            .timeout(Duration::from_secs_f64(hook.handler.timeout))
            .json(&payload(hook, event))
            .send()
            .await;
        match request {
            Ok(response) if response.status().is_success() => match response.text().await {
                Ok(text) if text.trim().is_empty() => {
                    (HookDecision::default(), audit(hook, "completed", None))
                }
                Ok(text) => parse_result(hook, &text, "completed"),
                Err(error) => failure(hook, "required http hook failed", &error.to_string()),
            },
            Ok(response) => failure(
                hook,
                "required http hook failed",
                &format!("HTTP {}", response.status().as_u16()),
            ),
            Err(error) if error.is_timeout() => {
                required_failure(hook, "required http hook timed out", "timeout")
            }
            Err(error) => failure(hook, "required http hook failed", &error.to_string()),
        }
    }

    async fn run_mcp(&self, hook: &HookDefinition, event: &HookEvent) -> (HookDecision, Value) {
        let Some(caller) = &self.mcp_caller else {
            return required_failure(hook, "required mcp hook unavailable", "unavailable");
        };
        if hook.handler.tool.trim().is_empty() {
            return failure(hook, "required mcp hook missing tool", "missing tool");
        }
        match caller.call(&hook.handler.tool, payload(hook, event)).await {
            Ok(text) if text.trim().is_empty() => {
                (HookDecision::default(), audit(hook, "completed", None))
            }
            Ok(text) => parse_result(hook, &text, "completed"),
            Err(error) => failure(hook, "required mcp hook failed", &error),
        }
    }

    async fn run_command(&self, hook: &HookDefinition, event: &HookEvent) -> (HookDecision, Value) {
        let Some(runner) = &self.command_runner else {
            return required_failure(
                hook,
                "required command hook unavailable on this platform",
                "unavailable",
            );
        };
        let command = expand(&hook.handler.command, hook, event, false);
        let argv = match split_argv(&command) {
            Ok(argv) if !argv.is_empty() => argv,
            Ok(_) => return failure(hook, "required hook has empty command", "empty command"),
            Err(error) => return failure(hook, "required hook has invalid command", &error),
        };
        let stdin = match serde_json::to_vec(&payload(hook, event)) {
            Ok(value) => value,
            Err(error) => return failure(hook, "required hook payload failed", &error.to_string()),
        };
        let output = runner
            .run(HookCommandRequest {
                argv,
                cwd: if event.project_root.is_empty() {
                    event.cwd.clone()
                } else {
                    event.project_root.clone()
                },
                event_name: event.event_name.clone(),
                plugin_root: if hook.plugin_root.is_empty() {
                    event.plugin_root.clone()
                } else {
                    hook.plugin_root.clone()
                },
                stdin,
                timeout: Duration::from_secs_f64(hook.handler.timeout),
            })
            .await;
        match output {
            Ok(output) if output.exit_code == 0 && output.stdout.trim().is_empty() => (
                HookDecision::default(),
                serde_json::json!({
                    "hook_id": hook.id,
                    "status": "completed",
                    "exit_code": output.exit_code,
                    "stderr": output.stderr.lines().next().unwrap_or_default(),
                }),
            ),
            Ok(output) if output.exit_code == 0 => parse_result(hook, &output.stdout, "completed"),
            Ok(output) => failure(
                hook,
                "required hook failed",
                output.stderr.lines().next().unwrap_or("command failed"),
            ),
            Err(error) if error == "timeout" => {
                required_failure(hook, "required hook timed out", "timeout")
            }
            Err(error) => failure(hook, "required hook failed", &error),
        }
    }
}

#[async_trait]
impl HookExecutor for HookEngine {
    async fn run(&self, event: HookEvent) -> HookDecision {
        let mut decision = HookDecision::default();
        let mut current_input = event.tool_input.clone();
        let mut current_output = event.tool_result.clone();
        for hook in self.hooks.iter().filter(|hook| {
            hook.event == event.event_name
                && (hook.matcher.is_empty()
                    || hook.matcher == "*"
                    || hook.matcher == event.tool_name)
        }) {
            if !hook.trusted {
                decision
                    .audit_events
                    .push(audit(hook, "skipped_untrusted", None));
                continue;
            }
            if !hook.handler.status_message.is_empty() {
                decision.status_message = hook.handler.status_message.clone();
            }
            let mut current_event = event.clone();
            current_event.tool_input = current_input.clone();
            current_event.tool_result = current_output.clone();
            let (result, audit_event) = self.run_one(hook, &current_event).await;
            decision.audit_events.push(audit_event);
            if let Some(updated) = result.updated_input {
                merge_object(&mut current_input, updated);
                decision.updated_input = Some(current_input.clone());
            }
            if let Some(updated) = result.updated_output {
                merge_object(&mut current_output, updated);
                decision.updated_output = Some(current_output.clone());
            }
            if !result.additional_context.is_empty() {
                if !decision.additional_context.is_empty() {
                    decision.additional_context.push('\n');
                }
                decision
                    .additional_context
                    .push_str(&result.additional_context);
            }
            if !result.permission_decision.is_empty() {
                decision.permission_decision = result.permission_decision;
                decision.permission_decision_reason = result.permission_decision_reason;
            }
            if !result.status_message.is_empty() {
                decision.status_message = result.status_message;
            }
            if result.decision == "block" {
                decision.decision = "block".into();
                decision.reason = result.reason;
                break;
            }
        }
        decision
    }
}

fn merge_object(target: &mut Value, updated: Value) {
    match (target.as_object_mut(), updated) {
        (Some(target), Value::Object(updated)) => target.extend(updated),
        (_, updated) => *target = updated,
    }
}

fn parse_result(hook: &HookDefinition, text: &str, success_status: &str) -> (HookDecision, Value) {
    let data: Value = match serde_json::from_str(text.trim()) {
        Ok(Value::Object(data)) => Value::Object(data),
        Ok(_) => return invalid_result(hook, "hook returned non-object JSON"),
        Err(error) => return invalid_result(hook, &format!("hook returned invalid JSON: {error}")),
    };
    let text_field = |camel: &str, snake: &str| {
        data.get(camel)
            .or_else(|| data.get(snake))
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned()
    };
    (
        HookDecision {
            decision: if data.get("decision").and_then(Value::as_str) == Some("block") {
                "block".into()
            } else {
                "allow".into()
            },
            reason: text_field("reason", "reason"),
            additional_context: text_field("additionalContext", "additional_context"),
            updated_input: data
                .get("updatedInput")
                .or_else(|| data.get("updated_input"))
                .filter(|value| value.is_object())
                .cloned(),
            permission_decision: text_field("permissionDecision", "permission_decision"),
            permission_decision_reason: text_field(
                "permissionDecisionReason",
                "permission_decision_reason",
            ),
            updated_output: data
                .get("updatedOutput")
                .or_else(|| data.get("updated_output"))
                .filter(|value| value.is_object())
                .cloned(),
            status_message: text_field("statusMessage", "status_message"),
            ..Default::default()
        },
        audit(hook, success_status, None),
    )
}

fn invalid_result(hook: &HookDefinition, error: &str) -> (HookDecision, Value) {
    let mut decision = HookDecision::default();
    if hook.handler.required {
        decision.decision = "block".into();
        decision.reason = "required hook returned invalid JSON".into();
    }
    (decision, audit(hook, "failed", Some(error)))
}

fn failure(hook: &HookDefinition, required_reason: &str, error: &str) -> (HookDecision, Value) {
    let mut decision = HookDecision::default();
    if hook.handler.required {
        decision.decision = "block".into();
        decision.reason = required_reason.into();
    }
    (decision, audit(hook, "failed", Some(error)))
}

fn required_failure(
    hook: &HookDefinition,
    required_reason: &str,
    status: &str,
) -> (HookDecision, Value) {
    let mut decision = HookDecision::default();
    if hook.handler.required {
        decision.decision = "block".into();
        decision.reason = required_reason.into();
    }
    (
        decision,
        audit(
            hook,
            if status == "timeout" {
                "timeout"
            } else {
                "skipped_unavailable"
            },
            None,
        ),
    )
}

fn audit(hook: &HookDefinition, status: &str, error: Option<&str>) -> Value {
    let mut value = serde_json::json!({"hook_id": hook.id, "status": status});
    if let (Some(object), Some(error)) = (value.as_object_mut(), error) {
        object.insert(
            "error".into(),
            Value::String(error.chars().take(200).collect()),
        );
    }
    value
}

fn payload(hook: &HookDefinition, event: &HookEvent) -> Value {
    let mut value = serde_json::json!({
        "event_name": event.event_name,
        "session_id": event.session_id,
        "run_id": event.run_id,
        "turn_id": event.turn_id,
        "cwd": event.cwd,
        "project_root": event.project_root,
        "plugin_name": if hook.plugin_name.is_empty() { &event.plugin_name } else { &hook.plugin_name },
        "plugin_root": if hook.plugin_root.is_empty() { &event.plugin_root } else { &hook.plugin_root },
        "plugin_data": event.plugin_data,
        "transcript_path": event.transcript_path,
        "metadata": event.metadata,
        "tool_name": event.tool_name,
        "tool_input": event.tool_input,
    });
    let object = value.as_object_mut().expect("hook payload is an object");
    for (key, field, present) in [
        (
            "tool_call_id",
            Value::String(event.tool_call_id.clone()),
            !event.tool_call_id.is_empty(),
        ),
        (
            "tool_result",
            event.tool_result.clone(),
            !event.tool_result.is_null(),
        ),
        (
            "error",
            Value::String(event.error.clone()),
            !event.error.is_empty(),
        ),
        (
            "error_type",
            Value::String(event.error_type.clone()),
            !event.error_type.is_empty(),
        ),
        (
            "user_message",
            Value::String(event.user_message.clone()),
            !event.user_message.is_empty(),
        ),
        (
            "permission_request",
            event.permission_request.clone(),
            !event.permission_request.is_null(),
        ),
    ] {
        if present {
            object.insert(key.into(), field);
        }
    }
    value
}

fn expand(template: &str, hook: &HookDefinition, event: &HookEvent, include_user: bool) -> String {
    let plugin_root = if hook.plugin_root.is_empty() {
        &event.plugin_root
    } else {
        &hook.plugin_root
    };
    let mut expanded = template
        .replace("${PLUGIN_ROOT}", plugin_root)
        .replace("${PLUGIN_DATA}", &event.plugin_data)
        .replace("${PROJECT_ROOT}", &event.project_root)
        .replace("${TOOL_NAME}", &event.tool_name)
        .replace("${TOOL_CALL_ID}", &event.tool_call_id)
        .replace("${EVENT_NAME}", &event.event_name);
    if include_user {
        expanded = expanded.replace("${USER_MESSAGE}", &event.user_message);
    }
    expanded
}

fn split_argv(command: &str) -> Result<Vec<String>, String> {
    let mut argv = Vec::new();
    let mut current = String::new();
    let mut quote = None;
    let mut chars = command.chars().peekable();
    while let Some(character) = chars.next() {
        match character {
            '\'' | '"' if quote.is_none() => quote = Some(character),
            value if quote == Some(value) => quote = None,
            '\\' if quote == Some('"') && matches!(chars.peek(), Some('"') | Some('\\')) => {
                if let Some(next) = chars.next() {
                    current.push(next);
                }
            }
            value if value.is_whitespace() && quote.is_none() => {
                if !current.is_empty() {
                    argv.push(std::mem::take(&mut current));
                }
            }
            value => current.push(value),
        }
    }
    if quote.is_some() {
        return Err("unclosed quote".into());
    }
    if !current.is_empty() {
        argv.push(current);
    }
    Ok(argv)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn hooks(raw: Value, trusted: bool) -> Vec<HookDefinition> {
        let first = HookRegistry::load_value(
            "hooks.json",
            "user",
            "config",
            "",
            "",
            &raw,
            &BTreeSet::new(),
        );
        if !trusted {
            return first;
        }
        HookRegistry::load_value(
            "hooks.json",
            "user",
            "config",
            "",
            "",
            &raw,
            &first.into_iter().map(|hook| hook.definition_hash).collect(),
        )
    }

    #[test]
    fn registry_loads_supported_handlers_and_requires_per_definition_trust() {
        let raw = serde_json::json!({
            "hooks": {"PreToolUse": [{"matcher": "write_file", "hooks": [
                {"type": "prompt", "prompt": "Review ${TOOL_NAME}"},
                {"type": "socket", "url": "x"}
            ]}]}
        });
        let pending = hooks(raw.clone(), false);
        assert_eq!(pending.len(), 1);
        assert!(!pending[0].trusted);
        let trusted = hooks(raw, true);
        assert!(trusted[0].trusted);
        assert_eq!(trusted[0].definition_hash.len(), 64);
    }

    #[tokio::test]
    async fn prompt_hooks_chain_input_context_and_blocking() {
        let raw = serde_json::json!({"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [
            {"type": "prompt", "prompt": "First ${TOOL_NAME}"},
            {"type": "prompt", "prompt": "Second ${PROJECT_ROOT}"}
        ]}]}});
        let engine = HookEngine::new(hooks(raw, true));
        let mut event = HookEvent::new(
            "PreToolUse",
            "turn-1",
            &HookRunContext {
                project_root: "/project".into(),
                ..Default::default()
            },
        );
        event.tool_name = "write_file".into();
        let decision = engine.run(event).await;
        assert_eq!(
            decision.additional_context,
            "First write_file\nSecond /project"
        );
        assert_eq!(decision.audit_events.len(), 2);
    }

    #[tokio::test]
    async fn required_command_is_fail_closed_when_platform_has_no_runner() {
        let raw = serde_json::json!({"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [
            {"type": "command", "command": "python check.py", "required": true}
        ]}]}});
        let decision = HookEngine::new(hooks(raw, true))
            .run(HookEvent::new(
                "PreToolUse",
                "turn-1",
                &HookRunContext::default(),
            ))
            .await;
        assert_eq!(decision.decision, "block");
        assert!(decision.reason.contains("unavailable"));
        assert_eq!(decision.audit_events[0]["status"], "skipped_unavailable");
    }

    #[test]
    fn argv_parser_never_invokes_a_shell_or_splits_operators() {
        assert_eq!(
            split_argv("python -c \"print('x; $(touch nope)')\"").unwrap(),
            vec!["python", "-c", "print('x; $(touch nope)')"]
        );
    }
}
