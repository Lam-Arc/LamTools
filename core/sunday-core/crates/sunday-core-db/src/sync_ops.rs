//! Native Rust implementation for `CoreSyncJournal` queries, delta sync, and pruning.
//!
//! user:“继续”+(将增量同步游标查询、delta 拉取、头部摘要、游标过期限缩与日志裁剪全部迁入 Rust，彻底去掉同步通道上的 SQLAlchemy/ORM 开销)。

use crate::pool::{DbEngine, DbError};
use crate::projector::format_iso_from_sqlite;
use crate::sessions::build_sync_snapshot_threads;
use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};

fn format_utc_iso_from_sqlite(raw: &str, fallback_iso: &str) -> String {
    let base = format_iso_from_sqlite(raw);
    if base.is_empty() {
        return fallback_iso.to_string();
    }
    if base.ends_with('Z') || base[10.min(base.len())..].contains('+') {
        return base;
    }
    format!("{base}+00:00")
}

fn row_to_sync_dict(
    seq: i64,
    change_id: String,
    row_ws: String,
    fallback_ws: &str,
    entity_type: String,
    event_type: String,
    operation: String,
    entity_id: String,
    thread_id: String,
    revision: i64,
    entity: Value,
    created_at_raw: String,
    fallback_iso: &str,
) -> Value {
    let ws = if row_ws.is_empty() { fallback_ws.to_string() } else { row_ws };
    let ev_type = if event_type.is_empty() {
        format!("{entity_type}.{operation}")
    } else {
        event_type
    };
    let snapshot_req = entity.get("snapshot_required") == Some(&Value::Bool(true));
    let mut out = json!({
        "seq": seq,
        "change_id": change_id,
        "workspace_id": ws,
        "type": entity_type,
        "entity_type": entity_type,
        "event_type": ev_type,
        "operation": operation,
        "entity_id": entity_id,
        "thread_id": thread_id,
        "revision": revision,
        "workspace_revision": seq,
        "snapshot_revision": revision,
        "payload": entity,
        "entity": entity,
        "created_at": format_utc_iso_from_sqlite(&created_at_raw, fallback_iso),
    });
    if snapshot_req {
        if let Some(obj) = out.as_object_mut() {
            obj.insert("snapshot_required".into(), json!(true));
        }
    }
    out
}

fn query_current_cursor(conn: &Connection, workspace_id: &str) -> Result<i64, DbError> {
    let val: i64 = if workspace_id.is_empty() {
        conn.query_row("SELECT COALESCE(MAX(seq), 0) FROM core_sync_changes", [], |r| r.get(0))?
    } else {
        conn.query_row(
            "SELECT COALESCE(MAX(seq), 0) FROM core_sync_changes WHERE workspace_id = ?1",
            [workspace_id],
            |r| r.get(0),
        )?
    };
    Ok(val)
}

fn query_oldest_cursor(conn: &Connection, workspace_id: &str) -> Result<Option<i64>, DbError> {
    let val: Option<i64> = if workspace_id.is_empty() {
        conn.query_row("SELECT MIN(seq) FROM core_sync_changes", [], |r| r.get(0))?
    } else {
        conn.query_row(
            "SELECT MIN(seq) FROM core_sync_changes WHERE workspace_id = ?1",
            [workspace_id],
            |r| r.get(0),
        )?
    };
    Ok(val)
}

fn query_snapshot_revision(conn: &Connection) -> Result<i64, DbError> {
    let val: i64 = conn
        .query_row("SELECT COALESCE(MAX(revision), 0) FROM core_thread_snapshots", [], |r| r.get(0))
        .unwrap_or(0);
    Ok(val)
}

