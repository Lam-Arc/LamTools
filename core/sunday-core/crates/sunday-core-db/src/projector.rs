//! Native Rust event append, snapshot reducer (`CoreAppSnapshotProjector` + `apply_run_item_event_in_place`),
//! and incremental snapshot persistence with in-place cache maintenance.
//!
//! user:“实现，我需要最后可感觉到的体验优化”+(把最重、最阻塞多会话并发的事件批量落库与快照增量投影迁入 Rust，并在提交后直接更新内存缓存，彻底消除写锁阻塞与重复全量序列化)。

use crate::pool::{DbEngine, DbError};
use crate::repair::{effective_thread_status, strip_inline_image_copies};
use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Map, Value};
use std::collections::{HashMap, HashSet};
use std::sync::atomic::Ordering;

pub(crate) const CORE_RUN_ITEM_METHOD: &str = "core/runItem";
const TERMINAL_TURN_STATUSES: &[&str] = &["completed", "failed", "cancelled", "skipped"];
const TERMINAL_ERROR_STATUSES: &[&str] = &["failed", "cancelled", "error"];
const TERMINAL_ITEM_STATUSES: &[&str] =
    &["completed", "done", "ok", "failed", "error", "cancelled"];
const ACTIVE_TURN_STATUSES: &[&str] = &["queued", "running", "waiting", "stopping", "interrupting"];
const APPROVAL_REQUEST_FACTS: &[&str] = &[
    "request_id",
    "tool_call_id",
    "tool_name",
    "kind",
    "message",
    "options",
    "context",
    "metadata",
    "sub_agent",
];
const CONTEXT_METRIC_KEYS: &[&str] = &[
    "estimated_prompt_tokens",
    "estimatedPromptTokens",
    "context_tokens",
    "contextTokens",
    "context_window_tokens",
    "contextWindowTokens",
    "context_compaction_trigger_tokens",
    "contextCompactionTriggerTokens",
    "trigger_tokens",
    "triggerTokens",
    "context_compacted",
    "contextCompacted",
    "context_compaction_status",
    "context_tokens_before_compaction",
    "context_tokens_after_compaction",
    "context_messages_before_compaction",
    "context_messages_after_compaction",
    "steps_total",
    "model_id",
];

const SLIM_ITEM_THRESHOLD_BYTES: usize = 1024;

// user:“继续”+(超过阈值的条目若在 core_app_events 中有完整源事件，则快照条目表只存轻量元数据与 _body_ref 引用，读时批量回填，消灭 2-3 倍写放大)
fn maybe_slim_snapshot_item(
    conn: &Connection,
    thread_id: &str,
    item_id: &str,
    item_val: &Value,
    raw_str: &str,
) -> String {
    if raw_str.len() <= SLIM_ITEM_THRESHOLD_BYTES {
        return raw_str.to_string();
    }
    let Some(orig_obj) = item_val.as_object() else {
        return raw_str.to_string();
    };
    let backed: bool = conn
        .prepare_cached(
            "SELECT 1 FROM core_app_events WHERE thread_id = ?1 AND item_id = ?2 AND method = ?3 LIMIT 1",
        )
        .and_then(|mut s| s.query_row(params![thread_id, item_id, CORE_RUN_ITEM_METHOD], |_| Ok(true)))
        .unwrap_or(false);
    if !backed {
        return raw_str.to_string();
    }
    let mut slim = orig_obj.clone();
    for key in ["content", "deltas", "payload", "artifacts"] {
        slim.remove(key);
    }
    let last_seq = orig_obj
        .get("last_seq")
        .or_else(|| orig_obj.get("seq"))
        .and_then(|v| v.as_i64())
        .unwrap_or(0);
    slim.insert(
        "_body_ref".into(),
        json!({
            "v": 1,
            "item_id": item_id,
            "last_seq": last_seq,
            "byte_len": raw_str.len(),
        }),
    );
    serde_json::to_string(&Value::Object(slim)).unwrap_or_else(|_| raw_str.to_string())
}

pub(crate) fn extract_item_type(item: &Value) -> String {
    if let Some(s) = item
        .get("type")
        .and_then(|v| v.as_str())
        .map(str::trim)
        .filter(|s| !s.is_empty())
    {
        return s.to_string();
    }
    item.get("payload")
        .and_then(|p| p.get("type"))
        .and_then(|v| v.as_str())
        .map(str::trim)
        .unwrap_or("")
        .to_string()
}

pub(crate) fn empty_core_snapshot(thread_id: &str) -> Value {
    json!({
        "thread_id": thread_id,
        "snapshot_seq": 0,
        "seen_event_ids": [],
        "turns": {},
        "items": {},
        "item_order": [],
        "requests": {},
        "artifacts": {},
        "deleted_agents": {},
        "status": "idle",
    })
}

pub(crate) fn empty_projection_state(thread_id: &str, member_defaults: Option<&Value>) -> Value {
    let mut state = json!({
        "thread_id": thread_id,
        "snapshot_seq": 0,
        "revision": 0,
        "seen_event_ids": [],
        "turns": {},
        "items": {},
        "item_order": [],
        "requests": {},
        "artifacts": {},
        "core": empty_core_snapshot(thread_id),
        "status": "idle",
    });
    if let (Some(dst), Some(src)) = (
        state.as_object_mut(),
        member_defaults.and_then(|v| v.as_object()),
    ) {
        for (k, v) in src {
            dst.insert(k.clone(), v.clone());
        }
    }
    state
}

pub(crate) fn format_iso_from_sqlite(raw: &str) -> String {
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        return String::new();
    }
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

#[derive(Clone, Debug)]
struct Envelope {
    event_id: String,
    protocol_version: String,
    seq: i64,
    thread_id: String,
    method: String,
    payload: Value,
    created_at_iso: String,
    turn_id: Option<String>,
    item_id: Option<String>,
    parent_item_id: Option<String>,
    client_message_id: Option<String>,
    workspace_id: String,
    entity_type: String,
    entity_id: String,
    event_seq: i64,
    revision: i64,
    event_type: String,
}

impl Envelope {
    fn to_value(&self) -> Value {
        let mut obj = Map::new();
        obj.insert("event_id".into(), json!(self.event_id));
        obj.insert("protocol_version".into(), json!(self.protocol_version));
        obj.insert("thread_id".into(), json!(self.thread_id));
        obj.insert("method".into(), json!(self.method));
        obj.insert("payload".into(), self.payload.clone());
        obj.insert("created_at".into(), json!(self.created_at_iso));
        obj.insert(
            "turn_id".into(),
            match &self.turn_id {
                Some(s) => json!(s),
                None => Value::Null,
            },
        );
        obj.insert(
            "item_id".into(),
            match &self.item_id {
                Some(s) => json!(s),
                None => Value::Null,
            },
        );
        obj.insert(
            "parent_item_id".into(),
            match &self.parent_item_id {
                Some(s) => json!(s),
                None => Value::Null,
            },
        );
        obj.insert(
            "client_message_id".into(),
            match &self.client_message_id {
                Some(s) => json!(s),
                None => Value::Null,
            },
        );
        obj.insert("workspace_id".into(), json!(self.workspace_id));
        obj.insert("entity_type".into(), json!(self.entity_type));
        obj.insert(
            "entity_id".into(),
            json!(if self.entity_id.is_empty() {
                &self.thread_id
            } else {
                &self.entity_id
            }),
        );
        obj.insert(
            "event_seq".into(),
            json!(if self.event_seq != 0 {
                self.event_seq
            } else {
                self.seq
            }),
        );
        obj.insert("revision".into(), json!(self.revision));
        obj.insert(
            "event_type".into(),
            json!(if self.event_type.is_empty() {
                &self.method
            } else {
                &self.event_type
            }),
        );
        if self.seq != 0 {
            obj.insert("seq".into(), json!(self.seq));
        }
        Value::Object(obj)
    }
}

fn push_seen_id(state: &mut Value, event_id: &str) -> bool {
    let seen_exists = state
        .get("seen_event_ids")
        .and_then(|v| v.as_array())
        .map(|arr| arr.iter().any(|x| x.as_str() == Some(event_id)))
        .unwrap_or(false);
    if seen_exists {
        return false;
    }
    let Some(root) = state.as_object_mut() else {
        return false;
    };
    let arr = root
        .entry("seen_event_ids".to_string())
        .or_insert_with(|| json!([]));
    if let Some(vec) = arr.as_array_mut() {
        vec.push(Value::String(event_id.to_string()));
        if vec.len() > 2000 {
            let drain_count = vec.len() - 2000;
            vec.drain(0..drain_count);
        }
    }
    true
}

fn already_projected(state: &Value, event_id: &str, seq: i64) -> bool {
    if state
        .get("seen_event_ids")
        .and_then(|v| v.as_array())
        .map(|arr| arr.iter().any(|x| x.as_str() == Some(event_id)))
        .unwrap_or(false)
    {
        return true;
    }
    let core_seen = state
        .get("core")
        .and_then(|c| c.get("seen_event_ids"))
        .and_then(|v| v.as_array())
        .map(|arr| arr.iter().any(|x| x.as_str() == Some(event_id)))
        .unwrap_or(false);
    if core_seen {
        return true;
    }
    let snap_seq = state
        .get("snapshot_seq")
        .and_then(|v| v.as_i64())
        .unwrap_or(0);
    let core_seq = state
        .get("core")
        .and_then(|c| c.get("snapshot_seq"))
        .and_then(|v| v.as_i64())
        .unwrap_or(0);
    seq > 0 && (snap_seq >= seq || core_seq >= seq)
}

fn is_truthy_json(v: &Value) -> bool {
    match v {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Number(n) => n.as_f64().map(|x| x != 0.0).unwrap_or(false),
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(m) => !m.is_empty(),
    }
}

fn merge_dict_values(current: Option<&Value>, incoming: &Map<String, Value>) -> Value {
    let mut result = current
        .and_then(|v| v.as_object())
        .cloned()
        .unwrap_or_default();
    for (k, v) in incoming {
        if k == "cache_hit_rate" {
            continue;
        }
        let merged = match (result.get(k), v) {
            (Some(Value::Number(cur)), Value::Number(inc)) => {
                if let (Some(a), Some(b)) = (cur.as_i64(), inc.as_i64()) {
                    Value::Number((a + b).into())
                } else {
                    let sum = cur.as_f64().unwrap_or(0.0) + inc.as_f64().unwrap_or(0.0);
                    serde_json::Number::from_f64(sum)
                        .map(Value::Number)
                        .unwrap_or_else(|| v.clone())
                }
            }
            _ => v.clone(),
        };
        result.insert(k.clone(), merged);
    }
    let mut denom = result
        .get("cache_reported_input_tokens")
        .and_then(|v| v.as_f64())
        .unwrap_or(0.0);
    if incoming.contains_key("cached_tokens") {
        let inp = incoming
            .get("input_tokens")
            .or_else(|| incoming.get("prompt_tokens"))
            .and_then(|v| v.as_f64())
            .unwrap_or(0.0);
        denom += inp;
    }
    if incoming.contains_key("cached_tokens") || result.contains_key("cache_reported_input_tokens")
    {
        if let Some(n) = serde_json::Number::from_f64(denom) {
            result.insert("cache_reported_input_tokens".into(), Value::Number(n));
        }
    }
    if denom > 0.0 {
        let cached = result
            .get("cached_tokens")
            .and_then(|v| v.as_f64())
            .unwrap_or(0.0);
        let rate = (cached / denom).min(1.0);
        if let Some(n) = serde_json::Number::from_f64(rate) {
            result.insert("cache_hit_rate".into(), Value::Number(n));
        }
    } else {
        result.remove("cache_hit_rate");
    }
    Value::Object(result)
}

fn typed_input_parts_text(parts: &[Value]) -> String {
    let mut pieces = String::new();
    for p in parts {
        if let Some(t) = p.get("text").and_then(|v| v.as_str()) {
            pieces.push_str(t);
        }
    }
    pieces.trim().to_string()
}

fn is_context_metrics_event(
    kind: &str,
    payload: &Map<String, Value>,
    usage: &Map<String, Value>,
) -> bool {
    if payload.get("replace").and_then(|v| v.as_bool()) == Some(true) {
        return true;
    }
    if kind == "status"
        && payload
            .get("runtime_metrics")
            .map(|v| !v.is_null())
            .unwrap_or(false)
    {
        return true;
    }
    !usage.is_empty()
        && usage
            .keys()
            .any(|k| CONTEXT_METRIC_KEYS.contains(&k.as_str()))
}

fn is_terminal_error_event(
    item_id: &str,
    payload: &Map<String, Value>,
    metadata: &Map<String, Value>,
) -> bool {
    let payload_type = payload
        .get("type")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_ascii_lowercase();
    if payload_type == "runtime" || payload_type == "turn" {
        return true;
    }
    if metadata.get("runtime_phase").and_then(|v| v.as_str()) == Some("runtime.failed") {
        return true;
    }
    item_id.is_empty()
}

fn is_sub_agent_child_item(item: &Map<String, Value>) -> bool {
    if item
        .get("parent_item_id")
        .map(is_truthy_json)
        .unwrap_or(false)
    {
        return true;
    }
    item.get("payload")
        .and_then(|p| p.get("sub_agent"))
        .map(|s| s.is_object())
        .unwrap_or(false)
}

fn has_open_request(state: &Value) -> bool {
    state
        .get("requests")
        .and_then(|r| r.as_object())
        .map(|reqs| {
            reqs.values()
                .any(|r| r.get("status").and_then(|s| s.as_str()) == Some("open"))
        })
        .unwrap_or(false)
}

