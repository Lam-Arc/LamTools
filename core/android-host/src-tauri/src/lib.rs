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
pub mod lifecycle;
pub mod secrets;

/// Bridges the core's event stream to the webview.
///
/// Events are emitted as `core-event` with the same envelope the socket transport
/// would have written, so the frontend does not need two code paths.
struct IpcSink {
    app: tauri::AppHandle,
}

impl FrameSink for IpcSink {
    fn event(&self, body: serde_json::Value) {
        let _ = self.app.emit("core-event", body);
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
    let sink: Arc<dyn FrameSink> = Arc::new(IpcSink { app });
    match state.session.handle(&method, &params, sink) {
        Ok(result) => Ok(result),
        Err((code, message, _data)) => Err(format!("{code}: {message}")),
    }
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

/// Called by the app when it leaves the foreground.
///
/// Deliberately does not kill a running turn. Cancelling on background would
/// silently truncate work the user started and walked away from; the state is
/// persisted so a later resume finds it.
#[tauri::command]
fn lifecycle_pause(state: tauri::State<'_, Arc<CoreState>>) -> serde_json::Value {
    let running = sunday_host::app_server::TurnRunner::running_threads(
        state.runner.as_ref() as &dyn sunday_host::app_server::TurnRunner,
    );
    lifecycle::on_pause(&state.data_dir, &running)
}

/// Called by the app when it returns.
#[tauri::command]
fn lifecycle_resume(state: tauri::State<'_, Arc<CoreState>>) -> serde_json::Value {
    lifecycle::on_resume(&state.data_dir)
}

/// Model configuration, without ever returning the key.
#[tauri::command]
fn model_config(state: tauri::State<'_, Arc<CoreState>>) -> serde_json::Value {
    config::public_view(&state.data_dir)
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
            std::fs::create_dir_all(&workspace)?;

            // The API key comes from the platform secret store, not from the JSON
            // config: a key in a JSON file is a key in every backup and log.
            let api_key = secrets::read_api_key(&data_dir).unwrap_or_default();
            let store = sunday_store::Store::open(data_dir.join("core.db"))?;
            let model: Arc<dyn sunday_protocol::Model> = if cfg.model_id.starts_with("scripted") {
                Arc::new(sunday_host::runner::scripted_model(&cfg.model_id)?)
            } else {
                Arc::new(sunday_llm::LlmClient::new(sunday_llm::ProviderConfig::openai(
                    cfg.base_url.clone(),
                    api_key,
                ))?)
            };

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
            let session = Session::trusted(Arc::clone(&runner) as Arc<dyn sunday_host::app_server::TurnRunner>);

            println!(
                "sunday core ready over ipc, data at {}",
                data_dir.display()
            );
            app.manage(Arc::new(CoreState {
                session,
                runner,
                data_dir,
                _lock: lock,
            }));
            handle.emit("core-ready", ()).ok();
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            core_rpc,
            core_info,
            lifecycle_pause,
            lifecycle_resume,
            model_config,
        ])
        .run(tauri::generate_context!())
        .expect("error while running the Android host");
}
