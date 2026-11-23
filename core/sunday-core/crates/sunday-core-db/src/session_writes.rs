//! Native Rust transactional writes for Core session CRUD and family cascade deletion.
//!
//! user:“开始”+(将 CoreDbSessionStore 的新建、更新、局部修改与全族级联删除全部迁入 Rust 事务并同步维护同步日志与读缓存，彻底统一单写入口)。

use crate::pool::{next_hex_id, DbEngine, DbError};
use crate::projector::{
    empty_projection_state, format_iso_from_sqlite, latest_active_turn_id, slim_registry_inline_images,
};
use crate::repair::{effective_thread_status, prune_orphan_turns, session_needs_repair};
use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Map, Value};
use std::collections::HashSet;

fn is_default_title(title: &str, session_id: &str) -> bool {
    let norm = title.trim().to_lowercase();
    if norm.is_empty()
        || matches!(
            norm.as_str(),
            "new session" | "新会话" | "新的研究" | "untitled" | "core"
        )
    {
        return true;
    }
    norm == session_id.trim().to_lowercase()
}

fn snapshot_revision_from(db_rev: i64, state: &Value) -> i64 {
    if db_rev > 0 {
        return db_rev;
    }
    state
        .get("revision")
        .and_then(|v| v.as_i64())
        .unwrap_or(0)
        .max(0)
}

fn append_sync_change(
    conn: &Connection,
    workspace_id: &str,
    entity_type: &str,
    operation: &str,
    entity_id: &str,
    thread_id: &str,
    revision: i64,
    entity: &Value,
    now_str: &str,
) -> Result<String, DbError> {
    let change_id = next_hex_id();
    let event_type = format!("{entity_type}.{operation}");
    let entity_str = serde_json::to_string(entity)?;
    conn.execute(
        "INSERT INTO core_sync_changes
         (change_id, workspace_id, entity_type, event_type, operation, entity_id, thread_id, revision, entity_json, created_at)
         VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10)",
        params![
            change_id,
            workspace_id,
            entity_type,
            event_type,
            operation,
            entity_id,
            thread_id,
            revision,
            entity_str,
            now_str,
        ],
    )?;
    Ok(change_id)
}

fn thread_sync_entity(
    session_id: &str,
    title: &str,
    status: &str,
    created_at_iso: &str,
    updated_at_iso: &str,
    metadata: &Value,
    revision: i64,
) -> Value {
    json!({
        "id": session_id,
        "title": title,
        "status": status,
        "created_at": created_at_iso,
        "updated_at": updated_at_iso,
        "metadata": metadata,
        "project_id": metadata.get("project_id").cloned().unwrap_or(Value::Null),
        "revision": revision,
        "snapshot_required": true,
        "deleted": false,
    })
}

