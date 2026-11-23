//! Fast session switching, bounded page loading, and snapshot metadata caching.
//!
//! user:“加载/切换/多会话多 agent 同时读写”+(把原本 7 次以上跨线程的 Python 快照/条目/审批/计划读取合并为 Rust 原生单次查询，并用 64 槽位缓存支撑多会话快速切换)。

use crate::pool::{DbEngine, DbError};
use crate::repair::{
    projection_needs_repair, prune_orphan_turns, reconcile_status, sha256_hex,
    strip_inline_image_copies,
};
use rusqlite::{params, Connection};
use serde_json::{json, Map, Value};
use std::sync::atomic::Ordering;

const MAX_PAGE_ITEM_ROWS: i64 = 4000;

fn empty_thread_snapshot(thread_id: &str) -> Value {
    json!({
        "thread_id": thread_id,
        "status": "idle",
        "turns": {},
        "items": {},
        "item_order": [],
        "requests": {},
        "queue": [],
        "artifacts": {},
    })
}

fn empty_projection(thread_id: &str) -> Value {
    json!({
        "thread_id": thread_id,
        "status": "idle",
        "snapshot_seq": 0,
        "session": Value::Null,
        "turns": {},
        "requests": {},
        "queue": [],
        "core": empty_thread_snapshot(thread_id),
    })
}

struct LoadedMeta {
    revision: i64,
    snapshot_seq: i64,
    active_turn_id: String,
    state: Value,
    needs_usage_hydration: bool,
}

// user:“规划并实现”+(把老会话 resource usage 补全彻底迁入 Rust，消除 load_wire_page/build_thread_outline 退回 Python)
fn hydrate_usage_in_place_conn(
    conn: &Connection,
    state: &mut Value,
    thread_id: &str,
    snapshot_seq: i64,
) -> Result<bool, DbError> {
    let Some(core) = state.get_mut("core").and_then(|c| c.as_object_mut()) else {
        return Ok(false);
    };
    if core.get("resource_usage_version").and_then(|v| v.as_i64()) == Some(1) {
        return Ok(false);
    }
    let has_turns = core
        .get("turns")
        .and_then(|t| t.as_object())
        .map(|m| !m.is_empty())
        .unwrap_or(false);
    if !has_turns {
        core.insert("resource_usage_version".into(), json!(1));
        return Ok(true);
    }

    let mut stmt = conn.prepare_cached(
        "SELECT seq, event_id, payload_json FROM core_app_events \
         WHERE thread_id = ?1 AND seq <= ?2 AND method = ?3 \
         AND json_extract(payload_json, '$.kind') = 'usage' \
         ORDER BY seq ASC",
    )?;
    let mut rows = stmt.query(params![
        thread_id,
        snapshot_seq,
        crate::projector::CORE_RUN_ITEM_METHOD
    ])?;

    let mut usage_state = crate::projector::empty_core_snapshot(thread_id);
    let mut any_usage = false;
    while let Some(row) = rows.next()? {
        let row_seq: i64 = row.get(0)?;
        let row_eid: String = row.get(1)?;
        let raw_payload: Option<String> = row.get(2)?;
        let mut payload: Value = match raw_payload {
            Some(ref s) if !s.is_empty() => serde_json::from_str(s).unwrap_or_else(|_| json!({})),
            _ => json!({}),
        };
        if let Some(obj) = payload.as_object_mut() {
            obj.insert("seq".into(), json!(row_seq));
            if !obj.contains_key("thread_id") {
                obj.insert("thread_id".into(), json!(thread_id));
            }
            if !obj.contains_key("event_id") && !row_eid.is_empty() {
                obj.insert("event_id".into(), json!(row_eid));
            }
        }
        any_usage = true;
        crate::projector::apply_run_item_event_in_place_core(&mut usage_state, &payload, row_seq);
    }

    if any_usage {
        if let Some(usage_turns) = usage_state.get("turns").and_then(|v| v.as_object()) {
            let core_obj = state
                .get_mut("core")
                .and_then(|c| c.as_object_mut())
                .expect("core object checked above");
            let turns_obj = core_obj
                .entry("turns".to_string())
                .or_insert_with(|| json!({}))
                .as_object_mut();
            if let Some(target_turns) = turns_obj {
                for (tid, res_val) in usage_turns {
                    let Some(res_obj) = res_val.as_object() else {
                        continue;
                    };
                    let turn_val = target_turns
                        .entry(tid.clone())
                        .or_insert_with(|| json!({ "turn_id": tid }));
                    if let Some(turn_obj) = turn_val.as_object_mut() {
                        for key in ["usage", "usage_calls", "child_context_metrics"] {
                            if let Some(val) = res_obj.get(key) {
                                turn_obj.insert(key.to_string(), val.clone());
                            }
                        }
                    }
                }
            }
        }
    }
    if let Some(core_obj) = state.get_mut("core").and_then(|c| c.as_object_mut()) {
        core_obj.insert("resource_usage_version".into(), json!(1));
    }
    crate::projector::sync_turns_from_core(state, None);
    Ok(true)
}

fn load_metadata_inner(
    conn: &Connection,
    engine: &DbEngine,
    thread_id: &str,
) -> Result<Option<LoadedMeta>, DbError> {
    load_metadata_inner_impl(conn, engine, thread_id, true)
}

