//! The one `TurnRunner` implementation.
//!
//! Before this file existed, `sunday-cli/src/serve.rs` and the Android host each
//! carried their own copy: event translation, approval handling, cancel tokens,
//! queue plumbing, history paging. They were about 90% identical, which is the
//! worst ratio: different enough to drift, similar enough that a fix in one would
//! look correct while the other stayed broken.
//!
//! A host's job is narrower than it looks. It should own:
//!
//!   * lifecycle and start/stop
//!   * paths, secrets and platform permissions
//!   * the transport (sockets, IPC, whatever the platform offers)
//!   * assembling the components below
//!
//! It should not own agent orchestration, event mapping, approvals or the queue.
//! That is what this module is: the part every host shares, built from a store, a
//! model and a grant policy.

use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use sunday_agent::{Approver, Env, TurnInput};
use sunday_protocol::{CancelToken, EventKind, HostKind, Model, RunBudget, RunOutcome, Tool};
use sunday_store::Store;

use crate::app_server::{
    BridgeEvent, EventBuffer, EventSink, HistoryPage, QueueView, SteerOutcome, StopMode, TurnRunner,
};
use crate::policy::GrantPolicy;

fn now_ms() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

/// Maps a journal event to the method a workbench dispatches on.
///
/// The payload is adapted too, not just renamed: the agent records `approval_id`
/// while the workbench reads `payload.request_id` and sends that value back. A
/// rename without the payload fix produces an approval card with no id, which the
/// user cannot answer.
pub fn translate(kind: &EventKind, payload: &serde_json::Value) -> (String, serde_json::Value) {
    let method = match kind {
        EventKind::CommandAccepted => "turn/accepted",
        EventKind::RunStarted => "turn/started",
        EventKind::ModelStarted => "turn/model_started",
        EventKind::ModelCompleted => "turn/model_completed",
        EventKind::ToolPrepared => "item/tool_prepared",
        EventKind::ApprovalRequested => "item/approval_request",
        EventKind::ApprovalResolved => "item/approval_resolved",
        EventKind::ToolDispatched => "item/tool_dispatched",
        EventKind::ToolSucceeded => "item/completed",
        EventKind::ToolFailed => "item/failed",
        EventKind::ToolOutcomeUnknown => "item/outcome_unknown",
        EventKind::ToolReplayed => "item/replayed",
        EventKind::GuidanceReceived => "item/guidance",
        EventKind::RunCancelled => "turn/cancelled",
        EventKind::RunCompleted => "turn/completed",
        EventKind::RunWaitingForReconciliation => "turn/waiting_for_reconciliation",
        EventKind::ContextCompacted => "turn/context_compacted",
    };
    let mut payload = payload.clone();
    if matches!(
        kind,
        EventKind::ApprovalRequested | EventKind::ApprovalResolved
    ) {
        if let Some(object) = payload.as_object_mut() {
            if !object.contains_key("request_id") {
                if let Some(id) = object.get("approval_id").cloned() {
                    object.insert("request_id".into(), id);
                }
            }
        }
    }
    (method.to_owned(), payload)
}

fn queue_view(item: sunday_store::QueueItem) -> QueueView {
    QueueView {
        queue_item_id: item.queue_item_id,
        position: item.position,
        input: item.input,
        status: item.status,
    }
}

/// Everything a host must supply, and nothing it must implement.
pub struct CoreOptions {
    pub store: Store,
    pub model: Arc<dyn Model>,
    pub model_id: String,
    /// Absolute path the tools may touch. Resolved by the host, because only it
    /// knows what the platform's private storage is.
    pub workspace: String,
    pub host_kind: HostKind,
    pub policy: GrantPolicy,
    /// System prompt for a turn. Hosts differ: a headless server and an app may
    /// want different framing.
    pub system: Option<String>,
}

