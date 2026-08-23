#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod pet_position;

use std::{
    env,
    io::{Read, Write},
    net::{TcpListener, TcpStream},
    path::PathBuf,
    process::{Child, Command, Stdio},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
    thread,
    time::{Duration, Instant},
};

#[cfg(windows)]
use std::os::windows::process::CommandExt;

use tauri::{Emitter, Manager, WebviewUrl, WebviewWindowBuilder};

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x08000000;

struct BackendState {
    api_base: Mutex<Option<String>>,
    child: Mutex<Option<Child>>,
}

#[cfg(windows)]
struct NativePetDrag {
    active: Arc<AtomicBool>,
    hwnd: isize,
    anchor_x: f64,
    anchor_y: f64,
}

#[cfg(not(windows))]
struct NativePetDrag;

struct PetDragState {
    active: Mutex<Option<Arc<NativePetDrag>>>,
}

impl Default for PetDragState {
    fn default() -> Self {
        Self {
            active: Mutex::new(None),
        }
    }
}

#[cfg(windows)]
#[repr(C)]
struct NativeCursorPoint {
    x: i32,
    y: i32,
}

#[cfg(windows)]
#[link(name = "user32")]
extern "system" {
    fn GetCursorPos(point: *mut NativeCursorPoint) -> i32;
    fn GetDpiForWindow(hwnd: isize) -> u32;
    fn SetWindowPos(
        hwnd: isize,
        insert_after: isize,
        x: i32,
        y: i32,
        width: i32,
        height: i32,
        flags: u32,
    ) -> i32;
}

#[cfg(windows)]
const SWP_NOSIZE: u32 = 0x0001;
#[cfg(windows)]
const SWP_NOZORDER: u32 = 0x0004;
#[cfg(windows)]
const SWP_NOACTIVATE: u32 = 0x0010;

#[cfg(windows)]
fn native_cursor_position() -> Option<NativeCursorPoint> {
    let mut point = NativeCursorPoint { x: 0, y: 0 };
    let success = unsafe { GetCursorPos(&mut point) } != 0;
    success.then_some(point)
}

#[cfg(windows)]
fn move_native_pet_window(drag: &NativePetDrag, cursor: NativeCursorPoint) {
    let dpi = unsafe { GetDpiForWindow(drag.hwnd) }.max(1);
    let scale = f64::from(dpi) / 96.0;
    let anchor_x = (drag.anchor_x * scale).round() as i32;
    let anchor_y = (drag.anchor_y * scale).round() as i32;
    unsafe {
        let _ = SetWindowPos(
            drag.hwnd,
            0,
            cursor.x - anchor_x,
            cursor.y - anchor_y,
            0,
            0,
            SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE,
        );
    }
}

#[cfg(windows)]
fn stop_native_pet_drag(state: &PetDragState) {
    let drag = state.active.lock().ok().and_then(|mut active| active.take());
    if let Some(drag) = drag {
        drag.active.store(false, Ordering::Release);
        if let Some(cursor) = native_cursor_position() {
            move_native_pet_window(&drag, cursor);
        }
    }
}

#[tauri::command]
fn start_pet_drag(
    window: tauri::WebviewWindow,
    state: tauri::State<'_, PetDragState>,
    anchor_x: f64,
    anchor_y: f64,
) -> Result<(), String> {
    #[cfg(windows)]
    {
        let hwnd = window.hwnd().map_err(|error| error.to_string())?.0 as isize;
        stop_native_pet_drag(state.inner());
        let active = Arc::new(AtomicBool::new(true));
        let drag = Arc::new(NativePetDrag {
            active: active.clone(),
            hwnd,
            anchor_x,
            anchor_y,
        });
        state
            .active
            .lock()
            .map_err(|_| "pet drag state lock failed".to_string())?
            .replace(drag.clone());
        thread::spawn(move || {
            while active.load(Ordering::Acquire) {
                if let Some(cursor) = native_cursor_position() {
                    move_native_pet_window(&drag, cursor);
                }
                thread::sleep(Duration::from_millis(4));
            }
        });
    }
    #[cfg(not(windows))]
    {
        let _ = (window, state, anchor_x, anchor_y);
    }
    Ok(())
}

