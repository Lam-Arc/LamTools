//! Desktop Overlay 标注层：全屏透明窗口，把 Agent 与用户的标记画在真实桌面上。
//!
//! user:“AI 直接在屏幕上标记、绘制、互动：箭头、框选、高亮、涂鸦、文字…
//! 标记可跟随窗口和对象，用户能直接点击、圈选、批注，与 Agent 实时互动。”
//! +(窗口只负责显示和收集圈选；标记内容与批注由 Core 的 /overlay/state 提供，
//!   这一层不做业务判断，也不抢焦点。)
//!
//! 兜底和 Computer Use 覆盖层同一套：默认整屏穿透，只有页面报上来的可点区域
//! 吃鼠标；Esc 直接收起；页面心跳停了就销毁窗口，避免一块没人画的透明窗
//! 永久盖住桌面。

use std::sync::{
    atomic::{AtomicBool, AtomicU64, Ordering},
    Mutex,
};
use std::thread;
use std::time::{Duration, Instant};

use tauri::{
    AppHandle, Emitter, Manager, PhysicalPosition, PhysicalSize, WebviewUrl, WebviewWindowBuilder,
};

use crate::pet::browser_args_from_env;
use crate::pet::platform;
use crate::pet::OverlayBounds;

pub const OVERLAY_LABEL: &str = "desktop-overlay";

/// 自动化/开发入口：带 --overlay 或 --open-overlay，或 SUNDAY_OVERLAY_OPEN=1
/// 启动时直接把标注层打开，不依赖托盘点击。
pub fn open_requested_from(args: &[String], overlay_open_env: Option<&str>) -> bool {
    args.iter().any(|arg| arg == "--overlay" || arg == "--open-overlay")
        || overlay_open_env.map(|value| value == "1").unwrap_or(false)
}

pub fn open_requested() -> bool {
    let args: Vec<String> = std::env::args().collect();
    open_requested_from(&args, std::env::var("SUNDAY_OVERLAY_OPEN").ok().as_deref())
}

/// 圈选请求事件：热键按下时推给页面，页面直接进入框选态。
pub const CAPTURE_EVENT: &str = "overlay://capture";

/// 默认圈选快捷键。和 Ping 的 Ctrl+Alt+Space 一样是全局键，可在桌宠设置里改。
pub const DEFAULT_CAPTURE_HOTKEY: &str = "Ctrl+Alt+A";

/// 设置变更事件：设置页改完弹幕参数后通知页面重读。
pub const SETTINGS_EVENT: &str = "overlay://settings";

/// 弹幕显示参数（速度倍率、字体族、字号）。
#[derive(Clone, Debug, PartialEq)]
pub struct DanmakuSettings {
    pub speed: f64,
    pub font: String,
    pub size: f64,
}

impl Default for DanmakuSettings {
    fn default() -> Self {
        Self {
            speed: 1.0,
            font: String::new(),
            size: 24.0,
        }
    }
}

/// 配置里的弹幕参数：缺项用默认，越界值夹回可用范围。
///
/// user:“设置中支持调节倍速、字体、字号”+(页面只拿最终值，界面上不出现
/// 0 倍速或 200 号字这类把弹幕弄没的配置)。
pub fn danmaku_settings_from_config(config: &serde_json::Value) -> DanmakuSettings {
    let raw = config.get("overlay").and_then(|value| value.get("danmaku"));
    let speed = raw
        .and_then(|value| value.get("speed"))
        .and_then(|value| value.as_f64())
        .unwrap_or(1.0)
        .clamp(0.3, 3.0);
    let size = raw
        .and_then(|value| value.get("fontSize"))
        .and_then(|value| value.as_f64())
        .unwrap_or(24.0)
        .clamp(12.0, 64.0);
    let font = raw
        .and_then(|value| value.get("fontFamily"))
        .and_then(|value| value.as_str())
        .unwrap_or("")
        .to_string();
    DanmakuSettings { speed, font, size }
}

/// 从桌宠配置里取圈选快捷键：没配用默认，配成空串表示解绑。
///
/// user:“没必要搞那个圈选批注的键，就是把它的入口设成跟 ping 一样就行”+
/// (入口从工具条按钮换成全局热键，配置位置和 Ping 那一条并排)。
pub fn capture_hotkey_from_config(config: &serde_json::Value) -> Option<String> {
    let raw = config
        .get("overlay")
        .and_then(|value| value.get("captureHotkey"))
        .and_then(|value| value.as_str());
    match raw {
        Some(text) if text.trim().is_empty() => None,
        Some(text) => Some(text.trim().to_string()),
        None => Some(DEFAULT_CAPTURE_HOTKEY.to_string()),
    }
}