/// The shared runner. One instance per core process.
pub struct CoreRunner {
    store: Mutex<Store>,
    model: Arc<dyn Model>,
    model_id: String,
    workspace: String,
    host_kind: HostKind,
    policy: GrantPolicy,
    system: Option<String>,
    /// Ordering for events this runner synthesises (stop acknowledgements). All
    /// journal-backed events use the journal's own seq.
    seq: AtomicU64,
    buffer: EventBuffer,
    /// One token per thread, so stopping one conversation cannot stop another.
    cancel: Mutex<HashMap<String, CancelToken>>,
    /// Threads with a turn currently running. Used to answer `turn/steer`
    /// honestly: guidance only applies to a live turn.
    live: Mutex<HashMap<String, bool>>,
}

impl CoreRunner {
    pub fn new(options: CoreOptions) -> Self {
        Self {
            store: Mutex::new(options.store),
            model: options.model,
            model_id: options.model_id,
            workspace: options.workspace,
            host_kind: options.host_kind,
            policy: options.policy,
            system: options.system,
            seq: AtomicU64::new(0),
            buffer: EventBuffer::default(),
            cancel: Mutex::new(HashMap::new()),
            live: Mutex::new(HashMap::new()),
        }
    }

    fn cancel_token(&self, thread: &str) -> CancelToken {
        let mut map = self.cancel.lock().unwrap();
        map.entry(thread.to_owned()).or_default().clone()
    }

    fn mark_cancel(&self, thread: &str) {
        let mut map = self.cancel.lock().unwrap();
        map.entry(thread.to_owned()).or_default().cancel();
    }

    fn set_live(&self, thread: &str, live: bool) {
        self.live.lock().unwrap().insert(thread.to_owned(), live);
    }

    fn is_live(&self, thread: &str) -> bool {
        self.live
            .lock()
            .unwrap()
            .get(thread)
            .copied()
            .unwrap_or(false)
    }

    /// Replays the journal from `from_seq` to the sink.
    fn emit_journal(&self, thread: &str, sink: EventSink<'_>, from_seq: u64) {
        let events = {
            let store = self.store.lock().unwrap();
            store.events(thread, from_seq).unwrap_or_default()
        };
        for event in events {
            let (method, payload) = translate(&event.kind, &event.payload);
            let bridge = BridgeEvent {
                method,
                seq: event.seq,
                payload,
                client_message_id: None,
            };
            self.buffer.push(thread, bridge.clone());
            sink(bridge);
        }
    }
}

impl CoreRunner {
    /// What the journal says about work that was interrupted.
    ///
    /// This is the fact a resume reports on. The lifecycle marker only records what
    /// a process believed when it lost visibility; this knows which tool calls were
    /// dispatched and never answered.
    pub fn recovery(&self) -> Result<sunday_store::RecoveryPlan, sunday_protocol::CoreError> {
        self.store.lock().expect("store lock").recover()
    }
}

