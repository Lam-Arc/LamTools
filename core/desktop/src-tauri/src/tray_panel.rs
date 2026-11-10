//! 托盘自绘面板：点托盘图标在图标旁边弹出一张 Sunday 风格的小卡片。
//!
//! user:“托盘样式重做”“只做自绘面板”+(Windows 原生托盘菜单不能改配色和圆角，
//! 于是换成独立的小窗口：面板内容和开关状态由页面画，宿主只负责建窗、贴边定位、
//! 失焦收起，以及把面板上的动作接到真实的桌宠/标注层/退出路径上。)

use std::sync::atomic::{AtomicBool, Ordering};

use tauri::{AppHandle, LogicalSize, Manager, WebviewUrl, WebviewWindowBuilder};

use crate::{desktop_overlay, pet};

pub const TRAY_PANEL_LABEL: &str = "tray-panel";

/// 面板逻辑尺寸：页面按这个宽度排版，换 DPI 也不会把文案挤变形。
pub const PANEL_WIDTH: f64 = 264.0;
pub const PANEL_HEIGHT: f64 = 248.0;

/// 面板与工作区边缘的最小距离。
const EDGE_MARGIN: i32 = 8;
/// 面板与托盘图标之间的缝隙。
const ANCHOR_GAP: i32 = 6;
/// 面板右边越过光标的距离，让面板看起来从图标长出来。
const ANCHOR_OVERLAP: i32 = 16;

/// 自动化/CLI 入口：带 `--tray-panel` 或 `SUNDAY_TRAY_PANEL_OPEN=1` 启动时直接把面板弹出来。
///
/// user:“每个 GUI 能力都要有对应的 CLI 能力”+(托盘点击没法被脚本模拟，
/// 面板本身必须有命令行入口，验证和排查才不用碰真实托盘图标)。
pub fn open_requested_from(args: &[String], panel_open_env: Option<&str>) -> bool {
    args.iter().any(|arg| arg == "--tray-panel")
        || panel_open_env.map(|value| value == "1").unwrap_or(false)
}

pub fn open_requested() -> bool {
    let args: Vec<String> = std::env::args().collect();
    open_requested_from(&args, std::env::var("SUNDAY_TRAY_PANEL_OPEN").ok().as_deref())
}

#[derive(Default)]
pub struct TrayPanelState {
    /// 面板当前是否真的显示着：失焦收起只对已显示的面板生效。
    visible: AtomicBool,
    /// 因为失焦自动收起的时刻：紧接着的托盘点击是“要关”的同一次点击，不能再打开。
    auto_hidden_at: std::sync::Mutex<Option<std::time::Instant>>,
    /// 窗口材质："mica" 交给系统，"solid" 由页面画不透明底色。
    material: std::sync::Mutex<String>,
    /// 最近一次弹出位置（屏幕物理像素），尺寸变化后按它重新贴边。
    last_anchor: std::sync::Mutex<Option<(i32, i32)>>,
    /// 我们自己触发开窗时的失焦免打扰截止时刻：开桌宠/标注层会把焦点带走。
    suppress_blur_until: std::sync::Mutex<Option<std::time::Instant>>,
    /// 前台看护线程只起一次。
    watch_started: AtomicBool,
    /// 面板是否已经真的拿到过前台：没拿到之前不做“点外面收起”，避免刚弹出就被自己收掉。
    seen_foreground: AtomicBool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct WorkArea {
    pub x: i32,
    pub y: i32,
    pub width: i32,
    pub height: i32,
}

/// 面板左上角（物理像素）：贴着托盘图标内侧展开，先朝上再朝下，始终留在工作区内。
///
/// 任务栏在下就往上长，任务栏在上就往下长；靠右靠左都会被夹回工作区，
/// 副屏在负坐标区时也不会算到屏幕外面。
pub fn panel_origin(anchor: (i32, i32), size: (i32, i32), work: WorkArea) -> (i32, i32) {
    let (anchor_x, anchor_y) = anchor;
    let (width, height) = (size.0.max(1), size.1.max(1));

    let min_x = work.x + EDGE_MARGIN;
    let max_x = work.x + work.width - width - EDGE_MARGIN;
    let min_y = work.y + EDGE_MARGIN;
    let max_y = work.y + work.height - height - EDGE_MARGIN;

    let raw_x = anchor_x - width + ANCHOR_OVERLAP;
    let x = if max_x < min_x {
        min_x
    } else {
        raw_x.clamp(min_x, max_x)
    };

    let above = anchor_y - height - ANCHOR_GAP;
    let below = anchor_y + ANCHOR_GAP;
    let raw_y = if above >= min_y {
        above
    } else if below <= max_y {
        below
    } else {
        above
    };
    let y = if max_y < min_y {
        min_y
    } else {
        raw_y.clamp(min_y, max_y)
    };

    (x, y)
}

// ---------------------------------------------------------------------------
// 窗口生命周期
// ---------------------------------------------------------------------------

fn panel_state(app: &AppHandle) -> tauri::State<'_, TrayPanelState> {
    if app.try_state::<TrayPanelState>().is_none() {
        app.manage(TrayPanelState::default());
    }
    app.state::<TrayPanelState>()
}

