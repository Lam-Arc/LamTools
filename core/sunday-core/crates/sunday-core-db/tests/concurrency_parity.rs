use serde_json::json;
use std::sync::Arc;
use std::thread;
use sunday_core_db::pool::DbEngine;
use sunday_core_db::runtime::{
    agent_run_list, agent_run_upsert, runtime_append_history, runtime_get, runtime_get_history,
    runtime_save,
};
use sunday_core_db::sessions::list_session_summaries;
use sunday_core_db::snapshots::load_snapshot_page;
use tempfile::tempdir;

fn init_schema(conn: &rusqlite::Connection) {
    conn.execute_batch(
        "CREATE TABLE core_thread_snapshots (
            thread_id TEXT PRIMARY KEY,
            snapshot_seq INTEGER NOT NULL DEFAULT 0,
            revision INTEGER NOT NULL DEFAULT 0,
            active_turn_id TEXT,
            workspace_pin_order INTEGER,
            workspace_session_order INTEGER,
            snapshot_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL
        );
        CREATE TABLE core_thread_snapshot_items (
            thread_id TEXT NOT NULL,
            item_id TEXT NOT NULL,
            seq INTEGER NOT NULL DEFAULT 0,
            item_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL,
            PRIMARY KEY (thread_id, item_id)
        );
        CREATE TABLE core_turn_interactions (
            interaction_id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL,
            turn_id TEXT NOT NULL,
            run_id TEXT NOT NULL DEFAULT '',
            scope TEXT NOT NULL DEFAULT 'main',
            kind TEXT NOT NULL,
            status TEXT NOT NULL,
            tool_call_id TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL DEFAULT '',
            body TEXT NOT NULL DEFAULT '',
            context_text TEXT NOT NULL DEFAULT '',
            options_json TEXT NOT NULL DEFAULT '[]',
            expires_at_ms INTEGER NOT NULL DEFAULT 0,
            answer_json TEXT,
            created_seq INTEGER NOT NULL DEFAULT 0,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE core_runtime_sessions (
            thread_id TEXT PRIMARY KEY,
            revision INTEGER NOT NULL DEFAULT 1,
            runtime_state_json TEXT NOT NULL DEFAULT '{}',
            history_json TEXT NOT NULL DEFAULT '[]',
            pending_approval_json TEXT NOT NULL DEFAULT '{}',
            last_event_seq INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE core_history_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id TEXT NOT NULL,
            seq INTEGER NOT NULL,
            revision INTEGER NOT NULL DEFAULT 0,
            message_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE (thread_id, seq)
        );
        CREATE TABLE core_agent_runs (
            agent_run_id TEXT PRIMARY KEY,
            parent_thread_id TEXT NOT NULL,
            parent_turn_id TEXT NOT NULL DEFAULT '',
            parent_run_id TEXT NOT NULL DEFAULT '',
            name TEXT NOT NULL DEFAULT '',
            type TEXT NOT NULL DEFAULT 'execute',
            model_id TEXT NOT NULL DEFAULT '',
            reasoning_level TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'idle',
            lease_until_ms INTEGER NOT NULL DEFAULT 0,
            sub_session_id TEXT NOT NULL DEFAULT '',
            source_call_id TEXT NOT NULL DEFAULT '',
            source_run_id TEXT NOT NULL DEFAULT '',
            source_turn_id TEXT NOT NULL DEFAULT '',
            summary TEXT NOT NULL DEFAULT '',
            started_at_ms INTEGER NOT NULL DEFAULT 0,
            completed_at_ms INTEGER NOT NULL DEFAULT 0,
            elapsed_ms INTEGER NOT NULL DEFAULT 0,
            payload_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL
        );
        CREATE TABLE core_app_events (
            event_id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL,
            seq INTEGER NOT NULL,
            turn_id TEXT,
            item_id TEXT,
            parent_item_id TEXT,
            client_message_id TEXT,
            method TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            workspace_id TEXT NOT NULL DEFAULT '',
            entity_type TEXT NOT NULL DEFAULT 'thread.event',
            entity_id TEXT NOT NULL DEFAULT '',
            event_seq INTEGER NOT NULL DEFAULT 0,
            revision INTEGER NOT NULL DEFAULT 0,
            event_type TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE core_sync_changes (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            change_id TEXT NOT NULL UNIQUE,
            workspace_id TEXT NOT NULL DEFAULT '',
            entity_type TEXT NOT NULL,
            event_type TEXT NOT NULL DEFAULT '',
            operation TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            thread_id TEXT NOT NULL DEFAULT '',
            revision INTEGER NOT NULL DEFAULT 0,
            entity_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );",
    )
    .unwrap();
}

#[test]
fn multithreaded_sessions_and_agents_rw() {
    let dir = tempdir().unwrap();
    let db_path = dir.path().join("rust_conc.db");
    let engine = Arc::new(DbEngine::open(&db_path).unwrap());
    engine
        .write_tx(|conn| {
            init_schema(conn);
            for i in 0..4 {
                conn.execute(
                    "INSERT INTO core_thread_snapshots (thread_id, snapshot_seq, revision, snapshot_json, updated_at) \
                     VALUES (?1, 1, 1, ?2, '2026-11-17 10:00:00.000000')",
                    rusqlite::params![
                        format!("t-{i}"),
                        json!({"thread_id": format!("t-{i}"), "status": "idle", "core": {"resource_usage_version": 1}}).to_string()
                    ],
                )?;
            }
            Ok(())
        })
        .unwrap();

    let mut handles = Vec::new();
    for w in 0..4 {
        let eng = Arc::clone(&engine);
        handles.push(thread::spawn(move || {
            let sid = format!("t-{w}");
            let mut rev: Option<i64> = None;
            for step in 0..30 {
                let res = runtime_save(
                    &eng,
                    &json!({
                        "session_id": sid,
                        "expected_revision": rev,
                        "state_payload": {"session_id": sid, "status": "running", "metadata": {"step": step}},
                        "pending_payload": {},
                        "last_event_seq": step,
                        "now_str": "2026-11-17 10:01:00.000000"
                    }),
                )
                .unwrap();
                rev = res["revision"].as_i64();
                runtime_append_history(
                    &eng,
                    &json!({
                        "session_id": sid,
                        "messages": [{"role": "user", "content": format!("hi {step}")}],
                        "now_str": "2026-11-17 10:01:00.000000"
                    }),
                )
                .unwrap();
                agent_run_upsert(
                    &eng,
                    &json!({
                        "agent_run_id": format!("ar-{w}"),
                        "parent_thread_id": sid,
                        "name": format!("sub-{w}"),
                        "status": "running",
                        "summary": format!("step {step}"),
                        "now_str": "2026-11-17 10:01:00.000000"
                    }),
                )
                .unwrap();
            }
        }));
    }
    for _ in 0..4 {
        let eng = Arc::clone(&engine);
        handles.push(thread::spawn(move || {
            for i in 0..40 {
                let _ = list_session_summaries(&eng).unwrap();
                let tid = format!("t-{}", i % 4);
                let _ = load_snapshot_page(&eng, &tid, None, None, 100_000).unwrap();
                let _ = runtime_get(&eng, &tid).unwrap();
                let _ = agent_run_list(&eng, None, Some(&tid), false).unwrap();
            }
        }));
    }
    for h in handles {
        h.join().unwrap();
    }

    for w in 0..4 {
        let hist = runtime_get_history(&engine, &format!("t-{w}"), 0).unwrap();
        assert_eq!(hist.as_array().unwrap().len(), 30);
    }
    engine.close();
}