fn reconcile_terminal_requests_core(state: &mut Value) {
    let terminal_statuses: HashMap<String, String> = state
        .get("turns")
        .and_then(|t| t.as_object())
        .map(|turns| {
            turns
                .iter()
                .filter_map(|(tid, t)| {
                    let st = t.get("status").and_then(|s| s.as_str())?;
                    if TERMINAL_TURN_STATUSES.contains(&st) {
                        Some((tid.clone(), st.to_string()))
                    } else {
                        None
                    }
                })
                .collect()
        })
        .unwrap_or_default();
    if terminal_statuses.is_empty() {
        return;
    }
    let Some(requests) = state.get_mut("requests").and_then(|r| r.as_object_mut()) else {
        return;
    };
    for req in requests.values_mut() {
        let Some(req_obj) = req.as_object_mut() else {
            continue;
        };
        if req_obj.get("status").and_then(|s| s.as_str()) != Some("open") {
            continue;
        }
        if req_obj
            .get("sub_agent")
            .map(|v| v.is_object())
            .unwrap_or(false)
        {
            continue;
        }
        let tid = req_obj
            .get("turn_id")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        if let Some(term_st) = terminal_statuses.get(tid) {
            let new_st = if term_st == "cancelled" {
                "cancelled"
            } else {
                "resolved"
            };
            req_obj.insert("status".into(), json!(new_st));
            req_obj.insert("terminal_turn_status".into(), json!(term_st));
        }
    }
}

fn recompute_thread_status_core(state: &mut Value) {
    let paused = state
        .get("turns")
        .and_then(|t| t.as_object())
        .map(|turns| {
            turns
                .values()
                .any(|t| t.get("status").and_then(|s| s.as_str()) == Some("paused"))
        })
        .unwrap_or(false);
    if paused {
        if let Some(root) = state.as_object_mut() {
            root.insert("status".into(), json!("paused"));
        }
        return;
    }
    if has_open_request(state) {
        if let Some(root) = state.as_object_mut() {
            root.insert("status".into(), json!("waiting"));
        }
        return;
    }
    let has_active_turn = state
        .get("turns")
        .and_then(|t| t.as_object())
        .map(|turns| {
            turns.values().any(|t| {
                matches!(
                    t.get("status").and_then(|s| s.as_str()),
                    Some("queued" | "running" | "waiting")
                )
            })
        })
        .unwrap_or(false);
    if has_active_turn {
        if let Some(root) = state.as_object_mut() {
            root.insert("status".into(), json!("running"));
        }
        return;
    }
    let mut best_seq: i64 = -1;
    let mut best_status = "";
    if let Some(turns) = state.get("turns").and_then(|t| t.as_object()) {
        for t in turns.values() {
            if !t.is_object() {
                continue;
            }
            let seq = t.get("last_seq").and_then(|v| v.as_i64()).unwrap_or(0);
            if best_seq < 0 || seq > best_seq {
                best_seq = seq;
                best_status = t.get("status").and_then(|s| s.as_str()).unwrap_or("");
            }
        }
    }
    let settled = match best_status {
        "completed" => "completed",
        "cancelled" => "cancelled",
        "failed" => "failed",
        _ => "idle",
    };
    if let Some(root) = state.as_object_mut() {
        root.insert("status".into(), json!(settled));
    }
}

fn apply_turn_metrics(
    turn: Option<&mut Map<String, Value>>,
    kind: &str,
    payload: &Map<String, Value>,
    usage: &Map<String, Value>,
    replace: bool,
) {
    let Some(t) = turn else {
        return;
    };
    if usage.is_empty() || !is_context_metrics_event(kind, payload, usage) {
        return;
    }
    if replace {
        t.insert("context_metrics".into(), Value::Object(usage.clone()));
    } else {
        let mut merged = t
            .get("context_metrics")
            .and_then(|v| v.as_object())
            .cloned()
            .unwrap_or_default();
        for (k, v) in usage {
            merged.insert(k.clone(), v.clone());
        }
        t.insert("context_metrics".into(), Value::Object(merged));
    }
}

fn upsert_core_turn<'a>(
    state: &'a mut Value,
    turn_id: &str,
    kind: &str,
    seq: i64,
    run_id: &str,
) -> Option<&'a mut Map<String, Value>> {
    if turn_id.is_empty() {
        return None;
    }
    let snap_seq = state
        .get("snapshot_seq")
        .and_then(|v| v.as_i64())
        .unwrap_or(0);
    let root = state.as_object_mut()?;
    let turns = root
        .entry("turns".to_string())
        .or_insert_with(|| json!({}))
        .as_object_mut()?;
    let entry = turns.entry(turn_id.to_string()).or_insert_with(|| {
        json!({
            "turn_id": turn_id,
            "status": "running",
            "items": [],
        })
    });
    let turn = entry.as_object_mut()?;
    turn.insert("last_kind".into(), json!(kind));
    turn.insert(
        "last_seq".into(),
        json!(if seq != 0 { seq } else { snap_seq }),
    );
    if !run_id.is_empty() {
        turn.insert("run_id".into(), json!(run_id));
    }
    Some(turn)
}

fn upsert_core_item(
    state: &mut Value,
    event_id: &str,
    thread_id: &str,
    turn_id: &str,
    parent_item_id: &str,
    raw_item_id: &str,
    kind: &str,
    status: &str,
    seq: i64,
    payload: &Map<String, Value>,
    artifacts: &[Value],
    usage: &Map<String, Value>,
) -> String {
    let item_id = if !raw_item_id.is_empty() {
        raw_item_id.to_string()
    } else {
        let scope = if !turn_id.is_empty() {
            turn_id
        } else {
            thread_id
        };
        format!("{scope}:{kind}:{event_id}")
    };
    let snap_seq = state
        .get("snapshot_seq")
        .and_then(|v| v.as_i64())
        .unwrap_or(0);

    // Duplicate approval_request on a terminal item does not demote it.
    if kind == "approval_request" {
        if let Some(existing) = state
            .get("items")
            .and_then(|i| i.get(&item_id))
            .and_then(|i| i.as_object())
        {
            let cur_st = existing
                .get("status")
                .and_then(|s| s.as_str())
                .unwrap_or("");
            if TERMINAL_ITEM_STATUSES.contains(&cur_st) {
                let prev_seq = existing
                    .get("last_seq")
                    .and_then(|v| v.as_i64())
                    .unwrap_or(0);
                if let Some(mut_existing) = state
                    .get_mut("items")
                    .and_then(|i| i.get_mut(&item_id))
                    .and_then(|i| i.as_object_mut())
                {
                    mut_existing.insert("last_seq".into(), json!(prev_seq.max(seq)));
                }
                return item_id;
            }
        }
    }

    let Some(root) = state.as_object_mut() else {
        return item_id;
    };
    let item_seq = seq;
    let is_server_req = matches!(
        kind,
        "approval_request" | "approval_response" | "interaction_update"
    );

    {
        let items = root
            .entry("items".to_string())
            .or_insert_with(|| json!({}))
            .as_object_mut();
        if let Some(items_map) = items {
            let entry = items_map.entry(item_id.clone()).or_insert_with(|| {
                json!({
                    "item_id": item_id,
                    "turn_id": turn_id,
                    "parent_item_id": parent_item_id,
                    "kind": kind,
                    "content": "",
                    "deltas": [],
                    "status": status,
                })
            });
            if let Some(item) = entry.as_object_mut() {
                if kind == "tool_result" {
                    item.insert("kind".into(), json!("tool_result"));
                } else {
                    let existing_kind = item.get("kind").and_then(|v| v.as_str()).unwrap_or("");
                    if existing_kind.is_empty() {
                        item.insert("kind".into(), json!(kind));
                    }
                }
                item.insert("last_kind".into(), json!(kind));
                item.insert(
                    "last_seq".into(),
                    json!(if seq != 0 { seq } else { snap_seq }),
                );
                item.insert("status".into(), json!(status));

                if !payload.is_empty() {
                    let cur_payload = item
                        .entry("payload".to_string())
                        .or_insert_with(|| json!({}));
                    if let Some(cp_map) = cur_payload.as_object_mut() {
                        for (k, v) in payload {
                            if is_server_req
                                && APPROVAL_REQUEST_FACTS.contains(&k.as_str())
                                && !is_truthy_json(v)
                                && cp_map.get(k).map(is_truthy_json).unwrap_or(false)
                            {
                                continue;
                            }
                            cp_map.insert(k.clone(), v.clone());
                        }
                    }
                }
                if !artifacts.is_empty() {
                    item.insert("artifacts".into(), Value::Array(artifacts.to_vec()));
                }
                if !usage.is_empty() {
                    let merged = merge_dict_values(item.get("usage"), usage);
                    item.insert("usage".into(), merged);
                }

                if let Some(delta) = payload.get("delta").and_then(|v| v.as_str()) {
                    if payload.get("replace").and_then(|v| v.as_bool()) == Some(true) {
                        item.insert("deltas".into(), json!([delta]));
                        item.insert("content".into(), json!(delta));
                    } else {
                        if let Some(deltas) = item
                            .entry("deltas".to_string())
                            .or_insert_with(|| json!([]))
                            .as_array_mut()
                        {
                            deltas.push(Value::String(delta.to_string()));
                        }
                        let cur_content =
                            item.get("content").and_then(|v| v.as_str()).unwrap_or("");
                        item.insert("content".into(), json!(format!("{cur_content}{delta}")));
                    }
                } else if let Some(c) = payload
                    .get("content")
                    .or_else(|| payload.get("text"))
                    .and_then(|v| v.as_str())
                {
                    item.insert("content".into(), json!(c));
                } else if let Some(parts) = payload
                    .get("content")
                    .or_else(|| payload.get("text"))
                    .and_then(|v| v.as_array())
                {
                    let txt = typed_input_parts_text(parts);
                    if !txt.is_empty() {
                        item.insert("content".into(), json!(txt));
                    }
                }
            }
        }
    }

    // Insert into item_order by seq if missing.
    let in_order = root
        .get("item_order")
        .and_then(|v| v.as_array())
        .map(|arr| arr.iter().any(|x| x.as_str() == Some(item_id.as_str())))
        .unwrap_or(false);
    if !in_order {
        if let Some(item) = root
            .get_mut("items")
            .and_then(|i| i.get_mut(&item_id))
            .and_then(|i| i.as_object_mut())
        {
            item.insert("seq".into(), json!(item_seq));
        }
        let seq_map: HashMap<String, i64> = root
            .get("_item_seq_map")
            .and_then(|v| v.as_object())
            .map(|m| {
                m.iter()
                    .filter_map(|(k, v)| v.as_i64().map(|n| (k.clone(), n)))
                    .collect()
            })
            .unwrap_or_default();
        let item_seqs: HashMap<String, i64> = root
            .get("items")
            .and_then(|v| v.as_object())
            .map(|m| {
                m.iter()
                    .filter_map(|(k, v)| {
                        v.get("seq")
                            .and_then(|s| s.as_i64())
                            .map(|n| (k.clone(), n))
                    })
                    .collect()
            })
            .unwrap_or_default();

        let order_arr = root
            .entry("item_order".to_string())
            .or_insert_with(|| json!([]))
            .as_array_mut();
        if let Some(order) = order_arr {
            let mut pos = order.len();
            for (idx, existing_id_val) in order.iter().enumerate() {
                let iid = existing_id_val.as_str().unwrap_or("");
                let s = seq_map
                    .get(iid)
                    .copied()
                    .or_else(|| item_seqs.get(iid).copied())
                    .unwrap_or(0);
                if s > item_seq {
                    pos = idx;
                    break;
                }
            }
            order.insert(pos, Value::String(item_id.clone()));
        }
        if let Some(sm) = root
            .get_mut("_item_seq_map")
            .and_then(|v| v.as_object_mut())
        {
            sm.insert(item_id.clone(), json!(item_seq));
        }
    } else if let Some(item) = root
        .get_mut("items")
        .and_then(|i| i.get_mut(&item_id))
        .and_then(|i| i.as_object_mut())
    {
        item.entry("seq".to_string())
            .or_insert_with(|| json!(item_seq));
    }

    item_id
}

fn close_turn_items(state: &mut Value, turn_id: &str, status: &str) {
    let item_ids: Vec<String> = state
        .get("turns")
        .and_then(|t| t.get(turn_id))
        .and_then(|t| t.get("items"))
        .and_then(|a| a.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str().map(str::to_string))
                .collect()
        })
        .unwrap_or_default();
    let Some(items) = state.get_mut("items").and_then(|i| i.as_object_mut()) else {
        return;
    };
    for iid in item_ids {
        let Some(item_obj) = items.get_mut(&iid).and_then(|v| v.as_object_mut()) else {
            continue;
        };
        if is_sub_agent_child_item(item_obj) {
            continue;
        }
        let cur = item_obj
            .get("status")
            .and_then(|s| s.as_str())
            .unwrap_or("");
        if !TERMINAL_ITEM_STATUSES.contains(&cur) {
            item_obj.insert("status".into(), json!(status));
        }
    }
}

fn interaction_matches(
    item: &Map<String, Value>,
    request_id: &str,
    payload: &Map<String, Value>,
) -> bool {
    let p_int = payload
        .get("interaction_id")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let p_tc = payload
        .get("tool_call_id")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    for key in ["interaction_id", "request_id", "tool_call_id"] {
        let val = item.get(key).and_then(|v| v.as_str()).unwrap_or("");
        if val == request_id || val == p_int || val == p_tc {
            return true;
        }
    }
    false
}

fn remove_interaction_from_pools(
    state: &mut Value,
    request_id: &str,
    payload: &Map<String, Value>,
) {
    for target in [
        Some(state as *mut Value),
        state.get_mut("core").map(|v| v as *mut Value),
    ] {
        if let Some(ptr) = target {
            let container = unsafe { &mut *ptr };
            if let Some(pool) = container
                .get_mut("interactions")
                .and_then(|v| v.as_array_mut())
            {
                pool.retain(|item| {
                    let Some(obj) = item.as_object() else {
                        return true;
                    };
                    !interaction_matches(obj, request_id, payload)
                });
            }
        }
    }
}

