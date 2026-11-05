//! Android host for the Rust core.
//!
//! Two decisions worth stating, because both were changed after review:
//!
//! 1. **No listening socket.** The previous version served the protocol on a
//!    loopback WebSocket. On Android every app on the device can dial another
//!    app's loopback port, so that was reachable by anything installed alongside
//!    this one. The protocol now runs over Tauri IPC: the webview invokes a
//!    command, the command hands it to `Session`, and there is no socket to find.
//!    A token is kept for the desktop/CLI transport, where a socket is unavoidable
//!    and cross-process access is the point.
//!
//! 2. **Deny by default.** The previous config defaulted `auto_approve` to `true`,
//!    so a fresh install would write and delete files without asking. Approvals
//!    are now governed by `GrantPolicy`: reading is allowed, anything with a side
//!    effect asks unless the host names that exact tool.
//!
//! What this host owns, and nothing else: the sandbox path, the lifecycle hooks,
//! the secret storage, and the IPC surface. Everything about how a turn runs is
//! in `sunday_host::runner`, shared with the CLI.

use std::sync::Arc;

use sunday_host::app_server::{FrameSink, Session};
use sunday_host::policy::GrantPolicy;
use sunday_host::runner::{CoreOptions, CoreRunner};
use tauri::{Emitter, Manager};

pub mod config;
pub mod config_rpc;
pub mod http_surface;
pub mod keystore;
pub mod lifecycle;
pub mod projection;
pub mod provider;
pub mod secrets;
pub mod settings;

/// Bridges the core's event stream to the webview.
///
/// Events are emitted as `core-event` with the same envelope the socket transport
/// would have written, so the frontend does not need two code paths.
struct IpcSink {
    app: tauri::AppHandle,
    /// Shared with the resume path so history and realtime agree on which turn an
    /// item belongs to and on what a tool call is called.
    projector: Arc<std::sync::Mutex<projection::Projector>>,
}

impl FrameSink for IpcSink {
    fn event(&self, body: serde_json::Value) {
        // The webview renders `core/runItem`, not the runner's own words. Projecting
        // here — at the boundary, not in the UI — keeps one code path for both cores.
        let projected = {
            let mut projector = self.projector.lock().unwrap();
            projector.project(&body)
        };
        let Some(projected) = projected else {
            #[cfg(debug_assertions)]
            println!(
                "core_event (not rendered) -> {} seq={}",
                body.get("method")
                    .and_then(|value| value.as_str())
                    .unwrap_or("?"),
                body.get("seq")
                    .and_then(|value| value.as_u64())
                    .unwrap_or(0),
            );
            return;
        };
        #[cfg(debug_assertions)]
        println!(
            "core_event -> {} kind={} seq={}",
            projected
                .get("method")
                .and_then(|value| value.as_str())
                .unwrap_or("?"),
            projected
                .get("payload")
                .and_then(|payload| payload.get("kind"))
                .and_then(|value| value.as_str())
                .unwrap_or("?"),
            projected
                .get("seq")
                .and_then(|value| value.as_u64())
                .unwrap_or(0),
        );
        let _ = self.app.emit("core-event", projected);
    }
    fn orphan_error(&self, code: i32, message: String) {
        let _ = self.app.emit(
            "core-event",
            serde_json::json!({
                "method": "core/error",
                "params": {"code": code, "message": message},
            }),
        );
    }
}

/// State the IPC commands need.
pub struct CoreState {
    session: Session,
    runner: Arc<CoreRunner>,
    data_dir: std::path::PathBuf,
    /// Projects, sessions and their files, served to the shared UI over `core_http`.
    projects: sunday_host::projects::Projects,
    /// What the operating system reported, and what it is allowed to claim.
    lifecycle: lifecycle::Lifecycle,
    /// Turns the runner's events into the projection the shared UI renders.
    projector: Arc<std::sync::Mutex<projection::Projector>>,
    /// Kept alive for the process lifetime: dropping it releases the single-writer
    /// lock and a second instance could then open the same database.
    _lock: sunday_host::lock::SingleWriterLock,
}

/// One RPC call. This is the whole IPC surface: it mirrors the socket protocol
/// exactly, so the frontend can swap transports without changing call sites.
#[tauri::command]
async fn core_rpc(
    app: tauri::AppHandle,
    state: tauri::State<'_, Arc<CoreState>>,
    method: String,
    params: serde_json::Value,
) -> Result<serde_json::Value, String> {
    // The settings screen speaks a `config.*` catalog that the desktop core owns.
    // This host has a single provider binding instead, so those methods are answered
    // by the adapter rather than handed to the runner, which would answer "method
    // not found" and leave the model screen permanently unusable.
    let core = Arc::clone(state.inner());
    if let Some(answer) = config_rpc::handle(&core, &method, &params).await {
        return answer;
    }

    let sink: Arc<dyn FrameSink> = Arc::new(IpcSink {
        app,
        projector: Arc::clone(&core.projector),
    });
    match state.session.handle(&method, &params, sink) {
        Ok(mut result) => {
            // A resumed conversation arrives as journal events. They have to be
            // projected by the same rules as the live stream, or the restored
            // transcript would be a second dialect of the same facts.
            project_events(&mut result, &core.projector);
            Ok(result)
        }
        Err((code, message, _data)) => Err(format!("{code}: {message}")),
    }
}

