//! `serve` — exposes a real core over `core.app_server.v1`.
//!
//! This is the piece that lets the existing Vue workbench talk to the new core.
//! It is deliberately a host: it owns the socket, the single-writer lock and the
//! model choice, and everything it drives is the real store, the real agent loop
//! and the real tools. The only substitutes are the ones named on the command
//! line.
//!
//! Two model sources, because a test needs both:
//!   * `--script <file>` replays fixed turns, so a protocol test is repeatable.
//!   * `--model-url <url> --model <id>` calls a real OpenAI-compatible provider.

use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use sunday_agent::{Approval, Approver, AutoApprove, Env, TurnInput};
use sunday_host::app_server::{AppServer, BridgeEvent, EventBuffer, EventSink, TurnRunner};
use sunday_host::lock::{LockError, SingleWriterLock};
use sunday_llm::{LlmClient, ProviderConfig};
use sunday_protocol::{
    CoreError, EventKind, HostKind, Model, Permission, RunBudget, RunOutcome, ToolCall, ToolSpec,
};
use sunday_store::Store;
use sunday_tools::file_read::ReadFile;
use sunday_tools::file_write::WriteFile;

/// How long a holder may go without a heartbeat before another core may take
/// the directory. Five seconds is longer than any pause this host can produce
/// and short enough that a crash does not need a manual cleanup.
const STALE_AFTER: std::time::Duration = std::time::Duration::from_secs(5);

/// Who gets asked. A tool marked `AskUser` always asks; everything that reached
/// the model is either allowed automatically or not offered at all.
struct PolicyApprover;

impl Approver for PolicyApprover {
    fn decide(&self, _call: &ToolCall, spec: &ToolSpec) -> Approval {
        match spec.permission {
            Permission::AskUser => Approval::Ask,
            _ => Approval::Auto,
        }
    }
}

pub struct Options {
    pub db: String,
    pub workspace: String,
    pub listen: String,
    pub model: Arc<dyn Model>,
    pub model_id: String,
    pub auto_approve: bool,
}

struct Runner {
    store: Mutex<Store>,
    model: Arc<dyn Model>,
    model_id: String,
    workspace: String,
    auto_approve: bool,
    seq: AtomicU64,
    buffer: EventBuffer,
    /// One cancel flag per thread, so stopping one conversation does not stop
    /// another.
    cancel: Mutex<HashMap<String, Arc<AtomicBool>>>,
}

impl Runner {
    fn cancel_flag(&self, thread: &str) -> Arc<AtomicBool> {
        let mut map = self.cancel.lock().unwrap();
        map.entry(thread.to_owned())
            .or_insert_with(|| Arc::new(AtomicBool::new(false)))
            .clone()
    }

    /// Turns the agent's journal into protocol events. The journal is the source
    /// of truth; this only renames kinds and copies the fields the UI reads.
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

    fn mark_cancel(&self, thread: &str) {
        let mut map = self.cancel.lock().unwrap();
        let flag = map
            .entry(thread.to_owned())
            .or_insert_with(|| Arc::new(AtomicBool::new(false)));
        flag.store(true, Ordering::SeqCst);
    }
}

