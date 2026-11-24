//! Device-to-device connection, as the phone sees it.
//!
//! user:“P2P 作为独立、可复用的传输组件”+(重量都在 `sunday-p2p` 里，这里只做三件事：
//! 保存身份与可信设备、把 UI 的调用转成隧道上的帧、把对端 id 报回去)。
//!
//! Android 注意：iroh 的默认 DNS 解析器要读系统 DNS，需要 JNI 上下文；没有时会退回
//! 备用域名服务器（本机直接地址照样能用）。等桌面端接上之后再把 JNI 上下文补进来。

use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Arc;
use std::time::Duration;

use anyhow::Result;
use serde_json::{json, Value};
use tauri::State;
use tokio::sync::Mutex;

use sunday_p2p::state::{CoreLayer, DeviceLayer, Layers, SessionLayer};
use sunday_p2p::{encode_ticket, Client, Identity, TrustStore, View};

pub struct P2pState {
    dir: PathBuf,
    inner: Mutex<Inner>,
    /// 最近一次成功连接的对端 id。
    ///
    /// user:“点刷新什么反应都没有”+(p2p_call 以前整条调用期间持有 inner 锁，状态查询如果也去
    /// 抢同一把锁，界面每 3 秒一次的刷新就会排在一条长 RPC 后面，看起来像卡住了)
    peer: Mutex<Option<String>>,
    /// 是否正在拨号。
    ///
    /// user:“类似的时序问题不要再犯，检查”+(拨号期间 inner 锁被占着，状态查询只能靠
    /// 「锁拿不到」猜，以前猜成「已连接」；界面于是拿着一个还没建好的隧道去读项目、读模型，
    /// 读一次空一次，还显示成「暂无可用模型」。这里把拨号单独记下来，让状态说实话)。
    connecting: Arc<AtomicBool>,
    /// 隧道是否还活着。
    ///
    /// user:“显示和电脑断联了”+(网络静默断开时读帧会一直挂着，界面却还是「已连接」；
    /// 这里存的就是 Client 自己那只存活标志，宿主据此在真的断了时通知界面)。
    alive: Mutex<Arc<AtomicBool>>,
    /// 业务层握手是否完成：initialize + ping 都成功了。
    ///
    /// user:“只有完成业务层握手并通过基本消息收发检查，才能显示已连接”+(隧道活着只说明
    /// QUIC 通了；PC 的 Core 没起来时，手机必须显示降级而不是「已连接」)。
    business: Arc<AtomicBool>,
    /// PC 的 Core bridge 是否应答过 initialize。
    core_ready: Arc<AtomicBool>,
    /// 这次连接是否真的探测过 Core（区分「没探过」和「探过但挂了」）。
    core_probed: Arc<AtomicBool>,
    /// 每次连接递增一个号：旧连接的后台监听据此退出，不会在新连接上来之后误报「断了」。
    generation: Arc<AtomicU64>,
    /// 拨号串行，但不占用 `inner` 锁。
    ///
    /// user:“切换的时候明明没在连，却报连接超时”+(以前拨号的预算里包含了排队等一条长调用
    /// 释放 inner 锁的时间，45 秒被等锁吃光，用户被引向错误的方向)。
    dialing_gate: Mutex<()>,
}

/// 拨号期间置位，离开作用域（成功、失败、超时、被取消）自动复位。
struct DialingGuard(Arc<AtomicBool>);

impl Drop for DialingGuard {
    fn drop(&mut self) {
        self.0.store(false, Ordering::SeqCst);
    }
}

#[derive(Default)]
struct Inner {
    endpoint: Option<sunday_p2p::iroh::Endpoint>,
    client: Option<Arc<Client>>,
    ticket: String,
}

impl P2pState {
    pub fn new(dir: PathBuf) -> Self {
        std::fs::create_dir_all(&dir).ok();
        Self {
            dir,
            inner: Mutex::new(Inner::default()),
            peer: Mutex::new(None),
            connecting: Arc::new(AtomicBool::new(false)),
            alive: Mutex::new(Arc::new(AtomicBool::new(false))),
            business: Arc::new(AtomicBool::new(false)),
            core_ready: Arc::new(AtomicBool::new(false)),
            core_probed: Arc::new(AtomicBool::new(false)),
            generation: Arc::new(AtomicU64::new(0)),
            dialing_gate: Mutex::new(()),
        }
    }

    fn trust(&self) -> Result<TrustStore> {
        TrustStore::load(&self.dir)
    }

