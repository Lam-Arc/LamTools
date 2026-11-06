//! The Android host: everything the shared UI needs to reach a real Python core.
//!
//! user:"Android：应用内运行环境承载共享 Core；平台特有的系统操作通过薄适配层处理"
//! +(宿主只做平台事情：装运行时、起进程、转发 IPC、放行文件选择；业务一律在 Core)。
//!
//! What this host owns, and nothing else:
//!
//! * the runtime install (unpack once per version) and the guest process lifetime;
//! * the port and bearer token the guest listens with — neither crosses into the UI,
//!   because on Android every other app can dial this app's loopback ports;
//! * the two IPC commands the shared transport speaks (`core_rpc`, `core_http`) and
//!   the `core-event` channel it subscribes to;
//! * the model configuration files the guest reads at startup.
//!
//! There is no second implementation of turns, tools or approvals here. That is the
//! whole point of running the shipping Python core instead of porting it.

use std::sync::Arc;

use serde_json::{json, Value};
use tauri::{Manager, State};

mod android_jni;
mod client;
mod picker;
mod runtime;

use client::CoreLink;
use runtime::Runtime;

/// The one handle the JNI callbacks need, for events the webview must see.
static APP: std::sync::OnceLock<tauri::AppHandle> = std::sync::OnceLock::new();

/// Publishes the keyboard height to the shared interface.
///
/// Called from Kotlin through JNI. The value lands on `--native-keyboard-inset`, which
/// `useComposerLayout` already layers over its own `visualViewport` measurement, so the
/// composer lifts above the keys exactly the way it does on the platforms that report a
/// resized viewport.
#[cfg(target_os = "android")]
fn publish_keyboard_inset(inset: i64) {
    use tauri::Emitter;
    if let Some(app) = APP.get() {
        app.emit("keyboard-inset", inset).ok();
    }
}

pub struct HostState {
    inner: Arc<Inner>,
}

struct Inner {
    app: tauri::AppHandle,
    link: Arc<CoreLink>,
    runtime: Runtime,
    data_dir: std::path::PathBuf,
}

/// Starts the guest if needed and points the RPC link at it.
///
/// Blocking on purpose: the first launch unpacks a few hundred megabytes, and reporting
/// progress from a background thread would be more machinery than the one screen that
/// waits for it needs. `spawn_blocking` keeps the async runtime free while it runs.
#[tauri::command]
async fn core_start(state: State<'_, HostState>) -> Result<Value, String> {
    let inner = Arc::clone(&state.inner);
    let started = tauri::async_runtime::spawn_blocking(move || {
        // user:“Android 宿主只承担进程存活、启动和必要的连接恢复”+(这条命令会被重复
        // 调用：界面重载、Activity 重建都会重新进来。已经在跑的 guest 直接复用，只有打包
        // 的镜像版本变了才在 ensure_started 里换一个新的，绝不因为一次重载杀掉正在执行的回合)。
        let port = inner.runtime.ensure_started()?;
        // The UI renders as soon as this resolves and immediately asks for its
        // project list; returning before uvicorn binds the port made that first
        // request fail, and the start screen then claimed there were no projects.
        inner
            .runtime
            .wait_ready(std::time::Duration::from_secs(180))?;
        inner.link.retarget(port, &inner.runtime.token());
        Ok::<_, String>(port)
    })
    .await
    .map_err(|error| format!("the start task was lost: {error}"))?;
    match started {
        Ok(port) => Ok(json!({ "phase": "ready", "port": port, "status": status_of(&state) })),
        Err(error) => Err(error),
    }
}

#[tauri::command]
fn core_status(state: State<'_, HostState>) -> Value {
    let status = state.inner.runtime.status();
    serde_json::to_value(status).unwrap_or_else(|_| json!({}))
}

#[tauri::command]
fn core_stop(state: State<'_, HostState>) {
    state.inner.runtime.stop();
}

#[tauri::command]
fn core_info(state: State<'_, HostState>) -> Value {
    let status = status_of(&state);
    json!({
        "transport": "ipc",
        "guest": "proot",
        "runtimeVersion": status["runtimeVersion"],
        "coreVersion": status["coreVersion"],
        "pythonVersion": status["pythonVersion"],
        "phase": status["phase"],
        "workRoot": runtime::GUEST_WORK_ROOT,
        "logTail": runtime::read_log_tail(&state.inner.app, 12),
    })
}

