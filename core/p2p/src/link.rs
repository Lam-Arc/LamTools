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
use std::sync::Arc;
use std::time::Duration;

use anyhow::{bail, Context, Result};
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
    Welcome { id: String, trusted: bool },
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

const MAX_FRAME_BYTES: usize = 16 * 1024 * 1024;
const EVENT_BUFFER: usize = 256;

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
    next_id: u64,
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
        let peer = match welcome {
            Frame::Welcome { id, trusted } => {
                if !trusted {
                    bail!("对端没有把这台设备当作可信设备，请先在电脑上确认配对");
                }
                id
            }
            other => bail!("对端先说了别的话：{other:?}"),
        };

        let pending: Arc<Mutex<HashMap<u64, oneshot::Sender<Result<serde_json::Value, String>>>>> =
            Arc::new(Mutex::new(HashMap::new()));
        let (event_tx, _) = broadcast::channel(EVENT_BUFFER);

        // One reader for the whole connection: replies go to their caller, events go to
        // subscribers, and a closed stream fails every waiting call instead of hanging.
        let reader_pending = Arc::clone(&pending);
        let reader_events = event_tx.clone();
        let reader_conn = conn.clone();
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
                    Ok(Frame::Pong) => {}
                    Ok(_) => {}
                    Err(error) => {
                        for (_, sender) in reader_pending.lock().await.drain() {
                            let _ = sender.send(Err(error.to_string()));
                        }
                        reader_conn.close(0u32.into(), b"closed");
                        return;
                    }
                }
            }
        });

        Ok(Self {
            conn,
            send: Arc::new(Mutex::new(send)),
            pending,
            events: event_tx,
            next_id: 1,
            peer,
        })
    }

    /// One Core-style call. Matched by id, so a slow answer cannot be taken for the next one.
    pub async fn call(
        &mut self,
        method: &str,
        params: serde_json::Value,
    ) -> Result<serde_json::Value> {
        let id = self.next_id;
        self.next_id += 1;
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
        self.conn.close(0u32.into(), b"done");
    }
}

/// Accepting side, one connection at a time.
pub struct ServerLink {
    conn: iroh::endpoint::Connection,
    send: Arc<Mutex<iroh::endpoint::SendStream>>,
    recv: iroh::endpoint::RecvStream,
    pub peer: String,
    pub trusted: bool,
}

impl ServerLink {
    /// Waits for one connection and runs the handshake.
    pub async fn accept(endpoint: &Endpoint, trust: Arc<Mutex<TrustStore>>) -> Result<Self> {
        let connecting = match endpoint.accept().await {
            Some(connecting) => connecting,
            None => bail!("endpoint closed"),
        };
        let conn = connecting.await.context("handshake failed")?;
        let peer = conn.remote_id().to_string();
        let (mut send, mut recv) = conn.accept_bi().await.context("no tunnel stream")?;
        let name = match read_frame(&mut recv).await? {
            Frame::Hello { name } => name,
            other => bail!("expected hello, got {other:?}"),
        };
        let trusted = {
            let mut store = trust.lock().await;
            let known = store.is_trusted(&peer);
            if !known {
                // First contact: the ticket was handed to this device by the user, which
                // is the consent. Remembering it here is what makes the next connection
                // silent.
                store.trust(&peer, &name);
                store.save().ok();
            }
            store.is_trusted(&peer)
        };
        write_frame(
            &mut send,
            &Frame::Welcome {
                id: endpoint.id().to_string(),
                trusted,
            },
        )
        .await?;
        Ok(Self {
            conn,
            send: Arc::new(Mutex::new(send)),
            recv,
            peer,
            trusted,
        })
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
    pub async fn serve<F, Fut>(&mut self, handler: F) -> Result<()>
    where
        F: Fn(String, serde_json::Value) -> Fut,
        Fut: std::future::Future<Output = Result<serde_json::Value>>,
    {
        loop {
            let frame = match read_frame(&mut self.recv).await {
                Ok(frame) => frame,
                Err(_) => return Ok(()),
            };
            match frame {
                Frame::Call { id, method, params } => {
                    let answer = handler(method, params).await;
                    let reply = match answer {
                        Ok(result) => Frame::Reply { id, result },
                        Err(error) => Frame::Error {
                            id,
                            message: error.to_string(),
                        },
                    };
                    let mut send = self.send.lock().await;
                    write_frame(&mut send, &reply).await?;
                }
                Frame::Ping => {
                    let mut send = self.send.lock().await;
                    write_frame(&mut send, &Frame::Pong).await?;
                }
                Frame::Hello { .. } | Frame::Welcome { .. } => bail!("在一次连接里重复握手"),
                other => bail!("意外的帧：{other:?}"),
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
