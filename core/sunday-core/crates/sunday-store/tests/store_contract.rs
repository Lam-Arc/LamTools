//! Contract tests for the durable store.
//!
//! Every test uses a real SQLite file in a temporary directory. Nothing here
//! uses an in-memory database, because the guarantees under test are about what
//! survives a process dying, and an in-memory database cannot show that.

use std::path::PathBuf;
use std::process::Command as ProcessCommand;
use sunday_protocol::{
    Command, CommandEnvelope, CommandStatus, CoreError, EventKind, Prepared, SideEffect, ToolCall,
    PROTOCOL_VERSION,
};
use sunday_store::ApprovalStatus;
use sunday_store::Store;

const WORKSPACE: &str = "ws";

fn temp_db() -> (tempfile::TempDir, PathBuf) {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("core.db");
    (dir, path)
}

fn envelope(request_id: &str, thread: &str, text: &str) -> CommandEnvelope {
    CommandEnvelope {
        protocol_version: PROTOCOL_VERSION.into(),
        request_id: request_id.into(),
        thread_id: thread.into(),
        expected_revision: None,
        payload: Command::TurnStart { text: text.into() },
    }
}

fn call(id: &str, path: &str) -> ToolCall {
    ToolCall {
        id: id.into(),
        name: "write_file".into(),
        args: serde_json::json!({ "path": path, "content": "x" }),
    }
}

// ---------------------------------------------------------------- S1

#[test]
fn s1_a_resent_request_yields_one_receipt_and_one_event() {
    let (_dir, path) = temp_db();
    let mut store = Store::open(&path).unwrap();

    let first = store
        .accept_command(WORKSPACE, &envelope("req-1", "t1", "hi"))
        .unwrap();
    let second = store
        .accept_command(WORKSPACE, &envelope("req-1", "t1", "hi"))
        .unwrap();

    assert_eq!(
        first, second,
        "the second call must return the stored receipt"
    );
    assert_eq!(first.seq, Some(1));
    assert_eq!(store.events("t1", 0).unwrap().len(), 1);
    assert_eq!(store.table_counts().unwrap()["command_receipts"], 1);
}

#[test]
fn s1b_the_same_request_id_with_a_different_body_is_refused() {
    let (_dir, path) = temp_db();
    let mut store = Store::open(&path).unwrap();
    store
        .accept_command(WORKSPACE, &envelope("req-1", "t1", "first"))
        .unwrap();

    let err = store
        .accept_command(WORKSPACE, &envelope("req-1", "t1", "different"))
        .unwrap_err();
    assert!(matches!(err, CoreError::Rejected { .. }), "got {err:?}");
    assert_eq!(store.events("t1", 0).unwrap().len(), 1);
}

// ---------------------------------------------------------------- S2

#[test]
fn s2_seq_is_contiguous_and_survives_reopening() {
    let (_dir, path) = temp_db();
    {
        let mut store = Store::open(&path).unwrap();
        store
            .accept_command(WORKSPACE, &envelope("req-1", "t1", "a"))
            .unwrap();
        for index in 0..3 {
            store
                .append_event(
                    WORKSPACE,
                    "t1",
                    &format!("e{index}"),
                    EventKind::ModelStarted,
                    serde_json::json!({}),
                )
                .unwrap();
        }
    }
    let mut store = Store::open(&path).unwrap();
    store
        .append_event(
            WORKSPACE,
            "t1",
            "e9",
            EventKind::RunCompleted,
            serde_json::json!({}),
        )
        .unwrap();

    let seqs: Vec<u64> = store
        .events("t1", 0)
        .unwrap()
        .iter()
        .map(|e| e.seq)
        .collect();
    assert_eq!(seqs, vec![1, 2, 3, 4, 5]);
}

#[test]
fn s2b_resending_an_event_id_is_a_noop() {
    let (_dir, path) = temp_db();
    let mut store = Store::open(&path).unwrap();
    let first = store
        .append_event(
            WORKSPACE,
            "t1",
            "same",
            EventKind::ModelStarted,
            serde_json::json!({}),
        )
        .unwrap();
    let again = store
        .append_event(
            WORKSPACE,
            "t1",
            "same",
            EventKind::ModelStarted,
            serde_json::json!({}),
        )
        .unwrap();
    assert_eq!(first, again);
    assert_eq!(store.events("t1", 0).unwrap().len(), 1);
}

