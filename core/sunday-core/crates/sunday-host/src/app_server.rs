//! `core.app_server.v1` adapter.
//!
//! The existing Vue workbench already speaks this protocol. Rather than invent a
//! second one, the new core answers the same JSON-RPC frames over WebSocket, so
//! the same UI can be pointed at either backend.
//!
//! Every field name here was read off the real client
//! (`core/ui/src/appServer/client.ts` and `store.ts`), not guessed:
//!   * `initialize` params are camelCase: `clientInfo`, `threadId`, `lastSeenSeq`.
//!   * `turn/start` params are snake_case: `thread_id`, `client_message_id`,
//!     `input` (array of `{type:"text",text}`), `work_root`, `include_snapshot`.
//!   * `approval/respond` params are `request_id`, `thread_id`, `decision`,
//!     `guidance` — the backend normalises `approve_once`/`other_guidance`
//!     aliases and accepts approve|deny|guide|skip|trust.
//!   * Events are notifications whose `params` is the whole `CoreAppEvent`
//!     envelope, including its own `method`.
//!
//! A turn runs on its own thread so the socket stays readable while it streams.
//! Without that, `turn/cancel` would sit in the socket buffer until the turn it
//! is meant to stop had already finished.
//!
//! Scope: the subset a workbench needs to open a thread, run a turn, stream
//! output, ask for approval and cancel. Anything else answers
//! `METHOD_NOT_FOUND`, because a fake `{}` reply would hide the gap.

use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::sync::mpsc::{Receiver, Sender};
use std::sync::Arc;
use std::time::Duration;
use sunday_protocol::PROTOCOL_VERSION;
use tungstenite::{accept, Message};

pub const APP_SERVER_PROTOCOL: &str = "core.app_server.v1";

/// How often the read loop wakes up to flush queued outbound frames. Small
/// enough that a cancel is noticed during a turn, large enough not to spin.
const READ_TICK: Duration = Duration::from_millis(25);

/// Where a running turn pushes its events. The adapter owns framing; the runner
/// only decides what happened.
pub type EventSink<'a> = &'a (dyn Fn(BridgeEvent) + Send + Sync);

/// One queued message as the workbench renders it.
#[derive(Clone, Debug, PartialEq)]
pub struct QueueView {
    pub queue_item_id: String,
    pub position: u64,
    pub input: String,
    pub status: String,
}

/// What a steer attempt did. The client distinguishes "applied" from "queued"
/// from "failed", and shows different text for each, so this cannot be a bool.
#[derive(Clone, Debug, PartialEq)]
pub struct SteerOutcome {
    pub applied: bool,
    pub queued: bool,
    pub reason: String,
}

/// A page of transcript.
#[derive(Clone, Debug, PartialEq)]
pub struct HistoryPage {
    pub events: Vec<BridgeEvent>,
    pub has_more: bool,
    pub total_items: u64,
}

/// What the adapter needs from whoever assembles the core.
///
/// Every method here has a caller in `core/ui/src/appServer/store.ts`. Methods
/// the workbench does not call are deliberately absent: an unimplemented method
/// answering `METHOD_NOT_FOUND` is honest, but a method that exists and returns
/// an empty object is not.
pub trait TurnRunner: Send + Sync {
    /// Starts a turn. Emit `turn/accepted` first: the client treats that event
    /// as the authoritative acceptance and stops waiting on the RPC reply.
    fn start_turn(
        &self,
        thread_id: &str,
        prompt: &str,
        client_message_id: &str,
        sink: EventSink<'_>,
    ) -> Result<(), String>;
    /// Resolves a pending approval. `decision` is already normalised to
    /// approve|deny|guide|skip|trust.
    fn respond(
        &self,
        thread_id: &str,
        request_id: &str,
        decision: &str,
        guidance: &str,
        sink: EventSink<'_>,
    ) -> Result<(), String>;
    fn cancel(&self, thread_id: &str) -> Result<Vec<BridgeEvent>, String>;
    fn events(&self, thread_id: &str, after: u64) -> Result<Vec<BridgeEvent>, String>;

