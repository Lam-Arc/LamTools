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
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
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
    tray::{MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Emitter, Manager, Url, WebviewWindow, WebviewWindowBuilder, WebviewUrl,
};

mod computer_use_overlay;
mod backend_startup;
// user:“一个新模块，不要两套浏览器”+(浏览器宿主全部收在 browser/，split_pane 只留文件能力)。
mod browser;
mod desktop_overlay;
mod tray_panel;
// user:“优先用 Windows 内置 OCR（Windows.Media.Ocr）”+(截图取字单独一个模块，只做
// 「图片字节 → 文字 + 逐行位置」；截图与裁剪仍归 computer_use/capture 与 Ping 界面)。
mod ocr;
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

pub(crate) struct BackendState {
    pub(crate) api_base: Mutex<Option<String>>,
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

/// user:“依旧无法最小化”+(不需要人点也能判定：环境变量 `SUNDAY_WINDOW_PROBE=1` 时，
/// 启动若干秒后自己调一次 minimize / maximize，并打印返回值与真实窗口状态。
/// 这一步用来区分「点击没到命令」与「命令到了但窗口 API 在子 webview 可见时失效」。)
#[cfg(windows)]
fn spawn_window_probe(app: tauri::AppHandle) {
    if std::env::var("SUNDAY_WINDOW_PROBE").ok().as_deref() != Some("1") {
        return;
    }
    std::thread::spawn(move || {
        // 两轮：第一轮通常在网页标签还没打开时（对照组），第二轮等网页起来后（实验组）。
        for round in 1..=2u32 {
            std::thread::sleep(std::time::Duration::from_secs(if round == 1 { 12 } else { 28 }));
            let Some(window) = app.get_webview_window("main") else {
                eprintln!("[window-probe] round={round} main window not found");
                return;
            };
            eprintln!("[window-probe] round={round} begin");
            let result = window.minimize();
            std::thread::sleep(std::time::Duration::from_millis(900));
            eprintln!(
                "[window-probe] round={round} minimize result={:?} is_minimized={:?}",
                result,
                window.is_minimized()
            );
            let _ = window.unminimize();
            std::thread::sleep(std::time::Duration::from_millis(600));
            let result = window.maximize();
            std::thread::sleep(std::time::Duration::from_millis(900));
            eprintln!(
                "[window-probe] round={round} maximize result={:?} is_maximized={:?} size={:?}",
                result,
                window.is_maximized(),
                window.inner_size()
            );
            let _ = window.unmaximize();
            std::thread::sleep(std::time::Duration::from_millis(600));
            eprintln!(
                "[window-probe] round={round} restore is_maximized={:?} size={:?}",
                window.is_maximized(),
                window.inner_size()
            );
        }
    });
}

#[cfg(not(windows))]
fn spawn_window_probe(_app: tauri::AppHandle) {}

#[tauri::command]
fn minimize_window(window: tauri::WebviewWindow) {
    // user:“窗口按钮改成纯 DOM 驱动…在点击路径上加一条无条件（非 dev-only 也建议保留）日志”+
    // (这条日志就是以后排查「点了没反应」的唯一证据：出现 = 点击确实到了命令；
    //  不出现 = 点击在到达应用之前就丢了，直接去看窗口样式/浮层那条线。)
    let result = window.minimize();
    let state = window.is_minimized();
    eprintln!(
        "[window-ctl] minimize source=dom label={} result={result:?} is_minimized={state:?}",
        window.label()
    );
}

#[tauri::command]
fn toggle_maximize_window(window: tauri::WebviewWindow) {
    // user:“窗口按钮改成纯 DOM 驱动”+(同上：无条件日志，record 点击是否真的进到命令)。
    let before = window.is_maximized().unwrap_or(false);
    let result = if before {
        window.unmaximize()
    } else {
        window.maximize()
    };
    let after = window.is_maximized();
    eprintln!(
        "[window-ctl] toggle-maximize source=dom label={} before={before} result={result:?} after={after:?} inner={:?}",
        window.label(),
        window.inner_size()
    );
}

#[tauri::command]
fn set_maximize_button_bounds(
    window: tauri::WebviewWindow,
    webview: tauri::Webview,
    x: f64,
    top: f64,
    width: f64,
    height: f64,
) -> Result<(), String> {
    // user:“去掉原生命中区…命令保留但空实现，返回 Ok，避免前端报错”+
    // (这套「按前端矩形摆透明子窗口」的链路已证伪：`[snap-click]` 从 0 命中，
    //  且前端报来的按钮 x=899.7 与屏幕实际 x≈1348 不符。命令留着只为兼容前端，
    //  等前端那条调用移除后再删。)
    let _ = (window, webview, x, top, width, height);
    Ok(())
}

#[tauri::command]
fn close_window(window: tauri::WebviewWindow) {
    // user:“窗口按钮改成纯 DOM 驱动”+(关闭也留一条无条件日志，三个按钮的证据口径一致)。
    let result = window.close();
    eprintln!(
        "[window-ctl] close source=dom label={} result={result:?}",
        window.label()
    );
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
    // user:“把这台电脑上的桌面端跑起来”+(传输进程同为子进程，退出路径也要一起收掉)。
    // user:“无需做安全边界”+(退出时把桌面操作覆盖层一起收掉，不留残窗)。
    if let Some(window) = app.get_webview_window(computer_use_overlay::OVERLAY_LABEL) {
        let _ = window.close();
    }
    p2p_host::stop(app.state::<p2p_host::P2pHostState>().inner());
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


/// 托盘打开标注层：和桌宠一样放到后台线程建窗，避免主线程同步等窗口就绪。
fn spawn_overlay_thread(app: &tauri::AppHandle) -> Result<(), String> {
    let handle = app.clone();
    std::thread::Builder::new()
        .name("desktop-overlay-open".into())
        .spawn(move || {
            match tauri::async_runtime::block_on(desktop_overlay::desktop_overlay_open(handle.clone())) {
                Ok(_) => {}
                Err(error) => eprintln!("[sunday] desktop overlay failed: {error}"),
            }
        })
        .map(|_| ())
        .map_err(|error| error.to_string())
}

/// 托盘左/右键都打开自绘面板：原生菜单已经完全退场。
///
/// user:“托盘样式重做”“只做自绘面板”+(Windows 原生托盘菜单改不了配色和圆角，
/// 点图标改成弹出独立小窗，打开界面/桌宠/标注层/退出都在窗口里完成。)
fn handle_tray_click(app: &tauri::AppHandle, position: tauri::PhysicalPosition<f64>) {
    tray_panel::toggle_at(app, (position.x.round() as i32, position.y.round() as i32));
}

fn setup_tray(app: &tauri::App) -> Result<(), Box<dyn std::error::Error>> {
    let mut builder = TrayIconBuilder::with_id(TRAY_ID)
        .tooltip("Sunday")
        // 不再挂原生菜单：点图标弹自绘面板，菜单和面板不同时存在。
        .show_menu_on_left_click(false)
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                position,
                button_state,
                ..
            } = event
            {
                // Windows 会同时派发按下和抬起，只认抬起，避免一次点击开两次面板。
                if button_state == MouseButtonState::Up {
                    handle_tray_click(tray.app_handle(), position);
                }
            }
        });
    if let Some(icon) = app.default_window_icon().cloned() {
        builder = builder.icon(icon);
    }
    builder.build(app)?;
    Ok(())
}

