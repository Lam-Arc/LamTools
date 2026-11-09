//! 远程的 JSON-RPC 转发。
//!
//! user:“连上电脑了之后也没有出现项目”“报错 transport RPC error peer closed stream”+
//! (界面加载项目、会话、工作台快照走的是 Core 的 JSON-RPC，不是 REST；隧道以前只转发了
//! REST 和事件，所有 RPC 都落在「未知方法」上，于是手机连着电脑却是一片空)。
//!
//! One WebSocket to the local Core's app-server, opened once per tunnel connection. The
//! socket is split: one task reads replies and matches them by id, another writes requests.
//! Neither blocks the other, and the event pump keeps its own socket.

use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Arc;
use std::time::Duration;

use anyhow::{bail, Context, Result};
use futures_util::{SinkExt as _, StreamExt as _};
use serde_json::{json, Value};
use tokio::sync::{broadcast, mpsc, oneshot, Mutex};
use tokio_tungstenite::tungstenite::Message;

type Job = (String, Value, oneshot::Sender<Result<Value>>);
type Pending = Arc<Mutex<HashMap<u64, oneshot::Sender<Result<Value>>>>>;

/// A live JSON-RPC bridge to the local Core.
pub struct CoreRpc {
    jobs: mpsc::Sender<Job>,
    /// 这条桥自己那次 `initialize` 的答复。
    ///
    /// user:“我这里显示的是暂无可用模型”+(界面在远程模式下也会发一次 initialize，而
    /// Core 一条连接只允许介绍一次；不留这份答复，界面之后每条 RPC 都会被拒成
    /// 「Already initialized」，模型、权限、插件就永远是空的)。
    initialized: Value,
    /// Core 推到这条连接上的通知。
    ///
    /// user:“显示和电脑断联了”“请立即回复你好没反应”+(Core 只把会话的流式事件推给
    /// 「订阅了这个会话」的连接；另开一条没订阅的 socket 永远收不到 item/delta，手机上
    /// 于是发得出去、看不见回复。请求和事件共用这条订阅过的连接，事件从这里转发出去)。
    events: broadcast::Sender<Value>,
    /// 这条桥的 Core socket 是否已经断开。
    ///
    /// user:“电脑那边一重启，手机上就全是错，只能重新配对”+(Core 换端口重启时这条
    /// WebSocket 会断，reader 退出、jobs 通道关闭；调用方如果不知道桥已经死了，就会一直
    /// 往一个空通道里投任务。这里留一个标志，让上层能重建而不是永久报错)。
    dead: Arc<AtomicBool>,
}

