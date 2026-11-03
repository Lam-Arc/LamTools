//! WAL checkpoint behaviour, measured before anything is changed.
//!
//! The instruction was explicit: measure the default auto-checkpoint's latency
//! first, then decide whether a separate background checkpoint is worth adding.
//! Four things this file learned the hard way, written down because each one
//! produces a confidently wrong answer if missed:
//!
//! 1. **Calling `PASSIVE` on the writer's own connection is not a background
//!    checkpoint.** It serialises with the commit. That shape made p99 worse.
//! 2. **WAL file size is the wrong metric for whether `PASSIVE` worked.** It never
//!    truncates, so the file stays at its high-water mark. What moves is the frame
//!    count, which is why `WalHealth` reports both.
//! 3. **`busy` from `PRAGMA wal_checkpoint(PASSIVE)` is always 0.** SQLite only
//!    raises it for RESTART/FULL/TRUNCATE, because PASSIVE gives up instead of
//!    waiting. Starvation has to be read as "frames in the log versus frames
//!    backfilled".
//! 4. **p99 cannot see a rare event.** A checkpoint every 1000 pages over 4000
//!    sends happens ~29 times, which lands beyond p99. Reporting p99 alone would
//!    claim "no spike" no matter how expensive the checkpoint was, so max and p99.9
//!    are reported too, along with the count of commits slower than 3x the median.

use std::path::{Path, PathBuf};
use std::sync::atomic::AtomicBool;
use std::sync::Arc;
use std::time::{Duration, Instant};

use sunday_protocol::EventKind;
use sunday_store::Store;

fn payload(size: usize) -> String {
    const UNIT: &str = "the quick brown fox jumps over the lazy dog 0123456789 ";
    let mut out = String::with_capacity(size + UNIT.len());
    while out.len() < size {
        out.push_str(UNIT);
    }
    out.truncate(size);
    out
}

fn wal_path(db: &Path) -> PathBuf {
    PathBuf::from(format!("{}-wal", db.display()))
}

fn wal_bytes(db: &Path) -> u64 {
    std::fs::metadata(wal_path(db))
        .map(|meta| meta.len())
        .unwrap_or(0)
}

fn append(store: &mut Store, thread: &str, index: usize, body: &str) {
    store
        .append_event(
            "local",
            thread,
            &format!("{thread}:{index}"),
            EventKind::ToolSucceeded,
            serde_json::json!({"index": index, "content": body}),
        )
        .expect("append");
}

/// Percentiles over one sample per commit, plus the numbers that actually expose a
/// rare checkpoint.
struct Stats {
    samples: usize,
    p50: Duration,
    p95: Duration,
    p99: Duration,
    p999: Duration,
    max: Duration,
    total: Duration,
    /// Commits slower than 3x the median: how often a user would feel it.
    slow: usize,
    wal_high: u64,
}

impl Stats {
    fn new(mut samples: Vec<Duration>, total: Duration, wal_high: u64) -> Self {
        samples.sort();
        let count = samples.len();
        let at = |percent: usize| {
            let index = (count * percent / 100).saturating_sub(1).min(count - 1);
            samples[index]
        };
        let p50 = at(50);
        let slow = samples.iter().filter(|each| **each > p50 * 3).count();
        Self {
            samples: count,
            p50,
            p95: at(95),
            p99: at(99),
            p999: at(999),
            max: *samples.last().expect("at least one sample"),
            total,
            slow,
            wal_high,
        }
    }

    fn print(&self, label: &str) {
        println!(
            "  {label:<34} p50 {:>7.3}ms  p95 {:>7.3}ms  p99 {:>7.3}ms  p99.9 {:>7.3}ms  max {:>8.3}ms",
            self.p50.as_secs_f64() * 1e3,
            self.p95.as_secs_f64() * 1e3,
            self.p99.as_secs_f64() * 1e3,
            self.p999.as_secs_f64() * 1e3,
            self.max.as_secs_f64() * 1e3,
        );
        println!(
            "  {:<34} total {:>7.2}s  ({:.0} us/commit)  WAL high-water {} KB  commits >3x median: {}",
            "",
            self.total.as_secs_f64(),
            self.total.as_secs_f64() * 1e6 / self.samples as f64,
            self.wal_high / 1024,
            self.slow,
        );
    }
}

