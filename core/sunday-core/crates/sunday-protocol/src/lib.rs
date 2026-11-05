//! Frozen contract for the Sunday core.
//!
//! This crate holds types and traits only. It must not perform IO, must not know
//! about SQLite, HTTP, Tauri, JNI or any operating system, and must not contain
//! business rules. If a rule needs to be enforced, it belongs one layer down.
//!
//! Architecture invariants (enforced by `scripts/check-deps.py` and by tests):
//!   I1  event seq is strictly increasing and contiguous per thread
//!   I2  one request_id produces at most one accepted execution
//!   I3  tool intent is durable before any side effect
//!   I4  a dispatched non-idempotent tool with no result becomes OutoundUnknown
//!       and is never replayed automatically
//!   I5  an approval is bound to a concrete argument digest
//!   I6  an expired approval is not consent
//!   I7  a thread runs one turn at a time; the rest queue
//!   I8  after cancel no new tool call starts, dispatched calls must finish
//!   I9  a projection can be rebuilt from the journal alone
//!   I10 no core crate references a platform host
//!   I11 errors are an enum, never a string
//!   I12 the approval the user saw is the call that executes

use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::time::Duration;

pub const PROTOCOL_VERSION: &str = "sunday.core.v1";

pub type DeviceId = String;
pub type WorkspaceId = String;
pub type ThreadId = String;
pub type RunId = String;
pub type TurnId = String;
pub type RequestId = String;

// ---------------------------------------------------------------- errors

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "code", rename_all = "snake_case")]
pub enum CoreError {
    Rejected { reason: String },
    UnsupportedCapability { capability: String },
    PermissionDenied { resource: String },
    RevisionConflict { expected: u64, actual: u64 },
    ProtocolIncompatible { min: u32, max: u32 },
    OutcomeUnknown { tool_call_id: String },
    ApprovalExpired { approval_id: String },
    ApprovalArgsMismatch { approval_id: String },
    InvalidRequest { reason: String },
    Storage { reason: String },
    Model { reason: String },
}

impl CoreError {
    pub fn storage(reason: impl std::fmt::Display) -> Self {
        Self::Storage {
            reason: reason.to_string(),
        }
    }
    pub fn invalid(reason: impl Into<String>) -> Self {
        Self::InvalidRequest {
            reason: reason.into(),
        }
    }
    pub fn model(reason: impl Into<String>) -> Self {
        Self::Model {
            reason: reason.into(),
        }
    }
    pub fn unsupported(capability: impl Into<String>) -> Self {
        Self::UnsupportedCapability {
            capability: capability.into(),
        }
    }

    /// Stable CLI exit codes. Distinct for every variant, never zero.
    pub fn exit_code(&self) -> i32 {
        match self {
            Self::Rejected { .. } => 10,
            Self::UnsupportedCapability { .. } => 11,
            Self::PermissionDenied { .. } => 12,
            Self::RevisionConflict { .. } => 13,
            Self::ProtocolIncompatible { .. } => 14,
            Self::OutcomeUnknown { .. } => 15,
            Self::ApprovalExpired { .. } => 16,
            Self::ApprovalArgsMismatch { .. } => 17,
            Self::InvalidRequest { .. } => 18,
            Self::Storage { .. } => 19,
            Self::Model { .. } => 20,
        }
    }

    /// Whether a caller may retry the same logical action.
    pub fn retryable(&self) -> bool {
        matches!(self, Self::Storage { .. })
    }
}

impl std::fmt::Display for CoreError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{:?}", self)
    }
}

impl std::error::Error for CoreError {}

