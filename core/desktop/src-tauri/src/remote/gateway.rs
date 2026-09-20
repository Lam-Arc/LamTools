use std::{
    collections::{HashMap, HashSet},
    io::{self, Cursor, Read, Write},
    net::{IpAddr, Shutdown, SocketAddr, TcpListener, TcpStream},
    str::FromStr,
    sync::{
        atomic::{AtomicBool, AtomicU64, Ordering},
        mpsc, Arc, Mutex,
    },
    thread::{self, JoinHandle},
    time::Duration,
};

use base64::Engine;
use getrandom::fill as fill_random;
use serde::{Deserialize, Serialize};
use sha1::{Digest, Sha1};
use url::Url;

use super::{
    diagnostics::trace,
    identity::{load_or_create_account_identity, load_or_create_identity, DeviceIdentity},
    lan::{LanAdvertisement, LanPublisher},
    pairing::{PairingCodePayload, PairingManager, PairingRedeemRequest, TrustedPeerSummary},
    relay::{PairingRegistration, RelayClient, RelayConfig},
    secure_store::{
        DesktopAccountSession, PlatformSecureStore, SecureStore, DESKTOP_ACCOUNT_SESSION_KEY,
    },
    tunnel::{
        TunnelCodec, TunnelFrame, TunnelStreamDecoder, MAX_CHUNK_PAYLOAD_BYTES,
        MAX_MESSAGE_PAYLOAD_BYTES,
    },
    REMOTE_PROTOCOL, REMOTE_PROTOCOL_VERSION,
};

const DEFAULT_BIND_HOST: &str = "0.0.0.0";
const MAX_REQUEST_HEAD_BYTES: usize = 64 * 1024;
const MAX_REQUEST_BODY_BYTES: usize = 8 * 1024 * 1024;
const MAX_TUNNEL_WS_FRAME_BYTES: u64 = 4 * 1024 * 1024;
const MAX_TUNNEL_WS_MESSAGE_BYTES: usize = 4 * 1024 * 1024;
// Core app-server snapshots can legitimately be much larger than one
// browser-sized WebSocket frame. The tunnel layer still splits the logical
// message into small authenticated envelopes before it reaches the mobile
// client.
const MAX_CORE_WS_FRAME_BYTES: u64 = 128 * 1024 * 1024;
const MAX_CORE_WS_MESSAGE_BYTES: usize = 128 * 1024 * 1024;
const WS_GUID: &str = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11";
const GATEWAY_ENABLED_STORAGE_KEY: &str = "gateway-enabled-v1";

#[derive(Clone, Default, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GatewayStartOptions {
    /// Defaults to all interfaces.  Only the encrypted Noise tunnel is
    /// accepted from non-loopback peers; Core itself remains loopback-only.
    pub bind_host: Option<String>,
    /// `0` chooses an available port.
    pub port: Option<u16>,
    /// Filled by RemoteGatewayManager from the system secure store. It is
    /// skipped by Tauri deserialization so tokens cannot be supplied as
    /// ordinary start options or persisted in frontend state.
    #[serde(skip)]
    pub(crate) relay_config: RelayConfig,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct GatewayStatus {
    pub enabled: bool,
    pub state: String,
    pub bind_addr: Option<String>,
    pub port: Option<u16>,
    pub device_id: Option<String>,
    pub public_key: Option<String>,
    pub active_connections: u64,
    pub trusted_devices: Vec<TrustedPeerSummary>,
    pub relay_configured: bool,
    pub relay_connected: bool,
    pub relay_reconnects: u64,
    pub last_error: Option<String>,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DesktopAccountStatus {
    pub base_url: String,
    pub server_id: String,
    pub username: String,
    pub node_id: String,
    pub access_expires_at_ms: i64,
    pub refresh_expires_at_ms: i64,
}

/// Public portion of the stable desktop Node identity. The private Noise key
/// never crosses the Tauri boundary.
#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct NodeIdentityStatus {
    pub node_id: String,
    pub public_key: String,
}

impl Default for GatewayStatus {
    fn default() -> Self {
        Self {
            enabled: false,
            state: "disabled".to_string(),
            bind_addr: None,
            port: None,
            device_id: None,
            public_key: None,
            active_connections: 0,
            trusted_devices: Vec::new(),
            relay_configured: false,
            relay_connected: false,
            relay_reconnects: 0,
            last_error: None,
        }
    }
}

struct GatewayRuntime {
    stop: Arc<AtomicBool>,
    active_connections: Arc<AtomicU64>,
    listener_addr: SocketAddr,
    join: Mutex<Option<JoinHandle<()>>>,
    core_api_base: String,
    pairings: Arc<PairingManager>,
    advertised_host: String,
    lan_publisher: Option<LanPublisher>,
    relay_client: Option<RelayClient>,
}

/// A secure HTTP/WebSocket gateway for the local Core server.
///
/// The gateway never binds Core itself and never interprets App Server event
/// payloads.  It only authenticates a trusted peer, proxies REST bytes, and
/// forwards WebSocket frames unchanged.
pub struct RemoteGateway {
    identity: DeviceIdentity,
    runtime: GatewayRuntime,
}

impl RemoteGateway {
    pub fn start(
        core_api_base: &str,
        identity: DeviceIdentity,
        pairings: Arc<PairingManager>,
        options: GatewayStartOptions,
    ) -> Result<Self, String> {
        let core = parse_loopback_http_base(core_api_base)?;
        let bind_host = options.bind_host.as_deref().unwrap_or(DEFAULT_BIND_HOST);
        let bind_ip = IpAddr::from_str(bind_host)
            .map_err(|_| format!("gateway bind host is not an IP address: {bind_host}"))?;
        let listener = TcpListener::bind(SocketAddr::new(bind_ip, options.port.unwrap_or(0)))
            .map_err(|error| format!("无法启动手机控制网关：{error}"))?;
        listener
            .set_nonblocking(true)
            .map_err(|error| format!("无法配置手机控制网关：{error}"))?;
        let listener_addr = listener
            .local_addr()
            .map_err(|error| format!("无法读取手机控制网关端口：{error}"))?;
        let stop = Arc::new(AtomicBool::new(false));
        let active_connections = Arc::new(AtomicU64::new(0));
        let advertised_host = if bind_ip.is_loopback() {
            bind_ip.to_string()
        } else {
            local_ip_address::local_ip()
                .map_err(|error| format!("无法确定局域网地址：{error}"))?
                .to_string()
        };
        let lan_publisher = if bind_ip.is_loopback() {
            None
        } else {
            Some(LanPublisher::start(
                &LanAdvertisement::new(identity.device_id.clone(), listener_addr.port()),
                &advertised_host,
            )?)
        };
        let relay_client = RelayClient::start(
            options.relay_config,
            identity.device_id.clone(),
            listener_addr.port(),
        )?;
        let runtime = GatewayRuntime {
            stop: stop.clone(),
            active_connections: active_connections.clone(),
            listener_addr,
            join: Mutex::new(None),
            core_api_base: core.normalized,
            pairings,
            advertised_host: advertised_host.clone(),
            lan_publisher,
            relay_client,
        };

        let thread_runtime = ListenerRuntime {
            listener,
            stop,
            active_connections,
            core_host: core.host,
            core_port: core.port,
            core_api_base: runtime.core_api_base.clone(),
            listener_addr,
            pairings: runtime.pairings.clone(),
            identity: identity.clone(),
            advertised_host: advertised_host.clone(),
        };
        let join = thread::Builder::new()
            .name("lamtools-remote-gateway".to_string())
            .spawn(move || thread_runtime.run())
            .map_err(|error| format!("无法启动手机控制网关线程：{error}"))?;
        *runtime
            .join
            .lock()
            .map_err(|_| "gateway state lock failed".to_string())? = Some(join);
        Ok(Self { identity, runtime })
    }

    pub fn status(&self) -> GatewayStatus {
        let relay = self
            .runtime
            .relay_client
            .as_ref()
            .map(RelayClient::status)
            .unwrap_or_default();
        GatewayStatus {
            enabled: true,
            state: if self.runtime.stop.load(Ordering::SeqCst) {
                "stopping".to_string()
            } else {
                "running".to_string()
            },
            bind_addr: Some(self.runtime.listener_addr.ip().to_string()),
            port: Some(self.runtime.listener_addr.port()),
            device_id: Some(self.identity.device_id.clone()),
            public_key: Some(self.identity.public_key.clone()),
            active_connections: self.runtime.active_connections.load(Ordering::Relaxed),
            trusted_devices: self.runtime.pairings.trusted_devices().unwrap_or_default(),
            relay_configured: relay.configured,
            relay_connected: relay.connected,
            relay_reconnects: relay.reconnects,
            last_error: relay.last_error,
        }
    }

    pub fn pairing_create(&self) -> Result<PairingCodePayload, String> {
        let gateway_url = format!(
            "ws://{}:{}/_lamtools/tunnel",
            self.runtime.advertised_host,
            self.runtime.listener_addr.port()
        );
        let mut pairing = self.runtime.pairings.create(&gateway_url)?;
        if let Some(relay) = self.runtime.relay_client.as_ref() {
            pairing.relay_url = Some(relay.endpoint().to_string());
            relay.register_pairing(PairingRegistration::from(&pairing));
        }
        Ok(pairing)
    }

    pub fn revoke_device(&self, device_id: &str) -> Result<bool, String> {
        self.runtime.pairings.revoke(device_id)
    }

    pub fn stop(&self) -> Result<(), String> {
        if self.runtime.stop.swap(true, Ordering::SeqCst) {
            return Ok(());
        }
        // Wake the non-blocking accept loop immediately.
        let _ = TcpStream::connect(self.runtime.listener_addr);
        if let Some(join) = self
            .runtime
            .join
            .lock()
            .map_err(|_| "gateway state lock failed".to_string())?
            .take()
        {
            join.join()
                .map_err(|_| "gateway thread did not exit cleanly".to_string())?;
        }
        if let Some(publisher) = self.runtime.lan_publisher.as_ref() {
            publisher.stop();
        }
        if let Some(relay) = self.runtime.relay_client.as_ref() {
            relay.stop();
        }
        Ok(())
    }
}

impl Drop for RemoteGateway {
    fn drop(&mut self) {
        let _ = self.stop();
    }
}

struct ListenerRuntime {
    listener: TcpListener,
    stop: Arc<AtomicBool>,
    active_connections: Arc<AtomicU64>,
    core_host: String,
    core_port: u16,
    core_api_base: String,
    listener_addr: SocketAddr,
    pairings: Arc<PairingManager>,
    identity: DeviceIdentity,
    advertised_host: String,
}

impl ListenerRuntime {
    fn run(self) {
        while !self.stop.load(Ordering::SeqCst) {
            match self.listener.accept() {
                Ok((stream, peer)) => {
                    let _ = stream.set_nonblocking(false);
                    if self.stop.load(Ordering::SeqCst) {
                        let _ = stream.shutdown(Shutdown::Both);
                        break;
                    }
                    let runtime = ConnectionRuntime {
                        stream,
                        active_connections: self.active_connections.clone(),
                        core_host: self.core_host.clone(),
                        core_port: self.core_port,
                        core_api_base: self.core_api_base.clone(),
                        listener_addr: self.listener_addr,
                        pairings: self.pairings.clone(),
                        identity: self.identity.clone(),
                        advertised_host: self.advertised_host.clone(),
                        peer,
                    };
                    self.active_connections.fetch_add(1, Ordering::Relaxed);
                    thread::spawn(move || {
                        runtime.run();
                    });
                }
                Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                    thread::sleep(Duration::from_millis(30));
                }
                Err(error) => {
                    eprintln!("[lamcore] remote gateway accept failed: {error}");
                    thread::sleep(Duration::from_millis(100));
                }
            }
        }
    }
}

struct ConnectionRuntime {
    stream: TcpStream,
    active_connections: Arc<AtomicU64>,
    core_host: String,
    core_port: u16,
    core_api_base: String,
    listener_addr: SocketAddr,
    pairings: Arc<PairingManager>,
    identity: DeviceIdentity,
    advertised_host: String,
    peer: SocketAddr,
}

