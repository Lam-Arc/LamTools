//! The platform-neutral V2 workflow document boundary.
//!
//! This module deliberately stops at the data boundary.  It validates and
//! canonicalizes an editable workflow document, projects it to the
//! canvas-free execution prompt and compact semantic graph, and translates the
//! public ComfyUI editor shape.  Scheduling, persistence and node execution
//! stay in the host/runtime layers.

use serde_json::{json, Map, Value};
use std::collections::{BTreeSet, HashMap, HashSet};
use std::fmt;
use uuid::Uuid;

pub const DOCUMENT_FORMAT: &str = "lamtools.workflow";
pub const DOCUMENT_VERSION: i64 = 2;
pub const PROMPT_FORMAT: &str = "lamtools.execution-prompt";
pub const PROMPT_VERSION: i64 = 1;
pub const SEMANTIC_FORMAT: &str = "lamtools.semantic-graph";
pub const SEMANTIC_VERSION: i64 = 1;

const UUID5_NAMESPACE_URL: [u8; 16] = [
    0x6b, 0xa7, 0xb8, 0x11, 0x9d, 0xad, 0x11, 0xd1, 0x80, 0xb4, 0x00, 0xc0, 0x4f, 0xd4, 0x30, 0xc8,
];

/// An invalid document or interchange payload.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkflowDocumentError(pub String);

impl WorkflowDocumentError {
    pub fn new(message: impl Into<String>) -> Self {
        Self(message.into())
    }

    pub fn message(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for WorkflowDocumentError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.0)
    }
}

impl std::error::Error for WorkflowDocumentError {}

impl From<serde_json::Error> for WorkflowDocumentError {
    fn from(error: serde_json::Error) -> Self {
        Self::new(error.to_string())
    }
}

pub type WorkflowDocumentResult<T> = Result<T, WorkflowDocumentError>;

fn invalid(message: impl Into<String>) -> WorkflowDocumentError {
    WorkflowDocumentError::new(message)
}

fn object<'a>(value: &'a Value, path: &str) -> WorkflowDocumentResult<&'a Map<String, Value>> {
    value
        .as_object()
        .ok_or_else(|| invalid(format!("{path} must be an object")))
}

fn array<'a>(value: &'a Value, path: &str) -> WorkflowDocumentResult<&'a Vec<Value>> {
    value
        .as_array()
        .ok_or_else(|| invalid(format!("{path} must be an array")))
}

fn string_field(value: Option<&Value>, default: &str) -> String {
    match value {
        Some(Value::String(value)) => value.clone(),
        Some(Value::Number(value)) => value.to_string(),
        Some(Value::Bool(value)) => value.to_string(),
        _ => default.to_owned(),
    }
}

fn non_empty_string(value: Option<&Value>, default: &str) -> String {
    let candidate = string_field(value, default).trim().to_owned();
    if candidate.is_empty() {
        default.to_owned()
    } else {
        candidate
    }
}

fn bool_field(value: Option<&Value>, default: bool) -> bool {
    value.and_then(Value::as_bool).unwrap_or(default)
}

fn integer_field(value: Option<&Value>, default: i64) -> i64 {
    value
        .and_then(|item| {
            item.as_i64()
                .or_else(|| item.as_u64().and_then(|number| i64::try_from(number).ok()))
        })
        .unwrap_or(default)
}

fn positive_version(value: Option<&Value>) -> WorkflowDocumentResult<i64> {
    match value {
        None | Some(Value::Null) => Ok(1),
        Some(Value::Number(number)) => number
            .as_i64()
            .filter(|version| *version >= 1)
            .ok_or_else(|| invalid("node type.version must be a positive integer")),
        Some(Value::String(text)) if text.trim().parse::<i64>().ok().is_some_and(|v| v >= 1) => {
            Ok(text.trim().parse::<i64>().expect("checked above"))
        }
        _ => Err(invalid("node type.version must be a positive integer")),
    }
}

fn numeric_field(value: Option<&Value>, default: f64) -> f64 {
    value
        .and_then(Value::as_f64)
        .filter(|number| number.is_finite())
        .unwrap_or(default)
}

fn clone_object(value: Option<&Value>) -> Map<String, Value> {
    value
        .and_then(Value::as_object)
        .cloned()
        .unwrap_or_default()
}

fn sensitive_key(key: &str) -> bool {
    matches!(
        key.to_ascii_lowercase().as_str(),
        "api_key"
            | "apikey"
            | "api-key"
            | "secret"
            | "secrets"
            | "password"
            | "passwd"
            | "auth_token"
            | "access_token"
            | "refresh_token"
            | "client_secret"
            | "private_key"
            | "secret_key"
            | "credential_data"
            | "credential_secret"
    )
}

/// Reject obvious secret material before it can be persisted in a document.
/// Credential references are represented by a non-secret object under a
/// different key (for example `{ "credential": { "id": "prod" } }`).
fn reject_secrets(value: &Value, path: &str) -> WorkflowDocumentResult<()> {
    match value {
        Value::Object(map) => {
            for (key, child) in map {
                if sensitive_key(key) && !child.is_null() {
                    return Err(invalid(format!(
                        "secret material is not allowed at {path}.{key}"
                    )));
                }
                reject_secrets(child, &format!("{path}.{key}"))?;
            }
        }
        Value::Array(items) => {
            for (index, child) in items.iter().enumerate() {
                reject_secrets(child, &format!("{path}[{index}]"))?;
            }
        }
        _ => {}
    }
    Ok(())
}

/// Stable id compatible with Python's `uuid.uuid5(NAMESPACE_URL, seed)`
/// prefix convention used by the Workflow backend.
pub fn stable_id(prefix: &str, parts: &[&str]) -> String {
    let seed = parts.join("\u{1f}");
    let mut payload = Vec::with_capacity(UUID5_NAMESPACE_URL.len() + seed.len());
    payload.extend_from_slice(&UUID5_NAMESPACE_URL);
    payload.extend_from_slice(seed.as_bytes());
    let mut digest = sha1_digest(&payload);
    digest[6] = (digest[6] & 0x0f) | 0x50;
    digest[8] = (digest[8] & 0x3f) | 0x80;
    let short = digest[..8]
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>();
    format!("{prefix}_{short}")
}

// Small dependency-free SHA-1 implementation for UUID5-compatible stable
// ids.  The input is only an id seed, never user data that needs encryption.
fn sha1_digest(data: &[u8]) -> [u8; 20] {
    let mut padded = data.to_vec();
    padded.push(0x80);
    while (padded.len() + 8) % 64 != 0 {
        padded.push(0);
    }
    padded.extend_from_slice(&((data.len() as u64) * 8).to_be_bytes());

    let mut h0 = 0x6745_2301_u32;
    let mut h1 = 0xefcd_ab89_u32;
    let mut h2 = 0x98ba_dcfe_u32;
    let mut h3 = 0x1032_5476_u32;
    let mut h4 = 0xc3d2_e1f0_u32;

    for chunk in padded.chunks_exact(64) {
        let mut words = [0_u32; 80];
        for (index, word) in words[..16].iter_mut().enumerate() {
            let offset = index * 4;
            *word = u32::from_be_bytes([
                chunk[offset],
                chunk[offset + 1],
                chunk[offset + 2],
                chunk[offset + 3],
            ]);
        }
        for index in 16..80 {
            words[index] =
                (words[index - 3] ^ words[index - 8] ^ words[index - 14] ^ words[index - 16])
                    .rotate_left(1);
        }

        let (mut a, mut b, mut c, mut d, mut e) = (h0, h1, h2, h3, h4);
        for (index, word) in words.iter().enumerate() {
            let (function, constant) = match index {
                0..=19 => ((b & c) | ((!b) & d), 0x5a82_7999),
                20..=39 => (b ^ c ^ d, 0x6ed9_eba1),
                40..=59 => ((b & c) | (b & d) | (c & d), 0x8f1b_bcdc),
                _ => (b ^ c ^ d, 0xca62_c1d6),
            };
            let next = a
                .rotate_left(5)
                .wrapping_add(function)
                .wrapping_add(e)
                .wrapping_add(constant)
                .wrapping_add(*word);
            e = d;
            d = c;
            c = b.rotate_left(30);
            b = a;
            a = next;
        }
        h0 = h0.wrapping_add(a);
        h1 = h1.wrapping_add(b);
        h2 = h2.wrapping_add(c);
        h3 = h3.wrapping_add(d);
        h4 = h4.wrapping_add(e);
    }

    let mut result = [0_u8; 20];
    for (index, word) in [h0, h1, h2, h3, h4].into_iter().enumerate() {
        result[index * 4..index * 4 + 4].copy_from_slice(&word.to_be_bytes());
    }
    result
}

pub fn is_v2_document(value: &Value) -> bool {
    value.as_object().is_some_and(|object| {
        object.get("format").and_then(Value::as_str) == Some(DOCUMENT_FORMAT)
            && object.get("version").and_then(Value::as_i64) == Some(DOCUMENT_VERSION)
    })
}

fn normalized_type(value: &str) -> String {
    let lower = value.trim().to_ascii_lowercase();
    match lower.as_str() {
        "text" | "str" => "string".into(),
        "int" | "integer" | "float" => "number".into(),
        "bool" => "boolean".into(),
        "dict" => "object".into(),
        "list" => "array".into(),
        "any" | "string" | "number" | "boolean" | "object" | "array" => lower,
        _ => "any".into(),
    }
}

fn types_compatible(source: &str, target: &str) -> bool {
    let source = normalized_type(source);
    let target = normalized_type(target);
    source == "any"
        || target == "any"
        || source == target
        || (matches!(source.as_str(), "number" | "boolean") && target == "string")
}

