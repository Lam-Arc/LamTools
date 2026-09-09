use serde::{Deserialize, Serialize};
use std::{
    collections::HashMap,
    net::TcpStream,
    sync::{
        atomic::{AtomicBool, AtomicU64, Ordering},
        mpsc, Arc, Mutex,
    },
    thread::{self, JoinHandle},
    time::{Duration, SystemTime, UNIX_EPOCH},
};
use tungstenite::{
    client::IntoClientRequest, connect, http::header, stream::MaybeTlsStream, Message, WebSocket,
};

use super::secure_store::{DesktopAccountSession, SecureStore, DESKTOP_ACCOUNT_SESSION_KEY};

const MAX_QUEUE: usize = 128;
const TUNNEL_ID_BYTES: usize = 36;
const ACCESS_REFRESH_SKEW_MS: i64 = 60_000;
const RELAY_UNAUTHORIZED_ERROR: &str = "relay authorization rejected: 401 Unauthorized";

#[derive(Clone, Default)]
pub struct RelayConfig {
    session: Option<DesktopAccountSession>,
    secure_store: Option<Arc<dyn SecureStore>>,
}

impl RelayConfig {
    pub fn from_account_session(
        session: Option<&DesktopAccountSession>,
        secure_store: Arc<dyn SecureStore>,
    ) -> Result<Self, String> {
        let Some(session) = session else {
            return Ok(Self::default());
        };
        if !session.is_valid() {
            return Err("桌面账号会话无效，请重新登录服务器".to_string());
        }
        relay_host_endpoint(&session.base_url)?;
        Ok(Self {
            session: Some(session.clone()),
            secure_store: Some(secure_store),
        })
    }
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct RefreshedTokens {
    server_id: String,
    access_token: String,
    refresh_token: String,
    access_expires_at_ms: i64,
    refresh_expires_at_ms: i64,
}

fn relay_host_endpoint(base_url: &str) -> Result<String, String> {
    let mut endpoint =
        url::Url::parse(base_url.trim()).map_err(|_| "Relay 服务器地址无效".to_string())?;
    endpoint.set_path("/v1/relay/host");
    endpoint.set_query(None);
    endpoint.set_fragment(None);
    match endpoint.scheme() {
        "https" => endpoint
            .set_scheme("wss")
            .map_err(|_| "Relay 服务器协议无效".to_string())?,
        "http" => endpoint
            .set_scheme("ws")
            .map_err(|_| "Relay 服务器协议无效".to_string())?,
        "wss" | "ws" => {}
        _ => return Err("Relay 服务器协议无效".to_string()),
    }
    Ok(endpoint.to_string())
}

fn refresh_endpoint(base_url: &str) -> Result<String, String> {
    let mut endpoint =
        url::Url::parse(base_url.trim()).map_err(|_| "Relay 服务器地址无效".to_string())?;
    match endpoint.scheme() {
        "https" | "http" => {}
        "wss" => endpoint
            .set_scheme("https")
            .map_err(|_| "Relay 服务器协议无效".to_string())?,
        "ws" => endpoint
            .set_scheme("http")
            .map_err(|_| "Relay 服务器协议无效".to_string())?,
        _ => return Err("Relay 服务器协议无效".to_string()),
    }
    endpoint.set_path("/v1/auth/refresh");
    endpoint.set_query(None);
    endpoint.set_fragment(None);
    Ok(endpoint.to_string())
}

fn now_ms() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
        .min(i64::MAX as u128) as i64
}

fn access_token_needs_refresh(session: &DesktopAccountSession) -> bool {
    session.access_expires_at_ms <= now_ms().saturating_add(ACCESS_REFRESH_SKEW_MS)
}

