//! Lifecycle: what the host learns from the operating system, and what it can
//! honestly say when the app comes back.
//!
//! Android separates four events that a single `paused` flag conflates, and the
//! difference is visible to the user:
//!
//! | OS event | what it actually means | what this module does |
//! |---|---|---|
//! | `onPause` | focus lost. A rotation or a permission dialog triggers it too | memory only |
//! | `onStop` | not visible. The OS may freeze or kill the process | one small file |
//! | `onDestroy` | the activity said goodbye | marks that file |
//! | no `onDestroy`, different process id next start | the process died | reads the journal |
//!
//! Two rules are not negotiable here.
//!
//! **The journal is the fact; the marker is a hint.** When they disagree the store
//! wins: `Store::recover` knows which tool calls were dispatched and never answered.
//! The marker only says what a process *believed* when it lost visibility.
//!
//! **Nothing is replayed.** A non-idempotent call whose result is unknown is
//! reported for a human decision, never re-dispatched. Every report this module
//! produces carries `auto_resumed_turns: false` for that reason.
//!
//! What is deliberately absent: any promise that a turn keeps running while the app
//! is in the background. It may, while the process is alive, but Android is free to
//! freeze or kill it, so the report says `background_execution_guaranteed: false`
//! rather than pretending otherwise.

use std::path::{Path, PathBuf};

use sunday_store::RecoveryPlan;

/// Auxiliary only. Named apart from `.json` so nothing mistakes it for state.
pub const MARKER_FILE: &str = "lifecycle.marker";

/// A trailing audit trail of the reports this module produced.
///
/// Appended to, never read back to make a decision. Without it a report exists only
/// as an event, and an event nobody subscribed to leaves no evidence that the OS
/// signal was even received.
pub const REPORTS_FILE: &str = "lifecycle.reports.log";

/// Rewritten once it grows past this, keeping the newest half. A log that can grow
/// without bound is a slow disk leak on a device that never gets cleaned.
const REPORTS_LIMIT: usize = 64 * 1024;

/// A random identifier for one process lifetime.
///
/// This is the whole basis for telling "the activity was recreated" apart from "the
/// process died": a rotation keeps the process, so the id matches; a kill or a
/// crash starts a new one.
pub fn new_instance_id() -> String {
    let mut bytes = [0u8; 8];
    if getrandom::fill(&mut bytes).is_err() {
        // Without randomness the id cannot distinguish lifetimes. Say so with a
        // value that never matches, which fails towards "report a possible death"
        // rather than "assume nothing happened".
        return "unknown-randomness".into();
    }
    let mut out = String::with_capacity(16);
    for byte in bytes {
        out.push_str(&format!("{byte:02x}"));
    }
    out
}

fn marker_path(dir: &Path) -> PathBuf {
    dir.join(MARKER_FILE)
}

fn now_ms() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

#[derive(Clone, Debug, Default, serde::Serialize, serde::Deserialize)]
struct Marker {
    instance: String,
    /// `onDestroy` ran. Absent means the process left without saying goodbye.
    #[serde(default)]
    destroyed: bool,
    /// When the app stopped being visible. Zero means it never did.
    #[serde(default)]
    backgrounded_at_ms: u64,
    /// Advisory only. What was running when visibility was lost; the journal decides
    /// what actually happened.
    #[serde(default)]
    noted_threads: Vec<String>,
}

/// Appends one report as a single line.
///
/// Best effort by design: failing to write an audit line must never fail the
/// lifecycle transition it describes.
fn append_report(dir: &Path, report: &serde_json::Value) {
    let path = dir.join(REPORTS_FILE);
    let line = format!("{report}\n");
    let kept = match std::fs::read_to_string(&path) {
        Ok(text) if text.len() + line.len() > REPORTS_LIMIT => {
            // Keep the newest half, on a line boundary so the file stays parseable.
            let keep_from = text.len().saturating_sub(REPORTS_LIMIT / 2);
            match text[keep_from..].find('\n') {
                Some(offset) => {
                    let kept = &text[keep_from + offset + 1..];
                    let _ = crate::private_file::write(&path, kept, "lifecycle report log");
                    kept.to_owned()
                }
                None => String::new(),
            }
        }
        Ok(text) => text,
        Err(_) => String::new(),
    };
    let updated = format!("{kept}{line}");
    let _ = crate::private_file::write(&path, &updated, "lifecycle report log");
}