/// Rewrites a reply's `events` array into the shared UI's projection.
///
/// Only replies that carry history are affected; everything else passes through
/// untouched, so a method that never had events cannot be changed by this.
fn project_events(
    result: &mut serde_json::Value,
    projector: &Arc<std::sync::Mutex<projection::Projector>>,
) {
    let Some(events) = result
        .get_mut("events")
        .and_then(|value| value.as_array_mut())
    else {
        return;
    };
    let mut guard = projector.lock().unwrap();
    let projected: Vec<serde_json::Value> = events
        .iter()
        .filter_map(|event| guard.project(event))
        .collect();
    // One line that answers "why does the composer still say Stop": the exact
    // kind/item/status triple the client is about to receive, in order.
    #[cfg(debug_assertions)]
    {
        let summary: Vec<String> = projected
            .iter()
            .map(|item| {
                let payload = item.get("payload").cloned().unwrap_or_default();
                format!(
                    "{}|{}|{}",
                    payload.get("kind").and_then(|v| v.as_str()).unwrap_or("?"),
                    payload
                        .get("item_id")
                        .and_then(|v| v.as_str())
                        .unwrap_or("?"),
                    payload
                        .get("status")
                        .and_then(|v| v.as_str())
                        .unwrap_or("?"),
                )
            })
            .collect();
        println!(
            "resume projection: {} events :: {}",
            summary.len(),
            summary.join(", ")
        );
    }
    *events = projected;
}

/// Where the data actually lives, for Settings and for tests.
#[tauri::command]
fn core_info(state: tauri::State<'_, Arc<CoreState>>) -> serde_json::Value {
    serde_json::json!({
        "transport": "ipc",
        "data_dir": state.data_dir.to_string_lossy(),
        "thread_id": state.session.thread_id(),
    })
}

/// One lifecycle signal, from whichever side reported it.
///
/// Both the JNI bridge and the IPC command come through here, so a signal reported
/// by the OS and one requested by the UI cannot produce different answers.
fn apply_lifecycle(state: &CoreState, event: &str) -> serde_json::Value {
    lifecycle::signal(&state.lifecycle, &state.runner, event)
}

/// Asks the core for a lifecycle report, on behalf of the UI.
///
/// Reading it here does not change what happened: the tracker already holds the
/// answer from the OS. This exists so a resumed screen can render synchronously
/// without waiting for the event that the JNI path emits.
#[tauri::command]
fn lifecycle_signal(state: tauri::State<'_, Arc<CoreState>>, event: String) -> serde_json::Value {
    apply_lifecycle(&state, &event)
}

/// Kept as its own command because the old name is what the UI calls.
#[tauri::command]
fn lifecycle_pause(state: tauri::State<'_, Arc<CoreState>>) -> serde_json::Value {
    apply_lifecycle(&state, "pause")
}

#[tauri::command]
fn lifecycle_resume(state: tauri::State<'_, Arc<CoreState>>) -> serde_json::Value {
    apply_lifecycle(&state, "resume")
}

/// The Android Activity callbacks, arriving over JNI.
///
/// `onStop` is the reason this exists: Tauri maps `onPause` and `onResume` to window
/// events but has no equivalent for `onStop`, and `onStop` is the one that means the
/// app is no longer visible. `onPause` fires on a rotation and on a permission
/// dialog, so treating it as "backgrounded" would be wrong most of the time.
#[cfg(target_os = "android")]
mod android_bridge {
    use std::sync::{Arc, OnceLock};

    use super::CoreState;
    use tauri::{Emitter, Manager};

    static APP: OnceLock<tauri::AppHandle> = OnceLock::new();

    pub fn publish(handle: tauri::AppHandle) {
        let _ = APP.set(handle);
    }

    fn state(app: &tauri::AppHandle) -> Option<tauri::State<'_, Arc<CoreState>>> {
        // Before `setup` completes there is no state, and a signal that arrives then
        // has nothing to report on: there is no turn and no journal worth reading.
        app.try_state::<Arc<CoreState>>()
    }

    pub fn deliver(event: &str) {
        let Some(app) = APP.get() else {
            return;
        };
        let Some(state) = state(app) else {
            return;
        };
        let report = super::apply_lifecycle(&state, event);
        // Emitted as well as returned, because the JNI call has no caller waiting:
        // a resumed UI learns what happened through this event.
        let _ = app.emit("lifecycle", report);
    }
}