#[tauri::command]
fn stop_pet_drag(state: tauri::State<'_, PetDragState>) {
    #[cfg(windows)]
    stop_native_pet_drag(state.inner());
    #[cfg(not(windows))]
    let _ = state;
}

// ---------------------------------------------------------------------------
// Tauri commands exposed to the frontend
// ---------------------------------------------------------------------------

#[tauri::command]
fn get_api_base(state: tauri::State<'_, BackendState>) -> Result<String, String> {
    state
        .api_base
        .lock()
        .map_err(|_| "backend state lock failed".to_string())?
        .clone()
        .ok_or_else(|| "backend not yet started".to_string())
}

#[tauri::command]
fn minimize_window(window: tauri::WebviewWindow) {
    let _ = window.minimize();
}

#[tauri::command]
fn toggle_maximize_window(window: tauri::WebviewWindow) {
    let _ = if window.is_maximized().unwrap_or(false) {
        window.unmaximize()
    } else {
        window.maximize()
    };
}

#[tauri::command]
fn close_window(window: tauri::WebviewWindow) {
    let _ = window.close();
}

#[tauri::command]
fn get_window_label(window: tauri::WebviewWindow) -> String {
    window.label().to_string()
}

fn create_pet_windows(app: &tauri::AppHandle) -> Result<(), String> {
    let api_base = app
        .state::<BackendState>()
        .api_base
        .lock()
        .ok()
        .and_then(|value| value.clone());
    for label in ["pet", "pet-overlay"] {
        if app.get_webview_window(label).is_some() {
            continue;
        }
        let (width, height, transparent, shadow, visible) = if label == "pet" {
            // Visibility is decided only after the frontend has read the
            // persisted core.pet settings. Showing here causes an enabled
            // flash when the saved setting is false.
            (180.0, 180.0, true, false, false)
        } else {
            // Draw the rounded surface in the webview. A native opaque
            // window can leave mismatched white corner arcs on Windows.
            (360.0, 460.0, true, false, false)
        };
        let page = api_base
            .as_deref()
            .map(|base| format!("index.html?api_base={base}"))
            .unwrap_or_else(|| "index.html".to_string());
        WebviewWindowBuilder::new(app, label, WebviewUrl::App(page.into()))
            .title("LamTools Pet")
            .inner_size(width, height)
            .decorations(false)
            .transparent(transparent)
            .always_on_top(true)
            .skip_taskbar(true)
            .resizable(false)
            .focused(false)
            .visible(visible)
            .shadow(shadow)
            // The main window has additionalBrowserArgs. WebView2 rejects
            // creating another webview with incompatible browser arguments
            // in the shared default data directory, so each Pet surface gets
            // its own persistent profile directory.
            .data_directory(
                app.path()
                    .app_local_data_dir()
                    .map_err(|error| error.to_string())?
                    .join(format!("webview-{label}")),
            )
            .build()
            .map_err(|error| error.to_string())?;
    }
    Ok(())
}

#[tauri::command]
fn ensure_pet_windows(app: tauri::AppHandle) -> Result<(), String> {
    let handle = app.clone();
    std::thread::spawn(move || {
        if let Err(error) = create_pet_windows(&handle) {
            eprintln!("[lamcore] ensure_pet_windows failed: {error}");
        }
    });
    Ok(())
}

#[tauri::command]
fn focus_main_window(app: tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
    if let Some(overlay) = app.get_webview_window("pet-overlay") {
        let _ = overlay.hide();
    }
}

