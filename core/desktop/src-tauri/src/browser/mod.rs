// user:“新建 browser/ 模块，不要再往 split_pane 里塞”+(浏览器宿主、标签、平台能力、安全策略分开放，split_pane 只留文件树)。
//
// 模块边界（详见 方案/内置浏览器-01-总体方案.md 3.3）：
// - `tabs`         标签模型、关闭栈、活动标签（纯逻辑，可单测）
// - `url_policy`   协议白名单、地址栏输入识别（与前端共用同一份规则形状）
// - `webview`      子 webview 的创建/销毁/矩形/可见性/导航
// - `platform_win` Windows 专属 WebView2 COM（标题、历史状态、弹窗、网页全屏、脚本求值）
// - `bridge`       Agent 桥（M2 起实现，这里只有接缝）
// - `session`      user data folder / profile（M2）
// - `download`     下载落盘策略（M3）
//
// user:“拿不到的能力不要猜”+(平台接口缺失时返回 unsupported 并留 TODO，不静默降级成“看起来能跑”)。
pub mod bridge;
#[cfg(windows)]
pub mod compositor;
pub mod download;
pub mod favicon;
pub mod platform_win;
pub mod security;
pub mod session;
pub mod shortcut;
pub mod tabs;
pub mod url_policy;
pub mod webview;

use std::collections::{HashMap, HashSet};
use std::sync::{Mutex, MutexGuard, OnceLock};

use serde::Serialize;
use tauri::{AppHandle, Emitter, Manager};

use crate::browser::session::BrowserProfile;
use crate::browser::tabs::{label_for, TabRegistry};
use crate::browser::url_policy::SearchEngine;
use crate::browser::webview::Bounds;

/// 状态变化事件：前端合并到对应标签上。
pub const EVENT_STATE: &str = "lamtools://browser-state";
/// 网页申请新窗口（`target=_blank`）时发给前端，由前端在同一个分屏里开新标签。
pub const EVENT_PENDING_TAB: &str = "lamtools://browser-pending-tab";
/// 页内查找结果（脚本实现求值后回传）。
pub const EVENT_FIND: &str = "lamtools://browser-find";
/// 网页（或工具栏）全屏状态变化。
pub const EVENT_FULLSCREEN: &str = "lamtools://browser-fullscreen";
/// 平台能力降级/失败（例如注册 WebView2 事件失败），前端要显示成可操作提示。
pub const EVENT_ERROR: &str = "lamtools://browser-error";
/// user:“权限默认全部拒绝，确认后放行”+(网页发起权限请求：`decision` 是当前结论；有 `requestId` 时等用户确认)。
pub const EVENT_PERMISSION: &str = "lamtools://browser-permission";
/// 站数据清理结果（按 host 清 Cookie / 页面存储 / 缓存）。
pub const EVENT_SITE_DATA: &str = "lamtools://browser-site-data";
/// 下载状态变化（开始/完成/失败三态，带 tab）。
pub const EVENT_DOWNLOAD: &str = "lamtools://browser-download";
/// 越权自检结果（网页里能不能摸到 Tauri IPC）：只在诊断命令触发时发出。
pub const EVENT_DIAGNOSTICS: &str = "lamtools://browser-diagnostics";
/// 浏览器拦到一个可接管的下载，问前端要不要交给 EasyNet。
/// 接管的请求头（Cookie / User-Agent）读完回传；前端等到这条再投递。
pub const EVENT_DOWNLOAD_HEADERS: &str = "lamtools://browser-download-headers";
/// 标签被关掉（含 Agent 自己关的）：界面据此把对应的分屏标签一起收掉，
/// 否则会留下「原生网页已经没了、分屏还在」的死标签，表现为只看到一张首页。
pub const EVENT_TAB_CLOSED: &str = "lamtools://browser-closed";

/// user:“统一错误模型：{code, message, retriable}”+(前端要能据此显示重试按钮，而不是弹一段英文异常)。
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct BrowserError {
    pub code: String,
    pub message: String,
    pub retriable: bool,
}

impl BrowserError {
    pub fn new(code: &str, message: impl Into<String>, retriable: bool) -> Self {
        Self { code: code.to_string(), message: message.into(), retriable }
    }

    pub fn tab_not_found() -> Self {
        Self::new("tab_not_found", "这个浏览器标签已经关闭", false)
    }

    /// 前端给非活动标签下发可见 bounds：按 R-规则拒绝，避免两个网页叠在一起。
    pub fn tab_inactive() -> Self {
        Self::new("tab_inactive", "后台标签不能占据可见区域", false)
    }

    pub fn invalid_bounds() -> Self {
        Self::new("invalid_bounds", "网页区域无效", false)
    }

    pub fn unsupported(message: impl Into<String>) -> Self {
        Self::new("unsupported", message, false)
    }

    pub fn internal(message: impl Into<String>) -> Self {
        Self::new("internal", message, false)
    }
}

impl std::fmt::Display for BrowserError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}: {}", self.code, self.message)
    }
}

impl std::error::Error for BrowserError {}

pub struct BrowserRuntime {
    pub tabs: TabRegistry,
    /// 每个标签最后一次生效的 bounds，供退出网页全屏时还原。
    pub bounds: HashMap<String, Bounds>,
    /// user:“两个网页重叠”+(每个标签属于哪块界面：同一块分屏里只允许一个网页可见，
    /// 切换标签时靠它把同组的其它网页收起；浮窗/不同分屏各是一组，互不影响)。
    pub groups: HashMap<String, String>,
    pub fullscreen: Option<String>,
    /// user:“权限默认全部拒绝”+(站点授权只由 Rust 记，前端只能发起「允许本次/允许该站点」)。
    pub permissions: security::PermissionStore,
    /// 等用户确认的权限请求：持有 deferral 才能在确认后放行。
    pub pending_permissions: HashMap<String, PendingPermission>,
    pub next_permission_id: u64,
    /// user:“favicon 按 tab+绝对 URL 缓存”+(换页后旧图标必须失效)。
    pub favicons: favicon::FaviconCache,
    /// user:“「继续访问」默认不记住”+(一次性放行：命中即消费，下一次同样的证书错误仍然阻断)。
    pub certificate_allows: HashSet<String>,
    /// user:“只做开始/完成/失败三态”+(下载列表由 Rust 自维护，wry 默认 handler 不转发字节进度)。
    pub downloads: download::DownloadRegistry,
    /// user:“ref 只在当前快照内有效”+(每个标签一份台账：上一份快照的编号立刻失效，写操作前先对账)。
    pub refs: HashMap<String, bridge::RefLedger>,
    click_popups: HashMap<String, Vec<PendingTabPayload>>,
}

/// 一个等用户确认的权限请求。`ticket` 在 Windows 上是 COM deferral，只能回 UI 线程解析。
pub struct PendingPermission {
    pub tab: String,
    pub host: String,
    pub kind: security::PermissionKind,
    pub user_initiated: bool,
    pub ticket: PermissionTicket,
}

#[cfg(windows)]
pub type PermissionTicket = platform_win::PermissionTicket;
#[cfg(not(windows))]
pub type PermissionTicket = ();

impl BrowserRuntime {
    fn new() -> Self {
        Self {
            tabs: TabRegistry::new(startup_seed()),
            bounds: HashMap::new(),
            groups: HashMap::new(),
            fullscreen: None,
            // user:“授权表落盘”+(启动时从 `<lam_home>/core/config/browser-permissions.json` 读回)。
            permissions: security::PermissionStore::load(),
            pending_permissions: HashMap::new(),
            next_permission_id: 0,
            favicons: favicon::FaviconCache::new(),
            certificate_allows: HashSet::new(),
            downloads: download::DownloadRegistry::new(),
            refs: HashMap::new(),
            click_popups: HashMap::new(),
        }
    }

    fn capture_click_popup(&mut self, payload: &PendingTabPayload) -> bool {
        let Some(popups) = self.click_popups.get_mut(&payload.tab) else { return false };
        if !matches!(self.tabs.get(&payload.tab), Ok(tab) if tab.ownership.owner() == bridge::Owner::Agent) {
            return false;
        }
        popups.push(payload.clone());
        true
    }
}

fn startup_seed() -> u64 {
    // 每次启动用不同的 id 前缀，避免重启后旧 webview label 撞车。
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|elapsed| elapsed.as_millis() as u64)
        .unwrap_or(0)
}

fn runtime() -> &'static Mutex<BrowserRuntime> {
    static RUNTIME: OnceLock<Mutex<BrowserRuntime>> = OnceLock::new();
    RUNTIME.get_or_init(|| Mutex::new(BrowserRuntime::new()))
}

// user:“回调里不能 panic”+(互斥锁中毒也转成错误码返回，不把 panic 抛进 COM 消息循环)。
fn lock_runtime() -> Result<MutexGuard<'static, BrowserRuntime>, BrowserError> {
    runtime().lock().map_err(|_| BrowserError::internal("浏览器状态不可用"))
}