#[cfg(target_os = "android")]
#[no_mangle]
pub extern "system" fn Java_com_lamtools_sunday_core_LifecycleBridge_signal(
    mut env: jni::JNIEnv,
    _class: jni::objects::JClass,
    event: jni::objects::JString,
) {
    let Ok(text) = env.get_string(&event) else {
        return;
    };
    let event: String = text.into();
    android_bridge::deliver(&event);
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            let handle = app.handle().clone();
            let data_dir = app
                .path()
                .app_data_dir()
                .map_err(|e| format!("cannot resolve the app data dir: {e}"))?;
            std::fs::create_dir_all(&data_dir)
                .map_err(|e| format!("cannot create {}: {e}", data_dir.display()))?;

            let lock = sunday_host::lock::SingleWriterLock::acquire(&data_dir, "sunday-android")
                .map_err(|e| format!("cannot take the data directory: {e}"))?;

            let cfg = config::load_or_default(&data_dir)?;
            let workspace = data_dir.join("workspace");
            let workspace_path = workspace.clone();
            std::fs::create_dir_all(&workspace)?;

            // The API key comes from the platform secret store, not from the JSON
            // config: a key in a JSON file is a key in every backup and log.
            // Which credential storage is actually in use, on the record. This is the
            // only place the keystore probe runs at startup, and a support log without
            // it cannot answer "is the key sealed or sitting in a file".
            let storage = secrets::storage_view(&data_dir);
            println!(
                "credential storage: {} (needs migration: {}, key present: {}, readable: {})",
                storage["kind"],
                storage["needs_migration"],
                storage["has_key"],
                storage["readable"]
            );
            if let Some(reason) = storage["reason"].as_str() {
                println!("credential storage unavailable: {reason}");
            }

            let store = sunday_store::Store::open(data_dir.join("core.db"))?;
            // The key is only ever handed to an endpoint the user approved. When it
            // has not been, this returns a model that refuses with the reason instead
            // of a client that would send the key anyway.
            let model = provider::build_model(&data_dir, &cfg)?;

            let runner = Arc::new(CoreRunner::new(CoreOptions {
                store,
                model,
                model_id: cfg.model_id.clone(),
                workspace: workspace.to_string_lossy().to_string(),
                host_kind: sunday_protocol::HostKind::Android,
                // Reads are fine; writes and deletes ask. The user opts specific
                // tools in from the UI, one at a time.
                policy: GrantPolicy::with_grants(cfg.granted_tools.clone()),
                system: Some("You are Sunday. Use the tools you are given.".into()),
            }));

            // A trusted session: IPC has no socket, so there is nothing to
            // authenticate against and no way to reach it from outside the app.
            let session = Session::trusted(
                Arc::clone(&runner) as Arc<dyn sunday_host::app_server::TurnRunner>
            );

            let lifecycle = lifecycle::Lifecycle::new(&data_dir);
            println!(
                "sunday core ready over ipc, data at {}, instance {}",
                data_dir.display(),
                lifecycle.instance()
            );
            // Projects live under the same workspace the runner uses, so a file the agent
            // writes is a file the user can open, and the boundary is one directory.
            let projects = sunday_host::projects::Projects::new(&data_dir, &workspace_path);
            app.manage(Arc::new(CoreState {
                session,
                runner,
                data_dir,
                projects,
                lifecycle,
                projector: Arc::new(std::sync::Mutex::new(projection::Projector::new())),
                _lock: lock,
            }));
            // Published so the JNI bridge, which runs on an Android thread with no
            // access to Tauri's context, can find the state it is reporting to.
            #[cfg(target_os = "android")]
            android_bridge::publish(handle.clone());
            // Android delivers its first `onResume` before `setup` has registered
            // the state above, so that signal is dropped. The report it would have
            // produced is the one that matters most: whether the previous process
            // died with work in flight. Ask for it here, where the state exists.
            let startup = {
                let state = app.state::<Arc<CoreState>>();
                lifecycle::resume(&state.lifecycle, &state.runner)
            };
            // Printed as well as emitted: a cold-start report is the only evidence
            // that a kill was noticed, and a dropped event would erase it.
            println!("lifecycle at startup: {startup}");
            handle.emit("lifecycle", &startup).ok();
            handle.emit("core-ready", ()).ok();
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            core_rpc,
            core_info,
            http_surface::core_http,
            settings::model_config,
            settings::save_model_config,
            settings::approve_endpoint,
            settings::set_api_key,
            settings::clear_api_key,
            settings::tool_catalog,
            settings::set_tool_grant,
            lifecycle_signal,
            lifecycle_pause,
            lifecycle_resume,
        ])
        .run(tauri::generate_context!())
        .expect("error while running the Android host");
}