pub(crate) fn load_metadata_for_outline(
    conn: &Connection,
    engine: &DbEngine,
    thread_id: &str,
) -> Result<Option<(i64, i64, Value)>, DbError> {
    let Some(meta) = load_metadata_inner_impl(conn, engine, thread_id, false)? else {
        return Ok(None);
    };
    Ok(Some((meta.revision, meta.snapshot_seq, meta.state)))
}

fn load_metadata_inner_impl(
    conn: &Connection,
    engine: &DbEngine,
    thread_id: &str,
    hydrate_usage: bool,
) -> Result<Option<LoadedMeta>, DbError> {
    let mut probe_stmt = conn.prepare_cached(
        "SELECT COALESCE(revision, 0), COALESCE(snapshot_seq, 0), COALESCE(active_turn_id, '') \
         FROM core_thread_snapshots WHERE thread_id = ?1",
    )?;
    let mut probe_rows = probe_stmt.query([thread_id])?;
    let Some(probe) = probe_rows.next()? else {
        let mut cache = engine.cache.write().unwrap_or_else(|e| e.into_inner());
        cache.invalidate_thread(Some(thread_id));
        return Ok(None);
    };
    let mut revision: i64 = probe.get(0)?;
    let snapshot_seq: i64 = probe.get(1)?;
    let active_turn_id: String = probe.get(2)?;
    drop(probe_rows);

    {
        let mut cache = engine.cache.write().unwrap_or_else(|e| e.into_inner());
        if let Some(hit) = cache.get_metadata(thread_id, revision, snapshot_seq) {
            engine.stats.snapshot_cache_hits.fetch_add(1, Ordering::Relaxed);
            let mut state = hit.state;
            drop(cache);
            if hydrate_usage && hydrate_usage_in_place_conn(conn, &mut state, thread_id, snapshot_seq)? {
                let mut wcache = engine.cache.write().unwrap_or_else(|e| e.into_inner());
                wcache.put_metadata_sized(
                    thread_id.to_string(),
                    hit.revision,
                    hit.snapshot_seq,
                    active_turn_id.clone(),
                    state.clone(),
                    hit.approx_bytes,
                );
            }
            return Ok(Some(LoadedMeta {
                revision: hit.revision,
                snapshot_seq: hit.snapshot_seq,
                active_turn_id,
                state,
                needs_usage_hydration: false,
            }));
        }
    }

    engine.stats.snapshot_cache_misses.fetch_add(1, Ordering::Relaxed);
    let raw_json: Option<String> = conn.query_row(
        "SELECT snapshot_json FROM core_thread_snapshots WHERE thread_id = ?1",
        [thread_id],
        |row| row.get(0),
    )?;
    let raw_bytes = raw_json.as_deref().map(|s| s.len()).unwrap_or(0);
    let mut state: Value = match raw_json {
        Some(ref s) if !s.is_empty() => serde_json::from_str(s)?,
        _ => empty_projection(thread_id),
    };
    if revision == 0 {
        revision = state
            .get("revision")
            .and_then(|v| v.as_i64())
            .unwrap_or(0)
            .max(0);
    }
    if hydrate_usage {
        let _ = hydrate_usage_in_place_conn(conn, &mut state, thread_id, snapshot_seq)?;
    }
    let cache_state = state.clone();
    {
        let mut cache = engine.cache.write().unwrap_or_else(|e| e.into_inner());
        cache.put_metadata_sized(
            thread_id.to_string(),
            revision,
            snapshot_seq,
            active_turn_id.clone(),
            cache_state,
            raw_bytes,
        );
    }

    Ok(Some(LoadedMeta {
        revision,
        snapshot_seq,
        active_turn_id,
        state,
        needs_usage_hydration: false,
    }))
}

