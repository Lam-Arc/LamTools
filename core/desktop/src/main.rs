#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{
    env,
    net::{TcpListener, TcpStream},
    path::PathBuf,
    process::{Child, Command, Stdio},
    sync::{Arc, Mutex},
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

impl BackendState {
    fn new() -> Self {
        Self {
            api_base: Mutex::new(None),
            child: Mutex::new(None),
        }
    }
}

#[tauri::command]
fn get_api_base(state: tauri::State<'_, Arc<BackendState>>) -> Result<String, String> {
    state
        .api_base
        .lock()
        .map_err(|_| "后端状态读取失败".to_string())?
        .clone()
        .ok_or_else(|| "后端尚未启动".to_string())
}

#[tauri::command]
fn select_directory() -> Result<Option<String>, String> {
    Ok(rfd::FileDialog::new()
        .pick_folder()
        .map(|path| path.to_string_lossy().to_string()))
}

fn main() {
    let backend_state = Arc::new(BackendState::new());
    let state_for_setup = Arc::clone(&backend_state);
    let state_for_exit = Arc::clone(&backend_state);

    tauri::Builder::default()
        .manage(backend_state)
        .setup(move |app| {
            let api_base = start_backend(app, &state_for_setup)?;
            *state_for_setup
                .api_base
                .lock()
                .map_err(|_| "后端状态写入失败")? = Some(api_base);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![get_api_base, select_directory])
        .on_window_event(move |_window, event| {
            if matches!(event, tauri::WindowEvent::Destroyed) {
                stop_backend(&state_for_exit);
            }
        })
        .run(tauri::generate_context!())
        .expect("failed to run LamTools Core");
}

fn start_backend(
    app: &tauri::App,
    state: &Arc<BackendState>,
) -> Result<String, Box<dyn std::error::Error>> {
    let port = pick_free_port()?;
    let api_base = format!("http://127.0.0.1:{port}");
    let mut command = backend_command(app, port)?;

    let child = command.spawn()?;
    *state.child.lock().map_err(|_| "后端进程状态写入失败")? = Some(child);
    wait_for_health(port)?;
    Ok(api_base)
}

fn backend_command(app: &tauri::App, port: u16) -> Result<Command, Box<dyn std::error::Error>> {
    let mut command = if cfg!(debug_assertions) {
        let mut cmd = Command::new("py");
        cmd.arg("-3.14")
            .arg("-m")
            .arg("uvicorn")
            .arg("lamtools_core.app.http_agent_server:app")
            .arg("--host")
            .arg("127.0.0.1")
            .arg("--port")
            .arg(port.to_string());
        cmd
    } else {
        let backend_exe = packaged_backend_path(app)?;
        let backend_dir = backend_exe
            .parent()
            .ok_or("无法定位打包后端目录")?
            .to_path_buf();
        let mut cmd = Command::new(backend_exe);
        cmd.current_dir(backend_dir);
        cmd
    };

    command
        .env("LAMTOOLS_CORE_HOST", "127.0.0.1")
        .env("LAMTOOLS_CORE_PORT", port.to_string())
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    hide_backend_window(&mut command);
    Ok(command)
}

#[cfg(windows)]
fn hide_backend_window(command: &mut Command) {
    command.creation_flags(CREATE_NO_WINDOW);
}

#[cfg(not(windows))]
fn hide_backend_window(_command: &mut Command) {}

fn packaged_backend_path(app: &tauri::App) -> Result<PathBuf, Box<dyn std::error::Error>> {
    let resource_path = app
        .path()
        .resource_dir()?
        .join("lamtools-core-backend")
        .join("lamtools-core-backend.exe");
    if resource_path.exists() {
        return Ok(resource_path);
    }

    let adjacent_path = env::current_exe()?
        .parent()
        .ok_or("无法定位应用目录")?
        .join("lamtools-core-backend")
        .join("lamtools-core-backend.exe");
    if adjacent_path.exists() {
        return Ok(adjacent_path);
    }

    Err(format!(
        "找不到 Core 后端：{} 或 {}",
        resource_path.display(),
        adjacent_path.display()
    )
    .into())
}

fn pick_free_port() -> Result<u16, Box<dyn std::error::Error>> {
    let listener = TcpListener::bind("127.0.0.1:0")?;
    Ok(listener.local_addr()?.port())
}

fn wait_for_health(port: u16) -> Result<(), Box<dyn std::error::Error>> {
    let deadline = Instant::now() + Duration::from_secs(30);
    while Instant::now() < deadline {
        if let Ok(mut stream) = TcpStream::connect(("127.0.0.1", port)) {
            use std::io::{Read, Write};
            let request =
                b"GET /api/health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n";
            stream.write_all(request)?;
            let mut response = String::new();
            stream.read_to_string(&mut response)?;
            if response.starts_with("HTTP/1.1 200") || response.starts_with("HTTP/1.0 200") {
                return Ok(());
            }
        }
        thread::sleep(Duration::from_millis(250));
    }
    Err("Core 后端启动超时".into())
}

fn stop_backend(state: &Arc<BackendState>) {
    if let Ok(mut guard) = state.child.lock() {
        if let Some(mut child) = guard.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}