fn normalize_trigger_list(value: Option<&Value>) -> WorkflowDocumentResult<Vec<Value>> {
    let Some(value) = value else {
        return Ok(Vec::new());
    };
    let items = array(value, "triggers")?;
    let allowed: BTreeSet<&str> = ["manual", "once", "interval", "calendar", "event"]
        .into_iter()
        .collect();
    let mut seen = HashSet::new();
    let mut result = Vec::with_capacity(items.len());
    for (index, raw) in items.iter().enumerate() {
        let source = object(raw, &format!("trigger {index}"))?;
        let kind = non_empty_string(source.get("type").or_else(|| source.get("kind")), "")
            .to_ascii_lowercase();
        if !allowed.contains(kind.as_str()) {
            return Err(invalid(format!(
                "trigger {index} has unsupported type {kind:?}"
            )));
        }
        let id = non_empty_string(
            source.get("id"),
            &stable_id("trigger", &[&index.to_string(), &kind]),
        );
        if !seen.insert(id.clone()) {
            return Err(invalid(format!("missing or duplicate trigger id: {id:?}")));
        }
        let mut item = source.clone();
        item.remove("kind");
        item.insert("id".into(), Value::String(id));
        item.insert("type".into(), Value::String(kind.clone()));
        item.insert(
            "enabled".into(),
            Value::Bool(bool_field(source.get("enabled"), true)),
        );
        match kind.as_str() {
            "once" => {
                let at = source
                    .get("at")
                    .or_else(|| source.get("run_at"))
                    .filter(|item| !item.is_null());
                if at.is_none()
                    || at.is_some_and(|item| {
                        item.as_str().is_some_and(str::is_empty) || item.is_boolean()
                    })
                {
                    return Err(invalid("once trigger requires a non-empty at/run_at value"));
                }
                item.insert("at".into(), at.cloned().expect("checked above"));
                item.remove("run_at");
            }
            "interval" => {
                let seconds = source
                    .get("every_seconds")
                    .or_else(|| source.get("interval_seconds"))
                    .or_else(|| source.get("seconds"))
                    .or_else(|| source.get("every"));
                let valid = seconds
                    .and_then(Value::as_f64)
                    .is_some_and(|number| number.is_finite() && number > 0.0);
                if !valid {
                    return Err(invalid("interval trigger requires positive every_seconds"));
                }
                item.insert(
                    "every_seconds".into(),
                    seconds.cloned().expect("checked above"),
                );
                for key in ["interval_seconds", "seconds", "every"] {
                    item.remove(key);
                }
            }
            "calendar" => {
                let frequency =
                    non_empty_string(source.get("frequency"), "daily").to_ascii_lowercase();
                if frequency != "daily" && frequency != "monthly" {
                    return Err(invalid("calendar frequency must be daily or monthly"));
                }
                let time = non_empty_string(source.get("time"), "");
                if time.is_empty() {
                    return Err(invalid("calendar trigger requires time"));
                }
                item.insert("frequency".into(), Value::String(frequency.clone()));
                item.insert("time".into(), Value::String(time));
                item.insert(
                    "timezone".into(),
                    Value::String(non_empty_string(source.get("timezone"), "Asia/Shanghai")),
                );
                if frequency == "monthly" {
                    let day = source
                        .get("day")
                        .and_then(Value::as_i64)
                        .filter(|day| (1..=31).contains(day));
                    let Some(day) = day else {
                        return Err(invalid("monthly calendar day must be between 1 and 31"));
                    };
                    item.insert("day".into(), json!(day));
                } else {
                    item.remove("day");
                }
                item.remove("rrule");
                item.remove("schedule");
            }
            "event" => {
                let event = source
                    .get("event_type")
                    .or_else(|| source.get("event"))
                    .or_else(|| source.get("event_name"))
                    .and_then(Value::as_str)
                    .map(str::trim)
                    .filter(|value| !value.is_empty());
                let Some(event) = event else {
                    return Err(invalid("event trigger requires a non-empty event_type"));
                };
                item.insert("event_type".into(), Value::String(event.into()));
                item.remove("event");
                item.remove("event_name");
            }
            _ => {}
        }
        result.push(Value::Object(item));
    }
    Ok(result)
}

fn canonicalize_flow_control(
    raw: &Map<String, Value>,
) -> WorkflowDocumentResult<Map<String, Value>> {
    let allowed = [
        "concurrency",
        "rate_limit",
        "throttle",
        "debounce",
        "priority",
    ];
    if let Some(unknown) = raw.keys().find(|key| !allowed.contains(&key.as_str())) {
        return Err(invalid(format!(
            "unknown flow-control policy field: {unknown}"
        )));
    }
    let mut result = Map::new();
    if let Some(value) = raw.get("concurrency") {
        let source = object(value, "policies.concurrency")?;
        let key = non_empty_string(source.get("key"), "");
        let max = source
            .get("max")
            .and_then(Value::as_f64)
            .filter(|number| number.is_finite() && *number >= 1.0 && number.fract() == 0.0);
        let Some(max) = max else {
            return Err(invalid(
                "policies.concurrency.max must be a positive integer",
            ));
        };
        if key.is_empty() {
            return Err(invalid("policies.concurrency.key is required"));
        }
        result.insert("concurrency".into(), json!({"key": key, "max": max as i64}));
    }
    if let Some(value) = raw.get("rate_limit") {
        let source = object(value, "policies.rate_limit")?;
        let count = source
            .get("count")
            .and_then(Value::as_f64)
            .filter(|number| number.is_finite() && *number >= 1.0 && number.fract() == 0.0);
        let window = source
            .get("window_seconds")
            .and_then(Value::as_f64)
            .filter(|number| number.is_finite() && *number > 0.0);
        let (Some(count), Some(window)) = (count, window) else {
            return Err(invalid(
                "policies.rate_limit requires positive count/window_seconds",
            ));
        };
        result.insert(
            "rate_limit".into(),
            json!({"count": count as i64, "window_seconds": window}),
        );
    }
    if let Some(value) = raw.get("throttle") {
        let source = object(value, "policies.throttle")?;
        let interval = source
            .get("min_interval_seconds")
            .or_else(|| source.get("minIntervalSeconds"))
            .and_then(Value::as_f64)
            .filter(|number| number.is_finite() && *number > 0.0);
        let Some(interval) = interval else {
            return Err(invalid(
                "policies.throttle requires positive min_interval_seconds",
            ));
        };
        result.insert("throttle".into(), json!({"min_interval_seconds": interval}));
    }
    if let Some(value) = raw.get("debounce") {
        let source = object(value, "policies.debounce")?;
        let window = source
            .get("window_seconds")
            .and_then(Value::as_f64)
            .filter(|number| number.is_finite() && *number > 0.0);
        let Some(window) = window else {
            return Err(invalid(
                "policies.debounce requires positive window_seconds",
            ));
        };
        let mode = match non_empty_string(source.get("mode"), "trailing").as_str() {
            "last" | "trailing" => "trailing",
            "first" | "leading" => "leading",
            _ => {
                return Err(invalid(
                    "policies.debounce.mode must be leading or trailing",
                ))
            }
        };
        result.insert(
            "debounce".into(),
            json!({"window_seconds": window, "mode": mode}),
        );
    }
    if let Some(priority) = raw.get("priority") {
        let priority = priority
            .as_i64()
            .or_else(|| {
                priority
                    .as_f64()
                    .filter(|number| number.fract() == 0.0)
                    .map(|v| v as i64)
            })
            .ok_or_else(|| invalid("policies.priority must be an integer"))?;
        result.insert("priority".into(), json!(priority));
    }
    Ok(result)
}

fn normalize_policies(value: Option<&Value>) -> WorkflowDocumentResult<Value> {
    let Some(value) = value else {
        return Ok(json!({}));
    };
    let source = object(value, "policies")?;
    let mut item = source.clone();
    for key in ["timeout_seconds", "max_concurrency", "retry_attempts"] {
        if let Some(raw) = item.get(key) {
            let number = raw
                .as_f64()
                .filter(|number| number.is_finite() && *number >= 0.0);
            if number.is_none() {
                return Err(invalid(format!(
                    "policies.{key} must be a non-negative number"
                )));
            }
            if key != "timeout_seconds"
                && number.is_some_and(|value| value.fract() != 0.0 || value < 1.0)
            {
                return Err(invalid(format!(
                    "policies.{key} must be a positive integer"
                )));
            }
        }
    }
    if let Some(permissions) = item.get("permissions") {
        let permissions = array(permissions, "policies.permissions")?;
        if permissions.iter().any(|permission| {
            permission
                .as_str()
                .is_none_or(|value| value.trim().is_empty())
        }) {
            return Err(invalid("policies.permissions must be an array of names"));
        }
        item.insert(
            "permissions".into(),
            Value::Array(
                permissions
                    .iter()
                    .map(|permission| Value::String(permission.as_str().unwrap().trim().into()))
                    .collect(),
            ),
        );
    }
    for (key, expected) in [
        ("on_error", "string or object"),
        ("retry", "object"),
        ("cache", "string"),
        ("resource_class", "string"),
    ] {
        if let Some(value) = item.get(key) {
            let valid = match expected {
                "string or object" => value.is_string() || value.is_object(),
                "object" => value.is_object(),
                "string" => value.is_string(),
                _ => true,
            };
            if !valid {
                return Err(invalid(format!("policies.{key} must be a {expected}")));
            }
        }
    }

    let aliases = [
        ("flow_control", "flow_control"),
        ("flowControl", "flow_control"),
        ("rateLimit", "rate_limit"),
        ("rate-limit", "rate_limit"),
        ("rateLimitPolicy", "rate_limit"),
        ("minInterval", "throttle"),
        ("minIntervalSeconds", "throttle"),
        ("debouncePolicy", "debounce"),
    ];
    let flow_keys = [
        "concurrency",
        "rate_limit",
        "throttle",
        "debounce",
        "priority",
    ];
    let mut flow = Map::new();
    for key in flow_keys {
        if let Some(value) = item.remove(key) {
            flow.insert(key.into(), value);
        }
    }
    for (alias, canonical) in aliases {
        if let Some(value) = item.remove(alias) {
            if let Some(previous) = flow.get(canonical) {
                if previous != &value {
                    return Err(invalid(format!(
                        "policies contains conflicting aliases for {canonical}"
                    )));
                }
            }
            flow.insert(canonical.into(), value);
        }
    }
    if let Some(wrapper) = flow.remove("flow_control") {
        if !flow.is_empty() {
            return Err(invalid(
                "flow_control wrapper cannot be combined with sibling fields",
            ));
        }
        let wrapped = object(&wrapper, "policies.flow_control")?.clone();
        item.extend(canonicalize_flow_control(&wrapped)?);
    } else if !flow.is_empty() {
        item.extend(canonicalize_flow_control(&flow)?);
    }
    Ok(Value::Object(item))
}

