//! Runs the core inside the host process.
//!
//! This is the same wiring `sunday serve` does for the desktop, with two
//! Android-specific differences that matter:
//!
//!   * the data directory is the app's own sandbox, resolved by Tauri
//!   * the model is chosen from a config file in that sandbox rather than from
//!     command-line flags, because an app has no command line
//!
//! The single-writer lock is taken here too. Two hosts writing one database is
//! the failure the lock exists to prevent, and an app can be relaunched while a
//! previous instance is still shutting down.

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use sunday_agent::{Approval, Approver, AutoApprove, Env, TurnInput};
use sunday_host::app_server::{
    AppServer, BridgeEvent, EventBuffer, EventSink, HistoryPage, QueueView, SteerOutcome, StopMode,
    TurnRunner,
};
use sunday_host::lock::SingleWriterLock;
use sunday_llm::{LlmClient, ProviderConfig};
use sunday_protocol::{
    CancelToken, EventKind, HostKind, Model, Permission, RunBudget, RunOutcome, ToolCall, ToolSpec,
};
use sunday_store::Store;
use sunday_tools::file_read::ReadFile;
use sunday_tools::file_write::WriteFile;

/// Long enough that a slow app pause cannot hand the database to a second host.
const STALE_AFTER: std::time::Duration = std::time::Duration::from_secs(10);
const LOCK_FILE: &str = "core.lock";
const CONFIG_FILE: &str = "core.config.json";

/// What the app is configured to talk to. Written by the app, read at startup.
#[derive(Clone, Debug, serde::Deserialize, serde::Serialize)]
pub struct CoreConfig {
    /// OpenAI-compatible endpoint, for example `http://10.0.2.2:11434/v1`.
    pub base_url: String,
    pub model_id: String,
    #[serde(default)]
    pub api_key: String,
    #[serde(default = "default_auto_approve")]
    pub auto_approve: bool,
}

fn default_auto_approve() -> bool {
    true
}

impl Default for CoreConfig {
    fn default() -> Self {
        Self {
            base_url: "http://10.0.2.2:11434/v1".into(),
            model_id: "qwen2.5:3b".into(),
            api_key: String::new(),
            auto_approve: true,
        }
    }
}

pub struct CoreService {
    port: u16,
    data_dir: PathBuf,
    /// Held for the process lifetime; dropping it releases the lock.
    _lock: SingleWriterLock,
}

impl CoreService {
    pub fn start(data_dir: PathBuf) -> Result<Self, Box<dyn std::error::Error>> {
        // Lock before touching the database.
        //
        // Waiting rather than failing: on a phone, force-stop followed by an
        // immediate relaunch is normal, and the previous process leaves a lock
        // whose heartbeat is still inside the reclaim window. Failing instantly
        // there would look like "the app does not open" to the user. The wait is
        // bounded by the reclaim window itself, so a genuinely live writer is
        // still respected: we only take over once its heartbeat has gone stale.
        let lock = acquire_with_wait(&data_dir)?;

        let config = read_config(&data_dir)?;
        let db = data_dir.join("core.db");
        let workspace = data_dir.join("workspace");
        std::fs::create_dir_all(&workspace)?;

        let store = Store::open(&db)?;
        let model: Arc<dyn Model> = Arc::new(LlmClient::new(ProviderConfig::openai(
            config.base_url.clone(),
            config.api_key.clone(),
        ))?);

        let runner = Arc::new(AndroidRunner {
            store: Mutex::new(store),
            model,
            model_id: config.model_id.clone(),
            workspace: workspace.to_string_lossy().to_string(),
            auto_approve: config.auto_approve,
            seq: AtomicU64::new(0),
            buffer: EventBuffer::default(),
            cancel: Mutex::new(HashMap::new()),
            live: Mutex::new(HashMap::new()),
        });

        // Port 0: let the OS pick. A fixed port would collide with whatever else
        // the device is running and would let another app talk to this core.
        let server = AppServer::bind("127.0.0.1:0", runner)?;
        let port = server.local_addr()?.port();
        std::thread::spawn(move || server.serve());

        Ok(Self {
            port,
            data_dir,
            _lock: lock,
        })
    }

    pub fn port(&self) -> u16 {
        self.port
    }

    pub fn data_dir(&self) -> &Path {
        &self.data_dir
    }
}

/// Acquires the single-writer lock, waiting out the reclaim window.
///
/// A previous instance killed by the OS or by force-stop leaves a lock file whose
/// last heartbeat is seconds old. That is indistinguishable from a live writer,
/// which is exactly the trade the lock makes, so the only correct move is to wait
/// for the window and then take over. Refusing instead would make the app appear
/// broken after every crash.
fn acquire_with_wait(dir: &Path) -> Result<SingleWriterLock, Box<dyn std::error::Error>> {
    let deadline = std::time::Instant::now() + STALE_AFTER + std::time::Duration::from_secs(2);
    let mut attempts = 0u32;
    loop {
        match SingleWriterLock::acquire(dir, "sunday-android", STALE_AFTER) {
            Ok(lock) => return Ok(lock),
            Err(error) => {
                attempts += 1;
                if std::time::Instant::now() >= deadline {
                    return Err(format!(
                        "another core is writing {} after {attempts} attempts: {error}",
                        dir.display()
                    )
                    .into());
                }
                // Short sleeps: the window is measured in seconds, and a long
                // sleep here would make launch feel slow even in the common case.
                std::thread::sleep(std::time::Duration::from_millis(250));
            }
        }
    }
}

