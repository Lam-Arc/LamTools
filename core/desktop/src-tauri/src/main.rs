#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{
    env,
    io::{Read, Write},
    net::{TcpListener, TcpStream},
    path::PathBuf,
    process::{Child, Command, Stdio},
    sync::Mutex,
    thread,
    time::{Duration, Instant},
};

#[cfg(windows)]
use std::os::windows::process::CommandExt;

use tauri::{Emitter, Manager};

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x08000000;

struct BackendState {
    api_base: Mutex<Option<String>>,
    child: Mutex<Option<Child>>,
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
        .invoke_handler(tauri::generate_handler![get_api_base, minimize_window, toggle_maximize_window, close_window, ping, get_app_info, pick_directory, open_external_url])
        .on_window_event(|window, event| {
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
    // Resolve the core/ directory relative to the Cargo workspace root.
    // src-tauri/ is two levels under core/desktop/, so go up three.
    let core_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()                      // src-tauri/
        .and_then(|p| p.parent())      // desktop/
        .and_then(|p| p.parent())      // core/
        .ok_or("cannot locate core/ directory")?
        .to_path_buf();

    let mut cmd = Command::new("py");
    cmd.arg("-3.14")
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