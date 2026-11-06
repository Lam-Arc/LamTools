//! Device-to-device connection, as the phone sees it.
//!
//! user:“P2P 作为独立、可复用的传输组件”+(重量都在 `sunday-p2p` 里，这里只做三件事：
//! 保存身份与可信设备、把 UI 的调用转成隧道上的帧、把对端 id 报回去)。
//!
//! Android 注意：iroh 的默认 DNS 解析器要读系统 DNS，需要 JNI 上下文；没有时会退回
//! 备用域名服务器（本机直接地址照样能用）。等桌面端接上之后再把 JNI 上下文补进来。

use std::path::PathBuf;
use std::sync::Arc;

use anyhow::Result;
use serde_json::{json, Value};
use tauri::State;
use tokio::sync::Mutex;

use sunday_p2p::{encode_ticket, Client, Identity, TrustStore};

pub struct P2pState {
    dir: PathBuf,
    inner: Mutex<Inner>,
}

#[derive(Default)]
struct Inner {
    endpoint: Option<sunday_p2p::iroh::Endpoint>,
    client: Option<Client>,
    ticket: String,
}

impl P2pState {
    pub fn new(dir: PathBuf) -> Self {
        std::fs::create_dir_all(&dir).ok();
        Self {
            dir,
            inner: Mutex::new(Inner::default()),
        }
    }

    fn trust(&self) -> Result<TrustStore> {
        TrustStore::load(&self.dir)
    }
}

/// The ticket the other device scans, plus this device's id.
#[tauri::command]
pub async fn p2p_ticket(state: State<'_, Arc<P2pState>>) -> Result<Value, String> {
    let mut inner = state.inner.lock().await;
    if inner.endpoint.is_none() {
        let identity = Identity::load_or_create(&state.dir).map_err(|error| error.to_string())?;
        let endpoint = identity
            .endpoint()
            .await
            .map_err(|error| format!("{error:#}"))?;
        inner.ticket = encode_ticket(&endpoint.addr()).map_err(|error| error.to_string())?;
        inner.endpoint = Some(endpoint);
    }
    let endpoint = inner.endpoint.as_ref().expect("endpoint just created");
    Ok(json!({
        "ticket": inner.ticket,
        "id": endpoint.id().to_string(),
    }))
}

/// Dials a ticket. The ticket is consent, so the peer is remembered on its side.
#[tauri::command]
pub async fn p2p_connect(
    app: tauri::AppHandle,
    state: State<'_, Arc<P2pState>>,
    ticket: String,
    name: String,
) -> Result<Value, String> {
    let mut inner = state.inner.lock().await;
    if inner.endpoint.is_none() {
        let identity = Identity::load_or_create(&state.dir).map_err(|error| error.to_string())?;
        let endpoint = identity
            .endpoint()
            .await
            .map_err(|error| format!("{error:#}"))?;
        inner.ticket = encode_ticket(&endpoint.addr()).map_err(|error| error.to_string())?;
        inner.endpoint = Some(endpoint);
    }
    let endpoint = inner.endpoint.clone().expect("endpoint ready");
    let client = Client::dial(&endpoint, &ticket, &name)
        .await
        .map_err(|error| format!("{error:#}"))?;
    let peer = client.peer.clone();
    // user:“接收实时事件”+(Core 的通知由 PC 侧泵进隧道，这里换成 Tauri 事件交给界面；
    // 界面拿到的是同一条通知，不需要知道它是从哪条网络路径来的)。
    let mut events = client.subscribe();
    let handle = app.clone();
    tauri::async_runtime::spawn(async move {
        use tauri::Emitter;
        while let Ok(event) = events.recv().await {
            handle
                .emit(
                    "p2p-event",
                    json!({ "method": event.method, "params": event.params }),
                )
                .ok();
        }
    });
    inner.client = Some(client);
    Ok(json!({ "peer": peer }))
}

/// Forwards one call over the tunnel. `core_http` is what the shared UI uses for the
/// Core's REST surface; everything else is whatever the Core speaks.
#[tauri::command]
pub async fn p2p_call(
    state: State<'_, Arc<P2pState>>,
    method: String,
    params: Option<Value>,
) -> Result<Value, String> {
    let mut inner = state.inner.lock().await;
    let client = inner
        .client
        .as_mut()
        .ok_or_else(|| "还没有连接到电脑".to_owned())?;
    client
        .call(&method, params.unwrap_or_else(|| json!({})))
        .await
        .map_err(|error| format!("{error:#}"))
}

#[tauri::command]
pub async fn p2p_status(state: State<'_, Arc<P2pState>>) -> Result<Value, String> {
    let inner = state.inner.lock().await;
    Ok(json!({
        "connected": inner.client.is_some(),
        "peer": inner.client.as_ref().map(|client| client.peer.clone()),
        "ticket": inner.ticket,
    }))
}

#[tauri::command]
pub async fn p2p_disconnect(state: State<'_, Arc<P2pState>>) -> Result<(), String> {
    let mut inner = state.inner.lock().await;
    if let Some(client) = inner.client.take() {
        client.close();
    }
    Ok(())
}

/// user:“允许撤销授权”+(删掉那条，下一次握手就被拒绝)。
#[tauri::command]
pub async fn p2p_devices(state: State<'_, Arc<P2pState>>) -> Result<Value, String> {
    let store = state.trust().map_err(|error| error.to_string())?;
    Ok(json!({ "devices": store.devices }))
}

#[tauri::command]
pub async fn p2p_revoke(state: State<'_, Arc<P2pState>>, id: String) -> Result<Value, String> {
    let mut store = state.trust().map_err(|error| error.to_string())?;
    let removed = store.revoke(&id);
    store.save().ok();
    Ok(json!({ "removed": removed }))
}