pub fn session_create(engine: &DbEngine, req: &Value) -> Result<Value, DbError> {
    let session_id = req
        .get("session_id")
        .and_then(|v| v.as_str())
        .ok_or_else(|| DbError::Invalid("session_id required".into()))?;
    let member_id = req.get("member_id").and_then(|v| v.as_str()).unwrap_or("core");
    let title = req.get("title").and_then(|v| v.as_str()).unwrap_or("New Session");
    let status = req.get("status").and_then(|v| v.as_str()).unwrap_or("idle");
    let metadata = req.get("metadata").cloned().unwrap_or_else(|| json!({}));
    let created_at_iso = req.get("created_at_iso").and_then(|v| v.as_str()).unwrap_or("");
    let updated_at_str = req.get("updated_at_str").and_then(|v| v.as_str()).unwrap_or("");
    let updated_at_iso = format_iso_from_sqlite(updated_at_str);
    let now_str = req.get("now_str").and_then(|v| v.as_str()).unwrap_or(updated_at_str);
    let emit_sync = req.get("emit_sync").and_then(|v| v.as_bool()).unwrap_or(false);
    let workspace_id = req.get("workspace_id").and_then(|v| v.as_str()).unwrap_or("");

    let mut state = empty_projection_state(session_id, None);
    if let Some(root) = state.as_object_mut() {
        root.insert("thread_id".into(), json!(session_id));
        root.insert("status".into(), json!(status));
        root.insert(
            "session".into(),
            json!({
                "member_id": member_id,
                "title": title,
                "metadata": metadata,
                "created_at": created_at_iso,
            }),
        );
        root.entry("revision".to_string()).or_insert_with(|| json!(0));
    }
    let revision = state.get("revision").and_then(|v| v.as_i64()).unwrap_or(0);
    let state_str = serde_json::to_string(&state)?;

    let change_id = engine.write_tx(|conn| {
        let existing: Option<String> = conn
            .query_row(
                "SELECT thread_id FROM core_thread_snapshots WHERE thread_id = ?1",
                [session_id],
                |r| r.get(0),
            )
            .optional()?;
        if existing.is_some() {
            return Err(DbError::Invalid(format!("Session '{session_id}' already exists")));
        }
        conn.execute(
            "INSERT INTO core_thread_snapshots (thread_id, snapshot_seq, revision, active_turn_id, snapshot_json, updated_at)
             VALUES(?1, 0, ?2, NULL, ?3, ?4)",
            params![session_id, revision, state_str, updated_at_str],
        )?;
        let mut cid = None;
        if emit_sync {
            let entity = thread_sync_entity(
                session_id,
                title,
                status,
                created_at_iso,
                &updated_at_iso,
                &metadata,
                revision,
            );
            cid = Some(append_sync_change(
                conn,
                workspace_id,
                "thread",
                "upsert",
                session_id,
                session_id,
                revision,
                &entity,
                now_str,
            )?);
        }
        Ok(cid)
    })?;

    {
        let mut cache = engine.cache.write().unwrap_or_else(|e| e.into_inner());
        cache.invalidate_thread(Some(session_id));
        cache.put_metadata(session_id.to_string(), revision, 0, String::new(), state);
    }

    let change_ids: Vec<Value> = change_id.into_iter().map(Value::String).collect();
    Ok(json!({ "ok": true, "change_ids": change_ids }))
}

fn build_repaired_state_fields(
    row_raw: &str,
    active_turn_id: &str,
) -> (Value, String, String, String, Value, String) {
    let mut state: Value = serde_json::from_str(row_raw).unwrap_or_else(|_| json!({}));
    if session_needs_repair(&state, active_turn_id) {
        prune_orphan_turns(&mut state);
    }
    let session_obj = state.get("session").and_then(|s| s.as_object()).cloned().unwrap_or_default();
    let member_id = session_obj
        .get("member_id")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .unwrap_or("core")
        .to_string();
    let title = session_obj
        .get("title")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let status = effective_thread_status(&state);
    let metadata = session_obj.get("metadata").cloned().unwrap_or_else(|| json!({}));
    let created_at = session_obj
        .get("created_at")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    (state, member_id, title, status, metadata, created_at)
}

fn canonicalize_project_metadata(existing: &Map<String, Value>, requested: &Map<String, Value>) -> Result<Map<String, Value>, DbError> {
    let work_root = existing
        .get("work_root")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty());
    if work_root.is_none() {
        if requested.contains_key("work_root") {
            return Err(DbError::Invalid(
                "Use the project session endpoint for project-owned sessions".into(),
            ));
        }
        return Ok(requested.clone());
    }
    let mut out = requested.clone();
    out.insert("work_root".into(), json!(work_root.unwrap()));
    Ok(out)
}

fn merge_runtime_preferences(existing: &Map<String, Value>, requested: &Map<String, Value>) -> Map<String, Value> {
    if requested.contains_key("runtime_preferences") {
        return requested.clone();
    }
    let mut out = requested.clone();
    if let Some(rp) = existing.get("runtime_preferences") {
        out.insert("runtime_preferences".into(), rp.clone());
    } else {
        out.insert(
            "runtime_preferences".into(),
            json!({
                "allow_access_outside_workdir": false,
                "permission_preset": "ask",
            }),
        );
    }
    out
}