fn normalize_interface(
    value: Option<&Value>,
    ports: &HashMap<(String, String), (String, String)>,
) -> WorkflowDocumentResult<Value> {
    let source = value.and_then(Value::as_object);
    let mut inputs = Vec::new();
    let mut input_ids = HashSet::new();
    if let Some(raw_inputs) = source.and_then(|item| item.get("inputs")) {
        for raw in array(raw_inputs, "interface.inputs")? {
            let source = match raw.as_object() {
                Some(source) => source,
                None => continue,
            };
            let id = non_empty_string(source.get("id"), "");
            if id.is_empty() || !input_ids.insert(id.clone()) {
                return Err(invalid("workflow interface input ids must be unique"));
            }
            let mut item = Map::new();
            item.insert("id".into(), Value::String(id.clone()));
            item.insert(
                "name".into(),
                Value::String(non_empty_string(source.get("name"), &id)),
            );
            item.insert(
                "data_type".into(),
                Value::String(non_empty_string(source.get("data_type"), "any")),
            );
            item.insert(
                "description".into(),
                Value::String(string_field(source.get("description"), "")),
            );
            item.insert(
                "required".into(),
                Value::Bool(bool_field(source.get("required"), true)),
            );
            if let Some(default) = source.get("default") {
                item.insert("default".into(), default.clone());
            }
            if let Some(target) = source.get("target") {
                let target = object(target, "interface input target")?;
                let key = (
                    string_field(target.get("node_id"), ""),
                    string_field(target.get("port_id"), ""),
                );
                if !ports
                    .get(&key)
                    .is_some_and(|(_, direction)| direction == "in")
                {
                    return Err(invalid(format!(
                        "interface input {} has invalid target",
                        item["id"]
                    )));
                }
                item.insert("target".into(), json!({"node_id": key.0, "port_id": key.1}));
            }
            inputs.push(Value::Object(item));
        }
    }
    let mut outputs = Vec::new();
    let mut output_ids = HashSet::new();
    if let Some(raw_outputs) = source.and_then(|item| item.get("outputs")) {
        for raw in array(raw_outputs, "interface.outputs")? {
            let Some(source) = raw.as_object() else {
                continue;
            };
            let id = non_empty_string(source.get("id"), "");
            let raw_source = source
                .get("source")
                .ok_or_else(|| invalid("workflow interface output id/source is invalid"))?;
            let raw_source = object(raw_source, "interface output source")?;
            let key = (
                string_field(raw_source.get("node_id"), ""),
                string_field(raw_source.get("port_id"), ""),
            );
            if id.is_empty()
                || !output_ids.insert(id.clone())
                || !ports.get(&key).is_some_and(|(data_type, direction)| {
                    direction == "out" && !data_type.is_empty()
                })
            {
                return Err(invalid("workflow interface output id/source is invalid"));
            }
            outputs.push(json!({
                "id": id,
                "name": non_empty_string(source.get("name"), &id),
                "data_type": non_empty_string(
                    source.get("data_type"),
                    &ports.get(&key).map(|item| item.0.clone()).unwrap_or_else(|| "any".into()),
                ),
                "description": string_field(source.get("description"), ""),
                "source": {"node_id": key.0, "port_id": key.1},
            }));
        }
    }
    Ok(json!({"inputs": inputs, "outputs": outputs}))
}

fn parent_id_from_view(view: Option<&Value>) -> Option<String> {
    let source = view?.as_object()?;
    let value = source.get("parent_id").or_else(|| source.get("parentId"))?;
    let id = value.as_str()?.trim();
    (!id.is_empty()).then(|| id.to_owned())
}

fn normalize_node_view(value: &Value) -> Value {
    let mut view = value.as_object().cloned().unwrap_or_default();
    let parent = parent_id_from_view(Some(value));
    view.remove("parentId");
    match parent {
        Some(parent) => {
            view.insert("parent_id".into(), Value::String(parent));
        }
        None => {
            view.remove("parent_id");
        }
    }
    Value::Object(view)
}

fn normalize_canvas(value: Option<&Value>, node_ids: &HashSet<String>) -> Value {
    let source = value.and_then(Value::as_object);
    let viewport = source
        .and_then(|item| item.get("viewport"))
        .and_then(Value::as_object);
    let mut node_views = Map::new();
    if let Some(raw_views) = source
        .and_then(|item| item.get("node_views"))
        .and_then(Value::as_object)
    {
        for (node_id, view) in raw_views {
            if node_ids.contains(node_id) && view.is_object() {
                node_views.insert(node_id.clone(), normalize_node_view(view));
            }
        }
    }
    let mut result = Map::new();
    result.insert(
        "viewport".into(),
        json!({
            "x": numeric_field(viewport.and_then(|item| item.get("x")), 0.0),
            "y": numeric_field(viewport.and_then(|item| item.get("y")), 0.0),
            "zoom": numeric_field(viewport.and_then(|item| item.get("zoom")), 1.0),
        }),
    );
    result.insert("node_views".into(), Value::Object(node_views));
    for key in ["groups", "reroutes", "annotations"] {
        result.insert(
            key.into(),
            source
                .and_then(|item| item.get(key))
                .filter(|value| value.is_array())
                .cloned()
                .unwrap_or_else(|| Value::Array(Vec::new())),
        );
    }
    if let Some(comfyui) = source
        .and_then(|item| item.get("comfyui"))
        .filter(|value| value.is_object())
    {
        result.insert("comfyui".into(), comfyui.clone());
    }
    Value::Object(result)
}

/// Validate and normalize a canonical V2 document.
pub fn canonicalize_document(value: &Value) -> WorkflowDocumentResult<Value> {
    if !is_v2_document(value) {
        return Err(invalid(format!(
            "expected {DOCUMENT_FORMAT:?} version {DOCUMENT_VERSION}"
        )));
    }
    reject_secrets(value, "document")?;
    let root = object(value, "document")?;
    let resource = object(
        root.get("resource")
            .ok_or_else(|| invalid("resource.name is required"))?,
        "resource",
    )?;
    let name = non_empty_string(resource.get("name"), "");
    if name.is_empty() {
        return Err(invalid("resource.name is required"));
    }
    let graph = object(
        root.get("graph")
            .ok_or_else(|| invalid("graph must be an object"))?,
        "graph",
    )?;
    let empty_nodes = Value::Array(Vec::new());
    let empty_links = Value::Array(Vec::new());
    let nodes = array(graph.get("nodes").unwrap_or(&empty_nodes), "graph.nodes")?;
    let links = array(graph.get("links").unwrap_or(&empty_links), "graph.links")?;

    let mut normalized_nodes = Vec::new();
    let mut node_ids = HashSet::new();
    let mut port_index: HashMap<(String, String), (String, String)> = HashMap::new();
    for raw in nodes {
        let raw = object(raw, "graph node")?;
        let node_id = non_empty_string(raw.get("id"), "");
        if node_id.is_empty() || !node_ids.insert(node_id.clone()) {
            return Err(invalid(format!(
                "missing or duplicate node id: {node_id:?}"
            )));
        }
        let type_ref = object(
            raw.get("type")
                .ok_or_else(|| invalid(format!("node {node_id:?} requires type.id")))?,
            &format!("node {node_id}.type"),
        )?;
        let type_id = non_empty_string(type_ref.get("id"), "");
        if type_id.is_empty() {
            return Err(invalid(format!("node {node_id:?} requires type.id")));
        }
        let type_version = positive_version(type_ref.get("version"))?;
        let empty_ports = Value::Array(Vec::new());
        let raw_ports = raw.get("ports").unwrap_or(&empty_ports);
        let raw_ports = array(raw_ports, &format!("node {node_id}.ports"))?;
        let mut port_ids = HashSet::new();
        let mut ports = Vec::new();
        for raw_port in raw_ports {
            let raw_port = object(raw_port, &format!("node {node_id} port"))?;
            let port_id = non_empty_string(raw_port.get("id"), "");
            let direction = string_field(raw_port.get("direction"), "");
            if port_id.is_empty() || !port_ids.insert(port_id.clone()) {
                return Err(invalid(format!(
                    "node {node_id:?} has a missing/duplicate port id"
                )));
            }
            if direction != "in" && direction != "out" {
                return Err(invalid(format!(
                    "port {node_id}.{port_id} has invalid direction"
                )));
            }
            let data_type = non_empty_string(raw_port.get("data_type"), "any");
            port_index.insert(
                (node_id.clone(), port_id.clone()),
                (data_type.clone(), direction.clone()),
            );
            let mut port = Map::new();
            port.insert("id".into(), Value::String(port_id.clone()));
            port.insert(
                "name".into(),
                Value::String(non_empty_string(raw_port.get("name"), &port_id)),
            );
            port.insert("direction".into(), Value::String(direction));
            port.insert("data_type".into(), Value::String(data_type));
            port.insert(
                "description".into(),
                Value::String(string_field(raw_port.get("description"), "")),
            );
            port.insert(
                "required".into(),
                Value::Bool(bool_field(raw_port.get("required"), false)),
            );
            port.insert(
                "lazy".into(),
                Value::Bool(bool_field(raw_port.get("lazy"), false)),
            );
            if let Some(default) = raw_port.get("default") {
                port.insert("default".into(), default.clone());
            }
            ports.push(Value::Object(port));
        }
        let execution = clone_object(raw.get("execution").filter(|value| value.is_object()));
        let mut normalized_execution = Map::new();
        normalized_execution.insert(
            "enabled".into(),
            Value::Bool(bool_field(execution.get("enabled"), true)),
        );
        normalized_execution.insert(
            "schema_only".into(),
            Value::Bool(bool_field(execution.get("schema_only"), false)),
        );
        normalized_execution.insert(
            "cache".into(),
            Value::String(non_empty_string(execution.get("cache"), "auto")),
        );
        normalized_execution.insert(
            "on_error".into(),
            execution
                .get("on_error")
                .filter(|value| value.is_object())
                .cloned()
                .unwrap_or_else(|| json!({"strategy": "abort"})),
        );
        normalized_execution.insert(
            "permissions".into(),
            Value::Array(
                execution
                    .get("permissions")
                    .and_then(Value::as_array)
                    .map(|items| {
                        items
                            .iter()
                            .map(|item| Value::String(string_field(Some(item), "")))
                            .collect()
                    })
                    .unwrap_or_default(),
            ),
        );
        normalized_nodes.push(json!({
            "id": node_id,
            "type": {"id": type_id, "version": type_version},
            "title": string_field(raw.get("title"), ""),
            "ports": ports,
            "params": raw.get("params").filter(|value| value.is_object()).cloned().unwrap_or_else(|| json!({})),
            "execution": normalized_execution,
        }));
    }

    let mut normalized_links = Vec::new();
    let mut link_ids = HashSet::new();
    let mut routes = HashSet::new();
    for raw in links {
        let raw = object(raw, "graph link")?;
        let id = non_empty_string(raw.get("id"), "");
        if id.is_empty() || !link_ids.insert(id.clone()) {
            return Err(invalid(format!("missing or duplicate link id: {id:?}")));
        }
        let source = object(
            raw.get("source")
                .ok_or_else(|| invalid(format!("link {id:?} endpoints must be objects")))?,
            &format!("link {id}.source"),
        )?;
        let target = object(
            raw.get("target")
                .ok_or_else(|| invalid(format!("link {id:?} endpoints must be objects")))?,
            &format!("link {id}.target"),
        )?;
        let source_key = (
            string_field(source.get("node_id"), ""),
            string_field(source.get("port_id"), ""),
        );
        let target_key = (
            string_field(target.get("node_id"), ""),
            string_field(target.get("port_id"), ""),
        );
        let Some((source_type, source_direction)) = port_index.get(&source_key) else {
            return Err(invalid(format!(
                "link {id:?} references an unknown endpoint"
            )));
        };
        let Some((target_type, target_direction)) = port_index.get(&target_key) else {
            return Err(invalid(format!(
                "link {id:?} references an unknown endpoint"
            )));
        };
        if source_direction != "out" || target_direction != "in" {
            return Err(invalid(format!("link {id:?} must connect output to input")));
        }
        if !types_compatible(source_type, target_type) {
            return Err(invalid(format!(
                "link {id:?} has incompatible types: {source_type} -> {target_type}"
            )));
        }
        let route = (
            source_key.0.clone(),
            source_key.1.clone(),
            target_key.0.clone(),
            target_key.1.clone(),
        );
        if !routes.insert(route) {
            return Err(invalid(format!("duplicate link route for {id:?}")));
        }
        let mut item = Map::new();
        item.insert("id".into(), Value::String(id));
        item.insert(
            "source".into(),
            json!({"node_id": source_key.0, "port_id": source_key.1}),
        );
        item.insert(
            "target".into(),
            json!({"node_id": target_key.0, "port_id": target_key.1}),
        );
        for key in ["transform", "condition"] {
            if let Some(expression) = raw.get(key).filter(|value| !value.is_null()) {
                if !expression.is_string() && !expression.is_object() {
                    return Err(invalid(format!(
                        "link {} {key} must be a string or expression AST",
                        item["id"]
                    )));
                }
                if expression.as_str().is_some_and(str::is_empty) {
                    continue;
                }
                item.insert(key.into(), expression.clone());
            }
        }
        normalized_links.push(Value::Object(item));
    }

    let resource_id = non_empty_string(resource.get("id"), &Uuid::new_v4().simple().to_string());
    let revision = integer_field(resource.get("revision"), 0).max(0);
    let mut result = Map::new();
    result.insert("format".into(), Value::String(DOCUMENT_FORMAT.into()));
    result.insert("version".into(), json!(DOCUMENT_VERSION));
    result.insert(
        "resource".into(),
        json!({
            "id": resource_id,
            "name": name,
            "description": string_field(resource.get("description"), ""),
            "work_root": string_field(resource.get("work_root"), ""),
            "revision": revision,
            "created_at": non_empty_string(resource.get("created_at"), &now_string()),
            "updated_at": non_empty_string(resource.get("updated_at"), &now_string()),
        }),
    );
    result.insert(
        "graph".into(),
        json!({"nodes": normalized_nodes, "links": normalized_links}),
    );
    result.insert(
        "interface".into(),
        normalize_interface(root.get("interface"), &port_index)?,
    );
    let exposure = root.get("exposure").and_then(Value::as_object);
    result.insert(
        "exposure".into(),
        json!({
            "enabled": bool_field(exposure.and_then(|item| item.get("enabled")), false),
            "tool_name": string_field(exposure.and_then(|item| item.get("tool_name")), ""),
        }),
    );
    result.insert(
        "canvas".into(),
        normalize_canvas(root.get("canvas"), &node_ids),
    );
    result.insert(
        "triggers".into(),
        Value::Array(normalize_trigger_list(root.get("triggers"))?),
    );
    result.insert("policies".into(), normalize_policies(root.get("policies"))?);
    let result = Value::Object(result);
    topological_order(&result)?;
    Ok(result)
}