fn apply_approval_response_core(
    state: &mut Value,
    payload: &Map<String, Value>,
    raw_item_id: &str,
) {
    let request_id = payload
        .get("request_id")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .unwrap_or(raw_item_id)
        .to_string();
    if request_id.is_empty() {
        return;
    }
    let resolved_status = payload
        .get("status")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .unwrap_or("resolved")
        .to_string();
    if let Some(requests) = state.as_object_mut().and_then(|r| {
        r.entry("requests".to_string())
            .or_insert_with(|| json!({}))
            .as_object_mut()
    }) {
        let req_val = requests
            .entry(request_id.clone())
            .or_insert_with(|| json!({ "request_id": request_id }));
        if let Some(req) = req_val.as_object_mut() {
            for (k, v) in payload {
                if APPROVAL_REQUEST_FACTS.contains(&k.as_str())
                    && !is_truthy_json(v)
                    && req.get(k).map(is_truthy_json).unwrap_or(false)
                {
                    continue;
                }
                req.insert(k.clone(), v.clone());
            }
            req.insert("status".into(), json!(resolved_status));
        }
        let matching_keys: Vec<String> = requests
            .iter()
            .filter_map(|(k, v)| {
                if k != &request_id
                    && v.get("request_id").and_then(|s| s.as_str()) == Some(request_id.as_str())
                {
                    Some(k.clone())
                } else {
                    None
                }
            })
            .collect();
        for k in matching_keys {
            if let Some(cand) = requests.get_mut(&k).and_then(|v| v.as_object_mut()) {
                for (f, v) in payload {
                    if APPROVAL_REQUEST_FACTS.contains(&f.as_str())
                        && !is_truthy_json(v)
                        && cand.get(f).map(is_truthy_json).unwrap_or(false)
                    {
                        continue;
                    }
                    cand.insert(f.clone(), v.clone());
                }
                cand.insert("status".into(), json!(resolved_status));
            }
        }
    }
    remove_interaction_from_pools(state, &request_id, payload);
}

fn apply_interaction_update_core(
    state: &mut Value,
    payload: &Map<String, Value>,
    raw_item_id: &str,
) {
    let interaction_id = payload
        .get("interaction_id")
        .or_else(|| payload.get("request_id"))
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .unwrap_or(raw_item_id)
        .to_string();
    if interaction_id.is_empty() {
        return;
    }
    let req_id_str = payload
        .get("request_id")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let int_id_str = payload
        .get("interaction_id")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    if let Some(existing_reqs) = state.get("requests").and_then(|v| v.as_object()) {
        for key in [interaction_id.as_str(), req_id_str, int_id_str] {
            if key.is_empty() {
                continue;
            }
            if let Some(st) = existing_reqs
                .get(key)
                .and_then(|r| r.get("status"))
                .and_then(|s| s.as_str())
            {
                if matches!(st, "resolved" | "cancelled" | "expired") {
                    return;
                }
            }
        }
    }
    let lifecycle = payload
        .get("state")
        .or_else(|| payload.get("lifecycle"))
        .and_then(|v| v.as_str())
        .unwrap_or("appearing");
    let status = if lifecycle == "processing" {
        "processing"
    } else {
        "open"
    };
    let request_id = if req_id_str.is_empty() {
        interaction_id.clone()
    } else {
        req_id_str.to_string()
    };
    let item = json!({
        "interaction_id": interaction_id,
        "request_id": request_id,
        "kind": payload.get("kind").and_then(|v| v.as_str()).unwrap_or("approval"),
        "status": status,
        "lifecycle": lifecycle,
        "decision_id": payload.get("decision_id").and_then(|v| v.as_str()).unwrap_or(""),
        "sequence": payload.get("sequence").and_then(|v| v.as_i64()).unwrap_or(0),
        "tool_call_id": payload.get("tool_call_id").and_then(|v| v.as_str()).unwrap_or(""),
        "turn_id": payload.get("turn_id").and_then(|v| v.as_str()).unwrap_or(""),
        "title": payload.get("title").and_then(|v| v.as_str()).unwrap_or(""),
        "options": payload.get("options").filter(|v| v.is_array()).cloned().unwrap_or_else(|| json!([])),
        "scope": payload.get("scope").and_then(|v| v.as_str()).unwrap_or("main"),
        "agent_name": payload.get("agent_name").and_then(|v| v.as_str()).unwrap_or(""),
        "agent_session_id": payload.get("agent_session_id").and_then(|v| v.as_str()).unwrap_or(""),
        "delivered_by": payload.get("delivered_by").and_then(|v| v.as_str()).unwrap_or("main"),
        "project_id": payload.get("project_id").and_then(|v| v.as_str()).unwrap_or(""),
    });

    for ptr in [
        Some(state as *mut Value),
        state.get_mut("core").map(|v| v as *mut Value),
    ] {
        if let Some(p) = ptr {
            let container = unsafe { &mut *p };
            if let Some(pool) = container.as_object_mut().and_then(|m| {
                m.entry("interactions".to_string())
                    .or_insert_with(|| json!([]))
                    .as_array_mut()
            }) {
                let mut replaced = false;
                for existing in pool.iter_mut() {
                    if let Some(ex_obj) = existing.as_object() {
                        if interaction_matches(ex_obj, &interaction_id, payload) {
                            let mut merged = ex_obj.clone();
                            if let Some(item_obj) = item.as_object() {
                                for (k, v) in item_obj {
                                    merged.insert(k.clone(), v.clone());
                                }
                                if !item_obj.get("options").map(is_truthy_json).unwrap_or(false) {
                                    if let Some(old_opts) =
                                        ex_obj.get("options").filter(|v| is_truthy_json(v))
                                    {
                                        merged.insert("options".into(), old_opts.clone());
                                    }
                                }
                            }
                            *existing = Value::Object(merged);
                            replaced = true;
                            break;
                        }
                    }
                }
                if !replaced {
                    pool.push(item.clone());
                }
            }
        }
    }

    if let Some(requests) = state.as_object_mut().and_then(|r| {
        r.entry("requests".to_string())
            .or_insert_with(|| json!({}))
            .as_object_mut()
    }) {
        let req = requests
            .entry(request_id.clone())
            .or_insert_with(|| json!({ "request_id": request_id }))
            .as_object_mut();
        if let Some(req_obj) = req {
            let st = req_obj.get("status").and_then(|s| s.as_str()).unwrap_or("");
            if !matches!(st, "resolved" | "cancelled" | "expired") {
                for (k, v) in payload {
                    req_obj.insert(k.clone(), v.clone());
                }
                req_obj.insert("status".into(), json!(status));
            }
        }
    }
}

fn apply_artifact_core(
    state: &mut Value,
    event_id: &str,
    item_id: &str,
    payload: &Map<String, Value>,
    artifacts: &[Value],
) {
    let fallback: Vec<Value> = if !artifacts.is_empty() {
        artifacts.to_vec()
    } else if !payload.is_empty() {
        vec![Value::Object(payload.clone())]
    } else {
        Vec::new()
    };
    let has_event_artifacts = !artifacts.is_empty();
    let Some(reg) = state.as_object_mut().and_then(|r| {
        r.entry("artifacts".to_string())
            .or_insert_with(|| json!({}))
            .as_object_mut()
    }) else {
        return;
    };
    for art in fallback {
        let Some(art_obj) = art.as_object() else {
            continue;
        };
        let aid = art_obj
            .get("artifact_id")
            .or_else(|| art_obj.get("id"))
            .and_then(|v| v.as_str())
            .filter(|s| !s.is_empty())
            .unwrap_or(if !item_id.is_empty() {
                item_id
            } else {
                event_id
            })
            .to_string();
        let mut copy = art_obj.clone();
        if let Some(meta) = copy.get_mut("metadata").and_then(|m| m.as_object_mut()) {
            meta.remove("image_data_url");
        }
        if has_event_artifacts {
            copy.remove("content");
        }
        reg.insert(aid, Value::Object(copy));
    }
}

