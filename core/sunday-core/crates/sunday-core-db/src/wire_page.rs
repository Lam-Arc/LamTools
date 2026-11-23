//! Native Rust character/byte-bounded wire page slicer and thread outline extractor.
//!
//! user:“继续”+(在 Rust 侧直接完成分页字节裁剪、大图转引用与对话大纲提取，避免上千条消息经过跨语言多层 JSON 往返与二次测长)。

use crate::pool::{now_unix_secs, DbEngine, DbError};
use crate::snapshots::{
    backfill_thread_item_types_best_effort, load_metadata_for_outline, load_page_around,
    load_snapshot_page, query_items_by_kind_conn,
};
use rusqlite::{params, OptionalExtension};
use serde_json::{json, Map, Value};
use std::collections::{HashMap, HashSet};

const MAX_INLINE_ARTIFACT_BYTES: usize = 256 * 1024;
const DEFAULT_PAGE_BYTES: i64 = 2 * 1024 * 1024;
const MAX_PAGE_BYTES: i64 = 3 * 1024 * 1024;
const MIN_PAGE_BYTES: i64 = 64 * 1024;
const DEFAULT_OUTLINE_CHAR_LIMIT: usize = 240;
const MAX_OUTLINE_CHAR_LIMIT: usize = 4_096;

fn is_active_turn_status(s: &str) -> bool {
    matches!(s, "queued" | "running" | "waiting" | "stopping" | "interrupting")
}

fn page_item_byte_budget(page_bytes: i64) -> i64 {
    let raw = (page_bytes * 3) / 2;
    raw.max(1024 * 1024).min(8 * 1024 * 1024)
}

fn clamp_page_bytes(v: i64) -> i64 {
    v.max(MIN_PAGE_BYTES).min(MAX_PAGE_BYTES)
}

fn int_param(v: Option<&Value>, default: i64) -> i64 {
    let Some(val) = v else {
        return default;
    };
    if val.is_boolean() || val.is_null() {
        return default;
    }
    if let Some(n) = val.as_i64() {
        return n;
    }
    if let Some(f) = val.as_f64() {
        return f as i64;
    }
    if let Some(s) = val.as_str() {
        if let Ok(n) = s.trim().parse::<i64>() {
            return n;
        }
    }
    default
}

fn mime_from_data_url(value: &str) -> String {
    if !value.starts_with("data:") {
        return String::new();
    }
    let after = &value[5..];
    let header = after.split(',').next().unwrap_or("");
    header.split(';').next().unwrap_or("").trim().to_string()
}

fn decoded_data_url_size(value: &str) -> i64 {
    let Some((_, payload)) = value.split_once(',') else {
        return 0;
    };
    let tail_start = payload.len().saturating_sub(2);
    let padding = payload[tail_start..].bytes().filter(|&b| b == b'=').count();
    let est = ((payload.len() * 3) / 4).saturating_sub(padding);
    est as i64
}

fn is_large_data_url(v: &Value) -> bool {
    v.as_str()
        .map(|s| s.starts_with("data:") && s.len() > MAX_INLINE_ARTIFACT_BYTES)
        .unwrap_or(false)
}

fn artifact_has_large_inline_body(art: &Map<String, Value>) -> bool {
    if art.get("content").map(is_large_data_url).unwrap_or(false) {
        return true;
    }
    if let Some(meta) = art.get("metadata").and_then(|v| v.as_object()) {
        return meta.values().any(is_large_data_url);
    }
    false
}

fn artifact_reference(art: &Map<String, Value>) -> Value {
    let mut reference = art.clone();
    let mut mime = art
        .get("mime_type")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let mut size: Option<i64> = art.get("size_bytes").and_then(|v| {
        if v.is_boolean() { None } else { v.as_i64() }
    });
    let mut inline_bytes: i64 = 0;

    if size.is_none() {
        if let Some(meta) = art.get("metadata").and_then(|v| v.as_object()) {
            if let Some(declared) = meta.get("size_bytes").and_then(|v| {
                if v.is_boolean() { None } else { v.as_i64() }
            }) {
                size = Some(declared);
            }
        }
    }

    if let Some(meta) = art.get("metadata").and_then(|v| v.as_object()) {
        let mut trimmed = Map::new();
        for (k, v) in meta {
            if let Some(s) = v.as_str() {
                if s.starts_with("data:") {
                    inline_bytes += s.len() as i64;
                    if mime.is_empty() {
                        mime = mime_from_data_url(s);
                    }
                    if size.is_none() {
                        size = Some(decoded_data_url_size(s));
                    }
                    continue;
                }
            }
            trimmed.insert(k.clone(), v.clone());
        }
        reference.insert("metadata".into(), Value::Object(trimmed));
    }

    if let Some(s) = art.get("content").and_then(|v| v.as_str()) {
        if s.starts_with("data:") && s.len() > MAX_INLINE_ARTIFACT_BYTES {
            inline_bytes += s.len() as i64;
            if mime.is_empty() {
                mime = mime_from_data_url(s);
            }
            if size.is_none() {
                size = Some(decoded_data_url_size(s));
            }
            reference.remove("content");
        }
    }

    reference.insert("availability".into(), json!("reference"));
    if !mime.is_empty() {
        reference.insert("mime_type".into(), json!(mime));
    }
    if let Some(sz) = size {
        reference.insert("size_bytes".into(), json!(sz));
    }
    reference.insert("inline_bytes".into(), json!(inline_bytes));
    Value::Object(reference)
}

