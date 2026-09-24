use crate::{
    hooks::{HookExecutor, HookRunContext},
    mcp::CompositeToolRuntime,
    provider::{HttpModelBackend, ProviderConfig},
    AgentContext, AgentRuntime, ApprovalRequest, ApprovalResponse, DeviceCapabilities,
    GuidanceSource, Message, ModelBackend, PermissionPreset, RuntimeError, ToolCall,
    ToolDefinition, ToolPermission, ToolRuntime, TurnContinuation, TurnOptions, TurnProgress,
    TurnRequest,
};
use async_trait::async_trait;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{
    collections::BTreeMap,
    sync::{Arc, Mutex as StdMutex},
    time::{SystemTime, UNIX_EPOCH},
};
use tokio::{
    sync::{Mutex, RwLock},
    task::JoinHandle,
};
use uuid::Uuid;

pub const SUB_AGENT_TOOL: &str = "sub_agent";
pub const SUB_AGENT_MESSAGE_TOOL: &str = "sub_agent_message";
pub const CHILD_MESSAGE_TOOL: &str = "message";

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct SubAgentModelEntry {
    pub id: String,
    pub display_name: String,
    pub provider: ProviderConfig,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct SubAgentRecord {
    pub parent_thread_id: String,
    #[serde(rename = "type")]
    pub agent_type: String,
    pub name: String,
    pub model_id: String,
    pub reasoning_level: String,
    pub status: String,
    #[serde(default)]
    pub summary: String,
    pub started_at: Option<u64>,
    pub completed_at: Option<u64>,
    pub elapsed_ms: Option<u64>,
    pub sub_session_id: String,
    #[serde(default)]
    pub source_call_id: String,
    #[serde(default)]
    pub source_run_id: String,
    #[serde(default)]
    pub source_turn_id: String,
    #[serde(default)]
    pub history: Vec<Message>,
    pub continuation: Option<TurnContinuation>,
    pub approval_request: Option<ApprovalRequest>,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct SubAgentMail {
    pub id: String,
    pub parent_thread_id: String,
    pub name: String,
    pub direction: String,
    pub body: String,
    pub message_key: String,
    pub created_at: u64,
    pub delivered_at: Option<u64>,
}

pub trait SubAgentStore: Send + Sync {
    fn recover_running(&self, parent_thread_id: &str) -> Result<(), String>;
    fn load(&self, parent_thread_id: &str, name: &str) -> Result<Option<SubAgentRecord>, String>;
    fn save(&self, record: &SubAgentRecord) -> Result<(), String>;
    fn list(&self, parent_thread_id: &str) -> Result<Vec<SubAgentRecord>, String>;
    fn insert_mail(&self, mail: &SubAgentMail) -> Result<bool, String>;
    fn undelivered(
        &self,
        parent_thread_id: &str,
        name: Option<&str>,
        direction: &str,
    ) -> Result<Vec<SubAgentMail>, String>;
    fn mark_delivered(&self, ids: &[String], delivered_at: u64) -> Result<(), String>;
}

#[derive(Clone)]
pub struct SubAgentParentConfig {
    pub models: Vec<SubAgentModelEntry>,
    pub child_tools: Arc<dyn ToolRuntime>,
    pub capabilities: DeviceCapabilities,
    pub context: AgentContext,
    pub options: TurnOptions,
    pub hook_context: HookRunContext,
    pub hooks: Option<Arc<dyn HookExecutor>>,
}

pub struct SubAgentHub {
    store: Arc<dyn SubAgentStore>,
    configs: RwLock<BTreeMap<String, SubAgentParentConfig>>,
    tasks: Mutex<BTreeMap<(String, String), JoinHandle<()>>>,
}

impl SubAgentHub {
    pub fn new(store: Arc<dyn SubAgentStore>) -> Arc<Self> {
        Arc::new(Self {
            store,
            configs: RwLock::new(BTreeMap::new()),
            tasks: Mutex::new(BTreeMap::new()),
        })
    }

    pub async fn configure_parent(
        self: &Arc<Self>,
        parent_thread_id: &str,
        config: SubAgentParentConfig,
    ) -> Result<(), String> {
        let mut configs = self.configs.write().await;
        if !configs.contains_key(parent_thread_id) {
            self.store.recover_running(parent_thread_id)?;
        }
        configs.insert(parent_thread_id.to_owned(), config);
        Ok(())
    }

    pub fn tools(self: &Arc<Self>, parent_thread_id: impl Into<String>) -> SubAgentTools {
        SubAgentTools {
            hub: self.clone(),
            parent_thread_id: parent_thread_id.into(),
        }
    }

    pub fn parent_guidance(
        self: &Arc<Self>,
        parent_thread_id: impl Into<String>,
    ) -> Arc<dyn GuidanceSource> {
        Arc::new(MailboxGuidance {
            hub: self.clone(),
            parent_thread_id: parent_thread_id.into(),
            name: None,
            direction: "child_to_parent".into(),
            persist_in_child_history: false,
        })
    }

    pub fn list(&self, parent_thread_id: &str) -> Result<Vec<SubAgentRecord>, String> {
        self.store.list(parent_thread_id)
    }

    pub async fn respond_approval(
        self: &Arc<Self>,
        parent_thread_id: &str,
        name: &str,
        response: ApprovalResponse,
    ) -> Result<(), String> {
        let record = self
            .store
            .load(parent_thread_id, name)?
            .ok_or_else(|| format!("sub-agent not found: {name}"))?;
        if record.status != "paused" {
            return Err("sub-agent is not waiting for approval".into());
        }
        let continuation = record
            .continuation
            .clone()
            .ok_or_else(|| "sub-agent approval continuation is missing".to_owned())?;
        let expected = record
            .approval_request
            .as_ref()
            .ok_or_else(|| "sub-agent approval request is missing".to_owned())?;
        if expected.request_id != response.request_id {
            return Err("approval request does not match sub-agent continuation".into());
        }
        self.spawn_resume(
            parent_thread_id.to_owned(),
            name.to_owned(),
            continuation,
            response,
        )
        .await
    }

    async fn create(&self, parent_thread_id: &str, call: &ToolCall) -> Result<Value, RuntimeError> {
        let arguments = object_arguments(call)?;
        require_exact_keys(
            arguments,
            &["action", "type", "name", "model", "reasoning_level"],
            "sub_agent requires exactly action,type,name,model,reasoning_level",
        )?;
        let action = string_argument(arguments, "action")?;
        let agent_type = validate_type(string_argument(arguments, "type")?)?;
        let name = validate_name(string_argument(arguments, "name")?)?;
        let model = string_argument(arguments, "model")?;
        let reasoning_level = validate_reasoning(string_argument(arguments, "reasoning_level")?)?;
        let config = self
            .configs
            .read()
            .await
            .get(parent_thread_id)
            .cloned()
            .ok_or_else(|| RuntimeError::Tool("sub-agent runtime is not configured".into()))?;
        let model_id = resolve_model(&config.models, model)?.id.clone();
        let existing = self
            .store
            .load(parent_thread_id, name)
            .map_err(RuntimeError::Tool)?;
        if action == "close" {
            let mut record = existing
                .ok_or_else(|| RuntimeError::Tool(format!("sub-agent not found: {name}")))?;
            if (
                record.agent_type.as_str(),
                record.model_id.as_str(),
                record.reasoning_level.as_str(),
            ) != (agent_type, model_id.as_str(), reasoning_level)
            {
                return Err(RuntimeError::Tool(
                    "close configuration does not match the durable sub-agent record".into(),
                ));
            }
            record.status = "closed".into();
            record.completed_at = Some(now_ms());
            record.elapsed_ms = record
                .started_at
                .map(|started| now_ms().saturating_sub(started));
            record.continuation = None;
            record.approval_request = None;
            self.store.save(&record).map_err(RuntimeError::Tool)?;
            if let Some(task) = self
                .tasks
                .lock()
                .await
                .remove(&(parent_thread_id.to_owned(), name.to_owned()))
            {
                task.abort();
            }
            return Ok(operation_payload(&record, "closed"));
        }
        if action != "create" {
            return Err(RuntimeError::Tool(
                "action must be exactly 'create' or 'close'".into(),
            ));
        }
        let lifecycle_action = if let Some(mut record) = existing {
            if record.status != "closed"
                && record.status != "interrupted"
                && record.status != "failed"
            {
                if (
                    record.agent_type.as_str(),
                    record.model_id.as_str(),
                    record.reasoning_level.as_str(),
                ) != (agent_type, model_id.as_str(), reasoning_level)
                {
                    return Err(RuntimeError::Tool(
                        "active sub-agent exists with a different configuration".into(),
                    ));
                }
                record.source_call_id = call.id.clone();
                self.store.save(&record).map_err(RuntimeError::Tool)?;
                return Ok(operation_payload(&record, "enabled"));
            }
            if (
                record.agent_type.as_str(),
                record.model_id.as_str(),
                record.reasoning_level.as_str(),
            ) != (agent_type, model_id.as_str(), reasoning_level)
            {
                return Err(RuntimeError::Tool(
                    "closed sub-agent can only be reopened with its exact configuration".into(),
                ));
            }
            record.status = "idle".into();
            record.completed_at = None;
            record.elapsed_ms = None;
            record.source_call_id = call.id.clone();
            self.store.save(&record).map_err(RuntimeError::Tool)?;
            return Ok(operation_payload(&record, "enabled"));
        } else {
            "created"
        };
        let record = SubAgentRecord {
            parent_thread_id: parent_thread_id.into(),
            agent_type: agent_type.into(),
            name: name.into(),
            model_id,
            reasoning_level: reasoning_level.into(),
            status: "idle".into(),
            summary: String::new(),
            started_at: None,
            completed_at: None,
            elapsed_ms: None,
            sub_session_id: format!("{parent_thread_id}:sub:{name}"),
            source_call_id: call.id.clone(),
            source_run_id: String::new(),
            source_turn_id: String::new(),
            history: Vec::new(),
            continuation: None,
            approval_request: None,
        };
        self.store.save(&record).map_err(RuntimeError::Tool)?;
        Ok(operation_payload(&record, lifecycle_action))
    }

    async fn message(
        self: &Arc<Self>,
        parent_thread_id: &str,
        call: &ToolCall,
    ) -> Result<Value, RuntimeError> {
        let arguments = object_arguments(call)?;
        require_exact_keys(
            arguments,
            &["type", "name", "prompt"],
            "sub_agent_message requires exactly type,name,prompt",
        )?;
        let agent_type = validate_type(string_argument(arguments, "type")?)?;
        let name = validate_name(string_argument(arguments, "name")?)?;
        let prompt = string_argument(arguments, "prompt")?.trim();
        if prompt.is_empty() {
            return Err(RuntimeError::Tool("prompt is required".into()));
        }
        let mut record = self
            .store
            .load(parent_thread_id, name)
            .map_err(RuntimeError::Tool)?
            .ok_or_else(|| RuntimeError::Tool(format!("sub-agent not found: {name}")))?;
        if record.agent_type != agent_type
            || matches!(record.status.as_str(), "closed" | "interrupted" | "failed")
        {
            return Err(RuntimeError::Tool(
                "sub-agent must exist, match type, and be active".into(),
            ));
        }
        let mail = SubAgentMail {
            id: Uuid::new_v4().simple().to_string(),
            parent_thread_id: parent_thread_id.into(),
            name: name.into(),
            direction: "parent_to_child".into(),
            body: prompt.into(),
            message_key: call.id.clone(),
            created_at: now_ms(),
            delivered_at: None,
        };
        let inserted = self.store.insert_mail(&mail).map_err(RuntimeError::Tool)?;
        if inserted {
            record.history.push(Message::User {
                content: prompt.into(),
            });
            record.source_call_id = call.id.clone();
            self.store.save(&record).map_err(RuntimeError::Tool)?;
            self.start_if_idle(parent_thread_id.to_owned(), name.to_owned())
                .await?;
        }
        Ok(serde_json::json!({
            "accepted": true,
            "deduplicated": !inserted,
            "type": agent_type,
            "name": name,
            "lifecycle_action": "message_sent",
        }))
    }

    async fn start_if_idle(
        self: &Arc<Self>,
        parent_thread_id: String,
        name: String,
    ) -> Result<(), RuntimeError> {
        let key = (parent_thread_id.clone(), name.clone());
        let mut tasks = self.tasks.lock().await;
        if tasks.get(&key).is_some_and(|task| !task.is_finished()) {
            return Ok(());
        }
        let hub = self.clone();
        let cleanup_key = key.clone();
        let task = tokio::spawn(async move {
            hub.drive(parent_thread_id, name).await;
            hub.tasks.lock().await.remove(&cleanup_key);
        });
        tasks.insert(key, task);
        Ok(())
    }

    async fn spawn_resume(
        self: &Arc<Self>,
        parent_thread_id: String,
        name: String,
        continuation: TurnContinuation,
        response: ApprovalResponse,
    ) -> Result<(), String> {
        let key = (parent_thread_id.clone(), name.clone());
        let mut tasks = self.tasks.lock().await;
        if tasks.get(&key).is_some_and(|task| !task.is_finished()) {
            return Err("sub-agent is already running".into());
        }
        let hub = self.clone();
        let cleanup_key = key.clone();
        let task = tokio::spawn(async move {
            hub.resume_child(parent_thread_id, name, continuation, response)
                .await;
            hub.tasks.lock().await.remove(&cleanup_key);
        });
        tasks.insert(key, task);
        Ok(())
    }

    async fn drive(self: &Arc<Self>, parent_thread_id: String, name: String) {
        let result = self.run_child(&parent_thread_id, &name, None).await;
        if let Err(error) = result {
            let _ = self.fail_record(&parent_thread_id, &name, &error);
        }
    }

    async fn resume_child(
        self: &Arc<Self>,
        parent_thread_id: String,
        name: String,
        continuation: TurnContinuation,
        response: ApprovalResponse,
    ) {
        let result = self
            .run_child(&parent_thread_id, &name, Some((continuation, response)))
            .await;
        if let Err(error) = result {
            let _ = self.fail_record(&parent_thread_id, &name, &error);
        }
    }

    async fn run_child(
        self: &Arc<Self>,
        parent_thread_id: &str,
        name: &str,
        resume: Option<(TurnContinuation, ApprovalResponse)>,
    ) -> Result<(), String> {
        let config = self
            .configs
            .read()
            .await
            .get(parent_thread_id)
            .cloned()
            .ok_or_else(|| "sub-agent runtime is not configured".to_owned())?;
        let mut record = self
            .store
            .load(parent_thread_id, name)?
            .ok_or_else(|| format!("sub-agent not found: {name}"))?;
        if record.status == "closed" {
            return Ok(());
        }
        let model_entry = resolve_model(&config.models, &record.model_id)
            .map_err(|error| error.to_string())?
            .clone();
        let model: Arc<dyn ModelBackend> = Arc::new(
            HttpModelBackend::new(model_entry.provider).map_err(|error| error.to_string())?,
        );
        let child_message: Arc<dyn ToolRuntime> = Arc::new(ChildMessageTools {
            hub: self.clone(),
            parent_thread_id: parent_thread_id.into(),
            name: name.into(),
        });
        let filtered: Arc<dyn ToolRuntime> = Arc::new(FilteredChildTools {
            inner: config.child_tools.clone(),
            read_only: record.agent_type == "consider",
        });
        let tools = CompositeToolRuntime::new(&config.capabilities, vec![filtered, child_message]);
        let mut runtime =
            AgentRuntime::new(model, tools).with_guidance_source(Arc::new(MailboxGuidance {
                hub: self.clone(),
                parent_thread_id: parent_thread_id.into(),
                name: Some(name.into()),
                direction: "parent_to_child".into(),
                persist_in_child_history: false,
            }));
        if let Some(hooks) = config.hooks {
            runtime = runtime.with_hook_executor(hooks);
        }
        let started = record.started_at.unwrap_or_else(now_ms);
        record.status = "running".into();
        record.started_at = Some(started);
        record.completed_at = None;
        record.elapsed_ms = None;
        record.continuation = None;
        record.approval_request = None;
        self.store.save(&record)?;

        let progress = if let Some((continuation, response)) = resume {
            runtime
                .resume_turn(continuation, response)
                .await
                .map_err(|error| error.to_string())?
        } else {
            let mut context = config.context;
            let role_context = format!(
                "[Sub-agent]\nname: {}\ntype: {}\nparent_thread_id: {}\nNested delegation is disabled.",
                record.name, record.agent_type, parent_thread_id
            );
            if !context.mode_context.is_empty() {
                context.mode_context.push_str("\n\n");
            }
            context.mode_context.push_str(&role_context);
            let mut options = config.options;
            options.reasoning_level = record.reasoning_level.clone();
            options.permission_preset = PermissionPreset::Ask;
            let mut hook_context = config.hook_context;
            hook_context.session_id = record.sub_session_id.clone();
            hook_context.run_id = format!("sub-{}", Uuid::new_v4().simple());
            runtime
                .run_turn_progress(TurnRequest {
                    turn_id: hook_context.run_id.clone(),
                    model_record_id: record.model_id.clone(),
                    history: record.history.clone(),
                    capabilities: config.capabilities,
                    context,
                    hook_context,
                    options,
                })
                .await
                .map_err(|error| error.to_string())?
        };
        self.finish_progress(record, progress)
    }

    fn finish_progress(
        &self,
        mut record: SubAgentRecord,
        progress: TurnProgress,
    ) -> Result<(), String> {
        match progress {
            TurnProgress::Completed { result } => {
                record.history = result.runtime_history;
                record.summary = result.text.chars().take(1000).collect();
                record.status = "idle".into();
                record.completed_at = Some(now_ms());
                record.elapsed_ms = record
                    .started_at
                    .map(|started| now_ms().saturating_sub(started));
                record.continuation = None;
                record.approval_request = None;
                self.store.save(&record)?;
                self.send_child_mail(&record, &result.text, "completed")?;
            }
            TurnProgress::ApprovalRequired {
                request,
                continuation,
            } => {
                record.status = "paused".into();
                record.summary = request.message.clone();
                record.continuation = Some(continuation);
                record.approval_request = Some(request.clone());
                self.store.save(&record)?;
                self.send_child_mail(&record, &request.message, "approval_required")?;
            }
        }
        Ok(())
    }

    fn fail_record(&self, parent_thread_id: &str, name: &str, error: &str) -> Result<(), String> {
        let Some(mut record) = self.store.load(parent_thread_id, name)? else {
            return Ok(());
        };
        if record.status == "closed" {
            return Ok(());
        }
        record.status = "failed".into();
        record.summary = error.chars().take(1000).collect();
        record.completed_at = Some(now_ms());
        record.elapsed_ms = record
            .started_at
            .map(|started| now_ms().saturating_sub(started));
        self.store.save(&record)?;
        self.send_child_mail(&record, error, "failed")
    }

    fn send_child_mail(
        &self,
        record: &SubAgentRecord,
        body: &str,
        kind: &str,
    ) -> Result<(), String> {
        let mail = SubAgentMail {
            id: Uuid::new_v4().simple().to_string(),
            parent_thread_id: record.parent_thread_id.clone(),
            name: record.name.clone(),
            direction: "child_to_parent".into(),
            body: format!("[Sub-agent {} · {}]\n{}", record.name, kind, body),
            message_key: format!("{}:{}", kind, Uuid::new_v4().simple()),
            created_at: now_ms(),
            delivered_at: None,
        };
        self.store.insert_mail(&mail).map(|_| ())
    }
}

#[derive(Clone)]
pub struct SubAgentTools {
    hub: Arc<SubAgentHub>,
    parent_thread_id: String,
}

#[async_trait]
impl ToolRuntime for SubAgentTools {
    fn definitions(&self, _capabilities: &DeviceCapabilities) -> Vec<ToolDefinition> {
        vec![
            ToolDefinition {
                name: SUB_AGENT_TOOL.into(),
                description: "Create or close one reusable, non-blocking sub-agent.".into(),
                input_schema: serde_json::json!({
                    "type":"object","additionalProperties":false,
                    "properties":{
                        "action":{"type":"string","enum":["create","close"]},
                        "type":{"type":"string","enum":["consider","execute"]},
                        "name":{"type":"string","pattern":"^[a-z][a-z0-9_]{0,63}$"},
                        "model":{"type":"string"},
                        "reasoning_level":{"type":"string","enum":["off","light","medium","Medium","high","xhigh","xh","max"]}
                    },
                    "required":["action","type","name","model","reasoning_level"]
                }),
            },
            ToolDefinition {
                name: SUB_AGENT_MESSAGE_TOOL.into(),
                description: "Send guidance to an active reusable sub-agent without blocking."
                    .into(),
                input_schema: serde_json::json!({
                    "type":"object","additionalProperties":false,
                    "properties":{
                        "type":{"type":"string","enum":["consider","execute"]},
                        "name":{"type":"string","pattern":"^[a-z][a-z0-9_]{0,63}$"},
                        "prompt":{"type":"string","minLength":1}
                    },
                    "required":["type","name","prompt"]
                }),
            },
        ]
    }

    fn permission(&self, _call: &ToolCall) -> ToolPermission {
        ToolPermission::AutoAllow
    }

    async fn execute(&self, call: &ToolCall) -> Result<Value, RuntimeError> {
        match call.name.as_str() {
            SUB_AGENT_TOOL => self.hub.create(&self.parent_thread_id, call).await,
            SUB_AGENT_MESSAGE_TOOL => self.hub.message(&self.parent_thread_id, call).await,
            _ => Err(RuntimeError::Tool(format!(
                "unknown sub-agent tool '{}'",
                call.name
            ))),
        }
    }
}

struct ChildMessageTools {
    hub: Arc<SubAgentHub>,
    parent_thread_id: String,
    name: String,
}

#[async_trait]
impl ToolRuntime for ChildMessageTools {
    fn definitions(&self, _capabilities: &DeviceCapabilities) -> Vec<ToolDefinition> {
        vec![ToolDefinition {
            name: CHILD_MESSAGE_TOOL.into(),
            description: "Send a persistent message to the parent agent.".into(),
            input_schema: serde_json::json!({
                "type":"object","additionalProperties":false,
                "properties":{"message":{"type":"string","minLength":1}},
                "required":["message"]
            }),
        }]
    }

    async fn execute(&self, call: &ToolCall) -> Result<Value, RuntimeError> {
        let arguments = object_arguments(call)?;
        require_exact_keys(arguments, &["message"], "message requires exactly message")?;
        let message = string_argument(arguments, "message")?.trim();
        if message.is_empty() {
            return Err(RuntimeError::Tool("message is required".into()));
        }
        let record = self
            .hub
            .store
            .load(&self.parent_thread_id, &self.name)
            .map_err(RuntimeError::Tool)?
            .ok_or_else(|| RuntimeError::Tool("sub-agent record disappeared".into()))?;
        self.hub
            .send_child_mail(&record, message, "message")
            .map_err(RuntimeError::Tool)?;
        Ok(serde_json::json!({"accepted":true,"injected":false}))
    }
}

struct FilteredChildTools {
    inner: Arc<dyn ToolRuntime>,
    read_only: bool,
}

#[async_trait]
impl ToolRuntime for FilteredChildTools {
    fn definitions(&self, capabilities: &DeviceCapabilities) -> Vec<ToolDefinition> {
        self.inner
            .definitions(capabilities)
            .into_iter()
            .filter(|definition| !self.read_only || is_read_only_tool(&definition.name))
            .filter(|definition| {
                definition.name != SUB_AGENT_TOOL && definition.name != SUB_AGENT_MESSAGE_TOOL
            })
            .collect()
    }

    fn permission(&self, call: &ToolCall) -> ToolPermission {
        if (self.read_only && !is_read_only_tool(&call.name))
            || call.name == SUB_AGENT_TOOL
            || call.name == SUB_AGENT_MESSAGE_TOOL
        {
            ToolPermission::HardBlock
        } else {
            self.inner.permission(call)
        }
    }

    async fn execute(&self, call: &ToolCall) -> Result<Value, RuntimeError> {
        if self.permission(call) == ToolPermission::HardBlock {
            return Err(RuntimeError::Tool(format!(
                "tool '{}' is unavailable to this sub-agent",
                call.name
            )));
        }
        self.inner.execute(call).await
    }
}

fn is_read_only_tool(name: &str) -> bool {
    matches!(name, "read_file" | "list_dir")
        || name.starts_with("read_")
        || name.starts_with("list_")
        || name.starts_with("search_")
}

struct MailboxGuidance {
    hub: Arc<SubAgentHub>,
    parent_thread_id: String,
    name: Option<String>,
    direction: String,
    persist_in_child_history: bool,
}

#[async_trait]
impl GuidanceSource for MailboxGuidance {
    async fn drain(&self) -> Vec<String> {
        let messages = match self.hub.store.undelivered(
            &self.parent_thread_id,
            self.name.as_deref(),
            &self.direction,
        ) {
            Ok(messages) => messages,
            Err(error) => return vec![format!("Mailbox error: {error}")],
        };
        if messages.is_empty() {
            return Vec::new();
        }
        let ids = messages
            .iter()
            .map(|message| message.id.clone())
            .collect::<Vec<_>>();
        let bodies = messages
            .iter()
            .map(|message| message.body.clone())
            .collect::<Vec<_>>();
        if self.persist_in_child_history {
            if let Some(name) = &self.name {
                if let Ok(Some(mut record)) = self.hub.store.load(&self.parent_thread_id, name) {
                    for body in &bodies {
                        record.history.push(Message::User {
                            content: format!("[Parent guidance]\n{body}"),
                        });
                    }
                    let _ = self.hub.store.save(&record);
                }
            }
        }
        let _ = self.hub.store.mark_delivered(&ids, now_ms());
        bodies
    }
}

fn operation_payload(record: &SubAgentRecord, action: &str) -> Value {
    let mut value = serde_json::to_value(record).unwrap_or_else(|_| serde_json::json!({}));
    if let Some(object) = value.as_object_mut() {
        object.insert("lifecycle_action".into(), Value::String(action.into()));
    }
    value
}

fn resolve_model<'a>(
    models: &'a [SubAgentModelEntry],
    reference: &str,
) -> Result<&'a SubAgentModelEntry, RuntimeError> {
    if reference.trim().is_empty() {
        return Err(RuntimeError::Tool("model is required".into()));
    }
    if let Some(model) = models.iter().find(|model| model.id == reference) {
        return Ok(model);
    }
    let matching = models
        .iter()
        .filter(|model| model.display_name == reference)
        .collect::<Vec<_>>();
    match matching.as_slice() {
        [model] => Ok(model),
        [] => Err(RuntimeError::Tool(format!("unknown model: {reference}"))),
        _ => Err(RuntimeError::Tool(format!(
            "model display_name is ambiguous: {reference}"
        ))),
    }
}

