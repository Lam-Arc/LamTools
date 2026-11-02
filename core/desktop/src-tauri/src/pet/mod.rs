//! Sunday 桌宠（桌宠 V1.0）桌面覆盖层与系统能力。
//!
//! user:“你现在负责在现有 Sunday 项目中实现「Sunday 桌宠 V1.0」”+
//! (桌宠必须能脱离 Agent 独立运行，所以桌面渲染、点击穿透、真实窗口遮挡、
//!  鼠标所在显示器截图、全局 Ping 快捷键这些系统能力放在 Rust 侧实现，
//!  动画/物理/寻路等业务逻辑放在前端引擎里。)
//!
//! 设计边界：
//! - 这里只提供"系统能力"，不包含角色行为，也不发起任何 Agent 请求。
//! - 覆盖层窗口是**一个**横跨虚拟桌面的透明窗口；是否接收鼠标由命中矩形集合
//!   决定（`pet_set_interactive_rects`），因此只有角色/气泡/卡片区域吃点击，
//!   其余位置鼠标穿透到桌面。
//! - 覆盖层**不做**屏幕捕获隐身：全屏覆盖层一旦被排除出捕获，任何抓屏式观看
//!   （远程桌面、录屏、屏幕共享）里就是一整块纯黑，用户会以为程序卡死。
//!   Ping 需要干净底图时，改为截图前把覆盖层隐藏 120ms 再抓。
//! - 角色包（`.sundaypet` / 文件夹）安装走白名单 + 大小/数量上限 + 路径穿越校验，
//!   普通资源包不能执行任何脚本。

mod platform;
pub mod cards;

use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use serde::Serialize;
use tauri::{AppHandle, Emitter, Manager, PhysicalPosition, PhysicalSize, WebviewUrl, WebviewWindowBuilder};

pub const OVERLAY_LABEL: &str = "pet-overlay";
/// Ping 独立覆盖层窗口：环/标记/标注/会话选择器，与桌宠覆盖层解耦。
pub const PING_OVERLAY_LABEL: &str = "ping-overlay";
/// 命中矩形、光标、快捷键轮询周期。8ms 让环显形/抓取的边界判定足够跟手，
/// 同时不改变其他窗口的输入（只有状态变化时才改窗口属性）。
const POLL_INTERVAL: Duration = Duration::from_millis(8);

#[derive(Default)]
pub struct PetState {
    /// 物理像素屏幕坐标的命中矩形 [x, y, w, h]。
    interactive: Mutex<Vec<[f64; 4]>>,
    /// auto | capture | passthrough
    input_mode: Mutex<String>,
    /// top | behind
    z_mode: Mutex<String>,
    hotkey: Mutex<Option<platform::HotkeySpec>>,
    import_root: Mutex<Option<PathBuf>>,
    poll_running: AtomicBool,
    cursor_inside: AtomicBool,
    /// 覆盖层页面最后一次和宿主说话的时间（心跳/命中矩形上报）。
    /// user:“从你启动开始就一直是黑屏未响应状态”+(页面死了必须能被发现，
    /// 否则一块没人画的透明窗口会一直盖在桌面上。)
    frontend_seen: Mutex<Option<Instant>>,
    /// 最近一次真正设到窗口上的穿透状态：失败下一轮重试，避免状态错位后
    /// 覆盖层永久吃掉整屏鼠标。
    click_through_applied: AtomicBool,
    /// 页面是否至少报过一次心跳：没报过说明还在启动，宽限期按“首次加载”算；
    /// 超过加载宽限仍没动静，就认定页面打不开，直接销毁窗口。
    ever_seen: AtomicBool,
    /// Ping 独立覆盖层（环/标记/标注/会话选择器）的命中矩形与穿透状态。
    /// user:“卡片即窗口，把 ping 和桌宠拆分开”+(Ping 有自己的覆盖层窗口，
    /// 命中判定不能和桌宠窗口共用一套。)
    ping_interactive: Mutex<Vec<[f64; 4]>>,
    ping_input_mode: Mutex<String>,
    ping_click_through_applied: AtomicBool,
    /// 进入 capture（整屏吃鼠标）的时间。
    capture_since: Mutex<Option<Instant>>,
    ping_capture_since: Mutex<Option<Instant>>,
}

/// capture 模式最长占用时间：超过就强制恢复穿透。
///
/// user:"那个'强制置顶'，你一定要给我记着。如果它一旦发生错误，把它退出置顶
/// 或者直接关闭。不然的话，就会出现无法访问，但是直接把我的屏幕全给占掉"+
/// (拖拽/菜单正常只用几秒 capture；页面卡死没来得及复位时，这个上限保证
///  最多 8 秒后把鼠标还给桌面，而不是永久占屏。)
const CAPTURE_HOLD_LIMIT: Duration = Duration::from_secs(8);

fn capture_timed_out(since: Option<Instant>) -> bool {
    since.map(|at| at.elapsed() >= CAPTURE_HOLD_LIMIT).unwrap_or(false)
}

#[derive(Serialize, Clone, Debug)]
pub struct OverlayBounds {
    pub x: i32,
    pub y: i32,
    pub width: i32,
    pub height: i32,
    pub scale: f64,
}

#[derive(Serialize, Clone, Debug)]
pub struct MonitorInfo {
    pub id: String,
    pub x: i32,
    pub y: i32,
    pub width: i32,
    pub height: i32,
    pub primary: bool,
    pub scale: f64,
}

#[derive(Serialize, Clone, Debug)]
pub struct CursorReport {
    pub x: i32,
    pub y: i32,
    pub monitor: Option<MonitorInfo>,
}

#[derive(Serialize, Clone, Debug)]
pub struct CursorEvent {
    pub x: i32,
    pub y: i32,
    pub inside: bool,
}

#[derive(Serialize, Clone, Debug)]
pub struct HotkeyEvent {
    pub phase: String,
    pub x: i32,
    pub y: i32,
    pub accelerator: String,
}

#[derive(Serialize, Clone, Debug)]
pub struct ImportScan {
    pub root: String,
    pub files: Vec<ImportFile>,
    pub total_bytes: u64,
}

#[derive(Serialize, Clone, Debug)]
pub struct ImportFile {
    pub rel: String,
    pub size: u64,
    pub ext: String,
}

#[derive(Serialize, Clone, Debug)]
pub struct InstalledPack {
    pub id: String,
    pub dir: String,
    pub files: usize,
    pub bytes: u64,
}

// ---------------------------------------------------------------------------
// 覆盖层窗口
// ---------------------------------------------------------------------------

fn overlay_url() -> WebviewUrl {
    // 排查开关：用主页面地址建窗，判断"窗口建不起来"还是"pet.html 取不到"。
    if std::env::var("SUNDAY_PET_URL_ROOT").map(|value| value == "1").unwrap_or(false) {
        return WebviewUrl::App("index.html".into());
    }
    // 诊断模式：页面带 diag 参数，HUD 自动展开（PetStage 读这个参数）。
    if diag_mode() {
        return WebviewUrl::App("pet.html?diag=1".into());
    }
    // dev 与打包都由 Tauri 自己把 App 路径解析到 devUrl / frontendDist，
    // 因此这里不需要判断调试模式。
    WebviewUrl::App("pet.html".into())
}

fn virtual_screen_bounds() -> Result<OverlayBounds, String> {
    #[cfg(windows)]
    {
        platform::virtual_screen_bounds()
    }
    #[cfg(not(windows))]
    {
        Err("desktop pet overlay is only implemented on Windows".into())
    }
}

/// 诊断模式：覆盖层变成一个普通小窗口（不置顶、不穿透、可截屏、自带 HUD），
/// 用于用截图验证"方块人到底渲染出来没有"。
/// user:"你先不用让桌宠窗口置顶，就在任何位置，你要能截一次图，能截到那个方块人出现"+
/// (验收必须落到截图证据上；全屏置顶+穿透的覆盖层既不方便截图也不方便定位渲染问题。)
fn diag_mode() -> bool {
    std::env::var("SUNDAY_PET_DIAG").map(|value| value == "1").unwrap_or(false)
}

fn diag_bounds() -> OverlayBounds {
    OverlayBounds { x: 140, y: 110, width: 960, height: 640, scale: 1.0 }
}

