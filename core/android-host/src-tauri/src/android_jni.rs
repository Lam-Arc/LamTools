//! The JNI symbols the Kotlin bridges link against.
//!
//! user:"平台特有的系统操作通过薄适配层处理"+(桥本身是平台代码，宿主只需要把
//! 它们的调用接住，不让链接失败，也不假装自己做完了业务)。
//!
//! Every `external fun` in `android-src` needs a symbol here or the app dies on first
//! touch — `UnsatisfiedLinkError` at the moment the object is initialised, which for
//! `MainActivity` means the launcher cannot start.
//!
//! Only bridges that carry real behaviour are kept. The keyboard inset and the open-file
//! request had empty symbols here and nothing calling them: the webview lays itself out
//! from `visualViewport`, and opening a file with another app is not something the shared
//! UI asks the host to do. They were deleted rather than registered as a capability that
//! silently does nothing.

#[cfg(target_os = "android")]
use jni::objects::{JClass, JString};
#[cfg(target_os = "android")]
use jni::JNIEnv;

#[cfg(target_os = "android")]
fn read(env: &mut JNIEnv, value: &JString) -> String {
    env.get_string(value)
        .map(|text| text.into())
        .unwrap_or_default()
}

#[cfg(target_os = "android")]
#[no_mangle]
pub extern "system" fn Java_com_lamtools_sunday_core_FilePickerBridge_nativeRegister(
    mut env: JNIEnv,
    _class: JClass,
) {
    crate::picker::remember(&mut env);
    println!("[sunday] file picker bridge registered");
}

/// The picker's answer, handed to the request that opened it.
#[cfg(target_os = "android")]
#[no_mangle]
pub extern "system" fn Java_com_lamtools_sunday_core_FilePickerBridge_nativeDeliver(
    mut env: JNIEnv,
    _class: JClass,
    request_id: JString,
    payload: JString,
) {
    let id = read(&mut env, &request_id);
    let body = read(&mut env, &payload);
    crate::picker::deliver(&id, &body);
}

/// The keyboard's height in CSS pixels.
///
/// The shared interface reads it from `--native-keyboard-inset`; this is the only place
/// that knows the number, because the window is not resized when the keyboard appears.
#[cfg(target_os = "android")]
#[no_mangle]
pub extern "system" fn Java_com_lamtools_sunday_core_KeyboardBridge_nativeRegister(
    mut env: JNIEnv,
    _class: JClass,
) {
    crate::picker::remember(&mut env);
    println!("[sunday] keyboard bridge registered");
}

#[cfg(target_os = "android")]
#[no_mangle]
pub extern "system" fn Java_com_lamtools_sunday_core_KeyboardBridge_nativePublishInsets(
    _env: JNIEnv,
    _class: JClass,
    keyboard: jni::sys::jint,
    top: jni::sys::jint,
) {
    crate::publish_insets(keyboard as i64, top as i64);
}

/// The floating ring: its bridge class, cached the same way the picker caches its own.
///
/// user:“JNI 桥模式照抄现成的：Rust 侧 VM/BRIDGE/ACTIVITY 三个 OnceLock +
/// attach_current_thread + call_static_method”+(所以这里不发明新机制，只换一个类名)。
#[cfg(target_os = "android")]
mod overlay {
    use std::sync::OnceLock;

    use jni::objects::{GlobalRef, JValue};
    use jni::JavaVM;

    static VM: OnceLock<JavaVM> = OnceLock::new();
    static CLASS: OnceLock<Pinned> = OnceLock::new();

    /// A global reference that may live in a `static`: valid from any attached thread.
    struct Pinned(GlobalRef);

    unsafe impl Send for Pinned {}
    unsafe impl Sync for Pinned {}

    /// Hands the JavaVM and the overlay class over. Whichever JNI entry point runs first wins.
    pub fn remember(env: &mut jni::JNIEnv) {
        if VM.get().is_none() {
            if let Ok(vm) = env.get_java_vm() {
                let _ = VM.set(vm);
            }
        }
        if CLASS.get().is_none() {
            if let Ok(class) = env.find_class("com/lamtools/sunday/core/OverlayBridge") {
                if let Ok(global) = env.new_global_ref(class) {
                    let _ = CLASS.set(Pinned(global));
                }
            }
        }
        // The activity class is what `app_background` and the ring's "bring to front" use.
        crate::picker::remember(env);
    }