/// 页面停止心跳多久就认定它死了。标注层没有“看门狗重启”的必要，
/// 直接销毁窗口，用户从托盘再打开即可。
const HEARTBEAT_TIMEOUT: Duration = Duration::from_secs(10);

/// 新窗口从建出来到页面第一次报心跳的宽限。超时还没报过心跳才算死，
/// 免得一个加载失败的页面把不可见的全屏窗口永远留在桌面上。
const LOAD_GRACE: Duration = Duration::from_secs(20);

/// 判死规则：报过心跳的会话按心跳超时判，还没报过的会话按加载宽限判。
///
/// user:“对代码进行审查，不要出错或者低级漏洞或问题”+(上一次会话的旧心跳
/// 留在状态里，重开窗口时页面还没加载完就被判死，表现为交互层关掉一会儿再按
/// 热键打不开；判死只能看当前这次会话的时间)。
fn session_is_dead(
    ever_seen: bool,
    heartbeat_age: Option<Duration>,
    open_age: Option<Duration>,
) -> bool {
    if ever_seen {
        return heartbeat_age.map_or(true, |age| age > HEARTBEAT_TIMEOUT);
    }
    open_age.map_or(false, |age| age > LOAD_GRACE)
}

pub struct OverlayState {
    rects: Mutex<Vec<[f64; 4]>>,
    ignoring: AtomicBool,
    heartbeat: Mutex<Option<Instant>>,
    ever_seen: AtomicBool,
    /// 这次会话开始建窗的时间：给“页面还没报过心跳”的窗口算加载宽限。
    opened_at: Mutex<Option<Instant>>,
    /// 批注输入条是否正在等键盘：为真时全局 Esc 不关窗，交给页面取消输入。
    annotating: AtomicBool,
    /// 圈选全局热键（解析后）。
    capture_hotkey: Mutex<Option<platform::HotkeySpec>>,
    /// 热键已经按过、页面还没来取的那一次圈选请求。
    capture_pending: AtomicBool,
    /// 热键轮询只起一次。
    capture_watch: AtomicBool,
    /// 正在为圈选请求建窗：连按热键时不重复建窗。
    capture_opening: AtomicBool,
    /// 建窗代际：每次重新打开加一，上一轮的轮询线程看到代际变了就退出。
    generation: AtomicU64,
}

impl Default for OverlayState {
    fn default() -> Self {
        Self {
            rects: Mutex::new(Vec::new()),
            ignoring: AtomicBool::new(true),
            heartbeat: Mutex::new(None),
            ever_seen: AtomicBool::new(false),
            opened_at: Mutex::new(None),
            annotating: AtomicBool::new(false),
            capture_hotkey: Mutex::new(None),
            capture_pending: AtomicBool::new(false),
            capture_watch: AtomicBool::new(false),
            capture_opening: AtomicBool::new(false),
            generation: AtomicU64::new(0),
        }
    }
}

impl OverlayState {
    /// 每次建窗都从零开始计时：旧会话的心跳不能带进新窗口。
    fn begin_session(&self) {
        if let Ok(mut slot) = self.heartbeat.lock() {
            *slot = None;
        }
        self.ever_seen.store(false, Ordering::SeqCst);
        if let Ok(mut slot) = self.opened_at.lock() {
            *slot = Some(Instant::now());
        }
    }

    /// 建窗代际：旧轮询线程据此退出。
    fn next_generation(&self) -> u64 {
        self.generation.fetch_add(1, Ordering::SeqCst) + 1
    }

    /// 窗口销毁时顺手清掉会话状态，下次打开是干净的一轮。
    fn end_session(&self) {
        if let Ok(mut slot) = self.heartbeat.lock() {
            *slot = None;
        }
        self.ever_seen.store(false, Ordering::SeqCst);
        if let Ok(mut slot) = self.opened_at.lock() {
            *slot = None;
        }
    }
}

fn ensure_state(app: &AppHandle) -> tauri::State<'_, OverlayState> {
    if app.try_state::<OverlayState>().is_none() {
        app.manage(OverlayState::default());
    }
    app.state::<OverlayState>()
}

