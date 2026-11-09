//! The bridge between the webview's IPC transport and the guest's WebSocket protocol.
//!
//! user:"Android 本地服务的访问控制，不能暴露无保护的 Core 操作接口"+(手机上
//! "本机回环"等于"任何别的 App 都能连"，因此 UI 不直连端口：它只发 IPC，宿主
//! 持令牌转发，端口和令牌都不离开这个进程)。
//!
//! ## One socket, one subscription, many page loads
//!
//! The core's app-server is session-scoped: `initialize` is accepted once per socket and
//! carries the `threadId` that socket subscribes to. Everything else — run items, turn
//! events, approval cards — is delivered only to the subscriber of that thread.
//!
//! The app has one window, and a page reload creates a new client against the same guest.
//! Two models were tried and both had a real failure:
//!
//! * **One socket per client handshake.** Correct per connection, but a new socket starts
//!   unsubscribed, and the previous socket is the one whose subscription the core is
//!   still streaming into. The UI then showed a turn running forever with no items.
//! * **Reuse the socket and cache the handshake.** The UI stayed alive, but a reloaded
//!   page got a reply for a subscription it had never asked for.
//!
//! What is here is one socket for the life of the guest, a cached handshake reply for
//! later clients, and — the part both earlier versions missed — `thread/resume` on the
//! socket whenever a client handshakes with a thread. That re-points the one subscription
//! at the thread the newest client is looking at, which is exactly what "open this
//! session" means.

use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use futures_util::{SinkExt, StreamExt};
use serde_json::{json, Value};
use tauri::{AppHandle, Emitter};
use tokio::sync::{mpsc, oneshot};
use tokio_tungstenite::tungstenite::client::IntoClientRequest;
use tokio_tungstenite::tungstenite::Message;

struct Session {
    outbound: mpsc::UnboundedSender<String>,
    pending: Mutex<HashMap<String, oneshot::Sender<Value>>>,
    /// Streams run items in the order the core produced them.
    ordered: Mutex<()>,
    /// Set to false when the socket task ends.
    ///
    /// user:“本地核心挂了之后，手机上所有操作都失败，只能杀掉应用重开”+(pump 退出时只清了
    /// 等待中的请求，`session` 还留着这条死连接；之后每一次调用都往关闭的通道里发。
    /// 这里留一个存活标志，下一次调用据此重建 socket 并重新握手)。
    alive: AtomicBool,
}

impl Session {
    fn new() -> (Arc<Self>, mpsc::UnboundedReceiver<String>) {
        let (outbound, inbound) = mpsc::unbounded_channel();
        (
            Arc::new(Self {
                outbound,
                pending: Mutex::new(HashMap::new()),
                ordered: Mutex::new(()),
                alive: AtomicBool::new(true),
            }),
            inbound,
        )
    }

    fn is_alive(&self) -> bool {
        self.alive.load(Ordering::SeqCst)
    }

    fn fail_pending(&self) {
        self.pending.lock().expect("pending lock").clear();
    }
}

pub struct CoreLink {
    app: AppHandle,
    endpoint: Mutex<(String, String)>,
    session: Mutex<Option<Arc<Session>>>,
    /// The first successful `initialize` reply. Later clients get it back rather than a
    /// second handshake, which the core would refuse on the same socket.
    handshake: Mutex<Option<Value>>,
    next_id: AtomicU64,
}

impl CoreLink {
    pub fn new(app: AppHandle) -> Arc<Self> {
        Arc::new(Self {
            app,
            endpoint: Mutex::new((String::new(), String::new())),
            session: Mutex::new(None),
            handshake: Mutex::new(None),
            next_id: AtomicU64::new(1),
        })
    }

    /// Points the link at a freshly started guest and drops the socket to the old one.
    pub fn retarget(&self, port: u16, token: &str) {
        *self.endpoint.lock().expect("endpoint lock") =
            (format!("ws://127.0.0.1:{port}/api/core/app-server"), token.to_owned());
        self.close_session();
    }

    fn close_session(&self) {
        if let Some(previous) = self.session.lock().expect("session lock").take() {
            previous.fail_pending();
        }
        *self.handshake.lock().expect("handshake lock") = None;
    }

    fn endpoint(&self) -> (String, String) {
        self.endpoint.lock().expect("endpoint lock").clone()
    }

    /// Returns the live session, connecting on first use.
    async fn ensure_session(&self) -> Result<Arc<Session>, String> {
        // Take the clone in its own statement: holding the guard across `close_session`
        // would re-lock the same mutex and deadlock.
        let existing = self.session.lock().expect("session lock").clone();
        if let Some(session) = existing {
            if session.is_alive() {
                return Ok(session);
            }
            // The socket died under us: drop it and its cached handshake, then reconnect.
            // The UI re-initializes on its own, so a fresh socket is enough here.
            self.close_session();
        }
        let (url, token) = self.endpoint();
        if url.is_empty() {
            return Err("the core is not running yet".to_owned());
        }
        let stream = connect(&url, &token).await?;
        let (session, inbound) = Session::new();
        *self.session.lock().expect("session lock") = Some(Arc::clone(&session));
        let app = self.app.clone();
        let driving = Arc::clone(&session);
        tauri::async_runtime::spawn(async move {
            pump(app, driving, stream, inbound).await;
        });
        Ok(session)
    }

