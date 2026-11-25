//! Native Rust SQLite backend for `SubAgentSupervisor`, mailbox wake watchdog, and lifecycle events.
//!
//! user:“开始”+(将子代理注册表、双向邮箱与生命周期唤醒状态全面迁入 Rust WAL 连接池与串行写通道，彻底消除在事件循环线程反复开关同步 sqlite3 导致的冻屏与锁争抢)。

use crate::pool::{next_hex_id, now_unix_secs, DbEngine, DbError};
use crate::repair::sha256_hex;
use rusqlite::{params, Connection, ErrorCode, OptionalExtension};
use serde_json::{json, Map, Value};
use std::collections::HashSet;
use std::sync::atomic::Ordering;

fn is_no_such_table(err: &DbError) -> bool {
    if let DbError::Sqlite(rusqlite::Error::SqliteFailure(inner, Some(msg))) = err {
        return inner.code == ErrorCode::Unknown || msg.contains("no such table");
    }
    if let DbError::Sqlite(rusqlite::Error::SqliteFailure(_, None)) = err {
        return true;
    }
    err.to_string().contains("no such table")
}

fn ensure_tables_on_conn(conn: &Connection) -> Result<(), DbError> {
    conn.execute_batch(
        "CREATE TABLE IF NOT EXISTS sub_agents (
           parent_thread_id TEXT NOT NULL, name TEXT NOT NULL, payload TEXT NOT NULL,
           PRIMARY KEY(parent_thread_id, name)
         );",
    )?;

    let mut present_cols: HashSet<String> = HashSet::new();
    {
        let mut stmt = conn.prepare("PRAGMA table_info(sub_agent_mailbox)")?;
        let mut rows = stmt.query([])?;
        while let Some(row) = rows.next()? {
            let col: String = row.get(1)?;
            present_cols.insert(col);
        }
    }
    if !present_cols.is_empty() && !present_cols.contains("message_key") {
        conn.execute(
            "ALTER TABLE sub_agent_mailbox RENAME TO sub_agent_mailbox_legacy",
            [],
        )?;
    }

    conn.execute_batch(
        "CREATE TABLE IF NOT EXISTS sub_agent_mailbox (
           id TEXT PRIMARY KEY, parent_thread_id TEXT NOT NULL, name TEXT NOT NULL,
           direction TEXT NOT NULL, body TEXT NOT NULL, digest TEXT NOT NULL,
           message_key TEXT NOT NULL, created_at REAL NOT NULL, delivered_at REAL,
           tags TEXT NOT NULL DEFAULT '', wake INTEGER NOT NULL DEFAULT 0,
           wake_count INTEGER NOT NULL DEFAULT 0,
           source_call_id TEXT NOT NULL DEFAULT '',
           source_run_id TEXT NOT NULL DEFAULT '',
           source_turn_id TEXT NOT NULL DEFAULT '',
           UNIQUE(parent_thread_id, name, direction, message_key)
         );",
    )?;

    if !present_cols.is_empty() && !present_cols.contains("message_key") {
        conn.execute_batch(
            "INSERT OR IGNORE INTO sub_agent_mailbox(
               id,parent_thread_id,name,direction,body,digest,message_key,created_at,delivered_at
             )
             SELECT id,parent_thread_id,name,direction,body,digest,id,created_at,delivered_at
             FROM sub_agent_mailbox_legacy;
             DROP TABLE sub_agent_mailbox_legacy;",
        )?;
    }

    let mut present_after: HashSet<String> = HashSet::new();
    {
        let mut stmt = conn.prepare("PRAGMA table_info(sub_agent_mailbox)")?;
        let mut rows = stmt.query([])?;
        while let Some(row) = rows.next()? {
            let col: String = row.get(1)?;
            present_after.insert(col);
        }
    }
    for (col, ddl) in [
        (
            "tags",
            "ALTER TABLE sub_agent_mailbox ADD COLUMN tags TEXT NOT NULL DEFAULT ''",
        ),
        (
            "wake",
            "ALTER TABLE sub_agent_mailbox ADD COLUMN wake INTEGER NOT NULL DEFAULT 0",
        ),
        (
            "wake_count",
            "ALTER TABLE sub_agent_mailbox ADD COLUMN wake_count INTEGER NOT NULL DEFAULT 0",
        ),
        (
            "source_call_id",
            "ALTER TABLE sub_agent_mailbox ADD COLUMN source_call_id TEXT NOT NULL DEFAULT ''",
        ),
        (
            "source_run_id",
            "ALTER TABLE sub_agent_mailbox ADD COLUMN source_run_id TEXT NOT NULL DEFAULT ''",
        ),
        (
            "source_turn_id",
            "ALTER TABLE sub_agent_mailbox ADD COLUMN source_turn_id TEXT NOT NULL DEFAULT ''",
        ),
    ] {
        if !present_after.contains(col) {
            conn.execute(ddl, [])?;
        }
    }

    conn.execute_batch(
        "CREATE INDEX IF NOT EXISTS sub_agent_mailbox_wake
         ON sub_agent_mailbox(parent_thread_id, direction, delivered_at, wake);
         CREATE TABLE IF NOT EXISTS sub_agent_events (
           id TEXT PRIMARY KEY, parent_thread_id TEXT NOT NULL, name TEXT NOT NULL,
           payload TEXT NOT NULL, event_key TEXT NOT NULL, created_at REAL NOT NULL,
           delivered_at REAL,
           UNIQUE(parent_thread_id, event_key)
         );",
    )?;
    Ok(())
}