// user:“会闪退，修复”+(启动期主窗口句柄尚未就绪或已关闭时，Win32 钩子挂载不得用 `?` 终止 `.setup()`；
// 应幂等跳过已挂载项并按需延后重试，彻底消除启动/重入时的 panic 闪退。)
#[cfg_attr(not(windows), allow(dead_code))]
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
struct MainWindowHookProgress {
    snap_layout: bool,
    close_request: bool,
    taskbar_icon: bool,
}

#[cfg_attr(not(windows), allow(dead_code))]
impl MainWindowHookProgress {
    fn is_complete(&self) -> bool {
        self.snap_layout && self.close_request && self.taskbar_icon
    }

    fn try_step<FSnap, FClose, FIcon>(
        &mut self,
        mut install_snap: FSnap,
        mut install_close: FClose,
        mut install_icon: FIcon,
    ) -> String
    where
        FSnap: FnMut() -> Result<(), String>,
        FClose: FnMut() -> Result<(), String>,
        FIcon: FnMut() -> Result<(), String>,
    {
        let mut pending = Vec::new();
        if !self.snap_layout {
            match install_snap() {
                Ok(()) => self.snap_layout = true,
                Err(error) => pending.push(format!("snap_layout={error}")),
            }
        }
        if !self.close_request {
            match install_close() {
                Ok(()) => self.close_request = true,
                Err(error) => pending.push(format!("close_request={error}")),
            }
        }
        if !self.taskbar_icon {
            match install_icon() {
                Ok(()) => self.taskbar_icon = true,
                Err(error) => pending.push(format!("taskbar_icon={error}")),
            }
        }
        pending.join("; ")
    }
}

