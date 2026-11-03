//! Lifecycle: what happens when the app leaves the foreground and comes back.
//!
//! The rule this encodes: **a running turn is not cancelled because the user
//! switched apps.** Cancelling there would silently truncate work the user
//! started and walked away from, and they would see a half-written file with no
//! explanation.
//!
//! What is recorded instead: which threads had a turn in flight. On resume that
//! note is read and reported, so the UI can say "this turn was interrupted" rather
//! than pretending nothing happened. The turn itself is not replayed: a
//! non-idempotent tool whose result is unknown must never be re-run automatically
//! (invariant I4). The store already marks such calls, and `recover()` is what a
//! host calls to learn about them.
//!
//! A process that is killed is not "paused". Nothing here tries to survive that;
//! the journal and the recovery plan already do.

use std::path::{Path, PathBuf};

pub const STATE_FILE: &str = "lifecycle.json";

#[derive(Clone, Debug, Default, serde::Serialize, serde::Deserialize)]
pub struct LifecycleState {
    /// Threads that had a turn running when the app was backgrounded.
    pub interrupted_threads: Vec<String>,
    /// Epoch milliseconds of the last pause.
    pub paused_at_ms: u64,
    /// Whether a resume has been reported to the UI yet.
    pub resumed: bool,
}

fn path_in(dir: &Path) -> PathBuf {
    dir.join(STATE_FILE)
}

fn now_ms() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

pub fn load(dir: &Path) -> LifecycleState {
    std::fs::read_to_string(path_in(dir))
        .ok()
        .and_then(|text| serde_json::from_str(&text).ok())
        .unwrap_or_default()
}

fn save(dir: &Path, state: &LifecycleState) {
    let body = serde_json::to_string_pretty(state).unwrap_or_default();
    // Best effort: failing to write a note must not break the app.
    let _ = std::fs::write(path_in(dir), body);
}

/// Records what was in flight. Deliberately does not stop anything.
pub fn on_pause(dir: &Path, running_threads: &[String]) -> serde_json::Value {
    let state = LifecycleState {
        interrupted_threads: running_threads.to_vec(),
        paused_at_ms: now_ms(),
        resumed: false,
    };
    save(dir, &state);
    serde_json::json!({
        "paused": true,
        "interrupted_threads": state.interrupted_threads,
        // Stated explicitly so the UI copy cannot drift into claiming the turn
        // keeps running in the background.
        "turn_continues_in_background": false,
    })
}

/// Reports what was interrupted, and clears the note.
pub fn on_resume(dir: &Path) -> serde_json::Value {
    let mut state = load(dir);
    let interrupted = std::mem::take(&mut state.interrupted_threads);
    state.resumed = true;
    save(dir, &state);
    serde_json::json!({
        "resumed": true,
        "interrupted_threads": interrupted,
        "paused_for_ms": if state.paused_at_ms == 0 {
            0
        } else {
            now_ms().saturating_sub(state.paused_at_ms)
        },
        // Never automatic: a non-idempotent call with an unknown result must not
        // be replayed, so a host must ask before continuing.
        "auto_resumed_turns": false,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_pause_records_what_was_running_without_stopping_it() {
        let dir = tempfile::tempdir().unwrap();
        let report = on_pause(dir.path(), &["t1".to_owned(), "t2".to_owned()]);
        assert_eq!(report["paused"], true);
        assert_eq!(report["interrupted_threads"][0], "t1");
        assert_eq!(report["turn_continues_in_background"], false);

        let state = load(dir.path());
        assert_eq!(state.interrupted_threads.len(), 2);
    }

    #[test]
    fn a_resume_reports_the_interruption_once() {
        let dir = tempfile::tempdir().unwrap();
        on_pause(dir.path(), &["t1".to_owned()]);
        let first = on_resume(dir.path());
        assert_eq!(first["interrupted_threads"][0], "t1");
        assert_eq!(first["auto_resumed_turns"], false);

        // A second resume must not repeat the warning: the user has seen it.
        let second = on_resume(dir.path());
        assert_eq!(
            second["interrupted_threads"].as_array().unwrap().len(),
            0,
            "the interruption was reported twice"
        );
    }

    #[test]
    fn a_pause_with_nothing_running_is_still_safe() {
        let dir = tempfile::tempdir().unwrap();
        let report = on_pause(dir.path(), &[]);
        assert_eq!(report["interrupted_threads"].as_array().unwrap().len(), 0);
    }

    #[test]
    fn a_missing_state_file_is_the_empty_state() {
        let dir = tempfile::tempdir().unwrap();
        let state = load(dir.path());
        assert!(state.interrupted_threads.is_empty());
        assert_eq!(state.paused_at_ms, 0);
    }
}