    /// Calls a `()Z` static method on the bridge.
    pub fn call_bool(method: &str) -> Result<bool, String> {
        let vm = VM
            .get()
            .ok_or_else(|| "the Android runtime is not ready".to_owned())?;
        let class = CLASS
            .get()
            .ok_or_else(|| "the overlay bridge is not ready".to_owned())?;
        let mut env = vm
            .attach_current_thread()
            .map_err(|error| error.to_string())?;
        let answer = env
            .call_static_method(&class.0, method, "()Z", no_args())
            .map_err(|error| error.to_string())?;
        // `z()` takes the owned value and answers the primitive, which keeps the generic
        // parameter of `JValueGen` out of this function's types.
        answer.z().map_err(|error| error.to_string())
    }

    /// Calls a `()V` static method on the bridge.
    pub fn call_unit(method: &str) -> Result<(), String> {
        let vm = VM
            .get()
            .ok_or_else(|| "the Android runtime is not ready".to_owned())?;
        let class = CLASS
            .get()
            .ok_or_else(|| "the overlay bridge is not ready".to_owned())?;
        let mut env = vm
            .attach_current_thread()
            .map_err(|error| error.to_string())?;
        env.call_static_method(&class.0, method, "()V", no_args())
            .map(|_| ())
            .map_err(|error| error.to_string())
    }

    /// An empty argument list with both lifetimes of `JValue` spelled out.
    ///
    /// A bare `&[]` leaves the reference type unconstrained, and the compiler then picks
    /// the owned-object shape — a type error the call itself does not hint at.
    fn no_args() -> &'static [JValue<'static, 'static>] {
        &[]
    }
}

/// False everywhere except Android, where the ring really exists.
#[cfg(not(target_os = "android"))]
pub fn overlay_call_bool(_method: &str) -> Result<bool, String> {
    Err("the floating ring only exists on Android".to_owned())
}

#[cfg(not(target_os = "android"))]
pub fn overlay_call_unit(_method: &str) -> Result<(), String> {
    Err("the floating ring only exists on Android".to_owned())
}

#[cfg(target_os = "android")]
pub fn overlay_call_bool(method: &str) -> Result<bool, String> {
    overlay::call_bool(method)
}

#[cfg(target_os = "android")]
pub fn overlay_call_unit(method: &str) -> Result<(), String> {
    overlay::call_unit(method)
}

/// The bridge's initialiser: Kotlin calls this when `OverlayBridge` is first touched.
#[cfg(target_os = "android")]
#[no_mangle]
pub extern "system" fn Java_com_lamtools_sunday_core_OverlayBridge_nativeRegister(
    mut env: JNIEnv,
    _class: JClass,
) {
    overlay::remember(&mut env);
    println!("[sunday] overlay bridge registered");
}

/// Permission, service liveness and the user's wish, reported on every resume.
#[cfg(target_os = "android")]
#[no_mangle]
pub extern "system" fn Java_com_lamtools_sunday_core_OverlayBridge_nativeState(
    mut env: JNIEnv,
    _class: JClass,
    granted: jni::sys::jboolean,
    running: jni::sys::jboolean,
    wanted: jni::sys::jboolean,
) {
    overlay::remember(&mut env);
    crate::publish_overlay_state(granted != 0, running != 0, wanted != 0);
}

/// One sector action, read from the activity's intent.
#[cfg(target_os = "android")]
#[no_mangle]
pub extern "system" fn Java_com_lamtools_sunday_core_MainActivity_nativeOverlayAction(
    mut env: JNIEnv,
    _class: JClass,
    payload: JString,
) {
    overlay::remember(&mut env);
    let json = read(&mut env, &payload);
    crate::publish_overlay_action(json);
}

/// The small window opened or closed.
#[cfg(target_os = "android")]
#[no_mangle]
pub extern "system" fn Java_com_lamtools_sunday_core_MainActivity_nativePipMode(
    mut env: JNIEnv,
    _class: JClass,
    active: jni::sys::jboolean,
) {
    overlay::remember(&mut env);
    crate::publish_pip_mode(active != 0);
}
