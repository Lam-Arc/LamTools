//! Windows 11 Snap Layout support for the frameless main window.
//!
//! WebView2 owns the client-area mouse messages, so subclassing the Tauri
//! parent window cannot produce `HTMAXBUTTON`. A transparent native child
//! window is kept directly above the HTML maximize button instead. Windows
//! sees that child as the maximize hit target while the page still draws the
//! control itself.

use std::{
    collections::HashMap,
    sync::{LazyLock, Mutex},
};

use tauri::{Emitter, WebviewWindow};
use windows_sys::Win32::{
    Foundation::{HINSTANCE, HWND, LPARAM, LRESULT, WPARAM},
    Graphics::Gdi::{GetStockObject, HBRUSH, NULL_BRUSH},
    System::LibraryLoader::GetModuleHandleW,
    UI::{
        HiDpi::GetDpiForWindow,
        Input::KeyboardAndMouse::{TrackMouseEvent, TME_LEAVE, TME_NONCLIENT, TRACKMOUSEEVENT},
        Shell::{DefSubclassProc, RemoveWindowSubclass, SetWindowSubclass},
        WindowsAndMessaging::{
            CreateWindowExW, DefWindowProcW, DestroyWindow, GetClientRect, RegisterClassExW,
            SetWindowPos, CS_HREDRAW, CS_VREDRAW, HTMAXBUTTON, HWND_TOP, SWP_ASYNCWINDOWPOS,
            SWP_NOACTIVATE, SWP_SHOWWINDOW, WM_DPICHANGED, WM_NCDESTROY, WM_NCHITTEST,
            WM_NCLBUTTONDOWN, WM_NCLBUTTONUP, WM_NCMOUSELEAVE, WM_NCMOUSEMOVE, WM_SIZE,
            WNDCLASSEXW, WS_CHILD, WS_CLIPSIBLINGS, WS_OVERLAPPED, WS_VISIBLE,
        },
    },
};

pub const EVENT_HOVER: &str = "lamtools://window/maximize-hover";
pub const EVENT_PRESS: &str = "lamtools://window/maximize-press";
pub const EVENT_CLICK: &str = "lamtools://window/maximize-click";

const SUBCLASS_ID: usize = 0x4c_41_4d_53_4e_41_50;
const SNAP_CLASS: &[u16] = &[
    b'L' as u16,
    b'a' as u16,
    b'm' as u16,
    b'T' as u16,
    b'o' as u16,
    b'o' as u16,
    b'l' as u16,
    b's' as u16,
    b'S' as u16,
    b'n' as u16,
    b'a' as u16,
    b'p' as u16,
    b'O' as u16,
    b'v' as u16,
    b'e' as u16,
    b'r' as u16,
    b'l' as u16,
    b'a' as u16,
    b'y' as u16,
    0,
];

#[derive(Clone, Copy, Default)]
struct LogicalBounds {
    right: f64,
    top: f64,
    width: f64,
    height: f64,
}

struct SnapState {
    overlay: HWND,
    bounds: LogicalBounds,
    hovering: bool,
    pressing: bool,
    window: WebviewWindow,
}

// HWND is only used on the UI thread. The mutex is required because Windows
// calls the window procedures through global function pointers.
unsafe impl Send for SnapState {}

static SNAP_WINDOWS: LazyLock<Mutex<HashMap<isize, SnapState>>> =
    LazyLock::new(|| Mutex::new(HashMap::new()));

pub fn install(window: &WebviewWindow) -> Result<(), String> {
    let hwnd = window
        .hwnd()
        .map_err(|error| format!("main window handle unavailable: {error}"))?
        .0 as HWND;

    unsafe { install_hwnd(hwnd, window.clone()) }
}

pub fn set_button_bounds(
    window: &WebviewWindow,
    x: f64,
    top: f64,
    width: f64,
    height: f64,
) -> Result<(), String> {
    if ![x, top, width, height].into_iter().all(f64::is_finite)
        || x < 0.0
        || top < 0.0
        || width <= 0.0
        || height <= 0.0
    {
        return Err("invalid maximize button bounds".to_string());
    }

    let hwnd = window
        .hwnd()
        .map_err(|error| format!("main window handle unavailable: {error}"))?
        .0 as HWND;

    let client_width = unsafe { logical_client_width(hwnd)? };
    let right = (client_width - x - width).max(0.0);

    let mut states = SNAP_WINDOWS
        .lock()
        .map_err(|_| "snap layout state poisoned".to_string())?;
    let state = states
        .get_mut(&(hwnd as isize))
        .ok_or_else(|| "snap layout overlay is not installed".to_string())?;
    state.bounds = LogicalBounds {
        right,
        top,
        width,
        height,
    };
    drop(states);

    unsafe { update_overlay_position(hwnd) };
    Ok(())
}