pub(crate) fn apply_run_item_event_in_place_core(
    state: &mut Value,
    payload_val: &Value,
    env_seq: i64,
) {
    let Some(ev) = payload_val.as_object() else {
        return;
    };
    let event_id = ev.get("event_id").and_then(|v| v.as_str()).unwrap_or("");
    let thread_id = ev.get("thread_id").and_then(|v| v.as_str()).unwrap_or("");
    if event_id.is_empty() || thread_id.is_empty() {
        return;
    }
    if !push_seen_id(state, event_id) {
        return;
    }
    let seq = ev.get("seq").and_then(|v| v.as_i64()).unwrap_or(env_seq);
    if let Some(root) = state.as_object_mut() {
        root.insert("thread_id".into(), json!(thread_id));
        let prev = root
            .get("snapshot_seq")
            .and_then(|v| v.as_i64())
            .unwrap_or(0);
        let mut next_seq = prev.max(seq);
        if seq == 0 {
            next_seq += 1;
        }
        root.insert("snapshot_seq".into(), json!(next_seq));
    }

    let kind = ev.get("kind").and_then(|v| v.as_str()).unwrap_or("");
    let status = ev
        .get("status")
        .and_then(|v| v.as_str())
        .unwrap_or("running");
    let turn_id = ev.get("turn_id").and_then(|v| v.as_str()).unwrap_or("");
    let run_id = ev.get("run_id").and_then(|v| v.as_str()).unwrap_or("");
    let item_id = ev.get("item_id").and_then(|v| v.as_str()).unwrap_or("");
    let parent_item_id = ev
        .get("parent_item_id")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let inner_payload = ev
        .get("payload")
        .and_then(|v| v.as_object())
        .cloned()
        .unwrap_or_default();
    let artifacts = ev
        .get("artifacts")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    let usage = ev
        .get("usage")
        .and_then(|v| v.as_object())
        .cloned()
        .unwrap_or_default();
    let metadata = ev
        .get("metadata")
        .and_then(|v| v.as_object())
        .cloned()
        .unwrap_or_default();

    if kind == "status" {
        let st = inner_payload
            .get("status")
            .and_then(|v| v.as_str())
            .filter(|s| !s.is_empty())
            .unwrap_or(status);
        let annotation_only = item_id.ends_with(":sub-agent-wait");
        let existing_status = state
            .get("turns")
            .and_then(|t| t.get(turn_id))
            .and_then(|t| t.get("status"))
            .and_then(|s| s.as_str())
            .unwrap_or("")
            .to_string();
        {
            let turn_opt = upsert_core_turn(state, turn_id, kind, seq, run_id);
            apply_turn_metrics(turn_opt, kind, &inner_payload, &usage, false);
        }
        if TERMINAL_TURN_STATUSES.contains(&existing_status.as_str()) && st != existing_status {
            if !usage.is_empty() && !is_context_metrics_event(kind, &inner_payload, &usage) {
                if let Some(t) = state
                    .get_mut("turns")
                    .and_then(|ts| ts.get_mut(turn_id))
                    .and_then(|t| t.as_object_mut())
                {
                    let mut merged = t
                        .get("usage")
                        .and_then(|u| u.as_object())
                        .cloned()
                        .unwrap_or_default();
                    for (k, v) in &usage {
                        merged.insert(k.clone(), v.clone());
                    }
                    t.insert("usage".into(), Value::Object(merged));
                }
            }
            recompute_thread_status_core(state);
            return;
        }
        if !st.is_empty() && !annotation_only {
            if let Some(root) = state.as_object_mut() {
                root.insert("status".into(), json!(st));
            }
            if let Some(t) = state
                .get_mut("turns")
                .and_then(|ts| ts.get_mut(turn_id))
                .and_then(|t| t.as_object_mut())
            {
                t.insert("status".into(), json!(st));
            }
        }
        if !usage.is_empty() && !is_context_metrics_event(kind, &inner_payload, &usage) {
            if let Some(t) = state
                .get_mut("turns")
                .and_then(|ts| ts.get_mut(turn_id))
                .and_then(|t| t.as_object_mut())
            {
                let mut merged = t
                    .get("usage")
                    .and_then(|u| u.as_object())
                    .cloned()
                    .unwrap_or_default();
                for (k, v) in &usage {
                    merged.insert(k.clone(), v.clone());
                }
                t.insert("usage".into(), Value::Object(merged));
            }
        }
        if let Some(dur) = inner_payload.get("duration_ms").and_then(|v| {
            if v.is_boolean() {
                None
            } else {
                v.as_f64()
            }
        }) {
            if let Some(t) = state
                .get_mut("turns")
                .and_then(|ts| ts.get_mut(turn_id))
                .and_then(|t| t.as_object_mut())
            {
                t.insert("duration_ms".into(), json!(dur.round().max(0.0) as i64));
            }
        }
        if matches!(st, "failed" | "cancelled" | "error")
            && (inner_payload
                .get("message")
                .map(is_truthy_json)
                .unwrap_or(false)
                || inner_payload
                    .get("raw_end_reason")
                    .map(is_truthy_json)
                    .unwrap_or(false))
        {
            let iid = upsert_core_item(
                state,
                event_id,
                thread_id,
                turn_id,
                parent_item_id,
                item_id,
                kind,
                status,
                seq,
                &inner_payload,
                &artifacts,
                &usage,
            );
            if let Some(items_arr) = state
                .get_mut("turns")
                .and_then(|ts| ts.get_mut(turn_id))
                .and_then(|t| t.get_mut("items"))
                .and_then(|a| a.as_array_mut())
            {
                if !items_arr.iter().any(|x| x.as_str() == Some(iid.as_str())) {
                    items_arr.push(Value::String(iid));
                }
            }
            if let Some(root) = state.as_object_mut() {
                root.insert("last_error".into(), Value::Object(inner_payload.clone()));
            }
        }
        if !turn_id.is_empty() && TERMINAL_TURN_STATUSES.contains(&st) {
            close_turn_items(state, turn_id, st);
            reconcile_terminal_requests_core(state);
        }
        return;
    }

    if kind == "interaction_update" {
        apply_interaction_update_core(state, &inner_payload, item_id);
        recompute_thread_status_core(state);
        return;
    }

    if kind == "approval_response" {
        apply_approval_response_core(state, &inner_payload, item_id);
        let nested_child = !parent_item_id.is_empty()
            || inner_payload
                .get("sub_agent")
                .map(|v| v.is_object())
                .unwrap_or(false);
        upsert_core_item(
            state,
            event_id,
            thread_id,
            turn_id,
            parent_item_id,
            item_id,
            kind,
            status,
            seq,
            &inner_payload,
            &artifacts,
            &usage,
        );
        let snap_seq = state
            .get("snapshot_seq")
            .and_then(|v| v.as_i64())
            .unwrap_or(0);
        if let Some(t) = state
            .get_mut("turns")
            .and_then(|ts| ts.get_mut(turn_id))
            .and_then(|t| t.as_object_mut())
        {
            if !item_id.is_empty() {
                if let Some(arr) = t
                    .entry("items".to_string())
                    .or_insert_with(|| json!([]))
                    .as_array_mut()
                {
                    if !arr.iter().any(|x| x.as_str() == Some(item_id)) {
                        arr.push(Value::String(item_id.to_string()));
                    }
                }
            }
            t.insert("last_kind".into(), json!(kind));
            t.insert(
                "last_seq".into(),
                json!(if seq != 0 { seq } else { snap_seq }),
            );
            if !run_id.is_empty() {
                t.insert("run_id".into(), json!(run_id));
            }
            let cur_st = t.get("status").and_then(|s| s.as_str()).unwrap_or("");
            if !nested_child && !matches!(cur_st, "failed" | "cancelled" | "skipped" | "paused") {
                t.insert("status".into(), json!("running"));
            }
        }
        recompute_thread_status_core(state);
        return;
    }

    if kind == "usage" {
        let snap_seq = state
            .get("snapshot_seq")
            .and_then(|v| v.as_i64())
            .unwrap_or(0);
        let Some(turn) = upsert_core_turn(state, turn_id, kind, seq, run_id) else {
            return;
        };
        if inner_payload.get("replace").and_then(|v| v.as_bool()) == Some(true) {
            if !usage.is_empty() {
                if !parent_item_id.is_empty() {
                    if let Some(ccm) = turn
                        .entry("child_context_metrics".to_string())
                        .or_insert_with(|| json!({}))
                        .as_object_mut()
                    {
                        ccm.insert(parent_item_id.to_string(), Value::Object(usage));
                    }
                } else {
                    turn.insert("context_metrics".into(), Value::Object(usage));
                }
            }
            return;
        }
        if !usage.is_empty() {
            let call_id = if !item_id.is_empty() {
                item_id
            } else {
                event_id
            };
            let call_seq = if seq != 0 { seq } else { snap_seq };
            let mut call = json!({
                "id": call_id,
                "seq": call_seq,
                "parent_item_id": parent_item_id,
                "usage": Value::Object(usage),
            });
            let calls = turn
                .entry("usage_calls".to_string())
                .or_insert_with(|| json!([]))
                .as_array_mut();
            if let Some(calls_arr) = calls {
                if let Some(idx) = calls_arr
                    .iter()
                    .position(|r| r.get("id").and_then(|v| v.as_str()) == Some(call_id))
                {
                    if let Some(prev_seq) = calls_arr[idx].get("seq").and_then(|v| v.as_i64()) {
                        if let Some(obj) = call.as_object_mut() {
                            obj.insert("seq".into(), json!(prev_seq));
                        }
                    }
                    calls_arr[idx] = call;
                } else {
                    calls_arr.push(call);
                }
                let mut total = Value::Object(Map::new());
                for row in calls_arr.iter() {
                    let has_parent = row
                        .get("parent_item_id")
                        .and_then(|v| v.as_str())
                        .map(|s| !s.is_empty())
                        .unwrap_or(false);
                    if !has_parent {
                        if let Some(u) = row.get("usage").and_then(|v| v.as_object()) {
                            total = merge_dict_values(Some(&total), u);
                        }
                    }
                }
                turn.insert("usage".into(), total);
            }
        }
        return;
    }

    if kind == "artifact" || !artifacts.is_empty() {
        apply_artifact_core(state, event_id, item_id, &inner_payload, &artifacts);
    }

    if inner_payload.get("type").and_then(|v| v.as_str()) == Some("subAgentStatus") {
        if let Some(sa) = inner_payload.get("sub_agent").and_then(|v| v.as_object()) {
            if sa.get("status").and_then(|v| v.as_str()) == Some("deleted") {
                if let Some(deleted) = state.as_object_mut().and_then(|r| {
                    r.entry("deleted_agents".to_string())
                        .or_insert_with(|| json!({}))
                        .as_object_mut()
                }) {
                    for k in ["name", "agent", "session_id", "sub_session_id"] {
                        if let Some(v) = sa
                            .get(k)
                            .and_then(|s| s.as_str())
                            .map(str::trim)
                            .filter(|s| !s.is_empty())
                        {
                            deleted.insert(v.to_string(), json!(true));
                        }
                    }
                }
            }
        }
    }

    let terminal_turn_status = state
        .get("turns")
        .and_then(|ts| ts.get(turn_id))
        .and_then(|t| t.get("status"))
        .and_then(|s| s.as_str())
        .filter(|s| TERMINAL_TURN_STATUSES.contains(s))
        .unwrap_or("")
        .to_string();
    let nested_child = !parent_item_id.is_empty()
        || inner_payload
            .get("sub_agent")
            .map(|v| v.is_object())
            .unwrap_or(false);

    if kind == "approval_request" {
        let req_id = inner_payload
            .get("request_id")
            .and_then(|v| v.as_str())
            .filter(|s| !s.is_empty())
            .unwrap_or(if !item_id.is_empty() {
                item_id
            } else {
                event_id
            });
        if let Some(st) = state
            .get("requests")
            .and_then(|r| r.get(req_id))
            .and_then(|r| r.get("status"))
            .and_then(|s| s.as_str())
        {
            if matches!(st, "resolved" | "cancelled" | "expired") {
                return;
            }
        }
    }

    let upserted_item_id = upsert_core_item(
        state,
        event_id,
        thread_id,
        turn_id,
        parent_item_id,
        item_id,
        kind,
        status,
        seq,
        &inner_payload,
        &artifacts,
        &usage,
    );

    if !terminal_turn_status.is_empty() && !nested_child {
        if let Some(item_obj) = state
            .get_mut("items")
            .and_then(|i| i.get_mut(&upserted_item_id))
            .and_then(|i| i.as_object_mut())
        {
            item_obj.insert("status".into(), json!(terminal_turn_status));
        }
        if let Some(t) = upsert_core_turn(state, turn_id, kind, seq, run_id) {
            if !item_id.is_empty() {
                if let Some(arr) = t
                    .entry("items".to_string())
                    .or_insert_with(|| json!([]))
                    .as_array_mut()
                {
                    if !arr.iter().any(|x| x.as_str() == Some(item_id)) {
                        arr.push(Value::String(item_id.to_string()));
                    }
                }
            }
        }
        recompute_thread_status_core(state);
        return;
    }

    if kind == "approval_request" {
        if let Some(item_obj) = state
            .get_mut("items")
            .and_then(|i| i.get_mut(&upserted_item_id))
            .and_then(|i| i.as_object_mut())
        {
            item_obj.insert("status".into(), json!("waiting"));
        }
        if !nested_child {
            if let Some(root) = state.as_object_mut() {
                root.insert("status".into(), json!("waiting"));
            }
        }
        let req_id = inner_payload
            .get("request_id")
            .and_then(|v| v.as_str())
            .filter(|s| !s.is_empty())
            .unwrap_or(if !item_id.is_empty() {
                item_id
            } else {
                event_id
            })
            .to_string();
        if let Some(reqs) = state.as_object_mut().and_then(|r| {
            r.entry("requests".to_string())
                .or_insert_with(|| json!({}))
                .as_object_mut()
        }) {
            let mut rec = reqs
                .get(&req_id)
                .and_then(|v| v.as_object())
                .cloned()
                .unwrap_or_default();
            for (k, v) in &inner_payload {
                if APPROVAL_REQUEST_FACTS.contains(&k.as_str())
                    && !is_truthy_json(v)
                    && rec.get(k).map(is_truthy_json).unwrap_or(false)
                {
                    continue;
                }
                rec.insert(k.clone(), v.clone());
            }
            rec.insert("request_id".into(), json!(req_id));
            rec.insert("status".into(), json!("open"));
            rec.insert("item_id".into(), json!(upserted_item_id));
            rec.insert("turn_id".into(), json!(turn_id));
            let rec_val = Value::Object(rec);
            reqs.insert(req_id.clone(), rec_val.clone());
            let tc_id = inner_payload
                .get("tool_call_id")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            if !tc_id.is_empty() && tc_id != req_id {
                reqs.insert(tc_id.to_string(), rec_val);
            }
        }
    } else if kind == "error" {
        let content_fallback = state
            .get("items")
            .and_then(|i| i.get(&upserted_item_id))
            .and_then(|i| i.get("content"))
            .and_then(|c| c.as_str())
            .unwrap_or("")
            .to_string();
        if let Some(item_obj) = state
            .get_mut("items")
            .and_then(|i| i.get_mut(&upserted_item_id))
            .and_then(|i| i.as_object_mut())
        {
            item_obj.insert("status".into(), json!("failed"));
        }
        if let Some(root) = state.as_object_mut() {
            let err_val = if inner_payload.is_empty() {
                json!({ "message": content_fallback })
            } else {
                Value::Object(inner_payload.clone())
            };
            root.insert("last_error".into(), err_val);
            if is_terminal_error_event(item_id, &inner_payload, &metadata) {
                root.insert("status".into(), json!("failed"));
            }
        }
    } else if status == "waiting" {
        if let Some(item_obj) = state
            .get_mut("items")
            .and_then(|i| i.get_mut(&upserted_item_id))
            .and_then(|i| i.as_object_mut())
        {
            item_obj.insert("status".into(), json!("waiting"));
        }
        if let Some(root) = state.as_object_mut() {
            root.insert("status".into(), json!("waiting"));
        }
    } else if TERMINAL_TURN_STATUSES.contains(&status) {
        if let Some(item_obj) = state
            .get_mut("items")
            .and_then(|i| i.get_mut(&upserted_item_id))
            .and_then(|i| i.as_object_mut())
        {
            item_obj.insert("status".into(), json!(status));
        }
    } else {
        if let Some(item_obj) = state
            .get_mut("items")
            .and_then(|i| i.get_mut(&upserted_item_id))
            .and_then(|i| i.as_object_mut())
        {
            item_obj.insert("status".into(), json!(status));
        }
        if !turn_id.is_empty() && !nested_child {
            let cur_st = state.get("status").and_then(|s| s.as_str()).unwrap_or("");
            if cur_st != "paused" {
                if let Some(root) = state.as_object_mut() {
                    root.insert("status".into(), json!("running"));
                }
            }
        }
    }

    let has_turn = {
        let Some(t) = upsert_core_turn(state, turn_id, kind, seq, run_id) else {
            recompute_thread_status_core(state);
            return;
        };
        if !item_id.is_empty() {
            if let Some(arr) = t
                .entry("items".to_string())
                .or_insert_with(|| json!([]))
                .as_array_mut()
            {
                if !arr.iter().any(|x| x.as_str() == Some(item_id)) {
                    arr.push(Value::String(item_id.to_string()));
                }
            }
        }
        true
    };
    if !has_turn {
        return;
    }

    if kind == "approval_request" {
        if !nested_child {
            if let Some(t) = state
                .get_mut("turns")
                .and_then(|ts| ts.get_mut(turn_id))
                .and_then(|t| t.as_object_mut())
            {
                t.insert("status".into(), json!("waiting"));
            }
            if let Some(root) = state.as_object_mut() {
                root.insert("status".into(), json!("waiting"));
            }
        }
    } else if TERMINAL_TURN_STATUSES.contains(&status)
        && kind == "error"
        && is_terminal_error_event(item_id, &inner_payload, &metadata)
    {
        if let Some(t) = state
            .get_mut("turns")
            .and_then(|ts| ts.get_mut(turn_id))
            .and_then(|t| t.as_object_mut())
        {
            t.insert("status".into(), json!(status));
        }
        reconcile_terminal_requests_core(state);
        recompute_thread_status_core(state);
    } else if status == "waiting" {
        if let Some(t) = state
            .get_mut("turns")
            .and_then(|ts| ts.get_mut(turn_id))
            .and_then(|t| t.as_object_mut())
        {
            t.insert("status".into(), json!("waiting"));
        }
        if let Some(root) = state.as_object_mut() {
            root.insert("status".into(), json!("waiting"));
        }
    } else if !turn_id.is_empty() {
        let cur_turn_st = state
            .get("turns")
            .and_then(|ts| ts.get(turn_id))
            .and_then(|t| t.get("status"))
            .and_then(|s| s.as_str())
            .unwrap_or("");
        if !TERMINAL_TURN_STATUSES.contains(&cur_turn_st) && cur_turn_st != "paused" {
            if let Some(t) = state
                .get_mut("turns")
                .and_then(|ts| ts.get_mut(turn_id))
                .and_then(|t| t.as_object_mut())
            {
                t.insert("status".into(), json!("running"));
            }
            recompute_thread_status_core(state);
        }
    }
}

pub(crate) fn sync_turns_from_core(state: &mut Value, only_turn_id: Option<&str>) {
    let Some(core_turns) = state
        .get("core")
        .and_then(|c| c.get("turns"))
        .and_then(|t| t.as_object())
        .cloned()
    else {
        return;
    };
    let Some(turns) = state.as_object_mut().and_then(|r| {
        r.entry("turns".to_string())
            .or_insert_with(|| json!({}))
            .as_object_mut()
    }) else {
        return;
    };
    for (tid, ct_val) in core_turns {
        if let Some(only) = only_turn_id {
            if tid != only {
                continue;
            }
        }
        let Some(ct) = ct_val.as_object() else {
            continue;
        };
        let entry = turns
            .entry(tid.clone())
            .or_insert_with(|| json!({ "turn_id": tid, "items": [] }));
        if let Some(t) = entry.as_object_mut() {
            let status = ct
                .get("status")
                .or_else(|| t.get("status"))
                .and_then(|s| s.as_str())
                .unwrap_or("running");
            let last_seq = ct
                .get("last_seq")
                .or_else(|| t.get("last_seq"))
                .and_then(|s| s.as_i64())
                .unwrap_or(0);
            t.insert("status".into(), json!(status));
            t.insert("last_seq".into(), json!(last_seq));
            if let Some(run_id) = ct
                .get("run_id")
                .and_then(|v| v.as_str())
                .filter(|s| !s.is_empty())
            {
                t.insert("run_id".into(), json!(run_id));
            }
            if let Some(u) = ct.get("usage").filter(|v| v.is_object()) {
                t.insert("usage".into(), u.clone());
            }
            if let Some(cm) = ct.get("context_metrics").filter(|v| v.is_object()) {
                t.insert("context_metrics".into(), cm.clone());
            }
        }
    }
}