    /// Opens a thread. Creating one is idempotent, so a retried press is safe.
    ///
    /// Defaults below answer with an explicit "not implemented by this runner"
    /// rather than an empty success. A stub that silently reports "no queue" is
    /// worse than one that says so: the UI would show an empty queue while the
    /// user's text went nowhere. The real host overrides every one of these.
    fn open_thread(&self, _thread_id: &str) -> Result<Vec<BridgeEvent>, String> {
        Err(NOT_IMPLEMENTED.to_owned())
    }

    /// A page of transcript, oldest first within the page.
    fn history(
        &self,
        _thread_id: &str,
        _before_seq: Option<u64>,
        _limit: usize,
    ) -> Result<HistoryPage, String> {
        Err(NOT_IMPLEMENTED.to_owned())
    }

    /// The queue in the user's order.
    fn queue(&self, _thread_id: &str) -> Result<Vec<QueueView>, String> {
        Err(NOT_IMPLEMENTED.to_owned())
    }
    fn queue_create(
        &self,
        _thread_id: &str,
        _queue_item_id: &str,
        _text: &str,
    ) -> Result<Vec<QueueView>, String> {
        Err(NOT_IMPLEMENTED.to_owned())
    }
    fn queue_update(
        &self,
        _thread_id: &str,
        _queue_item_id: &str,
        _text: &str,
    ) -> Result<Vec<QueueView>, String> {
        Err(NOT_IMPLEMENTED.to_owned())
    }
    fn queue_delete(
        &self,
        _thread_id: &str,
        _queue_item_id: &str,
    ) -> Result<Vec<QueueView>, String> {
        Err(NOT_IMPLEMENTED.to_owned())
    }
    fn queue_reorder(&self, _thread_id: &str, _order: &[String]) -> Result<Vec<QueueView>, String> {
        Err(NOT_IMPLEMENTED.to_owned())
    }

    /// A message typed while a turn is running. Applied if the turn is still
    /// live, otherwise reported as not applied so the client can queue it.
    fn steer(&self, _thread_id: &str, _turn_id: &str, _text: &str) -> Result<SteerOutcome, String> {
        Err(NOT_IMPLEMENTED.to_owned())
    }

    /// Stop the live turn. The difference between pause, interrupt, terminate
    /// and force_reset is how much cleanup the caller wants, not whether it
    /// stops, so they share one implementation with a policy argument.
    fn stop_turn(
        &self,
        thread_id: &str,
        _mode: StopMode,
        _sink: EventSink<'_>,
    ) -> Result<(), String> {
        self.cancel(thread_id).map(|_| ())
    }
}

/// The message a runner that does not implement an optional capability returns.
pub const NOT_IMPLEMENTED: &str = "this runner does not implement that method";

/// What kind of stop the user asked for.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum StopMode {
    /// Single click: finish what is dispatched, start nothing new.
    Pause,
    /// Abandon the current model call and start nothing new.
    Interrupt,
    /// Stop and discard the turn.
    Terminate,
    /// Stop even if the journal disagrees about what is running.
    ForceReset,
}

/// One event, already shaped like `CoreAppEvent`.
#[derive(Clone, Debug, PartialEq)]
pub struct BridgeEvent {
    pub method: String,
    pub seq: u64,
    pub payload: serde_json::Value,
    pub client_message_id: Option<String>,
}

pub struct AppServer {
    listener: TcpListener,
    runner: Arc<dyn TurnRunner>,
}

impl AppServer {
    pub fn bind(addr: &str, runner: Arc<dyn TurnRunner>) -> std::io::Result<Self> {
        let listener = TcpListener::bind(addr)?;
        Ok(Self { listener, runner })
    }

    pub fn local_addr(&self) -> std::io::Result<std::net::SocketAddr> {
        self.listener.local_addr()
    }