#[tauri::command]
pub async fn desktop_overlay_open(app: AppHandle) -> Result<OverlayBounds, String> {
    let state = ensure_state(&app);
    // user:“对代码进行审查，不要出错或者低级漏洞或问题”+(不复位的话，关掉交互层
    // 超过心跳超时再打开，新窗口会被上一轮的旧心跳判死，表现为再也打不开)。
    state.begin_session();
    let generation = state.next_generation();
    if let Some(window) = app.get_webview_window(OVERLAY_LABEL) {
        let _ = window.destroy();
        // WebView2 刚销毁一个覆盖层窗口时偶尔建出半成品，给事件循环一点时间。
        thread::sleep(Duration::from_millis(120));
    }

    let bounds = platform::virtual_screen_bounds()?;
    let window = WebviewWindowBuilder::new(&app, OVERLAY_LABEL, WebviewUrl::App("overlay.html".into()))
        .title("Sunday Overlay")
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
        .additional_browser_args(&browser_args_from_env())
        .build()
        .map_err(|error| format!("create desktop overlay failed: {error}"))?;

    window
        .set_position(PhysicalPosition::new(bounds.x, bounds.y))
        .map_err(|error| error.to_string())?;
    window
        .set_size(PhysicalSize::new(
            bounds.width.max(1) as u32,
            bounds.height.max(1) as u32,
        ))
        .map_err(|error| error.to_string())?;
    let _ = window.set_always_on_top(true);
    // 页面算出可点区域之前，覆盖层绝不能挡住桌面。
    let _ = window.set_ignore_cursor_events(true);
    #[cfg(windows)]
    if let Err(error) = platform::configure_overlay_window(&window) {
        eprintln!("[overlay] window styling skipped: {error}");
    }

    start_polling(app.clone(), generation);
    Ok(bounds)
}

/// 页面启动时读虚拟桌面边界。窗口由宿主建好，这里只返回几何，不重建窗口。
#[tauri::command]
pub async fn desktop_overlay_bounds(app: AppHandle) -> Result<OverlayBounds, String> {
    ensure_state(&app);
    platform::virtual_screen_bounds()
}

/// 页面画出第一帧后调用：到这一步才显示窗口，避免全屏黑块。
#[tauri::command]
pub async fn desktop_overlay_ready(app: AppHandle) -> Result<(), String> {
    let state = ensure_state(&app);
    if let Ok(mut slot) = state.heartbeat.lock() {
        *slot = Some(Instant::now());
    }
    state.ever_seen.store(true, Ordering::SeqCst);
    let window = app
        .get_webview_window(OVERLAY_LABEL)
        .ok_or_else(|| "desktop overlay is not open".to_string())?;
    window.show().map_err(|error| error.to_string())?;
    Ok(())
}

#[tauri::command]
pub async fn desktop_overlay_close(app: AppHandle) -> Result<(), String> {
    if let Some(window) = app.get_webview_window(OVERLAY_LABEL) {
        let _ = window.close();
    }
    Ok(())
}

/// 页面报上来的可点区域，物理像素屏幕坐标。标注本身不吃点击，
/// 只有文字标签、批注输入条和圈选状态会报矩形。
#[tauri::command]
pub fn desktop_overlay_set_rects(app: AppHandle, rects: Vec<[f64; 4]>) -> Result<(), String> {
    let state = ensure_state(&app);
    let mut slot = state
        .rects
        .lock()
        .map_err(|_| "desktop overlay rect lock failed".to_string())?;
    *slot = rects
        .into_iter()
        .filter(|rect| rect[2] > 0.5 && rect[3] > 0.5)
        .collect();
    #[cfg(debug_assertions)]
    eprintln!("[overlay] rects={} first={:?}", slot.len(), slot.first());
    Ok(())
}

/// 批注输入条出现时临时让覆盖层可激活并拿到键盘焦点。
///
/// user:“用户能直接点击、圈选、批注，与 Agent 实时互动”+(覆盖层默认
/// WS_EX_NOACTIVATE，键盘输入根本进不来；输入期间去掉该位，收起输入条后恢复。
/// 输入期间也不让全局 Esc 关窗，Esc 只取消这次批注)。
#[tauri::command]
pub fn desktop_overlay_set_activatable(app: AppHandle, active: bool) -> Result<(), String> {
    let state = ensure_state(&app);
    state.annotating.store(active, Ordering::SeqCst);
    let window = app
        .get_webview_window(OVERLAY_LABEL)
        .ok_or_else(|| "desktop overlay is not open".to_string())?;
    platform::set_overlay_activatable(&window, active)?;
    if active {
        let _ = window.set_focus();
        // 父窗口到前台还不够：键盘消息要落到 WebView2 的渲染子窗口。
        let _ = platform::focus_webview_child(&window);
    }
    Ok(())
}