impl TurnRunner for CoreRunner {
    fn start_turn(
        &self,
        thread_id: &str,
        prompt: &str,
        client_message_id: &str,
        sink: EventSink<'_>,
    ) -> Result<(), String> {
        // Acceptance must be a real journal event with a real seq: the client
        // treats it as authoritative and orders everything after it.
        let accept_seq = {
            let mut store = self.store.lock().unwrap();
            let request_id = if client_message_id.is_empty() {
                format!("{thread_id}:{}", now_ms())
            } else {
                client_message_id.to_owned()
            };
            let envelope = sunday_protocol::CommandEnvelope {
                protocol_version: sunday_protocol::PROTOCOL_VERSION.to_string(),
                request_id,
                thread_id: thread_id.to_owned(),
                expected_revision: None,
                payload: sunday_protocol::Command::TurnStart {
                    text: prompt.to_owned(),
                },
            };
            store
                .accept_command("local", &envelope)
                .map_err(|e| e.to_string())?
                .seq
                .ok_or_else(|| "the store accepted without returning a seq".to_owned())?
        };
        {
            let store = self.store.lock().unwrap();
            if let Some(event) = store
                .events(thread_id, accept_seq.saturating_sub(1))
                .map_err(|e| e.to_string())?
                .into_iter()
                .find(|event| event.seq == accept_seq)
            {
                let (method, payload) = translate(&event.kind, &event.payload);
                sink(BridgeEvent {
                    method,
                    seq: accept_seq,
                    payload,
                    client_message_id: Some(client_message_id.to_owned()),
                });
            }
        }

        let cancel = self.cancel_token(thread_id);
        cancel.reset();
        self.set_live(thread_id, true);

        let files =
            Arc::new(sunday_platform::LocalFiles::new(&self.workspace).map_err(|e| e.to_string())?);
        let read = sunday_tools::file_read::ReadFile::new(files.clone());
        let write = sunday_tools::file_write::WriteFile::new(files);
        let tools: Vec<&dyn Tool> = vec![&read, &write];

        let env = Env {
            store: &self.store,
            model: self.model.as_ref(),
            tools: &tools,
            approver: &self.policy as &dyn Approver,
            cancel: &cancel,
            workspace: "local".into(),
            host: self.host_kind,
            context: None,
        };
        let input = TurnInput {
            thread_id: thread_id.to_owned(),
            turn_id: format!("turn-{}", self.seq.load(Ordering::SeqCst)),
            model_id: self.model_id.clone(),
            system: self.system.clone(),
            prompt: prompt.to_owned(),
        };

        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .map_err(|e| format!("runtime: {e}"))?;
        let run = runtime.block_on(sunday_agent::run_turn(&env, input, RunBudget::default()));

        self.set_live(thread_id, false);
        self.emit_journal(thread_id, sink, accept_seq);

        match run {
            Ok(RunOutcome::Completed { .. })
            | Ok(RunOutcome::NeedsApproval { .. })
            | Ok(RunOutcome::Cancelled) => Ok(()),
            Ok(RunOutcome::WaitingForReconciliation { tool_call_id, hint }) => {
                Err(format!("outcome unknown for {tool_call_id}: {hint}"))
            }
            Ok(RunOutcome::BudgetExhausted { reason }) => {
                Err(format!("budget exhausted: {reason:?}"))
            }
            Err(error) => Err(error.to_string()),
        }
    }

    fn respond(
        &self,
        thread_id: &str,
        request_id: &str,
        decision: &str,
        guidance: &str,
        sink: EventSink<'_>,
    ) -> Result<(), String> {
        match decision {
            "approve" | "trust" => {}
            "deny" | "skip" => {
                let mut store = self.store.lock().unwrap();
                store
                    .respond_approval(request_id, "", now_ms(), false)
                    .map_err(|e| e.to_string())?;
                drop(store);
                self.emit_journal(thread_id, sink, 0);
                return Ok(());
            }
            "guide" => {
                let mut store = self.store.lock().unwrap();
                let guidance_id = format!("{thread_id}:guide:{}", now_ms());
                store
                    .append_guidance(thread_id, &guidance_id, guidance)
                    .map_err(|e| e.to_string())?;
                drop(store);
                self.emit_journal(thread_id, sink, 0);
                return Ok(());
            }
            other => return Err(format!("unsupported decision {other}")),
        }

        // The digest binds this decision to the exact arguments the user saw, so
        // approving one call cannot silently authorise another.
        let digest = {
            let store = self.store.lock().unwrap();
            match store.pending_call(request_id) {
                Ok(Some((_, digest))) => digest,
                Ok(None) => return Err("that approval has no pending call".into()),
                Err(e) => return Err(e.to_string()),
            }
        };
        let cancel = self.cancel_token(thread_id);

        let files =
            Arc::new(sunday_platform::LocalFiles::new(&self.workspace).map_err(|e| e.to_string())?);
        let read = sunday_tools::file_read::ReadFile::new(files.clone());
        let write = sunday_tools::file_write::WriteFile::new(files);
        let tools: Vec<&dyn Tool> = vec![&read, &write];
        let env = Env {
            store: &self.store,
            model: self.model.as_ref(),
            tools: &tools,
            approver: &self.policy as &dyn Approver,
            cancel: &cancel,
            workspace: "local".into(),
            host: self.host_kind,
            context: None,
        };
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .map_err(|e| format!("runtime: {e}"))?;
        let run = runtime.block_on(sunday_agent::resume_turn(
            &env,
            thread_id,
            request_id,
            &digest,
            RunBudget::default(),
        ));
        self.emit_journal(thread_id, sink, 0);
        match run {
            Ok(_) => Ok(()),
            Err(error) => Err(error.to_string()),
        }
    }

