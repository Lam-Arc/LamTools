//! Platform-neutral Sunday Agent runtime.
//!
//! Hosts provide model I/O and device tools.  The agent loop, identity,
//! capability-aware system context and tool-result continuation live here so
//! desktop and mobile cannot drift into separate agents.

use async_trait::async_trait;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{collections::BTreeMap, sync::Arc};

pub mod compaction;
pub mod fetch_tools;
pub mod hooks;
pub mod mcp;
pub mod image_gen;
pub mod memory;
pub mod plan_package;
pub mod plan_tools;
pub mod plugin_catalog;
mod profiles;
pub mod project_tools;
pub mod provider;
pub mod skills;
pub mod study;
pub mod tool_catalog;
pub mod study_skills;
pub mod sub_agent;
pub mod update_manifest;
pub mod web_search;
pub mod workflow_data_packet;
pub mod workflow_document;
pub mod workflow_ops;
pub mod workflow_runner;
pub mod workflow_store;

/// How many consecutive tool-only rounds the model may run before it is asked
/// for a visible progress note. Desktop parity for
/// `LoopPolicy.max_tool_only_rounds_without_progress`.
///
/// There is deliberately no cap on tool rounds: the desktop kernel has none
/// either, because a real task can take dozens of steps. What the desktop does
/// instead is require a short report from a model that keeps calling tools
/// without saying anything, and stop a model that keeps repeating one step.
pub const DEFAULT_TOOL_ONLY_ROUND_LIMIT: usize = 8;
/// Desktop parity for `LoopPolicy.max_identical_tool_results`: how often one
/// exact call-and-result pair may repeat inside the window below before the
/// turn is wound down.
pub const DEFAULT_IDENTICAL_TOOL_RESULT_LIMIT: usize = 10;
/// Desktop parity for `LoopPolicy.identical_tool_result_window`.
pub const DEFAULT_IDENTICAL_TOOL_RESULT_WINDOW: usize = 12;
/// The desktop's progress note, verbatim (`kernel/loop.py`), so a model that
/// learned one host's recovery path recovers the same way on the other.
const TOOL_PROGRESS_REQUIRED: &str = concat!(
    "[TOOL_PROGRESS_REQUIRED] Before using more tools, briefly report ",
    "[已确认事实] [剩余不确定性] [下一步]. Do not repeat prior evidence, and do not ",
    "claim a result that has not been observed."
);

// Image input carries no size or count budget here: the desktop has none either
// (it enforces one 50 MiB limit per attachment and sends what the user attached),
// so a cap on this side could only refuse requests the desktop accepts.

#[derive(Clone, Debug, Default, Deserialize, Serialize, PartialEq, Eq)]
pub struct DeviceCapabilities {
    pub platform: String,
    pub project_files: bool,
    pub shell: bool,
    pub git: bool,
    pub network: bool,
    pub notifications: bool,
}

/// Which host a runtime is built for.
///
/// Plugins (manifest `platforms`) and skills (frontmatter `platforms`) declare
/// one class in the same three words — `desktop`, `mobile`, `universal` — and a
/// host offers what is universal plus what is its own. A declaration is what
/// decides, not a capability proxy: the phone has no shell because it is the
/// phone, and a plugin that says `desktop` says so itself.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum HostPlatform {
    Desktop,
    Mobile,
}

/// The class name manifests and skill frontmatter use, so a declaration and a
/// host speak one word.
pub const PLATFORM_DESKTOP: &str = "desktop";
pub const PLATFORM_MOBILE: &str = "mobile";
pub const PLATFORM_UNIVERSAL: &str = "universal";

