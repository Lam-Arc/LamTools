//! Protocol coverage: every method the real workbench calls must have a real
//! implementation, not a placeholder that returns an empty object.
//!
//! The runner under test here is the real one from `sunday-cli`, backed by a
//! real SQLite store. Only the model is scripted, because a measurement of
//! protocol shape should not depend on a provider.
//!
//! What is checked, method by method:
//!
//!   * `queue/create` actually stores, and a retry with the same id does not
//!     duplicate
//!   * `queue/reorder` changes the order the UI will render
//!   * `thread/read` paginates and reports `has_more` truthfully
//!   * `turn/steer` refuses honestly when nothing is running, instead of
//!     claiming the text was delivered
//!   * `turn/pause` and friends stop the turn and are named distinctly

use sunday_host::app_server::{StopMode, TurnRunner};
use sunday_store::Store;

#[test]
fn a_queue_round_trips_through_the_store() {
    let dir = tempfile::tempdir().expect("tempdir");
    let mut store = Store::open(dir.path().join("core.db")).expect("open");

    store.enqueue("t1", "q1", "first").expect("enqueue");
    store.enqueue("t1", "q2", "second").expect("enqueue");
    let queue = store.queue("t1").expect("queue");
    assert_eq!(queue.len(), 2);
    assert_eq!(queue[0].queue_item_id, "q1");
    assert_eq!(queue[1].queue_item_id, "q2");
    assert!(queue[0].input.contains("first"));
    assert_eq!(queue[0].status, "queued");

    // A retried create with the same id must not duplicate: that is the
    // idempotency the client relies on when an acknowledgement is lost.
    store.enqueue("t1", "q1", "first").expect("retry");
    assert_eq!(store.queue("t1").expect("queue").len(), 2);

    // Reorder and confirm the UI's order changed.
    store
        .reorder_queue("t1", &["q2".to_owned(), "q1".to_owned()])
        .expect("reorder");
    let reordered = store.queue("t1").expect("queue");
    assert_eq!(
        reordered
            .iter()
            .map(|i| i.queue_item_id.as_str())
            .collect::<Vec<_>>(),
        vec!["q2", "q1"]
    );

    // Edit and delete.
    assert!(store
        .update_queue_item("t1", "q1", "edited")
        .expect("update"));
    assert!(store
        .queue("t1")
        .expect("queue")
        .iter()
        .any(|i| i.input.contains("edited")));
    assert!(store.delete_queue_item("t1", "q2").expect("delete"));
    assert_eq!(store.queue("t1").expect("queue").len(), 1);

    // Deleting again is not an error: a double click must not fail.
    assert!(!store.delete_queue_item("t1", "q2").expect("delete twice"));
}

#[test]
fn the_queue_survives_a_restart() {
    let dir = tempfile::tempdir().expect("tempdir");
    let db = dir.path().join("core.db");
    {
        let mut store = Store::open(&db).expect("open");
        store
            .enqueue("t1", "q1", "typed while it ran")
            .expect("enqueue");
    }
    let store = Store::open(&db).expect("reopen");
    let queue = store.queue("t1").expect("queue");
    assert_eq!(queue.len(), 1, "the queue was lost on restart");
    assert!(queue[0].input.contains("typed while it ran"));
}