fn refresh_account_session(
    session: &mut DesktopAccountSession,
    secure_store: &dyn SecureStore,
) -> Result<(), String> {
    if session.refresh_expires_at_ms <= now_ms() {
        return Err("桌面账号登录已过期，请重新登录服务器".to_string());
    }
    let endpoint = refresh_endpoint(&session.base_url)?;
    let mut response = ureq::post(&endpoint)
        .header("Accept", "application/json")
        .send_json(serde_json::json!({"refreshToken": session.refresh_token}))
        .map_err(|error| format!("Relay 凭据刷新失败：{error}"))?;
    let tokens: RefreshedTokens = response
        .body_mut()
        .read_json()
        .map_err(|error| format!("Relay 凭据刷新响应无效：{error}"))?;
    if tokens.server_id != session.server_id
        || tokens.access_token.trim().is_empty()
        || tokens.refresh_token.trim().is_empty()
        || tokens.access_expires_at_ms <= now_ms()
        || tokens.refresh_expires_at_ms <= now_ms()
    {
        return Err("Relay 凭据刷新响应无效".to_string());
    }
    session.access_token = tokens.access_token;
    session.refresh_token = tokens.refresh_token;
    session.access_expires_at_ms = tokens.access_expires_at_ms;
    session.refresh_expires_at_ms = tokens.refresh_expires_at_ms;
    secure_store.save(
        DESKTOP_ACCOUNT_SESSION_KEY,
        &serde_json::to_vec(session).map_err(|error| error.to_string())?,
    )
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PairingRegistration {
    pub pairing_id: String,
    pub code: String,
    pub desktop_device_id: String,
    pub desktop_public_key: String,
    pub gateway_url: String,
    pub relay_url: Option<String>,
    pub expires_at_ms: u64,
    pub protocol: String,
    pub version: u8,
}

impl From<&super::pairing::PairingCodePayload> for PairingRegistration {
    fn from(pairing: &super::pairing::PairingCodePayload) -> Self {
        Self {
            pairing_id: pairing.pairing_id.clone(),
            code: pairing.code.clone(),
            desktop_device_id: pairing.desktop_device_id.clone(),
            desktop_public_key: pairing.desktop_public_key.clone(),
            gateway_url: pairing.gateway_url.clone(),
            relay_url: pairing.relay_url.clone(),
            expires_at_ms: pairing.expires_at_ms,
            protocol: pairing.protocol.clone(),
            version: pairing.version,
        }
    }
}

#[derive(Clone, Debug, Default, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RelayStatus {
    pub configured: bool,
    pub connected: bool,
    pub reconnects: u64,
    pub last_error: Option<String>,
}

pub struct RelayClient {
    endpoint: String,
    stop: Arc<AtomicBool>,
    connected: Arc<AtomicBool>,
    reconnects: Arc<AtomicU64>,
    last_error: Arc<Mutex<Option<String>>>,
    pairing: Arc<Mutex<Option<PairingRegistration>>>,
    join: Mutex<Option<JoinHandle<()>>>,
}

struct BridgeHandle {
    sender: mpsc::SyncSender<Vec<u8>>,
    stop: Arc<AtomicBool>,
    join: Option<JoinHandle<()>>,
}

enum RelayEvent {
    Packet(Vec<u8>),
    BridgeReady(String),
}

impl BridgeHandle {
    fn stop(mut self) {
        self.stop.store(true, Ordering::SeqCst);
        // Dropping the last sender wakes a bridge that is waiting for input.
        drop(self.sender);
        if let Some(join) = self.join.take() {
            let _ = join.join();
        }
    }
}