// ---------------------------------------------------------------- S3

#[test]
fn s3_intent_is_durable_before_any_side_effect() {
    let (_dir, path) = temp_db();
    {
        let mut store = Store::open(&path).unwrap();
        let answer = store
            .prepare_tool_once("t1", &call("c1", "a.txt"), SideEffect::NonIdempotent)
            .unwrap();
        assert_eq!(answer, Prepared::Ready);
        // Simulate dying right here: no dispatch, no result.
    }
    let store = Store::open(&path).unwrap();
    assert_eq!(
        store.tool_stage("c1").unwrap(),
        Some(sunday_protocol::ToolStage::Prepared)
    );
    assert!(store.tool_result("c1").unwrap().is_none());
}

#[test]
fn s3b_the_same_call_id_with_different_arguments_is_refused() {
    let (_dir, path) = temp_db();
    let mut store = Store::open(&path).unwrap();
    store
        .prepare_tool_once("t1", &call("c1", "a.txt"), SideEffect::NonIdempotent)
        .unwrap();
    let err = store
        .prepare_tool_once(
            "t1",
            &call("c1", "elsewhere.txt"),
            SideEffect::NonIdempotent,
        )
        .unwrap_err();
    assert!(matches!(err, CoreError::Rejected { .. }));
}

// ---------------------------------------------------------------- S4

#[test]
fn s4_a_dispatched_non_idempotent_call_becomes_unknown_and_is_never_replayed() {
    let (_dir, path) = temp_db();
    {
        let mut store = Store::open(&path).unwrap();
        store
            .prepare_tool_once("t1", &call("c1", "a.txt"), SideEffect::NonIdempotent)
            .unwrap();
        store.mark_dispatched("c1").unwrap();
        // Process dies here, before the result could be written.
    }

    let mut store = Store::open(&path).unwrap();
    let plan = store.recover().unwrap();
    assert_eq!(plan.unknown, vec!["c1".to_owned()]);
    assert_eq!(
        store.tool_stage("c1").unwrap(),
        Some(sunday_protocol::ToolStage::Unknown)
    );

    let again = store
        .prepare_tool_once("t1", &call("c1", "a.txt"), SideEffect::NonIdempotent)
        .unwrap();
    assert_eq!(again, Prepared::MustReconcile);
}

#[test]
fn s4b_a_dispatched_idempotent_call_is_requeueable() {
    let (_dir, path) = temp_db();
    {
        let mut store = Store::open(&path).unwrap();
        store
            .prepare_tool_once("t1", &call("c2", "b.txt"), SideEffect::Idempotent)
            .unwrap();
        store.mark_dispatched("c2").unwrap();
    }
    let mut store = Store::open(&path).unwrap();
    let plan = store.recover().unwrap();
    assert_eq!(plan.requeueable, vec!["c2".to_owned()]);
    assert!(plan.unknown.is_empty());
}

#[test]
fn s4c_a_finished_call_replays_its_stored_answer_instead_of_running() {
    let (_dir, path) = temp_db();
    let mut store = Store::open(&path).unwrap();
    store
        .prepare_tool_once("t1", &call("c3", "c.txt"), SideEffect::NonIdempotent)
        .unwrap();
    store.mark_dispatched("c3").unwrap();
    store
        .finish_tool_call("c3", &serde_json::json!({"ok": true}), true)
        .unwrap();

    let mut store = Store::open(&path).unwrap();
    assert_eq!(store.recover().unwrap().unknown, Vec::<String>::new());
    assert_eq!(
        store
            .prepare_tool_once("t1", &call("c3", "c.txt"), SideEffect::NonIdempotent)
            .unwrap(),
        Prepared::AlreadyDone
    );
    assert_eq!(store.tool_result("c3").unwrap().unwrap()["ok"], true);
}

/// A denial inside the window must be recorded, not reported as expired.
///
/// The caller used to pass milliseconds where this comparison expects seconds, which
/// made every denial look a thousand times past its deadline: the user pressed Deny
/// and was told the request had aged out, and the row stayed pending.
#[test]
fn denying_inside_the_window_succeeds() {
    let (_dir, path) = temp_db();
    let mut store = Store::open(&path).unwrap();
    let approval = store
        .request_approval("t1", &call("c1", "a.txt"), 300, 1_000)
        .unwrap();

    store
        .respond_approval(&approval.approval_id, &approval.args_digest, 1_010, false)
        .expect("a denial inside the window must be accepted");
    assert_eq!(
        store
            .approval_status(&approval.approval_id)
            .unwrap()
            .as_deref(),
        Some("denied"),
    );
}