impl ConnectionRuntime {
    fn run(mut self) {
        trace(
            "gateway.connection_started",
            serde_json::json!({"peer": self.peer.to_string()}),
        );
        let result = self.handle();
        if let Err(error) = result {
            // Keep payloads out of logs; only the category is useful for
            // diagnostics and the frontend receives a generic connection error.
            eprintln!("[lamcore] remote gateway connection closed: {error}");
        }
        trace(
            "gateway.connection_closed",
            serde_json::json!({"peer": self.peer.to_string()}),
        );
        let _ = self.stream.shutdown(Shutdown::Both);
        self.active_connections.fetch_sub(1, Ordering::Relaxed);
    }

    fn handle(&mut self) -> Result<(), String> {
        self.stream
            .set_read_timeout(Some(Duration::from_secs(30)))
            .map_err(|error| error.to_string())?;
        self.stream
            .set_write_timeout(Some(Duration::from_secs(30)))
            .map_err(|error| error.to_string())?;
        let (request, remainder) = read_http_request(&mut self.stream)?;
        if is_websocket_upgrade(&request.headers) {
            self.handle_websocket(request, remainder)
        } else {
            self.handle_http(request)
        }
    }

    fn handle_http(&mut self, request: HttpRequest) -> Result<(), String> {
        if request.method.eq_ignore_ascii_case("OPTIONS") {
            return write_cors_preflight_response(&mut self.stream);
        }
        if request.target.split('?').next().unwrap_or_default() == "/_lamtools/pairing/resolve" {
            return self.handle_pairing_resolve(request);
        }
        if request.target.starts_with("/_lamtools/health") {
            return write_json_response(
                &mut self.stream,
                200,
                &serde_json::json!({
                    "status": "ok",
                    "service": "lamtools-remote-gateway",
                    "protocolVersion": 1,
                }),
            );
        }
        if !self.peer.ip().is_loopback() {
            return write_json_response(
                &mut self.stream,
                426,
                &serde_json::json!({"error": "encrypted tunnel required"}),
            );
        }
        if request.target.starts_with("/_lamtools/status") {
            if let Err(error) = self.require_auth(&request) {
                return write_json_response(
                    &mut self.stream,
                    401,
                    &serde_json::json!({"error": error}),
                );
            }
            return write_json_response(
                &mut self.stream,
                200,
                &serde_json::json!({
                    "status": "ok",
                    "deviceId": self.pairings.device_id(),
                    "trustedDevices": self.pairings.trusted_devices().unwrap_or_default(),
                }),
            );
        }
        if let Some(pairing_id) = pairing_id_from_target(&request.target) {
            return self.handle_pairing_http(&pairing_id, request);
        }
        if let Err(error) = self.require_auth(&request) {
            return write_json_response(
                &mut self.stream,
                401,
                &serde_json::json!({"error": error}),
            );
        }
        proxy_http_request(
            &mut self.stream,
            request,
            &self.core_host,
            self.core_port,
            &self.core_api_base,
        )
    }

    fn handle_pairing_resolve(&mut self, request: HttpRequest) -> Result<(), String> {
        if !request.method.eq_ignore_ascii_case("POST") {
            return write_json_response(
                &mut self.stream,
                405,
                &serde_json::json!({"error": "pairing resolve requires POST"}),
            );
        }
        #[derive(Deserialize)]
        struct PairingResolveRequest {
            code: String,
        }
        let payload: PairingResolveRequest = serde_json::from_slice(&request.body)
            .map_err(|_| "配对解析请求格式无效".to_string())?;
        let gateway_url = self.gateway_url();
        match self.pairings.resolve(&payload.code, &gateway_url) {
            Ok(pairing) => write_json_response(&mut self.stream, 200, &pairing),
            Err(error) => {
                let status = if error == "配对码必须是六位数字" {
                    400
                } else {
                    404
                };
                write_json_response(
                    &mut self.stream,
                    status,
                    &serde_json::json!({"error": error}),
                )
            }
        }
    }

    fn handle_pairing_http(
        &mut self,
        pairing_id: &str,
        request: HttpRequest,
    ) -> Result<(), String> {
        if request.method.eq_ignore_ascii_case("POST")
            && request
                .target
                .split('?')
                .next()
                .unwrap_or_default()
                .ends_with("/redeem")
        {
            let payload: PairingRedeemRequest = serde_json::from_slice(&request.body)
                .map_err(|_| "配对请求格式无效".to_string())?;
            let gateway_url = self.gateway_url();
            return match self.pairings.redeem(pairing_id, payload, &gateway_url) {
                Ok(redemption) => write_json_response(&mut self.stream, 200, &redemption),
                Err(error) => {
                    write_json_response(&mut self.stream, 400, &serde_json::json!({"error": error}))
                }
            };
        }
        write_json_response(
            &mut self.stream,
            404,
            &serde_json::json!({"error": "pairing endpoint not found"}),
        )
    }

    fn handle_websocket(&mut self, request: HttpRequest, remainder: Vec<u8>) -> Result<(), String> {
        let path = request.target.split('?').next().unwrap_or_default();
        if path != "/_lamtools/tunnel" {
            return write_json_response(
                &mut self.stream,
                404,
                &serde_json::json!({"error": "secure tunnel endpoint required"}),
            );
        }
        self.handle_secure_tunnel(request, remainder)
    }

    fn handle_secure_tunnel(
        &mut self,
        request: HttpRequest,
        remainder: Vec<u8>,
    ) -> Result<(), String> {
        let key = request
            .headers
            .get("sec-websocket-key")
            .ok_or_else(|| "websocket key is missing".to_string())?;
        let response = format!(
            "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: {}\r\n\r\n",
            websocket_accept(key)
        );
        self.stream
            .write_all(response.as_bytes())
            .map_err(|error| error.to_string())?;
        let pairing_id = query_value(&request.target, "pairing").map(str::to_string);
        // A Relay ticket has already been authorized by the server before it
        // reaches this loopback bridge. The marker is intentionally scoped to
        // a per-tunnel UUID supplied by this desktop's RelayClient; it is not
        // a reusable application credential.
        let relay_tunnel = query_value(&request.target, "relay_tunnel").map(str::to_string);
        if let Some(id) = pairing_id.as_deref() {
            if !self.pairings.pairing_exists(id)? {
                return Err("配对已失效或不存在".to_string());
            }
        }
        let params = "Noise_XX_25519_ChaChaPoly_BLAKE2b"
            .parse()
            .map_err(|error| format!("Noise parameters are invalid: {error}"))?;
        let builder = snow::Builder::new(params)
            .local_private_key(&self.identity.private_key)
            .prologue(b"LamTools Remote Tunnel v1");
        let mut noise = builder
            .build_responder()
            .map_err(|error| error.to_string())?;
        let mut client = BufferedStream::new(
            self.stream.try_clone().map_err(|e| e.to_string())?,
            remainder,
        );
        let mut handshake_buffer = vec![0_u8; 65_535];

        let first = read_tunnel_ws_payload(&mut client, |payload| {
            write_ws_pong(&mut self.stream, payload, false)
        })
        .map_err(|error| error.to_string())?;
        noise
            .read_message(&first, &mut handshake_buffer)
            .map_err(|error| format!("Noise handshake rejected: {error}"))?;
        let second_len = noise
            .write_message(&[], &mut handshake_buffer)
            .map_err(|error| format!("Noise handshake failed: {error}"))?;
        write_ws_binary(&mut self.stream, &handshake_buffer[..second_len])?;
        let third = read_tunnel_ws_payload(&mut client, |payload| {
            write_ws_pong(&mut self.stream, payload, false)
        })
        .map_err(|error| error.to_string())?;
        let auth_len = noise
            .read_message(&third, &mut handshake_buffer)
            .map_err(|error| format!("Noise authentication failed: {error}"))?;
        let remote_static = noise
            .get_remote_static()
            .ok_or_else(|| "Noise peer identity is missing".to_string())?
            .to_vec();
        let auth: TunnelAuth = serde_json::from_slice(&handshake_buffer[..auth_len])
            .map_err(|_| "tunnel authentication payload is invalid".to_string())?;
        let gateway_url = format!(
            "ws://{}:{}/_lamtools/tunnel",
            self.advertised_host,
            self.listener_addr.port()
        );
        let (access_token, ack, relay_authorized) =
            match (pairing_id.as_deref(), relay_tunnel, auth) {
                (
                    Some(id),
                    _,
                    TunnelAuth::Pair {
                        code,
                        device_id,
                        device_name,
                        platform,
                    },
                ) => {
                    if super::identity::encode_urlsafe(&remote_static).is_empty() {
                        return Err("mobile identity is invalid".to_string());
                    }
                    let redemption = self.pairings.redeem(
                        id,
                        PairingRedeemRequest {
                            code,
                            device_id,
                            device_name,
                            platform,
                            mobile_public_key: super::identity::encode_urlsafe(&remote_static),
                        },
                        &gateway_url,
                    )?;
                    (
                        redemption.access_token.clone(),
                        protocol_ack(
                            serde_json::to_value(&redemption).map_err(|e| e.to_string())?,
                        )?,
                        false,
                    )
                }
                (
                    None,
                    Some(_),
                    TunnelAuth::Connect {
                        access_token,
                        device_id: _,
                    },
                ) => (
                    access_token,
                    protocol_ack(serde_json::json!({"status":"ok"}))?,
                    true,
                ),
                (
                    None,
                    None,
                    TunnelAuth::Connect {
                        access_token,
                        device_id,
                    },
                ) => {
                    if !self.pairings.authenticate_peer(
                        &remote_static,
                        &access_token,
                        &device_id,
                    )? {
                        return Err("device authorization was rejected".to_string());
                    }
                    (
                        access_token,
                        protocol_ack(serde_json::json!({"status":"ok"}))?,
                        false,
                    )
                }
                _ => return Err("tunnel authentication mode mismatch".to_string()),
            };
        trace(
            "gateway.tunnel_authenticated",
            serde_json::json!({
                "peer": self.peer.to_string(),
                "pairing": pairing_id.is_some(),
                "via_relay": relay_authorized,
            }),
        );
        let transport = Arc::new(Mutex::new(
            noise.into_transport_mode().map_err(|e| e.to_string())?,
        ));
        let writer = SecureTunnelWriter::new(
            self.stream.try_clone().map_err(|e| e.to_string())?,
            transport.clone(),
        );
        writer.send(&ack)?;
        // Handshake timeouts protect setup only. Once the secure tunnel is
        // established, liveness is driven by Ping/Pong; an idle application
        // must not be mistaken for a dead connection.
        client
            .stream
            .set_read_timeout(None)
            .map_err(|error| error.to_string())?;
        client
            .stream
            .set_write_timeout(None)
            .map_err(|error| error.to_string())?;
        self.bridge_secure_tunnel(client, transport, writer, access_token, relay_authorized)
    }

