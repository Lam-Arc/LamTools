//! The tunnel: frames over one encrypted QUIC stream pair.
//!
//! user:“远程能力：手机可以连接电脑上的 Sunday，访问会话、发送消息……优先复用现有
//! Core API，不重新实现业务逻辑”+(这一层搬的就是 Core 本来就在说的 JSON-RPC 帧：
//! 同一个 method、同一份 params，到了对面直接交给同一个 Python Core)。
//!
//! Framing is a 4-byte big-endian length followed by UTF-8 JSON: trivial to read from any
//! side, and impossible to desync because the length is authoritative.

use std::sync::Arc;

use anyhow::{bail, Context, Result};
use iroh::{Endpoint, EndpointAddr};
use serde::{Deserialize, Serialize};
use tokio::sync::Mutex;

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

const MAX_FRAME_BYTES: usize = 16 * 1024 * 1024;

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
    send: iroh::endpoint::SendStream,
    recv: iroh::endpoint::RecvStream,
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
        Ok(Self {
            conn,
            send,
            recv,
            next_id: 1,
            peer,
        })
    }

    /// One Core-style call. Matches the reply by id, so a slow answer cannot be mistaken
    /// for the next one.
    pub async fn call(&mut self, method: &str, params: serde_json::Value) -> Result<serde_json::Value> {
        let id = self.next_id;
        self.next_id += 1;
        write_frame(
            &mut self.send,
            &Frame::Call {
                id,
                method: method.to_owned(),
                params,
            },
        )
        .await?;
        loop {
            match read_frame(&mut self.recv).await? {
                Frame::Reply { id: got, result } if got == id => return Ok(result),
                Frame::Error { id: got, message } if got == id => bail!("{message}"),
                Frame::Event { .. } => continue,
                other => bail!("对端回了意外的帧：{other:?}"),
            }
        }
    }

    /// Remote events, in order.
    pub fn events(&mut self) -> impl FnMut() -> Option<(String, serde_json::Value)> + '_ {
        move || None
    }

    pub fn close(&self) {
        self.conn.close(0u32.into(), b"done");
    }
}

/// Accepting side, one connection at a time.
pub struct ServerLink {
    conn: iroh::endpoint::Connection,
    send: iroh::endpoint::SendStream,
    recv: iroh::endpoint::RecvStream,
    pub peer: String,
    pub trusted: bool,
}

impl ServerLink {
    /// Waits for one connection and runs the handshake.
    ///
    /// `trust` is taken as a lock because a pairing decision can happen while another
    /// connection is being served.
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
            send,
            recv,
            peer,
            trusted,
        })
    }

    /// Serves calls until the peer hangs up, answering with `handler`.
    ///
    /// The handler is async and may fail; a failure becomes an `Error` frame so the phone
    /// shows the real reason instead of a timeout.
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
                    write_frame(&mut self.send, &reply).await?;
                }
                Frame::Ping => write_frame(&mut self.send, &Frame::Pong).await?,
                Frame::Hello { .. } | Frame::Welcome { .. } => {
                    bail!("在一次连接里重复握手")
                }
                other => bail!("意外的帧：{other:?}"),
            }
        }
    }

    pub fn close(&self) {
        self.conn.close(0u32.into(), b"done");
    }
}
