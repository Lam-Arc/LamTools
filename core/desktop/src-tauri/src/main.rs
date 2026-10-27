#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{
    env,
    fs::{self, File, OpenOptions},
    io::{self, Read, Write},
    net::{TcpListener, TcpStream},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::{
        atomic::{AtomicBool, AtomicU64, Ordering},
        Mutex,
    },
    thread,
    time::{Duration, Instant},
};

#[cfg(target_os = "linux")]
use std::os::unix::process::CommandExt;
#[cfg(windows)]
use std::os::windows::process::CommandExt;
#[cfg(windows)]
use windows_sys::Win32::{
    Foundation::{CloseHandle, HANDLE},
    Storage::FileSystem::{MoveFileExW, MOVEFILE_REPLACE_EXISTING, MOVEFILE_WRITE_THROUGH},
    System::{
        JobObjects::{
            AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
            SetInformationJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
            JOB_OBJECT_LIMIT_BREAKAWAY_OK, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
        },
        Threading::{OpenProcess, PROCESS_SET_QUOTA, PROCESS_TERMINATE},
    },
};

use tauri::{
    menu::{Menu, MenuEvent, MenuItem},
    tray::TrayIconBuilder,
    Emitter, Manager, Url, WebviewWindow, WebviewWindowBuilder, WebviewUrl,
};

mod remote;
mod split_pane;
#[cfg(windows)]
mod windows_close_request;
#[cfg(windows)]
mod windows_snap_layout;
use remote::{
    start_local_control_server, ControlServer, DesktopAccountSession, DesktopAccountStatus,
    GatewayStartOptions, GatewayStatus, NodeIdentityStatus, PairingCodePayload,
    RemoteGatewayManager,
};

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x08000000;
const TRAY_ID: &str = "lamtools-tray";
const TRAY_OPEN_MAIN_ID: &str = "tray-open-main";
const TRAY_QUIT_ID: &str = "tray-quit";
static NEXT_SESSION_EXPORT_TEMP_ID: AtomicU64 = AtomicU64::new(1);

#[cfg(target_os = "linux")]
const PR_SET_PDEATHSIG: i32 = 1;
#[cfg(target_os = "linux")]
const SIGTERM: i32 = 15;
#[cfg(target_os = "linux")]
const SIGKILL: i32 = 9;

#[cfg(target_os = "linux")]
unsafe extern "C" {
    fn getppid() -> i32;
    fn kill(pid: i32, signal: i32) -> i32;
    fn prctl(option: i32, arg2: usize, arg3: usize, arg4: usize, arg5: usize) -> i32;
}

struct BackendState {
    api_base: Mutex<Option<String>>,
    startup_error: Mutex<Option<String>>,
    child: Mutex<Option<Child>>,
    #[cfg(windows)]
    backend_job: Mutex<Option<usize>>,
    remote_gateway: RemoteGatewayManager,
    control_server: Mutex<Option<ControlServer>>,
    quitting: AtomicBool,
}

#[tauri::command]
fn get_api_base(state: tauri::State<'_, BackendState>) -> Result<String, String> {
    if state.quitting.load(Ordering::SeqCst) {
        return Err("app is quitting".into());
    }
    if let Some(error) = state
        .startup_error
        .lock()
        .map_err(|_| "backend state lock failed")?
        .clone()
    {
        return Err(error);
    }
    state
        .api_base
        .lock()
        .map_err(|_| "backend state lock failed".to_string())?
        .clone()
        .ok_or_else(|| "backend not yet started".to_string())
}

#[tauri::command]
fn append_frontend_console(app: tauri::AppHandle, lines: String) -> Result<(), String> {
    // Developer-mode console retention. WebView2 console output never reaches
    // the terminal, so a frontend error was invisible unless the user opened
    // devtools. This appends the batched lines to
    // `core/data/core-agent/frontend-console.log` in a source checkout.
    if lines.trim().is_empty() {
        return Ok(());
    }
    let path = if cfg!(debug_assertions) {
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .and_then(|desktop| desktop.parent())
            .map(|core| core.join("data").join("core-agent").join("frontend-console.log"))
            .ok_or_else(|| "cannot resolve frontend console log path".to_string())?
    } else {
        app.path()
            .app_log_dir()
            .map_err(|error| error.to_string())?
            .join("frontend-console.log")
    };
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    if fs::metadata(&path)
        .map(|metadata| metadata.len() > 32 * 1024 * 1024)
        .unwrap_or(false)
    {
        let rotated = path.with_extension("log.1");
        let _ = fs::rename(&path, rotated);
    }
    let mut file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&path)
        .map_err(|error| error.to_string())?;
    file.write_all(lines.as_bytes())
        .and_then(|_| file.write_all(b"\n"))
        .map_err(|error| error.to_string())
}