pub fn session_update(engine: &DbEngine, req: &Value) -> Result<Value, DbError> {
    let session_id = req
        .get("session_id")
        .and_then(|v| v.as_str())
        .ok_or_else(|| DbError::Invalid("session_id required".into()))?;
    let member_id = req.get("member_id").and_then(|v| v.as_str()).unwrap_or("core");
    let title = req.get("title").and_then(|v| v.as_str()).unwrap_or("");
    let status = req.get("status").and_then(|v| v.as_str()).unwrap_or("idle");
    let req_metadata = req
        .get("metadata")
        .and_then(|v| v.as_object())
        .cloned()
        .unwrap_or_default();
    let created_at_iso = req.get("created_at_iso").and_then(|v| v.as_str()).unwrap_or("");
    let expected_revision = req.get("expected_revision").and_then(|v| v.as_i64());
    let now_str = req.get("now_str").and_then(|v| v.as_str()).unwrap_or("");
    let now_iso = format_iso_from_sqlite(now_str);
    let emit_sync = req.get("emit_sync").and_then(|v| v.as_bool()).unwrap_or(false);
    let workspace_id = req.get("workspace_id").and_then(|v| v.as_str()).unwrap_or("");

    let (final_rev, final_seq, final_active, final_state, final_meta, change_id) = engine.write_tx(|conn| {
        let row: Option<(i64, i64, Option<String>, Option<String>)> = conn
            .query_row(
                "SELECT COALESCE(snapshot_seq, 0), COALESCE(revision, 0), active_turn_id, snapshot_json
                 FROM core_thread_snapshots WHERE thread_id = ?1",
                [session_id],
                |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)),
            )
            .optional()?;
        let Some((snap_seq, db_rev, active_opt, raw_opt)) = row else {
            return Ok((0, 0, String::new(), Value::Null, Value::Null, Some("NOT_FOUND".into())));
        };
        let raw_str = raw_opt.as_deref().unwrap_or("{}");
        let (mut state, _, _, _, existing_meta_val, _) =
            build_repaired_state_fields(raw_str, active_opt.as_deref().unwrap_or(""));
        let current_rev = snapshot_revision_from(db_rev, &state);
        if let Some(exp) = expected_revision {
            if exp != current_rev {
                return Err(DbError::Conflict(
                    json!({
                        "code": "REVISION_CONFLICT",
                        "thread_id": session_id,
                        "expected_revision": exp,
                        "current_revision": current_rev,
                    })
                    .to_string(),
                ));
            }
        }
        let existing_meta = existing_meta_val.as_object().cloned().unwrap_or_default();
        let mut merged_meta = canonicalize_project_metadata(&existing_meta, &req_metadata)?;
        merged_meta = merge_runtime_preferences(&existing_meta, &merged_meta);
        let merged_meta_val = Value::Object(merged_meta);
        let new_rev = current_rev + 1;

        if let Some(root) = state.as_object_mut() {
            root.insert("thread_id".into(), json!(session_id));
            root.insert("status".into(), json!(status));
            root.insert(
                "session".into(),
                json!({
                    "member_id": member_id,
                    "title": title,
                    "metadata": merged_meta_val,
                    "created_at": created_at_iso,
                }),
            );
            root.insert("revision".into(), json!(new_rev));
        }
        slim_registry_inline_images(&mut state);
        let new_active = latest_active_turn_id(&state)
            .or_else(|| active_turn_from_table_conn(conn, session_id))
            .unwrap_or_default();
        let state_str = serde_json::to_string(&state)?;

        conn.execute(
            "UPDATE core_thread_snapshots
             SET revision = ?1, active_turn_id = ?2, snapshot_json = ?3, updated_at = ?4
             WHERE thread_id = ?5",
            params![new_rev, new_active, state_str, now_str, session_id],
        )?;
        let mut cid = None;
        if emit_sync {
            let entity = thread_sync_entity(
                session_id,
                title,
                status,
                created_at_iso,
                &now_iso,
                &merged_meta_val,
                new_rev,
            );
            cid = Some(append_sync_change(
                conn,
                workspace_id,
                "thread",
                "upsert",
                session_id,
                session_id,
                new_rev,
                &entity,
                now_str,
            )?);
        }
        Ok((
            new_rev,
            snap_seq,
            new_active,
            state,
            merged_meta_val,
            cid,
        ))
    })?;

    if final_state.is_null() {
        return Ok(json!({ "found": false }));
    }

    {
        let mut cache = engine.cache.write().unwrap_or_else(|e| e.into_inner());
        cache.invalidate_thread(Some(session_id));
        cache.put_metadata(session_id.to_string(), final_rev, final_seq, final_active, final_state);
    }

    let change_ids: Vec<Value> = change_id.into_iter().map(Value::String).collect();
    Ok(json!({
        "found": true,
        "metadata": final_meta,
        "updated_at": now_iso,
        "revision": final_rev,
        "change_ids": change_ids,
    }))
}