pub fn sub_agent_init_db(engine: &DbEngine) -> Result<Value, DbError> {
    if engine.sub_agents_ready.load(Ordering::Acquire) {
        return Ok(json!({ "ok": true, "cached": true }));
    }
    engine.write_tx(|conn| ensure_tables_on_conn(conn))?;
    engine.sub_agents_ready.store(true, Ordering::Release);
    Ok(json!({ "ok": true, "cached": false }))
}

pub fn sub_agent_load(engine: &DbEngine, req: &Value) -> Result<Value, DbError> {
    let parent_tid = req
        .get("parent_thread_id")
        .and_then(|v| v.as_str())
        .ok_or_else(|| DbError::Invalid("parent_thread_id required".into()))?;
    let name = req
        .get("name")
        .and_then(|v| v.as_str())
        .ok_or_else(|| DbError::Invalid("name required".into()))?;
    let raw: Option<String> = engine.read(|conn| {
        conn.query_row(
            "SELECT payload FROM sub_agents WHERE parent_thread_id = ?1 AND name = ?2",
            params![parent_tid, name],
            |r| r.get(0),
        )
        .optional()
        .map_err(DbError::from)
    })?;
    match raw {
        Some(s) => Ok(json!({ "found": true, "record": serde_json::from_str::<Value>(&s)? })),
        None => Ok(json!({ "found": false, "record": Value::Null })),
    }
}

pub fn sub_agent_list(engine: &DbEngine, req: &Value) -> Result<Value, DbError> {
    let parent_tid = req
        .get("parent_thread_id")
        .and_then(|v| v.as_str())
        .ok_or_else(|| DbError::Invalid("parent_thread_id required".into()))?;
    let records = engine.read(|conn| {
        let mut stmt = conn.prepare_cached(
            "SELECT payload FROM sub_agents WHERE parent_thread_id = ?1 ORDER BY name",
        )?;
        let mut rows = stmt.query([parent_tid])?;
        let mut out = Vec::new();
        while let Some(r) = rows.next()? {
            let s: String = r.get(0)?;
            if let Ok(v) = serde_json::from_str::<Value>(&s) {
                out.push(v);
            }
        }
        Ok(out)
    })?;
    Ok(json!({ "records": records }))
}

pub fn sub_agent_list_by_names(engine: &DbEngine, req: &Value) -> Result<Value, DbError> {
    let parent_tid = req
        .get("parent_thread_id")
        .and_then(|v| v.as_str())
        .ok_or_else(|| DbError::Invalid("parent_thread_id required".into()))?;
    let names: Vec<String> = req
        .get("names")
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str().map(str::to_string))
                .collect()
        })
        .unwrap_or_default();
    if names.is_empty() {
        return Ok(json!({ "records": [] }));
    }
    let res = engine.read(|conn| {
        let placeholders = vec!["?"; names.len()].join(",");
        let sql = format!(
            "SELECT payload FROM sub_agents WHERE parent_thread_id = ?1 AND name IN ({placeholders})"
        );
        let mut stmt = conn.prepare(&sql)?;
        let mut p: Vec<&dyn rusqlite::ToSql> = Vec::with_capacity(names.len() + 1);
        p.push(&parent_tid);
        for n in &names {
            p.push(n);
        }
        let mut rows = stmt.query(p.as_slice())?;
        let mut out = Vec::new();
        while let Some(r) = rows.next()? {
            let s: String = r.get(0)?;
            if let Ok(v) = serde_json::from_str::<Value>(&s) {
                out.push(v);
            }
        }
        Ok(out)
    });
    match res {
        Ok(records) => Ok(json!({ "records": records })),
        Err(ref e) if is_no_such_table(e) => Ok(json!({ "records": [] })),
        Err(e) => Err(e),
    }
}

pub fn sub_agent_save(engine: &DbEngine, req: &Value) -> Result<Value, DbError> {
    let parent_tid = req
        .get("parent_thread_id")
        .and_then(|v| v.as_str())
        .ok_or_else(|| DbError::Invalid("parent_thread_id required".into()))?;
    let name = req
        .get("name")
        .and_then(|v| v.as_str())
        .ok_or_else(|| DbError::Invalid("name required".into()))?;
    let record = req
        .get("record")
        .ok_or_else(|| DbError::Invalid("record required".into()))?;
    let payload_str = serde_json::to_string(record)?;
    engine.write_tx(|conn| {
        conn.execute(
            "INSERT INTO sub_agents(parent_thread_id, name, payload) VALUES(?1, ?2, ?3)
             ON CONFLICT(parent_thread_id, name) DO UPDATE SET payload = excluded.payload",
            params![parent_tid, name, payload_str],
        )?;
        Ok(())
    })?;
    Ok(json!({ "ok": true }))
}