fn reference_oversized_item_artifacts(item: &Value) -> Value {
    let Some(obj) = item.as_object() else {
        return item.clone();
    };
    let Some(arts) = obj.get("artifacts").and_then(|v| v.as_array()) else {
        return item.clone();
    };
    if arts.is_empty() {
        return item.clone();
    }
    let mut replaced: Option<Vec<Value>> = None;
    for (idx, art) in arts.iter().enumerate() {
        if let Some(art_obj) = art.as_object() {
            if artifact_has_large_inline_body(art_obj) {
                let list = replaced.get_or_insert_with(|| arts.clone());
                list[idx] = artifact_reference(art_obj);
            }
        }
    }
    match replaced {
        None => item.clone(),
        Some(new_arts) => {
            let mut copy = obj.clone();
            copy.insert("artifacts".into(), Value::Array(new_arts));
            Value::Object(copy)
        }
    }
}

#[derive(Clone)]
struct TimelineEntry {
    seq: i64,
    source_rank: usize,
    order_index: usize,
    item_id: String,
    turn_id: String,
}

fn slice_wire_page(
    snapshot: &Value,
    before_item_id: Option<&str>,
    before_seq: Option<i64>,
    char_limit: i64,
    turn_limit: Option<i64>,
    byte_limit: i64,
    anchor_item_id: Option<&str>,
    anchor_seq: Option<i64>,
) -> Value {
    let snap_obj = snapshot.as_object();
    let core_obj = snap_obj
        .and_then(|s| s.get("core"))
        .and_then(|c| c.as_object());
    let empty_map = Map::new();
    let raw_core_items = core_obj
        .and_then(|c| c.get("items"))
        .and_then(|i| i.as_object())
        .unwrap_or(&empty_map);
    let raw_top_items = snap_obj
        .and_then(|s| s.get("items"))
        .and_then(|i| i.as_object())
        .unwrap_or(&empty_map);

    let raw_core_order: Vec<String> = core_obj
        .and_then(|c| c.get("item_order"))
        .and_then(|o| o.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str().map(str::to_string))
                .collect()
        })
        .unwrap_or_else(|| raw_core_items.keys().cloned().collect());
    let raw_top_order: Vec<String> = snap_obj
        .and_then(|s| s.get("item_order"))
        .and_then(|o| o.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str().map(str::to_string))
                .collect()
        })
        .unwrap_or_else(|| raw_top_items.keys().cloned().collect());

    let mut turn_index_opt: Option<HashMap<String, String>> = None;
    let mut turn_id_of = |item_id: &str, item: &Value| -> String {
        if let Some(direct) = item.get("turn_id").and_then(|v| v.as_str()).filter(|s| !s.is_empty()) {
            return direct.to_string();
        }
        let idx = turn_index_opt.get_or_insert_with(|| {
            let mut m = HashMap::new();
            for turns_val in [
                snap_obj.and_then(|s| s.get("turns")),
                core_obj.and_then(|c| c.get("turns")),
            ] {
                let Some(turns_map) = turns_val.and_then(|t| t.as_object()) else {
                    continue;
                };
                for (raw_tid, raw_t) in turns_map {
                    let Some(tobj) = raw_t.as_object() else {
                        continue;
                    };
                    let tid = tobj
                        .get("turn_id")
                        .and_then(|v| v.as_str())
                        .filter(|s| !s.is_empty())
                        .unwrap_or(raw_tid)
                        .to_string();
                    if let Some(items_arr) = tobj.get("items").and_then(|v| v.as_array()) {
                        for ri in items_arr {
                            let iid = match ri {
                                Value::String(s) => s.clone(),
                                other => other.to_string(),
                            };
                            m.entry(iid).or_insert_with(|| tid.clone());
                        }
                    }
                }
            }
            m
        });
        idx.get(item_id).cloned().unwrap_or_default()
    };

    let has_seqless_item = [raw_top_items, raw_core_items].iter().any(|src| {
        src.values().any(|item| {
            item.is_object()
                && int_param(item.get("seq").or_else(|| item.get("last_seq")), 0) == 0
        })
    });

    let mut ordered_by_id: HashMap<String, TimelineEntry> = HashMap::new();
    if has_seqless_item {
        for (source_rank, (raw_order, raw_items)) in [
            (&raw_top_order, raw_top_items),
            (&raw_core_order, raw_core_items),
        ]
        .into_iter()
        .enumerate()
        {
            for (idx0, iid) in raw_order.iter().enumerate() {
                let index = idx0 + 1;
                let Some(item) = raw_items.get(iid).filter(|v| v.is_object()) else {
                    continue;
                };
                let seq = int_param(item.get("seq").or_else(|| item.get("last_seq")), index as i64);
                let tid = turn_id_of(iid, item);
                match ordered_by_id.get_mut(iid) {
                    None => {
                        ordered_by_id.insert(
                            iid.clone(),
                            TimelineEntry {
                                seq,
                                source_rank,
                                order_index: index,
                                item_id: iid.clone(),
                                turn_id: tid,
                            },
                        );
                    }
                    Some(prev) => {
                        if prev.turn_id.is_empty() && !tid.is_empty() {
                            prev.turn_id = tid;
                        }
                    }
                }
            }
        }
    } else {
        for (source_rank, raw_items) in [raw_top_items, raw_core_items].into_iter().enumerate() {
            for (iid, item) in raw_items {
                if !item.is_object() {
                    continue;
                }
                let seq = int_param(item.get("seq").or_else(|| item.get("last_seq")), 0);
                let tid = turn_id_of(iid, item);
                ordered_by_id.insert(
                    iid.clone(),
                    TimelineEntry {
                        seq,
                        source_rank,
                        order_index: 0,
                        item_id: iid.clone(),
                        turn_id: tid,
                    },
                );
            }
        }
    }

    let mut full_order: Vec<TimelineEntry> = ordered_by_id.into_values().collect();
    full_order.sort_by(|a, b| {
        (a.seq, a.source_rank, a.order_index, &a.item_id)
            .cmp(&(b.seq, b.source_rank, b.order_index, &b.item_id))
    });

    let total_items: i64 = if let Some(pt) = core_obj
        .and_then(|c| c.get("_page_total_items"))
        .and_then(|v| if v.is_boolean() { None } else { v.as_i64() })
    {
        pt + (raw_top_order.len() as i64)
    } else {
        let mut union_ids: HashSet<&str> = HashSet::new();
        for s in &raw_top_order {
            union_ids.insert(s.as_str());
        }
        for s in &raw_core_order {
            union_ids.insert(s.as_str());
        }
        for e in &full_order {
            union_ids.insert(e.item_id.as_str());
        }
        union_ids.len() as i64
    };

    let ordered_slice: &[TimelineEntry] = if let Some(bid) = before_item_id.filter(|s| !s.is_empty()) {
        if let Some(pos) = full_order.iter().position(|e| e.item_id == bid) {
            &full_order[..pos]
        } else {
            &full_order
        }
    } else if let Some(bseq) = before_seq {
        let end = full_order.iter().take_while(|e| e.seq < bseq).count();
        // When items aren't strictly monotonic only filter like Python
        if end == full_order.len() || full_order[end..].iter().all(|e| e.seq >= bseq) {
            &full_order[..end]
        } else {
            &full_order
        }
    } else {
        &full_order
    };
    let ordered_owned: Vec<TimelineEntry>;
    let ordered: &[TimelineEntry] = if before_item_id.is_none() || ordered_slice.len() == full_order.len() {
        if let Some(bseq) = before_seq {
            if before_item_id.filter(|bid| full_order.iter().any(|e| &e.item_id == bid)).is_none() {
                ordered_owned = full_order.iter().filter(|e| e.seq < bseq).cloned().collect();
                &ordered_owned
            } else {
                ordered_slice
            }
        } else {
            ordered_slice
        }
    } else {
        ordered_slice
    };

    let mut wired_top: HashMap<String, Value> = HashMap::new();
    let mut wired_core: HashMap<String, Value> = HashMap::new();
    let mut char_sizes: HashMap<String, usize> = HashMap::new();
    let mut byte_sizes: HashMap<String, usize> = HashMap::new();

    let mut get_wire_top = |iid: &str| -> Option<Value> {
        let item = raw_top_items.get(iid).filter(|v| v.is_object())?;
        Some(
            wired_top
                .entry(iid.to_string())
                .or_insert_with(|| reference_oversized_item_artifacts(item))
                .clone(),
        )
    };
    let mut get_wire_core = |iid: &str| -> Option<Value> {
        let item = raw_core_items.get(iid).filter(|v| v.is_object())?;
        Some(
            wired_core
                .entry(iid.to_string())
                .or_insert_with(|| reference_oversized_item_artifacts(item))
                .clone(),
        )
    };

    let mut measure_item = |iid: &str| -> (usize, usize) {
        if let (Some(&c), Some(&b)) = (char_sizes.get(iid), byte_sizes.get(iid)) {
            return (c, b);
        }
        let mut chars = 0_usize;
        let mut bytes = 0_usize;
        if let Some(v) = get_wire_top(iid) {
            if let Ok(s) = serde_json::to_string(&v) {
                chars += s.chars().count();
                bytes += s.len();
            }
        }
        if let Some(v) = get_wire_core(iid) {
            if let Ok(s) = serde_json::to_string(&v) {
                chars += s.chars().count();
                bytes += s.len();
            }
        }
        char_sizes.insert(iid.to_string(), chars);
        byte_sizes.insert(iid.to_string(), bytes);
        (chars, bytes)
    };

    let mut selected: Vec<TimelineEntry> = Vec::new();
    if let Some(tl) = turn_limit {
        let tl_usize = tl.max(0) as usize;
        let mut selected_turns: HashSet<String> = HashSet::new();
        let mut selected_bytes: i64 = 0;
        for entry in ordered.iter().rev() {
            let turn_key = if entry.turn_id.is_empty() {
                format!("item:{}", entry.item_id)
            } else {
                entry.turn_id.clone()
            };
            if !selected_turns.contains(&turn_key) && selected_turns.len() >= tl_usize {
                continue;
            }
            let (_, item_bytes) = measure_item(&entry.item_id);
            let item_b = item_bytes as i64;
            if !selected.is_empty() && selected_bytes + item_b > byte_limit {
                break;
            }
            selected.push(entry.clone());
            selected_bytes += item_b;
            selected_turns.insert(turn_key);
        }
        selected.reverse();
    } else {
        let mut char_count: i64 = 0;
        for entry in ordered.iter().rev() {
            let (item_chars, _) = measure_item(&entry.item_id);
            let item_c = item_chars as i64;
            if !selected.is_empty() && char_count + item_c > char_limit {
                break;
            }
            selected.push(entry.clone());
            char_count += item_c;
        }
        selected.reverse();
    }

    let selected_ids: HashSet<String> = selected.iter().map(|e| e.item_id.clone()).collect();
    let earliest_seq: Option<i64> = selected.iter().map(|e| e.seq).min();
    let has_older = core_obj
        .and_then(|c| c.get("_page_has_older_items"))
        .and_then(|v| v.as_bool())
        .unwrap_or(false);
    let has_more = selected.len() < ordered.len() || has_older;

    let mut selected_turn_max_seq: HashMap<String, i64> = HashMap::new();
    for e in &selected {
        if let Some(item) = raw_core_items.get(&e.item_id).and_then(|v| v.as_object()) {
            let tid = item.get("turn_id").and_then(|v| v.as_str()).unwrap_or("");
            if !tid.is_empty() {
                let cur = selected_turn_max_seq.entry(tid.to_string()).or_insert(e.seq);
                if e.seq > *cur {
                    *cur = e.seq;
                }
            }
        }
    }

    let mut context_user_ids: HashSet<String> = HashSet::new();
    for (idx0, iid) in raw_top_order.iter().enumerate() {
        let index = (idx0 + 1) as i64;
        let Some(item) = raw_top_items.get(iid).and_then(|v| v.as_object()) else {
            continue;
        };
        // user:“查一下 constant 内会话为什么出现了：部分消息在最新消息的下方”
        // +(systemMessage 触发的子代理回报等回合同样需要保留开场条目，避免跨分页截断后失去所属回合锚点)
        let item_type = item.get("type").and_then(|v| v.as_str());
        if item_type != Some("userMessage") && item_type != Some("systemMessage") {
            continue;
        }
        let tid = item.get("turn_id").and_then(|v| v.as_str()).unwrap_or("");
        let Some(&max_seq) = selected_turn_max_seq.get(tid) else {
            continue;
        };
        let seq = int_param(item.get("seq").or_else(|| item.get("last_seq")), index);
        if seq <= max_seq {
            context_user_ids.insert(iid.clone());
        }
    }

    let mut visible_ids: HashSet<String> = selected_ids.clone();
    visible_ids.extend(context_user_ids.iter().cloned());

    let mut character_count: i64 = 0;
    for e in &selected {
        let (c, _) = measure_item(&e.item_id);
        character_count += c as i64;
    }
    for iid in &context_user_ids {
        if !selected_ids.contains(iid) {
            if let Some(item) = raw_top_items.get(iid) {
                if let Ok(s) = serde_json::to_string(item) {
                    character_count += s.chars().count() as i64;
                }
            }
        }
    }

    let mut page_bytes: i64 = 0;
    for e in &selected {
        let (_, b) = measure_item(&e.item_id);
        page_bytes += b as i64;
    }

    let mut visible_turn_ids: HashSet<String> = selected
        .iter()
        .filter(|e| !e.turn_id.is_empty())
        .map(|e| e.turn_id.clone())
        .collect();
    for iid in &context_user_ids {
        if let Some(tid) = raw_top_items
            .get(iid)
            .and_then(|i| i.get("turn_id"))
            .and_then(|v| v.as_str())
            .filter(|s| !s.is_empty())
        {
            visible_turn_ids.insert(tid.to_string());
        }
    }

    let filtered_turns = |turns_val: Option<&Value>| -> Value {
        let Some(turns_map) = turns_val.and_then(|v| v.as_object()) else {
            return json!({});
        };
        let mut out = Map::new();
        for (tid, raw_turn) in turns_map {
            let Some(tobj) = raw_turn.as_object() else {
                continue;
            };
            if visible_turn_ids.contains(tid) {
                let mut copy = tobj.clone();
                let kept_items: Vec<Value> = tobj
                    .get("items")
                    .and_then(|v| v.as_array())
                    .map(|arr| {
                        arr.iter()
                            .filter_map(|x| {
                                let s = match x {
                                    Value::String(s) => s.clone(),
                                    other => other.to_string(),
                                };
                                if visible_ids.contains(&s) {
                                    Some(Value::String(s))
                                } else {
                                    None
                                }
                            })
                            .collect()
                    })
                    .unwrap_or_default();
                copy.insert("items".into(), Value::Array(kept_items));
                out.insert(tid.clone(), Value::Object(copy));
            } else if tobj
                .get("status")
                .and_then(|v| v.as_str())
                .map(is_active_turn_status)
                .unwrap_or(false)
            {
                let mut copy = tobj.clone();
                copy.insert("items".into(), json!([]));
                out.insert(tid.clone(), Value::Object(copy));
            }
        }
        Value::Object(out)
    };

    let mut page_core_items = Map::new();
    for iid in &selected_ids {
        if let Some(v) = get_wire_core(iid) {
            page_core_items.insert(iid.clone(), v);
        }
    }
    let mut page_top_items = Map::new();
    for iid in &visible_ids {
        if let Some(v) = get_wire_top(iid) {
            page_top_items.insert(iid.clone(), v);
        }
    }

    let page_core_order: Vec<Value> = full_order
        .iter()
        .filter(|e| page_core_items.contains_key(&e.item_id))
        .map(|e| Value::String(e.item_id.clone()))
        .collect();
    let page_top_order: Vec<Value> = full_order
        .iter()
        .filter(|e| page_top_items.contains_key(&e.item_id))
        .map(|e| Value::String(e.item_id.clone()))
        .collect();

    let mut page_core = core_obj.cloned().unwrap_or_default();
    page_core.remove("_page_has_older_items");
    page_core.remove("_page_total_items");
    page_core.insert("items".into(), Value::Object(page_core_items));
    page_core.insert("turns".into(), filtered_turns(core_obj.and_then(|c| c.get("turns"))));
    page_core.insert("artifacts".into(), json!({}));
    page_core.insert("seen_event_ids".into(), json!([]));
    page_core.insert("item_order".into(), Value::Array(page_core_order));

    let mut page = snap_obj.cloned().unwrap_or_default();
    page.insert("core".into(), Value::Object(page_core));
    page.insert("items".into(), Value::Object(page_top_items));
    page.insert("turns".into(), filtered_turns(snap_obj.and_then(|s| s.get("turns"))));
    page.insert("artifacts".into(), json!({}));
    page.insert("seen_event_ids".into(), json!([]));
    page.insert("item_order".into(), Value::Array(page_top_order));

    let turn_count = selected
        .iter()
        .map(|e| {
            if e.turn_id.is_empty() {
                format!("item:{}", e.item_id)
            } else {
                e.turn_id.clone()
            }
        })
        .collect::<HashSet<_>>()
        .len();

    let next_before_item_id = if has_more && !selected.is_empty() {
        Value::String(selected[0].item_id.clone())
    } else {
        Value::Null
    };
    let next_before_seq = if has_more {
        earliest_seq.map(|n| json!(n)).unwrap_or(Value::Null)
    } else {
        Value::Null
    };
    let page_max_seq = selected.last().map(|e| json!(e.seq)).unwrap_or(Value::Null);

    page.insert(
        "history_page".into(),
        json!({
            "char_limit": char_limit,
            "character_count": character_count,
            "byte_limit": byte_limit,
            "byte_count": page_bytes,
            "turn_limit": turn_limit,
            "turn_count": turn_count,
            "item_count": visible_ids.len(),
            "total_items": total_items,
            "has_more": has_more,
            "next_before_item_id": next_before_item_id,
            "next_before_seq": next_before_seq,
            "anchor_item_id": anchor_item_id,
            "anchor_seq": anchor_seq,
            "page_min_seq": earliest_seq,
            "page_max_seq": page_max_seq,
        }),
    );

    Value::Object(page)
}