/// 诊断：页面报上来的可点区域、穿透状态与心跳，用来排查“看得见点不到”。
#[tauri::command]
pub fn desktop_overlay_debug_state(app: AppHandle) -> serde_json::Value {
    let state = ensure_state(&app);
    let rects = state.rects.lock().map(|value| value.clone()).unwrap_or_default();
    let heartbeat = state
        .heartbeat
        .lock()
        .ok()
        .and_then(|value| *value)
        .map(|at| at.elapsed().as_secs_f64())
        .unwrap_or(-1.0);
    let window = app.get_webview_window(OVERLAY_LABEL);
    serde_json::json!({
        "rects": rects,
        "ignoring": state.ignoring.load(Ordering::SeqCst),
        "ever_seen": state.ever_seen.load(Ordering::SeqCst),
        "heartbeat_age": heartbeat,
        "visible": window.as_ref().map(|w| w.is_visible().unwrap_or(false)).unwrap_or(false),
        "inner_size": window.as_ref().and_then(|w| w.inner_size().ok()).map(|s| [s.width, s.height]),
    })
}

#[tauri::command]
pub fn desktop_overlay_heartbeat(app: AppHandle) {
    let state = ensure_state(&app);
    if let Ok(mut slot) = state.heartbeat.lock() {
        *slot = Some(Instant::now());
    }
    state.ever_seen.store(true, Ordering::SeqCst);
}

/// 页面读弹幕参数。
#[tauri::command]
pub fn desktop_overlay_settings() -> serde_json::Value {
    let settings = crate::pet::read_config_json()
        .map(|config| danmaku_settings_from_config(&config))
        .unwrap_or_default();
    serde_json::json!({
        "danmaku_speed": settings.speed,
        "danmaku_font": settings.font,
        "danmaku_size": settings.size,
    })
}

/// 设置页改完通知交互层重读，不用重启窗口。
#[tauri::command]
pub fn desktop_overlay_settings_changed(app: AppHandle) {
    let _ = app.emit_to(OVERLAY_LABEL, SETTINGS_EVENT, ());
}

/// 设置圈选热键：空串表示解绑，非法组合直接报错。
#[tauri::command]
pub fn desktop_overlay_capture_hotkey_set(
    app: AppHandle,
    accelerator: Option<String>,
) -> Result<(), String> {
    apply_capture_hotkey(&app, accelerator.as_deref())
}

/// 页面挂载时取一次挂起的圈选请求：热键先按、页面后加载的情况在这里补上。
#[tauri::command]
pub fn desktop_overlay_take_capture(app: AppHandle) -> bool {
    ensure_state(&app).capture_pending.swap(false, Ordering::SeqCst)
}

fn apply_capture_hotkey(app: &AppHandle, accelerator: Option<&str>) -> Result<(), String> {
    let state = ensure_state(app);
    let parsed = match accelerator {
        Some(text) if !text.trim().is_empty() => Some(platform::parse_hotkey(text)?),
        _ => None,
    };
    eprintln!(
        "[overlay] capture hotkey set: {}",
        parsed
            .as_ref()
            .map(|spec| format!("{} mods={} vk=0x{:x}", spec.accelerator, spec.modifiers, spec.vk))
            .unwrap_or_else(|| "none".to_string())
    );
    let mut slot = state
        .capture_hotkey
        .lock()
        .map_err(|_| "overlay capture hotkey lock failed".to_string())?;
    *slot = parsed;
    Ok(())
}