pub fn sub_agent_save_if_current(engine: &DbEngine, req: &Value) -> Result<Value, DbError> {
    let parent_tid = req
        .get("parent_thread_id")
        .and_then(|v| v.as_str())
        .ok_or_else(|| DbError::Invalid("parent_thread_id required".into()))?;
    let name = req
        .get("name")
        .and_then(|v| v.as_str())
        .ok_or_else(|| DbError::Invalid("name required".into()))?;
    let token = req.get("token").and_then(|v| v.as_str()).unwrap_or("");
    let record = req
        .get("record")
        .ok_or_else(|| DbError::Invalid("record required".into()))?;
    let payload_str = serde_json::to_string(record)?;
    let changed = engine.write_tx(|conn| {
        let n = conn.execute(
            "UPDATE sub_agents SET payload = ?1
             WHERE parent_thread_id = ?2 AND name = ?3
             AND COALESCE(json_extract(payload, '$.execution_token'), '') = ?4
             AND json_extract(payload, '$.status') NOT IN ('terminated','closed','deleted')",
            params![payload_str, parent_tid, name, token],
        )?;
        Ok(n)
    })?;
    Ok(json!({ "changed": changed > 0 }))
}

pub fn sub_agent_delete_member(engine: &DbEngine, req: &Value) -> Result<Value, DbError> {
    let parent_tid = req
        .get("parent_thread_id")
        .and_then(|v| v.as_str())
        .ok_or_else(|| DbError::Invalid("parent_thread_id required".into()))?;
    let name = req
        .get("name")
        .and_then(|v| v.as_str())
        .ok_or_else(|| DbError::Invalid("name required".into()))?;
    engine.write_tx(|conn| {
        conn.execute(
            "DELETE FROM sub_agents WHERE parent_thread_id = ?1 AND name = ?2",
            params![parent_tid, name],
        )?;
        conn.execute(
            "DELETE FROM sub_agent_events WHERE parent_thread_id = ?1 AND name = ?2",
            params![parent_tid, name],
        )?;
        conn.execute(
            "DELETE FROM sub_agent_mailbox WHERE parent_thread_id = ?1 AND name = ?2",
            params![parent_tid, name],
        )?;
        Ok(())
    })?;
    Ok(json!({ "ok": true }))
}

pub fn sub_agent_recover_mark_interrupted(
    engine: &DbEngine,
    req: &Value,
) -> Result<Value, DbError> {
    let parent_tid = req
        .get("parent_thread_id")
        .and_then(|v| v.as_str())
        .ok_or_else(|| DbError::Invalid("parent_thread_id required".into()))?;
    let live_names: HashSet<String> = req
        .get("live_names")
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str().map(str::to_string))
                .collect()
        })
        .unwrap_or_default();
    let now = req
        .get("now")
        .and_then(|v| v.as_f64())
        .unwrap_or_else(now_unix_secs);

    let updated = engine.write_tx(|conn| {
        let mut stmt = conn
            .prepare_cached("SELECT name, payload FROM sub_agents WHERE parent_thread_id = ?1")?;
        let mut rows = stmt.query([parent_tid])?;
        let mut to_update: Vec<(String, Value)> = Vec::new();
        while let Some(r) = rows.next()? {
            let name: String = r.get(0)?;
            if live_names.contains(&name) {
                continue;
            }
            let raw: String = r.get(1)?;
            let Ok(mut payload) = serde_json::from_str::<Map<String, Value>>(&raw) else {
                continue;
            };
            if payload.get("status").and_then(|v| v.as_str()) != Some("running") {
                continue;
            }
            payload.insert("status".into(), json!("interrupted"));
            payload.insert("completed_at".into(), json!(now));
            if let Some(started) = payload.get("started_at").and_then(|v| v.as_f64()) {
                if started != 0.0 {
                    payload.insert(
                        "elapsed_ms".into(),
                        json!(((now - started) * 1000.0) as i64),
                    );
                }
            }
            to_update.push((name, Value::Object(payload)));
        }
        drop(rows);
        let mut out = Vec::with_capacity(to_update.len());
        for (name, payload_val) in to_update {
            let s = serde_json::to_string(&payload_val)?;
            conn.execute(
                "UPDATE sub_agents SET payload = ?1 WHERE parent_thread_id = ?2 AND name = ?3",
                params![s, parent_tid, name],
            )?;
            out.push(payload_val);
        }
        Ok(out)
    })?;
    Ok(json!({ "interrupted": updated }))
}