pub fn load_wire_page(engine: &DbEngine, req: &Value) -> Result<Value, DbError> {
    let tid = req
        .get("thread_id")
        .and_then(|v| v.as_str())
        .ok_or_else(|| DbError::Invalid("thread_id required".into()))?;
    let before_item_id = req.get("before_item_id").and_then(|v| v.as_str()).filter(|s| !s.is_empty());
    let before_seq = req.get("before_seq").and_then(|v| v.as_i64());
    let char_limit = req
        .get("char_limit")
        .and_then(|v| v.as_i64())
        .unwrap_or(200_000)
        .max(1_000)
        .min(1_000_000);
    let turn_limit = req
        .get("turn_limit")
        .and_then(|v| if v.is_null() { None } else { v.as_i64() })
        .map(|n| n.max(1).min(100));
    let byte_limit = clamp_page_bytes(
        req.get("byte_limit")
            .and_then(|v| v.as_i64())
            .unwrap_or(DEFAULT_PAGE_BYTES),
    );
    let anchor_item_id = req.get("anchor_item_id").and_then(|v| v.as_str()).filter(|s| !s.is_empty());

    let item_byte_budget = page_item_byte_budget(byte_limit);

    let (raw_res, resolved_before_seq, resolved_before_id, resolved_anchor_seq) =
        if let Some(aid) = anchor_item_id {
            let around = load_page_around(engine, tid, aid, item_byte_budget)?;
            let anchor_seq_opt = around.get("anchor_seq").and_then(|v| v.as_i64());
            let Some(aseq) = anchor_seq_opt else {
                return Ok(json!({
                    "found": false,
                    "needs_usage_hydration": false,
                    "snapshot": Value::Null,
                }));
            };
            let page_res = around.get("page").cloned().unwrap_or(Value::Null);
            (page_res, Some(aseq + 1), None, Some(aseq))
        } else {
            let page_res = load_snapshot_page(engine, tid, before_seq, before_item_id, item_byte_budget)?;
            let eff_before_seq = page_res
                .get("resolved_before_seq")
                .and_then(|v| v.as_i64())
                .or(before_seq);
            (page_res, eff_before_seq, before_item_id, None)
        };

    let needs_hydration = raw_res
        .get("needs_usage_hydration")
        .and_then(|v| v.as_bool())
        .unwrap_or(false);
    if needs_hydration {
        return Ok(json!({
            "found": true,
            "needs_usage_hydration": true,
            "snapshot": Value::Null,
        }));
    }

    let state = raw_res.get("state").cloned().unwrap_or(Value::Null);
    let wire_page = slice_wire_page(
        &state,
        resolved_before_id,
        resolved_before_seq,
        char_limit,
        turn_limit,
        byte_limit,
        anchor_item_id,
        resolved_anchor_seq,
    );
    let snapshot_seq = state
        .get("snapshot_seq")
        .and_then(|v| v.as_i64())
        .unwrap_or(0);
    Ok(json!({
        "found": true,
        "needs_usage_hydration": false,
        "snapshot_seq": snapshot_seq,
        "anchor_seq": resolved_anchor_seq,
        "snapshot": wire_page,
    }))
}