    fn cancel(&self, thread_id: &str) -> Result<Vec<BridgeEvent>, String> {
        self.mark_cancel(thread_id);
        Ok(Vec::new())
    }

    fn events(&self, thread_id: &str, after: u64) -> Result<Vec<BridgeEvent>, String> {
        let stored = {
            let store = self.store.lock().unwrap();
            store.events(thread_id, after).unwrap_or_default()
        };
        let mut out: Vec<BridgeEvent> = stored
            .into_iter()
            .map(|event| {
                let (method, payload) = translate(&event.kind, &event.payload);
                BridgeEvent {
                    method,
                    seq: event.seq,
                    payload,
                    client_message_id: None,
                }
            })
            .collect();
        if out.is_empty() {
            out = self.buffer.after(thread_id, after);
        }
        out.sort_by_key(|event| event.seq);
        Ok(out)
    }

    fn open_thread(&self, thread_id: &str) -> Result<Vec<BridgeEvent>, String> {
        // Opening is reading. A thread exists once its journal has events, which
        // the first accepted command creates. Nothing is written here, so a
        // retried press cannot fork a thread or bump a revision.
        let events = {
            let store = self.store.lock().unwrap();
            store.events(thread_id, 0).unwrap_or_default()
        };
        Ok(events
            .into_iter()
            .map(|event| {
                let (method, payload) = translate(&event.kind, &event.payload);
                BridgeEvent {
                    method,
                    seq: event.seq,
                    payload,
                    client_message_id: None,
                }
            })
            .collect())
    }

    fn history(
        &self,
        thread_id: &str,
        before_seq: Option<u64>,
        limit: usize,
    ) -> Result<HistoryPage, String> {
        let store = self.store.lock().unwrap();
        let (events, has_more) = store
            .history_page(thread_id, before_seq, limit)
            .map_err(|e| e.to_string())?;
        let total = store.event_count(thread_id).map_err(|e| e.to_string())?;
        Ok(HistoryPage {
            events: events
                .into_iter()
                .map(|event| {
                    let (method, payload) = translate(&event.kind, &event.payload);
                    BridgeEvent {
                        method,
                        seq: event.seq,
                        payload,
                        client_message_id: None,
                    }
                })
                .collect(),
            has_more,
            total_items: total,
        })
    }

    fn queue(&self, thread_id: &str) -> Result<Vec<QueueView>, String> {
        let store = self.store.lock().unwrap();
        Ok(store
            .queue(thread_id)
            .map_err(|e| e.to_string())?
            .into_iter()
            .map(queue_view)
            .collect())
    }

    fn queue_create(
        &self,
        thread_id: &str,
        queue_item_id: &str,
        text: &str,
    ) -> Result<Vec<QueueView>, String> {
        let mut store = self.store.lock().unwrap();
        store
            .enqueue(thread_id, queue_item_id, text)
            .map_err(|e| e.to_string())?;
        Ok(store
            .queue(thread_id)
            .map_err(|e| e.to_string())?
            .into_iter()
            .map(queue_view)
            .collect())
    }

    fn queue_update(
        &self,
        thread_id: &str,
        queue_item_id: &str,
        text: &str,
    ) -> Result<Vec<QueueView>, String> {
        let mut store = self.store.lock().unwrap();
        if !store
            .update_queue_item(thread_id, queue_item_id, text)
            .map_err(|e| e.to_string())?
        {
            return Err(format!("no queue item {queue_item_id} in {thread_id}"));
        }
        Ok(store
            .queue(thread_id)
            .map_err(|e| e.to_string())?
            .into_iter()
            .map(queue_view)
            .collect())
    }

    fn queue_delete(&self, thread_id: &str, queue_item_id: &str) -> Result<Vec<QueueView>, String> {
        let mut store = self.store.lock().unwrap();
        // Deleting something already gone is the state the caller wanted, so a
        // double click must not surface as a failure.
        store
            .delete_queue_item(thread_id, queue_item_id)
            .map_err(|e| e.to_string())?;
        Ok(store
            .queue(thread_id)
            .map_err(|e| e.to_string())?
            .into_iter()
            .map(queue_view)
            .collect())
    }