    /// 新连接 / 断线 / 主动断开时，业务层的结论必须一起归零。
    fn reset_business(&self) {
        self.business.store(false, Ordering::SeqCst);
        self.core_ready.store(false, Ordering::SeqCst);
        self.core_probed.store(false, Ordering::SeqCst);
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
    // 从这里开始到函数结束，对外都算「正在连接」，状态查询据此如实回答。
    state.connecting.store(true, Ordering::SeqCst);
    let _dialing = DialingGuard(state.connecting.clone());
    // 同一时刻只允许一次拨号。这里刻意不碰 inner 锁：一条 180 秒的调用不该让「切换设备」等到超时。
    let _gate = state.dialing_gate.lock().await;

    let endpoint = {
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
        inner.endpoint.clone().expect("endpoint ready")
    };
    // 这一代之前的连接与监听都作废。
    let generation = state.generation.fetch_add(1, Ordering::SeqCst) + 1;
    {
        let alive = state.alive.lock().await;
        alive.store(false, Ordering::SeqCst);
    }
    *state.peer.lock().await = None;
    state.reset_business();

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
    let client = match tokio::time::timeout(budget, Client::dial(&endpoint, &ticket, &name)).await {
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
    let peer = client.peer.clone();
    let peer_name = client.peer_name.clone();
    // user:“只有完成业务层握手并通过基本消息收发检查，才能显示已连接”+(隧道建立只说明
    // QUIC 通了；先向电脑要一次 initialize、再 ping 一次，Core 没起来就是 degraded)。
    let initialized = client
        .call_with_timeout(
            "initialize",
            json!({
                "clientInfo": {
                    "name": "sunday-p2p",
                    "version": env!("CARGO_PKG_VERSION"),
                },
            }),
            Duration::from_secs(8),
        )
        .await
        .is_ok();
    let pinged = client
        .call_with_timeout("ping", json!({}), Duration::from_secs(8))
        .await
        .is_ok();
    state.core_probed.store(true, Ordering::SeqCst);
    state.core_ready.store(initialized, Ordering::SeqCst);
    state.business.store(initialized && pinged, Ordering::SeqCst);
    if initialized && pinged {
        app.emit(
            "p2p-progress",
            json!({ "phase": "connected", "target": target }),
        )
        .ok();
    } else {
        let reason = if initialized { "session_not_resumed" } else { "core_unavailable" };
        app.emit(
            "p2p-progress",
            json!({ "phase": "degraded", "reason": reason, "target": target }),
        )
        .ok();
    }
    // user:“配对成功后建立持久设备信任，下次自动连接”+(把地址票回给界面；`sunday2:`
    // 配对票只有 5 分钟，拿它当长期凭据，应用重启或切设备后必然要重扫)。
    let resume = client.resume_ticket().ok();
    *state.peer.lock().await = Some(peer.clone());
    // 换成这条连接自己的标志：它的读帧与心跳任务断掉时，这个值会跟着变 false。
    let alive = client.alive_flag();
    *state.alive.lock().await = Arc::clone(&alive);

    // user:“接收实时事件”+(Core 的通知由 PC 侧泵进隧道，这里换成 Tauri 事件交给界面；
    // 界面拿到的是同一条通知，不需要知道它是从哪条网络路径来的)。
    let mut events = client.subscribe();
    let handle = app.clone();
    tauri::async_runtime::spawn(async move {
        use tauri::Emitter;
        loop {
            match events.recv().await {
                Ok(event) => {
                    handle
                        .emit(
                            "p2p-event",
                            json!({ "method": event.method, "params": event.params }),
                        )
                        .ok();
                }
                // user:“一轮里事件比转发快，不能悄悄丢”+(以前 Lagged 会让这个转发任务直接
                // 退出，手机从此只发得出、收不到，连断线都不算；现在告诉界面重新 resume)。
                Err(tokio::sync::broadcast::error::RecvError::Lagged(_)) => {
                    handle
                        .emit(
                            "p2p-event",
                            json!({ "method": "thread/gap", "params": { "reason": "p2p_lagged" } }),
                        )
                        .ok();
                }
                Err(_) => break,
            }
        }
    });

    // user:“显示和电脑断联了”+(断线必须主动告诉界面，而不是等下一次操作超时；
    // 界面收到 lost 才会显示「断开了」并开始重连)。
    {
        let owned = Arc::clone(state.inner());
        let watch = Arc::clone(&alive);
        let handle = app.clone();
        tauri::async_runtime::spawn(async move {
            use tauri::Emitter;
            loop {
                tokio::time::sleep(Duration::from_secs(1)).await;
                if owned.generation.load(Ordering::SeqCst) != generation {
                    return;
                }
                if watch.load(Ordering::SeqCst) {
                    continue;
                }
                *owned.peer.lock().await = None;
                owned.reset_business();
                if let Ok(mut inner) = owned.inner.try_lock() {
                    let dead = inner
                        .client
                        .as_ref()
                        .map(|client| !client.is_alive())
                        .unwrap_or(false);
                    if dead {
                        if let Some(client) = inner.client.take() {
                            client.close();
                        }
                    }
                }
                handle.emit("p2p-progress", json!({ "phase": "lost" })).ok();
                return;
            }
        });
    }

    let client = Arc::new(client);
    state.inner.lock().await.client = Some(client);
    Ok(json!({ "peer": peer, "name": peer_name, "resume": resume }))
}

/// Forwards one call over the tunnel. `core_http` is what the shared UI uses for the
/// Core's REST surface; everything else is whatever the Core speaks.
#[tauri::command]
pub async fn p2p_call(
    state: State<'_, Arc<P2pState>>,
    method: String,
    params: Option<Value>,
    timeout_ms: Option<u64>,
) -> Result<Value, String> {
    // 只在取连接时持锁：界面的项目、模型、会话是并发加载的，不该互相排队。
    let client = {
        let mut inner = state.inner.lock().await;
        // 隧道已经断了就当场丢掉，别让界面拿着一个死连接反复拿到英文报错。
        if inner
            .client
            .as_ref()
            .map(|client| !client.is_alive())
            .unwrap_or(false)
        {
            if let Some(client) = inner.client.take() {
                client.close();
            }
        }
        inner.client.clone()
    };
    let Some(client) = client else {
        state.alive.lock().await.store(false, Ordering::SeqCst);
        *state.peer.lock().await = None;
        state.reset_business();
        return Err("和电脑的连接已经断开，打开「设备连接」重连或切回本机".to_owned());
    };
    // user:“超时不自动等同于发送失败”+(界面给的预算只决定这一次等待多久；超时后
    // 连接与对端状态不变，重试仍复用同一个幂等键)。
    let timeout = Duration::from_millis(timeout_ms.unwrap_or(120_000).clamp(1_000, 300_000));
    match client
        .call_with_timeout(&method, params.unwrap_or_else(|| json!({})), timeout)
        .await
    {
        Ok(result) => {
            // 任何真正的 Core 调用成功，都说明 Core 这一层是通的；ping/whoami/echo/file/*
            // 由传输层自己处理，不能拿来证明 Core 可用。
            if !matches!(method.as_str(), "ping" | "whoami" | "echo") && !method.starts_with("file/") {
                state.core_ready.store(true, Ordering::SeqCst);
                state.core_probed.store(true, Ordering::SeqCst);
            }
            if method == "thread/resume" {
                state.business.store(true, Ordering::SeqCst);
            }
            Ok(result)
        }
        Err(error) => {
            let message = format!("{error:#}");
            if method != "ping"
                && (message.contains("RPC") || message.contains("Core") || message.contains("Core 端口"))
            {
                state.core_probed.store(true, Ordering::SeqCst);
                state.core_ready.store(false, Ordering::SeqCst);
            }
            Err(message)
        }
    }
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
    Ok(status_value(state.inner()).await)
}

/// 现在这一刻给界面看的快照（命令与 2 秒事件推送共用同一份）。
async fn status_value(state: &P2pState) -> Value {
    // 有一条调用正在进行时锁是拿不到的，那说明隧道正常在用；状态查询不能排在它后面。
    let snapshot = state.inner.try_lock().ok().map(|inner| {
        (
            inner
                .client
                .as_ref()
                .map(|client| client.is_alive())
                .unwrap_or(false),
            inner.client.as_ref().map(|client| client.peer.clone()),
            inner.ticket.clone(),
            inner.client.as_ref().map(|client| client.rtt_ms()).unwrap_or(0),
        )
    });
    let cached = state.peer.lock().await.clone();
    let alive_now = state.alive.lock().await.load(Ordering::SeqCst);
    let dialing = state.connecting.load(Ordering::SeqCst);
    let (connected, peer, ticket, rtt_ms) = match snapshot {
        Some((connected, peer, ticket, rtt_ms)) => (connected, peer.or(cached), ticket, rtt_ms),
        // 锁被一条调用占着：连通性只看存活标志，不能拿「锁拿不到」当「已连接」。
        None => (alive_now && !dialing, cached, String::new(), 0),
    };
    let transport = connected && alive_now;
    let authenticated = transport;
    let core = if !transport {
        CoreLayer::Unknown
    } else if state.core_probed.load(Ordering::SeqCst) {
        if state.core_ready.load(Ordering::SeqCst) {
            CoreLayer::Ready
        } else {
            CoreLayer::Down
        }
    } else {
        CoreLayer::Unknown
    };
    let session = if state.business.load(Ordering::SeqCst) {
        SessionLayer::Resumed
    } else {
        SessionLayer::NotResumed
    };
    let layers = Layers {
        transport,
        device: if authenticated {
            DeviceLayer::Authenticated
        } else {
            DeviceLayer::Unpaired
        },
        core,
        session,
    };
    let view = layers.view();
    let reason = match &view {
        View::Degraded { reason } => reason.code(),
        _ => "-",
    };
    json!({
        // connected 保留给老界面（= 隧道活着）；新界面只看 view / layers。
        "connected": transport,
        "connecting": dialing,
        "peer": peer,
        "ticket": ticket,
        // user:“只有业务真正可用才显示已连接”+(四层齐了才是 connected；Core 没起来是 degraded)。
        "view": view.phase(),
        "reason": reason,
        "layers": layers_json(&layers),
        "rttMs": rtt_ms,
    })
}

/// 事件驱动状态：2 秒算一次，只有真的变了才推 `p2p-state`。
///
/// user:“减少无故断连或者无连接反馈的情况”+(手机设备页以前只靠拨号/断开事件；Core
/// 中途挂掉或恢复没有推送。这里让宿主自己推状态，界面不用猜，也不用定时轮询)。
pub fn start_emitter(app: tauri::AppHandle, state: Arc<P2pState>) {
    tauri::async_runtime::spawn(async move {
        use tauri::Emitter as _;
        let mut last = String::new();
        let mut last_probe = std::time::Instant::now();
        loop {
            tokio::time::sleep(Duration::from_secs(2)).await;
            // user:“修”+(隧道仍在线时也定期验证电脑 Core，停答即降级，恢复就更新)。
            let transport = state.alive.lock().await.load(Ordering::SeqCst);
            if transport && last_probe.elapsed() >= Duration::from_secs(10) {
                last_probe = std::time::Instant::now();
                let generation = state.generation.load(Ordering::SeqCst);
                let client = state.inner.lock().await.client.clone();
                if let Some(client) = client {
                    let ready = client
                        .call_with_timeout(
                            "settings.get",
                            json!({ "namespace": "core.onboarding" }),
                            Duration::from_secs(5),
                        )
                        .await
                        .is_ok();
                    let inner = state.inner.lock().await;
                    let same_client = inner
                        .client
                        .as_ref()
                        .is_some_and(|current| Arc::ptr_eq(current, &client));
                    if same_client
                        && state.generation.load(Ordering::SeqCst) == generation
                        && client.is_alive()
                    {
                        state.core_ready.store(ready, Ordering::SeqCst);
                        state.core_probed.store(true, Ordering::SeqCst);
                    }
                }
            }
            let snapshot = status_value(&state).await;
            let text = snapshot.to_string();
            if text == last {
                continue;
            }
            last = text;
            let _ = app.emit("p2p-state", snapshot);
        }
    });
}

/// 四层状态给界面看的稳定字符串（与桌面 `p2p_status.layers` 同形）。
fn layers_json(layers: &Layers) -> Value {
    let device = match layers.device {
        DeviceLayer::Authenticated => "authenticated",
        DeviceLayer::Paired => "paired",
        DeviceLayer::Unpaired => "unpaired",
    };
    let core = match layers.core {
        CoreLayer::Ready => "ready",
        CoreLayer::Down => "down",
        CoreLayer::Unknown => "unknown",
    };
    let session = match layers.session {
        SessionLayer::Resumed => "resumed",
        SessionLayer::NotResumed => "not_resumed",
    };
    json!({
        "transport": layers.transport,
        "device": device,
        "core": core,
        "session": session,
    })
}

#[tauri::command]
pub async fn p2p_disconnect(state: State<'_, Arc<P2pState>>) -> Result<(), String> {
    // 先推进一代，旧连接的后台监听就不会在断开之后误报「断了」。
    state.generation.fetch_add(1, Ordering::SeqCst);
    let mut inner = state.inner.lock().await;
    if let Some(client) = inner.client.take() {
        client.close();
    }
    drop(inner);
    *state.peer.lock().await = None;
    state.alive.lock().await.store(false, Ordering::SeqCst);
    state.reset_business();
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

#[cfg(test)]
mod tests {
    use super::*;

    /// user:“只有业务真正可用才显示已连接”+(隧道通、Core 挂了也不能算已连接)。
    #[test]
    fn a_live_tunnel_with_a_dead_core_is_degraded() {
        let layers = Layers {
            transport: true,
            device: DeviceLayer::Authenticated,
            core: CoreLayer::Down,
            session: SessionLayer::NotResumed,
        };
        assert_eq!(layers.view().phase(), "degraded");
        assert_eq!(layers_json(&layers)["core"], "down");
    }

    #[test]
    fn only_all_four_layers_count_as_connected() {
        let layers = Layers {
            transport: true,
            device: DeviceLayer::Authenticated,
            core: CoreLayer::Ready,
            session: SessionLayer::Resumed,
        };
        assert_eq!(layers.view().phase(), "connected");
        assert_eq!(layers_json(&layers), json!({
            "transport": true,
            "device": "authenticated",
            "core": "ready",
            "session": "resumed",
        }));
    }
}