unsafe fn install_hwnd(hwnd: HWND, window: WebviewWindow) -> Result<(), String> {
    register_class();

    let overlay = unsafe {
        CreateWindowExW(
            0,
            SNAP_CLASS.as_ptr(),
            SNAP_CLASS.as_ptr(),
            WS_CHILD | WS_VISIBLE | WS_CLIPSIBLINGS | WS_OVERLAPPED,
            0,
            0,
            0,
            0,
            hwnd,
            std::ptr::null_mut(),
            module_instance(),
            std::ptr::null(),
        )
    };
    if overlay.is_null() {
        return Err("failed to create maximize hit-test overlay".to_string());
    }

    SNAP_WINDOWS
        .lock()
        .map_err(|_| "snap layout state poisoned".to_string())?
        .insert(
            hwnd as isize,
            SnapState {
                overlay,
                bounds: LogicalBounds::default(),
                hovering: false,
                pressing: false,
                window,
            },
        );

    if unsafe { SetWindowSubclass(hwnd, Some(parent_subclass_proc), SUBCLASS_ID, 0) } == 0 {
        SNAP_WINDOWS
            .lock()
            .map_err(|_| "snap layout state poisoned".to_string())?
            .remove(&(hwnd as isize));
        unsafe { DestroyWindow(overlay) };
        return Err("failed to attach maximize hit-test overlay".to_string());
    }

    Ok(())
}

unsafe fn register_class() {
    let class = WNDCLASSEXW {
        cbSize: std::mem::size_of::<WNDCLASSEXW>() as u32,
        style: CS_HREDRAW | CS_VREDRAW,
        lpfnWndProc: Some(overlay_proc),
        cbClsExtra: 0,
        cbWndExtra: 0,
        hInstance: unsafe { module_instance() },
        hIcon: std::ptr::null_mut(),
        hCursor: std::ptr::null_mut(),
        hbrBackground: unsafe { GetStockObject(NULL_BRUSH) } as HBRUSH,
        lpszMenuName: std::ptr::null(),
        lpszClassName: SNAP_CLASS.as_ptr(),
        hIconSm: std::ptr::null_mut(),
    };
    unsafe { RegisterClassExW(&class) };
}

unsafe fn module_instance() -> HINSTANCE {
    unsafe { GetModuleHandleW(std::ptr::null()) }
}

unsafe fn logical_client_width(hwnd: HWND) -> Result<f64, String> {
    let mut rect = std::mem::zeroed();
    if unsafe { GetClientRect(hwnd, &mut rect) } == 0 {
        return Err("failed to read main window bounds".to_string());
    }
    let dpi = unsafe { GetDpiForWindow(hwnd) }.max(96);
    Ok((rect.right - rect.left) as f64 * 96.0 / dpi as f64)
}

unsafe fn update_overlay_position(hwnd: HWND) {
    let Ok(states) = SNAP_WINDOWS.lock() else {
        return;
    };
    let Some(state) = states.get(&(hwnd as isize)) else {
        return;
    };
    if state.bounds.width <= 0.0 || state.bounds.height <= 0.0 {
        return;
    }

    let mut rect = std::mem::zeroed();
    if unsafe { GetClientRect(hwnd, &mut rect) } == 0 {
        return;
    }
    let dpi = unsafe { GetDpiForWindow(hwnd) }.max(96) as f64;
    let scale = dpi / 96.0;
    let width = (state.bounds.width * scale).round().max(1.0) as i32;
    let height = (state.bounds.height * scale).round().max(1.0) as i32;
    let right = (state.bounds.right * scale).round().max(0.0) as i32;
    let top = (state.bounds.top * scale).round().max(0.0) as i32;
    let x = rect.right - right - width;

    unsafe {
        SetWindowPos(
            state.overlay,
            HWND_TOP,
            x,
            top,
            width,
            height,
            SWP_ASYNCWINDOWPOS | SWP_NOACTIVATE | SWP_SHOWWINDOW,
        )
    };
}

