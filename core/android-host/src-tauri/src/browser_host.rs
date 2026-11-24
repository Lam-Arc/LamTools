//! The native webview behind a browser page on the phone.
//!
//! user:“在手机端，网页搜索时不应该去自动跳到分屏，而是收进标签页抽屉”+
//! “进来页之后要能切、能返回”+(页是界面里的一块区域，网页是这块区域里的一个原生 View：
//! 界面只下发矩形与可见性，加载、导航、取内容都在这里)。
//!
//! 这里只有一层转发：Tauri 命令 → Kotlin 的 `BrowserBridge`。真正的 WebView 生命周期由
//! Android 管理，宿主不假装自己拥有一块浏览器内核。矩形一律是物理像素（前端已乘过一次
//! devicePixelRatio），所以这里和 Kotlin 都不再乘第二次。

use std::collections::HashMap;
use std::sync::Mutex;

use serde_json::{json, Value};

#[cfg(target_os = "android")]
use std::sync::OnceLock;

#[cfg(target_os = "android")]
static VM: OnceLock<jni::JavaVM> = OnceLock::new();

/// A global reference to the Kotlin bridge class; valid from any attached thread.
#[cfg(target_os = "android")]
static BRIDGE: OnceLock<BridgeClass> = OnceLock::new();

#[cfg(target_os = "android")]
struct BridgeClass(jni::objects::GlobalRef);

#[cfg(target_os = "android")]
unsafe impl Send for BridgeClass {}

#[cfg(target_os = "android")]
unsafe impl Sync for BridgeClass {}

/// Called from the JNI symbol the Kotlin object declares, once, at class load.
#[cfg(target_os = "android")]
pub fn remember(env: &mut jni::JNIEnv) {
    if VM.get().is_none() {
        if let Ok(vm) = env.get_java_vm() {
            let _ = VM.set(vm);
        }
    }
    if BRIDGE.get().is_none() {
        if let Ok(class) = env.find_class("com/lamtools/sunday/core/BrowserBridge") {
            if let Ok(global) = env.new_global_ref(class) {
                let _ = BRIDGE.set(BridgeClass(global));
            }
        }
    }
}

#[cfg(target_os = "android")]
fn call_string(
    method: &str,
    signature: &str,
    args: &[jni::objects::JValue<'_, '_>],
) -> Result<String, String> {
    let vm = VM
        .get()
        .ok_or_else(|| "the Android runtime is not ready".to_owned())?;
    let class = BRIDGE
        .get()
        .ok_or_else(|| "the browser bridge is not registered yet".to_owned())?;
    let mut env = vm.attach_current_thread().map_err(|error| error.to_string())?;
    let value = env
        .call_static_method(&class.0, method, signature, args)
        .map_err(|error| error.to_string())?;
    let object = value.l().map_err(|error| error.to_string())?;
    let text: String = env
        .get_string(&jni::objects::JString::from(object))
        .map_err(|error| error.to_string())?
        .into();
    Ok(text)
}

#[cfg(target_os = "android")]
fn call_unit(
    method: &str,
    signature: &str,
    args: &[jni::objects::JValue<'_, '_>],
) -> Result<(), String> {
    let vm = VM
        .get()
        .ok_or_else(|| "the Android runtime is not ready".to_owned())?;
    let class = BRIDGE
        .get()
        .ok_or_else(|| "the browser bridge is not registered yet".to_owned())?;
    let mut env = vm.attach_current_thread().map_err(|error| error.to_string())?;
    env.call_static_method(&class.0, method, signature, args)
        .map(|_| ())
        .map_err(|error| error.to_string())
}

#[cfg(not(target_os = "android"))]
pub fn open(_url: &str) -> Result<String, String> {
    Err("the in-app browser only exists on Android".to_owned())
}

#[cfg(target_os = "android")]
pub fn open(url: &str) -> Result<String, String> {
    let vm = VM.get().ok_or_else(|| "the Android runtime is not ready".to_owned())?;
    let mut env = vm.attach_current_thread().map_err(|error| error.to_string())?;
    let value = env.new_string(url).map_err(|error| error.to_string())?;
    call_string(
        "open",
        "(Ljava/lang/String;)Ljava/lang/String;",
        &[jni::objects::JValue::Object(&value)],
    )
}

#[cfg(not(target_os = "android"))]
pub fn bounds(_: &str, _: i32, _: i32, _: i32, _: i32, _: bool) -> Result<(), String> {
    Err("the in-app browser only exists on Android".to_owned())
}

