//! Fast session list loading, existence checks, and sync snapshot summaries.
//!
//! user:“加载/切换/多会话多 agent 同时读写”+(会话列表与同步快照只在 Rust 中提取轻量元数据并缓存，不向 Python 传输庞大的 snapshot_json)。

use crate::pool::{DbEngine, DbError};
use crate::repair::{effective_thread_status, prune_orphan_turns, session_needs_repair};
use rusqlite::{params_from_iter, Connection};
use serde_json::{json, Map, Value};
use std::collections::HashMap;
use std::sync::atomic::Ordering;

#[derive(Clone, Debug)]
struct RowHeader {
    thread_id: String,
    snapshot_seq: i64,
    revision: i64,
    active_turn_id: String,
    workspace_pin_order: Option<i64>,
    workspace_session_order: Option<i64>,
    updated_at: String,
}

fn format_iso_timestamp(raw: &str) -> String {
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        return String::new();
    }
    // SQLAlchemy SQLite DateTime uses "YYYY-MM-DD HH:MM:SS(.ffffff)"; Python isoformat() uses 'T'
    // and omits ".000000" when microseconds == 0.
    let mut s = if trimmed.len() >= 19 && trimmed.as_bytes().get(10) == Some(&b' ') {
        let mut out = trimmed.to_string();
        out.replace_range(10..11, "T");
        out
    } else {
        trimmed.to_string()
    };
    if s.ends_with(".000000") {
        s.truncate(s.len() - 7);
    }
    s
}

fn build_summary_from_snapshot(conn: &Connection, header: &RowHeader, mut state: Value) -> Value {
    if session_needs_repair(&state, &header.active_turn_id) {
        let _ = crate::snapshots::hydrate_snapshot_turns_conn(
            conn,
            &header.thread_id,
            &mut state,
            None,
        );
        prune_orphan_turns(&mut state);
    }
    let session = state.get("session").and_then(|s| s.as_object());
    let member_id = session
        .and_then(|s| s.get("member_id"))
        .and_then(|v| v.as_str())
        .filter(|v| !v.is_empty())
        .unwrap_or("core")
        .to_string();
    let title = session
        .and_then(|s| s.get("title"))
        .and_then(|v| v.as_str())
        .filter(|v| !v.is_empty())
        .unwrap_or(&header.thread_id)
        .to_string();
    let status = effective_thread_status(&state);
    let metadata = session
        .and_then(|s| s.get("metadata"))
        .filter(|v| v.is_object())
        .cloned()
        .unwrap_or_else(|| Value::Object(Map::new()));
    let updated_iso = format_iso_timestamp(&header.updated_at);
    let created_at = session
        .and_then(|s| s.get("created_at"))
        .and_then(|v| v.as_str())
        .filter(|v| !v.is_empty())
        .map(format_iso_timestamp)
        .unwrap_or_else(|| updated_iso.clone());
    let rev = if header.revision > 0 {
        header.revision
    } else {
        state
            .get("revision")
            .and_then(|v| v.as_i64())
            .unwrap_or(0)
            .max(0)
    };

    json!({
        "id": header.thread_id,
        "member_id": member_id,
        "title": title,
        "status": status,
        "metadata": metadata,
        "created_at": created_at,
        "updated_at": updated_iso,
        "snapshot_seq": header.snapshot_seq,
        "revision": rev,
        "active_turn_id": header.active_turn_id,
        "workspace_pin_order": header.workspace_pin_order,
        "workspace_session_order": header.workspace_session_order,
    })
}

fn load_headers(conn: &Connection) -> Result<Vec<RowHeader>, DbError> {
    let mut stmt = conn.prepare(
        "SELECT thread_id, COALESCE(snapshot_seq, 0), COALESCE(revision, 0), \
         COALESCE(active_turn_id, ''), workspace_pin_order, workspace_session_order, \
         COALESCE(updated_at, '') \
         FROM core_thread_snapshots ORDER BY updated_at DESC",
    )?;
    let rows = stmt.query_map([], |row| {
        Ok(RowHeader {
            thread_id: row.get::<_, String>(0)?,
            snapshot_seq: row.get::<_, i64>(1)?,
            revision: row.get::<_, i64>(2)?,
            active_turn_id: row.get::<_, String>(3)?,
            workspace_pin_order: row.get::<_, Option<i64>>(4)?,
            workspace_session_order: row.get::<_, Option<i64>>(5)?,
            updated_at: row.get::<_, String>(6)?,
        })
    })?;
    let mut out = Vec::new();
    for r in rows {
        out.push(r?);
    }
    Ok(out)
}

