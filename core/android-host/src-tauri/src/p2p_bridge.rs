//! Device-to-device connection, as the phone sees it.
//!
//! user:“P2P 作为独立、可复用的传输组件”+(重量都在 `sunday-p2p` 里，这里只做三件事：
//! 保存身份与可信设备、把 UI 的调用转成隧道上的帧、把对端 id 报回去)。
//!
//! Android 注意：iroh 的默认 DNS 解析器要读系统 DNS，需要 JNI 上下文；没有时会退回
//! 备用域名服务器（本机直接地址照样能用）。等桌面端接上之后再把 JNI 上下文补进来。

use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

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
    // user:“连接过程中一点反应都没有，我根本不知道卡在哪里了”+(先告诉界面目标地址，
    // 再给整次尝试一个明确的上限，超时就报可执行的原因，而不是让 iroh 叠三层超时)。
    use tauri::Emitter as _;
    let target = sunday_p2p::decode_ticket(&ticket)
        .ok()
        .and_then(|addr| {
            addr.addrs.iter().find_map(|item| match item {
                sunday_p2p::iroh::TransportAddr::Ip(ip) => Some(ip.to_string()),
                _ => None,
            })
        })
        .unwrap_or_default();
    app.emit(
        "p2p-progress",
        json!({ "phase": "dialing", "target": target }),
    )
    .ok();
    let client = match tokio::time::timeout(
        Duration::from_secs(45),
        Client::dial(&endpoint, &ticket, &name),
    )
    .await
    {
        Ok(Ok(client)) => client,
        Ok(Err(error)) => {
            app.emit("p2p-progress", json!({ "phase": "failed", "target": target }))
                .ok();
            return Err(format!("{error:#}"));
        }
        Err(_) => {
            app.emit("p2p-progress", json!({ "phase": "timeout", "target": target }))
                .ok();
            return Err(format!(
                "连接超时（45 秒）。请确认电脑上的配对二维码是刚生成的，手机和电脑在同一 Wi-Fi，或电脑能连上中继。目标地址：{}",
                if target.is_empty() { "未知".to_owned() } else { target }
            ));
        }
    };
    app.emit(
        "p2p-progress",
        json!({ "phase": "connected", "target": target }),
    )
    .ok();
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

/// 实时扫码：相机预览里识别到二维码就回填票据。
///
/// user:“扫码还要靠拍照，而不是直接调用摄像头权限扫描识别”+(相机常开，每几帧解一次，
/// 识别到立即返回，不再经过系统相机拍照与落盘)。
#[tauri::command]
pub async fn p2p_scan() -> Result<Value, String> {
    let (request, receiver) = crate::picker::open_request();
    if let Err(error) = crate::picker::start_qr(&request) {
        crate::picker::forget(&request);
        return Err(error);
    }
    let answer = tauri::async_runtime::spawn_blocking(move || {
        receiver.recv_timeout(std::time::Duration::from_secs(120))
    })
    .await
    .map_err(|error| error.to_string())?;
    match answer {
        Ok(text) if !text.is_empty() => Ok(json!({ "ticket": text })),
        _ => Ok(json!({ "ticket": serde_json::Value::Null })),
    }
}

/// The ticket as an SVG QR code, so the other device can just scan it.
#[tauri::command]
pub async fn p2p_qr(ticket: String) -> Result<Value, String> {
    let svg = sunday_p2p::ticket_qr_svg(&ticket).map_err(|error| error.to_string())?;
    Ok(json!({ "svg": svg }))
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