pub fn sub_agent_mail_insert(engine: &DbEngine, req: &Value) -> Result<Value, DbError> {
    let parent_tid = req
        .get("parent_thread_id")
        .and_then(|v| v.as_str())
        .ok_or_else(|| DbError::Invalid("parent_thread_id required".into()))?;
    let name = req
        .get("name")
        .and_then(|v| v.as_str())
        .ok_or_else(|| DbError::Invalid("name required".into()))?;
    let direction = req
        .get("direction")
        .and_then(|v| v.as_str())
        .ok_or_else(|| DbError::Invalid("direction required".into()))?;
    let body = req.get("body").and_then(|v| v.as_str()).unwrap_or("");
    let message_key = req
        .get("message_key")
        .and_then(|v| v.as_str())
        .ok_or_else(|| DbError::Invalid("message_key required".into()))?;
    let tags = req.get("tags").and_then(|v| v.as_str()).unwrap_or("");
    let wake = if req.get("wake").and_then(|v| v.as_i64()).unwrap_or(0) != 0 {
        1_i64
    } else {
        0_i64
    };
    let source_call_id = req
        .get("source_call_id")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let source_run_id = req
        .get("source_run_id")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let source_turn_id = req
        .get("source_turn_id")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let fetch_id = req
        .get("fetch_id")
        .and_then(|v| v.as_bool())
        .unwrap_or(false);

    let digest = sha256_hex(body.as_bytes());
    let new_id = next_hex_id();
    let now = req
        .get("now")
        .and_then(|v| v.as_f64())
        .unwrap_or_else(now_unix_secs);

    let (inserted, message_id) = engine.write_tx(|conn| {
        let count = conn.execute(
            "INSERT OR IGNORE INTO sub_agent_mailbox
             (id,parent_thread_id,name,direction,body,digest,message_key,created_at,tags,wake,source_call_id,source_run_id,source_turn_id)
             VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13)",
            params![
                new_id,
                parent_tid,
                name,
                direction,
                body,
                digest,
                message_key,
                now,
                tags,
                wake,
                source_call_id,
                source_run_id,
                source_turn_id,
            ],
        )?;
        let msg_id = if count > 0 {
            Some(new_id.clone())
        } else if fetch_id {
            conn.query_row(
                "SELECT id FROM sub_agent_mailbox WHERE parent_thread_id=?1 AND name=?2 AND direction=?3 AND message_key=?4",
                params![parent_tid, name, direction, message_key],
                |r| r.get::<_, String>(0),
            )
            .optional()?
        } else {
            None
        };
        Ok((count > 0, msg_id))
    })?;
    Ok(json!({ "inserted": inserted, "message_id": message_id }))
}

pub fn sub_agent_mail_mark_delivered_by_key(
    engine: &DbEngine,
    req: &Value,
) -> Result<Value, DbError> {
    let parent_tid = req
        .get("parent_thread_id")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let name = req.get("name").and_then(|v| v.as_str()).unwrap_or("");
    let direction = req.get("direction").and_then(|v| v.as_str()).unwrap_or("");
    let message_key = req
        .get("message_key")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let now = req
        .get("now")
        .and_then(|v| v.as_f64())
        .unwrap_or_else(now_unix_secs);
    engine.write_tx(|conn| {
        conn.execute(
            "UPDATE sub_agent_mailbox SET delivered_at=?1 WHERE parent_thread_id=?2 AND name=?3 AND direction=?4 AND message_key=?5",
            params![now, parent_tid, name, direction, message_key],
        )?;
        Ok(())
    })?;
    Ok(json!({ "ok": true }))
}

pub fn sub_agent_pending_guidance(engine: &DbEngine, req: &Value) -> Result<Value, DbError> {
    let parent_tid = req
        .get("parent_thread_id")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let name = req.get("name").and_then(|v| v.as_str()).unwrap_or("");
    let rows = engine.read(|conn| {
        let mut stmt = conn.prepare_cached(
            "SELECT id,body,created_at,source_call_id,source_run_id,source_turn_id
             FROM sub_agent_mailbox
             WHERE parent_thread_id=?1 AND name=?2 AND direction='parent_to_child' AND delivered_at IS NULL
             ORDER BY created_at, id",
        )?;
        let mut r = stmt.query(params![parent_tid, name])?;
        let mut out = Vec::new();
        while let Some(row) = r.next()? {
            out.push(json!({
                "id": row.get::<_, String>(0)?,
                "body": row.get::<_, String>(1)?,
                "created_at": row.get::<_, f64>(2)?,
                "source_call_id": row.get::<_, String>(3)?,
                "source_run_id": row.get::<_, String>(4)?,
                "source_turn_id": row.get::<_, String>(5)?,
            }));
        }
        Ok(out)
    })?;
    Ok(json!({ "rows": rows }))
}

pub fn sub_agent_ack_guidance(engine: &DbEngine, req: &Value) -> Result<Value, DbError> {
    let parent_tid = req
        .get("parent_thread_id")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let name = req.get("name").and_then(|v| v.as_str()).unwrap_or("");
    let ids: Vec<String> = req
        .get("ids")
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str().filter(|s| !s.is_empty()).map(str::to_string))
                .collect()
        })
        .unwrap_or_default();
    if ids.is_empty() {
        return Ok(json!({ "ok": true }));
    }
    let now = req
        .get("now")
        .and_then(|v| v.as_f64())
        .unwrap_or_else(now_unix_secs);
    engine.write_tx(|conn| {
        let mut stmt = conn.prepare_cached(
            "UPDATE sub_agent_mailbox SET delivered_at = COALESCE(delivered_at, ?1)
             WHERE id = ?2 AND parent_thread_id = ?3 AND name = ?4 AND direction = 'parent_to_child'",
        )?;
        for id in &ids {
            stmt.execute(params![now, id, parent_tid, name])?;
        }
        Ok(())
    })?;
    Ok(json!({ "ok": true }))
}