fn topological_order(value: &Value) -> WorkflowDocumentResult<Vec<String>> {
    let root = object(value, "document")?;
    let graph = object(
        root.get("graph")
            .ok_or_else(|| invalid("graph is required"))?,
        "graph",
    )?;
    let nodes = array(
        graph
            .get("nodes")
            .ok_or_else(|| invalid("graph.nodes is required"))?,
        "graph.nodes",
    )?;
    let links = array(
        graph
            .get("links")
            .ok_or_else(|| invalid("graph.links is required"))?,
        "graph.links",
    )?;
    let mut indegree = HashMap::new();
    let mut outgoing: HashMap<String, Vec<String>> = HashMap::new();
    for node in nodes {
        let id = string_field(node.get("id"), "");
        indegree.insert(id.clone(), 0_i64);
        outgoing.entry(id).or_default();
    }
    for link in links {
        let source = link
            .get("source")
            .and_then(|value| value.get("node_id"))
            .and_then(Value::as_str)
            .unwrap_or_default();
        let target = link
            .get("target")
            .and_then(|value| value.get("node_id"))
            .and_then(Value::as_str)
            .unwrap_or_default();
        if indegree.contains_key(source) && indegree.contains_key(target) {
            *indegree.get_mut(target).expect("checked above") += 1;
            outgoing
                .get_mut(source)
                .expect("checked above")
                .push(target.into());
        }
    }
    let mut ready = indegree
        .iter()
        .filter(|(_, degree)| **degree == 0)
        .map(|(id, _)| id.clone())
        .collect::<Vec<_>>();
    ready.sort();
    let mut order = Vec::with_capacity(indegree.len());
    while let Some(current) = ready.first().cloned() {
        ready.remove(0);
        order.push(current.clone());
        let mut targets = outgoing.remove(&current).unwrap_or_default();
        targets.sort();
        for target in targets {
            let degree = indegree.get_mut(&target).expect("target exists");
            *degree -= 1;
            if *degree == 0 {
                ready.push(target);
                ready.sort();
            }
        }
    }
    if order.len() != indegree.len() {
        return Err(invalid("workflow graph contains a cycle"));
    }
    Ok(order)
}

/// Project the document to the deterministic canvas-free execution prompt.
pub fn compile_document(value: &Value) -> WorkflowDocumentResult<Value> {
    let document = canonicalize_document(value)?;
    let root = object(&document, "document")?;
    let graph = object(root.get("graph").expect("canonical graph"), "graph")?;
    let nodes = array(graph.get("nodes").expect("canonical nodes"), "graph.nodes")?;
    let links = array(graph.get("links").expect("canonical links"), "graph.links")?;
    let order = topological_order(&document)?;
    let mut incoming: HashMap<(String, String), Vec<&Map<String, Value>>> = HashMap::new();
    for link in links {
        let source = link.get("target").expect("canonical target");
        let key = (
            string_field(source.get("node_id"), ""),
            string_field(source.get("port_id"), ""),
        );
        incoming.entry(key).or_default().push(object(link, "link")?);
    }
    for items in incoming.values_mut() {
        items.sort_by_key(|link| string_field(link.get("id"), ""));
    }
    let mut prompt_nodes = Map::new();
    for node_value in nodes {
        let node = object(node_value, "node")?;
        let node_id = string_field(node.get("id"), "");
        let execution = object(
            node.get("execution").expect("canonical execution"),
            "execution",
        )?;
        if !bool_field(execution.get("enabled"), true) {
            return Err(invalid(format!(
                "node {node_id:?} is disabled and cannot be compiled"
            )));
        }
        if bool_field(execution.get("schema_only"), false) {
            let type_id = node
                .get("type")
                .and_then(|value| value.get("id"))
                .and_then(Value::as_str)
                .unwrap_or("unknown");
            return Err(invalid(format!(
                "node {node_id:?} ({type_id}) is schema-only and cannot execute"
            )));
        }
        let mut inputs = Map::new();
        let ports = array(node.get("ports").expect("canonical ports"), "node.ports")?;
        for port_value in ports {
            let port = object(port_value, "port")?;
            if string_field(port.get("direction"), "") != "in" {
                continue;
            }
            let port_id = string_field(port.get("id"), "");
            let key = (node_id.clone(), port_id.clone());
            if let Some(link_values) = incoming.get(&key).filter(|links| !links.is_empty()) {
                let sources = link_values
                    .iter()
                    .map(|link| {
                        let source = link.get("source").expect("canonical source");
                        let mut item = Map::new();
                        item.insert(
                            "node_id".into(),
                            source.get("node_id").cloned().unwrap_or(Value::Null),
                        );
                        item.insert(
                            "port_id".into(),
                            source.get("port_id").cloned().unwrap_or(Value::Null),
                        );
                        for key in ["transform", "condition"] {
                            if let Some(value) = link.get(key).filter(|value| !value.is_null()) {
                                item.insert(key.into(), value.clone());
                            }
                        }
                        Value::Object(item)
                    })
                    .collect::<Vec<_>>();
                inputs.insert(port_id, json!({"links": sources}));
            } else if let Some(default) = port.get("default") {
                inputs.insert(port_id, json!({"literal": default}));
            } else if bool_field(port.get("required"), false) {
                return Err(invalid(format!(
                    "required input is unbound: {node_id}.{port_id}"
                )));
            }
        }
        let outputs = ports
            .iter()
            .filter_map(|port| {
                (string_field(port.get("direction"), "") == "out")
                    .then(|| Value::String(string_field(port.get("id"), "")))
            })
            .collect::<Vec<_>>();
        let type_ref = object(node.get("type").expect("canonical type"), "node.type")?;
        prompt_nodes.insert(
            node_id,
            json!({
                "type_id": string_field(type_ref.get("id"), ""),
                "type_version": integer_field(type_ref.get("version"), 1),
                "params": node.get("params").cloned().unwrap_or_else(|| json!({})),
                "inputs": inputs,
                "outputs": outputs,
                "execution": execution,
            }),
        );
    }
    Ok(json!({
        "format": PROMPT_FORMAT,
        "version": PROMPT_VERSION,
        "workflow": {
            "id": root["resource"]["id"].clone(),
            "revision": root["resource"]["revision"].clone(),
        },
        "nodes": prompt_nodes,
        "order": order,
        "interface": root["interface"].clone(),
        "policies": root["policies"].clone(),
    }))
}

