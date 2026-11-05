//! The system document picker, as seen from Rust.
//!
//! user:“支持通过 Android 系统文件选择器选择单个或多个文件…正确处理 content:// URI、
//! 临时授权、持久授权和应用重启”+(选文件这件事只有系统能做，这里负责发起和收回答案)。
//!
//! Two decisions shape this module.
//!
//! **Copy, then forget the URI.** A `content://` grant lasts while the picking activity
//! lives, and the file behind it can be moved, renamed or deleted by its owner at any
//! time. The picker therefore copies the bytes into the app's own directory inside the
//! same grant and hands back real paths. Nothing downstream holds a URI, so nothing
//! downstream can be broken by a provider going away, and no persistable grant slots are
//! taken from the user for copies that are about to be re-imported by the core anyway.
//!
//! **The answer arrives on another thread.** The picker is an activity result: it returns
//! to Kotlin, not to the Rust call that started it. The caller parks a one-shot channel
//! under a request id, Kotlin calls back through `nativeDeliver` with that id, and the
//! waiting side is woken by exactly one message. A cancelled picker and a crash both
//! produce a message; only a picker that never returns produces the timeout.

/// What one picked file became.
#[derive(Clone, Debug, Default, PartialEq, Eq, serde::Deserialize, serde::Serialize)]
pub struct PickedFile {
    pub name: String,
    /// Absolute path inside the app sandbox, where the picker copied the bytes.
    pub path: String,
    #[serde(default)]
    pub mime: String,
    #[serde(default)]
    pub size: u64,
}

/// A file the picker was given but could not copy.
///
/// Returned instead of thrown: one unreadable file must not lose the other nine, and the
/// screen can only tell the user which one failed if it is named.
#[derive(Clone, Debug, Default, PartialEq, Eq, serde::Deserialize, serde::Serialize)]
pub struct PickedFailure {
    pub name: String,
    pub reason: String,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, serde::Deserialize, serde::Serialize)]
pub struct PickedFiles {
    pub files: Vec<PickedFile>,
    pub failed: Vec<PickedFailure>,
}

#[cfg(target_os = "android")]
mod opener {
    use std::sync::OnceLock;

    use jni::objects::{GlobalRef, JClass, JString, JValue, JValueOwned};
    use jni::{JNIEnv, JavaVM};

    static VM: OnceLock<JavaVM> = OnceLock::new();
    static CLASS_REF: OnceLock<GlobalRef> = OnceLock::new();

    pub fn register(vm: JavaVM, class: GlobalRef) {
        let _ = VM.set(vm);
        let _ = CLASS_REF.set(class);
    }

    fn cached_class<'local>() -> Result<JClass<'local>, String> {
        let held = CLASS_REF
            .get()
            .ok_or_else(|| "the file opener bridge was never registered".to_owned())?;
        // Safety: a global reference outlives this call, and the wrapper never escapes it.
        Ok(unsafe { JClass::from_raw(held.as_obj().as_raw() as jni::sys::jclass) })
    }

    /// Asks the platform to open the file. An empty answer means it opened.
    pub fn open(path: &str, mime: &str) -> Result<(), String> {
        let vm = VM
            .get()
            .ok_or_else(|| "the file opener bridge was never registered".to_owned())?;
        let mut env = vm
            .attach_current_thread()
            .map_err(|error| format!("cannot attach a thread: {error}"))?;
        let class = cached_class()?;
        let path_arg = env
            .new_string(path)
            .map_err(|error| format!("cannot pass the path: {error}"))?;
        let mime_arg = env
            .new_string(mime)
            .map_err(|error| format!("cannot pass the type: {error}"))?;
        let outcome = env.call_static_method(
            &class,
            "open",
            "(Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;",
            &[JValue::Object(&path_arg), JValue::Object(&mime_arg)],
        );
        let value = match outcome {
            Ok(value) => value,
            Err(error) => {
                let _ = env.exception_clear();
                return Err(format!("the file opener failed: {error}"));
            }
        };
        let object = match value {
            JValueOwned::Object(object) => object,
            _ => return Err("the file opener answered with something that is not text".into()),
        };
        if object.is_null() {
            return Ok(());
        }
        let reason = JString::from(object);
        let reason = env
            .get_string(&reason)
            .map(|text| String::from(text))
            .unwrap_or_default();
        if reason.is_empty() {
            Ok(())
        } else {
            Err(reason)
        }
    }
}