pub fn sub_agent_drain_parent_mailbox(engine: &DbEngine, req: &Value) -> Result<Value, DbError> {
    let parent_tid = req
        .get("parent_thread_id")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let mark_delivered = req
        .get("mark_delivered")
        .and_then(|v| v.as_bool())
        .unwrap_or(true);
    let now = req
        .get("now")
        .and_then(|v| v.as_f64())
        .unwrap_or_else(now_unix_secs);

    let res = if !mark_delivered {
        engine.read(|conn| {
            let mut stmt = conn.prepare_cached(
                "SELECT id,name,body,created_at FROM sub_agent_mailbox
                 WHERE parent_thread_id=?1 AND direction='child_to_parent' AND delivered_at IS NULL
                 ORDER BY created_at, id",
            )?;
            let mut r = stmt.query([parent_tid])?;
            let mut out = Vec::new();
            while let Some(row) = r.next()? {
                out.push(json!({
                    "id": row.get::<_, String>(0)?,
                    "name": row.get::<_, String>(1)?,
                    "body": row.get::<_, String>(2)?,
                    "created_at": row.get::<_, f64>(3)?,
                }));
            }
            Ok(out)
        })
    } else {
        engine.write_tx(|conn| {
            let mut stmt = conn.prepare_cached(
                "SELECT id,name,body,created_at FROM sub_agent_mailbox
                 WHERE parent_thread_id=?1 AND direction='child_to_parent' AND delivered_at IS NULL
                 ORDER BY created_at, id",
            )?;
            let mut r = stmt.query([parent_tid])?;
            let mut out = Vec::new();
            let mut ids = Vec::new();
            while let Some(row) = r.next()? {
                let id: String = row.get(0)?;
                ids.push(id.clone());
                out.push(json!({
                    "id": id,
                    "name": row.get::<_, String>(1)?,
                    "body": row.get::<_, String>(2)?,
                    "created_at": row.get::<_, f64>(3)?,
                }));
            }
            drop(r);
            if !ids.is_empty() {
                let mut upd = conn.prepare_cached(
                    "UPDATE sub_agent_mailbox SET delivered_at = ?1 WHERE id = ?2",
                )?;
                for id in ids {
                    upd.execute(params![now, id])?;
                }
            }
            Ok(out)
        })
    };
    match res {
        Ok(rows) => Ok(json!({ "rows": rows })),
        Err(ref e) if is_no_such_table(e) => Ok(json!({ "rows": [] })),
        Err(e) => Err(e),
    }
}

pub fn sub_agent_ack_parent_mailbox(engine: &DbEngine, req: &Value) -> Result<Value, DbError> {
    let parent_tid = req
        .get("parent_thread_id")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let ids: Vec<String> = req
        .get("ids")
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str().filter(|s| !s.is_empty()).map(str::to_string))
                .collect()
        })
        .unwrap_or_default();
    if ids.is_empty() {
        return Ok(json!({ "ok": true }));
    }
    let now = req
        .get("now")
        .and_then(|v| v.as_f64())
        .unwrap_or_else(now_unix_secs);
    engine.write_tx(|conn| {
        let placeholders = vec!["?"; ids.len()].join(",");
        let sql = format!(
            "UPDATE sub_agent_mailbox SET delivered_at = ?1
             WHERE parent_thread_id = ?2 AND direction = 'child_to_parent'
             AND delivered_at IS NULL AND id IN ({placeholders})"
        );
        let mut p: Vec<&dyn rusqlite::ToSql> = Vec::with_capacity(ids.len() + 2);
        p.push(&now);
        p.push(&parent_tid);
        for id in &ids {
            p.push(id);
        }
        conn.execute(&sql, p.as_slice())?;
        Ok(())
    })?;
    Ok(json!({ "ok": true }))
}

pub fn sub_agent_ack_parent_guidance(engine: &DbEngine, req: &Value) -> Result<Value, DbError> {
    let parent_tid = req
        .get("parent_thread_id")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let guidance_ids: HashSet<String> = req
        .get("guidance_ids")
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str().filter(|s| !s.is_empty()).map(str::to_string))
                .collect()
        })
        .unwrap_or_default();
    if guidance_ids.is_empty() {
        return Ok(json!({ "ok": true }));
    }
    let now = req
        .get("now")
        .and_then(|v| v.as_f64())
        .unwrap_or_else(now_unix_secs);
    let res = engine.write_tx(|conn| {
        let mut stmt = conn.prepare_cached(
            "SELECT id,name,message_key FROM sub_agent_mailbox
             WHERE parent_thread_id=?1 AND direction='child_to_parent' AND delivered_at IS NULL",
        )?;
        let mut rows = stmt.query([parent_tid])?;
        let mut matched = Vec::new();
        while let Some(r) = rows.next()? {
            let id: String = r.get(0)?;
            let name: String = r.get(1)?;
            let key: String = r.get(2)?;
            let composite = format!("sub-agent:{parent_tid}:{name}:{key}");
            if guidance_ids.contains(&composite) {
                matched.push(id);
            }
        }
        drop(rows);
        if !matched.is_empty() {
            let mut upd = conn.prepare_cached(
                "UPDATE sub_agent_mailbox SET delivered_at=?1
                 WHERE parent_thread_id=?2 AND direction='child_to_parent' AND delivered_at IS NULL AND id=?3",
            )?;
            for id in matched {
                upd.execute(params![now, parent_tid, id])?;
            }
        }
        Ok(())
    });
    match res {
        Ok(()) => Ok(json!({ "ok": true })),
        Err(ref e) if is_no_such_table(e) => Ok(json!({ "ok": true })),
        Err(e) => Err(e),
    }
}

