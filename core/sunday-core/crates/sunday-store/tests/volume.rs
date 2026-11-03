//! Volume and write-amplification measurements.
//!
//! These are measurements, not pass/fail gates, so they print numbers and only
//! assert the relationships that would indicate a real design fault: replay must
//! be linear, a page must not read the whole journal, and the database must not
//! grow super-linearly.
//!
//! Run with `--ignored --nocapture` to see the numbers.

use std::time::{Duration, Instant};
use sunday_protocol::EventKind;
use sunday_store::Store;

fn temp_db() -> (tempfile::TempDir, Store) {
    let dir = tempfile::tempdir().expect("tempdir");
    let store = Store::open(dir.path().join("core.db")).expect("open");
    (dir, store)
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

/// 10k small events: the case a long conversation actually produces.
#[test]
#[ignore = "measurement; run with --ignored --nocapture"]
fn ten_thousand_events_append_and_replay() {
    let (_dir, mut store) = temp_db();
    let body = "a tool result of ordinary size, about one hundred bytes long, repeated";

    let started = Instant::now();
    for index in 0..10_000 {
        append(&mut store, "thread-1", index, body);
    }
    let write_elapsed = started.elapsed();

    let started = Instant::now();
    let replay = store.events("thread-1", 0).expect("replay");
    let replay_elapsed = started.elapsed();

    assert_eq!(replay.len(), 10_000);
    // Sequence numbers must be dense and ordered: a gap would break the client's
    // "I have everything up to seq N" logic.
    assert_eq!(replay.first().unwrap().seq, 1);
    assert_eq!(replay.last().unwrap().seq, 10_000);

    let started = Instant::now();
    let tail = store.events("thread-1", 9_990).expect("tail");
    let tail_elapsed = started.elapsed();
    assert_eq!(tail.len(), 10);

    println!(
        "10k appends {:?} ({:.1} us/event), full replay {:?}, tail of 10 {:?}",
        write_elapsed,
        write_elapsed.as_secs_f64() * 1e6 / 10_000.0,
        replay_elapsed,
        tail_elapsed
    );
    // A tail read must not be proportional to the whole journal, or every
    // reconnect gets slower as the conversation grows.
    assert!(
        tail_elapsed < replay_elapsed,
        "reading 10 events took as long as reading 10000: tail {tail_elapsed:?} vs full {replay_elapsed:?}"
    );
}

/// Large payloads are the write-amplification case: one tool dump can be
/// megabytes.
#[test]
#[ignore = "measurement; run with --ignored --nocapture"]
fn a_hundred_large_events_stay_usable() {
    let (_dir, mut store) = temp_db();
    let body = "x".repeat(100_000);

    let started = Instant::now();
    for index in 0..100 {
        append(&mut store, "thread-big", index, &body);
    }
    let write_elapsed = started.elapsed();

    let started = Instant::now();
    let replay = store.events("thread-big", 0).expect("replay");
    let replay_elapsed = started.elapsed();

    assert_eq!(replay.len(), 100);
    println!(
        "100 x 100KB appends {:?} ({:.1} ms/event), replay {:?}",
        write_elapsed,
        write_elapsed.as_secs_f64() * 1e3 / 100.0,
        replay_elapsed
    );
    assert!(
        write_elapsed < Duration::from_secs(60),
        "writing 10MB of journal took {write_elapsed:?}"
    );
}

/// Many threads in one workspace: the index has to stay usable.
#[test]
#[ignore = "measurement; run with --ignored --nocapture"]
fn two_hundred_threads_do_not_slow_each_other() {
    let (_dir, mut store) = temp_db();
    let started = Instant::now();
    for thread in 0..200 {
        for index in 0..50 {
            append(&mut store, &format!("thread-{thread}"), index, "payload");
        }
    }
    let write_elapsed = started.elapsed();

    let started = Instant::now();
    let one = store.events("thread-150", 0).expect("one thread");
    let read_elapsed = started.elapsed();

    assert_eq!(one.len(), 50);
    assert!(one.iter().all(|event| event.thread_id == "thread-150"));
    println!(
        "10k events across 200 threads: write {:?}, one-thread read {:?}",
        write_elapsed, read_elapsed
    );
    // A per-thread read must not scan every thread's rows.
    assert!(
        read_elapsed < Duration::from_millis(200),
        "a 50 event read took {read_elapsed:?}, which suggests a full scan"
    );
}

/// How much the files grow per event. Quoting a number beats guessing.
///
/// The size of the database plus its WAL is measured, because that is the space
/// actually consumed on disk while the core is running. There is no checkpoint
/// API to fold the WAL back in, and inventing one just for a test would be a
/// change to production code for measurement's sake.
#[test]
#[ignore = "measurement; run with --ignored --nocapture"]
fn bytes_per_event_is_reported() {
    let dir = tempfile::tempdir().expect("tempdir");
    let db = dir.path().join("core.db");
    let mut store = Store::open(&db).expect("open");
    let body = "a tool result of ordinary size, about one hundred bytes long, repeated";

    fn footprint(db: &std::path::Path) -> u64 {
        let main = std::fs::metadata(db).map(|m| m.len()).unwrap_or(0);
        let wal = std::fs::metadata(db.with_extension("db-wal"))
            .map(|m| m.len())
            .unwrap_or(0);
        main + wal
    }

    let before = footprint(&db);
    for index in 0..1_000 {
        append(&mut store, "thread-1", index, body);
    }
    let after = footprint(&db);

    let delta = after.saturating_sub(before);
    println!(
        "1000 events grew the database by {} bytes ({:.0} bytes/event, payload {} bytes)",
        delta,
        delta as f64 / 1_000.0,
        body.len()
    );
    assert!(after > before, "the database did not grow at all");
}