/// Return compact topology with optional one-hop focus and pagination.
pub fn semantic_graph(
    value: &Value,
    node_ids: Option<&[String]>,
    offset: usize,
    limit: usize,
) -> WorkflowDocumentResult<Value> {
    let document = canonicalize_document(value)?;
    let root = object(&document, "document")?;
    let graph = object(root.get("graph").expect("canonical graph"), "graph")?;
    let all_nodes = array(graph.get("nodes").expect("canonical nodes"), "graph.nodes")?;
    let links = array(graph.get("links").expect("canonical links"), "graph.links")?;
    let requested = node_ids.unwrap_or(&[]);
    let focused = !requested.is_empty();
    let selected: HashSet<String> = requested.iter().cloned().collect();
    let mut focus = HashSet::new();
    let mut visible_nodes = Vec::new();
    if focused {
        for node in all_nodes {
            let id = string_field(node.get("id"), "");
            if selected.contains(&id) {
                focus.insert(id);
            }
        }
        let mut expanded = focus.clone();
        for link in links {
            let source = string_field(
                link.get("source").and_then(|value| value.get("node_id")),
                "",
            );
            let target = string_field(
                link.get("target").and_then(|value| value.get("node_id")),
                "",
            );
            if focus.contains(&source) || focus.contains(&target) {
                expanded.insert(source);
                expanded.insert(target);
            }
        }
        for node in all_nodes {
            if expanded.contains(&string_field(node.get("id"), "")) {
                visible_nodes.push(node.clone());
            }
        }
    } else {
        visible_nodes.extend(all_nodes.iter().cloned());
    }
    let total = visible_nodes.len();
    let page_limit = limit.clamp(1, 500);
    let start = offset.min(usize::MAX);
    let page = visible_nodes
        .iter()
        .skip(start)
        .take(page_limit)
        .collect::<Vec<_>>();
    let page_ids: HashSet<String> = page
        .iter()
        .map(|node| string_field(node.get("id"), ""))
        .collect();
    let summaries = page
        .iter()
        .map(|node_value| {
            let node = object(node_value, "node")?;
            let ports = array(node.get("ports").expect("canonical ports"), "node.ports")?;
            let inputs = ports
                .iter()
                .filter_map(|port_value| {
                    let port = port_value.as_object()?;
                    (string_field(port.get("direction"), "") == "in").then(|| {
                        json!({"id": port["id"], "name": port["name"], "type": port["data_type"]})
                    })
                })
                .collect::<Vec<_>>();
            let outputs = ports
                .iter()
                .filter_map(|port_value| {
                    let port = port_value.as_object()?;
                    (string_field(port.get("direction"), "") == "out").then(|| {
                        json!({"id": port["id"], "name": port["name"], "type": port["data_type"]})
                    })
                })
                .collect::<Vec<_>>();
            Ok(json!({
                "id": node["id"],
                "type_id": node["type"]["id"],
                "title": node["title"],
                "inputs": inputs,
                "outputs": outputs,
                "executable": node["execution"]["enabled"].as_bool().unwrap_or(true)
                    && !node["execution"]["schema_only"].as_bool().unwrap_or(false),
            }))
        })
        .collect::<WorkflowDocumentResult<Vec<_>>>()?;
    let adjacency = links
        .iter()
        .filter_map(|link_value| {
            let link = link_value.as_object()?;
            let source = link.get("source")?;
            let target = link.get("target")?;
            let source_node = source.get("node_id")?.as_str()?;
            let target_node = target.get("node_id")?.as_str()?;
            (page_ids.contains(source_node) && page_ids.contains(target_node)).then(|| {
                json!({
                    "link_id": link["id"],
                    "from": [source["node_id"], source["port_id"]],
                    "to": [target["node_id"], target["port_id"]],
                })
            })
        })
        .collect::<Vec<_>>();
    let mut interface = root["interface"].clone();
    if focused {
        if let Some(interface) = interface.as_object_mut() {
            for (key, endpoint_key) in [("inputs", "target"), ("outputs", "source")] {
                if let Some(items) = interface.get_mut(key).and_then(Value::as_array_mut) {
                    items.retain(|item| {
                        item.get(endpoint_key)
                            .and_then(|endpoint| endpoint.get("node_id"))
                            .and_then(Value::as_str)
                            .is_none_or(|node_id| page_ids.contains(node_id))
                    });
                }
            }
        }
    }
    let full_order = topological_order(&document)?;
    let visible_order = full_order
        .into_iter()
        .filter(|node_id| page_ids.contains(node_id))
        .collect::<Vec<_>>();
    Ok(json!({
        "format": SEMANTIC_FORMAT,
        "version": SEMANTIC_VERSION,
        "workflow": {
            "id": root["resource"]["id"],
            "name": root["resource"]["name"],
            "description": root["resource"]["description"],
            "revision": root["resource"]["revision"],
        },
        "interface": interface,
        "nodes": summaries,
        "adjacency": adjacency,
        "topological_order": visible_order,
        "page": {
            "offset": start,
            "limit": page_limit,
            "total": total,
            "has_more": start + page.len() < total,
        },
    }))
}

fn now_string() -> String {
    // A stable non-empty timestamp is sufficient for a boundary document. The
    // host may replace it with its persisted creation time on save.
    "1970-01-01T00:00:00+00:00".into()
}

/// Project the legacy runtime JSON shape into a canonical V2 document.
pub fn document_from_workflow_def(value: &Value) -> WorkflowDocumentResult<Value> {
    let definition = object(value, "workflow definition")?;
    let id = non_empty_string(
        definition
            .get("id")
            .or_else(|| definition.get("workflow_id")),
        &Uuid::new_v4().simple().to_string(),
    );
    let name = non_empty_string(definition.get("name"), "");
    if name.is_empty() {
        return Err(invalid("workflow definition name is required"));
    }
    let mut nodes = Vec::new();
    let mut views = Map::new();
    let raw_nodes = definition
        .get("nodes")
        .map(|value| array(value, "workflow definition.nodes"))
        .transpose()?
        .cloned()
        .unwrap_or_default();
    let mut port_ids: HashMap<(String, String, String), String> = HashMap::new();
    for raw in &raw_nodes {
        let raw = object(raw, "workflow node")?;
        let node_id = non_empty_string(raw.get("id"), "");
        if node_id.is_empty() {
            return Err(invalid("workflow node id is required"));
        }
        let kind = non_empty_string(raw.get("kind"), "command");
        let type_id = non_empty_string(raw.get("type_id").or_else(|| raw.get("typeId")), &kind);
        let type_version = integer_field(
            raw.get("type_version").or_else(|| raw.get("typeVersion")),
            1,
        )
        .max(1);
        let raw_ports = if let Some(ports) = raw.get("ports") {
            array(ports, &format!("node {node_id}.ports"))?.clone()
        } else {
            let mut ports = Vec::new();
            for (direction, key) in [("in", "inputs"), ("out", "outputs")] {
                if let Some(items) = raw.get(key).and_then(Value::as_array) {
                    for item in items {
                        let mut item = item.as_object().cloned().unwrap_or_default();
                        item.insert("direction".into(), Value::String(direction.into()));
                        ports.push(Value::Object(item));
                    }
                }
            }
            ports
        };
        let mut canonical_ports = Vec::new();
        for raw_port in raw_ports {
            let raw_port = object(&raw_port, "workflow port")?;
            let direction = string_field(raw_port.get("direction"), "in");
            let port_name = non_empty_string(raw_port.get("name"), "");
            let port_id = non_empty_string(
                raw_port
                    .get("id")
                    .or_else(|| raw_port.get("port_id"))
                    .or_else(|| raw_port.get("portId")),
                &stable_id("port", &[&id, &node_id, &direction, &port_name]),
            );
            port_ids.insert(
                (node_id.clone(), direction.clone(), port_name.clone()),
                port_id.clone(),
            );
            let mut port = Map::new();
            port.insert("id".into(), Value::String(port_id));
            port.insert("name".into(), Value::String(port_name));
            port.insert("direction".into(), Value::String(direction));
            port.insert(
                "data_type".into(),
                Value::String(non_empty_string(
                    raw_port.get("type").or_else(|| raw_port.get("data_type")),
                    "any",
                )),
            );
            port.insert(
                "description".into(),
                Value::String(string_field(raw_port.get("description"), "")),
            );
            port.insert("required".into(), Value::Bool(false));
            port.insert(
                "lazy".into(),
                Value::Bool(bool_field(raw_port.get("lazy"), false)),
            );
            if let Some(value) = raw_port.get("value") {
                port.insert("default".into(), value.clone());
            }
            canonical_ports.push(Value::Object(port));
        }
        let mut params = raw
            .get("config")
            .filter(|value| value.is_object())
            .cloned()
            .unwrap_or_else(|| json!({}));
        let mut execution = params
            .get("execution")
            .filter(|value| value.is_object())
            .cloned()
            .unwrap_or_else(|| json!({}));
        if let Some(params_object) = params.as_object_mut() {
            params_object.remove("execution");
            if let Some(on_error) = params_object.remove("on_error") {
                if let Some(execution_object) = execution.as_object_mut() {
                    execution_object.insert("on_error".into(), on_error);
                }
            }
        }
        let execution = execution.as_object().cloned().unwrap_or_default();
        let mut view = Map::new();
        view.insert(
            "position".into(),
            raw.get("position")
                .filter(|value| value.is_object())
                .cloned()
                .unwrap_or_else(|| json!({})),
        );
        if let Some(parent) = raw.get("parent_id").or_else(|| raw.get("parentId")) {
            if let Some(parent) = parent.as_str().filter(|value| !value.trim().is_empty()) {
                view.insert("parent_id".into(), Value::String(parent.trim().into()));
            }
        }
        views.insert(node_id.clone(), Value::Object(view));
        nodes.push(json!({
            "id": node_id,
            "type": {"id": type_id, "version": type_version},
            "title": string_field(raw.get("title"), ""),
            "ports": canonical_ports,
            "params": params,
            "execution": execution,
        }));
    }
    let mut links = Vec::new();
    let raw_edges = definition
        .get("edges")
        .map(|value| array(value, "workflow definition.edges"))
        .transpose()?
        .cloned()
        .unwrap_or_default();
    for (index, raw) in raw_edges.iter().enumerate() {
        let raw = object(raw, "workflow edge")?;
        let source_node = non_empty_string(raw.get("source"), "");
        let target_node = non_empty_string(raw.get("target"), "");
        let source_name = non_empty_string(raw.get("source_port"), "");
        let target_name = non_empty_string(raw.get("target_port"), "");
        let source_port = non_empty_string(
            raw.get("source_port_id")
                .or_else(|| raw.get("sourcePortId")),
            &port_ids
                .get(&(source_node.clone(), "out".into(), source_name.clone()))
                .cloned()
                .unwrap_or_default(),
        );
        let target_port = non_empty_string(
            raw.get("target_port_id")
                .or_else(|| raw.get("targetPortId")),
            &port_ids
                .get(&(target_node.clone(), "in".into(), target_name.clone()))
                .cloned()
                .unwrap_or_default(),
        );
        let edge_id = non_empty_string(raw.get("id"), &format!("link_{index}"));
        let mut link = Map::new();
        link.insert("id".into(), Value::String(edge_id));
        link.insert(
            "source".into(),
            json!({"node_id": source_node, "port_id": source_port}),
        );
        link.insert(
            "target".into(),
            json!({"node_id": target_node, "port_id": target_port}),
        );
        for key in ["transform", "condition"] {
            if let Some(value) = raw.get(key).filter(|value| !value.is_null()) {
                link.insert(key.into(), value.clone());
            }
        }
        links.push(Value::Object(link));
    }
    let mut interface_inputs = Vec::new();
    if let Some(items) = definition
        .get("input_params")
        .or_else(|| definition.get("inputParams"))
        .and_then(Value::as_array)
    {
        for item in items {
            let item = object(item, "workflow input")?;
            let param_name = non_empty_string(item.get("name"), "");
            if param_name.is_empty() {
                continue;
            }
            let mut output = Map::new();
            output.insert(
                "id".into(),
                Value::String(stable_id("input", &[&id, &param_name])),
            );
            output.insert("name".into(), Value::String(param_name.clone()));
            output.insert(
                "data_type".into(),
                Value::String(non_empty_string(
                    item.get("type").or_else(|| item.get("data_type")),
                    "any",
                )),
            );
            output.insert(
                "description".into(),
                Value::String(string_field(item.get("description"), "")),
            );
            output.insert(
                "required".into(),
                Value::Bool(bool_field(item.get("required"), true)),
            );
            if let Some(default) = item.get("default").filter(|value| !value.is_null()) {
                output.insert("default".into(), default.clone());
            }
            if let Some((node, port)) = param_name.rsplit_once('.') {
                if let Some(port_id) = port_ids.get(&(node.into(), "in".into(), port.into())) {
                    output.insert(
                        "target".into(),
                        json!({"node_id": node, "port_id": port_id}),
                    );
                }
            }
            interface_inputs.push(Value::Object(output));
        }
    }
    let mut interface_outputs = Vec::new();
    let output_port = non_empty_string(
        definition
            .get("output_port")
            .or_else(|| definition.get("outputPort")),
        "",
    );
    if let Some((node, port_name)) = output_port.split_once('.') {
        if let Some(port_id) = port_ids.get(&(node.into(), "out".into(), port_name.into())) {
            interface_outputs.push(json!({
                "id": stable_id("output", &[&id, node, port_id]),
                "name": port_name,
                "data_type": "any",
                "description": "",
                "source": {"node_id": node, "port_id": port_id},
            }));
        }
    }
    canonicalize_document(&json!({
        "format": DOCUMENT_FORMAT,
        "version": DOCUMENT_VERSION,
        "resource": {
            "id": id,
            "name": name,
            "description": string_field(definition.get("description"), ""),
            "work_root": string_field(definition.get("work_root").or_else(|| definition.get("workRoot")), ""),
            "revision": integer_field(definition.get("revision"), 0).max(0),
            "created_at": string_field(definition.get("created_at"), &now_string()),
            "updated_at": string_field(definition.get("updated_at"), &now_string()),
        },
        "graph": {"nodes": nodes, "links": links},
        "interface": {"inputs": interface_inputs, "outputs": interface_outputs},
        "exposure": {
            "enabled": bool_field(definition.get("exposed"), false),
            "tool_name": string_field(definition.get("tool_name").or_else(|| definition.get("toolName")), ""),
        },
        "canvas": {
            "viewport": {"x": 0, "y": 0, "zoom": 1},
            "node_views": views,
            "groups": [], "reroutes": [], "annotations": [],
        },
        "triggers": [], "policies": {},
    }))
}

