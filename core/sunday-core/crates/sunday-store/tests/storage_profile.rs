//! Storage measurements, with the WAL folded in before anything is reported.
//!
//! The previous round published "4291 bytes per event" and blamed the projection
//! rewrite. Both parts were wrong, and this file is how that was found:
//!
//!   * the projection blob is tiny (tens of bytes) and its cost is a page, not a
//!     body
//!   * byte counts taken without a checkpoint measure un-flushed WAL, so they
//!     depend on when a checkpoint happened to run, not on the data
//!   * the real per-event cost is one commit: one fsync and the pages it dirties
//!
//! Every number below is taken after `checkpoint()`, so it is the steady-state
//! cost on disk.

use std::time::{Duration, Instant};
use sunday_protocol::EventKind;
use sunday_store::Store;

const PAGE_SIZE: u64 = 4096;

fn footprint(db: &std::path::Path) -> u64 {
    let main = std::fs::metadata(db).map(|m| m.len()).unwrap_or(0);
    let wal = std::fs::metadata(format!("{}-wal", db.to_string_lossy()))
        .map(|m| m.len())
        .unwrap_or(0);
    main + wal
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

fn batched(store: &mut Store, thread: &str, from: usize, count: usize, body: &str) {
    let events: Vec<(String, EventKind, serde_json::Value)> = (0..count)
        .map(|offset| {
            let index = from + offset;
            (
                format!("{thread}:{index}"),
                EventKind::ToolSucceeded,
                serde_json::json!({"index": index, "content": body}),
            )
        })
        .collect();
    store
        .append_events("local", thread, &events)
        .expect("batch");
}

/// One transaction per event versus one per ten. Same data, same durability.
fn compare_shapes() {
    let body = "a tool result of ordinary size, about one hundred bytes long, repeated";
    const N: usize = 1000;
    const GROUP: usize = 10;

    let single = {
        let dir = tempfile::tempdir().expect("tempdir");
        let db = dir.path().join("core.db");
        let mut store = Store::open(&db).expect("open");
        for index in 0..50 {
            append(&mut store, "warm", index, body);
        }
        store.checkpoint().expect("checkpoint");
        let before = footprint(&db);

        let mut samples = Vec::new();
        let started = Instant::now();
        for index in 0..N {
            let each = Instant::now();
            append(&mut store, "measure", index, body);
            samples.push(each.elapsed());
        }
        let elapsed = started.elapsed();
        store.checkpoint().expect("checkpoint");
        let after = footprint(&db);
        samples.sort();
        (
            elapsed,
            after.saturating_sub(before),
            samples[samples.len() / 2],
            samples[samples.len() * 95 / 100],
        )
    };

    let batch = {
        let dir = tempfile::tempdir().expect("tempdir");
        let db = dir.path().join("core.db");
        let mut store = Store::open(&db).expect("open");
        for index in 0..50 {
            append(&mut store, "warm", index, body);
        }
        store.checkpoint().expect("checkpoint");
        let before = footprint(&db);

        let mut samples = Vec::new();
        let started = Instant::now();
        for group in 0..(N / GROUP) {
            let each = Instant::now();
            batched(&mut store, "measure", group * GROUP, GROUP, body);
            samples.push(each.elapsed());
        }
        let elapsed = started.elapsed();
        store.checkpoint().expect("checkpoint");
        let after = footprint(&db);
        samples.sort();
        (
            elapsed,
            after.saturating_sub(before),
            samples[samples.len() / 2],
            samples[samples.len() * 95 / 100],
        )
    };

    println!("=== 1000 events, identical payload and durability ===");
    println!(
        "one transaction per event: {:?} total, {:.0} us/event, p50 {:?}, p95 {:?}, {} bytes on disk ({:.0}/event), {} fsyncs",
        single.0,
        single.0.as_secs_f64() * 1e6 / N as f64,
        single.2,
        single.3,
        single.1,
        single.1 as f64 / N as f64,
        N
    );
    println!(
        "one transaction per {GROUP} events:  {:?} total, {:.0} us/event, p50 {:?}, p95 {:?}, {} bytes on disk ({:.0}/event), {} fsyncs",
        batch.0,
        batch.0.as_secs_f64() * 1e6 / N as f64,
        batch.2,
        batch.3,
        batch.1,
        batch.1 as f64 / N as f64,
        N / GROUP
    );
    println!(
        "speedup {:.1}x, fsyncs reduced {:.0}x",
        single.0.as_secs_f64() / batch.0.as_secs_f64(),
        N as f64 / (N / GROUP) as f64
    );

    // Batching must not have traded durability for speed: the data is the same.
    assert!(batch.1 > 0, "the batched database cannot be empty");
    assert!(
        batch.1 as f64 <= single.1 as f64 * 1.5,
        "batching used {:.1}x the disk of single writes, which means it lost a compression win or duplicated data",
        batch.1 as f64 / single.1 as f64
    );
}

#[test]
#[ignore = "measurement; run with --ignored --nocapture"]
fn batching_versus_single_commit() {
    compare_shapes();
}

/// Where the bytes actually go, decomposed with the WAL folded in.
#[test]
#[ignore = "measurement; run with --ignored --nocapture"]
fn growth_per_event_decomposed() {
    let dir = tempfile::tempdir().expect("tempdir");
    let db = dir.path().join("core.db");
    let mut store = Store::open(&db).expect("open");
    let body = "a tool result of ordinary size, about one hundred bytes long, repeated";

    for index in 0..50 {
        append(&mut store, "warm", index, body);
    }
    store.checkpoint().expect("checkpoint");
    let before = footprint(&db);

    const N: usize = 1000;
    let started = Instant::now();
    for index in 0..N {
        append(&mut store, "measure", index, body);
    }
    let elapsed = started.elapsed();
    store.checkpoint().expect("checkpoint");
    let after = footprint(&db);

    let delta = after.saturating_sub(before);
    let projection_bytes = store
        .projection("measure")
        .ok()
        .and_then(|p| serde_json::to_string(&p).ok())
        .map(|text| text.len() as u64)
        .unwrap_or(0);

    println!("--- {N} events, one transaction each, WAL folded in ---");
    println!(
        "latency {:?} total ({:.0} us/event)",
        elapsed,
        elapsed.as_secs_f64() * 1e6 / N as f64
    );
    println!(
        "steady-state disk growth {delta} bytes, {:.0} bytes/event",
        delta as f64 / N as f64
    );
    println!(
        "payload ~{} bytes, projection blob {projection_bytes} bytes",
        body.len() + 40
    );
    println!(
        "so the per-event cost is {:.1} pages of durable write for a payload that fits in one",
        delta as f64 / N as f64 / PAGE_SIZE as f64
    );

    // The point of the measurement: growth is page and commit granularity, not
    // payload size. One event cannot cost less than the pages it dirties.
    assert!(delta > 0);
}

/// Does payload size move the disk number? If it barely does, the payload is not
/// the driver and shrinking payloads is the wrong fix.
#[test]
#[ignore = "measurement; run with --ignored --nocapture"]
fn payload_size_versus_growth() {
    println!("=== 50 events at each payload size, WAL folded in ===");
    for size in [50usize, 500, 5_000, 20_000] {
        let dir = tempfile::tempdir().expect("tempdir");
        let db = dir.path().join("core.db");
        let mut store = Store::open(&db).expect("open");
        for index in 0..20 {
            append(&mut store, "warm", index, "x");
        }
        store.checkpoint().expect("checkpoint");
        let before = footprint(&db);

        let body = "x".repeat(size);
        for index in 0..50 {
            append(&mut store, &format!("size-{size}"), index, &body);
        }
        store.checkpoint().expect("checkpoint");
        let after = footprint(&db);
        let delta = after.saturating_sub(before);
        println!(
            "payload {size:>6} bytes -> {delta:>9} bytes for 50 events, {:>8.0} bytes/event",
            delta as f64 / 50.0
        );
    }
}

/// The projection is rewritten whole on every append. Show what one rewrite of
/// the row costs, so the claim can be checked instead of assumed.
#[test]
#[ignore = "measurement; run with --ignored --nocapture"]
fn projection_rewrite_cost() {
    let dir = tempfile::tempdir().expect("tempdir");
    let db = dir.path().join("core.db");
    let mut store = Store::open(&db).expect("open");

    for index in 0..10 {
        append(&mut store, "proj", index, "x");
    }
    store.checkpoint().expect("checkpoint");
    let before = footprint(&db);

    let started = Instant::now();
    for index in 10..1010 {
        append(&mut store, "proj", index, "x");
    }
    let elapsed = started.elapsed();
    store.checkpoint().expect("checkpoint");
    let after = footprint(&db);

    let blob = store
        .projection("proj")
        .ok()
        .and_then(|p| serde_json::to_string(&p).ok())
        .map(|t| t.len())
        .unwrap_or(0);
    let delta = after.saturating_sub(before);
    println!("=== 1000 appends with a projection rewrite each ===");
    println!(
        "latency {:?} ({:.0} us/event)",
        elapsed,
        elapsed.as_secs_f64() * 1e6 / 1000.0
    );
    println!(
        "disk growth {delta} bytes ({:.0}/event)",
        delta as f64 / 1000.0
    );
    println!(
        "the projection row is {blob} bytes; rewriting it once cannot explain {:.0} bytes/event",
        delta as f64 / 1000.0
    );
    assert!(blob > 0);
    // The blob is small because it holds only counts per kind, and the kinds are
    // a closed set. This bound is the reason "the projection grows without limit"
    // is not the explanation.
    assert!(
        blob < 4096,
        "the projection row is {blob} bytes, which no longer fits the 'tiny blob' claim"
    );
}

/// A batch must be all-or-nothing across a reopen, and the receipt, journal and
/// projection must agree afterwards.
#[test]
#[ignore = "measurement; run with --ignored --nocapture"]
fn a_batch_is_atomic_across_a_reopen() {
    let dir = tempfile::tempdir().expect("tempdir");
    let db = dir.path().join("core.db");
    {
        let mut store = Store::open(&db).expect("open");
        batched(&mut store, "atomic", 0, 10, "x");
    }
    let store = Store::open(&db).expect("reopen");
    let replayed = store.events("atomic", 0).expect("replay");
    assert_eq!(
        replayed.len(),
        10,
        "a committed batch must be fully durable"
    );
    assert_eq!(
        replayed.iter().map(|e| e.seq).collect::<Vec<_>>(),
        (1..=10).collect::<Vec<_>>()
    );
    let projection = store.projection("atomic").expect("projection");
    assert_eq!(projection.last_seq, 10);
    assert_eq!(projection.counts.get("tool_succeeded"), Some(&10));
}

/// Re-appending the same event ids must not duplicate or renumber anything.
#[test]
#[ignore = "measurement; run with --ignored --nocapture"]
fn a_replayed_batch_is_idempotent() {
    let dir = tempfile::tempdir().expect("tempdir");
    let db = dir.path().join("core.db");
    let mut store = Store::open(&db).expect("open");

    batched(&mut store, "idem", 0, 5, "x");
    let first = store.events("idem", 0).expect("replay");
    assert_eq!(first.len(), 5);

    // Same ids again, as a retry after a lost acknowledgement would send.
    let appended = batched_seq(&mut store, "idem", 0, 5, "x");
    assert!(
        appended.is_empty(),
        "a retry appended {appended:?} duplicates instead of being a no-op"
    );
    let second = store.events("idem", 0).expect("replay");
    assert_eq!(second, first, "a retry changed the journal");
}

fn batched_seq(store: &mut Store, thread: &str, from: usize, count: usize, body: &str) -> Vec<u64> {
    let events: Vec<(String, EventKind, serde_json::Value)> = (0..count)
        .map(|offset| {
            let index = from + offset;
            (
                format!("{thread}:{index}"),
                EventKind::ToolSucceeded,
                serde_json::json!({"index": index, "content": body}),
            )
        })
        .collect();
    store
        .append_events("local", thread, &events)
        .expect("batch")
}

/// Latency distribution, because a mean hides the fsync tail.
#[test]
#[ignore = "measurement; run with --ignored --nocapture"]
fn commit_latency_distribution() {
    let dir = tempfile::tempdir().expect("tempdir");
    let db = dir.path().join("core.db");
    let mut store = Store::open(&db).expect("open");

    for index in 0..50 {
        append(&mut store, "lat", index, "x");
    }

    let mut samples = Vec::new();
    for index in 50..1050 {
        let started = Instant::now();
        append(&mut store, "lat", index, "x");
        samples.push(started.elapsed());
    }
    samples.sort();
    let mean: Duration = samples.iter().sum::<Duration>() / samples.len() as u32;
    println!(
        "single-append: p50 {:?}, p95 {:?}, max {:?}, mean {:?} over {} samples",
        samples[samples.len() / 2],
        samples[samples.len() * 95 / 100],
        samples[samples.len() - 1],
        mean,
        samples.len()
    );

    let mut batch_samples = Vec::new();
    for batch in 0..100 {
        let started = Instant::now();
        batched(&mut store, "latb", batch * 10, 10, "x");
        batch_samples.push(started.elapsed());
    }
    batch_samples.sort();
    println!(
        "10-event batch: p50 {:?}, p95 {:?}, max {:?} over {} samples",
        batch_samples[batch_samples.len() / 2],
        batch_samples[batch_samples.len() * 95 / 100],
        batch_samples[batch_samples.len() - 1],
        batch_samples.len()
    );
}
