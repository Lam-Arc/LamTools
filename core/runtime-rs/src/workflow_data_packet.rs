//! Versioned JSON item envelope at Workflow node boundaries.
//!
//! Binary content belongs to Core attachments. A packet carries only JSON
//! values and validated references to those attachments.

use serde_json::{json, Map, Value};

pub const DATA_PACKET_FORMAT: &str = "lamtools.workflow.data-packet";
pub const DATA_PACKET_VERSION: u64 = 1;

#[derive(Clone, Debug, PartialEq, Eq, thiserror::Error)]
#[error("{0}")]
pub struct WorkflowDataPacketError(pub String);

type Result<T> = std::result::Result<T, WorkflowDataPacketError>;

fn error(message: impl Into<String>) -> WorkflowDataPacketError {
    WorkflowDataPacketError(message.into())
}

fn object<'a>(value: &'a Value, message: &str) -> Result<&'a Map<String, Value>> {
    value.as_object().ok_or_else(|| error(message))
}

fn python_string(value: &Value) -> String {
    match value {
        Value::Null => "None".into(),
        Value::Bool(true) => "True".into(),
        Value::Bool(false) => "False".into(),
        Value::String(value) => value.clone(),
        other => other.to_string(),
    }
}

fn text_or_empty(value: Option<&Value>) -> String {
    value
        .filter(|v| !v.is_null() && *v != "")
        .map(python_string)
        .unwrap_or_default()
}

fn first_truthy<'a>(map: &'a Map<String, Value>, keys: &[&str]) -> Option<&'a Value> {
    keys.iter()
        .filter_map(|key| map.get(*key))
        .find(|v| !v.is_null() && *v != "")
}

fn first_present<'a>(map: &'a Map<String, Value>, keys: &[&str]) -> Option<&'a Value> {
    keys.iter().find_map(|key| map.get(*key))
}

fn control_char(text: &str) -> bool {
    text.chars().any(|ch| (ch as u32) <= 31 || ch == '\u{7f}')
}

fn safe_identifier(value: &str, name: &str) -> Result<String> {
    let text = value.trim();
    if text.is_empty() {
        return Err(error(format!("{name} is required")));
    }
    if text.chars().count() > 512 || control_char(text) || text.chars().any(char::is_whitespace) {
        return Err(error(format!("{name} must be a non-whitespace identifier")));
    }
    Ok(text.into())
}

fn valid_uri(uri: &str, schemes: &[&str]) -> bool {
    if uri.chars().any(char::is_whitespace) {
        return false;
    }
    schemes.iter().any(|scheme| {
        uri.get(..scheme.len())
            .is_some_and(|prefix| prefix.eq_ignore_ascii_case(scheme))
            && uri.len() > scheme.len()
    })
}

fn validate_reference_map(map: &Map<String, Value>, kind: &str) -> Result<()> {
    const BINARY_FIELDS: &[&str] = &[
        "content",
        "data",
        "bytes",
        "blob",
        "body",
        "payload",
        "base64",
        "data_url",
        "data_uri",
        "inline",
        "raw_bytes",
        "storage_path",
        "local_path",
    ];
    for key in map.keys() {
        if BINARY_FIELDS.contains(&key.trim().to_ascii_lowercase().as_str()) {
            return Err(error(format!(
                "{kind} references cannot embed binary field {key:?}"
            )));
        }
    }
    for key in ["uri", "url", "ref", "path"] {
        if map
            .get(key)
            .and_then(Value::as_str)
            .is_some_and(|value| value.to_ascii_lowercase().starts_with("data:"))
        {
            return Err(error(format!("{kind} references cannot contain data URLs")));
        }
    }
    Ok(())
}

fn reject_unknown(map: &Map<String, Value>, allowed: &[&str], kind: &str) -> Result<()> {
    let unknown: Vec<&str> = map
        .keys()
        .map(String::as_str)
        .filter(|key| !allowed.contains(key))
        .collect();
    if unknown.is_empty() {
        Ok(())
    } else {
        Err(error(format!("unknown {kind} fields: {unknown:?}")))
    }
}

fn size(map: &Map<String, Value>, kind: &str) -> Result<Option<u64>> {
    match map.get("size") {
        None | Some(Value::Null) => Ok(None),
        Some(Value::Number(number)) => number
            .as_u64()
            .ok_or_else(|| error(format!("{kind} size must be a non-negative integer")))
            .map(Some),
        _ => Err(error(format!("{kind} size must be a non-negative integer"))),
    }
}

