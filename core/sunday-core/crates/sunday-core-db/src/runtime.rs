//! Multi-session and multi-agent concurrent runtime state, history, agent runs, and event reads.
//!
//! user:“加载/切换/多会话多 agent 同时读写”+(把多会话运行时状态、历史消息追加/分页、子代理运行态与事件查询全部落到 Rust 连接池与串行写事务上)。

use crate::pool::{DbEngine, DbError};
use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Map, Value};

fn parse_json_obj(raw: Option<String>) -> Value {
    match raw {
        Some(ref s) if !s.is_empty() => serde_json::from_str(s).unwrap_or_else(|_| json!({})),
        _ => json!({}),
    }
}

fn parse_json_arr(raw: Option<String>) -> Value {
    match raw {
        Some(ref s) if !s.is_empty() => serde_json::from_str(s).unwrap_or_else(|_| json!([])),
        _ => json!([]),
    }
}

fn append_history_rows_tx(
    conn: &Connection,
    session_id: &str,
    messages: &[Value],
    now_str: &str,
) -> Result<Vec<i64>, DbError> {
    let mut max_seq: i64 = conn.query_row(
        "SELECT COALESCE(MAX(seq), 0) FROM core_history_entries WHERE thread_id = ?1",
        [session_id],
        |r| r.get(0),
    )?;
    if max_seq == 0 {
        let legacy_raw: Option<String> = conn
            .query_row(
                "SELECT history_json FROM core_runtime_sessions WHERE thread_id = ?1",
                [session_id],
                |r| r.get(0),
            )
            .optional()?
            .flatten();
        if let Some(raw) = legacy_raw {
            if let Ok(Value::Array(legacy_msgs)) = serde_json::from_str::<Value>(&raw) {
                if !legacy_msgs.is_empty() {
                    let mut insert_stmt = conn.prepare_cached(
                        "INSERT INTO core_history_entries (thread_id, seq, revision, message_json, created_at) \
                         VALUES (?1, ?2, ?3, ?4, ?5)",
                    )?;
                    for (idx, mut msg) in legacy_msgs.into_iter().enumerate() {
                        let seq = (idx as i64) + 1;
                        if let Some(obj) = msg.as_object_mut() {
                            let meta = obj
                                .entry("metadata".to_string())
                                .or_insert_with(|| json!({}));
                            if let Some(meta_obj) = meta.as_object_mut() {
                                meta_obj.insert("history_seq".into(), json!(seq));
                            }
                        }
                        let msg_str = serde_json::to_string(&msg)?;
                        insert_stmt.execute(params![session_id, seq, seq, msg_str, now_str])?;
                    }
                    max_seq = conn.query_row(
                        "SELECT COALESCE(MAX(seq), 0) FROM core_history_entries WHERE thread_id = ?1",
                        [session_id],
                        |r| r.get(0),
                    )?;
                    conn.execute(
                        "UPDATE core_runtime_sessions SET history_json = '[]' WHERE thread_id = ?1",
                        [session_id],
                    )?;
                }
            }
        }
    }

    let mut assigned = Vec::with_capacity(messages.len());
    let mut insert_stmt = conn.prepare_cached(
        "INSERT INTO core_history_entries (thread_id, seq, revision, message_json, created_at) \
         VALUES (?1, ?2, ?3, ?4, ?5)",
    )?;
    for msg in messages {
        max_seq += 1;
        let mut tagged = msg.clone();
        if let Some(obj) = tagged.as_object_mut() {
            let meta = obj
                .entry("metadata".to_string())
                .or_insert_with(|| json!({}));
            if let Some(meta_obj) = meta.as_object_mut() {
                meta_obj
                    .entry("history_seq".to_string())
                    .or_insert_with(|| json!(max_seq));
            }
        }
        let msg_str = serde_json::to_string(&tagged)?;
        insert_stmt.execute(params![session_id, max_seq, max_seq, msg_str, now_str])?;
        assigned.push(max_seq);
    }
    Ok(assigned)
}

fn append_runtime_sync_change_tx(
    conn: &Connection,
    session_id: &str,
    state_payload: &Value,
    pending_payload: &Value,
    workspace_id: &str,
    change_id: &str,
    updated_iso: &str,
    now_str: &str,
) -> Result<(), DbError> {
    let index_ready: bool = conn
        .query_row(
            "SELECT 1 FROM sqlite_master WHERE type='index' AND name='idx_core_sync_changes_entity'",
            [],
            |r| r.get::<_, i64>(0),
        )
        .is_ok();
    if index_ready {
        conn.execute(
            "DELETE FROM core_sync_changes WHERE entity_type = 'runtime' AND entity_id = ?1",
            [session_id],
        )?;
    }
    let mut entity = Map::new();
    entity.insert("thread_id".into(), json!(session_id));
    if let Some(obj) = state_payload.as_object() {
        for (k, v) in obj {
            entity.insert(k.clone(), v.clone());
        }
    }
    if let Some(obj) = pending_payload.as_object() {
        for (k, v) in obj {
            entity.insert(k.clone(), v.clone());
        }
    }
    entity.insert("updated_at".into(), json!(updated_iso));
    let entity_str = serde_json::to_string(&Value::Object(entity))?;
    conn.execute(
        "INSERT INTO core_sync_changes \
         (change_id, workspace_id, entity_type, event_type, operation, entity_id, thread_id, revision, entity_json, created_at) \
         VALUES (?1, ?2, 'runtime', 'runtime.upsert', 'upsert', ?3, ?4, 0, ?5, ?6)",
        params![change_id, workspace_id, session_id, session_id, entity_str, now_str],
    )?;
    Ok(())
}