/// How the writer is configured for one arm of the comparison.
struct Shape {
    /// `None` leaves SQLite's default of 1000 pages alone.
    autocheckpoint: Option<u32>,
    /// `Some(interval)` runs PASSIVE on a **separate connection** on its own thread.
    background: Option<Duration>,
}

const DEFAULT_SHAPE: Shape = Shape {
    autocheckpoint: None,
    background: None,
};

/// Writes `samples` messages, each `commits` commits, and times the message rather
/// than the commit: a slow commit is only interesting if a send feels it.
fn measure(samples: usize, commits: usize, body: &str, shape: &Shape, thread: &str) -> Stats {
    let dir = tempfile::tempdir().expect("tempdir");
    let db = dir.path().join("core.db");
    let mut store = Store::open(&db).expect("open");

    // Warm the file and the OS page cache, then start from a folded log so the
    // first arm does not pay for first-touch costs the second arm never sees.
    for index in 0..50 {
        append(&mut store, thread, index, body);
    }
    store.checkpoint().expect("checkpoint");

    let stop = Arc::new(AtomicBool::new(false));
    let maintenance = shape.background.map(|interval| {
        // The maintenance connection is opened *before* timing so its migration
        // check cannot land in the middle of a measured sample.
        let other = Store::open(&db).expect("second connection");
        let stop = Arc::clone(&stop);
        std::thread::spawn(move || {
            let mut passes = 0u64;
            while !stop.load(std::sync::atomic::Ordering::SeqCst) {
                if other.checkpoint_passive().is_ok() {
                    passes += 1;
                }
                std::thread::sleep(interval);
            }
            passes
        })
    });
    if let Some(pages) = shape.autocheckpoint {
        store.raise_autocheckpoint(pages).expect("raise");
    }

    let mut samples_taken = Vec::with_capacity(samples);
    let mut wal_high = 0u64;
    let started = Instant::now();
    for sample in 0..samples {
        let each = Instant::now();
        for offset in 0..commits {
            append(&mut store, thread, sample * commits + offset, body);
        }
        samples_taken.push(each.elapsed());
        wal_high = wal_high.max(wal_bytes(&db));
    }
    let total = started.elapsed();

    stop.store(true, std::sync::atomic::Ordering::SeqCst);
    if let Some(handle) = maintenance {
        let passes = handle.join().unwrap_or(0);
        println!("  maintenance: {passes} PASSIVE passes on its own connection");
    }

    Stats::new(samples_taken, total, wal_high)
}

/// The measurement the decision rests on: default auto-checkpoint versus a raised
/// threshold plus a separate-connection PASSIVE thread, at three payload sizes.
///
/// Reported, not asserted: this test exists to produce numbers for a human to read,
/// and a threshold baked into an `assert!` would be a number invented after the
/// fact rather than one measured.
#[test]
#[ignore = "measurement; run with --ignored --nocapture --release"]
fn default_autocheckpoint_versus_background_thread() {
    // 512 B is a chat message, 8 KB a tool result, 64 KB a large file read.
    for size in [512usize, 8 * 1024, 64 * 1024] {
        let body = payload(size);
        // Three commits per message, which is what one turn actually writes: the
        // user's message, the tool event, the assistant's reply.
        let commits = 3;
        let samples = if size > 32 * 1024 { 500 } else { 1500 };

        println!(
            "\n=== payload {} KB, {} messages x {} commits ===",
            size / 1024,
            samples,
            commits
        );
        let baseline = measure(samples, commits, &body, &DEFAULT_SHAPE, "default");
        baseline.print("default (1000-page auto)");

        let tuned = measure(
            samples,
            commits,
            &body,
            &Shape {
                autocheckpoint: Some(4000),
                background: Some(Duration::from_millis(50)),
            },
            "tuned",
        );
        tuned.print("raised 4000 + background PASSIVE");

        println!(
            "  delta: p99 {:+.3}ms  p99.9 {:+.3}ms  max {:+.3}ms  WAL {:+.1}%",
            (tuned.p99.as_secs_f64() - baseline.p99.as_secs_f64()) * 1e3,
            (tuned.p999.as_secs_f64() - baseline.p999.as_secs_f64()) * 1e3,
            (tuned.max.as_secs_f64() - baseline.max.as_secs_f64()) * 1e3,
            (tuned.wal_high as f64 / baseline.wal_high.max(1) as f64 - 1.0) * 100.0,
        );
    }
}