#[tauri::command]
fn enable_startup_glass(window: WebviewWindow) -> Result<(), String> {
    #[cfg(windows)]
    {
        use tauri::window::{Effect, EffectsBuilder};

        window
            .set_effects(
                EffectsBuilder::new()
                    .effect(Effect::Acrylic)
                    .color((58, 59, 63, 32).into())
                    .build(),
            )
            .map_err(|error| format!("startup glass effect failed: {error}"))?;
    }

    #[cfg(not(windows))]
    let _ = window;

    Ok(())
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
fn set_maximize_button_bounds(
    window: tauri::WebviewWindow,
    x: f64,
    top: f64,
    width: f64,
    height: f64,
) -> Result<(), String> {
    #[cfg(windows)]
    {
        if window.label() != "main" {
            return Err(
                "maximize button bounds are only supported for the main window".to_string(),
            );
        }
        windows_snap_layout::set_button_bounds(&window, x, top, width, height)
    }

    #[cfg(not(windows))]
    {
        let _ = (window, x, top, width, height);
        Ok(())
    }
}

#[tauri::command]
fn close_window(window: tauri::WebviewWindow) {
    let _ = window.close();
}

#[tauri::command]
fn open_plugin_window(
    app: tauri::AppHandle,
    label: String,
    url: String,
    title: String,
    width: f64,
    height: f64,
) -> Result<(), String> {
    let label = label.trim();
    if label.is_empty() || label.len() > 120 {
        return Err("invalid plugin window label".to_string());
    }
    if let Some(window) = app.get_webview_window(label) {
        let _ = window.show();
        let _ = window.set_focus();
        return Ok(());
    }
    let parsed = Url::parse(&url).map_err(|error| error.to_string())?;
    WebviewWindowBuilder::new(&app, label, WebviewUrl::External(parsed))
        .title(title)
        .inner_size(width.max(160.0), height.max(160.0))
        .build()
        .map_err(|error| error.to_string())?;
    Ok(())
}

#[tauri::command]
fn show_main_window(app: tauri::AppHandle) {
    reveal_main_window(&app);
}

/// Shut the desktop shell down for real: the tray window is hidden, not
/// closed, so nothing else would stop the backend. Shared by the tray's quit
/// item, the `quit_app` command, and the system close requests handled in
/// `windows_close_request`.
pub(crate) fn request_quit(app: &tauri::AppHandle) {
    let state = app.state::<BackendState>();
    state.quitting.store(true, Ordering::SeqCst);
    let _ = state.remote_gateway.shutdown();
    stop_local_control_server(state.inner());
    stop_backend(state.inner());
    app.exit(0);
}

#[tauri::command]
fn quit_app(app: tauri::AppHandle) {
    request_quit(&app);
}

/// Start the desktop-only RemoteGateway.  Core itself remains on the
/// loopback address returned by `get_api_base`; no caller can supply a remote
/// Core URL through this command.
#[tauri::command]
fn remote_gateway_start(
    state: tauri::State<'_, BackendState>,
    options: Option<GatewayStartOptions>,
) -> Result<GatewayStatus, String> {
    let api_base = state
        .api_base
        .lock()
        .map_err(|_| "backend state lock failed".to_string())?
        .clone()
        .ok_or_else(|| "backend not yet started".to_string())?;
    state
        .remote_gateway
        .start(&api_base, options.unwrap_or_default())
}

#[tauri::command]
fn remote_gateway_stop(state: tauri::State<'_, BackendState>) -> Result<GatewayStatus, String> {
    state.remote_gateway.stop()
}

#[tauri::command]
fn remote_gateway_status(state: tauri::State<'_, BackendState>) -> Result<GatewayStatus, String> {
    state.remote_gateway.status()
}

#[tauri::command]
fn remote_pairing_create(
    state: tauri::State<'_, BackendState>,
) -> Result<PairingCodePayload, String> {
    state.remote_gateway.pairing_create()
}

#[tauri::command]
fn remote_device_revoke(
    state: tauri::State<'_, BackendState>,
    device_id: String,
) -> Result<bool, String> {
    state.remote_gateway.revoke_device(&device_id)
}

#[tauri::command]
fn remote_account_status(
    state: tauri::State<'_, BackendState>,
) -> Result<Option<DesktopAccountStatus>, String> {
    state.remote_gateway.account_status()
}

#[tauri::command]
fn remote_account_identity(
    state: tauri::State<'_, BackendState>,
    server_id: Option<String>,
    username: Option<String>,
) -> Result<NodeIdentityStatus, String> {
    match (server_id, username) {
        (Some(server_id), Some(username)) => state
            .remote_gateway
            .node_identity_for_account(&server_id, &username),
        _ => state.remote_gateway.node_identity(),
    }
}

#[tauri::command]
fn remote_account_save(
    state: tauri::State<'_, BackendState>,
    session: DesktopAccountSession,
) -> Result<DesktopAccountStatus, String> {
    state.remote_gateway.save_account_session(session)
}

#[tauri::command]
fn remote_account_logout(state: tauri::State<'_, BackendState>) -> Result<(), String> {
    state.remote_gateway.account_logout()
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

// user:“若此附件真实存在于计算机则添加绝对路径”+(原生选择器只返回路径，文件内容由工具按需读取)。
#[tauri::command]
async fn pick_files() -> Option<Vec<String>> {
    rfd::AsyncFileDialog::new().set_title("选择附件").pick_files().await
        .map(|files| files.into_iter().map(|file| file.path().to_string_lossy().into_owned()).collect())
}

#[tauri::command]
fn pick_directory() -> Option<String> {
    rfd::FileDialog::new()
        .set_title("选择目录")
        .pick_folder()
        .map(|p| p.to_string_lossy().into_owned())
}

#[tauri::command]
async fn export_session_archive(
    state: tauri::State<'_, BackendState>,
    session_id: String,
    suggested_filename: String,
) -> Result<Option<String>, String> {
    if session_id.trim().is_empty() {
        return Err("会话编号为空，无法导出完整归档".to_string());
    }
    let api_base = state
        .api_base
        .lock()
        .map_err(|_| "本地后端地址读取失败".to_string())?
        .clone()
        .ok_or_else(|| "本地后端尚未就绪".to_string())?;
    validate_loopback_api_base(&api_base)?;

    let suggested_filename = sanitize_export_filename(&suggested_filename);
    let Some(file) = rfd::AsyncFileDialog::new()
        .set_title("保存完整归档")
        .add_filter("ZIP 归档", &["zip"])
        .set_file_name(suggested_filename)
        .save_file()
        .await
    else {
        return Ok(None);
    };

    let destination = with_zip_extension(file.path());
    let session_id = session_id.trim().to_string();
    let saved_path = tauri::async_runtime::spawn_blocking(move || {
        save_session_archive_from_local_core(&api_base, &session_id, &destination)
    })
    .await
    .map_err(|error| format!("完整归档保存任务失败：{error}"))??;
    Ok(Some(saved_path))
}

fn validate_loopback_api_base(api_base: &str) -> Result<(), String> {
    let parsed = url::Url::parse(api_base).map_err(|_| "本地后端地址无效".to_string())?;
    if parsed.scheme() != "http" || parsed.host_str() != Some("127.0.0.1") {
        return Err("完整归档只允许通过本机 Sunday 后端导出".to_string());
    }
    Ok(())
}

fn sanitize_export_filename(filename: &str) -> String {
    let mut clean = filename
        .chars()
        .map(|ch| {
            if ch.is_control() || matches!(ch, '<' | '>' | ':' | '"' | '/' | '\\' | '|' | '?' | '*')
            {
                '_'
            } else {
                ch
            }
        })
        .collect::<String>();
    clean = clean.trim().trim_end_matches(['.', ' ']).to_string();
    if clean.is_empty() || clean == "." || clean == ".." {
        clean = "Sunday-session-archive".to_string();
    }
    if !clean.to_ascii_lowercase().ends_with(".zip") {
        clean.push_str(".zip");
    }
    clean
}

fn with_zip_extension(path: &Path) -> PathBuf {
    if path
        .extension()
        .and_then(|extension| extension.to_str())
        .is_some_and(|extension| extension.eq_ignore_ascii_case("zip"))
    {
        return path.to_path_buf();
    }
    let mut filename = path
        .file_name()
        .map(|name| name.to_os_string())
        .unwrap_or_default();
    filename.push(".zip");
    path.with_file_name(filename)
}

fn save_session_archive_from_local_core(
    api_base: &str,
    session_id: &str,
    destination: &Path,
) -> Result<String, String> {
    let parent = destination
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."));
    if !destination.is_absolute() {
        return Err("保存位置必须是绝对路径".to_string());
    }
    if !parent.is_dir() {
        return Err("所选保存目录不存在".to_string());
    }

    let (temporary_path, mut temporary_file) = create_session_export_temp(destination)?;
    let result = (|| -> Result<(), String> {
        let agent = ureq::Agent::new_with_config(
            ureq::Agent::config_builder()
                .proxy(None)
                .http_status_as_error(false)
                .timeout_global(Some(Duration::from_secs(120)))
                .build(),
        );
        let encoded_session_id = urlencoding::encode(session_id);
        let endpoint = format!("{api_base}/api/core/sessions/{encoded_session_id}/export");
        let mut response = agent
            .post(&endpoint)
            .header("Accept", "application/zip")
            .send_json(serde_json::json!({"mode": "full", "format": "zip"}))
            .map_err(|error| format!("请求完整归档失败：{error}"))?;
        if !response.status().is_success() {
            let status = response.status();
            let body = response.body_mut().read_to_string().unwrap_or_default();
            let detail = serde_json::from_str::<serde_json::Value>(&body)
                .ok()
                .and_then(|value| {
                    value
                        .get("detail")
                        .and_then(serde_json::Value::as_str)
                        .map(str::to_string)
                })
                .filter(|detail| !detail.trim().is_empty())
                .unwrap_or_else(|| body.trim().to_string());
            return Err(if detail.is_empty() {
                format!("完整归档导出失败（HTTP {status}）")
            } else {
                format!("完整归档导出失败（HTTP {status}）：{detail}")
            });
        }

        let mut response_body = response.body_mut().as_reader();
        io::copy(&mut response_body, &mut temporary_file)
            .map_err(|error| format!("写入完整归档失败：{error}"))?;
        temporary_file
            .sync_all()
            .map_err(|error| format!("完整归档写入磁盘失败：{error}"))?;
        Ok(())
    })();
    drop(temporary_file);

    if let Err(error) = result {
        let _ = fs::remove_file(&temporary_path);
        return Err(error);
    }
    if let Err(error) = replace_file_atomically(&temporary_path, destination) {
        let _ = fs::remove_file(&temporary_path);
        return Err(format!("归档已生成，但无法保存到所选位置：{error}"));
    }
    Ok(destination.to_string_lossy().into_owned())
}

fn create_session_export_temp(destination: &Path) -> Result<(PathBuf, File), String> {
    let parent = destination
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."));
    let filename = destination
        .file_name()
        .ok_or_else(|| "所选保存位置不是文件".to_string())?
        .to_string_lossy();
    for _ in 0..32 {
        let sequence = NEXT_SESSION_EXPORT_TEMP_ID.fetch_add(1, Ordering::Relaxed);
        let temp_path = parent.join(format!(
            ".{filename}.{}.{}.part",
            std::process::id(),
            sequence
        ));
        match OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temp_path)
        {
            Ok(file) => return Ok((temp_path, file)),
            Err(error) if error.kind() == io::ErrorKind::AlreadyExists => continue,
            Err(error) => return Err(format!("无法创建归档临时文件：{error}")),
        }
    }
    Err("无法分配归档临时文件名".to_string())
}

#[cfg(windows)]
fn replace_file_atomically(source: &Path, destination: &Path) -> io::Result<()> {
    use std::{iter::once, os::windows::ffi::OsStrExt};

    let source_wide = source
        .as_os_str()
        .encode_wide()
        .chain(once(0))
        .collect::<Vec<_>>();
    let destination_wide = destination
        .as_os_str()
        .encode_wide()
        .chain(once(0))
        .collect::<Vec<_>>();
    let result = unsafe {
        MoveFileExW(
            source_wide.as_ptr(),
            destination_wide.as_ptr(),
            MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH,
        )
    };
    if result == 0 {
        Err(io::Error::last_os_error())
    } else {
        Ok(())
    }
}

#[cfg(not(windows))]
fn replace_file_atomically(source: &Path, destination: &Path) -> io::Result<()> {
    fs::rename(source, destination)
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

fn handle_tray_menu(app: &tauri::AppHandle, event: MenuEvent) {
    match event.id().as_ref() {
        TRAY_OPEN_MAIN_ID => reveal_main_window(app),
        TRAY_QUIT_ID => request_quit(app),
        _ => {}
    }
}

fn setup_tray(app: &tauri::App) -> Result<(), Box<dyn std::error::Error>> {
    let open_main = MenuItem::with_id(app, TRAY_OPEN_MAIN_ID, "打开界面", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, TRAY_QUIT_ID, "退出", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&open_main, &quit])?;

    let mut builder = TrayIconBuilder::with_id(TRAY_ID)
        .menu(&menu)
        .tooltip("LamTools")
        .show_menu_on_left_click(true)
        .on_menu_event(handle_tray_menu);
    if let Some(icon) = app.default_window_icon().cloned() {
        builder = builder.icon(icon);
    }
    builder.build(app)?;

    Ok(())
}

#[cfg(windows)]
fn install_taskbar_icon(app: &tauri::App) -> Result<(), Box<dyn std::error::Error>> {
    use windows_sys::Win32::{
        System::LibraryLoader::GetModuleHandleW,
        UI::WindowsAndMessaging::{LoadImageW, SendMessageW, IMAGE_ICON, LR_SHARED, WM_SETICON},
    };
    let window = app
        .get_webview_window("main")
        .ok_or("main window missing")?;
    let hwnd = window.hwnd()?.0 as windows_sys::Win32::Foundation::HWND;
    // Shared resource icons live for the process lifetime; never destroy them.
    let icon = unsafe {
        LoadImageW(
            GetModuleHandleW(std::ptr::null()),
            32512usize as *const u16,
            IMAGE_ICON,
            0,
            0,
            LR_SHARED,
        )
    };
    if icon.is_null() {
        return Err(std::io::Error::last_os_error().into());
    }
    unsafe {
        SendMessageW(hwnd, WM_SETICON, 1, icon as isize);
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// App entry point
// ---------------------------------------------------------------------------

fn main() {
    // tungstenite uses rustls for the remote Relay connection. Rustls 0.23
    // can expose more than one crypto backend through the dependency graph;
    // install the explicitly selected ring provider before any Relay thread
    // attempts a TLS handshake.
    let _ = rustls::crypto::ring::default_provider().install_default();

    let state = BackendState {
        api_base: Mutex::new(None),
        startup_error: Mutex::new(None),
        child: Mutex::new(None),
        #[cfg(windows)]
        backend_job: Mutex::new(None),
        remote_gateway: RemoteGatewayManager::default(),
        control_server: Mutex::new(None),
        quitting: AtomicBool::new(false),
    };

    tauri::Builder::default()
        // Single-instance guard: two instances would each spawn a backend
        // writing the same .lam/core.db (SQLite lock storms, config
        // clobbering) (audit 20 S3).
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            // Focus the existing window instead of starting a second instance.
            reveal_main_window(app);
        }))
        .manage(state)
        .setup(|app| {
            #[cfg(windows)]
            if let Some(window) = app.get_webview_window("main") {
                windows_snap_layout::install(&window)
                    .map_err(|error| format!("snap layout setup failed: {error}"))?;
                windows_close_request::install(&window)
                    .map_err(|error| format!("system close handler setup failed: {error}"))?;
            }

            setup_tray(app)?;
            #[cfg(windows)]
            install_taskbar_icon(app)?;
            // Setup runs before the native event loop. Never wait for Python
            // or network services here: Windows would mark the window hung.
            let app = app.handle().clone();
            thread::spawn(move || {
                let state = app.state::<BackendState>();
                match start_backend(&app, state.inner()) {
                    Ok(api_base) => {
                        if state.quitting.load(Ordering::SeqCst) {
                            return;
                        }
                        let Ok(mut api_slot) = state.api_base.lock() else {
                            eprintln!("[lamcore] backend state lock failed");
                            return;
                        };
                        *api_slot = Some(api_base.clone());
                        drop(api_slot);
                        match start_local_control_server(
                            state.remote_gateway.clone(),
                            api_base.clone(),
                        ) {
                            Ok(server) => {
                                if let Ok(mut slot) = state.control_server.lock() {
                                    slot.replace(server);
                                }
                            }
                            Err(error) => {
                                eprintln!("[lamcore] remote CLI control server failed: {error}")
                            }
                        }
                        if state.remote_gateway.auto_start_enabled().unwrap_or(false) {
                            if let Err(error) = state
                                .remote_gateway
                                .start(&api_base, GatewayStartOptions::default())
                            {
                                eprintln!("[lamcore] remote gateway auto-start failed: {error}");
                            }
                        }
                        // Watch the backend process: if it dies mid-run (panic,
                        // fatal Python exception) the frontend gets an event and
                        // can show a recovery banner instead of silently failing
                        // every request (audit 20 S3).
                        let app_handle = app.clone();
                        spawn_backend_watcher(app_handle);
                        ()
                    }
                    Err(e) => {
                        if state.quitting.load(Ordering::SeqCst) {
                            return;
                        }
                        if let Ok(mut error) = state.startup_error.lock() {
                            *error = Some(format!("Sunday 后端启动失败：{e}"));
                        }
                        stop_backend(state.inner());
                        let msg = format!("Sunday 后端启动失败：\n\n{}", e);
                        eprintln!("{}", msg);
                        #[cfg(windows)]
                        {
                            let msg_wide: Vec<u16> =
                                msg.encode_utf16().chain(std::iter::once(0)).collect();
                            extern "system" {
                                fn MessageBoxW(
                                    hwnd: isize,
                                    text: *const u16,
                                    caption: *const u16,
                                    utype: u32,
                                ) -> i32;
                            }
                            let caption: Vec<u16> = "Sunday 启动错误"
                                .encode_utf16()
                                .chain(std::iter::once(0))
                                .collect();
                            unsafe {
                                MessageBoxW(0, msg_wide.as_ptr(), caption.as_ptr(), 0x00000010)
                            };
                        }
                        app.exit(1);
                    }
                }
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_api_base,
            split_pane::split_file_read,
            split_pane::split_file_write,
            split_pane::split_file_list,
            split_pane::split_browser,
            append_frontend_console,
            enable_startup_glass,
            export_session_archive,
            minimize_window,
            toggle_maximize_window,
            set_maximize_button_bounds,
            close_window,
            open_plugin_window,
            show_main_window,
            quit_app,
            remote_gateway_start,
            remote_gateway_stop,
            remote_gateway_status,
            remote_pairing_create,
            remote_device_revoke,
            remote_account_status,
            remote_account_identity,
            remote_account_save,
            remote_account_logout,
            ping,
            get_app_info,
            pick_directory,
            pick_files,
            open_external_url
        ])
        .on_window_event(|window, event| {
            let state = window.state::<BackendState>();
            match event {
                tauri::WindowEvent::CloseRequested { api, .. }
                    if window.label() == "main" && !state.quitting.load(Ordering::SeqCst) =>
                {
                    api.prevent_close();
                    let _ = window.hide();
                }
                tauri::WindowEvent::Destroyed if window.label() == "main" => {
                    let _ = state.remote_gateway.shutdown();
                    stop_local_control_server(state.inner());
                    stop_backend(state.inner());
                }
                _ => {}
            }
        })
        .build(tauri::generate_context!())
        .expect("failed to build Sunday")
        .run(|_app_handle, _event| {});
}

// ---------------------------------------------------------------------------
// Backend lifecycle
// ---------------------------------------------------------------------------

fn start_backend(
    app: &tauri::AppHandle,
    state: &BackendState,
) -> Result<String, Box<dyn std::error::Error>> {
    let started_at = Instant::now();
    let port = pick_free_port()?;
    let api_base = format!("http://127.0.0.1:{port}");

    let mut cmd = if cfg!(debug_assertions) {
        dev_backend_command(port)?
    } else {
        prod_backend_command(app, port)?
    };
    configure_backend_process(&mut cmd)?;

    // Serialize spawn/registration with shutdown so quitting during startup
    // cannot leave a late-spawned backend behind.
    let mut child_slot = state
        .child
        .lock()
        .map_err(|_| "backend state lock failed")?;
    if state.quitting.load(Ordering::SeqCst) {
        return Err("app is quitting".into());
    }
    let child = cmd.spawn()?;
    #[cfg(windows)]
    match create_backend_job(child.id()) {
        Ok(job) => {
            *state
                .backend_job
                .lock()
                .map_err(|_| "backend job state lock failed")? = Some(job);
        }
        Err(error) => {
            // Starting the backend is still preferable to aborting the app;
            // stop_backend retains its direct-child fallback below.
            eprintln!("[lamcore] backend process-tree guard unavailable: {error}");
        }
    }
    *child_slot = Some(child);
    drop(child_slot);

    wait_for_health(port, state)?;
    eprintln!(
        "[lamcore] backend ready in {} ms",
        started_at.elapsed().as_millis()
    );
    Ok(api_base)
}

fn configure_internal_backend_access(command: &mut Command) {
    // Desktop's API must not inherit standalone LAN configuration/credentials.
    command
        .env("LAMCORE_HOST", "127.0.0.1")
        .env_remove("LAMTOOLS_CORE_ALLOW_LAN")
        .env_remove("LAMTOOLS_CORE_API_TOKEN");
}

fn dev_backend_command(port: u16) -> Result<Command, Box<dyn std::error::Error>> {
    // Resolve core/ from core/desktop/src-tauri.
    let core_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent() // desktop/
        .and_then(|p| p.parent()) // core/
        .ok_or("cannot locate core/ directory")?
        .to_path_buf();

    // Resolve the requested interpreter once, then make Python itself the
    // tracked child. Tracking py.exe leaks its spawned python.exe whenever a
    // dev rebuild terminates the shell before normal shutdown runs.
    let mut cmd = Command::new(dev_python_executable()?);
    cmd.arg("-m")
        .arg("lamtools_core.cli")
        .arg("serve")
        .arg("--port")
        .arg(port.to_string())
        // No --reload: uvicorn's reloader spawns a detached child on Windows
        // that survives stop_backend's kill(), orphaning a backend that keeps
        // core/core.db locked (audit 20 S2). Tauri dev restarts are full
        // teardown anyway (AGENTS.md: exit completely, then tauri dev again).
        .current_dir(&core_dir)
        // A src-layout checkout is not importable from core/ by default.
        // Pin dev mode to this worktree instead of whichever editable
        // lamtools_core installation happens to be active on the machine.
        .env("PYTHONPATH", core_dir.join("src"))
        .stdin(Stdio::null())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit());

    configure_internal_backend_access(&mut cmd);
    hide_console(&mut cmd);
    Ok(cmd)
}

#[cfg(windows)]
fn dev_python_executable() -> Result<PathBuf, Box<dyn std::error::Error>> {
    let mut command = Command::new("py");
    command
        .arg("-3.14")
        .arg("-c")
        .arg("import sys; print(sys.executable)")
        .stdin(Stdio::null())
        .stderr(Stdio::null());
    hide_console(&mut command);
    let output = command.output()?;
    if !output.status.success() {
        return Err("Python 3.14 interpreter discovery failed".into());
    }
    let executable = String::from_utf8(output.stdout)?.trim().to_string();
    if executable.is_empty() {
        return Err("Python 3.14 interpreter path is empty".into());
    }
    Ok(PathBuf::from(executable))
}

#[cfg(not(windows))]
fn dev_python_executable() -> Result<PathBuf, Box<dyn std::error::Error>> {
    Ok(PathBuf::from("python3"))
}

fn prod_backend_command(
    app: &tauri::AppHandle,
    port: u16,
) -> Result<Command, Box<dyn std::error::Error>> {
    // The PyInstaller output is bundled as a resource at dist/LamCore/.
    // Tauri copies it to the bundle's resource directory.
    let backend_exe = find_backend_exe(app)?;
    let backend_dir = backend_exe
        .parent()
        .ok_or("cannot locate backend directory")?
        .to_path_buf();

    // Windows keeps its established green/portable app-side layout. Linux
    // AppImages may be mounted read-only, so all mutable state is rooted in
    // Tauri's XDG-backed per-user application data directory.
    let app_dir = env::current_exe()?
        .parent()
        .ok_or("cannot locate app directory")?
        .to_path_buf();
    #[cfg(target_os = "linux")]
    let storage_root = app.path().app_data_dir()?;
    #[cfg(not(target_os = "linux"))]
    let storage_root = app_dir.clone();
    let paths = prod_backend_storage_paths(&app_dir, &storage_root, cfg!(target_os = "linux"));

    let mut cmd = Command::new(&backend_exe);
    cmd.env("LAMCORE_PORT", port.to_string())
        .env("LAMTOOLS_HOME", &paths.lam_home)
        .env("LAMTOOLS_CORE_DATA_DIR", &paths.data_dir)
        .env("LAMTOOLS_PROJECTS_ROOT", &paths.projects_root)
        .current_dir(&backend_dir)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());

    configure_internal_backend_access(&mut cmd);
    hide_console(&mut cmd);
    Ok(cmd)
}