pub fn sub_agent_pending_event_count(engine: &DbEngine, req: &Value) -> Result<Value, DbError> {
    let parent_tid = req
        .get("parent_thread_id")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let n: i64 = engine.read(|conn| {
        conn.query_row(
            "SELECT COUNT(*) FROM sub_agent_events WHERE parent_thread_id = ?1 AND delivered_at IS NULL",
            [parent_tid],
            |r| r.get(0),
        )
        .map_err(DbError::from)
    })?;
    Ok(json!({ "count": n }))
}

pub fn sub_agent_write_event(engine: &DbEngine, req: &Value) -> Result<Value, DbError> {
    let parent_tid = req
        .get("parent_thread_id")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let name = req.get("name").and_then(|v| v.as_str()).unwrap_or("");
    let event_key = req.get("event_key").and_then(|v| v.as_str()).unwrap_or("");
    let payload = req
        .get("payload")
        .ok_or_else(|| DbError::Invalid("payload required".into()))?;
    let payload_str = serde_json::to_string(payload)?;
    let event_id = next_hex_id();
    let now = req
        .get("now")
        .and_then(|v| v.as_f64())
        .unwrap_or_else(now_unix_secs);
    let inserted = engine.write_tx(|conn| {
        let count = conn.execute(
            "INSERT OR IGNORE INTO sub_agent_events(id,parent_thread_id,name,payload,event_key,created_at)
             VALUES(?1,?2,?3,?4,?5,?6)",
            params![event_id, parent_tid, name, payload_str, event_key, now],
        )?;
        Ok(count > 0)
    })?;
    Ok(json!({ "event_id": if inserted { event_id } else { String::new() } }))
}

pub fn sub_agent_drain_member_events(engine: &DbEngine, req: &Value) -> Result<Value, DbError> {
    let parent_tid = req
        .get("parent_thread_id")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let now = req
        .get("now")
        .and_then(|v| v.as_f64())
        .unwrap_or_else(now_unix_secs);
    let events = engine.write_tx(|conn| {
        let mut stmt = conn.prepare_cached(
            "SELECT id,payload FROM sub_agent_events
             WHERE parent_thread_id=?1 AND delivered_at IS NULL ORDER BY created_at, id",
        )?;
        let mut rows = stmt.query([parent_tid])?;
        let mut out = Vec::new();
        let mut ids = Vec::new();
        while let Some(r) = rows.next()? {
            let id: String = r.get(0)?;
            let raw: String = r.get(1)?;
            ids.push(id);
            if let Ok(Value::Object(obj)) = serde_json::from_str::<Value>(&raw) {
                out.push(Value::Object(obj));
            }
        }
        drop(rows);
        if !ids.is_empty() {
            let mut upd =
                conn.prepare_cached("UPDATE sub_agent_events SET delivered_at=?1 WHERE id=?2")?;
            for id in ids {
                upd.execute(params![now, id])?;
            }
        }
        Ok(out)
    })?;
    Ok(json!({ "events": events }))
}

pub fn sub_agent_list_threads_with_pending_wakes(engine: &DbEngine) -> Result<Value, DbError> {
    let res = engine.read(|conn| {
        let mut stmt = conn.prepare_cached(
            "SELECT DISTINCT parent_thread_id FROM sub_agent_mailbox
             WHERE direction='child_to_parent' AND delivered_at IS NULL AND wake=1",
        )?;
        let mut rows = stmt.query([])?;
        let mut out = Vec::new();
        while let Some(r) = rows.next()? {
            let tid: String = r.get(0)?;
            if !tid.trim().is_empty() {
                out.push(Value::String(tid));
            }
        }
        Ok(out)
    });
    match res {
        Ok(threads) => Ok(json!({ "threads": threads })),
        Err(ref e) if is_no_such_table(e) => Ok(json!({ "threads": [] })),
        Err(e) => Err(e),
    }
}

pub fn sub_agent_peek_wake_messages(engine: &DbEngine, req: &Value) -> Result<Value, DbError> {
    let parent_tid = req
        .get("parent_thread_id")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let res = engine.read(|conn| {
        let mut stmt = conn.prepare_cached(
            "SELECT id,name,body,tags,wake_count,created_at FROM sub_agent_mailbox
             WHERE parent_thread_id=?1 AND direction='child_to_parent' AND delivered_at IS NULL AND wake=1
             ORDER BY created_at, id",
        )?;
        let mut rows = stmt.query([parent_tid])?;
        let mut out = Vec::new();
        while let Some(r) = r_next_row(&mut rows)? {
            out.push(json!({
                "id": r.0,
                "name": r.1,
                "body": r.2,
                "tags": r.3,
                "wake_count": r.4,
                "created_at": r.5,
            }));
        }
        Ok(out)
    });
    match res {
        Ok(messages) => Ok(json!({ "messages": messages })),
        Err(ref e) if is_no_such_table(e) => Ok(json!({ "messages": [] })),
        Err(e) => Err(e),
    }
}

fn r_next_row(
    rows: &mut rusqlite::Rows<'_>,
) -> Result<Option<(String, String, String, String, i64, f64)>, DbError> {
    let Some(r) = rows.next()? else {
        return Ok(None);
    };
    Ok(Some((
        r.get::<_, String>(0)?,
        r.get::<_, String>(1)?,
        r.get::<_, String>(2)?,
        r.get::<_, Option<String>>(3)?.unwrap_or_default(),
        r.get::<_, Option<i64>>(4)?.unwrap_or(0),
        r.get::<_, Option<f64>>(5)?.unwrap_or(0.0),
    )))
}

