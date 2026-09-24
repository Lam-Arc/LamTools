//! Platform-neutral Sunday Agent runtime.
//!
//! Hosts provide model I/O and device tools.  The agent loop, identity,
//! capability-aware system context and tool-result continuation live here so
//! desktop and mobile cannot drift into separate agents.

use async_trait::async_trait;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{collections::BTreeMap, sync::Arc};

pub mod compaction;
pub mod hooks;
pub mod mcp;
pub mod memory;
pub mod plugin_catalog;
mod profiles;
pub mod project_tools;
pub mod provider;
pub mod skills;
pub mod study;
pub mod study_skills;
pub mod sub_agent;
pub mod workflow_data_packet;
pub mod workflow_document;
pub mod workflow_ops;
pub mod workflow_runner;
pub mod workflow_store;

const MAX_TOOL_ROUNDS: usize = 8;
pub const MAX_MODEL_IMAGE_BYTES: usize = 10 * 1024 * 1024;
pub const MAX_MODEL_IMAGE_TOTAL_BYTES: usize = 20 * 1024 * 1024;
pub const MAX_MODEL_IMAGES: usize = 8;

#[derive(Clone, Debug, Default, Deserialize, Serialize, PartialEq, Eq)]
pub struct DeviceCapabilities {
    pub platform: String,
    pub project_files: bool,
    pub shell: bool,
    pub git: bool,
    pub network: bool,
    pub notifications: bool,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct ToolDefinition {
    pub name: String,
    pub description: String,
    pub input_schema: Value,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct ToolCall {
    pub id: String,
    pub name: String,
    #[serde(default)]
    pub arguments: Value,
}

#[derive(Clone, Copy, Debug, Default, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ToolPermission {
    #[default]
    AutoAllow,
    AskUser,
    HardBlock,
}

#[derive(Clone, Copy, Debug, Default, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum PermissionPreset {
    #[default]
    Ask,
    Auto,
    FullAccess,
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ApprovalDecision {
    ApproveOnce,
    ApproveForSession,
    Deny,
    OtherGuidance,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum ModelTurn {
    Text {
        text: String,
        #[serde(default)]
        reasoning: String,
        #[serde(default)]
        provider_state: Value,
    },
    ToolCalls {
        /// Text the model produced in the same turn before deciding to call
        /// tools.  Providers can return content and tool calls together, and
        /// dropping it here would lose the model's own narration for every
        /// round that ends in a tool call.
        #[serde(default)]
        text: String,
        calls: Vec<ToolCall>,
        #[serde(default)]
        provider_state: Value,
    },
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(tag = "role", rename_all = "snake_case")]
pub enum Message {
    System {
        content: String,
    },
    User {
        content: String,
    },
    UserMultimodal {
        content: String,
        images: Vec<ImageInput>,
    },
    Assistant {
        content: String,
        #[serde(default, rename = "providerState")]
        provider_state: Value,
    },
    AssistantToolCalls {
        /// Narration the model gave before requesting the tools.  Kept so the
        /// transcript and the next request both see what it said.
        #[serde(default)]
        content: String,
        calls: Vec<ToolCall>,
        #[serde(default, rename = "providerState")]
        provider_state: Value,
    },
    Tool {
        tool_call_id: String,
        #[serde(default)]
        name: String,
        content: String,
    },
}

/// A durable reference plus transient image bytes for a model request.
///
/// Hosts persist `attachment_id` and `mime_type`, then rehydrate `data_base64`
/// from their attachment store before replaying history. Omitting the bytes
/// from serialized runtime history avoids copying large payloads into session
/// metadata and approval continuations.
#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
pub struct ImageInput {
    pub attachment_id: String,
    pub mime_type: String,
    #[serde(default, skip_serializing)]
    pub data_base64: String,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct TurnOptions {
    #[serde(default)]
    pub reasoning_level: String,
    pub thinking_budget: Option<u32>,
    pub max_output_tokens: Option<u32>,
    pub temperature: Option<f64>,
    pub context_window: Option<u32>,
    pub compact_trigger_tokens: Option<u32>,
    pub compact_limit_tokens: Option<u32>,
    pub compact_retained_steps: Option<usize>,
    #[serde(default)]
    pub permission_preset: PermissionPreset,
    #[serde(default)]
    pub session_approved_tools: Vec<String>,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct AgentContext {
    #[serde(default)]
    pub global_instructions: String,
    #[serde(default)]
    pub project_instructions: String,
    #[serde(default)]
    pub memory: String,
    #[serde(default)]
    pub mode_context: String,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct TurnRequest {
    #[serde(default)]
    pub turn_id: String,
    pub model_record_id: String,
    pub history: Vec<Message>,
    pub capabilities: DeviceCapabilities,
    #[serde(default)]
    pub context: AgentContext,
    #[serde(default)]
    pub hook_context: hooks::HookRunContext,
    #[serde(default)]
    pub options: TurnOptions,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct TurnResult {
    pub text: String,
    #[serde(default)]
    pub reasoning: String,
    pub runtime_model_id: String,
    pub tool_rounds: usize,
    #[serde(default)]
    pub provider_state: Value,
    #[serde(default)]
    pub session_approved_tools: Vec<String>,
    #[serde(default)]
    pub hook_audit_events: Vec<Value>,
    #[serde(default)]
    pub hook_status_messages: Vec<String>,
    #[serde(default)]
    pub runtime_warnings: Vec<String>,
    #[serde(default)]
    pub runtime_history: Vec<Message>,
    pub compaction: Option<compaction::CompactionReport>,
    pub dreaming: Option<memory::DreamingOutcome>,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct ApprovalRequest {
    pub request_id: String,
    pub tool_call: ToolCall,
    pub message: String,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct ApprovalResponse {
    pub request_id: String,
    pub decision: ApprovalDecision,
    #[serde(default)]
    pub guidance: String,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct TurnContinuation {
    pub turn_id: String,
    pub model_record_id: String,
    pub messages: Vec<Message>,
    pub capabilities: DeviceCapabilities,
    pub options: TurnOptions,
    #[serde(default)]
    pub context: AgentContext,
    #[serde(default)]
    pub hook_context: hooks::HookRunContext,
    #[serde(default)]
    pub hook_audit_events: Vec<Value>,
    #[serde(default)]
    pub hook_status_messages: Vec<String>,
    #[serde(default)]
    pub runtime_warnings: Vec<String>,
    pub tool_rounds: usize,
    pub pending_calls: Vec<ToolCall>,
    pub next_call_index: usize,
    #[serde(default)]
    pub compaction: Option<compaction::CompactionReport>,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(tag = "status", rename_all = "snake_case")]
pub enum TurnProgress {
    Completed {
        result: TurnResult,
    },
    ApprovalRequired {
        request: ApprovalRequest,
        continuation: TurnContinuation,
    },
}

#[derive(Debug, thiserror::Error)]
pub enum RuntimeError {
    #[error("model error: {0}")]
    Model(String),
    #[error("tool error: {0}")]
    Tool(String),
    #[error("tool call limit exceeded")]
    ToolLimit,
    #[error("tool approval required: {0}")]
    ApprovalRequired(String),
}

#[async_trait]
pub trait ModelBackend: Send + Sync {
    async fn complete(
        &self,
        model_record_id: &str,
        messages: &[Message],
        tools: &[ToolDefinition],
        options: &TurnOptions,
    ) -> Result<ModelTurn, RuntimeError>;

    fn runtime_model_id(&self, model_record_id: &str) -> String {
        model_record_id.to_owned()
    }
}

#[async_trait]
impl<M> ModelBackend for Arc<M>
where
    M: ModelBackend + ?Sized,
{
    async fn complete(
        &self,
        model_record_id: &str,
        messages: &[Message],
        tools: &[ToolDefinition],
        options: &TurnOptions,
    ) -> Result<ModelTurn, RuntimeError> {
        (**self)
            .complete(model_record_id, messages, tools, options)
            .await
    }

    fn runtime_model_id(&self, model_record_id: &str) -> String {
        (**self).runtime_model_id(model_record_id)
    }
}

#[async_trait]
pub trait ToolRuntime: Send + Sync {
    fn definitions(&self, capabilities: &DeviceCapabilities) -> Vec<ToolDefinition>;
    fn permission(&self, _call: &ToolCall) -> ToolPermission {
        ToolPermission::AutoAllow
    }
    async fn execute(&self, call: &ToolCall) -> Result<Value, RuntimeError>;
}

#[async_trait]
impl<T> ToolRuntime for Arc<T>
where
    T: ToolRuntime + ?Sized,
{
    fn definitions(&self, capabilities: &DeviceCapabilities) -> Vec<ToolDefinition> {
        (**self).definitions(capabilities)
    }

    fn permission(&self, call: &ToolCall) -> ToolPermission {
        (**self).permission(call)
    }

    async fn execute(&self, call: &ToolCall) -> Result<Value, RuntimeError> {
        (**self).execute(call).await
    }
}

#[async_trait]
pub trait GuidanceSource: Send + Sync {
    async fn drain(&self) -> Vec<String>;
}

pub struct AgentRuntime<M, T> {
    model: M,
    tools: T,
    hooks: Option<Arc<dyn hooks::HookExecutor>>,
    guidance: Option<Arc<dyn GuidanceSource>>,
    progress: Option<Arc<dyn Fn(&'static str) + Send + Sync>>,
    tool_observer: Option<Arc<dyn ToolObserver>>,
}

impl<M, T> AgentRuntime<M, T>
where
    M: ModelBackend,
    T: ToolRuntime,
{
    pub fn new(model: M, tools: T) -> Self {
        Self {
            model,
            tools,
            hooks: None,
            guidance: None,
            progress: None,
            tool_observer: None,
        }
    }

    pub fn with_hook_executor(mut self, hooks: Arc<dyn hooks::HookExecutor>) -> Self {
        self.hooks = Some(hooks);
        self
    }

    pub fn with_guidance_source(mut self, guidance: Arc<dyn GuidanceSource>) -> Self {
        self.guidance = Some(guidance);
        self
    }

    pub fn with_progress(mut self, report: impl Fn(&'static str) + Send + Sync + 'static) -> Self {
        self.progress = Some(Arc::new(report));
        self
    }

    pub fn with_tool_observer(mut self, observer: Arc<dyn ToolObserver>) -> Self {
        self.tool_observer = Some(observer);
        self
    }

    fn report(&self, stage: &'static str) {
        if let Some(report) = &self.progress {
            report(stage);
        }
    }

    pub async fn run_turn(&self, request: TurnRequest) -> Result<TurnResult, RuntimeError> {
        match self.run_turn_progress(request).await? {
            TurnProgress::Completed { result } => Ok(result),
            TurnProgress::ApprovalRequired { request, .. } => {
                Err(RuntimeError::ApprovalRequired(request.request_id))
            }
        }
    }

    pub async fn run_turn_progress(
        &self,
        request: TurnRequest,
    ) -> Result<TurnProgress, RuntimeError> {
        let definitions = self.tools.definitions(&request.capabilities);
        let user_message = request
            .history
            .iter()
            .rev()
            .find_map(|message| match message {
                Message::User { content } => Some(content.clone()),
                Message::UserMultimodal { content, .. } => Some(content.clone()),
                _ => None,
            })
            .unwrap_or_default();
        let mut messages = Vec::with_capacity(request.history.len() + 8);
        messages.push(Message::System {
            content: system_context(&request.capabilities, &definitions, &request.context),
        });
        messages.extend(request.history);
        self.report("runtime_compaction_start");
        let (messages, compaction) = compaction::compact_if_needed(
            &self.model,
            &request.model_record_id,
            messages,
            &request.options,
        )
        .await;
        self.report("runtime_compaction_done");
        let mut continuation = TurnContinuation {
            turn_id: request.turn_id,
            model_record_id: request.model_record_id,
            messages,
            capabilities: request.capabilities,
            options: request.options,
            context: request.context,
            hook_context: request.hook_context,
            hook_audit_events: Vec::new(),
            hook_status_messages: Vec::new(),
            runtime_warnings: Vec::new(),
            tool_rounds: 0,
            pending_calls: Vec::new(),
            next_call_index: 0,
            compaction,
        };
        self.report("runtime_hooks_start");
        for mut event in [
            hooks::HookEvent::new(
                hooks::EVENT_SESSION_START,
                &continuation.turn_id,
                &continuation.hook_context,
            ),
            hooks::HookEvent::new(
                hooks::EVENT_USER_PROMPT_SUBMIT,
                &continuation.turn_id,
                &continuation.hook_context,
            ),
        ] {
            if event.event_name == hooks::EVENT_USER_PROMPT_SUBMIT {
                event.user_message = user_message.clone();
            }
            let decision = self.run_hook(event).await;
            absorb_hook_decision(&mut continuation, &decision);
            if decision.decision == "block" {
                return Err(RuntimeError::Tool(if decision.reason.is_empty() {
                    "turn blocked by hook".into()
                } else {
                    decision.reason
                }));
            }
        }
        self.report("runtime_hooks_done");
        self.continue_turn(continuation, &definitions).await
    }

    pub async fn resume_turn(
        &self,
        mut continuation: TurnContinuation,
        response: ApprovalResponse,
    ) -> Result<TurnProgress, RuntimeError> {
        let definitions = self.tools.definitions(&continuation.capabilities);
        let expected = approval_request(&continuation)?;
        if response.request_id != expected.request_id {
            return Err(RuntimeError::Tool(
                "approval request does not match continuation".into(),
            ));
        }
        let call = continuation.pending_calls[continuation.next_call_index].clone();
        match response.decision {
            ApprovalDecision::ApproveOnce => {
                self.execute_tool_with_hooks(&mut continuation, &call)
                    .await?;
            }
            ApprovalDecision::ApproveForSession => {
                if !continuation
                    .options
                    .session_approved_tools
                    .contains(&call.name)
                {
                    continuation
                        .options
                        .session_approved_tools
                        .push(call.name.clone());
                }
                self.execute_tool_with_hooks(&mut continuation, &call)
                    .await?;
            }
            ApprovalDecision::Deny | ApprovalDecision::OtherGuidance => {
                append_tool_result(
                    &mut continuation.messages,
                    &call,
                    json_object([
                        ("ok", Value::Bool(false)),
                        ("denied", Value::Bool(true)),
                        (
                            "error",
                            Value::String(if response.guidance.trim().is_empty() {
                                "User denied this tool call".into()
                            } else {
                                response.guidance
                            }),
                        ),
                    ]),
                )?;
            }
        }
        continuation.next_call_index += 1;
        self.continue_turn(continuation, &definitions).await
    }

    async fn continue_turn(
        &self,
        mut continuation: TurnContinuation,
        definitions: &[ToolDefinition],
    ) -> Result<TurnProgress, RuntimeError> {
        loop {
            while continuation.next_call_index < continuation.pending_calls.len() {
                let mut call = continuation.pending_calls[continuation.next_call_index].clone();
                let mut pre_event = hooks::HookEvent::new(
                    hooks::EVENT_PRE_TOOL_USE,
                    &continuation.turn_id,
                    &continuation.hook_context,
                );
                pre_event.tool_name = call.name.clone();
                pre_event.tool_call_id = call.id.clone();
                pre_event.tool_input = call.arguments.clone();
                let pre_decision = self.run_hook(pre_event).await;
                absorb_hook_decision(&mut continuation, &pre_decision);
                if let Some(updated_input) = pre_decision.updated_input {
                    call.arguments = updated_input;
                    continuation.pending_calls[continuation.next_call_index] = call.clone();
                }
                if pre_decision.decision == "block" || pre_decision.permission_decision == "deny" {
                    append_tool_result(
                        &mut continuation.messages,
                        &call,
                        json_object([
                            ("ok", Value::Bool(false)),
                            ("blocked", Value::Bool(true)),
                            (
                                "error",
                                Value::String(
                                    if !pre_decision.permission_decision_reason.is_empty() {
                                        pre_decision.permission_decision_reason
                                    } else if !pre_decision.reason.is_empty() {
                                        pre_decision.reason
                                    } else {
                                        "Tool call blocked by hook".into()
                                    },
                                ),
                            ),
                        ]),
                    )?;
                    continuation.next_call_index += 1;
                    continue;
                }
                let hook_ask_user = pre_decision.permission_decision == "ask_user";
                let tool_permission = self.tools.permission(&call);
                match tool_permission {
                    ToolPermission::HardBlock => {
                        append_tool_result(
                            &mut continuation.messages,
                            &call,
                            json_object([
                                ("ok", Value::Bool(false)),
                                ("blocked", Value::Bool(true)),
                                (
                                    "error",
                                    Value::String(format!("Tool '{}' is hard-blocked", call.name)),
                                ),
                            ]),
                        )?;
                        continuation.next_call_index += 1;
                    }
                    ToolPermission::AskUser | ToolPermission::AutoAllow
                        if hook_ask_user
                            || (tool_permission == ToolPermission::AskUser
                                && continuation.options.permission_preset
                                    == PermissionPreset::Ask
                                && !continuation
                                    .options
                                    .session_approved_tools
                                    .contains(&call.name)) =>
                    {
                        let request = approval_request(&continuation)?;
                        let mut permission_event = hooks::HookEvent::new(
                            hooks::EVENT_PERMISSION_REQUEST,
                            &continuation.turn_id,
                            &continuation.hook_context,
                        );
                        permission_event.tool_name = call.name.clone();
                        permission_event.tool_call_id = call.id.clone();
                        permission_event.tool_input = call.arguments.clone();
                        permission_event.permission_request = serde_json::to_value(&request)
                            .map_err(|error| RuntimeError::Tool(error.to_string()))?;
                        let permission_decision = self.run_hook(permission_event).await;
                        absorb_hook_decision(&mut continuation, &permission_decision);
                        if permission_decision.decision == "block"
                            || permission_decision.permission_decision == "deny"
                        {
                            append_tool_result(
                                &mut continuation.messages,
                                &call,
                                json_object([
                                    ("ok", Value::Bool(false)),
                                    ("denied", Value::Bool(true)),
                                    (
                                        "error",
                                        Value::String(if permission_decision.reason.is_empty() {
                                            permission_decision.permission_decision_reason
                                        } else {
                                            permission_decision.reason
                                        }),
                                    ),
                                ]),
                            )?;
                            continuation.next_call_index += 1;
                        } else if permission_decision.permission_decision == "allow" {
                            self.execute_tool_with_hooks(&mut continuation, &call)
                                .await?;
                            continuation.next_call_index += 1;
                        } else {
                            return Ok(TurnProgress::ApprovalRequired {
                                request,
                                continuation,
                            });
                        }
                    }
                    ToolPermission::AutoAllow | ToolPermission::AskUser => {
                        self.execute_tool_with_hooks(&mut continuation, &call)
                            .await?;
                        continuation.next_call_index += 1;
                    }
                }
            }
            if !continuation.pending_calls.is_empty() {
                continuation.tool_rounds += 1;
                continuation.pending_calls.clear();
                continuation.next_call_index = 0;
            }

            if let Some(guidance) = &self.guidance {
                let messages = guidance.drain().await;
                if !messages.is_empty() {
                    continuation.messages.push(Message::System {
                        content: format!("[Late guidance]\n{}", messages.join("\n\n")),
                    });
                }
            }

            self.report("runtime_model_start");
            let model_turn = self
                .model
                .complete(
                    &continuation.model_record_id,
                    &continuation.messages,
                    definitions,
                    &continuation.options,
                )
                .await?;
            self.report("runtime_model_done");
            match model_turn {
                ModelTurn::Text {
                    text,
                    reasoning,
                    provider_state,
                } => {
                    let stop_decision = self
                        .run_hook(hooks::HookEvent::new(
                            hooks::EVENT_STOP,
                            &continuation.turn_id,
                            &continuation.hook_context,
                        ))
                        .await;
                    absorb_hook_decision(&mut continuation, &stop_decision);
                    if stop_decision.decision == "block" {
                        return Err(RuntimeError::Tool(if stop_decision.reason.is_empty() {
                            "turn completion blocked by hook".into()
                        } else {
                            stop_decision.reason
                        }));
                    }
                    continuation.messages.push(Message::Assistant {
                        content: text.clone(),
                        provider_state: provider_state.clone(),
                    });
                    let runtime_history = continuation.messages.iter().skip(1).cloned().collect();
                    return Ok(TurnProgress::Completed {
                        result: TurnResult {
                            text,
                            reasoning,
                            runtime_model_id: self
                                .model
                                .runtime_model_id(&continuation.model_record_id),
                            tool_rounds: continuation.tool_rounds,
                            provider_state,
                            session_approved_tools: continuation.options.session_approved_tools,
                            hook_audit_events: continuation.hook_audit_events,
                            hook_status_messages: continuation.hook_status_messages,
                            runtime_warnings: continuation.runtime_warnings,
                            runtime_history,
                            compaction: continuation.compaction,
                            dreaming: None,
                        },
                    });
                }
                ModelTurn::ToolCalls {
                    text,
                    calls,
                    provider_state,
                } if continuation.tool_rounds < MAX_TOOL_ROUNDS => {
                    continuation.messages.push(Message::AssistantToolCalls {
                        content: text,
                        calls: calls.clone(),
                        provider_state,
                    });
                    continuation.pending_calls = calls;
                    continuation.next_call_index = 0;
                }
                ModelTurn::ToolCalls { .. } => return Err(RuntimeError::ToolLimit),
            }
        }
    }

    async fn run_hook(&self, event: hooks::HookEvent) -> hooks::HookDecision {
        match &self.hooks {
            Some(executor) => executor.run(event).await,
            None => hooks::HookDecision::default(),
        }
    }

    async fn execute_tool_with_hooks(
        &self,
        continuation: &mut TurnContinuation,
        call: &ToolCall,
    ) -> Result<(), RuntimeError> {
        if let Some(observer) = &self.tool_observer {
            observer.started(call);
        }
        let (mut result, event_name, error, error_type) = match self.tools.execute(call).await {
            Ok(result) => (
                result,
                hooks::EVENT_POST_TOOL_USE,
                String::new(),
                String::new(),
            ),
            Err(error) => (
                json_object([
                    ("ok", Value::Bool(false)),
                    ("error", Value::String(error.to_string())),
                ]),
                hooks::EVENT_POST_TOOL_USE_FAILURE,
                error.to_string(),
                "RuntimeError".into(),
            ),
        };
        let mut event = hooks::HookEvent::new(
            event_name,
            &continuation.turn_id,
            &continuation.hook_context,
        );
        event.tool_name = call.name.clone();
        event.tool_call_id = call.id.clone();
        event.tool_input = call.arguments.clone();
        event.tool_result = result.clone();
        event.error = error;
        event.error_type = error_type;
        let decision = self.run_hook(event).await;
        absorb_hook_decision(continuation, &decision);
        if let Some(updated_output) = decision.updated_output {
            result = updated_output;
        }
        if decision.decision == "block" {
            result = json_object([
                ("ok", Value::Bool(false)),
                ("blocked", Value::Bool(true)),
                (
                    "error",
                    Value::String(if decision.reason.is_empty() {
                        "Tool result blocked by hook".into()
                    } else {
                        decision.reason
                    }),
                ),
            ]);
        }
        if let Some(observer) = &self.tool_observer {
            // Tool results report failure with an explicit `ok: false`; anything
            // else counts as success so arbitrary tool payloads stay valid.
            let ok = result
                .get("ok")
                .and_then(Value::as_bool)
                .unwrap_or(true);
            observer.finished(call, &result, ok);
        }
        append_tool_result(&mut continuation.messages, call, result)
    }
}

/// Observes individual tool steps of a running turn.
///
/// The runtime itself only reports coarse stages, so a host that wants to show
/// which tool is running — and with what result — needs this narrower channel.
/// Callbacks are synchronous and must not block.
pub trait ToolObserver: Send + Sync {
    fn started(&self, call: &ToolCall);
    fn finished(&self, call: &ToolCall, result: &Value, ok: bool);
}

fn absorb_hook_decision(continuation: &mut TurnContinuation, decision: &hooks::HookDecision) {
    continuation
        .hook_audit_events
        .extend(decision.audit_events.iter().cloned());
    if !decision.status_message.is_empty() {
        continuation
            .hook_status_messages
            .push(decision.status_message.clone());
    }
    if !decision.additional_context.is_empty() {
        continuation.messages.push(Message::System {
            content: decision.additional_context.clone(),
        });
    }
}

fn approval_request(continuation: &TurnContinuation) -> Result<ApprovalRequest, RuntimeError> {
    let call = continuation
        .pending_calls
        .get(continuation.next_call_index)
        .cloned()
        .ok_or_else(|| RuntimeError::Tool("approval continuation has no pending call".into()))?;
    let turn_id = if continuation.turn_id.is_empty() {
        "turn"
    } else {
        continuation.turn_id.as_str()
    };
    Ok(ApprovalRequest {
        request_id: format!(
            "{turn_id}:approval:{}:{}:{}",
            continuation.tool_rounds, continuation.next_call_index, call.id
        ),
        message: format!("Allow Sunday Agent to run '{}' ?", call.name),
        tool_call: call,
    })
}

fn append_tool_result(
    messages: &mut Vec<Message>,
    call: &ToolCall,
    result: Value,
) -> Result<(), RuntimeError> {
    messages.push(Message::Tool {
        tool_call_id: call.id.clone(),
        name: call.name.clone(),
        content: serde_json::to_string(&result)
            .map_err(|error| RuntimeError::Tool(error.to_string()))?,
    });
    Ok(())
}

fn json_object<const N: usize>(entries: [(&str, Value); N]) -> Value {
    Value::Object(
        entries
            .into_iter()
            .map(|(key, value)| (key.to_owned(), value))
            .collect(),
    )
}

pub fn system_context(
    capabilities: &DeviceCapabilities,
    tools: &[ToolDefinition],
    context: &AgentContext,
) -> String {
    let enabled_tools = tools
        .iter()
        .map(|tool| tool.name.as_str())
        .collect::<Vec<_>>()
        .join(", ");
    let mut capability_map = BTreeMap::new();
    capability_map.insert("git", capabilities.git);
    capability_map.insert("network", capabilities.network);
    capability_map.insert("notifications", capabilities.notifications);
    capability_map.insert("project_files", capabilities.project_files);
    capability_map.insert("shell", capabilities.shell);
    let capability_text = capability_map
        .into_iter()
        .map(|(name, enabled)| format!("{name}={enabled}"))
        .collect::<Vec<_>>()
        .join(", ");
    let mut prompt = format!(
        "You are Sunday Agent, the AI agent built into LamTools.\n\
         Platform: {}. Device capabilities: {}.\n\
         Available tools: {}. Use provided tools when they are relevant. \
         Never claim a tool is unavailable without checking this list, and never \
         claim access to a capability marked false. Respond in the user's language.",
        capabilities.platform,
        capability_text,
        if enabled_tools.is_empty() {
            "none"
        } else {
            &enabled_tools
        },
    );
    for (heading, value) in [
        ("Global instructions", context.global_instructions.as_str()),
        (
            "Project instructions",
            context.project_instructions.as_str(),
        ),
        ("Long-term memory", context.memory.as_str()),
        ("Active mode context", context.mode_context.as_str()),
    ] {
        let value = value.trim();
        if value.is_empty() {
            continue;
        }
        prompt.push_str("\n\n## ");
        prompt.push_str(heading);
        prompt.push('\n');
        prompt.push_str(value);
    }
    prompt
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{
        atomic::{AtomicUsize, Ordering},
        Arc, Mutex,
    };

    struct FixtureModel {
        calls: Mutex<usize>,
    }

    #[async_trait]
    impl ModelBackend for FixtureModel {
        async fn complete(
            &self,
            _model_record_id: &str,
            messages: &[Message],
            tools: &[ToolDefinition],
            _options: &TurnOptions,
        ) -> Result<ModelTurn, RuntimeError> {
            assert!(
                matches!(&messages[0], Message::System { content } if content.contains("Sunday Agent"))
            );
            assert!(
                matches!(&messages[0], Message::System { content } if content.contains("PROJECT_RULE"))
            );
            assert_eq!(tools[0].name, "write_text_file");
            let mut calls = self.calls.lock().unwrap();
            *calls += 1;
            if *calls == 1 {
                Ok(ModelTurn::ToolCalls {
                    text: String::new(),
                    calls: vec![ToolCall {
                        id: "call-1".into(),
                        name: "write_text_file".into(),
                        arguments: serde_json::json!({"path":"你好.txt","content":"你好"}),
                    }],
                    provider_state: Value::Null,
                })
            } else {
                assert!(
                    matches!(messages.last(), Some(Message::Tool { tool_call_id, .. }) if tool_call_id == "call-1")
                );
                Ok(ModelTurn::Text {
                    text: "文件已创建。".into(),
                    reasoning: String::new(),
                    provider_state: Value::Null,
                })
            }
        }
    }

    struct FixtureTools;

    struct RecordingHooks {
        events: Mutex<Vec<String>>,
    }

    #[async_trait]
    impl hooks::HookExecutor for RecordingHooks {
        async fn run(&self, event: hooks::HookEvent) -> hooks::HookDecision {
            self.events.lock().unwrap().push(event.event_name.clone());
            if event.event_name == hooks::EVENT_PRE_TOOL_USE {
                return hooks::HookDecision {
                    status_message: "checking tool safety...".into(),
                    ..Default::default()
                };
            }
            hooks::HookDecision::default()
        }
    }

    #[async_trait]
    impl ToolRuntime for FixtureTools {
        fn definitions(&self, capabilities: &DeviceCapabilities) -> Vec<ToolDefinition> {
            if !capabilities.project_files {
                return Vec::new();
            }
            vec![ToolDefinition {
                name: "write_text_file".into(),
                description: "Write a project text file".into(),
                input_schema: serde_json::json!({"type":"object"}),
            }]
        }

        async fn execute(&self, call: &ToolCall) -> Result<Value, RuntimeError> {
            Ok(serde_json::json!({"ok": true, "path": call.arguments["path"]}))
        }
    }

    #[tokio::test]
    async fn identity_tools_and_runtime_model_are_shared_contracts() {
        let stages = Arc::new(Mutex::new(Vec::new()));
        let reported_stages = stages.clone();
        let runtime = AgentRuntime::new(
            FixtureModel {
                calls: Mutex::new(0),
            },
            FixtureTools,
        )
        .with_progress(move |stage| reported_stages.lock().unwrap().push(stage));
        let result = runtime
            .run_turn(TurnRequest {
                turn_id: "turn-1".into(),
                model_record_id: "commandcode:deepseek-v3.1".into(),
                history: vec![Message::User {
                    content: "创建文件".into(),
                }],
                capabilities: DeviceCapabilities {
                    platform: "android".into(),
                    project_files: true,
                    ..Default::default()
                },
                context: AgentContext {
                    project_instructions: "PROJECT_RULE".into(),
                    ..Default::default()
                },
                hook_context: hooks::HookRunContext::default(),
                options: TurnOptions::default(),
            })
            .await
            .unwrap();
        assert_eq!(
            stages.lock().unwrap().as_slice(),
            [
                "runtime_compaction_start",
                "runtime_compaction_done",
                "runtime_hooks_start",
                "runtime_hooks_done",
                "runtime_model_start",
                "runtime_model_done",
                "runtime_model_start",
                "runtime_model_done",
            ]
        );
        assert_eq!(result.text, "文件已创建。");
        assert_eq!(result.runtime_model_id, "commandcode:deepseek-v3.1");
        assert_eq!(result.tool_rounds, 1);
    }

    #[tokio::test]
    async fn hook_lifecycle_runs_inside_the_shared_agent_loop() {
        let hooks = Arc::new(RecordingHooks {
            events: Mutex::new(Vec::new()),
        });
        let runtime = AgentRuntime::new(
            FixtureModel {
                calls: Mutex::new(0),
            },
            FixtureTools,
        )
        .with_hook_executor(hooks.clone());
        let result = runtime
            .run_turn(TurnRequest {
                turn_id: "turn-hooks".into(),
                model_record_id: "model".into(),
                history: vec![Message::User {
                    content: "create".into(),
                }],
                capabilities: DeviceCapabilities {
                    project_files: true,
                    ..Default::default()
                },
                context: AgentContext {
                    project_instructions: "PROJECT_RULE".into(),
                    ..Default::default()
                },
                hook_context: hooks::HookRunContext {
                    session_id: "session-1".into(),
                    project_root: "/project".into(),
                    ..Default::default()
                },
                options: TurnOptions::default(),
            })
            .await
            .unwrap();
        assert_eq!(
            *hooks.events.lock().unwrap(),
            [
                "SessionStart",
                "UserPromptSubmit",
                "PreToolUse",
                "PostToolUse",
                "Stop",
            ]
        );
        assert_eq!(result.hook_status_messages, ["checking tool safety..."]);
    }

    /// Replies with narration plus a tool call first, then a final answer.
    struct NarratingModel {
        requests: Mutex<Vec<Vec<Message>>>,
    }

    #[async_trait]
    impl ModelBackend for NarratingModel {
        async fn complete(
            &self,
            _model_record_id: &str,
            messages: &[Message],
            _tools: &[ToolDefinition],
            _options: &TurnOptions,
        ) -> Result<ModelTurn, RuntimeError> {
            let mut requests = self.requests.lock().unwrap();
            requests.push(messages.to_vec());
            if requests.len() == 1 {
                Ok(ModelTurn::ToolCalls {
                    text: "我先看一下文件".into(),
                    calls: vec![ToolCall {
                        id: "call-1".into(),
                        name: "write_text_file".into(),
                        arguments: serde_json::json!({"path":"a.txt","content":"x"}),
                    }],
                    provider_state: Value::Null,
                })
            } else {
                Ok(ModelTurn::Text {
                    text: "完成".into(),
                    reasoning: String::new(),
                    provider_state: Value::Null,
                })
            }
        }
    }

    #[derive(Default)]
    struct RecordingToolObserver {
        events: Mutex<Vec<String>>,
    }

    impl ToolObserver for RecordingToolObserver {
        fn started(&self, call: &ToolCall) {
            self.events
                .lock()
                .unwrap()
                .push(format!("start:{}", call.name));
        }

        fn finished(&self, call: &ToolCall, _result: &Value, ok: bool) {
            self.events
                .lock()
                .unwrap()
                .push(format!("finish:{}:{ok}", call.name));
        }
    }

    #[tokio::test]
    async fn tool_round_narration_is_durable_and_tool_steps_are_observed() {
        let model = Arc::new(NarratingModel {
            requests: Mutex::new(Vec::new()),
        });
        let observer = Arc::new(RecordingToolObserver::default());
        let runtime = AgentRuntime::new(model.clone(), FixtureTools)
            .with_tool_observer(observer.clone());
        let result = runtime
            .run_turn(TurnRequest {
                turn_id: "turn-narration".into(),
                model_record_id: "model".into(),
                history: vec![Message::User {
                    content: "改一下文件".into(),
                }],
                capabilities: DeviceCapabilities {
                    project_files: true,
                    ..Default::default()
                },
                context: AgentContext::default(),
                hook_context: hooks::HookRunContext::default(),
                options: TurnOptions::default(),
            })
            .await
            .unwrap();

        // The narration of a tool round survives into the durable history, so a
        // transcript can retain it instead of only showing the final answer.
        let narration = result
            .runtime_history
            .iter()
            .find_map(|message| match message {
                Message::AssistantToolCalls { content, .. } => Some(content.clone()),
                _ => None,
            });
        assert_eq!(narration.as_deref(), Some("我先看一下文件"));

        // The follow-up request carries that narration back to the provider.
        let requests = model.requests.lock().unwrap();
        assert_eq!(requests.len(), 2);
        assert!(requests[1].iter().any(|message| matches!(
            message,
            Message::AssistantToolCalls { content, .. } if content == "我先看一下文件"
        )));

        // Hosts can show which tool is running without waiting for the turn.
        assert_eq!(
            *observer.events.lock().unwrap(),
            ["start:write_text_file", "finish:write_text_file:true"]
        );
        assert_eq!(result.tool_rounds, 1);
    }

    struct GatedTools {
        executions: Arc<AtomicUsize>,
    }

    #[async_trait]
    impl ToolRuntime for GatedTools {
        fn definitions(&self, _capabilities: &DeviceCapabilities) -> Vec<ToolDefinition> {
            vec![ToolDefinition {
                name: "write_text_file".into(),
                description: "Write".into(),
                input_schema: serde_json::json!({"type":"object"}),
            }]
        }

        fn permission(&self, _call: &ToolCall) -> ToolPermission {
            ToolPermission::AskUser
        }

        async fn execute(&self, _call: &ToolCall) -> Result<Value, RuntimeError> {
            self.executions.fetch_add(1, Ordering::SeqCst);
            Ok(serde_json::json!({"ok":true}))
        }
    }

    #[tokio::test]
    async fn ask_user_tools_pause_and_resume_without_replaying_the_model_call() {
        let executions = Arc::new(AtomicUsize::new(0));
        let runtime = AgentRuntime::new(
            FixtureModel {
                calls: Mutex::new(0),
            },
            GatedTools {
                executions: executions.clone(),
            },
        );
        let progress = runtime
            .run_turn_progress(TurnRequest {
                turn_id: "turn-gated".into(),
                model_record_id: "model".into(),
                history: vec![Message::User {
                    content: "write".into(),
                }],
                capabilities: DeviceCapabilities {
                    project_files: true,
                    ..Default::default()
                },
                context: AgentContext {
                    project_instructions: "PROJECT_RULE".into(),
                    ..Default::default()
                },
                hook_context: hooks::HookRunContext::default(),
                options: TurnOptions::default(),
            })
            .await
            .unwrap();
        let (request, continuation) = match progress {
            TurnProgress::ApprovalRequired {
                request,
                continuation,
            } => (request, continuation),
            _ => panic!("expected approval"),
        };
        assert_eq!(executions.load(Ordering::SeqCst), 0);
        assert_eq!(request.tool_call.name, "write_text_file");

        let resumed = runtime
            .resume_turn(
                continuation,
                ApprovalResponse {
                    request_id: request.request_id,
                    decision: ApprovalDecision::ApproveOnce,
                    guidance: String::new(),
                },
            )
            .await
            .unwrap();
        assert_eq!(executions.load(Ordering::SeqCst), 1);
        assert!(matches!(
            resumed,
            TurnProgress::Completed {
                result: TurnResult { tool_rounds: 1, .. }
            }
        ));
    }

    struct AutoCountingTools {
        calls: Arc<AtomicUsize>,
        arguments: Arc<Mutex<Vec<Value>>>,
    }

    #[async_trait]
    impl ToolRuntime for AutoCountingTools {
        fn definitions(&self, _: &DeviceCapabilities) -> Vec<ToolDefinition> {
            vec![ToolDefinition {
                name: "write_text_file".into(),
                description: "fixture".into(),
                input_schema: serde_json::json!({"type":"object"}),
            }]
        }
        async fn execute(&self, call: &ToolCall) -> Result<Value, RuntimeError> {
            self.calls.fetch_add(1, Ordering::SeqCst);
            self.arguments.lock().unwrap().push(call.arguments.clone());
            Ok(serde_json::json!({"ok":true}))
        }
    }

    struct PermissionHookFixture {
        pre_policy: &'static str,
        permission_policy: &'static str,
        events: Arc<Mutex<Vec<String>>>,
    }

    #[async_trait]
    impl hooks::HookExecutor for PermissionHookFixture {
        async fn run(&self, event: hooks::HookEvent) -> hooks::HookDecision {
            self.events.lock().unwrap().push(event.event_name.clone());
            match event.event_name.as_str() {
                hooks::EVENT_PRE_TOOL_USE => hooks::HookDecision {
                    permission_decision: self.pre_policy.into(),
                    permission_decision_reason: "fixture pre-tool rule".into(),
                    updated_input: Some(serde_json::json!({"path":"hook-updated.txt"})),
                    ..Default::default()
                },
                hooks::EVENT_PERMISSION_REQUEST => hooks::HookDecision {
                    permission_decision: self.permission_policy.into(),
                    permission_decision_reason: "fixture approval rule".into(),
                    ..Default::default()
                },
                _ => hooks::HookDecision::default(),
            }
        }
    }

    #[tokio::test]
    async fn pre_tool_hook_deny_blocks_auto_tool_and_reports_reason() {
        let calls = Arc::new(AtomicUsize::new(0));
        let events = Arc::new(Mutex::new(Vec::new()));
        let runtime = AgentRuntime::new(
            FixtureModel {
                calls: Mutex::new(0),
            },
            AutoCountingTools {
                calls: calls.clone(),
                arguments: Arc::new(Mutex::new(Vec::new())),
            },
        )
        .with_hook_executor(Arc::new(PermissionHookFixture {
            pre_policy: "deny",
            permission_policy: "",
            events: events.clone(),
        }));
        let progress = runtime
            .run_turn_progress(TurnRequest {
                turn_id: "pre-deny".into(),
                model_record_id: "fixture".into(),
                history: vec![Message::User {
                    content: "write".into(),
                }],
                capabilities: DeviceCapabilities::default(),
                context: AgentContext {
                    project_instructions: "PROJECT_RULE".into(),
                    ..Default::default()
                },
                hook_context: Default::default(),
                options: TurnOptions {
                    permission_preset: PermissionPreset::FullAccess,
                    ..Default::default()
                },
            })
            .await
            .unwrap();
        let TurnProgress::Completed { result } = progress else {
            panic!("deny must complete with blocked tool result")
        };
        assert_eq!(calls.load(Ordering::SeqCst), 0);
        assert!(result.runtime_history.iter().any(|message| matches!(message, Message::Tool { content, .. } if content.contains("fixture pre-tool rule") && content.contains("blocked"))));
        assert!(!events
            .lock()
            .unwrap()
            .contains(&hooks::EVENT_PERMISSION_REQUEST.to_owned()));
    }

    #[tokio::test]
    async fn pre_tool_hook_ask_user_pauses_auto_tool_even_under_full_access_and_resumes_updated_call(
    ) {
        let calls = Arc::new(AtomicUsize::new(0));
        let arguments = Arc::new(Mutex::new(Vec::new()));
        let events = Arc::new(Mutex::new(Vec::new()));
        let runtime = AgentRuntime::new(
            FixtureModel {
                calls: Mutex::new(0),
            },
            AutoCountingTools {
                calls: calls.clone(),
                arguments: arguments.clone(),
            },
        )
        .with_hook_executor(Arc::new(PermissionHookFixture {
            pre_policy: "ask_user",
            permission_policy: "",
            events: events.clone(),
        }));
        let progress = runtime
            .run_turn_progress(TurnRequest {
                turn_id: "pre-ask".into(),
                model_record_id: "fixture".into(),
                history: vec![Message::User {
                    content: "write".into(),
                }],
                capabilities: DeviceCapabilities::default(),
                context: AgentContext {
                    project_instructions: "PROJECT_RULE".into(),
                    ..Default::default()
                },
                hook_context: Default::default(),
                options: TurnOptions {
                    permission_preset: PermissionPreset::FullAccess,
                    session_approved_tools: vec!["write_text_file".into()],
                    ..Default::default()
                },
            })
            .await
            .unwrap();
        let TurnProgress::ApprovalRequired {
            request,
            continuation,
        } = progress
        else {
            panic!("hook must force approval")
        };
        assert_eq!(calls.load(Ordering::SeqCst), 0);
        assert_eq!(
            request.tool_call.arguments,
            serde_json::json!({"path":"hook-updated.txt"})
        );
        assert!(events
            .lock()
            .unwrap()
            .contains(&hooks::EVENT_PERMISSION_REQUEST.to_owned()));
        let resumed = runtime
            .resume_turn(
                continuation,
                ApprovalResponse {
                    request_id: request.request_id,
                    decision: ApprovalDecision::ApproveOnce,
                    guidance: String::new(),
                },
            )
            .await
            .unwrap();
        assert!(matches!(resumed, TurnProgress::Completed { .. }));
        assert_eq!(calls.load(Ordering::SeqCst), 1);
        assert_eq!(
            *arguments.lock().unwrap(),
            vec![serde_json::json!({"path":"hook-updated.txt"})]
        );
    }

    #[tokio::test]
    async fn pre_tool_hook_ask_user_still_honors_permission_request_allow_and_deny() {
        for permission_policy in ["allow", "deny"] {
            let calls = Arc::new(AtomicUsize::new(0));
            let events = Arc::new(Mutex::new(Vec::new()));
            let runtime = AgentRuntime::new(
                FixtureModel {
                    calls: Mutex::new(0),
                },
                AutoCountingTools {
                    calls: calls.clone(),
                    arguments: Arc::new(Mutex::new(Vec::new())),
                },
            )
            .with_hook_executor(Arc::new(PermissionHookFixture {
                pre_policy: "ask_user",
                permission_policy,
                events: events.clone(),
            }));
            let progress = runtime
                .run_turn_progress(TurnRequest {
                    turn_id: format!("pre-{permission_policy}"),
                    model_record_id: "fixture".into(),
                    history: vec![Message::User {
                        content: "write".into(),
                    }],
                    capabilities: DeviceCapabilities::default(),
                    context: AgentContext {
                        project_instructions: "PROJECT_RULE".into(),
                        ..Default::default()
                    },
                    hook_context: Default::default(),
                    options: TurnOptions {
                        permission_preset: PermissionPreset::FullAccess,
                        ..Default::default()
                    },
                })
                .await
                .unwrap();
            let TurnProgress::Completed { result } = progress else {
                panic!("PermissionRequest {permission_policy} must resolve without foreground approval")
            };
            assert_eq!(
                calls.load(Ordering::SeqCst),
                usize::from(permission_policy == "allow")
            );
            assert!(events
                .lock()
                .unwrap()
                .contains(&hooks::EVENT_PERMISSION_REQUEST.to_owned()));
            if permission_policy == "deny" {
                assert!(result.runtime_history.iter().any(|message| matches!(message, Message::Tool { content, .. } if content.contains("fixture approval rule") && content.contains("denied"))));
            }
        }
    }
}
