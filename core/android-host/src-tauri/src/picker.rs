//! The system document picker, wired to the shared attachment contract.
//!
//! user:“恢复 Android 上桌面已有的附件能力。使用 Android SAF 桥接现有 Python Core
//! 附件接口，不另建附件业务系统。”+(所以这里只有一座桥：Android 的选择器把文件落到
//! 核心能读到的目录，宿主把宿主路径换成 guest 路径交回共享 UI，剩下的登记、存储、
//! 预览全部由现有 Python Core 完成)。
//!
//! The answer never crosses as bytes. `core_http` carries text bodies only, and pushing a
//! 50 MB attachment through base64 twice would be the wrong direction; a path the core can
//! `stat` is exactly what desktop hands over.
//!
//! One request at a time, like the picker itself: the shared UI has one attachment button
//! and the Kotlin side refuses a second launch while one is open.

use std::collections::HashMap;
use std::sync::mpsc::{channel, Sender};
use std::sync::{Mutex, OnceLock};

use serde_json::Value;

use crate::runtime;

/// Requests waiting for the Kotlin side to answer, keyed by request id.
static PENDING: OnceLock<Mutex<HashMap<String, Sender<String>>>> = OnceLock::new();

fn pending() -> &'static Mutex<HashMap<String, Sender<String>>> {
    PENDING.get_or_init(|| Mutex::new(HashMap::new()))
}

#[cfg(target_os = "android")]
static VM: OnceLock<jni::JavaVM> = OnceLock::new();

/// A global reference to the Kotlin bridge class.
///
/// Looked up once, from a thread that has the app's class loader. A Rust thread attached
/// later has no class loader of its own, and `FindClass` from there resolves against the
/// boot loader only — the first attempt died with `ClassNotFoundException` exactly because
/// of that.
#[cfg(target_os = "android")]
static BRIDGE: OnceLock<BridgeClass> = OnceLock::new();

/// A `GlobalRef` that may live in a `static`.
///
/// `jni`'s `GlobalRef` is not `Sync` because it holds a raw object pointer, but a global
/// reference is exactly the thing that is valid from any attached thread for the life of
/// the JVM, which is why it can be pinned here.
#[cfg(target_os = "android")]
struct BridgeClass(jni::objects::GlobalRef);

#[cfg(target_os = "android")]
unsafe impl Send for BridgeClass {}

#[cfg(target_os = "android")]
unsafe impl Sync for BridgeClass {}

/// Hands the JavaVM and the bridge class over so this module can call Kotlin back.
///
/// Called from every JNI entry point that already receives an `env`; whichever one runs
/// first wins. `MainActivity.onCreate` runs before Tauri's setup, so the picker is
/// callable by the time the UI can ask for it.
#[cfg(target_os = "android")]
pub fn remember(env: &mut jni::JNIEnv) {
    if VM.get().is_none() {
        if let Ok(vm) = env.get_java_vm() {
            let _ = VM.set(vm);
        }
    }
    if BRIDGE.get().is_none() {
        if let Ok(class) = env.find_class("com/lamtools/sunday/core/FilePickerBridge") {
            if let Ok(global) = env.new_global_ref(class) {
                let _ = BRIDGE.set(BridgeClass(global));
            }
        }
    }
}

/// The picker's answer, delivered by JNI. Unknown ids are ignored: a stale answer with
/// nobody waiting is not an error.
pub fn deliver(request_id: &str, payload: &str) {
    let sender = pending().lock().expect("picker lock").remove(request_id);
    if let Some(sender) = sender {
        let _ = sender.send(payload.to_owned());
    }
}

/// Opens the picker and answers with paths the guest can read, or an empty list when the
/// user cancelled.
/// The document picker always allows several files. A caller that only wants one takes
/// the first; narrowing the intent here would mean a second picker for no gain.
pub async fn pick_paths(source: String, accept: String) -> Result<Vec<String>, String> {
    let request = next_request_id();
    let (sender, receiver) = channel::<String>();
    pending()
        .lock()
        .expect("picker lock")
        .insert(request.clone(), sender);
    if let Err(error) = request_pick(&request, &source, &accept) {
        pending().lock().expect("picker lock").remove(&request);
        return Err(error);
    }
    // The user needs as long as they need; this is only the point where a lost answer
    // becomes a visible failure instead of a composer that waits forever.
    let answered = tauri::async_runtime::spawn_blocking(move || {
        receiver.recv_timeout(std::time::Duration::from_secs(900))
    })
    .await
    .map_err(|error| format!("the picker task was lost: {error}"))?
    .map_err(|_| "文件选择器没有回应".to_owned())?;

    let parsed: Value =
        serde_json::from_str(&answered).map_err(|error| format!("文件选择器的回答无法解析: {error}"))?;
    if let Some(reason) = parsed.get("error").and_then(Value::as_str) {
        return Err(reason.to_owned());
    }
    let mut paths = Vec::new();
    for file in parsed
        .get("files")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
    {
        let host = file.get("path").and_then(Value::as_str).unwrap_or_default();
        // The copy lives under the guest's own user data; nothing else is answerable,
        // because the core would not be able to read it.
        let guest = runtime::guest_path(host)
            .ok_or_else(|| format!("选中的文件不在核心能读到的目录里: {host}"))?;
        paths.push(guest);
    }
    Ok(paths)
}

fn next_request_id() -> String {
    use std::sync::atomic::{AtomicU64, Ordering};
    static COUNTER: AtomicU64 = AtomicU64::new(1);
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|elapsed| elapsed.as_millis())
        .unwrap_or(0);
    format!("pick-{now}-{}", COUNTER.fetch_add(1, Ordering::SeqCst))
}

#[cfg(target_os = "android")]
fn request_pick(request: &str, source: &str, accept: &str) -> Result<(), String> {
    let vm = VM.get().ok_or_else(|| "文件选择器还没有准备好".to_owned())?;
    let bridge = BRIDGE.get().ok_or_else(|| "文件选择器还没有准备好".to_owned())?;
    let mut env = vm
        .attach_current_thread()
        .map_err(|error| format!("cannot attach to the Android runtime: {error}"))?;
    let request = env.new_string(request).map_err(|error| error.to_string())?;
    let source = env.new_string(source).map_err(|error| error.to_string())?;
    let accept = env.new_string(accept).map_err(|error| error.to_string())?;
    env.call_static_method(
        &bridge.0,
        "pick",
        "(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;)V",
        &[
            jni::objects::JValue::Object(&request),
            jni::objects::JValue::Object(&source),
            jni::objects::JValue::Object(&accept),
        ],
    )
    .map_err(|error| format!("cannot open the Android file picker: {error}"))?;
    Ok(())
}

#[cfg(not(target_os = "android"))]
fn request_pick(_request: &str, _source: &str, _accept: &str) -> Result<(), String> {
    Err("the system file picker only exists on Android".to_owned())
}