fn object_arguments(call: &ToolCall) -> Result<&serde_json::Map<String, Value>, RuntimeError> {
    call.arguments
        .as_object()
        .ok_or_else(|| RuntimeError::Tool(format!("{} arguments must be an object", call.name)))
}

fn require_exact_keys(
    arguments: &serde_json::Map<String, Value>,
    expected: &[&str],
    message: &str,
) -> Result<(), RuntimeError> {
    if arguments.len() == expected.len() && expected.iter().all(|key| arguments.contains_key(*key))
    {
        Ok(())
    } else {
        Err(RuntimeError::Tool(message.into()))
    }
}

fn string_argument<'a>(
    arguments: &'a serde_json::Map<String, Value>,
    key: &str,
) -> Result<&'a str, RuntimeError> {
    arguments
        .get(key)
        .and_then(Value::as_str)
        .ok_or_else(|| RuntimeError::Tool(format!("{key} must be a string")))
}

fn validate_name(name: &str) -> Result<&str, RuntimeError> {
    let mut characters = name.chars();
    let valid = name.len() <= 64
        && matches!(characters.next(), Some(character) if character.is_ascii_lowercase())
        && characters.all(|character| {
            character.is_ascii_lowercase() || character.is_ascii_digit() || character == '_'
        });
    if valid {
        Ok(name)
    } else {
        Err(RuntimeError::Tool(
            "name must match ^[a-z][a-z0-9_]{0,63}$".into(),
        ))
    }
}