impl CoreRpc {
    /// Connects to `ws://127.0.0.1:{port}/app-server` and completes the handshake.
    pub async fn connect(port: u16, token: &str) -> Result<Self> {
        use tokio_tungstenite::tungstenite::client::IntoClientRequest;

        let url = format!("ws://127.0.0.1:{port}/api/core/app-server");
        let mut request = url.as_str().into_client_request().context("RPC 通道地址不合法")?;
        if !token.is_empty() {
            request.headers_mut().insert(
                "authorization",
                format!("Bearer {token}")
                    .parse()
                    .map_err(|_| anyhow::anyhow!("invalid bearer token"))?,
            );
        }
        let (mut socket, _) = tokio_tungstenite::connect_async(request)
            .await
            .context("无法连接到本机 Core 的 RPC 通道")?;

        // The Core pushes nothing to a client that has not introduced itself.
        socket
            .send(Message::Text(
                json!({
                    "jsonrpc": "2.0",
                    "id": 0,
                    "method": "initialize",
                    "params": { "clientInfo": { "name": "sunday-p2p", "version": "0.1.0" } },
                })
                .to_string()
                .into(),
            ))
            .await
            .context("cannot send the initialize frame")?;

        // 先收下这次握手的答复，再开始转发。
        let initialized = loop {
            let message = socket
                .next()
                .await
                .context("Core 在握手期间关闭了 RPC 通道")?
                .context("握手时读取 Core 的答复失败")?;
            let text = match message {
                Message::Text(text) => text.to_string(),
                Message::Binary(bytes) => String::from_utf8_lossy(&bytes).to_string(),
                Message::Ping(_) | Message::Pong(_) | Message::Frame(_) => continue,
                Message::Close(_) => bail!("Core 在握手时关闭了 RPC 通道"),
            };
            let Ok(value) = serde_json::from_str::<Value>(&text) else { continue };
            if value.get("id").and_then(Value::as_u64) != Some(0) {
                // 握手期间的推送不关这次答复的事。
                continue;
            }
            if let Some(error) = value.get("error") {
                let message = error
                    .get("message")
                    .and_then(Value::as_str)
                    .unwrap_or("Core 拒绝了 initialize");
                bail!("{message}");
            }
            break value.get("result").cloned().unwrap_or(Value::Null);
        };

        let (events, _) = broadcast::channel::<Value>(4096);
        let events_for_reader = events.clone();
        let dead = Arc::new(AtomicBool::new(false));
        let dead_for_reader = Arc::clone(&dead);
        let (mut sink, mut stream) = socket.split();
        let pending: Pending = Arc::new(Mutex::new(HashMap::new()));
        let (jobs, mut inbox) = mpsc::channel::<Job>(64);

        // One reader for the whole bridge: replies go to their caller; notifications are
        // already handled by the event pump on its own socket.
        let reader_pending = Arc::clone(&pending);
        tokio::spawn(async move {
            while let Some(message) = stream.next().await {
                let Ok(message) = message else { break };
                let text = match message {
                    Message::Text(text) => text.to_string(),
                    Message::Binary(bytes) => String::from_utf8_lossy(&bytes).to_string(),
                    Message::Ping(_) | Message::Pong(_) | Message::Frame(_) => continue,
                    Message::Close(_) => break,
                };
                let Ok(value) = serde_json::from_str::<Value>(&text) else { continue };
                let Some(id) = value.get("id").and_then(|id| id.as_u64()) else {
                    // 没有 id 的是推送（item/delta、状态变化）：交给事件转发，不在这里丢。
                    if value.get("method").is_some() {
                        let _ = events_for_reader.send(value);
                    }
                    continue;
                };
                let Some(sender) = reader_pending.lock().await.remove(&id) else { continue };
                if let Some(error) = value.get("error") {
                    let message = error
                        .get("message")
                        .and_then(|text| text.as_str())
                        .unwrap_or("Core 返回了一个错误")
                        .to_owned();
                    let _ = sender.send(Err(anyhow::anyhow!("{message}")));
                    continue;
                }
                let _ = sender.send(Ok(value.get("result").cloned().unwrap_or(Value::Null)));
            }
            // The socket died: fail everything still waiting instead of hanging forever,
            // and tell the owner so the next call can rebuild the bridge.
            dead_for_reader.store(true, Ordering::SeqCst);
            for (_, sender) in reader_pending.lock().await.drain() {
                let _ = sender.send(Err(anyhow::anyhow!("与 Core 的 RPC 通道已断开")));
            }
        });

        let writer_pending = Arc::clone(&pending);
        tokio::spawn(async move {
            while let Some((method, params, answer)) = inbox.recv().await {
                let id = next_id();
                writer_pending.lock().await.insert(id, answer);
                let frame = json!({
                    "jsonrpc": "2.0",
                    "id": id,
                    "method": method,
                    "params": params,
                })
                .to_string();
                if sink.send(Message::Text(frame.into())).await.is_err() {
                    if let Some(sender) = writer_pending.lock().await.remove(&id) {
                        let _ = sender.send(Err(anyhow::anyhow!("向 Core 发送 RPC 失败")));
                    }
                    break;
                }
            }
        });

        Ok(Self { jobs, initialized, events, dead })
    }

    /// Core 那边的 socket 是否已经断开（需要重建）。
    pub fn is_dead(&self) -> bool {
        self.dead.load(Ordering::SeqCst)
    }

    /// 这条 Core 连接上的推送流。界面订阅的会话一经 `thread/resume` 生效，进度就来了。
    pub fn subscribe_events(&self) -> broadcast::Receiver<Value> {
        self.events.subscribe()
    }

    /// 远程界面的 `initialize` 该得到的答复。
    ///
    /// 界面每次连接、每次重载都会发一次；桥把它换成同一条 Core 连接上的那次握手结果，
    /// 既满足协议，也不会让 Core 因为“第二次介绍”而拒绝后续所有调用。
    pub fn initialize_result(&self) -> Value {
        self.initialized.clone()
    }

    /// One JSON-RPC call, answered by the Core on the shared socket.
    pub async fn call(&self, method: &str, params: Value) -> Result<Value> {
        let (answer, waiter) = oneshot::channel();
        self.jobs
            .send((method.to_owned(), params, answer))
            .await
            .context("RPC 通道已关闭")?;
        match tokio::time::timeout(Duration::from_secs(120), waiter).await {
            Ok(Ok(result)) => result,
            Ok(Err(_)) => bail!("Core 没有回答这条 RPC"),
            Err(_) => bail!("等待 Core 回答超时"),
        }
    }
}

/// Ids only have to be unique per socket; a monotonic value also keeps logs readable.
fn next_id() -> u64 {
    static COUNTER: AtomicU64 = AtomicU64::new(1);
    COUNTER.fetch_add(1, Ordering::SeqCst)
}