fn load_open_interactions(conn: &Connection, thread_id: &str) -> Vec<Value> {
    let Ok(mut stmt) = conn.prepare_cached(
        "SELECT interaction_id, turn_id, COALESCE(run_id, ''), COALESCE(scope, 'main'), \
         kind, status, COALESCE(created_seq, 0), COALESCE(tool_call_id, ''), \
         COALESCE(title, ''), COALESCE(body, ''), COALESCE(context_text, ''), \
         COALESCE(options_json, '[]'), COALESCE(expires_at_ms, 0), answer_json, \
         COALESCE(metadata_json, '{}') \
         FROM core_turn_interactions \
         WHERE thread_id = ?1 AND status IN ('open', 'deferred', 'processing') \
         ORDER BY created_seq ASC",
    ) else {
        return Vec::new();
    };
    let Ok(mut rows) = stmt.query([thread_id]) else {
        return Vec::new();
    };
    let mut out = Vec::new();
    while let Ok(Some(row)) = rows.next() {
        let interaction_id: String = row.get(0).unwrap_or_default();
        let turn_id: String = row.get(1).unwrap_or_default();
        let run_id: String = row.get(2).unwrap_or_default();
        let scope: String = row.get(3).unwrap_or_else(|_| "main".into());
        let kind: String = row.get(4).unwrap_or_default();
        let status: String = row.get(5).unwrap_or_default();
        let created_seq: i64 = row.get(6).unwrap_or(0);
        let tool_call_id: String = row.get(7).unwrap_or_default();
        let title: String = row.get(8).unwrap_or_default();
        let body: String = row.get(9).unwrap_or_default();
        let context_text: String = row.get(10).unwrap_or_default();
        let options_raw: String = row.get(11).unwrap_or_else(|_| "[]".into());
        let expires_at_ms: i64 = row.get(12).unwrap_or(0);
        let answer_raw: Option<String> = row.get(13).ok().flatten();
        let metadata_raw: String = row.get(14).unwrap_or_else(|_| "{}".into());

        let options: Value = serde_json::from_str(&options_raw).unwrap_or_else(|_| json!([]));
        let answer: Value = answer_raw
            .as_deref()
            .and_then(|s| serde_json::from_str(s).ok())
            .unwrap_or(Value::Null);
        let metadata: Value = serde_json::from_str(&metadata_raw).unwrap_or_else(|_| json!({}));
        let meta_obj = metadata.as_object();
        let project_id = meta_obj
            .and_then(|m| m.get("project_id"))
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let agent_name = meta_obj
            .and_then(|m| m.get("agent_name"))
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let agent_session_id = meta_obj
            .and_then(|m| m.get("agent_session_id"))
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let delivered_by = meta_obj
            .and_then(|m| m.get("delivered_by"))
            .and_then(|v| v.as_str())
            .filter(|s| !s.is_empty())
            .unwrap_or("main");
        let digest = sha256_hex(interaction_id.as_bytes());
        let decision_id = format!("dec_{}", &digest[..32]);
        let lifecycle = if status == "processing" {
            "processing"
        } else {
            "appearing"
        };
        out.push(json!({
            "interaction_id": interaction_id,
            "turn_id": turn_id,
            "run_id": run_id,
            "scope": if scope.is_empty() { "main" } else { &scope },
            "kind": kind,
            "status": status,
            "lifecycle": lifecycle,
            "decision_id": decision_id,
            "sequence": created_seq,
            "project_id": project_id,
            "agent_name": agent_name,
            "agent_session_id": agent_session_id,
            "delivered_by": delivered_by,
            "tool_call_id": tool_call_id,
            "title": title,
            "body": body,
            "context": context_text,
            "options": options,
            "expires_at_ms": expires_at_ms,
            "answer": answer,
            "metadata": metadata,
        }));
    }
    out
}

fn load_active_plan(conn: &Connection, thread_id: &str) -> Value {
    let raw: Result<Option<String>, _> = conn.query_row(
        "SELECT json_extract(runtime_state_json, '$.metadata.task_plan') \
         FROM core_runtime_sessions WHERE thread_id = ?1",
        [thread_id],
        |row| row.get(0),
    );
    match raw {
        Ok(Some(s)) if !s.is_empty() => {
            let val: Value = serde_json::from_str(&s).unwrap_or(Value::Null);
            if val.is_object() {
                val
            } else {
                Value::Null
            }
        }
        _ => Value::Null,
    }
}

fn item_seq(conn: &Connection, thread_id: &str, item_id: &str) -> Result<Option<i64>, DbError> {
    let mut stmt = conn.prepare_cached(
        "SELECT seq FROM core_thread_snapshot_items WHERE thread_id = ?1 AND item_id = ?2",
    )?;
    let mut rows = stmt.query(params![thread_id, item_id])?;
    if let Some(row) = rows.next()? {
        Ok(Some(row.get(0)?))
    } else {
        Ok(None)
    }
}

