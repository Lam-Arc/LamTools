mod backup;
mod control;
mod push;

use std::{
    collections::{HashMap, HashSet},
    env,
    net::SocketAddr,
    sync::{
        atomic::{AtomicU64, Ordering},
        Arc,
    },
    time::{Duration, SystemTime, UNIX_EPOCH},
};

use axum::body::Body;
use axum::{
    extract::{
        ws::{Message, WebSocket, WebSocketUpgrade},
        Path, Query, State,
    },
    http::{header, HeaderMap, Method, Request, StatusCode},
    middleware::{self, Next},
    response::{IntoResponse, Response},
    routing::{delete, get, patch, post},
    Json, Router,
};
use futures_util::{SinkExt, StreamExt};
use serde::{Deserialize, Serialize};
use tokio::sync::{mpsc, RwLock};
use uuid::Uuid;

use control::{
    AuthContext, AuthTokens, ControlError, ControlPlane, GrantRequest, NodeRecord,
    NodeRegistration, NodeRegistrationResult, NodeUpdate, WorkspaceRecord, WorkspaceRegistration,
    WorkspaceUpdate,
};
use push::{DisabledPushProvider, PushProvider, PushSignal};

const MAX_QUEUE: usize = 128;
const TUNNEL_ID_BYTES: usize = 36;
const PAIRING_CODE_LENGTH: usize = 6;
const HEARTBEAT_INTERVAL: Duration = Duration::from_secs(25);
const HEARTBEAT_TIMEOUT: Duration = Duration::from_secs(12);

#[derive(Default)]
struct Metrics {
    bytes: AtomicU64,
    mobile_to_desktop_packets: AtomicU64,
    mobile_to_desktop_forwarded: AtomicU64,
    mobile_to_desktop_bytes: AtomicU64,
    desktop_to_mobile_packets: AtomicU64,
    desktop_to_mobile_forwarded: AtomicU64,
    desktop_to_mobile_bytes: AtomicU64,
    active_tunnels: AtomicU64,
    reconnects: AtomicU64,
    errors: AtomicU64,
}

struct RelayState {
    control: ControlPlane,
    desktops: RwLock<HashMap<String, DesktopRoute>>,
    mobiles: RwLock<HashMap<String, MobileRoute>>,
    pairings: RwLock<HashMap<String, PairingRoute>>,
    metrics: Metrics,
    push: Arc<dyn PushProvider>,
}

/// Relay intentionally logs only routing metadata.  Application frames are
/// Noise-encrypted and remain opaque to this process.
fn relay_trace(event: &str, fields: serde_json::Value) {
    let mut object = match fields {
        serde_json::Value::Object(object) => object,
        _ => serde_json::Map::new(),
    };
    object.insert(
        "component".to_string(),
        serde_json::Value::String("relay".to_string()),
    );
    object.insert(
        "event".to_string(),
        serde_json::Value::String(event.to_string()),
    );
    eprintln!("[lamtools-remote] {}", serde_json::Value::Object(object));
}

#[derive(Clone)]
struct DesktopRoute {
    connection_id: String,
    sender: mpsc::Sender<Message>,
}

#[derive(Clone)]
struct MobileRoute {
    target: String,
    sender: mpsc::Sender<Message>,
}