#[derive(Debug, Eq, PartialEq)]
struct ProdBackendStoragePaths {
    lam_home: PathBuf,
    data_dir: PathBuf,
    projects_root: PathBuf,
}

fn prod_backend_storage_paths(
    app_dir: &std::path::Path,
    standard_data_dir: &std::path::Path,
    use_standard_data_dir: bool,
) -> ProdBackendStoragePaths {
    if use_standard_data_dir {
        ProdBackendStoragePaths {
            lam_home: standard_data_dir.join(".lam"),
            data_dir: standard_data_dir.join("data"),
            projects_root: standard_data_dir.join("lam_projects"),
        }
    } else {
        ProdBackendStoragePaths {
            lam_home: app_dir.join(".lam"),
            data_dir: app_dir.join(".lam"),
            projects_root: app_dir.join("lam_projects"),
        }
    }
}

/// Backend executable file names, most preferred first.
///
/// The Windows installer deploys the bundled Python runtime as
/// `sunday-core.exe` so Task Manager attributes it to Sunday instead of an
/// anonymous name. `LamCore.exe` stays as a fallback for layouts assembled
/// straight from the raw PyInstaller output (portable copies, the project dist
/// directory), which still use the build-time name. Linux keeps the
/// extension-less `LamCore`, which the Linux bundle and its acceptance scripts
/// pin.
fn backend_executable_names(windows: bool) -> &'static [&'static str] {
    if windows {
        &["sunday-core.exe", "LamCore.exe"]
    } else {
        &["LamCore"]
    }
}