fn validate_type(agent_type: &str) -> Result<&str, RuntimeError> {
    if matches!(agent_type, "consider" | "execute") {
        Ok(agent_type)
    } else {
        Err(RuntimeError::Tool(
            "type must be exactly 'consider' or 'execute'".into(),
        ))
    }
}

fn validate_reasoning(level: &str) -> Result<&str, RuntimeError> {
    let normalized = match level {
        "Medium" => "medium",
        "xh" => "xhigh",
        other => other,
    };
    if matches!(
        normalized,
        "off" | "light" | "medium" | "high" | "xhigh" | "max"
    ) {
        Ok(normalized)
    } else {
        Err(RuntimeError::Tool(
            "reasoning_level must be one of off, light, medium, high, xhigh, max".into(),
        ))
    }
}

fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis() as u64)
        .unwrap_or_default()
}

#[derive(Default)]
pub struct MemorySubAgentStore {
    records: StdMutex<BTreeMap<(String, String), SubAgentRecord>>,
    mail: StdMutex<Vec<SubAgentMail>>,
}

impl SubAgentStore for MemorySubAgentStore {
    fn recover_running(&self, parent_thread_id: &str) -> Result<(), String> {
        for ((parent, _), record) in self.records.lock().unwrap().iter_mut() {
            if parent == parent_thread_id && record.status == "running" {
                record.status = "interrupted".into();
                record.completed_at = Some(now_ms());
            }
        }
        Ok(())
    }

