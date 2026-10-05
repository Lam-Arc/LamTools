//! Windows session and close requests.
//!
//! Closing the main window hides it to the tray, which is the intended
//! behaviour for a user click but wrong for the requests the system makes when
//! it needs the program to go away: logoff, shutdown, and the Restart Manager
//! shutdown an installer sends before it replaces the program's files.
//! Swallowing those would leave the app running, and its files locked, while
//! the session ends or an update is installed.

use std::{
    collections::HashMap,
    sync::{LazyLock, Mutex},
};

use tauri::{Manager, WebviewWindow};
use windows_sys::Win32::{
    Foundation::{HWND, LPARAM, LRESULT, WPARAM},
    UI::{
        Shell::{DefSubclassProc, RemoveWindowSubclass, SetWindowSubclass},
        WindowsAndMessaging::{WM_ENDSESSION, WM_NCDESTROY, WM_QUERYENDSESSION},
    },
};

const SUBCLASS_ID: usize = 0x4c_41_4d_43_4c_4f_53; // "LAMCLOS"

struct CloseRequest {
    window: WebviewWindow,
}

// HWNDs are only used on the UI thread. The mutex is required because Windows
// calls the window procedure through a global function pointer.
unsafe impl Send for CloseRequest {}

static WINDOWS: LazyLock<Mutex<HashMap<isize, CloseRequest>>> =
    LazyLock::new(|| Mutex::new(HashMap::new()));

pub fn install(window: &WebviewWindow) -> Result<(), String> {
    let hwnd = window
        .hwnd()
        .map_err(|error| format!("main window handle unavailable: {error}"))?
        .0 as HWND;

    WINDOWS
        .lock()
        .map_err(|_| "system close state poisoned".to_string())?
        .insert(
            hwnd as isize,
            CloseRequest {
                window: window.clone(),
            },
        );

    if unsafe { SetWindowSubclass(hwnd, Some(subclass_proc), SUBCLASS_ID, 0) } == 0 {
        WINDOWS
            .lock()
            .map_err(|_| "system close state poisoned".to_string())?
            .remove(&(hwnd as isize));
        return Err("failed to attach the system close handler".to_string());
    }
    Ok(())
}

/// True when the message says the system needs the app to shut down, rather
/// than the user closing a window. Both session ends and an installer's
/// Restart Manager shutdown arrive here; a plain window close must keep
/// hiding to the tray, so it is deliberately excluded.
fn is_system_quit_request(message: u32, wparam: WPARAM) -> bool {
    match message {
        WM_QUERYENDSESSION => true,
        WM_ENDSESSION => wparam != 0,
        _ => false,
    }
}

fn take_window(hwnd: HWND) -> Option<WebviewWindow> {
    WINDOWS
        .lock()
        .ok()?
        .remove(&(hwnd as isize))
        .map(|request| request.window)
}

fn forget_window(hwnd: HWND) {
    if let Ok(mut windows) = WINDOWS.lock() {
        windows.remove(&(hwnd as isize));
    }
}

fn quit_in_background(window: WebviewWindow) {
    let app = window.app_handle().clone();
    // Quitting destroys this window, so it cannot run inside its own window
    // procedure; the desktop shell owns the graceful shutdown sequence.
    std::thread::spawn(move || crate::request_quit(&app));
}

unsafe extern "system" fn subclass_proc(
    hwnd: HWND,
    message: u32,
    wparam: WPARAM,
    lparam: LPARAM,
    _subclass_id: usize,
    _ref_data: usize,
) -> LRESULT {
    if is_system_quit_request(message, wparam) {
        // Claim the request once: it must not be answered twice, and the
        // window disappears with the quit that follows.
        if let Some(window) = take_window(hwnd) {
            quit_in_background(window);
        }
        // A session end has to be accepted, or Windows keeps waiting on us.
        return 1;
    }
    if message == WM_NCDESTROY {
        unsafe { RemoveWindowSubclass(hwnd, Some(subclass_proc), SUBCLASS_ID) };
        forget_window(hwnd);
    }
    unsafe { DefSubclassProc(hwnd, message, wparam, lparam) }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn system_requests_quit_the_app() {
        assert!(is_system_quit_request(WM_QUERYENDSESSION, 0));
        assert!(is_system_quit_request(WM_ENDSESSION, 1));
    }

    #[test]
    fn a_user_window_close_stays_with_the_tray_handler() {
        // WM_CLOSE: the window event handler decides, and hides the window.
        assert!(!is_system_quit_request(0x0010, 1));
        assert!(!is_system_quit_request(WM_ENDSESSION, 0));
        assert!(!is_system_quit_request(WM_NCDESTROY, 0));
    }
}