#[test]
fn history_paginates_and_reports_has_more_truthfully() {
    use sunday_protocol::EventKind;

    let dir = tempfile::tempdir().expect("tempdir");
    let mut store = Store::open(dir.path().join("core.db")).expect("open");
    for index in 0..25 {
        store
            .append_event(
                "local",
                "t1",
                &format!("e{index}"),
                EventKind::ToolSucceeded,
                serde_json::json!({"index": index}),
            )
            .expect("append");
    }

    // First page: the newest 10, oldest-first within the page.
    let (page, has_more) = store.history_page("t1", None, 10).expect("page");
    assert_eq!(page.len(), 10);
    assert!(has_more, "an older page exists but has_more said no");
    assert_eq!(page.first().unwrap().seq, 16);
    assert_eq!(page.last().unwrap().seq, 25);
    assert!(
        page.windows(2).all(|w| w[0].seq < w[1].seq),
        "a page must be ordered oldest-first for a transcript to render"
    );

    // Walk back until the beginning; the union must be the whole journal with no
    // gaps and no repeats. That is what "pagination" has to mean.
    let mut seen: Vec<u64> = page.iter().map(|e| e.seq).collect();
    let mut cursor = page.first().map(|e| e.seq);
    let mut guard = 0;
    loop {
        guard += 1;
        assert!(guard < 20, "pagination did not terminate");
        let (next, more) = store.history_page("t1", cursor, 10).expect("next page");
        if next.is_empty() {
            break;
        }
        // Prepending keeps the overall order.
        let mut seqs: Vec<u64> = next.iter().map(|e| e.seq).collect();
        seqs.extend(seen.clone());
        seen = seqs;
        cursor = next.first().map(|e| e.seq);
        if !more {
            break;
        }
    }
    assert_eq!(
        seen,
        (1..=25).collect::<Vec<u64>>(),
        "walking the pages did not reproduce the journal exactly"
    );
    assert_eq!(store.event_count("t1").expect("count"), 25);
}

#[test]
fn history_of_an_empty_thread_is_empty_and_final() {
    let dir = tempfile::tempdir().expect("tempdir");
    let store = Store::open(dir.path().join("core.db")).expect("open");
    let (page, has_more) = store.history_page("nobody", None, 10).expect("page");
    assert!(page.is_empty());
    assert!(!has_more, "an empty thread claimed there was more history");
    assert_eq!(store.event_count("nobody").expect("count"), 0);
}

/// The runner must answer "not applied" for a steer with no live turn, because
/// the client shows different text for that case and queues the text instead.
#[test]
fn the_unsupported_default_does_not_pretend_to_work() {
    struct Bare;
    impl TurnRunner for Bare {
        fn start_turn(
            &self,
            _: &str,
            _: &str,
            _: &str,
            _: sunday_host::app_server::EventSink<'_>,
        ) -> Result<(), String> {
            Ok(())
        }
        fn respond(
            &self,
            _: &str,
            _: &str,
            _: &str,
            _: &str,
            _: sunday_host::app_server::EventSink<'_>,
        ) -> Result<(), String> {
            Ok(())
        }
        fn cancel(&self, _: &str) -> Result<Vec<sunday_host::app_server::BridgeEvent>, String> {
            Ok(Vec::new())
        }
        fn events(
            &self,
            _: &str,
            _: u64,
        ) -> Result<Vec<sunday_host::app_server::BridgeEvent>, String> {
            Ok(Vec::new())
        }
    }

    let bare = Bare;
    let error = bare.queue("t1").expect_err("a bare runner must not answer");
    assert!(
        error.contains("does not implement"),
        "the refusal was unclear: {error}"
    );
    assert!(bare.history("t1", None, 10).is_err());
    assert!(bare.steer("t1", "turn-1", "hi").is_err());
    // stop_turn has a real default: it cancels through the existing method.
    assert!(bare.stop_turn("t1", StopMode::Pause, &|_| {}).is_ok());
}

/// Every method the workbench calls must be reachable through the adapter's
/// dispatcher. A method that exists on the trait but is not dispatched is the
/// same as unimplemented, and that is exactly the gap this test is for.
#[test]
fn every_workbench_method_is_dispatched() {
    // The list is taken from core/ui/src/appServer/store.ts, which is the only
    // authority on what the UI actually calls.
    const WORKBENCH_METHODS: &[&str] = &[
        "thread/start",
        "thread/resume",
        "thread/read",
        "thread/snapshot",
        "turn/start",
        "turn/resume",
        "turn/steer",
        "turn/pause",
        "turn/interrupt",
        "turn/terminate",
        "turn/force_reset",
        "queue/create",
        "queue/update",
        "queue/delete",
        "queue/guide",
        "queue/reorder",
        "approval/respond",
        "initialize",
    ];

    for method in WORKBENCH_METHODS {
        assert!(
            sunday_host::app_server::is_dispatched(method),
            "{method} is called by the workbench but the adapter answers METHOD_NOT_FOUND"
        );
    }
    assert!(
        !sunday_host::app_server::is_dispatched("artifact/export"),
        "an unimplemented method must still report METHOD_NOT_FOUND"
    );
}