fn sync_status_from_core(state: &mut Value) {
    let Some(core_status) = state
        .get("core")
        .and_then(|c| c.get("status"))
        .and_then(|s| s.as_str())
        .map(str::to_string)
    else {
        return;
    };
    let mapped = if core_status == "paused" {
        Some("paused")
    } else if core_status == "cancelled" {
        Some("cancelled")
    } else if TERMINAL_ERROR_STATUSES.contains(&core_status.as_str()) {
        Some("failed")
    } else if matches!(
        core_status.as_str(),
        "idle" | "running" | "waiting" | "completed"
    ) {
        Some(core_status.as_str())
    } else {
        None
    };
    if let (Some(st), Some(root)) = (mapped, state.as_object_mut()) {
        root.insert("status".into(), json!(st));
    }
}

fn queue_order_key(item: &Value) -> (i64, i64, String) {
    let qid = item
        .get("queue_item_id")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    if let Some(pos) = item.get("position") {
        if !pos.is_boolean() {
            if let Some(n) = pos.as_i64() {
                return (0, n, qid);
            }
            if let Some(f) = pos.as_f64() {
                return (0, f as i64, qid);
            }
        }
    }
    let seq = item.get("seq").and_then(|v| v.as_i64()).unwrap_or(0);
    (1, seq, qid)
}

fn apply_queue_item(state: &mut Value, env: &Envelope, forced_status: Option<&str>) {
    let payload = env.payload.as_object();
    let qid = env
        .item_id
        .as_deref()
        .filter(|s| !s.is_empty())
        .or_else(|| {
            payload.and_then(|p| {
                p.get("queue_item_id")
                    .or_else(|| p.get("queueItemId"))
                    .and_then(|v| v.as_str())
            })
        })
        .map(str::trim)
        .unwrap_or("")
        .to_string();
    if qid.is_empty() {
        return;
    }
    let mut queue = state
        .get("queue")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    let existing_idx = queue
        .iter()
        .position(|x| x.get("queue_item_id").and_then(|v| v.as_str()) == Some(qid.as_str()));
    let mut current = existing_idx
        .and_then(|idx| queue[idx].as_object().cloned())
        .unwrap_or_else(|| {
            let mut m = Map::new();
            m.insert("queue_item_id".into(), json!(qid));
            m
        });
    if let Some(p) = payload {
        for (k, v) in p {
            current.insert(k.clone(), v.clone());
        }
    }
    let status = forced_status
        .map(str::to_string)
        .or_else(|| {
            payload
                .and_then(|p| p.get("status"))
                .and_then(|v| v.as_str())
                .filter(|s| !s.is_empty())
                .map(str::to_string)
        })
        .or_else(|| {
            current
                .get("status")
                .and_then(|v| v.as_str())
                .filter(|s| !s.is_empty())
                .map(str::to_string)
        })
        .unwrap_or_else(|| "queued".into());
    let mode = payload
        .and_then(|p| p.get("mode"))
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .or_else(|| {
            current
                .get("mode")
                .and_then(|v| v.as_str())
                .filter(|s| !s.is_empty())
        })
        .unwrap_or("next_turn")
        .to_string();
    let input_val = payload
        .and_then(|p| p.get("input"))
        .cloned()
        .or_else(|| current.get("input").cloned())
        .unwrap_or(Value::Null);

    current.insert("queue_item_id".into(), json!(qid));
    current.insert("status".into(), json!(status));
    current.insert("mode".into(), json!(mode));
    current.insert("input".into(), input_val);
    current.insert("seq".into(), json!(env.seq));
    current.insert("last_method".into(), json!(env.method));

    if matches!(
        status.as_str(),
        "cancelled" | "deleted" | "dispatched" | "sent"
    ) {
        queue.retain(|x| x.get("queue_item_id").and_then(|v| v.as_str()) != Some(qid.as_str()));
    } else if let Some(idx) = existing_idx {
        queue[idx] = Value::Object(current);
    } else {
        queue.push(Value::Object(current));
    }
    if let Some(root) = state.as_object_mut() {
        root.insert("queue".into(), Value::Array(queue));
    }
}