    fn load(&self, parent_thread_id: &str, name: &str) -> Result<Option<SubAgentRecord>, String> {
        Ok(self
            .records
            .lock()
            .unwrap()
            .get(&(parent_thread_id.into(), name.into()))
            .cloned())
    }

    fn save(&self, record: &SubAgentRecord) -> Result<(), String> {
        self.records.lock().unwrap().insert(
            (record.parent_thread_id.clone(), record.name.clone()),
            record.clone(),
        );
        Ok(())
    }

    fn list(&self, parent_thread_id: &str) -> Result<Vec<SubAgentRecord>, String> {
        Ok(self
            .records
            .lock()
            .unwrap()
            .iter()
            .filter(|((parent, _), _)| parent == parent_thread_id)
            .map(|(_, record)| record.clone())
            .collect())
    }

    fn insert_mail(&self, mail: &SubAgentMail) -> Result<bool, String> {
        let mut messages = self.mail.lock().unwrap();
        if messages.iter().any(|existing| {
            existing.parent_thread_id == mail.parent_thread_id
                && existing.name == mail.name
                && existing.direction == mail.direction
                && existing.message_key == mail.message_key
        }) {
            return Ok(false);
        }
        messages.push(mail.clone());
        Ok(true)
    }

    fn undelivered(
        &self,
        parent_thread_id: &str,
        name: Option<&str>,
        direction: &str,
    ) -> Result<Vec<SubAgentMail>, String> {
        Ok(self
            .mail
            .lock()
            .unwrap()
            .iter()
            .filter(|mail| {
                mail.parent_thread_id == parent_thread_id
                    && name.is_none_or(|name| mail.name == name)
                    && mail.direction == direction
                    && mail.delivered_at.is_none()
            })
            .cloned()
            .collect())
    }