/// The gate the RPC layer asks before it claims a decision was accepted.
///
/// `pending_call` cannot answer this: it looks up the call's arguments and ignores
/// both `status` and `expires_at`. Reading it as permission let an hour-old request
/// pass the check and only fail later, on another thread, where the screen never saw
/// it.
#[test]
fn the_gate_separates_pending_from_expired_and_answered() {
    let (_dir, path) = temp_db();
    let mut store = Store::open(&path).unwrap();
    let approval = store
        .request_approval("t1", &call("c1", "a.txt"), 60, 1_000)
        .unwrap();

    assert_eq!(
        store.approval_gate(&approval.approval_id, 1_010).unwrap(),
        Some(ApprovalStatus::Pending),
    );
    // Past the deadline the same id may not be treated as consent, even though the
    // row still says `pending` until somebody sweeps it.
    assert_eq!(
        store.approval_gate(&approval.approval_id, 1_061).unwrap(),
        Some(ApprovalStatus::Expired),
    );

    store
        .respond_approval(&approval.approval_id, &approval.args_digest, 1_010, true)
        .unwrap();
    assert_eq!(
        store.approval_gate(&approval.approval_id, 1_011).unwrap(),
        Some(ApprovalStatus::Answered),
    );
    assert_eq!(store.approval_gate("nope", 1_011).unwrap(), None);
}

/// The sweep that lets a stuck conversation move again.
#[test]
fn the_sweep_closes_only_what_is_overdue_and_is_idempotent() {
    let (_dir, path) = temp_db();
    let mut store = Store::open(&path).unwrap();
    let stale = store
        .request_approval("t1", &call("c1", "a.txt"), 10, 1_000)
        .unwrap();
    let fresh = store
        .request_approval("t1", &call("c2", "b.txt"), 600, 1_000)
        .unwrap();

    let closed = store.expire_stale_approvals(1_020).unwrap();
    assert_eq!(closed, vec![stale.approval_id.clone()]);
    assert_eq!(
        store
            .approval_status(&stale.approval_id)
            .unwrap()
            .as_deref(),
        Some("expired"),
    );
    assert_eq!(
        store
            .approval_status(&fresh.approval_id)
            .unwrap()
            .as_deref(),
        Some("pending"),
        "a request still inside its window must survive the sweep",
    );

    // Second sweep finds nothing: the closure is a fact, not a repeated event.
    assert!(store.expire_stale_approvals(1_030).unwrap().is_empty());
}

/// A closed approval must never authorise execution afterwards.
#[test]
fn a_swept_approval_cannot_be_used() {
    let (_dir, path) = temp_db();
    let mut store = Store::open(&path).unwrap();
    let approval = store
        .request_approval("t1", &call("c1", "a.txt"), 10, 1_000)
        .unwrap();
    store.expire_stale_approvals(2_000).unwrap();

    let error = store
        .respond_approval(&approval.approval_id, &approval.args_digest, 2_001, true)
        .unwrap_err();
    assert!(
        matches!(error, CoreError::ApprovalExpired { .. }),
        "got {error:?}",
    );
}

// ---------------------------------------------------------------- S5, S6, S7

#[test]
fn s5_an_approval_is_bound_to_its_arguments() {
    let (_dir, path) = temp_db();
    let mut store = Store::open(&path).unwrap();
    let the_call = call("c1", "a.txt");
    let approval = store.request_approval("t1", &the_call, 300, 1_000).unwrap();

    let tampered = sunday_protocol::digest_json(&serde_json::json!({"path": "../etc/passwd"}));
    let err = store
        .respond_approval(&approval.approval_id, &tampered, 1_010, true)
        .unwrap_err();
    assert!(
        matches!(err, CoreError::ApprovalArgsMismatch { .. }),
        "got {err:?}"
    );
    assert_eq!(
        store
            .approval_status(&approval.approval_id)
            .unwrap()
            .as_deref(),
        Some("pending"),
        "a refused decision must not consume the approval"
    );
}

