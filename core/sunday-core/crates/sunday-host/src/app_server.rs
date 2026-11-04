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
use std::sync::{Arc, Mutex};
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
    /// Refuses an approval the runner cannot honour, before the caller reports
    /// success.
    ///
    /// Without this gate a resolved or expired request still answered `{}`, the
    /// screen marked the card as submitted, and the real failure only surfaced as
    /// an orphan event nobody was waiting for. The user saw a spinner that never
    /// ended and a tool that never ran.
    fn check_approval(&self, _request_id: &str) -> Result<(), String> {
        Ok(())
    }

    /// Closes approvals whose deadline passed, returning the ids that closed.
    ///
    /// A conversation whose approval aged out used to stay unusable: its card kept
    /// two live buttons, the composer stayed taken over by a decision nobody could
    /// answer, and no new turn could start. Reporting the closure lets the caller
    /// tell the screen that the card is dead.
    fn settled_approvals(
        &self,
        _thread_id: &str,
        _now_epoch: u64,
    ) -> Result<Vec<(String, String)>, String> {
        Ok(Vec::new())
    }

    /// Whether the thread still waits on a human decision.
    fn has_pending_approval(&self, _thread_id: &str) -> Result<bool, String> {
        Ok(false)
    }

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

    /// The slash commands this core offers.
    ///
    /// Returning an empty list is honest only when the core truly has none. The
    /// workbench renders whatever comes back, so a core that supports commands
    /// must list them or the palette will look empty for no stated reason.
    fn command_catalog(&self) -> Vec<serde_json::Value> {
        Vec::new()
    }

    /// Expands a command into the prompt a turn will run.
    ///
    /// Refusing with a reason is required: expanding to an empty string would
    /// start a turn with no instruction and report success.
    fn expand_command(&self, name: &str, _arguments: &str) -> Result<String, String> {
        Err(format!("unknown command: {name}"))
    }

    /// What the journal says about work that was interrupted.
    ///
    /// Read through the runner because the runner owns the store: a second
    /// connection opened to answer a lifecycle question would be the same
    /// two-writers mistake the single-writer lock exists to prevent.
    ///
    /// The default refuses rather than answering "nothing was interrupted". A stub
    /// that returns an empty plan tells the user their work is fine when nobody
    /// looked, which is the one wrong answer that loses data silently.
    fn recovery(&self) -> Result<sunday_store::RecoveryPlan, String> {
        Err(NOT_IMPLEMENTED.to_owned())
    }

    /// Threads with a turn currently running.
    ///
    /// Not part of the wire protocol. A host needs it for lifecycle decisions
    /// such as "the app went to the background, so note what was mid-flight".
    fn running_threads(&self) -> Vec<String> {
        Vec::new()
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
    /// Required on every connection. `None` is only for a transport that is not
    /// reachable from outside this process: tests, and Tauri IPC.
    token: Option<String>,
}

impl AppServer {
    /// Binds without authentication.
    ///
    /// Only for tests and for a transport that is unreachable from outside this
    /// process. A host serving a socket must use
    /// [`AppServer::bind_authenticated`]: a random loopback port is not access
    /// control, because any process on the device can enumerate listeners, and on
    /// Android any app can dial another app's loopback socket.
    pub fn bind(addr: &str, runner: Arc<dyn TurnRunner>) -> std::io::Result<Self> {
        let listener = TcpListener::bind(addr)?;
        Ok(Self {
            listener,
            runner,
            token: None,
        })
    }

    /// Binds and requires a token on every connection.
    pub fn bind_authenticated(
        addr: &str,
        runner: Arc<dyn TurnRunner>,
        token: impl Into<String>,
    ) -> std::io::Result<Self> {
        let listener = TcpListener::bind(addr)?;
        Ok(Self {
            listener,
            runner,
            token: Some(token.into()),
        })
    }

    pub fn local_addr(&self) -> std::io::Result<std::net::SocketAddr> {
        self.listener.local_addr()
    }

    /// Serves connections until the listener closes. One thread per client: the
    /// workbench opens a dedicated socket per window.
    pub fn serve(self) {
        let runner = self.runner.clone();
        let token = self.token.clone().map(Arc::new);
        for stream in self.listener.incoming() {
            let Ok(stream) = stream else { break };
            let runner = runner.clone();
            let token = token.clone();
            std::thread::spawn(move || {
                let _ = handle_client(stream, runner, token);
            });
        }
    }
}

