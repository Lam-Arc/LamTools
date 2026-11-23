//! C-ABI entrypoint and Rust-level concurrency/parity test suite for `sunday-core-db`.
//!
//! user:“加载/切换/多会话多 agent 同时读写”+(通过简洁的 C-ABI 暴露 Rust 存储引擎，绕开 Python 版本限制与 GIL 锁争用)。

pub mod pool;
pub mod projector;
pub mod repair;
pub mod runtime;
pub mod session_writes;
pub mod sessions;
pub mod snapshots;
pub mod sub_agents;
pub mod sync_ops;
pub mod wire_page;

use pool::{DbEngine, DbError};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::ffi::{CStr, CString};
use std::os::raw::c_char;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex, OnceLock};

static NEXT_HANDLE: AtomicU64 = AtomicU64::new(1);
static ENGINES: OnceLock<Mutex<HashMap<u64, Arc<DbEngine>>>> = OnceLock::new();

fn registry() -> &'static Mutex<HashMap<u64, Arc<DbEngine>>> {
    ENGINES.get_or_init(|| Mutex::new(HashMap::new()))
}

fn get_engine(handle: u64) -> Option<Arc<DbEngine>> {
    registry()
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .get(&handle)
        .cloned()
}

fn alloc_out(bytes: Vec<u8>, out_len: *mut usize) -> *mut u8 {
    let len = bytes.len();
    let mut boxed = bytes.into_boxed_slice();
    let ptr = boxed.as_mut_ptr();
    std::mem::forget(boxed);
    if !out_len.is_null() {
        unsafe {
            *out_len = len;
        }
    }
    ptr
}

fn err_response(code: &str, msg: &str) -> Vec<u8> {
    serde_json::to_vec(&json!({
        "ok": false,
        "error": code,
        "message": msg,
    }))
    .unwrap_or_else(|_| b"{\"ok\":false,\"error\":\"internal\",\"message\":\"serialize error\"}".to_vec())
}

fn ok_response(data: Value) -> Vec<u8> {
    serde_json::to_vec(&json!({
        "ok": true,
        "data": data,
    }))
    .unwrap_or_else(|e| err_response("serialize", &e.to_string()))
}

