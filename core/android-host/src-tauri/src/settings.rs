//! The settings surface: what the model screen may read and what it may change.
//!
//! Two rules run through every command here.
//!
//! **An endpoint change invalidates the approval.** Writing a new address through this
//! API resets `confirm_endpoint`, so the screen cannot approve a destination on the
//! user's behalf by editing the field that says it was approved. The user has to press
//! the approval button again, having seen the new host.
//!
//! **The key is never returned.** Writes go one way. The screen learns whether a key
//! exists and where it is stored, which is everything it needs to show the truth and
//! nothing that would leak if the webview were inspected.
//!
//! The logic functions and the commands have different names on purpose: a Tauri command
//! is a protocol entry point, and letting the two share a name makes the call graph read
//! as if the network surface were the behaviour.

use std::sync::Arc;

use serde::Deserialize;
use sunday_host::provider::{self, ProviderBook, TransportPolicy, Vendor};
use sunday_platform::SecretStore;
use tauri::State;

use crate::config;
use crate::secrets::{self, HostSecrets};
use crate::CoreState;

#[derive(Clone, Debug, Default, Deserialize)]
#[serde(default)]
pub struct ModelPatch {
    pub provider: Option<String>,
    pub base_url: Option<String>,
    pub model_id: Option<String>,
    pub allow_insecure_local: Option<bool>,
    /// Whether the model can read images. Stated by the user, because a wrong guess
    /// either loses an image or loses the whole message it was attached to.
    pub vision: Option<bool>,
}

fn vendor_for(config: &config::CoreConfig) -> Result<Vendor, String> {
    Vendor::parse(&config.provider).ok_or_else(|| {
        format!(
            "unknown provider {:?}: use openai, anthropic or openai-compatible",
            config.provider
        )
    })
}

fn transport_for(config: &config::CoreConfig) -> TransportPolicy {
    TransportPolicy {
        allow_insecure_local: config.allow_insecure_local,
    }
}

fn fingerprint_of(config: &config::CoreConfig, dir: &std::path::Path) -> Result<String, String> {
    let vendor = vendor_for(config)?;
    let book = ProviderBook::load(&crate::provider::bindings_path(dir));
    provider::admit(
        vendor,
        &config.base_url,
        secrets::has_api_key(dir),
        transport_for(config),
        &book,
    )
    .map(|admission| admission.endpoint().fingerprint().to_owned())
    .map_err(|error| error.to_string())
}

/// Applies a patch, validates it, and writes it back.
pub fn apply_patch(state: &CoreState, patch: ModelPatch) -> Result<serde_json::Value, String> {
    let mut next = config::load_or_default(&state.data_dir).map_err(|error| error.to_string())?;
    let previous_fingerprint = fingerprint_of(&next, &state.data_dir)?;
    let previous_provider = next.provider.clone();
    let previous_model = next.model_id.clone();

    if let Some(provider) = patch.provider {
        next.provider = provider;
    }
    if let Some(url) = patch.base_url {
        next.base_url = url.trim().to_owned();
    }
    if let Some(model) = patch.model_id {
        next.model_id = model.trim().to_owned();
    }
    if let Some(allow) = patch.allow_insecure_local {
        next.allow_insecure_local = allow;
    }
    let vision_changed = match patch.vision {
        Some(vision) => {
            let changed = next.vision != vision;
            next.vision = vision;
            changed
        }
        None => false,
    };

    // Validate before writing, so a typo cannot leave the app unable to start.
    let next_fingerprint = fingerprint_of(&next, &state.data_dir)?;

    let moved = previous_fingerprint != next_fingerprint
        || previous_provider != next.provider
        || previous_model != next.model_id;
    if moved {
        // Whatever was approved was approved for a different place.
        next.confirm_endpoint = false;
    }

    config::save(&state.data_dir, &next).map_err(|error| error.to_string())?;

    // The image setting is read when a turn starts, so it takes effect immediately;
    // only the provider binding needs a restart.
    if vision_changed {
        state.runner.set_images_allowed(next.vision);
    }
    let mut view = config::public_view(&state.data_dir);
    view["restart_required"] = serde_json::json!(moved);
    view["vision_applied_live"] = serde_json::json!(vision_changed);
    Ok(view)
}

/// Records that the user approved the endpoint currently configured.
pub fn approve(state: &CoreState) -> Result<serde_json::Value, String> {
    let mut next = config::load_or_default(&state.data_dir).map_err(|error| error.to_string())?;
    let vendor = vendor_for(&next)?;
    let path = crate::provider::bindings_path(&state.data_dir);
    let mut book = ProviderBook::load(&path);

    let admission = provider::admit(
        vendor,
        &next.base_url,
        secrets::has_api_key(&state.data_dir),
        transport_for(&next),
        &book,
    )
    .map_err(|error| error.to_string())?;

    book.approve(vendor, admission.endpoint());
    book.save(&path).map_err(|error| error.to_string())?;

    next.confirm_endpoint = true;
    config::save(&state.data_dir, &next).map_err(|error| error.to_string())?;

    let mut view = config::public_view(&state.data_dir);
    view["restart_required"] = serde_json::json!(true);
    Ok(view)
}