// user:“继续”+(把快照条目中的 _body_ref 引用从 core_app_events 批量回填，保留最新状态/序号字段，读回与完整存储完全一致)
pub(crate) fn hydrate_body_refs_conn(
    conn: &Connection,
    thread_id: &str,
    items: &mut Map<String, Value>,
) -> Result<(), DbError> {
    let mut ref_targets: Vec<(String, String)> = Vec::new();
    let mut max_seq: i64 = 0;
    let mut unbounded = false;
    for (map_id, val) in items.iter() {
        let Some(ref_obj) = val.get("_body_ref").and_then(|v| v.as_object()) else {
            continue;
        };
        let target_iid = ref_obj
            .get("item_id")
            .and_then(|v| v.as_str())
            .filter(|s| !s.is_empty())
            .unwrap_or(map_id.as_str())
            .to_string();
        let ref_seq = ref_obj.get("last_seq").and_then(|v| v.as_i64()).unwrap_or(0);
        if ref_seq > 0 {
            max_seq = max_seq.max(ref_seq);
        } else {
            unbounded = true;
        }
        ref_targets.push((map_id.clone(), target_iid));
    }
    if ref_targets.is_empty() {
        return Ok(());
    }

    let mut unique_iids: Vec<String> = Vec::with_capacity(ref_targets.len());
    let mut seen_iids = std::collections::HashSet::with_capacity(ref_targets.len());
    for (_, target_iid) in &ref_targets {
        if seen_iids.insert(target_iid.clone()) {
            unique_iids.push(target_iid.clone());
        }
    }

    let seq_bound = if unbounded || max_seq <= 0 { i64::MAX } else { max_seq };
    let mut recon_state = crate::projector::empty_core_snapshot(thread_id);
    for chunk in unique_iids.chunks(200) {
        let placeholders = vec!["?"; chunk.len()].join(",");
        let sql = format!(
            "SELECT seq, event_id, payload_json FROM core_app_events \
             WHERE thread_id = ? AND item_id IN ({placeholders}) AND method = ? AND seq <= ? \
             ORDER BY seq ASC"
        );
        let mut stmt = conn.prepare(&sql)?;
        let mut params_vec: Vec<&dyn rusqlite::ToSql> = Vec::with_capacity(chunk.len() + 3);
        let method = crate::projector::CORE_RUN_ITEM_METHOD;
        params_vec.push(&thread_id);
        for iid in chunk {
            params_vec.push(iid);
        }
        params_vec.push(&method);
        params_vec.push(&seq_bound);
        let mut rows = stmt.query(params_vec.as_slice())?;
        while let Some(row) = rows.next()? {
            let row_seq: i64 = row.get(0)?;
            let row_eid: String = row.get(1)?;
            let raw_payload: Option<String> = row.get(2)?;
            let mut payload: Value = match raw_payload {
                Some(ref s) if !s.is_empty() => serde_json::from_str(s).unwrap_or_else(|_| json!({})),
                _ => json!({}),
            };
            if let Some(obj) = payload.as_object_mut() {
                obj.insert("seq".into(), json!(row_seq));
                if !obj.contains_key("thread_id") {
                    obj.insert("thread_id".into(), json!(thread_id));
                }
                if !obj.contains_key("event_id") && !row_eid.is_empty() {
                    obj.insert("event_id".into(), json!(row_eid));
                }
            }
            crate::projector::apply_run_item_event_in_place_core(&mut recon_state, &payload, row_seq);
        }
    }

    let recon_items = recon_state.get("items").and_then(|v| v.as_object());
    for (map_id, target_iid) in ref_targets {
        let Some(item_obj) = items.get_mut(&map_id).and_then(|v| v.as_object_mut()) else {
            continue;
        };
        if let Some(recon_obj) = recon_items
            .and_then(|m| m.get(&target_iid))
            .and_then(|v| v.as_object())
        {
            for key in ["content", "deltas", "payload", "artifacts"] {
                if let Some(val) = recon_obj.get(key) {
                    item_obj.insert(key.to_string(), val.clone());
                } else {
                    item_obj.remove(key);
                }
            }
        }
        item_obj.remove("_body_ref");
    }
    Ok(())
}

fn load_item_rows_bounded(
    conn: &Connection,
    thread_id: &str,
    before_seq: Option<i64>,
    item_byte_budget: i64,
) -> Result<(Map<String, Value>, Option<i64>), DbError> {
    let budget = item_byte_budget.max(1);
    let mut chosen_oldest: Option<i64> = None;
    let mut total: i64 = 0;

    if let Some(bs) = before_seq {
        let mut stmt = conn.prepare_cached(
            "SELECT seq, COALESCE(CAST(json_extract(item_json, '$._body_ref.byte_len') AS INTEGER), length(item_json), 0) \
             FROM core_thread_snapshot_items \
             WHERE thread_id = ?1 AND seq < ?2 ORDER BY seq DESC, item_id DESC LIMIT ?3",
        )?;
        let mut rows = stmt.query(params![thread_id, bs, MAX_PAGE_ITEM_ROWS])?;
        while let Some(row) = rows.next()? {
            let seq: i64 = row.get(0)?;
            let sz: i64 = row.get(1)?;
            chosen_oldest = Some(match chosen_oldest {
                Some(prev) => prev.min(seq),
                None => seq,
            });
            total += sz;
            if total >= budget {
                break;
            }
        }
    } else {
        let mut stmt = conn.prepare_cached(
            "SELECT seq, COALESCE(CAST(json_extract(item_json, '$._body_ref.byte_len') AS INTEGER), length(item_json), 0) \
             FROM core_thread_snapshot_items \
             WHERE thread_id = ?1 ORDER BY seq DESC, item_id DESC LIMIT ?2",
        )?;
        let mut rows = stmt.query(params![thread_id, MAX_PAGE_ITEM_ROWS])?;
        while let Some(row) = rows.next()? {
            let seq: i64 = row.get(0)?;
            let sz: i64 = row.get(1)?;
            chosen_oldest = Some(match chosen_oldest {
                Some(prev) => prev.min(seq),
                None => seq,
            });
            total += sz;
            if total >= budget {
                break;
            }
        }
    }

    let Some(oldest) = chosen_oldest else {
        return Ok((Map::new(), None));
    };

    let mut items = if let Some(bs) = before_seq {
        let mut stmt = conn.prepare_cached(
            "SELECT item_id, seq, item_json FROM core_thread_snapshot_items \
             WHERE thread_id = ?1 AND seq >= ?2 AND seq < ?3 ORDER BY seq ASC, item_id ASC",
        )?;
        let rows = stmt.query(params![thread_id, oldest, bs])?;
        collect_item_rows(rows)?
    } else {
        let mut stmt = conn.prepare_cached(
            "SELECT item_id, seq, item_json FROM core_thread_snapshot_items \
             WHERE thread_id = ?1 AND seq >= ?2 ORDER BY seq ASC, item_id ASC",
        )?;
        let rows = stmt.query(params![thread_id, oldest])?;
        collect_item_rows(rows)?
    };
    let min_loaded_seq = items
        .values()
        .filter_map(|v| v.get("seq").and_then(|s| s.as_i64()))
        .min();
    hydrate_body_refs_conn(conn, thread_id, &mut items)?;

    Ok((items, min_loaded_seq))
}