    fn bridge_secure_tunnel(
        &mut self,
        client: BufferedStream,
        transport: Arc<Mutex<snow::TransportState>>,
        writer: SecureTunnelWriter,
        access_token: String,
        relay_authorized: bool,
    ) -> Result<(), String> {
        let (core, core_remainder) =
            connect_core_websocket(&self.core_host, self.core_port, "/api/core/app-server")?;
        trace(
            "gateway.core_connected",
            serde_json::json!({"peer": self.peer.to_string()}),
        );
        // Both socket readers own dedicated threads. Keep them blocking and
        // wake them with Shutdown::Both during teardown. A read timeout can
        // fire after read_exact has consumed only part of a frame; retrying
        // from a fresh frame header would then interpret payload bytes as a
        // header and permanently desynchronise the WebSocket stream.
        let core_writer = Arc::new(Mutex::new(core.try_clone().map_err(|e| e.to_string())?));
        let mut core_reader =
            BufferedStream::new(core.try_clone().map_err(|e| e.to_string())?, core_remainder);
        let mobile_shutdown = client.stream.try_clone().map_err(|e| e.to_string())?;
        let pairings = self.pairings.clone();
        let token_for_reader = access_token.clone();
        let finished = Arc::new(AtomicBool::new(false));
        let (core_to_tunnel_tx, core_to_tunnel_rx) = mpsc::channel::<TunnelFrame>();
        let core_reader_finished = finished.clone();
        let core_reader_writer = core_writer.clone();
        let core_reader_thread = thread::spawn(move || {
            let mut assembler = WsMessageAssembler::with_limit(MAX_CORE_WS_MESSAGE_BYTES);
            while !core_reader_finished.load(Ordering::SeqCst)
                && (relay_authorized || pairings.authenticate(&token_for_reader).unwrap_or(false))
            {
                match read_ws_frame_limited(&mut core_reader, MAX_CORE_WS_FRAME_BYTES) {
                    Ok(Some(frame)) => {
                        if frame.masked {
                            eprintln!(
                                "[lamcore] core websocket protocol error: masked server frame"
                            );
                            break;
                        }
                        match assembler.push(frame) {
                            Ok(WsMessageEvent::Message { opcode, payload }) => {
                                if let Err(error) =
                                    queue_core_message(&core_to_tunnel_tx, opcode, payload)
                                {
                                    eprintln!("[lamcore] core reader output failed: {error}");
                                    break;
                                }
                            }
                            Ok(WsMessageEvent::Ping(payload)) => {
                                let mut stream = match core_reader_writer.lock() {
                                    Ok(stream) => stream,
                                    Err(_) => break,
                                };
                                if let Err(error) = write_ws_pong(&mut *stream, &payload, true) {
                                    eprintln!("[lamcore] core reader Pong failed: {error}");
                                    break;
                                }
                            }
                            Ok(WsMessageEvent::Pong | WsMessageEvent::Pending) => {}
                            Ok(WsMessageEvent::Close) => break,
                            Err(error) => {
                                eprintln!("[lamcore] core websocket protocol error: {error}");
                                break;
                            }
                        }
                    }
                    Ok(None) => break,
                    Err(error) => {
                        eprintln!("[lamcore] core websocket reader failed: {error}");
                        break;
                    }
                }
            }
            core_reader_finished.store(true, Ordering::SeqCst);
        });

        let client_writer_finished = finished.clone();
        let client_writer = writer.clone();
        let client_writer_thread = thread::spawn(move || {
            while !client_writer_finished.load(Ordering::SeqCst) {
                match core_to_tunnel_rx.recv_timeout(Duration::from_millis(500)) {
                    Ok(frame) => {
                        trace_gateway_frame("gateway.mobile_forwarded", "core_to_mobile", &frame);
                        if let Err(error) = client_writer.send_tunnel_frame(frame) {
                            eprintln!("[lamcore] tunnel writer failed: {error}");
                            trace(
                                "gateway.mobile_forward_failed",
                                serde_json::json!({"direction": "core_to_mobile", "error": error}),
                            );
                            break;
                        }
                    }
                    Err(mpsc::RecvTimeoutError::Timeout) => continue,
                    Err(mpsc::RecvTimeoutError::Disconnected) => break,
                }
            }
            client_writer_finished.store(true, Ordering::SeqCst);
        });

        let heartbeat_finished = finished.clone();
        let heartbeat_writer = writer.clone();
        let heartbeat_thread = thread::spawn(move || {
            while !heartbeat_finished.load(Ordering::SeqCst) {
                thread::sleep(Duration::from_secs(25));
                if heartbeat_finished.load(Ordering::SeqCst) {
                    break;
                }
                if let Err(error) = heartbeat_writer.send_ping() {
                    eprintln!("[lamcore] mobile tunnel heartbeat failed: {error}");
                    heartbeat_finished.store(true, Ordering::SeqCst);
                    break;
                }
            }
        });

        let (to_core_tx, to_core_rx) = mpsc::channel::<WsFrame>();
        let core_writer_finished = finished.clone();
        let core_writer_thread = thread::spawn(move || {
            while !core_writer_finished.load(Ordering::SeqCst) {
                match to_core_rx.recv_timeout(Duration::from_millis(500)) {
                    Ok(frame) => {
                        let mut stream = match core_writer.lock() {
                            Ok(stream) => stream,
                            Err(_) => break,
                        };
                        if let Err(error) = write_ws_frame(&mut *stream, &frame, true) {
                            eprintln!("[lamcore] core websocket writer failed: {error}");
                            break;
                        }
                    }
                    Err(mpsc::RecvTimeoutError::Timeout) => continue,
                    Err(mpsc::RecvTimeoutError::Disconnected) => break,
                }
            }
            core_writer_finished.store(true, Ordering::SeqCst);
        });

        let client_reader_finished = finished.clone();
        let client_reader_transport = transport.clone();
        let client_reader_writer = writer.clone();
        let (from_client_tx, from_client_rx) = mpsc::channel::<TunnelFrame>();
        let client_reader_thread = thread::spawn(move || {
            let mut client = client;
            let mut decoder = TunnelStreamDecoder::default();
            let mut plain = vec![0_u8; MAX_TUNNEL_WS_FRAME_BYTES as usize];
            while !client_reader_finished.load(Ordering::SeqCst) {
                let encrypted = match read_tunnel_ws_payload(&mut client, |payload| {
                    client_reader_writer
                        .send_pong(payload)
                        .map_err(io::Error::other)
                }) {
                    Ok(value) => value,
                    Err(error) => {
                        eprintln!("[lamcore] mobile tunnel reader failed: {error}");
                        break;
                    }
                };
                let read = match client_reader_transport.lock() {
                    Ok(mut transport) => match transport.read_message(&encrypted, &mut plain) {
                        Ok(read) => read,
                        Err(error) => {
                            eprintln!("[lamcore] mobile tunnel decrypt failed: {error}");
                            break;
                        }
                    },
                    Err(_) => {
                        eprintln!("[lamcore] mobile tunnel state lock failed");
                        break;
                    }
                };
                let frames = match decoder.push(&plain[..read]) {
                    Ok(frames) => frames,
                    Err(error) => {
                        eprintln!("[lamcore] mobile tunnel frame decode failed: {error}");
                        break;
                    }
                };
                for frame in frames {
                    trace_gateway_frame("gateway.mobile_received", "mobile_to_core", &frame);
                    if from_client_tx.send(frame).is_err() {
                        client_reader_finished.store(true, Ordering::SeqCst);
                        return;
                    }
                }
            }
            client_reader_finished.store(true, Ordering::SeqCst);
        });

        let cancelled = Arc::new(Mutex::new(HashSet::<String>::new()));
        let mut bridge_error = None;
        while !finished.load(Ordering::SeqCst)
            && (relay_authorized || self.pairings.authenticate(&access_token)?)
        {
            let frame = match from_client_rx.recv_timeout(Duration::from_millis(500)) {
                Ok(frame) => frame,
                Err(mpsc::RecvTimeoutError::Timeout) => continue,
                Err(mpsc::RecvTimeoutError::Disconnected) => {
                    eprintln!("[lamcore] bridge input channel closed");
                    break;
                }
            };
            match frame.frame_type.as_str() {
                frame_type @ ("rpc.data" | "control.data" | "event.data")
                    if (frame_type == "rpc.data" && frame.stream_id == "rpc")
                        || (frame_type == "control.data" && frame.stream_id == "control")
                        || (frame_type == "event.data" && frame.stream_id == "event") =>
                {
                    let payload = frame.payload.unwrap_or_default().into_bytes();
                    let payload_bytes = payload.len();
                    let request_id = frame
                        .request_id
                        .clone()
                        .or_else(|| rpc_metadata(&payload).0);
                    let method = rpc_metadata(&payload).1;
                    if let Err(error) = to_core_tx.send(WsFrame {
                        fin: true,
                        opcode: 1,
                        masked: true,
                        payload,
                    }) {
                        bridge_error = Some(error.to_string());
                        trace(
                            "gateway.core_forward_failed",
                            serde_json::json!({
                                "direction": "mobile_to_core",
                                "request_id": &request_id,
                                "method": &method,
                                "error": error.to_string(),
                            }),
                        );
                        break;
                    }
                    trace(
                        "gateway.core_forwarded",
                        serde_json::json!({
                            "direction": "mobile_to_core",
                            "request_id": &request_id,
                            "method": &method,
                            "bytes": payload_bytes,
                        }),
                    );
                }
                "binary.data" if frame.stream_id == "binary" => {
                    let payload = match base64::engine::general_purpose::STANDARD
                        .decode(frame.payload.unwrap_or_default())
                    {
                        Ok(payload) => payload,
                        Err(_) => {
                            bridge_error = Some("binary tunnel payload is invalid".to_string());
                            break;
                        }
                    };
                    if let Err(error) = to_core_tx.send(WsFrame {
                        fin: true,
                        opcode: 2,
                        masked: true,
                        payload,
                    }) {
                        bridge_error = Some(error.to_string());
                        break;
                    }
                }
                "http.request" => {
                    let request_id = match frame.request_id {
                        Some(request_id) => request_id,
                        None => {
                            bridge_error = Some("HTTP tunnel request id is missing".to_string());
                            break;
                        }
                    };
                    let payload: TunnelHttpRequest =
                        match serde_json::from_str(frame.payload.as_deref().unwrap_or("{}")) {
                            Ok(payload) => payload,
                            Err(_) => {
                                bridge_error = Some("HTTP tunnel request is invalid".to_string());
                                break;
                            }
                        };
                    let writer = writer.clone();
                    let cancelled = cancelled.clone();
                    let core_host = self.core_host.clone();
                    let core_port = self.core_port;
                    let stream_id = frame.stream_id.clone();
                    thread::spawn(move || {
                        let response = match core_http_request(&core_host, core_port, payload) {
                            Ok(response) => response,
                            Err(error) => {
                                eprintln!("[lamcore] remote HTTP proxy failed: {error}");
                                tunnel_http_error_response(502, "Core request failed")
                            }
                        };
                        let was_cancelled = cancelled
                            .lock()
                            .map(|mut set| set.remove(&request_id))
                            .unwrap_or(true);
                        if was_cancelled {
                            return;
                        }
                        let Ok(encoded) = serde_json::to_string(&response) else {
                            return;
                        };
                        let _ = writer.send_frame(
                            "http.response",
                            &stream_id,
                            Some(request_id),
                            Some(encoded),
                        );
                    });
                }
                "http.cancel" => {
                    if let Some(request_id) = frame.request_id {
                        if let Ok(mut set) = cancelled.lock() {
                            set.insert(request_id);
                        }
                    }
                }
                _ => {
                    bridge_error = Some("unsupported tunnel frame".to_string());
                    break;
                }
            }
        }
        finished.store(true, Ordering::SeqCst);
        let _ = core.shutdown(Shutdown::Both);
        let _ = mobile_shutdown.shutdown(Shutdown::Both);
        let _ = client_reader_thread.join();
        let _ = core_reader_thread.join();
        let _ = core_writer_thread.join();
        let _ = client_writer_thread.join();
        let _ = heartbeat_thread.join();
        if let Some(error) = bridge_error {
            return Err(error);
        }
        Ok(())
    }

    fn require_auth(&self, request: &HttpRequest) -> Result<(), String> {
        let token = self.auth_token_from_request(request)?;
        if self.pairings.authenticate(&token).unwrap_or(false) {
            return Ok(());
        }
        Err("unauthorized".to_string())
    }

    fn auth_token_from_request(&self, request: &HttpRequest) -> Result<String, String> {
        request
            .headers
            .get("authorization")
            .and_then(|value| value.strip_prefix("Bearer "))
            .or_else(|| query_value(&request.target, "token"))
            .map(str::to_string)
            .ok_or_else(|| "unauthorized".to_string())
    }

    fn gateway_url(&self) -> String {
        // The listener address is intentionally not included in the
        // connection runtime.  Pairing over HTTP is only used by a mobile
        // client that already knows the endpoint from the resolved pairing;
        // value is replaced by the manager command for desktop-created flows.
        format!(
            "ws://{}:{}/_lamtools/tunnel",
            self.advertised_host,
            self.listener_addr.port()
        )
    }
}

#[derive(Deserialize)]
#[serde(tag = "mode", rename_all = "snake_case")]
enum TunnelAuth {
    Pair {
        code: String,
        device_id: String,
        #[serde(default)]
        device_name: String,
        #[serde(default)]
        platform: String,
    },
    Connect {
        access_token: String,
        #[serde(default)]
        device_id: String,
    },
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct TunnelHttpRequest {
    method: String,
    path: String,
    #[serde(default)]
    headers: HashMap<String, String>,
    #[serde(default)]
    body: String,
}

#[derive(Serialize)]
struct TunnelHttpResponse {
    status: u16,
    headers: HashMap<String, String>,
    body: String,
}

fn tunnel_http_error_response(status: u16, message: &str) -> TunnelHttpResponse {
    let body = serde_json::to_vec(&serde_json::json!({ "error": message })).unwrap_or_default();
    TunnelHttpResponse {
        status,
        headers: HashMap::from([(
            "content-type".to_string(),
            "application/json; charset=utf-8".to_string(),
        )]),
        body: base64::engine::general_purpose::STANDARD.encode(body),
    }
}

#[derive(Clone)]
struct SecureTunnelWriter {
    stream: Arc<Mutex<TcpStream>>,
    transport: Arc<Mutex<snow::TransportState>>,
    sequence: Arc<AtomicU64>,
    send_guard: Arc<Mutex<()>>,
}

impl SecureTunnelWriter {
    fn new(stream: TcpStream, transport: Arc<Mutex<snow::TransportState>>) -> Self {
        Self {
            stream: Arc::new(Mutex::new(stream)),
            transport,
            sequence: Arc::new(AtomicU64::new(0)),
            send_guard: Arc::new(Mutex::new(())),
        }
    }