/// 启动热键轮询：和 Ping 一样用全局轮询，按键时任意位置都能触发。
pub fn start_capture_watch(app: &AppHandle) {
    let state = ensure_state(app);
    if state.capture_watch.swap(true, Ordering::SeqCst) {
        return;
    }
    let accelerator = crate::pet::read_config_json()
        .as_ref()
        .and_then(capture_hotkey_from_config);
    let parsed = accelerator.as_deref().and_then(|text| platform::parse_hotkey(text).ok());
    eprintln!(
        "[overlay] capture hotkey: {}",
        parsed
            .as_ref()
            .map(|spec| spec.accelerator.clone())
            .unwrap_or_else(|| "none".to_string())
    );
    if let Ok(mut slot) = state.capture_hotkey.lock() {
        *slot = parsed;
    }
    let handle = app.clone();
    thread::spawn(move || {
        let mut was_down = false;
        loop {
            thread::sleep(Duration::from_millis(80));
            let Some(state) = handle.try_state::<OverlayState>() else {
                return;
            };
            let spec = state.capture_hotkey.lock().ok().and_then(|value| value.clone());
            let down = spec.map(|spec| platform::hotkey_active(&spec)).unwrap_or(false);
            if down && !was_down {
                request_capture(&handle);
            }
            was_down = down;
        }
    });
}

fn request_capture(app: &AppHandle) {
    let state = ensure_state(app);
    let ready = state.ever_seen.load(Ordering::SeqCst)
        && app
            .get_webview_window(OVERLAY_LABEL)
            .map(|window| window.is_visible().unwrap_or(false))
            .unwrap_or(false);
    if ready {
        state.capture_pending.store(false, Ordering::SeqCst);
        if let Err(error) = app.emit_to(OVERLAY_LABEL, CAPTURE_EVENT, ()) {
            eprintln!("[overlay] capture event failed: {error}");
        }
        return;
    }
    // 层没开或页面还没就绪：先开窗，页面挂载后会自己来取这次请求。
    state.capture_pending.store(true, Ordering::SeqCst);
    if state.capture_opening.swap(true, Ordering::SeqCst) {
        // 已经有一次建窗在进行，等它跑完就行，别重复建窗。
        return;
    }
    let handle = app.clone();
    thread::spawn(move || {
        let result = tauri::async_runtime::block_on(desktop_overlay_open(handle.clone()));
        if let Some(state) = handle.try_state::<OverlayState>() {
            state.capture_opening.store(false, Ordering::SeqCst);
        }
        match result {
            Ok(_) => {
                // 页面可能已经挂好了：再推一次，重复的请求由页面自己去重。
                let _ = handle.emit_to(OVERLAY_LABEL, CAPTURE_EVENT, ());
            }
            Err(error) => eprintln!("[overlay] capture hotkey open failed: {error}"),
        }
    });
}

pub fn is_open(app: &AppHandle) -> bool {
    app.get_webview_window(OVERLAY_LABEL)
        .map(|window| window.is_visible().unwrap_or(false))
        .unwrap_or(false)
}

pub fn close_sync(app: &AppHandle) -> Result<(), String> {
    if let Some(window) = app.get_webview_window(OVERLAY_LABEL) {
        window.close().map_err(|error| error.to_string())?;
    }
    if let Some(state) = app.try_state::<OverlayState>() {
        state.end_session();
    }
    Ok(())
}

fn start_polling(app: AppHandle, generation: u64) {
    thread::spawn(move || {
        let mut esc_was_down = false;
        loop {
            let Some(state) = app.try_state::<OverlayState>() else {
                break;
            };
            if state.generation.load(Ordering::SeqCst) != generation {
                break;
            }
            let Some(window) = app.get_webview_window(OVERLAY_LABEL) else {
                break;
            };
            let seen = state.ever_seen.load(Ordering::SeqCst);
            let last = state.heartbeat.lock().ok().and_then(|value| *value);
            let opened = state.opened_at.lock().ok().and_then(|value| *value);
            let dead = session_is_dead(
                seen,
                last.map(|at| at.elapsed()),
                opened.map(|at| at.elapsed()),
            );
            if dead {
                eprintln!("[overlay] page heartbeat stopped; closing the overlay");
                state.end_session();
                let _ = window.destroy();
                break;
            }
            if window.is_visible().unwrap_or(false) {
                #[cfg(windows)]
                {
                    let esc = platform::escape_down();
                    // 批注输入期间 Esc 只取消这次输入，页面自己处理；这里不关窗。
                    if esc && !esc_was_down && !state.annotating.load(Ordering::SeqCst) {
                        state.end_session();
                        let _ = window.close();
                        break;
                    }
                    esc_was_down = esc;
                    update_click_through(&app, &window);
                }
            }
            thread::sleep(Duration::from_millis(90));
        }
    });
}