/// Stores a key. Refuses rather than degrading when the keystore is unusable.
pub fn store_key(state: &CoreState, key: &str) -> Result<serde_json::Value, String> {
    let trimmed = key.trim();
    if trimmed.is_empty() {
        return Err("the key is empty".to_owned());
    }
    HostSecrets::new(&state.data_dir)
        .set(secrets::API_KEY_NAME, trimmed)
        .map_err(|error| error.to_string())?;

    let mut next = config::load_or_default(&state.data_dir).map_err(|error| error.to_string())?;
    // A new key for the same endpoint still has to be approved: the binding is about
    // where the credential goes, and this is a different credential.
    next.confirm_endpoint = false;
    config::save(&state.data_dir, &next).map_err(|error| error.to_string())?;

    let mut view = config::public_view(&state.data_dir);
    view["restart_required"] = serde_json::json!(true);
    Ok(view)
}

pub fn forget_key(state: &CoreState) -> Result<serde_json::Value, String> {
    HostSecrets::new(&state.data_dir)
        .delete(secrets::API_KEY_NAME)
        .map_err(|error| error.to_string())?;
    let mut next = config::load_or_default(&state.data_dir).map_err(|error| error.to_string())?;
    next.confirm_endpoint = false;
    config::save(&state.data_dir, &next).map_err(|error| error.to_string())?;

    let mut view = config::public_view(&state.data_dir);
    view["restart_required"] = serde_json::json!(true);
    Ok(view)
}

/// Every tool the core can run, with what it may do and whether it is pre-approved.
pub fn catalog(state: &CoreState) -> serde_json::Value {
    let granted = state.runner.policy_snapshot().granted;
    let tools: Vec<serde_json::Value> = state
        .runner
        .tool_catalog()
        .into_iter()
        .map(|tool| {
            serde_json::json!({
                "id": tool.id,
                "description": tool.description,
                "side_effect": match tool.side_effect {
                    sunday_protocol::SideEffect::Pure => "pure",
                    sunday_protocol::SideEffect::Idempotent => "idempotent",
                    sunday_protocol::SideEffect::NonIdempotent => "non-idempotent",
                },
                "permission": match tool.permission {
                    sunday_protocol::Permission::AutoAllow => "auto",
                    sunday_protocol::Permission::AskUser => "ask",
                    sunday_protocol::Permission::HardBlock => "blocked",
                },
                "granted": granted.contains(&tool.id),
            })
        })
        .collect();
    serde_json::json!({ "tools": tools })
}

/// Grants or revokes one tool, for this run and for the next one.
pub fn grant(state: &CoreState, tool_id: &str, granted: bool) -> Result<serde_json::Value, String> {
    let known = state
        .runner
        .tool_catalog()
        .iter()
        .any(|tool| tool.id == tool_id);
    if !known {
        return Err(format!("no such tool: {tool_id}"));
    }

    let mut policy = state.runner.policy_snapshot();
    if granted {
        policy.granted.insert(tool_id.to_owned());
    } else {
        policy.granted.remove(tool_id);
    }
    state.runner.set_policy(policy.clone());

    let mut next = config::load_or_default(&state.data_dir).map_err(|error| error.to_string())?;
    next.granted_tools = policy.granted.iter().cloned().collect();
    next.granted_tools.sort();
    config::save(&state.data_dir, &next).map_err(|error| error.to_string())?;

    // Applied live: the next tool call already sees the new policy.
    Ok(catalog(state))
}

// ---------------------------------------------------------------- commands

#[tauri::command]
pub fn model_config(state: State<'_, Arc<CoreState>>) -> serde_json::Value {
    config::public_view(&state.data_dir)
}

#[tauri::command]
pub fn save_model_config(
    state: State<'_, Arc<CoreState>>,
    patch: ModelPatch,
) -> Result<serde_json::Value, String> {
    apply_patch(&state, patch)
}

#[tauri::command]
pub fn approve_endpoint(state: State<'_, Arc<CoreState>>) -> Result<serde_json::Value, String> {
    approve(&state)
}

#[tauri::command]
pub fn set_api_key(
    state: State<'_, Arc<CoreState>>,
    key: String,
) -> Result<serde_json::Value, String> {
    store_key(&state, &key)
}

#[tauri::command]
pub fn clear_api_key(state: State<'_, Arc<CoreState>>) -> Result<serde_json::Value, String> {
    forget_key(&state)
}

#[tauri::command]
pub fn tool_catalog(state: State<'_, Arc<CoreState>>) -> serde_json::Value {
    catalog(&state)
}

#[tauri::command]
pub fn set_tool_grant(
    state: State<'_, Arc<CoreState>>,
    tool_id: String,
    granted: bool,
) -> Result<serde_json::Value, String> {
    grant(&state, &tool_id, granted)
}