    pub async fn call(&self, method: &str, params: Value, timeout: Duration) -> Result<Value, String> {
        if method == "initialize" {
            return self.initialize(params, timeout).await;
        }
        let session = self.ensure_session().await?;
        self.call_on(&session, method, params, timeout).await
    }

    /// Handshake for a client, reusing the socket and moving its subscription.
    async fn initialize(&self, params: Value, timeout: Duration) -> Result<Value, String> {
        let session = self.ensure_session().await?;
        let cached = self.handshake.lock().expect("handshake lock").clone();
        let reply = match cached {
            Some(reply) => reply,
            None => {
                let reply = self.call_on(&session, "initialize", params.clone(), timeout).await?;
                *self.handshake.lock().expect("handshake lock") = Some(reply.clone());
                reply
            }
        };
        // Point the socket's one subscription at the thread this client is opening. A new
        // page load always comes with one; without this the core keeps streaming into a
        // subscription nobody renders, which looks exactly like a frozen turn.
        if let Some(thread) = params.get("threadId").and_then(Value::as_str) {
            if !thread.is_empty() {
                if let Err(error) = self
                    .call_on(&session, "thread/resume", json!({ "thread_id": thread }), timeout)
                    .await
                {
                    println!("[sunday] could not subscribe {thread}: {error}");
                }
            }
        }
        Ok(reply)
    }

    async fn call_on(
        &self,
        session: &Arc<Session>,
        method: &str,
        params: Value,
        timeout: Duration,
    ) -> Result<Value, String> {
        let id = self.next_id.fetch_add(1, Ordering::SeqCst).to_string();
        let (sender, receiver) = oneshot::channel();
        session
            .pending
            .lock()
            .expect("pending lock")
            .insert(id.clone(), sender);
        let frame = json!({ "id": id, "method": method, "params": params });
        if session.outbound.send(frame.to_string()).is_err() {
            return Err("the core connection is closed".to_owned());
        }
        match tokio::time::timeout(timeout, receiver).await {
            Ok(Ok(value)) => Ok(value),
            Ok(Err(_)) => Err("the core connection dropped this request".to_owned()),
            Err(_) => {
                session.pending.lock().expect("pending lock").remove(&id);
                Err(format!("the core did not answer {method} in time"))
            }
        }
    }
}

/// Reads and writes one socket until it closes.
async fn pump(
    app: AppHandle,
    session: Arc<Session>,
    stream: tokio_tungstenite::WebSocketStream<
        tokio_tungstenite::MaybeTlsStream<tokio::net::TcpStream>,
    >,
    mut inbound: mpsc::UnboundedReceiver<String>,
) {
    println!("[sunday] core socket open");
    app.emit("core-event", json!({ "method": "core/connected", "payload": {} }))
        .ok();
    let (mut sink, mut source) = stream.split();
    loop {
        tokio::select! {
            outgoing = inbound.recv() => {
                match outgoing {
                    Some(text) => {
                        if sink.send(Message::Text(text)).await.is_err() {
                            break;
                        }
                    }
                    None => break,
                }
            }
            incoming = source.next() => {
                match incoming {
                    Some(Ok(Message::Text(text))) => dispatch(&app, &session, &text),
                    Some(Ok(Message::Binary(_))) => {}
                    // An unanswered ping is a closed socket on the core side.
                    Some(Ok(Message::Ping(payload))) => {
                        if sink.send(Message::Pong(payload)).await.is_err() {
                            break;
                        }
                    }
                    Some(Ok(Message::Pong(_))) => {}
                    Some(Ok(Message::Close(_))) | Some(Err(_)) | None => break,
                    Some(Ok(Message::Frame(_))) => {}
                }
            }
        }
    }
    session.alive.store(false, Ordering::SeqCst);
    session.fail_pending();
    println!("[sunday] core socket closed");
    app.emit("core-event", json!({ "method": "core/disconnected", "payload": {} }))
        .ok();
}

fn dispatch(app: &AppHandle, session: &Arc<Session>, text: &str) {
    let Ok(value) = serde_json::from_str::<Value>(text) else {
        return;
    };
    if let Some(id) = value.get("id").and_then(Value::as_str) {
        if let Some(sender) = session.pending.lock().expect("pending lock").remove(id) {
            let _ = sender.send(value);
            return;
        }
    }
    if let Some(method) = value.get("method").and_then(Value::as_str) {
        // Which notifications leave the host: a stream that stops here is a forwarding
        // bug, one that stops in the UI is a rendering bug, and a screenshot cannot tell
        // them apart.
        if method.starts_with("core/") || method.starts_with("turn/") {
            println!("[sunday] forward {method}");
        }
        let _guard = session.ordered.lock().expect("order lock");
        app.emit("core-event", value).ok();
    }
}

async fn connect(
    url: &str,
    token: &str,
) -> Result<
    tokio_tungstenite::WebSocketStream<tokio_tungstenite::MaybeTlsStream<tokio::net::TcpStream>>,
    String,
> {
    let mut request = url.into_client_request().map_err(|error| error.to_string())?;
    request.headers_mut().insert(
        "authorization",
        format!("Bearer {token}")
            .parse()
            .map_err(|_| "cannot build the authorization header".to_owned())?,
    );
    let (stream, _) = tokio_tungstenite::connect_async(request)
        .await
        .map_err(|error| error.to_string())?;
    Ok(stream)
}