/// Asks the platform to open a file with whatever handles its type.
#[cfg(target_os = "android")]
pub fn open_with_system(path: &str, mime: &str) -> Result<(), String> {
    opener::open(path, mime)
}

/// A host with no window manager cannot lend a file to another program.
#[cfg(not(target_os = "android"))]
pub fn open_with_system(_path: &str, _mime: &str) -> Result<(), String> {
    Err("this build cannot open files with another program".to_owned())
}

#[cfg(target_os = "android")]
mod bridge {
    use std::collections::HashMap;
    use std::sync::mpsc::{channel, Sender};
    use std::sync::{Mutex, OnceLock};
    use std::time::Duration;

    use jni::objects::{GlobalRef, JClass, JString, JValue, JValueOwned};
    use jni::{JNIEnv, JavaVM};

    const PICK_SIGNATURE: &str = "(Ljava/lang/String;)V";

    static VM: OnceLock<JavaVM> = OnceLock::new();
    static CLASS_REF: OnceLock<GlobalRef> = OnceLock::new();
    static WAITING: OnceLock<Mutex<HashMap<String, Sender<String>>>> = OnceLock::new();

    fn waiting() -> &'static Mutex<HashMap<String, Sender<String>>> {
        WAITING.get_or_init(|| Mutex::new(HashMap::new()))
    }

    pub fn register(vm: JavaVM, class: GlobalRef) {
        let _ = VM.set(vm);
        let _ = CLASS_REF.set(class);
    }

    /// The class reference Kotlin handed over at load time.
    ///
    /// A global reference is valid on any thread, which a lookup by name from an attached
    /// thread would not be: the class loader there is not the application's.
    fn cached_class<'local>() -> Result<JClass<'local>, String> {
        let held = CLASS_REF
            .get()
            .ok_or_else(|| "the file picker bridge was never registered".to_owned())?;
        // Safety: a global reference outlives this call, and the wrapper never escapes it.
        Ok(unsafe { JClass::from_raw(held.as_obj().as_raw() as jni::sys::jclass) })
    }

    fn request_id() -> String {
        use std::sync::atomic::{AtomicU64, Ordering};
        static COUNTER: AtomicU64 = AtomicU64::new(0);
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|elapsed| elapsed.as_nanos())
            .unwrap_or(0);
        format!("pick-{nanos}-{}", COUNTER.fetch_add(1, Ordering::SeqCst))
    }

    fn start(request_id: &str) -> Result<(), String> {
        let vm = VM
            .get()
            .ok_or_else(|| "the file picker bridge was never registered".to_owned())?;
        let mut env = vm
            .attach_current_thread()
            .map_err(|error| format!("cannot attach a thread: {error}"))?;
        let class = cached_class()?;
        let argument = env
            .new_string(request_id)
            .map_err(|error| format!("cannot pass the request id: {error}"))?;
        let outcome = env.call_static_method(
            &class,
            "pick",
            PICK_SIGNATURE,
            &[JValue::Object(&argument)],
        );
        match outcome {
            Ok(JValueOwned::Object(_)) | Ok(_) => Ok(()),
            Err(error) => {
                // A Java exception here means the picker could not even be asked to
                // open; clearing it keeps the process from carrying it into the next call.
                let _ = env.exception_clear();
                Err(format!("the document picker refused to start: {error}"))
            }
        }
    }

    /// Starts the picker and waits for Kotlin to report what the user chose.
    pub fn pick(timeout: Duration) -> Result<String, String> {
        let id = request_id();
        let (sender, receiver) = channel();
        waiting().lock().expect("picker map").insert(id.clone(), sender);
        if let Err(error) = start(&id) {
            waiting().lock().expect("picker map").remove(&id);
            return Err(error);
        }
        match receiver.recv_timeout(timeout) {
            Ok(payload) => Ok(payload),
            Err(_) => {
                waiting().lock().expect("picker map").remove(&id);
                Err("文件选择器没有返回结果".to_owned())
            }
        }
    }

    /// Kotlin's answer, routed to whoever is waiting for this request.
    ///
    /// An unknown id is ignored rather than kept: a late answer for a request that
    /// already timed out has nobody to reach.
    pub fn deliver(request_id: &str, payload: &str) {
        if let Some(sender) = waiting().lock().expect("picker map").remove(request_id) {
            let _ = sender.send(payload.to_owned());
        }
    }
}

