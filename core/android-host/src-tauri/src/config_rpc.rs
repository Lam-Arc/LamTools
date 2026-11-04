//! The `config.*` surface the shared settings screen speaks.
//!
//! The desktop app talks to a Python core that keeps a catalog of many providers,
//! many models and model groups. This host keeps exactly one active provider
//! binding, and pretending otherwise would let the screen show four providers while
//! the runner can only ever use one. So the mapping is explicit and honest: the
//! catalog has one provider and one model, every write lands in `core.config.json`
//! plus the platform secret store, and a second provider overwrites the first
//! instead of quietly piling up entries that do nothing.
//!
//! Two rules carried over from `settings.rs`, because a second door must not undo
//! what the first one enforces:
//!
//! * **Changing the endpoint drops its approval.** Writing a new address resets
//!   `confirm_endpoint`; only an explicit probe, where the user pressed "test
//!   connection" having just read the address, sets it again.
//! * **The key never comes back out.** Writes go one way; the screen learns whether
//!   a key exists, never what it is.

use std::time::Duration;

use serde_json::{json, Value};
use sunday_platform::SecretStore;

use crate::{config, secrets, CoreState};

/// The record ids the screen sees. Stable on purpose: the screen stores selections
/// and orderings against them, and a regenerated id would read as "the provider the
/// user configured has disappeared".
pub const PROVIDER_ID: &str = "default";
pub const MODEL_RECORD_ID: &str = "default";
pub const GROUP_ID: &str = "default";

/// Short enough that a wrong address reports itself while the user is still looking
/// at the dialog, long enough for a cold local model server to answer.
const PROBE_TIMEOUT: Duration = Duration::from_secs(8);

/// Handles one `config.*` call, or returns `None` when the method is not ours.
pub async fn handle(
    state: &CoreState,
    method: &str,
    params: &Value,
) -> Option<Result<Value, String>> {
    let outcome = match method {
        "config.providers.list" => read_providers(state),
        "config.providers.status" => read_status(state),
        "config.models.list" => read_models(state),
        "config.model_groups.list" => read_groups(state),
        // Grouping is a desktop convenience: with one model there is nothing to
        // group. Accept the writes and answer with the single group so a screen
        // that saves a group does not report a failure it cannot act on.
        "config.model_group.create"
        | "config.model_group.update"
        | "config.model_group.members.set"
        | "config.model_group.delete" => read_groups(state),
        "config.notices.drain" => Ok(json!({ "notices": [] })),
        "config.models.usage" => Ok(json!({ "usage": {}, "total": {}, "range": params.get("range").cloned().unwrap_or(Value::Null) })),
        "config.provider.create" | "config.provider.update" => write_provider(state, params),
        "config.provider.delete" => delete_provider(state),
        "config.models.upsert" | "config.model.create_with_provider" => write_model(state, params),
        "config.models.set_default" => set_default(state, params),
        "config.models.delete" => delete_model(state, params),
        "config.providers.probe" => probe(state, params).await,
        _ => return None,
    };
    Some(outcome)
}

fn load(state: &CoreState) -> Result<config::CoreConfig, String> {
    config::load_or_default(&state.data_dir).map_err(|error| error.to_string())
}

fn store(state: &CoreState, config: &config::CoreConfig) -> Result<(), String> {
    config::save(&state.data_dir, config).map_err(|error| error.to_string())
}

fn provider_view(state: &CoreState, config: &config::CoreConfig) -> Value {
    json!({
        "id": PROVIDER_ID,
        "name": config.provider_name,
        "api_type": config.provider,
        "base_url": config.base_url,
        "has_api_key": secrets::has_api_key(&state.data_dir),
        "extra": Value::Null,
    })
}

fn model_view(config: &config::CoreConfig) -> Value {
    json!({
        "id": MODEL_RECORD_ID,
        "provider_id": PROVIDER_ID,
        "model_id": config.model_id,
        "display_name": config.model_id,
        "is_default": true,
        "enabled": true,
        "capability": "chat",
        "extra": Value::Null,
    })
}

/// The models list, or nothing at all when the user deleted the last model.
///
/// An empty `model_id` means "no model configured", and the honest answer is an
/// empty list: reporting a placeholder would let the composer believe it can send.
fn models_payload(config: &config::CoreConfig) -> Value {
    if config.model_id.trim().is_empty() {
        return json!({ "models": [], "scene_models": {} });
    }
    json!({
        "models": [model_view(config)],
        "scene_models": { "chat": MODEL_RECORD_ID },
        "default_model_id": MODEL_RECORD_ID,
    })
}

fn read_providers(state: &CoreState) -> Result<Value, String> {
    let config = load(state)?;
    Ok(json!({ "providers": [provider_view(state, &config)] }))
}