// ---------------------------------------------------------------- model

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
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
    },
    AssistantToolCalls {
        calls: Vec<ToolCall>,
        content: Option<String>,
    },
    ToolResult {
        call_id: String,
        name: String,
        content: String,
    },
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ImageInput {
    pub mime: String,
    pub data_b64: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ToolCall {
    pub id: String,
    pub name: String,
    pub args: Value,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ToolDefinition {
    pub name: String,
    pub description: String,
    pub input_schema: Value,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Usage {
    pub input_tokens: u32,
    pub output_tokens: u32,
}

#[derive(Clone, Debug, PartialEq)]
pub struct ModelRequest {
    pub model_id: String,
    pub messages: Vec<Message>,
    pub tools: Vec<ToolDefinition>,
    /// f64 because JSON numbers are f64; an f32 here serialises as
    /// 0.20000000298023224 and providers reject it as out of range.
    pub temperature: Option<f64>,
    pub max_output_tokens: Option<u32>,
    /// Cancelling this stops the call as soon as the implementation notices.
    ///
    /// It is carried on the request rather than added as a `stream` parameter so
    /// that every existing implementation keeps its signature and a new one
    /// cannot forget to accept it.
    ///
    /// Cancelling is not a promise that the provider stops billing: it stops
    /// *this* client reading the stream. Say "stop receiving", never "free".
    pub cancel: CancelToken,
}

/// A cancellation signal shared by the loop, the model client and any future
/// host. Cloneable and cheap: every clone observes the same flag.
#[derive(Clone, Debug, Default)]
pub struct CancelToken {
    flag: std::sync::Arc<std::sync::atomic::AtomicBool>,
}

impl CancelToken {
    pub fn new() -> Self {
        Self::default()
    }

    /// Raises the flag. Idempotent: cancelling twice is not an error.
    pub fn cancel(&self) {
        self.flag.store(true, std::sync::atomic::Ordering::SeqCst);
    }

    pub fn is_cancelled(&self) -> bool {
        self.flag.load(std::sync::atomic::Ordering::SeqCst)
    }

    /// Clears the flag for reuse. A turn that ended should not leave the next
    /// one already cancelled, which is the mistake a shared flag invites.
    pub fn reset(&self) {
        self.flag.store(false, std::sync::atomic::Ordering::SeqCst);
    }
}

/// Two tokens are equal when they are the same signal, not when they happen to
/// hold the same value: a cancelled token and a token that was cancelled are
/// different things to whoever holds them.
impl PartialEq for CancelToken {
    fn eq(&self, other: &Self) -> bool {
        std::sync::Arc::ptr_eq(&self.flag, &other.flag)
    }
}

impl Eq for CancelToken {}

#[derive(Clone, Debug, PartialEq)]
pub enum ModelDelta {
    Text(String),
    Reasoning(String),
    ToolCallDelta {
        index: usize,
        id: Option<String>,
        name: Option<String>,
        args_fragment: String,
    },
    Usage(Usage),
}

#[derive(Clone, Debug, PartialEq)]
pub struct ModelTurn {
    pub text: Option<String>,
    pub reasoning: Option<String>,
    pub tool_calls: Vec<ToolCall>,
    pub usage: Option<Usage>,
    pub provider_state: Option<String>,
}

#[async_trait::async_trait]
pub trait Model: Send + Sync {
    /// Increments are delivered through the sink in order.
    ///
    /// An implementation must not retry after it has handed the sink any delta:
    /// the caller cannot unsend an event it already committed.
    async fn stream(
        &self,
        request: ModelRequest,
        sink: &mut (dyn FnMut(ModelDelta) + Send),
    ) -> Result<ModelTurn, CoreError>;
}

// ---------------------------------------------------------------- tools

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SideEffect {
    Pure,
    Idempotent,
    NonIdempotent,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum HostKind {
    Windows,
    Android,
    Server,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Permission {
    AutoAllow,
    AskUser,
    HardBlock,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ToolSpec {
    pub id: String,
    pub description: String,
    pub input_schema: Value,
    pub side_effect: SideEffect,
    pub hosts: Vec<HostKind>,
    pub permission: Permission,
}

impl ToolSpec {
    pub fn available_on(&self, host: HostKind) -> bool {
        self.hosts.contains(&host)
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ToolOutput {
    pub content: String,
    pub is_error: bool,
}

#[derive(Clone, Debug, Default)]
pub struct ToolCtx {
    pub thread_id: ThreadId,
    pub host: Option<HostKind>,
}

#[async_trait::async_trait]
pub trait Tool: Send + Sync {
    fn spec(&self) -> &ToolSpec;
    async fn execute(&self, args: Value, ctx: &ToolCtx) -> Result<ToolOutput, CoreError>;
}

/// The only place a platform difference may change behaviour.
pub fn visible_tools(tools: &[&dyn Tool], host: HostKind) -> Vec<ToolDefinition> {
    tools
        .iter()
        .filter(|t| t.spec().available_on(host) && t.spec().permission != Permission::HardBlock)
        .map(|t| ToolDefinition {
            name: t.spec().id.clone(),
            description: t.spec().description.clone(),
            input_schema: t.spec().input_schema.clone(),
        })
        .collect()
}

// ---------------------------------------------------------------- events

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EventKind {
    CommandAccepted,
    RunStarted,
    ModelStarted,
    ModelCompleted,
    ToolPrepared,
    ApprovalRequested,
    ApprovalResolved,
    ToolDispatched,
    ToolSucceeded,
    ToolFailed,
    ToolOutcomeUnknown,
    ToolReplayed,
    GuidanceReceived,
    RunCancelled,
    RunCompleted,
    RunWaitingForReconciliation,
    /// The message list was summarised to stay inside the budget.
    ContextCompacted,
}

impl EventKind {
    /// Consumers must ignore kinds they do not know; this list is append-only.
    pub fn as_str(self) -> &'static str {
        match self {
            Self::CommandAccepted => "command_accepted",
            Self::RunStarted => "run_started",
            Self::ModelStarted => "model_started",
            Self::ModelCompleted => "model_completed",
            Self::ToolPrepared => "tool_prepared",
            Self::ApprovalRequested => "approval_requested",
            Self::ApprovalResolved => "approval_resolved",
            Self::ToolDispatched => "tool_dispatched",
            Self::ToolSucceeded => "tool_succeeded",
            Self::ToolFailed => "tool_failed",
            Self::ToolOutcomeUnknown => "tool_outcome_unknown",
            Self::ToolReplayed => "tool_replayed",
            Self::GuidanceReceived => "guidance_received",
            Self::RunCancelled => "run_cancelled",
            Self::RunCompleted => "run_completed",
            Self::RunWaitingForReconciliation => "run_waiting_for_reconciliation",
            Self::ContextCompacted => "context_compacted",
        }
    }

    pub fn parse(text: &str) -> Option<Self> {
        Some(match text {
            "command_accepted" => Self::CommandAccepted,
            "run_started" => Self::RunStarted,
            "model_started" => Self::ModelStarted,
            "model_completed" => Self::ModelCompleted,
            "tool_prepared" => Self::ToolPrepared,
            "approval_requested" => Self::ApprovalRequested,
            "approval_resolved" => Self::ApprovalResolved,
            "tool_dispatched" => Self::ToolDispatched,
            "tool_succeeded" => Self::ToolSucceeded,
            "tool_failed" => Self::ToolFailed,
            "tool_outcome_unknown" => Self::ToolOutcomeUnknown,
            "tool_replayed" => Self::ToolReplayed,
            "guidance_received" => Self::GuidanceReceived,
            "run_cancelled" => Self::RunCancelled,
            "run_completed" => Self::RunCompleted,
            "run_waiting_for_reconciliation" => Self::RunWaitingForReconciliation,
            "context_compacted" => Self::ContextCompacted,
            _ => return None,
        })
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Event {
    pub thread_id: ThreadId,
    pub seq: u64,
    pub event_id: String,
    pub kind: EventKind,
    pub payload: Value,
    /// When the journal row was written, in epoch milliseconds.
    ///
    /// The journal has always stored this; the read path simply did not bring it back,
    /// so every replay invented a time and a message from last week was displayed at the
    /// moment the app was reopened. 0 means the producer did not know, which is how an
    /// event serialized before this field existed still parses.
    #[serde(default)]
    pub created_at: i64,
}

// ---------------------------------------------------------------- commands

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum Command {
    TurnStart {
        text: String,
        /// The client's input items, verbatim JSON, when it sent more than text.
        ///
        /// A turn can carry files, and the transcript has to show them again after a
        /// restart: the journal is the only thing that survives one, so what the user
        /// attached is journalled next to what they typed. Text stays separate because it
        /// is the part the core itself reads and every reader already has it.
        ///
        /// A string rather than a typed value because the item shape belongs to the
        /// client; storing it as it arrived cannot drift from what the screen sent.
        #[serde(default, skip_serializing_if = "String::is_empty")]
        input_json: String,
    },
    TurnCancel,
    ApprovalRespond {
        approval_id: String,
        args_digest: String,
        approve: bool,
    },
    ThreadArchive,
}

impl Command {
    pub fn kind(&self) -> &'static str {
        match self {
            Self::TurnStart { .. } => "turn_start",
            Self::TurnCancel => "turn_cancel",
            Self::ApprovalRespond { .. } => "approval_respond",
            Self::ThreadArchive => "thread_archive",
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct CommandEnvelope {
    pub protocol_version: String,
    pub request_id: RequestId,
    pub thread_id: ThreadId,
    /// Optimistic concurrency. `None` means "do not check".
    pub expected_revision: Option<u64>,
    pub payload: Command,
}

impl CommandEnvelope {
    /// A stable digest of the payload, so a resent request_id with a different
    /// body cannot silently reuse an old receipt.
    pub fn payload_digest(&self) -> String {
        let text = serde_json::to_string(&self.payload).unwrap_or_default();
        digest_str(&text)
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CommandStatus {
    Rejected,
    Accepted,
    Running,
    Completed,
    Failed,
    OutcomeUnknown,
}

impl CommandStatus {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Rejected => "rejected",
            Self::Accepted => "accepted",
            Self::Running => "running",
            Self::Completed => "completed",
            Self::Failed => "failed",
            Self::OutcomeUnknown => "outcome_unknown",
        }
    }
    pub fn parse(text: &str) -> Option<Self> {
        Some(match text {
            "rejected" => Self::Rejected,
            "accepted" => Self::Accepted,
            "running" => Self::Running,
            "completed" => Self::Completed,
            "failed" => Self::Failed,
            "outcome_unknown" => Self::OutcomeUnknown,
            _ => return None,
        })
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct CommandReceipt {
    pub request_id: RequestId,
    pub status: CommandStatus,
    pub thread_id: ThreadId,
    pub seq: Option<u64>,
    pub revision: u64,
}

// ---------------------------------------------------------------- tool stages

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ToolStage {
    Prepared,
    Approved,
    Dispatched,
    Succeeded,
    Failed,
    Unknown,
}

impl ToolStage {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Prepared => "prepared",
            Self::Approved => "approved",
            Self::Dispatched => "dispatched",
            Self::Succeeded => "succeeded",
            Self::Failed => "failed",
            Self::Unknown => "unknown",
        }
    }
    pub fn parse(text: &str) -> Option<Self> {
        Some(match text {
            "prepared" => Self::Prepared,
            "approved" => Self::Approved,
            "dispatched" => Self::Dispatched,
            "succeeded" => Self::Succeeded,
            "failed" => Self::Failed,
            "unknown" => Self::Unknown,
            _ => return None,
        })
    }
}

/// The answer to "may I run this call?" asked before any side effect.
#[derive(Clone, Debug, PartialEq)]
pub enum Prepared {
    Ready,
    /// Already ran and its result is durable. Replay the stored result.
    AlreadyDone,
    /// Dispatched once, no result recorded. A human must reconcile.
    MustReconcile,
}

// ---------------------------------------------------------------- approvals

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ApprovalRequest {
    pub approval_id: String,
    pub thread_id: ThreadId,
    pub tool_call_id: String,
    pub tool_id: String,
    pub args_digest: String,
    pub expires_at_epoch: u64,
}

// ---------------------------------------------------------------- runs

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct RunBudget {
    pub max_rounds: u32,
    pub max_tool_calls: u32,
    pub wall_clock: Duration,
}

impl Default for RunBudget {
    fn default() -> Self {
        Self {
            max_rounds: 16,
            max_tool_calls: 64,
            wall_clock: Duration::from_secs(1800),
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum BudgetReason {
    Rounds,
    ToolCalls,
    WallClock,
}

#[derive(Clone, Debug, PartialEq)]
pub enum RunOutcome {
    Completed { text: String },
    Cancelled,
    WaitingForReconciliation { tool_call_id: String, hint: String },
    NeedsApproval { approval_id: String },
    BudgetExhausted { reason: BudgetReason },
}

// ---------------------------------------------------------------- digests

/// FNV-1a over the UTF-8 bytes. Stable across runs and platforms, unlike
/// `DefaultHasher`, and short enough to store as an index key.
pub fn digest_str(text: &str) -> String {
    let mut hash: u64 = 0xcbf2_9ce4_8422_2325;
    for byte in text.as_bytes() {
        hash ^= *byte as u64;
        hash = hash.wrapping_mul(0x0000_0100_0000_01b3);
    }
    format!("{hash:016x}:{}", text.len())
}

pub fn digest_json(value: &Value) -> String {
    // serde_json serialises object keys in insertion order; sort them so two
    // structurally equal argument objects always produce the same digest.
    digest_str(&canonical(value))
}

fn canonical(value: &Value) -> String {
    match value {
        Value::Object(map) => {
            let mut keys: Vec<&String> = map.keys().collect();
            keys.sort();
            let body: Vec<String> = keys
                .into_iter()
                .map(|k| format!("{}:{}", k, canonical(&map[k])))
                .collect();
            format!("{{{}}}", body.join(","))
        }
        Value::Array(items) => {
            let body: Vec<String> = items.iter().map(canonical).collect();
            format!("[{}]", body.join(","))
        }
        other => other.to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_error_has_a_distinct_nonzero_exit_code() {
        let all = [
            CoreError::Rejected {
                reason: String::new(),
            },
            CoreError::UnsupportedCapability {
                capability: String::new(),
            },
            CoreError::PermissionDenied {
                resource: String::new(),
            },
            CoreError::RevisionConflict {
                expected: 0,
                actual: 1,
            },
            CoreError::ProtocolIncompatible { min: 1, max: 0 },
            CoreError::OutcomeUnknown {
                tool_call_id: String::new(),
            },
            CoreError::ApprovalExpired {
                approval_id: String::new(),
            },
            CoreError::ApprovalArgsMismatch {
                approval_id: String::new(),
            },
            CoreError::InvalidRequest {
                reason: String::new(),
            },
            CoreError::Storage {
                reason: String::new(),
            },
            CoreError::Model {
                reason: String::new(),
            },
        ];
        let mut codes: Vec<i32> = all.iter().map(|e| e.exit_code()).collect();
        codes.sort_unstable();
        let distinct = {
            let mut c = codes.clone();
            c.dedup();
            c.len()
        };
        assert_eq!(distinct, all.len(), "exit codes must be unique");
        assert!(
            codes.iter().all(|c| *c != 0),
            "no error may look like success"
        );
    }

    #[test]
    fn digests_ignore_object_key_order() {
        let a: Value = serde_json::from_str(r#"{"a":1,"b":{"c":2,"d":3}}"#).unwrap();
        let b: Value = serde_json::from_str(r#"{"b":{"d":3,"c":2},"a":1}"#).unwrap();
        assert_eq!(digest_json(&a), digest_json(&b));
    }

    #[test]
    fn digests_change_when_a_value_changes() {
        let a: Value = serde_json::from_str(r#"{"path":"a.txt"}"#).unwrap();
        let b: Value = serde_json::from_str(r#"{"path":"b.txt"}"#).unwrap();
        assert_ne!(digest_json(&a), digest_json(&b));
    }

    #[test]
    fn event_kind_round_trips_and_unknown_is_rejected() {
        for kind in [
            EventKind::CommandAccepted,
            EventKind::ToolOutcomeUnknown,
            EventKind::RunWaitingForReconciliation,
        ] {
            assert_eq!(EventKind::parse(kind.as_str()), Some(kind));
        }
        assert_eq!(EventKind::parse("something_new"), None);
    }

    #[test]
    fn hard_blocked_and_foreign_host_tools_never_reach_the_model() {
        fn spec(id: &str, perm: Permission, hosts: Vec<HostKind>) -> ToolSpec {
            ToolSpec {
                id: id.into(),
                description: String::new(),
                input_schema: serde_json::json!({"type": "object"}),
                side_effect: SideEffect::Pure,
                hosts,
                permission: perm,
            }
        }
        struct T(ToolSpec);
        #[async_trait::async_trait]
        impl Tool for T {
            fn spec(&self) -> &ToolSpec {
                &self.0
            }
            async fn execute(&self, _a: Value, _c: &ToolCtx) -> Result<ToolOutput, CoreError> {
                Ok(ToolOutput {
                    content: String::new(),
                    is_error: false,
                })
            }
        }
        let ok = T(spec(
            "read_file",
            Permission::AutoAllow,
            vec![HostKind::Windows, HostKind::Android],
        ));
        let blocked = T(spec(
            "danger",
            Permission::HardBlock,
            vec![HostKind::Windows],
        ));
        let windows_only = T(spec("ps", Permission::AutoAllow, vec![HostKind::Windows]));
        let list: Vec<&dyn Tool> = vec![&ok, &blocked, &windows_only];

        assert_eq!(visible_tools(&list, HostKind::Android).len(), 1);
        assert_eq!(visible_tools(&list, HostKind::Windows).len(), 2);
    }
}