fn projector_apply_in_place(state: &mut Value, env: &Envelope) {
    if !push_seen_id(state, &env.event_id) {
        return;
    }
    if let Some(root) = state.as_object_mut() {
        root.insert("thread_id".into(), json!(env.thread_id));
        let prev = root
            .get("snapshot_seq")
            .and_then(|v| v.as_i64())
            .unwrap_or(0);
        root.insert("snapshot_seq".into(), json!(prev.max(env.seq)));
    }

    match env.method.as_str() {
        "thread/started" => {
            let payload = env.payload.as_object();
            let cur_status = state
                .get("status")
                .and_then(|s| s.as_str())
                .unwrap_or("idle")
                .to_string();
            let st = payload
                .and_then(|p| p.get("status").and_then(|v| v.as_str()))
                .filter(|s| !s.is_empty())
                .unwrap_or(&cur_status)
                .to_string();
            if let Some(root) = state.as_object_mut() {
                root.insert("status".into(), json!(st));
                let sess = root
                    .entry("session".to_string())
                    .or_insert_with(|| json!({}));
                if !sess.is_object() {
                    *sess = json!({});
                }
                if let (Some(sobj), Some(pobj)) = (sess.as_object_mut(), payload) {
                    for k in ["member_id", "title"] {
                        if let Some(v) = pobj.get(k) {
                            sobj.insert(k.to_string(), v.clone());
                        }
                    }
                }
            }
        }
        "turn/accepted" => {
            let payload = env.payload.as_object();
            let turn_id = env
                .turn_id
                .as_deref()
                .filter(|s| !s.is_empty())
                .or_else(|| {
                    payload.and_then(|p| {
                        p.get("turn_id")
                            .or_else(|| p.get("turnId"))
                            .and_then(|v| v.as_str())
                    })
                })
                .map(str::trim)
                .unwrap_or("")
                .to_string();
            if turn_id.is_empty() {
                return;
            }
            if let Some(root) = state.as_object_mut() {
                let turns = root
                    .entry("turns".to_string())
                    .or_insert_with(|| json!({}))
                    .as_object_mut();
                if let Some(turns_map) = turns {
                    let mut turn = turns_map
                        .get(&turn_id)
                        .and_then(|v| v.as_object())
                        .cloned()
                        .unwrap_or_default();
                    let st = payload
                        .and_then(|p| p.get("status").and_then(|v| v.as_str()))
                        .filter(|s| !s.is_empty())
                        .unwrap_or("running");
                    let work_root = payload
                        .and_then(|p| {
                            p.get("work_root")
                                .or_else(|| p.get("workRoot"))
                                .and_then(|v| v.as_str())
                        })
                        .unwrap_or("");
                    turn.insert("turn_id".into(), json!(turn_id));
                    turn.insert("status".into(), json!(st));
                    turn.insert("seq".into(), json!(env.seq));
                    turn.insert("last_seq".into(), json!(env.seq));
                    turn.insert("last_method".into(), json!(env.method));
                    turn.insert("created_at".into(), json!(env.created_at_iso));
                    turn.insert(
                        "input".into(),
                        payload
                            .and_then(|p| p.get("input"))
                            .cloned()
                            .unwrap_or(Value::Null),
                    );
                    turn.insert("work_root".into(), json!(work_root));
                    if let Some(rs) = payload
                        .and_then(|p| p.get("runtime_snapshot"))
                        .filter(|v| v.is_object())
                    {
                        turn.insert("runtime_snapshot".into(), rs.clone());
                    }
                    if let Some(origin) = payload
                        .and_then(|p| p.get("origin").and_then(|v| v.as_str()))
                        .map(str::trim)
                        .filter(|s| !s.is_empty())
                    {
                        turn.insert("origin".into(), json!(origin));
                    }
                    turn.entry("items".to_string()).or_insert_with(|| json!([]));
                    turns_map.insert(turn_id, Value::Object(turn));
                }
                root.insert("status".into(), json!("running"));
                let sess = root
                    .entry("session".to_string())
                    .or_insert_with(|| json!({}));
                if !sess.is_object() {
                    *sess = json!({});
                }
                if let (Some(sobj), Some(pobj)) = (sess.as_object_mut(), payload) {
                    for k in ["member_id", "title"] {
                        if !sobj.contains_key(k) {
                            if let Some(v) = pobj.get(k) {
                                sobj.insert(k.to_string(), v.clone());
                            }
                        }
                    }
                }
            }
        }
        "turn/started" => {
            let payload = env.payload.as_object();
            let turn_id = env
                .turn_id
                .as_deref()
                .filter(|s| !s.is_empty())
                .or_else(|| {
                    payload.and_then(|p| {
                        p.get("turn_id")
                            .or_else(|| p.get("turnId"))
                            .and_then(|v| v.as_str())
                    })
                })
                .map(str::trim)
                .unwrap_or("")
                .to_string();
            if turn_id.is_empty() {
                return;
            }
            if let Some(root) = state.as_object_mut() {
                if let Some(turns_map) = root
                    .entry("turns".to_string())
                    .or_insert_with(|| json!({}))
                    .as_object_mut()
                {
                    let entry = turns_map.entry(turn_id.clone()).or_insert_with(
                        || json!({ "turn_id": turn_id, "status": "running", "items": [] }),
                    );
                    if let Some(t) = entry.as_object_mut() {
                        t.entry("items".to_string()).or_insert_with(|| json!([]));
                        if let Some(p) = payload {
                            for (k, v) in p {
                                t.insert(k.clone(), v.clone());
                            }
                        }
                        let st = payload
                            .and_then(|p| p.get("status").and_then(|v| v.as_str()))
                            .filter(|s| !s.is_empty())
                            .unwrap_or("running");
                        t.insert("status".into(), json!(st));
                        t.insert("seq".into(), json!(env.seq));
                        t.insert("last_seq".into(), json!(env.seq));
                        t.insert("last_method".into(), json!(env.method));
                    }
                }
                root.insert("status".into(), json!("running"));
                if payload.and_then(|p| p.get("resumed").and_then(|v| v.as_bool())) == Some(true) {
                    let core = root
                        .entry("core".to_string())
                        .or_insert_with(|| empty_core_snapshot(&env.thread_id));
                    if let Some(core_obj) = core.as_object_mut() {
                        if let Some(cturns) = core_obj
                            .entry("turns".to_string())
                            .or_insert_with(|| json!({}))
                            .as_object_mut()
                        {
                            let ct = cturns
                                .entry(turn_id.clone())
                                .or_insert_with(|| json!({ "turn_id": turn_id, "items": [] }));
                            if let Some(ct_obj) = ct.as_object_mut() {
                                ct_obj.insert("status".into(), json!("running"));
                                ct_obj.insert(
                                    "run_id".into(),
                                    payload
                                        .and_then(|p| p.get("run_id"))
                                        .cloned()
                                        .unwrap_or(Value::Null),
                                );
                                ct_obj.insert("last_seq".into(), json!(env.seq));
                            }
                        }
                        core_obj.insert("status".into(), json!("running"));
                        core_obj.remove("last_error");
                    }
                }
            }
        }
        "item/started" => {
            let payload = env.payload.as_object();
            let item_id = env
                .item_id
                .as_deref()
                .filter(|s| !s.is_empty())
                .or_else(|| {
                    payload.and_then(|p| {
                        p.get("item_id")
                            .or_else(|| p.get("itemId"))
                            .and_then(|v| v.as_str())
                    })
                })
                .map(str::trim)
                .unwrap_or("")
                .to_string();
            if item_id.is_empty() {
                return;
            }
            let turn_id = env
                .turn_id
                .as_deref()
                .filter(|s| !s.is_empty())
                .or_else(|| {
                    payload.and_then(|p| {
                        p.get("turn_id")
                            .or_else(|| p.get("turnId"))
                            .and_then(|v| v.as_str())
                    })
                })
                .map(str::trim)
                .unwrap_or("")
                .to_string();
            if let Some(root) = state.as_object_mut() {
                if let Some(items_map) = root
                    .entry("items".to_string())
                    .or_insert_with(|| json!({}))
                    .as_object_mut()
                {
                    let mut item = items_map
                        .get(&item_id)
                        .and_then(|v| v.as_object())
                        .cloned()
                        .unwrap_or_default();
                    let prev_seq = item.get("seq").and_then(|v| v.as_i64()).unwrap_or(0);
                    let min_seq = if prev_seq > 0 {
                        prev_seq.min(env.seq)
                    } else {
                        env.seq
                    };
                    let content_val = payload
                        .and_then(|p| p.get("content"))
                        .cloned()
                        .or_else(|| item.get("content").cloned())
                        .unwrap_or_else(|| json!(""));
                    item.insert("item_id".into(), json!(item_id));
                    item.insert(
                        "turn_id".into(),
                        if turn_id.is_empty() {
                            Value::Null
                        } else {
                            json!(turn_id)
                        },
                    );
                    item.insert(
                        "parent_item_id".into(),
                        match &env.parent_item_id {
                            Some(s) => json!(s),
                            None => Value::Null,
                        },
                    );
                    item.insert(
                        "type".into(),
                        json!(payload
                            .and_then(|p| p.get("type").and_then(|v| v.as_str()))
                            .filter(|s| !s.is_empty())
                            .unwrap_or("item")),
                    );
                    item.insert(
                        "status".into(),
                        json!(payload
                            .and_then(|p| p.get("status").and_then(|v| v.as_str()))
                            .filter(|s| !s.is_empty())
                            .unwrap_or("running")),
                    );
                    item.insert("content".into(), content_val);
                    item.insert("seq".into(), json!(min_seq));
                    item.insert("last_seq".into(), json!(env.seq));
                    item.insert("last_method".into(), json!(env.method));
                    item.entry("deltas".to_string())
                        .or_insert_with(|| json!([]));
                    if let Some(origin) = payload
                        .and_then(|p| p.get("origin").and_then(|v| v.as_str()))
                        .map(str::trim)
                        .filter(|s| !s.is_empty())
                    {
                        item.insert("origin".into(), json!(origin));
                        if let Some(role) = payload
                            .and_then(|p| p.get("role").and_then(|v| v.as_str()))
                            .filter(|s| !s.is_empty())
                        {
                            item.insert("role".into(), json!(role));
                        }
                    }
                    items_map.insert(item_id.clone(), Value::Object(item));
                }
                if let Some(order) = root
                    .entry("item_order".to_string())
                    .or_insert_with(|| json!([]))
                    .as_array_mut()
                {
                    if !order.iter().any(|x| x.as_str() == Some(item_id.as_str())) {
                        order.push(Value::String(item_id.clone()));
                    }
                }
                if !turn_id.is_empty() {
                    if let Some(turns_map) = root
                        .entry("turns".to_string())
                        .or_insert_with(|| json!({}))
                        .as_object_mut()
                    {
                        let entry = turns_map.entry(turn_id.clone()).or_insert_with(
                            || json!({ "turn_id": turn_id, "status": "running", "items": [] }),
                        );
                        if let Some(t) = entry.as_object_mut() {
                            if let Some(arr) = t
                                .entry("items".to_string())
                                .or_insert_with(|| json!([]))
                                .as_array_mut()
                            {
                                if !arr.iter().any(|x| x.as_str() == Some(item_id.as_str())) {
                                    arr.push(Value::String(item_id));
                                }
                            }
                            t.insert("last_seq".into(), json!(env.seq));
                        }
                    }
                }
            }
        }
        "turn/interrupted" => {
            let payload = env.payload.as_object();
            let turn_id = env
                .turn_id
                .as_deref()
                .filter(|s| !s.is_empty())
                .or_else(|| {
                    payload.and_then(|p| {
                        p.get("turn_id")
                            .or_else(|| p.get("turnId"))
                            .and_then(|v| v.as_str())
                    })
                })
                .map(str::trim)
                .unwrap_or("")
                .to_string();
            if !turn_id.is_empty() {
                let is_term = state
                    .get("turns")
                    .and_then(|ts| ts.get(&turn_id))
                    .and_then(|t| t.get("status"))
                    .and_then(|s| s.as_str())
                    .map(|s| TERMINAL_TURN_STATUSES.contains(&s))
                    .unwrap_or(false)
                    || state
                        .get("core")
                        .and_then(|c| c.get("turns"))
                        .and_then(|ts| ts.get(&turn_id))
                        .and_then(|t| t.get("status"))
                        .and_then(|s| s.as_str())
                        .map(|s| TERMINAL_TURN_STATUSES.contains(&s))
                        .unwrap_or(false);
                if is_term {
                    recompute_thread_status_core(state);
                    return;
                }
                if let Some(turns_map) = state.as_object_mut().and_then(|r| {
                    r.entry("turns".to_string())
                        .or_insert_with(|| json!({}))
                        .as_object_mut()
                }) {
                    let entry = turns_map.entry(turn_id.clone()).or_insert_with(
                        || json!({ "turn_id": turn_id, "status": "running", "items": [] }),
                    );
                    if let Some(t) = entry.as_object_mut() {
                        t.entry("items".to_string()).or_insert_with(|| json!([]));
                        if let Some(p) = payload {
                            for (k, v) in p {
                                t.insert(k.clone(), v.clone());
                            }
                        }
                        t.insert("status".into(), json!("interrupting"));
                        t.insert("last_seq".into(), json!(env.seq));
                        t.insert("last_method".into(), json!(env.method));
                    }
                }
            }
            if let Some(root) = state.as_object_mut() {
                root.insert("status".into(), json!("running"));
            }
        }
        "turn/steered" => {
            let payload = env.payload.as_object();
            let turn_id = env
                .turn_id
                .as_deref()
                .filter(|s| !s.is_empty())
                .or_else(|| {
                    payload.and_then(|p| {
                        p.get("turn_id")
                            .or_else(|| p.get("turnId"))
                            .and_then(|v| v.as_str())
                    })
                })
                .map(str::trim)
                .unwrap_or("")
                .to_string();
            if turn_id.is_empty() {
                return;
            }
            let existing = state
                .get("turns")
                .and_then(|ts| ts.get(&turn_id))
                .and_then(|t| t.as_object());
            let Some(ex) = existing else {
                return;
            };
            let st = ex.get("status").and_then(|s| s.as_str()).unwrap_or("");
            if TERMINAL_TURN_STATUSES.contains(&st) {
                return;
            }
            if let Some(t) = state
                .get_mut("turns")
                .and_then(|ts| ts.get_mut(&turn_id))
                .and_then(|t| t.as_object_mut())
            {
                if let Some(p) = payload {
                    for (k, v) in p {
                        if !matches!(k.as_str(), "status" | "input" | "runtime_input") {
                            t.insert(k.clone(), v.clone());
                        }
                    }
                }
                t.insert("seq".into(), json!(env.seq));
                t.insert("last_seq".into(), json!(env.seq));
                t.insert("last_method".into(), json!(env.method));
            }
        }
        "serverRequest/resolved" => {
            let payload = env.payload.as_object();
            let request_id = payload
                .and_then(|p| {
                    p.get("request_id")
                        .or_else(|| p.get("requestId"))
                        .and_then(|v| v.as_str())
                })
                .map(str::trim)
                .unwrap_or("")
                .to_string();
            if request_id.is_empty() {
                return;
            }
            if let Some(reqs) = state.as_object_mut().and_then(|r| {
                r.entry("requests".to_string())
                    .or_insert_with(|| json!({}))
                    .as_object_mut()
            }) {
                let entry = reqs
                    .entry(request_id.clone())
                    .or_insert_with(|| json!({ "request_id": request_id }));
                if let Some(req) = entry.as_object_mut() {
                    if let Some(p) = payload {
                        for (k, v) in p {
                            req.insert(k.clone(), v.clone());
                        }
                    }
                    req.insert("status".into(), json!("resolved"));
                    req.entry("turn_id".to_string())
                        .or_insert_with(|| match &env.turn_id {
                            Some(s) => json!(s),
                            None => Value::Null,
                        });
                    req.entry("item_id".to_string())
                        .or_insert_with(|| match &env.item_id {
                            Some(s) => json!(s),
                            None => Value::Null,
                        });
                }
            }
            recompute_thread_status_core(state);
        }
        "queue/itemAccepted" => apply_queue_item(state, env, Some("queued")),
        "queue/itemUpdated" => apply_queue_item(state, env, None),
        "queue/itemDispatched" => apply_queue_item(state, env, Some("dispatched")),
        "queue/itemDeleted" => {
            let payload = env.payload.as_object();
            let qid = env
                .item_id
                .as_deref()
                .filter(|s| !s.is_empty())
                .or_else(|| {
                    payload.and_then(|p| {
                        p.get("queue_item_id")
                            .or_else(|| p.get("queueItemId"))
                            .and_then(|v| v.as_str())
                    })
                })
                .map(str::trim)
                .unwrap_or("")
                .to_string();
            if !qid.is_empty() {
                if let Some(queue) = state.get_mut("queue").and_then(|q| q.as_array_mut()) {
                    queue.retain(|x| {
                        x.get("queue_item_id").and_then(|v| v.as_str()) != Some(qid.as_str())
                    });
                }
            }
        }
        "queue/itemReordered" => {
            let Some(order) = env.payload.get("order").and_then(|v| v.as_array()) else {
                return;
            };
            let mut pos_by_id: HashMap<String, i64> = HashMap::new();
            let mut next_pos: i64 = 0;
            for entry in order {
                let qid = entry.as_str().map(str::trim).unwrap_or("");
                if !qid.is_empty() && !pos_by_id.contains_key(qid) {
                    pos_by_id.insert(qid.to_string(), next_pos);
                    next_pos += 1;
                }
            }
            if let Some(queue) = state.get_mut("queue").and_then(|q| q.as_array_mut()) {
                for item in queue.iter_mut() {
                    if let Some(obj) = item.as_object_mut() {
                        obj.remove("position");
                        let qid = obj
                            .get("queue_item_id")
                            .and_then(|v| v.as_str())
                            .unwrap_or("");
                        if let Some(&pos) = pos_by_id.get(qid) {
                            obj.insert("position".into(), json!(pos));
                        }
                    }
                }
                queue.sort_by_key(queue_order_key);
            }
        }
        CORE_RUN_ITEM_METHOD => {
            let mut payload = env.payload.clone();
            let Some(pobj) = payload.as_object_mut() else {
                return;
            };
            let has_kind = pobj
                .get("kind")
                .and_then(|v| v.as_str())
                .map(|s| !s.is_empty())
                .unwrap_or(false);
            let has_tid = pobj
                .get("thread_id")
                .and_then(|v| v.as_str())
                .map(|s| !s.is_empty())
                .unwrap_or(false);
            if !has_kind || !has_tid {
                return;
            }
            pobj.insert("seq".into(), json!(env.seq));
            let turn_id_opt = pobj
                .get("turn_id")
                .and_then(|v| v.as_str())
                .filter(|s| !s.is_empty())
                .map(str::to_string);
            let mut core = state
                .get("core")
                .filter(|v| v.is_object())
                .cloned()
                .unwrap_or_else(|| empty_core_snapshot(&env.thread_id));
            apply_run_item_event_in_place_core(&mut core, &payload, env.seq);
            if let Some(root) = state.as_object_mut() {
                root.insert("core".into(), core);
            }
            sync_turns_from_core(state, turn_id_opt.as_deref());
            // _apply_member_wait_flag
            if let Some(inner) = payload.get("payload").and_then(|v| v.as_object()) {
                if inner.get("type").and_then(|v| v.as_str()) == Some("subAgents") {
                    let wt_tid = payload
                        .get("turn_id")
                        .or_else(|| inner.get("turn_id"))
                        .and_then(|v| v.as_str())
                        .unwrap_or("");
                    if !wt_tid.is_empty() {
                        let waiting = inner
                            .get("waiting_on_members")
                            .and_then(|v| v.as_bool())
                            .unwrap_or(false);
                        let members: Vec<Value> = inner
                            .get("members")
                            .and_then(|v| v.as_array())
                            .map(|arr| {
                                arr.iter()
                                    .filter_map(|m| {
                                        m.get("name")
                                            .and_then(|n| n.as_str())
                                            .filter(|s| !s.is_empty())
                                            .map(|s| Value::String(s.to_string()))
                                    })
                                    .collect()
                            })
                            .unwrap_or_default();
                        if let Some(turns_map) = state.as_object_mut().and_then(|r| {
                            r.entry("turns".to_string())
                                .or_insert_with(|| json!({}))
                                .as_object_mut()
                        }) {
                            let entry = turns_map.entry(wt_tid.to_string()).or_insert_with(
                                || json!({ "turn_id": wt_tid, "status": "running", "items": [] }),
                            );
                            if let Some(t) = entry.as_object_mut() {
                                t.insert("waiting_on_members".into(), json!(waiting));
                                t.insert("running_members".into(), Value::Array(members));
                            }
                        }
                    }
                }
            }
            sync_status_from_core(state);
        }
        _ => {}
    }
}

pub(crate) fn latest_active_turn_id(snapshot: &Value) -> Option<String> {
    let core = snapshot.get("core");
    let has_status = snapshot
        .get("status")
        .and_then(|v| v.as_str())
        .map(|s| !s.is_empty())
        .unwrap_or(false)
        || core
            .and_then(|c| c.get("status"))
            .and_then(|v| v.as_str())
            .map(|s| !s.is_empty())
            .unwrap_or(false);
    if has_status && !ACTIVE_TURN_STATUSES.contains(&effective_thread_status(snapshot).as_str()) {
        return None;
    }
    let mut merged: Map<String, Value> = Map::new();
    if let Some(outer) = snapshot.get("turns").and_then(|t| t.as_object()) {
        for (k, v) in outer {
            merged.insert(k.clone(), v.clone());
        }
    }
    if let Some(ct) = core
        .and_then(|c| c.get("turns"))
        .and_then(|t| t.as_object())
    {
        for (k, v) in ct {
            merged.insert(k.clone(), v.clone());
        }
    }
    let core_turns = core
        .and_then(|c| c.get("turns"))
        .and_then(|t| t.as_object());
    let outer_turns = snapshot.get("turns").and_then(|t| t.as_object());
    let mut best_seq: i64 = -1;
    let mut best_id: Option<String> = None;
    for (tid, t) in merged {
        let Some(t_obj) = t.as_object() else {
            continue;
        };
        let eff_id = t_obj
            .get("turn_id")
            .and_then(|v| v.as_str())
            .filter(|s| !s.is_empty())
            .unwrap_or(&tid);
        let eff_st = core_turns
            .and_then(|m| m.get(eff_id))
            .and_then(|x| x.get("status"))
            .and_then(|s| s.as_str())
            .filter(|s| !s.is_empty())
            .or_else(|| {
                outer_turns
                    .and_then(|m| m.get(eff_id))
                    .and_then(|x| x.get("status"))
                    .and_then(|s| s.as_str())
            })
            .unwrap_or("");
        if !ACTIVE_TURN_STATUSES.contains(&eff_st) {
            continue;
        }
        let seq = t_obj
            .get("last_seq")
            .or_else(|| t_obj.get("seq"))
            .and_then(|v| v.as_i64())
            .unwrap_or(0);
        if best_id.is_none() || seq > best_seq {
            best_seq = seq;
            best_id = Some(eff_id.to_string());
        }
    }
    best_id.filter(|s| !s.is_empty())
}

pub(crate) fn slim_registry_inline_images(state: &mut Value) {
    if let Some(reg) = state
        .get_mut("core")
        .and_then(|c| c.get_mut("artifacts"))
        .and_then(|a| a.as_object_mut())
    {
        for art in reg.values_mut() {
            if let Some(meta) = art.get_mut("metadata").and_then(|m| m.as_object_mut()) {
                meta.remove("image_data_url");
            }
        }
    }
    if let Some(reg) = state.get_mut("artifacts").and_then(|a| a.as_object_mut()) {
        for art in reg.values_mut() {
            if let Some(meta) = art.get_mut("metadata").and_then(|m| m.as_object_mut()) {
                meta.remove("image_data_url");
            }
        }
    }
}

