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

use tauri::Manager;

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

// ---------------------------------------------------------------------------
// App entry point
// ---------------------------------------------------------------------------

fn main() {
    let state = BackendState {
        api_base: Mutex::new(None),
        child: Mutex::new(None),
    };

    tauri::Builder::default()
        .manage(state)
        .setup(|app| {
            let state = app.state::<BackendState>();
            match start_backend(app, state.inner()) {
                Ok(api_base) => {
                    *state
                        .api_base
                        .lock()
                        .map_err(|_| "backend state lock failed")? = Some(api_base);
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
        .invoke_handler(tauri::generate_handler![get_api_base, minimize_window, toggle_maximize_window, close_window, ping])
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
        .arg("--reload")
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

    let mut cmd = Command::new(&backend_exe);
    cmd.env("LAMCORE_PORT", port.to_string())
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

    // ... rest unchanged

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
    let deadline = Instant::now() + Duration::from_secs(30);
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
    Err("backend health check timed out after 30s".into())
}

fn stop_backend(state: &BackendState) {
    if let Ok(mut guard) = state.child.lock() {
        if let Some(mut child) = guard.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

#[cfg(windows)]
fn hide_console(cmd: &mut Command) {
    cmd.creation_flags(CREATE_NO_WINDOW);
}

#[cfg(not(windows))]
fn hide_console(_cmd: &mut Command) {}