/// 建立（或复用）面板窗口。返回窗口实际物理尺寸，定位要用它而不是逻辑值。
fn ensure_panel(app: &AppHandle) -> Result<(u32, u32), String> {
    if let Some(window) = app.get_webview_window(TRAY_PANEL_LABEL) {
        if let Ok(size) = window.inner_size() {
            return Ok((size.width, size.height));
        }
        // WebView2 偶尔建出半成品窗口：销毁重来，别把用户锁在一个空窗上。
        let _ = window.destroy();
        std::thread::sleep(std::time::Duration::from_millis(120));
    }

    let window = WebviewWindowBuilder::new(app, TRAY_PANEL_LABEL, WebviewUrl::App("tray.html".into()))
        .title("Sunday 托盘面板")
        .decorations(false)
        .resizable(false)
        .maximizable(false)
        .minimizable(false)
        .closable(false)
        .focused(false)
        .visible(false)
        .transparent(true)
        .background_color(tauri::window::Color(0, 0, 0, 0))
        // 阴影交给系统：和 Ping 卡片、主窗口同一套观感。
        .shadow(true)
        .skip_taskbar(true)
        .additional_browser_args(&pet::browser_args_from_env())
        .build()
        .map_err(|error| format!("create tray panel failed: {error}"))?;

    window
        .set_size(LogicalSize::new(PANEL_WIDTH, PANEL_HEIGHT))
        .map_err(|error| error.to_string())?;
    let _ = window.set_always_on_top(true);

    // user:“这个东西就没必要搞半透明了吧，你撑死搞个云母”+(面板不要自己调透明度：
    // 能用系统云母就用系统云母，用不了就退回页面画的不透明卡片。)
    #[cfg(windows)]
    let material = apply_system_backdrop(&window);
    #[cfg(not(windows))]
    let material = "solid".to_string();
    if let Ok(mut slot) = panel_state(app).material.lock() {
        *slot = material;
    }

    // user:“点面板外面要收起”+(这个 webview 窗口不派发 Focused 事件，
    // 只能看护前台窗口：250ms 一次，面板是前台就没事，换成别的窗口就收起。)
    start_foreground_watch(app);

    let size = window.inner_size().map_err(|error| error.to_string())?;
    Ok((size.width, size.height))
}

pub fn is_open(app: &AppHandle) -> bool {
    panel_state(app).visible.load(Ordering::SeqCst)
}

fn hide(window: &tauri::WebviewWindow, app: &AppHandle) {
    let _ = window.hide();
    panel_state(app).visible.store(false, Ordering::SeqCst);
}

/// 失焦自动收起：记下发时刻，供紧接着的托盘点击判断“这一次是要关”。
fn auto_hide(app: &AppHandle) {
    let state = panel_state(app);
    if let Ok(mut slot) = state.auto_hidden_at.lock() {
        *slot = Some(std::time::Instant::now());
    }
    close(app);
}

