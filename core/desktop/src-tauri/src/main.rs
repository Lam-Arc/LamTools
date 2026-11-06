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

mod migration;
mod p2p_host;
mod pet;
mod split_pane;
#[cfg(windows)]
mod windows_close_request;
#[cfg(windows)]
mod windows_snap_layout;
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x08000000;
const TRAY_ID: &str = "lamtools-tray";
const TRAY_OPEN_MAIN_ID: &str = "tray-open-main";
// user:“桌宠是独立系统：即使桌宠隐藏，也可使用 Ping”+(托盘可直接开/关桌宠覆盖层)
const TRAY_PET_ID: &str = "tray-pet";
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
    stop_backend(state.inner());
    app.exit(0);
}

#[tauri::command]
fn quit_app(app: tauri::AppHandle) {
    request_quit(&app);
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

/// 在后台线程里把桌宠覆盖层建出来。
///
/// user:“点击打开桌宠后未响应了”+(托盘菜单事件跑在主线程上，而建窗口要等事件循环
/// 把窗口真正造好再回来；在主线程里同步等就是死锁，整个应用表现为“未响应”。
/// 建窗放到后台线程，事件循环始终可以继续处理消息。)
/// 等应用事件循环真的跑起来之后再建桌宠覆盖层窗口。
///
/// user:“从你启动开始就一直是黑屏未响应状态”+(启动早期建出来的覆盖层窗口是个
/// 半成品：所有窗口 API 都收不到响应、网页永远不加载，还会一直挡着后面正常的
/// 建窗。这里改成失败就等一会儿重试，直到拿到真窗口为止。)
fn open_pet_overlay_when_ready(app: &tauri::AppHandle) -> Result<pet::OverlayBounds, String> {
    let mut last_error = String::from("overlay window was never created");
    for _ in 0..40 {
        match pet::open_overlay_and_poll(app.clone()) {
            Ok(bounds) => return Ok(bounds),
            Err(error) => last_error = error,
        }
        std::thread::sleep(Duration::from_millis(500));
    }
    Err(last_error)
}

fn spawn_pet_overlay_thread(app: &tauri::AppHandle) -> Result<(), String> {
    let handle = app.clone();
    std::thread::Builder::new()
        .name("pet-overlay-open".into())
        .spawn(move || {
            // 托盘菜单线程自己建窗：这里不在任何 WebView2 回调里，直接走同步版。
            match pet::open_overlay_and_poll(handle.clone()) {
                Ok(_) => {
                    // 页面 ready 后会再刷新一次；这里先把托盘状态从“打开”切过去。
                    let _ = refresh_tray_menu(&handle);
                }
                Err(error) => {
                    eprintln!("[sunday] desktop pet overlay failed: {error}");
                }
            }
        })
        .map(|_| ())
        .map_err(|error| error.to_string())
}

fn handle_tray_menu(app: &tauri::AppHandle, event: MenuEvent) {
    match event.id().as_ref() {
        TRAY_OPEN_MAIN_ID => reveal_main_window(app),
        TRAY_PET_ID => {
            // user:"那个托盘的桌宠，不要一直都叫“打开桌宠”，应该是“打开桌宠”和“关闭桌宠”"+
            // (入口按覆盖层真实可见性切换：开着就关，关着就开。)
            if pet::overlay_is_open(app) {
                if let Err(error) = pet::close_overlay_sync(app) {
                    eprintln!("[sunday] desktop pet overlay close failed: {error}");
                }
                let _ = refresh_tray_menu(app);
            } else if let Err(error) = spawn_pet_overlay_thread(app) {
                eprintln!("[sunday] desktop pet overlay failed: {error}");
            }
        }
        TRAY_QUIT_ID => request_quit(app),
        _ => {}
    }
}

/// 托盘菜单的桌宠入口：打开时“关闭桌宠”，关闭时“打开桌宠”。
///
/// user:"应该是“打开桌宠”和“关闭桌宠”"+(状态变化时重建菜单；原生托盘菜单重建
/// 成本很低，比维护一个外部 CheckMenuItem 句柄可靠。)
fn refresh_tray_menu(app: &tauri::AppHandle) -> tauri::Result<()> {
    let open = pet::overlay_is_open(app);
    let open_main = MenuItem::with_id(app, TRAY_OPEN_MAIN_ID, "打开界面", true, None::<&str>)?;
    let pet_label = if open { "关闭桌宠" } else { "打开桌宠" };
    let pet_item = MenuItem::with_id(app, TRAY_PET_ID, pet_label, true, None::<&str>)?;
    let quit = MenuItem::with_id(app, TRAY_QUIT_ID, "退出", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&open_main, &pet_item, &quit])?;
    if let Some(tray) = app.tray_by_id(TRAY_ID) {
        tray.set_menu(Some(menu))?;
    }
    Ok(())
}

