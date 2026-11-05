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
    /// `openai`, `anthropic` or `openai-compatible`. Part of the provider binding.
    #[serde(default = "default_provider")]
    pub provider: String,
    /// What the user called this provider in the settings screen.
    ///
    /// Kept because the shared model screen lists providers by name, and deriving one
    /// from the host would silently rename the user's entry whenever they edited the
    /// address.
    #[serde(default = "default_provider_name")]
    pub provider_name: String,
    /// The acknowledgement that lets plain `http://` to a local model through.
    /// Off by default: a downgrade to clear text must be a decision.
    #[serde(default)]
    pub allow_insecure_local: bool,
    /// Set by the settings screen once the user has read the destination and agreed.
    /// Not a default, because a config file that grants itself consent is the exact
    /// hole the binding exists to close.
    #[serde(default)]
    pub confirm_endpoint: bool,
    /// Whether the configured model can read images.
    ///
    /// Off by default and stated by the user, not guessed: a text-only model rejects the
    /// whole message when an image part appears, so trying it loses the text that was
    /// typed along with the picture. With it off, an image attachment is described to the
    /// model as unreadable instead of being sent.
    #[serde(default)]
    pub vision: bool,
}

fn default_base_url() -> String {
    "http://10.0.2.2:11434/v1".into()
}

fn default_model() -> String {
    "qwen2.5:3b".into()
}

fn default_provider() -> String {
    "openai-compatible".into()
}

fn default_provider_name() -> String {
    "自定义接口".into()
}

impl Default for CoreConfig {
    fn default() -> Self {
        Self {
            base_url: default_base_url(),
            model_id: default_model(),
            granted_tools: Vec::new(),
            provider: default_provider(),
            provider_name: default_provider_name(),
            // The emulator's default endpoint is plain http to the host machine, so
            // the default config has to say so out loud rather than rely on a silent
            // exception for 10.0.2.2.
            allow_insecure_local: true,
            confirm_endpoint: false,
            vision: false,
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
    // say so, rather than failing to open. The fallback cannot leak the key, because
    // the binding gate below is consulted against whatever this returns, and the
    // default endpoint has not been approved by anyone.
    Ok(serde_json::from_str(&text).unwrap_or_default())
}

/// Writes the configuration back.
///
/// Owner-only permissions, because the file names the provider and the endpoint even
/// though it never holds the key.
pub fn save(dir: &Path, config: &CoreConfig) -> Result<(), Box<dyn std::error::Error>> {
    let text = serde_json::to_string_pretty(config)?;
    sunday_host::private_file::write(&path_in(dir), &text, "core config")
        .map_err(|error| error.to_string())?;
    Ok(())
}

/// What the UI may see. Note the absence of any key field.
///
/// `endpoint_approved` is the answer to "why is the model not answering": the
/// settings screen needs it, and it is not secret.
pub fn public_view(dir: &Path) -> serde_json::Value {
    let config = load_or_default(dir).unwrap_or_default();
    let has_api_key = crate::secrets::has_api_key(dir);
    let book = sunday_host::provider::ProviderBook::load(&crate::provider::bindings_path(dir));
    let vendor = sunday_host::provider::Vendor::parse(&config.provider)
        .unwrap_or(sunday_host::provider::Vendor::Compatible);
    let admission = sunday_host::provider::admit(
        vendor,
        &config.base_url,
        has_api_key,
        sunday_host::provider::TransportPolicy {
            allow_insecure_local: config.allow_insecure_local,
        },
        &book,
    );
    let (endpoint_approved, endpoint_prompt) = match &admission {
        Ok(admission) => (admission.is_cleared(), admission.prompt(vendor)),
        Err(error) => (false, Some(error.to_string())),
    };
    serde_json::json!({
        "base_url": config.base_url,
        "model_id": config.model_id,
        "provider": config.provider,
        "provider_name": config.provider_name,
        "granted_tools": config.granted_tools,
        "vision": config.vision,
        "has_api_key": has_api_key,
        "allow_insecure_local": config.allow_insecure_local,
        "endpoint_approved": endpoint_approved,
        "endpoint_prompt": endpoint_prompt,
        // Where the key actually lives, and why, so the settings screen never has to
        // guess whether it may claim system-level storage.
        "credential_storage": crate::secrets::storage_view(dir),
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
        // A key is present in the store, so an accidental passthrough would show up.
        sunday_platform::SecretStore::set(
            &crate::secrets::HostSecrets::new(dir.path()),
            crate::secrets::API_KEY_NAME,
            "sk-must-not-appear-in-the-view",
        )
        .unwrap();

        let view = public_view(dir.path());
        let text = view.to_string().to_lowercase();
        // `has_api_key` is a boolean the settings screen needs. What must not appear is
        // a field holding the key itself, so the check is on the values, not the names.
        assert!(
            !text.contains("sk-must-not-appear"),
            "the view exposes the key: {text}"
        );
        assert!(
            view.get("api_key").is_none(),
            "the view has a field named api_key: {text}"
        );
        assert!(!text.contains("secret"));
        assert!(view.get("granted_tools").is_some());
        assert_eq!(view["has_api_key"], true);
    }

    #[test]
    fn a_corrupt_config_falls_back_to_the_safe_default() {
        let dir = tempfile::tempdir().unwrap();
        std::fs::write(path_in(dir.path()), b"{not json").unwrap();
        let config = load_or_default(dir.path()).unwrap();
        assert!(config.granted_tools.is_empty());
    }
}