/// 前台看护：面板显示期间，前台不是面板就收起。
fn start_foreground_watch(app: &AppHandle) {
    let state = panel_state(app);
    if state.watch_started.swap(true, Ordering::SeqCst) {
        return;
    }
    let handle = app.clone();
    let spawned = std::thread::Builder::new()
        .name("tray-panel-watch".into())
        .spawn(move || loop {
            std::thread::sleep(std::time::Duration::from_millis(250));
            if handle.try_state::<TrayPanelState>().is_none() {
                return;
            }
            if !is_open(&handle) || blur_suppressed(&handle) {
                continue;
            }
            let Some(window) = handle.get_webview_window(TRAY_PANEL_LABEL) else {
                continue;
            };
            let Ok(panel_hwnd) = window.hwnd() else {
                continue;
            };
            let Some(foreground) = foreground_window() else {
                continue;
            };
            if foreground == panel_hwnd.0 as isize {
                panel_state(&handle)
                    .seen_foreground
                    .store(true, Ordering::SeqCst);
                continue;
            }
            // 从没拿到过前台（例如前台锁挡住了）就不要自作主张收起，
            // 否则面板会刚出现就闪掉。
            if !panel_state(&handle).seen_foreground.load(Ordering::SeqCst) {
                continue;
            }
            // 面板自己开桌宠/标注层时前台会变成自家覆盖层，那不是“点外面”；
            // 但主界面是用户主动切过去的，要按点外面处理。
            let main_hwnd = handle
                .get_webview_window("main")
                .and_then(|window| window.hwnd().ok())
                .map(|hwnd| hwnd.0 as isize);
            if Some(foreground) != main_hwnd && foreground_owner_pid(foreground) == Some(std::process::id()) {
                continue;
            }
            auto_hide(&handle);
        });
    if let Err(error) = spawned {
        eprintln!("[tray-panel] foreground watch failed: {error}");
    }
}

/// 自己触发的开窗会给焦点带来一次跳转，这段时间内的失焦不算“点外面”。
fn blur_suppressed(app: &AppHandle) -> bool {
    panel_state(app)
        .suppress_blur_until
        .lock()
        .ok()
        .and_then(|slot| *slot)
        .map(|until| std::time::Instant::now() < until)
        .unwrap_or(false)
}

fn suppress_blur_for(app: &AppHandle, duration: std::time::Duration) {
    if let Ok(mut slot) = panel_state(app).suppress_blur_until.lock() {
        *slot = Some(std::time::Instant::now() + duration);
    }
}

/// 刚刚因为失焦收起过（同一次点击的按下和抬起之间）。
fn recently_auto_hidden(app: &AppHandle) -> bool {
    panel_state(app)
        .auto_hidden_at
        .lock()
        .ok()
        .and_then(|slot| *slot)
        .map(|at| at.elapsed() < std::time::Duration::from_millis(400))
        .unwrap_or(false)
}

/// 在给定屏幕坐标处展开面板；已经开着就收起。
pub fn toggle_at(app: &AppHandle, anchor: (i32, i32)) {
    let state = panel_state(app);
    if state.visible.load(Ordering::SeqCst) {
        close(app);
        return;
    }
    // 托盘点击先让面板失焦（自动收起），同一次点击随后才到这里：
    // 这时不应该再打开，否则面板永远关不掉。
    if recently_auto_hidden(app) {
        return;
    }
    match open_at(app, anchor) {
        Ok(()) => {}
        Err(error) => eprintln!("[tray-panel] open failed: {error}"),
    }
}

fn open_at(app: &AppHandle, anchor: (i32, i32)) -> Result<(), String> {
    let (width, height) = ensure_panel(app)?;
    if let Ok(mut slot) = panel_state(app).last_anchor.lock() {
        *slot = Some(anchor);
    }
    let work = work_area_at(anchor);
    let (x, y) = panel_origin(anchor, (width as i32, height as i32), work);
    let window = app
        .get_webview_window(TRAY_PANEL_LABEL)
        .ok_or_else(|| "tray panel window missing".to_string())?;
    // 摆位复用桌宠覆盖层那套"设置后读回再修正"：125% 缩放下系统会把物理像素
    // 再乘一次比例，直接 set_position 会落到屏幕另一处。
    pet::place_overlay(
        &window,
        &pet::OverlayBounds {
            x,
            y,
            width: width as i32,
            height: height as i32,
            scale: 1.0,
        },
    )?;
    let state = panel_state(app);
    state.visible.store(true, Ordering::SeqCst);
    state.seen_foreground.store(false, Ordering::SeqCst);
    window.show().map_err(|error| error.to_string())?;
    // 托盘点击是给 Explorer 的输入，直接 SetForegroundWindow 常被前台锁挡掉；
    // 用附加输入线程的老办法把焦点抢过来，面板才能收到 Esc 和点外面收起。
    if let Ok(hwnd) = window.hwnd() {
        force_foreground(hwnd.0 as isize);
    }
    let _ = window.set_focus();
    Ok(())
}