/// The amplitude of the event that the distributions above can only hint at: what
/// one checkpoint actually costs when the log is full.
#[test]
#[ignore = "measurement; run with --ignored --nocapture --release"]
fn a_single_checkpoint_at_the_default_threshold_costs_this_much() {
    let dir = tempfile::tempdir().expect("tempdir");
    let db = dir.path().join("core.db");
    let mut store = Store::open(&db).expect("open");
    // Disable the automatic checkpoint so the log can reach the default threshold
    // intact instead of being folded away before it can be timed.
    store.raise_autocheckpoint(0).expect("disable auto");

    let body = payload(8 * 1024);
    let mut index = 0usize;

    // Calibrate: how many commits it takes to put 1000 frames in the log. With the
    // automatic checkpoint off and a fresh file, the file size is an honest count of
    // frames written so far, which it stops being the moment anything folds back.
    let mut per_round = 0usize;
    while wal_bytes(&db) < 1000 * 4096 {
        append(&mut store, "amplitude", index, &body);
        index += 1;
        per_round += 1;
    }
    println!(
        "  {per_round} commits fill 1000 frames ({} KB)",
        wal_bytes(&db) / 1024
    );

    // PASSIVE is what the auto-checkpoint runs, and what a background thread would
    // run, so this is the number either design has to pay per checkpoint. Refilling
    // by commit count means every round has a genuinely full log to fold back.
    let mut timings = Vec::new();
    for round in 0..6 {
        for _ in 0..per_round {
            append(&mut store, "amplitude", index, &body);
            index += 1;
        }
        let each = Instant::now();
        store.checkpoint_passive().expect("passive");
        let elapsed = each.elapsed();
        println!(
            "  round {round}: PASSIVE over ~1000 frames took {:.3}ms",
            elapsed.as_secs_f64() * 1e3
        );
        timings.push(elapsed);
    }

    let mut sorted = timings.clone();
    sorted.sort();
    let median = sorted[sorted.len() / 2];
    println!(
        "  one PASSIVE over ~1000 frames: min {:.3}ms  median {:.3}ms  max {:.3}ms",
        sorted[0].as_secs_f64() * 1e3,
        median.as_secs_f64() * 1e3,
        sorted[sorted.len() - 1].as_secs_f64() * 1e3,
    );
    assert!(
        median < Duration::from_millis(250),
        "a checkpoint of a 4 MB log took longer than any send could hide"
    );
}

/// Starvation: a reader holding a snapshot stops PASSIVE from making progress, and
/// `wal_health` has to say so instead of reporting a healthy WAL that keeps growing.
#[test]
#[ignore = "measurement; run with --ignored --nocapture"]
fn a_long_reader_starves_the_checkpoint_and_health_says_so() {
    let dir = tempfile::tempdir().expect("tempdir");
    let db = dir.path().join("core.db");
    let mut store = Store::open(&db).expect("open");
    for index in 0..50 {
        append(
            &mut store,
            "starve",
            index,
            "a tool result of ordinary size",
        );
    }

    // A snapshot that stays open across the writes. This is the shape of a slow
    // UI read or a paused process that still holds its connection.
    let reader = rusqlite::Connection::open(&db).expect("reader");
    reader
        .execute_batch("BEGIN; SELECT COUNT(*) FROM journal_events;")
        .expect("begin read");

    for index in 50..300 {
        append(
            &mut store,
            "starve",
            index,
            "a tool result of ordinary size",
        );
    }

    let starved = store.wal_health().expect("health");
    println!(
        "  with the reader open: {} frames, {} backfilled, file {} KB, starved {}",
        starved.log_pages,
        starved.checkpointed_pages,
        starved.file_bytes / 1024,
        starved.starved
    );
    assert!(
        starved.starved,
        "a held read snapshot must be reported as starvation, not as a healthy log"
    );

    reader.execute_batch("COMMIT;").expect("commit read");
    drop(reader);

    let recovered = store.wal_health().expect("health");
    println!(
        "  after the reader closed: {} frames, {} backfilled, starved {}",
        recovered.log_pages, recovered.checkpointed_pages, recovered.starved
    );
    assert!(
        !recovered.starved,
        "the checkpoint must resume once the reader lets go"
    );
    assert!(
        recovered.checkpointed_pages > starved.checkpointed_pages,
        "closing the reader did not let the checkpoint make progress"
    );
}