fn finish_assembled(
    conn: &Connection,
    mut state: Value,
    thread_id: &str,
    revision: i64,
    snapshot_seq: i64,
    active_turn_id: &str,
    needs_usage_hydration: bool,
) -> Value {
    if let Some(root) = state.as_object_mut() {
        root.insert("snapshot_seq".into(), json!(snapshot_seq));
        root.insert("revision".into(), json!(revision));
    }
    let decisions = Value::Array(load_open_interactions(conn, thread_id));
    let task_plan = load_active_plan(conn, thread_id);
    if let Some(core) = state.get_mut("core").and_then(|c| c.as_object_mut()) {
        core.insert("decisions".into(), decisions.clone());
        core.insert("interactions".into(), decisions);
        core.insert("task_plan".into(), task_plan);
    }
    strip_inline_image_copies(&mut state);
    if !needs_usage_hydration && projection_needs_repair(&state, Some(active_turn_id)) {
        prune_orphan_turns(&mut state);
        reconcile_status(&mut state);
    }
    json!({
        "state": state,
        "needs_usage_hydration": needs_usage_hydration,
        "active_turn_id": active_turn_id,
    })
}

// user:“嗯”+(从拆分的 core_thread_snapshot_artifacts / core_thread_snapshot_turns 表按需还原完整或本页状态)
pub(crate) fn hydrate_snapshot_artifacts_conn(
    conn: &Connection,
    thread_id: &str,
    state: &mut Value,
) -> Result<(), DbError> {
    let mut stmt = conn.prepare_cached(
        "SELECT artifact_id, artifact_json FROM core_thread_snapshot_artifacts WHERE thread_id = ?1",
    )?;
    let mut rows = stmt.query([thread_id])?;
    let mut extra: Vec<(String, Value)> = Vec::new();
    while let Some(r) = rows.next()? {
        let aid: String = r.get(0)?;
        let raw: Option<String> = r.get(1)?;
        let val: Value = raw
            .as_deref()
            .and_then(|s| serde_json::from_str(s).ok())
            .unwrap_or_else(|| json!({}));
        extra.push((aid, val));
    }
    if extra.is_empty() {
        return Ok(());
    }
    let Some(root) = state.as_object_mut() else {
        return Ok(());
    };
    let core = root
        .entry("core".to_string())
        .or_insert_with(|| empty_thread_snapshot(thread_id));
    if let Some(core_obj) = core.as_object_mut() {
        let arts = core_obj
            .entry("artifacts".to_string())
            .or_insert_with(|| json!({}));
        if let Some(map) = arts.as_object_mut() {
            for (aid, val) in extra {
                map.entry(aid).or_insert(val);
            }
        }
    }
    Ok(())
}