/// The agent writes `EventKind`; the workbench dispatches on `method`. Keeping
/// the mapping in one function means a new kind fails loudly at the call site
/// rather than silently disappearing from the UI.
///
/// The payload is also adapted, not just renamed: the agent records
/// `approval_id` while the workbench reads `payload.request_id` (it later sends
/// that value back as `approval/respond`'s `request_id`). Without this the UI
/// would render an approval card with no id and could not answer it.
fn translate(kind: &EventKind, payload: &serde_json::Value) -> (String, serde_json::Value) {
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

impl TurnRunner for Runner {
    fn start_turn(
        &self,
        thread_id: &str,
        prompt: &str,
        client_message_id: &str,
        sink: EventSink<'_>,
    ) -> Result<(), String> {
        // Acceptance must be the first frame and it must be a real journal
        // event: the client treats it as authoritative and also orders every
        // later event by `seq`. A synthetic seq would collide with the journal
        // and make the UI drop or reorder real work.
        let accepted = {
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
        };
        let accept_seq = accepted.seq.ok_or_else(|| {
            "the store accepted the command without returning a sequence".to_owned()
        })?;
        let accept_event = {
            let store = self.store.lock().unwrap();
            store
                .events(thread_id, accept_seq.saturating_sub(1))
                .map_err(|e| e.to_string())?
                .into_iter()
                .find(|event| event.seq == accept_seq)
                .ok_or_else(|| "the acceptance event is missing from the journal".to_owned())?
        };
        {
            let (method, payload) = translate(&accept_event.kind, &accept_event.payload);
            sink(BridgeEvent {
                method,
                seq: accept_seq,
                payload,
                client_message_id: Some(client_message_id.to_owned()),
            });
        }

        let cancel = self.cancel_flag(thread_id);
        cancel.store(false, Ordering::SeqCst);

        let files = sunday_platform::LocalFiles::new(&self.workspace).map_err(|e| e.to_string())?;
        let files = Arc::new(files);
        let read = ReadFile::new(files.clone());
        let write = WriteFile::new(files);
        let tools: Vec<&dyn sunday_protocol::Tool> = vec![&read, &write];
        let auto = AutoApprove;
        let policy = PolicyApprover;
        let approver: &dyn Approver = if self.auto_approve { &auto } else { &policy };

        let env = Env {
            store: &self.store,
            model: self.model.as_ref(),
            tools: &tools,
            approver,
            cancel: &cancel,
            workspace: "local".into(),
            host: HostKind::Server,
            context: None,
        };
        let input = TurnInput {
            thread_id: thread_id.to_owned(),
            turn_id: format!("turn-{}", self.seq.load(Ordering::SeqCst)),
            model_id: self.model_id.clone(),
            system: Some("You are Sunday. Use the tools you are given.".into()),
            prompt: prompt.to_owned(),
        };

        // The agent is async; this trait is sync because the adapter calls it
        // from a worker thread.
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .map_err(|e| format!("runtime: {e}"))?;
        let run = runtime.block_on(sunday_agent::run_turn(&env, input, RunBudget::default()));

        // Report whatever the run produced, whether it succeeded or not. Start
        // after the acceptance event so the client does not see it twice.
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
                // Denying must not execute the tool. Record the decision and let
                // the caller resume on the next turn.
                let mut store = self.store.lock().unwrap();
                store
                    .respond_approval(request_id, "", now_ms(), false)
                    .map_err(|e| e.to_string())?;
                drop(store);
                self.emit_journal(thread_id, sink, 0);
                return Ok(());
            }
            "guide" => {
                // Guidance is a new instruction, not an approval. It is stored
                // so the next turn picks it up.
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

        // The digest binds this decision to the exact arguments the user was
        // shown, so approving one call cannot silently authorise another.
        let digest = {
            let store = self.store.lock().unwrap();
            match store.pending_call(request_id) {
                Ok(Some((_, digest))) => digest,
                Ok(None) => return Err("that approval has no pending call".into()),
                Err(e) => return Err(e.to_string()),
            }
        };
        let cancel = self.cancel_flag(thread_id);

        let files = sunday_platform::LocalFiles::new(&self.workspace).map_err(|e| e.to_string())?;
        let files = Arc::new(files);
        let read = ReadFile::new(files.clone());
        let write = WriteFile::new(files);
        let tools: Vec<&dyn sunday_protocol::Tool> = vec![&read, &write];
        let auto = AutoApprove;
        let policy = PolicyApprover;
        let approver: &dyn Approver = if self.auto_approve { &auto } else { &policy };

        let env = Env {
            store: &self.store,
            model: self.model.as_ref(),
            tools: &tools,
            approver,
            cancel: &cancel,
            workspace: "local".into(),
            host: HostKind::Server,
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
        // Prefer the journal: it survives a restart, which the in-memory buffer
        // deliberately does not.
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
        out.sort_by_key(|e| e.seq);
        Ok(out)
    }
}

fn now_ms() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

/// Runs the server until the listener closes. Returns a process exit code.
pub fn run(options: Options) -> Result<(), CoreError> {
    // One writer per data directory, or refuse. This is the guard that stops two
    // cores from corrupting the same database.
    let lock = match SingleWriterLock::acquire(options.db_dir(), "sunday-serve", STALE_AFTER) {
        Ok(lock) => lock,
        Err(LockError::Busy { owner, pid, age_ms }) => {
            return Err(CoreError::Rejected {
                reason: format!(
                    "another core is writing this data directory: {owner} (pid {pid}, \
                     heartbeat {age_ms}ms ago). Close it first."
                ),
            })
        }
        Err(LockError::Io(reason)) => return Err(CoreError::Storage { reason }),
    };

    let store = Store::open(&options.db)?;
    let runner = Arc::new(Runner {
        store: Mutex::new(store),
        model: options.model,
        model_id: options.model_id,
        workspace: options.workspace,
        auto_approve: options.auto_approve,
        seq: AtomicU64::new(0),
        buffer: EventBuffer::default(),
        cancel: Mutex::new(HashMap::new()),
    });

    let server = AppServer::bind(&options.listen, runner)
        .map_err(|e| CoreError::storage(format!("cannot listen on {}: {e}", options.listen)))?;
    let addr = server
        .local_addr()
        .map_err(|e| CoreError::storage(format!("cannot read the bound address: {e}")))?;
    // The host prints the real address so a UI can be pointed at it even when
    // port 0 was requested.
    println!("listening ws://{addr} protocol core.app_server.v1");
    server.serve();
    let _ = lock.release();
    Ok(())
}

impl Options {
    /// The lock protects the data directory, so it lives beside the database.
    fn db_dir(&self) -> String {
        std::path::Path::new(&self.db)
            .parent()
            .map(|p| p.to_string_lossy().to_string())
            .filter(|p| !p.is_empty())
            .unwrap_or_else(|| ".".into())
    }
}

/// Builds a model from the command line. Kept here so the `serve` command has
/// no hidden default: without an explicit choice there is no model at all.
pub fn model_from_args(
    script: Option<String>,
    model_url: Option<String>,
    model_id: Option<String>,
    api_key: Option<String>,
) -> Result<(Arc<dyn Model>, String), CoreError> {
    if let Some(path) = script {
        let text = std::fs::read_to_string(&path)
            .map_err(|e| CoreError::invalid(format!("cannot read {path}: {e}")))?;
        let model = crate::scripted::ScriptedModel::from_json(&text)?;
        return Ok((Arc::new(model), "scripted".into()));
    }
    match (model_url, model_id) {
        (Some(url), Some(id)) => {
            let client = LlmClient::new(ProviderConfig::openai(url, api_key.unwrap_or_default()))?;
            Ok((Arc::new(client), id))
        }
        _ => Err(CoreError::invalid(
            "pass either --script <file>, or --model-url <url> and --model <id>",
        )),
    }
}