    fn send(&self, plaintext: &[u8]) -> Result<(), String> {
        let _guard = self
            .send_guard
            .lock()
            .map_err(|_| "tunnel send lock failed".to_string())?;
        self.send_locked(plaintext)
    }

    fn send_locked(&self, plaintext: &[u8]) -> Result<(), String> {
        for chunk in plaintext.chunks(60_000) {
            let mut encrypted = vec![0_u8; chunk.len() + 32];
            let written = self
                .transport
                .lock()
                .map_err(|_| "Noise state lock failed".to_string())?
                .write_message(chunk, &mut encrypted)
                .map_err(|_| "tunnel encryption failed".to_string())?;
            write_ws_binary(
                &mut *self
                    .stream
                    .lock()
                    .map_err(|_| "tunnel writer lock failed".to_string())?,
                &encrypted[..written],
            )?;
        }
        Ok(())
    }

    fn send_pong(&self, payload: &[u8]) -> Result<(), String> {
        let mut stream = self
            .stream
            .lock()
            .map_err(|_| "tunnel writer lock failed".to_string())?;
        write_ws_pong(&mut *stream, payload, false).map_err(|error| error.to_string())
    }

    fn send_ping(&self) -> Result<(), String> {
        let mut stream = self
            .stream
            .lock()
            .map_err(|_| "tunnel writer lock failed".to_string())?;
        write_ws_control(&mut *stream, 9, &[]).map_err(|error| error.to_string())
    }

    fn send_frame(
        &self,
        frame_type: &str,
        stream_id: &str,
        request_id: Option<String>,
        payload: Option<String>,
    ) -> Result<(), String> {
        let mut frame = TunnelFrame::new(frame_type, stream_id, 0);
        frame.request_id = request_id;
        frame.payload = payload;
        self.send_tunnel_frame(frame)
    }

    fn send_tunnel_frame(&self, mut frame: TunnelFrame) -> Result<(), String> {
        let _guard = self
            .send_guard
            .lock()
            .map_err(|_| "tunnel send lock failed".to_string())?;
        let payload = frame.payload.take();
        let Some(payload) = payload else {
            return self.send_tunnel_frame_locked(frame);
        };
        if payload.len() <= MAX_CHUNK_PAYLOAD_BYTES {
            frame.payload = Some(payload);
            return self.send_tunnel_frame_locked(frame);
        }
        if payload.len() > MAX_MESSAGE_PAYLOAD_BYTES {
            return Err("tunnel message is too large".to_string());
        }

        // Keep every JSON-line envelope well below the 4 MiB wire limit. The
        // message id is derived from the first sequence that will be used and
        // is therefore unique for this authenticated tunnel.
        let message_id = format!(
            "message-{}",
            self.sequence.load(Ordering::Relaxed).saturating_add(1)
        );
        let chunks = split_tunnel_payload(&payload);
        for (index, chunk) in chunks.iter().enumerate() {
            let mut chunk_frame = frame.clone();
            chunk_frame.payload = Some((*chunk).to_string());
            chunk_frame.message_id = Some(message_id.clone());
            chunk_frame.chunk_index = Some(index as u32);
            chunk_frame.chunk_final = Some(index + 1 == chunks.len());
            self.send_tunnel_frame_locked(chunk_frame)?;
        }
        Ok(())
    }

    fn send_tunnel_frame_locked(&self, mut frame: TunnelFrame) -> Result<(), String> {
        frame.sequence = self.sequence.fetch_add(1, Ordering::SeqCst) + 1;
        let encoded = TunnelCodec::encode(&frame)?;
        self.send_locked(&encoded)
    }
}

#[derive(Clone)]
pub struct RemoteGatewayManager {
    inner: Arc<Mutex<ManagerState>>,
}

struct ManagerState {
    gateway: Option<RemoteGateway>,
    identity: Option<DeviceIdentity>,
    pairings: Option<Arc<PairingManager>>,
    secure_store: Arc<dyn SecureStore>,
    status: GatewayStatus,
}

impl Default for RemoteGatewayManager {
    fn default() -> Self {
        Self {
            inner: Arc::new(Mutex::new(ManagerState {
                gateway: None,
                identity: None,
                pairings: None,
                secure_store: Arc::new(PlatformSecureStore),
                status: GatewayStatus::default(),
            })),
        }
    }
}

impl RemoteGatewayManager {
    #[cfg(test)]
    fn with_secure_store(secure_store: Arc<dyn SecureStore>) -> Self {
        Self {
            inner: Arc::new(Mutex::new(ManagerState {
                gateway: None,
                identity: None,
                pairings: None,
                secure_store,
                status: GatewayStatus::default(),
            })),
        }
    }

    pub fn start(
        &self,
        core_api_base: &str,
        options: GatewayStartOptions,
    ) -> Result<GatewayStatus, String> {
        let mut state = self
            .inner
            .lock()
            .map_err(|_| "gateway state lock failed".to_string())?;
        if let Some(gateway) = state.gateway.as_ref() {
            return Ok(gateway.status());
        }
        let account = load_account_session(state.secure_store.as_ref())?;
        let mut options = options;
        options.relay_config =
            RelayConfig::from_account_session(account.as_ref(), state.secure_store.clone())?;
        let identity = match account.as_ref() {
            Some(account) => load_or_create_account_identity(
                state.secure_store.as_ref(),
                &account.server_id,
                &account.username,
            )?,
            None => load_or_create_identity(state.secure_store.as_ref())?,
        };
        let pairings = Arc::new(PairingManager::with_secure_store(
            identity.clone(),
            state.secure_store.clone(),
        )?);
        let gateway =
            RemoteGateway::start(core_api_base, identity.clone(), pairings.clone(), options)?;
        let status = gateway.status();
        state.secure_store.save(GATEWAY_ENABLED_STORAGE_KEY, b"1")?;
        state.identity = Some(identity);
        state.pairings = Some(pairings);
        state.status = status.clone();
        state.gateway = Some(gateway);
        Ok(status)
    }

    pub fn stop(&self) -> Result<GatewayStatus, String> {
        let status = self.shutdown()?;
        self.inner
            .lock()
            .map_err(|_| "gateway state lock failed".to_string())?
            .secure_store
            .save(GATEWAY_ENABLED_STORAGE_KEY, b"0")?;
        Ok(status)
    }

    pub fn shutdown(&self) -> Result<GatewayStatus, String> {
        let mut state = self
            .inner
            .lock()
            .map_err(|_| "gateway state lock failed".to_string())?;
        if let Some(gateway) = state.gateway.take() {
            gateway.stop()?;
        }
        state.pairings = None;
        state.identity = None;
        state.status = GatewayStatus::default();
        Ok(state.status.clone())
    }

    pub fn auto_start_enabled(&self) -> Result<bool, String> {
        let state = self
            .inner
            .lock()
            .map_err(|_| "gateway state lock failed".to_string())?;
        Ok(matches!(
            state
                .secure_store
                .load(GATEWAY_ENABLED_STORAGE_KEY)?
                .as_deref(),
            Some(b"1")
        ))
    }

    pub fn status(&self) -> Result<GatewayStatus, String> {
        let state = self
            .inner
            .lock()
            .map_err(|_| "gateway state lock failed".to_string())?;
        Ok(state
            .gateway
            .as_ref()
            .map(RemoteGateway::status)
            .unwrap_or_else(|| state.status.clone()))
    }

    pub fn pairing_create(&self) -> Result<PairingCodePayload, String> {
        self.inner
            .lock()
            .map_err(|_| "gateway state lock failed".to_string())?
            .gateway
            .as_ref()
            .ok_or_else(|| "请先开启手机控制".to_string())?
            .pairing_create()
    }

    pub fn revoke_device(&self, device_id: &str) -> Result<bool, String> {
        self.inner
            .lock()
            .map_err(|_| "gateway state lock failed".to_string())?
            .gateway
            .as_ref()
            .ok_or_else(|| "手机控制未开启".to_string())?
            .revoke_device(device_id)
    }

    pub fn account_status(&self) -> Result<Option<DesktopAccountStatus>, String> {
        let state = self
            .inner
            .lock()
            .map_err(|_| "gateway state lock failed".to_string())?;
        let Some(session) = load_account_session(state.secure_store.as_ref())? else {
            return Ok(None);
        };
        Ok(Some(DesktopAccountStatus {
            base_url: session.base_url,
            server_id: session.server_id,
            username: session.username,
            node_id: session.node_id,
            access_expires_at_ms: session.access_expires_at_ms,
            refresh_expires_at_ms: session.refresh_expires_at_ms,
        }))
    }

    pub fn save_account_session(
        &self,
        session: DesktopAccountSession,
    ) -> Result<DesktopAccountStatus, String> {
        if !session.is_valid() {
            return Err("桌面账号会话无效，请重新登录服务器".to_string());
        }
        let mut state = self
            .inner
            .lock()
            .map_err(|_| "gateway state lock failed".to_string())?;
        if let Some(gateway) = state.gateway.take() {
            gateway.stop()?;
            state.pairings = None;
            state.identity = None;
            state.status = GatewayStatus::default();
        }
        state.secure_store.save(
            DESKTOP_ACCOUNT_SESSION_KEY,
            &serde_json::to_vec(&session).map_err(|error| error.to_string())?,
        )?;
        Ok(DesktopAccountStatus {
            base_url: session.base_url,
            server_id: session.server_id,
            username: session.username,
            node_id: session.node_id,
            access_expires_at_ms: session.access_expires_at_ms,
            refresh_expires_at_ms: session.refresh_expires_at_ms,
        })
    }

    pub fn account_logout(&self) -> Result<(), String> {
        let mut state = self
            .inner
            .lock()
            .map_err(|_| "gateway state lock failed".to_string())?;
        if let Some(gateway) = state.gateway.take() {
            gateway.stop()?;
            state.pairings = None;
            state.identity = None;
            state.status = GatewayStatus::default();
        }
        state.secure_store.delete(DESKTOP_ACCOUNT_SESSION_KEY)
    }

    pub fn node_identity(&self) -> Result<NodeIdentityStatus, String> {
        let state = self
            .inner
            .lock()
            .map_err(|_| "gateway state lock failed".to_string())?;
        let identity = match state.identity.clone() {
            Some(identity) => identity,
            None => load_or_create_identity(state.secure_store.as_ref())?,
        };
        Ok(NodeIdentityStatus {
            node_id: identity.device_id,
            public_key: identity.public_key,
        })
    }