pub(crate) fn hydrate_snapshot_turns_conn(
    conn: &Connection,
    thread_id: &str,
    state: &mut Value,
    filter_turn_ids: Option<&std::collections::HashSet<String>>,
) -> Result<(), DbError> {
    let mut fetched: Vec<(String, Option<Value>, Option<Value>)> = Vec::new();
    match filter_turn_ids {
        None => {
            let mut stmt = conn.prepare_cached(
                "SELECT turn_id, core_turn_json, app_turn_json \
                 FROM core_thread_snapshot_turns WHERE thread_id = ?1 ORDER BY seq ASC, turn_id ASC",
            )?;
            let mut rows = stmt.query([thread_id])?;
            while let Some(r) = rows.next()? {
                let tid: String = r.get(0)?;
                let c_raw: Option<String> = r.get(1)?;
                let a_raw: Option<String> = r.get(2)?;
                let c_val = c_raw.as_deref().and_then(|s| serde_json::from_str(s).ok());
                let a_val = a_raw.as_deref().and_then(|s| serde_json::from_str(s).ok());
                fetched.push((tid, c_val, a_val));
            }
        }
        Some(tids) => {
            if tids.is_empty() {
                let mut stmt = conn.prepare_cached(
                    "SELECT turn_id, core_turn_json, app_turn_json \
                     FROM core_thread_snapshot_turns \
                     WHERE thread_id = ?1 AND status IN ('running', 'waiting', 'interrupting', 'paused') \
                     ORDER BY seq ASC, turn_id ASC",
                )?;
                let mut rows = stmt.query([thread_id])?;
                while let Some(r) = rows.next()? {
                    let tid: String = r.get(0)?;
                    let c_raw: Option<String> = r.get(1)?;
                    let a_raw: Option<String> = r.get(2)?;
                    let c_val = c_raw.as_deref().and_then(|s| serde_json::from_str(s).ok());
                    let a_val = a_raw.as_deref().and_then(|s| serde_json::from_str(s).ok());
                    fetched.push((tid, c_val, a_val));
                }
            } else {
                let ids: Vec<String> = tids.iter().cloned().collect();
                let mut seen_tids: std::collections::HashSet<String> = std::collections::HashSet::new();
                for chunk in ids.chunks(200) {
                    let placeholders = vec!["?"; chunk.len()].join(",");
                    let sql = format!(
                        "SELECT turn_id, core_turn_json, app_turn_json \
                         FROM core_thread_snapshot_turns \
                         WHERE thread_id = ? AND turn_id IN ({placeholders})"
                    );
                    let mut stmt = conn.prepare(&sql)?;
                    let mut params_vec: Vec<&dyn rusqlite::ToSql> = Vec::with_capacity(chunk.len() + 1);
                    params_vec.push(&thread_id);
                    for id in chunk {
                        params_vec.push(id);
                    }
                    let mut rows = stmt.query(params_vec.as_slice())?;
                    while let Some(r) = rows.next()? {
                        let tid: String = r.get(0)?;
                        seen_tids.insert(tid.clone());
                        let c_raw: Option<String> = r.get(1)?;
                        let a_raw: Option<String> = r.get(2)?;
                        let c_val = c_raw.as_deref().and_then(|s| serde_json::from_str(s).ok());
                        let a_val = a_raw.as_deref().and_then(|s| serde_json::from_str(s).ok());
                        fetched.push((tid, c_val, a_val));
                    }
                }
                let mut active_stmt = conn.prepare_cached(
                    "SELECT turn_id, core_turn_json, app_turn_json \
                     FROM core_thread_snapshot_turns \
                     WHERE thread_id = ?1 AND status IN ('running', 'waiting', 'interrupting', 'paused')",
                )?;
                let mut active_rows = active_stmt.query([thread_id])?;
                while let Some(r) = active_rows.next()? {
                    let tid: String = r.get(0)?;
                    if !seen_tids.insert(tid.clone()) {
                        continue;
                    }
                    let c_raw: Option<String> = r.get(1)?;
                    let a_raw: Option<String> = r.get(2)?;
                    let c_val = c_raw.as_deref().and_then(|s| serde_json::from_str(s).ok());
                    let a_val = a_raw.as_deref().and_then(|s| serde_json::from_str(s).ok());
                    fetched.push((tid, c_val, a_val));
                }
            }
        }
    }
    if fetched.is_empty() {
        return Ok(());
    }
    let Some(root) = state.as_object_mut() else {
        return Ok(());
    };
    let mut core_entries: Vec<(String, Value)> = Vec::new();
    let mut app_entries: Vec<(String, Value)> = Vec::new();
    for (tid, c_opt, a_opt) in fetched {
        if let Some(cv) = c_opt {
            core_entries.push((tid.clone(), cv));
        }
        if let Some(av) = a_opt {
            app_entries.push((tid, av));
        }
    }
    if !app_entries.is_empty() {
        let turns = root.entry("turns".to_string()).or_insert_with(|| json!({}));
        if let Some(map) = turns.as_object_mut() {
            for (tid, val) in app_entries {
                map.entry(tid).or_insert(val);
            }
        }
    }
    if !core_entries.is_empty() {
        let core = root
            .entry("core".to_string())
            .or_insert_with(|| empty_thread_snapshot(thread_id));
        if let Some(core_obj) = core.as_object_mut() {
            let turns = core_obj.entry("turns".to_string()).or_insert_with(|| json!({}));
            if let Some(map) = turns.as_object_mut() {
                for (tid, val) in core_entries {
                    map.entry(tid).or_insert(val);
                }
            }
        }
    }
    Ok(())
}

pub fn load_snapshot_metadata(engine: &DbEngine, thread_id: &str) -> Result<Value, DbError> {
    engine.read(|conn| {
        let Some(meta) = load_metadata_inner(conn, engine, thread_id)? else {
            return Ok(json!({
                "state": empty_projection(thread_id),
                "needs_usage_hydration": false,
                "active_turn_id": "",
            }));
        };
        let mut state = meta.state;
        if let Some(core) = state.get_mut("core").and_then(|c| c.as_object_mut()) {
            core.entry("item_order".to_string())
                .or_insert_with(|| json!([]));
        }
        hydrate_snapshot_turns_conn(conn, thread_id, &mut state, None)?;
        Ok(finish_assembled(
            conn,
            state,
            thread_id,
            meta.revision,
            meta.snapshot_seq,
            &meta.active_turn_id,
            meta.needs_usage_hydration,
        ))
    })
}

pub fn load_snapshot_full(engine: &DbEngine, thread_id: &str) -> Result<Value, DbError> {
    engine.read(|conn| {
        let Some(meta) = load_metadata_inner(conn, engine, thread_id)? else {
            return Ok(json!({
                "state": empty_projection(thread_id),
                "needs_usage_hydration": false,
                "active_turn_id": "",
            }));
        };
        let mut state = meta.state;
        let mut stmt = conn.prepare_cached(
            "SELECT item_id, seq, item_json FROM core_thread_snapshot_items \
             WHERE thread_id = ?1 ORDER BY seq ASC, item_id ASC",
        )?;
        let (mut items, order) = collect_item_rows_ordered(stmt.query([thread_id])?)?;
        hydrate_body_refs_conn(conn, thread_id, &mut items)?;
        if let Some(root) = state.as_object_mut() {
            let core = root
                .entry("core".to_string())
                .or_insert_with(|| empty_thread_snapshot(thread_id));
            if let Some(core_obj) = core.as_object_mut() {
                core_obj.insert("items".into(), Value::Object(items));
                core_obj.insert("item_order".into(), Value::Array(order));
            }
        }
        hydrate_snapshot_artifacts_conn(conn, thread_id, &mut state)?;
        hydrate_snapshot_turns_conn(conn, thread_id, &mut state, None)?;
        Ok(finish_assembled(
            conn,
            state,
            thread_id,
            meta.revision,
            meta.snapshot_seq,
            &meta.active_turn_id,
            meta.needs_usage_hydration,
        ))
    })
}