/// A healthy log with no reader must fold back and then truncate, and the report
/// has to show real progress rather than a size that never moves.
#[test]
#[ignore = "measurement; run with --ignored --nocapture"]
fn wal_health_reports_progress_not_just_a_size() {
    let dir = tempfile::tempdir().expect("tempdir");
    let db = dir.path().join("core.db");
    let mut store = Store::open(&db).expect("open");

    for index in 0..400 {
        append(
            &mut store,
            "health",
            index,
            "a tool result of ordinary size",
        );
    }
    let health = store.wal_health().expect("health");
    println!(
        "before: {} frames ({} KB), file {} KB, starved {}",
        health.log_pages,
        health.frames_bytes / 1024,
        health.file_bytes / 1024,
        health.starved
    );
    assert!(
        !health.starved,
        "PASSIVE could not make progress with no reader holding pages"
    );
    assert!(health.checkpointed_pages > 0, "no pages were checkpointed");

    store.checkpoint().expect("truncate");
    let after = store.wal_health().expect("health");
    println!(
        "after TRUNCATE: {} frames ({} KB), file {} KB",
        after.log_pages,
        after.frames_bytes / 1024,
        after.file_bytes / 1024
    );
    assert!(
        after.log_pages < health.log_pages,
        "TRUNCATE left the log full"
    );
    assert!(
        after.file_bytes < health.file_bytes,
        "TRUNCATE did not shrink the file, so the size metric is meaningless"
    );
}

/// Durability must not change: committed events survive an unclean drop with a
/// background checkpoint running throughout.
#[test]
#[ignore = "measurement; run with --ignored --nocapture"]
fn a_background_checkpoint_does_not_weaken_durability() {
    const COMMITTED: usize = 500;
    let dir = tempfile::tempdir().expect("tempdir");
    let db = dir.path().join("core.db");
    {
        let mut store = Store::open(&db).expect("open");
        store.raise_autocheckpoint(4000).expect("raise");
        let stop = Arc::new(AtomicBool::new(false));
        let maintenance = {
            let other = Store::open(&db).expect("second connection");
            let stop = Arc::clone(&stop);
            std::thread::spawn(move || {
                while !stop.load(std::sync::atomic::Ordering::SeqCst) {
                    let _ = other.checkpoint_passive();
                    std::thread::sleep(Duration::from_millis(20));
                }
            })
        };
        for index in 0..COMMITTED {
            append(&mut store, "durable", index, "x");
        }
        stop.store(true, std::sync::atomic::Ordering::SeqCst);
        maintenance.join().expect("maintenance thread");
        // Deliberately no clean shutdown, like a killed process.
    }
    let store = Store::open(&db).expect("reopen");
    let events = store.events("durable", 0).expect("events");
    assert_eq!(
        events.len(),
        COMMITTED,
        "a committed write was lost with a background checkpoint active"
    );
    assert_eq!(
        events.iter().map(|event| event.seq).collect::<Vec<_>>(),
        (1..=COMMITTED as u64).collect::<Vec<_>>(),
        "the journal has a hole, so ordering did not survive"
    );
}