fn setup_tray(app: &tauri::App) -> Result<(), Box<dyn std::error::Error>> {
    let open_main = MenuItem::with_id(app, TRAY_OPEN_MAIN_ID, "打开界面", true, None::<&str>)?;
    // user:“托盘无打开桌宠选项”+(托盘必须给出桌宠入口，否则用户找不到打开的路径)
    let open_pet = MenuItem::with_id(app, TRAY_PET_ID, "打开桌宠", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, TRAY_QUIT_ID, "退出", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&open_main, &open_pet, &quit])?;

    let mut builder = TrayIconBuilder::with_id(TRAY_ID)
        .menu(&menu)
        .tooltip("Sunday")
        .show_menu_on_left_click(true)
        .on_menu_event(handle_tray_menu);
    if let Some(icon) = app.default_window_icon().cloned() {
        builder = builder.icon(icon);
    }
    builder.build(app)?;
    // 自启/CLI 可能已经把覆盖层打开了：按真实可见性初始化菜单文案。
    refresh_tray_menu(app.handle())?;

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

/// 给配置窗口设置与运行时窗口相同的 WebView2 参数。
/// 见 `pet::browser_args` 的说明：基线防节流参数 + 自动化模式注入的调试参数。
fn apply_browser_args(mut context: tauri::Context<tauri::Wry>) -> tauri::Context<tauri::Wry> {
    let browser_args = pet::browser_args_from_env();
    for window in &mut context.config_mut().app.windows {
        window.additional_browser_args = Some(browser_args.clone());
    }
    context
}

/// 桌宠覆盖层安全兜底：任何 panic 先把全屏置顶窗口关掉，再走原 panic 输出。
/// user:"那个'强制置顶'，你一定要给我记着。如果它一旦发生错误，把它退出置顶
/// 或者直接关闭。不然的话，就会出现无法访问，但是直接把我的屏幕全给占掉"
fn install_overlay_panic_safety() {
    let previous = std::panic::take_hook();
    std::panic::set_hook(Box::new(move |info| {
        pet::emergency_close_overlays();
        previous(info);
    }));
}

/// What a second instance does: hand its command line to the running one.
///
/// user:“把桌面端跑起来”+(开发版必须能和正在运行的正式版并存：单实例锁按 bundle
/// identifier 建全局互斥量，正式版在跑时 dev 实例一启动就被杀掉，窗口永远不会出现。)
#[cfg_attr(debug_assertions, allow(dead_code))]
fn on_second_instance(app: &tauri::AppHandle, args: Vec<String>, _cwd: String) {
    // user:“你为什么不CLI先行用CLI直接执行 ping 环内的操作”+(第二实例带
    // `--ping-commit=<扇区id>` 时直接驱动正在运行的实例执行该扇区，测完后退出。)
    if let Some(sector) = ping_commit_from_args(&args) {
        pet::simulate_ping_commit(app, &sector);
        return;
    }
    // 隔离测试：冻结截图页心跳，让看门狗把"页面死掉"的整屏窗口收回去。
    if args.iter().any(|arg| arg == "--capture-freeze-heartbeat") {
        pet::simulate_capture_heartbeat_stall(app);
        return;
    }
    // 隔离测试：只在本实例打开/收起 Ping 环，不触发正式实例的全局快捷键。
    if args.iter().any(|arg| arg == "--ping-ring-open") {
        pet::simulate_ping_ring(app, "down");
        return;
    }
    if args.iter().any(|arg| arg == "--ping-ring-close") {
        pet::simulate_ping_ring(app, "up");
        return;
    }
    // Focus the existing window instead of starting a second instance.
    reveal_main_window(app);
}