pub fn load_snapshot_page(
    engine: &DbEngine,
    thread_id: &str,
    before_seq: Option<i64>,
    before_item_id: Option<&str>,
    item_byte_budget: i64,
) -> Result<Value, DbError> {
    engine.read(|conn| {
        let Some(meta) = load_metadata_inner(conn, engine, thread_id)? else {
            return Ok(json!({
                "state": empty_projection(thread_id),
                "needs_usage_hydration": false,
                "active_turn_id": "",
            }));
        };
        let mut resolved_before_seq = before_seq.filter(|&s| s > 0);
        if resolved_before_seq.is_none() {
            if let Some(bid) = before_item_id.filter(|s| !s.is_empty()) {
                resolved_before_seq = item_seq(conn, thread_id, bid)?;
            }
        }
        let (loaded_items, min_loaded_seq) =
            load_item_rows_bounded(conn, thread_id, resolved_before_seq, item_byte_budget)?;

        let has_older = match min_loaded_seq {
            None => false,
            Some(oldest) => {
                if let Some(bs) = resolved_before_seq {
                    conn.query_row(
                        "SELECT 1 FROM core_thread_snapshot_items \
                         WHERE thread_id = ?1 AND seq < ?2 AND seq < ?3 LIMIT 1",
                        params![thread_id, oldest, bs],
                        |r| r.get::<_, i64>(0),
                    )
                    .is_ok()
                } else {
                    conn.query_row(
                        "SELECT 1 FROM core_thread_snapshot_items \
                         WHERE thread_id = ?1 AND seq < ?2 LIMIT 1",
                        params![thread_id, oldest],
                        |r| r.get::<_, i64>(0),
                    )
                    .is_ok()
                }
            }
        };

        let total_items: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM core_thread_snapshot_items WHERE thread_id = ?1",
                [thread_id],
                |r| r.get(0),
            )
            .unwrap_or(0);

        let mut turn_ids_in_page: std::collections::HashSet<String> = std::collections::HashSet::new();
        let mut has_turnless_item = false;
        for v in loaded_items.values() {
            if let Some(tid) = v.get("turn_id").and_then(|s| s.as_str()).filter(|s| !s.is_empty()) {
                turn_ids_in_page.insert(tid.to_string());
            } else {
                has_turnless_item = true;
            }
        }
        let mut state = meta.state;
        if let Some(root) = state.as_object_mut() {
            let core = root
                .entry("core".to_string())
                .or_insert_with(|| empty_thread_snapshot(thread_id));
            if let Some(core_obj) = core.as_object_mut() {
                core_obj
                    .entry("item_order".to_string())
                    .or_insert_with(|| json!([]));
                core_obj.insert("items".into(), Value::Object(loaded_items));
                core_obj.insert("_page_has_older_items".into(), json!(has_older));
                core_obj.insert("_page_total_items".into(), json!(total_items));
            }
        }
        hydrate_snapshot_turns_conn(
            conn,
            thread_id,
            &mut state,
            if has_turnless_item { None } else { Some(&turn_ids_in_page) },
        )?;
        let mut out = finish_assembled(
            conn,
            state,
            thread_id,
            meta.revision,
            meta.snapshot_seq,
            &meta.active_turn_id,
            meta.needs_usage_hydration,
        );
        if let Some(obj) = out.as_object_mut() {
            obj.insert("resolved_before_seq".into(), json!(resolved_before_seq));
        }
        Ok(out)
    })
}

// user:“规划并实现”+(按会话懒回填 item_type，避免启动全表重写，回填后走 idx_core_snapshot_items_thread_type_seq 索引)
pub(crate) fn backfill_thread_item_types_best_effort(engine: &DbEngine, thread_id: &str) {
    let _ = engine.try_write_tx(|conn| {
        conn.execute(
            "UPDATE core_thread_snapshot_items \
             SET item_type = COALESCE( \
                 NULLIF(TRIM(json_extract(item_json, '$.type')), ''), \
                 NULLIF(TRIM(json_extract(item_json, '$.payload.type')), ''), \
                 '' \
             ) \
             WHERE thread_id = ?1 AND item_type IS NULL",
            [thread_id],
        )?;
        Ok(())
    });
}

// user:“规划并实现”+(按 SQL 查询的 seq ASC, item_id ASC 顺序收集条目，避免 BTreeMap 字典序打乱 item_order)
fn collect_item_rows_ordered(
    mut rows: rusqlite::Rows<'_>,
) -> Result<(Map<String, Value>, Vec<Value>), DbError> {
    let mut items = Map::new();
    let mut order = Vec::new();
    while let Some(row) = rows.next()? {
        let item_id: String = row.get(0)?;
        let seq: i64 = row.get(1)?;
        let raw: Option<String> = row.get(2)?;
        let mut item: Value = match raw {
            Some(ref s) if !s.is_empty() => serde_json::from_str(s).unwrap_or_else(|_| json!({})),
            _ => json!({}),
        };
        if let Some(obj) = item.as_object_mut() {
            obj.insert("seq".into(), json!(seq));
        }
        if !items.contains_key(&item_id) {
            order.push(Value::String(item_id.clone()));
        }
        items.insert(item_id, item);
    }
    Ok((items, order))
}

