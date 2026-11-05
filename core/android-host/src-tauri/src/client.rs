//! The bridge between the webview's IPC transport and the guest's WebSocket protocol.
//!
//! user:"Android 本地服务的访问控制，不能暴露无保护的 Core 操作接口"+(手机上
//! "本机回环"等于"任何别的 App 都能连"，因此 UI 不直连端口：它只发 IPC，宿主
//! 持令牌转发，端口和令牌都不离开这个进程)。
//!
//! The shared UI talks the Core app-server protocol (JSON frames with an `id` for
//! requests and a `method` for notifications). This module is a WebSocket client for
//! that protocol plus a request table, so `core_rpc` can behave like a normal async
//! call from the webview's point of view.

use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use futures_util::{SinkExt, StreamExt};
use serde_json::{json, Value};
use tauri::{AppHandle, Emitter};
use tokio::sync::{mpsc, oneshot};
use tokio_tungstenite::tungstenite::client::IntoClientRequest;
use tokio_tungstenite::tungstenite::Message;

type Pending = Arc<Mutex<HashMap<String, oneshot::Sender<Value>>>>;

/// One connection to the guest, shared by every caller in the app.
///
/// Reconnecting is handled inside the driver task: the UI's transport treats a closed
/// socket as a lost connection and would otherwise need to rebuild its world.
pub struct CoreLink {
    outbound: mpsc::UnboundedSender<String>,
    pending: Pending,
    next_id: AtomicU64,
    app: AppHandle,
    url: Mutex<String>,
    token: Mutex<String>,
}

impl CoreLink {
    pub fn new(app: AppHandle) -> Arc<Self> {
        let (outbound, inbound) = mpsc::unbounded_channel::<String>();
        let link = Arc::new(Self {
            outbound,
            pending: Arc::new(Mutex::new(HashMap::new())),
            next_id: AtomicU64::new(1),
            app,
            url: Mutex::new(String::new()),
            token: Mutex::new(String::new()),
        });
        let driver = Arc::clone(&link);
        tauri::async_runtime::spawn(async move { driver.run(inbound).await });
        link
    }

    /// Points the link at a freshly started guest. A different URL starts a new driver
    /// loop; the old socket is closed because the guest it spoke to is gone.
    pub fn retarget(&self, port: u16, token: &str) {
        *self.url.lock().expect("url lock") = format!("ws://127.0.0.1:{port}/api/core/app-server");
        *self.token.lock().expect("token lock") = token.to_owned();
    }

    fn current(&self) -> (String, String) {
        (
            self.url.lock().expect("url lock").clone(),
            self.token.lock().expect("token lock").clone(),
        )
    }

    /// A JSON-RPC style call that resolves when the matching `id` comes back.
    pub async fn call(&self, method: &str, params: Value, timeout: Duration) -> Result<Value, String> {
        let id = self.next_id.fetch_add(1, Ordering::SeqCst).to_string();
        let (sender, receiver) = oneshot::channel();
        self.pending.lock().expect("pending lock").insert(id.clone(), sender);
        let frame = json!({ "id": id, "method": method, "params": params });
        self.outbound
            .send(frame.to_string())
            .map_err(|_| "the core connection is closed".to_owned())?;
        match tokio::time::timeout(timeout, receiver).await {
            Ok(Ok(value)) => Ok(value),
            Ok(Err(_)) => Err("the core connection dropped this request".to_owned()),
            Err(_) => {
                self.pending.lock().expect("pending lock").remove(&id);
                Err(format!("the core did not answer {method} in time"))
            }
        }
    }

    async fn run(self: Arc<Self>, mut inbound: mpsc::UnboundedReceiver<String>) {
        loop {
            let (url, token) = self.current();
            if url.is_empty() {
                // No guest yet: park until something retargets us.
                tokio::time::sleep(Duration::from_millis(250)).await;
                continue;
            }
            match connect(&url, &token).await {
                Ok(stream) => {
                    self.app
                        .emit("core-event", json!({ "method": "core/connected", "payload": {} }))
                        .ok();
                    self.pump(stream, &mut inbound).await;
                    self.app
                        .emit("core-event", json!({ "method": "core/disconnected", "payload": {} }))
                        .ok();
                }
                Err(error) => {
                    // A guest that is still booting refuses connections; retrying is the
                    // whole point, so this is a log line rather than an error surface.
                    eprintln!("core link: {error}");
                }
            }
            // Fail every waiter: their request died with the socket.
            self.pending.lock().expect("pending lock").clear();
            tokio::time::sleep(Duration::from_millis(700)).await;
        }
    }

    async fn pump(
        &self,
        stream: tokio_tungstenite::WebSocketStream<
            tokio_tungstenite::MaybeTlsStream<tokio::net::TcpStream>,
        >,
        inbound: &mut mpsc::UnboundedReceiver<String>,
    ) {
        let (mut sink, mut source) = stream.split();
        loop {
            tokio::select! {
                outgoing = inbound.recv() => {
                    match outgoing {
                        Some(text) => {
                            if sink.send(Message::Text(text)).await.is_err() {
                                return;
                            }
                        }
                        None => return,
                    }
                }
                incoming = source.next() => {
                    match incoming {
                        Some(Ok(Message::Text(text))) => self.dispatch(&text),
                        Some(Ok(Message::Binary(_))) => {}
                        Some(Ok(Message::Ping(_))) | Some(Ok(Message::Pong(_))) => {}
                        Some(Ok(Message::Close(_))) | Some(Err(_)) | None => return,
                        Some(Ok(Message::Frame(_))) => {}
                    }
                }
            }
        }
    }

    fn dispatch(&self, text: &str) {
        let Ok(value) = serde_json::from_str::<Value>(text) else {
            return;
        };
        if let Some(id) = value.get("id").and_then(Value::as_str) {
            if let Some(sender) = self.pending.lock().expect("pending lock").remove(id) {
                let _ = sender.send(value);
                return;
            }
        }
        // Notifications carry a method and no id; the UI's transport expects exactly
        // this envelope, with the frame itself as `payload`.
        if value.get("method").is_some() {
            self.app.emit("core-event", value).ok();
        }
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