pub fn list_session_summaries(engine: &DbEngine) -> Result<Value, DbError> {
    engine.read(|conn| {
        let headers = load_headers(conn)?;
        let mut resolved: HashMap<String, Value> = HashMap::with_capacity(headers.len());
        let mut misses: Vec<RowHeader> = Vec::new();

        {
            let cache = engine.cache.read().unwrap_or_else(|e| e.into_inner());
            for h in &headers {
                if let Some(cached) = cache.get_summary(&h.thread_id, h.revision, &h.updated_at) {
                    engine.stats.summary_cache_hits.fetch_add(1, Ordering::Relaxed);
                    resolved.insert(h.thread_id.clone(), cached);
                } else {
                    engine.stats.summary_cache_misses.fetch_add(1, Ordering::Relaxed);
                    misses.push(h.clone());
                }
            }
        }

        if !misses.is_empty() {
            let mut by_id: HashMap<String, RowHeader> = misses
                .iter()
                .map(|h| (h.thread_id.clone(), h.clone()))
                .collect();
            let mut newly_cached: Vec<(String, i64, String, Value)> = Vec::with_capacity(misses.len());
            for chunk in misses.chunks(200) {
                let placeholders = vec!["?"; chunk.len()].join(",");
                let sql = format!(
                    "SELECT thread_id, snapshot_json FROM core_thread_snapshots WHERE thread_id IN ({placeholders})"
                );
                let mut stmt = conn.prepare(&sql)?;
                let ids: Vec<&str> = chunk.iter().map(|h| h.thread_id.as_str()).collect();
                let mut rows = stmt.query(params_from_iter(ids))?;
                while let Some(row) = rows.next()? {
                    let tid: String = row.get(0)?;
                    let raw_json: Option<String> = row.get(1)?;
                    let state: Value = match raw_json {
                        Some(ref s) if !s.is_empty() => serde_json::from_str(s).unwrap_or_else(|_| json!({})),
                        _ => json!({}),
                    };
                    if let Some(h) = by_id.remove(&tid) {
                        let summary = build_summary_from_snapshot(conn, &h, state);
                        newly_cached.push((tid.clone(), h.revision, h.updated_at.clone(), summary.clone()));
                        resolved.insert(tid, summary);
                    }
                }
            }
            if !newly_cached.is_empty() {
                let mut cache = engine.cache.write().unwrap_or_else(|e| e.into_inner());
                for (tid, rev, upd, summary) in newly_cached {
                    cache.put_summary(tid, rev, upd, summary);
                }
            }
        }

        let ordered: Vec<Value> = headers
            .into_iter()
            .filter_map(|h| resolved.remove(&h.thread_id))
            .collect();
        Ok(Value::Array(ordered))
    })
}

pub fn list_core_sessions(engine: &DbEngine) -> Result<Value, DbError> {
    let summaries = list_session_summaries(engine)?;
    let arr = summaries.as_array().cloned().unwrap_or_default();
    let out: Vec<Value> = arr
        .into_iter()
        .map(|s| {
            json!({
                "thread_id": s.get("id").and_then(|v| v.as_str()).unwrap_or(""),
                "status": s.get("status").and_then(|v| v.as_str()).unwrap_or(""),
                "snapshot_seq": s.get("snapshot_seq").and_then(|v| v.as_i64()).unwrap_or(0),
                "updated_at": s.get("updated_at").and_then(|v| v.as_str()).unwrap_or(""),
            })
        })
        .collect();
    Ok(Value::Array(out))
}