fn touched_item_ids(events: &[Envelope], core: &Value) -> Vec<String> {
    let mut seen: HashSet<String> = HashSet::new();
    let mut out: Vec<String> = Vec::new();
    for env in events {
        if let Some(iid) = env
            .payload
            .get("item_id")
            .and_then(|v| v.as_str())
            .filter(|s| !s.is_empty())
        {
            if seen.insert(iid.to_string()) {
                out.push(iid.to_string());
            }
        }
        if env.payload.get("kind").and_then(|v| v.as_str()) == Some("status")
            && env
                .payload
                .get("status")
                .and_then(|v| v.as_str())
                .map(|s| TERMINAL_ITEM_STATUSES.contains(&s))
                .unwrap_or(false)
        {
            if let Some(tid) = env.turn_id.as_deref().filter(|s| !s.is_empty()) {
                if let Some(items) = core
                    .get("turns")
                    .and_then(|ts| ts.get(tid))
                    .and_then(|t| t.get("items"))
                    .and_then(|a| a.as_array())
                {
                    for val in items {
                        if let Some(s) = val.as_str().filter(|s| !s.is_empty()) {
                            if seen.insert(s.to_string()) {
                                out.push(s.to_string());
                            }
                        }
                    }
                }
            }
        }
    }
    out
}

fn fetch_existing_event(conn: &Connection, event_id: &str) -> Result<Option<Envelope>, DbError> {
    let mut stmt = conn.prepare_cached(
        "SELECT event_id, thread_id, seq, turn_id, item_id, parent_item_id, client_message_id, \
         method, payload_json, COALESCE(workspace_id,''), COALESCE(entity_type,'thread.event'), \
         COALESCE(entity_id,''), COALESCE(event_seq,0), COALESCE(revision,0), \
         COALESCE(event_type,''), COALESCE(created_at,'') \
         FROM core_app_events WHERE event_id = ?1",
    )?;
    let mut rows = stmt.query([event_id])?;
    let Some(row) = rows.next()? else {
        return Ok(None);
    };
    let raw_payload: Option<String> = row.get(8)?;
    let payload: Value = raw_payload
        .as_deref()
        .and_then(|s| serde_json::from_str(s).ok())
        .unwrap_or_else(|| json!({}));
    let created_raw: String = row.get(15)?;
    Ok(Some(Envelope {
        event_id: row.get(0)?,
        protocol_version: "core.agent.v1".into(),
        seq: row.get(2)?,
        thread_id: row.get(1)?,
        method: row.get(7)?,
        payload,
        created_at_iso: format_iso_from_sqlite(&created_raw),
        turn_id: row.get(3)?,
        item_id: row.get(4)?,
        parent_item_id: row.get(5)?,
        client_message_id: row.get(6)?,
        workspace_id: row.get(9)?,
        entity_type: row.get(10)?,
        entity_id: row.get(11)?,
        event_seq: row.get(12)?,
        revision: row.get(13)?,
        event_type: row.get(14)?,
    }))
}

