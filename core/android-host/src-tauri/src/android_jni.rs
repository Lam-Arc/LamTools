//! The JNI symbols the Kotlin bridges link against.
//!
//! user:"平台特有的系统操作通过薄适配层处理"+(桥本身是平台代码，宿主只需要把
//! 它们的调用接住，不让链接失败，也不假装自己做完了业务)。
//!
//! Every `external fun` in `android-src` needs a symbol here or the app dies on first
//! touch — `UnsatisfiedLinkError` at the moment the object is initialised, which for
//! `MainActivity` means the launcher cannot start.
//!
//! Today only two of these carry real behaviour: the library directory (the runtime
//! cannot start without it) and the lifecycle note. The picker and keyboard bridges are
//! compiled and called but their results are not consumed yet — that is a known gap, not
//! a silent no-op that pretends to work: the UI reports file picking as unavailable, so
//! nothing offers the user a button that does nothing.

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
    _env: JNIEnv,
    _class: JClass,
) {
    println!("[sunday] file picker bridge registered");
}

/// The picker's answer. A real implementation will hand this to whatever requested the
/// file; until attachments are wired through, the payload is logged so a support log can
/// show whether the picker itself worked.
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
    println!("[sunday] picker delivered request={id} bytes={}", body.len());
}

#[cfg(target_os = "android")]
#[no_mangle]
pub extern "system" fn Java_com_lamtools_sunday_core_KeyboardBridge_nativeRegister(
    _env: JNIEnv,
    _class: JClass,
) {
    println!("[sunday] keyboard bridge registered");
}

/// Keyboard inset changes. The webview lays itself out with `env(safe-area-inset-*)` and
/// `visualViewport`, so this only needs to be observable in the log.
#[cfg(target_os = "android")]
#[no_mangle]
pub extern "system" fn Java_com_lamtools_sunday_core_KeyboardBridge_nativePublish(
    _env: JNIEnv,
    _class: JClass,
    inset_dp: jni::sys::jint,
) {
    println!("[sunday] keyboard inset {inset_dp}dp");
}

#[cfg(target_os = "android")]
#[no_mangle]
pub extern "system" fn Java_com_lamtools_sunday_core_OpenFileBridge_nativeRegister(
    _env: JNIEnv,
    _class: JClass,
) {
    println!("[sunday] open-file bridge registered");
}