#[cfg(target_os = "android")]
pub fn bounds(tab: &str, x: i32, y: i32, width: i32, height: i32, visible: bool) -> Result<(), String> {
    let vm = VM.get().ok_or_else(|| "the Android runtime is not ready".to_owned())?;
    let mut env = vm.attach_current_thread().map_err(|error| error.to_string())?;
    let value = env.new_string(tab).map_err(|error| error.to_string())?;
    call_unit(
        "bounds",
        "(Ljava/lang/String;IIIIZ)V",
        &[
            jni::objects::JValue::Object(&value),
            jni::objects::JValue::Int(x),
            jni::objects::JValue::Int(y),
            jni::objects::JValue::Int(width),
            jni::objects::JValue::Int(height),
            jni::objects::JValue::Bool(visible as u8),
        ],
    )
}

#[cfg(not(target_os = "android"))]
pub fn navigate(_: &str, _: &str, _: &str) -> Result<(), String> {
    Err("the in-app browser only exists on Android".to_owned())
}

#[cfg(target_os = "android")]
pub fn navigate(tab: &str, action: &str, url: &str) -> Result<(), String> {
    let vm = VM.get().ok_or_else(|| "the Android runtime is not ready".to_owned())?;
    let mut env = vm.attach_current_thread().map_err(|error| error.to_string())?;
    let tab = env.new_string(tab).map_err(|error| error.to_string())?;
    let action = env.new_string(action).map_err(|error| error.to_string())?;
    let url = env.new_string(url).map_err(|error| error.to_string())?;
    call_unit(
        "navigate",
        "(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;)V",
        &[
            jni::objects::JValue::Object(&tab),
            jni::objects::JValue::Object(&action),
            jni::objects::JValue::Object(&url),
        ],
    )
}

#[cfg(not(target_os = "android"))]
pub fn hide(_: &str) -> Result<(), String> {
    Err("the in-app browser only exists on Android".to_owned())
}

#[cfg(target_os = "android")]
pub fn hide(tab: &str) -> Result<(), String> {
    let vm = VM.get().ok_or_else(|| "the Android runtime is not ready".to_owned())?;
    let mut env = vm.attach_current_thread().map_err(|error| error.to_string())?;
    let value = env.new_string(tab).map_err(|error| error.to_string())?;
    call_unit(
        "hide",
        "(Ljava/lang/String;)V",
        &[jni::objects::JValue::Object(&value)],
    )
}

#[cfg(not(target_os = "android"))]
pub fn hide_all() -> Result<(), String> {
    Err("the in-app browser only exists on Android".to_owned())
}

#[cfg(target_os = "android")]
pub fn hide_all() -> Result<(), String> {
    let vm = VM.get().ok_or_else(|| "the Android runtime is not ready".to_owned())?;
    let mut env = vm.attach_current_thread().map_err(|error| error.to_string())?;
    let _ = &mut env;
    call_unit("hideAll", "()V", &[])
}

#[cfg(not(target_os = "android"))]
pub fn activate(_: &str) -> Result<(), String> {
    Err("the in-app browser only exists on Android".to_owned())
}

#[cfg(target_os = "android")]
pub fn activate(tab: &str) -> Result<(), String> {
    let vm = VM.get().ok_or_else(|| "the Android runtime is not ready".to_owned())?;
    let mut env = vm.attach_current_thread().map_err(|error| error.to_string())?;
    let value = env.new_string(tab).map_err(|error| error.to_string())?;
    call_unit(
        "activate",
        "(Ljava/lang/String;)V",
        &[jni::objects::JValue::Object(&value)],
    )
}

#[cfg(not(target_os = "android"))]
pub fn close(_: &str) -> Result<(), String> {
    Err("the in-app browser only exists on Android".to_owned())
}

#[cfg(target_os = "android")]
pub fn close(tab: &str) -> Result<(), String> {
    let vm = VM.get().ok_or_else(|| "the Android runtime is not ready".to_owned())?;
    let mut env = vm.attach_current_thread().map_err(|error| error.to_string())?;
    let value = env.new_string(tab).map_err(|error| error.to_string())?;
    call_unit(
        "close",
        "(Ljava/lang/String;)V",
        &[jni::objects::JValue::Object(&value)],
    )
}

#[cfg(not(target_os = "android"))]
pub fn state(_: &str) -> Result<String, String> {
    Err("the in-app browser only exists on Android".to_owned())
}

#[cfg(target_os = "android")]
pub fn state(tab: &str) -> Result<String, String> {
    let vm = VM.get().ok_or_else(|| "the Android runtime is not ready".to_owned())?;
    let mut env = vm.attach_current_thread().map_err(|error| error.to_string())?;
    let value = env.new_string(tab).map_err(|error| error.to_string())?;
    call_string(
        "state",
        "(Ljava/lang/String;)Ljava/lang/String;",
        &[jni::objects::JValue::Object(&value)],
    )
}