fn outline_item_type(item: &Map<String, Value>) -> String {
    if let Some(s) = item.get("type").and_then(|v| v.as_str()).map(str::trim).filter(|s| !s.is_empty()) {
        return s.to_string();
    }
    item.get("payload")
        .and_then(|p| p.get("type"))
        .and_then(|v| v.as_str())
        .map(str::trim)
        .unwrap_or("")
        .to_string()
}

fn outline_parent_item_id(item: &Map<String, Value>) -> String {
    if let Some(s) = item
        .get("parent_item_id")
        .or_else(|| item.get("parentItemId"))
        .and_then(|v| v.as_str())
        .map(str::trim)
        .filter(|s| !s.is_empty())
    {
        return s.to_string();
    }
    item.get("metadata")
        .and_then(|m| m.get("parent_item_id").or_else(|| m.get("parentItemId")))
        .and_then(|v| v.as_str())
        .map(str::trim)
        .unwrap_or("")
        .to_string()
}

fn outline_is_child_owned(item: &Map<String, Value>) -> bool {
    let Some(payload) = item.get("payload").and_then(|v| v.as_object()) else {
        return false;
    };
    if payload.get("sub_agent").map(|v| v.is_object()).unwrap_or(false) {
        return true;
    }
    if let Some(meta) = payload.get("metadata").and_then(|v| v.as_object()) {
        let sa = meta.get("sub_agent").map(|v| !v.is_null() && v != &json!(false) && v != &json!("")).unwrap_or(false);
        let ss = meta.get("sub_session_id").map(|v| !v.is_null() && v != &json!(false) && v != &json!("")).unwrap_or(false);
        if sa || ss {
            return true;
        }
    }
    false
}