pub fn close(app: &AppHandle) {
    if let Some(window) = app.get_webview_window(TRAY_PANEL_LABEL) {
        hide(&window, app);
    } else {
        panel_state(app).visible.store(false, Ordering::SeqCst);
    }
}

// ---------------------------------------------------------------------------
// 面板动作：全部走真实的桌宠/标注层/退出路径，不另写一套
// ---------------------------------------------------------------------------

fn toggle_pet_now(app: &AppHandle) -> Result<bool, String> {
    if pet::overlay_is_open(app) {
        pet::close_overlay_sync(app)?;
        Ok(false)
    } else {
        pet::open_overlay_and_poll(app.clone())?;
        Ok(true)
    }
}

fn toggle_overlay_now(app: &AppHandle) -> Result<bool, String> {
    if desktop_overlay::is_open(app) {
        desktop_overlay::close_sync(app)?;
        Ok(false)
    } else {
        tauri::async_runtime::block_on(desktop_overlay::desktop_overlay_open(app.clone()))?;
        Ok(true)
    }
}

// ---------------------------------------------------------------------------
// 命令
// ---------------------------------------------------------------------------

#[tauri::command]
pub fn tray_panel_state(app: AppHandle) -> serde_json::Value {
    serde_json::json!({
        "pet_open": pet::overlay_is_open(&app),
        "overlay_open": desktop_overlay::is_open(&app),
        "panel_open": is_open(&app),
    })
}

/// 打开面板：默认贴着光标，也接受指定屏幕坐标（快捷键/自动化入口）。
#[tauri::command]
pub fn tray_panel_open(app: AppHandle, x: Option<i32>, y: Option<i32>) -> Result<(), String> {
    let anchor = match (x, y) {
        (Some(x), Some(y)) => (x, y),
        _ => crate::pet::platform::cursor_position().unwrap_or((0, 0)),
    };
    open_at(&app, anchor)
}

/// 页面按自己的真实排版把窗口调到刚好装下。
///
/// user:“这个东西就没必要搞半透明了吧，你撑死搞个云母”+(窗口尺寸不能按逻辑像素猜：
/// 系统缩放和 WebView 的 devicePixelRatio 可能对不上，猜出来的窗口会把内容裁掉。
/// 页面报 CSS 尺寸和 dpr，宿主换算成物理像素，再按原锚点重新贴边。)
#[tauri::command]
pub fn tray_panel_fit(
    app: AppHandle,
    width: f64,
    height: f64,
    dpr: f64,
) -> Result<(), String> {
    let window = app
        .get_webview_window(TRAY_PANEL_LABEL)
        .ok_or_else(|| "tray panel window missing".to_string())?;
    let dpr = if dpr.is_finite() && dpr >= 0.5 { dpr } else { 1.0 };
    let physical_width = (width.max(120.0) * dpr).round().clamp(160.0, 900.0) as u32;
    let physical_height = (height.max(120.0) * dpr).round().clamp(160.0, 1200.0) as u32;
    let anchor = panel_state(&app)
        .last_anchor
        .lock()
        .ok()
        .and_then(|slot| *slot)
        .unwrap_or((0, 0));
    let work = work_area_at(anchor);
    let (x, y) = panel_origin(anchor, (physical_width as i32, physical_height as i32), work);
    pet::place_overlay(
        &window,
        &pet::OverlayBounds {
            x,
            y,
            width: physical_width as i32,
            height: physical_height as i32,
            scale: 1.0,
        },
    )?;
    Ok(())
}

/// 页面据此决定要不要自己画不透明底色：云母可用时页面保持透明。
#[tauri::command]
pub fn tray_panel_material(app: AppHandle) -> String {
    panel_state(&app)
        .material
        .lock()
        .map(|slot| slot.clone())
        .unwrap_or_else(|_| "solid".to_string())
}

#[tauri::command]
pub fn tray_panel_close(app: AppHandle) {
    close(&app);
}