#[cfg(target_os = "android")]
#[no_mangle]
pub extern "system" fn Java_com_lamtools_sunday_core_OpenFileBridge_nativeRegister(
    mut env: jni::JNIEnv,
    class: jni::objects::JClass,
) {
    let Ok(vm) = env.get_java_vm() else {
        return;
    };
    let Ok(global) = env.new_global_ref(&class) else {
        return;
    };
    opener::register(vm, global);
}

#[cfg(target_os = "android")]
#[no_mangle]
pub extern "system" fn Java_com_lamtools_sunday_core_FilePickerBridge_nativeRegister(
    mut env: jni::JNIEnv,
    class: jni::objects::JClass,
) {
    let Ok(vm) = env.get_java_vm() else {
        return;
    };
    let Ok(global) = env.new_global_ref(&class) else {
        return;
    };
    bridge::register(vm, global);
}

#[cfg(target_os = "android")]
#[no_mangle]
pub extern "system" fn Java_com_lamtools_sunday_core_FilePickerBridge_nativeDeliver(
    mut env: jni::JNIEnv,
    _class: jni::objects::JClass,
    request_id: jni::objects::JString,
    payload: jni::objects::JString,
) {
    let Ok(id) = env.get_string(&request_id) else {
        return;
    };
    let Ok(body) = env.get_string(&payload) else {
        return;
    };
    let id: String = id.into();
    let body: String = body.into();
    bridge::deliver(&id, &body);
}

/// How long the UI waits for the system picker before giving up.
///
/// Generous: choosing a file can take a while on a large document provider, and the user
/// is the slow part. The point of a limit is to release the waiting thread at all, not to
/// hurry anyone.
#[cfg(target_os = "android")]
const PICK_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(900);

/// Opens the system picker and copies what the user chose into the sandbox.
///
/// The copy is what makes the rest of the pipeline simple: every later step sees a real
/// path inside the app's own storage, exactly as a desktop file chooser would hand over.
#[cfg(target_os = "android")]
pub fn pick() -> Result<PickedFiles, String> {
    let payload = bridge::pick(PICK_TIMEOUT)?;
    let parsed: PickedFiles = serde_json::from_str(&payload)
        .map_err(|error| format!("the picker answer could not be read: {error}"))?;
    Ok(parsed)
}

/// A desktop build of this host has no system picker to bridge to, and says so instead of
/// answering with an empty selection that reads as "the user cancelled".
#[cfg(not(target_os = "android"))]
pub fn pick() -> Result<PickedFiles, String> {
    Err("this build has no system file picker".to_owned())
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The shape Kotlin sends is the contract, so it is read the same way here.
    #[test]
    fn the_picker_answer_is_read_as_files_and_failures() {
        let payload = r#"{
            "files": [
                {"name":"notes.txt","path":"/data/app/files/picked/0/notes.txt","mime":"text/plain","size":12}
            ],
            "failed": [{"name":"huge.bin","reason":"超过 50 MB"}]
        }"#;
        let parsed: PickedFiles = serde_json::from_str(payload).unwrap();
        assert_eq!(parsed.files.len(), 1);
        assert_eq!(parsed.files[0].name, "notes.txt");
        assert_eq!(parsed.files[0].mime, "text/plain");
        assert_eq!(parsed.files[0].size, 12);
        assert_eq!(parsed.failed.len(), 1);
        assert_eq!(parsed.failed[0].name, "huge.bin");
    }

    /// A cancelled picker answers with no files rather than an error: the user closing a
    /// picker is not a failure and must not produce a red toast.
    #[test]
    fn a_cancelled_pick_is_an_empty_list() {
        let parsed: PickedFiles = serde_json::from_str(r#"{"files":[],"failed":[]}"#).unwrap();
        assert!(parsed.files.is_empty());
        assert!(parsed.failed.is_empty());
    }
}