fn outline_item_seq(item: &Map<String, Value>) -> Option<i64> {
    for k in ["seq", "last_seq"] {
        let Some(val) = item.get(k) else {
            continue;
        };
        let n = int_param(Some(val), 0);
        if n > 0 {
            return Some(n);
        }
    }
    None
}

fn outline_order_ids(raw_order: Option<&Value>, items: &Map<String, Value>) -> Vec<String> {
    if let Some(arr) = raw_order.and_then(|v| v.as_array()) {
        let mut ordered = Vec::with_capacity(arr.len().max(items.len()));
        let mut known = HashSet::new();
        for v in arr {
            let s = match v {
                Value::String(st) => st.clone(),
                Value::Null => String::new(),
                other => other.to_string(),
            };
            if !s.is_empty() {
                known.insert(s.clone());
                ordered.push(s);
            }
        }
        for k in items.keys() {
            if !k.is_empty() && !known.contains(k) {
                ordered.push(k.clone());
            }
        }
        ordered
    } else {
        items.keys().filter(|k| !k.is_empty()).cloned().collect()
    }
}

fn outline_input_text(item: &Map<String, Value>) -> String {
    let val = item
        .get("content")
        .or_else(|| item.get("payload").and_then(|p| p.get("content")));
    match val {
        Some(Value::String(s)) => s.trim().to_string(),
        Some(Value::Array(arr)) => {
            let parts: Vec<String> = arr
                .iter()
                .filter_map(|e| e.as_object())
                .filter_map(|e| {
                    let typ = e.get("type").and_then(|v| v.as_str()).unwrap_or("");
                    if typ == "image" || typ == "attachment" {
                        e.get("name").or_else(|| e.get("path")).and_then(|v| v.as_str()).map(|s| s.trim().to_string())
                    } else {
                        e.get("text").and_then(|v| v.as_str()).map(|s| s.trim().to_string())
                    }
                })
                .filter(|s| !s.is_empty())
                .collect();
            parts.join("\n")
        }
        Some(Value::Object(m)) => m
            .get("text")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim()
            .to_string(),
        _ => String::new(),
    }
}