fn dispatch(engine: &DbEngine, op: &str, req: &Value) -> Result<Value, DbError> {
    match op {
        "stats" => Ok(engine.stats_json()),
        "invalidate_thread" => {
            let tid = req.get("thread_id").and_then(|v| v.as_str());
            engine.invalidate_thread(tid);
            Ok(json!({ "ok": true }))
        }
        "list_session_summaries" => sessions::list_session_summaries(engine),
        "list_core_sessions" => sessions::list_core_sessions(engine),
        "session_exists_meta" => {
            let tid = req
                .get("thread_id")
                .and_then(|v| v.as_str())
                .ok_or_else(|| DbError::Invalid("thread_id required".into()))?;
            sessions::session_exists_meta(engine, tid)
        }
        "build_sync_snapshot_threads" => sessions::build_sync_snapshot_threads(engine),
        "load_snapshot_metadata" => {
            let tid = req
                .get("thread_id")
                .and_then(|v| v.as_str())
                .ok_or_else(|| DbError::Invalid("thread_id required".into()))?;
            snapshots::load_snapshot_metadata(engine, tid)
        }
        "load_snapshot_full" => {
            let tid = req
                .get("thread_id")
                .and_then(|v| v.as_str())
                .ok_or_else(|| DbError::Invalid("thread_id required".into()))?;
            snapshots::load_snapshot_full(engine, tid)
        }
        "load_snapshot_page" => {
            let tid = req
                .get("thread_id")
                .and_then(|v| v.as_str())
                .ok_or_else(|| DbError::Invalid("thread_id required".into()))?;
            let before_seq = req.get("before_seq").and_then(|v| v.as_i64());
            let before_item_id = req.get("before_item_id").and_then(|v| v.as_str());
            let item_byte_budget = req
                .get("item_byte_budget")
                .and_then(|v| v.as_i64())
                .unwrap_or(1_500_000);
            snapshots::load_snapshot_page(engine, tid, before_seq, before_item_id, item_byte_budget)
        }
        "load_items_by_kind" => {
            let tid = req
                .get("thread_id")
                .and_then(|v| v.as_str())
                .ok_or_else(|| DbError::Invalid("thread_id required".into()))?;
            let text_marker = req
                .get("text_marker")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            let limit = req.get("limit").and_then(|v| v.as_i64()).unwrap_or(200_000);
            snapshots::load_items_by_kind(engine, tid, text_marker, limit)
        }
        "resolve_item_seq" => {
            let tid = req
                .get("thread_id")
                .and_then(|v| v.as_str())
                .ok_or_else(|| DbError::Invalid("thread_id required".into()))?;
            let item_id = req
                .get("item_id")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            let seq = engine.read(|conn| snapshots::resolve_item_seq_value(conn, engine, tid, item_id))?;
            Ok(json!({ "seq": seq }))
        }
        "load_page_around" => {
            let tid = req
                .get("thread_id")
                .and_then(|v| v.as_str())
                .ok_or_else(|| DbError::Invalid("thread_id required".into()))?;
            let item_id = req
                .get("item_id")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            let item_byte_budget = req
                .get("item_byte_budget")
                .and_then(|v| v.as_i64())
                .unwrap_or(1_500_000);
            snapshots::load_page_around(engine, tid, item_id, item_byte_budget)
        }
        "runtime_get" => {
            let sid = req
                .get("session_id")
                .and_then(|v| v.as_str())
                .ok_or_else(|| DbError::Invalid("session_id required".into()))?;
            runtime::runtime_get(engine, sid)
        }
        "runtime_save" => runtime::runtime_save(engine, req),
        "runtime_cas_patch" => runtime::runtime_cas_patch(engine, req),
        "runtime_append_history" => runtime::runtime_append_history(engine, req),
        "runtime_replace_history" => runtime::runtime_replace_history(engine, req),
        "runtime_get_history" => {
            let sid = req
                .get("session_id")
                .and_then(|v| v.as_str())
                .ok_or_else(|| DbError::Invalid("session_id required".into()))?;
            let after_seq = req.get("after_seq").and_then(|v| v.as_i64()).unwrap_or(0);
            runtime::runtime_get_history(engine, sid, after_seq)
        }
        "runtime_read_history_page" => {
            let sid = req
                .get("session_id")
                .and_then(|v| v.as_str())
                .ok_or_else(|| DbError::Invalid("session_id required".into()))?;
            let after_seq = req.get("after_seq").and_then(|v| v.as_i64()).unwrap_or(0);
            let limit = req.get("limit").and_then(|v| v.as_i64()).unwrap_or(200);
            runtime::runtime_read_history_page(engine, sid, after_seq, limit)
        }
        "runtime_history_max_seq" => {
            let sid = req
                .get("session_id")
                .and_then(|v| v.as_str())
                .ok_or_else(|| DbError::Invalid("session_id required".into()))?;
            runtime::runtime_history_max_seq(engine, sid)
        }
        "runtime_append_dialogue_record" => runtime::runtime_append_dialogue_record(engine, req),
        "runtime_list_dialogue_records" => {
            let sid = req
                .get("session_id")
                .and_then(|v| v.as_str())
                .ok_or_else(|| DbError::Invalid("session_id required".into()))?;
            runtime::runtime_list_dialogue_records(engine, sid)
        }
        "runtime_dialogue_record_epoch" => {
            let sid = req
                .get("session_id")
                .and_then(|v| v.as_str())
                .ok_or_else(|| DbError::Invalid("session_id required".into()))?;
            runtime::runtime_dialogue_record_epoch(engine, sid)
        }
        "runtime_list_thread_ids" => runtime::runtime_list_thread_ids(engine),
        "runtime_find_threads_with_metadata_key" => {
            let key = req.get("key").and_then(|v| v.as_str()).unwrap_or("");
            runtime::runtime_find_threads_with_metadata_key(engine, key)
        }
        "runtime_list_pending_approvals" => runtime::runtime_list_pending_approvals(engine),
        "runtime_list_live_status_rows" => runtime::runtime_list_live_status_rows(engine),
        "agent_run_upsert" => runtime::agent_run_upsert(engine, req),
        "agent_run_get" => {
            let id = req
                .get("agent_run_id")
                .and_then(|v| v.as_str())
                .ok_or_else(|| DbError::Invalid("agent_run_id required".into()))?;
            runtime::agent_run_get(engine, id)
        }
        "agent_run_list" => {
            let parent_turn_id = req.get("parent_turn_id").and_then(|v| v.as_str());
            let parent_thread_id = req.get("parent_thread_id").and_then(|v| v.as_str());
            let live_only = req.get("live_only").and_then(|v| v.as_bool()).unwrap_or(false);
            runtime::agent_run_list(engine, parent_turn_id, parent_thread_id, live_only)
        }
        "events_list_after" => {
            let tid = req
                .get("thread_id")
                .and_then(|v| v.as_str())
                .ok_or_else(|| DbError::Invalid("thread_id required".into()))?;
            let after_seq = req.get("after_seq").and_then(|v| v.as_i64()).unwrap_or(0);
            let limit = req.get("limit").and_then(|v| v.as_i64()).unwrap_or(500);
            runtime::events_list_after(engine, tid, after_seq, limit)
        }
        "events_list_thread" => {
            let tid = req
                .get("thread_id")
                .and_then(|v| v.as_str())
                .ok_or_else(|| DbError::Invalid("thread_id required".into()))?;
            let limit = req.get("limit").and_then(|v| v.as_i64());
            runtime::events_list_thread(engine, tid, limit)
        }
        "events_find_turn_event" => {
            let tid = req
                .get("thread_id")
                .and_then(|v| v.as_str())
                .ok_or_else(|| DbError::Invalid("thread_id required".into()))?;
            let turn_id = req
                .get("turn_id")
                .and_then(|v| v.as_str())
                .ok_or_else(|| DbError::Invalid("turn_id required".into()))?;
            let terminal_only = req
                .get("terminal_only")
                .and_then(|v| v.as_bool())
                .unwrap_or(false);
            runtime::events_find_turn_event(engine, tid, turn_id, terminal_only)
        }
        "events_find_client_event" => {
            let tid = req
                .get("thread_id")
                .and_then(|v| v.as_str())
                .ok_or_else(|| DbError::Invalid("thread_id required".into()))?;
            let cid = req
                .get("client_message_id")
                .and_then(|v| v.as_str())
                .ok_or_else(|| DbError::Invalid("client_message_id required".into()))?;
            let methods: Vec<String> = req
                .get("methods")
                .and_then(|v| v.as_array())
                .map(|arr| {
                    arr.iter()
                        .filter_map(|v| v.as_str().map(str::to_string))
                        .collect()
                })
                .unwrap_or_default();
            runtime::events_find_client_event(engine, tid, cid, &methods)
        }
        "append_and_project_batch" => projector::append_and_project_batch(engine, req),
        "session_create" => session_writes::session_create(engine, req),
        "session_update" => session_writes::session_update(engine, req),
        "session_patch" => session_writes::session_patch(engine, req),
        "session_delete" => session_writes::session_delete(engine, req),
        "session_persist_legacy_metadata" => session_writes::session_persist_legacy_metadata(engine, req),
        "sub_agent_init_db" => sub_agents::sub_agent_init_db(engine),
        "sub_agent_load" => sub_agents::sub_agent_load(engine, req),
        "sub_agent_list" => sub_agents::sub_agent_list(engine, req),
        "sub_agent_list_by_names" => sub_agents::sub_agent_list_by_names(engine, req),
        "sub_agent_save" => sub_agents::sub_agent_save(engine, req),
        "sub_agent_save_if_current" => sub_agents::sub_agent_save_if_current(engine, req),
        "sub_agent_delete_member" => sub_agents::sub_agent_delete_member(engine, req),
        "sub_agent_recover_mark_interrupted" => sub_agents::sub_agent_recover_mark_interrupted(engine, req),
        "sub_agent_mail_insert" => sub_agents::sub_agent_mail_insert(engine, req),
        "sub_agent_mail_mark_delivered_by_key" => sub_agents::sub_agent_mail_mark_delivered_by_key(engine, req),
        "sub_agent_pending_guidance" => sub_agents::sub_agent_pending_guidance(engine, req),
        "sub_agent_ack_guidance" => sub_agents::sub_agent_ack_guidance(engine, req),
        "sub_agent_drain_parent_mailbox" => sub_agents::sub_agent_drain_parent_mailbox(engine, req),
        "sub_agent_ack_parent_mailbox" => sub_agents::sub_agent_ack_parent_mailbox(engine, req),
        "sub_agent_ack_parent_guidance" => sub_agents::sub_agent_ack_parent_guidance(engine, req),
        "sub_agent_pending_event_count" => sub_agents::sub_agent_pending_event_count(engine, req),
        "sub_agent_write_event" => sub_agents::sub_agent_write_event(engine, req),
        "sub_agent_drain_member_events" => sub_agents::sub_agent_drain_member_events(engine, req),
        "sub_agent_list_threads_with_pending_wakes" => sub_agents::sub_agent_list_threads_with_pending_wakes(engine),
        "sub_agent_peek_wake_messages" => sub_agents::sub_agent_peek_wake_messages(engine, req),
        "sub_agent_bump_wake_counts" => sub_agents::sub_agent_bump_wake_counts(engine, req),
        "sub_agent_migrate_pending_member_events_to_wake" => sub_agents::sub_agent_migrate_pending_member_events_to_wake(engine, req),
        "sub_agent_auto_release_unanswered" => sub_agents::sub_agent_auto_release_unanswered(engine, req),
        "sub_agent_peek_member_events" => sub_agents::sub_agent_peek_member_events(engine, req),
        "sub_agent_mark_member_events_delivered" => sub_agents::sub_agent_mark_member_events_delivered(engine, req),
        "load_wire_page" => wire_page::load_wire_page(engine, req),
        "build_thread_outline" => wire_page::build_thread_outline_native(engine, req),
        "sync_run" => sync_ops::sync_run(engine, req),
        "sync_prune" => sync_ops::sync_prune(engine, req),
        "sync_cursors" => sync_ops::sync_cursors(engine, req),
        "sync_list_after" => sync_ops::sync_list_after(engine, req),
        "sync_get_change" => sync_ops::sync_get_change(engine, req),
        _ => Err(DbError::Invalid(format!("unknown operation: {op}"))),
    }
}