#[test]
fn s6_an_expired_approval_is_not_consent() {
    let (_dir, path) = temp_db();
    let mut store = Store::open(&path).unwrap();
    let the_call = call("c1", "a.txt");
    let approval = store.request_approval("t1", &the_call, 10, 1_000).unwrap();

    let err = store
        .respond_approval(&approval.approval_id, &approval.args_digest, 9_999, true)
        .unwrap_err();
    assert!(
        matches!(err, CoreError::ApprovalExpired { .. }),
        "got {err:?}"
    );
    // The expiry is persisted, so a retry after a restart is still refused.
    drop(store);
    let store = Store::open(&path).unwrap();
    assert_eq!(
        store
            .approval_status(&approval.approval_id)
            .unwrap()
            .as_deref(),
        Some("expired")
    );
}

#[test]
fn s7_an_approval_can_be_spent_only_once() {
    let (_dir, path) = temp_db();
    let mut store = Store::open(&path).unwrap();
    let the_call = call("c1", "a.txt");
    store
        .prepare_tool_once("t1", &the_call, SideEffect::NonIdempotent)
        .unwrap();
    let approval = store.request_approval("t1", &the_call, 300, 1_000).unwrap();

    store
        .respond_approval(&approval.approval_id, &approval.args_digest, 1_010, true)
        .unwrap();
    let err = store
        .respond_approval(&approval.approval_id, &approval.args_digest, 1_011, true)
        .unwrap_err();
    assert!(
        matches!(err, CoreError::ApprovalExpired { .. }),
        "got {err:?}"
    );
}

#[test]
fn s7b_a_zero_ttl_approval_is_refused_at_creation() {
    let (_dir, path) = temp_db();
    let mut store = Store::open(&path).unwrap();
    let err = store
        .request_approval("t1", &call("c1", "a.txt"), 0, 1_000)
        .unwrap_err();
    assert!(matches!(err, CoreError::InvalidRequest { .. }));
}

// ---------------------------------------------------------------- S8

#[test]
fn s8_a_projection_rebuilds_from_the_journal_alone() {
    let (_dir, path) = temp_db();
    let mut store = Store::open(&path).unwrap();
    store
        .accept_command(WORKSPACE, &envelope("req-1", "t1", "a"))
        .unwrap();
    for index in 0..4 {
        store
            .append_event(
                WORKSPACE,
                "t1",
                &format!("e{index}"),
                if index % 2 == 0 {
                    EventKind::ModelStarted
                } else {
                    EventKind::ToolSucceeded
                },
                serde_json::json!({}),
            )
            .unwrap();
    }

    let live = store.projection("t1").unwrap();
    let rebuilt = store.rebuild_projection("t1").unwrap();

    assert_eq!(live.last_seq, rebuilt.last_seq);
    assert_eq!(live.counts, rebuilt.counts);
    assert_eq!(rebuilt.last_seq, 5);
    // Index 0 and 2 are model_started; 1 and 3 are tool_succeeded.
    assert_eq!(rebuilt.counts["model_started"], 2);
    assert_eq!(rebuilt.counts["tool_succeeded"], 2);
    assert_eq!(rebuilt.counts["command_accepted"], 1);
}

// ---------------------------------------------------------------- concurrency

#[test]
fn c1_a_stale_expected_revision_is_refused() {
    let (_dir, path) = temp_db();
    let mut store = Store::open(&path).unwrap();
    store
        .accept_command(WORKSPACE, &envelope("req-1", "t1", "a"))
        .unwrap();

    let mut stale = envelope("req-2", "t1", "b");
    stale.expected_revision = Some(0);
    let err = store.accept_command(WORKSPACE, &stale).unwrap_err();
    match err {
        CoreError::RevisionConflict { expected, actual } => {
            assert_eq!(expected, 0);
            assert_eq!(actual, 1);
        }
        other => panic!("expected a revision conflict, got {other:?}"),
    }

    let mut fresh = envelope("req-3", "t1", "c");
    fresh.expected_revision = Some(1);
    store.accept_command(WORKSPACE, &fresh).unwrap();
}