fn find_backend_exe(app: &tauri::AppHandle) -> Result<PathBuf, Box<dyn std::error::Error>> {
    let executable_names = backend_executable_names(cfg!(windows));
    // 1) Tauri resource directory (bundled flat)
    let resource = app.path().resource_dir()?.join("lamcore-backend");
    // 2) Adjacent to the current exe (portable layout)
    let adjacent = env::current_exe()?
        .parent()
        .ok_or("cannot locate app directory")?
        .join("LamCore");
    // 3) Project dist directory (dev convenience)
    let project_dist = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent() // src-tauri/ -> desktop/
        .and_then(|p| p.parent()) // desktop/ -> core/
        .and_then(|p| p.parent()) // core/ -> repo root
        .ok_or("cannot locate project root")?
        .join("dist")
        .join("LamCore");

    for directory in [&resource, &adjacent, &project_dist] {
        for executable_name in executable_names {
            let candidate = directory.join(executable_name);
            if candidate.exists() {
                return Ok(candidate);
            }
        }
    }

    Err(format!(
        "Sunday backend executable ({}) not found at any of:\n  {}\n  {}\n  {}",
        executable_names.join(" or "),
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

fn wait_for_health(port: u16, state: &BackendState) -> Result<(), Box<dyn std::error::Error>> {
    // Generous timeout: on a loaded dev machine the backend can take a while
    // to start (uvicorn --reload + stale-turn recovery), and failing here
    // blocks the whole app on an error dialog for no reason.
    let deadline = Instant::now() + Duration::from_secs(90);
    while Instant::now() < deadline {
        if state.quitting.load(Ordering::SeqCst) {
            return Err("app is quitting".into());
        }
        if let Ok(mut stream) = TcpStream::connect(("127.0.0.1", port)) {
            let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
            let request =
                b"GET /api/health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n";
            if stream.write_all(request).is_ok() {
                let mut response = String::new();
                if stream.read_to_string(&mut response).is_ok() && response.contains("200") {
                    return Ok(());
                }
            }
        }
        thread::sleep(Duration::from_millis(250));
    }
    Err("backend health check timed out after 90s".into())
}

fn stop_local_control_server(state: &BackendState) {
    if let Ok(mut slot) = state.control_server.lock() {
        if let Some(server) = slot.take() {
            server.stop();
        }
    }
}

fn stop_backend(state: &BackendState) {
    if let Ok(mut guard) = state.child.lock() {
        close_backend_job(state);
        if let Some(mut child) = guard.take() {
            #[cfg(target_os = "linux")]
            {
                // The backend owns a dedicated process group, so terminate any
                // subprocesses it created before escalating to SIGKILL.
                let process_group = -(child.id() as i32);
                unsafe {
                    let _ = kill(process_group, SIGTERM);
                }
                let deadline = Instant::now() + Duration::from_secs(3);
                while Instant::now() < deadline {
                    match child.try_wait() {
                        Ok(Some(_)) => break,
                        Ok(None) => thread::sleep(Duration::from_millis(25)),
                        Err(_) => break,
                    }
                }
                // The direct child can exit before one of its descendants.
                // Finish cleanup of the still-owned dedicated process group.
                unsafe {
                    let _ = kill(process_group, SIGKILL);
                }
            }
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

#[cfg(target_os = "linux")]
fn configure_backend_process(cmd: &mut Command) -> std::io::Result<()> {
    let expected_parent = std::process::id() as i32;
    cmd.process_group(0);
    unsafe {
        cmd.pre_exec(move || {
            // Ensure an abrupt desktop exit (including SIGKILL) cannot leave
            // the direct sidecar alive. Normal shutdown still uses the
            // graceful process-group SIGTERM path in stop_backend. Checking
            // the parent after prctl closes
            // the race where the desktop exits between fork and prctl.
            if prctl(PR_SET_PDEATHSIG, SIGKILL as usize, 0, 0, 0) != 0 {
                return Err(std::io::Error::last_os_error());
            }
            if getppid() != expected_parent {
                return Err(std::io::Error::new(
                    std::io::ErrorKind::BrokenPipe,
                    "desktop parent exited before backend startup",
                ));
            }
            Ok(())
        });
    }
    Ok(())
}

#[cfg(not(target_os = "linux"))]
fn configure_backend_process(_cmd: &mut Command) -> std::io::Result<()> {
    Ok(())
}

#[cfg(windows)]
fn create_backend_job(process_id: u32) -> Result<usize, Box<dyn std::error::Error>> {
    unsafe {
        let job = CreateJobObjectW(std::ptr::null(), std::ptr::null());
        if job.is_null() {
            return Err(std::io::Error::last_os_error().into());
        }
        let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
        // Kill-on-close keeps every tool process the backend started from
        // outliving the app, and BREAKAWAY_OK is what lets the one process that
        // must outlive it — the update installer, started before this app exits
        // to let it replace files — leave the job on purpose. Tools stay in the
        // job: they never ask to break away.
        info.BasicLimitInformation.LimitFlags =
            JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_BREAKAWAY_OK;
        if SetInformationJobObject(
            job,
            JobObjectExtendedLimitInformation,
            std::ptr::addr_of!(info).cast(),
            std::mem::size_of_val(&info) as u32,
        ) == 0
        {
            let error = std::io::Error::last_os_error();
            CloseHandle(job);
            return Err(error.into());
        }
        let process = OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, 0, process_id);
        if process.is_null() {
            let error = std::io::Error::last_os_error();
            CloseHandle(job);
            return Err(error.into());
        }
        let assigned = AssignProcessToJobObject(job, process);
        CloseHandle(process);
        if assigned == 0 {
            let error = std::io::Error::last_os_error();
            CloseHandle(job);
            return Err(error.into());
        }
        Ok(job as usize)
    }
}

#[cfg(windows)]
fn close_backend_job(state: &BackendState) {
    if let Ok(mut guard) = state.backend_job.lock() {
        if let Some(job) = guard.take() {
            unsafe { CloseHandle(job as HANDLE) };
        }
    }
}

#[cfg(not(windows))]
fn close_backend_job(_state: &BackendState) {}

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
            close_backend_job(state.inner());
            eprintln!("[lamcore] backend process exited unexpectedly");
            let _ = app_handle.emit("backend-crashed", ());
            return;
        }
    });
}

#[cfg(test)]
mod desktop_shell_tests {
    use super::{backend_executable_names, prod_backend_storage_paths, ProdBackendStoragePaths};
    use std::path::Path;

    #[test]
    fn internal_backend_overrides_inherited_lan_configuration() {
        let mut command = std::process::Command::new("not-executed");
        command.env("LAMCORE_HOST", "0.0.0.0");
        command.env("LAMTOOLS_CORE_ALLOW_LAN", "1");
        command.env("LAMTOOLS_CORE_API_TOKEN", "standalone-secret");
        super::configure_internal_backend_access(&mut command);
        let environment: std::collections::HashMap<_, _> = command.get_envs().collect();
        assert_eq!(environment[std::ffi::OsStr::new("LAMCORE_HOST")], Some(std::ffi::OsStr::new("127.0.0.1")));
        assert_eq!(environment[std::ffi::OsStr::new("LAMTOOLS_CORE_ALLOW_LAN")], None);
        assert_eq!(environment[std::ffi::OsStr::new("LAMTOOLS_CORE_API_TOKEN")], None);
    }

    #[test]
    fn backend_executable_name_is_platform_aware() {
        assert_eq!(
            backend_executable_names(true),
            &["sunday-core.exe", "LamCore.exe"][..]
        );
        assert_eq!(backend_executable_names(false), &["LamCore"][..]);
    }

    #[test]
    fn production_storage_keeps_portable_windows_and_uses_linux_user_data() {
        let app_dir = Path::new("/opt/sunday");
        let data_dir = Path::new("/home/user/.local/share/com.lamtools.lamcore");
        assert_eq!(
            prod_backend_storage_paths(app_dir, data_dir, false),
            ProdBackendStoragePaths {
                lam_home: app_dir.join(".lam"),
                data_dir: app_dir.join(".lam"),
                projects_root: app_dir.join("lam_projects"),
            }
        );
        assert_eq!(
            prod_backend_storage_paths(app_dir, data_dir, true),
            ProdBackendStoragePaths {
                lam_home: data_dir.join(".lam"),
                data_dir: data_dir.join("data"),
                projects_root: data_dir.join("lam_projects"),
            }
        );
    }
}

fn reveal_main_window(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

#[cfg(windows)]
fn hide_console(cmd: &mut Command) {
    cmd.creation_flags(CREATE_NO_WINDOW);
}

#[cfg(not(windows))]
fn hide_console(_cmd: &mut Command) {}