    fn mark_delivered(&self, ids: &[String], delivered_at: u64) -> Result<(), String> {
        for mail in self.mail.lock().unwrap().iter_mut() {
            if ids.contains(&mail.id) {
                mail.delivered_at = Some(delivered_at);
            }
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct EmptyTools;

    #[async_trait]
    impl ToolRuntime for EmptyTools {
        fn definitions(&self, _capabilities: &DeviceCapabilities) -> Vec<ToolDefinition> {
            Vec::new()
        }

        async fn execute(&self, _call: &ToolCall) -> Result<Value, RuntimeError> {
            Err(RuntimeError::Tool("no tools".into()))
        }
    }

    fn test_config() -> SubAgentParentConfig {
        SubAgentParentConfig {
            models: vec![SubAgentModelEntry {
                id: "model-a".into(),
                display_name: "Model A".into(),
                provider: ProviderConfig {
                    api_type: "openai".into(),
                    base_url: "https://example.invalid/v1".into(),
                    api_key: "key".into(),
                    api_model_id: "model-a".into(),
                    notes: String::new(),
                    max_output_tokens: None,
                    temperature: None,
                    provider_name: String::new(),
                    provider_extra: Value::Null,
                    model_extra: Value::Null,
                    thinking_supported: false,
                    thinking_budget: None,
                },
            }],
            child_tools: Arc::new(EmptyTools),
            capabilities: DeviceCapabilities::default(),
            context: AgentContext::default(),
            options: TurnOptions::default(),
            hook_context: HookRunContext::default(),
            hooks: None,
        }
    }

    #[tokio::test]
    async fn lifecycle_is_strict_durable_and_messages_are_deduplicated() {
        let store = Arc::new(MemorySubAgentStore::default());
        let hub = SubAgentHub::new(store.clone());
        hub.configure_parent("parent", test_config()).await.unwrap();
        let tools = hub.tools("parent");
        let create = ToolCall {
            id: "create-1".into(),
            name: SUB_AGENT_TOOL.into(),
            arguments: serde_json::json!({
                "action":"create","type":"consider","name":"research",
                "model":"Model A","reasoning_level":"xh"
            }),
        };
        let created = tools.execute(&create).await.unwrap();
        assert_eq!(created["lifecycle_action"], "created");
        assert_eq!(created["reasoningLevel"], "xhigh");
        assert_eq!(
            tools.execute(&create).await.unwrap()["lifecycle_action"],
            "enabled"
        );

        let message = ToolCall {
            id: "message-1".into(),
            name: SUB_AGENT_MESSAGE_TOOL.into(),
            arguments: serde_json::json!({
                "type":"consider","name":"research","prompt":"inspect"
            }),
        };
        assert_eq!(
            tools.execute(&message).await.unwrap()["deduplicated"],
            false
        );
        assert_eq!(tools.execute(&message).await.unwrap()["deduplicated"], true);
        assert_eq!(
            store
                .undelivered("parent", Some("research"), "parent_to_child")
                .unwrap()
                .len(),
            1
        );
    }

    #[test]
    fn running_records_are_interrupted_after_process_recovery() {
        let store = MemorySubAgentStore::default();
        store
            .save(&SubAgentRecord {
                parent_thread_id: "parent".into(),
                agent_type: "execute".into(),
                name: "worker".into(),
                model_id: "model-a".into(),
                reasoning_level: "high".into(),
                status: "running".into(),
                summary: String::new(),
                started_at: Some(1),
                completed_at: None,
                elapsed_ms: None,
                sub_session_id: "parent:sub:worker".into(),
                source_call_id: String::new(),
                source_run_id: String::new(),
                source_turn_id: String::new(),
                history: Vec::new(),
                continuation: None,
                approval_request: None,
            })
            .unwrap();
        store.recover_running("parent").unwrap();
        assert_eq!(
            store.load("parent", "worker").unwrap().unwrap().status,
            "interrupted"
        );
    }
}