#[tauri::command]
fn is_main_window_focused(app: tauri::AppHandle) -> bool {
    app.get_webview_window("main")
        .and_then(|window| window.is_focused().ok())
        .unwrap_or(false)
}

#[tauri::command]
fn show_pet_overlay(app: tauri::AppHandle) -> Result<(), String> {
    let overlay = app
        .get_webview_window("pet-overlay")
        .ok_or_else(|| "pet overlay window is not ready".to_string())?;
    if let Some(pet) = app.get_webview_window("pet") {
        if let (Ok(position), Ok(size)) = (pet.outer_position(), pet.outer_size()) {
                let overlay_size = overlay
                    .outer_size()
                    .unwrap_or(tauri::PhysicalSize::new(360, 460));
                let desired_x = i64::from(position.x) + i64::from(size.width) + 8;
                let desired_y = i64::from(position.y);
                let (x, y) = if let Ok(Some(monitor)) = pet.current_monitor() {
                    let work_area = monitor.work_area();
                    let monitor_left = i64::from(work_area.position.x);
                    let monitor_top = i64::from(work_area.position.y);
                    let monitor_right = monitor_left + i64::from(work_area.size.width);
                    let monitor_bottom = monitor_top + i64::from(work_area.size.height);
                    let overlay_width = i64::from(overlay_size.width);
                    let overlay_height = i64::from(overlay_size.height);
                    crate::pet_position::anchored_overlay_position(
                        desired_x,
                        desired_y,
                        i64::from(position.x),
                        monitor_left,
                        monitor_top,
                        monitor_right,
                        monitor_bottom,
                        overlay_width,
                        overlay_height,
                    )
                } else {
                    (desired_x, desired_y)
                };
                let _ = overlay.set_position(tauri::PhysicalPosition::new(x as i32, y as i32));
            }
    }
    overlay.show().map_err(|error| error.to_string())?;
    overlay.set_focus().map_err(|error| error.to_string())?;
    Ok(())
}

#[tauri::command]
fn hide_pet_overlay(app: tauri::AppHandle) {
    if let Some(overlay) = app.get_webview_window("pet-overlay") {
        let _ = overlay.hide();
    }
}

#[tauri::command]
fn show_pet_window(app: tauri::AppHandle) {
    if let Some(pet) = app.get_webview_window("pet") {
        let _ = pet.show();
    }
}

#[tauri::command]
fn hide_pet_window(app: tauri::AppHandle) {
    if let Some(pet) = app.get_webview_window("pet") {
        let _ = pet.hide();
    }
    if let Some(overlay) = app.get_webview_window("pet-overlay") {
        let _ = overlay.hide();
    }
}

#[tauri::command]
fn open_pet_resource_folder() -> Result<(), String> {
    let root = if cfg!(debug_assertions) {
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .and_then(|path| path.parent())
            .ok_or_else(|| "cannot locate core directory".to_string())?
            .join(".lam")
            .join("core")
            .join("pets")
    } else {
        env::current_exe()
            .map_err(|error| error.to_string())?
            .parent()
            .ok_or_else(|| "cannot locate app directory".to_string())?
            .join(".lam")
            .join("core")
            .join("pets")
    };
    std::fs::create_dir_all(&root).map_err(|error| error.to_string())?;
    open::that(&root).map_err(|error| error.to_string())
}

#[tauri::command]
fn resize_pet_window(app: tauri::AppHandle, width: u32, height: u32) -> Result<(), String> {
    let pet = app
        .get_webview_window("pet")
        .ok_or_else(|| "pet window is not ready".to_string())?;
    // The Vue surface uses CSS/logical pixels. Let Tauri convert those to
    // physical pixels for the monitor's current DPI instead of making a
    // 150% display render a smaller-than-intended Pet.
    pet.set_size(tauri::LogicalSize::new(
        f64::from(width.max(80)),
        f64::from(height.max(80)),
    ))
        .map_err(|error| error.to_string())
}