fn metadata(map: &Map<String, Value>) -> Map<String, Value> {
    map.get("metadata")
        .and_then(Value::as_object)
        .cloned()
        .unwrap_or_default()
}

/// Validated Core attachment locator. `from_value` accepts Python's field aliases.
#[derive(Clone, Debug, PartialEq)]
pub struct AttachmentRef {
    pub id: String,
    pub filename: String,
    pub mime_type: String,
    pub size: Option<u64>,
    pub checksum: String,
    pub uri: String,
    pub metadata: Map<String, Value>,
}

impl AttachmentRef {
    pub fn from_value(value: &Value) -> Result<Self> {
        let map = object(value, "attachment must be a reference object")?;
        validate_reference_map(map, "attachment")?;
        reject_unknown(
            map,
            &[
                "id",
                "attachment_id",
                "filename",
                "name",
                "mime_type",
                "mime",
                "size",
                "checksum",
                "sha256",
                "uri",
                "ref",
                "metadata",
            ],
            "attachment reference",
        )?;
        let uri = text_or_empty(first_present(map, &["uri", "ref"]))
            .trim()
            .to_owned();
        let mut id = text_or_empty(first_present(map, &["id", "attachment_id"]));
        if id.is_empty()
            && uri
                .get(..13)
                .is_some_and(|s| s.eq_ignore_ascii_case("attachment://"))
        {
            id = uri[13..].to_owned();
        }
        let id = safe_identifier(&id, "attachment id")?;
        let filename = text_or_empty(first_truthy(map, &["filename", "name"]))
            .trim()
            .to_owned();
        if control_char(&filename) {
            return Err(error("attachment filename is invalid"));
        }
        let mime_type = text_or_empty(first_truthy(map, &["mime_type", "mime"]))
            .trim()
            .to_owned();
        if control_char(&mime_type) || mime_type.chars().any(char::is_whitespace) {
            return Err(error("attachment mime_type is invalid"));
        }
        let checksum = text_or_empty(first_truthy(map, &["checksum", "sha256"]))
            .trim()
            .to_owned();
        if control_char(&checksum) || checksum.chars().any(char::is_whitespace) {
            return Err(error("attachment checksum is invalid"));
        }
        if !uri.is_empty() {
            if !valid_uri(&uri, &["attachment://", "http://", "https://"]) {
                return Err(error(
                    "attachment uri must be an attachment:// or http(s):// reference",
                ));
            }
            if uri
                .get(..13)
                .is_some_and(|s| s.eq_ignore_ascii_case("attachment://"))
                && uri[13..].trim() != id
            {
                return Err(error("attachment uri id does not match attachment id"));
            }
        }
        Ok(Self {
            id,
            filename,
            mime_type,
            size: size(map, "attachment")?,
            checksum,
            uri,
            metadata: metadata(map),
        })
    }

    pub fn to_value(&self) -> Value {
        let mut map = Map::new();
        map.insert("id".into(), json!(self.id));
        for (key, value) in [
            ("filename", &self.filename),
            ("mime_type", &self.mime_type),
            ("checksum", &self.checksum),
            ("uri", &self.uri),
        ] {
            if !value.is_empty() {
                map.insert(key.into(), json!(value));
            }
        }
        if let Some(size) = self.size {
            map.insert("size".into(), json!(size));
        }
        if !self.metadata.is_empty() {
            map.insert("metadata".into(), Value::Object(self.metadata.clone()));
        }
        Value::Object(map)
    }
}

/// Validated workspace, attachment, or remote artifact locator.
#[derive(Clone, Debug, PartialEq)]
pub struct ArtifactRef {
    pub artifact_id: String,
    pub uri: String,
    pub kind: String,
    pub mime_type: String,
    pub name: String,
    pub size: Option<u64>,
    pub checksum: String,
    pub metadata: Map<String, Value>,
}