#[test]
fn c2_two_processes_writing_at_once_do_not_lose_or_duplicate_events() {
    let (_dir, path) = temp_db();
    Store::open(&path).unwrap();

    const PER_WORKER: usize = 20;
    let children: Vec<_> = (0..2)
        .map(|worker| {
            ProcessCommand::new(std::env::current_exe().unwrap())
                .args(["--exact", "append_worker", "--ignored", "--nocapture"])
                .env("SUNDAY_CHILD", "append")
                .env("SUNDAY_CHILD_DB", &path)
                .env("SUNDAY_CHILD_WORKER", worker.to_string())
                .env("SUNDAY_CHILD_COUNT", PER_WORKER.to_string())
                .spawn()
                .expect("spawn worker")
        })
        .collect();
    for mut child in children {
        let status = child.wait().unwrap();
        assert!(status.success(), "worker failed: {status:?}");
    }

    let store = Store::open(&path).unwrap();
    let events = store.events("t1", 0).unwrap();
    assert_eq!(events.len(), PER_WORKER * 2);
    let seqs: Vec<u64> = events.iter().map(|e| e.seq).collect();
    let expected: Vec<u64> = (1..=PER_WORKER as u64 * 2).collect();
    assert_eq!(seqs, expected, "seq must be contiguous with no gaps");
}

/// Builds a database whose journal says a non-idempotent call was dispatched and
/// never answered.
///
/// Used to put a real "the process died mid-tool" state onto a device, so the resume
/// path can be checked against a journal it did not write itself. The log is folded
/// back into the main file so a single `core.db` can be copied into place.
#[test]
#[ignore = "helper; run with SUNDAY_FIXTURE_DB set"]
fn build_a_database_with_a_call_in_flight() {
    let Ok(path) = std::env::var("SUNDAY_FIXTURE_DB") else {
        return;
    };
    let mut store = Store::open(&path).unwrap();
    store
        .prepare_tool_once("t1", &call("call-1", "a.txt"), SideEffect::NonIdempotent)
        .unwrap();
    store.mark_dispatched("call-1").unwrap();
    store.checkpoint().unwrap();
}

// ---------------------------------------------------------------- crash

#[test]
#[ignore = "helper process; runs only when spawned by the crash test"]
fn crash_after_dispatch() {
    if std::env::var("SUNDAY_CHILD").as_deref() != Ok("crash") {
        return;
    }
    let db = std::env::var("SUNDAY_CHILD_DB").unwrap();
    let mut store = Store::open(&db).unwrap();
    store
        .prepare_tool_once("t1", &call("crash-1", "a.txt"), SideEffect::NonIdempotent)
        .unwrap();
    store.mark_dispatched("crash-1").unwrap();
    // Die without unwinding, the way a killed process does.
    std::process::abort();
}

#[test]
#[ignore = "helper process; runs only when spawned by the crash test"]
fn abort_mid_transaction() {
    if std::env::var("SUNDAY_CHILD").as_deref() != Ok("abort") {
        return;
    }
    let db = std::env::var("SUNDAY_CHILD_DB").unwrap();
    // Open the raw file and die inside an open write transaction.
    let conn = rusqlite::Connection::open(&db).unwrap();
    conn.execute_batch("BEGIN IMMEDIATE").unwrap();
    conn.execute(
        "INSERT INTO journal_events (workspace_id, thread_id, seq, event_id, kind, payload, created_at) \
         VALUES ('ws', 't1', 999, 'ghost', 'model_started', '{}', 0)",
        [],
    )
    .unwrap();
    std::process::abort();
}

#[test]
#[ignore = "helper process; runs only when spawned by the crash test"]
fn batch_abort_worker() {
    if std::env::var("SUNDAY_CHILD").as_deref() != Ok("batch-abort") {
        return;
    }
    let db = std::env::var("SUNDAY_CHILD_DB").unwrap();
    let mut store = Store::open(&db).unwrap();
    let events: Vec<(String, EventKind, serde_json::Value)> = (1..=20)
        .map(|index| {
            (
                format!("batch:{index}"),
                EventKind::ToolSucceeded,
                serde_json::json!({"index": index}),
            )
        })
        .collect();
    store.append_events("local", "t1", &events).unwrap();
    // Now start a second batch and die inside it, before it can commit.
    let conn = rusqlite::Connection::open(&db).unwrap();
    conn.execute_batch("BEGIN IMMEDIATE").unwrap();
    for index in 21..=40 {
        conn.execute(
            "INSERT INTO journal_events (workspace_id, thread_id, seq, event_id, kind, payload, created_at) \
             VALUES ('local', 't1', ?1, ?2, 'tool_succeeded', '{}', 0)",
            rusqlite::params![index as i64, format!("batch:{index}")],
        )
        .unwrap();
    }
    std::process::abort();
}