pub fn append_and_project_batch(engine: &DbEngine, req: &Value) -> Result<Value, DbError> {
    let events_req = req
        .get("events")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    if events_req.is_empty() {
        return Ok(json!({ "envelopes": [], "state": Value::Null }));
    }
    let project_snapshot = req
        .get("project_snapshot")
        .and_then(|v| v.as_bool())
        .unwrap_or(true);
    let expected_revision = req.get("expected_revision").and_then(|v| v.as_i64());
    let revision_thread_id = req.get("revision_thread_id").and_then(|v| v.as_str());
    let workspace_id = req
        .get("workspace_id")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let emit_sync = req
        .get("emit_sync")
        .and_then(|v| v.as_bool())
        .unwrap_or(true);
    let return_state = req
        .get("return_state")
        .and_then(|v| v.as_bool())
        .unwrap_or(false);
    let require_new = req
        .get("require_new")
        .and_then(|v| v.as_bool())
        .unwrap_or(false);
    // user:“check，事件通道压力过高：可靠通道 32/64；已丢弃 257 帧可丢进度；正在自动恢复，无需操作”+(支持 only_new 仅返回真正新写入的事件，并对已存在且已投影的重复事件短路跳过快照重写)
    let only_new = req
        .get("only_new")
        .and_then(|v| v.as_bool())
        .unwrap_or(false);
    let member_defaults = req.get("member_defaults");
    let now_str = req.get("now_str").and_then(|v| v.as_str()).unwrap_or("");
    let now_iso = format_iso_from_sqlite(now_str);

    let first_tid = events_req[0]
        .get("thread_id")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let cas_tid = revision_thread_id.unwrap_or(first_tid);

    let mut cache_updates: Vec<(String, i64, i64, String, Value, usize)> = Vec::new();
    let mut summary_invalidations: Vec<String> = Vec::new();
    let mut last_thread_id = String::new();

    let envelopes = engine.write_tx(|conn| {
        if require_new && !first_tid.is_empty() {
            let exists: Option<String> = conn
                .query_row(
                    "SELECT thread_id FROM core_thread_snapshots WHERE thread_id = ?1",
                    [first_tid],
                    |r| r.get(0),
                )
                .optional()?;
            if exists.is_some() {
                return Err(DbError::Conflict(
                    json!({ "code": "SESSION_ALREADY_EXISTS", "thread_id": first_tid }).to_string(),
                ));
            }
        }
        if let Some(exp) = expected_revision {
            let row_opt: Option<(i64, Option<String>)> = conn
                .query_row(
                    "SELECT COALESCE(revision, 0), snapshot_json FROM core_thread_snapshots WHERE thread_id = ?1",
                    [cas_tid],
                    |r| Ok((r.get(0)?, r.get(1)?)),
                )
                .optional()?;
            let current = match row_opt {
                None => 0,
                Some((rev, raw_json)) => {
                    if rev > 0 {
                        rev
                    } else {
                        raw_json
                            .as_deref()
                            .and_then(|s| serde_json::from_str::<Value>(s).ok())
                            .and_then(|v| v.get("revision").and_then(|r| r.as_i64()))
                            .unwrap_or(0)
                            .max(0)
                    }
                }
            };
            if exp != current {
                return Err(DbError::Conflict(
                    json!({
                        "code": "REVISION_CONFLICT",
                        "thread_id": cas_tid,
                        "expected_revision": exp,
                        "current_revision": current,
                    })
                    .to_string(),
                ));
            }
        }

        let mut max_seq_by_thread: HashMap<String, i64> = HashMap::new();
        let mut envelopes: Vec<Envelope> = Vec::with_capacity(events_req.len());
        let mut is_new_flags: Vec<bool> = Vec::with_capacity(events_req.len());

        for item in &events_req {
            let event_id = item
                .get("event_id")
                .and_then(|v| v.as_str())
                .ok_or_else(|| DbError::Invalid("event_id required".into()))?;
            let thread_id = item
                .get("thread_id")
                .and_then(|v| v.as_str())
                .ok_or_else(|| DbError::Invalid("thread_id required".into()))?;
            if let Some(existing) = fetch_existing_event(conn, event_id)? {
                if existing.thread_id != thread_id {
                    return Err(DbError::Invalid("Event identity belongs to another thread".into()));
                }
                if !only_new {
                    envelopes.push(existing);
                    is_new_flags.push(false);
                }
                continue;
            }
            let next_seq = if let Some(&prev) = max_seq_by_thread.get(thread_id) {
                prev + 1
            } else {
                let db_max: i64 = conn.query_row(
                    "SELECT COALESCE(MAX(seq), 0) FROM core_app_events WHERE thread_id = ?1",
                    [thread_id],
                    |r| r.get(0),
                )?;
                db_max + 1
            };
            max_seq_by_thread.insert(thread_id.to_string(), next_seq);

            let method = item.get("method").and_then(|v| v.as_str()).unwrap_or(CORE_RUN_ITEM_METHOD);
            let turn_id = item.get("turn_id").and_then(|v| v.as_str()).map(str::to_string);
            let item_id = item.get("item_id").and_then(|v| v.as_str()).map(str::to_string);
            let parent_item_id = item.get("parent_item_id").and_then(|v| v.as_str()).map(str::to_string);
            let client_message_id = item.get("client_message_id").and_then(|v| v.as_str()).map(str::to_string);
            let payload = item.get("payload").cloned().unwrap_or_else(|| json!({}));
            let entity_type = item.get("entity_type").and_then(|v| v.as_str()).unwrap_or("thread.event");
            let event_type = item
                .get("event_type")
                .and_then(|v| v.as_str())
                .filter(|s| !s.is_empty())
                .unwrap_or(method);
            let ev_ws = item
                .get("workspace_id")
                .and_then(|v| v.as_str())
                .filter(|s| !s.is_empty())
                .unwrap_or(workspace_id);
            let payload_str = serde_json::to_string(&payload)?;

            conn.execute(
                "INSERT INTO core_app_events \
                 (event_id, thread_id, seq, turn_id, item_id, parent_item_id, client_message_id, \
                  method, payload_json, workspace_id, entity_type, entity_id, event_seq, revision, event_type, created_at) \
                 VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,0,?14,?15)",
                params![
                    event_id,
                    thread_id,
                    next_seq,
                    turn_id,
                    item_id,
                    parent_item_id,
                    client_message_id,
                    method,
                    payload_str,
                    ev_ws,
                    entity_type,
                    thread_id,
                    next_seq,
                    event_type,
                    now_str,
                ],
            )?;

            let env = Envelope {
                event_id: event_id.to_string(),
                protocol_version: "core.agent.v1".into(),
                seq: next_seq,
                thread_id: thread_id.to_string(),
                method: method.to_string(),
                payload,
                created_at_iso: now_iso.clone(),
                turn_id,
                item_id,
                parent_item_id,
                client_message_id,
                workspace_id: ev_ws.to_string(),
                entity_type: entity_type.to_string(),
                entity_id: thread_id.to_string(),
                event_seq: next_seq,
                revision: 0,
                event_type: event_type.to_string(),
            };

            envelopes.push(env);
            is_new_flags.push(true);
        }

        if envelopes.is_empty() {
            return Ok(envelopes);
        }

        if !project_snapshot {
            if emit_sync {
                for (idx, env) in envelopes.iter().enumerate() {
                    if !is_new_flags[idx] {
                        continue;
                    }
                    let entity_str = serde_json::to_string(&json!({ "event": env.to_value() }))?;
                    conn.execute(
                        "INSERT INTO core_sync_changes \
                         (change_id, workspace_id, entity_type, event_type, operation, entity_id, thread_id, revision, entity_json, created_at) \
                         VALUES (?1,?2,?3,?4,'upsert',?5,?6,?7,?8,?9) \
                         ON CONFLICT(change_id) DO UPDATE SET \
                           entity_json = excluded.entity_json, \
                           revision = excluded.revision, \
                           event_type = excluded.event_type",
                        params![
                            env.event_id,
                            env.workspace_id,
                            env.entity_type,
                            env.event_type,
                            env.thread_id,
                            env.thread_id,
                            env.revision,
                            entity_str,
                            now_str,
                        ],
                    )?;
                }
            }
            return Ok(envelopes);
        }

        let mut group_order: Vec<String> = Vec::new();
        let mut by_thread: HashMap<String, Vec<usize>> = HashMap::new();
        for (idx, env) in envelopes.iter().enumerate() {
            if !by_thread.contains_key(&env.thread_id) {
                group_order.push(env.thread_id.clone());
            }
            by_thread.entry(env.thread_id.clone()).or_default().push(idx);
        }

        cache_updates.clear();
        summary_invalidations.clear();
        for thread_id in group_order {
            last_thread_id = thread_id.clone();
            let indices = &by_thread[&thread_id];
            let mut group_envs: Vec<Envelope> = indices.iter().map(|&i| envelopes[i].clone()).collect();
            group_envs.sort_by_key(|e| e.seq);

            let row_probe: Option<(i64, i64)> = conn
                .query_row(
                    "SELECT COALESCE(revision, 0), COALESCE(snapshot_seq, 0) FROM core_thread_snapshots WHERE thread_id = ?1",
                    [&thread_id],
                    |r| Ok((r.get(0)?, r.get(1)?)),
                )
                .optional()?;
            let existed = row_probe.is_some();

            let mut state = if let Some((db_rev, db_seq)) = row_probe {
                let cached_meta = {
                    let mut cache = engine.cache.write().unwrap_or_else(|e| e.into_inner());
                    cache.get_metadata(&thread_id, db_rev, db_seq)
                };
                if let Some(hit) = cached_meta {
                    engine.stats.snapshot_cache_hits.fetch_add(1, Ordering::Relaxed);
                    hit.state
                } else {
                    engine.stats.snapshot_cache_misses.fetch_add(1, Ordering::Relaxed);
                    let raw_json: Option<String> = conn
                        .query_row(
                            "SELECT snapshot_json FROM core_thread_snapshots WHERE thread_id = ?1",
                            [&thread_id],
                            |r| r.get(0),
                        )
                        .optional()?
                        .flatten();
                    match raw_json {
                        Some(ref s) if !s.is_empty() => serde_json::from_str(s)?,
                        _ => empty_projection_state(&thread_id, member_defaults),
                    }
                }
            } else {
                empty_projection_state(&thread_id, member_defaults)
            };

            let mut revision = row_probe
                .map(|(rev, _)| {
                    if rev > 0 {
                        rev
                    } else {
                        state
                            .get("revision")
                            .and_then(|v| v.as_i64())
                            .unwrap_or(0)
                            .max(0)
                    }
                })
                .unwrap_or(0);

            if existed {
                if let Some(root) = state.as_object_mut() {
                    let (_, db_seq) = row_probe.unwrap_or((0, 0));
                    root.insert("snapshot_seq".into(), json!(db_seq));
                    root.insert("revision".into(), json!(revision));
                }
                let all_existing_and_projected = indices.iter().all(|&idx| {
                    !is_new_flags[idx]
                        && already_projected(&state, &envelopes[idx].event_id, envelopes[idx].seq)
                });
                if all_existing_and_projected {
                    continue;
                }
                if let Some(root) = state.as_object_mut() {
                    let core = root
                        .entry("core".to_string())
                        .or_insert_with(|| empty_core_snapshot(&thread_id));
                    if !core.is_object() {
                        *core = empty_core_snapshot(&thread_id);
                    }
                    let touched = touched_item_ids(&group_envs, core);
                    let mut order: Vec<String> = core
                        .get("item_order")
                        .and_then(|v| v.as_array())
                        .map(|arr| {
                            arr.iter()
                                .filter_map(|v| v.as_str().map(str::to_string))
                                .collect()
                        })
                        .unwrap_or_default();
                    let mut order_set: HashSet<String> = order.iter().cloned().collect();
                    let row_count: i64 = conn
                        .query_row(
                            "SELECT COUNT(*) FROM core_thread_snapshot_items WHERE thread_id = ?1",
                            [&thread_id],
                            |r| r.get(0),
                        )
                        .unwrap_or(0);
                    let mut needs_anchors = touched.iter().any(|iid| !order_set.contains(iid));
                    let mut seq_map: Map<String, Value> = Map::new();
                    if needs_anchors || row_count != (order.len() as i64) {
                        needs_anchors = true;
                        let mut stmt = conn.prepare_cached(
                            "SELECT item_id, seq FROM core_thread_snapshot_items WHERE thread_id = ?1",
                        )?;
                        let mut rows = stmt.query([&thread_id])?;
                        while let Some(r) = rows.next()? {
                            let iid: String = r.get(0)?;
                            let seq: i64 = r.get(1)?;
                            seq_map.insert(iid.clone(), json!(seq));
                            if order_set.insert(iid.clone()) {
                                order.push(iid);
                            }
                        }
                    }
                    let mut items_map = Map::new();
                    if !touched.is_empty() {
                        for chunk in touched.chunks(200) {
                            let placeholders = vec!["?"; chunk.len()].join(",");
                            let sql = format!(
                                "SELECT item_id, seq, item_json FROM core_thread_snapshot_items \
                                 WHERE thread_id = ?1 AND item_id IN ({placeholders})"
                            );
                            let mut stmt = conn.prepare(&sql)?;
                            let mut params_vec: Vec<&dyn rusqlite::ToSql> = Vec::with_capacity(chunk.len() + 1);
                            params_vec.push(&thread_id);
                            for iid in chunk {
                                params_vec.push(iid);
                            }
                            let mut rows = stmt.query(params_vec.as_slice())?;
                            while let Some(r) = rows.next()? {
                                let iid: String = r.get(0)?;
                                let seq: i64 = r.get(1)?;
                                let raw: Option<String> = r.get(2)?;
                                let mut iv: Value = raw
                                    .as_deref()
                                    .and_then(|s| serde_json::from_str(s).ok())
                                    .unwrap_or_else(|| json!({}));
                                if let Some(obj) = iv.as_object_mut() {
                                    obj.insert("seq".into(), json!(seq));
                                }
                                items_map.insert(iid, iv);
                            }
                        }
                    }
                    crate::snapshots::hydrate_body_refs_conn(conn, &thread_id, &mut items_map)?;
                    if let Some(core_obj) = core.as_object_mut() {
                        core_obj.insert("items".into(), Value::Object(items_map));
                        core_obj.insert(
                            "item_order".into(),
                            Value::Array(order.into_iter().map(Value::String).collect()),
                        );
                        if needs_anchors {
                            core_obj.insert("_item_seq_map".into(), Value::Object(seq_map));
                        } else {
                            core_obj.remove("_item_seq_map");
                        }
                    }
                }
                // user:“嗯”+(增量投影前仅加载本次触及、进行中及最近一轮 turns 元数据，免扫几十个已完成旧回合)
                let mut touched_turns: HashSet<String> = HashSet::new();
                for env in &group_envs {
                    if let Some(tid) = env.turn_id.as_deref().filter(|s| !s.is_empty()) {
                        touched_turns.insert(tid.to_string());
                    }
                    if let Some(tid) = env
                        .payload
                        .get("turn_id")
                        .and_then(|v| v.as_str())
                        .filter(|s| !s.is_empty())
                    {
                        touched_turns.insert(tid.to_string());
                    }
                }
                if let Ok(Some(latest_tid)) = conn
                    .query_row(
                        "SELECT turn_id FROM core_thread_snapshot_turns \
                         WHERE thread_id = ?1 ORDER BY seq DESC LIMIT 1",
                        [&thread_id],
                        |r| r.get::<_, String>(0),
                    )
                    .optional()
                {
                    if !latest_tid.is_empty() {
                        touched_turns.insert(latest_tid);
                    }
                }
                crate::snapshots::hydrate_snapshot_turns_conn(
                    conn,
                    &thread_id,
                    &mut state,
                    Some(&touched_turns),
                )?;
                strip_inline_image_copies(&mut state);
            }

            let mut event_revisions: HashMap<String, i64> = HashMap::new();
            for env in &group_envs {
                if already_projected(&state, &env.event_id, env.seq) {
                    continue;
                }
                projector_apply_in_place(&mut state, env);
                revision += 1;
                if let Some(root) = state.as_object_mut() {
                    root.insert("revision".into(), json!(revision));
                }
                event_revisions.insert(env.event_id.clone(), revision);
            }

            // Persist touched items and metadata row.
            let items_to_upsert: Map<String, Value> = state
                .get("core")
                .and_then(|c| c.get("items"))
                .and_then(|i| i.as_object())
                .cloned()
                .unwrap_or_default();
            if !items_to_upsert.is_empty() {
                // user:“规划并实现”+(写入快照条目时同步落库 item_type，供大纲/分类走索引查询免扫全量 JSON)
                let mut upsert_stmt = conn.prepare_cached(
                    "INSERT INTO core_thread_snapshot_items (thread_id, item_id, seq, item_json, item_type, updated_at) \
                     VALUES (?1, ?2, ?3, ?4, ?5, ?6) \
                     ON CONFLICT(thread_id, item_id) DO UPDATE SET \
                       seq = excluded.seq, \
                       item_json = excluded.item_json, \
                       item_type = excluded.item_type, \
                       updated_at = excluded.updated_at",
                )?;
                for (iid, item_val) in &items_to_upsert {
                    let seq = item_val.get("seq").and_then(|v| v.as_i64()).unwrap_or(0);
                    let full_str = serde_json::to_string(item_val)?;
                    let item_type = extract_item_type(item_val);
                    let stored_str = maybe_slim_snapshot_item(conn, &thread_id, iid, item_val, &full_str);
                    upsert_stmt.execute(params![thread_id, iid, seq, stored_str, item_type, now_str])?;
                }
            }

            slim_registry_inline_images(&mut state);

            // user:“嗯”+(将 core.artifacts 与 turns 增量拆表落库，不随每条流式消息整块重写)
            if let Some(arts_map) = state
                .get("core")
                .and_then(|c| c.get("artifacts"))
                .and_then(|a| a.as_object())
            {
                if !arts_map.is_empty() {
                    let mut art_stmt = conn.prepare_cached(
                        "INSERT INTO core_thread_snapshot_artifacts (thread_id, artifact_id, artifact_json, updated_at) \
                         VALUES (?1, ?2, ?3, ?4) \
                         ON CONFLICT(thread_id, artifact_id) DO UPDATE SET \
                           artifact_json = excluded.artifact_json, \
                           updated_at = excluded.updated_at",
                    )?;
                    for (aid, aval) in arts_map {
                        let ajson = serde_json::to_string(aval)?;
                        art_stmt.execute(params![thread_id, aid, ajson, now_str])?;
                    }
                }
            }

            {
                let empty_map = Map::new();
                let core_turns = state
                    .get("core")
                    .and_then(|c| c.get("turns"))
                    .and_then(|t| t.as_object())
                    .unwrap_or(&empty_map);
                let app_turns = state
                    .get("turns")
                    .and_then(|t| t.as_object())
                    .unwrap_or(&empty_map);
                let mut turn_ids: HashSet<&str> = HashSet::new();
                for k in core_turns.keys() {
                    turn_ids.insert(k.as_str());
                }
                for k in app_turns.keys() {
                    turn_ids.insert(k.as_str());
                }
                if !turn_ids.is_empty() {
                    let mut turn_stmt = conn.prepare_cached(
                        "INSERT INTO core_thread_snapshot_turns \
                         (thread_id, turn_id, seq, status, core_turn_json, app_turn_json, updated_at) \
                         VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7) \
                         ON CONFLICT(thread_id, turn_id) DO UPDATE SET \
                           seq = excluded.seq, \
                           status = excluded.status, \
                           core_turn_json = excluded.core_turn_json, \
                           app_turn_json = excluded.app_turn_json, \
                           updated_at = excluded.updated_at",
                    )?;
                    for tid in turn_ids {
                        let c_val = core_turns.get(tid);
                        let a_val = app_turns.get(tid);
                        let seq = c_val
                            .or(a_val)
                            .and_then(|t| t.get("last_seq").or_else(|| t.get("seq")).and_then(|v| v.as_i64()))
                            .unwrap_or(0);
                        let st = c_val
                            .and_then(|t| t.get("status").and_then(|v| v.as_str()))
                            .or_else(|| a_val.and_then(|t| t.get("status").and_then(|v| v.as_str())))
                            .unwrap_or("");
                        let c_str = match c_val {
                            Some(v) => Some(serde_json::to_string(v)?),
                            None => None,
                        };
                        let a_str = match a_val {
                            Some(v) => Some(serde_json::to_string(v)?),
                            None => None,
                        };
                        turn_stmt.execute(params![thread_id, tid, seq, st, c_str, a_str, now_str])?;
                    }
                }
            }

            let active_turn_id = latest_active_turn_id(&state);

            let mut metadata_state = state.clone();
            if let Some(root) = metadata_state.as_object_mut() {
                root.remove("_item_seq_map");
                root.insert("turns".into(), json!({}));
                if let Some(core_obj) = root.get_mut("core").and_then(|c| c.as_object_mut()) {
                    core_obj.insert("items".into(), json!({}));
                    core_obj.insert("artifacts".into(), json!({}));
                    core_obj.insert("turns".into(), json!({}));
                    core_obj.remove("_item_seq_map");
                }
            }

            let snap_seq = metadata_state
                .get("snapshot_seq")
                .and_then(|v| v.as_i64())
                .unwrap_or(0);
            let final_rev = revision.max(
                metadata_state
                    .get("revision")
                    .and_then(|v| v.as_i64())
                    .unwrap_or(0)
                    .max(0),
            );
            if let Some(root) = metadata_state.as_object_mut() {
                root.insert("revision".into(), json!(final_rev));
            }
            let meta_str = serde_json::to_string(&metadata_state)?;
            let meta_bytes = meta_str.len();

            conn.execute(
                "INSERT INTO core_thread_snapshots \
                 (thread_id, snapshot_seq, revision, active_turn_id, snapshot_json, updated_at) \
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6) \
                 ON CONFLICT(thread_id) DO UPDATE SET \
                   snapshot_seq = excluded.snapshot_seq, \
                   revision = excluded.revision, \
                   active_turn_id = excluded.active_turn_id, \
                   snapshot_json = excluded.snapshot_json, \
                   updated_at = excluded.updated_at",
                params![thread_id, snap_seq, final_rev, active_turn_id, meta_str, now_str],
            )?;

            for &idx in indices {
                let eid = envelopes[idx].event_id.clone();
                if let Some(&ev_rev) = event_revisions.get(&eid) {
                    let ev_rev_clamped = ev_rev.max(0);
                    conn.execute(
                        "UPDATE core_app_events SET revision = ?1, event_seq = seq WHERE event_id = ?2",
                        params![ev_rev_clamped, eid],
                    )?;
                    envelopes[idx].revision = ev_rev_clamped;
                    envelopes[idx].event_seq = envelopes[idx].seq;
                    if emit_sync {
                        let entity_str = serde_json::to_string(&json!({ "event": envelopes[idx].to_value() }))?;
                        conn.execute(
                            "INSERT INTO core_sync_changes \
                             (change_id, workspace_id, entity_type, event_type, operation, entity_id, thread_id, revision, entity_json, created_at) \
                             VALUES (?1,?2,?3,?4,'upsert',?5,?6,?7,?8,?9) \
                             ON CONFLICT(change_id) DO UPDATE SET \
                               entity_json = excluded.entity_json, \
                               revision = excluded.revision, \
                               event_type = excluded.event_type",
                            params![
                                envelopes[idx].event_id,
                                envelopes[idx].workspace_id,
                                envelopes[idx].entity_type,
                                envelopes[idx].event_type,
                                envelopes[idx].thread_id,
                                envelopes[idx].thread_id,
                                ev_rev_clamped,
                                entity_str,
                                now_str,
                            ],
                        )?;
                    }
                } else if let Some(refreshed) = fetch_existing_event(conn, &eid)? {
                    envelopes[idx] = refreshed;
                    if emit_sync && is_new_flags[idx] {
                        let entity_str = serde_json::to_string(&json!({ "event": envelopes[idx].to_value() }))?;
                        conn.execute(
                            "INSERT INTO core_sync_changes \
                             (change_id, workspace_id, entity_type, event_type, operation, entity_id, thread_id, revision, entity_json, created_at) \
                             VALUES (?1,?2,?3,?4,'upsert',?5,?6,?7,?8,?9) \
                             ON CONFLICT(change_id) DO UPDATE SET \
                               entity_json = excluded.entity_json, \
                               revision = excluded.revision, \
                               event_type = excluded.event_type",
                            params![
                                envelopes[idx].event_id,
                                envelopes[idx].workspace_id,
                                envelopes[idx].entity_type,
                                envelopes[idx].event_type,
                                envelopes[idx].thread_id,
                                envelopes[idx].thread_id,
                                envelopes[idx].revision,
                                entity_str,
                                now_str,
                            ],
                        )?;
                    }
                }
            }

            cache_updates.push((
                thread_id.clone(),
                final_rev,
                snap_seq,
                active_turn_id.unwrap_or_default(),
                metadata_state,
                meta_bytes,
            ));
            summary_invalidations.push(thread_id);
        }

        Ok(envelopes)
    })?;

    if !cache_updates.is_empty() || !summary_invalidations.is_empty() {
        let mut cache = engine.cache.write().unwrap_or_else(|e| e.into_inner());
        for tid in summary_invalidations {
            cache.invalidate_thread(Some(&tid));
        }
        for (tid, rev, seq, active_tid, meta_state, meta_bytes) in cache_updates {
            cache.put_metadata_sized(tid, rev, seq, active_tid, meta_state, meta_bytes);
        }
    }

    let state_out = if return_state && project_snapshot && !last_thread_id.is_empty() {
        crate::snapshots::load_snapshot_full(engine, &last_thread_id)?
            .get("state")
            .cloned()
            .unwrap_or(Value::Null)
    } else {
        Value::Null
    };
    let env_vals: Vec<Value> = envelopes.into_iter().map(|e| e.to_value()).collect();
    Ok(json!({
        "envelopes": env_vals,
        "state": state_out,
    }))
}