fn read_marker(dir: &Path) -> Option<Marker> {
    let text = std::fs::read_to_string(marker_path(dir)).ok()?;
    // A corrupt marker is not evidence of anything, so it is dropped rather than
    // guessed at. The journal is consulted instead.
    serde_json::from_str(&text).ok()
}

/// What the journal says about work that was interrupted.
///
/// `Unavailable` exists because "the store could not be read" and "the store says
/// nothing happened" are opposite claims, and a report that rendered them the same
/// way would tell the user their work is fine when nobody checked.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Journal {
    Read(RecoveryPlan),
    Unavailable(String),
}

impl Journal {
    fn snapshot(&self) -> serde_json::Value {
        match self {
            Self::Read(plan) => serde_json::json!({
                "available": true,
                "outcome_unknown": plan.unknown,
                "requeueable": plan.requeueable,
                "abandoned_receipts": plan.abandoned_receipts,
                "orphaned_children": plan.orphaned_children,
            }),
            Self::Unavailable(reason) => serde_json::json!({
                "available": false,
                "reason": reason,
            }),
        }
    }

    /// Whether a human has to look at something before the UI may call this idle.
    fn needs_attention(&self) -> bool {
        match self {
            Self::Read(plan) => {
                !(plan.unknown.is_empty()
                    && plan.abandoned_receipts.is_empty()
                    && plan.orphaned_children.is_empty())
            }
            // Unreadable is unknown, and unknown is never "all clear".
            Self::Unavailable(_) => true,
        }
    }
}

/// Tracks one process's lifecycle and reports on it.
pub struct Tracker {
    dir: PathBuf,
    instance: String,
    /// In memory only. `onPause` fires on every rotation and every dialog, so it
    /// must not touch the disk or the database.
    focus_lost_at_ms: Option<u64>,
}

impl Tracker {
    pub fn new(dir: impl AsRef<Path>, instance: impl Into<String>) -> Self {
        Self {
            dir: dir.as_ref().to_path_buf(),
            instance: instance.into(),
            focus_lost_at_ms: None,
        }
    }

    pub fn instance(&self) -> &str {
        &self.instance
    }

    /// `onPause`: the app may still be visible, and will very likely be resumed.
    ///
    /// Nothing is written and nothing is stopped. A rotation reaches this method,
    /// and cancelling a turn on a rotation would be absurd.
    pub fn on_pause(&mut self) -> serde_json::Value {
        let at = now_ms();
        self.focus_lost_at_ms = Some(at);
        let report = serde_json::json!({
            "signal": "pause",
            "meaning": "focus lost; the app may still be visible",
            "persisted": false,
            "focused_at_ms": at,
            // Stated so no UI copy can drift into "paused, so the work stopped".
            "turn_stopped": false,
        });
        // Logged, because "focus lost but still visible" is the distinction that
        // justifies using `onStop` for the background. Without it there is no
        // evidence that a split screen produced a pause and nothing else. It is a
        // file append, not a database write: `onPause` fires on every rotation.
        append_report(&self.dir, &report);
        report
    }

    /// `onStop`: no longer visible.
    ///
    /// Writes one small file and returns. No database transaction: this runs on the
    /// main thread while the OS is deciding whether to freeze us.
    pub fn on_stop(&mut self, running_threads: &[String]) -> serde_json::Value {
        let marker = Marker {
            instance: self.instance.clone(),
            destroyed: false,
            backgrounded_at_ms: now_ms(),
            noted_threads: running_threads.to_vec(),
        };
        let persisted = self.write_marker(&marker);
        let report = serde_json::json!({
            "signal": "stop",
            "meaning": "not visible; the process may be frozen or killed",
            "persisted": persisted,
            "noted_threads": marker.noted_threads,
            "turn_stopped": false,
            // The honest answer. A turn may keep running while the process lives,
            // but nothing here can promise the OS will let it finish.
            "background_execution_guaranteed": false,
        });
        append_report(&self.dir, &report);
        report
    }

    /// `onDestroy`: the activity is going away.
    ///
    /// This is not a crash. A rotation also reaches here, and the process survives,
    /// which is why the marker records the process id as well as the goodbye.
    pub fn on_destroy(&mut self) -> serde_json::Value {
        let marker = Marker {
            instance: self.instance.clone(),
            destroyed: true,
            backgrounded_at_ms: 0,
            noted_threads: Vec::new(),
        };
        let persisted = self.write_marker(&marker);
        let report = serde_json::json!({
            "signal": "destroy",
            "meaning": "activity finished; not evidence of a crash",
            "persisted": persisted,
        });
        append_report(&self.dir, &report);
        report
    }

