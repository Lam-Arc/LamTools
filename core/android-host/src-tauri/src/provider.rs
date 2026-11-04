//! Which model may talk to which endpoint.
//!
//! The decision itself lives in `sunday_host::provider`, next to the endpoint parsing
//! and the binding file. This is the Android host's use of it, plus the fallback the
//! UI needs: when an endpoint has not been approved, the honest thing is a model that
//! refuses every request with the reason, not a request that quietly leaves anyway.

use std::path::{Path, PathBuf};
use std::sync::Arc;

use sunday_host::provider::{self, Admission, ProviderBook, TransportPolicy, Vendor};
use sunday_protocol::{CoreError, Model, ModelDelta, ModelRequest, ModelTurn};

pub fn bindings_path(dir: &Path) -> PathBuf {
    dir.join(provider::BINDINGS_FILE)
}

/// The model this configuration is allowed to use.
///
/// Returns `Blocked` rather than an error when the endpoint is unapproved, because a
/// failed startup hides the reason. A blocked model answers every turn with the
/// prompt a settings screen should show.
pub fn build_model(
    dir: &Path,
    config: &crate::config::CoreConfig,
) -> Result<Arc<dyn Model>, CoreError> {
    // A scripted model never leaves the device, so no key and no endpoint is involved.
    if config.model_id.starts_with("scripted") {
        return Ok(Arc::new(sunday_host::runner::scripted_model(
            &config.model_id,
        )?));
    }

    let vendor = match Vendor::parse(&config.provider) {
        Some(vendor) => vendor,
        None => {
            return Ok(Arc::new(Blocked::new(format!(
                "unknown provider {:?}: use openai, anthropic or openai-compatible",
                config.provider
            ))))
        }
    };

    // A stored key that cannot be decrypted is a failure to report, not an empty key.
    // Treating it as absent would present the endpoint as keyless and hide the cause
    // until the provider answered with a 401.
    let api_key = match crate::secrets::read_api_key(dir) {
        Ok(value) => value,
        Err(error) => {
            return Ok(Arc::new(Blocked::new(format!(
                "the stored API key cannot be read: {error}"
            ))))
        }
    };
    let key_present = !api_key.trim().is_empty();
    let path = bindings_path(dir);
    let mut book = ProviderBook::load(&path);
    let transport = TransportPolicy {
        allow_insecure_local: config.allow_insecure_local,
    };

    let admission = match provider::admit(vendor, &config.base_url, key_present, transport, &book) {
        Ok(admission) => admission,
        Err(error) => return Ok(Arc::new(Blocked::new(error.to_string()))),
    };

    if let Admission::NeedsApproval { endpoint, .. } = &admission {
        if !config.confirm_endpoint {
            let prompt = admission
                .prompt(vendor)
                .unwrap_or_else(|| "this endpoint has not been approved".into());
            return Ok(Arc::new(Blocked::new(prompt)));
        }
        book.approve(vendor, endpoint);
        book.save(&path)?;
    }

    // The normalised form, never the raw string from the config file.
    let base_url = admission.endpoint().base_url();
    let client = match vendor {
        Vendor::Anthropic => {
            sunday_llm::LlmClient::new(sunday_llm::ProviderConfig::anthropic(base_url, api_key))?
        }
        Vendor::OpenAi | Vendor::Compatible => {
            sunday_llm::LlmClient::new(sunday_llm::ProviderConfig::openai(base_url, api_key))?
        }
    };
    Ok(Arc::new(client))
}

/// A model that refuses every request, with the reason.
struct Blocked {
    reason: String,
}

impl Blocked {
    fn new(reason: String) -> Self {
        Self { reason }
    }
}

#[async_trait::async_trait]
impl Model for Blocked {
    async fn stream(
        &self,
        _request: ModelRequest,
        _sink: &mut (dyn FnMut(ModelDelta) + Send),
    ) -> Result<ModelTurn, CoreError> {
        // A permission failure, not a transport one: retrying it would be wrong, and a
        // retry loop is exactly what would eventually send something.
        Err(CoreError::PermissionDenied {
            resource: self.reason.clone(),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn config(base_url: &str, confirm: bool) -> crate::config::CoreConfig {
        config_as("openai-compatible", base_url, confirm)
    }

    fn config_as(provider: &str, base_url: &str, confirm: bool) -> crate::config::CoreConfig {
        crate::config::CoreConfig {
            base_url: base_url.into(),
            model_id: "qwen2.5:3b".into(),
            granted_tools: Vec::new(),
            provider: provider.into(),
            provider_name: "test".into(),
            allow_insecure_local: true,
            confirm_endpoint: confirm,
        }
    }

    /// With no key and a local endpoint, nothing needs approving.
    #[tokio::test]
    async fn a_keyless_local_endpoint_builds_a_client() {
        let dir = tempfile::tempdir().unwrap();
        let model = build_model(dir.path(), &config("http://127.0.0.1:11434/v1", false)).unwrap();
        assert!(model.stream(request(), &mut |_| {}).await.is_err());
    }

    /// A hosted vendor with no key must not produce a client that would send one.
    ///
    /// The vendor has to be the hosted one: `openai-compatible` is allowed to be
    /// keyless, and configuring it here would build a real client and make a real
    /// request, which is both the wrong test and a network call from a unit test.
    #[tokio::test]
    async fn a_hosted_vendor_without_a_key_is_blocked() {
        let dir = tempfile::tempdir().unwrap();
        let model = build_model(
            dir.path(),
            &config_as("openai", "https://api.openai.com/v1", false),
        )
        .unwrap();
        let error = model.stream(request(), &mut |_| {}).await.unwrap_err();
        match error {
            CoreError::PermissionDenied { resource } => {
                assert!(resource.contains("API key"), "{resource}");
            }
            other => panic!("expected a permission failure, got {other:?}"),
        }
    }

    /// Plain http to a public host must never build a client, approval or not.
    #[tokio::test]
    async fn plain_http_to_a_public_host_is_blocked() {
        let dir = tempfile::tempdir().unwrap();
        let model = build_model(dir.path(), &config("http://api.openai.com/v1", true)).unwrap();
        let error = model.stream(request(), &mut |_| {}).await.unwrap_err();
        assert!(
            matches!(error, CoreError::PermissionDenied { .. }),
            "{error:?}"
        );
    }

    /// Changing the address after approval blocks the key until it is approved again.
    #[tokio::test]
    async fn a_changed_endpoint_is_blocked_until_it_is_confirmed() {
        let dir = tempfile::tempdir().unwrap();
        sunday_platform::SecretStore::set(
            &crate::secrets::HostSecrets::new(dir.path()),
            crate::secrets::API_KEY_NAME,
            "sk-test-0123456789",
        )
        .unwrap();

        // First approval, explicitly given.
        build_model(dir.path(), &config("https://api.openai.com/v1", true)).unwrap();

        // The config now points elsewhere, and nothing was confirmed this time.
        let model = build_model(
            dir.path(),
            &config("https://collector.example.net/v1", false),
        )
        .unwrap();
        let error = model.stream(request(), &mut |_| {}).await.unwrap_err();
        match error {
            CoreError::PermissionDenied { resource } => {
                assert!(resource.contains("collector.example.net"), "{resource}");
                assert!(!resource.contains("sk-test"), "the prompt leaked the key");
            }
            other => panic!("expected a permission failure, got {other:?}"),
        }
    }

    fn request() -> ModelRequest {
        ModelRequest {
            model_id: "m".into(),
            messages: Vec::new(),
            tools: Vec::new(),
            temperature: None,
            max_output_tokens: None,
            cancel: Default::default(),
        }
    }
}