impl HostPlatform {
    pub fn as_str(self) -> &'static str {
        match self {
            HostPlatform::Desktop => PLATFORM_DESKTOP,
            HostPlatform::Mobile => PLATFORM_MOBILE,
        }
    }

    /// Whether this host offers something that declares `platforms`.
    ///
    /// An unrecognised class is not offered: an unknown word is a declaration
    /// this host cannot honour, and silently treating it as universal is how a
    /// surface ends up promising what it cannot run.
    pub fn offers(self, platforms: &str) -> bool {
        platforms == PLATFORM_UNIVERSAL || platforms == self.as_str()
    }
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
    /// Always asks, whatever the session's permission preset is. A control tool
    /// like `question` has no meaning if it runs without an answer, so the
    /// desktop pauses for it even under full access and this matches that.
    AlwaysAsk,
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
    /// Name of the active execution mode, used verbatim in the refusal below.
    #[serde(default)]
    pub active_mode: String,
    /// Tool names the active mode allows. `None` — and an empty list, which the
    /// desktop treats as full access — mean the mode restricts nothing.
    #[serde(default)]
    pub mode_tools: Option<Vec<String>>,
    /// Tool-only rounds before the model must report progress. `None` keeps the
    /// desktop default, `Some(0)` turns the request off.
    #[serde(default)]
    pub tool_only_round_limit: Option<usize>,
    /// Repetitions of one exact call-and-result pair that end the turn. `None`
    /// keeps the desktop default, `Some(0)` turns the stop off.
    #[serde(default)]
    pub identical_tool_result_limit: Option<usize>,
    /// How many recent tool results the repetition count looks at.
    #[serde(default)]
    pub identical_tool_result_window: Option<usize>,
}

impl TurnOptions {
    /// The mode whitelist, or `None` when this mode does not restrict tools.
    pub fn mode_whitelist(&self) -> Option<&[String]> {
        match &self.mode_tools {
            Some(tools) if !tools.is_empty() => Some(tools.as_slice()),
            _ => None,
        }
    }

    /// The progress-note threshold, or `None` when the host disabled it.
    pub fn tool_only_round_limit(&self) -> Option<usize> {
        match self.tool_only_round_limit {
            Some(0) => None,
            Some(limit) => Some(limit),
            None => Some(DEFAULT_TOOL_ONLY_ROUND_LIMIT),
        }
    }

    /// The repetition threshold, or `None` when the host disabled the stop.
    pub fn identical_tool_result_limit(&self) -> Option<usize> {
        match self.identical_tool_result_limit {
            Some(0) => None,
            Some(limit) => Some(limit),
            None => Some(DEFAULT_IDENTICAL_TOOL_RESULT_LIMIT),
        }
    }

    /// The repetition window, never smaller than the threshold so a threshold
    /// below the desktop window cannot make the stop unreachable.
    pub fn identical_tool_result_window(&self) -> usize {
        let window = self
            .identical_tool_result_window
            .unwrap_or(DEFAULT_IDENTICAL_TOOL_RESULT_WINDOW);
        window.max(self.identical_tool_result_limit().unwrap_or(0))
    }

    /// The refusal a disallowed call gets, worded exactly like the desktop so a
    /// model that learned one host's recovery path recovers the same way here.
    pub fn mode_block_reason(&self, name: &str) -> Option<String> {
        let allowed = self.mode_whitelist()?;
        if allowed.iter().any(|allowed| allowed == name) {
            return None;
        }
        Some(format!(
            "You are in the {} mode, you can't use {name}. Please make the plan prepared and ask user to switch mode.",
            self.active_mode
        ))
    }
}

/// Drop the tools a mode does not allow. The model is never told about a tool
/// it would be refused at execution time.
fn mode_filtered_definitions(
    definitions: Vec<ToolDefinition>,
    options: &TurnOptions,
) -> Vec<ToolDefinition> {
    let Some(allowed) = options.mode_whitelist() else {
        return definitions;
    };
    definitions
        .into_iter()
        .filter(|definition| allowed.iter().any(|name| name == &definition.name))
        .collect()
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
    /// Consecutive rounds that called tools without the model saying anything.
    /// Kept on the continuation so an approval pause does not lose the streak.
    #[serde(default)]
    pub tool_only_rounds: usize,
    /// Fingerprints of the most recent tool results, oldest first, trimmed to
    /// `identical_tool_result_window`.
    #[serde(default)]
    pub identical_tool_results: Vec<String>,
    /// Set when a result crossed the repetition threshold; read once its round
    /// has finished, so a batch of calls is never cut in half.
    #[serde(default)]
    pub duplicate_result_stop: Option<usize>,
    pub pending_calls: Vec<ToolCall>,
    pub next_call_index: usize,
    #[serde(default)]
    pub compaction: Option<compaction::CompactionReport>,
}