    pub fn node_identity_for_account(
        &self,
        server_id: &str,
        username: &str,
    ) -> Result<NodeIdentityStatus, String> {
        if server_id.trim().is_empty() || username.trim().is_empty() {
            return Err("服务器与账号不能为空".to_string());
        }
        let state = self
            .inner
            .lock()
            .map_err(|_| "gateway state lock failed".to_string())?;
        let identity =
            load_or_create_account_identity(state.secure_store.as_ref(), server_id, username)?;
        Ok(NodeIdentityStatus {
            node_id: identity.device_id,
            public_key: identity.public_key,
        })
    }
}

fn load_account_session(store: &dyn SecureStore) -> Result<Option<DesktopAccountSession>, String> {
    let Some(bytes) = store.load(DESKTOP_ACCOUNT_SESSION_KEY)? else {
        return Ok(None);
    };
    let session = serde_json::from_slice::<DesktopAccountSession>(&bytes)
        .map_err(|error| format!("桌面账号会话无效：{error}"))?;
    if !session.is_valid() {
        return Err("桌面账号会话无效，请重新登录服务器".to_string());
    }
    Ok(Some(session))
}

#[derive(Debug)]
struct CoreBase {
    normalized: String,
    host: String,
    port: u16,
}

fn parse_loopback_http_base(value: &str) -> Result<CoreBase, String> {
    let url = Url::parse(value).map_err(|_| "Core API 地址无效".to_string())?;
    if url.scheme() != "http" {
        return Err("Core API 必须使用 localhost HTTP".to_string());
    }
    let host = url
        .host_str()
        .ok_or_else(|| "Core API 地址缺少主机".to_string())?;
    if host != "127.0.0.1" && host != "localhost" && host != "[::1]" && host != "::1" {
        return Err("RemoteGateway 只允许代理 loopback Core".to_string());
    }
    let port = url
        .port_or_known_default()
        .ok_or_else(|| "Core API 地址缺少端口".to_string())?;
    let normalized = format!("http://{host}:{port}");
    Ok(CoreBase {
        normalized,
        host: host.trim_matches(['[', ']']).to_string(),
        port,
    })
}

#[derive(Debug)]
struct HttpRequest {
    method: String,
    target: String,
    headers: HashMap<String, String>,
    body: Vec<u8>,
}

fn read_http_request(stream: &mut TcpStream) -> Result<(HttpRequest, Vec<u8>), String> {
    let (head, mut remainder) = read_http_head(stream)?;
    let text = std::str::from_utf8(&head).map_err(|_| "HTTP 请求头不是 UTF-8".to_string())?;
    let mut lines = text.split("\r\n");
    let request_line = lines.next().ok_or_else(|| "HTTP 请求行缺失".to_string())?;
    let mut request_parts = request_line.split_whitespace();
    let method = request_parts.next().unwrap_or_default().to_string();
    let target = request_parts.next().unwrap_or_default().to_string();
    let version = request_parts.next().unwrap_or_default().to_string();
    if method.is_empty() || target.is_empty() || !version.starts_with("HTTP/") {
        return Err("HTTP 请求格式无效".to_string());
    }
    let mut headers = HashMap::new();
    for line in lines {
        if line.is_empty() {
            break;
        }
        let (name, value) = line
            .split_once(':')
            .ok_or_else(|| "HTTP 请求头格式无效".to_string())?;
        headers.insert(name.trim().to_ascii_lowercase(), value.trim().to_string());
    }
    let content_length = headers
        .get("content-length")
        .map(|value| {
            value
                .parse::<usize>()
                .map_err(|_| "content-length 无效".to_string())
        })
        .transpose()?
        .unwrap_or(0);
    if content_length > MAX_REQUEST_BODY_BYTES {
        return Err("HTTP 请求体过大".to_string());
    }
    while remainder.len() < content_length {
        let mut chunk = [0_u8; 8192];
        let read = stream.read(&mut chunk).map_err(|error| error.to_string())?;
        if read == 0 {
            return Err("HTTP 请求体提前结束".to_string());
        }
        remainder.extend_from_slice(&chunk[..read]);
    }
    let body = remainder.drain(..content_length).collect();
    Ok((
        HttpRequest {
            method,
            target,
            headers,
            body,
        },
        remainder,
    ))
}

fn read_http_head(stream: &mut TcpStream) -> Result<(Vec<u8>, Vec<u8>), String> {
    let mut buffer = Vec::with_capacity(4096);
    loop {
        if let Some(index) = find_header_end(&buffer) {
            let remainder = buffer.split_off(index + 4);
            buffer.truncate(index);
            return Ok((buffer, remainder));
        }
        if buffer.len() >= MAX_REQUEST_HEAD_BYTES {
            return Err("HTTP 请求头过大".to_string());
        }
        let mut chunk = [0_u8; 4096];
        let read = stream.read(&mut chunk).map_err(|error| error.to_string())?;
        if read == 0 {
            return Err("HTTP 请求提前结束".to_string());
        }
        buffer.extend_from_slice(&chunk[..read]);
    }
}

fn find_header_end(buffer: &[u8]) -> Option<usize> {
    buffer.windows(4).position(|window| window == b"\r\n\r\n")
}

fn is_websocket_upgrade(headers: &HashMap<String, String>) -> bool {
    headers
        .get("upgrade")
        .map(|value| value.eq_ignore_ascii_case("websocket"))
        .unwrap_or(false)
        && headers.contains_key("sec-websocket-key")
}

fn proxy_http_request(
    client: &mut TcpStream,
    request: HttpRequest,
    core_host: &str,
    core_port: u16,
    _core_api_base: &str,
) -> Result<(), String> {
    let mut core = TcpStream::connect((core_host, core_port))
        .map_err(|error| format!("Core proxy unavailable: {error}"))?;
    core.set_read_timeout(Some(Duration::from_secs(30))).ok();
    let target = strip_token_query(&request.target);
    let mut forwarded = format!(
        "{} {} HTTP/1.1\r\nHost: {}:{}\r\nConnection: close\r\n",
        request.method, target, core_host, core_port
    );
    for (name, value) in &request.headers {
        if matches!(
            name.as_str(),
            "host"
                | "connection"
                | "content-length"
                | "upgrade"
                | "sec-websocket-key"
                | "sec-websocket-version"
                | "sec-websocket-protocol"
                | "authorization"
                | "origin"
                | "referer"
                | "sec-fetch-dest"
                | "sec-fetch-mode"
                | "sec-fetch-site"
                | "sec-fetch-user"
        ) {
            continue;
        }
        forwarded.push_str(name);
        forwarded.push_str(": ");
        forwarded.push_str(value);
        forwarded.push_str("\r\n");
    }
    if !request.body.is_empty() {
        forwarded.push_str(&format!("Content-Length: {}\r\n", request.body.len()));
    }
    forwarded.push_str("\r\n");
    core.write_all(forwarded.as_bytes())
        .map_err(|error| error.to_string())?;
    core.write_all(&request.body)
        .map_err(|error| error.to_string())?;
    let (response_head, response_remainder) = read_http_head(&mut core)?;
    client
        .write_all(&response_head)
        .map_err(|error| error.to_string())?;
    client
        .write_all(b"\r\nAccess-Control-Allow-Origin: *\r\nAccess-Control-Allow-Headers: Authorization, Content-Type\r\nAccess-Control-Allow-Methods: GET, POST, PUT, PATCH, DELETE, OPTIONS\r\nAccess-Control-Allow-Private-Network: true\r\n\r\n")
        .map_err(|error| error.to_string())?;
    client
        .write_all(&response_remainder)
        .map_err(|error| error.to_string())?;
    io::copy(&mut core, client).map_err(|error| error.to_string())?;
    Ok(())
}

fn write_cors_preflight_response(stream: &mut TcpStream) -> Result<(), String> {
    stream
        .write_all(
            b"HTTP/1.1 204 No Content\r\nAccess-Control-Allow-Origin: *\r\nAccess-Control-Allow-Headers: Authorization, Content-Type\r\nAccess-Control-Allow-Methods: GET, POST, PUT, PATCH, DELETE, OPTIONS\r\nAccess-Control-Allow-Private-Network: true\r\nAccess-Control-Max-Age: 600\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
        )
        .map_err(|error| error.to_string())
}

fn write_json_response<T: Serialize>(
    stream: &mut TcpStream,
    status: u16,
    value: &T,
) -> Result<(), String> {
    let body = serde_json::to_vec(value).map_err(|error| error.to_string())?;
    let reason = match status {
        200 => "OK",
        400 => "Bad Request",
        401 => "Unauthorized",
        404 => "Not Found",
        502 => "Bad Gateway",
        _ => "Error",
    };
    let head = format!(
        "HTTP/1.1 {status} {reason}\r\nContent-Type: application/json; charset=utf-8\r\nContent-Length: {}\r\nCache-Control: no-store\r\nAccess-Control-Allow-Origin: *\r\nAccess-Control-Allow-Headers: Authorization, Content-Type\r\nAccess-Control-Allow-Methods: GET, POST, PUT, PATCH, DELETE, OPTIONS\r\nAccess-Control-Allow-Private-Network: true\r\nConnection: close\r\n\r\n",
        body.len()
    );
    stream
        .write_all(head.as_bytes())
        .map_err(|error| error.to_string())?;
    stream.write_all(&body).map_err(|error| error.to_string())
}

fn core_http_request(
    core_host: &str,
    core_port: u16,
    input: TunnelHttpRequest,
) -> Result<TunnelHttpResponse, String> {
    if input.path.contains("\r")
        || input.path.contains("\n")
        || input.method.contains(|c: char| c.is_whitespace())
    {
        return Err("invalid tunneled HTTP request".to_string());
    }
    let target = if input.path.starts_with("/api/core/") {
        input.path
    } else {
        format!("/api/core/{}", input.path.trim_start_matches('/'))
    };
    let body = if input.body.is_empty() {
        Vec::new()
    } else {
        base64::engine::general_purpose::STANDARD
            .decode(&input.body)
            .map_err(|_| "invalid tunneled HTTP body".to_string())?
    };
    if body.len() > MAX_REQUEST_BODY_BYTES {
        return Err("HTTP tunnel body is too large".to_string());
    }
    let mut core = TcpStream::connect((core_host, core_port))
        .map_err(|e| format!("Core proxy unavailable: {e}"))?;
    core.set_read_timeout(Some(Duration::from_secs(30))).ok();
    let mut request = format!(
        "{} {} HTTP/1.1\r\nHost: {}:{}\r\nConnection: close\r\n",
        input.method, target, core_host, core_port
    );
    for (name, value) in input.headers {
        let name = name.to_ascii_lowercase();
        if name.contains(['\r', '\n'])
            || value.contains(['\r', '\n'])
            || matches!(
                name.as_str(),
                "host" | "connection" | "content-length" | "authorization" | "origin" | "referer"
            )
        {
            continue;
        }
        request.push_str(&name);
        request.push_str(": ");
        request.push_str(&value);
        request.push_str("\r\n");
    }
    request.push_str(&format!("Content-Length: {}\r\n\r\n", body.len()));
    core.write_all(request.as_bytes())
        .map_err(|e| e.to_string())?;
    core.write_all(&body).map_err(|e| e.to_string())?;
    let (head, mut response_body) = read_http_head(&mut core)?;
    let text =
        std::str::from_utf8(&head).map_err(|_| "Core response head is invalid".to_string())?;
    let mut lines = text.split("\r\n");
    let status = lines
        .next()
        .and_then(|line| line.split_whitespace().nth(1))
        .and_then(|v| v.parse::<u16>().ok())
        .ok_or_else(|| "Core response status is invalid".to_string())?;
    let mut headers = HashMap::new();
    for line in lines {
        if let Some((name, value)) = line.split_once(':') {
            headers.insert(name.trim().to_ascii_lowercase(), value.trim().to_string());
        }
    }
    if headers
        .get("transfer-encoding")
        .is_some_and(|value| value.eq_ignore_ascii_case("chunked"))
    {
        let mut rest = Vec::new();
        core.read_to_end(&mut rest).map_err(|e| e.to_string())?;
        response_body.extend_from_slice(&rest);
        response_body = decode_chunked_body(&response_body)?;
        headers.remove("transfer-encoding");
    } else if let Some(length) = headers
        .get("content-length")
        .and_then(|value| value.parse::<usize>().ok())
    {
        while response_body.len() < length {
            let mut chunk = [0_u8; 8192];
            let read = core.read(&mut chunk).map_err(|e| e.to_string())?;
            if read == 0 {
                break;
            }
            response_body.extend_from_slice(&chunk[..read]);
        }
        response_body.truncate(length);
    } else {
        core.read_to_end(&mut response_body)
            .map_err(|e| e.to_string())?;
    }
    Ok(TunnelHttpResponse {
        status,
        headers,
        body: base64::engine::general_purpose::STANDARD.encode(response_body),
    })
}

fn decode_chunked_body(input: &[u8]) -> Result<Vec<u8>, String> {
    let mut cursor = 0;
    let mut output = Vec::new();
    loop {
        let line_end = input[cursor..]
            .windows(2)
            .position(|w| w == b"\r\n")
            .ok_or_else(|| "invalid chunked response".to_string())?
            + cursor;
        let length_text = std::str::from_utf8(&input[cursor..line_end])
            .map_err(|_| "invalid chunk length".to_string())?;
        let length = usize::from_str_radix(length_text.split(';').next().unwrap_or_default(), 16)
            .map_err(|_| "invalid chunk length".to_string())?;
        cursor = line_end + 2;
        if length == 0 {
            break;
        }
        let end = cursor
            .checked_add(length)
            .filter(|end| *end + 2 <= input.len())
            .ok_or_else(|| "truncated chunked response".to_string())?;
        output.extend_from_slice(&input[cursor..end]);
        cursor = end + 2;
    }
    Ok(output)
}

fn connect_core_websocket(
    core_host: &str,
    core_port: u16,
    target: &str,
) -> Result<(TcpStream, Vec<u8>), String> {
    let mut core = TcpStream::connect((core_host, core_port))
        .map_err(|error| format!("Core websocket unavailable: {error}"))?;
    // RFC 6455 requires Sec-WebSocket-Key to be the standard-base64
    // encoding of exactly 16 random bytes.  The desktop identity helper
    // intentionally emits URL-safe base64 tokens, which some strict ASGI
    // servers reject with HTTP 400 during the upstream handshake.
    let mut key_bytes = [0_u8; 16];
    fill_random(&mut key_bytes).map_err(|error| error.to_string())?;
    let key = base64::engine::general_purpose::STANDARD.encode(key_bytes);
    let request = format!(
        "GET {target} HTTP/1.1\r\nHost: {core_host}:{core_port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: {key}\r\n\r\n"
    );
    core.write_all(request.as_bytes())
        .map_err(|error| error.to_string())?;
    let (head, remainder) = read_http_head(&mut core)?;
    let text =
        std::str::from_utf8(&head).map_err(|_| "Core websocket response invalid".to_string())?;
    let status = text.lines().next().unwrap_or_default();
    if !status.contains(" 101 ") {
        return Err("Core websocket handshake rejected".to_string());
    }
    Ok((core, remainder))
}

fn websocket_accept(key: &str) -> String {
    let mut hasher = Sha1::new();
    hasher.update(key.trim().as_bytes());
    hasher.update(WS_GUID.as_bytes());
    base64::engine::general_purpose::STANDARD.encode(hasher.finalize())
}

fn protocol_ack(mut value: serde_json::Value) -> Result<Vec<u8>, String> {
    let object = value
        .as_object_mut()
        .ok_or_else(|| "remote protocol acknowledgement must be an object".to_string())?;
    object.insert(
        "protocol".to_string(),
        serde_json::Value::String(REMOTE_PROTOCOL.to_string()),
    );
    object.insert(
        "version".to_string(),
        serde_json::Value::Number(REMOTE_PROTOCOL_VERSION.into()),
    );
    serde_json::to_vec(&value).map_err(|error| error.to_string())
}

struct BufferedStream {
    stream: TcpStream,
    prefix: Cursor<Vec<u8>>,
}

impl BufferedStream {
    fn new(stream: TcpStream, prefix: Vec<u8>) -> Self {
        Self {
            stream,
            prefix: Cursor::new(prefix),
        }
    }
}

impl Read for BufferedStream {
    fn read(&mut self, output: &mut [u8]) -> io::Result<usize> {
        let read = self.prefix.read(output)?;
        if read > 0 {
            return Ok(read);
        }
        self.stream.read(output)
    }
}

#[derive(Debug)]
struct WsFrame {
    fin: bool,
    opcode: u8,
    masked: bool,
    payload: Vec<u8>,
}

struct WsMessageAssembler {
    opcode: Option<u8>,
    payload: Vec<u8>,
    max_message_bytes: usize,
}

impl WsMessageAssembler {
    fn with_limit(max_message_bytes: usize) -> Self {
        Self {
            opcode: None,
            payload: Vec::new(),
            max_message_bytes,
        }
    }
}

impl Default for WsMessageAssembler {
    fn default() -> Self {
        Self::with_limit(MAX_TUNNEL_WS_MESSAGE_BYTES)
    }
}

enum WsMessageEvent {
    Message { opcode: u8, payload: Vec<u8> },
    Ping(Vec<u8>),
    Pong,
    Close,
    Pending,
}

impl WsMessageAssembler {
    fn push(&mut self, frame: WsFrame) -> io::Result<WsMessageEvent> {
        match frame.opcode {
            0 => {
                let opcode = self.opcode.ok_or_else(|| {
                    io::Error::new(
                        io::ErrorKind::InvalidData,
                        "websocket continuation without an initial frame",
                    )
                })?;
                self.extend(&frame.payload)?;
                if !frame.fin {
                    return Ok(WsMessageEvent::Pending);
                }
                self.opcode = None;
                Ok(WsMessageEvent::Message {
                    opcode,
                    payload: std::mem::take(&mut self.payload),
                })
            }
            opcode @ (1 | 2) => {
                if self.opcode.is_some() {
                    return Err(io::Error::new(
                        io::ErrorKind::InvalidData,
                        "websocket data frame interrupted a fragmented message",
                    ));
                }
                if frame.payload.len() > self.max_message_bytes {
                    return Err(io::Error::new(
                        io::ErrorKind::InvalidData,
                        "websocket message too large",
                    ));
                }
                if frame.fin {
                    return Ok(WsMessageEvent::Message {
                        opcode,
                        payload: frame.payload,
                    });
                }
                self.opcode = Some(opcode);
                self.payload = frame.payload;
                Ok(WsMessageEvent::Pending)
            }
            8 => Ok(WsMessageEvent::Close),
            9 => Ok(WsMessageEvent::Ping(frame.payload)),
            10 => Ok(WsMessageEvent::Pong),
            _ => Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "unsupported websocket opcode",
            )),
        }
    }

    fn extend(&mut self, chunk: &[u8]) -> io::Result<()> {
        let length = self
            .payload
            .len()
            .checked_add(chunk.len())
            .filter(|length| *length <= self.max_message_bytes)
            .ok_or_else(|| {
                io::Error::new(io::ErrorKind::InvalidData, "websocket message too large")
            })?;
        self.payload.reserve(length - self.payload.len());
        self.payload.extend_from_slice(chunk);
        Ok(())
    }
}