pub fn runtime_get(engine: &DbEngine, session_id: &str) -> Result<Value, DbError> {
    engine.read(|conn| {
        let mut stmt = conn.prepare_cached(
            "SELECT revision, runtime_state_json, pending_approval_json, COALESCE(last_event_seq, 0) \
             FROM core_runtime_sessions WHERE thread_id = ?1",
        )?;
        let mut rows = stmt.query([session_id])?;
        if let Some(row) = rows.next()? {
            let revision: i64 = row.get(0)?;
            let state_raw: Option<String> = row.get(1)?;
            let pending_raw: Option<String> = row.get(2)?;
            let last_event_seq: i64 = row.get(3)?;
            Ok(json!({
                "found": true,
                "thread_id": session_id,
                "revision": revision,
                "runtime_state_json": parse_json_obj(state_raw),
                "pending_approval_json": parse_json_obj(pending_raw),
                "last_event_seq": last_event_seq,
            }))
        } else {
            Ok(json!({ "found": false }))
        }
    })
}

pub fn runtime_save(engine: &DbEngine, req: &Value) -> Result<Value, DbError> {
    let session_id = req
        .get("session_id")
        .and_then(|v| v.as_str())
        .ok_or_else(|| DbError::Invalid("session_id required".into()))?;
    let expected_revision = req.get("expected_revision").and_then(|v| v.as_i64());
    let adopt_revision = req.get("adopt_revision").and_then(|v| v.as_i64());
    let state_payload = req.get("state_payload").cloned().unwrap_or_else(|| json!({}));
    let pending_payload = req.get("pending_payload").cloned().unwrap_or_else(|| json!({}));
    let last_event_seq = req
        .get("last_event_seq")
        .and_then(|v| v.as_i64())
        .unwrap_or(0);
    let history_opt = req.get("history").and_then(|v| v.as_array()).cloned();
    let append_messages = req
        .get("append_messages")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    let emit_sync = req
        .get("emit_sync")
        .and_then(|v| v.as_bool())
        .unwrap_or(false);
    let workspace_id = req
        .get("workspace_id")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let change_id = req
        .get("change_id")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let now_str = req
        .get("now_str")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let updated_iso = req
        .get("updated_iso")
        .and_then(|v| v.as_str())
        .unwrap_or(now_str);

    let state_str = serde_json::to_string(&state_payload)?;
    let pending_str = serde_json::to_string(&pending_payload)?;

    let result = engine.write_tx(|conn| {
        let existing: Option<(i64, Option<String>)> = conn
            .query_row(
                "SELECT COALESCE(revision, 0), runtime_state_json FROM core_runtime_sessions WHERE thread_id = ?1",
                [session_id],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .optional()?;

        if let Some((current_revision, ref existing_raw)) = existing {
            let stale_stamp = match expected_revision {
                Some(exp) => exp != current_revision,
                None => true,
            };
            if stale_stamp && adopt_revision != Some(current_revision) {
                let existing_payload = parse_json_obj(existing_raw.clone());
                let st = existing_payload
                    .get("status")
                    .and_then(|s| s.as_str())
                    .unwrap_or("");
                if matches!(st, "running" | "waiting" | "interrupting") {
                    return Ok(json!({
                        "status": "check_owner",
                        "current_revision": current_revision,
                        "existing_payload": existing_payload,
                    }));
                }
            }
        }

        let assigned_seqs = if !append_messages.is_empty() {
            append_history_rows_tx(conn, session_id, &append_messages, now_str)?
        } else {
            Vec::new()
        };

        let Some((current_revision, _)) = existing else {
            let hist_str = match history_opt {
                Some(ref arr) => serde_json::to_string(arr)?,
                None => "[]".to_string(),
            };
            conn.execute(
                "INSERT INTO core_runtime_sessions \
                 (thread_id, revision, runtime_state_json, history_json, pending_approval_json, last_event_seq, updated_at) \
                 VALUES (?1, 1, ?2, ?3, ?4, ?5, ?6)",
                params![session_id, state_str, hist_str, pending_str, last_event_seq, now_str],
            )?;
            let emitted_change_id = if emit_sync && !change_id.is_empty() {
                append_runtime_sync_change_tx(
                    conn,
                    session_id,
                    &state_payload,
                    &pending_payload,
                    workspace_id,
                    change_id,
                    updated_iso,
                    now_str,
                )?;
                Some(change_id)
            } else {
                None
            };
            return Ok(json!({
                "status": "ok",
                "revision": 1,
                "change_id": emitted_change_id,
                "assigned_seqs": assigned_seqs,
            }));
        };

        let next_revision = current_revision + 1;
        let updated = if let Some(ref arr) = history_opt {
            let hist_str = serde_json::to_string(arr)?;
            conn.execute(
                "UPDATE core_runtime_sessions SET \
                 revision = ?1, runtime_state_json = ?2, pending_approval_json = ?3, \
                 last_event_seq = ?4, history_json = ?5, updated_at = ?6 \
                 WHERE thread_id = ?7 AND COALESCE(revision, 0) = ?8",
                params![
                    next_revision,
                    state_str,
                    pending_str,
                    last_event_seq,
                    hist_str,
                    now_str,
                    session_id,
                    current_revision
                ],
            )?
        } else {
            conn.execute(
                "UPDATE core_runtime_sessions SET \
                 revision = ?1, runtime_state_json = ?2, pending_approval_json = ?3, \
                 last_event_seq = ?4, updated_at = ?5 \
                 WHERE thread_id = ?6 AND COALESCE(revision, 0) = ?7",
                params![
                    next_revision,
                    state_str,
                    pending_str,
                    last_event_seq,
                    now_str,
                    session_id,
                    current_revision
                ],
            )?
        };
        if updated != 1 {
            return Err(DbError::Conflict(format!(
                "Runtime state revision conflict for {session_id}"
            )));
        }
        let emitted_change_id = if emit_sync && !change_id.is_empty() {
            append_runtime_sync_change_tx(
                conn,
                session_id,
                &state_payload,
                &pending_payload,
                workspace_id,
                change_id,
                updated_iso,
                now_str,
            )?;
            Some(change_id)
        } else {
            None
        };
        Ok(json!({
            "status": "ok",
            "revision": next_revision,
            "change_id": emitted_change_id,
            "assigned_seqs": assigned_seqs,
        }))
    })?;
    Ok(result)
}

pub fn runtime_cas_patch(engine: &DbEngine, req: &Value) -> Result<Value, DbError> {
    let session_id = req
        .get("session_id")
        .and_then(|v| v.as_str())
        .ok_or_else(|| DbError::Invalid("session_id required".into()))?;
    let expected_revision = req
        .get("expected_revision")
        .and_then(|v| v.as_i64())
        .ok_or_else(|| DbError::Invalid("expected_revision required".into()))?;
    let state_payload = req.get("state_payload").cloned().unwrap_or_else(|| json!({}));
    let pending_payload = req.get("pending_payload").cloned().unwrap_or_else(|| json!({}));
    let last_event_seq = req
        .get("last_event_seq")
        .and_then(|v| v.as_i64())
        .unwrap_or(0);
    let emit_sync = req
        .get("emit_sync")
        .and_then(|v| v.as_bool())
        .unwrap_or(false);
    let workspace_id = req
        .get("workspace_id")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let change_id = req
        .get("change_id")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let now_str = req
        .get("now_str")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let updated_iso = req
        .get("updated_iso")
        .and_then(|v| v.as_str())
        .unwrap_or(now_str);

    let state_str = serde_json::to_string(&state_payload)?;
    let pending_str = serde_json::to_string(&pending_payload)?;
    let next_revision = expected_revision + 1;

    engine.write_tx(|conn| {
        let updated = conn.execute(
            "UPDATE core_runtime_sessions SET \
             revision = ?1, runtime_state_json = ?2, pending_approval_json = ?3, \
             last_event_seq = ?4, updated_at = ?5 \
             WHERE thread_id = ?6 AND COALESCE(revision, 0) = ?7",
            params![
                next_revision,
                state_str,
                pending_str,
                last_event_seq,
                now_str,
                session_id,
                expected_revision
            ],
        )?;
        if updated != 1 {
            return Err(DbError::Conflict(format!(
                "Runtime state revision conflict for {session_id}"
            )));
        }
        if emit_sync && !change_id.is_empty() {
            append_runtime_sync_change_tx(
                conn,
                session_id,
                &state_payload,
                &pending_payload,
                workspace_id,
                change_id,
                updated_iso,
                now_str,
            )?;
        }
        Ok(json!({ "revision": next_revision }))
    })
}

pub fn runtime_append_history(engine: &DbEngine, req: &Value) -> Result<Value, DbError> {
    let session_id = req
        .get("session_id")
        .and_then(|v| v.as_str())
        .ok_or_else(|| DbError::Invalid("session_id required".into()))?;
    let messages = req
        .get("messages")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    let now_str = req
        .get("now_str")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    if messages.is_empty() {
        return Ok(json!({ "assigned_seqs": [] }));
    }
    let assigned = engine.write_tx(|conn| append_history_rows_tx(conn, session_id, &messages, now_str))?;
    Ok(json!({ "assigned_seqs": assigned }))
}

pub fn runtime_replace_history(engine: &DbEngine, req: &Value) -> Result<Value, DbError> {
    let session_id = req
        .get("session_id")
        .and_then(|v| v.as_str())
        .ok_or_else(|| DbError::Invalid("session_id required".into()))?;
    let messages = req
        .get("messages")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    let now_str = req
        .get("now_str")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    engine.write_tx(|conn| {
        conn.execute(
            "DELETE FROM core_history_entries WHERE thread_id = ?1",
            [session_id],
        )?;
        let mut stmt = conn.prepare_cached(
            "INSERT INTO core_history_entries (thread_id, seq, revision, message_json, created_at) \
             VALUES (?1, ?2, ?3, ?4, ?5)",
        )?;
        for (idx, msg) in messages.iter().enumerate() {
            let seq = (idx as i64) + 1;
            let mut copy = msg.clone();
            if let Some(meta) = copy.get_mut("metadata").and_then(|m| m.as_object_mut()) {
                meta.insert("history_seq".into(), json!(seq));
            }
            let msg_str = serde_json::to_string(&copy)?;
            stmt.execute(params![session_id, seq, seq, msg_str, now_str])?;
        }
        conn.execute(
            "UPDATE core_runtime_sessions SET history_json = '[]' WHERE thread_id = ?1",
            [session_id],
        )?;
        Ok(json!({ "ok": true }))
    })
}

pub fn runtime_get_history(engine: &DbEngine, session_id: &str, after_seq: i64) -> Result<Value, DbError> {
    engine.read(|conn| {
        let mut rows_out: Vec<Value> = Vec::new();
        if after_seq > 0 {
            let mut stmt = conn.prepare_cached(
                "SELECT message_json FROM core_history_entries \
                 WHERE thread_id = ?1 AND seq > ?2 ORDER BY seq ASC",
            )?;
            let mut rows = stmt.query(params![session_id, after_seq])?;
            while let Some(row) = rows.next()? {
                let raw: String = row.get(0)?;
                rows_out.push(serde_json::from_str(&raw).unwrap_or_else(|_| json!({})));
            }
        } else {
            let mut stmt = conn.prepare_cached(
                "SELECT message_json FROM core_history_entries \
                 WHERE thread_id = ?1 ORDER BY seq ASC",
            )?;
            let mut rows = stmt.query([session_id])?;
            while let Some(row) = rows.next()? {
                let raw: String = row.get(0)?;
                rows_out.push(serde_json::from_str(&raw).unwrap_or_else(|_| json!({})));
            }
        }
        if !rows_out.is_empty() {
            return Ok(Value::Array(rows_out));
        }
        let legacy: Option<String> = conn
            .query_row(
                "SELECT history_json FROM core_runtime_sessions WHERE thread_id = ?1",
                [session_id],
                |r| r.get(0),
            )
            .optional()?
            .flatten();
        Ok(parse_json_arr(legacy))
    })
}

pub fn runtime_read_history_page(
    engine: &DbEngine,
    session_id: &str,
    after_seq: i64,
    limit: i64,
) -> Result<Value, DbError> {
    engine.read(|conn| {
        let mut stmt = conn.prepare_cached(
            "SELECT seq, message_json FROM core_history_entries \
             WHERE thread_id = ?1 AND seq > ?2 ORDER BY seq ASC LIMIT ?3",
        )?;
        let mut rows = stmt.query(params![session_id, after_seq, limit])?;
        let mut out = Vec::new();
        while let Some(row) = rows.next()? {
            let seq: i64 = row.get(0)?;
            let raw: String = row.get(1)?;
            let mut msg: Value = serde_json::from_str(&raw).unwrap_or_else(|_| json!({}));
            if let Some(obj) = msg.as_object_mut() {
                let meta = obj
                    .entry("metadata".to_string())
                    .or_insert_with(|| json!({}));
                if let Some(meta_obj) = meta.as_object_mut() {
                    meta_obj.insert("history_seq".into(), json!(seq));
                }
            }
            out.push(msg);
        }
        if !out.is_empty() {
            return Ok(Value::Array(out));
        }
        let exists_modern: bool = conn
            .query_row(
                "SELECT 1 FROM core_history_entries WHERE thread_id = ?1 LIMIT 1",
                [session_id],
                |r| r.get::<_, i64>(0),
            )
            .is_ok();
        if exists_modern {
            return Ok(Value::Array(Vec::new()));
        }
        let mut legacy_stmt = conn.prepare_cached(
            "SELECT CAST(j.key AS INTEGER) + 1 AS seq, j.value AS message \
             FROM core_runtime_sessions AS s, json_each(s.history_json) AS j \
             WHERE s.thread_id = ?1 AND CAST(j.key AS INTEGER) >= ?2 \
             ORDER BY CAST(j.key AS INTEGER) LIMIT ?3",
        )?;
        let mut legacy_rows = legacy_stmt.query(params![session_id, after_seq, limit])?;
        let mut legacy_out = Vec::new();
        while let Some(row) = legacy_rows.next()? {
            let seq: i64 = row.get(0)?;
            let raw: String = row.get(1)?;
            if let Ok(mut msg) = serde_json::from_str::<Value>(&raw) {
                if let Some(obj) = msg.as_object_mut() {
                    let meta = obj
                        .entry("metadata".to_string())
                        .or_insert_with(|| json!({}));
                    if let Some(meta_obj) = meta.as_object_mut() {
                        meta_obj.insert("history_seq".into(), json!(seq));
                    }
                    legacy_out.push(msg);
                }
            }
        }
        Ok(Value::Array(legacy_out))
    })
}

pub fn runtime_history_max_seq(engine: &DbEngine, session_id: &str) -> Result<Value, DbError> {
    engine.read(|conn| {
        let max_seq: i64 = conn.query_row(
            "SELECT COALESCE(MAX(seq), 0) FROM core_history_entries WHERE thread_id = ?1",
            [session_id],
            |r| r.get(0),
        )?;
        Ok(json!({ "max_seq": max_seq }))
    })
}

pub fn runtime_append_dialogue_record(engine: &DbEngine, req: &Value) -> Result<Value, DbError> {
    let session_id = req
        .get("session_id")
        .and_then(|v| v.as_str())
        .ok_or_else(|| DbError::Invalid("session_id required".into()))?;
    let id = req
        .get("id")
        .and_then(|v| v.as_str())
        .ok_or_else(|| DbError::Invalid("id required".into()))?;
    let kind = req.get("kind").and_then(|v| v.as_str()).unwrap_or("");
    let branch_epoch = req
        .get("branch_epoch")
        .and_then(|v| v.as_i64())
        .unwrap_or(0)
        .max(0);
    let watermark = req
        .get("watermark")
        .and_then(|v| v.as_i64())
        .unwrap_or(0)
        .max(0);
    let record_json = req.get("record").cloned().unwrap_or_else(|| json!({}));
    let now_str = req.get("now_str").and_then(|v| v.as_str()).unwrap_or("");
    let record_str = serde_json::to_string(&record_json)?;

    engine.write_tx(|conn| {
        let max_seq: i64 = conn.query_row(
            "SELECT COALESCE(MAX(seq), 0) FROM core_dialogue_records WHERE thread_id = ?1",
            [session_id],
            |r| r.get(0),
        )?;
        let next_seq = max_seq + 1;
        conn.execute(
            "INSERT INTO core_dialogue_records \
             (id, thread_id, seq, kind, branch_epoch, watermark, record_json, created_at) \
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
            params![
                id,
                session_id,
                next_seq,
                kind,
                branch_epoch,
                watermark,
                record_str,
                now_str
            ],
        )?;
        Ok(json!({ "seq": next_seq }))
    })
}

pub fn runtime_list_dialogue_records(engine: &DbEngine, session_id: &str) -> Result<Value, DbError> {
    engine.read(|conn| {
        let mut stmt = conn.prepare_cached(
            "SELECT COALESCE(seq, 0), COALESCE(kind, ''), COALESCE(branch_epoch, 0), \
             COALESCE(watermark, 0), COALESCE(record_json, '{}'), COALESCE(created_at, '') \
             FROM core_dialogue_records WHERE thread_id = ?1 ORDER BY seq ASC",
        )?;
        let mut rows = stmt.query([session_id])?;
        let mut out = Vec::new();
        while let Some(row) = rows.next()? {
            let seq: i64 = row.get(0)?;
            let kind: String = row.get(1)?;
            let branch_epoch: i64 = row.get(2)?;
            let watermark: i64 = row.get(3)?;
            let raw_rec: String = row.get(4)?;
            let created_at: String = row.get(5)?;
            out.push(json!({
                "seq": seq,
                "kind": kind,
                "branch_epoch": branch_epoch,
                "watermark": watermark,
                "record": serde_json::from_str::<Value>(&raw_rec).unwrap_or_else(|_| json!({})),
                "created_at": created_at,
            }));
        }
        Ok(Value::Array(out))
    })
}

pub fn runtime_dialogue_record_epoch(engine: &DbEngine, session_id: &str) -> Result<Value, DbError> {
    engine.read(|conn| {
        let epoch: i64 = conn.query_row(
            "SELECT COALESCE(MAX(branch_epoch), 0) FROM core_dialogue_records WHERE thread_id = ?1",
            [session_id],
            |r| r.get(0),
        )?;
        Ok(json!({ "epoch": epoch }))
    })
}

pub fn runtime_list_thread_ids(engine: &DbEngine) -> Result<Value, DbError> {
    engine.read(|conn| {
        let mut stmt = conn.prepare_cached("SELECT thread_id FROM core_runtime_sessions")?;
        let mut rows = stmt.query([])?;
        let mut out = Vec::new();
        while let Some(row) = rows.next()? {
            out.push(Value::String(row.get(0)?));
        }
        Ok(Value::Array(out))
    })
}

pub fn runtime_find_threads_with_metadata_key(
    engine: &DbEngine,
    key: &str,
) -> Result<Value, DbError> {
    if key.is_empty()
        || !key
            .chars()
            .next()
            .map(|c| c.is_ascii_alphabetic() || c == '_')
            .unwrap_or(false)
        || !key.chars().all(|c| c.is_ascii_alphanumeric() || c == '_')
    {
        return Ok(Value::Array(Vec::new()));
    }
    let path = format!("$.metadata.{key}");
    engine.read(|conn| {
        let mut stmt = conn.prepare_cached(
            "SELECT thread_id FROM core_runtime_sessions \
             WHERE json_extract(runtime_state_json, ?1) IS NOT NULL",
        )?;
        let mut rows = stmt.query([&path])?;
        let mut out = Vec::new();
        while let Some(row) = rows.next()? {
            out.push(Value::String(row.get(0)?));
        }
        Ok(Value::Array(out))
    })
}

pub fn runtime_list_pending_approvals(engine: &DbEngine) -> Result<Value, DbError> {
    engine.read(|conn| {
        let mut stmt = conn.prepare_cached(
            "SELECT thread_id, revision, runtime_state_json, pending_approval_json, COALESCE(last_event_seq, 0) \
             FROM core_runtime_sessions \
             WHERE json_extract(pending_approval_json, '$.pending_approval') IS NOT NULL",
        )?;
        let mut rows = stmt.query([])?;
        let mut out = Vec::new();
        while let Some(row) = rows.next()? {
            let tid: String = row.get(0)?;
            let rev: i64 = row.get(1)?;
            let state_raw: Option<String> = row.get(2)?;
            let pending_raw: Option<String> = row.get(3)?;
            let last_seq: i64 = row.get(4)?;
            out.push(json!({
                "thread_id": tid,
                "revision": rev,
                "runtime_state_json": parse_json_obj(state_raw),
                "pending_approval_json": parse_json_obj(pending_raw),
                "last_event_seq": last_seq,
            }));
        }
        Ok(Value::Array(out))
    })
}

pub fn runtime_list_live_status_rows(engine: &DbEngine) -> Result<Value, DbError> {
    engine.read(|conn| {
        let mut stmt = conn.prepare_cached(
            "SELECT thread_id, runtime_state_json, pending_approval_json \
             FROM core_runtime_sessions \
             WHERE json_extract(runtime_state_json, '$.status') IN ('interrupting', 'running', 'waiting')",
        )?;
        let mut rows = stmt.query([])?;
        let mut out = Vec::new();
        while let Some(row) = rows.next()? {
            let tid: String = row.get(0)?;
            let state_raw: Option<String> = row.get(1)?;
            let pending_raw: Option<String> = row.get(2)?;
            out.push(json!({
                "thread_id": tid,
                "runtime_state_json": parse_json_obj(state_raw),
                "pending_approval_json": parse_json_obj(pending_raw),
            }));
        }
        Ok(Value::Array(out))
    })
}

pub fn agent_run_upsert(engine: &DbEngine, req: &Value) -> Result<Value, DbError> {
    let agent_run_id = req
        .get("agent_run_id")
        .and_then(|v| v.as_str())
        .ok_or_else(|| DbError::Invalid("agent_run_id required".into()))?;
    let parent_thread_id = req.get("parent_thread_id").and_then(|v| v.as_str()).unwrap_or("");
    let parent_turn_id = req.get("parent_turn_id").and_then(|v| v.as_str()).unwrap_or("");
    let parent_run_id = req.get("parent_run_id").and_then(|v| v.as_str()).unwrap_or("");
    let name = req.get("name").and_then(|v| v.as_str()).unwrap_or("");
    let run_type = req.get("type").and_then(|v| v.as_str()).unwrap_or("execute");
    let model_id = req.get("model_id").and_then(|v| v.as_str()).unwrap_or("");
    let reasoning_level = req.get("reasoning_level").and_then(|v| v.as_str()).unwrap_or("");
    let status = req.get("status").and_then(|v| v.as_str()).unwrap_or("idle");
    let lease_until_ms = req.get("lease_until_ms").and_then(|v| v.as_i64()).unwrap_or(0);
    let sub_session_id = req.get("sub_session_id").and_then(|v| v.as_str()).unwrap_or("");
    let source_call_id = req.get("source_call_id").and_then(|v| v.as_str()).unwrap_or("");
    let source_run_id = req.get("source_run_id").and_then(|v| v.as_str()).unwrap_or("");
    let source_turn_id = req.get("source_turn_id").and_then(|v| v.as_str()).unwrap_or("");
    let summary = req.get("summary").and_then(|v| v.as_str()).unwrap_or("");
    let started_at_ms = req.get("started_at_ms").and_then(|v| v.as_i64()).unwrap_or(0);
    let completed_at_ms = req.get("completed_at_ms").and_then(|v| v.as_i64()).unwrap_or(0);
    let elapsed_ms = req.get("elapsed_ms").and_then(|v| v.as_i64()).unwrap_or(0);
    let payload_json = req.get("metadata").cloned().unwrap_or_else(|| json!({}));
    let now_str = req.get("now_str").and_then(|v| v.as_str()).unwrap_or("");
    let payload_str = serde_json::to_string(&payload_json)?;

    engine.write_tx(|conn| {
        conn.execute(
            "INSERT INTO core_agent_runs ( \
                agent_run_id, parent_thread_id, parent_turn_id, parent_run_id, name, type, \
                model_id, reasoning_level, status, lease_until_ms, sub_session_id, \
                source_call_id, source_run_id, source_turn_id, summary, \
                started_at_ms, completed_at_ms, elapsed_ms, payload_json, updated_at \
             ) VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16,?17,?18,?19,?20) \
             ON CONFLICT(agent_run_id) DO UPDATE SET \
                parent_thread_id = excluded.parent_thread_id, \
                parent_turn_id = excluded.parent_turn_id, \
                parent_run_id = excluded.parent_run_id, \
                name = excluded.name, \
                type = excluded.type, \
                model_id = excluded.model_id, \
                reasoning_level = excluded.reasoning_level, \
                status = excluded.status, \
                lease_until_ms = excluded.lease_until_ms, \
                sub_session_id = excluded.sub_session_id, \
                source_call_id = excluded.source_call_id, \
                source_run_id = excluded.source_run_id, \
                source_turn_id = excluded.source_turn_id, \
                summary = excluded.summary, \
                started_at_ms = excluded.started_at_ms, \
                completed_at_ms = excluded.completed_at_ms, \
                elapsed_ms = excluded.elapsed_ms, \
                payload_json = excluded.payload_json, \
                updated_at = excluded.updated_at",
            params![
                agent_run_id,
                parent_thread_id,
                parent_turn_id,
                parent_run_id,
                name,
                run_type,
                model_id,
                reasoning_level,
                status,
                lease_until_ms,
                sub_session_id,
                source_call_id,
                source_run_id,
                source_turn_id,
                summary,
                started_at_ms,
                completed_at_ms,
                elapsed_ms,
                payload_str,
                now_str,
            ],
        )?;
        Ok(json!({ "ok": true }))
    })
}

fn agent_run_from_row(row: &rusqlite::Row<'_>) -> rusqlite::Result<Value> {
    let payload_raw: Option<String> = row.get(18)?;
    Ok(json!({
        "agent_run_id": row.get::<_, String>(0)?,
        "parent_thread_id": row.get::<_, String>(1)?,
        "parent_turn_id": row.get::<_, String>(2)?,
        "parent_run_id": row.get::<_, String>(3)?,
        "name": row.get::<_, String>(4)?,
        "type": row.get::<_, String>(5)?,
        "model_id": row.get::<_, String>(6)?,
        "reasoning_level": row.get::<_, String>(7)?,
        "status": row.get::<_, String>(8)?,
        "lease_until_ms": row.get::<_, i64>(9)?,
        "sub_session_id": row.get::<_, String>(10)?,
        "source_call_id": row.get::<_, String>(11)?,
        "source_run_id": row.get::<_, String>(12)?,
        "source_turn_id": row.get::<_, String>(13)?,
        "summary": row.get::<_, String>(14)?,
        "started_at_ms": row.get::<_, i64>(15)?,
        "completed_at_ms": row.get::<_, i64>(16)?,
        "elapsed_ms": row.get::<_, i64>(17)?,
        "metadata": parse_json_obj(payload_raw),
    }))
}

const AGENT_RUN_COLS: &str =
    "agent_run_id, COALESCE(parent_thread_id,''), COALESCE(parent_turn_id,''), \
     COALESCE(parent_run_id,''), COALESCE(name,''), COALESCE(type,'execute'), \
     COALESCE(model_id,''), COALESCE(reasoning_level,''), status, COALESCE(lease_until_ms,0), \
     COALESCE(sub_session_id,''), COALESCE(source_call_id,''), COALESCE(source_run_id,''), \
     COALESCE(source_turn_id,''), COALESCE(summary,''), COALESCE(started_at_ms,0), \
     COALESCE(completed_at_ms,0), COALESCE(elapsed_ms,0), payload_json";

pub fn agent_run_get(engine: &DbEngine, agent_run_id: &str) -> Result<Value, DbError> {
    engine.read(|conn| {
        let sql = format!("SELECT {AGENT_RUN_COLS} FROM core_agent_runs WHERE agent_run_id = ?1");
        let mut stmt = conn.prepare_cached(&sql)?;
        let mut rows = stmt.query([agent_run_id])?;
        if let Some(row) = rows.next()? {
            Ok(agent_run_from_row(row)?)
        } else {
            Ok(Value::Null)
        }
    })
}

pub fn agent_run_list(
    engine: &DbEngine,
    parent_turn_id: Option<&str>,
    parent_thread_id: Option<&str>,
    live_only: bool,
) -> Result<Value, DbError> {
    engine.read(|conn| {
        let mut clauses: Vec<String> = Vec::new();
        let mut bind_vals: Vec<String> = Vec::new();
        if let Some(pt) = parent_turn_id.filter(|s| !s.is_empty()) {
            bind_vals.push(pt.to_string());
            clauses.push(format!("parent_turn_id = ?{}", bind_vals.len()));
        }
        if let Some(pth) = parent_thread_id.filter(|s| !s.is_empty()) {
            bind_vals.push(pth.to_string());
            clauses.push(format!("parent_thread_id = ?{}", bind_vals.len()));
        }
        if live_only {
            clauses.push("status IN ('running', 'paused', 'suspended', 'interrupted')".to_string());
        }
        let where_sql = if clauses.is_empty() {
            String::new()
        } else {
            format!("WHERE {}", clauses.join(" AND "))
        };
        let sql = format!(
            "SELECT {AGENT_RUN_COLS} FROM core_agent_runs {where_sql} ORDER BY started_at_ms ASC"
        );
        let mut stmt = conn.prepare(&sql)?;
        let params_refs: Vec<&dyn rusqlite::ToSql> =
            bind_vals.iter().map(|s| s as &dyn rusqlite::ToSql).collect();
        let mut rows = stmt.query(params_refs.as_slice())?;
        let mut out = Vec::new();
        while let Some(row) = rows.next()? {
            out.push(agent_run_from_row(row)?);
        }
        Ok(Value::Array(out))
    })
}

fn event_from_row(row: &rusqlite::Row<'_>) -> rusqlite::Result<Value> {
    let payload_raw: Option<String> = row.get(7)?;
    Ok(json!({
        "event_id": row.get::<_, String>(0)?,
        "thread_id": row.get::<_, String>(1)?,
        "seq": row.get::<_, i64>(2)?,
        "turn_id": row.get::<_, Option<String>>(3)?,
        "item_id": row.get::<_, Option<String>>(4)?,
        "parent_item_id": row.get::<_, Option<String>>(5)?,
        "client_message_id": row.get::<_, Option<String>>(6)?,
        "payload": parse_json_obj(payload_raw),
        "method": row.get::<_, String>(8)?,
        "workspace_id": row.get::<_, String>(9)?,
        "entity_type": row.get::<_, String>(10)?,
        "entity_id": row.get::<_, String>(11)?,
        "event_seq": row.get::<_, i64>(12)?,
        "revision": row.get::<_, i64>(13)?,
        "event_type": row.get::<_, String>(14)?,
        "created_at": row.get::<_, String>(15)?,
    }))
}

const EVENT_COLS: &str =
    "event_id, thread_id, seq, turn_id, item_id, parent_item_id, client_message_id, \
     payload_json, method, COALESCE(workspace_id,''), COALESCE(entity_type,'thread.event'), \
     COALESCE(entity_id,''), COALESCE(event_seq,0), COALESCE(revision,0), \
     COALESCE(event_type,''), COALESCE(created_at,'')";

pub fn events_list_after(
    engine: &DbEngine,
    thread_id: &str,
    after_seq: i64,
    limit: i64,
) -> Result<Value, DbError> {
    engine.read(|conn| {
        let sql = format!(
            "SELECT {EVENT_COLS} FROM core_app_events \
             WHERE thread_id = ?1 AND seq > ?2 ORDER BY seq ASC LIMIT ?3"
        );
        let mut stmt = conn.prepare_cached(&sql)?;
        let mut rows = stmt.query(params![thread_id, after_seq, limit.max(1)])?;
        let mut out = Vec::new();
        while let Some(row) = rows.next()? {
            out.push(event_from_row(row)?);
        }
        Ok(Value::Array(out))
    })
}

pub fn events_list_thread(
    engine: &DbEngine,
    thread_id: &str,
    limit: Option<i64>,
) -> Result<Value, DbError> {
    engine.read(|conn| {
        let mut out = Vec::new();
        if let Some(lim) = limit {
            let sql = format!(
                "SELECT {EVENT_COLS} FROM core_app_events WHERE thread_id = ?1 ORDER BY seq ASC LIMIT ?2"
            );
            let mut stmt = conn.prepare_cached(&sql)?;
            let mut rows = stmt.query(params![thread_id, lim.max(1)])?;
            while let Some(row) = rows.next()? {
                out.push(event_from_row(row)?);
            }
        } else {
            let sql = format!(
                "SELECT {EVENT_COLS} FROM core_app_events WHERE thread_id = ?1 ORDER BY seq ASC"
            );
            let mut stmt = conn.prepare_cached(&sql)?;
            let mut rows = stmt.query([thread_id])?;
            while let Some(row) = rows.next()? {
                out.push(event_from_row(row)?);
            }
        }
        Ok(Value::Array(out))
    })
}

pub fn events_find_turn_event(
    engine: &DbEngine,
    thread_id: &str,
    turn_id: &str,
    terminal_only: bool,
) -> Result<Value, DbError> {
    engine.read(|conn| {
        let extra = if terminal_only {
            " AND method = 'core/runItem' \
              AND json_extract(payload_json, '$.kind') = 'status' \
              AND json_extract(payload_json, '$.status') IN ('completed', 'failed', 'error', 'cancelled', 'interrupted') \
              AND json_extract(payload_json, '$.payload.type') = 'turn'"
        } else {
            ""
        };
        let sql = format!(
            "SELECT {EVENT_COLS} FROM core_app_events \
             WHERE thread_id = ?1 AND turn_id = ?2{extra} ORDER BY seq DESC LIMIT 1"
        );
        let mut stmt = conn.prepare_cached(&sql)?;
        let mut rows = stmt.query(params![thread_id, turn_id])?;
        if let Some(row) = rows.next()? {
            Ok(event_from_row(row)?)
        } else {
            Ok(Value::Null)
        }
    })
}

pub fn events_find_client_event(
    engine: &DbEngine,
    thread_id: &str,
    client_message_id: &str,
    methods: &[String],
) -> Result<Value, DbError> {
    engine.read(|conn| {
        if methods.is_empty() {
            let sql = format!(
                "SELECT {EVENT_COLS} FROM core_app_events \
                 WHERE thread_id = ?1 AND client_message_id = ?2 ORDER BY seq ASC LIMIT 1"
            );
            let mut stmt = conn.prepare_cached(&sql)?;
            let mut rows = stmt.query(params![thread_id, client_message_id])?;
            if let Some(row) = rows.next()? {
                return Ok(event_from_row(row)?);
            }
            return Ok(Value::Null);
        }
        let placeholders: Vec<String> = (0..methods.len()).map(|i| format!("?{}", i + 3)).collect();
        let sql = format!(
            "SELECT {EVENT_COLS} FROM core_app_events \
             WHERE thread_id = ?1 AND client_message_id = ?2 AND method IN ({}) \
             ORDER BY seq ASC LIMIT 1",
            placeholders.join(",")
        );
        let mut stmt = conn.prepare(&sql)?;
        let mut params_vec: Vec<&dyn rusqlite::ToSql> = Vec::with_capacity(methods.len() + 2);
        params_vec.push(&thread_id);
        params_vec.push(&client_message_id);
        for m in methods {
            params_vec.push(m);
        }
        let mut rows = stmt.query(params_vec.as_slice())?;
        if let Some(row) = rows.next()? {
            Ok(event_from_row(row)?)
        } else {
            Ok(Value::Null)
        }
    })
}