#[tauri::command]
fn ping() -> String {
    "pong".to_string()
}

/// Report the packaged app name and version (from tauri.conf.json).
///
/// The frontend injects this into `window.__LAMTOOLS_APP_VERSION__` so the
/// settings UI can show the real version without hardcoding a string — the
/// update check compares it against the backend's `__version__`.
#[tauri::command]
fn get_app_info(app: tauri::AppHandle) -> Result<serde_json::Value, String> {
    let info = app.package_info();
    Ok(serde_json::json!({
        "name": info.name,
        "version": info.version.to_string(),
    }))
}

#[tauri::command]
fn pick_directory() -> Option<String> {
    rfd::FileDialog::new()
        .set_title("选择目录")
        .pick_folder()
        .map(|p| p.to_string_lossy().into_owned())
}

/// Open an external URL in the OS default browser.
///
/// The Tauri webview has no navigation policy by default, so a plain
/// `<a href="https://...">` click would navigate the app window itself
/// (turning it into a browser). The frontend intercepts link clicks and
/// routes them through this command instead. Only http(s) URLs are
/// accepted — everything else is rejected to prevent scheme/protocol abuse.
#[tauri::command]
fn open_external_url(url: String) -> Result<(), String> {
    let parsed = url::Url::parse(&url).map_err(|_| "invalid URL".to_string())?;
    match parsed.scheme() {
        "http" | "https" => {}
        other => return Err(format!("refused scheme: {other}")),
    }
    open::that(url).map_err(|e| e.to_string())
}

// ---------------------------------------------------------------------------
// App entry point
// ---------------------------------------------------------------------------

fn main() {
    let state = BackendState {
        api_base: Mutex::new(None),
        child: Mutex::new(None),
    };

    tauri::Builder::default()
        // Single-instance guard: two instances would each spawn a backend
        // writing the same .lam/core.db (SQLite lock storms, config
        // clobbering) (audit 20 S3).
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            // Focus the existing window instead of starting a second instance.
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.set_focus();
            }
        }))
        .manage(state)
        .manage(PetDragState::default())
        .setup(|app| {
            let state = app.state::<BackendState>();
            match start_backend(app, state.inner()) {
                Ok(api_base) => {
                    *state
                        .api_base
                        .lock()
                        .map_err(|_| "backend state lock failed")? = Some(api_base);
                    // Watch the backend process: if it dies mid-run (panic,
                    // fatal Python exception) the frontend gets an event and
                    // can show a recovery banner instead of silently failing
                    // every request (audit 20 S3).
                    let app_handle = app.handle().clone();
                    spawn_backend_watcher(app_handle);
                    let pet_app = app.handle().clone();
                    std::thread::spawn(move || {
                        if let Err(error) = create_pet_windows(&pet_app) {
                            eprintln!("[lamcore] desktop pet startup failed: {error}");
                        }
                    });
                    Ok(())
                }
                Err(e) => {
                    let msg = format!("LamCore 后端启动失败：\n\n{}", e);
                    eprintln!("{}", msg);
                    #[cfg(windows)]
                    {
                        let msg_wide: Vec<u16> = msg.encode_utf16().chain(std::iter::once(0)).collect();
                        extern "system" {
                            fn MessageBoxW(hwnd: isize, text: *const u16, caption: *const u16, utype: u32) -> i32;
                        }
                        let caption: Vec<u16> = "LamCore 启动错误".encode_utf16().chain(std::iter::once(0)).collect();
                        unsafe { MessageBoxW(0, msg_wide.as_ptr(), caption.as_ptr(), 0x00000010) };
                    }
                    Err(e)
                }
            }
        })
        .invoke_handler(tauri::generate_handler![
            get_api_base,
            get_window_label,
            ensure_pet_windows,
            minimize_window,
            toggle_maximize_window,
            close_window,
            focus_main_window,
            is_main_window_focused,
            show_pet_overlay,
            hide_pet_overlay,
            show_pet_window,
            hide_pet_window,
            open_pet_resource_folder,
            resize_pet_window,
            start_pet_drag,
            stop_pet_drag,
            ping,
            get_app_info,
            pick_directory,
            open_external_url
        ])
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Focused(true) = event {
                if window.label() == "main" {
                    if let Some(overlay) = window.app_handle().get_webview_window("pet-overlay") {
                        let _ = overlay.hide();
                    }
                }
            }
            if let tauri::WindowEvent::Destroyed = event {
                let state = window.state::<BackendState>();
                stop_backend(state.inner());
            }
        })
        .run(tauri::generate_context!())
        .expect("failed to run LamCore");
}