#[cfg(windows)]
fn update_click_through(app: &AppHandle, window: &tauri::WebviewWindow) {
    let Some(state) = app.try_state::<OverlayState>() else {
        return;
    };
    let rects = state.rects.lock().map(|value| value.clone()).unwrap_or_default();
    let (cx, cy) = platform::cursor_position().unwrap_or((-1, -1));
    let inside = rects.iter().any(|rect| {
        let (x, y, w, h) = (rect[0], rect[1], rect[2], rect[3]);
        (cx as f64) >= x && (cx as f64) <= x + w && (cy as f64) >= y && (cy as f64) <= y + h
    });
    let want_ignore = !inside;
    if state.ignoring.swap(want_ignore, Ordering::SeqCst) != want_ignore {
        let _ = window.set_ignore_cursor_events(want_ignore);
    }
}

#[cfg(test)]
mod tests {
    use super::{
        capture_hotkey_from_config, session_is_dead, DEFAULT_CAPTURE_HOTKEY, HEARTBEAT_TIMEOUT,
        LOAD_GRACE,
    };
    use std::time::Duration;

    #[test]
    fn reopened_session_is_not_killed_by_stale_heartbeat() {
        // 复现过的缺陷：关掉交互层 12 秒后按热键，新窗口被上一轮的旧心跳判死。
        assert!(!session_is_dead(false, None, Some(Duration::from_millis(400))));
        // 反过来，同一份旧状态如果被当成当前会话，就会立刻误杀。
        assert!(session_is_dead(true, Some(Duration::from_secs(30)), None));
    }

    #[test]
    fn session_without_heartbeat_dies_after_load_grace() {
        assert!(!session_is_dead(false, None, Some(LOAD_GRACE - Duration::from_secs(1))));
        assert!(session_is_dead(false, None, Some(LOAD_GRACE + Duration::from_secs(1))));
        // 还没建窗就没有会话，不判死。
        assert!(!session_is_dead(false, None, None));
    }

    #[test]
    fn live_session_dies_only_after_heartbeat_timeout() {
        assert!(!session_is_dead(true, Some(Duration::from_secs(2)), Some(Duration::from_secs(2))));
        assert!(session_is_dead(
            true,
            Some(HEARTBEAT_TIMEOUT + Duration::from_secs(1)),
            Some(Duration::from_secs(60)),
        ));
    }

    #[test]
    fn capture_hotkey_falls_back_to_default_when_config_missing() {
        let config: serde_json::Value = serde_json::json!({});
        assert_eq!(
            capture_hotkey_from_config(&config).as_deref(),
            Some(DEFAULT_CAPTURE_HOTKEY)
        );
    }

    #[test]
    fn empty_capture_hotkey_unbinds_the_entry() {
        let config: serde_json::Value = serde_json::json!({ "overlay": { "captureHotkey": "" } });
        assert_eq!(capture_hotkey_from_config(&config), None);
    }

    #[test]
    fn custom_capture_hotkey_is_used_as_is() {
        let config: serde_json::Value =
            serde_json::json!({ "overlay": { "captureHotkey": " Ctrl+Shift+A " } });
        assert_eq!(
            capture_hotkey_from_config(&config).as_deref(),
            Some("Ctrl+Shift+A")
        );
    }

    #[test]
    fn danmaku_settings_default_and_clamped() {
        use super::{danmaku_settings_from_config, DanmakuSettings};
        let empty: serde_json::Value = serde_json::json!({});
        assert_eq!(danmaku_settings_from_config(&empty), DanmakuSettings::default());

        let wild: serde_json::Value =
            serde_json::json!({ "overlay": { "danmaku": { "speed": 99, "fontSize": 1, "fontFamily": "KaiTi" } } });
        let parsed = danmaku_settings_from_config(&wild);
        assert_eq!(parsed.speed, 3.0);
        assert_eq!(parsed.size, 12.0);
        assert_eq!(parsed.font, "KaiTi");
    }

    #[test]
    fn rect_hit_is_inclusive_on_edges() {
        let rects = [[10.0, 20.0, 100.0, 50.0]];
        let hit = |x: i32, y: i32| {
            rects.iter().any(|rect| {
                let (rx, ry, rw, rh) = (rect[0], rect[1], rect[2], rect[3]);
                (x as f64) >= rx && (x as f64) <= rx + rw && (y as f64) >= ry && (y as f64) <= ry + rh
            })
        };
        assert!(hit(10, 20));
        assert!(hit(110, 70));
        assert!(!hit(111, 70));
        assert!(!hit(9, 20));
    }
}