    /// Serves connections until the listener closes. One thread per client: the
    /// workbench opens a dedicated socket per window.
    pub fn serve(self) {
        let runner = self.runner.clone();
        for stream in self.listener.incoming() {
            let Ok(stream) = stream else { break };
            let runner = runner.clone();
            std::thread::spawn(move || {
                let _ = handle_client(stream, runner);
            });
        }
    }
}

/// Frames the main loop still has to write. A turn thread produces them; only
/// the socket-owning thread touches the socket.
enum Outbound {
    Result {
        id: serde_json::Value,
        body: serde_json::Value,
    },
    Error {
        id: serde_json::Value,
        code: i32,
        message: String,
        data: Option<serde_json::Value>,
    },
    Event {
        body: serde_json::Value,
    },
}

struct State {
    thread_id: String,
    initialized: bool,
}

fn handle_client(stream: TcpStream, runner: Arc<dyn TurnRunner>) -> std::io::Result<()> {
    stream.set_nodelay(true)?;
    stream.set_read_timeout(Some(READ_TICK))?;
    let mut socket = accept(stream).map_err(std::io::Error::other)?;
    let mut state = State {
        thread_id: String::new(),
        initialized: false,
    };
    let (tx, rx): (Sender<Outbound>, Receiver<Outbound>) = std::sync::mpsc::channel();

    loop {
        let message = match socket.read() {
            Ok(Message::Text(text)) => Some(text),
            Ok(Message::Close(_)) => break,
            Ok(Message::Ping(payload)) => {
                let _ = socket.send(Message::Pong(payload));
                None
            }
            // A read timeout is the normal case between frames: it is how this
            // loop stays responsive to work happening on turn threads.
            Err(tungstenite::Error::Io(err))
                if matches!(
                    err.kind(),
                    std::io::ErrorKind::WouldBlock | std::io::ErrorKind::TimedOut
                ) =>
            {
                None
            }
            Ok(_) => None,
            Err(_) => break,
        };

        // Flush whatever the turn threads produced, including their reasoning
        // about the frame that just arrived.
        while let Ok(item) = rx.try_recv() {
            let _ = socket.send(Message::Text(render(item).into()));
        }

        let Some(message) = message else { continue };
        let value: serde_json::Value = match serde_json::from_str(&message) {
            Ok(value) => value,
            Err(_) => continue,
        };
        let id = value.get("id").cloned();
        let method = value
            .get("method")
            .and_then(|m| m.as_str())
            .unwrap_or_default()
            .to_owned();
        let params = value
            .get("params")
            .cloned()
            .unwrap_or_else(|| serde_json::json!({}));

        // A response to a server-initiated request carries an id but no method.
        // This adapter reports approvals as events, so there is nothing to do.
        if method.is_empty() {
            continue;
        }

        match dispatch(&method, &params, &mut state, runner.clone(), &tx) {
            Ok(result) => {
                // `_events` is scaffolding, never part of the client's result.
                let events = result
                    .get("_events")
                    .and_then(|e| e.as_array())
                    .cloned()
                    .unwrap_or_default();
                let mut result = result;
                if let Some(object) = result.as_object_mut() {
                    object.remove("_events");
                }
                if let Some(id) = id {
                    let _ = socket.send(Message::Text(
                        render(Outbound::Result { id, body: result }).into(),
                    ));
                }
                for event in events {
                    let _ = socket.send(Message::Text(
                        render(Outbound::Event { body: event }).into(),
                    ));
                }
            }
            Err((code, message, data)) => {
                if let Some(id) = id {
                    let _ = socket.send(Message::Text(
                        render(Outbound::Error {
                            id,
                            code,
                            message,
                            data,
                        })
                        .into(),
                    ));
                }
            }
        }
    }

    // One last flush so a turn that finished during teardown still reports.
    while let Ok(item) = rx.try_recv() {
        let _ = socket.send(Message::Text(render(item).into()));
    }
    let _ = socket.close(None);
    Ok(())
}