/// A batch that is killed mid-way must leave nothing at all: either the whole
/// logical operation is durable or none of it is. This is the guarantee batching
/// could have quietly broken.
#[test]
fn c3_a_batch_interrupted_by_a_crash_leaves_no_partial_events() {
    let (_dir, path) = temp_db();
    Store::open(&path).unwrap();

    let mut child = ProcessCommand::new(std::env::current_exe().unwrap())
        .args(["--exact", "batch_abort_worker", "--ignored", "--nocapture"])
        .env("SUNDAY_CHILD", "batch-abort")
        .env("SUNDAY_CHILD_DB", &path)
        .spawn()
        .expect("spawn");
    let status = child.wait().unwrap();
    assert!(!status.success(), "the helper was supposed to die");

    let store = Store::open(&path).unwrap();
    let events = store.events("t1", 0).unwrap();
    assert_eq!(
        events.len(),
        20,
        "the committed batch should be fully present"
    );
    let seqs: Vec<u64> = events.iter().map(|e| e.seq).collect();
    assert_eq!(
        seqs,
        (1..=20).collect::<Vec<u64>>(),
        "seq must stay contiguous after an interrupted batch"
    );
    // And the projection must not claim more than the journal holds.
    let projection = store.projection("t1").unwrap();
    assert_eq!(projection.last_seq, 20);
}

#[test]
#[ignore = "helper process; runs only when spawned by the crash test"]
fn append_worker() {
    if std::env::var("SUNDAY_CHILD").as_deref() != Ok("append") {
        return;
    }
    let db = std::env::var("SUNDAY_CHILD_DB").unwrap();
    let worker = std::env::var("SUNDAY_CHILD_WORKER").unwrap();
    let count: usize = std::env::var("SUNDAY_CHILD_COUNT")
        .unwrap()
        .parse()
        .unwrap();
    let mut store = Store::open(&db).unwrap();
    for index in 0..count {
        store
            .append_event(
                WORKSPACE,
                "t1",
                &format!("w{worker}-{index}"),
                EventKind::ModelStarted,
                serde_json::json!({"worker": worker, "index": index}),
            )
            .unwrap();
    }
}

#[test]
fn k1_a_process_killed_after_dispatch_leaves_an_unknown_outcome() {
    let (_dir, path) = temp_db();
    Store::open(&path).unwrap();

    let status = ProcessCommand::new(std::env::current_exe().unwrap())
        .args([
            "--exact",
            "crash_after_dispatch",
            "--ignored",
            "--nocapture",
        ])
        .env("SUNDAY_CHILD", "crash")
        .env("SUNDAY_CHILD_DB", &path)
        .status()
        .expect("spawn crash child");
    assert!(!status.success(), "the child must die, not exit cleanly");

    let mut store = Store::open(&path).unwrap();
    let plan = store.recover().unwrap();
    assert_eq!(plan.unknown, vec!["crash-1".to_owned()]);
    assert_eq!(
        store
            .prepare_tool_once("t1", &call("crash-1", "a.txt"), SideEffect::NonIdempotent)
            .unwrap(),
        Prepared::MustReconcile,
        "an unknown side effect must never be retried by the machine"
    );
}

#[test]
fn k2_a_write_interrupted_by_a_kill_leaves_no_partial_row() {
    let (_dir, path) = temp_db();
    {
        let mut store = Store::open(&path).unwrap();
        store
            .append_event(
                WORKSPACE,
                "t1",
                "before",
                EventKind::RunStarted,
                serde_json::json!({}),
            )
            .unwrap();
    }

    let status = ProcessCommand::new(std::env::current_exe().unwrap())
        .args([
            "--exact",
            "abort_mid_transaction",
            "--ignored",
            "--nocapture",
        ])
        .env("SUNDAY_CHILD", "abort")
        .env("SUNDAY_CHILD_DB", &path)
        .status()
        .expect("spawn abort child");
    assert!(!status.success());

    let mut store = Store::open(&path).unwrap();
    let events = store.events("t1", 0).unwrap();
    assert_eq!(events.len(), 1, "the uncommitted row must be gone");
    assert_eq!(events[0].event_id, "before");

    // The sequence must continue from the last committed value, not from 999.
    let seq = store
        .append_event(
            WORKSPACE,
            "t1",
            "after",
            EventKind::RunCompleted,
            serde_json::json!({}),
        )
        .unwrap();
    assert_eq!(seq, 2);
}

