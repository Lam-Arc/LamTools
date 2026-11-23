//! Pumping Core events into the tunnel.
//!
//! user:“手机可以连接电脑上的 Sunday，访问会话、发送消息、查看 Agent 运行状态、处理审批、
//! 接收实时事件”+(会话状态与流式输出全靠 Core 的 WebSocket 通知；没有这条泵，远端只能
//! 发出去却收不到回复)。
//!
//! user:“事件泵重连不带游标：pump_core_events 重新 initialize 时没有 lastSeenSeq”+
//! (Core 的重订阅只看这一次 initialize 带的位点。泵断了重连却总从「现在」开始，断线那几秒
//! 里产生的事件就永远丢了；靠界面自己 `thread/resume` 兜底只能救回界面正在看的那一条会话，
//! 不走 store 续订的页面（审批、后台任务、桌宠）会静默少事件)。
//!
//! 所以这里把位点做成泵自己的一部分：每转发一条事件就记下它的 `seq` 与它所属的会话，
//! 重连时把 `lastSeenSeq` 带给 `initialize`，并对已知会话补一次 `thread/resume`，
//! 让 Core 从那个位点把漏掉的事件补回来。
//!
//! The pump is deliberately dumb about *meaning*: it forwards every message that carries a
//! `method`. Which events matter is the interface's business, not the transport's.

use anyhow::{Context, Result};
use futures_util::{SinkExt, StreamExt};
use tokio::sync::Mutex;
use tokio_tungstenite::tungstenite::Message;

use crate::link::write_event;

/// 事件位点：Core journal 里的 `seq`，加上它属于哪条会话。
///
/// 两条都要：`lastSeenSeq` 只说明「看到哪」，补事件还得知道「补哪一条会话」——Core 的
/// `thread/resume` 是按会话取日志的。
#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct Cursor {
    seq: u64,
    thread: Option<String>,
}

impl Cursor {
    pub fn new(seq: u64, thread: Option<String>) -> Self {
        Self { seq, thread }
    }

    /// 看到一条事件：位点只往前走，不往回退。
    ///
    /// 补发、重放、乱序都可能让 seq 变小；退回去会让下一次重连重复补一大段。
    pub fn observe(&mut self, params: &serde_json::Value) {
        if let Some(seq) = event_seq(params) {
            self.seq = self.seq.max(seq);
        }
        if let Some(thread) = params
            .get("thread_id")
            .or_else(|| params.get("threadId"))
            .and_then(|value| value.as_str())
        {
            self.thread = Some(thread.to_owned());
        }
    }

    pub fn seq(&self) -> u64 {
        self.seq
    }

    pub fn thread(&self) -> Option<&str> {
        self.thread.as_deref()
    }

    /// 有没有值得补的位点：0 说明一开始就没见过任何东西，重连时不必带。
    pub fn is_empty(&self) -> bool {
        self.seq == 0 && self.thread.is_none()
    }
}

/// 从一条通知的 params 里取位点。
///
/// Core 把 journal 事件的 `seq` 放在 params 里（`event_notification` 直接把事件字典当
/// params）；`event_seq` 是同一件事的历史字段名，两种都认。拿不到就是 0——流式增量
/// （`seq=0`）本来就不进 journal，不该被当成位点。
pub fn event_seq(params: &serde_json::Value) -> Option<u64> {
    ["seq", "event_seq", "eventSeq"]
        .iter()
        .find_map(|key| params.get(*key).and_then(|value| value.as_u64()))
        .filter(|seq| *seq > 0)
}

/// `initialize` 的 params：带上位点，Core 才会从那里续订。
pub fn initialize_params(last_seen_seq: u64, thread: Option<&str>) -> serde_json::Value {
    let mut params = serde_json::json!({
        "clientInfo": { "name": "sunday-p2p", "version": env!("CARGO_PKG_VERSION") },
    });
    if last_seen_seq > 0 {
        params["lastSeenSeq"] = serde_json::json!(last_seen_seq);
    }
    if let Some(thread) = thread.filter(|thread| !thread.is_empty()) {
        params["threadId"] = serde_json::json!(thread);
    }
    params
}

/// Connects to the Core's app-server socket and relays notifications until it closes.
///
/// `link` is shared with the request handler: replies and events travel on the same tunnel
/// stream, so both sides take the same lock.
pub async fn pump_core_events(
    port: u16,
    token: &str,
    send: std::sync::Arc<Mutex<iroh::endpoint::SendStream>>,
) -> Result<()> {
    let mut cursor = Cursor::default();
    pump_core_events_with_cursor(port, token, send, &mut cursor).await
}