    fn queue_reorder(&self, thread_id: &str, order: &[String]) -> Result<Vec<QueueView>, String> {
        let mut store = self.store.lock().unwrap();
        store
            .reorder_queue(thread_id, order)
            .map_err(|e| e.to_string())?;
        Ok(store
            .queue(thread_id)
            .map_err(|e| e.to_string())?
            .into_iter()
            .map(queue_view)
            .collect())
    }

    fn steer(&self, thread_id: &str, turn_id: &str, text: &str) -> Result<SteerOutcome, String> {
        if !self.is_live(thread_id) {
            // Answering "applied" with nothing running would make the UI show the
            // text as delivered while the user never sees it again.
            return Ok(SteerOutcome {
                applied: false,
                queued: false,
                reason: if turn_id.is_empty() {
                    "run_not_active".into()
                } else {
                    "active_turn_mismatch".into()
                },
            });
        }
        let mut store = self.store.lock().unwrap();
        let guidance_id = format!("{thread_id}:steer:{}", now_ms());
        store
            .append_guidance(thread_id, &guidance_id, text)
            .map_err(|e| e.to_string())?;
        Ok(SteerOutcome {
            applied: true,
            queued: false,
            reason: String::new(),
        })
    }

    fn stop_turn(
        &self,
        thread_id: &str,
        mode: StopMode,
        sink: EventSink<'_>,
    ) -> Result<(), String> {
        // Every mode stops the loop. What differs is how much state is cleared.
        self.mark_cancel(thread_id);
        if matches!(mode, StopMode::Terminate | StopMode::ForceReset) {
            // A terminated turn must not be resumable, so drop the continuation
            // that would otherwise continue it on the next press.
            let mut store = self.store.lock().unwrap();
            store
                .clear_continuation(thread_id)
                .map_err(|e| e.to_string())?;
        }
        sink(BridgeEvent {
            method: "turn/completed".into(),
            seq: self.seq.fetch_add(1, Ordering::SeqCst) + 1,
            payload: serde_json::json!({
                "status": "cancelled",
                "mode": format!("{mode:?}"),
            }),
            client_message_id: None,
        });
        Ok(())
    }

    fn command_catalog(&self) -> Vec<serde_json::Value> {
        // Only what the core can actually do. A longer list would be a lie the
        // palette tells the user.
        let mut commands = vec![
            serde_json::json!({
                "name": "clear",
                "title": "Clear the conversation",
                "description": "Start a fresh conversation in this thread.",
                "source": "core",
                "action": "run_action",
                "kind": "action",
                "accepts_args": false,
            }),
            serde_json::json!({
                "name": "tools",
                "title": "List available tools",
                "description": "Ask the model which tools it can use here.",
                "source": "core",
                "action": "expand_on_send",
                "kind": "action",
                "accepts_args": false,
            }),
        ];
        // The tools themselves are also commands, so a user can ask for one by
        // name instead of hoping the model picks it.
        for spec in offered_tools() {
            commands.push(serde_json::json!({
                "name": spec.id,
                "title": spec.id,
                "description": spec.description,
                "source": "core",
                "action": "expand_on_send",
                "kind": "tool",
                "accepts_args": true,
            }));
        }
        commands
    }

    fn expand_command(&self, name: &str, arguments: &str) -> Result<String, String> {
        match name {
            "clear" => Ok("The user asked to clear this conversation. Acknowledge briefly; the                            UI handles the reset."
                .to_owned()),
            "tools" => {
                let names: Vec<String> = offered_tools().into_iter().map(|t| t.id).collect();
                Ok(format!(
                    "List these tools and what each is for, in one line each: {}",
                    names.join(", ")
                ))
            }
            other => {
                if offered_tools().iter().any(|spec| spec.id == other) {
                    if arguments.trim().is_empty() {
                        return Err(format!("{other} needs arguments"));
                    }
                    Ok(format!("Use the {other} tool. {arguments}"))
                } else {
                    Err(format!("unknown command: {other}"))
                }
            }
        }
    }

    /// Not part of the protocol: the host uses this to answer "is anything
    /// running" for lifecycle decisions such as pausing on background.
    fn recovery(&self) -> Result<sunday_store::RecoveryPlan, String> {
        CoreRunner::recovery(self).map_err(|error| error.to_string())
    }