fn outline_item_text(item: &Map<String, Value>) -> String {
    let candidates = [
        item.get("content"),
        item.get("payload").and_then(|p| p.get("content")),
        item.get("text"),
        item.get("payload").and_then(|p| p.get("text")),
    ];
    for c in candidates {
        if let Some(Value::String(s)) = c {
            return s.clone();
        }
    }
    if let Some(arr) = item.get("deltas").and_then(|v| v.as_array()) {
        let mut joined = String::new();
        for v in arr {
            if let Some(s) = v.as_str() {
                joined.push_str(s);
            }
        }
        return joined;
    }
    String::new()
}

fn is_protocol_envelope_text(content: &str) -> bool {
    let text = content.trim();
    if !text.starts_with('{') || !text.ends_with('}') {
        return false;
    }
    let Ok(Value::Object(obj)) = serde_json::from_str::<Value>(text) else {
        return false;
    };
    if obj.get("jsonrpc").and_then(|v| v.as_str()) == Some("2.0")
        && (obj.contains_key("method") || obj.contains_key("result") || obj.contains_key("error"))
    {
        return true;
    }
    obj.get("event").map(|v| v.is_string()).unwrap_or(false)
        && (obj.contains_key("payload") || obj.contains_key("params"))
}

fn bound_text_chars(s: &str, limit: usize) -> String {
    s.chars().take(limit).collect()
}