/// No probe has run yet, so every state is `unknown` rather than a made-up "ok".
fn read_status(state: &CoreState) -> Result<Value, String> {
    let config = load(state)?;
    Ok(json!({
        "providers": { PROVIDER_ID: unknown_status(&config) },
        "updated_at": "",
    }))
}

fn unknown_status(config: &config::CoreConfig) -> Value {
    json!({
        "state": "unknown",
        "detail": if config.confirm_endpoint { "" } else { "端点尚未验证：打开设置点一次「检测连接」" },
        "latency_ms": 0,
        "http_status": 0,
        "model_count": 0,
        "checked_at": "",
    })
}

fn read_models(state: &CoreState) -> Result<Value, String> {
    let config = load(state)?;
    Ok(models_payload(&config))
}

fn read_groups(state: &CoreState) -> Result<Value, String> {
    let config = load(state)?;
    let members: Vec<&str> = if config.model_id.trim().is_empty() {
        Vec::new()
    } else {
        vec![MODEL_RECORD_ID]
    };
    Ok(json!({
        "groups": [{
            "id": GROUP_ID,
            "name": "默认",
            "model_ids": members,
            "revision": 0,
            "is_system": true,
        }],
        "revision": 0,
    }))
}

/// `openai-compatible` is the only type that accepts an arbitrary base URL, so an
/// unrecognised `api_type` from the screen becomes that rather than an error the
/// user cannot fix from the dialog.
fn normalise_api_type(raw: &str) -> String {
    match raw.trim().to_ascii_lowercase().as_str() {
        "anthropic" | "claude" => "anthropic".into(),
        "openai" => "openai".into(),
        _ => "openai-compatible".into(),
    }
}

fn write_provider(state: &CoreState, params: &Value) -> Result<Value, String> {
    let mut config = load(state)?;
    let text = |key: &str| params.get(key).and_then(Value::as_str).map(str::trim).unwrap_or("");

    let name = text("name");
    if !name.is_empty() {
        config.provider_name = name.to_owned();
    }
    let api_type = text("api_type");
    if !api_type.is_empty() {
        config.provider = normalise_api_type(api_type);
    }
    let base_url = text("base_url");
    if !base_url.is_empty() && base_url != config.base_url {
        config.base_url = base_url.to_owned();
        // A new address is a new destination. The old approval cannot carry over,
        // or editing the field would be a way to approve a host without seeing it.
        config.confirm_endpoint = false;
    }
    // Plain http is only ever allowed to a local server, and the setting is a
    // convenience for the emulator loopback rather than a user-facing switch.
    config.allow_insecure_local = base_url.is_empty() || base_url.starts_with("http://");

    if let Some(key) = params.get("api_key").and_then(Value::as_str) {
        if !key.trim().is_empty() {
            SecretStore::set(
                &crate::secrets::HostSecrets::new(&state.data_dir),
                secrets::API_KEY_NAME,
                key.trim(),
            )
            .map_err(|error| error.to_string())?;
        }
    }

    // A provider added together with its models carries the first one as the model
    // this host will actually use.
    if let Some(models) = params.get("models").and_then(Value::as_array) {
        if let Some(model_id) = models
            .iter()
            .find_map(|model| model.get("model_id").and_then(Value::as_str))
        {
            if !model_id.trim().is_empty() {
                config.model_id = model_id.trim().to_owned();
            }
        }
    }

    store(state, &config)?;
    Ok(json!({
        "provider": provider_view(state, &config),
        "models": models_payload(&config)["models"].clone(),
    }))
}

fn delete_provider(state: &CoreState) -> Result<Value, String> {
    crate::secrets::HostSecrets::new(&state.data_dir)
        .delete(secrets::API_KEY_NAME)
        .map_err(|error| error.to_string())?;
    let mut config = load(state)?;
    config.confirm_endpoint = false;
    store(state, &config)?;
    Ok(json!({ "providers": [provider_view(state, &config)] }))
}

fn write_model(state: &CoreState, params: &Value) -> Result<Value, String> {
    let mut config = load(state)?;
    if let Some(model_id) = params.get("model_id").and_then(Value::as_str) {
        if !model_id.trim().is_empty() {
            config.model_id = model_id.trim().to_owned();
        }
    }
    if let Some(base_url) = params.get("base_url").and_then(Value::as_str) {
        let base_url = base_url.trim();
        if !base_url.is_empty() && base_url != config.base_url {
            config.base_url = base_url.to_owned();
            config.confirm_endpoint = false;
            config.allow_insecure_local = base_url.starts_with("http://");
        }
    }
    store(state, &config)?;
    Ok(models_payload(&config))
}