fn status_of(state: &State<'_, HostState>) -> Value {
    let status = state.inner.runtime.status();
    serde_json::to_value(status).unwrap_or_else(|_| json!({}))
}

/// Forwards one app-server RPC. The UI's transport calls this for every mutation.
#[tauri::command]
async fn core_rpc(
    state: State<'_, HostState>,
    method: String,
    params: Option<Value>,
) -> Result<Value, String> {
    let link = Arc::clone(&state.inner.link);
    let answer = link
        .call(&method, params.unwrap_or_else(|| json!({})), std::time::Duration::from_secs(120))
        .await?;
    if let Some(error) = answer.get("error") {
        // The transport parses "<code>: <message>" back into an RpcError, so the code
        // survives this boundary instead of degrading into a bare string.
        let code = error.get("code").and_then(Value::as_i64).unwrap_or(-32000);
        let message = error
            .get("message")
            .and_then(Value::as_str)
            .unwrap_or("core request failed");
        return Err(format!("{code}: {message}"));
    }
    Ok(answer.get("result").cloned().unwrap_or(Value::Null))
}

/// Forwards one HTTP request to the guest's REST surface.
///
/// The shared UI asks for projects, files and attachments over HTTP because desktop does;
/// answering the same paths here keeps one code path in the frontend.
#[tauri::command]
async fn core_http(
    state: State<'_, HostState>,
    method: String,
    path: String,
    body: Option<String>,
) -> Result<Value, String> {
    let inner = Arc::clone(&state.inner);
    let port = inner.runtime.ensure_started()?;
    let token = inner.runtime.token();
    // The shared UI asks for `/projects`, `/files/...` and so on; on desktop the base URL
    // carries the `/api/core` prefix, which the direct transport prepends. IPC has no base
    // URL, so the prefix has to be applied here — without it every such call is a 404,
    // including creating a project.
    let path = if path.starts_with("/api/") {
        path
    } else {
        format!("/api/core{path}")
    };
    let url = format!("http://127.0.0.1:{port}{path}");
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(120))
        .build()
        .map_err(|error| error.to_string())?;
    let mut request = client.request(
        reqwest::Method::from_bytes(method.as_bytes()).map_err(|error| error.to_string())?,
        &url,
    );
    request = request.bearer_auth(token);
    if let Some(body) = body {
        request = request
            .header("content-type", "application/json")
            .body(body);
    }
    let response = request
        .send()
        .await
        .map_err(|error| {
            println!("[sunday] core_http {method} {path} failed: {error}");
            error.to_string()
        })?;
    println!("[sunday] core_http {method} {path} -> {}", response.status());
    let status = response.status().as_u16();
    let content_type = response
        .headers()
        .get("content-type")
        .and_then(|value| value.to_str().ok())
        .unwrap_or("application/json")
        .to_owned();
    let bytes = response.bytes().await.map_err(|error| error.to_string())?;
    // Text stays text so the UI can parse JSON without a base64 round trip; only real
    // binaries (attachment downloads) take the base64 path.
    let is_text = content_type.starts_with("application/json")
        || content_type.starts_with("text/")
        || content_type.starts_with("application/javascript");
    if is_text {
        Ok(json!({
            "status": status,
            "content_type": content_type,
            "body": String::from_utf8_lossy(&bytes).to_string(),
            "body_base64": Value::Null,
        }))
    } else {
        Ok(json!({
            "status": status,
            "content_type": content_type,
            "body": Value::Null,
            "body_base64": base64(&bytes),
        }))
    }
}

/// The system document picker, answering in-guest paths.
///
/// user:“使用 Android SAF 桥接现有 Python Core 附件接口”+(共享 UI 拿到路径后走它本来
/// 就用的 attachment reference 接口，宿主不解析附件、不保存附件记录)。
#[tauri::command]
async fn pick_paths(source: Option<String>, accept: Option<String>) -> Result<Vec<String>, String> {
    picker::pick_paths(
        source.unwrap_or_else(|| "file".to_owned()),
        accept.unwrap_or_default(),
    )
    .await
}

/// Progress and diagnostics for the installing screen.
#[tauri::command]
fn runtime_log(state: State<'_, HostState>, lines: Option<usize>) -> String {
    runtime::read_log_tail(&state.inner.app, lines.unwrap_or(40))
}