fn read_config(dir: &Path) -> Result<CoreConfig, Box<dyn std::error::Error>> {
    let path = dir.join(CONFIG_FILE);
    if !path.exists() {
        // Write the default so a user can edit it without reverse-engineering
        // the format, and so the first run says what it is going to talk to.
        let config = CoreConfig::default();
        std::fs::write(&path, serde_json::to_string_pretty(&config)?)?;
        return Ok(config);
    }
    let text = std::fs::read_to_string(&path)?;
    Ok(serde_json::from_str(&text)?)
}

/// Who gets asked. A tool marked `AskUser` always asks.
struct PolicyApprover;

impl Approver for PolicyApprover {
    fn decide(&self, _call: &ToolCall, spec: &ToolSpec) -> Approval {
        match spec.permission {
            Permission::AskUser => Approval::Ask,
            _ => Approval::Auto,
        }
    }
}

struct AndroidRunner {
    store: Mutex<Store>,
    model: Arc<dyn Model>,
    model_id: String,
    workspace: String,
    auto_approve: bool,
    seq: AtomicU64,
    buffer: EventBuffer,
    cancel: Mutex<HashMap<String, CancelToken>>,
    live: Mutex<HashMap<String, bool>>,
}

fn now_ms() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

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
    if matches!(kind, EventKind::ApprovalRequested | EventKind::ApprovalResolved) {
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

impl AndroidRunner {
    fn cancel_flag(&self, thread: &str) -> CancelToken {
        let mut map = self.cancel.lock().unwrap();
        map.entry(thread.to_owned()).or_default().clone()
    }

    fn mark_cancel(&self, thread: &str) {
        let mut map = self.cancel.lock().unwrap();
        map.entry(thread.to_owned()).or_default().cancel();
    }

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

impl TurnRunner for AndroidRunner {
    fn start_turn(
        &self,
        thread_id: &str,
        prompt: &str,
        client_message_id: &str,
        sink: EventSink<'_>,
    ) -> Result<(), String> {
        // Acceptance must be a real journal event with a real seq, or the UI
        // reorders everything after it.
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
                    input_json: String::new(),
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
                .find(|e| e.seq == accept_seq)
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

        let cancel = self.cancel_flag(thread_id);
        cancel.reset();
        self.live.lock().unwrap().insert(thread_id.to_owned(), true);

        let files = Arc::new(
            sunday_platform::LocalFiles::new(&self.workspace).map_err(|e| e.to_string())?,
        );
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
            host: HostKind::Android,
            context: None,
        };
        let input = TurnInput {
            thread_id: thread_id.to_owned(),
            turn_id: format!("turn-{}", self.seq.load(Ordering::SeqCst)),
            model_id: self.model_id.clone(),
            system: Some("You are Sunday. Use the tools you are given.".into()),
            prompt: prompt.to_owned(),
        };

        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .map_err(|e| format!("runtime: {e}"))?;
        let run = runtime.block_on(sunday_agent::run_turn(&env, input, RunBudget::default()));

        self.live.lock().unwrap().insert(thread_id.to_owned(), false);
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

        let digest = {
            let store = self.store.lock().unwrap();
            match store.pending_call(request_id) {
                Ok(Some((_, digest))) => digest,
                Ok(None) => return Err("that approval has no pending call".into()),
                Err(e) => return Err(e.to_string()),
            }
        };
        let cancel = self.cancel_flag(thread_id);

        let files = Arc::new(
            sunday_platform::LocalFiles::new(&self.workspace).map_err(|e| e.to_string())?,
        );
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
            host: HostKind::Android,
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
        out.sort_by_key(|e| e.seq);
        Ok(out)
    }

    fn open_thread(&self, thread_id: &str) -> Result<Vec<BridgeEvent>, String> {
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
            return Err(format!("no queue item {queue_item_id}"));
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
        let live = {
            let map = self.live.lock().unwrap();
            map.get(thread_id).copied().unwrap_or(false)
        };
        if !live {
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

    fn stop_turn(&self, thread_id: &str, mode: StopMode, sink: EventSink<'_>) -> Result<(), String> {
        self.mark_cancel(thread_id);
        if matches!(mode, StopMode::Terminate | StopMode::ForceReset) {
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
}

/// Tells the frontend which port the core got.
#[tauri::command]
pub fn core_port(state: tauri::State<'_, Arc<CoreService>>) -> u16 {
    state.port()
}

/// Where the data actually lives, for the About screen and for tests.
#[tauri::command]
pub fn core_info(state: tauri::State<'_, Arc<CoreService>>) -> serde_json::Value {
    serde_json::json!({
        "port": state.port(),
        "data_dir": state.data_dir().to_string_lossy(),
        "lock_file": LOCK_FILE,
    })
}