fn collect_item_rows(rows: rusqlite::Rows<'_>) -> Result<Map<String, Value>, DbError> {
    Ok(collect_item_rows_ordered(rows)?.0)
}

pub(crate) fn query_items_by_kind_conn(
    conn: &Connection,
    thread_id: &str,
    text_marker: &str,
    limit: i64,
) -> Result<(Map<String, Value>, bool), DbError> {
    let has_null_item_type: bool = conn
        .query_row(
            "SELECT 1 FROM core_thread_snapshot_items WHERE thread_id = ?1 AND item_type IS NULL LIMIT 1",
            [thread_id],
            |_| Ok(true),
        )
        .unwrap_or(false);

    let lim = limit.max(1);
    let mut items = if !has_null_item_type {
        let mut stmt = conn.prepare_cached(
            "SELECT item_id, seq, item_json FROM core_thread_snapshot_items \
             WHERE thread_id = ?1 AND item_type = ?2 \
             ORDER BY seq ASC, item_id ASC LIMIT ?3",
        )?;
        let rows = stmt.query(params![thread_id, text_marker, lim])?;
        collect_item_rows(rows)?
    } else {
        let pattern = format!("%\"{text_marker}\"%");
        let mut stmt = conn.prepare_cached(
            "SELECT item_id, seq, item_json FROM core_thread_snapshot_items \
             WHERE thread_id = ?1 AND item_json LIKE ?2 \
             ORDER BY seq ASC, item_id ASC LIMIT ?3",
        )?;
        let rows = stmt.query(params![thread_id, pattern, lim])?;
        collect_item_rows(rows)?
    };
    hydrate_body_refs_conn(conn, thread_id, &mut items)?;
    Ok((items, has_null_item_type))
}

pub fn load_items_by_kind(
    engine: &DbEngine,
    thread_id: &str,
    text_marker: &str,
    limit: i64,
) -> Result<Value, DbError> {
    if text_marker.is_empty() {
        return load_snapshot_metadata(engine, thread_id);
    }
    let (res, saw_null) = engine.read(|conn| {
        let Some(meta) = load_metadata_inner(conn, engine, thread_id)? else {
            return Ok((
                json!({
                    "state": empty_projection(thread_id),
                    "needs_usage_hydration": false,
                    "active_turn_id": "",
                }),
                false,
            ));
        };
        let (items, saw_null) = query_items_by_kind_conn(conn, thread_id, text_marker, limit)?;
        let mut state = meta.state;
        if let Some(root) = state.as_object_mut() {
            let core = root
                .entry("core".to_string())
                .or_insert_with(|| empty_thread_snapshot(thread_id));
            if let Some(core_obj) = core.as_object_mut() {
                core_obj
                    .entry("item_order".to_string())
                    .or_insert_with(|| json!([]));
                core_obj.insert("items".into(), Value::Object(items));
            }
        }
        hydrate_snapshot_turns_conn(conn, thread_id, &mut state, None)?;
        Ok((
            finish_assembled(
                conn,
                state,
                thread_id,
                meta.revision,
                meta.snapshot_seq,
                &meta.active_turn_id,
                meta.needs_usage_hydration,
            ),
            saw_null,
        ))
    })?;
    if saw_null {
        backfill_thread_item_types_best_effort(engine, thread_id);
    }
    Ok(res)
}

pub fn resolve_item_seq_value(
    conn: &Connection,
    engine: &DbEngine,
    thread_id: &str,
    item_id: &str,
) -> Result<Option<i64>, DbError> {
    if item_id.is_empty() {
        return Ok(None);
    }
    if let Some(seq) = item_seq(conn, thread_id, item_id)? {
        return Ok(Some(seq));
    }
    let Some(meta) = load_metadata_inner(conn, engine, thread_id)? else {
        return Ok(None);
    };
    let state = meta.state;
    let containers = [Some(&state), state.get("core")];
    for container_opt in containers {
        let Some(container) = container_opt else {
            continue;
        };
        if let Some(item) = container.get("items").and_then(|m| m.get(item_id)) {
            if let Some(val) = item.get("seq").or_else(|| item.get("last_seq")) {
                if let Some(n) = val.as_i64() {
                    return Ok(Some(n));
                }
            }
            return Ok(None);
        }
        if let Some(order) = container.get("item_order").and_then(|o| o.as_array()) {
            if let Some(idx) = order.iter().position(|v| v.as_str() == Some(item_id)) {
                return Ok(Some((idx + 1) as i64));
            }
        }
    }
    Ok(None)
}

pub fn load_page_around(
    engine: &DbEngine,
    thread_id: &str,
    item_id: &str,
    item_byte_budget: i64,
) -> Result<Value, DbError> {
    let seq_opt = engine.read(|conn| resolve_item_seq_value(conn, engine, thread_id, item_id))?;
    let Some(seq) = seq_opt else {
        return Ok(json!({
            "anchor_seq": Value::Null,
            "page": {
                "state": empty_projection(thread_id),
                "needs_usage_hydration": false,
                "active_turn_id": "",
            }
        }));
    };
    let page = load_snapshot_page(engine, thread_id, Some(seq + 1), None, item_byte_budget)?;
    Ok(json!({
        "anchor_seq": seq,
        "page": page,
    }))
}