fn render(item: Outbound) -> String {
    match item {
        Outbound::Result { id, body } => serde_json::json!({"id": id, "result": body}).to_string(),
        Outbound::Error {
            id,
            code,
            message,
            data,
        } => serde_json::json!({
            "id": id,
            "error": {"code": code, "message": message, "data": data}
        })
        .to_string(),
        Outbound::Event { body } => {
            serde_json::json!({"method": body["method"], "params": body}).to_string()
        }
    }
}

/// Which methods this adapter actually answers.
///
/// Exposed so a test can compare it against the list the workbench calls. A
/// method that exists on the trait but is missing here is indistinguishable from
/// an unimplemented one, and that is the exact gap this guards.
pub const DISPATCHED: &[&str] = &[
    "initialize",
    "initialized",
    "thread/start",
    "thread/resume",
    "thread/read",
    "thread/snapshot",
    "turn/start",
    "turn/resume",
    "turn/cancel",
    "turn/steer",
    "turn/pause",
    "turn/interrupt",
    "turn/terminate",
    "turn/force_reset",
    "queue/list",
    "queue/create",
    "queue/update",
    "queue/delete",
    "queue/guide",
    "queue/reorder",
    "approval/respond",
];

pub fn is_dispatched(method: &str) -> bool {
    DISPATCHED.contains(&method)
}

type Reply = Result<serde_json::Value, (i32, String, Option<serde_json::Value>)>;

/// The client sends `threadId` for `initialize` and `thread_id` everywhere else.
/// Accept both rather than silently dropping the resume thread.
fn thread_param(params: &serde_json::Value) -> String {
    params
        .get("thread_id")
        .or_else(|| params.get("threadId"))
        .and_then(|v| v.as_str())
        .unwrap_or_default()
        .to_owned()
}

/// Plain approval decisions, plus the aliases the Python backend accepted, so a
/// UI that still sends `approve_once` keeps working.
fn normalise_decision(raw: &str) -> &str {
    match raw {
        "approve_once" | "approve_for_session" => "approve",
        "other_guidance" | "answer" => "guide",
        other => other,
    }
}