/// Project a canonical V2 document back to the legacy runtime JSON shape.
pub fn workflow_def_from_document(value: &Value) -> WorkflowDocumentResult<Value> {
    let document = canonicalize_document(value)?;
    let root = object(&document, "document")?;
    let graph = object(root.get("graph").expect("canonical graph"), "graph")?;
    let nodes = array(graph.get("nodes").expect("canonical nodes"), "graph.nodes")?;
    let views = root["canvas"]["node_views"]
        .as_object()
        .cloned()
        .unwrap_or_default();
    let mut legacy_nodes = Vec::new();
    let mut port_names = HashMap::new();
    for node_value in nodes {
        let node = object(node_value, "node")?;
        let node_id = string_field(node.get("id"), "");
        let ports = array(node.get("ports").expect("canonical ports"), "ports")?;
        let mut legacy_ports = Vec::new();
        for port_value in ports {
            let port = object(port_value, "port")?;
            let port_id = string_field(port.get("id"), "");
            let port_name = string_field(port.get("name"), "");
            let direction = string_field(port.get("direction"), "in");
            port_names.insert((node_id.clone(), port_id), port_name.clone());
            let mut legacy = json!({
                "id": port["id"], "name": port_name, "type": port["data_type"],
                "direction": direction, "description": port["description"], "lazy": port["lazy"],
            });
            if let Some(default) = port.get("default") {
                legacy["value"] = default.clone();
            }
            legacy_ports.push(legacy);
        }
        let mut config = node.get("params").cloned().unwrap_or_else(|| json!({}));
        config["execution"] = node["execution"].clone();
        config["on_error"] = node["execution"]["on_error"].clone();
        let mut legacy = json!({
            "id": node["id"], "kind": node["type"]["id"], "type_id": node["type"]["id"],
            "type_version": node["type"]["version"], "title": node["title"], "config": config,
            "ports": legacy_ports,
            "position": views.get(&node_id).and_then(|view| view.get("position")).cloned().unwrap_or_else(|| json!({})),
        });
        if let Some(parent) = parent_id_from_view(views.get(&node_id)) {
            legacy["parent_id"] = Value::String(parent);
        }
        legacy_nodes.push(legacy);
    }
    let links = array(graph.get("links").expect("canonical links"), "graph.links")?;
    let mut edges = Vec::new();
    for link_value in links {
        let link = object(link_value, "link")?;
        let source = object(link.get("source").expect("source"), "source")?;
        let target = object(link.get("target").expect("target"), "target")?;
        let source_node = string_field(source.get("node_id"), "");
        let target_node = string_field(target.get("node_id"), "");
        let source_port_id = string_field(source.get("port_id"), "");
        let target_port_id = string_field(target.get("port_id"), "");
        edges.push(json!({
            "id": link["id"], "source": source_node,
            "source_port": port_names.get(&(string_field(source.get("node_id"), ""), source_port_id.clone())).cloned().unwrap_or_default(),
            "source_port_id": source_port_id, "target": target_node,
            "target_port": port_names.get(&(string_field(target.get("node_id"), ""), target_port_id.clone())).cloned().unwrap_or_default(),
            "target_port_id": target_port_id,
            "transform": link.get("transform").cloned().unwrap_or_else(|| Value::String(String::new())),
            "condition": link.get("condition").cloned().unwrap_or_else(|| Value::String(String::new())),
        }));
    }
    let output_port = root["interface"]["outputs"]
        .as_array()
        .and_then(|outputs| outputs.first())
        .and_then(|item| item.get("source"))
        .and_then(|source| {
            let node = source.get("node_id")?.as_str()?;
            let port = source.get("port_id")?.as_str()?;
            Some(format!(
                "{node}.{}",
                port_names
                    .get(&(node.into(), port.into()))
                    .cloned()
                    .unwrap_or_default()
            ))
        })
        .unwrap_or_default();
    let input_params = root["interface"]["inputs"]
        .as_array()
        .into_iter()
        .flatten()
        .map(|item| {
            json!({
                "name": item["name"], "type": item["data_type"], "description": item["description"],
                "required": item["required"], "default": item.get("default").cloned().unwrap_or(Value::Null),
            })
        })
        .collect::<Vec<_>>();
    Ok(json!({
        "id": root["resource"]["id"], "name": root["resource"]["name"],
        "description": root["resource"]["description"], "nodes": legacy_nodes, "edges": edges,
        "input_params": input_params, "output_port": output_port,
        "exposed": root["exposure"]["enabled"], "tool_name": root["exposure"]["tool_name"],
        "work_root": root["resource"]["work_root"], "revision": root["resource"]["revision"],
        "created_at": root["resource"]["created_at"], "updated_at": root["resource"]["updated_at"],
    }))
}

fn numeric_id(value: Option<&Value>) -> Option<i64> {
    match value {
        Some(Value::Number(number)) => number.as_i64().filter(|value| *value >= 0),
        Some(Value::String(text)) if text.trim().chars().all(|char| char.is_ascii_digit()) => {
            text.trim().parse::<i64>().ok()
        }
        _ => None,
    }
}

fn known_comfyui_type(type_id: &str) -> bool {
    matches!(
        type_id,
        "model"
            | "agent"
            | "ai"
            | "command"
            | "script"
            | "python"
            | "content"
            | "constant"
            | "input"
            | "output"
            | "template"
            | "transform"
            | "condition"
            | "branch"
            | "merge"
            | "join"
            | "wait_event"
            | "approval"
            | "subgraph"
    )
}