fn with_runtime<T>(apply: impl FnOnce(&mut BrowserRuntime) -> Result<T, BrowserError>) -> Result<T, BrowserError> {
    let mut guard = lock_runtime()?;
    apply(&mut guard)
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct BrowserStatePayload {
    pub tab: String,
    pub url: String,
    pub title: String,
    pub favicon: Option<String>,
    pub loading: bool,
    pub can_go_back: bool,
    pub can_go_forward: bool,
    pub zoom: f64,
    pub crashed: bool,
    pub owner: String,
    /// user:“命令与状态里能读能写”+(M1 只有 normal；M2 接上 incognito 与自定义目录后前端据此显示角标)。
    pub profile: String,
}

fn state_payload(guard: &BrowserRuntime, tab: &str) -> Option<BrowserStatePayload> {
    guard.tabs.get(tab).ok().map(|state| BrowserStatePayload {
        tab: tab.to_string(),
        url: state.url.clone(),
        title: state.title.clone(),
        favicon: state.favicon.clone(),
        loading: state.loading,
        can_go_back: state.can_back,
        can_go_forward: state.can_forward,
        zoom: state.zoom,
        crashed: state.crashed,
        owner: state.ownership.owner().label().to_string(),
        profile: state.profile.label(),
    })
}

/// 把某个标签的最新状态发给主工作区。所有调用点都在锁外调用，避免重入死锁。
pub fn emit_state(app: &AppHandle, tab: &str) {
    let payload = lock_runtime().ok().and_then(|guard| state_payload(&guard, tab));
    if let Some(payload) = payload {
        let _ = app.emit_to("main", EVENT_STATE, payload);
    }
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PendingTabPayload {
    pub tab: String,
    pub url: String,
    pub opener: Option<String>,
    pub user_initiated: bool,
}

// user:“这是工具返回值和实际状态不同步”+(点击期间把原生新窗口请求交给该次操作，普通弹窗仍交给分屏)。
pub fn emit_pending_tab(app: &AppHandle, payload: PendingTabPayload) {
    if with_runtime(|rt| Ok(rt.capture_click_popup(&payload))).unwrap_or(false) {
        return;
    }
    let _ = app.emit_to("main", EVENT_PENDING_TAB, payload);
}

struct ClickPopupCapture {
    app: AppHandle,
    tab: Option<String>,
}

impl ClickPopupCapture {
    fn begin(app: &AppHandle, tab: &str) -> Result<Self, BrowserError> {
        with_runtime(|rt| {
            if rt.click_popups.contains_key(tab) {
                return Err(BrowserError::new("busy", "这个标签已有点击操作在执行", true));
            }
            rt.click_popups.insert(tab.to_string(), Vec::new());
            Ok(())
        })?;
        Ok(Self { app: app.clone(), tab: Some(tab.to_string()) })
    }

    fn take(&mut self) -> Vec<PendingTabPayload> {
        let Some(tab) = self.tab.take() else { return Vec::new() };
        with_runtime(|rt| Ok(rt.click_popups.remove(&tab).unwrap_or_default())).unwrap_or_default()
    }
}

impl Drop for ClickPopupCapture {
    fn drop(&mut self) {
        // 页面应答失败或调用取消时，已经发生的弹窗仍交给原来的前端处理流程。
        for popup in self.take() {
            let _ = self.app.emit_to("main", EVENT_PENDING_TAB, popup);
        }
    }
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ErrorPayload {
    pub tab: String,
    pub code: String,
    pub message: String,
    pub retriable: bool,
    /// user:“证书错误要有继续访问”+(证书错误时带上站点 host，前端据此发起显式确认)。
    pub host: Option<String>,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct FindPayload {
    pub tab: String,
    pub matches: usize,
    pub index: i64,
    /// user:“Ctrl+F 在网页聚焦时也要能唤起查找”+(原生快捷键拦下来后，用 `action: "open"` 让前端打开查找条)。
    pub action: Option<String>,
}

pub fn emit_find(app: &AppHandle, payload: FindPayload) {
    let _ = app.emit_to("main", EVENT_FIND, payload);
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PermissionPayload {
    pub tab: String,
    pub host: String,
    pub kind: String,
    /// `allow` / `deny`：`deny` 配 `request_id` 时表示「已按拒绝处理，等用户确认」。
    pub decision: String,
    pub scope: Option<String>,
    pub request_id: Option<String>,
    pub message: String,
}

pub fn emit_permission(app: &AppHandle, payload: PermissionPayload) {
    let _ = app.emit_to("main", EVENT_PERMISSION, payload);
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SiteDataPayload {
    pub tab: String,
    pub host: String,
    pub kinds: Vec<String>,
    pub cleared: bool,
    pub message: String,
}

pub fn emit_site_data(app: &AppHandle, payload: SiteDataPayload) {
    let _ = app.emit_to("main", EVENT_SITE_DATA, payload);
}

/// user:“第三方网页无法越权调用 Tauri 命令”+(静态断言只是第一道闸，运行时自检给出真实结论)。
#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DiagnosticsPayload {
    pub tab: String,
    /// 三个全局都不存在才算通过：`__TAURI_INTERNALS__` / `ipc` / `__TAURI__`。
    pub passed: bool,
    pub checks: Vec<DiagnosticsCheck>,
    pub message: String,
    /// user:“后台标签消息投递可观测”+(最近一次 Agent 指令投递：是否后台、是否收到应答、耗时)。
    /// 只报事实，不下结论：有没有应答本身就是「要不要先临时显示」的判定依据。
    pub delivery: Option<bridge::DeliveryRecord>,
    /// 上面那条记录的可读一句话；没有记录时说明原因。
    pub delivery_note: String,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DiagnosticsCheck {
    pub name: String,
    pub passed: bool,
    pub detail: String,
}

pub fn emit_diagnostics(app: &AppHandle, payload: DiagnosticsPayload) {
    let _ = app.emit_to("main", EVENT_DIAGNOSTICS, payload);
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DownloadPayload {
    pub tab: String,
    pub record: download::DownloadRecord,
}

/// 只带三个白名单头的搬运结构；Cookie 不落盘、不进日志。
#[derive(Clone, Debug, Default, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DownloadHeaders {
    pub cookie: String,
    pub user_agent: String,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DownloadHeadersPayload {
    pub tab: String,
    pub url: String,
    pub cookie: String,
    pub user_agent: String,
}

pub fn emit_download_headers(app: &AppHandle, tab: &str, url: &str, headers: DownloadHeaders) {
    let _ = app.emit_to(
        "main",
        EVENT_DOWNLOAD_HEADERS,
        DownloadHeadersPayload {
            tab: tab.to_string(),
            url: url.to_string(),
            cookie: headers.cookie,
            user_agent: headers.user_agent,
        },
    );
}

pub fn emit_download(app: &AppHandle, tab: &str, record: download::DownloadRecord) {
    let _ = app.emit_to("main", EVENT_DOWNLOAD, DownloadPayload { tab: tab.to_string(), record });
}

/// 下载落盘目录：系统下载目录下的 `Sunday` 子目录（M3 不做「按项目分目录」）。
pub fn download_dir(app: &AppHandle) -> Option<std::path::PathBuf> {
    let base = app.path().download_dir().ok()?;
    let dir = base.join(download::DOWNLOAD_FOLDER);
    std::fs::create_dir_all(&dir).ok()?;
    Some(dir)
}

/// `on_download` 的 Requested 分支调用：记账并通知前端。
pub fn record_download_started(app: &AppHandle, tab: &str, url: &str, target: &std::path::Path, now: &str) {
    let record = with_runtime(|rt| {
        let id = rt.downloads.begin(tab, url, target, now);
        Ok(rt.downloads.get(&id).cloned())
    })
    .ok()
    .flatten();
    if let Some(record) = record {
        emit_download(app, tab, record);
    }
}

/// `on_download` 的 Finished 分支调用：更新为完成/失败。
pub fn record_download_finished(
    app: &AppHandle,
    tab: &str,
    url: &str,
    path: Option<&std::path::Path>,
    success: bool,
) {
    let now = security::iso_from_unix(
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|elapsed| elapsed.as_secs())
            .unwrap_or(0),
    );
    let record = with_runtime(|rt| {
        let Some(id) = rt.downloads.pending_id(tab, url) else { return Ok(None) };
        Ok(rt.downloads.finish(&id, path, success, &now))
    })
    .ok()
    .flatten();
    if let Some(record) = record {
        emit_download(app, tab, record);
    }
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct FullscreenPayload {
    pub tab: String,
    pub fullscreen: bool,
}

pub fn emit_fullscreen(app: &AppHandle, payload: FullscreenPayload) {
    let _ = app.emit_to("main", EVENT_FULLSCREEN, payload);
}

pub(crate) fn view_for(app: &AppHandle, tab: &str) -> Result<tauri::Webview, BrowserError> {
    let label = label_for(tab).ok_or_else(BrowserError::tab_not_found)?;
    app.get_webview(&label).ok_or_else(BrowserError::tab_not_found)
}

#[derive(Clone, Debug, Serialize)]
pub struct OpenPayload {
    pub tab: String,
}

#[derive(Clone, Debug, Serialize)]
pub struct ReopenPayload {
    pub url: String,
    pub title: String,
}

#[derive(Clone, Debug, Serialize)]
pub struct ZoomPayload {
    pub zoom: f64,
}

// user:“在 Sunday 里能打开一个网页”+(open 是唯一创建子 webview 的入口，label 由 Rust 分配)。
// profile 可在 open 时指定（normal/incognito/自定义目录），但创建之后无法再改：controller 建好就带上了环境。
//
// user:“一开网页整个界面就未响应”+(必须是 async 命令：tauri 的同步命令跑在**主线程**上，而
// `tauri::Window::add_child` 内部是 `run_on_main_thread(...)` + `rx.recv()` 阻塞等待 →
// 主线程等主线程 = 自死锁，整个 IPC 与窗口消息泵都会停住（实测：调用后 `Responding=False`，
// 连 `plugin:window|is_maximized` 都超时）。改成 async 后命令跑在异步运行时的任务线程上，
// `add_child` 投递给主线程的闭包才有机会执行。本文件其余命令不经过 `add_child`，
// 用的 set_size/navigate/show/hide/with_webview 都只是向事件循环**投递**消息（不等待），不需要 async。
#[tauri::command]
pub async fn browser_open(
    app: AppHandle,
    webview: tauri::Webview,
    url: String,
    opener_tab: Option<String>,
    profile: Option<String>,
) -> Result<OpenPayload, BrowserError> {
    url_policy::require_main(&webview)?;
    let engine = SearchEngine::default_engine();
    let target = url_policy::navigation_target(&url, &engine)?;
    let profile = BrowserProfile::parse(profile.as_deref().unwrap_or(""))?;
    open_browser_tab(&app, &webview, target, opener_tab, profile).await
}

async fn open_browser_tab(
    app: &AppHandle,
    webview: &tauri::Webview,
    target: url::Url,
    opener_tab: Option<String>,
    profile: BrowserProfile,
) -> Result<OpenPayload, BrowserError> {
    // user:“临时会话不可用必须明确报错，绝不静默建成共享会话标签”+(隔离路径不存在时先把门关上)。
    if matches!(profile, BrowserProfile::Incognito) && !platform_win::supports_incognito() {
        return Err(temporary_session_unavailable());
    }
    let tab = with_runtime(|rt| rt.tabs.open_with_profile(target.to_string(), opener_tab, profile.clone()))?;
    let window = webview.window().clone();
    // user:“后台标签不销毁但也不可见”+(新标签先按 1×1 离屏创建，等前端下发 bounds 再显示)。
    if let Err(error) = webview::create(app, &window, &tab, &target, Bounds::hidden(), &profile).await {
        let _ = with_runtime(|rt| rt.tabs.close(&tab).map(|_| ()));
        // user:“失败后的降级方案需要重新批准”+(临时会话建不起来就是「不可用」，不退化成共享会话)。
        if matches!(profile, BrowserProfile::Incognito) {
            return Err(BrowserError::new(
                "temporary_session_unavailable",
                format!("临时会话在本版本不可用：{}", error.message),
                false,
            ));
        }
        return Err(error);
    }
    emit_state(app, &tab);
    // user:“去掉原生命中区（LamToolsSnapOverlay）”+(命中区已删除：不再需要把子窗口抬到网页之上，
    // 窗口按钮由前端 DOM 直接调 `minimize_window` / `toggle_maximize_window`。
    // 原因见 `windows_snap_layout.rs` 顶部注释：`[snap-click]`/`[window-ctl]` 长期 0 命中，
    // 且前端报来的按钮矩形与屏幕实际位置不符——这套原生方案已证伪。)
    Ok(OpenPayload { tab })
}

/// user:“临时会话不可用”+(固定错误码，前端据此把入口置灰并说明原因)。
fn temporary_session_unavailable() -> BrowserError {
    BrowserError::new("temporary_session_unavailable", "临时会话在本版本不可用（当前平台不支持 WebView2 InPrivate）", false)
}

#[tauri::command]
pub fn browser_close(app: AppHandle, webview: tauri::Webview, tab: String) -> Result<(), BrowserError> {
    url_policy::require_main(&webview)?;
    #[cfg(windows)]
    {
        let _ = compositor::close_tab(&app, &tab);
    }
    #[cfg(not(windows))]
    if let Ok(view) = view_for(&app, &tab) {
        // 关闭即释放：不等 GC，直接把子 webview 拆掉。
        let _ = view.close();
    }
    with_runtime(|rt| {
        rt.bounds.remove(&tab);
        rt.groups.remove(&tab);
        if rt.fullscreen.as_deref() == Some(tab.as_str()) {
            rt.fullscreen = None;
        }
        // 等确认的授权请求随标签一起作废：deferral 丢掉即按已写的拒绝生效。
        let stale = rt
            .pending_permissions
            .iter()
            .filter(|(_, pending)| pending.tab == tab)
            .map(|(id, _)| id.clone())
            .collect::<Vec<_>>();
        for id in stale {
            rt.pending_permissions.remove(&id);
        }
        rt.favicons.forget(&tab);
        // user:“关闭即释放”+(桥的等待项、ref 台账、频率计数随标签一起清掉，避免旧编号在重开标签上复活)。
        rt.refs.remove(&tab);
        bridge::forget_tab(&tab);
        rt.tabs.close(&tab).map(|_| ())
    })?;
    // user:“未进入实际网页，而是处于新标签页”+(原生标签没了、界面那块分屏还留着，
    // 就只剩一张「新标签页」；关标签必须广播，界面据此把分屏标签一起收掉)。
    let _ = app.emit_to("main", EVENT_TAB_CLOSED, serde_json::json!({ "tab": tab }));
    Ok(())
}

// user:“两个网页重叠”+(同一块界面里只允许一个网页可见：把同组里仍然显示着的其它标签收起来。
//  返回被收起的那批（id + 收起后的矩形），调用方负责真的去隐藏；运行时的记账在这里一并更新，
//  这样后续任何读 bounds 的路径看到的都是「已隐藏」)。
#[cfg(windows)]
fn hide_group_siblings(tab: &str) -> Vec<(String, Bounds)> {
    with_runtime(|rt| {
        let group = match rt.groups.get(tab).cloned() {
            Some(group) => group,
            None => return Ok(Vec::new()),
        };
        let mut hidden: Vec<(String, Bounds)> = Vec::new();
        for (id, owner) in rt.groups.iter() {
            if id == tab || owner != &group {
                continue;
            }
            if let Some(bounds) = rt.bounds.get(id).copied() {
                if bounds.visible {
                    hidden.push((id.clone(), Bounds { visible: false, ..bounds }));
                }
            }
        }
        for (id, bounds) in hidden.iter() {
            rt.bounds.insert(id.clone(), *bounds);
        }
        Ok(hidden)
    })
    .unwrap_or_default()
}

#[tauri::command]
pub fn browser_activate(app: AppHandle, webview: tauri::Webview, tab: String) -> Result<(), BrowserError> {
    url_policy::require_main(&webview)?;
    let others = with_runtime(|rt| {
        rt.tabs.activate(&tab)?;
        Ok(rt.tabs.ids().into_iter().filter(|id| id != &tab).collect::<Vec<_>>())
    })?;
    // user:“两个网页重叠”+(切换标签时：先把**同一块分屏**里其它网页收起，
    //  并且这次激活不按「上次存的矩形」直接上屏——那份矩形可能来自更早的窄布局，
    //  直接上屏就会留下一块位置/宽度都不对的旧网页。真正的位置等前端随后下发的 bounds。)
    #[cfg(windows)]
    {
        let _ = others;
        for (id, bounds) in hide_group_siblings(&tab) {
            let _ = compositor::set_bounds(&app, &id, bounds);
        }
    }
    #[cfg(not(windows))]
    {
        if let Ok(view) = view_for(&app, &tab) {
            let bounds = with_runtime(|rt| Ok(rt.bounds.get(&tab).copied())).ok().flatten();
            if let Some(bounds) = bounds {
                let _ = webview::set_bounds(&view, Bounds { visible: true, ..bounds });
            }
        }
        for other in others {
            if let Ok(view) = view_for(&app, &other) {
                let _ = webview::hide_offscreen(&view);
            }
        }
    }
    emit_state(&app, &tab);
    Ok(())
}

// user:“Ctrl+Shift+T 能把关掉的标签找回来”+(Rust 只提供关闭栈内容，重建仍走前端布局模型)。
#[tauri::command]
pub fn browser_reopen_closed(webview: tauri::Webview) -> Result<ReopenPayload, BrowserError> {
    url_policy::require_main(&webview)?;
    let closed = with_runtime(|rt| Ok(rt.tabs.reopen()))?
        .ok_or_else(|| BrowserError::new("tab_not_found", "没有可恢复的标签", false))?;
    Ok(ReopenPayload { url: closed.url, title: closed.title })
}

// user:“网页不能盖住 Sunday 的菜单/浮层”+(可见性由前端纯函数算好后下发，Rust 只做执行器，并拒绝后台标签抢可见区域)。
#[tauri::command]
pub fn browser_bounds(
    app: AppHandle,
    webview: tauri::Webview,
    tab: String,
    x: f64,
    y: f64,
    width: f64,
    height: f64,
    visible: bool,
    // user:“网页跑到分屏外面”+(一次性诊断用的对齐键：前后端各打一行同 trace 的日志，
    // 用来把「前端宿主矩形 / 前端下发值 / 后端收到值 / 换算出的物理值」四者对齐)。
    trace: Option<String>,
    is_float: Option<bool>,
    stack_index: Option<u32>,
    // user:“两个网页重叠”+(所属界面：'area:<分屏>'、'surface:<浮窗>'；Rust 只拿它做同组互斥)。
    group: Option<String>,
) -> Result<(), BrowserError> {
    url_policy::require_main(&webview)?;
    let bounds = Bounds::validated(x, y, width, height, visible)?;
    let allowed = with_runtime(|rt| {
        rt.tabs.get(&tab)?;
        if let Some(group) = group.as_ref() {
            rt.groups.insert(tab.clone(), group.clone());
        }
        #[cfg(not(windows))]
        if bounds.visible && !rt.tabs.is_active(&tab) {
            return Err(BrowserError::tab_inactive());
        }
        rt.bounds.insert(tab.clone(), bounds);
        Ok(())
    });
    allowed?;
    #[cfg(windows)]
    {
        let _ = trace;
        // user:“两个网页重叠”+(同组互斥：这一页要显示，就先收起同组里还显示着的其它页。
        //  放在合成层之前做，保证「同一块分屏同时只有一个网页可见」是一条不变量，
        //  而不是靠某个路径恰好记得隐藏)。
        if bounds.visible {
            for (id, sibling) in hide_group_siblings(&tab) {
                let _ = compositor::set_bounds(&app, &id, sibling);
            }
        }
        // user:“浮层网页层级不对，被分屏遮挡了”+(浮窗标记不再在 Windows 侧被丢掉：
        //  合成层用它保证浮窗永远排在分屏之上，而不是只信一个可能漂移的相对插入)。
        compositor::set_stacked_bounds(&app, &tab, is_float.unwrap_or(false), bounds, stack_index)?;
        return Ok(());
    }
    #[cfg(not(windows))]
    {
        let _ = (is_float, stack_index);
        let view = view_for(&app, &tab)?;
        webview::set_bounds(&view, bounds)?;
        log_bounds_diag(trace.as_deref(), &tab, &bounds, &view);
        Ok(())
    }
}

/// user:“迁移”+(透明主界面上的网页区域把鼠标/滚轮事件路由给底层 CompositionController)。
#[tauri::command]
pub fn browser_input(
    app: AppHandle,
    webview: tauri::Webview,
    tab: String,
    kind: i32,
    virtual_keys: i32,
    wheel_delta: u32,
    x: i32,
    y: i32,
) -> Result<(), BrowserError> {
    url_policy::require_main(&webview)?;
    #[cfg(windows)]
    {
        compositor::send_mouse(&app, &tab, kind, virtual_keys, wheel_delta, x, y)?;
    }
    #[cfg(not(windows))]
    {
        let _ = (app, tab, kind, virtual_keys, wheel_delta, x, y);
    }
    Ok(())
}

/// user:“网页跑到分屏外面”+(坐标空间约定，写死在这里，别处不要再换算：
/// **前端只传 CSS px（= 逻辑像素，相对主 webview 视口）；Rust 只把逻辑值交给
/// `LogicalPosition/LogicalSize`，由 tauri 按窗口 scale_factor 换成物理像素。**
/// 两侧都不许自己乘 `devicePixelRatio`——150% 缩放下那会正好偏 1.5 倍)。
///
/// 诊断只在 dev 构建输出：同一 trace 能对齐「收到什么 → 期望物理坐标 → webview 实际回读」。
fn log_bounds_diag(trace: Option<&str>, tab: &str, bounds: &Bounds, view: &tauri::Webview) {
    if !cfg!(debug_assertions) {
        return;
    }
    let window = view.window();
    let scale = window.scale_factor().unwrap_or(1.0);
    let inner = window.inner_size().map(|size| (size.width, size.height)).unwrap_or((0, 0));
    let inner_pos = window.inner_position().map(|p| (p.x, p.y)).unwrap_or((0, 0));
    let outer_pos = window.outer_position().map(|p| (p.x, p.y)).unwrap_or((0, 0));
    // user:“网页盖住页眉/标题栏”+(判据：子 webview 的落位坐标是**相对父窗口客户区**的
    // （wry `set_bounds_inner` 用 `SetWindowPos(子窗口, …, position)`，Windows 对子窗口按父客户区解释；
    //  `parent_bounds` 也是 `GetClientRect`）。所以 `inner_position - outer_position` 只描述
    //  「客户区原点相对外框原点」的那点偏移，**绝不能出现在落点里**：
    //  recv_phys 必须是客户区坐标，actual_phys 必须与之相等（delta=0）；
    //  若哪天有人改用 outer_position 做基准，落点就会整体少掉 frame 这一段 → 正好盖住页眉。
    // 典型无边框窗口（本项目 decorations=false）frame≈(0,0)，带原生标题栏时通常 (0,~31)。
    let frame = client_origin_offset(inner_pos, outer_pos);
    let actual_pos = view.position().map(|p| (p.x, p.y)).unwrap_or((-1, -1));
    let actual_size = view.size().map(|s| (s.width, s.height)).unwrap_or((0, 0));
    let dx = (actual_pos.0 as f64) - bounds.x;
    let dy = (actual_pos.1 as f64) - bounds.y;
    let dw = (actual_size.0 as f64) - bounds.width;
    let dh = (actual_size.1 as f64) - bounds.height;
    // user:“避免点到别处”+(落位窗口必须是主窗口；不是就明确标出来，别默默画到别的窗口上)。
    let parent = window.label().to_string();
    let parent_ok = parent == "main";
    eprintln!(
        "[bounds-diag] trace={} tab={} parent={}{} view={} recv_phys=({:.1},{:.1} {:.1}x{:.1} vis={}) win_scale={} win_inner_phys={}x{} inner_pos=({},{}) outer_pos=({},{}) frame=({},{}) actual_phys=({},{} {}x{}) delta=({:.1},{:.1} {:.1}x{:.1})",
        trace.unwrap_or("-"),
        tab,
        parent,
        if parent_ok { "" } else { "(!!不是主窗口)" },
        view.label(),
        bounds.x,
        bounds.y,
        bounds.width,
        bounds.height,
        bounds.visible,
        scale,
        inner.0,
        inner.1,
        inner_pos.0,
        inner_pos.1,
        outer_pos.0,
        outer_pos.1,
        frame.0,
        frame.1,
        actual_pos.0,
        actual_pos.1,
        actual_size.0,
        actual_size.1,
        dx,
        dy,
        dw,
        dh
    );
    // user:“最大化/最小化、点更多没反应”+(若窗口里存在**另一个**子 webview 且盖住了页眉区域，
    // 原生窗口会把点击全吃在那个 webview 上——DOM 完全收不到。这里把同窗口下所有 webview
    // 的标签与矩形一起打出来，一条日志就能判断「是不是有第二块网页面」)。
    let mut siblings = String::new();
    for other in window.webviews() {
        let pos = other.position().map(|p| (p.x, p.y)).unwrap_or((-1, -1));
        let size = other.size().map(|s| (s.width, s.height)).unwrap_or((0, 0));
        siblings.push_str(&format!(
            " [{}({},{} {}x{}){}]",
            other.label(),
            pos.0,
            pos.1,
            size.0,
            size.1,
            if other.label() == view.label() { "|this" } else { "|other" }
        ));
    }
    eprintln!("[bounds-diag-siblings]{siblings}");
}

/// 客户区原点相对窗口外框原点的偏移（`inner_position - outer_position`）。
///
/// user:“网页盖住页眉/标题栏”+(这个偏移只用来核对坐标系，**不允许被加到落点上**：
/// 子 webview 的坐标是相对客户区的，再加一次就会向上顶掉一个标题栏高度)。
pub fn client_origin_offset(inner: (i32, i32), outer: (i32, i32)) -> (i32, i32) {
    (inner.0 - outer.0, inner.1 - outer.1)
}

/// 屏幕坐标 → 客户区坐标（落位前若要换算，只能减去 `inner_position`，不能减 `outer_position`）。
pub fn screen_to_client(screen: (i32, i32), inner: (i32, i32)) -> (i32, i32) {
    (screen.0 - inner.0, screen.1 - inner.1)
}

/// 逻辑像素 → 物理像素（唯一换算入口，供诊断与单测共用）。
pub fn logical_to_physical(x: f64, y: f64, width: f64, height: f64, scale: f64) -> (f64, f64, f64, f64) {
    (x * scale, y * scale, width * scale, height * scale)
}

/// 物理像素 → 逻辑像素（反向核对用；scale 非法时原样返回）。
pub fn physical_to_logical(x: f64, y: f64, width: f64, height: f64, scale: f64) -> (f64, f64, f64, f64) {
    if !(scale > 0.0) {
        return (x, y, width, height);
    }
    (x / scale, y / scale, width / scale, height / scale)
}

#[derive(Clone, Debug, serde::Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum NavAction {
    Navigate,
    Back,
    Forward,
    Reload,
    Stop,
    Home,
}

impl NavAction {
    fn parse(raw: &str) -> Result<Self, BrowserError> {
        match raw {
            "navigate" => Ok(Self::Navigate),
            "back" => Ok(Self::Back),
            "forward" => Ok(Self::Forward),
            "reload" => Ok(Self::Reload),
            "stop" => Ok(Self::Stop),
            "home" => Ok(Self::Home),
            other => Err(BrowserError::new("unsupported", format!("未知导航动作：{other}"), false)),
        }
    }
}

#[tauri::command]
pub fn browser_nav(
    app: AppHandle,
    webview: tauri::Webview,
    tab: String,
    action: String,
    url: Option<String>,
    query: Option<String>,
) -> Result<(), BrowserError> {
    url_policy::require_main(&webview)?;
    with_runtime(|rt| rt.tabs.get(&tab).map(|_| ()))?;
    let engine = SearchEngine::default_engine();
    #[cfg(windows)]
    {
        match NavAction::parse(&action)? {
            NavAction::Navigate => {
                let target = match (query, url) {
                    (Some(query), _) => url_policy::parse_web(&engine.url_for(&query)?)?,
                    (None, Some(url)) => url_policy::navigation_target(&url, &engine)?,
                    (None, None) => return Err(BrowserError::new("invalid_url", "请输入网址或搜索内容", false)),
                };
                compositor::navigate(&app, &tab, target.as_str())?;
                with_runtime(|rt| {
                    let state = rt.tabs.get_mut(&tab)?;
                    state.url = target.to_string();
                    state.loading = true;
                    Ok(())
                })?;
                emit_state(&app, &tab);
            }
            NavAction::Back => compositor::with_core_async(&app, &tab, |core, _| { let _ = unsafe { core.GoBack() }; })?,
            NavAction::Forward => compositor::with_core_async(&app, &tab, |core, _| { let _ = unsafe { core.GoForward() }; })?,
            NavAction::Reload => {
                with_runtime(|rt| rt.tabs.get_mut(&tab).map(|state| state.loading = true))?;
                compositor::with_core_async(&app, &tab, |core, _| { let _ = unsafe { core.Reload() }; })?;
                emit_state(&app, &tab);
            }
            NavAction::Stop => compositor::with_core_async(&app, &tab, |core, _| { let _ = unsafe { core.Stop() }; })?,
            NavAction::Home => {
                return Err(BrowserError::unsupported("主页地址还没定义，先用地址栏打开网页"))
            }
        }
        return Ok(());
    }
    #[cfg(not(windows))]
    {
        let view = view_for(&app, &tab)?;
        match NavAction::parse(&action)? {
            NavAction::Navigate => {
                let target = match (query, url) {
                    (Some(query), _) => url_policy::parse_web(&engine.url_for(&query)?)?,
                    (None, Some(url)) => url_policy::navigation_target(&url, &engine)?,
                    (None, None) => return Err(BrowserError::new("invalid_url", "请输入网址或搜索内容", false)),
                };
                webview::navigate(&view, &target)?;
                with_runtime(|rt| {
                    let state = rt.tabs.get_mut(&tab)?;
                    state.url = target.to_string();
                    state.loading = true;
                    Ok(())
                })?;
                emit_state(&app, &tab);
            }
            NavAction::Back => platform_win::go_back(&view)?,
            NavAction::Forward => platform_win::go_forward(&view)?,
            NavAction::Reload => {
                with_runtime(|rt| rt.tabs.get_mut(&tab).map(|state| state.loading = true))?;
                webview::reload(&view)?;
                emit_state(&app, &tab);
            }
            NavAction::Stop => platform_win::stop(&view)?,
            NavAction::Home => {
                return Err(BrowserError::unsupported("主页地址还没定义，先用地址栏打开网页"))
            }
        }
        Ok(())
    }
}

#[tauri::command]
pub fn browser_state(webview: tauri::Webview, tab: String) -> Result<BrowserStatePayload, BrowserError> {
    url_policy::require_main(&webview)?;
    with_runtime(|rt| state_payload(rt, &tab).ok_or_else(BrowserError::tab_not_found))
}

// user:“Ctrl+F 能高亮”+(首版用注入脚本实现查找，接口固定，后续可换原生 Find 接口)。
#[tauri::command]
pub fn browser_find(
    app: AppHandle,
    webview: tauri::Webview,
    tab: String,
    action: String,
    query: Option<String>,
    match_case: Option<bool>,
) -> Result<(), BrowserError> {
    url_policy::require_main(&webview)?;
    with_runtime(|rt| rt.tabs.get(&tab).map(|_| ()))?;
    let match_case = match_case.unwrap_or(false);
    let native = with_runtime(|rt| Ok(rt.tabs.get(&tab)?.native_find))?;
    #[cfg(windows)]
    {
        if native {
            if !matches!(action.as_str(), "start" | "next" | "prev" | "stop") {
                return Err(BrowserError::new("unsupported", format!("未知查找动作：{action}"), false));
            }
            let app_c = app.clone();
            let tab_c = tab.clone();
            let action_c = action.clone();
            let query_c = query.unwrap_or_default();
            return compositor::with_core_async(&app, &tab, move |core, _| {
                platform_win::native_find_core(&app_c, &tab_c, core, &action_c, &query_c, match_case);
            });
        }
        let script = webview::find_script(&action, query.as_deref(), match_case)?;
        let app_c = app.clone();
        let tab_c = tab.clone();
        return compositor::with_core_async(&app, &tab, move |core, _| {
            platform_win::eval_with_result_core(&app_c, &tab_c, core, script);
        });
    }
    #[cfg(not(windows))]
    {
        let view = view_for(&app, &tab)?;
        if native && platform_win::native_find(&app, &tab, &view, &action, query.as_deref(), match_case)? {
            return Ok(());
        }
        let script = webview::find_script(&action, query.as_deref(), match_case)?;
        platform_win::eval_with_result(&app, &tab, &view, script)
    }
}

// user:“Ctrl+滚轮缩放，按标签记忆”+(缩放系数存在 Rust 侧，前端只显示与触发)。
#[tauri::command]
pub fn browser_zoom(
    app: AppHandle,
    webview: tauri::Webview,
    tab: String,
    action: String,
    value: Option<f64>,
) -> Result<ZoomPayload, BrowserError> {
    url_policy::require_main(&webview)?;
    let zoom = zoom_to(&app, &tab, &action, value)?;
    Ok(ZoomPayload { zoom })
}

/// user:“Ctrl+加/减/0 转自家命令”+(加速键回调也走这里，命令与快捷键只有一份缩放实现)。
pub fn zoom_step(app: &AppHandle, tab: &str, action: &str) -> Result<f64, BrowserError> {
    zoom_to(app, tab, action, None)
}

fn zoom_to(app: &AppHandle, tab: &str, action: &str, value: Option<f64>) -> Result<f64, BrowserError> {
    let zoom = with_runtime(|rt| {
        let state = rt.tabs.get_mut(tab)?;
        let next = match action {
            "set" => value.ok_or_else(|| BrowserError::new("invalid_zoom", "缺少缩放值", false))?,
            "in" => state.zoom * 1.1,
            "out" => state.zoom / 1.1,
            "reset" => 1.0,
            other => return Err(BrowserError::new("unsupported", format!("未知缩放动作：{other}"), false)),
        };
        let next = if next.is_finite() { next.clamp(0.25, 5.0) } else { 1.0 };
        state.zoom = (next * 100.0).round() / 100.0;
        Ok(state.zoom)
    })?;
    #[cfg(windows)]
    compositor::set_zoom(app, tab, zoom)?;
    #[cfg(not(windows))]
    {
        let view = view_for(app, tab)?;
        view.set_zoom(zoom).map_err(|error| BrowserError::internal(format!("缩放失败：{error}")))?;
    }
    emit_state(app, tab);
    Ok(zoom)
}

// user:“网页请求全屏时能真全屏”+(网页全屏与 F11 窗口全屏分开：F11 由前端处理)。
#[tauri::command]
pub fn browser_fullscreen(
    app: AppHandle,
    webview: tauri::Webview,
    tab: String,
    on: bool,
) -> Result<(), BrowserError> {
    url_policy::require_main(&webview)?;
    with_runtime(|rt| rt.tabs.get(&tab).map(|_| ()))?;
    apply_fullscreen(&app, &tab, on)
}

/// 进入/退出网页全屏。进入时把该 webview 撑满窗口，退出时还原上次 bounds。
pub fn apply_fullscreen(app: &AppHandle, tab: &str, on: bool) -> Result<(), BrowserError> {
    let view = view_for(app, tab)?;
    let window = view.window().clone();
    if on {
        window
            .set_fullscreen(true)
            .map_err(|error| BrowserError::internal(format!("进入全屏失败：{error}")))?;
        let size = window
            .inner_size()
            .map_err(|error| BrowserError::internal(format!("无法读取窗口尺寸：{error}")))?;
        // user:“网页跑到分屏外面”+(坐标空间约定：Bounds 一律是物理像素，
        // `inner_size()` 本来就是物理像素，直接用，不再 to_logical)。
        let bounds = Bounds::validated(0.0, 0.0, size.width as f64, size.height as f64, true)?;
        webview::set_bounds(&view, bounds)?;
        with_runtime(|rt| {
            rt.fullscreen = Some(tab.to_string());
            rt.bounds.insert(tab.to_string(), bounds);
            Ok(())
        })?;
    } else {
        window
            .set_fullscreen(false)
            .map_err(|error| BrowserError::internal(format!("退出全屏失败：{error}")))?;
        let restore = with_runtime(|rt| {
            rt.fullscreen = None;
            Ok(rt.bounds.get(tab).copied())
        })?;
        if let Some(bounds) = restore {
            webview::set_bounds(&view, bounds)?;
        }
    }
    emit_fullscreen(app, FullscreenPayload { tab: tab.to_string(), fullscreen: on });
    Ok(())
}

// ---------------------------------------------------------------------------
// M2：会话形态、权限、证书、站数据清理、越权自检
// ---------------------------------------------------------------------------

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ProfileEntry {
    pub name: String,
    pub label: String,
    pub available: bool,
    pub persistent: bool,
    pub note: String,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ProfilesPayload {
    pub profiles: Vec<ProfileEntry>,
    pub temporary_session_available: bool,
}

/// user:“新标签旁的下拉：普通 / 临时”+(不可用的会话形态要置灰并给出原因，而不是点了才报错)。
#[tauri::command]
pub fn browser_profiles(webview: tauri::Webview) -> Result<ProfilesPayload, BrowserError> {
    url_policy::require_main(&webview)?;
    let temporary = platform_win::supports_incognito();
    Ok(ProfilesPayload {
        profiles: vec![
            ProfileEntry {
                name: "normal".to_string(),
                label: "普通".to_string(),
                available: true,
                persistent: true,
                note: "登录态跨重启保留".to_string(),
            },
            ProfileEntry {
                name: "incognito".to_string(),
                label: "临时".to_string(),
                available: temporary,
                persistent: false,
                note: if temporary {
                    "关闭即丢弃，登录态不保留".to_string()
                } else {
                    "临时会话在本版本不可用".to_string()
                },
            },
        ],
        temporary_session_available: temporary,
    })
}

/// user:“前端最小授权确认后回命令放行（仅本次/该站点）”+(授权表只由 Rust 写；必须带 tab 与 requestId，跨标签一律拒绝)。
#[tauri::command]
pub fn browser_permission(
    app: AppHandle,
    webview: tauri::Webview,
    tab: String,
    request_id: String,
    decision: String,
    scope: Option<String>,
) -> Result<(), BrowserError> {
    url_policy::require_main(&webview)?;
    let allow = match decision.as_str() {
        "allow" => true,
        "deny" => false,
        other => return Err(BrowserError::new("unsupported", format!("未知的授权决定：{other}"), false)),
    };
    let scope = security::PermissionScope::parse(scope.as_deref().unwrap_or("once"))?;
    let pending = with_runtime(|rt| {
        rt.pending_permissions.remove(&request_id).ok_or_else(|| {
            BrowserError::new("permission_denied", "这个授权请求已经失效，请让页面重新发起", false)
        })
    })?;
    if pending.tab != tab {
        return Err(BrowserError::new("permission_denied", "这个授权请求不属于当前标签", false));
    }
    if allow && matches!(scope, security::PermissionScope::Site) {
        // user:“写盘失败要有明确错误”+(授权不落盘就等于没记住，所以写盘失败直接把错误抛给前端)。
        with_runtime(|rt| rt.permissions.grant(&pending.host, pending.kind))?;
    }
    let host = pending.host.clone();
    let kind = pending.kind;
    let ticket = pending.ticket;
    #[cfg(windows)]
    {
        let _ = app.run_on_main_thread(move || {
            platform_win::resolve_permission_ticket(ticket, allow);
        });
    }
    #[cfg(not(windows))]
    {
        let view = view_for(&app, &tab)?;
        let _ = view.with_webview(move |_platform| {
            platform_win::resolve_permission_ticket(ticket, allow);
        });
    }
    emit_permission(
        &app,
        PermissionPayload {
            tab: tab.clone(),
            host: host.clone(),
            kind: kind.label().to_string(),
            decision: if allow { "allow".to_string() } else { "deny".to_string() },
            scope: Some(
                match scope {
                    security::PermissionScope::Once => "once",
                    security::PermissionScope::Site => "site",
                }
                .to_string(),
            ),
            request_id: None,
            message: if allow {
                format!("已允许 {host} 使用{}", kind.display())
            } else {
                security::permission_denied_message(&host, kind)
            },
        },
    );
    Ok(())
}

/// user:“站数据清理：按 host 删 Cookie + 清缓存”+(不用 CDP；清理后同一 host 的登录态应失效)。
#[tauri::command]
pub fn browser_clear_site_data(
    app: AppHandle,
    webview: tauri::Webview,
    tab: String,
    host: String,
    kinds: Option<Vec<String>>,
) -> Result<(), BrowserError> {
    url_policy::require_main(&webview)?;
    with_runtime(|rt| rt.tabs.get(&tab).map(|_| ()))?;
    let host = session::require_host(&host)?;
    let kinds = session::SiteDataKinds::parse(kinds.as_deref())?;
    if kinds.is_empty() {
        return Err(BrowserError::new("unsupported", "没有选择要清理的内容", false));
    }
    // user:“清站数据连带撤销授权”+(清了数据还留着摄像头权限会误导用户；这里同步落盘，失败就报错)。
    with_runtime(|rt| rt.permissions.clear_host(&host))?;
    #[cfg(windows)]
    {
        let app_c = app.clone();
        let tab_c = tab.clone();
        return compositor::with_core_async(&app, &tab, move |core, _| {
            platform_win::clear_site_data_core(&app_c, &tab_c, core, host, kinds);
        });
    }
    #[cfg(not(windows))]
    {
        let view = view_for(&app, &tab)?;
        platform_win::clear_site_data(&app, &tab, &view, host, kinds)
    }
}

/// user:“证书错误被阻断且可读，「继续访问」要显式确认”+(我们只做一次性放行；WebView2 的
/// `ALWAYS_ALLOW` 会在本次会话里记住该主机，所以额外提供 `forget` 显式清除，不声称会自动过期)。
#[tauri::command]
pub fn browser_certificate(
    app: AppHandle,
    webview: tauri::Webview,
    tab: String,
    host: String,
    action: String,
) -> Result<(), BrowserError> {
    url_policy::require_main(&webview)?;
    with_runtime(|rt| rt.tabs.get(&tab).map(|_| ()))?;
    let host = session::require_host(&host)?;
    match action.as_str() {
        "continue" => {
            with_runtime(|rt| {
                rt.certificate_allows.insert(host.clone());
                Ok(())
            })?;
            #[cfg(windows)]
            {
                compositor::with_core_async(&app, &tab, |core, _| { let _ = unsafe { core.Reload() }; })
            }
            #[cfg(not(windows))]
            {
                let view = view_for(&app, &tab)?;
                webview::reload(&view)
            }
        }
        "forget" => {
            with_runtime(|rt| {
                rt.certificate_allows.remove(&host);
                Ok(())
            })?;
            #[cfg(windows)]
            {
                let app_c = app.clone();
                let tab_c = tab.clone();
                compositor::with_core_async(&app, &tab, move |core, _| {
                    platform_win::clear_certificate_memory_core(&app_c, &tab_c, core);
                })
            }
            #[cfg(not(windows))]
            {
                let view = view_for(&app, &tab)?;
                platform_win::clear_certificate_memory(&app, &tab, &view)
            }
        }
        other => Err(BrowserError::new("unsupported", format!("未知的证书操作：{other}"), false)),
    }
}

/// user:“下载列表由 Rust 自维护”+(三态：started/finished/failed，没有字节进度，也没有暂停/继续)。
#[tauri::command]
pub fn browser_downloads(webview: tauri::Webview, tab: Option<String>) -> Result<Vec<download::DownloadRecord>, BrowserError> {
    url_policy::require_main(&webview)?;
    with_runtime(|rt| Ok(rt.downloads.list(tab.as_deref())))
}

/// user:“危险后缀要审批才能打开”+(没有 approve=true 时返回 download_blocked，不静默打开 exe/msi/脚本)。
#[tauri::command]
pub fn browser_download(
    webview: tauri::Webview,
    id: String,
    action: String,
    approve: Option<bool>,
) -> Result<(), BrowserError> {
    url_policy::require_main(&webview)?;
    let record = with_runtime(|rt| {
        rt.downloads.get(&id).cloned().ok_or_else(|| BrowserError::new("tab_not_found", "这条下载记录已经不在列表里", false))
    })?;
    if record.state != download::DownloadState::Finished {
        return Err(BrowserError::new("unsupported", "文件还没下载完", true));
    }
    let Some(path) = record.path.clone().map(std::path::PathBuf::from) else {
        return Err(BrowserError::new("internal", "这条下载记录没有落盘路径", false));
    };
    match action.as_str() {
        "open" => {
            if record.needs_approval && approve != Some(true) {
                return Err(BrowserError::new(
                    "download_blocked",
                    format!("{} 是可执行/脚本文件，确认来源可信后才能打开", record.filename),
                    false,
                ));
            }
            open::that(&path).map_err(|error| BrowserError::internal(format!("打开文件失败：{error}")))
        }
        "reveal" => {
            let dir = path.parent().map(|parent| parent.to_path_buf()).unwrap_or(path.clone());
            open::that(&dir).map_err(|error| BrowserError::internal(format!("打开所在文件夹失败：{error}")))
        }
        other => Err(BrowserError::new("unsupported", format!("未知的下载操作：{other}"), false)),
    }
}

/// user:“修”+(保留命令兼容性，桌面下载事件无法确认原请求可重放，报告接管未开启)。
#[tauri::command]
pub fn browser_download_takeover(webview: tauri::Webview, enabled: bool) -> Result<bool, BrowserError> {
    url_policy::require_main(&webview)?;
    let _ = enabled;
    Ok(false)
}

/// 读当前标签对该 URL 的 Cookie 与 User-Agent；结果用事件回传，不阻塞 UI 线程。
#[tauri::command]
pub fn browser_download_headers(
    app: AppHandle,
    webview: tauri::Webview,
    tab: String,
    url: String,
) -> Result<(), BrowserError> {
    url_policy::require_main(&webview)?;
    if !download::handoff_candidate(&url) {
        return Err(BrowserError::new("invalid_url", "只能把 HTTP 或 HTTPS 直链交给 EasyNet", false));
    }
    platform_win::read_download_headers(&app, &tab, &url);
    Ok(())
}

/// 在原标签中重新请求一个已知可以直接打开的下载地址。
#[tauri::command]
pub fn browser_download_retry(
    app: AppHandle,
    webview: tauri::Webview,
    tab: String,
    url: String,
) -> Result<(), BrowserError> {
    url_policy::require_main(&webview)?;
    if !download::handoff_candidate(&url) {
        return Err(BrowserError::new("invalid_url", "只能重试 HTTP 或 HTTPS 下载", false));
    }
    let view = view_for(&app, &tab)?;
    let parsed = url
        .parse::<tauri::Url>()
        .map_err(|_| BrowserError::new("invalid_url", "下载地址无效", false))?;
    view.navigate(parsed)
        .map_err(|error| BrowserError::internal(format!("重新下载失败：{error}")))
}

/// user:“EasyNet 开了加速，浏览器立刻用上；关掉就回到系统代理”+(只改之后创建的网页，已打开的要重开)。
#[tauri::command]
pub fn browser_network_state(
    webview: tauri::Webview,
    mode: String,
    endpoint: Option<String>,
) -> Result<bool, BrowserError> {
    url_policy::require_main(&webview)?;
    #[cfg(windows)]
    {
        return Ok(compositor::set_network_state(&mode, endpoint.as_deref().unwrap_or("")));
    }
    #[cfg(not(windows))]
    {
        let _ = (mode, endpoint);
        Ok(false)
    }
}

/// user:“第三方网页无法越权调用 Tauri 命令”+(运行时自检：在浏览器标签里探三个全局并尝试越权调用)。
#[tauri::command]
pub fn browser_diagnostics(
    app: AppHandle,
    webview: tauri::Webview,
    tab: String,
) -> Result<(), BrowserError> {
    url_policy::require_main(&webview)?;
    with_runtime(|rt| rt.tabs.get(&tab).map(|_| ()))?;
    #[cfg(not(windows))]
    {
        let view = view_for(&app, &tab)?;
        platform_win::run_diagnostics(&app, &tab, &view);
    }
    #[cfg(windows)]
    {
        let _ = (&app, &tab);
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// M4：Agent 感知与操作（快照 / 操作 / 等待 / 截图 / 接管）
//
// user:“唯一通道是注入桥 + WebMessage”+(这里只做编排：校验 → 闸门 → 临时显示 → 投递指令 →
// 等应答（带超时）→ 恢复可见性。COM 调用在 platform_win，校验/台账/接管状态机在 bridge)。
// ---------------------------------------------------------------------------

/// user:“进入 human-owned 后 Rust 拒绝一切 Agent 写操作”+(写操作集合与 3.8 的清单一致：
/// click/type/clear/pressKeys/select/scroll；`hover` 会展开菜单改变页面状态，按写操作处理)。
const WRITE_OPS: [&str; 7] = ["click", "type", "clear", "hover", "select", "scroll", "pressKey"];

/// user:“支付/删除/发布这类高风险动作走既有统一审批机制”+(Rust 侧只做动作级声明校验：
/// 带这些 intent 的指令没有显式 `approved` 时一律拒绝，审批本身在工具层完成)。
const APPROVAL_INTENTS: [&str; 4] = ["payment", "delete", "publish", "auth"];

#[derive(Clone, Copy, Debug, Default, PartialEq, Serialize, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ScrollOffset {
    pub x: f64,
    pub y: f64,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Serialize, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PageViewport {
    pub w: f64,
    pub h: f64,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Serialize, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RefBounds {
    pub x: f64,
    pub y: f64,
    pub w: f64,
    pub h: f64,
}

/// 一个可交互元素。`ref` 由页面脚本分配（`e12`），宿主只认最近一次快照出现过的编号。
#[derive(Clone, Debug, PartialEq, Serialize, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SnapshotRef {
    #[serde(rename = "ref")]
    pub r#ref: String,
    pub role: String,
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub value: Option<String>,
    #[serde(default)]
    pub bounds: RefBounds,
    #[serde(default)]
    pub states: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SnapshotTextBlock {
    #[serde(default)]
    pub level: u32,
    #[serde(default)]
    pub text: String,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SnapshotText {
    #[serde(default)]
    pub blocks: Vec<SnapshotTextBlock>,
    #[serde(default)]
    pub truncated: bool,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Serialize, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SnapshotCounts {
    #[serde(default)]
    pub total: u32,
    #[serde(default)]
    pub returned: u32,
    #[serde(default)]
    pub omitted: u32,
}

/// 页面回报的快照原文。URL/标题/加载状态**不用**这里的值（R6：以 COM 为准）。
#[derive(Clone, Debug, Default, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
struct PageSnapshot {
    #[serde(default)]
    refs: Vec<SnapshotRef>,
    #[serde(default)]
    text: SnapshotText,
    #[serde(default)]
    counts: SnapshotCounts,
    #[serde(default)]
    stale: Vec<String>,
    #[serde(default)]
    viewport: PageViewport,
    #[serde(default)]
    scroll: ScrollOffset,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SnapshotPayload {
    pub tab: String,
    /// 以 Rust 侧状态为准（页面回报只作提示）。
    pub url: String,
    pub title: String,
    pub loading: bool,
    pub owner: String,
    pub viewport: PageViewport,
    pub scroll: ScrollOffset,
    pub refs: Vec<SnapshotRef>,
    pub text: SnapshotText,
    pub counts: SnapshotCounts,
    /// 上一份快照里存在、这份里消失的编号。
    pub stale: Vec<String>,
    /// user:“可见文本按需切片，不要每次全量传输”+(任一维度被截断都置真)。
    pub truncated: bool,
    pub sequences: u32,
    /// user:“网页内容一律包成不可信信封”+(工具层据此拒绝把网页文本当指令)。
    pub trust: &'static str,
    pub source: &'static str,
    pub fetched_at: String,
}

#[derive(Clone, Debug, serde::Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ActInstruction {
    pub op: String,
    #[serde(rename = "ref")]
    pub target: Option<String>,
    /// 用 CSS 选择器直接定位目标元素。
    /// user:“内置那个新标签页，我手动输入之后点回车，它搜出来的结果也没有问题”+
    /// (搜索走的是「引擎首页 -> 在它的搜索框里输入 -> 回车」，手上没有 snapshot 给的 ref，
    ///  只能用页面自带的搜索框定位；这是 type/click 的另一种定位方式，不是新增能力)。
    pub selector: Option<String>,
    /// 提交搜索框前把表单里的 form 字段拨回「搜索入口」。
    /// user:“我手动输入之后点回车，它搜出来的结果也没有问题”+
    /// (实测：直接按表单默认按钮提交时，Bing 首页给的是 popularnow.carousel 那个
    ///  「热门内容轮播」视图，整页只有一两条卡片；真人的回车走的是 form=QBRE 的搜索入口)。
    pub form_value: Option<String>,
    pub text: Option<String>,
    pub clear: Option<bool>,
    pub submit: Option<bool>,
    pub value: Option<String>,
    pub key: Option<String>,
    pub dx: Option<f64>,
    pub dy: Option<f64>,
    /// `payment` / `delete` / `publish` / `auth`：声明了就必须走审批。
    pub intent: Option<String>,
    /// 审批通过后由工具层显式置真；模型不能凭自己声明绕过。
    pub approved: Option<bool>,
}

impl ActInstruction {
    /// 只接受结构化操作，不接受选择器字符串之外的即席脚本。
    fn canonical_op(&self) -> Result<&'static str, BrowserError> {
        match self.op.as_str() {
            "click" => Ok("click"),
            "type" => Ok("type"),
            "clear" => Ok("clear"),
            "hover" => Ok("hover"),
            "select" => Ok("select"),
            "scroll" => Ok("scroll"),
            "pressKey" => Ok("pressKey"),
            other => Err(BrowserError::new(
                "unsupported",
                format!("未知操作「{other}」：只接受 click/type/clear/hover/select/scroll/pressKey"),
                false,
            )),
        }
    }

    fn needs_ref(&self) -> bool {
        // 给了 selector 就不需要 ref：搜索流程没有 snapshot，只认页面自带的搜索框。
        if self.selector.as_deref().map(str::trim).is_some_and(|value| !value.is_empty()) {
            return false;
        }
        match self.op.as_str() {
            "click" | "clear" | "hover" | "select" => true,
            // `type` 与 `scroll` 的 ref 可选：不给就作用于当前焦点 / 窗口本身。
            _ => false,
        }
    }

    fn validate(&self) -> Result<(), BrowserError> {
        let op = self.canonical_op()?;
        if let Some(selector) = &self.selector {
            if selector.trim().is_empty() || selector.chars().count() > 400 {
                return Err(BrowserError::new("unsupported", "selector 不能为空，且长度不超过 400", false));
            }
        }
        if self.needs_ref() && self.target.is_none() {
            return Err(BrowserError::new("invalid_ref", format!("{op} 需要 ref（先做一次 browser_snapshot）"), false));
        }
        match op {
            "type" => {
                let text = self.text.as_deref().unwrap_or("");
                if text.chars().count() > 4000 {
                    return Err(BrowserError::new("unsupported", "一次最多输入 4000 个字符", false));
                }
            }
            "select" => {
                if self.value.is_none() {
                    return Err(BrowserError::new("unsupported", "select 需要 value（选项值或选项文本）", false));
                }
            }
            "pressKey" => {
                if self.key.as_deref().unwrap_or("").is_empty() {
                    return Err(BrowserError::new("unsupported", "pressKey 需要 key，例如 \"Enter\"", false));
                }
            }
            "scroll" => {
                if self.target.is_none() && self.dx.is_none() && self.dy.is_none() {
                    return Err(BrowserError::new("unsupported", "scroll 需要 ref 或 dx/dy", false));
                }
                let dx = self.dx.unwrap_or(0.0).abs();
                let dy = self.dy.unwrap_or(0.0).abs();
                if !dx.is_finite() || !dy.is_finite() || dx > 20000.0 || dy > 20000.0 {
                    return Err(BrowserError::new("unsupported", "一次滚动距离必须在 ±20000 像素内", false));
                }
            }
            _ => {}
        }
        Ok(())
    }

    fn page_args(&self) -> serde_json::Value {
        let mut map = serde_json::Map::new();
        map.insert("op".to_string(), serde_json::json!(self.op));
        if let Some(target) = &self.target {
            map.insert("ref".to_string(), serde_json::json!(target));
        }
        if let Some(selector) = &self.selector {
            map.insert("selector".to_string(), serde_json::json!(selector));
        }
        if let Some(form_value) = &self.form_value {
            map.insert("formValue".to_string(), serde_json::json!(form_value));
        }
        if let Some(text) = &self.text {
            map.insert("text".to_string(), serde_json::json!(text));
        }
        if let Some(clear) = self.clear {
            map.insert("clear".to_string(), serde_json::json!(clear));
        }
        if let Some(submit) = self.submit {
            map.insert("submit".to_string(), serde_json::json!(submit));
        }
        if let Some(value) = &self.value {
            map.insert("value".to_string(), serde_json::json!(value));
        }
        if let Some(key) = &self.key {
            map.insert("key".to_string(), serde_json::json!(key));
        }
        if let Some(dx) = self.dx {
            map.insert("dx".to_string(), serde_json::json!(dx));
        }
        if let Some(dy) = self.dy {
            map.insert("dy".to_string(), serde_json::json!(dy));
        }
        serde_json::Value::Object(map)
    }
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ActPayload {
    pub tab: String,
    pub op: String,
    /// 操作是否改变页面 URL 或打开了新标签。
    pub navigated: bool,
    pub url: String,
    pub scroll: Option<ScrollOffset>,
    pub owner: String,
    /// 旧 ref 失效时自动重快照过一次：提示调用方用新编号重试。
    pub resnapshot: bool,
    pub trust: &'static str,
    pub source: &'static str,
    pub fetched_at: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source_tab: Option<String>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub opened_tabs: Vec<OpenedActTab>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub popup_errors: Vec<BrowserError>,
}

#[derive(Clone, Debug, Serialize)]
pub struct OpenedActTab {
    pub tab: String,
    pub url: String,
    pub owner: String,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct WaitPayload {
    pub tab: String,
    pub satisfied: bool,
    pub kind: String,
    pub value: String,
    pub state: String,
    pub elapsed_ms: u64,
    pub url: String,
    pub ready_state: String,
    pub owner: String,
    pub trust: &'static str,
    pub source: &'static str,
    pub fetched_at: String,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ScreenshotPayload {
    pub tab: String,
    pub target: String,
    /// `data:image/png;base64,...`
    pub png: String,
    pub width: u32,
    pub height: u32,
    pub note: String,
    pub trust: &'static str,
    pub source: &'static str,
    pub fetched_at: String,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct OwnershipPayload {
    pub tab: String,
    /// `agent` / `human`
    pub owner: String,
    pub quiet_seconds: u64,
}

fn now_iso() -> String {
    security::iso_from_unix(
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|elapsed| elapsed.as_secs())
            .unwrap_or(0),
    )
}

/// 用户真实输入到达（桥上报 `isTrusted` 事件）：切到 human-owned 并通知前端。
pub fn note_user_input(app: &AppHandle, tab: &str) {
    let changed = with_runtime(|rt| {
        let state = rt.tabs.get_mut(tab)?;
        Ok(state.ownership.note_user_input(std::time::Instant::now()))
    })
    .unwrap_or(false);
    if changed {
        emit_state(app, tab);
    }
}

/// 写操作前的闸门：先按静默阈值自动交还，再过 human-owned 检查。
fn require_agent_control(tab: &str) -> Result<(), BrowserError> {
    with_runtime(|rt| {
        let state = rt.tabs.get_mut(tab)?;
        state.ownership.release_if_quiet(std::time::Instant::now());
        state.ownership.can_write()
    })
}

fn current_owner(tab: &str) -> String {
    with_runtime(|rt| Ok(rt.tabs.get(tab)?.ownership.owner().label().to_string()))
        .unwrap_or_else(|_| "agent".to_string())
}

// user:“后台标签被操作时临时显示，操作期间不给它焦点”+(只有写操作/截图/等待才临时显示；
// 纯读取的 DOM 快照不打扰用户，超时了再退到「临时显示后重试一次」)。
enum RestoreBounds {
    Hide,
    Bounds(webview::Bounds),
}

struct TempShow {
    app: AppHandle,
    tab: String,
    #[cfg(not(windows))]
    view: tauri::Webview,
    restore: RestoreBounds,
}

impl TempShow {
    fn restore(self) {
        #[cfg(windows)]
        {
            let b = match self.restore {
                RestoreBounds::Hide => webview::Bounds::hidden(),
                RestoreBounds::Bounds(bounds) => bounds,
            };
            let _ = compositor::set_bounds(&self.app, &self.tab, b);
        }
        #[cfg(not(windows))]
        match self.restore {
            RestoreBounds::Hide => {
                let _ = webview::hide_offscreen(&self.view);
            }
            RestoreBounds::Bounds(bounds) => {
                let _ = webview::set_bounds(&self.view, bounds);
            }
        }
    }
}

fn begin_agent_foreground(app: &AppHandle, tab: &str) -> Result<Option<TempShow>, BrowserError> {
    let (is_active, stored, active_bounds) = with_runtime(|rt| {
        rt.tabs.get(tab)?;
        let is_active = rt.tabs.is_active(tab);
        let stored = rt.bounds.get(tab).copied();
        let active_bounds = rt
            .tabs
            .active()
            .and_then(|id| rt.bounds.get(id).copied())
            .filter(|bounds| bounds.visible && bounds.width > 2.0 && bounds.height > 2.0);
        Ok((is_active, stored, active_bounds))
    })?;
    let visible = stored.map(|bounds| bounds.visible).unwrap_or(false);
    match bridge::foreground_plan(is_active, visible) {
        bridge::ForegroundPlan::Keep => Ok(None),
        bridge::ForegroundPlan::ShowTemporarily => {
            let rect = stored
                .filter(|bounds| bounds.width > 2.0 && bounds.height > 2.0)
                .or(active_bounds)
                .unwrap_or(webview::Bounds { x: 0.0, y: 0.0, width: 800.0, height: 600.0, visible: false });
            #[cfg(windows)]
            {
                compositor::set_bounds(app, tab, webview::Bounds { visible: true, ..rect })?;
                let restore = if is_active { RestoreBounds::Bounds(rect) } else { RestoreBounds::Hide };
                Ok(Some(TempShow { app: app.clone(), tab: tab.to_string(), restore }))
            }
            #[cfg(not(windows))]
            {
                let view = view_for(app, tab)?;
                webview::set_bounds(&view, webview::Bounds { visible: true, ..rect })?;
                let restore = if is_active { RestoreBounds::Bounds(rect) } else { RestoreBounds::Hide };
                Ok(Some(TempShow { app: app.clone(), tab: tab.to_string(), view, restore }))
            }
        }
    }
}

/// 投递一条指令并等应答。等待放在阻塞线程里，避免占住异步执行器。
async fn page_call(
    app: &AppHandle,
    tab: &str,
    op: &'static str,
    args: serde_json::Value,
    timeout: std::time::Duration,
) -> Result<serde_json::Value, BrowserError> {
    with_runtime(|rt| rt.tabs.get(tab).map(|_| ()))?;
    #[cfg(not(windows))]
    let view = view_for(app, tab)?;
    // user:“后台 WebMessage 投递可观测”+(投递前先判定这条指令是不是发给后台标签：
    // 当前可见的活动标签算前台，其余都算后台——临时显示会把 visible 改成 true，所以必须提前取)。
    let background = with_runtime(|rt| {
        let visible = rt.bounds.get(tab).map(|bounds| bounds.visible).unwrap_or(false);
        Ok(!(visible && rt.tabs.is_active(tab)))
    })?;
    let started = std::time::Instant::now();
    let id = bridge::next_request_id();
    let receiver = bridge::register(&id, tab);
    let payload = serde_json::json!({
        "sunday": bridge::PROTOCOL_VERSION,
        "id": id,
        "op": op,
        "args": args,
    });
    let text = serde_json::to_string(&payload)
        .map_err(|error| BrowserError::internal(format!("指令无法序列化：{error}")))?;
    let timeout = timeout.clamp(bridge::MIN_TIMEOUT, bridge::MAX_TIMEOUT) + std::time::Duration::from_millis(500);
    #[cfg(windows)]
    {
        let json_s = text.clone();
        compositor::with_core_async(app, tab, move |core, _| {
            let _ = unsafe { core.PostWebMessageAsJson(&windows::core::HSTRING::from(json_s.as_str())) };
        })?;
    }
    #[cfg(not(windows))]
    platform_win::post_message(&view, &text)?;
    let reply = tauri::async_runtime::spawn_blocking(move || bridge::wait(receiver, timeout))
        .await
        .map_err(|error| BrowserError::internal(format!("等待页面响应失败：{error}")))?;
    let reply = match reply {
        Ok(reply) => reply,
        Err(mut error) => {
            // user:“不允许静默伪装成功”+(页面其实回话了、只是被判非法时，不能只说「页面没响应」：
            // 把丢弃原因挂到超时错误上，调用方一眼能区分「没回」与「回了但不合法」)。
            if let Some(summary) = bridge::drop_summary(&tab) {
                error.message = format!("{}；{}", error.message, summary);
            }
            bridge::record_delivery(bridge::DeliveryRecord {
                tab: tab.to_string(),
                op: op.to_string(),
                background,
                acked: false,
                outcome: error.code.clone(),
                elapsed_ms: started.elapsed().as_millis() as u64,
            });
            return Err(error);
        }
    };
    let outcome = reply.into_result();
    // 每次投递都记一条：诊断命令读到的就是「最近一次投递成不成」。
    bridge::record_delivery(bridge::DeliveryRecord {
        tab: tab.to_string(),
        op: op.to_string(),
        background,
        acked: outcome.is_ok(),
        outcome: match &outcome {
            Ok(_) => "ok".to_string(),
            Err(error) => error.code.clone(),
        },
        elapsed_ms: started.elapsed().as_millis() as u64,
    });
    outcome
}

/// user:“browser_snapshot 返回 refs 与文本切片”+(URL/标题/加载状态取自 Rust 状态，页面回报只作提示)。
#[tauri::command]
#[allow(clippy::too_many_arguments)]
pub async fn browser_snapshot(
    app: AppHandle,
    webview: tauri::Webview,
    tab: String,
    mode: Option<String>,
    max_nodes: Option<u32>,
    max_chars: Option<u32>,
    scope: Option<String>,
) -> Result<SnapshotPayload, BrowserError> {
    url_policy::require_main(&webview)?;
    let mode = match mode.as_deref() {
        None | Some("interactive") => "interactive",
        Some("text") => "text",
        Some("full") => "full",
        Some(other) => return Err(BrowserError::new("unsupported", format!("未知快照模式：{other}"), false)),
    };
    let scope = match scope.as_deref() {
        None | Some("viewport") => "viewport",
        Some("document") => "document",
        Some(other) => return Err(BrowserError::new("unsupported", format!("未知快照范围：{other}"), false)),
    };
    let max_nodes = max_nodes.unwrap_or(200).clamp(1, 500);
    let max_chars = max_chars.unwrap_or(8000).clamp(200, 32000);
    let args = serde_json::json!({
        "mode": mode,
        "maxNodes": max_nodes,
        "maxChars": max_chars,
        "scope": scope,
    });
    // 只读快照不抢用户视野；万一隐藏页收不到指令（P2 未证实项），再临时显示重试一次。
    let mut call = page_call(&app, &tab, "snapshot", args.clone(), bridge::DEFAULT_TIMEOUT).await;
    if let Err(error) = &call {
        if error.code == "timeout" {
            let temp = begin_agent_foreground(&app, &tab)?;
            let retry = page_call(&app, &tab, "snapshot", args, bridge::DEFAULT_TIMEOUT).await;
            if let Some(temp) = temp {
                temp.restore();
            }
            if retry.is_ok() {
                call = retry;
            }
        }
    }
    let raw = call?;
    let page: PageSnapshot = serde_json::from_value(raw)
        .map_err(|error| BrowserError::new("internal", format!("快照格式不符合预期：{error}"), true))?;
    let (url, title, loading, owner, sequences) = with_runtime(|rt| {
        let state = rt.tabs.get(&tab)?;
        let owner = state.ownership.owner().label().to_string();
        let sequences = rt.refs.entry(tab.clone()).or_default().record_snapshot(
            page.refs.iter().map(|item| item.r#ref.clone()).collect(),
        );
        Ok((state.url.clone(), state.title.clone(), state.loading, owner, sequences))
    })?;
    let truncated = page.text.truncated || page.counts.omitted > 0;
    Ok(SnapshotPayload {
        tab,
        url,
        title,
        loading,
        owner,
        viewport: page.viewport,
        scroll: page.scroll,
        refs: page.refs,
        text: page.text,
        counts: page.counts,
        stale: page.stale,
        truncated,
        sequences,
        trust: "untrusted",
        source: "web",
        fetched_at: now_iso(),
    })
}

// user:“以结构化数据作为 Agent 的主要输入”+(搜索结果与正文都要结构化，不能把整页 HTML 丢给模型：
// 页面侧按调用方给的 CSS 选择器把命中的 DOM 片段清洗后取回，卡片识别与字段配对在 Python 侧做，
// 换搜索引擎只改一个适配器文件，不重编宿主)。
#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct HtmlNodePayload {
    pub selector: String,
    pub html: String,
}

#[derive(Clone, Debug, Default, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct HtmlCountsPayload {
    pub matched: u32,
    pub returned: u32,
    pub omitted: u32,
    pub chars: u32,
    pub truncated: bool,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct HtmlPayload {
    pub tab: String,
    /// 以 Rust 侧状态为准（页面回报只作提示）。
    pub url: String,
    pub title: String,
    pub loading: bool,
    pub nodes: Vec<HtmlNodePayload>,
    pub counts: HtmlCountsPayload,
    /// 页面可见文本前缀：只用来判断「结果页 / 验证码页 / 无结果」，不当作正文。
    pub page_text: String,
    /// 页面拒收的选择器（语法非法等）：不让一个写错的选择器拖垮整次提取。
    pub skipped_selectors: Vec<String>,
    pub trust: &'static str,
    pub source: &'static str,
    pub fetched_at: String,
}

#[derive(Clone, Debug, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
struct PageHtmlNode {
    selector: String,
    html: String,
}

#[derive(Clone, Debug, Default, serde::Deserialize)]
#[serde(rename_all = "camelCase", default)]
struct PageHtmlCounts {
    matched: u32,
    returned: u32,
    omitted: u32,
    chars: u32,
    truncated: bool,
}

#[derive(Clone, Debug, Default, serde::Deserialize)]
#[serde(rename_all = "camelCase", default)]
struct PageHtml {
    nodes: Vec<PageHtmlNode>,
    counts: PageHtmlCounts,
    page_text: String,
    skipped_selectors: Vec<String>,
}

/// 选择器上限：够一次性取回一页搜索结果的候选卡片 + 少量容器，再多就是调用方在滥用。
const MAX_HTML_SELECTORS: usize = 8;
const MAX_HTML_SELECTOR_CHARS: usize = 160;

#[tauri::command]
#[allow(clippy::too_many_arguments)]
pub async fn browser_html(
    app: AppHandle,
    webview: tauri::Webview,
    tab: String,
    selectors: Vec<String>,
    max_nodes: Option<u32>,
    per_node_chars: Option<u32>,
    max_chars: Option<u32>,
    page_text_chars: Option<u32>,
) -> Result<HtmlPayload, BrowserError> {
    url_policy::require_main(&webview)?;
    let mut cleaned: Vec<String> = Vec::new();
    for raw in selectors {
        let item = raw.trim();
        if item.is_empty() {
            continue;
        }
        if item.chars().count() > MAX_HTML_SELECTOR_CHARS {
            return Err(BrowserError::new(
                "invalid_argument",
                format!("选择器过长（上限 {MAX_HTML_SELECTOR_CHARS} 字）：{item}"),
                false,
            ));
        }
        if !cleaned.iter().any(|existing| existing == item) {
            cleaned.push(item.to_string());
        }
    }
    if cleaned.is_empty() {
        return Err(BrowserError::new("invalid_argument", "至少要给一个 CSS 选择器", false));
    }
    if cleaned.len() > MAX_HTML_SELECTORS {
        return Err(BrowserError::new(
            "invalid_argument",
            format!("选择器最多 {MAX_HTML_SELECTORS} 个，收到 {}", cleaned.len()),
            false,
        ));
    }
    // 页面桥单条消息上限 256 KB：这里的预算必须留出 JSON 转义与外壳的余量。
    let max_nodes = max_nodes.unwrap_or(20).clamp(1, 40);
    let per_node_chars = per_node_chars.unwrap_or(12_000).clamp(400, 40_000);
    let max_chars = max_chars.unwrap_or(100_000).clamp(2_000, 150_000);
    let page_text_chars = page_text_chars.unwrap_or(0).clamp(0, 8_000);
    let args = serde_json::json!({
        "selectors": cleaned,
        "maxNodes": max_nodes,
        "perNodeChars": per_node_chars,
        "maxChars": max_chars,
        "pageTextChars": page_text_chars,
    });
    // 与 snapshot 同一条经验：后台标签可能收不到指令，超时后临时显示重试一次。
    let mut call = page_call(&app, &tab, "html", args.clone(), bridge::DEFAULT_TIMEOUT).await;
    if let Err(error) = &call {
        if error.code == "timeout" {
            let temp = begin_agent_foreground(&app, &tab)?;
            let retry = page_call(&app, &tab, "html", args, bridge::DEFAULT_TIMEOUT).await;
            if let Some(temp) = temp {
                temp.restore();
            }
            if retry.is_ok() {
                call = retry;
            }
        }
    }
    let raw = call?;
    let page: PageHtml = serde_json::from_value(raw)
        .map_err(|error| BrowserError::new("internal", format!("页面片段格式不符合预期：{error}"), true))?;
    let (url, title, loading) = with_runtime(|rt| {
        let state = rt.tabs.get(&tab)?;
        Ok((state.url.clone(), state.title.clone(), state.loading))
    })?;
    Ok(HtmlPayload {
        tab,
        url,
        title,
        loading,
        nodes: page
            .nodes
            .into_iter()
            .map(|node| HtmlNodePayload { selector: node.selector, html: node.html })
            .collect(),
        counts: HtmlCountsPayload {
            matched: page.counts.matched,
            returned: page.counts.returned,
            omitted: page.counts.omitted,
            chars: page.counts.chars,
            truncated: page.counts.truncated,
        },
        page_text: page.page_text,
        skipped_selectors: page.skipped_selectors,
        trust: "untrusted",
        source: "web",
        fetched_at: now_iso(),
    })
}

/// user:“操作全部基于 ref，不接受即席脚本”+(写操作先过 human-owned 闸门，再按需要临时显示标签)。
#[tauri::command]
pub async fn browser_act(
    app: AppHandle,
    webview: tauri::Webview,
    tab: String,
    instruction: ActInstruction,
) -> Result<ActPayload, BrowserError> {
    url_policy::require_main(&webview)?;
    let op = instruction.canonical_op()?;
    instruction.validate()?;
    // user:“R9 危险动作审批”+(声明了 intent 就必须带 approved，模型自己声明不算通过)。
    if let Some(intent) = instruction.intent.as_deref() {
        if APPROVAL_INTENTS.contains(&intent) && instruction.approved != Some(true) {
            return Err(BrowserError::new(
                "needs_approval",
                format!("这条操作声明为 {intent}，属于高风险动作，需要用户确认后才能执行"),
                false,
            ));
        }
    }
    if WRITE_OPS.contains(&op) {
        require_agent_control(&tab)?;
    }
    // 页面回报的 stale 之前就先按台账挡一次：旧编号不可能摸到变化后的页面。
    if let Some(target) = instruction.target.as_deref() {
        let verdict = with_runtime(|rt| {
            let ledger = rt.refs.entry(tab.clone()).or_default();
            Ok(ledger.require(target).map(|_| ()))
        })?;
        verdict?;
    }
    let mut click_popups = if op == "click" {
        Some(ClickPopupCapture::begin(&app, &tab)?)
    } else {
        None
    };
    let temp = begin_agent_foreground(&app, &tab)?;
    let result = page_call(&app, &tab, "act", instruction.page_args(), bridge::DEFAULT_TIMEOUT).await;
    if let Some(temp) = temp {
        temp.restore();
    }
    let raw = match result {
        Ok(raw) => raw,
        Err(error) => {
            if error.code == "stale_ref" {
                if let Some(target) = instruction.target.as_deref() {
                    with_runtime(|rt| {
                        let ledger = rt.refs.entry(tab.clone()).or_default();
                        ledger.invalidate(target);
                        Ok(())
                    })?;
                }
                // user:“旧 ref 操作要返回 stale_ref，并自动重快照一次”+(只刷新编号，不重放写操作，
                // 避免「已经点下去了又点一次」的重复提交风险)。
                if let Err(refresh) = page_call(&app, &tab, "snapshot", serde_json::json!({}), bridge::DEFAULT_TIMEOUT).await {
                    return Err(BrowserError::new(
                        "stale_ref",
                        format!("{}；自动重快照也失败了（{}），请重新调用 browser_snapshot", error.message, refresh.message),
                        true,
                    ));
                }
                return Err(BrowserError::new(
                    "stale_ref",
                    format!("{}；已自动重新快照，请用新的 ref 重试", error.message),
                    true,
                ));
            }
            return Err(error);
        }
    };
    let mut opened_tabs = Vec::new();
    let mut popup_errors = Vec::new();
    if let Some(mut capture) = click_popups.take() {
        // WebView2 的 NewWindowRequested 可能晚于页面的 WebMessage 回执到达。
        // 给原生事件一个有上限的窗口，捕获期间界面仍可继续处理消息。
        let popups = tauri::async_runtime::spawn_blocking(move || {
            std::thread::sleep(std::time::Duration::from_millis(350));
            capture.take()
        })
        .await
        .map_err(|error| BrowserError::internal(format!("读取新标签请求失败：{error}")))?;
        for popup in popups {
            match open_act_popup(&app, &webview, &tab, &popup.url).await {
                Ok(opened) => opened_tabs.push(opened),
                Err(error) => popup_errors.push(error),
            }
        }
    }
    let owner = current_owner(&tab);
    Ok(build_act_payload(tab, op, &raw, owner, opened_tabs, popup_errors))
}

async fn open_act_popup(
    app: &AppHandle,
    webview: &tauri::Webview,
    source: &str,
    url: &str,
) -> Result<OpenedActTab, BrowserError> {
    let target = url_policy::parse_web(url)?;
    let profile = with_runtime(|rt| Ok(rt.tabs.get(source)?.profile.clone()))?;
    let opened = open_browser_tab(app, webview, target, Some(source.to_string()), profile).await?;
    let url = with_runtime(|rt| Ok(rt.tabs.get(&opened.tab)?.url.clone()))?;
    Ok(OpenedActTab { owner: current_owner(&opened.tab), tab: opened.tab, url })
}

fn build_act_payload(
    tab: String,
    op: &str,
    raw: &serde_json::Value,
    owner: String,
    opened_tabs: Vec<OpenedActTab>,
    popup_errors: Vec<BrowserError>,
) -> ActPayload {
    // user:“这是工具返回值和实际状态不同步”+(优先回报此次点击最终打开的原生标签，保留点击来源以便回看)。
    let (tab, url, owner, navigated, scroll, source_tab) = if let Some(opened) = opened_tabs.last() {
        (opened.tab.clone(), opened.url.clone(), opened.owner.clone(), true, None, Some(tab))
    } else {
        (
            tab,
            raw.get("url").and_then(serde_json::Value::as_str).unwrap_or_default().to_string(),
            owner,
            raw.get("navigated").and_then(serde_json::Value::as_bool).unwrap_or(false),
            raw.get("scroll").and_then(|value| serde_json::from_value(value.clone()).ok()),
            None,
        )
    };
    ActPayload {
        tab,
        op: op.to_string(),
        navigated,
        url,
        scroll,
        owner,
        resnapshot: false,
        trust: "untrusted",
        source: "web",
        fetched_at: now_iso(),
        source_tab,
        opened_tabs,
        popup_errors,
    }
}

/// user:“browser_waitFor 带超时与轮询上限；超时返回可读错误码”+(页面侧是事件驱动，
/// 宿主侧按前台真实时钟再兜一次超时，后台冻结不会让等待无限延长)。
#[tauri::command]
#[allow(clippy::too_many_arguments)]
pub async fn browser_wait_for(
    app: AppHandle,
    webview: tauri::Webview,
    tab: String,
    kind: String,
    value: Option<String>,
    state: Option<String>,
    timeout_ms: Option<u64>,
) -> Result<WaitPayload, BrowserError> {
    url_policy::require_main(&webview)?;
    let kind = match kind.as_str() {
        "selector" | "text" | "url" | "load" => kind.clone(),
        other => return Err(BrowserError::new("unsupported", format!("未知等待类型：{other}（只接受 selector/text/url/load）"), false)),
    };
    let state = match state.as_deref() {
        None | Some("present") => "present",
        Some("absent") => "absent",
        Some(other) => return Err(BrowserError::new("unsupported", format!("未知等待状态：{other}"), false)),
    };
    let value = value.unwrap_or_default();
    if kind != "load" && value.is_empty() {
        return Err(BrowserError::new("unsupported", "selector/text/url 等待必须给 value", false));
    }
    if value.chars().count() > 512 {
        return Err(BrowserError::new("unsupported", "等待值最多 512 个字符", false));
    }
    let timeout_ms = timeout_ms.unwrap_or(5000).clamp(200, 30000);
    let args = serde_json::json!({
        "kind": kind,
        "value": value,
        "state": state,
        "timeoutMs": timeout_ms,
    });
    let temp = begin_agent_foreground(&app, &tab)?;
    let call = page_call(
        &app,
        &tab,
        "waitFor",
        args,
        std::time::Duration::from_millis(timeout_ms) + std::time::Duration::from_millis(1500),
    )
    .await;
    if let Some(temp) = temp {
        temp.restore();
    }
    let raw = call?;
    let read_string = |key: &str| raw.get(key).and_then(serde_json::Value::as_str).unwrap_or_default().to_string();
    Ok(WaitPayload {
        tab: tab.clone(),
        satisfied: true,
        kind: read_string("kind"),
        value: read_string("value"),
        state: read_string("state"),
        elapsed_ms: raw.get("elapsedMs").and_then(serde_json::Value::as_u64).unwrap_or(0),
        url: read_string("url"),
        ready_state: read_string("readyState"),
        owner: current_owner(&tab),
        trust: "untrusted",
        source: "web",
        fetched_at: now_iso(),
    })
}

/// user:“browser_screenshot 用 CapturePreview 取视口，整页与 element 明确不支持”+
#[tauri::command]
pub async fn browser_screenshot(
    app: AppHandle,
    webview: tauri::Webview,
    tab: String,
    target: Option<String>,
) -> Result<ScreenshotPayload, BrowserError> {
    url_policy::require_main(&webview)?;
    with_runtime(|rt| rt.tabs.get(&tab).map(|_| ()))?;
    let target = target.unwrap_or_else(|| "viewport".to_string());
    if target != "viewport" {
        // user:“明确不支持整页与 element 级”+(不半成品：整页需要滚屏拼图或 CDP，元素裁剪会错位)。
        return Err(BrowserError::unsupported(format!(
            "截图只支持 target=viewport；{target} 需要滚屏拼图或 CDP，本阶段明确不做（改用 snapshot 的 refs/文本，或先滚动再截视口）"
        )));
    }
    // 隐藏的标签截出来是空白，所以先临时显示再截。
    let temp = begin_agent_foreground(&app, &tab)?;
    #[cfg(windows)]
    let capture = {
        let app_c = app.clone();
        let tab_c = tab.clone();
        tauri::async_runtime::spawn_blocking(move || {
            compositor::capture_viewport(&app_c, &tab_c, std::time::Duration::from_millis(4000))
        })
        .await
        .map_err(|error| BrowserError::internal(format!("截图任务失败：{error}")))?
    };
    #[cfg(not(windows))]
    let capture = {
        let view = view_for(&app, &tab)?;
        tauri::async_runtime::spawn_blocking(move || {
            platform_win::capture_viewport(&view, std::time::Duration::from_millis(4000))
        })
        .await
        .map_err(|error| BrowserError::internal(format!("截图任务失败：{error}")))?
    };
    if let Some(temp) = temp {
        temp.restore();
    }
    let bytes = capture?;
    let (width, height) = png_size(&bytes).ok_or_else(|| BrowserError::internal("截图不是合法的 PNG"))?;
    use base64::Engine as _;
    let encoded = base64::engine::general_purpose::STANDARD.encode(&bytes);
    Ok(ScreenshotPayload {
        tab,
        target,
        png: format!("data:image/png;base64,{encoded}"),
        width,
        height,
        note: format!("视口截图（{}×{}），物理像素；整页与元素级截图本阶段不支持", width, height),
        trust: "untrusted",
        source: "web",
        fetched_at: now_iso(),
    })
}

/// 读 PNG 头里的宽高（IHDR 固定在第 16..24 字节），失败返回 None。
fn png_size(bytes: &[u8]) -> Option<(u32, u32)> {
    const SIGNATURE: [u8; 8] = [0x89, b'P', b'N', b'G', 0x0d, 0x0a, 0x1a, 0x0a];
    if bytes.len() < 24 || bytes[..8] != SIGNATURE || &bytes[12..16] != b"IHDR" {
        return None;
    }
    let width = u32::from_be_bytes([bytes[16], bytes[17], bytes[18], bytes[19]]);
    let height = u32::from_be_bytes([bytes[20], bytes[21], bytes[22], bytes[23]]);
    Some((width, height))
}

/// user:“恢复需用户点「交回给 Agent」”+(action=status 只读当前归属；hand_to_agent 由前端按钮调用)。
#[tauri::command]
pub fn browser_control(
    app: AppHandle,
    webview: tauri::Webview,
    tab: String,
    action: String,
) -> Result<OwnershipPayload, BrowserError> {
    url_policy::require_main(&webview)?;
    let (owner, quiet) = with_runtime(|rt| {
        let state = rt.tabs.get_mut(&tab)?;
        match action.as_str() {
            "status" => {
                state.ownership.release_if_quiet(std::time::Instant::now());
            }
            "hand_to_agent" => {
                state.ownership.hand_to_agent();
            }
            other => {
                return Err(BrowserError::new("unsupported", format!("未知控制动作：{other}"), false));
            }
        }
        Ok((state.ownership.owner().label().to_string(), state.ownership.quiet().as_secs()))
    })?;
    emit_state(&app, &tab);
    Ok(OwnershipPayload { tab, owner, quiet_seconds: quiet })
}

/// user:“切换标签要先知道有哪些标签”+(Agent 用它在断线/重启后重新认领标签；只读命令)。
#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct TabEntry {
    pub tab: String,
    pub url: String,
    pub title: String,
    pub active: bool,
    pub owner: String,
    pub profile: String,
    pub loading: bool,
}

#[derive(Clone, Debug, Serialize)]
pub struct TabsPayload {
    pub tabs: Vec<TabEntry>,
}

#[cfg(test)]
mod click_popup_tests {
    use super::*;

    fn popup(tab: &str, url: &str) -> PendingTabPayload {
        PendingTabPayload {
            tab: tab.to_string(),
            url: url.to_string(),
            opener: Some(tab.to_string()),
            user_initiated: false,
        }
    }

    // user:“这是工具返回值和实际状态不同步”+(同一次点击只收录来源匹配的原生新窗口请求)。
    #[test]
    fn click_popup_capture_is_scoped_to_the_opener() {
        let mut runtime = BrowserRuntime::new();
        let source = runtime.tabs.open("https://example.com/search".into(), None).unwrap();
        let other = runtime.tabs.open("https://example.org/".into(), None).unwrap();
        runtime.click_popups.insert(source.clone(), Vec::new());

        assert!(!runtime.capture_click_popup(&popup(&other, "https://example.org/other")));
        assert!(runtime.capture_click_popup(&popup(&source, "https://example.com/video")));
        let captured = runtime.click_popups.remove(&source).unwrap();
        assert_eq!(captured.len(), 1);
        assert_eq!(captured[0].url, "https://example.com/video");
        assert!(!runtime.capture_click_popup(&popup(&source, "https://example.com/later")));
    }

    #[test]
    fn click_popup_result_points_to_the_opened_tab() {
        let raw = serde_json::json!({
            "url": "https://example.com/search",
            "navigated": false,
            "scroll": {"x": 0, "y": 20}
        });
        let same_tab = build_act_payload("t1".into(), "click", &raw, "agent".into(), vec![], vec![]);
        let same = serde_json::to_value(same_tab).unwrap();
        assert_eq!(same["tab"], "t1");
        assert_eq!(same["url"], "https://example.com/search");
        assert_eq!(same["navigated"], false);
        assert_eq!(same["scroll"]["y"].as_f64(), Some(20.0));
        assert!(same.get("openedTabs").is_none());

        let result = build_act_payload("t1".into(), "click", &raw, "agent".into(), vec![
            OpenedActTab { tab: "t2".into(), url: "https://example.com/video".into(), owner: "agent".into() },
        ], vec![]);
        let opened = serde_json::to_value(result).unwrap();
        assert_eq!(opened["sourceTab"], "t1");
        assert_eq!(opened["tab"], "t2");
        assert_eq!(opened["url"], "https://example.com/video");
        assert_eq!(opened["navigated"], true);
        assert_eq!(opened["openedTabs"][0]["tab"], "t2");
        assert!(opened["scroll"].is_null());
    }
}

#[tauri::command]
pub fn browser_tabs(webview: tauri::Webview) -> Result<TabsPayload, BrowserError> {
    url_policy::require_main(&webview)?;
    let tabs = with_runtime(|rt| {
        let mut out = Vec::new();
        for id in rt.tabs.ids() {
            let state = rt.tabs.get(&id)?;
            out.push(TabEntry {
                tab: id.clone(),
                url: state.url.clone(),
                title: state.title.clone(),
                active: rt.tabs.is_active(&id),
                owner: state.ownership.owner().label().to_string(),
                profile: state.profile.label(),
                loading: state.loading,
            });
        }
        Ok(out)
    })?;
    Ok(TabsPayload { tabs })
}

/// user:“一开网页整个界面就未响应”+(结构性回归守卫：直接扫本文件源码，不依赖窗口与运行时)。
///
/// 复核步骤：`browser_open` 若是同步命令，tauri 会在**主线程**执行它，而 `Window::add_child`
/// 内部是 `run_on_main_thread(...)` + `rx.recv()`；主线程等自己 → 死锁，表现为窗口
/// `Responding=False`、所有 IPC 超时、后端仍活着。改 async 后才能回到正常路径。
#[cfg(test)]
mod threading_assert {
    const SOURCE: &str = include_str!("mod.rs");

    /// 拼出「要找的字面量」而不是直接写在源码里：SOURCE 就是本文件，
    /// 直接写出调用名加括号会让测试把自己的断言文本扫进去（假红）。
    fn needle(prefix: &str, name: &str, suffix: &str) -> String {
        format!("{prefix}{name}{suffix}")
    }

    #[test]
    fn browser_open_must_stay_async() {
        let async_form = needle("pub ", "async fn browser_open(", "");
        let sync_form = needle("pub ", "fn browser_open(", "");
        assert!(
            SOURCE.contains(&async_form),
            "browser_open 必须是 async 命令：同步命令跑在主线程，add_child 会自己等自己"
        );
        assert!(
            !SOURCE.contains(&sync_form),
            "browser_open 不能退回同步命令（会把「一开网页界面就未响应」带回来）"
        );
    }

    #[test]
    fn only_browser_open_creates_child_webviews() {
        // add_child 是本模块唯一会阻塞主线程的调用；新增调用点前必须先确认调用方是 async 命令。
        let call = needle("webview::", "create", "(");
        assert_eq!(
            SOURCE.matches(&call).count(),
            1,
            "创建子 webview 只能由 browser_open（async）这一处发起"
        );
    }
}

/// user:“网页跑到分屏外面”+(坐标空间契约的单测：前端传 CSS px（= 逻辑像素），
/// Rust 交给 tauri 的 Logical* 再按窗口 scale_factor 换物理像素。150% 下必须是 1.5×，
/// 而且双向可逆——任何一侧自行乘 devicePixelRatio 都会让这组断言失败)。
#[cfg(test)]
mod bounds_scale_tests {
    use super::*;

    /// user:“网页盖住页眉/标题栏”+(落位原点必须是**客户区**：屏幕坐标换算只能减 `inner_position`。
    /// 带原生标题栏时 frame=(0,31)，若拿 `outer_position` 当基准，落点会整体上移 31px —— 正好盖住页眉)。
    #[test]
    fn placement_origin_is_client_area_not_outer_frame() {
        let outer = (100, 50);
        let inner = (100, 81); // 原生标题栏 31px
        let frame = client_origin_offset(inner, outer);
        assert_eq!(frame, (0, 31));

        // 期望落在客户区内的 (1104, 200)
        let client_point = (1104, 200);
        let screen_point = (inner.0 + client_point.0, inner.1 + client_point.1);

        // 正确：屏幕 → 客户区减 inner_position
        assert_eq!(screen_to_client(screen_point, inner), client_point);
        // 错误：减 outer_position 会把标题栏那 31px 一起算进落点（落点被顶到 y=231，
        // 与期望差一个 frame）——这正是「网页盖住页眉/标题栏」的机理。
        let wrong = screen_to_client(screen_point, outer);
        assert_eq!(wrong, (1104, 231));
        assert_eq!(wrong.1 - client_point.1, frame.1);
    }

    /// 本项目 `decorations:false`：frame≈0，两种基准结果相同 —— 所以**不能只靠这台机器验证**，
    /// 这条断言把「无边框时不暴露、带边框时差一个标题栏」的语义固定下来。
    #[test]
    fn borderless_window_hides_the_frame_offset() {
        assert_eq!(client_origin_offset((0, 0), (0, 0)), (0, 0));
        assert_eq!(screen_to_client((1104, 200), (0, 0)), (1104, 200));
    }

    #[test]
    fn logical_to_physical_at_150_percent() {
        let (x, y, w, h) = logical_to_physical(320.0, 210.0, 800.0, 600.0, 1.5);
        assert_eq!((x, y, w, h), (480.0, 315.0, 1200.0, 900.0));
    }

    #[test]
    fn physical_and_logical_roundtrip_at_150_percent() {
        let logical = (320.0, 210.0, 800.0, 600.0);
        let (px, py, pw, ph) = logical_to_physical(logical.0, logical.1, logical.2, logical.3, 1.5);
        let back = physical_to_logical(px, py, pw, ph, 1.5);
        assert!((back.0 - logical.0).abs() < 1e-9);
        assert!((back.1 - logical.1).abs() < 1e-9);
        assert!((back.2 - logical.2).abs() < 1e-9);
        assert!((back.3 - logical.3).abs() < 1e-9);
    }

    #[test]
    fn scale_one_is_identity_and_bad_scale_is_guarded() {
        assert_eq!(logical_to_physical(1.0, 2.0, 3.0, 4.0, 1.0), (1.0, 2.0, 3.0, 4.0));
        assert_eq!(physical_to_logical(1.0, 2.0, 3.0, 4.0, 0.0), (1.0, 2.0, 3.0, 4.0));
        assert_eq!(physical_to_logical(1.0, 2.0, 3.0, 4.0, -1.5), (1.0, 2.0, 3.0, 4.0));
    }

    /// user:“网页跑到分屏外面”+(实测回归：宿主 CSS 矩形 597,108 371x495、dpr=1.85，
    /// 物理落点必须是 1104,200 686x916。旧实现按窗口 scale=1.25 换算成 746,135 464x619，
    /// 两者差 1.48 倍——这条断言就是那个 bug 的守卫)。
    #[test]
    fn measured_host_rect_scales_by_dpr_not_by_window_scale() {
        let (x, y, w, h) = logical_to_physical(597.0, 108.0, 371.0, 495.0, 1.85);
        assert_eq!((x.round(), y.round(), w.round(), h.round()), (1104.0, 200.0, 686.0, 916.0));
        // 旧的错误换算（按窗口 scale=1.25）必须明显不同，防止有人把系数换回去。
        let (wx, wy, _, _) = logical_to_physical(597.0, 108.0, 371.0, 495.0, 1.25);
        assert!((wx - x).abs() > 300.0, "按窗口 scale 换算会偏出 300px 以上");
        assert!((wy - y).abs() > 50.0, "按窗口 scale 换算会纵向偏出 50px 以上");
    }
}

#[cfg(test)]
mod agent_tests {
    use super::*;

    fn instruction(op: &str, target: Option<&str>) -> ActInstruction {
        ActInstruction {
            op: op.to_string(),
            target: target.map(str::to_string),
            selector: None,
            form_value: None,
            text: None,
            clear: None,
            submit: None,
            value: None,
            key: None,
            dx: None,
            dy: None,
            intent: None,
            approved: None,
        }
    }

    #[test]
    fn act_instructions_reject_improvised_scripts() {
        let mut run_script = instruction("evaluate", None);
        run_script.text = Some("document.body.innerHTML = ''".into());
        assert_eq!(run_script.canonical_op().unwrap_err().code, "unsupported");

        // 需要 ref 的操作没给 ref：明确报 invalid_ref，而不是偷偷用坐标。
        assert_eq!(instruction("click", None).validate().unwrap_err().code, "invalid_ref");
        assert!(instruction("click", Some("e3")).validate().is_ok());

        // type 的 ref 可选，但文本超长要拒绝。
        let mut typing = instruction("type", None);
        typing.text = Some("x".repeat(4001));
        assert_eq!(typing.validate().unwrap_err().code, "unsupported");

        let mut selecting = instruction("select", Some("e4"));
        assert_eq!(selecting.validate().unwrap_err().code, "unsupported");
        selecting.value = Some("北京".into());
        assert!(selecting.validate().is_ok());

        assert_eq!(instruction("pressKey", None).validate().unwrap_err().code, "unsupported");
        let mut key = instruction("pressKey", None);
        key.key = Some("Enter".into());
        assert!(key.validate().is_ok());

        assert_eq!(instruction("scroll", None).validate().unwrap_err().code, "unsupported");
        let mut scroll = instruction("scroll", None);
        scroll.dy = Some(400.0);
        assert!(scroll.validate().is_ok());
        scroll.dy = Some(500_000.0);
        assert_eq!(scroll.validate().unwrap_err().code, "unsupported");
    }

    #[test]
    fn act_payload_only_forwards_whitelisted_fields() {
        let mut typing = instruction("type", Some("e7"));
        typing.text = Some("hello".into());
        typing.clear = Some(true);
        typing.submit = Some(true);
        // intent/approved 是宿主侧概念，不能出现在发给页面的载荷里。
        typing.intent = Some("delete".into());
        let args = typing.page_args();
        let object = args.as_object().expect("必须是对象");
        for key in object.keys() {
            assert!(
                matches!(key.as_str(), "op" | "ref" | "text" | "clear" | "submit" | "value" | "key" | "dx" | "dy"),
                "不允许把 {key} 发给页面"
            );
        }
        assert_eq!(object.get("op").and_then(|value| value.as_str()), Some("type"));
        assert_eq!(object.get("ref").and_then(|value| value.as_str()), Some("e7"));
    }

    #[test]
    fn write_ops_are_the_documented_set() {
        for op in ["click", "type", "clear", "hover", "select", "scroll", "pressKey"] {
            assert!(WRITE_OPS.contains(&op), "{op} 必须按写操作处理");
        }
        assert!(!WRITE_OPS.contains(&"snapshot"));
        for intent in ["payment", "delete", "publish", "auth"] {
            assert!(APPROVAL_INTENTS.contains(&intent));
        }
    }

    #[test]
    fn png_size_reads_header() {
        let mut header = vec![0x89, b'P', b'N', b'G', 0x0d, 0x0a, 0x1a, 0x0a];
        header.extend_from_slice(&[0, 0, 0, 13]);
        header.extend_from_slice(b"IHDR");
        header.extend_from_slice(&1280u32.to_be_bytes());
        header.extend_from_slice(&720u32.to_be_bytes());
        header.extend_from_slice(&[8, 6, 0, 0, 0]);
        assert_eq!(png_size(&header), Some((1280, 720)));
        assert_eq!(png_size(&header[..10]), None);
        assert_eq!(png_size(b"not a png at all, definitely not"), None);
    }

    #[test]
    fn snapshot_parsing_ignores_page_reported_navigation_state() {
        // 页面回报的 url/title 不参与判定：反序列化结构里没有这两个字段，注入它们也不会污染宿主状态。
        let raw = serde_json::json!({
            "url": "https://evil.example/",
            "title": "伪造标题",
            "loading": false,
            "viewport": { "w": 800, "h": 600 },
            "scroll": { "x": 0, "y": 120 },
            "refs": [{ "ref": "e1", "role": "link", "name": "首页", "value": null, "bounds": {"x":1,"y":2,"w":3,"h":4}, "states": ["onscreen"] }],
            "text": { "blocks": [{ "level": 1, "text": "标题" }], "truncated": true },
            "counts": { "total": 9, "returned": 1, "omitted": 8 },
            "stale": ["e2"]
        });
        let page: PageSnapshot = serde_json::from_value(raw).expect("结构必须能反序列化");
        assert_eq!(page.refs.len(), 1);
        assert_eq!(page.refs[0].r#ref, "e1");
        assert!(page.text.truncated);
        assert_eq!(page.counts.omitted, 8);
        assert_eq!(page.stale, vec!["e2".to_string()]);
        assert_eq!(page.viewport.w, 800.0);
    }
}