impl RelayClient {
    pub fn start(
        config: RelayConfig,
        device_id: String,
        gateway_port: u16,
    ) -> Result<Option<Self>, String> {
        let (Some(session), Some(secure_store)) = (config.session, config.secure_store) else {
            return Ok(None);
        };
        let endpoint = relay_host_endpoint(&session.base_url)?;
        let credentials = Arc::new(Mutex::new(session));
        let stop = Arc::new(AtomicBool::new(false));
        let connected = Arc::new(AtomicBool::new(false));
        let reconnects = Arc::new(AtomicU64::new(0));
        let last_error = Arc::new(Mutex::new(None));
        let pairing = Arc::new(Mutex::new(None));
        let thread_stop = stop.clone();
        let thread_connected = connected.clone();
        let thread_reconnects = reconnects.clone();
        let thread_error = last_error.clone();
        let thread_pairing = pairing.clone();
        let thread_endpoint = endpoint.clone();
        let thread_credentials = credentials.clone();
        let thread_secure_store = secure_store.clone();
        let join = thread::Builder::new()
            .name("lamtools-relay-client".to_string())
            .spawn(move || {
                let mut delay = Duration::from_secs(1);
                while !thread_stop.load(Ordering::SeqCst) {
                    let access_token = {
                        let mut session = thread_credentials.lock().unwrap();
                        if access_token_needs_refresh(&session) {
                            if let Err(error) =
                                refresh_account_session(&mut session, thread_secure_store.as_ref())
                            {
                                *thread_error.lock().unwrap() = Some(error);
                                thread_connected.store(false, Ordering::SeqCst);
                                thread_reconnects.fetch_add(1, Ordering::Relaxed);
                                drop(session);
                                wait_for_reconnect(&thread_stop, delay);
                                delay = (delay * 2).min(Duration::from_secs(30));
                                continue;
                            }
                        }
                        session.access_token.clone()
                    };
                    let connection = run_relay_connection(
                        &thread_endpoint,
                        &access_token,
                        &device_id,
                        gateway_port,
                        &thread_stop,
                        &thread_connected,
                        &thread_pairing,
                    );
                    if matches!(&connection, Err(error) if error == RELAY_UNAUTHORIZED_ERROR) {
                        let refresh = thread_credentials
                            .lock()
                            .map_err(|_| "Relay 凭据锁不可用".to_string())
                            .and_then(|mut session| {
                                refresh_account_session(&mut session, thread_secure_store.as_ref())
                            });
                        match refresh {
                            Ok(()) => {
                                *thread_error.lock().unwrap() = None;
                                thread_connected.store(false, Ordering::SeqCst);
                                delay = Duration::from_secs(1);
                                continue;
                            }
                            Err(error) => *thread_error.lock().unwrap() = Some(error),
                        }
                    } else {
                        match connection {
                            Ok(()) if thread_stop.load(Ordering::SeqCst) => break,
                            Ok(()) => {}
                            Err(error) => *thread_error.lock().unwrap() = Some(error),
                        }
                    }
                    thread_connected.store(false, Ordering::SeqCst);
                    thread_reconnects.fetch_add(1, Ordering::Relaxed);
                    wait_for_reconnect(&thread_stop, delay);
                    delay = (delay * 2).min(Duration::from_secs(30));
                }
            })
            .map_err(|error| error.to_string())?;
        Ok(Some(Self {
            endpoint,
            stop,
            connected,
            reconnects,
            last_error,
            pairing,
            join: Mutex::new(Some(join)),
        }))
    }

    pub fn register_pairing(&self, pairing: PairingRegistration) {
        if let Ok(mut current) = self.pairing.lock() {
            *current = Some(pairing);
        }
    }

    pub fn endpoint(&self) -> &str {
        &self.endpoint
    }

    pub fn status(&self) -> RelayStatus {
        RelayStatus {
            configured: true,
            connected: self.connected.load(Ordering::Relaxed),
            reconnects: self.reconnects.load(Ordering::Relaxed),
            last_error: self.last_error.lock().ok().and_then(|value| value.clone()),
        }
    }

    pub fn stop(&self) {
        self.stop.store(true, Ordering::SeqCst);
        if let Ok(mut join) = self.join.lock() {
            if let Some(handle) = join.take() {
                let _ = handle.join();
            }
        }
    }
}

impl Drop for RelayClient {
    fn drop(&mut self) {
        self.stop();
    }
}

fn wait_for_reconnect(stop: &AtomicBool, delay: Duration) {
    for _ in 0..delay.as_millis() / 100 {
        if stop.load(Ordering::SeqCst) {
            break;
        }
        thread::sleep(Duration::from_millis(100));
    }
}