/// Open a `DbEngine` for `db_path` (UTF-8) and return a positive handle, or 0 on error.
#[no_mangle]
pub extern "C" fn sunday_core_db_open(db_path: *const c_char) -> u64 {
    if db_path.is_null() {
        return 0;
    }
    let Ok(cstr) = unsafe { CStr::from_ptr(db_path) }.to_str() else {
        return 0;
    };
    let Ok(engine) = DbEngine::open(cstr) else {
        return 0;
    };
    let handle = NEXT_HANDLE.fetch_add(1, Ordering::Relaxed);
    registry()
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .insert(handle, Arc::new(engine));
    handle
}

/// Close and drop the `DbEngine` for `handle`, releasing all SQLite file handles.
#[no_mangle]
pub extern "C" fn sunday_core_db_close(handle: u64) {
    let removed = registry()
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .remove(&handle);
    if let Some(engine) = removed {
        engine.close();
    }
}

/// Execute an operation with a UTF-8 JSON request payload and return an owned UTF-8 JSON buffer.
/// Caller must free the returned pointer using `sunday_core_db_free(ptr, out_len)`.
#[no_mangle]
pub extern "C" fn sunday_core_db_call(
    handle: u64,
    op: *const c_char,
    req_json: *const u8,
    req_len: usize,
    out_len: *mut usize,
) -> *mut u8 {
    let result = std::panic::catch_unwind(|| {
        let Some(engine) = get_engine(handle) else {
            return err_response("closed", "invalid or closed db handle");
        };
        if op.is_null() {
            return err_response("invalid", "op is null");
        }
        let Ok(op_str) = unsafe { CStr::from_ptr(op) }.to_str() else {
            return err_response("invalid", "op is not utf-8");
        };
        let req: Value = if req_json.is_null() || req_len == 0 {
            json!({})
        } else {
            let slice = unsafe { std::slice::from_raw_parts(req_json, req_len) };
            match serde_json::from_slice(slice) {
                Ok(v) => v,
                Err(e) => return err_response("json", &e.to_string()),
            }
        };
        match dispatch(&engine, op_str, &req) {
            Ok(data) => ok_response(data),
            Err(DbError::Conflict(msg)) => err_response("conflict", &msg),
            Err(DbError::Invalid(msg)) => err_response("invalid", &msg),
            Err(DbError::Closed) => err_response("closed", "engine closed"),
            Err(e) => err_response("db", &e.to_string()),
        }
    });

    match result {
        Ok(bytes) => alloc_out(bytes, out_len),
        Err(_) => alloc_out(err_response("panic", "unexpected panic in sunday-core-db"), out_len),
    }
}

#[no_mangle]
pub extern "C" fn sunday_core_db_free(ptr: *mut u8, len: usize) {
    if !ptr.is_null() && len > 0 {
        unsafe {
            let slice = std::slice::from_raw_parts_mut(ptr, len);
            drop(Box::from_raw(slice));
        }
    }
}

#[allow(dead_code)]
fn _cstr(s: &str) -> CString {
    CString::new(s).unwrap_or_default()
}
