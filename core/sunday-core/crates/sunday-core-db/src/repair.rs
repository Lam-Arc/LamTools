//! Native Rust equivalents of snapshot repair, status derivation, and SHA-256 helpers.
//!
//! user:“加载/切换/多会话多 agent 同时读写”+(在 Rust 中直接完成会话状态推导与历史损坏修复，避免 Python 循环解析大对象)。

use serde_json::{Map, Value};
use std::collections::{HashMap, HashSet};

const INLINE_IMAGE_METADATA_KEY: &str = "image_data_url";
const REPAIR_STATUSES: &[&str] = &["running", "waiting", "interrupting", "paused"];
const LIVE_RUNTIME_STATUSES: &[&str] = &["running", "waiting", "interrupting"];
const ACTIVE_TURN_STATUSES: &[&str] = &["running", "waiting", "interrupting", "paused"];

pub fn effective_thread_status(snapshot: &Value) -> String {
    if let Some(core_status) = snapshot
        .get("core")
        .and_then(|c| c.get("status"))
        .and_then(|s| s.as_str())
    {
        if !core_status.is_empty() && core_status != "idle" {
            return core_status.to_string();
        }
    }
    snapshot
        .get("status")
        .and_then(|s| s.as_str())
        .filter(|s| !s.is_empty())
        .unwrap_or("idle")
        .to_string()
}

pub fn session_needs_repair(state: &Value, active_turn_id: &str) -> bool {
    if !active_turn_id.is_empty() {
        return true;
    }
    let core_status = state
        .get("core")
        .and_then(|c| c.get("status"))
        .and_then(|s| s.as_str())
        .unwrap_or("");
    let status = if !core_status.is_empty() && core_status != "idle" {
        core_status
    } else {
        state.get("status").and_then(|s| s.as_str()).unwrap_or("")
    };
    REPAIR_STATUSES.contains(&status)
}

pub fn projection_needs_repair(state: &Value, active_turn_id: Option<&str>) -> bool {
    match active_turn_id {
        None => true,
        Some(tid) if !tid.is_empty() => true,
        Some(_) => REPAIR_STATUSES.contains(&effective_thread_status(state).as_str()),
    }
}

fn no_active_turn(container: Option<&Value>) -> bool {
    let Some(obj) = container.and_then(|v| v.as_object()) else {
        return true;
    };
    !obj.values().any(|turn| {
        turn.get("status")
            .and_then(|s| s.as_str())
            .map(|s| LIVE_RUNTIME_STATUSES.contains(&s))
            .unwrap_or(false)
    })
}

pub fn prune_orphan_turns(state: &mut Value) {
    struct Evidence {
        statuses: HashSet<String>,
        kinds: HashSet<String>,
        items: usize,
    }

    let mut evidence: HashMap<String, Evidence> = HashMap::new();
    for turns_opt in [
        state.get("turns"),
        state.get("core").and_then(|c| c.get("turns")),
    ] {
        if let Some(obj) = turns_opt.and_then(|v| v.as_object()) {
            for (turn_id, turn) in obj {
                let Some(turn_obj) = turn.as_object() else {
                    continue;
                };
                let entry = evidence.entry(turn_id.clone()).or_insert_with(|| Evidence {
                    statuses: HashSet::new(),
                    kinds: HashSet::new(),
                    items: 0,
                });
                if let Some(st) = turn_obj.get("status").and_then(|s| s.as_str()) {
                    if !st.is_empty() {
                        entry.statuses.insert(st.to_string());
                    }
                }
                if let Some(k) = turn_obj.get("last_kind").and_then(|s| s.as_str()) {
                    if !k.is_empty() {
                        entry.kinds.insert(k.to_string());
                    }
                }
                if let Some(arr) = turn_obj.get("items").and_then(|i| i.as_array()) {
                    entry.items += arr.len();
                }
            }
        }
    }

    let to_drop: Vec<String> = evidence
        .into_iter()
        .filter_map(|(tid, ev)| {
            if ev.statuses.is_empty()
                || ev.statuses.iter().any(|s| !LIVE_RUNTIME_STATUSES.contains(&s.as_str()))
                || ev.items > 0
                || ev.kinds.len() != 1
                || !ev.kinds.contains("approval_response")
            {
                None
            } else {
                Some(tid)
            }
        })
        .collect();

    if !to_drop.is_empty() {
        if let Some(obj) = state.get_mut("turns").and_then(|v| v.as_object_mut()) {
            for tid in &to_drop {
                obj.remove(tid);
            }
        }
        if let Some(obj) = state
            .get_mut("core")
            .and_then(|c| c.get_mut("turns"))
            .and_then(|v| v.as_object_mut())
        {
            for tid in &to_drop {
                obj.remove(tid);
            }
        }
    }

    let no_outer = no_active_turn(state.get("turns"));
    let no_core = no_active_turn(state.get("core").and_then(|c| c.get("turns")));
    if no_outer && no_core {
        let mut latest_seq: i64 = -1;
        let mut latest_status = String::new();
        for container_opt in [
            state.get("turns"),
            state.get("core").and_then(|c| c.get("turns")),
        ] {
            if let Some(obj) = container_opt.and_then(|v| v.as_object()) {
                for turn in obj.values() {
                    let Some(t) = turn.as_object() else { continue };
                    let seq = t.get("last_seq").and_then(|v| v.as_i64()).unwrap_or(0);
                    if latest_seq < 0 || seq >= latest_seq {
                        latest_seq = seq;
                        latest_status = t
                            .get("status")
                            .and_then(|v| v.as_str())
                            .unwrap_or("")
                            .to_string();
                    }
                }
            }
        }
        let settled = match latest_status.as_str() {
            "completed" => Some("completed"),
            "cancelled" => Some("cancelled"),
            "failed" => Some("failed"),
            _ => None,
        };
        if let Some(settled_str) = settled {
            let cur = state.get("status").and_then(|s| s.as_str()).unwrap_or("");
            if LIVE_RUNTIME_STATUSES.contains(&cur) {
                if let Some(root) = state.as_object_mut() {
                    root.insert("status".into(), Value::String(settled_str.into()));
                }
                if let Some(core) = state.get_mut("core").and_then(|c| c.as_object_mut()) {
                    core.insert("status".into(), Value::String(settled_str.into()));
                }
            }
        }
    }
}