/// 面板里的开关只认 "pet" / "overlay"，其它值直接拒绝。
///
/// 开窗要建 WebView2，放到独立线程里做：命令立刻返回，页面轮询到真实状态，
/// 既不卡住面板，也不在 IPC 回调线程里碰窗口 API。
#[tauri::command]
pub fn tray_panel_toggle(app: AppHandle, target: String) -> Result<(), String> {
    if target != "pet" && target != "overlay" {
        return Err(format!("unknown tray target: {target}"));
    }
    // 开覆盖层会把焦点从面板带走，先给这次失焦开个免打扰。
    suppress_blur_for(&app, std::time::Duration::from_millis(3000));
    let handle = app.clone();
    std::thread::Builder::new()
        .name("tray-panel-toggle".into())
        .spawn(move || {
            let result = if target == "pet" {
                toggle_pet_now(&handle)
            } else {
                toggle_overlay_now(&handle)
            };
            if let Err(error) = result {
                eprintln!("[tray-panel] toggle {target} failed: {error}");
            }
        })
        .map(|_| ())
        .map_err(|error| error.to_string())
}

#[tauri::command]
pub fn tray_panel_reveal_main(app: AppHandle) {
    close(&app);
    crate::reveal_main_window(&app);
}

#[tauri::command]
pub fn tray_panel_quit(app: AppHandle) {
    // 先收面板再退出，免得留一块贴在任务栏旁边的空窗。
    close(&app);
    crate::request_quit(&app);
}

// ---------------------------------------------------------------------------
// 平台：光标所在显示器的工作区（扣掉任务栏）
// ---------------------------------------------------------------------------

/// 当前前台窗口句柄（顶层窗口），拿不到返回 None。
#[cfg(windows)]
fn foreground_window() -> Option<isize> {
    use windows_sys::Win32::UI::WindowsAndMessaging::GetForegroundWindow;

    unsafe {
        let hwnd = GetForegroundWindow();
        if hwnd.is_null() {
            None
        } else {
            Some(hwnd as isize)
        }
    }
}

#[cfg(not(windows))]
fn foreground_window() -> Option<isize> {
    None
}

/// 把窗口强制提到前台：AttachThreadInput 绕开前台锁。
#[cfg(windows)]
fn force_foreground(hwnd: isize) {
    use windows_sys::Win32::System::Threading::{AttachThreadInput, GetCurrentThreadId};
    use windows_sys::Win32::UI::WindowsAndMessaging::{
        BringWindowToTop, GetForegroundWindow, GetWindowThreadProcessId, SetForegroundWindow,
    };

    unsafe {
        let target = hwnd as windows_sys::Win32::Foundation::HWND;
        let foreground = GetForegroundWindow();
        if foreground.is_null() {
            let _ = SetForegroundWindow(target);
            return;
        }
        let foreground_thread = GetWindowThreadProcessId(foreground, std::ptr::null_mut());
        let current_thread = GetCurrentThreadId();
        if foreground_thread != 0 && foreground_thread != current_thread {
            AttachThreadInput(current_thread, foreground_thread, 1);
            let _ = SetForegroundWindow(target);
            let _ = BringWindowToTop(target);
            AttachThreadInput(current_thread, foreground_thread, 0);
        } else {
            let _ = SetForegroundWindow(target);
        }
    }
}

#[cfg(not(windows))]
fn force_foreground(_hwnd: isize) {}

/// 窗口所属进程：判断前台是不是自家窗口。
#[cfg(windows)]
fn foreground_owner_pid(hwnd: isize) -> Option<u32> {
    use windows_sys::Win32::UI::WindowsAndMessaging::GetWindowThreadProcessId;

    unsafe {
        let mut pid = 0u32;
        GetWindowThreadProcessId(hwnd as windows_sys::Win32::Foundation::HWND, &mut pid);
        if pid == 0 {
            None
        } else {
            Some(pid)
        }
    }
}

#[cfg(not(windows))]
fn foreground_owner_pid(_hwnd: isize) -> Option<u32> {
    None
}

/// 系统材质：Windows 11 用云母，其它情况退回"页面自己画不透明底"。
///
/// 顺带把窗口圆角交给 DWM，云母背景才会跟着圆角一起被裁，而不是留一圈方角。
#[cfg(windows)]
fn apply_system_backdrop(window: &tauri::WebviewWindow) -> String {
    use tauri::window::{Effect, EffectsBuilder};

    // user:“也不用刻意去做圆角”+(不设 DWM 圆角偏好，窗口就是系统默认的方角)。
    let applied = window
        .set_effects(EffectsBuilder::new().effect(Effect::Mica).build())
        .is_ok();
    if applied { "mica".to_string() } else { "solid".to_string() }
}

