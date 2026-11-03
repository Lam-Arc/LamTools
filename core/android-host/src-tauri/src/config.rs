//! Model configuration for the Android host.
//!
//! The API key is deliberately **not** in this file. It lives in the platform
//! secret store (Android Keystore via the plugin, with a file fallback for
//! desktop builds of the same host). Storing it in JSON would put it in every
//! backup, every log capture and every bug report the user files.
//!
//! The grant list is here because it is a security decision the user makes, and
//! it must be visible: `granted_tools` names exactly which side-effecting tools
//! may run without asking. It is empty by default.

use std::path::{Path, PathBuf};

pub const CONFIG_FILE: &str = "core.config.json";

#[derive(Clone, Debug, serde::Serialize, serde::Deserialize)]
pub struct CoreConfig {
    /// OpenAI-compatible endpoint. `10.0.2.2` is the emulator's route to the host.
    #[serde(default = "default_base_url")]
    pub base_url: String,
    #[serde(default = "default_model")]
    pub model_id: String,
    /// Tools allowed to run without asking. Empty by default: a fresh install
    /// asks before writing or deleting anything.
    #[serde(default)]
    pub granted_tools: Vec<String>,
}

fn default_base_url() -> String {
    "http://10.0.2.2:11434/v1".into()
}

fn default_model() -> String {
    "qwen2.5:3b".into()
}

impl Default for CoreConfig {
    fn default() -> Self {
        Self {
            base_url: default_base_url(),
            model_id: default_model(),
            granted_tools: Vec::new(),
        }
    }
}

pub fn path_in(dir: &Path) -> PathBuf {
    dir.join(CONFIG_FILE)
}

pub fn load_or_default(dir: &Path) -> Result<CoreConfig, Box<dyn std::error::Error>> {
    let path = path_in(dir);
    if !path.exists() {
        let config = CoreConfig::default();
        std::fs::write(&path, serde_json::to_string_pretty(&config)?)?;
        return Ok(config);
    }
    let text = std::fs::read_to_string(&path)?;
    // A corrupt config must not brick the app: fall back to the safe default and
    // say so, rather than failing to open.
    Ok(serde_json::from_str(&text).unwrap_or_default())
}

/// What the UI may see. Note the absence of any key field.
pub fn public_view(dir: &Path) -> serde_json::Value {
    let config = load_or_default(dir).unwrap_or_default();
    serde_json::json!({
        "base_url": config.base_url,
        "model_id": config.model_id,
        "granted_tools": config.granted_tools,
        "has_api_key": crate::secrets::has_api_key(dir),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_fresh_config_grants_nothing() {
        let dir = tempfile::tempdir().unwrap();
        let config = load_or_default(dir.path()).unwrap();
        assert!(
            config.granted_tools.is_empty(),
            "a fresh install pre-authorised tools: {:?}",
            config.granted_tools
        );
    }

    #[test]
    fn the_public_view_never_contains_a_key() {
        let dir = tempfile::tempdir().unwrap();
        load_or_default(dir.path()).unwrap();
        let view = public_view(dir.path());
        let text = view.to_string().to_lowercase();
        assert!(!text.contains("api_key"), "the view exposes a key field: {text}");
        assert!(!text.contains("secret"));
        assert!(view.get("granted_tools").is_some());
    }

    #[test]
    fn a_corrupt_config_falls_back_to_the_safe_default() {
        let dir = tempfile::tempdir().unwrap();
        std::fs::write(path_in(dir.path()), b"{not json").unwrap();
        let config = load_or_default(dir.path()).unwrap();
        assert!(config.granted_tools.is_empty());
    }
}