fn run_relay_connection(
    endpoint: &str,
    access_token: &str,
    device_id: &str,
    gateway_port: u16,
    stop: &AtomicBool,
    connected: &AtomicBool,
    pairing: &Arc<Mutex<Option<PairingRegistration>>>,
) -> Result<(), String> {
    let separator = if endpoint.contains('?') { '&' } else { '?' };
    let url = format!(
        "{endpoint}{separator}role=desktop&device_id={}",
        urlencoding::encode(device_id),
    );
    let mut request = url
        .into_client_request()
        .map_err(|error| format!("relay request failed: {error}"))?;
    request.headers_mut().insert(
        header::AUTHORIZATION,
        format!("Bearer {access_token}")
            .parse()
            .map_err(|error| format!("relay authorization header failed: {error}"))?,
    );
    let (mut relay, _) = match connect(request) {
        Ok(connection) => connection,
        Err(tungstenite::Error::Http(response))
            if response.status() == tungstenite::http::StatusCode::UNAUTHORIZED =>
        {
            return Err(RELAY_UNAUTHORIZED_ERROR.to_string());
        }
        Err(error) => return Err(format!("relay connect failed: {error}")),
    };
    connected.store(true, Ordering::SeqCst);
    set_read_timeout(&mut relay, Some(Duration::from_millis(250)));
    let (outgoing, receiver) = mpsc::sync_channel::<RelayEvent>(MAX_QUEUE);
    let mut bridges: HashMap<String, BridgeHandle> = HashMap::new();
    let mut registered_pairing_id: Option<String> = None;
    let mut last_heartbeat = std::time::Instant::now();
    let result = loop {
        if stop.load(Ordering::SeqCst) {
            break Ok(());
        }
        let mut send_error = None;
        while let Ok(event) = receiver.try_recv() {
            let message = match event {
                RelayEvent::Packet(packet) => Message::Binary(packet.into()),
                RelayEvent::BridgeReady(id) => Message::Text(
                    serde_json::json!({"type":"bridge_ready","tunnel_id":id})
                        .to_string()
                        .into(),
                ),
            };
            if let Err(error) = relay.send(message) {
                send_error = Some(format!("relay send failed: {error}"));
                break;
            }
        }
        if let Some(error) = send_error {
            break Err(error);
        }

        if last_heartbeat.elapsed() >= Duration::from_secs(25) {
            relay
                .send(Message::Ping(Vec::new().into()))
                .map_err(|error| format!("relay heartbeat failed: {error}"))?;
            last_heartbeat = std::time::Instant::now();
        }

        let current_pairing = pairing.lock().ok().and_then(|value| value.clone());
        if current_pairing
            .as_ref()
            .map(|value| value.pairing_id.as_str())
            != registered_pairing_id.as_deref()
        {
            if let Some(value) = current_pairing {
                let mut message = serde_json::to_value(value)
                    .map_err(|error| format!("pairing registration failed: {error}"))?;
                message["type"] = serde_json::Value::String("pairing_register".to_string());
                relay
                    .send(Message::Text(message.to_string().into()))
                    .map_err(|error| format!("pairing registration send failed: {error}"))?;
                registered_pairing_id = message
                    .get("pairingId")
                    .and_then(|value| value.as_str())
                    .map(str::to_string);
            }
        }

        let message = match relay.read() {
            Ok(message) => message,
            Err(tungstenite::Error::Io(error))
                if matches!(
                    error.kind(),
                    std::io::ErrorKind::WouldBlock | std::io::ErrorKind::TimedOut
                ) =>
            {
                continue
            }
            Err(error) => break Err(format!("relay receive failed: {error}")),
        };
        match message {
            Message::Text(text) => {
                let value: serde_json::Value = serde_json::from_str(&text).unwrap_or_default();
                let kind = value
                    .get("type")
                    .and_then(|value| value.as_str())
                    .unwrap_or_default();
                let id = value
                    .get("tunnel_id")
                    .and_then(|value| value.as_str())
                    .unwrap_or_default()
                    .to_string();
                if kind == "open" && id.len() == TUNNEL_ID_BYTES {
                    if let Some(previous) = bridges.remove(&id) {
                        previous.stop();
                    }
                    let (sender, input) = mpsc::sync_channel(MAX_QUEUE);
                    let pairing_id = value
                        .get("pairing_id")
                        .and_then(|value| value.as_str())
                        .map(str::to_string);
                    let (bridge_stop, join) = spawn_local_bridge(
                        id.clone(),
                        gateway_port,
                        pairing_id,
                        input,
                        outgoing.clone(),
                    );
                    bridges.insert(
                        id,
                        BridgeHandle {
                            sender,
                            stop: bridge_stop,
                            join: Some(join),
                        },
                    );
                } else if kind == "close" {
                    if let Some(bridge) = bridges.remove(&id) {
                        bridge.stop();
                    }
                }
            }
            Message::Binary(packet) => {
                if packet.len() < TUNNEL_ID_BYTES {
                    continue;
                }
                let Ok(id) = std::str::from_utf8(&packet[..TUNNEL_ID_BYTES]) else {
                    continue;
                };
                let disconnected = bridges.get(id).is_some_and(|bridge| {
                    matches!(
                        bridge.sender.try_send(packet[TUNNEL_ID_BYTES..].to_vec()),
                        Err(mpsc::TrySendError::Disconnected(_))
                    )
                });
                if disconnected {
                    if let Some(bridge) = bridges.remove(id) {
                        bridge.stop();
                    }
                }
            }
            Message::Close(_) => break Ok(()),
            Message::Ping(value) => {
                relay
                    .send(Message::Pong(value))
                    .map_err(|error| format!("relay Pong failed: {error}"))?;
            }
            _ => {}
        }
    };
    let _ = relay.close(None);
    stop_all_bridges(&mut bridges);
    result
}