fn queue_core_message(
    output: &mpsc::Sender<TunnelFrame>,
    opcode: u8,
    payload: Vec<u8>,
) -> Result<(), String> {
    let payload_bytes = payload.len();
    let (request_id, method) = if opcode == 1 {
        rpc_metadata(&payload)
    } else {
        (None, None)
    };
    let frame = match opcode {
        1 => {
            let payload = String::from_utf8(payload)
                .map_err(|_| "Core websocket text frame is not UTF-8".to_string())?;
            let mut frame = TunnelFrame::new("rpc.data", "rpc", 0);
            frame.request_id = request_id.clone();
            frame.payload = Some(payload);
            frame
        }
        2 => {
            let mut frame = TunnelFrame::new("binary.data", "binary", 0);
            frame.payload = Some(base64::engine::general_purpose::STANDARD.encode(payload));
            frame
        }
        _ => return Err("unsupported Core websocket message".to_string()),
    };
    if !is_streaming_run_item(&method, frame.payload.as_deref()) {
        trace(
            "gateway.core_received",
            serde_json::json!({
                "direction": "core_to_mobile",
                "request_id": &request_id,
                "method": &method,
                "frame_type": &frame.frame_type,
                "bytes": payload_bytes,
            }),
        );
    }
    output.send(frame).map_err(|error| error.to_string())
}

fn trace_gateway_frame(event: &str, direction: &str, frame: &TunnelFrame) {
    if frame.frame_type != "rpc.data" {
        return;
    }
    let (payload_request_id, method) = frame
        .payload
        .as_deref()
        .map(str::as_bytes)
        .map(rpc_metadata)
        .unwrap_or((None, None));
    if is_streaming_run_item(&method, frame.payload.as_deref()) {
        return;
    }
    let request_id = frame.request_id.as_ref().or(payload_request_id.as_ref());
    trace(
        event,
        serde_json::json!({
            "direction": direction,
            "request_id": request_id,
            "method": &method,
            "frame_type": &frame.frame_type,
            "stream_id": &frame.stream_id,
            "sequence": frame.sequence,
            "bytes": frame.payload.as_ref().map_or(0, String::len),
        }),
    );
}

fn rpc_metadata(payload: &[u8]) -> (Option<String>, Option<String>) {
    let Ok(value) = serde_json::from_slice::<serde_json::Value>(payload) else {
        return (None, None);
    };
    let request_id = value.get("id").and_then(json_scalar_string);
    let method = value
        .get("method")
        .and_then(serde_json::Value::as_str)
        .map(str::to_string);
    (request_id, method)
}

fn json_scalar_string(value: &serde_json::Value) -> Option<String> {
    match value {
        serde_json::Value::String(value) => Some(value.clone()),
        serde_json::Value::Number(value) => Some(value.to_string()),
        _ => None,
    }
}

fn is_streaming_run_item(method: &Option<String>, payload: Option<&str>) -> bool {
    if method.as_deref() != Some("core/runItem") {
        return false;
    }
    let Some(payload) = payload else { return false };
    let Ok(mut value) = serde_json::from_str::<serde_json::Value>(payload) else {
        return false;
    };
    for _ in 0..4 {
        if value
            .get("delta")
            .and_then(serde_json::Value::as_str)
            .is_some()
        {
            return true;
        }
        let Some(next) = value.get("payload") else {
            break;
        };
        value = next.clone();
    }
    false
}

fn split_tunnel_payload(payload: &str) -> Vec<&str> {
    let mut chunks = Vec::new();
    let mut start = 0;
    while start < payload.len() {
        let mut end = start
            .saturating_add(MAX_CHUNK_PAYLOAD_BYTES)
            .min(payload.len());
        while !payload.is_char_boundary(end) {
            end -= 1;
        }
        chunks.push(&payload[start..end]);
        start = end;
    }
    chunks
}

fn read_ws_frame(stream: &mut impl Read) -> io::Result<Option<WsFrame>> {
    read_ws_frame_limited(stream, MAX_TUNNEL_WS_FRAME_BYTES)
}

fn read_ws_frame_limited(
    stream: &mut impl Read,
    max_frame_bytes: u64,
) -> io::Result<Option<WsFrame>> {
    let mut header = [0_u8; 2];
    match stream.read_exact(&mut header) {
        Ok(()) => {}
        Err(error) if error.kind() == io::ErrorKind::UnexpectedEof => return Ok(None),
        Err(error) => return Err(error),
    }
    if header[0] & 0x70 != 0 {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "websocket reserved bits",
        ));
    }
    let fin = header[0] & 0x80 != 0;
    let opcode = header[0] & 0x0f;
    let masked = header[1] & 0x80 != 0;
    let mut length = u64::from(header[1] & 0x7f);
    if length == 126 {
        let mut bytes = [0_u8; 2];
        stream.read_exact(&mut bytes)?;
        length = u64::from(u16::from_be_bytes(bytes));
    } else if length == 127 {
        let mut bytes = [0_u8; 8];
        stream.read_exact(&mut bytes)?;
        length = u64::from_be_bytes(bytes);
    }
    if opcode_is_control(opcode) && (!fin || length > 125) {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "invalid websocket control frame",
        ));
    }
    if length > max_frame_bytes {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "websocket frame too large",
        ));
    }
    let mut mask = [0_u8; 4];
    if masked {
        stream.read_exact(&mut mask)?;
    }
    let mut payload = vec![0_u8; length as usize];
    stream.read_exact(&mut payload)?;
    if masked {
        for (index, byte) in payload.iter_mut().enumerate() {
            *byte ^= mask[index % 4];
        }
    }
    Ok(Some(WsFrame {
        fin,
        opcode,
        masked,
        payload,
    }))
}

fn read_tunnel_ws_payload(
    stream: &mut impl Read,
    mut on_ping: impl FnMut(&[u8]) -> io::Result<()>,
) -> io::Result<Vec<u8>> {
    let mut assembler = WsMessageAssembler::with_limit(MAX_TUNNEL_WS_MESSAGE_BYTES);
    loop {
        let frame = read_ws_frame_limited(stream, MAX_TUNNEL_WS_FRAME_BYTES)?
            .ok_or_else(|| io::Error::new(io::ErrorKind::UnexpectedEof, "tunnel socket closed"))?;
        if !frame.masked {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "mobile websocket frames must be masked",
            ));
        }
        match assembler.push(frame)? {
            WsMessageEvent::Message { opcode: 2, payload } => return Ok(payload),
            WsMessageEvent::Message { .. } => {
                return Err(io::Error::new(
                    io::ErrorKind::InvalidData,
                    "tunnel requires binary websocket messages",
                ))
            }
            WsMessageEvent::Close => {
                return Err(io::Error::new(
                    io::ErrorKind::UnexpectedEof,
                    "tunnel socket closed",
                ))
            }
            WsMessageEvent::Ping(payload) => {
                on_ping(&payload)?;
            }
            WsMessageEvent::Pong | WsMessageEvent::Pending => {}
        }
    }
}