fn emit(parent: HWND, event: &'static str, payload: bool) {
    let target = SNAP_WINDOWS.lock().ok().and_then(|states| {
        states
            .get(&(parent as isize))
            .map(|state| state.window.clone())
    });
    if let Some(window) = target {
        let _ = window.emit(event, payload);
    }
}

unsafe fn parent_for_overlay(overlay: HWND) -> Option<HWND> {
    SNAP_WINDOWS.lock().ok().and_then(|states| {
        states
            .iter()
            .find_map(|(parent, state)| (state.overlay == overlay).then_some(*parent as HWND))
    })
}

unsafe extern "system" fn parent_subclass_proc(
    hwnd: HWND,
    msg: u32,
    wparam: WPARAM,
    lparam: LPARAM,
    _subclass_id: usize,
    _ref_data: usize,
) -> LRESULT {
    match msg {
        WM_SIZE | WM_DPICHANGED => unsafe { update_overlay_position(hwnd) },
        WM_NCDESTROY => {
            unsafe { RemoveWindowSubclass(hwnd, Some(parent_subclass_proc), SUBCLASS_ID) };
            if let Ok(mut states) = SNAP_WINDOWS.lock() {
                states.remove(&(hwnd as isize));
            }
        }
        _ => {}
    }

    unsafe { DefSubclassProc(hwnd, msg, wparam, lparam) }
}

unsafe extern "system" fn overlay_proc(
    hwnd: HWND,
    msg: u32,
    wparam: WPARAM,
    lparam: LPARAM,
) -> LRESULT {
    match msg {
        WM_NCHITTEST => return HTMAXBUTTON as LRESULT,
        WM_NCMOUSEMOVE => {
            if let Some(parent) = unsafe { parent_for_overlay(hwnd) } {
                let entered = SNAP_WINDOWS
                    .lock()
                    .ok()
                    .and_then(|mut states| {
                        states.get_mut(&(parent as isize)).map(|state| {
                            let entered = !state.hovering;
                            state.hovering = true;
                            entered
                        })
                    })
                    .unwrap_or(false);
                if entered {
                    emit(parent, EVENT_HOVER, true);
                }

                let mut track = TRACKMOUSEEVENT {
                    cbSize: std::mem::size_of::<TRACKMOUSEEVENT>() as u32,
                    dwFlags: TME_LEAVE | TME_NONCLIENT,
                    hwndTrack: hwnd,
                    dwHoverTime: 0,
                };
                unsafe { TrackMouseEvent(&mut track) };
            }
            return 0;
        }
        WM_NCMOUSELEAVE => {
            if let Some(parent) = unsafe { parent_for_overlay(hwnd) } {
                if let Ok(mut states) = SNAP_WINDOWS.lock() {
                    if let Some(state) = states.get_mut(&(parent as isize)) {
                        state.hovering = false;
                        state.pressing = false;
                    }
                }
                emit(parent, EVENT_HOVER, false);
                emit(parent, EVENT_PRESS, false);
            }
            return 0;
        }
        WM_NCLBUTTONDOWN => {
            if let Some(parent) = unsafe { parent_for_overlay(hwnd) } {
                if let Ok(mut states) = SNAP_WINDOWS.lock() {
                    if let Some(state) = states.get_mut(&(parent as isize)) {
                        state.pressing = true;
                    }
                }
                emit(parent, EVENT_PRESS, true);
            }
            return 0;
        }
        WM_NCLBUTTONUP => {
            if let Some(parent) = unsafe { parent_for_overlay(hwnd) } {
                let clicked = SNAP_WINDOWS
                    .lock()
                    .ok()
                    .and_then(|mut states| {
                        states.get_mut(&(parent as isize)).map(|state| {
                            let clicked = state.pressing;
                            state.pressing = false;
                            clicked
                        })
                    })
                    .unwrap_or(false);
                emit(parent, EVENT_PRESS, false);
                if clicked {
                    emit(parent, EVENT_CLICK, true);
                }
            }
            return 0;
        }
        _ => {}
    }

    unsafe { DefWindowProcW(hwnd, msg, wparam, lparam) }
}
