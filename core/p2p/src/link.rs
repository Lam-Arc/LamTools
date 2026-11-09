//! The tunnel: frames over one encrypted QUIC stream pair.
//!
//! user:“远程能力：手机可以连接电脑上的 Sunday，访问会话、发送消息……优先复用现有
//! Core API，不重新实现业务逻辑”+(这一层搬的就是 Core 本来就在说的 JSON-RPC 帧：
//! 同一个 method、同一份 params，到了对面直接交给同一个 Python Core)。
//!
//! user:“网络切换后尽可能恢复连接及会话状态”+(读帧必须一直在跑：应答按 id 回给调用方，
//! 事件直接交给订阅者。否则界面发得出消息却看不到回复)。
//!
//! Framing is a 4-byte big-endian length followed by UTF-8 JSON: trivial to read from any
//! side, and impossible to desync because the length is authoritative.

use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Arc;
use std::time::Duration;

use anyhow::{bail, Context, Result};
use futures_util::stream::{FuturesUnordered, StreamExt as _};
use iroh::{Endpoint, EndpointAddr};
use serde::{Deserialize, Serialize};
use tokio::sync::{broadcast, oneshot, Mutex};

use crate::ticket::decode_ticket;
use crate::trust::TrustStore;

/// One framed message on the wire.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum Frame {
    /// First frame from the dialer.
    Hello { name: String },
    /// Answer to a hello.
    ///
    /// `name` is what the peer calls itself, so the device list shows "我的电脑" instead of
    /// a truncated node id. `#[serde(default)]` keeps a new dialer talking to an older
    /// server whose welcome had no name.
    Welcome {
        id: String,
        #[serde(default)]
        name: String,
        trusted: bool,
    },
    /// A Core-style call.
    Call { id: u64, method: String, params: serde_json::Value },
    /// Its answer.
    Reply { id: u64, result: serde_json::Value },
    /// A failed call.
    Error { id: u64, message: String },
    /// An event the remote side should see as it happens.
    Event { method: String, params: serde_json::Value },
    Ping,
    Pong,
}

/// An event pushed by the far side.
#[derive(Debug, Clone)]
pub struct Event {
    pub method: String,
    pub params: serde_json::Value,
}

/// A single frame has to carry a whole Core reply, and a thread snapshot on a long
/// conversation is tens of megabytes (the UI avoids asking for one, but `thread/resume`
/// and approval snapshots still can). 16 MB used to turn those into a closed tunnel;
/// this bound still refuses a hostile length while leaving room for a real reply.
const MAX_FRAME_BYTES: usize = 64 * 1024 * 1024;
const EVENT_BUFFER: usize = 256;

/// 客户端多久发一次心跳。
const PING_EVERY: Duration = Duration::from_secs(12);
/// 多久没收到 Pong 就认为这条连接已经没了。
const PING_DEAD_AFTER_MILLIS: u64 = 26_000;
/// 服务端多久没收到任何帧就收掉连接。
///
/// user:“显示和电脑断联了”+(网络静默断开时 QUIC 既不报错也不关闭，读帧会一直挂着；
/// 客户端每 12 秒发一次 Ping，服务端两分钟看不到帧就把这条连接关掉，两端都能重连，
/// 而不是一直显示「已连接」)。
const IDLE_TIMEOUT: Duration = Duration::from_secs(120);

fn now_millis() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|elapsed| elapsed.as_millis() as u64)
        .unwrap_or(0)
}

async fn write_frame(send: &mut iroh::endpoint::SendStream, frame: &Frame) -> Result<()> {
    let bytes = serde_json::to_vec(frame).context("cannot encode a frame")?;
    if bytes.len() > MAX_FRAME_BYTES {
        bail!("一帧超过 {} 字节", MAX_FRAME_BYTES);
    }
    send.write_all(&(bytes.len() as u32).to_be_bytes())
        .await
        .context("cannot write a frame header")?;
    send.write_all(&bytes).await.context("cannot write a frame")?;
    Ok(())
}

async fn read_frame(recv: &mut iroh::endpoint::RecvStream) -> Result<Frame> {
    let mut header = [0u8; 4];
    recv.read_exact(&mut header)
        .await
        .context("peer closed the stream")?;
    let length = u32::from_be_bytes(header) as usize;
    if length == 0 || length > MAX_FRAME_BYTES {
        bail!("对端给了一个不合法的帧长度 {length}");
    }
    let mut buffer = vec![0u8; length];
    recv.read_exact(&mut buffer)
        .await
        .context("cannot read a frame")?;
    serde_json::from_slice(&buffer).context("cannot parse a frame")
}