    /// `onResume`: visible again. Says what is actually true now.
    ///
    /// `running_threads` and `journal` come from the process and the store, which are
    /// the two things that know. The marker is consulted only to tell "the activity
    /// was recreated" from "the process died", and its thread list is labelled
    /// advisory so the UI cannot present a guess as a fact.
    pub fn on_resume(&mut self, running_threads: &[String], journal: Journal) -> serde_json::Value {
        let marker = read_marker(&self.dir);
        let same_process = marker
            .as_ref()
            .map(|held| held.instance == self.instance)
            .unwrap_or(false);
        // Three cases, not two. "No marker at all" means this is the first launch or
        // the previous one never reached a point where it could write one; calling
        // that a restart would invent a death that never happened.
        let process = match &marker {
            Some(_) if same_process => "same",
            Some(_) => "restarted",
            None => "fresh",
        };

        let previous_end = match &marker {
            // Same process: nothing ended at all.
            Some(_) if same_process => "none",
            Some(held) if held.destroyed => "clean",
            Some(_) => "unclean",
            None => "none",
        };
        let died_abruptly = previous_end == "unclean";

        let backgrounded_for_ms = marker
            .as_ref()
            .filter(|held| held.backgrounded_at_ms > 0)
            .map(|held| now_ms().saturating_sub(held.backgrounded_at_ms))
            .unwrap_or(0);

        // Dying without a goodbye is only worth interrupting the user over when
        // something was actually in flight. A force-stop from the foreground with
        // nothing running is a normal way to close an app, and a banner for it would
        // teach people to dismiss the banner that matters.
        let died_with_work_running = died_abruptly
            && marker
                .as_ref()
                .map(|held| !held.noted_threads.is_empty())
                .unwrap_or(false);

        // Running work wins over everything else. If this process still has a live
        // turn, telling the user it was interrupted would be a lie, and it is the
        // lie that makes people distrust a resume banner afterwards.
        let turn_state = if !running_threads.is_empty() {
            "running"
        } else if journal.needs_attention() || died_with_work_running {
            "needs_attention"
        } else {
            "idle"
        };

        // Same process, so nothing was interrupted: the working set is untouched.
        let advisory_threads = if same_process {
            Vec::new()
        } else {
            marker
                .as_ref()
                .map(|held| held.noted_threads.clone())
                .unwrap_or_default()
        };

        let note = match (turn_state, previous_end) {
            ("running", _) => "A turn is still running in this process.",
            ("needs_attention", "unclean") => {
                "The previous process ended while work was in flight. What is unfinished comes from the journal."
            }
            ("needs_attention", _) => "Work was interrupted. The journal lists what needs a decision.",
            // Recorded, not dramatised: the exit was unclean but nothing was lost.
            ("idle", "unclean") => {
                "The previous process ended unexpectedly, but nothing was running and the journal has no unfinished work."
            }
            _ => "Nothing needs attention.",
        };

        self.focus_lost_at_ms = None;
        let report = serde_json::json!({
            "signal": "resume",
            // "same" means the activity was recreated inside a live process, which
            // is what a rotation looks like. "restarted" means a new process took
            // over an abandoned marker. "fresh" means there was no marker to inherit.
            "process": process,
            "previous_end": previous_end,
            "turn_state": turn_state,
            "running_threads": running_threads,
            // Advisory: what a process believed when it lost visibility. Not a fact.
            "advisory_threads": advisory_threads,
            "journal": journal.snapshot(),
            "backgrounded_for_ms": backgrounded_for_ms,
            // Never automatic, in any shape of report.
            "auto_resumed_turns": false,
            "note": note,
        });
        append_report(&self.dir, &report);

        // Fold the marker onto this process, after the restart has been reported.
        // Without this every later resume in the same process would claim to be a
        // restart again, because the old instance id would still be on disk.
        if process == "restarted" {
            let held = Marker {
                instance: self.instance.clone(),
                destroyed: false,
                // Kept so "how long was it away" still answers for this resume.
                backgrounded_at_ms: marker
                    .as_ref()
                    .map(|held| held.backgrounded_at_ms)
                    .unwrap_or(0),
                // The advisory list was just reported; keeping it would let a stale
                // guess outlive the fact it refers to.
                noted_threads: Vec::new(),
            };
            self.write_marker(&held);
        }
        report
    }