fn main() {
    install_overlay_panic_safety();
    // user:“迁移”+(应用标识从 com.lamtools.lamcore 改成 com.lamtools.sunday，
    // 旧数据目录必须先搬到新标识下，再让 Tauri 解析 app_data_dir。)
    migration::migrate_legacy_identity();

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
        quitting: AtomicBool::new(false),
    };

    let builder = tauri::Builder::default();
    // Single-instance guard: two instances would each spawn a backend
    // writing the same .lam/core.db (SQLite lock storms, config
    // clobbering) (audit 20 S3).
    //
    // user:“把桌面端跑起来”+(只在正式版注册：锁键是 bundle identifier，开发版与
    // 已安装的正式版相同，正式版在跑时 dev 实例会被直接杀掉，窗口永远不出现。)
    #[cfg(not(debug_assertions))]
    let builder = builder.plugin(tauri_plugin_single_instance::init(on_second_instance));
    builder
        .manage(state)
        // user:“你现在负责在现有 Sunday 项目中实现「Sunday 桌宠 V1.0」”+(桌宠覆盖层状态独立托管，禁用时不注册任何窗口/钩子)
        .manage(pet::PetState::default())
        // user:“P2P 作为独立、可复用的传输组件”+(桌面只托管那个进程与它的票据)。
        .manage(p2p_host::P2pHostState::default())
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
            // user:“你看看 ping 环 要不也自己做窗口？”+(Ping 覆盖层独立于桌宠：
            // 应用启动就把窗口准备好（隐藏），全局热键随时可用；轮询直到事件循环就绪。)
            let ping_overlay_app = app.handle().clone();
            thread::spawn(move || {
                for _ in 0..50 {
                    if pet::ensure_ping_overlay(&ping_overlay_app).is_ok() {
                        break;
                    }
                    thread::sleep(std::time::Duration::from_millis(200));
                }
            });
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
                            eprintln!("[sunday] backend state lock failed");
                            return;
                        };
                        *api_slot = Some(api_base.clone());
                        drop(api_slot);
                        // Watch the backend process: if it dies mid-run (panic,
                        // fatal Python exception) the frontend gets an event and
                        // can show a recovery banner instead of silently failing
                        // every request (audit 20 S3).
                        let app_handle = app.clone();
                        spawn_backend_watcher(app_handle);
                        // user:“打开桌宠你用 cli”+(带 --pet 或 --open-pet 启动就直接
                        // 打开覆盖层，不依赖托盘，自动化也能直接驱动。)
                        // 既支持命令行参数，也支持环境变量：tauri dev 会把 `--` 之后的
                        // 参数塞进 cargo 自己的参数位，环境变量更稳。
                        if pet::open_requested() {
                            match open_pet_overlay_when_ready(&app) {
                                Ok(bounds) => eprintln!(
                                    "[sunday] desktop pet overlay opened via --open-pet: {}x{} at ({}, {})",
                                    bounds.width, bounds.height, bounds.x, bounds.y
                                ),
                                Err(error) => eprintln!("[sunday] --open-pet failed: {error}"),
                            }
                        }
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
            p2p_host::p2p_ticket,
            p2p_host::p2p_qr,
            p2p_host::p2p_serve_start,
            p2p_host::p2p_serve_stop,
            p2p_host::p2p_status,
            p2p_host::p2p_devices,
            p2p_host::p2p_revoke,
            ping,
            get_app_info,
            pick_directory,
            pick_files,
            open_external_url,
            pet::pet_overlay_open,
            pet::pet_overlay_close,
            pet::pet_overlay_heartbeat,
            pet::pet_overlay_ready,
            pet::pet_set_interactive_rects,
            pet::pet_main_window_focused,
            // user:“你看看 ping 环 要不也自己做窗口？”+(Ping 独立覆盖层)
            pet::pet_ping_overlay_open,
            pet::pet_ping_overlay_show,
            pet::pet_ping_overlay_hide,
            pet::pet_ping_set_interactive_rects,
            pet::pet_ping_set_input_mode,
            // user:“卡片即窗口，把 ping 和桌宠拆分开”+(Ping 卡片独立窗口)
            pet::pet_open_ping_card,
            pet::pet_show_ping_card,
            pet::pet_close_ping_card,
            // user:“ping完之后用一个合适的大小打开Sunday本体”+(复用主窗口)
            pet::pet_open_main_session,
            pet::pet_set_input_mode,
            pet::pet_set_z_mode,
            pet::pet_monitors,
            pet::pet_cursor,
            pet::pet_capture_monitor_under_cursor,
            pet::pet_capture_monitor,
            // user:“重新设计与实现 Ping 的框选工具”+(独立截图窗口 + 心跳看门狗)
            pet::pet_ping_capture_open,
            pet::pet_ping_capture_frame,
            pet::pet_ping_capture_show,
            pet::pet_ping_capture_heartbeat,
            pet::pet_ping_capture_close,
            pet::pet_hotkey_set,
            pet::pet_default_work_root,
            pet::pet_desktop_windows,
            pet::pet_autostart,
            pet::pet_config_read,
            pet::pet_config_patch,
            pet::pet_scan_import,
            pet::pet_read_import_asset,
            pet::pet_read_zip,
            pet::pet_read_image,
            pet::pet_install_pack,
            pet::pet_write_pack_asset,
            pet::pet_write_pack_bundle,
            pet::pet_pack_asset,
            pet::pet_pick_import,
            pet::pet_pick_import_file
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
                    
                    
                    stop_backend(state.inner());
                }
                _ => {}
            }
        })
        .build(apply_browser_args(tauri::generate_context!()))
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
    // user:“你给开发版改一下端口吧”+(开发实例优先用固定端口，被占时才退回随机空闲端口，
    // 避免和其它实例抢同一个监听。)
    let port = if cfg!(debug_assertions) {
        std::env::var("LAMTOOLS_DEV_BACKEND_PORT")
            .ok()
            .and_then(|value| value.parse::<u16>().ok())
            .filter(|port| TcpListener::bind(("127.0.0.1", *port)).is_ok())
            .unwrap_or(pick_free_port()?)
    } else {
        pick_free_port()?
    };
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
            eprintln!("[sunday] backend process-tree guard unavailable: {error}");
        }
    }
    *child_slot = Some(child);
    drop(child_slot);

    wait_for_health(port, state)?;
    eprintln!(
        "[sunday] backend ready in {} ms",
        started_at.elapsed().as_millis()
    );
    Ok(api_base)
}