fn dispatch(
    method: &str,
    params: &serde_json::Value,
    state: &mut State,
    runner: Arc<dyn TurnRunner>,
    tx: &Sender<Outbound>,
) -> Reply {
    // The runner is cloned per worker thread below; nothing here needs a
    // borrowed alias, so do not create one.
    let thread = thread_param(params);

    match method {
        "initialize" => {
            state.initialized = true;
            if !thread.is_empty() {
                state.thread_id = thread.clone();
                let after = params
                    .get("lastSeenSeq")
                    .or_else(|| params.get("last_seen_seq"))
                    .and_then(|v| v.as_u64())
                    .unwrap_or(0);
                let events = runner
                    .events(&thread, after)
                    .map_err(|e| (-32000, e, None))?;
                return Ok(serde_json::json!({
                    "capabilities": capabilities(),
                    "_events": events.iter().map(|e| event_json(&thread, e)).collect::<Vec<_>>(),
                }));
            }
            Ok(serde_json::json!({ "capabilities": capabilities() }))
        }
        "initialized" => Ok(serde_json::json!({})),
        "thread/start" | "thread/resume" => {
            // `thread/start` and `thread/resume` are the same operation from the
            // journal's point of view: make sure the conversation exists and hand
            // back its tail. A retried press therefore cannot fork a thread.
            let thread = if thread.is_empty() {
                state.thread_id.clone()
            } else {
                thread
            };
            if thread.is_empty() {
                return Err((-32602, "thread_id is required".into(), None));
            }
            state.thread_id = thread.clone();
            let events = runner.open_thread(&thread).map_err(|e| (-32000, e, None))?;
            Ok(serde_json::json!({
                "thread_id": thread,
                "_events": events.iter().map(|e| event_json(&thread, e)).collect::<Vec<_>>(),
            }))
        }
        "thread/read" => {
            let thread = if thread.is_empty() {
                state.thread_id.clone()
            } else {
                thread
            };
            if thread.is_empty() {
                return Err((-32602, "thread_id is required".into(), None));
            }
            state.thread_id = thread.clone();
            let before_seq = params
                .get("before_seq")
                .or_else(|| params.get("next_before_seq"))
                .and_then(|v| v.as_u64());
            let limit = params
                .get("limit")
                .or_else(|| params.get("turn_limit"))
                .and_then(|v| v.as_u64())
                .unwrap_or(100) as usize;
            let page = runner
                .history(&thread, before_seq, limit)
                .map_err(|e| (-32000, e, None))?;
            let next_before = page.events.first().map(|e| e.seq);
            Ok(serde_json::json!({
                "thread_id": thread,
                "snapshot_seq": page.events.last().map(|e| e.seq).unwrap_or(0),
                "history_page": {
                    "char_limit": 0,
                    "character_count": 0,
                    "turn_limit": limit,
                    "turn_count": page.events.len(),
                    "item_count": page.events.len(),
                    "total_items": page.total_items,
                    "has_more": page.has_more,
                    "next_before_seq": next_before,
                },
                "status": "idle",
                "turns": {},
                "items": {},
                "item_order": [],
                "_events": page.events.iter().map(|e| event_json(&thread, e)).collect::<Vec<_>>(),
            }))
        }
        "queue/list" => {
            let thread = if thread.is_empty() {
                state.thread_id.clone()
            } else {
                thread
            };
            let items = runner.queue(&thread).map_err(|e| (-32000, e, None))?;
            Ok(serde_json::json!({
                "thread_id": thread,
                "queue": items.iter().map(queue_json).collect::<Vec<_>>(),
            }))
        }
        "queue/create" | "queue/update" | "queue/delete" | "queue/reorder" | "queue/guide" => {
            let thread = if thread.is_empty() {
                state.thread_id.clone()
            } else {
                thread
            };
            if thread.is_empty() {
                return Err((-32602, "thread_id is required".into(), None));
            }
            state.thread_id = thread.clone();
            let item_id = params
                .get("queue_item_id")
                .and_then(|v| v.as_str())
                .unwrap_or_default()
                .to_owned();
            let text = prompt_param(params);
            let items = match method {
                "queue/create" => {
                    let id = if item_id.is_empty() {
                        // The client normally supplies its own idempotency key.
                        // Without one, derive a stable id from the content so a
                        // retried create still cannot duplicate.
                        format!("queue-{}", app_server_fnv(&format!("{thread}:{text}")))
                    } else {
                        item_id
                    };
                    runner.queue_create(&thread, &id, &text)
                }
                "queue/update" => {
                    if item_id.is_empty() {
                        return Err((-32602, "queue_item_id is required".into(), None));
                    }
                    runner.queue_update(&thread, &item_id, &text)
                }
                "queue/delete" => {
                    if item_id.is_empty() {
                        return Err((-32602, "queue_item_id is required".into(), None));
                    }
                    runner.queue_delete(&thread, &item_id)
                }
                "queue/reorder" => {
                    let order: Vec<String> = params
                        .get("order")
                        .or_else(|| params.get("queue_item_ids"))
                        .and_then(|v| v.as_array())
                        .map(|items| {
                            items
                                .iter()
                                .filter_map(|v| v.as_str().map(str::to_owned))
                                .collect()
                        })
                        .unwrap_or_default();
                    if order.is_empty() {
                        return Err((-32602, "order is required".into(), None));
                    }
                    runner.queue_reorder(&thread, &order)
                }
                // `queue/guide` edits the text of an existing item, which is what
                // the UI's inline edit actually does.
                _ => {
                    if item_id.is_empty() {
                        return Err((-32602, "queue_item_id is required".into(), None));
                    }
                    runner.queue_update(&thread, &item_id, &text)
                }
            }
            .map_err(|e| (-32000, e, None))?;
            Ok(serde_json::json!({
                "thread_id": thread,
                "queue": items.iter().map(queue_json).collect::<Vec<_>>(),
            }))
        }
        "turn/steer" => {
            let thread = if thread.is_empty() {
                state.thread_id.clone()
            } else {
                thread
            };
            if thread.is_empty() {
                return Err((-32602, "thread_id is required".into(), None));
            }
            let turn = params
                .get("turn_id")
                .and_then(|v| v.as_str())
                .unwrap_or_default()
                .to_owned();
            let text = prompt_param(params);
            if text.is_empty() {
                return Err((-32602, "input carries no text".into(), None));
            }
            let outcome = runner
                .steer(&thread, &turn, &text)
                .map_err(|e| (-32000, e, None))?;
            // The client reads `applied` to decide what to show, and does not
            // treat a refusal as an error. Answering with an error here would make
            // it show a failure toast instead of queueing the text.
            Ok(serde_json::json!({
                "thread_id": thread,
                "applied": outcome.applied,
                "queued": outcome.queued,
                "reason": outcome.reason,
            }))
        }
        "turn/pause" | "turn/interrupt" | "turn/terminate" | "turn/force_reset" => {
            let thread = if thread.is_empty() {
                state.thread_id.clone()
            } else {
                thread
            };
            if thread.is_empty() {
                return Err((-32602, "thread_id is required".into(), None));
            }
            state.thread_id = thread.clone();
            let mode = match method {
                "turn/pause" => StopMode::Pause,
                "turn/interrupt" => StopMode::Interrupt,
                "turn/terminate" => StopMode::Terminate,
                _ => StopMode::ForceReset,
            };
            let worker = runner.clone();
            let sink_sender = tx.clone();
            let error_sender = tx.clone();
            let thread_for_run = thread.clone();
            std::thread::spawn(move || {
                let sink = move |event: BridgeEvent| {
                    let _ = sink_sender.send(Outbound::Event {
                        body: event_json(&thread_for_run, &event),
                    });
                };
                if let Err(error) = worker.stop_turn(&thread, mode, &sink) {
                    let _ = error_sender.send(Outbound::Error {
                        id: serde_json::Value::Null,
                        code: -32000,
                        message: error,
                        data: None,
                    });
                }
            });
            Ok(serde_json::json!({}))
        }
        "thread/snapshot" => {
            let thread = if thread.is_empty() {
                state.thread_id.clone()
            } else {
                thread
            };
            let events = runner.events(&thread, 0).map_err(|e| (-32000, e, None))?;
            Ok(serde_json::json!({
                "thread_id": thread,
                "snapshot_seq": events.last().map(|e| e.seq).unwrap_or(0),
                "turns": {},
                "items": {},
                "item_order": [],
                "status": "idle",
            }))
        }
        "turn/start" | "turn/resume" => {
            let prompt = prompt_param(params);
            let client_id = params
                .get("client_message_id")
                .and_then(|v| v.as_str())
                .unwrap_or_default()
                .to_owned();
            let thread = if thread.is_empty() {
                state.thread_id.clone()
            } else {
                thread
            };
            if thread.is_empty() {
                return Err((-32602, "thread_id is required".into(), None));
            }
            if prompt.is_empty() {
                return Err((-32602, "input carries no text".into(), None));
            }
            state.thread_id = thread.clone();

            // The turn runs on its own thread so this loop can still read a
            // `turn/cancel` while the answer streams.
            let worker = runner.clone();
            let sink_sender = tx.clone();
            let error_sender = tx.clone();
            let thread_for_run = thread.clone();
            std::thread::spawn(move || {
                let sink = move |event: BridgeEvent| {
                    let _ = sink_sender.send(Outbound::Event {
                        body: event_json(&thread_for_run, &event),
                    });
                };
                if let Err(error) = worker.start_turn(&thread, &prompt, &client_id, &sink) {
                    let _ = error_sender.send(Outbound::Error {
                        id: serde_json::Value::Null,
                        code: -32000,
                        message: error,
                        data: None,
                    });
                }
            });
            Ok(serde_json::json!({}))
        }
        "turn/cancel" => {
            let thread = if thread.is_empty() {
                state.thread_id.clone()
            } else {
                thread
            };
            if thread.is_empty() {
                return Err((-32602, "thread_id is required".into(), None));
            }
            let events = runner.cancel(&thread).map_err(|e| (-32000, e, None))?;
            Ok(serde_json::json!({
                "_events": events.iter().map(|e| event_json(&thread, e)).collect::<Vec<_>>(),
            }))
        }
        "approval/respond" => {
            let request_id = params
                .get("request_id")
                .or_else(|| params.get("requestId"))
                .or_else(|| params.get("approval_id"))
                .and_then(|v| v.as_str())
                .unwrap_or_default()
                .to_owned();
            if request_id.is_empty() {
                return Err((-32602, "request_id is required".into(), None));
            }
            let raw_decision = params
                .get("decision")
                .and_then(|v| v.as_str())
                .unwrap_or("deny");
            let decision = normalise_decision(raw_decision);
            if !matches!(decision, "approve" | "deny" | "guide" | "skip" | "trust") {
                return Err((-32602, format!("unknown decision: {raw_decision}"), None));
            }
            let guidance = params
                .get("guidance")
                .and_then(|v| v.as_str())
                .unwrap_or_default()
                .to_owned();
            let thread = if thread.is_empty() {
                state.thread_id.clone()
            } else {
                thread
            };
            if thread.is_empty() {
                // The real backend binds an approval to its subscribed thread;
                // without one an untrusted page could answer another thread's
                // approval. Refuse instead of guessing.
                return Err((-32602, "thread_id is required".into(), None));
            }
            // Approval resolution also continues work, so it runs off the loop.
            let worker = runner.clone();
            let sink_sender = tx.clone();
            let error_sender = tx.clone();
            let thread_for_run = thread.clone();
            let decision_owned = decision.to_owned();
            std::thread::spawn(move || {
                let sink = move |event: BridgeEvent| {
                    let _ = sink_sender.send(Outbound::Event {
                        body: event_json(&thread_for_run, &event),
                    });
                };
                if let Err(error) =
                    worker.respond(&thread, &request_id, &decision_owned, &guidance, &sink)
                {
                    let _ = error_sender.send(Outbound::Error {
                        id: serde_json::Value::Null,
                        code: -32000,
                        message: error,
                        data: None,
                    });
                }
            });
            Ok(serde_json::json!({}))
        }
        other => Err((-32601, format!("method not found: {other}"), None)),
    }
}