fn query_list_after(
    conn: &Connection,
    workspace_id: &str,
    cursor: i64,
    limit: i64,
    fallback_iso: &str,
) -> Result<Vec<Value>, DbError> {
    let clamped = limit.max(1).min(2_000);
    let mut rows_out = Vec::new();
    let sql = if workspace_id.is_empty() {
        "SELECT seq, change_id, COALESCE(workspace_id,''), entity_type, COALESCE(event_type,''), \
         operation, entity_id, COALESCE(thread_id,''), COALESCE(revision,0), COALESCE(entity_json,'{}'), \
         COALESCE(created_at,'') \
         FROM core_sync_changes WHERE seq > ?1 ORDER BY seq ASC LIMIT ?2"
    } else {
        "SELECT seq, change_id, COALESCE(workspace_id,''), entity_type, COALESCE(event_type,''), \
         operation, entity_id, COALESCE(thread_id,''), COALESCE(revision,0), COALESCE(entity_json,'{}'), \
         COALESCE(created_at,'') \
         FROM core_sync_changes WHERE workspace_id = ?1 AND seq > ?2 ORDER BY seq ASC LIMIT ?3"
    };
    let mut stmt = conn.prepare_cached(sql)?;
    let mut rows = if workspace_id.is_empty() {
        stmt.query(params![cursor, clamped])?
    } else {
        stmt.query(params![workspace_id, cursor, clamped])?
    };
    while let Some(r) = rows.next()? {
        let raw_entity: String = r.get(9)?;
        let entity: Value = serde_json::from_str(&raw_entity).unwrap_or_else(|_| json!({}));
        rows_out.push(row_to_sync_dict(
            r.get(0)?,
            r.get(1)?,
            r.get(2)?,
            workspace_id,
            r.get(3)?,
            r.get(4)?,
            r.get(5)?,
            r.get(6)?,
            r.get(7)?,
            r.get(8)?,
            entity,
            r.get(10)?,
            fallback_iso,
        ));
    }
    Ok(rows_out)
}

pub fn sync_prune(engine: &DbEngine, req: &Value) -> Result<Value, DbError> {
    let limit = req.get("keep").and_then(|v| v.as_i64()).unwrap_or(50_000).max(1);
    let deleted = engine.write_tx(|conn| {
        let newest: i64 = conn
            .query_row("SELECT COALESCE(MAX(seq), 0) FROM core_sync_changes", [], |r| r.get(0))?;
        let cutoff = newest - limit;
        if cutoff <= 0 {
            return Ok(0_i64);
        }
        let n = conn.execute("DELETE FROM core_sync_changes WHERE seq <= ?1", [cutoff])?;
        Ok(n as i64)
    })?;
    Ok(json!({ "deleted": deleted }))
}

pub fn sync_cursors(engine: &DbEngine, req: &Value) -> Result<Value, DbError> {
    let ws = req.get("workspace_id").and_then(|v| v.as_str()).unwrap_or("");
    engine.read(|conn| {
        let current = query_current_cursor(conn, ws)?;
        let oldest = query_oldest_cursor(conn, ws)?;
        let snapshot_revision = query_snapshot_revision(conn)?;
        Ok(json!({
            "current": current,
            "oldest": oldest,
            "snapshot_revision": snapshot_revision,
        }))
    })
}

pub fn sync_list_after(engine: &DbEngine, req: &Value) -> Result<Value, DbError> {
    let ws = req.get("workspace_id").and_then(|v| v.as_str()).unwrap_or("");
    let cursor = req.get("cursor").and_then(|v| v.as_i64()).unwrap_or(0);
    let limit = req.get("limit").and_then(|v| v.as_i64()).unwrap_or(500);
    let now_iso = req.get("now_iso").and_then(|v| v.as_str()).unwrap_or("");
    let changes = engine.read(|conn| query_list_after(conn, ws, cursor, limit, now_iso))?;
    Ok(json!({ "changes": changes }))
}