fn configure_internal_backend_access(command: &mut Command) {
    // Desktop's API must not inherit standalone LAN configuration/credentials.
    command
        .env("SUNDAY_CORE_HOST", "127.0.0.1")
        // Same compatibility window as SUNDAY_CORE_PORT.
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
        // user:“后端是不是与你自己冲突了？能解决吗？”+(开发实例用独立数据目录：
        // 数据库、配置、项目都不与正式 .lam 共享，避免锁库与串扰。)
        .env(
            "LAMTOOLS_HOME",
            std::env::var("LAMTOOLS_PET_DEV_HOME")
                .map(PathBuf::from)
                .unwrap_or_else(|_| core_dir.join(".lam"))
                .to_string_lossy()
                .into_owned(),
        )
        .env(
            "LAMTOOLS_CORE_DATA_DIR",
            std::env::var("LAMTOOLS_PET_DEV_HOME")
                .map(PathBuf::from)
                .unwrap_or_else(|_| core_dir.join(".lam"))
                .to_string_lossy()
                .into_owned(),
        )
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
    // The PyInstaller output is bundled as a resource at dist/SundayCore/.
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
    cmd.env("SUNDAY_CORE_PORT", port.to_string())
        // A stale portable backend assembled before the rename still reads the
        // old spelling. Both names carry the same value during the migration.
        .env("LAMCORE_PORT", port.to_string())
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
/// anonymous name. `SundayCore.exe` is the raw PyInstaller artifact name used
/// by portable copies and the project dist directory, and `LamCore.exe` stays
/// as a fallback for layouts assembled from pre-migration builds. Linux uses
/// the extension-less forms, which the Linux bundle and its acceptance scripts
/// pin.
fn backend_executable_names(windows: bool) -> &'static [&'static str] {
    if windows {
        &["sunday-core.exe", "SundayCore.exe", "LamCore.exe"]
    } else {
        &["sunday-core", "SundayCore", "LamCore"]
    }
}