impl ArtifactRef {
    pub fn from_value(value: &Value) -> Result<Self> {
        let map = object(value, "artifact must be a reference object")?;
        validate_reference_map(map, "artifact")?;
        reject_unknown(
            map,
            &[
                "artifact_id",
                "id",
                "uri",
                "ref",
                "path",
                "kind",
                "mime_type",
                "name",
                "filename",
                "size",
                "checksum",
                "sha256",
                "metadata",
            ],
            "artifact reference",
        )?;
        let uri = text_or_empty(first_present(map, &["uri", "ref", "path"]))
            .trim()
            .to_owned();
        let id = text_or_empty(first_truthy(map, &["artifact_id", "id"]));
        let artifact_id = safe_identifier(if id.is_empty() { &uri } else { &id }, "artifact id")?;
        if !uri.is_empty()
            && !valid_uri(
                &uri,
                &["workspace://", "attachment://", "http://", "https://"],
            )
        {
            return Err(error(
                "artifact uri must use workspace://, attachment://, or http(s)://",
            ));
        }
        let kind = text_or_empty(map.get("kind")).trim().to_owned();
        let mime_type = text_or_empty(map.get("mime_type")).trim().to_owned();
        let name = text_or_empty(first_truthy(map, &["name", "filename"]))
            .trim()
            .to_owned();
        let checksum = text_or_empty(first_truthy(map, &["checksum", "sha256"]))
            .trim()
            .to_owned();
        for (field, value) in [
            ("kind", &kind),
            ("mime_type", &mime_type),
            ("name", &name),
            ("checksum", &checksum),
        ] {
            if control_char(value) {
                return Err(error(format!("artifact {field} is invalid")));
            }
        }
        Ok(Self {
            artifact_id,
            uri,
            kind,
            mime_type,
            name,
            size: size(map, "artifact")?,
            checksum,
            metadata: metadata(map),
        })
    }