/// Stable id derivation for a queue item the client did not name. Not a hash in
/// any security sense: it exists so a retried create with identical text maps to
/// the same row instead of appending a duplicate.
pub fn app_server_fnv(text: &str) -> u64 {
    let mut hash: u64 = 0xcbf29ce484222325;
    for byte in text.as_bytes() {
        hash ^= *byte as u64;
        hash = hash.wrapping_mul(0x100000001b3);
    }
    hash
}

fn queue_json(item: &QueueView) -> serde_json::Value {
    serde_json::json!({
        "queue_item_id": item.queue_item_id,
        "position": item.position,
        "input": item.input,
        "status": item.status,
    })
}

/// What this adapter can do, so the UI can enable a feature only when the
/// backend really implements it.
fn capabilities() -> serde_json::Value {
    serde_json::json!({
        "protocol": APP_SERVER_PROTOCOL,
        "protocol_version": APP_SERVER_PROTOCOL,
        "core_protocol": PROTOCOL_VERSION,
        "streaming": true,
        "approval": true,
        "thread_snapshot": true,
        "turn_cancel": true,
    })
}

/// `input` is `[{type:"text",text:"..."}]`. Fall back to a bare `text` for
/// hand-written frames, and join multiple text items instead of keeping only
/// the first one, which would silently drop half the prompt.
fn prompt_param(params: &serde_json::Value) -> String {
    if let Some(items) = params.get("input").and_then(|i| i.as_array()) {
        let parts: Vec<String> = items
            .iter()
            .filter_map(|item| {
                let kind = item.get("type").and_then(|t| t.as_str()).unwrap_or("text");
                if kind != "text" {
                    return None;
                }
                item.get("text").and_then(|t| t.as_str()).map(str::to_owned)
            })
            .collect();
        if !parts.is_empty() {
            return parts.join("\n");
        }
    }
    params
        .get("text")
        .and_then(|t| t.as_str())
        .unwrap_or_default()
        .to_owned()
}