fn find_backend_exe(app: &tauri::AppHandle) -> Result<PathBuf, Box<dyn std::error::Error>> {
    let executable_names = backend_executable_names(cfg!(windows));
    // 1) Tauri resource directory (bundled flat)
    let resource = app.path().resource_dir()?.join("sunday-backend");
    // 2) Adjacent to the current exe (portable layout)
    let adjacent = env::current_exe()?
        .parent()
        .ok_or("cannot locate app directory")?
        .join("SundayCore");
    // 3) Legacy portable layout from pre-migration builds
    let legacy_adjacent = env::current_exe()?
        .parent()
        .ok_or("cannot locate app directory")?
        .join("LamCore");
    // 4) Project dist directory (dev convenience)
    let project_dist = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent() // src-tauri/ -> desktop/
        .and_then(|p| p.parent()) // desktop/ -> core/
        .and_then(|p| p.parent()) // core/ -> repo root
        .ok_or("cannot locate project root")?
        .join("dist")
        .join("SundayCore");
    let legacy_project_dist = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(|p| p.parent())
        .and_then(|p| p.parent())
        .ok_or("cannot locate project root")?
        .join("dist")
        .join("LamCore");

    for directory in [
        &resource,
        &adjacent,
        &legacy_adjacent,
        &project_dist,
        &legacy_project_dist,
    ] {
        for executable_name in executable_names {
            let candidate = directory.join(executable_name);
            if candidate.exists() {
                return Ok(candidate);
            }
        }
    }

    Err(format!(
        "Sunday backend executable ({}) not found at any of:\n  {}\n  {}\n  {}\n  {}\n  {}",
        executable_names.join(" or "),
        resource.display(),
        adjacent.display(),
        legacy_adjacent.display(),
        project_dist.display(),
        legacy_project_dist.display(),
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
            eprintln!("[sunday] backend process exited unexpectedly");
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
        command.env("SUNDAY_CORE_HOST", "0.0.0.0");
        command.env("LAMTOOLS_CORE_ALLOW_LAN", "1");
        command.env("LAMTOOLS_CORE_API_TOKEN", "standalone-secret");
        super::configure_internal_backend_access(&mut command);
        let environment: std::collections::HashMap<_, _> = command.get_envs().collect();
        assert_eq!(
            environment[std::ffi::OsStr::new("SUNDAY_CORE_HOST")],
            Some(std::ffi::OsStr::new("127.0.0.1"))
        );
        assert_eq!(
            environment[std::ffi::OsStr::new("LAMCORE_HOST")],
            Some(std::ffi::OsStr::new("127.0.0.1"))
        );
        assert_eq!(
            environment[std::ffi::OsStr::new("LAMTOOLS_CORE_ALLOW_LAN")],
            None
        );
        assert_eq!(
            environment[std::ffi::OsStr::new("LAMTOOLS_CORE_API_TOKEN")],
            None
        );
    }

    #[test]
    fn backend_executable_name_is_platform_aware() {
        assert_eq!(
            backend_executable_names(true),
            &["sunday-core.exe", "SundayCore.exe", "LamCore.exe"][..]
        );
        assert_eq!(
            backend_executable_names(false),
            &["sunday-core", "SundayCore", "LamCore"][..]
        );
    }

    #[test]
    fn production_storage_keeps_portable_windows_and_uses_linux_user_data() {
        let app_dir = Path::new("/opt/sunday");
        let data_dir = Path::new("/home/user/.local/share/com.lamtools.sunday");
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

/// 从第二实例命令行里取 `--ping-commit=<扇区id>`（或空格分隔形式）。
///
/// user:“你为什么不CLI先行用CLI直接执行 ping 环内的操作”+(CLI 直接驱动轮盘，
/// 自动化测试不再依赖真实键鼠操作。)
fn ping_commit_from_args(args: &[String]) -> Option<String> {
    let mut iter = args.iter();
    while let Some(arg) = iter.next() {
        if let Some(value) = arg.strip_prefix("--ping-commit=") {
            let trimmed = value.trim();
            if !trimmed.is_empty() {
                return Some(trimmed.to_string());
            }
        }
        if arg == "--ping-commit" {
            if let Some(value) = iter.next() {
                let trimmed = value.trim();
                if !trimmed.is_empty() {
                    return Some(trimmed.to_string());
                }
            }
        }
    }
    None
}

#[cfg(windows)]
fn hide_console(cmd: &mut Command) {
    cmd.creation_flags(CREATE_NO_WINDOW);
}

#[cfg(not(windows))]
fn hide_console(_cmd: &mut Command) {}
