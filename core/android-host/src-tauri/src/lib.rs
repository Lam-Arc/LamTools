//! Minimal Android host for the Rust core.
//!
//! What it does, and nothing more:
//!
//!   * opens the core's SQLite database inside the app's own sandbox directory
//!   * takes the single-writer lock before opening it
//!   * serves `core.app_server.v1` on a loopback port
//!   * tells the WebView which port it got
//!
//! What it deliberately does not do: tray icons, pet overlay, native window
//! management. Those are desktop concerns; including them is how an "Android
//! port" turns into a pile of `#[cfg(not(target_os = "android"))]` branches.
//!
//! The path comes from Tauri's app data dir, which on Android is the app's own
//! private storage (`/data/data/<package>/files`), not `/data/local/tmp`. That
//! distinction is the whole point of this host existing.

use std::sync::Arc;
use tauri::{Emitter, Manager};

pub mod core_service;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            let handle = app.handle().clone();
            // Resolved from Tauri, so it is the real app sandbox on every host.
            let data_dir = app
                .path()
                .app_data_dir()
                .map_err(|e| format!("cannot resolve the app data dir: {e}"))?;
            std::fs::create_dir_all(&data_dir)
                .map_err(|e| format!("cannot create {}: {e}", data_dir.display()))?;

            let service = core_service::CoreService::start(data_dir)?;
            let port = service.port();
            println!(
                "sunday core listening on 127.0.0.1:{port}, data at {}",
                service.data_dir().display()
            );
            // Kept alive for the process lifetime: dropping it would stop the
            // server and release the single-writer lock mid-session.
            app.manage(Arc::new(service));

            // Tell the loaded page where to connect. The frontend reads this
            // before it constructs its transport.
            handle.emit("core-port", port).ok();
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![core_service::core_port, core_service::core_info])
        .run(tauri::generate_context!())
        .expect("error while running the Android host");
}
