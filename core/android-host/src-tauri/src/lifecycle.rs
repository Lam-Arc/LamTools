//! The Android side of the lifecycle: it maps OS callbacks onto
//! `sunday_host::lifecycle`.
//!
//! This file is deliberately thin. Every decision lives in
//! `sunday_host::lifecycle`, where it can be tested without an emulator. What is
//! here is the mapping from Android's callbacks, plus the single place that gathers
//! the two authoritative inputs: the runner's live threads and the journal's
//! recovery plan.
//!
//! Why this is not done in the webview: the OS is the only thing that knows the app
//! lost visibility. A lifecycle signal that starts in Vue stops arriving exactly
//! when it matters, because a backgrounded or throttled webview is the first thing
//! Android slows down.

use std::sync::Mutex;

use sunday_host::app_server::TurnRunner;
use sunday_host::lifecycle::{Journal, Tracker};
use sunday_host::runner::CoreRunner;

pub struct Lifecycle {
    tracker: Mutex<Tracker>,
}

impl Lifecycle {
    pub fn new(data_dir: &std::path::Path) -> Self {
        Self {
            tracker: Mutex::new(Tracker::new(
                data_dir,
                sunday_host::lifecycle::new_instance_id(),
            )),
        }
    }

    /// The id of this process lifetime, for `core_info` and for tests.
    pub fn instance(&self) -> String {
        self.tracker
            .lock()
            .expect("lifecycle lock")
            .instance()
            .to_owned()
    }
}

fn running(runner: &CoreRunner) -> Vec<String> {
    TurnRunner::running_threads(runner as &dyn TurnRunner)
}

fn journal(runner: &CoreRunner) -> Journal {
    match runner.recovery() {
        Ok(plan) => Journal::Read(plan),
        Err(error) => Journal::Unavailable(error.to_string()),
    }
}

pub fn pause(lifecycle: &Lifecycle) -> serde_json::Value {
    lifecycle.tracker.lock().expect("lifecycle lock").on_pause()
}

pub fn stop(lifecycle: &Lifecycle, runner: &CoreRunner) -> serde_json::Value {
    // Read before taking the tracker lock, so a slow turn map never serialises
    // against a concurrent pause.
    let threads = running(runner);
    lifecycle
        .tracker
        .lock()
        .expect("lifecycle lock")
        .on_stop(&threads)
}

pub fn destroy(lifecycle: &Lifecycle) -> serde_json::Value {
    lifecycle
        .tracker
        .lock()
        .expect("lifecycle lock")
        .on_destroy()
}

pub fn resume(lifecycle: &Lifecycle, runner: &CoreRunner) -> serde_json::Value {
    // The journal is read before the tracker lock is taken. `recover()` is a small
    // write transaction, and holding both locks at once would make the resume path
    // hold the store for longer than it needs to.
    let threads = running(runner);
    let journal = journal(runner);
    lifecycle
        .tracker
        .lock()
        .expect("lifecycle lock")
        .on_resume(&threads, journal)
}

/// The single entry point for every lifecycle signal.
///
/// Both the IPC command and the JNI bridge go through here, so the two paths cannot
/// drift into reporting different things about the same event.
pub fn signal(lifecycle: &Lifecycle, runner: &CoreRunner, event: &str) -> serde_json::Value {
    match event {
        "pause" | "focus_lost" => pause(lifecycle),
        "stop" | "background" => stop(lifecycle, runner),
        "destroy" => destroy(lifecycle),
        "resume" | "foreground" => resume(lifecycle, runner),
        other => serde_json::json!({
            "signal": other,
            "ignored": true,
            "reason": "unknown lifecycle signal",
        }),
    }
}
