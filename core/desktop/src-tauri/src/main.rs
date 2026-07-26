#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{
    env, path::PathBuf, process::{Child, Command, Stdio}, sync::{Arc, Mutex}, thread, time::{Duration, Instant},
};
use std::net::{TcpListener, TcpStream};
use std::io::{Read, Write};

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
    fn new() -> Self { Self { api_base: Mutex::new(None), child: Mutex::new(None) } }
}

fn main() {
    let backend_state = Arc::new(BackendState::new());
    let state_for_setup = Arc::clone(&backend_state);
    let state_for_exit = Arc::clone(&backend_state);

    tauri::Builder::default()
        .manage(backend_state)
        .setup(move |app| {
            let api_base = start_backend(app, &state_for_setup)?;
            *state_for_setup.api_base.lock().map_err(|_| "backend state error")? = Some(api_base);
            Ok(())
        })
        .on_window_event(move |_window, event| {
            if matches!(event, tauri::WindowEvent::Destroyed) {
                stop_backend(&state_for_exit);
            }
        })
        .run(tauri::generate_context!())
        .expect("failed to run LamCore");
}

fn start_backend(app: &tauri::App, state: &Arc<BackendState>) -> Result<String, Box<dyn std::error::Error>> {
    let port = pick_free_port()?;
    let api_base = format!("http://127.0.0.1:{port}");
    let mut command = backend_command(app, port)?;
    let child = command.spawn()?;
    *state.child.lock().map_err(|_| "backend process state error")? = Some(child);
    wait_for_health(port)?;
    Ok(api_base)
}

fn backend_command(app: &tauri::App, port: u16) -> Result<Command, Box<dyn std::error::Error>> {
    let mut command = if cfg!(debug_assertions) {
        let mut cmd = Command::new("py");
        cmd.arg("-3.14").arg("-m").arg("lamtools_core.cli").arg("serve")
            .arg("--host").arg("127.0.0.1").arg("--port").arg(port.to_string());
        cmd
    } else {
        let backend_exe = packaged_backend_path(app)?;
        let backend_dir = backend_exe.parent().ok_or("no backend dir")?.to_path_buf();
        let mut cmd = Command::new(backend_exe);
        cmd.current_dir(backend_dir);
        cmd
    };

    command
        .env("LAMTOOLS_CORE_PORT", port.to_string())
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    hide_backend_window(&mut command);
    Ok(command)
}

fn packaged_backend_path(app: &tauri::App) -> Result<PathBuf, Box<dyn std::error::Error>> {
    let p1 = app.path().resource_dir()?.join("lamtools-core-backend").join("lamtools-core-backend.exe");
    if p1.exists() { return Ok(p1); }
    let p2 = env::current_exe()?.parent().ok_or("no parent dir")?.join("lamtools-core-backend").join("lamtools-core-backend.exe");
    if p2.exists() { return Ok(p2); }
    Err(format!("cannot find core backend").into())
}

fn pick_free_port() -> Result<u16, Box<dyn std::error::Error>> {
    let listener = TcpListener::bind("127.0.0.1:0")?;
    Ok(listener.local_addr()?.port())
}

fn wait_for_health(port: u16) -> Result<(), Box<dyn std::error::Error>> {
    let deadline = Instant::now() + Duration::from_secs(30);
    while Instant::now() < deadline {
        if let Ok(mut stream) = TcpStream::connect(("127.0.0.1", port)) {
            let request = b"GET /api/health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n";
            stream.write_all(request)?;
            let mut response = String::new();
            stream.read_to_string(&mut response)?;
            if response.starts_with("HTTP/1.1 200") || response.starts_with("HTTP/1.0 200") {
                return Ok(());
            }
        }
        thread::sleep(Duration::from_millis(300));
    }
    Err("Core backend start timeout".into())
}

fn stop_backend(state: &Arc<BackendState>) {
    if let Ok(mut guard) = state.child.lock() {
        if let Some(mut child) = guard.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

#[cfg(windows)]
fn hide_backend_window(command: &mut Command) { command.creation_flags(CREATE_NO_WINDOW); }
#[cfg(not(windows))]
fn hide_backend_window(_command: &mut Command) {}