pub fn session_patch(engine: &DbEngine, req: &Value) -> Result<Value, DbError> {
    let session_id = req
        .get("session_id")
        .and_then(|v| v.as_str())
        .ok_or_else(|| DbError::Invalid("session_id required".into()))?;
    let title_opt = req.get("title").and_then(|v| v.as_str());
    let status_opt = req.get("status").and_then(|v| v.as_str());
    let req_metadata_opt = req.get("metadata").and_then(|v| v.as_object()).cloned();
    let only_if_title_default = req
        .get("only_if_title_default")
        .and_then(|v| v.as_bool())
        .unwrap_or(false);
    let expected_revision = req.get("expected_revision").and_then(|v| v.as_i64());
    let now_str = req.get("now_str").and_then(|v| v.as_str()).unwrap_or("");
    let now_iso = format_iso_from_sqlite(now_str);
    let emit_sync = req.get("emit_sync").and_then(|v| v.as_bool()).unwrap_or(false);
    let workspace_id = req.get("workspace_id").and_then(|v| v.as_str()).unwrap_or("");

    let result = engine.write_tx(|conn| {
        let row: Option<(i64, i64, Option<String>, Option<String>, Option<String>)> = conn
            .query_row(
                "SELECT COALESCE(snapshot_seq, 0), COALESCE(revision, 0), active_turn_id, snapshot_json, COALESCE(updated_at, '')
                 FROM core_thread_snapshots WHERE thread_id = ?1",
                [session_id],
                |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?, r.get(4)?)),
            )
            .optional()?;
        let Some((snap_seq, db_rev, active_opt, raw_opt, old_updated)) = row else {
            return Ok(None);
        };
        let raw_str = raw_opt.as_deref().unwrap_or("{}");
        let (mut state, member_id, cur_title, cur_status, cur_meta_val, cur_created) =
            build_repaired_state_fields(raw_str, active_opt.as_deref().unwrap_or(""));
        let effective_title = if cur_title.is_empty() { session_id.to_string() } else { cur_title };
        if only_if_title_default && title_opt.is_some() && !is_default_title(&effective_title, session_id) {
            return Ok(None);
        }
        let current_rev = snapshot_revision_from(db_rev, &state);
        if let Some(exp) = expected_revision {
            if exp != current_rev {
                return Err(DbError::Conflict(
                    json!({
                        "code": "REVISION_CONFLICT",
                        "thread_id": session_id,
                        "expected_revision": exp,
                        "current_revision": current_rev,
                    })
                    .to_string(),
                ));
            }
        }

        let new_title = title_opt.unwrap_or(&effective_title).to_string();
        let new_status = status_opt.unwrap_or(&cur_status).to_string();
        let cur_meta = cur_meta_val.as_object().cloned().unwrap_or_default();
        let new_meta = if let Some(ref req_m) = req_metadata_opt {
            let mut m = canonicalize_project_metadata(&cur_meta, req_m)?;
            m = merge_runtime_preferences(&cur_meta, &m);
            m
        } else {
            cur_meta
        };
        let new_meta_val = Value::Object(new_meta);
        let created_iso = if !cur_created.is_empty() {
            cur_created
        } else {
            let fb = format_iso_from_sqlite(old_updated.as_deref().unwrap_or(""));
            if fb.is_empty() { now_iso.clone() } else { fb }
        };
        let new_rev = current_rev + 1;

        if let Some(root) = state.as_object_mut() {
            root.insert("thread_id".into(), json!(session_id));
            root.insert("status".into(), json!(new_status));
            root.insert(
                "session".into(),
                json!({
                    "member_id": member_id,
                    "title": new_title,
                    "metadata": new_meta_val,
                    "created_at": created_iso,
                }),
            );
            root.insert("revision".into(), json!(new_rev));
        }
        slim_registry_inline_images(&mut state);
        let new_active = latest_active_turn_id(&state)
            .or_else(|| active_turn_from_table_conn(conn, session_id))
            .unwrap_or_default();
        let state_str = serde_json::to_string(&state)?;

        conn.execute(
            "UPDATE core_thread_snapshots
             SET revision = ?1, active_turn_id = ?2, snapshot_json = ?3, updated_at = ?4
             WHERE thread_id = ?5",
            params![new_rev, new_active, state_str, now_str, session_id],
        )?;
        let mut cid = None;
        if emit_sync {
            let entity = thread_sync_entity(
                session_id,
                &new_title,
                &new_status,
                &created_iso,
                &now_iso,
                &new_meta_val,
                new_rev,
            );
            cid = Some(append_sync_change(
                conn,
                workspace_id,
                "thread",
                "upsert",
                session_id,
                session_id,
                new_rev,
                &entity,
                now_str,
            )?);
        }

        let record = json!({
            "id": session_id,
            "member_id": member_id,
            "title": new_title,
            "status": new_status,
            "metadata": new_meta_val,
            "created_at": created_iso,
            "updated_at": now_iso,
        });
        Ok(Some((
            new_rev,
            snap_seq,
            new_active,
            state,
            record,
            cid,
        )))
    })?;

    let Some((new_rev, snap_seq, new_active, state, record, cid)) = result else {
        return Ok(json!({ "updated": false, "record": Value::Null }));
    };

    {
        let mut cache = engine.cache.write().unwrap_or_else(|e| e.into_inner());
        cache.invalidate_thread(Some(session_id));
        cache.put_metadata(session_id.to_string(), new_rev, snap_seq, new_active, state);
    }

    let change_ids: Vec<Value> = cid.into_iter().map(Value::String).collect();
    Ok(json!({
        "updated": true,
        "record": record,
        "change_ids": change_ids,
    }))
}