pub fn session_exists_meta(engine: &DbEngine, thread_id: &str) -> Result<Value, DbError> {
    engine.read(|conn| {
        let mut stmt = conn.prepare_cached(
            "SELECT json_extract(snapshot_json, '$.session.metadata.owner_plugin') \
             FROM core_thread_snapshots WHERE thread_id = ?1",
        )?;
        let mut rows = stmt.query([thread_id])?;
        if let Some(row) = rows.next()? {
            let owner_plugin: Option<String> = row.get(0)?;
            Ok(json!({
                "exists": true,
                "owner_plugin": owner_plugin.unwrap_or_default(),
            }))
        } else {
            Ok(json!({
                "exists": false,
                "owner_plugin": "",
            }))
        }
    })
}

pub fn build_sync_snapshot_threads(engine: &DbEngine) -> Result<Value, DbError> {
    let summaries = list_session_summaries(engine)?;
    engine.read(|conn| {
        let mut project_ids_by_root: HashMap<String, String> = HashMap::new();
        let mut projects: Vec<Value> = Vec::new();
        if let Ok(mut stmt) = conn.prepare(
            "SELECT id, name, work_root, COALESCE(icon_key, 'folder'), COALESCE(color_key, 'gray'), \
             COALESCE(created_at, ''), COALESCE(updated_at, ''), COALESCE(revision, 1) \
             FROM core_projects ORDER BY created_at ASC, id ASC",
        ) {
            let mut rows = stmt.query([])?;
            while let Some(row) = rows.next()? {
                let id: String = row.get(0)?;
                let name: String = row.get(1)?;
                let work_root: String = row.get(2)?;
                let icon_key: String = row.get(3)?;
                let color_key: String = row.get(4)?;
                let created_at: String = row.get(5)?;
                let updated_at: String = row.get(6)?;
                let revision: i64 = row.get(7)?;
                project_ids_by_root.insert(work_root.clone(), id.clone());
                projects.push(json!({
                    "id": id,
                    "name": name,
                    "path": work_root,
                    "work_root": work_root,
                    "icon_key": if icon_key.is_empty() { "folder" } else { &icon_key },
                    "color_key": if color_key.is_empty() { "gray" } else { &color_key },
                    "created_at": format_iso_timestamp(&created_at),
                    "updated_at": format_iso_timestamp(&updated_at),
                    "revision": revision.max(1),
                    "deleted": false,
                }));
            }
        }

        let workspace_revision: i64 = conn
            .query_row(
                "SELECT COALESCE(MAX(seq), 0) FROM core_sync_changes",
                [],
                |row| row.get(0),
            )
            .unwrap_or(0);

        let mut snapshot_revision: i64 = 0;
        let mut threads: Vec<Value> = Vec::new();
        if let Some(arr) = summaries.as_array() {
            for s in arr {
                let tid = s.get("id").and_then(|v| v.as_str()).unwrap_or("");
                let rev = s.get("revision").and_then(|v| v.as_i64()).unwrap_or(0);
                snapshot_revision = snapshot_revision.max(rev);
                let meta = s.get("metadata").and_then(|v| v.as_object());
                let work_root = meta
                    .and_then(|m| m.get("work_root"))
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                let project_id = meta
                    .and_then(|m| m.get("project_id"))
                    .and_then(|v| v.as_str())
                    .filter(|v| !v.is_empty())
                    .map(str::to_string)
                    .or_else(|| project_ids_by_root.get(work_root).cloned());
                threads.push(json!({
                    "id": tid,
                    "project_id": project_id,
                    "title": s.get("title").and_then(|v| v.as_str()).unwrap_or(tid),
                    "status": s.get("status").and_then(|v| v.as_str()).unwrap_or("idle"),
                    "created_at": s.get("created_at").and_then(|v| v.as_str()).unwrap_or(""),
                    "updated_at": s.get("updated_at").and_then(|v| v.as_str()).unwrap_or(""),
                    "metadata": s.get("metadata").cloned().unwrap_or_else(|| json!({})),
                    "revision": rev,
                    "deleted": false,
                }));
            }
        }

        Ok(json!({
            "workspace_revision": workspace_revision,
            "snapshot_revision": snapshot_revision,
            "projects": projects,
            "threads": threads,
        }))
    })
}
