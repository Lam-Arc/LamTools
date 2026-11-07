//! Pumping Core events into the tunnel.
//!
//! user:“手机可以连接电脑上的 Sunday，访问会话、发送消息、查看 Agent 运行状态、处理审批、
//! 接收实时事件”+(会话状态与流式输出全靠 Core 的 WebSocket 通知；没有这条泵，远端只能
//! 发出去却收不到回复)。
//!
//! The pump is deliberately dumb: it opens one WebSocket to the local Core with the same
//! bearer token the REST calls use, sends the same `initialize` the interface sends, and
//! forwards every message that carries a `method` as an event frame. Which events matter is
//! the interface's business, not the transport's.

use anyhow::{bail, Context, Result};
use futures_util::{SinkExt, StreamExt};
use tokio::sync::Mutex;
use tokio_tungstenite::tungstenite::Message;

use crate::link::write_event;

/// Connects to the Core's app-server socket and relays notifications until it closes.
///
/// `link` is shared with the request handler: replies and events travel on the same tunnel
/// stream, so both sides take the same lock.
pub async fn pump_core_events(
    port: u16,
    token: &str,
    send: std::sync::Arc<Mutex<iroh::endpoint::SendStream>>,
) -> Result<()> {
    let url = format!("ws://127.0.0.1:{port}/app-server");
    use tokio_tungstenite::tungstenite::client::IntoClientRequest;
    let mut request = url
        .as_str()
        .into_client_request()
        .context("事件通道地址不合法")?;
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
        .context("无法连接到本机 Core 的事件通道")?;

    // Same handshake the shared interface performs; the Core does not push anything to a
    // client that has not introduced itself.
    let initialize = serde_json::json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": { "clientInfo": { "name": "sunday-p2p", "version": "0.1.0" } },
    });
    socket
        .send(Message::Text(initialize.to_string().into()))
        .await
        .context("cannot send the initialize frame")?;

    while let Some(message) = socket.next().await {
        let message = match message {
            Ok(message) => message,
            Err(_) => break,
        };
        let text = match message {
            Message::Text(text) => text.to_string(),
            Message::Binary(bytes) => String::from_utf8_lossy(&bytes).to_string(),
            Message::Ping(_) | Message::Pong(_) | Message::Frame(_) => continue,
            Message::Close(_) => break,
        };
        let value: serde_json::Value = match serde_json::from_str(&text) {
            Ok(value) => value,
            Err(_) => continue,
        };
        // Notifications carry a method; responses carry the id we asked with.
        let Some(method) = value.get("method").and_then(|value| value.as_str()) else {
            continue;
        };
        let params = value
            .get("params")
            .cloned()
            .unwrap_or(serde_json::Value::Null);
        if write_event(&send, method, params).await.is_err() {
            break;
        }
    }
    Ok(())
}

/// Keeps one pump alive for the life of a connection.
pub async fn pump_until_closed(
    port: u16,
    token: String,
    send: std::sync::Arc<Mutex<iroh::endpoint::SendStream>>,
    closed: std::sync::Arc<Mutex<bool>>,
) {
    loop {
        if *closed.lock().await {
            return;
        }
        if pump_core_events(port, &token, std::sync::Arc::clone(&send))
            .await
            .is_err()
        {
            return;
        }
        // The Core restarted or the socket dropped: wait a moment and re-subscribe.
        tokio::time::sleep(std::time::Duration::from_secs(2)).await;
        if *closed.lock().await {
            return;
        }
    }
}

/// Answers whether a Core is reachable on this port, for a clear error instead of silence.
pub async fn core_reachable(port: u16) -> bool {
    if port == 0 {
        return false;
    }
    tokio::net::TcpStream::connect(("127.0.0.1", port))
        .await
        .is_ok()
}