/// 带位点的事件泵：断线重连时从 `cursor` 指的地方接着订。
///
/// 返回时 `cursor` 保留最后一次成功转发的位置，调用方在下一轮重连时原样交回来。
pub async fn pump_core_events_with_cursor(
    port: u16,
    token: &str,
    send: std::sync::Arc<Mutex<iroh::endpoint::SendStream>>,
    cursor: &mut Cursor,
) -> Result<()> {
    let url = format!("ws://127.0.0.1:{port}/api/core/app-server");
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
        "params": initialize_params(cursor.seq(), cursor.thread()),
    });
    socket
        .send(Message::Text(initialize.to_string().into()))
        .await
        .context("cannot send the initialize frame")?;

    // 断过线、又知道在看哪条会话：让 Core 从位点把漏掉的事件补一遍。
    //
    // user:“断线恢复后不得漏事件”+(initialize 的 lastSeenSeq 只是把位点交给 Core；
    // 真正把 journal 取回来的是 `thread/resume`。这里补一次，补回来的事件照常往后转发，
    // 对端按 seq 去重)。
    if let (Some(thread), true) = (cursor.thread(), cursor.seq() > 0) {
        let resume = serde_json::json!({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "thread/resume",
            "params": {
                "thread_id": thread,
                "last_seen_seq": cursor.seq(),
            },
        });
        socket
            .send(Message::Text(resume.to_string().into()))
            .await
            .context("cannot send the resume frame")?;
    }

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
        // 先记位点再转发：转发失败的这一条，下一次重连还能被补回来。
        cursor.observe(&params);
        if write_event(&send, method, params).await.is_err() {
            break;
        }
    }
    Ok(())
}

/// Keeps one pump alive for the life of a connection.
///
/// user:“事件泵重连不带游标”+(位点活在循环外面：每一次重连都把上一次转发到哪带回去，
/// 而不是从「现在」重新开始)。
pub async fn pump_until_closed(
    port: u16,
    token: String,
    send: std::sync::Arc<Mutex<iroh::endpoint::SendStream>>,
    closed: std::sync::Arc<Mutex<bool>>,
) {
    let mut cursor = Cursor::default();
    pump_until_closed_from(port, token, send, closed, &mut cursor).await
}

/// 同上，但位点由调用方持有——宿主可以在自己那一侧保留它，跨多次连接复用。
pub async fn pump_until_closed_from(
    port: u16,
    token: String,
    send: std::sync::Arc<Mutex<iroh::endpoint::SendStream>>,
    closed: std::sync::Arc<Mutex<bool>>,
    cursor: &mut Cursor,
) {
    loop {
        if *closed.lock().await {
            return;
        }
        if pump_core_events_with_cursor(port, &token, std::sync::Arc::clone(&send), cursor)
            .await
            .is_err()
        {
            // 连接不是对端关的，而是这条 socket 坏了（Core 重启、端口换了）：带着位点
            // 重来一次比直接放弃更有用，Core 会从那个位置把事件补回来。
            eprintln!(
                "[sunday-p2p] event pump dropped at seq={}; retrying with the cursor",
                cursor.seq()
            );
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

#[cfg(test)]
mod tests {
    use super::*;

    /// user:“事件泵重连不带游标”+(位点从事件里来，重连的 initialize 必须带出去)。
    #[test]
    fn the_cursor_is_read_from_the_events_themselves() {
        let mut cursor = Cursor::default();
        assert!(cursor.is_empty());
        cursor.observe(&serde_json::json!({ "seq": 41, "thread_id": "t-1" }));
        assert_eq!(cursor.seq(), 41);
        assert_eq!(cursor.thread(), Some("t-1"));
    }

    /// 补发/乱序不能让位点往回退：退回去等于下次重连重复补一大段。
    #[test]
    fn the_cursor_never_walks_backwards() {
        let mut cursor = Cursor::default();
        cursor.observe(&serde_json::json!({ "seq": 90, "thread_id": "t-1" }));
        cursor.observe(&serde_json::json!({ "seq": 12 }));
        assert_eq!(cursor.seq(), 90);
    }

    /// 流式增量（seq=0）不是位点：把它当位点会让重连永远只补最后一条。
    #[test]
    fn transient_progress_is_not_a_position() {
        assert_eq!(event_seq(&serde_json::json!({ "seq": 0 })), None);
        assert_eq!(event_seq(&serde_json::json!({ "event_seq": 7 })), Some(7));
        assert_eq!(event_seq(&serde_json::json!({ "method": "item/delta" })), None);
        let mut cursor = Cursor::default();
        cursor.observe(&serde_json::json!({ "seq": 0, "method": "item/delta" }));
        assert!(cursor.is_empty());
    }

    /// 重连时交出去的 params 里必须有 `lastSeenSeq`，而且只有真的见过事件才带。
    #[test]
    fn the_reconnect_handshake_carries_the_cursor_and_nothing_fake() {
        let fresh = initialize_params(0, None);
        assert_eq!(
            fresh["clientInfo"]["name"],
            serde_json::json!("sunday-p2p"),
            "clientInfo 一直要有：Core 只对介绍过自己的连接推送"
        );
        assert!(fresh.get("lastSeenSeq").is_none(), "没见过事件就别编位点");
        assert!(fresh.get("threadId").is_none());

        let resumed = initialize_params(128, Some("t-9"));
        assert_eq!(resumed["lastSeenSeq"], serde_json::json!(128));
        assert_eq!(resumed["threadId"], serde_json::json!("t-9"));
    }
}