/// Where dispatch sends things that are not the RPC reply.
///
/// This exists so the same dispatch serves both transports. A WebSocket writes
/// frames to its socket; Tauri IPC emits to the webview. Without it, a second
/// transport would need a second copy of every method, which is how the CLI and
/// Android runners drifted apart in the first place.
/// The socket transport's sink: hands frames to the thread that owns the socket.
impl FrameSink for Sender<Outbound> {
    fn event(&self, body: serde_json::Value) {
        let _ = self.send(Outbound::Event { body });
    }
    fn orphan_error(&self, code: i32, message: String) {
        let _ = self.send(Outbound::Error {
            id: serde_json::Value::Null,
            code,
            message,
            data: None,
        });
    }
}

pub trait FrameSink: Send + Sync {
    /// One `CoreAppEvent` envelope, already JSON-shaped.
    fn event(&self, body: serde_json::Value);
    /// An error that has no request id because it came from a worker thread.
    fn orphan_error(&self, code: i32, message: String);
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
    /// Cleared until a correct token arrives. Everything except `initialize` is
    /// refused while this is false.
    authenticated: bool,
}

fn handle_client(
    stream: TcpStream,
    runner: Arc<dyn TurnRunner>,
    token: Option<Arc<String>>,
) -> std::io::Result<()> {
    stream.set_nodelay(true)?;
    stream.set_read_timeout(Some(READ_TICK))?;
    let mut socket = accept(stream).map_err(std::io::Error::other)?;
    let mut state = State {
        thread_id: String::new(),
        initialized: false,
        // A transport with no token configured is trusted by construction: it is
        // either a test or IPC that never touches a socket.
        authenticated: token.is_none(),
    };
    let (tx, rx): (Sender<Outbound>, Receiver<Outbound>) = std::sync::mpsc::channel();
    let sink: Arc<dyn FrameSink> = Arc::new(tx.clone());

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

        let expected = token.as_ref().map(|value| value.as_str());
        match dispatch(
            &method,
            &params,
            &mut state,
            runner.clone(),
            &sink,
            expected,
        ) {
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
    "command.catalog",
    "command.execute",
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
    tx: &Arc<dyn FrameSink>,
    expected_token: Option<&str>,
) -> Reply {
    // The authentication gate. Everything except `initialize` is refused until a
    // correct token has been presented, and `initialize` itself refuses a wrong
    // one. Putting the check here, rather than at the socket, means a new method
    // cannot be added without inheriting it.
    if let Some(expected) = expected_token {
        if !state.authenticated {
            if method != "initialize" {
                return Err((-32001, "not authenticated".into(), None));
            }
            let presented = params
                .get("auth")
                .and_then(|value| value.as_str())
                .unwrap_or_default();
            if !crate::token::matches(expected, presented) {
                return Err((-32001, "invalid credentials".into(), None));
            }
            state.authenticated = true;
        }
    }

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
            // Close anything that aged out before replaying the thread, so a dead
            // card cannot keep the composer taken over for another session.
            let settled = runner
                .settled_approvals(&thread, crate::runner::now_epoch())
                .unwrap_or_default();
            let mut events = runner.open_thread(&thread).map_err(|e| (-32000, e, None))?;
            // Recovery: close every turn that opened and never closed.
            //
            // Older runs recorded an approval decision without ending its turn, and
            // nothing else ever closed it, so the replayed transcript carried turns
            // that read "running" forever — the composer offered Stop on a
            // conversation with nothing left to do. Closing only the newest turn was
            // not enough: a thread accumulates several.
            //
            // This is skipped entirely while something is still pending, because a
            // genuine wait must keep its card answerable.
            let still_waiting = runner.has_pending_approval(&thread).unwrap_or(true);
            if !still_waiting {
                let mut opened: Vec<String> = Vec::new();
                let mut closed: Vec<String> = Vec::new();
                for event in &events {
                    let turn = event
                        .payload
                        .get("turn_id")
                        .and_then(|value| value.as_str())
                        .unwrap_or_default()
                        .to_owned();
                    if turn.is_empty() {
                        continue;
                    }
                    match event.method.as_str() {
                        "turn/started" => opened.push(turn),
                        "turn/completed" | "turn/cancelled" => closed.push(turn),
                        _ => {}
                    }
                }
                for turn in opened {
                    if closed.contains(&turn) {
                        continue;
                    }
                    events.push(BridgeEvent {
                        method: "turn/completed".into(),
                        seq: 0,
                        client_message_id: None,
                        payload: serde_json::json!({
                            "text": "",
                            "recovered": true,
                            // Names the turn this closes, so the client updates that
                            // turn rather than inventing another.
                            "turn_id": turn,
                        }),
                    });
                }
            }
            for (approval_id, status) in settled {
                events.push(BridgeEvent {
                    // Derived from the approval id, so a second resume reports the
                    // same closure once and the client's seen-set drops the repeat.
                    method: "item/approval_resolved".into(),
                    seq: 0,
                    client_message_id: None,
                    payload: serde_json::json!({
                        "approval_id": approval_id,
                        "request_id": approval_id,
                        // Settling an aged-out card is not resuming its turn. Naming
                        // the finished turn here made the client revive it.
                        "turn_id": "",
                        // The status the row actually carries, so a denied or
                        // approved card is reported as what it was, not as expired.
                        "decision": status,
                        // `applyDecisionLifecycle` closes a card on `ending`; any
                        // other word leaves it open, which is the bug this line
                        // exists to avoid.
                        "state": "ending",
                    }),
                });
            }
            let history: Vec<serde_json::Value> =
                events.iter().map(|e| event_json(&thread, e)).collect();
            // The client rebuilds a conversation from `snapshot` plus `events`: it
            // hydrates the snapshot and then replays everything the snapshot does not
            // cover. Shipping only `_events` — which `Session::handle` strips before
            // the reply leaves the host — left a resumed session with no state at all,
            // so the thread rendered empty and every live event that followed was
            // dropped for want of a state to apply it to.
            //
            // `snapshot_seq` is deliberately 0: any higher value tells the client to
            // skip exactly the events this same reply is delivering, and the
            // conversation would come back blank again.
            Ok(serde_json::json!({
                "thread_id": thread,
                "snapshot": {
                    "thread_id": thread,
                    "snapshot_seq": 0,
                    "revision": 0,
                    "status": "idle",
                    "turns": {},
                    "items": {},
                    "item_order": [],
                    "requests": {},
                    "artifacts": {},
                    "queue": [],
                    "seen_event_ids": [],
                },
                "events": history.clone(),
                "_events": history,
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
            let page_events: Vec<serde_json::Value> =
                page.events.iter().map(|e| event_json(&thread, e)).collect();
            Ok(serde_json::json!({
                "thread_id": thread,
                "events": page_events.clone(),
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
                "_events": page_events,
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
        // The slash-command surface. The workbench calls `command.catalog` to
        // fill the palette and `command.execute` to run one, so a MODULE_NOT_FOUND
        // here made the palette fail rather than show an empty list.
        "command.catalog" => {
            let commands = runner.command_catalog();
            Ok(serde_json::json!({ "commands": commands }))
        }
        "command.execute" => {
            let thread = if thread.is_empty() {
                state.thread_id.clone()
            } else {
                thread
            };
            if thread.is_empty() {
                return Err((-32602, "thread_id is required".into(), None));
            }
            state.thread_id = thread.clone();
            let name = params
                .get("command")
                .and_then(|value| value.as_str())
                .unwrap_or_default()
                .to_owned();
            let arguments = params
                .get("arguments")
                .and_then(|value| value.as_str())
                .unwrap_or_default()
                .to_owned();
            if name.is_empty() {
                return Err((-32602, "command is required".into(), None));
            }
            // A command either expands to a prompt or is refused with a reason.
            // Silently doing nothing would look like a successful run to the UI.
            let expanded = runner
                .expand_command(&name, &arguments)
                .map_err(|e| (-32602, e, None))?;
            let client_id = params
                .get("client_message_id")
                .and_then(|value| value.as_str())
                .unwrap_or_default()
                .to_owned();
            let worker = runner.clone();
            let sink_sender = Arc::clone(tx);
            let error_sender = Arc::clone(tx);
            let thread_for_run = thread.clone();
            let prompt = expanded.clone();
            std::thread::spawn(move || {
                let sink = move |event: BridgeEvent| {
                    sink_sender.event(event_json(&thread_for_run, &event));
                };
                // A command runs as an ordinary turn: it gets the same journal,
                // approvals and cancellation as anything else.
                if let Err(error) = worker.start_turn(&thread, &prompt, &client_id, &sink) {
                    error_sender.orphan_error(-32000, error);
                }
            });
            Ok(serde_json::json!({ "expanded": expanded }))
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
            let sink_sender = Arc::clone(tx);
            let error_sender = Arc::clone(tx);
            let thread_for_run = thread.clone();
            std::thread::spawn(move || {
                let sink = move |event: BridgeEvent| {
                    sink_sender.event(event_json(&thread_for_run, &event));
                };
                if let Err(error) = worker.stop_turn(&thread, mode, &sink) {
                    error_sender.orphan_error(-32000, error);
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
            let sink_sender = Arc::clone(tx);
            let error_sender = Arc::clone(tx);
            let thread_for_run = thread.clone();
            std::thread::spawn(move || {
                let sink = move |event: BridgeEvent| {
                    sink_sender.event(event_json(&thread_for_run, &event));
                };
                if let Err(error) = worker.start_turn(&thread, &prompt, &client_id, &sink) {
                    error_sender.orphan_error(-32000, error);
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
            // Print before any validation: "the button did nothing" and "the request
            // was refused" look identical from the screen, and the difference decides
            // which layer to fix.
            #[cfg(debug_assertions)]
            println!(
                "approval/respond entry params={}",
                params.to_string().chars().take(240).collect::<String>()
            );
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
            let sink_sender = Arc::clone(tx);
            let error_sender = Arc::clone(tx);
            let thread_for_run = thread.clone();
            // Answer the truth synchronously: an approval that can no longer be
            // honoured must fail here, where the RPC reply still reaches the screen.
            if let Err(reason) = runner.check_approval(&request_id) {
                return Err((-32000, reason, None));
            }
            let decision_owned = decision.to_owned();
            // Debug-only: an approval that never resumes the agent looks identical
            // from the screen whether the call never arrived, was refused, or failed
            // inside the runner. One line at the entry and one at the failure makes
            // the difference visible without a debugger.
            #[cfg(debug_assertions)]
            println!(
                "approval/respond request_id={request_id} decision={decision_owned} thread={thread} guidance_len={}",
                guidance.len()
            );
            std::thread::spawn(move || {
                let sink = move |event: BridgeEvent| {
                    sink_sender.event(event_json(&thread_for_run, &event));
                };
                if let Err(error) =
                    worker.respond(&thread, &request_id, &decision_owned, &guidance, &sink)
                {
                    #[cfg(debug_assertions)]
                    println!("approval/respond failed request_id={request_id} error={error}");
                    error_sender.orphan_error(-32000, error);
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

/// One client conversation, decoupled from any transport.
///
/// Tauri IPC uses this: the webview calls a command, the command hands the
/// method and params here, and the result goes straight back. No socket is opened,
/// so nothing outside the app process can reach it — which is a stronger
/// guarantee than a token on a listening port.
///
/// The WebSocket transport uses the same `dispatch` through `handle`, so the two
/// cannot answer differently.
pub struct Session {
    state: Mutex<State>,
    runner: Arc<dyn TurnRunner>,
    token: Option<String>,
}

impl Session {
    /// A session for a transport that is unreachable from outside this process.
    pub fn trusted(runner: Arc<dyn TurnRunner>) -> Self {
        Self {
            state: Mutex::new(State {
                thread_id: String::new(),
                initialized: false,
                authenticated: true,
            }),
            runner,
            token: None,
        }
    }

    /// A session that requires the token on `initialize`.
    pub fn authenticated(runner: Arc<dyn TurnRunner>, token: impl Into<String>) -> Self {
        Self {
            state: Mutex::new(State {
                thread_id: String::new(),
                initialized: false,
                authenticated: false,
            }),
            runner,
            token: Some(token.into()),
        }
    }

    /// Handles one request. Events produced by a turn are delivered to `sink`.
    ///
    /// Returns the frame the caller should answer with: either a result or an
    /// error code and message. Deliberately not a `Result`, because a JSON-RPC
    /// error is a valid reply, not a Rust failure.
    pub fn handle(
        &self,
        method: &str,
        params: &serde_json::Value,
        sink: Arc<dyn FrameSink>,
    ) -> Reply {
        let mut state = self.state.lock().unwrap();
        let expected = self.token.as_deref();
        let reply = dispatch(
            method,
            params,
            &mut state,
            Arc::clone(&self.runner),
            &sink,
            expected,
        )?;
        // `_events` is transport scaffolding; the caller gets the rest.
        let mut result = reply;
        if let Some(object) = result.as_object_mut() {
            object.remove("_events");
        }
        Ok(result)
    }

    /// Which thread this session last worked on. Used by a host that needs to
    /// resume after being backgrounded.
    pub fn thread_id(&self) -> String {
        self.state.lock().unwrap().thread_id.clone()
    }
}