impl TurnContinuation {
    /// Whether the round that just finished called tools without narration.
    ///
    /// The round's own assistant message is the newest one in the transcript,
    /// so this reads what the model actually said rather than a copy that could
    /// drift.
    fn round_was_tool_only(&self) -> bool {
        self.messages
            .iter()
            .rev()
            .find_map(|message| match message {
                Message::AssistantToolCalls { content, .. } => Some(content.trim().is_empty()),
                _ => None,
            })
            // No tool-call message: treat the round as narrated, so a bookkeeping
            // edge case cannot inject a progress demand nobody earned.
            .unwrap_or(false)
    }
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(tag = "status", rename_all = "snake_case")]
pub enum TurnProgress {    Completed {
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
        let definitions = mode_filtered_definitions(
            self.tools.definitions(&request.capabilities),
            &request.options,
        );
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
            tool_only_rounds: 0,
            identical_tool_results: Vec::new(),
            duplicate_result_stop: None,
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
        let definitions = mode_filtered_definitions(
            self.tools.definitions(&continuation.capabilities),
            &continuation.options,
        );
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
                    &mut continuation,
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
                // A model can still name a tool the mode keeps out of its list.
                // Refuse it with the desktop's wording instead of running it.
                if let Some(reason) = continuation.options.mode_block_reason(&call.name) {
                    append_tool_result(
                        &mut continuation,
                        &call,
                        json_object([
                            ("ok", Value::Bool(false)),
                            ("blocked", Value::Bool(true)),
                            ("error", Value::String(reason)),
                        ]),
                    )?;
                    continuation.next_call_index += 1;
                    continue;
                }
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
                        &mut continuation,
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
                            &mut continuation,
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
                    ToolPermission::AskUser | ToolPermission::AlwaysAsk | ToolPermission::AutoAllow
                        if hook_ask_user
                            || tool_permission == ToolPermission::AlwaysAsk
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
                                &mut continuation,
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
                    // Handled by the asking arm above; reached only if the guard
                    // there stops covering it, which is why it asks again.
                    ToolPermission::AlwaysAsk => {
                        return Ok(TurnProgress::ApprovalRequired {
                            request: approval_request(&continuation)?,
                            continuation,
                        });
                    }
                }
            }
            if !continuation.pending_calls.is_empty() {
                continuation.tool_rounds += 1;
                continuation.pending_calls.clear();
                continuation.next_call_index = 0;
                // Desktop parity (`kernel/loop.py`): a round counts as
                // tool-only when the model called tools without saying
                // anything, and the streak resets as soon as it speaks.
                if continuation.round_was_tool_only() {
                    continuation.tool_only_rounds += 1;
                } else {
                    continuation.tool_only_rounds = 0;
                }
                if let Some(count) = continuation.duplicate_result_stop.take() {
                    return self
                        .finish_after_repeated_results(continuation, count)
                        .await;
                }
                if let Some(limit) = continuation.options.tool_only_round_limit() {
                    if continuation.tool_only_rounds >= limit {
                        continuation.messages.push(Message::User {
                            content: TOOL_PROGRESS_REQUIRED.into(),
                        });
                    }
                }
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
                    return self.finish_turn(continuation, text, reasoning, provider_state);
                }
                ModelTurn::ToolCalls {
                    text,
                    calls,
                    provider_state,
                } => {
                    continuation.messages.push(Message::AssistantToolCalls {
                        content: text,
                        calls: calls.clone(),
                        provider_state,
                    });
                    continuation.pending_calls = calls;
                    continuation.next_call_index = 0;
                }
            }
        }
    }

    async fn run_hook(&self, event: hooks::HookEvent) -> hooks::HookDecision {
        match &self.hooks {
            Some(executor) => executor.run(event).await,
            None => hooks::HookDecision::default(),
        }
    }

    /// Close the turn with the model's answer and everything it accumulated.
    fn finish_turn(
        &self,
        continuation: TurnContinuation,
        text: String,
        reasoning: String,
        provider_state: Value,
    ) -> Result<TurnProgress, RuntimeError> {
        let runtime_history = continuation.messages.iter().skip(1).cloned().collect();
        Ok(TurnProgress::Completed {
            result: TurnResult {
                text,
                reasoning,
                runtime_model_id: self.model.runtime_model_id(&continuation.model_record_id),
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
        })
    }

    /// End a turn whose model keeps repeating one exact step.
    ///
    /// The desktop pauses the run here and waits for the user. A mobile turn
    /// cannot wait for a resume, so this ends recoverably instead: no error and
    /// nothing dropped, the reason travels on the warning channel, and the
    /// model gets one last request — with no tools on offer — to answer from
    /// the evidence it already has.
    async fn finish_after_repeated_results(
        &self,
        mut continuation: TurnContinuation,
        count: usize,
    ) -> Result<TurnProgress, RuntimeError> {
        let window = continuation.options.identical_tool_result_window();
        let reason = format!(
            "No progress observed: the same exact tool call and result occurred {count} times \
             within the last {window} tool results. The turn was ended and the model was asked to \
             answer with the evidence already collected."
        );
        continuation.runtime_warnings.push(reason.clone());
        continuation.messages.push(Message::User {
            content: format!(
                "No progress observed: the same exact tool call and result occurred {count} times \
                 within the last {window} tool results. Stop repeating it: report what you have \
                 confirmed, what is still uncertain and what you would do differently, then answer \
                 with the evidence already collected."
            ),
        });
        self.report("runtime_model_start");
        let turn = self
            .model
            .complete(
                &continuation.model_record_id,
                &continuation.messages,
                &[],
                &continuation.options,
            )
            .await?;
        self.report("runtime_model_done");
        let stop_decision = self
            .run_hook(hooks::HookEvent::new(
                hooks::EVENT_STOP,
                &continuation.turn_id,
                &continuation.hook_context,
            ))
            .await;
        absorb_hook_decision(&mut continuation, &stop_decision);
        if stop_decision.decision == "block" {
            // The normal path refuses to complete when a hook blocks it, but a
            // wind-down cannot keep working: it is ending because the model
            // stopped making progress. Record the objection and finish anyway.
            continuation.runtime_warnings.push(if stop_decision.reason.is_empty() {
                "turn completion blocked by hook".into()
            } else {
                stop_decision.reason
            });
        }
        let (text, reasoning, provider_state) = match turn {
            ModelTurn::Text {
                text,
                reasoning,
                provider_state,
            } => (text, reasoning, provider_state),
            // A provider that calls a tool nobody offered still said something;
            // keep its words instead of discarding a diagnosed turn.
            ModelTurn::ToolCalls {
                text,
                provider_state,
                ..
            } => (text, String::new(), provider_state),
        };
        if !text.trim().is_empty() {
            continuation.messages.push(Message::Assistant {
                content: text.clone(),
                provider_state: provider_state.clone(),
            });
        }
        self.finish_turn(continuation, text, reasoning, provider_state)
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
        append_tool_result(continuation, call, result)
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
    continuation: &mut TurnContinuation,
    call: &ToolCall,
    result: Value,
) -> Result<(), RuntimeError> {
    let content = serde_json::to_string(&result)
        .map_err(|error| RuntimeError::Tool(error.to_string()))?;
    record_tool_result(continuation, call, &content);
    continuation.messages.push(Message::Tool {
        tool_call_id: call.id.clone(),
        name: call.name.clone(),
        content,
    });
    Ok(())
}

/// Remember one exact call-and-result pair and flag the turn when it keeps
/// repeating. This is the desktop's `max_identical_tool_results` guard: it is
/// what keeps an unlimited tool loop from running forever on a stuck model,
/// and it fires on the evidence (same call, same answer) rather than on a step
/// count.
fn record_tool_result(continuation: &mut TurnContinuation, call: &ToolCall, content: &str) {
    let Some(limit) = continuation.options.identical_tool_result_limit() else {
        return;
    };
    let window = continuation.options.identical_tool_result_window();
    let fingerprint = tool_result_fingerprint(call, content);
    continuation.identical_tool_results.push(fingerprint.clone());
    if continuation.identical_tool_results.len() > window {
        let excess = continuation.identical_tool_results.len() - window;
        continuation.identical_tool_results.drain(..excess);
    }
    let count = continuation
        .identical_tool_results
        .iter()
        .filter(|seen| **seen == fingerprint)
        .count();
    if count >= limit {
        continuation.duplicate_result_stop = Some(count);
    }
}

/// Hash of everything the desktop compares for a repeat: the tool, its exact
/// arguments and the exact result it produced. Hashed rather than kept whole so
/// a long result cannot grow the continuation a host has to carry.
fn tool_result_fingerprint(call: &ToolCall, content: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(call.name.as_bytes());
    hasher.update([0]);
    hasher.update(serde_json::to_vec(&call.arguments).unwrap_or_default());
    hasher.update([0]);
    hasher.update(content.as_bytes());
    format!("{:x}", hasher.finalize())
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
            assert_eq!(tools[0].name, "write_file");
            let mut calls = self.calls.lock().unwrap();
            *calls += 1;
            if *calls == 1 {
                Ok(ModelTurn::ToolCalls {
                    text: String::new(),
                    calls: vec![ToolCall {
                        id: "call-1".into(),
                        name: "write_file".into(),
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
                name: "write_file".into(),
                description: "Write a project text file".into(),
                input_schema: serde_json::json!({"type":"object"}),
            }]
        }

        async fn execute(&self, call: &ToolCall) -> Result<Value, RuntimeError> {
            Ok(serde_json::json!({"ok": true, "path": call.arguments["path"]}))
        }
    }

    /// A mode that allows reading but not writing, and a model that asks to
    /// write anyway: the call must come back blocked with the desktop wording,
    /// and the tool list must not have offered it in the first place.
    struct AskingModel {
        seen_tools: Mutex<Vec<String>>,
        seen_system: Mutex<String>,
        calls: Mutex<usize>,
    }

    #[async_trait]
    impl ModelBackend for AskingModel {
        async fn complete(
            &self,
            _model_record_id: &str,
            messages: &[Message],
            tools: &[ToolDefinition],
            _options: &TurnOptions,
        ) -> Result<ModelTurn, RuntimeError> {
            *self.seen_tools.lock().unwrap() = tools
                .iter()
                .map(|definition| definition.name.clone())
                .collect();
            if let Some(Message::System { content }) = messages.first() {
                *self.seen_system.lock().unwrap() = content.clone();
            }
            let mut calls = self.calls.lock().unwrap();
            *calls += 1;
            if *calls == 1 {
                Ok(ModelTurn::ToolCalls {
                    text: String::new(),
                    calls: vec![ToolCall {
                        id: "call-1".into(),
                        name: "write_file".into(),
                        arguments: serde_json::json!({"path":"a.txt","content":"x"}),
                    }],
                    provider_state: Value::Null,
                })
            } else {
                Ok(ModelTurn::Text {
                    text: "已改为只读操作。".into(),
                    reasoning: String::new(),
                    provider_state: Value::Null,
                })
            }
        }
    }

    struct CountingTools {
        executions: Arc<AtomicUsize>,
    }

    #[async_trait]
    impl ToolRuntime for CountingTools {
        fn definitions(&self, _capabilities: &DeviceCapabilities) -> Vec<ToolDefinition> {
            vec![
                ToolDefinition {
                    name: "read_file".into(),
                    description: "Read a project text file".into(),
                    input_schema: serde_json::json!({"type":"object"}),
                },
                ToolDefinition {
                    name: "write_file".into(),
                    description: "Write a project text file".into(),
                    input_schema: serde_json::json!({"type":"object"}),
                },
            ]
        }

        async fn execute(&self, _call: &ToolCall) -> Result<Value, RuntimeError> {
            self.executions.fetch_add(1, Ordering::SeqCst);
            Ok(serde_json::json!({"ok": true}))
        }
    }

    #[tokio::test]
    async fn a_mode_whitelist_hides_and_blocks_every_tool_it_excludes() {
        let executions = Arc::new(AtomicUsize::new(0));
        let model = Arc::new(AskingModel {
            seen_tools: Mutex::new(Vec::new()),
            seen_system: Mutex::new(String::new()),
            calls: Mutex::new(0),
        });
        let runtime = AgentRuntime::new(
            model.clone(),
            CountingTools {
                executions: executions.clone(),
            },
        );
        let result = runtime
            .run_turn(TurnRequest {
                turn_id: "turn-mode".into(),
                model_record_id: "fixture:model".into(),
                history: vec![Message::User {
                    content: "写个文件".into(),
                }],
                capabilities: DeviceCapabilities {
                    project_files: true,
                    ..Default::default()
                },
                context: AgentContext::default(),
                hook_context: hooks::HookRunContext::default(),
                options: TurnOptions {
                    active_mode: "consider".into(),
                    mode_tools: Some(vec!["read_file".into()]),
                    permission_preset: PermissionPreset::FullAccess,
                    ..Default::default()
                },
            })
            .await
            .unwrap();
        // Advertised: only what the mode allows.
        assert_eq!(
            model.seen_tools.lock().unwrap().clone(),
            vec!["read_file".to_owned()]
        );
        // The system prompt must agree with the same list.
        assert!(
            model
                .seen_system
                .lock()
                .unwrap()
                .contains("Available tools: read_file."),
            "the prompt must list exactly the tools the mode allows"
        );
        // Executed: nothing, and the refusal is the desktop sentence.
        assert_eq!(executions.load(Ordering::SeqCst), 0);
        let refusal = result
            .runtime_history
            .iter()
            .find_map(|message| match message {
                Message::Tool { content, .. } if content.contains("write_file") => Some(content.clone()),
                _ => None,
            })
            .expect("the blocked call must be reported back to the model");
        assert!(
            refusal.contains(
                "You are in the consider mode, you can't use write_file. \
                 Please make the plan prepared and ask user to switch mode."
            ),
            "unexpected refusal text: {refusal}"
        );
        assert!(refusal.contains("\"blocked\":true"));
    }

    #[tokio::test]
    async fn a_full_access_mode_still_advertises_every_tool() {
        let executions = Arc::new(AtomicUsize::new(0));
        let model = Arc::new(AskingModel {
            seen_tools: Mutex::new(Vec::new()),
            seen_system: Mutex::new(String::new()),
            calls: Mutex::new(0),
        });
        let runtime = AgentRuntime::new(
            model.clone(),
            CountingTools {
                executions: executions.clone(),
            },
        );
        runtime
            .run_turn(TurnRequest {
                turn_id: "turn-execute".into(),
                model_record_id: "fixture:model".into(),
                history: vec![Message::User {
                    content: "写个文件".into(),
                }],
                capabilities: DeviceCapabilities {
                    project_files: true,
                    ..Default::default()
                },
                context: AgentContext::default(),
                hook_context: hooks::HookRunContext::default(),
                options: TurnOptions {
                    active_mode: "execute".into(),
                    mode_tools: Some(Vec::new()),
                    ..Default::default()
                },
            })
            .await
            .unwrap();
        let mut seen = model.seen_tools.lock().unwrap().clone();
        seen.sort();
        assert_eq!(seen, vec!["read_file".to_owned(), "write_file".to_owned()]);
        assert_eq!(
            executions.load(Ordering::SeqCst),
            1,
            "an unrestricted mode must run the call"
        );
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
                        name: "write_file".into(),
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
            ["start:write_file", "finish:write_file:true"]
        );
        assert_eq!(result.tool_rounds, 1);
    }

    /// A model that calls tools for `tool_rounds` rounds and then answers, with
    /// narration on one chosen round when a test needs the streak to reset.
    struct StreakModel {
        tool_rounds: usize,
        narrate_round: Option<usize>,
        /// Repeat one identical call and arguments every round.
        repeat_call: bool,
        requests: Mutex<Vec<Vec<Message>>>,
        offered_tools: Mutex<Vec<usize>>,
        step: Mutex<usize>,
    }

    impl StreakModel {
        fn new(tool_rounds: usize) -> Self {
            Self {
                tool_rounds,
                narrate_round: None,
                repeat_call: false,
                requests: Mutex::new(Vec::new()),
                offered_tools: Mutex::new(Vec::new()),
                step: Mutex::new(0),
            }
        }
    }

    #[async_trait]
    impl ModelBackend for StreakModel {
        async fn complete(
            &self,
            _model_record_id: &str,
            messages: &[Message],
            tools: &[ToolDefinition],
            _options: &TurnOptions,
        ) -> Result<ModelTurn, RuntimeError> {
            self.requests.lock().unwrap().push(messages.to_vec());
            self.offered_tools.lock().unwrap().push(tools.len());
            // A request with no tools can only be the wind-down after a repeated
            // step, and a model answers it with what it already has.
            if tools.is_empty() {
                return Ok(ModelTurn::Text {
                    text: "按现有证据作答。".into(),
                    reasoning: String::new(),
                    provider_state: Value::Null,
                });
            }
            let mut step = self.step.lock().unwrap();
            let index = *step;
            *step += 1;
            if index >= self.tool_rounds {
                return Ok(ModelTurn::Text {
                    text: "完成了。".into(),
                    reasoning: String::new(),
                    provider_state: Value::Null,
                });
            }
            Ok(ModelTurn::ToolCalls {
                text: if self.narrate_round == Some(index) {
                    "我先看一下".into()
                } else {
                    String::new()
                },
                calls: vec![ToolCall {
                    id: format!("call-{index}"),
                    name: "read_file".into(),
                    arguments: if self.repeat_call {
                        serde_json::json!({"path":"same.txt"})
                    } else {
                        serde_json::json!({"path": format!("file-{index}.txt")})
                    },
                }],
                provider_state: Value::Null,
            })
        }
    }

    fn streak_request(turn_id: &str, options: TurnOptions) -> TurnRequest {
        TurnRequest {
            turn_id: turn_id.into(),
            model_record_id: "fixture".into(),
            history: vec![Message::User {
                content: "读一批文件".into(),
            }],
            capabilities: DeviceCapabilities {
                project_files: true,
                ..Default::default()
            },
            context: AgentContext::default(),
            hook_context: hooks::HookRunContext::default(),
            options,
        }
    }

    fn count<F: Fn(&Message) -> bool>(messages: &[Message], predicate: F) -> usize {
        messages.iter().filter(|message| predicate(message)).count()
    }

    const PROGRESS_NOTE: &str = "[TOOL_PROGRESS_REQUIRED] Before using more tools, briefly report \
[已确认事实] [剩余不确定性] [下一步]. Do not repeat prior evidence, and do not claim a result \
that has not been observed.";

    /// The old runtime abandoned the whole turn on the ninth tool round
    /// (`MAX_TOOL_ROUNDS`), so every round before it was lost. The desktop has
    /// no such cap, and neither does this loop.
    #[tokio::test]
    async fn a_long_tool_streak_runs_to_the_end_without_losing_a_round() {
        let executions = Arc::new(AtomicUsize::new(0));
        let model = Arc::new(StreakModel::new(12));
        let runtime = AgentRuntime::new(
            model.clone(),
            CountingTools {
                executions: executions.clone(),
            },
        );
        let result = runtime
            .run_turn(streak_request("turn-streak", TurnOptions::default()))
            .await
            .unwrap();

        assert_eq!(result.text, "完成了。");
        assert_eq!(result.tool_rounds, 12);
        assert_eq!(executions.load(Ordering::SeqCst), 12);
        assert!(result.runtime_warnings.is_empty());
        // Every round's call and result survives into the durable history.
        assert_eq!(
            count(&result.runtime_history, |message| matches!(
                message,
                Message::AssistantToolCalls { .. }
            )),
            12
        );
        assert_eq!(
            count(&result.runtime_history, |message| matches!(
                message,
                Message::Tool { .. }
            )),
            12
        );
        // And the model sees all of them, not just the last eight.
        let final_request = model.requests.lock().unwrap().last().cloned().unwrap();
        assert_eq!(
            count(&final_request, |message| matches!(
                message,
                Message::Tool { .. }
            )),
            12
        );
    }

    /// Desktop parity: after eight tool-only rounds the model is asked for a
    /// short progress note, once per round until it says something.
    #[tokio::test]
    async fn tool_only_rounds_are_asked_for_progress_and_a_narrated_round_resets_the_streak() {
        let silent = AgentRuntime::new(
            Arc::new(StreakModel::new(12)),
            CountingTools {
                executions: Arc::new(AtomicUsize::new(0)),
            },
        )
        .run_turn(streak_request("turn-gate", TurnOptions::default()))
        .await
        .unwrap();
        let notes = silent
            .runtime_history
            .iter()
            .filter(|message| matches!(message, Message::User { content } if content == PROGRESS_NOTE))
            .collect::<Vec<_>>();
        // Rounds 8, 9, 10, 11 and 12 are past the threshold.
        assert_eq!(notes.len(), 5);
        // The demand must be the desktop's sentence, word for word.

        let narrated = AgentRuntime::new(
            Arc::new(StreakModel {
                narrate_round: Some(9),
                ..StreakModel::new(12)
            }),
            CountingTools {
                executions: Arc::new(AtomicUsize::new(0)),
            },
        )
        .run_turn(streak_request("turn-gate-reset", TurnOptions::default()))
        .await
        .unwrap();
        let notes = narrated
            .runtime_history
            .iter()
            .filter(|message| matches!(message, Message::User { content } if content == PROGRESS_NOTE))
            .count();
        // The narrated round clears the streak, so only rounds 8 and 9 demand it.
        assert_eq!(notes, 2);
    }

    /// A host may tune or switch off the two thresholds, like every other
    /// desktop policy knob the runtime reads from `TurnOptions`.
    #[test]
    fn tool_round_policy_defaults_to_the_desktop_and_can_be_switched_off() {
        assert_eq!(
            TurnOptions::default().tool_only_round_limit(),
            Some(DEFAULT_TOOL_ONLY_ROUND_LIMIT)
        );
        assert_eq!(
            TurnOptions::default().identical_tool_result_limit(),
            Some(DEFAULT_IDENTICAL_TOOL_RESULT_LIMIT)
        );
        assert_eq!(
            TurnOptions::default().identical_tool_result_window(),
            DEFAULT_IDENTICAL_TOOL_RESULT_WINDOW
        );
        let disabled = TurnOptions {
            tool_only_round_limit: Some(0),
            identical_tool_result_limit: Some(0),
            ..Default::default()
        };
        assert_eq!(disabled.tool_only_round_limit(), None);
        assert_eq!(disabled.identical_tool_result_limit(), None);
        // A threshold below the window still has to be reachable.
        assert_eq!(
            TurnOptions {
                identical_tool_result_limit: Some(20),
                ..Default::default()
            }
            .identical_tool_result_window(),
            20
        );
    }

    /// The stop that replaces the cap: the same call and result ten times in the
    /// last twelve results ends the turn. Nothing is discarded and nothing is
    /// reported as an error — the model is asked to answer with what it has.
    #[tokio::test]
    async fn a_repeated_tool_result_ends_the_turn_recoverably() {
        let executions = Arc::new(AtomicUsize::new(0));
        let model = Arc::new(StreakModel {
            repeat_call: true,
            ..StreakModel::new(15)
        });
        let runtime = AgentRuntime::new(
            model.clone(),
            CountingTools {
                executions: executions.clone(),
            },
        );
        let result = runtime
            .run_turn(streak_request("turn-repeat", TurnOptions::default()))
            .await
            .unwrap();

        assert_eq!(result.tool_rounds, DEFAULT_IDENTICAL_TOOL_RESULT_LIMIT);
        assert_eq!(executions.load(Ordering::SeqCst), 10);
        assert_eq!(result.text, "按现有证据作答。");
        assert_eq!(result.runtime_warnings.len(), 1);
        assert!(
            result.runtime_warnings[0].contains("No progress observed")
                && result.runtime_warnings[0].contains("10 times"),
            "unexpected warning: {}",
            result.runtime_warnings[0]
        );
        // The ten rounds that ran are all still there.
        assert_eq!(
            count(&result.runtime_history, |message| matches!(
                message,
                Message::AssistantToolCalls { .. }
            )),
            10
        );
        assert_eq!(
            count(&result.runtime_history, |message| matches!(
                message,
                Message::Tool { .. }
            )),
            10
        );
        // The last request offered no tools, so the model had to answer.
        assert_eq!(*model.offered_tools.lock().unwrap().last().unwrap(), 0);
    }

    /// A Stop hook still observes the wind-down, but its objection cannot turn a
    /// recoverable end back into a failure.
    #[tokio::test]
    async fn a_hook_objection_is_recorded_when_a_repeated_step_ends_the_turn() {
        struct BlockingStop;

        #[async_trait]
        impl hooks::HookExecutor for BlockingStop {
            async fn run(&self, event: hooks::HookEvent) -> hooks::HookDecision {
                if event.event_name == hooks::EVENT_STOP {
                    return hooks::HookDecision {
                        decision: "block".into(),
                        reason: "stop rule".into(),
                        ..Default::default()
                    };
                }
                hooks::HookDecision::default()
            }
        }

        let runtime = AgentRuntime::new(
            Arc::new(StreakModel {
                repeat_call: true,
                ..StreakModel::new(15)
            }),
            CountingTools {
                executions: Arc::new(AtomicUsize::new(0)),
            },
        )
        .with_hook_executor(Arc::new(BlockingStop));
        let result = runtime
            .run_turn(streak_request("turn-repeat-hook", TurnOptions::default()))
            .await
            .unwrap();
        assert_eq!(result.text, "按现有证据作答。");
        assert_eq!(
            result.runtime_warnings,
            ["No progress observed: the same exact tool call and result occurred 10 times \
              within the last 12 tool results. The turn was ended and the model was asked to \
              answer with the evidence already collected."
                .to_owned(),
             "stop rule".to_owned()]
        );
    }

    struct GatedTools {
        executions: Arc<AtomicUsize>,
    }
    #[async_trait]
    impl ToolRuntime for GatedTools {
        fn definitions(&self, _capabilities: &DeviceCapabilities) -> Vec<ToolDefinition> {
            vec![ToolDefinition {
                name: "write_file".into(),
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
        assert_eq!(request.tool_call.name, "write_file");

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
                name: "write_file".into(),
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
                    session_approved_tools: vec!["write_file".into()],
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