/// The dialing side.
pub struct Client {
    conn: iroh::endpoint::Connection,
    send: Arc<Mutex<iroh::endpoint::SendStream>>,
    pending: Arc<Mutex<HashMap<u64, oneshot::Sender<Result<serde_json::Value, String>>>>>,
    events: broadcast::Sender<Event>,
    /// 请求 id 用原子计数，`call` 就能拿 `&self`：多条请求可以同时在路上，不必互相排队。
    next_id: AtomicU64,
    /// 读帧的任务还在跑就说明隧道还活着。断了之后界面必须知道，否则会一直显示
    /// 「已连接」，而每一次操作都拿到一个看不懂的英文错误。
    alive: Arc<AtomicBool>,
    /// 最近一次收到 Pong 的时间，心跳任务据此判死。
    /// 对端的显示名，来自握手；老服务端没有这个名字时是空串。
    pub peer_name: String,
    pub peer: String,
}

impl Client {
    /// Dials a ticket and completes the hello/welcome exchange.
    ///
    /// `name` is what the peer shows the user; it is not an identity, the key is.
    pub async fn dial(endpoint: &Endpoint, ticket: &str, name: &str) -> Result<Self> {
        let addr: EndpointAddr = decode_ticket(ticket)?;
        let conn = endpoint
            .connect(addr, crate::ALPN)
            .await
            .context("无法连接到对端（可能需要对方在线，或走中继）")?;
        let (mut send, mut recv) = conn.open_bi().await.context("cannot open the tunnel")?;
        write_frame(
            &mut send,
            &Frame::Hello {
                name: name.to_owned(),
            },
        )
        .await?;
        let welcome = read_frame(&mut recv).await?;
        let (peer, peer_name) = match welcome {
            Frame::Welcome { id, name, trusted } => {
                if !trusted {
                    bail!("对端没有接受这台设备：可能已被撤销授权，请在电脑的「设备连接」页确认后重试");
                }
                (id, name)
            }
            other => bail!("对端先说了别的话：{other:?}"),
        };

        let send = Arc::new(Mutex::new(send));
        let pending: Arc<Mutex<HashMap<u64, oneshot::Sender<Result<serde_json::Value, String>>>>> =
            Arc::new(Mutex::new(HashMap::new()));
        let (event_tx, _) = broadcast::channel(EVENT_BUFFER);
        let alive = Arc::new(AtomicBool::new(true));
        let last_pong = Arc::new(AtomicU64::new(now_millis()));

        // One reader for the whole connection: replies go to their caller, events go to
        // subscribers, and a closed stream fails every waiting call instead of hanging.
        let reader_pending = Arc::clone(&pending);
        let reader_events = event_tx.clone();
        let reader_conn = conn.clone();
        let reader_alive = Arc::clone(&alive);
        let reader_pong = Arc::clone(&last_pong);
        tauri_free_spawn(async move {
            loop {
                match read_frame(&mut recv).await {
                    Ok(Frame::Reply { id, result }) => {
                        if let Some(sender) = reader_pending.lock().await.remove(&id) {
                            let _ = sender.send(Ok(result));
                        }
                    }
                    Ok(Frame::Error { id, message }) => {
                        if let Some(sender) = reader_pending.lock().await.remove(&id) {
                            let _ = sender.send(Err(message));
                        }
                    }
                    Ok(Frame::Event { method, params }) => {
                        let _ = reader_events.send(Event { method, params });
                    }
                    Ok(Frame::Pong) => {
                        reader_pong.store(now_millis(), Ordering::SeqCst);
                    }
                    Ok(_) => {}
                    Err(error) => {
                        reader_alive.store(false, Ordering::SeqCst);
                        for (_, sender) in reader_pending.lock().await.drain() {
                            let _ = sender.send(Err(error.to_string()));
                        }
                        reader_conn.close(0u32.into(), b"closed");
                        return;
                    }
                }
            }
        });

        // 心跳：一条已经静默断掉的连接既不报错也不会自己关闭，只能靠对端回 Pong 证明它还在。
        // user:“显示和电脑断联了”+(没有这条，下一次操作要等 180 秒超时才发现对方已经没了)。
        let ping_send = Arc::clone(&send);
        let ping_alive = Arc::clone(&alive);
        let ping_pong = Arc::clone(&last_pong);
        let ping_conn = conn.clone();
        tauri_free_spawn(async move {
            loop {
                tokio::time::sleep(PING_EVERY).await;
                if !ping_alive.load(Ordering::SeqCst) {
                    return;
                }
                let last = ping_pong.load(Ordering::SeqCst);
                if now_millis().saturating_sub(last) > PING_DEAD_AFTER_MILLIS {
                    ping_alive.store(false, Ordering::SeqCst);
                    ping_conn.close(0u32.into(), b"heartbeat lost");
                    return;
                }
                let mut send = ping_send.lock().await;
                if write_frame(&mut send, &Frame::Ping).await.is_err() {
                    ping_alive.store(false, Ordering::SeqCst);
                    ping_conn.close(0u32.into(), b"heartbeat write failed");
                    return;
                }
            }
        });

        Ok(Self {
            conn,
            send,
            pending,
            events: event_tx,
            next_id: AtomicU64::new(1),
            alive,
            peer_name,
            peer,
        })
    }