fn opcode_is_control(opcode: u8) -> bool {
    opcode & 0x08 != 0
}

fn write_ws_pong(stream: &mut impl Write, payload: &[u8], masked: bool) -> io::Result<()> {
    if payload.len() > 125 {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "websocket control frame is too large",
        ));
    }
    write_ws_frame(
        stream,
        &WsFrame {
            fin: true,
            opcode: 10,
            masked: false,
            payload: payload.to_vec(),
        },
        masked,
    )
}

fn write_ws_control(stream: &mut impl Write, opcode: u8, payload: &[u8]) -> io::Result<()> {
    if payload.len() > 125 || opcode & 0x08 == 0 {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "invalid websocket control frame",
        ));
    }
    write_ws_frame(
        stream,
        &WsFrame {
            fin: true,
            opcode,
            masked: false,
            payload: payload.to_vec(),
        },
        false,
    )
}

fn write_ws_binary(stream: &mut impl Write, payload: &[u8]) -> Result<(), String> {
    write_ws_frame(
        stream,
        &WsFrame {
            fin: true,
            opcode: 2,
            masked: false,
            payload: payload.to_vec(),
        },
        false,
    )
    .map_err(|error| error.to_string())
}

fn write_ws_frame(stream: &mut impl Write, frame: &WsFrame, masked: bool) -> io::Result<()> {
    let mut first = if frame.fin { 0x80 } else { 0 };
    first |= frame.opcode & 0x0f;
    stream.write_all(&[first])?;
    let length = frame.payload.len();
    let mask_bit = if masked { 0x80 } else { 0 };
    if length < 126 {
        stream.write_all(&[mask_bit | length as u8])?;
    } else if length <= u16::MAX as usize {
        stream.write_all(&[mask_bit | 126])?;
        stream.write_all(&(length as u16).to_be_bytes())?;
    } else {
        stream.write_all(&[mask_bit | 127])?;
        stream.write_all(&(length as u64).to_be_bytes())?;
    }
    if !masked {
        return stream.write_all(&frame.payload);
    }
    let mut mask = [0_u8; 4];
    getrandom::fill(&mut mask)
        .map_err(|error| io::Error::other(format!("websocket mask generation failed: {error}")))?;
    stream.write_all(&mask)?;
    let payload = frame
        .payload
        .iter()
        .enumerate()
        .map(|(index, byte)| byte ^ mask[index % 4])
        .collect::<Vec<_>>();
    stream.write_all(&payload)
}

fn strip_token_query(target: &str) -> String {
    let Ok(mut url) = Url::parse(&format!("http://gateway.invalid{target}")) else {
        return target.to_string();
    };
    let pairs = url
        .query_pairs()
        .filter(|(name, _)| name != "token")
        .map(|(name, value)| (name.into_owned(), value.into_owned()))
        .collect::<Vec<_>>();
    url.set_query(None);
    if !pairs.is_empty() {
        let mut query = url.query_pairs_mut();
        query.extend_pairs(pairs.iter().map(|(name, value)| (name, value)));
    }
    let mut result = url.path().to_string();
    if let Some(query) = url.query() {
        result.push('?');
        result.push_str(query);
    }
    result
}

fn pairing_id_from_target(target: &str) -> Option<String> {
    let path = target.split('?').next()?;
    let parts: Vec<_> = path.split('/').collect();
    if parts.len() >= 4 && parts[1] == "_lamtools" && parts[2] == "pairing" {
        return Some(parts[3].to_string());
    }
    None
}

fn query_value<'a>(target: &'a str, key: &str) -> Option<&'a str> {
    let query = target.split_once('?')?.1;
    query.split('&').find_map(|pair| {
        let (name, value) = pair.split_once('=')?;
        if name == key {
            Some(value)
        } else {
            None
        }
    })
}

#[cfg(test)]
mod tests {
    use super::{
        parse_loopback_http_base, read_http_head, read_tunnel_ws_payload, read_ws_frame,
        split_tunnel_payload, strip_token_query, websocket_accept, write_ws_frame, write_ws_pong,
        BufferedStream, GatewayStartOptions, RemoteGateway, SecureTunnelWriter, WsFrame,
    };
    use crate::remote::secure_store::MemorySecureStore;
    use crate::remote::{
        identity::DeviceIdentity,
        pairing::PairingManager,
        tunnel::{TunnelCodec, TunnelFrame},
    };
    use serde_json::Value;
    use std::{
        io::{Cursor, Read, Write},
        net::{Shutdown, SocketAddr, TcpListener, TcpStream},
        sync::{mpsc, Arc, Barrier, Mutex},
        thread,
        time::Duration,
    };

    fn send_http(addr: SocketAddr, request: &str) -> String {
        let mut stream = TcpStream::connect(addr).expect("connect gateway");
        stream
            .set_read_timeout(Some(Duration::from_secs(5)))
            .expect("read timeout");
        stream.write_all(request.as_bytes()).expect("write request");
        stream.shutdown(Shutdown::Write).expect("shutdown write");
        let mut response = String::new();
        stream.read_to_string(&mut response).expect("read response");
        response
    }

    #[test]
    fn tunnel_payload_split_uses_utf8_bytes_and_valid_boundaries() {
        let ascii = "a".repeat(super::MAX_CHUNK_PAYLOAD_BYTES + 1);
        let ascii_chunks = split_tunnel_payload(&ascii);
        assert_eq!(
            ascii_chunks
                .iter()
                .map(|chunk| chunk.len())
                .collect::<Vec<_>>(),
            vec![super::MAX_CHUNK_PAYLOAD_BYTES, 1,]
        );

        let unicode = format!("{}你🙂", "a".repeat(super::MAX_CHUNK_PAYLOAD_BYTES - 2));
        let unicode_chunks = split_tunnel_payload(&unicode);
        assert_eq!(unicode_chunks.concat(), unicode);
        assert_eq!(unicode_chunks[0].len(), super::MAX_CHUNK_PAYLOAD_BYTES - 2);
        assert!(unicode_chunks
            .iter()
            .all(|chunk| chunk.len() <= super::MAX_CHUNK_PAYLOAD_BYTES));
    }

    #[test]
    fn tunnel_reader_replies_to_ping_before_next_payload() {
        let mut input = Vec::new();
        write_ws_frame(
            &mut input,
            &WsFrame {
                fin: true,
                opcode: 9,
                masked: true,
                payload: b"keepalive".to_vec(),
            },
            true,
        )
        .expect("ping");
        write_ws_frame(
            &mut input,
            &WsFrame {
                fin: true,
                opcode: 2,
                masked: true,
                payload: b"encrypted".to_vec(),
            },
            true,
        )
        .expect("binary payload");

        let mut reader = Cursor::new(input);
        let mut output = Vec::new();
        let payload =
            read_tunnel_ws_payload(&mut reader, |ping| write_ws_pong(&mut output, ping, false))
                .expect("payload after ping");
        assert_eq!(payload, b"encrypted");

        let mut pong_reader = Cursor::new(output);
        let pong = read_ws_frame(&mut pong_reader)
            .expect("pong frame")
            .expect("pong frame present");
        assert_eq!(pong.opcode, 10);
        assert!(!pong.masked);
        assert_eq!(pong.payload, b"keepalive");
    }

    #[test]
    fn tunnel_reader_reassembles_fragmented_binary_with_interleaved_ping() {
        let mut input = Vec::new();
        write_ws_frame(
            &mut input,
            &WsFrame {
                fin: false,
                opcode: 2,
                masked: true,
                payload: b"encr".to_vec(),
            },
            true,
        )
        .expect("first fragment");
        write_ws_frame(
            &mut input,
            &WsFrame {
                fin: true,
                opcode: 9,
                masked: true,
                payload: b"still-alive".to_vec(),
            },
            true,
        )
        .expect("ping");
        write_ws_frame(
            &mut input,
            &WsFrame {
                fin: true,
                opcode: 0,
                masked: true,
                payload: b"ypted".to_vec(),
            },
            true,
        )
        .expect("continuation");

        let mut reader = Cursor::new(input);
        let mut output = Vec::new();
        let payload =
            read_tunnel_ws_payload(&mut reader, |ping| write_ws_pong(&mut output, ping, false))
                .expect("fragmented payload");
        assert_eq!(payload, b"encrypted");

        let mut pong_reader = Cursor::new(output);
        let pong = read_ws_frame(&mut pong_reader)
            .expect("pong frame")
            .expect("pong frame present");
        assert_eq!(pong.opcode, 10);
        assert_eq!(pong.payload, b"still-alive");
    }

    #[test]
    fn concurrent_tunnel_sends_keep_sequences_and_noise_chunks_ordered() {
        let params: snow::params::NoiseParams =
            "Noise_XX_25519_ChaChaPoly_BLAKE2b".parse().unwrap();
        let initiator_key = snow::Builder::new(params.clone())
            .generate_keypair()
            .expect("initiator key");
        let responder_key = snow::Builder::new(params.clone())
            .generate_keypair()
            .expect("responder key");
        let mut initiator = snow::Builder::new(params.clone())
            .local_private_key(&initiator_key.private)
            .build_initiator()
            .expect("initiator");
        let mut responder = snow::Builder::new(params)
            .local_private_key(&responder_key.private)
            .build_responder()
            .expect("responder");
        let mut message = vec![0_u8; 65_535];
        let mut scratch = vec![0_u8; 65_535];
        let length = initiator
            .write_message(&[], &mut message)
            .expect("message 1");
        responder
            .read_message(&message[..length], &mut scratch)
            .expect("read message 1");
        let length = responder
            .write_message(&[], &mut message)
            .expect("message 2");
        initiator
            .read_message(&message[..length], &mut scratch)
            .expect("read message 2");
        let length = initiator
            .write_message(&[], &mut message)
            .expect("message 3");
        responder
            .read_message(&message[..length], &mut scratch)
            .expect("read message 3");
        let mut receiver_transport = initiator
            .into_transport_mode()
            .expect("initiator transport");
        let sender_transport = responder
            .into_transport_mode()
            .expect("responder transport");

        let listener = TcpListener::bind("127.0.0.1:0").expect("listener");
        let mut receiver = TcpStream::connect(listener.local_addr().unwrap()).expect("connect");
        receiver
            .set_read_timeout(Some(Duration::from_secs(5)))
            .expect("timeout");
        let (sender, _) = listener.accept().expect("accept");
        let writer = SecureTunnelWriter::new(sender, Arc::new(Mutex::new(sender_transport)));
        let barrier = Arc::new(Barrier::new(5));
        let threads = (0..4)
            .map(|index| {
                let writer = writer.clone();
                let barrier = barrier.clone();
                thread::spawn(move || {
                    let mut frame = TunnelFrame::new("rpc.data", "rpc", 0);
                    frame.payload = Some(format!("{index}:{}", "x".repeat(130_000)));
                    barrier.wait();
                    writer.send_tunnel_frame(frame).expect("send frame");
                })
            })
            .collect::<Vec<_>>();
        barrier.wait();

        let mut decoder = super::TunnelStreamDecoder::default();
        let mut decoded = Vec::new();
        let mut plain = vec![0_u8; 65_535];
        while decoded.len() < 4 {
            let encrypted = read_ws_frame(&mut receiver)
                .expect("websocket read")
                .expect("websocket frame")
                .payload;
            let read = receiver_transport
                .read_message(&encrypted, &mut plain)
                .expect("decrypt");
            decoded.extend(decoder.push(&plain[..read]).expect("decode"));
        }
        for handle in threads {
            handle.join().expect("sender thread");
        }
        assert_eq!(
            decoded
                .iter()
                .map(|frame| frame.sequence)
                .collect::<Vec<_>>(),
            vec![1, 2, 3, 4]
        );
        assert!(decoded.iter().all(|frame| frame
            .payload
            .as_ref()
            .is_some_and(|value| value.len() == 130_002)));
    }