#[cfg(not(target_os = "android"))]
pub fn html(_: &str, _: &str, _: u32, _: u32, _: u32, _: u32) -> Result<String, String> {
    Err("the in-app browser only exists on Android".to_owned())
}

#[cfg(target_os = "android")]
pub fn html(
    tab: &str,
    selectors_json: &str,
    max_nodes: u32,
    per_node_chars: u32,
    max_chars: u32,
    page_text_chars: u32,
) -> Result<String, String> {
    let vm = VM.get().ok_or_else(|| "the Android runtime is not ready".to_owned())?;
    let mut env = vm.attach_current_thread().map_err(|error| error.to_string())?;
    let tab = env.new_string(tab).map_err(|error| error.to_string())?;
    let selectors = env.new_string(selectors_json).map_err(|error| error.to_string())?;
    call_string(
        "html",
        "(Ljava/lang/String;Ljava/lang/String;IIII)Ljava/lang/String;",
        &[
            jni::objects::JValue::Object(&tab),
            jni::objects::JValue::Object(&selectors),
            jni::objects::JValue::Int(max_nodes as i32),
            jni::objects::JValue::Int(per_node_chars as i32),
            jni::objects::JValue::Int(max_chars as i32),
            jni::objects::JValue::Int(page_text_chars as i32),
        ],
    )
}

// --------------------------------------------------------------------- commands

/// Which native tab belongs to which split-tab id.
///
/// user:“桌面的分屏标签页对于手机来说，等于换页”+(同一个页面可能由界面先拉起、再被同一个
/// 组件接管；按 key 去重，避免一次点击建出两个原生网页、其中一个谁也管不到)。
static KEYS: std::sync::OnceLock<Mutex<HashMap<String, String>>> = std::sync::OnceLock::new();

fn key_map() -> &'static Mutex<HashMap<String, String>> {
    KEYS.get_or_init(|| Mutex::new(HashMap::new()))
}

/// Opens a page and answers its id. `profile` is accepted for shape parity with desktop.
///
/// With a `key` (the split-tab id) an existing native tab is reused as long as it is alive.
#[tauri::command]
pub async fn browser_open(
    url: Option<String>,
    profile: Option<String>,
    key: Option<String>,
) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || browser_open_blocking(url, profile, key))
        .await
        .map_err(|error| error.to_string())?
}

fn browser_open_blocking(
    url: Option<String>,
    profile: Option<String>,
    key: Option<String>,
) -> Result<Value, String> {
    let _ = profile;
    let requested = key.as_deref().filter(|value| !value.is_empty());
    if let Some(key) = requested {
        let existing = key_map()
            .lock()
            .map_err(|error| error.to_string())?
            .get(key)
            .cloned();
        if let Some(tab) = existing {
            let alive = state(&tab)
                .map(|text| !text.contains(MISSING_MARKER))
                .unwrap_or(false);
            if alive {
                return Ok(json!({ "tab": tab }));
            }
        }
    }
    let tab = open(url.as_deref().unwrap_or(""))?;
    if let Some(key) = requested {
        key_map()
            .lock()
            .map_err(|error| error.to_string())?
            .insert(key.to_owned(), tab.clone());
    }
    Ok(json!({ "tab": tab }))
}

/// The Kotlin state answer carries `{"missing":true}` when the tab no longer exists.
const MISSING_MARKER: &str = "missing";

#[tauri::command]
pub fn browser_bounds(
    tab: String,
    x: i32,
    y: i32,
    width: i32,
    height: i32,
    visible: bool,
    trace: Option<String>,
    is_float: Option<bool>,
    stack_index: Option<i32>,
    group: Option<String>,
) -> Result<(), String> {
    let _ = (trace, is_float, stack_index, group);
    bounds(&tab, x, y, width.max(1), height.max(1), visible)
}

#[tauri::command]
pub fn browser_nav(
    tab: String,
    action: Option<String>,
    url: Option<String>,
    query: Option<String>,
) -> Result<(), String> {
    let _ = query;
    navigate(&tab, action.as_deref().unwrap_or("navigate"), url.as_deref().unwrap_or(""))
}

/// 收起某一页对应的原生网页；不带 key 时收全部。
///
/// user:“网页收不起来，收起来了仍出现”+(收起要按宿主自己的 key 记账来做：前端的映射
/// 一旦对不上，命令就发不出去，网页会一直浮在会话上面)。
#[tauri::command]
pub fn browser_hide(key: Option<String>) -> Result<(), String> {
    let requested = key.as_deref().filter(|value| !value.is_empty());
    match requested {
        Some(key) => {
            let mapped = key_map()
                .lock()
                .map_err(|error| error.to_string())?
                .get(key)
                .cloned();
            match mapped {
                Some(tab) => hide(&tab),
                None => hide_all(),
            }
        }
        None => hide_all(),
    }
}