    /// 隧道是否还活着。
    pub fn is_alive(&self) -> bool {
        self.alive.load(Ordering::SeqCst)
    }

    /// 存活标志本身，给宿主做「断了就告诉界面」的监听。
    pub fn alive_flag(&self) -> Arc<AtomicBool> {
        Arc::clone(&self.alive)
    }

    /// One Core-style call. Matched by id, so a slow answer cannot be taken for the next one.
    ///
    /// `&self`：界面的项目、模型、会话是并发加载的，它们不该因为对方回答慢就互相排队。
    pub async fn call(&self, method: &str, params: serde_json::Value) -> Result<serde_json::Value> {
        let id = self.next_id.fetch_add(1, Ordering::SeqCst);
        let (tx, rx) = oneshot::channel();
        self.pending.lock().await.insert(id, tx);
        {
            let mut send = self.send.lock().await;
            write_frame(
                &mut send,
                &Frame::Call {
                    id,
                    method: method.to_owned(),
                    params,
                },
            )
            .await?;
        }
        match tokio::time::timeout(Duration::from_secs(180), rx).await {
            Ok(Ok(Ok(result))) => Ok(result),
            Ok(Ok(Err(message))) => bail!("{message}"),
            Ok(Err(_)) => bail!("连接已关闭"),
            Err(_) => {
                self.pending.lock().await.remove(&id);
                bail!("等待对端回答超时")
            }
        }
    }

    /// Events pushed by the far side.
    pub fn subscribe(&self) -> broadcast::Receiver<Event> {
        self.events.subscribe()
    }

    pub fn close(&self) {
        self.alive.store(false, Ordering::SeqCst);
        self.conn.close(0u32.into(), b"done");
    }
}

/// Accepting side, one connection per `accept`, many connections per server.
pub struct ServerLink {
    conn: iroh::endpoint::Connection,
    send: Arc<Mutex<iroh::endpoint::SendStream>>,
    recv: iroh::endpoint::RecvStream,
    pub peer: String,
    pub trusted: bool,
}

impl ServerLink {
    /// Waits for one connection and runs the handshake.
    ///
    /// `Ok(None)` 表示端点已经关了，调用方该收工；握手失败则是 `Err`——一次失败只说明
    /// 那一次没成就，不能让调用方连带退出。手机在超时后放弃拨号时，留下的那次握手会
    /// 在服务端超时，这属于正常现象。
    pub async fn accept(
        endpoint: &Endpoint,
        trust: Arc<Mutex<TrustStore>>,
        name: &str,
    ) -> Result<Option<Self>> {
        let Some(connecting) = endpoint.accept().await else {
            return Ok(None);
        };
        let conn = connecting.await.context("handshake failed")?;
        let peer = conn.remote_id().to_string();
        let (mut send, mut recv) = conn.accept_bi().await.context("no tunnel stream")?;
        let peer_name = match read_frame(&mut recv).await? {
            Frame::Hello { name } => name,
            other => bail!("expected hello, got {other:?}"),
        };
        let (trusted, revoked) = {
            let mut store = trust.lock().await;
            // user:“撤销设备要真的生效”+(宿主撤销时改的是名单文件，传输进程手里是启动时
            // 读的那份内存副本；不重读就会出现「列表里没了、那台设备还能连」，而且下一次
            // 写入还会把撤销记录覆盖掉。每次握手前重读一次，文件很小）。
            store.reload().ok();
            if store.is_revoked(&peer) {
                // user:“允许撤销授权”+(首次连接会自动信任，所以撤销必须先于自动信任检查，
                // 否则那台设备下一次连上来又被当成“第一次见面”重新放进来)。
                (false, true)
            } else {
                let known = store.is_trusted(&peer);
                if !known {
                    // First contact: the ticket was handed to this device by the user,
                    // which is the consent. Remembering it here is what makes the next
                    // connection silent.
                    store.trust(&peer, &peer_name);
                    store.save().ok();
                }
                (store.is_trusted(&peer), false)
            }
        };
        write_frame(
            &mut send,
            &Frame::Welcome {
                id: endpoint.id().to_string(),
                name: name.to_owned(),
                trusted,
            },
        )
        .await?;
        // user:“撤销设备要真的生效”+(不要在这一帧之后立刻断开：连接一关，对端可能还没读到
        // 这个 Welcome，只能看到「closed by peer」。让这一帧走到、由调用方决定怎么收尾)。
        let _ = revoked;
        Ok(Some(Self {
            conn,
            send: Arc::new(Mutex::new(send)),
            recv,
            peer,
            trusted,
        }))
    }