#[derive(Clone, Debug)]
struct PairingRoute {
    pairing_id: String,
    desktop_device_id: String,
    code: String,
    desktop_public_key: String,
    gateway_url: String,
    relay_url: Option<String>,
    expires_at_ms: u64,
    protocol: String,
    version: u8,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct PairingRegistration {
    pairing_id: String,
    code: String,
    desktop_device_id: String,
    desktop_public_key: String,
    gateway_url: String,
    #[serde(default)]
    relay_url: Option<String>,
    expires_at_ms: u64,
    protocol: String,
    version: u8,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct PairingResolveRequest {
    code: String,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct PairingResolveResponse {
    pairing_id: String,
    desktop_device_id: String,
    desktop_public_key: String,
    gateway_url: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    relay_url: Option<String>,
    relay_ticket: String,
    expires_at_ms: u64,
    protocol: String,
    version: u8,
}

#[derive(Deserialize)]
struct RelayQuery {
    role: String,
    device_id: String,
    target: Option<String>,
    ticket: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct AuthRequest {
    username: String,
    password: String,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct NodeRegistrationApiResponse {
    node: NodeRecord,
    workspace: Option<WorkspaceRecord>,
    tokens: AuthTokens,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct HealthResponse {
    status: &'static str,
    server_id: Option<String>,
    registration_mode: Option<String>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct ErrorResponse {
    error: String,
    code: &'static str,
    message: String,
}

#[tokio::main]
async fn main() {
    let mut arguments = env::args();
    let _program = arguments.next();
    match arguments.next().as_deref() {
        Some("backup") => {
            if let Err(error) = backup::run_backup_cli(arguments.collect()) {
                eprintln!("backup error: {error}");
                std::process::exit(1);
            }
            return;
        }
        Some("verify") => {
            if let Err(error) = backup::run_verify_cli(arguments.collect()) {
                eprintln!("verify error: {error}");
                std::process::exit(1);
            }
            return;
        }
        Some("help") | Some("--help") | Some("-h") => {
            println!("{}", backup::CLI_USAGE);
            return;
        }
        Some(command) => {
            eprintln!("unknown command: {command}");
            eprintln!("{}", backup::CLI_USAGE);
            std::process::exit(2);
        }
        None => {}
    }

    run_server().await;
}

async fn run_server() {
    let database_path =
        env::var("DATABASE_PATH").unwrap_or_else(|_| "data/lamtools.db".to_string());
    let control = ControlPlane::open(&database_path)
        .unwrap_or_else(|error| panic!("relay control plane failed: {error}"));
    let bind: SocketAddr = env::var("LAMTOOLS_RELAY_BIND")
        .unwrap_or_else(|_| "0.0.0.0:8787".to_string())
        .parse()
        .expect("LAMTOOLS_RELAY_BIND must be a socket address");
    let state = Arc::new(RelayState {
        control,
        desktops: RwLock::new(HashMap::new()),
        mobiles: RwLock::new(HashMap::new()),
        pairings: RwLock::new(HashMap::new()),
        metrics: Metrics::default(),
        push: Arc::new(DisabledPushProvider),
    });
    let app = build_router(state);

    let cert = env::var("LAMTOOLS_RELAY_TLS_CERT").ok();
    let key = env::var("LAMTOOLS_RELAY_TLS_KEY").ok();
    if let (Some(cert), Some(key)) = (cert, key) {
        let config = axum_server::tls_rustls::RustlsConfig::from_pem_file(cert, key)
            .await
            .expect("invalid relay TLS certificate");
        axum_server::bind_rustls(bind, config)
            .serve(app.into_make_service())
            .await
            .expect("relay server failed");
    } else {
        let listener = tokio::net::TcpListener::bind(bind)
            .await
            .expect("relay bind failed");
        axum::serve(listener, app)
            .await
            .expect("relay server failed");
    }
}

fn build_router(state: Arc<RelayState>) -> Router {
    Router::new()
        .route("/v1/relay", get(relay_upgrade))
        .route("/v1/relay/host", get(relay_upgrade))
        .route("/v1/relay/connect", get(relay_upgrade))
        .route("/v1/auth/register", post(auth_register))
        .route("/v1/auth/login", post(auth_login))
        .route("/v1/auth/refresh", post(auth_refresh))
        .route("/v1/auth/logout", post(auth_logout))
        .route("/v1/nodes", get(list_nodes))
        .route("/v1/nodes/register", post(register_node))
        .route("/v1/nodes/{node_id}", patch(update_node))
        .route("/v1/nodes/{node_id}/revoke", post(revoke_node))
        .route("/v1/workspaces", get(list_workspaces))
        .route("/v1/workspaces/register", post(register_workspace))
        .route("/v1/workspaces/{workspace_id}", patch(update_workspace))
        .route(
            "/v1/workspaces/{workspace_id}/connect-ticket",
            post(create_connection_ticket),
        )
        .route(
            "/v1/workspaces/{workspace_id}/grants",
            get(list_grants).post(create_grant),
        )
        .route(
            "/v1/workspaces/{workspace_id}/grants/{grant_id}",
            delete(revoke_grant),
        )
        .route(
            "/v1/pairing/resolve",
            post(resolve_pairing).options(resolve_pairing_options),
        )
        .route("/v1/presence/{device_id}", get(presence))
        .route("/v1/push", post(push_signal))
        .route("/health", get(health))
        .route("/healthz", get(health))
        .route("/readyz", get(ready))
        .route("/metrics", get(metrics))
        .fallback(cors_fallback)
        .with_state(state)
        .layer(middleware::from_fn(cors_middleware))
}

async fn auth_register(
    State(state): State<Arc<RelayState>>,
    Json(request): Json<AuthRequest>,
) -> Response {
    match state.control.register(&request.username, &request.password) {
        Ok(tokens) => json_response(StatusCode::OK, tokens),
        Err(error) => control_error_response(error),
    }
}

async fn auth_login(
    State(state): State<Arc<RelayState>>,
    Json(request): Json<AuthRequest>,
) -> Response {
    match state.control.login(&request.username, &request.password) {
        Ok(tokens) => json_response(StatusCode::OK, tokens),
        Err(error) => control_error_response(error),
    }
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct RefreshRequest {
    refresh_token: String,
}

async fn auth_refresh(
    State(state): State<Arc<RelayState>>,
    Json(request): Json<RefreshRequest>,
) -> Response {
    match state.control.refresh(&request.refresh_token) {
        Ok(tokens) => json_response(StatusCode::OK, tokens),
        Err(error) => control_error_response(error),
    }
}

async fn auth_logout(
    State(state): State<Arc<RelayState>>,
    headers: HeaderMap,
    Json(request): Json<RefreshRequest>,
) -> Response {
    if let Err(error) = require_bearer(&state.control, &headers) {
        return control_error_response(error);
    }
    match state.control.logout(&request.refresh_token) {
        Ok(()) => json_response(StatusCode::NO_CONTENT, serde_json::json!({})),
        Err(error) => control_error_response(error),
    }
}

async fn list_nodes(State(state): State<Arc<RelayState>>, headers: HeaderMap) -> Response {
    let auth = match require_bearer(&state.control, &headers) {
        Ok(auth) => auth,
        Err(error) => return control_error_response(error),
    };
    match state.control.list_nodes(&auth) {
        Ok(nodes) => json_response(StatusCode::OK, serde_json::json!({"nodes": nodes})),
        Err(error) => control_error_response(error),
    }
}

async fn register_node(
    State(state): State<Arc<RelayState>>,
    headers: HeaderMap,
    Json(request): Json<NodeRegistration>,
) -> Response {
    let access_token = match bearer_token(&headers) {
        Some(token) => token,
        None => {
            return control_error_response(ControlError::unauthorized(
                "AUTH_REQUIRED",
                "需要登录服务器账号",
            ))
        }
    };
    let auth = match state.control.authenticate(access_token) {
        Ok(auth) => auth,
        Err(error) => return control_error_response(error),
    };
    let result: NodeRegistrationResult = match state.control.register_node(&auth, request) {
        Ok(result) => result,
        Err(error) => return control_error_response(error),
    };
    let node_id = result.node.node_id.clone();
    let tokens = match state.control.bind_node_session(access_token, &node_id) {
        Ok(tokens) => tokens,
        Err(error) => return control_error_response(error),
    };
    json_response(
        StatusCode::OK,
        NodeRegistrationApiResponse {
            node: result.node,
            workspace: result.workspace,
            tokens,
        },
    )
}

async fn update_node(
    State(state): State<Arc<RelayState>>,
    headers: HeaderMap,
    Path(node_id): Path<String>,
    Json(request): Json<NodeUpdate>,
) -> Response {
    let auth = match require_bearer(&state.control, &headers) {
        Ok(auth) => auth,
        Err(error) => return control_error_response(error),
    };
    match state.control.update_node(&auth, &node_id, request) {
        Ok(node) => json_response(StatusCode::OK, serde_json::json!({"node": node})),
        Err(error) => control_error_response(error),
    }
}

async fn revoke_node(
    State(state): State<Arc<RelayState>>,
    headers: HeaderMap,
    Path(node_id): Path<String>,
) -> Response {
    let auth = match require_bearer(&state.control, &headers) {
        Ok(auth) => auth,
        Err(error) => return control_error_response(error),
    };
    match state.control.revoke_node(&auth, &node_id) {
        Ok(()) => json_response(StatusCode::NO_CONTENT, serde_json::json!({})),
        Err(error) => control_error_response(error),
    }
}

async fn list_workspaces(State(state): State<Arc<RelayState>>, headers: HeaderMap) -> Response {
    let auth = match require_bearer(&state.control, &headers) {
        Ok(auth) => auth,
        Err(error) => return control_error_response(error),
    };
    let online_nodes = online_node_ids(&state).await;
    match state.control.list_workspaces(&auth, &online_nodes) {
        Ok(workspaces) => json_response(
            StatusCode::OK,
            serde_json::json!({"workspaces": workspaces}),
        ),
        Err(error) => control_error_response(error),
    }
}

async fn register_workspace(
    State(state): State<Arc<RelayState>>,
    headers: HeaderMap,
    Json(request): Json<WorkspaceRegistration>,
) -> Response {
    let auth = match require_bearer(&state.control, &headers) {
        Ok(auth) => auth,
        Err(error) => return control_error_response(error),
    };
    match state.control.register_workspace(&auth, request) {
        Ok(workspace) => json_response(StatusCode::OK, workspace),
        Err(error) => control_error_response(error),
    }
}

async fn update_workspace(
    State(state): State<Arc<RelayState>>,
    headers: HeaderMap,
    Path(workspace_id): Path<String>,
    Json(request): Json<WorkspaceUpdate>,
) -> Response {
    let auth = match require_bearer(&state.control, &headers) {
        Ok(auth) => auth,
        Err(error) => return control_error_response(error),
    };
    match state
        .control
        .update_workspace(&auth, &workspace_id, request)
    {
        Ok(workspace) => json_response(StatusCode::OK, workspace),
        Err(error) => control_error_response(error),
    }
}

async fn create_connection_ticket(
    State(state): State<Arc<RelayState>>,
    headers: HeaderMap,
    Path(workspace_id): Path<String>,
) -> Response {
    let auth = match require_bearer(&state.control, &headers) {
        Ok(auth) => auth,
        Err(error) => return control_error_response(error),
    };
    let (_, target_host_node_id) = match state.control.workspace_access(&auth, &workspace_id) {
        Ok(value) => value,
        Err(error) => return control_error_response(error),
    };
    let online = state
        .desktops
        .read()
        .await
        .contains_key(&target_host_node_id);
    match state.control.create_ticket(&auth, &workspace_id, online) {
        Ok(ticket) => json_response(StatusCode::OK, ticket),
        Err(error) => control_error_response(error),
    }
}

async fn create_grant(
    State(state): State<Arc<RelayState>>,
    headers: HeaderMap,
    Path(workspace_id): Path<String>,
    Json(request): Json<GrantRequest>,
) -> Response {
    let auth = match require_bearer(&state.control, &headers) {
        Ok(auth) => auth,
        Err(error) => return control_error_response(error),
    };
    match state.control.create_grant(&auth, &workspace_id, request) {
        Ok(grant) => json_response(StatusCode::OK, grant),
        Err(error) => control_error_response(error),
    }
}

async fn list_grants(
    State(state): State<Arc<RelayState>>,
    headers: HeaderMap,
    Path(workspace_id): Path<String>,
) -> Response {
    let auth = match require_bearer(&state.control, &headers) {
        Ok(auth) => auth,
        Err(error) => return control_error_response(error),
    };
    match state.control.list_grants(&auth, &workspace_id) {
        Ok(grants) => json_response(StatusCode::OK, serde_json::json!({"grants": grants})),
        Err(error) => control_error_response(error),
    }
}

async fn revoke_grant(
    State(state): State<Arc<RelayState>>,
    headers: HeaderMap,
    Path((workspace_id, grant_id)): Path<(String, String)>,
) -> Response {
    let auth = match require_bearer(&state.control, &headers) {
        Ok(auth) => auth,
        Err(error) => return control_error_response(error),
    };
    match state.control.revoke_grant(&auth, &workspace_id, &grant_id) {
        Ok(()) => json_response(StatusCode::NO_CONTENT, serde_json::json!({})),
        Err(error) => control_error_response(error),
    }
}

fn bearer_token(headers: &HeaderMap) -> Option<&str> {
    headers
        .get(header::AUTHORIZATION)
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.strip_prefix("Bearer "))
        .map(str::trim)
        .filter(|value| !value.is_empty())
}

fn require_bearer(
    control: &ControlPlane,
    headers: &HeaderMap,
) -> Result<AuthContext, ControlError> {
    let token = bearer_token(headers)
        .ok_or_else(|| ControlError::unauthorized("AUTH_REQUIRED", "需要登录服务器账号"))?;
    control.authenticate(token)
}

async fn online_node_ids(state: &RelayState) -> HashSet<String> {
    state.desktops.read().await.keys().cloned().collect()
}

async fn health(State(state): State<Arc<RelayState>>) -> Response {
    json_response(
        StatusCode::OK,
        HealthResponse {
            status: "ok",
            server_id: Some(state.control.server_id().to_string()),
            registration_mode: Some(state.control.registration_mode().to_string()),
        },
    )
}

async fn ready(State(state): State<Arc<RelayState>>) -> Response {
    health(State(state)).await
}

async fn relay_upgrade(
    State(state): State<Arc<RelayState>>,
    headers: HeaderMap,
    Query(query): Query<RelayQuery>,
    ws: WebSocketUpgrade,
) -> Response {
    if query.role == "desktop" {
        let Some(credential) = bearer_token(&headers) else {
            state.metrics.errors.fetch_add(1, Ordering::Relaxed);
            return StatusCode::UNAUTHORIZED.into_response();
        };
        let auth = match state.control.authenticate(credential) {
            Ok(auth) => auth,
            Err(_) => {
                state.metrics.errors.fetch_add(1, Ordering::Relaxed);
                return StatusCode::UNAUTHORIZED.into_response();
            }
        };
        if auth.node_id.as_deref() != Some(query.device_id.as_str()) {
            state.metrics.errors.fetch_add(1, Ordering::Relaxed);
            return StatusCode::FORBIDDEN.into_response();
        }
        let nodes = match state.control.list_nodes(&auth) {
            Ok(nodes) => nodes,
            Err(_) => return StatusCode::INTERNAL_SERVER_ERROR.into_response(),
        };
        let Some(node) = nodes
            .into_iter()
            .find(|node| node.node_id == query.device_id)
        else {
            return StatusCode::FORBIDDEN.into_response();
        };
        if node.revoked_at_ms.is_some()
            || (!node
                .capabilities
                .iter()
                .any(|cap| cap == "workspace_host" || cap == "agent_runtime")
                && node.platform.to_ascii_lowercase().contains("mobile"))
        {
            return StatusCode::FORBIDDEN.into_response();
        }
        let _ = state.control.touch_node(&query.device_id);
        return ws.on_upgrade(move |socket| desktop_connection(state, query.device_id, socket));
    }
    if query.role == "mobile" {
        let Some(target) = query.target else {
            return StatusCode::BAD_REQUEST.into_response();
        };
        let Some(ticket) = query.ticket.as_deref() else {
            state.metrics.errors.fetch_add(1, Ordering::Relaxed);
            return StatusCode::UNAUTHORIZED.into_response();
        };
        let (pairing_id, target_host_node_id) =
            match state.control.consume_ticket(ticket, &query.device_id) {
                Ok(consumed) => (None, consumed.target_host_node_id),
                Err(_) => match state
                    .control
                    .consume_pairing_ticket(ticket, &query.device_id)
                {
                    Ok(consumed) => (Some(consumed.pairing_id), consumed.target_host_node_id),
                    Err(pairing_error) => {
                        state.metrics.errors.fetch_add(1, Ordering::Relaxed);
                        return control_error_response(pairing_error);
                    }
                },
            };
        if target_host_node_id != target {
            state.metrics.errors.fetch_add(1, Ordering::Relaxed);
            return StatusCode::FORBIDDEN.into_response();
        }
        if !state.desktops.read().await.contains_key(&target) {
            return StatusCode::SERVICE_UNAVAILABLE.into_response();
        }
        return ws.on_upgrade(move |socket| mobile_connection(state, target, pairing_id, socket));
    }
    StatusCode::BAD_REQUEST.into_response()
}

async fn desktop_connection(state: Arc<RelayState>, device_id: String, socket: WebSocket) {
    let (outgoing, mut receiver) = mpsc::channel(MAX_QUEUE);
    let control_sender = outgoing.clone();
    let connection_id = Uuid::new_v4().to_string();
    let previous = state.desktops.write().await.insert(
        device_id.clone(),
        DesktopRoute {
            connection_id: connection_id.clone(),
            sender: outgoing,
        },
    );
    relay_trace(
        "desktop_connected",
        serde_json::json!({"device_id": &device_id, "connection_id": &connection_id}),
    );
    if let Some(previous) = previous {
        state.metrics.reconnects.fetch_add(1, Ordering::Relaxed);
        // A device has one active desktop route. Close the old route and all
        // mobile tunnels attached to it so clients can re-select a fresh
        // transport instead of being left on a dead socket.
        let _ = previous.sender.try_send(Message::Close(None));
        close_mobile_tunnels_for_target(&state, &device_id).await;
    }
    clear_pairings_for_desktop(&state, &device_id).await;
    let (mut sink, mut source) = socket.split();
    let mut heartbeat = Box::pin(tokio::time::sleep(HEARTBEAT_INTERVAL));
    let mut awaiting_pong = false;
    loop {
        tokio::select! {
            _ = heartbeat.as_mut() => {
                if awaiting_pong { break }
                if sink.send(Message::Ping(Vec::new().into())).await.is_err() { break }
                awaiting_pong = true;
                heartbeat.as_mut().reset(tokio::time::Instant::now() + HEARTBEAT_TIMEOUT);
            },
            Some(message) = receiver.recv() => {
                let close = matches!(message, Message::Close(_));
                if sink.send(message).await.is_err() || close { break }
            },
            value = source.next() => match value {
                Some(Ok(Message::Binary(packet))) => route_to_mobile(&state, packet.to_vec()).await,
                Some(Ok(Message::Text(text))) => {
                    handle_desktop_control(&state, &device_id, &connection_id, text.as_ref()).await;
                }
                Some(Ok(Message::Ping(payload))) => {
                    if control_sender.send(Message::Pong(payload)).await.is_err() { break }
                }
                Some(Ok(Message::Pong(_))) => {
                    awaiting_pong = false;
                    heartbeat.as_mut().reset(tokio::time::Instant::now() + HEARTBEAT_INTERVAL);
                }
                Some(Ok(Message::Close(_))) | None => break,
                Some(Err(_)) => { state.metrics.errors.fetch_add(1, Ordering::Relaxed); break },
            }
        }
    }
    let removed_current_route = {
        let mut desktops = state.desktops.write().await;
        if desktops
            .get(&device_id)
            .is_some_and(|route| route.connection_id == connection_id)
        {
            desktops.remove(&device_id);
            true
        } else {
            false
        }
    };
    if removed_current_route {
        clear_pairings_for_desktop(&state, &device_id).await;
    }
    relay_trace(
        "desktop_disconnected",
        serde_json::json!({"device_id": &device_id, "connection_id": &connection_id}),
    );
}

async fn mobile_connection(
    state: Arc<RelayState>,
    target: String,
    pairing_id: Option<String>,
    socket: WebSocket,
) {
    let tunnel_id = Uuid::new_v4().to_string();
    let (outgoing, mut receiver) = mpsc::channel(MAX_QUEUE);
    let Some(desktop) = state
        .desktops
        .read()
        .await
        .get(&target)
        .map(|route| route.sender.clone())
    else {
        state.metrics.errors.fetch_add(1, Ordering::Relaxed);
        return;
    };
    state.mobiles.write().await.insert(
        tunnel_id.clone(),
        MobileRoute {
            target: target.clone(),
            sender: outgoing.clone(),
        },
    );
    state.metrics.active_tunnels.fetch_add(1, Ordering::Relaxed);
    relay_trace(
        "tunnel_opened",
        serde_json::json!({"direction": "mobile_to_desktop", "tunnel_id": tunnel_id}),
    );
    if desktop
        .send(control_message("open", &tunnel_id, pairing_id.as_deref()))
        .await
        .is_err()
    {
        state.mobiles.write().await.remove(&tunnel_id);
        state.metrics.active_tunnels.fetch_sub(1, Ordering::Relaxed);
        return;
    }
    let (mut sink, mut source) = socket.split();
    let mut heartbeat = Box::pin(tokio::time::sleep(HEARTBEAT_INTERVAL));
    let mut awaiting_pong = false;
    let bridge_ready = tokio::time::timeout(std::time::Duration::from_secs(10), async {
        loop {
            tokio::select! {
                _ = heartbeat.as_mut() => {
                    if awaiting_pong { break false }
                    if sink.send(Message::Ping(Vec::new().into())).await.is_err() { break false }
                    awaiting_pong = true;
                    heartbeat.as_mut().reset(tokio::time::Instant::now() + HEARTBEAT_TIMEOUT);
                }
                Some(message) = receiver.recv() => match message {
                    Message::Text(text) => {
                        let value: serde_json::Value = serde_json::from_str(&text).unwrap_or_default();
                        if value.get("type").and_then(|value| value.as_str()) == Some("bridge_ready")
                            && value.get("tunnel_id").and_then(|value| value.as_str()) == Some(tunnel_id.as_str())
                        {
                            relay_trace(
                                "tunnel_ready",
                                serde_json::json!({"tunnel_id": tunnel_id}),
                            );
                            break true;
                        }
                    }
                    Message::Close(_) => break false,
                    _ => {}
                },
                value = source.next() => match value {
                    Some(Ok(Message::Ping(payload))) => {
                        if outgoing.send(Message::Pong(payload)).await.is_err() { break false }
                    }
                    Some(Ok(Message::Pong(_))) => {
                        awaiting_pong = false;
                        heartbeat.as_mut().reset(tokio::time::Instant::now() + HEARTBEAT_INTERVAL);
                    }
                    Some(Ok(Message::Close(_))) | None => break false,
                    Some(Err(_)) => break false,
                    _ => {}
                }
            }
        }
    }).await.ok().unwrap_or(false);
    if !bridge_ready
        || sink
            .send(control_message("ready", &tunnel_id, None))
            .await
            .is_err()
    {
        state.mobiles.write().await.remove(&tunnel_id);
        state.metrics.active_tunnels.fetch_sub(1, Ordering::Relaxed);
        let _ = desktop
            .send(control_message("close", &tunnel_id, None))
            .await;
        return;
    }
    loop {
        tokio::select! {
            _ = heartbeat.as_mut() => {
                if awaiting_pong { break }
                if sink.send(Message::Ping(Vec::new().into())).await.is_err() { break }
                awaiting_pong = true;
                heartbeat.as_mut().reset(tokio::time::Instant::now() + HEARTBEAT_TIMEOUT);
            },
            Some(message) = receiver.recv() => {
                let close = matches!(message, Message::Close(_));
                if sink.send(message).await.is_err() || close { break }
            },
            value = source.next() => match value {
                Some(Ok(Message::Binary(packet))) => {
                    state.metrics.bytes.fetch_add(packet.len() as u64, Ordering::Relaxed);
                    state.metrics.mobile_to_desktop_packets.fetch_add(1, Ordering::Relaxed);
                    state.metrics.mobile_to_desktop_bytes.fetch_add(packet.len() as u64, Ordering::Relaxed);
                    if packet.len() < TUNNEL_ID_BYTES || &packet[..TUNNEL_ID_BYTES] != tunnel_id.as_bytes() {
                        state.metrics.errors.fetch_add(1, Ordering::Relaxed);
                        relay_trace(
                            "packet_dropped",
                            serde_json::json!({
                                "direction": "mobile_to_desktop",
                                "tunnel_id": tunnel_id,
                                "bytes": packet.len(),
                                "reason": "invalid_tunnel_id",
                            }),
                        );
                        break;
                    }
                    relay_trace(
                        "packet_received",
                        serde_json::json!({
                            "direction": "mobile_to_desktop",
                            "tunnel_id": tunnel_id,
                            "bytes": packet.len(),
                        }),
                    );
                    if desktop.send(Message::Binary(packet)).await.is_err() {
                        state.metrics.errors.fetch_add(1, Ordering::Relaxed);
                        break;
                    }
                    state.metrics.mobile_to_desktop_forwarded.fetch_add(1, Ordering::Relaxed);
                    relay_trace(
                        "packet_forwarded",
                        serde_json::json!({
                            "direction": "mobile_to_desktop",
                            "tunnel_id": tunnel_id,
                        }),
                    );
                }
                Some(Ok(Message::Ping(payload))) => {
                    if outgoing.send(Message::Pong(payload)).await.is_err() { break }
                }
                Some(Ok(Message::Pong(_))) => {
                    awaiting_pong = false;
                    heartbeat.as_mut().reset(tokio::time::Instant::now() + HEARTBEAT_INTERVAL);
                }
                Some(Ok(Message::Close(_))) | None => break,
                Some(Err(_)) => { state.metrics.errors.fetch_add(1, Ordering::Relaxed); break },
                _ => {}
            }
        }
    }
    let removed = state.mobiles.write().await.remove(&tunnel_id).is_some();
    if removed {
        state.metrics.active_tunnels.fetch_sub(1, Ordering::Relaxed);
    }
    let _ = desktop
        .send(control_message("close", &tunnel_id, None))
        .await;
    relay_trace("tunnel_closed", serde_json::json!({"tunnel_id": tunnel_id}));
}

async fn handle_desktop_control(
    state: &RelayState,
    device_id: &str,
    connection_id: &str,
    text: &str,
) {
    let Ok(value) = serde_json::from_str::<serde_json::Value>(text) else {
        state.metrics.errors.fetch_add(1, Ordering::Relaxed);
        return;
    };
    let kind = value
        .get("type")
        .and_then(|value| value.as_str())
        .unwrap_or_default();
    if kind == "bridge_ready" {
        let tunnel_id = value
            .get("tunnel_id")
            .and_then(|value| value.as_str())
            .unwrap_or_default();
        if tunnel_id.len() != TUNNEL_ID_BYTES {
            state.metrics.errors.fetch_add(1, Ordering::Relaxed);
            return;
        }
        let current = state
            .desktops
            .read()
            .await
            .get(device_id)
            .is_some_and(|route| route.connection_id == connection_id);
        if current {
            route_control_to_mobile(state, tunnel_id, "bridge_ready").await;
        }
        return;
    }
    if kind != "pairing_register" {
        return;
    }
    let Ok(registration) = serde_json::from_value::<PairingRegistration>(value) else {
        state.metrics.errors.fetch_add(1, Ordering::Relaxed);
        return;
    };
    register_pairing(state, device_id, connection_id, registration).await;
}

async fn route_control_to_mobile(state: &RelayState, tunnel_id: &str, kind: &str) {
    if let Some(mobile) = state.mobiles.read().await.get(tunnel_id).cloned() {
        if mobile
            .sender
            .send(control_message(kind, tunnel_id, None))
            .await
            .is_err()
        {
            state.metrics.errors.fetch_add(1, Ordering::Relaxed);
        }
    }
}

async fn register_pairing(
    state: &RelayState,
    device_id: &str,
    connection_id: &str,
    registration: PairingRegistration,
) {
    let is_current_connection = state
        .desktops
        .read()
        .await
        .get(device_id)
        .is_some_and(|route| route.connection_id == connection_id);
    if !is_current_connection
        || registration.desktop_device_id != device_id
        || registration.pairing_id.trim().is_empty()
        || registration.pairing_id.len() > 128
        || !is_valid_pairing_code(&registration.code)
        || registration.desktop_public_key.trim().is_empty()
        || registration.gateway_url.trim().is_empty()
        || registration.expires_at_ms <= now_ms()
        || registration.protocol != "lamtools-remote"
        || registration.version != 1
    {
        state.metrics.errors.fetch_add(1, Ordering::Relaxed);
        return;
    }

    let mut pairings = state.pairings.write().await;
    let now = now_ms();
    pairings.retain(|_, route| route.expires_at_ms > now);
    if pairings.values().any(|route| {
        route.desktop_device_id != device_id
            && constant_time_eq(route.code.as_bytes(), registration.code.as_bytes())
    }) {
        // A six-digit code must be unambiguous within one Relay. The desktop
        // will keep its local code authoritative, so rejecting a collision is
        // safer than routing a phone to the wrong desktop.
        state.metrics.errors.fetch_add(1, Ordering::Relaxed);
        return;
    }
    pairings.retain(|_, route| route.desktop_device_id != device_id);
    pairings.insert(
        registration.pairing_id.clone(),
        PairingRoute {
            pairing_id: registration.pairing_id,
            desktop_device_id: registration.desktop_device_id,
            code: registration.code,
            desktop_public_key: registration.desktop_public_key,
            gateway_url: registration.gateway_url,
            relay_url: registration.relay_url,
            expires_at_ms: registration.expires_at_ms,
            protocol: registration.protocol,
            version: registration.version,
        },
    );
}

async fn clear_pairings_for_desktop(state: &RelayState, device_id: &str) {
    state
        .pairings
        .write()
        .await
        .retain(|_, route| route.desktop_device_id != device_id);
}

async fn route_to_mobile(state: &RelayState, packet: Vec<u8>) {
    state
        .metrics
        .bytes
        .fetch_add(packet.len() as u64, Ordering::Relaxed);
    if packet.len() < TUNNEL_ID_BYTES {
        state.metrics.errors.fetch_add(1, Ordering::Relaxed);
        relay_trace(
            "packet_dropped",
            serde_json::json!({
                "direction": "desktop_to_mobile",
                "bytes": packet.len(),
                "reason": "missing_tunnel_id",
            }),
        );
        return;
    }
    let id = match std::str::from_utf8(&packet[..TUNNEL_ID_BYTES]) {
        Ok(id) => id.to_string(),
        Err(_) => {
            state.metrics.errors.fetch_add(1, Ordering::Relaxed);
            relay_trace(
                "packet_dropped",
                serde_json::json!({
                    "direction": "desktop_to_mobile",
                    "bytes": packet.len(),
                    "reason": "invalid_tunnel_id",
                }),
            );
            return;
        }
    };
    state
        .metrics
        .desktop_to_mobile_packets
        .fetch_add(1, Ordering::Relaxed);
    state
        .metrics
        .desktop_to_mobile_bytes
        .fetch_add(packet.len() as u64, Ordering::Relaxed);
    relay_trace(
        "packet_received",
        serde_json::json!({
            "direction": "desktop_to_mobile",
            "tunnel_id": &id,
            "bytes": packet.len(),
        }),
    );
    if let Some(mobile) = state.mobiles.read().await.get(&id).cloned() {
        if mobile
            .sender
            .send(Message::Binary(packet.into()))
            .await
            .is_err()
        {
            state.metrics.errors.fetch_add(1, Ordering::Relaxed);
        } else {
            state
                .metrics
                .desktop_to_mobile_forwarded
                .fetch_add(1, Ordering::Relaxed);
            relay_trace(
                "packet_forwarded",
                serde_json::json!({
                    "direction": "desktop_to_mobile",
                    "tunnel_id": &id,
                }),
            );
        }
    } else {
        relay_trace(
            "packet_dropped",
            serde_json::json!({
                "direction": "desktop_to_mobile",
                "tunnel_id": &id,
                "bytes": packet.len(),
                "reason": "tunnel_not_found",
            }),
        );
    }
}

async fn close_mobile_tunnels_for_target(state: &RelayState, target: &str) {
    let stale = {
        let mut mobiles = state.mobiles.write().await;
        let ids = mobiles
            .iter()
            .filter(|(_, route)| route.target == target)
            .map(|(id, _)| id.clone())
            .collect::<Vec<_>>();
        ids.into_iter()
            .filter_map(|id| mobiles.remove(&id))
            .collect::<Vec<_>>()
    };
    for route in stale {
        state.metrics.active_tunnels.fetch_sub(1, Ordering::Relaxed);
        let _ = route.sender.try_send(Message::Close(None));
    }
}

fn control_message(kind: &str, tunnel_id: &str, pairing_id: Option<&str>) -> Message {
    let mut value = serde_json::json!({
        "type": kind,
        "tunnel_id": tunnel_id,
    });
    if let Some(pairing_id) = pairing_id {
        value["pairing_id"] = serde_json::Value::String(pairing_id.to_string());
    }
    Message::Text(value.to_string().into())
}

async fn presence(
    State(state): State<Arc<RelayState>>,
    headers: HeaderMap,
    Path(device_id): Path<String>,
) -> Response {
    if let Err(error) = require_bearer(&state.control, &headers) {
        return control_error_response(error);
    }
    json_response(
        StatusCode::OK,
        serde_json::json!({"online": state.desktops.read().await.contains_key(&device_id)}),
    )
}

async fn resolve_pairing(
    State(state): State<Arc<RelayState>>,
    headers: HeaderMap,
    Json(request): Json<PairingResolveRequest>,
) -> Response {
    let auth = match require_bearer(&state.control, &headers) {
        Ok(auth) => auth,
        Err(error) => {
            state.metrics.errors.fetch_add(1, Ordering::Relaxed);
            return control_error_response(error);
        }
    };
    let Some(_source_node_id) = auth.node_id.as_deref() else {
        state.metrics.errors.fetch_add(1, Ordering::Relaxed);
        return control_error_response(ControlError::bad_request(
            "NODE_REQUIRED",
            "当前账号会话尚未绑定 Node",
        ));
    };
    let code = request.code.trim();
    if !is_valid_pairing_code(code) {
        return json_response(
            StatusCode::BAD_REQUEST,
            serde_json::json!({"error": "配对码必须是六位数字"}),
        );
    }
    let now = now_ms();
    let pairing = {
        let mut pairings = state.pairings.write().await;
        pairings.retain(|_, route| route.expires_at_ms > now);
        pairings
            .values()
            .find(|route| constant_time_eq(route.code.as_bytes(), code.as_bytes()))
            .cloned()
    };
    let Some(pairing) = pairing else {
        return json_response(
            StatusCode::NOT_FOUND,
            serde_json::json!({"error": "配对码无效、已过期或电脑未连接"}),
        );
    };
    let online = state
        .desktops
        .read()
        .await
        .contains_key(&pairing.desktop_device_id);
    let relay_ticket = match state.control.create_pairing_ticket(
        &auth,
        &pairing.pairing_id,
        &pairing.desktop_device_id,
        online,
    ) {
        Ok(ticket) => ticket,
        Err(error) => {
            state.metrics.errors.fetch_add(1, Ordering::Relaxed);
            return control_error_response(error);
        }
    };
    json_response(
        StatusCode::OK,
        PairingResolveResponse {
            pairing_id: pairing.pairing_id,
            desktop_device_id: pairing.desktop_device_id,
            desktop_public_key: pairing.desktop_public_key,
            gateway_url: pairing.gateway_url,
            relay_url: pairing.relay_url,
            relay_ticket: relay_ticket.ticket,
            expires_at_ms: pairing.expires_at_ms,
            protocol: pairing.protocol,
            version: pairing.version,
        },
    )
}

async fn resolve_pairing_options() -> Response {
    (StatusCode::NO_CONTENT, cors_headers()).into_response()
}

fn is_valid_pairing_code(value: &str) -> bool {
    value.len() == PAIRING_CODE_LENGTH && value.bytes().all(|byte| byte.is_ascii_digit())
}

fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}

fn cors_headers() -> [(header::HeaderName, &'static str); 6] {
    [
        (header::ACCESS_CONTROL_ALLOW_ORIGIN, "*"),
        (
            header::ACCESS_CONTROL_ALLOW_HEADERS,
            "Authorization, Cache-Control, Content-Type",
        ),
        (
            header::ACCESS_CONTROL_ALLOW_METHODS,
            "GET, POST, PATCH, DELETE, OPTIONS",
        ),
        (
            header::HeaderName::from_static("access-control-allow-private-network"),
            "true",
        ),
        (header::ACCESS_CONTROL_MAX_AGE, "600"),
        (header::CACHE_CONTROL, "no-store"),
    ]
}

async fn cors_middleware(request: Request<Body>, next: Next) -> Response {
    if request.method() == Method::OPTIONS {
        let mut response = StatusCode::NO_CONTENT.into_response();
        apply_cors_headers(&mut response);
        return response;
    }
    let mut response = next.run(request).await;
    apply_cors_headers(&mut response);
    response
}

async fn cors_fallback(request: Request<Body>) -> Response {
    let mut response = if request.method() == Method::OPTIONS {
        StatusCode::NO_CONTENT.into_response()
    } else {
        StatusCode::NOT_FOUND.into_response()
    };
    apply_cors_headers(&mut response);
    response
}

fn apply_cors_headers(response: &mut Response) {
    let headers = response.headers_mut();
    for (name, value) in cors_headers() {
        headers.insert(name, axum::http::HeaderValue::from_static(value));
    }
}

fn json_response<T: Serialize>(status: StatusCode, value: T) -> Response {
    (status, cors_headers(), Json(value)).into_response()
}

fn control_error_response(error: ControlError) -> Response {
    let status = StatusCode::from_u16(error.status).unwrap_or(StatusCode::INTERNAL_SERVER_ERROR);
    json_response(
        status,
        ErrorResponse {
            error: error.message.clone(),
            code: error.code,
            message: error.message,
        },
    )
}

async fn push_signal(
    State(state): State<Arc<RelayState>>,
    Json(signal): Json<PushSignal>,
) -> Response {
    if !state.push.enabled() {
        return json_response(
            StatusCode::SERVICE_UNAVAILABLE,
            serde_json::json!({"status":"disabled"}),
        );
    }
    match state.push.send(&signal) {
        Ok(()) => json_response(StatusCode::OK, serde_json::json!({"status":"sent"})),
        Err(_) => json_response(
            StatusCode::BAD_GATEWAY,
            serde_json::json!({"error":"push provider failed"}),
        ),
    }
}

async fn metrics(State(state): State<Arc<RelayState>>) -> Response {
    let body = format!(
        "lamtools_relay_online_devices {}\nlamtools_relay_active_tunnels {}\nlamtools_relay_bytes_total {}\nlamtools_relay_mobile_to_desktop_packets_total {}\nlamtools_relay_mobile_to_desktop_forwarded_total {}\nlamtools_relay_mobile_to_desktop_bytes_total {}\nlamtools_relay_desktop_to_mobile_packets_total {}\nlamtools_relay_desktop_to_mobile_forwarded_total {}\nlamtools_relay_desktop_to_mobile_bytes_total {}\nlamtools_relay_reconnects_total {}\nlamtools_relay_errors_total {}\n",
        state.desktops.read().await.len(),
        state.metrics.active_tunnels.load(Ordering::Relaxed),
        state.metrics.bytes.load(Ordering::Relaxed),
        state.metrics.mobile_to_desktop_packets.load(Ordering::Relaxed),
        state.metrics.mobile_to_desktop_forwarded.load(Ordering::Relaxed),
        state.metrics.mobile_to_desktop_bytes.load(Ordering::Relaxed),
        state.metrics.desktop_to_mobile_packets.load(Ordering::Relaxed),
        state.metrics.desktop_to_mobile_forwarded.load(Ordering::Relaxed),
        state.metrics.desktop_to_mobile_bytes.load(Ordering::Relaxed),
        state.metrics.reconnects.load(Ordering::Relaxed),
        state.metrics.errors.load(Ordering::Relaxed),
    );
    let mut response = (StatusCode::OK, body).into_response();
    apply_cors_headers(&mut response);
    response
}

fn constant_time_eq(left: &[u8], right: &[u8]) -> bool {
    if left.len() != right.len() {
        return false;
    }
    let mut difference = 0_u8;
    for (a, b) in left.iter().zip(right) {
        difference |= a ^ b;
    }
    difference == 0
}

#[cfg(test)]
mod tests {
    use super::{
        build_router, close_mobile_tunnels_for_target, constant_time_eq, DesktopRoute, Metrics,
        MobileRoute, RelayState,
    };
    use crate::control::{ControlPlane, NodeRegistration};
    use futures_util::{SinkExt, StreamExt};
    use std::{
        net::SocketAddr,
        sync::{atomic::Ordering, Arc},
    };
    use tokio::sync::{mpsc, RwLock};
    use tokio_tungstenite::{
        connect_async,
        tungstenite::{client::IntoClientRequest, http::header, Message},
    };

    use crate::push::DisabledPushProvider;

    struct TestSetup {
        control: ControlPlane,
        desktop_token: String,
        mobile_token: String,
        workspace_id: String,
    }

    fn test_setup() -> TestSetup {
        let path =
            std::env::temp_dir().join(format!("lamtools-relay-test-{}.db", uuid::Uuid::new_v4()));
        let control = ControlPlane::open(path).expect("control plane");
        let account = control
            .register("relay-owner", "correct horse battery")
            .expect("account");
        let auth = control
            .authenticate(&account.access_token)
            .expect("account auth");
        let desktop = control
            .register_node(
                &auth,
                NodeRegistration {
                    node_id: "desktop-test".to_string(),
                    public_key: "desktop-key".to_string(),
                    display_name: "Desktop".to_string(),
                    platform: "desktop".to_string(),
                    capabilities: vec!["workspace_host".to_string(), "agent_runtime".to_string()],
                },
            )
            .expect("desktop node");
        let desktop_token = control
            .bind_node_session(&account.access_token, &desktop.node.node_id)
            .expect("desktop session")
            .access_token;
        let mobile = control
            .register_node(
                &auth,
                NodeRegistration {
                    node_id: "mobile-test".to_string(),
                    public_key: "mobile-key".to_string(),
                    display_name: "Mobile".to_string(),
                    platform: "mobile".to_string(),
                    capabilities: vec!["workspace_client".to_string()],
                },
            )
            .expect("mobile node");
        let mobile_token = control
            .bind_node_session(&account.access_token, &mobile.node.node_id)
            .expect("mobile session")
            .access_token;
        TestSetup {
            control,
            desktop_token,
            mobile_token,
            workspace_id: desktop.workspace.expect("workspace").workspace_id,
        }
    }

    fn test_state(setup: &TestSetup) -> Arc<RelayState> {
        Arc::new(RelayState {
            control: setup.control.clone(),
            desktops: RwLock::new(std::collections::HashMap::new()),
            mobiles: RwLock::new(std::collections::HashMap::new()),
            pairings: RwLock::new(std::collections::HashMap::new()),
            metrics: Metrics::default(),
            push: Arc::new(DisabledPushProvider),
        })
    }

    fn authorized_ws_request(
        url: &str,
        token: &str,
    ) -> tokio_tungstenite::tungstenite::http::Request<()> {
        let mut request = url
            .to_string()
            .into_client_request()
            .expect("websocket request");
        request.headers_mut().insert(
            header::AUTHORIZATION,
            format!("Bearer {token}")
                .parse()
                .expect("authorization header"),
        );
        request
    }

    fn issue_connection_ticket(setup: &TestSetup) -> String {
        let auth = setup
            .control
            .authenticate(&setup.mobile_token)
            .expect("mobile auth");
        setup
            .control
            .create_ticket(&auth, &setup.workspace_id, true)
            .expect("connection ticket")
            .ticket
    }

    async fn start_server(state: Arc<RelayState>) -> (SocketAddr, tokio::task::JoinHandle<()>) {
        let app = build_router(state);
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
            .await
            .expect("relay listener");
        let address = listener.local_addr().expect("relay address");
        let server = tokio::spawn(async move {
            axum::serve(listener, app).await.expect("relay server");
        });
        (address, server)
    }

    async fn next_open(
        desktop: &mut (impl StreamExt<Item = Result<Message, tokio_tungstenite::tungstenite::Error>>
                  + Unpin),
    ) -> String {
        loop {
            match desktop
                .next()
                .await
                .expect("desktop open")
                .expect("desktop frame")
            {
                Message::Text(text) => {
                    let value: serde_json::Value = serde_json::from_str(&text).expect("open json");
                    if value["type"] == "open" {
                        return value["tunnel_id"].as_str().expect("tunnel id").to_string();
                    }
                }
                Message::Ping(_) | Message::Pong(_) => {}
                other => panic!("unexpected desktop frame: {other:?}"),
            }
        }
    }

    async fn next_ready(
        mobile: &mut (impl StreamExt<Item = Result<Message, tokio_tungstenite::tungstenite::Error>>
                  + Unpin),
    ) -> String {
        loop {
            match mobile
                .next()
                .await
                .expect("mobile ready")
                .expect("mobile frame")
            {
                Message::Text(text) => {
                    let value: serde_json::Value = serde_json::from_str(&text).expect("ready json");
                    if value["type"] == "ready" {
                        return value["tunnel_id"]
                            .as_str()
                            .expect("ready tunnel id")
                            .to_string();
                    }
                }
                Message::Ping(_) | Message::Pong(_) => {}
                other => panic!("unexpected mobile frame: {other:?}"),
            }
        }
    }

    #[test]
    fn credentials_use_constant_time_comparison() {
        assert!(constant_time_eq(b"relay-token", b"relay-token"));
        assert!(!constant_time_eq(b"relay-token", b"other-token"));
    }

    #[tokio::test]
    async fn closing_a_desktop_removes_its_mobile_tunnels_from_metrics() {
        let setup = test_setup();
        let state = Arc::new(RelayState {
            control: setup.control,
            desktops: RwLock::new(std::collections::HashMap::from([(
                "desktop-metrics".to_string(),
                DesktopRoute {
                    connection_id: "desktop-connection".to_string(),
                    sender: mpsc::channel(1).0,
                },
            )])),
            mobiles: RwLock::new(std::collections::HashMap::new()),
            pairings: RwLock::new(std::collections::HashMap::new()),
            metrics: Metrics::default(),
            push: Arc::new(DisabledPushProvider),
        });
        let (first_sender, mut first_receiver) = mpsc::channel(1);
        let (second_sender, mut second_receiver) = mpsc::channel(1);
        state.mobiles.write().await.extend([
            (
                "tunnel-metrics-1".to_string(),
                MobileRoute {
                    target: "desktop-metrics".to_string(),
                    sender: first_sender,
                },
            ),
            (
                "tunnel-metrics-2".to_string(),
                MobileRoute {
                    target: "desktop-metrics".to_string(),
                    sender: second_sender,
                },
            ),
        ]);
        state.metrics.active_tunnels.store(2, Ordering::Relaxed);

        close_mobile_tunnels_for_target(&state, "desktop-metrics").await;

        assert!(state.mobiles.read().await.is_empty());
        assert_eq!(state.metrics.active_tunnels.load(Ordering::Relaxed), 0);
        assert!(matches!(
            first_receiver.recv().await,
            Some(axum::extract::ws::Message::Close(_))
        ));
        assert!(matches!(
            second_receiver.recv().await,
            Some(axum::extract::ws::Message::Close(_))
        ));
    }

    /// Exercises the complete relay routing contract with two real websocket
    /// clients.  The payload is deliberately opaque: this test proves that a
    /// mobile packet reaches the desktop gateway connection (and back) with
    /// its 36-byte tunnel id intact, without teaching the relay anything
    /// about LamTools/App Server messages.
    #[tokio::test]
    async fn routes_opaque_packets_between_mobile_and_desktop() {
        let setup = test_setup();
        let state = test_state(&setup);
        let (address, server) = start_server(state).await;

        let desktop_url = format!(
            "ws://{}/v1/relay?role=desktop&device_id=desktop-test",
            address
        );
        let (mut desktop, _) =
            connect_async(authorized_ws_request(&desktop_url, &setup.desktop_token))
                .await
                .expect("desktop relay socket");

        let ticket = issue_connection_ticket(&setup);
        let mobile_url = format!(
            "ws://{}/v1/relay?role=mobile&device_id=mobile-test&target=desktop-test&ticket={ticket}", address
        );
        let (mut mobile, _) = connect_async(mobile_url)
            .await
            .expect("mobile relay socket");

        let tunnel_id = next_open(&mut desktop).await;
        desktop
            .send(Message::Text(
                serde_json::json!({"type":"bridge_ready","tunnel_id":tunnel_id})
                    .to_string()
                    .into(),
            ))
            .await
            .expect("bridge ready");
        let ready = next_ready(&mut mobile).await;
        assert_eq!(tunnel_id, ready);
        assert_eq!(tunnel_id.len(), 36);

        let mut packet = tunnel_id.as_bytes().to_vec();
        packet.extend_from_slice(b"opaque-noise-payload");
        mobile
            .send(Message::Binary(packet.clone().into()))
            .await
            .expect("mobile send");
        assert_eq!(
            desktop
                .next()
                .await
                .expect("desktop packet")
                .expect("desktop frame"),
            Message::Binary(packet.clone().into())
        );

        desktop
            .send(Message::Binary(packet.clone().into()))
            .await
            .expect("desktop send");
        assert_eq!(
            mobile
                .next()
                .await
                .expect("mobile packet")
                .expect("mobile frame"),
            Message::Binary(packet.into())
        );

        let metrics_url = format!("http://{address}/metrics");
        let metrics = reqwest_like_request(&metrics_url, "GET", &[], "").await;
        assert!(metrics.contains("lamtools_relay_mobile_to_desktop_packets_total 1"));
        assert!(metrics.contains("lamtools_relay_mobile_to_desktop_forwarded_total 1"));
        assert!(metrics.contains("lamtools_relay_desktop_to_mobile_packets_total 1"));
        assert!(metrics.contains("lamtools_relay_desktop_to_mobile_forwarded_total 1"));

        let presence_url = format!("http://{}/v1/presence/desktop-test", address);
        let presence = reqwest_like_request(
            &presence_url,
            "GET",
            &[("Authorization", &format!("Bearer {}", setup.desktop_token))],
            "",
        )
        .await;
        assert!(presence.contains("\"online\":true"));

        let _ = mobile.close(None).await;
        let _ = desktop.close(None).await;
        server.abort();
        let _ = server.await;
    }

    #[tokio::test]
    async fn resolves_registered_numeric_pairing_only_with_bearer_token() {
        let setup = test_setup();
        let state = test_state(&setup);
        let (address, server) = start_server(state.clone()).await;

        let desktop_url = format!("ws://{address}/v1/relay?role=desktop&device_id=desktop-test");
        let (mut desktop, _) =
            connect_async(authorized_ws_request(&desktop_url, &setup.desktop_token))
                .await
                .expect("desktop relay socket");
        desktop
            .send(Message::Text(
                serde_json::json!({
                    "type": "pairing_register",
                    "pairingId": "pairing-resolve",
                    "code": "012345",
                    "desktopDeviceId": "desktop-test",
                    "desktopPublicKey": "desktop-public-key",
                    "gatewayUrl": "ws://192.168.1.20:43123/_lamtools/tunnel",
                    "relayUrl": format!("ws://{address}/v1/relay/connect"),
                    "expiresAtMs": super::now_ms() + 300_000,
                    "protocol": "lamtools-remote",
                    "version": 1,
                })
                .to_string()
                .into(),
            ))
            .await
            .expect("pairing registration");

        let pairing_deadline = tokio::time::Instant::now() + std::time::Duration::from_secs(1);
        loop {
            if state.pairings.read().await.contains_key("pairing-resolve") {
                break;
            }
            assert!(
                tokio::time::Instant::now() < pairing_deadline,
                "pairing registration was not stored"
            );
            tokio::time::sleep(std::time::Duration::from_millis(5)).await;
        }

        let resolve_url = format!("http://{address}/v1/pairing/resolve");
        let unauthorized = reqwest_like_request(
            &resolve_url,
            "POST",
            &[("Content-Type", "application/json")],
            r#"{"code":"012345"}"#,
        )
        .await;
        assert!(unauthorized.starts_with("HTTP/1.1 401"));

        let response = reqwest_like_request(
            &resolve_url,
            "POST",
            &[
                ("Authorization", &format!("Bearer {}", setup.mobile_token)),
                ("Content-Type", "application/json"),
            ],
            r#"{"code":"012345"}"#,
        )
        .await;
        assert!(response.starts_with("HTTP/1.1 200"));
        assert!(response.contains("access-control-allow-origin: *"));
        assert!(response.contains("\"pairingId\":\"pairing-resolve\""));
        assert!(!response.contains("\"code\""));
        assert!(response.contains("\"desktopDeviceId\":\"desktop-test\""));
        assert!(response.contains("\"desktopPublicKey\":\"desktop-public-key\""));
        assert!(response.contains("\"relayTicket\":"));

        let body = response.split("\r\n\r\n").nth(1).expect("response body");
        let resolved: serde_json::Value = serde_json::from_str(body).expect("resolved json");
        let relay_ticket = resolved["relayTicket"].as_str().expect("relay ticket");
        let mobile_url = format!(
            "ws://{address}/v1/relay/connect?role=mobile&device_id=mobile-test&target=desktop-test&ticket={relay_ticket}"
        );
        let (mut mobile, _) = connect_async(mobile_url)
            .await
            .expect("mobile relay pair socket");
        let tunnel_id = next_open(&mut desktop).await;
        desktop
            .send(Message::Text(
                serde_json::json!({"type":"bridge_ready","tunnel_id":tunnel_id})
                    .to_string()
                    .into(),
            ))
            .await
            .expect("pair bridge ready");
        assert_eq!(next_ready(&mut mobile).await, tunnel_id);

        let malformed = reqwest_like_request(
            &resolve_url,
            "POST",
            &[
                ("Authorization", &format!("Bearer {}", setup.mobile_token)),
                ("Content-Type", "application/json"),
            ],
            r#"{"code":"12345"}"#,
        )
        .await;
        assert!(malformed.starts_with("HTTP/1.1 400"));

        let _ = desktop.close(None).await;
        server.abort();
        let _ = server.await;
    }

    #[tokio::test]
    async fn stale_desktop_cleanup_does_not_remove_a_replacement_route() {
        let setup = test_setup();
        let state = test_state(&setup);
        let (address, server) = start_server(state).await;

        let desktop_url = format!("ws://{address}/v1/relay?role=desktop&device_id=desktop-test");
        let (mut old_desktop, _) =
            connect_async(authorized_ws_request(&desktop_url, &setup.desktop_token))
                .await
                .expect("old desktop socket");
        let (mut new_desktop, _) =
            connect_async(authorized_ws_request(&desktop_url, &setup.desktop_token))
                .await
                .expect("replacement desktop socket");

        // Replacing the route closes the old socket. Its eventual cleanup is
        // deliberately allowed to race with the new route registration.
        let _ = old_desktop.next().await;
        let _ = old_desktop.close(None).await;

        let ticket = issue_connection_ticket(&setup);
        let mobile_url = format!(
            "ws://{address}/v1/relay?role=mobile&device_id=mobile-test&target=desktop-test&ticket={ticket}"
        );
        let (mut mobile, _) = connect_async(mobile_url)
            .await
            .expect("mobile socket after replacement");
        let tunnel_id = next_open(&mut new_desktop).await;
        new_desktop
            .send(Message::Text(
                serde_json::json!({"type":"bridge_ready","tunnel_id":tunnel_id})
                    .to_string()
                    .into(),
            ))
            .await
            .expect("replacement bridge ready");
        assert_eq!(next_ready(&mut mobile).await, tunnel_id);

        let mut packet = tunnel_id.as_bytes().to_vec();
        packet.extend_from_slice(b"replacement-route");
        mobile
            .send(Message::Binary(packet.clone().into()))
            .await
            .expect("mobile packet");
        assert_eq!(
            new_desktop
                .next()
                .await
                .expect("desktop packet")
                .expect("frame"),
            Message::Binary(packet.into())
        );

        let _ = mobile.close(None).await;
        let _ = new_desktop.close(None).await;
        server.abort();
        let _ = server.await;
    }

    #[tokio::test]
    async fn routes_multiple_mobile_tunnels_independently() {
        let setup = test_setup();
        let state = test_state(&setup);
        let (address, server) = start_server(state).await;

        let desktop_url = format!("ws://{address}/v1/relay?role=desktop&device_id=desktop-test");
        let (mut desktop, _) =
            connect_async(authorized_ws_request(&desktop_url, &setup.desktop_token))
                .await
                .expect("desktop socket");
        let first_ticket = issue_connection_ticket(&setup);
        let (mut first, _) = connect_async(format!(
            "ws://{address}/v1/relay?role=mobile&device_id=mobile-test&target=desktop-test&ticket={first_ticket}"
        ))
            .await
            .expect("first mobile socket");
        let first_tunnel_id = next_open(&mut desktop).await;
        desktop
            .send(Message::Text(
                serde_json::json!({"type":"bridge_ready","tunnel_id":first_tunnel_id})
                    .to_string()
                    .into(),
            ))
            .await
            .expect("first bridge ready");
        assert_eq!(next_ready(&mut first).await, first_tunnel_id);
        let second_ticket = issue_connection_ticket(&setup);
        let (mut second, _) = connect_async(format!(
            "ws://{address}/v1/relay?role=mobile&device_id=mobile-test&target=desktop-test&ticket={second_ticket}"
        ))
            .await
            .expect("second mobile socket");
        let second_tunnel_id = next_open(&mut desktop).await;
        desktop
            .send(Message::Text(
                serde_json::json!({"type":"bridge_ready","tunnel_id":second_tunnel_id})
                    .to_string()
                    .into(),
            ))
            .await
            .expect("second bridge ready");
        assert_eq!(next_ready(&mut second).await, second_tunnel_id);

        let mut first_packet = first_tunnel_id.as_bytes().to_vec();
        first_packet.extend_from_slice(b"first");
        first
            .send(Message::Binary(first_packet.clone().into()))
            .await
            .expect("first send");
        let mut second_packet = second_tunnel_id.as_bytes().to_vec();
        second_packet.extend_from_slice(b"second");
        second
            .send(Message::Binary(second_packet.clone().into()))
            .await
            .expect("second send");
        let mut desktop_packets = Vec::new();
        while desktop_packets.len() < 2 {
            if let Message::Binary(packet) = desktop
                .next()
                .await
                .expect("desktop packet")
                .expect("frame")
            {
                desktop_packets.push(packet.to_vec());
            }
        }
        assert!(desktop_packets.contains(&first_packet));
        assert!(desktop_packets.contains(&second_packet));

        let mut reverse_first = first_tunnel_id.as_bytes().to_vec();
        reverse_first.extend_from_slice(b"back-first");
        desktop
            .send(Message::Binary(reverse_first.clone().into()))
            .await
            .expect("desktop send");
        let mut reverse_second = second_tunnel_id.as_bytes().to_vec();
        reverse_second.extend_from_slice(b"back-second");
        desktop
            .send(Message::Binary(reverse_second.clone().into()))
            .await
            .expect("desktop send");
        assert_eq!(
            first.next().await.expect("first packet").expect("frame"),
            Message::Binary(reverse_first.into())
        );
        assert_eq!(
            second.next().await.expect("second packet").expect("frame"),
            Message::Binary(reverse_second.into())
        );

        let _ = first.close(None).await;
        let _ = second.close(None).await;
        let _ = desktop.close(None).await;
        server.abort();
        let _ = server.await;
    }

    async fn reqwest_like_request(
        url: &str,
        method: &str,
        headers: &[(&str, &str)],
        body: &str,
    ) -> String {
        let parsed = url::Url::parse(url).expect("presence url");
        let host = parsed.host_str().expect("presence host");
        let port = parsed.port_or_known_default().expect("presence port");
        let stream = tokio::net::TcpStream::connect((host, port))
            .await
            .expect("presence tcp");
        let mut stream = tokio::io::BufStream::new(stream);
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        let target = match parsed.query() {
            Some(query) => format!("{}?{query}", parsed.path()),
            None => parsed.path().to_string(),
        };
        let mut request = format!(
            "{method} {target} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\nContent-Length: {}\r\n",
            body.len()
        );
        for (name, value) in headers {
            request.push_str(&format!("{name}: {value}\r\n"));
        }
        request.push_str("\r\n");
        request.push_str(body);
        stream
            .write_all(request.as_bytes())
            .await
            .expect("presence request");
        stream.flush().await.expect("presence flush");
        let mut body = Vec::new();
        stream
            .read_to_end(&mut body)
            .await
            .expect("presence response");
        String::from_utf8_lossy(&body).into_owned()
    }
}