/// The screen sends the record id, not the model name, when it sets a default.
fn set_default(state: &CoreState, params: &Value) -> Result<Value, String> {
    let config = load(state)?;
    let requested = params.get("model_id").and_then(Value::as_str).unwrap_or("");
    if !requested.is_empty() && requested != MODEL_RECORD_ID && requested != config.model_id {
        return Err(format!(
            "no such model: {requested} (this host serves exactly one configured model)"
        ));
    }
    // Nothing to switch: with a single model the default is that model, and
    // rewriting the config on a no-op would drop the endpoint approval for nothing.
    Ok(models_payload(&config))
}

fn delete_model(state: &CoreState, params: &Value) -> Result<Value, String> {
    let mut config = load(state)?;
    let requested = params.get("model_id").and_then(Value::as_str).unwrap_or("");
    if requested.is_empty() || requested == MODEL_RECORD_ID || requested == config.model_id {
        // Deleting the only model leaves the host with none. That is a real state —
        // the composer then reports it cannot send — so it is written down rather
        // than refused with an error the delete button cannot explain.
        config.model_id = String::new();
        store(state, &config)?;
    }
    Ok(models_payload(&config))
}

/// Really asks the endpoint for its model list.
///
/// `force`/`provider_ids` are accepted and ignored: there is one provider and the
/// probe always performs a request. Answering from a cache would make "test
/// connection" a button that agrees with itself.
async fn probe(state: &CoreState, _params: &Value) -> Result<Value, String> {
    let mut config = load(state)?;
    let api_key = crate::secrets::read_api_key(&state.data_dir).unwrap_or_default();
    let started = std::time::Instant::now();
    let outcome = sunday_llm::list_models(&config.base_url, &api_key, PROBE_TIMEOUT).await;
    let latency = started.elapsed().as_millis() as u64;
    let checked_at = timestamp();

    let status = match outcome {
        Ok(names) => {
            // The user read this address and pressed "test connection", which is the
            // explicit approval the binding gate wants. Only a reachable endpoint
            // earns it.
            config.confirm_endpoint = true;
            store(state, &config)?;
            json!({
                "state": "ok",
                "detail": if names.is_empty() { "端点可达，但没有返回任何模型".to_owned() } else { format!("{} 个模型可用：{}", names.len(), names.join(", ")) },
                "latency_ms": latency,
                "http_status": 200,
                "model_count": names.len(),
                "checked_at": checked_at,
            })
        }
        Err(error) => {
            let message = error.to_string();
            let state_name = if message.contains("api key") || message.contains("401") || message.contains("403") {
                "unauthorized"
            } else if message.contains("cannot reach") {
                "unreachable"
            } else {
                "error"
            };
            json!({
                "state": state_name,
                "detail": message,
                "latency_ms": latency,
                "http_status": 0,
                "model_count": 0,
                "checked_at": checked_at,
            })
        }
    };

    Ok(json!({
        "providers": { PROVIDER_ID: status },
        "updated_at": checked_at,
    }))
}

fn timestamp() -> String {
    // Seconds since the epoch is enough for "when was this checked", and it avoids
    // pulling a date-formatting dependency into the host for one label.
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default();
    format!("{}", now.as_secs())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn config(model_id: &str) -> config::CoreConfig {
        config::CoreConfig {
            model_id: model_id.into(),
            ..config::CoreConfig::default()
        }
    }

    /// The screen must never see an empty model list while a model is configured:
    /// the composer refuses to send, and the reason would look like a core bug.
    #[test]
    fn a_configured_model_shows_up_in_the_list() {
        let payload = models_payload(&config("qwen2.5:3b"));
        assert_eq!(payload["models"][0]["model_id"], "qwen2.5:3b");
        assert_eq!(payload["models"][0]["id"], MODEL_RECORD_ID);
        assert_eq!(payload["scene_models"]["chat"], MODEL_RECORD_ID);
    }

    /// Deleting the last model is a real state, not a crash: the list goes empty so
    /// the composer can say why it will not send.
    #[test]
    fn deleting_the_only_model_leaves_an_empty_catalog() {
        let payload = models_payload(&config(""));
        assert_eq!(payload["models"].as_array().map(Vec::len), Some(0));
        assert!(payload["scene_models"].get("chat").is_none());
    }

    /// A hosted preset that speaks Anthropic must not be sent to an OpenAI wire.
    #[test]
    fn api_types_map_onto_the_three_wires_the_runner_knows() {
        assert_eq!(normalise_api_type("claude"), "anthropic");
        assert_eq!(normalise_api_type("Anthropic"), "anthropic");
        assert_eq!(normalise_api_type("openai"), "openai");
        assert_eq!(normalise_api_type("openai-compatible"), "openai-compatible");
        assert_eq!(normalise_api_type("something-else"), "openai-compatible");
    }

    #[test]
    fn an_unprobed_provider_is_unknown_not_ok() {
        let status = unknown_status(&config("m"));
        assert_eq!(status["state"], "unknown");
        assert!(status["detail"].as_str().unwrap_or("").contains("检测连接"));
    }
}