    /// Pushes one event to the far side.
    pub async fn send_event(&self, method: &str, params: serde_json::Value) -> Result<()> {
        write_event(&self.send, method, params).await
    }

    /// The write half, for a task that pushes events while `serve` answers calls.
    ///
    /// Frames are written under the same lock, so an event never lands in the middle of a
    /// reply.
    pub fn sender(&self) -> Arc<Mutex<iroh::endpoint::SendStream>> {
        Arc::clone(&self.send)
    }

    /// Serves calls until the peer hangs up, answering with `handler`.
    ///
    /// 每条 Call 各自成任务、谁先答完谁先回，不再一条慢调用挡住后面的全部加载。
    /// user:“远程的时候打开界面要等很久”+(界面启动会并发读项目、模型、设置、大纲；
    /// 以前服务端逐条 await，一条冷启动的写在前面，后面全在排队)。
    pub async fn serve<F, Fut>(&mut self, handler: F) -> Result<()>
    where
        F: Fn(String, serde_json::Value) -> Fut,
        Fut: std::future::Future<Output = Result<serde_json::Value>>,
    {
        let send = Arc::clone(&self.send);
        let recv = &mut self.recv;
        let mut inflight: FuturesUnordered<_> = FuturesUnordered::new();
        loop {
            tokio::select! {
                frame = tokio::time::timeout(IDLE_TIMEOUT, read_frame(recv)) => {
                    let frame = match frame {
                        // 两分钟一个帧都没有：对端已经不在了，收掉这条连接等它重连。
                        Err(_) => bail!("对端长时间没有任何帧（心跳超时）"),
                        // A clean close is not an error worth logging as one.
                        Ok(Err(_)) => return Ok(()),
                        Ok(Ok(frame)) => frame,
                    };
                    match frame {
                        Frame::Call { id, method, params } => {
                            let answer = handler(method, params);
                            inflight.push(async move { (id, answer.await) });
                        }
                        Frame::Ping => {
                            let mut send = send.lock().await;
                            write_frame(&mut send, &Frame::Pong).await?;
                        }
                        Frame::Hello { .. } | Frame::Welcome { .. } => bail!("在一次连接里重复握手"),
                        other => bail!("意外的帧：{other:?}"),
                    }
                }
                Some((id, answer)) = inflight.next(), if !inflight.is_empty() => {
                    let reply = match answer {
                        Ok(result) => Frame::Reply { id, result },
                        Err(error) => Frame::Error {
                            id,
                            message: error.to_string(),
                        },
                    };
                    let mut send = send.lock().await;
                    write_frame(&mut send, &reply).await?;
                }
            }
        }
    }

    pub fn close(&self) {
        self.conn.close(0u32.into(), b"done");
    }
}

/// Writes one event frame through a shared write half.
pub async fn write_event(
    send: &Arc<Mutex<iroh::endpoint::SendStream>>,
    method: &str,
    params: serde_json::Value,
) -> Result<()> {
    let mut send = send.lock().await;
    write_frame(
        &mut send,
        &Frame::Event {
            method: method.to_owned(),
            params,
        },
    )
    .await
}

/// Spawns a task on whatever async runtime is current.
///
/// The crate is used from Tauri's runtime and from the CLI's; `tokio::spawn` needs the
/// caller to have entered a runtime, which both do.
fn tauri_free_spawn<F>(future: F)
where
    F: std::future::Future<Output = ()> + Send + 'static,
{
    tokio::spawn(future);
}