/// Import a ComfyUI v0.4/v1 editor workflow into V2.
pub fn import_comfyui(value: &Value, name: &str) -> WorkflowDocumentResult<Value> {
    reject_secrets(value, "comfyui")?;
    let source = object(value, "ComfyUI workflow")?;
    let raw_nodes = array(
        source
            .get("nodes")
            .ok_or_else(|| invalid("ComfyUI workflow requires nodes[]"))?,
        "ComfyUI nodes",
    )?;
    let workflow_id = non_empty_string(source.get("id"), &Uuid::new_v4().simple().to_string());
    let mut nodes = Vec::new();
    let mut views = Map::new();
    let mut slot_ports: HashMap<(String, String, i64), String> = HashMap::new();
    for raw_value in raw_nodes {
        let raw = match raw_value.as_object() {
            Some(raw) => raw,
            None => continue,
        };
        let node_id = non_empty_string(raw.get("id"), "");
        if node_id.is_empty() {
            return Err(invalid("ComfyUI node requires a non-empty id"));
        }
        let class_type =
            non_empty_string(raw.get("type").or_else(|| raw.get("class_type")), "unknown");
        let mapped = raw
            .get("properties")
            .and_then(|value| value.get("lamtools_type_id"))
            .and_then(Value::as_str)
            .filter(|value| !value.is_empty())
            .unwrap_or(&class_type)
            .to_owned();
        let mut ports = Vec::new();
        for (direction, key) in [("in", "inputs"), ("out", "outputs")] {
            if let Some(slots) = raw.get(key).and_then(Value::as_array) {
                for (index, slot_value) in slots.iter().enumerate() {
                    let slot = slot_value.as_object().cloned().unwrap_or_default();
                    let port_id = stable_id(
                        "port",
                        &[&workflow_id, &node_id, direction, &index.to_string()],
                    );
                    slot_ports.insert(
                        (node_id.clone(), direction.into(), index as i64),
                        port_id.clone(),
                    );
                    ports.push(json!({
                        "id": port_id,
                        "name": non_empty_string(slot.get("name"), &format!("{direction}{index}")),
                        "direction": direction,
                        "data_type": non_empty_string(slot.get("type"), "any").to_ascii_lowercase(),
                        "description": "", "required": false, "lazy": false,
                    }));
                }
            }
        }
        let pos = raw.get("pos").and_then(Value::as_array);
        let size = raw.get("size").and_then(Value::as_array);
        let mut view = Map::new();
        view.insert(
            "position".into(),
            json!({"x": numeric_field(pos.and_then(|items| items.first()), 0.0), "y": numeric_field(pos.and_then(|items| items.get(1)), 0.0)}),
        );
        if let Some(size) = size.filter(|items| items.len() >= 2) {
            view.insert(
                "size".into(),
                json!({"width": numeric_field(size.first(), 0.0), "height": numeric_field(size.get(1), 0.0)}),
            );
        }
        view.insert(
            "comfyui".into(),
            json!({
                "order": raw.get("order").cloned().unwrap_or(Value::Null),
                "mode": raw.get("mode").cloned().unwrap_or(Value::Null),
                "flags": raw.get("flags").filter(|value| value.is_object()).cloned().unwrap_or_else(|| json!({})),
                "raw": Value::Object(raw.clone()),
            }),
        );
        views.insert(node_id.clone(), Value::Object(view));
        nodes.push(json!({
            "id": node_id,
            "type": {"id": mapped, "version": 1},
            "title": non_empty_string(raw.get("title"), &class_type),
            "ports": ports,
            "params": {},
            "execution": {
                "enabled": true,
                "schema_only": !known_comfyui_type(&mapped),
                "cache": "auto",
                "on_error": {"strategy": "abort"},
                "permissions": [],
            },
        }));
    }
    let mut links = Vec::new();
    let mut link_metadata = Map::new();
    if let Some(raw_links) = source.get("links").and_then(Value::as_array) {
        for (index, raw_value) in raw_links.iter().enumerate() {
            let (link_id, source_node, source_slot, target_node, target_slot) =
                if let Some(items) = raw_value.as_array() {
                    if items.len() < 5 {
                        continue;
                    }
                    (
                        items[0].clone(),
                        items[1].clone(),
                        items[2].clone(),
                        items[3].clone(),
                        items[4].clone(),
                    )
                } else if let Some(item) = raw_value.as_object() {
                    (
                        item.get("id").cloned().unwrap_or_else(|| json!(index)),
                        item.get("origin_id")
                            .or_else(|| item.get("source_id"))
                            .cloned()
                            .unwrap_or(Value::Null),
                        item.get("origin_slot")
                            .or_else(|| item.get("source_slot"))
                            .cloned()
                            .unwrap_or_else(|| json!(0)),
                        item.get("target_id").cloned().unwrap_or(Value::Null),
                        item.get("target_slot").cloned().unwrap_or_else(|| json!(0)),
                    )
                } else {
                    continue;
                };
            let source_node = string_field(Some(&source_node), "");
            let target_node = string_field(Some(&target_node), "");
            let source_slot = numeric_id(Some(&source_slot)).ok_or_else(|| {
                invalid(format!(
                    "ComfyUI link {:?} has an invalid origin slot",
                    link_id
                ))
            })?;
            let target_slot = numeric_id(Some(&target_slot)).ok_or_else(|| {
                invalid(format!(
                    "ComfyUI link {:?} has an invalid target slot",
                    link_id
                ))
            })?;
            let source_key = (source_node.clone(), "out".into(), source_slot);
            let target_key = (target_node.clone(), "in".into(), target_slot);
            let Some(source_port) = slot_ports.get(&source_key) else {
                return Err(invalid(format!(
                    "ComfyUI link {:?} references an unknown slot",
                    link_id
                )));
            };
            let Some(target_port) = slot_ports.get(&target_key) else {
                return Err(invalid(format!(
                    "ComfyUI link {:?} references an unknown slot",
                    link_id
                )));
            };
            let id = string_field(Some(&link_id), &index.to_string());
            links.push(json!({
                "id": id,
                "source": {"node_id": source_node, "port_id": source_port},
                "target": {"node_id": target_node, "port_id": target_port},
            }));
            if let Some(raw) = raw_value.as_object() {
                link_metadata.insert(id, Value::Object(raw.clone()));
            }
        }
    }
    let extra = source.get("extra").and_then(Value::as_object);
    let ds = extra
        .and_then(|extra| extra.get("ds"))
        .and_then(Value::as_object);
    let offset = ds.and_then(|ds| ds.get("offset")).and_then(Value::as_array);
    let legacy = string_field(source.get("version"), "").starts_with("0.");
    let reroutes = if legacy {
        extra.and_then(|extra| extra.get("reroutes"))
    } else {
        source.get("reroutes")
    }
    .filter(|value| value.is_array())
    .cloned()
    .unwrap_or_else(|| json!([]));
    let lamtools = extra
        .and_then(|extra| extra.get("lamtools"))
        .and_then(Value::as_object);
    canonicalize_document(&json!({
        "format": DOCUMENT_FORMAT, "version": DOCUMENT_VERSION,
        "resource": {
            "id": workflow_id,
            "name": if name.trim().is_empty() { non_empty_string(source.get("name"), "Imported ComfyUI workflow") } else { name.to_owned() },
            "description": "", "work_root": "", "revision": 0,
            "created_at": now_string(), "updated_at": now_string(),
        },
        "graph": {"nodes": nodes, "links": links},
        "interface": {"inputs": [], "outputs": []},
        "exposure": {"enabled": false, "tool_name": ""},
        "triggers": lamtools.and_then(|item| item.get("triggers")).cloned().unwrap_or_else(|| json!([])),
        "policies": lamtools.and_then(|item| item.get("policies")).cloned().unwrap_or_else(|| json!({})),
        "canvas": {
            "viewport": {
                "x": numeric_field(offset.and_then(|items| items.first()), 0.0),
                "y": numeric_field(offset.and_then(|items| items.get(1)), 0.0),
                "zoom": numeric_field(ds.and_then(|item| item.get("scale")), 1.0),
            },
            "node_views": views,
            "groups": source.get("groups").filter(|value| value.is_array()).cloned().unwrap_or_else(|| json!([])),
            "reroutes": reroutes,
            "annotations": [],
            "comfyui": {"links": link_metadata},
        },
    }))
}