// ---------------------------------------------------------------------------
// Backend lifecycle
// ---------------------------------------------------------------------------

fn start_backend(
    app: &tauri::App,
    state: &BackendState,
) -> Result<String, Box<dyn std::error::Error>> {
    let port = pick_free_port()?;
    let api_base = format!("http://127.0.0.1:{port}");

    let mut cmd = if cfg!(debug_assertions) {
        dev_backend_command(port)?
    } else {
        prod_backend_command(app, port)?
    };

    let child = cmd.spawn()?;
    *state.child.lock().map_err(|_| "backend state lock failed")? = Some(child);

    wait_for_health(port)?;
    Ok(api_base)
}

fn dev_backend_command(port: u16) -> Result<Command, Box<dyn std::error::Error>> {
    // Resolve the core/ directory relative to the Cargo manifest.
    // src-tauri/ -> desktop/ -> core/.
    let core_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()                      // desktop/
        .and_then(|p| p.parent())      // core/
        .ok_or("cannot locate core/ directory")?
        .to_path_buf();

    let core_src = core_dir.join("src");
    let python_path = match env::var_os("PYTHONPATH") {
        Some(existing) => env::join_paths([core_src.as_os_str(), existing.as_os_str()])?,
        None => core_src.into_os_string(),
    };

    let mut cmd = Command::new("py");
    cmd.env("PYTHONPATH", python_path)
        .arg("-3.14")
        .arg("-m")
        .arg("lamtools_core.cli")
        .arg("serve")
        .arg("--port")
        .arg(port.to_string())
        // No --reload: uvicorn's reloader spawns a detached child on Windows
        // that survives stop_backend's kill(), orphaning a backend that keeps
        // core/core.db locked (audit 20 S2). Tauri dev restarts are full
        // teardown anyway (AGENTS.md: exit completely, then tauri dev again).
        .current_dir(&core_dir)
        .stdin(Stdio::null())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit());

    hide_console(&mut cmd);
    Ok(cmd)
}

fn prod_backend_command(
    app: &tauri::App,
    port: u16,
) -> Result<Command, Box<dyn std::error::Error>> {
    // The PyInstaller output is bundled as a resource at dist/LamCore/.
    // Tauri copies it to the bundle's resource directory.
    let backend_exe = find_backend_exe(app)?;
    let backend_dir = backend_exe
        .parent()
        .ok_or("cannot locate backend directory")?
        .to_path_buf();

    // Green/portable mode: keep every user data file (core.db, workspace,
    // logs, ~/.lam jsonc configs) beside the app under {app}/.lam so nothing
    // is written outside the install root (no %APPDATA%, no ~).
    let app_dir = env::current_exe()?
        .parent()
        .ok_or("cannot locate app directory")?
        .to_path_buf();
    let lam_home = app_dir.join(".lam");

    let mut cmd = Command::new(&backend_exe);
    cmd.env("LAMCORE_PORT", port.to_string())
        .env("LAMTOOLS_HOME", &lam_home)
        .env("LAMTOOLS_PROJECTS_ROOT", app_dir.join("lam_projects"))
        .current_dir(&backend_dir)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());

    hide_console(&mut cmd);
    Ok(cmd)
}