#[cfg(windows)]
pub fn work_area_at(anchor: (i32, i32)) -> WorkArea {
    use std::mem::{size_of, zeroed};
    use windows_sys::Win32::Foundation::POINT;
    use windows_sys::Win32::Graphics::Gdi::{
        GetMonitorInfoW, MonitorFromPoint, MONITORINFOEXW, MONITOR_DEFAULTTONEAREST,
    };

    unsafe {
        let hmon = MonitorFromPoint(
            POINT {
                x: anchor.0,
                y: anchor.1,
            },
            MONITOR_DEFAULTTONEAREST,
        );
        if !hmon.is_null() {
            let mut info: MONITORINFOEXW = zeroed();
            info.monitorInfo.cbSize = size_of::<MONITORINFOEXW>() as u32;
            if GetMonitorInfoW(hmon, &mut info.monitorInfo as *mut _) != 0 {
                let work = info.monitorInfo.rcWork;
                return WorkArea {
                    x: work.left,
                    y: work.top,
                    width: (work.right - work.left).max(1),
                    height: (work.bottom - work.top).max(1),
                };
            }
        }
    }
    // 拿不到显示器信息时退化成“以光标为右下的一个大工作区”，面板仍然出现在光标附近。
    WorkArea {
        x: anchor.0 - 1920,
        y: anchor.1 - 1080,
        width: 1920,
        height: 1080,
    }
}

#[cfg(not(windows))]
pub fn work_area_at(anchor: (i32, i32)) -> WorkArea {
    // 非 Windows 只保证能编译：托盘面板是桌面端能力。
    WorkArea {
        x: anchor.0 - 1920,
        y: anchor.1 - 1080,
        width: 1920,
        height: 1080,
    }
}

#[cfg(test)]
mod tests {
    use super::{panel_origin, WorkArea};

    fn work(x: i32, y: i32, width: i32, height: i32) -> WorkArea {
        WorkArea {
            x,
            y,
            width,
            height,
        }
    }

    #[test]
    fn bottom_taskbar_panel_opens_above_the_anchor() {
        // 2560×1440 屏幕、任务栏在下方，图标在右下角。
        // 靠边时 6px 的图标缝隙让位给 8px 的工作区内边距：面板底边不贴死任务栏。
        let (x, y) = panel_origin((2500, 1400), (264, 248), work(0, 0, 2560, 1400));
        assert_eq!(x, 2252);
        assert_eq!(y, 1400 - 248 - 8);
        assert!(y + 248 < 1400);
    }

    #[test]
    fn top_taskbar_panel_opens_below_the_anchor() {
        // 任务栏在顶部：上方放不下，就改朝下长。
        let (x, y) = panel_origin((100, 10), (264, 248), work(0, 0, 2560, 1400));
        assert_eq!(y, 16);
        assert_eq!(x, 8);
    }

    #[test]
    fn panel_never_leaves_the_work_area_on_the_right_edge() {
        let (x, _) = panel_origin((2559, 1400), (264, 248), work(0, 0, 2560, 1400));
        assert_eq!(x, 2560 - 264 - 8);
    }

    #[test]
    fn secondary_monitor_in_negative_coordinates_stays_inside() {
        // 副屏在主屏左边，x 为负。
        let area = work(-1920, 0, 1920, 1080);
        let (x, y) = panel_origin((-1910, 1000), (264, 248), area);
        assert_eq!(x, -1920 + 8);
        assert_eq!(y, 1000 - 248 - 6);
    }

    #[test]
    fn cli_and_env_can_request_the_panel() {
        use super::open_requested_from;
        assert!(open_requested_from(&["sunday".into(), "--tray-panel".into()], None));
        assert!(open_requested_from(&["sunday".into()], Some("1")));
        assert!(!open_requested_from(&["sunday".into()], Some("0")));
        assert!(!open_requested_from(&["sunday".into(), "--open-overlay".into()], None));
    }

    #[test]
    fn workspace_smaller_than_panel_still_produces_inside_point() {
        let area = work(0, 0, 200, 200);
        let (x, y) = panel_origin((180, 190), (264, 248), area);
        assert_eq!((x, y), (8, 8));
    }
}