    fn running_threads(&self) -> Vec<String> {
        let map = self.live.lock().unwrap();
        map.iter()
            .filter(|(_, live)| **live)
            .map(|(thread, _)| thread.clone())
            .collect()
    }
}

/// Tool specs the core offers, so a host can describe them without duplicating
/// the list. Used by `command.catalog` and by any UI that wants to explain what
/// it is about to do.
pub fn offered_tools() -> Vec<sunday_protocol::ToolSpec> {
    let Ok(files) = sunday_platform::LocalFiles::new(std::env::temp_dir()) else {
        return Vec::new();
    };
    let files = Arc::new(files);
    let read = sunday_tools::file_read::ReadFile::new(files.clone());
    let write = sunday_tools::file_write::WriteFile::new(files);
    vec![
        sunday_protocol::Tool::spec(&read).clone(),
        sunday_protocol::Tool::spec(&write).clone(),
    ]
}

/// A model that replays a fixed script, for hosts that must start without a
/// provider and for tests.
///
/// Lives here rather than in the CLI so the Android host can start in the same
/// way; previously each host had its own copy.
pub fn scripted_model(script: &str) -> Result<ScriptedModel, sunday_protocol::CoreError> {
    ScriptedModel::from_json(script)
}

pub struct ScriptedModel {
    turns: std::sync::Mutex<Vec<sunday_protocol::ModelTurn>>,
}

impl ScriptedModel {
    /// A script is a JSON array of turns. `{"text": "..."}` or
    /// `{"tool_calls": [{"id": "...", "name": "...", "args": {...}}]}`.
    pub fn from_json(text: &str) -> Result<Self, sunday_protocol::CoreError> {
        let raw: serde_json::Value = serde_json::from_str(text)
            .map_err(|e| sunday_protocol::CoreError::invalid(format!("script is not json: {e}")))?;
        let array = raw
            .as_array()
            .ok_or_else(|| sunday_protocol::CoreError::invalid("script must be a JSON array"))?;
        let mut turns = Vec::new();
        for (index, entry) in array.iter().enumerate() {
            let text = entry
                .get("text")
                .and_then(|v| v.as_str())
                .map(str::to_owned);
            let mut tool_calls = Vec::new();
            if let Some(calls) = entry.get("tool_calls").and_then(|v| v.as_array()) {
                for call in calls {
                    let id = call.get("id").and_then(|v| v.as_str()).ok_or_else(|| {
                        sunday_protocol::CoreError::invalid(format!("turn {index} call has no id"))
                    })?;
                    let name = call.get("name").and_then(|v| v.as_str()).ok_or_else(|| {
                        sunday_protocol::CoreError::invalid(format!(
                            "turn {index} call has no name"
                        ))
                    })?;
                    tool_calls.push(sunday_protocol::ToolCall {
                        id: id.to_owned(),
                        name: name.to_owned(),
                        args: call.get("args").cloned().unwrap_or(serde_json::json!({})),
                    });
                }
            }
            turns.push(sunday_protocol::ModelTurn {
                text,
                reasoning: None,
                tool_calls,
                usage: None,
                provider_state: None,
            });
        }
        if turns.is_empty() {
            return Err(sunday_protocol::CoreError::invalid("script has no turns"));
        }
        Ok(Self {
            turns: std::sync::Mutex::new(turns),
        })
    }
}

#[async_trait::async_trait]
impl Model for ScriptedModel {
    async fn stream(
        &self,
        _request: sunday_protocol::ModelRequest,
        sink: &mut (dyn FnMut(sunday_protocol::ModelDelta) + Send),
    ) -> Result<sunday_protocol::ModelTurn, sunday_protocol::CoreError> {
        let mut turns = self.turns.lock().unwrap();
        if turns.is_empty() {
            return Err(sunday_protocol::CoreError::model(
                "the script ran out of turns, which means the loop asked for more than expected",
            ));
        }
        let turn = turns.remove(0);
        if let Some(text) = &turn.text {
            sink(sunday_protocol::ModelDelta::Text(text.clone()));
        }
        Ok(turn)
    }
}
