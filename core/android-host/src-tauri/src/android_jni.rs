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
pub extern "system" fn Java_com_lamtools_sunday_core_KeyboardBridge_nativePublish(
    _env: JNIEnv,
    _class: JClass,
    inset: jni::sys::jint,
) {
    crate::publish_keyboard_inset(inset as i64);
}