fn spawn_local_bridge(
    id: String,
    gateway_port: u16,
    pairing_id: Option<String>,
    input: mpsc::Receiver<Vec<u8>>,
    outgoing: mpsc::SyncSender<RelayEvent>,
) -> (Arc<AtomicBool>, JoinHandle<()>) {
    let stop = Arc::new(AtomicBool::new(false));
    let thread_stop = stop.clone();
    let join = thread::spawn(move || {
        let target = pairing_id
            .map(|value| {
                format!(
                    "ws://127.0.0.1:{gateway_port}/_lamtools/tunnel?pairing={}",
                    urlencoding::encode(&value)
                )
            })
            .unwrap_or_else(|| {
                format!(
                    "ws://127.0.0.1:{gateway_port}/_lamtools/tunnel?relay_tunnel={}",
                    urlencoding::encode(&id)
                )
            });
        let Ok((mut gateway, _)) = connect(target) else {
            return;
        };
        if !send_bridge_event(&outgoing, RelayEvent::BridgeReady(id.clone()), &thread_stop) {
            return;
        }
        set_read_timeout(&mut gateway, Some(Duration::from_millis(100)));
        while !thread_stop.load(Ordering::SeqCst) {
            loop {
                match input.try_recv() {
                    Ok(payload) => {
                        if gateway.send(Message::Binary(payload.into())).is_err() {
                            return;
                        }
                    }
                    Err(mpsc::TryRecvError::Empty) => break,
                    Err(mpsc::TryRecvError::Disconnected) => return,
                }
            }
            match gateway.read() {
                Ok(Message::Binary(payload)) => {
                    let mut packet = Vec::with_capacity(TUNNEL_ID_BYTES + payload.len());
                    packet.extend_from_slice(id.as_bytes());
                    packet.extend_from_slice(&payload);
                    if !send_bridge_event(&outgoing, RelayEvent::Packet(packet), &thread_stop) {
                        return;
                    }
                }
                Ok(Message::Ping(value)) => {
                    if gateway.send(Message::Pong(value)).is_err() {
                        return;
                    }
                }
                Ok(Message::Close(_)) => return,
                Ok(_) => {}
                Err(tungstenite::Error::Io(error))
                    if matches!(
                        error.kind(),
                        std::io::ErrorKind::WouldBlock | std::io::ErrorKind::TimedOut
                    ) => {}
                Err(_) => return,
            }
            thread::sleep(Duration::from_millis(5));
        }
    });
    (stop, join)
}

fn send_bridge_event(
    outgoing: &mpsc::SyncSender<RelayEvent>,
    mut event: RelayEvent,
    stop: &AtomicBool,
) -> bool {
    loop {
        if stop.load(Ordering::SeqCst) {
            return false;
        }
        match outgoing.try_send(event) {
            Ok(()) => return true,
            Err(mpsc::TrySendError::Disconnected(_)) => return false,
            Err(mpsc::TrySendError::Full(returned)) => {
                event = returned;
                thread::sleep(Duration::from_millis(10));
            }
        }
    }
}