#[cfg(windows)]
fn install_taskbar_icon_for_window(window: &WebviewWindow) -> Result<(), String> {
    use windows_sys::Win32::{
        System::LibraryLoader::GetModuleHandleW,
        UI::WindowsAndMessaging::{LoadImageW, SendMessageW, IMAGE_ICON, LR_SHARED, WM_SETICON},
    };
    let hwnd = window
        .hwnd()
        .map_err(|error| format!("main window handle unavailable: {error}"))?
        .0 as windows_sys::Win32::Foundation::HWND;
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
        return Err(std::io::Error::last_os_error().to_string());
    }
    unsafe {
        SendMessageW(hwnd, WM_SETICON, 1, icon as isize);
    }
    Ok(())
}

#[cfg(windows)]
fn run_main_window_hooks_pass(
    app: &tauri::AppHandle,
    progress: &Mutex<MainWindowHookProgress>,
) -> Option<String> {
    let window = app.get_webview_window("main");
    let Ok(mut guard) = progress.lock() else {
        return Some("hook progress lock poisoned".to_string());
    };
    let summary = guard.try_step(
        || match window.as_ref() {
            Some(win) => windows_snap_layout::install(win),
            None => Err("main window missing".to_string()),
        },
        || match window.as_ref() {
            Some(win) => windows_close_request::install(win),
            None => Err("main window missing".to_string()),
        },
        || match window.as_ref() {
            Some(win) => install_taskbar_icon_for_window(win),
            None => Err("main window missing".to_string()),
        },
    );
    if guard.is_complete() {
        None
    } else {
        Some(summary)
    }
}

