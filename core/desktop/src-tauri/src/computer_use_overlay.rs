//! Computer Use 覆盖层：全屏透明窗口，画操作边框、提示条和 Agent 光标。
//!
//! user:“覆盖层说明 Sunday 正在操作你的电脑，esc 或点击此处以停止，覆盖层做成一个
//! 4px 的有流动感的黯彩边框以表明此处被操作中”+(覆盖层只负责显示和两个停止入口，
//! 任务状态和动作都由后端决定，窗口本身不抢焦点、不挡鼠标)。

use std::sync::{
    atomic::{AtomicBool, AtomicU64, Ordering},
    Mutex,
};
use std::thread;
use std::time::Duration;

use tauri::{
    AppHandle, Manager, PhysicalPosition, PhysicalSize, WebviewUrl, WebviewWindowBuilder,
};

use crate::pet::browser_args_from_env;
use crate::pet::platform;
use crate::pet::OverlayBounds;

pub const OVERLAY_LABEL: &str = "computer-use-overlay";

/// 交互矩形与穿透状态。页面把提示条的位置报上来，轮询线程据此决定这一帧
/// 覆盖层吃不吃鼠标：只有提示条区域可点，其余全部穿透。
pub struct OverlayState {
    rects: Mutex<Vec<[f64; 4]>>,
    ignoring: AtomicBool,
    /// 建窗代际：每次重新打开加一，上一轮的轮询线程看到代际变了就退出。
    generation: AtomicU64,
}

impl Default for OverlayState {
    fn default() -> Self {
        Self {
            rects: Mutex::new(Vec::new()),
            ignoring: AtomicBool::new(true),
            generation: AtomicU64::new(0),
        }
    }
}

impl OverlayState {
    /// 建窗代际：旧轮询线程据此退出。
    fn next_generation(&self) -> u64 {
        self.generation.fetch_add(1, Ordering::SeqCst) + 1
    }
}

#[tauri::command]
pub async fn computer_use_overlay_open(app: AppHandle) -> Result<OverlayBounds, String> {
    if app.try_state::<OverlayState>().is_none() {
        app.manage(OverlayState::default());
    }
    let generation = app.state::<OverlayState>().next_generation();
    if let Some(window) = app.get_webview_window(OVERLAY_LABEL) {
        let _ = window.destroy();
        // 与标注层一致：WebView2 刚销毁窗口时偶尔建出半成品，给事件循环一点时间。
        thread::sleep(Duration::from_millis(120));
    }

    let bounds = platform::virtual_screen_bounds()?;
    let window = WebviewWindowBuilder::new(
        &app,
        OVERLAY_LABEL,
        WebviewUrl::App("computer-use.html".into()),
    )
    .title("Sunday Computer Use")
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
    .map_err(|error| format!("create computer use overlay failed: {error}"))?;

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
    let _ = window.set_ignore_cursor_events(true);
    #[cfg(windows)]
    if let Err(error) = platform::configure_overlay_window(&window) {
        eprintln!("[computer-use] overlay styling skipped: {error}");
    }

    start_polling(app.clone(), generation);
    Ok(bounds)
}

/// 页面画出第一帧后调用：到这一步才显示窗口，避免全屏黑块。
#[tauri::command]
pub async fn computer_use_overlay_ready(app: AppHandle) -> Result<(), String> {
    let window = app
        .get_webview_window(OVERLAY_LABEL)
        .ok_or_else(|| "computer use overlay is not open".to_string())?;
    window.show().map_err(|error| error.to_string())?;
    Ok(())
}

#[tauri::command]
pub async fn computer_use_overlay_close(app: AppHandle) -> Result<(), String> {
    if let Some(window) = app.get_webview_window(OVERLAY_LABEL) {
        let _ = window.close();
    }
    Ok(())
}

/// 页面报上来的可点击区域，物理像素屏幕坐标。
#[tauri::command]
pub fn computer_use_overlay_set_rects(app: AppHandle, rects: Vec<[f64; 4]>) -> Result<(), String> {
    let Some(state) = app.try_state::<OverlayState>() else {
        return Err("computer use overlay is not open".to_string());
    };
    let mut slot = state
        .rects
        .lock()
        .map_err(|_| "computer use rect lock failed".to_string())?;
    *slot = rects
        .into_iter()
        .filter(|rect| rect[2] > 0.5 && rect[3] > 0.5)
        .collect();
    Ok(())
}

#[tauri::command]
pub fn computer_use_overlay_heartbeat(app: AppHandle) {
    let _ = app;
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
            if !window.is_visible().unwrap_or(false) {
                thread::sleep(Duration::from_millis(120));
                continue;
            }
            #[cfg(windows)]
            {
                let esc = platform::escape_down();
                if esc && !esc_was_down {
                    // 先关窗再上报：后端没响应时不能让整屏覆盖层继续盖着桌面。
                    let _ = window.close();
                    let handle = app.clone();
                    thread::spawn(move || request_stop(&handle, "用户按 Esc 停止"));
                    break;
                }
                esc_was_down = esc;
                update_click_through(&app, &window);
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

/// 让后端把任务标成结束。覆盖层自己不做业务判断，只发这个请求。
fn request_stop(app: &AppHandle, reason: &str) {
    let Some(state) = app.try_state::<crate::BackendState>() else {
        return;
    };
    let base = state
        .api_base
        .lock()
        .ok()
        .and_then(|value| value.clone());
    let Some(base) = base else {
        return;
    };
    let body = serde_json::json!({"action": "stop", "reason": reason}).to_string();
    let _ = ureq::post(&format!("{base}/api/core/computer-use/control"))
        .header("Content-Type", "application/json")
        .send(body.as_str());
}