    pub fn to_value(&self) -> Value {
        let mut map = Map::new();
        map.insert("artifact_id".into(), json!(self.artifact_id));
        for (key, value) in [
            ("uri", &self.uri),
            ("kind", &self.kind),
            ("mime_type", &self.mime_type),
            ("name", &self.name),
            ("checksum", &self.checksum),
        ] {
            if !value.is_empty() {
                map.insert(key.into(), json!(value));
            }
        }
        if let Some(size) = self.size {
            map.insert("size".into(), json!(size));
        }
        if !self.metadata.is_empty() {
            map.insert("metadata".into(), Value::Object(self.metadata.clone()));
        }
        Value::Object(map)
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct WorkflowDataItem {
    pub json: Value,
    pub binary: Option<AttachmentRef>,
    pub paired: Vec<Value>,
    pub lineage: Vec<String>,
}

impl WorkflowDataItem {
    pub fn from_value(value: &Value) -> Result<Self> {
        let map = object(value, "packet items must be objects")?;
        reject_unknown(
            map,
            &[
                "json",
                "binary",
                "paired",
                "paired_item",
                "pairedItem",
                "lineage",
            ],
            "data item",
        )?;
        let json = map
            .get("json")
            .ok_or_else(|| error("packet item requires json"))?
            .clone();
        let binary = map
            .get("binary")
            .filter(|value| !value.is_null())
            .map(AttachmentRef::from_value)
            .transpose()?;
        let paired = match first_present(map, &["paired", "paired_item", "pairedItem"]) {
            None | Some(Value::Null) => vec![],
            Some(Value::Array(items)) => items.clone(),
            Some(value @ (Value::Object(_) | Value::String(_))) => vec![value.clone()],
            _ => return Err(error("item.paired must be a JSON value or array")),
        };
        let lineage = match map.get("lineage") {
            None | Some(Value::Null) => vec![],
            Some(Value::String(value)) => vec![value.clone()],
            Some(Value::Array(items)) => items
                .iter()
                .map(|item| python_string(item).trim().to_owned())
                .collect(),
            _ => return Err(error("item.lineage must be a string or array")),
        };
        if lineage
            .iter()
            .any(|entry| entry.is_empty() || control_char(entry))
        {
            return Err(error("item.lineage entries must be non-empty identifiers"));
        }
        Ok(Self {
            json,
            binary,
            paired,
            lineage,
        })
    }

    pub fn to_value(&self) -> Value {
        let mut map = Map::new();
        map.insert("json".into(), self.json.clone());
        map.insert("paired".into(), json!(self.paired));
        map.insert("lineage".into(), json!(self.lineage));
        if let Some(binary) = &self.binary {
            map.insert("binary".into(), binary.to_value());
        }
        Value::Object(map)
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WorkflowDataPacket {
    pub items: Vec<WorkflowDataItem>,
}

impl WorkflowDataPacket {
    pub fn from_value(value: &Value) -> Result<Self> {
        let map = object(value, "data packet must be an object")?;
        if map.get("format").and_then(Value::as_str) != Some(DATA_PACKET_FORMAT) {
            return Err(error(format!(
                "expected {DATA_PACKET_FORMAT:?} packet format"
            )));
        }
        if map.get("version").and_then(Value::as_u64) != Some(DATA_PACKET_VERSION) {
            return Err(error(format!(
                "unsupported data packet version: {:?}",
                map.get("version")
            )));
        }
        let items = map
            .get("items")
            .and_then(Value::as_array)
            .ok_or_else(|| error("data packet items must be an array"))?;
        Ok(Self {
            items: items
                .iter()
                .map(WorkflowDataItem::from_value)
                .collect::<Result<_>>()?,
        })
    }

    /// Wrap an arbitrary legacy JSON value as one item. A marked packet is parsed.
    pub fn from_legacy(value: &Value) -> Result<Self> {
        if is_data_packet(value) {
            return Self::from_value(value);
        }
        Ok(Self {
            items: vec![WorkflowDataItem {
                json: value.clone(),
                binary: None,
                paired: vec![],
                lineage: vec![],
            }],
        })
    }

    /// Adapt an array whose elements already represent separate workflow items.
    pub fn from_legacy_items(value: &Value) -> Result<Self> {
        let values = value
            .as_array()
            .ok_or_else(|| error("legacy item sequence must be an array"))?;
        Ok(Self {
            items: values
                .iter()
                .cloned()
                .map(|json| WorkflowDataItem {
                    json,
                    binary: None,
                    paired: vec![],
                    lineage: vec![],
                })
                .collect(),
        })
    }

    pub fn coerce(value: &Value) -> Result<Self> {
        Self::from_legacy(value)
    }

    pub fn to_value(&self) -> Value {
        json!({"format": DATA_PACKET_FORMAT, "version": DATA_PACKET_VERSION, "items": self.items.iter().map(WorkflowDataItem::to_value).collect::<Vec<_>>()})
    }

    pub fn to_legacy(&self) -> Value {
        if self.items.len() == 1 {
            self.items[0].json.clone()
        } else {
            Value::Array(self.items.iter().map(|item| item.json.clone()).collect())
        }
    }
}

/// Matches only a structurally marked envelope; full validation happens in `from_value`.
pub fn is_data_packet(value: &Value) -> bool {
    let Some(map) = value.as_object() else {
        return false;
    };
    let version = map.get("version");
    map.get("format").and_then(Value::as_str) == Some(DATA_PACKET_FORMAT)
        && (version.and_then(Value::as_u64) == Some(DATA_PACKET_VERSION)
            || version == Some(&Value::Bool(true)))
        && map
            .get("items")
            .and_then(Value::as_array)
            .is_some_and(|items| {
                items
                    .iter()
                    .all(|item| item.as_object().is_some_and(|map| map.contains_key("json")))
            })
}

pub fn adapt_legacy_value(value: &Value) -> Result<WorkflowDataPacket> {
    WorkflowDataPacket::from_legacy(value)
}
pub fn adapt_data_packet(value: &Value) -> Result<WorkflowDataPacket> {
    WorkflowDataPacket::coerce(value)
}
pub fn packet_to_legacy(value: &Value) -> Result<Value> {
    Ok(WorkflowDataPacket::from_value(value)?.to_legacy())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn legacy_shapes_and_explicit_items_are_distinct() {
        let old = json!({"items": [1], "kind": "ordinary-config"});
        assert!(!is_data_packet(&old));
        assert_eq!(WorkflowDataPacket::coerce(&old).unwrap().to_legacy(), old);
        assert_eq!(
            WorkflowDataPacket::from_legacy(&json!([1, 2]))
                .unwrap()
                .items
                .len(),
            1
        );
        assert_eq!(
            WorkflowDataPacket::from_legacy_items(&json!([1, 2]))
                .unwrap()
                .items
                .len(),
            2
        );
        assert_eq!(
            WorkflowDataPacket::from_legacy_items(&json!([]))
                .unwrap()
                .to_legacy(),
            json!([])
        );
        assert!(WorkflowDataPacket::from_legacy_items(&json!({})).is_err());
    }

    #[test]
    fn canonical_packet_round_trips_references_pairing_and_lineage() {
        let packet = json!({"format": DATA_PACKET_FORMAT, "version": 1, "items": [{
            "json": {"answer": 1}, "binary": {"id": "att-1", "mime_type": "image/png", "size": 12},
            "paired": [{"item": 0}], "lineage": ["run-1", "node-a"]
        }]});
        let parsed = WorkflowDataPacket::from_value(&packet).unwrap();
        assert_eq!(parsed.to_value(), packet);
        assert_eq!(parsed.to_legacy(), json!({"answer": 1}));
        assert_eq!(packet_to_legacy(&packet).unwrap(), json!({"answer": 1}));
    }

    #[test]
    fn references_accept_aliases_and_reject_inline_data_or_unsafe_locators() {
        assert_eq!(
            AttachmentRef::from_value(&json!({"ref": "attachment://att", "name": "x"}))
                .unwrap()
                .to_value(),
            json!({"id": "att", "filename": "x", "uri": "attachment://att"})
        );
        for bad in [
            json!({"id":"att","content":"inline"}),
            json!({"id":"att","data":"aGVsbG8="}),
            json!({"id":"att","uri":"data:text/plain;base64,SGk="}),
            json!({"id":"att","uri":"workspace://x"}),
            json!({"id":"att","uri":"attachment://other"}),
            json!({"id":"a b"}),
            json!({"id":"att","size":true}),
            json!({"id":"att","metadata":{"x":1},"unknown":1}),
        ] {
            assert!(AttachmentRef::from_value(&bad).is_err(), "{bad}");
        }
        assert_eq!(
            ArtifactRef::from_value(
                &json!({"id":"artifact-1","uri":"workspace://out/result.json"})
            )
            .unwrap()
            .to_value(),
            json!({"artifact_id":"artifact-1","uri":"workspace://out/result.json"})
        );
        for bad in [
            json!({"artifact_id":"a","path":"C:/secret.bin"}),
            json!({"artifact_id":"a","bytes":[1]}),
            json!({"artifact_id":"a","uri":"data:text/plain,hi"}),
            json!({"artifact_id":"a","size":-1}),
        ] {
            assert!(ArtifactRef::from_value(&bad).is_err(), "{bad}");
        }
    }

    #[test]
    fn malformed_items_and_envelopes_are_rejected() {
        for bad in [
            json!({"format":DATA_PACKET_FORMAT,"version":true,"items":[]}),
            json!({"format":DATA_PACKET_FORMAT,"version":2,"items":[]}),
            json!({"format":DATA_PACKET_FORMAT,"version":1,"items":{}}),
            json!({"format":DATA_PACKET_FORMAT,"version":1,"items":[{"json":1,"extra":0}]}),
            json!({"format":DATA_PACKET_FORMAT,"version":1,"items":[{"json":1,"binary":{"id":"a","payload":"x"}}]}),
        ] {
            assert!(WorkflowDataPacket::from_value(&bad).is_err(), "{bad}");
        }
        assert!(WorkflowDataItem::from_value(&json!({"json":1,"paired":3})).is_err());
        assert!(WorkflowDataItem::from_value(&json!({"json":1,"lineage":[""]})).is_err());
        assert_eq!(
            WorkflowDataItem::from_value(
                &json!({"json":null,"paired_item":{"item":0},"lineage":"run"})
            )
            .unwrap()
            .to_value(),
            json!({"json":null,"paired":[{"item":0}],"lineage":["run"]})
        );
    }

    #[test]
    fn json_boundary_rejects_nonfinite_numbers_and_copies_nested_values() {
        assert!(serde_json::from_str::<Value>("NaN").is_err());
        assert!(serde_json::from_str::<Value>("Infinity").is_err());
        let mut input = json!({"json": {"nested": [1]}, "binary": {"id": "att", "metadata": {"labels": ["first"]}}});
        let item = WorkflowDataItem::from_value(&input).unwrap();
        input["json"]["nested"][0] = json!(99);
        input["binary"]["metadata"]["labels"][0] = json!("changed");
        assert_eq!(item.json, json!({"nested": [1]}));
        assert_eq!(item.binary.unwrap().metadata["labels"], json!(["first"]));
    }
}