fn open_overlay_window(app: &AppHandle) -> Result<OverlayBounds, String> {
    let bounds = if diag_mode() { diag_bounds() } else { virtual_screen_bounds()? };
    let state = app.state::<PetState>();
    // 诊断：把进程里所有窗口的真实状态打出来，判断"拿不到窗口 API 响应"
    // 是这个窗口独有的，还是所有窗口都一样。
    for (label, handle) in app.webview_windows() {
        eprintln!(
            "[pet] diag window {label}: size={:?} url={:?} visible={:?}",
            handle.inner_size(),
            handle.url().map(|value| value.to_string()),
            handle.is_visible()
        );
    }
    if let Some(window) = app.get_webview_window(OVERLAY_LABEL) {
        // user:“未响应”+“黑屏”+
        // (注册表里的窗口可能是个半成品——事件循环还没起来时就建了，所有窗口 API
        //  都收不到响应、也永远不会加载网页。它会一直挡着后面正常的建窗，
        //  所以必须先销毁再重建，绝不能直接复用。)
        // user:“点击打开桌宠没反应”+(页面超过宽限期没报心跳同样不可信：直接销毁
        //  重建，让页面重新 boot；页面还活着时才走复用路径。)
        let page_alive = page_alive(&state);
        if page_alive && window.inner_size().is_ok() {
            place_overlay(&window, &bounds)?;
            if diag_mode() {
                // 诊断窗口就是普通窗口：不置顶、不吃穿透设置。
                let _ = window.set_always_on_top(false);
                let _ = window.set_ignore_cursor_events(false);
                state.click_through_applied.store(false, Ordering::SeqCst);
            }
            // user:“点击打开桌宠没反应”+(托盘点「打开桌宠」的意图是"让我看见它"：
            //  窗口被收起过就直接 show；角色被「显隐」藏起来过，广播事件让页面恢复
            //  显示，而不是让点击变成空操作。)
            if !window.is_visible().unwrap_or(true) {
                let _ = window.show();
            }
            let _ = app.emit("pet://overlay/opened", ());
            start_polling(&app);
            return Ok(bounds);
        }
        if !page_alive {
            eprintln!("[pet] overlay page never became reachable; rebuilding it");
        } else {
            eprintln!("[pet] discarding half-created overlay window and rebuilding it");
        }
        let _ = window.destroy();
        std::thread::sleep(Duration::from_millis(120));
    }
    // 排查开关：逐项关掉样式，定位哪个设置让 WebView2 建不出网页。
    let flag = |name: &str| std::env::var(name).map(|value| value == "1").unwrap_or(false);
    // user:"你给我兜好底，一旦遇到无法访问页面的时候，立刻把这个窗口关掉"+
    // (页面崩溃被看门狗销毁后，用户还会从托盘重新打开。WebView2 在刚销毁一个
    //  覆盖层窗口时偶尔会建出"消息通道还没就绪"的半成品窗口，place_overlay 会
    //  报 failed to receive message from webview。这里有限重试：失败就销毁，
    //  隔一小会儿再建，避免一次抖动就让桌宠再也打不开。)
    let mut last_error = String::from("pet overlay window build did not run");
    for attempt in 0..3 {
        if attempt > 0 {
            std::thread::sleep(Duration::from_millis(350 * attempt as u64));
            eprintln!("[pet] retrying overlay window build (attempt {})", attempt + 1);
        }
        let mut builder = WebviewWindowBuilder::new(app, OVERLAY_LABEL, overlay_url())
            .title("Sunday Pet")
            .decorations(false)
            .resizable(false)
            .maximizable(false)
            .minimizable(false)
            .closable(false)
            .focused(false)
            .visible(false);
        if !flag("SUNDAY_PET_NO_TRANSPARENT") {
            builder = builder.transparent(true);
        }
        if !flag("SUNDAY_PET_NO_BACKGROUND") {
            builder = builder.background_color(tauri::window::Color(0, 0, 0, 0));
        }
        if !flag("SUNDAY_PET_NO_SHADOW") {
            builder = builder.shadow(false);
        }
        if !flag("SUNDAY_PET_KEEP_TASKBAR") {
            builder = builder.skip_taskbar(true);
        }
        // 覆盖层必须和主窗口用同一份浏览器参数：同一个数据目录下，不同参数的
        // WebView2 环境不能共存（见 browser_args 的说明）。
        builder = builder.additional_browser_args(&browser_args_from_env());
        // 排查用调试端口走进程级环境变量 WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS，
        // 不在单个窗口上追加浏览器参数：那样会让 WebView2 建窗变慢并让
        // 窗口句柄取不到（报 "the underlying handle is not available"）。
        // user:“从你启动开始就一直是黑屏未响应状态”+
        // (窗口**先不显示**：页面画出第一帧后自己调 `pet_overlay_ready` 再显示。
        //  新建的全屏窗口在页面没跑起来之前只会是一块黑，绝不能让它盖住桌面。)
        // user:"你给我兜好底，一旦遇到无法访问页面的时候，立刻把这个窗口关掉"+
        // (这里只记"窗口刚建好"的时间，不算页面已就绪：页面从没报过心跳时，
        //  看门狗按首次加载宽限期判死，超时直接销毁窗口，而不是让坏页面一直挂着。)
        // 必须在 build() 之前标记：窗口一注册就会进入轮询线程的视野，若还带着
        // 上一个页面的旧时间戳，看门狗会在 place_overlay 等待响应时把新窗口销毁。
        mark_page_created(app);
        let window = match builder.build() {
            Ok(window) => window,
            Err(error) => {
                last_error = format!("create pet overlay window failed: {error}");
                continue;
            }
        };
        // 建完立刻验证它是不是真窗口：半成品所有 API 都失败，也永远不会有网页，
        // 直接销毁并重试，绝不能把它留在窗口表里。
        if window.inner_size().is_err() {
            eprintln!("[pet] overlay window came back half-created; destroying it and retrying");
            let _ = window.destroy();
            last_error = "overlay window was created before the app loop was ready".into();
            continue;
        }
        if let Err(error) = place_overlay(&window, &bounds) {
            eprintln!("[pet] place overlay failed: {error}; destroying it and retrying");
            let _ = window.destroy();
            last_error = format!("place overlay: {error}");
            continue;
        }
        eprintln!(
            "[pet] overlay placed size={:?} pos={:?} visible={:?}",
            window.inner_size(),
            window.outer_position(),
            window.is_visible()
        );
        // 先按穿透启动：前端算出命中矩形之前，覆盖层绝不能挡住桌面。
        // 诊断模式相反：普通窗口，可点可截。
        if diag_mode() {
            let _ = window.set_always_on_top(false);
            let _ = window.set_ignore_cursor_events(false);
            state.click_through_applied.store(false, Ordering::SeqCst);
        } else {
            let _ = window.set_ignore_cursor_events(true);
            #[cfg(windows)]
            if let Err(error) = platform::configure_overlay_window(&window) {
                // 不抢焦点/不进 Alt+Tab 是锦上添花，取不到句柄不该让桌宠打不开。
                eprintln!("[pet] overlay window styling skipped: {error}");
            }
        }
        // 排查开关：验证"隐藏窗口是否根本不建网页"。设 SUNDAY_PET_SHOW_ON_OPEN=1 时
        // 建完立刻显示，和旧行为一致。
        if std::env::var("SUNDAY_PET_SHOW_ON_OPEN").map(|value| value == "1").unwrap_or(false) {
            let _ = window.show();
        }
        return Ok(bounds);
    }
    Err(last_error)
}

/// 建立（或复用）Ping 独立覆盖层窗口：全屏透明、置顶、默认穿透。
///
/// user:“你看看 ping 环 要不也自己做窗口？”+(Ping 的环/标记/标注/会话选择器
/// 有了自己的全屏窗口，桌宠关掉或禁用都不影响 Ping 入口。窗口先隐藏，
/// 页面首次就绪或需要显示环时再 show。)
pub fn ensure_ping_overlay(app: &AppHandle) -> Result<OverlayBounds, String> {
    let bounds = virtual_screen_bounds()?;
    let state = app.state::<PetState>();
    if let Some(window) = app.get_webview_window(PING_OVERLAY_LABEL) {
        if window.inner_size().is_ok() {
            place_overlay(&window, &bounds)?;
            // Ping 的全局快捷键与光标事件都由轮询线程产生；桌宠禁用时页面不会
            // 调 pet_overlay_open，这里必须自己保证轮询已启动。
            start_polling(app);
            return Ok(bounds);
        }
        eprintln!("[pet] discarding half-created ping overlay window and rebuilding it");
        let _ = window.destroy();
        std::thread::sleep(Duration::from_millis(120));
    }
    let builder = WebviewWindowBuilder::new(app, PING_OVERLAY_LABEL, WebviewUrl::App("ping.html".into()))
        .title("Sunday Ping")
        .decorations(false)
        .resizable(false)
        .maximizable(false)
        .minimizable(false)
        .closable(false)
        .focused(false)
        .visible(false)
        .transparent(true)
        .background_color(tauri::window::Color(0, 0, 0, 0))
        .shadow(false)
        .skip_taskbar(true)
        .additional_browser_args(&browser_args_from_env());
    let window = builder
        .build()
        .map_err(|error| format!("create ping overlay window failed: {error}"))?;
    if window.inner_size().is_err() {
        eprintln!("[pet] ping overlay window came back half-created; destroying it and asking for a retry");
        let _ = window.destroy();
        return Err("ping overlay window was created before the app loop was ready".into());
    }
    place_overlay(&window, &bounds)?;
    let _ = window.set_always_on_top(true);
    let _ = window.set_ignore_cursor_events(true);
    state.ping_click_through_applied.store(true, Ordering::SeqCst);
    #[cfg(windows)]
    if let Err(error) = platform::configure_overlay_window(&window) {
        eprintln!("[pet] ping overlay window styling skipped: {error}");
    }
    // user:“窗口没有出现”+(隐藏窗口里的 WebView2 会被浏览器节流：页面加载、
    // 热键注册能拖到一分钟，用户一启动就按快捷键等于没反应。Ping 覆盖层是
    // 全屏透明 + 鼠标穿透，直接常显对桌面没有任何视觉/交互影响，页面保持活跃。)
    let _ = window.show();
    start_polling(app);
    eprintln!("[pet] ping overlay window ready (always visible, click-through)");
    Ok(bounds)
}

/// 把覆盖层摆成"正好覆盖整个虚拟桌面"。///
/// user:“启动就是黑屏”+(某些系统缩放下，窗口 API 会把物理像素当逻辑像素再乘一次
/// 缩放，2048×1152 的屏幕会被摆成 2560×1440，桌宠于是落到屏幕外面。这里改成
/// 设置后读回真实尺寸，按比例修正，直到和屏幕一致。)
fn place_overlay(window: &tauri::WebviewWindow, bounds: &OverlayBounds) -> Result<(), String> {
    let target_w = bounds.width.max(1) as f64;
    let target_h = bounds.height.max(1) as f64;
    let mut want_w = target_w;
    let mut want_h = target_h;
    let mut want_x = bounds.x as f64;
    let mut want_y = bounds.y as f64;
    for _ in 0..4 {
        window
            .set_position(PhysicalPosition::new(want_x.round() as i32, want_y.round() as i32))
            .map_err(|error| format!("position pet overlay failed: {error}"))?;
        window
            .set_size(PhysicalSize::new(
                want_w.round().max(1.0) as u32,
                want_h.round().max(1.0) as u32,
            ))
            .map_err(|error| format!("resize pet overlay failed: {error}"))?;
        let size = window.inner_size().map_err(|error| error.to_string())?;
        let position = window.outer_position().map_err(|error| error.to_string())?;
        let size_ok = (size.width as f64 - target_w).abs() < 1.5
            && (size.height as f64 - target_h).abs() < 1.5;
        let position_ok = position.x == bounds.x && position.y == bounds.y;
        if size_ok && position_ok {
            return Ok(());
        }
        // 用"实际 / 请求"估出系统额外乘的缩放比例，把修正量换算回去。
        let scale_x = if want_w > 0.0 { size.width as f64 / want_w } else { 1.0 };
        let scale_y = if want_h > 0.0 { size.height as f64 / want_h } else { 1.0 };
        if size.width > 0 && size.height > 0 {
            want_w = want_w * target_w / size.width as f64;
            want_h = want_h * target_h / size.height as f64;
        }
        let scale_x = if scale_x > 0.01 { scale_x } else { 1.0 };
        let scale_y = if scale_y > 0.01 { scale_y } else { 1.0 };
        want_x += (bounds.x - position.x) as f64 / scale_x;
        want_y += (bounds.y - position.y) as f64 / scale_y;
    }
    Err("pet overlay did not reach the target bounds".into())
}

