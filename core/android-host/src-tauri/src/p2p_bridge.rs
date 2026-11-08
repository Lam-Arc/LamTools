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
    /// 最近一次成功连接的对端 id。
    ///
    /// user:“点刷新什么反应都没有”+(p2p_call 会整条调用期间持有 inner 锁，状态查询如果也去
    /// 抢同一把锁，界面每 3 秒一次的刷新就会排在一条长 RPC 后面，看起来像卡住了)
    peer: Mutex<Option<String>>,
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
            peer: Mutex::new(None),
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
    timeout_ms: Option<u64>,
) -> Result<Value, String> {
    // user:“从点击图标到进入界面要 5 秒以内”+(启动时只用很短的时间试着连一次电脑，
    // 连不上立刻用本机，绝不把界面卡在一次等不到的重连上)。
    let budget = Duration::from_millis(timeout_ms.unwrap_or(45_000).clamp(400, 120_000));
    // 连接的第一步是创建 iroh 端点，这一步本身就可能花几十秒（建 socket、连中继、查地址）；
    // 只给拨号设上限没有用。整个连接过程都罩在同一个预算里。
    let attempt = async move {
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
    // 重连之前先把旧连接收掉，否则电脑那边还挂着上一台手机，会白等一轮握手。
    if let Some(previous) = inner.client.take() {
        previous.close();
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
        budget,
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
                "连接超时（{} 秒）。请确认电脑上的配对二维码是刚生成的，手机和电脑在同一 Wi-Fi，或电脑能连上中继。目标地址：{}",
                budget.as_secs().max(1),
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
    *state.peer.lock().await = Some(peer.clone());
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
    };

    match tokio::time::timeout(budget + Duration::from_millis(250), attempt).await {
        Ok(result) => result,
        Err(_) => Err(format!(
            "连接超时（{} 秒）。请确认电脑上的配对二维码是刚生成的，手机和电脑在同一 Wi-Fi，或电脑能连上中继。",
            budget.as_secs().max(1)
        )),
    }
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
    // 隧道已经断了就当场丢掉，别让界面拿着一个死连接反复拿到英文报错。
    if inner.client.as_ref().map(|client| !client.is_alive()).unwrap_or(false) {
        if let Some(client) = inner.client.take() {
            client.close();
        }
    }
    if inner.client.is_none() {
        drop(inner);
        *state.peer.lock().await = None;
        return Err("和电脑的连接已经断开，回「远程连接」点刷新重连一次".to_owned());
    }
    let client = inner
        .client
        .as_mut()
        .ok_or_else(|| "和电脑的连接已经断开，回「远程连接」点刷新重连一次".to_owned())?;
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
    // 有一条调用正在进行时锁是拿不到的，那说明隧道正常在用；这时候按缓存回答，别让
    // 刷新按钮排在它后面。
    let inner = match state.inner.try_lock() {
        Ok(guard) => Some(guard),
        Err(_) => None,
    };
    let cached = state.peer.lock().await.clone();
    if let Some(inner) = inner.as_ref() {
        let connected = inner
            .client
            .as_ref()
            .map(|client| client.is_alive())
            .unwrap_or(false);
        return Ok(json!({
            "connected": connected,
            "peer": inner.client.as_ref().map(|c| c.peer.clone()).or(cached),
            "ticket": inner.ticket,
        }));
    }
    return Ok(json!({ "connected": true, "busy": true, "peer": cached }));
}


#[tauri::command]
pub async fn p2p_disconnect(state: State<'_, Arc<P2pState>>) -> Result<(), String> {
    let mut inner = state.inner.lock().await;
    if let Some(client) = inner.client.take() {
        client.close();
    }
    drop(inner);
    *state.peer.lock().await = None;
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