fn collect_matching_thread_ids(
    conn: &Connection,
    sql: &str,
    roots: &[String],
    owned: &mut HashSet<String>,
) -> Result<(), DbError> {
    let mut stmt = conn.prepare_cached(sql)?;
    let mut rows = stmt.query([])?;
    while let Some(r) = rows.next()? {
        let Some(val) = r.get::<_, Option<String>>(0)? else {
            continue;
        };
        if roots
            .iter()
            .any(|root| val == *root || val.starts_with(&format!("{root}:sub:")))
        {
            owned.insert(val);
        }
    }
    Ok(())
}

fn active_turn_from_table_conn(conn: &Connection, thread_id: &str) -> Option<String> {
    conn.query_row(
        "SELECT turn_id FROM core_thread_snapshot_turns \
         WHERE thread_id = ?1 AND status IN ('running', 'waiting', 'interrupting', 'paused') \
         ORDER BY seq DESC LIMIT 1",
        [thread_id],
        |r| r.get::<_, String>(0),
    )
    .optional()
    .ok()
    .flatten()
    .filter(|s| !s.is_empty())
}

fn delete_where_in(conn: &Connection, table: &str, col: &str, ids: &[String]) -> Result<(), DbError> {
    if ids.is_empty() {
        return Ok(());
    }
    for chunk in ids.chunks(400) {
        let placeholders = vec!["?"; chunk.len()].join(",");
        let sql = format!("DELETE FROM {table} WHERE {col} IN ({placeholders})");
        let p: Vec<&dyn rusqlite::ToSql> = chunk.iter().map(|s| s as &dyn rusqlite::ToSql).collect();
        conn.execute(&sql, p.as_slice())?;
    }
    Ok(())
}