/// Export a V2 document using ComfyUI v1 object links or v0.4 array links.
pub fn export_comfyui(value: &Value, version: &str) -> WorkflowDocumentResult<Value> {
    let document = canonicalize_document(value)?;
    let root = object(&document, "document")?;
    let graph = object(root.get("graph").expect("canonical graph"), "graph")?;
    let nodes = array(graph.get("nodes").expect("canonical nodes"), "nodes")?;
    let links = array(graph.get("links").expect("canonical links"), "links")?;
    let v1 = version.starts_with('1');
    let mut used_link_ids = HashSet::new();
    let mut link_numbers = HashMap::new();
    let mut next_link_id = 1_i64;
    for link in links {
        let id = string_field(link.get("id"), "");
        let mut candidate = numeric_id(link.get("id"));
        if candidate.is_none() || used_link_ids.contains(&candidate.unwrap()) {
            while used_link_ids.contains(&next_link_id) {
                next_link_id += 1;
            }
            candidate = Some(next_link_id);
        }
        let candidate = candidate.expect("assigned above");
        used_link_ids.insert(candidate);
        next_link_id = next_link_id.max(candidate + 1);
        link_numbers.insert(id, candidate);
    }
    let mut node_ports: HashMap<(String, String), (String, usize)> = HashMap::new();
    let mut port_types = HashMap::new();
    let mut external_node_ids = HashMap::new();
    let views = root["canvas"]["node_views"]
        .as_object()
        .cloned()
        .unwrap_or_default();
    for node_value in nodes {
        let node = object(node_value, "node")?;
        let node_id = string_field(node.get("id"), "");
        let view = views.get(&node_id).and_then(Value::as_object);
        let raw = view
            .and_then(|view| view.get("comfyui"))
            .and_then(|value| value.get("raw"))
            .and_then(Value::as_object);
        let external = raw
            .and_then(|raw| raw.get("id"))
            .filter(|raw_id| raw_id.to_string().trim_matches('"') == node_id)
            .cloned()
            .unwrap_or_else(|| Value::String(node_id.clone()));
        external_node_ids.insert(node_id.clone(), external);
        let ports = array(node.get("ports").expect("ports"), "ports")?;
        for (index, port_value) in ports
            .iter()
            .filter(|port| string_field(port.get("direction"), "") == "in")
            .enumerate()
        {
            let port = object(port_value, "port")?;
            let port_id = string_field(port.get("id"), "");
            node_ports.insert((node_id.clone(), port_id), ("in".into(), index));
            port_types.insert(
                (node_id.clone(), string_field(port.get("id"), "")),
                string_field(port.get("data_type"), "*").to_ascii_uppercase(),
            );
        }
        for (index, port_value) in ports
            .iter()
            .filter(|port| string_field(port.get("direction"), "") == "out")
            .enumerate()
        {
            let port = object(port_value, "port")?;
            let port_id = string_field(port.get("id"), "");
            node_ports.insert((node_id.clone(), port_id.clone()), ("out".into(), index));
            port_types.insert(
                (node_id.clone(), port_id),
                string_field(port.get("data_type"), "*").to_ascii_uppercase(),
            );
        }
    }
    let raw_link_metadata = root["canvas"]["comfyui"]["links"]
        .as_object()
        .cloned()
        .unwrap_or_default();
    let mut links_by_port: HashMap<(String, String), Vec<i64>> = HashMap::new();
    let mut link_rows = Vec::new();
    for link_value in links {
        let link = object(link_value, "link")?;
        let id = string_field(link.get("id"), "");
        let source = object(link.get("source").expect("source"), "source")?;
        let target = object(link.get("target").expect("target"), "target")?;
        let source_node = string_field(source.get("node_id"), "");
        let source_port = string_field(source.get("port_id"), "");
        let target_node = string_field(target.get("node_id"), "");
        let target_port = string_field(target.get("port_id"), "");
        let source_slot = node_ports
            .get(&(source_node.clone(), source_port.clone()))
            .map(|(_, index)| *index)
            .ok_or_else(|| invalid(format!("link {id:?} references an unknown source port")))?;
        let target_slot = node_ports
            .get(&(target_node.clone(), target_port.clone()))
            .map(|(_, index)| *index)
            .ok_or_else(|| invalid(format!("link {id:?} references an unknown target port")))?;
        let number = *link_numbers.get(&id).expect("assigned above");
        let source_id = external_node_ids
            .get(&source_node)
            .cloned()
            .unwrap_or(Value::String(source_node.clone()));
        let target_id = external_node_ids
            .get(&target_node)
            .cloned()
            .unwrap_or(Value::String(target_node.clone()));
        let link_type = port_types
            .get(&(source_node.clone(), source_port.clone()))
            .cloned()
            .unwrap_or_else(|| "*".into());
        if v1 {
            let mut row = raw_link_metadata
                .get(&id)
                .and_then(Value::as_object)
                .cloned()
                .unwrap_or_default();
            row.insert("id".into(), json!(number));
            row.insert("origin_id".into(), source_id);
            row.insert("origin_slot".into(), json!(source_slot));
            row.insert("target_id".into(), target_id);
            row.insert("target_slot".into(), json!(target_slot));
            row.insert("type".into(), Value::String(link_type));
            link_rows.push(Value::Object(row));
        } else {
            link_rows.push(json!([
                number,
                source_id,
                source_slot,
                target_id,
                target_slot,
                link_type
            ]));
        }
        links_by_port
            .entry((source_node, source_port))
            .or_default()
            .push(number);
        links_by_port
            .entry((target_node, target_port))
            .or_default()
            .push(number);
    }
    let mut exported_nodes = Vec::new();
    for (order, node_value) in nodes.iter().enumerate() {
        let node = object(node_value, "node")?;
        let node_id = string_field(node.get("id"), "");
        let view = views
            .get(&node_id)
            .and_then(Value::as_object)
            .cloned()
            .unwrap_or_default();
        let comfy_view = view
            .get("comfyui")
            .and_then(Value::as_object)
            .cloned()
            .unwrap_or_default();
        let mut raw_node = comfy_view
            .get("raw")
            .and_then(Value::as_object)
            .cloned()
            .unwrap_or_default();
        let raw_inputs = raw_node
            .get("inputs")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        let raw_outputs = raw_node
            .get("outputs")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        let params = node
            .get("params")
            .and_then(Value::as_object)
            .cloned()
            .unwrap_or_default();
        let comfy_params = params
            .get("comfyui")
            .and_then(Value::as_object)
            .cloned()
            .unwrap_or_default();
        let ports = array(node.get("ports").expect("ports"), "ports")?;
        let mut inputs = Vec::new();
        let mut outputs = Vec::new();
        for port_value in ports {
            let port = object(port_value, "port")?;
            let port_id = string_field(port.get("id"), "");
            let direction = string_field(port.get("direction"), "in");
            let linked = links_by_port
                .get(&(node_id.clone(), port_id))
                .cloned()
                .unwrap_or_default();
            if direction == "in" {
                let mut slot = raw_inputs
                    .get(inputs.len())
                    .and_then(Value::as_object)
                    .cloned()
                    .unwrap_or_default();
                slot.insert(
                    "name".into(),
                    Value::String(string_field(port.get("name"), "")),
                );
                slot.insert(
                    "type".into(),
                    Value::String(string_field(port.get("data_type"), "*").to_ascii_uppercase()),
                );
                slot.insert(
                    "link".into(),
                    linked
                        .first()
                        .copied()
                        .map_or(Value::Null, |value| json!(value)),
                );
                inputs.push(Value::Object(slot));
            } else {
                let mut slot = raw_outputs
                    .get(outputs.len())
                    .and_then(Value::as_object)
                    .cloned()
                    .unwrap_or_default();
                slot.insert(
                    "name".into(),
                    Value::String(string_field(port.get("name"), "")),
                );
                slot.insert(
                    "type".into(),
                    Value::String(string_field(port.get("data_type"), "*").to_ascii_uppercase()),
                );
                slot.insert(
                    "links".into(),
                    if linked.is_empty() {
                        Value::Null
                    } else {
                        json!(linked)
                    },
                );
                outputs.push(Value::Object(slot));
            }
        }
        let mut properties = raw_node
            .get("properties")
            .and_then(Value::as_object)
            .cloned()
            .unwrap_or_default();
        properties.insert("lamtools_type_id".into(), node["type"]["id"].clone());
        properties.insert(
            "lamtools_type_version".into(),
            node["type"]["version"].clone(),
        );
        raw_node.insert(
            "id".into(),
            external_node_ids
                .get(&node_id)
                .cloned()
                .unwrap_or(Value::String(node_id.clone())),
        );
        raw_node.insert(
            "type".into(),
            Value::String(string_field(
                raw_node
                    .get("type")
                    .or_else(|| comfy_params.get("class_type")),
                string_field(
                    node.get("type").and_then(|value| value.get("id")),
                    "unknown",
                )
                .as_str(),
            )),
        );
        let position = view.get("position").and_then(Value::as_object);
        let size = view.get("size").and_then(Value::as_object);
        raw_node.insert(
            "pos".into(),
            json!([
                numeric_field(position.and_then(|item| item.get("x")), 0.0),
                numeric_field(position.and_then(|item| item.get("y")), 0.0)
            ]),
        );
        raw_node.insert(
            "size".into(),
            json!([
                numeric_field(size.and_then(|item| item.get("width")), 240.0),
                numeric_field(size.and_then(|item| item.get("height")), 120.0)
            ]),
        );
        raw_node.insert(
            "flags".into(),
            comfy_view
                .get("flags")
                .filter(|value| value.is_object())
                .cloned()
                .unwrap_or_else(|| json!({})),
        );
        raw_node.insert("order".into(), json!(order));
        raw_node.insert(
            "mode".into(),
            json!(integer_field(comfy_view.get("mode"), 0)),
        );
        raw_node.insert("inputs".into(), Value::Array(inputs));
        raw_node.insert("outputs".into(), Value::Array(outputs));
        raw_node.insert(
            "title".into(),
            node.get("title")
                .cloned()
                .unwrap_or_else(|| Value::String(String::new())),
        );
        raw_node.insert("properties".into(), Value::Object(properties));
        raw_node.insert(
            "widgets_values".into(),
            raw_node
                .get("widgets_values")
                .cloned()
                .or_else(|| comfy_params.get("widgets_values").cloned())
                .unwrap_or_else(|| json!([])),
        );
        exported_nodes.push(Value::Object(raw_node));
    }
    let viewport = root["canvas"]["viewport"]
        .as_object()
        .cloned()
        .unwrap_or_default();
    let max_node_id = exported_nodes
        .iter()
        .filter_map(|node| numeric_id(node.get("id")))
        .max()
        .unwrap_or(0);
    let max_link_id = used_link_ids.iter().copied().max().unwrap_or(0);
    let groups = root["canvas"]["groups"].clone();
    let reroutes = root["canvas"]["reroutes"].clone();
    let max_group_id = groups
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|item| numeric_id(item.get("id")))
        .max()
        .unwrap_or(0);
    let max_reroute_id = reroutes
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|item| numeric_id(item.get("id")))
        .max()
        .unwrap_or(0);
    let mut extra = json!({
        "ds": {"scale": numeric_field(viewport.get("zoom"), 1.0), "offset": [numeric_field(viewport.get("x"), 0.0), numeric_field(viewport.get("y"), 0.0)]},
    });
    if !root["triggers"].as_array().is_none_or(Vec::is_empty)
        || !root["policies"].as_object().is_none_or(Map::is_empty)
    {
        extra["lamtools"] = json!({"triggers": root["triggers"], "policies": root["policies"]});
    }
    if !v1 {
        extra["reroutes"] = reroutes.clone();
        Ok(json!({
            "version": 0.4, "last_node_id": max_node_id, "last_link_id": max_link_id,
            "nodes": exported_nodes, "links": link_rows, "groups": groups, "extra": extra,
        }))
    } else {
        Ok(json!({
            "version": 1,
            "state": {"lastGroupId": max_group_id, "lastNodeId": max_node_id, "lastLinkId": max_link_id, "lastRerouteId": max_reroute_id},
            "nodes": exported_nodes, "links": link_rows, "groups": groups, "reroutes": reroutes, "extra": extra,
        }))
    }
}

pub fn canonicalize(value: &Value) -> WorkflowDocumentResult<Value> {
    canonicalize_document(value)
}

pub fn compile(value: &Value) -> WorkflowDocumentResult<Value> {
    compile_document(value)
}

pub fn semantic(value: &Value) -> WorkflowDocumentResult<Value> {
    semantic_graph(value, None, 0, 100)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn uuid5_stable_ids_match_python_prefix_shape() {
        assert_eq!(
            stable_id("port", &["wf", "a", "out", "value"]),
            "port_24ee1661e87f5ed0"
        );
        assert_ne!(
            stable_id("port", &["wf", "a", "out", "value"]),
            stable_id("port", &["wf", "a", "in", "value"])
        );
    }
}

// Keep the public module's API intentionally data-only.  These aliases make
// callers migrating from the Python names explicit while preserving a single
// canonical implementation.
pub type Document = Value;
pub type Prompt = Value;
pub type SemanticGraph = Value;