fn reconcile_terminal_requests(container: &mut Map<String, Value>) {
    let turns = container
        .get("turns")
        .and_then(|t| t.as_object())
        .cloned();
    let Some(turns_map) = turns else {
        return;
    };
    let Some(requests) = container.get_mut("requests").and_then(|r| r.as_object_mut()) else {
        return;
    };
    for req in requests.values_mut() {
        let Some(req_obj) = req.as_object_mut() else {
            continue;
        };
        let status = req_obj.get("status").and_then(|s| s.as_str()).unwrap_or("");
        if status != "open" && status != "pending" {
            continue;
        }
        let turn_id = req_obj.get("turn_id").and_then(|t| t.as_str()).unwrap_or("");
        if let Some(turn_status) = turns_map
            .get(turn_id)
            .and_then(|t| t.get("status"))
            .and_then(|s| s.as_str())
        {
            if matches!(turn_status, "completed" | "failed" | "cancelled") {
                req_obj.insert("status".into(), Value::String("resolved".into()));
            }
        }
    }
}

fn recompute_thread_status_map(container: &mut Map<String, Value>) {
    let mut best_status: Option<String> = None;
    let mut best_seq: i64 = -1;
    if let Some(turns) = container.get("turns").and_then(|t| t.as_object()) {
        for turn in turns.values() {
            let Some(t) = turn.as_object() else { continue };
            let status = t.get("status").and_then(|s| s.as_str()).unwrap_or("");
            if ACTIVE_TURN_STATUSES.contains(&status) {
                let seq = t
                    .get("last_seq")
                    .or_else(|| t.get("seq"))
                    .and_then(|v| v.as_i64())
                    .unwrap_or(0);
                if seq >= best_seq {
                    best_seq = seq;
                    best_status = Some(status.to_string());
                }
            }
        }
    }
    if let Some(active) = best_status {
        container.insert("status".into(), Value::String(active));
        return;
    }
    if let Some(requests) = container.get("requests").and_then(|r| r.as_object()) {
        let has_open = requests.values().any(|r| {
            matches!(
                r.get("status").and_then(|s| s.as_str()).unwrap_or(""),
                "open" | "pending"
            )
        });
        if has_open {
            container.insert("status".into(), Value::String("waiting".into()));
            return;
        }
    }
    let mut latest_status: Option<String> = None;
    let mut latest_seq: i64 = -1;
    if let Some(turns) = container.get("turns").and_then(|t| t.as_object()) {
        for turn in turns.values() {
            let Some(t) = turn.as_object() else { continue };
            let status = t.get("status").and_then(|s| s.as_str()).unwrap_or("");
            if status.is_empty() {
                continue;
            }
            let seq = t
                .get("last_seq")
                .or_else(|| t.get("seq"))
                .and_then(|v| v.as_i64())
                .unwrap_or(0);
            if seq >= latest_seq {
                latest_seq = seq;
                latest_status = Some(match status {
                    "error" => "failed".into(),
                    other => other.to_string(),
                });
            }
        }
    }
    if let Some(s) = latest_status {
        container.insert("status".into(), Value::String(s));
    } else if !container.contains_key("status") {
        container.insert("status".into(), Value::String("idle".into()));
    }
}