/// 新窗口刚建好：只记录时间，不算页面已就绪。
fn mark_page_created(app: &AppHandle) {
    let state = app.state::<PetState>();
    state.ever_seen.store(false, Ordering::SeqCst);
    let lock_result = state.frontend_seen.lock();
    if let Ok(mut slot) = lock_result {
        *slot = Some(Instant::now());
    }
}

/// 记录"覆盖层页面还活着"：心跳和命中矩形上报都算。
fn mark_frontend_seen(app: &AppHandle) {
    let state = app.state::<PetState>();
    state.ever_seen.store(true, Ordering::SeqCst);
    let lock_result = state.frontend_seen.lock();
    if let Ok(mut slot) = lock_result {
        *slot = Some(Instant::now());
    }
}

/// 页面是否可信：报过心跳的 6 秒判死（心跳每 2 秒一次，连丢三拍）；
/// 还在启动的（从没报过）给 12 秒加载宽限，超过就认为页面根本打不开。
///
/// user:"你给我兜好底，一旦遇到无法访问页面的时候，立刻把这个窗口关掉"+
/// (页面不可访问时不能只隐藏或一直等：宽限期一到就销毁窗口，绝不留盖屏窗口。)
fn page_alive(state: &PetState) -> bool {
    let grace = if state.ever_seen.load(Ordering::SeqCst) { 6 } else { 12 };
    state
        .frontend_seen
        .lock()
        .ok()
        .and_then(|slot| *slot)
        .map(|at| at.elapsed() < Duration::from_secs(grace))
        .unwrap_or(false)
}

fn stop_polling(state: &PetState) {
    state.poll_running.store(false, Ordering::SeqCst);
}

fn start_polling(app: &AppHandle) {
    let state = app.state::<PetState>();
    if state.loop_running_swap(true) {
        return;
    }
    eprintln!("[pet] poll loop starting");
    let handle = app.clone();
    std::thread::Builder::new()
        .name("pet-overlay-poll".into())
        .spawn(move || poll_loop(handle))
        .ok();
}

impl PetState {
    /// 返回"之前是否已经在跑"，保证只有一个轮询线程。
    fn loop_running_swap(&self, value: bool) -> bool {
        self.poll_running.swap(value, Ordering::SeqCst) == value
    }
}

/// panic 兜底：关闭桌宠/Ping 覆盖层窗口，避免置顶窗口卡在桌面上。
pub fn emergency_close_overlays() {
    platform::close_overlay_windows();
}

#[derive(Clone, Copy, Debug)]
enum PointerTarget {
    Pet,
    Ping,
}

/// 按命中矩形/输入模式决定并应用某个覆盖层窗口是否吃鼠标，返回"鼠标是否在有效区内"。
fn apply_pointer_mode(
    state: &PetState,
    window: &tauri::WebviewWindow,
    target: PointerTarget,
    cx: i32,
    cy: i32,
) -> bool {
    let (mode_slot, rects_slot, applied) = match target {
        PointerTarget::Pet => (&state.input_mode, &state.interactive, &state.click_through_applied),
        PointerTarget::Ping => (&state.ping_input_mode, &state.ping_interactive, &state.ping_click_through_applied),
    };
    let mode = mode_slot
        .lock()
        .map(|value| value.clone())
        .unwrap_or_else(|_| "auto".to_string());
    // user:"现在全穿透了"+(矩形边缘没有容差，鼠标 1-2px 的手抖就让状态在
    // 接住/穿透之间翻转，点击正好落在穿透瞬间。迟滞方向：进入按原矩形，
    // 离开要超出 28px 才切回穿透——抓角色、点菜单边缘不再漏。)
    let inside = match mode.as_str() {
        "capture" => true,
        "passthrough" => false,
        _ => {
            let was_ignoring = applied.load(Ordering::SeqCst);
            let pad = if was_ignoring { 0.0 } else { 28.0 };
            rects_slot
                .lock()
                .map(|rects| rects.iter().any(|rect| point_in_rect_padded(cx, cy, rect, pad)))
                .unwrap_or(false)
        }
    };
    if matches!(target, PointerTarget::Pet) {
        state.cursor_inside.store(inside, Ordering::SeqCst);
    }
    let ignoring = !inside;
    // 只在"想要的"和"已经设上的"不一致时才动窗口属性：高频调用会让系统堆叠
    // 窗口样式消息。状态错位（上次调用没生效）下一轮会自己补上，
    // 不会出现覆盖层永久吃住整屏鼠标的情况。
    // 诊断模式下窗口保持可点、可截屏，不做穿透切换。
    if !diag_mode() && applied.load(Ordering::SeqCst) != ignoring {
        eprintln!(
            "[pet] click-through({target:?}) -> {ignoring} at cursor ({cx},{cy})"
        );
        match window.set_ignore_cursor_events(ignoring) {
            Ok(()) => applied.store(ignoring, Ordering::SeqCst),
            Err(error) => {
                eprintln!("[pet] set_ignore_cursor_events({ignoring}) failed: {error}")
            }
        }
    }
    inside
}

fn poll_loop(app: AppHandle) {
    let state = app.state::<PetState>();
    let mut last_cursor: Option<(i32, i32, bool)> = None;
    let mut hotkey_down = false;
    while state.poll_running.load(Ordering::SeqCst) {
        let pet_window = app.get_webview_window(OVERLAY_LABEL);
        let ping_window = app.get_webview_window(PING_OVERLAY_LABEL);
        if pet_window.is_none() && ping_window.is_none() {
            state.poll_running.store(false, Ordering::SeqCst);
            break;
        }
        let (cx, cy) = platform::cursor_position().unwrap_or((-1, -1));
        // capture 兜底：页面卡死没复位时最多占 8 秒，之后强制穿透并清空命中区，
        // 把鼠标还给桌面。（正常拖拽/菜单只占几秒。）
        if capture_timed_out(state.capture_since.lock().ok().and_then(|slot| *slot)) {
            if let Ok(mut mode) = state.input_mode.lock() {
                *mode = "auto".to_string();
            }
            if let Ok(mut since) = state.capture_since.lock() {
                *since = None;
            }
            if let Ok(mut rects) = state.interactive.lock() {
                rects.clear();
            }
            if let Some(window) = &pet_window {
                let _ = window.set_ignore_cursor_events(true);
                state.click_through_applied.store(true, Ordering::SeqCst);
            }
            eprintln!(
                "[pet] capture mode held too long; forcing click-through so the desktop stays usable"
            );
        }
        if capture_timed_out(state.ping_capture_since.lock().ok().and_then(|slot| *slot)) {
            if let Ok(mut mode) = state.ping_input_mode.lock() {
                *mode = "auto".to_string();
            }
            if let Ok(mut since) = state.ping_capture_since.lock() {
                *since = None;
            }
            if let Ok(mut rects) = state.ping_interactive.lock() {
                rects.clear();
            }
            if let Some(window) = &ping_window {
                let _ = window.set_ignore_cursor_events(true);
                state.ping_click_through_applied.store(true, Ordering::SeqCst);
            }
            eprintln!(
                "[pet] ping capture mode held too long; forcing click-through so the desktop stays usable"
            );
        }
        let inside = pet_window
            .as_ref()
            .map(|window| apply_pointer_mode(&state, window, PointerTarget::Pet, cx, cy))
            .unwrap_or(false);
        if let Some(window) = &ping_window {
            apply_pointer_mode(&state, window, PointerTarget::Ping, cx, cy);
        }
        if last_cursor != Some((cx, cy, inside)) {
            last_cursor = Some((cx, cy, inside));
            let _ = app.emit(
                "pet://cursor",
                CursorEvent {
                    x: cx,
                    y: cy,
                    inside,
                },
            );
        }
        if let Some(spec) = state.hotkey.lock().ok().and_then(|value| value.clone()) {
            let active = platform::hotkey_active(&spec);
            if active != hotkey_down {
                hotkey_down = active;
                eprintln!(
                    "[pet] ping hotkey {} at cursor ({cx},{cy})",
                    if active { "down" } else { "up" }
                );
                let _ = app.emit(
                    "pet://ping/hotkey",
                    HotkeyEvent {
                        phase: if active { "down" } else { "up" }.to_string(),
                        x: cx,
                        y: cy,
                        accelerator: spec.accelerator.clone(),
                    },
                );
            }
        }
        // 看门狗：覆盖层页面超过宽限期没跟宿主说话，就认为这块窗口已经没人画了。
        // user:"你给我兜好底，一旦遇到无法访问页面的时候，立刻把这个窗口关掉"+
        // (不再"先隐藏留着"：页面失联就直接销毁窗口、清掉命中区、退出置顶，
        //  把桌面立刻还给用户；托盘入口同时恢复成“打开桌宠”。)
        // 宽限期见 page_alive：报过心跳 6 秒，首次加载 12 秒。
        // Ping 覆盖层是独立窗口（可能还在用轮询），不能因为桌宠页面失联就退出。
        if let Some(window) = &pet_window {
            if !page_alive(&state) {
                eprintln!(
                    "[pet] overlay page unreachable; closing the overlay window immediately"
                );
                destroy_overlay_now(&app, window);
                if ping_window.is_none() {
                    state.poll_running.store(false, Ordering::SeqCst);
                    break;
                }
            }
        }
        std::thread::sleep(POLL_INTERVAL);
    }
}

fn point_in_rect(x: i32, y: i32, rect: &[f64; 4]) -> bool {
    let (rx, ry, rw, rh) = (rect[0], rect[1], rect[2], rect[3]);
    (x as f64) >= rx && (x as f64) <= rx + rw && (y as f64) >= ry && (y as f64) <= ry + rh
}