pub fn sub_agent_bump_wake_counts(engine: &DbEngine, req: &Value) -> Result<Value, DbError> {
    let parent_tid = req
        .get("parent_thread_id")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let ids: Vec<String> = req
        .get("ids")
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str().filter(|s| !s.is_empty()).map(str::to_string))
                .collect()
        })
        .unwrap_or_default();
    if ids.is_empty() {
        return Ok(json!({ "max_wake_count": 0 }));
    }
    let max_val = engine.write_tx(|conn| {
        let placeholders = vec!["?"; ids.len()].join(",");
        let upd_sql = format!(
            "UPDATE sub_agent_mailbox SET wake_count = wake_count + 1
             WHERE parent_thread_id = ?1 AND id IN ({placeholders})"
        );
        let mut p: Vec<&dyn rusqlite::ToSql> = Vec::with_capacity(ids.len() + 1);
        p.push(&parent_tid);
        for id in &ids {
            p.push(id);
        }
        conn.execute(&upd_sql, p.as_slice())?;

        let sel_sql = format!(
            "SELECT MAX(wake_count) FROM sub_agent_mailbox WHERE parent_thread_id = ?1 AND id IN ({placeholders})"
        );
        let mx: Option<i64> = conn.query_row(&sel_sql, p.as_slice(), |r| r.get(0))?;
        Ok(mx.unwrap_or(0))
    })?;
    Ok(json!({ "max_wake_count": max_val }))
}

fn format_member_event_rust(payload: &Map<String, Value>) -> String {
    let event = payload
        .get("event")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .unwrap_or("member_update");
    if event == "members_still_running" {
        let members = payload
            .get("members")
            .and_then(|v| v.as_array())
            .cloned()
            .unwrap_or_default();
        let parts: Vec<String> = members
            .iter()
            .filter_map(|m| m.as_object())
            .map(|m| {
                let name = m
                    .get("name")
                    .and_then(|v| v.as_str())
                    .filter(|s| !s.is_empty())
                    .unwrap_or("?");
                let st = m
                    .get("status")
                    .and_then(|v| v.as_str())
                    .filter(|s| !s.is_empty())
                    .unwrap_or("running");
                let ms = m.get("running_ms").and_then(|v| v.as_f64()).unwrap_or(0.0);
                format!("{name}（{st}，已运行 {:.0} 秒）", ms / 1000.0)
            })
            .collect();
        let detail = parts.join("；");
        let suffix = if payload
            .get("lease_timed_out")
            .and_then(|v| v.as_bool())
            .unwrap_or(false)
        {
            "（本次等待已到租约上限）"
        } else {
            ""
        };
        return format!(
            "- 成员仍在运行{suffix}：{}。你可以继续等下一个事件，也可以先推进不依赖他们的工作。",
            if detail.is_empty() { "未知" } else { &detail }
        );
    }
    let name = payload
        .get("name")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .unwrap_or("(未署名成员)");
    let elapsed_text = match payload.get("elapsed_ms").and_then(|v| v.as_f64()) {
        Some(ms) if ms != 0.0 => format!("，用时 {:.0} 秒", ms / 1000.0),
        _ => String::new(),
    };
    let status_fallback = payload
        .get("status")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .unwrap_or(event);
    let label = match event {
        "member_finished" => "已完成",
        "member_paused" => "已暂停（在等确认或补充信息）",
        "member_failed" => "已失败",
        "member_closed" => "已关闭",
        "member_interrupted" => "已被中断",
        _ => status_fallback,
    };
    let summary = payload
        .get("summary")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim();
    let detail = payload
        .get("detail")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim();
    let mut tail = if !summary.is_empty() {
        format!("：{summary}")
    } else {
        String::new()
    };
    if !detail.is_empty() && detail != summary {
        tail.push_str(&format!("（原因：{detail}）"));
    }
    format!("- {name} {label}{elapsed_text}{tail}")
}

pub fn sub_agent_migrate_pending_member_events_to_wake(
    engine: &DbEngine,
    req: &Value,
) -> Result<Value, DbError> {
    let now = req
        .get("now")
        .and_then(|v| v.as_f64())
        .unwrap_or_else(now_unix_secs);
    let res = engine.write_tx(|conn| {
        let mut stmt = conn.prepare_cached(
            "SELECT id,parent_thread_id,name,payload,event_key FROM sub_agent_events
             WHERE delivered_at IS NULL ORDER BY created_at, id",
        )?;
        let mut rows = stmt.query([])?;
        let mut items: Vec<(String, String, String, String, String)> = Vec::new();
        while let Some(r) = rows.next()? {
            items.push((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?, r.get(4)?));
        }
        drop(rows);
        let mut migrated = 0_i64;
        for (id, ptid, name, raw_payload, event_key) in items {
            let parsed = serde_json::from_str::<Value>(&raw_payload).unwrap_or_else(|_| json!({}));
            let Some(obj) = parsed.as_object() else {
                continue;
            };
            let event = obj.get("event").and_then(|v| v.as_str()).unwrap_or("");
            if event.is_empty() {
                continue;
            }
            let body = format_member_event_rust(obj);
            let digest = sha256_hex(body.as_bytes());
            let mail_id = next_hex_id();
            let msg_key = format!("wake:{event_key}");
            let inserted = conn.execute(
                "INSERT OR IGNORE INTO sub_agent_mailbox
                 (id,parent_thread_id,name,direction,body,digest,message_key,created_at,tags,wake)
                 VALUES(?1,?2,?3,'child_to_parent',?4,?5,?6,?7,?8,1)",
                params![mail_id, ptid, name, body, digest, msg_key, now, event],
            )?;
            if inserted > 0 {
                migrated += 1;
            }
            conn.execute(
                "UPDATE sub_agent_events SET delivered_at=?1 WHERE id=?2",
                params![now, id],
            )?;
        }
        Ok(migrated)
    });
    match res {
        Ok(migrated) => Ok(json!({ "migrated": migrated })),
        Err(ref e) if is_no_such_table(e) => Ok(json!({ "migrated": 0 })),
        Err(e) => Err(e),
    }
}