#[cfg(windows)]
fn install_main_window_hooks(app: &tauri::App) {
    let progress = std::sync::Arc::new(Mutex::new(MainWindowHookProgress::default()));
    let Some(initial_summary) = run_main_window_hooks_pass(app.handle(), &progress) else {
        return;
    };

    eprintln!(
        "[sunday] main window native hooks deferred during setup ({initial_summary}); scheduling UI-thread retry"
    );
    let app_handle = app.handle().clone();
    let _ = thread::Builder::new()
        .name("main-window-hooks".into())
        .spawn(move || {
            let mut last_summary = initial_summary;
            for _ in 0..50 {
                if app_handle.state::<BackendState>().quitting.load(Ordering::SeqCst) {
                    return;
                }
                let (tx, rx) = std::sync::mpsc::channel();
                let main_app = app_handle.clone();
                let main_progress = std::sync::Arc::clone(&progress);
                if app_handle
                    .run_on_main_thread(move || {
                        let _ = tx.send(run_main_window_hooks_pass(&main_app, &main_progress));
                    })
                    .is_err()
                {
                    return;
                }
                match rx.recv_timeout(std::time::Duration::from_millis(500)) {
                    Ok(None) => {
                        eprintln!("[sunday] main window native hooks attached on deferred retry");
                        return;
                    }
                    Ok(Some(summary)) => {
                        last_summary = summary;
                    }
                    Err(_) => return,
                }
                thread::sleep(std::time::Duration::from_millis(100));
            }
            eprintln!(
                "[sunday] main window native hooks stayed unavailable after retries (non-fatal): {last_summary}"
            );
        });
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

// user:“查清 constant 安装版为什么退出 + 修掉事件风暴”+(崩溃可观测性：Rust 侧
// panic 落盘到 `.lam/crash-<ts>.log`；正常与异常退出都写一条 exit reason=/code=
// 到 `.lam/desktop-shell.log`。上一轮安装版 03:35 退出时既没有 CrashDump、事件
// 日志也没有记录，只能靠日志猜，这次把结论直接留在磁盘上。)
static LAM_HOME: Mutex<Option<PathBuf>> = Mutex::new(None);

/// 后端 storage paths 解析完成后调用；之后所有落盘日志都指向同一处 .lam。
fn remember_lam_home(path: &Path) {
    if let Ok(mut guard) = LAM_HOME.lock() {
        *guard = Some(path.to_path_buf());
    }
}

/// 解析不到 .lam（例如早期 panic）时回退到可执行文件旁的便携布局。
fn lam_home_dir() -> Option<PathBuf> {
    if let Some(path) = LAM_HOME.lock().ok().and_then(|guard| guard.clone()) {
        return Some(path);
    }
    env::current_exe()
        .ok()?
        .parent()
        .map(|directory| directory.join(".lam"))
}

/// 把 UNIX 秒换算成 UTC 民用时间（不引入 chrono，避免为了一行时间戳加依赖）。
fn utc_parts(seconds: i64) -> (i64, u32, u32, u32, u32, u32) {
    let days = seconds.div_euclid(86_400);
    let remainder = seconds.rem_euclid(86_400);
    let shifted = days + 719_468;
    let era = if shifted >= 0 { shifted } else { shifted - 146_096 } / 146_097;
    let day_of_era = (shifted - era * 146_097) as u64;
    let year_of_era =
        (day_of_era - day_of_era / 1_460 + day_of_era / 36_524 - day_of_era / 146_096) / 365;
    let year = year_of_era as i64 + era * 400;
    let day_of_year = day_of_era - (365 * year_of_era + year_of_era / 4 - year_of_era / 100);
    let month_prime = (5 * day_of_year + 2) / 153;
    let day = (day_of_year - (153 * month_prime + 2) / 5 + 1) as u32;
    let month = (if month_prime < 10 { month_prime + 3 } else { month_prime - 9 }) as u32;
    let year = year + i64::from(month <= 2);
    (
        year,
        month,
        day,
        (remainder / 3_600) as u32,
        ((remainder % 3_600) / 60) as u32,
        (remainder % 60) as u32,
    )
}

fn iso_stamp() -> String {
    let seconds = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs() as i64;
    let (year, month, day, hour, minute, second) = utc_parts(seconds);
    format!("{year:04}-{month:02}-{day:02}T{hour:02}:{minute:02}:{second:02}Z")
}

fn compact_stamp() -> String {
    let seconds = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs() as i64;
    let (year, month, day, hour, minute, second) = utc_parts(seconds);
    format!("{year:04}{month:02}{day:02}-{hour:02}{minute:02}{second:02}")
}

/// 一条桌面壳层事件：stderr 给人看，`.lam/desktop-shell.log` 给事后取证。
fn append_shell_log(line: &str) {
    eprintln!("[sunday] {line}");
    let Some(home) = lam_home_dir() else {
        return;
    };
    let path = home.join("desktop-shell.log");
    if let Some(parent) = path.parent() {
        let _ = fs::create_dir_all(parent);
    }
    if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(&path) {
        let _ = writeln!(file, "{} {}", iso_stamp(), line);
    }
}

fn write_panic_report(message: &str, location: &str, thread_name: &str) {
    let backtrace = std::backtrace::Backtrace::force_capture();
    let body = format!(
        "time={}\npid={}\nthread={thread_name}\nlocation={location}\nmessage={message}\n\nbacktrace:\n{backtrace}\n",
        iso_stamp(),
        std::process::id(),
    );
    if let Some(home) = lam_home_dir() {
        if fs::create_dir_all(&home).is_ok() {
            let path = home.join(format!(
                "crash-{}-{}.log",
                compact_stamp(),
                std::process::id()
            ));
            if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(&path) {
                let _ = file.write_all(body.as_bytes());
            }
            append_shell_log(&format!("panic captured path={}", path.display()));
            return;
        }
    }
    // 连 .lam 都写不进去时，至少把原文留在 stderr。
    eprintln!("[sunday] panic (no .lam directory): {body}");
}

fn panic_payload_text(payload: &(dyn std::any::Any + Send)) -> String {
    if let Some(text) = payload.downcast_ref::<&str>() {
        return (*text).to_string();
    }
    if let Some(text) = payload.downcast_ref::<String>() {
        return text.clone();
    }
    "<non-string panic payload>".to_string()
}

fn exit_code_label(status: &std::process::ExitStatus) -> String {
    match status.code() {
        Some(code) if code >= 0 => format!("{code}"),
        Some(code) => format!("{code} (0x{:08X})", code as u32),
        None => "signal".to_string(),
    }
}

/// 桌宠覆盖层安全兜底：任何 panic 先把全屏置顶窗口关掉，再走原 panic 输出。
/// user:"那个'强制置顶'，你一定要给我记着。如果它一旦发生错误，把它退出置顶
/// 或者直接关闭。不然的话，就会出现无法访问，但是直接把我的屏幕全给占掉"
fn install_overlay_panic_safety() {
    let previous = std::panic::take_hook();
    std::panic::set_hook(Box::new(move |info| {
        pet::emergency_close_overlays();
        let location = info
            .location()
            .map(|position| format!("{}:{}:{}", position.file(), position.line(), position.column()))
            .unwrap_or_else(|| "<unknown>".to_string());
        let thread_name = thread::current()
            .name()
            .unwrap_or("<unnamed>")
            .to_string();
        let message = panic_payload_text(info.payload());
        write_panic_report(&message, &location, &thread_name);
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
            // user:“会闪退，修复”+(Win32 主窗口钩子在 `.setup()` 失败或句柄延迟就绪时改为日志+主线程重试，
            // 不再用 `?` 抛 panic 导致应用启动阶段直接闪退)
            #[cfg(windows)]
            install_main_window_hooks(app);
            // user:“依旧无法最小化”+(不需要人点也能判定：`SUNDAY_WINDOW_PROBE=1` 时
            // 启动后自调 minimize/maximize，把返回值与真实窗口状态打进日志)。
            spawn_window_probe(app.handle().clone());

            setup_tray(app)?;
            // user:“把它的入口设成跟 ping 一样”+(标注层圈选改成全局热键，
            // 和 Ping 同一套轮询实现；配置读不到就用默认 Ctrl+Alt+A)。
            desktop_overlay::start_capture_watch(app.handle());
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
                        // user:“发布版本启动后 P2P 服务能真的起来：给出启动状况的可见状态”+
                        // (正式版启动就尝试拉起传输进程，不再等用户打开设备页；成功与失败
                        // 都进 `p2p_status`，设备页直接显示运行状态或失败原因)。
                        p2p_host::autostart(
                            api_base.clone(),
                            app.state::<p2p_host::P2pHostState>().inner().clone(),
                        );
                        // user:“清理无效轮询与监听：把托盘/状态面板里的定时轮询收敛到事件驱动”+
                        // (宿主自己盯着状态，变了才推 `p2p-state`：界面不再每秒问一次，
                        // 没人连的时候也不探测 Core)。
                        p2p_host::start_emitter(
                            app.clone(),
                            app.state::<p2p_host::P2pHostState>().inner().clone(),
                        );
                        // Watch the backend process: if it dies mid-run (panic,
                        // fatal Python exception) the frontend gets an event and
                        // can show a recovery banner instead of silently failing
                        // every request (audit 20 S3).
                        let app_handle = app.clone();
                        spawn_backend_watcher(app_handle);
                        // user:“AI 直接在屏幕上标记、绘制、互动”+(自动化与开发验收
                        // 也要能直接拉起标注层，不依赖托盘点击)。
                        if desktop_overlay::open_requested() {
                            match spawn_overlay_thread(&app) {
                                Ok(()) => eprintln!("[sunday] desktop overlay requested via --open-overlay"),
                                Err(error) => eprintln!("[sunday] --open-overlay failed: {error}"),
                            }
                        }
                        // user:“每个 GUI 能力都要有对应的 CLI 能力”+(托盘点击没法脚本化，
                        // 面板也要能带 --tray-panel 或环境变量直接弹出来做验证)。
                        if tray_panel::open_requested() {
                            let handle = app.clone();
                            std::thread::Builder::new()
                                .name("tray-panel-open".into())
                                .spawn(move || {
                                    let anchor = pet::platform::cursor_position().unwrap_or((0, 0));
                                    tray_panel::toggle_at(&handle, anchor);
                                    eprintln!("[sunday] tray panel requested via --tray-panel");
                                })
                                .map(|_| ())
                                .ok();
                        }
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
            // user:“导航 + 标签骨架”+(浏览器命令全部只允许 main 发起；子 webview 的 label 不在任何 capability 里)。
            browser::browser_open,
            browser::browser_close,
            browser::browser_activate,
            browser::browser_reopen_closed,
            browser::browser_bounds,
            browser::browser_input,
            browser::browser_nav,
            browser::browser_state,
            browser::browser_find,
            browser::browser_zoom,
            browser::browser_fullscreen,
            // user:“会话三态、权限矩阵、证书阻断、站数据清理、越权自检”+(M2 新增命令，同样只允许 main 发起)。
            browser::browser_profiles,
            browser::browser_permission,
            browser::browser_clear_site_data,
            browser::browser_certificate,
            browser::browser_diagnostics,
            browser::browser_downloads,
            browser::browser_download,
            // user:“让 Agent Loop 能直接调用：打开/切换标签、快照、点击、输入、等待、截图”+
            // (M4 新增 5 条：只读 snapshot/screenshot，写操作 act/waitFor 走 human-owned 闸门)。
            browser::browser_snapshot,
            browser::browser_act,
            browser::browser_wait_for,
            browser::browser_screenshot,
            browser::browser_control,
            browser::browser_tabs,
            // user:“以结构化数据作为 Agent 的主要输入”+(搜索适配器用的唯一新命令：按选择器取回
            // DOM 片段，只读、不给页面任何额外能力)。
            browser::browser_html,
            // user:“可在 Rust 侧加一个命令（例如 ocr_image(bytes) → {text, lines[]}）”+
            // (界面与 Agent 工具都调这一条；语言包缺失时报 ocr_language_missing，不返回空字符串)。
            ocr::ocr_image,
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
            // user:“设备切换：多设备时切换当前连接，状态随之更新”+(切换只是改宿主里的
            // 「当前那台」，状态与路径跟着它走)。
            p2p_host::p2p_switch_device,
            // user:“Android 前后台恢复”+(手机宿主回到前台时一次取全恢复所需的快照)。
            p2p_host::p2p_resume_state,
            p2p_host::p2p_devices,
            p2p_host::p2p_revoke,
            p2p_host::p2p_allow,
            // user:“发送入口…选中后开始传输”“支持取消”“完成后可「打开所在文件夹」”+
            // (发送是宿主起一个 `sunday-p2p send` 进程；取消停掉它；定位交给系统文件管理器)。
            p2p_host::p2p_send_file,
            p2p_host::p2p_cancel_transfer,
            p2p_host::p2p_reveal_path,
            // user:“记住用户是否开启远程访问（持久化）”+(设备页的开关读写它；不新增窗口，
            // 只加两个命令)。
            p2p_host::p2p_config_get,
            p2p_host::p2p_config_set,
            ping,
            get_app_info,
            pick_directory,
            pick_files,
            open_external_url,
            computer_use_overlay::computer_use_overlay_open,
            computer_use_overlay::computer_use_overlay_ready,
            computer_use_overlay::computer_use_overlay_close,
            computer_use_overlay::computer_use_overlay_set_rects,
            computer_use_overlay::computer_use_overlay_heartbeat,
            desktop_overlay::desktop_overlay_open,
            desktop_overlay::desktop_overlay_capture_hotkey_set,
            desktop_overlay::desktop_overlay_take_capture,
            desktop_overlay::desktop_overlay_settings,
            desktop_overlay::desktop_overlay_settings_changed,
            tray_panel::tray_panel_state,
            tray_panel::tray_panel_open,
            tray_panel::tray_panel_material,
            tray_panel::tray_panel_fit,
            tray_panel::tray_panel_close,
            tray_panel::tray_panel_toggle,
            tray_panel::tray_panel_reveal_main,
            tray_panel::tray_panel_quit,
            desktop_overlay::desktop_overlay_bounds,
            desktop_overlay::desktop_overlay_ready,
            desktop_overlay::desktop_overlay_close,
            desktop_overlay::desktop_overlay_set_rects,
            desktop_overlay::desktop_overlay_heartbeat,
            desktop_overlay::desktop_overlay_debug_state,
            desktop_overlay::desktop_overlay_set_activatable,
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
            pet::pet_ping_capture_region,
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
                    p2p_host::stop(window.state::<p2p_host::P2pHostState>().inner());
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
    let result = backend_startup::retry_port_conflict(
        || start_backend_attempt(app, state), || stop_backend(state),
    );
    if result.is_err() { stop_backend(state); }
    result
}

fn start_backend_attempt(
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
    // user:“授权表落盘位置”+(浏览器模块不自己猜路径：由宿主把 <lam_home> 注入，
    // 站点授权只写在 `<lam_home>/core/config/browser-permissions.json`)。
    browser::security::set_config_root(paths.lam_home.clone());
    // user:“查清 constant 安装版为什么退出 + 修掉事件风暴”+(崩溃日志写到安装版
    // 真正的 .lam：这里把解析结果交给桌面壳层的日志/panic 落盘统一使用。)
    remember_lam_home(&paths.lam_home);

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
        // user:“调查并检修 constant 内 sunday 出现过的所有报错，整理并给出方案，然后修复，不要出错”+(子进程已退出时立即识别端口冲突，不继续等待90秒或误认其他进程的健康响应)。
        let exited = {
            let mut child_slot = state.child.lock().map_err(|_| "backend state lock failed")?;
            match child_slot.as_mut() {
                Some(child) => child.try_wait()?,
                None => return Err("backend process is missing".into()),
            }
        };
        if let Some(status) = exited {
            return Err(backend_startup::exited_backend_error(port, status));
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
            let backend_pid = child.id();
            let _ = child.kill();
            let _ = child.wait();
            // user:“查清 constant 安装版为什么退出 + 修掉事件风暴”+(正常关闭同样
            // 留一条 exit reason=，才能和上面的 crash 记录对照判断。)
            append_shell_log(&format!(
                "backend exit reason=shutdown code=0 pid={backend_pid} at={}",
                iso_stamp()
            ));
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
        // user:“查清 constant 安装版为什么退出 + 修掉事件风暴”+(异常退出原来只打
        // 一行 eprintln、退出码被 _status 丢掉，事后完全无法判定是崩溃还是被外部
        // 结束；这里把 reason 和 code 一起落盘。)
        let (exited, code) = match guard.as_mut().map(|child| child.try_wait()) {
            Some(Ok(Some(status))) => (true, exit_code_label(&status)),
            Some(Ok(None)) => (false, String::new()),
            _ => (true, "unknown".to_string()), // try_wait error — treat as gone
        };
        if exited {
            *guard = None;
            drop(guard);
            close_backend_job(state.inner());
            append_shell_log(&format!("backend exit reason=crash code={code} at={}", iso_stamp()));
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

    // user:“会闪退，修复”+(启动期主窗口句柄尚未就绪或已关闭时，Win32 钩子挂载不得用 `?` 终止 `.setup()`；
    // 应幂等跳过已挂载项并按需延后重试，彻底消除启动/重入时的 panic 闪退。)
    #[test]
    fn main_window_hooks_recover_after_transient_unavailable_handle() {
        let mut progress = super::MainWindowHookProgress::default();
        let mut snap_attempts = 0usize;
        let mut close_attempts = 0usize;
        let mut icon_attempts = 0usize;

        // First pass: snap layout and close request fail with transient Tauri handle error,
        // while taskbar icon also isn't ready yet — startup MUST NOT abort/panic.
        let summary_1 = progress.try_step(
            || {
                snap_attempts += 1;
                if snap_attempts < 3 {
                    Err("main window handle unavailable: the underlying handle is not available".to_string())
                } else {
                    Ok(())
                }
            },
            || {
                close_attempts += 1;
                if close_attempts < 2 {
                    Err("main window handle unavailable: the underlying handle is not available".to_string())
                } else {
                    Ok(())
                }
            },
            || {
                icon_attempts += 1;
                Ok(())
            },
        );
        assert!(!progress.is_complete());
        assert!(!summary_1.is_empty());
        assert!(progress.taskbar_icon);
        assert!(!progress.snap_layout);
        assert!(!progress.close_request);

        // Second pass: taskbar icon is already done and must NOT be re-run;
        // close_request succeeds now, snap_layout succeeds on pass 3.
        let _ = progress.try_step(
            || {
                snap_attempts += 1;
                if snap_attempts < 3 {
                    Err("main window handle unavailable: the underlying handle is not available".to_string())
                } else {
                    Ok(())
                }
            },
            || {
                close_attempts += 1;
                Ok(())
            },
            || {
                icon_attempts += 1;
                Ok(())
            },
        );
        assert_eq!(icon_attempts, 1);
        assert!(progress.close_request);
        assert!(!progress.snap_layout);

        let summary_3 = progress.try_step(
            || {
                snap_attempts += 1;
                Ok(())
            },
            || {
                close_attempts += 1;
                Ok(())
            },
            || {
                icon_attempts += 1;
                Ok(())
            },
        );
        assert!(progress.is_complete());
        assert!(summary_3.is_empty());
        assert_eq!(snap_attempts, 3);
        assert_eq!(close_attempts, 2);
        assert_eq!(icon_attempts, 1);
    }

    #[test]
    fn main_window_hooks_report_nonfatal_summary_when_handle_stays_unavailable() {
        let mut progress = super::MainWindowHookProgress::default();
        let summary = progress.try_step(
            || Err("main window handle unavailable: the underlying handle is not available".to_string()),
            || Err("main window handle unavailable: the underlying handle is not available".to_string()),
            || Err("main window missing".to_string()),
        );
        assert!(!progress.is_complete());
        assert!(summary.contains("snap_layout="));
        assert!(summary.contains("close_request="));
        assert!(summary.contains("taskbar_icon="));
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