fn event_json(thread: &str, event: &BridgeEvent) -> serde_json::Value {
    serde_json::json!({
        "event_id": format!("{thread}:{}", event.seq),
        "protocol_version": APP_SERVER_PROTOCOL,
        "seq": event.seq,
        "thread_id": thread,
        "method": event.method,
        "payload": event.payload,
        "created_at": "",
        "client_message_id": event.client_message_id,
    })
}

/// Used by tests and by hosts that need to shove a raw frame at a socket.
pub fn write_frame(stream: &mut TcpStream, body: &serde_json::Value) -> std::io::Result<()> {
    stream.write_all(body.to_string().as_bytes())
}

/// A blocking reader for one frame, used by the smoke test.
pub fn read_frame(stream: &mut TcpStream, buffer: &mut Vec<u8>) -> std::io::Result<Option<String>> {
    let mut chunk = [0u8; 4096];
    loop {
        if let Some(text) = take_frame(buffer) {
            return Ok(Some(text));
        }
        match stream.read(&mut chunk) {
            Ok(0) => return Ok(None),
            Ok(n) => buffer.extend_from_slice(&chunk[..n]),
            Err(e) => return Err(e),
        }
    }
}

fn take_frame(buffer: &mut Vec<u8>) -> Option<String> {
    // Minimal unmasked-frame reader for server text frames, enough for a smoke
    // test. The real client uses a full WebSocket implementation.
    if buffer.len() < 2 {
        return None;
    }
    let len0 = buffer[1] & 0x7f;
    let (mut offset, mut length) = (2usize, len0 as usize);
    if len0 == 126 {
        if buffer.len() < 4 {
            return None;
        }
        length = u16::from_be_bytes([buffer[2], buffer[3]]) as usize;
        offset = 4;
    } else if len0 == 127 {
        if buffer.len() < 10 {
            return None;
        }
        length = u64::from_be_bytes([
            buffer[2], buffer[3], buffer[4], buffer[5], buffer[6], buffer[7], buffer[8], buffer[9],
        ]) as usize;
        offset = 10;
    }
    if buffer.len() < offset + length {
        return None;
    }
    let body = buffer[offset..offset + length].to_vec();
    buffer.drain(..offset + length);
    String::from_utf8(body).ok()
}

/// Events retained for replay. The store is the real journal; this buffer only
/// serves a reconnect that asks for `lastSeenSeq`, so a lost socket does not
/// lose a turn's output.
#[derive(Default)]
pub struct EventBuffer {
    inner: std::sync::Mutex<std::collections::HashMap<String, Vec<BridgeEvent>>>,
}

impl EventBuffer {
    pub fn push(&self, thread: &str, event: BridgeEvent) {
        self.inner
            .lock()
            .unwrap()
            .entry(thread.to_owned())
            .or_default()
            .push(event);
    }

    pub fn after(&self, thread: &str, seq: u64) -> Vec<BridgeEvent> {
        self.inner
            .lock()
            .unwrap()
            .get(thread)
            .map(|events| events.iter().filter(|e| e.seq > seq).cloned().collect())
            .unwrap_or_default()
    }
}