/// 关掉某一页：销毁原生网页并清掉记账。
#[tauri::command]
pub fn browser_release(key: String) -> Result<(), String> {
    let mapped = key_map()
        .lock()
        .map_err(|error| error.to_string())?
        .remove(&key);
    match mapped {
        Some(tab) => close(&tab),
        None => Ok(()),
    }
}

#[tauri::command]
pub fn browser_activate(tab: String) -> Result<(), String> {
    activate(&tab)
}

#[tauri::command]
pub fn browser_close(tab: String) -> Result<(), String> {
    if let Ok(mut map) = key_map().lock() {
        map.retain(|_, value| value != &tab);
    }
    close(&tab)
}

#[tauri::command]
pub async fn browser_state(tab: String) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let raw = state(&tab)?;
        serde_json::from_str(&raw).map_err(|error| error.to_string())
    })
    .await
    .map_err(|error| error.to_string())?
}

/// Read-only page extraction in the shape the desktop host answers with.
///
/// user:“browser_html 拿不到正文”+(同步命令由 Tauri 放在主线程执行：它一阻塞等页面回话，
/// 主线程就被占住，页面那边的回包永远排不上队，只能等到超时之后才送达。改成异步 +
/// 阻塞线程池，主线程继续转，回包立刻就能被接住)。
#[tauri::command]
pub async fn browser_html(
    tab: String,
    selectors: Option<Vec<String>>,
    max_nodes: Option<u32>,
    per_node_chars: Option<u32>,
    max_chars: Option<u32>,
    page_text_chars: Option<u32>,
) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || {
        browser_html_blocking(
            tab,
            selectors,
            max_nodes,
            per_node_chars,
            max_chars,
            page_text_chars,
        )
    })
    .await
    .map_err(|error| error.to_string())?
}

fn browser_html_blocking(
    tab: String,
    selectors: Option<Vec<String>>,
    max_nodes: Option<u32>,
    per_node_chars: Option<u32>,
    max_chars: Option<u32>,
    page_text_chars: Option<u32>,
) -> Result<Value, String> {
    let cleaned: Vec<String> = selectors
        .unwrap_or_default()
        .into_iter()
        .map(|item| item.trim().to_owned())
        .filter(|item| !item.is_empty())
        .collect();
    if cleaned.is_empty() {
        return Err("invalid_argument: 至少要给一个 CSS 选择器".to_owned());
    }
    let max_nodes = max_nodes.unwrap_or(20).clamp(1, 40);
    let per_node_chars = per_node_chars.unwrap_or(12_000).clamp(400, 40_000);
    let max_chars = max_chars.unwrap_or(100_000).clamp(2_000, 150_000);
    let page_text_chars = page_text_chars.unwrap_or(0).clamp(0, 8_000);
    let selectors_json = serde_json::to_string(&cleaned).map_err(|error| error.to_string())?;
    let raw = html(
        &tab,
        &selectors_json,
        max_nodes,
        per_node_chars,
        max_chars,
        page_text_chars,
    )?;
    let page: Value = serde_json::from_str(&raw).unwrap_or_else(|_| json!({}));
    let runtime = state(&tab)
        .ok()
        .and_then(|text| serde_json::from_str::<Value>(&text).ok())
        .unwrap_or_else(|| json!({}));
    Ok(json!({
        "tab": tab,
        "url": runtime.get("url").cloned().unwrap_or_else(|| json!("")),
        "title": runtime.get("title").cloned().unwrap_or_else(|| json!("")),
        "loading": runtime.get("loading").cloned().unwrap_or_else(|| json!(false)),
        "nodes": page.get("nodes").cloned().unwrap_or_else(|| json!([])),
        "counts": page.get("counts").cloned().unwrap_or_else(|| json!({
            "matched": 0, "returned": 0, "omitted": 0, "chars": 0, "truncated": false
        })),
        "pageText": page.get("pageText").cloned().unwrap_or_else(|| json!("")),
        "skippedSelectors": page.get("skippedSelectors").cloned().unwrap_or_else(|| json!([])),
        // 页面脚本没有回话时这里为 true：比“返回空列表”更容易分辨是读不到还是被拒。
        "timedOut": page.get("timeout").cloned().unwrap_or_else(|| json!(false)),
        "trust": "untrusted",
        "source": "web",
        "fetchedAt": "",
    }))
}