pub fn reconcile_status(state: &mut Value) {
    if let Some(core) = state.get_mut("core").and_then(|c| c.as_object_mut()) {
        reconcile_terminal_requests(core);
        recompute_thread_status_map(core);
    }
    let core_turns = state
        .get("core")
        .and_then(|c| c.get("turns"))
        .and_then(|t| t.as_object())
        .cloned();
    if let (Some(core_turns_map), Some(root)) = (core_turns, state.as_object_mut()) {
        let turns_val = root
            .entry("turns")
            .or_insert_with(|| Value::Object(Map::new()));
        if let Some(turns_map) = turns_val.as_object_mut() {
            for (turn_id, core_turn_val) in core_turns_map {
                let Some(core_turn) = core_turn_val.as_object() else {
                    continue;
                };
                let entry = turns_map.entry(turn_id.clone()).or_insert_with(|| {
                    let mut m = Map::new();
                    m.insert("turn_id".into(), Value::String(turn_id.clone()));
                    m.insert("items".into(), Value::Array(Vec::new()));
                    Value::Object(m)
                });
                if let Some(turn_obj) = entry.as_object_mut() {
                    let status = core_turn
                        .get("status")
                        .or_else(|| turn_obj.get("status"))
                        .and_then(|s| s.as_str())
                        .unwrap_or("running");
                    let last_seq = core_turn
                        .get("last_seq")
                        .or_else(|| turn_obj.get("last_seq"))
                        .and_then(|s| s.as_i64())
                        .unwrap_or(0);
                    turn_obj.insert("status".into(), Value::String(status.into()));
                    turn_obj.insert("last_seq".into(), Value::Number(last_seq.into()));
                    if let Some(run_id) = core_turn.get("run_id").and_then(|v| v.as_str()) {
                        if !run_id.is_empty() {
                            turn_obj.insert("run_id".into(), Value::String(run_id.into()));
                        }
                    }
                    if let Some(usage) = core_turn.get("usage").filter(|v| v.is_object()) {
                        turn_obj.insert("usage".into(), usage.clone());
                    }
                    if let Some(cm) = core_turn.get("context_metrics").filter(|v| v.is_object()) {
                        turn_obj.insert("context_metrics".into(), cm.clone());
                    }
                }
            }
        }
    }
    if let Some(root) = state.as_object_mut() {
        reconcile_terminal_requests(root);
        recompute_thread_status_map(root);
    }
}

pub fn strip_inline_image_copies(state: &mut Value) {
    if let Some(core) = state.get_mut("core").and_then(|c| c.as_object_mut()) {
        if let Some(registry) = core.get_mut("artifacts").and_then(|a| a.as_object_mut()) {
            for artifact in registry.values_mut() {
                if let Some(meta) = artifact.get_mut("metadata").and_then(|m| m.as_object_mut()) {
                    meta.remove(INLINE_IMAGE_METADATA_KEY);
                }
            }
        }
        if let Some(items) = core.get_mut("items").and_then(|i| i.as_object_mut()) {
            for item in items.values_mut() {
                if let Some(meta) = item
                    .get_mut("payload")
                    .and_then(|p| p.get_mut("metadata"))
                    .and_then(|m| m.as_object_mut())
                {
                    meta.remove(INLINE_IMAGE_METADATA_KEY);
                }
            }
        }
    }
}

pub fn sha256_hex(data: &[u8]) -> String {
    const K: [u32; 64] = [
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4,
        0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe,
        0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f,
        0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
        0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc,
        0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
        0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116,
        0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
        0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
        0xc67178f2,
    ];
    let mut h: [u32; 8] = [
        0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab,
        0x5be0cd19,
    ];
    let bit_len = (data.len() as u64) * 8;
    let mut msg = data.to_vec();
    msg.push(0x80);
    while (msg.len() % 64) != 56 {
        msg.push(0);
    }
    msg.extend_from_slice(&bit_len.to_be_bytes());
    for chunk in msg.chunks_exact(64) {
        let mut w = [0u32; 64];
        for i in 0..16 {
            w[i] = u32::from_be_bytes([
                chunk[i * 4],
                chunk[i * 4 + 1],
                chunk[i * 4 + 2],
                chunk[i * 4 + 3],
            ]);
        }
        for i in 16..64 {
            let s0 = w[i - 15].rotate_right(7) ^ w[i - 15].rotate_right(18) ^ (w[i - 15] >> 3);
            let s1 = w[i - 2].rotate_right(17) ^ w[i - 2].rotate_right(19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16]
                .wrapping_add(s0)
                .wrapping_add(w[i - 7])
                .wrapping_add(s1);
        }
        let [mut a, mut b, mut c, mut d, mut e, mut f, mut g, mut hh] = h;
        for i in 0..64 {
            let s1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
            let ch = (e & f) ^ ((!e) & g);
            let temp1 = hh
                .wrapping_add(s1)
                .wrapping_add(ch)
                .wrapping_add(K[i])
                .wrapping_add(w[i]);
            let s0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
            let maj = (a & b) ^ (a & c) ^ (b & c);
            let temp2 = s0.wrapping_add(maj);
            hh = g;
            g = f;
            f = e;
            e = d.wrapping_add(temp1);
            d = c;
            c = b;
            b = a;
            a = temp1.wrapping_add(temp2);
        }
        h[0] = h[0].wrapping_add(a);
        h[1] = h[1].wrapping_add(b);
        h[2] = h[2].wrapping_add(c);
        h[3] = h[3].wrapping_add(d);
        h[4] = h[4].wrapping_add(e);
        h[5] = h[5].wrapping_add(f);
        h[6] = h[6].wrapping_add(g);
        h[7] = h[7].wrapping_add(hh);
    }
    let mut out = String::with_capacity(64);
    for word in h {
        out.push_str(&format!("{word:08x}"));
    }
    out
}
