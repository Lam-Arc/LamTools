//! Model configuration, written where the guest reads it.
//!
//! user:"配置模型并进行真实对话"+(手机上第一次打开必须能填地址、模型和密钥，
//! 存进 Core 自己读的那份配置里，而不是宿主自造一套设置)。
//!
//! The guest core reads `.lam/core/config/{providers,models}/*.jsonc` and its own
//! loader decides what is valid. Writing the same files means there is one source of
//! truth, and a file the desktop app would also understand: the phone is running the
//! same core, so it must be configurable the same way.
//!
//! The key is written but never read back. `model_config` reports whether one exists,
//! which is all the settings screen needs to show the truth.

use std::path::{Path, PathBuf};

use serde_json::{json, Value};
use tauri::State;

use crate::HostState;

/// Where the guest's user-level config lives inside the installed rootfs.
fn config_dir(state: &HostState) -> PathBuf {
    crate::runtime::path_of(&state.inner.app)
        .join("rootfs/root/.sunday/core/config")
}

fn provider_id(base_url: &str) -> String {
    // Stable, readable, and derived: re-saving the same endpoint overwrites its file
    // instead of accumulating one entry per save.
    let host = base_url
        .split("//")
        .nth(1)
        .unwrap_or(base_url)
        .split('/')
        .next()
        .unwrap_or("provider");
    let cleaned: String = host
        .chars()
        .map(|ch| if ch.is_ascii_alphanumeric() || ch == '.' || ch == '-' { ch } else { '-' })
        .collect();
    format!("android-{cleaned}")
}

/// The settings screen's view: what is configured, and whether a key is present.
#[tauri::command]
pub fn model_config(state: State<'_, HostState>) -> Value {
    let dir = config_dir(&state);
    let providers = read_all(&dir.join("providers"));
    let models = read_all(&dir.join("models"));
    let provider = providers
        .iter()
        .find(|item| item.get("is_default").and_then(Value::as_bool).unwrap_or(false))
        .or_else(|| providers.first());
    let model = models
        .iter()
        .find(|item| item.get("is_default").and_then(Value::as_bool).unwrap_or(false))
        .or_else(|| models.first());
    json!({
        "baseUrl": provider.and_then(|item| item.get("base_url")).and_then(Value::as_str).unwrap_or(""),
        "providerName": provider.and_then(|item| item.get("name")).and_then(Value::as_str).unwrap_or(""),
        "hasKey": provider
            .and_then(|item| item.get("api_key"))
            .and_then(Value::as_str)
            .map(|key| !key.trim().is_empty())
            .unwrap_or(false),
        "modelId": model.and_then(|item| item.get("model_id")).and_then(Value::as_str).unwrap_or(""),
        "displayName": model.and_then(|item| item.get("display_name")).and_then(Value::as_str).unwrap_or(""),
        "providerCount": providers.len(),
        "modelCount": models.len(),
    })
}

/// Writes one provider and one model, both default.
///
/// Replacing the catalogue rather than appending to it is deliberate on a phone: the
/// app has one endpoint, and a list of half-configured leftovers is a support problem.
/// The desktop app remains the place to keep several providers.
#[tauri::command]
pub fn configure_model(
    state: State<'_, HostState>,
    base_url: String,
    model_id: String,
    api_key: Option<String>,
    display_name: Option<String>,
) -> Result<Value, String> {
    let base_url = base_url.trim().trim_end_matches('/').to_owned();
    let model_id = model_id.trim().to_owned();
    if base_url.is_empty() {
        return Err("base_url is required".into());
    }
    if model_id.is_empty() {
        return Err("model_id is required".into());
    }
    if !(base_url.starts_with("http://") || base_url.starts_with("https://")) {
        return Err("base_url must start with http:// or https://".into());
    }

    let dir = config_dir(&state);
    let providers_dir = dir.join("providers");
    let models_dir = dir.join("models");
    std::fs::create_dir_all(&providers_dir).map_err(|error| error.to_string())?;
    std::fs::create_dir_all(&models_dir).map_err(|error| error.to_string())?;

    let previous_key = read_all(&providers_dir)
        .into_iter()
        .find_map(|item| item.get("api_key").and_then(Value::as_str).map(str::to_owned))
        .unwrap_or_default();
    let key = api_key
        .map(|value| value.trim().to_owned())
        .filter(|value| !value.is_empty())
        .unwrap_or(previous_key);
    if key.is_empty() {
        return Err("an API key is required the first time this endpoint is configured".into());
    }

    let id = provider_id(&base_url);
    let label = display_name
        .map(|value| value.trim().to_owned())
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| model_id.clone());

    let provider = json!({
        "id": id,
        "name": "Android endpoint",
        "api_type": "openai",
        "base_url": base_url,
        "api_key": key,
        "is_default": true,
        "notes": "",
        "adapter_profile_id": "openai-chat",
    });
    let model = json!({
        "id": format!("{id}-{model_id}"),
        "model_id": model_id,
        "display_name": label,
        "provider": "Android endpoint",
        "context_window": 128000,
        "max_output_tokens": 8192,
        "temperature": 0.7,
        "thinking": { "supported": false, "budget": 0 },
        "adapter_profile_id": "openai-chat",
        "capability": "text",
        "notes": "",
        "is_default": true,
        "provider_id": id,
    });

    // Clear previous entries first: two defaults is a state the loader resolves by
    // file order, which is not something a settings screen should depend on.
    clear_json(&providers_dir)?;
    clear_json(&models_dir)?;
    write_json(&providers_dir.join(format!("{id}.jsonc")), &provider)?;
    write_json(&models_dir.join(format!("{id}.jsonc")), &model)?;

    Ok(json!({ "saved": true, "providerId": id, "modelId": model_id }))
}

/// Runtime facts for the settings/diagnostics panel.
#[tauri::command]
pub fn runtime_settings(state: State<'_, HostState>) -> Value {
    let status = state.inner.runtime.status();
    json!({
        "status": serde_json::to_value(&status).unwrap_or_else(|_| json!({})),
        "installed": crate::runtime::is_installed(&state.inner.app),
        "workRoot": crate::runtime::GUEST_WORK_ROOT,
        "log": crate::runtime::read_log_tail(&state.inner.app, 60),
    })
}

fn read_all(dir: &Path) -> Vec<Value> {
    let Ok(entries) = std::fs::read_dir(dir) else {
        return Vec::new();
    };
    let mut files: Vec<PathBuf> = entries
        .filter_map(|entry| entry.ok())
        .map(|entry| entry.path())
        .filter(|path| path.extension().and_then(|value| value.to_str()) == Some("jsonc"))
        .collect();
    files.sort();
    files
        .into_iter()
        .filter_map(|path| std::fs::read_to_string(path).ok())
        .filter_map(|text| serde_json::from_str::<Value>(&text).ok())
        .collect()
}

fn clear_json(dir: &Path) -> Result<(), String> {
    let entries = std::fs::read_dir(dir).map_err(|error| error.to_string())?;
    for entry in entries.flatten() {
        let path = entry.path();
        if path.extension().and_then(|value| value.to_str()) == Some("jsonc") {
            std::fs::remove_file(&path).map_err(|error| error.to_string())?;
        }
    }
    Ok(())
}

fn write_json(path: &Path, value: &Value) -> Result<(), String> {
    let text = serde_json::to_string_pretty(value).map_err(|error| error.to_string())?;
    std::fs::write(path, text).map_err(|error| format!("cannot write {}: {error}", path.display()))
}