#[test]
fn k3_recovery_is_idempotent() {
    let (_dir, path) = temp_db();
    {
        let mut store = Store::open(&path).unwrap();
        store
            .prepare_tool_once("t1", &call("c1", "a.txt"), SideEffect::NonIdempotent)
            .unwrap();
        store.mark_dispatched("c1").unwrap();
    }
    let mut store = Store::open(&path).unwrap();
    let first = store.recover().unwrap();
    let second = store.recover().unwrap();
    assert_eq!(first.unknown.len(), 1);
    assert!(second.unknown.is_empty(), "the second pass must be a no-op");
}

#[test]
fn k4_an_abandoned_receipt_is_marked_failed_on_recovery() {
    let (_dir, path) = temp_db();
    {
        let mut store = Store::open(&path).unwrap();
        store
            .accept_command(WORKSPACE, &envelope("req-1", "t1", "a"))
            .unwrap();
        // The command was accepted, then the process died before finishing it.
    }
    let mut store = Store::open(&path).unwrap();
    let plan = store.recover().unwrap();
    assert_eq!(plan.abandoned_receipts, vec!["req-1".to_owned()]);
    assert_eq!(
        store.receipt("req-1").unwrap().unwrap().status,
        CommandStatus::Failed
    );
}

#[test]
fn k5_inspection_never_writes_not_even_wal_or_shm() {
    let (_dir, path) = temp_db();
    {
        let mut store = Store::open(&path).unwrap();
        store
            .accept_command(WORKSPACE, &envelope("req-1", "t1", "a"))
            .unwrap();
    }
    // A clean close checkpoints and removes the side files.
    let side = |suffix: &str| PathBuf::from(format!("{}{suffix}", path.display()));
    assert!(!side("-wal").exists(), "wal survived a clean close");
    assert!(!side("-shm").exists(), "shm survived a clean close");

    let before = std::fs::read(&path).unwrap();
    {
        let store = Store::open_read_only(&path).unwrap();
        // Read from the constant, not a literal: a schema bump is a deliberate
        // change, and a hard-coded number here just breaks on every upgrade
        // without saying anything about inspection.
        assert_eq!(
            store.schema_version().unwrap(),
            sunday_store::SCHEMA_VERSION
        );
        assert_eq!(store.table_counts().unwrap()["journal_events"], 1);
    }
    let after = std::fs::read(&path).unwrap();
    assert_eq!(before, after, "read-only inspection changed the database");
    assert!(
        !side("-wal").exists(),
        "read-only inspection created a wal file"
    );
    assert!(
        !side("-shm").exists(),
        "read-only inspection created a shm file"
    );
}

#[test]
fn k5b_a_database_with_a_live_wal_is_refused_rather_than_read_as_a_moving_target() {
    let (_dir, path) = temp_db();
    Store::open(&path).unwrap();
    // Pretend another process is mid-write.
    let wal = PathBuf::from(format!("{}-wal", path.display()));
    std::fs::write(&wal, b"pending").unwrap();

    let err = Store::open_read_only(&path).unwrap_err();
    assert!(matches!(err, CoreError::Rejected { .. }), "got {err:?}");
    std::fs::remove_file(&wal).unwrap();
}

#[test]
fn k6_a_newer_schema_is_refused_instead_of_downgraded() {
    let (_dir, path) = temp_db();
    {
        let store = Store::open(&path).unwrap();
        drop(store);
    }
    {
        let conn = rusqlite::Connection::open(&path).unwrap();
        conn.execute(
            "UPDATE schema_meta SET value = '99' WHERE key = 'schema_version'",
            [],
        )
        .unwrap();
    }
    let err = Store::open(&path).unwrap_err();
    assert!(
        matches!(err, CoreError::ProtocolIncompatible { .. }),
        "got {err:?}"
    );
}