fn stop_all_bridges(bridges: &mut HashMap<String, BridgeHandle>) {
    for (_, bridge) in bridges.drain() {
        bridge.stop();
    }
}

fn set_read_timeout(socket: &mut WebSocket<MaybeTlsStream<TcpStream>>, timeout: Option<Duration>) {
    match socket.get_mut() {
        MaybeTlsStream::Plain(stream) => {
            let _ = stream.set_read_timeout(timeout);
        }
        MaybeTlsStream::Rustls(stream) => {
            let _ = stream.get_mut().set_read_timeout(timeout);
        }
        _ => {}
    }
}

#[cfg(test)]
mod tests {
    use super::{
        refresh_account_session, refresh_endpoint, relay_host_endpoint, DesktopAccountSession,
    };
    use crate::remote::secure_store::{
        MemorySecureStore, SecureStore, DESKTOP_ACCOUNT_SESSION_KEY,
    };
    use std::{
        io::{Read, Write},
        net::TcpListener,
        thread,
    };

    #[test]
    fn relay_and_refresh_endpoints_are_derived_from_one_server_base() {
        assert_eq!(
            relay_host_endpoint("https://relay.example/root?stale=1").unwrap(),
            "wss://relay.example/v1/relay/host"
        );
        assert_eq!(
            refresh_endpoint("wss://relay.example/v1/relay/host").unwrap(),
            "https://relay.example/v1/auth/refresh"
        );
    }

    #[test]
    fn refresh_rotates_and_persists_desktop_credentials() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let server = thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut request = Vec::new();
            let mut chunk = [0_u8; 4096];
            loop {
                let length = stream.read(&mut chunk).unwrap();
                request.extend_from_slice(&chunk[..length]);
                let Some(header_end) = request.windows(4).position(|value| value == b"\r\n\r\n")
                else {
                    continue;
                };
                let headers = String::from_utf8_lossy(&request[..header_end]);
                let content_length = headers
                    .lines()
                    .find_map(|line| {
                        line.to_ascii_lowercase()
                            .strip_prefix("content-length:")
                            .and_then(|value| value.trim().parse::<usize>().ok())
                    })
                    .unwrap_or_default();
                if request.len() >= header_end + 4 + content_length {
                    break;
                }
            }
            let request = String::from_utf8_lossy(&request);
            assert!(request.starts_with("POST /v1/auth/refresh HTTP/1.1"));
            assert!(request.contains("refresh-old"));
            let body = serde_json::json!({
                "serverId": "server-1",
                "accessToken": "access-new",
                "refreshToken": "refresh-new",
                "accessExpiresAtMs": super::now_ms() + 600_000,
                "refreshExpiresAtMs": super::now_ms() + 1_200_000,
            })
            .to_string();
            write!(
                stream,
                "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                body.len(),
                body
            )
            .unwrap();
        });
        let store = MemorySecureStore::default();
        let mut session = DesktopAccountSession {
            base_url: format!("http://{address}"),
            server_id: "server-1".to_string(),
            username: "Lam".to_string(),
            node_id: "desktop-1".to_string(),
            public_key: "public-key".to_string(),
            access_token: "access-old".to_string(),
            refresh_token: "refresh-old".to_string(),
            access_expires_at_ms: super::now_ms() - 1,
            refresh_expires_at_ms: super::now_ms() + 600_000,
        };

        refresh_account_session(&mut session, &store).unwrap();
        server.join().unwrap();
        assert_eq!(session.access_token, "access-new");
        assert_eq!(session.refresh_token, "refresh-new");
        let persisted = store.load(DESKTOP_ACCOUNT_SESSION_KEY).unwrap().unwrap();
        let persisted: DesktopAccountSession = serde_json::from_slice(&persisted).unwrap();
        assert_eq!(persisted.access_token, "access-new");
        assert_eq!(persisted.refresh_token, "refresh-new");
    }
}
