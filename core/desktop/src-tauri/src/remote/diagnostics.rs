use serde_json::Value;

/// Emit one-line, payload-free remote routing diagnostics.  Remote application
/// messages stay encrypted; only identifiers and sizes needed for correlation
/// are recorded.
pub(crate) fn trace(event: &str, fields: Value) {
    let mut object = match fields {
        Value::Object(object) => object,
        _ => serde_json::Map::new(),
    };
    object.insert(
        "component".to_string(),
        Value::String("desktop".to_string()),
    );
    object.insert("event".to_string(), Value::String(event.to_string()));
    eprintln!("[lamtools-remote] {}", Value::Object(object));
}