    fn response_json(response: &str) -> Value {
        let body = response.split_once("\r\n\r\n").expect("response body").1;
        serde_json::from_str(body).expect("json response")
    }

    fn test_gateway(core_addr: SocketAddr) -> RemoteGateway {
        let identity = DeviceIdentity::generate().expect("identity");
        let pairings = Arc::new(PairingManager::new(identity.clone()));
        RemoteGateway::start(
            &format!("http://{core_addr}"),
            identity,
            pairings,
            GatewayStartOptions {
                bind_host: Some("127.0.0.1".to_string()),
                port: Some(0),
                ..Default::default()
            },
        )
        .expect("gateway")
    }

    #[test]
    fn gateway_only_accepts_loopback_core() {
        assert!(parse_loopback_http_base("http://127.0.0.1:5172/api/core").is_ok());
        assert!(parse_loopback_http_base("http://localhost:5172").is_ok());
        assert!(parse_loopback_http_base("http://192.168.1.5:5172").is_err());
        assert!(parse_loopback_http_base("https://127.0.0.1:5172").is_err());
    }

    #[test]
    fn gateway_accepts_non_loopback_binding_with_encrypted_tunnel() {
        let identity = DeviceIdentity::generate().expect("identity");
        let pairings = Arc::new(PairingManager::new(identity.clone()));
        let gateway = RemoteGateway::start(
            "http://127.0.0.1:5172",
            identity,
            pairings,
            GatewayStartOptions {
                bind_host: Some("0.0.0.0".to_string()),
                port: Some(0),
                ..Default::default()
            },
        )
        .expect("encrypted gateway must bind");
        assert_eq!(gateway.status().state, "running");
        gateway.stop().expect("stop gateway");
    }

    #[test]
    fn token_query_is_not_forwarded_to_core() {
        assert_eq!(
            strip_token_query("/api/core/app-server?token=secret&foo=bar"),
            "/api/core/app-server?foo=bar"
        );
        assert_eq!(
            strip_token_query("/api/core/sessions"),
            "/api/core/sessions"
        );
    }

    #[test]
    fn websocket_accept_matches_rfc_example() {
        assert_eq!(
            websocket_accept("dGhlIHNhbXBsZSBub25jZQ=="),
            "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="
        );
    }

    #[test]
    fn gateway_health_auth_pairing_and_rest_proxy_work_end_to_end() {
        let core_listener = TcpListener::bind("127.0.0.1:0").expect("core listener");
        let core_addr = core_listener.local_addr().expect("core addr");
        let (request_tx, request_rx) = mpsc::channel();
        let core_thread = thread::spawn(move || {
            let (mut stream, _) = core_listener.accept().expect("core accept");
            let (head, _) = read_http_head(&mut stream).expect("core request");
            request_tx
                .send(String::from_utf8(head).expect("utf8"))
                .expect("send");
            let body = b"{\"proxied\":true}";
            write!(
                stream,
                "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                body.len()
            )
            .expect("response head");
            stream.write_all(body).expect("response body");
        });

        let gateway = test_gateway(core_addr);
        let status = gateway.status();
        let gateway_addr = SocketAddr::new(
            status.bind_addr.expect("bind addr").parse().expect("ip"),
            status.port.expect("port"),
        );

        let health = send_http(
            gateway_addr,
            "GET /_lamtools/health HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n",
        );
        assert!(health.starts_with("HTTP/1.1 200"));
        assert!(health
            .to_ascii_lowercase()
            .contains("access-control-allow-origin: *"));
        let preflight = send_http(
            gateway_addr,
            "OPTIONS /api/core/sessions HTTP/1.1\r\nHost: localhost\r\nOrigin: capacitor://localhost\r\nAccess-Control-Request-Method: GET\r\nAccess-Control-Request-Headers: authorization\r\nConnection: close\r\n\r\n",
        );
        assert!(preflight.starts_with("HTTP/1.1 204"));
        assert!(preflight
            .to_ascii_lowercase()
            .contains("access-control-allow-private-network: true"));
        let unauthorized = send_http(
            gateway_addr,
            "GET /api/core/sessions HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n",
        );
        assert!(unauthorized.starts_with("HTTP/1.1 401"));

        let pairing = gateway.pairing_create().expect("pairing");
        let payload = serde_json::json!({
            "code": pairing.code,
            "deviceId": "phone-e2e",
            "deviceName": "Integration phone",
            "platform": "test"
        })
        .to_string();
        let redeem_request = format!(
            "POST /_lamtools/pairing/{}/redeem HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
            pairing.pairing_id,
            payload.len(),
            payload
        );
        let redeemed = send_http(gateway_addr, &redeem_request);
        assert!(redeemed.starts_with("HTTP/1.1 200"));
        let access_token = response_json(&redeemed)["accessToken"]
            .as_str()
            .expect("access token")
            .to_string();
        let replay = send_http(gateway_addr, &redeem_request);
        assert!(replay.starts_with("HTTP/1.1 400"));

        let proxied = send_http(
            gateway_addr,
            &format!(
                "GET /api/core/sessions HTTP/1.1\r\nHost: localhost\r\nAuthorization: Bearer {access_token}\r\nOrigin: capacitor://localhost\r\nReferer: capacitor://localhost/\r\nSec-Fetch-Site: cross-site\r\nConnection: close\r\n\r\n"
            ),
        );
        assert!(proxied.starts_with("HTTP/1.1 200"));
        assert!(proxied
            .to_ascii_lowercase()
            .contains("access-control-allow-origin: *"));
        assert_eq!(response_json(&proxied)["proxied"], true);
        let core_request = request_rx
            .recv_timeout(Duration::from_secs(5))
            .expect("core request");
        let normalized = core_request.to_ascii_lowercase();
        assert!(normalized.starts_with("get /api/core/sessions http/1.1"));
        assert!(!normalized.contains("authorization:"));
        assert!(!normalized.contains("origin:"));
        assert!(!normalized.contains("referer:"));
        assert!(!normalized.contains("sec-fetch-"));

        gateway.stop().expect("stop gateway");
        core_thread.join().expect("core thread");
    }

    #[test]
    fn gateway_rejects_legacy_direct_core_websocket() {
        let core_listener = TcpListener::bind("127.0.0.1:0").expect("core listener");
        let gateway = test_gateway(core_listener.local_addr().expect("core addr"));
        let status = gateway.status();
        let gateway_addr = SocketAddr::new(
            status.bind_addr.expect("bind addr").parse().expect("ip"),
            status.port.expect("port"),
        );
        let response = send_http(
            gateway_addr,
            "GET /api/core/app-server HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nConnection: close\r\n\r\n",
        );
        assert!(response.starts_with("HTTP/1.1 404"));
        gateway.stop().expect("stop gateway");
    }

    #[test]
    fn encrypted_pairing_and_tunnel_handshake_round_trip() {
        let core_listener = TcpListener::bind("127.0.0.1:0").expect("core listener");
        let core_addr = core_listener.local_addr().expect("core addr");
        let (core_frame_tx, core_frame_rx) = mpsc::channel();
        let core_thread = thread::spawn(move || {
            let (mut stream, _) = core_listener.accept().expect("core accept");
            let (head, remainder) = read_http_head(&mut stream).expect("core handshake");
            let text = String::from_utf8(head).expect("core header");
            let key = text
                .lines()
                .find_map(|line| {
                    let (name, value) = line.split_once(':')?;
                    name.eq_ignore_ascii_case("sec-websocket-key")
                        .then(|| value.trim().to_string())
                })
                .expect("core key");
            write!(stream, "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: {}\r\n\r\n", websocket_accept(&key)).expect("core response");
            let mut reader = BufferedStream::new(stream, remainder);
            if let Ok(Some(frame)) = read_ws_frame(&mut reader) {
                core_frame_tx.send(frame.payload).expect("core frame");
            }
        });

        let desktop = DeviceIdentity::generate().expect("desktop identity");
        let pairings = Arc::new(PairingManager::new(desktop.clone()));
        let gateway = RemoteGateway::start(
            &format!("http://{core_addr}"),
            desktop.clone(),
            pairings,
            GatewayStartOptions {
                bind_host: Some("127.0.0.1".to_string()),
                port: Some(0),
                ..Default::default()
            },
        )
        .expect("gateway");
        let pairing = gateway.pairing_create().expect("pairing");
        let mobile = snow::Builder::new("Noise_XX_25519_ChaChaPoly_BLAKE2b".parse().unwrap())
            .generate_keypair()
            .expect("mobile key");
        let mut handshake =
            snow::Builder::new("Noise_XX_25519_ChaChaPoly_BLAKE2b".parse().unwrap())
                .local_private_key(&mobile.private)
                .prologue(b"LamTools Remote Tunnel v1")
                .build_initiator()
                .expect("initiator");
        let endpoint = format!(
            "ws://127.0.0.1:{}/_lamtools/tunnel?pairing={}",
            gateway.status().port.unwrap(),
            pairing.pairing_id
        );
        let (mut socket, _) = tungstenite::connect(endpoint).expect("mobile socket");
        let mut bytes = vec![0_u8; 65_535];
        let length = handshake.write_message(&[], &mut bytes).expect("msg1");
        socket
            .send(tungstenite::Message::Binary(
                bytes[..length].to_vec().into(),
            ))
            .expect("send msg1");
        let msg2 = socket.read().expect("msg2").into_data();
        let mut scratch = vec![0_u8; 65_535];
        handshake
            .read_message(&msg2, &mut scratch)
            .expect("read msg2");
        let auth = serde_json::json!({"mode":"pair","code":pairing.code,"device_id":"mobile-e2e","device_name":"E2E","platform":"test"});
        let length = handshake
            .write_message(auth.to_string().as_bytes(), &mut bytes)
            .expect("msg3");
        socket
            .send(tungstenite::Message::Binary(
                bytes[..length].to_vec().into(),
            ))
            .expect("send msg3");
        let mut transport = handshake.into_transport_mode().expect("transport");
        let ack_cipher = socket.read().expect("ack").into_data();
        let ack_len = transport
            .read_message(&ack_cipher, &mut scratch)
            .expect("ack decrypt");
        let ack: Value = serde_json::from_slice(&scratch[..ack_len]).expect("ack json");
        let access_token = ack["accessToken"].as_str().expect("token");
        assert!(!access_token.is_empty());
        assert_eq!(ack["protocol"], "lamtools-remote");
        assert_eq!(ack["version"], 1);
        let mut frame = TunnelFrame::new("rpc.data", "rpc", 1);
        frame.payload = Some("{\"jsonrpc\":\"2.0\",\"method\":\"ping\"}".to_string());
        let encoded = TunnelCodec::encode(&frame).expect("frame");
        let mut encrypted = vec![0_u8; encoded.len() + 32];
        let length = transport
            .write_message(&encoded, &mut encrypted)
            .expect("encrypt");
        socket
            .send(tungstenite::Message::Binary(
                encrypted[..length].to_vec().into(),
            ))
            .expect("send frame");
        let forwarded = core_frame_rx
            .recv_timeout(Duration::from_secs(5))
            .expect("forwarded frame");
        assert_eq!(forwarded, frame.payload.unwrap().into_bytes());
        let _ = socket.close(None);
        gateway.stop().expect("stop gateway");
        core_thread.join().expect("core thread");
    }

    #[test]
    fn enabled_preference_survives_shutdown_but_not_user_stop() {
        let core_listener = TcpListener::bind("127.0.0.1:0").expect("core listener");
        let store = Arc::new(MemorySecureStore::default());
        let manager = super::RemoteGatewayManager::with_secure_store(store.clone());
        assert!(!manager.auto_start_enabled().expect("initial preference"));
        manager
            .start(
                &format!("http://{}", core_listener.local_addr().expect("core addr")),
                GatewayStartOptions {
                    bind_host: Some("127.0.0.1".to_string()),
                    port: Some(0),
                    ..Default::default()
                },
            )
            .expect("start");
        assert!(manager.auto_start_enabled().expect("enabled preference"));
        manager.shutdown().expect("shutdown");
        assert!(manager.auto_start_enabled().expect("preserved preference"));

        let restored = super::RemoteGatewayManager::with_secure_store(store);
        assert!(restored.auto_start_enabled().expect("restored preference"));
        restored.stop().expect("user stop");
        assert!(!restored.auto_start_enabled().expect("disabled preference"));
    }
}