fn base64(bytes: &[u8]) -> String {
    const ALPHABET: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut out = String::with_capacity((bytes.len() + 2) / 3 * 4);
    for chunk in bytes.chunks(3) {
        let first = chunk[0] as u32;
        let second = *chunk.get(1).unwrap_or(&0) as u32;
        let third = *chunk.get(2).unwrap_or(&0) as u32;
        let combined = (first << 16) | (second << 8) | third;
        out.push(ALPHABET[(combined >> 18) as usize & 63] as char);
        out.push(ALPHABET[(combined >> 12) as usize & 63] as char);
        out.push(if chunk.len() > 1 {
            ALPHABET[(combined >> 6) as usize & 63] as char
        } else {
            '='
        });
        out.push(if chunk.len() > 2 {
            ALPHABET[combined as usize & 63] as char
        } else {
            '='
        });
    }
    out
}

#[cfg(target_os = "android")]
#[no_mangle]
pub extern "system" fn Java_com_lamtools_sunday_core_LifecycleBridge_signal(
    mut env: jni::JNIEnv,
    _class: jni::objects::JClass,
    event: jni::objects::JString,
) {
    // The Kotlin side passes the OS callback verbatim; the guest re-reads its own state
    // when the UI reconnects, so this is only a timestamped note in logcat.
    if let Ok(text) = env.get_string(&event) {
        let value: String = text.into();
        println!("[sunday] lifecycle {value}");
    }
}

#[cfg(target_os = "android")]
#[no_mangle]
pub extern "system" fn Java_com_lamtools_sunday_core_KeystoreBridge_nativeRegister(
    mut env: jni::JNIEnv,
    _class: jni::objects::JClass,
) {
    // This is the earliest JNI call the app makes (`MainActivity.onCreate` touches this
    // object before Tauri starts), so the picker takes the JavaVM from here.
    picker::remember(&mut env);
    // The keystore is not used: the API key lives in the guest's own provider config,
    // the same place desktop keeps it. Keeping the symbol means the Kotlin initialiser
    // still links; when key sealing moves here, this is where it plugs in.
    println!("[sunday] keystore bridge registered (unused, keys live in the guest config)");
}

/// Called from the Activity before Tauri starts: `applicationInfo.nativeLibraryDir` is
/// the only directory Android still executes binaries from.
#[cfg(target_os = "android")]
#[no_mangle]
pub extern "system" fn Java_com_lamtools_sunday_core_MainActivity_nativeSetLibraryDir(
    mut env: jni::JNIEnv,
    _class: jni::objects::JClass,
    dir: jni::objects::JString,
) {
    if let Ok(text) = env.get_string(&dir) {
        let value: String = text.into();
        picker::remember(&mut env);
        runtime::set_native_lib_dir(&value);
        println!("[sunday] native library dir: {value}");
    }
}

/// Called from the Activity: the app's own files directory, before Tauri starts.
#[cfg(target_os = "android")]
#[no_mangle]
pub extern "system" fn Java_com_lamtools_sunday_core_MainActivity_nativeSetFilesDir(
    mut env: jni::JNIEnv,
    _class: jni::objects::JClass,
    dir: jni::objects::JString,
) {
    if let Ok(text) = env.get_string(&dir) {
        let value: String = text.into();
        picker::remember(&mut env);
        runtime::set_files_dir(&value);
        println!("[sunday] files dir: {value}");
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            let handle = app.handle().clone();
            let data_dir = runtime::data_dir(&handle);
            println!("[sunday] host data dir {}", data_dir.display());
            std::fs::create_dir_all(&data_dir).ok();
            // The runtime directory carries the manifest that ships in assets; copy it
            // out once so every later read is a plain file read.

            let _ = APP.set(handle.clone());
            let link = CoreLink::new(handle.clone());
            let runtime = Runtime::new(handle.clone());
            // Nothing is copied here: staging the packaged archive is Kotlin's job (it
            // streams assets without holding the archive in memory), and the runtime
            // install waits for the manifest that staging writes last.
            app.manage(HostState {
                inner: Arc::new(Inner {
                    app: handle.clone(),
                    link,
                    runtime,
                    data_dir,
                }),
            });
            handle.emit_core_info();
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            core_start,
            core_status,
            core_stop,
            core_info,
            core_rpc,
            core_http,
            pick_paths,
            runtime_log,
        ])
        .run(tauri::generate_context!())
        .expect("error while running the Android host");
}

trait EmitCoreInfo {
    fn emit_core_info(&self);
}

impl EmitCoreInfo for tauri::AppHandle {
    fn emit_core_info(&self) {
        use tauri::Emitter;
        self.emit("core-event", json!({ "method": "core/hostReady", "payload": {} }))
            .ok();
    }
}