pub fn sub_agent_auto_release_unanswered(engine: &DbEngine, req: &Value) -> Result<Value, DbError> {
    let parent_tid = req
        .get("parent_thread_id")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let limit = req.get("limit").and_then(|v| v.as_i64()).unwrap_or(2);
    let now = req
        .get("now")
        .and_then(|v| v.as_f64())
        .unwrap_or_else(now_unix_secs);
    let body = "未获答复，按合理默认继续。";
    let digest = sha256_hex(body.as_bytes());
    let res = engine.write_tx(|conn| {
        let mut stmt = conn.prepare_cached(
            "SELECT id,name FROM sub_agent_mailbox
             WHERE parent_thread_id=?1 AND direction='child_to_parent'
             AND tags='question' AND wake=1 AND delivered_at IS NOT NULL AND wake_count>=?2",
        )?;
        let mut rows = stmt.query(params![parent_tid, limit])?;
        let mut candidates: Vec<(String, String)> = Vec::new();
        while let Some(r) = rows.next()? {
            candidates.push((r.get(0)?, r.get(1)?));
        }
        drop(rows);
        let mut released = Vec::with_capacity(candidates.len());
        for (qid, name) in candidates {
            let msg_id = next_hex_id();
            let msg_key = format!("auto-release:{qid}");
            conn.execute(
                "INSERT OR IGNORE INTO sub_agent_mailbox
                 (id,parent_thread_id,name,direction,body,digest,message_key,created_at,tags,wake)
                 VALUES(?1,?2,?3,'parent_to_child',?4,?5,?6,?7,'release',0)",
                params![msg_id, parent_tid, name, body, digest, msg_key, now],
            )?;
            conn.execute("UPDATE sub_agent_mailbox SET wake=0 WHERE id=?1", [qid])?;
            released.push(Value::String(name));
        }
        Ok(released)
    });
    match res {
        Ok(released) => Ok(json!({ "released": released })),
        Err(ref e) if is_no_such_table(e) => Ok(json!({ "released": [] })),
        Err(e) => Err(e),
    }
}

pub fn sub_agent_peek_member_events(engine: &DbEngine, req: &Value) -> Result<Value, DbError> {
    let parent_tid = req
        .get("parent_thread_id")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let res = engine.read(|conn| {
        let mut stmt = conn.prepare_cached(
            "SELECT id,payload,event_key FROM sub_agent_events
             WHERE parent_thread_id=?1 AND delivered_at IS NULL ORDER BY created_at, id",
        )?;
        let mut rows = stmt.query([parent_tid])?;
        let mut out = Vec::new();
        while let Some(r) = rows.next()? {
            let id: String = r.get(0)?;
            let raw: String = r.get(1)?;
            let event_key: String = r.get(2)?;
            let payload: Value = serde_json::from_str::<Value>(&raw)
                .ok()
                .filter(|v| v.is_object())
                .unwrap_or_else(|| json!({}));
            out.push(json!({
                "id": id,
                "event_key": event_key,
                "payload": payload,
            }));
        }
        Ok(out)
    });
    match res {
        Ok(events) => Ok(json!({ "events": events })),
        Err(ref e) if is_no_such_table(e) => Ok(json!({ "events": [] })),
        Err(e) => Err(e),
    }
}

pub fn sub_agent_mark_member_events_delivered(
    engine: &DbEngine,
    req: &Value,
) -> Result<Value, DbError> {
    let ids: Vec<String> = req
        .get("ids")
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str().filter(|s| !s.is_empty()).map(str::to_string))
                .collect()
        })
        .unwrap_or_default();
    if ids.is_empty() {
        return Ok(json!({ "ok": true }));
    }
    let now = req
        .get("now")
        .and_then(|v| v.as_f64())
        .unwrap_or_else(now_unix_secs);
    let res = engine.write_tx(|conn| {
        let placeholders = vec!["?"; ids.len()].join(",");
        let sql = format!(
            "UPDATE sub_agent_events SET delivered_at=?1 WHERE delivered_at IS NULL AND id IN ({placeholders})"
        );
        let mut p: Vec<&dyn rusqlite::ToSql> = Vec::with_capacity(ids.len() + 1);
        p.push(&now);
        for id in &ids {
            p.push(id);
        }
        conn.execute(&sql, p.as_slice())?;
        Ok(())
    });
    match res {
        Ok(()) => Ok(json!({ "ok": true })),
        Err(ref e) if is_no_such_table(e) => Ok(json!({ "ok": true })),
        Err(e) => Err(e),
    }
}