/// 带外扩容差的命中判定（迟滞迟返：离开判定比进入判定更宽松）。
fn point_in_rect_padded(x: i32, y: i32, rect: &[f64; 4], pad: f64) -> bool {
    point_in_rect(x, y, &[
        rect[0] - pad,
        rect[1] - pad,
        rect[2] + pad * 2.0,
        rect[3] + pad * 2.0,
    ])
}

// ---------------------------------------------------------------------------
// 命令：覆盖层与输入
// ---------------------------------------------------------------------------

/// 启动参数/环境变量是否要求“起来就直接打开桌宠覆盖层”。
///
/// user:“打开桌宠你用 cli”+(命令行给出 `--pet` 或 `--open-pet` 时，应用启动完就
///  自动开覆盖层，不依赖托盘点击；同时保留 `SUNDAY_PET_OPEN=1` 环境变量通道，
///  因为 tauri dev 会把 `--` 之后的参数塞给 cargo 自己，自动化走环境变量更稳。)
pub fn open_requested_from(args: &[String], pet_open_env: Option<&str>) -> bool {
    args.iter().any(|arg| arg == "--pet" || arg == "--open-pet")
        || pet_open_env.map(|value| value == "1").unwrap_or(false)
}

pub fn open_requested() -> bool {
    let args: Vec<String> = std::env::args().collect();
    open_requested_from(&args, std::env::var("SUNDAY_PET_OPEN").ok().as_deref())
}

/// 所有 WebView 窗口共用的基线参数：窗口被隐藏/遮挡时不要节流渲染器与定时器。
/// 覆盖层的心跳是 2 秒、看门狗 6 秒，一旦被节流会把自己判死；主窗口的流式渲染
/// 也会退化。这份基线同时用于配置窗口和运行时创建的覆盖层/卡片窗口——同一数据
/// 目录下，WebView2 不允许不同参数的环境共存。
pub const BASE_BROWSER_ARGS: &str = "--disable-backgrounding-occluded-windows --disable-renderer-backgrounding --disable-background-timer-throttling --disable-backgrounding-tabs";

/// WebView2 浏览器参数：基线 + 自动化模式注入的参数。
///
/// user:“自动化用 WebdriverIO”+(msedgedriver 拉起应用时通过
/// `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS` 注入 `--remote-debugging-port=0`，但
/// WebView2 规定 EnvironmentOptions 优先于环境变量，而 wry 固定写入自己的参数，
/// 调试端口永远开不出来，`DevToolsActivePort` 文件不会生成，会话建不起来。
/// 检测到注入时，把注入参数并入应用自己的 additionalBrowserArgs。)
pub fn browser_args(injected: Option<&str>) -> String {
    let mut args = BASE_BROWSER_ARGS.to_string();
    let Some(injected) = injected.map(str::trim).filter(|value| !value.is_empty()) else {
        return args;
    };
    args.push_str(
        " --autoplay-policy=no-user-gesture-required --disable-features=msWebOOUI,msPdfOOUI,msSmartScreenProtection ",
    );
    args.push_str(injected);
    args
}

pub fn browser_args_from_env() -> String {
    browser_args(std::env::var("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS").ok().as_deref())
}

/// 启动恢复：用户上次开着桌宠，这次启动就把它恢复起来。
/// user:“启动、退出、隐藏、恢复、休眠/暂停及异常重启路径完整”+
/// (只在配置里 enabled 且确有已安装角色时打开覆盖层，避免给没配角色的人凭空开窗。)
/// user:“一直未响应”+(主窗口前端在启动时 invoke 本命令；它最终会走 place_overlay
/// 的窗口读写，必须 async，否则在 WebView2 IPC 回调线程里重入死锁。)
#[tauri::command]
pub async fn pet_autostart(app: AppHandle) -> Result<bool, String> {
    let path = pet_root().join("config.json");
    let Ok(text) = std::fs::read_to_string(&path) else {
        return Ok(false);
    };
    let Ok(config) = serde_json::from_str::<serde_json::Value>(&text) else {
        return Ok(false);
    };
    let enabled = config.get("enabled").and_then(|value| value.as_bool()).unwrap_or(false);
    let has_pets = config
        .get("pets")
        .and_then(|value| value.as_array())
        .map(|list| !list.is_empty())
        .unwrap_or(false);
    if !(enabled && has_pets) {
        return Ok(false);
    }
    open_overlay_and_poll(app)?;
    Ok(true)
}

/// 建出/复用覆盖层窗口并启动轮询（同步版，供托盘线程、CLI 路径与自动恢复调用；
/// 这些调用方都在自己的线程上，不在 WebView2 的 IPC 回调里，等待主线程是安全的）。
pub fn open_overlay_and_poll(app: AppHandle) -> Result<OverlayBounds, String> {
    let bounds = open_overlay_window(&app)?;
    // 窗口的显示由页面自己触发（`pet_overlay_ready`）：页面没画出东西之前，
    // 这块全屏窗口保持隐藏，永远不会变成盖住桌面的黑块。
    start_polling(&app);
    Ok(bounds)
}

/// 页面通过 invoke 调用同名命令。
///
/// user:“一直未响应”+(页面 invoke 的命令跑在 WebView2 的 IPC 回调线程上；命令里
/// 再调窗口 API（place_overlay 的读写、show/hide、is_visible）就是对 WebView2
/// 宿主的同线程重入，直接死锁。所有会被页面调到、且要碰窗口 API 的命令都改成
/// async，让它们在异步运行时线程上执行。)
#[tauri::command]
pub async fn pet_overlay_open(app: AppHandle) -> Result<OverlayBounds, String> {
    open_overlay_and_poll(app)
}

/// 页面画出第一帧后调用：到这一步才真正把覆盖层显示出来。
/// user:“未响应”+(没有内容的窗口绝不能出现在桌面上，先把内容画出来再显示。)
/// 同 pet_overlay_open：show() 不能在 IPC 回调线程里重入，命令必须是 async。
#[tauri::command]
pub async fn pet_overlay_ready(app: AppHandle) -> Result<(), String> {
    let Some(window) = app.get_webview_window(OVERLAY_LABEL) else {
        return Err("pet overlay window is not open".into());
    };
    mark_frontend_seen(&app);
    window.show().map_err(|error| error.to_string())?;
    // 覆盖层真正可见后，托盘入口切成“关闭桌宠”。
    let _ = crate::refresh_tray_menu(&app);
    // user:“点击打开桌宠没反应”+(看门狗收走窗口后会停掉轮询线程；页面慢启动
    //  完成后再显示时，必须把轮询一起拉起来，否则穿透状态和 Ping 快捷键全失效。)
    start_polling(&app);
    Ok(())
}

#[tauri::command]
pub async fn pet_overlay_close(app: AppHandle) -> Result<(), String> {
    close_overlay_sync(&app)?;
    let _ = crate::refresh_tray_menu(&app);
    Ok(())
}

/// 覆盖层当前是否真的可见（托盘“打开桌宠/关闭桌宠”的状态源）。
pub fn overlay_is_open(app: &AppHandle) -> bool {
    app.get_webview_window(OVERLAY_LABEL)
        .and_then(|window| window.is_visible().ok())
        .unwrap_or(false)
}

/// 立即销毁覆盖层窗口：看门狗判定页面不可访问、以及“关闭桌宠”共用。
///
/// user:"你给我兜好底，一旦遇到无法访问页面的时候，立刻把这个窗口关掉"+
/// (先退出置顶 + 切回穿透再销毁，销毁失败也不会留下挡住桌面的窗口；
///  命中区一并清空，托盘文案恢复成“打开桌宠”。)
fn destroy_overlay_now(app: &AppHandle, window: &tauri::WebviewWindow) {
    let state = app.state::<PetState>();
    let _ = window.set_always_on_top(false);
    let _ = window.set_ignore_cursor_events(true);
    state.click_through_applied.store(true, Ordering::SeqCst);
    if let Ok(mut rects) = state.interactive.lock() {
        rects.clear();
    }
    if let Err(error) = window.destroy() {
        eprintln!("[pet] destroy overlay window failed: {error}");
        let _ = window.hide();
    }
    let _ = crate::refresh_tray_menu(app);
}