fn find_backend_exe(app: &tauri::App) -> Result<PathBuf, Box<dyn std::error::Error>> {
    // 1) Tauri resource directory (bundled flat)
    let resource = app
        .path()
        .resource_dir()?
        .join("lamcore-backend")
        .join("LamCore.exe");
    if resource.exists() {
        return Ok(resource);
    }

    // 2) Adjacent to the current exe (portable layout)
    let adjacent = env::current_exe()?
        .parent()
        .ok_or("cannot locate app directory")?
        .join("LamCore")
        .join("LamCore.exe");
    if adjacent.exists() {
        return Ok(adjacent);
    }

    // 3) Project dist directory (dev convenience)
    let project_dist = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()                         // src-tauri/ -> desktop/
        .and_then(|p| p.parent())         // desktop/ -> core/
        .and_then(|p| p.parent())         // core/ -> repo root
        .ok_or("cannot locate project root")?
        .join("dist")
        .join("LamCore")
        .join("LamCore.exe");
    if project_dist.exists() {
        return Ok(project_dist);
    }

    Err(format!(
        "LamCore.exe not found at any of:\n  {}\n  {}\n  {}",
        resource.display(),
        adjacent.display(),
        project_dist.display(),
    )
    .into())
}

// ---------------------------------------------------------------------------
// Utility helpers
// ---------------------------------------------------------------------------

fn pick_free_port() -> Result<u16, Box<dyn std::error::Error>> {
    let listener = TcpListener::bind("127.0.0.1:0")?;
    Ok(listener.local_addr()?.port())
}

fn wait_for_health(port: u16) -> Result<(), Box<dyn std::error::Error>> {
    // Generous timeout: on a loaded dev machine the backend can take a while
    // to start (uvicorn --reload + stale-turn recovery), and failing here
    // blocks the whole app on an error dialog for no reason.
    let deadline = Instant::now() + Duration::from_secs(90);
    while Instant::now() < deadline {
        if let Ok(mut stream) = TcpStream::connect(("127.0.0.1", port)) {
            let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
            let request =
                b"GET /api/health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n";
            if stream.write_all(request).is_ok() {
                let mut response = String::new();
                if stream.read_to_string(&mut response).is_ok() {
                    if response.contains("200") {
                        return Ok(());
                    }
                }
            }
        }
        thread::sleep(Duration::from_millis(250));
    }
    Err("backend health check timed out after 90s".into())
}

fn stop_backend(state: &BackendState) {
    if let Ok(mut guard) = state.child.lock() {
        if let Some(mut child) = guard.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

/// Poll the backend child process; if it exits outside the normal shutdown
/// path (child was still registered), emit a `backend-crashed` event so the
/// frontend can surface a recovery banner (audit 20 S3).
fn spawn_backend_watcher(app_handle: tauri::AppHandle) {
    thread::spawn(move || loop {
        thread::sleep(Duration::from_secs(2));
        let state = app_handle.state::<BackendState>();
        let mut guard = match state.child.lock() {
            Ok(guard) => guard,
            Err(_) => return,
        };
        if guard.is_none() {
            // Normal shutdown: stop_backend already took the child.
            return;
        }
        let exited = match guard.as_mut().map(|child| child.try_wait()) {
            Some(Ok(Some(_status))) => true,
            Some(Ok(None)) => false,
            _ => true, // try_wait error — treat as gone
        };
        if exited {
            *guard = None;
            drop(guard);
            eprintln!("[lamcore] backend process exited unexpectedly");
            let _ = app_handle.emit("backend-crashed", ());
            return;
        }
    });
}

#[cfg(windows)]
fn hide_console(cmd: &mut Command) {
    cmd.creation_flags(CREATE_NO_WINDOW);
}

#[cfg(not(windows))]
fn hide_console(_cmd: &mut Command) {}