pub fn build_thread_outline_native(engine: &DbEngine, req: &Value) -> Result<Value, DbError> {
    let tid = req
        .get("thread_id")
        .and_then(|v| v.as_str())
        .ok_or_else(|| DbError::Invalid("thread_id required".into()))?;
    let limit_raw = int_param(req.get("char_limit"), DEFAULT_OUTLINE_CHAR_LIMIT as i64);
    let char_limit = (limit_raw as usize).max(1).min(MAX_OUTLINE_CHAR_LIMIT);
    let char_limit_i64 = char_limit as i64;

    // user:“规划并实现”+(大纲直走版本校验的内存+SQLite持久缓存，未命中时仅按 item_type='agentMessage' 走索引且完全跳过 usage hydration)
    enum OutlineLookup {
        Empty,
        Cached(Value),
        Miss {
            db_rev: i64,
            db_seq: i64,
            state: Value,
            core_items: Map<String, Value>,
            saw_null_type: bool,
        },
    }

    let lookup = engine.read(|conn| {
        let probe: Option<(i64, i64)> = conn
            .query_row(
                "SELECT COALESCE(revision, 0), COALESCE(snapshot_seq, 0) FROM core_thread_snapshots WHERE thread_id = ?1",
                [tid],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .optional()?;
        let Some((db_rev, db_seq)) = probe else {
            return Ok(OutlineLookup::Empty);
        };

        if let Ok(cache) = engine.cache.read() {
            if let Some(hit) = cache.get_outline(tid, char_limit_i64, db_rev, db_seq) {
                return Ok(OutlineLookup::Cached(hit));
            }
        }

        let cached_sql: Option<String> = conn
            .query_row(
                "SELECT outline_json FROM core_thread_outlines \
                 WHERE thread_id = ?1 AND char_limit = ?2 AND revision = ?3 AND snapshot_seq = ?4",
                params![tid, char_limit_i64, db_rev, db_seq],
                |r| r.get(0),
            )
            .optional()?;
        if let Some(raw_outline) = cached_sql {
            if let Ok(parsed) = serde_json::from_str::<Value>(&raw_outline) {
                if parsed.is_object() {
                    if let Ok(mut wcache) = engine.cache.write() {
                        wcache.put_outline(tid.to_string(), char_limit_i64, db_rev, db_seq, parsed.clone());
                    }
                    return Ok(OutlineLookup::Cached(parsed));
                }
            }
        }

        let Some((_, _, mut state)) = load_metadata_for_outline(conn, engine, tid)? else {
            return Ok(OutlineLookup::Empty);
        };
        crate::snapshots::hydrate_snapshot_turns_conn(conn, tid, &mut state, None)?;
        let (core_items, saw_null_type) = query_items_by_kind_conn(conn, tid, "agentMessage", 200_000)?;
        Ok(OutlineLookup::Miss {
            db_rev,
            db_seq,
            state,
            core_items,
            saw_null_type,
        })
    })?;

    let (db_rev, db_seq, state, core_items) = match lookup {
        OutlineLookup::Empty => {
            return Ok(json!({
                "needs_usage_hydration": false,
                "outline": {
                    "thread": { "id": tid },
                    "items": [],
                }
            }));
        }
        OutlineLookup::Cached(cached) => {
            return Ok(json!({
                "needs_usage_hydration": false,
                "outline": cached,
            }));
        }
        OutlineLookup::Miss {
            db_rev,
            db_seq,
            state,
            core_items,
            saw_null_type,
        } => {
            if saw_null_type {
                backfill_thread_item_types_best_effort(engine, tid);
            }
            (db_rev, db_seq, state, core_items)
        }
    };

    let state_obj = state.as_object();
    let core_obj = state_obj.and_then(|s| s.get("core")).and_then(|c| c.as_object());
    let empty_map = Map::new();
    let outer_items = state_obj.and_then(|s| s.get("items")).and_then(|i| i.as_object()).unwrap_or(&empty_map);

    struct OutlineRow {
        is_outer: bool,
        item_id: String,
        item: Map<String, Value>,
        raw_seq: Option<i64>,
        seq: i64,
        source_rank: usize,
        order_rank: usize,
    }

    let mut rows: Vec<OutlineRow> = Vec::new();
    let mut seen: HashSet<String> = HashSet::new();
    for (source_rank, (is_outer, items, raw_order)) in [
        (true, outer_items, state_obj.and_then(|s| s.get("item_order"))),
        (false, &core_items, core_obj.and_then(|c| c.get("item_order"))),
    ]
    .into_iter()
    .enumerate()
    {
        let order = outline_order_ids(raw_order, items);
        for (idx0, iid) in order.into_iter().enumerate() {
            if !seen.insert(iid.clone()) {
                continue;
            }
            let Some(item_obj) = items.get(&iid).and_then(|v| v.as_object()) else {
                continue;
            };
            let raw_seq = outline_item_seq(item_obj);
            rows.push(OutlineRow {
                is_outer,
                item_id: iid,
                item: item_obj.clone(),
                raw_seq,
                seq: 0,
                source_rank,
                order_rank: idx0 + 1,
            });
        }
    }

    rows.sort_by(|a, b| {
        let ka = (
            if a.raw_seq.is_some() { 0_u8 } else { 1_u8 },
            a.raw_seq.unwrap_or(0),
            a.source_rank,
            a.order_rank,
            &a.item_id,
        );
        let kb = (
            if b.raw_seq.is_some() { 0_u8 } else { 1_u8 },
            b.raw_seq.unwrap_or(0),
            b.source_rank,
            b.order_rank,
            &b.item_id,
        );
        ka.cmp(&kb)
    });
    for (idx0, r) in rows.iter_mut().enumerate() {
        r.seq = r.raw_seq.unwrap_or((idx0 + 1) as i64);
    }

    let mut turn_by_id: HashMap<String, Map<String, Value>> = HashMap::new();
    for turns_val in [
        state_obj.and_then(|s| s.get("turns")),
        core_obj.and_then(|c| c.get("turns")),
    ] {
        let Some(turns_map) = turns_val.and_then(|v| v.as_object()) else {
            continue;
        };
        for (raw_id, turn_val) in turns_map {
            if let Some(tobj) = turn_val.as_object() {
                let turn_id = tobj
                    .get("turn_id")
                    .and_then(|v| v.as_str())
                    .filter(|s| !s.is_empty())
                    .unwrap_or(raw_id)
                    .to_string();
                if !turn_id.is_empty() && !turn_by_id.contains_key(&turn_id) {
                    turn_by_id.insert(turn_id, tobj.clone());
                }
            }
        }
    }

    let mut outlines: Vec<Value> = Vec::new();
    let mut current: Option<(Map<String, Value>, bool)> = None;

    for row in rows {
        let itype = outline_item_type(&row.item);
        if row.is_outer && itype == "userMessage" && outline_parent_item_id(&row.item).is_empty() {
            if let Some((cur, _)) = current.take() {
                outlines.push(Value::Object(cur));
            }
            let direct_tid = row
                .item
                .get("turn_id")
                .or_else(|| row.item.get("turnId"))
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .trim()
                .to_string();
            let turn_id = if !direct_tid.is_empty() {
                direct_tid
            } else {
                let iid_key = if !row.item_id.is_empty() {
                    row.item_id.clone()
                } else {
                    row.item.get("item_id").and_then(|v| v.as_str()).unwrap_or("").to_string()
                };
                turn_by_id
                    .iter()
                    .find_map(|(tid, tobj)| {
                        tobj.get("items").and_then(|v| v.as_array()).and_then(|arr| {
                            if arr.iter().any(|x| x.as_str() == Some(iid_key.as_str())) {
                                Some(tid.clone())
                            } else {
                                None
                            }
                        })
                    })
                    .unwrap_or_default()
            };
            let turn_opt = if turn_id.is_empty() { None } else { turn_by_id.get(&turn_id) };
            let ts_val: Value = [
                row.item.get("timestamp"),
                row.item.get("created_at"),
                row.item.get("payload").and_then(|p| p.get("timestamp")),
                row.item.get("payload").and_then(|p| p.get("created_at")),
                turn_opt.and_then(|t| t.get("timestamp")),
                turn_opt.and_then(|t| t.get("created_at")),
            ]
            .into_iter()
            .flatten()
            .filter_map(|v| v.as_str().map(str::trim).filter(|s| !s.is_empty()))
            .next()
            .map(|s| json!(s))
            .unwrap_or(Value::Null);

            let mut obj = Map::new();
            obj.insert("message_id".into(), json!(row.item_id));
            obj.insert("turn_id".into(), json!(turn_id));
            obj.insert("seq".into(), json!(row.seq));
            obj.insert("timestamp".into(), ts_val);
            obj.insert("prompt".into(), json!(bound_text_chars(&outline_input_text(&row.item), char_limit)));
            obj.insert("response_excerpt".into(), json!(""));
            let is_queued = row.item.get("status").and_then(|v| v.as_str()) == Some("queued");
            current = Some((obj, is_queued));
            continue;
        }

        let Some((ref mut cur_obj, cur_queued)) = current else {
            continue;
        };
        if itype != "agentMessage"
            || !outline_parent_item_id(&row.item).is_empty()
            || outline_is_child_owned(&row.item)
            || cur_queued
        {
            continue;
        }
        let text = outline_item_text(&row.item).trim().to_string();
        if text.is_empty() || is_protocol_envelope_text(&text) {
            continue;
        }
        cur_obj.insert("response_excerpt".into(), json!(bound_text_chars(&text, char_limit)));
    }

    if let Some((cur, _)) = current.take() {
        outlines.push(Value::Object(cur));
    }

    let outline = json!({
        "thread": { "id": tid },
        "items": outlines,
    });
    if let Ok(mut wcache) = engine.cache.write() {
        wcache.put_outline(tid.to_string(), char_limit_i64, db_rev, db_seq, outline.clone());
    }
    if let Ok(outline_str) = serde_json::to_string(&outline) {
        let now = now_unix_secs();
        let _ = engine.try_write_tx(|conn| {
            conn.execute(
                "INSERT INTO core_thread_outlines (thread_id, char_limit, revision, snapshot_seq, outline_json, updated_at) \
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6) \
                 ON CONFLICT(thread_id, char_limit) DO UPDATE SET \
                   revision = excluded.revision, \
                   snapshot_seq = excluded.snapshot_seq, \
                   outline_json = excluded.outline_json, \
                   updated_at = excluded.updated_at",
                params![tid, char_limit_i64, db_rev, db_seq, outline_str, now],
            )?;
            Ok(())
        });
    }

    Ok(json!({
        "needs_usage_hydration": false,
        "outline": outline,
    }))
}