/// 同步关闭覆盖层：托盘菜单在主线程上调用，不能走 async 命令。
pub fn close_overlay_sync(app: &AppHandle) -> Result<(), String> {
    let state = app.state::<PetState>();
    // 只有 Ping 窗口也关着时才停轮询；Ping 还开着时轮询要继续为它工作。
    if app.get_webview_window(PING_OVERLAY_LABEL).is_none() {
        stop_polling(&state);
    }
    if let Some(window) = app.get_webview_window(OVERLAY_LABEL) {
        destroy_overlay_now(app, &window);
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Ping 独立覆盖层（环/标记/标注/会话选择器）
// ---------------------------------------------------------------------------

#[tauri::command]
pub async fn pet_ping_overlay_open(app: AppHandle) -> Result<OverlayBounds, String> {
    ensure_ping_overlay(&app)
}

#[tauri::command]
pub async fn pet_ping_overlay_show(app: AppHandle) -> Result<(), String> {
    let window = app
        .get_webview_window(PING_OVERLAY_LABEL)
        .ok_or_else(|| "ping overlay is not open".to_string())?;
    window.show().map_err(|error| error.to_string())?;
    eprintln!("[pet] ping overlay shown");
    start_polling(&app);
    Ok(())
}

#[tauri::command]
pub async fn pet_ping_overlay_hide(app: AppHandle) -> Result<(), String> {
    if let Some(window) = app.get_webview_window(PING_OVERLAY_LABEL) {
        let _ = window.set_ignore_cursor_events(true);
        app.state::<PetState>()
            .ping_click_through_applied
            .store(true, Ordering::SeqCst);
        let _ = window.hide();
        eprintln!("[pet] ping overlay hidden");
    }
    Ok(())
}

/// Ping 窗口的命中矩形（物理像素屏幕坐标 [x, y, w, h]）。
#[tauri::command]
pub fn pet_ping_set_interactive_rects(app: AppHandle, rects: Vec<[f64; 4]>) -> Result<(), String> {
    let state = app.state::<PetState>();
    let kept: Vec<[f64; 4]> = rects
        .into_iter()
        .map(|rect| [
            rect[0].round(),
            rect[1].round(),
            rect[2].max(1.0).round(),
            rect[3].max(1.0).round(),
        ])
        .collect();
    *state
        .ping_interactive
        .lock()
        .map_err(|_| "ping interactive rect lock failed".to_string())? = kept;
    Ok(())
}

/// Ping 窗口输入模式：auto | capture | passthrough（框选时 capture）。
///
/// 框选需要键盘（Esc 取消）：capture 时临时让覆盖层可激活并聚焦，
/// 退出时恢复不可激活，避免键盘事件永远进不来。
#[tauri::command]
pub async fn pet_ping_set_input_mode(app: AppHandle, mode: String) -> Result<(), String> {
    let capture = mode == "capture";
    {
        let state = app.state::<PetState>();
        *state
            .ping_input_mode
            .lock()
            .map_err(|_| "ping input mode lock failed".to_string())? = mode.clone();
        if let Ok(mut since) = state.ping_capture_since.lock() {
            *since = if capture { Some(Instant::now()) } else { None };
        };
    }
    #[cfg(windows)]
    if let Some(window) = app.get_webview_window(PING_OVERLAY_LABEL) {
        let _ = platform::set_overlay_activatable(&window, capture);
        if capture {
            let _ = window.show();
            let _ = window.set_focus();
        }
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Ping 卡片窗口（卡片即窗口：与桌宠覆盖层分离，原生 Acrylic 材质）
// ---------------------------------------------------------------------------

/// 测试/自动化入口：让正在运行的实例直接执行某个 Ping 扇区动作。
///
/// user:“你为什么不CLI先行用CLI直接执行 ping 环内的操作”+(单实例回调收到
/// `--ping-commit=<扇区id>` 时给 Ping 页发事件，页面直接执行该扇区；
///  不依赖真实键鼠，自动化可重复。)
pub fn simulate_ping_commit(app: &AppHandle, sector_id: &str) {
    eprintln!("[pet] ping test-commit sector={sector_id}");
    let _ = app.emit("pet://ping/test-commit", sector_id.to_string());
}

// user:“环出现了，但是我把它选中到对话之后，没有任何的窗口打开”+
// (卡片命令必须 async：页面 invoke 的同步命令跑在 WebView2 IPC 回调线程上，
//  命令里再建/关窗口就是同线程重入死锁，表现就是点「对话」后整个应用未响应。)

#[tauri::command]
pub async fn pet_open_ping_card(
    app: AppHandle,
    card_id: String,
    session_id: String,
    project_id: Option<String>,
    title: String,
    rect: [f64; 4],
) -> Result<(), String> {
    cards::open(&app, &card_id, &session_id, project_id.as_deref(), &title, rect)
}

#[tauri::command]
pub async fn pet_show_ping_card(app: AppHandle, card_id: String) -> Result<(), String> {
    cards::show(&app, &card_id)
}

#[tauri::command]
pub async fn pet_close_ping_card(app: AppHandle, card_id: String) -> Result<(), String> {
    cards::close(&app, &card_id)
}

/// Ping 完成后打开 Sunday 本体：把主窗口恢复到一个合适的大小，并通知主界面
/// 切到对应会话。
///
/// user:“ping完之后用一个合适的大小打开Sunday本体…这样最大程度复用”+
/// (不再为 Ping 单独建卡片窗口：直接复用主窗口完整的聊天/输入界面。)
#[tauri::command]
pub async fn pet_open_main_session(
    app: AppHandle,
    project_id: Option<String>,
    session_id: String,
) -> Result<(), String> {
    let window = app
        .get_webview_window("main")
        .ok_or_else(|| "main window is not open".to_string())?;
    let _ = window.unminimize();
    let _ = window.unmaximize();
    // 小尺寸：窄而高的聊天窗口（用户指定的截图大小，约 582×720 逻辑像素）。
    let _ = window.set_size(tauri::LogicalSize::new(582.0, 720.0));
    let _ = window.show();
    let _ = window.set_focus();
    app.emit_to(
        "main",
        "app://open-session",
        serde_json::json!({
            "projectId": project_id,
            "sessionId": session_id,
        }),
    )
    .map_err(|error| error.to_string())?;
    Ok(())
}

/// 主窗口是否处于焦点。
///
/// user:"主窗口聚焦时不显示气泡"+(用户已经在 Sunday 主界面里，桌宠头顶的审批/提问
/// 气泡不再重复弹；失焦后自动恢复显示。异步命令：窗口 API 不能跑在 IPC 回调线程上。)
#[tauri::command]
pub async fn pet_main_window_focused(app: AppHandle) -> bool {
    app.get_webview_window("main")
        .and_then(|window| window.is_focused().ok())
        .unwrap_or(false)
}

/// 前端把当前所有可交互区域（角色、气泡、卡片、环）按**物理像素屏幕坐标**
/// 报了上来。轮询线程据此决定这一帧覆盖层吃不吃鼠标。
#[tauri::command]
pub fn pet_set_interactive_rects(app: AppHandle, rects: Vec<[f64; 4]>) -> Result<(), String> {
    mark_frontend_seen(&app);
    let state = app.state::<PetState>();
    let kept: Vec<[f64; 4]> = rects
        .into_iter()
        .filter(|rect| rect[2] > 0.5 && rect[3] > 0.5)
        .collect();
    let mut slot = state
        .interactive
        .lock()
        .map_err(|_| "pet interactive rect lock failed".to_string())?;
    *slot = kept;
    Ok(())
}

/// 覆盖层页面的心跳。前端每 2 秒报一次；超过 6 秒没报，宿主就认定这块窗口
/// 已经没人画了，直接销毁窗口，避免留下一块盖住桌面又没内容的窗口。
#[tauri::command]
pub fn pet_overlay_heartbeat(app: AppHandle) {
    mark_frontend_seen(&app);
}

#[tauri::command]
pub fn pet_set_input_mode(app: AppHandle, mode: String) -> Result<(), String> {
    let normalized = match mode.as_str() {
        "capture" | "passthrough" | "auto" => mode,
        _ => "auto".to_string(),
    };
    let state = app.state::<PetState>();
    let capture = normalized == "capture";
    let mut slot = state
        .input_mode
        .lock()
        .map_err(|_| "pet input mode lock failed".to_string())?;
    *slot = normalized;
    drop(slot);
    if let Ok(mut since) = state.capture_since.lock() {
        *since = if capture { Some(Instant::now()) } else { None };
    }
    Ok(())
}

#[tauri::command]
pub async fn pet_set_z_mode(app: AppHandle, mode: String) -> Result<(), String> {
    // 同 pet_overlay_open：set_always_on_top / 平台 Z 序都要动窗口，不能在
    // IPC 回调线程里执行。
    // 诊断模式下窗口必须是普通窗口，置顶/压底都跳过。
    if diag_mode() {
        return Ok(());
    }
    set_z_mode_impl(&app, mode)
}

fn set_z_mode_impl(app: &AppHandle, mode: String) -> Result<(), String> {
    let normalized = if mode == "behind" { "behind" } else { "top" };
    let state = app.state::<PetState>();
    if let Ok(mut slot) = state.z_mode.lock() {
        *slot = normalized.to_string();
    }
    let Some(window) = app.get_webview_window(OVERLAY_LABEL) else {
        return Ok(());
    };
    window
        .set_always_on_top(normalized == "top")
        .map_err(|error| error.to_string())?;
    #[cfg(windows)]
    platform::set_z_mode(&window, normalized)?;
    Ok(())
}

/// 真实桌面窗口（含位置与 Z 序）：L2 地形来源，也给"真实遮挡"诊断用。
#[tauri::command]
pub fn pet_desktop_windows() -> Result<Vec<DesktopWindowReport>, String> {
    // 按本进程 id 排除 Sunday 自己的窗口（主界面/覆盖层/卡片），不再只靠标题。
    let windows = platform::desktop_windows(
        vec!["Sunday Pet".to_string(), "Sunday".to_string()],
        Some(std::process::id()),
    );
    Ok(windows
        .into_iter()
        .map(|window| DesktopWindowReport {
            id: window.id,
            title: window.title,
            class_name: window.class_name,
            bounds: WindowBounds {
                x: window.x,
                y: window.y,
                width: window.width,
                height: window.height,
            },
            z: window.z,
        })
        .collect())
}

#[derive(Serialize, Clone, Debug)]
pub struct WindowBounds {
    pub x: i32,
    pub y: i32,
    pub width: i32,
    pub height: i32,
}

#[derive(Serialize, Clone, Debug)]
pub struct DesktopWindowReport {
    pub id: String,
    pub title: String,
    pub class_name: String,
    pub bounds: WindowBounds,
    pub z: i32,
}

#[tauri::command]
pub fn pet_monitors() -> Result<Vec<MonitorInfo>, String> {
    #[cfg(windows)]
    {
        platform::monitors()
    }
    #[cfg(not(windows))]
    {
        Ok(Vec::new())
    }
}

#[tauri::command]
pub fn pet_cursor() -> Result<CursorReport, String> {
    let (x, y) = platform::cursor_position()?;
    Ok(CursorReport {
        x,
        y,
        monitor: platform::monitor_at(x, y).ok(),
    })
}

// ---------------------------------------------------------------------------
// 命令：截图
// ---------------------------------------------------------------------------

/// user:“从你启动开始就一直是黑屏未响应状态”+
/// (抓屏时不再依赖 SetWindowDisplayAffinity 的全程隐身，而是只在真正截图这一下
///  把覆盖层藏起来：既不污染 Ping 底图，也不会让远程桌面/录屏看到整屏纯黑。)
fn capture_with_overlay_hidden<R>(
    app: &AppHandle,
    run: impl FnOnce() -> Result<R, String>,
) -> Result<R, String> {
    // 桌宠与 Ping 是两个独立覆盖层：抓屏时都要藏起来，否则 Ping 的环/标记会被
    // 烘进底图，前端再叠加一次标记就出现重影。
    let overlays: Vec<(tauri::WebviewWindow, bool)> = [OVERLAY_LABEL, PING_OVERLAY_LABEL]
        .iter()
        .filter_map(|label| app.get_webview_window(label))
        .map(|window| {
            let visible = window.is_visible().unwrap_or(false);
            if visible {
                let _ = window.hide();
            }
            (window, visible)
        })
        .collect();
    if overlays.iter().any(|(_, visible)| *visible) {
        // 给 DWM 两帧时间把窗口真正从合成结果里拿掉，否则抓到的还是上一帧。
        std::thread::sleep(Duration::from_millis(120));
    }
    let result = run();
    for (window, visible) in overlays {
        if visible {
            let _ = window.show();
        }
    }
    result
}

#[tauri::command]
pub async fn pet_capture_monitor_under_cursor(app: AppHandle) -> Result<tauri::ipc::Response, String> {
    #[cfg(windows)]
    {
        // user:“一直未响应”+(同步命令跑在 WebView2 的 IPC 回调线程上，命令里再调
        // is_visible/hide 这类要进 WebView2 宿主的 API 就是同线程重入，整个应用
        // 死锁。异步命令在异步运行时线程上执行，窗口 API 等主线程事件循环是安全的。)
        capture_with_overlay_hidden(&app, || {
            let (x, y) = platform::cursor_position()?;
            let monitor = platform::monitor_at(x, y)?;
            let (width, height, pixels) = platform::capture(&monitor)?;
            Ok(platform::encode_capture(monitor.x, monitor.y, monitor.scale, width, height, pixels))
        })
    }
    #[cfg(not(windows))]
    {
        let _ = app;
        Err("screen capture is only implemented on Windows".into())
    }
}

#[tauri::command]
pub async fn pet_capture_monitor(app: AppHandle, monitor_id: String) -> Result<tauri::ipc::Response, String> {
    #[cfg(windows)]
    {
        // 同 pet_capture_monitor_under_cursor：窗口 API 不能在 IPC 回调里重入。
        capture_with_overlay_hidden(&app, || {
            let monitor = platform::monitors()?
                .into_iter()
                .find(|item| item.id == monitor_id)
                .ok_or_else(|| format!("monitor not found: {monitor_id}"))?;
            let (width, height, pixels) = platform::capture(&monitor)?;
            Ok(platform::encode_capture(monitor.x, monitor.y, monitor.scale, width, height, pixels))
        })
    }
    #[cfg(not(windows))]
    {
        let _ = (app, monitor_id);
        Err("screen capture is only implemented on Windows".into())
    }
}

// ---------------------------------------------------------------------------
// 命令：全局 Ping 快捷键
// ---------------------------------------------------------------------------

#[tauri::command]
pub fn pet_hotkey_set(app: AppHandle, accelerator: Option<String>) -> Result<(), String> {
    let state = app.state::<PetState>();
    let parsed = match accelerator {
        // user:“快捷键按住时，以按下瞬间鼠标位置为中心显示轮盘”+
        // (按下/松开两个阶段都要拿到，因此用全局轮询而不是只报按下的 RegisterHotKey)
        Some(text) if !text.trim().is_empty() => Some(platform::parse_hotkey(&text)?),
        _ => None,
    };
    let mut slot = state
        .hotkey
        .lock()
        .map_err(|_| "pet hotkey lock failed".to_string())?;
    eprintln!(
        "[pet] hotkey set: {}",
        parsed
            .as_ref()
            .map(|spec| format!("{} mods={} vk=0x{:x}", spec.accelerator, spec.modifiers, spec.vk))
            .unwrap_or_else(|| "none".to_string())
    );
    *slot = parsed;
    Ok(())
}

// ---------------------------------------------------------------------------
// 存储：配置、角色包
// ---------------------------------------------------------------------------

/// 与后端 `config/root.py` 的 `lam_home()` 保持一致：
/// 1) LAMTOOLS_HOME  2) debug 源码树 core/.lam  3) 打包后 <exe_dir>/.lam
fn lam_home() -> PathBuf {
    if let Ok(value) = std::env::var("LAMTOOLS_HOME") {
        if !value.trim().is_empty() {
            return PathBuf::from(value);
        }
    }
    if cfg!(debug_assertions) {
        return PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .and_then(|desktop| desktop.parent())
            .map(|core| core.join(".lam"))
            .unwrap_or_else(|| PathBuf::from(".lam"));
    }
    std::env::current_exe()
        .ok()
        .and_then(|exe| exe.parent().map(|dir| dir.join(".lam")))
        .unwrap_or_else(|| PathBuf::from(".lam"))
}

fn pet_root() -> PathBuf {
    lam_home().join("pet")
}

fn packs_root() -> PathBuf {
    pet_root().join("packs")
}

fn ensure_pet_root() -> Result<(), String> {
    std::fs::create_dir_all(packs_root()).map_err(|error| format!("create pet root failed: {error}"))
}

/// 与后端 `fallback_project_root()` 一致的兜底工作区（My Project）。
/// user:“用户从未设过默认绑定但首次需要 Agent 交互时，在 My Project 下按需创建一个
/// 新会话”+(兜底项目的工作区必须与后端认定的同一个，否则会多出一个空项目。)
#[tauri::command]
pub fn pet_default_work_root() -> Result<String, String> {
    let projects_root = if cfg!(debug_assertions) {
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .and_then(|desktop| desktop.parent())
            .and_then(|core| core.parent())
            .map(|repo| repo.join("lam_projects"))
    } else {
        std::env::current_exe()
            .ok()
            .and_then(|exe| exe.parent().map(|dir| dir.join("lam_projects")))
    }
    .ok_or_else(|| "cannot resolve lam_projects root".to_string())?;
    let fallback = projects_root
        .parent()
        .ok_or_else(|| "cannot resolve fallback workspace".to_string())?
        .join("MyProject");
    Ok(fallback.to_string_lossy().into_owned())
}

#[tauri::command]
pub fn pet_config_read() -> Result<Option<String>, String> {
    let path = pet_root().join("config.json");
    match std::fs::read_to_string(&path) {
        Ok(text) => Ok(Some(text)),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(error) => Err(format!("read pet config failed: {error}")),
    }
}

#[tauri::command]
pub fn pet_config_write(text: String) -> Result<(), String> {
    // user:“用户配置与默认值具有明确版本号，可从旧版迁移/初始化”+
    // (配置写盘只由 Rust 侧完成，前端不直接碰磁盘路径。)
    ensure_pet_root()?;
    if text.len() > 4 * 1024 * 1024 {
        return Err("pet config is too large".into());
    }
    let path = pet_root().join("config.json");
    let temp = path.with_extension("json.tmp");
    std::fs::write(&temp, text.as_bytes()).map_err(|error| format!("write pet config failed: {error}"))?;
    std::fs::rename(&temp, &path).map_err(|error| format!("commit pet config failed: {error}"))
}

const ALLOWED_ASSET_EXTS: &[&str] = &[
    "json", "png", "jpg", "jpeg", "webp", "gif", "bmp", "svg", "glb", "gltf", "bin", "atlas",
    "txt", "md", "ogg", "mp3", "wav", "vrm", "vrma", "inp", "inp2d", "plist", "skel", "spriteatlas",
];
const MAX_PACK_FILES: usize = 800;
const MAX_PACK_BYTES: u64 = 160 * 1024 * 1024;
const MAX_SINGLE_ASSET_BYTES: u64 = 64 * 1024 * 1024;

fn normalize_rel(rel: &str) -> Result<PathBuf, String> {
    let cleaned = rel.replace('\\', "/");
    if cleaned.is_empty() {
        return Err("empty asset path".into());
    }
    let mut out = PathBuf::new();
    for part in cleaned.split('/') {
        if part.is_empty() || part == "." {
            continue;
        }
        if part == ".." {
            return Err(format!("asset path escapes its root: {rel}"));
        }
        // 冒号会把 Windows 盘符/备用数据流带进来。
        if part.contains(':') {
            return Err(format!("asset path has an invalid segment: {rel}"));
        }
        out.push(part);
    }
    if out.as_os_str().is_empty() {
        return Err("empty asset path".into());
    }
    Ok(out)
}

fn asset_ext(path: &Path) -> String {
    path.extension()
        .map(|ext| ext.to_string_lossy().to_ascii_lowercase())
        .unwrap_or_default()
}

fn is_allowed_asset(path: &Path) -> bool {
    ALLOWED_ASSET_EXTS.contains(&asset_ext(path).as_str())
}

/// 递归扫描一个候选角色包目录：只读元数据，不读内容，不跟随符号链接。
fn scan_dir(root: &Path) -> Result<ImportScan, String> {
    let mut files = Vec::new();
    let mut total = 0u64;
    let mut stack = vec![root.to_path_buf()];
    while let Some(dir) = stack.pop() {
        let entries = std::fs::read_dir(&dir)
            .map_err(|error| format!("read {} failed: {error}", dir.display()))?;
        for entry in entries {
            let entry = entry.map_err(|error| error.to_string())?;
            let file_type = entry.file_type().map_err(|error| error.to_string())?;
            // 普通资源包不跟随符号链接，避免把任意系统目录拉进角色包。
            if file_type.is_symlink() {
                continue;
            }
            let path = entry.path();
            if file_type.is_dir() {
                stack.push(path);
                continue;
            }
            if !file_type.is_file() {
                continue;
            }
            let rel = path
                .strip_prefix(root)
                .map_err(|error| error.to_string())?
                .to_string_lossy()
                .replace('\\', "/");
            let size = entry.metadata().map(|meta| meta.len()).unwrap_or(0);
            total += size;
            files.push(ImportFile {
                rel,
                size,
                ext: asset_ext(&path),
            });
            if files.len() > MAX_PACK_FILES {
                return Err(format!("角色包文件数超过上限（{MAX_PACK_FILES}）"));
            }
            if total > MAX_PACK_BYTES {
                return Err(format!("角色包体积超过上限（{} MB）", MAX_PACK_BYTES / 1024 / 1024));
            }
        }
    }
    files.sort_by(|a, b| a.rel.cmp(&b.rel));
    Ok(ImportScan {
        root: root.to_string_lossy().into_owned(),
        files,
        total_bytes: total,
    })
}

/// 读取用户选中的皮肤图片（只接受图片扩展名，64MB 上限）。
/// user:“支持导入自定义 PNG 皮肤并即时换肤”+
/// (只读用户自己选的图片，随后由前端校验尺寸并写进角色包目录。)
#[tauri::command]
pub fn pet_read_image(path: String) -> Result<tauri::ipc::Response, String> {
    let canonical = PathBuf::from(&path)
        .canonicalize()
        .map_err(|error| format!("读取皮肤失败：{error}"))?;
    let ext = asset_ext(&canonical);
    if !matches!(ext.as_str(), "png" | "jpg" | "jpeg" | "webp" | "bmp" | "gif") {
        return Err(format!("不是图片文件：{ext}"));
    }
    let meta = std::fs::metadata(&canonical).map_err(|error| error.to_string())?;
    if meta.len() > 64 * 1024 * 1024 {
        return Err("图片超过 64MB，已拒绝读取".into());
    }
    let bytes = std::fs::read(&canonical).map_err(|error| format!("读取皮肤失败：{error}"))?;
    Ok(tauri::ipc::Response::new(bytes))
}

/// 读取用户选中的 `.sundaypet` / `.zip` 字节。
/// user:“支持安装/打开 .sundaypet（ZIP 包或正式采用的等效容器）”+
/// (解包在前端内存里做并逐文件校验后落盘；Rust 只负责按路径读一个**用户自己选的**文件。)
#[tauri::command]
pub fn pet_read_zip(path: String) -> Result<tauri::ipc::Response, String> {
    let raw = PathBuf::from(&path);
    let canonical = raw
        .canonicalize()
        .map_err(|error| format!("读取角色包失败：{error}"))?;
    let meta = std::fs::metadata(&canonical).map_err(|error| error.to_string())?;
    if !meta.is_file() {
        return Err("角色包路径不是文件".into());
    }
    // 200MB 上限：超过它的"角色包"不是资源包，是别的东西。
    if meta.len() > 200 * 1024 * 1024 {
        return Err("角色包超过 200MB，已拒绝读取".into());
    }
    let ext = asset_ext(&canonical);
    if ext != "sundaypet" && ext != "zip" {
        return Err(format!("不是角色包容器：{ext}"));
    }
    let bytes = std::fs::read(&canonical).map_err(|error| format!("读取角色包失败：{error}"))?;
    Ok(tauri::ipc::Response::new(bytes))
}

#[tauri::command]
pub fn pet_scan_import(app: AppHandle, path: String) -> Result<ImportScan, String> {
    let raw = PathBuf::from(&path);
    if !raw.exists() {
        return Err(format!("路径不存在：{path}"));
    }
    let canonical = raw
        .canonicalize()
        .map_err(|error| format!("resolve import path failed: {error}"))?;
    // 单文件导入：把它当成一个只含该文件的角色包根（父目录作为根）。
    let (root, scan) = if canonical.is_dir() {
        (canonical.clone(), scan_dir(&canonical)?)
    } else {
        let parent = canonical
            .parent()
            .ok_or_else(|| "file has no parent directory".to_string())?
            .to_path_buf();
        let rel = canonical
            .strip_prefix(&parent)
            .map_err(|error| error.to_string())?
            .to_string_lossy()
            .replace('\\', "/");
        let size = std::fs::metadata(&canonical).map(|meta| meta.len()).unwrap_or(0);
        (
            parent,
            ImportScan {
                root: String::new(),
                files: vec![ImportFile {
                    rel,
                    size,
                    ext: asset_ext(&canonical),
                }],
                total_bytes: size,
            },
        )
    };
    let state = app.state::<PetState>();
    if let Ok(mut slot) = state.import_root.lock() {
        *slot = Some(root.clone());
    }
    Ok(ImportScan {
        root: root.to_string_lossy().into_owned(),
        ..scan
    })
}

#[tauri::command]
pub fn pet_read_import_asset(app: AppHandle, rel: String) -> Result<tauri::ipc::Response, String> {
    let state = app.state::<PetState>();
    let root = state
        .import_root
        .lock()
        .ok()
        .and_then(|slot| slot.clone())
        .ok_or_else(|| "没有待导入的角色包".to_string())?;
    read_bounded_asset(&root, &rel)
}

fn read_bounded_asset(root: &Path, rel: &str) -> Result<tauri::ipc::Response, String> {
    Ok(tauri::ipc::Response::new(read_bounded_asset_bytes(root, rel)?))
}

fn read_bounded_asset_bytes(root: &Path, rel: &str) -> Result<Vec<u8>, String> {
    let normalized = normalize_rel(rel)?;
    if !is_allowed_asset(&normalized) {
        return Err(format!("不支持的资源类型：{rel}"));
    }
    let target = root.join(&normalized);
    let canonical = target
        .canonicalize()
        .map_err(|error| format!("read asset {rel} failed: {error}"))?;
    if !canonical_contains(root, &canonical) {
        return Err(format!("资源路径越界：{rel}"));
    }
    let meta = std::fs::metadata(&canonical).map_err(|error| error.to_string())?;
    if meta.len() > MAX_SINGLE_ASSET_BYTES {
        return Err(format!("单个资源超过上限：{rel}"));
    }
    std::fs::read(&canonical).map_err(|error| format!("read asset {rel} failed: {error}").into())
}

/// 判断 canonical 之后的子路径是否仍在 root 内。
///
/// user:"左下角确实有个诊断，但是我没看见方块人啊"+
/// (Windows 的 `canonicalize()` 返回 `\\?\E:\...` 长前缀，root 不做同样的规范化
/// 就永远比不中——所有包内资源（方块人皮肤、贴图）都被误判"资源路径越界"，
/// 角色加载不出任何外观。两边必须同一种形态再比。)
fn canonical_contains(root: &Path, canonical_child: &Path) -> bool {
    let canonical_root = root
        .canonicalize()
        .unwrap_or_else(|_| root.to_path_buf());
    canonical_child.starts_with(&canonical_root)
}

fn install_into(root: &Path, target: &Path, scan: &ImportScan) -> Result<usize, String> {
    let mut copied = 0usize;
    for file in &scan.files {
        let normalized = match normalize_rel(&file.rel) {
            Ok(value) => value,
            Err(_) => continue,
        };
        if !is_allowed_asset(&normalized) {
            // 不支持的类型跳过而不是整包失败：允许保留其他可用资源。
            continue;
        }
        let source = root.join(&normalized);
        let canonical = match source.canonicalize() {
            Ok(value) => value,
            Err(_) => continue,
        };
        if !canonical_contains(root, &canonical) {
            continue;
        }
        let destination = target.join(&normalized);
        if let Some(parent) = destination.parent() {
            std::fs::create_dir_all(parent).map_err(|error| error.to_string())?;
        }
        std::fs::copy(&canonical, &destination).map_err(|error| {
            format!("复制 {} 失败：{error}", file.rel)
        })?;
        copied += 1;
    }
    Ok(copied)
}

/// user:“支持安装/打开 .sundaypet（ZIP 包或正式采用的等效容器）”+
/// (ZIP 解包改由前端 fflate 在内存中完成并校验后逐文件写入，Rust 侧只负责
///  路径/大小/类型三重校验与落盘，二者共用同一套白名单。)
#[tauri::command]
pub fn pet_install_pack(app: AppHandle, name: String) -> Result<InstalledPack, String> {
    ensure_pet_root()?;
    let state = app.state::<PetState>();
    let root = state
        .import_root
        .lock()
        .ok()
        .and_then(|slot| slot.clone())
        .ok_or_else(|| "没有待导入的角色包".to_string())?;
    let scan = scan_dir(&root)?;
    if scan.files.is_empty() {
        return Err("这个角色包里没有任何资源".into());
    }
    let id = sanitize_pack_id(&name)?;
    let target = packs_root().join(&id);
    if target.exists() {
        std::fs::remove_dir_all(&target).map_err(|error| error.to_string())?;
    }
    std::fs::create_dir_all(&target).map_err(|error| error.to_string())?;
    let copied = install_into(&root, &target, &scan)?;
    if copied == 0 {
        let _ = std::fs::remove_dir_all(&target);
        return Err("角色包里没有可用资源（类型均不在白名单内）".into());
    }
    Ok(InstalledPack {
        id: id.clone(),
        dir: target.to_string_lossy().into_owned(),
        files: copied,
        bytes: scan.total_bytes,
    })
}

#[derive(Serialize, Clone, Debug)]
pub struct PackWriteReport {
    pub id: String,
    pub files: usize,
    pub bytes: u64,
}

fn read_u16(bytes: &[u8], cursor: &mut usize) -> Result<u16, String> {
    if *cursor + 2 > bytes.len() {
        return Err("角色包数据不完整".into());
    }
    let value = u16::from_le_bytes([bytes[*cursor], bytes[*cursor + 1]]);
    *cursor += 2;
    Ok(value)
}

fn read_u32(bytes: &[u8], cursor: &mut usize) -> Result<u32, String> {
    if *cursor + 4 > bytes.len() {
        return Err("角色包数据不完整".into());
    }
    let value = u32::from_le_bytes([
        bytes[*cursor],
        bytes[*cursor + 1],
        bytes[*cursor + 2],
        bytes[*cursor + 3],
    ]);
    *cursor += 4;
    Ok(value)
}

fn read_slice<'a>(bytes: &'a [u8], cursor: &mut usize, length: usize) -> Result<&'a [u8], String> {
    if *cursor + length > bytes.len() {
        return Err("角色包数据不完整".into());
    }
    let slice = &bytes[*cursor..*cursor + length];
    *cursor += length;
    Ok(slice)
}

/// 一次性写入整包资源（ZIP 解包后的结果）。
/// user:“支持安装/打开 .sundaypet”+(整包二进制一次传输，避免逐文件 JSON 数组把大模型拖慢；
/// 校验规则与单文件写入完全一致。)
#[tauri::command]
pub fn pet_write_pack_bundle(request: tauri::ipc::Request<'_>) -> Result<PackWriteReport, String> {
    let raw = match request.body() {
        tauri::ipc::InvokeBody::Raw(data) => data.as_slice(),
        _ => return Err("角色包写入需要二进制请求体".into()),
    };
    ensure_pet_root()?;
    let mut cursor = 0usize;
    let name_length = read_u16(raw, &mut cursor)? as usize;
    let name_bytes = read_slice(raw, &mut cursor, name_length)?;
    let pack_name = String::from_utf8(name_bytes.to_vec()).map_err(|_| "角色包名字不是有效 UTF-8".to_string())?;
    let id = sanitize_pack_id(&pack_name)?;
    let count = read_u32(raw, &mut cursor)?;
    if count as usize > MAX_PACK_FILES {
        return Err(format!("角色包文件数超过上限（{MAX_PACK_FILES}）"));
    }
    let target = packs_root().join(&id);
    if target.exists() {
        std::fs::remove_dir_all(&target).map_err(|error| error.to_string())?;
    }
    std::fs::create_dir_all(&target).map_err(|error| error.to_string())?;
    let mut written = 0usize;
    let mut total = 0u64;
    for _ in 0..count {
        let rel_length = read_u16(raw, &mut cursor)? as usize;
        let rel_bytes = read_slice(raw, &mut cursor, rel_length)?;
        let rel = String::from_utf8(rel_bytes.to_vec()).map_err(|_| "资源路径不是有效 UTF-8".to_string())?;
        let data_length = read_u32(raw, &mut cursor)? as usize;
        let data = read_slice(raw, &mut cursor, data_length)?;
        let normalized = match normalize_rel(&rel) {
            Ok(value) => value,
            Err(_) => continue,
        };
        if !is_allowed_asset(&normalized) || data.len() as u64 > MAX_SINGLE_ASSET_BYTES {
            continue;
        }
        total += data.len() as u64;
        if total > MAX_PACK_BYTES {
            let _ = std::fs::remove_dir_all(&target);
            return Err(format!("角色包体积超过上限（{} MB）", MAX_PACK_BYTES / 1024 / 1024));
        }
        let destination = target.join(&normalized);
        if let Some(parent) = destination.parent() {
            std::fs::create_dir_all(parent).map_err(|error| error.to_string())?;
        }
        std::fs::write(&destination, data).map_err(|error| format!("写入 {rel} 失败：{error}"))?;
        written += 1;
    }
    if written == 0 {
        let _ = std::fs::remove_dir_all(&target);
        return Err("角色包里没有可用资源（类型均不在白名单内）".into());
    }
    Ok(PackWriteReport {
        id,
        files: written,
        bytes: total,
    })
}

/// 把前端从 ZIP 里解出来的单个资源写进已安装的角色包目录。
#[tauri::command]
pub fn pet_write_pack_asset(pack_id: String, rel: String, bytes: Vec<u8>) -> Result<(), String> {
    ensure_pet_root()?;
    let id = sanitize_pack_id(&pack_id)?;
    let target = packs_root().join(&id);
    std::fs::create_dir_all(&target).map_err(|error| error.to_string())?;
    let normalized = normalize_rel(&rel)?;
    if !is_allowed_asset(&normalized) {
        return Err(format!("不支持的资源类型：{rel}"));
    }
    if bytes.len() as u64 > MAX_SINGLE_ASSET_BYTES {
        return Err(format!("单个资源超过上限：{rel}"));
    }
    let destination = target.join(&normalized);
    if let Some(parent) = destination.parent() {
        std::fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    std::fs::write(&destination, &bytes).map_err(|error| format!("写入 {rel} 失败：{error}"))
}

fn sanitize_pack_id(name: &str) -> Result<String, String> {
    let trimmed = name.trim();
    if trimmed.is_empty() {
        return Err("角色包名字为空".into());
    }
    let mut out = String::new();
    for ch in trimmed.chars() {
        if ch.is_ascii_alphanumeric() || ch == '-' || ch == '_' || ch == '.' {
            out.push(ch.to_ascii_lowercase());
        } else if ch.is_whitespace() {
            out.push('-');
        }
        if out.len() >= 48 {
            break;
        }
    }
    let cleaned = out.trim_matches('-').trim_matches('.').to_string();
    if cleaned.is_empty() {
        return Err("角色包名字里没有可用字符".into());
    }
    if cleaned.contains("..") {
        return Err("角色包名字非法".into());
    }
    Ok(cleaned)
}

#[tauri::command]
pub fn pet_pack_asset(pack_id: String, rel: String) -> Result<tauri::ipc::Response, String> {
    let id = sanitize_pack_id(&pack_id)?;
    let root = packs_root().join(id);
    if !root.is_dir() {
        return Err("角色包不存在".into());
    }
    read_bounded_asset(&root, &rel)
}

#[tauri::command]
pub async fn pet_pick_import() -> Option<String> {
    // 目录优先：`.sundaypet` ZIP 由前端文件选择器处理，这里给文件夹导入。
    // 必须用 AsyncFileDialog：同步文件对话框会阻塞 WebView2 的 IPC 回调线程，
    // 整个窗口在用户选完目录前都表现为未响应。
    rfd::AsyncFileDialog::new()
        .set_title("选择角色资源文件夹")
        .pick_folder()
        .await
        .map(|folder| folder.path().to_string_lossy().into_owned())
}

#[tauri::command]
pub async fn pet_pick_import_file() -> Option<String> {
    rfd::AsyncFileDialog::new()
        .set_title("选择角色资源或 .sundaypet")
        .add_filter("Sunday 角色包", &["sundaypet", "zip"])
        .add_filter("图片/模型", &["png", "jpg", "jpeg", "webp", "glb", "gltf"])
        .pick_file()
        .await
        .map(|file| file.path().to_string_lossy().into_owned())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_path_traversal() {
        assert!(normalize_rel("../secret.png").is_err());
        assert!(normalize_rel("a/../../b.png").is_err());
        assert!(normalize_rel("C:/windows/x.png").is_err());
        assert!(normalize_rel("a/b.png").is_ok());
    }

    #[test]
    fn capture_timeout_forces_passthrough() {
        assert!(!capture_timed_out(None::<Instant>));
        assert!(!capture_timed_out(Some(Instant::now())));
        assert!(capture_timed_out(Some(
            Instant::now() - CAPTURE_HOLD_LIMIT - Duration::from_secs(1)
        )));
    }

    #[test]
    fn pack_id_sanitizes_dangerous_names() {
        assert_eq!(sanitize_pack_id("My Pet").unwrap(), "my-pet");
        assert!(sanitize_pack_id("..").is_err());
        assert!(sanitize_pack_id("   ").is_err());
        // 带 ".." 的名字直接拒绝，而不是"清理后凑一个"。
        assert!(sanitize_pack_id("a/../b").is_err());
        assert_eq!(sanitize_pack_id("arc-ball").unwrap(), "arc-ball");
    }

    #[test]
    fn hit_test_respects_rect_bounds() {
        let rect = [10.0, 10.0, 20.0, 20.0];
        assert!(point_in_rect(10, 10, &rect));
        assert!(point_in_rect(30, 30, &rect));
        assert!(!point_in_rect(31, 30, &rect));
    }

    #[test]
    fn asset_whitelist_blocks_scripts() {
        assert!(ALLOWED_ASSET_EXTS.contains(&"png"));
        assert!(!ALLOWED_ASSET_EXTS.contains(&"js"));
        assert!(!ALLOWED_ASSET_EXTS.contains(&"py"));
        assert!(!ALLOWED_ASSET_EXTS.contains(&"exe"));
    }

    #[test]
    fn open_flag_accepts_pet_and_open_pet_aliases() {
        let on = |flags: &[&str]| {
            let args: Vec<String> = flags.iter().map(|flag| flag.to_string()).collect();
            open_requested_from(&args, None)
        };
        assert!(on(&["--pet"]));
        assert!(on(&["Sunday.exe", "--pet"]));
        assert!(on(&["--open-pet"]));
        // 相近写法不能误触发，没给参数也不能触发。
        assert!(!on(&["--no-pet"]));
        assert!(!on(&["--pet=1"]));
        assert!(!on(&[]));
        // 环境变量通道只认 "1"。
        assert!(open_requested_from(&[], Some("1")));
        assert!(!open_requested_from(&[], Some("0")));
        assert!(!open_requested_from(&[], None));
        // 命令行与环境变量任一命中即可。
        assert!(open_requested_from(&["--pet".to_string()], Some("0")));
    }

    #[test]
    fn browser_args_keep_baseline_and_merge_injected_args() {
        let merged = browser_args(Some("--remote-debugging-port=0 --enable-automation"));
        assert!(merged.contains("--remote-debugging-port=0"));
        assert!(merged.contains("--enable-automation"));
        // 应用默认参数要保留（否则行为和正常模式不一致）。
        assert!(merged.contains("--disable-features=msWebOOUI,msPdfOOUI,msSmartScreenProtection"));
        assert!(merged.contains("--autoplay-policy=no-user-gesture-required"));
        // 没有注入时仍然返回基线参数：所有窗口必须用同一份 WebView2 参数。
        for args in [browser_args(None), browser_args(Some("")), browser_args(Some("   "))] {
            assert_eq!(args, BASE_BROWSER_ARGS);
        }
    }

    #[test]
    fn bounded_asset_reads_inside_root_and_rejects_traversal() {
        // user:"左下角确实有个诊断，但是我没看见方块人啊"+
        // (修复前 root 未规范化，Windows canonicalize 的 \\?\ 长前缀让所有包内
        //  资源读取都被误判"资源路径越界"——方块人加载不出任何外观。)
        let root = std::env::temp_dir().join(format!("sunday-pet-asset-{}", std::process::id()));
        let dir = root.join("skins");
        std::fs::create_dir_all(&dir).expect("create test pack dir");
        std::fs::write(dir.join("skin.png"), b"png-bytes").expect("write test skin");
        let bytes = read_bounded_asset_bytes(&root, "skins/skin.png")
            .expect("包内资源必须可读（Windows 长路径前缀不得导致误判越界）");
        assert_eq!(bytes, b"png-bytes");
        assert!(read_bounded_asset_bytes(&root, "../outside.png").is_err());
        assert!(read_bounded_asset_bytes(&root, "skins/evil.exe").is_err());
        std::fs::remove_dir_all(&root).ok();
    }
}
