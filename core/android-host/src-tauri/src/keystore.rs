//! The Android Keystore, as seen from Rust.
//!
//! The cryptography is in `KeystoreBridge.kt`: an AES key generated inside
//! AndroidKeyStore, which never leaves it. This module is the call path, and it is
//! deliberately the only one. When any step fails the error travels back unchanged so
//! the caller can refuse to store anything; there is no fallback here, because a
//! fallback would be the plaintext file this exists to replace.
//!
//! On a non-Android build every entry point reports that the keystore is unavailable,
//! which is true. The desktop host keeps its owner-only file and says so.

#[cfg(target_os = "android")]
mod bridge {
    use std::sync::OnceLock;

    use jni::objects::{GlobalRef, JClass, JString, JValue, JValueOwned};
    use jni::{JNIEnv, JavaVM};
    use sunday_protocol::CoreError;

    const STRING_SIGNATURE: &str = "(Ljava/lang/String;)Ljava/lang/String;";

    static VM: OnceLock<JavaVM> = OnceLock::new();
    static CLASS_REF: OnceLock<GlobalRef> = OnceLock::new();

    /// Called once from Kotlin, which is the only moment a `JavaVM` and this class are
    /// handed to us together.
    pub fn register(vm: JavaVM, class: GlobalRef) {
        let _ = VM.set(vm);
        let _ = CLASS_REF.set(class);
    }

    /// The cached class, as the borrowed form the call API wants.
    ///
    /// A global reference is valid on any thread, which is the whole reason for caching
    /// it: looking the class up by name from an attached thread finds nothing.
    fn cached_class<'local>() -> Result<JClass<'local>, CoreError> {
        let held = CLASS_REF
            .get()
            .ok_or_else(|| unavailable("the bridge class was never registered"))?;
        // Safety: this is a global reference that outlives the call, and the wrapping
        // `JClass` never escapes this function.
        Ok(unsafe { JClass::from_raw(held.as_obj().as_raw() as jni::sys::jclass) })
    }

    fn unavailable(reason: impl Into<String>) -> CoreError {
        CoreError::storage(format!("Android keystore unavailable: {}", reason.into()))
    }

    /// A pending Java exception, described well enough to act on.
    ///
    /// The Kotlin side never lets an exception escape `unavailableReason`, so reaching
    /// this at all means something structural is wrong, such as the class being absent.
    /// The description is therefore allowed to stay generic; the useful message comes
    /// from `unavailableReason` on the normal failure path.
    /// A pending Java exception, described only as far as is cheap.
    ///
    /// The useful text is written to logcat by the Kotlin side, which has the stack
    /// trace and does not need to hand it back across the boundary.
    fn describe(env: &mut JNIEnv, error: jni::errors::Error) -> String {
        if matches!(error, jni::errors::Error::JavaException) {
            let _ = env.exception_clear();
            return "a Java exception was thrown; see logcat for SundayKeystore".to_owned();
        }
        error.to_string()
    }

    fn call_string(method: &str, argument: Option<&str>) -> Result<String, CoreError> {
        let vm = VM
            .get()
            .ok_or_else(|| unavailable("the bridge was never registered"))?;
        let mut env = vm
            .attach_current_thread()
            .map_err(|error| unavailable(format!("cannot attach a thread: {error}")))?;
        let class = cached_class()?;

        let value = match argument {
            Some(text) => {
                let input = env
                    .new_string(text)
                    .map_err(|error| unavailable(format!("cannot pass the value: {error}")))?;
                env.call_static_method(
                    &class,
                    method,
                    STRING_SIGNATURE,
                    &[JValue::Object(&input)],
                )
            }
            None => env.call_static_method(&class, method, "()Ljava/lang/String;", &[] as &[JValue]),
        }
        .map_err(|error| unavailable(describe(&mut env, error)))?;

        let object = match value {
            JValueOwned::Object(object) => object,
            _ => return Err(unavailable(format!("{method} returned a non-string"))),
        };
        if object.is_null() {
            return Err(unavailable(format!("{method} returned null")));
        }
        // `get_string` borrows the JString, so it cannot be a temporary.
        let key = JString::from(object);
        let text = env
            .get_string(&key)
            .map_err(|error| unavailable(format!("cannot read the result: {error}")))?;
        Ok(text.into())
    }

    /// Whether a working key can be produced right now.
    ///
    /// Returns the reason as plain text rather than a nested error, because this string
    /// is shown to the user: a `CoreError` rendered with Debug reads
    /// `Storage { reason: "..." }`, which is not an explanation.
    pub fn probe() -> Result<(), String> {
        match call_string("unavailableReason", None) {
            // An empty reason is the Kotlin side saying the key is there and usable.
            Ok(reason) if reason.is_empty() => Ok(()),
            Ok(reason) => Err(reason),
            Err(error) => Err(error.to_string()),
        }
    }

    /// Registration without a class reference. Kept so a failure to capture the class
    /// still leaves an honest "the bridge class was never registered" instead of
    /// silently reporting the keystore as usable.
    pub fn register_without_class(vm: JavaVM) {
        let _ = VM.set(vm);
    }

    pub fn seal(plain: &str) -> Result<String, CoreError> {
        call_string("seal", Some(plain))
    }

    pub fn open(sealed: &str) -> Result<String, CoreError> {
        call_string("open", Some(sealed))
    }
}

#[cfg(target_os = "android")]
#[no_mangle]
pub extern "system" fn Java_com_lamtools_sunday_core_KeystoreBridge_nativeRegister(
    mut env: jni::JNIEnv,
    class: jni::objects::JClass,
) {
    let Ok(vm) = env.get_java_vm() else {
        return;
    };
    // Captured here because this is the one call that comes from the class itself, so
    // the class loader is the application's.
    let Ok(global) = env.new_global_ref(&class) else {
        bridge::register_without_class(vm);
        return;
    };
    bridge::register(vm, global);
}

/// The keystore is not available on this build, and says so.
#[cfg(not(target_os = "android"))]
mod bridge {
    use sunday_protocol::CoreError;

    fn unavailable() -> CoreError {
        CoreError::storage(
            "Android keystore is not available on this build; the desktop host uses an \
             owner-only file instead",
        )
    }

    pub fn probe() -> Result<(), String> {
        Err("this build has no Android keystore".to_owned())
    }
    pub fn seal(_plain: &str) -> Result<String, CoreError> {
        Err(unavailable())
    }
    pub fn open(_sealed: &str) -> Result<String, CoreError> {
        Err(unavailable())
    }
}

pub use bridge::{open, probe, seal};