pub fn sync_get_change(engine: &DbEngine, req: &Value) -> Result<Value, DbError> {
    let ws = req.get("workspace_id").and_then(|v| v.as_str()).unwrap_or("");
    let change_id = req
        .get("change_id")
        .and_then(|v| v.as_str())
        .ok_or_else(|| DbError::Invalid("change_id required".into()))?;
    let header_only = req.get("header_only").and_then(|v| v.as_bool()).unwrap_or(false);
    let now_iso = req.get("now_iso").and_then(|v| v.as_str()).unwrap_or("");

    engine.read(|conn| {
        let meta_opt: Option<(i64, String, String, String, String, String, String, i64, String)> = conn
            .query_row(
                "SELECT seq, COALESCE(workspace_id,''), entity_type, COALESCE(event_type,''), \
                 operation, entity_id, COALESCE(thread_id,''), COALESCE(revision,0), COALESCE(created_at,'') \
                 FROM core_sync_changes WHERE change_id = ?1",
                [change_id],
                |r| {
                    Ok((
                        r.get(0)?,
                        r.get(1)?,
                        r.get(2)?,
                        r.get(3)?,
                        r.get(4)?,
                        r.get(5)?,
                        r.get(6)?,
                        r.get(7)?,
                        r.get(8)?,
                    ))
                },
            )
            .optional()?;
        let Some((seq, row_ws, entity_type, event_type, operation, entity_id, thread_id, revision, created_raw)) = meta_opt else {
            return Ok(json!({ "change": Value::Null }));
        };
        if header_only && entity_type == "thread.event" {
            let mut item = row_to_sync_dict(
                seq,
                change_id.to_string(),
                row_ws,
                ws,
                entity_type,
                event_type,
                operation,
                entity_id,
                thread_id,
                revision,
                json!({}),
                created_raw,
                now_iso,
            );
            if let Some(obj) = item.as_object_mut() {
                obj.remove("payload");
                obj.remove("entity");
            }
            return Ok(json!({ "change": item }));
        }
        let raw_entity: Option<String> = conn
            .query_row(
                "SELECT COALESCE(entity_json, '{}') FROM core_sync_changes WHERE change_id = ?1",
                [change_id],
                |r| r.get(0),
            )
            .optional()?;
        let entity: Value = raw_entity
            .as_deref()
            .and_then(|s| serde_json::from_str(s).ok())
            .unwrap_or_else(|| json!({}));
        let item = row_to_sync_dict(
            seq,
            change_id.to_string(),
            row_ws,
            ws,
            entity_type,
            event_type,
            operation,
            entity_id,
            thread_id,
            revision,
            entity,
            created_raw,
            now_iso,
        );
        Ok(json!({ "change": item }))
    })
}

pub fn sync_run(engine: &DbEngine, req: &Value) -> Result<Value, DbError> {
    let ws = req.get("workspace_id").and_then(|v| v.as_str()).unwrap_or("");
    let cursor_opt = req.get("cursor").and_then(|v| if v.is_null() { None } else { v.as_i64() });
    let limit = req.get("limit").and_then(|v| v.as_i64()).unwrap_or(500);
    let now_iso = req.get("now_iso").and_then(|v| v.as_str()).unwrap_or("");

    let (current, oldest, snapshot_revision, changes_opt) = engine.read(|conn| {
        let cur = query_current_cursor(conn, ws)?;
        let old = query_oldest_cursor(conn, ws)?;
        let srev = query_snapshot_revision(conn)?;
        if let (Some(c), Some(o)) = (cursor_opt, old) {
            if c < o - 1 {
                return Ok((cur, old, srev, None));
            }
        }
        if let Some(c) = cursor_opt {
            let list = query_list_after(conn, ws, c, limit, now_iso)?;
            return Ok((cur, old, srev, Some(list)));
        }
        Ok((cur, old, srev, Some(Vec::new())))
    })?;

    if let (Some(c), Some(o)) = (cursor_opt, oldest) {
        if c < o - 1 {
            return Ok(json!({
                "ok": false,
                "error": "SYNC_CURSOR_EXPIRED",
                "workspace_id": ws,
                "workspace_revision": current,
                "snapshot_revision": snapshot_revision,
                "cursor": current,
                "oldest_cursor": o,
            }));
        }
    }

    if cursor_opt.is_none() {
        let snap = build_sync_snapshot_threads(engine)?;
        return Ok(json!({
            "ok": true,
            "mode": "snapshot",
            "workspace_id": ws,
            "workspace_revision": snap.get("workspace_revision").and_then(|v| v.as_i64()).unwrap_or(current),
            "snapshot_revision": snap.get("snapshot_revision").and_then(|v| v.as_i64()).unwrap_or(snapshot_revision),
            "snapshotVersion": current,
            "cursor": current,
            "projects": snap.get("projects").cloned().unwrap_or_else(|| json!([])),
            "threads": snap.get("threads").cloned().unwrap_or_else(|| json!([])),
            "snapshots": [],
            "messages": [],
        }));
    }

    let changes = changes_opt.unwrap_or_default();
    let next_cursor = changes
        .last()
        .and_then(|c| c.get("seq"))
        .and_then(|v| v.as_i64())
        .unwrap_or(current);
    Ok(json!({
        "ok": true,
        "mode": "delta",
        "workspace_id": ws,
        "workspace_revision": current,
        "snapshot_revision": snapshot_revision,
        "snapshotVersion": current,
        "cursor": next_cursor,
        "has_more": next_cursor < current,
        "changes": changes,
    }))
}