pub fn session_delete(engine: &DbEngine, req: &Value) -> Result<Value, DbError> {
    let session_id = req
        .get("session_id")
        .and_then(|v| v.as_str())
        .ok_or_else(|| DbError::Invalid("session_id required".into()))?;
    let expected_revision = req.get("expected_revision").and_then(|v| v.as_i64());
    let now_str = req.get("now_str").and_then(|v| v.as_str()).unwrap_or("");
    let emit_sync = req.get("emit_sync").and_then(|v| v.as_bool()).unwrap_or(false);
    let workspace_id = req.get("workspace_id").and_then(|v| v.as_str()).unwrap_or("");

    let out = engine.write_tx(|conn| {
        let row: Option<(i64, Option<String>)> = conn
            .query_row(
                "SELECT COALESCE(revision, 0), snapshot_json FROM core_thread_snapshots WHERE thread_id = ?1",
                [session_id],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .optional()?;
        let Some((db_rev, raw_opt)) = row else {
            return Ok(None);
        };
        let state: Value = raw_opt
            .as_deref()
            .and_then(|s| serde_json::from_str(s).ok())
            .unwrap_or_else(|| json!({}));
        let current_rev = snapshot_revision_from(db_rev, &state);
        if let Some(exp) = expected_revision {
            if exp != current_rev {
                return Err(DbError::Conflict(
                    json!({
                        "code": "REVISION_CONFLICT",
                        "thread_id": session_id,
                        "expected_revision": exp,
                        "current_revision": current_rev,
                    })
                    .to_string(),
                ));
            }
        }

        let mut cid = None;
        if emit_sync {
            cid = Some(append_sync_change(
                conn,
                workspace_id,
                "thread",
                "delete",
                session_id,
                session_id,
                current_rev + 1,
                &json!({ "id": session_id, "deleted": true }),
                now_str,
            )?);
        }

        let roots = vec![session_id.to_string()];
        let mut owned_set: HashSet<String> = roots.iter().cloned().collect();
        for sql in [
            "SELECT DISTINCT thread_id FROM core_runtime_sessions",
            "SELECT DISTINCT thread_id FROM core_app_events",
            "SELECT DISTINCT thread_id FROM core_history_entries",
            "SELECT DISTINCT thread_id FROM core_thread_snapshot_items",
            "SELECT DISTINCT thread_id FROM core_thread_snapshot_artifacts",
            "SELECT DISTINCT thread_id FROM core_thread_snapshot_turns",
            "SELECT DISTINCT thread_id FROM core_thread_snapshots",
            "SELECT DISTINCT session_id FROM core_attachments",
            "SELECT DISTINCT thread_id FROM core_goals",
            "SELECT DISTINCT thread_id FROM core_handoff_contexts",
        ] {
            collect_matching_thread_ids(conn, sql, &roots, &mut owned_set)?;
        }
        let owned_ids: Vec<String> = owned_set.into_iter().collect();

        // Preserve library-referenced attachments (`core_artifacts.deleted = 0 AND path LIKE 'attachment://%'`)
        let mut referenced_att_ids: HashSet<String> = HashSet::new();
        {
            let mut stmt = conn.prepare_cached(
                "SELECT path FROM core_artifacts WHERE deleted = 0 AND path LIKE 'attachment://%'",
            )?;
            let mut rows = stmt.query([])?;
            while let Some(r) = rows.next()? {
                let p: String = r.get(0)?;
                if let Some(stripped) = p.strip_prefix("attachment://") {
                    referenced_att_ids.insert(stripped.to_string());
                }
            }
        }

        let mut att_ids_to_del: Vec<String> = Vec::new();
        let mut unlink_paths: Vec<String> = Vec::new();
        for chunk in owned_ids.chunks(400) {
            let placeholders = vec!["?"; chunk.len()].join(",");
            let sql = format!(
                "SELECT id, storage_path FROM core_attachments WHERE session_id IN ({placeholders})"
            );
            let mut stmt = conn.prepare(&sql)?;
            let p: Vec<&dyn rusqlite::ToSql> = chunk.iter().map(|s| s as &dyn rusqlite::ToSql).collect();
            let mut rows = stmt.query(p.as_slice())?;
            while let Some(r) = rows.next()? {
                let aid: String = r.get(0)?;
                let spath: String = r.get(1)?;
                if !referenced_att_ids.contains(&aid) {
                    att_ids_to_del.push(aid);
                    if !spath.is_empty() {
                        unlink_paths.push(spath);
                    }
                }
            }
        }

        // Collect checkpoint IDs & arrange job IDs before deleting parents.
        let mut cp_ids: Vec<String> = Vec::new();
        for chunk in owned_ids.chunks(400) {
            let placeholders = vec!["?"; chunk.len()].join(",");
            let sql = format!("SELECT id FROM core_checkpoints WHERE root_session_id IN ({placeholders})");
            let mut stmt = conn.prepare(&sql)?;
            let p: Vec<&dyn rusqlite::ToSql> = chunk.iter().map(|s| s as &dyn rusqlite::ToSql).collect();
            let mut rows = stmt.query(p.as_slice())?;
            while let Some(r) = rows.next()? {
                cp_ids.push(r.get(0)?);
            }
        }
        let mut arrange_job_ids: Vec<String> = Vec::new();
        for chunk in owned_ids.chunks(400) {
            let placeholders = vec!["?"; chunk.len()].join(",");
            let sql = format!("SELECT id FROM core_arrange_jobs WHERE thread_id IN ({placeholders})");
            let mut stmt = conn.prepare(&sql)?;
            let p: Vec<&dyn rusqlite::ToSql> = chunk.iter().map(|s| s as &dyn rusqlite::ToSql).collect();
            let mut rows = stmt.query(p.as_slice())?;
            while let Some(r) = rows.next()? {
                arrange_job_ids.push(r.get(0)?);
            }
        }

        delete_where_in(conn, "core_app_events", "thread_id", &owned_ids)?;
        delete_where_in(conn, "core_history_entries", "thread_id", &owned_ids)?;
        delete_where_in(conn, "core_handoff_contexts", "thread_id", &owned_ids)?;
        delete_where_in(conn, "core_runtime_sessions", "thread_id", &owned_ids)?;
        delete_where_in(conn, "core_thread_snapshot_items", "thread_id", &owned_ids)?;
        delete_where_in(conn, "core_thread_snapshot_artifacts", "thread_id", &owned_ids)?;
        delete_where_in(conn, "core_thread_snapshot_turns", "thread_id", &owned_ids)?;
        delete_where_in(conn, "core_thread_outlines", "thread_id", &owned_ids)?;
        delete_where_in(conn, "core_thread_snapshots", "thread_id", &owned_ids)?;
        delete_where_in(conn, "core_checkpoint_artifact_refs", "checkpoint_id", &cp_ids)?;
        delete_where_in(conn, "core_checkpoint_blob_refs", "checkpoint_id", &cp_ids)?;
        delete_where_in(conn, "core_checkpoint_v2_session_messages", "checkpoint_id", &cp_ids)?;
        delete_where_in(conn, "core_checkpoint_v2_session_history", "checkpoint_id", &cp_ids)?;
        delete_where_in(conn, "core_checkpoint_v2_materialized", "checkpoint_id", &cp_ids)?;
        delete_where_in(conn, "core_checkpoints_v2", "root_session_id", &owned_ids)?;
        delete_where_in(conn, "core_checkpoints", "root_session_id", &owned_ids)?;
        delete_where_in(conn, "core_restore_operations", "root_session_id", &owned_ids)?;
        delete_where_in(conn, "core_attachments", "id", &att_ids_to_del)?;
        delete_where_in(conn, "core_goals", "thread_id", &owned_ids)?;
        delete_where_in(conn, "core_arrange_occurrences", "job_id", &arrange_job_ids)?;
        delete_where_in(conn, "core_arrange_jobs", "thread_id", &owned_ids)?;

        Ok(Some((owned_ids, unlink_paths, cid)))
    })?;

    let Some((owned_ids, unlink_paths, cid)) = out else {
        return Ok(json!({ "deleted": false, "unlink_paths": [], "change_ids": [] }));
    };

    {
        let mut cache = engine.cache.write().unwrap_or_else(|e| e.into_inner());
        for oid in &owned_ids {
            cache.invalidate_thread(Some(oid));
        }
    }

    let change_ids: Vec<Value> = cid.into_iter().map(Value::String).collect();
    Ok(json!({
        "deleted": true,
        "owned_ids": owned_ids,
        "unlink_paths": unlink_paths,
        "change_ids": change_ids,
    }))
}

pub fn session_persist_legacy_metadata(engine: &DbEngine, req: &Value) -> Result<Value, DbError> {
    let entries = req
        .get("entries")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    if entries.is_empty() {
        return Ok(json!({ "updated": 0 }));
    }
    let mode = req
        .get("mode")
        .and_then(|v| v.as_str())
        .unwrap_or("runtime_preferences");
    let now_str = req.get("now_str").and_then(|v| v.as_str()).unwrap_or("");
    let mut touched_ids = Vec::new();
    let updated = engine.write_tx(|conn| {
        let mut cnt = 0_i64;
        for entry in &entries {
            let Some(sid) = entry.get("session_id").and_then(|v| v.as_str()) else {
                continue;
            };
            let raw_opt: Option<String> = conn
                .query_row(
                    "SELECT snapshot_json FROM core_thread_snapshots WHERE thread_id = ?1",
                    [sid],
                    |r| r.get(0),
                )
                .optional()?
                .flatten();
            let Some(raw) = raw_opt else {
                continue;
            };
            let mut state: Value = serde_json::from_str(&raw).unwrap_or_else(|_| json!({}));
            let mut session_obj = state
                .get("session")
                .and_then(|s| s.as_object())
                .cloned()
                .unwrap_or_default();
            let mut meta_obj = session_obj
                .get("metadata")
                .and_then(|m| m.as_object())
                .cloned()
                .unwrap_or_default();
            if mode == "runtime_preferences" {
                if meta_obj.contains_key("runtime_preferences") {
                    continue;
                }
                if let Some(rp) = entry.get("runtime_preferences") {
                    meta_obj.insert("runtime_preferences".into(), rp.clone());
                }
            } else if mode == "fork_project" {
                if meta_obj
                    .get("work_root")
                    .and_then(|v| v.as_str())
                    .map(|s| !s.is_empty())
                    .unwrap_or(false)
                {
                    continue;
                }
                if let Some(title) = entry.get("title").and_then(|v| v.as_str()) {
                    session_obj.insert("title".into(), json!(title));
                }
                if let Some(meta_patch) = entry.get("metadata").and_then(|v| v.as_object()) {
                    for (k, v) in meta_patch {
                        meta_obj.insert(k.clone(), v.clone());
                    }
                }
            }
            session_obj.insert("metadata".into(), Value::Object(meta_obj));
            if let Some(root) = state.as_object_mut() {
                root.insert("session".into(), Value::Object(session_obj));
            }
            slim_registry_inline_images(&mut state);
            let s = serde_json::to_string(&state)?;
            conn.execute(
                "UPDATE core_thread_snapshots SET snapshot_json = ?1, updated_at = ?2 WHERE thread_id = ?3",
                params![s, now_str, sid],
            )?;
            touched_ids.push(sid.to_string());
            cnt += 1;
        }
        Ok(cnt)
    })?;
    if !touched_ids.is_empty() {
        let mut cache = engine.cache.write().unwrap_or_else(|e| e.into_inner());
        for sid in touched_ids {
            cache.invalidate_thread(Some(&sid));
        }
    }
    Ok(json!({ "updated": updated }))
}
