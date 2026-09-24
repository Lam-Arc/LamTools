use async_trait::async_trait;
use lamtools_runtime::{
    hooks::{HookDecision, HookEvent, HookExecutor, EVENT_PRE_TOOL_USE},
    AgentRuntime, DeviceCapabilities, Message, ModelBackend, ModelTurn,
    RuntimeError, ToolCall, ToolDefinition, ToolRuntime, TurnOptions, TurnProgress, TurnRequest,
};
use serde_json::{json, Value};
use std::sync::{atomic::{AtomicUsize, Ordering}, Arc};

struct Model { calls: AtomicUsize }
#[async_trait]
impl ModelBackend for Model {
    async fn complete(&self, _: &str, _: &[Message], _: &[ToolDefinition], _: &TurnOptions) -> Result<ModelTurn, RuntimeError> {
        if self.calls.fetch_add(1, Ordering::SeqCst) == 0 {
            Ok(ModelTurn::ToolCalls { calls: vec![ToolCall { id: "a".into(), name: "auto_test".into(), arguments: json!({}) }], provider_state: Value::Null })
        } else {
            Ok(ModelTurn::Text { text: "done".into(), reasoning: String::new(), provider_state: Value::Null })
        }
    }
}
struct Tool { calls: Arc<AtomicUsize> }
#[async_trait]
impl ToolRuntime for Tool {
    fn definitions(&self, _: &DeviceCapabilities) -> Vec<ToolDefinition> {
        vec![ToolDefinition { name: "auto_test".into(), description: "test".into(), input_schema: json!({"type":"object"}) }]
    }
    async fn execute(&self, _: &ToolCall) -> Result<Value, RuntimeError> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        Ok(json!({"ok":true}))
    }
}
struct Hook { policy: String }
#[async_trait]
impl HookExecutor for Hook {
    async fn run(&self, event: HookEvent) -> HookDecision {
        if event.event_name == EVENT_PRE_TOOL_USE {
            HookDecision { permission_decision: self.policy.clone(), permission_decision_reason: "audit rule".into(), ..Default::default() }
        } else { HookDecision::default() }
    }
}
#[tokio::main]
async fn main() {
    for policy in ["deny", "ask_user"] {
        let calls = Arc::new(AtomicUsize::new(0));
        let runtime = AgentRuntime::new(Model { calls: AtomicUsize::new(0) }, Tool { calls: calls.clone() })
            .with_hook_executor(Arc::new(Hook { policy: policy.into() }));
        let progress = runtime.run_turn_progress(TurnRequest {
            turn_id: policy.into(), model_record_id: "fixture".into(), history: vec![Message::User { content: "test".into() }],
            capabilities: DeviceCapabilities::default(), context: Default::default(), hook_context: Default::default(), options: Default::default(),
        }).await.unwrap();
        let status = match progress { TurnProgress::Completed { .. } => "completed", TurnProgress::ApprovalRequired { .. } => "approval_required" };
        println!("policy={policy} status={status} auto_tool_execute_count={}", calls.load(Ordering::SeqCst));
    }
}