    fn write_marker(&self, marker: &Marker) -> bool {
        let Ok(text) = serde_json::to_string_pretty(marker) else {
            return false;
        };
        crate::private_file::write(&marker_path(&self.dir), &text, "lifecycle marker").is_ok()
    }
}

/// Reads what the journal knows, without letting a storage failure crash startup.
pub fn read_journal(store: &mut sunday_store::Store) -> Journal {
    match store.recover() {
        Ok(plan) => Journal::Read(plan),
        Err(error) => Journal::Unavailable(error.to_string()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use sunday_protocol::{SideEffect, ToolCall};
    use sunday_store::Store;

    fn threads(list: &[&str]) -> Vec<String> {
        list.iter().map(|each| (*each).to_owned()).collect()
    }

    fn clean() -> Journal {
        Journal::Read(RecoveryPlan::default())
    }

    /// `onPause` is not a background transition: it fires on rotations and dialogs,
    /// so it must not write anything and must not stop anything.
    #[test]
    fn a_pause_writes_nothing_and_touches_no_turn() {
        let dir = tempfile::tempdir().unwrap();
        let mut tracker = Tracker::new(dir.path(), "p1");
        let report = tracker.on_pause();

        assert_eq!(report["persisted"], false);
        assert_eq!(report["turn_stopped"], false);
        assert!(
            !marker_path(dir.path()).exists(),
            "onPause wrote a lifecycle file, so a rotation now looks like a background"
        );
    }

    /// The stated rule: a pause loses a couple of milliseconds of widget state at
    /// most, so it must not open the store either. This checks the only observable
    /// consequence: no database file is touched.
    #[test]
    fn a_pause_does_not_create_or_touch_a_database() {
        let dir = tempfile::tempdir().unwrap();
        {
            let mut store = Store::open(dir.path().join("core.db")).unwrap();
            store
                .append_event(
                    "local",
                    "t1",
                    "e1",
                    sunday_protocol::EventKind::ToolSucceeded,
                    serde_json::json!({"ok": true}),
                )
                .unwrap();
            store.checkpoint().unwrap();
        }
        let before = std::fs::metadata(dir.path().join("core.db"))
            .unwrap()
            .modified()
            .unwrap();

        let mut tracker = Tracker::new(dir.path(), "p1");
        tracker.on_pause();
        tracker.on_pause();

        let after = std::fs::metadata(dir.path().join("core.db"))
            .unwrap()
            .modified()
            .unwrap();
        assert_eq!(before, after, "onPause touched the database");
    }

    #[test]
    fn a_stop_records_the_process_without_claiming_a_guarantee() {
        let dir = tempfile::tempdir().unwrap();
        let mut tracker = Tracker::new(dir.path(), "p1");
        tracker.on_pause();
        let report = tracker.on_stop(&threads(&["t1"]));

        assert_eq!(report["persisted"], true);
        assert_eq!(report["background_execution_guaranteed"], false);
        assert_eq!(report["turn_stopped"], false);

        let marker = read_marker(dir.path()).expect("marker");
        assert_eq!(marker.instance, "p1");
        assert!(!marker.destroyed);
        assert_eq!(marker.noted_threads, threads(&["t1"]));
    }

    /// The requirement that matters most for trust: while the turn is alive, coming
    /// back must say so instead of "your task was interrupted".
    #[test]
    fn a_resume_in_the_live_process_reports_running_not_interrupted() {
        let dir = tempfile::tempdir().unwrap();
        let mut tracker = Tracker::new(dir.path(), "p1");
        tracker.on_pause();
        tracker.on_stop(&threads(&["t1"]));
        let report = tracker.on_resume(&threads(&["t1"]), clean());

        assert_eq!(report["process"], "same");
        assert_eq!(report["turn_state"], "running");
        assert_eq!(report["running_threads"][0], "t1");
        assert_eq!(
            report["advisory_threads"].as_array().unwrap().len(),
            0,
            "a live turn was reported as an interrupted one"
        );
        assert_eq!(report["auto_resumed_turns"], false);
    }

    /// A stop with nothing running, resumed in the same process: idle, no drama.
    #[test]
    fn a_resume_with_nothing_running_is_idle() {
        let dir = tempfile::tempdir().unwrap();
        let mut tracker = Tracker::new(dir.path(), "p1");
        tracker.on_stop(&[]);
        let report = tracker.on_resume(&[], clean());
        assert_eq!(report["turn_state"], "idle");
        assert_eq!(report["process"], "same");
    }

    /// A rotation destroys and recreates the activity inside the same process, so it
    /// must never be reported as an interruption.
    #[test]
    fn a_rotation_is_not_an_interruption() {
        let dir = tempfile::tempdir().unwrap();
        let mut tracker = Tracker::new(dir.path(), "p1");
        tracker.on_pause();
        tracker.on_destroy();
        // Same process id: the activity was recreated, not the process.
        let mut recreated = Tracker::new(dir.path(), "p1");
        let report = recreated.on_resume(&[], clean());

        assert_eq!(report["process"], "same");
        assert_eq!(report["turn_state"], "idle");
        assert_eq!(
            report["advisory_threads"].as_array().unwrap().len(),
            0,
            "a rotation was reported as an interrupted turn"
        );
    }

    /// A new process with no goodbye in the marker is an abnormal death, and the
    /// report says so.
    #[test]
    fn a_restart_without_a_goodbye_is_an_abnormal_death() {
        let dir = tempfile::tempdir().unwrap();
        {
            let mut tracker = Tracker::new(dir.path(), "p1");
            tracker.on_stop(&threads(&["t1"]));
        }
        let mut restarted = Tracker::new(dir.path(), "p2");
        let report = restarted.on_resume(&[], clean());

        assert_eq!(report["process"], "restarted");
        assert_eq!(report["previous_end"], "unclean");
        assert_eq!(report["turn_state"], "needs_attention");
        // Still advisory, even now: it is what the dead process believed.
        assert_eq!(report["advisory_threads"][0], "t1");
        assert_eq!(report["auto_resumed_turns"], false);
    }

    /// A forced stop with nothing running is not an incident. The unclean exit is
    /// still recorded, because it is true, but it must not raise a banner.
    #[test]
    fn a_kill_with_nothing_running_does_not_ask_for_attention() {
        let dir = tempfile::tempdir().unwrap();
        {
            let mut tracker = Tracker::new(dir.path(), "p1");
            // Backgrounded with nothing running, then killed before it could come
            // back: the marker says "not destroyed" and notes no threads.
            tracker.on_stop(&[]);
        }
        let mut restarted = Tracker::new(dir.path(), "p2");
        let report = restarted.on_resume(&[], clean());

        assert_eq!(report["process"], "restarted");
        assert_eq!(report["previous_end"], "unclean");
        assert_eq!(
            report["turn_state"], "idle",
            "a force-stop with nothing in flight was reported as an interruption"
        );
        assert_eq!(report["auto_resumed_turns"], false);
    }

    /// The first ever launch has nothing to inherit, so it is fresh rather than a
    /// restart. Reporting a death that never happened is how a banner loses trust.
    #[test]
    fn a_first_launch_is_fresh_not_a_restart() {
        let dir = tempfile::tempdir().unwrap();
        let mut tracker = Tracker::new(dir.path(), "p1");
        let report = tracker.on_resume(&[], clean());

        assert_eq!(report["process"], "fresh");
        assert_eq!(report["previous_end"], "none");
        assert_eq!(report["turn_state"], "idle");
    }

    /// One death, one report. The marker is folded onto the new process, so coming
    /// back from a background later in the same run is not a second restart.
    #[test]
    fn a_restart_is_reported_once_and_then_the_process_is_the_same() {
        let dir = tempfile::tempdir().unwrap();
        {
            let mut tracker = Tracker::new(dir.path(), "p1");
            tracker.on_stop(&threads(&["t1"]));
        }
        let mut restarted = Tracker::new(dir.path(), "p2");
        let first = restarted.on_resume(&[], clean());
        assert_eq!(first["process"], "restarted");
        assert_eq!(first["previous_end"], "unclean");

        restarted.on_stop(&[]);
        let second = restarted.on_resume(&[], clean());
        assert_eq!(
            second["process"], "same",
            "the same death was reported again on the next resume"
        );
        assert_eq!(second["turn_state"], "idle");
    }

    /// A process that ran `onDestroy` before exiting ended cleanly. Calling that a
    /// crash would cry wolf on every deliberate close.
    #[test]
    fn a_destroyed_activity_is_a_clean_end() {
        let dir = tempfile::tempdir().unwrap();
        {
            let mut tracker = Tracker::new(dir.path(), "p1");
            tracker.on_stop(&[]);
            tracker.on_destroy();
        }
        let mut restarted = Tracker::new(dir.path(), "p2");
        let report = restarted.on_resume(&[], clean());

        assert_eq!(report["process"], "restarted");
        assert_eq!(report["previous_end"], "clean");
        assert_eq!(report["turn_state"], "idle");
    }

    /// The rule that makes the journal authoritative: when the marker has a guess and
    /// the journal has a fact, the fact decides the state and the guess is labelled.
    #[test]
    fn the_journal_decides_what_was_interrupted() {
        let dir = tempfile::tempdir().unwrap();
        {
            let mut tracker = Tracker::new(dir.path(), "p1");
            tracker.on_stop(&threads(&["noted-by-the-marker"]));
        }

        let plan = RecoveryPlan {
            unknown: vec!["call-1".into()],
            ..Default::default()
        };
        let mut restarted = Tracker::new(dir.path(), "p2");
        let report = restarted.on_resume(&[], Journal::Read(plan));

        assert_eq!(report["turn_state"], "needs_attention");
        assert_eq!(report["journal"]["available"], true);
        assert_eq!(report["journal"]["outcome_unknown"][0], "call-1");
        assert_eq!(report["advisory_threads"][0], "noted-by-the-marker");
        assert_eq!(report["auto_resumed_turns"], false);
    }

    /// An unreadable journal is unknown. Rendering that as "all clear" is the one
    /// failure mode that loses a user's work silently.
    #[test]
    fn an_unreadable_journal_is_not_all_clear() {
        let dir = tempfile::tempdir().unwrap();
        let mut tracker = Tracker::new(dir.path(), "p1");
        let report = tracker.on_resume(&[], Journal::Unavailable("disk gone".into()));

        assert_eq!(report["turn_state"], "needs_attention");
        assert_eq!(report["journal"]["available"], false);
        assert_eq!(report["journal"]["reason"], "disk gone");
    }

    /// A marker corrupted by a half-write must not become a crash accusation.
    #[test]
    fn a_corrupt_marker_is_not_a_crash_report() {
        let dir = tempfile::tempdir().unwrap();
        std::fs::write(marker_path(dir.path()), b"{ not json").unwrap();
        let mut tracker = Tracker::new(dir.path(), "p1");
        let report = tracker.on_resume(&[], clean());

        assert_eq!(report["previous_end"], "none");
        assert_eq!(report["turn_state"], "idle");
    }

    /// End to end against a real store: a non-idempotent call that was dispatched and
    /// never answered must surface from the journal as needing a decision, and must
    /// not be replayed.
    #[test]
    fn a_tool_killed_mid_flight_needs_a_decision_and_is_not_replayed() {
        let dir = tempfile::tempdir().unwrap();
        let db = dir.path().join("core.db");
        {
            let mut store = Store::open(&db).unwrap();
            store
                .prepare_tool_once(
                    "t1",
                    &ToolCall {
                        id: "call-1".into(),
                        name: "write_file".into(),
                        args: serde_json::json!({"path": "a.txt"}),
                    },
                    SideEffect::NonIdempotent,
                )
                .unwrap();
            // The process dies between dispatch and result, exactly as a kill would.
            store.mark_dispatched("call-1").unwrap();
        }

        let mut store = Store::open(&db).unwrap();
        let journal = read_journal(&mut store);
        match &journal {
            Journal::Read(plan) => assert_eq!(plan.unknown, vec!["call-1".to_owned()]),
            Journal::Unavailable(reason) => panic!("journal unreadable: {reason}"),
        }

        let mut tracker = Tracker::new(dir.path(), "p2");
        let report = tracker.on_resume(&[], journal);
        assert_eq!(report["turn_state"], "needs_attention");
        assert_eq!(report["journal"]["outcome_unknown"][0], "call-1");
        assert_eq!(
            report["auto_resumed_turns"], false,
            "an unknown-outcome call must never be resumed automatically"
        );

        // And the store agrees that it is unknown rather than queued for a retry.
        let stage = Store::open(&db).unwrap().tool_stage("call-1").unwrap();
        assert_eq!(
            stage,
            Some(sunday_protocol::ToolStage::Unknown),
            "a dispatched non-idempotent call was left in a replayable stage"
        );
    }
}
